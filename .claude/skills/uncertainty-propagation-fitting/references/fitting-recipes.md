# Fitting recipes with outputs

Every block below was run in October 2026 (Python 3.13, NumPy 2.5, SciPy 1.18, lmfit 1.3.4,
iminuit 2.33, emcee 3.1.6, odrpack 0.6.1, arch 8.0). Outputs are quoted in comments so that a
regression in your environment is visible. Blocks share the data set defined in section 1.

## 1. One data set, four fitters

```python
import numpy as np
from scipy import stats
from scipy.optimize import curve_fit
rng = np.random.default_rng(42)
x = np.linspace(0, 4, 15); sig = np.full_like(x, 0.05)
f = lambda x, A, tau: A*np.exp(-x/tau)
y = f(x, 2.0, 1.3) + rng.normal(0, sig)

# curve_fit: absolute errors versus the default rescaled ones
popt, pcov = curve_fit(f, x, y, p0=[1, 1], sigma=sig, absolute_sigma=True)
_, pcov_rel = curve_fit(f, x, y, p0=[1, 1], sigma=sig)            # absolute_sigma=False
chi2 = np.sum(((y - f(x, *popt))/sig)**2); nu = x.size - 2
print(popt, np.sqrt(np.diag(pcov)))         # [1.9943 1.2889] [0.0387 0.0402]
print(np.sqrt(np.diag(pcov_rel)/np.diag(pcov)), np.sqrt(chi2/nu))   # 0.944 0.944: same factor
print(chi2, nu, stats.chi2.sf(chi2, nu))    # 11.59 13 0.56
```

```python
import lmfit
mod = lmfit.Model(f)                          # independent variable inferred from the signature
pars = mod.make_params(A=1, tau=1); pars["tau"].set(min=0)
res = mod.fit(y, pars, x=x, weights=1/sig, scale_covar=False)    # weights multiply residuals
print(res.params["tau"].value, res.params["tau"].stderr, res.redchi)   # 1.2889 0.0402 0.892
print(res.aic, res.bic)                       # 0.134 1.550 (N ln(chi2/N) + 2k and + k ln N)
ci = res.conf_interval(sigmas=[1, 2])         # profile-likelihood intervals
print(lmfit.ci_report(ci))                    # tau: -0.03943 / +0.04084 at 68.27 %
```

```python
from iminuit import Minuit
from iminuit.cost import LeastSquares
m = Minuit(LeastSquares(x, y, sig, f), A=1, tau=1)
m.migrad(); m.hesse(); m.minos()
print(m.values["tau"], m.errors["tau"], m.fval, m.ndof, m.fmin.reduced_chi2)
# 1.2889 0.0409 11.59 13.0 0.892
print(m.merrors["tau"].lower, m.merrors["tau"].upper)   # -0.0402 +0.0416
print(m.covariance.correlation()["A", "tau"])            # -0.64
```

```python
import emcee
def log_prob(th):
    A, tau = th
    if tau <= 0: return -np.inf                # flat priors with a positivity bound
    return -0.5*np.sum(((y - f(x, A, tau))/sig)**2)
nw, nd = 16, 2
s = emcee.EnsembleSampler(nw, nd, log_prob)
s.run_mcmc(popt + 1e-4*rng.normal(size=(nw, nd)), 3000, progress=False)
print(s.get_autocorr_time(tol=0))             # ~[30, 30] steps: discard several times this
chain = s.get_chain(discard=500, thin=10, flat=True)
print(np.percentile(chain[:, 1], [16, 50, 84]))   # 1.251 1.294 1.333
```

## 2. Residual diagnostics

```python
def runs_test(r):
    s = np.sign(r[r != 0]); n1, n2 = (s > 0).sum(), (s < 0).sum(); n = n1 + n2
    R = 1 + np.count_nonzero(s[1:] != s[:-1])
    mu = 1 + 2*n1*n2/n; var = 2*n1*n2*(2*n1*n2 - n)/(n**2*(n - 1))
    return R, mu, (R - mu)/np.sqrt(var)
r = (y - f(x, *popt))/sig
print(runs_test(r))                           # (9, 7.67, z = 0.81): no structure
p_lin, _ = curve_fit(lambda x, a, b: a + b*x, x, y, sigma=sig, absolute_sigma=True)
r_lin = (y - (p_lin[0] + p_lin[1]*x))/sig
print(np.sum(r_lin**2)/13, runs_test(r_lin))  # 25.1, (3, 8.47, z = -2.94): wrong model
corr = pcov/np.outer(np.sqrt(np.diag(pcov)), np.sqrt(np.diag(pcov)))   # corr(A, tau) = -0.63
```

## 3. Errors in x

