---
name: orchestration-patterns
description: "Catalog of this stack's multi-agent patterns (single delegate, pipeline, fan-out/fan-in, swarm, mesh/blackboard, ensemble, mediator vote, judge panel, adversarial verify, loop-until-dry, completeness critic) with a selection procedure, depth and spawn preconditions, cost/latency formulas, and the mapping to agents and saved workflows. Load when routing a request or deciding how to structure multi-agent work."
when_to_use: "Before dispatching anything bigger than one specialist call; when choosing between /swarm-run, /fanout, /mediate, /expert-panel, /research-sweep, /review-verify and /plan-tournament; when a running orchestration is not converging and needs a different shape."
---

# Orchestration patterns

A pattern is three things: a **topology** (who talks to whom), a **termination rule** (when it stops),
and a **merge rule** (how many outputs become one). Pick the cheapest pattern whose merge rule gives
the confidence the request needs. Everything here composes: a pipeline stage can be a fan-out, a swarm
shard can be an ensemble, a mediator vote can settle one contested node of a DAG.

Per-pattern cards (topology sketches, brief skeletons, failure modes) live in
[pattern cards](references/pattern-cards.md). Exact saved-workflow arguments, returns and costs live in
[workflow invocations](references/workflow-invocations.md).

## 1. Selection procedure (first match wins)

Answer in order. Stop at the first "yes".

| # | Question | If yes |
|---|----------|--------|
| 0 | Is it conversation, a definition, or something you can answer correctly from context in under a minute? | Answer directly (or `general-chat`). No spawn. |
| 1 | Can ONE specialist finish it inside its own `maxTurns` with no cross-checking needed? | **Single delegate** to that specialist. |
| 2 | Are there 2-5 dependent phases with different skills (plan, build, test, verify)? | **Pipeline**; hand to `orchestrator` if more than 3 phases or any phase needs a validation gate. |
| 3 | Are there N independent items of the same kind and a known agent type per item? | **Fan-out/fan-in** (`concurrent-dispatcher`; `/fanout` when N > 8 only if you are the main thread, i.e. no `<stack-context>` header). |
| 4 | Is it one big job that must be partitioned, with coverage tracking, dedup and a merged result? | **Swarm** (`swarm-coordinator`; `/swarm-run` when shards > 6 only if you are the main thread). |
| 5 | Must specialists react to each other's partial results over several rounds? | **Mesh/blackboard** (`mesh-router`). |
| 6 | Does it span 2+ disciplines whose answers are complementary pieces of one solution? | **Ensemble** (`ensemble-assembler` then `cross-domain-synthesizer`). |
| 7 | Is there one question with several plausible competing answers and you need the best one? | Competing-answer family, see 1a. |
| 8 | Is the output a set of claims or findings that will be acted on and might be false? | Add **adversarial verify** (`adversarial-verifier`; `/review-verify` for code). |
| 9 | Is the size of the answer set unknown (bugs, sources, edge cases)? | Wrap discovery in **loop-until-dry** and finish with a **completeness critic**. |

Rows 8 and 9 are modifiers: they attach to whatever rows 1-7 chose. Every `/workflow` named in this
skill is main-thread only (section 4); a subagent uses the owner agent or the manual fallback instead.

### 1a. Competing-answer family

| Answer type | Pattern | Owner / workflow |
|-------------|---------|------------------|
| Discrete solutions (designs, algorithms, proofs, fixes) | Mediator vote (Schulze default) | `mediator`, `/mediate` |
| Plans or roadmaps | Judge panel tournament | `/plan-tournament` (planner, architect, plan-critic) |
| Numeric estimate or probability | Delphi panel | `expert-panel-chair`, `/expert-panel` with `estimate: true` |
| Binary go/no-go with trade-offs | Structured debate | `debate-moderator` |
| Free-form artifacts judged on a rubric | Judge panel | `mediator` with `judge-panel` skill, or `/plan-tournament` shape |

## 2. Pattern table

