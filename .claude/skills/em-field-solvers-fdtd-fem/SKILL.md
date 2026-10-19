---
name: em-field-solvers-fdtd-fem
description: "Electromagnetics problem solving and field solvers: Maxwell in media, interface conditions, skin depth, waveguide and cavity formulas, SI/Gaussian translation, then FDTD (Yee grid, Courant, PML, Meep/openEMS/Tidy3D) and FEM (Nédélec elements, FEniCSx/Palace/Elmer) set-up and validation. Load for any field, antenna, waveguide or EM simulation task."
when_to_use: "Computing fields, capacitance, inductance, skin depth, surface resistance, waveguide cutoffs or cavity modes; setting up Meep, openEMS, Tidy3D, FEniCSx/dolfinx, Palace, Elmer or MFEM; choosing FDTD vs FEM vs MoM; a Courant or PML instability; spurious modes in an eigen-solve; R + T > 1; converting a formula between SI and Gaussian units; validating against Mie, cavity, dipole or Fresnel results."
---

# Electromagnetic field solvers: FDTD and FEM

EM results fail in five repeatable ways: the wrong regime (quasi-static vs full-wave), a sign or
phasor convention mixed between sources (loss turns into gain, power off by 2), a grid that does
not resolve the in-material wavelength or the skin depth, absorbing boundaries that reflect or
touch evanescent fields, and no normalisation or benchmark run. Numbers marked "computed" were
run with NumPy/SciPy in October 2026; solver APIs are stated with the version they assume.

## 1. Triage by size and frequency

| Regime | Test | Equations | Methods |
|---|---|---|---|
| Electrostatics | no time dependence, or L ≪ λ with no currents | ∇·(ε∇φ) = −ρ | FD/FEM Poisson, BEM, images |
| Magnetostatics | DC currents | ∇×(μ⁻¹∇×A) = J | FEM A-formulation, Biot-Savart |
| Quasi-static eddy currents | L ≪ λ but δ ≈ conductor size | ∇×(μ⁻¹∇×A) + jωσA = J_s | FEM A-V; impedance boundary when δ ≪ mesh |
| Full wave | L ≈ 0.1λ…100λ | curl equations | FDTD (broadband, transients), FEM (resonances, complex geometry, dispersive data at few frequencies), MoM/BEM (open metallic radiators, wires) |
| Electrically huge | L ≫ 100λ | asymptotic | ray tracing, physical optics, GO/UTD |
| Layered or periodic optics | planar stacks, gratings | Fresnel / Bloch | transfer matrix (`tmm`), RCWA (S4) |

Skin depth δ = sqrt(2/(ωμσ)) (valid for σ ≫ ωε) decides between volume meshing of conductors and
a surface impedance. Time domain suits broadband responses and transients; frequency domain
suits narrow bands, high-Q resonances and tabulated dispersive materials (`optics-wave-propagation`
for beam and diffraction problems).

## 2. Core formulas (SI)

- Maxwell: ∇·D = ρ, ∇·B = 0, ∇×E = −∂B/∂t, ∇×H = J + ∂D/∂t; D = εE, B = μH, J = σE.
- Interfaces (normal n̂ from 1 to 2): n̂×(E₂ − E₁) = 0; n̂×(H₂ − H₁) = K_s (zero without
  surface current); n̂·(D₂ − D₁) = σ_s; n̂·(B₂ − B₁) = 0.
- Poynting S = E×H; time average ⟨S⟩ = ½Re(E×H*) for peak phasors, Re(E×H*) for RMS phasors.
- η₀ = sqrt(μ₀/ε₀) = 376.730 Ω (computed); plane wave |E|/|H| = η₀/n.
- Larmor power P = q²a²/(6πε₀c³); short dipole R_rad = 80π²(l/λ)², half-wave dipole 73.1 Ω,
  directivity 1.64 (2.15 dBi).
