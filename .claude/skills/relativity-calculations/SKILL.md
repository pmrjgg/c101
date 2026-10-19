---
name: relativity-calculations
description: "Special and general relativity calculations covering conventions, Lorentz transformations, four-vectors, invariants, thresholds and two-body decays, Doppler and aberration, metrics, Christoffel symbols and geodesics in SymPy, Schwarzschild orbits, ISCO, precession and light bending, gravitational redshift and GPS clock corrections, and numerical geodesics. Load when doing relativistic kinematics or general-relativity computations."
when_to_use: "Lorentz boosts, rapidities and velocity addition; invariant mass, threshold energies or two-body decay momenta; relativistic Doppler and aberration; Christoffel symbols, Ricci tensors or geodesic equations from a metric in SymPy; Schwarzschild orbits, ISCO, perihelion precession or light bending; gravitational redshift and GPS clock corrections; integrating geodesics numerically; converting between c = 1, geometric and SI units."
---

# Relativity calculations

Relativity errors are convention errors far more often than physics errors: a metric signature switched
halfway, a c dropped between MeV and MeV/c, a Doppler angle measured in the wrong frame, or coordinate
time used where proper time belongs. Fix the conventions first, then every step has an invariant to
check. Numbers below were recomputed with NumPy, SciPy and SymPy in October 2026 (PDG masses, IERS and
IAU constants).

## 1. Conventions

| Choice | Options | Rule |
|---|---|---|
| Signature | (−,+,+,+) in GR texts (MTW, Carroll); (+,−,−,−) in particle physics | p·p = −m²c² or +m²c²; state it on line one |
| Units | SI; c = 1 (energies in MeV, momenta MeV/c, masses MeV/c²); geometric G = c = 1 | restore factors by dimensions at the end |
| Indices | x^μ = (ct, x) contravariant, x_μ = g_μν x^ν; Greek 0-3, Latin 1-3 | only contract an upper index with a lower one |
| Curvature | R^ρ_σμν = ∂_μΓ^ρ_νσ − ∂_νΓ^ρ_μσ + Γ^ρ_μλΓ^λ_νσ − Γ^ρ_νλΓ^λ_μσ, R_σν = R^ρ_σρν | the unit 2-sphere then has R_ab = +g_ab |
| Field equations | G_μν + Λg_μν = (8πG/c⁴)T_μν | |

Geometric units: a mass M becomes the length GM/c² and the time GM/c³. The Sun: 1476.6 m and 4.9255 μs; the
Earth: GM/c² = 4.435 mm.

## 2. Lorentz transformations

- Boost along x with β = v/c, γ = 1/√(1 − β²): ct′ = γ(ct − βx), x′ = γ(x − βct), y′ = y, z′ = z.
- General boost: Λ⁰₀ = γ, Λ⁰_i = Λ^i_0 = −γβ_i, Λ^i_j = δ_ij + (γ − 1)β_iβ_j/β².
- Rapidity: β = tanh φ, γ = cosh φ, γβ = sinh φ. Collinear boosts add rapidities. Non-collinear boosts compose
  to a boost times a rotation (Thomas-Wigner rotation), so velocities do not simply add.
- Velocity addition for S′ moving at v along x: u_x = (u′_x + v)/(1 + u′_x v/c²) and
  u_y = u′_y/(γ(1 + u′_x v/c²)).
- Time dilation Δt = γΔτ (a clock at rest in the moving frame); length contraction L = L₀/γ (both ends
  measured simultaneously in the observer frame); relativity of simultaneity Δt′ = −γvΔx/c² for Δt = 0.
- Checks: ΛᵀηΛ = η, det Λ = +1, Λ⁰₀ ≥ 1, |u| < c, the interval s² = −c²Δt² + |Δx|² is invariant, and
  γ = 1 + T/(mc²) for kinetic energy T.

