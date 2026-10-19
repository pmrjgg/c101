---
name: simulation-verification-validation
description: "Verification and validation of physics simulations: code verification by manufactured solutions and observed order, solution verification by Richardson extrapolation and GCI, error budgets, floating-point floors, conserved-quantity monitors, a benchmark catalogue, reproducibility and golden tests, and the pre-return physics sanity gate. Load before trusting, reporting or reviewing any simulated number."
when_to_use: "Reporting or reviewing a simulated number; running a grid, time-step or particle-number refinement study; computing observed order, Richardson extrapolation or GCI; writing a manufactured-solution test; observed order differs from theory; energy, mass or norm drifting during a run; choosing tolerances for golden or regression tests of simulation code; a claim that a model is verified or validated."
---

# Simulation verification and validation

A simulated number carries three separable errors: the code may not solve its equations (code
verification), this run may not be converged (solution verification), and the equations may not
describe the system (validation). Name which one a claim needs before running anything; the
evidence differs and none substitutes for another.

Deep material: [MMS template and order-test harness](references/mms-template.md) |
[benchmark catalogue with reference values](references/benchmarks.md)

## 1. Vocabulary (Roache; Oberkampf and Roy; ASME V&V 10 and V&V 20)

| Activity | Question | Evidence | Fails when |
|---|---|---|---|
| Code verification | Are the equations solved correctly? | observed order = formal order on manufactured or exact solutions (section 4) | order below theory, error flat, results depend on unrelated settings |
| Solution verification | How large is the numerical error of this result? | refinement study, Richardson, GCI, iterative and statistical estimates (sections 2, 3, 5) | not asymptotic, two grids only, unconverged iterations |
| Validation | Are these the right equations for this purpose and range? | comparison with experiment, both uncertainties stated | the comparison data also tuned the model |
| Calibration | Which parameter values fit the data? | a fit with uncertainties (`uncertainty-propagation-fitting`) | reported as "validation" |

Order: code verification once per code change, solution verification per result, validation per
intended use and parameter range. A validation comparison means nothing until the numerical
error is known to be small against the comparison error. ASME V&V 10 covers computational solid
mechanics, V&V 20 CFD and heat transfer; textbooks: Roache, *Verification and Validation in
Computational Science and Engineering* (1998); Oberkampf and Roy, *Verification and Validation in
Scientific Computing* (2010).

V&V 20 validation comparison: E = S − D (simulation minus data),
u_val = sqrt(u_num² + u_input² + u_D²); the model error δ_model lies in E ± k·u_val.

| Outcome | Reading |
|---|---|
| \|E\| ≫ u_val | model error ≈ E: improve the physics, not the grid |
| \|E\| ≲ u_val | model error is hidden in the noise of this comparison; shrink u_val to learn more |
| u_num dominates u_val | refine before discussing physics |

## 2. Convergence study

1. Run three (better four) systematically refined levels h₁ < h₂ < h₃ (1 = fine) with constant
   ratio r = h₂/h₁ = h₃/h₂; Celik et al. (2008) ask for r ≥ 1.3. For unstructured meshes use
   h = (V/N)^{1/d}. Refine all discretisation parameters together (Δt with Δx at fixed Courant
   number) or study each alone with the others fine.
2. Converge iterations and statistics far below the differences you are about to form (section 5).
3. Use scalar quantities of interest (drag, peak, flux, eigenvalue, integral); point values in
   steep regions converge differently.
4. Form ε₂₁ = f₂ − f₁, ε₃₂ = f₃ − f₂, R = ε₂₁/ε₃₂:

| R | Convergence | Action |
|---|---|---|
| 0 < R < 1 | monotone | p = ln(ε₃₂/ε₂₁)/ln r; Richardson f_ext = f₁ + (f₁ − f₂)/(r^p − 1); GCI (section 3) |
| −1 < R < 0 | oscillatory: the differences change sign | not asymptotic, no p; bound the error by half the oscillation range or add levels |
| \|R\| ≥ 1 | divergent | bug, instability or wrong regime; no error estimate exists |

