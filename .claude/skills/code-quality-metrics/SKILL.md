---
name: code-quality-metrics
description: "Measuring code quality with numbers that drive decisions: cyclomatic and cognitive complexity, duplication, coupling and cohesion (Ca, Ce, instability, abstractness, LCOM4), dependency-graph cycles, churn x complexity hotspots from git history, type coverage and lint baselines with ratchets; exact tool commands per language, a bundled hotspot script, and the prioritized refactor-list format. Load when assessing codebase health, choosing refactor targets, setting CI quality gates, or comparing a module before and after a refactor."
when_to_use: "Someone asks where the worst code is, what to refactor first, whether a refactor improved things, or which quality gates to enforce in CI."
---

# Code quality metrics

Metrics are triage, not verdicts. A number earns attention only when it is (a) extreme relative to the
rest of this codebase, (b) in code that changes often, and (c) linked to a cost: defects, slow changes,
or untestable logic. Every recommendation you make cites the numbers and the command that produced them.

## 1. Metric quick reference

| Metric | Measures | Computation | Function-level thresholds (green / amber / red) | Main tools |
|---|---|---|---|---|
| Cyclomatic complexity (CCN) | Independent (basis) paths; tests for basis-path coverage, an upper bound for branch coverage | decisions + 1 (if, loop, case, catch, `&&`, `\|\|`, ternary) | <= 10 / 11-20 / > 20 (> 50 untestable) | lizard, radon, gocyclo, PMD, ESLint `complexity` |
| Cognitive complexity | Effort to understand; penalizes nesting | +1 per flow break, + nesting level for nested structures | <= 15 / 16-25 / > 25 | SonarQube rules, complexipy, gocognit, `eslint-plugin-sonarjs`, clippy |
| Length | Size of a unit | NLOC (non-comment lines) | <= 60 / 61-120 / > 120 | lizard, scc |
| Parameters | Interface width | count | <= 4 / 5-6 / > 6 | lizard `-a` |
| Nesting depth | Indentation of logic | max block depth | <= 3 / 4 / > 4 | linters (`max-depth`, ruff PLR1702) |
| Duplication | Copy-paste debt | % duplicated tokens/lines | < 3% / 3-5% / > 5% of new code | jscpd, PMD CPD, Sonar |
| Efferent coupling Ce | What a module depends on | outgoing deps | relative; watch top 5% | dep graphs |
| Afferent coupling Ca | Who depends on it | incoming deps | relative | dep graphs |
| Instability I | Susceptibility to change | Ce / (Ca + Ce), 0 stable .. 1 unstable | dependencies should point toward lower I | derived |
| Abstractness A | Share of abstract types | abstract / total types | with I, distance D = \|A + I - 1\| ; D > 0.5 is a smell | derived |
| LCOM4 | Class cohesion | connected components of methods linked by shared fields or calls | 1 / 2 / >= 3 (split candidate) | custom, Sonar (some languages) |
| Cycles | Tangled modules | strongly connected components of size > 1 | 0 between packages | madge, dependency-cruiser, import-linter, ArchUnit, jdeps |
| Churn | Change frequency | commits (and lines) touching a file in a window | relative | git log |
| Hotspot score | Where complexity hurts | pct(churn) x pct(complexity) | top 10 files | scripts/hotspots.py |
| Type coverage | Static safety | typed expressions / total; `any` count | >= 95% TS; non-decreasing | type-coverage, mypy reports, pyright |
| Lint debt | Known violations | count per rule vs baseline | non-increasing (ratchet) | ESLint suppressions, ruff, golangci-lint |

Exact counting rules (cognitive complexity increments, LCOM variants, Martin metrics, Halstead, MI):
[Metric definitions](references/metric-definitions.md). Per-language commands:
[Tool commands](references/tool-commands.md).

Reading thresholds: absolute thresholds are for gating new code. For assessing existing code, rank
within the repo (percentiles) and report distributions (p50, p90, max), not means. A 400-case
`switch` in a generated lexer is fine; a 40-CCN function in billing edited weekly is not.

## 2. Assessment procedure

Write all raw outputs to `.stack/out/<agent>/<YYYYMMDD-HHMM>-metrics/` and keep commands in a
`commands.txt` there so the run can be repeated for the before/after comparison.

1. **Inventory and exclusions.**
   ```bash
   M=.stack/out/<agent>/$(date +%Y%m%d-%H%M)-metrics; mkdir -p "$M"   # never write into the target tree
   git ls-files | sed -n 's/.*\.\([A-Za-z0-9]*\)$/\1/p' | sort | uniq -c | sort -rn | head
   scc --by-file -s code --format csv > "$M/sizes.csv"   # or: tokei --sort code
   ```
   Exclude vendored, generated, minified, migrations, fixtures and snapshot files from every metric.
   List the exclusions in the report.
