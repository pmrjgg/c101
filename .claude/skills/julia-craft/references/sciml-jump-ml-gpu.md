# Julia recipes: DifferentialEquations.jl, JuMP, Flux, Lux, CUDA.jl

Versions move quickly in these ecosystems; check the docs (context7 or the package site) for
the installed major version before relying on keyword names.

## 1. DifferentialEquations.jl / OrdinaryDiffEq.jl

Load only what you need (`using OrdinaryDiffEq` loads far less than `DifferentialEquations`;
recent versions also split solvers into sublibraries such as `OrdinaryDiffEqTsit5`).

```julia
using OrdinaryDiffEq

function lorenz!(du, u, p, t)
    σ, ρ, β = p
    du[1] = σ * (u[2] - u[1])
    du[2] = u[1] * (ρ - u[3]) - u[2]
    du[3] = u[1] * u[2] - β * u[3]
    return nothing
end

prob = ODEProblem(lorenz!, [1.0, 0.0, 0.0], (0.0, 100.0), (10.0, 28.0, 8 / 3))
sol  = solve(prob, Tsit5(); reltol=1e-8, abstol=1e-8, saveat=0.1)
SciMLBase.successful_retcode(sol) || error("solve failed: $(sol.retcode)")
```

Solver selection:

| Problem | Solver | Notes |
|---|---|---|
| non-stiff, default tolerances | `Tsit5()` | first choice |
| non-stiff, tight tolerances (< 1e-8) | `Vern7()`, `Vern9()` | high order |
| non-stiff, loose tolerances, cheap f | `BS3()` | |
| stiff, small system (< ~50 states) | `Rodas5P()`, `Rosenbrock23()` | Rosenbrock methods, need Jacobians (AD by default) |
| stiff, medium/large | `FBDF()`, `QNDF()`, `KenCarp4()` (IMEX) | provide sparsity (`jac_prototype`) for large systems |
| stiff, very large (PDE semi-discretization) | `FBDF()` / Sundials `CVODE_BDF(linear_solver=:GMRES)` | Krylov linear solvers |
| unknown stiffness | default `solve(prob)` (automatic choice) or `AutoTsit5(Rosenbrock23())` | switching |
| DAE in mass-matrix form | `Rodas5P()`, `FBDF()` | `ODEFunction(f; mass_matrix=M)` |
| fully implicit DAE | `DFBDF()`, Sundials `IDA()` | consistent initial conditions matter |
| SDE | `SOSRI()` (diagonal noise), `EM()` (fixed step) | `SDEProblem(f, g, u0, tspan, p)` |
| delay DE | `MethodOfSteps(Tsit5())` | `DDEProblem` |

Stiffness symptoms: tiny `dt`, `retcode` `MaxIters`/`Unstable`, warnings about dt below
`dtmin`, runtime exploding as tolerances tighten. Switch to a stiff solver rather than raising
`maxiters`.

Performance rules:
- In-place `f!(du, u, p, t)` for systems larger than ~20 states; out-of-place with `SVector`
  (`f(u, p, t) = SA[...]`) for small systems: zero allocations.
- `p` should be a concrete type (NamedTuple, tuple, struct), not a `Vector{Any}`.
- `saveat` / `save_everystep=false` reduce memory; dense output (`sol(t)`) costs storage.
- Ensembles: `EnsembleProblem(prob; prob_func=(prob, i, repeat) -> remake(prob; u0=u0s[i]))`
  then `solve(eprob, Tsit5(), EnsembleThreads(); trajectories=1000)`; `EnsembleGPUArray`
  (DiffEqGPU.jl) for many small systems.
- Events: `ContinuousCallback(condition, affect!)` with `terminate!(integrator)` for stopping.
- Sensitivities: ForwardDiff through `solve` for few parameters (< ~100); SciMLSensitivity
  adjoints (`InterpolatingAdjoint`, `GaussAdjoint`) for many parameters or neural ODEs.
- Symbolic modelling and index reduction for DAEs: ModelingToolkit.jl.

## 2. JuMP

```julia
using JuMP, HiGHS

function facility_location(c, f, d, C)          # c[i,j] cost, f[j] fixed, d[i] demand, C[j] capacity
    n, m = size(c)
    model = Model(HiGHS.Optimizer)
    set_silent(model)
    set_time_limit_sec(model, 60.0)
    @variable(model, x[1:n, 1:m] >= 0)
    @variable(model, y[1:m], Bin)
    @constraint(model, demand[i=1:n], sum(x[i, j] for j in 1:m) == d[i])
    @constraint(model, cap[j=1:m], sum(x[i, j] for i in 1:n) <= C[j] * y[j])
    @objective(model, Min, sum(c .* x) + sum(f .* y))
    optimize!(model)
    # assert_is_solved_and_feasible would throw on TIME_LIMIT even with a good incumbent: branch instead
    st = termination_status(model)
    if !(st == OPTIMAL || (st == TIME_LIMIT && primal_status(model) == FEASIBLE_POINT))
        error("facility_location: $(st), primal status $(primal_status(model))")
    end
    st == TIME_LIMIT && @warn "time limit hit; returning the best incumbent" relative_gap(model)
    return value.(x), value.(y), objective_value(model)
end
```

Solver choice:

| Problem class | Open-source | Commercial |
|---|---|---|
| LP, MILP | HiGHS | Gurobi, CPLEX, Xpress |
| convex QP / SOCP / conic | Clarabel, SCS, COSMO | MOSEK, Gurobi |
| smooth NLP (local) | Ipopt | KNITRO |
| MINLP | Juniper, SCIP (via SCIP.jl) | Gurobi (nonconvex quadratic), BARON |
| SDP | Clarabel, SCS | MOSEK |

