---
name: uncertainty-propagation-fitting
description: "Measurement uncertainty and model fitting for physics data: GUM Type A/B budgets, linear and correlated propagation with the uncertainties package, Monte Carlo propagation (JCGM 101), weighted least squares with chi-square diagnostics, ODR for x-errors, Poisson likelihoods, bootstrap, and reporting conventions. Load when a result needs an error bar or a model must be fit to data."
when_to_use: "Attaching an error bar to a measured or derived value; building a GUM budget; calling curve_fit, lmfit, iminuit, emcee, scipy.odr or odrpack; reduced chi-square far from 1; counts below ~20 per bin; errors on both x and y; a scipy.odr DeprecationWarning; choosing significant figures or a stat/sys split for a reported result."
---

# Uncertainty propagation and fitting

Error bars fail in five repeatable ways: the wrong σ (a range, a full width, a double-counted
systematic), dropped correlations, a fit statistic that does not match the noise (χ² on small
counts, ignored x-errors), a covariance silently rescaled by χ²_ν, and over-precise reporting.
APIs below were run in October 2026 with uncertainties 3.2, pint 0.26, SciPy 1.18, lmfit 1.3,
iminuit 2.33, emcee 3.1, odrpack 0.6, arch 8.0 and JAX 0.12.

Deep material: [fitting recipes with outputs](references/fitting-recipes.md) |
[GUM budget tables and the JCGM 101 adaptive loop](references/gum-budget-tables.md)

## 1. Budget procedure (GUM, JCGM 100)

1. Write the measurement model y = f(x₁…x_N). Corrections (zero offset, calibration factor,
   temperature coefficient, cosine error) are explicit inputs with estimate 0 or 1 and their own u.
2. **Type A** (statistics of repeats): mean x̄, sample sd s, u = s/√n, ν = n − 1.
3. **Type B** (everything else): convert the stated information with the table below.
4. Sensitivity coefficients c_i = ∂f/∂x_i at the estimates (analytic, autodiff, or evaluate f at
   x_i ± u_i).
5. u_c² = Σ c_i² u_i² + 2 Σ_{i<j} c_i c_j u(x_i, x_j) (section 2).
6. ν_eff = u_c⁴ / Σ (c_i u_i)⁴/ν_i (Welch-Satterthwaite, GUM G.4.1); truncate to an integer.
7. U = k·u_c with k = t_p(ν_eff). k = 2 means ≈ 95 % only when ν_eff is large (≳ 30) and the
   output is near Gaussian; otherwise use the k table or Monte Carlo (section 4).

| Information you have | Distribution | Standard uncertainty |
|---|---|---|
| Bounds ±a and nothing else (spec sheet, tolerance, handbook range) | rectangular | a/√3 |
| Bounds ±a, values near the centre more likely | triangular | a/√6 |
| Quantity cycling sinusoidally between ±a (room temperature, phase) | arcsine (U-shaped) | a/√2 |
| Digital resolution δ (one count of the last digit) | rectangular, half-width δ/2 | δ/√12 |
| Certificate "U, k = 2" | normal | U/2 |
| "± a at 95 %" with no k stated | normal | a/1.96 |
| Asymmetric bounds x − b₋ to x + b₊ | rectangular of full width b₋ + b₊ | (b₊ + b₋)/√12 (GUM 4.3.8) |

Type B degrees of freedom (GUM G.4.2): ν ≈ ½ (Δu/u)⁻², so "u reliable to 10 %" gives ν = 50,
25 % gives 8, 50 % gives 2. Bounds treated as exactly known give ν = ∞ (the usual case, GUM G.6.4).

Coverage factor k = t_p(ν_eff) (`scipy.stats.t.ppf`, matches GUM Table G.2):

| ν_eff | 2 | 3 | 4 | 5 | 6 | 8 | 10 | 20 | 50 | ∞ |
|---|---|---|---|---|---|---|---|---|---|---|
| p = 95.45 % | 4.53 | 3.31 | 2.87 | 2.65 | 2.52 | 2.37 | 2.28 | 2.13 | 2.05 | 2.00 |
| p = 95 % | 4.30 | 3.18 | 2.78 | 2.57 | 2.45 | 2.31 | 2.23 | 2.09 | 2.01 | 1.96 |

Triage: u_c is set by the one or two largest |c_i|·u_i. A line one third of the largest adds about
5 % to u_c, so spend effort on the top line. A filled seven-line budget (ν_eff = 13 → k = 2.21) is
in [GUM budget tables](references/gum-budget-tables.md).

