---
name: zero-downtime-migrations
description: "Zero-downtime schema changes on live databases plus new-table defaults: PostgreSQL/MySQL lock levels, lock_timeout with retries, expand-migrate-contract with deploy ordering, NOT VALID constraints, concurrent indexes, batched resumable backfills, migration-tool specifics (Alembic, Django, Prisma, Flyway, Atlas, golang-migrate) and linters (squawk, Atlas lint, strong_migrations). Load when writing, reviewing or sequencing a database migration."
when_to_use: "Files under migrations/, alembic/versions/, db/migrate/, prisma/migrations/ or raw *.sql DDL; ALTER TABLE, CREATE INDEX, NOT NULL, foreign keys, type changes or renames on a table that serves traffic; errors such as 'canceling statement due to lock timeout', 'CREATE INDEX CONCURRENTLY cannot run inside a transaction block' or MySQL 'Waiting for table metadata lock'; planning a backfill or a column rename across deploys."
---

# Zero-downtime migrations

Scope: changing the schema of a database that is serving traffic without an outage, and choosing
defaults for new tables. `code-review-checklist` keeps the short "Database migrations" checklist and
points here for the procedure; test design lives in `testing-strategy`, query and index tuning in
`performance-optimization`. Baseline: PostgreSQL 13-18 and MySQL 8.0/8.4 unless a row names a version.

Deep material: [DDL lock matrix and monitoring queries](references/ddl-lock-matrix.md) |
[tool recipes (Alembic, Django, Prisma, Flyway, Liquibase, Atlas, golang-migrate, sqlx, Diesel)](references/tool-recipes.md)

## 1. Defaults for new tables

Get the first migration right; every later fix is a live migration.

| Concern | Default | Why / when to deviate |
|---|---|---|
| Primary key | `bigint GENERATED ALWAYS AS IDENTITY`, or `uuid` v7 when ids are minted client-side or merged across shards | `int` overflows at 2^31; random UUIDv4 keys scatter B-tree inserts. PG18 has `uuidv7()` built in; older servers generate v7 in the app |
| Timestamps | `timestamptz NOT NULL DEFAULT now()` for `created_at`; `updated_at` set by app or trigger | `timestamp` without zone silently drops the offset |
| Money | `numeric(p,s)` (e.g. `numeric(19,4)`) or integer minor units (`bigint` cents) plus a currency column | never `float`/`double`/`real` |
| Strings | `text` plus `CHECK (char_length(col) <= n)` | changing a CHECK is cheap; shrinking `varchar(n)` is a rewrite |
| Nullability | `NOT NULL` unless "unknown" is a real state | adding NOT NULL later costs the section 11 procedure |
| Foreign keys | declare them, and index the referencing column | an unindexed FK makes parent deletes scan the child table |
| Business invariants | `UNIQUE` / `CHECK` / exclusion constraints in the database | app-only checks race under concurrency |
| Soft delete | only with partial unique indexes: `CREATE UNIQUE INDEX ... (email) WHERE deleted_at IS NULL` | otherwise a deleted row blocks re-creating the same email |
| Enumerations | lookup table + FK when values change often or carry attributes; `CHECK (status IN (...))` or a PG enum when the set is small and stable | PG enum values cannot be removed or reordered without recreating the type |

## 2. PostgreSQL DDL risk table

Every `ALTER TABLE` takes a lock; the question is which one and for how long.
`ACCESS EXCLUSIVE` blocks reads and writes; `SHARE` blocks writes; `SHARE UPDATE EXCLUSIVE`
blocks neither (only other DDL, VACUUM and itself). Full matrix in
[the lock matrix](references/ddl-lock-matrix.md).