5. Compare p with the formal order p_th. p ≈ p_th: asymptotic range. p < p_th: coarse levels, a
   lower-order component (boundary, interface, limiter, shock) or a bug. p > p_th: error
   cancellation or too-coarse levels, not extra accuracy.
6. Report the value with discretisation, iterative, statistical and roundoff errors kept apart.

Unequal ratios and the full procedure of Celik et al. (2008, J. Fluids Eng. 130, 078001):

```python
import math
def gci(f1, f2, f3, r21, r32=None, Fs=1.25, iters=50):
    """f1 fine, f2 medium, f3 coarse; r21 = h2/h1 > 1, r32 = h3/h2 > 1."""
    r32 = r21 if r32 is None else r32
    e21, e32 = f2 - f1, f3 - f2
    R = e21/e32
    if not 0 < R < 1:
        return {"R": R, "kind": "oscillatory" if -1 < R < 0 else "divergent"}
    s = math.copysign(1, e32/e21)
    p = math.log(abs(e32/e21))/math.log(r21)
    for _ in range(iters):                          # fixed point; exact when r21 == r32
        p = abs(math.log(abs(e32/e21)) + math.log((r21**p - s)/(r32**p - s)))/math.log(r21)
    return {"R": R, "p": p, "f_ext": f1 + (f1 - f2)/(r21**p - 1),
            "gci_fine": Fs*abs(e21/f1)/(r21**p - 1), "gci_medium": Fs*abs(e32/f2)/(r32**p - 1)}
```

## 3. Grid convergence index

GCI_fine = F_s·|(f₂ − f₁)/f₁|/(r^p − 1), with F_s = 1.25 for three or more levels (observed p)
and F_s = 3.0 for two levels (assumed p). GCI_medium uses (f₃ − f₂)/f₂. Asymptotic-range check:
GCI_medium ≈ r^p·GCI_fine (ratio within a few % of 1). Report GCI as the relative discretisation
uncertainty of the fine result: "C_D = 1.338, U_num = 0.44 % (GCI, F_s = 1.25, p = 2.0)".

- When p_obs > p_th, use p_th in the GCI; the observed value would shrink the band.
- Four or more levels with scatter: least-squares fits of the error expansion (Eça and Hoekstra,
  J. Comput. Phys. 262, 104–130, 2014), which reduce to the GCI for clean data.
- GCI is an engineering band, not a guaranteed 95 % interval: a 2021 assessment of nine
  estimators on the ASME 2017 workshop cases found none that bounded the exact error 95 times in 100.

## 4. Method of manufactured solutions

1. Choose u* smooth and non-polynomial (sin and exp products) with every operator term active and
   of similar size, no symmetry that zeroes a term, and admissible values (positive densities).
2. Derive the source S = L[u*] with SymPy, `lambdify` it, add it to the right-hand side.
3. Take boundary and initial data from u*: Dirichlet values, Neumann fluxes −k ∂u*/∂n.
4. Run 3–4 levels; compute L2 and L∞ errors against u*; observed order per pair of levels.
5. Both norms must show the formal order. Repeat for each boundary type, coefficient variant and
   code path the result uses; boundary conditions are the usual culprit.

```python
import sympy as sp
x = sp.symbols("x")
u_star = sp.sin(sp.pi*x)*sp.exp(x) + x**2          # all terms active, nonzero at x = 1
k = 1 + x**2; c = 2
S = -sp.diff(k*sp.diff(u_star, x), x) + c*u_star     # source for -(k u')' + c u = S
S_f, u_f = sp.lambdify(x, S, "numpy"), sp.lambdify(x, u_star, "numpy")
```

Measured with that u* (second-order finite differences, Dirichlet at x = 1, Neumann flux at
x = 0, N = 16 → 128; full script and a 2D advection-diffusion template in
[MMS template](references/mms-template.md)):

| Neumann closure at x = 0 | L2 error | p (L2) | p (L∞) |
|---|---|---|---|
| half-cell finite volume | 5.4e-3 → 8.1e-5 | 2.04, 2.02, 2.01 | 2.00 |
| one-sided first-order flux | 7.1e-2 → 8.8e-3 | 1.01, 1.01, 1.00 | 0.96–0.99 |
| half-cell with the flux sign flipped | 1.81 → 1.72 | 0.04, 0.02, 0.01 | 0.00 |

