---
name: delphi-method
description: "Run Delphi panels with agents: question framing, panel design for low error correlation, anonymous round-1 estimates with rationale, controlled feedback (median, IQR, clustered arguments, outlier rationales), revision rules against herding, consensus and stability criteria with exact thresholds, persistent-dissent and crux handling, aggregation, and the consensus report. Load when several agents must converge on an estimate, forecast, probability, ranking or judgment."
when_to_use: "expert-panel-chair and the /expert-panel workflow; effort or cost estimates, forecasts, risk probabilities, parameter values, option rankings, Likert judgments where no cheap ground truth exists. Not for choosing among full solutions (mediator-voting), stress-testing one decision (structured-debate) or integrating complementary reports (expert-synthesis)."
---

# Delphi method for agent panels

Delphi (RAND, Dalkey and Helmer, 1950s-60s) has four defining features: **anonymity**,
**iteration**, **controlled feedback**, and **statistical aggregation** of the final round. It
outperforms unstructured groups mainly by removing social pressure and by letting sound minority
arguments travel without their authors' status (Rowe and Wright, 1999, review the evidence).

Agent panels add two risks human panels have less of, and this skill is built around them:
1. **Correlated errors.** Panelists on the same model with the same framing make the same mistakes;
   seven of them are worth much less than seven independent opinions.
2. **Conformity convergence.** LLM panelists move toward the shown median without new reasons.
   Convergence then measures compliance, not knowledge.

## 0. Does Delphi fit?

| Situation | Use |
|---|---|
| One quantity, probability, ranking or rating; judgment needed; no cheap ground truth | Delphi (this skill) |
| The answer can be computed, measured or looked up | do that instead (tester, Bash, fact-checker) |
| Several complete competing solutions | mediator-voting (`mediate` workflow, main thread only) |
| A single decision to attack from both sides | structured-debate |
| Complementary partial reports | expert-synthesis |
| You already have the estimates and only need to pool them | bayesian-aggregation |

## 1. Frame the question (most panels fail here)

Write a question spec before recruiting anyone:

```yaml
question: "Engineer-weeks to migrate the media store from S3 layout v1 to v2, incl. backfill and cutover"
kind: continuous            # continuous | probability | ranking | likert | categorical
unit: engineer-weeks        # continuous only
resolution: "sum of tracked effort on epic MED-42 at cutover"   # how truth would be known
horizon: "cutover by 2027-03-31"
conditions: ["team of 3", "no freeze periods", "v2 schema as in docs/media-v2.md"]
elicit: [p10, p50, p90, confidence, arguments, assumptions, would_change_if]
context_files: [docs/media-v2.md, infra/s3/README.md]
```

Checklist:
- [ ] Single quantity, not compound ("cost and time" is two panels or two questions).
- [ ] Resolvable: someone could later check the true value; probabilities name the event, the
      deadline and the source of truth.
- [ ] Units and boundaries explicit (what is in scope, which percentile, which population).
- [ ] Context is given as file paths every panelist receives identically (asymmetric context is a
      deliberate lever, section 2, never an accident).
- [ ] Elicit intervals (p10/p90), not just points: they reveal uncertainty and give the aggregation
      something to work with.

## 2. Design the panel

Size: 5-9 panelists; 7 is the default (odd, enough for meaningful quartiles). Below 5 the IQR is
noise. Above 9 gains are small unless diversity also increases.

Effective panel size under error correlation rho (the survey-sampling design effect):

```
n_eff = n / (1 + (n - 1) * rho)
n = 7, rho = 0.5  ->  n_eff = 7 / 4 = 1.75
n = 7, rho = 0.1  ->  n_eff = 7 / 1.6 = 4.4
```

Assume rho is high (0.5 or more) for a same-model, same-framing panel unless you have data. Diversity
is worth more than headcount; pull these levers, strongest first:

| Lever | How | Note |
|---|---|---|
| method assignment | give each panelist a different estimation method (table below) | cheapest, strongest decorrelator |
| agent type | different expert agents (physics-expert, computer-science-expert, architect, ...) | needed for domain questions |
| agent tier | mix ADVANCED-tier panelists (physics-expert, computer-science-expert, architect) with MEDIUM-tier ones (julia-expert, go-expert, quick-researcher) per config/models.json; never pass `model`/`effort` on the Agent call (the pre-agent hook strips them) | different model, different blind spots |
| evidence access | 1-2 panelists may research (WebSearch, mcp__exa__web_search_exa); others reason from context | prevents everyone anchoring on one search hit |

