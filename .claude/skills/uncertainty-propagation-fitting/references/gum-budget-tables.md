# GUM budget tables and the JCGM 101 adaptive loop

Sources: JCGM 100:2008 (GUM) and JCGM 101:2008 (Supplement 1, Monte Carlo), both free from the
BIPM. Numbers below were computed with SciPy 1.18 in October 2026.

## 1. Budget template

One row per input quantity (or per component of one), sorted by contribution:

| Source | x_i | u(x_i) | Distribution, ν_i | c_i = ∂f/∂x_i | \|c_i\|·u(x_i) | % of u_c² |
|---|---|---|---|---|---|---|
| … | estimate | standard uncertainty | Type A (n − 1) or Type B (∞ or G.3) | at the estimates | contribution | (c_i u_i)²/u_c² |
| **Combined** | y | | ν_eff (Welch-Satterthwaite) | | u_c | 100 % |
| **Expanded** | | | k = t_p(ν_eff) | | U = k·u_c | |

Add correlation rows (pairs with r ≠ 0) underneath, or model the shared cause as its own row.

## 2. Filled example: pendulum g = 4π²L/T²

L = 1.000 m from a tape to the pivot plus the bob centre; T = 2.007 s from ten timings of ten
periods (s = 0.15 s for each 10-period timing). Sensitivities: c_L = g/L = 9.801 s⁻²,
c_T = −2g/T = −9.767 m s⁻³.

| Source | u(x_i) | ν_i | \|c_i\|·u_i (m/s²) | % of u_c² |
|---|---|---|---|---|
| T: 10 repeats of 10 T (Type A: 0.15/√10/10) | 4.74e-3 s | 9 | 0.0463 | 81.7 |
| L: pivot point ±4 mm (triangular, a/√6) | 1.63e-3 m | ∞ | 0.0160 | 9.8 |
| T: start/stop reaction asymmetry ±0.02 s on 10 T (rectangular) | 1.15e-3 s | ∞ | 0.0113 | 4.8 |
| L: bob centre of mass ±1.5 mm (rectangular) | 8.66e-4 m | ∞ | 0.0085 | 2.7 |
| L: tape tolerance ±0.5 mm (rectangular) | 2.89e-4 m | ∞ | 0.0028 | 0.3 |
| L: tape resolution 1 mm (δ/√12) | 2.89e-4 m | ∞ | 0.0028 | 0.3 |
| T: stopwatch resolution 0.01 s on 10 T (δ/√12) | 2.89e-4 s | ∞ | 0.0028 | 0.3 |
| **Combined** u_L = 1.9 mm, u_T = 4.9 ms | | ν_eff = 13.5 → 13 | **u_c = 0.0512** | |
| **Expanded** | | k(95.45 %, 13) = 2.21 | **U = 0.11** | |

g = 9.80 m/s², U = 0.11 m/s² (k = 2.21, p ≈ 95 %). With k = 2 the interval would be 0.10 and
under-cover, because one Type A line with ν = 9 dominates. Lines below 1 % of u_c² can be dropped
from the report but stay in the working file.

## 3. Type B source checklist

| Source | Typical information | Conversion |
|---|---|---|
| Calibration certificate | U and k (or p) | U/k |
| Manufacturer specification | ± (a % of reading + b digits) | a_total/√3 |
| Display resolution | one count δ | δ/√12 |
| Hysteresis (up versus down reading) | difference Δ | Δ/√12 |
| Drift since calibration | maximum drift ±d | d/√3 |
| Temperature effect | coefficient α × possible ΔT | α·ΔT_max/√3 (arcsine if cycling: /√2) |
| Cosine or alignment error | angle ≤ θ_max, bias always one-sided | correct by the mean bias, then u of the remainder |
| Reference data (handbook) | tabulated value, last digit | half a unit of the last digit, /√3 |
| Operator or model judgement | "within ±a, probably" | triangular a/√6, ν from G.3 |

ν for a Type B component: ν ≈ ½·(Δu/u)⁻² (GUM G.3): 10 % → 50, 20 % → 12, 25 % → 8, 50 % → 2.

## 4. Coverage factors t_p(ν)

