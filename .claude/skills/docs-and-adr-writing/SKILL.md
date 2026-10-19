---
name: docs-and-adr-writing
description: "Technical documentation that stays correct: Diataxis doc types, README templates (library, service, CLI), per-language docstring conventions with executable examples (doctest, cargo doc tests, Go examples), lightweight MADR decision records, changelogs driven by Conventional Commits, migration guides and docs CI (markdownlint, Vale, lychee, typos). Load when writing or reviewing READMEs, API docs, docstrings, ADRs, changelogs or migration guides."
when_to_use: "Editing README.md, docs/**, CHANGELOG.md, docs/adr/*.md, .changeset/*.md, mkdocs.yml, conf.py (Sphinx), docusaurus.config.*; adding or reviewing docstrings, TSDoc, rustdoc or Javadoc; a release needs notes or a migration guide; a doc build fails on broken links or warnings; a design choice needs a short decision record."
---

# Docs and ADR writing

Documentation is code: it has a type, a test and a reviewer. This skill covers writing it so it stays
true. One-way-door architecture decisions use the `architect` agent's full ADR procedure; this skill
covers the lightweight record for reversible choices. Commit-message hygiene in general sits with the
repo's git conventions; test design in `testing-strategy`.

Deep material: [templates: READMEs, MADR, migration guide, changelog](references/templates.md) |
[docs CI: configs and workflow](references/docs-ci.md)

## 1. Pick the doc type first (Diataxis)

| Type | Reader's question | Shape | Never contains |
|---|---|---|---|
| Tutorial | "Teach me" (newcomer) | one guaranteed success path, every step shows expected output | options, alternatives, edge cases |
| How-to guide | "How do I X?" (competent user) | goal in the title, prerequisites, numbered steps, result | conceptual background beyond one line |
| Reference | "What exactly is Y?" | complete, uniform, generated from code or specs where possible | tutorials, opinions |
| Explanation | "Why is it like this?" | context, trade-offs, history, alternatives | step-by-step instructions |

One page is one type; link between types instead of mixing them.

| Request | Write |
|---|---|
| "Document the new endpoint" | reference (generated from OpenAPI) + one how-to for the common task |
| "Onboarding for new contributors" | tutorial (clone, run, make a change, see it) |
| "How do I rotate the signing key?" | how-to |
| "Why do we use event sourcing here?" | explanation, or a decision record (section 5) |
| "List all config options" | reference table generated from the config schema |
| "Upgrade to v3" | migration guide (section 6): a how-to with before/after code |

## 2. README skeletons

| Library | Service | CLI |
|---|---|---|
| One-line purpose | What it owns (data, endpoints, jobs) and who calls it | One-line purpose |
| Install (one command) | Run locally (one command after clone) | Install |
| Runnable quickstart, <= 10 lines, executed in CI | Configuration table: name, default, description, required | Synopsis: `tool [OPTIONS] <ARGS>` |
| Link to API reference | Dependencies (DBs, queues, other services) | Examples for the 3-5 common tasks, with output |
| Supported versions (runtime, OS) | Health endpoints (`/healthz`, `/readyz`), metrics, dashboards | Exit codes table |
| License, contributing, changelog links | Runbook link, on-call owner, SLOs | Config files and env vars |

Full fill-in templates in [the templates reference](references/templates.md). The README's first
screen answers "what is this, should I care, how do I try it"; everything else is a link.

## 3. Docstring conventions

Document the contract, not the implementation: preconditions, postconditions, units and ranges, errors,
thread-safety, ownership/lifetimes, complexity when not obvious, side effects.

| Language | Convention | Sections / tags | Checker |
|---|---|---|---|
| Python | Google (`Args:`, `Returns:`, `Raises:`, `Yields:`, `Examples:`) or NumPy (underlined `Parameters`) | units and ranges in `Args`, every raised exception in `Raises` | `pydoclint --style=google` (or `[tool.pydoclint]` in `pyproject.toml`), `interrogate -v --fail-under 90`, ruff `D` rules with `pydocstyle.convention = "google"` |
| TypeScript | TSDoc | `@param`, `@returns`, `@throws`, `@example`, `@remarks`, `@deprecated` | TypeDoc (warnings as errors), `eslint-plugin-tsdoc` |
| Rust | rustdoc Markdown | `# Examples`, `# Errors`, `# Panics`, `# Safety` (mandatory on `unsafe fn`) | `#![warn(missing_docs)]`, clippy `missing_errors_doc`, `missing_panics_doc` (pedantic), `missing_safety_doc` |
| Go | doc comment starts with the identifier name: `// Retry calls fn until ...` | `Deprecated:` paragraph; examples as `ExampleXxx` functions | `go vet`, `staticcheck`, `go doc`, pkgsite |
| Java | Javadoc | `@param`, `@return`, `@throws`, `{@code}`, `@since`, `@deprecated` | `javadoc -Xdoclint:all` |

