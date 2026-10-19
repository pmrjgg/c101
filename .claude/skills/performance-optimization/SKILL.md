---
name: performance-optimization
description: "Measure-first performance engineering: frame the metric, workload and target, bound the problem with back-of-envelope numbers, benchmark with statistics (warmup, repetitions, medians, bootstrap confidence intervals, sample-size formula, bundled compare script), profile with the right tool per language (perf, Instruments/xctrace, samply, pprof, async-profiler/JFR, py-spy, criterion, JMH, BenchmarkTools, hyperfine), fix in the order algorithm > data layout > I/O > parallelism > micro-optimizations, reduce allocations and cache misses, and report before/after with confidence intervals. Load when code is too slow or memory-hungry, when claiming or reviewing a speedup, or when a performance regression appears."
when_to_use: "A latency, throughput, CPU, memory or startup target is missed; someone claims X is faster; a benchmark regressed in CI; choosing between implementations on performance grounds."
---

# Performance optimization

No optimization without a baseline measurement, a profile that points at the cost, and a target.
No claim of improvement without a confidence interval. Correctness tests stay green throughout.

## 1. Frame the problem

Fill this before touching code; an unanswerable field is an Open doubt for the caller.

```markdown
Metric:      p99 latency of POST /quote | throughput rows/s | wall time of job | peak RSS | allocations | startup
Workload:    exact input (path, size, distribution), concurrency, warm or cold cache
Target:      p99 < 120 ms at 300 rps | 2x faster | < 2 GB RSS   (and why: SLO, cost, user complaint)
Baseline:    current value with CI, revision SHA
Environment: CPU model, cores, OS, runtime/compiler version, build flags (release, LTO, -O2), power state
Constraints: memory budget, no new dependencies, API unchanged, determinism required, ...
```

Measure the build users run: release/optimized builds, production-like configuration, debug assertions
off, logging at production level. A profile of a debug build is not evidence.

## 2. Bound the problem (back-of-envelope)

Compare the measurement to what the hardware can do. If you are within 2x of a hard bound, the
remaining work is architectural (do less), not tuning.

| Operation (2020s server/laptop, order of magnitude) | Cost |
|---|---|
| L1 hit / L2 hit / L3 hit | ~1 ns / ~4 ns / ~10-20 ns |
| DRAM access (cache miss) | ~80-120 ns |
| Branch mispredict | ~15-20 cycles (~5 ns) |
| Uncontended mutex lock+unlock; uncontended atomic RMW | ~20 ns; ~5-20 ns |
| Cache line bouncing between cores (contended atomic) | ~50-200 ns per transfer |
| Small heap allocation + free (fast path) | ~20-50 ns; much more under contention or fragmentation |
| Trivial syscall; thread context switch | ~0.1-0.5 us; ~1-5 us |
| NVMe 4 KiB random read | ~20-100 us |
| Same-datacenter round trip; cross-continent | ~0.2-0.5 ms; ~70-150 ms |
| Memory bandwidth: one core; one socket | ~10-20 GB/s; ~50-200+ GB/s |
| NVMe sequential read | ~3-7 GB/s |

Useful laws:
- **Amdahl**: speedup = 1 / ((1 - p) + p / s). Optimizing 30% of runtime by 10x gives 1.37x overall;
  the remaining 70% caps you at 1.43x however fast the 30% becomes.
- **Little**: L = lambda W (items in system = arrival rate x time in system). 300 rps at 80 ms needs 24
  requests in flight; a pool of 16 connections is the bottleneck before CPU is.
- **Roofline**: attainable FLOP/s = min(peak FLOP/s, arithmetic intensity x memory bandwidth). Low
  FLOPs per byte means memory-bound: fix data movement, not arithmetic.
- **Throughput from per-item cost**: 1 us per item = 1M items/s per core; if the target is 10M/s on 8
  cores, the per-item budget is 0.8 us including everything.

## 3. Benchmark methodology

Choose the harness by scope:

