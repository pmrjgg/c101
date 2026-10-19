---
name: fluid-dynamics-cfd
description: "Fluid dynamics, convective heat transfer and CFD basics: regime triage from Re/Ma/Kn, analytic anchor flows and correlations, boundary layers, incompressible projection/PISO solvers, turbulence-model and y+ choice, OpenFOAM/SU2/Basilisk/LBM set-up, mesh checks and validation benchmarks. Load when modelling a flow or heat-transfer problem or setting up or reviewing a CFD case."
when_to_use: "Estimating drag, pressure drop, a heat-transfer coefficient or a boundary-layer thickness; deciding laminar vs turbulent, compressible vs incompressible or continuum vs rarefied; writing a projection or PISO solver; choosing a turbulence model, wall treatment or first-cell height; setting up or debugging OpenFOAM, SU2, Basilisk, Dedalus or LBM; checkMesh failures; a mesh-independence (GCI) study; validating against the lid-driven cavity, backward-facing step or cylinder wake."
---

# Fluid dynamics and CFD

CFD answers fail in five repeatable ways: the wrong regime (laminar/turbulent, compressible,
continuum), a wall treatment that does not match the mesh (y+), an integral quantity that is not
converged in iterations or in mesh, no analytic anchor or validation case, and a correlation
quoted outside its range. All numbers are SI; every dimensionless group names its length scale.
Numbers marked "computed" were run with NumPy/SciPy in October 2026.

## 1. Regime triage

Write each choice as an assumption with its number, for example "Re_D = 5.0e4, turbulent; Ma =
7e-4, incompressible; Kn ≈ 1e-9, continuum".

| Group | Definition | Thresholds and consequence |
|---|---|---|
| Re | UL/ν | ≪ 1 Stokes (linear, reversible). Pipe: < 2300 laminar, 2300–4000 transitional, > 4000 turbulent. Flat plate transition Re_x ≈ 5e5 (3e5–3e6 with free-stream turbulence). Cylinder shedding from Re ≈ 47 |
| Ma | U/a, a = sqrt(γRT) (343 m/s, air 20 °C) | < 0.3 incompressible (Δρ/ρ ≈ Ma²/2 < 5 %); 0.3–0.8 compressible subsonic; 0.8–1.2 transonic shocks; > 5 hypersonic, real-gas effects |
| Kn | λ/L (λ ≈ 68 nm, air at STP) | < 0.01 continuum Navier-Stokes; 0.01–0.1 slip/jump BCs; 0.1–10 transitional (DSMC, BGK/Boltzmann); > 10 free molecular |
| We, Fr, Bo | ρU²L/σ, U/sqrt(gL), ΔρgL²/σ | free surface: We ≳ 10 drop break-up; Fr ≈ 1 critical open-channel flow; Bo ≪ 1 capillary-dominated (capillary length of water 2.7 mm) |
| Ra, Ri | gβΔTL³/(να), gβΔTL/U² | Rayleigh-Bénard onset Ra_c = 1708 (rigid walls); vertical plate turbulent above Ra ≈ 1e9; Ri ≪ 0.1 forced, 0.1–10 mixed, ≫ 10 natural convection |
| Ro | U/(fL), f Coriolis parameter | Ro ≪ 1 rotation dominates (geostrophic balance) |
| Pr, Sc | ν/α, ν/D | δ_T/δ ≈ Pr^(-1/3) for Pr ≳ 1; liquid metals (Pr ≪ 1) need separate correlations |

## 2. Anchor solutions

Check every CFD set-up against the closest analytic flow first.

- Hagen-Poiseuille pipe: Q = πR⁴Δp/(8μL), u_max = 2ū, Darcy f = 64/Re_D.
- Couette: u = Uy/h, wall stress μU/h. Plane Poiseuille: Q per unit width = h³Δp/(12μL).
- Stokes drag F = 6πμRv (Re ≲ 0.1–1); terminal velocity v_t = 2Δρ g R²/(9μ).
- Sphere drag, Schiller-Naumann: C_D = 24/Re·(1 + 0.15 Re^0.687) for Re ≲ 800; Newton regime
  C_D ≈ 0.44 for 1e3 < Re < 2e5; drag crisis near Re ≈ 3e5.
- Blasius laminar plate: δ₉₉ ≈ 5.0x/√Re_x, local C_f = 0.664/√Re_x, mean C_D = 1.328/√Re_L,
  δ* = 1.72x/√Re_x. Turbulent plate (1/7 law): δ ≈ 0.37x Re_x^(-1/5), C_f ≈ 0.0592 Re_x^(-1/5).
