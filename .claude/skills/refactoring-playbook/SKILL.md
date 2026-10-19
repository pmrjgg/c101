---
name: refactoring-playbook
description: "Behaviour-preserving refactoring procedure: safety net first (characterization, approval and differential tests), a smell-to-refactoring decision table with micro-step mechanics, legacy-code seams, parallel change, branch by abstraction, strangler fig and Mikado graphs for large changes, and commit discipline. Load when restructuring code without changing behaviour or executing items from a code-quality refactor list."
when_to_use: "Executing a row of a code-quality-metrics refactor list; a function with CCN or cognitive complexity > 15 must be split; untested legacy code must change; replacing a module or implementation behind live traffic; a PR claims 'no behaviour change'; renaming or moving code across many files."
---

# Refactoring playbook

A refactoring changes structure and keeps observable behaviour: same outputs, same side effects,
same errors, same performance envelope. If any of those must change, it is a behaviour change and
goes in a separate commit with its own tests.

Scope split: `code-quality-metrics` measures and ranks targets (its prioritized refactor list);
this skill executes them. Test design depth (levels, property-based, mutation testing) is in
`testing-strategy`; this skill only names the tests a refactor needs.

Deep material:
[extended refactoring catalogue](references/refactoring-catalogue.md) |
[seams by language](references/seams-by-language.md)

## 1. Entry gate (do not start without it)

| Check | How | Pass |
|---|---|---|
| behaviour to preserve, one sentence | write it in the PR body | e.g. "compute_totals returns the same InvoiceTotals for every input" |
| all callers found | `rg -n '\bcompute_totals\b' --type py`, LSP "find references", plus dynamic uses (`getattr`, reflection, string dispatch, config files) | list in PR |
| public API surface | exported? semver library? serialized names? | stated |
| branch coverage of the target | `pytest --cov=billing --cov-branch --cov-report=term-missing`, `go test -coverprofile`, `cargo llvm-cov`, JaCoCo | >= ~70% or write characterization tests first |
| baseline suite green | full suite on the base commit | green, flaky tests listed |
| baseline metrics | rerun the `code-quality-metrics` commands, save output | stored for the before/after table |

## 2. Characterization and approval tests (the oracle)

Characterization tests pin what the code does now, bugs included. They are the oracle for the
whole refactor; do not "fix" a pinned oddity during the refactor (section 9).

| Ecosystem | Tool | Record / update |
|---|---|---|
| Python | syrupy (`snapshot` fixture) | `pytest --snapshot-update` |
| Python | inline-snapshot (`assert x == snapshot()`) | `pytest --inline-snapshot=create` / `=fix` |
| Rust | insta (`insta::assert_snapshot!`, `assert_debug_snapshot!`) | `cargo insta test --review` |
| TS/JS | Vitest / Jest `toMatchSnapshot()`, `toMatchInlineSnapshot()` | `vitest -u`, `jest -u` |
| Java / .NET | ApprovalTests (`Approvals.verify(...)`), Verify (.NET) | approve the `.received` file |
| Go | golden files under `testdata/` + a custom `flag.Bool("update", ...)` in the test package | `go test ./pkg -update` |
| any CLI / service | record request/response or argv/stdout pairs, diff later | script |

Input selection, in order of value:
1. Real inputs: production samples (anonymized), fixtures, replayed logs; stratify by the branches
   you are about to touch (customer type x country x coupon, error paths).
2. Boundary inputs from reading the code: empty, one, many, zero, negative, max, unicode, None.
3. Generated inputs when the space is large: property-based generators with a fixed seed.

Determinism checklist: sorted keys (`json.dumps(..., sort_keys=True)`), fixed clock (inject `now`),
seeded randomness, stable ordering of sets/dicts/maps, normalized floats (`Decimal` or fixed
precision), no absolute paths, no hostnames, no memory addresses in reprs.

```python
# tests/test_compute_totals_golden.py
import json, pathlib, pytest
from billing.invoice import compute_totals

CASES = sorted(pathlib.Path(__file__).parent.joinpath("golden/invoices").glob("*.json"))

@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_compute_totals_golden(path, snapshot):
    case = json.loads(path.read_text())
    result = compute_totals(**case["args"])
    assert json.dumps(result, sort_keys=True, default=str, indent=1) == snapshot
```

Record on the unchanged code (`pytest tests/test_compute_totals_golden.py --snapshot-update`),
commit the snapshots, rerun without the flag: must pass twice in a row (proves determinism).

## 3. Smell to refactoring

