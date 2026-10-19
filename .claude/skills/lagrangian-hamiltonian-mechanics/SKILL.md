---
name: lagrangian-hamiltonian-mechanics
description: "Deriving equations of motion and conserved quantities: generalised coordinates and constraints, Euler-Lagrange with dissipation, Noether charges, Legendre transform to Hamiltonians, Poisson brackets, canonical transforms, normal modes, rigid bodies, nonlinear-oscillator perturbation and SymPy mechanics. Load when deriving or checking classical dynamics."
when_to_use: "Writing or checking a Lagrangian or Hamiltonian; equations of motion for pendula, beads, linkages, orbits, tops, vehicles or robot arms; normal modes and stability of an equilibrium; conserved quantities, cyclic coordinates and Noether charges; secular t*sin(t) terms in an oscillator expansion; sympy.physics.mechanics (LagrangesMethod, KanesMethod) or euler_equations code; energy that drifts in a simulation of a rotating or constrained system; Poincare sections and Lyapunov exponents."
---

# Lagrangian and Hamiltonian mechanics

Derive in generalised coordinates, check against symmetries, then verify the generated equations
numerically before trusting them. Time stepping (stiffness, symplectic schemes, events) belongs to
`physics-ode-integrators`. All numbers below were computed with SymPy 1.14 / SciPy 1.18.

Deep material: perturbation derivations |
chaos and rigid-body code

## 1. Procedure

1. Degrees of freedom: n = 3N − (independent holonomic constraints f_k(r, t) = 0). Choose q_1..q_n
   that satisfy every holonomic constraint identically.
2. Write each r_i(q, t), differentiate, form T = Σ ½ m_i |ṙ_i|² and V(q, t). L = T − V.
3. For every coordinate: d/dt(∂L/∂q̇_j) − ∂L/∂q_j = Q_j^nc, with the generalised force
   Q_j^nc = Σ_i F_i^nc · ∂r_i/∂q_j (units energy/[q_j]: N for lengths, N m for angles).
4. Linear damping: Rayleigh function F = ½ Σ c_jk q̇_j q̇_k; add +∂F/∂q̇_j to the left side.
   Power dissipated = 2F.
5. Non-holonomic (velocity) constraints Σ_j a_kj(q, t) q̇_j + a_kt = 0: keep all coordinates and add
   multipliers, d/dt ∂L/∂q̇_j − ∂L/∂q_j = Σ_k λ_k a_kj, solved together with the constraints. Never
   substitute a velocity constraint into L: the equations come out wrong (rolling disk, skate, cart).
6. Need a constraint force? Keep the constrained coordinate, add λ ∂f/∂q_j; λ∇f is the force.
7. Check dimensions of each equation, the small-amplitude limit, one conserved quantity (section 2)
   and numerical conservation of the generated code (section 8).

| Constraint | Example | Treatment | Consequence |
|---|---|---|---|
| holonomic, scleronomic f(q) = 0 | rigid rod, bead on a fixed wire | eliminate a coordinate | h = T + V |
| holonomic, rheonomic f(q, t) = 0 | spinning hoop, driven pivot | eliminate; Ω or t appears in L | h ≠ T + V; T + V not conserved |
| non-holonomic (velocity) | rolling without slipping | Lagrange multipliers | cannot reduce coordinates |
| unilateral f ≥ 0 | contact, slack rope | event + impact law | see `physics-ode-integrators` |

## 2. Noether and conservation

| Symmetry (Noether) | Conserved quantity | Breaks when |
|---|---|---|
| time translation, ∂L/∂t = 0 | energy function h = Σ q̇_j ∂L/∂q̇_j − L | time-dependent drive, dissipation |
| space translation | linear momentum | external potential with gradients |
| rotation about n | angular momentum n·L | non-central forces, anisotropy |
| Galilean / Lorentz boost | centre-of-mass motion (x_cm − v_cm t) | external forces |
| U(1) phase | charge, particle number | number-violating terms |
| scaling, V ∝ r^n | virial 2⟨T⟩ = n⟨V⟩ (bound motion, time averages) | non-power-law potentials |
| cyclic coordinate, ∂L/∂q = 0 | p_q = ∂L/∂q̇ | q appears in L |

