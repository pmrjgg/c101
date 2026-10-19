# Cost and tuning math

Reference for the effort-and-model-selection skill: how to estimate what a delegated call costs,
when starting cheap is actually cheaper, and what the self-tuning learner does with the runs you
route. Prices are list prices as of October 2026; re-check before quoting dollars to a user. You
never pick a model per call (the pre-agent hook strips `model`/`effort`): the tables compare the three
tiers so you can choose a cheaper or stronger agent.

## 1. Price table (USD per million tokens)

| Tier (alias) | Current model | Input | Cached read | Output | Output ratio vs LOW |
|---|---|---|---|---|---|
| LOW_MODEL (haiku) | Claude Haiku 5.5 | 0.10 (prompts up to 100K; 0.50 beyond) | assume ~0.01 (see note) | 0.50 (2.50 beyond 100K) | 1x |
| MEDIUM_MODEL (sonnet) | Claude Sonnet 5.5 | 2.00 | 0.20 | 10.00 | 20x |
| ADVANCED_MODEL (opus) | Claude Opus 5.5 | 4.00 | 0.20 | 20.00 | 40x |

Note: the haiku cached-read price is an assumption (10% of input) used only in the examples below;
it barely moves any haiku total. Cache writes cost somewhat more than plain input; they are ignored
here because Claude Code writes the prefix once and reads it every turn after.

## 2. Cost model for one agent run

```
C = I_fresh * p_in + I_cached * p_cached + O * p_out
```

- `I_fresh`: tokens that enter the context for the first time: system prompt, preloaded skills,
  the brief, files read, tool results, search pages.
- `I_cached`: tokens re-read from the prompt cache on every later turn. Roughly
  turns x average context size. In long runs this term rivals output.
- `O`: output tokens including thinking. Effort mostly moves this term (bands: low under 4k,
  medium 4k-16k, high 16k-48k, xhigh 48k-120k, max 120k and up).

Levers by term:
- `I_fresh`: pass paths and line ranges, not blobs; have file-summarizer read huge inputs.
- `I_cached`: fewer turns and a leaner context: offload outputs to files (output-contract), avoid
  re-reading whole files, split long jobs into shards.
- `O`: effort; terse output contracts; no restating of the brief.

## 3. Worked examples

### 3.1 First failing test in a 2,400-line CI log

Assume 40k fresh input (log about 30k plus system and skills), 100k cached reads over 4 turns, 2k output.

| Tier | Cost | Ratio |
|---|---|---|
| LOW (file-summarizer) | $0.006 | 1x |
| MEDIUM | $0.12 | 20x |
| ADVANCED | $0.22 | 37x |

A LOW-tier agent is correct here: pure extraction, trivially checkable (the test name either exists or not).

### 3.2 Fan-out: summarise 30 web sources

Per call: 33k fresh (page about 25k plus 8k system and skills), 60k cached, 1.5k output.

| Tier | Per call | 30 calls |
|---|---|---|
| LOW (source-summarizer) | $0.0046 | $0.14 |
| MEDIUM | $0.093 | $2.79 |
| ADVANCED | $0.174 | $5.22 |

The same fan-out on an ADVANCED-tier agent buys nothing measurable for extraction-type summaries.
Spend the difference on one ADVANCED-tier synthesis call over the 30 summaries instead.

### 3.3 Long review run

40 turns, 120k fresh, 3.2M cached reads, output varies with effort.

| Tier / learned effort | Output | Cost |
|---|---|---|
| MEDIUM / high | 30k | $1.18 |
| ADVANCED / high | 30k | $1.72 |
| ADVANCED / xhigh | 90k | $2.92 |

Observation: on the ADVANCED tier the cached-read term ($0.64) is larger than the fresh-input term ($0.48).
Keeping the context lean matters as much as choosing effort.

## 4. Start cheap or start strong?

Expected cost of a routing choice, first order:

```
E[C] = C_first + P_fail * ( P_detect * C_next + (1 - P_detect) * W )
```

- `P_fail`: chance the first call's result is wrong or insufficient.
- `P_detect`: chance the failure is caught (tests, validator, quality-control). High when
  verification difficulty V is low.
- `C_next`: cost of the next ladder rung.
- `W`: cost of an undetected wrong result: rework, wrong decision, incident. Grows with blast radius B.

Example, a coding task. A MEDIUM-tier agent (e.g. go-expert): $0.40, P_fail 0.35. An ADVANCED-tier
agent (e.g. rust-expert or computer-science-expert): $1.72, P_fail 0.10. Next rung after that: a
stronger or more specialised ADVANCED agent whose learned effort is xhigh, about $2.92.

