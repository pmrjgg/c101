---
name: dimensional-analysis-units
description: "Dimensions, units and magnitudes: Buckingham pi and nondimensionalisation, regime-deciding dimensionless numbers, scaling laws, Fermi estimates, limiting cases, SI 2019 and CODATA 2022 constants, unit-carrying code (pint, astropy.units, Unitful.jl), unit systems and conversion traps. Load before deriving or trusting any physical formula, magnitude or conversion."
when_to_use: "Deriving or checking a formula's dimensions; Buckingham pi or nondimensionalising equations; deciding a regime from Re, Ma, Kn, Bi and similar numbers; Fermi or order-of-magnitude estimates; converting between units or unit systems (Gaussian, natural, atomic, reduced LJ); choosing constants or checking a CODATA vintage; pint DimensionalityError or UnitStrippedWarning, astropy UnitConversionError, Unitful DimensionError."
---

# Dimensional analysis and units

Physics answers fail on dimensions, on regime (a formula used outside its validity), on unit or
constant slips, and on factors that dimensional analysis cannot see (2π, √2, ½). This skill puts
a check against each in front of every derivation, estimate and conversion. APIs were run in
October 2026 with pint 0.26, astropy 8.0, SciPy 1.18 and SymPy 1.14; the Julia APIs come from
the Unitful, UnitfulEquivalences and PhysicalConstants documentation.

Deep material: constants and conversions |
dimensionless numbers |
magnitude anchors

## 1. Buckingham pi

n variables built from k independent base dimensions give n − k independent dimensionless groups;
the law is a relation among them, π₁ = Φ(π₂, …).

1. List every relevant variable, including dimensional constants (g, ħ, c, k_B, G, γ).
2. Build the dimension matrix: rows M, L, T, Θ, I; columns variables; entries exponents.
3. k = rank of the matrix (it can be smaller than the number of base dimensions).
4. Pick k repeating variables that span the dimensions, usually the controls.
5. Form the n − k groups; recombine them into conventional ones (Re, C_D) before reporting.
6. Write π₁ = Φ(π₂, …). Φ comes from theory, a limit or data, never from the analysis itself.

Pendulum: T [T], L [L], g [L T⁻²], m [M], θ₀ [1]; n = 5, k = 3, two groups T·sqrt(g/L) and θ₀.
The mass cannot appear (nothing else carries M), so T = sqrt(L/g)·Φ(θ₀) with Φ(0) = 2π. Large
amplitude: T = 2π sqrt(L/g)(1 + θ₀²/16 + 11θ₀⁴/3072 + …); exact T/T₀ = 2K(sin²(θ₀/2))/π.

| θ₀ | Series | Exact |
|---|---|---|
| 5° | 1.000 476 | 1.000 476 |
| 30° | 1.017 404 | 1.017 409 |
| 90° | 1.176 0 | 1.180 3 |

```python
import sympy as sp, pint
dims = {"T": {"T": 1}, "L": {"L": 1}, "g": {"L": 1, "T": -2}, "m": {"M": 1}, "theta0": {}}
names = list(dims)
D = sp.Matrix([[dims[v].get(b, 0) for v in names] for b in ("M", "L", "T")])
print(D.rank(), len(names) - D.rank())               # 3 2
for v in D.nullspace():                              # one null vector per group (exponents)
    v = v*sp.ilcm(*[e.q for e in v])                 # clear fractions
    print(sp.Mul(*[sp.Symbol(n)**e for n, e in zip(names, v)]))   # T**2*g/L, theta0
ureg = pint.UnitRegistry(); Q_ = ureg.Quantity
pi1 = Q_(2.0, "s")**2*Q_(9.81, "m/s^2")/Q_(1.0, "m")
assert pi1.dimensionality == {}                      # pi1.dimensionless is True; value 39.24
```

