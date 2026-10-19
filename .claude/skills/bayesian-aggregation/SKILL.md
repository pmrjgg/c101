---
name: bayesian-aggregation
description: "Combining probabilistic judgments from several agents into one calibrated probability or distribution: verbal-to-numeric conversion, linear vs logarithmic opinion pools, extremizing, weights from calibration history (Brier and log score, shrinkage, Hedge), Bayesian model averaging, recalibration, correlated experts and effective N, multi-outcome and quantile pooling, with a stdlib script and worked numeric examples. Load whenever you merge probabilities, confidences or estimates from multiple agents."
when_to_use: "Mediator log-pool votes, Delphi estimate rounds, synthesizing expert confidences, weighting agents by track record, deciding whether agreement among same-model agents is real evidence. Not for ranking artifacts (judge-panel) or choosing among answers by ballots alone (mediator-voting)."
---

# Bayesian aggregation

Several agents gave probabilities for the same event. The pooled number must be better than any
single input on average, honest about disagreement, and not fooled by five copies of the same model
agreeing with itself. The procedure: make the inputs comparable, pick the pool, weight by track
record, correct for correlation, extremize only when justified, sanity-check, report.

Tool: [scripts/pool.py](scripts/pool.py) (stdlib Python 3.9+, JSON output):

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
P="$STACK/.claude/skills/bayesian-aggregation/scripts/pool.py"
python3 "$P" binary --p 0.6 0.7 0.9 [--w ...] [--d 1.5]
python3 "$P" multi --dist 0.5,0.3,0.2 0.6,0.3,0.1 --labels A,B,C
python3 "$P" clusters --p 0.9 0.9 0.6 --cluster m1 m1 m2 --rho 0.8
python3 "$P" weights --ledger .stack/calibration/ledger.jsonl [--scheme skill|hedge]
python3 "$P" recal --ledger .stack/calibration/ledger.jsonl --agent fact-checker
python3 "$P" neff --n 5 --rho 0.6
python3 "$P" verbal "very likely" "roughly even chance"
python3 "$P" quantiles --q 80,120,200 100,150,260 90,130,400 --levels 0.1,0.5,0.9
```

## 1. Preconditions: is pooling even legitimate?

- [ ] **Same question, same resolution criterion.** "Ships by June 30" and "ships in Q2" are
      different events. Rewrite every input against one resolution sentence, or do not pool.
- [ ] **Same outcome space.** For multi-outcome questions all agents use the same exhaustive,
      mutually exclusive list (add "other" if needed).
- [ ] **No decisive private evidence.** If one agent holds a proof, a passing test or a primary
      source that settles the question, use that evidence; a poll does not outvote a proof.
- [ ] **Inputs are independent judgments**, not one agent's number copied by others (check
      whether briefs or sources were shared; that is correlation, section 5).

## 2. Get numbers

1. Ask for numeric probabilities in the brief ("p in [0.02, 0.98], two decimals"). Verbal
   confidence is the fallback, not the format.
2. If only words exist, convert with ICD 203 band midpoints (full tables, Kent and IPCC scales,
   and LLM phrasing notes in [verbal probability](references/verbal-probability.md)):

| Phrase | p | Phrase | p |
|---|---|---|---|
| almost no chance / remote | 0.03 | likely / probable | 0.67 |
| very unlikely | 0.12 | very likely | 0.87 |
| unlikely / probably not | 0.32 | almost certain(ly) | 0.97 |
| roughly even chance | 0.50 | | |

3. Clip every input to [0.02, 0.98]. One 0 or 1 makes the log pool undefined or dictatorial, and
   LLM extremes are the least calibrated region.
4. If the agent has a recalibration fit (section 4), apply it now: `p' = sigmoid(a + b logit(p))`.

## 3. Choose the pool

Notation: weights w_i >= 0 summing to 1, logit(p) = ln(p / (1 - p)), sigmoid is its inverse.

| Pool | Binary formula | Behaviour |
|---|---|---|
| Linear | P = sum_i w_i p_i | Never outside [min p_i, max p_i]; bounded influence of any one agent; preserves tail risk; under-confident when agents hold independent evidence |
| Logarithmic (geometric mean of odds when equal weights) | logit P = sum_i w_i logit p_i | Sharpens when agents agree; externally Bayesian (pool-then-update equals update-then-pool); one confident outlier moves it a lot |
| Extremized log | logit P = d * sum_i w_i logit p_i, d > 1 | Compensates for each agent seeing only part of the evidence; harmful when agents share evidence |
| Multi-outcome log | P_k proportional to prod_i p_ik^(w_i) | as log pool, normalize over k |

Decision table:

| Situation | Use |
|---|---|
| Default for agent panels (after clipping and recalibration) | log pool, d = 1; report the linear pool beside it |
| Decision hinges on a rare, costly outcome (tail risk) | linear (the log pool drowns one dissenting 0.2 among several 0.01s) |
| One input is suspect (possible hallucination, off-scope) | linear, or drop the input after verifying why |
| Agents used different evidence (different sources, tools, data) and N_eff >= 2 | log pool, consider extremizing (section 6) |
| Agents are the same model on the same evidence | linear or log with d = 1, effective-N weights; never extremize |
| You must later update the pooled belief with shared new evidence | log pool |

