---
name: codemod-automation
description: "Large-scale automated code rewrites with syntax-aware tools (ast-grep, comby, semgrep autofix, OpenRewrite, jscodeshift/ts-morph, LibCST, gofmt -r/gopls/go fix, rust-analyzer SSR, Coccinelle, clang-tidy, ruff/eslint/clippy fixers): tool choice, rule writing and testing, dry runs, batched application, verification and reintroduction guards. Load when the same change must be applied at dozens to thousands of sites."
when_to_use: "API migrations, deprecation removals ('DeprecationWarning: datetime.datetime.utcnow() is deprecated'), renames across packages or repos, JUnit 4 to 5, framework or JDK upgrades, logging/HTTP client swaps, more than ~30 identical edits, or a reviewer asking for the rule that produced a mechanical diff."
---

# Codemod automation

A codemod is a deterministic, re-runnable program that edits code. The deliverable is the rule plus
its tests plus the diff it produced, so the diff can be regenerated after every rebase.
Behaviour-preserving restructuring of a few sites by hand is `refactoring-playbook`; this skill
starts where hand edits stop scaling.

Verified versions (October 2026): ast-grep 0.51 (the short `sg` alias now prints a deprecation
warning; use `ast-grep`), ruff 0.17, LibCST 1.9. Check `<tool> --version` and `--help` before use;
flags move.

Deep material:
[per-tool command crib](references/tool-cribs.md) |
[ast-grep rule reference and the tested utcnow rules](references/ast-grep-rules.md)

## 1. When to automate

| Sites | Shape | Do |
|---|---|---|
| < ~10 | any | hand edit or LSP rename |
| ~10-30 | identical syntax | LSP rename / IDE structural replace, or a one-off `ast-grep run -r` with review |
| > ~30, or across repos | any repeatable shape | written, tested codemod (this procedure) |
| any count | needs type info to decide (overloads, which `get` method) | type-aware tool: OpenRewrite, ts-morph, LibCST with metadata, gopls, clang-tidy |
| tail that no rule covers | irregular | manual or LLM-assisted, each hunk reviewed (section 8) |

Never `sed`/`perl -pi` over source except for a unique literal token (a version string, a
UUID-like identifier). Regex rewrites hit strings, comments and unrelated names, and miss
multi-line call forms, keyword arguments and different whitespace.

## 2. Tool choice

| Tool | Languages | Strength | Typical use |
|---|---|---|---|
| ast-grep | ~25 tree-sitter languages | code-shaped patterns with `$VAR` / `$$$ARGS`, YAML rules with `inside`/`has`/`not`, `fix`, test runner | default for syntax-level rewrites, CI lint rules |
| comby | any delimiter-balanced language | `:[hole]` templates, balanced brackets, no grammar needed | config files, templates, languages without good parsers |
| semgrep (`--autofix`) | ~30 languages | rule `fix:` / `fix-regex:`, taint and security rule ecosystem | when the team already ships semgrep rules |
| OpenRewrite | Java, Kotlin, Groovy, Gradle, Maven, YAML, XML | type-attributed LST, large recipe catalogue | Spring Boot upgrades, JUnit 4 -> 5, JDK upgrades (`UpgradeToJava21`) |
| jscodeshift | JS/TS (babel, ts, tsx parsers) | jQuery-like AST collections, recast keeps formatting | React and library API migrations |
| ts-morph | TypeScript | full type checker access, `addImportDeclaration`, `organizeImports` | rewrites that depend on types or symbol resolution |
| LibCST | Python | concrete syntax tree (keeps comments/format), matchers, `AddImportsVisitor`, scope metadata | Python API migrations needing import management |
| `gofmt -r` | Go | expression-level rewrite rules | small pattern swaps |
| `gopls rename`, `go fix` | Go | type-correct rename; `go fix` modernizers (rewritten in Go 1.26) and `//go:fix inline` | renames, modernizing to newer Go, migrating to inlined replacements |
| rust-analyzer `ssr` | Rust | type-aware structural search-replace (`$a.foo($b) ==>> bar($a, $b)`) | method/function migrations |
| Coccinelle (`spatch`) | C | semantic patches (SmPL) over control flow | kernel-style API migrations |
| clang-tidy `--fix` | C/C++ | `modernize-*`, `readability-*` checks with fixes, needs `compile_commands.json` | C++ modernization |
| linter fixers | per language | `ruff check --fix [--unsafe-fixes]`, `eslint --fix`, `pyupgrade --py311-plus`, `cargo clippy --fix` | when an existing rule already covers the change |

