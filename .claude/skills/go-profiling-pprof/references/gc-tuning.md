# Go GC and memory tuning reference

## Decoding GODEBUG=gctrace=1

```text
gc 12 @3.418s 4%: 0.031+2.1+0.024 ms clock, 0.25+0.48/4.1/9.6+0.19 ms cpu, 38->39->20 MB, 40 MB goal, 0 MB stacks, 0 MB globals, 8 P
```

| Field | Meaning |
|---|---|
| `gc 12` | GC cycle number |
| `@3.418s` | seconds since program start |
| `4%` | share of CPU time spent in GC since start: above ~10% is worth attacking |
| `0.031+2.1+0.024 ms clock` | wall time: stop-the-world sweep termination + concurrent mark + STW mark termination |
| `0.25+0.48/4.1/9.6+0.19 ms cpu` | CPU time: STW + mark assist / background mark / idle mark + STW |
| `38->39->20 MB` | heap at GC start -> heap at GC end -> live heap marked |
| `40 MB goal` | heap goal for this cycle |
| `0 MB stacks`, `0 MB globals` | scannable stack and global sizes (part of the GC roots) |
| `8 P` | processors used (GOMAXPROCS) |

Signals: a large assist term (first of the three mark CPU numbers) means goroutines are paying GC
cost inline, which shows as request latency; cycles every few milliseconds mean the allocation rate
is high relative to the live heap and `GOGC`.

## Heap goal arithmetic

Goal = live + (live + roots) x GOGC/100, subject to `GOMEMLIMIT`.

| Live heap | Roots | GOGC | Goal | Allocation between cycles |
|---|---|---|---|---|
| 200 MiB | 10 MiB | 100 | 410 MiB | 210 MiB |
| 200 MiB | 10 MiB | 200 | 620 MiB | 420 MiB (about half the cycles) |
| 200 MiB | 10 MiB | 50 | 305 MiB | 105 MiB (about twice the cycles) |

GC CPU is roughly proportional to cycles x (live heap + roots) scanned, so doubling `GOGC` roughly
halves GC CPU at the cost of peak heap.

## Container sizing

| Container memory limit | Suggested `GOMEMLIMIT` | Why |
|---|---|---|
| 512 MiB | 460MiB | ~10% headroom for non-Go memory and measurement lag |
| 1 GiB | 920MiB | |
| 4 GiB | 3700MiB | |

Units accepted: `B`, `KiB`, `MiB`, `GiB`, `TiB`. Set it in code with `debug.SetMemoryLimit(n)`.
`GOMEMLIMIT` covers memory the Go runtime manages (heap, goroutine stacks, runtime structures); it
does not cover C allocations via cgo or memory mapped outside the runtime: subtract those first.

Checklist for a service in Kubernetes:
1. CPU limit set: Go 1.25+ derives `GOMAXPROCS` from it (rounded up); without a limit it uses all
   node cores, and CPU requests are ignored.
2. Memory limit set and `GOMEMLIMIT` at about 90% of it.
3. Keep `GOGC` at 100 unless profiles show GC CPU above ~10% with memory headroom left.
4. Watch `/gc/limiter/last-enabled:gc-cycle`: when it keeps advancing, the GC CPU limiter is
   engaging and the live heap is too close to the limit: raise the limit or cut the live heap.

## runtime/metrics worth exporting

| Metric | Use |
|---|---|
| `/gc/heap/live:bytes` | live heap after the last GC: the leak signal |
| `/gc/heap/goal:bytes` | current heap goal |
| `/gc/heap/allocs:bytes`, `/gc/heap/allocs:objects` | cumulative allocation: rate of change is the allocation rate |
| `/gc/cycles/total:gc-cycles` | GC frequency |
| `/sched/pauses/total/gc:seconds` | distribution of GC stop-the-world pause latencies |
| `/cpu/classes/gc/total:cpu-seconds`, `/cpu/classes/gc/mark/assist:cpu-seconds` | GC CPU, assists |
| `/gc/gogc:percent`, `/gc/gomemlimit:bytes` | effective settings |
| `/gc/limiter/last-enabled:gc-cycle` | last cycle where the GC CPU limiter engaged |
| `/memory/classes/heap/objects:bytes`, `/memory/classes/heap/released:bytes`, `/memory/classes/total:bytes` | heap objects, memory returned to the OS, total mapped |
| `/sched/latencies:seconds` | time goroutines wait runnable: CPU starvation or throttling |
| `/sched/goroutines:goroutines`, `/sched/goroutines-created:goroutines` | goroutine count and creation rate (state breakdown under `/sched/goroutines/*` in 1.26+) |
| `/sched/gomaxprocs:threads` | effective GOMAXPROCS (changes when cgroup limits change) |
| `/sync/mutex/wait/total:seconds` | cumulative time blocked on `sync.Mutex`/`RWMutex` |

```go
samples := []metrics.Sample{{Name: "/gc/heap/live:bytes"}, {Name: "/sched/latencies:seconds"}}
metrics.Read(samples)
live := samples[0].Value.Uint64()
hist := samples[1].Value.Float64Histogram()   // Counts and Buckets
```

`metrics.All()` lists every supported metric with its description for the running toolchain.

## Allocation reduction toolbox

| Technique | When |
|---|---|
| preallocate with known length (`make([]T, 0, n)`, `make(map[K]V, n)`) | sizes known or estimable |
| reuse a buffer across iterations (`buf = buf[:0]`) | loops on one goroutine |
| `sync.Pool` of `*bytes.Buffer` or large structs, capped before `Put` | short-lived, per-request, large objects |
| `strconv.Append*`, `fmt.Appendf`, `strings.Builder.Grow` | building strings and byte slices |
| values instead of pointers in slices (`[]T` not `[]*T`) | fewer objects and fewer pointers to scan |
| pointer-free structs (IDs instead of pointers, `[N]byte` instead of string) | big caches: GC skips scanning pointer-free spans |
| `unique.Make` interning (1.23) | many duplicate strings |
| avoid `[]byte` <-> `string` round trips | parsing hot paths |
| streaming encoders and decoders (`json.NewEncoder(w)`, `bufio`) | large payloads |

## Returning memory to the OS

The runtime returns free memory to the OS in the background (scavenger). `debug.FreeOSMemory()`
forces a GC and an immediate return: use for one-off batch phases, never per request. RSS that
stays above `/memory/classes/total:bytes` minus `/memory/classes/heap/released:bytes` points at
non-Go memory (cgo, mmap).