The null space is a valid but arbitrary basis. For sphere drag (F, ρ, v, D, μ) it returns
ρv²D²/F and μ²/(Fρ); their ratio is Re², so recombine to C_D = F/(½ρv²A) and Re = ρvD/μ.

## 2. Nondimensionalisation and small parameters

1. Scale each variable by a characteristic value (x = L x̃, t = τ t̃, u = U ũ), with τ and U chosen
   from the dominant balance.
2. Divide by the coefficient of the dominant term. The remaining coefficients are the
   dimensionless groups; write down every small one as ε with its value.
3. Regular limit: ε multiplies lower-order terms; drop them with O(ε) error, uniformly.
4. Singular limit: ε multiplies the highest derivative; the reduced problem cannot meet all
   boundary conditions and a boundary layer of width δ(ε) appears; use matched asymptotics.
5. Distinguished limit: the scaling that keeps the most terms in balance, e.g. a viscous
   boundary layer of thickness δ ~ L·Re^{−1/2} from u ∂u/∂x ~ ν ∂²u/∂y².

Regular example: vertical launch against gravity that weakens with height, ẍ = −gR²/(R + x)².
With length v₀²/g and time v₀/g this becomes X″ = −1/(1 + εX)², ε = v₀²/(gR). For v₀ = 100 m/s,
ε = 1.6e-4, and the maximum height is (v₀²/2g)(1 + ε/2 + …): flat-Earth physics is exact to 1e-4.

Singular example: εy″ + y′ + y = 0, y(0) = 0, y(1) = 1. Outer solution y = e^{1−x} misses y(0) = 0;
inner variable X = x/ε gives Y = e(1 − e^{−X}); composite y ≈ e^{1−x} − e^{1−x/ε}, error O(ε).

## 3. Regime table

| Number | Definition | Thresholds |
|---|---|---|
| Reynolds Re | ρvL/μ = vL/ν | pipe laminar below ≈ 2300 (turbulent above ~4000); flat-plate transition Re_x ≈ 5e5; cylinder shedding above ≈ 47; sphere drag crisis ≈ 3e5; Stokes flow Re ≪ 1 |
| Mach Ma | v/c_s | incompressible below 0.3 (density change ≈ Ma²/2 = 4.5 %); transonic 0.8–1.2; hypersonic ≳ 5 |
| Knudsen Kn | λ_mfp/L | continuum < 0.01; slip 0.01–0.1; transitional 0.1–10; free molecular > 10 (air at 1 atm: λ ≈ 66 nm) |
| Froude Fr | v/sqrt(gL) | open channel: subcritical < 1 < supercritical; ship wave resistance climbs steeply near Fr ≈ 0.4 |
| Péclet Pe | vL/D (or vL/α) | > 1 advection dominates; a cell Péclet vΔx/D > 2 makes central differences oscillate |
| Prandtl Pr | ν/α | air 0.71, water ≈ 7, liquid metals ~0.01, oils 10²–10⁴ |
| Biot Bi | hL/k_solid (L = V/A) | < 0.1: uniform body temperature, lumped model valid |
| Strouhal St | fL/v | ≈ 0.2 for cylinders over roughly 300 < Re < 2e5 |
| Weber We | ρv²L/γ | drop break-up above ≈ 12 |
| Bond Bo | Δρ g L²/γ | ≪ 1 capillarity dominates; Bo = 1 at the capillary length (2.7 mm for water) |
| Rayleigh Ra | gβΔT L³/(να) | convection onset 1708 (rigid-rigid), 1101 (rigid-free), 657.5 (free-free) |
| Richardson Ri | N²/(du/dz)² | below 0.25 somewhere: shear instability possible (Miles-Howard) |
| Rossby Ro | U/(fL) | ≪ 1 rotation dominated, geostrophic; synoptic weather ~0.1 |
| Deborah De | relaxation time / observation time | ≪ 1 flows like a fluid, ≫ 1 responds like a solid |
| v/c | Lorentz factor γ | γ − 1 ≈ (v/c)²/2: 0.5 % at v = 0.1c |
| S/ħ | action / ħ | ≫ 1 classical, ~1 quantum |
| k_BT/(ħω) | thermal / quantum energy | ≫ 1 classical equipartition; ≪ 1 mode frozen (a 3000 cm⁻¹ C–H stretch is 4316 K) |
| α | e²/(4πε₀ħc) ≈ 1/137.036 | QED perturbation parameter |

