---
name: validation-gates
description: "Acceptance-criteria verification before work is declared done: turning requirements (explicit and implicit) into atomic checkable criteria, an evidence strength ladder (reproduced command output, targeted tests, artifact inspection, citations, producer claims), a pass/fail matrix with requirement-to-evidence traceability and scope-creep detection, a regression guard against baseline, waiver rules, the fix-first loop, gates between DAG waves, and the ship / fix-first / escalate decision. Load when validating a deliverable against its brief, gating a plan wave, or deciding whether a result can be returned or shipped."
when_to_use: "A producer says the work is finished; an orchestrator must decide whether a wave passed; a caller asks whether something meets the requirements; before returning Status done on any non-trivial task."
---

# Validation gates

Done means every criterion has evidence that you produced or re-checked yourself, against a frozen list
of criteria derived from the requirements. A claim without evidence is UNVERIFIED, never PASS. The
producer's summary tells you where to look, not what is true.

## 1. Requirements to checkable criteria

1. **Collect sources**: the brief (quote it), the user's original request if available, plan node
   acceptance criteria, linked issues, repository conventions (`docs/CONVENTIONS.md` here), the
   output contract.
2. **Extract requirements** R1..Rn as quoted or closely paraphrased statements, each with its source.
3. **Add implicit requirements** unless the brief excludes them:
   - builds, type checks and existing tests still pass; no new lint errors in changed files
   - repository conventions followed (`bin/stack doctor` clean for stack content)
   - no secrets, no debug leftovers, no unrelated changes
   - user-visible behaviour changes are documented
4. **Decompose** each requirement into atomic criteria AC<r>.<n>: one observable outcome, binary,
   reproducible by someone else, with a named method.
5. **Prioritize**: `must` (ship-blocking) or `should` (follow-up acceptable).
6. **Freeze** the list before inspecting the deliverable. Criteria added later are labelled
   "added after review" with the reason, so you cannot fit criteria to the result.

Vague to checkable:

| Vague requirement | Checkable criterion |
|---|---|
| "Make search fast" | p95 latency of `GET /search?q=` < 200 ms at 50 rps on the fixture dataset, 60 s k6 run, median of 3 runs |
| "Handle errors gracefully" | On upstream 503 the endpoint returns 502 with body `{"error":"upstream_unavailable"}` within 2 s; no stack trace in the body |
| "Well tested" | Each new public function has a test; diff branch coverage >= 80%; the regression test fails on the base commit |
| "Clean code" | Linter clean on changed files; no changed function above cognitive complexity 15 |
| "Document the flag" | `--help` lists the flag with its default; the docs page has a section with an example invocation |
| "Research the best option" | >= 3 options compared on the stated criteria; every load-bearing claim cites a primary source with URL and access date; recommendation names its trade-off |
| "Works on mobile" | At 375x812 the flow completes, no horizontal scroll, tap targets >= 44 px; screenshots attached |