```python
import numpy as np
def boost(beta):
    b = np.asarray(beta, float); b2 = b @ b; g = 1/np.sqrt(1 - b2)
    L = np.eye(4); L[0, 0] = g; L[0, 1:] = L[1:, 0] = -g*b
    L[1:, 1:] += (g - 1)*np.outer(b, b)/b2 if b2 > 0 else 0
    return L
eta = np.diag([-1.0, 1, 1, 1])
L = boost([0.6, 0.0, 0.0]); assert np.allclose(L.T @ eta @ L, eta)      # γ = 1.25
assert np.isclose(np.arctanh(0.6) + np.arctanh(0.6), np.arctanh(1.2/1.36))  # rapidities add
```

## 3. Four-vectors and invariants

- u^μ = γ(c, v), p^μ = (E/c, p) = mu^μ, E² = (pc)² + (mc²)²; β = pc/E, γ = E/mc², γβ = p/mc.
- Invariant mass of a system: M²c⁴ = (ΣE)² − |Σp|²c². Mandelstam s = (p₁ + p₂)² is the centre-of-mass energy
  squared: fixed target s = m₁² + m₂² + 2E₁m₂, head-on collider s ≈ 4E₁E₂ (c = 1).
- Threshold, fixed target (particle 2 at rest), products of total mass ΣM: E₁ = [(ΣM)² − m₁² − m₂²]/(2m₂), a total
  energy. Antiprotons from p + p → p + p + p + p̄: E₁ = 7m_p, kinetic 6m_p = 5.63 GeV.
- Two-body decay at rest, M → 1 + 2 (c = 1, masses in energy units):
  p* = √([M² − (m₁ + m₂)²][M² − (m₁ − m₂)²])/(2M), E₁* = (M² + m₁² − m₂²)/(2M).
- In flight with parent γ, β: E_lab = γ(E* + βp* cos θ*); an isotropic decay (spin-0 parent) gives a flat
  spectrum between γ(E* − βp*) and γ(E* + βp*).
- Three-body decays: Dalitz variables with m₁₂² + m₂₃² + m₁₃² = M² + m₁² + m₂² + m₃².
- Compton scattering: λ′ − λ = (h/mc)(1 − cos θ), h/m_e c = 2.426 pm.

## 4. Doppler and aberration

- Source velocity v; θ is the angle between v and the source-to-observer direction, measured in the observer
  frame: f_obs = f_src/(γ(1 − β cos θ)). In terms of the source-frame angle θ′: f_obs = γf_src(1 + β cos θ′).
- Longitudinal: approaching f_obs = f_src√((1 + β)/(1 − β)), receding √((1 − β)/(1 + β)); redshift
  z = λ_obs/λ_src − 1.
- Transverse: θ = 90° in the observer frame gives f_src/γ (redshift); θ′ = 90° in the source frame gives
  γf_src (blueshift). Always say which frame the angle lives in.
- Aberration, S′ moving at +v along x: cos θ′ = (cos θ − β)/(1 − β cos θ), inverse
  cos θ = (cos θ′ + β)/(1 + β cos θ′), or tan(θ′/2) = √((1 + β)/(1 − β))·tan(θ/2).
- Headlight effect: half of the photons emitted isotropically in the source frame fall within sin θ = 1/γ of
  the velocity. I_ν/ν³ is invariant, which fixes how brightness transforms.
- Cosmological redshift is not a Doppler shift: 1 + z = a(t_obs)/a(t_emit).

## 5. Metric, Christoffel symbols, geodesic equation

- ds² = g_μν dx^μ dx^ν. Γ^λ_μν = ½g^λσ(∂_μg_σν + ∂_νg_σμ − ∂_σg_μν). Geodesics: d²x^λ/dτ² + Γ^λ_μν ẋ^μẋ^ν = 0,
  with g_μνẋ^μẋ^ν = −c² for timelike (−1 in G = c = 1) and 0 for null curves (affine parameter).
- By hand it is faster to vary L = ½g_μνẋ^μẋ^ν: the Euler-Lagrange equations are the geodesic equations, and
  cyclic coordinates give the conserved quantities directly (Killing vectors: ∂_t gives E = −u_t, ∂_φ gives
  L = u_φ).

