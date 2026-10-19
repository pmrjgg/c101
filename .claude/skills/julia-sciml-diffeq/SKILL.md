---
name: julia-sciml-diffeq
description: "Solving differential equations in Julia with SciML (OrdinaryDiffEq v7, SciMLBase v3, ModelingToolkit v11): problem setup, solver selection by stiffness and tolerance, retcode checks, in-place vs SVector performance, sparse Jacobians, callbacks, ensembles, DAEs with ModelingToolkit, and sensitivities with parameter fitting. Load when simulating ODE, SDE, DAE or DDE models, or fitting model parameters in Julia."
when_to_use: "ODEProblem, SDEProblem, DDEProblem or DAEProblem code; retcodes MaxIters, DtLessThanMin, Unstable or InitialFailure; dt-below-dtmin warnings; stiff kinetics or PDE semi-discretizations; upgrade errors from OrdinaryDiffEq v6 (sol[i] semantics, autodiff=true, prob_func(prob, i, repeat), KenCarp4 not defined); ModelingToolkit mtkcompile or structural_simplify; ensemble Monte Carlo runs; parameter estimation, adjoints or neural ODEs."
---

# Julia SciML differential equations

Versions as of October 2026: OrdinaryDiffEq 7.8 (solver sublibraries 2.x), SciMLBase 3.58,
DifferentialEquations 8, ModelingToolkit 11.45, SciMLSensitivity 7.119, Optimization 5.9,
DiffEqCallbacks 4.19, DiffEqGPU 3.21, Sundials 6.7, DiffEqDevTools 3.6. v7 broke a lot of v6
code: check `Pkg.status(["OrdinaryDiffEq", "SciMLBase", "ModelingToolkit"])` before editing.

| v6 habit | v7 form |
|---|---|
| `sol[i]` is the i-th state, `length(sol)` the step count | `sol.u[i]` or `sol[:, i]`; `length(sol.t)` (`sol[i]` is now a scalar) |
| `sol.retcode == :Success` | `SciMLBase.successful_retcode(sol)` |
| `Rodas5P(autodiff = false)` | `Rodas5P(autodiff = AutoFiniteDiff())` (ADTypes objects only) |
| `solve(...; verbose = false, alias_u0 = true)` | `verbose = DEVerbosity(SciMLLogging.None())`, `alias = ODEAliasSpecifier(alias_u0 = true)` |
| `prob_func = (prob, i, repeat) -> ...` | `prob_func = (prob, ctx) -> ...` with `ctx.sim_id`, `ctx.rng` |
| `using OrdinaryDiffEq` then `KenCarp4()` | `using OrdinaryDiffEqSDIRK` (only a default set is exported) |
| inconsistent DAE `u0` silently repaired | `CheckInit()` default errors; opt in with `initializealg = BrownFullBasicInit()` |
| `u_modified!(integrator, false)`, `sol.destats` | `derivative_discontinuity!(integrator, false)`, `sol.stats` |

Deep material: [v6 to v7 migration](references/v7-migration.md) |
[ModelingToolkit and DAEs](references/mtk-dae.md) |
[sensitivities and fitting](references/fitting-sensitivity.md) |
[Robertson reference data](references/robertson-reference.md)

## 1. Load only what you need

`using DifferentialEquations` (v8) now loads only OrdinaryDiffEq. `using OrdinaryDiffEq` loads
the default set `DefaultODEAlgorithm, Tsit5, AutoTsit5, Vern6-9, AutoVern6-9, Rosenbrock23,
Rodas5P, FBDF`. Smallest load time: import only the sublibraries you call.

