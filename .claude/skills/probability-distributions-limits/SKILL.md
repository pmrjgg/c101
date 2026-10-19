---
name: probability-distributions-limits
description: "Probability calculations and limit theorems: distribution facts, parametrisations and relationships, expectation via indicators and conditioning, transformations, modes of convergence, LLN/CLT/delta method with their conditions, choosing a concentration or tail bound, martingales and optional stopping, Markov chains, paradoxes, and seeded Monte Carlo checks. Load when deriving, bounding or checking any probability, expectation, distribution or limit."
when_to_use: "Expected value or variance of a count or waiting time, 'what is the distribution of', scipy.stats or numpy parametrisation confusion (scale vs rate, loc/scale, geom/nbinom/hypergeom conventions), validity of a normal approximation or CLT, choosing Chernoff vs Hoeffding vs Bernstein, randomized-algorithm analysis, martingale or stopping-time arguments, gambler's ruin, Markov chain stationary distributions, hitting times or mixing, probability puzzles and paradoxes, sizing a simulation."
---

# Probability: distributions, expectations, limits

Every probability answer states its probability space, independence assumptions and the theorem
used with its conditions checked. Derive exactly, then check by exact enumeration (small cases) or
a seeded simulation with a reported confidence interval (section 11). Statistical inference from
data lives in `statistical-inference-bayesian`.

Deep material: [distribution formulas and conventions](references/distributions.md) |
[Markov chain and martingale code](references/chains-martingales.md)

## 1. Distribution reference

| Distribution | Support | Mean | Variance | MGF M(t) / CF φ(t) | `scipy.stats` (trap) |
|---|---|---|---|---|---|
| Bernoulli(p) | {0, 1} | p | p(1-p) | 1 - p + peᵗ | `bernoulli(p)` |
| Binomial(n, p) | 0..n | np | np(1-p) | (1 - p + peᵗ)ⁿ | `binom(n, p)` |
| Poisson(λ) | 0, 1, ... | λ | λ | exp(λ(eᵗ - 1)) | `poisson(mu=λ)` |
| Geometric(p), trials to 1st success | 1, 2, ... | 1/p | (1-p)/p² | peᵗ/(1 - (1-p)eᵗ), t < -ln(1-p) | `geom(p)` counts trials; failures: `geom(p, loc=-1)` |
| Negative binomial(r, p), failures before r-th success | 0, 1, ... | r(1-p)/p | r(1-p)/p² | (p/(1 - (1-p)eᵗ))^r, t < -ln(1-p) | `nbinom(r, p)` counts failures |
| Hypergeometric: population N, K successes, n draws | max(0, n+K-N)..min(n, K) | nK/N | n(K/N)(1-K/N)(N-n)/(N-1) | no closed form (₂F₁) | `hypergeom(M=N, n=K, N=n)`: letters reshuffled |
| Uniform(a, b) | [a, b] | (a+b)/2 | (b-a)²/12 | (e^{tb} - e^{ta})/(t(b-a)) | `uniform(loc=a, scale=b-a)` (scale is the width) |
| Normal(μ, σ²) | ℝ | μ | σ² | exp(μt + σ²t²/2) | `norm(loc=μ, scale=σ)` (σ, not σ²) |
| Exponential, rate λ | [0, ∞) | 1/λ | 1/λ² | λ/(λ - t), t < λ | `expon(scale=1/λ)` (scale = 1/rate) |
| Gamma, shape k, scale θ (rate β = 1/θ) | (0, ∞) | kθ | kθ² | (1 - θt)^(-k), t < 1/θ | `gamma(a=k, scale=θ)`; rate β → `scale=1/β` |
| Beta(α, β) | [0, 1] | α/(α+β) | αβ/((α+β)²(α+β+1)) | ₁F₁(α; α+β; t) | `beta(a, b)` |
| Chi-square(k) = Gamma(k/2, scale 2) | (0, ∞) | k | 2k | (1 - 2t)^(-k/2), t < 1/2 | `chi2(df=k)` |
| Student t(ν) | ℝ | 0 (ν > 1) | ν/(ν-2) (ν > 2) | MGF does not exist; CF via Bessel K | `t(df=ν)` |
| Cauchy(x₀, γ) | ℝ | undefined | undefined | φ(t) = exp(i x₀ t - γ\|t\|) | `cauchy(loc=x₀, scale=γ)` |
| Lognormal(μ, σ) | (0, ∞) | e^{μ+σ²/2} | (e^{σ²} - 1)e^{2μ+σ²} | MGF infinite for t > 0; E Xᵏ = e^{kμ + k²σ²/2} | `lognorm(s=σ, scale=e^μ)` |
| Pareto I(α, x_m) | [x_m, ∞) | αx_m/(α-1), α > 1 | x_m²α/((α-1)²(α-2)), α > 2 | MGF infinite for t > 0 | `pareto(b=α, scale=x_m)` |
| Multivariate normal N(μ, Σ) | ℝ^d | μ | Σ | exp(μᵀt + tᵀΣt/2) | `multivariate_normal(mean=μ, cov=Σ)` |

