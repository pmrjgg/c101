# Saved workflow invocations

The stack ships seven saved workflows under `.claude/workflows/`. Only the main thread (no `<stack-context>`
header) can invoke them, with the Workflow tool by name; Claude Code removes Workflow from every
subagent. Pass `args` as a real JSON object (not a JSON-encoded string); scripts also accept a string
and parse it, but objects avoid quoting bugs.

General rules:

- Workflow agents run concurrently up to `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (the stack sets
  16; unset, `min(16, max(2, CPUs-2))`). Excess items queue; they are not dropped.
- Every workflow agent counts against the session spawn budget (`config/policy.json`).
- A workflow returns a structured object. Read the fields you need; large reports are written to
  files and the object carries the path.
- A subagent never calls Workflow: it uses the manual fallback named in each section or returns
  `Workflow name=<w> args={...}` as an Open doubt. The main thread falls back to the manual pattern
  only if a Workflow call errors, and says so in Evidence.
- `model` (opus|sonnet|haiku) and `effort` are allowed only for `agentType: general-purpose`; never
  override them for this stack's own agents (their tiers in `config/models.json` are authoritative).

---

## /fanout: generic map

```json
{ "name": "fanout",
  "args": {
    "items": ["src/a.py", "src/b.py"],
    "agentType": "code-quality-analyst",
    "promptTemplate": "Measure complexity hotspots in {{item}} (item #{{index}}). Write details to .stack/out/code-quality-analyst/fanout-cq/{{index}}.md. Return the schema.",
    "schema": { "type": "object",
      "properties": { "id": {"type": "string"}, "status": {"type": "string", "enum": ["ok", "partial", "failed"]},
                      "summary": {"type": "string"}, "file": {"type": "string"} },
      "required": ["id", "status", "summary"] },
    "retry": 1 } }
```

- Placeholders: `{{item}}`, `{{item.field}}`, `{{index}}` (0-based), `{{n}}` (1-based), `{{total}}`.
- Optional: `retry` (default 1, max 3; re-runs null, empty or thrown results), `maxItems` (default 400).
- Returns `{started, total, attempted, succeeded, results: [{index, ref, attempts, result}],
  failed: [{index, ref, attempts, reason, item}], skipped, template_warnings}`.
- Use when: N > 8 homogeneous independent items, you want schema-validated results.
- Manual fallback: `concurrent-fanout` batches of at most 20 Agent calls per message.

## /swarm-run: sharded job with merge

```json
{ "name": "swarm-run",
  "args": {
    "task": "Find concurrency bugs (data races, lock ordering, missed cancellation). Report file:line, bug class, failure scenario.",
    "shards": [ {"id": "pkg-ingest", "brief": "Scope: services/ingest/** (31k LOC)."},
                {"id": "pkg-billing", "brief": "Scope: services/billing/** (22k LOC)."} ],
    "agentType": "reviewer",
    "merge": "Dedup by file:line:bug-class; keep the most specific failure scenario; list shards with zero findings explicitly." } }
```

- Optional: `key` (dedup key definition), `retry` (default 1: uncovered remainder, bisected when
  large), `maxShards` (default 150), `outDir` (default `.stack/out/swarm-run/<slug>`).
- Returns `{started, outDir, merged, perShard, failed, coverage}`. Workers per shard (pipelined),
  per-shard normalize (`file-summarizer`, LOW tier), barrier, exact-key dedup and ledger in code, then a
  `swarm-coordinator` merge in MERGE MODE (semantic dedup, conflicts). `coverage.line` and
  `coverage.ledger` hold the coverage sentence and table; `merged.merged_path` the full result.
- Shards are easiest to produce with `.claude/skills/swarm-execution/scripts/shard_plan.py`.
- Use when: more than 6 shards, or you need normalize + merge without hand-rolling it.
- Manual fallback: `swarm-coordinator` running the `swarm-execution` procedure.

## /mediate: collective decision

```json
{ "name": "mediate",
  "args": {
    "problem": "Pick the conflict-resolution strategy for offline-first notes sync (CRDT vs OT vs LWW with merge UI). Constraints in docs/sync-constraints.md.",
    "voters": [ {"agentType": "computer-science-expert", "perspective": "consistency models"},
                {"agentType": "architect", "perspective": "operability"},
                {"agentType": "first-principles-decomposer", "perspective": "invariants"},
                {"agentType": "general-purpose", "model": "sonnet", "perspective": "user-facing behaviour"} ],
    "method": "schulze" } }