- Pipe friction (Darcy, Δp = f(L/D)ρū²/2): Blasius f = 0.316 Re^(-1/4) (4e3 < Re < 1e5);
  Colebrook 1/√f = −2 log₁₀(ε/(3.7D) + 2.51/(Re√f)) (Moody chart); Haaland
  1/√f = −1.8 log₁₀[(ε/D/3.7)^1.11 + 6.9/Re], explicit and within ~2 % of Colebrook.
- Kolmogorov scale η = (ν³/ε)^(1/4), η/L ~ Re^(-3/4); DNS needs ~(L/η)³ ~ Re^(9/4) points
  (and ~Re³ total work), so DNS is a research tool above Re ~ 1e4.

```python
import numpy as np
def friction_factor(Re, rel_rough=0.0):
    if Re < 2300: return 64/Re
    f = (-1.8*np.log10((rel_rough/3.7)**1.11 + 6.9/Re))**-2       # Haaland start
    for _ in range(50):                                            # Colebrook fixed point
        f = (-2*np.log10(rel_rough/3.7 + 2.51/(Re*np.sqrt(f))))**-2
    return f
```

## 3. Convective heat transfer

Correlations carry ±10–25 % scatter; a CFD result inside that band is not "wrong".

| Configuration | Correlation | Range |
|---|---|---|
| Turbulent pipe | Dittus-Boelter Nu = 0.023 Re^0.8 Pr^n, n = 0.4 heating, 0.3 cooling | Re > 1e4, 0.6 < Pr < 160, L/D > 10 |
| Turbulent pipe (better) | Gnielinski Nu = (f/8)(Re − 1000)Pr / (1 + 12.7√(f/8)(Pr^(2/3) − 1)), f = (0.79 ln Re − 1.64)⁻² | 3e3 < Re < 5e6 |
| Laminar pipe, developed | Nu = 3.66 (uniform T_w), 4.36 (uniform q) | thermal entry ≈ 0.05 Re Pr D |
| Laminar plate | Nu_x = 0.332 Re_x^(1/2) Pr^(1/3) | Pr > 0.6 |
| Natural convection, vertical plate | Churchill-Chu Nu = {0.825 + 0.387 Ra^(1/6)/[1 + (0.492/Pr)^(9/16)]^(8/27)}² | all Ra |
| Natural convection, horizontal cylinder | Churchill-Chu Nu_D = {0.60 + 0.387 Ra_D^(1/6)/[1 + (0.559/Pr)^(9/16)]^(8/27)}² | Ra_D ≤ 1e12 |
| Cylinder in cross-flow | Churchill-Bernstein Nu = 0.3 + 0.62 Re^(1/2) Pr^(1/3)/[1 + (0.4/Pr)^(2/3)]^(1/4) · [1 + (Re/282000)^(5/8)]^(4/5) | Re·Pr > 0.2 |
| Radiation | h_rad ≈ 4εσT_m³ (exact εσ(T_s² + T_∞²)(T_s + T_∞)) | add in parallel with h_conv |

Thermal resistance network: R_conv = 1/(hA), R_wall = L/(kA), cylindrical shell
ln(r₂/r₁)/(2πkL); series resistances add, parallel paths (convection + radiation) add as
conductances. Biot Bi = hL_c/k < 0.1 allows a lumped solid. When the solid conduction and the
fluid boundary layer interact (heat sinks, cooled turbine blades) solve conjugate heat transfer:
`chtMultiRegionFoam` in OpenFOAM ESI; Foundation 11+ uses `foamMultiRun` with fluid and solid
modules (version-dependent).

## 4. Boundary layers

- Laminar thickness δ/L ~ Re^(-1/2); turbulent viscous sublayer thickness ~5ν/u_τ.
- Matched asymptotics: the outer inviscid (Euler or potential) solution gives U_e(x) and p(x);
  the inner Prandtl equations keep ∂p/∂y = 0; matching requires u_inner(y → ∞) = U_e(x).
  The displacement thickness δ* feeds back on the outer flow (interactive boundary layers).
- An adverse pressure gradient (dp/dx > 0) decelerates the near-wall fluid until τ_w = 0:
  separation. Thwaites: θ² = (0.45ν/U_e⁶)∫U_e⁵dx, λ = (θ²/ν)dU_e/dx, laminar separation at
  λ ≈ −0.09. Turbulent layers resist separation longer; predicting the turbulent separation point
  is where RANS models differ most (prefer SST, section 6).
