# Profilers and measurement commands

Build with symbols and frame pointers for usable stacks: C/C++ `-g -fno-omit-frame-pointer`; Rust
`[profile.release] debug = true` (or `CARGO_PROFILE_RELEASE_DEBUG=true`); Go keeps frame pointers by
default. Profile optimized builds.

## Linux system-wide: perf

```bash
perf stat -d ./prog args                         # cycles, instructions (IPC), cache and branch misses
perf stat -e cycles,instructions,cache-references,cache-misses,branch-misses,L1-dcache-load-misses,LLC-load-misses ./prog
perf record -F 999 -g -- ./prog args             # sample stacks at 999 Hz (frame pointers)
perf record -F 999 --call-graph dwarf -- ./prog  # when frame pointers are missing (bigger files)
perf report --no-children --sort symbol          # self time ranking
perf script | inferno-collapse-perf | inferno-flamegraph > flame.svg
perf c2c record -- ./prog && perf c2c report     # false sharing / cache-line contention
perf sched record -- ./prog && perf sched latency   # scheduler delays
perf trace -s ./prog                             # syscall summary (strace-like, lower overhead)
```
Interpretation: IPC < 1 on a modern core with high LLC misses suggests memory-bound; branch-miss rate
> 5% of branches in a hot loop suggests unpredictable branches.

Other Linux tools: `valgrind --tool=callgrind ./prog` + `callgrind_annotate` or KCachegrind
(deterministic instruction counts, ~50x slowdown); `valgrind --tool=cachegrind`; `heaptrack ./prog`
+ `heaptrack_print`; `valgrind --tool=massif` + `ms_print` (heap over time); bcc/bpftrace tools
(`offcputime`, `profile`, `biolatency`).

## macOS

```bash
xcrun xctrace record --template 'Time Profiler' --launch -- ./prog args     # opens as .trace in Instruments
xcrun xctrace record --template 'Allocations' --launch -- ./prog args
xcrun xctrace record --template 'Time Profiler' --attach <pid> --time-limit 30s
samply record --save-only -o .stack/out/<agent>/<YYYYMMDD-HHMM>-profile.json.gz -- ./prog args   # no server/UI; Rust, C/C++, Go
sample <pid> 10 -file sample.txt                  # quick 10 s call-tree sample of a running process
leaks --atExit -- ./prog                          # leak check at exit
/usr/bin/time -l ./prog                           # max RSS (bytes), page faults, context switches
```
Linux equivalent of the last line: `/usr/bin/time -v ./prog` ("Maximum resident set size" in KiB).

## Rust

```bash
cargo bench --bench parse -- --save-baseline before      # criterion
cargo bench --bench parse -- --baseline before           # compare against saved baseline
cargo flamegraph --bin app -- args                       # flamegraph crate (perf on Linux, dtrace on macOS)
samply record --save-only -o .stack/out/<agent>/<YYYYMMDD-HHMM>-profile.json.gz -- target/release/app args
```
- `std::hint::black_box` around inputs and outputs in hand-rolled benchmarks.
- Allocation profiling: `dhat` crate (`#[global_allocator] static ALLOC: dhat::Alloc`), heaptrack, or
  bytehound on Linux.
- Instruction-count benchmarks for noisy CI: gungraun (formerly iai-callgrind; valgrind-based).
- Check codegen: `cargo asm` (cargo-show-asm) or Compiler Explorer for hot functions.

## Go

```bash
go test -run '^$' -bench 'BenchmarkParse$' -benchmem -count 10 ./parser > new.txt
benchstat old.txt new.txt                                # golang.org/x/perf/cmd/benchstat
go test -run '^$' -bench 'BenchmarkParse$' -cpuprofile cpu.out -memprofile mem.out ./parser
go tool pprof -http=:0 cpu.out                           # web UI with flame graph
go tool pprof -sample_index=alloc_space mem.out          # allocation volume
go tool pprof -top -diff_base old.pprof new.pprof        # differential profile
curl -o cpu.pprof 'http://localhost:6060/debug/pprof/profile?seconds=30'    # net/http/pprof in services
curl -o heap.pprof 'http://localhost:6060/debug/pprof/heap'
go test -trace trace.out -run TestX && go tool trace trace.out               # scheduler, GC, blocking
GODEBUG=gctrace=1 ./app                                  # GC cycles and pause times
```
- Enable contention profiles in code: `runtime.SetMutexProfileFraction(5)`, `runtime.SetBlockProfileRate(1)`.
- Escape analysis: `go build -gcflags='-m' ./pkg 2>&1 | grep escapes`.
- PGO: put a representative CPU profile at `default.pgo` in the main package directory; `go build`
  uses it automatically (Go 1.21+), typically a few percent.