- Good conductor: Z_s = (1 + j)/(σδ), surface resistance R_s = 1/(σδ), loss per area
  ½R_s|H_t|² with peak |H_t|.
- Rectangular waveguide a × b: f_c(TE/TM_mn) = (c/2)sqrt((m/a)² + (n/b)²) (c → c/n when filled);
  λ_g = λ/sqrt(1 − (f_c/f)²). WR-90 (22.86 × 10.16 mm): TE10 6.557 GHz, TE20 13.114 GHz, TE01
  14.754 GHz (computed), so single-mode operation lies between 6.56 and 13.1 GHz.
- Rectangular cavity a × b × d: f_mnp = (c/2)sqrt((m/a)² + (n/b)² + (p/d)²); TE₁₀₁ of
  22.86 × 10.16 × 25 mm is 8.885 GHz (computed). Q = ωW/P_loss.
- Fresnel at normal incidence R = ((n₁ − n₂)/(n₁ + n₂))² (air-glass n = 1.5: 4 %); Brewster
  tan θ_B = n₂/n₁.

## 3. Unit systems

State SI or Gaussian next to every formula and translate whole formulas with the substitution
table in `dimensional-analysis-units`; never combine fields computed in two systems. Two checks
of a translation: Coulomb q₁q₂/(4πε₀r²) becomes q₁q₂/r², and Larmor q²a²/(6πε₀c³) becomes
2q²a²/(3c³) (ε₀ → 1/(4π)). Codes use their own units: Meep sets c = 1 with a chosen length a,
so frequency f = a/λ; openEMS and Palace work in SI with a mesh unit you declare.

## 4. FDTD procedure (Yee grid)

1. Resolution: Δx ≤ λ_min/(10–20) with λ_min = c/(n_max f_max); also resolve the thinnest layer
   (≥ 2–3 cells) or rely on subpixel averaging (Meep default) instead of staircased boundaries.
2. Time step from the Courant number S = cΔt/Δx: S ≤ 1 (1D), 1/√2 (2D), 1/√3 (3D); in general
   Δt ≤ 1/(c·sqrt(Σ1/Δxᵢ²)). Meep fixes S = 0.5. Computed 1D check: S = 1.0 stays bounded for
   2000 steps, S = 1.01 reaches 1.5e227.
3. Numerical dispersion (computed, 1D, phase-velocity error): S = 0.5 gives −1.27 % at 10
   cells/λ and −0.31 % at 20; S = 0.99 gives −0.034 % and −0.008 %. Phase error accumulates:
   20 cells/λ at S = 0.5 drifts ~1 rad over 50 wavelengths, so long paths need finer grids.
4. PML 8–16 cells thick (polynomial grading order 3–4, target reflection 1e-6..1e-8), at least
   λ/2 from scatterers and evanescent tails; periodic structures use Bloch boundaries.
5. Dispersive media by auxiliary differential equations: Drude ε = ε_∞ − ω_p²/(ω² + iγω)
   (e^(−iωt)) via ∂J/∂t + γJ = ε₀ω_p²E; Lorentz poles similarly. Fit the poles over the band you
   simulate (Meep `meep.materials`, Tidy3D fitters).
6. Sources and stopping: a Gaussian pulse covering the band; run until the field at a monitor
   decays by 1e-6..1e-9; spectra from DFT monitors divided by a normalisation run.
7. Convergence: double the resolution; quantities of interest must change below tolerance.

## 5. Meep (pymeep) snippet: transmission with a normalisation run

