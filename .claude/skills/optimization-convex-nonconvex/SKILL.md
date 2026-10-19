---
name: optimization-convex-nonconvex
description: "Formulating and solving optimisation problems: classifying the problem and choosing a solver (LP/QP/SOCP/SDP/MILP/NLP/black-box), convexity checks and DCP modelling in CVXPY or JuMP, KKT conditions with constraint qualifications, duality certificates, first-order method rates, local NLP solvers with gradient checks, global and combinatorial methods, and verifying returned optima. Load when anything is minimised, fitted, allocated or scheduled."
when_to_use: "Choose a solver or formulation; fix a CVXPY DCP, DGP or DPP error; derive or check KKT conditions or a dual; read duals as sensitivities or infeasibility certificates; pick step sizes for gradient, proximal or ADMM methods; run scipy.optimize with exact, checked gradients; write a tight MILP; or certify whether a returned optimum is global, local or only best-found."
---

# Optimisation: convex and nonconvex

Classify the problem first, because the class decides which certificate exists:

| Problem | Certificate |
|---|---|
| convex, in disciplined form | duality gap: certified global optimum |
| smooth nonconvex | KKT residual: local optimum |
| MILP | branch-and-bound gap |
| black box | none: best found |

Always say which of these you are reporting.

## 1. Classification and solver choice

| Problem form | Class | Open-source solvers | Commercial |
|---|---|---|---|
| linear objective and constraints | LP | HiGHS (`scipy.optimize.linprog(method="highs")`), GLOP (OR-Tools) | Gurobi, CPLEX, MOSEK |
| LP plus integer variables | MILP | HiGHS (`scipy.optimize.milp`), SCIP, CBC | Gurobi, CPLEX |
| convex quadratic objective, linear constraints | QP | OSQP (ADMM, moderate accuracy), Clarabel (interior point), PIQP | Gurobi, MOSEK |
| norms, √, hyperbolic constraints | SOCP | Clarabel, ECOS, SCS | MOSEK, Gurobi |
| linear matrix inequalities | SDP | Clarabel, SCS (first-order, about 1e−4) | MOSEK |
| exp, log, entropy; a GP after the log transform | exponential cone | Clarabel, SCS | MOSEK |
| smooth nonlinear with constraints | NLP | IPOPT (JuMP, cyipopt), scipy `trust-constr`, `SLSQP` | KNITRO, SNOPT |
| smooth, bounds only | box-constrained | scipy `L-BFGS-B` | — |
| logic, scheduling, assignment with integer data | CP | OR-Tools CP-SAT | — |
| nonconvex with integers | MINLP | SCIP, Bonmin, Couenne | BARON, Gurobi (nonconvex quadratic) |
| expensive black box, a few hundred evaluations | Bayesian optimisation / HPO | Optuna (TPE), BoTorch/Ax (GP) | — |

Decision:

1. If it can be written in convex form (section 2), use a conic solver through CVXPY or JuMP; that
   gives a certified global optimum.
2. If it is smooth but nonconvex, use a local NLP solver with exact gradients and multistart
   (section 7).
3. If it is discrete, use MILP or CP-SAT and report the gap (section 8).
4. If it is a black box, fix an evaluation budget and report the best point found.

## 2. Recognising convexity

- **Tests.** f is convex iff dom f is convex and f(θx + (1−θ)y) ≤ θf(x) + (1−θ)f(y). For C² f the
  test is ∇²f ⪰ 0 on the open convex domain. PSD needs **all** principal minors ≥ 0, not only the
  leading ones: [[0,0],[0,−1]] has leading minors 0, 0 and is not PSD. Positive definiteness does
  follow from leading minors > 0 (Sylvester). Hessian eigenvalues at sample points are evidence,
  not proof.
- **Composition.** h(g(x)) is convex if h is convex and nondecreasing and g is convex, or h is
  convex and nonincreasing and g is concave, or h is convex and g is affine. Maxima and nonnegative
  sums of convex functions are convex. inf over y ∈ C of a jointly convex f(x, y) is convex in x
  when C is convex.
- **Perspective.** t f(x/t) is convex for t > 0 when f is convex (x²/t is `quad_over_lin`;
  x log(x/y) is `rel_entr`).
- **Schur complement.** For C ≻ 0, [[A, B], [Bᵀ, C]] ⪰ 0 ⇔ A − B C⁻¹ Bᵀ ⪰ 0. So xᵀP⁻¹x ≤ t with
  P ≻ 0 ⇔ [[P, x], [xᵀ, t]] ⪰ 0.