Twenty-five numbers with definitions: dimensionless numbers.
Compute each with the length scale its correlation was built on (diameter, not radius; hydraulic
diameter 4A/P for ducts; V/A for Biot).

## 4. Scaling laws and similarity

| Law | Formula | Valid when |
|---|---|---|
| Stokes drag | F = 3πμDv; terminal speed (ρ_p − ρ_f)gD²/(18μ) | Re ≲ 0.5 for < 10 % error (Oseen: C_D = (24/Re)(1 + 3Re/16)) |
| Intermediate drag | C_D = (24/Re)(1 + 0.15 Re^0.687) (Schiller-Naumann) | Re ≲ 800 |
| Newton drag | F = ½C_D ρAv², sphere C_D ≈ 0.44–0.47 | 10³ ≲ Re ≲ 2e5, below the drag crisis |
| Diffusion length | ⟨x²⟩ = 2Dt per dimension (6Dt in 3D); ℓ ~ sqrt(Dt); thermal time L²/α | t ≫ collision time, no advection |
| Kolmogorov scales | η = (ν³/ε)^{1/4}, τ_η = (ν/ε)^{1/2}, u_η = (νε)^{1/4} | high-Re turbulence; air at ε = 0.01 W/kg: η ≈ 0.8 mm |
| Taylor blast wave | R = β(Et²/ρ)^{1/5}, β = 1.033 for γ = 1.4 | strong shock: post-shock pressure ≫ ambient |
| Capillary length | ℓ_c = sqrt(γ/(Δρ g)) = 2.7 mm for water-air | meniscus and drop sizes where Bo ~ 1 |

Similarity: model and prototype behave alike only when every relevant group matches. A ship model
in water at scale λ = L_m/L_p = 1/25 run at Froude-matched speed v_m = v_p sqrt(λ) has
Re_m = Re_p·λ^{3/2} = Re_p/125; matching Re as well would need a fluid with ν_m = ν_p λ^{3/2}.
Practice: match Fr, take friction from a friction line at each Re (ITTC-1957:
C_F = 0.075/(log₁₀ Re − 2)²) and scale only the residual (wave) resistance by Fr.

## 5. Fermi estimates

1. Write the target as a product of factors you can bound.
2. For each factor take bounds you would bet on and use their geometric mean: between 10 and
   1000 means 100.
3. Each factor known within ×3 has σ_ln ≈ ln 3 = 1.1; log-errors add in quadrature, so four such
   factors give ×9 (one order of magnitude).
4. Quote one significant figure; cross-check by a second decomposition.

Anchors: water 1000 kg/m³, air 1.2 kg/m³, atmospheric pressure 1e5 Pa, solar constant 1361 W/m²,
k_BT(300 K) = 25.85 meV ≈ 1/40 eV, human metabolism ~100 W, chemical bonds 1–10 eV
(more in magnitude anchors). Example: the mass of the
atmosphere is p₀·4πR²/g = 1.013e5 × 5.10e14/9.81 = 5.3e18 kg; the accepted value is about
5.15e18 kg because topography lowers the mean surface pressure.

## 6. Limiting-case checklist

- [ ] Every parameter to 0 and to ∞ (mass ratio, coupling, damping, temperature, frequency, size).
- [ ] Known special cases: ellipse with e → 0 is a circle, Z = 1 is hydrogen, V → 0 is a free
      particle.
