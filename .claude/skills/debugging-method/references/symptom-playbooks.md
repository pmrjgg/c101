# Symptom playbooks

Each playbook: what to collect, the usual causes ranked by frequency in production systems, and the
experiment that discriminates between them.

## Crash: segfault, access violation, abort

Collect: core dump or crash report, exact binary and symbols, input that triggered it.
1. `bt full` from the core; note the faulting address (near 0 = null deref; looks like freed heap
   pattern such as `0xdeadbeef`/`0xfeeefeee` or ASan poison = use-after-free).
2. Rebuild with ASan + UBSan and rerun the input; ASan reports the allocation and free stacks.
3. Usual causes: use-after-free (iterator/reference invalidation, callback after owner destroyed),
   buffer overflow (off-by-one, wrong size units), null from an unchecked error path, stack overflow
   from unbounded recursion (deep input nesting), ABI mismatch between libraries.
4. Discriminating experiment: does the crash move or vanish with ASan, with `-O0`, with a different
   allocator? Moving crashes indicate memory corruption earlier than the crash site.

## Hang or deadlock

Collect: two all-thread stack dumps 10 s apart; CPU usage during the hang.
- CPU ~0%: blocked. Look for threads waiting on locks held by other waiting threads (cycle = deadlock),
  waits on network/IO without timeouts, waits on a pool with no free workers (pool exhaustion: tasks
  waiting for tasks in the same pool), channel sends with no receiver.
- CPU ~100% on one core: livelock or infinite loop; the same frames in both dumps locate it.
- Async runtimes: a blocking call on the event loop stalls everything; look for sync I/O or long
  computation in async functions (asyncio debug mode `PYTHONASYNCIODEBUG=1` logs slow callbacks).
- Experiment: add timeouts to every wait in the suspected path; the one that fires names the culprit.

## Memory growth / leak

Collect: RSS over time under steady load; two heap snapshots at different times.
1. Distinguish leak from high-water mark: does memory return after load stops? Allocator retention
   (glibc arenas, Go heap scavenging) can look like a leak; check heap-in-use, not just RSS.
2. Diff the snapshots (pprof `-diff_base`, MAT dominator tree, memray, heaptrack): the type that grows
   is the lead.
3. Usual causes: unbounded caches/maps keyed by request data, listeners or callbacks never removed,
   goroutines/threads/tasks blocked forever (each holds its stack), global lists of "recent" items,
   reference cycles with finalizers, large objects retained by a closure or a log context.
4. Experiment: run N identical iterations and check that live heap returns to baseline after each.

## Wrong result (deterministic)

1. Find the first point where data is wrong: binary search over pipeline stages with dumps or
   assertions.
2. Usual causes: off-by-one, wrong units, integer division/truncation, rounding, mutated shared input,
   stale cache key missing a dimension, wrong default value, sign errors, implicit type coercion.
3. Compare against an independent computation (spreadsheet, naive implementation, previous version)
   for the minimal input.

## Wrong result only in optimized or release builds

- Undefined behaviour (C/C++/unsafe Rust): sanitizers, Miri, `-fwrapv`/`-fno-strict-aliasing` as
  diagnostics (if they "fix" it, you have UB to find, not a fix).
- Floating point: `-ffast-math`, FMA contraction, x87 vs SSE, different summation order under
  vectorization or parallel reduction.
- Uninitialized memory that happened to be zero in debug.
- Timing changes exposing races.

## Passes locally, fails in CI

Diff the environments systematically: OS image, CPU count (parallelism changes timing and test order),
locale and TZ, file system case sensitivity, missing services or different versions, environment
variables and secrets presence, network restrictions, clock (CI machines may run in UTC), resource
limits (memory, open files), test sharding. Reproduce in the CI image locally before theorizing.

## Intermittent failure

1. Measure the rate (loop the test; record seed and order).
2. Increase the rate to make experiments cheap: stress CPU, add parallelism, shuffle order, inject
   small random delays (`rr --chaos`, sleep injection at suspected interleaving points).
3. Classify with the flaky-test causes table (`testing-strategy`): order, time, concurrency, external
   state, resources, randomness, environment.
4. A fix is verified only when the post-fix run count meets the rule-of-three bound for the measured
   pre-fix rate.

## Regression after a change or upgrade

- Code change: `git bisect run ./repro.sh`.
- Dependency upgrade: bisect the lockfile (apply half the bumps), then read the changelog and diff of
  the identified dependency between the two versions.
- Infrastructure change (new image, kernel, runtime): compare with the previous image pinned; check
  default changes (TLS versions, DNS resolution, cgroup limits, JVM ergonomics).
- Config change: diff deployed configs between last good and first bad deploy.

## Performance regression

1. Confirm with statistics (median + CI) that it is real (see `performance-optimization`).
2. Bisect with a benchmark predicate that exits 1 when slower than a threshold midway between the two
   medians.
3. Differential profile between good and bad revisions (pprof `-diff_base`, differential flame graphs).

## Data corruption

1. Stop the bleeding first: identify writers to the corrupted data and disable or guard them.
2. Find the earliest corrupted record (timestamps, audit logs, WAL/binlog) and the writer and code
   version active then.
3. Usual causes: lost updates (read-modify-write without locking/versioning), partial writes without
   transactions, encoding round-trips, timezone conversions on write, migrations/backfills with bugs,
   two services writing the same field.
4. Repair plan is a separate, reviewed change with a dry run and a backup.

## Network and integration failures

- Timeouts vs connection refused vs reset vs TLS errors each point to different layers (app slow, nothing
  listening, peer/proxy closing, certificate/protocol mismatch).
- `curl -v`, `openssl s_client -connect host:443 -servername host`, `dig`, `tcpdump` to see what is
  actually exchanged.
- Check retries and timeouts compose: client timeout shorter than the server's processing time
  produces duplicate work and confusing logs.