| Pattern | Topology | Owner agent | Saved workflow | Merge rule | Caller route (agent / workflow / self) |
|---------|----------|-------------|----------------|------------|-----------------------|
| Single delegate | caller -> 1 | caller | none | none | 1 (specialist) |
| Pipeline | A -> B -> C (files between stages) | `orchestrator` | none (or a chain of workflows) | last stage wins, gates in between | 3 / - / 1 |
| Fan-out/fan-in | caller -> N parallel -> collate | `concurrent-dispatcher` | `/fanout` | collation table, no judgement | 3 / main / 1 |
| Swarm | coordinator -> S shards -> normalize -> merge | `swarm-coordinator` | `/swarm-run` | dedup by key + coverage ledger | 3 / main / 1 |
| Mesh/blackboard | router <-> P specialists via `.stack/blackboard/<task-id>/` | `mesh-router` | none | router decision posts + FINAL.md | 3 / - / 1 |
| Ensemble | assembler -> k experts -> synthesizer | `ensemble-assembler` | none (`/expert-panel` for estimates) | provenance table, conflict matrix | 3 / main / 2 |
| Mediator vote | N solvers -> blind cross-critique -> tally -> synth | `mediator` | `/mediate` | declared voting rule + margin | 3 / main / 1 |
| Judge panel | N angles -> J blind judges -> graft synth | `mediator` or `planner` | `/plan-tournament` | rubric scores, winner + grafts | 3 / main / 1 |
| Adversarial verify | claim -> V refuters (distinct lenses) | `adversarial-verifier` | `/review-verify` | survives iff at least ceil(V/2) not refuted | 1 / main / 1 |
| Loop-until-dry | finders x rounds until K dry rounds | any orchestrator | inside `/research-sweep`, `/review-verify` | dedup against everything seen | - / main / 1 |
| Completeness critic | one critic over the result | `quality-control`, `plan-critic` | inside `/research-sweep` | gaps become next round | 1 / main / 1 |

The last column is what the CALLER needs to run the pattern three ways: by spawning the owner agent
(a coordinator, so `remaining_depth` at least 3 per `delegation-protocol`), by calling the saved
workflow (`main` = main thread only: no `<stack-context>` header; for any subagent the workflow route
is `-`, return `Workflow name=<w> args={...}` as an Open doubt instead), or by running it yourself with
leaf workers (`remaining_depth` at least 1; 2 for ensembles because experts escalate doubts to
leaves). `-` means no such route.

## 3. Cost and latency

Let `c` be the token cost of one typical specialist call, `L` its wall-clock time, `S` the size of
one solution or report in tokens, `W` the workflow concurrency (the
`CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` value, 16 in this stack; unset, `min(16, max(2, CPUs-2))`).

| Pattern | Tokens | Wall clock | Spawns |
|---------|--------|------------|--------|
| Single delegate | `c` | `L` | 1 |
| Pipeline, k stages | `sum(c_i)` | `sum(L_i)` | k |
| Fan-out, N items, Agent batches of 20 | `N*c + collate` | `ceil(N/20) * max(L in batch)` | N + retries |
| `/fanout`, N items | `N*c` | about `ceil(N/W) * mean(L)` (no batch barrier) | N + retries |
| Swarm, S shards | `S*(c_w + c_norm) + c_merge` | `L_w + L_norm + L_merge` (pipelined) | 2S + 1 |
| Mesh, P participants, R rounds | `sum_r P_r*(c + B_r)`, `B_r` = board tokens read in round r | `R * L` | `sum_r P_r` + 1 |
| Ensemble, k experts | `k*c_e + c_synth`, synth reads `k*S` | `L_e + L_synth` | k + 1 (+ challenger) |
| Mediator, N voters | `N*c_solve + N*(N*S + c_crit) + c_synth` | 3-4 `L` (+2 on debate) | 2N + 1 (+N on re-vote) |
| Judge panel, N attempts, J judges | `N*c + J*N*S + c_synth` | 3 `L` | N + J + 1 |
| Adversarial verify, F findings, V lenses | `F*V*c_v` | `L_v` | F*V |
| Loop-until-dry, R rounds | `sum_r (finders*c + fresh_r*V*c_v)` | `R * (L_f + L_v)` | grows with R |

Rules of thumb that hold in practice:

- The mediator critique term is quadratic: N=5 voters reading 5 solutions of 3k tokens is 75k read
  tokens; N=7 is 147k. Keep N at 3-5 unless solutions are short (under 1k tokens).
- Mesh cost grows with board size, not with rounds alone. Cap posts at about 400 words and make
  participants read `board.md` plus only the posts they are routed to.
- A barrier wastes `(L_max - L_mean)` per worker per stage. Use barriers only for cross-item dedup,
  voting, or early exit (zero findings, skip verification).
- Agent choice is the biggest lever: a LOW-tier agent (`file-summarizer`, `source-summarizer`,
  `web-scraper`) is roughly an order of magnitude cheaper than an ADVANCED xhigh agent. Put LOW-tier
  agents on mechanical stages (normalize, summarize, collate) and keep ADVANCED agents for solve, judge
  and refute; never pass `model`/`effort` on an Agent call. See `effort-and-model-selection`.
- Verification spend should scale with blast radius, not with how confident the author sounds:
  1 refuter for internal notes, 3 lenses for anything that ships, 5 for security or irreversible actions.

## 4. Preconditions: depth and spawn budget

Read the header first: `<stack-context depth=".." max_depth="8" parent=".." remaining_depth=".."
spawns_this_session=".." budget="ok|soft|hard" prompt_tokens="used/120M" session_tokens="used/3B"
out_dir=".."/>`. No header means you are the main thread (the only caller that can launch workflows).

