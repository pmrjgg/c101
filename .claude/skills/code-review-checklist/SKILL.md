---
name: code-review-checklist
description: "Principal-level code review procedure across correctness, error handling, concurrency, security, API design, performance, tests and readability, with a severity rubric, a file:line + failure-scenario + fix finding format, and a verify-before-report protocol. Load when reviewing a diff, PR, branch range or module, or when triaging review findings produced by others."
when_to_use: "Reviewing changes or a code area; running one dimension inside /review-verify; deciding whether a suspected defect is real before reporting it; writing findings that someone will act on without asking you follow-up questions."
---

# Code review checklist

A review exists to find defects that would reach users, and to say so in a form the author can act on
in one pass. Every finding you report is a claim with a concrete failure scenario and evidence. A
suspicion without a scenario is a question, not a finding.

## 1. Scope the review before reading code

1. Identify the target and its size.
   ```bash
   git diff --stat origin/main...HEAD          # three dots = changes since merge-base
   git log --oneline origin/main..HEAD
   gh pr view 123 --json title,body,files,baseRefName && gh pr diff 123
   git diff -U10 origin/main...HEAD -- src/    # extra context lines around hunks
   ```
2. Write one sentence: "This change intends to <X> by <Y>." If you cannot, read the PR body, linked
   issue and commit messages; if still unclear, that is an Open doubt for the caller.
3. Budget by size of *logic* changed (exclude lockfiles, generated code, snapshots, vendored code).

   | Logic lines changed | Approach |
   |---|---|
   | < 400 | One pass, all dimensions, by you |
   | 400 - 1500 | Split by subsystem; review each chunk fully before the next |
   | > 1500, or > 30 files | Main thread only (no `<stack-context>` header): `review-verify` workflow with `target` + explicit `dimensions`. As a subagent: shard per subsystem and spawn one `reviewer` per shard as parallel Agent calls in one message with `run_in_background: false`, or return `Workflow name=review-verify args={"target":"<range>","dimensions":[...]}` as an Open doubt |

4. Mark the risk surface. Any of these raises the depth for the listed dimensions.

   | Signal in the diff | Extra depth on |
   |---|---|
   | Auth, sessions, permissions, crypto, parsing of external input, file paths, shell, SQL | security (load the `security-review` approach or delegate to `security-auditor`) |
   | Locks, async, threads, goroutines, channels, shared caches, DB transactions, queues | concurrency |
   | Public API, wire formats, DB schema, config keys, CLI flags, exported types | API design, backward compatibility |
   | Loops over request data, new queries, caches, hot paths named in profiles | performance |
   | Deleted or edited assertions, new `skip`/`xfail`/`@Disabled`, changed golden files | tests (treat as weakening until proven otherwise) |
   | Migrations, backfills, feature flags, deploy ordering | correctness under partial rollout |

## 2. Reading order

1. **Tests first.** They tell you what the author believes the code does and which cases they thought of.
   Missing cases become your first hypotheses.
2. **Types, interfaces, schemas, signatures.** Contract changes are where callers break.
3. **Core logic**, top-down from the entry point.
4. **Outside the diff.** The diff hides callers and siblings. For every changed signature, return
   value, error type or side effect:
   ```bash
   rg -n "\bfunctionName\s*\(" --type-add 'src:*.{py,ts,go,rs,java,kt}' -t src
   rg -n "implements PaymentGateway|impl PaymentGateway for"   # other implementations
   ```
5. **Config, migrations, infra, CI** last, but never skipped.

## 3. Checklist by dimension

High-yield checks only. The extended catalog with domain-specific items (migrations, frontend, data
pipelines, IaC, shell) is in [Extended checklist catalog](references/checklist-catalog.md); per-language
traps are in [Language pitfalls](references/language-pitfalls.md).

### Correctness
- [ ] Boundaries: empty, single element, maximum size, exactly-at-limit; inclusive vs exclusive ranges.
- [ ] Integer overflow, truncating casts (`int64 -> int32`, `usize as u32`), sign of `%` on negatives
      (follows the dividend in C/C++/Java/Go/Rust/JS, the divisor in Python; use `rem_euclid`/`Math.floorMod`
      when a non-negative index is needed).
- [ ] Absent values: null/None/undefined/nil/Option; defaults that mask a valid zero (`x or 10` when 0 is legal).
- [ ] Semantic change behind an unchanged signature (same name, different meaning) for existing callers.
- [ ] Partial failure: what state is left if the operation fails halfway (two writes, no transaction)?
- [ ] Retries and re-delivery: is the operation idempotent? Duplicate side effects (double charge, double email)?
- [ ] Time: wall clock used for durations (use monotonic), time zones, DST, `now()` read twice in one decision.
- [ ] Floating point equality; money in binary floats; rounding mode.
- [ ] Mutation during iteration; aliasing (shared mutable default args, slice/array views, shallow copies).
- [ ] Text: bytes vs code points vs graphemes, normalization, case folding, locale-dependent formatting.

