---
name: pde-discretization-stability
description: "Choosing and stabilising grid discretisations (FD, FV, spectral, FEM) for diffusion, advection, wave, Poisson and Schrödinger equations: CFL and von Neumann analysis, Crank-Nicolson pitfalls, limiters, boundary conditions, and sparse solvers with preconditioners. Load when building or debugging a grid-based PDE solver."
when_to_use: "Writing or debugging an FD, FV, spectral or FEM solver; checkerboard or exponential blow-up; ringing next to a step or shock; smeared or wiggly fronts; a shock moving at the wrong speed; convergence order below the design order; choosing a time step from CFL or diffusion limits; picking CG, GMRES, MINRES, AMG or ILU; setting up FEniCSx, Dedalus, PETSc, PyAMG, Gridap or Trixi."
---

# PDE discretisation and stability

Grid solvers fail in five repeatable ways: a time step past a stability limit (checkerboard
blow-up), a stable but inaccurate scheme (Crank-Nicolson ringing, upwind smearing, dispersive
wiggles), a non-conservative form for shocks, boundary conditions that lower the order, and a
linear solve converged far past (or short of) the discretisation error. Numbers marked
"computed" were run with NumPy/SciPy in October 2026.

## 1. Scheme table

| Equation | Default scheme | Notes |
|---|---|---|
| Diffusion u_t = D∇²u | Crank-Nicolson with Rannacher start-up, or BDF2 | FTCS only for quick checks; CN rings on rough data (section 4) |
| Advection u_t + c·∇u = 0 | upwind (1st), Lax-Wendroff (2nd, dispersive), TVD MUSCL + limiter or WENO5 + SSP-RK3 | CFL limit; limiters for discontinuities |
| Conservation laws with shocks | finite volume, Godunov-type flux (Roe + entropy fix, HLLC, Rusanov) + limiter | conservative form mandatory |
| Wave u_tt = c²∇²u, Maxwell | leapfrog in time, centred in space; Yee staggering for Maxwell | multi-D Courant limit |
| Poisson / Laplace | multigrid, FFT (periodic or rectangular), CG + AMG | iterate only to the discretisation error |
| Schrödinger iψ_t = Hψ | Crank-Nicolson (Cayley form, unitary) or Strang split-step Fourier | norm conserved to round-off (`schrodinger-numerics`) |
| Smooth periodic problems | pseudo-spectral (FFT) with RK4/ETDRK4; 2/3-rule dealiasing of quadratic terms | exponential convergence |
| Complex geometry | FEM (Lagrange P1/P2; H(curl)/H(div) elements for vector fields) | SUPG stabilisation when advection dominates |

## 2. Stability limits

| Scheme | Condition |
|---|---|
| Upwind or Lax-Wendroff advection, 1D | ν = \|c\|Δt/Δx ≤ 1 |
| Unsplit upwind, d dimensions | Σᵢ \|cᵢ\|Δt/Δxᵢ ≤ 1 |
| FTCS diffusion | r = DΔt/Δx² ≤ 1/2 in 1D; Σᵢ DΔt/Δxᵢ² ≤ 1/2, i.e. r ≤ 1/(2d) on a uniform grid |
| FTCS advection-diffusion | ν² ≤ 2r ≤ 1 |
| FTCS pure advection | unconditionally unstable |
| Method of lines: RK4 + central advection | ν ≤ 2√2 ≈ 2.83 (imaginary-axis bound); RK4 + diffusion r ≤ 2.785/4 |
| Leapfrog wave, 1D | cΔt/Δx ≤ 1 |
| 3D leapfrog / Yee | cΔt ≤ 1/sqrt(1/Δx² + 1/Δy² + 1/Δz²), i.e. S = cΔt/Δx ≤ 1/√3 on a cube grid |
| Central differencing of advection-diffusion (steady or implicit) | cell Péclet Pe = \|u\|Δx/D ≤ 2, otherwise node-to-node wiggles |

Unconditionally stable (backward Euler, CN, BDF2 for diffusion) means bounded, not accurate.

## 3. Von Neumann analysis

1. Linearise, freeze coefficients, assume a periodic domain.
2. Substitute u_jⁿ = Gⁿ e^(ikjΔx) and write θ = kΔx ∈ [−π, π].
3. Solve for the amplification factor G(θ) (for systems, the spectral radius of the matrix G).
4. Require |G| ≤ 1 (+O(Δt) when the PDE itself grows) for every θ.