| Package | Solvers |
|---|---|
| `OrdinaryDiffEqTsit5` | `Tsit5`, `AutoTsit5` |
| `OrdinaryDiffEqVerner` | `Vern6`-`Vern9`, `AutoVern6`-`AutoVern9` |
| `OrdinaryDiffEqLowOrderRK` | `BS3`, `BS5`, `DP5`, `RK4`, `OwrenZen3/4/5` |
| `OrdinaryDiffEqRosenbrock` | `Rosenbrock23`, `Rodas5P`, `Rodas4P`, `Rodas6P`, `Rodas5` |
| `OrdinaryDiffEqBDF` | `FBDF`, `QNDF`, `DFBDF` (implicit DAE), `ABDF2` |
| `OrdinaryDiffEqSDIRK` | `KenCarp4`, `KenCarp47`, `Kvaerno5`, `TRBDF2`, `ImplicitEuler` |
| `OrdinaryDiffEqFIRK` | `RadauIIA5`, `RadauIIA9`, `AdaptiveRadau` |
| `OrdinaryDiffEqDefault` | `DefaultODEAlgorithm` (what `solve(prob)` uses) |
| `StochasticDiffEq` / `DelayDiffEq` / `Sundials` | SDE solvers / `MethodOfSteps` / `CVODE_BDF`, `IDA` |

Measure with `@time_imports using OrdinaryDiffEqTsit5` versus `using DifferentialEquations`.

## 2. Problem template and result checks

```julia
using OrdinaryDiffEqTsit5, SciMLBase       # SciMLBase as a direct dependency: Pkg.add("SciMLBase")

function lorenz!(du, u, p, t)
    σ, ρ, β = p
    du[1] = σ * (u[2] - u[1])
    du[2] = u[1] * (ρ - u[3]) - u[2]
    du[3] = u[1] * u[2] - β * u[3]
    return nothing
end
p = (σ = 10.0, ρ = 28.0, β = 8 / 3)                      # concrete NamedTuple, not Vector{Any}
prob = ODEProblem(lorenz!, [1.0, 0.0, 0.0], (0.0, 100.0), p)
sol = solve(prob, Tsit5(); reltol = 1e-8, abstol = 1e-8, saveat = 0.1)
SciMLBase.successful_retcode(sol) || error("solve failed: $(sol.retcode)")
```

- Read results with `sol.t`, `sol.u[i]`, `sol[:, i]`, `sol[j, :]` (component `j` over time),
  `Array(sol)`, `sol(t)` (interpolation: accurate only with dense output, i.e. no `saveat`),
  `sol.stats` (`nf`, `naccept`, `nreject`, `nw`, `nsolve`).
- Success codes: `Success`, `Terminated` (a callback called `terminate!`), `ExactSolutionLeft/Right`,
  `FloatingPointLimit`, `StalledSuccess`. Failures: `MaxIters`, `DtLessThanMin`, `Unstable`,
  `DtNaN`, `InitialFailure`, `ConvergenceFailure`, `MaxTime`, `Failure`.
- Defaults: `reltol = 1e-3`, `abstol = 1e-6` (ODE/DDE/DAE), `1e-2` for SDEs; `maxiters = 1e5`.
  The defaults are for plotting, not science: use `reltol` 1e-6..1e-10 and set `abstol` below
  the smallest magnitude you need to resolve in each component (a vector is allowed).
- Never "fix" `MaxIters` by raising `maxiters` before checking stiffness (section 4).

## 3. Solver selection

