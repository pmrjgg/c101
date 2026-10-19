---
name: statistical-inference-bayesian
description: "Applied statistical inference for engineering and research data: estimands and design, estimators and standard errors, intervals (Wilson, Clopper-Pearson, bootstrap BCa), choosing a test, power and sample size, multiple comparisons, A/B tests and sequential monitoring, benchmark comparisons, regression with robust and clustered errors, and the Bayesian workflow with PyMC/NumPyro/Stan and ArviZ diagnostics. Load when data must support a claim or an experiment must be designed."
when_to_use: "A/B test or experiment readout, 'is this difference significant', p-values, confidence or credible intervals, sample size or power, comparing benchmark timings or model scores, many metrics or tests at once, regression tables and standard errors, PyMC/NumPyro/CmdStanPy/ArviZ models, divergences or r_hat warnings, sample ratio mismatch, reviewing the statistics of a paper, report or dashboard."
---

# Statistical inference and the Bayesian workflow

Checked October 2026 with SciPy 1.18, statsmodels 0.15, PyMC 6.3, ArviZ 1.3, NumPyro 0.22,
CmdStanPy 1.3. Fix the estimand, the analysis and the decision rule before looking at outcomes;
everything after that is arithmetic. Probability facts (distributions, CLT, tail bounds) live in
`probability-distributions-limits`.

Deep material: [Bayesian workflow templates](references/bayesian-workflow.md) |
A/B testing and sequential monitoring

## 1. Estimand and design first

- **Estimand**: which quantity (difference or ratio of means or rates, median shift, coefficient), in
  which population, absolute or relative.
- **Unit of randomisation = unit of analysis.** Users randomised but requests analysed ⇒ correlated
  rows and standard errors that are too small: aggregate per user or use cluster-robust errors.
- **Independence**: repeated measures, time series, shared machines and caches break it.
- **Paired or unpaired**: the same units measured under both conditions call for paired methods
  (much more power when the pairs correlate).
- **Fixed horizon or sequential**: decided in advance; looking repeatedly needs sequential methods.
- **Primary metric, guardrails, α, power, n and the decision rule** written down before launch.

