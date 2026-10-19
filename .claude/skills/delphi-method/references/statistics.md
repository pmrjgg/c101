# Delphi statistics: formulas and interpretation

The [stats script](../scripts/delphi_stats.py) implements continuous, probability (including the
log-odds IQR rule) and ranking statistics. Compute by hand: likert and categorical consensus,
calibration sanity, and Kendall's W significance. Use the formulas when checking its output too.

## Location and spread (continuous, probability)

- Quartiles: inclusive / type-7 linear interpolation (numpy default, Python
  `statistics.quantiles(x, n=4, method="inclusive")`). For sorted x of size n, the q-quantile sits at
  position `h = (n - 1) * q` (0-based); interpolate between floor(h) and ceil(h).
- Example: x = 6, 8, 9, 10, 12, 16, 30. Q1 at h = 1.5: 8.5. Median at h = 3: 10. Q3 at h = 4.5: 14.
  IQR 5.5, relative IQR 0.55.
- Relative IQR = IQR / abs(median). Undefined at median 0; use an absolute tolerance from the caller.
- Report the sorted values for n <= 9; the eye catches clusters a summary hides.

## Stability

Per panelist i, relative move `m_i = abs(x_i(r) - x_i(r-1)) / abs(x_i(r-1))` (use 1 as denominator
when the old value is 0). Moved share = (number with m_i > 0.15) / (panelists present in both rounds).
Stable when moved share <= 0.15. With n = 7 that means at most one panelist moved more than 15%.

This individual-level rule catches a panel whose median is fixed while members swap positions,
which a median-shift rule would call stable. Also report the median shift
`abs(med(r) - med(r-1)) / abs(med(r-1))` for readers.

## Bimodality (explainable rule)

Sort the values; split at the largest gap g; low side L and high side H. Flag bimodal when
`len(L) >= 2`, `len(H) >= 2` and `g > max(range(L), range(H))`. Conservative by design: it ignores lone
dissenters (handled separately) and requires a gap wider than either cluster. For n >= 15 you may use
a kernel density estimate or Hartigan's dip test instead; keep the explainable rule in the report.

## Probabilities

Geometric mean of odds (equivalent to an unweighted logarithmic pool for a binary event):

```
o_i = p_i / (1 - p_i)
G   = exp( mean_i( ln o_i ) )
p   = G / (1 + G)
```

Example: p = 0.20, 0.30, 0.35, 0.40, 0.60 gives p = 0.361 (arithmetic mean 0.37, median 0.35).
Clip p to [1e-6, 1 - 1e-6] first. Extremizing (raising G to a power a > 1) helps only when panelists
hold independent information; same-model agent panels usually do not, so default a = 1. Weighted and
calibration-weighted variants: bayesian-aggregation.

For probabilities near 0 or 1 (the script switches when the median p50 is below 0.1 or above 0.9),
judge spread in log-odds: IQR of `ln o_i` <= 0.5 is roughly a factor of 1.65 in odds.

## Rankings: Kendall's coefficient of concordance W

m panelists rank n items (no ties). Let R_j be the sum of ranks item j received.

```
R_bar = m (n + 1) / 2
S     = sum_j (R_j - R_bar)^2
W     = 12 S / ( m^2 (n^3 - n) )          0 = no agreement, 1 = identical rankings
```

Example: m = 4, n = 4, rank sums a 5, b 8, c 12, d 15. R_bar = 10, S = 25 + 4 + 4 + 25 = 58,
W = 696 / 960 = 0.725 (strong by the Schmidt bands: 0.1 very weak, 0.3 weak, 0.5 moderate,
0.7 strong, 0.9 unusually strong).

Significance for small panels is weak evidence; for n > 7 items the chi-square approximation
`chi2 = m (n - 1) W` with n - 1 degrees of freedom is usable (Siegel, 1956); for fewer items use
exact tables (Siegel Table R) or a permutation test. Ties need a correction term; the
script rejects ties, so ask panelists for strict rankings.

## Likert and categorical

- Likert 1-5: consensus when IQR <= 1 and at least 70% of responses fall within two adjacent points.
  Report the full count per point; never report the mean of a Likert item as if interval-scaled.
- Categorical: consensus at >= 70% on one option (published Delphi studies use thresholds from 51%
  to 80%; state yours in the spec before round 1, never after seeing the data).

## Intervals

- Consensus interval: median of p10s, median of p90s (quantile averaging, robust form). Narrow;
  represents a typical panelist's uncertainty.
- Disagreement envelope: min p10, max p90. Wide; represents disagreement plus uncertainty.
- Calibration sanity: if fewer than ~60% of panelists' 80% intervals contain the final median, the
  panel's intervals are overconfident; widen the reported consensus interval or say so.

## Error correlation and effective size

`n_eff = n / (1 + (n - 1) rho)`. You rarely know rho; two cheap proxies:
- Round-1 spread vs the spread you would expect from the methods: near-identical answers from
  different methods suggest a shared anchor in the context files or model.
- Argument overlap: if more than ~70% of arguments fall into the same 2 clusters in round 1, treat
  the panel as low-diversity and say so in Caveats.
