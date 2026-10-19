---
name: real-complex-analysis
description: "Rigorous real and complex analysis: epsilon-delta templates, convergence tests, uniform convergence and limit-interchange theorems with their hypotheses, measure-theoretic convergence theorems, a counterexample catalogue, asymptotic expansions (Laplace, Euler-Maclaurin, Watson, saddle point), and contour integration with residues and branch cuts. Load when a proof or derivation involves limits, series, integrals, analytic estimates or contour integrals."
when_to_use: "Proving a limit, continuity or convergence claim; swapping a limit with a sum, integral or derivative; deciding whether a series converges; differentiating under the integral sign; auditing a derivation that uses Fubini, DCT, L'Hopital, MVT or Taylor; asymptotics of sums or integrals (Stirling, H_n, Laplace, stationary phase); evaluating real integrals by residues or keyhole contours; checking a closed form with mpmath."
---

# Real and complex analysis

The usual error is not a wrong theorem but a missing hypothesis. Rules: every interchange of
limits, sums, integrals or derivatives names its theorem and the line where the hypothesis is
checked; constants carry their dependencies (δ = δ(ε, x)); every evaluated integral or sum gets a
numerical check at two precisions. Status labels as in hub `mathematics-toolkit`.
Deep material: [counterexamples with checks](references/counterexamples.md) |
[contour integrals and asymptotic expansions](references/contours-asymptotics.md).

## 1. Epsilon-delta templates

```
limit       lim_{x→a} f = L   ∀ε>0 ∃δ>0 ∀x: 0 < |x-a| < δ ⇒ |f(x) - L| < ε      δ = δ(ε, a)
uniform cont. on S            ∀ε ∃δ ∀x,y ∈ S: |x-y| < δ ⇒ |f(x) - f(y)| < ε    δ = δ(ε) only
sequence    a_n → L           ∀ε ∃N ∀n ≥ N: |a_n - L| < ε                        N = N(ε)
Cauchy                        ∀ε ∃N ∀m,n ≥ N: |a_m - a_n| < ε
pointwise   f_n → f on S      ∀x ∈ S ∀ε ∃N ∀n ≥ N: |f_n(x) - f(x)| < ε           N = N(ε, x)
uniform     f_n ⇉ f on S      ∀ε ∃N ∀n ≥ N ∀x ∈ S: |f_n(x) - f(x)| < ε  ⇔  sup_S |f_n - f| → 0
```

| Negation | Usable form | Example |
|---|---|---|
| not uniformly continuous | ∃ε ∃x_n, y_n: \|x_n - y_n\| → 0, \|f(x_n) - f(y_n)\| ≥ ε | x² on ℝ: x_n = n, y_n = n + 1/n, gap 2 + 1/n² |
| not uniformly convergent | ∃ε ∃x_n: \|f_n(x_n) - f(x_n)\| ≥ ε | x^n on [0, 1): x_n = 2^(-1/n) gives 1/2 |
| not Cauchy / no limit | ∃ε, subsequences staying ε apart | (-1)^n with ε = 1 |

Explicit δ: for x² at a, |x² - a²| = |x - a||x + a| ≤ |x - a|(2|a| + 1) once |x - a| < 1, so
δ = min(1, ε/(2|a| + 1)) (depends on a: continuity, not uniform continuity on ℝ). For 1/x at a > 0:
δ = min(a/2, a²ε/2).

Standard estimates:
- Add and subtract a term you control, then the triangle inequality.
- ε/3: |f(x) - f(y)| ≤ |f - f_N|(x) + |f_N(x) - f_N(y)| + |f_N - f|(y) proves that a uniform limit of
  continuous functions is continuous; choose N first (uniformity), then δ for f_N.
- Split a sum or integral into a head and a tail: fix the tail bound K(ε) first, then n for the
  head (Cesàro means, Abelian theorems, Tauberian arguments).