All means and variances above were rechecked against `scipy.stats` 1.18 `.mean()` / `.var()`.
`scipy.stats` uses X = loc + scale·Z for its standard form Z, so "rate" parameters always enter as
`scale=1/rate`. NumPy `Generator` traps: `rng.exponential(scale=1/λ)`, `rng.gamma(shape, scale)`,
`rng.geometric(p)` counts trials (support from 1), `rng.pareto(a)` is Pareto II (Lomax) on [0, ∞):
Pareto I is `(rng.pareto(a) + 1) * x_m`; `rng.multivariate_normal(mean, cov, method="cholesky")`
(default `method="svd"`). Densities, extra families (F, Weibull, Laplace, Dirichlet, multinomial)
and conjugacy: [distributions](references/distributions.md).

## 2. Relationships

| Fact | Conditions / numbers |
|---|---|
| Σ of n i.i.d. Exp(rate λ) = Gamma(n, scale 1/λ) (Erlang) | KS test of 200 000 sums of 3 Exp(2.5) against `gamma(3, scale=0.4)`: p = 0.10 |
| Sums: Poisson + Poisson, Gamma + Gamma (same scale), Normal + Normal, Bernoullis → Binomial, r geometric(failures) → NB(r, p) | independence |
| Bin(n, λ/n) → Poisson(λ); d_TV(Bin(n, p), Poi(np)) ≤ np² (Le Cam), ≤ (1 - e^{-np})p (Barbour-Hall) | n = 1000, p = 0.003: d_TV = 7.5e-4, bounds 9.0e-3 and 2.9e-3 |
| Normal approximation to Bin(n, p) | rule np ≥ 10 and n(1-p) ≥ 10; Bin(50, 0.04): P(X ≥ 6) exact 0.0144, normal (continuity-corrected) 0.0058, Poisson 0.0166; Bin(1000, 0.5): P(X ≥ 530) exact 0.03101, normal 0.03104 |
| Beta-binomial: p ~ Beta(α, β), X \| p ~ Bin(n, p) | mean nα/(α+β), variance nαβ(α+β+n)/((α+β)²(α+β+1)); `betabinom(n, a, b)` |
| Gamma-Poisson mixture: λ ~ Gamma(r, scale (1-p)/p), X \| λ ~ Poi(λ) ⇒ X ~ NB(r, p) | overdispersed counts |
| Z/sqrt(V/ν) ~ t_ν; (U/d₁)/(V/d₂) ~ F(d₁, d₂); Z² ~ χ²₁; ratio of independent N(0,1) ~ Cauchy | Z ~ N(0,1), U ~ χ²_{d₁}, V ~ χ²_ν independent |
| Memorylessness P(X > s + t \| X > s) = P(X > t) | only exponential (continuous) and geometric (discrete) |
| min of independent Exp(λ_i) ~ Exp(Σλ_i); P(min is X_i) = λ_i/Σλ_j | independence |
| U_(k), k-th order statistic of n uniforms, ~ Beta(k, n - k + 1) | i.i.d. U(0, 1) |
| Poisson process rate λ: N(t) ~ Poi(λt), gaps Exp(λ); given N(t) = n the points are i.i.d. uniform | homogeneous process |

## 3. Expectation toolkit

