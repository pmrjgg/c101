# Supply chain and release workflows

## 1. cargo-deny (`deny.toml`, cargo-deny 0.20)

```toml
[graph]
all-features = true                  # check every optional dependency too

[advisories]
yanked = "deny"                      # deny | warn (default) | allow
unmaintained = "workspace"           # all (default) | workspace | transitive | none
ignore = [
  # { id = "RUSTSEC-2026-0000", reason = "not reachable: we never call X", expiry = "P90D" },  # duration since publication
]

[licenses]
allow = ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC", "Unicode-3.0", "Zlib"]
confidence-threshold = 0.8

[bans]
multiple-versions = "warn"           # "deny" once duplicates are cleaned up
wildcards = "deny"                   # no `*` version requirements
deny = [{ crate = "openssl", reason = "use rustls" }]
skip = []                            # crate@version allowed to be duplicated

[sources]
unknown-registry = "deny"
unknown-git = "deny"
allow-git = []
```

`cargo deny check` runs all four; `cargo deny check advisories` alone is fast enough for every
PR. `[advisories] version = 2` and the removed `vulnerability`/`notice` keys belong to old
templates: regenerate with `cargo deny init` when upgrading. `maximum-db-staleness` defaults to
90 days.

## 2. Other supply-chain tools

| Tool | Use |
|---|---|
| `cargo audit` | RustSec check of `Cargo.lock`; `cargo audit --deny warnings` in CI if you do not run cargo-deny |
| `cargo vet` | `cargo vet init` creates `supply-chain/`; `cargo vet` fails on unaudited crates; `cargo vet certify <crate> <version>` records your audit; import audits from organisations you trust |
| `cargo cyclonedx --format json --all` | CycloneDX SBOM files per crate for compliance scanners |
| `cargo geiger` | counts `unsafe` in the dependency tree before adopting a crate |
| `cargo tree -d`, `cargo machete` | duplicates and unused dependencies (attack surface and build time) |

## 3. Semver checks

```bash
cargo install --locked cargo-semver-checks
cargo semver-checks check-release -p appcore                 # vs latest crates.io version
cargo semver-checks check-release -p appcore --baseline-rev v0.4.0
cargo semver-checks check-release --workspace
```

Typical findings: removed or renamed public item, new required trait method, changed function
signature, enum variant added to an exhaustive enum (add `#[non_exhaustive]` before 1.0),
auto-trait (`Send`/`Sync`) lost through a new field. It checks API, not behaviour.

## 4. release-plz (versions, changelogs, publishing)

```toml
# release-plz.toml
[workspace]
changelog_update = true
git_release_enable = true
semver_check = true                  # default true for libraries
dependencies_update = false          # only bump workspace packages

[[package]]
name = "app-cli"
publish = false                      # tag and release notes, no crates.io upload
```

```yaml
# .github/workflows/release-plz.yml
on:
  push:
    branches: [main]
jobs:
  release-pr:
    runs-on: ubuntu-latest
    permissions: { contents: write, pull-requests: write }
    concurrency: { group: "release-plz-${{ github.ref }}", cancel-in-progress: false }
    steps:
      - uses: actions/checkout@v7
        with: { fetch-depth: 0 }
      - uses: dtolnay/rust-toolchain@stable
      - uses: release-plz/action@v0.5
        with: { command: release-pr }
        env: { GITHUB_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }
  release:
    runs-on: ubuntu-latest
    permissions: { contents: write, pull-requests: read, id-token: write }   # id-token: trusted publishing
    steps:
      - uses: actions/checkout@v7
        with: { fetch-depth: 0 }
      - uses: dtolnay/rust-toolchain@stable
      - uses: release-plz/action@v0.5
        with: { command: release }
        env: { GITHUB_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }
```

With trusted publishing configured on crates.io, release-plz obtains the crates.io token itself:
omit `CARGO_REGISTRY_TOKEN` and do not add `crates-io-auth-action` to this workflow.

## 5. Plain cargo publishing with trusted publishing

```yaml
jobs:
  publish:
    runs-on: ubuntu-latest
    environment: release
    permissions: { id-token: write, contents: read }
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@stable
      - uses: rust-lang/crates-io-auth-action@v1
        id: auth
      - run: cargo publish --workspace          # dependency order, skips publish = false
        env: { CARGO_REGISTRY_TOKEN: "${{ steps.auth.outputs.token }}" }
```

Setup on crates.io (crate settings, Trusted Publishing): repository owner, repository name,
workflow file name and optional environment. The token is short-lived and revoked by the
action's post step. New crates: publish the first version manually with an API token, then
configure trusted publishing.

cargo-release alternative: `cargo release minor --workspace` (dry run by default), then
`--execute` to bump, commit, tag, publish and push.

## 6. dist (binary installers and GitHub Releases)

```bash
cargo install --locked cargo-dist      # installs the `dist` binary
dist init                              # interactive: targets, installers (shell, powershell, homebrew, msi), CI
dist plan                              # what would be built for the current tag
git tag v0.4.0 && git push --tags      # generated release.yml builds, uploads, publishes the release
```

Configuration lives in `dist-workspace.toml` (or `[workspace.metadata.dist]` in older setups);
re-run `dist init` after upgrading dist so the generated workflow matches the tool version.

## 7. Release checklist

1. `cargo deny check`, full CI green on main, `cargo semver-checks` clean or bump chosen.
2. Changelog reviewed (release-plz PR); MSRV change called out explicitly if any.
3. `cargo publish --workspace --dry-run` (packaging, `include`/`exclude`, README, license files).
4. Merge the release PR; the workflow publishes crates, tags, creates the GitHub Release and
   (dist) uploads binaries.
5. Verify docs.rs built every crate and features render; yank (`cargo yank --version x.y.z`) only
   for broken releases, never to hide mistakes in already-used versions.
