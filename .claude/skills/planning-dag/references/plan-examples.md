# Plan examples and anti-patterns

Four complete plans, a re-plan walkthrough, and the mistakes plan-critic finds most often. Every
example validates with `python3 .claude/skills/planning-dag/scripts/dag.py <file>` (ERRORS: none);
the numbers below are that script's output.

## 1. Code change: per-client rate limiting (full dag.json)

```json
{
  "plan_id": "ratelimit-go",
  "plan_version": 1,
  "requires_depth": 2,
  "goal": "Per-client rate limiting on the public HTTP API of service ledgerd, with tests and docs",
  "done_when": ["requests above the configured rate per API key get HTTP 429 with Retry-After", "go test -race ./... exits 0", "docs/ratelimit.md documents every new config key"],
  "assumptions": ["single-region deployment; in-process limiter acceptable for v1"],
  "nodes": [
    {"id": "R1", "title": "Survey middleware chain and config loading", "phase": "research", "owner": "go-expert", "deps": [], "inputs": ["internal/http/", "internal/config/"], "writes": [".stack/out/go-expert/survey-middleware.md"], "acceptance": ["lists every middleware in order with file:line", "names where per-request API key is available"], "verify": {"method": "review", "by": "architect"}, "risk": {"likelihood": 1, "impact": 1}, "est_turns": 4, "status": "pending"},
    {"id": "R2", "title": "Token bucket vs sliding window; golang.org/x/time/rate fit", "phase": "research", "owner": "quick-researcher", "deps": [], "inputs": [], "writes": [".stack/out/quick-researcher/limiter-options.md"], "acceptance": ["2+ primary sources with URL and date", "recommendation with burst semantics"], "verify": {"method": "citation-check", "by": "architect"}, "risk": {"likelihood": 1, "impact": 1}, "est_turns": 3, "status": "pending"},
    {"id": "D1", "title": "Design: algorithm, keying, storage, config schema", "phase": "design", "owner": "architect", "deps": ["R1", "R2"], "inputs": [".stack/out/go-expert/survey-middleware.md", ".stack/out/quick-researcher/limiter-options.md"], "writes": [".stack/out/architect/ratelimit-adr.md"], "acceptance": ["ADR with 2+ rejected alternatives", "config keys named with defaults", "memory bound per key stated"], "verify": {"method": "review", "by": "plan-critic"}, "risk": {"likelihood": 2, "impact": 2, "mitigation": "plan-critic reviews before implementation"}, "est_turns": 8, "status": "pending"},
    {"id": "I1", "title": "Implement limiter middleware", "phase": "implement", "owner": "go-expert", "deps": ["D1"], "inputs": [".stack/out/architect/ratelimit-adr.md"], "writes": ["internal/ratelimit/limiter.go", "internal/http/middleware.go"], "acceptance": ["go build ./... exits 0", "429 + Retry-After on exceed"], "verify": {"method": "command", "by": "validator", "how": "go build ./... && go vet ./..."}, "risk": {"likelihood": 2, "impact": 3, "mitigation": "feature flag RATE_LIMIT_ENABLED default off"}, "est_turns": 12, "status": "pending"},
    {"id": "T1", "title": "Tests from the ADR (table-driven + concurrency)", "phase": "implement", "owner": "tester", "deps": ["D1"], "inputs": [".stack/out/architect/ratelimit-adr.md"], "writes": ["internal/ratelimit/limiter_test.go"], "acceptance": ["covers burst, refill, per-key isolation, 1000 concurrent goroutines", "fails before I1 lands"], "verify": {"method": "test", "by": "validator"}, "risk": {"likelihood": 1, "impact": 2}, "est_turns": 8, "status": "pending"},
    {"id": "I2", "title": "Config keys and docs", "phase": "implement", "owner": "go-expert", "deps": ["D1"], "inputs": [".stack/out/architect/ratelimit-adr.md"], "writes": ["internal/config/ratelimit.go", "docs/ratelimit.md"], "acceptance": ["every key in the ADR exists with its default", "docs/ratelimit.md lists all keys"], "verify": {"method": "command", "by": "validator", "how": "grep -c 'rate_limit' docs/ratelimit.md"}, "risk": {"likelihood": 1, "impact": 1}, "est_turns": 4, "status": "pending"},
    {"id": "V1", "title": "Gate: race tests, vet, lint", "phase": "verify", "owner": "validator", "deps": ["I1", "T1", "I2"], "inputs": [], "writes": [".stack/out/validator/ratelimit-gate.md"], "acceptance": ["go test -race ./... exits 0", "golangci-lint run exits 0"], "verify": {"method": "command", "by": "validator", "how": "go test -race ./... && golangci-lint run"}, "risk": {"likelihood": 2, "impact": 2, "mitigation": "one fix loop via go-expert"}, "est_turns": 3, "status": "pending"},
    {"id": "RV", "title": "Review limiter and middleware", "phase": "verify", "owner": "reviewer", "deps": ["I1", "T1"], "inputs": ["internal/ratelimit/", "internal/http/middleware.go"], "writes": [".stack/out/reviewer/ratelimit-review.md"], "acceptance": ["no unresolved high-severity finding"], "verify": {"method": "adversarial", "by": "adversarial-verifier"}, "risk": {"likelihood": 2, "impact": 2, "mitigation": "findings verified before fix loop"}, "est_turns": 6, "status": "pending"},
    {"id": "QC", "title": "Final gate against done_when", "phase": "verify", "owner": "quality-control", "deps": ["V1", "RV", "I2"], "inputs": [".stack/out/validator/ratelimit-gate.md", ".stack/out/reviewer/ratelimit-review.md"], "writes": [".stack/out/quality-control/ratelimit-ship.md"], "acceptance": ["every done_when item traced to evidence", "verdict ship or fix-first"], "verify": {"method": "review", "by": "caller"}, "risk": {"likelihood": 1, "impact": 1}, "est_turns": 3, "status": "pending"}
  ],
  "replan_triggers": ["any node fails twice", "D1 rejects in-process limiter", "critical path grows above 50 turns"],
  "replan_log": []
}
```

