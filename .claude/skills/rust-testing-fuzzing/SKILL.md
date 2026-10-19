---
name: rust-testing-fuzzing
description: "Rust verification beyond unit tests. Covers test layout, nextest profiles and doctests, proptest properties and state machines, cargo-fuzz with arbitrary, insta snapshots, loom and shuttle concurrency checks, tokio paused time, Miri, cargo-careful and Kani in CI, cargo-mutants, llvm-cov coverage and test doubles. Load when designing a Rust test suite, hardening a parser, or chasing a flaky or concurrency bug."
when_to_use: "tests/ or #[cfg(test)] code, .config/nextest.toml, proptest!/prop_compose!, proptest-regressions files, fuzz/fuzz_targets/*.rs, *.snap files, cfg(loom), #[kani::proof], mutants.out/, lcov.info; flaky or order-dependent tests, 'minimal failing input', fuzz crash artifacts, Miri UB reports in CI, untested logic found by mutation testing, coverage gates."
---

# Rust testing, property testing and fuzzing

Verified October 2026: Rust 1.99, cargo-nextest 0.9.x, proptest 1.12 (+ proptest-state-machine
0.9), cargo-fuzz 0.13 / libfuzzer-sys 0.4 / arbitrary 1.x, insta 1.49, loom 0.7, shuttle 0.9,
cargo-mutants 27, cargo-llvm-cov 0.9, Kani 0.68.

Deep material: [nextest config and CI jobs](references/nextest-and-ci.md) |
[fuzzing playbook](references/fuzzing.md) |
[loom, shuttle, Kani and test doubles](references/concurrency-and-doubles.md)

## 1. Layout

| Kind | Where | Sees | Use for |
|---|---|---|---|
| unit | `#[cfg(test)] mod tests` in the file | private items | invariants of one module |
| integration | `tests/*.rs` (each file is its own crate) | public API only | user-visible behaviour; shared helpers in `tests/common/mod.rs` (not `tests/common.rs`, which would become a test crate) |
| doctests | `///` examples | public API | executable docs; `no_run`, `ignore`, `should_panic`, `compile_fail`; hide setup with `# ` lines |
| benches/examples | `benches/`, `examples/` | public API | `cargo test --examples` keeps examples compiling |

- Edition 2024 compiles a crate's doctests into one binary (each still runs in its own process);
  examples that cannot be merged (crate-level `#![...]` attributes, reliance on line numbers or
  `module_path!`) take the `standalone_crate` tag; `compile_fail` tests are never merged.
- Dev-dependency hygiene: test-only crates go in `[dev-dependencies]`; they never reach users,
  but they unify features in `cargo test` (a library can pass tests yet fail to build for users;
  check with `cargo hack check --no-dev-deps`, see `cargo-workspaces-features`).
- Many integration files means many link steps: group them as modules of one `tests/it/main.rs`
  when link time dominates.

## 2. nextest and doctests

```bash
cargo nextest run --workspace --all-features         # process per test, parallel, retries
cargo test --doc --workspace                         # nextest does not run doctests
cargo nextest run -p crate name_substring --no-capture
cargo nextest run --profile ci --partition count:1/4  # sharded CI
```

`.config/nextest.toml` essentials (full file in [nextest-and-ci](references/nextest-and-ci.md)):

```toml
[profile.default]
slow-timeout = { period = "60s", terminate-after = 2 }   # kill after 120 s

[profile.ci]
retries = 2              # report flakes; fix them, do not hide them
fail-fast = false
[profile.ci.junit]
path = "junit.xml"

[test-groups]
serial-db = { max-threads = 1 }

[[profile.default.overrides]]
filter = 'test(/^db_/) | package(storage)'
test-group = 'serial-db'
```

Process-per-test isolates global state and panics; it also means `static` caches are rebuilt
per test, so heavy fixtures belong in files or containers, not lazies.

## 3. proptest

```rust
use proptest::prelude::*;
use proptest::collection::btree_map;

prop_compose! {
    fn config()(root in btree_map("[a-z][a-z0-9_]{0,8}", "\\PC{0,16}", 0..4),
                sections in btree_map("[a-z]{1,6}", btree_map("[a-z][a-z0-9_]{0,8}", "\\PC{0,16}", 0..4), 0..3))
                -> Config { Config { root, sections } }
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(512))]
    #[test]
    fn render_then_parse_is_identity(cfg in config()) {
        prop_assert_eq!(parse(&render(&cfg)), Ok(cfg));
    }
}
```

