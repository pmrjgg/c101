---
name: optics-wave-propagation
description: "Optics and wave propagation, from regime choice by Fresnel number through ABCD ray matrices, Gaussian beams and q-parameters, diffraction formulas, correctly sampled angular-spectrum and Fresnel propagation with FFTs, Fresnel equations and thin-film transfer matrices, coherence, Fabry-Perot cavities, dispersion and pulse broadening. Load when designing, estimating or simulating an optical system or wave field."
when_to_use: "Focusing a laser or sizing a spot, waist or Rayleigh range; chaining ABCD matrices or q-parameters; propagating a field with FFTs (angular spectrum, Fresnel, Fraunhofer) and choosing grid size and sampling; aliasing, ghost beams or wrap-around in a diffraction simulation; Fresnel coefficients, Brewster or TIR angles, AR coatings and multilayer stacks; coherence length, fringe visibility, Fabry-Perot finesse or FSR; group index, GVD, fibre V number or pulse broadening."
---

# Optics and wave propagation

Optical estimates fail on conventions (1/e² radius against FWHM, field against intensity, T₀ against
FWHM pulse width), and simulations fail on sampling: an aliased chirp or a wrapped field still draws a
plausible picture. The numbers below were checked in NumPy in October 2026, including the
N = 4096 angular-spectrum run of §11 and the tmm call of §7. Structures with features near λ need a
full-wave solver (`em-field-solvers-fdtd-fem`).

## 1. Regime triage

| Feature size a against λ | Regime | Method |
|---|---|---|
| a ≫ λ and N_F ≫ 1 | geometric | rays, ABCD (§2), sequential ray tracing |
| a ≳ 10λ, angles below about 0.5 rad (NA ≲ 0.5) | scalar diffraction | formulas (§4), FFT propagation (§5) |
| a ~ λ, high NA, polarisation, metals, subwavelength periods | full-wave | FDTD or FEM (`em-field-solvers-fdtd-fem`), RCWA for periodic stacks |

Fresnel number N_F = a²/(λz), a the aperture half-width or radius. N_F ≫ 1 gives the geometric shadow with
edge ripples, N_F ~ 1 Fresnel (near-field) diffraction, N_F ≪ 1 Fraunhofer: the pattern is the Fourier
transform of the aperture. Example: a = 0.5 mm, λ = 500 nm gives N_F = 1 at z = 0.5 m, so Fraunhofer needs
z ≫ 0.5 m or a lens (its focal plane is the far field). Antenna rule for the far field: z > 2D²/λ (D full width).

## 2. Paraxial rays (ABCD)

Ray vector (y, θ): height and angle. System matrix M = M_N ⋯ M₂M₁ (first element rightmost).

| Element | Matrix |
|---|---|
| Free space, length d | [[1, d], [0, 1]] |
| Thin lens, focal length f | [[1, 0], [−1/f, 1]] |
| Flat interface n₁ → n₂ | [[1, 0], [0, n₁/n₂]] |
| Curved interface, radius R (R > 0 if the centre lies after the surface) | [[1, 0], [(n₁ − n₂)/(n₂R), n₁/n₂]] |
| Mirror, radius R (concave R > 0, unfolded) | [[1, 0], [−2/R, 1]] |

- det M = n_in/n_out (1 within one medium). Imaging condition B = 0; then A is the transverse magnification and
  D = 1/A. Effective focal length f = −1/C; back focal distance −A/C.
- Thin lens 1/s_o + 1/s_i = 1/f; two thin lenses 1/f = 1/f₁ + 1/f₂ − d/(f₁f₂); thick lensmaker
  1/f = (n − 1)[1/R₁ − 1/R₂ + (n − 1)d/(nR₁R₂)].
- ABCD has no aberrations. Real designs: rayoptics, optiland or KrakenOS in Python, Zemax or CODE V.

```python
import numpy as np
free = lambda d: np.array([[1.0, d], [0.0, 1.0]])
lens = lambda f: np.array([[1.0, 0.0], [-1.0/f, 1.0]])
M = free(0.2) @ lens(0.1) @ free(0.2)     # 2f-2f imaging: [[-1, 0], [-10, -1]], B = 0, magnification -1
```

## 3. Gaussian beams

- w(z) = w₀√(1 + (z/z_R)²), z_R = πw₀²n/λ (λ in vacuum), R(z) = z[1 + (z_R/z)²], Gouy phase ψ = arctan(z/z_R),
  (m + n + 1)ψ for Hermite-Gauss HG_mn.
