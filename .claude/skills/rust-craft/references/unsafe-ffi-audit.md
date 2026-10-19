# Unsafe Rust and FFI audit checklist

Use this when writing or reviewing any `unsafe` block, `unsafe fn`, `unsafe impl`, `extern` block
or `#[repr]` type. Unsafe code is correct only if the **safe API around it is sound for every
possible input and every possible safe caller**, including adversarial ones.

## 1. Audit procedure

1. Inventory: `grep -rnw 'unsafe' --include='*.rs' src/ | grep -vE '^[^:]+:[0-9]+:[[:space:]]*//'`
   (drops only whole-line comments, keeps sites with trailing comments) and `cargo geiger`
   (counts unsafe in dependencies too).
2. For each unsafe site, write down the safety contract of every unsafe operation it performs
   (from the std docs "Safety" sections) and check the `// SAFETY:` comment proves each one.
3. Find the module boundary: any safe function in the same module can break invariants that the
   unsafe block relies on (privacy is the real safety boundary). Audit the whole module.
4. Try to break it from safe code: zero-length input, `usize::MAX`, unaligned slices, panicking
   closures/`Drop`/`Clone`/`Hash`/`Ord` impls supplied by the caller, re-entrancy, threads.
5. Run Miri and sanitizers (section 6). Add tests that exercise every unsafe path under Miri.
6. Record findings with file:line, the violated precondition, and a safe-code reproducer.

## 2. Operation-specific contracts

| Operation | Must prove |
|---|---|
| `*ptr` deref (read/write) | non-null, aligned for `T`, points to a live allocation of at least `size_of::<T>()`, initialized (for reads), no conflicting `&mut` alive (aliasing) |
| `slice::from_raw_parts(p, n)` | p non-null and aligned **even when n == 0** (use `NonNull::dangling()`), `n * size_of::<T>() <= isize::MAX`, single allocation, initialized, not mutated for the lifetime |
| `from_raw_parts_mut` | as above plus no other reference to that memory alive |
| `get_unchecked(i)` | `i < len` proven by a dominating check |
| `String::from_utf8_unchecked` / `str::from_utf8_unchecked` | bytes are valid UTF-8 (str with invalid UTF-8 is immediate UB) |
| `mem::transmute::<A, B>` | same size, every bit pattern of A valid for B, alignment, lifetimes not extended; prefer `from_ne_bytes`, `bytemuck`, `zerocopy` |
| `MaybeUninit::assume_init` | every byte the type requires is initialized (padding excepted) |
| `Vec::set_len(n)` | `n <= capacity`, elements `0..n` initialized |
| `ptr::copy_nonoverlapping` | regions do not overlap, both valid for `count * size_of::<T>()` |
| `unsafe impl Send/Sync` | the type's API cannot produce a data race from any thread combination; raw pointers inside must be uniquely owned (Send) or synchronized (Sync) |
| `Pin::new_unchecked` / `get_unchecked_mut` | the pointee never moves again until drop; `Drop` does not move it |
| `unreachable_unchecked`, `assume` | truly unreachable for all safe inputs (otherwise UB, not a panic) |
| `static mut` | taking `&`/`&mut` references to a `static mut` is denied in edition 2024 (`static_mut_refs`); prefer atomics, `Mutex`, `OnceLock`, or `&raw mut` with external synchronization |

## 3. Validity invariants (instant UB if violated, even if never used)

- `bool` must be 0 or 1; `char` a valid scalar value; enums a valid discriminant.
- References (`&T`, `&mut T`) non-null, aligned, pointing to valid `T`; `Box<T>` likewise.
- `!` and empty enums can never exist.
- Integers and raw pointers from uninitialized memory are UB to read (use `MaybeUninit<T>`).
- `&mut T` must be unique for its whole lifetime; creating two overlapping `&mut` is UB even if
  you never write through one. Prefer raw pointers (`&raw mut place`) for aliasing patterns.

## 4. Panic and drop safety

- A panic inside an unsafe region (from caller-supplied `Clone`, `Ord`, closures, allocation
  failure) must not leave memory in a state that a later `Drop` treats as initialized.
  Technique: set `len` to the initialized prefix before calling user code ("leak amplification"),
  or use a guard struct whose `Drop` repairs state.
- `mem::forget` is safe; your API must stay sound if users forget guards (no "scoped" safety that
  depends on a destructor running; this is why `thread::scope` uses a closure).
- `Drop` of a generic container must not access `T` after it may be dropped; `#[may_dangle]` is
  nightly-only and needs `PhantomData<T>` ownership signalling.

## 5. Concurrency and atomics

| Ordering | Use for | Pairing |
|---|---|---|
| `Relaxed` | counters, statistics, IDs; no other memory depends on the value | none |
| `Release` store / `Acquire` load | publishing data: write payload, then `flag.store(true, Release)`; reader `flag.load(Acquire)` then reads payload | must pair |
| `AcqRel` | read-modify-write that both consumes and publishes (refcount decrement reaching zero, lock-free stack push/pop) | |
| `SeqCst` | need a single total order across several atomics (Dekker-style, rarely needed) | default when unsure, then justify relaxing |

