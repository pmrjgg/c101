---
name: dependency-upgrades
description: "Keeping dependencies, runtimes and toolchains current safely: per-ecosystem outdated inventories, semver risk classification, one-major-at-a-time upgrades with official codemods, lockfile hygiene and frozen installs, Renovate/Dependabot policies and release-age cooldowns (pnpm 11 default), vulnerability triage by reachability and lockfile bisection of regressions. Load when bumping dependencies, runtimes or toolchains, or configuring update bots."
when_to_use: "Editing pyproject.toml/uv.lock, package.json/pnpm-lock.yaml/package-lock.json, Cargo.toml/Cargo.lock, go.mod/go.sum, pom.xml, build.gradle(.kts)/libs.versions.toml, renovate.json, .github/dependabot.yml; a Renovate or Dependabot PR to review; ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION, ERR_PNPM_IGNORED_BUILDS, ERESOLVE or resolver conflicts; a CVE alert; tests failing after a lockfile change; moving to a new Python, Node, Go, Rust or JDK version."
---

# Dependency upgrades

The workflow for moving dependencies forward without breaking production. `security-review` keeps the
SCA and new-dependency vetting depth; `debugging-method` keeps the general bisection mechanics; this
skill is the upgrade procedure. Verified on uv 0.13, npm 11.19, pnpm 11/12 docs, cargo 1.99 and
Go 1.27 (October 2026).

Deep material: [per-ecosystem command reference](references/ecosystem-commands.md) |
[update-bot and cooldown configurations](references/bot-configs.md)

## 1. Inventory: what is outdated

| Ecosystem | Outdated list | Notes |
|---|---|---|
| Python (uv) | `uv tree --outdated --depth 1` | `uv pip list --outdated` in non-project envs |
| Node (pnpm) | `pnpm outdated -r` | `-r` covers every workspace package |
| Node (npm) | `npm outdated` | `Wanted` = max in range, `Latest` = dist-tag latest |
| Rust | `cargo update --dry-run` (in-range), `cargo outdated -R` (plugin, majors too) | `cargo update --verbose` lists held-back versions |
| Go | `go list -m -u all` | `-json` for scripting; shows `[v1.2.3]` available updates |
| Maven | `mvn versions:display-dependency-updates` (+ `display-plugin-updates`) | versions-maven-plugin |
| Gradle | `./gradlew dependencyUpdates` | ben-manes versions plugin |

Record per package: current, wanted (in range), latest, release date, and whether it is direct or
transitive. Transitive-only changes are reviewed through the lockfile diff, not one by one.

## 2. Risk classification

| Change | Batch? | Gate |
|---|---|---|
| Patch and minor of mature (>= 1.0) packages | batch together, weekly | CI green |
| Dev-only tooling (linters, test runners, type stubs) | batch | CI green; automerge allowed |
| Major versions | one package per PR | release notes read, codemods run, full tests, canary |
| `0.x` minor (`0.4 -> 0.5`) | treat as major | semver allows breaking changes below 1.0 |
| Runtime / toolchain (Python, Node, Go, Rust, JDK) | own PR, CI matrix first | old and new versions both green before switching the default |
| Transitive-only bumps | with the lockfile refresh | review the lockfile diff for new packages and install scripts |

Runtime status, October 2026: Python 3.15.0 was released in October 2026 (PEP 790 target 1 October; uv
already ships it); Node 26 is scheduled to enter Active LTS at the end of October 2026, and the release
working group has announced one major release per year starting with Node 27 (check the nodejs/Release
schedule); Go pins via the `go` (minimum language version) and `toolchain` (preferred toolchain) lines
in `go.mod`, with `GOTOOLCHAIN=local` to forbid auto-download; Rust declares MSRV with `rust-version`
in `Cargo.toml` (the MSRV-aware resolver v3 is the default with edition 2024). Raising a library's
minimum runtime is a breaking change for its users.

## 3. Major-upgrade procedure

1. **Read the migration guide and changelog** from the current to the target version (use
   context7 docs or the `quick-researcher` agent for long histories). List removed APIs, changed
   defaults (timeouts, serialization, TLS, strictness) and new minimum runtimes.
