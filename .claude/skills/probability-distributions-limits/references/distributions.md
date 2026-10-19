# Distribution formulas and library conventions

Means and variances in this file were rechecked numerically against `scipy.stats` 1.18 (October
2026). `scipy.stats` standard form: X = loc + scale·Z, pdf(x) = pdf_Z((x - loc)/scale)/scale.

## 1. Discrete

| Distribution | pmf | PGF E[sˣ] | `scipy.stats` | NumPy `Generator` |
|---|---|---|---|---|
| Bernoulli(p) | pˣ(1-p)^{1-x} | 1 - p + ps | `bernoulli(p)` | `rng.binomial(1, p)` |
| Binomial(n, p) | C(n,x) pˣ(1-p)^{n-x} | (1 - p + ps)ⁿ | `binom(n, p)` | `rng.binomial(n, p)` |
| Poisson(λ) | e^{-λ} λˣ/x! | e^{λ(s-1)} | `poisson(mu)` | `rng.poisson(lam)` |
| Geometric(p), trials | (1-p)^{x-1} p, x ≥ 1 | ps/(1 - (1-p)s) | `geom(p)` | `rng.geometric(p)` (trials) |
| Negative binomial(r, p), failures | C(x+r-1, x) p^r (1-p)ˣ | (p/(1 - (1-p)s))^r | `nbinom(r, p)` | `rng.negative_binomial(r, p)` (failures) |
| Hypergeometric(N, K, n) | C(K,x) C(N-K, n-x)/C(N,n) | ₂F₁ form | `hypergeom(M=N, n=K, N=n)` | `rng.hypergeometric(ngood=K, nbad=N-K, nsample=n)` |
| Beta-binomial(n, α, β) | C(n,x) B(x+α, n-x+β)/B(α, β) | — | `betabinom(n, a, b)` | sample p then binomial |
| Multinomial(n, p) | n!/Πx_i! Π p_i^{x_i} | (Σ p_i s_i)ⁿ | `multinomial(n, p)` | `rng.multinomial(n, p)` |
| Discrete uniform {a..b} | 1/(b - a + 1) | — | `randint(a, b + 1)` (upper bound exclusive) | `rng.integers(a, b + 1)` |

Moments: Multinomial E X_i = np_i, Var X_i = np_i(1 - p_i), Cov(X_i, X_j) = -np_i p_j.
Beta-binomial variance nαβ(α + β + n)/((α + β)²(α + β + 1)).

## 2. Continuous

| Distribution | pdf | Mean | Variance | `scipy.stats` |
|---|---|---|---|---|
| Normal(μ, σ²) | exp(-(x-μ)²/(2σ²))/(σ√(2π)) | μ | σ² | `norm(loc=μ, scale=σ)` |
| Exponential(rate λ) | λe^{-λx}, x ≥ 0 | 1/λ | 1/λ² | `expon(scale=1/λ)` |
| Gamma(k, scale θ) | x^{k-1}e^{-x/θ}/(Γ(k)θ^k) | kθ | kθ² | `gamma(a=k, scale=θ)` |
| Inverse gamma(α, scale β) | β^α x^{-α-1} e^{-β/x}/Γ(α) | β/(α-1), α > 1 | β²/((α-1)²(α-2)), α > 2 | `invgamma(a=α, scale=β)` |
| Beta(α, β) | x^{α-1}(1-x)^{β-1}/B(α, β) | α/(α+β) | αβ/((α+β)²(α+β+1)) | `beta(a, b)` |
| Uniform(a, b) | 1/(b - a) | (a+b)/2 | (b-a)²/12 | `uniform(loc=a, scale=b-a)` |
| Chi-square(k) | x^{k/2-1}e^{-x/2}/(2^{k/2}Γ(k/2)) | k | 2k | `chi2(df=k)` |
| Student t(ν) | Γ((ν+1)/2)/(√(νπ)Γ(ν/2)) (1 + x²/ν)^{-(ν+1)/2} | 0, ν > 1 | ν/(ν-2), ν > 2 | `t(df=ν)` |
| F(d₁, d₂) | ratio of scaled χ² | d₂/(d₂-2), d₂ > 2 | 2d₂²(d₁+d₂-2)/(d₁(d₂-2)²(d₂-4)), d₂ > 4 | `f(dfn=d₁, dfd=d₂)` |
| Cauchy(x₀, γ) | 1/(πγ(1 + ((x-x₀)/γ)²)) | undefined | undefined | `cauchy(loc=x₀, scale=γ)` |
| Lognormal(μ, σ) | exp(-(ln x - μ)²/(2σ²))/(xσ√(2π)) | e^{μ+σ²/2} | (e^{σ²}-1)e^{2μ+σ²} | `lognorm(s=σ, scale=e^μ)` |
| Pareto I(α, x_m) | αx_m^α/x^{α+1}, x ≥ x_m | αx_m/(α-1) | x_m²α/((α-1)²(α-2)) | `pareto(b=α, scale=x_m)`; Lomax: `lomax(c=α)` |
| Weibull(k, λ) | (k/λ)(x/λ)^{k-1}e^{-(x/λ)^k} | λΓ(1 + 1/k) | λ²(Γ(1 + 2/k) - Γ(1 + 1/k)²) | `weibull_min(c=k, scale=λ)` |
| Laplace(μ, b) | e^{-\|x-μ\|/b}/(2b) | μ | 2b² | `laplace(loc=μ, scale=b)` |
| Logistic(μ, s) | e^{-(x-μ)/s}/(s(1 + e^{-(x-μ)/s})²) | μ | s²π²/3 | `logistic(loc=μ, scale=s)` |
| Gumbel (max) (μ, β) | (1/β)e^{-(z + e^{-z})}, z = (x-μ)/β | μ + βγ | π²β²/6 | `gumbel_r(loc=μ, scale=β)` |
| Rayleigh(σ) | (x/σ²)e^{-x²/(2σ²)} | σ√(π/2) | (4-π)σ²/2 | `rayleigh(scale=σ)` |
| Half-normal(σ) | √2/(σ√π) e^{-x²/(2σ²)}, x ≥ 0 | σ√(2/π) | σ²(1 - 2/π) | `halfnorm(scale=σ)` |
| Dirichlet(α) | Π x_i^{α_i - 1}/B(α) on the simplex | α_i/α₀ | α_i(α₀ - α_i)/(α₀²(α₀ + 1)) | `dirichlet(alpha)` |

