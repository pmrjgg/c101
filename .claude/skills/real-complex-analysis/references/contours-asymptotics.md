# Contour integrals, residue sums and asymptotic expansions

Every row below was checked with the script at the end (mpmath 1.3, dps 30): integrals agree to
better than 1e-30 unless stated, asymptotic rows show the error of the displayed truncation.

## 1. Standard real integrals by contours

| Integral | Value | Conditions | Contour and key step |
|---|---|---|---|
| ∫_ℝ dx/(1 + x²) | π | | semicircle, Res_i = 1/(2i) |
| ∫_ℝ dx/(1 + x⁴) | π/√2 | | semicircle, poles e^(iπ/4), e^(3iπ/4) |
| ∫_0^∞ dx/(1 + x^n) | (π/n)/sin(π/n) | n ≥ 2 | wedge of angle 2π/n, one pole e^(iπ/n) |
| ∫_ℝ cos(bx)/(x² + A²) | π e^(-Ab)/A | A > 0, b ≥ 0 | Re of e^(ibz), Jordan |
| ∫_ℝ x sin(bx)/(x² + A²) | π e^(-Ab) | A > 0, b > 0 | Im of z e^(ibz)/(z² + A²), Jordan (decay only 1/R) |
| ∫_0^∞ sin x/x | π/2 | | indented contour for e^(iz)/z: PV ∫_ℝ e^(ix)/x = iπ |
| ∫_0^∞ (1 - cos x)/x² | π/2 | | integrate by parts to ∫ sin x/x, or indent at 0 |
| ∫_0^(2π) dθ/(A + B cos θ) | 2π/√(A² - B²) | A > \|B\| | unit circle, one pole inside |
| ∫_0^∞ x^(a-1)/(1 + x) | π/sin(πa) | 0 < a < 1 | keyhole (edges differ by e^(2πia)); same as ∫_ℝ e^(at)/(1 + e^t) by x = e^t (rectangle) |
| ∫_0^∞ ln x/(1 + x²) | 0 | | x → 1/x symmetry, or keyhole with ln² |
| ∫_0^∞ ln(1 + x²)/(1 + x²) | π ln 2 | | x = tan θ: -2∫_0^(π/2) ln cos θ dθ |
| ∫_0^∞ cos(x²), ∫_0^∞ sin(x²) | √(π/8) each | | wedge of angle π/4, Jordan's inequality on the arc |
| ∫_ℝ e^(-x²) cos(2bx) | √π e^(-b²) | b real | rectangle: shift the Gaussian to Im z = b |

## 2. Sums by residues

For f rational with deg(denominator) ≥ deg(numerator) + 2 and no poles at integers:
Σ_(k∈ℤ) f(k) = -Σ_(poles z_j of f) Res[π cot(πz) f(z)] and Σ (-1)^k f(k) = -Σ Res[π csc(πz) f(z)].
The square contours through half-integers have |cot πz| bounded, so their integrals vanish.

| Sum | Value |
|---|---|
| Σ_(k∈ℤ) 1/(k² + b²) | (π/b) coth(πb) |
| Σ_(k∈ℤ) (-1)^k/(k² + b²) | (π/b) csch(πb) |
| Σ_(k≥1) 1/k² | π²/6 (limit b → 0 of the first row after removing k = 0) |

## 3. Asymptotic expansions (truncation error at the stated point)

| Quantity | Expansion | Check |
|---|---|---|
| H_n | ln n + γ + 1/(2n) - 1/(12n²) + 1/(120n⁴) - 1/(252n⁶) | error 4.1e-11 at n = 10 |
| ln n! | n ln n - n + ½ ln(2πn) + 1/(12n) - 1/(360n³) + 1/(1260n⁵) | error 5.9e-11 at n = 10 |
| Σ_(k≤n) 1/k² | π²/6 - 1/n + 1/(2n²) - 1/(6n³) + 1/(30n⁵) | error 2.4e-9 at n = 10 |
| erfc x | e^(-x²)/(x√π) (1 - 1/(2x²) + 3/(4x⁴) - ...) | relative 1.1e-4 at x = 5 |
| E₁(x) = ∫_x^∞ e^(-t)/t dt | (e^(-x)/x)(1 - 1/x + 2/x² - 6/x³ + ...) | relative 1.8e-3 at x = 10 (divergent series) |
| Γ(x + ½)/Γ(x) | √x (1 - 1/(8x) + ...) | relative 2.0e-5 at x = 20 |
| J_ν(x) | √(2/(πx)) cos(x - νπ/2 - π/4) + O(x^(-3/2)) | J₁(50) = -0.0975118 vs -0.0979276 |
| Ai(x), x → +∞ | e^(-(2/3)x^(3/2))/(2√π x^(1/4)) (1 + O(x^(-3/2))) | relative 3.2e-3 at x = 10 |
| C(2n, n) | 4^n/√(πn) (1 - 1/(8n) + ...) | ratio 1.0000032 at n = 50 |