Worked FTCS diffusion: G = 1 + r(e^(iθ) − 2 + e^(−iθ)) = 1 − 4r sin²(θ/2). The worst mode is
θ = π (the checkerboard, G = 1 − 4r), so |G| ≤ 1 ⇔ r ≤ 1/2, and a violation blows up as an
odd-even pattern. Upwind: |G|² = 1 − 2ν(1 − ν)(1 − cos θ) ≤ 1 ⇔ 0 ≤ ν ≤ 1. Crank-Nicolson:
G = (1 − 2r sin²(θ/2))/(1 + 2r sin²(θ/2)), always in (−1, 1], but G(π) → −1 as r grows: the
shortest waves are not damped and flip sign every step.

Lax equivalence theorem: for a consistent scheme of a well-posed linear problem, stability ⇔
convergence. Modified-equation analysis shows what a stable scheme actually solves:
- upwind: u_t + cu_x = (cΔx/2)(1 − ν)u_xx, numerical diffusion (exact transport at ν = 1);
- Lax-Wendroff: u_t + cu_x = −(cΔx²/6)(1 − ν²)u_xxx, dispersion (trailing wiggles);
- FTCS diffusion: u_t = Du_xx + (DΔx²/12)(1 − 6r)u_xxxx, fourth order at r = 1/6.

Spectrum check for any semi-discrete operator A (small n): every eigenvalue of ΔtA must lie in
the time stepper's stability region. Non-normal operators (advection with inflow BCs) can grow
transiently even then; inspect pseudospectra or run long.

```python
lam = np.linalg.eigvals((dt*A).toarray())      # compare with the stepper's stability region
```

## 4. Fixes for stable-but-wrong schemes

- Crank-Nicolson on rough data: Rannacher start-up replaces the first step(s) by 2–4 implicit
  Euler half-steps, which damp the high modes (G = 0.048 for the shortest wave at r = 10 against
  −0.905 for CN). Computed in section 9: it restores second-order convergence.
- Upwind smearing: flux-limited (TVD) scheme. For c > 0, r_i = (u_i − u_{i−1})/(u_{i+1} − u_i)
  and face value u_{i+1/2} = u_i + ½(1 − ν)φ(r_i)(u_{i+1} − u_i); φ = 0 is upwind, φ = 1 is
  Lax-Wendroff. Limiters: minmod φ = max(0, min(1, r)); MC φ = max(0, min(2r, (1 + r)/2, 2));
  superbee φ = max(0, min(2r, 1), min(r, 2)); van Leer φ = (r + |r|)/(1 + |r|).

```python
def tvd_step(u, nu, phi=lambda r: np.maximum(0, np.minimum(1, r))):   # periodic, c > 0, nu <= 1
    du = np.roll(u, -1) - u
    r = (u - np.roll(u, 1))/np.where(du == 0, 1e-300, du)
    uf = u + 0.5*(1 - nu)*phi(r)*du               # u at face i+1/2
    return u - nu*(uf - np.roll(uf, 1))            # conservative update
```

- Shocks: write u_t + f(u)_x = 0 as u_iⁿ⁺¹ = u_iⁿ − (Δt/Δx)(F_{i+1/2} − F_{i−1/2}). By the
  Lax-Wendroff theorem a convergent conservative scheme converges to a weak solution with the
  Rankine-Hugoniot speed s = [f]/[u] (Burgers: (u_L + u_R)/2). Non-conservative forms (upwinding
  u·u_x) move shocks at the wrong speed. Roe fluxes need Harten's entropy fix at sonic points.

## 5. Boundary conditions

- Dirichlet: impose on the boundary node (vertex-centred), or ghost u₀ = 2g − u₁ (cell-centred,
  second order).
- Neumann: ghost u₋₁ = u₁ − 2Δx·g (centred), or one-sided (−3u₀ + 4u₁ − u₂)/(2Δx) = g. The
  first-order (u₁ − u₀)/Δx = g usually drops the global order of a diffusion solve to one.
- Periodic: wrap (`np.roll`) or FFT.
- Open boundaries: characteristic (non-reflecting) conditions, sponge layers, or a PML (complex
  coordinate stretching); keep absorbing layers away from sources and evanescent fields.
- The boundary truncation error may be one order below the interior for elliptic and parabolic
  problems, never more. Boundary conditions are the usual cause of lost convergence order; prove
  the order with manufactured solutions (`simulation-verification-validation`).

## 6. Linear solvers

| System | Solver | Preconditioner |
|---|---|---|
| Small or dense | LU (LAPACK), factor once and reuse | — |
| Sparse SPD (diffusion, elasticity) | CG | AMG (PyAMG, hypre BoomerAMG, PETSc GAMG), incomplete Cholesky |
| Sparse nonsymmetric (advection-diffusion) | GMRES(m), BiCGSTAB | ILU(k); AMG when diffusion dominates |
| Saddle point (Stokes, constraints) | MINRES (symmetric) or GMRES | block preconditioners with a Schur-complement approximation |
| A few eigenpairs | `eigsh` with shift-invert, LOBPCG | AMG or ILU as LOBPCG preconditioner |

