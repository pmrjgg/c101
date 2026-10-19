---
name: database-transactions-isolation
description: "How databases store, version and isolate data: B+tree vs LSM engines, WAL and recovery, MVCC and vacuum, row locks and SKIP LOCKED queues, real vendor isolation semantics (PostgreSQL, InnoDB, Oracle, SQL Server, CockroachDB), anomalies as concrete histories, and their fixes. Load when concurrent transactions misbehave, picking an isolation level, or reasoning about storage engines (query tuning lives in sql-query-tuning)."
when_to_use: "Oversold inventory, double bookings, negative balances or duplicate job execution under concurrency; SQLSTATE 40001 or 40P01, 'could not serialize access', deadlocks or lock waits; choosing READ COMMITTED vs REPEATABLE READ vs SERIALIZABLE; SELECT ... FOR UPDATE or SKIP LOCKED queues; autovacuum, bloat, xid wraparound or long-running transactions; InnoDB undo, purge or gap-lock surprises; B+tree vs LSM or UUID key choices."
---

# Database transactions and isolation

## 1. Scope

This skill covers how the engine stores, versions and isolates rows. Index design and plan reading
live in `sql-query-tuning`; DDL lock levels and online schema changes in `zero-downtime-migrations`;
replicated and distributed consistency (and Elle-style history checking) in
`distributed-consensus-consistency`. Behaviour below is stated for PostgreSQL and MySQL 8 InnoDB
unless another vendor is named; verify edge cases against the Hermitage suite for your version.

## 2. Storage engines

| Engine | Writes | Reads | Space | Examples |
|---|---|---|---|---|
| B+tree, update in place | random page writes plus WAL | one tree walk, good ranges | page slack from splits | InnoDB, PostgreSQL indexes, SQLite, WiredTiger |
| LSM, leveled compaction | sequential, high write amplification (about fanout x levels) | bloom filters for points; ranges merge levels | low | RocksDB default, LevelDB |
| LSM, tiered/universal | lower write amplification | higher read amplification | up to about 2x during compaction | Cassandra STCS, RocksDB universal, ScyllaDB |
| Bitcask (hash index + log) | append only | one seek | all keys must fit in RAM | Riak |
| Columnar | batch appends | fast scans, slow point lookups | compressed | Parquet, ClickHouse, DuckDB |

RUM: an engine trades read, update and memory (space) amplification; improving two worsens the third.
Pages: PostgreSQL 8 KB, InnoDB 16 KB. PostgreSQL stores tables as heaps with separate indexes
pointing at tuple ids; InnoDB clusters the table by primary key and every secondary index stores the
primary key, so a wide key bloats every secondary. Random UUIDv4 keys scatter inserts across the
B+tree (page splits, cache misses); prefer bigint identities or time-ordered UUIDv7 (PostgreSQL 18
has `uuidv7()`).

## 3. Durability

- WAL rule: the log record reaches stable storage before the data page, and the commit record
  before the commit is acknowledged.
- ARIES recovery: analysis (dirty pages and active transactions since the checkpoint), redo
  (repeat history), undo (roll back losers, logging compensation records). It supports steal (dirty
  pages of uncommitted transactions may be written) and no-force (commit does not flush data pages).
  PostgreSQL logs redo only: aborted tuple versions simply stay invisible. InnoDB has redo plus undo
  logs, and undo doubles as MVCC history.
- Checkpoints bound recovery time (`checkpoint_timeout`, `max_wal_size`); more frequent checkpoints
  mean more full-page images.
- fsync: after a failed fsync, Linux may drop the dirty pages and report success on retry; since the
  2018 "fsyncgate" fixes PostgreSQL panics and recovers from WAL instead of retrying.
- Torn pages: PostgreSQL `full_page_writes` (whole page logged at first change after a checkpoint);
  InnoDB doublewrite buffer. Disable only on storage with atomic page writes.