Pick the first linter fixer that already implements the change; then the syntax tool for the
language; go type-aware only when syntax cannot decide. Commands per tool:
[per-tool command crib](references/tool-cribs.md).

## 3. Procedure

1. **Inventory with counts and variants.**
   ```bash
   rg -c 'utcnow' --type py | awk -F: '{s+=$2} END {print s}'            # rough upper bound
   ast-grep run -l python -p '$C.utcnow()' --json=compact . | jq length    # syntactic matches
   ast-grep run -l python -p '$C.utcnow()' --json=compact . \
     | jq -r '.[].metaVariables.single.C.text' | sort | uniq -c            # variants by receiver
   ```
   Categorize: canonical form, aliases, keyword arguments, multi-line, references without calls,
   generated/vendored files. Each category becomes a rule, a test case or a manual item.
2. **Write the rule against 3-5 real samples** copied from the inventory, not invented ones.
3. **Test it with fixtures**: `valid` (must not match) and `invalid` (must match, with expected
   output snapshot). ast-grep: `ast-grep test`; OpenRewrite: `RewriteTest`; LibCST: `CodemodTest`;
   jscodeshift: `defineTest` / `applyTransform`.
4. **Dry run**: diff plus diffstat, no writes.
   ```bash
   ast-grep scan -c tools/codemods/sgconfig.yml src/ | head -100        # diagnostics with inline diffs
   git diff --stat                                                        # after an apply: files and lines
   ```
5. **Apply in batches** (one package/directory per batch): `ast-grep scan -c ... -U src/billing`.
6. **Per batch**: formatter, import fixer, compiler/type checker, tests for that package. Commit
   the mechanical batch only when green.
7. **List the residue**: rerun the inventory; every remaining site is either a new rule case or a
   manual item with file:line in the PR.

## 4. ast-grep crib

```bash
ast-grep run -p 'foo($A, $B)' -r 'bar($B, $A)' -l ts src/       # preview (diff), no writes
ast-grep run -p 'foo($A, $B)' -r 'bar($B, $A)' -l ts -i src/    # interactive accept/reject per hunk
ast-grep run -p 'foo($A, $B)' -r 'bar($B, $A)' -l ts -U src/    # apply all
ast-grep run -p 'console.log($$$ARGS)' -l ts --json=compact src/ | jq length
ast-grep run -p 'foo($A)' -l py --debug-query=ast                # see how the pattern parses
ast-grep scan -r tools/codemods/rules/x.yml src/                 # one rule file
ast-grep scan -c tools/codemods/sgconfig.yml --filter '^utcnow' -U src/   # rules by id regex, apply
ast-grep new project                                             # sgconfig.yml, rules/, rule-tests/
ast-grep new rule my-rule -l python -y                           # rule skeleton in the first ruleDir
ast-grep test -c tools/codemods/sgconfig.yml                     # run rule tests; -U updates snapshots
```

Metavariables: `$A` one node, `$$$ARGS` zero or more nodes, `$_` non-capturing, same name twice
must match identical text. JSON output line numbers are 0-based.

Rule skeleton:

```yaml
id: no-foo-swap
language: typescript
severity: error            # error makes `ast-grep scan` exit non-zero (CI guard)
message: use bar(b, a) instead of foo(a, b)
rule:
  pattern: foo($A, $B)
  not:
    inside:                # leave the legacy definition itself alone
      kind: function_declaration
      has: { field: name, regex: '^foo$' }
      stopBy: end
constraints:
  A: { regex: '^[a-z]' }
fix: bar($B, $A)
```

Commit rules and tests under `tools/codemods/` (`sgconfig.yml`, `rules/`, `rule-tests/`) so
downstream consumers of a library can run the same migration. Composite rules (`all`, `any`, `not`),
relational rules (`inside`, `has`, `follows`, `precedes`, `stopBy`), `transform` and `utils`:
[ast-grep rule reference](references/ast-grep-rules.md).

## 5. Import and symbol hygiene

A rewrite that introduces a name must also import it; one that removes the last use must drop the
import; neither may shadow an existing name.

