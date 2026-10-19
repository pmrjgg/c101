# Verdict examples

Extended worked verdicts in the SKILL.md format. Each shows the claim card, the falsification
hypotheses, what was run, and why the verdict and grade follow.

## Contents
- 1. Concurrency race (SURVIVES, E5)
- 2. Proof step (REFUTED, E5 counterexample)
- 3. Flaky-test root cause (NARROWED, E5)
- 4. Database capability claim (NARROWED, E3)
- 5. Path traversal finding (REFUTED, guarded elsewhere)
- 6. Capacity estimate (REFUTED, E4 derivation)
- 7. Aggregating five verdicts

## 1. Concurrency race

```text
id: F-21   claim: Cache.Get and Cache.Set race on the map `c.items` (pkg/cache/cache.go:57, :73)
quantifier: some interleaving   falsifier: race detector stays silent under concurrent Get/Set
```
Hypotheses: (1) a mutex already guards both; (2) Set only runs at init; (3) map is copy-on-write.
Read: Set takes `c.mu.Lock()`, Get reads `c.items[k]` without the lock (line 57). Set is called
from the refresh goroutine every 30 s, so (2) is false.
Repro: `go test -race -run TestCacheConcurrent -count=20 ./pkg/cache` with a test doing 8
goroutines of Get and 1 of Set: race detector reports a read at cache.go:57 and a write at cache.go:73.
**SURVIVES, basis reproduced, E5, confidence 0.97.** Severity note: concurrent map read/write in Go
can abort the process with a fatal error, so this is a crash bug, not only a stale read.

## 2. Proof step

```text
id: M-3   claim: for all integers n >= 1, n^2 + n + 41 is prime (step 4 of the submitted proof)
quantifier: all   falsifier: one n >= 1 with a composite value
```
Exhaustive check for n = 1..60 with a short script: n = 40 gives 1681 = 41 x 41; n = 41 gives
41 x 43. **REFUTED, basis counterexample, E5, confidence 0.99.** Narrowed claim that does hold:
"n^2 + n + 41 is prime for 0 <= n <= 39". The proof's conclusion must be re-checked, because step 4
was load-bearing.

## 3. Flaky-test root cause

```text
id: T-8   claim: test_upload is flaky because of network timeouts to the staging bucket
quantifier: typically   falsifier: failures persist with the network removed
```
Hypotheses: network; time-dependent assertion; shared temp directory; test order dependence.
Ran 200 times with the storage client stubbed (no network): 7 failures (3.5%). All 7 failures
assert `elapsed < 1.0` after a stubbed upload that sleeps up to 1.0 s inclusive.
**NARROWED, E5:** "test_upload fails about 3.5% of the time because of a timing assertion at the
1.0 s boundary; network is not required to reproduce". Original claim REFUTED (basis
failed-reproduction for the network cause).

## 4. Database capability claim

```text
id: P-2   claim: PostgreSQL 16 supports MERGE ... RETURNING, so step 5 needs no extra SELECT
conditions: production runs PostgreSQL 16.4
```
Primary sources: the PostgreSQL MERGE documentation for version 16 has no RETURNING clause; the
version 17 release notes list RETURNING support for MERGE. **NARROWED, E3:** "MERGE ... RETURNING
requires PostgreSQL 17 or later; on the production 16.4 cluster step 5 needs a follow-up SELECT or
an INSERT ... ON CONFLICT ... RETURNING rewrite." The plan must change; flag to the caller.

## 5. Path traversal finding

```text
id: S-5   claim: download handler at app/files.py:31 allows path traversal via `name`
source: reviewer report, failure scenario name=../../etc/passwd
```
Trace: `name = request.args["name"]` (line 27) -> `safe = secure_filename(name)` (line 29) ->
`send_file(os.path.join(UPLOAD_DIR, safe))` (line 31). Werkzeug's documented example maps
"../../../etc/passwd" to "etc_passwd". Local test with the app's test client requesting
`?name=../../etc/passwd` returns 404. Probes for absolute paths and encoded separators (`%2F`,
`..%5c`) also 404.
**REFUTED, basis guarded-elsewhere, E5, confidence 0.9.** Residual note for the reviewer:
`secure_filename` can return an empty string; line 31 then passes the upload directory itself to
`send_file`, an unhandled error (HTTP 500). That is a
separate, smaller finding (S-5b), sent back as a new claim rather than folded into this verdict.

## 6. Capacity estimate

```text
id: C-1   claim: 1 billion events per day at about 1 KB each needs about 1 TB of storage per month
```
Independent derivation (before reading the claimant's arithmetic): 1e9 x 1e3 B = 1e12 B = 1 TB
per day, so about 30 TB per month before compression and replication; with replication factor 3,
about 90 TB raw. The claimant divided by 30 instead of multiplying.
**REFUTED, basis derivation-conflict, E4, confidence 0.97.** Corrected figure goes back to the
caller with the derivation.

## 7. Aggregating five verdicts

Claim: "Retry loop in client.go:120 can amplify load 10x during an outage." Five lenses:

| Lens | Verdict | Grade | Note |
|---|---|---|---|
| correctness | SURVIVES | E2 | 3 attempts per layer x 3 layers (gateway, service, client) = up to 27 backend calls |
| performance | SURVIVES | E5 | fault-injection test: 1 failing request produced 27 backend calls |
| reproducibility | SURVIVES | E5 | re-ran the fault test from a clean checkout, same count |
| scope | NARROWED | E3 | gateway retries only idempotent GETs; for POSTs the factor is 9 |
| security | REFUTED | E1 | "not a security issue": off-lens, carries little weight |

Override check: the E5 fault-injection evidence re-ran in the aggregator's session (27 calls), so
the existential claim "it can amplify at least 10x" is confirmed outright. Majority: 3 SURVIVES of
5 also passes. Reported as: confirmed, amplification up to 27x for GETs and 9x for POSTs, with the
scope lens's narrowing attached.