| Change | Cost | Safe recipe |
|---|---|---|
| `ADD COLUMN` nullable, or with a non-volatile default (PG11+) | metadata only, brief ACCESS EXCLUSIVE | run under `lock_timeout` (section 3) |
| `ADD COLUMN` with a volatile default (`clock_timestamp()`, `gen_random_uuid()`, `uuidv7()`), stored generated or identity column | full table and index rewrite under ACCESS EXCLUSIVE | add nullable, backfill in batches, then set the default for new rows |
| `ALTER COLUMN TYPE` (most changes, e.g. `int` -> `bigint`) | rewrite under ACCESS EXCLUSIVE; indexes rebuilt | new column + dual write + backfill + swap (section 4). `varchar(n)` -> `text` or a longer `varchar` is metadata only |
| `CREATE INDEX` | SHARE lock: blocks writes for the whole build | `CREATE INDEX CONCURRENTLY` outside any transaction; a failed build leaves an `INVALID` index: `DROP INDEX CONCURRENTLY` it and retry |
| `ADD UNIQUE` / `PRIMARY KEY` | builds an index under the table lock | `CREATE UNIQUE INDEX CONCURRENTLY idx ...;` then `ADD CONSTRAINT c UNIQUE USING INDEX idx` |
| `ADD FOREIGN KEY` | validates every row while holding SHARE ROW EXCLUSIVE on both tables | `ADD CONSTRAINT ... NOT VALID` (instant), then `VALIDATE CONSTRAINT` (SHARE UPDATE EXCLUSIVE, plus ROW SHARE on the referenced table) |
| `ADD CHECK` | full scan under ACCESS EXCLUSIVE | `ADD CONSTRAINT ... CHECK (...) NOT VALID`, then `VALIDATE CONSTRAINT` |
| `SET NOT NULL` | full scan under ACCESS EXCLUSIVE | PG12+: first a valid `CHECK (col IS NOT NULL)`; `SET NOT NULL` then skips the scan. PG18: `ADD CONSTRAINT nn NOT NULL col NOT VALID` + `VALIDATE CONSTRAINT nn` |
| `RENAME COLUMN` / `RENAME TABLE` | instant | breaks every running instance that uses the old name: expand-contract instead |
| `DROP COLUMN` | instant (space reclaimed only by a rewrite) | only after no deployed code reads or writes it (section 4 step 6) |
| `ALTER TYPE ... ADD VALUE` (enum) | instant | PG < 12: not inside a transaction block. PG12+: allowed, but the new value is unusable until that transaction commits |
| `REINDEX` | blocks writes | `REINDEX INDEX CONCURRENTLY` (PG12+) |

Partitioned tables: `CREATE INDEX CONCURRENTLY` is not supported on the parent; create the index
`ON ONLY` the parent, build each partition's index concurrently, then `ALTER INDEX parent_idx ATTACH
PARTITION child_idx`.

## 3. The lock-queue hazard

An "instant" DDL statement still needs its lock. If a long transaction holds any conflicting lock,
the DDL waits, and every query that arrives after it queues behind the DDL: a 1 ms ALTER can stall
the table for as long as the oldest transaction runs.

Pre-flight on the primary:

```sql
-- transactions older than 1 minute (they will block the ALTER)
SELECT pid, now() - xact_start AS xact_age, state, left(query, 80)
FROM pg_stat_activity
WHERE xact_start < now() - interval '1 minute' ORDER BY xact_age DESC;

-- who blocks whom right now
SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event_type, left(query, 80)
FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;
```

Every DDL statement runs with a short `lock_timeout` and is retried with jittered backoff:

```sql
SET lock_timeout = '2s';         -- give up waiting for the lock quickly
SET statement_timeout = '15s';   -- cap the statement itself; raise it for VALIDATE / backfills
ALTER TABLE orders ADD COLUMN note text;
```

```bash
# psql keeps one session across -c flags, so the SETs apply to the ALTER
for attempt in 1 2 3 4 5 6 7 8; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
    -c "SET lock_timeout = '2s'" -c "ALTER TABLE orders ADD COLUMN note text" && break
  sleep $(( RANDOM % (2 ** attempt) + 1 ))   # SQLSTATE 55P03 lock_not_available: back off, retry
