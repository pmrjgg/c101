# Per-ecosystem command reference

Companion to `dependency-upgrades` sections 1, 4, 5, 6 and 9. Commands checked against uv 0.13,
npm 11.19, cargo 1.99 and Go 1.27 help output where those tools were available; plugin commands
(cargo-outdated, versions-maven-plugin, Gradle versions plugin) follow their documentation.

## Python (uv)

| Task | Command |
|---|---|
| Outdated direct deps | `uv tree --outdated --depth 1` |
| Upgrade one package within constraints | `uv lock -P httpx` (`--upgrade-package`) |
| Pin one package to an exact version in the lock | `uv lock -P 'httpx==0.28.1'` (verified) |
| Change the constraint | `uv add 'httpx>=0.29'` (edits `pyproject.toml` and locks) |
| Upgrade everything (maintenance PR only) | `uv lock --upgrade` |
| Frozen install in CI | `uv sync --locked` |
| Why is it installed | `uv tree --invert --package certifi` |
| Force a version the resolver would not pick | `[tool.uv] override-dependencies = ["urllib3>=2.2"]` |
| Constrain without adding a dependency | `[tool.uv] constraint-dependencies = ["grpcio<1.70"]` |
| Vulnerabilities | `uv audit` (OSV; `--ignore ID`, `--ignore-until-fixed ID`) |
| Release-age gate | `[tool.uv] exclude-newer = "3 days"`; per package `exclude-newer-package` |
| Runtime pin | `.python-version`, `requires-python` in `pyproject.toml`; `uv python install 3.15` |

## Node (pnpm / npm / Yarn)

| Task | pnpm | npm | Yarn (4) |
|---|---|---|---|
| Outdated | `pnpm outdated -r` | `npm outdated` | `yarn upgrade-interactive` |
| Update within range | `pnpm update foo` | `npm update foo` | `yarn up -R foo` (re-resolves every instance within existing ranges) |
| Go to latest | `pnpm update foo --latest` | `npm install foo@latest` | `yarn up foo@latest` |
| Frozen install | `pnpm install --frozen-lockfile` | `npm ci` | `yarn install --immutable` |
| Why | `pnpm why foo` | `npm explain foo` / `npm ls foo` | `yarn why foo` |
| Deduplicate | `pnpm dedupe` | `npm dedupe` | `yarn dedupe` |
| Force a version | `overrides:` in `pnpm-workspace.yaml` | `"overrides"` in `package.json` | `"resolutions"` in `package.json` |
| Audit | `pnpm audit --prod` | `npm audit --omit=dev` | `yarn npm audit --environment production` |
| Approve dependency build scripts | `pnpm approve-builds` / `allowBuilds:` | `ignore-scripts=true` to block all | `enableScripts: false` |
| Runtime pin | `engines.node`, `.nvmrc` / `.node-version`, `packageManager` field | same | same |

## Rust (cargo)

| Task | Command |
|---|---|
| In-range updates preview | `cargo update --dry-run` (`-n`) |
| Majors available | `cargo outdated -R` (cargo-outdated plugin) |
| Update one crate | `cargo update serde` |
| Exact version | `cargo update serde --precise 1.0.228` |
| Highest semver-breaking version | `cargo update serde --breaking` (unstable, nightly `-Z`) |
| Frozen build | `cargo build --locked` |
| Why / duplicates | `cargo tree -i serde`, `cargo tree -d` |
| Force a source or fork | `[patch.crates-io] foo = { git = "...", rev = "..." }` |
| Advisories, licenses, bans | `cargo deny check` (`advisories` only: `cargo deny check advisories`) |
| MSRV | `rust-version = "1.85"` in `Cargo.toml`; check with `cargo +1.85 check` |
| Toolchain pin | `rust-toolchain.toml` (`channel = "1.99"`) |

## Go

| Task | Command |
|---|---|
| Outdated | `go list -m -u all` (`-json` for tooling) |
| Update one module | `go get example.com/foo@v1.2.3 && go mod tidy` |
| Patch-level updates of all deps | `go get -u=patch ./... && go mod tidy` (maintenance PR) |
| New major | change imports to `example.com/foo/v2`, `go get example.com/foo/v2@latest` |
| Why | `go mod why -m example.com/foo`, `go mod graph` |
| Verify checksums | `go mod verify` |
| Force a version or fork | `replace example.com/foo => example.com/fork v1.2.4` in `go.mod` |
| Vulnerabilities (reachability-aware) | `govulncheck ./...` |
| Toolchain | `go 1.25` (minimum language version) and `toolchain go1.27.2` lines; `GOTOOLCHAIN=local` disables auto-download |
| Deprecated API use | `staticcheck ./...` (SA1019) |

## JVM (Maven / Gradle)

| Task | Maven | Gradle |
|---|---|---|
| Outdated | `mvn versions:display-dependency-updates`, `versions:display-plugin-updates` | `./gradlew dependencyUpdates` (ben-manes plugin) |
| Set one version | `mvn versions:use-dep-version -Dincludes=g:a -DdepVersion=1.2.3` | edit `gradle/libs.versions.toml` |
| Why | `mvn dependency:tree -Dincludes=g:a` | `./gradlew dependencyInsight --dependency a` |
| Force | `<dependencyManagement>` | `constraints { }` / `resolutionStrategy.force` |
| Lock | n/a (pin exact versions) | `dependencyLocking { lockAllConfigurations() }` + `./gradlew dependencies --write-locks` |
| Codemods | OpenRewrite `rewrite-maven-plugin:run -Drewrite.activeRecipes=...` | OpenRewrite Gradle plugin `rewriteRun` |
| Runtime pin | `maven.compiler.release`, toolchains | `java { toolchain { languageVersion = JavaLanguageVersion.of(25) } }` |

## Lockfile bisection (uv example)

```bash
# 1. packages whose locked version changed between the good and the bad commit
git show GOOD:uv.lock > /tmp/good.lock && git show BAD:uv.lock > /tmp/bad.lock
uv run --no-project python - <<'EOF'
import tomllib
load = lambda f: {p["name"]: p.get("version") for p in tomllib.load(open(f, "rb"))["package"]}
good, bad = load("/tmp/good.lock"), load("/tmp/bad.lock")
for name in sorted(set(good) | set(bad)):
    if good.get(name) != bad.get(name):
        print(f"{name}=={bad.get(name)}")        # target versions to apply
EOF

# 2. on a branch at GOOD, apply half of the bumps, test, recurse into the failing half
git switch -c bisect-lock GOOD
uv lock -P 'httpx==0.28.1' -P 'anyio==4.9.0' -P 'certifi==2026.9.1'   # half of the list
uv sync --locked && uv run pytest -x -q tests/test_failing.py
```

Removed or added packages ride along with the package that pulled them in. With n changed packages the
search takes about log2(n) rounds; for pnpm/npm the same approach uses `pnpm update foo@x.y.z` /
`npm install foo@x.y.z` on the good lockfile.