- **Reformulations.**
  - |x| ≤ t ⇔ −t ≤ x ≤ t, and max_i (a_iᵀx + b_i) ≤ t ⇔ each term ≤ t.
  - ‖x‖₁ ≤ t ⇔ −s ≤ x ≤ s and Σs ≤ t, and ‖x‖₂ ≤ t is a second-order cone.
  - A linear-fractional objective (cᵀx + d)/(eᵀx + f) with eᵀx + f > 0 becomes an LP by
    Charnes-Cooper: y = x/(eᵀx + f), z = 1/(eᵀx + f).
  - Log-sum-exp is convex. Geometric programs become convex after x = e^y (CVXPY `gp=True`).
- **Nonconvex signals.** An indefinite xᵀQx; a nonlinear equality constraint (even with h convex);
  a bilinear xy; ‖x‖ ≥ 1; rank constraints; integrality; division by a variable.

| CVXPY rejects | Rewrite |
|---|---|
| x*y with both variables | not DCP: reformulate (geo_mean, a Schur LMI) or fix one factor |
| sqrt(x**2 + y**2) | `cp.norm(cp.hstack([x, y]))` |
| x**2/y | `cp.quad_over_lin(x, y)` |
| 1/x for x > 0 | `cp.inv_pos(x)` |
| xᵀPx with P numerically indefinite | `cp.sum_squares(L.T @ x)` with P = L Lᵀ, or `cp.psd_wrap(P)` when P ⪰ 0 is known |
| log(sum(exp(.))) | `cp.log_sum_exp` |
| −x log x, x log(x/y) | `cp.entr`, `cp.rel_entr`, `cp.kl_div` |
| a product of positive variables to a fractional power | `cp.geo_mean` |

Check `expr.curvature`, `prob.is_dcp()`, `prob.is_dgp()` and `prob.is_dpp()`. A DCPError lists the
offending subexpressions ("The objective is not DCP. Its following subexpressions are not: ...").

## 3. CVXPY practice (and JuMP)

```python
import cvxpy as cp, numpy as np
x = cp.Variable(3); lam = cp.Parameter(nonneg=True)
prob = cp.Problem(cp.Minimize(cp.sum_squares(x - 1) + lam * cp.norm1(x)))
assert prob.is_dpp()                     # parameters enter affinely, so re-solves skip recompilation
for v in (0.1, 1.0, 10.0):
    lam.value = v
    prob.solve(solver=cp.CLARABEL)
    if prob.status != cp.OPTIMAL:        # optimal_inaccurate, infeasible, unbounded, ...
        raise RuntimeError(prob.status)
    print(v, x.value.round(6))           # soft thresholding: max(1 - v/2, 0) = 0.95, 0.5, 0
```

- **Statuses.** `cp.OPTIMAL`, `OPTIMAL_INACCURATE`, `INFEASIBLE`, `INFEASIBLE_INACCURATE`,
  `UNBOUNDED`, `UNBOUNDED_INACCURATE`, `USER_LIMIT`, `SOLVER_ERROR`. `prob.value` is +inf for an
  infeasible minimisation and −inf for an unbounded one. Treat any *_INACCURATE status as
  unverified.
- **Duals.** `constraint.dual_value`. Measured with CVXPY 1.9 and Clarabel: a `w >= 0` constraint
  has dual λ ≥ 0 entering the Lagrangian as −λᵀw, and `cp.sum(w) == 1` has dual y entering as
  +y(Σw − 1). Confirm the convention with a stationarity residual every time (section 9).
- **Infeasibility.** On an infeasible problem, conic solvers such as Clarabel put a Farkas
  certificate in `dual_value` (section 5). Check it yourself.
- **Scaling.** Rescale variables and rows so the data entries are O(1). First-order solvers (SCS,
  OSQP) are the most scale-sensitive.
- **Tolerances.** Clarabel (interior point) defaults to about 1e−8 (`tol_gap_abs`, `tol_gap_rel`,
  `tol_feas`). OSQP and SCS are first-order with looser defaults (`eps_abs`, `eps_rel`, from about
  1e−3 to 1e−5 depending on the version). Tighten them, or switch to Clarabel, when KKT residuals
  must fall below 1e−6. OSQP's `polish=True` refines the active set.
- **Diagnostics.** `prob.solver_stats` (solve time, iterations) and `prob.solve(verbose=True)`.

```julia
using JuMP, Clarabel
model = Model(Clarabel.Optimizer)
@variable(model, w[1:n] >= 0)
@constraint(model, budget, sum(w) == 1)
@objective(model, Min, w' * Σ * w)
optimize!(model)
is_solved_and_feasible(model) || error(termination_status(model))
value.(w), objective_value(model), dual(budget), shadow_price(budget)
```