- `compare_exchange_weak` in loops, `compare_exchange` for single attempts.
- ABA in lock-free structures: tagged pointers, epoch reclamation (`crossbeam-epoch`), or hazard
  pointers. Do not write a lock-free structure if a `Mutex` meets the latency target.
- Test lock-free code with `loom` (exhaustive interleavings) and under Miri (`-Zmiri-many-seeds`
  explores schedules).

## 6. Tools

```bash
rustup +nightly component add miri && cargo +nightly miri setup
cargo +nightly miri test                                   # Stacked Borrows (default)
MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test    # Tree Borrows model
MIRIFLAGS="-Zmiri-strict-provenance" cargo +nightly miri test   # flags int-to-pointer casts
MIRIFLAGS="-Zmiri-many-seeds=0..16" cargo +nightly miri test    # explore thread schedules
# sanitizers (Linux, nightly)
RUSTFLAGS="-Zsanitizer=address" cargo +nightly test --target x86_64-unknown-linux-gnu
RUSTFLAGS="-Zsanitizer=thread"  cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu
cargo geiger                                               # unsafe usage including dependencies
```

Miri cannot run FFI calls (except a small shim set) or inline assembly; isolate those behind a
trait and test the unsafe Rust logic with a pure-Rust fake under Miri. Miri is slow: mark heavy
tests `#[cfg_attr(miri, ignore)]` and shrink sizes with `if cfg!(miri) { 10 } else { 10_000 }`.

## 7. FFI checklist

Types and layout:
- [ ] Every type crossing the boundary is `#[repr(C)]` (or `#[repr(transparent)]` newtype,
      or a primitive from `core::ffi`: `c_int`, `c_char`, `c_void`, ...).
- [ ] Rust `enum` never receives values from C unless every possible value is a declared
      variant; receive as the integer type and convert with `TryFrom`.
- [ ] `bool` across FFI only if the C side uses `_Bool`/`bool`.
- [ ] Optional pointers are `Option<NonNull<T>>` or `Option<&T>` / `Option<extern "C" fn(..)>`
      (null-pointer optimization guaranteed for these).
- [ ] Generated bindings (`bindgen`) checked into the repo or generated in `build.rs` with a
      pinned header version; layout tests (`bindgen` emits them) run in CI.

Strings and buffers:
- [ ] Incoming `*const c_char`: `CStr::from_ptr` requires NUL termination and validity for the
      call's duration; convert to owned (`to_string_lossy().into_owned()` or `to_str()?`).
- [ ] Outgoing strings: `CString::new(s)?` (fails on interior NUL); keep the `CString` alive
      while C uses the pointer; `c"literal"` for constants.
- [ ] Buffers passed with explicit length; never trust a C-provided length without bounds.

Ownership and allocation:
- [ ] Memory is freed by the allocator that allocated it. Rust-allocated objects handed out via
      `Box::into_raw` come back through a Rust `extern "C" fn foo_free(p: *mut Foo)` that does
      `drop(Box::from_raw(p))` (null-check first).
- [ ] Opaque handles: `pub struct Foo { _private: [u8; 0], _marker: PhantomData<(*mut u8, PhantomPinned)> }`
      pattern for foreign types so Rust cannot construct or move them.
- [ ] Callbacks with `void* user_data`: document lifetime, ensure the Rust closure outlives every
      callback invocation, and that the callback thread is allowed (`Send` requirements).

Unwinding and errors:
- [ ] Rust functions exported to C either cannot panic or wrap the body in
      `std::panic::catch_unwind` and convert to an error code. Panic across `extern "C"` aborts.
- [ ] If the foreign code can unwind (C++ exceptions, longjmp is never OK), declare the import
      `extern "C-unwind"`.
- [ ] `errno`-style errors read immediately after the call (`std::io::Error::last_os_error()`).

Threads and globals:
- [ ] Library thread-safety documented and respected (global init once via `OnceLock`, per-thread
      contexts not shared, `!Send` wrappers for thread-affine handles).
- [ ] Edition 2024 syntax: `unsafe extern "C" { pub fn foo(x: c_int) -> c_int; }` and
      items declared `pub safe fn` inside the block only when calling them is sound for all inputs.
- [ ] Exported symbols: `#[unsafe(no_mangle)] pub extern "C" fn ...`.

Tooling choice:

| Need | Tool |
|---|---|
| call C from Rust | `bindgen` (generate), `cc` crate (build C sources in `build.rs`), `pkg-config` |
| expose Rust to C | `cbindgen` header generation |
| call C++ safely in both directions | `cxx` (shared types, no raw pointers in user code) |
| Python / Node / JVM | `pyo3` + `maturin`, `napi-rs`, `jni` / `uniffi` |
| system linking issues | `cargo rustc -- --print native-static-libs`, `RUSTFLAGS="-C link-arg=..."` sparingly |

## 8. Writing the SAFETY comment

```rust
// SAFETY:
// - `idx < self.len` is checked on the line above, so `ptr.add(idx)` stays in the allocation.
// - Elements 0..len are initialized (invariant maintained by `push` and `truncate`).
// - We hold `&self`, and no method hands out `&mut` to elements while `&self` exists.
unsafe { &*self.ptr.as_ptr().add(idx) }
```

One bullet per precondition, each pointing at the code or invariant that guarantees it. A
comment that only restates the operation ("dereferencing the pointer") fails review.