```python
import sympy as sp
t, r, th, ph, M = sp.symbols('t r theta phi M', positive=True)
X = [t, r, th, ph]; n = 4
f = 1 - 2*M/r
g = sp.diag(-f, 1/f, r**2, r**2*sp.sin(th)**2)            # Schwarzschild, G = c = 1, signature -+++
gi = g.inv()
Gam = [[[sp.simplify(sum(gi[l, s]*(sp.diff(g[s, m], X[k]) + sp.diff(g[s, k], X[m]) - sp.diff(g[m, k], X[s]))
                         for s in range(n))/2) for k in range(n)] for m in range(n)] for l in range(n)]
Ric = sp.Matrix(n, n, lambda m, k: sp.simplify(
    sum(sp.diff(Gam[l][m][k], X[l]) - sp.diff(Gam[l][m][l], X[k]) for l in range(n))
    + sum(Gam[l][l][s]*Gam[s][m][k] - Gam[l][k][s]*Gam[s][m][l] for l in range(n) for s in range(n))))
assert Ric == sp.zeros(n, n)                               # vacuum solution
# nonzero: Γ^t_tr = M/(r(r−2M)), Γ^r_tt = M(r−2M)/r³, Γ^r_rr = −M/(r(r−2M)), Γ^r_θθ = −(r−2M),
# Γ^r_φφ = −(r−2M)sin²θ, Γ^θ_rθ = Γ^φ_rφ = 1/r, Γ^θ_φφ = −sinθ cosθ, Γ^φ_θφ = cot θ
```

- Declare symbols positive=True and simplify each Γ before contracting, or the Ricci expressions explode.
- For numerics, sp.lambdify the Christoffels once and call them inside the integrator (§8).
- sympy.diffgeom and EinsteinPy's symbolic module (MetricTensor, ChristoffelSymbols, RicciTensor) do the same
  job; cross-check either against this loop on a known metric before trusting it on a new one.

## 6. Schwarzschild orbits, ISCO, precession, light bending

G = c = 1 below; restore M → GM/c².
- ds² = −(1 − 2M/r)dt² + dr²/(1 − 2M/r) + r²dΩ². Horizon 2M (2.95 km per solar mass), photon sphere 3M
  (critical impact parameter 3√3M), ISCO 6M.
- Timelike equatorial motion: E = (1 − 2M/r)ṫ and L = r²φ̇ are conserved, and ṙ² = E² − V(r) with
  V = (1 − 2M/r)(1 + L²/r²). The Newtonian-like form is ½ṙ² + Φ_eff = (E² − 1)/2 with
  Φ_eff = −M/r + L²/(2r²) − ML²/r³; the last term is the GR correction.
- Circular orbits: r = (L²/2M)[1 ± √(1 − 12M²/L²)], + stable. They merge at L² = 12M²: the ISCO at r = 6M with
  L = 2√3M and E = √(8/9) = 0.9428, so 5.72% of the rest mass is radiated by the time matter reaches it.
  The orbital frequency is Ω = √(M/r³) in coordinate time; the gravitational-wave frequency at the ISCO is
  2Ω/2π = 1/(6^{3/2}πM) ≈ 4.4 kHz × (M_sun/M).

```python
Lq = sp.symbols('L', positive=True)
V = sp.Rational(1, 2)*(1 - 2*M/r)*(1 + Lq**2/r**2)
sp.solve([sp.diff(V, r), sp.diff(V, r, 2)], [r, Lq], dict=True)   # [{L: 2*sqrt(3)*M, r: 6*M}]
```

- Perihelion advance (weak field): Δφ = 6πM/(a(1 − e²)) per orbit, 6πGM/(c²a(1 − e²)) in SI. Mercury
  (a = 5.7909 × 10¹⁰ m, e = 0.2056, period 87.969 d) gives 42.98″ per century. Exact per radial period, with p
  the semi-latus rectum in units of M: Δφ = 4√(p/(p − 6 + 2e))·K(4e/(p − 6 + 2e)) − 2π, K the complete
  elliptic integral with parameter m (scipy.special.ellipk).
- Light bending: δ = 4M/b (4GM/(c²b) in SI), 1.751″ at the solar limb. Shapiro round-trip radar delay
  ≈ (4GM/c³)ln(4r₁r₂/b²), about 200 μs for Venus near superior conjunction.