done
```

Exception: `CREATE INDEX CONCURRENTLY` and `VALIDATE CONSTRAINT` take SHARE UPDATE EXCLUSIVE, which
does not block reads or writes while it waits, so run them without a short `lock_timeout`: a
concurrent build cancelled part-way leaves an `INVALID` index. They still wait for old transactions,
so run the pre-flight query first.

MySQL behaves the same with metadata locks: an open transaction that touched the table blocks the
ALTER, and the ALTER blocks everyone behind it (`SHOW PROCESSLIST` shows "Waiting for table metadata
lock"). Use `SET SESSION lock_wait_timeout = 5;` and the same retry loop; find holders in
`performance_schema.metadata_locks`.

## 4. Expand, migrate, contract (with deploy ordering)

Rule: app versions N and N+1 both run during a rolling deploy, so each must work against every
intermediate schema. Renaming `users.fullname` to `users.display_name`:

| Step | Schema change | App release | Reversible? |
|---|---|---|---|
| 1 Expand | `ADD COLUMN display_name text` (nullable) | none | yes: drop the empty column |
| 2 Dual write | none | N+1 writes both columns, reads `fullname` | yes: redeploy N |
| 3 Backfill | batched `UPDATE ... SET display_name = fullname WHERE display_name IS NULL` (section 5) | none | yes |
| 4 Switch reads | optional: `NOT NULL` via section 11 recipe | N+2 reads `display_name` behind a flag, still writes both | yes: flip the flag |
| 5 Stop old writes | none | N+3 writes only `display_name`; ORM ignores `fullname` | yes: redeploy N+2 (old column still there, backfill again) |
| 6 Contract | `DROP COLUMN fullname` in a later release, after N+2 is gone everywhere (workers, cron, replicas of the app) | none | **no: point of no return**; take a backup checkpoint first |

Same shape for type changes (`int` -> `bigint`: new column, trigger or dual write, backfill, swap in a
short transaction), table splits and moving a column to another table. Never combine expand and
contract in one deploy.

## 5. Backfills

| Rule | Value |
|---|---|
| Unit of work | primary-key range, 1,000-10,000 rows per batch, one commit per batch |
| Idempotent statement | `UPDATE t SET new = f(old) WHERE id >= $1 AND id < $2 AND new IS NULL` |
| Where it runs | a job or management command, never inside the migration transaction |
| Resume | checkpoint the last finished `id` (a table or the job's state store) |
| Throttle | sleep between batches; pause when replica lag > 5 s or primary CPU > 70 % |
| Bloat | every UPDATE leaves a dead tuple: watch `n_dead_tup`, let autovacuum keep up |
| Verify | counts and a checksum on both sides before switching reads |

```python
# backfill_display_name.py: resumable, throttled, idempotent (psycopg 3)
import os, time, psycopg

BATCH, MAX_LAG_S = 5_000, 5.0
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    conn.execute("SET lock_timeout = '2s'; SET statement_timeout = '30s'")
    start = conn.execute("SELECT coalesce(max(last_id), 0) FROM backfill_progress WHERE job = 'display_name'").fetchone()[0]
    top = conn.execute("SELECT max(id) FROM users").fetchone()[0]
    while start <= top:
        with conn.transaction():
            conn.execute("""UPDATE users SET display_name = fullname
                            WHERE id >= %s AND id < %s AND display_name IS NULL""", (start, start + BATCH))
            conn.execute("""INSERT INTO backfill_progress (job, last_id) VALUES ('display_name', %s)
                            ON CONFLICT (job) DO UPDATE SET last_id = excluded.last_id""", (start + BATCH,))
        start += BATCH
        lag = conn.execute("SELECT coalesce(extract(epoch FROM max(replay_lag)), 0) FROM pg_stat_replication").fetchone()[0]
        time.sleep(0.05 if lag < MAX_LAG_S else 5.0)