Estimation methods to assign (one per panelist):

| Method | Instruction to the panelist |
|---|---|
| outside view | find a reference class and its base rate; adjust minimally |
| inside view | decompose bottom-up into components, estimate each, sum with risk buffer |
| trend extrapolation | extrapolate from historical data in the context files |
| premortem pessimist | assume it went badly; estimate what that looks like; then back off to p50 |
| analogy | estimate from the closest past project; list the differences and adjust |
| constraint bound | derive hard lower/upper bounds first (first-principles), then place the estimate |
| contrarian | identify what the obvious estimate ignores and price it in |

The chair (you, typically expert-panel-chair) never estimates, never argues, and never reveals
identities. The chair's job is framing, feedback, rule enforcement and the report.

## 3. Round 1: independent elicitation

All panelists in **one message** (parallel Agent calls with `run_in_background: false`), no
cross-visibility. Each brief is self-contained: question spec, context paths, assigned method,
response schema, where to write.
Template in [briefs](references/briefs.md). Response schema:

```json
{"panelist":"P3","p10":7,"p50":10,"p90":15,"confidence":"medium","method":"inside-view",
 "arguments":[{"id":"a1","direction":"up","text":"backfill throughput limited by S3 LIST rate","evidence":"infra/s3/README.md:88"}],
 "assumptions":["v2 writer ready by week 2"],"would_change_if":"backfill dry-run exceeds 2 days per 10 TB"}
```

Store raw responses as `<out_dir>/<stamp>-<slug>/round-1/P<k>.json`. Keep the identity map
(P-id to agent type and tier) in `<out_dir>/<stamp>-<slug>/identity.json` at the run root, never in
a round directory (the stats script reads those) and never in a brief. P-ids
are stable across rounds internally; you may relabel in the feedback text, but stats must be per
stable id so stability can be measured.

## 4. Controlled feedback

