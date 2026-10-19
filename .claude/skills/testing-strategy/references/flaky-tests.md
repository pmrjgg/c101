# Flaky test playbook

## Measuring

- Failure rate estimate: run until you have at least 5 failures; rate = failures / runs.
- Zero failures in n runs bounds the rate below about 3/n at 95% confidence (rule of three).
  Required clean runs to claim rate < p: n >= ln(0.05) / ln(1 - p).

  | Target p | Clean runs needed |
  |---|---|
  | 10% | 29 |
  | 5% | 59 |
  | 1% | 299 |
  | 0.1% | 2995 |

- Before/after a fix: report "k1/n1 failures before, 0/n2 after"; n2 must satisfy the table for the
  pre-fix rate (if the test failed 4% of the time, 0/75 clean runs is meaningful, 0/10 is not).
- Run under the conditions that expose it: CI image, parallel workers, CPU pressure
  (`stress-ng --cpu 0 --timeout 600s &` on Linux), random order.

## Triage flow

1. Get the failure output from CI (full log, seed, test order, timing). Do not rerun blindly.
2. Reproduce locally with the same seed and order; if not, add CPU pressure and parallelism.
3. Classify with the table in SKILL.md section 9; apply the matching playbook below.
4. Fix the cause. Prove with the run-count table.
5. If not fixable now: quarantine with issue, owner, deadline; keep it running non-gating.

## Playbooks

### Order dependence
- Bisect the test order: run the failing test after the first half of preceding tests, then the second
  half; repeat. pytest: `pytest -p randomly --randomly-seed=<seed>` then trim the list with `--deselect`.
  `pytest-randomly` prints the seed at the top of the run.
- Go: `go test -shuffle=<seed printed on failure> -run 'TestA|TestB'`.
- Usual causes: module-level caches, singletons, environment variables set without restore
  (`monkeypatch.setenv`, `t.Setenv` restore automatically), DB rows left behind, mocked globals not undone.

### Time-dependent
- Freeze time at the failing timestamp (`freezegun.freeze_time("2026-03-29T01:30:00+01:00")`,
  `vi.setSystemTime(...)`, a fixed `Clock`).
- Common: "today" computed twice across midnight; DST gaps (02:30 does not exist on spring-forward day);
  month-end arithmetic; timeouts measured with wall clock; token expiry in fixtures created once per
  session.

### Async and concurrency
- Replace `sleep(n)` with waiting on a condition: poll with deadline, `asyncio.wait_for(event.wait(), 5)`,
  `eventually` helpers, Playwright web-first assertions (`await expect(locator).toHaveText(...)`,
  which retry until timeout) instead of reading text once.
- Run with race detectors: `go test -race`, `-fsanitize=thread`, Java `jcstress` for low-level code.
- Increase contention to reproduce: more workers, CPU pressure, `GOMAXPROCS=1` vs high values.
- Unawaited tasks finishing after the test ends and failing the next test: ensure each test awaits or
  cancels what it started (pytest-asyncio strict mode, `asyncio.TaskGroup`).

### External dependencies
- Network calls in tests: block outbound network in unit tests (`pytest-socket` `--disable-socket`), use
  recorded fixtures or containers.
- Containers not ready: use readiness wait strategies (Testcontainers log/port/health waits), never a
  fixed sleep.
- Shared staging environments: give each test run unique namespaces (prefix resources with run id).

### Resources
- Fixed ports: bind to port 0 and read the assigned port.
- File descriptors and temp dirs: per-test temp dirs (`tmp_path`, `t.TempDir()`), cleanup on failure.
- Memory pressure in CI: smaller parallelism or bigger runners; look for OOM-killer messages.

### Randomness and data
- Log the seed of every RNG used in tests; reproduce with it.
- Generated data colliding with unique constraints (two random emails equal); use sequences.
- Sets/maps iterated in nondeterministic order compared to fixed lists; sort before comparing.

### Environment
- Locale (`LC_ALL`), timezone (`TZ`), filesystem case sensitivity (macOS default vs Linux), path
  separators, line endings, CPU features (SIMD paths giving different float results).
- Pin these in CI and in the test runner config; compare `env` dumps between passing and failing hosts.

### UI and E2E specifics
- Use role/label locators, not CSS paths tied to layout.
- Wait for network idle only when necessary; prefer waiting for the specific element state.
- Disable animations in test builds.
- Record traces on retry (Playwright `trace: 'on-first-retry'`) and inspect the failing step.
- Seed test data through APIs, not through the UI, to shorten and stabilize journeys.

## Quarantine record template
```markdown
Test: tests/api/test_orders.py::test_concurrent_checkout
Observed rate: 6/200 runs (3%) on CI linux-x64, 0/200 on macOS
Suspected cause: race between inventory reservation and payment callback (not confirmed)
Issue: #4821  Owner: payments team  Deadline: 2026-11-02
Mode: runs on every PR, non-gating; results tracked in the CI dashboard
```
