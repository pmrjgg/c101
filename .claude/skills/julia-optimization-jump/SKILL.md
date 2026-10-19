---
name: julia-optimization-jump
description: "Mathematical optimization in Julia with JuMP and Optimization.jl. Covers model building, solver choice by problem class, status checks, MIP gaps and time limits, big-M vs indicator constraints, nonlinear expressions, duals and sensitivity, infeasibility diagnosis with conflicts, and fast model construction. Load when formulating or debugging LP, MILP, QP, conic or NLP models in Julia."
when_to_use: "Writing or reviewing a JuMP model (HiGHS, Gurobi, CPLEX, Ipopt, Clarabel, SCS, MOSEK); termination_status is INFEASIBLE, INFEASIBLE_OR_UNBOUNDED, DUAL_INFEASIBLE, TIME_LIMIT or NUMERICAL_ERROR; a MILP stalls with a large relative_gap; reading duals, shadow prices or sensitivity ranges; model construction slower than the solve; choosing between JuMP, Optimization.jl and Optim.jl."
---

# Julia optimization with JuMP

JuMP builds the model, MathOptInterface (MOI) bridges it to the solver's native form, and the
solver does the math. Most failures are formulation or status-handling bugs, not solver bugs:
check the status before reading any value, keep coefficients well scaled, and make every big-M
as small as the data allows.

Baseline: JuMP 1.x on MOI 1.x. Version-dependent: nonlinear expressions directly in
`@objective`/`@constraint`, `@operator` and `Parameter` need JuMP 1.15+;
`is_solved_and_feasible`/`assert_is_solved_and_feasible` exist only in recent 1.x releases
(2024 onward). Solver attribute names (`"mip_rel_gap"`, `"MIPGap"`) are solver-specific strings.

## 1. Model template

```julia
using JuMP, HiGHS

function solve_knapsack(value, weight, cap; time_limit = 60.0, gap = 1e-4)
    n = length(value)
    model = Model(HiGHS.Optimizer)
    set_silent(model)                               # unset_silent while debugging numerics
    set_time_limit_sec(model, time_limit)
    set_attribute(model, "mip_rel_gap", gap)        # HiGHS name; Gurobi uses "MIPGap"
    @variable(model, x[1:n], Bin)
    @constraint(model, capacity, sum(weight[i] * x[i] for i in 1:n) <= cap)
    @objective(model, Max, sum(value[i] * x[i] for i in 1:n))
    optimize!(model)
    assert_is_solved_and_feasible(model)            # throws unless OPTIMAL/LOCALLY_SOLVED with a feasible point
    return value.(x) .> 0.5, objective_value(model)
end
```

`assert_is_solved_and_feasible` rejects `TIME_LIMIT` even when a good incumbent exists; with a
time limit use the status branch of section 3 instead.

Syntax cheat sheet (bounds, sparse and conditional indices, semicontinuous variables, fix,
expressions, solver swap, MPS export): [formulation-recipes](references/formulation-recipes.md).

Name every constraint family: conflicts, duals and `print` output then say `cap[3]` instead of
an anonymous row.

## 2. Solver table

| Problem class | Open source | Commercial | Notes |
|---|---|---|---|
| LP, MILP | HiGHS | Gurobi, CPLEX, Xpress, COPT | HiGHS is the default; commercial solvers are often several times faster on hard MILPs |
| convex QP (continuous) | HiGHS, Clarabel, OSQP | Gurobi, MOSEK | MIQP: Gurobi, CPLEX, SCIP |
| SOCP, exponential and power cones | Clarabel, SCS, COSMO, ECOS | MOSEK | convex conic gives a global optimum with certificates |
| SDP | Clarabel, SCS, COSMO, Hypatia | MOSEK | SCS is first-order: expect ~1e-4 accuracy |
| smooth NLP (local) | Ipopt, MadNLP | KNITRO | result is local (`LOCALLY_SOLVED`) |
| MINLP | Juniper (Ipopt + HiGHS), SCIP, Alpine | BARON, KNITRO, Gurobi (nonconvex quadratic) | global guarantees only from SCIP, Alpine, BARON, Gurobi |
| unconstrained, box, black box | Optim.jl, Optimization.jl wrappers | none needed | section 5 |