| Scenario | Start MEDIUM-tier agent | Start ADVANCED-tier agent | Winner |
|---|---|---|---|
| Tests catch failures (P_detect 0.9), W = $20 | 0.40 + 0.35 x (0.9 x 1.72 + 0.1 x 20) = $1.64 | 1.72 + 0.10 x (0.9 x 2.92 + 0.1 x 20) = $2.18 | MEDIUM |
| Hard to verify (P_detect 0.3), W = $200 | 0.40 + 0.35 x (0.3 x 1.72 + 0.7 x 200) = $49.58 | 1.72 + 0.10 x (0.3 x 2.92 + 0.7 x 200) = $15.81 | ADVANCED |

This is the formal reason behind the tier choice in the skill (section 3): V and B, not task size,
decide when the expensive tier is the cheap option.

## 5. What the learner does with your runs

Parameters live in `config/learning.json`; code in `stack/learn/model.py`.

| Parameter | Shipped value | Effect |
|---|---|---|
| `turns_quantile`, `turns_margin` | 0.95, 1.15 | maxTurns target = ceil(q95 of predictive turns x 1.15) |
| `prior_limit_ratio` | 3.0 | prior belief: a typical run uses maxTurns / 3 turns |
| `max_step_factor` | 2.0 | maxTurns moves at most 2x (or 1/2) per update |
| `min_change_frac` | 0.1 | hysteresis: changes under 10% (and under 2 turns) are ignored |
| `min_obs_turns`, `min_obs_effort` | 3, 5 | effective runs needed before turns / effort move |
| `effort_bands_output_tokens` | 4k, 16k, 48k, 120k | bins runs into low, medium, high, xhigh, max |
| `effort_cover_mass` | 0.8 | choose the smallest level covering 80% of predictive mass |
| `effort_prior_alpha`, `effort_prior_stickiness` | 0.5, 3.0 | Dirichlet prior; +3 pseudo-runs on the current level |
| `fail_prior` | Beta(1, 4) | prior failure rate 0.2 |
| `fail_rate_escalate`, `fail_rate_deescalate` | 0.25, 0.08 | escalate one level above 0.25; block de-escalation above 0.08 |
| forgetting factor gamma | chosen per agent by prequential log score | how many past runs the posterior listens to |
| `apply_compact_window`, `context_window_tokens`, `context_pressure` | true, 200000, 0.8 | raise-only autoCompactWindow = ceil(q95 ctx_peak x 1.15 / 10k) x 10k (100k-1M) when ctx_peak q95 > 0.8 x current window |

A run counts as failed when it hit maxTurns (capped) or was recorded as failed.

### 5.1 Example: quick-researcher drifts up

Ten runs, current effort low, maxTurns 20. Output tokens: 2.0k, 3.0k, 3.5k, 5.0k, 2.5k, 6.0k, 3.0k,
2.0k, 9.0k, 3.0k (7 low-band, 3 medium-band). Turns: 6, 8, 7, 11, 6, 12, 7, 5, 15, 8. No failures.

Learner output (computed with `stack/learn/model.py`, gamma = 1.0):
- Effort posterior: low 0.677, medium 0.226, the other levels 0.032 each. Low alone covers 0.677,
  under 0.8, so the recommendation is medium (allowed: bounds for quick-researcher are low-medium).
  P(fail) mean 0.067 is under 0.08, so nothing blocks the move.
- Turns: q95 = 16.3, target ceil(16.3 x 1.15) = 19; |19 - 20| < 2, so maxTurns stays 20.

Routing lesson: three medium-sized lookups in ten were enough to move the default. If those were
really deep-research questions misrouted to quick-researcher, fix the routing, not the agent.

### 5.2 Example: two over-scoped briefs double a reviewer's budget

Ten reviewer runs at maxTurns 60, effort high. Turns: 18, 22, 25, 31, 60 (cap), 44, 60 (cap), 38, 27,
52. Output tokens: 20k-70k.

Learner output:
- Turns: the two capped runs are censored ("at least 60"), so q95 = 102.5, target
  ceil(102.5 x 1.15) = 118, within the 2x step limit: maxTurns 60 becomes 118.
- Effort: high 0.613 plus lower levels 0.064 = 0.677 < 0.8, so xhigh. P(fail) = (1 + 2) / (5 + 10) = 0.20.

Routing lesson: two briefs that should have been split (effort-and-model-selection, turn scoping)
raised maxTurns and effort for every later reviewer call. If those reviews were genuinely large, the
change is right; if they were over-scoped, split future briefs and let the learner walk back down.

## 6. Commands

```bash
bin/stack agents list                       # live tier / effort / maxTurns per agent
bin/stack learn report --agent reviewer     # posterior summary: n, gamma, maxTurns and effort current->recommended, P(fail), token window
bin/stack learn apply --dry-run             # changes the next apply would write
bin/stack agents set reviewer effort=high   # manual edit; learn apply may move it back within bounds
```

Pinning a value: narrow that agent's bounds in `config/learning.json` (stack-tuner owns this file),
for example `"reviewer": {"effort": ["high", "high"]}`.
