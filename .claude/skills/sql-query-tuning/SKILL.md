---
name: sql-query-tuning
description: "Finding and fixing slow SQL: pg_stat_statements and slow-log triage, reading EXPLAIN ANALYZE plans in PostgreSQL 17/18 and MySQL 8.x, estimate-vs-actual diagnosis, composite/covering/partial/expression/GIN/BRIN index design, sargable rewrites, keyset pagination, ORM N+1 fixes, extended statistics and runtime timeouts. Load when a query or endpoint is slow, a new query needs an index, or reviewing SQL performance."
when_to_use: "An endpoint or job is slow and the database is suspected; EXPLAIN output to interpret ('Sort Method: external merge', 'Rows Removed by Filter', 'Heap Fetches'); a new WHERE/ORDER BY needs an index; OFFSET pagination slows with depth; an ORM issues hundreds of queries per request; 'canceling statement due to statement timeout'; reviewing migrations that add indexes."
---

# SQL query tuning

Measure, read the plan, fix the biggest cause, re-measure. Engine coverage: PostgreSQL 17/18
(primary), MySQL 8.0/8.4, SQLite for local checks.

Scope: general benchmarking statistics live in `performance-optimization`; review-time SQL checks in
`code-review-checklist`; MVCC, isolation and locking in `database-transactions-isolation`; online
index builds and schema changes in `zero-downtime-migrations`.

Deep material:
[diagnostic queries (PostgreSQL, MySQL)](references/diagnostic-queries.md) |
[ORM N+1 detection and fixes](references/orm-n-plus-one.md)

## 1. Triage: total time first

Rank by total time (calls x mean), not by mean: a 2 ms query called 5 million times a day beats a
4 s report run twice.

```sql
-- PostgreSQL: shared_preload_libraries = 'pg_stat_statements'; CREATE EXTENSION pg_stat_statements;
SELECT queryid, calls,
       round(total_exec_time::numeric)            AS total_ms,
       round(mean_exec_time::numeric, 2)          AS mean_ms,
       round(100 * total_exec_time / sum(total_exec_time) OVER (), 1) AS pct,
       rows, shared_blks_hit, shared_blks_read, temp_blks_written,
       left(query, 100)                           AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

```sql
-- MySQL 8: timers are picoseconds
SELECT DIGEST_TEXT, COUNT_STAR,
       ROUND(SUM_TIMER_WAIT / 1e12, 1) AS total_s, ROUND(AVG_TIMER_WAIT / 1e9, 2) AS avg_ms,
       SUM_ROWS_EXAMINED, SUM_ROWS_SENT, SUM_NO_INDEX_USED