- Squeeze; bounded monotone sequences converge; "eventually" bounds (a_n ≥ L/2 > 0 for n ≥ N₁) before
  dividing by a_n.
- Statement shape "limit / convergence" (hub table): ε-δ with explicit choice, squeeze, monotone +
  bounded, dominated convergence; an interchange of limits always needs a theorem.

## 2. Series convergence

| Shape | Test | Verdict and caveat |
|---|---|---|
| a_n ↛ 0 | n-th term | diverges |
| Σ n^(-p), Σ 1/(n (ln n)^p) | p-series, Cauchy condensation | converge iff p > 1 |
| 0 ≤ a_n ≤ b_n | comparison | Σ b_n < ∞ ⇒ Σ a_n < ∞ |
| a_n/b_n → c ∈ (0, ∞), both positive | limit comparison | same behaviour |
| factorials, exponentials | ratio: L = lim \|a_(n+1)/a_n\| | L < 1 absolutely convergent, L > 1 diverges, L = 1 says nothing (Σ 1/n, Σ 1/n²) |
| n-th powers | root: L = limsup \|a_n\|^(1/n) | same thresholds; stronger than ratio |
| ratio → 1 | Raabe: n(a_n/a_(n+1) - 1) → R | R > 1 converges, R < 1 diverges |
| a_n = f(n), f ≥ 0 decreasing | integral test | ∫_(N+1)^∞ f ≤ Σ_(n>N) a_n ≤ ∫_N^∞ f gives the tail |
| (-1)^n b_n, b_n ↓ 0 | Leibniz | converges; \|R_N\| ≤ b_(N+1), sign of the first omitted term |
| Σ a_n b_n, partial sums of a_n bounded, b_n monotone → 0 | Dirichlet | Σ sin(nx)/n, x ∉ 2πℤ |
| Σ a_n converges, b_n monotone bounded | Abel | |
| a_n ≥ 0 nonincreasing | Cauchy condensation | Σ a_n < ∞ ⇔ Σ 2^k a_(2^k) < ∞ |
| Σ c_n z^n | radius R = 1/limsup \|c_n\|^(1/n) | absolute inside, uniform on compact subsets; boundary case by case; Abel's theorem: Σ c_n converges ⇒ lim_(x→1⁻) Σ c_n x^n = Σ c_n |

- Absolute convergence ⇒ every rearrangement has the same sum. Conditional convergence ⇒ Riemann
  rearrangement: any real limit or ±∞. Σ (-1)^(n+1)/n = ln 2, while 1 + 1/3 - 1/2 + 1/5 + 1/7 - 1/4 + ...
  = (3/2) ln 2 (checked to 6 digits with 6·10^5 terms).
- Cauchy products: Σ c_n converges to the product when one factor converges absolutely (Mertens);
  (Σ (-1)^n/√(n+1))² has |c_n| → π, so it diverges.

## 3. Uniform convergence and the real-analysis facts table

- Weierstrass M-test: |f_n| ≤ M_n on S and Σ M_n < ∞ ⇒ Σ f_n converges absolutely and uniformly on S.
- Dini: f_n continuous on compact K, monotone in n, pointwise limit continuous ⇒ uniform.
- Arzelà-Ascoli: uniformly bounded and equicontinuous on compact K ⇒ a uniformly convergent subsequence.
- Integration: f_n ⇉ f on [a, b] ⇒ ∫_a^b f_n → ∫_a^b f. Not on infinite intervals: (1/n)·1_[0,n] ⇉ 0
  but every integral is 1.
- Differentiation: f_n' ⇉ g on [a, b] and f_n(x₀) converges ⇒ f_n ⇉ f and f' = g. Uniform
  convergence of f_n alone is not enough: sin(nx)/√n ⇉ 0, derivatives √n cos(nx) diverge.

