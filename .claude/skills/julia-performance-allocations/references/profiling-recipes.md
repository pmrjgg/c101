# Profiling recipes (CPU, allocations, memory, GC)

Checked on Julia 1.13.2 unless noted. Agents read text or files; GUIs and web UIs are for humans.

## 1. CPU sampling profiler

```julia
using Profile
kernel!(out, x)                                  # compile outside the profile
Profile.init(delay = 1e-4)                       # default (10^7 IPs, 0.001 s); finer for short runs
Profile.clear()
@profile for _ in 1:200
    kernel!(out, x)
end
Profile.print(format = :flat, sortedby = :count, mincount = 50)   # hottest functions first
Profile.print(format = :tree, maxdepth = 25, mincount = 20)      # call tree
Profile.print(format = :flat, sortedby = :count, C = true)       # include C/runtime frames
Profile.print(groupby = :thread)                                 # per-thread breakdown
```

Reading `:flat` output: columns are `Count` (samples with the frame anywhere on the stack),
`Overhead` (samples where it was the top frame), file, line, function. High overhead on a line
is where time is spent; high count with low overhead means the time is in callees.

Runtime frames worth recognising with `C = true`:

| Frame | Meaning |
|---|---|
| `ijl_apply_generic`, `ijl_invoke` | runtime dispatch (type instability) |
| `ijl_gc_small_alloc`, `jl_alloc_genericmemory*` | heap allocation |
| `ijl_gc_collect` and `gc_mark*` frames | garbage collection |
| `jl_compile*`, `jl_type_infer*` | compilation inside the profiled region (warm up first) |

Boxing of scalars does not show a dedicated frame on 1.13 (the box is an inline small
allocation); it appears in the allocation profiler as `Float64`/`Int64` objects (section 2).

Exports:

```julia
using PProf
pprof(; web = false, out = ".stack/out/<agent>/cpu.pb.gz")    # file only; web=true opens a UI (humans)
```

With Go's pprof installed, `go tool pprof -top .stack/out/<agent>/cpu.pb.gz` prints a text
summary. GUI options for humans: VS Code `@profview f(x)`; `ProfileView.@profview f(x)` (write it
qualified inside VS Code, which defines its own `@profview`).

## 2. Allocation profiler

```julia
using Profile
Profile.Allocs.clear()
Profile.Allocs.@profile sample_rate = 0.05 step(pos, vel)    # default 0.1; 1.0 records everything
res = Profile.Allocs.fetch()
```

`res.allocs` is a vector of records with `type`, `size` and `stacktrace` (types are always
reported since 1.11). Counts are samples: divide by `sample_rate` to estimate totals.

Summariser (tested on 1.13): groups by type and first frame in user code.

```julia
function summarize_allocs(res = Profile.Allocs.fetch(); n = 10,
                          user = r"^(?!\./|.*/stdlib/|.*/base/|boot\.jl$|none$)")
    groups = Dict{Tuple{String,String},Tuple{Int,Int}}()     # (type, site) => (count, bytes)
    for a in res.allocs
        fr = findfirst(sf -> !sf.from_c && occursin(user, string(sf.file)), a.stacktrace)
        site = fr === nothing ? "?" :
            string(a.stacktrace[fr].func, " @ ", basename(string(a.stacktrace[fr].file)), ":", a.stacktrace[fr].line)
        key = (string(a.type), site)
        c, b = get(groups, key, (0, 0))
        groups[key] = (c + 1, b + a.size)
    end
    for ((T, site), (c, b)) in first(sort!(collect(groups); by = kv -> -kv[2][2]), n)
        println(rpad(string(b, " B"), 12), rpad(string(c, "x"), 8), rpad(T, 28), site)
    end
end
```

Output for the skill's "before" `step` (N = 10,000, sample_rate 0.05), abridged:

```
37200 B     930x    Memory{Float64}             step @ perf_defs.jl:9    <- slice copies, broadcast results
32352 B     1011x   Vector{Float64}             step @ perf_defs.jl:9
16672 B     521x    Tuple{Int64, Int64}         step @ perf_defs.jl:10
15200 B     1900x   Int64                       step @ perf_defs.jl:9    <- boxed indices: runtime dispatch
8128 B      1016x   Tuple{Int64, Colon}         step @ perf_defs.jl:9    <- boxed index tuple
7680 B      480x    Base.Broadcast.Broadcasted{...}  step @ perf_defs.jl:9
```

Interpretation: `Memory`/`Vector` entries are copies or temporaries (fix with views, `.=`,
preallocation); boxed `Int64`, `Float64` or small tuples are type instability (fix types first).

Other front ends: `Profile.print(res)` prints an allocation tree on 1.13;
`PProf.Allocs.pprof(res; web = false, out = ".stack/out/<agent>/allocs.pb.gz")`; VS Code
`@profview_allocs f(x) sample_rate=0.1` (default 0.0001 there).

## 3. Line-level allocation tracking

```bash
julia --project --track-allocation=user script.jl     # writes <file>.jl.<pid>.mem next to each source file
```

Inside `script.jl` run the workload once, call `Profile.clear_malloc_data()`, then run it again
so compilation allocations are excluded. Rank the results:

```julia
using Coverage
for m in first(sort(analyze_malloc("src"); by = m -> -m.bytes), 15)
    println(m.bytes, "  ", m.filename, ":", m.linenumber)
end
```

Delete the `*.mem` files afterwards (`find src -name '*.mem' -delete`); they are not source.
`--track-allocation=all` also counts Base and stdlib lines.

## 4. Heap and GC

- Heap snapshot: `Profile.take_heap_snapshot("app.heapsnapshot")`; open in a Chromium DevTools
  memory tab (humans). Data values are redacted by default (`redact_data=true`, 1.12+).
- GC logging: `GC.enable_logging(true)` prints a line per collection (pause time, heap size).
- `@time` prints `% gc time`; `@timed f(x)` returns a NamedTuple with `time`, `bytes`, `gctime`.
- Memory pressure: `julia --heap-size-hint=4G` makes the GC collect more eagerly below a limit;
  `--gcthreads=N[,M]` sets mark threads (and 0/1 concurrent sweep thread).
- A rising `gctime` share with more threads means allocation, not compute, limits scaling.

## 5. Profiling threaded code

- `Profile.print(groupby = :thread)` or `groupby = [:thread, :task]` to see imbalance.
- A thread with few samples while others are busy: load imbalance; use `:greedy` scheduling or
  smaller chunks.
- Many samples in `jl_gc_*` across all threads: allocations in the parallel region.
- Lock contention shows as time in `lock`/`wait` frames; switch to per-task accumulation.

## 6. Benchmark bookkeeping

```julia
using BenchmarkTools, LinearAlgebra
env = (julia = VERSION, threads = Threads.nthreads(), blas = BLAS.get_num_threads(), cpu = Sys.CPU_NAME)
old = @benchmark kernel_v1!($out, $x)
new = @benchmark kernel_v2!($out, $x)
judge(median(new), median(old))           # "improvement" / "regression" / "invariant" (5% time, 1% memory)
```

Save `env` with every reported number; numbers without the environment cannot be compared.
