---
name: rust-error-handling
description: "Rust error design. Covers thiserror 2 enums for libraries, anyhow or eyre context for binaries, Display and source-chain rules, error size, panics vs Result and panic policy, errors across task, FFI and HTTP boundaries, logging once with tracing, testing rendered errors, and migration off unwrap. Load when adding fallible APIs, reviewing error types, or fixing lost or duplicated error messages."
when_to_use: "Writing or reviewing Result-returning Rust code: thiserror or anyhow in Cargo.toml, 'called `Result::unwrap()` on an `Err` value' panics, messages printed twice ('x: x: x'), lost errors from spawned tasks, clippy result_large_err, unwrap_used or expect_used warnings, axum handlers returning errors, extern \"C\" functions that may panic, or snapshot tests of error output."
---

# Rust error handling

Baseline: stable Rust, edition 2024, `thiserror` 2.x, `anyhow` 1.x (2.0.21 and 1.0.104 in October
2026). All terminal output below was produced by running the code on rustc 1.99.1.

## 1. Decide the shape first

| Code kind | Error type | Shape |
|---|---|---|
| library crate or module with callers that branch on failures | `thiserror` enum, `#[non_exhaustive]`, one per operation family (`LoadError`, `QueryError`) | variants carry the data needed to act (path, id, field) |
| binary, CLI, service glue, tests | `anyhow::Result<T>` (or `eyre::Result<T>` with `color-eyre` for colored reports) | `.context(..)` / `.with_context(\|\| ..)` at every layer boundary |
| FFI boundary (`extern "C"`) | integer codes or an out-param error struct | never unwind across it (section 5) |
| HTTP or RPC boundary | an `AppError` that maps to status codes | internal detail logged, never sent (section 7) |
| impossible state (a bug if reached) | `unreachable!("..")` or `.expect("invariant: ..")` | the message states the invariant, not "failed" |
| caller input | always `Result` | never `panic!` on input |

One error enum per crate that every function returns becomes a grab bag where no caller can tell
which variants are possible; split by operation family instead. `Box<dyn Error>` in public APIs
must be `Box<dyn Error + Send + Sync + 'static>` so it can cross threads and be downcast.

## 2. thiserror 2 template

```rust
use std::{io, path::PathBuf};

#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum LoadError {
    #[error("reading {path}")]                       // context only; PathBuf fields render via .display()
    Read { path: PathBuf, #[source] source: io::Error },
    #[error("parsing {path}")]
    Parse { path: PathBuf, #[source] source: Box<toml::de::Error> },   // boxed: 88-byte error
    #[error("invalid value for `{field}`: {reason}")]
    Invalid { field: &'static str, reason: String },
    #[error(transparent)]                            // forwards Display and source() unchanged
    Other(#[from] anyhow::Error),
}
```

| Attribute | Effect | Use when |
|---|---|---|
| `#[error("..{field}..")]` | generates `Display`; fields by name, tuple fields as `{0}` | every variant |
| `#[source]` (or a field named `source`) | `Error::source()` returns it | wrapping a lower error with added context |
| `#[from]` | `#[source]` plus `impl From<Inner> for LoadError`, so `?` converts | the variant adds no context worth keeping (one call site, obvious meaning) |
| `#[error(transparent)]` | `Display` and `source()` delegate to the single field | opaque passthrough, `Other(anyhow::Error)` |

Leave `#[from]` off when the variant should carry context: with `#[from] io::Error` every `?` on
any I/O call converts silently and you lose which file failed. Use
`.map_err(|source| LoadError::Read { path: path.to_owned(), source })` instead.

Size: `Result<T, E>` is at least as big as `E`, and every `?` moves it. Measured: the enum above is
40 bytes; with `toml::de::Error` unboxed it is 112 bytes; `anyhow::Error` is 8 bytes. clippy
`result_large_err` (perf group, warn by default) fires when the `Err` type reaches
`large-error-threshold` (default 128 bytes; configurable in `clippy.toml`): "the `Err`-variant
returned from this function is very large ... the largest variant contains at least 136 bytes".
Fix by boxing the large field or the whole error (`Box<LoadErrorInner>`).

## 3. Message rules

- Lowercase start, no trailing period: messages are chained with `: `.
- Describe what this layer was doing ("reading /etc/app.toml"); never repeat the source's text.
  Writing `#[error("reading {path}: {source}")]` prints the I/O text twice once a chain printer
  walks `source()`: "reading app.toml: No such file or directory (os error 2): No such file or
  directory (os error 2)".
- Print chains with the right formatter:

| Value | `{}` | `{:#}` | `{:?}` |
|---|---|---|---|
| `anyhow::Error` | outermost context only | whole chain on one line, `: `-separated | multi-line report with `Caused by:` (what `main` prints) |
| `thiserror` enum | this layer only | same as `{}` | derived `Debug` struct dump |

For a plain `&dyn Error`, walk the chain yourself:

```rust
let mut cur: Option<&(dyn std::error::Error + 'static)> = Some(&err);
while let Some(e) = cur { eprintln!("  caused by: {e}"); cur = e.source(); }
```

## 4. Crossing layers

| Situation | Do |
|---|---|
| lower error, no extra context needed | `#[from]` and `?` |
| lower error, context needed (path, id, operation) | `map_err(\|source\| Variant { ctx, source })?` |
| application code | `.with_context(\|\| format!("loading config from {path}"))?` (lazy: the closure runs only on error) |
| `Option` to error | `opt.context("PORT not set")?` (anyhow), `opt.ok_or(MyError::Missing("PORT"))?` |
| callers must branch on a cause without matching every variant | a stable `kind()` accessor returning a small `#[non_exhaustive]` `Copy` enum |
| foreign `io::Error` | map `source.kind()`: `NotFound`, `PermissionDenied`, `TimedOut`, `ConnectionRefused`, `AlreadyExists` ... |

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum LoadErrorKind { NotFound, PermissionDenied, Io, Syntax, Invalid, Other }

impl LoadError {
    pub fn kind(&self) -> LoadErrorKind {
        match self {
            LoadError::Read { source, .. } => match source.kind() {
                io::ErrorKind::NotFound => LoadErrorKind::NotFound,
                io::ErrorKind::PermissionDenied => LoadErrorKind::PermissionDenied,
                _ => LoadErrorKind::Io,
            },
            LoadError::Parse { .. } => LoadErrorKind::Syntax,
            LoadError::Invalid { .. } => LoadErrorKind::Invalid,
            LoadError::Other(_) => LoadErrorKind::Other,
        }
    }
}
```

Downcasting an `anyhow::Error` back to a typed error: `err.downcast_ref::<LoadError>()` (finds the
typed error even under added `.context`). Prefer `kind()` over string matching on messages.

## 5. Panic policy

| Rule | How |
|---|---|
| no `unwrap`/`expect` in library code paths | `[lints.clippy] unwrap_used = "warn"`, `expect_used = "warn"` (restriction lints, off by default); `allow-unwrap-in-tests = true` in `clippy.toml` (default false) |
| `expect` only for invariants | `.expect("invariant: queue non-empty after push")` |
| panics are bugs, not control flow | return `Result` for anything a caller can cause |
| catch panics only at FFI and thread boundaries | `std::panic::catch_unwind(AssertUnwindSafe(\|\| body()))` and convert to an error code |
| log panics once | `std::panic::set_hook` (chain to the previous hook from `take_hook`) |

`panic = "abort"` in a release profile: destructors do not run on panic, `catch_unwind` catches
nothing, a panic in any thread kills the process (`JoinHandle::join` never sees `Err`), binaries get
smaller. Tests, benchmarks, build scripts and proc macros ignore the setting (the test harness needs
unwinding). Choose it only when nothing relies on `catch_unwind` or on per-thread panic isolation.

FFI: since 1.81 a panic escaping an `extern "C" fn` aborts the process ("panic in a function that
cannot unwind"). Wrap exported bodies:

```rust
#[unsafe(no_mangle)]
pub extern "C" fn checked_div(a: i32, b: i32, out: *mut i32) -> i32 {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| a / b)) {
        Ok(v) => { if !out.is_null() { unsafe { *out = v }; } 0 }   // SAFETY: caller passes a valid out pointer or null
        Err(_) => -1,                                                // panicked: report, do not unwind
    }
}
```

Use `extern "C-unwind"` only when foreign frames must be unwound through deliberately (C++
exceptions). More FFI rules: `rust-ffi-bindings`.

```rust
let default = std::panic::take_hook();
std::panic::set_hook(Box::new(move |info| {
    let msg = info.payload_as_str().unwrap_or("<non-string payload>");
    let loc = info.location().map(|l| format!("{}:{}", l.file(), l.line())).unwrap_or_default();
    tracing::error!(panic = msg, location = %loc, "panic");
    default(info);                                   // keep the standard message and backtrace
}));
```

## 6. Task boundaries

A spawned task's error travels in a `JoinHandle`/`JoinSet`; dropping the handle loses it.

```rust
while let Some(res) = set.join_next().await {        // Result<Result<T, E>, JoinError>
    match res {
        Ok(Ok(v)) => handle(v),
        Ok(Err(e)) => tracing::warn!(error = %format!("{e:#}"), "task failed"),
        Err(je) if je.is_panic() => {
            let payload = je.into_panic();            // Box<dyn Any + Send>
            let msg = payload.downcast_ref::<String>().map(String::as_str)
                .or_else(|| payload.downcast_ref::<&str>().copied()).unwrap_or("?");
            tracing::error!(panic = msg, "worker panicked");   // restart, count, alert on rate
        }
        Err(je) => debug_assert!(je.is_cancelled()),  // aborted on purpose
    }
}
```

Verified output for four tasks returning `Ok(0)`, `Ok(1)`, a panic "boom 2" and `Err("bad 3")`:
`ok 0`, `ok 1`, `task error: bad 3`, `panic: Some("boom 2")` (`panic!` with a format string carries
a `String` payload; a literal-only `panic!("x")` carries `&'static str`).