| Need | Tool |
|---|---|
| alternatives | `prop_oneof![3 => small(), 1 => huge()]` (weights) |
| derived structure | `prop_compose!`, `.prop_map`, `.prop_flat_map` (dependent sizes) |
| filtering | `prop_assume!` / `.prop_filter` sparingly: too many rejects aborts the test |
| more cases | `PROPTEST_CASES=10000 cargo test -p crate prop_` (default 256) |
| reproducibility | failures persist seeds: `proptest-regressions/<file>.txt` for tests under `src/`; `tests/<file>.proptest-regressions` for integration tests. Commit them. |
| stateful APIs | proptest-state-machine: `ReferenceStateMachine` (`init_state`, `transitions`, `apply`, optional `preconditions`) models the system; `StateMachineTest` (`init_test`, `apply`, `check_invariants`) drives the real one; `prop_state_machine! { #[test] fn run(sequential 1..30 => MyTest); }` |

Property shapes that find bugs: round trip (`decode(encode(x)) == x`), oracle (fast impl ==
simple impl), invariants (sorted, no duplicates, len preserved), idempotence
(`normalize(normalize(x)) == normalize(x)`), "never panics" on arbitrary input.

## 4. cargo-fuzz

```bash
cargo install cargo-fuzz
cargo +nightly fuzz init && cargo +nightly fuzz add roundtrip
cargo +nightly fuzz run roundtrip -- -max_total_time=300 -dict=fuzz/conf.dict -jobs=8
cargo +nightly fuzz tmin roundtrip fuzz/artifacts/roundtrip/crash-<sha1>   # minimise
cargo +nightly fuzz fmt roundtrip <input>          # Debug-print the decoded (Arbitrary) input
cargo +nightly fuzz cmin roundtrip                 # shrink the corpus
cargo +nightly fuzz coverage roundtrip             # then llvm-cov show for uncovered branches
```

- Builds are optimised with debug assertions on by default (`-O` drops them, `-D` is unoptimised);
  ASan is the default sanitizer (`-s none` for pure safe code runs faster).
- Structured inputs: `#[derive(arbitrary::Arbitrary)]` on an input struct and
  `fuzz_target!(|input: MyInput| ...)`; reject unrepresentable values early with `return`.
- Dictionaries list format tokens (`open="["`, `eq="="`) and lift coverage of text formats fast.
- Corpus lives in `fuzz/corpus/<target>/`, crashes in `fuzz/artifacts/<target>/`. Seed the corpus
  with real files; cache it in CI.
- CI: ClusterFuzzLite (`.clusterfuzzlite/` with `project.yaml` `language: rust`, a Dockerfile
  `FROM gcr.io/oss-fuzz-base/base-builder-rust`, `build.sh` running `cargo fuzz build -O`) or
  OSS-Fuzz for open source; afl.rs (`cargo afl build`, `cargo afl fuzz`) as a second engine.
- Every crash becomes a named regression test before the fix lands.
Details: [fuzzing](references/fuzzing.md).

## 5. insta snapshots

```rust
insta::assert_snapshot!(rendered_text);
insta::assert_debug_snapshot!(parse("[a]\nk=v\n").unwrap());
insta::assert_json_snapshot!(response_body, { ".id" => "[id]", ".created_at" => "[ts]" });
```

- Features: `json`/`yaml` for the serde formats, `redactions` for selectors (`.field`, `.*`,
  `[]`), plus `insta::sorted_redaction()` and `insta::dynamic_redaction(...)`.
- Review: `cargo insta test --review` or `cargo insta review`; `--unreferenced=reject` in CI
  catches stale `.snap` files.
- `INSTA_UPDATE` defaults to `auto`: writes `.snap.new` locally, writes nothing when `CI` is set
  (set `INSTA_UPDATE=no` explicitly on CI systems that do not export `CI`).
- Determinism: `BTreeMap` or sort before snapshotting; redact ids, timestamps, paths.

## 6. Concurrency checking

| Tool | Finds | Cost |
|---|---|---|
| loom 0.7 | every interleaving (bounded) of a small test using `loom::sync`/`loom::thread`; memory-ordering bugs | exponential: 2-3 threads, few ops |
| shuttle 0.9 | randomized (`check_random`) or PCT (`check_pct`) schedules of larger tests; `replay` a failing schedule | probabilistic, scales further |
| tokio paused time | timer logic without real sleeps: `#[tokio::test(start_paused = true)]` (needs tokio `test-util`), `tokio::time::advance` | cheap |
| Miri `-Zmiri-many-seeds` | data races and weak-memory effects in unsafe code | slow |
| turmoil | network partitions and latency in simulated distributed tests | moderate |

