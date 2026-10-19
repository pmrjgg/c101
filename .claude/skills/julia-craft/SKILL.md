---
name: julia-craft
description: "Julia expertise pack covering multiple-dispatch design, type stability with @code_warntype and JET, allocation hunting, broadcasting and loop fusion, StaticArrays, DifferentialEquations.jl, JuMP, Flux and Lux, CUDA.jl, BenchmarkTools, package and project environments, and pitfalls such as non-const globals and abstract containers. Load when writing, reviewing, profiling or packaging Julia code for scientific computing, optimization or ML."
when_to_use: "Any task touching .jl files, Project.toml/Manifest.toml, slow or allocating Julia code, ODE/SDE simulation, mathematical optimization models, Julia ML training loops, GPU kernels in Julia, or Julia package CI."
---

# Julia craft

Baseline: Julia 1.10 (LTS) through 1.12+ (1.11 added `Memory{T}`,
the `public` keyword and `@main`; 1.12 added binding world-age so structs and constants can be
redefined, and experimental `--trim` for `juliac` executables). Manage versions with `juliaup`
(`juliaup add 1.10`, `julia +1.10`). Package APIs in the SciML and ML ecosystems change between
majors; confirm signatures with `mcp__context7__resolve-library-id` then
`mcp__context7__query-docs` or the package docs before writing.

Deep material:
[performance checklist and profiling](references/performance-profiling.md) |
[SciML, JuMP, Flux/Lux and CUDA recipes](references/sciml-jump-ml-gpu.md)

## 1. Orient in a repo

```bash
julia --version; cat Project.toml; ls Manifest*.toml test/Project.toml docs/Project.toml 2>/dev/null
grep -n '\[compat\]' -A20 Project.toml
grep -rn 'Threads.@threads\|@spawn\|CUDA\|using Flux\|using Lux\|using JuMP' src | head
julia --project -e 'using Pkg; Pkg.status(; outdated=true)'
```

Record: Julia compat bound, package vs application (applications commit `Manifest.toml`,
packages do not), test environment style (`test/Project.toml` or `[extras]`), GPU usage,
threading model.

## 2. The gate

| Step | Command | Blocks when |
|---|---|---|
| Instantiate | `julia --project -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'` | resolve/precompile errors |
| Tests | `julia --project -e 'using Pkg; Pkg.test()'` (add `--threads=auto` when code is threaded) | failure |
| Package hygiene | `Aqua.test_all(MyPkg)` inside the test suite | ambiguities, piracy, stale deps, missing compat |
| Static inference check | `JET.test_package(MyPkg)` and `@test_opt` on hot functions | new errors / runtime dispatch in hot code |
| Type stability of hot functions | `@inferred f(args...)` in tests | inference returns a non-concrete type |
| Allocation budget | `@test (@allocated f!(out, x)) == 0` after a warm-up call | allocations in a zero-alloc kernel |
| Format | `JuliaFormatter.format(".")` check mode or the project's formatter | diff |

## 3. Multiple dispatch design

Rules:
1. Write generic code against abstract types and interfaces (`AbstractVector`, `AbstractArray{T,N}`,
   iteration, `getindex`, `size`), dispatch on argument types, keep struct fields concrete.
2. One function, many methods: `area(::Circle)`, `area(::Square)`. Never `if x isa Circle ...`
   chains in library code.
3. No type piracy: do not add methods to functions you do not own for types you do not own
   (`Base.+(::Vector{String}, ::Vector{String})`). Aqua detects it.
4. Avoid method ambiguities: when two methods could both match (`f(::Number, ::Any)` and
   `f(::Any, ::Int)`), add the specific intersection method or restructure. `Aqua` / `Test.detect_ambiguities`.
5. Holy traits for orthogonal properties instead of deep hierarchies:

```julia
abstract type Smoothness end
struct Smooth <: Smoothness end
struct Rough  <: Smoothness end
smoothness(::Type) = Rough()                    # default
smoothness(::Type{<:MyKernel}) = Smooth()

integrate(f, a, b) = integrate(smoothness(typeof(f)), f, a, b)
integrate(::Smooth, f, a, b) = gauss_legendre(f, a, b)
integrate(::Rough,  f, a, b) = adaptive_simpson(f, a, b)
```