- Group commit shares one fsync among concurrent commits.

| PostgreSQL `synchronous_commit` | Commit returns after | Crash risk |
|---|---|---|
| `on` (default) | local WAL flush (and synchronous standby flush if configured) | none |
| `remote_apply` | standby has applied the commit | none; read-your-writes on the standby |
| `local` | local flush only | synchronous standby may lag |
| `off` | WAL written later by the WAL writer | lose up to 3 x `wal_writer_delay` of commits, no corruption |

MySQL: `innodb_flush_log_at_trx_commit=1` and `sync_binlog=1` for durability; `2` or `0` risk about a
second of commits.

## 4. MVCC

- PostgreSQL tuples carry `xmin` (inserter) and `xmax` (deleter or locker). A snapshot (xmin, xmax,
  in-progress list) sees a version if its inserter committed before the snapshot and its deleter did
  not. An `UPDATE` writes a new version; it is HOT (no new index entries) when no indexed column
  changes and the page has room, so set `fillfactor` 70-90 on update-heavy tables and watch
  `n_tup_hot_upd` vs `n_tup_upd`.
- VACUUM removes versions older than the oldest snapshot still needed (the horizon). Autovacuum
  triggers at `autovacuum_vacuum_threshold` + `autovacuum_vacuum_scale_factor` x rows (50 + 0.2 by
  default): far too lazy for big tables, so set a per-table scale factor around 0.01-0.05.
- Transaction IDs are 32-bit: anti-wraparound vacuums start at `autovacuum_freeze_max_age` (200M);
  monitor `SELECT datname, age(datfrozenxid) FROM pg_database;`. Near about 2 billion PostgreSQL
  warns, then refuses new transactions.
- Horizon holders cause bloat: long or idle-in-transaction sessions, abandoned replication slots,
  forgotten prepared transactions:

```sql
SELECT pid, state, now() - xact_start AS age, backend_xmin, left(query, 60)
FROM pg_stat_activity WHERE backend_xmin IS NOT NULL ORDER BY age(backend_xmin) DESC LIMIT 5;
SELECT slot_name, active, xmin, catalog_xmin FROM pg_replication_slots;
SELECT gid, prepared FROM pg_prepared_xacts;
```

- InnoDB updates rows in place and keeps old versions in undo logs; the purge thread drops them when
  no read view needs them. Long transactions grow the "History list length" in
  `SHOW ENGINE INNODB STATUS` and slow every read that walks version chains.
- Replicas: PostgreSQL standby queries conflict with replayed cleanup and get cancelled;
  `hot_standby_feedback=on` stops that by holding the primary's horizon (primary bloat), and
  `max_standby_streaming_delay` trades replay lag for fewer cancellations.

## 5. Locking

| PostgreSQL row lock | Taken by | Conflicts with |
|---|---|---|
| `FOR KEY SHARE` | foreign-key checks | `FOR UPDATE` |
| `FOR SHARE` | explicit | `FOR NO KEY UPDATE`, `FOR UPDATE` |
| `FOR NO KEY UPDATE` | `UPDATE` not touching key columns | `FOR SHARE`, `FOR NO KEY UPDATE`, `FOR UPDATE` |
| `FOR UPDATE` | `DELETE`, key-changing `UPDATE`, explicit | all four |

Job queue without double execution (PostgreSQL 9.5+, MySQL 8.0+ support `SKIP LOCKED`):

```sql
WITH next AS (
  SELECT id FROM jobs WHERE status = 'queued' ORDER BY run_at LIMIT 10
  FOR UPDATE SKIP LOCKED)
UPDATE jobs j SET status = 'running', started_at = now()
FROM next WHERE j.id = next.id
RETURNING j.*;
```

- Advisory locks: `pg_advisory_xact_lock(key)` (released at transaction end); session-level locks
  break under transaction-mode poolers such as PgBouncer.