dag.py: waves W0 R1, R2 | W1 D1 | W2 I1, T1, I2 | W3 RV, V1 | W4 QC. Critical path
R1 -> D1 -> I1 -> RV -> QC, L = 33, W = 51, P = 1.55. Ready at start: R1, R2.

## 2. Re-plan walkthrough (same plan, version 2)

State: R1, R2, D1, T1, I2 done. I1 failed its validator gate twice; the evidence shows the API key is
not yet in the request context when the limiter runs, because auth middleware is registered after it.

Patch (DAG patch from planner, not a fresh plan):
- I1 -> `cancelled`.
- I1a "limiter core, no wiring" (go-expert, writes `internal/ratelimit/limiter.go`, 6 turns, deps D1).
- X1 "move auth ahead of the limiter slot" (go-expert, writes `internal/http/router.go`, 4 turns,
  deps D1, risk 2 x 3 with mitigation "router order test" and rollback "revert router.go").
- I1b "wire limiter after auth" (go-expert, writes `internal/http/middleware.go`, 3 turns, deps I1a, X1).
- V1 and RV now depend on I1b instead of I1.

`replan_log` entry:

```json
{"version": 2, "trigger": "I1 failed its gate twice",
 "change": "I1 cancelled; split into I1a (core) and I1b (wiring); X1 inserted to reorder auth before the limiter; RV and V1 now depend on I1b",
 "reason": "validator evidence: API key not yet set in request context when the limiter runs"}
```

dag.py on v2: critical path R1 -> D1 -> I1a -> I1b -> RV -> QC, L = 30 (splitting the zero-slack
node shortened the plan by 3 turns even after adding X1), remaining critical length 18, ready now
I1a, X1 (one message, two Agent calls; disjoint write-sets).

Note that the cancelled node is removed from `nodes` (kept in the v1 file and the ledger) so its
successors do not wait for it; a `skipped` node would instead count as finished.

## 3. Research report

Goal: cited report on the performance cost and adoption of hybrid post-quantum key exchange in TLS.

| id | title | owner | deps | est | slack |
|---|---|---|---|---|---|
| Q1 | sub-questions and search plan | deep-researcher | - | 3 | 0 |
| S1 | web sweep: deployment and adoption data | web-searcher | Q1 | 6 | 4 |
| S2 | papers: handshake latency and size overhead | paper-researcher | Q1 | 10 | 0 |
| S3 | crawl vendor docs and changelogs | web-crawler | Q1 | 8 | 2 |
| E1 | extract and dedup claims with sources | deep-researcher | S1, S2, S3 | 5 | 0 |
| F1 | fact-check the 15 load-bearing claims | fact-checker | E1 | 6 | 0 |
| C1 | completeness critique against the sub-questions | quality-control | E1 | 3 | 3 |
| W1 | write the cited report | deep-researcher | F1, C1 | 8 | 0 |
| QC | final gate | quality-control | W1 | 2 | 0 |

L = 34, W = 51, P = 1.50; critical path Q1 -> S2 -> E1 -> F1 -> W1 -> QC.

Lessons:
- This shape (decompose, three-modality sweep, extract, verify, critique, synthesise) is exactly what
  the research-sweep workflow runs, with loop-until-dry on the critique. When the plan you draw looks
  like this and the executor is the main thread (no <stack-context> header), make Workflow
  name=research-sweep a single node. Otherwise execute the nodes, or return
  `Workflow name=research-sweep args={question}` as an Open doubt.
