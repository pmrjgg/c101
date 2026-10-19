---
name: quantum-mechanics-methods
description: "Analytic quantum mechanics toolkit covering operator algebra and ladder operators, angular momentum addition and Clebsch-Gordan coefficients, selection rules, nondegenerate, degenerate and time-dependent perturbation theory, the Fermi golden rule, variational and WKB methods, Born and partial-wave scattering and identical particles, with validity and sign checks. Load when solving or checking a QM problem by hand or with SymPy."
when_to_use: "Computing an energy shift or matrix element by hand; coupling angular momenta or needing Clebsch-Gordan coefficients; deciding whether a transition is dipole-allowed; a transition rate from the Fermi golden rule; a variational, WKB or tunnelling estimate; Born-approximation or partial-wave cross sections; singlet and triplet exchange questions; checking hermiticity, normalisation or the sign of a QM result; sympy.physics.quantum or sympy.physics.wigner code."
---

# Quantum mechanics methods

Hand calculations go wrong in five repeatable ways: a nondegenerate formula used inside a degenerate
level, a density of states with the wrong normalisation, h where ħ belongs, a dropped spin degeneracy,
and an approximation used outside its regime. Every formula below carries its validity condition and a
check. Numbers were recomputed with NumPy, SciPy and SymPy in October 2026. Grids, shooting and time
stepping belong to `schrodinger-numerics`.

## 1. Procedure

1. Write H. List the symmetries (parity, rotation, translation, time reversal, permutation) and a complete
   commuting set {H, L², L_z, S², J_z, P, …}. Good quantum numbers label states and give selection rules free.
2. Choose the basis that diagonalises H₀ and that set: number states for oscillators, |n l m⟩, or the coupled
   |n l j m_j⟩ once L·S is present, Bloch states for lattices (`tight-binding-band-structure`).
3. Pick the method:

| Situation | Method | Validity or stop condition |
|---|---|---|
| H = H₀ + V, H₀ solved, V small | Rayleigh-Schrödinger (§4) | \|V_mn\| ≪ \|E_n − E_m\|; next order ≪ current |
| Degenerate or nearly degenerate level | diagonalise V in the subspace (§4) | splitting ≫ coupling to outside levels |
| Ground state, no small parameter | variational (§6) | gives an upper bound only |
| Large quantum numbers, slowly varying V | WKB (§7) | \|ħp′/p²\| ≪ 1 away from turning points |
| Weak drive into a continuum | Fermi golden rule (§5) | t ≫ ħ/ΔE and Γt ≪ 1 |
| Two levels driven near resonance | Rabi formula, exact in the RWA (§5) | Ω, \|Δ\| ≪ ω₀ |
| Weak potential or fast particle | Born approximation (§8) | m\|V₀\|a²/ħ² ≪ 1 or \|V₀\|a/(ħv) ≪ 1 |
| Low energy, short range | partial waves up to l ≈ ka (§8) | phase shifts converge in l |
| Nothing applies, or numbers needed | truncated-basis diagonalisation (`schrodinger-numerics`) | converged in basis size |

4. Solve, then run every check in §10 before reporting.

## 2. Operator toolkit

- [x, p] = iħ, [x_i, p_j] = iħδ_ij, [f(x), p] = iħf′(x), [L_i, L_j] = iħε_ijk L_k.
- Oscillator: a = √(mω/2ħ)(x + ip/mω), x = √(ħ/2mω)(a + a†), p = i√(mħω/2)(a† − a), [a, a†] = 1,
  a|n⟩ = √n|n−1⟩, a†|n⟩ = √(n+1)|n+1⟩, H = ħω(a†a + ½).
- Hadamard lemma: e^A B e^−A = B + [A,B] + [A,[A,B]]/2! + …, so e^{iθa†a} a e^{−iθa†a} = e^{−iθ}a and
  D(α)† a D(α) = a + α. When [A,B] commutes with A and B: e^{A+B} = e^A e^B e^{−[A,B]/2}.
- Heisenberg: dA_H/dt = (i/ħ)[H, A_H] + (∂A/∂t)_H. Ehrenfest: d⟨x⟩/dt = ⟨p⟩/m, d⟨p⟩/dt = −⟨V′(x)⟩, which is
  classical only when ⟨V′(x)⟩ ≈ V′(⟨x⟩) (V at most quadratic across the packet).