## 2. Linear propagation and correlation

u_y² = Σ_i (∂f/∂x_i)² u_i² + 2 Σ_{i<j} (∂f/∂x_i)(∂f/∂x_j) u_ij, with u_ij = r_ij u_i u_j.
Matrix form Σ_y = J Σ_x Jᵀ also gives the covariance between several outputs.

| y | u_y (independent inputs unless a covariance term is shown) |
|---|---|
| a x₁ ± b x₂ | sqrt(a²u₁² + b²u₂² ± 2ab·u₁₂) |
| x₁x₂ or x₁/x₂ | \|y\|·sqrt((u₁/x₁)² + (u₂/x₂)² ± 2u₁₂/(x₁x₂)), + for the product, − for the quotient |
| c·x₁^p₁·x₂^p₂ ⋯ | \|y\|·sqrt(Σ (p_i u_i/x_i)²): relative errors add in quadrature, weighted by the power |
| ln x | u/x |
| eˣ | y·u |

Validity: first order needs ½|f″|u² ≪ |f′|u, roughly relative input errors below 10–20 % for
powers and ratios. It fails at stationary points: y = x² with x = 0 ± 0.1 gives 0 ± 0 linearly,
while the true output has mean 0.0100 and sd 0.0142. Use section 4 there.

**Worked: difference of correlated readings.** One thermometer, two readings, each with ±0.20 K
noise plus a shared calibration offset of ±0.45 K: T₁ = 352.1 ± 0.5 K, T₂ = 351.3 ± 0.5 K,
r = 0.84 (computed with `uncertainties`):

| Quantity | With the correlation | Treated as independent |
|---|---|---|
| T₁ − T₂ | 0.80 ± 0.28 K (offset cancels) | 0.8 ± 0.7 K |
| T₁ + T₂ | 703.4 ± 0.9 K (offset adds coherently) | 703.4 ± 0.7 K |
| T₁/T₂ | 1.0023 ± 0.0008 | 1.0023 ± 0.0020 |

Model the common cause as its own input (cal = 0 ± 0.45 K added to both readings) instead of
guessing r; the correlation then follows. A shared input q gives u(x_i, x_j) = c_iq·c_jq·u_q².

## 3. Code: uncertainties, autodiff Jacobians, pint

```python
import numpy as np
from uncertainties import ufloat, correlated_values, unumpy, umath
L = ufloat(1.000, 0.002, tag="L")                 # tags name the budget lines
T = ufloat(2.007, 0.005, tag="T")
g = 4*np.pi**2*L/T**2                              # correlations tracked through every operation
print(f"{g:.2uS}")                                 # 9.801(53)
print({v.tag: c for v, c in g.error_components().items()})   # T: 0.0488, L: 0.0196
cal = ufloat(0, 0.45); T1 = ufloat(352.10, 0.20) + cal; T2 = ufloat(351.30, 0.20) + cal
print(T1 - T2)                                     # 0.80+/-0.28 (the shared offset cancels)
a, b = correlated_values(popt, pcov)               # fit parameters keep their covariance
arr = unumpy.uarray([1.0, 2.0], [0.1, 0.1]); unumpy.sqrt(arr)   # arrays: unumpy.*
umath.sin(L)              # math.sin(L) and np.sin(L) raise TypeError in uncertainties 3.2
```

Autodiff sensitivities for many inputs or several correlated outputs (JAX 0.12):

```python
import jax, jax.numpy as jnp
jax.config.update("jax_enable_x64", True)         # JAX defaults to float32
f = lambda x: jnp.array([4*jnp.pi**2*x[0]/x[1]**2, 2*jnp.pi/x[1]])   # (g, ω) from (L, T)
x0 = jnp.array([1.000, 2.007]); Sx = jnp.diag(jnp.array([0.002, 0.005])**2)
J = jax.jacfwd(f)(x0)                              # c_ij; autograd.jacobian is equivalent
Sy = J @ Sx @ J.T                                  # u_g = 0.0526, u_ω = 0.0078, r(g, ω) = 0.93
```

Units and errors together (pint 0.26; Measurement needs uncertainties installed):

```python
import pint; ureg = pint.UnitRegistry(); Q_ = ureg.Quantity
gm = 4*np.pi**2*Q_(1.000, "m").plus_minus(0.002)/Q_(2.007, "s").plus_minus(0.005)**2
gm.value, gm.error                                 # 9.8009 m/s², 0.0526 m/s²
Q_(5.0, "m").plus_minus(0.01, relative=True)       # (5.00 +/- 0.05) m
```

