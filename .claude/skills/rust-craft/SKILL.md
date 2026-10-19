---
name: rust-craft
description: "Rust expertise pack covering ownership and borrowing patterns, lifetimes, traits and generics, error handling with thiserror and anyhow, async with tokio, an unsafe and FFI audit checklist, performance idioms, cargo workspaces and features, clippy, miri, criterion, proptest and cargo-fuzz commands, and common pitfalls. Load when writing, reviewing, debugging, profiling or hardening Rust code."
when_to_use: "Any task touching .rs files, Cargo.toml, borrow-checker errors, async/tokio services, unsafe or FFI code, Rust performance work, or Rust CI gates."
---

# Rust craft

Baseline: stable Rust with **edition 2024** (Rust >= 1.85). Everything below works on stable unless
marked `nightly`. Verify crate APIs you are unsure of with `mcp__context7__resolve-library-id` then
`mcp__context7__query-docs` (tokio, serde, axum, sqlx move fast) before writing code against them.

Deep material:
[async and tokio](references/async-tokio.md) |
[unsafe and FFI audit](references/unsafe-ffi-audit.md) |
[tooling and command cheat-sheet](references/tooling-commands.md)

## 1. Orient in a repo (first five minutes)

```bash
rustc -V; cargo -V; cat rust-toolchain.toml 2>/dev/null       # pinned toolchain?
grep -nE '^(edition|rust-version|resolver)' Cargo.toml */Cargo.toml crates/*/Cargo.toml 2>/dev/null
cargo metadata --no-deps --format-version 1 | jq -r '.packages[].name'   # workspace members
grep -n '\[lints' -A12 Cargo.toml                                        # lint policy
grep -rn 'unsafe' --include=*.rs -l . | grep -v target | head             # unsafe surface
ls .cargo/config.toml deny.toml clippy.toml rustfmt.toml 2>/dev/null
```

Record: edition, MSRV (`rust-version`), async runtime, error crates, `unsafe` count, feature flags.
Never raise MSRV or edition as a side effect; it is a breaking change for library users.

## 2. The gate (what "done" means)

| Step | Command | Blocks merge when |
|---|---|---|
| Format | `cargo fmt --all -- --check` | any diff |
| Lint | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | any warning |
| Test | `cargo nextest run --workspace --all-features` then `cargo test --doc --workspace` | any failure (nextest skips doctests) |
| Features | `cargo hack check --feature-powerset --no-dev-deps --workspace` | a combination fails to build |
| Unsafe | `cargo +nightly miri test -p <crate-with-unsafe>` | any UB report |
| Supply chain | `cargo deny check` (advisories, bans, licenses, sources) | advisory or license violation |
| Public API (libs) | `cargo semver-checks check-release -p <crate>` | unintended breaking change |

Run the cheap rows first. For a single-crate change scope with `-p <crate>`.

## 3. Ownership: choose the signature first

| The function needs to | Take | Notes |
|---|---|---|
| read | `&T`, `&str`, `&[T]`, `&Path` | never `&String`, `&Vec<T>`, `&PathBuf` (clippy `ptr_arg`) |
| mutate in place | `&mut T` | |
| store or consume | `T` (owned) | caller decides whether to clone; no hidden clones inside |
| store, accept many string types | `impl Into<String>` | one allocation at most |
| maybe modify, usually not | `Cow<'_, str>` | return `Cow::Borrowed` on the fast path |
| iterate any collection | `impl IntoIterator<Item = T>` | |
| call back, not stored | `impl Fn(A) -> B` / `F: FnMut` | static dispatch |
| call back, stored heterogeneously | `Box<dyn Fn(A) -> B + Send + Sync>` | |

