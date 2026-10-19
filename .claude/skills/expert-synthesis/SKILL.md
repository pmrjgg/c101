---
name: expert-synthesis
description: "Integrate several expert outputs into one higher-level solution: vocabulary alignment, assumption map, claim-level provenance table, conflict-resolution matrix (who is authoritative on which sub-question and why), gap analysis, emergent cross-domain opportunities, and the integrated-answer template. Load when 2+ expert or agent reports covering different parts of one problem must become a single answer."
when_to_use: "After ensemble-assembler, /expert-panel, /swarm-run or a research fan-out returns complementary reports; when experts disagree across disciplines; when a final answer needs per-claim provenance. Not for choosing among competing full answers (mediator-voting) or pooling estimates of one number (delphi-method, bayesian-aggregation)."
---

# Expert synthesis

Synthesis is neither summarisation (shorter text, same structure) nor voting (pick one). It produces
a solution none of the inputs contains, in which every claim is traceable to an expert, a derivation
or a check you ran, and every disagreement has an explicit, reasoned resolution. The two failure modes
it exists to prevent are (1) the **stapled report**: sections from each expert concatenated, with
contradictions left in place, and (2) the **mushy average**: incompatible designs blended into one
that satisfies nobody ("the mean of a bridge and a tunnel is a wet bridge").

## 0. Pick the aggregation tool first

| Shape of the inputs | Tool |
|---|---|
| Complementary parts of one problem (each expert owns different sub-questions) | this skill |
| Competing full answers to the same question | mediator-voting (`mediate` workflow, main thread only) |
| Numeric estimates or probabilities of the same quantity | delphi-method (`expert-panel` workflow, main thread only), then bayesian-aggregation |
| One favoured option that must survive attack | structured-debate, red-teaming |
| Individual claims that must survive refutation | adversarial-verification |

Mixed shapes are the norm. Run this skill as the backbone and route single contested sub-questions to
the specialised protocol (section 7, escalation column).

## 1. Intake

Required inputs (return an Open doubt if missing and the gap is load-bearing):
- The original problem statement, verbatim, and the success criteria the caller gave.
- Each expert report as a **path** (not pasted), plus its agent type, model and effort.
- The decomposition the experts were briefed with, if one exists (ensemble-assembler writes it).

Read selectively. Locate sections first, then read ranges:

```bash
grep -n -E '^## (Result|Evidence|Files|Open doubts|Confidence)' .stack/out/*/2026*-<slug>*.md
```

then `Read` with `offset`/`limit` on the Result and Open doubts ranges. Large reports: hand them to
`file-summarizer` with a brief that asks for atomic claims with line anchors, not a prose summary.

Create the workspace under your `out_dir` from the `<stack-context>` header:

```
<out_dir>/<YYYYMMDD-HHMM>-<slug>/
  frame.md        sub-question tree + coverage matrix
  glossary.md     aligned vocabulary
  claims.md       provenance table (the spine of everything else)
  assumptions.md  assumption map
  conflicts.md    conflict-resolution matrix
  gaps.md         gap ledger + actions taken
  integrated.md   the deliverable
```

Intake ledger (top of `frame.md`):

| Id | Agent | Model/effort | Scope it covered | Self-reported confidence | Open doubts | Path |
|---|---|---|---|---|---|---|
| E1 | physics-expert | opus/xhigh | integrator, error bounds | medium | 1 | `.stack/out/physics-expert/...md` |

Use opaque ids E1..En everywhere after intake. Name experts only in the provenance appendix; this keeps
you from deferring to a label instead of an argument.

## 2. Frame: sub-question tree and coverage matrix

1. Rewrite the problem as a tree of sub-questions Q1..Qn, each answerable by one discipline and each
   with an acceptance test ("Q3: what is the per-frame network payload, in bytes, at target N?").
2. Mark the **seams**: sub-questions whose answer is produced by one discipline and consumed by
   another (units, data formats, timing, failure ownership). Seams are where most synthesis bugs live.
