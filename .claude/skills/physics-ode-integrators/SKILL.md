---
name: physics-ode-integrators
description: "Choosing, running and diagnosing ODE and SDE time steppers for physical systems: symplectic Verlet/Yoshida for long Hamiltonian runs, adaptive RK (DOP853, Tsit5) with tolerance-reduction checks, stiff BDF/Radau/Rodas with Jacobians, events, constraints and Langevin integrators. Load when writing or debugging a time integrator."
when_to_use: "Calling solve_ivp, OrdinaryDiffEq.jl, diffrax, SUNDIALS or REBOUND; energy drift in an orbit, MD or rigid-body run; an explicit solver taking millions of tiny steps (stiffness); choosing rtol and atol; impacts, switching or zero-crossing events; holonomic constraints or DAEs; Langevin or Brownian dynamics; measuring the observed order of a stepper."
---

# Physics ODE and SDE integrators

Time integration fails in five repeatable ways: the wrong class of method (explicit on a stiff
problem, non-symplectic over a long Hamiltonian horizon), tolerances mistaken for global error,
events stepped over, noise with the wrong amplitude or correlated streams, and numerical drift
reported as physics. Numbers marked "computed" were run in October 2026 (SciPy solve_ivp,
NumPy); API names were checked against REBOUND 5.2 and scikit-sundae 1.2.

## 1. Decision table

| Problem | SciPy `solve_ivp` | Julia OrdinaryDiffEq | JAX diffrax |
|---|---|---|---|
| Non-stiff, rtol 1e-3..1e-8 | `RK45` | `Tsit5()` | `Tsit5()` |
| Smooth, high accuracy (≤ 1e-9) | `DOP853` | `Vern9()` (or `Vern7()`) | `Dopri8()` |
| Stiff (chemistry, circuits, semi-discrete diffusion) | `BDF`, `Radau`, `LSODA` (auto-switch) | `Rodas5P()` small/medium, `FBDF()` large, `KenCarp4()` IMEX splits | `Kvaerno5()` |
| Hamiltonian, long horizon | hand-written velocity Verlet or Yoshida4 (section 2) | `VelocityVerlet()`, `McAte5()`, `Yoshida6()`, `KahanLi8()` (fixed dt) | — |
| Constrained mechanics | SHAKE/RATTLE (hand-written) | `DAEProblem` + `IDA()`, or mass-matrix ODE + `Rodas5P()` | — |
| SDE / Langevin | Euler-Maruyama, Milstein, BAOAB (section 9) | StochasticDiffEq `EM()` and higher-order SRK | `Euler()`/`Heun()` + Brownian path |
| Gravitational N-body | — | — | REBOUND: `whfast` (near-Keplerian), `ias15` (close encounters), `mercurius` (hybrid) |

Procedure:
1. Conserved quantity needed over ≫ 1e3 periods (orbits, MD, rigid bodies, particle beams)?
   Use a fixed-step symplectic scheme and stop here.
2. Unknown stiffness: run `RK45`/`Tsit5` briefly and apply the tests in section 3, or start with
   `LSODA` / `AutoTsit5(Rosenbrock23())`.
3. Stiff: implicit method with an analytic Jacobian or a sparsity pattern; `Radau`/`Rodas5P` for
   ≲ 100 equations at tight tolerance, `BDF`/`FBDF`/CVODE for large sparse systems.
4. Discontinuities, impacts or switching: events and restarts (section 8). Noise: section 9.

## 2. Symplectic schemes

```
velocity Verlet (kick-drift-kick; order 2, symplectic, time-reversible)
  p_{1/2} = p_n − (h/2)∇V(q_n);  q_{n+1} = q_n + h p_{1/2}/m;  p_{n+1} = p_{1/2} − (h/2)∇V(q_{n+1})
Yoshida / Forest-Ruth (order 4): Verlet sub-steps of w1·h, w0·h, w1·h
  w1 = 1/(2 − 2^(1/3)) = 1.351207,  w0 = −2^(1/3)/(2 − 2^(1/3)) = −1.702414 (a backward sub-step)
```