| Observed-order signature | Likely cause |
|---|---|
| ≈ p_th in L2 and L∞ | pass |
| ≈ 0, error flat | inconsistent discretisation: wrong sign or scale in a source, flux or BC; S not added |
| ≈ 1 where 2 expected, error largest near a boundary | first-order boundary closure, one-sided flux, interface treatment |
| L2 at p_th, L∞ lower | local defect: boundary, corner, interface, singular point |
| above p_th | error cancellation, nodal superconvergence, coarse levels, or a u* that zeroes a term |
| erratic | roundoff floor, unconverged iterations, non-smooth u* |

Time-dependent problems: refine Δt and Δx together at fixed Courant number to see the combined
order, or freeze one at a tiny value to isolate the other. Exact solutions (Taylor-Green vortex,
Gaussian diffusion, Sod) complement MMS where they exist.

## 5. Error budget

| Component | Estimate | Acceptance |
|---|---|---|
| Discretisation (space, time) | GCI or Richardson from 3+ levels | stated; usually the dominant numerical term |
| Iterative (nonlinear and linear solves) | residual history; change of f between solver tolerances | 0.01–0.1 of the discretisation error; set ‖b − Ax‖/‖b‖ from it |
| Statistical (MC, MD, turbulence averages) | σ·sqrt(τ_int/N), blocking (`statmech-monte-carlo`) | below the discretisation error, or reported |
| Roundoff | precision comparison and floor estimate (section 6) | orders below everything else |
| Input parameters | sensitivities or MC over inputs (`uncertainty-propagation-fitting`) | reported separately |
| Model form | validation comparison (section 1), model ensembles | reported separately, never folded into u_num |

Report components separately, e.g. f = 1.333 (extrapolated) ± 0.006 (discretisation, GCI)
± 0.002 (statistical, 1σ) ± 0.03 (inputs, k = 2); combine only with a stated rule (RSS for
independent terms) at one coverage level, never silently. Over-solving wastes time; under-solving
leaks iterative error into the convergence study.

## 6. Roundoff floor

| Format | Machine epsilon (spacing of floats at 1) |
|---|---|
| bfloat16 | 7.8e-3 |
| float16 | 9.77e-4 |
| float32 | 1.19e-7 |
| float64 | 2.22e-16 |

- Total error E(h) ≈ C·h^p + ε·κ·h^{−q} (q = 1 for first-derivative stencils, 2 for second):
  refinement helps until the second term wins, then the error flattens or grows and p_obs
  collapses. Use only levels well above the floor.
- Accumulation over N steps: about ε√N when rounding errors are random, up to εN when biased.
- Finite-difference steps: forward error ≈ h|f″|/2 + 2ε|f|/h, h_opt ≈ 2 sqrt(ε|f/f″|) ~ sqrt(ε)|x|;
  central error ≈ h²|f‴|/6 + ε|f|/h, h_opt ≈ (3ε|f/f‴|)^{1/3} ~ ε^{1/3}|x|.
- float32 or GPU runs: keep a float64 reference for every configuration and compare the quantity
  of interest; accumulate sums in higher precision. Atomic reductions reorder sums between runs
  (PyTorch: `torch.use_deterministic_algorithms(True)` with `CUBLAS_WORKSPACE_CONFIG=:4096:8`);
  BLAS thread counts and `-ffast-math` also change results at the 1e-16 level or worse.
- Cancellation rewrites (expm1, log1p, stable quadratic roots, Welford variance), Kahan or
  pairwise summation, `math.fsum` and complex-step derivatives: `numerical-error-analysis`.

## 7. Runtime monitors

