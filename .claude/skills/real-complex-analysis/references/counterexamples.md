# Counterexample catalogue: constructions, reasons, checks

Each entry names the hypothesis it shows to be necessary. Use them two ways: before citing a theorem,
test its conclusion on the matching example; when auditing a proof, look for the step the example
would break. The script at the end reproduces every computational claim (SymPy 1.14, mpmath 1.3;
a few seconds).

## 1. Limits and integrals

| Example | Construction and reason | Hypothesis shown necessary |
|---|---|---|
| Spike n·1_(0,1/n) | → 0 pointwise, ∫ = 1 for all n; sup_n f_n(x) ≥ 1/(2x) on (0, 1/2], not integrable | DCT needs one integrable dominator; Fatou can be strict |
| Moving bump 1_[n,n+1] | → 0 pointwise, ∫ = 1; mass escapes to infinity | same; tightness |
| (1/n)·1_[0,n] | → 0 uniformly on [0, ∞), ∫ = 1 | uniform convergence moves limits inside ∫ only on finite measure |
| x^n on [0, 1] | limit is 1_{1}, discontinuous; sup_[0,1) x^n = 1 | uniform limit needed for continuity (∫ still converges by DCT) |
| Σ_(n≥0) x²/(1 + x²)^n | geometric sum = 1 + x² for x ≠ 0, 0 at x = 0 | uniform convergence of series for a continuous sum |
| sin(nx)/√n | sup = 1/√n → 0, derivative √n cos(nx) unbounded | uniform convergence of derivatives |
| a_(mn) = m/(m + n) | lim_m lim_n = 0, lim_n lim_m = 1 | iterated limits commute only under uniformity (Moore-Osgood) |
| (x² - y²)/(x² + y²)² on (0, 1)² | ∫ dy = 1/(1 + x²), so ∫∫ dy dx = π/4; by antisymmetry ∫∫ dx dy = -π/4; in polar coordinates \|f\| r = \|cos 2θ\|/r, so ∫∫ \|f\| = ∞ | Fubini needs ∫∫ \|f\| < ∞ |
| Cauchy product of Σ (-1)^n/√(n + 1) with itself | \|c_n\| = Σ_k 1/√((k + 1)(n - k + 1)) → π, terms do not tend to 0 | Mertens' theorem needs one absolutely convergent factor |

## 2. Series rearrangement

Σ (-1)^(n+1)/n = ln 2 converges conditionally. Taking two positive terms then one negative,
1 + 1/3 - 1/2 + 1/5 + 1/7 - 1/4 + ... = (3/2) ln 2. Riemann's greedy construction (add unused positive
terms while the partial sum is ≤ T, negative terms while it is > T) converges to any target T because
the terms tend to 0 and both the positive and the negative parts diverge.

## 3. Derivatives

| Example | Facts | Lesson |
|---|---|---|
| x² sin(1/x), f(0) = 0 | f'(0) = lim x sin(1/x) = 0; f'(x) = 2x sin(1/x) - cos(1/x); f'(1/(2πk)) = -1, f'(1/((2k+1)π)) = 1 | derivatives need not be continuous (they still have the intermediate value property, Darboux) |
| x² sin(1/x²), f(0) = 0 | differentiable; f'(1/√(2πk)) = -2√(2πk) → -∞ | a derivative can be unbounded, hence not Riemann integrable |
| x + 2x² sin(1/x), f(0) = 0 | f'(0) = 1 > 0 but f'(1/(2πk)) = -1: not increasing on any interval around 0 | f'(a) > 0 gives local monotonicity only if f' is continuous |
| xy/(x² + y²), 0 at the origin | partials at 0 are 0, yet f = 1/2 on the diagonal | partial derivatives do not imply continuity or differentiability |
| e^(iθ) on [0, 2π] | f(2π) - f(0) = 0 but \|f'\| = 1 | MVT is for real-valued f; use \|f(b) - f(a)\| ≤ sup\|f'\|·(b - a) |
| (x + sin x)/x as x → ∞ | limit 1, but (1 + cos x)/1 has no limit | L'Hôpital is one-directional: the limit of f'/g' must exist |

## 4. Pathological functions

- Cantor function C: write x in base 3; replace digits 2 by 1 up to the first digit 1 (which becomes
  the last binary digit 1), read in base 2. C is continuous, nondecreasing, constant on every removed
  middle third, C(0) = 0, C(1) = 1 and C' = 0 almost everywhere, so ∫_0^1 C' = 0 ≠ C(1) - C(0): the
  fundamental theorem of calculus for Lebesgue integrals needs absolute continuity.