Compute statistics in code, not by eye:

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
python3 "$STACK/.claude/skills/delphi-method/scripts/delphi_stats.py" <dir>/round-2 --prev <dir>/round-1
```

The [stats script](scripts/delphi_stats.py) reports median, Q1/Q3 (inclusive / type-7 quartiles),
IQR, relative IQR, consensus interval, disagreement envelope, panelists outside the IQR, moved share
vs previous round, stability, bimodality, geometric mean of odds (probabilities) and Kendall's W
(rankings). It reads only `P*.json`; likert and categorical stats are computed by hand. Formulas
are in [statistics](references/statistics.md).

Feedback packet sent to every panelist (same packet for all), in this order:
1. **Arguments first**: clustered themes, up to 3 pushing up and 3 pushing down, each with how many
   panelists raised it and whether it carries evidence. Cluster yourself for n <= 9; for larger
   panels or long rationales have a `source-summarizer` (LOW tier) cluster them with a brief that
   forbids adding arguments.
2. **Outlier rationales**: verbatim (anonymised, under 80 words each) reasons from panelists outside
   the IQR. This is the main channel by which a correct minority persuades.
3. **Statistics last**: median, Q1-Q3, min-max, the sorted anonymised values.
4. The panelist's own previous answer (individualised, the only per-panelist part).

Arguments before numbers reduces pure anchoring on the median.

## 5. Revision rules (enforced by the chair)

Each panelist in round r >= 2 must:
1. Answer `keep` or `revise` for p10/p50/p90.
2. If `revise`: cite the argument ids or the new evidence that caused it. "The group median is
   higher" is not a reason; such moves are logged as **uncited**.
3. If outside the previous IQR and `keep`: rebut the strongest opposing argument explicitly.
4. Add any new argument or evidence found (it enters the next feedback packet).

Chair checks after each round:
- Uncited moves: if more than half of all moves are uncited, flag **conformity convergence** in
  the report and cap the final confidence at medium.
- Arguments that are factual and checkable: route them now (fact-checker, tester, quick-researcher,
  Grep the repo yourself) and put the verdict into the next packet as evidence. Do not let a panel
  vote on a fact.

## 6. Convergence and stopping

| Kind | Consensus | Stability (round r vs r-1) |
|---|---|---|
| continuous | relative IQR = IQR / abs(median) <= 0.20, or IQR within the caller's stated tolerance | share of panelists whose p50 moved > 15% is <= 15% |
| probability | IQR <= 0.10 absolute (for p near 0 or 1, IQR <= 0.5 in log-odds) | same rule on p50 |
| ranking | Kendall's W >= 0.7 | abs(W_r - W_{r-1}) < 0.05 |
| likert 1-5 | IQR <= 1 and >= 70% within two adjacent points | share changing category <= 15% |
| categorical | >= 70% on one option | share switching <= 15% |

The 15% stability heuristic follows Scheibe, Skutsch and Schofer (1975); Kendall's W bands
(0.3 weak, 0.5 moderate, 0.7 strong) follow Schmidt (1997). Treat both as conventions, not laws.

Stop rules, checked in order after each round r >= 2:

| Condition | Action |
|---|---|
| consensus and stable | stop: report consensus |
| consensus, not stable | one more round (the distribution is still moving) unless at cap |
| not consensus, stable | stop: further rounds will not help; report dissent (section 7) |
| neither, r < cap | next round |
| r = cap (default 3, hard max 4) | stop: report the state as is |

Never stop after round 1 alone, even on apparent agreement: agreement before feedback from a
low-diversity panel is the signature of correlated error, not of truth. Most opinion change happens
between rounds 1 and 2; rounds beyond 3 mainly add conformity.

## 7. Persistent dissent and cruxes

Consensus is not correctness. A stable minority with a specific, checkable argument is the most
valuable output a panel can produce.

1. **Bimodal panel** (script flag: largest gap exceeds the spread of each side, each side >= 2):
   do not report a median as consensus. Report both clusters, their ranges, and their arguments.
2. **Lone stable dissenter**: keep the value in the statistics (the median is robust to it); quote
   the argument in the report; check whether the argument is factual.
3. **Crux finding**: ask each cluster (or the dissenter and two majority members) one question:
   "what single observation would move you to the other value?" If both sides name the same
   observable, that is the crux.
4. **Resolve the crux with evidence**, not with another vote: fact-checker (sources), tester or
   Bash (measure it), quick-researcher (small fact), adversarial-verifier (an argument's validity).
5. Feed the verdict back as a **crux round** (counts toward the hard max of 4). If the crux cannot be
   resolved, report conditional answers: "if X, 11 weeks; if not X, 22 weeks".

## 8. Aggregate the final round

| Kind | Point aggregate | Interval / spread |
|---|---|---|
| continuous | median of p50s | consensus interval = (median of p10s, median of p90s); disagreement envelope = (min p10, max p90) |
| probability | geometric mean of odds: `o_i = p_i/(1-p_i)`, `G = (prod o_i)^(1/n)`, `p = G/(1+G)` | Q1-Q3 of p50s |
| ranking | Borda or Schulze over final rankings (mediator-voting) | Kendall's W |
| likert / categorical | median category / plurality share | full distribution |

Notes:
- Do not extremize pooled probabilities from a same-model panel; extremizing assumes independent
  information. Weighted pools and calibration weights: bayesian-aggregation.
- The consensus interval (quantile averaging) is narrower than the disagreement envelope; report both
  when the decision depends on tails (budgets, deadlines, risk caps).
- Probabilities of exactly 0 or 1 are clipped to [1e-6, 1-1e-6] before pooling; ask the panelist to
  justify certainty instead.

## 9. Running it

**Workflow route** (preferred for 5+ panelists, only if you are the main thread, i.e. your prompt
has no `<stack-context>` header): call the Workflow tool with name `expert-panel` and args
`{question, experts?, rounds?: 3, estimate?: true}`. As a subagent you have no Workflow tool: use
the manual route, or, when the panel exceeds your depth or budget headroom, return
`Workflow name=expert-panel args={question: "<spec>", estimate: true, rounds: 3}` as an Open doubt.
The workflow does the independent round, computes feedback in code, revises, stops on
IQR/stability, and has expert-panel-chair synthesise. Pass the question spec text as `question`.

**Manual route** (any subagent, small panels, custom methods):
1. Write the spec and identity map; create `round-1/`.
2. One message with all panelist Agent calls (`subagent_type` per panel design; no `model`/`effort`,
   tiers come from config/models.json; `run_in_background: false`, because the stats step needs
   every result). Each writes its JSON to `round-r/P<k>.json` and returns a one-line summary
   (p10/p50/p90) and the path.
3. Run the stats script; build the feedback packet; check revision rules; apply stop rules.
4. Repeat. Budget: n x rounds panelist calls plus at most one clusterer per round; a 7 x 3 panel is
   21 to 24 calls. Check `remaining_depth`, `spawns_this_session` and `budget` in the
   `<stack-context>` header before starting. At `budget="soft"` start no new panel or extra round:
   finish the current round and report. At `budget="hard"` only file-summarizer, quality-control,
   validator and source-summarizer can be spawned, so report the current state and list the gaps
   (unrun rounds, unresolved cruxes) as Open doubts. At `remaining_depth` 1-2, panelists must be
   leaves (tell them not to spawn).

Write the report to `<out_dir>/<stamp>-<slug>/report.md`; the rounds directory is its evidence.

## 10. Report template

```markdown
# Delphi: <question short form>
## Answer
<point estimate + consensus interval + unit>, consensus: yes/no (criterion, value), stop reason.
## Question spec
<verbatim spec or path>
## Panel
| P | Method | Agent type | Tier (config/models.json) |   (types listed only here, never in feedback)
## Rounds
| Round | Median | Q1 | Q3 | rel IQR / W | Moved share | Uncited moves | Notes |
## Key arguments
Up: <top arguments with evidence>. Down: <top arguments with evidence>.
## Dissent and cruxes
<cluster or dissenter value, argument, crux, how resolved or conditional answer>
## Caveats
<conformity flag, low diversity, unresolved crux, context limits>
## Confidence
<calibrated level and why; capped at medium if conformity was flagged>
```

## Worked example

Question: engineer-weeks for the media-store migration (spec in section 1). Panel of 7: methods
outside view, inside view, trend, premortem, analogy, constraint bound, contrarian; ADVANCED- and
MEDIUM-tier agent types mixed (architect, physics-expert, julia-expert, go-expert); two panelists
allowed to research.

| Round | p50 values (sorted) | Median | Q1-Q3 | rel IQR | Moved > 15% | Verdict |
|---|---|---|---|---|---|---|
| 1 | 6, 8, 9, 10, 12, 16, 30 | 10 | 8.5-14 | 0.55 | - | no consensus |
| 2 | 8, 10, 10, 10, 12, 13, 26 | 10 | 10-12.5 | 0.25 | 3 of 7 (43%) | not stable, continue |
| 3 | 9, 10, 10, 11, 11, 12, 24 | 11 | 10-11.5 | 0.14 | 0 of 7 | consensus and stable |

Rounds 1-3 stop by the table with consensus at 11 weeks. But P7 held 24-30 for three rounds with one
specific argument: "a share of v1 objects use the legacy multipart layout and need re-encoding, which
nobody priced". It is factual and checkable, so the chair routes it before reporting: a tester run
samples 10k object manifests and finds 18% in the legacy layout (grade A evidence). Crux round 4:

| Round | p50 values (sorted) | Median | Q1-Q3 | rel IQR | Consensus interval |
|---|---|---|---|---|---|
| 4 (crux) | 13, 14, 14, 15, 16, 18, 22 | 15 | 14-17 | 0.20 | 11-20 weeks |

Report: 15 engineer-weeks (consensus interval 11-20, envelope 10-32), consensus at the threshold,
stopped at the hard max. The round-3 consensus was wrong by about 35%; the dissent, resolved with
evidence, moved the answer. Caveat: round 2 had 1 uncited move out of 3 (not over half, so no
conformity flag).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| near-identical round-1 answers | same model, same framing | assign methods, mix agent types across tiers (config/models.json) |
| everyone moves to the median, no citations | conformity | enforce rule 2, flag, cap confidence |
| median swings between rounds | question ambiguous | stop, rewrite spec, restart (do not "average through" ambiguity) |
| arguments are about facts | panel voting on a lookup | route facts out, feed back verdicts |
| bimodal final round | two world models | report clusters and the crux; resolve or condition |
| very wide intervals everywhere | missing context | add context files, not rounds |

## Output

Follow output-contract. `## Result`: the answer line, consensus verdict and stop reason, plus the
rounds table. `## Evidence`: report path and round directories, crux verdicts with grades.
`## Files`: report and rounds paths. `## Open doubts`: unresolved cruxes with the exact check that
would settle each. `## Confidence`: from consensus, diversity and conformity flags, not from panelist
self-confidence.
