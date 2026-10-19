---
name: mediator-voting
description: "Collective decision protocol for N independent agent answers to one problem: independent generation, anonymization, cross-critique ballots, exact tallies (plurality, Borda, Schulze, approval, confidence-weighted log opinion pool), margins, near-tie debate, tie-breaks, calibration-weighted votes and dissent reporting. Load when several agents must converge on ONE answer, when running or auditing /mediate, or when a vote result looks fragile."
when_to_use: "Mediator runs, the /mediate workflow, picking one of several competing solutions to a well-posed problem, auditing a tally or a near-tie. Use judge-panel instead for multi-criteria artifacts (plans, designs, code) and bayesian-aggregation or delphi-method for numeric estimates."
---

# Mediator voting

A vote turns N independent, fallible answers into one decision plus an honest account of how
contested it was. The protocol below is the one `mediator` follows and `/mediate` implements in code.
Its job is not to find consensus; it is to make the aggregation rule explicit, declared in advance,
robust to the known LLM-ensemble biases, and auditable from files.

## 1. Vote, verify, or score? Decide first

| Situation | Do this instead of / before voting |
|---|---|
| Answer is mechanically checkable (tests, recomputation, proof checker, a primary source) | Verify every candidate first (`validator`, `tester`, `fact-checker`); vote only among survivors. Evidence beats votes. |
| Candidates are artifacts judged on several criteria (plans, designs, prose) | `judge-panel` (rubric scoring), not a vote |
| Output is a number or a probability | `bayesian-aggregation` (pool) or `delphi-method` (iterate) |
| Disagreement is about values or framing, not facts | `structured-debate` to surface the crux, then vote |
| One competent agent is enough (low blast radius, reversible) | Do not vote. A 5-voter mediation costs 10-20 spawns. |
| Mutually exclusive solutions to one well-posed problem, no cheap checker | **Vote with this protocol** |

## 2. Protocol at a glance

| Phase | What happens | Spawns (N voters) | Artifact in `<run>/` |
|---|---|---|---|
| 0 Frame | Problem card, answer schema, voting method and thresholds declared | 0 | `FRAME.md` |
| 1 Solve | N voters solve independently, no shared context | N (parallel) | `raw/<voter>.md` |
| 2 Anonymize | Normalize format, merge equivalent answers, label S1..Sk, fix per-voter order | 0 | `S1.md`..`Sk.md`, `labels.json` (sealed) |
| 3 Critique + ballot | Every voter critiques all candidates blind and returns a ballot | N (parallel) | `ballots.json` |
| 4 Tally | Compute the declared method in code, plus robustness | 0 | `tally.json` |
| 5 Near-tie | Debate between top-2 authors, pairwise re-vote, tie-break cascade | 2 + N (only if near-tie) | `debate.md`, `revote.json` |
| 6 Synthesize | Winner + compatible grafts from runners-up, dissent table | 0-1 | report `.md` |

`<run>` = `<out_dir>/<YYYYMMDD-HHMM>-<slug>/` with `out_dir` from your `<stack-context>` header;
the final report is `<out_dir>/<YYYYMMDD-HHMM>-<slug>.md` (output-contract offloading rule).

## 3. Phase 0 — Frame (before any spawn)

Write `FRAME.md` with:

- [ ] **Problem card**: the question in one paragraph, inputs as file paths, constraints, what a
      complete answer contains. Every voter gets the identical card.
- [ ] **Answer schema**: fixed sections every solution must use, e.g. `Answer` (<=5 lines, the
      decision itself), `Rationale`, `Assumptions`, `Risks`, `How to verify`. Comparable shape is what
      makes anonymization and clustering possible.
- [ ] **Equivalence rule**: when two answers count as the same candidate (same chosen option; same
      numeric result within a stated tolerance; same observable behaviour on the stated tests).
- [ ] **Method, declared now**: pick from the table below and write it down. Report other methods
      only as robustness checks. Choosing the method after seeing ballots is method shopping.
- [ ] **Thresholds**: near-tie margin (table in section 7), maximum debate rounds (1), weight cap.

