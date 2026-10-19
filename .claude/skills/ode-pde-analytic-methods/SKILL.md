---
name: ode-pde-analytic-methods
description: "Analytic and qualitative ODE/PDE methods: first-order techniques, constant-coefficient and Cauchy-Euler equations, Frobenius series, Laplace transforms, matrix exponentials, existence/uniqueness, stability (phase plane, Lyapunov), Sturm-Liouville and Green's functions, separation of variables, Fourier methods, characteristics, checked with SymPy and numerical solves. Load when an ODE or PDE needs an analytic solution or a qualitative guarantee."
when_to_use: "Solve an ODE or IVP in closed form, pick a method from the equation's form, find a series or special-function solution, use Laplace transforms with switched or impulsive forcing, classify equilibria or prove stability, solve a boundary-value or eigenvalue problem, separate variables for heat, wave or Laplace equations, follow characteristics to shocks, or check a claimed solution symbolically and numerically."
---

# ODE and PDE analytic methods

A solution is finished when it satisfies the equation and the initial and boundary data, states
its interval of validity, and has been substituted back (SymPy) and compared with a numerical
solve. Choosing and tuning integrators belongs to `physics-toolkit` and `julia-sciml-diffeq`; this
skill covers closed forms and guarantees.

## 1. From equation form to method

| Form | Method | Key step |
|---|---|---|
| y′ = f(x) g(y) | separable | ∫ dy/g(y) = ∫ f dx; the zeros of g are constant solutions that dividing by g loses |
| y′ + p(x) y = q(x) | integrating factor μ = e^(∫p) | (μy)′ = μq, so y = (∫ μq dx + C)/μ |
| M dx + N dy = 0 with M_y = N_x | exact | F_x = M, F_y = N; the solution is F(x,y) = C |
| not exact, (M_y − N_x)/N = h(x) | integrating factor μ(x) = e^(∫h) | if instead (N_x − M_y)/M = k(y), use μ(y) = e^(∫k) |
| y′ + p y = q yⁿ, n ≠ 0, 1 | Bernoulli, v = y^(1−n) | v′ + (1−n) p v = (1−n) q, which is linear |
| y′ = F(y/x) | homogeneous, v = y/x | x v′ = F(v) − v, which is separable |
| y′ = q₀ + q₁y + q₂y², with a known solution y₁ | Riccati, y = y₁ + 1/v | v′ = −(q₁ + 2q₂y₁) v − q₂, which is linear |
| y′ = f(y) | autonomous | x = ∫ dy/f(y); the sign of f gives the phase line |
| y″ = f(y) | energy | multiply by y′: (y′)²/2 = ∫ f dy + E |
| y″ = f(x, y′) or f(y, y′) | reduction of order | p = y′; for f(y, y′) write y″ = p dp/dy |

## 2. Linear constant-coefficient and Cauchy-Euler equations

For a y″ + b y′ + c y = 0, take the roots of a r² + b r + c:

| Roots | Solution |
|---|---|
| distinct real r₁, r₂ | c₁e^(r₁x) + c₂e^(r₂x) |
| repeated r | (c₁ + c₂x) e^(rx) |
| complex α ± iβ | e^(αx)(c₁ cos βx + c₂ sin βx) |

For order n, a root of multiplicity m contributes x^j e^(rx) for j < m.

- **Undetermined coefficients.** For forcing P_m(x) e^(sx) cos ωx or sin ωx, try
  x^k e^(sx)(Q_m(x) cos ωx + R_m(x) sin ωx), where k is the multiplicity of s + iω as a
  characteristic root (k = 0 if it is not a root). This is the resonance rule. Example: y″ + y = cos x
  has i as a simple root, so y_p = (x/2) sin x.
- **Variation of parameters.** Normalise the leading coefficient to 1 first: y″ + p y′ + q y = g.
  Then y_p = −y₁ ∫ y₂ g/W dx + y₂ ∫ y₁ g/W dx with W = y₁y₂′ − y₁′y₂. This works for any continuous
  g, and for variable coefficients once y₁ and y₂ are known.