Inside `tokio::select!`, a refutable pattern drops errors silently: `Ok(v) = fallible() => ..`
disables that branch on `Err` and the error is gone. Bind the whole `Result` (`r = fallible() =>
match r { .. }`) or use `?` inside the branch body. More in `rust-async-tokio`.

## 7. HTTP boundary (axum 0.8)

```rust
use axum::{http::StatusCode, response::{IntoResponse, Response}, Json};

pub enum AppError { NotFound(&'static str), Invalid(String), Internal(anyhow::Error) }

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, msg) = match self {
            AppError::NotFound(what) => (StatusCode::NOT_FOUND, format!("{what} not found")),
            AppError::Invalid(m) => (StatusCode::UNPROCESSABLE_ENTITY, m),
            AppError::Internal(e) => {
                tracing::error!(error = %format!("{e:#}"), "request failed");   // log once, here
                (StatusCode::INTERNAL_SERVER_ERROR, "internal error".to_owned()) // no internals to clients
            }
        };
        (status, Json(serde_json::json!({ "error": msg }))).into_response()
    }
}

// `?` on anything convertible to anyhow::Error becomes Internal.
impl<E: Into<anyhow::Error>> From<E> for AppError {
    fn from(e: E) -> Self { AppError::Internal(e.into()) }
}
```

Do not also `impl std::error::Error for AppError`: the blanket `From` would then overlap with
`From<T> for T`. Log exactly once, at the boundary; lower layers add context and return.

tracing field forms (verified with `tracing-subscriber` fmt):

| Field | Logged as |
|---|---|
| `error = %e` (anyhow) | `error=starting store` (outermost context only) |
| `error = %format!("{e:#}")` | `error=starting store: connecting to db:5432: connection refused` |
| `error = &e as &(dyn std::error::Error + 'static)` | `error=connecting to db:5432 error.sources=[connection refused]` |

## 8. Combinators and control flow

```rust
let Some(raw) = env.get("PORT") else { return Err(ConfigError::Missing("PORT")) };   // let-else
let port: u16 = raw.parse().map_err(ConfigError::BadPort)
    .inspect_err(|e| tracing::debug!(?e, "bad PORT"))?;                              // inspect_err (1.76)
if let Some(h) = env.get("HOST") && h.is_empty() { warn_empty_host(); }               // let chains: 1.88, edition 2024
fn first_word_len(s: &str) -> Option<usize> { Some(s.split_whitespace().next()?.len()) }   // ? on Option
```

Useful: `ok_or_else`, `map_err`, `and_then`, `transpose` (`Option<Result<T,E>>` to `Result<Option<T>,E>`),
`Iterator::collect::<Result<Vec<_>, _>>()` (stops at the first error), `unwrap_or_default`.
`try` blocks are still unstable (E0658 "`try` expression is experimental" on 1.99); use a closure
or a helper function returning `Result` instead.

## 9. Testing errors

```rust
#[test]
fn zero_workers_is_rejected() {
    let err = load(Path::new("tests/data/zero.toml")).unwrap_err();
    assert!(matches!(err, LoadError::Invalid { field: "workers", .. }));
    assert_eq!(err.kind(), LoadErrorKind::Invalid);
}

#[test]
fn missing_file_report() {
    let err = run("does-not-exist.toml").unwrap_err();
    insta::assert_snapshot!(format!("{err:#}"));   // one-line chain; use {err:?} for the multi-line report
}
```

Locally: `cargo insta test` (collects changed snapshots) then `cargo insta review`. In CI, plain
`cargo test` fails on a mismatch; `cargo insta test --unreferenced=reject` also fails on orphaned
`.snap` files. Snapshot only messages you own: OS error text varies by
platform ("No such file or directory (os error 2)" is Linux/macOS), so redact or assert on `kind()`.

## 10. Worked example: unwrap-heavy config loader

Complete compiling programs, every transcript and the tests:
[config loader example](references/config-loader-example.md).