| Monitor | Healthy | Alarm |
|---|---|---|
| Energy, symplectic integrator | bounded oscillation O(h^p), no trend (Kepler e = 0.5, Verlet dt = 0.01: max 2.7e-4 over 100 orbits) | linear drift (non-symplectic or bug); jumps (close encounters) |
| Energy, dissipative system | input = stored + dissipated within tolerance | budget does not close |
| Linear and angular momentum | roundoff for symmetric forces (same Kepler run: L drifts 2.7e-14) | drift: force asymmetry, cutoffs, thermostat |
| Mass, charge (conservative finite volume) | roundoff | drift: non-conservative form, boundary leak |
| Norm (Crank-Nicolson, split-step Schrödinger) | roundoff | drift: non-unitary step, absorbing boundary |
| NVE energy in MD | < ~0.01 k_BT per degree of freedom per ns (working target, `molecular-dynamics-setup`) | larger: time step, constraints, cutoffs |
| Positivity (density, pressure, temperature, probability) | always | negative: time step, limiter, interpolation |
| Second law | entropy production ≥ 0; heat flows hot to cold | negative production |
| Causality | signals travel no faster than the largest characteristic speed | response before the cause can arrive |
| Mirror test | mirrored input gives mirrored output | asymmetric stencil, loop-order bug |
| Time reversal | N steps forward, flip velocities, N back: start state within roundoff growth | far from start in a non-chaotic system |

Log each monitor as drift divided by allowed drift and fail the run when the ratio exceeds 1.
Plot relative energy error against time on log axes: a flat band is healthy, linear growth is
drift, steps are events.

## 8. Benchmark catalogue

Reference values, set-ups and checks: [benchmarks](references/benchmarks.md).

| Benchmark | Reference | Tests | Domain skill |
|---|---|---|---|
| Kepler orbit, harmonic oscillator | E and L conserved; period 2π sqrt(a³/GM); closed-form x(t) | integrator order, symplecticity | `physics-ode-integrators` |
| Heat-equation Gaussian | σ²(t) = σ₀² + 2Dt; peak ∝ (σ₀² + 2Dt)^{−1/2} | diffusion scheme order, stability | `pde-discretization-stability` |
| Sod shock tube (γ = 1.4, t = 0.2) | p* = 0.30313, u* = 0.92745, shock at x = 0.85043 | Riemann solver, limiter, conservation | `fluid-dynamics-cfd` |
| Lid-driven cavity (Ghia, Ghia and Shin 1982) | Re = 100: ψ_min ≈ −0.1034 near (0.617, 0.734) | incompressible solver, wall BCs | `fluid-dynamics-cfd` |
| 2D Ising (Onsager) | T_c = 2.269185 J/k_B, u(T_c) = −√2 J; exact 4×4 enumeration | MC sampler, autocorrelation | `statmech-monte-carlo` |
| Rahman LJ argon (1964) | 864 atoms, 94.4 K, 1.374 g/cm³; g(r), D, velocity autocorrelation | MD integrator, force field, units | `molecular-dynamics-setup` |
| Mie scattering | m = 1.5, x = 1: Q_ext = 0.2151; Q_ext → 2 as x → ∞ | EM solvers, far-field extraction | `optics-wave-propagation`, `em-field-solvers-fdtd-fem` |
| Hydrogen, oscillator spectra | E_n = −1/(2n²) hartree; E_n = (n + ½)ħω | eigensolvers, grids, boundaries | `schrodinger-numerics` |

## 9. Reproducibility and regression

- Seeds: draw one root entropy, record it, spawn independent streams per worker.

```python
import numpy as np
ss = np.random.SeedSequence()                 # store ss.entropy in the run record
rngs = [np.random.default_rng(s) for s in ss.spawn(n_workers)]   # or default_rng(seed).spawn(n)
```

- Committed configs: every run reads a versioned config; outputs carry the git commit, config
  hash, package versions, compiler flags, hardware and thread counts.
- Locked environments: `uv lock` plus `uv sync --locked` (fails on a stale lock), Julia
  `Manifest.toml` with `Pkg.instantiate()`, conda-lock for conda stacks.
- Golden-value tests take their tolerance from the error budget, never from habit:

| Output | Tolerance |
|---|---|
| deterministic, same platform and build | bitwise, or a few ε·κ |
| deterministic across platforms, compilers or thread counts | ~10–1000 ε·κ, measured once |
| stochastic, fixed seed | tight (it is deterministic), plus seed-varied runs at k·σ_stat, k = 3–4 |
| discretised field or functional | the GCI or Richardson error of the reference |
| chaotic trajectory | none on the trajectory: compare invariants (time averages, spectra, Lyapunov exponents) |

  Lorenz check: two DOP853 runs differing only in rtol (1e-12 against 1e-11) differ by 4.5e-10 at
  t = 10, 1.6e-6 at t = 20, 3.7e-2 at t = 30 and O(10) by t = 40, while their time-averaged z agree
  to 0.08 %. A 1e-12 golden test on chaotic output tests the compiler, not the physics.
