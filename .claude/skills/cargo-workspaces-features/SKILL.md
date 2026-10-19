---
name: cargo-workspaces-features
description: "Cargo workspace and release engineering. Covers virtual workspaces with resolver 3, inherited dependencies, lints and package fields, crate-split heuristics, additive features and cargo-hack powersets, MSRV policy and toolchain pinning, dependency hygiene, cargo-deny and supply chain, semver checks, and releases with release-plz, dist and crates.io trusted publishing. Load when restructuring crates, adding features or preparing a Rust release."
when_to_use: "Editing Cargo.toml [workspace], [workspace.dependencies], [workspace.lints], [features], rust-version, rust-toolchain.toml, .cargo/config.toml, deny.toml, release-plz.toml; errors like 'cannot find module or crate' only with -p, 'failed to select a version', 'package requires rustc X', duplicate dependency versions, feature combinations failing, docs.rs build failures; splitting a crate, adding an optional dependency, raising MSRV, publishing to crates.io."
---

# Cargo workspaces, features and releases

Verified October 2026 on Cargo 1.99 (resolver 3, `cargo publish --workspace`), cargo-hack 0.6,
cargo-deny 0.20, cargo-semver-checks 0.51, release-plz 0.3, dist 0.32, cargo-msrv 0.19.
Never raise MSRV or edition as a side effect of another change: both are breaking for users.

Deep material: [CI matrix template](references/ci-matrix.md) |
[supply chain and release workflows](references/release-and-supply-chain.md)

## 1. Virtual workspace template

```toml
# Cargo.toml (root, no [package])
[workspace]
resolver = "3"                 # must be explicit in a virtual workspace; MSRV-aware resolution
members = ["crates/*"]
exclude = ["fuzz"]

[workspace.package]            # inheritable: version, edition, rust-version, license, authors,
version = "0.4.0"              # description, documentation, homepage, repository, readme,
edition = "2024"               # keywords, categories, include, exclude, publish, license-file
rust-version = "1.85"
license = "MIT OR Apache-2.0"
repository = "https://github.com/org/app"

[workspace.dependencies]       # one version per dependency for the whole tree
serde = { version = "1", features = ["derive"] }
tokio = { version = "1", default-features = false }
appcore = { path = "crates/core", version = "0.4.0" }   # version needed to publish dependents

[workspace.lints.rust]
unsafe_op_in_unsafe_fn = "deny"
unexpected_cfgs = { level = "warn", check-cfg = ['cfg(loom)'] }
# unsafe_code = "forbid" belongs in crates without unsafe (forbid cannot be relaxed per crate)

[workspace.lints.clippy]
all = { level = "warn", priority = -1 }    # group first (lower priority) so single lints override it
unwrap_used = "warn"
undocumented_unsafe_blocks = "deny"
```

```toml
# crates/server/Cargo.toml
[package]
name = "app-server"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
publish = false

[dependencies]
appcore = { workspace = true, features = ["serde"] }   # features add to the workspace ones
tokio = { workspace = true, features = ["rt-multi-thread", "macros"] }

[lints]
workspace = true
```

Orient in an unknown workspace first: `cargo metadata --no-deps --format-version 1 | jq -r '.packages[].name'`
(members), `grep -nE '^(edition|rust-version|resolver)' Cargo.toml crates/*/Cargo.toml`,
`cat rust-toolchain.toml`, `ls .cargo/config.toml deny.toml clippy.toml rustfmt.toml`.

Rules: workspace dependencies cannot be `optional` at the root (members add `optional = true`);
member `features` are additive to the workspace entry; member `default-features = false`
overrides the workspace entry only on Rust 1.99+ in edition-2024 members (older: ignored with a
warning). Lints in `[lints]` apply to the package only, not to dependencies.
Suppress locally with `#[expect(clippy::lint, reason = "...")]`: it warns when the lint stops firing.
Useful non-default clippy lints: `undocumented_unsafe_blocks`, `unwrap_used`, `expect_used` (libs),
`cast_possible_truncation`, `cast_sign_loss`, `large_futures`, `missing_errors_doc` (libs),
`dbg_macro`, `todo`, `print_stdout` (libs). Survey with `cargo clippy -- -W clippy::pedantic`
(do not gate on it blindly); apply machine fixes with `cargo clippy --fix --allow-dirty -p crate`.

