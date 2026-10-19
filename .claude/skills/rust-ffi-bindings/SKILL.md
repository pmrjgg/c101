---
name: rust-ffi-bindings
description: "Rust interop and bindings. Covers the C ABI checklist, -sys crates with bindgen, cc and pkg-config, cbindgen and cxx/autocxx, PyO3 0.30 with maturin abi3 and free-threaded wheels, napi-rs, UniFFI, wasm-bindgen and jni, plus testing across the boundary. Load when calling C or C++ from Rust, exposing Rust to another language, or shipping a Rust-backed Python wheel or npm package."
when_to_use: "build.rs with bindgen/cc/pkg-config, a *-sys crate, links = key, cbindgen.toml, #[cxx::bridge], pyproject.toml with build-backend maturin, #[pyfunction]/#[pyclass]/#[pymodule], #[napi], #[wasm_bindgen], #[uniffi::export]; errors like 'Undefined symbols _Py...', 'panic in a function that cannot unwind', 'dynamic module does not define module export function', abi3 or manylinux wheel tags; wrapping a C library or releasing the GIL."
---

# Rust FFI and language bindings

Verified October 2026 against: Rust 1.99 (edition 2024), bindgen 0.73, cc 1.x, cbindgen 0.29,
cxx 1.0, PyO3 0.30 (MSRV 1.85, CPython >= 3.9), maturin 1.15, napi 3.x, UniFFI 0.32,
wasm-bindgen 0.2.x with wasm-pack 0.15. Re-check binding crates with context7 or docs.rs before
coding: PyO3 renames APIs almost every minor release.

Deep material: [C ABI checklist and Rust-to-C exports](references/c-abi-checklist.md) |
[PyO3 and maturin details](references/pyo3-maturin.md) |
[wasm-bindgen, napi-rs, UniFFI templates](references/wasm-napi-uniffi.md)

## 1. Tool chooser

| Direction | Tool | Use when | Notes |
|---|---|---|---|
| Rust calls C | `bindgen` + `cc` / `pkg-config` in a `foo-sys` crate | any C library | bindgen needs libclang at build time; commit bindings if users lack it |
| C calls Rust | `cbindgen` | ship a `.h` for a Rust `cdylib`/`staticlib` | generate in CI, diff against the committed header |
| Rust and C++ | `cxx` (hand-written bridge), `autocxx` (generated from headers) | C++ classes, `std::string`, `unique_ptr` | cxx forbids raw pointers in user code; no exceptions across the bridge |
| Python | PyO3 + maturin | wheels for CPython (and PyPy/GraalPy) | abi3 = one wheel per platform for all versions |
| Node.js | napi-rs (`#[napi]`, `@napi-rs/cli`) | npm packages with prebuilt binaries | one npm package per platform triple |
| Kotlin / Swift / Python / Ruby | UniFFI (proc-macros) | mobile SDKs from one Rust core | async supported; library mode |
| JS / browser | wasm-bindgen + wasm-pack | web or bundler targets | no threads by default |
| JVM | `jni` crate | Android/JVM without UniFFI | manual JNI env handling |
| Linking trouble | `cargo rustc -- --print native-static-libs` | which system libs a staticlib needs | use `RUSTFLAGS="-C link-arg=..."` sparingly |

## 2. C ABI rules (non-negotiable)

1. Only `#[repr(C)]` structs/enums, `#[repr(transparent)]` newtypes, and `core::ffi` primitives
   (`c_int`, `c_char`, `c_void`, ...) cross the boundary. Never `String`, `Vec`, `&str`, `Option<String>`,
   generics, trait objects, tuples or `bool` unless the C side is `_Bool`.
2. Receive C enums as the integer type and convert with `TryFrom`; a Rust enum holding an
   undeclared discriminant is instant UB. Rust 1.93+ warns on `repr(C)` enums whose discriminants
   do not fit `c_int`/`c_uint`.
3. Edition 2024 syntax: `unsafe extern "C" { ... }` blocks (mark items `safe fn` only if every
   input is sound), `#[unsafe(no_mangle)]`, `#[unsafe(export_name = "...")]`.
