# ORM N+1 detection and fixes

N+1: one query loads N parents, then one query per parent loads its children. It hides in templates,
serializers and resolvers. Detect it with query counts in tests; fix it with eager loading or batching;
guard it with a test that fails when the count grows with N.

## The test pattern (any stack)

1. Seed 1 parent with children, count queries for the request.
2. Seed 20 parents, count again.
3. The count must not grow with N (allow a constant). Assert the exact number to catch regressions.

## Django

```python
from django.db import connection
from django.test.utils import CaptureQueriesContext

def test_order_list_queries(client, django_assert_num_queries):      # pytest-django fixture
    OrderFactory.create_batch(20, lines=3)
    with django_assert_num_queries(3):                                 # session, orders, lines
        client.get("/orders/")

with CaptureQueriesContext(connection) as ctx:                         # ad hoc inspection
    list(Order.objects.all())
print(len(ctx.captured_queries), ctx.captured_queries[-1]["sql"])
```

Fixes:

```python
Order.objects.select_related("customer")                   # FK / one-to-one: one JOIN
Order.objects.prefetch_related("lines")                    # reverse FK / M2M: one extra IN query
Order.objects.prefetch_related(Prefetch("lines", queryset=Line.objects.only("id", "sku", "qty")))
Order.objects.annotate(line_count=Count("lines"))          # aggregate instead of len(o.lines.all())
```

`TestCase.assertNumQueries(n)` is the unittest form. django-debug-toolbar shows duplicates per page.

## SQLAlchemy 2.x

```python
from contextlib import contextmanager
from sqlalchemy import event

@contextmanager
def count_queries(engine):              # for AsyncEngine pass engine.sync_engine
    n = 0
    def before(conn, cursor, statement, parameters, context, executemany):
        nonlocal n
        n += 1
    event.listen(engine, "before_cursor_execute", before)
    try:
        yield lambda: n
    finally:
        event.remove(engine, "before_cursor_execute", before)

with count_queries(engine) as count:
    render_orders(session)
assert count() == 2
```

Fixes and guards:

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload, raiseload

stmt = (select(Order)
        .options(joinedload(Order.customer),         # many-to-one: JOIN
                 selectinload(Order.lines),          # one-to-many: second query WHERE order_id IN (...)
                 raiseload("*")))                     # anything else lazy-loaded raises: finds the next N+1
orders = session.scalars(stmt).all()               # add .unique() if joinedload targets a collection
```

`lazy="raise"` on a relationship makes lazy loading an error everywhere (good default for async code,
where lazy loads fail anyway).

## Prisma

```ts
const prisma = new PrismaClient({ log: [{ emit: "event", level: "query" }] });
let queries = 0;
prisma.$on("query", () => { queries++; });

const orders = await prisma.order.findMany({
  where: { tenantId },
  include: { customer: true, lines: { select: { sku: true, qty: true } } },
  take: 50,
});
```

Batch manual lookups: `prisma.customer.findMany({ where: { id: { in: ids } } })` then map by id.
Join-based relation loading (`relationLoadStrategy: "join"`) exists in recent versions; check the
version's docs before relying on it.

## Rails (ActiveRecord)

```ruby
Order.includes(:customer, :lines)       # lets Rails choose preload (separate queries) or eager_load (JOIN)
Order.preload(:lines)                   # always separate IN queries
Order.eager_load(:customer)             # always LEFT OUTER JOIN (needed when filtering on the association)
Order.strict_loading.find(id)           # lazy load raises (Rails 6.1+); config.active_record.strict_loading_by_default
```

The Bullet gem reports N+1 and unused eager loading in development and test.

## Hibernate / JPA / Spring Data

```java
@Query("select o from Order o join fetch o.customer where o.tenantId = :tenantId")
List<Order> findWithCustomer(@Param("tenantId") long tenantId);

@EntityGraph(attributePaths = {"customer", "lines"})
List<Order> findByTenantId(long tenantId);
```

- `@BatchSize(size = 50)` on a collection or `hibernate.default_batch_fetch_size=50` turns N lazy
  loads into N/50 `IN` queries.
- `join fetch` on two collections at once produces a cartesian product (or `MultipleBagFetchException`):
  fetch one collection per query.
- Count queries in tests with `hibernate.generate_statistics=true` and
  `SessionFactory.getStatistics().getPrepareStatementCount()`.
- Keep `spring.jpa.open-in-view=false` so lazy loads cannot happen during view rendering unnoticed.

## GORM (Go)

```go
db.Preload("Lines").Preload("Customer").Where("tenant_id = ?", tid).Find(&orders)   // separate IN queries
db.Joins("Customer").Where("tenant_id = ?", tid).Find(&orders)                      // JOIN for belongs-to
```

Count with a GORM logger or callback (`db.Callback().Query().After("gorm:query").Register(...)`).

## Entity Framework Core

```csharp
var orders = await db.Orders
    .Where(o => o.TenantId == tenantId)
    .Include(o => o.Customer)
    .Include(o => o.Lines)
    .AsSplitQuery()                      // avoid cartesian explosion with several collections
    .ToListAsync();
```

Log SQL with `optionsBuilder.LogTo(Console.WriteLine, LogLevel.Information)` in tests.

## GraphQL: DataLoader

```ts
import DataLoader from "dataloader";

const customerLoader = new DataLoader<string, Customer | null>(async (ids) => {
  const rows = await db.query("SELECT * FROM customers WHERE id = ANY($1)", [ids]);
  const byId = new Map(rows.map((r) => [r.id, r]));
  return ids.map((id) => byId.get(id) ?? null);     // same length and order as ids
});
// create loaders per request (cache is per request, not global)
```

## Raw SQL batching

```sql
SELECT * FROM order_lines WHERE order_id = ANY($1::bigint[]);       -- one query for all parents
SELECT o.id, l.* FROM unnest($1::bigint[]) AS o(id)
CROSS JOIN LATERAL (SELECT * FROM order_lines WHERE order_id = o.id ORDER BY id LIMIT 5) l;  -- top-N per parent
```

## Bulk writes

```python
# psycopg 3
with conn.cursor() as cur, cur.copy("COPY events (tenant_id, kind, payload) FROM STDIN") as copy:
    for row in rows:
        copy.write_row(row)

# multi-row insert via arrays (one round trip, one statement)
cur.execute(
    "INSERT INTO events (tenant_id, kind) SELECT * FROM unnest(%s::bigint[], %s::text[])",
    (tenant_ids, kinds),
)
```

asyncpg: `await conn.copy_records_to_table("events", records=rows, columns=[...])`.
Batch size for row-by-row ORMs: `bulk_create(objs, batch_size=1000)` (Django),
`session.execute(insert(Event), list_of_dicts)` (SQLAlchemy 2.x bulk insert).
