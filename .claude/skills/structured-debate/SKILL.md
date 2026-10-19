---
name: structured-debate
description: "Structured debate protocol for 2-4 agents: motion framing, criteria and burden of proof fixed in advance, assigned positions, opening / rebuttal / cross-examination / closing rounds with word limits, evidence rules with binding fact-checks, a moderator flow ledger, a bias-resistant judging rubric, and extraction of the decision, its boundary conditions and the hidden assumptions from the transcript. Load when a decision must be stress-tested from opposing sides."
when_to_use: "debate-moderator; choosing between 2-4 options with real trade-offs, attacking a favoured plan before commitment, or surfacing the assumptions a decision silently rests on. Not for facts that can be looked up (fact-checker), numeric estimates (delphi-method) or ranking many candidate solutions (mediator-voting)."
---

# Structured debate

A debate is a tool for **decisions**, not for truth-finding about facts. It forces each option's
strongest case into the open, makes every claim answerable, and produces a transcript from which
you can read off the decision, the conditions under which it would flip, and the premises nobody
tested. Research on LLM debate is encouraging but bounded: multi-agent debate improved factuality
and reasoning on benchmarks (Du et al., 2023), and debate helped weaker judges pick correct answers
more often than single-advocate consultancy (Khan et al., 2024). Persuasiveness is still not
correctness, and LLM judges show position, verbosity and self-preference biases (Zheng et al., 2023).
Every rule below exists to keep the verdict tied to evidence and criteria rather than rhetoric.

## 0. When to debate

| Situation | Use |
|---|---|
| 2-4 options, real trade-offs, a decision is due | debate (this skill) |
| One plan the team favours; you want it attacked | debate with the plan as the motion, or red-teaming |
| A factual question | fact-checker or quick-researcher; never debate a lookup |
| A quantity to estimate | delphi-method |
| Many candidate solutions to rank | mediator-voting (`mediate` workflow, main thread only) or judge-panel |
| Complementary expert reports to merge | expert-synthesis |

## 1. Frame the motion

Template: **"This team should <action> <scope> <by when>, instead of <status quo>."**

Checklist:
- [ ] One decision (no "and"). Compound motions split into separate debates or a multi-option format.
- [ ] Actionable and falsifiable: a judge can say yes or no; it names scope and time.
- [ ] Status quo stated explicitly; it is what happens if the motion fails.
- [ ] Neutral wording: no loaded adjectives ("modernise", "legacy", "simply").
- [ ] Definitions for every term that could be equivocated (scale, availability, done).

| Bad motion | Problem | Rewrite |
|---|---|---|
| "Microservices are better" | no decision, no scope | "Split the billing module out of the monolith this quarter, instead of keeping it in-process" |
| "We should improve reliability and move to Kubernetes" | compound | two motions, or options {stay, k8s, managed PaaS} |
| "Should we stop using the outdated ORM?" | loaded | "Replace the ORM in the orders service with hand-written SQL by Q2, instead of upgrading the ORM" |

## 2. Fix criteria and burden before positions are assigned

Write in the setup file, before any debater speaks:
- **Criteria with weights** summing to 1, each with a 1/3/5 anchor
  (e.g. availability: 1 = worse than today, 3 = equal, 5 = survives zone loss with < 30 s of write
  unavailability). Weights come from the caller; if absent, propose them and mark them as an Open
  doubt in the report rather than letting debaters argue weights mid-debate.
- **Burden of proof**: the proposition must show the change beats the status quo on the weighted
  criteria; ties go to the status quo (change has switching costs).
- **Decision threshold**: what margin is needed to act (default, section 8: a majority of judges
  and abs(S) >= 2, S the signed margin sum; a stricter threshold stated in setup.md overrides it).
- **Context files** every debater gets identically.

Criteria fixed late are rationalisation, not judgment.

## 3. Choose the format

| Format | Positions | Use when |
|---|---|---|
| Two-sided (default) | Proposition vs Opposition | binary decision |
| Multi-option | one advocate per option, 3-4 | several live alternatives; each advocate also attacks the others |
| Red / blue | blue defends a plan, red attacks; no counter-proposal required | pre-commitment stress test |
| Side-swap control | the same two agents debate twice with sides swapped | high-stakes calls; detects debater-skill effects |