## 4. Monte Carlo propagation (JCGM 101)

Use it when f is nonlinear over the input spread (relative u above ~10–20 %), the output is
skewed or bounded (ratios, logs, exponentials, positive quantities), a stationary point is near,
derivatives are awkward, or one non-Gaussian input (e.g. rectangular) dominates.

1. Assign a PDF to each input: Gaussian (Type A, certificates), rectangular (bounds), scaled t
   with n − 1 dof (Type A from few repeats), multivariate normal (correlated inputs).
2. Draw M samples and evaluate y_r = f(x_r).
3. Report u(y) = sd of the y_r and a 95 % interval: the probabilistically symmetric one (2.5th to
   97.5th percentile), or the shortest one for skewed output. Use the median and percentiles when
   the mean does not exist (1/x of a Gaussian).
4. Validate the GUM result: d_low = |y − U − y_low| and d_high = |y + U − y_high| must both be
   ≤ δ, where δ = ½·10^l when u(y) written with n_dig significant digits is c × 10^l
   (JCGM 101 §8.1, §7.9.2).

Trial count: M = 10⁶ "can often be expected" to fix a 95 % interval to one or two significant
digits (JCGM 101 §7.2.1 note); in general M ≥ 10⁴/(1 − p). The adaptive procedure (§7.9.4) runs
batches of max(⌈100/(1 − p)⌉, 10⁴) until twice the sd of the batch estimates of y, u(y), y_low and
y_high is below δ; for the pendulum it stops at 2·10⁴ trials for n_dig = 1 and 3.9·10⁵ for
n_dig = 2 ([adaptive loop](references/gum-budget-tables.md)). Expensive models (FEM, CFD): 50–100
runs give a mean and sd that capture the nonlinearity, then assume Gaussian (§7.2.3 note), or fit
a surrogate first.

```python
rng = np.random.default_rng(2026); M = 1_000_000
L = rng.normal(1.000, 0.002, M); T = rng.normal(2.007, 0.005, M)
g = 4*np.pi**2*L/T**2
y_lo, y_hi = np.percentile(g, [2.5, 97.5])         # probabilistically symmetric 95 %
# correlated: rng.multivariate_normal(mean, cov, size=M); bounds: rng.uniform(x - a, x + a, M)
# Type A from n repeats: xbar + s/np.sqrt(n)*rng.standard_t(n - 1, M)
```

Asymmetry example: y = 1/x with x = 1.0 ± 0.3 gives 1.00 ± 0.30 linearly (95 %: 0.41–1.59);
Monte Carlo gives median 1.00 and a 95 % interval of 0.63–2.4.

## 5. Fitting

| Situation | Tool | Settings that matter |
|---|---|---|
| Known Gaussian σ_y, exact x | `scipy.optimize.curve_fit` | `sigma=σ, absolute_sigma=True`; a 2-D `sigma` is the covariance of y |
| Bounds, fixed or tied parameters, profile intervals | `lmfit.Model.fit` | `weights=1/σ, scale_covar=False`; `result.conf_interval(sigmas=[1, 2])` |
| Asymmetric errors, likelihood costs | `iminuit` | `Minuit(LeastSquares(x, y, σ, f), **p0)`; `migrad()`, `hesse()`, `minos()` |
| Posterior, priors, nuisance parameters, multimodality | `emcee` or PyMC (NUTS) | autocorrelation time, R̂, effective sample size |
| Errors in x | ODR or effective variance | section 7 |
| Counts | Poisson likelihood | section 8 |

`curve_fit` defaults to `absolute_sigma=False`: σ is read as relative weights and pcov is
multiplied by χ²_ν, so every error is your σ-based error × sqrt(χ²_ν). With measured σ this hides
a bad fit and makes a χ²_ν = 0.89 fit look 6 % more precise than it is. The same switch elsewhere:

| Library | Errors from your σ (absolute) | Errors rescaled by χ²_ν |
|---|---|---|
| curve_fit | `absolute_sigma=True` | default |
| lmfit | `scale_covar=False` | default (`scale_covar=True`) |
| odrpack / scipy.odr | `np.sqrt(np.diag(out.cov_beta))` | `out.sd_beta` |
| iminuit `LeastSquares` | default (errordef 1) | multiply by `sqrt(m.fmin.reduced_chi2)` yourself |