## 4. Weights from calibration history

Without a track record use equal weights. Do not weight by self-reported confidence; that is
already inside the probabilities.

With resolved history (ledger format in section 9), per agent type (and model, if it varies):

```
Brier         BS_i  = (1/n_i) sum_t (p_t - o_t)^2
Reference     BS_ref = obar (1 - obar)            # always forecasting the base rate obar
Skill         BSS_i = 1 - BS_i / BS_ref
Raw weight    r_i   = max(0.05, BSS_i), normalized to sum 1
Shrinkage     w_i   = (n_i r_i + k / M) / (n_i + k)    # k = 20 pseudo-questions, M agents
Cap           no weight below max_j(w_j) / 4, then renormalize
```

- `pool.py weights --scheme skill` implements exactly this. With 50+ shared questions,
  `--scheme hedge` uses exponential weights w_i proportional to exp(-eta T BS_i) with
  eta = sqrt(8 ln M / T), the standard Hedge rate for losses in [0, 1].
- **Bayesian model averaging**: treating agents as models with a uniform prior, the posterior
  weight is proportional to the product of the probabilities each assigned to what actually
  happened, i.e. exp(-cumulative log loss). It concentrates on one agent fast (a 2-nat gap gives a
  7.4:1 ratio) and assumes one agent is "true". Use it tempered (exponent 0.5) and still capped, or
  prefer the skill-score weights above.
- **Recalibration** (`pool.py recal`, needs >= 30 resolved rows): fit logit(p') = a + b logit(p).
  b < 1 means overconfident (typical for LLMs), a != 0 means biased. Apply before pooling;
  recalibrated agents need smaller weight differences.
- Always state weights and their source in the report.

## 5. Correlated agents

Agreement among correlated agents is weaker evidence than it looks.

```
Effective number of independent agents:  N_eff = N / (1 + (N - 1) rho)
```

rho = average pairwise correlation of the agents' errors. From history: correlation of their logit
errors on shared resolved questions. Without history use priors:

| Relationship | rho prior |
|---|---|
| Same model and same sources/brief | 0.8 |
| Same model, different perspective prompts | 0.6 |
| Different model families, shared sources | 0.4 |
| Different models and different evidence | 0.2 |

N = 5, rho = 0.6 gives N_eff = 1.47: five same-model voters are worth about one and a half.

**Cluster-then-pool**: group agents by (model family, evidence base). Log-pool within each cluster,
give the cluster effective weight sum(w) x N_eff(m) / m, then log-pool across clusters
(`pool.py clusters`). Self-consistency samples of one agent form one cluster with rho near 0.9.

## 6. Extremize or not

Extremizing (d > 1) is justified when each agent saw only part of the total evidence, so the
average of partially informed opinions is too timid. Forecasting-tournament research found it
helps aggregates of diverse human forecasters; LLM panels are often the opposite case (shared
training and shared retrieved sources).

| Condition | d |
|---|---|
| N_eff < 1.5, or agents share their sources | 1.0 |
| Different models, same evidence | 1.0-1.2 |
| Different evidence bases (each agent researched separately), N_eff >= 2 | 1.2-1.5 |
| Fitted on at least 30 resolved pooled questions | the d that minimizes log loss on that history |

These priors are heuristics; replace them with a fitted d as soon as history allows. Never
extremize a pool whose inputs span more than 0.4.

## 7. Multi-outcome and continuous quantities

- **K exclusive outcomes**: normalize each agent's vector, pool with `pool.py multi` (linear and
  log). Never pool marginals of one outcome while ignoring the others.
- **Quantile estimates** (10/50/90): average the quantiles level by level (Vincentization) for a
  consensus of similar shape; use the per-level median when one agent is an outlier. A linear pool
  of the distributions instead keeps every agent's mass and is wider; prefer it when the tails drive
  the decision. Report the envelope (min and max per level) either way.
- For point estimates with uncertainty, collect quantiles, not a point plus "confidence".

## 8. Sanity checks and disagreement

- [ ] Linear pool lies within [min, max]; a log pool outside it must come from deliberate d > 1.
- [ ] Spread = max - min. Spread >= 0.4: do not just report a pool. Find the crux (the
      sub-claim on which the agents disagree) and send it to `fact-checker`, `adversarial-verifier`,
      or a `structured-debate`; re-elicit after the crux is resolved.
- [ ] Linear vs log gap > 0.1: the inputs are heterogeneous; say which you used and why.
- [ ] Check that no single agent carries more than 50% of the weight unless justified by history.
- [ ] Sensitivity: drop each agent once; if the pooled p crosses a decision threshold, say so.

## 9. Calibration ledger

Location: `.stack/calibration/ledger.jsonl` (runtime artefact, gitignored with `.stack/`). Append
one line when a pooled question resolves, one per contributing agent:

```json
{"agent": "fact-checker", "model": "sonnet", "qid": "2026-10-19-pg17-merge", "p": 0.8, "outcome": 1, "resolved": "2026-10-21"}
```

- Keep pending predictions with their `qid` in your run directory; append only on resolution.
- Resolution sources: test or validator results, adversarial-verifier verdicts at E3+, later facts.
  A resolution decided by another LLM's opinion is not a resolution.
- Rows are binary. A K-way question becomes K one-vs-rest rows ("outcome k happened": 1 or 0),
  qids suffixed `#k`; their sum of squared errors is the multi-class Brier score. The K rows are
  correlated, so count the question once when judging whether n is large enough.
- Use `--since` to forget old behaviour after a model change.

## 10. Worked examples (all reproducible with pool.py)

**A. Three agents, equal weights.** p = 0.60, 0.70, 0.90.
Linear 0.733. Log pool: odds 1.5, 2.33, 9.0, geometric mean 3.16, P = 0.760. Extremized d = 1.5:
P = 0.849 (only if the three researched independently).

**B. Same inputs with track records.** Ledger over 40 resolved questions each, base rate 0.5
(BS_ref = 0.25): agent 1 Brier 0.1275 (BSS 0.49), agent 2 0.23 (0.08), agent 3 0.33 (-0.32,
floored to 0.05). Raw weights 0.790 / 0.129 / 0.081; shrunk with k = 20: **0.638 / 0.197 / 0.165**.
Pooled: linear 0.669, log 0.687. The best-calibrated agent said 0.6, so the pool moves down from
0.76 to 0.69.

**C. Recalibration.** Agent 3 said 0.9 on 20 questions and was right on 12, and 0.1 on 20 and was
wrong on 8. Fit: a = 0.00, b = 0.18. Its 0.9 becomes sigmoid(0.18 x 2.197) = 0.60.

**D. Correlated pair.** Two same-model agents say 0.9 (rho 0.8), a different-model agent says 0.6.
Naive equal log pool 0.832. Cluster-aware: the pair has N_eff = 2 / 1.8 = 1.11, weight 1.11 vs
1.00, P = **0.794**.

**E. Three outcomes.** Agents give (0.5, 0.3, 0.2), (0.6, 0.3, 0.1), (0.2, 0.5, 0.3) for A, B, C.
Linear (0.433, 0.367, 0.200); log (0.422, 0.383, 0.196). A leads under both; the log pool narrows
A's lead because one agent strongly preferred B.

**F. Latency quantiles (ms, 10/50/90).** (80, 120, 200), (100, 150, 260), (90, 130, 400).
Vincentized (90, 133, 287); per-level median (90, 130, 260); envelope at p90: 200-400. The p90
disagreement is the crux; ask the 400 ms agent for its tail mechanism before committing to an SLO.

**G. BMA concentration.** Cumulative log loss over 20 questions: agent X 8.0 nats, agent Y 10.0.
Plain BMA weights 0.881 / 0.119 (ratio e^2); tempered with exponent 0.5: 0.731 / 0.269.

More cases (Delphi round pooling, mediator log-pool vote, threshold decisions):
[scoring and calibration](references/scoring-and-calibration.md#worked-cases).

## 11. Failure modes

| Failure | Countermeasure |
|---|---|
| Pooling different questions | single resolution sentence (section 1) |
| Five same-model agents treated as five opinions | effective N, cluster-then-pool |
| Extremizing shared-evidence agents | d = 1 unless evidence bases differ |
| Zero or one probabilities | clip to [0.02, 0.98] |
| Confidence counted twice (as p and as weight) | weights only from history |
| Weights fitted on 5 questions | shrinkage k = 20, cap 4:1, minimum 30 rows for recalibration |
| Averaging away a real disagreement | spread rule, crux resolution |
| Tail risk erased by geometric pooling | linear pool for tail-driven decisions |
| LLM-judged "resolutions" in the ledger | only test, validator, E3+ verification or real-world outcomes |

## 12. Output

```markdown
## Result
P(event) = 0.69 (log pool, calibration weights 0.64/0.20/0.16, d = 1); linear pool 0.67.
Inputs 0.60 / 0.70 / 0.90, spread 0.30. Effective N 2.4. Decision threshold 0.5: robust to dropping any agent.
## Evidence
Input table (agent, model, raw p, recalibrated p, weight, weight source), pool comparison, sensitivity.
## Files
Run file with inputs and pool.py output; ledger rows appended (if resolved).
## Open doubts
The crux if spread >= 0.4; missing history (equal weights used).
## Confidence
The pooled probability IS the answer; confidence here is about the inputs' quality and independence.
```

## References

- [Scoring and calibration](references/scoring-and-calibration.md): proper scoring rules, Brier
  decomposition, reliability diagrams and ECE, recalibration, choosing weights, extended cases.
- [Verbal probability](references/verbal-probability.md): ICD 203, Kent and IPCC scales and how to
  map LLM confidence language.
- [scripts/pool.py](scripts/pool.py): every formula above, deterministic.
