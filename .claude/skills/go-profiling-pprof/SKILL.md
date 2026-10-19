---
name: go-profiling-pprof
description: "Go performance and memory diagnosis: benchmarks with b.Loop and benchstat; CPU, heap, mutex, block and goroutine profiles with pprof; execution traces and the flight recorder; escape analysis and inlining; GOGC, GOMEMLIMIT and GOMAXPROCS tuning; Green Tea GC; and PGO. Load when a Go service is slow, allocation-heavy, leaking memory or showing latency spikes."
when_to_use: "Slow Go functions or endpoints; runtime.mallocgc or GC CPU high in a profile; memory growth or OOM kills in containers; p99 latency spikes; lock contention; writing or comparing benchmarks; reading go tool pprof or go tool trace output; -gcflags=-m escape output; tuning GOGC, GOMEMLIMIT or GOMAXPROCS; adding default.pgo."
---

# Go profiling and performance

Baseline Go 1.26/1.27. Version map: `-pgo=auto` default 1.21; `testing.B.Loop` and Swiss-table maps
1.24; `runtime/trace.FlightRecorder`, cgroup-aware `GOMAXPROCS`, `GOEXPERIMENT=jsonv2` and the
Green Tea GC experiment 1.25; Green Tea on by default, `pprof -http` opening the flame graph, `B.Loop`
no longer blocking inlining 1.26; size-specialised small allocations, `encoding/json` backed by
the v2 implementation, `goroutineleak` profile GA 1.27.

Deep material: [pprof and trace CLI](references/pprof-cli.md) (endpoints, flags, interactive
commands, trace views) | [GC and memory tuning](references/gc-tuning.md) (gctrace decoding, sizing
arithmetic, runtime/metrics list)

## 1. Procedure

1. State the target: metric (p99, allocs/op, RSS, CPU per request), workload and budget.
2. Reproduce with a benchmark (function level) or a load test (service level); record a baseline.
3. Profile under that workload: CPU first; heap `alloc_space` when `mallocgc` or GC is high; mutex
   and block when CPU is low but latency is high; an execution trace for scheduling and pauses.
4. Fix only the top item in your own code (largest `cum` you control).
5. Verify: benchstat over `-count=10` (10 minimum, 20 better) and keep only deltas with p < 0.05;
   `pprof -diff_base` shows where the cost moved.
6. Keep the benchmark in the repo; quote before/after numbers in the PR.

```bash
go test -run='^$' -bench='^BenchmarkList$' -benchmem -count=10 ./api | tee old.txt   # base commit
go test -run='^$' -bench='^BenchmarkList$' -benchmem -count=10 ./api | tee new.txt   # change
go install golang.org/x/perf/cmd/benchstat@latest    # or: go get -tool golang.org/x/perf/cmd/benchstat
benchstat old.txt new.txt                            # Mann-Whitney U, alpha 0.05; "~" = no significant change
```

```go
func BenchmarkList(b *testing.B) {
    rows := sampleRows(100)          // with b.Loop, setup runs once per -count
    b.ReportAllocs()
    for b.Loop() {                   // keeps call results alive: no dead-code elimination
        if err := writeList(io.Discard, rows); err != nil { b.Fatal(err) }
    }
}
```

Noise rules: same machine, idle, power settings fixed; never time runs with `-race`, `-cover` or
profiling flags; sub-benchmarks per input size (`b.Run(strconv.Itoa(n), ...)`); `-cpu=1,4,8` for
scaling. Old-style `for i := 0; i < b.N; i++` loops need `b.ResetTimer()` after setup and a sink
variable against dead-code elimination.

## 2. Collecting

| Profile | From tests | From a service | Use |
|---|---|---|---|
| CPU | `-cpuprofile cpu.out` | `/debug/pprof/profile?seconds=30` | where CPU time goes (100 Hz sampling) |
| heap | `-memprofile mem.out` (`-memprofilerate=1` records every allocation, profiling runs only) | `/debug/pprof/heap` (`?gc=1` collects first) | live and allocated memory; default sampling about 1 per 512 KiB |
| allocs | same file, `alloc_*` indexes | `/debug/pprof/allocs` | allocation churn |
| mutex | `-mutexprofile mutex.out` | `/debug/pprof/mutex` after `runtime.SetMutexProfileFraction(n)` | contention delay at the unlocking site |
| block | `-blockprofile block.out` | `/debug/pprof/block` after `runtime.SetBlockProfileRate(ns)` | time blocked on channels, selects, locks |
| goroutine | n/a | `/debug/pprof/goroutine?debug=2` | stacks of every goroutine |
| trace | `-trace trace.out` | `/debug/pprof/trace?seconds=5` | scheduling, GC, syscalls, blocking over time |