Phrasing aids: Given/When/Then for behaviour; EARS for requirements ("When <trigger>, the <system>
shall <response>"; "If <unwanted condition>, then the <system> shall <response>"; "While <state>, ...").

## 2. Evidence strength ladder

| Level | Evidence | Example |
|---|---|---|
| E5 | Reproduced by you in this session: command, exit code, decisive output lines, revision | `pytest tests/test_cli.py -q` exit 0, "12 passed", at e4f5a6b |
| E4 | Targeted automated test, run by you now, and read by you to confirm it asserts the criterion | `test_report_json_matches_text` passes and compares every field |
| E3 | Direct inspection of an artifact: diff, file at `path:line`, rendered page, screenshot, schema validation | `docs/MCP.md:41` documents `--json` |
| E2 | Independent external source: primary citation with URL, access date, short quote | vendor doc confirming an API default |
| E1 | Producer's claim, summary or log not re-run | "all tests pass" in the producer's Result |
| E0 | Nothing | |

Minimum evidence for PASS:

| Criterion type | Minimum | Preferred |
|---|---|---|
| Functional behaviour | E4 | E5 end-to-end + E4 |
| Bug fixed | E5 repro fails on base and passes on head | + E4 regression test in the suite |
| Performance target | E5 benchmark with statistics (`performance-optimization` method) | |
| No regression | E5 full relevant suite compared with baseline counts | |
| Docs, config, structure | E3 | E5 when executable (`--help`, config load) |
| UI and layout | E3 screenshot at the stated viewport | + E5 E2E step via `tester` |
| Factual claim | E2; two independent sources when load-bearing | `fact-checker` batch |
| Security property | E5 negative test (the forbidden action fails) | + review by `security-auditor` |
| "Nothing else changed" | E3 `git diff --stat <base>...HEAD` with traceability (section 5) | |

E1 never yields PASS. A test you did not read can be a test that asserts nothing.

## 3. Gate procedure

1. Write the frozen criteria into the matrix file `.stack/out/<agent>/<YYYYMMDD-HHMM>-gate-<slug>.md`.
2. Establish the baseline: base revision, test counts, lint/type error counts, doctor output. If not
   known, measure on the base in a separate worktree:
   ```bash
   base=$(git merge-base origin/main HEAD); wt=$(mktemp -d)
   git worktree add "$wt" "$base" && (cd "$wt" && <test command>) ; git worktree remove "$wt"
   ```
3. Evaluate each criterion with its method. Record the evidence right away:
   ```
   AC1.1 PASS (E5) at e4f5a6b
     $ bin/stack mcp list --json | python3 -m json.tool > /dev/null; echo "exit=$?"   # hypothetical flag from the section 10 example
     exit=0
   ```
4. Run the regression guard (section 6).
5. Run traceability (section 5).
6. Decide (section 7) and report with the output contract.

Result states:

| State | Meaning |
|---|---|
| PASS | Evidence at or above the minimum shows the criterion holds |
| FAIL | Evidence shows it does not hold (include expected vs actual) |
| BLOCKED | Cannot evaluate: missing environment, permission, data, or tool; name exactly what is needed |
| UNVERIFIED | Only E1/E0 available, or evidence below the minimum |
| WAIVED | The requester explicitly waived it (who, when, why recorded) |
| N/A | Does not apply to this deliverable, with the reason |

Avoid PARTIAL: split the criterion into the parts that pass and the parts that fail.

## 4. Pass/fail matrix

```markdown
| ID | Req | Criterion | Pri | Method | Evidence | Lvl | Result |
|---|---|---|---|---|---|---|---|
| AC1.1 | R1 | `mcp list --json` exits 0 and prints valid JSON | must | run + json.tool | exit=0 (log L12) | E5 | PASS |
| AC2.1 | R2 | JSON contains every server shown in text output, same enabled state | must | test | test_mcp_list_json_matches_text: FAILED, `enabled` missing | E4 | FAIL |
| AC3.1 | R3 | docs/MCP.md documents `--json` with an example | must | inspect | not found (rg -n "\-\-json" docs/MCP.md: no match) | E3 | FAIL |
| AC4.1 | R4 | doctor error count not increased | must | run on base and head | 0 -> 0 | E5 | PASS |
```

Machine-readable form (for workflows and orchestrators), report template, and producer fix-brief
template: [Gate templates](references/templates.md). How to produce evidence for each deliverable type
(code, bug fix, docs, research, UI, data, infrastructure, stack agents and skills, images):
[Evidence recipes](references/evidence-recipes.md).

## 5. Traceability

- **Forward**: every requirement has at least one criterion; every criterion has evidence.
- **Backward**: every changed file maps to a requirement.
  ```bash
  git diff --name-only "$(git merge-base origin/main HEAD)"...HEAD
  ```
  Annotate each path with requirement IDs. Unmapped changes are scope creep: report them (S2 by
  default; S1 if risky, such as config, CI, migrations, dependency changes, or deleted tests).
- **Orphans table** in the report: requirements without criteria, criteria without evidence, changes
  without requirements.

## 6. Regression guard

| Signal | Baseline | Head | Rule |
|---|---|---|---|
| Build / type check | pass | pass | must stay passing |
| Tests passed / failed / skipped / errored | 214 / 0 / 3 / 0 | 219 / 0 / 3 / 0 | failed and errored must not rise; skipped must not rise without a stated reason; total must not drop without a stated reason |
| Lint or doctor errors | 0 | 0 | must not rise |
| Diff coverage (changed lines, branch) | - | 86% | meets the brief's threshold if one was set |
| Size / performance budgets | as set | | within budget when the brief sets one |

A rising skipped count or a dropped test is a finding until justified: it is the most common way
regressions get hidden.

## 7. Decision

| Condition | Decision | Return |
|---|---|---|
| All `must` PASS or WAIVED, regression guard clean, no open S0/S1 findings | SHIP | Status: done |
| `must` PASS, some `should` FAIL | SHIP WITH NOTES | Status: done; failures listed as follow-ups |
| Any `must` FAIL with a clear fix and loop budget left | FIX-FIRST | Brief to producer (section 8). As `validator`: Status: partial with that brief in Result or the gate file for the caller to dispatch (a `validator` cannot spawn producers); the caller re-runs the gate after the fix |
| Any `must` BLOCKED or UNVERIFIED for environment reasons | ESCALATE | Status: partial or blocked; Open doubt naming the exact evidence needed |
| Requirement found ambiguous or contradictory | ESCALATE to the caller (scope doubt) | Status: blocked if the ambiguity is load-bearing |
| Fix loop exhausted (2 rounds) | ESCALATE with the history of attempts | Status: partial |

Waivers: only the requester who owns the requirement (the user or the calling agent that set the
criterion) can waive. A validator never waives, and never downgrades `must` to `should` on its own.

## 8. Fix-first loop

Brief to the producer (self-contained; the producer does not see your context):
- the failing rows of the matrix with expected vs actual and the evidence,
- the exact commands to reproduce each failure,
- constraints: keep passing criteria passing, do not weaken or skip tests, no unrelated changes,
- acceptance: the listed criteria PASS under the same commands.

Re-validate after the fix: re-run the failed criteria **and** the full regression guard (fixes often
break something else). Maximum two loops; then escalate with the full history. A `validator` returns
the brief and its caller owns the loop (dispatches the producer, then re-runs the gate).

## 9. Gates in a plan DAG

| Gate | When | Checks | Who |
|---|---|---|---|
| Entry | Before a wave starts | Prerequisite nodes PASS; each node in the wave has acceptance criteria and a verification method | `orchestrator` itself |
| Wave | After each wave | Each node's criteria; affected tests only | `validator` per node (MEDIUM tier from config/models.json; never pass model/effort), as parallel Agent calls with `run_in_background: false` for independent nodes |
| Integration | After parallel outputs are merged | Conflicts, combined build and tests, cross-node contracts | `validator` or `tester` |
| Final | Before returning to the user | Full matrix, traceability, full regression guard; content quality for non-code deliverables | `validator`, plus `quality-control` for documents and research |

Spend in proportion to blast radius: a docs-only node needs E3 checks; a migration node needs E5 on a
copy of realistic data.

## 10. Worked example

Brief: "Add `--json` to `bin/stack mcp list` that prints the same data as the text output; document
it." Repository convention: Python tooling is stdlib-only.

Requirements: R1 flag exists; R2 same data as text; R3 documented; R4 no regressions (implicit);
R5 stdlib only (convention).

| ID | Criterion | Method | Result |
|---|---|---|---|
| AC1.1 | `bin/stack mcp list --json` exits 0 with valid JSON | E5: run, pipe through `python3 -m json.tool` | PASS |
| AC1.2 | `bin/stack mcp --help` mentions `--json` | E5 | PASS |
| AC2.1 | Every server in text output appears in JSON with the same enabled state | E4: new test comparing both outputs on a fixture `.mcp.json` | FAIL: `enabled` field missing |
| AC3.1 | `docs/MCP.md` documents the flag with an example | E3: `rg -n -- "--json" docs/MCP.md` | FAIL: no match |
| AC4.1 | Doctor errors 0 -> 0; test counts unchanged or higher | E5 on base and head | PASS |
| AC5.1 | No non-stdlib imports added | E3: `git diff <base> -- stack/ \| rg '^\+\s*(import\|from) '` reviewed | PASS |
| Trace | `config/learning.json` modified, maps to no requirement | E3 diff | Scope creep (S1: tuning bounds changed) |

Decision: FIX-FIRST. Brief to the producer: add `enabled` to the JSON objects, document the flag,
revert the unrelated `config/learning.json` change; acceptance = AC2.1, AC3.1 PASS and the regression
guard unchanged. Second validation: all `must` PASS; SHIP, Status: done, confidence 0.9.

## 11. Anti-patterns

- Accepting "tests pass" from the producer without running them (E1 treated as E5).
- Checking the happy path only; criteria for error paths and edge cases are part of the requirement.
- Counting skipped or deleted tests as success.
- Writing criteria after seeing the result.
- Letting the producer validate its own work for `must` criteria when an independent check is cheap.
- Gate theatre: dozens of trivial criteria while the one risky behaviour has none. Weight effort by risk.

## Delegation

| Need | Agent |
|---|---|
| Run suites, E2E journeys, screenshots at viewports | `tester` |
| Code-level defects behind a FAIL | `reviewer` or `debugger` |
| Factual claims and citations | `fact-checker` (batch all claims in one brief) |
| Content quality, completeness of documents and research | `quality-control` |
| Contested PASS on a high-stakes criterion | `adversarial-verifier` |
| Security criteria | `security-auditor` |
| Performance criteria | `code-optimizer` |

If you are `validator`, the pre-agent hook lets you spawn only `tester`, `quick-researcher`,
`deep-researcher`, `fact-checker`, `quality-control`, `code-quality-analyst`, `adversarial-verifier`
and `file-summarizer` (config/policy.json spawn_rules). For `reviewer`, `debugger`, `security-auditor`
or `code-optimizer` needs, return an Open doubt that names the agent and the brief, for your caller
to dispatch.