- **Cauchy-Euler** a x² y″ + b x y′ + c y = 0 on x > 0. Try y = x^r with a r(r−1) + b r + c = 0.
  A repeated root gives x^r(c₁ + c₂ ln x); complex roots α ± iβ give
  x^α(c₁ cos(β ln x) + c₂ sin(β ln x)). The substitution x = e^t gives constant coefficients (use
  |x| for x < 0).

## 3. Power series, Frobenius and special functions

- **Ordinary point** x₀ (p and q analytic in y″ + p y′ + q y = 0). Use y = Σ aₙ(x − x₀)ⁿ; the radius
  is at least the distance from x₀ to the nearest complex singularity of p or q.
- **Regular singular point** ((x − x₀)p and (x − x₀)²q analytic). Try (x − x₀)^r Σ aₙ(x − x₀)ⁿ. The
  indicial equation is r(r−1) + p₀r + q₀ = 0, with p₀ = lim (x − x₀)p and q₀ = lim (x − x₀)²q.
  Order the roots so that Re r₁ ≥ Re r₂.
  - If r₁ − r₂ is not an integer, there are two Frobenius series.
  - If r₁ = r₂, then y₂ = y₁ ln(x − x₀) + (x − x₀)^r₁ Σ bₙ(x − x₀)ⁿ.
  - If r₁ − r₂ is a positive integer, then y₂ = C y₁ ln(x − x₀) + (x − x₀)^r₂ Σ bₙ(x − x₀)ⁿ. C can
    be 0: compute it, never assume it.

| Equation | Solutions | DLMF |
|---|---|---|
| x²y″ + xy′ + (x² − ν²)y = 0 (Bessel) | J_ν, Y_ν | §10.2 |
| x²y″ + xy′ − (x² + ν²)y = 0 (modified Bessel) | I_ν, K_ν | §10.25 |
| y″ − xy = 0 (Airy) | Ai, Bi | §9.2 |
| (1 − x²)y″ − 2xy′ + ν(ν+1)y = 0 (Legendre) | P_ν, Q_ν; bounded on [−1, 1] only for ν ∈ ℕ (polynomials) | §14.2 |
| x(1−x)y″ + [c − (a+b+1)x]y′ − ab y = 0 (hypergeometric) | ₂F₁(a, b; c; x) | §15.10 |
| x y″ + (b − x)y′ − a y = 0 (Kummer) | M(a, b, x), U(a, b, x) | §13.2 |
| y″ − 2xy′ + 2ny = 0 (Hermite) | H_n for n ∈ ℕ | §18.8 |

Reduction to Bessel: x²y″ + (1 − 2a)x y′ + (b²c²x^(2c) + a² − ν²c²)y = 0 has the solutions
x^a J_ν(b x^c) and x^a Y_ν(b x^c). This was checked in SymPy for a = 1/2, b = 2, c = 3/2, ν = 1/3.
Cite the DLMF equation number for every special-function identity you use.

```python
from sympy import symbols, Function, dsolve
x, nu = symbols("x nu", positive=True); y = Function("y")
dsolve(x**2*y(x).diff(x, 2) + x*y(x).diff(x) + (x**2 - nu**2)*y(x))    # C1*besselj(nu, x) + C2*bessely(nu, x)
dsolve(y(x).diff(x, 2) - x*y(x))                                        # C1*airyai(x) + C2*airybi(x)
dsolve(y(x).diff(x, 2) + x*y(x).diff(x) + y(x), hint="2nd_power_series_ordinary", n=6)
```

## 4. Laplace transform

L{f}(s) = ∫₀^∞ e^(−st) f(t) dt.

