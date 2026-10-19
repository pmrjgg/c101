# Templates: READMEs, MADR, migration guide, changelog

Fill-in templates for `docs-and-adr-writing`. Replace every `{...}`; delete rows that do not apply
rather than writing "N/A".

## Library README

````markdown
# {name}

{One sentence: what it does and for whom.}

## Install

```bash
{pip install name | npm install name | cargo add name | go get example.com/name}
```

## Quickstart

```{language}
{<= 10 lines, runnable as-is, executed in CI, shows the output it produces}
```

## Documentation

- API reference: {link to generated docs}
- Guides: {link}
- Changelog: [CHANGELOG.md](CHANGELOG.md)

## Supported versions

| {Runtime} | Supported |
|---|---|
| {3.13, 3.14, 3.15} | yes |

## License

{SPDX id}, see [LICENSE](LICENSE).
````

## Service README

````markdown
# {service-name}

Owns {data / endpoints / jobs}. Called by {consumers}. On-call: {team, channel}.

## Run locally

```bash
{one command after clone, e.g. docker compose up --build}
```

## Configuration

| Name | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | none | yes | PostgreSQL DSN |
| `HTTP_PORT` | `8080` | no | Listen port |

## Dependencies

| Dependency | Purpose | Failure behaviour |
|---|---|---|
| {PostgreSQL 16} | {orders store} | {readiness fails} |

## Operations

- Health: `GET /healthz` (liveness), `GET /readyz` (readiness)
- Metrics: {endpoint, dashboard link}
- SLOs: {availability, latency targets}
- Runbook: {link}
````

## CLI README

````markdown
# {tool}

{One sentence.}

## Install

```bash
{command}
```

## Usage

```text
{tool} [OPTIONS] <INPUT>...
```

## Examples

```bash
{tool} convert data.csv --to parquet        # writes data.parquet
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | invalid input |
| 2 | usage error |

## Configuration

{Config file locations in precedence order; environment variables.}
````

## MADR 4.0 decision record (worked example from the skill)

File: `docs/adr/0003-use-full-jitter-backoff.md`. Optional MADR sections ("Pros and Cons of the
Options") may be dropped for small decisions; "Confirmation" is worth keeping.

```markdown
---
status: accepted
date: 2026-10-19
decision-makers: retrykit maintainers
---

# Use full-jitter exponential backoff in `retry()`

## Context and Problem Statement

`retry()` slept a fixed 1 s between attempts. When a shared dependency recovers, every client that
failed together retries together, so the dependency sees synchronized spikes. Which backoff should
`retry()` use by default?

## Decision Drivers

* Spread retries of many independent clients over time (no thundering herd)
* Bounded worst-case wait so callers can budget deadlines
* Deterministic tests (injectable randomness)

## Considered Options

* Fixed delay (status quo)
* Exponential backoff without jitter
* Full jitter: `random(0, min(cap, base * 2**attempt))`
* Decorrelated jitter: `min(cap, random(base, previous * 3))`

## Decision Outcome

Chosen option: "Full jitter", because it spreads retries uniformly over the window, needs no state
between attempts, and has a simple upper bound per attempt (`min(cap, base * 2**attempt)`).

### Consequences

* Good, because synchronized clients de-correlate after the first failure.
* Good, because the per-attempt bound makes deadline budgets easy to compute.
* Bad, because a single retry can happen almost immediately (delay close to 0).

### Confirmation

Doctests in `full_jitter_delay` pin the bound with an injected `rng`; the README quickstart runs in CI
via `pytest --markdown-docs`.

## More Information

Supersedes nothing. Revisit if users need a minimum delay (equal jitter) or server-provided
`Retry-After` handling.
```

Empty MADR skeleton:

```markdown
---
status: proposed
date: {YYYY-MM-DD}
decision-makers: {names or team}
---

# {Short title of solved problem and solution}

## Context and Problem Statement

{2-3 sentences; end with the question being decided.}

## Decision Drivers

* {driver}

## Considered Options

* {option 1}
* {option 2}

## Decision Outcome

Chosen option: "{option}", because {justification}.

### Consequences

* Good, because {...}
* Bad, because {...}

### Confirmation

{How compliance is checked: test, lint rule, review item.}

## Pros and Cons of the Options

### {option 1}

* Good, because {...}
* Bad, because {...}

## More Information

{Links, follow-ups, when to revisit.}
```

## Migration guide

````markdown
# Migrating from {name} {X} to {Y}

**Who is affected:** {users of A, B; not affected if ...}
**Effort:** {e.g. 10 minutes with the codemod; up to an hour for custom subclasses}

## Automated path

```bash
{codemod command, with --dry-run first}
```

## Breaking changes

### 1. {change, one per heading}

Why: {one sentence}

Before ({X}):

```{language}
{old code}
```

After ({Y}):

```{language}
{new code}
```

## Deprecations (still work in {Y}, removed in {Z})

| Old | New |
|---|---|

## Verify

```bash
{test command or check that proves the migration worked}
```
````

## Changelog (Keep a Changelog 1.1.0)

```markdown
# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-19

### Added

- `full_jitter_delay()` is public.

### Changed

- `retry()` waits with full-jitter exponential backoff (`random(0, min(20 s, 0.1 s * 2**attempt))`)
  instead of a fixed 1 s ([ADR 0003](docs/adr/0003-use-full-jitter-backoff.md)).

[Unreleased]: https://example.com/retrykit/compare/v0.3.0...HEAD
[0.3.0]: https://example.com/retrykit/compare/v0.2.0...v0.3.0
```

Changeset file equivalent (changesets-managed JS/TS monorepos), `.changeset/full-jitter-backoff.md`:

```markdown
---
"retrykit": minor
---

`retry()` now waits with full-jitter exponential backoff (`random(0, min(20 s, 0.1 s * 2**attempt))`)
instead of a fixed 1 s, and `full_jitter_delay()` is public. See docs/adr/0003-use-full-jitter-backoff.md.
```