4. Unwinding: a panic escaping `extern "C"` aborts the process (since 1.81). Wrap every exported
   body and every callback in `std::panic::catch_unwind` and convert to an error code. Declare
   imports `extern "C-unwind"` only when the foreign side really unwinds (C++ exceptions);
   `longjmp` over Rust frames is never allowed.
5. Opaque handles: hand out `Box::into_raw(Box::new(x))`, take it back in exactly one
   `foo_free(p)` that null-checks and calls `drop(Box::from_raw(p))`. Model foreign handles as
   `NonNull<ffi::foo_ctx>` inside an RAII struct whose `Drop` calls the C destructor.
6. Thread safety is a claim you prove: `unsafe impl Send` only if the C docs allow use from any
   thread; `Sync` only if concurrent calls are allowed. Otherwise take `&mut self` or wrap in a `Mutex`.
7. Every `unsafe` block gets a `// SAFETY:` comment naming each precondition (pointer validity,
   lifetime, aliasing, thread rules); every `pub unsafe fn` gets a `# Safety` doc section.

Exported function shape (compiles clean under `clippy::undocumented_unsafe_blocks`):

```rust
/// Returns 0 on success, -1 on a NULL argument, -2 if Rust panicked.
/// # Safety
/// `p` from `bar_parser_new`; `line` NUL-terminated and valid for the call; `out_len` writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn bar_parser_feed(p: *mut BarParser, line: *const c_char, out_len: *mut usize) -> c_int {
    catch_unwind(AssertUnwindSafe(|| {
        if p.is_null() || line.is_null() || out_len.is_null() { return -1; }
        // SAFETY: non-null checked above; validity is the caller's contract (see # Safety).
        let (parser, text) = unsafe { (&mut *p, CStr::from_ptr(line)) };
        parser.lines += 1;
        // SAFETY: `out_len` is non-null and writable per the contract.
        unsafe { out_len.write(text.to_bytes().len()) };
        0
    }))
    .unwrap_or(-2)
}
```

## 3. Strings, buffers and errors

| Situation | Do | Never |
|---|---|---|
| C string in (`*const c_char`) | null-check, `CStr::from_ptr(p)` (needs NUL, valid for the call), then `to_str()?` or `to_string_lossy().into_owned()` | keep the `&CStr` past the call |
| Rust string out | `CString::new(s)?` (fails on interior NUL); `into_raw()` plus a `foo_string_free` that calls `CString::from_raw` | return `s.as_ptr()` of a temporary |
| constant strings | `c"literal"` (stable since 1.77) | `"literal\0".as_ptr()` casts |
| buffers | `(ptr, len)` pairs; `slice::from_raw_parts(p, n)` needs `p` non-null and aligned even when `n == 0` (`NonNull::dangling()`) | trust a C length without bounds |
| caller-provided output buffer | `(buf, cap, *mut out_len)`; return "too small" with the needed length | write past `cap` |
| allocation ownership | free with the allocator that allocated: Rust `Box`/`CString` -> Rust `free` fn; C `malloc` -> C `free` | `libc::free` on Rust memory or the reverse |
| errors | `int` status (0 = ok) plus out-params, or a thread-local `foo_last_error()`; read `errno` immediately via `io::Error::last_os_error()` | panics or `Result` across the ABI |

## 4. build.rs hygiene and the -sys convention

- Split `foo-sys` (raw bindings, `links = "foo"`, build script) from `foo` (safe API, RAII, error
  enum). Only one crate in a graph may declare `links = "foo"`; it can publish
  `cargo::metadata=include=...`, which dependents' build scripts read as `DEP_FOO_INCLUDE`.
- Default to the system library via `pkg-config`; add a `vendored` feature that compiles the
  bundled source with `cc` (or `cmake`). Error text must name the feature to enable.
- Print `cargo::rerun-if-changed=` for every input (wrapper header, vendored dir) and
  `cargo::rerun-if-env-changed=` for every env var read; without any directive Cargo reruns the
  script whenever any package file changes. `cargo::` syntax needs Rust 1.77+.
