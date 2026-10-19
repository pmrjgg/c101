---
name: testing-strategy
description: "Test design and suite strategy: picking the level (unit, integration, contract, E2E) by risk, example-based design techniques, property-based testing (Hypothesis, proptest, QuickCheck, fast-check, jqwik, rapid), fuzzing, metamorphic and differential testing, mutation testing, regression tests for bugs, flaky-test triage with run-count math, and coverage interpretation, under the hard rule never to weaken an assertion to get green. Load when writing or reviewing tests, planning tests for a change, or dealing with failing or flaky suites."
when_to_use: "Writing tests for new code or a bug fix; deciding what level a test belongs at; a test fails or flakes and you are tempted to change the assertion; judging whether coverage numbers mean the change is tested."
---

# Testing strategy

A test is evidence that a specific behaviour holds. Design tests by asking what failure you want to
catch, at the lowest level that can observe it, with an oracle you trust.

## 1. The hard rule: never weaken an assertion to get green

A red test is information. Changing the test instead of the code requires proof that the test is wrong.

| Weakening move | Allowed only if |
|---|---|
| Loosen a tolerance (`1e-9` to `1e-3`), widen a range | You show the old tolerance is below the algorithm's error bound (derivation or reference) |
| Broaden an expected exception (`ValueError` to `Exception`) | The spec defines the broader contract |
| Delete or comment out an assertion | The asserted behaviour was removed by the requirement you are implementing |
| `skip`, `xfail`, `@Disabled`, `t.Skip`, `#[ignore]` | Linked issue with owner and date, and the caller is told in Open doubts |
| Regenerate golden files or snapshots | You reviewed the diff line by line and every change is intended |
| Increase timeouts, add retries | You identified the cause (section 9) and it is genuinely slow, not racy |
| Mock the unit under test, or catch-and-ignore inside the test | Never |

If you believe a test is wrong: quote the requirement it contradicts, change it in a separate commit or
clearly separated edit, and state it under Open doubts so the caller can veto.

## 2. Choose the level

Rule: test at the lowest level that can observe the failure, and add one higher-level test per critical
path to catch wiring mistakes.

| What you are verifying | Level | Typical tooling |
|---|---|---|
| Pure logic, algorithms, parsing, validation | Unit | pytest, `cargo test`, `go test`, JUnit 5, Vitest/Jest |
| Code plus real DB, queue, filesystem, HTTP client | Integration | Testcontainers, temp dirs, in-process servers |
| Agreement between two services owned by different teams | Contract | Pact, schema compatibility checks (buf breaking, OpenAPI diff) |
| A user journey through the deployed stack | E2E | Playwright (`mcp__playwright__*` via `tester`), Cypress |
| No oracle exists (search ranking, compilers, numerics, ML) | Metamorphic / differential | Section 5 |
| Untrusted bytes in (parsers, decoders, protocol handlers) | Fuzz | Section 6 |
| Suite strength | Mutation | Section 7 |

Suite shape by project type:

| Project | Shape | Rationale |
|---|---|---|
| Library / algorithmic code | Pyramid: many unit + property tests | Logic dominates, I/O is thin |
| Backend service | Integration-heavy ("trophy"): real DB in containers, few mocks | Most bugs live in queries, serialization, config |
| UI application | Component tests + 5-20 E2E journeys | E2E are slow and flaky; reserve for money/auth/core flows |
| Data pipeline | Golden datasets + invariant checks between stages (row counts, uniqueness, null rates) | Correctness is about data properties |
| Compiler / interpreter / codec | Differential + fuzz + snapshot of outputs | Specs are huge; reference implementations exist |

Budgets that keep a suite usable: unit test < 50 ms, integration < 2 s, PR feedback < 10 min. A test
slower than its budget moves up a tier or gets fixed.

## 3. Example-based test design

1. **Equivalence partitions.** Group inputs that should behave the same; one test per partition.
2. **Boundary values.** For a valid range [min, max]: min-1, min, min+1, a nominal value, max-1, max, max+1.
   Add empty, single, and huge for collections; zero, negative, overflow for numbers.
3. **Decision tables** for combinations of conditions: one column per rule, one test per column.
4. **State transitions.** Cover every valid transition once and every invalid event in every state once.
5. **Pairwise** for many independent parameters: cover all value pairs, not all combinations
   (e.g. 10 parameters x 3 values: 59049 combinations vs about 15-20 pairwise cases; tools: PICT, allpairspy).
