---
name: schrodinger-numerics
description: "Numerical quantum mechanics: discretising H (finite differences, Colbert-Miller/Fourier DVR, number bases), sparse shift-invert eigensolvers, split-operator and Crank-Nicolson propagation with norm checks, spin chains by symmetry-blocked exact diagonalisation, MPS pointers, and Lindblad dynamics with QuTiP 5. Load when a QM problem needs a computer."
when_to_use: "Solving the time-independent or time-dependent Schrödinger equation on a grid or in a basis; scipy eigsh on a Hamiltonian that is slow or raises ArpackNoConvergence; wavepacket, tunnelling or scattering runs with norm drift or edge reflections; spin-chain exact diagonalisation or DMRG; QuTiP mesolve, mcsolve or steadystate runs; checking computed levels against oscillator, Morse, hydrogen or Rabi benchmarks."
---

# Schrödinger numerics

Numerical QM goes wrong in a few predictable ways. The grid is too coarse for the kinetic energy,
the box is too small for the tails, eigsh is asked for the bottom of the spectrum without
shift-invert, the propagator is not unitary or uses a real dtype, the boundaries reflect, and a
grid eigenvalue gets reported as if it were a variational bound. This skill covers each one.
Units: atomic units (ħ = m_e = e = 4πε₀ = 1) unless stated. 1 E_h = 27.211386 eV,
1 a₀ = 0.529177 Å, 1 fs = 41.341 a.u. of time, m_p = 1836.15 m_e.

Deep material: [propagators, DVR and absorbers](references/propagators-and-grids.md) |
spin chains, symmetry sectors and MPS |
double-well example, full script

## 1. Method selection

| Problem | Method | Why / limit |
|---|---|---|
| 1-3D single particle, any V | FD grid (3/5-point) + sparse eigsh | simple and sparse, O(Δx²) or O(Δx⁴) error |
| Smooth V, high accuracy | Colbert-Miller (sinc) DVR or Fourier grid | converges exponentially in Δx; dense or FFT-applied T |
| Anharmonic oscillator, cavity, few modes | number (Fock/HO) basis, truncate at n_max | Galerkin, so it gives upper bounds; converge in n_max |
| Radial problems (atoms) | FD or DVR on u(r) = rR(r), one run per l | Coulomb cusp slows FD convergence for s states |
| Spin chains, N ≲ 24-26 (S=1/2) | sparse Lanczos in symmetry sectors | memory 2^N·16 B per complex vector |
| Larger 1D (gapped or modest entanglement) | DMRG/MPS: ITensorMPS.jl, TeNPy (`physics-tenpy`), quimb | converge in bond dimension χ |
| Open systems, Markovian | QuTiP `mesolve` (ρ) or `mcsolve` (trajectories) | Born-Markov needs γ ≪ system frequencies |
| Time-dependent, 1-3D grid | split-operator FFT; Crank-Nicolson; Chebyshev | section 4 |

## 2. Grid rules

- **Spacing.** The grid represents momenta up to k_max = π/Δx. Need k_max above the largest
  relevant k = sqrt(2m E_max)/ħ, where E_max is the kinetic energy above V_min that the states
  or wavepacket reach. A 3-point FD kinetic energy is low by a relative (kΔx)²/12, so 1% needs
  kΔx ≤ 0.35 (about 18 points per wavelength). Sinc-DVR and FFT grids are exact up to kΔx = π;
  keep a 1.5× margin.
- **Box.** Tails decay like e^(-κx) with κ = sqrt(2m(V - E))/ħ beyond the turning point. Keep
  ≥ ln(1/tol)/(2κ) of forbidden region on each side, e.g. 11.5/κ for tol = 1e-10.
- **Converge Δx and L separately** and report both. Measured for the harmonic oscillator:

| Run (V = x²/2) | E₀ - 0.5 | Notes |
|---|---|---|
| FD, L = 20, Δx = 0.2 / 0.1 / 0.05 | -1.25e-3 / -3.13e-4 / -7.81e-5 | ratio 4: O(Δx²), from below |
| DVR, L = 20, Δx = 0.8 / 0.6 / 0.4 | 8.6e-7 / 3.5e-12 / 4e-15 | exponential |
| FD, Δx = 0.05, L = 6 / 8 / 10 | +2.2e-4 / -7.8e-5 / -7.8e-5 | small box pushes levels up |

## 3. Discretise and diagonalise