- [ ] ħ → 0 recovers the classical result, c → ∞ the nonrelativistic one, low density the ideal
      gas, small drive linear response.
- [ ] Symmetric configurations (equal masses, isotropic media) give symmetric answers.
- [ ] Signs and monotonicity: the result grows or falls with each parameter as physics demands.
- [ ] Every smallness parameter evaluated at the actual numbers, with its value written down:

| Case | Parameter | Value |
|---|---|---|
| Pendulum at θ₀ = 5° | θ₀²/16 | 4.8e-4 |
| Aluminium sphere, still air | Biot; h_rad/h | 1.4e-4; 0.15 |
| Launch at 100 m/s | v₀²/(gR) | 1.6e-4 |
| Trinity fireball at 25 ms | ambient / post-shock pressure | 1 atm / ~50 atm = 0.02 |

## 7. Constants

- SI 2019 fixes seven constants exactly: Δν_Cs = 9 192 631 770 Hz, c = 299 792 458 m/s,
  h = 6.626 070 15e-34 J s, e = 1.602 176 634e-19 C, k_B = 1.380 649e-23 J/K,
  N_A = 6.022 140 76e23 mol⁻¹, K_cd = 683 lm/W. Derived exact: ħ, R = N_A k_B, F = N_A e, σ_SB,
  Wien b, ħc = 197.326 980 4… MeV fm, R_K = h/e², K_J = 2e/h, 1 eV = 1.602 176 634e-19 J.
- No longer exact: μ₀ = 1.256 637 061 27(20)e-6 N/A² (4π×10⁻⁷ is off by 1.3e-10 relative), ε₀,
  the molar mass constant M_u = 1.000 000 001 05(31) g/mol, the molar mass of ¹²C.
- CODATA 2022 is the current adjustment: α⁻¹ = 137.035 999 177(21), G = 6.674 30(15)e-11
  m³ kg⁻¹ s⁻² (relative 2.2e-5, the worst-known constant), m_e = 9.109 383 7139(28)e-31 kg. Full
  table: constants and conversions.
- Vintage check: `1/scipy.constants.fine_structure` gives 137.035999177… for CODATA 2022 and
  137.035999084… for 2018. SciPy ≥ 1.15 carries 2022 (1.14 carried 2018); astropy ≥ 8.0 defaults
  to codata2022 (7.x used codata2018; `astropy.physical_constants.set("codata2018")` before the
  first import of astropy.constants switches back); PhysicalConstants.jl ships CODATA2014,
  CODATA2018 and CODATA2022 modules.
- Never hand-type a constant a library carries; record library, version and CODATA year with the
  result; reproduce a paper with its vintage. 2018 → 2022 shifts are ~1e-9 relative (m_e 1.4e-9).
- Material data (densities, conductivities, viscosities) come from NIST (Chemistry WebBook, SRD
  databases) or the CRC Handbook, cited with edition, temperature and pressure.

## 8. Units in code

```python
import numpy as np, pint
ureg = pint.UnitRegistry(); Q_ = ureg.Quantity       # one registry per process
lam = Q_(1550, "nm")
lam.to("eV", "sp")                                   # 0.7999 eV; contexts: sp, boltzmann,
with ureg.context("sp"): lam.to("THz")               #   chemistry, Gaussian, ESU, energy, textile
@ureg.wraps("s", ("m", "m/s^2"))                     # converts args, strips, calls, re-attaches
def period(L, g): return 2*np.pi*np.sqrt(L/g)
@ureg.check("[length]", "[acceleration]")            # DimensionalityError on misuse
def period_checked(L, g): return 2*np.pi*(L/g)**0.5
Q_(1.000, "m").plus_minus(0.002)                     # Measurement: units plus uncertainty
(Q_(1, "cm")/Q_(1, "m")).magnitude                   # 1.0 (!): use .m_as("dimensionless") -> 0.01
```