- S1 and S3 have slack: run them at their cheap defaults. S2 is on the critical path: if papers are
  many, split S2 by sub-question rather than reaching for a stronger owner.
- E1 is written by deep-researcher and critiqued by quality-control (C1); deep-researcher then
  checks the critique while writing W1, so no agent grades its own output.

## 4. Multi-expert decision with a conditional vote

Goal: choose the time integrator for a GPU rigid-body solver.

| id | title | owner | deps | est | slack |
|---|---|---|---|---|---|
| F1 | frame candidates and weighted criteria | architect | - | 4 | 0 |
| E1 | stability and energy behaviour | physics-expert | F1 | 8 | 0 |
| E2 | GPU suitability: memory traffic, divergence | computer-graphics-expert | F1 | 6 | 2 |
| E3 | implementation cost, C++ reference | cpp-expert | F1 | 6 | 2 |
| X1 | integrate into a scored matrix with provenance | cross-domain-synthesizer | E1, E2, E3 | 6 | 0 |
| M1 | vote, only if X1 leaves the top two in conflict | mediator | X1 | 8 | 4 |
| P1 | benchmark the top two on the reference scene | cpp-expert | X1 | 10 | 0 |
| V1 | thresholds: drift < 0.1% over 10k steps; step <= 4 ms at 100k bodies | validator | P1 | 2 | 0 |
| QC | final gate and recommendation | quality-control | M1, V1 | 2 | 0 |

L = 32, W = 52, P = 1.62; `requires_depth: 3` because mediator is a coordinator.

M1 carries `"condition": "run only when X1 lists an unresolved conflict between the top-2
candidates; else skipped"`. The executor evaluates conditions when the node becomes ready; dag.py
does not. A false condition sets `status: skipped` with the reason in the ledger, and QC proceeds.

Lessons: experts run in one wave with scoped briefs; the benchmark (P1) turns the expert matrix into
measured evidence, and the validator gate gives V1 numeric thresholds instead of "fast enough".

## 5. Image asset pipeline

Goal: app icon set and marketing hero image for a launch.

| id | title | owner | deps | est | slack |
|---|---|---|---|---|---|
| B1 | creative brief and style guide (palette hex, type, sizes) | graphic-design-expert | - | 4 | 0 |
| G1 | 4 hero variants, 2048x1152, sidecar metadata | image-generator | B1 | 5 | 1 |
| G2 | 3 icon concepts as native SVG, viewBox 0 0 1024 1024 | vector-artist | B1 | 6 | 0 |
| C1 | rubric critique; pick one hero and one icon with fixes | graphic-design-expert | G1, G2 | 3 | 0 |
| E1 | hero: apply fixes, remove background, upscale to 4096x2304, keep original | image-editor | C1 | 4 | 0 |
| E2 | icon: fixes, svg_optimize, PNG exports 16-1024 px | vector-artist | C1 | 3 | 1 |
| V1 | sizes exist, alpha present, icon contrast >= 3:1 on light and dark | validator | E1, E2 | 2 | 0 |
| QC | every brief item traced | quality-control | V1 | 2 | 0 |

L = 21, W = 29, P = 1.38. `requires_depth: 1`: every owner is a worker. B1 and C1 are verified by
`caller` (the user approves the brief and the pick), which also keeps the designer from grading its
own brief.

## 6. Anti-patterns

| Anti-pattern | Symptom | Fix |
|---|---|---|
| activity nodes | "Research X", "Look into Y" with no artefact | name the deliverable and its path; acceptance on its content |
| false serialisation | P close to 1; edges without data, knowledge or resource reasons | delete the edge; hang spec-only work off the design node |
| self-verification | `verify.by` equals the owner for review-type checks | independent verifier; only `command` may be self-run |
| mega-node | est_turns above 0.6 x maxTurns; 6+ criteria; 3+ subsystems | split by subsystem or by reversible versus irreversible work |
| confetti plan | 30 nodes of 1-2 turns each | merge until each node carries real work; or one bulk node for homogeneous items |
| shared write-sets in a wave | two implementers touching the same file | serialise with an edge, split the file ownership, or have one return a patch |
| coordinator under a shallow executor | mediator or deep-researcher owners with requires_depth unset | set requires_depth; replace with workers or move the node up a level |
| pasted context | inputs that say "see above" or embed text | paths and upstream node ids only |
| hidden human gate | "once agreed", "after sign-off" inside a node | explicit `caller` node upstream; irreversible nodes always have one |
| late risk | high-risk node scheduled at the end of the critical path | move it as early as dependencies allow; add a spike |
| no final gate | several sinks; nobody checks done_when | validator over done_when, then one quality-control node |
| re-plan thrash | third re-plan of the same goal | stop; return Status partial with the diagnosis as an Open doubt |
| hours as estimates | wall-clock guesses for agents | estimate in owner turns; the learner tunes maxTurns, not hours |