6. **Error paths.** One test per distinct error branch introduced by the change.

Structure: Arrange / Act / Assert, one behaviour per test, name states condition and expectation:
`test_parse_duration_rejects_negative_hours`, `TestRateLimiter_AllowsBurstThenBlocks`.

Test doubles, in order of preference:

| Double | Use when | Risk |
|---|---|---|
| Real dependency (container, temp dir, in-memory engine that is the real code) | Feasible within budget | Slower |
| Fake (working lightweight implementation: in-memory repo, fake clock) | Dependency is slow or nondeterministic | Fake drifts from real; contract-test the fake |
| Stub (canned answers) | You only need an input to flow | None significant |
| Mock (verifies interactions) | The interaction itself is the behaviour (an email was sent once) | Over-specification; brittle |

Do not mock what you do not own: wrap the third-party client in a thin adapter you own, mock the adapter
in unit tests, and integration-test the adapter against the real thing.

Determinism: inject the clock (`freezegun`/`time-machine`, `vi.useFakeTimers()`, `java.time.Clock`,
a `Clock` trait), seed RNGs and log the seed, generate IDs through an injectable source, no network in
unit tests, no sleeps for synchronization (wait on a condition with a deadline).

## 4. Property-based testing

Write a property when you can state something true for *all* inputs. The framework generates inputs and
shrinks failures to a minimal counterexample.

| Property pattern | Form | Example |
|---|---|---|
| Round trip | `decode(encode(x)) == x` | serializers, parsers + printers, compression |
| Invariant | output satisfies a predicate | `sorted(xs)` is ordered and a permutation of `xs` |
| Idempotence | `f(f(x)) == f(x)` | normalization, dedup, `PUT` handlers |
| Oracle / model | `fast(x) == naive(x)` | optimized vs reference, new vs old implementation |
| Algebraic | commutativity, associativity, identity | merges, CRDTs, monoids, set operations |
| Metamorphic | relation between outputs of related inputs | section 5 |
| No crash | `f(x)` raises only documented errors | any input-handling function |
| Stateful model | random command sequences agree with a simple model | caches, queues, key-value stores |

Hypothesis (Python):
```python
from hypothesis import given, settings, strategies as st

@settings(max_examples=500)
@given(st.lists(st.integers()))
def test_sort_is_ordered_permutation(xs):
    out = my_sort(xs)
    assert all(a <= b for a, b in zip(out, out[1:]))
    assert sorted(xs) == out
```
Run with `pytest --hypothesis-show-statistics`; failing examples are stored in `.hypothesis/` and replayed
first on the next run. Pin a CI profile with `settings.register_profile("ci", max_examples=1000)`.

Framework snippets for proptest, QuickCheck/Hedgehog, fast-check, jqwik, rapid, stateful testing,
generator design and shrinking are in [Property-based testing reference](references/property-based-testing.md).

Generator rules: generate the input space the code actually accepts (use `filter` sparingly, prefer
constructive generators), include edge values (frameworks bias toward them), and bound sizes so a run
fits the unit-test budget. When a property fails, copy the shrunk counterexample into an explicit
example test so it is never lost.

## 5. Metamorphic and differential testing

Use when no oracle tells you the correct output, but you know how outputs must *relate*.

| Domain | Metamorphic relation |
|---|---|
| Search / ranking | Adding a non-matching document does not change the result set of a query |
| Sorting / aggregation | Permuting input does not change `sum`, `max`, set of outputs |
| Numerical integration | Splitting the interval and summing parts equals the whole (within error bound) |
| Geometry / graphics | Translating all inputs translates outputs; rotating a scene rotates the image |
| Compilers | Semantics-preserving rewrite of the source (dead code insertion) gives same program output |
| ML inference | Small label-preserving perturbation keeps the class (robustness check, not correctness) |
| Shortest paths | Adding an edge never lengthens the shortest path |

Differential testing compares two implementations on the same generated inputs: old vs new (refactors),
optimized vs naive, your parser vs a reference parser, `-O0` vs `-O2`, two database engines. Any
disagreement is either a bug in one of them or an undocumented spec ambiguity; both are worth knowing.

## 6. Fuzzing

Fuzz anything that consumes bytes from outside your trust boundary: parsers, decoders, deserializers,
protocol handlers, image/font/archive readers, and any `unsafe`/C code reachable from input.

