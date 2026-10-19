---
name: julia-type-stability
description: "Julia type-stability diagnosis and repair: reading @code_warntype, JET @report_opt and @test_opt, Cthulhu, DispatchDoctor @stable, AllocCheck, a cause-to-fix table, function barriers, parametric struct design, specialization control, codegen checks and CI gates. Load when Julia code is slow, allocates unexpectedly, or JET reports runtime dispatch."
when_to_use: "Hot .jl functions that allocate inside scalar loops; @code_warntype shows red Any, abstract types or Core.Box; JET prints 'runtime dispatch detected'; @inferred throws 'does not match inferred return type'; DispatchDoctor TypeInstabilityError or AllocCheckFailure; profiles dominated by ijl_apply_generic; adding inference and zero-allocation gates to Julia CI."
---

# Julia type stability

A method instance is type-stable when inference can give every local and the return value a
concrete type from the argument types alone. Fix stability before any other performance work
(loop tuning, threads, SIMD): unstable code boxes values and dispatches at runtime, and nothing
downstream compensates for that.

Baseline (October 2026): Julia 1.13.2 is the release, 1.10.12 the LTS (`juliaup add lts`).
Tool versions and their Julia coupling:

| Tool | Version | Julia support | Agent use |
|---|---|---|---|
| `@code_warntype`, `@inferred`, `Base.return_types` | stdlib | all | yes |
| `@trace_dispatch` / `--trace-dispatch=stderr` | InteractiveUtils | 1.12+ | yes |
| JET.jl | 0.12.x | full analysis on 1.12 and 1.13 only; 0.9 series for 1.11; check `JET.JET_AVAILABLE` | yes |
| Cthulhu.jl | 3.x | 1.12+ (`2.16` branch for 1.10/1.11) | no: interactive TUI, humans only |
| DispatchDoctor.jl | 0.4.x | checks active only on [1.10, 1.13) per its README; a no-op on 1.13 | yes, in tests |
| AllocCheck.jl | 0.2.x | 1.10+ | yes |

Deep material: [annotated @code_warntype, JET and trace output](references/warntype-and-jet-output.md) |
[CI test templates](references/ci-gates.md)

## 1. What instability costs and how it shows up

| Mechanism | What happens | Signature |
|---|---|---|
| Boxing | a value whose type is unknown is heap-allocated with a type tag | allocations inside scalar loops |
| Runtime dispatch | each call on an `Any` value goes through the method table (`ijl_apply_generic`) | `ijl_apply_generic` in `Profile.print(C=true)` and in `@code_llvm` |
| Lost optimization | no inlining, no SIMD, no constant propagation past the unstable value | 10-1000x slowdown versus the stable kernel |
| Infection | an `Any` result makes every later operation in the function unstable too | one bad line turns the rest of the body red |

Benchmark rules of thumb:

- `allocs / inner iterations` is a small integer >= 1 in scalar code: boxing (instability).
  The worked example below measured 4,000,000 allocations for 1,000,000 inner iterations.
- Allocation count constant in problem size: setup or temporaries, see `julia-performance-allocations`.
- Time ratio stable/unstable of 100x or more on arithmetic loops is normal for this bug class
  (measured 241x below).

## 2. Diagnosis tools

Run in this order; stop when the cause is found.

```julia
f(x)                                  # 1. warm up (first call compiles)
@code_warntype f(x)                   # 2. read Locals and Body (section 2.1)
@code_warntype f(::Vector{Float64})   #    1.13+: type annotations instead of values
using JET; @report_opt f(x)           # 3. runtime dispatch in f and all callees
@report_opt target_modules=(MyPkg,) f(x)   # only report sites inside your package
@trace_dispatch f(x)                  # 4. 1.12+: prints precompile(...) per dynamically dispatched signature
Base.return_types(f, (Vector{Float64},))   # 5. scripted check: Any[Float64] good, Any[Any] bad
@inferred f(x)                        # 6. in tests: throws if the call's return type is not inferred
```

