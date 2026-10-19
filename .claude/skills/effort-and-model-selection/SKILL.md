---
name: effort-and-model-selection
description: "Choosing who does the work in a three-tier stack: the tier table by agent from config/models.json (ADVANCED_MODEL claude-opus-5-5, MEDIUM_MODEL claude-sonnet-5-5, LOW_MODEL claude-haiku-5-5), picking a cheaper or stronger agent instead of overriding (the pre-agent hook strips per-call model/effort), categorising a task's effort for routing, turn scoping, how effort, maxTurns and autoCompactWindow are learned, and the session and per-prompt token budgets."
when_to_use: "When writing a routing plan, choosing which agent gets a task, sizing a brief against maxTurns, seating an ensemble or vote, retrying after a weak result, reacting to budget=soft/hard, or deciding whether an agent should be re-tiered."
---

# Effort and model selection

## 1. Principles

1. Tiers are authoritative. Never pass `model` or `effort` on an Agent call: the pre-agent hook
   strips both (`config/policy.json` `enforce_tiers`). Every agent runs on its tier model from
   `config/models.json` at its learned effort.
2. You control cost with two levers only: which agent you pick (section 4) and how much you put in
   its brief (section 6). `maxTurns` is not a per-call parameter either.
3. Judge cost per completed task, not per call. A cheap call that fails and is redone costs the
   cheap call plus the expensive one.
4. Spend where verification is hard and errors are expensive; save where outputs are machine-checkable.
5. Large but easy work goes to more LOW/MEDIUM agents on shards, not one ADVANCED agent on everything.
6. Optimise for context usage, not speed: fresh-context summarizers for heavy reading, paths in
   briefs, offload past ~60 lines / 3k chars. Parallelism is for independence and coverage, never latency.

## 2. The three tiers

| Tier (model id, workflow alias) | Strong at | Output-price ratio | Agents (initial effort / maxTurns) |
|---|---|---|---|
| ADVANCED_MODEL (claude-opus-5-5, `opus`) | deep reasoning, long-horizon agentic work, synthesis, review, proofs | 40x | delegator high/300, orchestrator high/300, swarm-coordinator medium/220, ensemble-assembler high/180, mediator xhigh/180, planner high/80, architect xhigh/120, plan-critic high/60, reviewer high/120, adversarial-verifier high/90, quality-control medium/70, code-optimizer high/150, security-auditor high/120, debugger high/160, deep-researcher high/240, paper-researcher high/120, computer-graphics-expert high/150, computer-science-expert xhigh/150, quantum-computing-expert xhigh/150, rust-expert high/180, cpp-expert high/180, haskell-expert high/180, mathematics-expert max/180, physics-expert xhigh/150, graphic-design-expert high/120, cross-domain-synthesizer xhigh/120, expert-panel-chair high/180, debate-moderator high/120, analogy-mapper high/90, first-principles-decomposer xhigh/90, agent-architect high/120 |
| MEDIUM_MODEL (claude-sonnet-5-5, `sonnet`) | coding, tool loops, browsing, routine judgement | 20x | mesh-router high/220, validator medium/90, tester high/150, code-quality-analyst medium/90, quick-researcher low/40, web-searcher low/50, browser-operator medium/150, computer-operator medium/150, fact-checker medium/60, go-expert high/180, julia-expert high/180, java-expert high/180, kotlin-expert high/180, python-expert high/180, typescript-expert high/180, image-generator medium/90, image-editor medium/90, vector-artist medium/90, general-chat low/35, stack-tuner medium/60 |
| LOW_MODEL (claude-haiku-5-5, `haiku`) | fast long-context reading, extraction, classification, reformatting | 1x | concurrent-dispatcher medium/150, web-scraper low/80, web-crawler medium/120, source-summarizer low/35, file-summarizer low/40 |

Effort and maxTurns are initial traits; live values: `bin/stack agents list`. Re-tier:
`bin/stack agents set NAME tier=MEDIUM_MODEL`, then `bin/stack agents tiers --apply` (stack-tuner's
call). Env vars `ADVANCED_MODEL` / `MEDIUM_MODEL` / `LOW_MODEL` override the ids, e.g. to trial a
release. List prices, October 2026, USD per million tokens (input / output): Haiku 5.5 0.10 / 0.50
(prompts up to 100K tokens), Sonnet 5.5 2 / 10, Opus 5.5 4 / 20. Prices move; recheck before quoting
dollars. Cost math: [cost and tuning math](references/cost-and-tuning-math.md).