2. **Make the current version warning-free**: turn deprecations into errors and fix them first.

   | Stack | Command |
   |---|---|
   | Python | `pytest -W error::DeprecationWarning` (or `filterwarnings = ["error::DeprecationWarning"]` in pytest config) |
   | Node | `node --trace-deprecation` to locate, `--throw-deprecation` to enforce |
   | Java | `javac -Xlint:deprecation -Werror` |
   | Go | `staticcheck ./...` (SA1019 reports deprecated API use) |
   | Rust | `RUSTFLAGS="-D deprecated" cargo check` |
   | TypeScript | `@typescript-eslint/no-deprecated` |

3. **Bump one package** (section 4), plus only the packages that must move with it (its plugins,
   `@types/*`, peer packages).
4. **Run the official codemod** if one exists:

   | Upgrade | Codemod |
   |---|---|
   | pydantic 1 -> 2 | `bump-pydantic <package-dir>` (`--diff` to preview) |
   | Next.js | `npx @next/codemod@canary upgrade latest` (or a named transform) |
   | React types 18 -> 19 | `npx types-react-codemod@latest preset-19 ./src` |
   | Java / Spring Boot | OpenRewrite recipes via `rewrite-maven-plugin` or the Gradle plugin |
   | Python syntax for a new minimum | `pyupgrade --py313-plus`, `django-upgrade --target-version 5.2` |
   | Angular | `ng update @angular/core @angular/cli` |
   | Rust edition | `cargo fix --edition` |

5. **Type-check, full test suite, then a canary**: deploy to a small share of traffic and compare
   error rate and latency with the baseline before rolling out.
6. Write what changed behaviour (not just "bumped X") in the PR and changelog (`docs-and-adr-writing`).

## 4. Targeted update commands

| Ecosystem | Within constraints | Change the constraint / go to latest |
|---|---|---|
| uv | `uv lock --upgrade-package httpx` (`-P httpx`) | edit `pyproject.toml`, or `uv add 'httpx>=0.29'`, then `uv lock` |
| pnpm | `pnpm update foo` | `pnpm update foo --latest` (`-L`), `-r` for all workspaces |
| npm | `npm update foo` | `npm install foo@^5` |
| cargo | `cargo update foo` / `cargo update foo --precise 1.2.3` | edit `Cargo.toml`; `cargo update --breaking` is unstable |
| Go | `go get foo@v1.2.3 && go mod tidy` | major versions change the import path (`foo/v2`) |
| Gradle | `gradle/libs.versions.toml` version catalog: change one entry | |
| Maven | `mvn versions:use-dep-version -Dincludes=g:a -DdepVersion=1.2.3` | or edit `<version>` |

Never run "upgrade everything" (`uv lock --upgrade`, `pnpm update --latest -r`, `go get -u ./...`)
in a feature PR; do it as a scheduled lockfile-maintenance PR with nothing else in it.

## 5. Lockfile hygiene