Rescaled errors are right only when σ is unknown, and then χ²_ν carries no goodness-of-fit
information.

```python
from scipy.optimize import curve_fit
from scipy import stats
f = lambda x, A, tau: A*np.exp(-x/tau)
popt, pcov = curve_fit(f, x, y, p0=[1, 1], sigma=sig, absolute_sigma=True)
perr = np.sqrt(np.diag(pcov))
chi2 = np.sum(((y - f(x, *popt))/sig)**2); nu = x.size - popt.size
p_value = stats.chi2.sf(chi2, nu)
```

On 15 simulated points (σ = 0.05): A = 1.994 ± 0.039, τ = 1.289 ± 0.040, χ² = 11.6, ν = 13,
p = 0.56, corr(A, τ) = −0.63. MINOS gives τ −0.040/+0.042, lmfit `conf_interval` −0.039/+0.041,
emcee 16–84 % 1.25–1.33: all agree because the problem is nearly linear. Full scripts:
[fitting recipes](references/fitting-recipes.md).

## 6. Goodness of fit

- χ²_ν = χ²/ν with ν = N − n_params; expect 1 ± sqrt(2/ν) (ν = 13: 0.61–1.39); p-value from
  `stats.chi2.sf(chi2, nu)`.

| Result | Reading |
|---|---|
| p < 0.001 (χ²_ν ≫ 1) | model wrong, σ underestimated or outliers: inspect residuals before touching σ |
| 0.001 ≤ p ≤ 0.999 | consistent; still check residual structure |
| p > 0.999 (χ²_ν ≪ 1) | σ overestimated (ranges, double-counted systematics), correlated points treated as independent, or over-fitting |

- Normalised residuals r_i = (y_i − f(x_i))/σ_i: about 68 % within ±1 and 95 % within ±2. Plot
  them against x, against f, and in acquisition order; trends or curvature are model error that
  χ² can miss.
- Runs test on residual signs: R runs, n₊ and n₋ signs, n = n₊ + n₋; E[R] = 1 + 2n₊n₋/n,
  Var R = 2n₊n₋(2n₊n₋ − n)/(n²(n − 1)); |z| > 2 flags systematic misfit. A straight line fitted to
  the decay data above gives χ²_ν = 25 and z = −2.9; the exponential gives z = 0.8.
- Correlation matrix ρ_ij = C_ij/sqrt(C_ii C_jj): |ρ| > 0.95 means near-degenerate parameters, so
  reparametrise. A line fitted over x = 100…110 has corr(a, b) = −0.9995, and y(105) is
  54.492 ± 0.030 with the covariance but ± 1.4 without it. Centring (y = a′ + b(x − x̄)) gives
  ρ = 0 and ± 0.030 directly.
- Model choice with known Gaussian σ: AIC = χ² + 2k, BIC = χ² + k ln N, AICc = AIC +
  2k(k + 1)/(N − k − 1). ΔAIC 0–2: equivalent; 4–7: considerably less support; > 10: essentially
  none (Burnham and Anderson). ΔBIC ≈ 2 ln(Bayes factor): 2–6 positive, 6–10 strong, > 10 very
  strong (Kass and Raftery). lmfit's `aic`/`bic` use N ln(χ²/N) + 2k (σ treated as unknown); with
  trusted σ compute χ² + 2k yourself.
- Nested models: Δχ² ~ χ²(Δk) (Wilks), except for a parameter on a boundary (amplitude ≥ 0),
  where the null distribution is a 50:50 mix of 0 and χ²(1).

## 7. Errors in x: ODR or effective variance

Compare ρ_x = σ_x·|f′(x)|/σ_y point by point:

| ρ_x | Action |
|---|---|
| < 0.2 | ignore the x-errors (they add < 4 % to the variance) |
| 0.2 to ~1, mildly nonlinear f | effective variance σ_eff² = σ_y² + (f′(x)σ_x)²; refit and update f′ until stable (3–5 passes) |
| ≳ 1, strongly nonlinear f, or correlated x-y errors | orthogonal distance regression |

`scipy.odr` is deprecated since SciPy 1.17.0 and scheduled for removal in 1.19.0; its warning
points to the `odrpack` package (ODRPACK95 bindings). Note the reversed model signature,
f(x, beta), against scipy.odr's f(beta, x):