- Virial theorem (stationary states): 2⟨T⟩ = ⟨r·∇V⟩; V ∝ r^k gives 2⟨T⟩ = k⟨V⟩. Coulomb: ⟨T⟩ = −E, ⟨V⟩ = 2E.
- Hellmann-Feynman: dE_n/dλ = ⟨n|∂H/∂λ|n⟩ for exact or fully variational eigenstates. Hydrogen: d/dZ gives
  ⟨1/r⟩ = Z/(n²a₀); d/dl gives ⟨1/r²⟩.
- Oscillator moments: ⟨n|x²|n⟩ = (ħ/2mω)(2n + 1), ⟨n|x⁴|n⟩ = (ħ/2mω)²·3(2n² + 2n + 1). x links Δn = ±1,
  x² links 0, ±2 and x⁴ links 0, ±2, ±4.

```python
import sympy as sp
from sympy.physics.quantum import Commutator, Dagger
from sympy.physics.quantum.boson import BosonOp
from sympy.physics.quantum.operatorordering import normal_ordered_form
a = BosonOp('a')
Commutator(a, Dagger(a)).doit()                                  # 1
normal_ordered_form(sp.expand((a + Dagger(a))**4), independent=True)
# a†⁴ + 4a†³a + 6a†²a² + 4a†a³ + a⁴ + 6a†² + 6a² + 12a†a + 3: vacuum value 3, so ⟨0|x⁴|0⟩ = 3(ħ/2mω)²
```

## 3. Angular momentum

- J²|j m⟩ = ħ²j(j+1)|j m⟩, J_z|j m⟩ = ħm|j m⟩, J±|j m⟩ = ħ√((j ∓ m)(j ± m + 1))|j, m ± 1⟩.
- j₁ ⊗ j₂ = |j₁ − j₂| ⊕ … ⊕ (j₁ + j₂), M = m₁ + m₂, dimension check (2j₁+1)(2j₂+1) = Σ_J (2J+1).
- Condon-Shortley phases (⟨j₁ j₁; j₂ J−j₁|J J⟩ > 0). Two spins: |1 0⟩ = (|↑↓⟩ + |↓↑⟩)/√2,
  |0 0⟩ = (|↑↓⟩ − |↓↑⟩)/√2. l = 1 ⊗ s = ½: |3/2 ½⟩ = √(2/3)|1 0⟩|↑⟩ + √(1/3)|1 1⟩|↓⟩ and
  |½ ½⟩ = √(2/3)|1 1⟩|↓⟩ − √(1/3)|1 0⟩|↑⟩.

```python
from sympy import S
from sympy.physics.quantum.cg import CG                        # CG(j1, m1, j2, m2, J, M)
from sympy.physics.wigner import clebsch_gordan, wigner_3j     # clebsch_gordan(j1, j2, J, m1, m2, M)
CG(S(1)/2, S(1)/2, S(1)/2, -S(1)/2, 1, 0).doit()      # sqrt(2)/2
CG(1, 0, S(1)/2, S(1)/2, S(1)/2, S(1)/2).doit()       # -sqrt(3)/3
clebsch_gordan(1, S(1)/2, S(1)/2, 1, -S(1)/2, S(1)/2) # sqrt(6)/3, same coefficient as CG(1,1,1/2,-1/2,1/2,1/2)
```

- Wigner-Eckart: ⟨j′m′|T^k_q|j m⟩ = ⟨j m; k q|j′ m′⟩⟨j′‖T^k‖j⟩/√(2j′+1). Reduced elements come in at least
  three normalisations; ratios inside one multiplet are convention-free. Nonzero only if m′ = m + q and
  |j − k| ≤ j′ ≤ j + k.

| Multipole | Rank, parity | Δl | Δm | Parity | Also |
|---|---|---|---|---|---|
| E1 | k = 1, odd | ±1 | 0, ±1 | changes | ΔS = 0 in LS coupling; ΔJ = 0, ±1, not 0 → 0 |
| M1 | k = 1, even | 0 | 0, ±1 | same | ΔJ = 0, ±1, not 0 → 0 |
| E2 | k = 2, even | 0, ±2 | 0, ±1, ±2 | same | ΔJ ≤ 2; l = 0 → 0 forbidden |