| Scope | Tool |
|---|---|
| Whole program / CLI | `hyperfine --warmup 3 --runs 30 -N 'old args' 'new args' --export-json out.json` (runs all of A, then B; when drift matters, alternate one hyperfine invocation per revision with `--export-json before.json` / `after.json`) |
| Rust function | criterion (`cargo bench -- --save-baseline before`, then `--baseline before`), divan; gungraun (formerly iai-callgrind; valgrind-based instruction counts) in noisy CI |
| Go function | `go test -run '^$' -bench 'BenchmarkParse$' -benchmem -count 10 > new.txt; benchstat old.txt new.txt` |
| JVM | JMH (`@Fork(3) @Warmup(iterations=5) @Measurement(iterations=10)`, return results or use `Blackhole`) |
| Python | pyperf (`python -m pyperf timeit`, `pyperf compare_to old.json new.json`), pytest-benchmark (`--benchmark-autosave`, `--benchmark-compare`) |
| C/C++ | Google Benchmark (`benchmark::DoNotOptimize`, `--benchmark_repetitions=20`) |
| Julia | BenchmarkTools `@benchmark f($x)` (interpolate globals with `$`) |
| Service | load generator with an open model (constant arrival rate): k6 `constant-arrival-rate`, wrk2 `-R`, vegeta `-rate`; closed-loop tools understate tail latency (coordinated omission) |

Noise control checklist:
- [ ] Same machine, same build flags, same input for both variants; inputs not constant-folded by the
      compiler (pass through `black_box`/`Blackhole`/`DoNotOptimize`).
- [ ] Warmup (JIT, caches, lazy init) excluded from measurement; state cold vs warm cache explicitly.
- [ ] Interleave variants (ABAB...) or randomize order to cancel drift and thermal effects.
- [ ] Linux: record the governor (`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`) and pin
      with `taskset -c 2`; setting the performance governor or disabling turbo needs root, so list it as
      an Open doubt for the user instead of running it; macOS: record power source and Low Power Mode
      (`pmset -g batt`, `pmset -g | grep lowpowermode`) and report them,
      do not trust laptop numbers under thermal throttling (watch the trend across runs).
- [ ] Coefficient of variation recorded; if CV > 5% for a microbenchmark, fix the noise before comparing.

## 4. Statistics for claims

Report medians with 95% confidence intervals, never a single run, never only the mean.

- Sample size per variant to detect relative effect d with coefficient of variation CV (alpha 0.05,
  power 0.8): **n ~= 16 (CV / d)^2**. CV 3%, effect 2%: n ~= 16 x 2.25 = 36 runs per variant.
- Effect: ratio of medians after/before with a bootstrap CI (resample each side, 10,000 replicates).
- Decision rule: **improved** only if the CI of the ratio excludes 1 and the point effect exceeds the
  practical threshold (default 3%); **no change** if the CI lies within +/- threshold; otherwise
  inconclusive: collect more samples, do not round up to a win.
- Tail latency: estimating p99 needs >= ~1,000 samples (about 10 beyond the percentile); p99.9 needs
  >= ~10,000. Use histograms (HdrHistogram) and report p50/p90/p99/max together.