| Problem | Solver | Notes |
|---|---|---|
| non-stiff, `reltol` >= 1e-6 | `Tsit5()` | default explicit choice |
| non-stiff, 1e-8..1e-12 | `Vern7()`; `Vern9()` below 1e-12 or `BigFloat` | high order, lazy interpolants |
| non-stiff, loose tolerance, cheap `f` | `BS3()` | |
| unknown stiffness | `solve(prob)` (`DefaultODEAlgorithm`) or `AutoTsit5(Rosenbrock23())`, `AutoVern7(Rodas5P())` | stiffness detection and switching |
| stiff, <= 50 states | `Rosenbrock23()` (reltol >= 1e-6), `Rodas5P()` (tighter, or mass matrix) | the default algorithm uses these thresholds |
| stiff, 50-500 states | `FBDF()`, `QNDF()`, `KenCarp4()` / `KenCarp47()` | supply sparsity (section 5) |
| stiff, > 500 states (PDE semi-discretization) | `FBDF(linsolve = KrylovJL_GMRES())`, `KenCarp47(linsolve = KrylovJL_GMRES())`, Sundials `CVODE_BDF(linear_solver = :GMRES)` | Krylov plus preconditioner |
| stiff, `reltol` <= 1e-9 | `RadauIIA5()`, `Rodas5P()` | fully implicit high order |
| mass-matrix DAE `M u' = f(u)` | `Rodas5P()`, `FBDF()`, `RadauIIA5()` | `ODEFunction(f!; mass_matrix = M)` |
| fully implicit DAE `F(du, u, p, t) = 0` | `DFBDF()`, Sundials `IDA()` | `DAEProblem`, consistent `u0`/`du0` |
| SDE, diagonal noise | `SOSRI()` | `SDEProblem(f!, g!, u0, tspan, p)` |
| SDE, additive / stiff additive | `SOSRA()` / `SKenCarp()` | |
| SDE, non-diagonal noise | `LambaEM()` (adaptive), `EM()` (fixed, needs `dt`) | `noise_rate_prototype` |
| delay DE | `MethodOfSteps(Tsit5())`; stiff `MethodOfSteps(Rosenbrock23())` / `MethodOfSteps(Rodas4())` | `DDEProblem(f!, u0, h, tspan, p; constant_lags)` |

The SciML default itself encodes the size rules: non-stiff `Tsit5`, or `Vern7` when
`reltol < 1e-6`; stiff `Rosenbrock23` (or `Rodas5P` for `reltol < 1e-6` or a mass matrix) up
to 50 states, `FBDF` up to 500, Krylov `FBDF` above.

## 4. Stiffness diagnosis and tolerance choice

Symptoms: `dt` collapses (`sol.t` steps far below the time scale of the solution),
`MaxIters`, `DtLessThanMin` or `Unstable` retcodes, `nreject` comparable to `naccept`, run time that
explodes as tolerances tighten while accuracy does not improve. Confirm with eigenvalues:

```julia
using ForwardDiff, LinearAlgebra
J = ForwardDiff.jacobian(u -> (du = similar(u); f!(du, u, p, t); du), u)   # at a state of interest
λ = sort(real.(eigvals(J)))   # skip ~0 eigenvalues from conservation laws; ratio = |λ[1]| / |slowest nonzero|
```

Explicit methods need `h·|λmax| ≲ 3` (Dormand-Prince 5: about 3.3). If that `h` is far smaller
than accuracy requires, switch to a stiff solver. Robertson at t = 1e5 has `λmax ≈ -9826` and a
stiffness ratio near 5e8 (section 10).

Choose tolerances with a work-precision diagram against a tight reference:

```julia
using DiffEqDevTools, Plots
ref = solve(prob, Rodas5P(); reltol = 1e-14, abstol = 1e-14)     # or RadauIIA5 / Sundials
abstols = 1.0 ./ 10.0 .^ (6:10); reltols = 1.0 ./ 10.0 .^ (3:7)
setups = [Dict(:alg => Rodas5P()), Dict(:alg => FBDF()), Dict(:alg => KenCarp4())]
wp = WorkPrecisionSet(prob, abstols, reltols, setups; appxsol = ref, save_everystep = false,
                      numruns = 10, maxiters = Int(1e5))           # error_estimate = :final default
plot(wp)
```

Pick the fastest solver at the error you need; `error_estimate = :l2` measures the whole time
series (needs saved points). The SciMLBenchmarks ROBER study found `Rosenbrock23` and `lsoda`
fast at loose tolerances, `Rodas4`/`Rodas5` very fast at normal tolerances, and `radau`
competitive below `reltol = 1e-9`. Quick check without a diagram: solve at `reltol` and
`reltol/10`; if the quantities you report move more than you can accept, tighten.