```python
from odrpack import odr_fit                        # uv add odrpack
sol = odr_fit(lambda x, b: b[0] + b[1]*x, x, y, beta0=np.array([1.0, 1.0]),
              weight_x=1/sx**2, weight_y=1/sy**2)
abs_err = np.sqrt(np.diag(sol.cov_beta))           # from your σ
scaled = sol.sd_beta                               # = abs_err*sqrt(sol.res_var)
```

Checked on 20 simulated points: odrpack and scipy.odr return the same beta, and in both
sd_beta = sqrt(diag(cov_beta)·res_var) (res_var = 1.21 there). Effective variance landed within
0.3σ of ODR. Straight lines with correlated x-y errors: York et al. (2004), Am. J. Phys. 72, 367.

## 8. Counting data

- Below ~10–20 counts per bin, σ = √n is wrong (and zero in empty bins). Maximise the Poisson
  likelihood. The deviance D = 2 Σ[μ_i − n_i + n_i ln(n_i/μ_i)] (Baker-Cousins; n ln n → 0 for
  empty bins) is asymptotically χ²(N − k), so it doubles as the goodness-of-fit statistic. Cash's
  C = 2 Σ(μ_i − n_i ln μ_i) differs from D by a data-only constant.
- iminuit: `cost.poisson_chi2(n, mu)` returns D; `ExtendedBinnedNLL(n, xe, scaled_cdf)` and
  `UnbinnedNLL(data, pdf)` cover binned and unbinned fits. A hand-written D uses
  `errordef = Minuit.LEAST_SQUARES` (χ² scale); a hand-written −ln L uses `Minuit.LIKELIHOOD` (0.5).
- 2000 simulated spectra, 20 bins, μ = 12e^{−t/4} + 0.5 (≈ 58 counts each):

| Fit | Median τ (true 4.0) | Mean Σμ̂ − Σn |
|---|---|---|
| Neyman χ², σ² = max(n, 1) | 3.30 | −9.1 counts (−16 %) |
| Poisson deviance | 4.02 | 0.00 (a free normalisation preserves the total exactly) |
| Weighted LS iterated with σ² = μ̂ (IRLS) | 4.02 | 0.00 (converges to the Poisson MLE) |

- Never fit ln n with unit weights: Var(ln n) ≈ 1/n and E[ln n] ≈ ln μ − 1/(2μ), so low-count
  points get too much weight and a downward bias. Fit the counts with the Poisson likelihood
  (weighting ln n by n is acceptable only when every bin has ≳ 20 counts).
- Few events near a physical boundary (signal ≥ 0): Feldman-Cousins unified intervals.

## 9. Resampling

| Method | Use when | Recipe |
|---|---|---|
| Residual bootstrap | x fixed, homoscedastic errors | refit f̂ + resampled residuals, B ≥ 1000 |
| Wild bootstrap | heteroscedastic residuals | refit f̂ + r_i·(random ±1) |
| Pairs bootstrap | model or σ may be wrong | resample (x_i, y_i, σ_i) rows |
| Parametric bootstrap | trusted model and σ, nonlinear estimator | refit f̂ + N(0, σ_i) |
| Jackknife | smooth nonlinear estimator, cheap bias estimate | bias = (n − 1)(θ̄₍.₎ − θ̂); var = ((n − 1)/n)·Σ(θ₍ᵢ₎ − θ̄₍.₎)²; fails for medians and quantiles |
| Block bootstrap | time-correlated samples (MC chains, time series) | blocks ≫ τ_int; `arch.bootstrap.StationaryBootstrap(optimal_block_length(x)...)` |

`scipy.stats.bootstrap((x,), np.mean, n_resamples=9999, method="BCa")`: data go in as a tuple of
samples; use ≥ 10⁴ resamples for 95 % percentile or BCa intervals. On the decay fit, se(τ) was
0.040 (curve_fit), 0.040 (jackknife), 0.035 (residual), 0.031 (wild), 0.046 (pairs).

Correlated data: an AR(1) series with φ = 0.9 (τ_int = (1 + φ)/(1 − φ) = 19), n = 20 000. Naive
SE of the mean 0.0164; stationary block bootstrap 0.0717; moving block 0.0735; blocking plateau
0.072–0.076; theory 0.0716. τ_int windows and blocking analysis: `statmech-monte-carlo`.

## 10. Reporting

- Uncertainty to 1–2 significant digits (GUM 7.2.6). The PDG rule, which the `uncertainties`
  default format applies: leading three digits 100–354 → two digits, 355–949 → one digit,
  950–999 → round up to 1000 and keep two.