6. Extend Base interfaces instead of inventing names: implement `size`, `getindex`, `setindex!`,
   `IndexStyle` for arrays; `iterate`, `length`, `eltype` for iterables; `show(io, ::MIME"text/plain", x)` for display.
7. Mutating functions end with `!` and take the mutated argument first (`mul!(C, A, B)`).
8. Mark API with `export` (or `public` on 1.11+) and document with docstrings and `jldoctest` blocks.

## 4. Type stability

A function is type-stable when the types of all locals and the return value are inferable from
argument types. Instability means boxed values and runtime dispatch on every operation.

Check:

```julia
@code_warntype f(x)                 # red Any / Union{...} in Body or locals = problem (small Unions are OK)
using JET; @report_opt f(x)         # lists runtime dispatch sites including callees
using Cthulhu; @descend f(x)        # interactive TUI, humans only; agents use JET @report_opt above
@inferred f(x)                      # in tests: throws if return type not concrete
```

Fix table:

| Cause | Example | Fix |
|---|---|---|
| non-const global | `scale = 2.0; f(x) = scale * x` | `const scale = 2.0`, typed global `scale::Float64 = 2.0` (1.8+), or pass as argument |
| abstract field type | `struct P; x::Real; v::AbstractVector; end` | parametrize: `struct P{T<:Real,V<:AbstractVector{T}}; x::T; v::V; end` |
| abstract container | `xs = Real[]`, `Dict{Any,Any}()` | concrete: `Float64[]`, `Dict{Symbol,Int}()` |
| variable changes type | `s = 0; for x in v; s += x; end` (Int then Float64) | `s = zero(eltype(v))` |
| return type depends on values | `f(x) = x > 0 ? x : nothing` used in hot loops | small unions are fine; otherwise return a sentinel of the same type or split functions |
| captured variable reassigned in a closure | `Core.Box` in `@code_warntype` | do not reassign captured vars; use `let x = x` or pass explicitly |
| container from untyped source | `JSON.parse`, `DataFrame` column access in a loop | function barrier: extract, then call a kernel `kernel(col::Vector{Float64})` |
| type-unstable keyword or `Val` misuse | `Val(n)` with runtime `n` | dispatch on types known at compile time only |
| function argument not specialized | higher-order `g(f, x)` stored in a field `f::Function` | field `f::F` with type parameter `F` |

Function barrier pattern:

```julia
function process(path)
    data = load_untyped(path)                 # type-unstable, called once
    xs = convert(Vector{Float64}, data["x"])  # concretize
    return kernel(xs)                         # kernel is compiled for Vector{Float64}
end
```

## 5. Allocations and loop performance

Workflow: warm up (first call compiles), then measure with BenchmarkTools, interpolating
globals with `$`:

```julia
using BenchmarkTools
@btime f!($out, $x)                  # minimum time + allocations
@benchmark f!($out, $x)              # distribution
@allocated f!(out, x)                # bytes, after a warm-up call
```

| Allocation source | Fix |
|---|---|
| slicing `A[:, j]` copies | `@views` or `view(A, :, j)` |
| `x = x .+ 1` | `x .+= 1` (in place) |
| unfused broadcast: `y .= f(x) .+ 1` where `f(x)` is not dotted | `y .= f.(x) .+ 1` or `@. y = f(x) + 1` |
| temporary arrays in a loop | preallocate outside, pass buffers to `foo!` functions |
| small fixed-size vectors (3D points, 4x4 matrices) | `StaticArrays.SVector`/`SMatrix` (stack-allocated, size <= ~100 elements) |
| `push!` growth | `sizehint!(v, n)` or preallocate |
| string concatenation in loops | `IOBuffer` + `print(io, ...)`, then `String(take!(io))` |
| type instability | section 4; unstable code allocates boxes |
| matrix products into new arrays | `mul!(C, A, B)`, `ldiv!`, BLAS in-place variants |
| `sum(x.^2)` | `sum(abs2, x)` (no temporary) |