## 5. Performance

- Small systems (up to ~20 states): out-of-place with `SVector`, zero allocations per step:

```julia
using StaticArrays
lorenz(u, p, t) = SA[p.σ * (u[2] - u[1]), u[1] * (p.ρ - u[3]) - u[2], u[1] * u[2] - p.β * u[3]]
prob_s = ODEProblem(lorenz, SA[1.0, 0.0, 0.0], (0.0, 100.0), p)
```

- Larger systems: in-place `f!(du, u, p, t)`, no allocations inside (`@allocated f!(du, u, p, 0.0) == 0`
  after a warm-up; see `julia-performance-allocations`), concrete `p` (NamedTuple, tuple,
  struct, ComponentArray), never `Vector{Any}`.
- Output: `saveat = tgrid`, `save_everystep = false`, `save_idxs = [1, 3]`; dense output stores
  all stages and costs memory.
- v7 wraps `f` with `AutoSpecialize` (better compile caching). For a hot benchmark use
  `ODEFunction{true, SciMLBase.FullSpecialize}(f!)`.
- AD for Jacobians: `Rodas5P(autodiff = AutoForwardDiff(chunksize = 8))`, `AutoFiniteDiff()`,
  `AutoEnzyme()`; analytic Jacobians via `ODEFunction(f!; jac = jac!)`.
- Sparse Jacobians (SparseConnectivityTracer detects, SparseMatrixColorings colours):

```julia
import SparseConnectivityTracer, ADTypes
detector = SparseConnectivityTracer.TracerSparsityDetector()
du0 = similar(u0)
S = ADTypes.jacobian_sparsity((du, u) -> f!(du, u, p, 0.0), du0, u0, detector)
fs = ODEFunction(f!; jac_prototype = float.(S))
sol = solve(ODEProblem(fs, u0, tspan, p), FBDF(); save_everystep = false)
```

  With `jac_prototype` set, OrdinaryDiffEq wraps the AD backend in
  `AutoSparse(...; sparsity_detector = KnownJacobianSparsityDetector(S), coloring_algorithm = GreedyColoringAlgorithm())`.
  Equivalent explicit form: `FBDF(autodiff = AutoSparse(AutoForwardDiff(); sparsity_detector = TracerSparsityDetector(), coloring_algorithm = GreedyColoringAlgorithm()))`.
  Sparse AD is switched off (with a warning) for `StaticArray` or complex `u0`.
- Linear solvers: `KenCarp47(linsolve = KrylovJL_GMRES())` (LinearSolve), preconditioners via
  `KrylovJL_GMRES(precs = myprecs)` with `concrete_jac = true`. DiffEqDocs' 32×32 Brusselator
  (2048 unknowns): dense `TRBDF2` 8.5 s, sparse `TRBDF2` 288 ms, sparse `KenCarp47` + GMRES +
  incomplete-LU 254 ms; Sundials `CVODE_BDF` 15.3 s by default vs 196 ms with `:GMRES`.

## 6. Callbacks

```julia
using DiffEqCallbacks                                   # PresetTimeCallback and friends
# patterns for a model with u = [height, velocity, amount] and p = (k = Ref(1.0), ...)
hit_ground = ContinuousCallback((u, t, i) -> u[1],      # root of u[1] = 0, located by interpolation
                                i -> (i.u[2] = -0.9 * i.u[2]))
stop = ContinuousCallback((u, t, i) -> u[3] - 10.0, terminate!)   # retcode Terminated
dose = PresetTimeCallback([24.0, 48.0, 72.0], i -> (i.u[3] += 100.0))   # adds tstops itself
check = DiscreteCallback((u, t, i) -> t == 12.0, i -> (i.p.k[] *= 2); save_positions = (true, true))
sol = solve(model_prob, Tsit5(); callback = CallbackSet(hit_ground, stop, dose, check), tstops = [12.0])
```