```python
import numpy as np, scipy.sparse as sp, scipy.sparse.linalg as spla

def fd_hamiltonian(x, V, m=1.0, hbar=1.0):          # Dirichlet walls just outside x[0], x[-1]
    dx = x[1] - x[0]; t = hbar**2 / (2 * m * dx**2)
    off = -t * np.ones(x.size - 1)
    return sp.diags_array([off, 2 * t + V(x), off], offsets=[-1, 0, 1], format="csc")

def cm_dvr(x, V, m=1.0, hbar=1.0):                   # Colbert & Miller, J. Chem. Phys. 96, 1982 (1992)
    dx = x[1] - x[0]; d = np.subtract.outer(np.arange(x.size), np.arange(x.size))
    with np.errstate(divide="ignore"):
        T = np.where(d == 0, np.pi**2 / 3, 2.0 * (-1.0) ** d / d**2)
    return hbar**2 / (2 * m * dx**2) * T + np.diag(V(x))

x = np.arange(-10, 10 + 1e-9, 0.05)
H = fd_hamiltonian(x, lambda x: 0.5 * x**2)
E, U = spla.eigsh(H, k=4, sigma=0.0, which="LM")      # shift-invert: the 4 levels nearest sigma
order = np.argsort(E); E, U = E[order], U[:, order]   # eigsh does not promise ascending order
U /= np.sqrt((x[1] - x[0]))                            # grid vector -> continuum normalisation
```

- `sigma` with `which="LM"` factorises H - σI once (SuperLU) and returns the eigenvalues
  nearest σ. Put σ slightly below the wanted level, or in the middle of an interior window.
- Measured, FD oscillator, k = 4: N = 5000 takes 0.005 s with shift-invert and 2.9 s with
  `which="SA"`. At N = 20000 it is 0.011 s versus no convergence after 39 s (maxiter 20000).
  The lowest levels of a grid Laplacian are crowded relative to its spectral width 2ħ²/(mΔx²).
- 2D/3D: H = T_x ⊗ I ⊗ I + I ⊗ T_y ⊗ I + I ⊗ I ⊗ T_z + diag(V) via `sp.kron`. Shift-invert
  still works up to ~10⁶ unknowns in 3D. Beyond that use LOBPCG with a preconditioner or a
  split-operator imaginary-time relaxation.
- Number basis: x = (a + a†)/√2, p = i(a† - a)/√2 with a = diag(√n, 1). For
  p² + x² + 0.1x⁴, E₀ = 1.06528551 (Hioe-Montroll) is converged at n_max = 20 and reached from
  above. Code: [propagators and grids](references/propagators-and-grids.md).

## 4. Time evolution

| Propagator | Unitary | Error | Use when |
|---|---|---|---|
| Split-operator FFT, Strang e^(-iVdt/2) e^(-iTdt) e^(-iVdt/2) | yes | O(dt²) global | periodic/absorbing grid, local V, many steps |
| Crank-Nicolson (1 + iHdt/2)ψ' = (1 - iHdt/2)ψ | yes (Cayley) | O(dt²); phase of level E becomes (2/dt)·arctan(E dt/2) | sparse H, non-FFT geometry, Dirichlet walls |
| `expm_multiply(-1j*H*t, psi)` | to tolerance | adaptive | reference values, moderate ‖H‖t (cost ∝ ‖H‖₁t) |
| Chebyshev (Tal-Ezer-Kosloff) | to 1e-12+ | exponential once K > ΔE·t/2 | long steps, time-independent H, high accuracy |
| Runge-Kutta on iψ' = Hψ | no | norm drifts | avoid for long runs |

```python
k = 2 * np.pi * np.fft.fftfreq(N, d=dx)               # angular wavenumbers in fft order
half = np.exp(-0.5j * V * dt); kin = np.exp(-0.5j * k**2 * dt / m)
for n in range(nsteps):                                # psi must be complex128
    psi = half * np.fft.ifft(kin * np.fft.fft(half * psi))

I = sp.eye_array(N, format="csc", dtype=complex)       # Crank-Nicolson: factorise once
lu = spla.splu((I + 0.5j * dt * H).tocsc()); B = (I - 0.5j * dt * H).tocsr()
for n in range(nsteps):
    psi = lu.solve(B @ psi)
```

Measured: CN on the FD oscillator (N = 2000) keeps the norm to 2e-14 per period. A coherent
state returns to ⟨x⟩ = 2 within 1.5e-4 (dt = 0.02) and 3e-5 (dt = 0.01). `expm_multiply` over
the same period took 7.2 s against 0.03 s for CN, because ‖H‖ ≈ 2/Δx². CN distortion: a component
at E = 1000 with dt = 0.01 propagates at the phase rate of E_eff = 275, so keep E_max·dt/2 ≪ 1.