- Noether charge: if q → q + εK(q) changes L by ε dΛ/dt, then Q = Σ_j (∂L/∂q̇_j) K_j − Λ is conserved.
- dh/dt = −∂L/∂t + Σ_j Q_j^nc q̇_j. h = T + V only when T is homogeneous quadratic in q̇ (scleronomic
  constraints) and V is velocity independent. A spinning constraint conserves h but not T + V
  (section 11). Magnetic forces do no work: h = T + qφ.
- Virial: Kepler (n = −1) 2⟨T⟩ = −⟨V⟩ so E = −⟨T⟩; harmonic (n = 2) ⟨T⟩ = ⟨V⟩ = E/2.
- Use symmetries twice: to reduce the problem (cyclic coordinates, centre-of-mass frame,
  angular-momentum barrier) and to check the answer (a simulation must conserve them to tolerance).
- Dissipative or driven systems: check the energy budget instead, E(t) − E(0) = ∫(P_drive − 2F) dt.
- Adiabatic invariant J = (1/2π)∮p dq survives slow parameter change only when the change time is
  much longer than the period; it fails near a separatrix where the period diverges. Slowly
  shortened pendulum: J = E/ω constant gives amplitude θ₀ ∝ l^(−3/4).

## 3. Hamiltonian formulation

- p_j = ∂L/∂q̇_j. For L = ½ q̇ᵀM(q)q̇ − V: p = Mq̇ and H = ½ pᵀM⁻¹p + V.
- H(q, p, t) = Σ p_j q̇_j − L with q̇ eliminated; q̇ = ∂H/∂p, ṗ = −∂H/∂q, dH/dt = ∂H/∂t = −∂L/∂t.
- The Legendre transform needs det(∂²L/∂q̇∂q̇) ≠ 0; a singular Hessian (gauge freedom, constraints)
  needs Dirac's constrained formalism.
- Charged particle (SI): L = ½mv² − qφ + q v·A, canonical p = mv + qA (gauge dependent),
  H = |p − qA|²/(2m) + qφ. Quantise p, report mv; mixing them is a classic error.
