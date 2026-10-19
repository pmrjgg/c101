# Propagators, grids, DVR and absorbers

Every snippet below was run with NumPy 2.5 / SciPy 1.18, and the outputs quoted are from those
runs. Atomic units, m = ħ = 1 unless the code says otherwise.

## 1. Kinetic operators and their accuracy

| Representation | Kinetic matrix | Error for a plane wave e^(ikx) |
|---|---|---|
| FD 3-point | (ħ²/2mΔx²)·tridiag(-1, 2, -1) | E_FD/E = (2 - 2cos kΔx)/(kΔx)² ≈ 1 - (kΔx)²/12 |
| FD 5-point | (ħ²/2mΔx²)·(1, -16, 30, -16, 1)/12 | O((kΔx)⁴) |
| Colbert-Miller sinc DVR (infinite grid) | T_ii = (ħ²/2mΔx²)·π²/3, T_ij = (ħ²/2mΔx²)·2(-1)^(i-j)/(i-j)² | exact for \|k\| < π/Δx |
| Fourier grid (periodic) | T = F⁻¹ diag(ħ²k²/2m) F | exact for \|k\| < π/Δx |

Measured (oscillator V = x²/2, L = 20): the 5-point stencil gives E₀ - 0.5 = -1.65e-5 at Δx = 0.2
and -1.04e-6 at Δx = 0.1 (ratio 16, so O(Δx⁴)). The 3-point stencil gives -1.25e-3 and -3.13e-4.

```python
# 5-point FD Hamiltonian (Dirichlet), O(dx^4)
c = 1 / (24 * dx**2)                               # = (hbar^2/2m) / (12 dx^2) with m = hbar = 1
H5 = sp.diags_array([c*np.ones(n-2), -16*c*np.ones(n-1), 30*c + V(x), -16*c*np.ones(n-1), c*np.ones(n-2)],
                    offsets=[-2, -1, 0, 1, 2], format="csc")

# Fourier-grid Hamiltonian (dense, N <~ 4000), consistent with the split-operator propagator
k = 2 * np.pi * np.fft.fftfreq(N, d=dx)
T = np.fft.ifft(0.5 * k[:, None]**2 * np.fft.fft(np.eye(N), axis=0), axis=0)
H = T + np.diag(V(x)); H = 0.5 * (H + H.conj().T)     # symmetrise round-off
E, U = np.linalg.eigh(H)
```

## 2. Multidimensional grids

```python
T1 = sp.diags_array([-t*np.ones(n-1), 2*t*np.ones(n), -t*np.ones(n-1)], offsets=[-1, 0, 1], format="csr")
I = sp.eye_array(n, format="csr")
X, Y = np.meshgrid(x, x, indexing="ij")             # ravel order must match the kron order
H2 = (sp.kron(T1, I) + sp.kron(I, T1) + sp.diags_array(V2(X, Y).ravel())).tocsc()
E = np.sort(spla.eigsh(H2, k=6, sigma=0.0, which="LM", return_eigenvectors=False))
# 2D oscillator, dx = 0.1: [0.99937 1.99812 1.99812 2.99562 2.99562 2.99687]  (1, 2, 2, 3, 3, 3)
```

Degenerate levels split by O(Δx²) on a Cartesian grid. Do not read physics into that.

## 3. Number (HO) basis

```python
n = np.arange(nmax)
a = np.diag(np.sqrt(n[1:]), 1)                       # annihilation, truncated
x = (a + a.T) / np.sqrt(2); p2 = -((a - a.T) @ (a - a.T)) / 2
H = p2 + x @ x + 0.1 * np.linalg.matrix_power(x, 4)   # Hioe-Montroll normalisation p^2 + x^2 + g x^4
E = np.linalg.eigvalsh(H)
# nmax = 10: 1.06528559, nmax = 20: 1.06528551 (literature 1.0652855095)
```

Truncation edge: `x @ x` built from truncated `x` is wrong in the last row and column. Discard
the top ~10% of levels, and converge the levels you keep in n_max. Results approach from above.

## 4. Imaginary-time relaxation (ground states of large grids)

```python
hv = np.exp(-0.5 * V * tau); kt = np.exp(-0.5 * k**2 * tau)
for i in range(3000):
    psi = hv * np.fft.ifft(kt * np.fft.fft(hv * psi))
    psi /= np.sqrt(np.sum(abs(psi)**2) * dx)          # renormalise every step
# oscillator, N = 256, L = 20, tau = 0.01: E0 = 0.5000000000
```