3. Build the coverage matrix (rows Q, columns E): `A` answered with evidence, `a` answered without
   evidence, `m` mentioned only, blank = not covered.

Rules: a row with one `A` and nothing else is **single-source**; a row with no `A`/`a` is a
**coverage gap**; a seam row with no owner is an **interface gap**. All three go to section 8.

## 3. Vocabulary alignment

Experts from different fields use the same word for different quantities. Resolve this before you
compare claims, or you will "resolve" conflicts that do not exist and miss ones that do.

For every term that appears in 2+ reports or carries a number, fill `glossary.md`:

| Term as written | E-id: meaning | Unit / scale / reference frame | Canonical term used in synthesis |
|---|---|---|---|
| accuracy | E1: relative energy drift abs(dE/E0); E2: per-force relative error | dimensionless; per-run vs per-evaluation | `energy-drift`, `force-error` |
| latency | E3: p50 server compute; E4: p99 end-to-end incl. network | ms; percentile and boundary differ | `t_compute_p50`, `t_e2e_p99` |

Checks: same symbol different quantity (homonym); different word same quantity (synonym, merge);
units and percentiles; per-unit vs aggregate (per request vs per second, per node vs cluster); time
base (wall vs CPU vs simulated time); reference population (all users vs active users). The catalogue
of frequent cross-discipline collisions is in [false friends](references/false-friends.md).

## 4. Claims and the provenance table

Break each report into **atomic claims**: one assertion, one truth value, testable in principle.
"Use Barnes-Hut because it is fast and simple" is two claims plus a recommendation.

`claims.md` columns:

| Id | Claim (canonical vocabulary) | Q | Src | Type | Evidence | Grade | Conf | Depends on | Status |
|---|---|---|---|---|---|---|---|---|---|

- **Type**: `fact` | `estimate` (number with range) | `mechanism` (X causes Y) | `recommendation` |
  `constraint` | `assumption` (only if stated; implicit ones go to section 5).
- **Grade** (use these exactly, other skills in the stack share them):
  - `A` reproduced in this session: command output, test run, computation you executed.
  - `B` primary source cited: spec, paper, official docs, `file:line`, dataset.
  - `C` derivation shown or reputable secondary source; checkable but not checked.
  - `D` assertion by the expert with no support.
- **Conf**: the expert's stated confidence mapped to a probability (high 0.85, medium 0.65,
  low 0.4 unless the expert gave a number). Self-reported confidence is weakly calibrated; never use it
  alone to break a conflict.
- **Status**: `accepted` | `conditional(<assumption or regime>)` | `superseded(Cx)` |
  `disputed(Kx)` | `unverified` | `rejected(<reason>)`.

Load-bearing test for every claim: *if this were false, would the integrated recommendation change?*
Mark load-bearing claims with `*`. Load-bearing + grade D is a validation gap (section 8).

## 5. Assumption map

Experts disagree most often because they silently assume different worlds. Extract assumptions in
three passes: stated ("assuming read-heavy traffic"), implied by a recommendation ("use a single
leader" implies write rate fits one node), and implied by a number (a latency figure implies a
hardware class and a percentile).

`assumptions.md`:

| Id | Assumption | Held by | Contradicted by | Claims depending | Load (deps x impact) | Check |
|---|---|---|---|---|---|---|
| A3 | sim clock advances in lock-step with 60 Hz render | E4 | E1 (adaptive dt) | C14, C15, C21 | high | caller / design choice |

Classify each pair of assumptions across experts: `compatible`, `orthogonal`, `conflicting`. Every
`conflicting` pair becomes a conflict row in section 7. Rank by load; check the top three explicitly
(cheap check: Grep the codebase, `quick-researcher`, a one-line computation; expensive: return it as
an Open doubt for the caller).

## 6. Detect and classify conflicts

Two claims conflict when both cannot hold for the same sub-question, regime and assumptions. Classify
before resolving, because the type determines the rule:

| Type | Signature | Resolution route |
|---|---|---|
| T1 terminological | conflict disappears after glossary | rewrite both in canonical terms; usually both survive |
| T2 assumption | each is right under its own assumption | make the answer conditional, or pick the assumption that matches the caller's facts |
| T3 regime | each is right in a different range (scale, load, size, time) | split by regime with an explicit boundary; measure the boundary if load-bearing |
| T4 factual | one must be false | evidence: run it (tester, Bash), source it (fact-checker), refute it (adversarial-verifier) |
| T5 value / priority | both true; they weigh criteria differently | expose the trade-off; caller decides unless the brief fixed the weights |
| T6 evidence-quality | same claim, different strength of support | keep the higher grade; note the lower as corroboration only if independent |

## 7. Conflict-resolution matrix

Precedence of authority, applied top-down until one rule decides:

1. **Reproduced evidence beats rank.** A grade-A result from this session beats any unreproduced
   claim, whatever the discipline, within the conditions actually tested.
2. **Mechanism ownership.** The expert whose discipline owns the *mechanism* the sub-question is about
   is authoritative (table below). Owning the topic is not enough; owning the causal mechanism is.
3. **Regime bounding.** Authority holds only inside its regime: asymptotic analysis owns large n;
   a benchmark owns the n it measured; a physical bound owns everything it bounds.
4. **Specificity.** A claim with stated conditions beats an unconditional claim on the same point.
5. **Recency** for fast-moving facts (API surface, versions, prices, browser support): the newer
   primary source wins; record the date.
6. **Escalate** when still tied (section 7 escalation column, never a coin flip).

| Sub-question is about | Authoritative agent | Why |
|---|---|---|
| asymptotic cost, correctness of an algorithm or protocol | computer-science-expert | owns the proof |
| measured speed on this hardware and code | code-optimizer (with benchmark) | owns the measurement |
| numerical stability, convergence, error bounds | mathematics-expert, physics-expert | own the analysis |
| conservation, units, physical limits | physics-expert | owns the invariants |
| language semantics, UB, borrow rules, runtime behaviour | the language expert (rust-expert, cpp-expert, ...) | owns the semantics |
| exploitability, trust boundaries | security-auditor | owns the threat model |
| rendering, GPU pipeline behaviour | computer-graphics-expert | owns the pipeline |
| what a source actually says | fact-checker | owns the reading |

`conflicts.md` row format:

| K | Q | Claims | Type | Positions (one line each) | Rule applied | Outcome | Residual uncertainty | Escalated to |
|---|---|---|---|---|---|---|---|---|
| K2 | Q2 | C7 vs C11 | T3 | E2: FMM O(N) wins; E3: Barnes-Hut faster at N=1e6 on target GPU (bench) | 1 then 3 | BH for N<=1e6; FMM revisit if N grows 10x | crossover N not measured | - |

Escalation routes (spawn per delegation-protocol; several in one message when independent, each with
`run_in_background: false`, because the conflict outcome waits on the verdicts):

| Conflict need | Agent | Tier (config/models.json; never pass model/effort) |
|---|---|---|
| what does source X say, is fact Y current | fact-checker | MEDIUM |
| does code/config behave like this | tester | MEDIUM |
| is this derivation or argument sound | adversarial-verifier | ADVANCED |
| missing fact, small | quick-researcher | MEDIUM |
| contested multi-hop question | deep-researcher | ADVANCED |
| two sound positions, high stakes | debate-moderator (structured-debate) | ADVANCED (orchestrator: only while your remaining_depth >= 3, i.e. the child depth stays <= 6; otherwise return it as an Open doubt) |
| value trade-off | back to caller as an Open doubt with options and consequences | - |

Never resolve by: averaging incompatible designs; counting heads when the experts share a model or a
source (they are not independent); deferring to the most confident or the longest report; silently
dropping the losing claim (it goes to the dissent section with the reason it lost).

## 8. Gap analysis

