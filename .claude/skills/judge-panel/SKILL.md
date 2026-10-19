---
name: judge-panel
description: "Judge panels for choosing among N candidate artifacts (plans, designs, code, reports, images): independent attempts from distinct angles, rubric design with weights, gates and behavioural anchors, blind independent judges, aggregation (mean, median, trimmed mean), inter-judge agreement and disagreement handling, and synthesis that keeps the winner and grafts the best ideas from runners-up. Load when scoring alternatives against criteria, running or auditing /plan-tournament, or writing a rubric."
when_to_use: "Multi-criteria comparison of artifacts, architecture or plan tournaments, best-of-N generation with grading, rubric design for LLM judges. Use mediator-voting instead when the candidates are competing answers to one question with a single correct outcome."
---

# Judge panel

Generate several genuinely different attempts, score them blind against a rubric written before
anyone saw them, aggregate robustly, check that the judges actually agreed, then ship the winner
improved with the best transplantable ideas from the losers. Used by `architect`, `mediator` and the
`/plan-tournament` workflow.

## 1. When a panel is the right tool

| Signal | Panel? |
|---|---|
| Candidates are artifacts with several quality dimensions (plan, design, code, report, image) | yes |
| Quality is partly judgment, not fully checkable by tests | yes; run the checkable part first (`validator`, `tester`) and feed results to judges as evidence |
| One correct answer exists and voters can rank it | no, use `mediator-voting` |
| Output is a number | no, use `bayesian-aggregation` / `delphi-method` |
| Only one plausible approach exists | no, one author + `plan-critic` or `reviewer` is cheaper |
| Stakes justify about N + J + 2 spawns (N attempts, J judges) | required |

## 2. Protocol at a glance

| Phase | Output | Spawns |
|---|---|---|
| 1 Attempts | N candidates from distinct angles, same brief | N (parallel) |
| 2 Rubric | criteria, weights, anchors, gates, written BEFORE reading candidates | 0 |
| 3 Judging | each judge scores every candidate blind, with evidence per score | J (parallel) |
| 4 Aggregate | per-criterion aggregate, weighted totals 0-100, gates, ranking | 0 (script) |
| 5 Agreement | disagreement flags, Kendall's W, decisiveness, reconciliation if needed | 0-2 |
| 6 Synthesis | winner + grafts, regression check by a fresh judge | 1-2 |

Files: `<out_dir>/<YYYYMMDD-HHMM>-<slug>/` holding `RUBRIC.md`, `P1.md..Pn.md`, `scores.json`,
`panel.json`, `synthesis.md`; the report goes to `<out_dir>/<YYYYMMDD-HHMM>-<slug>.md`.

## 3. Phase 1 — Attempts from distinct angles

N = 3-5. Each author gets the identical brief plus ONE angle line. Angles must force structurally
different solutions, not stylistic variants.

| Angle | Steer given to the author |
|---|---|
| mvp-first | Smallest thing that delivers the core value end to end; defer everything else explicitly. |
| risk-first | Retire the largest unknowns first (spikes, prototypes, measurements) before building. |
| performance-first | Design around the hot path and explicit latency/throughput/memory budgets. |
| user-first | Work backwards from the user journey and the observable outcome. |
| simplicity-first | Fewest moving parts and dependencies; boring technology. |
| reuse-first | Maximize existing components, libraries and services; build only the gap. |
| security-first | Start from the threat model and trust boundaries. |
| ops-first | Observability, rollout, rollback and on-call burden drive the design. |
| contrarian | Reject the obvious approach and make the strongest case for an alternative. |

Default sets: plans `mvp-first, risk-first, performance-first, user-first` (as `/plan-tournament`);
architecture `simplicity-first, performance-first, risk-first` (+ `contrarian` when stakes are high).
Authors: `planner` for plans, `architect` for system-level designs, the relevant domain expert
(`rust-expert`, `go-expert`, ...) for code, `deep-researcher` for reports, `image-generator` for images.
Mix tiers across authors when the budget allows (pick agents from different tiers in
`config/models.json`; per-call `model`/`effort` are stripped by the hook), and tell authors not to spawn.
Two attempts that converge on the same core decision are one candidate: merge them before judging.

## 4. Phase 2 — Rubric design

Write `RUBRIC.md` before opening any candidate. Rules:

- [ ] **3-7 criteria**, each measuring one thing. Overlap test: if no candidate could score 5 on one
      and 1 on the other, merge them (double counting inflates whatever they share).
- [ ] **Weights** sum to 1, set from the caller's priorities, none above 0.40 (a criterion that
      dominant is either a gate or the whole decision).
- [ ] **Gates** (pass/fail, outside the weights): hard constraints such as "meets the stated budget",
      "has a rollback path", "no secrets or credentials in the artifact". Majority-of-judges fail
      disqualifies regardless of score.