## JVM (Java, Kotlin)

```bash
asprof -d 30 -e cpu -f cpu.html <pid>              # async-profiler 3.x flame graph (older: profiler.sh)
asprof -d 30 -e alloc -f alloc.html <pid>
asprof -d 30 -e wall -t -f wall.html <pid>         # wall clock, per thread: finds waiting
asprof -d 30 -e lock -f lock.html <pid>
jcmd <pid> JFR.start duration=60s filename=rec.jfr settings=profile
jfr print --events jdk.ExecutionSample rec.jfr | head
jfr view hot-methods rec.jfr                       # JDK 21+
java -jar target/benchmarks.jar -f 3 -wi 5 -i 10 -prof gc    # JMH with GC/allocation profiler
```
- JIT warmup dominates short runs; never time a JVM method with a single `System.nanoTime` pair.
- GC logs: `-Xlog:gc*:file=gc.log:time,uptime,level,tags`.

## Python

```bash
py-spy record -o flame.svg -- python -m app args   # sampling, low overhead, no code changes
py-spy record -o flame.svg --pid <pid> --duration 30
py-spy record --native --idle -o flame.svg -- python app.py   # include C extensions and idle threads
py-spy dump --pid <pid>                            # current stacks of all threads
python -m cProfile -o out.prof app.py && python -m pstats out.prof    # deterministic, higher overhead
scalene app.py                                     # CPU (Python vs native), memory, copy volume per line
memray run -o mem.bin app.py && memray flamegraph mem.bin   # allocations
python -m pyperf timeit -s 'from m import f, x' 'f(x)' -o new.json
python -m pyperf compare_to old.json new.json
python -X importtime -c 'import app' 2> import.log # startup cost by import
```

## JavaScript / Node

```bash
node --cpu-prof app.js                       # writes .cpuprofile; open in Chrome DevTools Performance panel
node --heap-prof app.js                      # sampling heap profile
node --prof app.js && node --prof-process isolate-*.log > prof.txt
npx 0x app.js                                # flame graph
npx clinic doctor -- node app.js             # event-loop delay, GC, I/O triage
```
Browser: Chrome DevTools Performance panel; Lighthouse for page-level metrics; Playwright traces via
`tester` for reproducible runs.

## C / C++

```bash
./bench --benchmark_repetitions=20 --benchmark_report_aggregates_only=true --benchmark_format=json > new.json
# Google Benchmark ships tools/compare.py: compare.py benchmarks old.json new.json
perf record -g ./prog ; heaptrack ./prog ; valgrind --tool=callgrind ./prog
```
Also: Tracy (frame-based instrumentation), Intel VTune (microarchitecture analysis), uftrace
(function-level tracing with `-pg`/`-finstrument-functions`).

## Julia

```julia
using BenchmarkTools
@benchmark f($x)            # interpolate globals with $ to avoid measuring global lookups
@btime f($x)                # minimum time and allocations
@code_warntype f(x)         # red/Any types = type instability
@allocated f(x)
using Profile; @profile for _ in 1:1000; f(x); end; Profile.print(format=:flat, sortedby=:count)
```
`julia --track-allocation=user` writes per-line allocation counts (`.mem` files); ProfileView /
`@profview` (VS Code) for flame graphs.

## Haskell

```bash
cabal run app --enable-profiling -- +RTS -p -RTS      # .prof cost centres
cabal run app --enable-profiling -- +RTS -hT -RTS     # heap profile by closure type; hp2ps or eventlog2html
cabal run app -- +RTS -s -RTS                         # GC and allocation summary
```
Executables need `ghc-options: -rtsopts` for most `+RTS` flags. criterion or tasty-bench for benchmarks; space leaks show as growing heap profiles (see `haskell-expert`).

## Databases

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT ...;            -- PostgreSQL: actual rows, time, buffer hits
SELECT query, calls, mean_exec_time, total_exec_time FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20;
EXPLAIN ANALYZE SELECT ...;                                    -- MySQL 8.0.18+
```
Look for sequential scans on large tables, estimated vs actual row mismatches (stale statistics:
`ANALYZE table`), nested loops over large inputs, sorts spilling to disk.

## Load testing services

```bash
k6 run script.js        # use the constant-arrival-rate executor for open-model load
wrk2 -t4 -c64 -d60s -R2000 --latency http://localhost:8080/quote   # fixed request rate, corrected latency
vegeta attack -rate=500/s -duration=60s -targets=targets.txt | vegeta report -type=hist[0,50ms,100ms,200ms,500ms]
```
Closed-loop generators (fixed concurrency, next request after the previous returns) hide queueing
delay (coordinated omission) and understate tail latency.