| Effort level | Behaviour | Learner band: output tokens per run (thinking included) |
|---|---|---|
| `low` | minimal thinking, fewer and consolidated tool calls, terse replies | under 4k |
| `medium` | moderate deliberation | 4k-16k |
| `high` | thorough reasoning with self-checks | 16k-48k |
| `xhigh` | extended deliberation; best for hard coding and long agentic work | 48k-120k |
| `max` | no holding back; correctness matters far more than cost | 120k and up |

Effort is an agent trait, never a call argument. The bands are `effort_bands_output_tokens` in
`config/learning.json`; the learner classifies observed runs with them (section 7).

## 3. Categorise the task

Score the task on five signals, 0-3 each.

| Signal | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Novelty (N) | done many times; template exists | familiar with a twist | unfamiliar combination | no known approach; research-grade |
| Ambiguity (A) | fully specified, testable criteria | small gaps with safe defaults | several readings; judgement needed | the goal itself is unclear |
| Verification difficulty (V) | machine-checkable (test, schema, diff) | quick human-readable check | needs expert review or reproduction | unverifiable before consequences (proof, design, forecast) |
| Blast radius (B) | scratch or throwaway | one file or answer, easily reverted | shared code, user-facing answer, input to other decisions | security, data loss, money, production, irreversible |
| Length (L) | under 10 tool calls, under 20k tokens to read | 10-30 calls | 30-80 calls or over 100k tokens to read | over 80 calls or many files/sources |

S = N + A + V + B + L. S picks an agent class, never an override:

| S | Route to | Examples |
|---|---|---|
| 0-3 | LOW/MEDIUM leaf | file-summarizer, source-summarizer, web-scraper, quick-researcher |
| 4-6 | MEDIUM worker | fact-checker, validator, tester, web-searcher, go/java/kotlin/julia-expert |
| 7-9 | ADVANCED agent at its learned effort | reviewer, debugger, deep-researcher, rust/cpp/haskell-expert |
| 10-15 | ADVANCED agent shipped at xhigh/max, plus an independent ADVANCED verifier | architect, mathematics-expert, computer-science-expert, physics-expert, first-principles-decomposer; checked by adversarial-verifier or quality-control |

Floors: B = 3 or V = 3 means an ADVANCED owner plus an independent verifier (author and verifier
differ). A = 3 means do not route yet: return a scope doubt (doubt-escalation). L = 3 means split
first (planning-dag), then score each shard. Pure transformation of given text (summarise, extract,
format, classify) with V <= 1 always goes to a LOW agent. If the discipline's natural owner sits on
another tier than S suggests, take its cheaper or stronger alternative (section 4).

## 4. Cheaper and stronger agents by task