## 2. When to split a crate

| Split out | Because |
|---|---|
| a slow-to-compile leaf (codegen, big generics) | parallel and incremental builds; check with `cargo build --timings` |
| proc macros | must be their own `proc-macro = true` crate |
| C bindings | `foo-sys` (raw, `links =`) + `foo` (safe) convention, see `rust-ffi-bindings` |
| domain core used by several binaries | `core` lib + thin `cli` / `server` bins; keeps I/O out of the core |
| internal helpers, test utilities, `xtask` | `publish = false`; test utils as a dev-dependency |

Avoid: one crate per module (link and metadata overhead), dev-dependency cycles (`core` dev-depends
on `testkit` which depends on `core` builds two copies of `core` and types no longer match:
put such tests in a separate crate), and splits across hot inlining boundaries (generic hot
paths across crates need `#[inline]` or LTO).

## 3. Feature rules

- Additive only: enabling a feature never removes API or changes behaviour incompatibly. Mutually
  exclusive backends become separate crates or a runtime choice.
- Optional dependency through `dep:` (`json = ["dep:serde_json"]`) so no implicit feature named
  after the dependency leaks into your API.
- Weak dependency features: `serde = ["dep:serde", "chrono?/serde"]` enables `chrono/serde` only if
  something else enabled `chrono`; likewise `derive = ["serde?/derive"]` never pulls in `serde` itself.
- Libraries: minimal `default`; binaries opt in. `no_std` crates: `default = ["std"]` plus
  `#![cfg_attr(not(feature = "std"), no_std)]`; `alloc` as its own feature when useful.
- Gate code, not just dependencies: `#[cfg_attr(feature = "serde", derive(serde::Serialize))]`.
- Document every feature in the crate docs or `Cargo.toml` comments. docs.rs:
  `[package.metadata.docs.rs] all-features = true` and `rustdoc-args = ["--cfg", "docsrs"]`,
  crate root `#![cfg_attr(docsrs, feature(doc_cfg))]` (current nightly rustdoc badges cfg'd items
  automatically), explicit `#[cfg_attr(docsrs, doc(cfg(feature = "serde")))]` where needed.

## 4. Feature unification checks

Features unify per build across all selected packages: a crate that only compiles because a
sibling enables a feature is a latent bug that `cargo build -p that-crate` or downstream users hit.

```bash
cargo tree -e features -i serde                      # who enables which serde features
cargo tree -e features -i appcore                    # which members turn on appcore/serde
cargo hack check --each-feature --no-dev-deps --workspace
cargo hack check --feature-powerset --depth 2 --no-dev-deps --workspace   # pairs; full powerset is 2^n
cargo hack check --feature-powerset --exclude-features nightly --group-features rustls,native-tls
```

Resolver 2/3 rules: build-dependencies and proc macros do not share features with normal
dependencies; dev-dependency features apply only when building tests/examples/benches; features of
target-specific dependencies for other platforms are ignored. `--no-dev-deps` removes
dev-dependencies during the run (faster, no dev-only feature unification, no dev-dependency
cycles); keep a second `--each-feature --all-targets` run so tests also compile per feature.

## 5. MSRV and toolchain

- Declare `rust-version` (inherited from the workspace). Edition 2024 needs >= 1.85.
- Resolver 3 (default for edition 2024) prefers dependency versions whose `rust-version` is
  compatible (`incompatible-rust-versions = "fallback"`); configure it explicitly in
  `.cargo/config.toml` under `[resolver]` for older-edition workspaces; bypass once with
  `cargo update --ignore-rust-version`.
- Verify: `cargo hack check --rust-version --workspace` (runs `rustup run <rust-version> cargo check`
  per package), `cargo msrv find` / `cargo msrv verify`, or a CI job on `dtolnay/rust-toolchain@1.85`.
- Nightly-only tools (Miri, cargo-fuzz, udeps, sanitizers) run as `cargo +nightly ...` and never
  become a build requirement of the crate itself.
- Pin the development toolchain for applications (libraries pin MSRV in CI instead):

```toml
# rust-toolchain.toml
[toolchain]
channel = "1.99.1"
components = ["rustfmt", "clippy"]
targets = ["wasm32-unknown-unknown"]
profile = "minimal"
```