Reformulate to the most specific class that fits (LP before conic before NLP). A convex model
handed to Ipopt only ever reports `LOCALLY_SOLVED`; the same model as a conic program comes with
a certificate. Clarabel is the default open-source conic solver; use SCS only when an
interior-point method runs out of memory.

## 3. Status handling

```julia
optimize!(model)
ts, ps = termination_status(model), primal_status(model)
if ts == OPTIMAL || ts == LOCALLY_SOLVED
    obj = objective_value(model)
elseif ts == TIME_LIMIT && ps == FEASIBLE_POINT          # incumbent exists, gap still open
    @warn "time limit" objective_value(model) objective_bound(model) relative_gap(model)
elseif ts in (INFEASIBLE, LOCALLY_INFEASIBLE)
    diagnose_infeasibility(model)                         # section 7
elseif ts in (INFEASIBLE_OR_UNBOUNDED, DUAL_INFEASIBLE)
    error("unbounded or ambiguous: bound every variable and re-solve with presolve off")
else
    error("solver stopped: $ts, $(raw_status(model))")
end
```

| termination_status | primal_status | Meaning | Action |
|---|---|---|---|
| `OPTIMAL` | `FEASIBLE_POINT` | optimal within tolerances (MIP: within the gap) | read values |
| `LOCALLY_SOLVED` | `FEASIBLE_POINT` | NLP local optimum | multistart or a convex reformulation if global matters |
| `TIME_LIMIT` | `FEASIBLE_POINT` | incumbent, gap open | accept if `relative_gap` meets the target, else strengthen the formulation |
| `TIME_LIMIT` | `NO_SOLUTION` | no incumbent found | MIP start, smaller big-M, longer limit |
| `INFEASIBLE` | `NO_SOLUTION` | proven infeasible | section 7 |
| `INFEASIBLE_OR_UNBOUNDED` | `NO_SOLUTION` | presolve could not tell which | HiGHS: `set_attribute(model, "presolve", "off")`, re-solve |
| `DUAL_INFEASIBLE` | any | unbounded if feasible | add bounds; check objective sense and signs |
| `ALMOST_OPTIMAL`, `ALMOST_LOCALLY_SOLVED` | any | tolerances missed | rescale (section 4) |
| `NUMERICAL_ERROR`, `SLOW_PROGRESS` | any | numerics | rescale, smaller big-M, other algorithm |
| `ITERATION_LIMIT`, `NODE_LIMIT`, `SOLUTION_LIMIT` | any | a limit was hit | raise it or accept the incumbent |

Queries: `solution_summary(model)` (`verbose = true` lists values), `objective_bound(model)`,
`relative_gap(model)`, `solve_time(model)`, `result_count(model)` with `value(x; result = 2)`
for solution pools, `raw_status(model)` for the solver's own message.

Gap targets: 1e-4 (HiGHS default) for small models and tests; 1e-3 to 1e-2 for planning models
whose data is uncertain at that level anyway. Always report the bound next to the incumbent.

## 4. Formulation craft

Big-M: derive M from data as the largest value the constrained expression can take.

```julia
# x[i, j] = quantity shipped from site j to customer i, y[j] = site open
# weak:   x[i, j] <= 1e6 * y[j]
M = [min(d[i], C[j]) for i in I, j in J]            # x[i, j] can never exceed either
@constraint(model, link[i in I, j in J], x[i, j] <= M[i, j] * y[j])
```

- An M of 1e6 next to coefficients near 1 gives a weak relaxation (large gap) and lets a
  binary at 1e-7 switch the constraint off within tolerance.
- Indicator constraints when no finite bound exists:
  `@constraint(model, [j in J], !y[j] --> {sum(x[:, j]) <= 0})`. Native in Gurobi, CPLEX,
  Xpress and SCIP; recent MOI versions bridge them to big-M for other solvers only when the
  variables have finite bounds. A tight explicit big-M often solves faster than an indicator.
- Keep disaggregated linking rows (`x[i, j] <= M[i, j] * y[j]`) next to the aggregated capacity
  row: the aggregated row alone lets `y[j]` sit at load/capacity in the relaxation.
- Symmetry: identical sites, machines or vehicles get ordering rows
  (`@constraint(model, [j in 1:m-1], y[j] >= y[j+1])`), else branch and bound explores every
  permutation of the same solution.