- q = z + iz_R and 1/q = 1/R − iλ/(πnw²); through any ABCD system q′ = (Aq + B)/(Cq + D).
- Far-field half-angle θ = λ/(πnw₀); a real beam has θ = M²λ/(πw₀) and beam parameter product w₀θ = M²λ/π.
- Lens focusing with the input waist w_in at the lens: w_f = (λf/πw_in)/√(1 + (f/z_R,in)²) at distance
  d = f/(1 + (f/z_R,in)²); for z_R,in ≫ f this is w_f ≈ λf/(πw_in) at d ≈ f. Depth of focus 2z_R.
- Radii: w is the 1/e² intensity radius; the 1/e intensity radius is w/√2; intensity FWHM = √(2 ln 2)·w = 1.1774w;
  the power inside radius r is 1 − exp(−2r²/w²) (86.5% at r = w).

```python
def q_out(q, M):
    (A, B), (C, D) = M
    return (A*q + B)/(C*q + D)
def w_of_q(q, lam, n=1.0):
    return np.sqrt(-lam/(np.pi*n*np.imag(1/q)))
lam, w0 = 632.8e-9, 2e-3
w_of_q(q_out(1j*np.pi*w0**2/lam, free(0.1) @ lens(0.1)), lam)   # 1.0071e-05 m in the focal plane
```

## 4. Diffraction formulas

| Geometry | Formula | Note |
|---|---|---|
| Single slit, width a | minima a sin θ = mλ, m = ±1, ±2, … | central lobe full width 2λ/a |
| Double slit, spacing d | maxima d sin θ = mλ | modulated by the single-slit envelope |
| Circular aperture, diameter D | first zero sin θ = 1.22λ/D; focal Airy radius 1.22λf/D = 1.22λN | 83.8% of the power in the core |
| Resolution | Rayleigh θ_min = 1.22λ/D; Sparrow ≈ 0.95λ/D | incoherent point sources |
| Grating, period d | d(sin θ_m − sin θ_i) = mλ | angles from the normal; θ_0 = θ_i is the undiffracted beam |
| Grating resolving power | R = λ/Δλ = mN | N illuminated lines |
| Grating dispersion and free spectral range | dθ/dλ = m/(d cos θ_m); Δλ_FSR = λ/m | |

Fraunhofer field: U(x, y) = e^{ikz}e^{ik(x²+y²)/2z}/(iλz)·Û₀(x/λz, y/λz); behind a lens put f in place of z.

## 5. Numerical propagation procedure

Kernels, for the time convention e^{i(kz − ωt)}:

| Kernel | Formula | Correctly sampled when |
|---|---|---|
| Angular spectrum (exact scalar) | H = exp(i2πz√(1/λ² − f_x² − f_y²)) | z ≤ z_c, or band-limited beyond |
| Fresnel transfer function (TF) | H = e^{ikz}exp(−iπλz(f_x² + f_y²)) | z ≤ z_c |
| Fresnel impulse response (IR) | h = e^{ikz}/(iλz)·exp(ik(x² + y²)/2z), FFT convolution times Δx² | z ≥ z_c |
| Single-FFT Fresnel or Fraunhofer | output pitch λz/L | far field; the output grid scales with z |

The critical distance is z_c = NΔx²/λ = LΔx/λ, equivalently Δx = λz/L: there the kernel chirp changes by π
per sample at the edge of the grid, for the frequency-domain (TF) and the space-domain (IR) kernel alike.

1. Extent L: holds the field at both planes plus a guard band. Zero-pad to at least 2× when the field spreads,
   because FFT convolution is circular and energy leaving one edge re-enters at the other.
2. Pitch Δx = L/N: resolves the finest feature and every input phase, |∂φ/∂x|Δx ≤ π. For a lens chirp
   e^{−ikr²/2f} that means Δx ≤ λf/(2r_max), r_max the radius where the field is non-negligible (≈ 3w for a Gaussian).
3. Compare z with z_c: TF or AS for z ≤ z_c, IR for z ≥ z_c. Past z_c with AS, zero H outside
   |f| ≤ 1/(λ√((2Δf·z)² + 1)) with Δf = 1/(2L) on the 2× padded grid (band-limited angular spectrum, Matsushima
   and Shimobaba 2009), or split the distance into several steps.
4. A smooth, band-limited field may relax the strict rule: the kernel phase step 2πλz f_max/L across the
   occupied bandwidth f_max must stay below π.
5. Propagate, then check energy (Parseval: Σ|U|²Δx² is conserved apart from evanescent loss) and compare one
   analytic case before trusting the run.