| Sharing need | Use |
|---|---|
| single owner, heap | `Box<T>` |
| shared, single thread | `Rc<T>`; mutate via `RefCell<T>` / `Cell<T>`; break cycles with `Weak` |
| shared across threads, immutable | `Arc<T>` (`Arc<str>`, `Arc<[T]>` for immutable buffers) |
| shared, mutable, short critical sections | `Arc<Mutex<T>>` (std or `parking_lot`) |
| read-mostly config swapped atomically | `arc_swap::ArcSwap<T>` |
| init-once global | `std::sync::LazyLock` / `OnceLock` (never `static mut`) |
| counters/flags | `AtomicU64` / `AtomicBool` (see memory ordering in the unsafe reference) |
| ownership transfer between tasks | channels (message passing beats shared state) |

### Borrow-checker error → fix

| Error | Typical cause | Fix (in order of preference) |
|---|---|---|
| E0382 use of moved value | value moved into call/closure, used after | borrow instead; restructure; clone deliberately if cheap |
| E0499 two `&mut` | two mutable paths into one struct/slice | split borrows: destructure fields, `split_at_mut`, `iter_mut`, indices |
| E0502 `&mut` while `&` live | reading then writing the same collection | finish the read first (collect keys, copy the small value), entry API |
| E0505 / E0506 move/assign while borrowed | reference outlives intended scope | shrink the borrow scope with a block; compute owned value first |
| E0507 move out of borrow | taking a field out of `&mut self` | `std::mem::take`, `Option::take`, `std::mem::replace` |
| E0597 / E0716 does not live long enough / temporary dropped | reference to a temporary or local | bind the temporary with `let`; return owned data |
| E0373 closure may outlive | `thread::spawn`/`tokio::spawn` capturing refs | `move` closure plus owned or `Arc` data; `std::thread::scope` for borrowed |
| E0277 `Send` not satisfied (async) | `Rc`, `RefCell`, std `MutexGuard` held across `.await` | drop it before `.await` (inner block), use `Arc`/tokio `Mutex` |
| "lifetime may not live long enough" | returned ref tied to wrong input | add explicit lifetime linking output to the right input |

Rule: `clone()` to silence the borrow checker is acceptable outside hot paths only when the
value is small or `Arc`; write `Arc::clone(&x)` so reviewers see it is a refcount bump.

## 4. Lifetimes

- Elision covers most signatures: one input reference → output gets its lifetime; `&self` methods
  → output gets `self`'s lifetime. Name lifetimes only when two inputs could feed the output.
- `T: 'static` means "owns all its data or borrows only statics", not "lives forever".
  `tokio::spawn` and `thread::spawn` require it; satisfy it with owned data or `Arc`.
- Structs holding references (`struct Parser<'a> { src: &'a str }`) are fine for short-lived views
  (parsers, iterators). For long-lived state hold owned data or indices into an arena.
- Self-referential structs: do not hand-roll with raw pointers. Use indices, `Arc`, or crates
  built for it (`ouroboros`, `self_cell`) after checking their soundness history.
- Edition 2024: return-position `impl Trait` captures **all** in-scope generic parameters and
  lifetimes by default. Restrict with precise capturing: `fn iter(&self) -> impl Iterator<Item = u32> + use<>`.
- Edition 2024 `if let` temporaries drop before the `else` branch, and tail-expression temporaries
  drop before locals; old code that relied on a guard living through `else` changes behavior.

## 5. Traits and generics

| Decision | Choose generics (`T: Trait`, `impl Trait`) | Choose `dyn Trait` |
|---|---|---|
| hot path, inlining matters | yes | no (vtable call, no inlining) |
| heterogeneous collection / plugin registry | no | `Vec<Box<dyn Trait>>` |
| compile time and binary size matter | no (monomorphization bloat, check `cargo llvm-lines`) | yes |
| trait has generic methods or returns `Self` | fine | not dyn-compatible unless `where Self: Sized` on those methods |
| hide implementation type from API | `impl Trait` in return position | `Box<dyn Trait>` |

- Associated type when each implementor has exactly one natural choice (`Iterator::Item`);
  generic parameter when one type implements the trait many ways (`From<T>`).
- Orphan rule: you can implement a trait for a type only if you own one of them. Wrap foreign
  types in a newtype (`struct Meters(f64);`) and derive what you need.
- Sealed traits for public traits users must not implement: `mod private { pub trait Sealed {} }`
  plus `pub trait Api: private::Sealed`.