- Weierstrass W(x) = Σ a^n cos(b^n πx) with 0 < a < 1, b odd integer and ab > 1 + 3π/2 (Weierstrass
  1872; Hardy 1916 showed ab ≥ 1 suffices): uniformly convergent (M-test) hence continuous, and nowhere
  differentiable. Difference quotients at 0 with h = b^(-m) grow like (ab)^m (6.5x per step for
  a = 1/2, b = 13 in the script).
- e^(-1/x²) with f(0) = 0: every derivative is P_k(1/x) e^(-1/x²) for a polynomial P_k, which tends to 0,
  so f^(k)(0) = 0 for all k and the Taylor series at 0 is identically 0.
- Dirichlet function 1_ℚ: discontinuous everywhere, not Riemann integrable, Lebesgue integral 0.
  Thomae's function (1/q at p/q in lowest terms, 0 at irrationals): continuous exactly at the
  irrationals, Riemann integrable with integral 0 (Lebesgue's criterion: bounded, discontinuity set
  of measure zero).
- sin x/x on [0, ∞): the improper Riemann integral is π/2, but ∫_(kπ)^((k+1)π) |sin x|/x ≥ 2/((k + 1)π),
  so ∫_0^(Nπ) |sin x|/x ≥ (2/π) H_N → ∞; it is not Lebesgue integrable, and DCT-style arguments must
  work with the truncated integrals.
- 1/(1 + x²): analytic on ℝ, but its Taylor series at a has radius √(1 + a²), the distance to ±i.

## 5. Script