Loop rules: Julia arrays are column-major, iterate the first index innermost
(`for j in axes(A,2), i in axes(A,1)`); use `eachindex`/`axes` (works for offset arrays);
`@inbounds` only after the indices are proven in range (bounds-check errors become memory
corruption); `@simd` for reductions you allow to reassociate; `@fastmath` only with care.

Deep checklist, profiling and threading in [performance-profiling](references/performance-profiling.md).

## 6. Broadcasting and fusion

- Dotted operations in one expression fuse into a single loop with no temporaries:
  `@. y = a * x + b` equals `y .= a .* x .+ b`.
- A non-dotted call in the middle breaks fusion and allocates (`y .= a .* sin(x)` errors for a
  vector `x`; `sin.(x)` inside is required).
- Treat an array as a scalar in broadcasting with `Ref(v)` (`in.(xs, Ref(set))`).
- Custom types participate by defining `Base.broadcastable` or a `BroadcastStyle`; on GPU arrays
  fused broadcasts compile to one kernel.
- Broadcasting over `Float32` arrays with `Float64` literals promotes: write `0.5f0` or
  `oftype(x, 0.5)` for type-generic code.

## 7. StaticArrays

```julia
using StaticArrays
p = SVector(1.0, 2.0, 3.0)            # immutable, stack
R = @SMatrix [cos(θ) -sin(θ) 0; sin(θ) cos(θ) 0; 0 0 1]
q = R * p                             # unrolled, no allocation
p2 = setindex(p, 5.0, 2)              # new SVector (immutable)
m = MVector{3,Float64}(undef)         # mutable, when in-place updates are needed
```

Use for sizes known at compile time and small (rule of thumb: under ~100 elements); larger
static sizes explode compile time. Arrays of `SVector` (`Vector{SVector{3,Float64}}`) are a
cache-friendly layout for particle and mesh data.

## 8. Packages and environments

| Task | Command (shown in REPL `]` form for humans; agents run the `Pkg.` API: `julia --project=. -e 'using Pkg; Pkg.add("Foo")'`, `Pkg.rm`, `Pkg.develop(path="../Foo")`, `Pkg.update("Foo"; preserve=Pkg.PRESERVE_ALL)`, `Pkg.status(; outdated=true)`) |
|---|---|
| use project in current dir | `julia --project=.` (or `@.` to search upward) |
| add / remove | `]add Foo`, `]rm Foo` |
| develop a local package | `]dev ../Foo` |
| compat bounds (required for registration) | `[compat] Foo = "1.2"` (caret semantics: >=1.2, <2.0) |
| optional integration | `[weakdeps]` + `[extensions]` (package extensions, 1.9+) instead of Requires.jl |
| unregistered source | `[sources]` section (1.11+) |
| test-only deps | `test/Project.toml` (preferred) |
| reproducibility for apps | commit `Manifest.toml`; CI runs `Pkg.instantiate()` |
| update safely | `]up --preserve=all` then targeted `]up Foo`; check `]status --outdated` |
| new package skeleton | `PkgTemplates.Template(; plugins=[GitHubActions(), Codecov(), Documenter{GitHubActions}()])` |
| latency (TTFX) | `PrecompileTools.@setup_workload` / `@compile_workload` in the package; check invalidations with SnoopCompile |

Keep the default `@v1.x` environment minimal (Revise, BenchmarkTools, JET, Cthulhu); never put
project dependencies there.

## 9. Threads and parallelism

- Start with `julia -t auto` (or `JULIA_NUM_THREADS`); `Threads.nthreads()` to check.
- `Threads.@threads for i in eachindex(x)` for simple loops; `Threads.@spawn` + `fetch` for tasks.
- Never index per-thread buffers with `Threads.threadid()`: tasks can migrate between threads
  (since 1.7). Chunk the work and give each task its own buffer (`ChunkSplitters.jl`,
  `OhMyThreads.jl` `tmapreduce`).
- Combine threads and BLAS carefully: `LinearAlgebra.BLAS.set_num_threads(1)` when parallelizing
  over many small matrix operations.
- Distributed (multi-process) via `Distributed` / `addprocs` for memory isolation or clusters.

