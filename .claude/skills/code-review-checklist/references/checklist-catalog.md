# Extended review checklist catalog

Deep checks per dimension and per change type. Use the SKILL.md checklist first; come here when the
diff touches one of these areas or when a dimension needs a second, deeper pass.

## A. Correctness, deeper

### Arithmetic and numbers
- Division by zero on empty collections (`sum / len(xs)`), averages of zero samples.
- Overflow in intermediate values: `(a + b) / 2` for midpoints (use `a + (b - a) / 2`), `a * b` before a
  division, timestamp in ms into 32-bit ints (overflows in 24.8 days), sizes in `int` on 32-bit targets.
- Unsigned underflow: `len - 1` when `len == 0` (`usize`, `size_t`, `uint`).
- Floating point: accumulation error in long sums (Kahan or `math.fsum`), `NaN` comparisons always false
  (sorting with NaN breaks comparators), `-0.0`, `float -> int` casts saturating (Rust) vs UB (C/C++).
- Money: integer minor units or decimal types; currency carried with the amount; rounding policy stated.
- Percentages and ratios: denominators that can be zero; percentage points vs percent.

### Collections and iteration
- Off-by-one in slicing (`[i:j]` excludes `j`), pagination (`offset = page * size` with 1-based pages).
- Stable vs unstable sort when ties matter; comparator consistency (transitivity, antisymmetry).
- Hash iteration order assumed stable (Go maps randomize; Python dicts keep insertion order since 3.7;
  JS objects order integer-like keys first).
- Dedup by object identity vs value equality; `equals`/`hashCode` (or `Eq`/`Hash`) consistency.
- Removing from a list while iterating forward; `ConcurrentModificationException`; invalidated iterators in C++.

### State and lifecycle
- State machines: list every state x event; check that illegal transitions are rejected, not ignored.
- Initialization order: use before init, partially constructed objects escaping the constructor.
- Caches: key includes every input that affects the value (user, locale, version, feature flag).
- Feature flags: both branches tested; flag removal plan; default when the flag service is down.
- Idempotency keys: scope (per user? per endpoint?), retention window longer than the client retry window.

### Time
- Store UTC, convert at the edges; never store local wall time without the zone.
- Durations via monotonic clocks (`time.monotonic()`, `Instant`, `System.nanoTime`, Go's monotonic reading
  in `time.Now()` is stripped by `Round(0)`, serialization and `t.Equal` semantics differ from `==`).
- Day arithmetic across DST (a day is not always 86400 s); end-of-month rollovers (Jan 31 + 1 month).
- Clock skew between hosts; JWT `exp`/`nbf` leeway; distributed ordering by timestamp is unsafe.

## B. Error handling, deeper

- Error classes: distinguish retryable (timeouts, 429, 503, connection reset) from permanent
  (400, 404, validation, auth). Retrying a permanent error amplifies load.
- Retry budget: max attempts x per-attempt timeout must fit inside the caller's deadline.
- Backoff with full jitter: `sleep = random(0, min(cap, base * 2^attempt))`.
- Circuit breakers and fallbacks: fallback values must be safe (never "allow" on authz failure).
- Fail-open vs fail-closed: authorization, rate limits, fraud checks must fail closed.
- Logging: log once at the boundary that handles the error, not at every layer (log storms).
- Partial batch failure: report which items failed; do not fail the whole batch silently or succeed it silently.
- Process exit codes: CLIs exit non-zero on failure; scripts use `set -euo pipefail`.

## C. Concurrency, deeper

- Interleaving table technique: write threads as columns, time as rows, and place each shared read and
  write; a finding needs one concrete bad interleaving.
- Double-checked locking without proper memory ordering (Java needs `volatile`; C++ needs acquire/release).
- Condition variables: wait in a `while` loop on the predicate (spurious wakeups); notify under or
  after the state change.
- Thread pools: tasks that block on other tasks in the same bounded pool deadlock.
- Async cancellation: cleanup in `finally` may not run if the task is cancelled at an await point in some
  runtimes; dropping a Rust future cancels it at the last `.await` (cancel safety of `select!` branches).
- Backpressure: unbounded channels or queues between producer and consumer of different speeds.
- Singletons and global state initialized lazily from multiple threads.
- File system races: check-then-open (TOCTOU), temp files with predictable names, rename atomicity
  (atomic on the same filesystem only).
- Distributed locks: lease expiry while holder still works (fencing tokens required), clock dependence.

## D. API design, deeper