- [ ] **Anchors** at 1, 3 and 5 describe observable properties of the artifact (2 and 4 are between).
      "Good error handling" is not an anchor; "every external call has a timeout and a named failure
      path" is.
- [ ] **Pilot**: score one candidate yourself. If you hesitate between two anchors more than once,
      rewrite those anchors.

Default plan rubric (the `/plan-tournament` criteria, which that workflow scores 1-10; more rubrics in
[rubric library](references/rubric-library.md)):

| Criterion (weight) | 1 | 3 | 5 |
|---|---|---|---|
| feasibility (.25) | depends on unavailable capability or unrealistic effort | feasible with named unknowns | every step maps to available tools/skills/agents; effort estimates justified |
| risk (.20) | top risks unnamed | risks named, mitigations vague | top risks ranked with concrete mitigations and early detection |
| cost (.15) | cost unbounded or unstated | rough estimate | estimate per phase with the dominant cost driver identified |
| verifiability (.20) | success described with adjectives | most steps have checks, some lack thresholds | every step has an acceptance criterion with a threshold and a named check |
| completeness (.20) | major requirement missing | all requirements touched, some shallow | every requirement traced to a step; edge cases and rollout covered |

## 5. Phase 3 — Blind, independent judging

J = 3 by default, 5 for high-stakes or contested decisions. Judges never authored a candidate.

| Artifact | Judges (J=3) |
|---|---|
| Plan / task DAG | `plan-critic`, `quality-control`, one domain expert |
| Architecture | `computer-science-expert`, `security-auditor`, `code-optimizer` or a domain expert |
| Code change | `reviewer`, `tester` (runs the tests, supplies evidence), `code-quality-analyst` |
| Research report | `fact-checker`, `quality-control`, `paper-researcher` |
| Visual design / image | `graphic-design-expert` (ADVANCED), `image-editor` (MEDIUM tier: a second model on craft criteria), plus `quality-control` |
| Prose / docs | `quality-control`, built-in `general-purpose`, one domain expert |

Bias controls (LLM judges show position, verbosity and self-preference biases):
1. **Blind labels** P1..Pn; strip authorship tells (reuse the anonymization checklist from
   `mediator-voting`). Keep the label map sealed until synthesis.
2. **Per-judge order**: rotate cyclically so each candidate appears first for some judge.
3. **Criterion-major scoring**: judge criterion 1 for all candidates, then criterion 2. Reduces halo.
4. **Evidence per score**: a quote (<=15 words) or section reference. A score without evidence is
   returned to the judge once, then dropped.
5. **Length neutrality** stated in the brief; cap candidate length or give judges the same summary
   format plus the full file path.
6. **Model diversity**: tiers are fixed per agent (`config/models.json`; the hook strips per-call
   `model`/`effort`), so mix ADVANCED-tier judges (plan-critic, quality-control, reviewer,
   security-auditor) with MEDIUM-tier ones (validator, fact-checker, tester, code-quality-analyst),
   avoid a panel whose judges all share the authors' tier, and say in the report when they do.
7. **N = 2 special case**: use pairwise comparison in BOTH orders; a verdict that flips with order is a tie.