Excited states need Gram-Schmidt against the lower states every step, or a symmetry-restricted
start. Convergence slows as e^(-(E₁ - E₀)τ), so near-degenerate doublets need many steps.

## 5. Crank-Nicolson details

- The propagator (1 + iHdt/2)⁻¹(1 - iHdt/2) is unitary for Hermitian H. The phase of
  eigencomponent E advances at E_eff = (2/dt)·arctan(E dt/2) ≈ E - E³dt²/12. Components with
  E·dt/2 ≳ 0.3 carry visible phase errors even though the norm is perfect.
- Factorise once with `spla.splu(A.tocsc())` and reuse it. Rebuild only when H(t) or dt changes.
  For time-dependent H use the midpoint H(t + dt/2).
- Dirichlet walls (FD) reflect. Add the CAP to H as -iW, which makes A non-Hermitian. That is
  fine for `splu`.

## 6. expm_multiply and Krylov

```python
psis = spla.expm_multiply(-1j * dt * H, psi0, start=0, stop=nsteps, num=nsteps + 1, endpoint=True)
# psis[n] = exp(-i H n dt) psi0 ; cost grows with ||H||_1 * t
```

FD grids have ‖H‖ ≈ 2ħ²/(mΔx²), so this is slow for long times. One oscillator period on N = 2000
took 7.2 s against 0.03 s for CN. Use it for reference values and short steps, or apply it to a
spectrally truncated H.

## 7. Chebyshev propagator (Tal-Ezer and Kosloff 1984)

```python
from scipy.special import jv
Emin, Emax = 0.0, 4*t + Vmax                         # spectral bounds (Gershgorin is fine)
a, b = (Emax - Emin) / 2 * 1.01, (Emax + Emin) / 2    # 1% safety margin keeps H_norm inside [-1, 1]
def cheb_prop(psi, T):
    z = a * T; K = int(z + 10 * z**(1/3) + 20)       # Bessel J_n(z) decays once n > z
    p0, p1 = psi, (H @ psi - b * psi) / a
    out = jv(0, z) * p0 + 2 * (-1j) * jv(1, z) * p1
    for n in range(2, K + 1):
        p0, p1 = p1, 2 * (H @ p1 - b * p1) / a - p0
        out += 2 * (-1j)**n * jv(n, z) * p1
    return np.exp(-1j * b * T) * out
# oscillator, dx = 0.05, T = pi: K = 1478 terms, max |cheb - expm_multiply| = 5.8e-12
```

The spectral bounds must enclose the whole spectrum, or the series diverges. Static H only
(for H(t) use short steps with a Magnus midpoint).

## 8. Absorbing boundaries

```python
xc = L/2 - W                                           # absorber starts here, both sides
Wcap = np.where(np.abs(x) > xc, eta * (np.abs(x) - xc)**2, 0.0)
expV = np.exp(-0.5j * V * dt) * np.exp(-0.5 * Wcap * dt)    # split-operator half step with H - iW
absorbed = 1 - np.sum(abs(psi)**2) * dx                     # track it: this is the outgoing flux
```

Measured probability left in the interior after the packet should have gone (N = 4096, L = 200):

| CAP width W | η | k₀ = 2 (λ = 3.1) | k₀ = 5 (λ = 1.3) |
|---|---|---|---|
| 5 | 0.05 | 1.7e-2 | 1.9e-1 |
| 20 | 0.005 | 7.0e-9 | 2.5e-5 (too weak, wraps around) |
| 20 | 0.05 | 7.0e-7 (too strong, reflects) | 3.8e-10 |
| 40 | 0.002 | 1.1e-12 | 2e-19 |

Mask alternative: multiply ψ each step by m(x) = cos^(1/8)(π(|x| - x_c)/(2W)) inside the strip.
It is cheap and robust but not a Hermitian-plus-absorber model, so flux bookkeeping is approximate.

## 9. Time-step and grid checklist for a propagation

1. Δx from the largest momentum the packet reaches, including acceleration by V: k_max·Δx ≤ π/1.5
   (FFT) or ≤ 0.35 (3-point FD at 1%).
2. dt: |V|max·dt/ħ ≲ 0.1-0.3 rad per half step, E_max·dt/2ħ ≪ 1 for CN, and every external
   period resolved by ≥ 20 steps.
3. Box and absorber: no density above 1e-8 reaches the outer 10% unabsorbed.
4. Two runs, (Δx, dt) and (Δx/2, dt/2): report observables from both with their difference.
