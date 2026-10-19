---
name: concurrent-fanout
description: "Mechanics of parallel fan-out/fan-in: independence checks, choosing Agent batches (up to 20 calls in one message) vs the /fanout workflow, stable item ids and idempotent briefs, a structured per-item result schema, partial-failure classification with a single retry, collation tables and coverage lines. Load when launching the same operation over many independent items."
when_to_use: "When you have a list of independent work items (files, URLs, claims, modules, configs) and one agent type to apply to each, when collating many subagent results, or when deciding whether to use /fanout."
---

# Concurrent fan-out

Fan-out applies one operation to N independent items concurrently and collates the results. It is
pure mechanics: no item's result depends on another's, and the collator makes no content judgement
(that belongs to a synthesizer, verifier or the caller). If items need partitioning, dedup or a merged
answer, that is a swarm (`swarm-execution`).

Brief, schema and retry templates ready to copy: [templates](references/templates.md).
Collation helper: [collate.py](scripts/collate.py) turns item JSON into the table and coverage line.

## 1. Preconditions

- [ ] **Independent**: no item needs another item's output.
- [ ] **Disjoint writes**: no two items write the same file. Read-only work is ideal. Shared build
      directories count as shared state: concurrent `cargo`, `gradle` or `npm` runs in one checkout
      contend for locks; give each item its own target dir or serialize.
- [ ] **One agent type per item** (or an explicit item -> agent type map).
- [ ] **Schema** for the per-item result defined before launch (section 4).
- [ ] **Budget**: `N + ceil(0.2 N)` (retry reserve) at most `H/2`, with
      `H = max_spawns_per_session - spawns_this_session` (`delegation-protocol`).
- [ ] **Depth**: `remaining_depth >= 1`; at 1-2 the item agent must be a leaf (no coordinators).
- [ ] **Token budget**: header `budget="ok"`; at `"soft"` launch only the items the deliverable needs
      (converge, no exploratory items); at `"hard"` launch no fan-out (only `file-summarizer`,
      `quality-control`, `validator`, `source-summarizer` may be spawned) and return the items as Open
      doubts.

Any box unchecked: fix the plan (split shared files out, serialize the conflicting part, shrink N by
putting several items per brief) before launching.

## 2. Choose the mode

| Situation | Mode |
|-----------|------|
| N <= 8 | Agent calls, all in ONE message |
| 9 <= N, one agent type, you are the main thread (no `<stack-context>` header) | `/fanout` (section 8) |
| 9 <= N <= 20, you are a subagent | ONE message with N Agent calls |
| N > 20, you are a subagent | Batches of 20, one message per batch, sequential |
| Mixed agent types | At most 8 calls per message |
| Items are tiny (one lookup each) | Pack 3-10 items per brief; fewer spawns, same wall clock |

Choose the mode for context and coverage, not wall clock: `/fanout` (main thread only) keeps per-item
results out of your context and validates a schema; Agent batches return every result into your
window, so keep per-item returns short (JSON block + path) and offload details to files.

## 3. Item ids and idempotent briefs

- **Run slug** once at start: `<YYYYMMDD-HHMM>-<slug>` (`date +%Y%m%d-%H%M`).
- **Item id**: zero-padded index plus a short slug from the item itself, e.g. `i07-billing-api`.
  Ids derive from the item list, never from timing, so a re-run maps to the same ids.
- **Output path per item**: `.stack/out/<agentType>/<run-slug>/<item-id>.md`.
- **Idempotency clause** in every brief: "The first line of <path> is your Status line. If <path>
  already exists and its first line is `Status: done`, return its result without redoing the work."
  Re-running a half-failed fan-out then only pays for the missing items.
- **Side effects**: an item writes only its own output path plus files explicitly assigned to it.

Brief skeleton (full version in [templates](references/templates.md)):

```
GOAL: <operation> for ONE item. ITEM: <id> = <path | URL | claim | module>
CONTEXT: one of N items in run <run-slug>; others are handled by other agents; do not touch them.
TASK / ACCEPTANCE: <what to produce for this item; checkable criteria>
WRITE: .stack/out/<agentType>/<run-slug>/<id>.md   (idempotency clause)
RETURN: output-contract; Result line 1 Status; then the ITEM RESULT json block (schema below)
BUDGET: about <k> tool calls; stop and return partial rather than exceed it
```

