# Threading patterns

Base snippets were run on Julia 1.13.2 with `-t 4` and produced correct results; package
snippets follow the OhMyThreads 0.8 and ChunkSplitters 3.2 documentation.

## 1. Choosing the mechanism

| Situation | Use |
|---|---|
| simple loop, uniform iteration cost | `Threads.@threads :dynamic for i in eachindex(x)` |
| very uneven iteration cost | `Threads.@threads :greedy` (1.11+) or OhMyThreads `scheduler=:greedy` |
| reduction | chunked `@spawn` with task-local accumulators, or `OhMyThreads.tmapreduce` |
| per-task scratch buffers | `@local` in OhMyThreads `@tasks`, `OncePerTask` (1.12+), or allocate inside the chunk task |
| nested parallelism (parallel code calling parallel code) | `@spawn` / `:dynamic` (composable); avoid `:static` |
| independent heavy jobs needing memory isolation, or many machines | `Distributed` (`addprocs`, `pmap`) |
| GPU-sized data parallelism | see `julia-gpu` |

## 2. Chunked reduction (Base)

```julia
function tsum(f, xs; ntasks = Threads.nthreads())
    chunks = Iterators.partition(eachindex(xs), cld(length(xs), ntasks))
    tasks = map(chunks) do idx
        Threads.@spawn begin
            acc = zero(eltype(xs))
            @inbounds for i in idx
                acc += f(xs[i])
            end
            acc
        end
    end
    return sum(fetch, tasks)
end
```

Measured `tsum(sin, rand(10^7))`: 36.8 ms serial loop, 5.1 ms with 8 threads. Use 2-8 tasks per
thread (`ntasks = 4 * Threads.nthreads()`) when chunk costs vary.

## 3. `@threads` with chunk-local slots

```julia
function chunked_threads(xs; nchunks = Threads.nthreads())
    parts = collect(Iterators.partition(eachindex(xs), cld(length(xs), nchunks)))
    partial = zeros(length(parts))
    Threads.@threads for (k, idx) in collect(enumerate(parts))
        acc = 0.0
        for i in idx
            acc += xs[i]^2
        end
        partial[k] = acc            # one slot per chunk: safe even if tasks migrate
    end
    return sum(partial)
end
```

The broken variant indexes `partial[Threads.threadid()]`: tasks can migrate between threads
(since 1.7), and since 1.12 thread 1 belongs to the interactive pool. With `-t 4` on 1.13 a
`@threads` loop ran on thread ids 2-5 while `Threads.nthreads()` returned 4, so
`zeros(Threads.nthreads())[Threads.threadid()]` would throw a `BoundsError` on id 5.

## 4. ChunkSplitters 3.x

```julia
using ChunkSplitters                  # exports index_chunks, chunks, Consecutive, RoundRobin
for (k, idx) in enumerate(index_chunks(x; n = 4))        # idx is a UnitRange (Consecutive)
    # ...
end
index_chunks(x; size = 1000)                             # fixed chunk size instead of a count
index_chunks(x; n = 4, split = RoundRobin())             # interleaved (StepRange) indices
index_chunks(x; n = 64, minsize = 10_000)                # fewer chunks if they would be too small
for c in chunks(x; n = 4)                                # c is a view of the elements
    # ...
end
```

`n` and `size` are mutually exclusive. ChunkSplitters 2.x called the index-range iterator
`chunks`; code written for 2.x silently changes meaning on 3.x.

## 5. OhMyThreads

```julia
using OhMyThreads: tmapreduce, tmap, tforeach, @tasks, @set, @local
s = tmapreduce(sin, +, x)                                  # parallel sum(sin, x); op must be associative
s = tmapreduce(sin, +, x; scheduler = :static, chunksize = 10_000)   # kwargs go to the scheduler
y = tmap(f, x)                                             # parallel map
tforeach(eachindex(x)) do i                                # side effects only
    out[i] = f(x[i])
end

function matsums(As, Bs)                                   # task-local buffer with @local
    N = size(first(As), 1)
    @tasks for i in eachindex(As, Bs)
        @set reducer = +
        @local C = Matrix{Float64}(undef, N, N)            # allocated once per task
        mul!(C, As[i], Bs[i])
        sum(C)
    end
end
```

Schedulers (`scheduler=` Symbol or object):

| Scheduler | Behaviour | Key options |
|---|---|---|
| `:dynamic` / `DynamicScheduler()` (default) | tasks spawned per chunk, composable | `ntasks`/`nchunks` (default `nthreads()`), `chunksize`, `split` |
| `:static` / `StaticScheduler()` | one task pinned per thread | `ntasks`, `chunksize`, `split` |
| `:greedy` / `GreedyScheduler()` | tasks pull items from a shared queue | `ntasks`, `chunking=false`; reducer must be commutative too |
| `:serial` / `SerialScheduler()` | no threading (debugging) | none |

Keyword forwarding (`chunksize=...` etc.) works only when `scheduler` is given as a Symbol.
`@allow_boxed_captures` / `@localize` exist for closures that would otherwise box captured
variables; OhMyThreads errors on boxed captures by default.

## 6. Shared state when unavoidable

```julia
L = Base.Lockable(Int[])                         # 1.11+: value bundled with its lock
@sync for i in 1:100
    Threads.@spawn @lock L push!(L[], i)
end

lk = ReentrantLock()
@lock lk push!(shared, x)                        # classic lock

mutable struct Counter
    @atomic n::Int                               # atomic field
end
c = Counter(0)
@sync for i in 1:1000
    Threads.@spawn @atomic c.n += 1
end

a = Threads.Atomic{Int}(0)
Threads.@threads for i in 1:1000
    Threads.atomic_add!(a, 1)
end
```

All four produced the exact expected counts (100, 1000, 1000) under 4 threads. Locks and atomics
in a hot loop serialize it: accumulate per task and combine once.

## 7. Per-task scratch buffers and reproducible randomness

```julia
const SCRATCH = OncePerTask{Vector{Float64}}(() -> zeros(64))   # 1.12+
work(i) = (buf = SCRATCH(); buf .= i; sum(buf))                  # one buffer per task

function mc_pi(n; nchunks = 8, seed = 42)
    parts = Iterators.partition(1:n, cld(n, nchunks))
    tasks = [Threads.@spawn begin
                 rng = Xoshiro(seed + k)                         # stream fixed by chunk index
                 cnt = 0
                 for _ in idx
                     cnt += (rand(rng)^2 + rand(rng)^2 <= 1)
                 end
                 cnt
             end for (k, idx) in enumerate(parts)]
    return 4 * sum(fetch, tasks) / n
end
```

`mc_pi(10^6)` returned the same value (3.140632) on repeated runs: results depend on `nchunks`
and `seed`, not on the thread count or scheduling.

## 8. BLAS and threads

- `LinearAlgebra.BLAS.get_num_threads()` reported 24 on the test machine with 4 Julia threads:
  BLAS has its own pool.
- Julia threads each calling BLAS on small matrices oversubscribe cores:
  `BLAS.set_num_threads(1)` inside such programs; keep BLAS threads for single large products.

## 9. Distributed

```julia
using Distributed
addprocs(4)                                    # or julia -p 4
@everywhere using MyPkg                        # load code on every worker
results = pmap(MyPkg.simulate, param_list; batch_size = 10)
```

Workers have separate heaps and GC (no stop-the-world interference, crash containment) and can
live on other machines; arguments and results are serialized, so send parameters, not big arrays.