```python
"""Checks for the counterexample catalogue (SymPy 1.14, mpmath 1.3). Run: python -I counterexamples_check.py"""
import sympy as sp
from fractions import Fraction
from mpmath import mp, mpf, quad, pi, sin, cos, exp, log, sqrt, fsum, inf, harmonic, euler

x, y = sp.symbols("x y", positive=True)

# 1. Fubini failure: iterated integrals of (x^2 - y^2)/(x^2 + y^2)^2 on (0,1)^2
f = (x**2 - y**2) / (x**2 + y**2)**2
inner_y = sp.simplify(sp.integrate(f, (y, 0, 1)))          # 1/(x**2 + 1)
inner_x = sp.simplify(sp.integrate(f, (x, 0, 1)))          # -1/(y**2 + 1)
print("Fubini:", inner_y, sp.integrate(inner_y, (x, 0, 1)), "|", inner_x, sp.integrate(inner_x, (y, 0, 1)))

# 2. Riemann rearrangement: greedy reordering of sum (-1)^(n+1)/n towards any target T
def rearrange(T, terms=200000):
    pos, neg, s = 1, 2, 0.0          # next odd (positive) and even (negative) denominators
    for _ in range(terms):
        if s <= T:
            s += 1.0 / pos; pos += 2
        else:
            s -= 1.0 / neg; neg += 2
    return s
print("rearranged to pi:", rearrange(3.141592653589793), " to -1:", rearrange(-1.0))
mp.dps = 20
s = fsum(mpf(1)/(4*k + 1) + mpf(1)/(4*k + 3) - mpf(1)/(2*k + 2) for k in range(300000))
print("1 + 1/3 - 1/2 + ... =", s, " (3/2) ln 2 =", 1.5 * log(2))

# 3. x^2 sin(1/x): derivative exists everywhere, f' discontinuous at 0
t = sp.symbols("t", real=True)
g = t**2 * sp.sin(1/t)
print("difference quotient at 0 -> ", sp.limit(g/t, t, 0), "; f'(1/(2 pi k)) =", sp.simplify(sp.diff(g, t).subs(t, 1/(2*sp.pi*7))))
g2 = t**2 * sp.sin(1/t**2)
print("x^2 sin(1/x^2): f'(1/sqrt(2 pi k)) =", sp.simplify(sp.diff(g2, t).subs(t, 1/sp.sqrt(2*sp.pi*50))))

# 4. x + 2x^2 sin(1/x): f'(0) = 1 > 0 but f is not increasing on any neighbourhood of 0
h = t + 2*t**2*sp.sin(1/t)
print("f'(0) =", sp.limit(h/t, t, 0), "; f'(1/(2 pi k)) =", sp.simplify(sp.diff(h, t).subs(t, 1/(2*sp.pi*9))))

# 5. e^(-1/x^2): every derivative at 0 is 0
E = sp.exp(-1/t**2)
print("derivatives of exp(-1/x^2) at 0 (limits):", [sp.limit(sp.diff(E, t, k), t, 0) for k in range(1, 5)])

# 6. Cantor function via ternary digits (exact rationals)
def cantor(q, depth=60):
    q, val, scale = Fraction(q), Fraction(0), Fraction(1, 2)
    for _ in range(depth):
        q *= 3
        d = int(q); q -= d
        if d == 1:
            return val + scale
        val += scale * (d // 2)
        scale /= 2
    return val
print("Cantor: C(1/4) ~", float(cantor(Fraction(1, 4))), " C(1/3), C(1/2), C(2/3) =", cantor(Fraction(1, 3)), cantor(Fraction(1, 2)), cantor(Fraction(2, 3)), " C(0.0123) =", float(cantor(Fraction(123, 10000))))

# 7. Weierstrass W(x) = sum a^n cos(b^n pi x), a = 0.5, b = 13 (ab = 6.5 > 1 + 3pi/2 = 5.71)
a, b = mpf("0.5"), 13
W = lambda z: fsum(a**n * cos(b**n * pi * z) for n in range(0, 40))
mp.dps = 60
print("Weierstrass |difference quotients| at 0, h = b^-m:", [mp.nstr(abs((W(mpf(b)**-m) - W(0)) * mpf(b)**m), 4) for m in range(1, 6)])
mp.dps = 20

# 8. sin x / x is not absolutely integrable: int_0^{N pi} |sin x|/x >= (2/pi) H_N
for N in (10, 100):
    v = quad(lambda z: abs(sin(z)) / z, [k * pi for k in range(N + 1)])
    print("int_0^{%d pi} |sin x|/x = %s >= (2/pi) H_N = %s" % (N, mp.nstr(v, 8), mp.nstr(2 / pi * harmonic(N), 8)))

# 9. Sum of continuous functions with a discontinuous sum: sum_{n>=0} x^2/(1+x^2)^n = 1 + x^2 (x != 0), 0 at 0
n = sp.symbols("n", integer=True, nonnegative=True)
print("series sum:", sp.simplify(sp.summation(x**2 / (1 + x**2)**n, (n, 0, sp.oo))))

# 10. L'Hopital's converse fails: (x + sin x)/x -> 1 while (1 + cos x)/1 has no limit
print("lim (x + sin x)/x =", sp.limit((t + sp.sin(t))/t, t, sp.oo), "; lim (1 + cos x) =", sp.limit(1 + sp.cos(t), t, sp.oo))

# 11. iterated limits of m/(m+n)
m_, n_ = sp.symbols("m n", positive=True)
print("iterated limits:", sp.limit(sp.limit(m_/(m_ + n_), n_, sp.oo), m_, sp.oo), sp.limit(sp.limit(m_/(m_ + n_), m_, sp.oo), n_, sp.oo))

# 12. xy/(x^2+y^2): along y = x the value is 1/2, partial derivatives at 0 are 0
F = x*y/(x**2 + y**2)
print("xy/(x^2+y^2) on the diagonal:", sp.simplify(F.subs(y, x)))

# 13. Cauchy product of sum (-1)^n/sqrt(n+1) with itself: |c_n| does not tend to 0
for N in (10, 100, 1000):
    c = fsum(1 / sqrt((k + 1) * (N - k + 1)) for k in range(N + 1))
    print("|c_%d| = %s" % (N, mp.nstr(c, 6)))

# 14. sin(nx)/sqrt(n) -> 0 uniformly, derivatives sqrt(n) cos(nx) unbounded
print("sup|sin(nx)/sqrt n| = 1/sqrt n; derivative at 0 =", [sp.sqrt(k) for k in (1, 4, 100)])
print("all counterexample checks ran")
```

Expected output (abridged): `Fubini: 1/(x**2 + 1) pi/4 | -1/(y**2 + 1) -pi/4`; rearranged sums near π
and -1; `1 + 1/3 - 1/2 + ... = 1.03971993...` vs (3/2) ln 2 = 1.03972077 (slow convergence, error
~ 1/(4·3·10^5)); `f'(1/(2 pi k)) = -1`; derivative limits `[0, 0, 0, 0]`; Cantor values 1/3, 1/2;
Weierstrass quotients 26.4, 171.5, 1115, 7245, 47090; ∫|sin x|/x = 3.31 and 4.77; `x**2 + 1`;
`AccumBounds(0, 2)`; iterated limits `0 1`; `1/2`; |c_n| = 2.29, 2.85, 3.05.