- Deadlocks: PostgreSQL checks after `deadlock_timeout` (1 s) and aborts one transaction with 40P01;
  InnoDB detects immediately and rolls back one with error 1213 (SQLSTATE 40001). Prevent them with a
  consistent lock order (lock rows sorted by primary key with `SELECT ... ORDER BY id FOR UPDATE`).
- Bound waiting: `lock_timeout`, `statement_timeout`, `idle_in_transaction_session_timeout`; InnoDB
  `innodb_lock_wait_timeout` (50 s default, error 1205).
- Who blocks whom:

```sql
SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event_type, wait_event,
       now() - xact_start AS xact_age, left(query, 80) AS query
FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;
```

## 6. Isolation levels as vendors implement them

| Vendor | Default | What the levels really are | Retry signal |
|---|---|---|---|
| PostgreSQL | READ COMMITTED | RU behaves as RC. RC: new snapshot per statement; `UPDATE`/`DELETE`/`FOR UPDATE` wait for a concurrent writer, then re-check `WHERE` on the newest version. REPEATABLE READ = snapshot isolation (a concurrent update of a row you update raises 40001; no phantoms in reads; write skew allowed). SERIALIZABLE = SSI: aborts dangerous read-write dependency patterns with 40001, possibly at `COMMIT`; `SERIALIZABLE READ ONLY DEFERRABLE` never aborts | 40001, 40P01 |
| MySQL InnoDB | REPEATABLE READ | Plain `SELECT` reads a snapshot taken at the first read; locking reads, `UPDATE` and `DELETE` read the latest committed row ("current read") and take next-key (record + gap) locks. Read-then-write loses updates. SERIALIZABLE turns plain `SELECT` into `FOR SHARE` when autocommit is off | 1213 (40001), 1205 |
| Oracle | READ COMMITTED | SERIALIZABLE is snapshot isolation: ORA-08177 on write conflicts; write skew allowed | ORA-08177 |
| SQL Server | READ COMMITTED (locking) | RCSI (`READ_COMMITTED_SNAPSHOT ON`): statement snapshots. SNAPSHOT: SI with update-conflict error 3960. REPEATABLE READ and SERIALIZABLE are lock-based (key-range locks) | 1205 (deadlock victim), 3960 |
| CockroachDB | SERIALIZABLE | serializable by default; READ COMMITTED available in recent versions | 40001 |

## 7. Anomalies as histories

Notation: r1[x]=v read by T1, w2[x] write by T2, c commit, a abort. "ok" = prevented.

| Anomaly | History | PG RC | PG RR | PG SER | InnoDB RR | InnoDB SER | Oracle SER | SQL Server SNAPSHOT |
|---|---|---|---|---|---|---|---|---|
| Dirty read | w1[x] r2[x] a1 | ok | ok | ok | ok | ok | ok | ok |
| Non-repeatable read | r1[x]=0 w2[x]=1 c2 r1[x]=1 | allowed | ok | ok | ok (plain reads) | ok | ok | ok |
| Lost update | r1[x]=10 r2[x]=10 w1[x]=9 c1 w2[x]=9 c2 | allowed | ok (40001) | ok | allowed | ok (deadlock) | ok (08177) | ok (3960) |
| Read skew | r1[x]=50 w2[x]=25 w2[y]=75 c2 r1[y]=75 | allowed | ok | ok | ok for read-only transactions | ok | ok | ok |
| Write skew | r1[x,y] r2[x,y] w1[x] w2[y] c1 c2 | allowed | allowed | ok | allowed | ok | allowed | allowed |
| Phantom read | r1[P] w2[insert in P] c2 r1[P] | allowed | ok | ok | ok (plain); locking reads block the insert | ok | ok | ok |
| Phantom write skew | r1[P]=empty r2[P]=empty w1[insert in P] w2[insert in P] | allowed | allowed | ok | allowed (ok if the check uses `FOR UPDATE`) | ok | allowed | allowed |
| Read-only anomaly | below | allowed | allowed | ok | allowed | ok | allowed | allowed |

