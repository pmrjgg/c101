---
name: julia-performance-allocations
description: "Julia speed and allocation work once types are stable: BenchmarkTools and Chairmarks discipline, CPU and allocation profilers, an ordered performance checklist, views and in-place operations, broadcast fusion, StaticArrays, @inbounds/@simd, multithreading with OhMyThreads and ChunkSplitters, and compile latency (TTFX). Load when Julia code needs measured speedups or fewer allocations."
when_to_use: "Slow or allocation-heavy .jl kernels; @btime or @b reporting allocations; high '% gc time' in @time output; reading flame graphs or Profile.Allocs results; deciding between SIMD, StaticArrays and threads; wrong results or poor scaling with Threads.@threads; slow first call or package load (TTFX, invalidations); building PackageCompiler sysimages or juliac --trim executables."
---

# Julia performance and allocations

Precondition: the hot code is type-stable (see `julia-type-stability`); every tip below assumes
concrete types. Loop: measure, profile, change one thing, re-measure, keep the change only if the
number moved. Baseline: Julia 1.10 LTS to 1.13 release. All timings below were measured on Julia
1.13.2, Apple M3 Ultra (aarch64); absolute numbers differ per machine, ratios transfer.

Deep material: [profiling recipes](references/profiling-recipes.md) |
[threading patterns](references/threading-patterns.md) |
[compile latency and binaries](references/compile-latency.md)

## 1. Benchmarking discipline

| Tool | Call | Notes |
|---|---|---|
| BenchmarkTools | `@btime f!($out, $x)` | minimum time plus allocations; default budget 5 s / 10,000 samples, evals tuned |
| | `b = @benchmark f!($out, $x); median(b)` | full distribution |
| | `@ballocated f($x)`, `@belapsed f($x)`, `@btimed f($x)` | same arguments as `@benchmark` |
| | `@btime sort!(y) setup=(y = copy($x)) evals=1` | mutating code: setup runs once per sample, not per evaluation, so `evals=1` |
| Chairmarks | `@b f($x)` or `@b x f`; `@be f($x)` | 0.1 s default budget (`Chairmarks.DEFAULTS.seconds`); prints e.g. `95.500 ns (2 allocs: 928 bytes)`; arguments are functions, so globals hurt less than in BenchmarkTools |
| | `@b rand(1000) sort! evals=1` | first argument runs once per sample, second once per evaluation on its result |
| | `@b rand(100) sum(_ .* _),sum(abs2, _)` | experimental side-by-side comparison with randomized order |
| Base | `@time f(x)` (twice), `@timed`, `@allocated`, `@allocations` (1.9+) | first call includes `% compilation time` |

Rules:

1. Interpolate every global with `$` (BenchmarkTools); otherwise the benchmark measures a
   global-variable access. Multiple setup variables use `;`: `setup=(x=rand(n); y=rand(n))`.
2. Defeat constant folding: `@btime $a + $b` can report ~0.02 ns; use `$(Ref(a))[] + $(Ref(b))[]`.
3. Defeat dead-code elimination in hand-written timing loops: a 1e6-element `@simd` reduction
   timed with its result discarded measured 0.0 µs; with `Base.donotdelete(r)` (exists since
   1.8, public API since 1.12) it measured 139.8 µs.
4. Compare variants in one session; record `VERSION`, `Threads.nthreads()`,
   `BLAS.get_num_threads()`, `Sys.CPU_NAME`.
5. Regression check: `judge(median(new), median(old))` uses 5% time and 1% memory tolerance.
6. Report minimum for algorithmic comparisons, median when GC or threads add variance, and
   always the allocation count and bytes.

## 2. Profiling

```julia
using Profile
kernel!(out, x)                                       # compile first
Profile.clear(); @profile for _ in 1:200; kernel!(out, x); end
Profile.print(format=:flat, sortedby=:count, mincount=50)   # agents: text output
Profile.print(format=:flat, sortedby=:count, C=true)        # include runtime frames (ijl_apply_generic, GC)
```

