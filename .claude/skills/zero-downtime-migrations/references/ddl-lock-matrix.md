# DDL lock matrix and monitoring queries

Extended reference for `zero-downtime-migrations` section 2-3. PostgreSQL lock names are the table-level
modes from the "Explicit Locking" chapter; verify against the docs of your server version.

## PostgreSQL: which statement takes which lock

| Statement | Table lock | Blocks reads | Blocks writes | Duration |
|---|---|---|---|---|
| `SELECT` | ACCESS SHARE | no | no | query |
| `INSERT` / `UPDATE` / `DELETE` | ROW EXCLUSIVE | no | no | transaction |
| `CREATE INDEX` | SHARE | no | **yes** | whole build |
| `CREATE INDEX CONCURRENTLY` | SHARE UPDATE EXCLUSIVE | no | no | two scans + waits for older transactions |
| `VACUUM` (not FULL), `ANALYZE` | SHARE UPDATE EXCLUSIVE | no | no | run |
| `ALTER TABLE ... VALIDATE CONSTRAINT` | SHARE UPDATE EXCLUSIVE (+ ROW SHARE on referenced table for FKs) | no | no | full scan |
| `ALTER TABLE ... ADD FOREIGN KEY` (also `NOT VALID`) | SHARE ROW EXCLUSIVE on both tables | no | **yes** | instant with NOT VALID, else full validation |
| `CREATE TRIGGER` | SHARE ROW EXCLUSIVE | no | **yes** | instant |
| `ALTER TABLE ... ADD COLUMN / DROP COLUMN / SET NOT NULL / ADD CHECK / ALTER TYPE / RENAME` | ACCESS EXCLUSIVE | **yes** | **yes** | instant, scan or rewrite (see SKILL.md section 2) |
| `DROP TABLE`, `TRUNCATE`, `VACUUM FULL`, `CLUSTER` | ACCESS EXCLUSIVE | **yes** | **yes** | rewrite or instant |
| `REINDEX` (non-concurrent) | SHARE on the table, ACCESS EXCLUSIVE on the index | queries that would use the index | **yes** | whole rebuild |
| `REINDEX ... CONCURRENTLY` (PG12+) | SHARE UPDATE EXCLUSIVE | no | no | rebuild + swap |
| `REFRESH MATERIALIZED VIEW` (without CONCURRENTLY) | ACCESS EXCLUSIVE on the view | **yes** | n/a | whole refresh |
| `REFRESH MATERIALIZED VIEW CONCURRENTLY` (needs a unique index) | EXCLUSIVE on the view | no | n/a | whole refresh |

Conflict summary: ACCESS EXCLUSIVE conflicts with everything; SHARE conflicts with ROW EXCLUSIVE (writes);
SHARE UPDATE EXCLUSIVE conflicts with itself, SHARE, SHARE ROW EXCLUSIVE, EXCLUSIVE and ACCESS EXCLUSIVE,
so two concurrent index builds or a VALIDATE plus a manual VACUUM on the same table serialize.

## Rewrite or not (PostgreSQL)

| Change | Rewrite? |
|---|---|
| `ADD COLUMN c int` / `ADD COLUMN c int DEFAULT 0` (PG11+) | no |
| `ADD COLUMN c timestamptz DEFAULT now()` | no (`now()` is stable, evaluated once) |
| `ADD COLUMN c uuid DEFAULT gen_random_uuid()` / `clock_timestamp()` | yes (volatile) |
| `ADD COLUMN ... GENERATED ALWAYS AS (...) STORED`, identity column | yes |
| `ADD COLUMN ... GENERATED ALWAYS AS (...)` virtual (PG18 default kind) | no |
| `ALTER COLUMN c TYPE text` from `varchar(n)`; `varchar(n)` -> `varchar(m)`, m > n | no |
| `ALTER COLUMN c TYPE bigint` from `int` | yes, and every index on `c` is rebuilt |
| `ALTER COLUMN c TYPE timestamptz` from `timestamp` | yes, unless the session `TimeZone` is UTC (PG12+ then skips the table rewrite but still rebuilds indexes on the column); values are interpreted in the session time zone |
| `SET NOT NULL` | no rewrite, but a full scan unless a valid CHECK proves it (PG12+) |
| `DROP COLUMN` | no (column hidden; space reclaimed by later rewrites) |
| `SET DEFAULT` / `DROP DEFAULT` | no |

