---
name: physics-toolkit
description: "Physics working pack: dimensional analysis and Buckingham pi, nondimensionalisation and scaling, limiting cases and order-of-magnitude estimates, conservation laws and symmetries (Noether, virial), perturbation theory (regular, singular, secular, quantum), variational methods, numerical methods with error estimates (ODE integrators incl. symplectic, PDE stability, Monte Carlo with autocorrelation, Richardson extrapolation), units and CODATA constants handling, and a pre-return sanity-check gate. Load for any physics derivation, model, estimate or simulation."
when_to_use: "Deriving or checking a physical formula, building or reviewing a simulation, estimating magnitudes, choosing an integrator or discretisation, converting units, judging whether a numerical result is converged, or auditing another agent's physics."
---

# Physics toolkit

Physics answers fail in four repeatable ways: wrong dimensions, wrong regime (a formula used
outside its validity), unconverged numerics presented as results, and unit/constant slips.
This skill puts a check against each in the path of every derivation and simulation.

## 0. Workflow

1. **Regime.** List the scales (lengths, times, energies, velocities) and form the dimensionless
   ratios (section 1). Decide: classical or quantum (ħ vs action), relativistic (v/c), continuum
   (Knudsen number), equilibrium or not, linear or not.
2. **Model.** Write governing equations with every assumption numbered (A1: incompressible,
   A2: small angle ...). Each assumption gets a dimensionless smallness parameter.
3. **Estimate first.** Order-of-magnitude answer from scaling before any detailed solution.
4. **Solve** analytically, perturbatively, variationally or numerically (sections 4-6).
5. **Check** dimensions, limits, symmetries, conservation, known special cases (sections 1-3;
   run the gate in section 8).
6. **Report** value ± uncertainty with units, validity range of every assumption, and how the
   uncertainty was obtained.

## 1. Dimensional analysis

Buckingham π: n variables involving k independent base dimensions → n - k independent
dimensionless groups; the physical law is a relation among them.

Procedure: (1) list all relevant variables including dimensional constants (g, ħ, c, k_B, G);
(2) dimension matrix (rows M, L, T, Θ, I...; columns variables); (3) rank k; (4) choose k
repeating variables spanning the dimensions; (5) form π groups; (6) write π₁ = Φ(π₂, ...).

Worked: pendulum period T depends on L, g, m, θ₀. Dimensions: T [T], L [L], g [L T⁻²], m [M],
θ₀ [1]. n = 5, k = 3 → 2 groups: T sqrt(g/L) and θ₀; m cannot appear (no other mass to cancel it).
So T = sqrt(L/g) Φ(θ₀). Small angle: Φ(0) = 2π. Large angle series:
T = 2π sqrt(L/g) (1 + θ₀²/16 + 11θ₀⁴/3072 + ...) (θ₀ = 30° → +1.7%).

Dimensionless numbers that decide the regime (more in [constants and scales](references/constants-and-scales.md)):

| Number | Definition | Meaning | Regime boundaries |
|---|---|---|---|
| Reynolds | ρ v L/μ | inertia / viscosity | pipe laminar < ~2300; Stokes flow ≪ 1 |
| Mach | v/c_s | compressibility | incompressible below ~0.3 |
| Froude | v/sqrt(g L) | inertia / gravity | hull speed, open-channel flow ~1 |
| Knudsen | λ_mfp / L | continuum validity | continuum < 0.01; free molecular > 10 |
| Péclet | v L / D | advection / diffusion | > 1 advection-dominated |
| Prandtl | ν/α | momentum / thermal diffusivity | air ≈ 0.71, water ≈ 7 |
| Biot | h L / k_solid | surface / internal heat resistance | < 0.1 lumped capacitance valid |
| Strouhal | f L / v | vortex shedding | ≈ 0.2 for cylinders over a broad Re range |
| v/c, γ | Lorentz factor | relativity | corrections ~ (v/c)²/2 |
| Action / ħ | S/ħ | quantum vs classical | ≫ 1 classical |
| k_B T / ħω | thermal vs quantum energy | equipartition validity | ≫ 1 classical equipartition |
| Fine-structure α | e²/(4πε₀ħc) ≈ 1/137.036 | EM coupling | perturbation parameter in QED |

Nondimensionalise equations to expose small parameters: scale x = L x̃, t = τ t̃ with τ chosen from
the dominant balance; coefficients that become ε ≪ 1 tell you which terms to drop and whether the
limit is regular (drop safely) or singular (ε multiplies the highest derivative → boundary layer).