JuMP's `dual` follows conic-duality signs, while `shadow_price` is the objective change per unit of
relaxation. `is_solved_and_feasible` exists in recent JuMP; on older versions test
`termination_status(model) == OPTIMAL` and `primal_status(model) == FEASIBLE_POINT`.

## 4. Optimality conditions (KKT)

For min f(x) s.t. g_i(x) ≤ 0, h_j(x) = 0, take L = f + Σλ_i g_i + Σν_j h_j. The KKT conditions are:

1. stationarity: ∇f + Σλ_i∇g_i + Σν_j∇h_j = 0;
2. primal feasibility;
3. dual feasibility: λ ≥ 0;
4. complementary slackness: λ_i g_i(x) = 0.

A local minimum satisfies KKT only under a constraint qualification:

| CQ | Statement | Consequence |
|---|---|---|
| LICQ | the gradients of the active constraints are linearly independent | KKT necessary, unique multipliers |
| MFCQ | the ∇h_j are independent and some d has ∇h_jᵀd = 0 and ∇g_iᵀd < 0 for every active i | KKT necessary, bounded multiplier set |
| Slater (convex problems) | some point is strictly feasible for the nonaffine g_i | KKT necessary, strong duality |
| linear constraints | all g_i and h_j affine | KKT necessary without further conditions |

Without a CQ KKT can fail. Example: min x s.t. x² ≤ 0 has x* = 0, but ∇f = 1 and ∇g = 0, so no
multiplier exists.

- **Sufficiency.** If f and the g_i are convex and the h_j affine, every KKT point is a global
  minimum; no CQ is needed.
- **Second order, nonconvex.** At a KKT point with its multipliers, suppose dᵀ∇²_xx L d > 0 for every
  d ≠ 0 in the critical cone: ∇h_jᵀd = 0, ∇g_iᵀd = 0 for active i with λ_i > 0, and ∇g_iᵀd ≤ 0 for
  active i with λ_i = 0. Then the point is a strict local minimum. Under LICQ, ≥ 0 on the cone is
  necessary. With strict complementarity, test the reduced Hessian Zᵀ∇²L Z, where Z is a null-space
  basis of the active gradients.

## 5. Duality

- **Dual problem.** g(λ, ν) = inf_x L(x, λ, ν) is concave; the dual problem maximises g over λ ≥ 0.
- **Weak duality.** g(λ, ν) ≤ p* for every λ ≥ 0, so f(x) − g(λ, ν) ≥ f(x) − p*. The duality gap of
  any feasible pair bounds the suboptimality, and that gap is the certificate to report.
- **Strong duality.** Convexity plus Slater gives d* = p*, with the dual optimum attained. For LPs it
  holds whenever either the primal or the dual has a finite optimum.
- **LP pair.** min cᵀx s.t. Ax = b, x ≥ 0 pairs with max bᵀy s.t. Aᵀy ≤ c. Complementary
  slackness: x_j(c − Aᵀy)_j = 0.
- **Farkas.** Exactly one holds: some x ≥ 0 has Ax = b, or some y has Aᵀy ≥ 0 and bᵀy < 0. That y
  certifies infeasibility; check it numerically. CVXPY with Clarabel on x₁ + x₂ = −1, x ≥ 0 returned
  y = 1: Aᵀy = (1, 1) ≥ 0 and bᵀy = −1 < 0.
- **Sensitivity.** For min f s.t. g_i(x) ≤ u_i (convex), p*(u) ≥ p*(0) − λ*ᵀu globally, and
  ∂p*/∂u_i = −λ_i* where p* is differentiable. LP duals are shadow prices only while the optimal
  basis is unchanged (ranging). Degenerate LPs have non-unique duals and one-sided derivatives.

## 6. First-order methods and rates

Assume f is L-smooth (‖∇f(x) − ∇f(y)‖ ≤ L‖x − y‖) and, where stated, μ-strongly convex; κ = L/μ and
R = ‖x₀ − x*‖.

| Method | Assumptions | Guarantee |
|---|---|---|
| gradient descent, step 1/L | convex | f(x_k) − f* ≤ L R²/(2k) |
| gradient descent, step 1/L | μ-strongly convex | f(x_k) − f* ≤ (1 − 1/κ)^k (f(x₀) − f*) |
| Nesterov accelerated | convex | f(x_k) − f* ≤ 2L R²/(k + 1)² |
| Nesterov accelerated | μ-strongly convex | rate (1 − 1/√κ)^k: about √κ log(1/ε) iterations |
| subgradient, step ∝ 1/√k | convex, G-Lipschitz | best iterate within O(RG/√k) |
| SGD | convex, bounded gradient variance | O(1/√k) for the averaged iterate; O(1/k) when strongly convex with steps ∝ 1/(μk) |
| proximal gradient (ISTA) / FISTA | f smooth plus g with a cheap prox | O(1/k) / O(1/k²) |
| ADMM | convex, two-block splitting | O(1/k), ergodic |
| damped Newton | strongly convex, Lipschitz Hessian | locally quadratic |