```python
import astropy.units as u
(1550*u.nm).to(u.eV, equivalencies=u.spectral())     # also spectral_density, temperature_energy,
                                                     # mass_energy, dimensionless_angles, doppler_*
@u.quantity_input
def period(L: u.m, g: u.m/u.s**2) -> u.s: return 2*np.pi*np.sqrt(L/g)
# (1*u.Hz).to(u.rad/u.s) raises UnitConversionError; pint returns 1 rad/s without complaint
```

```julia
using Unitful, UnitfulEquivalences, Measurements
import PhysicalConstants.CODATA2022: ħ, c_0
uconvert(u"eV", 1550u"nm", Spectral())              # Spectral(frequency=:angular) gives ω
uconvert(u"eV", 20u"°C", Thermal()); uconvert(u"keV", 1u"me", MassEnergy())
ustrip(u"m", 3u"mm")                                 # 3//1000: converts, then strips
uconvert(NoUnits, 1.0u"μm/m")                        # 1.0e-6, whereas ustrip(1.0u"μm/m") is 1.0
dimension(x) == NoDims                               # dimensionless check
measurement(ħ)                                       # constant with its CODATA uncertainty
```

SymPy for symbolic work: `convert_to(planck*speed_of_light/(1550*nanometer), electronvolt)` gives
0.799898 eV; `dimsys_SI.get_dimensional_dependencies(expr)` returns the exponent dictionary.

Strip units once at the numerical kernel boundary, in SI, and re-attach once on the way out:

```python
def cooling_time(r, h, T0, Tend, Tinf):              # public API takes Quantities
    args = r.m_as("m"), h.m_as("W/(m^2*K)"), T0.m_as("K"), Tend.m_as("K"), Tinf.m_as("K")
    return Q_(_kernel(*args), "s")                   # floats inside (numba, C, GPU), units outside
```

## 9. Unit systems

Gaussian ↔ SI. Formula translations:

| Gaussian | SI |
|---|---|
| Coulomb F = q₁q₂/r² | F = q₁q₂/(4πε₀r²) |
| Lorentz F = q(E + v × B/c) | F = q(E + v × B) |
| ∇·E = 4πρ | ∇·E = ρ/ε₀ |
| ∇ × B = (4π/c)J + (1/c)∂E/∂t | ∇ × B = μ₀J + μ₀ε₀ ∂E/∂t |
| D = E + 4πP, B = H + 4πM | D = ε₀E + P, B = μ₀(H + M) |
| energy density (E² + B²)/8π | (ε₀E² + B²/μ₀)/2 |
| α = e²/(ħc) | α = e²/(4πε₀ħc) |

Symbol substitution, Gaussian formula → SI formula: E → sqrt(4πε₀)E, D → sqrt(4π/ε₀)D,
(q, ρ, J, I, P) → (·)/sqrt(4πε₀), B → sqrt(4π/μ₀)B, H → sqrt(4πμ₀)H, M → sqrt(μ₀/4π)M,
c → 1/sqrt(μ₀ε₀), ε → ε/ε₀, μ → μ/μ₀. Translate whole formulas, then check dimensions; never mix
fields from both systems in one equation. Conversions: 1 G = 1e-4 T, 1 Oe = 79.577 A/m,
1 statC = 3.335 64e-10 C, 1 statV = 299.792 458 V, 1 erg = 1e-7 J, 1 dyn = 1e-5 N, a capacitance
of 1 cm = 1.112 65 pF.