### 2.1 Reading `@code_warntype`

- Header `Arguments` and `Locals`: every entry should be concrete. `Body::T` is the return type.
- Red (non-concrete: `Any`, `Real`, `AbstractVector`, large unions) is a problem. Yellow is a
  small `Union` containing `Nothing` or `Missing`; usually fine (section 6).
- Plain-text output (piped to a file, captured by an agent) has no colour: warnings are printed
  in UPPERCASE (`Main.dt::ANY`, `@_5::UNION{NOTHING, TUPLE{INT64, INT64}}`). Grep for
  uppercase type names, then judge each: `ANY` and abstract types are bugs, the
  `UNION{NOTHING, TUPLE{...}}` of the `iterate` protocol is benign.
- A concrete `Body` does not prove stability. In the worked example `Body::Vector{Float64}`
  was printed while the body contained `%25 = Main.g::ANY` and `(%24)(%25, %26)::ANY`.
- `Core.Box` in Locals or in a closure type: a captured variable is reassigned (table row 6).

### 2.2 JET

```julia
using JET
JET.JET_AVAILABLE || @warn "JET analysis unavailable on this Julia version"
@report_opt f(x)                                   # call-site analysis, compiled callees included
report_opt(f, (Vector{Float64},))                  # by signature, no values needed
@report_opt ignored_modules=(Base,) f(x)           # silence reports inside Base
@test_opt target_modules=(MyPkg,) f(x)             # Test-integrated; fails on any report
```

Output: a header such as `═════ 1 possible error found ═════`, a call tree with `┌`/`│`/`└`
markers, and one `runtime dispatch detected: <call>::<type>` line per site. Fix the deepest
site in your own code first; reports inside Base usually disappear once your inputs are concrete.
`skip_noncompileable_calls=false` also reports inside calls Julia would not compile for the
inferred signature (noisier). `@report_call` (JET error analysis) finds `MethodError`s and
undefined names; run it after `@report_opt` is clean.

### 2.3 Enforcing stability in code: DispatchDoctor and AllocCheck

```julia
using DispatchDoctor: @stable, @unstable
@stable default_mode="warn" begin              # or "error" (default) or "disable"
    kernel(x::AbstractVector) = sum(abs2, x)
    @unstable describe(x) = string(x)          # opt out a method
end
```

- Throws `TypeInstabilityError` (mode `"error"`) when a call's inferred return type is not
  concrete. `default_union_limit=1` (default) treats every `Union` as unstable; set `2` to
  accept `Union{Nothing,T}`.
- Libraries: wrap with `default_mode="disable"` and switch on in tests via the
  `dispatch_doctor_mode` preference (`Preferences.set_preferences!("MyPkg", "dispatch_doctor_mode" => "error")`, restart Julia).
- Skipped automatically: precompilation, closures, `@generated`, functions containing
  `@nospecialize`, code reloaded by Revise, and Julia 1.13 (unsupported version range).

```julia
using AllocCheck
@check_allocs scale!(out, x) = (out .= 2 .* x; out)   # in-place fused broadcast: passes
@check_allocs scaled(x) = 2 .* x                        # allocates its result
scaled(rand(3))   # throws AllocCheckFailure: "@check_allocs function encountered N errors (...)"
check_allocs(scale!, (Vector{Float64}, Vector{Float64}))   # Vector of sites; empty = clean
```

AllocCheck statically analyses the compiled LLVM IR of the method and its callees, reporting
`AllocationSite`, `DynamicDispatch` and `AllocatingRuntimeCall` entries, so it catches
instability on rare branches that a runtime `@allocated` never executes. Allocations on throw
paths are ignored by default (`ignore_throw=false` to include them). The `@check_allocs`
wrapper behaves like a dynamic call on entry: put it on the outer entry point or main loop, not
on tiny inner functions. `check_allocs` results are not guaranteed identical across Julia
sessions; when allocation-freedom is a safety requirement, use `@check_allocs` in production.