| Fact | Statement | Hypothesis people forget |
|---|---|---|
| Completeness | non-empty set bounded above has a supremum | ℝ (fails in ℚ) |
| Monotone sequences | bounded monotone ⇒ convergent | real-valued |
| Bolzano-Weierstrass | bounded sequence has a convergent subsequence | finite dimension |
| Heine-Borel | compact ⇔ closed and bounded | ℝ^n; false in infinite dimensions |
| Extreme value | continuous f on K attains max and min | K compact: closed and bounded interval, not (0, 1) |
| Heine-Cantor | continuous on compact ⇒ uniformly continuous | compact |
| IVT | f(a) < y < f(b) ⇒ ∃c, f(c) = y | real-valued, connected domain |
| MVT | f(b) - f(a) = f'(c)(b - a) | continuous on [a, b], differentiable on (a, b), real-valued (fails for e^(ix) on [0, 2π]; use \|f(b) - f(a)\| ≤ sup\|f'\|\|b - a\|) |
| Taylor (Lagrange) | R_n = f^(n+1)(ξ)(x - a)^(n+1)/(n+1)! | f ∈ C^(n+1) on the interval |
| L'Hôpital | lim f/g = lim f'/g' | 0/0 or ∞/∞, g' ≠ 0 near the point, and lim f'/g' exists |
| Uniform limit | uniform limit of continuous functions is continuous | uniform, not pointwise (x^n on [0, 1]) |
| Term-by-term derivative | (Σ f_n)' = Σ f_n' | Σ f_n' converges uniformly and Σ f_n converges at one point |
| ∫ lim = lim ∫ | | dominated or monotone convergence, or uniform convergence on a finite measure space |
| Swap sums / integrals | Fubini | absolute integrability (Tonelli when f ≥ 0) |
| Rearranging a series | same sum | absolute convergence |
| Banach fixed point | unique fixed point, geometric convergence | contraction constant < 1 on a complete metric space |
| Stone-Weierstrass | polynomials dense in C([a, b]) (sup norm) | compact interval, or compact Hausdorff with a separating unital subalgebra |

## 4. Interchange theorems (measure and integration)

| Theorem | Conclusion | Hypotheses |
|---|---|---|
| Monotone convergence | 0 ≤ f_n ↑ f ⇒ ∫ f_n → ∫ f; also ∫ Σ f_n = Σ ∫ f_n for f_n ≥ 0 | measurable, non-negative |
| Fatou | ∫ liminf f_n ≤ liminf ∫ f_n | non-negative measurable; strict for n·1_(0,1/n) |
| Dominated convergence | f_n → f a.e., \|f_n\| ≤ g ∈ L¹ ⇒ ∫ f_n → ∫ f and ∫\|f_n - f\| → 0 | one integrable g for all n |
| Bounded convergence | \|f_n\| ≤ M, f_n → f a.e. ⇒ ∫ f_n → ∫ f | finite measure |
| Vitali | f_n → f in measure and {f_n} uniformly integrable ⇔ f_n → f in L¹ | finite measure; use when no dominator exists |
| Fubini | iterated integrals equal the double integral | ∫∫ \|f\| < ∞ |
| Tonelli | same, values may be +∞ | f ≥ 0 measurable, σ-finite spaces |
| Sum-integral swap | Σ ∫ f_n = ∫ Σ f_n | Σ ∫ \|f_n\| < ∞, or f_n ≥ 0 |
| Leibniz rule | d/dt ∫ f(x, t) dx = ∫ ∂_t f(x, t) dx | ∂_t f exists and \|∂_t f(x, t)\| ≤ g(x) ∈ L¹ for all t near t₀ (g independent of t) |
| Variable limits | d/dt ∫_(a(t))^(b(t)) f = f(b, t) b' - f(a, t) a' + ∫ ∂_t f | as above, f continuous |
| Change of variables | ∫_(φ(U)) f = ∫_U f(φ(u)) \|det Dφ(u)\| du | φ a C¹ diffeomorphism (injective); in 1D a C¹ monotone map |
| Cauchy-Schwarz in L² | \|∫ fg\| ≤ ‖f‖₂ ‖g‖₂ | f, g ∈ L² |