| System | Set to 1 | Conversions to restore SI |
|---|---|---|
| Natural (particle physics) | ħ = c (= k_B) = 1 | ħc = 197.327 MeV fm, so 1 GeV⁻¹ = 0.1973 fm = 6.582e-25 s; 1 GeV = 1.783e-27 kg; (ħc)² = 0.3894 GeV² mb; 1 eV ↔ 11 604.5 K |
| Atomic (Hartree) | ħ = m_e = e = 4πε₀ = 1 | length a₀ = 0.529 177 Å; energy E_h = 27.211 386 eV; time 2.418 884e-17 s; velocity αc = 2.187 691e6 m/s; field 5.142 207e11 V/m; c = 137.036 |
| Geometric (relativity) | G = c = 1 | mass → length GM/c² (Sun 1.4766 km), time GM/c³ (Sun 4.9255 μs) |
| Reduced Lennard-Jones | σ = ε = m = 1 | τ = σ sqrt(m/ε); T* = k_BT/ε, ρ* = nσ³, P* = Pσ³/ε; argon (σ = 3.405 Å, ε/k_B = 119.8 K): τ = 2.16 ps |

Restore dimensions explicitly at the end: multiply by ħ^a c^b k_B^d with exponents solved from
the target unit, e.g. a cross-section of 1/E² in GeV⁻² times (ħc)² = 0.3894 mb GeV².

## 10. Traps

| Trap | Symptom | Fix |
|---|---|---|
| ω versus f | factor 2π; ħω versus hf | name variables omega or freq; pint converts 1 Hz to 1 rad/s silently because radians are dimensionless; astropy raises unless `dimensionless_angles()` |
| cm⁻¹ versus k | ν̃ = 1/λ (spectroscopy) against k = 2π/λ (waves) | state which wavenumber |
| per mole versus per particle | ×6.022e23 | R = N_A k_B; 1 kJ/mol = 10.364 meV, 1 kcal/mol = 43.364 meV per particle |
| eV, eV/c², eV/c | energy, mass, momentum all written "eV" | restore c on output |
| absolute K versus ΔT | wrong ratios, Arrhenius, radiation | absolute T in formulas; a ΔT in °C equals one in K; pint raises OffsetUnitCalculusError for degC + degC and offers delta_degC |
| dB as 10 versus 20 log₁₀ | factor 2 in dB, square root in ratios | power 10 log₁₀, amplitude 20 log₁₀; pint's dB is a power ratio (20 dB → 100) |
| 2π hidden in "dimensionless" radians | rad/s versus Hz, degrees in trig calls | carry cycles explicitly; `np.sin` takes radians |
| `scipy.constants.g` | it is standard gravity 9.806 65 m/s² | the gravitational constant is `scipy.constants.G` = 6.6743e-11 |
| NumPy strips pint units | `np.asarray(q)` returns a bare array with only a UnitStrippedWarning; compiled code sees magnitudes | strip deliberately with `m_as`; in tests `warnings.simplefilter("error", pint.UnitStrippedWarning)` |
| `.magnitude` of a ratio | (1 cm / 1 m).magnitude = 1.0 | `.m_as("dimensionless")` or `to_reduced_units()`; Unitful's `ustrip` has the same trap |
| pint gauss | `Q_(1, "G").to("T")` raises DimensionalityError | `.to("T", "Gaussian")` gives 0.999 999 999 93e-4 T (μ₀ is no longer exactly 4π×10⁻⁷) |
| Planck peak per λ versus per ν | λ_max T = 2.898e-3 m K, but c/ν_max = 5.10e-3 m K | name the spectral density; at 5772 K: 502 nm against 883 nm |
| calorie | thermochemical 4.184 J versus IT 4.1868 J | state which (`scipy.constants.calorie` is 4.184) |
| gauge versus absolute pressure | psig, bar(g) | add the ambient pressure |

## 11. Worked examples