γ ≈ 0.5772 is the Euler-Mascheroni constant; α₀ = Σα_i.

## 3. Characteristic functions (always exist)

| Distribution | φ(t) = E e^{itX} |
|---|---|
| Normal(μ, σ²) | exp(iμt - σ²t²/2) |
| Exponential(λ) | λ/(λ - it) |
| Gamma(k, θ) | (1 - iθt)^{-k} |
| Poisson(λ) | exp(λ(e^{it} - 1)) |
| Uniform(a, b) | (e^{itb} - e^{ita})/(it(b - a)) |
| Cauchy(x₀, γ) | exp(ix₀t - γ\|t\|) |
| Laplace(μ, b) | e^{iμt}/(1 + b²t²) |
| Symmetric α-stable (scale c) | exp(-\|ct\|^α), 0 < α ≤ 2 |

Use: sums of independent variables multiply CFs; φ_X(t) = 1 + iμt - (σ² + μ²)t²/2 + o(t²) when
E X² < ∞ (the CLT proof); Lévy continuity for convergence in distribution.

## 4. Conjugate pairs (details and workflow in `statistical-inference-bayesian`)

| Likelihood | Prior | Posterior after data |
|---|---|---|
| Binomial(n, p), x successes | Beta(α, β) | Beta(α + x, β + n - x) |
| Poisson(λ), counts x_1..x_n | Gamma(α, rate β) | Gamma(α + Σx_i, rate β + n) |
| Normal(μ, σ² known), x_1..x_n | Normal(μ₀, τ₀²) | precision 1/τ₀² + n/σ², mean (μ₀/τ₀² + n x̄/σ²)/(1/τ₀² + n/σ²) |
| Exponential(rate λ) | Gamma(α, rate β) | Gamma(α + n, rate β + Σx_i) |
| Multinomial counts | Dirichlet(α) | Dirichlet(α + counts) |
| Normal, σ² unknown (μ known) | Inverse gamma(α, β) on σ² | IG(α + n/2, β + Σ(x_i - μ)²/2) |

## 5. Sampling recipes

- Inverse CDF: X = F⁻¹(U), U ~ U(0, 1) (`dist.ppf(rng.random(n))`); exact for any 1-D law with a
  computable quantile function.
- Box-Muller: R = sqrt(-2 ln U₁), Θ = 2πU₂ give two independent N(0, 1) (Jacobian example).
- Multivariate normal: L = cholesky(Σ), X = μ + LZ; fails for singular Σ (use eigh or SVD).
- Use `scipy.stats.qmc` (Sobol, Halton, Latin hypercube) for low-discrepancy integration; scramble
  and use several replicates to get an error estimate.
