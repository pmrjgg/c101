# Benchmark catalogue with reference values

Each entry: set-up, reference values (with their source or how they were checked in October
2026), what a pass looks like, and the domain skill that owns the method. Values marked
"computed" were reproduced here with the stated script settings.

## 1. Kepler orbit and harmonic oscillator (`physics-ode-integrators`)

- Set-up: GM = 1, a = 1, e = 0.5; q₀ = (1 − e, 0) = (0.5, 0), p₀ = (0, sqrt((1 + e)/(1 − e))) = (0, √3).
- Exact: E = −GM/(2a) = −0.5; L = sqrt(GM·a(1 − e²)) = 0.866 03; period 2π sqrt(a³/GM) = 2π.
- Computed regression values, dt = 0.01 (≈ 628 steps per orbit): velocity Verlet keeps the
  relative energy error in a band of maximum 2.7e-4 with no growth (100 orbits checked; the hub
  run reported no growth over 1000) and conserves L to 2.7e-14. Classical RK4 drifts linearly:
  3.0e-8 after 10 orbits, 3.1e-7 after 100.
- Pass: Verlet band shrinks ×4 when dt halves (order 2) and stays flat in time; RK4 drift per orbit
  shrinks ×16 when dt halves.
- Harmonic oscillator: x(t) = x₀ cos ωt + (v₀/ω) sin ωt. Verlet is stable for ωh < 2 and its
  energy error stays bounded at O((ωh)²); phase error grows linearly in time.

## 2. Heat-equation Gaussian (`pde-discretization-stability`)

- u_t = D u_xx with u(x, 0) a normalised Gaussian of variance σ₀²: u(x, t) is Gaussian with
  σ²(t) = σ₀² + 2Dt and peak (2π(σ₀² + 2Dt))^{−1/2}.
- Computed (FTCS, r = DΔt/Δx² = 0.4, D = 1, σ₀ = 0.1, t = 0.05, domain [−3, 3]): the discrete
  variance matches σ₀² + 2Dt to 1e-15 on every grid, while the peak error falls 6.2e-3, 1.6e-3,
  3.9e-4, 9.8e-5 for N = 100…800 (order 2 at fixed r).
- Lesson: any mass-conserving three-point scheme reproduces the variance growth exactly, so a
  variance check verifies D and conservation, not the order. Measure the order on the peak or an
  L2 error against the exact profile.

## 3. Sod shock tube (`fluid-dynamics-cfd`)

- Euler equations, γ = 1.4, x ∈ [0, 1], diaphragm at 0.5; left (ρ, u, p) = (1, 0, 1), right
  (0.125, 0, 0.1); compare at t = 0.2.
- Exact Riemann solution (computed with an exact solver, Newton on the pressure function):

| Quantity | Value |
|---|---|
| p* (star pressure) | 0.30313 |
| u* (contact speed) | 0.92745 |
| ρ*_L (behind rarefaction) | 0.42632 |
| ρ*_R (behind shock) | 0.26557 |
| shock speed | 1.75216 |
| rarefaction head, tail at t = 0.2 | x = 0.26336, 0.48595 |
| contact, shock at t = 0.2 | x = 0.68549, 0.85043 |

- Pass: plateaus at the exact values, discontinuities at the exact positions, total mass, momentum
  and energy conserved to roundoff (conservative form). Expect L1 convergence of order 1 or less
  near discontinuities; formal order is unattainable there. A shock in the wrong place means a
  non-conservative discretisation.

## 4. Lid-driven cavity (`fluid-dynamics-cfd`)

- Unit square, lid u = 1 at y = 1, no slip elsewhere, Re = UL/ν.
- Ghia, Ghia and Shin (1982, J. Comput. Phys. 48, 387): tables of u along the vertical centreline
  and v along the horizontal centreline for Re = 100 to 10 000, plus vortex centres and stream
  function extrema. Re = 100 on a 129 × 129 grid: primary vortex ψ_min = −0.103 423 at
  (0.6172, 0.7344).
- Cross-check computed here: a second-order stream function-vorticity solver (Thom wall
  vorticity, pseudo-time marching) gave ψ_min = −0.102 76 at 65² and −0.103 34 at 129², centre
  (0.615, 0.738); Richardson with p = 2 gives −0.1035, bracketing the Ghia value.
- Pass: centreline profiles within ~1 % of the tables at Re ≤ 1000 on comparable grids; secondary
  corner vortices appear at the right Re. Ghia's values are themselves second-order results, so
  use spectral references (Botella and Peyret 1998) when testing high-order codes.

## 5. Two-dimensional Ising model (`statmech-monte-carlo`)

