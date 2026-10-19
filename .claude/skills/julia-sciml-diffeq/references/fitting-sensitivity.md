# Sensitivities, parameter fitting and neural ODEs

Versions as of October 2026: SciMLSensitivity 7.119, Optimization 5.9 (solvers in subpackages:
OptimizationOptimJL, OptimizationOptimisers, OptimizationLBFGSB, OptimizationPolyalgorithms),
DiffEqFlux 4.12, Lux 1.31. APIs below follow the current SciMLSensitivity, Optimization and
DiffEqFlux documentation.

## 1. Choosing how to differentiate through `solve`

| Situation | Method | Notes |
|---|---|---|
| fewer than ~100 parameters (plus states) | forward mode: `ForwardDiff.gradient` / `jacobian` through `solve` | SciMLSensitivity docs: `ForwardDiffSensitivity` is fastest below ~100 parameters; `sensealg` is ignored by ForwardDiff |
| forward mode but solver not AD-compatible | `sensealg = ForwardSensitivity()` | forward sensitivity equations |
| many parameters (neural ODEs, large models) | reverse mode (Zygote, Enzyme, Mooncake) with an adjoint `sensealg` | |
| default adjoint | `GaussAdjoint()` | the docs recommend it in general |
| memory-light alternatives | `InterpolatingAdjoint()` (optionally checkpointed), `QuadratureAdjoint()` | |
| `BacksolveAdjoint()` | solves the ODE backwards | cheapest memory; can be unstable for stiff or chaotic systems, verify against another method |
| vector-Jacobian products inside adjoints | `autojacvec = EnzymeVJP()` (fastest when it applies), `ReverseDiffVJP(true)` (compiled tape; next best), `ZygoteVJP()` | e.g. `GaussAdjoint(autojacvec = EnzymeVJP())` |

Without an explicit `sensealg`, SciMLSensitivity picks one with a polyalgorithm; set it
explicitly once performance matters.

## 2. Gradients through `solve`

```julia
using OrdinaryDiffEqTsit5, SciMLSensitivity, ForwardDiff, Zygote

function lv!(du, u, p, t)
    α, β, γ, δ = p
    du[1] = α * u[1] - β * u[1] * u[2]
    du[2] = -γ * u[2] + δ * u[1] * u[2]
    return nothing
end
prob = ODEProblem(lv!, [1.0, 1.0], (0.0, 10.0), [1.5, 1.0, 3.0, 1.0])

g(p) = sum(solve(remake(prob; p), Tsit5(); reltol = 1e-6, abstol = 1e-6, saveat = 0.1))
ForwardDiff.gradient(g, [1.5, 1.0, 3.0, 1.0])                 # forward mode

g_adj(p) = sum(solve(remake(prob; p), Tsit5(); reltol = 1e-6, abstol = 1e-6, saveat = 0.1,
                     sensealg = GaussAdjoint()))
Zygote.gradient(g_adj, [1.5, 1.0, 3.0, 1.0])                  # reverse mode via adjoint
```

The SciMLSensitivity getting-started page differentiates the same Lotka-Volterra sum (with
respect to `u0` and `p`) with Zygote's default sensitivity choice and with `GaussAdjoint()` at
`reltol = abstol = 1e-6`: the parameter gradients agree to 3-6 significant digits (`8.3042` vs
`8.3076`, `-159.4840` vs `-159.4846`). Differences of that size are tolerance-limited adjoint
error; tighten tolerances when gradients drive a sensitive fit.

## 3. Fitting parameters with Optimization.jl