## 6. FFT hygiene code

```python
import numpy as np
def grid(N, L):
    dx = L/N
    x = (np.arange(N) - N//2)*dx            # x = 0 at index N//2, the fftshift convention
    return x, np.fft.fftfreq(N, dx), dx     # fftfreq is in unshifted order, matching np.fft.fft2

def angular_spectrum(U0, dx, lam, z):
    f = np.fft.fftfreq(U0.shape[0], dx)
    arg = 1/lam**2 - f[None, :]**2 - f[:, None]**2
    H = np.exp(2j*np.pi*z*np.sqrt(arg.astype(complex)))   # evanescent: sqrt -> i|.|, decays
    return np.fft.ifft2(np.fft.fft2(U0)*H)

def fresnel_tf(U0, dx, lam, z):
    f = np.fft.fftfreq(U0.shape[0], dx)
    H = np.exp(2j*np.pi*z/lam)*np.exp(-1j*np.pi*lam*z*(f[None, :]**2 + f[:, None]**2))
    return np.fft.ifft2(np.fft.fft2(U0)*H)

def ft_centered(U, dx):                     # continuous FT on a centred grid (Fraunhofer, PSFs)
    return np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(U)))*dx**2

def w_1e2(U, x):                            # 1/e² radius from the second moment of |U|² (exact for Gaussians)
    Ix = (np.abs(U)**2).sum(axis=0)
    return 2*np.sqrt((x**2*Ix).sum()/Ix.sum())
```

- Convolution propagation (AS, TF) needs no shifts when H comes from fftfreq; centred transforms and plots do.
  A centred FT without ifftshift multiplies the result by a (−1)ⁿ checkerboard.
- Never build frequencies with arange: fftfreq(N, dx) handles even and odd N and the negative half.
- With e^{i(kz − ωt)}: propagation phase +ikz, converging lens e^{−ikr²/2f}, absorbing index n + iκ. The
  opposite convention flips all three together; flipping one of them is a bug.
- Free-beam test: w₀ = 50 μm, λ = 632.8 nm, z = 2z_R = 24.8 mm, N = 2048, L = 8 mm (z_c = 49 mm). The angular
  spectrum gives w = 111.804 μm against the analytic w₀√5 = 111.803 μm.
- Large grids: scipy.fft accepts workers=-1 for threaded transforms; one 4096² complex128 array is 268 MB, so
  budget 1-2 GB for a 4096² run.

## 7. Interfaces and films

Snell's law n₁sin θ₁ = n₂sin θ₂. Fresnel amplitude coefficients:

- r_s = (n₁cos θ₁ − n₂cos θ₂)/(n₁cos θ₁ + n₂cos θ₂), t_s = 2n₁cos θ₁/(n₁cos θ₁ + n₂cos θ₂)
- r_p = (n₂cos θ₁ − n₁cos θ₂)/(n₂cos θ₁ + n₁cos θ₂), t_p = 2n₁cos θ₁/(n₂cos θ₁ + n₁cos θ₂)
- R = |r|², T = (n₂cos θ₂/n₁cos θ₁)|t|² for real indices. This r_p convention gives r_p = −r_s at normal
  incidence; other books flip r_p. R is unaffected; phases and the ellipsometric Δ are not.

- Normal incidence R = ((n₁ − n₂)/(n₁ + n₂))²: 4.0% for glass with n = 1.5.
- Brewster angle tan θ_B = n₂/n₁ (r_p = 0): 56.31° from air into glass, 33.69° from glass into air.
- Critical angle sin θ_c = n₂/n₁ for n₁ > n₂: 41.81° from glass to air. Beyond it R = 1 and the evanescent field
  decays as e^{−κz} with κ = k₀√(n₁²sin²θ − n₂²).
- Multilayer characteristic matrix (convention e^{i(kz − ωt)}, ñ = n + iκ): M_j = [[cos δ_j, −i sin δ_j/η_j],
  [−iη_j sin δ_j, cos δ_j]], δ_j = 2πñ_j d_j cos θ_j/λ, η_j = ñ_j cos θ_j (s) or ñ_j/cos θ_j (p).
  [B, C]ᵀ = M₁M₂⋯[1, η_sub]ᵀ, r = (η₀B − C)/(η₀B + C), T = 4η₀Re(η_sub)/|η₀B + C|².