- H = −J Σ⟨ij⟩ s_i s_j on the square lattice, k_B = J = 1.
- Exact (Onsager, Yang): T_c = 2/ln(1 + √2) = 2.269 185, β_c = 0.440 687; spontaneous
  magnetisation M = (1 − sinh⁻⁴(2/T))^{1/8} for T < T_c: M(1.5) = 0.986 50, M(2.0) = 0.911 32,
  M(2.2) = 0.784 75. Internal energy per spin (infinite lattice, computed from Onsager's formula
  with the complete elliptic integral): u(2.0) = −1.745 565, u(T_c) = −√2 = −1.414 214,
  u(3.0) = −0.817 310. Exponents β = 1/8, ν = 1, γ = 7/4, α = 0 (logarithmic specific heat).
- Exact enumeration of the 4 × 4 periodic lattice (2¹⁶ states, computed), a fast unit test for a
  Metropolis or cluster code:

| T | ⟨E⟩/N | ⟨\|M\|⟩/N | C/N |
|---|---|---|---|
| 2.0 | −1.755 380 | 0.918 943 | 0.605 533 |
| 2.269 | −1.565 769 | 0.843 920 | 0.783 194 |
| 3.0 | −1.017 070 | 0.601 291 | 0.603 135 |

- Pass: MC means within k·σ (σ from blocking, k = 3) of the enumeration; near T_c expect
  critical slowing down for single-spin updates.

## 6. Rahman's liquid argon (`molecular-dynamics-setup`)

- Rahman, Phys. Rev. 136, A405 (1964): 864 Lennard-Jones particles, T = 94.4 K,
  ρ = 1.374 g/cm³; LJ parameters commonly quoted for the paper ε/k_B = 120 K, σ = 3.4 Å.
- Reduced state (computed from those numbers): ρ* = nσ³ = 0.814, T* = k_BT/ε = 0.787.
- The abstract reports that the pair correlation function and the self-diffusion constant agree
  well with experiment (D about 15 % below the measured value) and that the velocity
  autocorrelation spectrum has a broad maximum near ω ≈ 0.25 k_BT/ħ.
- Pass: g(r) first peak near 1.1σ with the liquid shell structure, velocity autocorrelation
  function with a negative dip (cage effect), D from the mean-square displacement and from the
  Green-Kubo integral agreeing with each other, NVE energy drift within the monitor target.

## 7. Mie scattering (`optics-wave-propagation`, `em-field-solvers-fdtd-fem`)

- Homogeneous sphere, relative index m, size parameter x = 2πa/λ (medium wavelength).
- Rayleigh limit: Q_sca = (8/3) x⁴ |(m² − 1)/(m² + 2)|²; m = 1.5, x = 0.1 gives 2.31e-5.
- Computed with miepython 3.3 (`miepython.efficiencies_mx(m, x)` returns qext, qsca, qback, g):

| m | x | Q_ext | Q_sca | g |
|---|---|---|---|---|
| 1.5 | 0.1 | 2.3e-5 | 2.3e-5 | 0.0020 |
| 1.5 | 1 | 0.215 098 | 0.215 098 | 0.198 942 |
| 1.5 | 10 | 2.881 999 | 2.881 999 | 0.742 913 |
| 1.5 | 1000 | 2.013 945 | 2.013 945 | 0.827 882 |
| 1.33 | 3 | 1.753 397 | 1.753 397 | 0.783 201 |

- Q_ext → 2 for x ≫ 1 (extinction paradox: diffraction removes as much as geometric blocking).
- Pass for FDTD or FEM: Q_ext within ~1 % at x ≈ 1–5 with converged mesh and absorbing boundary;
  absorbing spheres need the code's sign convention for Im m checked first.

## 8. Hydrogen and harmonic-oscillator spectra (`schrodinger-numerics`)

- Hydrogen (infinite nuclear mass, atomic units): E_n = −1/(2n²) hartree = −13.605 693 eV/n².
  Reduced-mass correction multiplies by m_p/(m_p + m_e) = 0.999 456 (E₁ = −13.598 eV).
  Degeneracy in l (2s = 2p) is a sharp test of radial grids and the centrifugal term.
- Harmonic oscillator: E_n = (n + ½)ħω; in d dimensions the level N = n₁ + … + n_d has degeneracy
  C(N + d − 1, d − 1).
- Pass: eigenvalue errors fall at the formal order of the discretisation (h² for three-point
  finite differences, exponentially for DVR or spectral bases) until the box size or the r = 0
  treatment limits them; increase the box until the result stops moving.

## 9. Exact Navier-Stokes solution: Taylor-Green vortex

- 2D periodic box [0, 2π]²: u = sin x cos y e^{−2νt}, v = −cos x sin y e^{−2νt},
  p = (ρ/4)(cos 2x + cos 2y) e^{−4νt}.
- Pass: kinetic energy decays as e^{−4νt}; velocity error converges at the formal order in space
  and time. In 3D the Taylor-Green flow transitions and has no closed form; use it only for
  dissipation-rate comparisons against published spectral data.