### Error handling
- [ ] No swallowed errors: `except: pass`, `catch (e) {}`, `_ = f()`, `let _ = f();`, `.catch(() => {})`.
- [ ] Errors keep their cause (`raise ... from e`, `fmt.Errorf("...: %w", err)`, `anyhow::Context`); no
      control flow by matching error message strings.
- [ ] Cleanup on every exit path: locks, file handles, transactions rolled back, temp files removed.
- [ ] Every network or IPC call has a timeout; cancellation propagates (`context.Context`, `AbortSignal`,
      `CancellationToken`, task cancellation).
- [ ] Retries are bounded, use backoff with jitter, and only wrap idempotent operations and retryable errors.
- [ ] Exceptions or panics do not cross thread, task, FFI or callback boundaries unobserved.
- [ ] User-facing errors do not leak stack traces, SQL, file paths or secrets.

### Concurrency
- [ ] Every shared mutable value is identified, and every access uses the same synchronization.
- [ ] Check-then-act races (exists-then-create, read-modify-write, lazy init) are atomic or guarded.
- [ ] Lock ordering is consistent; no lock held across `await`, I/O, callbacks or user code.
- [ ] Async: no blocking calls on the event loop/runtime; no forgotten `await`; fire-and-forget tasks
      have error handling; fan-out is bounded (no `Promise.all` over 10k items).
- [ ] Goroutines/threads/tasks have a guaranteed exit (channel receiver exists, ctx cancelled, joined).
- [ ] Atomics: publication uses release/acquire, not relaxed; no mixed atomic and plain access.
- [ ] Database: isolation level fits; lost updates prevented (`SELECT ... FOR UPDATE`, version column,
      or a conditional `UPDATE ... WHERE version = ?`); uniqueness enforced by a constraint, not by code.
- [ ] Messaging: at-least-once delivery handled with idempotency keys; ordering not assumed across partitions.

### Security (screening level)
- [ ] Untrusted input reaches a sink (SQL, shell, file path, template, HTML, URL fetch, deserializer,
      regex) only through the context-correct defense (parameterization, argv arrays, canonicalize + base
      check, auto-escaping, allowlists).
- [ ] Every new endpoint, handler, job or RPC checks authorization, including object ownership (IDOR).
- [ ] No secrets or PII in code, logs, error messages, URLs or analytics events.
- [ ] Crypto: library primitives only, CSPRNG for tokens, constant-time comparison for MACs and tokens.
- [ ] New dependency: maintained, licensed compatibly, no install scripts surprises, version pinned in lockfile.

### API design and compatibility
- [ ] Names and semantics match neighbours; least surprise for a caller reading only the signature.
- [ ] Backward compatibility: removed or renamed fields, changed defaults, new required parameters,
      narrowed accepted input, changed error types, new enum variants breaking exhaustive matches,
      protobuf field numbers reused, JSON keys renamed.
- [ ] Illegal states unrepresentable: boolean flag pairs become an enum; optional-but-required-together
      fields become one struct.
- [ ] Ownership and lifecycle are explicit: who closes, who frees, who may retain a reference.
- [ ] HTTP: correct status codes, idempotency of PUT/DELETE, pagination for unbounded lists, versioning.
- [ ] Schema changes follow expand/contract: add nullable, dual-write, backfill in batches, switch reads,
      then drop. Lock-taking DDL on large tables is flagged.

### Performance (flag only with a size or hotness argument)
- [ ] Quadratic patterns on data that can grow: nested loops, `x in list` inside a loop, repeated
      string concatenation, sorting inside a loop.
- [ ] N+1 queries; queries without a supporting index (ask for `EXPLAIN` on the new query).
- [ ] Unbounded growth: caches without eviction, listeners never removed, buffers that never shrink.
- [ ] Whole-file or whole-table loads where streaming is possible; synchronous I/O on a request path.
- [ ] Repeated expensive setup: regex compilation, client construction, connection opening per call.
- For measured claims use the `performance-optimization` method or delegate to `code-optimizer`.

### Tests
- [ ] New behaviour has a test that fails without the change. Ask: "If I revert the fix, does a test go red?"
- [ ] Assertions are specific (values, not just "no exception"; not a snapshot of everything).
- [ ] Edge cases from the correctness list are covered where they are reachable.
- [ ] No `sleep` for synchronization; time, randomness and IDs are injected or seeded.
- [ ] No weakening: loosened tolerances, broader expected exceptions, deleted assertions, new skips,
      regenerated golden files without explanation. Each instance needs a stated reason.
