---
name: debugging-method
description: "Systematic debugging from symptom to verified root cause: intake, a one-command reproduction with exit-code contract, minimization (delta debugging, cvise/creduce, shrinkers), localization by bisection in history (git bisect run) and in space (pipeline midpoints, good-vs-bad diffs), instrumentation, a falsifiable hypothesis log, one change at a time, root cause vs symptom (5 whys, fix at the origin), regression test, sibling search, and blameless postmortem notes. Load when a bug, crash, wrong output, hang, leak, flaky failure or regression must be explained and fixed."
when_to_use: "Something behaves wrongly and the cause is not obvious after reading the code once; a test fails in CI but not locally; a regression appeared between two versions; a fix is proposed without a demonstrated root cause."
---

# Debugging method

Debugging is the scientific method under time pressure: observe, reproduce, form falsifiable
hypotheses, run the experiment that splits the hypothesis space best, and stop only at a cause you
can switch on and off. A fix without a reproduced failure is a guess.

## 0. The loop and its exit criteria

```
Intake -> Reproduce -> Minimize -> Localize -> Hypothesize <-> Experiment -> Fix -> Verify -> Prevent
```

Done means all of:
- [ ] A repro that fails before the fix and passes after it (N runs for intermittent bugs, section 8).
- [ ] A root-cause statement: the defect, the triggering condition, and why it produces the symptom.
- [ ] A regression test in the suite that fails without the fix.
- [ ] Sibling search done (same pattern elsewhere).
- [ ] Notes written (section 10) when the bug escaped to users or cost more than ~2 hours.

## 1. Intake

Collect before theorizing; write it at the top of the hypothesis log.

```markdown
Expected:    <exact expected behaviour, with source: spec, test, doc>
Actual:      <exact observed behaviour; paste the error verbatim, first and last 20 lines of trace>
Steps:       <minimal known steps>
Environment: <versions: app SHA, runtime, OS, dependency lockfile hash, config, data snapshot>
Frequency:   always | N of M runs | only under load | only in CI | only in prod
Last good:   <version/date where it worked, if known>   First bad: <...>
Artifacts:   logs, core dump, HAR, screenshots, failing CI job URL
```

Read the error message literally and completely before anything else; the answer is often in the
second line of the trace or in the "caused by" section that most people skip.

## 2. Reproduce

Write a one-command repro with an exit-code contract, so humans, `git bisect run` and agents can all
use it:

```bash
#!/usr/bin/env bash
# repro.sh: exit 0 = good (bug absent), 1 = bad (bug present), 125 = cannot test this revision
set -uo pipefail
make build >/dev/null 2>&1 || exit 125
out=$(./bin/app convert fixtures/case-4812.csv 2>&1)
grep -q "total: 0.00" <<<"$out" && exit 1 || exit 0
```

If it does not reproduce:

| Difference to eliminate | How |
|---|---|
| Data | Use the exact input (production sample, failing CI artifact); check encoding, size, ordering |
| Versions | Same SHA, lockfile, runtime; `git status` clean; rebuild from scratch (stale build artifacts) |
| Configuration and environment | Diff `env`, config files, feature flags, locale, TZ, CPU count, file system case sensitivity |
| Timing and load | Loop it (`for i in $(seq 200)`), add CPU pressure, more threads, inject delays at suspected race points, `rr record --chaos` (Linux) |
| State | Fresh vs reused DB/cache/session; order of prior operations |
| Platform | Container with the CI image (`docker run --rm -v "$PWD":/src -w /src <ci-image> ./repro.sh`; no `-it`, agents have no TTY), same architecture |

Still not reproducible: instrument where it does happen (structured logs with correlation IDs around
the suspected path, extra assertions that dump state) and wait for the next occurrence. Record the
repro rate when you find one ("fails 7/200 runs").

## 3. Minimize

Smaller repros make causes obvious and tests fast. Minimize input, code and environment.

- **Input**: delta debugging (ddmin): split the input into n chunks; if a chunk alone still fails, recurse
  into it; else if removing a chunk still fails, drop it; else double n. Automated tools:
  `cvise ./interesting.sh case.c` / `creduce` (C/C++ and other text), `shrinkray`, property-test shrinkers,
  `cargo fuzz tmin`, libFuzzer `-minimize_crash=1`. The interestingness script exits 0 when the bug is
  still present (note: opposite polarity to `repro.sh`).
- **Code**: delete calls, branches and modules until the bug disappears; the last deletion that made it
  disappear points at the cause. For dependency bugs build a minimal project with only the dependency.
- **Environment**: strip flags, plugins, extensions, middleware one at a time.

## 4. Localize