| Question | Method | Call |
|---|---|---|
| two independent means | Welch t | `scipy.stats.ttest_ind(a, b, equal_var=False)` (default is Student's) |
| paired means | paired t; signed-rank | `ttest_rel(a, b)`; `wilcoxon(a, b)` |
| skewed or ordinal, two groups | Mann-Whitney U; Brunner-Munzel (unequal spreads) | `mannwhitneyu(a, b)`; `brunnermunzel(a, b)` |
| one proportion | Wilson or Clopper-Pearson interval | `statsmodels.stats.proportion.proportion_confint(x, n, method="wilson")` / `"beta"` |
| two proportions | score test, Newcombe interval; Fisher for small counts | `proportions_ztest`, `confint_proportions_2indep(..., method="newcomb")`, `fisher_exact` |
| r×c association | chi-square (expected counts ≥ 5), else exact or permutation | `chi2_contingency(t)`; `fisher_exact(t)` (r×c accepted in 1.18) |
| k groups | Welch ANOVA; Kruskal-Wallis | `statsmodels.stats.oneway.anova_oneway(data, groups, use_var="unequal")`; `kruskal(*groups)` |
| any statistic | permutation test | `permutation_test((a, b), stat, permutation_type="independent")` |
| interval for any statistic | bootstrap (BCa) | `bootstrap((x,), stat, method="BCa", rng=rng)` |
| equivalence | TOST with a pre-set margin | `statsmodels.stats.weightstats.ttost_ind(x1, x2, low, upp, usevar="unequal")` |
| outcome on covariates | OLS / GLM with robust errors | `smf.ols(...).fit(cov_type="HC3")`, `smf.logit`, `smf.glm` |
| observed vs expected counts (SRM) | chi-square goodness of fit | `chisquare(obs, f_exp)` |

## 2. Estimators and standard errors

- MSE = bias² + variance; consistency = convergence to the estimand; prefer low MSE over unbiasedness
  when they conflict (shrinkage).
- MLE: √n(θ̂ - θ) →d N(0, I(θ)⁻¹) when the model is identifiable, θ is interior, the support does not
  depend on θ and the log-likelihood is smooth. Standard errors from the inverse observed information
  (statsmodels `res.bse`, `res.cov_params()`). `scipy.stats.<dist>.fit(x)` returns the MLE only.
- Fisher information per observation: Bernoulli 1/(p(1-p)), Poisson 1/λ, normal mean 1/σ².
  Cramér-Rao: Var(T) ≥ 1/(nI(θ)) for unbiased T under the same regularity (X̄ attains it for the
  Poisson mean). Irregular cases break the n^(-1/2) rate: Uniform(0, θ) has MLE max X_i with error
  O(1/n); parameters on a boundary (variance component 0) give mixture-χ² likelihood-ratio tests.
- Delta method: Var g(θ̂) ≈ ∇gᵀ Cov(θ̂) ∇g. Relative lift r = p_B/p_A - 1 with independent arms:
  Var r̂ ≈ Var(p̂_B)/p_A² + p_B² Var(p̂_A)/p_A⁴ (worked example: SE 0.149).
- Bootstrap SE: `scipy.stats.bootstrap(...).standard_error` when no formula is available.

## 3. Intervals

| Situation | Use | Avoid |
|---|---|---|
| proportion, any n | Wilson (good coverage), Clopper-Pearson (exact, conservative), Jeffreys | Wald p̂ ± z√(p̂(1-p̂)/n) at small n or p near 0/1: at x = 0, n = 50 it is (0, 0) |
| zero events in n | Clopper-Pearson or Wilson upper bound; rule of three 3/n (95%) | — |
| difference of proportions | Newcombe hybrid score (`confint_proportions_2indep`) | Wald difference at small counts |
| mean, moderate skew, n ≳ 30 | t interval; Welch-Satterthwaite df for differences | z interval with estimated σ at small n |
| skewed positive data, multiplicative effects | log scale: ratio of geometric means | arithmetic t on raw skewed data at small n |
| any statistic, i.i.d. data | `scipy.stats.bootstrap` BCa (default method), ≥ 9999 resamples | percentile bootstrap at small n |

Zero events, n = 50: Wald (0, 0), Wilson (0, 0.071), Clopper-Pearson (0, 0.071), rule of three 0.06.
Wilson: (p̂ + z²/(2n) ± z√(p̂(1-p̂)/n + z²/(4n²)))/(1 + z²/n). Clopper-Pearson:
[Beta⁻¹(α/2; x, n-x+1), Beta⁻¹(1-α/2; x+1, n-x)]. `proportion_confint` methods: `"normal"` (Wald),
`"wilson"`, `"beta"` (Clopper-Pearson), `"agresti_coull"`, `"jeffreys"`, `"binom_test"`.

Where the bootstrap fails, and the fix:

| Failure | Fix |
|---|---|
| heavy tails (infinite variance): the mean's bootstrap is inconsistent | robust statistic (median, trimmed mean) or a parametric tail model |
| extremes (max, min, high quantiles at small n) | order-statistic or extreme-value methods |
| very small n (< 20) | exact or permutation methods; report the bootstrap as rough |
| dependent data (time series) | block bootstrap: `arch.bootstrap.StationaryBootstrap`, `MovingBlockBootstrap`, `CircularBlockBootstrap`; block length from `arch.bootstrap.optimal_block_length` or start near n^(1/3) and vary it |
| clustered data | resample whole clusters |
| parameter on a boundary | parametric bootstrap or likelihood methods |

## 4. Choosing and reading a test

- Welch by default: Student's pooled t is wrong when variances and group sizes differ, and Welch
  loses almost nothing when they are equal.
- Mann-Whitney tests P(X > Y) = 1/2 under exchangeability, not equality of medians; with different
  spreads or shapes it can reject with equal medians. Brunner-Munzel tests
  P(X > Y) + ½P(X = Y) = ½ without equal spreads. Report U/(n₁n₂) as the common-language effect size.
- Chi-square needs expected counts ≥ 5; otherwise Fisher exact or `permutation_test`. For paired
  binary outcomes use McNemar (`statsmodels.stats.contingency_tables.mcnemar`).
- `permutation_test` types: `"independent"` (two samples), `"samples"` (paired), `"pairings"`
  (correlation); exact when the number of permutations is small, Monte Carlo otherwise.
- Assumptions: plot first (histograms, QQ, residuals); do not gate on normality tests, which reject
  trivial deviations at large n and miss real ones at small n. Independence comes from the design.
- Effect sizes next to every p-value: difference with CI in natural units; Cohen's d or Hedges' g;
  risk difference, risk ratio, odds ratio; Cohen's h = 2 arcsin√p₁ - 2 arcsin√p₂
  (`proportion_effectsize`).

## 5. Power and sample size

- Lehr's rule: n ≈ 16σ²/δ² per arm for 80% power at two-sided α = 0.05 (2(1.96 + 0.84)² = 15.7); use
  21 for 90% power. Proportions: σ² = p̄(1 - p̄).
- Minimum detectable effect at given n: MDE ≈ 2.8·√(2σ²/n) (80%, α = 0.05); n = 2400 per arm at
  p ≈ 0.05: MDE ≈ 0.0176 absolute (35% relative).

```python
from statsmodels.stats.power import TTestIndPower, NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize
TTestIndPower().solve_power(effect_size=0.5, alpha=0.05, power=0.8, ratio=1.0)   # 63.8 per group (Lehr 64)
h = proportion_effectsize(0.0625, 0.05)                                          # Cohen's h 0.0543
NormalIndPower().solve_power(effect_size=h, alpha=0.05, power=0.8, ratio=1.0)    # 5317 per arm
NormalIndPower().power(effect_size=h, nobs1=2400, alpha=0.05, ratio=1.0)         # 0.469
```

- Simulation-based power for anything non-standard (clusters, ratio metrics, sequential rules, mixed
  models): simulate data under the assumed effect, run the exact planned analysis, power = rejection
  fraction over 1000-5000 replicates with its binomial CI; simulate under the null too and confirm
  the type I error.

## 6. Multiple comparisons

| Goal | Procedure | Call |
|---|---|---|
| family-wise error ≤ α, any dependence | Bonferroni α/m; Holm step-down (reject while p_(i) ≤ α/(m - i + 1)), never worse | `multipletests(p, alpha, method="holm")` |
| false discovery rate ≤ q, independent or positively dependent tests | Benjamini-Hochberg: largest k with p_(k) ≤ kq/m, reject 1..k | `scipy.stats.false_discovery_control(p, method="bh")` (adjusted p-values), `method="fdr_bh"` |
| FDR, arbitrary dependence | Benjamini-Yekutieli (q divided by Σ 1/i) | `false_discovery_control(p, method="by")` |

p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]: Bonferroni and Holm reject 1 test,
BH rejects 2 (adjusted 0.008, 0.032, then 0.067 for the next three). Pre-register one primary
metric; label the rest exploratory. Garden of forking paths: data-dependent exclusions, metric
definitions, transformations and subgroups inflate false positives with no explicit second test;
freeze the plan, report every analysis run, confirm on fresh data.