- Poisson bracket {f, g} = Σ_j (∂f/∂q_j ∂g/∂p_j − ∂f/∂p_j ∂g/∂q_j): {q_i, p_j} = δ_ij,
  {L_x, L_y} = L_z, df/dt = {f, H} + ∂f/∂t. The bracket of two constants of motion is a constant
  (Jacobi identity, Poisson's theorem).
- Canonical transformations, new Hamiltonian K = H + ∂F/∂t:

| Generating function | Relations | Example |
|---|---|---|
| F1(q, Q, t) | p = ∂F1/∂q, P = −∂F1/∂Q | F1 = qQ swaps: Q = p, P = −q |
| F2(q, P, t) | p = ∂F2/∂q, Q = ∂F2/∂P | F2 = qP identity; F2 = f(q)P point transformation |
| F3(p, Q, t) | q = −∂F3/∂p, P = −∂F3/∂Q | |
| F4(p, P, t) | q = −∂F4/∂p, Q = ∂F4/∂P | |

  Test any candidate with {Q, P}_(q,p) = 1, or Jacobian Mᵀ J M = J for several DOF.
- Action-angle variables: J = (1/2π)∮p dq, ω = ∂H/∂J, angle θ = ωt + θ₀; harmonic oscillator J = E/ω.
  Integrable n-DOF systems have n actions; under perturbation KAM tori break up (section 9).

## 4. Small oscillations and normal modes

1. Equilibrium: ∂V_eff/∂q = 0 (V_eff includes centrifugal terms in rotating or reduced problems).
2. M_ij = ∂²T/∂q̇_i∂q̇_j and K_ij = ∂²V/∂q_i∂q_j at q₀ give M q̈ + K q = 0.
3. Solve K v = ω² M v with `scipy.linalg.eigh(K, M)`; M must be SPD and the eigenvectors come out
   M-orthonormal (Vᵀ M V = I).
4. ω² < 0: unstable with growth rate sqrt(−ω²). ω² = 0: zero mode = symmetry (translation,
   rotation) or a marginal direction that needs the next order.
5. Gyroscopic or damped terms (M q̈ + (C + G) q̇ + K q = 0): quadratic eigenproblem; write it as a
   2n×2n first-order system and use `scipy.linalg.eig`.

```python
import numpy as np
from scipy.linalg import eigh
m, l, g, k = 1.0, 1.0, 9.81, 2.0                  # two pendula, spring k between the bobs
M = m*l**2*np.eye(2)
K = np.array([[m*g*l + k*l**2, -k*l**2], [-k*l**2, m*g*l + k*l**2]])
w2, V = eigh(K, M)
print(np.sqrt(w2))  # [3.13209195 3.71618084] = sqrt(g/l), sqrt(g/l + 2k/m)
print(V)            # columns (1,1)/sqrt2 in phase and (1,-1)/sqrt2 antiphase (signs arbitrary)
```

Displace one bob: energy beats between the pendula with period 2π/(ω₂ − ω₁) = 10.76 s. A free
three-mass chain, K = [[1,−1,0],[−1,2,−1],[0,−1,1]], gives ω² = 0, 1, 3; the zero mode
(1, 1, 1)/√3 is the translation symmetry.

## 5. Central forces

- Two bodies reduce to one: μ = m₁m₂/(m₁ + m₂), r = r₁ − r₂; the centre of mass moves uniformly.
- L = μr²θ̇ is conserved; radial motion μr̈ = −dV_eff/dr with V_eff = L²/(2μr²) + V(r). Turning
  points solve E = V_eff(r); circular orbits sit at V_eff′ = 0 and are stable when V_eff″ > 0
  (power law V ∝ r^n: stable for n > −2).
- Binet equation for the orbit shape, u = 1/r: d²u/dθ² + u = −μ F_r(1/u)/(L² u²), with F_r the
  radial force (positive outward). Kepler F_r = −k u² gives u = (μk/L²)(1 + e cos(θ − θ₀)).
- Bertrand's theorem: only V ∝ −1/r and V ∝ r² close every bounded orbit. Otherwise orbits precess;
  apsidal angle of a near-circular orbit in F ∝ r^m is π/sqrt(m + 3) (Kepler m = −2: π, harmonic: π/2).
- Kepler elements from E and L (V = −k/r): a = −k/(2E), e = sqrt(1 + 2EL²/(μk²)),
  r_p = a(1 − e), r_a = a(1 + e), period T = 2π sqrt(μa³/k). Check with the benchmark orbit of
  `physics-ode-integrators` (μ = k = 1, a = 1, e = 0.5): E = −0.5, L = sqrt(1 − e²) = 0.8660, and
  sqrt(1 − 2·0.5·0.75) = 0.5 recovers e.
- Relativistic perihelion advance per orbit: Δφ = 6πGM/(c²a(1 − e²)) (Mercury: 43″ per century).

## 6. Rigid bodies

- Inertia tensor I_ij = Σ m (r²δ_ij − x_i x_j); parallel axis I = I_cm + M(|d|²𝟙 − d dᵀ); principal
  axes from `numpy.linalg.eigh(I)`. Anchors: solid sphere 2MR²/5; rod ML²/12 (centre), ML²/3 (end);
  solid cylinder about its axis MR²/2; box about the axis along a: M(b² + c²)/12.
- T = ½ ωᵀIω and L = Iω in the body frame. Euler's equations on principal axes:
  I₁ω̇₁ − (I₂ − I₃)ω₂ω₃ = τ₁ and cyclic permutations. Torque-free invariants:
  E = ½ Σ I_i ω_i² and |L|² = Σ I_i² ω_i².
- Intermediate-axis theorem (I₁ < I₂ < I₃): spin about axes 1 and 3 is stable, about axis 2 it is
  unstable with growth rate σ = ω₂ sqrt((I₂ − I₁)(I₃ − I₂)/(I₁I₃)). Computed for I = (1, 2, 3),
  ω = (1e-3, 1, 1e-3): σ = 0.577 s⁻¹, first flip of ω₂ at t = 14.9 s (linear estimate
  ln(1e3)/σ = 12.0 s); the same perturbation about axes 1 or 3 stays below 2e-3.
- Orientation: unit quaternion q (body to world), q̇ = ½ q ⊗ (0, ω_body). Renormalise every step;
  RK4 with h = 0.05 at 2 rad/s for 1000 s drifts |q| − 1 = −2.2e-6 without renormalisation (angle
  error 1.0e-4 rad either way, from truncation). For constant ω over a step, q ⊗ exp(½ω h) is exact.
- Euler angles hit gimbal lock (ZXZ at θ = 0, ZYX at pitch ±90°); use quaternions or rotation
  matrices with re-orthonormalisation. q and −q are the same rotation: flip sign before
  interpolating when q₁·q₂ < 0.
- Explicit Euler on Euler's equations gains energy at high spin; use small RK4 steps, a splitting
  scheme, or implicit treatment of ω × Iω. Code in chaos and rigid-body code.
- Heavy symmetric top: L = ½I₁(θ̇² + φ̇² sin²θ) + ½I₃(ψ̇ + φ̇ cosθ)² − Mgl cosθ; φ and ψ are cyclic,
  so p_φ and p_ψ are conserved; a fast top precesses at Ω ≈ Mgl/(I₃ω₃).

## 7. Nonlinear oscillators and perturbation (classical)

| Situation | Method | Validity check |
|---|---|---|
| small ε, solution analytic in ε | regular expansion x = x₀ + εx₁ + ... | next term ≪ current over the whole domain |
| secular t·sin t growth | Poincaré-Lindstedt (frequency shift) or two-timing (slow amplitude) | uniform for t ~ 1/ε |
| ε multiplies the highest derivative | matched asymptotics, boundary layer of width ε^a | inner and outer agree in the overlap |
| divergent asymptotic series | optimal truncation at the smallest term | error ~ smallest term |

- Poincaré-Lindstedt: rescale τ = ωt with ω = ω₀ + εω₁ + ..., expand x, and choose each ω_k to kill
  the resonant cos τ forcing at that order. Duffing ẍ + ω₀²x + βx³ = 0 with amplitude A:
  ω = ω₀(1 + 3βA²/(8ω₀²)) + O(ε²), ε = βA²/ω₀².
- Two-timing: x(t, T = εt) with amplitude equations from removing secular terms. van der Pol
  ẍ + x = ε(1 − x²)ẋ gives a limit cycle of amplitude 2 (computed 2.0001 at ε = 0.1); damped
  ẍ + 2εẋ + x = 0 gives e^(−εt)cos t, error 0.048 up to t = 1/ε at ε = 0.05 against 0.33 for the
  naive regular expansion.

Duffing check (ω₀ = 1, β = 0.1, period from successive maxima with solve_ivp events):

| A | ε | ω numerical | ω Poincaré-Lindstedt | relative error |
|---|---|---|---|---|
| 0.5 | 0.025 | 1.009324 | 1.009375 | 5.0e-5 |
| 1.0 | 0.1 | 1.036717 | 1.037500 | 7.6e-4 |
| 2.0 | 0.4 | 1.138908 | 1.150000 | 9.7e-3 |

The error scales as ε²; at ε ≳ 0.3 go to the next order or integrate numerically. Step-by-step
derivations, a boundary-layer example and optimal truncation numbers are in
perturbation derivations.

## 8. SymPy mechanics

| API (SymPy 1.14) | Use |
|---|---|
| `dynamicsymbols("q1 q2")`, time symbol `dynamicsymbols._t` | coordinates as functions of t |
| `LagrangesMethod(L, qs, forcelist=None, bodies=None, frame=None, hol_coneqs=None, nonhol_coneqs=None)` | `.form_lagranges_equations()`, `.mass_matrix_full`, `.forcing_full`, `.rhs()` |
| `KanesMethod(frame, q_ind, u_ind, kd_eqs=...)` | `fr, frstar = km.kanes_equations(bodies, loads)`, then `km.rhs()` |
| `Lagrangian(frame, *bodies)`, `Particle`, `RigidBody`, `ReferenceFrame`, `Point`, `inertia` | build T and V from bodies |
| `sympy.calculus.euler.euler_equations(L, funcs, t)` | quick E-L equations without frames |
| `lambdify(args, expr, cse=True)` | fast numeric right-hand side for `solve_ivp` |

- `euler_equations` raises "Variables (t,) do not match args" when your `t` is a new Symbol (for
  example created with `positive=True`); use `t = dynamicsymbols._t`.
- Non-holonomic constraints go into `nonhol_coneqs` (Lagrange) or `u_dependent` plus
  `velocity_constraints` (Kane); Kane's method scales better for many bodies and constraints.
- Always run the generated right-hand side once and check h or E conservation at tight tolerance
  (section 11 shows the pattern; expect ~1e-10 relative with DOP853 at rtol = 1e-10).

## 9. Chaos diagnostics

- Poincaré section: record (q₂, p₂) whenever q₁ crosses 0 upward (event function with direction +1).
  Regular orbits draw closed curves, chaotic ones fill areas.
- Largest Lyapunov exponent (Benettin): integrate the state y with a tangent vector v, v̇ = J(y)v,
  renormalise v every τ, λ = (1/(Nτ)) Σ ln|v|. Plot the running estimate; a regular orbit gives
  λ → 0 like ln t/t.
- Double pendulum (m = l = 1, g = 9.81, θ₁ = θ₂ = 2 rad at rest), twin run with δθ₁ = 1e-9:
  separation exceeds 1e-6 at 5.4 s, 1e-3 at 11.5 s and 1 at 16.9 s. Benettin gives λ ≈ 1.2 s⁻¹
  (1.22, 1.18, 1.21 at T = 50, 100, 200 s) and ln(1e9)/λ = 17.2 s matches the divergence time.
- Predictability horizon t_p ≈ ln(Δ_tol/δ₀)/λ: each 10× better initial accuracy buys only
  ln 10/λ ≈ 1.9 s here. Beyond t_p compare statistics (sections, λ, invariant densities), never
  trajectories. Script: chaos and rigid-body code.

## 10. Rotating frames

Write L with coordinates r measured in a frame rotating at Ω:
L = ½m|ṙ + Ω × r|² − V = ½mṙ² + m ṙ·(Ω × r) + ½m|Ω × r|² − V. The cross term produces the Coriolis
force −2mΩ × ṙ, the last kinetic term is the centrifugal potential −½m|Ω × r|², and Ω̇ ≠ 0 adds
the Euler force −mΩ̇ × r. Then p = m(ṙ + Ω × r) and h = ½mṙ² − ½m|Ω × r|² + V is the Jacobi
integral (restricted three-body problem: Jacobi constant and Lagrange points come from it).
Pitfall: with L written this way, adding Coriolis and centrifugal forces again as Q double-counts them.

## 11. Worked example: bead on a spinning hoop

Hoop of radius R spun at Ω about its vertical diameter, θ measured from the bottom:
L = ½mR²(θ̇² + Ω²sin²θ) + mgR cosθ, so θ̈ = sinθ (Ω²cosθ − g/R).
- θ = 0: ω² = g/R − Ω², stable for Ω² < g/R.
- Bifurcation at Ω_c = sqrt(g/R) to cosθ* = g/(RΩ²) with ω² = Ω²sin²θ* = Ω² − g²/(Ω²R²).
- h = ½mR²θ̇² − ½mR²Ω²sin²θ − mgR cosθ is conserved (∂L/∂t = 0) but T + V − h = mR²Ω²sin²θ:
  the motor does work, so T + V is not conserved.

```python
import numpy as np, sympy as sm
from sympy.physics.mechanics import dynamicsymbols, LagrangesMethod
from scipy.integrate import solve_ivp

m, R, g, W = sm.symbols("m R g Omega", positive=True)
t = dynamicsymbols._t                       # the time symbol dynamicsymbols uses
th = dynamicsymbols("theta"); thd = th.diff(t)
L = sm.Rational(1, 2)*m*R**2*(thd**2 + W**2*sm.sin(th)**2) + m*g*R*sm.cos(th)

LM = LagrangesMethod(L, [th]); LM.form_lagranges_equations()
acc = sm.simplify(LM.rhs()[1])              # (Omega**2*R*cos(theta) - g)*sin(theta)/R
h = sm.simplify(thd*L.diff(thd) - L)        # energy function (Jacobi integral)
E = sm.Rational(1, 2)*m*R**2*(thd**2 + W**2*sm.sin(th)**2) - m*g*R*sm.cos(th)   # T + V
print("E - h =", sm.simplify(E - h))        # Omega**2*R**2*m*sin(theta)**2  -> h != T + V

x = sm.Symbol("x"); f = acc.subs(th, x); fp = sm.diff(f, x)
print("omega^2 at 0     :", sm.simplify(-fp.subs(x, 0)))                     # g/R - Omega**2
print("omega^2 at theta*:", sm.simplify(-fp.subs(x, sm.acos(g/(R*W**2)))))  # Omega**2 - g**2/(Omega**2*R**2)

vals = {m: 0.05, R: 0.1, g: 9.81, W: 15.0}
q, u = sm.symbols("q u")
sub = lambda e: e.subs(vals).subs(thd, u).subs(th, q)
F = sm.lambdify((q, u), sub(acc)); Hn = sm.lambdify((q, u), sub(h)); En = sm.lambdify((q, u), sub(E))
sol = solve_ivp(lambda tt, y: [y[1], F(*y)], (0, 20), [0.3, 0.0], method="DOP853",
                rtol=1e-10, atol=1e-12, dense_output=True)
Y = sol.sol(np.linspace(0, 20, 2001)); hv = Hn(*Y); Ev = En(*Y)
print("max |h-h0|/|h0| = %.1e" % (np.abs(hv - hv[0]).max()/abs(hv[0])))
print("T+V range = [%.4f, %.4f] J, theta range = [%.2f, %.2f] deg" % (
      Ev.min(), Ev.max(), np.degrees(Y[0].min()), np.degrees(Y[0].max())))
```

Output: `max |h-h0|/|h0| = 3.1e-10`, `T+V range = [-0.0419, 0.0607] J`,
`theta range = [17.19, 94.78] deg`. With R = 0.1 m and Ω = 15 rad/s: Ω_c = 9.905 rad/s,
θ* = 64.15°, ω(θ*) = Ω sinθ* = 13.499 rad/s (the zero crossings of a run started at θ* + 1e-3 give
13.4992 rad/s), and θ = 0 is unstable with growth rate sqrt(Ω² − g/R) = 11.27 s⁻¹. The bead released
at 0.3 rad oscillates about θ* between 17° and 95°. Conservation of h confirms the derivation;
the variation of T + V is physics (motor work), not integrator error.

## 12. Pitfalls

- Sign errors in V: with θ from the bottom, V = −mgR cosθ. Check that the small-angle limit gives
  ω² = g/R (positive) before anything else.
- Time-dependent constraints (spinning hoop, driven pivot, moving wall) make H or h differ from E;
  testing T + V conservation then flags a "bug" that is physics.
- Generalised forces in the wrong coordinates: Q_j = Σ F·∂r/∂q_j. A torque enters only angle
  coordinates; Q_θ has units N m, Q_x has N.
- Substituting non-holonomic constraints into L, or adding Coriolis forces to a Lagrangian already
  written in rotating coordinates.
- Canonical vs kinetic momentum with magnetic fields (p = mv + qA).
- Stiff constrained systems (stiff springs standing in for rods, penalty constraints, DAEs)
  integrated with an explicit method: hand off to `physics-ode-integrators` (RATTLE, Radau, IDA).
- Euler angles near gimbal lock; quaternions that are never renormalised; trajectories of a
  chaotic system compared beyond the predictability horizon.
- Adiabatic invariants trusted near a separatrix or when the change is not slow.

Related: `physics-ode-integrators`, `quantum-mechanics-methods`, `dimensional-analysis-units`,
`simulation-verification-validation`, `sympy-symbolic-verification`, `ode-pde-analytic-methods`,
`computer-graphics`; hub `physics-toolkit`.
