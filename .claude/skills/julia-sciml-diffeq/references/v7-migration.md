# OrdinaryDiffEq v6 to v7 (SciMLBase v3, RecursiveArrayTools v4, DifferentialEquations v8)

Source: the OrdinaryDiffEq.jl `NEWS.md` for the v7 release (OrdinaryDiffEq 7.8.1, SciMLBase 3.58
as of October 2026). Check what is installed before editing code:

```bash
julia --project -e 'using Pkg; Pkg.status(["OrdinaryDiffEq", "SciMLBase", "DifferentialEquations", "ModelingToolkit"])'
```

Recommended path (from the release notes): stay on v6, switch every call site to the new names
(they exist on v6 with deprecation warnings), get the tests warning-free, then bump to v7. On v7
only the genuinely new breakage remains (array semantics, ensemble signatures, removed kwargs,
new defaults).

## 1. Package scope

| v6 | v7 / DiffEq v8 |
|---|---|
| `using DifferentialEquations` loaded ODE, SDE, DDE, BVP, jumps, Sundials, steady state, LinearSolve, NonlinearSolve, Optimization | loads only `OrdinaryDiffEq`; add `StochasticDiffEq`, `DelayDiffEq`, `BoundaryValueDiffEq`, `JumpProcesses`, `SteadyStateDiffEq`, `Sundials`, `LinearSolve`, `NonlinearSolve`, `Optimization` explicitly |
| `using OrdinaryDiffEq` exported every solver | exports only `DefaultODEAlgorithm`, `Tsit5`, `AutoTsit5`, `Vern6`-`Vern9`, `AutoVern6`-`AutoVern9`, `Rosenbrock23`, `Rodas5P`, `FBDF`; everything else needs its sublibrary (`KenCarp4` and `TRBDF2` in `OrdinaryDiffEqSDIRK`, `RadauIIA5` in `OrdinaryDiffEqFIRK`, other Rosenbrock/Rodas in `OrdinaryDiffEqRosenbrock`, `BS3`/`DP5` in `OrdinaryDiffEqLowOrderRK`, `QNDF`/`DFBDF` in `OrdinaryDiffEqBDF`) |
| `StochasticDelayDiffEq` | deprecated, use `DelayDiffEq` (+ `StochasticDiffEq`) |
| `Rodas5` | still available; the notes strongly recommend `Rodas5P` |

## 2. Solutions are AbstractArrays (RecursiveArrayTools v4)

| Operation | v6 meaning | v7 meaning | Write instead (works on both) |
|---|---|---|---|
| `sol[i]` | i-th saved state | i-th scalar (column-major) | `sol.u[i]` or `sol[:, i]` |
| `length(sol)` | number of time points | total number of scalars | `length(sol.t)` |
| `eachindex(sol)` | `1:nsteps` | `CartesianIndices` | `eachindex(sol.u)` |
| `for u in sol` | iterate states | iterate scalars | `for u in sol.u` |
| `first(sol)`, `last(sol)` | first/last state | first/last scalar | `first(sol.u)`, `last(sol.u)` |
| `map(f, sol)`, `maximum(sol)` | over states | over scalars | `map(f, sol.u)`, `maximum(f, sol.u)` |
| `sim[j]` (ensemble) | j-th trajectory | scalar | `sim.u[j]` |
| `sim[i, j]` | state i of trajectory j | scalar | `sim.u[j].u[i]` |
| `length(sim)` | trajectories | scalars | `length(sim.u)` |

Unchanged and safe: `sol.t`, `sol.u`, `sol(t)`, `sol[j, :]` (component `j` over time),
`Array(sol)`. Escape hatch: `RaggedVectorOfArray(sol)` from `RecursiveArrayToolsRaggedArrays`
restores v3 indexing per solution.

## 3. Typed options instead of Bool