FROM performance_schema.events_statements_summary_by_digest
ORDER BY SUM_TIMER_WAIT DESC LIMIT 20;
-- or: SELECT * FROM sys.statement_analysis LIMIT 20;  slow log: slow_query_log=ON, long_query_time=0.5
```

Capture production plans with real parameter values (plans differ per value):

```ini
# postgresql.conf (or LOAD 'auto_explain' in one session)
shared_preload_libraries = 'pg_stat_statements,auto_explain'
auto_explain.log_min_duration = '500ms'
auto_explain.log_analyze = on        # actual rows/time; instruments every statement, so:
auto_explain.log_timing = off        # keep row counts, drop per-node timing overhead
auto_explain.log_buffers = on
auto_explain.log_format = json       # for pev2 / explain.dalibo.com
auto_explain.sample_rate = 0.1       # instrument 10% of statements on busy servers
```

Signals in the ranking: `rows / calls` large (returning too much), `shared_blks_read` high (cold or
too much I/O), `temp_blks_written` > 0 (sort/hash spills), MySQL `SUM_ROWS_EXAMINED` >> `SUM_ROWS_SENT`
(filtering after reading).

## 2. Reading a plan

```sql
EXPLAIN (ANALYZE, BUFFERS, SETTINGS) SELECT ...;   -- PG18 adds BUFFERS automatically with ANALYZE
EXPLAIN (GENERIC_PLAN) SELECT ... WHERE id = $1;   -- PG16+: plan with placeholders, no execution
```

`ANALYZE` executes the statement: wrap writes in `BEGIN; EXPLAIN ANALYZE ...; ROLLBACK;`.

Procedure:
1. Run on production-sized data (a replica or a restored snapshot), never a 1k-row dev database.
2. Read bottom-up (innermost node first); time is inclusive of children, per loop.
3. Per node compare estimated `rows` vs actual `rows x loops`. 10x or more off = a statistics or
   correlation problem (section 9); the node above it probably picked the wrong algorithm.
4. Look for: `Rows Removed by Filter` large vs rows kept (missing or wrong index);
   `Heap Fetches` on Index Only Scan (visibility map stale, VACUUM); `Sort Method: external merge  Disk:`
   or `Batches: > 1` on Hash (work_mem spill); `shared read` vs `hit` (I/O vs cache);
   `Rows Removed by Index Recheck` and `Heap Blocks: lossy=` (bitmap exceeded work_mem).
5. PG18 extras: actual row counts print with two decimals (`rows=0.50` means fewer than one row per
   loop), `Index Searches: N` shows how many times an index was descended (skip scan, `IN` lists).
6. Visualize long plans: pev2 (`explain.dalibo.com`) with `FORMAT JSON` output.

| Engine | Command |
|---|---|
| MySQL 8.0.18+ | `EXPLAIN ANALYZE SELECT ...` (tree with actual time/rows/loops; executes) |
| MySQL 8.0.16+ | `EXPLAIN FORMAT=TREE SELECT ...` (estimates only) |
| SQLite | `EXPLAIN QUERY PLAN SELECT ...` (`SEARCH ... USING INDEX` vs `SCAN`, `USE TEMP B-TREE FOR ORDER BY`) |

## 3. Node -> meaning -> usual fix

| Plan shows | Meaning | Usual fix |
|---|---|---|
| Seq Scan, selective filter, many `Rows Removed by Filter` | no usable index | index on the filter columns (section 5) |
| Seq Scan returning most of the table | correct choice | reduce rows needed, or accept |
| Nested Loop, outer rows huge, inner index scan x loops | estimate too low on the outer side | fix estimates (ANALYZE, extended stats); index the inner join key |
| Nested Loop with inner Seq Scan | missing index on the join key | index the referencing (FK) column |
| Hash Join `Batches: 8` / Hash `Disk Usage` | hash table spilled | raise work_mem for that role/session, reduce columns, filter earlier |
| Sort on large input, `external merge  Disk:` | sort spilled to disk | index matching `ORDER BY` (+ LIMIT), or work_mem |
| Index Scan, many rows, high `shared read` | random heap I/O per row | covering index (INCLUDE) for an Index Only Scan, or CLUSTER-like locality |
| Index Only Scan with high `Heap Fetches` | visibility map not set | VACUUM (tune autovacuum on that table) |
| Bitmap Heap Scan, `lossy=` blocks, Recheck removes rows | bitmap degraded to page granularity | work_mem, more selective index |
| Gather with few workers launched | parallel workers exhausted | `max_parallel_workers*`, or accept |
| Memoize with low hit ratio | cache not helping | usually fine; check estimates |
| SubPlan executed per row | correlated subquery | rewrite as JOIN / EXISTS / LATERAL |

## 4. Planner model

- Cost units: `seq_page_cost = 1.0`, `random_page_cost = 4.0` (set 1.1 on SSD/NVMe),
  `cpu_tuple_cost = 0.01`, `cpu_index_tuple_cost = 0.005`, `cpu_operator_cost = 0.0025`.
  Seq scan cost = `relpages x seq_page_cost + reltuples x (cpu_tuple_cost + quals x cpu_operator_cost)`.
- Cardinality: per-column statistics (`pg_stats`: `null_frac`, `n_distinct`, `most_common_vals/freqs`,
  `histogram_bounds`, `correlation`) from a sample of `300 x default_statistics_target` rows
  (target default 100).
- Independence assumption: `sel(a AND b) = sel(a) x sel(b)`. Correlated columns (city and zip,
  tenant and status) make estimates far too low; fix with `CREATE STATISTICS` (section 9).
- Join algorithms:

| Algorithm | Wins when | Needs |
|---|---|---|
| Nested loop (with inner index) | small outer side, selective inner index | index on inner join key |
| Hash join | large unsorted inputs, equality joins | memory for the smaller side (`work_mem x hash_mem_multiplier`, default 2.0) |
| Merge join | both inputs already sorted (indexes) or huge | sort order on join keys |

- Join order: dynamic programming (System R style) up to `join_collapse_limit` / `from_collapse_limit`
  (default 8) relations per subproblem; genetic optimizer (GEQO) from `geqo_threshold = 12` FROM items.
  Queries with 12+ joins can get different plans run to run.
- Prepared statements: `plan_cache_mode = auto` uses custom plans for the first 5 executions, then a
  generic plan if it is not costlier on average. Skewed parameters can then get a bad generic plan;
  drivers prepare implicitly (psycopg 3 and pgJDBC after 5 executions). Diagnose with
  `EXPLAIN (GENERIC_PLAN)`; fix per role or statement with `SET plan_cache_mode = force_custom_plan`.

## 5. Index design

- Composite column order: equality columns first, then the sort columns, then range columns (ESR).
  The index serves a query using a leftmost prefix of its columns.
- PostgreSQL 18 B-tree skip scan can use an index whose leading column has no condition when that
  column has few distinct values; treat it as a bonus, not a design target.
- Covering: `INCLUDE (col)` adds non-key payload so the query is answered by an Index Only Scan.
  MySQL InnoDB secondary indexes always contain the primary key; no INCLUDE clause.
- Partial: `CREATE INDEX ... ON orders (created_at) WHERE deleted_at IS NULL`; the query must repeat
  the predicate (or one that implies it).
- Expression: `CREATE INDEX ON users (lower(email))` and query `WHERE lower(email) = lower($1)`;
  MySQL 8.0.13+: `CREATE INDEX ix ON users ((lower(email)))`.
- GIN for `jsonb` containment (`jsonb_path_ops` for `@>` only, smaller), arrays, full text;
  `pg_trgm` + `gin_trgm_ops` for `ILIKE '%x%'` and similarity.
- BRIN for huge append-only tables filtered by a column correlated with physical order
  (`created_at` in an event log): tiny, coarse; useless when correlation is low.
- Index every foreign-key referencing column used in joins or parent deletes (PostgreSQL does not
  create them; parent `DELETE` scans the child table otherwise).
- Mixed sort directions need a matching index: `ORDER BY a DESC, b ASC` needs `(a DESC, b ASC)`
  (or `(a ASC, b DESC)` scanned backward).
- Write amplification: every index adds work to each INSERT, WAL volume and vacuum time; an index on
  a frequently updated column disables HOT updates for that column. Measure write cost (section 10).
- Remove unused (`pg_stat_user_indexes.idx_scan = 0` over a full business cycle, checked on every
  replica) and duplicate/prefix-redundant indexes: queries in [diagnostic queries](references/diagnostic-queries.md).
- Trial before building: HypoPG `SELECT * FROM hypopg_create_index('CREATE INDEX ON orders (tenant_id, created_at)')`,
  then plain `EXPLAIN` (not ANALYZE). MySQL: create it `INVISIBLE`, test with
  `SET optimizer_switch = 'use_invisible_indexes=on'`.
- Build without blocking writes: `CREATE INDEX CONCURRENTLY` (not inside a transaction; a failed build
  leaves an INVALID index to drop). Rollout procedure: `zero-downtime-migrations`.

## 6. Sargable rewrites

| Anti-pattern | Rewrite |
|---|---|
| `WHERE date(created_at) = $1` | `WHERE created_at >= $1 AND created_at < $1 + interval '1 day'` |
| `WHERE lower(email) = $1` without expression index | add the expression index, or `citext` |
| parameter type differs from column (`bigint` col vs text param, MySQL varchar col vs integer) | bind the column's type; implicit casts disable the index |
| `WHERE a = $1 OR b = $1` with ORDER BY/LIMIT | `UNION ALL` of two indexed queries (PG can BitmapOr two indexes when no ORDER BY/LIMIT is involved) |
| `NOT IN (SELECT x FROM ...)` | `NOT EXISTS (...)`: correct with NULLs and plans as an anti-join |
| `SELECT DISTINCT` to hide join fan-out | fix the join; use `EXISTS` for "has any" semantics |
| `IN (SELECT ...)` correlated per row, scalar subquery in SELECT list | JOIN, `EXISTS`, or `LATERAL` |
| CTE used as an optimization fence by habit | PG12+ inlines a non-recursive, side-effect-free CTE referenced once; `MATERIALIZED` forces the fence when wanted |
| exact `COUNT(*)` on a huge table for a UI badge | estimate (`SELECT reltuples::bigint FROM pg_class WHERE oid = 'orders'::regclass`, or EXPLAIN rows) or a maintained counter |
| `SELECT *` | list the needed columns: enables Index Only Scans, less I/O and network |
| `LIKE '%term%'` on B-tree | trigram GIN index, or full-text search |

## 7. Keyset pagination

```sql
-- first page
SELECT id, created_at, total FROM orders
WHERE tenant_id = $1 AND status = 'open'
ORDER BY created_at DESC, id DESC LIMIT 50;
-- next page: pass the last row's (created_at, id)
SELECT id, created_at, total FROM orders
WHERE tenant_id = $1 AND status = 'open' AND (created_at, id) < ($2, $3)
ORDER BY created_at DESC, id DESC LIMIT 50;
-- index: (tenant_id, status, created_at DESC, id DESC) INCLUDE (total)
```

- OFFSET reads and discards every skipped row: cost grows linearly with depth, and rows inserted
  between requests shift pages (duplicates, skips). Keyset cost is constant per page.
- The unique tiebreaker (`id`) is mandatory; without it equal timestamps make pages unstable.
- MySQL: if `EXPLAIN` shows the row comparison not used as a range, write
  `created_at < ? OR (created_at = ? AND id < ?)`.
- API shape (opaque cursor, `next_cursor`, max limit): `api-contract-design`.

## 8. ORM N+1 and chatty access

Detect by counting queries per request or test, not by reading code:

| Stack | Detect | Fix |
|---|---|---|
| Django | `with self.assertNumQueries(3):`, `django.test.utils.CaptureQueriesContext` | `select_related` (FK/one-to-one, JOIN), `prefetch_related` (many, second query) |
| SQLAlchemy 2.x | `event.listen(engine, "before_cursor_execute", counter)`; `lazy="raise"` / `raiseload("*")` in tests | `selectinload` (collections), `joinedload` (many-to-one) |
| Prisma | `new PrismaClient({ log: ["query"] })` | `include` / `select` nested relations; batch with `findMany({ where: { id: { in: ids } } })` |
| any SQL | `pg_stat_statements` calls per request, APM spans | `WHERE id = ANY($1)` with an array parameter; JOIN |
| GraphQL | resolver query counts | DataLoader (batch + per-request cache) |

Bulk writes: `COPY` (psycopg 3 `cursor.copy()`), multi-row `INSERT ... VALUES (...), (...)`, or
`INSERT ... SELECT unnest($1::bigint[]), unnest($2::text[])`; not one INSERT per row in a loop.
Per-ORM snippets: [ORM N+1 detection and fixes](references/orm-n-plus-one.md).

## 9. Statistics, maintenance and runtime guards

```sql
ANALYZE orders;                                             -- after bulk loads, always
ALTER TABLE orders ALTER COLUMN tenant_id SET STATISTICS 1000;   -- skewed column: 500-1000 (default 100, max 10000)
CREATE STATISTICS orders_tenant_status (dependencies, ndistinct, mcv) ON tenant_id, status FROM orders;
ANALYZE orders;                                             -- extended stats are built by ANALYZE
ALTER TABLE orders SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.01);
```

Runtime guards per role (not globally; migrations and batch jobs need different values):

```sql
ALTER ROLE api_rw SET statement_timeout = '5s';
ALTER ROLE api_rw SET lock_timeout = '2s';
ALTER ROLE api_rw SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE api_rw SET transaction_timeout = '60s';          -- PostgreSQL 17+
```

PgBouncer in transaction mode: session state does not survive between transactions (`SET` -> use
`SET LOCAL`; session advisory locks, `LISTEN`, temp tables break). Protocol-level prepared
statements work from PgBouncer 1.21 with `max_prepared_statements` > 0 (default differs by version
and provider); SQL-level `PREPARE` still does not.

## 10. Verification

| Evidence | How |
|---|---|
| plan before/after | `EXPLAIN (ANALYZE, BUFFERS)` text for both, same parameters, in the PR |
| timing | >= 10 runs each, median and spread, cache state stated (warm: discard first run; cold: say how caches were dropped); statistics method from `performance-optimization` |
| representative parameters | at least: the biggest tenant, a median tenant, an empty result |
| write-path cost of a new index | insert/update benchmark before/after (`pgbench -f insert.sql -T 60`), index size from `pg_relation_size` |
| regression guard | test asserting query count (`assertNumQueries`) or plan shape on a seeded DB, where cheap |
| production | `pg_stat_statements` mean/total for the queryid after deploy (`pg_stat_statements_reset()` scoped to it if needed) |

## 11. Pitfalls

- Tuning on a 1k-row dev database: a Seq Scan is the right plan there; numbers mean nothing.
- Hints (`pg_hint_plan`, MySQL optimizer hints) as a first resort: they freeze today's data shape;
  fix statistics, indexes or the query first.
- `SELECT *` defeating Index Only Scans and inflating sorts.
- Collation/locale differences between environments: `text_pattern_ops` needs, `ORDER BY` results and
  index usability for `LIKE 'abc%'` differ under non-C collations.
- Testing a parameter-dependent plan with one value only (small tenant fast, big tenant slow).
- Adding an index per slow query without removing old ones: write amplification and planner confusion.
- `EXPLAIN ANALYZE` on a data-modifying statement outside a rolled-back transaction.
- Forgetting `ANALYZE` after a bulk load or a new extended statistics object.

## 12. Worked example: `/orders` at 2.3 s

Symptom: `GET /orders?page=N` p50 2.3 s for tenant 42 (infinite scroll goes deep). `pg_stat_statements`
puts the list query first by total time (38%).

```sql
SELECT * FROM orders WHERE tenant_id = $1 AND status = 'open'
ORDER BY created_at DESC LIMIT 50 OFFSET $2;          -- $2 = 200000 at depth
```

Before (PG18, abridged, tenant 42, OFFSET 200000):

```text
Limit  (cost=412216.10..412216.22 rows=50 width=412) (actual time=2291.82..2291.90 rows=50.00 loops=1)
  Buffers: shared hit=1210 read=321000, temp read=22950 written=23010
  ->  Sort  (cost=412215.80..412216.10 rows=120 width=412) (actual time=2264.10..2287.55 rows=200050.00 loops=1)
        Sort Key: created_at DESC
        Sort Method: external merge  Disk: 184320kB
        ->  Seq Scan on orders  (cost=0.00..412210.00 rows=120 width=412) (actual time=0.03..1712.40 rows=410213.00 loops=1)
              Filter: ((tenant_id = 42) AND (status = 'open'::text))
              Rows Removed by Filter: 5589787