## 7. A/B testing pitfalls

| Pitfall | Measured or rule | Remedy |
|---|---|---|
| peeking at a fixed-horizon test | type I error at nominal 0.05 with K equally spaced looks: 0.085 (K = 2), 0.14 (5), 0.19 (10), 0.26 (20); 20 000 simulated null experiments | group-sequential boundaries (K = 5: Pocock 2.42 at every look; O'Brien-Fleming 2.04·√(K/k)) or an always-valid mSPRT (type I 0.036 under continuous monitoring, simulated) |
| sample-ratio mismatch | `chisquare([n_A, n_B], f_exp=expected)`; alarm at p < 0.001 | stop and debug assignment or logging; never reweight it away |
| high variance metric | CUPED: Y' = Y - θ(X - X̄), θ = Cov(Y, X)/Var(X) from a pre-period covariate, pooled over arms | variance × (1 - ρ²) |
| novelty or primacy | effect by exposure day or cohort drifts | run whole weekly cycles; analyse steady state |
| ratio metrics (clicks per session with users randomised) | rows within a user are correlated | delta-method variance of Ȳ/X̄ or per-user aggregation |
| interference, shared budgets, network effects | units affect each other | cluster or switchback randomisation |

Formulas, boundary code and mSPRT code: A/B testing reference.

## 8. Comparing performance benchmarks

This is the statistics half; how to measure (profilers, warm-up mechanics, environment control) is in
`performance-optimization`.

1. Runs are the unit: ≥ 10-30 independent process runs per variant, interleaved (ABAB...) to spread
   drift, after warm-up, on a quiet machine with fixed frequency.
2. Summarise with the median per variant and a BCa bootstrap CI of the median ratio.
3. Test with Mann-Whitney or Brunner-Munzel on run-level values; estimate the shift with
   Hodges-Lehmann (median of all pairwise differences).
4. Establish the noise floor from A/A comparisons (the same build split into halves); differences
   inside the A/A spread are not findings.

```python
import numpy as np
from scipy import stats as st
rng = np.random.default_rng(42)
a = 100 * rng.lognormal(0, 0.05, 30) + rng.exponential(2, 30)   # baseline timings (ms)
b = 97 * rng.lognormal(0, 0.05, 30) + rng.exponential(2, 30)    # candidate
ratio = lambda x, y, axis=-1: np.median(y, axis=axis) / np.median(x, axis=axis)
ci = st.bootstrap((a, b), ratio, n_resamples=9999, method="BCa", rng=rng, vectorized=True).confidence_interval
hl = np.median(np.subtract.outer(b, a))                          # Hodges-Lehmann shift
aa = [np.median(p[:15]) / np.median(p[15:]) - 1 for p in (rng.permutation(a) for _ in range(2000))]
print(ratio(a, b), ci, st.mannwhitneyu(a, b).pvalue, st.brunnermunzel(a, b).pvalue, hl,
      np.quantile(np.abs(aa), 0.95))
```

Measured: median ratio 0.955, 95% BCa CI (0.932, 0.986), Mann-Whitney p = 1.1e-3, Brunner-Munzel
p = 4.0e-4, Hodges-Lehmann shift -3.5 ms, A/A 95th percentile 3.1%. Report "4.5% faster
(95% CI 1.4% to 6.8%), above the 3.1% A/A floor, 30 runs per variant".

## 9. Regression

- OLS needs: linearity in parameters, exogeneity E[ε | X] = 0 (no omitted confounder), no perfect
  collinearity; homoskedastic independent errors only for the classical standard errors; normal
  errors only for exact small-sample inference.

```python
import statsmodels.formula.api as smf, statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.diagnostic import het_breuschpagan, het_white
m = smf.ols("y ~ x1 + x2 + C(region)", data=df)
r_hc3 = m.fit(cov_type="HC3")                                          # heteroskedasticity-robust
r_cl = m.fit(cov_type="cluster", cov_kwds={"groups": df["user_id"]})   # clustered by user
X = sm.add_constant(df[["x1", "x2"]]); vif = [variance_inflation_factor(X.values, i) for i in range(1, X.shape[1])]
r0 = m.fit(); bp_p = het_breuschpagan(r0.resid, r0.model.exog)[1]; white_p = het_white(r0.resid, r0.model.exog)[1]
```

- HC3 in small samples (HC0/HC1 are fine at large n). Clustered errors when rows share a unit; with
  few clusters (rule of thumb under 30-50) they are biased low: use a wild cluster bootstrap.
  Simulated 2000 rows in 50 clusters (5 seeds): intercept SE 0.046-0.049 classical vs 0.139-0.155
  clustered, a 3× understatement of uncertainty when the clustering is ignored.
- VIF_j = 1/(1 - R_j²) with the constant in the design; above 5-10 the coefficient is poorly
  determined (x2 = 0.9·x1 + noise gave VIF 83), not biased. Drop or combine, use ridge, or ignore
  it if only predictions matter.
- Diagnostics: residuals against fitted values, QQ plot, `res.get_influence().cooks_distance`.
  Breusch-Pagan only detects variance linear in the regressors: with noise sd 1 + |x1| it gave
  p = 0.009 to 0.26 over 5 seeds, while White's test (`het_white`) gave p < 1e-37 every time. When
  in doubt, skip the test and use HC3 errors anyway.
- Causation: coefficients are conditional associations. A causal reading needs randomisation or an
  explicit causal graph; adjust for confounders, never for mediators, colliders or post-treatment
  variables. GLMs: `smf.logit`, `smf.poisson`, `smf.glm(..., family=sm.families.NegativeBinomial())`;
  report marginal effects (`res.get_margeff()`).

## 10. Bayesian workflow

Conjugate quick answers (no sampler needed):

| Data | Prior | Posterior |
|---|---|---|
| x successes of n | Beta(α, β) | Beta(α + x, β + n - x) |
| Poisson counts x_1..x_n | Gamma(α, rate β) | Gamma(α + Σx_i, rate β + n) |
| Normal, σ known, x̄ of n | Normal(μ₀, τ₀²) | precision 1/τ₀² + n/σ²; mean (μ₀/τ₀² + n x̄/σ²)/(1/τ₀² + n/σ²) |

Otherwise PyMC (6.x returns an xarray `DataTree`; PyMC 5 returned `arviz.InferenceData`; the model
code is the same), NumPyro (JAX) or CmdStanPy (Stan); templates in
[Bayesian workflow](references/bayesian-workflow.md).

1. Weakly informative priors on interpretable scales; prior predictive check:
   `idata = pm.sample_prior_predictive(draws=500, random_seed=s)`,
   `az.plot_ppc_dist(idata, group="prior_predictive")`: simulated data must look possible.
2. Fit: `idata.update(pm.sample(1000, tune=1000, chains=4, random_seed=s))`; raise
   `target_accept=0.95` or reparametrise (non-centred hierarchies) when divergences appear.
3. Diagnostics, all required: R-hat ≤ 1.01, bulk and tail ESS ≥ 400 (100 per chain with 4 chains),
   zero divergences, no tree-depth saturation, E-BFMI > 0.3:
   `az.summary(idata, kind="diagnostics")`, `az.diagnose(idata)` (checks all five),
   `int(idata.sample_stats["diverging"].sum())`.
4. Posterior predictive check: `pm.sample_posterior_predictive(idata, extend_inferencedata=True)`,
   `az.plot_ppc_dist(idata)`; LOO-PIT `az.loo_pit`.
5. Prior sensitivity: `pm.stats.compute_log_prior(idata)`, `pm.stats.compute_log_likelihood(idata)`,
   then `az.psense_summary(idata)` (power-scaling; flags prior-data conflict). Flat priors have
   nothing to scale (Beta(1, 1) raised "All tail values are the same"): refit with alternatives.
6. Compare models: `az.loo(idata)`, `az.compare({"a": ia, "b": ib})` (stacking weights); Pareto k
   above 0.7 means the LOO estimate is unreliable for those points.
7. New model or new code: simulation-based calibration; ranks of prior draws among posterior draws
   must be uniform (loop in the reference).

ArviZ 1.x defaults: `az.summary` reports an 89% equal-tailed interval (`eti89_lb`, `eti89_ub`); pass
`ci_prob=0.95, ci_kind="hdi"` for 95% HDI. `pm.compute_log_prior` at the package root is
deprecated in favour of `pm.stats.compute_log_prior`.

## 11. Reporting

- Effect size with an interval in natural units, the exact test and its assumptions, exact p-value,
  sample sizes, exclusions, the number of comparisons and the correction, pre-registered or not.
- Bayesian: priors, posterior median or mean with 95% interval, P(effect > 0) and P(effect > MDE),
  diagnostics passed, predictive checks. Bayes factors only with a prior-sensitivity analysis: they
  scale with the prior width (Lindley's paradox).
- Never "p > 0.05, so no effect": give the CI; claiming equivalence needs TOST with a margin fixed in
  advance.
- Baseline-balance p-values in a randomised experiment test the randomiser, not the treatment; only
  the SRM check is informative.

## 12. Pitfalls

- Student's t with unequal variances; Wald intervals for rare events; analysing requests when users
  were randomised.
- Reading overlapping per-arm CIs as "no difference": the CI of the difference decides.
- Peeking, optional stopping, and switching metrics after seeing data.
- Bootstrap on dependent, heavy-tailed or extreme-value statistics (section 3).
- Unchecked sampler output: one divergence or R-hat 1.05 invalidates the posterior summary.
- Post-hoc power computed from the observed effect (it is a function of the p-value; use the
  pre-specified MDE instead).

## 13. Worked example: conversions 120/2400 vs 150/2400

```python
import numpy as np
from scipy import stats as st, integrate
from statsmodels.stats.proportion import proportion_confint, proportions_ztest, confint_proportions_2indep
ci_a = proportion_confint(120, 2400, method="wilson"); ci_b = proportion_confint(150, 2400, method="wilson")
z, p = proportions_ztest([150, 120], [2400, 2400])                       # pooled two-proportion z
diff_ci = confint_proportions_2indep(150, 2400, 120, 2400, method="newcomb")
post_a, post_b = st.beta(1 + 120, 1 + 2280), st.beta(1 + 150, 1 + 2250)  # Beta(1, 1) priors
p_b_gt_a = integrate.quad(lambda x: post_b.pdf(x) * post_a.cdf(x), 0, 0.2, points=[0.05, 0.0625], limit=200)[0]
rng = np.random.default_rng(1); da, db = post_a.rvs(10**6, random_state=rng), post_b.rvs(10**6, random_state=rng)
loss_b = np.maximum(da - db, 0).mean()                                   # expected loss of shipping B
```

| Quantity | Value |
|---|---|
| rates, Wilson 95% | A 5.00% (4.20%, 5.95%); B 6.25% (5.35%, 7.29%) |
| difference, Newcombe 95% | +1.25 pp (-0.06 pp, +2.56 pp) |
| two-proportion z test | z = 1.879, p = 0.060 |
| relative lift | +25%, delta-method SE 0.149 (posterior sd 0.15) |
| P(p_B > p_A), Beta(1, 1) priors | 0.970 (quadrature 0.96977; 10⁶ draws 0.9699; NUTS 4×1000 draws 0.966) |
| 95% credible interval of the difference | (-0.05 pp, +2.56 pp) |
| expected loss: ship B / keep A | 0.008 pp / 1.26 pp |
| power of this design for 5% → 6.25% | 0.47; 80% power needs 5317 per arm (Lehr 5436) |

Reading. The frequentist test at the pre-registered α = 0.05 is not significant: the result is
inconclusive, not "no effect", and the design was underpowered (47%). With flat priors and large n,
P(B > A) ≈ 1 - p/2 = 0.970: both analyses see the same evidence; they answer different questions.
Which rule applies is whatever was registered before launch. Claiming an effect (a report, a paper,
a guardrail) uses the frequentist rule: do not ship on this data alone, extend to the planned n.
A cheap, reversible product decision with an explicit loss may use the Bayesian rule (ship when
P(B > A) > 0.95 and the expected loss of shipping is below a tolerance, here 0.008 pp): ship B, keep
monitoring. Report both numbers, the rule used, and the power.

Related: `probability-distributions-limits`, `performance-optimization`, `bayesian-aggregation`,
`julia-craft`, `inequality-proving`, hub `mathematics-toolkit`.