Side-swap rule: if the same agent wins both runs regardless of side, the verdict measures the agent,
not the motion; decide from the flow ledger and evidence outcomes instead of the win count.

## 4. Cast the debaters and judges

- Assign positions **regardless** of what the agents believe; say so in the brief.
- Choose debaters whose discipline owns the strongest case for that side (e.g. architect for a
  migration, computer-science-expert for consistency and latency arguments, security-auditor for an
  attack-surface argument). Equal strength matters more than prestige: do not pit an
  ADVANCED-tier agent against a MEDIUM- or LOW-tier one (config/models.json) unless that asymmetry
  is the point.
- Judges: 3 by default, independent, never a debater. Prefer judges whose agent type, and where
  possible tier in config/models.json, differs from the debaters' (e.g. plan-critic, quality-control
  or a MEDIUM-tier validator judging expert debaters; never a per-call `model`/`effort`, which the
  pre-agent hook strips), and at least one judge from a discipline neither side used.
- The moderator (you, typically debate-moderator) does not judge and does not argue.

## 5. Rounds

Subagents are stateless: each round is a fresh Agent call that receives the setup file, the
transcript so far (paths) and its own side's previous statements. Both sides run **in parallel in one
message** each round, every call with `run_in_background: false` (the next round needs both
outputs). The moderator appends each output to `transcript.md` and updates `flow.md`.

| Round | Who | Content | Limit |
|---|---|---|---|
| R0 setup | moderator | motion, definitions, status quo, criteria and weights, burden, evidence rules, context paths | - |
| R1 opening | all sides | up to 5 numbered claims (P1.., O1..), each: claim, warrant, evidence tags, impact on named criteria | 600 words |
| R2 rebuttal + questions | all sides | respond to **every** opposing claim by id: concede, contest, mitigate or turn; up to 2 new claims; up to 3 cross-examination questions | 500 words |
| challenge window | moderator | dispatch evidence challenges (section 6) in parallel | - |
| R3 answers | all sides | answer each question: direct answer first (yes / no / number / unknown), then <= 80 words | 300 words |
| R4 closing | all sides | weigh the 2-3 decisive clashes against the criteria; **no new claims or evidence** | 300 words |
| R5 judgment | judges | rubric scores, winner, margin, reasons for decision (section 8) | 250 words |

Call budget for two sides: 8 debater calls + 3 judges + up to 4 fact-checks = 15. Multi-option with
4 advocates: 16 + 3 + challenges. Check `remaining_depth`, `spawns_this_session` and `budget`
before R0. At `budget="soft"` do not open a new debate: decide from the evidence in hand and report
(mid-debate: skip to closings and judgment). At `budget="hard"` only file-summarizer,
quality-control, validator and source-summarizer can be spawned, so return the decision question
(and any unrun rounds) as an Open doubt. At `remaining_depth="1"` debaters and judges must be told
not to spawn (they become leaves; the moderator runs all checks).

Moderator rules during rounds:
- A rebuttal that does not cite the claim id it answers is returned for one rewrite, then accepted
  with a "straw-man risk" note in the flow.
- An unanswered opposing claim is **dropped**; dropped claims stand as conceded in the flow, and
  judges weigh them by their impact on criteria (a dropped trivial claim does not win the debate).
- A non-answer in R3 (answering a different question, hedging without a direct answer) is logged
  as an **evasion**; judges see the log.
- Over-limit statements are truncated at the limit before relay. This is the main defence against
  judges' verbosity bias.

## 6. Evidence rules

- Every factual claim carries a tag `[E#]` with its source: URL + access date, `file:line`, command
  and output path, or a computation shown. Untagged claims are **assertions** and judges are told to
  weigh them as such.
- Grades as in the stack's shared scale: A reproduced in-session, B primary source, C derivation or
  secondary source, D assertion.