| Situation | Method | Reason |
|---|---|---|
| Default, 3+ candidates, ranked ballots | **schulze** | Condorcet-consistent, clone-independent, resolves cycles deterministically |
| One answer is correct, voters give p(correct), calibration history exists | **logpool** (weighted) | Uses confidence intensity; compatible with proper scoring |
| Compromise matters more than a sharp optimum (naming, conventions, API shape) | **borda** | Rewards consistently high placement; clone-sensitive, so merge first |
| Gate question: which candidates are acceptable at all | **approval** | Cheap, answers "would you ship this" |
| Many samples of short final answers (self-consistency) | **plurality** | Ballots are answers, not rankings |
| Exactly 2 candidates | weighted majority | All ranked methods coincide |

## 4. Phase 1 — Independent solve

Voter roster (`/mediate` default): `computer-science-expert`, `mathematics-expert`, `architect`,
`first-principles-decomposer`, built-in `general-purpose`. Swap in the domain experts the problem
needs. Rules:

- **N odd, 3 to 7.** 5 is the default. Beyond 7, correlation between LLM voters makes marginal voters
  nearly worthless (see `bayesian-aggregation`, effective N).
- **Diversity on two axes**: agent type/perspective and tier. Model and effort come from each
  agent's tier and learned effort (`config/models.json`); the pre-agent hook strips per-call
  `model`/`effort`, so never pass them. To diversify models, mix ADVANCED-tier voters with 1-2
  MEDIUM-tier agents whose domain fits (e.g. go-expert, java-expert, kotlin-expert, julia-expert,
  python-expert, typescript-expert).
  A panel of five same-tier voters behaves like about 1.5 independent voters (section 10, rho 0.6).
  Never a LOW-tier agent as a voter on hard problems.
