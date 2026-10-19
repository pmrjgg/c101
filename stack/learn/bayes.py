"""Bayesian estimators used to tune agent budgets from observed sessions.

Everything here is stdlib-only and Python 3.9 compatible, so it can run inside
a Claude Code hook on a stock macOS install.

Models
------
* ``LogNormalGrid``  -- log-normal likelihood with a grid posterior over
  (mu, sigma).  Handles right-censored observations exactly (a run that hit
  ``maxTurns`` only tells us "needed at least this many turns"), supports
  per-observation weights (exponential forgetting), and gives posterior
  predictive CDF / quantiles / log densities.
* ``BetaRate``       -- Beta-Bernoulli rate (failure / cap-hit probability).
* ``DirichletCategories`` -- Dirichlet-multinomial over ordered categories
  (effort levels), with predictive cumulative probabilities.
* ``select_forgetting`` -- picks the forgetting factor (the effective data
  window) that maximises the prequential (one-step-ahead) log score, i.e. the
  window the evidence itself prefers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

_SQRT2 = math.sqrt(2.0)
_LOG_SQRT_2PI = 0.5 * math.log(2.0 * math.pi)


# --------------------------------------------------------------------------- #
# Normal helpers
# --------------------------------------------------------------------------- #
def norm_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / _SQRT2)


def norm_logsf(z: float) -> float:
    """log(1 - Phi(z)), stable in both tails."""
    if z < 5.0:
        sf = 0.5 * math.erfc(z / _SQRT2)
        return math.log(sf) if sf > 0.0 else -745.0
    # Asymptotic (Mills ratio) expansion for the far right tail.
    z2 = z * z
    return -0.5 * z2 - math.log(z) - _LOG_SQRT_2PI + math.log1p(-1.0 / z2 + 3.0 / (z2 * z2))


def _logsumexp(xs: Sequence[float]) -> float:
    m = max(xs)
    if m == -math.inf:
        return -math.inf
    return m + math.log(sum(math.exp(x - m) for x in xs))


def _linspace(a: float, b: float, n: int) -> List[float]:
    if n == 1:
        return [0.5 * (a + b)]
    step = (b - a) / (n - 1)
    return [a + i * step for i in range(n)]


def _logspace(a: float, b: float, n: int) -> List[float]:
    return [math.exp(v) for v in _linspace(math.log(a), math.log(b), n)]


# --------------------------------------------------------------------------- #
# Observations
# --------------------------------------------------------------------------- #
@dataclass
class Obs:
    """One observed run.  ``censored`` means the true value is >= ``value``."""

    value: float
    censored: bool = False
    weight: float = 1.0


def forgetting_weights(n: int, gamma: float) -> List[float]:
    """Weights for n chronologically ordered observations (oldest first)."""
    return [gamma ** (n - 1 - i) for i in range(n)]


# --------------------------------------------------------------------------- #
# Censored log-normal with a grid posterior
# --------------------------------------------------------------------------- #
@dataclass
class LogNormalPrior:
    """Weakly-informative prior.

    mu ~ Normal(mu_mean, mu_sd) on the log scale; sigma ~ LogNormal(log(sigma_med), sigma_sd).
    """

    mu_mean: float
    mu_sd: float = 1.0
    sigma_med: float = 0.6
    sigma_sd: float = 0.6

    @classmethod
    def around(cls, typical: float, spread_factor: float = 3.0, sigma_med: float = 0.6) -> "LogNormalPrior":
        """Prior centred on a typical value; ``spread_factor`` is a 1-sd multiplicative range."""
        return cls(mu_mean=math.log(max(typical, 1e-9)), mu_sd=math.log(max(spread_factor, 1.0001)),
                   sigma_med=sigma_med)


class LogNormalGrid:
    """Posterior over (mu, sigma) of log(value) on a fixed grid."""

    def __init__(self, prior: LogNormalPrior, n_mu: int = 48, n_sigma: int = 28,
                 sigma_range: Tuple[float, float] = (0.05, 2.5)) -> None:
        self.prior = prior
        self.n_mu = n_mu
        self.n_sigma = n_sigma
        self.sigma_range = sigma_range
        self.mus: List[float] = []
        self.sigmas: List[float] = _logspace(sigma_range[0], sigma_range[1], n_sigma)
        self.logw: List[float] = []      # normalised log posterior per cell (row-major mu x sigma)
        self.n_eff: float = 0.0
        self.n_censored: float = 0.0
        self._build_mu_grid([])

    # -- grid -------------------------------------------------------------- #
    def _build_mu_grid(self, ys: Sequence[float]) -> None:
        lo = self.prior.mu_mean - 4.0 * self.prior.mu_sd
        hi = self.prior.mu_mean + 4.0 * self.prior.mu_sd
        if ys:
            lo = min(lo, min(ys) - 1.5)
            hi = max(hi, max(ys) + 2.5)  # room above: censored points push mass upward
        self.mus = _linspace(lo, hi, self.n_mu)

    def _log_prior(self, mu: float, sigma: float) -> float:
        p = self.prior
        lp_mu = -0.5 * ((mu - p.mu_mean) / p.mu_sd) ** 2
        ls = math.log(sigma)
        lp_sigma = -0.5 * ((ls - math.log(p.sigma_med)) / p.sigma_sd) ** 2
        # Grid in sigma is log-spaced, so the density on log(sigma) needs no Jacobian.
        return lp_mu + lp_sigma

    # -- fitting ----------------------------------------------------------- #
    def fit(self, observations: Iterable[Obs]) -> "LogNormalGrid":
        obs = [o for o in observations if o.value > 0 and o.weight > 0]
        exact = [(math.log(o.value), o.weight) for o in obs if not o.censored]
        cens = [(math.log(o.value), o.weight) for o in obs if o.censored]
        self._build_mu_grid([y for y, _ in exact] + [y for y, _ in cens])

        # Sufficient statistics for the exact (uncensored) part.
        W = sum(w for _, w in exact)
        S1 = sum(w * y for y, w in exact)
        S2 = sum(w * y * y for y, w in exact)
        self.n_eff = W + sum(w for _, w in cens)
        self.n_censored = sum(w for _, w in cens)

        logw: List[float] = []
        for mu in self.mus:
            for sigma in self.sigmas:
                lp = self._log_prior(mu, sigma)
                if W > 0:
                    ss = S2 - 2.0 * mu * S1 + mu * mu * W
                    lp += -W * math.log(sigma) - ss / (2.0 * sigma * sigma)
                for y, w in cens:
                    lp += w * norm_logsf((y - mu) / sigma)
                logw.append(lp)
        z = _logsumexp(logw)
        self.logw = [v - z for v in logw]
        return self

    # -- posterior summaries ----------------------------------------------- #
    def _cells(self):
        k = 0
        for mu in self.mus:
            for sigma in self.sigmas:
                yield mu, sigma, self.logw[k]
                k += 1

    def posterior_mean(self) -> Tuple[float, float]:
        m = s = 0.0
        for mu, sigma, lw in self._cells():
            w = math.exp(lw)
            m += w * mu
            s += w * sigma
        return m, s

    def predictive_cdf(self, x: float) -> float:
        if x <= 0:
            return 0.0
        y = math.log(x)
        total = 0.0
        for mu, sigma, lw in self._cells():
            if lw < -30:
                continue
            total += math.exp(lw) * norm_cdf((y - mu) / sigma)
        return min(max(total, 0.0), 1.0)

    def predictive_logpdf(self, x: float) -> float:
        """Log posterior-predictive density of a new value x (on the x scale)."""
        y = math.log(x)
        terms = []
        for mu, sigma, lw in self._cells():
            z = (y - mu) / sigma
            terms.append(lw - 0.5 * z * z - math.log(sigma) - _LOG_SQRT_2PI - y)
        return _logsumexp(terms)

    def predictive_logsf(self, x: float) -> float:
        """Log posterior-predictive probability that a new value is >= x."""
        y = math.log(x)
        return _logsumexp([lw + norm_logsf((y - mu) / sigma) for mu, sigma, lw in self._cells()])

    def predictive_quantile(self, q: float, tol: float = 1e-4) -> float:
        q = min(max(q, 1e-6), 1 - 1e-6)
        lo, hi = self.mus[0] - 4 * self.sigmas[-1], self.mus[-1] + 4 * self.sigmas[-1]
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if self.predictive_cdf(math.exp(mid)) < q:
                lo = mid
            else:
                hi = mid
            if hi - lo < tol:
                break
        return math.exp(0.5 * (lo + hi))


# --------------------------------------------------------------------------- #
# Beta-Bernoulli rate
# --------------------------------------------------------------------------- #
@dataclass
class BetaRate:
    a: float = 1.0
    b: float = 1.0

    def update(self, successes: float, failures: float) -> "BetaRate":
        return BetaRate(self.a + successes, self.b + failures)

    @property
    def mean(self) -> float:
        return self.a / (self.a + self.b)

    def quantile(self, q: float) -> float:
        """Quantile by bisection on the regularised incomplete beta (continued fraction)."""
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if _betainc(self.a, self.b, mid) < q:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)


def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1.0 - x) / b


# --------------------------------------------------------------------------- #
# Dirichlet over ordered categories
# --------------------------------------------------------------------------- #
class DirichletCategories:
    def __init__(self, labels: Sequence[str], alpha0: Optional[Sequence[float]] = None) -> None:
        self.labels = list(labels)
        self.alpha = list(alpha0) if alpha0 is not None else [1.0] * len(self.labels)

    def update(self, weighted_counts: Sequence[float]) -> "DirichletCategories":
        d = DirichletCategories(self.labels, [a + c for a, c in zip(self.alpha, weighted_counts)])
        return d

    def predictive(self) -> List[float]:
        s = sum(self.alpha)
        return [a / s for a in self.alpha]

    def smallest_covering(self, mass: float) -> int:
        """Index of the smallest category c with P(category <= c) >= mass."""
        acc = 0.0
        for i, p in enumerate(self.predictive()):
            acc += p
            if acc >= mass - 1e-12:
                return i
        return len(self.labels) - 1


# --------------------------------------------------------------------------- #
# Data-window (forgetting factor) selection by prequential log score
# --------------------------------------------------------------------------- #
def prequential_score(values: Sequence[Obs], gamma: float, prior: LogNormalPrior,
                      holdout: int = 12, grid: Tuple[int, int] = (32, 20)) -> float:
    """Sum of one-step-ahead predictive log scores over the last ``holdout`` points.

    Uncensored points score with the predictive log density; censored points
    with the predictive log survival -- both are proper scores for what was seen.
    """
    n = len(values)
    start = max(1, n - holdout)
    total = 0.0
    for t in range(start, n):
        past = values[:t]
        ws = forgetting_weights(len(past), gamma)
        model = LogNormalGrid(prior, n_mu=grid[0], n_sigma=grid[1]).fit(
            Obs(o.value, o.censored, w) for o, w in zip(past, ws))
        cur = values[t]
        total += model.predictive_logsf(cur.value) if cur.censored else model.predictive_logpdf(cur.value)
    return total


DEFAULT_GAMMAS = (1.0, 0.99, 0.97, 0.94, 0.9, 0.85)


def select_forgetting(values: Sequence[Obs], prior: LogNormalPrior,
                      gammas: Sequence[float] = DEFAULT_GAMMAS, min_points: int = 8,
                      tolerance: float = 1.5) -> Tuple[float, dict]:
    """Return (gamma, {gamma: score}).  Falls back to 1.0 with too little data.

    Prequential scores are noisy, so we apply a "one standard error"-style rule:
    among the gammas scoring within ``tolerance`` nats of the best, keep the one
    with the longest memory.  A shorter window is chosen only when the evidence
    for drift is clear.
    """
    if len(values) < min_points:
        return 1.0, {}
    scores = {g: prequential_score(values, g, prior) for g in gammas}
    best_score = max(scores.values())
    best = max(g for g, sc in scores.items() if sc >= best_score - tolerance)
    return best, scores


def effective_window(gamma: float, n: int) -> float:
    """Effective number of observations retained under forgetting factor gamma."""
    if gamma >= 1.0:
        return float(n)
    return (1 - gamma ** n) / (1 - gamma)
