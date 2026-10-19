# Diagnostic queries

Read-only catalog and statistics queries. Statistics counters are per server and reset with
`pg_stat_reset()` / restarts on some managed services: check `stats_reset` before trusting a zero.

```sql
SELECT stats_reset FROM pg_stat_database WHERE datname = current_database();
```

## PostgreSQL

### Top statements (pg_stat_statements)

```sql
-- by total time (default triage)
SELECT queryid, calls, round(total_exec_time::numeric) AS total_ms,
       round(mean_exec_time::numeric, 2) AS mean_ms, round(stddev_exec_time::numeric, 2) AS stddev_ms,
       rows / nullif(calls, 0) AS rows_per_call,
       round(100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0), 1) AS hit_pct,
       temp_blks_written, left(query, 120) AS query
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20;

-- statements that spill to disk
SELECT queryid, calls, temp_blks_written, left(query, 120)
FROM pg_stat_statements WHERE temp_blks_written > 0 ORDER BY temp_blks_written DESC LIMIT 20;

-- reset one statement's counters after deploying a fix (PG12+ signature: userid, dbid, queryid)
SELECT pg_stat_statements_reset(0, 0, <queryid>);
```

### Tables read mostly by sequential scans

```sql
SELECT relname, seq_scan, seq_tup_read, idx_scan, n_live_tup,
       seq_tup_read / nullif(seq_scan, 0) AS rows_per_seq_scan
FROM pg_stat_user_tables
WHERE seq_scan > 0
ORDER BY seq_tup_read DESC LIMIT 20;
```