## Monitoring during a migration

```sql
-- lock waits right now, with the blocker's query
SELECT a.pid, a.wait_event_type, now() - a.query_start AS waiting,
       left(a.query, 60) AS waiting_query,
       b.pid AS blocker_pid, left(b.query, 60) AS blocker_query, now() - b.xact_start AS blocker_xact_age
FROM pg_stat_activity a
JOIN LATERAL unnest(pg_blocking_pids(a.pid)) AS bp(pid) ON true
JOIN pg_stat_activity b ON b.pid = bp.pid;

-- progress of a concurrent index build
SELECT pid, phase, blocks_done, blocks_total, tuples_done, tuples_total
FROM pg_stat_progress_create_index;

-- progress of (auto)vacuum, including anti-wraparound runs that VALIDATE will wait for
SELECT pid, relid::regclass, phase, heap_blks_scanned, heap_blks_total FROM pg_stat_progress_vacuum;

-- invalid indexes left by failed CONCURRENTLY builds
SELECT indexrelid::regclass AS index, indrelid::regclass AS table FROM pg_index WHERE NOT indisvalid;

-- replication lag (on the primary, PG10+)
SELECT application_name, replay_lag FROM pg_stat_replication;

-- dead tuples and autovacuum health of the table being backfilled
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, autovacuum_count
FROM pg_stat_user_tables WHERE relname = 'orders';
```

Emergency stop for a migration that is queueing traffic behind it: `SELECT pg_cancel_backend(<pid>);`
(cancels the statement); `pg_terminate_backend(<pid>)` only if cancel does not work.

Server settings worth having during migration windows: `log_lock_waits = on` (logs any lock wait longer
than `deadlock_timeout`, default 1 s), `log_min_duration_statement` low enough to capture DDL timings.

## MySQL (InnoDB) online DDL summary

| Operation | INSTANT | INPLACE | Rebuilds table | Concurrent DML |
|---|---|---|---|---|
| Add column | yes (8.0.12+ at the end, 8.0.29+ any position; default algorithm in 8.4) | yes | no with INSTANT | yes |
| Drop column | yes (8.0.29+) | yes | yes unless INSTANT | yes |
| Rename column | yes | yes | no | yes |
| Set / drop column default | yes | yes | no | yes |
| Change column data type | no | no | yes (COPY) | **no** |
| Extend VARCHAR within the same length-byte class | no | yes | no | yes |
| Add secondary index | no | yes | no | yes |
| Add primary key | no | yes (expensive) | yes | yes |
| Add foreign key | no | yes with `foreign_key_checks=0`, else COPY | no | yes (INPLACE) |

Instant changes are limited to 64 row versions per table (255 from MySQL 9.1); check
`INFORMATION_SCHEMA.INNODB_TABLES.TOTAL_ROW_VERSIONS`. Always state `ALGORITHM=` and `LOCK=` explicitly so
the server refuses instead of degrading to a blocking copy.

```sql
SET SESSION lock_wait_timeout = 5;   -- metadata-lock wait cap for this session
ALTER TABLE orders ADD COLUMN note TEXT, ALGORITHM=INSTANT;
ALTER TABLE orders ADD INDEX orders_note_idx (note(32)), ALGORITHM=INPLACE, LOCK=NONE;

-- who holds metadata locks on the table
SELECT object_schema, object_name, lock_type, lock_status, owner_thread_id
FROM performance_schema.metadata_locks WHERE object_name = 'orders';
```

Online copy tools for COPY-only changes:

```bash
gh-ost --host=db1 --database=shop --table=orders \
  --alter="MODIFY COLUMN total DECIMAL(19,4) NOT NULL" \
  --max-lag-millis=1500 --chunk-size=1000 --execute          # binlog-based, throttles on lag
pt-online-schema-change --alter "MODIFY COLUMN total DECIMAL(19,4) NOT NULL" \
  D=shop,t=orders --max-lag=1 --chunk-size=1000 --execute    # trigger-based
```

Run either first without `--execute` (gh-ost dry run, pt-osc `--dry-run`) and test the cut-over on a
replica-sized copy.