- Blanket impls (`impl<T: Display> MyTrait for T`) are a semver commitment; add them before 1.0.
- Async fn in traits is stable but such traits are not dyn-compatible and callers cannot require
  `Send` futures. For public traits used with multithreaded runtimes, declare
  `fn fetch(&self) -> impl Future<Output = Result<Bytes>> + Send;` or generate a Send variant with
  `#[trait_variant::make(SendFetch: Send)]`. For `dyn` use, `async-trait` (boxes) is still correct.
- Prefer `#[derive(Debug, Clone, PartialEq, Eq, Hash)]` on public types when semantically valid
  (C-COMMON-TRAITS); add `Default` only with a meaningful default. Implement `Display` for user text.

## 6. Error handling

| Code kind | Crate | Shape |
|---|---|---|
| library | `thiserror` (2.x) | one `enum` per module or operation family, `#[non_exhaustive]` |
| binary / app glue | `anyhow` (or `eyre`) | `anyhow::Result<T>`, `.context(...)` at each layer boundary |
| FFI boundary | none | map to error codes; never unwind across `extern "C"` |
| truly impossible state | `unreachable!` / `expect("invariant: ...")` | message states the invariant, not "failed" |

```rust
#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum LoadError {
    #[error("config file {path} not found")]
    NotFound { path: std::path::PathBuf },
    #[error("reading {path}")]                       // do not repeat the source's text here
    Io { path: std::path::PathBuf, #[source] source: std::io::Error },
    #[error("invalid config")]
    Parse(#[from] toml::de::Error),
}
```

```rust
use anyhow::{bail, Context, Result};
fn main() -> Result<()> {
    let path = std::env::args().nth(1).context("usage: tool <config>")?;
    let cfg = load(&path).with_context(|| format!("loading {path}"))?;
    if cfg.workers == 0 { bail!("workers must be > 0"); }
    Ok(())
}
```

Rules:
- Display messages are lowercase, no trailing period, and do **not** include the source error's
  text (the chain printer `{:#}` / `{:?}` adds it; duplicating produces "x: x: x").
- No `unwrap()` in library code paths. Tests and examples may unwrap.
- `Box<dyn Error>` in public APIs must be `Box<dyn Error + Send + Sync + 'static>`.
- Do not `?` across a `tokio::spawn` boundary and forget the `JoinHandle`; a dropped handle loses
  the error. Collect with `JoinSet` and inspect each `Result<Result<T, E>, JoinError>`.

## 7. Async with tokio (summary; full rules in [async-tokio](references/async-tokio.md))

1. Never block a worker: no `std::fs`, blocking HTTP, `std::thread::sleep`, or CPU work longer
   than roughly 10-100 µs between `.await` points. Use `tokio::task::spawn_blocking` for blocking
   I/O and `rayon` (bridged with a oneshot) for CPU-bound batches.
2. Every spawned task has an owner: `JoinSet` or `tokio_util::task::TaskTracker` plus a
   `CancellationToken`. Detached `tokio::spawn` is a leak with lost errors.
3. Bounded channels only (`mpsc::channel(n)`); unbounded queues turn overload into OOM.
4. std `Mutex` is fine in async code if the guard never crosses `.await`; use `tokio::sync::Mutex`
   only when it must. Prefer message passing to an actor task for contended state.
5. Everything in `tokio::select!` must be cancel-safe or pinned outside the loop. `read_exact`,
   `read_to_end`, `write_all`, and `mpsc::Sender::send` are not cancel-safe.
6. Wrap every network call in `tokio::time::timeout`; propagate deadlines, not just timeouts.
7. Bounded fan-out: `futures::stream::iter(xs).map(f).buffer_unordered(16)` or `JoinSet` plus
   `Semaphore`.

## 8. Unsafe and FFI (summary; full checklist in [unsafe-ffi-audit](references/unsafe-ffi-audit.md))

- Every `unsafe` block carries a `// SAFETY:` comment proving each precondition; every
  `pub unsafe fn` has a `# Safety` doc section. Enforce with `clippy::undocumented_unsafe_blocks`.