## 4. Per-item result schema

Every item returns the same shape so collation is mechanical:

```json
{ "id": "i07-billing-api",
  "status": "done",
  "summary": "<= 2 sentences, no line breaks",
  "data": { "<flat task-specific fields>": "primitives only: string, number, boolean" },
  "file": ".stack/out/<agentType>/<run-slug>/i07-billing-api.md",
  "confidence": 0.85,
  "error": null }
```

Rules: `status` uses the output-contract values (`done | partial | blocked`); `id` is echoed back
exactly; `data` is flat (nested objects break collation tables; put depth in the file); `error` is a
one-line reason when status is not `done`. With direct Agent calls the agent puts this JSON in a fenced
block inside Result; with `/fanout` pass it as `schema` and the workflow validates it.

## 5. Launch

- One message, N tool calls. Each call: `subagent_type` (exact agent name), `description`
  (3-6 words including the item id), `prompt` (the brief), `run_in_background: false`. Never `model`/`effort` (the pre-agent hook strips
  them; pick a cheaper or stronger agent instead).
- Set `run_in_background: false` on every call of a fan-out you will collate in this turn (under the
  SDK subagents otherwise default to the background); each child's final message must carry its whole
  deliverable (JSON block + file path).
- Results arrive in any order: key by `id`, never by position.
- Between batches: update the ledger (id -> status, attempts), re-check budget headroom, then send
  the next batch.

## 6. Partial failure and the single retry

| Symptom | Class | Retry | How |
|---------|-------|-------|-----|
| No reply, tool error, null result | crash | once | same brief plus "Previous attempt returned nothing; keep scope minimal." |
| JSON block missing or fields invalid | contract | once | quote the schema and the missing fields; or a `file-summarizer` (LOW tier) normalize call that extracts it from the item's file |
| Hit maxTurns or context, little done | exhausted | once | narrower scope, or the next tier up by agent (e.g. `source-summarizer` LOW -> `quick-researcher` MEDIUM -> `deep-researcher` ADVANCED; `code-quality-analyst` MEDIUM -> `reviewer` ADVANCED) |
| Off-brief content | off-brief | once | sharper brief: restate the item, the output, and what was wrong |
| `Status: partial` | partial | no, unless the missing part is required by acceptance | then a narrowed brief for the gap only |
| `Status: blocked` on a scope doubt | blocked | only if your own brief answers the doubt | add the answer to the brief; otherwise pass the doubt up |
| Hook denial (depth limit, spawn policy, spawn budget, token budget) | denied | never | mark `failed (denied)` |

At most two attempts per item. Never resend an identical prompt. Send all retries of a batch together
in one message. Items still failing after the retry are reported, not hidden.

## 7. Collation

```
| # | id | status | att | summary | <metric 1> | <metric 2> | file |
|---|----|--------|-----|---------|------------|------------|------|
| 1 | i01-auth | done | 1 | 14 endpoints, 2 unauthenticated | 14 | 2 | .stack/out/.../i01-auth.md |
| 7 | i07-billing-api | partial | 2 | 9 of 11 handlers parsed; macros unexpanded | 9 | 0 | ... |

Coverage: 12/14 done, 1 partial (i07), 1 failed (i11: contract x2). Spawns: 16 (14 + 2 retries).
Totals: endpoints 163, unauthenticated 5 (done items only).
```

- Sort by id. State totals only over the statuses you counted ("done items only").
- Allowed aggregation: counts, sums, min/max/median of numeric fields, group-by of a categorical
  field. Not allowed: ranking by quality, picking winners, rewriting summaries. Those are judgement.
- More than ~60 lines or ~3k characters (in practice more than ~20 rows with paths), or the caller
  will post-process: write the table to
  `.stack/out/<you>/<run-slug>-results.md` and the raw item JSON array to `<run-slug>-results.json`;
  inline only the coverage line, totals and the non-done rows.
- Carry every item's Open doubts upward, deduplicated, tagged with the item id.

## 8. /fanout