- Scaling: keep matrix, cost, bound and RHS magnitudes within roughly 1e-6 to 1e6. Change units
  (kilo-dollars, tonnes, hours) instead of trusting solver scaling. HiGHS prints its
  "Coefficient ranges" when not silent: read them first on any numerical trouble.
- Bound every integer variable from data; unbounded `Int` variables cripple branching.

Piecewise-linear costs with an SOS2 λ formulation, with code:
[formulation-recipes](references/formulation-recipes.md).

| Situation | Use |
|---|---|
| binary switches a bounded continuous quantity | big-M with data-derived M |
| no finite bound available | indicator (native solver) |
| at most one of a group nonzero | `sum(z) <= 1` over binaries, or `SOS1` for continuous variables |
| nonconvex piecewise-linear function | `SOS2` λ formulation (recipes reference) |
| convex piecewise cost being minimized | epigraph rows `t >= a[k] * q + b[k]`: plain LP, no SOS2 |
| identical machines, sites, vehicles | ordering constraints |

## 5. Nonlinear

```julia
using JuMP, Ipopt
model = Model(Ipopt.Optimizer); set_silent(model)
@variable(model, x[1:2], start = 0.5)                 # Ipopt needs sensible starts
@objective(model, Min, (1 - x[1])^2 + 100 * (x[2] - x[1]^2)^2)
@constraint(model, x[1]^2 + x[2]^2 <= 1.5)
@constraint(model, exp(x[1]) - x[2] >= 0.5)
optimize!(model)                                      # expect LOCALLY_SOLVED

penalty(a, b) = a > b ? (a - b)^2 : zero(a)           # accept any Real: ForwardDiff passes Dual numbers
@operator(model, op_penalty, 2, penalty)              # name, arity, function (gradient, Hessian optional)
@objective(model, Min, op_penalty(x[1], x[2]) + x[1]^2)
```

- Use `@operator` for functions JuMP cannot trace (branches, loops, calls into other packages);
  univariate operators accept derivatives: `@operator(model, op_f, 1, f, df, d2f)`.
- Never mix the legacy `@NLobjective`/`@NLconstraint`/`@NLexpression` macros with the new
  syntax in one model; migrate everything.
- Repeated solves with changing data: `@variable(model, p in Parameter(1.0))`, then
  `set_parameter_value(p, 2.0)` and `optimize!` again.

| Problem | Tool |
|---|---|
| unconstrained smooth, gradient by AD | Optim.jl `LBFGS()`, or Optimization.jl + `OptimizationOptimJL` |
| box-constrained smooth | Optim.jl `Fminbox(LBFGS())` |
| derivative-free, under ~20 parameters | `NelderMead()`; global search via `OptimizationBBO` (BlackBoxOptim) |
| ODE parameter fitting | Optimization.jl + SciMLSensitivity (see `julia-sciml-diffeq`) |
| constrained, sparse, large | JuMP |

Optimization.jl puts Optim.jl, BlackBoxOptim and others behind one `OptimizationProblem`/`solve`
interface; worked calls for it and for Optim.jl: [formulation-recipes](references/formulation-recipes.md).

## 6. Duals and sensitivity

```julia
optimize!(model)
assert_is_solved_and_feasible(model; dual = true)    # also requires a dual solution
dual(cap[j])                 # MOI convention: sign depends on constraint direction and sense
shadow_price(cap[j])         # objective change per unit relaxation of the RHS (LP only)
reduced_cost(x[i, j])
report = lp_sensitivity_report(model)
report[cap[j]]               # (lo, hi) RHS change range for which the basis stays optimal
report[x[i, j]]              # (lo, hi) objective-coefficient change range
```

- `shadow_price` for explanations to people; `dual` for algorithms needing the conic sign
  convention (Lagrangian bounds, column generation). Check `has_duals(model)` first.
- MIPs have no duals. Conditional prices given the integer decisions:

```julia
undo = fix_discrete_variables(model)    # fix Int/Bin at their values, drop integrality
optimize!(model)
assert_is_solved_and_feasible(model; dual = true)
prices = shadow_price.(model[:serve])
undo()                                   # restore the MIP
```

## 7. Infeasibility debugging