### In history: `git bisect`
```bash
git bisect start <bad-sha> <good-sha>      # or: git bisect start; git bisect bad; git bisect good v1.4.0
git bisect run ./repro.sh                  # 0 good, 1-124/126-127 bad, 125 skip
git bisect log > .stack/out/debugger/bisect.log
git bisect reset
```
- About log2(N) steps: 1,000 commits take ~10 builds.
- `git bisect start --first-parent` on merge-heavy histories to find the merged PR first.
- Bisect performance regressions with a benchmark predicate (exit 1 if slower than threshold) and custom
  terms: `git bisect start --term-old=fast --term-new=slow`.
- Bisect dependency upgrades by bisecting the lockfile: apply half the version bumps, test, recurse.

### In space
- **Pipeline midpoint**: dump intermediate data at the middle stage; if correct there, the bug is
  downstream; recurse (binary search over stages).
- **Good vs bad diff**: run the passing and failing case with identical tracing and diff the logs; the
  first divergence is the place to look (`diff <(./app good 2>&1) <(./app bad 2>&1) | head`).
- **Stack traces**: start at the deepest frame in your code, not the library frame where it surfaced.
- **Watchpoints** find who changed a value: `watch -l obj->field` (gdb), `watchpoint set expression -- &x` (lldb).
- **Reverse execution**: `rr record ./prog; rr replay`, then `reverse-continue` to the last write of a
  corrupted value (Linux x86-64).

## 5. Hypothesis log

Keep it in `.stack/out/<agent>/<YYYYMMDD-HHMM>-debug-<slug>.md`. One row per hypothesis, written
*before* running the experiment.

| # | Hypothesis | Prediction if true | Experiment | Result | Verdict | P(after) |
|---|---|---|---|---|---|---|
| H1 | Rounding happens before the discount is applied | Total for qty=3 x 0.335 is 1.00 not 1.01 | Unit call with those inputs | 1.01 | Refuted | 0.05 |
| H2 | Locale-dependent decimal parsing in CI (de_DE) | `LC_ALL=de_DE.UTF-8 ./repro.sh` fails locally | Run with locale set | Fails | Supported | 0.85 |
| H3 | `float()` on "0,335" silently parses "0" via fallback in `to_decimal` | Log shows input "0,335", value 0 | Add log at to_decimal | Confirmed | Root cause | 0.97 |

Rules:
- Each hypothesis has a prediction that could fail. "Something with caching" is not a hypothesis.
- Prefer experiments that split the remaining hypotheses roughly in half, and cheap ones first.
- Record refuted hypotheses; they stop you (and the next agent) from retesting them.
- Change one variable per experiment. Two simultaneous changes that "fix it" teach nothing.
- Before trusting any result, check that the code you are reading is the code that runs (stale build,
  wrong branch, cached artifact, different deployed version, shadowing module on `PYTHONPATH`).

## 6. Instrument and observe

| Need | Tools |
|---|---|
| State at a point | Debugger breakpoints (conditional, logpoints), `breakpoint()`/pdb, `dlv`, lldb/gdb |
| Flow over time | Structured logs with request IDs, tracing spans (OpenTelemetry), `RUST_LOG=debug` |
| Invariant violations | Temporary assertions at module boundaries; fail fast close to the cause |
| System interaction | `strace -f -e trace=file,network`, `ltrace`, `lsof -p`, `fs_usage` (macOS), `tcpdump`, bpftrace |
| Memory errors and UB | ASan/UBSan/MSan, Valgrind memcheck, Miri, `GODEBUG`, `-race`/TSan |
| Hangs | All-thread stack dumps: `jstack`/`jcmd Thread.print`, `py-spy dump`, `kill -QUIT` (Go), `thread apply all bt` |
| Crashes post-mortem | Core dumps (`ulimit -c unlimited`; `coredumpctl` on systemd), crash reports, minidumps |

Command details per language and tool: [Debugging tools cheat-sheet](references/tools.md).

Remove temporary instrumentation before finishing (or convert useful assertions into permanent checks
deliberately).

## 7. Root cause, not symptom

Ask "why" until you reach a cause you can fix that would have prevented the whole class:

```
Symptom:   invoice totals are 0.00 for some German customers.
Why 1:     unit_price parsed as 0.          Why 2: "0,335" fails float(), fallback returns 0.
Why 3:     to_decimal() swallows ValueError and returns a default.
Why 4:     CSV import accepts locale-formatted numbers without declaring the locale.
Root cause: silent fallback in to_decimal() + undeclared input locale.
```

Where to fix:

| Situation | Fix at |
|---|---|
| Bad data created upstream, crash downstream | The origin of the bad data, plus validation at the trust boundary |
| Function silently accepts invalid input | The function: reject loudly (error), do not default |
| Several callers misuse an API the same way | The API (make misuse impossible or loud), not each caller |
| Symptom fix is urgent | Ship the mitigation, label it as such, open a tracked root-cause fix |

Then ask "why was it not caught?": missing test, missing validation, missing alert. That answer becomes
a prevention item.

Sibling search: `rg -n "except (ValueError|Exception):\s*$" -A2` or the equivalent pattern for the
defect; the same mistake usually exists in more than one place. Report or fix siblings explicitly.

## 8. Fix and verify

1. Write the regression test first (fails for the reported reason), per the `testing-strategy` rules.
2. Make the minimal fix at the root-cause location.
3. Run the regression test, the module's suite, then the full relevant suite.
4. Intermittent bugs: run the repro N times. With a pre-fix failure rate p, zero failures in
   n >= ln(0.05)/ln(1 - p) runs gives 95% confidence the rate dropped below p (p = 5%: 59 runs; 2%: 149).
5. Check the fix does not just move the failure: re-run the original end-to-end steps from intake.
6. Review your own diff for unintended behaviour changes (other callers of what you changed).

## 9. Symptom to first moves

| Symptom | First moves |
|---|---|
| Segfault / access violation | ASan build; core dump backtrace; check lifetimes, bounds, use-after-free; `rr` |
| Hang / deadlock | All-thread stack dump twice, 10 s apart; look for lock order cycles, waits without timeouts, pool exhaustion |
| Memory growth | Heap snapshots at two times and diff; unbounded caches, listeners, goroutine/thread counts |
| Wrong result only in release/optimized build | UB (sanitizers), uninitialized memory, float fast-math, data races, timing |
| Passes locally, fails in CI | Environment diff (section 2 table), test order, parallelism, missing services, time zone/locale |
| Intermittent | Concurrency or time or ordering; run with race detectors, shuffle, stress; log seeds |
| Regression after upgrade | `git bisect` or lockfile bisect; read the changelog of the bisected dependency |
| Performance regression | Bisect with a benchmark predicate; differential profiles (see `performance-optimization`) |
| Only for some users / data | Find the distinguishing attribute: locale, encoding, size, permissions, feature flag cohort |
| Off-by-one around dates | DST transitions, month ends, leap days, UTC vs local conversions |
| Encoding garbage | Byte-level dump (`xxd`), declared vs actual encoding, double encoding (UTF-8 bytes decoded as Latin-1) |

Longer playbooks per symptom: [Symptom playbooks](references/symptom-playbooks.md).

## 10. Postmortem notes (blameless)

```markdown
## Bug <id>: <one-line summary>
Impact:       who/what was affected, how long, how much (orders, users, data)
Timeline:     first bad deploy, first report, repro, root cause, fix deployed (UTC times)
Root cause:   defect + trigger + mechanism (from section 7)
Detection:    how it was found; how it should have been found
Fix:          commit/PR; regression test name
Why not caught earlier: missing test / validation / alert / review gap
Action items: | action | owner | due | issue |
Siblings:     other locations with the same pattern and their status
```

## 11. Time-boxing and escalation

- After ~5 refuted hypotheses or ~45 minutes without narrowing: stop and re-verify the basics (is the
  build fresh, is this the running version, is the repro measuring the right thing, is the expected
  behaviour actually specified?).
- Explain the problem in writing from scratch (the act of writing the brief often reveals the gap);
  then, only if `budget="ok"` and `remaining_depth` >= 1, spawn a fresh `debugger` with that brief; at
  `budget="soft"` or `"hard"` put the brief and the hypothesis log path in Open doubts instead.

| Need | Agent |
|---|---|
| Run a repro loop N times, write the regression test, CI-like environment | `tester` |
| Exact error string, known upstream issue, changelog of a dependency | `quick-researcher` |
| Language/runtime semantics (UB, memory model, GC, async runtime behaviour) | `rust-expert`, `cpp-expert`, `go-expert`, `java-expert`, `kotlin-expert`, `haskell-expert`, `julia-expert`, `python-expert`, `typescript-expert` |
| The bug looks exploitable (memory corruption from input, auth bypass) | `security-auditor` |
| Performance regression analysis | `code-optimizer` |
| Independent check that the root cause explains all observations | `adversarial-verifier` |

Brief template for a fresh debugger: symptom, repro command, environment, hypothesis log path (with
refuted hypotheses), what you want back (root cause statement with evidence, or the next experiment).

## Output

Result: root cause in one paragraph, the fix, and status of the regression test. Evidence: repro
command with before/after exit codes and run counts, the decisive experiment from the hypothesis log,
bisect result if used. Files: hypothesis log, repro script, test, fix diff.