Before:

```rust
#[derive(serde::Deserialize)]
struct Config { listen: String, workers: usize }
fn load(path: &str) -> Config {
    let text = std::fs::read_to_string(path).unwrap();
    let cfg: Config = toml::from_str(&text).unwrap();
    if cfg.workers == 0 { panic!("bad config"); }
    cfg
}
fn main() { let cfg = load("app.toml"); println!("{} {}", cfg.listen, cfg.workers); }
```

```text
thread 'main' (11) panicked at src/main.rs:5:46:
called `Result::unwrap()` on an `Err` value: Os { code: 2, kind: NotFound, message: "No such file or directory" }
```

With `workers = "four"` the second unwrap dumps the parser's internal struct, including the whole
input text: `Error { message: "invalid type: string \"four\", expected usize", input: Some(..), keys: ["workers"], span: Some(34..40) }`.
No file name, exit code 101, and a backtrace hint instead of a message.

After: `LoadError` from section 2 and `kind()` from section 4, plus:

```rust
use std::path::Path;
use anyhow::Context;                                 // for .with_context on Result and Option

#[derive(Debug, serde::Deserialize)]
pub struct Config { pub listen: String, pub workers: usize }

pub fn load(path: &Path) -> Result<Config, LoadError> {
    let text = std::fs::read_to_string(path)
        .map_err(|source| LoadError::Read { path: path.to_owned(), source })?;
    let cfg: Config = toml::from_str(&text)
        .map_err(|e| LoadError::Parse { path: path.to_owned(), source: Box::new(e) })?;
    if cfg.workers == 0 {
        return Err(LoadError::Invalid { field: "workers", reason: "must be at least 1".into() });
    }
    Ok(cfg)
}

fn main() -> anyhow::Result<()> {
    let path = std::env::args().nth(1).unwrap_or_else(|| "app.toml".into());
    let cfg = load(Path::new(&path)).with_context(|| format!("loading config from {path}"))?;
    println!("{} {}", cfg.listen, cfg.workers);
    Ok(())
}
```

Terminal output (exit code 1, no panic, each line names its layer):

```text
$ app                                   # missing file
Error: loading config from app.toml

Caused by:
    0: reading app.toml
    1: No such file or directory (os error 2)

$ app /tmp/bad.toml                     # workers = "four"
Error: loading config from /tmp/bad.toml

Caused by:
    0: parsing /tmp/bad.toml
    1: TOML parse error at line 2, column 11
         |
       2 | workers = "four"
         |           ^^^^^^
       invalid type: string "four", expected usize

$ app /tmp/zero.toml                    # workers = 0
Error: loading config from /tmp/zero.toml

Caused by:
    invalid value for `workers`: must be at least 1
```

One-line form for logs (`{:#}`): `loading config from app.toml: reading app.toml: No such file or
directory (os error 2)`. Callers branch with `err.downcast_ref::<LoadError>().map(LoadError::kind)`
(`Some(NotFound)`, `Some(Syntax)`, `Some(Invalid)` for the three runs). Migration order for a larger
codebase: run `cargo clippy -- -W clippy::unwrap_used -W clippy::expect_used`, fix library code
first (typed errors), then binaries (context), then turn the lints to `deny` in `[lints.clippy]`.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| "x: x: x" duplicated text | `Display` includes `{source}` and a chain printer also walks `source()` | describe the layer only |
| "which file?" | `#[from] io::Error` plus bare `?` | `map_err` with a path-carrying variant, or `.with_context` |
| errors from background work vanish | dropped `JoinHandle`, detached `tokio::spawn` | `JoinSet`, inspect every join result |
| select! loop silently stops reacting | `Ok(v) = fut` pattern disabled the branch on `Err` | bind the `Result` and handle `Err` |
| process aborts on a panic in a callback from C | panic crossed `extern "C"` | `catch_unwind` in every exported fn |
| clients see SQL text or file paths | `Display` of an internal error sent in the response | map to a generic message; log the chain server-side |
| the same failure logged 3 times | each layer logs and returns | return with context; log once at the boundary |
| `Result` moves cost a lot in hot loops | 100+ byte error type | box large variants; watch `result_large_err` |
| `Box<dyn Error>` cannot cross `tokio::spawn` | missing `Send + Sync` | `Box<dyn Error + Send + Sync + 'static>` or `anyhow::Error` |
| a new variant breaks downstream `match` | enum not `#[non_exhaustive]` | mark public error enums `#[non_exhaustive]` from the first release |

Related: `rust-traits-generics`, `rust-async-tokio`, `rust-axum-services`, `rust-ffi-bindings`,
`rust-testing-fuzzing`, hub `rust-craft`.