| Tool | Add / remove imports | Then |
|---|---|---|
| LibCST | `AddImportsVisitor.add_needed_import(self.context, "datetime", "UTC")`, `RemoveImportsVisitor.remove_unused_import(self.context, "datetime", "timezone")` | merges into an existing `from datetime import ...` |
| ts-morph | `sf.addImportDeclaration({ moduleSpecifier: "x", namedImports: ["y"] })`, `sf.organizeImports()` | `await project.save()` |
| jscodeshift | insert an `ImportDeclaration` node at the top of `program.body` | `eslint --fix` with an import-sorting rule |
| ast-grep | a second rule that adds an import statement next to the existing one (tested example in the reference) | `ruff check --select I,F401 --fix`, `goimports -w`, `eslint --fix` |
| OpenRewrite | `maybeAddImport` / `maybeRemoveImport` in the visitor | recipe handles it |

Checks after the rewrite: name collisions (a local variable or parameter already named `UTC`,
`bar`), star imports hiding the new name, `TYPE_CHECKING`-only imports, annotations and stubs still
valid (`mypy`/`pyright`/`tsc --noEmit`), and `__all__`/re-exports updated.

## 6. Scaling out

- Shard by package or directory, never by arbitrary file lists: a package must compile as a unit.
- Parallel workers: one `swarm-run` brief per shard carrying the tested rule file path and the
  per-batch verification commands; workers must not edit the rule (changes go back through tests).
- One mechanical commit per shard (`refactor(codemod): utcnow -> now(UTC) in billing`), plus a
  separate commit for manual fixes, so reviewers can skim the mechanical part and read the manual part.
- Exclude generated, vendored and fixture files: `.gitignore`d paths are skipped by ast-grep by
  default; add `ignores:` globs to each rule or pass `--globs '!**/generated/**'`.
- Long-lived branches: keep the rule, not the diff; rebase by dropping the mechanical commits and
  re-running the rule on the new base.

## 7. Verification

| Check | How | Pass |
|---|---|---|
| compiler / type checker (primary oracle) | `mypy`, `pyright`, `tsc --noEmit`, `go build ./...`, `cargo check`, `mvn -q compile` | clean |
| tests | package tests per batch, full suite once at the end | green |
| diffstat sanity | `git diff --stat origin/main...HEAD \| tail -1` | file count matches the inventory's file count; no unexpected directories |
| spot review | 10 random hunks: `git diff -U2 origin/main...HEAD \| grep -c '^@@'` then sample | all correct |
| zero old-pattern occurrences | rerun inventory | 0, or each remaining site listed in the PR |
| reintroduction guard | enable the lint rule or `ast-grep scan` / semgrep rule in CI with severity error | CI fails on a new occurrence |
| idempotence | run the codemod again | no changes |

## 8. LLM-assisted edits: residual tail only

Deterministic rules for the bulk keep the diff reproducible, reviewable as a rule, and re-runnable
after rebases. Use an LLM (or manual edits) only for the residue the rules cannot express: each
such hunk is listed with file:line, reviewed individually, and lives in the manual-fix commit.
Never let an LLM rewrite the whole set: the diff becomes non-reproducible and every hunk needs review.

## 9. Pitfalls

- Formatting churn: tools emit their own whitespace; run the project formatter on touched files
  only, in the same mechanical commit.
- Invisible call sites: macros, templates, reflection, `getattr`, dependency injection by name,
  string-built SQL/HTML, dynamic dispatch. Syntax tools cannot see them; grep for the bare name too.
- Edge variants: keyword arguments, spreads (`...args`), optional chaining (`a?.foo()`), aliased
  imports (`from datetime import datetime as dt`), fully qualified calls, function references
  without a call (`default_factory=datetime.utcnow`), multi-line calls with comments inside.
- Partially migrated codebases mixing old and new API: decide whether the codemod must be
  idempotent over already-migrated code (it must) and test that case as `valid`.
- Rewriting generated code that the generator will overwrite: fix the generator or its template.
- Semantics that differ between old and new API beyond the call shape (naive vs aware datetimes,
  exceptions thrown, laziness, ordering): the compiler will not catch these; tests and a manual
  review of semantic edge cases must.
- `ast-grep` constraints apply after the whole rule matched: a `has` sub-rule binds the first
  candidate and does not backtrack to another one; put filters (`not`, `regex`) inside the sub-rule.