| Task | Typical agent (tier / initial effort) | Cheaper agent when | Stronger agent when |
|---|---|---|---|
| Condense a long file or log for one question | file-summarizer (LOW / low) | - | code judgement needed: the domain expert (ADVANCED) reads the digest |
| Summarise a fetched source | source-summarizer (LOW / low) | - | dense technical paper: paper-researcher (ADVANCED) |
| One factual lookup | quick-researcher (MEDIUM / low) | known URL: web-scraper (LOW) | broad or contested: deep-researcher (ADVANCED) |
| Multi-hop cited report | deep-researcher (ADVANCED / high) | 2-3 narrow sub-questions: quick-researcher (MEDIUM) each | main thread only: Workflow name=research-sweep |
| Verify claims | fact-checker (MEDIUM / medium) | one dated fact: quick-researcher (MEDIUM) | claim drives a high-blast decision: adversarial-verifier (ADVANCED) |
| Check criteria by running commands | validator (MEDIUM / medium) | long log to read: file-summarizer (LOW) | completeness judgement: quality-control (ADVANCED) |
| Write and run tests | tester (MEDIUM / high) | run the existing suite: validator (MEDIUM) | race or heisenbug: debugger (ADVANCED) |
| Root-cause a bug | debugger (ADVANCED / high) | reproduce only: tester (MEDIUM) | memory corruption or UB: cpp-expert or rust-expert (ADVANCED) alongside |
| Review a diff | reviewer (ADVANCED / high) | structure and complexity only: code-quality-analyst (MEDIUM) | auth, crypto, migration: security-auditor, then adversarial-verifier (ADVANCED) |
| Refute a finding | adversarial-verifier (ADVANCED / high) | trivially checkable: fact-checker or tester (MEDIUM) | proof step: mathematics-expert (ADVANCED / max) |
| Final gate | quality-control (ADVANCED / medium) | criteria are commands: validator (MEDIUM) | riskiest claim: adversarial-verifier (ADVANCED) |
| Task plan | planner (ADVANCED / high) | 5 or fewer obvious nodes: plan it yourself | system-level goal: architect (ADVANCED / xhigh) |
| System design | architect (ADVANCED / xhigh) | choice between two known designs: planner (ADVANCED / high) | architects disagree: mediator (ADVANCED / xhigh) |
| Proof or derivation | mathematics-expert (ADVANCED / max) | numeric sanity script: tester (MEDIUM) | adversarial-verifier on each proof step |
| Language work | rust/cpp/haskell-expert (ADVANCED / high); go/java/kotlin/julia-expert (MEDIUM / high) | lint or format triage: code-quality-analyst (MEDIUM) | unsafe/FFI, memory model, lock-free: computer-science-expert or rust/cpp-expert (ADVANCED) |
| Scraping and browsing | web-scraper, web-crawler (LOW) | - | JS-heavy or interactive: web-searcher, browser-operator (MEDIUM) |
| Image asset | image-generator, image-editor, vector-artist (MEDIUM / medium) | - | brand-critical: graphic-design-expert (ADVANCED) reviews |
| Chat answer | general-chat (MEDIUM / low) | - | needs sources: quick-researcher (MEDIUM) |

Every agent with its bounds and alternatives: [agent tiers and alternatives](references/agent-defaults.md).

## 5. Escalation ladder after a weak result

Move one rung at a time; never resend an identical call.

| Rung | Change | Use when |
|---|---|---|
| 0 | fix the brief: inputs, criteria, scope | Status partial or blocked for missing information. Never pay for a stronger agent to compensate for a vague brief |
| 1 | split or sharpen the scope | shallow answer, ran out of turns, several disciplines in one brief |
| 2 | a stronger-tier or more specialised agent (section 4) | reasoning error on a sound brief |
| 3 | change structure: ensemble-assembler, mediator, or adversarial-verifier to find where it breaks; main thread only: Workflow name=mediate or name=expert-panel | two failures at rung 2 |

De-escalate too: if several similar calls finished `done`, confidence 0.8 or more, well under the
turn estimate, route the next similar call to the cheaper agent.

## 6. Turn scoping

The Agent tool has no maxTurns argument, so size the brief to the target's maxTurns (M; live values
from `bin/stack agents list`).

T = (files to read / 3) + searches + fetches + 2 x edits + 2 x verification runs + 3, then T x 1.3 slack.

| T versus M | Action |
|---|---|
| T <= 0.6 M | send as one brief |
| 0.6 M < T <= M | trim scope, or instruct: "checkpoint to a file and return Status partial before running out" |
| T > M | split into shards (planning-dag) and fan out with parallel Agent calls; only the main thread (no <stack-context> header) may use Workflow name=swarm-run; a subagent returns `Workflow name=swarm-run args={...}` as an Open doubt |

Example: a reviewer with M = 120 asked to review 24 files (8 turns), run the suite twice (4), write
findings (2): T = (8 + 4 + 2 + 3) x 1.3 = 22, under 72 (0.6 M): one brief.

A run that hits maxTurns counts as a failure for the learner and pushes the agent's traits up for
everyone (section 7). Over-scoped briefs are a tax on the whole stack.

## 7. How traits are learned

SubagentStop/SessionEnd -> `bin/stack learn ingest|update|apply` (`learn run` does all three); output
to `~/.claude/stack-data/{recommendations.json,budgets.json,changes.jsonl}`.
- maxTurns: censored log-normal on tool rounds; ceil(q95 x 1.15), clamped to the bounds in
  `config/learning.json`, at most x2 or /2 per update, applied only if the change is >= max(2 turns,
  10%); needs n_eff >= 3. Capped runs are censored, so a cap that is too low pushes the estimate up.