## 4. Laplace's method: interior vs endpoint maxima

| Situation | Leading term of ∫ g e^(Mf) |
|---|---|
| interior max x₀, f''(x₀) < 0 | g(x₀) e^(Mf(x₀)) √(2π/(M\|f''(x₀)\|)) |
| endpoint max a with f'(a) = 0, f''(a) < 0 | half of the interior formula |
| endpoint max a with f'(a) < 0 (moving inward) | g(a) e^(Mf(a))/(M\|f'(a)\|) |

Checks at M = 50: ∫_0^π e^(M sin x) dx / (e^M √(2π/M)) = 1.0025 and ∫_0^π e^(M cos x) dx /
(e^M √(π/(2M))) = 1.0025; the relative correction is O(1/M) (here 1/(8M) = 0.0025).

## 5. Saddle point sketch for C(2n, n)

C(2n, n) = (1/2πi) ∮ (1 + z)^(2n) z^(-n-1) dz = (1/2πi) ∮ e^(n f(z)) dz/z with f = 2 ln(1 + z) - ln z.
f'(z) = 2/(1 + z) - 1/z = 0 at z₀ = 1, f(1) = ln 4, f''(1) = -1/2 + 1 = 1/2. On the circle |z| = 1 through
z₀ the steepest-descent direction is vertical (dz = i dy), so the integral ≈ (1/2π) e^(n ln 4)
∫ e^(-n y²/4) dy = 4^n/√(πn).

## 6. Script