Execution Time: 2302.61 ms
```

Diagnosis: estimate 120 vs actual 410,213 (3,400x): tenant 42 bulk-imported 410k open orders after
the last ANALYZE, and `status = 'open'` is correlated with that tenant. No index starts with
`(tenant_id, status)`; sorting 410k wide rows spills 180 MB because of `SELECT *`. Cost check with
section 4: 322,210 pages x 1.0 + 6,000,000 rows x (0.01 + 2 x 0.0025) = 412,210, the Seq Scan's cost.

Fix:

```sql
ANALYZE orders;
CREATE STATISTICS orders_tenant_status (dependencies, mcv) ON tenant_id, status FROM orders;
ANALYZE orders;
CREATE INDEX CONCURRENTLY orders_tenant_status_created_id_idx
  ON orders (tenant_id, status, created_at DESC, id DESC) INCLUDE (total);
VACUUM (ANALYZE) orders;                             -- sets the visibility map for Index Only Scans
```

Query changed to the keyset form of section 7 with the three columns the endpoint renders (API
cursor per `api-contract-design`). HypoPG confirmed the plan shape before the 9-minute concurrent build.

After:

```text
Limit  (cost=0.56..9.12 rows=50 width=24) (actual time=0.041..0.212 rows=50.00 loops=1)
  Buffers: shared hit=6
  ->  Index Only Scan using orders_tenant_status_created_id_idx on orders  (cost=0.56..70212.33 rows=409876 width=24) (actual time=0.040..0.201 rows=50.00 loops=1)
        Index Cond: ((tenant_id = 42) AND (status = 'open'::text) AND (ROW(created_at, id) < ROW('2026-09-30 12:00:00+00'::timestamp with time zone, '981234'::bigint)))
        Heap Fetches: 0
        Index Searches: 1
Execution Time: 0.254 ms
```

Before the VACUUM the same plan showed `Heap Fetches: 50`. Results (10 warm runs each, same
parameters, biggest and a median tenant): query median 2,291 ms -> 0.25 ms at any depth; endpoint
p50 2.3 s -> 4 ms; index size 412 MB; single-row INSERT p50 0.21 ms -> 0.23 ms (pgbench, 60 s).
The old `(tenant_id)` index became a prefix of the new one: dropped after `idx_scan` stayed flat for a
week on primary and replicas. A test on the seeded DB asserts `Index Only Scan` in
`EXPLAIN (FORMAT JSON)` for the list query.

Related: `performance-optimization` (measurement statistics), `api-contract-design` (cursor API),
`code-review-checklist`, `database-transactions-isolation`, `zero-downtime-migrations`,
`refactoring-playbook`, hub `coding-general`.