Large `rows_per_seq_scan` on a big table with frequent scans = candidate for an index (confirm with
the statement's plan).

### Unused indexes

```sql
SELECT s.schemaname, s.relname AS table_name, s.indexrelname AS index_name, s.idx_scan,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.idx_scan = 0
  AND NOT i.indisunique AND NOT i.indisprimary      -- constraints are used even when never scanned
ORDER BY pg_relation_size(s.indexrelid) DESC;
```

Run on the primary and every replica (counters are per node; read traffic often hits replicas only),
over a full business cycle (month-end jobs). PG16+ also has `last_idx_scan`.

### Exact duplicate indexes

```sql
SELECT pg_size_pretty(sum(pg_relation_size(idx))::bigint) AS size,
       (array_agg(idx))[1] AS idx1, (array_agg(idx))[2] AS idx2, (array_agg(idx))[3] AS idx3
FROM (SELECT indexrelid::regclass AS idx,
             indrelid::text || E'\n' || indclass::text || E'\n' || indkey::text || E'\n' ||
             coalesce(indexprs::text, '') || E'\n' || coalesce(indpred::text, '') AS key
      FROM pg_index) sub
GROUP BY key HAVING count(*) > 1
ORDER BY sum(pg_relation_size(idx)) DESC;
```

### Prefix-redundant indexes (review each pair before dropping)

```sql
SELECT a.indexrelid::regclass AS maybe_redundant, b.indexrelid::regclass AS longer_index
FROM pg_index a
JOIN pg_index b ON a.indrelid = b.indrelid AND a.indexrelid <> b.indexrelid
WHERE NOT a.indisunique
  AND a.indpred IS NULL AND a.indexprs IS NULL AND b.indpred IS NULL
  AND a.indnatts = a.indnkeyatts                     -- a has no INCLUDE columns
  AND a.indnkeyatts < b.indnkeyatts
  AND (b.indkey::text || ' ') LIKE (a.indkey::text || ' %');
```

Before dropping `maybe_redundant`, compare operator classes (`indclass`), sort directions
(`indoption`) and collations, and check the longer index is not much wider (a 4-column index is
a worse fit for a query that only needs the first column if rows are wide).

### Foreign keys without a supporting index

```sql
SELECT c.conrelid::regclass AS table_name, c.conname AS fk,
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum) AS columns
FROM pg_constraint c
WHERE c.contype = 'f'
  AND NOT EXISTS (
    SELECT 1 FROM pg_index i
    WHERE i.indrelid = c.conrelid
      AND (i.indkey::text || ' ') LIKE (array_to_string(c.conkey, ' ') || ' %'))
ORDER BY 1;
```

Reports FKs whose columns are not a leading prefix (in the same order) of some index.

### Invalid indexes (failed CREATE INDEX CONCURRENTLY)

```sql
SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
-- DROP INDEX CONCURRENTLY <name>; then rebuild
```

### Vacuum and analyze health

```sql
SELECT relname, n_live_tup, n_dead_tup, n_mod_since_analyze,
       last_autovacuum, last_autoanalyze, last_analyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC LIMIT 20;
```

`n_mod_since_analyze` large relative to `n_live_tup` = stale statistics: run `ANALYZE <table>`.

### Column and extended statistics

```sql
SELECT attname, null_frac, n_distinct, most_common_vals, most_common_freqs, correlation
FROM pg_stats WHERE tablename = 'orders' AND attname IN ('tenant_id', 'status', 'created_at');

SELECT statistics_name, attnames, dependencies, n_distinct
FROM pg_stats_ext WHERE tablename = 'orders';
```

`correlation` near +-1 on a time column: BRIN is viable. `n_distinct` negative values are a fraction of
rows (-1 = unique).

### What is running and what is blocked

```sql
SELECT pid, now() - query_start AS runtime, state, wait_event_type, wait_event,
       pg_blocking_pids(pid) AS blocked_by, left(query, 100) AS query
FROM pg_stat_activity
WHERE state <> 'idle' AND query_start < now() - interval '30 seconds'
ORDER BY runtime DESC;
```

### Size overview

```sql
SELECT relname, pg_size_pretty(pg_table_size(relid)) AS table_size,
       pg_size_pretty(pg_indexes_size(relid)) AS indexes_size, n_live_tup
FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 20;
```

### Hypothetical index trial (HypoPG)

```sql
CREATE EXTENSION IF NOT EXISTS hypopg;
SELECT * FROM hypopg_create_index('CREATE INDEX ON orders (tenant_id, status, created_at DESC, id DESC)');
EXPLAIN SELECT id FROM orders WHERE tenant_id = 42 AND status = 'open' ORDER BY created_at DESC, id DESC LIMIT 50;
SELECT hypopg_reset();
```

Hypothetical indexes exist only in the current session and only for plain `EXPLAIN`.

## MySQL 8.x

```sql
SELECT * FROM sys.statement_analysis LIMIT 20;                 -- normalized statements by latency
SELECT * FROM sys.statements_with_full_table_scans LIMIT 20;
SELECT * FROM sys.statements_with_sorting LIMIT 20;
SELECT * FROM sys.statements_with_temp_tables LIMIT 20;
SELECT * FROM sys.schema_unused_indexes;                       -- since last restart
SELECT * FROM sys.schema_redundant_indexes;

ANALYZE TABLE orders;                                          -- refresh index statistics
ANALYZE TABLE orders UPDATE HISTOGRAM ON status WITH 64 BUCKETS;   -- non-indexed skewed column

SET optimizer_trace = 'enabled=on';
SELECT ...;                                                    -- the query under study
SELECT TRACE FROM information_schema.OPTIMIZER_TRACE;          -- why the plan was chosen
SET optimizer_trace = 'enabled=off';

ALTER TABLE orders ALTER INDEX ix_orders_status INVISIBLE;     -- test dropping without dropping
```

Slow log analysis: `pt-query-digest /var/log/mysql/slow.log | head -100` (Percona Toolkit).

## SQLite

```sql
EXPLAIN QUERY PLAN SELECT ...;   -- SCAN t = full scan; SEARCH t USING INDEX ix (a=?) = index lookup
ANALYZE;                         -- populates sqlite_stat1 for the planner
PRAGMA optimize;                 -- cheap; run before closing long-lived connections
```