```python
W1 = 1/(2 - 2**(1/3)); W0 = -2**(1/3)/(2 - 2**(1/3))
def verlet(q, p, F, h, force, m):           # F = force(q) carried between steps: 1 evaluation per step
    p = p + 0.5*h*F; q = q + h*p/m; F = force(q); p = p + 0.5*h*F
    return q, p, F
def yoshida4(q, p, F, h, force, m):         # 3 force evaluations per step
    for w in (W1, W0, W1):
        q, p, F = verlet(q, p, F, w*h, force, m)
    return q, p, F
```

- A symplectic method integrates a modified Hamiltonian H̃ = H + O(h^p) exactly, so the energy
  error stays bounded (oscillates) for exponentially long times while the phase error grows
  linearly. Momentum and angular momentum are conserved exactly when the force has the symmetry.
- Harmonic stability (computed from the step matrix): Verlet ωh < 2, Yoshida4 ωh < 1.573. For
  accuracy keep ωh ≲ 0.3; Verlet's frequency error is ≈ (ωh)²/24.
- Adaptive step sizes destroy symplecticity (energy drifts again). Use a Sundman time transform
  dt = g(q) ds with fixed ds (g = r or r^(3/2) for close approaches), a symmetric step-size
  controller, or a non-symplectic integrator with error at round-off (REBOUND `ias15`).
- Non-separable H(q, p): explicit splitting does not apply; use implicit midpoint or
  Gauss-Legendre collocation (`ImplicitMidpoint()`, `GaussLegendre` methods in Julia).

## 3. Explicit stability limits and stiffness

Test equation y' = λy with real λ < 0: stable when h|λ| ≤ the boundary below (computed from the
stability polynomials).

| Method | Boundary on the negative real axis |
|---|---|
| Forward Euler, RK2 (Heun, midpoint) | 2 |
| Classical RK4 | 2.785 |
| Dormand-Prince 5(4) (`RK45`) | 3.307 |
| Backward Euler, BDF2, Radau IIA, trapezoid | unbounded (A-stable); BDF3-5 are only A(α)-stable |

Stiffness tests, any one suffices:
- Steady-state step size h with h·|λ_max| ≈ the boundary (3.3 for `RK45`; section 10 shows it).
- Jacobian eigenvalues along the trajectory spanning many decades: `np.linalg.eigvals(jac(t, y))`.
- nfev grows linearly with the horizon while the solution barely changes.

Give the implicit solver derivatives: `jac=` (dense callable) for small systems, `jac_sparsity=`
for large ones (`BDF` and `Radau`; `LSODA` is dense only). Pattern for 2 species on N cells
(diffusion couples neighbours, reaction couples species in the same cell):

```python
import numpy as np
from scipy.sparse import diags, identity, kron
S = kron(identity(2), diags([1, 1, 1], [-1, 0, 1], shape=(N, N))) + kron(np.ones((2, 2)), identity(N))
sol = solve_ivp(f, (0, T), y0, method="BDF", jac_sparsity=S, rtol=1e-6, atol=1e-9)
```

## 4. Tolerance discipline

```python
from scipy.integrate import solve_ivp
sol = solve_ivp(f, (0, T), y0, method="DOP853", rtol=1e-10, atol=1e-12)
ref = solve_ivp(f, (0, T), y0, method="DOP853", rtol=1e-12, atol=1e-14)
err = np.abs(sol.y[:, -1] - ref.y[:, -1])      # must shrink ~100x per 100x tolerance cut
```

Computed on the Kepler orbit (e = 0.5, 10 orbits, exact answer = initial state):

| rtol / atol | error vs exact | change vs previous run | nfev |
|---|---|---|---|
| 1e-8 / 1e-10 | 4.97e-5 | — | 3,590 |
| 1e-10 / 1e-12 | 3.51e-7 | 4.93e-5 | 6,194 |
| 1e-12 / 1e-14 | 2.42e-9 | 3.48e-7 | 9,098 |