- Parameter order of same-typed arguments (`copy(dst, src)` vs `copy(src, dst)`); prefer named/struct args.
- Return types: do not return `null` and empty collection with different meanings without documenting.
- Errors as part of the contract: which errors can callers handle, and are they typed?
- Pagination: cursor-based for mutable datasets; stable sort key; max page size enforced server-side.
- Versioning: additive changes only within a version; deprecation window and telemetry on old usage.
- Protobuf/Avro/Thrift: never reuse or renumber fields; mark removed fields `reserved`; new fields optional.
- JSON: unknown fields tolerated by readers; nullable vs absent distinguished if semantics differ.
- CLI: flags are API too; renamed flags keep a deprecated alias; exit codes documented; stdout for data,
  stderr for logs.
- Config: new keys have defaults; invalid config fails at startup, not at first use.

## E. Tests, deeper

- Test isolation: no order dependence, no shared temp dirs, no fixed ports, no global singletons mutated.
- Test data builders over giant fixtures; fixtures not shared-and-mutated across tests.
- Contract tests for service boundaries (consumer-driven, e.g. Pact) when two teams own the two sides.
- Integration tests against real dependencies in containers (Testcontainers) instead of mocks for DBs.
- Snapshot tests: reviewed diffs, small snapshots, deterministic serialization (sorted keys, fixed time).
- Coverage of error paths: at least one test per distinct error branch the change introduced.

## F. Change-type checklists

### Database migrations
- [ ] Reversible or explicitly marked irreversible with a backup/restore plan.
- [ ] No long locks on large tables: PostgreSQL `CREATE INDEX CONCURRENTLY`, add column nullable without
      volatile default, `NOT VALID` constraint then `VALIDATE CONSTRAINT`; MySQL online DDL options.
- [ ] Backfills in batches with throttling, resumable, idempotent.
- [ ] Code deployed before migration tolerates both old and new schema (expand/contract).
- [ ] New queries have supporting indexes; `EXPLAIN (ANALYZE, BUFFERS)` on realistic data size.

### Frontend
- [ ] No `dangerouslySetInnerHTML` / `v-html` / `innerHTML` with untrusted data; URL schemes allowlisted
      for `href` (`javascript:`).
- [ ] Accessibility: labels for inputs, keyboard navigation, focus management in dialogs, contrast.
- [ ] Loading, empty and error states rendered; double-submit prevented.
- [ ] Effects clean up subscriptions and timers; dependency arrays complete; no state updates after unmount.
- [ ] Bundle impact of new dependencies; images sized; no blocking third-party scripts.

### Data pipelines and analytics
- [ ] Schema drift handled (new/missing columns); nulls and duplicates handled explicitly.
- [ ] Idempotent re-runs (overwrite partitions, merge keys), late-arriving data policy.
- [ ] Join cardinality checked (fan-out joins silently multiply rows); row counts asserted between stages.
- [ ] Time zone of event time vs processing time.

### ML and numerical code
- [ ] Train/test leakage (fitting scalers on full data, time-series shuffling).
- [ ] Random seeds set and recorded; nondeterministic GPU kernels acknowledged.
- [ ] Numerical stability: log-sum-exp, softmax with max subtraction, epsilon in divisions.
- [ ] Shapes and dtypes asserted at boundaries; silent broadcasting.

### Infrastructure as code and CI
- [ ] Least privilege IAM; no wildcard actions/resources without justification.
- [ ] No public buckets, open security groups (`0.0.0.0/0` on admin ports), unencrypted storage.
- [ ] Destroy/replace operations in the plan output reviewed (`terraform plan` shows `-/+`).
- [ ] CI: third-party actions pinned by commit SHA; `permissions:` minimal; no untrusted input interpolated
      into `run:` scripts; `pull_request_target` does not check out PR code with secrets available.

### Shell scripts
- [ ] `set -euo pipefail`; variables quoted (`"$var"`); arrays for argument lists.
- [ ] `mktemp` for temp files; `trap 'rm -rf "$tmp"' EXIT`.
- [ ] No parsing of `ls`; `find -print0 | xargs -0`; `--` before user-supplied paths.
- [ ] `shellcheck` clean.

## G. Readability, deeper

- Function does one thing at one level of abstraction; a function mixing HTTP parsing, business rules and
  SQL is a finding only if it causes a concrete problem (untestable branch, duplicated rule).
- Boolean parameters at call sites (`send(msg, true, false)`) hide meaning; suggest enums or named args.
- Magic numbers with domain meaning get names; units in names (`timeout_ms`).
- Error messages say what failed, with which input, and what the caller can do.
- Consistency beats local preference: follow the file's existing conventions.