## 10. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| slow, allocating code with no obvious arrays | non-const globals / type instability | `const`, function barrier, `@code_warntype` |
| first call takes 30 s | compilation (TTFX), invalidations | PrecompileTools workload, fix invalidating methods, sysimage for apps (PackageCompiler) |
| benchmark shows 0 ns | constant folded / not interpolated | `$x` interpolation, `Ref` trick for scalars |
| wrong results with threads | shared accumulator, `threadid()` buffers | per-chunk accumulators, atomics, locks |
| `MethodError` with "world age" | calling a method defined via `eval` in the same call | `invokelatest`, restructure codegen |
| GPU code slow with warnings about scalar indexing | element-wise CPU-style loops on `CuArray` | broadcast, kernels, `CUDA.allowscalar(false)` |
| `Float64` sneaks into `Float32` pipeline | literals, `rand()` default type | `0.5f0`, `rand(Float32, n)`, `eltype`-generic code |
| `InexactError` / silent overflow | `Int` overflow wraps silently; conversions throw | `widen`, `BigInt` where needed, `Base.checked_add` |
| package load breaks after update | missing `[compat]` bounds | add compat for every dependency; CompatHelper |
| `@inbounds` segfault/corruption | wrong index assumption | remove, test with `--check-bounds=yes` |
| tests pass locally, fail in CI | unpinned Manifest in an app, RNG | commit Manifest for apps; `StableRNGs.jl` for reproducible random streams across versions |

## 11. Review checklist

- [ ] Struct fields concrete or parametric; no `Any`/abstract element containers in hot paths.
- [ ] Hot functions pass `@inferred` / `@test_opt`; allocations measured and budgeted.
- [ ] No non-const globals used in computation; function barriers around untyped data.
- [ ] Mutating API uses `!` and accepts preallocated outputs.
- [ ] Generic over number types (`zero(T)`, `oneunit`, `eltype`) where the domain allows.
- [ ] Methods extend Base interfaces properly; no piracy; no ambiguities (Aqua passes).
- [ ] `[compat]` complete; Manifest committed only for applications.
- [ ] Threading uses chunked task-local state; RNG seeded per task where reproducibility matters.
- [ ] Numerical choices documented (solver, tolerances, termination status checked).

## 12. Worked example: from 40 ms and 30 MB to 0.4 ms and 0 bytes

Before:

```julia
dt = 0.01
function step(pos, vel)
    newpos = pos + vel * dt             # global dt (non-const): unstable; allocates two arrays
    for i in 1:size(newpos, 1)
        newpos[i, :] = wrap.(newpos[i, :])   # row slices copy; row-wise access is cache-hostile
    end
    return newpos
end
```

After:

```julia
const DT = 0.01
function step!(pos::Matrix{T}, vel::Matrix{T}, dt::T=T(DT)) where {T<:AbstractFloat}
    @assert size(pos) == size(vel)
    @inbounds for j in axes(pos, 2), i in axes(pos, 1)    # column-major order
        pos[i, j] = wrap(pos[i, j] + vel[i, j] * dt)
    end
    return pos
end
```

Or the broadcast form `@. pos = wrap(pos + vel * dt)` (one fused loop, zero allocations).
Better still for 3D particles: store `Vector{SVector{3,T}}` so each particle is one cache-friendly
value, then `pos .= wrap.(pos .+ vel .* dt)` with `wrap(::SVector)` defined.

Verify: `@btime step!($pos, $vel)` reports `0 allocations`; `@inferred step!(pos, vel)` passes.

## Delegation hints

- Solver selection and numerical stability questions: `mathematics-expert` or `physics-expert`
  with the model equations attached.
- Systematic allocation and kernel tuning with a target: `code-optimizer`.
- GPU kernel review and data-transfer analysis: a second `julia-expert` pass with the
  [GPU recipes](references/sciml-jump-ml-gpu.md).

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `julia-performance-allocations` | Julia code needs measured speedups or fewer allocations |
| `julia-sciml-diffeq` | simulating ODE, SDE, DAE or DDE models, or fitting model parameters in Julia |
| `julia-type-stability` | Julia code is slow, allocates unexpectedly, or JET reports runtime dispatch |