Defaults: 1 ms sampling, buffer of 10^7 instruction pointers (`Profile.init()`); for runs under
~1 s use `Profile.init(delay=1e-4)`. Viewers for humans: VS Code `@profview f(x)`,
`ProfileView.@profview` (qualify it inside VS Code, whose own `@profview` conflicts), PProf web UI.
Agents write files: `using PProf; pprof(; web=false, out=".stack/out/<agent>/cpu.pb.gz")`.

Allocations:

```julia
Profile.Allocs.clear()
Profile.Allocs.@profile sample_rate=0.1 kernel!(out, x)    # default 0.1; 1.0 records every allocation
res = Profile.Allocs.fetch()                               # res.allocs: type, size, stacktrace
```

Summarise `res.allocs` by type and top user frame in code (snippet in
[profiling-recipes](references/profiling-recipes.md)); on 1.13 `Profile.print(res)` also works.
VS Code: `@profview_allocs f(x) sample_rate=0.1` (its default is 0.0001). Line level for a whole
script: `julia --track-allocation=user script.jl`, run the workload twice with
`Profile.clear_malloc_data()` in between, then read the `*.mem` files (Coverage.jl
`analyze_malloc("src")` sorts them). Static proof of zero allocations: AllocCheck
(`julia-type-stability`).

## 3. Ordered checklist

| # | Check | Verify with | Done when |
|---|---|---|---|
| 1 | hot code inside functions, not top-level script code | read the code | no loops at top level |
| 2 | no non-const globals in hot code | `@code_warntype` | no `::ANY` global reads |
| 3 | concrete, inferred types | `@report_opt`, `@inferred` | no runtime dispatch |
| 4 | outputs preallocated, mutating `f!` API | `@allocated` after warm-up | 0 or a fixed small budget |
| 5 | no hidden copies: `@views`, `.=` | `Profile.Allocs` | no `Array`/`Memory` allocs in the loop |
| 6 | broadcasts fused | allocation count | one loop per expression |
| 7 | column-major loop order | timing | first index innermost |
| 8 | small fixed-size data in StaticArrays or tuples | `isbitstype(eltype(v))` | no `Vector{Vector}` of length-3 data |
| 9 | concrete containers | `eltype` checks | no `Vector{Any}`, `Vector{Real}` |
| 10 | `@inbounds` / `@simd` only after verification | tests under `--check-bounds=yes` | vector instructions in `@code_llvm` |
| 11 | threads last | scaling test 1, 2, 4, N threads | allocations already ~0 (GC is stop-the-world) |

## 4. Arrays: views, in-place, layout

| Allocation source | Fix | Measured (1.13) |
|---|---|---|
| slice copies `A[:, j]` | `@views`, `view(A, :, j)` | 1000 column sums: 0.25 ms / 8.26 MB to 0.08 ms / 0.01 MB |
| `y = a * x .+ b` | `y .= a .* x .+ b` or `@. y = a * x + b` | 1e6 elements: 16.0 MB to 0 B |
| `x = x .+ 1` | `x .+= 1` | |
| temporaries inside loops | allocate once with `similar(x)` / `zeros(eltype(x), n)`, pass buffers to `f!` | |
| `push!` growth | `sizehint!(v, n)` or preallocate | |
| matrix products and solves | `mul!(C, A, B)`, `mul!(y, A, x, α, β)`, `F = lu!(A); ldiv!(F, b)` | |
| `sum(x.^2)`, `sum(f.(x))` | `sum(abs2, x)`, `sum(f, x)`, `mapreduce(f, op, x)` | |
| string building in loops | `io = IOBuffer(); print(io, ...); String(take!(io))` (`takestring!(io)` on 1.13) | |
| `Vector{Vector{T}}` for rectangular data | `Matrix{T}` (or ElasticArrays when growing) | |
| arrays of mutable structs (pointer per element) | immutable isbits structs, StructArrays.jl for struct-of-arrays | |

- Loop order: Julia arrays are column-major. Summing a 4000×4000 matrix took 11.0 ms with
  `for j in axes(A, 2), i in axes(A, 1)` and 32.2 ms with the indices swapped.
- Iterate with `eachindex(A)` / `eachindex(x, y)` (checks matching axes) and `axes(A, d)`; never
  assume `1:n` (offset arrays). With `eachindex` the compiler often removes bounds checks itself.