Stop at the first rung that explains the infeasibility.

1. Data sanity: total demand vs total capacity, `lb <= ub` everywhere, empty index sets.
2. LP relaxation: `undo = relax_integrality(model); optimize!(model)`. Still infeasible: the
   conflict is linear and cheap to diagnose. Feasible: integrality or big-M logic causes it.
3. Conflict (IIS): `compute_conflict!(model)`, check
   `get_attribute(model, MOI.ConflictStatus()) == MOI.CONFLICT_FOUND`, then
   `iis_model, _ = copy_conflict(model); print(iis_model)` or loop over constraints with
   `MOI.ConstraintConflictStatus()` (section 11). Native in Gurobi, CPLEX and Xpress; HiGHS
   implements it through MathOptIIS.jl, which is fine on small and medium models but can run
   for a very long time on large ones: diagnose the LP relaxation or a reduced instance.
4. Penalty relaxation, any LP/MILP solver:

```julia
penalties = relax_with_penalty!(model; default = 1.0)   # a priced slack on every constraint
optimize!(model)
for (con, pen) in penalties
    v = value(pen)
    v > 1e-6 && println(con, " violated by ", v)
end
```

   Price trusted constraints high (`relax_with_penalty!(model, Dict(con => 1e3))`) so the
   violations land on the soft ones. It mutates the model: rebuild before solving for real.
5. Check a known-good plan: `primal_feasibility_report(model, point; atol = 1e-6)` with
   `point::Dict{VariableRef,Float64}` lists violated constraints and amounts
   (`skip_missing = true` for partial points).

Unbounded models: add temporary bounds of ±1e6, re-solve, and list variables at a bound.

## 8. Construction speed

Measure `@elapsed build(data)` against `solve_time(model)`; act when building exceeds ~20% of
the total.

| Fix | Effect |
|---|---|
| `sum` over generators inside the macros, `add_to_expression!(ex, coef, var)` | linear time; `ex = ex + c * x` in a loop is quadratic |
| precomputed adjacency (`out_arcs[i]`) instead of conditions over I×J | no pass over the full product |
| `direct_model(HiGHS.Optimizer())` | no cache copy (about half the memory); no `set_optimizer` later |
| `set_string_names_on_creation(model, false)` | no name strings on huge models |
| `Model(HiGHS.Optimizer; add_bridges = false)` | when every constraint type is native |
| `set_normalized_rhs`, `set_normalized_coefficient`, `set_objective_coefficient` | edit and re-solve; LP solvers warm-start from the previous basis |
| `Parameter` variables | data changes without rebuilding |
| MIP start `set_start_value.(y, y_prev)` | immediate first incumbent where the solver supports starts |

## 9. Testing models

- Tiny instances with hand-checked optima as unit tests; a deliberately infeasible instance
  must reach the infeasibility branch, not crash.
- Invariants on every returned solution, and a cross-check on small instances against a second
  solver or brute force over the binaries (objectives equal within 1e-6 relative).

```julia
using Test
@testset "facility location" begin
    m = facility_model(tiny...); optimize!(m)
    @test termination_status(m) == OPTIMAL
    @test objective_value(m) ≈ 37.0 atol = 1e-6               # hand-computed optimum
    @test isempty(primal_feasibility_report(m; atol = 1e-6))  # current solution violates nothing
    @test all(v -> abs(v - round(v)) < 1e-6, value.(m[:y]))
end
```

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `OptimizeNotCalled` when reading `value` | model modified after `optimize!`, or never solved | re-solve; read values right after the solve |
| values from an infeasible or time-limited run | no status check | section 3 branch |
| binary at 0.9999999 or 1e-7 | tolerances | compare `> 0.5`, never `== 1` |
| gap never closes | weak big-M, symmetry, aggregated linking only | section 4 |
| `NUMERICAL_ERROR`, `ALMOST_OPTIMAL` | coefficients spanning more than ~1e12 | rescale units |
| `INFEASIBLE_OR_UNBOUNDED` read as infeasible | presolve ambiguity | presolve off, bound variables |
| Ipopt answer reported as global | `LOCALLY_SOLVED` | multistart or convex reformulation |
| slow build, fast solve | quadratic expression building, I×J filters | section 8 |
| dual signs look wrong | MOI conic convention | `shadow_price` for interpretation |
| `MethodError` with `Dual` in an operator | function typed to `Float64` | accept `Real` |
| assert throws on a good time-limited incumbent | it requires `OPTIMAL`/`LOCALLY_SOLVED` | section 3 branch |