The ~140× shrink per step shows the asymptotic regime, and the change between two runs is a usable
error estimate for the looser one. Rules:
- Set `atol` per component: atol_i ≈ rtol × the smallest magnitude of y_i that matters
  (Robertson below uses atol = [1e-8, 1e-12, 1e-8] because y₂ ~ 1e-5). Nondimensionalise first
  (`dimensional-analysis-units`).
- Global error is not bounded by rtol: it accumulates (∝ T for periodic motion, ∝ e^(λT) for
  chaotic motion, where only statistics survive past the Lyapunov time).
- The dense-output interpolant is less accurate than the steps; use it only at tight tolerance.

## 5. Tool snippets (2026)

```python
# SciPy: stiff with analytic Jacobian (rob, rjac in section 10); sol.nfev, sol.njev, sol.nlu report the cost
sol = solve_ivp(rob, (0, 1e5), [1, 0, 0], method="Radau", jac=rjac, rtol=1e-6, atol=[1e-8, 1e-12, 1e-8])
# JAX diffrax: stiff solve, differentiable through args (default adjoint RecursiveCheckpointAdjoint)
import jax, jax.numpy as jnp, diffrax
jax.config.update("jax_enable_x64", True)               # stiff solves need float64
def f(t, y, k):
    return jnp.array([-k[0]*y[0] + k[2]*y[1]*y[2], k[0]*y[0] - k[2]*y[1]*y[2] - k[1]*y[1]**2, k[1]*y[1]**2])
sol = diffrax.diffeqsolve(diffrax.ODETerm(f), diffrax.Kvaerno5(), t0=0.0, t1=1e5, dt0=1e-6,
                          y0=jnp.array([1.0, 0.0, 0.0]), args=jnp.array([0.04, 3e7, 1e4]),
                          stepsize_controller=diffrax.PIDController(rtol=1e-6, atol=1e-10), max_steps=100_000)
# REBOUND (5.x): WHFast for near-Keplerian systems; ias15 for close encounters
import rebound
sim = rebound.Simulation(); sim.add(m=1.0); sim.add(m=1e-3, a=1.0, e=0.05)
sim.integrator = "whfast"; sim.dt = 2*np.pi/50; sim.move_to_com()
E0 = sim.energy(); sim.integrate(2*np.pi*1e4); print(abs(sim.energy()/E0 - 1))
```

```julia
using OrdinaryDiffEq, Sundials
function rober!(du, u, k, t)
    du[1] = -k[1]*u[1] + k[3]*u[2]*u[3]
    du[2] =  k[1]*u[1] - k[3]*u[2]*u[3] - k[2]*u[2]^2
    du[3] =  k[2]*u[2]^2
end
prob = ODEProblem(rober!, [1.0, 0.0, 0.0], (0.0, 1e5), [0.04, 3e7, 1e4])
sol = solve(prob, Rodas5P(); reltol=1e-8, abstol=1e-10)            # FBDF() for large systems
sol = solve(prob, CVODE_BDF())          # SUNDIALS via Sundials.jl; linear_solver = :GMRES for large sparse
# Kepler, fixed-step symplectic: f1 gives dv (acceleration), f2 gives dq = v
acc!(dv, v, q, par, t) = (dv .= -q ./ sum(abs2, q)^1.5)
vel!(dq, v, q, par, t) = (dq .= v)
kep = DynamicalODEProblem(acc!, vel!, [0.0, sqrt(3.0)], [0.5, 0.0], (0.0, 2pi*1000))
sol = solve(kep, KahanLi8(); dt = 0.01)                             # or McAte5(), VelocityVerlet()
# DAE with an algebraic constraint (index 1): residual form for IDA
function res!(r, du, u, k, t)
    r[1] = -0.04u[1] + 1e4*u[2]*u[3] - du[1]
    r[2] =  0.04u[1] - 1e4*u[2]*u[3] - 3e7*u[2]^2 - du[2]
    r[3] =  u[1] + u[2] + u[3] - 1.0
end
dae = DAEProblem(res!, [-0.04, 0.04, 0.0], [1.0, 0.0, 0.0], (0.0, 1e5); differential_vars = [true, true, false])
sol = solve(dae, IDA())
```