`go test -cpuprofile` leaves the test binary (`api.test`) in the current directory; modern profiles
are symbolised, so pprof does not need it. Service setup, on an admin-only listener:

```go
import "net/http/pprof"

admin := http.NewServeMux()
admin.HandleFunc("/debug/pprof/", pprof.Index)          // also serves heap, goroutine, mutex, block...
admin.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
admin.HandleFunc("/debug/pprof/profile", pprof.Profile)
admin.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
admin.HandleFunc("/debug/pprof/trace", pprof.Trace)
runtime.SetMutexProfileFraction(5)                       // sample 1 in 5 contention events
runtime.SetBlockProfileRate(10_000)                      // about one sample per 10 µs spent blocked
go func() { _ = http.ListenAndServe("127.0.0.1:6060", admin) }()
```

Importing `net/http/pprof` also registers on `http.DefaultServeMux`: a public server built with a
nil handler then exposes profiles to the internet. A `?seconds=` longer than the server's
`WriteTimeout` is refused.

## 3. Reading

Agents use text modes; `go tool pprof -http=:0 cpu.out` opens a browser (humans; flame graph by
default since 1.26).

```bash
go tool pprof -top -cum cpu.out | head -30              # inclusive cost: which call trees matter
go tool pprof -top cpu.out | head -20                   # flat: functions that burn CPU themselves
go tool pprof -list 'api\.writeList' cpu.out            # per-line cost of one function (regex)
go tool pprof -peek 'fmt\.Sprintf$' cpu.out             # callers and callees of a hot runtime/std symbol
go tool pprof -sample_index=alloc_space -top mem.out | head -20   # bytes allocated (churn)
go tool pprof -sample_index=inuse_space -top heap.pprof | head    # bytes retained now (leaks)
go tool pprof -tagfocus=endpoint=list -top cpu.pprof    # only samples labelled endpoint=list
go tool pprof -top -diff_base=old.pprof new.pprof | head -30      # regression or improvement
```

| Column / index | Meaning |
|---|---|
| `flat`, `flat%` | samples in the function itself |
| `cum`, `cum%` | the function plus everything it calls |
| `inuse_space` / `inuse_objects` | live at the last GC: leaks, cache sizing |
| `alloc_space` / `alloc_objects` | allocated since start: GC pressure, `mallocgc` CPU |
| `contentions` / `delay` | mutex and block profiles: event counts / time waited |
| flame graph (web UI) | frame width = cumulative share; a wide frame whose children are narrow is self time |

Runtime symbols (`mallocgc`, `growslice`, `mapassign`, `memmove`, `gcBgMarkWorker`) are symptoms:
`-peek` them to find your calling function. Per-endpoint attribution with labels:

```go
pprof.Do(r.Context(), pprof.Labels("endpoint", route), func(ctx context.Context) {
    next.ServeHTTP(w, r.WithContext(ctx))                // goroutines started inside inherit labels
})
```

Labels reach CPU and goroutine profiles only, not heap. Go 1.27 also prints them in traceback
headers for `go 1.27` modules (`GODEBUG=tracebacklabels=0` disables): keep secrets out of labels.

## 4. Execution traces

Use when CPU looks fine but latency does not: scheduler delay, GC pauses and assists, blocking,
syscalls, idle processors. Tracing overhead is a few percent on current releases.

```bash
go tool trace -pprof=sched trace.out > sched.pprof && go tool pprof -top sched.pprof | head -20
go tool trace -pprof=sync trace.out > sync.pprof        # also: net, syscall
go tool trace trace.out                                  # web UI, humans; -http=:port binds localhost (1.27)
```

| Trace view | Answers |
|---|---|
| View trace by proc / thread | idle Ps, GC bands, one goroutine hogging a P |
| Goroutine analysis | per goroutine kind: execution, scheduler wait, block and syscall time |
| Network / Synchronization / Syscall blocking profiles | where goroutines wait |
| Scheduler latency profile | runnable-but-not-running time |
| User-defined tasks and regions | latency of operations annotated with `trace.NewTask` / `trace.WithRegion` |
| Minimum mutator utilization | CPU share left to your code by GC over time windows |

