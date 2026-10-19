# nextest configuration and CI test jobs

## 1. `.config/nextest.toml`

```toml
[profile.default]
retries = 0
slow-timeout = { period = "60s", terminate-after = 2 }   # mark slow at 60 s, kill at 120 s
fail-fast = true
# global-timeout = "2h"

[profile.ci]
retries = 2                         # flaky tests show as FLAKY in the summary: track and fix
fail-fast = false
slow-timeout = { period = "60s", terminate-after = 5, grace-period = "30s" }

[profile.ci.junit]
path = "junit.xml"                  # written under target/nextest/ci/

[profile.mutants]                   # used by cargo-mutants: cargo mutants --cargo-arg=--profile=mutants
fail-fast = true
slow-timeout = { period = "30s", terminate-after = 2 }

[test-groups]
serial-db = { max-threads = 1 }     # tests sharing one real database
gpu = { max-threads = 2 }

[[profile.default.overrides]]
filter = 'test(/^db_/) | package(storage)'
test-group = 'serial-db'

[[profile.default.overrides]]
filter = 'test(e2e_)'
slow-timeout = { period = "120s", terminate-after = 5 }
```

Filtersets: `test(substr)`, `test(/regex/)`, `test(=exact)`, `package(name)`, `kind(test)`,
`binary(name)`, `deps(crate)`, `group(name)`; combine with `|`, `&`, `not`, `()`.
Select a profile with `--profile ci` or `NEXTEST_PROFILE=ci`. Preview selection:
`cargo nextest list -E 'group(serial-db)'`.

Useful flags: `--no-capture` (stream output, runs serially), `--partition count:2/4` or
`hash:2/4` (sharding), `cargo nextest archive --archive-file tests.tar.zst` (build once, run on
other machines with `--archive-file`), `--run-ignored only`.

## 2. GitHub Actions jobs (adapt to the CI in use)

```yaml
env:
  CARGO_TERM_COLOR: always
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix: { os: [ubuntu-latest, macos-latest, windows-latest] }
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - uses: taiki-e/install-action@v2
        with: { tool: cargo-nextest }
      - run: cargo nextest run --workspace --all-features --profile ci
      - run: cargo test --doc --workspace --all-features

  miri:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@nightly
        with: { components: miri }
      - run: cargo miri setup
      - run: cargo miri test -p mycrate-with-unsafe
      - run: cargo miri test -p mycrate-with-unsafe
        env: { MIRIFLAGS: "-Zmiri-tree-borrows -Zmiri-strict-provenance" }

  loom:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@stable
      - run: cargo test --release --lib loom_
        env: { RUSTFLAGS: "--cfg loom", LOOM_MAX_PREEMPTIONS: "2" }

  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@stable
        with: { components: llvm-tools-preview }
      - uses: taiki-e/install-action@v2
        with: { tool: "cargo-llvm-cov,cargo-nextest" }
      - run: cargo llvm-cov nextest --workspace --lcov --output-path lcov.info --fail-under-lines 70

  mutants-pr:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with: { fetch-depth: 0 }
      - uses: dtolnay/rust-toolchain@stable
      - uses: taiki-e/install-action@v2
        with: { tool: "cargo-mutants,cargo-nextest" }
      - run: git diff origin/${{ github.base_ref }}.. > pr.diff
      - run: cargo mutants --no-shuffle -vV --in-diff pr.diff --test-tool=nextest
      - uses: actions/upload-artifact@v7
        if: always()
        with: { name: mutants.out, path: mutants.out }
```

Schedule-only jobs (nightly cron): full `cargo mutants`, long fuzzing runs, Kani proofs,
`cargo +nightly careful test`, sanitizer runs. Keep the PR path under ~15 minutes.

## 3. Gate summary

| Gate | Blocks merge when | Typical runtime |
|---|---|---|
| nextest + doctests | any failure (flaky = retried but reported) | minutes |
| Miri on crates with unsafe | any UB report | slow: scope to those crates |
| loom models | any failing interleaving | seconds to minutes |
| coverage floor | below agreed line coverage (ratchet upwards) | + build time |
| mutants in diff | new `missed` mutants in changed code | proportional to diff |
| fuzz smoke (ClusterFuzzLite `code-change` mode) | new crash | 5-10 min per target |