- Keep unsafe in small modules behind safe APIs; the safe API must be sound for **all** inputs.
- Edition 2024: `unsafe extern "C" { ... }`, `#[unsafe(no_mangle)]`, `std::env::set_var` is unsafe,
  references to `static mut` are denied. Use `&raw const` / `&raw mut` for raw place pointers.
- Run Miri on every crate with unsafe: `cargo +nightly miri test`, then again with
  `MIRIFLAGS="-Zmiri-tree-borrows"`; add `-Zmiri-strict-provenance` for pointer/int casts.
- FFI: `#[repr(C)]` types only, `extern "C-unwind"` if foreign code may unwind through Rust,
  `catch_unwind` at every Rust callback invoked from C, `CStr`/`CString` for strings, never pass
  Rust-allocated memory to a foreign `free`.

## 9. Performance procedure

1. Benchmark first: criterion or divan bench with `std::hint::black_box`; save a baseline
   (`cargo bench -- --save-baseline before`).
2. Profile the release build with symbols: `[profile.profiling] inherits = "release"` plus
   `debug = true`, then `samply record --save-only -o .stack/out/<agent>/profile.json.gz
   target/profiling/app` (summarise the JSON with a script; plain `samply record` serves a browser
   UI and blocks) or, on Linux, `cargo flamegraph -o .stack/out/<agent>/flame.svg` (on macOS it
   uses dtrace and needs root: return it as an Open doubt).
3. Fix the top frame, re-run against the baseline (`cargo bench -- --baseline before`),
   keep changes that beat noise (criterion reports p < 0.05 and the change percent).

| Symptom in profile | Likely fix |
|---|---|
| `malloc`/`free`, `RawVec::grow` hot | `Vec::with_capacity`, reuse buffers with `clear()`, `SmallVec`/`arrayvec` for small N |
| `clone` / `to_string` / `format!` hot | borrow, `Cow`, `write!` into a reused `String`, `Arc<str>` for shared immutable text |
| `SipHash` (`hash_one`, `write`) hot | `rustc_hash::FxHashMap` or `ahash` when keys are not attacker-controlled |
| bounds checks in tight loops | iterate (`zip`, `chunks_exact`), re-slice once (`let s = &s[..n];`), assert lengths up front |
| `dyn` calls in inner loop | generics / enum dispatch |
| poor cache behavior | struct-of-arrays, `Vec<T>` over `Vec<Box<T>>` / `LinkedList`, shrink enum variants (`Box` the big one) |
| lock contention | shard the map, `parking_lot`, per-thread accumulation then merge |
| async overhead per item | batch work per task; avoid one task per tiny item |

Release profile for shipped binaries (measure each step; `panic = "abort"` changes semantics):

```toml
[profile.release]
lto = "fat"
codegen-units = 1
panic = "abort"          # only if nothing relies on catch_unwind
[profile.profiling]
inherits = "release"
debug = true
```

Then consider PGO (`cargo pgo`), `-C target-cpu=native` only for binaries that never leave the
build host's CPU family, and a global allocator (`mimalloc`) for allocation-heavy servers.
Size check for hot enums: `const _: () = assert!(std::mem::size_of::<Msg>() <= 32);`.

## 10. Cargo workspaces and features

```toml
# Cargo.toml (virtual workspace)
[workspace]
resolver = "3"                  # must be explicit in a virtual workspace; MSRV-aware
members = ["crates/*"]

[workspace.package]
edition = "2024"
rust-version = "1.85"
license = "MIT OR Apache-2.0"

[workspace.dependencies]
serde = { version = "1", features = ["derive"] }
tokio = { version = "1", default-features = false }

[workspace.lints.rust]
unsafe_op_in_unsafe_fn = "deny"
[workspace.lints.clippy]
all = { level = "warn", priority = -1 }
undocumented_unsafe_blocks = "deny"
unwrap_used = "warn"
```

Member crates: `edition.workspace = true`, `serde.workspace = true`, and `[lints] workspace = true`.