- In build scripts read the *target* from env (`CARGO_CFG_TARGET_OS`, `TARGET`), never
  `cfg!(target_os)` (that is the host).
- bindgen: allowlist (`allowlist_function("foo_.*")`, `allowlist_type`, `allowlist_var`), use
  `bindgen::CargoCallbacks::new()`, keep its layout tests; it emits `unsafe extern "C"` blocks
  for Rust targets >= 1.82.

Cross-compiling checklist:

| Tool | Variable |
|---|---|
| `cc` | `CC_<target_with_underscores>` / `CFLAGS_<target>` or `TARGET_CC` |
| `pkg-config` | `PKG_CONFIG_SYSROOT_DIR`, `PKG_CONFIG_PATH`, `PKG_CONFIG_ALLOW_CROSS=1` |
| bindgen | `BINDGEN_EXTRA_CLANG_ARGS_<target>` (sysroot `--sysroot=`, `-I`), `LIBCLANG_PATH` |
| linker | `[target.<triple>] linker = "..."` in `.cargo/config.toml` |

## 5. PyO3 0.30 essentials

| Topic | Current API (0.26+) | Gone or renamed |
|---|---|---|
| attach to interpreter | `Python::attach(\|py\| ...)` | `Python::with_gil` (renamed in 0.26) |
| release for CPU or C work | `py.detach(\|\| ...)`; closure and result must be `Ungil` (`Send` on stable) | `allow_threads` (renamed in 0.26) |
| object handles | `Bound<'py, T>` in signatures, `Py<T>` for storage, `Borrowed` | `&PyAny` GIL refs (removed), `PyObject` alias (deprecated 0.26) |
| downcasting | `.cast::<T>()`, `CastError` | `.downcast()` (0.27) |
| exceptions | `create_exception!(module, FooError, PyException)`; raise with `FooError::new_err(msg)` | |
| classes | `#[pyclass]` must be `Send + Sync`; `#[pyclass(frozen)]` + `Mutex`/atomics for state; since 0.30 no automatic `FromPyObject` for `Clone` classes | |
| functions and modules | `#[pyfunction] fn f(...)`; export with a declarative `#[pymodule] mod m { #[pymodule_export] use super::f; }` or, function-style, `m.add_function(wrap_pyfunction!(f, m)?)?` with `m: &Bound<'_, PyModule>` | |
| free-threaded CPython | supported by default since 0.28; opt out with `#[pymodule(gil_used = true)]`; 3.14t+ only (3.13t dropped in 0.29) | `gil_used = false` opt-in (pre-0.28) |
| bytes | `&[u8]` args accept `bytes`; `Vec<u8>`/`&[u8]` return `bytes` (not a list) | |

Error mapping: `impl From<foo::Error> for PyErr` is illegal in a third crate (orphan rule: both
foreign). Write `fn to_py(e: foo::Error) -> PyErr` and `.map_err(to_py)`, or implement
`From` in the crate that owns the error type behind a `python` feature.

## 6. maturin workflow

```bash
uv venv && uv pip install maturin pytest          # or: uv tool install maturin
maturin develop --release --uv                    # build + install into the active venv
maturin build --release --out dist                # wheel(s) in dist/
maturin generate-ci github > .github/workflows/CI.yml
```

- `pyproject.toml`: `[build-system] requires = ["maturin>=1.9.4,<2"]`, `build-backend = "maturin"`;
  `[tool.maturin] module-name = "foo_py"` (must equal the `#[pymodule]` name and `[lib] name`).
- The `pyo3/extension-module` feature is deprecated: maturin >= 1.9.4 sets
  `PYO3_BUILD_EXTENSION_MODULE` itself. Plain `cargo build` of the cdylib on macOS fails with
  `Undefined symbols ... "_PyBaseObject_Type"`; build with maturin (manual fallback:
  `-C link-arg=-undefined -C link-arg=dynamic_lookup`).