- Differential tests: an independent implementation (other method, language or author) must agree
  within the combined error budgets.
- Generic test design (fixtures, property-based tests, flaky-test policy): `testing-strategy`.

```python
def test_drag_regression():                   # run_case: the project's own driver
    cd = run_case("configs/case_a.toml").drag_coefficient
    # reference 1.338: GCI_fine 0.44 %, statistical 0.1 % (1 sigma) taken at k = 3
    assert abs(cd - 1.338) <= 1.338*np.hypot(0.0044, 3*0.001)
```

## 10. Sanity gate (run before returning any physics result)

- [ ] Dimensions of every equation and of the final result checked explicitly.
- [ ] At least two limiting cases reproduce known results (`dimensional-analysis-units`).
- [ ] Signs and monotonic dependencies are physically sensible.
- [ ] The order of magnitude matches a Fermi estimate within ×10, or the gap is explained.
- [ ] Conserved quantities are conserved, analytically or to a stated tolerance (section 7).
- [ ] Every smallness parameter is evaluated at the actual numbers.
- [ ] Numerical results have a convergence study with p_obs ≈ p_th and a separate error budget
      (discretisation, iterative, statistical, roundoff, input, model).
- [ ] Constants are sourced (library and CODATA vintage) and every number carries units.
- [ ] Second law, causality and positivity of probabilities, densities and temperatures hold.

## 11. Worked example: drag coefficient on three grids

Levels refined by r = 2: f₁ = 1.338 (fine), f₂ = 1.352, f₃ = 1.408.

1. ε₂₁ = 0.014, ε₃₂ = 0.056, R = 0.25: monotone convergence.
2. p = ln(0.056/0.014)/ln 2 = 2.00, the formal order of a second-order scheme.
3. Richardson: f_ext = 1.338 + (1.338 − 1.352)/(2² − 1) = 1.3333 (f₁ is 0.35 % above it).
4. GCI_fine = 1.25 × (0.014/1.338)/3 = 0.436 %; GCI_medium = 1.25 × (0.056/1.352)/3 = 1.726 %.
5. Asymptotic check: GCI_medium/(r^p·GCI_fine) = 1.726/(4 × 0.436) = 0.990 ≈ 1, so the levels are
   in the asymptotic range.
6. Report C_D = 1.338 ± 0.006 (discretisation, GCI, F_s = 1.25, p = 2.0), extrapolated 1.333.
   `gci(1.338, 1.352, 1.408, 2.0)` returns these numbers. With r = 1.5 the same three values give
   p = 3.42, above the formal order of a second-order scheme: suspect, not better.

## 12. Pitfalls

- **Convergence claimed from two grids.** Two levels fix neither p nor the asymptotic range; if
  that is all there is, use F_s = 3 with an assumed p and say so.
- **Residual drop taken as solution convergence.** Iterative convergence on one grid says nothing
  about the discretisation error.
- **Observed order above theory** read as good news: usually cancellation between error terms of
  opposite sign or levels too coarse; refine further and put p_th in the GCI.
- **Validation against the calibration data.** Agreement with the data that tuned the parameters
  is circular; hold out data or regimes.
- **Oscillatory convergence** pushed through the monotone formula (the log of a negative ratio).
- **One parameter refined, the other frozen** (Δx refined at fixed Δt): the frozen error floors
  the study and fakes a low order.
- **Golden tolerances from habit:** 1e-12 on chaotic or stochastic output, or 1 % with no budget.
- **Quantities of interest that never converge** (peaks at singularities, point probes in shear
  layers); use integral or smoothed functionals.

Related: `uncertainty-propagation-fitting`, `dimensional-analysis-units`, `physics-ode-integrators`,
`pde-discretization-stability`, `statmech-monte-carlo`, `numerical-error-analysis`,
`testing-strategy`, hub `physics-toolkit`.
