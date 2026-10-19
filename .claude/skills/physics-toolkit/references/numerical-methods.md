# Numerical methods for physics

Verification vocabulary (use it in reports):
- **Code verification**: the code solves the equations it claims to, at the expected order
  (method of manufactured solutions, convergence tests).
- **Solution verification**: the numerical error of a particular result is estimated
  (grid/step refinement, Richardson, GCI).
- **Validation**: the equations describe reality for this purpose (comparison with experiment).

## 1. ODE integrators

### Symplectic schemes for H = p²/2m + V(q)

```
velocity Verlet (order 2, symplectic, time-reversible)
  p_{1/2} = p_n - (h/2) ∇V(q_n)
  q_{n+1} = q_n + h p_{1/2} / m
  p_{n+1} = p_{1/2} - (h/2) ∇V(q_{n+1})

Yoshida / Forest-Ruth order 4: three Verlet steps with sizes w1 h, w0 h, w1 h
  w1 = 1 / (2 - 2^(1/3)) ≈ 1.3512,  w0 = -2^(1/3) / (2 - 2^(1/3)) ≈ -1.7024
```

Properties: energy error bounded (oscillates, O(h^p)) for exponentially long times when h is below
the stability limit; phase error still grows linearly. Variable step sizes destroy symplecticity
unless done with time transformations (Sundman) or symmetric step-size control. Stability for a
harmonic mode of frequency ω: ω h < 2 (Verlet).

### Explicit stability limits on the negative real axis (test equation y' = λ y)

| Method | Stable for h|λ| ≤ |
|---|---|
| Forward Euler | 2 |
| RK2 (Heun, midpoint) | 2 |
| RK4 (classical) | ≈ 2.785 |
| Dormand-Prince 5(4) | ≈ 3.3 |
| Backward Euler, BDF2, Radau IIA | unbounded (A-stable) |

Stiffness diagnosis: an explicit adaptive solver takes far more steps than the solution's visible
time scale needs, or the Jacobian has eigenvalues spanning many orders of magnitude.
`solve_ivp(..., method="LSODA")` switches automatically; for large stiff systems give the Jacobian
(or its sparsity pattern via `jac_sparsity`).

### Tolerance discipline (scipy)

```python
from scipy.integrate import solve_ivp
sol = solve_ivp(f, (0, T), y0, method="DOP853", rtol=1e-10, atol=1e-12, dense_output=True)
ref = solve_ivp(f, (0, T), y0, method="DOP853", rtol=1e-12, atol=1e-14)
err = abs(sol.y[:, -1] - ref.y[:, -1])        # tolerance-reduction check: should shrink ~100x
```

Set `atol` per component when scales differ (e.g. positions in m, concentrations in mol/L).
Global error is not bounded by `rtol`; it accumulates. Always do the tolerance-reduction check.

### Kepler test (used in SKILL.md section 6)

```python
import math
def acc(q):
    r = math.hypot(*q); return (-q[0]/r**3, -q[1]/r**3)
def energy(q, p): return 0.5*(p[0]**2 + p[1]**2) - 1/math.hypot(*q)
e = 0.5; q = [1 - e, 0.0]; p = [0.0, math.sqrt((1 + e)/(1 - e))]   # GM = 1, a = 1, period 2π
E0, dt = energy(q, p), 0.01
a = acc(q)
for _ in range(int(round(1000*2*math.pi/dt))):                      # 1000 orbits
    p = [p[i] + 0.5*dt*a[i] for i in (0, 1)]
    q = [q[i] + dt*p[i] for i in (0, 1)]
    a = acc(q)
    p = [p[i] + 0.5*dt*a[i] for i in (0, 1)]
print(abs(energy(q, p) - E0)/abs(E0))
```

Diagnostics for any orbit/MD code: relative energy error vs time on log axes (flat band =
symplectic healthy; linear growth = non-symplectic or bug; sudden jump = close encounter, needs
regularisation or adaptive time steps), angular momentum (should be exact to roundoff for central
forces with Verlet), and time-reversal test (integrate forward then backward, return to start).

## 2. PDEs

| Equation type | Default scheme | Stability / accuracy notes |
|---|---|---|
| Diffusion u_t = D u_xx | Crank-Nicolson (2nd order) or BDF2; FTCS only for quick checks | FTCS: r = DΔt/Δx² ≤ 1/2 (1D) |
| Advection u_t + c u_x = 0 | upwind (1st), Lax-Wendroff (2nd, oscillates), high-resolution TVD/WENO | CFL ν = |c|Δt/Δx ≤ 1 |
| Conservation laws with shocks | finite volume + approximate Riemann solver (Roe, HLLC) + limiter | conservative form required (Lax-Wendroff theorem) |
| Wave u_tt = c² u_xx | leapfrog in time, centred space | CFL ≤ 1 |
| Poisson / Laplace | multigrid, FFT (periodic/rectangular), CG + AMG | check residual reduction per cycle (~0.1 for good multigrid) |
| Schrödinger i u_t = H u | Crank-Nicolson (unitary), split-step Fourier | preserve norm to roundoff |
| Smooth periodic problems | pseudo-spectral (FFT) | exponential convergence; dealias with the 2/3 rule for quadratic nonlinearities |
| Complex geometry | finite elements (FEniCSx, deal.II, MFEM) | element order, mesh quality (aspect ratio) |

