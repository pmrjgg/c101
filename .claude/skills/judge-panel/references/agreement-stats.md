# Agreement statistics for judge panels

What `scripts/panel.py` reports, how it is computed, and what to do with it. m = number of judges,
n = number of candidates.

## Contents
- Which statistic answers which question
- Kendall's W (rank agreement)
- Krippendorff's alpha, interval metric (score agreement)
- Paired differences (is the winner really ahead)
- Disagreement flags
- Worked computation on the SKILL.md example

## Which statistic answers which question

| Question | Statistic | Uses |
|---|---|---|
| Do judges order the candidates the same way? | Kendall's W on per-judge totals | choosing a winner |
| Do judges give the same absolute scores? | Krippendorff's alpha (interval) over cells | reporting scores, reusing a rubric |
| Is the winner ahead for every judge, beyond judge noise? | paired deltas and paired t | decisiveness |
| Where exactly do judges diverge? | per-cell range | reconciliation targets |

High W with low alpha is common: judges differ in leniency but agree on order. That is acceptable
for picking a winner and unacceptable for publishing absolute scores.

## Kendall's W

Each judge ranks the candidates by its own weighted total (rank 1 = best, ties get the average rank).
R_c = sum of ranks of candidate c over judges; mean R = m(n+1)/2.

```
S = sum_c (R_c - m(n+1)/2)^2
T_j = sum over tie groups in judge j's ranking of (t^3 - t)
W = 12 S / (m^2 (n^3 - n) - m * sum_j T_j)
```

W is 1 for identical rankings and 0 for no agreement. Large-sample test: chi2 = m(n-1)W with n-1
degrees of freedom (only meaningful for n >= 7; for panels of 3-5 candidates read W descriptively).

| W | Reading | Action |
|---|---|---|
| < 0.3 | weak | the rubric does not discriminate or candidates are near-equivalent: fix anchors, merge candidates, or add a criterion that matters |
| 0.3-0.6 | moderate | proceed only if decisive; report the spread |
| >= 0.7 | strong | proceed |

## Krippendorff's alpha (interval)

Units u are candidate x criterion cells; each holds the m_u judge scores (cells with fewer than 2
scores are dropped). n_v = total number of pairable values.

```
D_o = (1 / n_v) * sum_u [ sum_{i != j in u} (x_ui - x_uj)^2 / (m_u - 1) ]
D_e = (1 / (n_v (n_v - 1))) * sum_{a != b over all pairable values} (x_a - x_b)^2
alpha = 1 - D_o / D_e
```

Krippendorff's conventional thresholds: alpha >= 0.800 reliable; 0.667-0.800 only tentative
conclusions; below 0.667 do not rely on the absolute scores. Alpha can be negative (systematic
disagreement), which usually means two judges read an anchor in opposite directions.

Check value: units [1,1], [2,2], [3,3], [3,4] give alpha = 1 - 0.25 / 2.25 = 0.889.

## Paired differences

For winner w and runner-up r, per judge: delta_j = T_j(w) - T_j(r). Mean delta over judges, its
standard deviation s and t = mean / (s / sqrt(m)), df = m - 1. Two-sided 5% critical values:
4.30 (m = 3), 3.18 (m = 4), 2.78 (m = 5), 2.45 (m = 7). With m = 3 the test has little power, so
the operational rule is: decisive = every delta_j > 0 AND aggregated margin >= 5 points.
Pairing removes judge leniency: a lenient judge raises both totals, not the difference.

## Disagreement flags

A cell is flagged when max - min of judge scores >= 2 on a 1-5 scale (use about 40% of the scale
for other scales). Only flags that could change the top-2 order or a graft decision need
reconciliation; a flag on a candidate that cannot reach the top 2 is reported and left alone.

## Worked computation (SKILL.md example)

Per-judge totals (0-100):

| | P1 | P2 | P3 |
|---|---|---|---|
| J1 | 70.00 | 81.25 | 56.25 |
| J2 | 53.75 | 71.25 | 56.25 |
| J3 | 61.25 | 73.75 | 43.75 |

Ranks: J1 (2, 1, 3), J2 (3, 1, 2), J3 (2, 1, 3). R = (7, 3, 8), mean R = 3 x 4 / 2 = 6.
S = 1 + 9 + 4 = 14. No ties, so W = 12 x 14 / (9 x (27 - 3)) = 168 / 216 = 0.778.

Paired deltas P2 - P1: 11.25, 17.50, 12.50; mean 13.75, s = 3.31, t = 13.75 / (3.31 / 1.732) = 7.2
(above 4.30): decisive by both the statistical and the operational rule.

Alpha over the 15 cells = 0.616: the judges agree on the order (W 0.78) but not on absolute
levels. Quote ranks and margins; tighten the anchors of the criteria with the widest ranges before
the rubric is reused.