Finding a dominating function:
1. Compute g(x) = sup_n |f_n(x)| (the best dominator) and test ∫ g < ∞.
2. Standard bounds: (1 - x/n)^n 1_[0,n](x) ≤ e^(-x) (since ln(1 - y) ≤ -y); (1 + x/n)^(-n) ≤ (1 + x/2)^(-2)
   for n ≥ 2, x ≥ 0; |sin u| ≤ min(1, |u|); |e^(iu) - 1| ≤ min(2, |u|).
3. Split the domain: near each singularity and near infinity separately.
4. If sup_n |f_n| is not integrable because mass escapes (moving bump, spike n·1_(0,1/n)), DCT does not
   apply; test the conclusion on that example before trying harder.

Examples: lim ∫_0^n (1 - x/n)^n dx = ∫_0^∞ e^(-x) dx = 1 by DCT (exact value n/(n + 1)).
I(t) = ∫_0^∞ e^(-x) sin(tx)/x dx: ∂_t integrand = e^(-x) cos(tx), dominated by e^(-x), so
I'(t) = 1/(1 + t²), I(0) = 0, I(t) = arctan t (checked with `quadosc` at t = 0.5, 2, 10).

## 5. Counterexample catalogue

| Example | What it breaks |
|---|---|
| f_n = n·1_(0,1/n) | f_n → 0 pointwise, ∫ f_n = 1: no dominating function (sup_n f_n ≈ 1/x); Fatou strict |
| f_n = 1_[n,n+1]; (1/n)·1_[0,n] | mass escapes to infinity; uniform convergence on an infinite measure space does not move limits inside ∫ |
| x^n on [0, 1] | continuous functions, discontinuous pointwise limit; not uniform (yet ∫ → 0 by DCT) |
| (x² - y²)/(x² + y²)² on (0, 1)² | ∫_0^1∫_0^1 dy dx = π/4, ∫_0^1∫_0^1 dx dy = -π/4 (inner ∫_0^1 dy = 1/(1 + x²)); ∫∫\|f\| = ∞, Fubini fails |
| Σ (-1)^(n+1)/n and its rearrangements | ln 2 vs (3/2) ln 2 vs any real number |
| x² sin(1/x), f(0) = 0 | differentiable everywhere with f'(0) = 0, f' = 2x sin(1/x) - cos(1/x) discontinuous at 0 |
| x² sin(1/x²), f(0) = 0 | differentiable, f' unbounded near 0: not Riemann integrable although it is a derivative |
| Cantor function | continuous, nondecreasing, f' = 0 a.e., f(1) - f(0) = 1 ≠ ∫ f' = 0: FTC needs absolute continuity |
| Weierstrass W(x) = Σ a^n cos(b^n π x) | 0 < a < 1, b odd integer, ab > 1 + 3π/2: continuous, nowhere differentiable (Hardy: ab ≥ 1 suffices) |
| e^(-1/x²), f(0) = 0 | C^∞ with every derivative 0 at 0: Taylor series 0 ≠ f; smooth is not analytic |
| sin x/x on [0, ∞) | improper Riemann integral π/2, not Lebesgue integrable (∫_0^(Nπ) \|sin x\|/x ≈ (2/π) ln N + C) |
| 1_ℚ; Thomae's function | not Riemann integrable (Lebesgue ∫ = 0); continuous exactly at the irrationals |
| a_(mn) = m/(m + n) | lim_m lim_n = 0 ≠ 1 = lim_n lim_m |
| xy/(x² + y²), 0 at the origin | partial derivatives exist everywhere, not continuous, not differentiable at 0 |
| 1/(1 + x²) | real-analytic on ℝ, Taylor radius 1 at 0 (poles at ±i), √(1 + a²) at a |

Constructions and checking code: [counterexamples](references/counterexamples.md).