```python
import meep as mp, numpy as np
fcen, df, nfreq = 0.645, 0.2, 101                 # a = 1 µm, so f = a/λ: λ = 1.55 µm -> 0.645
cell, pml = mp.Vector3(16, 8, 0), [mp.PML(1.0)]
wg = mp.Block(mp.Vector3(mp.inf, 0.5, mp.inf), material=mp.Medium(index=3.45))
src = [mp.Source(mp.GaussianSource(fcen, fwidth=df), component=mp.Ez,
                 center=mp.Vector3(-6, 0), size=mp.Vector3(0, 2))]
def run(geometry, minus=None):                    # resolution 40 -> 18 cells per wavelength in Si
    sim = mp.Simulation(cell_size=cell, boundary_layers=pml, geometry=geometry, sources=src, resolution=40)
    refl = sim.add_flux(fcen, df, nfreq, mp.FluxRegion(center=mp.Vector3(-5, 0), size=mp.Vector3(0, 3)))
    tran = sim.add_flux(fcen, df, nfreq, mp.FluxRegion(center=mp.Vector3(5, 0), size=mp.Vector3(0, 3)))
    if minus is not None:
        sim.load_minus_flux_data(refl, minus)     # subtract the incident field from the reflection monitor
    sim.run(until_after_sources=mp.stop_when_fields_decayed(50, mp.Ez, mp.Vector3(5, 0), 1e-6))
    return sim, refl, tran
sim0, refl0, tran0 = run([wg])                    # 1) mandatory normalisation run without the device
incident = np.array(mp.get_fluxes(tran0)); minus = sim0.get_flux_data(refl0)
gap = mp.Block(mp.Vector3(0.2, 0.5, mp.inf), material=mp.air)      # 2) device: 200 nm air gap
sim1, refl1, tran1 = run([wg, gap], minus)        # later objects take precedence
R = -np.array(mp.get_fluxes(refl1))/incident; T = np.array(mp.get_fluxes(tran1))/incident
radiated = 1 - R - T                              # must be >= 0; negative means a set-up error

# Resonances and Q with Harminv: sim is a resonator run (ring, cavity, defect) with a pulse inside it
h = mp.Harminv(mp.Ez, mp.Vector3(0.3, 0), fcen, df)
sim.run(mp.after_sources(h), until_after_sources=300)
for m in h.modes: print(m.freq, m.Q, abs(m.amp), m.err)            # keep small-err modes only
```

## 6. FEM procedure (frequency domain)

1. Weak form of ∇×(μ_r⁻¹∇×E) − k₀²ε_r E = −jk₀η₀J (e^(+jωt)): find E in H(curl) with
   ∫ μ_r⁻¹(∇×E)·(∇×v̄) − k₀²ε_r E·v̄ dΩ + boundary terms = −jk₀η₀∫J·v̄ dΩ.
2. Use curl-conforming Nédélec (`N1curl`) elements: they enforce tangential continuity only.
   Nodal Lagrange elements produce spurious modes and miss field singularities at corners.
3. Mesh with about 5–10 second-order elements per wavelength (more in resonators, curved
   elements on curved boundaries) and ≥ 3 elements across δ inside conductors, or a surface
   impedance boundary with Z_s = (1 + j)/(σδ) when δ is far below the element size.
4. Open problems: PML (complex coordinate stretching) or first-order absorbing boundaries placed
   ≥ λ/4–λ/2 from scatterers.
5. Eigenmodes: Kx = k²Mx has a large null space of gradient fields at k = 0; use shift-and-invert
   (SLEPc) with a target k² above zero and discard near-zero eigenvalues. Q from complex
   eigenvalues, Q = Re ω/(2 Im ω), or from energies, Q = ωW/P_loss.

