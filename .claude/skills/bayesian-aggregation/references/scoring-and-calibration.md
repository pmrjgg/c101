# Scoring and calibration

How to measure whether an agent's probabilities deserve weight, how to correct them, and extended
worked cases. Binary events unless stated; p = forecast, o in {0, 1} = outcome, n = resolved count.

## Contents
- Proper scoring rules
- Brier decomposition
- Reliability diagram and ECE
- Comparing two agents
- Recalibration
- Choosing a weighting scheme
- Worked cases

## Proper scoring rules

A scoring rule is proper when reporting your true belief maximizes expected score; only proper
rules may be used to weight or rank forecasters.

| Rule | Per-question loss | Range | Character |
|---|---|---|---|
| Brier (quadratic) | (p - o)^2 | [0, 1] | bounded, forgiving of rare confident misses |
| Log loss | -ln(p) if o = 1, -ln(1 - p) if o = 0 | [0, inf) | punishes confident misses hard: p = 0.01 on a true event costs 4.6 nats |
| Multi-class Brier | sum_k (p_k - o_k)^2 | [0, 2] | K-way generalization |

Accuracy (fraction of p > 0.5 that came true) is NOT proper; never weight by it.
Skill relative to always forecasting the base rate: BSS = 1 - BS / (obar (1 - obar)).
BSS <= 0 means the agent adds nothing over the base rate.

## Brier decomposition

Group forecasts into bins k (or by distinct forecast value f_k), n_k items each, observed frequency
obar_k, overall base rate obar:

```
BS = REL - RES + UNC
REL = (1/n) sum_k n_k (f_k - obar_k)^2      reliability (calibration error; lower is better)
RES = (1/n) sum_k n_k (obar_k - obar)^2     resolution (discrimination; higher is better)
UNC = obar (1 - obar)                       uncertainty of the questions themselves
```

The identity is exact when forecasts take the discrete bin values. Use it diagnostically:
high REL means fixable by recalibration; low RES means the agent cannot tell cases apart, which
recalibration cannot fix (lower its weight instead).

Example (the agent 3 history in SKILL.md): forecasts 0.9 (20 items, 12 true) and 0.1 (20 items,
8 true). REL = 0.5 x (0.9 - 0.6)^2 + 0.5 x (0.1 - 0.4)^2 = 0.09. RES = 0.5 x 0.1^2 + 0.5 x 0.1^2
= 0.01. UNC = 0.25. BS = 0.09 - 0.01 + 0.25 = 0.33 (matches). Mostly a calibration problem:
recalibrate, and its resolution (0.01) still says it discriminates poorly.

## Reliability diagram and ECE

Bin forecasts (10 equal-width bins; 5 when n < 100; skip bins with fewer than 10 items), plot mean
forecast vs observed frequency, and compute

```
ECE = sum_k (n_k / n) |mean forecast_k - obar_k|
```

Curve below the diagonal at high p = overconfident (the LLM default); above = underconfident.

## Comparing two agents

Use paired per-question differences on the SAME questions: d_t = BS_A,t - BS_B,t,
t = mean(d) / (sd(d) / sqrt(n)). Example: n = 40, mean d = -0.05, sd 0.12, t = -2.64; critical
value about 2.02 at df = 39, so A is better beyond noise. With n < 20 shared questions, differences
under about 0.05 in Brier are not distinguishable; keep near-equal weights (shrinkage does this).

## Recalibration

Logistic recalibration on the logit scale, fitted by maximum likelihood (`pool.py recal`):

```
p' = sigmoid(a + b logit(p))
b < 1: overconfident, shrink toward 0.5      b > 1: underconfident
a > 0: forecasts too low on average          a < 0: too high
```

- Needs at least 30 resolved rows per agent (and model). Refit after a model change.
- Fit on older rows, check log loss on the newest 20%; keep the fit only if it improves.
- Recalibrate before pooling and before computing weights for the pool you will use.

## Choosing a weighting scheme

| Scheme | Formula | Use when |
|---|---|---|
| Equal | w = 1/M | no history, or n < 20 per agent |
| Skill (default) | max(0.05, BSS), shrunk with k = 20, capped 4:1 | 20+ resolved per agent |
| Hedge | exp(-eta T BS), eta = sqrt(8 ln M / T) | 50+ shared questions, agents stable |
| Tempered BMA | exp(-lambda x cumulative log loss), lambda = 0.5 | you believe one agent is close to right in general |
| Stacking | weights minimizing pooled log loss on history (grid search, M <= 5) | 100+ shared questions; most accurate, most prone to overfit |

## Worked cases

**Delphi round pooling.** Five experts, round 1 probabilities 0.20, 0.35, 0.40, 0.50, 0.80.
Median 0.40 (feedback to the panel with the IQR 0.35-0.50 and key arguments). Pools: linear 0.450,
log 0.449. Spread 0.60 triggers the crux rule: the 0.80 expert's argument goes to the panel
explicitly in round 2 instead of being averaged away. (`expert-panel-chair` runs rounds per
`delphi-method`.)

**Threshold decision that depends on the pool.** Ship if P(no regression) >= 0.80. Inputs 0.85,
0.90, 0.60, equal weights: linear 0.783 (do not ship), log 0.809 (ship). Drop-one sensitivity on
the log pool: without 0.60 it is 0.877, without 0.90 0.745, without 0.85 0.786. The decision
depends on both the pool and a single agent: do not decide by pooling. Ask the 0.60 agent for its
concrete concern and verify it (`tester`, `adversarial-verifier`); then re-elicit.

**Mediator log-pool vote.** Exclusive candidates S1..S4 with five voters' p_correct; normalize
each voter, take the weighted geometric mean per candidate, renormalize: 0.209 / 0.415 / 0.214 /
0.162 (the `mediator-voting` worked example). The margin P1 - P2 = 0.20 exceeds the 0.10 near-tie
threshold.

**Weights after a model upgrade.** The ledger shows `fact-checker` on sonnet with 60 rows from
before an upgrade and 12 after. Use `--since <upgrade date>`: 12 rows, so shrinkage keeps its weight
close to uniform until about 30 new rows accumulate; do not carry the old skill score over.