## 6. Taylor's theorem and rigorous remainders

| Remainder | Formula (between a and x) | Use |
|---|---|---|
| Lagrange | f^(n+1)(ξ)(x - a)^(n+1)/(n + 1)! | bound with M = max \|f^(n+1)\| |
| Integral | ∫_a^x f^(n+1)(t)(x - t)^n/n! dt | exact; sign and monotonicity information |
| Cauchy | f^(n+1)(ξ)(x - ξ)^n (x - a)/n! | log(1 + x) near x = -1 |
| Alternating | ≤ first omitted term | when the series alternates with decreasing terms |
| Multivariate | f(x + h) = f(x) + ∇f·h + ½ hᵀ∇²f(x + θh) h | second-order conditions, error of linearisation |

- Rigorous numerical error: e = Σ_(k≤n) 1/k! + R with 0 < R < 3/(n + 1)! (e^ξ < 3 on (0, 1)). For
  10^(-10), n = 13: bound 3/14! = 3.4e-11, actual 1.23e-11. Bound M with interval arithmetic
  (`mpmath.iv`, python-flint `arb`) when f^(n+1) is messy.
- Analytic vs C^∞: a real-analytic f equals its Taylor series near a; the radius is the distance from a to
  the nearest complex singularity. C^∞ alone gives no convergence (e^(-1/x²)).

## 7. Asymptotic methods

- O, o, ~: f = O(g) means |f| ≤ C|g| near the stated limit point, with C independent of every other
  parameter unless you say so; f = o(g): f/g → 0; f ~ g: f/g → 1, i.e. f = g(1 + o(1)).
- Algebra: O(f) + O(g) = O(|f| + |g|); O(f)O(g) = O(fg). ~ survives products, quotients and logs of
  functions → 0 or ∞, not sums with cancellation or exponentiation (n² + n ~ n² but e^(n²+n)/e^(n²) = e^n).
- Euler-Maclaurin: Σ_(k=a)^b f(k) = ∫_a^b f + (f(a) + f(b))/2 + Σ_(j=1)^p B_(2j)/(2j)! (f^(2j-1)(b) - f^(2j-1)(a)) + R_p,
  |R_p| ≤ 2ζ(2p)/(2π)^(2p) ∫_a^b |f^(2p)|; B₂ = 1/6, B₄ = -1/30, B₆ = 1/42.
  - H_n = ln n + γ + 1/(2n) - 1/(12n²) + 1/(120n⁴) - 1/(252n⁶) + ... (error 4.1e-11 at n = 10)
  - ln n! = n ln n - n + ½ ln(2πn) + 1/(12n) - 1/(360n³) + 1/(1260n⁵) - ... (error 5.9e-11 at n = 10);
    √(2πn)(n/e)^n ≤ n! ≤ e√n(n/e)^n; C(2n, n) ~ 4^n/√(πn) (ratio 0.9876 at n = 10, 0.99875 at n = 100)
  - f decreasing: ∫_1^(n+1) f ≤ Σ_(k=1)^n f(k) ≤ f(1) + ∫_1^n f
- Laplace: ∫_a^b g e^(Mf) dx ~ g(x₀) e^(Mf(x₀)) √(2π/(M|f''(x₀)|)) for a unique interior maximum x₀ with
  f''(x₀) < 0 and g(x₀) ≠ 0; maximum at an endpoint a with f'(a) < 0: ~ g(a) e^(Mf(a))/(M|f'(a)|).
  n! = ∫_0^∞ e^(n ln t - t) dt gives Stirling.
- Watson's lemma: ∫_0^T e^(-λt) t^α h(t) dt with h(t) ~ Σ a_k t^k at 0, α > -1, h of at most exponential
  growth: ~ Σ a_k Γ(k + α + 1)/λ^(k+α+1).