```json
{ "name": "fanout",
  "args": {
    "items": [ {"id": "i01-auth", "path": "services/auth"}, {"id": "i02-billing", "path": "services/billing"} ],
    "agentType": "general-purpose",
    "promptTemplate": "Item {{n}} of {{total}} ({{item.id}}): list every HTTP endpoint (method, path, handler file:line, auth required yes/no) defined under {{item.path}}. Write details to .stack/out/general-purpose/20261019-1600-endpoints/{{item.id}}.md. Echo id={{item.id}}. Return the schema.",
    "schema": { "type": "object",
      "properties": { "id": {"type": "string"},
                      "status": {"type": "string", "enum": ["done", "partial", "blocked"]},
                      "summary": {"type": "string"},
                      "endpoints": {"type": "integer"}, "unauthenticated": {"type": "integer"},
                      "file": {"type": "string"} },
      "required": ["id", "status", "summary"] },
    "model": "sonnet", "effort": "low", "retry": 1 } }
```

- Placeholders: `{{item}}` (strings as-is, objects as JSON), `{{item.field}}` (a field path),
  `{{index}}` (0-based), `{{n}}` (1-based), `{{total}}`. A field path that is empty for every item
  stops the run before any spend; check `template_warnings` in the return.
- Retries: items whose agent returned null, empty text or threw are re-run up to `retry` times
  (default 1, max 3). A schema-valid `status: partial` is NOT retried by the workflow; apply section 6
  yourself.
- `maxItems` (default 400) caps the run; capped items come back in `skipped` and must go in a second call.
- Returns `{started, total, attempted, succeeded, results, failed, skipped, template_warnings}` with
  `results[] = {index, ref, attempts, result}` (your schema object in `result`) and
  `failed[] = {index, ref, attempts, reason, item}`. `started: false` comes with `reason` and `next`.
- Map by the echoed `id`, or by `index` back into your item list. `collate.py` accepts this object as is.
- Only the main thread (no `<stack-context>` header) can call `/fanout`; Claude Code removes Workflow
  from every subagent. A subagent (e.g. `concurrent-dispatcher`) uses Agent batches (section 2) or
  returns `Workflow name=fanout args={...}` as an Open doubt. If a main-thread Workflow call errors,
  fall back to Agent batches and say so in Evidence.
- `model`/`effort` in the args are allowed only with `agentType: general-purpose` (aliases
  opus|sonnet|haiku); never pass them for this stack's own agents.

## 9. Worked example

Request: "For each of our 14 services, list the HTTP endpoints and flag unauthenticated ones."

1. Independence: read-only, one directory per item. Agent: `general-purpose` with `model: sonnet`,
   `effort: low` in the `/fanout` args (mechanical extraction; allowed only for general-purpose).
   Budget: 14 + 3 = 17; `H = 400 - 61 = 339`, so 17 <= 169.
2. N = 14 > 8 and you are the main thread (no `<stack-context>` header) -> `/fanout` with the call
   above (14 object items with `id` and `path`). As `concurrent-dispatcher` at remaining_depth 4 you
   would send 14 Agent calls in one message instead, each with `run_in_background: false` and no
   model/effort (pick `code-quality-analyst`, MEDIUM tier, rather than general-purpose).
3. Returns: 12 done; `services/billing` partial (route macros not expanded, 9 of 11 handlers);
   `services/legacy-gw` partial with `error: "maxTurns reached, 4 of 31 files read"`.
4. `legacy-gw` is class exhausted: its single retry is a direct Agent call to an ADVANCED-tier
   agent (`security-auditor`, which owns the auth question) with `run_in_background: false` and a
   narrower brief ("only `routes*.go` and `handlers/`") -> done. `billing` is not retried: the gap is
   macro expansion, which the same tools would not fix.
5. Collation table, coverage `13/14 done, 1 partial (billing)`, spawns 15, totals over done items,
   Open doubt:
   `[runtime|med] billing route macros not expanded - endpoint list may be incomplete - resolve: dump the router table at startup - route: tester`.

## 10. Checklist before returning

- [ ] Every item has a terminal status and an attempt count; no item silently missing.
- [ ] Coverage line with counts and the ids of non-done items.
- [ ] Totals state which statuses they include.
- [ ] No judgement in the collation; downstream judgement is named as a next step if needed.
- [ ] Large tables offloaded; Files lists the results files; spawns used reported.