| Smell | Signal | Refactoring | Watch out |
|---|---|---|---|
| long function | > ~50 lines, CCN > 15 or cognitive > 15 | Extract Function; Split Phase when it does stage A then stage B | shared mutable locals: extract a phase object first |
| flag parameter | `def render(x, pdf: bool)`; callers pass literals | separate functions (`render_pdf`, `render_html`) or an enum | public API: keep old entry as a shim |
| repeated type switch | same `if kind == ...` / `match` on a type tag in >= 2 places | Replace Conditional with Polymorphism, or table-driven dispatch (dict of handlers/rates) | only when the switch is repeated; one switch is fine |
| long parameter list | > 4-5 params; same group passed through layers | Introduce Parameter Object (dataclass/record/struct) | keep argument order in the shim |
| feature envy | method reads another object's fields more than its own | Move Function to the data's owner | circular imports after the move |
| data clumps | same 3+ values travel together in >= 3 signatures | Extract Class / value object | equality and hashing semantics |
| low cohesion | LCOM4 >= 2 (disconnected method/field groups) | split the class along the components | callers that use both halves |
| duplication | same logic 3 times (rule of three) | Extract Function / shared module | two copies that will diverge: leave them |
| primitive obsession | strings/ints carrying meaning (`currency: str`, `cents: int`) | value type: `NewType`, dataclass, Rust newtype, TS branded type | serialization formats |
| deep nesting | > 3 levels of `if`/`for` | guard clauses (early return), extract loop body | early returns skipping cleanup: use `with`/`defer`/RAII |
| temporary field | field set only in some code paths | extract the path into its own object | |
| speculative generality | interface with one implementation, unused hooks | Inline Class / remove parameter | public extension points |

More rows and mechanics: [extended refactoring catalogue](references/refactoring-catalogue.md).

## 4. Mechanics (compile and test after every numbered step)

**Extract Function**
1. Copy the fragment into a new function; name it for what it does, not how.
2. Locals read by the fragment become parameters; locals written and used after become return values (more than two: return a small record, or Split Phase first).
3. Replace the fragment with the call. Run tests.
4. Search for other copies of the fragment; replace them only if the semantics are identical.

**Inline Function / Variable**
1. Check it is not polymorphic (overridden) and has no side effects that the call order matters for.
2. Replace each call with the body (LSP "inline" where available). Run tests after each site.
3. Delete the definition.

**Rename** (function, type, field, module)
1. Use the language server rename (gopls, rust-analyzer, pyright/pylance, tsserver, IntelliJ), never text replace: it skips strings, comments and same-named unrelated symbols correctly.
2. Search afterwards for string uses: `rg -n 'old_name'` in configs, templates, SQL, docs, reflection.
3. Published names (serialized fields, CLI flags, HTTP params, env vars): add an alias, deprecate, remove later (section 6, parallel change).

**Change Signature with a deprecated shim**
1. Add the new function with the new signature; implement it by moving the body.
2. Turn the old function into a one-line shim calling the new one, marked deprecated: Python `@warnings.deprecated("use x")` (3.13+) or `warnings.warn(..., DeprecationWarning, stacklevel=2)`; Java `@Deprecated(since = "2.3", forRemoval = true)`; Kotlin `@Deprecated("use x", ReplaceWith("x(a)"))`; Rust `#[deprecated(since = "0.4.0", note = "use x")]`; Go `// Deprecated: use X.`; TS `/** @deprecated use x */`.
3. Migrate callers in batches (more than ~30 sites: `codemod-automation`). Run tests per batch.
4. Delete the shim when no callers remain (libraries: next major version).

**Move Function / Module**
1. `git mv old.py new.py` in a commit of its own with no content change, so rename detection and `git log --follow` keep history.
2. Leave a re-export at the old location (`from new import *` with `__all__`, `pub use`, type alias) while callers migrate.
3. Fix imports (LSP organize imports, `ruff check --select I --fix`, `goimports`), run tests, remove the re-export last.

**Split Phase**
1. Identify the boundary: the first stage produces data the second consumes (parse then compute; compute then format).
2. Introduce an intermediate data structure (dataclass/record) holding everything stage 2 needs.
3. Extract stage 1 into a function returning that structure; stage 2 takes only the structure.
4. Keep side-effect order identical (logging, rounding points, I/O); check with the oracle.

## 5. Legacy seams (Feathers)

A seam is a place where behaviour can change without editing the code at that place. Create one,
get the code under test, then refactor.

| Technique | Use when | Shape |
|---|---|---|
| Sprout method / class | new logic must go into untested code | write the new logic in a new tested unit; call it from one line in the old code |
| Wrap method / class | new behaviour before/after existing behaviour | rename old `pay()` to `_pay_core()`, new `pay()` calls log + `_pay_core()` |
| Extract interface | class depends on a concrete heavy collaborator | interface with the used methods; production and fake implementations |
| Parameterize constructor | object creates its own dependencies | pass them in with the old default (`def __init__(self, repo=None): self.repo = repo or Repo()`) |
| Subclass and override (test only) | one method does I/O inside otherwise testable logic | subclass in the test, override the I/O method |
| Extract and override call | static/global call inside logic | move the call into a protected method, override in a test subclass |