- Stationary phase: ∫_a^b g e^(iλφ) dx with one nondegenerate stationary point x₀ ∈ (a, b):
  ~ g(x₀) e^(iλφ(x₀) + iπ sgn(φ''(x₀))/4) √(2π/(λ|φ''(x₀)|)); no stationary point: O(1/λ) from the endpoints.
  J₀(x) ~ √(2/(πx)) cos(x - π/4): -0.24594 vs -0.24676 at x = 10, 0.019986 vs 0.020083 at x = 100.
- Saddle point: deform the contour through z₀ with f'(z₀) = 0 along the steepest-descent path (Im f
  constant): ∫ g e^(λf) dz ~ g(z₀) e^(λf(z₀)) √(2π/(-λ f''(z₀))), branch of the root fixed by the
  direction of travel. C(2n, n) = (1/2πi)∮ (1 + z)^(2n) z^(-n-1) dz gives 4^n/√(πn).
- Divergent asymptotic series: terms shrink, then grow; stop before the smallest term, and the error
  is about the first omitted term. ∫_0^∞ e^(-λt)/(1 + t) dt ~ Σ (-1)^k k!/λ^(k+1): at λ = 10 the value is
  0.0915633339; the best truncation (k ≤ 9) errs by 1.8e-5, and the smallest term is 10!/10^11 = 3.6e-5.

More expansions and their checks: [contours and asymptotics](references/contours-asymptotics.md).

## 8. Complex analysis facts with hypotheses

| Fact | Statement | Hypotheses |
|---|---|---|
| Cauchy's theorem | ∮_γ f = 0 | f holomorphic on a simply connected domain containing γ (or γ null-homologous) |
| Cauchy's integral formula | f^(n)(z₀) = n!/(2πi) ∮ f(z)/(z - z₀)^(n+1) dz; \|f^(n)(z₀)\| ≤ n! M/r^n | holomorphic inside and on γ, z₀ inside, γ positively oriented |
| Residue theorem | ∮_γ f = 2πi Σ Res (poles inside) | meromorphic inside, no poles on γ |
| Liouville | bounded entire ⇒ constant | entire |
| Maximum modulus | \|f\| has no interior maximum | holomorphic, non-constant, connected open set |
| Identity theorem | f = g on a set with a limit point inside ⇒ f ≡ g | connected domain |
| Argument principle | (1/2πi) ∮ f'/f = Z - P with multiplicity | meromorphic inside, no zeros or poles on γ |
| Rouché | \|f - g\| < \|g\| on γ (or \|f + g\| < \|f\| + \|g\|) ⇒ same number of zeros inside | f, g holomorphic inside and on γ |
| Jordan's lemma | \|∫_(C_R) e^(iaz) g dz\| ≤ (π/a) max_(C_R) \|g\| → 0 | a > 0, upper semicircle C_R, max \|g\| → 0 (lower half-plane for a < 0) |
| ML inequality | \|∫_γ f\| ≤ length(γ) · max_γ \|f\| | f continuous on γ |
| Removable singularity | bounded near an isolated singularity ⇒ removable | isolated singularity |

Rouché in practice: z⁵ + 3z + 1 against 3z on |z| = 1 gives |z⁵ + 1| ≤ 2 < 3, so exactly one zero in
the unit disc (numpy roots have moduli 1.374, 1.374, 1.263, 1.263, 0.332; the argument-principle
integral evaluates to 1.0000).

## 9. Contour integration recipe