- abi3: `pyo3 = { version = "0.30", features = ["abi3-py39"] }` builds one `cp39-abi3` wheel per
  platform for every CPython >= 3.9. Free-threaded interpreters ignore abi3: ship a separate
  `cp314t` wheel (`abi3t`, PEP 803, exists only for 3.15+).
- Linux wheels: `PyO3/maturin-action@v1` with `manylinux: auto` and a second job with
  `manylinux: musllinux_1_2`; add `sccache: true`.
- Stubs: pure-Rust project ships `foo_py.pyi` next to `Cargo.toml` (maturin adds `py.typed`);
  mixed projects put `.pyi` and an empty `py.typed` in `python/foo_py/`.
Details and the CI matrix: [pyo3-maturin](references/pyo3-maturin.md).

## 7. wasm-bindgen

- `crate-type = ["cdylib", "rlib"]`; export with `#[wasm_bindgen] pub fn f(x: &str) -> Result<JsValue, JsError>`;
  pass structs with `serde-wasm-bindgen`; install `console_error_panic_hook` in debug builds.
- `wasm-pack build --target web` (ES module, load with `init()`), `--target bundler` (default,
  webpack/vite), `--target nodejs`. Release builds run `wasm-opt` automatically.
- Size: `[profile.release] opt-level = "z"`, `lto = true`, `codegen-units = 1`, `panic = "abort"`,
  then `wasm-opt -Oz`; inspect with `twiggy top`.
- No threads by default (`std::thread::spawn` fails on `wasm32-unknown-unknown`); real threads need
  nightly `-Z build-std` with atomics plus COOP/COEP headers.
- `getrandom` on the web: enable its `wasm_js` feature in the final binary crate only.
- The rustwasm org was archived in 2025; wasm-bindgen and wasm-pack now live under the
  `wasm-bindgen` GitHub org and are maintained.

## 8. UniFFI and napi-rs essentials

| | UniFFI 0.32 | napi-rs 3.x |
|---|---|---|
| declare | `uniffi::setup_scaffolding!();` then `#[uniffi::export]` on fns/impls, `#[derive(uniffi::Record / Enum / Object / Error)]` | `#[napi]` fns, `#[napi(object)]` structs, `#[napi] impl` classes; `build.rs`: `napi_build::setup()` |
| errors | `#[derive(Debug, thiserror::Error, uniffi::Error)]` -> exceptions | `napi::Result<T>`, `napi::Error::from_reason(msg)` |
| async | `#[uniffi::export] async fn` -> Kotlin `suspend` / Swift `async`; tokio futures need `#[uniffi::export(async_runtime = "tokio")]` | `#[napi] async fn` (tokio runtime feature) -> `Promise` |
| crate type | `["cdylib", "staticlib", "lib"]` (staticlib for iOS) | `["cdylib"]` |
| generate / build | `cargo run -p uniffi-bindgen generate --library target/release/libfoo.so --language kotlin --out-dir out` | `napi build --platform --release` |
| ship | Kotlin AAR / Swift XCFramework | `napi create-npm-dirs`, `napi artifacts`, `napi prepublish -t npm`: one npm package per triple via optionalDependencies |

Prefer UniFFI proc-macros over UDL files for new code. Templates:
[wasm-napi-uniffi](references/wasm-napi-uniffi.md).

## 9. Testing across the boundary

| Layer | How |
|---|---|
| C library itself | build the vendored C with ASan: `CFLAGS=-fsanitize=address RUSTFLAGS=-Zsanitizer=address cargo +nightly test --target x86_64-unknown-linux-gnu -p foo` |
| safe wrapper logic | unit tests in `foo` against the real library (vendored feature in CI) |
| unsafe Rust around FFI | Miri cannot execute foreign code (an experimental Unix-only `-Zmiri-native-lib` exists): put the C calls behind a trait, test the Rust side under Miri with a pure-Rust fake |
| layout drift | keep bindgen's generated layout tests; run them on every target you ship |
| macro-generated glue (PyO3, cxx, napi) | read what the macro emitted: `cargo expand -p crate path::to::module` (cargo-expand) |
| Python surface | `maturin develop` then `pytest` in CI on each Python you claim, plus one free-threaded job (`python3.14t`) running a threaded stress test |
| exported C API | a C test program linked against the `staticlib`, run under ASan and Valgrind |