The flight recorder (1.25) keeps the last seconds in memory and snapshots on demand:

```go
fr := trace.NewFlightRecorder(trace.FlightRecorderConfig{MinAge: 10 * time.Second, MaxBytes: 64 << 20})
if err := fr.Start(); err != nil { return err }          // one active flight recorder per process
defer fr.Stop()
var once sync.Once
// in the request path, after measuring:
if time.Since(start) > 500*time.Millisecond && fr.Enabled() {
    once.Do(func() {                                     // WriteTo allows one caller at a time
        f, err := os.Create(filepath.Join(dumpDir, "slow.trace"))
        if err != nil { return }
        defer f.Close()
        _, _ = fr.WriteTo(f)                             // then: go tool trace slow.trace
    })
}
```

`MaxBytes` takes precedence over `MinAge`; both are hints. It may run alongside `trace.Start`.

## 5. Escape analysis and inlining

```bash
go build -gcflags='-m' ./api 2>&1 | grep -E 'escapes to heap|moved to heap'
go build -gcflags='-m=2' ./api 2>&1 | grep 'cannot inline'          # with the reason and cost
go build -gcflags='all=-m' ./... 2>&1 | grep api/                   # flags apply to named packages unless patterned
go build -gcflags='-d=ssa/check_bce/debug=1' ./api                  # bounds checks left: "Found IsInBounds"
```

| Message | Meaning |
|---|---|
| `moved to heap: x` | local `x` is heap-allocated |
| `... escapes to heap` | a value outlives the frame, often via interface conversion |
| `leaking param: p` | `p` flows to the heap or a result; the caller's argument may escape |
| `can inline f with cost 37` / `inlining call to f` | inlinable; inlined at this site |
| `cannot inline f: function too complex: cost 112 exceeds budget 80` | over the inlining budget (80 nodes) |

| Escape cause | Fix on hot paths |
|---|---|
| returning `&local` | return a value, or fill a caller-provided `*T` |
| interface conversion (`any` params, `fmt` args, boxing ints above 255) | concrete types, `strconv.Append*` |
| closures capturing variables used by goroutines or stored callbacks | pass values as parameters |
| `make([]T, n)` with large or non-constant `n` | reuse buffers, `sync.Pool`, fixed-size arrays |
| pointers stored in heap objects or sent on channels | values or indices |

PGO raises the inlining budget for hot call sites. A bounds-check hint `_ = b[7]` before reading
`b[0]..b[7]` removes the per-index checks; ranging instead of indexing avoids them too.

## 6. Symptom to fix

| Symptom | Fix |
|---|---|
| `runtime.mallocgc` high, GC above ~10% of CPU | preallocate (`make([]T, 0, n)`), reuse buffers (`sync.Pool` for short-lived large ones), avoid `[]byte`/`string` round trips, pointer-free structs |
| `runtime.growslice`, `runtime.mapassign` growth | capacity hints: `make(map[K]V, n)`, `slices.Grow(s, n)` |
| `fmt.Sprintf` in hot paths | `strconv.AppendInt`, `strings.Builder` with `Grow`, typed writes |
| `encoding/json` hot | typed structs instead of `map[string]any`, stream with `json.NewEncoder(w)`; on 1.25/1.26 test `GOEXPERIMENT=jsonv2`; on 1.27 the v2-backed `encoding/json` unmarshals much faster (opt out `GOEXPERIMENT=nojsonv2`); code-generated codecs last, after tests |
| `sync.(*Mutex).Lock` with mutex-profile delay | shard state, shorten sections, atomics for counters, RWMutex only for long read-mostly sections |
| many small `write` syscalls | `bufio.Writer` / `bufio.Reader`, batch requests |
| `gcAssistAlloc` in request paths | allocation rate exceeds GC pace: cut allocations, raise `GOGC`, give `GOMEMLIMIT` headroom |
| high `/sched/latencies:seconds`, CPU throttling | `GOMAXPROCS` equal to the CPU limit (automatic in 1.25+), fewer CPU-bound goroutines |
| `regexp.Compile` / template parsing per request | compile once at package level |
| CPU fine, latency poor | execution trace (section 4) |

## 7. GC and memory

Target heap = live heap + (live heap + GC roots) x `GOGC`/100. Live 200 MiB, roots 10 MiB:
`GOGC=100` gives a 410 MiB goal; `GOGC=200` gives 620 MiB and about half as many cycles.