Monitor every ~100 steps and log it:

| Quantity | Healthy | Otherwise |
|---|---|---|
| norm Σ\|ψ\|²Δx | 1 to ~1e-11 (unitary schemes) | decay without an absorber means a real dtype, non-Hermitian H or a bug |
| ⟨H⟩ (static H) | constant to O(dt²) | drift: dt too large, or a time-dependent term leaks in |
| \|ψ\| at the box edge | < 1e-8 | reflections or wrap-around (section 5) |
| \|ψ̃(k)\| near ±π/Δx | < 1e-8 | aliasing: refine Δx |

## 5. Boundaries and aliasing

- FFT grids are periodic: a packet leaving at +L/2 re-enters at -L/2. FD with Dirichlet walls
  reflects instead. Either way, physics needs an absorber or a bigger box.
- Complex absorbing potential: H → H - iW(x), W = η(|x| - x_c)² for |x| > x_c (in split-operator
  multiply by e^(-W dt/2)). Measured, quadratic CAP, k₀ = 2 and 5 packets: width 5, η = 0.05
  leaves 2-19% in the interior. Width 20, η = 0.005 leaves 2.5e-5 for fast packets (too weak:
  transmission). Width 20, η = 0.05 leaves 7e-7 for slow packets (too strong: reflection).
  Width 40 (≈ 13 wavelengths of the slowest part), η = 0.002 leaves ≤ 1e-12 for both. Rule:
  width ≥ several de Broglie wavelengths of the slowest component. Double W and halve η, and
  accept when the observable does not move.
- Masks (multiply ψ by cos^(1/8) over the last ~10% of the box each step) are cheap
  alternatives. Use them only when the absorbed flux is not an observable.
- Momentum cap: |k| ≤ π/Δx. A packet accelerated past it aliases to -k, so watch |ψ̃(k)|.
- Phase per step: |V|Δt/ħ ≪ π for the potential half-steps, and changes of V(t) must be
  resolved. Halve dt and compare observables, not just the norm.

## 6. Spin systems

- Build H from Kronecker products of local operators (`sp.kron`), from `qutip.tensor` for small
  N, or with QuSpin (`spin_basis_1d(L, Nup=L//2, pauli=0, kblock=0, pblock=1, zblock=1)` plus
  `hamiltonian(static, [], basis=basis)`).
- Block-diagonalise before diagonalising. Total S^z (or particle number) is a bit count, then
  translation (momentum k), reflection parity and spin inversion. The S^z = 0 sector of N = 24
  has C(24,12) = 2,704,156 states, and k, parity and inversion shrink it by about 4N more.
- Memory: a full complex128 vector is 2^N·16 B, so N = 20 needs 16.8 MB, N = 24 needs
  16,777,216 amplitudes = 268 MB, and N = 28 needs 4.3 GB. Lanczos keeps ~20 vectors plus the
  sparse matrix, so use matrix-free H·v above ~N = 24.
- Lanczos on many-body H: `eigsh(H, k=1, which="SA")` is fine here, because nothing is cheap
  to factorise. Reference: periodic Heisenberg chain E₀ = -7.1422963606 (N = 16) and
  -8.9043865299 (N = 20), against Bethe 1/4 - ln 2 = -0.443147 per site at N → ∞. Sector code:
  spin chains.
- Beyond ED: DMRG/MPS for 1D (and 2D cylinders of width ≲ 6-10). Converge the energy and
  correlations in χ, and report the truncation error.

## 7. Open systems with QuTiP 5

```python
import numpy as np, qutip as qt                      # verified with QuTiP 5.3
N, gamma = 15, 0.2
a = qt.destroy(N); H = a.dag() * a
res = qt.mesolve(H, qt.ket2dm(qt.fock(N, 3)), np.linspace(0, 10, 101),
                 c_ops=[np.sqrt(gamma) * a], e_ops=[a.dag() * a], options={"store_states": True})
# res.expect[0][-1] = 0.4060059 vs 3 e^{-2} = 0.4060058
rho = res.states[-1]; assert abs(rho.tr() - 1) < 1e-10 and rho.eigenenergies().min() > -1e-10
Hd = qt.QobjEvo([0.25 * qt.sigmaz(), [0.5 * qt.sigmax(), lambda t, w: np.cos(w * t)]], args={"w": 1.0})
rss = qt.steadystate(0.3 * a.dag() * a + 0.5 * (a + a.dag()), [np.sqrt(gamma) * a])
# <a>_ss = -1.4999935 - 0.4999978j vs analytic -iE/(gamma/2 + i*Delta) = -1.5 - 0.5j
mc = qt.mcsolve(H, qt.fock(N, 3), np.linspace(0, 10, 101), c_ops=[np.sqrt(gamma) * a],
                e_ops=[a.dag() * a], ntraj=500, seeds=1, options={"progress_bar": False})
```