- Round the value to the last digit of the uncertainty: 10.057 62 Ω with u = 27 mΩ → 10.058 Ω.
- Concise form 1.2345(67) = 1.2345 ± 0.0067; `f"{x:.2uS}"` prints it.
- Keep components apart: g = 9.81 ± 0.02 (stat) ± 0.05 (sys) m/s². Combine only when asked, in
  quadrature if independent, and say so.
- Always say what the number is: "u_c = 0.053 m/s² (k = 1)" or "U = 0.11 m/s² (k = 2.21,
  95.45 %, ν_eff = 13)".
- Asymmetric intervals stay asymmetric: τ = 1.289 +0.042/−0.040 (MINOS, profile or MC percentiles).
- Give correlation coefficients to three digits when |ρ| is near 1, or give the covariance matrix.
- Round up rather than to nearest when understating would matter (GUM: 10.47 mΩ → 11 mΩ).

## 11. Worked example: pendulum g

Inputs L = 1.000 ± 0.002 m and T = 2.007 ± 0.005 s (k = 1, independent).

1. g = 4π²L/T² = 39.478 418/4.028 049 = 9.8009 m/s².
2. (u_g/g)² = (u_L/L)² + (2u_T/T)² = 0.0020² + 0.004 983², so u_g/g = 0.537 %.
3. u_g = 0.0526 m/s². Budget: the T line contributes 0.0488 (86 % of u_g²), the L line 0.0196.
   Better timing pays; a better ruler barely helps.
4. Report g = 9.80 ± 0.05 m/s² (k = 1), concise 9.801(53) m/s².
5. Monte Carlo (M = 10⁶): mean 9.8010, sd 0.0527, 95 % interval [9.6985, 9.9047]. GUM interval
   9.8009 ± 1.96 × 0.0526 = [9.6977, 9.9040]; d_low = 0.0008 and d_high = 0.0007 are below
   δ = 0.005 (u = 0.05 at n_dig = 1), so linear propagation is validated. Ten independent MC runs
   moved the endpoints by about 1e-4 (sd).
6. Amplitude θ₀ = 5°: T = T₀(1 + θ₀²/16 + …) = 1.000 476·T₀ (the exact elliptic result agrees), so
   g rises by 0.095 % = +0.0093 m/s² = 0.18 u_g. Negligible now; it is a known bias, so apply it as
   a correction once u_g drops below ~0.02 m/s².

If T came from ten repeats of 10 periods (s = 0.15 s), ν_eff = 13 and k(95.45 %) = 2.21, so
U = 0.11 m/s² rather than 2u_c = 0.10 m/s² ([budget table](references/gum-budget-tables.md)).

## 12. Pitfalls

- **Max-min spread as σ.** For 5 normal readings the expected range is 2.33σ, so quoting the range
  as the uncertainty of the mean overstates it 5.2×. Use s/√n; use a/√3 only for real bounds.
- **Half-width versus full width.** "Tolerance ±a" gives a/√3; "an interval of width a" gives a/√12.
- **Double-counted correlated systematics.** A calibration term inside each input's u and again
  as its own line; or a shared offset treated as independent across N averaged readings, which
  wrongly shrinks it by √N.
- **Hidden systematic floor.** Averaging reduces only the random part: u = sqrt(s²/N + u_sys²)
  plateaus at u_sys. An s/√N quoted for N = 10⁴ readings usually ignores the floor.
- **absolute_sigma left at its default** (and lmfit `scale_covar=True`, ODR `sd_beta`): errors
  follow the scatter, not your σ, and χ²_ν stops testing anything.
- **Ignored parameter correlations in derived quantities:** ±1.4 instead of ±0.030 in the line
  example. Propagate with `correlated_values(popt, pcov)` or J·C·Jᵀ.
- **Inflating errors by sqrt(χ²_ν)** to hide a bad fit. If you do it (PDG scale factor
  S = sqrt(χ²/ν) when S > 1), say so and investigate the model first.
- **Linearising** near an extremum or at large relative errors (x² at 0, 1/x at 30 %).
- **math.sin or np.sin on a ufloat** raise TypeError (use `umath`, `unumpy`); JAX runs in float32
  until `jax_enable_x64` is set.
- **χ² with σ = √n at low counts**, or a fit to ln(counts) with unit weights.

Related: `simulation-verification-validation`, `dimensional-analysis-units`, `statmech-monte-carlo`,
`statistical-inference-bayesian`, `numerical-error-analysis`, hub `physics-toolkit`.