- Quotes from sources: under 15 words, in quotation marks, attributed.
- **Evidence challenge**: in the challenge window each side may challenge up to 2 opposing factual
  claims. The moderator dispatches all challenges in one message, with `run_in_background: false`:
  `fact-checker` (sources), `tester` (behaviour of code or config), `quick-researcher` (small
  missing fact). Verdicts are binding: contradicted means struck from the flow; unverifiable means
  downgraded to assertion; supported means upgraded to grade A or B and immune to further challenge.
- No new evidence in closing. The moderator strikes it before relay.

## 7. The flow ledger

`flow.md` is the moderator's single source of truth; judges receive it alongside the transcript.

| Claim | Side | Text (short) | Evidence | R2 response | Challenge | CX | Status |
|---|---|---|---|---|---|---|---|
| P2 | Prop | writes grow 3x per year, primary saturates in 18 months | dashboard export [E3] | O contests: promo spike | fact-check: 1.6x excl. promo | - | mitigated |
| O2 | Opp | 40 stored procedures and serializable semantics make migration high-risk | `db/procs/` count [E7] | none | - | - | dropped by Prop: stands |

Status values: `standing`, `conceded`, `dropped` (stands), `contested` (unresolved clash),
`mitigated` (stands with reduced impact), `turned` (now supports the other side), `struck` (failed
challenge), `assertion` (untagged or unverifiable).

## 8. Judging

Rubric per side, each criterion scored 1-5 with anchors (full anchors in
[briefs and rubric](references/briefs-and-rubric.md)):

| Criterion | 1 | 5 |
|---|---|---|
| support | claims rest on assertions | key claims grade A/B, warrants explicit |
| clash | ignored or straw-manned the strongest opposing claims | engaged each strong opposing claim by id |
| impact on criteria | argued things the criteria do not reward | tied every major claim to the weighted criteria |
| survival | struck or evaded under challenge and cross-examination | claims survived challenges, direct answers |
| candour | no concessions, evasions logged | conceded where warranted, no evasions |

Each judge returns: winner, margin (`narrow` 1, `clear` 2, `decisive` 3), rubric scores, reasons for
decision (RFD) citing claim ids, the decisive clash, the losing side's strongest argument, and the
single premise that, if false, would flip the verdict.

Bias controls:
- Present sides in a different order to each judge; label them by role, never by agent type or model.
- Tell judges that length is not merit and that the flow ledger outranks rhetoric.
- Require claim-id citations in the RFD; an RFD without them is returned once.

Aggregation: signed margin sum S (Prop positive). Decide for a side when a majority of judges agree
and abs(S) >= 2; otherwise report **no clear winner** and decide on the crux (section 10) by
evidence, falling back to the status quo per the burden.

## 9. Extract the decision

From the verdict, flow and RFDs, write:
1. **Decision**: the action, scoped as in the motion, and whether it is conditional.
2. **Why**: the decisive clashes with claim ids and their evidence grades.
3. **Decision boundary**: the parameter values at which the losing side would have won (from the
   clashes the RFDs called decisive). Phrase as tripwires: "revisit if sustained write growth exceeds
   2.5x per year or primary CPU exceeds 70% at peak for 2 weeks".
4. **Actions now, monitors, verifications**: each with an owner (agent or caller).
5. **What the losing side got right**: claims that stand and should shape implementation.

## 10. Extract hidden assumptions

Run these six scans over transcript and flow; each hit becomes a row in the assumption register.

| Scan | Detection | Why it matters |
|---|---|---|
| shared premise | a premise both sides used and neither contested | untested by construction; the most dangerous kind |
| crux | the premise each judge named as verdict-flipping | the decision is only as good as this premise |
| equivocation | a key term used with different meanings by the sides | the clash was partly illusory |
| unpriced number | a number driving impact with grade D | the verdict may rest on a guess |
| weight drift | a side argued as if the weights differed from R0 | reveals a disagreement about values, not facts |
| missing option | both sides attacked each other, nobody considered option C | a dominating alternative may exist |

For each decisive argument, write its Toulmin structure (claim, grounds, warrant, backing,
qualifier, rebuttal conditions; Toulmin, 1958). A warrant without backing is a hidden assumption.