- Quarter-wave AR coating: n_c = √(n₀n_s), d = λ₀/(4n_c), R(λ₀) = ((n₀n_s − n_c²)/(n₀n_s + n_c²))². MgF₂ (1.38) on
  n_s = 1.5 gives 1.41% against 4.0% bare; n_c = 1.2247 gives 0.

```python
def stack_R(ns, ds, n0, nsub, lam0):        # normal incidence; complex n allowed
    M = np.eye(2, dtype=complex)
    for n, d in zip(ns, ds):
        dl = 2*np.pi*n*d/lam0
        M = M @ np.array([[np.cos(dl), -1j*np.sin(dl)/n], [-1j*n*np.sin(dl), np.cos(dl)]])
    B, C = M @ np.array([1, nsub])
    return abs((n0*B - C)/(n0*B + C))**2
stack_R([1.38], [550e-9/(4*1.38)], 1.0, 1.5, 550e-9)            # 0.014110
import tmm                                                       # same stack, lengths in any one unit
tmm.coh_tmm('s', [1.0, 1.38, 1.5], [np.inf, 550/(4*1.38), np.inf], 0, 550)['R']   # 0.014110
```

## 8. Coherence and cavities

- Temporal coherence: τ_c ≈ 1/Δν and l_c ≈ λ²/Δλ, with a line-shape and definition-dependent prefactor between
  about 0.3 and 0.7, so state the definition. An 850 nm LED with Δλ = 40 nm has l_c ≈ 18 μm; a single-frequency
  HeNe laser has metres or more.
- Fringe visibility V = (I_max − I_min)/(I_max + I_min) = [2√(I₁I₂)/(I₁ + I₂)]|γ₁₂(τ)|.
- Spatial coherence (van Cittert-Zernike): the coherence factor is the normalised Fourier transform of the
  incoherent source intensity. A uniform disk of angular diameter α gives μ(d) = 2J₁(u)/u, u = πdα/λ, first zero
  at d = 1.22λ/α: 72 μm for sunlight (α = 9.3 mrad) at 550 nm.
- Fabry-Pérot (lossless, mirror reflectance R): round-trip phase δ = 4πnL cos θ/λ, T = 1/(1 + F sin²(δ/2)),
  coefficient of finesse F = 4R/(1 − R)², finesse ℱ = π√R/(1 − R) (29.8 at R = 0.9, 312.6 at R = 0.99),
  FSR = c/(2n_g L), linewidth δν = FSR/ℱ, Q = ν/δν, photon lifetime τ = 1/(2πδν).
- A two-mirror resonator is stable for 0 ≤ g₁g₂ ≤ 1 with g_i = 1 − L/R_i.

## 9. Dispersion and pulses

- Group index n_g = n − λ dn/dλ, v_g = c/n_g. β(ω) = n(ω)ω/c, β₁ = 1/v_g, β₂ = d²β/dω² = (λ³/2πc²)d²n/dλ²,
  D = −(2πc/λ²)β₂. Standard single-mode fibre at 1550 nm: D ≈ 17 ps/(nm km), so β₂ ≈ −21.7 ps²/km (anomalous).
- Unchirped Gaussian pulse with T₀ the 1/e intensity half-width (T_FWHM = 2√(ln 2)T₀ = 1.665T₀):
  T(z) = T₀√(1 + (z/L_D)²) with L_D = T₀²/|β₂|. With an initial chirp C: T/T₀ = √((1 + Cβ₂z/T₀²)² + (β₂z/T₀²)²).
  A 1 ps FWHM pulse in that fibre has T₀ = 0.601 ps and L_D = 16.6 m.
- Transform limit Δν·Δt ≥ 0.441 for Gaussians (both FWHM), 0.315 for sech² pulses.
- Step-index fibre: V = (2πa/λ)NA, NA = √(n_core² − n_clad²), single mode for V < 2.405, so the cutoff wavelength
  is 2πa·NA/2.405. Mode-field radius (Marcuse, 0.8 < V < 2.5): w/a ≈ 0.65 + 1.619V^{−3/2} + 2.879V^{−6}.

## 10. Tools

| Need | Tool |
|---|---|
| Custom scalar propagation | NumPy or scipy.fft with the §6 kernels |
| Laser beams and optical benches | LightPipes |
| Telescopes, coronagraphs, PSFs and wavefronts | poppy, HCIPy, prysm |
| Quick diffraction pictures | diffractsim |
| Thin-film stacks | tmm |
| Periodic structures (gratings, metasurfaces, photonic-crystal slabs) | RCWA with S4 or grcwa |
| Full-wave fields | Meep (open-source FDTD), Tidy3D (cloud FDTD), FEM via `em-field-solvers-fdtd-fem` |
| Lens design with aberrations | rayoptics, optiland, KrakenOS, Zemax, CODE V |