- `Memory{T}` (1.11+) is the fixed-size buffer `Array` is built on: lower overhead, no resizing;
  use it for fixed-capacity scratch buffers in low-level code.
- `reshape`, `vec`, `transpose`/`adjoint` and `reinterpret(reshape, SVector{3,Float64}, M)` (for a
  3×N matrix) are zero-copy views.

## 5. Broadcasting and fusion

- All dotted operations in one expression fuse into one loop with no temporaries:
  `@. y = a * x + b` equals `y .= a .* x .+ b`.
- A non-dotted call breaks fusion: `y .= a .* sin(x)` throws a `MethodError` for vector `x`;
  write `sin.(x)` or put the whole line under `@.`. Splice with `$` to keep one call un-dotted:
  `@. y = $norm(x) * x` expands to `y .= (*).(norm(x), x)` and calls `norm` once (checked).
- `.=` writes into existing memory; `y = ...` rebinds and allocates.
- Treat a container as a scalar with `Ref(v)` or a 1-tuple: `in.(xs, Ref(set))`.
- Custom types: `Base.broadcastable(x::MyScalarLike) = Ref(x)`; container types define a
  `BroadcastStyle`. On GPU arrays a fused broadcast compiles to one kernel.
- `Float32` arrays with `Float64` literals promote: write `0.5f0` or `oftype(x, 0.5)`.
- Reductions over expressions: `sum(abs2, x)` instead of `sum(x .^ 2)`; `@views` works inside
  broadcasts (`@views y[2:end] .= x[1:end-1] .* 2`).

## 6. StaticArrays for small fixed sizes

```julia
using StaticArrays
p = SVector(1.0, 2.0, 3.0)            # immutable, isbits, no heap allocation
q = SA[1.0, 2.0, 3.0]                 # literal syntax; SA[1 2; 3 4] isa SMatrix{2,2,Int}
R = @SMatrix [cos(θ) -sin(θ) 0; sin(θ) cos(θ) 0; 0 0 1]
r = R * p                             # unrolled, no allocation
p2 = setindex(p, 5.0, 2)              # returns a new SVector
m = MVector{3,Float64}(undef)         # mutable variant when in-place updates are required
```

- Size limit: the StaticArrays README calls ~100 elements a very rough threshold; beyond it
  compile time grows and `Array` becomes faster. Sizes must be known at compile time.
- Layout choice, measured for an elementwise update of 100,000 particles: 3×N `Matrix` columns
  (struct-of-arrays) 0.049 ms, `Vector` of 24-byte isbits 3-vectors (the `SVector{3,Float64}`
  layout) 0.069 ms, both 0 allocations. Array-of-`SVector` wins when each operation works on a
  whole particle (norms, cross products, 3×3 transforms, neighbour interactions); columns win for
  pure elementwise sweeps that SIMD across particles.
- `SVector` state is also the fast path for small ODE systems (`julia-sciml-diffeq`).

## 7. Loop annotations