- Indicators: E[#events] = Σ P(A_i), no independence needed. Fixed points of a random permutation:
  n·(1/n) = 1. Distinct coupons seen in m draws from n: n(1 - (1 - 1/n)^m).
- Variance of a count: Var Σ I_i = Σ p_i(1 - p_i) + Σ_{i≠j} (P(A_i ∩ A_j) - p_i p_j); this needs the
  pairwise probabilities (second-moment method).
- Total expectation and variance: E X = E[E[X | Y]]; Var X = E[Var(X | Y)] + Var(E[X | Y]).
  Tower: E[E[X | G] | H] = E[X | H] for H ⊆ G.
- Symmetry: among n exchangeable continuous variables each is the maximum with probability 1/n;
  E[X_1 | X_1 + ... + X_n = s] = s/n.
- Tail sums: X ∈ {0, 1, ...}: E X = Σ_{k≥1} P(X ≥ k), E X² = Σ_{k≥1} (2k - 1)P(X ≥ k); X ≥ 0:
  E X = ∫_0^∞ P(X > t) dt.
- First-step analysis: condition on the first move, solve the linear equations. Fair-coin waiting
  time for HH is 6 and for HT is 4 (simulation agrees: 6.06, 3.99).

## 4. Transformations

- Change of variables: Y = g(X), g a C¹ bijection: f_Y(y) = f_X(g⁻¹(y)) |det Dg⁻¹(y)|; for
  non-injective g sum over preimages. X ~ N(0, 1), Y = X²: f_Y(y) = e^{-y/2}/sqrt(2πy) (χ²₁).
- Order statistics: f_(k)(x) = n!/((k-1)!(n-k)!) F(x)^{k-1}(1 - F(x))^{n-k} f(x); max has CDF Fⁿ,
  min has CDF 1 - (1 - F)ⁿ.
- Convolution: f_{X+Y}(z) = ∫ f_X(t) f_Y(z - t) dt for independent X, Y; discrete pmfs on a
  common grid: `np.convolve(p, q)`.
- Random sums S_N = X_1 + ... + X_N: Wald E S_N = E N · E X when N is a stopping time with E N < ∞
  and E|X| < ∞ (or N independent of the X_i); Var S_N = E N Var X + Var N (E X)² when N is
  independent of the i.i.d. X_i.
- Uniqueness: equal MGFs on an open interval around 0 ⇒ equal distributions. Equal moments do not
  suffice in general (the lognormal is not determined by its moments). The CF always exists; Lévy
  continuity: φ_n → φ pointwise with φ continuous at 0 ⇔ convergence in distribution.

## 5. Modes of convergence

```
a.s. ──────────────┐
                   ├──► in probability ──► in distribution
L^p (p ≥ 1) ───────┘         │
in probability ⇒ a.s. along a subsequence; in distribution to a constant ⇒ in probability;
L^p ⇒ L^q for p ≥ q ≥ 1; in probability + uniform integrability ⇔ L¹
```

| Counterexample | Shows |
|---|---|
| X_n independent Bernoulli(1/n) | → 0 in probability and in L^p, not a.s. (Σ 1/n = ∞, second Borel-Cantelli) |
| X_n = n·1_{(0, 1/n)} on ([0, 1], Lebesgue) | → 0 a.s., E X_n = 1: no L¹ convergence |
| X ~ N(0, 1), X_n = -X | → X in distribution, not in probability |
| typewriter indicators of dyadic intervals | → 0 in probability and L^p, a.s. at no point |

- Slutsky: X_n →d X and Y_n →p c ⇒ X_n + Y_n →d X + c, X_n Y_n →d cX, X_n/Y_n →d X/c (c ≠ 0).
- Continuous mapping: g continuous on a set of limit-probability 1 preserves a.s., in-probability
  and in-distribution convergence.
- Delta method: √n(T_n - θ) →d N(0, σ²), g differentiable at θ with g'(θ) ≠ 0 ⇒
  √n(g(T_n) - g(θ)) →d N(0, g'(θ)²σ²); vector form ∇gᵀΣ∇g; if g'(θ) = 0 use the second-order version
  (rate n, scaled χ² limit). Example: X̄ of Exp(λ) has σ² = 1/λ², g = log: Var(log X̄) ≈ 1/n.

## 6. LLN, CLT and when they fail

| Theorem | Conditions | Conclusion |
|---|---|---|
| Weak LLN | i.i.d. with E\|X\| < ∞ (or uncorrelated, bounded variances) | X̄ →p μ |
| Strong LLN (Kolmogorov; Etemadi) | i.i.d. (pairwise independent suffices, Etemadi) with E\|X\| < ∞ | X̄ → μ a.s. |
| CLT (Lindeberg-Lévy) | i.i.d., 0 < σ² < ∞ | √n(X̄ - μ)/σ →d N(0, 1) |
| CLT (Lindeberg-Feller) | independent, s_n² = Σσ_i², (1/s_n²)Σ E[(X_i - μ_i)² 1{\|X_i - μ_i\| > ε s_n}] → 0 ∀ε > 0 (Lyapunov's (2+δ)-moment condition implies it) | (S_n - E S_n)/s_n →d N(0, 1) |
| Berry-Esseen | i.i.d., ρ = E\|X - μ\|³ < ∞ | sup_x \|F_n(x) - Φ(x)\| ≤ Cρ/(σ³√n), C < 0.4748 (Shevtsova 2011) |

- Berry-Esseen in numbers, Exp(1) (ρ = 12/e - 2 ≈ 2.415): exact sup distance 0.042, 0.013, 0.0042
  at n = 10, 100, 1000 against bounds 0.36, 0.11, 0.036: the rate is right, the constant is ~9×
  pessimistic. Skewness, not n alone, decides when the normal approximation is usable.
- Heavy tails: the mean of n i.i.d. Cauchy is Cauchy for every n (no LLN; the IQR of simulated sample
  means stayed ≈ 2 at n = 10, 10³, 10⁵). Pareto α ≤ 1: infinite mean, no LLN. 1 < α < 2: LLN holds,
  variance infinite, no CLT; the generalised CLT gives an α-stable limit at scale n^{1/α}.
- Borel-Cantelli: Σ P(A_n) < ∞ ⇒ P(A_n i.o.) = 0 (no independence needed); Σ P(A_n) = ∞ and A_n
  independent (pairwise suffices) ⇒ P(A_n i.o.) = 1.

## 7. Tail-bound selection

| Bound | Statement | Hypotheses | Tightest when |
|---|---|---|---|
| Markov | P(X ≥ a) ≤ E X/a | X ≥ 0, a > 0 | only the mean is known; tight for a two-point law on {0, a} |
| Chebyshev | P(\|X - μ\| ≥ t) ≤ σ²/t² | finite variance | only the variance is known; heavy-ish tails |
| Cantelli | P(X - μ ≥ t) ≤ σ²/(σ² + t²) | finite variance | one-sided, t ≲ σ |
| Chernoff (generic) | P(X ≥ a) ≤ inf_{t>0} e^{-ta} M(t) | MGF finite near 0 | MGF known: optimise t (gives the KL form for sums) |
| Multiplicative Chernoff | P(S ≥ (1+δ)μ) ≤ exp(-δ²μ/(2+δ)); P(S ≤ (1-δ)μ) ≤ exp(-δ²μ/2) | S sum of independent [0,1] variables, μ = E S; δ > 0 (upper), 0 < δ < 1 (lower) | rare events, μ ≪ n |
| Hoeffding | P(S - E S ≥ t) ≤ exp(-2t²/Σ(b_i - a_i)²) | independent, X_i ∈ [a_i, b_i] | variance close to the range² /4 |
| Bernstein | P(S - E S ≥ t) ≤ exp(-(t²/2)/(Σ Var X_i + Mt/3)) | independent, \|X_i - E X_i\| ≤ M | variance much smaller than the range² |
| Azuma-Hoeffding | P(Z_n - Z_0 ≥ t) ≤ exp(-t²/(2Σc_i²)) | martingale, \|Z_i - Z_{i-1}\| ≤ c_i | dependent increments |
| McDiarmid | P(f - E f ≥ t) ≤ exp(-2t²/Σc_i²) | independent inputs, changing input i moves f by ≤ c_i | functions of many independent inputs |
| Union bound | P(∪A_i) ≤ Σ P(A_i) | none | few events or tiny probabilities |
| Paley-Zygmund | P(X > θ E X) ≥ (1 - θ)²(E X)²/E X² | X ≥ 0, θ ∈ [0, 1] | lower bounds |
| Second moment | P(X > 0) ≥ (E X)²/E X² | X ≥ 0 | existence, thresholds (random graphs) |

Same event, S ~ Bin(1000, 0.1), P(S ≥ 150), exact 4.5e-7: Markov 0.67, Chebyshev 0.036, Cantelli
0.035, Hoeffding 6.7e-3 (ignores the small variance), multiplicative Chernoff 4.5e-5, Bernstein
8.1e-6, optimised Chernoff exp(-n·KL(0.15 ‖ 0.1)) 4.9e-6. Rule: use the variance when it is small
relative to the range (Bernstein, KL-Chernoff); Hoeffding only when it is not.

## 8. Martingales and optional stopping

Building a martingale: partial sums of independent mean-zero steps; S_n² - nσ² for mean-zero
steps; the exponential martingale e^{θS_n}/M(θ)ⁿ; (q/p)^{S_n} for a ±1 walk with P(+1) = p; the Doob
martingale E[f(X_1..X_N) | X_1..X_n]; likelihood ratios under the null.

Optional stopping: E M_τ = E M_0 for a martingale M and stopping time τ if one of
(i) τ ≤ N almost surely; (ii) E τ < ∞ and |M_{n+1} - M_n| ≤ c; (iii) τ < ∞ a.s. and |M_{n∧τ}| ≤ K for
all n (more generally (M_{n∧τ}) uniformly integrable). Counterexample: simple symmetric walk from 0
stopped at the first visit to 1 has τ < ∞ a.s. but E τ = ∞ and M_τ = 1 ≠ 0 = E M_0.

Gambler's ruin, start k, absorb at 0 and N, steps +1 with probability p, q = 1 - p:

| Quantity | Fair (p = 1/2) | Biased (p ≠ 1/2) |
|---|---|---|
| martingale used | S_n (bounded, (iii)) | (q/p)^{S_n} (bounded, (iii)) |
| P(reach N first) | k/N | ((q/p)^k - 1)/((q/p)^N - 1) |
| martingale for duration | S_n² - n (E τ < ∞, (ii)) | S_n - n(p - q) ((ii)) |
| E τ | k(N - k) | k/(q - p) - (N/(q - p))·(1 - (q/p)^k)/(1 - (q/p)^N) |

Check, p = 0.45, N = 10, k = 5: P(win) = 0.268283 and E τ = 23.171740 from both the formulas and the
linear system (I - Q)h = 1 (code in [chains and martingales](references/chains-martingales.md));
fair game E τ = 25.

## 9. Markov chains (finite state space)

- Stationary distribution: solve πP = π, Σπ = 1 as a least-squares system
  `np.linalg.lstsq(np.vstack([P.T - np.eye(n), np.ones(n)]), np.r_[np.zeros(n), 1])`; unique and
  positive when the chain is irreducible; P^t(x, ·) → π when it is also aperiodic. Kac: E_i[return
  time] = 1/π_i.
- Reversibility: π_i P_ij = π_j P_ji (detailed balance) ⇒ π is stationary; birth-death chains are
  reversible; check numerically with `F = pi[:, None] * P; np.allclose(F, F.T)`.
- Absorption: order states transient then absorbing, P = [[Q, R], [0, I]]; expected steps
  t = (I - Q)⁻¹1 and absorption probabilities B = (I - Q)⁻¹R, computed with `np.linalg.solve`.
- Mixing: d(t) = max_x ‖P^t(x, ·) - π‖_TV, t_mix(ε) = min{t : d(t) ≤ ε} (ε = 1/4 by default).
  Coupling inequality ‖P^t(x, ·) - P^t(y, ·)‖_TV ≤ P(X_t ≠ Y_t). Reversible chains (Levin-Peres-
  Wilmer, ch. 12): with absolute spectral gap γ* = 1 - max(|λ_2|, |λ_n|) and t_rel = 1/γ*,
  (t_rel - 1) ln(1/(2ε)) ≤ t_mix(ε) ≤ ⌈t_rel ln(1/(ε π_min))⌉.
- Example P = [[0.9, 0.1, 0], [0.2, 0.7, 0.1], [0, 0.3, 0.7]]: π = (0.6, 0.3, 0.1), reversible,
  eigenvalues 1, 0.8, 0.5, t_rel = 5; bounds 2.8 ≤ t_mix(1/4) ≤ 19; exact t_mix(1/4) = 7.

## 10. Paradoxes and pitfalls

| Trap | Fact |
|---|---|
| uncorrelated ⇒ independent | false: X ~ U(-1, 1), Y = X² has Cov = 0; true only for jointly normal vectors (normal marginals are not enough) |
| Simpson's paradox | kidney stones: A wins in each stratum (81/87, 192/263) but loses pooled (273/350 vs 289/350); stratify on confounders, never on mediators or colliders |
| inspection (waiting-time) paradox | the gap covering a fixed time has mean E[X²]/E[X] ≥ E X; Poisson buses: 2/λ, not 1/λ |
| Bertrand's chord | "random chord" is undefined: 1/3, 1/2 or 1/4 depending on the sampling scheme; state the measure |
| conditioning on a probability-0 event | Borel-Kolmogorov: the answer depends on how the event is approached; condition on a random variable (σ-algebra), with the limiting procedure stated |
| base-rate neglect | sensitivity 0.99, specificity 0.99, prevalence 0.01 ⇒ P(disease \| +) = 0.5 |
| Monty Hall, two-child problems | answers depend on the host's or the reporter's protocol; write the protocol as a probability model first |
| infinite expectations | St Petersburg; Pareto α ≤ 1; sample means never settle |

## 11. Simulation check protocol

1. `rng = np.random.default_rng(seed)`, seed recorded; parallel workers get `rng.spawn(k)` streams;
   never the legacy global `np.random.seed`.
2. Choose N from the target 95% half-width w: N = (1.96 s/w)². For a probability, s² ≤ 1/4 gives
   N = 0.96/w² (w = 0.005 → N ≈ 38 400). For a rare event with relative half-width r:
   N ≈ 1.96²(1 - p)/(p r²) (p = 1e-4, r = 0.1 → 3.8 million).
3. Report estimate ± 1.96 s/√N with N and the seed. A simulated value outside the exact answer's
   interval more often than 1 time in 20 is a bug in the derivation or the code.
4. For small discrete cases enumerate exactly (`itertools.product`, `fractions.Fraction`) and compare
   with the formula before simulating large cases.
5. Vectorise (sample whole arrays); a Python loop of 10⁵ trials is the usual reason simulations are
   underpowered.

## 12. Worked example: coupon collector

T = draws until all n coupon types are seen. T = Σ_{i=0}^{n-1} G_i with independent
G_i ~ Geometric(p_i = (n - i)/n) (trials).

- E T = Σ n/(n - i) = n H_n. Var T = Σ (1 - p_i)/p_i² = n² Σ_{k=1}^n 1/k² - n H_n ≤ π²n²/6.
- Tail: P(T > m) = P(some type missing after m draws) ≤ n(1 - 1/n)^m ≤ n e^{-m/n}; with
  m ≥ n ln n + cn this is ≤ e^{-c} (union bound). The Erdős-Rényi limit is
  P(T > n ln n + cn) → 1 - exp(-e^{-c}).

```python
import math, numpy as np
from fractions import Fraction
n = 50
H = sum(Fraction(1, k) for k in range(1, n + 1)); H2 = sum(Fraction(1, k * k) for k in range(1, n + 1))
print(float(n * H), float(n * n * H2 - n * H), math.pi**2 * n * n / 6)   # 224.9603 3837.87 4112.34
rng, N = np.random.default_rng(20261019), 100_000
T = rng.geometric((n - np.arange(n)) / n, size=(N, n)).sum(axis=1)       # vectorised: sum of geometrics
print(T.mean(), 1.96 * T.std(ddof=1) / math.sqrt(N), T.std(ddof=1))      # 224.95 0.38 61.91
for c in (0.5, 1, 2, 3):
    emp = (T > n * math.log(n) + c * n).mean()
    print(c, emp, math.exp(-c), 1 - math.exp(-math.exp(-c)))
```

| c | threshold n ln n + cn | simulated P(T > threshold) ± 95% | union bound e^{-c} | limit 1 - exp(-e^{-c}) |
|---|---|---|---|---|
| 0.5 | 220.6 | 0.4545 ± 0.0031 | 0.6065 | 0.4548 |
| 1 | 245.6 | 0.3042 ± 0.0029 | 0.3679 | 0.3078 |
| 2 | 295.6 | 0.1214 ± 0.0020 | 0.1353 | 0.1266 |
| 3 | 345.6 | 0.0457 ± 0.0013 | 0.0498 | 0.0486 |

Exact E T = 224.9603 lies inside the simulated 224.95 ± 0.38; the simulated sd 61.91 matches
sqrt(3837.87) = 61.95; every tail estimate sits below e^{-c}, as the union bound requires, and close
to the Gumbel limit already at n = 50. A direct loop simulation (2000 runs) gave mean 223.6, also
consistent. Status: E T, Var T and the tail bound Proved; simulation Numerical evidence (seed
20261019, N = 10⁵).

Related: `statistical-inference-bayesian`, `inequality-proving`, `combinatorics-generating-functions`,
`graph-theory-probabilistic-method`, `real-complex-analysis`, `quantum-computing`, hub `mathematics-toolkit`.
