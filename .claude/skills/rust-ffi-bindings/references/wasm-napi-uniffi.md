# wasm-bindgen, napi-rs and UniFFI templates

Versions checked October 2026: wasm-bindgen 0.2.x and wasm-pack 0.15 (both under the
`wasm-bindgen` GitHub org since the rustwasm org was archived in 2025), napi 3.x with
`@napi-rs/cli` v3, UniFFI 0.32. Treat snippets as starting points and confirm signatures on
docs.rs for the exact version you pin.

## 1. wasm-bindgen + wasm-pack

```toml
[lib]
crate-type = ["cdylib", "rlib"]          # rlib keeps native unit tests working

[dependencies]
wasm-bindgen = "0.2"
serde = { version = "1", features = ["derive"] }
serde-wasm-bindgen = "0.6"
console_error_panic_hook = { version = "0.1", optional = true }

[profile.release]
opt-level = "z"
lto = true
codegen-units = 1
panic = "abort"
```

```rust
use wasm_bindgen::prelude::*;

#[derive(serde::Serialize)]
pub struct Stats { lines: u32, words: u32 }

#[wasm_bindgen(start)]
pub fn start() {
    #[cfg(feature = "console_error_panic_hook")]
    console_error_panic_hook::set_once();
}

#[wasm_bindgen]
pub fn stats(text: &str) -> Result<JsValue, JsError> {
    if text.len() > 10_000_000 {
        return Err(JsError::new("input too large"));       // becomes a JS Error
    }
    let s = Stats { lines: text.lines().count() as u32, words: text.split_whitespace().count() as u32 };
    Ok(serde_wasm_bindgen::to_value(&s)?)
}
```

```bash
rustup target add wasm32-unknown-unknown
wasm-pack build --target web --release          # pkg/: .wasm, .js glue, .d.ts, package.json
wasm-pack build --target bundler                # default; for webpack/vite
wasm-pack test --headless --firefox             # runs #[wasm_bindgen_test] tests in a browser
twiggy top -n 20 pkg/*_bg.wasm                  # what takes the space
```

Size checklist: release profile above, avoid `format!`-heavy panics (`panic = "abort"` plus
`opt-level = "z"`), drop `serde_json` in favour of `serde-wasm-bindgen`, check that
`wasm-opt` ran (wasm-pack runs it in release; standalone: `wasm-opt -Oz in.wasm -o out.wasm`).

Constraints: no threads on `wasm32-unknown-unknown` without nightly `-Z build-std`, atomics and
cross-origin isolation (COOP/COEP headers); no blocking I/O; `getrandom` needs its `wasm_js`
feature enabled in the final binary crate (not in libraries). Since Rust 1.89 `extern "C"` on
`wasm32-unknown-unknown` follows the standard C ABI; hand-written JS glue that relied on the
old ABI breaks.

## 2. napi-rs (Node.js)

```toml
[lib]
crate-type = ["cdylib"]

[dependencies]
napi = { version = "3", features = ["tokio_rt"] }   # tokio_rt: runtime for async fns
napi-derive = "3"
tokio = { version = "1", features = ["fs"] }

[build-dependencies]
napi-build = "2"
```

```rust
// build.rs
fn main() { napi_build::setup(); }
```

```rust
use napi::bindgen_prelude::*;
use napi_derive::napi;

#[napi(object)]
pub struct Stats { pub lines: u32, pub words: u32 }

#[napi]
pub fn stats(text: String) -> Stats {
    Stats { lines: text.lines().count() as u32, words: text.split_whitespace().count() as u32 }
}

#[napi]
pub async fn read_len(path: String) -> Result<u32> {      // JS: Promise<number>
    let bytes = tokio::fs::read(&path).await.map_err(|e| Error::from_reason(e.to_string()))?;
    Ok(bytes.len() as u32)
}

#[napi]
pub struct Counter { n: u32 }
#[napi]
impl Counter {
    #[napi(constructor)]
    pub fn new() -> Self { Counter { n: 0 } }
    #[napi]
    pub fn inc(&mut self) -> u32 { self.n += 1; self.n }
}
```

```bash
npm i -D @napi-rs/cli
npx napi build --platform --release      # index.<triple>.node + index.js + index.d.ts
npx napi create-npm-dirs                 # npm/<triple>/package.json per target
npx napi artifacts                       # copy CI-built binaries into npm/<triple>/
npx napi prepublish -t npm               # publish platform packages, wire optionalDependencies
```

Cross builds: `--cross-compile` (`-x`, cargo-zigbuild/cargo-xwin) or `--use-napi-cross` (Linux
glibc targets only); both are marked experimental. Check `crate-type` and the `napi` feature
for the N-API level you target (`napi1` ... `napi10`) against the Node versions you support.
Verify the `napi-build` major for your `napi` version on crates.io.

## 3. UniFFI (Kotlin, Swift, Python, Ruby)

```toml
[lib]
crate-type = ["cdylib", "staticlib", "lib"]    # staticlib for iOS XCFrameworks

[dependencies]
uniffi = { version = "0.32", features = ["tokio"] }
thiserror = "2"
```

```rust
uniffi::setup_scaffolding!();

#[derive(uniffi::Record)]
pub struct Stats { pub lines: u32, pub words: u32 }

#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum StatsError {
    #[error("input too large: {size} bytes")]
    TooLarge { size: u64 },
}

#[uniffi::export]
pub fn stats(text: String) -> Result<Stats, StatsError> {
    if text.len() > 10_000_000 { return Err(StatsError::TooLarge { size: text.len() as u64 }); }
    Ok(Stats { lines: text.lines().count() as u32, words: text.split_whitespace().count() as u32 })
}

#[derive(uniffi::Object)]
pub struct Counter { n: std::sync::atomic::AtomicU32 }   // objects are shared (Arc): need Sync

#[uniffi::export(async_runtime = "tokio")]
impl Counter {
    #[uniffi::constructor]
    pub fn new() -> std::sync::Arc<Self> { std::sync::Arc::new(Counter { n: 0.into() }) }
    pub fn inc(&self) -> u32 { self.n.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1 }
    pub async fn slow_inc(&self) -> u32 {                 // Kotlin suspend fun / Swift async
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        self.inc()
    }
}
```

Binding generator crate (workspace member `uniffi-bindgen` with `uniffi = { version = "0.32", features = ["cli"] }`):

```rust
fn main() { uniffi::uniffi_bindgen_main() }
```

```bash
cargo build --release
cargo run -p uniffi-bindgen generate --library target/release/libstats.so --language kotlin --out-dir out/kotlin
cargo run -p uniffi-bindgen generate --library target/release/libstats.so --language swift --out-dir out/swift
```

Notes for 0.32: `[ByRef] bytes` / `&[u8]` arguments are zero-copy from Kotlin (direct
`ByteBuffer`), Swift (`Data`) and Python; Kotlin and Python fail to generate bindings for async
primary constructors (use a named async constructor); `--config` now expects a global config
file; traits exported for foreign implementation use `#[uniffi::export(foreign)]`.