## 6. Dependency hygiene

| Check | Command / rule |
|---|---|
| duplicate versions | `cargo tree -d` (then unify through `[workspace.dependencies]` or upgrades) |
| unused deps | `cargo machete` (fast, heuristic; ignore false positives in `[package.metadata.cargo-machete] ignored = [...]`), `cargo +nightly udeps` (precise, slower) |
| why is X here | `cargo tree -i X -e normal,build` |
| local fork of a dep | `[patch.crates-io] foo = { path = "../foo" }` (whole graph), not a `path` dep in one member |
| git deps | pin `rev = "<sha>"`; crates.io refuses to publish crates with git-only deps |
| lockfile | commit `Cargo.lock` (apps and libraries alike); CI uses `--locked` |
| upgrades | `cargo update --dry-run`, `cargo update -p foo --precise 1.2.3` |

## 7. Supply chain

| Tool | Command | Covers |
|---|---|---|
| cargo-deny | `cargo deny init`; `cargo deny check advisories bans licenses sources` | RustSec advisories, yanked crates, license allow-list, banned or duplicate crates, unknown registries/git |
| cargo-audit | `cargo audit` | RustSec advisories only (quick local check) |
| cargo-vet | `cargo vet init`, `cargo vet`, `cargo vet certify` | human audits of third-party code, imported from trusted orgs |
| SBOM | `cargo cyclonedx --format json --all` | CycloneDX SBOM per crate |
| new dependency review | maintenance activity, `unsafe` count (`cargo geiger`), transitive count (`cargo tree -p dep`), license | before `cargo add` |

`deny.toml` essentials and a release workflow: [release-and-supply-chain](references/release-and-supply-chain.md).

## 8. Release

1. Library API check: `cargo semver-checks check-release -p appcore` (against the last published
   version; `--baseline-rev <git-ref>` for unpublished history). Breaking change -> major bump
   (or minor bump below 1.0).
2. Versioning and changelog: release-plz (`release-plz release-pr` opens a PR with bumps and
   changelog from conventional commits, `release-plz release` publishes and tags) or cargo-release
   (`cargo release minor --execute`).
3. Publishing order: `cargo publish --workspace` (Cargo 1.90+) publishes members in dependency
   order and skips `publish = false` members; dry run first with `--dry-run`.
4. Binaries and installers: dist (`dist init` generates `.github/workflows/release.yml`; pushing a
   version tag builds archives, shell/PowerShell installers and a GitHub Release).
5. crates.io trusted publishing from GitHub Actions: configure the repository/workflow on the
   crate's settings page, grant `id-token: write`, get a short-lived token with
   `rust-lang/crates-io-auth-action@v1` (output `token`) or let release-plz do it. The first
   release of a new crate must still be published with a regular token.

## 9. Build configuration

```toml
# .cargo/config.toml (checked in; per-user overrides go in ~/.cargo/config.toml)
[alias]
lint = "clippy --workspace --all-targets --all-features -- -D warnings"
xtask = "run --package xtask --"

[target.x86_64-unknown-linux-gnu]
rustflags = ["-C", "link-arg=-fuse-ld=mold"]     # lld is already the default here since 1.90

[resolver]
incompatible-rust-versions = "fallback"

[profile.dev.package."*"]
opt-level = 2                                    # optimised deps, debuggable workspace code
```

Profiles may also live in the root `Cargo.toml` (only the root's `[profile]` counts in a
workspace). Build scripts: `cargo::rerun-if-changed=` / `rerun-if-env-changed=` for every input
(syntax `cargo::` needs 1.77+); read target info from `CARGO_CFG_*`, not `cfg!`.

## 10. CI matrix

| Job | Command | Toolchain |
|---|---|---|
| fmt | `cargo fmt --all -- --check` | stable |
| clippy | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable (pinned) |
| test | `cargo nextest run --workspace --all-features --locked` + `cargo test --doc --workspace` | stable, 3 OSes if claimed |
| features | `cargo hack check --feature-powerset --depth 2 --no-dev-deps --workspace` | stable |
| MSRV | `cargo hack check --rust-version --workspace --locked` | per-package MSRV |
| Miri | `cargo +nightly miri test -p <crates with unsafe>` | nightly |
| deny | `cargo deny check` (EmbarkStudios/cargo-deny-action@v2) | any |
| semver (release PRs) | `cargo semver-checks check-release --workspace` | stable |