| Gap type | Detection | Default action |
|---|---|---|
| coverage | Q row empty in coverage matrix | spawn the owning expert with a narrow brief |
| single-source | one `A`/`a` on a load-bearing Q | cheap cross-check (fact-checker, tester, or a second expert from a MEDIUM-tier agent type; no per-call effort) |
| interface / seam | seam row has no owner, or units/formats mismatch | compute it yourself (often a first-principles bound) |
| requirement | security, cost, operability, migration, observability unaddressed | in scope per the brief: spawn the owner; scope not stated: do not spawn, record it as an Open doubt (scope question plus the brief to run if in scope) and continue |
| validation | load-bearing claim with grade D | upgrade to B or A, or downgrade the recommendation |

Decision rule per gap: load-bearing and cheap (one leaf agent, `remaining_depth >= 1`, `budget` not
"hard") means fill it now. Load-bearing and expensive means fill it only at `budget="ok"` with room
in `spawns_this_session`, else record it as an Open doubt with the exact brief someone should run.
At `budget="soft"` start no new expert spawns; at `budget="hard"` only file-summarizer,
quality-control, validator and source-summarizer may be spawned. Not load-bearing means list
it under Limitations.

## 9. Emergent cross-domain opportunities

The reason to synthesise instead of concatenate. Scan for these six patterns explicitly:

1. **Free-parameter arbitrage**: a hard constraint for one expert is a free choice for another
   (graphics needs a fixed frame clock; the integrator can sub-step freely: decouple the clocks).
2. **Shared bottleneck**: two experts optimise the same resource from different sides; one change
   serves both.