loom setup: `[target.'cfg(loom)'.dev-dependencies] loom = "0.7"`, declare the cfg
(`[lints.rust] unexpected_cfgs = { level = "warn", check-cfg = ['cfg(loom)'] }`), swap imports
behind `#[cfg(loom)]`, run `RUSTFLAGS="--cfg loom" cargo test --release --lib loom_`. Bound the
search with `LOOM_MAX_PREEMPTIONS=2`; `LOOM_CHECKPOINT_FILE` resumes long runs; `LOOM_LOG=trace`
explains a failure. Real run: a counter doing `load` then `store` passed its plain unit test but
loom failed with `left: 1, right: 2` on two threads; `fetch_add` made the model pass.

## 7. Unsafe verification in CI

| Job | Command | Notes |
|---|---|---|
| Miri | `cargo +nightly miri nextest run -p crate` or `cargo +nightly miri test` | add a `MIRIFLAGS="-Zmiri-tree-borrows"` pass; `-Zmiri-strict-provenance` for pointer/int casts; mark slow tests `#[cfg_attr(miri, ignore)]`, shrink sizes with `cfg!(miri)` |
| cargo-careful | `cargo +nightly careful test` | std built with debug assertions: catches unchecked preconditions without Miri's slowness |
| sanitizers | `RUSTFLAGS=-Zsanitizer=address cargo +nightly test --target x86_64-unknown-linux-gnu` | also `thread` (needs `-Zbuild-std`); covers FFI code Miri cannot run |
| Kani | `cargo kani --harness parse_u64_never_panics` | bounded proofs for small kernels: `#[kani::proof]`, `#[kani::unwind(N)]`, `kani::any()`, `kani::assume()` |

Miri cannot execute foreign code or inline asm; test the Rust side against a pure-Rust fake.
Generic unsafe review procedure: `rust-unsafe-soundness`.

## 8. Mutation testing

```bash
cargo install --locked cargo-mutants
cargo mutants --test-tool=nextest -j 4                 # whole crate, in parallel
git diff origin/main... > pr.diff && cargo mutants --in-diff pr.diff   # PR scope only
cargo mutants --file src/parser.rs                      # scope to one file (glob allowed)
```

Results in `mutants.out/`: `missed.txt` (logic no test checks: write the test), `caught.txt`,
`timeout.txt`, `unviable.txt` (did not compile). Mutants caught only by doctests show as missed
under nextest. Skip intentional no-ops with `#[mutants::skip]`. Run nightly or per PR diff;
whole-crate runs are long.

## 9. Coverage

```bash
cargo llvm-cov nextest --workspace --lcov --output-path lcov.info
cargo llvm-cov nextest --html --open                    # target/llvm-cov/html
cargo llvm-cov nextest --ignore-filename-regex '(generated|pb)\.rs$' --fail-under-lines 80
```

Exclude generated code by filename regex, or per item with
`#[cfg_attr(coverage_nightly, coverage(off))]` (+ `#![cfg_attr(coverage_nightly, feature(coverage_attribute))]`).
Coverage proves code ran, not that it was checked: pair with mutation testing.

## 10. Test doubles

| Dependency | Double |
|---|---|
| your own trait | hand-written fake struct (preferred: no macros, real behaviour) |
| trait you cannot fake by hand | mockall `#[automock]`: `let mut m = MockStore::new(); m.expect_get().with(eq(7)).times(1).returning(\|_\| Ok(None));` |
| HTTP API | wiremock (async: `MockServer::start().await`, `Mock::given(method("GET")).and(path("/v1/x")).respond_with(ResponseTemplate::new(200)).mount(&server).await`), httpmock (sync and async) |
| PostgreSQL/MySQL | `#[sqlx::test]` (fresh database per test from `DATABASE_URL`, applies `migrations`), testcontainers (`testcontainers-modules` `Postgres::default().start().await`) |
| time | tokio paused time, or inject a `Clock` trait |
| filesystem | `tempfile::tempdir()`; never write into the repo |

## 11. Worked example: hardening a config parser

Format: `key=value` lines, `[section]` headers, `#` comments, `\\` and `\n` escapes in values.
`parse(&str) -> Result<Config, ParseError>`, `render(&Config) -> String`, `Config` holds
`BTreeMap`s (deterministic equality and output).

**Step 1: round-trip property** (section 3 code, in `tests/roundtrip.rs`). Real run:

```text
proptest: Saving this and future failures in .../tests/roundtrip.proptest-regressions
Test failed: assertion failed: `(left == right)`
  left: `Err(BadEscape { line: 2 })`,
 right: `Ok(Config { root: {}, sections: {"a": {"a": "\\"}} })`
minimal failing input: cfg = Config { root: {}, sections: { "a": { "a": "\\" } } }
	successes: 2
```

Shrinking reduced it to one backslash: `render` escaped `\n` but not `\` itself, so `a=\` ended
in a dangling escape. Fix: `v.replace('\\', "\\\\").replace('\n', "\\n")` (backslash first).
Commit `tests/roundtrip.proptest-regressions` (it replays the seed first on every run).

**Step 2: fuzz target** for arbitrary input (`fuzz/fuzz_targets/roundtrip.rs`):

```rust
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let Ok(text) = std::str::from_utf8(data) else { return };
    if let Ok(cfg) = confparse::parse(text) {            // must never panic
        let again = confparse::parse(&confparse::render(&cfg)).expect("rendered config re-parses");
        assert_eq!(again, cfg);
    }
});
```

Run it with `cargo +nightly fuzz run roundtrip -- -max_total_time=300 -dict=fuzz/conf.dict` and
`tmin` any artifact (this target needs nightly and was not run for this skill). The panic class
it exposes was reproduced on stable with a "never panics" property over a small alphabet
(`s in "[\\[\\]a-z=#\\\\ \n]{0,12}"`); real output: `panicked at src/lib.rs:29:32: attempt to
subtract with overflow`, `minimal failing input: s = "[\n"`, caused by `&rest[..rest.len() - 1]`
assuming a closing `]` (fuzz builds keep debug assertions, so the fuzzer reports the same panic).

**Step 3: fix and pin with named regression tests** (`tests/regressions.rs`):

```rust
/// Found by the never-panics property (minimised input "[\n"): a lone '[' underflowed `len() - 1`.
#[test]
fn regression_lone_open_bracket_is_an_error_not_a_panic() {
    assert_eq!(parse("["), Err(ParseError::BadSection { line: 1 }));
    assert_eq!(parse("[\n"), Err(ParseError::BadSection { line: 1 }));
}

/// Found by the round-trip property: a value of a single backslash did not survive render.
#[test]
fn regression_backslash_value_round_trips() {
    let cfg = parse("[a]\na=\\\\\n").unwrap();
    assert_eq!(cfg.sections["a"]["a"], "\\");
    assert_eq!(parse(&render(&cfg)), Ok(cfg));
}
```

Fix: `let Some(name) = rest.trim_end().strip_suffix(']') else { return Err(ParseError::BadSection { line: n }) };`.
Final run: all suites green, and `PROPTEST_CASES=20000 cargo test --release` passed both
properties in under a second. Keep the fuzz target running nightly in CI with the corpus cached;
copy each new crash file into `tests/fuzz_regressions/` and assert it parses without panicking.

## 12. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| test passes alone, fails in the suite (or the reverse) | shared global state, env vars, current dir, ports | nextest (process per test), unique temp dirs, port 0, test groups for real shared resources |
| snapshot differs between runs | `HashMap` order, timestamps, absolute paths | `BTreeMap`/sort, redactions |
| proptest "Too many local rejects" | filters reject most inputs | generate valid values directly (`prop_map`, constrained regex) |
| property passes but bug ships | generator never produces the bad shape | add edge-biased strategies (`prop_oneof!` with empty, max, unicode, escapes) |
| fuzzing finds nothing for hours | parser rejects random bytes at the first check | dictionary, structured `Arbitrary` input, seed corpus |
| loom test never finishes | too many threads/ops | 2 threads, fewer operations, `LOOM_MAX_PREEMPTIONS=2` |
| "unexpected cfg condition name: loom" warnings | cfg not declared | `check-cfg = ['cfg(loom)']` in `[lints.rust]` |
| Miri job times out | big loops and inputs | `cfg!(miri)` sizes, `#[cfg_attr(miri, ignore)]` for pure-perf tests |
| flaky test "fixed" by retries | real race or timing assumption | keep `retries` only to report flakes; fix with paused time or synchronisation |
| coverage high, bugs remain | assertions too weak | cargo-mutants `missed.txt` |
| doctests silently not run in CI | only `cargo nextest run` | add `cargo test --doc` |

Related: `rust-unsafe-soundness`, `rust-async-tokio`, `rust-error-handling`, `rust-performance`,
`cargo-workspaces-features`, `rust-axum-services`, hub `rust-craft`.