- [ ] Mocks do not replace the unit under test; mocked behaviour matches the real dependency's contract.

### Readability and maintainability
- [ ] Names carry domain meaning; functions do one thing; nesting is shallow.
- [ ] No dead code, commented-out code, debug prints, or duplicated logic that already exists as a helper
      (`rg` for the helper before claiming duplication).
- [ ] Comments explain *why*; TODOs reference an issue.
- [ ] Formatter and linter pass (run them; do not hand-review style).
- Readability findings are S3 unless they hide a defect.

## 4. Severity rubric

Severity is impact x likelihood. Rate each independently, then read the matrix.

| Impact \ Likelihood | Likely (common path, normal input) | Plausible (realistic but uncommon) | Rare (contrived, needs several conditions) |
|---|---|---|---|
| **High**: data loss or corruption, security breach, outage, irreversible migration, money moved wrongly | S0 | S0 | S1 |
| **Medium**: wrong result visible to users, leak under load, broken API for some callers, missing test for core behaviour | S1 | S1 | S2 |
| **Low**: degraded message, minor inefficiency off hot path, maintainability debt | S2 | S2 | S3 |

| Level | Meaning | Merge impact |
|---|---|---|
| S0 Blocker | Must not ship | Block |
| S1 Major | Real defect on realistic inputs | Request changes |
| S2 Minor | Edge case or debt worth fixing | Comment; may merge with follow-up issue |
| S3 Nit | Style, naming, wording | Batch into one comment; never blocks |

Confidence is separate from severity:

| Confidence | Requirement | Where it goes |
|---|---|---|
| Confirmed | Reproduced: failing test, script output, race detector report, or compiler error | Findings |
| Probable | Concrete code-path trace with line numbers, precondition shown reachable | Findings, marked Probable |
| Speculative | Pattern match without a traced path | Open doubts or a question to the author, never a finding |

## 5. Finding format

One defect per finding. Concrete scenario, evidence, minimal fix.

```markdown
### [S1][concurrency] Cache refresh races with invalidation (<=60 chars)
- Location: src/cache/store.go:142 (writer), src/cache/store.go:198 (invalidator)
- Failure scenario: refresh() reads v1 from DB at t0; Invalidate(k) runs at t1 and deletes k;
  refresh() stores v1 at t2. Readers get stale v1 until TTL (10 min) although v2 was committed.
- Evidence: interleaving traced above; `go test -race -run TestRefreshInvalidate ./cache` (test in
  .stack/out/reviewer/20261019-1412-race-test.go) reports a stale read in 37/100 runs.
- Fix: store with a generation check: capture gen before the DB read, `if s.gen[k] == gen { s.m[k] = v }`
  under the same mutex; bump gen in Invalidate. Add the test above to the suite.
- Confidence: Confirmed
```

Rules:
- The failure scenario names inputs or state and the wrong outcome. "Could cause issues" is not a scenario.
- No hedged verbs ("consider", "might want to") in S0-S2 findings. State the defect.
- The fix is the smallest correct change; offer a larger redesign only as a separate S2/S3 note.
- Quote at most the few lines needed; point to line numbers instead of pasting blocks.

Bad vs good:

| Bad | Good |
|---|---|
| "Possible SQL injection in user search." | "[S0][security] `q` from `GET /users?q=` is f-string-interpolated into SQL at api/users.py:57; `q=' OR '1'='1` returns all rows (repro test attached). Fix: `cur.execute('... WHERE name ILIKE %s', (f'%{q}%',))`." |
| "Error handling could be improved." | "[S1][error-handling] `os.remove(tmp)` at jobs/export.py:88 is skipped when `upload()` raises; a failing S3 call leaves 2 GB temp files per job (disk filled on 2026-10-02 per incident log). Fix: `try/finally`." |

## 6. Verify before reporting

Run this for every S0-S2 candidate. Most false positives die at steps 2-3.

1. **Re-read with exact lines.** `Read` the file at the cited offset; confirm the code is what you think
   and that line numbers are current (not from a stale diff).
2. **Reachability.** Find callers (`rg`) and confirm the triggering precondition can occur: is the input
   validated upstream, constrained by type, or impossible by construction?
3. **Guard elsewhere.** Check middleware, decorators, ORM parameterization, framework auto-escaping, DB
   constraints, language guarantees (bounds checks, null safety), retries in a wrapper.