## 11. Worked example: focusing a HeNe beam

Given λ = 632.8 nm, w_in = 2 mm (waist at the lens) and f = 100 mm. Analytic: z_R,in = πw_in²/λ = 19.9 m ≫ f,
so w_f = λf/(πw_in) = 10.07 μm, z_R = πw_f²/λ = 0.504 mm, and the waist sits at f − 2.5 μm (§3).

Grid: N = 4096, L = 20 mm, Δx = 4.88 μm; the input support 3w = 6 mm lies inside the 10 mm half-width.
Sampling: z_c = NΔx²/λ = 154 mm ≥ f + z_R, so the AS kernel is correctly sampled; the lens chirp needs
Δx ≤ λf/(2·3w_in) = 5.27 μm, which holds; the focal spot has σ = w_f/2 = 5.0 μm ≥ Δx, so the second-moment width
is unbiased (aliasing term ≈ e^{−2π²σ²/Δx²} ≈ e^{−21}).

```python
lam, w_in, f = 632.8e-9, 2e-3, 0.1
k = 2*np.pi/lam
wf = lam*f/(np.pi*w_in); zR = np.pi*wf**2/lam                 # 10.071 μm, 0.5036 mm
x, fx, dx = grid(4096, 20e-3)
assert 4096*dx**2/lam >= f + zR and lam*f/(2*3*w_in) >= dx
R2 = x[None, :]**2 + x[:, None]**2
U0 = np.exp(-R2/w_in**2)*np.exp(-1j*k*(np.sqrt(R2 + f**2) - f))   # aberration-free (spherical) lens phase
for z in (f - zR, f, f + zR):
    print(z, w_1e2(angular_spectrum(U0, dx, lam, z), x)/wf)         # 1.4109, 1.0003, 1.4180
```

Results, about 1 s per propagation on a laptop:

| Lens phase and kernel | w(f − z_R)/w_f | w(f)/w_f | w(f + z_R)/w_f |
|---|---|---|---|
| spherical phase, angular spectrum | 1.4109 | 1.0003 | 1.4180 |
| parabolic phase e^{−ikr²/2f}, Fresnel TF | 1.4107 | 1.0001 | 1.4178 |
| parabolic phase, angular spectrum (mixed) | 1.3834 | 1.0015 | 1.4467 |
| analytic, waist exactly at f | 1.4142 | 1 | 1.4142 |

The two consistent rows match the analytic beam to 0.3%, and their ±0.25% asymmetry is the real waist shift
(a waist at f − 2.5 μm predicts 1.4107 and 1.4177). The mixed row passes every sampling test yet is 2.3% off at
f + z_R: a parabolic phase under the exact kernel is spherically aberrated, and best focus moves about
fθ²/2 ≈ 20 μm (θ = w_in/f) towards the lens, 4% of z_R. Pair paraxial phases with paraxial kernels and exact
with exact.

## 12. Pitfalls

- Paraxial formulas above NA ≈ 0.5: w_f = λf/πw fails and the focus is a vector field; use Richards-Wolf
  (Debye) integrals, and expect an elongated spot for linear polarisation.
- 1/e² radius against FWHM against 1/e radius; beam profilers often report the 1/e² diameter 2w.
- Field against intensity: a Gaussian field e^{−r²/w²} has intensity e^{−2r²/w²}, so field widths are √2 larger.
- Unshifted FFTs put the Fraunhofer pattern in the corners; a missing ifftshift adds a (−1)ⁿ phase.
- Aliased chirp: a lens or kernel phase stepping by more than π per sample makes ghost beams and a wrong focus.
  Check both z_c and the input phase.
- Wrap-around: energy that leaves the grid re-enters on the other side. Pad 2× or add an absorbing window.
- Mixed sign conventions: e^{−iωt} against e^{+iωt} flips the lens phase, the kernel and the sign of κ in n ± iκ.
- Paraxial phase with the exact kernel, or the reverse (§11).
- Pulse widths: L_D uses T₀, not the FWHM; the time-bandwidth product uses FWHM in both domains.
- Fresnel number from the diameter instead of the radius changes it by 4×.

Related: `em-field-solvers-fdtd-fem`, `pde-discretization-stability`, `uncertainty-propagation-fitting`, `dimensional-analysis-units`, `computer-graphics`, hub `physics-toolkit`