- In QuTiP 5 `e_ops`, `args` and `options` are keyword-only, and options is a dict. Results are
  in `res.expect` (list), with states only if `store_states` is set.
- Collapse operators carry the rate: `sqrt(gamma) * L`. A thermal bath at occupation n_th uses
  `sqrt(gamma*(n_th+1))*a` and `sqrt(gamma*n_th)*a.dag()`.
- Check that tr ρ = 1, ρ = ρ† and min eig ρ ≥ -1e-10 at the end. Increase N until populations
  of the top Fock states fall below 1e-6.
- Born-Markov validity: γ ≪ the system frequencies and the bath correlation time ≪ 1/γ. When
  they fail (strong coupling, structured baths), use HEOM (`qutip.solver.heom`) or a
  pseudo-mode model and say so.

## 8. Validation benchmarks

| System | Exact | Measured here (FD) |
|---|---|---|
| Harmonic oscillator | E_n = ħω(n + ½); virial ⟨T⟩ = ⟨V⟩ | ⟨T⟩ = 0.2500000, ⟨V⟩ = 0.2499969 (Δx = 0.01) |
| Infinite well, width L | E_n = n²π²ħ²/(2mL²) | interior points only, N = 200: 4.93470 vs 4.93480 |
| Morse D(1 - e^(-a(x - x₀)))² | E_v = ħω(v + ½) - [ħω(v + ½)]²/(4D), ω = a·sqrt(2D/m); bound v < sqrt(2mD)/(aħ) - ½ | D = 10, a = 1: 2.111055 vs 2.111068 |
| Pöschl-Teller -(ħ²α²/2m)λ(λ-1)sech²(αx) | E_n = -(ħ²α²/2m)(λ - 1 - n)², n < λ - 1 | λ = 5: -8.000011, -4.500036 vs -8, -4.5 |
| Hydrogen, u(r) = rR | -½(u'' ) + [-Z/r + l(l+1)/(2r²)]u = Eu, E_n = -Z²/(2n²) | dr = 0.005: 1s -0.4999969 (above), 2p -0.12500007 (below) |
| Rabi, detuning Δ, coupling Ω | P_e = (Ω²/W²)·sin²(Wt/2), W = sqrt(Ω² + Δ²) | `sesolve` max error 4.4e-6 |
| Anharmonic p² + x² + 0.1x⁴ | E₀ = 1.0652855095 | number basis, n_max = 20: 1.06528551 |

Virial check for any bound state in V ∝ r^n: 2⟨T⟩ = n⟨V⟩ (hydrogen 2⟨T⟩ = -⟨V⟩). A violation
beyond discretisation error means a bug in T or in the normalisation.

## 9. Variational or not

- Galerkin/basis results (HO basis, Gaussians, finite elements) are Rayleigh-Ritz upper bounds
  for every computed level (Hylleraas-Undheim-MacDonald).
- FD eigenvalues are not bounds. The 3-point kinetic operator underestimates k² by (kΔx)²/12,
  so smooth problems converge from below (oscillator, Morse, Pöschl-Teller, well). The Coulomb s
  states above converge from above, because the cusp at r = 0 is under-resolved.
- DVR is not variational either (V by quadrature): the oscillator n = 3 level came out 3e-3
  low at Δx = 0.8.
- So label every reported number "variational upper bound", "grid value, converged to ±δ"
  or "extrapolated". Never bracket an exact value with two FD runs alone.

## 10. Performance