## 2. Limiting cases and estimates

Every derived formula must reduce correctly in the limits that apply:
- Parameter → 0 or ∞ (mass ratio, coupling, damping, temperature, frequency).
- Known special cases (circle for ellipse e → 0, hydrogen for Z = 1, free particle for V → 0).
- Classical limit ħ → 0; nonrelativistic c → ∞; ideal gas at low density; linear response at
  small drive.
- Symmetric configurations (equal masses, isotropic media) where the answer must be symmetric.
- Sign and monotonicity: does the result increase with the parameter as physics demands?

Fermi estimate pattern: write the target as a product of factors each known to within ×3; keep
one significant figure; the log-error of the product grows like sqrt(number of factors).
Example anchors: water 1000 kg/m³, air 1.2 kg/m³, atmospheric pressure 1e5 Pa, solar constant
1361 W/m², human power ~100 W, bond energies ~1-10 eV, k_B T at 300 K = 25.9 meV.

## 3. Conservation laws and symmetries

| Symmetry (Noether) | Conserved quantity | Breaks when |
|---|---|---|
| Time translation | energy (Hamiltonian if ∂L/∂t = 0) | time-dependent drive, dissipation |
| Space translation | linear momentum | external potential with gradients |
| Rotation | angular momentum | non-central forces, anisotropy |
| Galilean / Lorentz boost | centre-of-mass motion | external forces |
| U(1) phase | charge, particle number | particle-number-violating terms |
| Scaling (V ∝ r^n) | virial: 2⟨T⟩ = n⟨V⟩ for bound motion | non-power-law potentials |

Use them twice: to reduce the problem (cyclic coordinates, centre-of-mass frame, angular
momentum barrier) and to check the answer (simulations must conserve these to integrator
tolerance, section 6). Adiabatic invariants (∮ p dq) are conserved under slow parameter change:
check time scale separation first. Dissipative systems: check the energy budget instead
(input = stored + dissipated).

## 4. Perturbation theory

| Situation | Method | Validity check |
|---|---|---|
| Small ε, solution analytic in ε | regular expansion x = x₀ + ε x₁ + ... | next term ≪ current term over the whole domain |
| Secular terms (t sin t growth) in oscillators | Poincaré-Lindstedt, multiple scales (two-timing) | expansion uniform for t ~ 1/ε |
| ε multiplies highest derivative | matched asymptotics, boundary layers of width ε^a | inner and outer solutions match in the overlap |
| Slowly varying wave / large quantum numbers | WKB: ψ ≈ p^(-1/2) exp(±(i/ħ)∫p dx) | |dλ/dx| ≪ 2π, i.e. |ħ p'/p²| ≪ 1; connection formulas at turning points |
| Quantum, nondegenerate | E_n⁽¹⁾ = ⟨n|V|n⟩, E_n⁽²⁾ = Σ_{m≠n} |⟨m|V|n⟩|²/(E_n - E_m) | |⟨m|V|n⟩| ≪ |E_n - E_m| |
| Quantum, degenerate | diagonalise V within the degenerate subspace first | splitting ≫ coupling to other levels |
| Transitions | Fermi golden rule Γ = (2π/ħ)|V_fi|² ρ(E_f) | continuum final states, t ≫ ħ/ΔE, Γ t ≪ 1 depletion |
| Asymptotic (divergent) series | optimal truncation at the smallest term | error ~ smallest term |

Second-order energy shift of the ground state is always negative (each term has E_0 - E_m < 0);
use it as a sign check.

## 5. Variational methods

- Rayleigh-Ritz: E₀ ≤ ⟨ψ|H|ψ⟩/⟨ψ|ψ⟩ for any trial ψ in the domain of H. Linear trial spaces give
  upper bounds to the lowest k eigenvalues (Hylleraas-Undheim/MacDonald).
- Classical: Hamilton's principle δS = 0 gives Euler-Lagrange equations; Ritz/Galerkin for
  boundary-value problems; minimum potential energy in elasticity.
- Hellmann-Feynman: dE/dλ = ⟨∂H/∂λ⟩ for exact eigenstates (and fully variational trial states).

Worked: hydrogen ground state with Gaussian trial ψ = exp(-a r²), atomic units.
E(a) = 3a/2 - 2 sqrt(2a/π). dE/da = 0 → a = 8/(9π); E_min = -4/(3π) = -0.4244 Ha = -11.55 eV,
versus exact -0.5 Ha = -13.606 eV (15% above, as required for an upper bound). The error is the
wrong cusp and tail of a Gaussian; a sum of 3-4 Gaussians (STO-3G style) gets within ~1%.