2. **Complexity per function.**
   ```bash
   lizard -l python -l javascript -l go -l rust -l java --csv -x "./vendor/*" -x "./node_modules/*" src/ > "$M/lizard.csv"
   lizard -C 15 -L 80 -a 6 -w src/                       # warnings only, thresholds applied
   ```
   Add cognitive complexity with the language tool (complexipy, gocognit, sonarjs, clippy).
3. **Duplication.**
   ```bash
   npx jscpd --min-tokens 70 --reporters console,json --output "$M/dup/" --ignore "**/node_modules/**,**/dist/**,**/*.test.*" src/
   ```
4. **Dependency graph and cycles** (language commands in the reference). Record cycle count and the
   members of each cycle; compute Ca, Ce, I per package.
5. **Churn and hotspots.**
   ```bash
   STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"   # run from inside the target repo
   python3 "$STACK/.claude/skills/code-quality-metrics/scripts/hotspots.py" --since 12.months --complexity-csv "$M/lizard.csv" --top 25
   git log --since=12.months --no-merges --format= --name-only | sort | uniq -c | sort -rn | head -30
   ```
6. **Types and lint.** Type coverage, `any`/`type: ignore`/`@SuppressWarnings` counts, lint counts per
   rule (section 6).
7. **Test safety net** for the top hotspots: line/branch coverage of those files (see the
   `testing-strategy` commands). Low coverage changes the plan: characterization tests come first.
8. **Synthesize** into the refactor list (section 5).

## 3. Hotspots: the highest-value analysis

Complexity alone over-reports stable legacy code nobody touches; churn alone over-reports config
files. Their product finds code that is both hard and constantly edited.

```
score(f) = pct_rank(commits(f)) x pct_rank(complexity(f))        in (0, 1]
defect signal(f) = fix_commits(f) / commits(f)                    subject has fix|fixes|fixed|bug|hotfix|regression|patch as a whole word
```

The bundled [hotspots.py](scripts/hotspots.py) computes this from git history (stdlib only). With
`--complexity-csv lizard.csv` it sums CCN per file and reports the worst function; without it, it uses
indentation complexity, a language-agnostic proxy.

Worked example (12-month window, 1,240 source files):

| File | Commits | pct | Sum CCN | pct | Score | Fix commits | Worst function |
|---|---|---|---|---|---|---|---|
| billing/invoice.py | 142 | 0.99 | 310 | 0.98 | 0.97 | 31 (22%) | `compute_totals` CCN 47, cognitive 88 |
| api/routes/orders.py | 96 | 0.97 | 145 | 0.90 | 0.87 | 9 (9%) | `create_order` CCN 21 |
| legacy/report_gen.py | 3 | 0.20 | 520 | 0.99 | 0.20 | 0 | `build` CCN 112 (stable; leave alone) |

`legacy/report_gen.py` is the most complex file but nearly unchanged: refactoring it buys little.
`billing/invoice.py` is the target: hot, complex, and one in five changes is a fix.