```python
# dolfinx 0.10 sketch (complex PETSc build): driven PEC box, 2nd-order Nédélec
from mpi4py import MPI
import numpy as np, ufl
from dolfinx import mesh, fem
from dolfinx.fem.petsc import LinearProblem
k0 = 2*np.pi*10e9/299792458.0
msh = mesh.create_box(MPI.COMM_WORLD, [np.zeros(3), np.array([0.02286, 0.01016, 0.05])],
                      [12, 6, 30], mesh.CellType.tetrahedron)
V = fem.functionspace(msh, ("N1curl", 2))
E, v = ufl.TrialFunction(V), ufl.TestFunction(V)
x = ufl.SpatialCoordinate(msh)
J = ufl.as_vector((0, ufl.exp(-((x[0] - 0.0114)**2 + (x[2] - 0.01)**2)/1e-6), 0))
a = ufl.inner(ufl.curl(E), ufl.curl(v))*ufl.dx - k0**2*ufl.inner(E, v)*ufl.dx
L = -1j*k0*376.73*ufl.inner(J, v)*ufl.dx
fdim = msh.topology.dim - 1
walls = mesh.locate_entities_boundary(msh, fdim, lambda x: np.full(x.shape[1], True))
E0 = fem.Function(V); E0.x.array[:] = 0                         # PEC: tangential E = 0
bc = fem.dirichletbc(E0, fem.locate_dofs_topological(V, fdim, walls))
Eh = LinearProblem(a, L, bcs=[bc], petsc_options_prefix="maxwell_",
                   petsc_options={"ksp_type": "preonly", "pc_type": "lu",
                                  "pc_factor_mat_solver_type": "mumps"}).solve()
```

## 7. Tool map (2026)

| Tool | Method | Use |
|---|---|---|
| FEniCSx / dolfinx | FEM (Python/C++) | custom weak forms, N1curl elements, PETSc/SLEPc solvers |
| scikit-fem | FEM (pure Python) | small 2D/3D problems, teaching, quick checks |
| MFEM | FEM (C++, high order, GPU) | large-scale and high-order EM |
| Elmer | FEM multiphysics | eddy currents, magnetostatics, coupled thermal |
| Palace (AWS) | FEM on MFEM | eigenmodes, driven, transient, electrostatic and magnetostatic runs; energy participation ratios for superconducting circuits |
| openEMS | FDTD (EC-FDTD) | antennas, microstrip and PCB structures; Python and MATLAB interfaces |
| Meep | FDTD | photonics, Harminv resonances, adjoint optimisation |
| Tidy3D | cloud FDTD (commercial) | large photonics jobs, Python API, paid credits |
| COMSOL | FEM (commercial) | interop via LiveLink or the MPh Python package |
| NEC2 / PyNEC, bempp-cl | MoM, BEM | wire antennas; boundary-element scattering |
| gmsh | meshing | geometry, physical groups and mesh fields for all FEM tools above |

## 8. Statics quick methods

- Method of images: a charge q at height h above a grounded plane acts with an image −q at −h;
  a grounded sphere of radius R places q′ = −qR/d at R²/d.
- Capacitance from field energy C = 2U/V²; inductance L = Φ/I = 2U/I².
- Poisson by SOR with ω_opt = 2/(1 + sin(π/N)) on an N-interval square grid, or multigrid
  (`pde-discretization-stability`); converge the residual below the discretisation error.
- Fringe-field check, circular plates (Kirchhoff, d ≪ R): C ≈ ε₀[πR²/d + R(ln(16πR/d) − 1)].
  R = 10 mm, d = 1 mm: ideal 2.78 pF, with fringing 3.24 pF (+17 %). A solver that returns
  2.78 pF has not resolved the fringe field or put the boundary too close.

## 9. Validation benchmarks

| Benchmark | Check |
|---|---|
| Mie sphere | Q_ext, Q_sca against miepython 3.x (`efficiencies_mx(m, x)`; it takes the index as n − iκ, absorbing κ ≥ 0); small spheres against Rayleigh Q_sca = (8/3)x⁴\|(m² − 1)/(m² + 2)\|² |
| Rectangular cavity | f_mnp from section 2; degeneracies preserved; Q of copper walls from R_s |
| Parallel-plate capacitor | Kirchhoff fringing formula (section 8) |
| Dipole | sin²θ far-field pattern, R_rad = 80π²(l/λ)², 73.1 Ω half-wave |
| Fresnel interface | R and T versus angle, Brewster angle for TM |
| Energy and reciprocity | R + T + A = 1 for passive structures; S₂₁ = S₁₂ for reciprocal media |