```python
def full_jitter_delay(attempt: int, base: float = 0.1, cap: float = 20.0,
                      rng: Callable[[], float] = random.random) -> float:
    """Return the sleep before retry number ``attempt`` (AWS "full jitter").

    Args:
        attempt: Zero-based retry number; must be >= 0.
        base: First window size in seconds; must be > 0.
        cap: Upper bound of the window in seconds; must be >= ``base``.
        rng: Source of uniform floats in ``[0, 1)``; inject a fake in tests.

    Returns:
        Delay in seconds, ``0 <= delay < min(cap, base * 2**attempt)``.

    Raises:
        ValueError: If ``attempt`` is negative or ``base``/``cap`` are invalid.

    Examples:
        >>> full_jitter_delay(3, base=0.1, cap=20.0, rng=lambda: 0.5)
        0.4
    """
```

## 4. Executable docs

Examples that are not executed rot. Run them in CI:

| Stack | How | Command |
|---|---|---|
| Python docstrings | doctest | `pytest --doctest-modules src/` |
| Python Markdown (README, guides) | `pytest-markdown-docs` runs fenced `python` blocks | `pytest --markdown-docs README.md docs/` |
| Python, plain doctest in `.md` | `>>>` sessions inside Markdown | `pytest --doctest-glob='*.md'` |
| Rust | doc tests in `///` comments; README included as crate docs (`#![doc = include_str!("../README.md")]`) | `cargo test --doc` (nextest skips doctests) |
| Go | `func ExampleRetry()` with a trailing `// Output:` comment (or `// Unordered output:`); no comment means compiled only | `go test ./...` |
| TypeScript | extract fenced `ts` blocks with a small script into a temp project | `tsc --noEmit` on the extracted files |
| Shell / CLI docs | run documented commands in CI and diff against the documented output | a script per page |

Rules: examples use public APIs only, show output, avoid network and clocks (inject `rng`, `sleep`,
`now`), and are short enough to read in the rendered page.

## 5. Decision records (MADR 4.0)

Use for two-way-door choices (reversible at moderate cost): a library, a backoff algorithm, a naming
scheme, a CI tool. One-way doors (data model, storage engine, service boundaries, public API shape)
go to the `architect` agent, which writes the full ADR with candidates, scoring and fitness functions.

| Item | Rule |
|---|---|
| Location | `docs/adr/NNNN-kebab-title.md`, numbered sequentially, never renumbered |
| Front matter | `status`, `date`, `decision-makers` (optional `consulted`, `informed`) |
| Sections | Context and Problem Statement; Decision Drivers; Considered Options; Decision Outcome (with Consequences and Confirmation); optional Pros and Cons of the Options; More Information |
| Status flow | `proposed` -> `accepted` (or `rejected`) -> `deprecated` / `superseded by ADR-NNNN`; old records stay, edited only to set status |
| Length | one screen to two pages; if it needs more, it is probably a one-way door |
| Confirmation | how compliance is checked: a test, a lint rule, an architecture test, a review checklist item |

Write it when the decision is made (in the same PR as the change), not afterwards from memory.

## 6. Changelogs, commits and migration guides

| Piece | Standard | Rule |
|---|---|---|
| Changelog | Keep a Changelog 1.1.0 | `## [Unreleased]` on top; sections Added, Changed, Deprecated, Removed, Fixed, Security; written for users, not a commit dump |
| Commits | Conventional Commits 1.0.0 | `feat:` (minor), `fix:` (patch), `feat!:` or a `BREAKING CHANGE:` footer (major); `docs:`, `refactor:`, `chore:` do not release |
| Release automation | release-please (from commits), changesets (from `.changeset/*.md` files written in the PR), git-cliff (`git cliff -o CHANGELOG.md`, `--bump`) | pick one per repo; changesets suits JS/TS monorepos, release-please and git-cliff work for any language |

Every breaking change ships a migration guide (template in the references): what changed and why,
who is affected, an automated path (codemod) if any, then before/after code for each change, and how
to verify. Link it from the changelog entry and the release notes.

## 7. Style rules

- Task-first headings: "Rotate the signing key", not "Key management".
- Numbered steps for procedures; after a step that produces output, show the expected output.
- Exact versions and copy-pasteable commands; no `<placeholders>` without saying where the value
  comes from; no prompts (`$`) inside copyable blocks.
- Define a term once, then use exactly that term (no synonyms for the same thing).
- No "simply", "just", "obviously", "easy": they insult the reader who is stuck.
- Second person, present tense, active voice: "The command creates", "you run".
- Tables for options and comparisons; prose for reasoning.
- Diagrams as code (Mermaid in Markdown, rendered by GitHub and most doc generators) under version
  control; no screenshots of text or terminals.
- Dates on facts that expire: "Last verified 2026-10-19 against v3.2".

## 8. Docs CI

| Check | Tool | PR (fast) | Scheduled (nightly/weekly) |
|---|---|---|---|
| Markdown lint | `markdownlint-cli2 "**/*.md"` with `.markdownlint-cli2.jsonc` | yes | |
| Prose style | `vale sync` once, then `vale docs/ README.md` with a project style and vocabulary | yes (errors only) | full report |
| Links | `lychee --offline --no-progress './**/*.md'` (local files and anchors only) | yes | `lychee --cache --max-cache-age 1d './**/*.md'` (external links) |
| Spelling | `typos` (config `_typos.toml`) or `codespell` | yes | |
| Build | Sphinx `sphinx-build -W --keep-going -b html docs docs/_build`; `mkdocs build --strict`; Docusaurus `onBrokenLinks: 'throw'` (the default) | yes | |
| Examples | section 4 commands | yes | |
| Docstrings | `pydoclint`, `interrogate`, rustdoc lints, TypeDoc warnings | yes | |