| f(t) | F(s) |
|---|---|
| 1, tⁿ, e^(at) | 1/s, n!/s^(n+1), 1/(s − a) |
| sin ωt, cos ωt | ω/(s² + ω²), s/(s² + ω²) |
| e^(at) f(t) | F(s − a) |
| H(t − a) f(t − a) | e^(−as) F(s) |
| δ(t − a) | e^(−as) |
| f′, f″ | sF − f(0⁻), s²F − s f(0⁻) − f′(0⁻) |
| (f ∗ g)(t) = ∫₀ᵗ f(τ) g(t − τ) dτ | F G |
| t f(t) | −F′(s) |

IVP recipe: transform, solve for Y(s), split with `apart`, then invert term by term using the shift
rules. For a y″ + b y′ + c y = u with zero initial data, the transfer function is
H(s) = 1/(a s² + b s + c), the impulse response is h = L⁻¹{H}, and the response to u is h ∗ u.

```python
from sympy import symbols, exp, apart, inverse_laplace_transform, pi
s = symbols("s"); t = symbols("t", positive=True)
# y'' + 3y' + 2y = H(t - 1), y(0) = 0, y'(0) = 1   =>   (s^2 + 3s + 2) Y = 1 + e^(-s)/s
Y = (1 + exp(-s)/s) / (s**2 + 3*s + 2)
apart(1/(s*(s + 1)*(s + 2)), s)          # 1/(2s) - 1/(s+1) + 1/(2(s+2))
inverse_laplace_transform(Y, s, t)       # e^-t - e^-2t + H(t-1)(1/2 - e^(1-t) + e^(2-2t)/2)
inverse_laplace_transform(exp(-pi*s)/(s**2 + 1), s, t)   # -sin(t)*Heaviside(t - pi)
```

The last line solves y″ + y = δ(t − π) from rest. An impulse makes y′ jump, so use the 0⁻ initial
values.

## 5. Linear systems x′ = A x + f(t)

- **Duhamel.** x(t) = e^(At)x₀ + ∫₀ᵗ e^(A(t−s)) f(s) ds.
- **Diagonalisable** A = VΛV⁻¹: e^(At) = V e^(Λt) V⁻¹.
- **Jordan block** J = λI + N with N^m = 0: e^(Jt) = e^(λt) Σ_{j<m} N^j t^j/j!. Example:
  A = [[0,1],[−1,−2]] has λ = −1 twice; N = A + I satisfies N² = 0, so
  e^(At) = e^(−t)[[1+t, t],[−t, 1−t]] (SymPy `(A*t).exp()` agrees).
- **Fundamental matrix** Φ (Φ′ = AΦ, det Φ ≠ 0): e^(At) = Φ(t)Φ(0)⁻¹. Liouville:
  det Φ(t) = det Φ(t₀) exp(∫ tr A).
- **Stability, constant A.** Asymptotically stable iff every eigenvalue has Re λ < 0. Bounded iff
  Re λ ≤ 0 and the imaginary-axis eigenvalues are semisimple.
- **Variable A(t).** exp(∫A) is the solution only when the A(t) commute with one another.
  Otherwise use a numerical fundamental matrix or the Magnus series. Numerically, use
  `scipy.linalg.expm` (and `expm_frechet` for sensitivities).

## 6. Existence and uniqueness

- **Picard-Lindelöf.** Let f be continuous on R = {t₀ − a ≤ t ≤ t₀ + a, y₀ − b ≤ y ≤ y₀ + b} and
  Lipschitz in y with constant L. Then there is a unique solution for t within min(a, b/M) of t₀,
  where M = max over R of abs(f).
- **Peano.** Continuity of f alone gives existence, not uniqueness. Example: y′ = √|y|, y(0) = 0 is
  solved by y ≡ 0 and by y = (t − c)²/4 for t ≥ c (0 before) for every c ≥ 0. Here f is not
  Lipschitz at y = 0.
- **Extension.** If f is locally Lipschitz on an open D, the maximal solution either exists for all
  t or leaves every compact subset of D. Blow-up: y′ = y², y(0) = 1 gives y = 1/(1 − t), which
  escapes at t = 1 although f is smooth. Linear growth, abs(f(t,y)) ≤ α(t) + β(t) abs(y), rules out
  blow-up.