Δm = 0 for π (z-polarised) light, ±1 for σ±. M1 and E2 are suppressed relative to E1 by roughly α² and
(ka₀)² (both ≲ 10⁻⁵ for optical lines).

- Spin-orbit: ⟨L·S⟩ = (ħ²/2)[j(j+1) − l(l+1) − s(s+1)]. A p level gets +ħ²/2 (j = 3/2) and −ħ² (j = ½); the
  interval rule E(j) − E(j−1) ∝ j follows. Landé g_J = 1 + [j(j+1) + s(s+1) − l(l+1)]/[2j(j+1)] (g_s ≈ 2):
  4/3 for p_3/2, 2/3 for p_1/2.

## 4. Time-independent perturbation theory

| Situation | Formula | Validity |
|---|---|---|
| Nondegenerate, first order | E_n⁽¹⁾ = ⟨n\|V\|n⟩ | always the first check |
| Nondegenerate, second order | E_n⁽²⁾ = Σ_{m≠n} \|V_mn\|²/(E_n − E_m) | \|V_mn\| ≪ \|E_n − E_m\| |
| State, first order | \|n⁽¹⁾⟩ = Σ_{m≠n} \|m⟩V_mn/(E_n − E_m) | same |
| Degenerate level (g states) | diagonalise W_ij = ⟨n,i\|V\|n,j⟩; its eigenvalues are E⁽¹⁾ | splitting ≫ coupling outside |
| Asymptotic series | stop at the smallest term | error ≈ smallest term |

- The ground-state E⁽²⁾ is always < 0 (every denominator is negative); second order pushes coupled levels apart.
- Degenerate shortcut: an operator commuting with both H₀ and V (L_z for a field along z) labels the good
  zeroth-order states; in its eigenbasis W is diagonal and the nondegenerate formulas apply level by level.
- Linear Stark effect, hydrogen n = 2, V = eℰz: parity and Δm = 0 leave only |⟨2s|z|2p₀⟩| = 3a₀, so W is
  [[0, −3eℰa₀], [−3eℰa₀, 0]] in the standard phase convention, giving shifts ±3eℰa₀ for (|2s⟩ ∓ |2p₀⟩)/√2,
  while 2p±1 stay unshifted. 1s has no linear shift; its quadratic shift is −½αℰ² with α = 4.5 a₀³ (4πε₀ = 1).

## 5. Time-dependent perturbation theory

- First order: c_f(t) = (1/iħ)∫₀ᵗ V_fi(t′)e^{iω_fi t′}dt′, ω_fi = (E_f − E_i)/ħ, P_i→f = |c_f|².
- Constant V switched on at t = 0: P(t) = 4|V_fi|² sin²(ω_fi t/2)/(ħω_fi)². Summed over a continuum it grows
  linearly in t, giving the Fermi golden rule Γ = (2π/ħ)|V_fi|²ρ(E_f).
- Harmonic V(t) = F e^{−iωt} + F† e^{iωt}: absorption Γ = (2π/ħ)|F_fi|²ρ(E_i + ħω); emission uses F†.
- Validity: |V_fi|²ρ smooth over the window ħ/t, t ≫ ħ/ΔE, Γt ≪ 1 (no depletion). Beyond that, a flat continuum
  gives exponential decay at the same Γ (Wigner-Weisskopf).
- Free-particle density of states per spin: box normalisation ψ = e^{ik·r}/√𝒱 gives ρ(E)dΩ = 𝒱mk/((2π)³ħ²)dΩ,
  and 𝒱 cancels against |V_fi|² ∝ 1/𝒱; δ-normalisation ψ = e^{ik·r}/(2π)^{3/2} gives ρ(E)dΩ = (mk/ħ²)dΩ.
- Rabi (two levels, RWA coupling ⟨e|V|g⟩ = ħΩ/2, detuning Δ = ω − ω₀):
  P_e(t) = Ω²/(Ω² + Δ²)·sin²(√(Ω² + Δ²)t/2). Ωt = π at Δ = 0 is a π pulse; Ω ≪ |Δ| recovers first order. The
  RWA needs Ω, |Δ| ≪ ω₀ (the Bloch-Siegert shift is ≈ Ω²/4ω₀).