- A `DiscreteCallback` that tests `t == t_event` fires only if the solver steps exactly there:
  pass `tstops`, or use `PresetTimeCallback` (dosing schedules) / `PeriodicCallback`.
- After an affect changes `u` or parameters, keep the default restart (the derivative jumps).
  Only when an affect changes nothing `f` depends on (logging, bookkeeping) call
  `derivative_discontinuity!(i, false)` (v6 name `u_modified!`) to skip it. Mutate parameters
  through a mutable container (here `k = Ref(...)` inside a NamedTuple `p`).
- `VectorContinuousCallback(condition!, affect!, len)`: v7 calls `affect!(i, events)` once per step
  with `events::Vector{Int8}` (`0` none, `+1` upcrossing, `-1` downcrossing), handling
  simultaneous events.
- Other callback library entries: `SavingCallback`, `TerminateSteadyState`, `ManifoldProjection`,
  `PositiveDomain`, `GeneralDomain`, `PeriodicCallback`.

## 7. Ensembles

```julia
u0s = [rand(3) for _ in 1:1000]
eprob = EnsembleProblem(prob;
    prob_func = (prob, ctx) -> remake(prob; u0 = u0s[ctx.sim_id]),        # v7 signature
    output_func = (sol, ctx) -> (sol.u[end], false))                      # (output, rerun?)
sim = solve(eprob, Tsit5(), EnsembleThreads(); trajectories = 1000, seed = 42, saveat = 1.0)
finals = sim.u                                                            # v7: sim.u[j], not sim[j]
```

- Randomness per trajectory: draw from `ctx.rng` and pass `seed` (or `rng`) to `solve`; results
  are then independent of the thread count.
- `EnsembleSerial()`, `EnsembleThreads()` (default), `EnsembleDistributed()` (`pmap`; load code
  with `@everywhere`), `EnsembleSplitThreads()`.
- GPU (DiffEqGPU): prefer `EnsembleGPUKernel(CUDA.CUDABackend())` with GPU solvers such as
  `GPUTsit5()` on out-of-place `SVector`, `Float32` problems (fewer kernel launches, lower
  overhead); fall back to `EnsembleGPUArray(CUDA.CUDABackend())` when the method you need has no
  kernel version or the problem cannot be written out-of-place. See `julia-gpu`.
- `safetycopy` (default true for a user `prob_func`) deep-copies `prob`; keep it when `prob_func`
  mutates shared state. Summaries: `EnsembleSummary(sim; quantiles = [0.05, 0.95])`.

## 8. ModelingToolkit (acausal models, DAEs, initialization)

- v10 renamed `structural_simplify` to `mtkcompile` and `@mtkbuild` to `@mtkcompile`, unified
  `ODESystem`/`NonlinearSystem` into `System`, and changed problems to `ODEProblem(sys, op, tspan)`
  (one map for unknowns and parameters). v11 replaced `defaults` with `initial_conditions` and
  `bindings`, deprecated `@mtkmodel` (moved to SciCompDSL.jl) and split the package:
  ModelingToolkitBase's `mtkcompile` does no index reduction; full index reduction and tearing
  live in AGPL-licensed StateSelection.jl / ModelingToolkitTearing used by ModelingToolkit.
- High-index DAE (pendulum, from the MTK docs):

```julia
using ModelingToolkit, OrdinaryDiffEq
using ModelingToolkit: t_nounits as t, D_nounits as D
@parameters g
@variables x(t) y(t) [state_priority = 10] λ(t)
eqs = [D(D(x)) ~ λ * x, D(D(y)) ~ λ * y - g, x^2 + y^2 ~ 1]
@mtkcompile pend = System(eqs, t)                     # index reduction, tearing, alias removal
prob = ODEProblem(pend, [x => 1, y => 0, g => 1], (0.0, 1.5), guesses = [λ => 1])
sol = solve(prob, Rodas5P())
```