| Knob | Effect | Guidance |
|---|---|---|
| `GOGC` (default 100) | heap growth between cycles | raise to 200-400 to trade memory for GC CPU |
| `GOMEMLIMIT` | soft limit on Go-runtime memory (heap, stacks, runtime metadata; not cgo) | about 90% of the container limit: 1 GiB limit gives `GOMEMLIMIT=920MiB`; GC CPU is capped near 50% to avoid death spirals |
| `GOGC=off` + `GOMEMLIMIT` | GC only near the limit | only with a hard limit, a stable live heap and headroom |
| `GOMAXPROCS` | Ps running Go code | 1.25+: defaults to the cgroup CPU limit (rounded up), updated periodically; ignores CPU requests; disabled when set explicitly (`GODEBUG=containermaxprocs=0`, `updatemaxprocs=0`); older: `go.uber.org/automaxprocs` |
| Green Tea GC | 1.26 default: 10-40% less GC overhead in GC-heavy programs, about 10% more on newer amd64 | opt out at build time with `GOEXPERIMENT=nogreenteagc` (1.26; announced for removal in 1.27: check your toolchain's release notes) |
| size-specialised malloc (1.27) | small (<80 B) allocations up to 30% cheaper | opt out `GOEXPERIMENT=nosizespecializedmalloc` |
| `GODEBUG=gctrace=1` | one stderr line per GC | `gc 12 @3.4s 4%: ... 38->39->20 MB, 40 MB goal, ...`: decoding in the GC reference |

Export `runtime/metrics` rather than polling `runtime.ReadMemStats` (stop-the-world): watch
`/gc/heap/live:bytes`, `/gc/heap/goal:bytes`, `/cpu/classes/gc/total:cpu-seconds`,
`/sched/latencies:seconds`, `/sched/goroutines:goroutines`, `/gc/limiter/last-enabled:gc-cycle`.
Prometheus: `collectors.NewGoCollector(collectors.WithGoCollectorRuntimeMetrics(collectors.MetricsAll))`.

## 8. Leak triage

1. Classify: RSS vs `/memory/classes/heap/objects:bytes` vs goroutine count over hours. Heap flat
   but RSS rising points at cgo, mmap, stacks, or memory not yet returned to the OS.
2. Heap: two `inuse_space` profiles minutes apart under steady load, then diff:
   `curl -so h1.pprof 'localhost:6060/debug/pprof/heap?gc=1'`, wait 10 min, same for `h2.pprof`,
   `go tool pprof -sample_index=inuse_space -top -diff_base=h1.pprof h2.pprof | head`. Growth at one
   allocation site is the leak; the profile shows who allocated, so reason about who retains it.
3. Goroutines: a growing count with identical stacks (`goroutine?debug=1`); 1.27 `goroutineleak`.
4. Usual retainers: unbounded caches and maps (maps keep their buckets after `delete`: rebuild),
   small sub-slices pinning large arrays (`slices.Clone` the part you keep), goroutines looping on
   tickers without a ctx exit, `sync.Pool` buffers grown huge, high-cardinality metric labels.

## 9. PGO

```bash
curl -so cpu1.pprof 'http://127.0.0.1:6060/debug/pprof/profile?seconds=30'   # several instances and times
go tool pprof -proto cpu1.pprof cpu2.pprof cpu3.pprof > cmd/api/default.pgo  # merge equal-length profiles
go build ./cmd/api                   # -pgo=auto uses default.pgo in the main package directory
go build -pgo=off -o api.nopgo ./cmd/api && go version -m api | grep pgo     # A/B and confirm
```

Typical gain 2-14% CPU (Go docs, as of 1.22): hot call sites get a larger inlining budget and hot
interface calls are devirtualised. Commit `default.pgo` from representative production load, never
from a microbenchmark; refresh it regularly (each release or monthly), since edits inside hot
functions degrade matching gracefully. The first build with a new profile rebuilds every package.

## 10. Worked example: halve allocations in a JSON list handler

Before (100 rows per request):

```go
type Item struct { ID string `json:"id"`; Name string `json:"name"`; Tags []string `json:"tags"` }

func writeList(w io.Writer, rows []Row) error {
    var items []Item                                      // grows by appending: ~8 allocations for 100
    for _, r := range rows {
        items = append(items, Item{
            ID:   fmt.Sprintf("%d", r.ID),                // boxes the int64 and allocates the string
            Name: r.Name,
            Tags: strings.Split(r.TagCSV, ","),           // one slice per row
        })
    }
    b, err := json.Marshal(map[string]any{"items": items, "total": len(items)}) // map + copy out
    if err != nil { return err }
    _, err = w.Write(b)
    return err
}
```

Profile (separate, untimed run with exact allocation sampling):

```bash
go test -run='^$' -bench='^BenchmarkList$' -benchtime=2000x -memprofilerate=1 -memprofile mem.old.pprof ./api
go tool pprof -sample_index=alloc_objects -top mem.old.pprof | head -15
```

The top rows are `fmt.Sprintf` and its int boxing (2 per row), `strings.genSplit` (1 per row),
`runtime.growslice` and `encoding/json.Marshal`. After (same wire format):

```go
type Item struct { ID int64 `json:"id,string"`; Name string `json:"name"`; Tags []string `json:"tags"` }
type listResponse struct { Items []Item `json:"items"`; Total int `json:"total"` }

var bufPool = sync.Pool{New: func() any { return new(bytes.Buffer) }}

func writeList(w io.Writer, rows []Row) error {
    items := make([]Item, 0, len(rows))                  // one allocation
    for _, r := range rows {
        items = append(items, Item{ID: r.ID, Name: r.Name, Tags: strings.Split(r.TagCSV, ",")})
    }
    buf := bufPool.Get().(*bytes.Buffer)
    buf.Reset()
    defer func() { if buf.Cap() <= 64<<10 { bufPool.Put(buf) } }() // do not pin huge buffers
    if err := json.NewEncoder(buf).Encode(listResponse{Items: items, Total: len(items)}); err != nil {
        return fmt.Errorf("encode list: %w", err)
    }
    _, err := w.Write(buf.Bytes())
    return err
}
```

Evidence (illustrative figures showing the expected shape; rerun the commands for real numbers):

```text
$ benchstat old.txt new.txt
       │   old.txt    │               new.txt               │
       │    sec/op    │   sec/op     vs base                │
List-8    48.21µ ± 1%   30.94µ ± 2%  -35.82% (p=0.000 n=10)
       │     B/op     │     B/op      vs base               │
List-8   27.63Ki ± 0%   11.91Ki ± 0%  -56.89% (p=0.000 n=10)
       │  allocs/op   │  allocs/op   vs base                │
List-8    312.0 ± 0%    106.0 ± 0%   -66.03% (p=0.000 n=10)
```

```bash
go test -run='^$' -bench='^BenchmarkList$' -benchtime=2000x -memprofilerate=1 -memprofile mem.new.pprof ./api
go tool pprof -sample_index=alloc_objects -top -diff_base=mem.old.pprof mem.new.pprof | head -15
```

The diff must show negative counts at the removed sites (Sprintf and boxing, about 2 x 100 x 2000;
growslice; Marshal's copy) and nothing new near the top. The remaining 106 allocations per request
are the 100 `strings.Split` results plus the slice and encoder internals: the next step, if the
budget demands it, is splitting tags once at load time. Wire check: a golden test comparing old and
new bodies (the `Encoder` appends `\n`; `,string` keeps `"id":"42"`).

## 11. Pitfalls

- Optimising without a profile, or a profile of the wrong workload (idle instance, warm-up only).
- Comparing single runs: without `-count=10` and benchstat, a 5% change is noise.
- Reading `inuse_space` to find churn, or `alloc_space` to find leaks.
- Heap profiles reflect the last completed GC: use `?gc=1` for current data.
- `-memprofilerate=1` or `-race` in timed runs distorts every number.
- `sync.Pool` for small objects or long-lived values: overhead without benefit; it is cleared by GC.
- `GOMEMLIMIT` at or above the container limit: OOM kill before the GC reacts; too close to the live
  heap: GC thrashes at the CPU cap.
- pprof endpoints on the public port or on `DefaultServeMux`: leaks command lines and internals.
- Micro-optimising code outside the top of `-top -cum`: invisible end to end.
- A stale `default.pgo` after a large refactor: rebuild it from fresh production profiles.

Delegation: profiles from a production incident go to the `debugger` agent with the file paths;
systematic work against a latency or allocation budget goes to `code-optimizer`.

Related: `go-concurrency-context`, `go-error-handling`, `go-testing-fuzzing`,
`go-http-services`, `go-modules-tooling`, hub `go-craft`.