| Change over time τ | Criterion | Result |
|---|---|---|
| Sudden | τ ≪ ħ/ΔE | state frozen, P_n = \|⟨n_new\|ψ_old⟩\|²; tritium β decay leaves He⁺ in 1s with 512/729 = 0.702 |
| Adiabatic | ħ\|⟨m\|∂_tH\|n⟩\| ≪ (E_n − E_m)² | follows the instantaneous eigenstate, gains dynamic and Berry phases |
| Avoided crossing | Landau-Zener | P_diabatic = exp(−2π\|H₁₂\|²/(ħ\|d(E₁ − E₂)/dt\|)), E₁, E₂ diabatic |

## 6. Variational methods

- Rayleigh-Ritz: E₀ ≤ ⟨ψ|H|ψ⟩/⟨ψ|ψ⟩ for any ψ in the domain of H. The energy error is second order in the
  wavefunction error, so a good energy does not certify a good wavefunction (check ⟨r²⟩ or the cusp).
- Linear trial space: solve Hc = ESc (S = overlap). Hylleraas-Undheim-MacDonald: the k-th root bounds the k-th
  exact level from above and decreases monotonically as the basis grows.
- Excited states: use a trial orthogonal to all lower exact states, usually by symmetry (an odd trial bounds the
  first excited state of an even potential).
- Hydrogen with a Gaussian trial e^{−αr²}, atomic units:

```python
import sympy as sp
al, r = sp.symbols('alpha r', positive=True)
psi = sp.exp(-al*r**2)
vol = lambda f: sp.integrate(4*sp.pi*r**2*f, (r, 0, sp.oo))
T = vol(psi*(-sp.Rational(1, 2))*sp.diff(r**2*sp.diff(psi, r), r)/r**2)
E = sp.simplify((T + vol(-psi**2/r))/vol(psi**2))   # 3*alpha/2 - 2*sqrt(2)*sqrt(alpha)/sqrt(pi)
a_opt = sp.solve(sp.diff(E, al), al)[0]             # 8/(9*pi)
E.subs(al, a_opt)                                   # -4/(3*pi) = -0.4244 Ha = -11.549 eV (exact -13.606 eV)
```

  The result is 15% high, as an upper bound must be: a Gaussian misses the cusp and the exponential tail
  (3-4 Gaussians get within about 1%).
- Helium with both electrons in 1s orbitals of charge Z_eff: E(Z_eff) = Z_eff² − 2ZZ_eff + (5/8)Z_eff Ha, minimum
  at Z_eff = Z − 5/16 = 27/16, E = −(27/16)² = −2.8477 Ha (−77.49 eV) against −2.9037 Ha (1.9% high).
  First-order perturbation theory gives −2.75 Ha.

## 7. WKB

- ψ ≈ C p^{−1/2} exp(±(i/ħ)∫p dx), p = √(2m(E − V)); in the forbidden region κ = √(2m(V − E))/ħ and
  ψ ∝ κ^{−1/2} e^{±∫κ dx}.
- Quantisation, with ∮ = 2∫ from x₁ to x₂: ∮p dx = 2πħ(n + ½) for two soft turning points, 2πħ(n + ¾) for
  one hard wall, 2πħ(n + 1) for two hard walls. Exact for the oscillator and the infinite well.
- Tunnelling: T ≈ exp(−2∫κ dx) across the forbidden region (prefactor of order 1 for a thick barrier).
- Validity: |ħp′/p²| = |mħV′/p³| ≪ 1. It fails within ≈ (ħ²/(2m|V′|))^{1/3} of a turning point, where Airy
  matching gives the connection formula 2p^{−1/2}cos(∫_x^{x₂}p dx′/ħ − π/4) ↔ |p|^{−1/2}exp(−∫_{x₂}^x|p|dx′/ħ).
- Check: a particle bouncing on a hard floor, V = mgz. WKB with n + ¾ gives
  E_n = (ħ²mg²/2)^{1/3}[3π(n + ¾)/2]^{2/3}, coefficients 2.3203, 4.0818, 5.5172 against the exact Airy zeros
  2.3381, 4.0879, 5.5206 (errors 0.8%, 0.15%, 0.06%). WKB improves with n, as it should.