| Language | Tool | Start command |
|---|---|---|
| Go | native fuzzing | `go test -fuzz=FuzzParse -fuzztime=60s ./parser` |
| Rust | cargo-fuzz (libFuzzer) | `cargo +nightly fuzz run parse -- -max_total_time=300` |
| C/C++ | libFuzzer, AFL++ | `clang -g -O1 -fsanitize=fuzzer,address f.c -o f && ./f corpus/` |
| Python | Atheris | `python fuzz_parse.py -max_total_time=300` |
| JVM | Jazzer | `@FuzzTest` with JUnit 5 |
| JS/TS | Jazzer.js | `npx jazzer fuzz_target` |

Always fuzz with sanitizers on, seed the corpus with real samples, add a dictionary for token-based
formats, and turn every crash into a minimized regression test. Details:
[Fuzzing and mutation testing reference](references/fuzzing-mutation.md).

## 7. Mutation testing

Mutation testing changes the code (flip `<` to `<=`, delete a call, return a constant) and checks that a
test fails. Mutation score = killed / (total - equivalent). Line coverage says code ran; mutation score
says tests would notice if it were wrong.

Run it on changed files only (full runs are slow): `cargo mutants --in-diff changes.diff`,
`mutmut run` with `paths_to_mutate` set, `npx stryker run --incremental`, PIT with `targetClasses`, Go
`gremlins unleash`. Each surviving mutant is either an equivalent mutant (document and ignore) or a
missing assertion (write it). Target: no surviving non-equivalent mutants in the code you changed.

## 8. Regression tests for bugs

1. Reproduce the bug as an automated test at the lowest level that shows it. Name it after the symptom
   and reference the issue: `test_invoice_total_handles_zero_quantity_issue_4812`.
2. Run it and confirm it fails **for the reason in the bug report** (read the assertion message; a test
   failing on an unrelated import error proves nothing).
3. Fix the code. Run the test: green.
4. Prove the test guards the fix: revert only the fix (`git stash push -- <fix files>`, or
   `git diff -- <fix files> | git apply -R` and reapply after), confirm the regression test is still
   present (co-located tests such as Rust `#[cfg(test)]` modules must not be stashed), run, see red, restore.
5. If the bug is an instance of a class (all inputs with property P break), add a property test for P.
6. `rg` for the same pattern elsewhere; siblings of a bug are common.

## 9. Flaky-test triage

A flaky test passes and fails on the same code. Treat it as a bug in the test or in the code, never as noise.

How many runs to trust a fix: to claim the failure rate is below p with 95% confidence after zero
failures, you need n >= ln(0.05) / ln(1 - p), roughly 3/p ("rule of three"). p = 1% needs 299 clean runs;
p = 5% needs 59. To estimate the current rate, run until at least 5 failures and divide.

```bash
LOG=.stack/out/<agent>/$(date +%Y%m%d-%H%M)-flaky-runs.log; mkdir -p "${LOG%/*}"   # output to file, not context
pytest tests/test_x.py::test_y --count=300 -x -p no:randomly >>"$LOG" 2>&1; echo "exit=$?"   # needs pytest-repeat
go test -run '^TestY$' -count=300 -race ./pkg >>"$LOG" 2>&1; echo "exit=$?"
for i in $(seq 300); do cargo test --quiet test_y >>"$LOG" 2>&1 || { echo "failed on run $i (log: $LOG)"; break; }; done
for i in $(seq 300); do npx vitest run -t "y" >>"$LOG" 2>&1 || { echo "failed on run $i (log: $LOG)"; break; }; done
```

| Cause | Signal | Detection | Fix |
|---|---|---|---|
| Order dependence / shared state | Fails only with other tests or in a certain order | `pytest -p randomly`, `go test -shuffle=on`, run alone vs full suite | Isolate state, fresh fixtures per test |
| Time | Fails near midnight, month end, DST, or under load | Freeze clock and replay the failing timestamp | Inject clock; no wall-clock asserts |
| Async waits / races | Fails more under CPU load (`stress-ng`, `-p 32`) | Race detector, TSan, increase parallelism | Wait on conditions, not sleeps; fix the race |
| External services | Network errors in logs | Run offline | Hermetic fakes or containers |
| Resource leaks, fixed ports | "address in use", fd exhaustion late in suite | `lsof`, run the suite twice in one process | Ephemeral ports (`:0`), cleanup fixtures |
| Randomness | Fails with certain seeds | Log seed; rerun with it | Fixed or recorded seeds |
| Float, locale, timezone, filesystem order | Fails only on some machines or CI images | Compare environments | Explicit tolerances, locale, sorted listings |