## 6. Numerical methods (details: [numerical methods](references/numerical-methods.md))

ODE integrator choice:

| Problem | Integrator | Why |
|---|---|---|
| Smooth, non-stiff, moderate accuracy | adaptive RK45 (Dormand-Prince), `scipy.integrate.solve_ivp(method="RK45")` | error control |
| High accuracy, smooth | DOP853, or Taylor / extrapolation | high order |
| Stiff (widely separated time scales, chemistry, circuits) | BDF, Radau, LSODA (auto-switch) | explicit methods need dt < 2/|λ_max| |
| Hamiltonian, long times (orbits, MD) | symplectic: velocity Verlet / leapfrog (order 2), Yoshida/Forest-Ruth (order 4) | bounded energy error, no secular drift |
| Constrained mechanics | SHAKE/RATTLE, DAE solvers (IDA) | preserve constraints |
| Stochastic | Euler-Maruyama (strong order 0.5), Milstein (1.0); BAOAB for Langevin | correct invariant measure |

Worked comparison (computed here, pure Python): Kepler orbit e = 0.5, dt = 0.01 (≈ 628 steps per
orbit). Velocity Verlet relative energy error oscillates with a fixed maximum 2.7e-4 and does not
grow over 1000 orbits. RK4 drifts linearly: 3.0e-8 after 10 orbits, 3.0e-7 after 100, 3.0e-6 after
1000. At equal force evaluations (Verlet with dt/4) the Verlet bound is 1.7e-5, so RK4 is more
accurate up to ~5,600 orbits and Verlet wins beyond. Choose by horizon and accuracy, not by slogan;
for long-horizon problems use a 4th-order symplectic scheme to get both.

PDE stability and accuracy rules:
- Explicit advection: CFL |c| Δt/Δx ≤ 1 (1D upwind). Explicit diffusion (FTCS):
  D Δt/Δx² ≤ 1/2 in 1D, ≤ 1/(2d) in d dimensions. Violations blow up as checkerboards.
- Crank-Nicolson is unconditionally stable for diffusion but rings for large D Δt/Δx² with
  discontinuous data; use a few implicit Euler steps first (Rannacher start-up).
- Hyperbolic with shocks: finite volume, Godunov-type fluxes, slope limiters (minmod, MC);
  conservation form or shocks travel at the wrong speed.
- Elliptic: multigrid or preconditioned CG; check residual reduction, not iteration count.

Monte Carlo error: σ/sqrt(N) for independent samples. Correlated (MCMC) samples:
N_eff = N/τ, τ = 1 + 2 Σ_{t≥1} ρ(t) (integrated autocorrelation time, truncated with an automatic
window); error = σ sqrt(τ/N). Estimate τ by blocking (Flyvbjerg-Petersen: block sizes 2^k until
the error estimate plateaus). Random-walk Metropolis: tune step to ~0.44 acceptance in 1D, ~0.234
in high dimension. Near critical points τ diverges (critical slowing down): use cluster updates
(Wolff, Swendsen-Wang) for spin models.

Convergence study (mandatory for any reported numerical value):
1. Run at h, h/2, h/4 (step, grid spacing, or 1/N).
2. Observed order p = log2(|f_h - f_{h/2}| / |f_{h/2} - f_{h/4}|); must match the method's
   theoretical order, otherwise you are not in the asymptotic regime (or there is a bug).
3. Richardson error estimate for f_{h/4}: (f_{h/4} - f_{h/2})/(2^p - 1); extrapolated value
   f_{h/4} + that estimate.
4. Report value, estimated discretisation error, statistical error and roundoff floor separately.

Floating point: finite-difference derivative step h ≈ sqrt(ε_mach)·|x| for forward differences,
ε_mach^(1/3)·|x| for central (ε_mach = 2.2e-16 in double); subtracting nearly equal numbers loses
digits; sum many small terms with Kahan or pairwise summation; never test floats with ==.

## 7. Units and constants

- Carry units through calculations in code: `pint` (Python), `astropy.units` (astronomy),
  `Unitful.jl` (Julia). Strip units only at the numerical kernel boundary, re-attach after.