## 10. Worked example: copper at 1 GHz (computed)

σ = 5.96e7 S/m, μ = μ₀, ω = 2π·1e9 s⁻¹.

1. δ = sqrt(2/(ωμ₀σ)) = sqrt(2/(6.283e9 × 1.2566e-6 × 5.96e7)) = 2.06 μm.
2. R_s = 1/(σδ) = 1/(5.96e7 × 2.0616e-6) = 8.14 mΩ; Z_s = R_s(1 + j).
3. Loss for a tangential field of 1 A/m peak: ½R_s|H_t|² = 4.07 mW/m² (8.14 mW/m² if the
   1 A/m is RMS: the factor-2 pitfall).
4. Verify with an eddy-current FEM solve: 1D half-space, H'' = jωμ₀σH, H(0) = 1, domain 10δ,
   linear elements; Z_s = −H'(0)/(σH(0)) with the flux taken from the assembled residual of the
   first row (variationally consistent).

| Elements per δ | R_s from consistent flux | Error | X_s | Error with one-sided dH/dx |
|---|---|---|---|---|
| 1 | 7.491 mΩ | −8.0 % | 8.843 mΩ | −19.8 % |
| 2 | 7.971 mΩ | −2.1 % | 8.310 mΩ | −7.0 % |
| 3 | 8.064 mΩ | −0.9 % | 8.214 mΩ | −3.6 % |
| 10 | 8.132 mΩ | −0.08 % | 8.146 mΩ | −0.4 % |
| 20 | 8.137 mΩ | −0.02 % | 8.140 mΩ | −0.1 % |

Three elements per δ already give R_s within 1 % with the consistent flux; differentiating the
field at the surface needs about 3× more elements for the same accuracy.

```python
import numpy as np, scipy.sparse as sp, scipy.sparse.linalg as spla
mu0, sigma, w = 1.25663706212e-6, 5.96e7, 2*np.pi*1e9
delta = np.sqrt(2/(w*mu0*sigma)); k2 = 1j*w*mu0*sigma
ne = 30; h = 10*delta/ne; n = ne + 1; off = np.ones(n - 1)          # 3 elements per delta
dK = np.full(n, 2/h); dK[[0, -1]] = 1/h; dM = np.full(n, 4*h/6); dM[[0, -1]] = 2*h/6
A = (sp.diags([dK, -off/h, -off/h], [0, 1, -1]) + k2*sp.diags([dM, off*h/6, off*h/6], [0, 1, -1])).tocsr()
H = np.zeros(n, complex); H[0] = 1.0
H[1:] = spla.spsolve(A[1:, 1:].tocsc(), -A[1:, 0].toarray().ravel())
Zs = (A[0] @ H)[0]/sigma                                              # 8.064e-3 + 8.214e-3j ohm
```

## 11. Pitfalls

- Time convention: physics e^(−iωt) gives ε = ε′ + iε″ with ε″ > 0 for loss; engineering e^(jωt)
  gives ε′ − jε″. Mixing them turns absorbers into gain media and flips the sign of Im Z.
- Peak vs RMS phasors: a factor 2 in every power, loss and Poynting result.
- No normalisation run, or a reflection monitor without the incident field subtracted, giving
  R + T > 1.
- PML touching evanescent fields or placed too close to the structure; PML across a material
  boundary that is not invariant through the layer.
- Mesh too coarse inside conductors (fewer than ~3 elements per δ) or a lossy volume mesh where a
  surface impedance belongs.
- Lagrange elements for curl-curl problems; trusting the near-zero eigenvalues of a Nédélec
  eigensolve as physical modes.
- Meep frequencies are in units of c/a: forgetting f = a/λ shifts every spectrum.

Related: `optics-wave-propagation`, `pde-discretization-stability`, `dimensional-analysis-units`, `quantum-computing`, `simulation-verification-validation`, hub `physics-toolkit`