## 3. Cause to fix table

| # | Cause | Example | Shows as | Fix |
|---|---|---|---|---|
| 1 | non-const global | `dt = 0.01; step(x) = x + dt` | `Main.dt::ANY` | `const DT = 0.01`; typed global `dt::Float64 = 0.01` (1.8+; inferred `Float64`); or pass as an argument |
| 2 | abstract field type | `struct P; x::Real; v::AbstractVector; end` | `p.x::Real`, callers return `Any` | type parameters: `struct P{T<:Real,V<:AbstractVector{T}}` (section 5) |
| 3 | abstract container | `Real[]`, `Any[]`, `Dict{Any,Any}()`, `Vector{AbstractFloat}`, field `x::Array{Float64}` (no `N`) | element reads `::Any` / `::Real` | concrete: `Float64[]`, `Dict{Symbol,Int}()`, `Matrix{Float64}`; build with comprehensions or `map` so the eltype is inferred |
| 4 | variable changes type | `s = 0; for x in v; s += x; end` with `v::Vector{Float64}` | `s::Union{Float64, Int64}` | `s = zero(eltype(v))`; in generic code `zero(T)`, `oneunit(T)` |
| 5 | value-dependent return type | `f(x) = x > 0 ? x : 0` for `Float64` `x`; `parse(flag ? Int : Float64, s)` | `Body::Union{...}` or `Any` | return one type (`zero(x)`, `float(x)`, `oftype(x, 0)`); split into two functions; keep a deliberate small `Union` only where callers branch on it |
| 6 | `Core.Box` from a reassigned capture | `s = 0.0; foreach(x -> (s += x), v)` | `Core.Box` local (verified on 1.13) | do not reassign captured variables: use `sum`/`foldl`, pass state as an argument, `let s = s ... end`, or a typed `Ref{Float64}` |
| 7 | untyped data source | `JSON.parse`, `Dict{String,Any}`, `DataFrame` row access in a loop, `eval` | `::Any` after `getindex` | function barrier (section 4): extract and `convert` once, then call a concrete kernel |
| 8 | runtime `Val` | `ntuple(_ -> 0.0, Val(n))` with runtime `n::Int` | `Tuple{Vararg{Float64}}` (verified) | `Val` only from literals or type parameters (`Val(3)` infers `NTuple{3,Float64}`); otherwise use a `Vector` |
| 9 | `Function`-typed field | `struct Op; f::Function; end` | `o.f(x)::Any` (verified) | `struct Op{F}; f::F; end` infers `Float64` for `Op{typeof(sin)}` (verified) |
| 10 | `Float64` leaks into a `Float32` pipeline | literal `0.5`, `rand()`, `zeros(n)` | not unstable but promotes and slows | `0.5f0`, `oftype(x, 0.5)`, `T(0.5)`, `rand(Float32, n)`, `zeros(eltype(x), n)` |

## 4. Function-barrier pattern

Untyped data enters once at the boundary; the kernel is compiled for concrete types.

```julia
function load_and_run(path::AbstractString)
    data = JSON.parse(read(path, String))            # Dict{String,Any}: unstable, called once
    xs = convert(Vector{Float64}, data["x"])         # concretize at the boundary
    p  = (k = Float64(data["k"]), n = Int(data["n"]))   # NamedTuple of concrete fields
    return kernel(xs, p)                             # dispatch happens once, here
end
function kernel(xs::Vector{Float64}, p::NamedTuple{(:k, :n), Tuple{Float64, Int}})
    acc = 0.0
    for _ in 1:p.n, x in xs
        acc += p.k * x
    end
    return acc
end
```

Rules: one dynamic dispatch per barrier call is cheap; put the barrier outside loops; `convert`
copies, so a barrier that mutates must return the new array; for DataFrames pass whole
columns (`kernel(df.x)`), never iterate rows of an untyped table inside the hot loop.
Measured cost in the worked example: 281 µs including two 10,000-element converts versus 64.5 ms
for the unstable original.