The bundled [compare_bench.py](scripts/compare_bench.py) implements this on hyperfine JSON or
one-number-per-line files:

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
CMP="$STACK/.claude/skills/performance-optimization/scripts/compare_bench.py"
python3 "$CMP" before.json after.json --threshold 0.03          # one hyperfine export per revision
python3 "$CMP" out.json out.json --before-command 'old args' --after-command 'new args'   # one export, two commands
```

Formulas, derivations, multiple-comparison handling and pitfalls: [Benchmark statistics](references/statistics.md).

## 5. Profile before you hypothesize

Pick the profiler by the question:

| Question | Tool type | Examples |
|---|---|---|
| Where does CPU time go? | Sampling CPU profiler, flame graph | `perf record -g`, samply, Instruments Time Profiler, pprof CPU, async-profiler `-e cpu`, py-spy |
| Why is this code slow on the hardware? | Hardware counters | `perf stat -d` (IPC, cache and branch misses), Instruments CPU Counters, VTune |
| Where is time spent *waiting*? | Wall-clock / off-CPU profiling, tracing | async-profiler `-e wall`, py-spy `--idle`, `go tool trace`, `perf sched`, offcputime (bcc) |
| Who allocates, and how much? | Allocation profiler | pprof `-memprofile`/`alloc_space`, async-profiler `-e alloc`, JFR, memray, heaptrack, dhat, Instruments Allocations |
| Why does memory grow? | Heap snapshots over time, leak checkers | pprof `inuse_space` diffs, heap dumps (Eclipse MAT), memray, `leaks` (macOS), valgrind massif |
| Lock contention? | Mutex/block profiling | Go `SetMutexProfileFraction`, async-profiler `-e lock`, JFR `jdk.JavaMonitorEnter`, `perf lock` |
| Which query is slow? | DB-side plans and stats | `EXPLAIN (ANALYZE, BUFFERS)`, `pg_stat_statements`, MySQL `EXPLAIN ANALYZE` |

Reading a flame graph: width is time; look for wide frames and wide plateaus (self time). Tall narrow
towers are rarely the problem. Compare before/after flame graphs (differential flame graphs) to confirm
the change removed what you targeted and did not move cost elsewhere.

Per-language command cheat-sheet (perf, xctrace, samply, pprof, async-profiler, JFR, py-spy, memray,
scalene, Node `--cpu-prof`, valgrind, BenchmarkTools, `@code_warntype`): [Profilers](references/profilers.md).

## 6. Optimization ladder

Work top-down. Each rung typically yields less than the one above and costs more maintainability.

| Rung | Typical gain | Moves |
|---|---|---|
| 1. Do less work | 10x-1000x | Better algorithm or data structure (hash set instead of list scans, sort + sweep instead of pairwise), remove redundant work, cache or memoize with bounded size, batch, push filters down to the DB, early exit, lazy evaluation |
| 2. Data layout and memory | 2x-10x | Contiguous arrays over pointer graphs, struct-of-arrays for hot fields, smaller types, avoid boxing, preallocate capacity, reuse buffers, arenas, avoid copies/clones, interning |
| 3. I/O and system | 2x-100x for I/O-bound work | Batch syscalls and queries (fix N+1), buffered I/O, connection pooling, pipelining, compression trade-offs, async overlap of independent waits, avoid sync I/O on hot paths |
| 4. Parallelism | <= cores, minus Amdahl and contention | Data parallelism (rayon, worker pools, `concurrent.futures`, parallel streams), SIMD, pipeline stages; shard to avoid shared state; watch false sharing |
| 5. Micro-optimizations | 1.05x-2x on the hot loop | Branch elimination, hoisting bounds checks, inlining hints, faster hashers, PGO/LTO, `-march` (only when deployment hardware is known) |

Catalog of patterns per rung with language specifics: [Optimization catalog](references/optimization-catalog.md).

Symptom to first move:

| Profile shows | First move |
|---|---|
| One function dominant, high self time, nested loops | Rung 1: complexity of the algorithm |
| `malloc`/`free`/GC dominant | Rung 2: allocation reduction (profile allocations, not CPU) |
| Low IPC (< 1) and high LLC misses (`perf stat -d`) | Rung 2: data layout, access order, prefetch-friendly traversal |
| Many syscalls or tiny reads/writes | Rung 3: buffering and batching |
| CPU low, latency high | Off-CPU: waits on locks, I/O, pool exhaustion, downstream calls |
| Time in hashing, string formatting, regex, serialization | Rung 1/2: avoid the work, precompile, cheaper format, reuse buffers |
| Scaling flat beyond N threads | Contention (locks, atomics, false sharing), memory bandwidth, or serial fraction (Amdahl) |

## 7. Change one thing at a time

For each candidate change:
1. State the hypothesis with a number: "Replacing the list scan with a set cuts `dedup()` from 93% of
   samples to < 5%, job time from 41 s to < 4 s."
2. Make the single change; run the correctness suite.
3. Re-run the benchmark with the same harness and sample size; compare with the script.
4. Re-profile to confirm the targeted cost moved. Keep or revert; log the result either way.

Keep an experiment log (`.stack/out/<agent>/<YYYYMMDD-HHMM>-perf-log.md`):

| # | Change | Hypothesis | Result (ratio, CI) | Kept |
|---|---|---|---|---|

## 8. Report template

```markdown
## Result
Status: done
`import_job` wall time 41.2 s -> 1.9 s (21.7x; ratio 0.046, 95% CI [0.045, 0.048]) on fixtures/200k.csv.
Target (< 5 s) met. Peak RSS 310 MB -> 335 MB (+8%).