- **Gronwall.** If u(t) ≤ α + ∫_{t₀}^t β u ds with β ≥ 0, then u(t) ≤ α exp(∫_{t₀}^t β ds).
  Continuous dependence follows: abs(y(t) − z(t)) ≤ abs(y(t₀) − z(t₀)) e^(L abs(t − t₀)).

## 7. Qualitative analysis

Equilibria satisfy f(x*) = 0; let J = Df(x*).

- **Hartman-Grobman.** If no eigenvalue of J has zero real part (hyperbolic x*), the flow near x* is
  topologically conjugate to the linear flow. At a non-hyperbolic point the linearisation decides
  nothing: x′ = −x³ (stable) and x′ = x³ (unstable) both linearise to x′ = 0.
- **Planar classification** with T = tr J, D = det J and Δ = T² − 4D:

| Condition | Type |
|---|---|
| D < 0 | saddle (unstable) |
| D > 0, T < 0 | stable: node if Δ ≥ 0, spiral if Δ < 0 |
| D > 0, T > 0 | unstable: node if Δ ≥ 0, spiral if Δ < 0 |
| D > 0, T = 0 | linear centre; the nonlinear system is undecided (needs a Lyapunov function or reversibility) |
| D = 0 | non-isolated or non-hyperbolic; undecided |

- **Lyapunov.** Take V(x*) = 0 and V > 0 near x*. V̇ = ∇V·f ≤ 0 gives stability; V̇ < 0 away from x*
  gives asymptotic stability. If V is radially unbounded and V̇ < 0 on ℝⁿ ∖ {x*}, x* is globally
  asymptotically stable.
- **LaSalle.** If V̇ ≤ 0 on a compact positively invariant Ω, every trajectory from Ω approaches the
  largest invariant set in {V̇ = 0}. Damped pendulum: V = θ′²/2 + (1 − cos θ) gives V̇ = −cθ′² ≤ 0.
  The only invariant subset of {θ′ = 0} near 0 is the equilibrium, so it is asymptotically stable.
- **Poincaré-Bendixson** (planar C¹ flows). A nonempty compact ω-limit set with no equilibria is a
  periodic orbit, so a trapping annulus with no equilibria contains a limit cycle.
  Bendixson-Dulac: if div(Bf) has one sign and is not identically 0 on a simply connected region,
  there is no periodic orbit inside it.
- **Bifurcation normal forms.** Saddle-node x′ = r + x² (two equilibria for r < 0, none for r > 0);
  transcritical x′ = rx − x²; pitchfork x′ = rx − x³ (supercritical) or rx + x³ (subcritical). Hopf:
  a complex pair crosses the imaginary axis with nonzero speed d Re λ/dμ. The sign of the first
  Lyapunov coefficient decides super- vs subcritical; the supercritical polar form is r′ = μr − r³.

## 8. Boundary value problems

**Regular Sturm-Liouville problem:** −(p y′)′ + q y = λ w y on [a, b], with p ∈ C¹, p > 0, w > 0,
q continuous and separated conditions α₁y(a) + α₂y′(a) = 0, β₁y(b) + β₂y′(b) = 0.

- The eigenvalues are real and simple, λ₁ < λ₂ < ... → ∞.
- The eigenfunctions are orthogonal in L²_w; the n-th has n − 1 zeros in (a, b); they are complete
  in L²_w.
- Rayleigh: λ₁ = min ∫(p y′² + q y²)/∫ w y² over admissible y (Dirichlet; Robin adds boundary
  terms).
- Expansion coefficients: c_n = ⟨f, φ_n⟩_w/⟨φ_n, φ_n⟩_w.

**Green's function** for (p y′)′ + q y = f with homogeneous separated BCs. Let u₁ solve the
homogeneous equation with the left BC and u₂ with the right BC, and let W = u₁u₂′ − u₁′u₂ (pW is
constant). If pW ≠ 0, then G(x, ξ) = u₁(min(x,ξ)) u₂(max(x,ξ))/(pW) and y(x) = ∫ G(x, ξ) f(ξ) dξ.
G is continuous at x = ξ, and ∂G/∂x jumps by 1/p(ξ) there. Check: y″ = f on [0, 1] with
y(0) = y(1) = 0 has u₁ = x, u₂ = x − 1 and W = 1, so G = min(x,ξ)(max(x,ξ) − 1), and f = 1 gives
y = x(x − 1)/2.