- Rotating holes (Kerr): the ISCO runs from M (prograde, extremal spin) to 9M (retrograde); never use 6M there.

## 7. Gravitational redshift and the GPS clock correction

- Static clock: dτ/dt = √(1 − 2GM/(rc²)). Moving clock in a weak field (Earth-centred inertial frame):
  dτ/dt ≈ 1 + Φ/c² − v²/(2c²) with Φ = −GM/r.
- Between static clocks Δν/ν ≈ ΔΦ/c² = gh/c²; for the Pound-Rebka tower (h = 22.5 m) that is 2.46 × 10⁻¹⁵,
  the shift their experiment confirmed.
- GPS from first principles (GM_E = 3.986004418 × 10¹⁴ m³s⁻², orbit radius a = 26 561.75 km, mean Earth radius
  R_E = 6371 km, c = 299 792 458 m/s):

| Term | Formula | Fractional rate | Per day |
|---|---|---|---|
| Gravitational blueshift of the satellite clock | (GM/c²)(1/R_E − 1/a) | +5.292 × 10⁻¹⁰ | +45.72 μs |
| Time dilation at v = √(GM/a) = 3873.8 m/s | −v²/(2c²) | −8.349 × 10⁻¹¹ | −7.21 μs |
| Net, satellite clock gains | | +4.457 × 10⁻¹⁰ | +38.51 μs |
| Refined: ground clocks on the rotating geoid, L_G = W₀/c² = 6.969290134 × 10⁻¹⁰ | L_G − 3GM/(2ac²) | +4.4647 × 10⁻¹⁰ | +38.58 μs |

  Uncorrected, 38.5 μs/day of clock error is about 11.5 km/day of range error. GPS therefore sets the satellite
  oscillators low, 10.23 MHz × (1 − 4.4647 × 10⁻¹⁰) = 10.229 999 995 43 MHz.
- Remaining terms: the eccentricity correction Δt = (2/c²)√(GMa)·e sin E (amplitude 22.9 ns for e = 0.01,
  applied by receivers), and the Sagnac correction for receivers working in the rotating Earth-fixed frame
  (up to about 133 ns).

## 8. Numerical geodesic integration

- Integrate the second-order geodesic equations for (x^μ, u^μ) in proper time τ (affine λ for light) with an
  adaptive high-order method (DOP853, rtol = atol = 1e-12). The first-order radial equation ṙ² = E² − V has
  square-root trouble at turning points; keep it as a check instead.
- Monitor the invariants: g_μνu^μu^ν + 1 for timelike orbits, and the Killing energies E and L. Drifts should
  stay near 1e-11 and grow at most linearly; quadratic growth means a bug or loose tolerances.
- Schwarzschild coordinates are singular at r = 2M (stop with an event, or switch to Eddington-Finkelstein or
  Kerr-Schild coordinates) and on the polar axis (keep orbits equatorial or rotate the frame).
- Very long runs: use a Hamiltonian H = ½g^μν p_μp_ν with a symplectic integrator (`physics-ode-integrators`).

```python
import numpy as np
from scipy.integrate import solve_ivp
from scipy.special import ellipk
def rhs(tau, y, M=1.0):                     # equatorial Schwarzschild, G = c = 1
    t, r, ph, ut, ur, uph = y
    return [ut, ur, uph,
            -2*M/(r*(r - 2*M))*ut*ur,
            -M*(r - 2*M)/r**3*ut**2 + M/(r*(r - 2*M))*ur**2 + (r - 2*M)*uph**2,
            -2/r*ur*uph]
p, e = 20.0, 0.5                             # semi-latus rectum in units of M, eccentricity
L = np.sqrt(p**2/(p - 3 - e**2)); E = np.sqrt(((p - 2)**2 - 4*e**2)/(p*(p - 3 - e**2)))
rp = p/(1 + e)
peri = lambda tau, y: y[4]; peri.direction = 1          # u^r crosses 0 upwards at periapsis
sol = solve_ivp(rhs, [0, 3e4], [0, rp, 0, E/(1 - 2/rp), 0, L/rp**2],
                method='DOP853', rtol=1e-12, atol=1e-12, events=peri)
adv = np.diff(sol.y_events[0][:, 2]) - 2*np.pi            # 1.233862 rad per orbit
exact = 4*np.sqrt(p/(p - 6 + 2*e))*ellipk(4*e/(p - 6 + 2*e)) - 2*np.pi   # 1.233862
t, r, ph, ut, ur, uph = sol.y[:, -1]
drift = ((1 - 2/r)*ut - E, r**2*uph - L, -(1 - 2/r)*ut**2 + ur**2/(1 - 2/r) + r**2*uph**2 + 1)
# drifts 8e-13, 4e-11, 1e-12. The weak-field 6π/p = 0.9425 is 24% low at p = 20 and 4.5% low at p = 100
```

