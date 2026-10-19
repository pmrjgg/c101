# Gate templates

## Machine-readable gate record (JSON)

Use this shape when a saved workflow or an orchestrator consumes the gate result. Keep it next to the
markdown matrix in `.stack/out/<agent>/`.

```json
{
  "gate": "final",
  "subject": "bin/stack mcp list --json",
  "base": "a1b2c3d",
  "head": "e4f5a6b",
  "frozen_at": "2026-10-19T15:20:00Z",
  "requirements": [
    {"id": "R1", "text": "Add --json to bin/stack mcp list", "source": "brief line 1"},
    {"id": "R4", "text": "No regressions", "source": "implicit"}
  ],
  "criteria": [
    {
      "id": "AC1.1",
      "req": "R1",
      "text": "bin/stack mcp list --json exits 0 and prints valid JSON",
      "priority": "must",
      "method": "command",
      "evidence": {
        "level": "E5",
        "command": "bin/stack mcp list --json | python3 -m json.tool > /dev/null; echo exit=$?",
        "exit_code": 0,
        "excerpt": "exit=0",
        "ref": ".stack/out/validator/20261019-1520-gate-mcp-json.md#L12"
      },
      "result": "PASS",
      "added_after_review": false
    }
  ],
  "regression": {
    "tests": {"baseline": {"passed": 214, "failed": 0, "skipped": 3, "errored": 0},
              "head": {"passed": 219, "failed": 0, "skipped": 3, "errored": 0}},
    "lint_errors": {"baseline": 0, "head": 0},
    "build": {"baseline": "pass", "head": "pass"}
  },
  "traceability": {
    "unmapped_changes": ["config/learning.json"],
    "requirements_without_criteria": [],
    "criteria_without_evidence": []
  },
  "waivers": [],
  "decision": "FIX_FIRST",
  "failing": ["AC2.1", "AC3.1"],
  "loop": 1
}
```

Allowed values: `priority` in {must, should}; `result` in {PASS, FAIL, BLOCKED, UNVERIFIED, WAIVED, N/A};
`decision` in {SHIP, SHIP_WITH_NOTES, FIX_FIRST, ESCALATE}; `level` in {E0..E5}.

## Markdown gate report

```markdown
## Result
Status: partial
Decision: FIX-FIRST (2 of 6 must criteria fail; 1 scope-creep change). Loop 1 of 2.

| ID | Criterion | Pri | Lvl | Result |
|---|---|---|---|---|
| AC1.1 | `--json` exits 0 with valid JSON | must | E5 | PASS |
| AC2.1 | JSON matches text output (servers, enabled state) | must | E4 | FAIL |
| ... |

Regression guard: tests 214/0/3/0 -> 219/0/3/0; doctor errors 0 -> 0; build pass.
Traceability: config/learning.json changed without a requirement (S1).

## Evidence
- AC1.1: `bin/stack mcp list --json | python3 -m json.tool > /dev/null; echo exit=$?` -> exit=0 at e4f5a6b
- AC2.1: `python3 -m pytest tests/test_mcp_cli.py::test_json_matches_text -q` -> exit 1,
  "KeyError: 'enabled'" (full log: <matrix file>#L40-L52)
- Baseline measured in a temporary worktree at a1b2c3d with the same commands.

## Files
- .stack/out/validator/20261019-1520-gate-mcp-json.md - full matrix and logs - new
- .stack/out/validator/20261019-1520-gate-mcp-json.json - machine-readable gate record - new

## Open doubts
- none

## Confidence
0.90 (high) - every criterion evaluated with E4/E5 except docs (E3); drops if CI uses a different Python.
```

## Producer fix brief (FIX-FIRST)

```markdown
Goal: make the failing acceptance criteria below pass without breaking passing ones.
Repository: <path>, branch <name>, head <sha>.

Failing criteria:
| ID | Criterion | Expected | Actual | Reproduce |
|---|---|---|---|---|
| AC2.1 | JSON matches text output | each object has `name`, `type`, `enabled` | `enabled` missing | `python3 -m pytest tests/test_mcp_cli.py::test_json_matches_text -q` |
| AC3.1 | docs/MCP.md documents `--json` with an example | section with example command | no mention | `rg -n -- "--json" docs/MCP.md` |

Scope correction: revert the change to config/learning.json (not part of the request).

Constraints:
- Keep these passing: AC1.1, AC1.2, AC4.1, AC5.1 (commands in the matrix file).
- Do not edit, skip or weaken tests; do not change test expectations.
- Python stdlib only.

Acceptance: AC2.1 and AC3.1 PASS with the commands above; regression guard unchanged
(tests 219/0/3/0 or better, doctor errors 0).
Return: output contract; list changed files.
```

## Criteria worksheet (fill before inspecting the deliverable)

```markdown
| Req | Source (quote) | Criterion (atomic, observable) | Pri | Method | Min evidence |
|---|---|---|---|---|---|
| R1 | "add a --json flag" | `cmd --json` exits 0 and stdout parses as JSON | must | command | E5 |
| R1 | (implicit) | `cmd --help` lists `--json` | should | command | E5 |
| R4 | (implicit) | failed/errored test counts do not rise | must | suite on base and head | E5 |
```

## Waiver record

```markdown
Waiver: AC6.2 (p95 < 200 ms at 50 rps) waived for this release.
By: <requester> in <message/issue reference>, 2026-10-19.
Reason: load test environment unavailable; production canary will gate instead.
Follow-up: issue #512, owner <team>, due 2026-11-01.
```
