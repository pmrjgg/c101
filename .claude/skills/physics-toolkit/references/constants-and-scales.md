# Constants, conversions and scales

Prefer library values (`scipy.constants`, `astropy.constants`) over typed numbers, and record the
CODATA vintage. The values below are rounded to digits that agree between CODATA 2018 and 2022
unless marked exact; use them for checks and estimates, not for metrology.

## 1. Exact SI defining constants (2019 SI)

| Constant | Value |
|---|---|
| Speed of light c | 299 792 458 m/s |
| Planck constant h | 6.626 070 15 × 10⁻³⁴ J s |
| Elementary charge e | 1.602 176 634 × 10⁻¹⁹ C |
| Boltzmann constant k_B | 1.380 649 × 10⁻²³ J/K |
| Avogadro constant N_A | 6.022 140 76 × 10²³ mol⁻¹ |
| Cs hyperfine frequency Δν_Cs | 9 192 631 770 Hz |
| Luminous efficacy K_cd | 683 lm/W at 540 THz |

Derived exact (infinite decimals): ħ = h/2π = 1.054 571 817... × 10⁻³⁴ J s;
R = N_A k_B = 8.314 462 618... J/(mol K); F = N_A e = 96 485.332 12... C/mol;
σ_SB = 5.670 374 419... × 10⁻⁸ W/(m² K⁴); Wien b = 2.897 771 955... × 10⁻³ m K;
ħc = 197.326 980 4... MeV fm; 1 eV = 1.602 176 634 × 10⁻¹⁹ J.

Conventional exact: g_n = 9.806 65 m/s²; 1 atm = 101 325 Pa; 1 cal_th = 4.184 J;
1 au = 149 597 870 700 m (IAU 2012).

## 2. Measured constants (CODATA)

| Constant | Value | Rel. uncertainty (order) |
|---|---|---|
| Fine-structure α⁻¹ | 137.035 999 (2022: 137.035 999 177) | 1e-10 |
| Newtonian G | 6.674 30 × 10⁻¹¹ m³ kg⁻¹ s⁻² | 2e-5 (worst-known constant) |
| Electron mass m_e | 9.109 383 7 × 10⁻³¹ kg = 0.510 998 95 MeV/c² | 3e-10 |
| Proton mass m_p | 1.672 621 9 × 10⁻²⁷ kg = 938.272 09 MeV/c² | 3e-10 |
| Neutron mass m_n | 1.674 927 5 × 10⁻²⁷ kg = 939.565 4 MeV/c² | 5e-10 |
| m_p/m_e | 1836.152 673 | 6e-11 |
| Atomic mass unit u | 1.660 539 07 × 10⁻²⁷ kg = 931.494 10 MeV/c² | 3e-10 |
| Vacuum permittivity ε₀ | 8.854 187 8 × 10⁻¹² F/m | 2e-10 |
| Vacuum permeability μ₀ | 1.256 637 06 × 10⁻⁶ N/A² (≈ 4π × 10⁻⁷, no longer exact) | 2e-10 |
| Bohr radius a₀ | 5.291 772 1 × 10⁻¹¹ m | 2e-10 |
| Rydberg constant R∞ | 10 973 731.568 m⁻¹ | 1e-12 |
| Hartree energy E_h | 4.359 744 72 × 10⁻¹⁸ J = 27.211 386 2 eV | 1e-12 |
| Rydberg energy | 13.605 693 12 eV | 1e-12 |
| Bohr magneton μ_B | 9.274 010 1 × 10⁻²⁴ J/T = 5.788 381 8 × 10⁻⁵ eV/T | 3e-10 |
| Nuclear magneton μ_N | 5.050 783 7 × 10⁻²⁷ J/T | 3e-10 |
| Electron g-factor g_e | -2.002 319 304 36 | 2e-13 |
| Classical electron radius r_e | 2.817 940 3 × 10⁻¹⁵ m | 5e-10 |
| Electron Compton wavelength λ_C | 2.426 310 2 × 10⁻¹² m | 3e-10 |
| Thomson cross section σ_T | 6.652 458 7 × 10⁻²⁹ m² | 1e-9 |

Check the library vintage:

```python
import scipy.constants as sc
print(1/sc.fine_structure)                      # 137.035999177 -> CODATA 2022; 137.035999084 -> 2018
print(sc.physical_constants["electron mass"])   # (value, unit, uncertainty)
```

## 3. Conversions

| From | To |
|---|---|
| 1 eV | 1.602 176 634 × 10⁻¹⁹ J; 11 604.518 K (÷k_B); 2.417 989 24 × 10¹⁴ Hz (÷h); 8065.544 cm⁻¹; 1239.842 nm (λ = hc/E) |
| 1 Hartree | 27.211 386 eV; 219 474.63 cm⁻¹; 627.509 kcal/mol; 2625.50 kJ/mol |
| 1 kcal/mol | 43.364 meV; 4.184 kJ/mol |
| 1 kJ/mol | 10.364 meV |
| k_B T at 300 K | 25.852 meV; 0.596 kcal/mol; 2.494 kJ/mol; 208.5 cm⁻¹ |
| 1 bar | 10⁵ Pa (1 atm = 1.013 25 bar; 1 Torr = 133.322 Pa) |
| 1 Å | 10⁻¹⁰ m; 1 bohr = 0.529 177 Å |
| 1 barn | 10⁻²⁸ m² |
| 1 gauss | 10⁻⁴ T |
| 1 erg | 10⁻⁷ J; 1 dyn = 10⁻⁵ N |
| 1 debye | 3.335 64 × 10⁻³⁰ C m |
| 1 light year | 9.460 730 472 580 8 × 10¹⁵ m; 1 pc = 3.085 677 581 × 10¹⁶ m = 3.2616 ly |
| 1 day (sidereal) | 86 164.0905 s |
| 1 Julian year | 365.25 d = 3.155 76 × 10⁷ s |