- **Prox examples.** The prox of t‖·‖₁ is soft thresholding sign(v)·max(abs(v) − t, 0); projection
  onto a box is clipping.
- **Diagnosing divergence.** On a quadratic, steps above 2/L diverge with oscillations of growing
  amplitude. Estimate L by power iteration on Hessian-vector products, or backtrack with the Armijo
  test f(x − t∇f) ≤ f(x) − (t/2)‖∇f‖². Read the symptoms:
  - rising loss: shrink the step;
  - slow zig-zag: ill-conditioning (large κ), so precondition or rescale;
  - noisy plateau: SGD variance, so decay the step or grow the batch.

## 7. Nonconvex local optimisation

| Situation | `scipy.optimize` choice |
|---|---|
| smooth, unconstrained, gradient available | BFGS (small n), L-BFGS-B (large n) |
| bounds only | L-BFGS-B, TNC |
| general constraints, small to medium n | SLSQP (fast, fragile), trust-constr (robust, accepts Hessians) |
| Hessian or Hessian-vector products available | trust-exact, trust-krylov, Newton-CG |
| a residual vector (least squares) | `least_squares` (trf, lm) |
| nonsmooth or noisy, low dimension | Nelder-Mead, Powell (no guarantees) |

- **Exact gradients.** Get them from JAX (`jax.grad` + `jax.jit`, with x64 enabled) or autograd, and
  pass `jac=`.
- **Gradient check.** `check_grad(f, grad, x0)` returns ‖grad − finite difference‖; compare it with
  ‖grad‖. For Rosenbrock at (1.2, 0.8, 1.1) it gives 1.1e−5 against a gradient norm of 423 (relative
  2.5e−8: correct). A relative error near 1 means a bug.
- **Scaling.** Scale variables (x = Dz) and the objective to O(1): `gtol` and similar tolerances are
  absolute.
- **Multistart.** Start from a Sobol or Latin-hypercube design (`scipy.stats.qmc`), cluster the
  solutions, and report the best together with how many starts reached it.
- **Read the result.** Check `res.success`, `res.message`, `res.nit` and ‖res.jac‖ at the solution.
  success=True only means a stopping test fired.

## 8. Global and discrete methods

- **scipy global methods.** `differential_evolution` (bounds, constraints, integrality; polishes
  with L-BFGS-B), `dual_annealing`, `shgo` (low dimension; can return every local minimum) and
  `basinhopping` (random jumps plus a local minimiser). None certifies global optimality: report
  "best found after N evaluations and M starts".
- **Big-M.** x ≤ M y with y binary.
  - M must be a valid bound; too small cuts off optima.
  - M must be as tight as possible. Too large weakens the LP relaxation and interacts with the
    integrality tolerance: with M = 1e6 and tolerance 1e−5, y = 1e−5 already allows x = 10.
  - Derive M from variable bounds, or use indicator or SOS1 constraints (Gurobi, CP-SAT).
- **Tight formulations.** Disaggregated constraints (x_ij ≤ y_i for each j) beat aggregated ones
  (Σ_j x_ij ≤ n y_i). Also use convex-hull or extended formulations and symmetry breaking.
- **Gaps are certificates.** The branch-and-bound gap (incumbent − bound)/|incumbent| goes in the
  report. Gurobi's default MIPGap is 1e−4; HiGHS's `mip_rel_gap` is similar.
- **SOS for polynomials.** min p(x) ≥ max γ s.t. p − γ is a sum of squares, which is an SDP.
  Lasserre's hierarchy converges under an Archimedean condition, and the SOS bound is exact for
  univariate polynomials and for quadratics. If the SOS bound equals p at a feasible point, that
  point is globally optimal up to solver tolerance. Tools: SumOfSquares.jl, TSSOS, or a Gram-matrix
  SDP in CVXPY (see `inequality-proving`).

## 9. Verifying any returned optimum

1. **Feasibility residuals.** max_i max(g_i(x), 0), max_j |h_j(x)| and |x − round(x)| for integer
   variables, all relative to the data scale.