- **Perspective line**: append one sentence per voter ("Solve it as a complexity theorist would;
  prefer provable bounds"). Same card, different lens.
- **Independence**: one message, N parallel Agent calls, each with `run_in_background: false` (you
  need every result before Phase 2; never rely on completion order); no voter sees another's draft;
  tell every voter not to spawn subagents (the voters are leaves of this protocol). The same applies
  to the Phase 3, debate and re-vote batches.
- Use the solve brief in [ballot templates](references/ballot-templates.md#solve-brief).
- A voter that fails or returns off-schema output: one retry with the schema restated; then drop it
  and log the drop in the report (do not silently shrink N).

## 5. Phase 2 — Normalize, cluster, anonymize

1. **Normalize** each answer into the schema; cap at ~600 words (truncate Rationale, never Answer).
2. **Strip identity tells**: agent names, "as a mathematician", model names, self-references to
   tools only one agent has. Checklist in [ballot templates](references/ballot-templates.md#anonymization-checklist).
3. **Cluster equivalent answers** by the Phase 0 equivalence rule. One cluster = one candidate;
   keep the best-written member as text and list the variants as notes. Record cluster size: two
   independent agents converging is evidence, but it enters the decision through ballots, never as
   extra votes. Unmerged clones split plurality and inflate Borda.
4. **Label** S1..Sk in a fixed, content-independent order (by voter index of the first member).
   Keep `labels.json` (label -> author agent, cluster members) sealed until Phase 6.
5. **Presentation order per voter**: rotate cyclically, voter i sees S(i mod k + 1) first. This
   spreads position bias evenly; log the order used per voter.

## 6. Phase 3 — Cross-critique and ballot

Every voter receives ALL candidates (its own included, unlabelled) and returns this ballot:

```json
{"voter": "V3",
 "critique": {"S1": "fails when n=0: line 4 divides by n", "S2": "...", "S3": "..."},
 "checkable_objections": [{"target": "S1", "claim": "S1 divides by zero for empty input", "how_to_check": "run S1 with []"}],
 "ranking": ["S2", "S3", ["S1", "S4"]],
 "approvals": ["S2", "S3"],
 "p_correct": {"S1": 0.15, "S2": 0.70, "S3": 0.40, "S4": 0.10},
 "self_label": "S2"}
```

Rules given to voters (full brief: [ballot templates](references/ballot-templates.md#critique-and-ballot-brief)):
- Critique before ranking; each critique names a concrete defect or strength, not a vibe.
- `ranking`: best first, every candidate placed; a nested list means a genuine tie.
- `approvals`: candidates you would ship as-is.
- `p_correct`: probability each candidate is correct/acceptable, numeric, in [0.02, 0.98].
  For mutually exclusive candidates the tally normalizes them; do not force a sum of 1.
- `self_label`: which candidate you believe is yours, if any (used only to measure self-preference).
- Length and polish are not merit; judge the Answer and the reasons.

Mediator checks on receipt:
- **Collect in code**: each ballot is in `<run>/ballots/<Vi>.json` (else extract the fenced json
  block from the reply with code); merge with `jq -s '.' <run>/ballots/V*.json`, never by eye.
- **Consistency**: a ranking that contradicts the voter's own `p_correct` by more than 0.2 on any
  pair is flagged; ask once to reconcile, else exclude that voter from `logpool` only.
- **Checkable objections** are not voted on: route each one that targets a top-2 candidate to
  `adversarial-verifier` (or `tester` for code) before finalizing. A confirmed fatal objection
  disqualifies the candidate regardless of the tally.

## 7. Phase 4 — Tally (exact rules)

Run the declared method in code, never by eye:

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
T="$STACK/.claude/skills/mediator-voting/scripts/tally.py"
python3 "$T" <run>/ballots.json --method schulze > <run>/tally.json
python3 "$T" <run>/ballots.json --method all   # robustness view
```

[scripts/tally.py](scripts/tally.py) takes `{"candidates", "exclusive", "ballots": [{voter, ranking,
approvals, p_correct, weight, author_of}]}` and reports scores, ranking, winner or tie set, runner-up,
margin, leave-one-voter-out winners, the no-self-vote winner, self-rank stats and method agreement.
Ties are reported, never broken. Let W = total voter weight, k = number of candidates.

| Method | Score | Normalized margin (winner vs runner-up) | Near-tie if |
|---|---|---|---|
| plurality | weight of first preferences (tied firsts split equally) | (v1 - v2) / W | < 0.20 |
| approval | weight of approvals | (a1 - a2) / W | < 0.20 |
| borda | sum of w x (k - position), first = k-1 points, ties share the average | (B1 - B2) / (W(k-1)) | < 0.10 |
| schulze | candidates beaten on strongest paths (display only; ranking = unbeaten tiers) | (p[w][r] - p[r][w]) / W on strongest paths | < 0.20 or no Condorcet winner |
| logpool | P(S) proportional to exp(sum_i w_i log p_i(S) / sum_i w_i) | P1 - P2 | < 0.10 |

Always also near-tie: any leave-one-voter-out run changes the winner (`loo_stability < 1`), or the
no-self-vote winner differs from the winner.

**Schulze in four lines** (full algorithm and a cycle example in [voting math](references/voting-math.md#schulze)):
1. `d[X][Y]` = weight of voters ranking X strictly above Y.
2. Link strength `p[X][Y] = d[X][Y]` if `d[X][Y] > d[Y][X]`, else 0 (winning votes).
3. Widest paths: for each i, j, k: `p[j][k] = max(p[j][k], min(p[j][i], p[i][k]))`.
4. X beats Y iff `p[X][Y] > p[Y][X]`. Winner set = candidates beaten by nobody (several = a tie);
   rank by successive unbeaten tiers, never by the count of candidates beaten.

**Log pool**: clip p to [0.02, 0.98]; for exclusive candidates normalize each voter's vector, take
the weighted geometric mean per candidate, renormalize. For non-exclusive candidates pool each one
on the logit scale: `P = sigmoid(d * sum_i w_i logit(p_i) / sum_i w_i)`; extremizing `d > 1` only
under the conditions in `bayesian-aggregation`.

### Worked example (5 voters, 4 candidates, equal weights)

Ballots (V1 and V2 authored S1 after clustering; V3 authored S2, V4 S3, V5 S4):

| Voter | Ranking | Approvals | p_correct S1/S2/S3/S4 |
|---|---|---|---|
| V1 | S1 > S2 > S3 > S4 | S1 S2 | .7 / .5 / .2 / .1 |
| V2 | S1 > S2 > S4 > S3 | S1 S2 | .6 / .5 / .1 / .2 |
| V3 | S2 > S3 > S1 > S4 | S2 S3 | .2 / .7 / .4 / .1 |
| V4 | S3 > S2 > S4 > S1 | S3 S2 | .1 / .5 / .6 / .2 |
| V5 | S4 > S2 > S3 > S1 | S4 | .1 / .3 / .2 / .6 |

| Method | Scores S1 / S2 / S3 / S4 | Winner | Margin | LOO stable |
|---|---|---|---|---|
| plurality | 2 / 1 / 1 / 1 | S1 | 0.20 | 3/5 (fragile) |
| borda | 7 / 11 / 7 / 5 | S2 | (11-7)/15 = 0.27 | 5/5 |
| approval | 2 / 4 / 2 / 1 | S2 | 0.40 | 5/5 |
| schulze | beats 1 / 3 / 2 / 0 | S2 | (4-0)/5 = 0.80 vs S3 | 2/5 (fragile) |
| logpool | .209 / .415 / .214 / .162 | S2 | 0.20 | 5/5 |

Pairwise d: S2 beats S1 3-2, S3 4-1, S4 4-1, so S2 is the Condorcet winner. Plurality picks S1
only because the S1 cluster had two authors who both voted for themselves; the no-self run also
gives S2. Every voter ranked its own candidate first: self-preference is present but did not decide
the result. Declared method schulze: **S2 leads** (margin 0.80, Condorcet winner), but S2 beats S1
only 3-2, so dropping V3, V4 or V5 leaves S1 and S2 unbeaten together: LOO 2/5 makes it a near-tie
and Phase 5 runs (debate S2 vs S1). Report `method_sensitive: true` (plurality disagrees) with that
explanation.

## 8. Phase 5 — Near-tie: debate, re-vote, tie-break cascade

Trigger: any near-tie condition from section 7. At most ONE debate round.

1. **Debate**: spawn the authors of the top-2 candidates in parallel with `run_in_background: false`
   (same agent type as in Phase 1, hence the same tier model; they have no memory, so the brief carries their own candidate, the rival candidate and
   all critiques of both). Each returns <=300 words: concede or rebut each critique point, and may
   **patch** its own candidate (fix defects, not replace it). Brief: [debate brief](references/ballot-templates.md#debate-brief).
2. **Re-vote**: all N voters get both (patched) candidates and both rebuttals and return a pairwise
   ballot `{prefer, p_correct: {Sa, Sb}, reason}`. Decide by weighted majority.
3. **Still near-tie** (margin < 0.20 of W or LOO-fragile): tie-break cascade, first rule that
   separates them wins:
   1. Verifiable evidence: run any available check (test, recomputation, source) on both.
   2. Higher pooled p_correct (logpool over the re-vote ballots).
   3. Fewer unresolved checkable objections after `adversarial-verifier`.
   4. Cheaper to reverse: prefer the reversible, smaller-blast-radius option.
   5. Escalate: return both candidates and the crux as an Open doubt to your caller.
   Never break a tie by label order, recency or coin flip.

## 9. Phase 6 — Synthesis and dissent

**Synthesize** (mediator itself; `cross-domain-synthesizer` if the candidates span disciplines):
- Start from the winner's text. Never average two incompatible answers into a third one nobody
  voted for.
- Grafts: an element of a runner-up enters only if (a) at least one critique praised it or at least
  half of the weight approved its candidate, (b) it does not contradict a load-bearing decision of
  the winner, (c) it does not reopen a confirmed objection. Record each in a graft table
  (`element | from | why compatible | accepted/rejected`).
- If a graft changes a load-bearing claim, send the final answer through `adversarial-verifier`.

**Dissent** is mandatory output, not an appendix. Unseal `labels.json` and report:

| Voter (agent/tier) | Top choice | Rank of winner | p(winner) | Strongest objection | Addressed? |
|---|---|---|---|---|---|

Raise a **minority report** (quoted in the Result) when any holds: at least 1/3 of the weight ranked
the winner in its bottom half; a voter gave the winner p <= 0.2 with a concrete reason; no Condorcet
winner existed; the result is method-sensitive.

## 10. Calibration-weighted votes

- Default: equal weights. Self-reported confidence already enters through `p_correct`; do not also
  turn it into vote weight (double counting).
- With a resolved track record (see `bayesian-aggregation`, ledger and `pool.py weights --cap 3`;
  its default cap is 4): weight = shrunk skill score per agent type, capped at 3:1 between the
  heaviest and lightest voter. Put it in each ballot's `weight`; every formula above already uses weighted counts.
- Correlated voters (same model, same sources): give the cluster total weight
  `m / (1 + (m - 1) rho)` instead of m, default rho 0.6 for same-model voters.
- State the weights and their source in the report; an unexplained weight is an unauditable vote.

## 11. Failure modes

| Failure | Symptom | Countermeasure |
|---|---|---|
| Herding | ballots near-identical, critiques echo each other | strict Phase 1 independence; ballots submitted blind to other ballots |
| Position bias | first-shown candidate over-ranked | per-voter cyclic order; check rank vs position correlation |
| Verbosity bias | longest answer wins | normalized schema, word cap, explicit instruction |
| Self-preference | voters rank own first | `self_label`, `--no-self` run, near-tie if it flips |
| Clone splitting / teaming | near-duplicates split plurality or inflate Borda | cluster in Phase 2; Schulze default |
| Correlated majority | 4 same-tier voters outvote 1 different, correct one | tier diversity, effective-N weights, verify checkable claims |
| Confident wrong majority | vote overrides a correct minority on a checkable fact | verify-first rule (section 1); checkable objections go to verification, not to the vote |
| Condorcet cycle | no candidate beats all others | Schulze resolves; still mark near-tie and debate |
| Method shopping | method chosen after ballots | method fixed in FRAME.md; others only as robustness |
| Silent drop | a voter fails and N shrinks unreported | log every drop; if N falls below 3, stop and return an Open doubt |

## 12. Depth, cost, and the /mediate workflow

- Spawns: N solves + N ballots (+2 debate + N re-vote on near-tie) + optional verification.
  N=5 costs 10 spawns when decisive and about 17-20 when not. Check `spawns_this_session`.
- `budget="soft"`: do not start a new mediation (no new exploratory branches); finish one already
  running without the debate round, mark the result near-tie if it is one, verify and report.
  `budget="hard"`: only file-summarizer, quality-control, validator and source-summarizer may be
  spawned, so do not run this protocol; return the labelled single-agent approximation below and list
  the missing vote as an Open doubt.
- `remaining_depth` 0: you cannot run this protocol. Return an Open doubt, or produce a clearly
  labelled single-agent approximation (you write 3 approaches yourself and argue them), never
  presented as a vote.
- `remaining_depth` 1-2: voters must be leaves; say "do not spawn subagents" in every brief.
- Only if you are the main thread (no `<stack-context>` header) and the default schema fits, launch
  the saved workflow: `Workflow name=mediate args={problem, voters?: [{agentType, perspective, weight?}], method?}`
  (`model` only for agentType general-purpose: opus|sonnet|haiku; never model/effort for this stack's
  agents). A subagent runs this protocol by hand with parallel Agent calls, or returns
  `Workflow name=mediate args={...}` as an Open doubt for the main thread. The workflow runs Solve, Critique+Rank, Tally (in code), one debate round on small margins, and synthesis,
  and returns `{winner, ranking, tally, margin, dissent, final}`. Run the protocol by hand when you
  need custom clustering, non-default voters, checkable-objection routing, or weights.

## 13. Output

Follow output-contract; specialise it like this:

```markdown
## Result
Decision: S2 — <one-line answer>. Method schulze (declared in advance), margin <m> vs <runner-up>,
Condorcet winner yes|no, leave-one-out stability <k>/N, no-self winner <S>. Debate round: <outcome|not needed>.
Final answer: <synthesized answer, or path#anchor if long>
Minority report: <only if triggered: who, what, why it did not prevail>
## Evidence
Vote table (method x candidate), pairwise matrix for the top 3, graft table, verified objections.
## Files
- <out_dir>/<stamp>-<slug>.md — full report (candidates, critiques, ballots, tally, debate, dissent)
- <out_dir>/<stamp>-<slug>/ballots.json, tally.json
## Open doubts
Unresolved checkable objections, method sensitivity, dropped voters.
## Confidence
Pooled p(winner correct) from logpool, adjusted down for near-ties and low effective N.
```

## References

- [Voting math](references/voting-math.md): every method step by step, Schulze on a Condorcet
  cycle, log-pool derivation, properties table, margin and robustness definitions.
- [Ballot templates](references/ballot-templates.md): solve, critique+ballot, debate, re-vote and
  synthesis briefs; anonymization checklist; JSON schemas.
- [scripts/tally.py](scripts/tally.py): the reference tally (stdlib Python, deterministic).