## 8. Scattering

- Born: f(θ) = −(m/2πħ²)∫e^{−iq·r}V(r)d³r, q = k_f − k_i, |q| = 2k sin(θ/2). Central potential:
  f = −(2m/ħ²q)∫₀^∞ rV(r)sin(qr)dr.
- Yukawa V = βe^{−μr}/r: f = −2mβ/(ħ²(μ² + q²)). μ → 0 gives Rutherford, dσ/dΩ = (β/4E)²/sin⁴(θ/2) with
  β = Z₁Z₂e²/(4πε₀), exact for pure Coulomb scattering apart from a phase.
- Validity (range a, depth V₀): at low energy m|V₀|a²/ħ² ≪ 1 (no near-threshold bound state); at high energy
  |V₀|a/(ħv) ≪ 1.
- Partial waves: f(θ) = (1/k)Σ(2l+1)e^{iδ_l}sin δ_l P_l(cos θ), σ_tot = (4π/k²)Σ(2l+1)sin²δ_l, unitarity limit
  σ_l ≤ 4π(2l+1)/k², l_max ≈ ka. Low energy: k cot δ₀ = −1/a_s + r_e k²/2 and σ → 4πa_s².
- Hard sphere: δ₀ = −ka and σ(k → 0) = 4πa², four times the geometric cross-section.
- Optical theorem σ_tot = (4π/k) Im f(0). The first-Born amplitude is real and violates it at its own order, so
  never take σ_tot from a Born f(0).

## 9. Identical particles

- Bosons are symmetric and fermions antisymmetric (Slater determinant); no two fermions share a spin-orbital.
- Two electrons: the singlet (S = 0) pairs with a symmetric spatial function, the triplet (S = 1) with an
  antisymmetric one. E = I + J ± K, + for the singlet and − for the triplet, with J the direct and K the exchange
  integral. K > 0 for the Coulomb repulsion of orthogonal orbitals, so the triplet lies lower (Hund's first rule;
  in He 1s2s the ³S level is ≈ 0.8 eV below ¹S).
- Exchange effect on separation: ⟨(x₁ − x₂)²⟩ = ⟨x²⟩_a + ⟨x²⟩_b − 2⟨x⟩_a⟨x⟩_b ∓ 2|⟨x⟩_ab|², with the upper sign
  for symmetric spatial states (bunching).
- Second quantisation: {c_i, c_j†} = δ_ij for fermions, [b_i, b_j†] = δ_ij for bosons. One-body operators are
  Σ_ij⟨i|o|j⟩c_i†c_j; two-body ½Σ_ijkl⟨ij|v|kl⟩c_i†c_j†c_l c_k (note l before k). Check [H, N̂] = 0. Hubbard
  H = −tΣ_⟨ij⟩σ c_iσ†c_jσ + UΣ_i n_i↑n_i↓ at half filling with U ≫ t maps to a Heisenberg model with J = 4t²/U.

## 10. Checks

| Check | How |
|---|---|
| Hermiticity | H = H† as a matrix; real eigenvalues; boundary terms vanish (⟨p⟩ is real only if ψ → 0 at the ends) |
| Normalisation | ∫\|ψ\|² = 1; CG tables orthonormal by rows and columns; Σ\|c_n\|² = 1 |
| Units | restore atomic units: E_h = 27.211386 eV, a₀ = 0.529177 Å, ħ/E_h = 24.189 as; every term same dimension |
| Limits | V → 0 returns the H₀ result; ħ → 0 (large n) reproduces Bohr-Sommerfeld and classical motion |
| Sum rules | Thomas-Reiche-Kuhn Σ_n f_n0 = N, f_n0 = (2m/ħ²)(E_n − E_0)\|⟨n\|x\|0⟩\|²; the oscillator has f_10 = 1 exactly |
| Commutators | [x, p] = iħ in the representation used; truncated matrices break it (Tr[x, p] = 0) |
| Signs | ground-state E⁽²⁾ < 0; E_variational ≥ E_exact; Γ ≥ 0 and σ ≥ 0; levels repel |
| Algebra | redo it in SymPy (sympy.physics.quantum, sympy.physics.wigner), see `sympy-symbolic-verification` |

## 11. Worked example: V = λx⁴ added to the oscillator

