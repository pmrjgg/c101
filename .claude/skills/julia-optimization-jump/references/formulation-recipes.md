# JuMP formulation recipes

Overflow from SKILL.md: the syntax cheat sheet, the SOS2 piecewise-linear pattern, Optimization.jl
and Optim.jl calls, and linear-time expression building. Version notes as in SKILL.md (JuMP 1.x;
nonlinear syntax and `Parameter` need 1.15+).

## Syntax cheat sheet

| Need | Syntax |
|---|---|
| bounds, integrality | `@variable(model, 0 <= x[1:n] <= 10, Int)`, `Bin` |
| sparse index set | `@variable(model, flow[a in arcs] >= 0)` (`arcs` a vector of tuples) |
| conditional index | `@variable(model, x[i in I, j in J; ok[i, j]])` gives a `SparseAxisArray` but iterates all of I×J |
| semicontinuous | `@variable(model, x in Semicontinuous(2.0, 10.0))` (0 or within [2, 10]) |
| start value | `@variable(model, x, start = 1.0)` or `set_start_value(x, 1.0)` |
| fix / unfix | `fix(x, 3.0; force = true)`, `unfix(x)` |
| reusable expression | `@expression(model, load[j in J], sum(d[i] * x[i, j] for i in I))` |
| named constraint family | `@constraint(model, cap[j in J], load[j] <= C[j])` |
| swap the solver | `set_optimizer(model, Gurobi.Optimizer)` |
| hand the model to someone | `write_to_file(model, "model.mps")`, `read_from_file("model.mps")` |

## Piecewise-linear cost with SOS2 (nonconvex case)

```julia
bp, cost = [0.0, 10.0, 20.0, 40.0], [0.0, 50.0, 80.0, 120.0]
@variable(model, λ[1:4] >= 0)
@constraint(model, sum(λ) == 1)
@constraint(model, q == sum(bp[k] * λ[k] for k in 1:4))
@constraint(model, λ in SOS2(bp))                      # at most two adjacent λ nonzero
@expression(model, pwl_cost, sum(cost[k] * λ[k] for k in 1:4))
```

A convex piecewise cost that is minimized needs no SOS2: epigraph rows `t >= a[k] * q + b[k]`
keep the model an LP.

## Optimization.jl and Optim.jl

```julia
using Optimization, OptimizationOptimJL, ForwardDiff
rosen(u, p) = (p[1] - u[1])^2 + p[2] * (u[2] - u[1]^2)^2
f = OptimizationFunction(rosen, Optimization.AutoForwardDiff())
sol = solve(OptimizationProblem(f, zeros(2), [1.0, 100.0]), LBFGS())
sol.u, sol.objective, sol.retcode                     # retcode Success when converged
# Optim.jl directly: optimize(u -> rosen(u, [1.0, 100.0]), zeros(2), LBFGS(); autodiff = :forward)
# (newer Optim releases take ADTypes: autodiff = AutoForwardDiff()); check Optim.converged(res)
```

Use these for unconstrained, box-constrained or black-box problems; anything with many
constraints belongs in JuMP.

## Linear-time expression building

```julia
ex = AffExpr(0.0)
for (i, j) in arcs
    add_to_expression!(ex, cost[i, j], flow[(i, j)])
end
@objective(model, Min, ex)
```

`ex = ex + c * x` inside a loop copies the growing expression each time (quadratic time);
`add_to_expression!` appends in place, and inside JuMP macros `sum` over a generator is rewritten
into the same in-place accumulation.