```julia
using OrdinaryDiffEqTsit5, SciMLSensitivity, SciMLBase
using Optimization, OptimizationOptimJL, ForwardDiff

tdata = 0.0:0.5:10.0
p_true = [1.5, 1.0, 3.0, 1.0]
data = Array(solve(remake(prob; p = p_true), Tsit5(); saveat = tdata, reltol = 1e-10, abstol = 1e-10))

function loss(p, _)
    sol = solve(prob, Tsit5(); p, saveat = tdata, reltol = 1e-8, abstol = 1e-8)
    SciMLBase.successful_retcode(sol) || return Inf          # failed solves must not look good
    return sum(abs2, Array(sol) .- data)
end

optf = OptimizationFunction(loss, Optimization.AutoForwardDiff())   # 4 parameters: forward mode
optprob = OptimizationProblem(optf, [1.2, 0.8, 2.5, 0.8]; lb = fill(0.1, 4), ub = fill(5.0, 4))
res = solve(optprob, BFGS(); maxiters = 200)          # bounds handled for BFGS (box-constrained)
res.u, res.objective, res.retcode                     # SciMLBase v3: no sol.minimizer / sol.minimum
```

Checks before trusting `res.u`: `SciMLBase.successful_retcode(res)`; re-solve at `res.u` and
plot against data; restart from several initial guesses (multi-start) because ODE losses are
non-convex; compare the fitted parameters' sensitivity (Hessian or profile likelihood) before
reporting uncertainties.

Callback signature (Optimization v4+): `callback = (state, l) -> (println(l); false)`; return
`true` to stop. `state.u` holds the current parameters. Mini-batching moved into the problem
(pass a DataLoader as the second argument `p` of the objective) in Optimization v4.

Large models: switch to `Optimization.AutoZygote()` and an adjoint `sensealg`, start with
`OptimizationOptimisers.Adam(0.01)` for a few hundred iterations, then refine with `BFGS()`
starting from `remake(optprob; u0 = res_adam.u)`.

## 4. Neural ODE with Lux (DiffEqFlux)

```julia
using ComponentArrays, Lux, DiffEqFlux, OrdinaryDiffEqTsit5, Optimization,
      OptimizationOptimisers, OptimizationOptimJL, Random, Zygote

rng = Xoshiro(0)
u0 = Float32[2.0, 0.0]
tspan = (0.0f0, 1.5f0)
tsteps = range(tspan[1], tspan[2]; length = 30)
ode_data = ...                                        # 2×30 Float32 matrix of observations

model = Chain(x -> x .^ 3, Dense(2, 50, tanh), Dense(50, 2))
ps, st = Lux.setup(rng, model)                        # parameters and state are separate
node = NeuralODE(model, tspan, Tsit5(); saveat = tsteps)
predict(p) = Array(node(u0, p, st)[1])
loss(p) = sum(abs2, ode_data .- predict(p))

optf = OptimizationFunction((p, _) -> loss(p), Optimization.AutoZygote())
optprob = OptimizationProblem(optf, ComponentArray(ps))
res1 = solve(optprob, OptimizationOptimisers.Adam(0.05); maxiters = 300)
res2 = solve(remake(optprob; u0 = res1.u), BFGS(; initial_stepnorm = 0.01); allow_f_increases = false)
```

Keep everything `Float32` (data, `u0`, `tspan`); a single `Float64` literal promotes the whole
network. Lux keeps parameters explicit (`ps`) and state separate (`st`), which is what the ODE
solver and adjoints need; `ComponentArray(ps)` gives the optimizer a flat vector view.

## 5. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `MethodError` with `Dual` inside `f!` | a cache allocated as `zeros(n)` (Float64) captured by `f!` | allocate caches with `similar(u)` / `eltype(u)` inside, or use PreallocationTools `DiffCache` |
| gradient is `nothing` / zero | loss does not depend on `p` (e.g. `prob` captured with old `p`) | pass `p` to `solve` or `remake(prob; p)` inside the loss |
| fit "converges" to nonsense | failed solves returned a finite loss | return `Inf` when `!successful_retcode(sol)` |
| loss shapes mismatch | `saveat` differs from data times; `sol` indexing changed in v7 | `saveat = tdata`; compare `Array(sol)` to a matrix of data |
| adjoint gradient disagrees with ForwardDiff | tolerance-limited adjoint or `BacksolveAdjoint` instability | tighten `reltol`/`abstol`, use `GaussAdjoint` / `InterpolatingAdjoint` |
| very slow reverse mode | Zygote through mutation-heavy `f!` | `autojacvec = EnzymeVJP()` or `ReverseDiffVJP(true)` |