## 10. Worked example: libfoo -> foo-sys -> foo -> abi3 Python wheel

libfoo API (`vendor/foo.h`): `foo_ctx *foo_new(uint32_t level, int *err)`,
`int foo_checksum(foo_ctx*, const uint8_t *buf, size_t len, uint32_t *out)` (not thread-safe,
one thread at a time), `const char *foo_strerror(int)` (static), `void foo_free(foo_ctx*)`;
`#define FOO_OK 0`, `FOO_EINVAL 1`, `FOO_ENOMEM 2`.

**Step 1: foo-sys.** `Cargo.toml`: `links = "foo"`, `[features] vendored = ["dep:cc"]`,
build-deps `bindgen = "0.73"`, `cc` (optional), `pkg-config`.

```rust
// foo-sys/build.rs
fn main() {
    println!("cargo::rerun-if-changed=wrapper.h");
    println!("cargo::rerun-if-changed=vendor");
    let includes: Vec<std::path::PathBuf> = if cfg!(feature = "vendored") {
        #[cfg(feature = "vendored")]
        cc::Build::new().file("vendor/foo.c").include("vendor").warnings(true).compile("foo");
        vec!["vendor".into()]
    } else {
        pkg_config::Config::new().atleast_version("1.0").probe("foo")
            .expect("libfoo >= 1.0 not found via pkg-config; enable the `vendored` feature")
            .include_paths
    };
    let mut b = bindgen::Builder::default().header("wrapper.h")
        .allowlist_function("foo_.*").allowlist_type("foo_.*").allowlist_var("FOO_.*")
        .parse_callbacks(Box::new(bindgen::CargoCallbacks::new()));
    for inc in &includes { b = b.clang_arg(format!("-I{}", inc.display())); }
    let out = std::path::PathBuf::from(std::env::var("OUT_DIR").unwrap());
    b.generate().expect("bindgen failed").write_to_file(out.join("bindings.rs")).unwrap();
}
```

`src/lib.rs` is `include!(concat!(env!("OUT_DIR"), "/bindings.rs"));`. Generated output (real):
`pub const FOO_OK: u32 = 0;`, an opaque `pub struct foo_ctx { _unused: [u8; 0] }` and
`unsafe extern "C" { pub fn foo_new(level: u32, err: *mut c_int) -> *mut foo_ctx; }`.

**Step 2: safe foo.** RAII handle plus error enum:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[non_exhaustive]
pub enum Error {
    #[error("invalid argument")] InvalidArgument,
    #[error("out of memory")] OutOfMemory,
    #[error("libfoo error {code}: {msg}")] Other { code: i32, msg: &'static str },
}
pub struct Checksummer { ctx: NonNull<foo_sys::foo_ctx> }
// SAFETY: foo.h allows any thread, one at a time; `checksum` takes &mut self.
unsafe impl Send for Checksummer {}
impl Checksummer {
    pub fn new(level: u32) -> Result<Self, Error> {
        let mut err: c_int = 0;
        // SAFETY: any level is accepted; `err` is a valid c_int written on failure.
        let raw = unsafe { foo_sys::foo_new(level, &mut err) };
        NonNull::new(raw).map(|ctx| Self { ctx }).ok_or_else(|| Error::from_code(err))
    }
    pub fn checksum(&mut self, data: &[u8]) -> Result<u32, Error> {
        let mut out = 0u32;
        // SAFETY: ctx live until Drop; (ptr, len) valid for the call and not retained.
        let rc = unsafe { foo_sys::foo_checksum(self.ctx.as_ptr(), data.as_ptr(), data.len(), &mut out) };
        if rc == foo_sys::FOO_OK as c_int { Ok(out) } else { Err(Error::from_code(rc)) }
    }
}
impl Drop for Checksummer {
    fn drop(&mut self) {
        // SAFETY: ctx came from foo_new and is freed exactly once.
        unsafe { foo_sys::foo_free(self.ctx.as_ptr()) }
    }
}
```

`Error::from_code` matches `u32::try_from(code)` against `foo_sys::FOO_EINVAL`/`FOO_ENOMEM` and
falls back to `CStr::from_ptr(foo_strerror(code))` (static string, documented).

**Step 3: foo-py.** `[lib] name = "foo_py"`, `crate-type = ["cdylib"]`,
`pyo3 = { version = "0.30", features = ["abi3-py39"] }`:

```rust
pyo3::create_exception!(foo_py, FooError, pyo3::exceptions::PyException);
fn to_py(e: foo::Error) -> PyErr { FooError::new_err(e.to_string()) } // orphan rule