- effort: output tokens (thinking included) binned low<4k<=medium<16k<=high<48k<=xhigh<120k<=max.
  Dirichlet with stickiness 3 on the current level picks the smallest level covering 80%. A Beta(1,4)
  capped-run rate above 0.25 escalates one level; above 0.08 it blocks de-escalation. Needs n_eff >= 5.
- autoCompactWindow (raise-only): when q95 ctx_peak > 0.8 x the current window (default 200k) and
  n_eff >= 3, set to ceil(q95 ctx_peak x 1.15 / 10k) x 10k, clamped 100k-1M (`apply_compact_window`).
- Token windows (max_output_tokens, recommend_1m_context) go to budgets.json.

Consequences for routing: misrouted work is training data. Easy jobs sent to an ADVANCED agent or
over-scoped briefs move its traits for every later caller; fix the routing, not the agent. Inspect:
`bin/stack learn report --agent NAME`, `bin/stack learn apply --dry-run`. Pin: narrow the bounds in
`config/learning.json` (stack-tuner). If an agent's tier looks wrong on most calls, return an Open
doubt routed to stack-tuner instead of routing around it forever.

## 8. Token budgets

Whole tree (`config/policy.json` `token_budget`): session 750M guaranteed / 2.25B soft / 3B max; per
prompt 30M / 90M / 120M. Header `budget="soft"`: converge, no new exploratory branches, finish,
verify, report. `budget="hard"`: only file-summarizer, quality-control, validator and
source-summarizer may be spawned; wrap up and list the gaps as Open doubts. Under soft, prefer the
cheaper column of section 4.

## 9. Ensembles, votes and judges

- Independence beats individual strength: mix agent types and tiers across members (e.g. an ADVANCED
  domain expert, a MEDIUM language expert, deep-researcher) and vary the perspective in each brief.
- Judges should not be the author's agent type when avoidable (self-preference); blind them to authorship.
- Do not seat LOW-tier agents as voters or judges on reasoning-heavy questions; use them for extraction.
- Weight members by calibration history when available (bayesian-aggregation, mediator-voting).
- Saved workflows run only from the main thread. There, `model` may be passed only for agentType
  general-purpose, as alias opus, sonnet or haiku; never `model` or `effort` for this stack's agentTypes.

## 10. Worked examples

| # | Call | N A V B L = S | Route |
|---|---|---|---|
| 1 | Find the first failing test in a 2,400-line CI log | 0 0 1 0 1 = 2 | pure extraction: file-summarizer (LOW) |
| 2 | Review a 40-line diff in JWT validation | 1 0 2 3 0 = 6 | floor B = 3: reviewer (ADVANCED), then adversarial-verifier (ADVANCED) on its findings |
| 3 | Run `pytest -q tests/api` and report each criterion | 0 0 0 1 0 = 1 | machine-checkable: validator (MEDIUM); nothing cheaper runs commands |
| 4 | Prove an amortised O(log n) bound for a new heap | 3 1 3 1 2 = 10 | mathematics-expert (ADVANCED / max) plus adversarial-verifier per step |
| 5 | Port 30 Go modules from callbacks to async | 1 0 1 2 3 | L = 3: 6 shards of 5 modules (each 1 0 1 2 1 = 5): go-expert (MEDIUM) per shard, tester (MEDIUM) gate |
| 6 | Choose the event store for a payments ledger after two architects disagreed | 3 1 3 3 1 = 11 | rung 3: mediator (ADVANCED) over both designs; main thread: Workflow name=mediate |

Dollar comparison for example 1 and a 30-source summary fan-out:
[cost and tuning math](references/cost-and-tuning-math.md).

## 11. Anti-patterns

- `model` or `effort` on an Agent call: stripped silently; the child runs on its tier anyway.
- ADVANCED agents for extraction or summarising: 20-40x the cost with no quality gain.
- LOW agents for judgement, code edits or votes.
- One agent on a huge, easy job instead of shards on cheaper agents.
- A stronger agent to fix a vague brief: fix the brief (rung 0).
- Downgrading to a cheaper agent on a high-blast task, then paying for rework and incident review.