```python
xt = np.linspace(0, 10, 20); sx = np.full(20, 0.3); sy = np.full(20, 0.5)
r2 = np.random.default_rng(1)
xo = xt + r2.normal(0, sx); yo = 2.0 + 1.5*xt + r2.normal(0, sy)

from odrpack import odr_fit                  # model signature f(x, beta)
sol = odr_fit(lambda x, b: b[0] + b[1]*x, xo, yo, beta0=np.array([1., 1.]),
              weight_x=1/sx**2, weight_y=1/sy**2)
print(sol.beta, np.sqrt(np.diag(sol.cov_beta)), sol.sd_beta, sol.res_var)
# [1.7009 1.5531] [0.2996 0.0514] [0.3302 0.0567] 1.215  -> sd_beta = sqrt(diag(cov)*res_var)

# scipy.odr (deprecated in 1.17, removal planned for 1.19): model signature f(beta, x)
import scipy.odr as sodr
out = sodr.ODR(sodr.RealData(xo, yo, sx=sx, sy=sy), sodr.Model(lambda b, x: b[0] + b[1]*x),
               beta0=[1, 1]).run()            # same beta, cov_beta, sd_beta

# effective variance: iterate weights with the current slope
p = np.array([1., 1.])
for _ in range(10):
    s_eff = np.sqrt(sy**2 + (p[1]*sx)**2)
    p, C = curve_fit(lambda x, a, b: a + b*x, xo, yo, p0=p, sigma=s_eff, absolute_sigma=True)
print(p, np.sqrt(np.diag(C)))                 # [1.787 1.536] [0.298 0.051]: within 0.3 sigma of ODR
```

## 4. Poisson counts

```python
from iminuit.cost import poisson_chi2
t = np.arange(20) + 0.5                       # bin centres, width 1
mu = lambda t, A, tau, b: A*np.exp(-t/tau) + b
n = np.random.default_rng(7).poisson(mu(t, 12.0, 4.0, 0.5))
m = Minuit(lambda A, tau, b: poisson_chi2(n, mu(t, A, tau, b)), A=10, tau=3, b=1)
m.errordef = Minuit.LEAST_SQUARES             # poisson_chi2 is on the chi2 scale (deviance)
m.limits["tau"] = (0.1, None); m.limits["b"] = (0, None)
m.migrad(); m.hesse()
deviance, ndof = m.fval, n.size - 3           # 19.1, 17: deviance ~ chi2(ndof), p = 0.32
```

Bias study (2000 replicas, script in the SKILL.md table): Neyman χ² with σ² = max(n, 1) gave a
median τ of 3.30 and lost 9.1 of ~58 counts on average; the Poisson deviance and IRLS with
σ² = μ̂ gave a median τ of 4.02 and Σμ̂ = Σn to machine precision.

Binned and unbinned likelihood classes: `ExtendedBinnedNLL(n, xe, scaled_cdf)` (counts n in bins
with edges xe, model expected cumulative counts), `BinnedNLL(n, xe, cdf)` (shape only),
`UnbinnedNLL(data, pdf)` and `ExtendedUnbinnedNLL(data, scaled_pdf)`; their `errordef` is set for
you.

## 5. Jackknife and bootstraps for a fitted parameter

```python
th = np.array([curve_fit(f, np.delete(x, i), np.delete(y, i), p0=popt,
                         sigma=np.delete(sig, i), absolute_sigma=True)[0][1] for i in range(x.size)])
nn = x.size; tb = th.mean()
bias = (nn - 1)*(tb - popt[1])                    # 0.012
se_jack = np.sqrt((nn - 1)/nn*np.sum((th - tb)**2))   # 0.0397

fit = f(x, *popt); res_ = y - fit
def boot(kind, B=2000):
    out = []
    for _ in range(B):
        if kind == "pairs":
            i = rng.integers(0, x.size, x.size)
            out.append(curve_fit(f, x[i], y[i], p0=popt, sigma=sig[i], absolute_sigma=True)[0][1])
            continue
        yb = fit + (rng.choice(res_, res_.size) if kind == "residual"
                    else res_*rng.choice([-1.0, 1.0], res_.size))          # "wild"
        out.append(curve_fit(f, x, yb, p0=popt, sigma=sig, absolute_sigma=True)[0][1])
    return np.std(out, ddof=1)
# residual 0.035, wild 0.031, pairs 0.046 (curve_fit 0.040)
```

`scipy.stats.bootstrap(data, statistic, *, n_resamples=9999, batch=None, vectorized=None,
paired=False, axis=0, confidence_level=0.95, alternative='two-sided', method='BCa', ...,
rng=None)`: `data` is a sequence of samples, so a single sample is `(x,)`.

## 6. Block bootstrap for correlated series

```python
from arch.bootstrap import StationaryBootstrap, MovingBlockBootstrap, optimal_block_length
g3 = np.random.default_rng(0); N = 20000; xs = np.empty(N); xs[0] = 0; e = g3.normal(size=N)
for i in range(1, N): xs[i] = 0.9*xs[i - 1] + e[i]              # AR(1), tau_int = 19
b = float(optimal_block_length(xs)["stationary"].iloc[0])       # ~127
se_sb = np.sqrt(StationaryBootstrap(b, xs, seed=1).cov(np.mean, reps=1000))       # 0.0717
se_mb = np.sqrt(MovingBlockBootstrap(int(round(b)), xs, seed=1).cov(np.mean, reps=1000))  # 0.0735
naive = xs.std(ddof=1)/np.sqrt(N)                                # 0.0164: 4.4x too small
```

The arch bootstrap objects expose `cov`, `var`, `conf_int(func, reps, method=...)` with methods
`basic`, `percentile`, `studentized`, `norm`, `bc`, `bca`.