Feature rules:
- Features must be **additive**; never a feature that removes API. `no_std` crates use
  `default = ["std"]` with `#![cfg_attr(not(feature = "std"), no_std)]`.
- Optional dependencies use `dep:` (`json = ["dep:serde_json"]`); enable a dependency's feature
  only if it is already on with `serde?/derive` (weak dependency feature).
- Features unify across the dependency graph for a build; a crate that only compiles because a
  sibling enables a feature is a latent bug. `cargo hack --feature-powerset` catches it.
- Keep `default` features minimal in libraries; binaries opt in.

## 11. Testing beyond unit tests

```rust
// Property test (proptest): round-trip and invariants
use proptest::prelude::*;
proptest! {
    #[test]
    fn roundtrip(s in "\\PC{0,64}") {
        prop_assert_eq!(decode(&encode(&s)).unwrap(), s);
    }
}
```

```rust
// fuzz/fuzz_targets/parse.rs  (cargo +nightly fuzz add parse)
#![no_main]
use libfuzzer_sys::fuzz_target;
fuzz_target!(|data: &[u8]| {
    if let Ok(s) = std::str::from_utf8(data) { let _ = mycrate::parse(s); }  // must never panic
});
```

```bash
cargo +nightly fuzz run parse -- -max_total_time=300      # crashes land in fuzz/artifacts/parse/
cargo +nightly fuzz tmin parse fuzz/artifacts/parse/crash-<hash>
```

Turn every fuzz crash and proptest failure (proptest persists seeds in `proptest-regressions/`;
commit them) into a named regression test. Snapshot tests: `insta` with `cargo insta review`.

## 12. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| value wraps silently in release | integer overflow checks off in release | `checked_*`/`saturating_*`/`wrapping_*` explicitly, or `overflow-checks = true` |
| truncated numbers | `as` casts | `u32::try_from(x)?`; clippy `cast_possible_truncation` |
| runtime panic "already borrowed" | overlapping `RefCell::borrow_mut` | shorten borrows; restructure ownership |
| memory grows with `Rc`/`Arc` graphs | reference cycle | `Weak` back-pointers, arena + indices |
| async service stalls under load | blocking call on a worker thread | `spawn_blocking`; find long polls with runtime metrics (`Handle::current().metrics()`) or a scheduling-delay watchdog task (tokio-console is an interactive TUI: humans only) |
| task errors vanish | dropped `JoinHandle` | `JoinSet`, log or propagate each join result |
| deadlock in async code | std guard across `.await`, or lock-order inversion | scope guards; one lock order; actor task |
| snapshot test flaky | `HashMap` iteration order | `BTreeMap` or sort before asserting |
| destructors skipped | `std::process::exit` or `panic = "abort"` | return from `main`; flush explicitly |
| docs build fails on docs.rs | feature-gated items | `#[cfg_attr(docsrs, doc(cfg(feature = "x")))]`, `package.metadata.docs.rs` |
| `impl Trait` borrow errors after 2024 migration | new RPIT capture rules | `+ use<'a, T>` precise capturing |
| build differs CI vs local | unpinned toolchain, feature unification | `rust-toolchain.toml`, `--locked`, commit `Cargo.lock` for binaries |

## 13. Review checklist

- [ ] Signatures borrow by default; owned params only where stored; no `&String`/`&Vec`.
- [ ] No `unwrap`/`expect` in library paths without an invariant message; no `panic!` for input errors.
- [ ] Error types: library uses typed enums, binary adds context at boundaries; no duplicated messages.
- [ ] Every `unsafe` has `SAFETY:`; Miri passes; safe wrappers sound for all inputs.
- [ ] Async: no blocking calls, no guard across `.await`, bounded channels, timeouts, owned tasks.
- [ ] `select!` branches cancel-safe; long-lived futures pinned outside the loop.
- [ ] Public types derive the common traits; `#[non_exhaustive]` on growable enums/structs.
- [ ] Features additive and powerset-checked; MSRV unchanged or bumped deliberately.
- [ ] Hot paths benchmarked before/after with a saved baseline; no speculative micro-optimizations.
- [ ] `cargo deny check` clean; new dependencies justified (maintenance, unsafe, transitive count).