Run the cheap jobs first and scope single-crate changes with `-p <crate>`. Cache with
`Swatinem/rust-cache@v2`; install tools with `taiki-e/install-action@v2` (locally:
`cargo install --locked cargo-nextest cargo-hack cargo-deny cargo-semver-checks cargo-llvm-cov`
or prebuilt binaries via `cargo binstall`). Full YAML: [ci-matrix](references/ci-matrix.md).

## 11. Worked example: split a monolith into core, cli and server

Goal: `crates/core` (lib `appcore`, optional `serde` feature), `crates/cli` and `crates/server`
(bins, `publish = false`), shared lints, versions and dependencies through the template in
section 1. First attempt at `crates/core/src/lib.rs`:

```rust
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]   // not gated
pub struct Task { pub id: u64, pub title: String, pub done: bool }
```

with `serde = { workspace = true, optional = true }`, `[features] serde = ["dep:serde"]`, the
workspace entry `serde = { version = "1", default-features = false, features = ["derive"] }`, and
`app-server` depending on `appcore` with `features = ["serde"]` plus `serde_json`.

Real results (Cargo 1.99, cargo-hack 0.6.45; paths and tree output abridged):

```text
$ cargo build                      # whole workspace: OK (server switches serde on for everyone)
$ cargo build -p app-cli
error[E0433]: cannot find module or crate `serde` in this scope
 --> crates/core/src/lib.rs:4:35
$ cargo tree -e features -i appcore
appcore v0.1.0 (crates/core)
├── appcore feature "default" (command-line) ... app-cli, app-server
└── appcore feature "serde"
    └── app-server v0.1.0 (crates/server)
```

Fix 1: `#[derive(Debug, Clone, PartialEq)]` plus
`#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]`. Then the powerset:

```text
$ cargo hack check --feature-powerset --no-dev-deps --workspace
info: running `cargo check` on app-cli (1/6)
info: running `cargo check --no-default-features` on appcore (2/6)
info: running `cargo check --no-default-features --features default,serde` on appcore (3/6)
error[E0277]: the trait bound `String: serde::Serialize` is not satisfied
```

A second latent bug: the workspace entry disabled serde's default features (no `std`, so no
`String` impls); `serde_json` in the server re-enabled them through unification. Fix 2:
`serde = { version = "1", features = ["derive"] }`. Re-run: all 6 checks pass (app-cli,
appcore x4 combinations, app-server). `cargo publish --workspace --dry-run` then packaged and
verified only `appcore` (both bins are `publish = false`) and stopped with
"aborting upload due to dry run". Keep the powerset job in CI so the next feature cannot regress.

## 12. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| builds at the root, fails with `-p crate` or for users | feature unification masks a missing feature | `cargo hack --each-feature/--feature-powerset --no-dev-deps` |
| "failed to select a version for the requirement" | wrong major (`tracing = "1"`; it is 0.1) or MSRV filter | `cargo search` / `cargo info`, check `rust-version` |
| CI and local builds differ | unpinned toolchain, no lockfile, `cargo update` drift | `rust-toolchain.toml`, commit `Cargo.lock`, `--locked` |
| two versions of a crate, type mismatch errors | different majors or a dev-dependency cycle | `cargo tree -d`, unify in `[workspace.dependencies]`, break cycles |
| `default-features = false` ignored | member override on edition < 2024 or Rust < 1.99 | set it on the `[workspace.dependencies]` entry |
| clippy group overrides your single lint | missing `priority = -1` on the group | lower priority for groups |
| docs.rs build fails | feature-gated items need features or nightly-only attributes outside `cfg_attr(docsrs)` | `package.metadata.docs.rs`, gate attributes on `docsrs` |
| publish fails "all dependencies must have a version" | path/git dep without `version` | add `version` next to `path`; no git-only deps |
| semver-checks flags a break you did not intend | removed pub item, added a required trait item, changed a type | restore, deprecate first, or bump major |
| trusted publishing 403 on first release | new crates cannot be created via OIDC | publish the first version with a token |

Related: `rust-testing-fuzzing`, `rust-performance`, `rust-ffi-bindings`, `rust-error-handling`,
`rust-unsafe-soundness`, hub `rust-craft`.