Change coupling (files that change together without a code dependency) is the next signal: it reveals
hidden coupling such as a schema duplicated in two services. Snippet in
[Tool commands](references/tool-commands.md#change-coupling).

## 4. Coupling and cohesion analysis

1. Build the package-level graph (edges = imports). Collapse to the level where ownership lives
   (packages, crates, modules), not files.
2. Find cycles: every strongly connected component with more than one node. Report members and the
   edges that, if removed, break the cycle (prefer edges from stable to unstable packages, which also
   violate the stable-dependencies principle).
3. Compute Ce, Ca, I per package. Flag edges where a package depends on a more unstable one
   (I(dep) > I(pkg)): changes flow upward into stable code.
4. For classes in hotspots, compute LCOM4. LCOM4 >= 2 means the class holds unrelated responsibilities;
   each connected component is a candidate class.
5. Fan-in hotspots (high Ca, high churn) are risky to change: any refactor there needs strong tests and
   possibly a compatibility layer.

## 5. Prioritized refactor list

Priority combines value, risk and cost:

```
priority = hotspot_score x (1 + defect_signal) x safety_factor / effort_points
effort_points: S = 1 (< 1 day), M = 3 (1-3 days), L = 8 (> 3 days)
safety_factor: 1.0 if branch coverage of the target >= 70%, 0.5 otherwise (tests must be written first; add their effort)
```

Template (the deliverable; rank by priority):

```markdown
| # | Target (file:function) | Evidence | Problem | Refactor | Effort | Risk | Expected delta | Safety net |
|---|---|---|---|---|---|---|---|---|
| 1 | billing/invoice.py:compute_totals (L120-310) | CCN 47, cognitive 88, 142 commits/12mo, 31 fixes, LCOM4 3 | Tax, discount and rounding rules interleaved in one function | Extract TaxPolicy and DiscountRules; replace flag params with a strategy; table-driven rounding | M | Medium: 14 callers | max fn CCN 47 -> <= 12; cognitive 88 -> <= 15 each | 42% branch -> write characterization tests first (S) |
| 2 | api/routes/orders.py:create_order | CCN 21, 96 commits, dup 38 lines with update_order | Validation duplicated between create and update | Extract a shared OrderValidator | S | Low | dup -38 lines; CCN 21 -> 9 | 81% branch |
```

Rules for the list:
- Evidence column cites measured numbers only; method and window stated in the report header.
- Each refactor names the technique (extract function, replace conditional with polymorphism, introduce
  parameter object, split class along LCOM components, break cycle by dependency inversion).
- Expected delta is a falsifiable prediction to check after the refactor.
- No more than 10 items; the rest go in an appendix file.

## 6. Quality gates and ratchets

Gate new and changed code strictly; ratchet existing debt down; never gate on a global absolute that
legacy code already fails.

| Gate | Scope | Rule | How |
|---|---|---|---|
| Function complexity | Changed functions | cognitive <= 15, CCN <= 15 | lizard `-w` on changed files; complexipy; gocognit `-over 15`; ESLint `sonarjs/cognitive-complexity` |
| Duplication | Changed files | <= 3% duplicated lines on new code | jscpd on the diff's files with `--threshold 3` |
| Cycles | Package graph | no new cycles | madge `--circular`, dependency-cruiser `no-circular`, import-linter contracts, ArchUnit `beFreeOfCycles()` |
| Lint debt | Repo | per-rule count <= baseline | ESLint bulk suppressions (`eslint --suppress-all`, v9.24+), golangci-lint `--new-from-rev=origin/main`, ruff counts file |
| Types | Repo | type coverage non-decreasing; no new `any` / `type: ignore` without reason | `type-coverage --at-least N`, `rg` counts |

Ratchet pattern (works with any linter that emits JSON):
```bash
ruff check --output-format json . | python3 -c 'import json,sys,collections
c = collections.Counter(d["code"] for d in json.load(sys.stdin))
print(json.dumps(dict(sorted(c.items())), indent=1))' > .quality/lint-counts.json.new
# CI: fail if any rule count in .new exceeds the committed .quality/lint-counts.json; commit decreases.
```

## 7. Before/after comparison

Re-run the exact commands from `commands.txt` on the new revision and report deltas:

```markdown
| Metric (scope: billing/) | Before (a1b2c3d) | After (e4f5a6b) | Delta |
|---|---|---|---|
| Max function CCN | 47 | 12 | -35 |
| Functions with cognitive > 15 | 6 | 1 | -5 |
| Duplicated lines | 212 (4.1%) | 64 (1.2%) | -148 |
| Package cycles | 1 (billing <-> pricing) | 0 | -1 |
| Branch coverage | 42% | 77% | +35 pts |
```

A refactor that improves metrics but changes behaviour is a failure: pair the table with the test
run (same suite, all green before and after).

## 8. Pitfalls

- Goodhart: when a metric becomes a gate, people split functions mechanically. Review the shape, not
  just the number (a 5-CCN function calling five 5-CCN helpers that share state did not get simpler).
- Generated code, test fixtures, and migrations inflate duplication and size; exclude them.
- Test code duplication is often intentional (readable, independent tests); report it separately.
- Tools disagree: lizard counts `&&`/`||`, some tools do not; switch counted per case vs once
  (`lizard -m`). Never compare numbers from different tools.
- Maintainability Index blends Halstead volume, CCN and LOC into one opaque number; do not lead with it.
- Coverage percentages from different instrumentations (line vs branch) are not comparable.
- Short git windows on a new repo exaggerate churn; use at least 6 months or the full history if shorter.

## Delegation

| Need | Agent |
|---|---|
| Executing a refactor from the list | language expert (`rust-expert`, `go-expert`, `java-expert`, `kotlin-expert`, `cpp-expert`, `haskell-expert`, `julia-expert`, `python-expert`, `typescript-expert`) or the caller |
| Characterization tests before refactoring | `tester` |
| Judging whether a hotspot also hides defects | `reviewer` |
| Performance side effects of a refactor | `code-optimizer` |
| Over ~8 packages or repos to measure | One `code-quality-analyst` per package as parallel Agent calls in one message (`run_in_background: false`), each writing raw CSV/JSON under `.stack/out/<agent>/`; merge the tables with a script (python/jq), not by reading them into context. Only the main thread (no `<stack-context>` header) runs the `fanout` workflow; otherwise return `Workflow name=fanout args={items:[...], agentType:"code-quality-analyst", promptTemplate:"..."}` as an Open doubt |

## Output

Result: top findings and the refactor list (<= 10 rows). Evidence: commands, tool versions, window,
exclusions. Files: the metrics directory with raw CSV/JSON and the full report.
