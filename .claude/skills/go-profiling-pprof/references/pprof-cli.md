# pprof and trace command reference

## net/http/pprof endpoints

All paths start with `/debug/pprof/` and, since Go 1.22, must be requested with GET.

| Path | Content | Parameters |
|---|---|---|
| `/debug/pprof/` | HTML index of available profiles | |
| `profile` | CPU profile | `seconds=N` (default 30); must stay below the server `WriteTimeout` |
| `trace` | execution trace | `seconds=N` (default 1) |
| `heap` | sampled live and allocated memory | `gc=1` runs a GC first; `seconds=N` returns a delta profile |
| `allocs` | same data as heap, `alloc_space` default index | `seconds=N` delta |
| `goroutine` | all goroutine stacks | `debug=1` grouped text, `debug=2` full panic-style stacks; `seconds=N` delta |
| `goroutineleak` (1.27; 1.26 with `GOEXPERIMENT=goroutineleakprofile`) | goroutines blocked on unreachable primitives | |
| `mutex` | contended mutex holders | needs `runtime.SetMutexProfileFraction(n > 0)`; `seconds=N` delta |
| `block` | blocking events | needs `runtime.SetBlockProfileRate(ns > 0)`; `seconds=N` delta |
| `threadcreate` | stacks that created OS threads | |
| `cmdline`, `symbol` | process command line, symbol lookup | |

`debug=N` on any profile: 0 binary (default), > 0 text. Delta profiles (`seconds=N` on heap, allocs,
block, mutex) answer "what happened in the last N seconds" without manual diffing.

Profiles can be read straight from a URL: `go tool pprof -top http://127.0.0.1:6060/debug/pprof/heap`.

## go test profiling flags

| Flag | Effect |
|---|---|
| `-cpuprofile f` | CPU profile of the whole test binary run |
| `-memprofile f`, `-memprofilerate n` | heap profile; `n=1` records every allocation (slow) |
| `-mutexprofile f`, `-mutexprofilefraction n` | mutex contention, sampling 1 in n events |
| `-blockprofile f`, `-blockprofilerate n` | blocking events, rate in nanoseconds blocked per sample |
| `-trace f` | execution trace |
| `-outputdir d` | where profile files are written |
| `-benchtime 2000x` / `-benchtime 3s` | fixed iteration count / minimum duration |
| `-count n`, `-cpu 1,4,8`, `-benchmem` | repetitions for benchstat, GOMAXPROCS sweep, allocation columns |

Profile flags apply to one package per invocation. Use a fixed `-benchtime=Nx` when comparing
allocation profiles so both runs do identical work.

## go tool pprof options

| Option | Use |
|---|---|
| `-top`, `-cum` | flat or cumulative ranking |
| `-list regex` | annotated source of matching functions |
| `-peek regex` | callers and callees of matching functions |
| `-traces` | every sample's stack (goroutine and small profiles) |
| `-tree` | call tree in text |
| `-nodecount=N` | limit output rows |
| `-focus=regex`, `-ignore=regex` | keep / drop samples whose stack matches |
| `-hide=regex`, `-show=regex`, `-show_from=regex` | drop or keep frames, or start stacks at a frame |
| `-tagfocus=key=value`, `-tagignore`, `-tags` | filter by pprof labels; list label values |
| `-sample_index=name` | `inuse_space`, `inuse_objects`, `alloc_space`, `alloc_objects`, `contentions`, `delay`, ... |
| `-granularity=lines` (`functions`, `filefunctions`, `files`, `addresses`) | aggregation level |
| `-diff_base=old` | show new minus old with percentages relative to old |
| `-base=old` | subtract old (for cumulative profiles taken from the same process) |
| `-proto a b > merged` | merge profiles (PGO input) |
| `-svg`, `-png`, `-output f` | render graphs (needs graphviz) for reports |
| `-http=:0` | interactive web UI on a free localhost port (humans) |

Interactive mode (`go tool pprof cpu.out`, then commands): `top 20`, `top -cum`, `list Func`,
`peek Func`, `traces`, `sample_index=alloc_space`, `focus=Func`, `disasm Func`, `quit`.

## Reading a CPU profile in five minutes

1. `-top -cum | head -30`: find the first frame that is your code with a large `cum`.
2. `-list` that function: the heavy lines name the expensive calls.
3. If a runtime frame dominates (`mallocgc`, `growslice`, `mapassign`, `memmove`, `selectgo`,
   `gcBgMarkWorker`), `-peek` it to find which of your functions drives it.
4. If `cum` is spread thinly across many functions, the cost is structural (allocation rate,
   serialization): switch to the heap `alloc_space` view.
5. Check sample count in the header: a 30 s profile at 100 Hz on 8 busy cores has about 24,000
   samples; a few hundred samples means the process was mostly idle.

## go tool trace

```bash
go tool trace -pprof=net trace.out > net.pprof          # network blocking
go tool trace -pprof=sync trace.out > sync.pprof        # channel, mutex, WaitGroup blocking
go tool trace -pprof=syscall trace.out > syscall.pprof  # syscall time
go tool trace -pprof=sched trace.out > sched.pprof      # scheduler latency
go tool trace trace.out                                 # web UI; since 1.27 -http=:port binds localhost
```

Annotate application work so traces show it:

```go
ctx, task := trace.NewTask(ctx, "checkout")               // latency measured until task.End
defer task.End()
trace.WithRegion(ctx, "charge", func() { charge(ctx) })   // region inside the task
trace.Log(ctx, "order", orderID)                          // one-off event
r := trace.StartRegion(ctx, "render"); render(); r.End()  // End on the same goroutine, nested properly
```

`trace.Start(w)` / `trace.Stop()` capture a whole window programmatically; only one may be active,
though a `FlightRecorder` can run alongside it.