**Taylor's Trinity yield.** Variables E, ρ, R, t (n = 4, k = 3): one group Et²/(ρR⁵), so
R = β(Et²/ρ)^{1/5}. The frame usually quoted from J. E. Mack's photographs has R ≈ 140 m at
t ≈ 25 ms; with ρ ≈ 1.2 kg/m³, E ≈ ρR⁵/t² = 1.2 × 140⁵/0.025² = 1.03e14 J = 25 kt of TNT
(1 kt = 4.184e12 J). With β(γ = 1.4) = 1.033, E = 1.03e14/1.033⁵ = 8.8e13 J = 21 kt. The official
yield is 21 kt and a 2021 re-analysis gives 24.8 ± 2 kt. Checks: [kg m⁻³][m⁵][s⁻²] = J; the
shock speed dR/dt = (2/5)R/t = 2240 m/s gives a post-shock pressure 2ρv²/(γ + 1) ≈ 5e6 Pa ≈ 50 atm,
so the strong-shock assumption holds; E ∝ R⁵, so 5 % in R is 28 % in E.

**Lumped cooling of an aluminium sphere.** 2 cm diameter at 200 °C in still air at 20 °C,
h ≈ 10 W/(m² K); time to 50 °C? Bi = h(V/A)/k = 10 × (0.01/3)/237 = 1.4e-4 ≪ 0.1, so the sphere is
isothermal. τ = ρcV/(hA) = 2700 × 897 × (0.01/3)/10 = 807 s; 30 = 180 e^{−t/τ} gives
t = τ ln 6 = 1446 s = 24.1 min. Radiation (ε ≈ 0.1, oxidised): linearised at 400 K,
h_rad = 4εσT³ = 1.45 W/(m² K), giving 21.1 min; integrating the nonlinear radiation term gives
22.2 min. Report 21–24 min. Sensitivity: ε = 0.05–0.3 moves it to 23.1–19.1 min, but h = 7–13
W/(m² K) (natural convection, ±30 %) moves it to 30.6–17.4 min: h dominates. Checks: τ has units
(kg/m³)(J/(kg K))(m)/(W/(m² K)) = s; h → ∞ gives τ → 0.

**A 1550 nm photon, by hand and with pint.** E = hc/λ = 1239.842 eV nm/1550 nm = 0.799 90 eV;
f = c/λ = 193.414 THz; ν̃ = 1/λ = 6451.6 cm⁻¹; ω = 2πf = 1.2153e15 rad/s; k = 2π/λ = 4.0537e6 m⁻¹;
E/k_B = 9282 K.

```python
lam = Q_(1550, "nm")
[lam.to(t, "sp") for t in ("eV", "THz", "1/cm")]  # 0.79990 eV, 193.414 THz, 6451.61 1/cm
(1550*u.nm).to(u.eV, equivalencies=u.spectral())  # astropy: 0.79990 eV
```

## 12. Pitfalls

- **A missing variable** in a Buckingham analysis (g, surface tension, a second length) gives a
  confident wrong law; an irrelevant extra one only adds a group the data will ignore.
- **Right dimensions, wrong number:** 2π, √2 and ½ are invisible to dimensional analysis; fix them
  with a limit or a special case.
- **Wrong length scale or viscosity** in a regime number: radius for diameter, a pipe diameter for
  a duct's hydraulic diameter, μ for ν = μ/ρ (Re off by 2 or by 1000).
- **Scaling laws outside their validity:** Stokes drag at Re = 50, the blast-wave law once the shock
  has weakened, Kolmogorov scales at low Re.
- **A Fermi estimate dominated by one poorly known factor:** find it, bound it better, then stop.
- **Mixed CODATA vintages** in one calculation, or constants typed from memory.
- **Results left in natural or atomic units** without restoring dimensions.
- **Linearising** a nonlinear law at the wrong operating point (radiation at 400 K: 21.1 min
  against 22.2 min from the full law).
- **Trusting a unit library across a compiled boundary:** units vanish at `np.asarray`, numba,
  Cython and C extensions.

Related: `uncertainty-propagation-fitting`, `simulation-verification-validation`,
`fluid-dynamics-cfd`, `em-field-solvers-fdtd-fem`, `molecular-dynamics-setup`,
`quantum-mechanics-methods`, `sympy-symbolic-verification`, hub `physics-toolkit`.