Stop at a relative residual ‖b − Ax‖/‖b‖ about 10× below the estimated discretisation error
(1e-5 when the scheme error is 1e-4). Good multigrid reduces the residual ~10× per V-cycle;
iteration counts that grow with refinement mean a weak preconditioner.

## 7. Tool snippets

```python
import numpy as np, pyamg, scipy.sparse.linalg as spla
A = pyamg.gallery.poisson((500, 500), format="csr")              # 2.5e5 unknowns, SPD
ml = pyamg.smoothed_aggregation_solver(A)
x, info = spla.cg(A, np.ones(A.shape[0]), M=ml.aspreconditioner(cycle="V"), rtol=1e-8)
```

```python
# FEniCSx / dolfinx 0.10: P2 Poisson, -lap u = 1, u = 0 on the boundary
from mpi4py import MPI
import numpy as np, ufl
from dolfinx import mesh, fem, default_scalar_type
from dolfinx.fem.petsc import LinearProblem
msh = mesh.create_unit_square(MPI.COMM_WORLD, 64, 64)
V = fem.functionspace(msh, ("Lagrange", 2))
u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
a = ufl.inner(ufl.grad(u), ufl.grad(v))*ufl.dx
L = fem.Constant(msh, default_scalar_type(1.0))*v*ufl.dx
fdim = msh.topology.dim - 1
facets = mesh.locate_entities_boundary(msh, fdim, lambda x: np.full(x.shape[1], True))
bc = fem.dirichletbc(default_scalar_type(0), fem.locate_dofs_topological(V, fdim, facets), V)
problem = LinearProblem(a, L, bcs=[bc], petsc_options_prefix="poisson_",   # prefix required from 0.10
                        petsc_options={"ksp_type": "cg", "pc_type": "gamg", "ksp_rtol": 1e-10})
uh = problem.solve()
```

```python
# Dedalus v3: Burgers with implicit diffusion; dealias=3/2 padding is the 2/3 rule
import numpy as np, dedalus.public as d3
xc = d3.Coordinate("x"); dist = d3.Distributor(xc, dtype=np.float64)
xb = d3.RealFourier(xc, size=256, bounds=(0, 2*np.pi), dealias=3/2)
u = dist.Field(name="u", bases=xb); nu = 1e-2
dx = lambda A: d3.Differentiate(A, xc)
problem = d3.IVP([u], namespace=locals())
problem.add_equation("dt(u) - nu*dx(dx(u)) = -u*dx(u)")          # linear terms left (implicit)
solver = problem.build_solver(d3.RK222); solver.stop_sim_time = 1.0
u["g"] = np.sin(dist.local_grid(xb))
while solver.proceed: solver.step(1e-3)
```

PETSc (petsc4py, or any code calling `ksp.setFromOptions()`): run with
`-ksp_type cg -pc_type gamg -ksp_rtol 1e-8 -ksp_monitor -ksp_converged_reason`; use
`-ksp_type gmres -pc_type ilu` for nonsymmetric systems and `-ksp_view` to see what ran.

```julia
using Gridap                                     # FEM weak form in Julia
model = CartesianDiscreteModel((0, 1, 0, 1), (64, 64))
V = TestFESpace(model, ReferenceFE(lagrangian, Float64, 2); dirichlet_tags = "boundary")
U = TrialFESpace(V, 0.0); dΩ = Measure(Triangulation(model), 4)
a(u, v) = ∫(∇(v)⋅∇(u))dΩ;  l(v) = ∫(1.0*v)dΩ
uh = solve(AffineFEOperator(a, l, U, V))
```

Trixi.jl covers high-order DG for hyperbolic conservation laws (Euler, MHD) with shock capturing.

## 8. Failure signatures

| Symptom | Likely cause | Check |
|---|---|---|
| Odd-even checkerboard growing exponentially | stability limit violated | ν, r, S against section 2; the θ = π mode |
| Oscillation at a jump that does not grow | Gibbs, dispersive scheme (Lax-Wendroff, spectral) or CN at large r | limiter, Rannacher start-up, filtering |
| Fronts smeared over many cells | numerical diffusion (upwind) | modified equation; higher order + limiter |
| Steady wiggles in advection-diffusion | cell Péclet > 2 with central differences | refine, upwind, SUPG |
| Slow drift of total mass or energy | non-conservative scheme or a leaking boundary flux | track Σu_iΔx every step |
| Shock at the wrong position | non-conservative form | Rankine-Hugoniot speed |
| Observed order below design | boundary conditions, rough data, loose solver tolerance, not asymptotic | manufactured solution on 3-4 grids |
| Late blow-up in a spectral code | aliasing of nonlinear terms | 2/3 rule or 3/2 padding |
| Pressure checkerboard (collocated incompressible) | odd-even decoupling | Rhie-Chow or staggered grid (`fluid-dynamics-cfd`) |