- Commit lockfiles for applications **and** libraries (libraries' CI then tests a known set; consumers
  still resolve from the library's ranges).
- Frozen installs in CI so the lockfile is the single source of truth:

  | Tool | Frozen install |
  |---|---|
  | uv | `uv sync --locked` (fails if `uv.lock` is stale); `--frozen` skips the check |
  | npm | `npm ci` |
  | pnpm | `pnpm install --frozen-lockfile` (default in CI) |
  | cargo | `cargo build --locked` |
  | Go | `go mod verify` and `go build -mod=readonly` (default) |
  | Gradle | dependency locking: `./gradlew dependencies --write-locks` once, then locked builds |

- Never hand-edit a lockfile. Merge conflict in a lockfile: take either side, rerun the tool on the
  merged manifest (`uv lock`, `pnpm install`, `npm install`, `cargo update -w`, `go mod tidy`), commit.
- Ranges (`^`, `~`, `>=`) in an app without a lockfile mean every deploy may install new code.

## 6. Why is this here, and duplicates

| Tool | Reverse dependency query | Deduplicate |
|---|---|---|
| uv | `uv tree --invert --package x` | `uv lock` already picks one version per package |
| pnpm | `pnpm why x` | `pnpm dedupe` |
| npm | `npm ls x`, `npm explain x` | `npm dedupe` |
| cargo | `cargo tree -i x` (`-d` lists duplicates) | bump the dependents; `cargo update` |
| Go | `go mod why -m x`, `go mod graph` | MVS picks one version per major |

Overrides force a version the graph does not choose: npm `overrides`, pnpm `overrides`, Yarn
`resolutions`, uv `override-dependencies` / `constraint-dependencies`, cargo `[patch]`, Go `replace`,
Gradle `constraints`, Maven `dependencyManagement`. Use one only as a last resort, with a comment
naming the reason and a tracking issue to remove it.

## 7. Update bots and supply-chain cooldowns

Most malicious package versions are found and pulled within hours to days, so do not install
versions published minutes ago.

| Layer | Setting |
|---|---|
| Renovate | `extends: ["config:recommended"]` (or `config:best-practices`, which adds `security:minimumReleaseAgeNpm` = 3 days), `minimumReleaseAge: "3 days"`, `packageRules` grouping, `schedule`, automerge of patch/minor dev deps on green CI, `dependencyDashboard` |
| Dependabot | `groups` per ecosystem, `cooldown: {default-days: 3, semver-major-days: 14}`, `open-pull-requests-limit` |
| pnpm 11+ | `minimumReleaseAge` defaults to 1440 minutes (1 day); `minimumReleaseAgeExclude` for urgent fixes; dependency build scripts blocked unless allowed (`allowBuilds`, `pnpm approve-builds`; unreviewed builds fail with `ERR_PNPM_IGNORED_BUILDS` because `strictDepBuilds` defaults to true) |
| npm 11.10+ | `min-release-age=3` in `.npmrc` (days; default off), `min-release-age-exclude` |
| Yarn 4.10+ | `npmMinimalAgeGate` in `.yarnrc.yml` (duration; current docs show default `"1w"`), `npmPreapprovedPackages` |
| uv | `[tool.uv] exclude-newer = "3 days"` (friendly durations in current uv) |

Align the bot with the package manager: if Renovate proposes a version 2 hours old, `pnpm install
--frozen-lockfile` in CI fails with `ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION`. Set the bot's
`minimumReleaseAge` / `cooldown` at least as long as the package manager's gate. For an urgent security
fix younger than the gate, add that package to the exclude list in the same PR and remove it later.

## 8. Vulnerability triage

| Ecosystem | Scanner | Reachability |
|---|---|---|
| Any lockfile | `osv-scanner scan source -r .` | no (lists affected versions) |
| Python | `uv audit` (uv 0.13+, OSV-backed; `--ignore-until-fixed ID`) or `pip-audit` in the project env | no |
| Node | `npm audit --omit=dev`, `pnpm audit --prod` | no |
| Rust | `cargo deny check advisories` (or `cargo audit`) | no |
| Go | `govulncheck ./...` | **yes**: reports only vulnerabilities whose symbols your code calls |

Decision per finding:

| Situation | Action |
|---|---|
| Fixed version exists, in range | upgrade now (patch PR, normal review) |
| Fix needs a major bump | upgrade with the section 3 procedure, or a temporary override of the transitive package |
| No fix, vulnerable code unreachable or not exposed (dev-only, no untrusted input) | accept with an expiry: osv-scanner `ignoreUntil`, `uv audit --ignore-until-fixed ID`, `pip-audit --ignore-vuln ID`, cargo-deny `ignore` entry with `reason` |
| No fix, reachable and exposed | mitigate (input validation, feature off, WAF rule), escalate to `security-auditor` |

Reachability and exposure decide priority more than raw CVSS: a 9.8 in a test-only dependency matters
less than a 6.5 in the request parser.

## 9. Regression after an upgrade

1. Confirm the lockfile change is the cause: check out the commit before the bump, run the failing test,
   then after.
2. Bisect the lockfile: list changed packages and their new versions (script in
   [the command reference](references/ecosystem-commands.md)), apply half of them to the old lockfile
   (`uv lock -P 'a==1.4.0' -P 'b==2.1.3' ...`), test, recurse. With 32 changed packages that is at most
   5 rounds. Mechanics in `debugging-method`.
3. Read the guilty package's changelog and commits between the two versions; look for changed defaults.
4. Pin the previous version with a comment and an issue (`"foo<2.4  # 2.4 changes X, see #123"`), then
   fix forward: adapt the code or report upstream with a minimal reproduction.

## 10. Pitfalls

- Upgrading everything at once: one red CI run, forty suspects.
- `^`/`~` ranges in applications without a committed lockfile.
- Upper-bound pins in library metadata (`requests<2.32`) that force resolver conflicts on every
  consumer; libraries declare the minimum they need and test against the latest.
- Ignoring peer-dependency warnings (`ERESOLVE`, unmet peer): the app runs two copies of React or a
  plugin built for another major.
- `@types/*` drifting from the runtime package's major version: types lie about the API.
- Silently changed defaults: HTTP client timeouts, JSON serialization of dates and decimals, TLS
  minimum versions, strict validation; read the "Changed" section, not only "Breaking".
- New `postinstall` / build scripts in a minor release (supply-chain red flag; pnpm blocks them).
- Running codemods on a dirty tree; always on a clean branch so the diff is reviewable.
- Treating "tests pass" as "safe" when tests mock the upgraded library.

## 11. Worked example: pydantic 1.10 -> 2.x in a FastAPI service

Starting point: 140 pydantic models, `pydantic>=1.10,<2`, FastAPI already on a release that supports
both pydantic majors (that FastAPI bump was its own PR, merged first).

```bash
# 0. warning-free on 1.10 first
uv run pytest -W error::DeprecationWarning -q                  # fix every warning, commit

# 1. bump only pydantic: rewrites the constraint in pyproject.toml, re-locks only what it must
uv add 'pydantic>=2.12,<3'
git diff uv.lock | rg '^\+name = '                              # new packages in the lock
#   +name = "annotated-types"   +name = "pydantic-core"   +name = "typing-inspection"

# 2. official codemod, preview then apply
uvx bump-pydantic app --diff | less
uvx bump-pydantic app
```

What `bump-pydantic` changed (checked on a sample model): `class Config: orm_mode = True;
allow_population_by_field_name = True` became `model_config = ConfigDict(from_attributes=True,
populate_by_name=True)`; `@validator` became `@field_validator` plus `@classmethod`; `Optional[str]`
fields gained `= None` (v2 no longer implies a default). It did **not** touch `@root_validator`, `.dict()`
or `.parse_obj()`; those were the 23 hand-fixed sites, found with:

```bash
rg -n '@root_validator|\.(dict|json|parse_obj|parse_raw|copy|schema)\(|__fields__|update_forward_refs' app/
```

| v1 | v2 |
|---|---|
| `@root_validator` | `@model_validator(mode="before")` (classmethod, gets raw data) or `mode="after"` (instance method, returns `self`) |
| `obj.dict()`, `obj.json()` | `obj.model_dump()`, `obj.model_dump_json()` |
| `Model.parse_obj(d)`, `parse_raw(s)` | `Model.model_validate(d)`, `model_validate_json(s)` |
| `obj.copy(update=...)` | `obj.model_copy(update=...)` |
| `Model.schema()`, `__fields__` | `Model.model_json_schema()`, `Model.model_fields` |

```bash
# 3. gates
uv run mypy app                       # with the pydantic.mypy plugin enabled
uv run pytest -q -W error::DeprecationWarning   # PydanticDeprecatedSince20 is a DeprecationWarning
```

The tests catch behaviour changes the codemod cannot: v2 no longer coerces `123` to `"123"` for `str`
fields (verified on 2.14.1: `ValidationError`), so a model fed numeric ids by an upstream payload needs
`Field(coerce_numbers_to_str=True)` (or the upstream fix). Quick performance check on a 5-line order
model, same machine and Python 3.12: `parse_obj` 11.0 us per call on 1.10.26, `model_validate` 2.2 us
on 2.14.1. Then a canary at 5 % for a day and full rollout; the PR description lists the coercion
change.

Related: `zero-downtime-migrations`, `regex-engineering`, `resilience-patterns`,
`docs-and-adr-writing`, `security-review`, `debugging-method`, `testing-strategy`, hub `coding-general`.
