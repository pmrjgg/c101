# Julia performance checklist, profiling and threading

## 1. The ten-point checklist (in order)

1. Code is inside functions (top-level code in scripts is not optimized the same way).
2. No non-const globals read in hot code (`const`, typed globals, or arguments).
3. Struct fields concrete or type parameters; containers have concrete element types.
4. Hot functions infer concrete return types (`@inferred`, `@code_warntype`, `JET.@report_opt`).
5. Loops iterate in memory order (column-major: first index innermost).
6. No hidden copies: `@views` on slices, in-place broadcasting `.=`, preallocated outputs.
7. Small fixed-size data uses StaticArrays or tuples.
8. Inner loops avoid dynamic dispatch (no `Vector{Any}`, no abstract-typed callbacks).
9. Bounds checks removed only where proven (`@inbounds`, `eachindex`), SIMD where reassociation is fine.
10. Measure with BenchmarkTools / Chairmarks, profile with `Profile` + a flame-graph viewer.

## 2. Benchmarking correctly

```julia
using BenchmarkTools
x = rand(10^6); out = similar(x)
@btime kernel!($out, $x)                         # interpolate globals with $
@btime sum(x) setup=(x = rand(10^6)) evals=1     # fresh input per sample
b = @benchmark kernel!($out, $x); median(b)      # distribution statistics
```

- Chairmarks.jl (`@b kernel!($out, $x)`) is a faster alternative with similar semantics.
- Constants that the compiler can fold produce nanosecond timings that mean nothing; wrap in
  `Ref` and dereference: `@btime f($(Ref(3.0))[])`.
- Compare variants in the same session; record Julia version, thread count, CPU.
- `BenchmarkTools.judge(median(new), median(old))` classifies regressions/improvements with a
  tolerance (default 5%).

## 3. Profiling

```julia
using Profile
kernel!(out, x)                              # compile first
Profile.clear(); @profile for _ in 1:100; kernel!(out, x); end
Profile.print(format=:flat, sortedby=:count, mincount=50)
# graphical: ProfileView.@profview, or in VS Code: @profview kernel!(out, x)
# pprof web UI (humans only): using PProf; pprof(); agents use Profile.print above
```

Allocation profiling:

```julia
Profile.Allocs.clear()
Profile.Allocs.@profile sample_rate=0.1 kernel!(out, x)
using PProf; PProf.Allocs.pprof(web=false, out=".stack/out/<agent>/allocs.pb.gz")   # file only; read with `go tool pprof -top` or summarise `Profile.Allocs.fetch().allocs` in code; web=true is humans only
```

Line-level allocation tracking for a whole run:
`julia --track-allocation=user script.jl`, then inspect the generated `*.mem` files
(Coverage.jl `analyze_malloc` sorts them). Run the workload twice in the script and call
`Profile.clear_malloc_data()` between runs to exclude compilation.

Zero-allocation guarantee in tests: AllocCheck.jl `@check_allocs` analyzes a function
statically and errors if any code path can allocate.

## 4. Reading `@code_warntype`

```
Body::Float64                      ← concrete return: good
  %1 = Main.scale::Any             ← global read typed Any: fix
  s::Union{Float64, Int64}         ← variable changes type: initialize with zero(T)
```

Yellow small `Union`s (e.g. `Union{Nothing, Int}`) are handled by union splitting and are usually
fine; red `Any`, abstract types and large unions in loops are not. `@code_llvm debuginfo=:none f(x)`
and `@code_native` confirm vectorization (`<4 x double>` / `vfmadd` instructions).

## 5. Compiler annotations

| Annotation | Effect | Safety |
|---|---|---|
| `@inbounds` | removes bounds checks in the block | memory corruption if wrong; verify with `--check-bounds=yes` |
| `@simd` | allows reordering of reductions for vectorization | changes floating-point summation order |
| `@fastmath` | IEEE relaxations (no NaN/Inf guarantees) | can break NaN handling |
| `@inline` / `@noinline` | inlining hints | `@noinline` on error paths keeps hot code small |
| `@nospecialize` | avoid compiling per argument type | for compile-time-heavy, perf-irrelevant code |
| `Base.@assume_effects` | promise purity/termination to the compiler | wrong promises cause miscompilation |
| `@turbo` (LoopVectorization.jl) | aggressive SIMD | package deprecated for Julia 1.11+; avoid in new code |

## 6. Memory layout patterns

- Arrays of structs of isbits fields (`Vector{SVector{3,Float64}}`, `Vector{MyImmutable}`) are
  stored inline and contiguous; arrays of mutable structs are arrays of pointers.
- StructArrays.jl gives struct-of-arrays layout with an array-of-structs interface (good for
  SIMD over one field).
- Avoid `Vector{Vector{T}}` for rectangular data; use `Matrix{T}` or `ElasticArrays`.
- Keep element types `isbitstype` (`isbitstype(T)` check) for GPU transfer and inline storage.

## 7. Threading patterns

```julia
using ChunkSplitters          # 3.x: index_chunks yields index ranges (2.x called this `chunks`)
function parallel_sum(f, xs; ntasks=Threads.nthreads())   # or OhMyThreads.tmapreduce(f, +, xs)
    tasks = map(index_chunks(xs; n=ntasks)) do idx
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

- Task-local accumulators, combined after `fetch`; no shared mutable state in the loop.
- `Threads.@threads :static` pins iterations to threads (rarely needed); the default `:dynamic`
  is composable with nested parallelism.
- Locks: `lk = ReentrantLock(); @lock lk push!(shared, x)`; atomics: `Threads.Atomic{Int}` or
  `@atomic` fields in `mutable struct`.
- GC is stop-the-world and multi-threaded since 1.10; allocation-heavy threaded code scales
  poorly; remove allocations first.
- Reproducible parallel RNG: give each task its own `Xoshiro(seed + task_index)`.

## 8. Compile latency (TTFX)

| Problem | Tool / fix |
|---|---|
| package slow to load | `@time_imports using MyPkg` (1.8+) lists per-dependency load times |
| first call slow | PrecompileTools `@compile_workload` with a representative workload |
| precompiled code discarded on load | invalidations: `using SnoopCompileCore; invs = @snoop_invalidations using MyPkg; using SnoopCompile; trees = invalidation_trees(invs)` (older SnoopCompile versions: `@snoopr`) |
| app startup | `PackageCompiler.create_sysimage([:MyPkg]; sysimage_path="app.so", precompile_execution_file="warmup.jl")` |
| small standalone binaries | 1.12+ `juliac --trim` via JuliaC.jl (experimental; code must be free of dynamic dispatch) |

## 9. Numerical accuracy

- Summation: `sum` uses pairwise summation (accurate); hand-written loops do not. Use
  `sum`/`mapreduce` or Kahan (`KahanSummation.jl`/`Xsum.jl`) when accuracy matters.
- Compare floats with `isapprox(a, b; rtol=..., atol=...)` (`≈`); set `atol` near zero values.
- Generic code over `T<:AbstractFloat` lets callers run in `Float32`, `Float64`, `BigFloat`,
  `Double64`, or with dual numbers (ForwardDiff): never hard-code `Float64` in kernels.