3. **Solution import**: one domain's solved problem is another's open problem (run analogical-transfer).
4. **Unneeded conservatism**: an expert assumed a worst case that another expert's facts rule out.
5. **Dominating composition**: combining parts of two proposals beats each full proposal on every
   criterion (check Pareto dominance against the caller's criteria, not your taste).
6. **Evidence reuse**: one expert's instrumentation, dataset or test answers another's open doubt.

Each opportunity entry: statement; claims it builds on; why no single expert saw it (which seam);
feasibility check performed (grade); who must verify it; expected gain on the success criteria.
An opportunity without a feasibility check is labelled `speculative` and kept out of the main answer.

## 10. Integrate

Write `integrated.md` from the claims table, not from the reports. Rules:
- Every sentence traces to claim ids, an assumption id, or a derivation shown inline.
- Numbers keep units and ranges. Independent multiplicative factors: relative errors add in
  quadrature, `rel(x*y) = sqrt(rel(x)^2 + rel(y)^2)`; additive terms: absolute errors add in
  quadrature. Correlated or unknown dependence: add linearly (conservative).
- Several experts estimating the same quantity: pool per bayesian-aggregation (median or log pool),
  never the arithmetic mean of skewed point estimates.
- Conflicts resolved by T2/T3 rules appear as conditionals with explicit boundaries.
- Dissent is preserved with the reason it lost and what evidence would reverse the call.
- Re-run the quality gate (section 11) before returning.

## Integrated-answer template

```markdown
# <Problem title> - integrated answer
## Answer
<3-8 sentences: the recommendation, its main conditions, the headline numbers with ranges.>
## Solution structure
<components / steps / decisions; each line ends with [C#, C#] or [derived: section X]>
## Decisions and why
| Decision | Chosen | Rejected | Deciding claims | Rule (evidence/ownership/regime/...) |
## Conditions and regimes
<if/then boundaries from T2/T3 resolutions; what to monitor to know which regime you are in>
## Emergent opportunities
<each with feasibility grade and verification owner; speculative ones labelled>
## Dissent
| Overruled claim | Held by | Why it lost | What would reverse it |
## Gaps and limitations
<unfilled gaps, single-source load-bearing claims, unverified assumptions>
## Provenance
<claim table (or path + line range), glossary, intake ledger>
```

## 11. Quality gate (all must pass)

- [ ] Every sub-question has an answer or is listed as a gap with an action.
- [ ] No two accepted claims contradict (scan accepted rows pairwise per Q).
- [ ] Every load-bearing claim in the answer has grade A or B, or is flagged in Limitations.
- [ ] Every conflict row has a type, a rule and an outcome; no outcome says "balanced" or "both".
- [ ] Units consistent end to end; seam quantities computed, not assumed.
- [ ] Dissent section non-empty whenever any claim was overruled.
- [ ] No statement in the answer lacks a claim id or derivation (spot-check 10 sentences).
- [ ] Emergent opportunities are either feasibility-checked or labelled speculative.

## Worked example (compressed)

Problem: interactive gravitational N-body, N = 1e6, GPU server, browser viewer at 60 fps, energy drift
below 1e-3 over 1e4 steps. Reports: E1 physics-expert, E2 computer-science-expert, E3 julia-expert,
E4 computer-graphics-expert.

Glossary: "accuracy" split into `energy-drift` (E1) and `force-error` (E2). "Frame" split into
`sim-step` (E1, E3) and `render-frame` (E4).

| K | Type | Positions | Resolution |
|---|---|---|---|
| K1 | T1 | E1 "accuracy 1e-3" vs E2 "accuracy 1% is fine" | both survive after split: drift <= 1e-3 per run, force error ~1% per evaluation |
| K2 | T3 + T4 | E2 FMM asymptotically better; E3 benchmark shows Barnes-Hut (theta 0.6) faster at 1e6 | rule 1 (E3 rerun by tester, grade A) then rule 3; FMM recorded as revisit-if-N-x10 |
| K3 | T2 | E1 adaptive per-particle dt; E4 assumes one sim step per render frame | assumption A3 rejected; leads to opportunity O1 |
| K4 | T4 | E4 "WebGPU compute available in target browsers"; E3 planned WebGL2 fallback | fact-checker per target browser list; keep fallback until verdict (cheap hedge) |

Seam gap found in section 8 (nobody owned Q5, transport): positions are 3 x 4 B x 1e6 = 12 MB per
frame; at 60 fps that is 720 MB/s (about 5.8 Gbit/s), far beyond a browser client's link. Computed
here (grade A arithmetic), it invalidates E4's client-side point rendering of raw positions.

Opportunities: O1 (free-parameter arbitrage) decouple clocks: the sim runs block time steps, the
viewer interpolates between snapshots. O2 (dominating composition) stream a server-rendered video
or a decimated LOD set plus a density texture instead of raw positions; satisfies E4's 60 fps and
E1's integrator freedom at a payload set by video bitrate, not N.

Integrated answer: Barnes-Hut on GPU with block time steps and KDK leapfrog [C3, C7, C12]; sim and
render clocks decoupled [O1]; transport via server-side render or LOD stream [Q5 derivation, O2];
WebGPU path pending fact-checker with WebGL2 fallback [K4]. Dissent: E2's FMM preference, reversible
if N grows 10x or a faster FMM implementation is benchmarked.

More templates and a fuller example: [worksheets](references/worksheets.md).

## Anti-patterns

- Summarising each expert in turn, then appending "overall" paragraph (stapled report).
- Resolving a T1 conflict by picking a side (both were right in their own vocabulary).
- Treating three experts that read the same blog post as three independent confirmations.
- Fixing a seam by assumption ("the network will handle it") instead of a two-line computation.
- Promoting an emergent idea to the headline without a feasibility check.
- Re-asking every expert to "review the synthesis": ask only the owner of each disputed claim, with
  the specific claim id and counter-evidence.

## Output

Follow output-contract. `## Result`: the Answer section plus the decisions table. `## Evidence`:
claim ids with grades for every load-bearing claim and the conflict outcomes. `## Files`: the workspace
paths (`integrated.md` first, with line anchors for Dissent and Gaps). `## Open doubts`: unfilled
load-bearing gaps and T5 value conflicts, each with the decision the caller must make.
`## Confidence`: driven by the weakest load-bearing claim, not by the average.
