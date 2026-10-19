# Merge and reduce

How to turn S shard outputs into one result without losing coverage information or inventing
agreement. Pick the strategy before launching; the worker item format must carry its fields.

## 1. Union + dedup (default for findings and sources)

```
seen = {}                                  # key -> merged item
for shard in shards_in_ledger_order:
    for item in shard.items:
        k = key(item)                      # see SKILL.md section 8
        if k not in seen:
            seen[k] = item | {shards: [shard.id]}
        else:
            m = seen[k]
            m.severity  = max(m.severity, item.severity)        # by ordinal: critical > high > medium > low
            m.scenario  = more_specific(m.scenario, item.scenario)  # the one with concrete inputs
            m.evidence  = union(m.evidence, item.evidence)
            m.shards   += [shard.id]
report: raw_count, unique_count, items sorted by (severity desc, len(shards) desc)
```

"More specific" = names concrete inputs, state, and observed wrong output. Prefer an item with a
reproduction command over one without. Agreement across shards (`len(shards) > 1`) is evidence,
but only weak evidence when the shards share a helper file that both read.

## 2. Quorum (redundant coverage)

Used when the same unit was covered by r workers on purpose (high-stakes units, or a decorrelated
mix of agents). Keep an item iff at least q of r report it.

| r | q | Use |
|---|---|-----|
| 2 | 1 | recall-oriented sweep (keep anything either found), then verify |
| 3 | 2 | balanced; standard for shipped findings |
| 5 | 3 | precision-oriented, expensive; security sign-off |

Decorrelate the r workers by agent (different tiers or disciplines, e.g. `reviewer` ADVANCED +
`code-quality-analyst` MEDIUM) and by framing; per-call model/effort is stripped by the pre-agent hook.
Identical briefs to the same agent mostly agree on the same mistakes.

## 3. Reciprocal rank fusion (ranked lists)

`score(d) = sum over lists i containing d of 1 / (k + rank_i(d))`, with k = 60 and ranks from 1.

Worked example, three shards ranking sources:

| Source | rank in A | rank in B | rank in C | score |
|--------|-----------|-----------|-----------|-------|
| X | 1 | 3 | - | 1/61 + 1/63 = 0.03227 |
| Y | 2 | 1 | 2 | 1/62 + 1/61 + 1/62 = 0.04865 |
| Z | - | 2 | 1 | 1/62 + 1/61 = 0.03252 |

Fused order: Y, Z, X. Items appearing in many lists win over a single first place, which is the point.

## 4. Argmax with confirmation (hypotheses, grids)

1. Rank by the metric. Compute run-to-run spread from repeated runs of one point (or from the
   workers' reported variance).
2. If the winner's margin over the runner-up is below 2x the spread, re-run both (3 runs each) and
   compare medians.
3. Re-run the final winner once on a fresh worker to confirm it reproduces.
4. Report the winner, the margin, the spread and n. For hypotheses: the confirming test output.

## 5. Statistical reduce (numbers)

| Quantity | Report | Formula |
|----------|--------|---------|
| Latencies, timings | median and IQR | robust to outliers; also p95 when tails matter |
| Counts, rates | mean and 95% CI | `mean +/- t * s / sqrt(n)`; t = 1.96 for n >= 30, 2.776 for n = 5, 2.262 for n = 10 |
| Proportions | p and Wilson interval | prefer Wilson over normal approximation for small n or p near 0 or 1 |

Always keep n. Never average medians from shards of different sizes without weighting; merge the raw
samples instead when they are available in the shard files.

## 6. Tree reduce (large merges)

When the concatenated shard outputs exceed about 60k tokens, one merge agent will skim. Reduce in
levels:

```
branching b = 4..6 shard outputs per merge agent
levels      = ceil(log_b(S))          S=25, b=5 -> 2 levels (5 merges, then 1 final)
spawns      = ceil(S/b) + ceil(S/b^2) + ... + 1
```

Merge brief (each level):

```
MERGE inputs: <list of shard result files with line anchors>
KEY: <dedup key definition>; STRATEGY: <union+dedup | quorum q of r | RRF>
KEEP per item: key fields, max severity, most specific scenario, union of evidence, contributing shard ids
CONFLICTS: if two inputs contradict on the same key, keep both under CONFLICTS with evidence; do not choose
WRITE: .stack/out/<agentType>/<swarm-slug>/merge-L<level>-<group>.md
RETURN: counts (raw, unique, conflicts), path, and the ids of inputs you could not read
```

Use `file-summarizer` (LOW tier) for intermediate levels (mechanical); do the final level yourself, or
hand it to an ADVANCED agent such as `cross-domain-synthesizer` only if it must also write prose.

## 7. Conflict list

```
| key | shard A says | evidence A | shard B says | evidence B | route |
|-----|--------------|------------|--------------|------------|-------|
| pkg/pool/pool.go::Get::leak | leak on ctx cancel | test log line 88 | no leak, Close drains | pool.go:141 | adversarial-verifier |
```

Route by doubt type: factual -> `fact-checker`, runtime behaviour -> `tester`, contested reasoning ->
`adversarial-verifier`, judgment call -> the caller. Unresolved conflicts go to Open doubts.