```

```sql
-- verification before switching reads
SELECT count(*) FILTER (WHERE display_name IS DISTINCT FROM fullname) AS mismatches FROM users;
SELECT n_dead_tup, last_autovacuum FROM pg_stat_user_tables WHERE relname = 'users';
```

## 6. MySQL and table-rewrite tools

| Operation (InnoDB, 8.0/8.4) | Algorithm | Notes |
|---|---|---|
| Add column | `ALGORITHM=INSTANT` (default in 8.4) | 8.0.12 added INSTANT add at the end, 8.0.29 any position; at most 64 instant row versions (255 from 9.1), then a rebuild resets the counter |
| Drop / rename column, set / drop default | INSTANT | renaming a column referenced by another table's FK needs INPLACE |
| Add secondary index | `ALGORITHM=INPLACE, LOCK=NONE` | concurrent DML allowed; still I/O heavy |
| Change column type | COPY only | blocks writes: use an online copy tool |
| Extend `VARCHAR` | INPLACE if the length-byte count does not change (both < 256 bytes or both >= 256) | crossing 255 bytes needs COPY |

Always write the algorithm explicitly (`ALTER TABLE t ADD COLUMN c INT, ALGORITHM=INSTANT;`): MySQL
then errors instead of silently falling back to a blocking copy. For COPY-only changes use `gh-ost`
(binlog-based, no triggers, pausable) or `pt-online-schema-change` (trigger-based).

PostgreSQL rewrites to reclaim bloat or reorder: `pg_repack` (extension; exclusive locks only briefly
at the start and at the swap). PostgreSQL 19 adds `REPACK (CONCURRENTLY)`; its GA is planned for
November 2026, so check `SHOW server_version` before relying on it. Never run `VACUUM FULL` or
`CLUSTER` on a live table.

## 7. Migration-tool specifics

One concern per migration file; non-transactional statements alone in their own file.

| Tool | Read the SQL | Run outside a transaction (for `CONCURRENTLY`) | Watch out |
|---|---|---|---|
| Alembic | `alembic upgrade head --sql` (offline mode) | `with op.get_context().autocommit_block():` + `op.create_index(..., postgresql_concurrently=True)` | autogenerate turns renames into drop + add; review every generated op |
| Django | `python manage.py sqlmigrate app 0042` | `atomic = False` on the Migration + `AddIndexConcurrently` | `AddConstraintNotValid` and `ValidateConstraint` in separate migrations; `SeparateDatabaseAndState` to drop a field from state before the column |
| Prisma Migrate | `prisma migrate dev --create-only`, then edit `migration.sql` | keep the CONCURRENTLY statement alone in its migration; transaction wrapping varies by version, verify on staging | `prisma migrate deploy` in CI/CD, never `migrate dev` |
| Flyway | the SQL file is the migration | `V7__idx.sql.conf` containing `executeInTransaction=false` | mixing transactional and non-transactional statements needs `mixed=true` |
| Liquibase | `liquibase update-sql` | `--changeset alice:42 runInTransaction:false` | one statement per non-transactional changeset |
| Atlas | `atlas migrate diff` writes SQL | `-- atlas:txmode none` file directive | `atlas migrate lint` in CI (section 8) |
| golang-migrate | the SQL file | one statement per file (multi-statement Exec runs in one implicit transaction) | `x-statement-timeout` URL parameter |
| sqlx (Rust) | the SQL file | first line `-- no-transaction` | |
| Diesel | `up.sql` | `metadata.toml` with `run_in_transaction = false` | |

Snippets for each in [tool recipes](references/tool-recipes.md).

## 8. Lint and test in CI

| Gate | Command | Blocks merge on |
|---|---|---|
| SQL lint (PG) | `squawk --pg-version=16.0 'migrations/*.sql'` | `require-concurrent-index-creation`, `constraint-missing-not-valid`, `adding-not-nullable-field`, `changing-column-type`, `renaming-column`, `ban-drop-column`, `require-timeout-settings` |
| Atlas | `atlas migrate lint --dev-url "docker://postgres/16/dev" --git-base main` | destructive and data-dependent changes, table locks |
| Rails | `strong_migrations` gem | unsafe operations not wrapped in `safety_assured` |
| Django | `python manage.py lintmigrations` (django-migration-linter) | backward-incompatible migrations |
| Rehearsal | apply to a restored production-sized snapshot and time each statement | any statement holding ACCESS EXCLUSIVE > 1 s, total runtime over the window |
| Compatibility | run version N's test suite against the N+1 schema | any failure: N+1 is not deployable while N still runs |
| Reversibility | `down` migration tested, or "forward-fix only" written in the PR | silent irreversibility |

## 9. Safety net before irreversible steps

1. Backup checkpoint: confirm PITR covers "now" (WAL archiving healthy) or take a snapshot; record the
   LSN or timestamp in the PR (`SELECT pg_current_wal_lsn(), now();`).
2. Feature flag for the read switch (step 4), so rollback is a flag flip, not a deploy.
3. Post-backfill verification queries (section 5) pasted into the PR with results.
4. Rollback plan written before running: the exact command per step and the step after which only
   forward fixes exist.
5. Run the risky steps in a low-traffic window with someone watching lock waits
   (`log_lock_waits = on` logs waits longer than `deadlock_timeout`).

## 10. Pitfalls

- Migration frameworks wrap every file in a transaction: `CREATE INDEX CONCURRENTLY cannot run inside
  a transaction block`. Use the tool's opt-out (section 7), not a manual `COMMIT` in the file.
- A failed concurrent build leaves an `INVALID` index that still slows writes:
  `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;` and drop it.
- ORMs that `SELECT *` or map every column break when a column disappears: remove it from the model
  first (Rails `ignored_columns`, Django `SeparateDatabaseAndState`, SQLAlchemy: delete the attribute),
  deploy, then drop.
- Enum `ADD VALUE` inside a transaction on PG < 12 fails; on 12+ the value cannot be used in the same
  transaction.
- Views, materialized views, triggers and functions that depend on an altered column: `ALTER TYPE`
  fails or the view keeps the old definition. List dependants with `pg_depend` or `\d+` first.
- One giant `UPDATE` backfill: one transaction, a table's worth of dead tuples, WAL spike, replica lag,
  and a lock held for its whole duration.
- `statement_timeout` also counts lock wait; for a long `VALIDATE` raise `statement_timeout` but keep
  `lock_timeout` short.
- An anti-wraparound autovacuum holds SHARE UPDATE EXCLUSIVE and does not yield: `VALIDATE` waits
  behind it. Check `pg_stat_progress_vacuum` first.
- Adding a FK without an index on the referencing column: validation is fine, but every parent
  `DELETE` later scans the child table.

## 11. Worked example: `orders.customer_id` NOT NULL with a FK, 400M rows

Starting point: `orders(id bigint PK, customer_id bigint NULL, ...)`, 400M rows, ~3,000 writes/s, a
few thousand rows with NULL or dangling `customer_id`. Product decision (recorded in the PR): orphans
point at a pre-created `customers` row `id = 1` ("legacy-unknown"). Steps 1, 4, 5 and 6 take strong
locks and run inside the section 3 retry loop with `lock_timeout = '2s'`; steps 0, 3 and 7 take SHARE
UPDATE EXCLUSIVE and run with `lock_timeout` off (section 3 exception).

```sql
-- 0. index the referencing column (writes continue; plan ~25 min, measure in the rehearsal)
CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);

