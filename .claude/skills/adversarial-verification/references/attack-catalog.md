# Attack catalog

Falsification probes per claim type, with commands. Pick the probes your lens owns; record every
probe tried in `attempts`, including those that failed to refute. Run repros from
`<out_dir>/<stamp>-<slug>/`, never by editing the code under review.

## Contents
- Code correctness
- Concurrency
- Memory safety and undefined behaviour
- Numerics
- Performance
- Security findings
- Dependency and CVE claims
- Factual and external claims
- Math and proof steps
- Experimental and ML results
- Statistical claims
- Capability and plan claims
- Minimal repro skeletons

## Code correctness

| Probe | What it catches |
|---|---|
| Reachability: Grep all callers of the function, follow to an entry point | findings on dead or internal-only code |
| Upstream guards: validation, schema, type constraints, framework defaults | "missing check" findings already handled |
| Boundaries: 0, 1, n-1, n, max, empty, None/null, duplicate, unsorted | off-by-one, empty-collection crashes |
| Error paths: dependency raises, timeout, partial write, retry after failure | unhandled exceptions, leaked resources |
| Encoding: non-ASCII, combining characters, CRLF, BOM, very long strings | parsing and length bugs |
| Time: DST transitions, leap day, time zones, clock going backwards | scheduling and expiry bugs |
| Property-based search | universal claims |

Commands:
```bash
pytest -x -q <out_dir>/<stamp>-<slug>/test_claim.py         # Python repro
pytest -q -p no:randomly --hypothesis-seed=0 <out_dir>/<stamp>-<slug>/test_prop.py   # Hypothesis, reproducible
cargo test --test claim -- --nocapture                      # Rust repro (proptest inside)
go test ./pkg/x -run TestClaim -count=1 -v                  # Go repro
go test ./pkg/x -fuzz=FuzzParse -fuzztime=60s               # Go native fuzzing
git log -L 40,48:src/api/list.py                            # when was the line introduced, and why
```

## Concurrency

| Probe | Command / method |
|---|---|
| Go data race | `go test -race -run TestX -count=50 ./pkg/...` |
| Rust interleavings | `loom` model test, or `cargo +nightly miri test` for UB under concurrency |
| C/C++ races | build with `-fsanitize=thread`, run the stress test |
| Java memory model | jcstress test for the specific publication pattern |
| Stress loop | `for i in $(seq 1 200); do <cmd> || echo FAIL $i; done \| grep -c FAIL` |
| Happens-before reasoning | list every shared variable, the lock or atomic protecting it, and the publication point |

A race claim survives on a sanitizer report naming both accesses, or on a deterministic
interleaving test. "Could race" without a shared mutable location identified is E0.

## Memory safety and undefined behaviour

- `-fsanitize=address,undefined -fno-omit-frame-pointer` (C/C++), run the repro.
- `valgrind --error-exitcode=1 ./repro` where sanitizers are unavailable.
- `cargo +nightly miri test` for Rust `unsafe` blocks.
- Check the documented safety contract of every `unsafe` call in the path.

## Numerics

| Probe | Example |
|---|---|
| Catastrophic cancellation | `(1 + 1e-16) - 1` in float64 is 0 |
| Equality on floats | compare with a tolerance appropriate to the condition number |
| Overflow and wraparound | int32 sums of large counters; Rust release builds wrap unless checked |
| NaN and infinity propagation | NaN != NaN breaks sorting, dedup and min/max |
| Integer division and modulo of negatives | language-specific sign rules (Python floors, C truncates) |
| High-precision reference | `python3 -c "from fractions import Fraction; ..."` or mpmath to compare |

## Performance

Checklist for any speedup or regression claim:
- [ ] Release/optimized build, same machine, same input size and data distribution.
- [ ] Warmup runs; at least 10-30 measured runs; report mean +/- stddev or a confidence interval.
- [ ] Noise floor: run A vs A first; a difference inside A-vs-A spread is no difference.
- [ ] Hot-path share from a profile; Amdahl bound `1 / ((1 - f) + f / s)` caps any end-to-end claim.
- [ ] Caches: cold vs warm stated; file system cache dropped or warmed consistently.
- [ ] Throughput vs latency: a mean improvement can hide a p99 regression.

```bash
hyperfine --warmup 5 --runs 30 'old/bin --input data.json' 'new/bin --input data.json'
cargo bench --bench parse -- --save-baseline before    # criterion, then --baseline before
go test -bench=BenchmarkParse -benchmem -count=10 ./... | tee new.txt && benchstat old.txt new.txt
python3 -m pyperf timeit -s "import m" "m.f(data)"
```

## Security findings