| Integral | Contour | Vanishing argument |
|---|---|---|
| ∫_ℝ P/Q, deg Q ≥ deg P + 2 | upper semicircle | ML: πR·O(R^(-2)) |
| ∫_ℝ R(x) e^(iax), a > 0, deg Q ≥ deg P + 1 | upper semicircle (lower for a < 0) | Jordan |
| ∫_0^(2π) R(cos θ, sin θ) dθ | unit circle, z = e^(iθ), cos θ = (z + 1/z)/2, sin θ = (z - 1/z)/(2i), dθ = dz/(iz) | none needed |
| ∫_0^∞ x^(a-1) R(x) dx, ∫ R(x) ln x | keyhole, cut on [0, ∞), arg ∈ [0, 2π) | small circle O(r^a) needs a > 0 (R(0) finite); large circle needs a < deg Q - deg P |
| ∫_ℝ e^(ax)/(1 + e^x), Gaussian shifts | rectangle of height 2π (one period) | vertical sides decay exponentially |
| pole on the real axis (principal value) | indent with a small semicircle | a clockwise half-circle at a simple pole gives -πi Res |
| ∫_0^∞ cos(x²), ∫_0^∞ dx/(1 + x^n) | wedge of angle π/4, 2π/n | Jordan's inequality sin 2θ ≥ 4θ/π (Fresnel); ML (1/(1 + x^n)) |