-- 1. stop new NULLs: NOT VALID checks new rows only. ACCESS EXCLUSIVE for a few ms.
ALTER TABLE orders ADD CONSTRAINT orders_customer_id_nn CHECK (customer_id IS NOT NULL) NOT VALID;
```

App: the release that always sets `customer_id` must be fully deployed before step 1, or its inserts
fail the check.

```sql
-- 2. backfill orphans in id ranges of 10,000 (40,000 ranges; the section 5 job, throttled)
UPDATE orders SET customer_id = 1
WHERE id >= $1 AND id < $2
  AND (customer_id IS NULL
       OR NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = orders.customer_id));

-- 3. prove it: full scan under SHARE UPDATE EXCLUSIVE (reads and writes continue)
SET statement_timeout = '4h';
ALTER TABLE orders VALIDATE CONSTRAINT orders_customer_id_nn;

-- 4. NOT NULL without a scan (PG12+ uses the valid CHECK). ACCESS EXCLUSIVE for a few ms.
SET statement_timeout = '15s';
ALTER TABLE orders ALTER COLUMN customer_id SET NOT NULL;

-- 5. the CHECK is now redundant
ALTER TABLE orders DROP CONSTRAINT orders_customer_id_nn;

-- 6. FK without validation: SHARE ROW EXCLUSIVE on orders and customers for a few ms
ALTER TABLE orders ADD CONSTRAINT orders_customer_id_fk
  FOREIGN KEY (customer_id) REFERENCES customers (id) NOT VALID;

-- 7. validate: SHARE UPDATE EXCLUSIVE on orders, ROW SHARE on customers
SET statement_timeout = '4h';
ALTER TABLE orders VALIDATE CONSTRAINT orders_customer_id_fk;
```

On PG18 steps 1, 3, 4 and 5 collapse to
`ADD CONSTRAINT orders_customer_id_nn NOT NULL customer_id NOT VALID` then
`VALIDATE CONSTRAINT orders_customer_id_nn`.

Budget check: steps 1, 4, 5 and 6 each hold their strong lock for single-digit milliseconds once
acquired, so total exclusive-lock time stays under 50 ms; the long scans (0, 3, 7) take only
SHARE UPDATE EXCLUSIVE. Confirm in the rehearsal on a production-sized snapshot with `\timing on`
and `log_lock_waits = on`, and paste the per-step timings into the PR. Rollback: before step 4 drop
the CHECK; after step 4 `ALTER COLUMN customer_id DROP NOT NULL` is also instant; the backfill
itself is the only data change, so keep the list of rewritten ids (job log) for an audit.

Related: `resilience-patterns`, `dependency-upgrades`, `regex-engineering`, `docs-and-adr-writing`,
`code-review-checklist`, `testing-strategy`, `performance-optimization`, hub `coding-general`.