## 5. Parametric struct design

```julia
struct Particles{T<:Real, V<:AbstractVector{T}}
    mass::T
    pos::V
    vel::V
    function Particles{T,V}(mass::T, pos::V, vel::V) where {T<:Real, V<:AbstractVector{T}}
        length(pos) == length(vel) || throw(DimensionMismatch("pos/vel lengths differ"))
        mass > 0 || throw(ArgumentError("mass must be positive"))
        return new{T,V}(mass, pos, vel)
    end
end
Particles(mass::T, pos::V, vel::V) where {T<:Real, V<:AbstractVector{T}} = Particles{T,V}(mass, pos, vel)
function Particles(mass::Real, pos::AbstractVector, vel::AbstractVector)   # promoting convenience form
    T = promote_type(typeof(mass), eltype(pos), eltype(vel))
    return Particles(T(mass), T.(pos), T.(vel))
end
```

Checked on 1.13: `Particles(1, [0.0, 1.0], [1, 2])` gives `Particles{Float64, Vector{Float64}}`;
`Float32` inputs stay `Float32`; views give a concrete `SubArray` parameter; the inner
constructor rejects bad mass and mismatched lengths.

Design rules:

- Tie related parameters: `V<:AbstractVector{T}` guarantees the element type matches `mass`.
- Validate invariants in the inner constructor only; outer constructors convert and delegate.
- `isconcretetype(S)` is `true` even for `struct S; x::Real; end`. Test fields instead:
  `all(isconcretetype, fieldtypes(typeof(s)))`, and `isbitstype(T)` when inline storage or GPU
  transfer matters.
- Avoid over-parameterization: parametrize only fields that vary between uses and sit on hot
  paths; fix the rest (`n::Int`, `name::String`). Do not parametrize on runtime values
  (`Grid{N}` with `N` read from a file compiles per `N` and dispatches at construction). Five or
  more parameters usually means the struct should be split.
- Keep code generic over number types (`zero(T)`, `oneunit(T)`, `eltype`) so callers can run
  `Float32`, `BigFloat`, `Double64` or ForwardDiff duals; never hard-code `Float64` in kernels.
- Mutable state with a fixed type: concrete field in a `mutable struct`, or `Base.RefValue{T}`.

## 6. Small unions, `nothing` and `missing`

- Inference keeps unions of up to `max_union_splitting = 4` members
  (`Base.Compiler.InferenceParams()` on 1.13) and splits call sites into concrete branches.
  `findfirst` returning `Union{Nothing,Int}` compiled to 0 allocations in a check on 1.13.
- `Vector{Union{Missing,Float64}}` stores elements inline with a type-tag byte per element;
  no boxing.
- Handle the union where it appears: `i === nothing && return 0`, `something(x, default)`,
  `coalesce(x, default)`, `skipmissing(v)`, `ismissing(x)`.
- In tests permit an intended union explicitly: `@inferred Union{Nothing,Int} f(x)`.
- Large unions (5+ members), `Union{Int,Float64,String,...}` element types, and unions that flow
  into arithmetic loops are not split: restructure.

## 7. Specialization control

| Situation | Behaviour (checked on 1.13) | Action |
|---|---|---|
| keyword args with inferable values `kw(x; scale=2.0)` | specialized, infers `Float64` | fine |
| keywords splatted from `Dict{Symbol,Any}`: `kw(x; d...)` | infers `Any` | build a `NamedTuple` once at the boundary |
| splatting a `Vector`: `f(v...)` | length unknown, 64 B allocated per call | splat tuples or `SVector` (0 B), or pass the collection |
| `Function`, `Type`, `Vararg` arguments only passed through | not specialized: one `store(::Function, ::Float64)` instance for 3 functions | force with `g(f::F, x) where {F}`, `g(::Type{T}) where {T}`, `g(x::Vararg{Any,N}) where {N}` |
| `Vararg{T,N}` | specializes on count and types | keep `N` small (tuples of a few elements) |
| `@nospecialize(x)` | 1 MethodInstance instead of 41 for 40 argument types | use on compile-heavy, non-hot code: printing, logging, setup, type-generic utilities |
| `Base.@nospecializeinfer` (1.10+) on a `@nospecialize` method | inference also uses the declared types | further cuts compile time; calls inside become dynamic |
| `Base.@constprop :aggressive` | forces constant propagation through the method | for `Val`-from-literal APIs; costs compile time |