## 10. Worked example: `datetime.utcnow()` -> `datetime.now(UTC)`

Repo: 900 Python files, `requires-python = ">=3.12"` (`datetime.UTC` needs 3.11+; on older
targets use `timezone.utc`). `utcnow()` is deprecated since 3.12 and returns a naive datetime.

Inventory:

```bash
ruff check --select DTZ003 --statistics .
# 214	DTZ003	call-datetime-utcnow
ast-grep run -l python -p '$C.utcnow()' --json=compact . | jq -r '.[].metaVariables.single.C.text' | sort | uniq -c
#  187 datetime            (from datetime import datetime)
#   21 datetime.datetime   (import datetime)
#    6 dt                  (from datetime import datetime as dt)
rg -n 'utcnow\b[^(]' --type py | wc -l
#    4                     function references: default_factory=datetime.utcnow, default=datetime.utcnow
```

DTZ003 has no autofix (ruff reports it, `--fix` does nothing), hence a codemod. Three rules in
`tools/codemods/rules/utcnow.yml` (full tested file in
[the reference](references/ast-grep-rules.md)):

- `utcnow-qualified`: `datetime.datetime.utcnow()` -> `datetime.datetime.now(datetime.UTC)` (no new import).
- `utcnow-class`: `$CLS.utcnow()` -> `$CLS.now(UTC)` only inside a module where `$CLS` is bound by
  `from datetime import datetime` or `... datetime as $CLS`.
- `utcnow-add-utc-import`: in modules that still contain such a call and do not import `UTC`, append
  `from datetime import UTC` after the existing `from datetime import ...` statement.

Tests (`tools/codemods/rule-tests/`): `valid` cases cover `arrow.utcnow()` (not stdlib), already
migrated code and files that already import `UTC`; `invalid` cases cover the plain import, the `dt`
alias, and the mixed `import datetime` + `from datetime import datetime as dt` module.

```bash
ast-grep test -c tools/codemods/sgconfig.yml
# PASS utcnow-class  ....
# PASS utcnow-add-utc-import  ....
# test result: ok. 2 passed; 0 failed;
```

Six batches, one per top-level package (`api`, `billing`, `ingest`, `jobs`, `reports`, `shared`):

```bash
for pkg in api billing ingest jobs reports shared; do
  ast-grep scan -c tools/codemods/sgconfig.yml -U "src/$pkg" &&
  ruff check --select I,F401 --fix "src/$pkg" && ruff format "src/$pkg" &&
  mypy "src/$pkg" && pytest -q "tests/$pkg" &&
  git add -A "src/$pkg" && git commit -qm "refactor(codemod): utcnow -> now(UTC) in $pkg" || break
done
```

`ruff --select I` merges the appended import into `from datetime import UTC, datetime, timedelta`.
Five batches went green at once. `jobs` failed in pytest:
`TypeError: can't compare offset-naive and offset-aware datetimes` at 3 sites comparing the new
aware `now(UTC)` with naive datetimes read from a legacy table. Fixed by hand in a separate commit
(`fix: compare aware datetimes in job scheduler`, converting the legacy values with
`.replace(tzinfo=UTC)` after confirming they are stored as UTC), plus the 4 function references
rewritten to `default_factory=lambda: datetime.now(UTC)`.

Verification and guard:

```bash
ruff check --select DTZ003 --statistics .            # nothing reported
ast-grep scan -c tools/codemods/sgconfig.yml .       # 0 diagnostics
git diff --stat origin/main...HEAD | tail -1         # 131 files changed (inventory: 131 files)
ast-grep scan -c tools/codemods/sgconfig.yml -U .    # idempotent: no changes
```

`pyproject.toml`: `[tool.ruff.lint] extend-select = ["DTZ003"]`; CI also runs
`ast-grep scan -c tools/codemods/sgconfig.yml` because DTZ003 does not flag function references.
PR: 6 mechanical commits (rule + tests linked), 1 manual commit with the 3 + 4 sites listed.

Related: `refactoring-playbook` (hand refactors, parallel change), `git-advanced-workflows` (per-shard
commits, rebasing mechanical diffs), `testing-strategy`, `code-quality-metrics` (lint ratchets),
`api-contract-design` (deprecation policy), `swarm-execution`, hub `coding-general`.