```python
"""Checks for the contour-integral and asymptotics tables (mpmath 1.3). Run: python -I contours_check.py"""
from mpmath import (mp, mpf, quad, quadosc, nsum, inf, pi, e, exp, log, sqrt, sin, cos, coth, csch,
                    gamma, erfc, expint, besselj, airyai, binomial, harmonic, loggamma, euler, zeta)
mp.dps = 30
a, b, n = mpf(1)/3, mpf(2), 5
A, B = mpf(3), mpf(2)
table = [
    ("int_R dx/(1+x^2) = pi",                 quad(lambda x: 1/(1 + x**2), [-inf, inf]), pi),
    ("int_R dx/(1+x^4) = pi/sqrt2",           quad(lambda x: 1/(1 + x**4), [-inf, inf]), pi/sqrt(2)),
    ("int_0^inf dx/(1+x^n) = (pi/n)/sin(pi/n)", quad(lambda x: 1/(1 + x**n), [0, 1, inf]), (pi/n)/sin(pi/n)),
    ("int_R cos(bx)/(x^2+A^2) = pi e^{-Ab}/A",  2*quadosc(lambda x: cos(b*x)/(x**2 + A**2), [0, inf], omega=b), pi*exp(-A*b)/A),
    ("int_R x sin(bx)/(x^2+A^2) = pi e^{-Ab}",  2*quadosc(lambda x: x*sin(b*x)/(x**2 + A**2), [0, inf], omega=b), pi*exp(-A*b)),
    ("int_0^inf sin x/x = pi/2",               quadosc(lambda x: sin(x)/x, [0, inf], omega=1), pi/2),
    ("int_0^inf (1-cos x)/x^2 = pi/2 [split]", quad(lambda x: 2*sin(x/2)**2/x**2, [0, 1]) + 1 - quadosc(lambda x: cos(x)/x**2, [1, inf], omega=1), pi/2),
    ("int_0^2pi dt/(A + B cos t) = 2pi/sqrt(A^2-B^2)", quad(lambda t: 1/(A + B*cos(t)), [0, 2*pi]), 2*pi/sqrt(A**2 - B**2)),
    ("int_0^inf x^(a-1)/(1+x) = pi/sin(pi a)  [via x = e^t]", quad(lambda t: exp(a*t)/(1 + exp(t)), [-inf, 0, inf]), pi/sin(pi*a)),
    ("int_0^inf ln x/(1+x^2) = 0",             quad(lambda x: log(x)/(1 + x**2), [0, 1, inf]), mpf(0)),
    ("int_0^inf ln(1+x^2)/(1+x^2) = pi ln 2",  quad(lambda x: log(1 + x**2)/(1 + x**2), [0, inf]), pi*log(2)),
    ("int_0^inf cos(x^2) = sqrt(pi/8)",        quadosc(lambda x: cos(x**2), [0, inf], zeros=lambda k: sqrt(pi*(k - mpf(1)/2))), sqrt(pi/8)),
    ("int_R e^{-x^2} cos(2bx) = sqrt(pi) e^{-b^2}", quad(lambda x: exp(-x**2)*cos(2*b*x), [-inf, inf]), sqrt(pi)*exp(-b**2)),
    ("sum_Z 1/(k^2+b^2) = (pi/b) coth(pi b)",  nsum(lambda k: 1/(k**2 + b**2), [-inf, inf]), pi/b*coth(pi*b)),
    ("sum_Z (-1)^k/(k^2+b^2) = (pi/b) csch(pi b)", nsum(lambda k: (-1)**k/(k**2 + b**2), [-inf, inf]), pi/b*csch(pi*b)),
]
for name, got, exact in table:
    print(f"{name:58s} |error| = {mp.nstr(abs(got - exact), 3)}")

print("-- asymptotic expansions (relative or absolute error at the stated point)")
N = mpf(10)
H = log(N) + euler + 1/(2*N) - 1/(12*N**2) + 1/(120*N**4) - 1/(252*N**6)
print("H_10 expansion error", mp.nstr(harmonic(N) - H, 3))
L = N*log(N) - N + log(2*pi*N)/2 + 1/(12*N) - 1/(360*N**3) + 1/(1260*N**5)
print("ln 10! expansion error", mp.nstr(loggamma(N + 1) - L, 3))
T = pi**2/6 - 1/N + 1/(2*N**2) - 1/(6*N**3) + 1/(30*N**5)
print("sum_{k<=10} 1/k^2 tail expansion error", mp.nstr(nsum(lambda k: 1/k**2, [1, 10]) - T, 3))
X = mpf(5)
print("erfc(5) vs e^{-x^2}/(x sqrt pi)(1 - 1/(2x^2) + 3/(4x^4)) rel err", mp.nstr(erfc(X)/(exp(-X**2)/(X*sqrt(pi))*(1 - 1/(2*X**2) + 3/(4*X**4))) - 1, 3))
print("E1(10) vs (e^-x/x)(1 - 1/x + 2/x^2 - 6/x^3) rel err", mp.nstr(expint(1, 10*X/5)/(exp(-10)/10*(1 - mpf(1)/10 + mpf(2)/100 - mpf(6)/1000)) - 1, 3))
x = mpf(20)
print("Gamma(x+1/2)/Gamma(x) vs sqrt(x)(1 - 1/(8x)) rel err at 20", mp.nstr(gamma(x + mpf(1)/2)/gamma(x)/(sqrt(x)*(1 - 1/(8*x))) - 1, 3))
print("J_1(50) vs sqrt(2/(pi x)) cos(x - 3pi/4):", mp.nstr(besselj(1, 50), 8), mp.nstr(sqrt(2/(pi*50))*cos(50 - 3*pi/4), 8))
print("Ai(10) vs e^{-2/3 x^1.5}/(2 sqrt(pi) x^0.25) rel err", mp.nstr(airyai(10)/(exp(-mpf(2)/3*10**1.5)/(2*sqrt(pi)*mpf(10)**0.25)) - 1, 3))
M = mpf(50)
print("Laplace int_0^pi e^{M sin x} vs e^M sqrt(2 pi/M) ratio", mp.nstr(quad(lambda t: exp(M*sin(t)), [0, pi/2, pi])/(exp(M)*sqrt(2*pi/M)), 8))
print("endpoint (f'(a)=0) int_0^pi e^{M cos x} vs half Gaussian e^M sqrt(pi/(2M)) ratio", mp.nstr(quad(lambda t: exp(M*cos(t)), [0, pi])/(exp(M)*sqrt(pi/(2*M))), 8))
print("C(2n,n) n=50 vs 4^n/sqrt(pi n)(1 - 1/(8n)) ratio", mp.nstr(binomial(100, 50)/(4**50/sqrt(pi*50)*(1 - 1/mpf(400))), 8))
print("all contour/asymptotic checks ran")
```

Numerical pitfalls met while building this table: `quadosc` assumes sign changes, so a non-negative
tail such as (1 - cos x)/x² must be split into a non-oscillating part plus an oscillating one; and
(1 - cos x)/x² near 0 loses about 20 digits at dps 30 unless rewritten as 2 sin²(x/2)/x².