## 4. Gaussian ↔ SI electromagnetism

| Gaussian | SI equivalent substitution |
|---|---|
| e² | e²/(4πε₀) |
| Coulomb F = q₁q₂/r² | F = q₁q₂/(4πε₀ r²) |
| Lorentz F = q(E + v × B/c) | F = q(E + v × B) (B_G ↔ c B_SI in this formula) |
| ∇·E = 4πρ | ∇·E = ρ/ε₀ |
| ∇ × B = (4π/c) J + (1/c) ∂E/∂t | ∇ × B = μ₀ J + μ₀ε₀ ∂E/∂t |
| Energy density (E² + B²)/(8π) | (ε₀E² + B²/μ₀)/2 |
| α = e²/(ħc) | α = e²/(4πε₀ħc) |

Translate whole formulas with the substitution, then check dimensions; do not mix fields from
different systems in one equation.

## 5. Astronomical and planetary values (IAU nominal or standard)

| Quantity | Value |
|---|---|
| GM_sun | 1.327 124 400 18 × 10²⁰ m³/s² (known far better than M_sun) |
| M_sun | 1.988 4 × 10³⁰ kg |
| R_sun (nominal) | 6.957 × 10⁸ m |
| L_sun (nominal) | 3.828 × 10²⁶ W |
| GM_earth | 3.986 004 418 × 10¹⁴ m³/s² |
| M_earth | 5.972 2 × 10²⁴ kg |
| R_earth (equatorial) | 6.378 1 × 10⁶ m |
| Solar constant (1 au) | 1361 W/m² |
| Hubble constant | ≈ 67-73 km/s/Mpc (tension between methods; state which) |

## 6. Dimensionless numbers (fluids, heat, transport)

| Number | Definition | Ratio |
|---|---|---|
| Reynolds Re | ρ v L / μ = v L / ν | inertia / viscous |
| Mach Ma | v / c_s | flow / sound speed |
| Froude Fr | v / sqrt(g L) | inertia / gravity |
| Weber We | ρ v² L / γ | inertia / surface tension |
| Bond Bo | Δρ g L² / γ | gravity / surface tension (capillary length sqrt(γ/(Δρ g)) ≈ 2.7 mm for water) |
| Capillary Ca | μ v / γ | viscous / surface tension |
| Prandtl Pr | ν / α | momentum / thermal diffusivity |
| Schmidt Sc | ν / D | momentum / mass diffusivity |
| Lewis Le | α / D | thermal / mass diffusivity |
| Péclet Pe | v L / D (or v L / α) | advection / diffusion = Re·Sc (or Re·Pr) |
| Nusselt Nu | h L / k_fluid | convective / conductive heat transfer |
| Biot Bi | h L / k_solid | surface / internal resistance |
| Grashof Gr | g β ΔT L³ / ν² | buoyancy / viscous |
| Rayleigh Ra | Gr · Pr | convection onset ≈ 1708 (rigid-rigid Rayleigh-Bénard) |
| Richardson Ri | N² / (du/dz)² | stratification / shear (< 0.25 shear instability possible) |
| Rossby Ro | U / (f L) | inertia / Coriolis |
| Ekman Ek | ν / (f L²) | viscous / Coriolis |
| Strouhal St | f L / v | shedding frequency |
| Knudsen Kn | λ / L | mean free path / size |
| Damköhler Da | reaction rate / transport rate | > 1 reaction-limited by transport |
| Deborah De | relaxation time / observation time | elastic vs viscous behaviour |
| Stokes Stk | particle response time / flow time | particles follow flow if ≪ 1 |
| Magnetic Reynolds Rm | μ₀ σ v L | advection / diffusion of magnetic field |
| Hartmann Ha | B L sqrt(σ / μ) | Lorentz / viscous |

## 7. Order-of-magnitude anchors

| Quantity | Value |
|---|---|
| Atomic size | 1 Å; atomic energy ~ 10 eV; atomic time ħ/E_h = 2.4 × 10⁻¹⁷ s |
| Nuclear size / energy | 1 fm; ~ 1-10 MeV per nucleon binding |
| Covalent bond energy | 3-5 eV (C-C 3.6 eV); hydrogen bond 0.1-0.3 eV |
| Molecular vibration | 10¹³-10¹⁴ Hz (300-3000 cm⁻¹) |
| Speed of sound | air 343 m/s (20 °C), water 1480 m/s, steel ~5900 m/s |
| Densities | air 1.2 kg/m³, water 1000, rock 2700, iron 7870 |
| Viscosity | air 1.8 × 10⁻⁵ Pa s, water 1.0 × 10⁻³ Pa s (20 °C) |
| Thermal conductivity | air 0.026, water 0.6, steel 15-50, aluminium 237, copper 400 W/(m K) |
| Specific heat | water 4186 J/(kg K), aluminium 897, iron 449 |
| Young's modulus | rubber ~0.01 GPa, bone ~20, steel ~200, diamond ~1000 |
| Earth surface | g = 9.81 m/s², escape speed 11.2 km/s, solar flux at ground ~1 kW/m² |
| Human scale | metabolic ~100 W, walking 1.4 m/s, reaction time ~0.2 s |