| `remaining_depth` | What you may run |
|-------------------|------------------|
| 0 | Nothing. Do the work yourself or return Open doubts. |
| 1 | Leaf workers only: run fan-out, swarm, verify or judge panels yourself with leaves (researchers, summarizers, testers, verifiers, reviewers). |
| 2 | Leaves only. Saved workflows are main-thread only (no `<stack-context>` header): a subagent fans out with parallel Agent calls itself or returns `Workflow name=<w> args={...}` as an Open doubt. No coordinator agents. |
| 3+ | Coordinator agents too (`orchestrator`, `swarm-coordinator`, `mesh-router`, `ensemble-assembler`, `concurrent-dispatcher`, `mediator`, `expert-panel-chair`, `debate-moderator`, `deep-researcher`). |
| `budget="soft"` | Converge: no new exploratory branches or fan-outs; finish, verify, report. |
| `budget="hard"` | Spawn only `file-summarizer`, `quality-control`, `validator`, `source-summarizer`; wrap up and list gaps as Open doubts. |

Spawn budget (same rule as `delegation-protocol`): `B = max_spawns_per_session` in
`config/policy.json` (400 as shipped), headroom `H = B - spawns_this_session`.

```
planned = workers + retry reserve (10-20% of workers) + merge/synth agents + verifiers
          (+ every agent a saved workflow will launch)
proceed iff planned <= H / 2;   H < 20 -> no new fan-outs, single essential spawns only
```