Callees of a `@nospecialize` function still see runtime types through dynamic dispatch, so
put the barrier between the despecialized wrapper and any hot kernel.

## 8. Codegen checks for hot kernels

```julia
@code_typed optimize=true kernel!(out, x)     # inlined IR; `invoke` = static call (good), a call typed ::Any = dynamic
@code_llvm debuginfo=:none kernel!(out, x)
@code_native debuginfo=:none kernel!(out, x)
```

| Pattern in output | Meaning |
|---|---|
| `<2 x double>` and `fmla` on `.2d` registers | vectorized on aarch64 NEON (seen on Apple M3, 1.13) |
| `<4 x double>` / `<8 x double>` and `vfmadd231pd` | vectorized on x86 AVX2 / AVX-512 |
| `call ... @ijl_apply_generic` | runtime dispatch (seen for the unstable loop) |
| `jl_get_binding...` / `get_binding_value` calls | non-const global read at runtime |
| `@ijl_gc_small_alloc`, `jl_alloc_genericmemory_unchecked` | heap allocation (array or box) |
| `call ... @j_throw_boundserror_<n>` in the loop (1.13 naming) | bounds checks kept; they block SIMD |

`@inline` small hot helpers, `@noinline` on error-reporting helpers so the hot path stays small.
`Base.@assume_effects` promises purity or termination to the compiler; a wrong promise is a
miscompilation, so use it only with a test that would catch it.

## 9. CI enforcement

```julia
using Test, JET, AllocCheck, MyPkg
@testset "type stability" begin
    out, x = zeros(100), rand(100)
    @inferred MyPkg.kernel!(out, x)
    MyPkg.kernel!(out, x)                                   # warm-up: compile before measuring
    @test (@allocated MyPkg.kernel!(out, x)) == 0           # zero-allocation budget
    @test isempty(check_allocs(MyPkg.kernel!, (Vector{Float64}, Vector{Float64})))
    if JET.JET_AVAILABLE
        @test_opt target_modules=(MyPkg,) MyPkg.kernel!(out, x)
        JET.test_package(MyPkg; target_modules=(MyPkg,))    # whole-package error analysis
    end
end
```

- Measure allocations only after a warm-up call; put the check inside a function or `@testset`
  so global-variable access cannot add allocations on older Julia versions.
- Budget, not just zero: `@test (@allocated f(x)) <= 1024` for kernels that legitimately
  allocate their output.
- JET results depend on the Julia version: run the JET job on 1.12/1.13 and skip elsewhere via
  `JET.JET_AVAILABLE`; run DispatchDoctor checks on 1.12 or 1.10 (inactive on 1.13).
- Since Pkg 1.13, `Pkg.test()` inherits `--check-bounds` from the parent process instead of
  forcing `yes`: run CI as `julia --check-bounds=yes --project -e 'using Pkg; Pkg.test()'`.
- Full templates (test environment, matrix, preferences): [ci-gates](references/ci-gates.md).

## 10. Worked example: unstable particle kernel to zero allocations

Before (globals `dt`, `g`; positions arrive as `Vector{Any}` from a parser):

```julia
dt = 0.01
g  = -9.81
function advance!(pos, vel, nsteps)
    for _ in 1:nsteps, i in eachindex(pos)
        vel[i] = vel[i] + g * dt
        pos[i] = pos[i] + vel[i] * dt
    end
    return pos
end
pos = Any[rand() for _ in 1:10_000]; vel = Any[0.0 for _ in 1:10_000]
```