Residues: simple pole of g/h (g(z₀) ≠ 0, h(z₀) = 0, h'(z₀) ≠ 0): g(z₀)/h'(z₀). Pole of order m:
(1/(m - 1)!) lim_(z→z₀) d^(m-1)/dz^(m-1) [(z - z₀)^m f(z)]. Or read the (z - z₀)^(-1) Laurent
coefficient (`sympy.residue(f, z, z0)`, `series`). At infinity: Res_∞ f = -Res_(w=0) f(1/w)/w²;
all residues including ∞ sum to 0. Principal value with poles on the axis:
PV ∫ = 2πi Σ_(upper) Res + πi Σ_(axis) Res.

Branches (numpy, cmath, SymPy and mpmath agree): Log z = ln|z| + i Arg z with Arg ∈ (-π, π], cut on the
negative real axis; z^a = e^(a Log z); √ has the same cut. Signed zero picks the side in numpy/cmath:
`np.log(complex(-1, 0.0))` = πi, `np.log(complex(-1, -0.0))` = -πi, `np.sqrt(complex(-4, -0.0))` = -2j.
A keyhole needs arg ∈ [0, 2π), which is not the principal branch: write log z = Log(-z) + iπ yourself.
`(-8)**(1/3)` in Python is the principal root 1 + 1.732i; `np.cbrt(-8.0)` = -2; `np.power(-8.0, 1/3)` = nan.

## 10. Numerical checks (two precisions, every time)

```python
from mpmath import mp, quad, quadosc, nsum, inf, pi, e, cos, identify
for dps in (30, 60):
    mp.dps = dps
    v = 2*quadosc(lambda x: cos(x)/(1 + x**2), [0, inf], omega=1)
    print(dps, v, v - pi/e)
print(identify(v, ["pi", "e"]))          # proposes (1*pi)/e; a guess until proved
```

- `quad` (tanh-sinh by default) handles endpoint singularities; split at interior kinks:
  `quad(f, [a, c, b])`. Oscillatory infinite ranges need `quadosc` (`omega=`, `period=` or `zeros=`):
  plain `quad` on ∫_ℝ cos x/(1 + x²) is off by 4e-3 at dps 30 with no warning.
- `nsum(f, [1, inf])` accelerates convergence (Richardson, Euler-Maclaurin, Levin-type); compare
  with a direct partial sum plus an integral-test tail bound.
- Agreement to ~30 digits at dps 30 and 60 plus a matching closed form is strong evidence: label it
  "Numerical evidence (N digits)", never "Proved". `identify` and `pslq` only propose closed forms.
- Rigorous enclosures: `mpmath.iv`, python-flint `arb`/`acb` (`acb.integral` returns a certified
  ball), Julia IntervalArithmetic.jl: label "Verified (rigorous enclosure)".
- Nested `quad` loses digits at corner singularities (0.7853973 instead of π/4 = 0.7853982 for the
  Fubini example): do the inner integral in closed form or split the square, and compare precisions.
- SymPy closed forms may be unsimplified: `integrate(cos(x)/(1 + x**2), (x, -oo, oo))` returns
  sqrt(pi)*(-sqrt(pi)*sinh(1) + sqrt(pi)*cosh(1)); `simplify` gives pi*exp(-1).

## 11. Worked example: ∫_ℝ cos x/(1 + x²) dx = π/e

1. Integrand: |cos x/(1 + x²)| ≤ 1/(1 + x²) ∈ L¹(ℝ), so the integral converges absolutely and equals
   lim_(R→∞) ∫_(-R)^R (no principal-value subtlety).
2. Complexify: f(z) = e^(iz)/(1 + z²); on ℝ, Re f = cos x/(1 + x²) and Im f = sin x/(1 + x²) (odd,
   integral 0). Poles: z = ±i, simple; only i lies in the upper half-plane.
3. Contour: [-R, R] followed by the upper semicircle C_R, R > 1, positively oriented; no poles on it.
4. Residue: g/h' rule with g = e^(iz), h = 1 + z²: Res_(z=i) = e^(i·i)/(2i) = e^(-1)/(2i).
   Residue theorem: ∮ f = 2πi · e^(-1)/(2i) = π/e for every R > 1.
5. Arc: on C_R, z = Re^(iθ), θ ∈ [0, π]; |e^(iz)| = e^(-R sin θ) ≤ 1 and |1 + z²| ≥ R² - 1. Jordan's lemma
   with a = 1, g = 1/(1 + z²), max_(C_R)|g| ≤ 1/(R² - 1): |∫_(C_R) f| ≤ π/(R² - 1) → 0. (ML alone also works
   here: πR/(R² - 1) → 0.)
6. Limit: ∫_(-R)^R f(x) dx = π/e - ∫_(C_R) f → π/e. Taking real parts, ∫_ℝ cos x/(1 + x²) dx = π/e. ∎
7. Check:

```python
from mpmath import mp, quadosc, quad, inf, pi, e, cos
import sympy as sp
for dps in (30, 60):
    mp.dps = dps
    v = 2*quadosc(lambda x: cos(x)/(1 + x**2), [0, inf], omega=1)
    print(dps, mp.nstr(v, 25), mp.nstr(v - pi/e, 3))
z = sp.symbols("z")
print(sp.residue(sp.exp(sp.I*z)/(1 + z**2), z, sp.I))    # -I*exp(-1)/2 = e^(-1)/(2i)
```

Output: `30 1.155727349790921717910093 1.97e-31` and `60 1.155727349790921717910093 0.0`; residue
`-I*exp(-1)/2`. Status: Proved (residue theorem + Jordan's lemma); numerical evidence agrees to 30
digits at both precisions.

## Pitfalls

- Swapping lim, Σ, ∫ or d/dt without naming DCT, MCT, Fubini/Tonelli or uniform convergence and
  checking its hypothesis on the actual functions.
- Wrong quantifier order (∃δ ∀ε), or N silently depending on x in a "uniform" claim.
- Ratio test limit 1 read as divergence; rearranging or multiplying conditionally convergent series.
- A "dominating" function that depends on n, or whose sup over n is not integrable.
- L'Hôpital without the existence of lim f'/g'; MVT for complex- or vector-valued functions.
- Principal Log inside a keyhole computation; forgetting signed zeros on numpy branch cuts.
- Missing half-residues at poles on the contour; arcs bounded by ML when only Jordan's lemma works
  (∫ e^(ix)/x).
- Summing a divergent asymptotic series to all orders; exponentiating ~; O-constants depending on a
  hidden parameter.
- Plain quadrature on oscillatory infinite ranges, one precision only, and numerical agreement
  reported as proof.

Related: `inequality-proving`, `probability-distributions-limits`, `ode-pde-analytic-methods`,
`numerical-error-analysis`, `sympy-symbolic-verification`, `proof-techniques-and-writing`,
`lean4-mathlib-formalization`, hub `mathematics-toolkit`.