Rules:
- Always check status before reading values: `termination_status(model)`,
  `primal_status(model)`, or `is_solved_and_feasible(model)`. A time-limited MIP may return
  `TIME_LIMIT` with a feasible solution (`primal_status == FEASIBLE_POINT`) and a gap
  (`relative_gap(model)`).
- `solution_summary(model)` for a one-shot readable status report.
- Nonlinear expressions go directly into `@objective`/`@constraint` (JuMP 1.15+); the legacy
  `@NLobjective`/`@NLconstraint` macros are superseded.
- Big-M constraints: choose the smallest valid M from data; huge M values cause numerical
  trouble and weak relaxations. Indicator constraints (`y --> {x <= 0}`) when the solver supports them.
- Build large expressions with `sum` over generators or `add_to_expression!`, not repeated `+`
  in a loop (quadratic time).
- Duals: `dual(con)` / `shadow_price(con)` for LP; for MIP fix the integers
  (`fix_discrete_variables(model)`) and re-solve the LP.
- Performance of model construction: `direct_model(HiGHS.Optimizer())` skips the cache layer;
  `@constraint(model, ...)` in loops over sparse index sets uses `SparseAxisArray` containers.
- Solver attributes: `set_attribute(model, "mip_rel_gap", 1e-4)`; names are solver-specific.

## 3. Flux (implicit-free, explicit-gradient style)

```julia
using Flux
model = Chain(Dense(784 => 256, relu), Dropout(0.1), Dense(256 => 10))
opt_state = Flux.setup(Adam(1f-3), model)
for epoch in 1:10
    Flux.trainmode!(model)
    for (x, y) in train_loader                       # Flux.DataLoader((X, Y); batchsize=128, shuffle=true)
        loss, grads = Flux.withgradient(m -> Flux.logitcrossentropy(m(x), y), model)
        Flux.update!(opt_state, model, grads[1])
    end
    Flux.testmode!(model)
    @info "epoch" epoch val_acc = accuracy(model, val_loader)
end
```

- Use `Float32` data; `Dense` weights are `Float32` and mixing `Float64` input slows everything.
- GPU: move model and batches to the device (`gpu(model)`, or `gpu_device()` from
  MLDataDevices in newer Flux) and keep the training loop free of CPU round trips.
- Save with `JLD2.jldsave("model.jld2"; model_state = Flux.state(model))`, load with `Flux.loadmodel!`.

## 4. Lux (explicit parameters and state)

```julia
using Lux, Random, Optimisers, Zygote
rng = Xoshiro(0)
model = Chain(Dense(784 => 256, relu), Dense(256 => 10))
ps, st = Lux.setup(rng, model)                       # parameters and state are separate values
y, st = model(x, ps, st)                             # pure function call

ts = Training.TrainState(model, ps, st, Adam(1f-3))
for (x, y) in train_loader
    _, loss, _, ts = Training.single_train_step!(AutoZygote(), CrossEntropyLoss(; logits=Val(true)), (x, y), ts)
end
```

When to choose: Lux for SciML (neural ODEs, physics-informed models), explicit parameter
handling, and compilation via Reactant.jl; Flux for conventional deep learning with the larger
model zoo. AD backends: Zygote (reverse, default), Enzyme (fast, mutation-friendly), ForwardDiff
(few parameters).

## 5. CUDA.jl

```julia
using CUDA
CUDA.functional() || error("no usable GPU")
x = CUDA.rand(Float32, 10^7); y = CUDA.zeros(Float32, 10^7)
y .= 2f0 .* x .+ 1f0                  # fused broadcast = one kernel launch

function axpy!(y, a, x)
    i = (blockIdx().x - 1i32) * blockDim().x + threadIdx().x
    if i <= length(y)
        @inbounds y[i] += a * x[i]
    end
    return nothing                    # kernels must return nothing
end

kernel = @cuda launch=false axpy!(y, 2f0, x)
config = launch_configuration(kernel.fun)
threads = min(length(y), config.threads)
CUDA.@sync kernel(y, 2f0, x; threads, blocks=cld(length(y), threads))   # @sync waits for completion
```

(`1i32` comes from `using CUDA: i32`; plain `1` also works but promotes index math to Int64.)

Rules and pitfalls:

| Pitfall | Fix |
|---|---|
| scalar indexing (`x[i]` on a `CuArray` from host code) | vectorize with broadcast/`mapreduce`; keep `CUDA.allowscalar(false)` (default outside the REPL) |
| `cu(x)` silently converts `Float64` to `Float32` | intended for ML; use `CuArray(x)` to keep the element type |
| timing without sync | `CUDA.@time f()` or `CUDA.@sync` before stopping the clock; `CUDA.@profile` for a trace |
| host-device transfers in the loop | keep data resident; transfer once; `Array(x)` only at the end |
| Float64 on consumer GPUs | 1/32-1/64 throughput; use Float32 |
| type-unstable kernels | `@device_code_warntype @cuda ...` |
| out of memory | `CUDA.memory_status()`, `CUDA.reclaim()`, smaller batches, `unsafe_free!` for big temporaries |
| portability (AMD, Apple, Intel GPUs) | write kernels with KernelAbstractions.jl and pick the backend at runtime |

Use CUBLAS/CUFFT/CUSPARSE through the standard interfaces (`A * B`, `mul!`, `fft`,
`CUSPARSE.CuSparseMatrixCSR(A)`) before hand-writing kernels.
