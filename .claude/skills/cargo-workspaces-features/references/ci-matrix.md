# CI matrix template (GitHub Actions)

Action majors current as of October 2026: `actions/checkout@v7`, `dtolnay/rust-toolchain`
(branch per channel or version), `Swatinem/rust-cache@v2`, `taiki-e/install-action@v2`,
`EmbarkStudios/cargo-deny-action@v2`, `obi1kenobi/cargo-semver-checks-action@v2`. Adapt the
shape to other CI systems: the commands are the contract.

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]
env:
  CARGO_TERM_COLOR: always
  RUSTFLAGS: -D warnings            # also fails on rustc warnings outside clippy
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@stable
        with: { components: "rustfmt, clippy" }
      - uses: Swatinem/rust-cache@v2
      - run: cargo fmt --all -- --check
      - run: cargo clippy --workspace --all-targets --all-features --locked -- -D warnings

  test:
    needs: lint
    strategy:
      fail-fast: false
      matrix: { os: [ubuntu-latest, macos-latest, windows-latest] }
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - uses: taiki-e/install-action@v2
        with: { tool: cargo-nextest }
      - run: cargo nextest run --workspace --all-features --locked
      - run: cargo test --doc --workspace --all-features --locked

  features:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - uses: taiki-e/install-action@v2
        with: { tool: cargo-hack }
      - run: cargo hack check --feature-powerset --depth 2 --no-dev-deps --workspace
      - run: cargo hack check --each-feature --all-targets --workspace   # with dev-deps (tests compile per feature)

  msrv:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@1.85      # == workspace.package.rust-version
      - uses: Swatinem/rust-cache@v2
      - run: cargo +1.85 check --workspace --all-features --locked   # explicit: beats rust-toolchain.toml

  miri:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: dtolnay/rust-toolchain@nightly
        with: { components: miri }
      - run: cargo miri setup
      - run: cargo miri test -p appcore           # crates containing unsafe only

  deny:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: EmbarkStudios/cargo-deny-action@v2
        with: { command: check advisories bans licenses sources }

  semver:
    if: github.event_name == 'pull_request' && startsWith(github.head_ref, 'release-plz-')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: obi1kenobi/cargo-semver-checks-action@v2
```

Notes:
- A checked-in `rust-toolchain.toml` takes precedence over rustup's default toolchain, which is
  what the setup action usually sets; jobs that must use another toolchain (MSRV, nightly) should
  say so explicitly (`cargo +1.85 ...` or `RUSTUP_TOOLCHAIN=1.85`).
- `--locked` everywhere: a stale `Cargo.lock` must fail CI, not silently update.
- Cargo 1.99 disables incremental compilation when `CI` is set; rust-cache stores
  `~/.cargo/registry` and `target/` keyed by `Cargo.lock` and the toolchain.
- For many workspace members, split heavy jobs with `cargo hack --partition 1/4` or nextest
  `--partition count:1/4`.
- Schedule (cron) jobs: `cargo update` + full test (catches upstream breakage early), full
  mutation testing, long fuzzing, `cargo +nightly udeps`.

Single-crate repositories use the same jobs with `-p` removed and `--workspace` kept (harmless).