| ν | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 12 | 15 | 20 | 30 | 50 | 100 | ∞ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 68.27 % | 1.84 | 1.32 | 1.20 | 1.14 | 1.11 | 1.09 | 1.08 | 1.07 | 1.06 | 1.05 | 1.04 | 1.03 | 1.03 | 1.02 | 1.01 | 1.01 | 1.00 |
| 90 % | 6.31 | 2.92 | 2.35 | 2.13 | 2.02 | 1.94 | 1.89 | 1.86 | 1.83 | 1.81 | 1.78 | 1.75 | 1.72 | 1.70 | 1.68 | 1.66 | 1.645 |
| 95 % | 12.71 | 4.30 | 3.18 | 2.78 | 2.57 | 2.45 | 2.36 | 2.31 | 2.26 | 2.23 | 2.18 | 2.13 | 2.09 | 2.04 | 2.01 | 1.98 | 1.96 |
| 95.45 % | 13.97 | 4.53 | 3.31 | 2.87 | 2.65 | 2.52 | 2.43 | 2.37 | 2.32 | 2.28 | 2.23 | 2.18 | 2.13 | 2.09 | 2.05 | 2.03 | 2.00 |
| 99 % | 63.66 | 9.92 | 5.84 | 4.60 | 4.03 | 3.71 | 3.50 | 3.36 | 3.25 | 3.17 | 3.05 | 2.95 | 2.85 | 2.75 | 2.68 | 2.63 | 2.576 |
| 99.73 % | 235.8 | 19.21 | 9.22 | 6.62 | 5.51 | 4.90 | 4.53 | 4.28 | 4.09 | 3.96 | 3.76 | 3.59 | 3.42 | 3.27 | 3.16 | 3.08 | 3.00 |

`scipy.stats.t.ppf(0.5 + p/2, nu)` reproduces any entry. GUM G.6.4: truncate a non-integer ν_eff
to the next lower integer (or interpolate).

## 5. Range of n normal readings (why max-min is not σ)

Expected range E[max − min] = d₂(n)·σ:

| n | 2 | 3 | 4 | 5 | 6 | 8 | 10 | 20 |
|---|---|---|---|---|---|---|---|---|
| d₂ | 1.128 | 1.693 | 2.059 | 2.326 | 2.534 | 2.847 | 3.078 | 3.735 |

If only a range R of n repeats survives, σ ≈ R/d₂(n) and u(mean) = σ/√n. Treating R itself as
u(mean) overstates it by d₂(n)·√n (5.2× for n = 5).

## 6. JCGM 101 adaptive Monte Carlo (§7.9.4)

```python
import math, numpy as np
def adaptive_mcm(model, sampler, p=0.95, ndig=2, rng=np.random.default_rng(1), hmax=200):
    M = max(math.ceil(100/(1 - p)), 10_000)           # batch size, step b)
    est, ys = [], []
    for h in range(1, hmax + 1):
        y = model(*sampler(rng, M)); ys.append(y)
        lo, hi = np.percentile(y, [50*(1 - p), 50*(1 + p)])
        est.append((y.mean(), y.std(ddof=1), lo, hi))
        if h == 1:
            continue
        s = np.std(est, axis=0, ddof=1)/math.sqrt(h)    # sd of the averages, steps g)-h)
        u = np.concatenate(ys).std(ddof=1)
        delta = 0.5*10**(math.floor(math.log10(u)) - ndig + 1)   # §7.9.2
        if np.all(2*s <= delta):                       # step k)
            yall = np.concatenate(ys)
            return h*M, yall.mean(), u, np.percentile(yall, [50*(1 - p), 50*(1 + p)])
    raise RuntimeError("not stabilised; raise hmax")

model = lambda L, T: 4*np.pi**2*L/T**2
sampler = lambda rng, M: (rng.normal(1.000, 0.002, M), rng.normal(2.007, 0.005, M))
print(adaptive_mcm(model, sampler, ndig=1))   # 20 000 trials, u = 0.052, [9.699, 9.903]
print(adaptive_mcm(model, sampler, ndig=2))   # 390 000 trials, u = 0.0526, [9.6984, 9.9048]
```

Validation of a GUM result against MCM (JCGM 101 §8.1): with y ± U from the GUM framework and
(y_low, y_high) from MCM, compute d_low = |y − U − y_low| and d_high = |y + U − y_high|. The GUM
result is validated at that coverage probability when both are ≤ δ.

## 7. Correlation from shared inputs

If inputs x_i and x_j both depend on a common quantity q (same reference standard, same
thermometer, same calibration constant), u(x_i, x_j) = (∂x_i/∂q)(∂x_j/∂q)·u²(q). Two results
calibrated against the same standard with relative u_s share r = u_s²/(u_i u_j) in relative
terms. GUM 5.2 and annex H.2 work through correlated cases (simultaneous resistance, reactance
and impedance measurements).