External link checks on every PR are flaky (rate limits, outages); run them on a schedule and open an
issue on failure. Workflow file in [the docs CI reference](references/docs-ci.md).

## 9. Keeping docs true

- Docs change in the same PR as the behaviour; reviewers check "docs updated?" as a checklist item
  (`code-review-checklist`).
- Generate reference from the source of truth: OpenAPI -> Redoc or Scalar; TypeDoc; rustdoc and
  docs.rs; pkgsite; Sphinx autodoc / mkdocstrings for Python; config tables from the config schema.
- Never document intended behaviour as current; mark planned features as planned, with an issue link.
- One canonical page per topic; others link to it (duplicated pages drift apart).
- Put "last verified" dates on facts about external systems (quotas, versions, URLs).

## 10. Pitfalls

- Quickstarts that do not run: missing import, renamed function, an install step that needs a flag.
- Docs describing intended behaviour rather than what the code does today.
- Duplicated pages that drift: two "configuration" pages with different defaults.
- Screenshots of text or terminals: unsearchable, unreadable in dark mode, never updated.
- Secrets, internal hostnames, real customer data or personal emails in examples; use
  `example.com`, `203.0.113.0/24` (TEST-NET-3) and obviously fake keys.
- Changelogs generated from commit subjects only ("fix stuff", "wip"); users need effects.
- ADRs written months later to justify a decision; record it when made.
- Docstrings that restate the signature ("Args: x: the x") instead of units, ranges and errors.
- Default markdownlint line length (80) failing every existing file: set `MD013` to the repo's wrap
  width once instead of disabling the linter.

## 11. Worked example: documenting a retry helper library (`retrykit`)

Change: `retry()` switches from a fixed 1 s sleep to full-jitter backoff; release 0.3.0.

1. **Docstrings**: `full_jitter_delay` and `retry` get Google-style docstrings with Args, Returns,
   Raises and doctested Examples (section 3). `pydoclint src` found a real defect on the first run:

   ```text
   src/retrykit/backoff.py
       50: DOC503: Function `retry` exceptions in the "Raises" section in the docstring do not match
       those in the function body. ... Raised exceptions in the body: ['AssertionError', 'RetryError', 'ValueError'].
   ```

   The body ended with an unreachable `raise AssertionError("unreachable")`; restructuring the loop to
   `raise RetryError(...) from last` after it removed the undocumented exception. Second run:
   "No violations"; `interrogate -v --fail-under 100 src` passes at 100 %.

2. **README quickstart**, executed by `pytest --markdown-docs`:

   ```python
   from retrykit import RetryError, retry

   attempts = []

   def fetch_price() -> int:
       attempts.append(1)
       if len(attempts) < 2:
           raise ConnectionError("connection reset")
       return 42

   assert retry(fetch_price, attempts=3, sleep=lambda s: None) == 42
   assert len(attempts) == 2
   ```

   `pyproject.toml`: `[tool.pytest.ini_options] addopts = "--doctest-modules --markdown-docs"`,
   `testpaths = ["src", "README.md"]`. Result: 3 passed (two docstring doctests, one README block).

3. **Decision record** `docs/adr/0003-use-full-jitter-backoff.md` (MADR, status `accepted`): options
   fixed delay, exponential without jitter, full jitter, decorrelated jitter; chosen full jitter
   because it de-correlates clients, needs no state and has a per-attempt bound
   `min(cap, base * 2**attempt)`; bad consequence: a retry can fire almost immediately; confirmation:
   the doctest that pins the bound with an injected `rng`. Full text in the templates reference.

4. **Changelog entry**, as a changeset (`.changeset/full-jitter-backoff.md`, front matter
   `"retrykit": minor`) in a changesets-managed monorepo, or as the `### Changed` entry under
   `## [Unreleased]` in `CHANGELOG.md` with a `feat:` commit for release-please or git-cliff:
   "`retry()` now waits with full-jitter exponential backoff (`random(0, min(20 s, 0.1 s * 2**attempt))`)
   instead of a fixed 1 s; `full_jitter_delay()` is public."

5. **Docs CI** on the PR: pytest (doctests + README), pydoclint, interrogate, `markdownlint-cli2`,
   `typos`, `vale`, `lychee --offline`. `markdownlint-cli2` flagged MD013 (line length 80) on the ADR
   and MD041 (no top-level heading) on the changeset file; the fix was a `.markdownlint-cli2.jsonc` with
   `MD013.line_length = 110` and `.changeset/**` in `ignores`, after which 0 issues; `typos` was clean.

Related: `zero-downtime-migrations`, `regex-engineering`, `resilience-patterns`,
`dependency-upgrades`, `code-review-checklist`, `testing-strategy`, hub `coding-general`.