| Annotation | Effect | Rule |
|---|---|---|
| `@inbounds` | removes bounds checks | only for proven indices; run tests with `--check-bounds=yes` (since Pkg 1.13 `Pkg.test()` inherits the parent's setting instead of forcing it) |
| `@simd` | lets LLVM reorder a reduction to vectorize | 1e6-element sum of squares: 139.8 µs vs 664.8 µs without; result changed in the 15th digit |
| `@simd ivdep` | also asserts no loop-carried memory dependencies | non-generic code only; wrong use gives wrong results |
| `@fastmath` | IEEE relaxations | can break `NaN`/`Inf` handling and change results; `--math-mode=ieee` disables it globally |
| `@inline` / `@noinline` | inlining hints | `@noinline` on error paths keeps hot loops small |
| SIMD.jl `Vec{4,Float64}`, `vload`, `vstore`, `VecRange` | explicit vectors | only when the compiler refuses to vectorize a profiled hot loop |
| LoopVectorization `@turbo` | aggressive vectorization | no active maintainer: its README routes fixes, including Julia 1.12 support, through SciML small grants; do not adopt in new code, keep a plain-loop fallback in old code |

Accuracy on the same 1e6 values: `sum(abs2, v)` (pairwise) matched a `BigFloat` reference
exactly, the `@simd` loop differed by 4e-15 relative, the plain sequential loop by 1.3e-14.
Prefer `sum`/`mapreduce` for accuracy; KahanSummation.jl or Xsum.jl when it matters more.
Confirm vectorization with `@code_llvm debuginfo=:none` (`<2 x double>` on aarch64,
`<4 x double>` on AVX2).

## 8. Threading

- Start Julia with threads: `julia -t auto` or `-t 8` (`JULIA_NUM_THREADS`). Since 1.12 one extra
  interactive thread is added by default (`-t 8` gave 8 default + 1 interactive threads);
  `-t 8,0` disables it. On 1.13, `auto` counts all Apple Silicon cores.
- `Threads.@threads :dynamic for i in eachindex(x)` (default schedule, composable),
  `:static` (one chunk per thread, not composable), `:greedy` (1.11+, shared queue, for very
  uneven iteration costs).
- Never size or index buffers with `Threads.threadid()`: tasks migrate between threads (since
  1.7). Give each task or chunk its own buffer and accumulator.
- Chunked reduction in Base, measured `sum(sin, x)` over 1e7 elements: 36.8 ms serial, 5.1 ms on
  8 threads (7.2x):

```julia
function tsum(f, xs; ntasks = Threads.nthreads())
    chunks = Iterators.partition(eachindex(xs), cld(length(xs), ntasks))
    tasks = map(chunks) do idx
        Threads.@spawn begin
            acc = zero(eltype(xs))              # task-local accumulator
            @inbounds for i in idx
                acc += f(xs[i])
            end
            acc
        end
    end
    return sum(fetch, tasks)
end
```

- OhMyThreads.jl: `tmapreduce(f, +, xs)`, `tmap`, `tforeach`, `@tasks for ... end` with
  `@set reducer=+` and `@local buf = similar(x)` (one buffer per task); keywords such as
  `ntasks`, `chunksize`, `scheduler=:static|:dynamic|:greedy` pass through when `scheduler` is a
  Symbol. The greedy scheduler needs a commutative and associative reducer.
- ChunkSplitters.jl 3.x: `index_chunks(x; n=ntasks)` yields index ranges, `chunks(x; n)` yields
  views (`size=` instead of `n=`, `split=RoundRobin()` for interleaving, `minsize=`); in 2.x the
  range-yielding function was called `chunks`.
- BLAS has its own threads (24 here by default): call `LinearAlgebra.BLAS.set_num_threads(1)` when
  Julia threads each run many small matrix operations.
- Allocation-heavy threaded code scales poorly: GC is stop-the-world (parallel marking with
  `--gcthreads`, 1.10+). Remove allocations before adding threads.
- `Distributed` (`addprocs`, `@everywhere`, `pmap`) for process isolation: separate heaps and GC,
  crash containment, clusters; pays serialization costs.
- Patterns for locks, atomics, per-task RNG and buffers:
  [threading-patterns](references/threading-patterns.md).

## 9. Compile latency (TTFX)

| Problem | Tool |
|---|---|
| package slow to load | `@time_imports using MyPkg` (per-dependency load and `__init__` time) |
| first call slow | PrecompileTools `@setup_workload` / `@compile_workload` in the package module |
| which methods compile at runtime | `@trace_compile f(x)` (1.12+) or `julia --trace-compile=stderr --trace-compile-timing` |
| precompiled code discarded | invalidations: `using SnoopCompileCore; invs = @snoop_invalidations using MyPkg; using SnoopCompile; trees = invalidation_trees(invs)` (SnoopCompile 3 renamed `@snoopr`) |
| inference time hot spots | SnoopCompile `@snoop_inference` (renamed from `@snoopi_deep`) |
| application startup | PackageCompiler `create_sysimage(["MyPkg"]; sysimage_path="sys.so", precompile_execution_file="warmup.jl")`, start with `julia -Jsys.so` |
| small standalone binary | `juliac` from JuliaC.jl (Julia 1.12+, experimental): `juliac --output-exe app --bundle build --trim=safe --experimental AppProject`; entry `function @main(args::Vector{String})` |

`--trim=safe` turns dynamic call sites it cannot resolve into build errors, so trimmed programs
must be type-stable end to end. Recipes: [compile-latency](references/compile-latency.md).

## 10. Worked example: 37 ms / 38 MB to 0.049 ms / 0 bytes

Particles in a periodic unit box, positions and velocities as N×3 matrices, N = 100,000.

Before:

```julia
wrap(x) = x - floor(x)
dt = 0.01
function step(pos, vel)
    newpos = pos + vel * dt                  # global dt: newpos is inferred Any; two temporaries
    for i in 1:size(newpos, 1)
        newpos[i, :] = wrap.(newpos[i, :])   # row slice copy + broadcast result, strided access
    end
    return newpos
end
```

After, three variants (results identical to the original, max difference 0.0):

```julia
const DT = 0.01
function step!(pos::Matrix{T}, vel::Matrix{T}, dt::T = T(DT)) where {T<:AbstractFloat}
    size(pos) == size(vel) || throw(DimensionMismatch("pos/vel"))
    @inbounds for j in axes(pos, 2), i in axes(pos, 1)          # column-major order
        pos[i, j] = wrap(pos[i, j] + vel[i, j] * dt)
    end
    return pos
end
step_bc!(pos, vel, dt = eltype(pos)(DT)) = (@. pos = wrap(pos + vel * dt); pos)   # fused broadcast

using StaticArrays                                               # array-of-structs layout
wrap(v::SVector) = map(wrap, v)
step_sv!(pos::Vector{SVector{3,T}}, vel::Vector{SVector{3,T}}, dt::T = T(DT)) where {T} =
    (pos .= wrap.(pos .+ vel .* dt); pos)
```

Measured (minimum of 30 runs after warm-up, fresh inputs each run):

| Variant | Time | Allocated | Allocations |
|---|---|---|---|
| `step` (before) | 36.9 ms | 38.4 MB | 1,396,942 |
| `step!` in-place column loop | 0.049 ms | 0 B | 0 |
| `step_bc!` fused `@.` | 0.049 ms | 0 B | 0 |
| array of 3-vectors (`SVector{3,Float64}` layout; timed with an equivalent 24-byte isbits struct) | 0.069 ms | 0 B | 0 |

Scaling check: N = 200,000 and 400,000 gave 71.7 ms / 76.8 MB and 147.2 ms / 153.6 MB before,
0.099 ms and 0.201 ms after: linear in N, so the fix holds. About 14 allocations per particle
before: the non-const `dt` made `newpos` an `Any`, so every row operation was dispatched at
runtime on top of the slice copies. Gate it: `@test (@allocated step!(pos, vel)) == 0`.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| benchmark reports 0 ns or sub-ns | constant folding or dead code | `$` interpolation, `Ref` trick, `Base.donotdelete` |
| mutating benchmark looks too fast | input already sorted/updated after the first evaluation | `setup=(y = copy($x)) evals=1` |
| allocations reported only in benchmarks, not in the function | non-interpolated globals in the benchmark expression | interpolate with `$` |
| `@time` dominated by compilation | first call | call twice or use `@btime` / `@b` |
| wrong sums with threads | shared accumulator, `threadid()` buffers | task-local accumulators, atomics, locks |
| threads give no speedup | allocations (GC), BLAS oversubscription, tiny work per task | remove allocations, `BLAS.set_num_threads(1)`, larger chunks |
| `@inbounds` crash or silent corruption | wrong index assumption | remove, rerun under `--check-bounds=yes` |
| StaticArrays code compiles for minutes | sizes far above ~100 elements | use `Array` |
| `@fastmath` results differ or `NaN` checks fail | relaxed IEEE semantics | remove it; restrict to proven-safe kernels |
| first call takes 30 s | TTFX: compilation, invalidations | PrecompileTools workload, fix invalidating methods, sysimage |

Related: `julia-type-stability`, `julia-sciml-diffeq`, `julia-gpu`, `julia-packages-environments`, `julia-optimization-jump`; hub `julia-craft`.