Trace template: source (request param, header, cookie, file, env, deserialized object, message
queue) -> each hop file:line -> sink (SQL, shell, file path, template, eval, redirect, outbound URL,
deserializer). At each hop record any sanitizer, encoder, type constraint or authorization check.

| Claimed class | Refuting evidence to look for |
|---|---|
| SQL injection | parameterized query or ORM binding at the sink; identifier allow-list for ORDER BY |
| Command injection | argument vector without shell; fixed command with validated args |
| Path traversal | canonicalize-then-prefix-check; `secure_filename`-style normalization; chroot or fixed directory handle |
| XSS | auto-escaping template engine with no raw/unsafe filter on the path; CSP |
| SSRF | allow-listed hosts resolved and checked after DNS resolution; no redirects followed |
| AuthZ bypass | middleware or decorator enforcing ownership before the handler |
| Secrets exposure | value is a placeholder, test fixture, or public identifier |

Grep starters: `grep -rnE "execute\(|raw\(|subprocess|os\.system|shell=True|eval\(|pickle\.loads|innerHTML|dangerouslySetInnerHTML|send_file|open\(" <paths>`.
Stop at demonstrating reachability with a local test. Never produce or run a working exploit against
a real system.

## Dependency and CVE claims

- Read the advisory (GHSA or OSV) affected ranges; compare with the lockfile version, not the manifest range.
- Check whether the vulnerable function is reachable from this code (Grep for the API).
- Tools: `pip-audit`, `npm audit --omit=dev`, `cargo audit`, `govulncheck ./...` (govulncheck also
  reports reachability).

## Factual and external claims

| Probe | Method |
|---|---|
| Primary source | spec, official docs, release notes, paper, dataset; `mcp__jina__read_url`, `mcp__exa__web_fetch_exa` |
| Version and date | docs for the version in question; changelog entry introducing the behaviour |
| Citation laundering | follow citations to the origin; three articles citing one blog are one source |
| Context | the quote's surrounding paragraph; conditions and caveats |
| Retractions and errata | journal page, arXiv later versions |
| Library APIs | `mcp__context7__resolve-library-id` then `mcp__context7__query-docs` at the right version |

## Math and proof steps

- Check small cases exhaustively (n = 0..50) with a script; one counterexample refutes.
- Symbolic identity: `python3 -c "import sympy as s; x=s.symbols('x'); print(s.simplify(lhs - rhs))"`.
- Quantifier order (for all x exists y vs exists y for all x); hidden division by zero; domain edges.
- Induction: base case, and whether the step uses the hypothesis for the right n.
- Inequalities: direction under negation or multiplication by a possibly negative factor.
- Dimensional consistency for physics-style derivations.
- Re-derive independently before reading the claimant's derivation; compare only conclusions.

## Experimental and ML results

- Seeds: at least 3-5 seeds; report mean and spread; a gain inside seed variance is noise.
- Leakage: train/test overlap, temporal leakage, preprocessing fitted on the full dataset.
- Baseline parity: equal tuning budget for the baseline.
- Metric definition: same split, same metric implementation, same averaging (micro vs macro).
- Benchmark contamination for LLM evaluations: test items present in training or prompt data.
- Selection: number of configurations tried versus reported.

## Statistical claims

Base rates, sample size and power, multiple comparisons (Bonferroni or FDR), Simpson's paradox
(stratify), regression to the mean, survivorship, confounders, causal language on observational data.

## Capability and plan claims

- "Tool X supports Y": docs at the deployed version plus a quick local probe when safe.
- "Step takes N hours": decompose and re-estimate independently; compare.
- "API limit is fine": find the documented rate limit and compare with the planned call rate.
- "Agent Z can do this": check its frontmatter (tools, mcpServers, skills) under `.claude/agents/`.

## Minimal repro skeletons

```python
# <out_dir>/<stamp>-<slug>/test_claim.py  -- run: pytest -q <out_dir>/<stamp>-<slug>/test_claim.py
import sys; sys.path.insert(0, "<repo>/src")
from api.list import paginate

def test_claim():
    items = list(range(10))
    for limit in range(0, 12):
        page, has_more = paginate(items, start=0, limit=limit)
        assert len(page) <= limit
        assert has_more == (len(items) > limit)
```

```bash
# shell repro with captured evidence
set -euo pipefail
out="<out_dir>/<stamp>-<slug>"; mkdir -p "$out"
rc=0; <command under test> >"$out/repro.stdout" 2>"$out/repro.stderr" || rc=$?   # -e must not abort
echo "exit=$rc" >>"$out/repro.stdout"
tail -n 20 "$out/repro.stdout" "$out/repro.stderr"
```