- Law of the wall: u⁺ = y⁺ for y⁺ < 5, buffer 5–30, log law u⁺ = (1/κ)ln y⁺ + B with κ = 0.41,
  B ≈ 5.0–5.2 for 30 < y⁺ ≲ 0.1–0.2 δ⁺.

## 5. Incompressible solvers

Chorin projection, one step:

1. Advect and diffuse: u* = uⁿ + Δt[−(u·∇)u + ν∇²u + f] (explicit, or implicit diffusion).
2. Pressure Poisson: ∇²φ = ∇·u*/Δt.
3. Project: uⁿ⁺¹ = u* − Δt∇φ. Plain projection gives O(Δt) pressure; incremental pressure
   correction recovers second order.

Grids: a staggered MAC grid has no pressure checkerboard; collocated finite volume needs Rhie-Chow
face-flux interpolation. Pressure-velocity coupling: SIMPLE for steady flows (under-relax, or
SIMPLEC with `consistent yes`), PISO for transient flows at Courant < 1 with 2 correctors,
PIMPLE for Courant > 1 with outer correctors. Explicit time steps: advective Courant
|u|Δt/Δx ≈ 0.5 (≤ 1), viscous Δt ≤ Δx²/(2dν). Semi-Lagrangian advection (Stam's Stable Fluids)
is unconditionally stable but numerically diffusive: right for graphics, wrong for drag or Nu
(`computer-graphics`).

Pseudo-spectral projection with a Taylor-Green check (computed: N = 64, Courant 0.5, Heun steps,
t = 2, ν = 0.01: max velocity error 6.1e-9, max |∇·u| 1.2e-14, kinetic energy decays exactly
as e^(−4νt)):

```python
import numpy as np
N, nu = 64, 0.01; x = np.arange(N)*2*np.pi/N; X, Y = np.meshgrid(x, x, indexing="ij")
k = np.fft.fftfreq(N, 1/N); KX, KY = np.meshgrid(k, k, indexing="ij"); K2 = KX**2 + KY**2
K2i = np.where(K2 == 0, 0.0, 1/np.where(K2 == 0, 1, K2))
d = lambda f, K: np.real(np.fft.ifft2(1j*K*np.fft.fft2(f)))
lap = lambda f: np.real(np.fft.ifft2(-K2*np.fft.fft2(f)))
def project(u, v):                                    # remove the gradient part (step 2 + 3)
    uh, vh = np.fft.fft2(u), np.fft.fft2(v); ph = -(1j*KX*uh + 1j*KY*vh)*K2i
    return np.real(np.fft.ifft2(uh - 1j*KX*ph)), np.real(np.fft.ifft2(vh - 1j*KY*ph))
def rhs(u, v):                                        # step 1: advection + diffusion
    return (-(u*d(u, KX) + v*d(u, KY)) + nu*lap(u), -(u*d(v, KX) + v*d(v, KY)) + nu*lap(v))
u, v = np.sin(X)*np.cos(Y), -np.cos(X)*np.sin(Y)      # exact: same shape times exp(-2 nu t)
dt = 0.5*(2*np.pi/N)/1.0; nsteps = int(np.ceil(2.0/dt)); dt = 2.0/nsteps
for _ in range(nsteps):
    a1, b1 = rhs(u, v); us, vs = project(u + dt*a1, v + dt*b1)
    a2, b2 = rhs(us, vs); u, v = project(u + 0.5*dt*(a1 + a2), v + 0.5*dt*(b1 + b2))
```

## 6. Turbulence models and wall treatment

| Flow | Model | Notes |
|---|---|---|
| Adverse pressure gradient, separation, internal flows | k-ω SST | engineering default; y⁺ ≈ 1 or wall functions |
| Free shear (jets, mixing layers), industrial high Re | realizable k-ε | wall functions, y⁺ 30–300 |
| External aero, attached boundary layers | Spalart-Allmaras | one equation, y⁺ ≈ 1 |
| Strong swirl or curvature | Reynolds-stress model or SST with curvature correction | eddy-viscosity models miss secondary flows |
| Massive unsteady separation (bluff bodies) | DDES (SST-based) | RANS near walls, LES in the wake |
| Resolved turbulence | LES with WALE or dynamic Smagorinsky | resolve ≥ ~80 % of TKE (Pope); wall-resolved needs y⁺ ≲ 1, Δx⁺ ≲ 100, Δz⁺ ≲ 30 |
| Laminar-turbulent transition | γ-Re_θ SST | y⁺ ≈ 1 and fine streamwise spacing |

Wall rules: y⁺ = y u_τ/ν. Resolved walls need y⁺ ≈ 1 with 10–15 cells across the boundary layer
and growth ratio ≤ 1.2. Wall functions need y⁺ 30–300 (log layer). Avoid the buffer layer
(5–30) unless an all-y⁺ formulation is used (for example OpenFOAM's
`nutUSpaldingWallFunction`). First-cell height: take C_f from a correlation (section 2),
τ_w = C_f ρU²/2, u_τ = sqrt(τ_w/ρ), y = y⁺ν/u_τ. In cell-centred FV codes y⁺ refers to the cell
centre, so the first cell is 2y thick.

## 7. Tools (2026)

| Tool | Use |
|---|---|
| OpenFOAM ESI (v2412, v2506) / Foundation (12, 13) | general FV: incompressible, compressible, multiphase, CHT; Foundation 11+ runs modular solvers via `foamRun -solver incompressibleFluid` (version-dependent) |
| SU2 8.x | compressible aerodynamics, discrete adjoint shape optimisation |
| Basilisk | adaptive quadtree/octree, VOF multiphase, surface tension |
| Dedalus v3 | spectral convection, stratified and rotating flows |
| LBM: Palabos, waLBerla, lbmpy | complex/porous geometry, GPUs; keep lattice Ma < 0.1, relaxation τ > 0.5, ν = c_s²(τ − 1/2)Δt |
| JAX-Fluids, PhiFlow | differentiable CFD, ML coupling |
| ParaView, pyvista | post-processing (foamToVTK output, VTK/VTU) |

## 8. OpenFOAM workflow (ESI names; Foundation differences noted)

```bash
blockMesh                                 # background hex mesh from system/blockMeshDict
surfaceFeatureExtract                     # ESI; Foundation: surfaceFeatures
snappyHexMesh -overwrite                  # castellate, snap, add layers
checkMesh -allGeometry -allTopology       # max non-orthogonality < 70, skewness < 4, aspect ratio < 1000
simpleFoam > log.simpleFoam               # steady RANS; pimpleFoam transient; icoFoam laminar transient
foamMonitor -l postProcessing/<residualsFunctionObject>/0/<file>.dat
simpleFoam -postProcess -func yPlus       # needs the turbulence model, so run through the solver
# Foundation 13 (reported usage): foamPostProcess -solver incompressibleFluid -func yPlus
foamToVTK                                 # then ParaView or pyvista
```

`system/fvSchemes` and `system/fvSolution` for steady SST (second order everywhere):

```
divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U);
             div(phi,k) bounded Gauss limitedLinear 1; div(phi,omega) bounded Gauss limitedLinear 1;
             div((nuEff*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear corrected; }   // "limited corrected 0.5" if non-orth > 70
solvers { p { solver GAMG; smoother GaussSeidel; tolerance 1e-7; relTol 0.01; }
          "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; } }
SIMPLE { nNonOrthogonalCorrectors 0; consistent yes;
         residualControl { p 1e-5; U 1e-6; "(k|omega)" 1e-6; } }
relaxationFactors { equations { U 0.9; ".*" 0.9; } }
```

## 9. Mesh and boundary-condition rules

1. Grid convergence: three meshes with refinement ratio r ≥ 1.3; observed order
   p = ln|(f₃ − f₂)/(f₂ − f₁)|/ln r; GCI_fine = 1.25|(f₂ − f₁)/f₁|/(r^p − 1); report the fine
   value with GCI as its discretisation uncertainty (`simulation-verification-validation`).
2. Domain: inlet ≥ 5 D upstream of a body, outlet ≥ 10 D downstream (≥ 20 D for wakes), blockage
   < ~5 % or correct for it; developed internal flow needs ~4.4 D Re^(1/6) of entry length or
   periodic/mapped inlets.
3. Inlet turbulence must be stated: intensity I (1 % low, 5 % medium, 10 % high), k = 1.5(UI)²,
   length scale ℓ ≈ 0.07 D_h, ω = √k/(C_μ^(1/4)ℓ), ε = C_μ^(3/4)k^(3/2)/ℓ, C_μ = 0.09.
4. Convergence: monitor integral quantities (C_D, C_L, Δp, Nu, mass imbalance < 0.1 %) until they
   change < 0.1 % over ~1000 iterations; residuals falling 3 orders is necessary, not sufficient.
   Unsteady runs: discard the start-up transient and average over ≥ 10–20 shedding periods.

## 10. Validation benchmarks

| Case | Quantity | Reference |
|---|---|---|
| Lid-driven cavity, Re = 100 | primary vortex at (0.6172, 0.7344); centreline u_min = −0.21090 at y = 0.4531 | Ghia, Ghia & Shin 1982 |
| Lid-driven cavity, Re = 1000 | primary vortex at (0.5313, 0.5625); u_min = −0.38289 at y = 0.1719 | Ghia et al. 1982 |
| Backward-facing step | reattachment x_r/h ≈ 6.26 (turbulent, Driver & Seegmiller 1985), 6.28 (DNS Re_h = 5100, Le, Moin & Kim 1997); laminar x_r(Re) from Armaly et al. 1983 | RANS typically within 10–15 % |
| Cylinder, Re = 100 (2D laminar) | St ≈ 0.164–0.166, mean C_D ≈ 1.33–1.35, C_L amplitude ≈ 0.33 | blockage < 5 %, ≥ 20 D wake |
| Taylor-Green 2D | u = sin x cos y e^(−2νt), exact | code verification (section 5) |
| Taylor-Green 3D, Re = 1600 | dissipation peak ≈ 0.013 near t ≈ 9 | DNS (Brachet et al.; van Rees et al. 2011) for LES/DNS schemes |
| Turbulent channel | mean profile, Reynolds stresses at Re_τ = 180–5200 | Moser, Kim & Mansour 1999; Lee & Moser 2015 |

## 11. Worked example: water in a 5 cm pipe at 1 m/s (computed)

Water at 20 °C: ρ = 998.2 kg/m³, μ = 1.002e-3 Pa·s, ν = 1.004e-6 m²/s, Pr = 7.0, k = 0.598 W/(m·K).

1. Re_D = vD/ν = 1 × 0.05/1.004e-6 = 4.98e4: turbulent. Ma = 1/1480 ≈ 7e-4: incompressible.
   Smooth wall assumed.
2. Blasius f = 0.316 Re^(-1/4) = 0.0212. Colebrook gives 0.0209 and Haaland 0.0207, so the
   friction factor is known to ±2 %.
3. Δp/L = fρv²/(2D) = 0.0212 × 998.2 × 1/(2 × 0.05) = 211 Pa/m.
4. τ_w = fρv²/8 = 2.64 Pa, u_τ = v·sqrt(f/8) = 0.0514 m/s, Re_τ = u_τR/ν = 1281.
5. First cell: y⁺ = 1 needs y = ν/u_τ = 19.5 μm (cell-centred: first cell ≈ 39 μm thick); wall
   functions at y⁺ = 30 put the centroid at 0.59 mm.
6. If the wall heats the water: Dittus-Boelter Nu = 287 (h = 3430 W/(m²·K)), Gnielinski Nu = 328
   (h = 3930). The 13 % spread is the correlation uncertainty to quote.
7. Entry length ≈ 4.4 D Re^(1/6) = 1.33 m (27 D): a shorter CFD domain needs a periodic or
   mapped inlet to be "fully developed".
8. Kolmogorov η ≈ D Re^(-3/4) = 15 μm; DNS at Re^(9/4) ≈ 4e10 points is out of reach for a design
   question, so use SST with y⁺ ≈ 1 and check Δp/L against 211 Pa/m (within ~5 %).

## 12. Pitfalls

- Steady RANS on an inherently unsteady flow (bluff-body wakes, Re > 47 cylinders): residuals
  stall and the "answer" depends on the iteration count. Run transient (URANS, DDES).
- Wall functions at y⁺ < 30, or y⁺ ≈ 1 meshes with a high-Re model: the wall shear is wrong.
- First-order upwind in production results: it smears gradients like a large viscosity; use it
  only to start a run, then switch to linearUpwind or limitedLinear.
- An incompressible solver at Ma > 0.3, or an LBM run at lattice Ma > 0.1.
- 2D simulations compared with 3D turbulent data (turbulence is 3D; 2D cylinder runs above
  Re ≈ 190 miss the 3D wake transition).
- Residual drops taken as convergence while C_D or Δp still drift; no mesh study; outlet
  boundaries cutting through a recirculation zone (backflow at the outlet).
- Correlations applied outside their range (Dittus-Boelter at Re = 3000, Schiller-Naumann at
  Re = 1e4) and quoted to three significant figures.

Related: `pde-discretization-stability`, `simulation-verification-validation`, `dimensional-analysis-units`, `uncertainty-propagation-fitting`, `computer-graphics`, `molecular-dynamics-setup`, hub `physics-toolkit`