Hidden dependencies to break by injection before changing logic: globals and singletons, the clock
(`now: Callable[[], datetime] = lambda: datetime.now(UTC)`), randomness (pass a seeded `Random`),
environment variables, file system, network, database, thread/sleep calls.
Per-language seam mechanics: [seams by language](references/seams-by-language.md).

## 6. Large refactors

| Pattern | Use for | Steps |
|---|---|---|
| Parallel change (expand / migrate / contract) | changing an interface used by many callers or services | expand: add new alongside old; migrate: callers move in batches, both work; contract: remove old once usage telemetry shows zero |
| Branch by abstraction | swapping an implementation (ORM, HTTP client, queue) | introduce an abstraction over the old implementation; move callers to it; build the new implementation behind it; switch (flag); delete the old one |
| Strangler fig | replacing a module or service at route/module level | route-level facade; move one route/use case at a time to the new code; old code shrinks to nothing |
| Feature flag at cutover | any switch that must be reversible in production | flag defaults to old path; dark-launch with differential comparison; ramp; remove flag and old path within a fixed deadline |
| Mikado method | a change whose prerequisites are unknown | see below |

Mikado graph:
1. Write the goal as the root node. Try it directly, time-boxed.
2. Note every failure (compile errors, failing tests) as prerequisite nodes under the goal.
3. Revert everything (`git restore . && git clean -fd` on the scratch attempt only, or `git stash -u`).
4. Pick a leaf; try it; if it breaks things, record its prerequisites and revert again.
5. When a leaf succeeds with a green suite, commit it and remove it from the graph.
6. Repeat until the goal itself is a leaf. Keep the graph in the PR description (Mermaid or indented list).

## 7. Commit discipline

- One refactoring step per commit, message `refactor: <technique> <target>`; behaviour changes in
  separate `fix:`/`feat:` commits, never mixed.
- Formatting-only changes get their own commit; add its full SHA to `.git-blame-ignore-revs`.
- `git mv` alone in a commit before editing a moved file.
- Every commit green: `git rebase -x '<fast test cmd>' origin/main` (procedure in `git-advanced-workflows`).
- PR body: "Behaviour change: none", followed by how it was proven (oracle, case count, differential
  result, mutation score on touched code, before/after metrics).
- More than ~30 mechanical edit sites, or the same edit across repos: hand off to `codemod-automation`.

## 8. Verification

| Evidence | Command / method | Pass |
|---|---|---|
| suite before and after | same command, same seed | identical pass set |
| golden master | snapshot tests without update flag | 0 changed snapshots |
| differential run | old code in a worktree (`git worktree add ../old <base-sha>`), same inputs, diff outputs | byte-identical, or every diff explained in the PR |
| mutation testing on touched code | mutmut / cosmic-ray / Stryker / PIT / cargo-mutants (method in `testing-strategy`) | surviving mutants in touched lines reviewed; score not lower than before |
| metrics | rerun `code-quality-metrics` commands; before/after table | the expected delta from the refactor list met |
| performance | benchmark when the hot path changed (new dynamic dispatch, allocations, copies) | within noise (`performance-optimization` statistics) |
| public API | `cargo semver-checks`, japicmp, `api-extractor`, `griffe check` | no unintended breaking change |

## 9. Pitfalls

- Refactoring and bug-fixing in one commit: the oracle can no longer tell them apart.
- Silently "fixing" behaviour the characterization tests pin: record it as an Open doubt with the
  case ID, fix it after the refactor in its own `fix:` commit with the snapshot update reviewed.
- Unintended public API changes in a library (renamed export, changed default, narrower type):
  semver major for users.
- Speculative generality: interfaces and hooks for a second implementation nobody asked for.
- Splitting a function to game CCN while the pieces share mutable state through `self` or globals:
  complexity moved, not removed. Pass data explicitly or Split Phase.
- Copy-then-delete moves lose blame and `--follow` history: `git mv` in its own commit.
- Changing rounding, ordering or error timing while "just extracting": the oracle must cover them.
- Snapshot updates accepted in bulk (`--snapshot-update` after a change): review each changed snapshot.
- Refactoring without the baseline suite green: you cannot tell what you broke.

## 10. Worked example: billing `compute_totals`

Refactor list row (from `code-quality-metrics`): `billing/invoice.py:compute_totals`, CCN 47,
cognitive 88, branch coverage 42%, 7 parameters, a type switch on `customer_type` x `country` for
tax, rounding interleaved with arithmetic. 14 callers (`rg -c '\bcompute_totals\(' --type py`).