## 9. Worked example: u_t = u_xx on [0, 1], Δx = 0.01 (computed)

Dirichlet u = 0 at both ends, box initial data u = 1 on (0.3, 0.7) and 0.5 on the two jump
nodes; exact solution from the Fourier series u = Σ b_n sin(nπx)e^(−n²π²t),
b_n = (2/(nπ))(cos 0.3nπ − cos 0.7nπ).

1. FTCS needs Δt ≤ Δx²/(2D) = 5e-5. At r = 0.50 the solution at t = 0.1 has max 0.2788 (exact
   0.2790); at r = 0.51 it reaches 1.8e29 with alternating signs: the checkerboard.
2. CN at Δt = 1e-3 (r = 10) is stable, but the shortest wave has G = −0.905, so the error next to
   the jumps flips sign every step and decays only like 0.905ⁿ: 0.23 after 1 step, 0.157 after
   2, 0.075 after 5, 0.028 after 10. With Rannacher start-up (2 implicit Euler half-steps) the
   errors are 0.033, 0.0073, 0.0013 and 3.5e-4. By t = 0.1 both are ~4e-6.
3. Convergence with Δt = Δx/10 (r = 5, 10, 20), max error at t = 0.02:

| Data and start-up | Δx = 0.02 | 0.01 | 0.005 | Observed order |
|---|---|---|---|---|
| Box, plain CN | 5.66e-3 | 5.75e-3 | 5.76e-3 | 0.0 (no convergence) |
| Box, 2 implicit Euler half-steps | 4.32e-4 | 1.07e-4 | 2.68e-5 | 2.01, 2.00 |
| Box, 4 implicit Euler half-steps | 9.40e-4 | 2.35e-4 | 5.86e-5 | 2.00, 2.00 |
| Smooth sin data, plain CN | 7.66e-5 | 1.90e-5 | 4.73e-6 | 2.02, 2.00 |
| Smooth sin data, 2 half-steps | 7.83e-4 | 1.96e-4 | 4.89e-5 | 2.00, 2.00 |

O(Δt², Δx²) is confirmed only with the start-up on rough data; on smooth data the start-up costs
a larger error constant but keeps second order.

```python
import numpy as np, scipy.sparse as sp
from scipy.sparse.linalg import splu
def cn(u0, dx, dt, T, rannacher_steps=0):
    n = len(u0); I = sp.identity(n, format="csc")
    A = sp.diags([np.ones(n - 1), -2*np.ones(n), np.ones(n - 1)], [-1, 0, 1], format="csc")/dx**2
    left = splu((I - 0.5*dt*A).tocsc())        # factor once; also the implicit-Euler half-step matrix
    right = (I + 0.5*dt*A).tocsr(); u = u0.copy()
    for _ in range(2*rannacher_steps): u = left.solve(u)            # half-steps of size dt/2
    for _ in range(int(round(T/dt)) - rannacher_steps): u = left.solve(right @ u)
    return u
dx = 0.01; x = dx*np.arange(1, 100)
u0 = np.where((x > 0.3) & (x < 0.7), 1.0, 0.0); u0[np.isclose(x, 0.3) | np.isclose(x, 0.7)] = 0.5
k = np.arange(1, 3001)*np.pi; b = 2/k*(np.cos(0.3*k) - np.cos(0.7*k))
exact = lambda t: np.sin(np.outer(x, k)) @ (b*np.exp(-k*k*t))
for R in (0, 1):
    print(R, abs(cn(u0, dx, 1e-3, 0.01, R) - exact(0.01)).max())    # 2.8e-2 vs 3.5e-4
```

## 10. Pitfalls

- Treating unconditional stability as accuracy: CN at r = 10 is stable and still off by 0.23 on
  a unit jump after one step.
- Refining Δx without scaling Δt ∝ Δx² for explicit diffusion (halving Δx needs Δt/4), or
  without rescaling Δt ∝ Δx for the CFL limit.
- Aliasing of quadratic terms in spectral codes: dealias (2/3 rule) or add hyperviscosity.
- Solving each implicit step to 1e-14 while the discretisation error is 1e-4 (10–100× wasted
  work), or to 1e-3 so that solver error pollutes the convergence study.
- First-order boundary stencils inside a second-order scheme; a convergence study on data that
  is not smooth enough for the design order.
- A stability check done for the interior only, then broken by a non-uniform grid (use the
  smallest cell) or a variable coefficient (use the maximum |c| or D).

Related: `physics-ode-integrators`, `em-field-solvers-fdtd-fem`, `fluid-dynamics-cfd`, `schrodinger-numerics`, `matrix-decompositions-conditioning`, `numerical-error-analysis`, `simulation-verification-validation`, hub `physics-toolkit`