If it fails: shrink (fewer, larger shards; fewer voters; cheaper verify), or return an Open doubt to
the caller with the planned count. A hook denial ("Stack spawn budget exhausted", "Stack depth limit
reached", "Token budget exhausted" or "Spawn policy:") is final for that call: never retry it; do the
part yourself or return it.

The Workflow tool exists only on the main thread (no `<stack-context>` header); Claude Code removes it
from every subagent. As a subagent never plan a Workflow call: fan out with parallel Agent calls (see
`concurrent-fanout`) or return `Workflow name=<w> args={...}` as an Open doubt for the main thread.

## 5. Composition recipes

| Goal | Chain | Notes |
|------|-------|-------|
| Ship a feature | `planner` -> waves of domain experts (e.g. `rust-expert`, `go-expert`; fan-out per DAG wave) -> `tester` + `/review-verify` -> `validator` -> `quality-control` | `orchestrator` owns it; plan in `planning-dag` format. |
| Answer a research question | `/research-sweep` (depth by stakes) -> `quality-control` | Use `quick-researcher` alone if one fact. |
| Cross-domain design | `ensemble-assembler` -> `cross-domain-synthesizer` -> `plan-critic` or 3-lens adversarial verify -> `quality-control` | Contested sub-question inside: `/mediate` on that sub-question only. |
| Choose an architecture | `/plan-tournament` (angles: mvp-first, risk-first, performance-first) -> `plan-critic` | `architect` for system level. |
| Codebase audit | `/swarm-run` by directory with `agentType: reviewer` -> dedup -> `/review-verify` on the survivors | Coverage ledger must list every directory. |
| Forecast or sizing | `/expert-panel` with `estimate: true` -> `quality-control` | Report median, IQR, dissent. |
| Hard bug with many hypotheses | swarm by hypothesis (`debugger` x H, each with one hypothesis) -> `adversarial-verifier` on the winner | Stop when one hypothesis reproduces. |
| Specialists must negotiate (API contract, protocol, threat model) | `mesh-router` with 3-5 participants -> decision posts -> `quality-control` | Cap 6 rounds. |

## 6. Signals to switch pattern mid-flight

| Observation | Switch to |
|-------------|-----------|
| Fan-out results contradict each other on the same question | Mediator vote on the contradicting items only |
| Swarm workers keep returning cross-shard questions ("depends on what module X does") | Mesh for the coupled shards, swarm for the rest |
| Mesh open-item count not falling for 2 rounds | Router forces a decision: spawns `mediator` on the stuck question (needs remaining_depth >= 3; `/mediate` is main-thread only) |
| Ensemble experts disagree on a sub-question both own | `mediator` or `debate-moderator` on that sub-question; others proceed |
| Loop-until-dry still finding new items after 4 rounds | Re-shard: the finders are under-scoped, not unlucky |
| Mediator margin below threshold after debate round | Report the tie with dissent; do not manufacture a winner |
| Verify refutes more than half of findings | Quality problem upstream: tighten finder briefs, re-run finders, not verifiers |

## 7. Anti-patterns seen in production

1. **Orchestrator under an orchestrator at `remaining_depth` 2.** Workers end at depth 0 and cannot
   escalate doubts; quality silently drops. Flatten: call the specialists directly.
2. **Voting on complementary answers.** Security and performance findings are not rivals. Use
   synthesis (ensemble) for complements, voting for substitutes.
3. **Swarm without a coverage ledger.** A dead shard reads like "nothing found there". Every shard
   ends in exactly one status; dropped shards are logged in the result.
4. **Mesh for work with no cross-talk.** If no participant ever reads another's post, you paid R
   serial rounds for a fan-out.
5. **Barrier between independent stages.** Use `pipeline()` semantics; barrier only for dedup/vote/exit.
6. **Self-verification.** The author never verifies its own claim. Verifiers get the claim and the
   evidence pointers, not the author's reasoning.
7. **Correlated ensembles.** Seven ADVANCED-tier experts with overlapping remits produce one opinion
   seven times. Diversify by choosing agents from different tiers and disciplines and by framing
   (per-call model/effort is stripped by the pre-agent hook); cap at the disciplines actually load-bearing.
8. **Blobs in briefs.** Paste paths and line anchors, not 40k tokens of content. Children read files.
9. **Re-verifying the same claim.** Dedup by a normalized key before verification; keep a seen-set
   across rounds (dedup against everything seen, not only against confirmed items, or rejected items
   reappear every round and the loop never dries).
10. **Silent caps.** Top-N, sampling, skipped retries: always state what was dropped and why.

## 8. Worked routing examples

**A. "Summarize these 30 RFCs into one-paragraph notes each."**
Row 3 (independent, homogeneous, N=30 > 8). `/fanout` (main thread only) with `agentType:
source-summarizer` (already LOW tier with low effort; never pass `model`/`effort` for a stack
agentType), schema `{id, summary, key_terms}`. Spawns 30 + up to 30 retries
(reserve 5). Wall clock about `ceil(30/16)` x 1 call. No verification: summaries are not acted on.

**B. "Audit this 1,400-file monorepo for concurrency bugs."**
Row 4 (partition, coverage, dedup). `/swarm-run` with shards by package, balanced by LOC
(about 25k LOC per shard -> 18 shards), `agentType: reviewer`, merge instruction "dedup by
file:line:bug-class". Then row 8: `/review-verify` style 3-lens verify on the merged findings.
Needs the main thread (no `<stack-context>` header); a subagent such as `orchestrator` runs it
through `swarm-coordinator` (remaining_depth >= 3) or returns `Workflow name=swarm-run args={...}` as
an Open doubt. Spawns about 2*18 + 1 + 3*F; with F=25 that is 112,
so headroom must be at least 224.

**C. "Should we move the ingest service from Kafka to NATS JetStream?"**
Row 7, binary decision with trade-offs -> `debate-moderator` (positions: migrate, stay, hybrid),
fed by one `deep-researcher` pass on operational evidence. Not a mediator vote: there is one decision,
not N candidate solutions.

**D. "Design a differentiable path tracer for inverse rendering of molecular orbitals on GPU."**
Row 6. Disciplines: rendering (`computer-graphics-expert`, lead), numerics and gradients
(`mathematics-expert`), quantum chemistry inputs (`physics-expert`), GPU performance
(`cpp-expert` or `code-optimizer`), challenger `first-principles-decomposer`. Ensemble of 5, then
`cross-domain-synthesizer`. If the experts split on "edge sampling vs reparameterization" for
visibility gradients, run `/mediate` (main thread) or `mediator` (subagent) on that sub-question alone.

**E. "Find every place we log PII."**
Rows 4 + 9. Swarm by directory with `Grep`-heavy LOW/MEDIUM-tier workers (e.g. `code-quality-analyst`, or
`general-purpose` with `model: haiku` inside `/swarm-run` on the main thread), loop-until-dry with
varied search angles (by field name, by logger call, by serializer), then a completeness critic
asking which logging paths (structured loggers, panic handlers, tracing spans) were never searched.

## 9. Routing note template

Write this (5-10 lines) before dispatching anything beyond a single delegate; it goes in Evidence.

```
Pattern: swarm (+ adversarial verify)      Owner: swarm-coordinator via /swarm-run
Why: 1,400 files, independent shards, need coverage + dedup; findings ship -> verify
Depth: main thread (no header; workflows allowed)  Spawns: planned 112, H=363, H/2=181 -> ok
Merge rule: dedup file:line:class, union; verify survive iff >=2 of 3 lenses not refuted
Termination: all shards done|failed|dropped (logged); verify complete
Cost class: high (reviewer [ADVANCED] x18, file-summarizer [LOW] normalize, adversarial-verifier [ADVANCED] verify)
Fallback (subagent caller): swarm-coordinator, or concurrent-fanout batches of at most 20 Agent calls with run_in_background: false
```