Read-only anomaly (Fekete, O'Neil and O'Neil 2004): checking x = 0, savings y = 0. T2 (withdraw 10,
fee 1 if x + y - 10 < 0) reads x = 0, y = 0. T1 deposits 20 into y and commits. T3 (read-only report)
reads x = 0, y = 20 and commits. T2 writes x = -11 and commits. Final state implies T2 before T1, but
T3 saw T1 without T2: no serial order explains it. Snapshot isolation allows it; SSI aborts one.

## 8. Fix menu

| Problem | Fix |
|---|---|
| Counter or stock decrement | atomic conditional update: `UPDATE inventory SET stock = stock - $2 WHERE sku = $1 AND stock >= $2 RETURNING stock;` (zero rows = insufficient) |
| Read, decide, write one row | `SELECT ... FOR UPDATE`, or optimistic version column (`... WHERE id = $1 AND version = $2`, zero rows = retry) |
| Invariant over a predicate | constraints: `UNIQUE`, partial unique index (`ON bookings (room_id) WHERE active`), exclusion constraint `EXCLUDE USING gist (room_id WITH =, during WITH &&)` (needs `btree_gist`) |
| Write skew on rows that may not exist | materialise the conflict: a row per shift/room/account locked `FOR UPDATE` by every writer |
| Many interacting invariants | SERIALIZABLE plus a bounded retry loop with an idempotent body |

```go
// pgx v5: retry the whole transaction on serialization failure or deadlock.
func WithSerializable(ctx context.Context, pool *pgxpool.Pool, body func(pgx.Tx) error) error {
	for attempt := 1; ; attempt++ {
		err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{IsoLevel: pgx.Serializable}, body)
		var pgErr *pgconn.PgError
		retry := errors.As(err, &pgErr) && (pgErr.Code == "40001" || pgErr.Code == "40P01")
		if !retry || attempt == 5 {
			return err
		}
		select { // full jitter, growing cap
		case <-time.After(time.Duration(rand.Int64N(int64(10*time.Millisecond) << attempt))):
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}
```

The body does database work only; emails, payments and HTTP calls go after commit (or through an
outbox), because a retry re-runs everything inside. The commit itself can fail with 40001.

## 9. Reproduce before fixing

- Two psql sessions with numbered steps (section 11) reproduce most anomalies deterministically.
- pgbench custom scripts drive concurrency: `-f script.pgbench -c 16 -j 4 -T 60`, variables with
  `\set` and `-D`, query results with `\gset`, branching with `\if`; PostgreSQL 15+ adds
  `--max-tries` and `--failures-detailed` to retry and count serialization failures.
- Hermitage (github.com/ept/hermitage) documents the expected behaviour per vendor and level.
- For histories recorded from production-like tests, check anomalies with Elle
  (`distributed-consensus-consistency`).

## 10. Pitfalls

- Trusting the ORM default: most use the database default (READ COMMITTED on PostgreSQL, REPEATABLE
  READ on MySQL) and none make read-modify-write safe.
- Read-modify-write in application code (`stock = read(); write(stock - 1)`).
- SERIALIZABLE without a retry loop, or retrying only the statement instead of the transaction.
- Retries that repeat non-idempotent side effects.
- Assuming REPEATABLE READ means the same thing across vendors: PostgreSQL's prevents lost updates,
  InnoDB's does not.
- Long transactions (or idle-in-transaction sessions) silently stopping vacuum and purge.

## 11. Worked example: oversell and on-call write skew in PostgreSQL

```sql
CREATE TABLE inventory (sku int PRIMARY KEY, stock int NOT NULL CHECK (stock >= 0));
CREATE TABLE orders (id bigserial PRIMARY KEY, sku int NOT NULL);
INSERT INTO inventory VALUES (1, 1);
```

