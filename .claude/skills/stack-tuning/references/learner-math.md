# Learner math, with a fully worked example

All numbers below were produced by running `stack/learn/model.py` on the example data, so you can
reproduce them with `python3 scripts/tune_tool.py whatif` on equivalent observations.

## 1. Turns: censored log-normal on a grid

Observation i: y_i = log(tool_rounds_i) (responses that called at least one tool, the unit `maxTurns`
limits; called "turns" below and in the report), weight w_i = gamma^(n-1-i) (oldest first). A run that hit its
cap c_j is right-censored: we only know turns >= c_j.

```
log p(mu, sigma | data) = log prior(mu, sigma)
    + sum_exact  [ -w_i log sigma - w_i (y_i - mu)^2 / (2 sigma^2) ]
    + sum_capped [  w_j log(1 - Phi((log c_j - mu) / sigma)) ]
prior: mu ~ N(log(maxTurns_cur / prior_limit_ratio), log(prior_spread))   # config: 3.0, 2.5 (the worked example below uses 4.0)
       log sigma ~ N(log 0.6, 0.6)
       (no current maxTurns: centre on prior_turns_typical = 12)
```

Grid: 48 values of mu spanning prior mean +- 4 prior sd, widened to [min(y) - 1.5, max(y) + 2.5];
28 values of sigma log-spaced over [0.05, 2.5]. The posterior is normalised on the grid; the
predictive CDF is the posterior-weighted mixture of normal CDFs on the log scale, and quantiles
are found by bisection.

Why censoring matters: treating capped runs as "needed exactly the cap" anchors the estimate at
the cap, so a too-low cap would never rise. As survival terms, capped runs push mass upward.

## 2. Worked example (rust-expert, maxTurns 80, effort high)

14 runs, oldest first:

| run | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| turns | 22 | 31 | 18 | 45 | 80 cap | 27 | 39 | 80 cap | 52 | 33 | 61 | 80 cap | 29 | 44 |
| output tokens (k) | 21 | 30.5 | 12 | 52 | 88 | 26 | 41 | 95 | 47 | 33 | 60 | 91 | 24 | 39 |

Data window: prequential scores for gamma 1.0 ... 0.85 were all within 0.13 nats (-46.50 to
-46.37); within the 1.5-nat tolerance the longest memory wins, so gamma = 1.0, effective runs 14.

Config used: `prior_limit_ratio` 4.0 (overridden; shipped 3.0 gives q95 133.9, rec 154), `prior_spread` 2.5, other keys as shipped (2026-10-19).

Prior: typical = 80 / 4.0 = 20, so mu0 = ln 20 = 2.996, prior sd of mu = ln 2.5 = 0.916.

Posterior: E[mu] = 3.763 (e^3.763 = 43.1 rounds), E[sigma] = 0.645. The 14 runs dominate the
prior: with `prior_limit_ratio` 2.5 (prior centre 32) the q95 would be 135.1 instead of 132.1.
Predictive quantiles: q50 43.0, q90 100.7, q95 132.1.
Same data with the three capped runs treated as exact 80: q50 40.5, q90 80.3, q95 99.1, which
would recommend only ceil(99.1 x 1.15) = 114.

maxTurns:
```
ceil(132.1 x 1.15) = ceil(151.9) = 152
step clamp: [floor(80/2), ceil(80 x 2)] = [40, 160]   -> 152
bounds:     default [5, 1000]                         -> 152   (with bounds [40, 120] -> 120)
hysteresis: |152 - 80| = 72 >= max(2, 0.10 x 80 = 8)  -> recommend 152
```

Effort. Bands by output tokens: low < 4k, medium < 16k, high < 48k, xhigh < 120k, max >= 120k.
Counts (gamma 1): low 0, medium 1, high 8, xhigh 5, max 0.

```
prior alpha = 0.5 each + 3.0 stickiness on current (high) = [0.5, 0.5, 3.5, 0.5, 0.5]
posterior   = [0.5, 1.5, 11.5, 5.5, 0.5], sum 19.5
predictive  = [0.026, 0.077, 0.590, 0.282, 0.026]
cumulative  = [0.026, 0.103, 0.692, 0.974, 1.000]  -> smallest level with >= 0.80 is xhigh
P(fail): Beta(1 + 3, 4 + 11) = Beta(4, 15); mean 4/19 = 0.211 (< 0.25, no escalation); q90 0.334
one level per update from high -> xhigh allowed; bounds [low, max] -> xhigh
```

Token budget (example with output_max_turn q95 = 19,800 and ctx_peak q95 = 237,964):
```
max_output_tokens = clamp(ceil(19,800 x 1.15 / 1000) x 1000, 8,000, 128,000) = 23,000
recommend_1m_context = 237,964 > 0.8 x 200,000 = 160,000 -> true
```

## 3. Data window (forgetting factor)

For each gamma in {1.0, 0.99, 0.97, 0.94, 0.90, 0.85} and each of the last 12 runs t, fit the
posterior on runs before t (weights gamma^age, coarser 32 x 20 grid) and score run t: log
predictive density if exact, log predictive survival if capped. Sum over the 12 runs. Choose the
largest gamma whose score is within 1.5 nats of the best (a one-standard-error style rule: shorten
memory only on clear evidence of drift). Fewer than 8 runs: gamma = 1.

Effective runs with n = 50:

| gamma | 1.0 | 0.99 | 0.97 | 0.94 | 0.90 | 0.85 |
|---|---|---|---|---|---|---|
| effective runs | 50 | 39.5 | 26.1 | 15.9 | 9.9 | 6.7 |

Interpretation: gamma 0.90 means the posterior is driven by roughly the last 10 runs. After a
deliberate change (new prompt, different model) that is what you want; without one, find out what
changed in the task mix.

Note that gamma also weights the effort counts and failure counts, and `n_eff` (the sum of
weights) is what is compared with `min_obs_turns` and `min_obs_effort`, so a short window can
push an agent back below the evidence threshold.

## 4. Token windows

For each metric (output_tokens, tokens_total, ctx_peak, output_max_turn) with any positive
values: log-normal grid posterior with a prior centred on the observed median (spread factor 4),
same gamma weights, no censoring. Reported `[min, median, max]` = predictive [q05, q50, q95].

## 5. Sensitivity cheatsheet

| Change | Effect on the example |
|---|---|
| `turns_quantile` 0.95 -> 0.90 | 152 -> 116 (q90 100.7 x 1.15 = 115.8, ceil 116) |
| bounds maxTurns [40, 120] | 152 -> 120 |
| bounds effort [medium, high] | xhigh -> high |
| more capped runs | q95 rises further. Escalation needs (1 + caps) / (5 + runs) > 0.25, i.e. caps > (runs + 1) / 4 (gamma 1): with 15 runs, 4 caps give exactly 0.25 (no escalation), 5 caps give 6/20 = 0.30 (escalate) |
| `prior_limit_ratio` 4.0 -> 2.5 | prior centre 32 rounds; q95 132.1 -> 135.1, recommendation 152 -> 156 |

Check any of these on real data with `tune_tool.py whatif --agent A --set key=value --bounds ...`.