## 14. Worked example: lookup-or-insert that fights the borrow checker

Broken (rejected by the current borrow checker; the early return keeps `cache` borrowed):

```rust
fn get_or_load<'a>(cache: &'a mut HashMap<String, Data>, key: &str) -> &'a Data {
    if let Some(d) = cache.get(key) { return d; }      // E0502 on the insert below
    cache.insert(key.to_owned(), load(key));
    &cache[key]
}
```

Fixes, by trade-off:

```rust
// A: entry API (allocates the key String on every call, even on hits)
cache.entry(key.to_owned()).or_insert_with(|| load(key))

// B: two lookups, no allocation on hits (usually best for hot read paths)
if !cache.contains_key(key) { cache.insert(key.to_owned(), load(key)); }
&cache[key]
```

Pick B when hits dominate and keys are long; A when misses dominate or the code must stay
single-lookup. `hashbrown`'s `entry_ref` avoids both costs if the dependency is acceptable.

## 15. Worked example: bounded concurrent fetch with cancellation

```rust
use std::time::Duration;
use anyhow::Context;
use futures::{stream, StreamExt, TryStreamExt};
use tokio_util::sync::CancellationToken;

async fn fetch_all(client: &reqwest::Client, urls: Vec<String>, cancel: CancellationToken)
    -> anyhow::Result<Vec<bytes::Bytes>>
{
    let work = stream::iter(urls)
        .map(|u| async move {
            let resp = tokio::time::timeout(Duration::from_secs(10), client.get(&u).send())
                .await
                .with_context(|| format!("timeout fetching {u}"))??;
            Ok::<_, anyhow::Error>(resp.error_for_status()?.bytes().await?)
        })
        .buffered(16)                         // order-preserving, max 16 in flight
        .try_collect::<Vec<_>>();
    tokio::select! {
        r = work => r,
        _ = cancel.cancelled() => anyhow::bail!("cancelled"),
    }
}
```

Why it is right: concurrency is bounded (`buffered(16)`), each request has a timeout, the first
error short-circuits `try_collect` and drops the remaining in-flight futures, and cancellation
drops the whole stream (safe because nothing partial is written).

## Delegation hints

- Hot-path optimization with measurable targets: hand profiling evidence to `code-optimizer`.
- Unsafe-heavy or FFI-heavy diffs: request a second pass from `security-auditor`, giving the
  checklist path in the brief (`.claude/skills/rust-craft/references/unsafe-ffi-audit.md`, or
  `~/.claude/skills/rust-craft/references/unsafe-ffi-audit.md` after `bin/stack install --user`);
  do not paste it.
- Property and fuzz test design across modules: `tester`, giving the path
  `.claude/skills/rust-craft/SKILL.md` and the line range of section 11 (Testing beyond unit tests)
  in the brief.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `cargo-workspaces-features` | restructuring crates, adding features or preparing a Rust release |
| `rust-async-tokio` | debugging a tokio service bug, stall or leak, or when designing tasks, channels and shutdown |
| `rust-axum-services` | creating, extending, testing or debugging a Rust HTTP or gRPC service |
| `rust-error-handling` | adding fallible APIs, reviewing error types, or fixing lost or duplicated error messages |
| `rust-ffi-bindings` | calling C or C++ from Rust, exposing Rust to another language, or shipping a Rust-backed Python wheel or npm package |
| `rust-ownership-lifetimes` | a borrow or lifetime error blocks a build, or when choosing ownership for a new API |
| `rust-performance` | a Rust hot path, allocation rate, binary size or build time needs measured improvement |
| `rust-testing-fuzzing` | designing a Rust test suite, hardening a parser, or chasing a flaky or concurrency bug |
| `rust-traits-generics` | designing or reviewing a Rust public API or trait hierarchy |
| `rust-unsafe-soundness` | writing, reviewing or debugging any unsafe block, raw-pointer code or lock-free structure |