Assumption register:

| A | Assumption | Used by (claim ids) | Shared? | Flips verdict? | Test | Owner |
|---|---|---|---|---|---|---|

Load-bearing assumptions (flips verdict = yes) are routed to a check before the report is final when
the check is cheap (one leaf agent); otherwise they go to Open doubts with the exact brief.

## 11. Report template

```markdown
# Debate: <motion>
## Verdict
<side>, margin <S>, judges <votes>; decision: <action + conditions>
## Setup
Status quo, criteria and weights, burden, format, debaters (role -> agent/model), judges.
## Decisive clashes
| Clash | Claims | Evidence grades | Outcome | Judges citing it |
## Decision boundary and tripwires
## Assumption register
## What the losing side got right
## Process notes
Evasions, struck claims, side-swap result, word-limit truncations, bias controls applied.
## Files
setup.md, transcript.md, flow.md, judges/J1..J3.md
```

## Worked example (compressed)

Motion: "This team should replace the single-primary PostgreSQL cluster behind the order service with
a distributed SQL database this quarter, instead of keeping the primary with two replicas."
Criteria: availability under zone loss 0.30, p99 write latency 0.25, migration risk 0.25, cost 0.20.
Prop: architect. Opp: computer-science-expert. Judges: three, of different agent types (plan-critic,
security-auditor, validator).

- R1: Prop P1 failover after zone loss caused minutes of write unavailability (postmortems [E1]);
  P2 writes grow 3x per year, primary saturates in 18 months [E3]. Opp O1 quorum replication adds a
  cross-zone round trip to every write, about 1-2 ms within a region; O2 40 stored procedures plus
  serializable-isolation behaviour differences make migration high-risk [E7]; O3 partitioning and
  vertical headroom postpone saturation by 2+ years.
- R2: Opp contests P2 as a promotion spike and challenges it. Prop turns O1: checkout's p99 write
  SLO is 50 ms, so 2 ms is immaterial. Prop never answers O2.
- Challenge: fact-checker on metrics export: growth is 1.6x excluding the promotion. P2 mitigated.
- R3: Opp asks for measured failover times; Prop answers 90 s, 4 min, 45 s.
- Verdict: Opp 2 (clear, clear), Prop 1 (narrow); S = -3. Decisive clashes: O2 dropped, P2
  mitigated. O1 judged immaterial (turn accepted).
- Decision: keep Postgres this quarter; tune failover, partition the orders table, spike a
  compatibility test of the stored procedures on the candidate database. Tripwires: sustained write
  growth > 2.5x per year or primary CPU > 70% at peak.
- Hidden assumption (shared premise): both sides assumed zone loss is the dominant availability
  risk. Neither checked the incident history; if bad deploys and schema migrations dominate, neither
  option addresses availability. Routed to quick check of `docs/postmortems/`; result goes in the
  register.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| both sides talk past each other | no claim ids, no forced response | enforce R2 by-id responses |
| verdict tracks the longer side | verbosity bias | hard word limits, truncation, judge instruction |
| debate about a fact | wrong tool | stop; fact-check; resume only on the decision |
| winner flips with side swap | debater-skill effect | decide from flow and evidence |
| criteria argued mid-debate | criteria not fixed in R0 | freeze criteria; weight disputes go to the caller |
| everyone agrees by R2 | motion not contested, or debaters ignoring assignment | re-brief with "argue the assigned side regardless of belief", or drop the debate |

Argument defects to watch for, with detection cues and moderator responses:
[argument defects](references/argument-defects.md).

## Output

Follow output-contract. `## Result`: verdict, decision, decision boundary, top load-bearing
assumptions. `## Evidence`: decisive claim ids with grades, challenge verdicts, judge votes and
margins. `## Files`: setup, transcript, flow and judge files under your `out_dir`. `## Open doubts`:
unverified load-bearing assumptions and any weight dispute for the caller. `## Confidence`: lower it
for a narrow or split verdict, a failed side-swap control, or a crux resting on grade D evidence.