Von Neumann analysis: substitute u_j^n = G^n e^{ikjΔx}; require |G| ≤ 1 for all k. Example FTCS
diffusion: G = 1 - 4r sin²(kΔx/2) → |G| ≤ 1 iff r ≤ 1/2.

Lax equivalence: for a consistent scheme for a well-posed linear problem, stability ⇔ convergence.

### Method of manufactured solutions (MMS)

1. Choose a smooth u*(x, t) that exercises all terms (e.g. sin(πx) e^{-t} + x²).
2. Compute the source S = L[u*] symbolically (SymPy) and add it to the solver's right-hand side;
   set boundary/initial data from u*.
3. Run on 3-4 grids; error ‖u_h - u*‖ must decrease at the theoretical order. Anything else is a
   bug (boundary conditions are the usual culprit).

### Grid convergence index (Roache)

With grids refined by ratio r and observed order p, fine-grid result f₁, medium f₂:

```
GCI_fine = F_s |(f₂ - f₁)/f₁| / (r^p - 1),   F_s = 1.25 with ≥ 3 grids, 3.0 with 2 grids
```

Report GCI as the relative discretisation uncertainty; confirm asymptotic range with
GCI_medium ≈ r^p GCI_fine.

## 3. Linear algebra in simulations

| System | Solver | Preconditioner |
|---|---|---|
| Small dense | LU (LAPACK) | n/a |
| Sparse SPD (diffusion, elasticity) | CG | AMG (PyAMG, hypre BoomerAMG), incomplete Cholesky |
| Sparse nonsymmetric (advection-diffusion) | GMRES(m), BiCGSTAB | ILU(k), AMG for diffusion-dominated |
| Saddle point (Stokes, constrained) | MINRES / GMRES | block preconditioners (Schur complement approximations) |
| Eigenproblems, few eigenvalues | Lanczos / Arnoldi (ARPACK via `scipy.sparse.linalg.eigsh/eigs`), LOBPCG | shift-invert for interior eigenvalues |

Stop on relative residual ‖b - Ax‖/‖b‖ below a tolerance tied to the discretisation error
(over-solving wastes time; under-solving pollutes results).

## 4. Monte Carlo

Plain MC: estimate mean ± σ/√N. Variance reduction: importance sampling (weights f/p, watch heavy
tails of the weights: effective sample size (Σw)²/Σw²), control variates, antithetic variates,
stratification, quasi-Monte Carlo for smooth low-dimensional integrands.

MCMC checklist:
- Detailed balance (or at least global balance) of the update; proposal asymmetry corrected in
  the acceptance ratio (Metropolis-Hastings).
- Thermalisation: discard burn-in judged from observable traces, not a fixed fraction.
- Autocorrelation: τ_int = 1 + 2 Σ_{t=1}^{M} ρ(t), window M the smallest with M ≥ 5 τ_int
  (Sokal); N_eff = N/τ_int.
- Blocking (Flyvbjerg-Petersen): repeatedly average adjacent pairs; the naive standard error
  rises and plateaus at the true error; no plateau means the run is too short.
- Several independent chains: Gelman-Rubin R̂ < 1.01 and bulk ESS > 400 (Vehtari et al. 2021) for
  parameter inference.
- Finite-size scaling for critical phenomena: simulate several L, fit observables to L^{x/ν}
  forms; never quote a single-L critical exponent.

```python
import numpy as np
def blocking_error(x):
    x = np.asarray(x, float); errs = []
    while len(x) >= 32:
        errs.append(x.std(ddof=1) / np.sqrt(len(x)))
        x = 0.5 * (x[: len(x)//2*2 : 2] + x[1 : len(x)//2*2 : 2])
    return errs          # look for the plateau
```

## 5. Molecular dynamics specifics

- Time step: ~1/10-1/20 of the fastest period; 1 fs with flexible bonds to hydrogen, 2 fs with
  SHAKE/RATTLE/LINCS constraints; check NVE energy drift (e.g. < ~0.01 kT per degree of freedom
  per ns as a working target) before running thermostatted production.
- Thermostats: Langevin, Nosé-Hoover chains or Bussi stochastic velocity rescaling give the
  canonical ensemble; Berendsen does not (use only for equilibration).
- Long-range electrostatics: Ewald / PME, never plain cutoffs for charged systems.
- Report: force field, ensemble, thermostat/barostat and coupling times, time step, run length
  in multiples of the slowest relevant correlation time.

## 6. Floating point

```
machine epsilon (double) 2.22e-16, single 1.19e-7, half 9.77e-4
forward difference error ≈ h|f''|/2 + 2ε|f|/h  →  h_opt ≈ 2 sqrt(ε |f/f''|)
central difference error ≈ h²|f'''|/6 + ε|f|/h  →  h_opt ≈ (3ε |f/f'''|)^(1/3)
```

- Catastrophic cancellation: 1 - cos x for small x → 2 sin²(x/2); e^x - 1 → `expm1`; log(1 + x)
  → `log1p`; quadratic roots with the stable formula; variance with Welford's algorithm, not
  E[x²] - E[x]².
- Summation: pairwise (NumPy default for contiguous arrays) or Kahan/Neumaier for long running
  sums; `math.fsum` for exact-rounded sums in Python.
- Complex-step derivative f'(x) ≈ Im f(x + ih)/h with h = 1e-20: no cancellation, machine precision
  for analytic f implemented with complex-safe operations; automatic differentiation (JAX,
  ForwardDiff.jl) for gradients in production.