Diagnose: `@code_warntype advance!(rand(4), zeros(4), 1)` prints `Body::Vector{Float64}` but
`%25 = Main.g::ANY`, `%26 = Main.dt::ANY`, `(%24)(%25, %26)::ANY` (full output in
[warntype-and-jet-output](references/warntype-and-jet-output.md)). Two causes: rows 1 and 3.

After:

```julia
const DT = 0.01
const G  = -9.81
function advance_kernel!(pos::AbstractVector{T}, vel::AbstractVector{T}, nsteps::Integer,
                         dt::T = T(DT), g::T = T(G)) where {T<:AbstractFloat}
    axes(pos) == axes(vel) || throw(DimensionMismatch("pos and vel differ"))
    for _ in 1:nsteps
        @inbounds @simd for i in eachindex(pos, vel)
            vel[i] += g * dt
            pos[i] += vel[i] * dt
        end
    end
    return pos
end
advance!(pos::Vector{Any}, vel::Vector{Any}, nsteps) =            # function barrier
    advance_kernel!(convert(Vector{Float64}, pos), convert(Vector{Float64}, vel), nsteps)
```

Measured on Julia 1.13.2, Apple M3 Ultra, N = 10,000 particles, 100 steps, minimum of repeated
runs after warm-up (`@elapsed`, `@allocated`, `@allocations`):

| Variant | Time | Allocated | Allocations |
|---|---|---|---|
| before, `Vector{Any}` input | 64.5 ms | 61.0 MiB | 4,000,000 |
| before code, `Vector{Float64}` input (globals still non-const) | 69.3 ms | 106.8 MiB | 7,000,000 |
| `advance_kernel!` on `Vector{Float64}` | 267.5 µs | 0 B | 0 |
| barrier from `Vector{Any}` (includes two converts) | 281.1 µs | 160.1 KiB | 6 |

Lessons: fixing the container alone made things worse (the `Any` results must be converted on
every store); the globals had to go too. A return-type check would not have caught the bug:
`Base.return_types` reports a concrete `Vector{Any}` (or `Vector{Float64}`) for the original
because it returns its argument, so read the body or run `@report_opt`.
`@inferred advance_kernel!(rand(3), zeros(3), 1)` passes and `Float32` inputs stay `Float32`.
Lock it in with the section 9 tests (`@test (@allocated advance_kernel!(p, v, 10)) == 0`).

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `@code_warntype` looks clean, code still slow | instability in a callee | `@report_opt` (follows callees) or `@trace_dispatch` |
| JET silent or erroring | JET version does not match the Julia minor | check `JET.JET_AVAILABLE`; use a temp env (`Pkg.activate(; temp=true)`) if Revise pins an incompatible JuliaInterpreter |
| `@stable` never fires | running Julia 1.13, Revise-reloaded code, or a closure | run the check on 1.12; restart without Revise |
| `@inferred` fails on a legitimate `Union{Nothing,T}` | strict equality with the inferred type | `@inferred Union{Nothing,T} f(x)` |
| zero-allocation test flaky | measured the compiling call, or a global in the expression | warm up first; measure inside a function |
| benchmark of the "fixed" code shows 0 ns | dead-code elimination or constant folding | interpolate inputs and keep results, see `julia-performance-allocations` |
| huge compile time after adding parameters | over-parameterized structs or `Val` on many values | drop parameters that do not affect hot code; `@nospecialize` cold paths |
| barrier "did not update" the caller's data | `convert` returned a copy | return and use the new array, or convert at construction |
| stable on 1.10, unstable on 1.12+ (or reverse) | inference heuristics change between minors | test the oldest and newest supported Julia in CI |

Related: `julia-performance-allocations`, `julia-sciml-diffeq`, `julia-packages-environments`, `julia-gpu`, `julia-optimization-jump`; hub `julia-craft`.