**Fredholm alternative** (self-adjoint case). Either the homogeneous problem has only y = 0, and
L y = f has exactly one solution for every f; or it has solutions φ ≠ 0, and L y = f is solvable iff
⟨f, φ⟩ = 0 for every such φ, with non-unique solutions (add any φ). Example: y″ + y = f on [0, π]
with y(0) = y(π) = 0 is solvable iff ∫₀^π f(x) sin x dx = 0 (resonance).

## 9. PDEs: classification, separation and Fourier methods

**Classification.** a u_xx + 2b u_xy + c u_yy + (lower order) = 0 is elliptic if b² − ac < 0
(Laplace), parabolic if it is 0 (heat) and hyperbolic if it is > 0 (wave). The type can change with
position, as in Tricomi's y u_xx + u_yy = 0.

**Well-posedness** (Hadamard: existence, uniqueness, continuous dependence). Elliptic problems need
boundary data on a closed boundary. Parabolic problems need initial and boundary data, forward in
time. Hyperbolic problems need initial position and velocity, plus boundary data. The backward heat
equation and the Cauchy problem for Laplace's equation are ill-posed.

**Separation of variables**, u = X(x)T(t). The boundary conditions choose the eigenfunctions:

| BCs on [0, L] | X_n | λ_n |
|---|---|---|
| u = 0 at both ends | sin(nπx/L), n ≥ 1 | (nπ/L)² |
| u_x = 0 at both ends | cos(nπx/L), n ≥ 0 (the constant mode included) | (nπ/L)² |
| u(0) = 0, u_x(L) = 0 | sin((n − ½)πx/L), n ≥ 1 | ((n − ½)π/L)² |
| periodic with period L | cos(2nπx/L), sin(2nπx/L) | (2nπ/L)² |
| u(0) = 0, u_x(L) + h u(L) = 0, h > 0 | sin(√λ x) with tan(√λ L) = −√λ/h | the roots, found numerically |

Inhomogeneous or time-dependent BCs: first subtract a function that satisfies them (the steady
state).

**Fourier convergence.** For f piecewise C¹, the series converges pointwise, to the midpoint
(f(x⁺) + f(x⁻))/2 at a jump of the periodic extension. Convergence is uniform if the periodic
extension is continuous and piecewise C¹, and in L² for any f in L². Coefficient decay diagnoses
smoothness: O(1/n) with jumps, O(1/n²) with kinks. **Gibbs:** near a jump of size J, partial sums
overshoot by about 0.0895 J for every N. Fejér or Lanczos σ-factors reduce the overshoot.

**Unbounded domains.** Take the Fourier transform in x. The heat equation u_t = k u_xx on ℝ gives
u = G_t ∗ f with G_t(x) = (4πkt)^(−1/2) e^(−x²/(4kt)). On x > 0 with u(0,t) = 1 and u(x,0) = 0, a
Laplace transform in t gives u = erfc(x/(2√(kt))).