## Evidence
| Variant | n | median | 95% CI | CV |
|---|---|---|---|---|
| before a1b2c3d | 20 | 41.2 s | [40.9, 41.6] | 0.9% |
| after  e4f5a6b | 20 | 1.90 s | [1.88, 1.92] | 1.2% |
Commands: hyperfine --warmup 2 --runs 20 -N "python -m importer fixtures/200k.csv" (each revision)
Profile before: py-spy 93% of samples in dedup() -> list.__contains__ (flame graph path)
Profile after: dedup() 2%; CSV parsing now 61% (next candidate)
Correctness: 412 tests passed; output files identical (sha256 match on 3 fixtures)
Environment: M3 Pro, macOS 15, CPython 3.12.6, AC power

## Files
.stack/out/<agent>/<YYYYMMDD-HHMM>-perf-log.md - experiment log - new

## Open doubts
Production input distribution may contain more duplicates than the fixture; not measured.

## Confidence
high (0.85) - 20 runs per variant, CI excludes 1; drops if production inputs differ from the fixture
```

## 9. Worked example

`import_job` takes 41 s on a 200k-row CSV; target < 5 s.
1. Baseline: hyperfine 20 runs, median 41.2 s, CV 0.9%.
2. Profile: `py-spy record -o before.svg -- python -m importer fixtures/200k.csv` shows 93% in
   `dedup()`, which does `if key not in seen_list`: O(n^2) over 200k rows.
3. Rung 1 change: `seen = set()`. Tests green. Median 1.90 s, ratio CI [0.045, 0.048]: IMPROVED.
4. New profile: CSV parsing 61%, DB insert 30%. Amdahl check before parallelizing parsing over 4
   workers: best case 1 / (0.39 + 0.61 / 4) = 1.84x, minus process start-up and IPC. The target is
   already met, so stop: further work adds complexity without a requirement.

## 10. Pitfalls

- Microbenchmarks whose inputs fit in L1 when production data does not; benchmark at production sizes.
- Dead-code elimination making the benchmark measure nothing (suspiciously fast results, ns for real work).
- Comparing runs across different machines, power states, or compiler versions.
- Improving p50 while regressing p99 (e.g. bigger batches, GC pauses); always report tails for services.
- Caches that win the benchmark (repeated identical input) and lose in production (low hit rate).
- Parallelism that speeds up the benchmark but saturates a shared resource in production (DB, memory
  bandwidth, rate limits).
- Trading memory for speed beyond the memory budget; report RSS alongside time.
- Leaving profiling builds or debug flags in the shipped configuration.

## Delegation

| Need | Agent |
|---|---|
| Correctness suite and repeated benchmark runs | `tester` |
| Algorithmic lower bounds, data-structure choice | `computer-science-expert` |
| Language/runtime specifics (GC tuning, unsafe SIMD, allocator behaviour) | `rust-expert`, `cpp-expert`, `go-expert`, `java-expert`, `kotlin-expert`, `julia-expert`, `haskell-expert` |
| Unexplained regression between two revisions | `debugger` (bisect with the benchmark as the predicate) |
| GPU / rendering performance | `computer-graphics-expert` |

Several independent candidate optimizations can be benchmarked in parallel only on separate machines
or sequentially on one machine; parallel benchmark runs on the same host contaminate each other.