Units ħ = m = ω = 1 (λ in units of m²ω³/ħ). ⟨n|x⁴|n⟩ = 3(2n² + 2n + 1)/4 = 0.75, 3.75, 9.75, … (the matrix
check below agrees), so the ground state shifts by 3λ(ħ/2mω)² = 3λ/4. Second order: x⁴|0⟩ =
(3|0⟩ + 6√2|2⟩ + 2√6|4⟩)/4, so E⁽²⁾ = −[(9/2)/2 + (3/2)/4]λ² = −21λ²/8. The recursion gives the series
E₀ = ½ + ¾λ − (21/8)λ² + (333/16)λ³ − (30885/128)λ⁴ + …, whose coefficients grow factorially: the radius of
convergence is zero because λ < 0 is unbounded below.

```python
import numpy as np
nb = 120
a = np.diag(np.sqrt(np.arange(1, nb)), 1); x = (a + a.T)/np.sqrt(2)
X4 = np.linalg.matrix_power(x, 4)      # last 4 rows/columns corrupted by truncation; only low states matter
E0 = np.arange(nb) + 0.5
for lam in (0.01, 0.1, 1.0):
    print(lam, np.linalg.eigvalsh(np.diag(E0) + lam*X4)[0])   # 0.50725620, 0.55914633, 0.80377065
R = np.r_[0.0, 1/(E0[0] - E0[1:])]; psi = [np.eye(nb)[0]]; E = [0.5]   # RS recursion, ⟨0|ψ_k⟩ = 0
for k in range(1, 5):
    E.append(psi[0] @ X4 @ psi[k - 1])
    psi.append(R*(X4 @ psi[k - 1] - sum(E[j]*psi[k - j] for j in range(1, k + 1))))
print(E)                               # [0.5, 0.75, -2.625, 20.8125, -241.2890625]
```

| λ | exact (120 states; 200 agree to 1e-15) | 1st order | 2nd | 3rd | 4th |
|---|---|---|---|---|---|
| 0.01 | 0.5072562 | 0.5075000 | 0.5072375 | 0.5072583 | 0.5072559 |
| 0.1 | 0.5591463 | 0.5750 | 0.5488 | 0.5696 | 0.5454 |
| 1 | 0.8037707 | 1.25 | −1.375 | 19.44 | −221.9 |

At λ = 0.01 four orders reach 3 × 10⁻⁷. At λ = 0.1 the terms stop shrinking after second order
(|E⁽³⁾λ³| = 0.021 against |E⁽²⁾λ²| = 0.026), so optimal truncation leaves an error near 0.01. At λ = 1 the
series is useless. Above λ ≈ 0.05 diagonalise, as above or with `schrodinger-numerics`, or minimise over a
Gaussian of free width.

## 12. Pitfalls

- Nondegenerate formulas inside a degenerate subspace (n = 2 Stark, Zeeman with spin-orbit coupling) give
  divergent denominators or arbitrary mixing. Diagonalise W first.
- Box normalisation in ρ(E) and δ-normalisation in the matrix element; per spin versus total; 𝒱 not cancelling.
- h versus ħ: E = hν = ħω. Γ is a rate (s⁻¹); ħΓ is the energy FWHM of the Lorentzian.
- Fourier sign conventions: the Born amplitude uses e^{−iq·r} with q = k_f − k_i; flipping only one of the two
  flips the phases.
- Spin factor 2: average over initial and sum over final spin states; DOS per spin; singlet and triplet weights
  are 1 : 3.
- CG(j1, m1, j2, m2, J, M) and clebsch_gordan(j1, j2, J, m1, m2, M) take different argument orders.
- Reduced matrix elements: compare ratios only, unless the normalisation is stated.
- Hellmann-Feynman applied to non-variational approximate states gives wrong derivatives (and forces).
- WKB for low n against steep walls; Born for attractive wells with a near-threshold bound state.
- Truncated matrices: powers like x⁴ are wrong in the last rows, and [x, p] ≠ iħ at the cut.

Related: `schrodinger-numerics`, `tight-binding-band-structure`, `lagrangian-hamiltonian-mechanics`, `sympy-symbolic-verification`, `dimensional-analysis-units`, hub `physics-toolkit`