4. **Reproduce cheaply.** Write a minimal failing test or script under `.stack/out/<agent>/` (the
   `out_dir` in your `<stack-context>` header), run it, keep the output. For races use the race tool (`go test -race`,
   `-fsanitize=thread`, `cargo +nightly miri test`, loom) or a written interleaving table.
5. **Check intent.** Docs, tests, commit messages, ADRs may show the behaviour is deliberate. If
   deliberate but wrong, the finding is about the requirement: route to the caller as an Open doubt.
6. **Self-refute for two minutes.** Argue the finding is false using the `adversarial-verification`
   lenses. If you cannot write the failure scenario concretely, downgrade to Speculative.

| Outcome of verification | Report as |
|---|---|
| Reproduced | Finding, Confirmed |
| Traced path, precondition reachable, not reproduced (too costly) | Finding, Probable, with the cost noted |
| Guard found elsewhere | Drop; optionally S3 note "guard lives in X, consider asserting here" |
| Behaviour intended but questionable | Open doubt for the caller, not a finding |
| Cannot decide without runtime facts | Open doubt routed to `tester` or `debugger` per doubt-escalation |

False-positive traps:
- Parameterized ORM calls flagged as SQL injection; React/Jinja2 autoescaped output flagged as XSS.
- "Missing null check" where the type system or a constructor invariant guarantees non-null.
- "Race" on data confined to one goroutine/thread/actor, or on immutable data after publication.
- "Unbounded" loops whose bound is enforced by a schema or validator upstream.
- "Leak" of a resource that a framework scope (request context, `with`, `using`, RAII) owns.
- Scanner output reported without reading the code (semgrep, CodeQL, clippy). Tools produce candidates.

## 7. Delegation during a review

| Need | Spawn | Brief contents |
|---|---|---|
| Large diff, several dimensions | Main thread only (no `<stack-context>` header): `review-verify` workflow (`target` + `dimensions`). As a subagent: parallel `reviewer` Agent calls per shard with `run_in_background: false`, or the Open doubt `Workflow name=review-verify args={target, dimensions}` | Saves you merging and verification |
| Deep security path (auth, crypto, deserialization) | `security-auditor` | file:line list, threat question |
| Speed or memory claim needs numbers | `code-optimizer` | the code path, the workload, the claim |
| Need a test executed or written to confirm | `tester` | exact test to write, command to run, expected red/green |
| Language semantics question (UB, lifetimes, memory model) | `rust-expert`, `cpp-expert`, `go-expert`, `java-expert`, `kotlin-expert`, `haskell-expert`, `julia-expert`, `python-expert`, `typescript-expert` | the snippet path and the precise question |
| Independent refutation of an S0/S1 | `adversarial-verifier` | the finding in the format above |
| Complexity or duplication across the module | `code-quality-analyst` | paths, metric needed |

Keep for yourself: reading, tracing, writing findings, the verdict. At `remaining_depth` 0 do the
verification yourself or mark the finding Probable and list the unrun check under Open doubts.

## 8. Review verdict and report

| Condition | Verdict |
|---|---|
| Any S0 | Block |
| Any S1 | Request changes |
| Any S2 (no S0/S1) | Approve with comments |
| Only S3 | Approve (nits batched) |
| Nothing | Approve |

Report skeleton (findings ranked S0 first, then by confidence):

```markdown
## Result
Status: done
Verdict: Request changes. 1 S0, 2 S1, 3 S2, 5 S3 (S3 batched at the end).
Intent understood as: <one sentence>.

### Findings
<findings in the section 5 format>

### Coverage
| Area / file group | correctness | errors | concurrency | security | API | perf | tests | readability |
|---|---|---|---|---|---|---|---|---|
| src/cache/* | done | done | done | screened | n/a | done | done | done |
Not reviewed: vendored/, generated protobufs, migrations/0042 (out of scope per brief).

## Evidence
Commands run with exit codes; paths of repro tests under .stack/out/<agent>/.
```

Then the output-contract sections (Files, Open doubts, Confidence). If the findings exceed ~60 lines or
~3k characters, write them to `.stack/out/<agent>/<YYYYMMDD-HHMM>-review-<slug>.md` and return the
summary table plus the path and line anchors.

## 9. Anti-patterns

- Reviewing only the hunk: callers, sibling implementations and rollback paths are where breakage hides.
- Burying one S0 under thirty nits. Lead with severity; batch nits.
- Reporting unverified scanner or pattern-match hits as findings.
- Style opinions that the formatter or linter does not enforce.
- Rewriting the design in review comments when the change is correct. Note it as S3 or a follow-up issue.
- Approving because tests pass without checking that the tests exercise the change.