Judge return shape (brief template in [rubric library](references/rubric-library.md#judge-brief)):

```json
{"judge": "J2",
 "gates":    {"P1": {"has-rollback": true}, "P2": {"has-rollback": false}},
 "scores":   {"P1": {"feasibility": 4, "risk": 3, "cost": 5, "verifiability": 3, "completeness": 3}},
 "evidence": {"P1": {"feasibility": "sec 2 reuses the existing job queue", "risk": "..."}},
 "steal":    {"P1": "week-1 read-only shadow mode", "P3": "per-tenant rate limit table"}}
```

`steal` names the single best transplantable idea in each candidate; it feeds Phase 6.

## 6. Phase 4 — Aggregation

Merge judge files into `scores.json` (`scale`, `criteria` weights, `scores` judge -> candidate ->
criterion -> number, optional `gates`) and run:

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
P="$STACK/.claude/skills/judge-panel/scripts/panel.py"
python3 "$P" <run>/scores.json > <run>/panel.json
python3 "$P" <run>/scores.json --normalize z   # leniency check
```

Definitions ([scripts/panel.py](scripts/panel.py)), scale [lo, hi], weights w_c summing to 1:

- Per candidate x criterion: `agg_c = AGG(scores of all judges)`.
- Total: `T = 100 * sum_c w_c (agg_c - lo) / (hi - lo)` (0-100).
- Per-judge totals use the same formula with that judge's raw scores (for agreement and decisiveness).

| Judges | AGG | Why |
|---|---|---|
| 2 | add a third judge | cannot tell which one is the outlier |
| 3-4 | median | one outlier cannot move it |
| 5-7 | trimmed mean, 20% each side | uses more information, still drops the extremes |
| 8+ | mean of z-normalized scores | leniency differences dominate at that size |

**Leniency (severity) bias**: a judge whose mean score sits 0.75+ points (1-5 scale) away from the
panel mean shifts every total. Re-run with `--normalize z` (per-judge z-scores mapped back to the
scale); if the winner changes, the result is leniency-sensitive: report it and add judges. Only
z-normalize with at least 12 scores per judge (for example 3 candidates x 4 criteria).

## 7. Phase 5 — Agreement and disagreement

Read from `panel.json`:

| Signal | Rule | Action |
|---|---|---|
| `disagreements` | a candidate x criterion with judge range >= 2 points (1-5 scale) | reconcile only if it could change the top-2 order or a graft decision |
| `kendall_w` | W = 12S / (m^2(n^3 - n) - m*sum T) on per-judge total rankings | < 0.3 weak: fix the rubric or the candidates, do not synthesize; 0.3-0.7 moderate: proceed only if decisive; >= 0.7 strong |
| `krippendorff_alpha` | interval alpha over all candidate x criterion cells | < 0.667: absolute scores unreliable, report ranks not scores and tighten anchors before reusing the rubric; >= 0.8 reliable |
| `decisive` | every judge ranks winner above runner-up AND margin >= 5 points | proceed to synthesis |
| `paired_t` | mean of per-judge (winner - runner-up) deltas / standard error | context only at J=3; below 2.78 with J=5 (two-sided 5% critical value, see agreement-stats) means contested |

Reconciliation ladder for a flagged cell:
1. **Evidence check**: compare the judges' evidence strings with the artifact. A judge who misread
   the artifact gets that score corrected (log old, new, reason).
2. **Anchor ambiguity**: if both readings are defensible, tighten the anchor in `RUBRIC.md` and have
   all judges re-score that criterion for all candidates (one batch of J parallel calls).
3. **Genuine judgment difference**: keep the median, report the spread in the Result.

Not decisive after reconciliation: add 2 judges (J=5, trimmed mean). Still not decisive: break the
tie by (a) the higher score on the highest-weight criterion, (b) fewer gate warnings, (c) the more
reversible option; if none separates them, return both with the crux as an Open doubt.

Formulas and worked computations for Kendall's W, Krippendorff's alpha and the paired test:
[agreement statistics](references/agreement-stats.md).

## 8. Phase 6 — Synthesis with grafts

1. Unseal labels. The winner's artifact is the skeleton; its load-bearing decisions stay.
2. **Graft candidates** = `panel.json.graft_candidates` (runner-up beats winner on a criterion by
   >= 1 point, sorted by weighted gain) plus every judge `steal` note.
3. For each, fill the graft table and accept at most 3-5 (more produces an incoherent hybrid):

| Idea (concrete) | From | Criterion improved | Conflicts with winner decision? | Cost | Decision |
|---|---|---|---|---|---|

   Accept only if it improves its criterion, conflicts with no load-bearing decision, and costs
   less than its weighted gain is worth to the caller.
4. Write the synthesized artifact (the winner's author or `planner`/`architect`; for cross-domain
   artifacts `cross-domain-synthesizer`).
5. **Regression check**: a fresh judge (not an author, not the synthesizer) scores synthesized vs
   winner on the same rubric. The synthesis must be >= the winner on every criterion and better on
   the grafted ones; drop any graft that lowered a criterion.
6. For plans and designs, finish with a `red-teaming` pass (`plan-critic`), as `/plan-tournament` does.

## 9. Worked example: three migration plans, three judges

Plans: P1 mvp-first, P2 risk-first, P3 performance-first. Rubric: the default plan rubric.
Gate `has-rollback`: only J2 failed P3 (1 of 3), so no disqualification.

Raw scores (feasibility, risk, cost, verifiability, completeness):

| | P1 | P2 | P3 |
|---|---|---|---|
| J1 | 5 3 5 3 3 | 4 5 3 5 4 | 3 3 2 4 4 |
| J2 | 4 2 5 3 2 | 4 4 3 4 4 | 3 3 2 3 5 |
| J3 | 5 3 4 2 3 | 3 5 4 5 3 | 2 2 3 4 3 |

Medians: P1 5 3 5 3 3, P2 4 5 3 5 4, P3 3 3 2 4 4.
P2 total = 100 x (.25x.75 + .20x1 + .15x.5 + .20x1 + .20x.75) = **81.25**; P1 = 70.00; P3 = 56.25.
Per-judge totals: J1 70.00 / 81.25 / 56.25, J2 53.75 / 71.25 / 56.25, J3 61.25 / 73.75 / 43.75.
Kendall's W: rank sums P1 7, P2 3, P3 8; S = 14; W = 12 x 14 / (9 x 24) = **0.78** (strong).
Krippendorff's alpha over the 15 cells = 0.62: judges agree on the order, not on absolute levels,
so the report quotes ranks and margins, and the anchors get tightened before the rubric is reused.
Paired deltas P2 - P1: 11.25, 17.5, 12.5; unanimous, margin 11.25 points: **decisive**.
Disagreement flag: P3 completeness 4/5/3. P3 cannot reach the top 2, so no reconciliation.
Graft candidates: P1 cost (+2 points, worth 7.5 weighted points), P1 feasibility (+1, 6.25).
Steal notes pointed to P1's reuse of the existing job queue (cost) and its one-week first milestone
(feasibility). Both are compatible with P2's spike-first sequencing: accepted. The regression judge
scored the synthesis 5 4 4 5 4 (86.25) against P2's medians 4 5 3 5 4: risk regressed from 5 to 4
because queue reuse adds unmitigated backlog growth. Adding a queue-depth alert and a backpressure
limit fixed it; re-scored 5 5 4 5 4. Final: P2 + two grafts, total 91.25, no criterion below P2.

## 10. Failure modes

| Failure | Symptom | Countermeasure |
|---|---|---|
| Fake diversity | attempts differ in wording, not structure | angle table; merge same-core candidates |
| Rubric written after reading | criteria mirror the favourite candidate | RUBRIC.md timestamped before candidates are opened |
| Halo effect | one strong criterion lifts all scores | criterion-major scoring; evidence per score |
| Position / verbosity bias | first or longest candidate wins | per-judge rotation; length cap; pairwise both orders at N=2 |
| Leniency spread | one generous judge decides | z-normalized re-run; median |
| Frankenstein synthesis | many grafts, incoherent result | max 3-5 grafts; conflict column; regression judge |
| Judges grading compliance with the angle | "risk-first" plan rewarded for being risk-first | the rubric judges outcomes; angles are never criteria |
| Unverified scores on checkable criteria | judges guess whether tests pass | run tests/validators first, give judges the evidence |

## 11. Depth, cost, and /plan-tournament

- Spawns: N + J + 1 synthesis + 1 regression (+1 red-team). N=4, J=3 costs about 10.
- Launch each batch (attempts, judges, re-scores) as parallel Agent calls with
  `run_in_background: false`; never rely on completion order. `budget="soft"`: no new panel; finish a
  running one without adding judges and report. `budget="hard"`: only file-summarizer,
  quality-control, validator and source-summarizer may be spawned; score the candidates you have
  yourself as a single-judge result and list the missing panel as an Open doubt.
- `remaining_depth` 0: no panel. Score candidates you already have with the rubric yourself,
  state that it is a single-judge result, and return an Open doubt if the stakes need a panel.
- `remaining_depth` 1-2: authors and judges must be leaves ("do not spawn subagents" in each brief).
- Only if you are the main thread (no `<stack-context>` header):
  `Workflow name=plan-tournament args={goal, angles?, judges?}` runs: planner per angle (architect for
  system-level), blind rubric judging (feasibility, risk, cost, verifiability, completeness),
  planner synthesis with grafts, plan-critic red-team and one revision; it returns
  `{plan_path, plan, scores, critique}`. Run by hand for non-plan artifacts, custom rubrics, gates
  or reconciliation. A subagent runs this protocol by hand with parallel Agent calls, or returns
  `Workflow name=plan-tournament args={...}` as an Open doubt for the main thread.
- Auditing a /plan-tournament result: it scores 1-10 with its own judge pool (plan-critic,
  quality-control, architect, validator, planner), medians and a Borda tie-break, so scale this
  skill's 1-5 thresholds by the same fraction of the scale (disagreement range >= 5, leniency about
  1.7 points) before applying them.

## 12. Output

```markdown
## Result
Winner P2 (risk-first), 81.25/100 vs P1 70.00; decisive (all 3 judges agree, W = 0.78).
Synthesized plan = P2 + 2 grafts from P1 (queue reuse, 1-week first milestone): 91.25 on regression check.
## Evidence
Totals table, per-criterion medians, gate results, disagreement flags and how each was resolved,
graft table with decisions.
## Files
- <out_dir>/<stamp>-<slug>.md — full report; <out_dir>/<stamp>-<slug>/panel.json, synthesis.md
## Open doubts
Leniency-sensitive results, unreconciled flags, dropped judges or candidates.
## Confidence
High only when decisive with W >= 0.7; state what would change the ranking.
```

## References

- [Rubric library](references/rubric-library.md): anchored rubrics for plans, architecture, code,
  research reports, visual design, prose and prompts, plus the judge brief.
- [Agreement statistics](references/agreement-stats.md): Kendall's W with ties, Krippendorff's
  alpha (interval), paired test, worked computations, interpretation thresholds.
- [scripts/panel.py](scripts/panel.py): aggregation, gates, agreement, grafts (stdlib Python).