**Wave equation on ℝ (d'Alembert).**
u = [f(x − ct) + f(x + ct)]/2 + (1/(2c)) ∫_{x−ct}^{x+ct} g(s) ds. The value at (x, t) depends only on
data in [x − ct, x + ct]. On a half-line, use the odd extension for u(0,t) = 0 and the even
extension for u_x(0,t) = 0.

## 10. First-order PDEs, shocks, similarity and uniqueness

- **Quasilinear** a u_x + b u_y = c. The characteristics are dx/ds = a, dy/ds = b, du/ds = c.
  Parametrise the data curve, which must be non-characteristic (transversal to (a, b)).
- **Transport** u_t + c u_x = 0: u = f(x − ct).
- **Inviscid Burgers** u_t + u u_x = 0: u = f(x − u t) implicitly. Characteristics cross where
  f′ < 0, first at the breaking time t* = −1/min f′.
- **Shocks** in u_t + F(u)_x = 0 after breaking need weak solutions. The Rankine-Hugoniot speed is
  s = (F(u_L) − F(u_R))/(u_L − u_R); for Burgers, s = (u_L + u_R)/2. The Lax entropy condition is
  F′(u_L) > s > F′(u_R) (u_L > u_R for Burgers). Otherwise a rarefaction fan joins the states
  (u = x/t for Burgers).
- **Similarity.** The heat equation is invariant under x → λx, t → λ²t. u = t^(−1/2) φ(x/√t) gives
  the heat kernel, and u = φ(x/√(4kt)) gives the erf solutions.
- **Maximum principle.** A solution of u_t = k u_xx on [0, L] × [0, T] attains its max and min at
  t = 0 or at x ∈ {0, L}. Harmonic functions attain their extrema on the boundary. Apply this to the
  difference of two solutions for uniqueness.
- **Energy method.** For w = u₁ − u₂ (heat equation, Dirichlet or Neumann BCs), E(t) = ∫ w² dx
  satisfies E′ = −2k ∫ w_x² ≤ 0 and E(0) = 0, so w ≡ 0. For the wave equation,
  ∫ (w_t² + c² w_x²)/2 is conserved.

## 11. Verification

```python
from sympy import Eq, Function, symbols, cos, dsolve, checkodesol, classify_ode
from sympy.solvers.pde import pdsolve
x = symbols("x"); y = Function("y")
ode = Eq(y(x).diff(x, 2) + y(x), cos(x))
classify_ode(ode)[:2]      # ('nth_linear_constant_coeff_undetermined_coefficients', ...)
sol = dsolve(ode)          # y = C2 cos x + (C1 + x/2) sin x
checkodesol(ode, sol)      # (True, 0)
X, Y = symbols("X Y"); u = Function("u")
pdsolve(2*u(X, Y).diff(X) + 3*u(X, Y).diff(Y) + u(X, Y))   # F(3X - 2Y) exp(-2X/13 - 3Y/13)
```

1. Substitute into the equation and into every initial or boundary condition, and simplify the
   residual to 0. If simplify stalls, evaluate it at exact random rationals.
2. For IVPs use `dsolve(..., ics={y(0): a, y(x).diff(x).subs(x, 0): b})`, and `hint=` to force a
   method. `checkodesol` can return False on implicit solutions it cannot simplify; check those
   numerically.
3. Compare with `scipy.integrate.solve_ivp(..., rtol=1e-10, atol=1e-12)` or a fine-grid PDE solve
   at several points. The gap must shrink at the expected rate as the tolerance or grid spacing
   shrinks.
4. State the interval of validity: singular points of the coefficients, blow-up time, and the branch
   of any sqrt or log.

## 12. Worked example: heat equation on [0, L]

Solve u_t = k u_xx for 0 < x < L, with u(0,t) = u(L,t) = 0 and u(x,0) = x(L − x).

1. **Separate.** X″ + λX = 0 with X(0) = X(L) = 0 gives X_n = sin(nπx/L), λ_n = (nπ/L)² and
   T_n = e^(−kλ_n t).
2. **Coefficients.** b_n = (2/L)∫₀^L x(L − x) sin(nπx/L) dx = 4L²(1 − (−1)ⁿ)/(n³π³). That is
   8L²/(n³π³) for odd n and 0 for even n.
3. **Solution.** u(x,t) = Σ_{n odd} 8L²/(n³π³) sin(nπx/L) e^(−kn²π²t/L²). Mode n decays at rate
   kn²π²/L². At t = L²/(kπ²), the n = 3 term is (1/27)e^(−8) ≈ 1.2·10⁻⁵ of the n = 1 term, so one
   mode describes the late solution.
4. **Truncation bound.** Keeping odd n ≤ M,
   abs(u − u_M) ≤ (8L²/π³) e^(−k(M+2)²π²t/L²) Σ_{odd n ≥ M+2} n⁻³ ≤ (2L²/(π³M²)) e^(−k(M+2)²π²t/L²),
   using Σ_{odd n ≥ M+2} n⁻³ ≤ ½∫_M^∞ x⁻³ dx. At t = 0 with L = 1 and M = 19, the bound is
   1.79·10⁻⁴ and the observed maximum error is 1.24·10⁻⁴. The coefficients are O(n⁻³), so the
   series converges uniformly and takes the initial data continuously.
5. **Sanity check.** By the maximum principle, 0 ≤ u ≤ L²/4 for all t.

```python
from sympy import symbols, integrate, sin, exp, pi, simplify, diff
x, t, L, k = symbols("x t L k", positive=True); n = symbols("n", integer=True, positive=True)
bn = simplify(2/L * integrate(x*(L - x)*sin(n*pi*x/L), (x, 0, L)))   # 4*L**2*(1 - (-1)**n)/(pi**3*n**3)
mode = sin(n*pi*x/L) * exp(-k*(n*pi/L)**2*t)
assert simplify(diff(mode, t) - k*diff(mode, x, 2)) == 0 and mode.subs(x, 0) == 0 and mode.subs(x, L) == 0

import numpy as np
from scipy.integrate import solve_ivp
L_, k_, T = 1.0, 1.0, 0.1
def u_series(xs, t, M=199):
    m = np.arange(1, M + 1, 2)
    return (8*L_**2/(m**3*np.pi**3) * np.exp(-k_*(m*np.pi/L_)**2*t) * np.sin(np.outer(xs, m)*np.pi/L_)).sum(axis=1)
for N in (100, 200, 400):                              # method of lines, central differences
    xs = np.linspace(0, L_, N + 1); h = xs[1] - xs[0]
    def rhs(t, u):
        du = np.zeros_like(u); du[1:-1] = k_*(u[2:] - 2*u[1:-1] + u[:-2])/h**2; return du
    sol = solve_ivp(rhs, (0, T), xs*(L_ - xs), method="BDF", rtol=1e-10, atol=1e-12)
    print(N, np.abs(sol.y[:, -1] - u_series(xs, T)).max())   # 7.8e-6, 1.9e-6, 4.9e-7
```

The error falls by a factor of 4 each time h halves, the second order that central differences
predict, so the series and the numerical solution agree. For L = k = 1, u(L/2, 0.1) = 0.0961619.
Status: Proved (separation with uniform convergence); the numerical check is evidence.

## 13. Pitfalls

- **Lost constant solutions.** Dividing by g(y) drops the solutions where g(y) = 0.
- **Undetermined coefficients without the resonance factor x^k.** Likewise, variation of parameters
  without first dividing by the leading coefficient.
- **Two Frobenius series assumed** when the indicial roots differ by an integer.
- **0⁻ and 0⁺ mixed up** in Laplace problems with impulses.
- **exp(∫A dt) used for non-commuting A(t).**
- **Stability claimed from the linearisation at a non-hyperbolic equilibrium.**
- **Separation errors.** Separating with inhomogeneous BCs before subtracting a steady state, or
  using the wrong eigenfunctions (Neumann problems need the constant mode).
- **Fourier misreadings.** Taking Gibbs overshoot for a bug, or quoting pointwise accuracy for a
  series truncated at a jump.
- **Characteristics past breaking.** A classical characteristic solution continued past the
  breaking time, or a shock that violates the entropy condition.
- **Unchecked dsolve output.** Reporting it without substitution, or giving an implicit solution
  without the interval where it defines y(x).
- **One numerical tolerance.** Run two tolerances or two grids.

Related: `physics-toolkit`, `julia-sciml-diffeq`, `real-complex-analysis`, `numerical-error-analysis`, `sympy-symbolic-verification`, `lagrangian-hamiltonian-mechanics`, hub `mathematics-toolkit`