| Step | Session A | Session B |
|---|---|---|
| 1 | `BEGIN; SELECT stock FROM inventory WHERE sku = 1;` returns 1 | |
| 2 | | `BEGIN; SELECT stock FROM inventory WHERE sku = 1;` returns 1 |
| 3 | `UPDATE inventory SET stock = 0 WHERE sku = 1; INSERT INTO orders (sku) VALUES (1); COMMIT;` | |
| 4 | | `UPDATE inventory SET stock = 0 WHERE sku = 1; INSERT INTO orders (sku) VALUES (1); COMMIT;` |

READ COMMITTED: two orders for one unit (the CHECK never fires: both wrote 0). REPEATABLE READ
(`BEGIN ISOLATION LEVEL REPEATABLE READ`): step 4's `UPDATE` fails with "could not serialize access
due to concurrent update" (40001); the retry reads 0 and refuses. The fix that works at any level:
`UPDATE inventory SET stock = stock - 1 WHERE sku = 1 AND stock >= 1 RETURNING stock;` and insert the
order only if a row came back. B blocks on A's row lock, re-checks the `WHERE` on stock 0 and updates
nothing.

```sql
CREATE TABLE doctors (shift_id int, slot int, on_call bool NOT NULL, PRIMARY KEY (shift_id, slot));
INSERT INTO doctors SELECT s, k, true FROM generate_series(1, 500) s, generate_series(1, 2) k;
```

| Step | Session A | Session B |
|---|---|---|
| 1 | `BEGIN ISOLATION LEVEL REPEATABLE READ; SELECT count(*) FROM doctors WHERE shift_id = 1 AND on_call;` returns 2 | |
| 2 | | same, returns 2 |
| 3 | `UPDATE doctors SET on_call = false WHERE shift_id = 1 AND slot = 1;` | `UPDATE doctors SET on_call = false WHERE shift_id = 1 AND slot = 2;` |
| 4 | `COMMIT;` | `COMMIT;` both succeed: nobody is on call |

The same happens under READ COMMITTED. Under SERIALIZABLE, B fails with "could not serialize access
due to read/write dependencies among transactions" (40001); its retry counts 1 and refuses. Lock-based
alternative: `SELECT slot FROM doctors WHERE shift_id = 1 AND on_call FOR UPDATE` and count rows in
the application (`FOR UPDATE` is not allowed with aggregates); under READ COMMITTED B blocks, then
gets only the row that still matches.

Measure the retry cost with pgbench (`oncall.pgbench`):

```
\set shift random(1, :nshifts)
\set slot random(1, 2)
BEGIN ISOLATION LEVEL SERIALIZABLE;
SELECT count(*) AS n FROM doctors WHERE shift_id = :shift AND on_call \gset
\if :n >= 2
UPDATE doctors SET on_call = false WHERE shift_id = :shift AND slot = :slot;
\else
UPDATE doctors SET on_call = true WHERE shift_id = :shift;
\endif
COMMIT;
```

```bash
for n in 5 50 500; do
  pgbench -n -c 16 -j 4 -T 60 -D nshifts=$n --max-tries=10 --failures-detailed -f oncall.pgbench shop
done
```

Report throughput and the retried share ("number of transactions retried" over processed) per
contention level. Expect retries to climb as `nshifts` shrinks; if they exceed your budget at peak,
switch the hot path to the materialised-conflict lock. For the correctness run, drop the `\else`
branch, run once with REPEATABLE READ and once with SERIALIZABLE, then check
`SELECT shift_id FROM doctors GROUP BY shift_id HAVING NOT bool_or(on_call);`: rows under
REPEATABLE READ are write-skew violations; SERIALIZABLE must return none.

Related: `sql-query-tuning`, `zero-downtime-migrations`, `distributed-consensus-consistency`, `caching-and-system-tradeoffs`, `concurrent-data-structures`, hub `cs-foundations`