- Constants: SI 2019 fixes c, h, e, k_B, N_A, Δν_Cs, K_cd exactly; everything else comes from
  CODATA (2022 is the current adjustment). Use `scipy.constants` or `astropy.constants` and record
  which CODATA vintage the library carries (print `1/scipy.constants.fine_structure`; CODATA 2022
  gives 137.035999177). Table with values: [constants and scales](references/constants-and-scales.md).
- Unit-system traps: Gaussian vs SI electromagnetism (factors of 4π and ε₀, B vs H); natural units
  (ħ = c = 1) need a dimensional restore at the end; atomic units (Hartree = 27.211386 eV, Bohr
  radius = 0.529177 Å); eV vs eV/c² vs K (1 eV ↔ 11,604.5 K); angular vs ordinary frequency
  (ω = 2πf, ħω vs hf); log bases (dB = 10 log10 for power, 20 log10 for amplitude).
- Temperatures in formulas are absolute (K); ΔT in °C equals ΔT in K.

## 8. Sanity-check gate (run before returning any physics result)

- [ ] Dimensions of every equation and of the final result check out (do it explicitly for the
      final formula).
- [ ] At least two limiting cases reproduce known results.
- [ ] Signs and monotonic dependencies are physically sensible.
- [ ] Order of magnitude matches the Fermi estimate within ~×10, or the discrepancy is explained.
- [ ] Conserved quantities are conserved (analytically, or numerically to stated tolerance).
- [ ] Every assumption has its smallness parameter evaluated for the actual numbers.
- [ ] Numerical results have a convergence study (order observed ≈ order expected) and separate
      error budget (discretisation, statistical, model).
- [ ] Constants sourced (library + CODATA year); units explicit in every reported number.
- [ ] Second law, causality, positivity of probabilities/densities/temperatures respected.

## 9. Worked example: is a lumped thermal model valid?

Question: a 2 cm aluminium sphere at 200 °C cools in still air (h ≈ 10 W/(m² K)); predict the time
to reach 50 °C. Regime: Biot = h (V/A)/k = 10 · (0.01/3) / 237 = 1.4e-4 ≪ 0.1, so the sphere is
isothermal (lumped model valid). τ = ρ c V/(h A) = 2700 · 897 · (0.01/3)/10 = 807 s. Air at
20 °C: T(t) - 20 = 180 e^(-t/τ), so 30 = 180 e^(-t/τ) → t = τ ln 6 = 1446 s ≈ 24 min.
Checks: dimensions of τ are (kg/m³)(J/(kg K))(m)/(W/(m² K)) = s; limit h → ∞ gives τ → 0;
radiation adds h_rad ≈ 4 ε σ T³ ≈ 4 · 0.1 · 5.67e-8 · (400 K)³ ≈ 1.5 W/(m² K) for oxidised
aluminium (ε ≈ 0.1), a ~15% correction: report 24 min as an upper estimate, about 21 min with
radiation, with h (natural convection, ±30%) as the dominant uncertainty.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `dimensional-analysis-units` | Dimensions, units and magnitudes: Buckingham pi and nondimensionalisation, regime-deciding dimensionless numbers, scaling laws, Fermi estimates, limiting cas... |
| `em-field-solvers-fdtd-fem` | Electromagnetics problem solving and field solvers: Maxwell in media, interface conditions, skin depth, waveguide and cavity formulas, SI/Gaussian translatio... |
| `fluid-dynamics-cfd` | modelling a flow or heat-transfer problem or setting up or reviewing a CFD case |
| `lagrangian-hamiltonian-mechanics` | deriving or checking classical dynamics |
| `molecular-dynamics-setup` | building, running or reviewing an MD simulation |
| `optics-wave-propagation` | designing, estimating or simulating an optical system or wave field |
| `pde-discretization-stability` | building or debugging a grid-based PDE solver |
| `physics-ode-integrators` | writing or debugging a time integrator |
| `quantum-mechanics-methods` | solving or checking a QM problem by hand or with SymPy |
| `relativity-calculations` | doing relativistic kinematics or general-relativity computations |
| `schrodinger-numerics` | a QM problem needs a computer |
| `simulation-verification-validation` | Verification and validation of physics simulations: code verification by manufactured solutions and observed order, solution verification by Richardson extra... |
| `statmech-monte-carlo` | sampling a physical system or judging MC error bars |
| `tight-binding-band-structure` | building or interpreting band structures or topological lattice models |
| `uncertainty-propagation-fitting` | a result needs an error bar or a model must be fit to data |