2. **KKT residuals** with the returned duals: the stationarity norm, min(λ, 0) and max_i |λ_i g_i(x)|.
3. **Duality gap** f(x) − g(λ, ν), or primal minus dual objective, for convex problems.
4. **Perturbed restart.** Perturb the start or the data by about 1e−6 and re-solve. A different x
   with the same objective means non-uniqueness; a different objective means a fragile or local
   solution.
5. **Bounds.** Compare with a relaxation (LP, SDP or Lagrangian bound) or a closed-form special
   case.
6. **Label.** "Certified optimal (gap ≤ ε)", "KKT point, residual ≤ ε (local)", or "best found, no
   certificate".

## 10. Pitfalls

- **A nonconvex problem fed to a convex solver**, for example through `psd_wrap` on an indefinite
  matrix. The answer is meaningless.
- **Unscaled data**, with coefficients from 1e−6 to 1e6. Expect *_inaccurate statuses and wrong
  active sets.
- **Redundant equality rows** (rank-deficient A). They cause solver failures or non-unique duals:
  remove them, or plan for them.
- **Integer variables silently relaxed**, by a solver without MIP support or a dropped
  `integer=True`.
- **optimal_inaccurate treated as optimal.**
- **A local minimum reported as global**, or success=True from a stopping test reported as
  optimality.
- **Unreliable gradients.** Finite differences on a noisy objective, or analytic gradients never
  checked.
- **Dual sign conventions assumed instead of checked.**

## 11. Worked example: long-only minimum-variance portfolio

Minimise wᵀΣw s.t. 1ᵀw = 1 and w ≥ 0, with σ = (0.10, 0.15, 0.20, 0.25), constant correlation ρ and
Σ = diag(σ) C diag(σ).

- **KKT.** With L = wᵀΣw + ν(1 − 1ᵀw) − λᵀw: 2Σw = ν1 + λ, λ ≥ 0 and λ_i w_i = 0.
- **Inactive bounds.** If no bound is active, w* = Σ⁻¹1/(1ᵀΣ⁻¹1) with variance 1/(1ᵀΣ⁻¹1).
  Multiplying the stationarity by wᵀ gives ν = 2 × variance.
- **Dual function.** g(ν, λ) = ν − ¼(ν1 + λ)ᵀΣ⁻¹(ν1 + λ).

```python
import numpy as np, cvxpy as cp
sig = np.array([0.10, 0.15, 0.20, 0.25]); one = np.ones(4)
for rho in (0.2, 0.8):
    C = np.full((4, 4), rho); np.fill_diagonal(C, 1.0); S = np.outer(sig, sig) * C
    w = cp.Variable(4); cons = [cp.sum(w) == 1, w >= 0]
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, S)), cons)
    prob.solve(solver=cp.CLARABEL, tol_gap_abs=1e-12, tol_gap_rel=1e-12, tol_feas=1e-12)
    assert prob.status == cp.OPTIMAL
    wv, nu, lam = w.value, -cons[0].dual_value, cons[1].dual_value   # CVXPY's y equals -nu here
    stat = np.abs(2 * S @ wv - nu * one - lam).max()
    v = nu * one + lam
    gap = prob.value - (nu - 0.25 * v @ np.linalg.solve(S, v))
    wcf = np.linalg.solve(S, one); wcf /= wcf.sum()                   # closed form without w >= 0
    print(rho, wv.round(6), lam.round(6), stat, gap, np.abs(wv - wcf).max())
```

| ρ | w | λ | stationarity | gap | closed form |
|---|---|---|---|---|---|
| 0.2 | (0.658763, 0.223629, 0.086892, 0.030715) | 0 | 3.9e−17 | 8.7e−14 | matches to 1.3e−11: all w_i > 0, bounds inactive |
| 0.8 | (1, 0, 0, 0) | (0, 0.004, 0.012, 0.020) | 3.6e−15 | 9.0e−13 | unconstrained w = (1.301, 0.137, −0.171, −0.268) is infeasible; the closed form on the support {1} gives w₁ = 1 |

Reading the duals:

- ν = 2 × variance: 0.0155 = 2 × 0.00776 for ρ = 0.2, and 0.02 = 2 × 0.01 for ρ = 0.8.
- λ_i > 0 marks the assets the long-only bound pins at zero. Forcing w_i ≥ ε raises the variance by
  about λ_i ε.

Status: certified optimal (KKT residual and duality gap below 1e−8), and it matches the closed form
when the nonnegativity bounds are inactive.

Related: `inequality-proving`, `matrix-decompositions-conditioning`, `numerical-error-analysis`, `statistical-inference-bayesian`, `uncertainty-propagation-fitting`, `variational-quantum-algorithms`, hub `mathematics-toolkit`