## 11. Worked example: capacitated facility location, then an infeasible variant

`x[i, j]` is the share of customer i's demand served by site j, so the tightest valid big-M in
the linking rows is 1.

```julia
using JuMP, HiGHS, Random
rng = Xoshiro(1)
nI, nJ = 40, 10
cust, site = rand(rng, nI, 2), rand(rng, nJ, 2)
c = [100 * hypot(cust[i, 1] - site[j, 1], cust[i, 2] - site[j, 2]) for i in 1:nI, j in 1:nJ]
d, C, f = rand(rng, 10:30, nI), rand(rng, 150:250, nJ), rand(rng, 300:600, nJ)

function facility_model(c, d, C, f)
    nI, nJ = size(c)
    model = Model(HiGHS.Optimizer)
    set_silent(model)
    set_time_limit_sec(model, 30.0)
    set_attribute(model, "mip_rel_gap", 1e-3)
    @variable(model, 0 <= x[1:nI, 1:nJ] <= 1)
    @variable(model, y[1:nJ], Bin)
    @constraint(model, serve[i in 1:nI], sum(x[i, j] for j in 1:nJ) == 1)
    @constraint(model, cap[j in 1:nJ], sum(d[i] * x[i, j] for i in 1:nI) <= C[j] * y[j])
    @constraint(model, link[i in 1:nI, j in 1:nJ], x[i, j] <= y[j])      # disaggregated, M = 1
    @objective(model, Min, sum(f[j] * y[j] for j in 1:nJ) +
                           sum(c[i, j] * d[i] * x[i, j] for i in 1:nI, j in 1:nJ))
    return model
end

model = facility_model(c, d, C, f)
optimize!(model)
ts = termination_status(model)
ts == OPTIMAL || (ts == TIME_LIMIT && primal_status(model) == FEASIBLE_POINT) || error("no solution: $ts")
X, Y = value.(model[:x]), value.(model[:y])
@assert all(abs.(sum(X; dims = 2) .- 1) .< 1e-6)          # every customer fully served
@assert all(X' * d .<= C .* Y .+ 1e-6)                    # load within open capacity
println("open ", findall(Y .> 0.5), " obj ", objective_value(model), " gap ", relative_gap(model))
```

Acceptance: `relative_gap <= 1e-3` and both invariants hold. Deleting the `link` family and
re-solving (HiGHS log via `unset_silent`) shows a weaker root bound and more nodes: that is the
evidence for keeping it.

Infeasible variant: a policy allows at most two sites, but total demand (~800) exceeds any two
capacities (at most 500).

```julia
bad = facility_model(c, d, C, f)
@constraint(bad, policy, sum(bad[:y]) <= 2)
optimize!(bad); termination_status(bad)            # INFEASIBLE

undo = relax_integrality(bad)                      # rung 2: the LP is infeasible too, so diagnose the LP
optimize!(bad)
compute_conflict!(bad)                             # HiGHS via MathOptIIS; Gurobi/CPLEX/Xpress natively
if get_attribute(bad, MOI.ConflictStatus()) == MOI.CONFLICT_FOUND
    for (F, S) in list_of_constraint_types(bad), con in all_constraints(bad, F, S)
        MOI.get(bad, MOI.ConstraintConflictStatus(), con) == MOI.IN_CONFLICT && println(con)
    end
end                                                # expect: policy, the cap[j] and serve[i] rows, y <= 1 bounds
undo()

pen = relax_with_penalty!(bad, Dict(bad[:policy] => 1_000.0))
optimize!(bad)
value(pen[bad[:policy]])                           # extra sites the cheapest repair needs beyond 2
```

Reading: the conflict says the two-site policy cannot carry total demand; the penalty run turns
that into a number the planner can act on (open more sites or cut demand), instead of a bare
INFEASIBLE.

Related: `julia-sciml-diffeq`, `julia-performance-allocations`, `julia-type-stability`, `julia-packages-environments`, hub `julia-craft`
