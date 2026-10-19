# Rust tooling and command cheat-sheet

Install helpers once per machine: `cargo install --locked cargo-nextest cargo-hack cargo-deny
cargo-semver-checks cargo-llvm-cov cargo-fuzz cargo-expand cargo-show-asm cargo-bloat
cargo-llvm-lines cargo-machete samply flamegraph` (or `cargo binstall` for prebuilt binaries).

## Build and check

| Goal | Command |
|---|---|
| fast type check | `cargo check --workspace --all-targets` |
| reproducible build (lockfile enforced) | `cargo build --locked --release` |
| one crate, one feature set | `cargo check -p core --no-default-features --features alloc` |
| all feature combinations | `cargo hack check --feature-powerset --no-dev-deps` (add `--depth 2` for large sets) |
| MSRV verification | `cargo hack check --rust-version --workspace` or `cargo +1.85 check` |
| why is this dependency here | `cargo tree -i <crate> -e features` |
| duplicate versions | `cargo tree -d` |
| unused dependencies | `cargo machete` (fast, heuristic) or `cargo +nightly udeps` |
| expand macros | `cargo expand -p crate path::to::module` |
| emitted assembly of a function | `cargo asm -p crate --lib crate::module::func` |
| binary size by crate/function | `cargo bloat --release --crates` / `-n 30` |
| monomorphization bloat | `cargo llvm-lines --release | head -30` |
| build timing | `cargo build --timings` (HTML report in `target/cargo-timings/`) |

## Lint and format

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo clippy --fix --allow-dirty -p crate          # apply machine-applicable suggestions
cargo clippy -- -W clippy::pedantic                # one-off survey, do not gate on it blindly
```

Useful non-default clippy lints to enable per workspace (in `[workspace.lints.clippy]`):
`undocumented_unsafe_blocks`, `unwrap_used` (warn), `expect_used` (warn in libs),
`cast_possible_truncation`, `cast_sign_loss`, `large_futures`, `missing_errors_doc` (libs),
`dbg_macro`, `todo`, `print_stdout` (libs). Allow locally with `#[expect(clippy::lint, reason = "...")]`
(the `expect` attribute warns if the lint stops firing, keeping suppressions honest).

## Test

| Goal | Command |
|---|---|
| all tests, fast runner | `cargo nextest run --workspace --all-features` |
| doctests (nextest does not run them) | `cargo test --doc --workspace` |
| one test, show output | `cargo nextest run -p crate test_name --no-capture` |
| retries for known-flaky integration tests | `cargo nextest run --retries 2` (fix the flake, then remove) |
| coverage | `cargo llvm-cov nextest --workspace --lcov --output-path lcov.info` |
| HTML coverage | `cargo llvm-cov --open` |
| snapshot review | `cargo insta test --review` |
| property tests with more cases | `PROPTEST_CASES=10000 cargo test -p crate prop_` |
| Miri | `cargo +nightly miri test -p crate` |
| fuzz | `cargo +nightly fuzz run target -- -max_total_time=600 -jobs=8` |
| fuzz coverage | `cargo +nightly fuzz coverage target` then `llvm-cov show` |
| minimize corpus | `cargo +nightly fuzz cmin target` |

## Benchmark

criterion setup:

```toml
[dev-dependencies]
criterion = { version = "0.8", features = ["html_reports"] }   # API changed since 0.5: check with context7
[[bench]]
name = "parse"
harness = false
```

```rust
use criterion::{criterion_group, criterion_main, Criterion, BenchmarkId, Throughput};
use std::hint::black_box;

fn bench(c: &mut Criterion) {
    let mut g = c.benchmark_group("parse");
    for size in [1_000, 100_000] {
        let input = make_input(size);
        g.throughput(Throughput::Bytes(input.len() as u64));
        g.bench_with_input(BenchmarkId::from_parameter(size), &input, |b, i| {
            b.iter(|| parse(black_box(i)))
        });
    }
    g.finish();
}
criterion_group!(benches, bench);
criterion_main!(benches);
```

```bash
cargo bench --bench parse -- --save-baseline main     # on the base commit
cargo bench --bench parse -- --baseline main          # on the change; reports % and p-value
```

Alternatives: `divan` (attribute-based, allocation counting with `divan::AllocProfiler`),
`gungraun` (formerly `iai-callgrind`; instruction counts, stable in noisy CI). Pin CPU frequency or use instruction
counts in CI; wall-clock benchmarks on shared runners have 5-10% noise.

## Profile

| Question | Tool |
|---|---|
| where does CPU time go | `samply record --save-only -o profile.json.gz ./target/profiling/app args` (without `--save-only` it serves a browser UI and blocks); `cargo flamegraph --profile profiling --bin app -o flame.svg` (perf on Linux; dtrace on macOS needs root: Open doubt) |
| heap allocations by site | `dhat` crate (`#[global_allocator] static A: dhat::Alloc`) or `heaptrack` (Linux) |
| allocation counts in tests | `divan::AllocProfiler`, or a counting global allocator in a test binary |
| async task stalls | runtime metrics / scheduling-delay watchdog (agents); `tokio-console` (interactive TUI, humans) |
| instruction-level | `perf annotate`, `cargo asm`, `llvm-mca` on hot loops |
| compile times | `cargo build --timings`, `-Zself-profile` (nightly) |

Always profile `--release` (or a `profiling` profile inheriting release with `debug = true`);
debug builds have different hotspots.

## Supply chain and release

```bash
cargo deny init && cargo deny check           # advisories, licenses, bans, sources
cargo audit                                   # RustSec advisories only
cargo semver-checks check-release -p crate    # before publishing a library
cargo publish --dry-run -p crate
cargo vet                                     # if the org uses audited-dependency policies
```

`deny.toml` essentials: `[advisories] yanked = "deny"`, `[licenses] allow = ["MIT", "Apache-2.0", ...]`,
`[bans] multiple-versions = "warn"`, `[sources] unknown-registry = "deny"`, `unknown-git = "deny"`.

## Toolchain pinning

```toml
# rust-toolchain.toml
[toolchain]
channel = "1.89"                         # pin for apps; libraries pin MSRV in CI instead
components = ["rustfmt", "clippy"]
```

Nightly-only tools (miri, fuzz, udeps, sanitizers) run with `cargo +nightly ...` and never become
a build requirement for the main crate.

## CI matrix template (GitHub Actions shape, adapt to the CI in use)

1. `fmt` + `clippy -D warnings` (stable).
2. `nextest` + doctests on Linux, macOS, Windows if the crate claims them.
3. MSRV job: `cargo hack check --rust-version`.
4. Feature powerset job (`cargo hack`), `--no-default-features` build for `no_std` crates.
5. Miri job for crates with `unsafe`.
6. `cargo deny check`.
7. Optional: coverage upload, `semver-checks` on release branches, nightly fuzz job with a
   persisted corpus (cache `fuzz/corpus`).