| v6 | v7 |
|---|---|
| `Rosenbrock23(autodiff = true)` / `false` | `Rosenbrock23(autodiff = AutoForwardDiff())` / `AutoFiniteDiff()` (also `AutoEnzyme()`, `AutoZygote()`, `AutoMooncake()`) |
| `chunk_size = 8` | `autodiff = AutoForwardDiff(chunksize = 8)` |
| `diff_type = Val{:central}` | `autodiff = AutoFiniteDiff(fdtype = Val(:central))` |
| `standardtag = ...` | removed (always on) |
| `precs = ...` on the algorithm | preconditioners go into `linsolve` (LinearSolve `Pl`/`Pr` or `precs` of the Krylov solver) |
| `solve(...; verbose = false)` | `verbose = DEVerbosity(SciMLLogging.None())` |
| `alias = true`, `alias_u0 = true` | `alias = ODEAliasSpecifier(alias_u0 = true)` (SDE: `SDEAliasSpecifier`) |
| `Vern7(lazy = false)` | `Vern7(lazy = Val{false}())` |
| `solve(...; gamma, beta1, beta2, qmin, qmax, qsteady_min, qsteady_max, qoldinit)` | `controller = PIController(...)` / `PIDController(...)` / `IController(...)` |
| `integrator.EEst` | `OrdinaryDiffEqCore.get_EEst(integrator)` / `set_EEst!` |
| threading `OrdinaryDiffEq.True()` / `False()` | `FastBroadcast.Threaded()` / `Serial()` (`thread` kwarg); `threading` takes `OrdinaryDiffEq.PolyesterThreads()` (qualified, 7.5+) |

## 4. Renamed or removed API (SciMLBase v3)

| Old | New |
|---|---|
| `sol.retcode == :Success` | `SciMLBase.successful_retcode(sol)`; specific codes as `ReturnCode.MaxIters` |
| `u_modified!(integrator, false)` | `derivative_discontinuity!(integrator, false)` |
| `integrator.u_modified` | `integrator.derivative_discontinuity` |
| `sol.destats`, `has_destats` | `sol.stats`, `has_stats` |
| `DEAlgorithm`, `DEProblem`, `DESolution` | `AbstractDEAlgorithm`, `AbstractSciMLProblem`, `AbstractSciMLSolution` |
| `syms`, `paramsyms`, `indepsym` kwargs | the problem's `sys` / ModelingToolkit symbolic interface |
| optimization `sol.minimizer`, `sol.minimum`, `sol.x` | `sol.u`, `sol.objective` |
| `tuples(sol)`, `intervals(sol)` | iterate `sol.t` / `sol.u` |
| `EnsembleProblem([prob1, prob2, ...])` | a `prob_func` |
| `constructDormandPrince()` tableau constructors | `OrdinaryDiffEqExplicitTableaus.DormandPrince()` (DiffEqDevTools v3 no longer re-exports them) |
| positional `Alg(stage_limiter!, step_limiter!)` | `Alg(; stage_limiter! = ..., step_limiter! = ...)` |

## 5. Behaviour changes

- Ensembles: `prob_func(prob, i, repeat)` became `prob_func(prob, ctx)` and
  `output_func(sol, i)` became `output_func(sol, ctx)`. `ctx::EnsembleContext` has `sim_id`
  (trajectory index), `repeat`, `worker_id`, `sim_seed`, `rng`, `master_rng`. Pass `seed = 42`
  (or `rng`) to `solve` for results independent of thread count; draw randomness from `ctx.rng`.
- DAE initialization default is `CheckInit()`: inconsistent `u0`/`du0` now throws instead of
  being silently repaired. Opt back in with `initializealg = BrownFullBasicInit()`.
- `VectorContinuousCallback` calls `affect!(integrator, events::Vector{Int8})` once per step
  with every simultaneous event (`0` none, `+1` upcrossing, `-1` downcrossing); `affect_neg!`
  is no longer used for it. `ContinuousCallback` is unchanged.
- `ODEFunction{iip}(f)` defaults to `AutoSpecialize` (better precompilation reuse); for maximum
  inlining in benchmarks write `ODEFunction{true, SciMLBase.FullSpecialize}(f)`.
- Low-storage 2N methods default to `williamson_condition = false` (safe for StaticArrays, GPU
  arrays, ComponentArrays).
- `d_discontinuities` land one ULP past the discontinuity and refresh FSAL data there; `tstops`
  only force a step.

## 6. Search patterns for an upgrade

```bash
grep -rnE 'sol\[[a-z0-9_]+\]|length\(sol\)|retcode == :|autodiff *= *(true|false)|verbose *= *(true|false)' src test
grep -rnE 'alias_u0|u_modified!|destats|prob_func *= *\(prob, *i|\(prob, *i, *repeat\)|chunk_size|structural_simplify|@mtkbuild' src test
```

Each hit maps to a row above (`structural_simplify` / `@mtkbuild` are the ModelingToolkit v10
renames to `mtkcompile` / `@mtkcompile`).
