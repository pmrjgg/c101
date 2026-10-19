# Benchmark statistics

## Why medians and bootstrap

Benchmark timings are right-skewed (interrupts, GC, page faults add time, nothing subtracts it) and
often multimodal (frequency states, cache alignment). Means and t-tests assume roughly normal noise;
medians with bootstrap confidence intervals do not. For microbenchmarks where noise is purely
additive, the minimum is also a stable estimator of the "true" cost, but it hides real variability
(GC, contention) that users experience; report it next to the median, not instead of it.

## Quantities to report

| Quantity | Formula | Use |
|---|---|---|
| Median | middle value | central tendency |
| 95% CI of the median | bootstrap percentile interval | precision of the estimate |
| Coefficient of variation | CV = sd / mean | noise level; > 5% on microbenchmarks means fix the environment |
| Ratio of medians | r = median(after) / median(before) | effect; r < 1 is faster when lower is better |
| 95% CI of the ratio | bootstrap: resample both sides, recompute r, take 2.5th and 97.5th percentiles | the claim |
| Speedup | 1 / r | communication only; compute CI on r, then invert the bounds |
| Mann-Whitney U p-value | rank-sum test | secondary check that the distributions differ |

## Sample size

To detect a relative difference d between two variants with noise CV, two-sided alpha = 0.05 and
power 0.8, per-variant sample size is approximately:

```
n ~= 2 (z_0.975 + z_0.8)^2 (CV / d)^2 = 2 (1.96 + 0.84)^2 (CV / d)^2 ~= 15.7 (CV / d)^2
```

| CV \ effect d | 1% | 2% | 5% | 10% |
|---|---|---|---|---|
| 1% | 16 | 4 (use >= 10) | 1 (use >= 10) | 1 (use >= 10) |
| 3% | 142 | 36 | 6 (use >= 10) | 2 (use >= 10) |
| 5% | 393 | 99 | 16 | 4 (use >= 10) |
| 10% | 1570 | 393 | 63 | 16 |

Floor at 10 runs per variant so the bootstrap has something to resample. If n is impractical, reduce
CV (environment control, longer iterations, more items per iteration) rather than lowering standards.

## Bootstrap CI (procedure)

1. Inputs: samples A (before) and B (after).
2. Repeat B_rep = 10,000 times: draw |A| values from A with replacement and |B| from B with replacement;
   compute r* = median(B*) / median(A*).
3. Sort the r* values; the 250th and 9,750th are the 95% CI bounds.
4. Fix the RNG seed and report it, so the CI is reproducible.

`scripts/compare_bench.py` does exactly this (and the per-variant median CIs, CV and Mann-Whitney U).

## Decision rule

Let t be the practical threshold (default 3%; pick it before measuring).

| CI of r (lower is better) | Point effect | Verdict |
|---|---|---|
| Entirely below 1 | 1 - r >= t | Improved |
| Entirely above 1 | r - 1 >= t | Regressed |
| Inside [1 - t, 1 + t] | any | No practical change |
| Anything else | any | Inconclusive: more samples or less noise |

A statistically significant 0.4% change is real but usually not worth complexity; the threshold
encodes that judgement up front.

## Multiple comparisons

Comparing many benchmarks at once (a CI suite of 200 benchmarks) at 95% confidence yields about 10
false "changes" by chance. Options:
- Bonferroni: use a 1 - 0.05/k confidence level for k comparisons (very conservative).
- Benjamini-Hochberg on the Mann-Whitney p-values to control the false discovery rate at 5%.
- Practical: require the change to reproduce on a second, independent run before acting.

## Tail latency

- Percentile estimation needs samples beyond the percentile: p99 from 1,000 samples rests on about 10
  observations; p99.9 needs 10,000+. Report the sample count with every tail number.
- Never average percentiles across hosts or time windows; merge histograms (HdrHistogram supports
  lossless merging) and recompute.
- Open-model load (fixed arrival rate) is required to see queueing; closed-model tools suffer from
  coordinated omission.
- Report p50, p90, p99, p99.9 and max, plus throughput achieved (not just offered).

## Drift and ordering

- Run variants interleaved: A B A B ... or randomized blocks. Sequential "all A then all B" confounds the
  change with thermal state, background tasks, and cache warmth.
- Watch for trends inside a run (plot time vs iteration index); a monotonic trend means warmup was too
  short or the machine is throttling.
- When comparing revisions, build both with the same toolchain in the same session; toolchain upgrades
  between builds invalidate the comparison.

## Worked example

Before: 40 runs, median 412.3 ms, CV 1.1%. After: 40 runs, median 268.9 ms, CV 0.9%.
Bootstrap (10,000 replicates, seed 1): r = 0.652, 95% CI [0.646, 0.659]. The CI excludes 1 and
1 - r = 34.8% >= 3%: Improved, 1.53x faster (CI of speedup [1.517, 1.548], inverted bounds).
Mann-Whitney p < 1e-10 agrees. Sample size check: CV ~1%, effect 35%: n of 10 per side would have
sufficed; 40 gives tight intervals for the report.