- `guesses` seed the initialization solve; `initialization_eqs` add conditions at `t0`;
  unsatisfiable initialization returns `ReturnCode.InitialFailure`.
- Acausal components are plain functions returning `System`s joined with `connect(...)`; numeric
  mass-matrix code can be traced with `modelingtoolkitize` and index-reduced with
  `mtkcompile(dae_index_lowering(sys))`. Recipes: [mtk-dae](references/mtk-dae.md).

## 9. Sensitivities and parameter fitting

- Fewer than ~100 parameters: ForwardDiff straight through `solve`
  (`ForwardDiff.gradient(p -> loss(p), p0)`); `sensealg` is ignored in forward mode.
- Many parameters: reverse mode (Zygote) with SciMLSensitivity adjoints: `GaussAdjoint()`
  (recommended default), `InterpolatingAdjoint()`, `QuadratureAdjoint()`; `BacksolveAdjoint()`
  only after checking stability. Vector-Jacobian products: `autojacvec = EnzymeVJP()` first,
  `ReverseDiffVJP(true)` next.
- Fit with Optimization.jl over a loss that calls `solve` and returns `Inf` on failure:

```julia
using Optimization, OptimizationOptimJL, SciMLSensitivity, ForwardDiff
# prob, tdata (save times), data (states × times matrix), θ0 (initial guess) defined beforehand
function loss(θ, _)
    sol = solve(prob, Tsit5(); p = θ, saveat = tdata, reltol = 1e-8, abstol = 1e-8)
    SciMLBase.successful_retcode(sol) || return Inf
    return sum(abs2, Array(sol) .- data)
end
optprob = OptimizationProblem(OptimizationFunction(loss, Optimization.AutoForwardDiff()), θ0;
                              lb = fill(0.1, length(θ0)), ub = fill(5.0, length(θ0)))
res = solve(optprob, BFGS(); maxiters = 200)          # res.u, res.objective, res.retcode
```

- Neural ODEs: Lux model + DiffEqFlux `NeuralODE(model, tspan, Tsit5(); saveat)`, parameters as
  `ComponentArray`, `Optimization.AutoZygote()`, Adam then BFGS, everything `Float32`. Full code
  and pitfalls: [fitting-sensitivity](references/fitting-sensitivity.md).

## 10. Worked example: Robertson stiff kinetics

```julia
using OrdinaryDiffEqTsit5, OrdinaryDiffEqRosenbrock, OrdinaryDiffEqBDF, SciMLBase

function rober!(du, u, p, t)
    k1, k2, k3 = p
    y1, y2, y3 = u
    du[1] = -k1 * y1 + k3 * y2 * y3
    du[2] =  k1 * y1 - k2 * y2^2 - k3 * y2 * y3
    du[3] =  k2 * y2^2
    return nothing
end
prob = ODEProblem(rober!, [1.0, 0.0, 0.0], (0.0, 1e5), (0.04, 3e7, 1e4))

sol_e = solve(prob, Tsit5())                  # explicit: expect sol_e.retcode == ReturnCode.MaxIters
```

Why Tsit5 fails (numbers from the plain-Julia reference in
[robertson-reference](references/robertson-reference.md)): the fast Jacobian eigenvalue grows
from -1750 (t = 1e-3) to -9826 (t = 1e5) while the slow one decays to -1.8e-5, a stiffness ratio
near 5e8. An explicit 5th-order pair is stable only for `h·|λ| ≲ 3.3`, so `h` stays between
about 3e-4 and 2e-3 for the whole run: covering t = 1e5 would take on the order of 3e8 steps
against the default `maxiters = 1e5`. A Dormand-Prince 5(4) loop of the same class as Tsit5 stalled at
t = 72.5 after 100,000 iterations with `h·|λ| = 3.2`, and even on [0, 40] it lost accuracy
(`y1` relative error 1.6e-4 at `rtol = 1e-6`).

