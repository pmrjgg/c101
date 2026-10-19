# Plan schema (dag.json)

Field reference for planning-dag plans. "Check" names what `scripts/dag.py` enforces: E = error
(exit 1), W = warning, - = not checked mechanically (plan-critic and the checklist cover it).

## Plan object

| Field | Type | Required | Meaning | Check |
|---|---|---|---|---|
| `plan_id` | string, kebab-case | yes | stable id across versions | - |
| `plan_version` | integer, starts at 1 | yes | incremented on every re-plan; previous file kept | - |
| `requires_depth` | integer 0-8 | yes | minimum `remaining_depth` the executor needs (coordinator owners need 3) | - |
| `goal` | string | yes | one-sentence outcome | - |
| `done_when` | string[] (2-6) | yes | checkable completion criteria for the whole plan | - |
| `non_goals` | string[] | no | explicitly excluded work | - |
| `assumptions` | string[] | yes (may be empty) | facts taken as given; each risky one has a re-plan trigger | - |
| `nodes` | node[] | yes | the DAG | E if missing |
| `replan_triggers` | string[] | yes | conditions that force a re-plan | - |
| `replan_log` | object[] | yes (may be empty) | `{version, trigger, change, reason}` per re-plan | - |

A bare JSON array of nodes is accepted by dag.py for quick checks.

## Node object

| Field | Type | Required | Meaning | Check |
|---|---|---|---|---|
| `id` | string, short (R1, I3, QC) | yes | unique within the plan | E: missing or duplicate |
| `title` | string | yes | the deliverable in a few words | - |
| `phase` | string | no | `research`, `design`, `implement`, `verify`, ... for phase gates | - |
| `owner` | agent name, `caller`, or a built-in | yes | who executes the node | E: missing; W: not in `.claude/agents` |
| `model`, `effort` | - | no | not supported: tiers are authoritative (the pre-agent hook strips per-call model/effort); dag.py ignores them; choose the owner's tier instead | - |
| `deps` | id[] | yes (may be empty) | real data, knowledge or resource dependencies | E: unknown id, self-dependency, cycle |
| `inputs` | string[] | yes (may be empty) | paths or upstream node ids the brief cites | - |
| `writes` | string[] | yes | write-set: files or directories the node may modify, globs allowed | E: certain overlap with a concurrent node; W: possible glob overlap or empty |
| `acceptance` | string[] (1-5) | yes | checkable criteria | E: empty |
| `verify` | object or string | yes | `{method, by, how}`; a string is read as `how` | E: missing; W: `by` equals owner (except `command` and human owners) |
| `risk` | object | yes | `{likelihood 1-3, impact 1-3, mitigation?, rollback?}` | W: product >= 6 without mitigation |
| `irreversible` | boolean | no | data migration, release, deletion, publishing | W: no rollback when high risk; no `caller` dep |
| `condition` | string | no | evaluated by the executor when ready; false means `skipped` | - |
| `est_turns` | number > 0 | yes | owner turns; at most 0.6 x owner maxTurns | W: missing (1 assumed) |
| `status` | enum | yes | see statuses | E: unknown value |
| `attempts` | integer | no | dispatch count, for the retry rule | - |
| `result` | object or null | no | `{verdict, evidence, outputs, note}` after the node returns | - |

`verify.method` values: `command`, `test`, `review`, `citation-check`, `adversarial`, `user`.

Aliases accepted by dag.py (other agents' shapes): `write_set` and `outputs` for `writes`;
`estimate` for `est_turns`; `severity` for `risk.impact`; `verify.command` for `verify.how`;
`risk` as a plain string is tolerated but carries no mitigation check.

## Statuses

| Status | Meaning | Counts as finished for successors |
|---|---|---|
| `pending` | not started | no |
| `running` | dispatched, no result yet | no |
| `done` | returned and its gate passed (aliases: PASS, passed, ok) | yes |
| `failed` | gate failed or agent failed (aliases: FAIL, FAILED, error) | no |
| `blocked` | waiting on an Open doubt | no |
| `skipped` | deliberately not run (false condition, made redundant); reason in the ledger | yes |
| `cancelled` | removed by a re-plan; delete it from `nodes` in the new version | n/a |

## Result object

```json
{"verdict": "PASS", "evidence": "nodes/I3/validator.md",
 "outputs": ["crates/auth/src/token.rs", "nodes/I3/report.md"],
 "confidence": 0.9, "note": "retry after clippy fix"}
```

Downstream briefs cite `result.outputs`; the ledger row repeats verdict and evidence path.

## Write-set overlap rules (dag.py)

| Pair | Example | Verdict |
|---|---|---|
| identical concrete paths | `src/a.rs` and `src/a.rs` | certain conflict |
| directory and a path inside it | `crates/auth/src/` and `crates/auth/src/token.rs` | certain conflict |
| glob covering a concrete path | `internal/session/**` and `internal/session/store/x.go` | possible overlap |
| two globs with nested static prefixes | `src/**` and `src/api/*.rs` | possible overlap |
| sibling files | `limiter.go` and `limiter_test.go` in one directory | no conflict |

Conflicts only matter between nodes that can run concurrently (neither is an ancestor of the other).
Resolve with an edge, by splitting file ownership, or by having one node return a patch for the other.

## Minimal valid node

```json
{"id": "T1", "title": "Regression test for the dropped-last-page bug", "owner": "tester", "deps": [],
 "inputs": ["src/pager.py"], "writes": ["tests/test_pager.py"],
 "acceptance": ["test_partial_last_page fails on main and passes after the fix"],
 "verify": {"method": "test", "by": "validator", "how": "pytest -q tests/test_pager.py"},
 "risk": {"likelihood": 1, "impact": 1}, "est_turns": 4, "status": "pending"}
```