```

- Returns `{winner, ranking, tally, margin, dissent, final}`. Default voters are 5 diverse agents;
  default method Schulze. Small margin triggers one debate round between the top 2 and a re-vote.
- Use when: one question, competing discrete answers. Not for complementary sub-answers.
- Manual fallback: `mediator` agent with the `mediator-voting` skill.

## /expert-panel: Delphi

```json
{ "name": "expert-panel",
  "args": { "question": "Logical qubits needed to run Shor on RSA-2048 under a surface code at p=1e-3 physical error rate?",
            "experts": ["quantum-computing-expert", "physics-expert", "computer-science-expert"],
            "rounds": 3, "estimate": true } }
```

- `experts` entries may be agent names or `{agentType, model?, effort?, perspective?}` (`model`
  opus|sonnet|haiku and `effort` only with `agentType: general-purpose`; never for this stack's agents); omitted, the
  chair selects 4-7 panelists. `rounds` is capped at 4. `kind` (`quantity`, `probability`, `choice`,
  `open`), `unit`, `options` and `evidence` (paths) sharpen the frame; `estimate: true` implies quantity.
- Returns `{consensus, aggregate, rounds, stop, dissent, minority, confidence, report_path, ...}`.
  Feedback (median, IQR, pooled estimates, clustered arguments, fact-checked cruxes) is computed between
  rounds; stops on convergence, stability, or the round cap.
- Use when: estimates, forecasts, or judgments where anonymous iteration reduces anchoring.
- Manual fallback: `expert-panel-chair` with the `delphi-method` skill.

## /research-sweep: multi-modal research

```json
{ "name": "research-sweep",
  "args": { "question": "State of production-grade WebGPU compute for sparse linear algebra in 2026", "depth": "standard" } }
```

- Returns `{report_path, summary, claims, gaps}`. Plan (sub-questions) -> sweep per sub-question
  (web, papers, crawl) -> deep read -> fact-check deduped key claims -> completeness critic loop ->
  cited report (default `.stack/out/research-sweep/<slug>.md`).
- Depth: `quick` for orientation, `standard` default, `exhaustive` for decisions with money or
  safety attached.
- Manual fallback: `deep-researcher` with the `deep-research` skill.

## /review-verify: code review with adversarial verification

```json
{ "name": "review-verify",
  "args": { "target": "origin/main..HEAD", "dimensions": ["correctness", "security", "concurrency", "tests"] } }
```

- Returns ranked confirmed findings and the rejected list. One reviewer per dimension (security via
  `security-auditor`, performance via `code-optimizer`), dedup by file+line+summary, 3 verifier lenses
  per finding, survive iff at least 2 not refuted.
- Manual fallback: `reviewer` per dimension in one message, then `adversarial-verifier` x3 per finding.

## /plan-tournament: competing plans

```json
{ "name": "plan-tournament",
  "args": { "goal": "Migrate the monolith's job queue to a durable workflow engine with zero lost jobs", "angles": ["mvp-first", "risk-first", "performance-first"], "judges": 3 } }
```

- Returns `{plan_path, plan, scores, critique}`. A planner per angle (`architect` for system level),
  blind rubric judging (feasibility, risk, cost, verifiability, completeness), synthesis with grafts,
  `plan-critic` red-team, one revision.
- Manual fallback: `planner`/`architect` per angle in one message, `judge-panel` scoring, `plan-critic`.

---

## Cost classes (order of magnitude, for the routing note)

| Workflow | Typical spawns | Cost class |
|----------|----------------|------------|
| /fanout N | N to 2N | low to medium, scales with the agent's tier |
| /swarm-run S | 2S + 1 | medium to high |
| /mediate | 2N + 1 (+2 rebuttals and N re-votes on a near tie) | high (quadratic critique reading) |
| /expert-panel | experts x rounds + 2 | medium to high |
| /research-sweep | 10-60 by depth | high |
| /review-verify | dimensions + 3 x findings | medium to high |
| /plan-tournament | angles + judges x angles + 3 | high |