Tolerances: `y2` peaks at 3.65e-5 (t ≈ 5e-3) and ends at 7.3e-8, so the default
`abstol = 1e-6` cannot resolve it. Use a per-component `abstol`:

```julia
ref = [1.78659211420993e-2, 7.27475146843626e-8, 9.82134006110384e-1]   # t = 1e5, reference data
abstol = [1e-10, 1e-14, 1e-10]
for alg in (Rodas5P(), FBDF())
    sol = solve(prob, alg; reltol = 1e-8, abstol)
    SciMLBase.successful_retcode(sol) || error("$alg: $(sol.retcode)")
    relerr = maximum(abs.(sol.u[end] .- ref) ./ abs.(ref))
    println(nameof(typeof(alg)), ": rel err ", relerr, ", accepted steps ", sol.stats.naccept,
            ", f evals ", sol.stats.nf, ", sum-1 = ", sum(sol.u[end]) - 1)
end
```

Acceptance: both retcodes successful; `relerr` within a small multiple of `reltol` (if it is
more than ~100× `reltol`, tighten tolerances and compare again); `sum(sol.u[end]) - 1` at the
level of roundoff or the nonlinear-solver tolerance (the linear invariant must survive);
`naccept` orders of magnitude below the 1e5 iterations Tsit5 burned. Then compare the two
stiff solvers at your accuracy target with section 4's work-precision set (SciMLBenchmarks' ROBER study: Rosenbrock methods are fastest at normal
tolerances, Radau below 1e-9). The reference values come from an independent order-5
Radau IIA integration whose two grid refinements agree to 3e-15 and whose t = 40 state matches
the classical ROBER values (y1 ≈ 0.715827, y2 ≈ 9.1855e-6). In-package tight reference, as in
SciMLBenchmarks: `solve(prob, Rodas5P(); abstol = 1e-14, reltol = 1e-14)` (or Sundials
`CVODE_BDF()`); it should reproduce the table to many digits before it serves as `appxsol`.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `UndefVarError: KenCarp4` (or `RadauIIA5`, `QNDF`, `BS3`) | v7 exports only the default set | `using OrdinaryDiffEqSDIRK` / `...FIRK` / `...BDF` / `...LowOrderRK` |
| SDE/DDE solvers missing after `using DifferentialEquations` | DiffEq v8 loads only ODEs | `using StochasticDiffEq`, `using DelayDiffEq` |
| `sol[2]` returns a number | RecursiveArrayTools v4 | `sol.u[2]` |
| `MaxIters` with an explicit solver | stiffness | stiff solver; do not raise `maxiters` |
| tiny component wrong or negative | `abstol` larger than the component | per-component `abstol`; `isoutofdomain` or `PositiveDomain` for positivity |
| DAE solve throws at start | v7 `CheckInit` on inconsistent `u0` | consistent initial values or `initializealg = BrownFullBasicInit()` |
| event at a fixed time never fires | `DiscreteCallback` time not in `tstops` | `tstops = [t_event]` or `PresetTimeCallback` |
| ensemble results change with thread count | global RNG inside `prob_func` | `ctx.rng` plus `seed` |
| `EM()` errors | fixed-step method without `dt` | `solve(prob, EM(); dt = 1e-3)` |
| allocations in every step | out-of-place `Vector` code or non-concrete `p` | in-place `f!` or `SVector`; concrete `p` |
| `Dual` `MethodError` inside `f!` during stiff solves or ForwardDiff | `Float64` cache captured in `f!` | allocate from `eltype(u)` or use PreallocationTools `DiffCache` |
| `structural_simplify` / `@mtkbuild` undefined | ModelingToolkit v10+ | `mtkcompile` / `@mtkcompile` |

Related: `julia-performance-allocations`, `julia-type-stability`, `julia-gpu`, `julia-optimization-jump`, `julia-packages-environments`; hub `julia-craft`.