Before (shape, abridged):

```python
def compute_totals(lines, customer_type, country, coupon, currency, rounding, include_tax):
    subtotal = Decimal("0"); tax = Decimal("0")
    for raw in lines:
        price = Decimal(str(raw["unit_price"])) * int(raw["qty"])
        if raw.get("discount_pct"):
            price = price * (1 - Decimal(str(raw["discount_pct"])) / 100)
        price = price.quantize(Decimal("0.01"), rounding=rounding)      # per-line rounding
        if include_tax:
            if customer_type == "B2B":
                if country == "DE": t = price * Decimal("0.19")
                elif country == "FR": t = price * Decimal("0.20")
                else: t = Decimal("0")                                     # reverse charge
            elif customer_type == "B2C":
                ...  # 30 more lines of nested country/category branches
        ...
```

Step 0, safety net (commit 1): 500 invoices sampled from last quarter's production data, anonymized,
stratified over customer type x 9 countries x coupon/no coupon x currency; stored as
`tests/golden/invoices/*.json`; golden test from section 2 recorded on the old code. Branch
coverage of `compute_totals`: 42% -> 93%. Suite run twice, stable.

Commits (each followed by `uv run pytest -q`; all green):

| # | Commit | Technique |
|---|---|---|
| 1 | `test: golden master over 500 recorded invoices` | characterization |
| 2 | `refactor: introduce InvoiceContext parameter object` | Introduce Parameter Object (7 params -> `lines, ctx`), old signature kept as shim |
| 3 | `refactor: parse raw lines into LineItem` | Split Phase, stage 1 |
| 4 | `refactor: compute line amounts from LineItem` | Split Phase, stage 2 (pure) |
| 5 | `refactor: isolate rounding in round_line` | Split Phase, stage 3 |
| 6 | `refactor: table-driven tax rates` | Replace Conditional with table dispatch |
| 7 | `refactor: extract apply_coupon` | Extract Function |
| 8 | `refactor: guard clauses in compute_totals` | Replace nested conditional with guard clauses |
| 9 | `refactor: migrate 14 callers, drop shim` | Change Signature (callers via LSP, < 30 sites) |

After (core):

```python
@dataclass(frozen=True)
class InvoiceContext:
    customer_type: CustomerType
    country: str
    coupon: Coupon | None
    currency: str
    rounding: str
    include_tax: bool

TAX_RATES: dict[tuple[CustomerType, str], Decimal] = {
    (CustomerType.B2B, "DE"): Decimal("0.19"),
    (CustomerType.B2B, "FR"): Decimal("0.20"),
    (CustomerType.B2C, "DE"): Decimal("0.19"),
    # ... 18 rows, generated from the old branches and checked against the golden master
}

def compute_totals(lines: list[dict], ctx: InvoiceContext) -> InvoiceTotals:
    items = [parse_line(raw) for raw in lines]                    # phase 1: parse
    amounts = [round_line(line_amount(i), ctx) for i in items]    # phase 2+3: compute, round per line
    subtotal = apply_coupon(sum(amounts, Decimal("0")), ctx.coupon)
    if not ctx.include_tax:
        return InvoiceTotals(subtotal=subtotal, tax=Decimal("0"), currency=ctx.currency)
    rate = TAX_RATES.get((ctx.customer_type, ctx.country), Decimal("0"))
    tax = sum((round_line(a * rate, ctx) for a in amounts), Decimal("0"))
    return InvoiceTotals(subtotal=subtotal, tax=tax, currency=ctx.currency)
```

What the oracle caught: the first version of commit 5 rounded once at the end instead of per line;
37 of 500 golden cases changed by 0.01. Reverted, rounding kept per line, all 500 identical. The
per-line rounding is arguably a bug; it is recorded as an Open doubt for the billing owner, not fixed here.

Verification table for the PR:

| Evidence | Result |
|---|---|
| golden master (500 invoices) | 500/500 byte-identical |
| differential run vs `../old` worktree at base SHA, same 500 inputs + 2,000 seeded generated inputs | 0 diffs |
| suite | 1,284 passed before and after |
| mutation testing on `billing/invoice.py` (mutmut) | 81% -> 88% killed; 0 survivors in tax table rows |
| `lizard -C 12 -w billing/invoice.py` | max CCN 47 -> 12 (no warnings) |
| cognitive complexity (complexipy) | 88 -> max 9 per function |
| p50 of `compute_totals` over the 500 cases | 41 us -> 39 us (within noise) |

Related: `code-quality-metrics` (targets and before/after metrics), `testing-strategy` (mutation,
property-based), `codemod-automation` (many-site edits), `git-advanced-workflows` (fixups, `rebase -x`),
`code-review-checklist`, `performance-optimization`, hub `coding-general`.