#[pyclass(frozen)]
struct Checksummer { inner: Mutex<foo::Checksummer> } // pyclass needs Sync; C ctx is only Send

#[pymethods]
impl Checksummer {
    #[new]
    #[pyo3(signature = (level = 0))]
    fn new(level: u32) -> PyResult<Self> {
        Ok(Self { inner: Mutex::new(foo::Checksummer::new(level).map_err(to_py)?) })
    }
    fn checksum(&self, py: Python<'_>, data: &[u8]) -> PyResult<u32> {
        py.detach(|| {
            let mut c = self.inner.lock().map_err(|_| FooError::new_err("checksummer poisoned"))?;
            c.checksum(data).map_err(to_py)
        })
    }
}

#[pymodule]
mod foo_py {
    #[pymodule_export] use super::Checksummer;
    #[pymodule_export] use super::FooError;
}
```

**Step 4: build and test.** `maturin develop --release --uv && pytest`, then
`maturin build --release --out dist` gives `foo_py-0.1.0-cp39-abi3-<platform>.whl`. Measured on
this stack (macOS arm64): the module built once against 3.13 imported and passed on CPython 3.10,
3.12, 3.13 and 3.15 (`Checksummer().checksum(b"hello") == 1335831723`, matching a pure-Python
FNV-1a; `Checksummer(10)` raised `foo_py.FooError: invalid argument`, base `Exception`). A build
for free-threaded 3.14t kept `sys._is_gil_enabled() == False` after import, and 8 threads x 2000
calls returned 16000 identical results (the `Mutex` serialises the C context).

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| process aborts with "panic in a function that cannot unwind" | panic crossed `extern "C"` | `catch_unwind` in every export and callback |
| crash in `free` / heap corruption | memory freed by the wrong allocator | pair every `*_new` with a `*_free` from the same side |
| garbage strings in C | returned pointer of a dropped `CString` | `into_raw` + explicit free fn, or caller-provided buffer |
| `ImportError: dynamic module does not define module export function (PyInit_x)` | `[lib] name`, `#[pymodule]` name and `module-name` disagree | make all three identical |
| `Undefined symbols "_Py..."` linking on macOS | built the extension with plain cargo | use maturin, or `-undefined dynamic_lookup` |
| wheel works locally, fails on other Linux | built on a new glibc host | maturin-action `manylinux: auto`, check with `auditwheel show` |
| deadlock or `Already borrowed` under threads | mutable `#[pyclass]` shared across threads, lock held while re-attaching | `#[pyclass(frozen)]` + `Mutex`; `MutexExt::lock_py_attached` when Python is touched inside |
| build works on host, cross build links host libs | `cfg!(target_os)` / host pkg-config in build.rs | `CARGO_CFG_TARGET_*`, cross pkg-config env |
| bindings silently stale | missing `rerun-if-changed` | list every header/dir; `CargoCallbacks::new()` |
| UB with C enums | foreign value outside declared variants | receive as integer + `TryFrom` |
| wasm `unreachable` trap with no message | panic without hook | `console_error_panic_hook::set_once()` |

Related: `rust-unsafe-soundness`, `rust-error-handling`, `rust-testing-fuzzing`,
`cargo-workspaces-features`, `rust-performance`, hub `rust-craft`.