Quarantine policy: a quarantined test gets an issue, an owner and a deadline, and still runs (results
recorded, not gating). Automatic retries hide real races; use them only as a tracked stopgap.

Detailed playbooks per cause: [Flaky test playbook](references/flaky-tests.md).

## 10. Coverage interpretation

Coverage is a negative indicator: uncovered code is untested; covered code is not necessarily tested.

| Metric | Says | Use |
|---|---|---|
| Line / statement | The line ran | Find untested regions |
| Branch | Both outcomes of each decision ran | Default metric for gates |
| MC/DC | Each condition independently affects the decision | Safety-critical code (DO-178C level A) |
| Mutation score | Tests detect changes in behaviour | Strength of assertions in critical code |

Practice:
- Gate on **diff coverage** (changed lines, branch-level), e.g. >= 80%, not on a global number.
  `diff-cover coverage.xml --compare-branch=origin/main --fail-under=80`.
- Read the uncovered lines in changed code: error branches and early returns are the usual gaps.
- Exclude generated code; do not exclude hard-to-test code without a comment saying why.
- Rising coverage with falling mutation score means assertion-free tests were added.

Commands per language (coverage, randomization, repetition, benchmarks in tests):
[Test command cheat-sheet](references/commands.md).

## 11. Test plan template for a change

```markdown
## Test plan: <change>
Risk: <what breaks for whom if this is wrong>
| ID | Behaviour / requirement | Level | Technique | Test name | Status |
|----|-------------------------|-------|-----------|-----------|--------|
| T1 | Parses "1h30m" to 5400 s | unit | boundary + examples | test_parse_basic | new |
| T2 | format(parse(s)) round-trips | unit | property | test_roundtrip | new |
| T3 | Never panics on arbitrary input | fuzz | go fuzz 60 s | FuzzParseDuration | new |
| T4 | Config loader rejects "-5m" | integration | example | test_config_negative | new |
Not tested (and why): <...>
Commands: <exact commands that run T1-T4>
```

## 12. Worked example

Bug report: `parse_duration("0s")` returns `None` instead of 0, so a config with `timeout: 0s` falls
back to the default 30 s timeout.

1. Regression test: `assert parse_duration("0s") == 0`. Fails with `None != 0`: matches the report.
2. Root cause: `if not total: return None` treats 0 as missing. Fix: `if total is None`.
3. Revert-check: test red without the fix, green with it.
4. Class of bug: "zero-valued durations". Property: for `h, m, s` drawn from 0..99, the string
   `f"{h}h{m}m{s}s"` with each part optionally omitted (at least one kept) parses to `h*3600 + m*60 + s`.
   The generator produces `"0m"` and `"0h0m"` (same root cause), so the property covers them; against
   the unfixed code it fails on such zero inputs.
5. Sibling search: `rg -n "if not (total|count|size|n)\b"` finds the same pattern in `parse_size`; a
   failing test for `parse_size("0B")` confirms it. Both fixed, both reported.
6. Diff coverage 100% of changed lines; no assertion edited; full suite green 3 consecutive runs.

## Delegation

| Need | Agent |
|---|---|
| Run suites, E2E journeys, repeated flaky-runs, browser tests | `tester` |
| Failure with unknown cause after reproduction | `debugger` |
| Framework idioms (proptest strategies, jqwik arbitraries, Kotest) | language expert (`rust-expert`, `java-expert`, `kotlin-expert`, ...) |
| Check that criteria are met with test evidence | `validator` |
| Hard oracle questions (numerical error bounds) | `mathematics-expert`, `physics-expert` |

If you are `validator`, you may spawn only `tester`, `quick-researcher`, `deep-researcher`,
`fact-checker`, `quality-control`, `code-quality-analyst`, `adversarial-verifier` and `file-summarizer`
(config/policy.json spawn_rules). Route the other rows back to your caller as Open doubts.

Report test results as counts (passed / failed / skipped / errored) plus the exact command and exit code;
a skipped count that grew is reported as a finding, not as success.