## 9. Pitfalls and worked example

Worked example (a): π⁺ → μ⁺ν_μ at rest, m_π = 139.57039 MeV, m_μ = 105.6583755 MeV, m_ν ≈ 0.
- p* = (m_π² − m_μ²)/(2m_π) = 29.792 MeV/c, E_μ = (m_π² + m_μ²)/(2m_π) = 109.778 MeV, T_μ = 4.120 MeV,
  β_μ = p*/E_μ = 0.2714, γ_μ = 1.0390, E_ν = p* = 29.792 MeV. Check: E_μ + E_ν = 139.570 MeV = m_π.
- In flight with p_π = 1 GeV/c (γ = 7.234, γβ = 7.165): the neutrino energy is flat between γE*(1 − β) = 2.07 MeV
  and γE*(1 + β) = 429.0 MeV, a maximum fraction 0.425 of E_π (→ 1 − m_μ²/m_π² = 0.427 as β → 1); the muon
  energy lies between 580.7 and 1007.6 MeV; the mean decay length is γβcτ = 55.9 m with τ = 26.033 ns.

Worked example (b): the GPS correction from first principles is the table in §7, +45.72 − 7.21 = +38.51 μs/day,
refined to +38.58 μs/day with the geoid potential.

```python
mpi, mmu = 139.57039, 105.6583755                         # MeV
p = (mpi**2 - mmu**2)/(2*mpi); Emu = (mpi**2 + mmu**2)/(2*mpi)
print(p, Emu, Emu - mmu, p/Emu, Emu/mmu)                  # 29.792 109.778 4.120 0.2714 1.0390
GM, c, a, RE, day = 3.986004418e14, 299792458.0, 26561.75e3, 6371e3, 86400
grav = GM/c**2*(1/RE - 1/a)*day*1e6                       # +45.72 μs/day
kin = -(GM/a)/(2*c**2)*day*1e6                            # -7.21 μs/day
frac = 6.969290134e-10 - 1.5*GM/(a*c**2)                  # 4.4647e-10, i.e. +38.58 μs/day
```

Pitfalls:
- Mixing signatures: E² − p² code fed a (−,+,+,+) metric flips the sign of every invariant mass squared.
- Dropped c factors between MeV, MeV/c and MeV/c²; geometric-unit results not converted back.
- Treating non-collinear boosts as collinear and forgetting the Thomas-Wigner rotation.
- Contracting a length that was not measured simultaneously in the frame used.
- A Doppler or aberration angle taken in the wrong frame: transverse Doppler is red in one frame, blue in the other.
- Coordinate time against proper time: Ω = √(M/r³) is per unit t, not τ; clock rates need dτ/dt.
- Schwarzschild results (ISCO 6M, photon sphere 3M) applied to spinning bodies.
- GPS: omitting the ground clock's own rate (use the geoid potential), or using Earth-fixed velocities in the
  inertial-frame formula.
- Integrating through r = 2M in Schwarzschild coordinates; tolerances loose enough to fake a precession.
- SymPy without positive=True or per-step simplification: expressions too large to simplify to zero.

Related: `lagrangian-hamiltonian-mechanics`, `physics-ode-integrators`, `dimensional-analysis-units`, `sympy-symbolic-verification`, `quantum-mechanics-methods`, hub `physics-toolkit`