Python SUNDIALS: scikit-sundae exposes `sksundae.cvode.CVODE(rhsfn, **options)` and
`sksundae.ida.IDA(resfn, **options)` with a `.solve(...)` method; its callbacks fill an output
array in place (check the option names in its docs).

## 6. Kepler benchmark (computed)

GM = 1, a = 1, e = 0.5, period 2π, dt = 0.01 (628 steps per orbit), relative energy error |ΔE/E|:

| Method | Force evaluations per orbit | 10 orbits | 100 orbits | 1000 orbits |
|---|---|---|---|---|
| Velocity Verlet, dt = 0.01 | 628 | max 2.72e-4 | max 2.72e-4 | max 2.72e-4 (bounded) |
| RK4, dt = 0.01 | 2513 | 3.03e-8 | 3.03e-7 | 3.03e-6 (linear drift) |
| Velocity Verlet, dt = 0.0025 (RK4's cost) | 2513 | max 1.70e-5 | max 1.70e-5 | max 1.70e-5 |

At equal cost RK4 is more accurate until 3.03e-9 × N = 1.70e-5, i.e. N ≈ 5,600 orbits; Verlet
wins beyond. Choose by horizon and required accuracy; for both, use a 4th-order symplectic
scheme. Observed orders from 200/400/800 steps per orbit: Verlet 2.00, RK4 4.23.

```python
import math
e = 0.5
def init(): return 1 - e, 0.0, 0.0, math.sqrt((1 + e)/(1 - e))
def acc(x, y): r3 = (x*x + y*y)**1.5; return -x/r3, -y/r3
def energy(x, y, px, py): return 0.5*(px*px + py*py) - 1/math.hypot(x, y)
def verlet(dt, n):
    x, y, px, py = init(); E0 = energy(x, y, px, py); ax, ay = acc(x, y); emax = 0.0
    for _ in range(n):
        px += 0.5*dt*ax; py += 0.5*dt*ay; x += dt*px; y += dt*py
        ax, ay = acc(x, y); px += 0.5*dt*ax; py += 0.5*dt*ay
        emax = max(emax, abs(energy(x, y, px, py)/E0 - 1))
    return emax
def rk4(dt, n):
    x, y, px, py = init(); E0 = energy(x, y, px, py); h = dt
    for _ in range(n):
        a1x, a1y = acc(x, y)
        x2, y2, px2, py2 = x + h/2*px, y + h/2*py, px + h/2*a1x, py + h/2*a1y; a2x, a2y = acc(x2, y2)
        x3, y3, px3, py3 = x + h/2*px2, y + h/2*py2, px + h/2*a2x, py + h/2*a2y; a3x, a3y = acc(x3, y3)
        x4, y4, px4, py4 = x + h*px3, y + h*py3, px + h*a3x, py + h*a3y; a4x, a4y = acc(x4, y4)
        x += h/6*(px + 2*px2 + 2*px3 + px4); y += h/6*(py + 2*py2 + 2*py3 + py4)
        px += h/6*(a1x + 2*a2x + 2*a3x + a4x); py += h/6*(a1y + 2*a2y + 2*a3y + a4y)
    return abs(energy(x, y, px, py)/E0 - 1)
for orbits in (10, 100, 1000):
    n = round(orbits*2*math.pi/0.01)
    print(orbits, verlet(0.01, n), rk4(0.01, n), verlet(0.0025, 4*n))    # ~2 s in CPython 3.13
```

## 7. Diagnostics

- Relative energy error vs t on log axes: a flat band is a healthy symplectic run; linear growth
  means a non-symplectic or adaptive integrator, or a non-conservative force (cutoff jumps); √t
  growth is round-off random walk; sudden jumps are close encounters (regularise or adapt).
- Angular momentum must be exact to round-off for central forces under Verlet.
- Time reversal: integrate N steps, negate p, integrate N steps; the start must be recovered to
  round-off (amplified by e^(λT) in chaotic systems).
- Observed order from h, h/2, h/4 at the same final time (pick h = T/N):

```python
def observed_order(run, N):          # run(N) -> final state after N steps over a fixed T
    f1, f2, f3 = run(N), run(2*N), run(4*N)
    return np.log2(np.linalg.norm(f1 - f2)/np.linalg.norm(f2 - f3))
```

## 8. Events and discontinuities

```python
def ball(t, y): return [y[1], -9.81]
def ground(t, y): return y[0]
ground.terminal, ground.direction = True, -1          # stop only when falling through 0
t0, y, e_rest, impacts = 0.0, [1.0, 0.0], 0.8, []
while t0 < 5.0 and len(impacts) < 50:
    sol = solve_ivp(ball, (t0, 5.0), y, events=ground, rtol=1e-10, atol=1e-12)
    if sol.status != 1: break                         # reached t = 5 without an impact
    t0 = sol.t_events[0][0]; impacts.append(t0)       # first impact at sqrt(2/9.81) = 0.4515 s
    y = [0.0, -e_rest*sol.y_events[0][0][1]]          # impact map, then restart
```

- At a kink or jump in f (contact, friction, switching, piecewise forcing) stop on an event and
  restart; a high-order method stepping across silently drops to order 1 and the controller
  thrashes. Known switch times go into the time span (SciPy) or `tstops` (Julia).
- Event location uses the dense interpolant: at loose tolerance the crossing time inherits its
  error. Tighten rtol or refine the root on the true solution.
- Julia: `ContinuousCallback(condition, affect!)`, `VectorContinuousCallback`, `DiscreteCallback`.
- Zeno behaviour (infinitely many impacts in finite time) needs an explicit stop rule.

## 9. Stochastic and Langevin integrators

- Euler-Maruyama X_{n+1} = X_n + aΔt + bΔW, ΔW ~ N(0, Δt): strong order 0.5, weak order 1.
  Milstein adds ½bb′(ΔW² − Δt): strong order 1 (scalar or commutative noise). Computed on
  geometric Brownian motion (μ = 1.5, σ = 1, 20,000 paths, Δt = 2⁻⁴…2⁻⁸): strong-error slopes
  0.496 and 0.97.
- White-noise limits of physical coloured noise are Stratonovich; converting to Itô adds ½bb′ to
  the drift.
- Underdamped Langevin m dv = F dt − γmv dt + sqrt(2γmk_BT) dW. An Euler-Maruyama velocity kick
  has amplitude sqrt(2γk_BTΔt/m); BAOAB uses the exact Ornstein-Uhlenbeck step, which reduces to
  that for γΔt ≪ 1. Overdamped: x_{n+1} = x_n + (D/k_BT)FΔt + sqrt(2DΔt)ξ.
- BAOAB samples configurations accurately (exactly for harmonic forces) but biases the kinetic
  temperature. Computed for a harmonic oscillator, γ = ω = 1: ⟨q²⟩mω²/k_BT = 0.996, 0.997, 1.000
  while ⟨p²⟩/(mk_BT) = 0.94, 0.75, 0.44 at ωh = 0.5, 1.0, 1.5. Measure temperature from
  configurations, not velocities, at large steps.

```python
def baoab(q, p, force, m, h, gamma, kT, rng, nsteps):
    c1 = np.exp(-gamma*h); c2 = np.sqrt((1 - c1*c1)*m*kT); F = force(q)
    for _ in range(nsteps):
        p += 0.5*h*F; q += 0.5*h*p/m                       # B, A
        p = c1*p + c2*rng.standard_normal(p.shape)         # O: exact OU step
        q += 0.5*h*p/m; F = force(q); p += 0.5*h*F         # A, B
    return q, p
ss = np.random.SeedSequence(20261019)                       # record ss.entropy with the results
rngs = [np.random.default_rng(s) for s in ss.spawn(8)]      # independent streams per worker
```

## 10. Stiff worked example: Robertson kinetics (computed)

y₁′ = −0.04y₁ + 1e4·y₂y₃, y₂′ = 0.04y₁ − 1e4·y₂y₃ − 3e7·y₂², y₃′ = 3e7·y₂², y(0) = (1, 0, 0),
rtol = 1e-6, atol = [1e-8, 1e-12, 1e-8], analytic Jacobian for the implicit solvers.

```python
def rob(t, y):
    return [-0.04*y[0] + 1e4*y[1]*y[2], 0.04*y[0] - 1e4*y[1]*y[2] - 3e7*y[1]**2, 3e7*y[1]**2]
def rjac(t, y):
    return [[-0.04, 1e4*y[2], 1e4*y[1]], [0.04, -1e4*y[2] - 6e7*y[1], -1e4*y[1]], [0.0, 6e7*y[1], 0.0]]
for method, T in (("RK45", 100.0), ("Radau", 1e5), ("BDF", 1e5), ("LSODA", 1e5)):
    kw = {} if method == "RK45" else {"jac": rjac}
    sol = solve_ivp(rob, (0, T), [1, 0, 0], method=method, rtol=1e-6, atol=[1e-8, 1e-12, 1e-8], **kw)
    print(method, T, sol.nfev, len(sol.t) - 1, sol.y[:, -1])
```

| Solver | Interval | nfev | Steps | Wall time |
|---|---|---|---|---|
| RK45 | [0, 1] | 4,790 | 676 | < 0.1 s |
| RK45 | [0, 10] | 49,832 | 7,091 | 0.2 s |
| RK45 | [0, 100] | 729,326 | 104,143 | 2.4 s |
| Radau | [0, 1e5] | 1,718 (njev 99, nlu 274) | 201 | 0.02 s |
| BDF | [0, 1e5] | 1,034 (njev 12, nlu 79) | 368 | 0.02 s |
| LSODA | [0, 1e5] | 898 | 574 | < 0.01 s |

The RK45 step is set by stability, not accuracy: at every horizon h·|λ_max| = 3.30, exactly the
Dormand-Prince boundary 3.307, while the solution changes on time scales ~t. |λ_max| grows from
2.2e3 (t = 1) to 4.2e3 (t = 100) to ≈ 1e4 (t = 1e5), so RK45 on [0, 1e5] needs ~3e8 steps (hours)
for what Radau does in 201. y(1e5) = (1.7866e-2, 7.2748e-8, 0.98213): the three implicit solvers
agree to ~1e-5 relative and conserve y₁ + y₂ + y₃ = 1 to 1e-16; RK45 and Radau agree to 1e-9 at
t = 100.

## 11. Pitfalls

- Reporting RK4 (or any adaptive RK) energy drift over long runs as physical dissipation.
- Accumulating state or time in float32 (ε ≈ 6e-8): a 1e6-step run loses ~1e-2 relative
  accuracy; keep float64 and use compensated sums for time.
- atol in the wrong units: atol = 1e-6 on a quantity of size 1e-9 means it is never controlled.
- Locating events on the interpolant at loose tolerance, or letting a step jump over a short
  pulse (cap `max_step` below the pulse width).
- Stepping over a stability limit after a parameter change (stiffer spring, lighter particle,
  hotter MD run): recheck ωh and h·|λ_max| whenever parameters change.
- Comparing integrators at equal step size instead of equal force evaluations.
- Adaptive stepping wrapped around Verlet, then trusting bounded energy error.

Related: `lagrangian-hamiltonian-mechanics`, `pde-discretization-stability`, `molecular-dynamics-setup`, `statmech-monte-carlo`, `julia-sciml-diffeq`, `numerical-error-analysis`, `simulation-verification-validation`, hub `physics-toolkit`