- Store H as CSR for products and CSC for factorisation. Factorise once per (H, dt) and reuse
  (`splu`, or shift-invert's internal LU).
- Large FFT grids: use FFT sizes with small prime factors (2^a·3^b·5^c). `scipy.fft` with
  `workers=-1`, pyFFTW, CuPy (`cupy.fft`) or JAX (`jax.numpy.fft`, 64-bit needs
  `jax.config.update("jax_enable_x64", True)`). Matrix-free H·v for spin chains above N ≈ 24.
- Precision: do convergence studies in float64/complex128. Use float32/complex64 in production
  only after a side-by-side run shows the observable is unchanged at the reported precision.
  Phases of long propagations accumulate float32 error like ~1e-7·(number of steps).

## 11. Worked example: double-well tunnelling

V(x) = V₀(x²/a² - 1)², V₀ = 6, a = 1.5, m = ħ = 1. Harmonic well frequency
ω = sqrt(8V₀)/a = 4.6188, barrier V₀/(ħω/2) = 2.6. Full script:
double-well example.

1. **Splitting from FD** (`eigsh`, σ = 0, L = 12):

| Δx | E₀ | ΔE = E₁ - E₀ |
|---|---|---|
| 0.04 | 2.16698010 | 2.75985605e-2 |
| 0.02 | 2.16764985 | 2.75986496e-2 |
| 0.01 | 2.16781721 | 2.75986646e-2 (Richardson 2.7598668e-2) |

   L = 6 shifts ΔE by +6.5e-6 relative, and L ≥ 8 changes it by < 1e-9. Report
   ΔE = 2.759867e-2 E_h, a converged grid value with no bound implied.
2. **WKB check**: ΔE ≈ (ħω_cl/π)·exp(-∫|p|dx/ħ), with the integral between the inner turning
   points at E = (E₀ + E₁)/2 and ω_cl the classical frequency there. Result 2.5505e-2 (-7.6%).
   Garg (Am. J. Phys. 68, 430, 2000) shows the textbook prefactor is low by sqrt(e/π) for the
   ground doublet. Multiplying by sqrt(π/e) = 1.075 gives 2.742e-2 (-0.65%). Evaluated at the
   harmonic energy ħω/2 the same formula is +25% here and only reaches +6% at
   V₀/(ħω/2) = 9.5. Trust WKB for the exponent and treat its O(1) prefactor as a cross-check.
3. **Dynamics**: Fourier grid N = 512 on L = 12 (k_max = 134) gives ΔE = 2.7598669e-2, the same
   as FD. Start in ψ = (φ₀ + φ₁)/√2 (right well) and propagate split-operator for 2.2 periods.
   P_R(t) = ∫_{x>0}|ψ|² swings 0.9989 → 0.0009 with period 2πħ/ΔE = 227.66. A cosine fit gives
   Ω/ΔE - 1 = +5.5e-4, +1.4e-4 and +3.4e-5 for dt = 0.02, 0.01 and 0.005 (O(dt²)). The norm
   error is ≤ 1.4e-11 after 10⁵ steps.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| eigsh runs for minutes or raises `ArpackNoConvergence` | `which="SA"` on a grid Laplacian, or an interior level without shift-invert | `sigma=E_guess, which="LM"` |
| norm decays, or the packet freezes | real dtype (`np.exp(-1j*...)` cast into a float array), or `V*dt` without `1j` | allocate ψ as complex128 and assert `psi.dtype.kind == "c"` |
| levels shuffled, wrong state plotted | shift-invert returns them in no fixed order; near-degenerate pairs mix | sort by eigenvalue and classify by parity or overlap, not by index |
| doublet "splitting" is noise | ΔE below eigensolver tolerance (~1e-14·\|E\|) | check tol, use the symmetric/antisymmetric sectors separately |
| interference fringes appear late in a run | boundary reflection or FFT wrap-around | CAP or mask, bigger box, edge monitor |
| levels move when the box grows | box too small (an upward shift) | converge L separately from Δx |
| packet momentum flips sign | k exceeded π/Δx (aliasing) | smaller Δx, watch \|ψ̃(k)\| at the edge |
| wrong energy scale by 2π | `fftfreq` returns cycles per length | k = 2π·fftfreq(N, dx) |
| amplitudes off by sqrt(Δx) | grid vector normalised to 1, not ∫\|ψ\|²dx = 1 | divide eigenvectors by sqrt(Δx) |
| Coulomb levels converge slowly | s-state cusp on a uniform grid | finer grid near r = 0, log/mapped grid, or a basis |
| mesolve gives tr ρ ≠ 1 or negative populations | non-Lindblad c_ops, truncation N too small, or tolerances too loose | check Fock tail populations, tighten `atol`/`rtol` in options |

Related: `quantum-mechanics-methods`, `pde-discretization-stability`, `physics-ode-integrators`, `quantum-circuit-simulators`, `hamiltonian-simulation-methods`, `matrix-decompositions-conditioning`, `simulation-verification-validation`; hub `physics-toolkit`.
