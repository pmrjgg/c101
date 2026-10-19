---
name: rust-unsafe-soundness
description: "Unsafe Rust soundness audits. Covers the audit procedure, per-operation safety contracts, validity invariants, aliasing (Stacked and Tree Borrows) and strict provenance, panic and drop safety, atomic orderings, edition-2024 unsafe rules, SAFETY-comment discipline and lint policy, and Miri, sanitizer, cargo-careful, loom and Kani commands. Load when writing, reviewing or debugging any unsafe block, raw-pointer code or lock-free structure."
when_to_use: "Any .rs file containing unsafe, unsafe impl Send/Sync, raw pointers, MaybeUninit, transmute, UnsafeCell, static mut, atomics with explicit Ordering, Pin::new_unchecked, or extern blocks; Miri 'Undefined Behavior' or 'Data race detected' reports; 'unsafe precondition(s) violated' aborts; security review of unsafe code; adding lock-free data structures."
---

# Unsafe Rust soundness

Baseline: stable rustc 1.99 with edition 2024; Miri and sanitizers on nightly (1.101 in October
2026). Unsafe code is correct only if **the safe API around it is sound for every input and every
safe caller**, including adversarial ones. Full worked-example listings and Miri transcripts:
[ring buffer under Miri](references/ring-buffer-miri.md). FFI-specific rules: `rust-ffi-bindings`.

## 1. Audit procedure

1. Inventory: `rg -n '\bunsafe\b' --type rust -g '!target'` (or
   `grep -rnw 'unsafe' --include='*.rs' src/ | grep -vE '^[^:]+:[0-9]+:[[:space:]]*//'`, which drops
   whole-line comments only), `rg -c 'unsafe \{' --type rust` per file, and `cargo geiger` for
   unsafe in dependencies.
2. Map each unsafe block to the safe API it backs. Privacy is the safety boundary: any safe function
   in the same module can break an invariant the block relies on, so audit the whole module, and
   keep unsafe in small modules whose private fields carry the invariants.
3. For every unsafe operation, list its contract (section 2) and prove each precondition holds for
   all safe inputs: zero length, `usize::MAX`, unaligned slices, caller-supplied `Clone`/`Drop`/
   `Hash`/`Ord`/closures that panic or lie, re-entrancy, several threads.
4. Check or write the `// SAFETY:` comment: one bullet per precondition, each pointing to the code
   or invariant that guarantees it (section 10).
5. Run the tools (section 8) with tests that reach every unsafe path.
6. Report each finding as file:line, the violated precondition, and a safe-code reproducer.

## 2. Operation contracts

| Operation | Must prove |
|---|---|
| `*ptr` read or write | non-null, aligned for `T`, inside one live allocation of `size_of::<T>()` bytes, initialised (reads), no conflicting live reference (aliasing) |
| `slice::from_raw_parts(p, n)` | `p` non-null and aligned **even when n == 0** (use `NonNull::dangling()`), `n * size_of::<T>() <= isize::MAX`, one allocation, initialised, not mutated while the slice lives |
| `slice::from_raw_parts_mut` | as above, plus no other access to that memory while it lives |
| `get_unchecked(i)` / `get_unchecked_mut` | `i < len` proven by a dominating check |
| `str::from_utf8_unchecked`, `String::from_utf8_unchecked` | bytes are valid UTF-8 (a `str` with invalid UTF-8 is immediate UB) |
| `mem::transmute::<A, B>` | same size, every bit pattern of A valid for B, alignment, no lifetime extension; prefer `to_ne_bytes`/`from_ne_bytes`, `bytemuck::cast`, `zerocopy` |
| `MaybeUninit::assume_init` | every byte the type needs is initialised (padding excepted) |
| `Vec::set_len(n)` | `n <= capacity`, elements `old_len..n` initialised |
| `Vec::from_raw_parts(p, len, cap)` | parts come from a `Vec<T>` with the same `T` and allocator that is never used again |
| `ptr::copy_nonoverlapping(src, dst, n)` | regions do not overlap; both valid for `n * size_of::<T>()`; aligned |
| `unsafe impl Send` / `Sync` | no thread combination can cause a data race through the type's API; raw pointers inside are uniquely owned (Send) or synchronised (Sync) |
| `Pin::new_unchecked`, `Pin::get_unchecked_mut` | the pointee never moves again until dropped, including in `Drop` |
| `hint::unreachable_unchecked`, `hint::assert_unchecked(c)` | truly unreachable / `c` true for all safe inputs; otherwise UB, not a panic |
| `static mut` | `&`/`&mut` to it are denied in 2024 (`static_mut_refs`); use atomics, `Mutex`, `OnceLock`, or `&raw mut STATIC` with external synchronisation |

Debug builds check some contracts at run time and abort: verified on 1.99,
`from_raw_parts(null, 0)` hidden behind `black_box` aborts with "unsafe precondition(s) violated:
slice::from_raw_parts requires the pointer to be aligned and non-null, and the total size of the
slice not to exceed `isize::MAX`" in debug and silently returns in release. With a literal null,
rustc refuses to compile (`invalid_null_arguments`, deny by default). These checks are optional;
never count on them.

## 3. Validity invariants (UB the moment the value exists, used or not)

- `bool` is 0 or 1; `char` a Unicode scalar value (not a surrogate, at most `0x10FFFF`); an enum
  holds a declared discriminant. `!` and empty enums can never exist.
- `&T`, `&mut T`, `Box<T>`, `NonNull<T>`, `fn` pointers: non-null; references also aligned and
  pointing to a valid `T`.
- Integers, floats and raw pointers must be initialised: reading uninitialised memory as `u32` is
  UB (use `MaybeUninit<T>`).
- `str` contains valid UTF-8.
- `&mut T` is unique for its whole lifetime: two overlapping `&mut` are UB even if one is never
  written through. Use raw pointers (`&raw mut place`) for aliasing patterns.

Miri messages (nightly, October 2026): `transmute::<u8, bool>(2)` gives "constructing invalid value
of type bool: encountered 0x02, but expected a boolean"; `MaybeUninit::<u32>::uninit().assume_init()`
gives "constructing invalid value of type u32: encountered uninitialized memory, but expected an
integer" (plain rustc only warns "the type `u32` does not permit being left uninitialized" and
prints garbage).

## 4. Aliasing and provenance

| Rule | Practice |
|---|---|
| `&mut` is unique, `&` is read-only (outside `UnsafeCell`) | never write through a pointer derived from `&T`, from `as_ptr()` on a shared slice, or from `&self` without `UnsafeCell` |
| `UnsafeCell<T>` is the only interior-mutability primitive | `Cell`, `RefCell`, `Mutex`, atomics are built on it; `&UnsafeCell<T>` permits writes through `.get()` |
| raw pointers to places | `&raw const x` / `&raw mut x` (1.82) create a pointer without an intermediate reference (packed fields, `static mut`, uninitialised memory) |
| provenance | a pointer is an address plus permission for one allocation; integer round trips lose it |
| strict provenance (1.84) | `p.addr()`, `p.with_addr(a)`, `p.map_addr(f)` for tagging and alignment tricks; `ptr::without_provenance(a)` for sentinels; `p.expose_provenance()` plus `ptr::with_exposed_provenance(a)` only when an integer must round-trip |

Aliasing models in Miri: Stacked Borrows is the default; Tree Borrows (`-Zmiri-tree-borrows`) is
newer and accepts more real-world patterns. Both are still described as experimental. Run both:
a report under both is a real bug; a report under Stacked Borrows only usually means the code
leans on rules that are not settled, so restructure it rather than argue.

## 5. Panic and drop safety

- Code inside an unsafe region that calls user code (`Clone`, `Ord`, closures, allocation) can
  unwind. Never leave memory that a later `Drop` treats as initialised but is not. Techniques:
  set `len` to the initialised prefix before calling user code ("leak amplification": `Vec::drain`
  shrinks `len` first, so a leaked `Drain` leaks elements instead of double-dropping them), or a
  guard struct whose `Drop` repairs the state:

```rust
struct Guard<'a, T> { buf: &'a mut Vec<T>, initialised: usize }
impl<T> Drop for Guard<'_, T> {
    fn drop(&mut self) {
        // SAFETY: elements 0..initialised were written before the panic and initialised <= capacity;
        // the uninitialised tail is never exposed.
        unsafe { self.buf.set_len(self.initialised) }
    }
}
```

- `mem::forget` is safe: an API must stay sound when users forget guards, so safety may not depend
  on a destructor running (why `thread::scope` takes a closure instead of returning a guard).
- `ManuallyDrop<T>` suppresses the destructor of one field or value; take it out with
  `ManuallyDrop::into_inner` or `ManuallyDrop::take` (unsafe: at most once).
- Drop check: a generic container that owns `T` through a raw pointer needs `PhantomData<T>` so the
  compiler knows it drops `T`. `unsafe impl<#[may_dangle] T> Drop` (feature `dropck_eyepatch`) is
  nightly-only and promises `drop` never reads a `T` that may already be dangling.

## 6. Atomics and memory ordering

| Ordering | Use for | Pairing |
|---|---|---|
| `Relaxed` | counters, statistics, ID generators: no other memory depends on the value | none |
| `Release` store / `Acquire` load | publication: write the payload, `flag.store(true, Release)`; reader `flag.load(Acquire)` then reads the payload | must pair on the same atomic |
| `AcqRel` | read-modify-write that both consumes and publishes (lock-free push/pop, refcount reaching zero) | |
| `SeqCst` | a single total order across several atomics (Dekker-style flags; rare) | default when unsure, then justify relaxing |

```rust
let mut cur = a.load(Relaxed);
loop {
    let new = cur.checked_mul(2)?;
    match a.compare_exchange_weak(cur, new, AcqRel, Relaxed) {   // weak may fail spuriously: loop only
        Ok(_) => break,
        Err(actual) => cur = actual,
    }
}
// one-shot alternatives: compare_exchange; closures: try_update / update
// (rustc 1.99 deprecates fetch_update: "renamed to `try_update` for consistency")

if strong.fetch_sub(1, Release) == 1 {   // Arc-style drop: last owner
    fence(Acquire);                      // see every write made before the other owners' Release
    drop_slow();
}
```

- The failure ordering of `compare_exchange` may be `Relaxed`, `Acquire` or `SeqCst`, never
  `Release`/`AcqRel`. `compiler_fence` only stops compiler reordering (signal handlers).
- ABA in lock-free structures: tagged pointers, epoch reclamation (`crossbeam-epoch`), or hazard
  pointers. Do not write a lock-free structure when a `Mutex` meets the latency target.
- Model-check small kernels with loom: `loom::model(|| { .. })` using `loom::sync` and
  `loom::thread`, built with `RUSTFLAGS="--cfg loom" cargo test --release`; loom's `UnsafeCell`
  exposes `with`/`with_mut` closures instead of `get`. `LOOM_MAX_PREEMPTIONS=2` or `3` catches most
  bugs at a fraction of the run time.

## 7. Edition 2024 rules

| Rule | Error or lint (verified on 1.99) | Write |
|---|---|---|
| `extern` blocks must be `unsafe` | "extern blocks must be unsafe" | `unsafe extern "C" { pub safe fn abs(x: c_int) -> c_int; pub unsafe fn strlen(s: *const c_char) -> usize; }` (`safe fn` only if sound for every input) |
| unsafe attributes | "unsafe attribute used without unsafe" | `#[unsafe(no_mangle)]`, `#[unsafe(export_name = "..")]`, `#[unsafe(link_section = "..")]` |
| unsafe ops inside `unsafe fn` need a block | warning E0133 via `unsafe_op_in_unsafe_fn` (warn) | `unsafe fn f(p: *const u32) -> u32 { unsafe { *p } }`; set it to `deny` in `[lints.rust]` |
| `std::env::set_var` / `remove_var` are unsafe | error E0133 | call before spawning threads, inside `unsafe { }` with a SAFETY note; prefer passing config explicitly |
| references to `static mut` | "creating a shared reference to mutable static" (`static_mut_refs`, deny) | `&raw const STATIC` / `&raw mut STATIC`, or an atomic or `OnceLock` |
| safe `#[target_feature]` functions (1.86) | calling one from a context without the feature needs `unsafe` | `#[target_feature(enable = "avx2")] fn sum(xs: &[u32]) -> u32`; call after `is_x86_feature_detected!("avx2")` |

FFI boundary essentials (full checklist in `rust-ffi-bindings`): only `#[repr(C)]` or
`#[repr(transparent)]` types cross it; `extern "C-unwind"` when foreign code may unwind into Rust;
`catch_unwind` in every Rust callback called from C (a panic out of `extern "C"` aborts);
`CStr`/`CString` for strings; memory is freed by the allocator that allocated it.

## 8. Tooling

```bash
rustup +nightly component add miri && cargo +nightly miri setup
cargo +nightly miri test                                           # Stacked Borrows (default)
MIRIFLAGS="-Zmiri-tree-borrows" cargo +nightly miri test            # Tree Borrows
MIRIFLAGS="-Zmiri-strict-provenance" cargo +nightly miri test       # reject integer-to-pointer casts
MIRIFLAGS="-Zmiri-many-seeds=0..16" cargo +nightly miri test        # schedules and weak-memory choices (bare flag: 0..64)
MIRIFLAGS="-Zmiri-many-seeds -Zmiri-many-seeds-keep-going" cargo +nightly miri test   # failure rate across seeds
cargo +nightly miri nextest run                                    # one Miri process per test
cargo +nightly miri test --target s390x-unknown-linux-gnu          # big-endian check
```

Other Miri flags: `-Zmiri-seed=N` (replay one schedule), `-Zmiri-disable-isolation` (host env,
clock, files), `-Zmiri-ignore-leaks`, `-Zmiri-backtrace=full`, `-Zmiri-symbolic-alignment-check`,
`-Zmiri-preemption-rate` (default 0.01). Limits: no FFI (only the experimental, unsound
`-Zmiri-native-lib`), no inline assembly, no networking, slow. Isolate FFI behind a trait and test
the unsafe Rust with a pure-Rust fake; mark heavy tests `#[cfg_attr(miri, ignore)]`; shrink sizes
with `if cfg!(miri) { 10 } else { 10_000 }`.

| Tool | Command | Finds |
|---|---|---|
| AddressSanitizer | `RUSTFLAGS=-Zsanitizer=address RUSTDOCFLAGS=-Zsanitizer=address cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu` | out-of-bounds, use-after-free, also through FFI |
| ThreadSanitizer | same with `-Zsanitizer=thread` (needs `-Zbuild-std`; `rustup component add rust-src`) | data races across real threads and C code |
| cargo-careful | `cargo install cargo-careful`, then `cargo +nightly careful test` | std built with debug assertions: alignment and null checks in `ptr::read`/`write`, collection invariants, strict init checks; `#[cfg(careful)]` available |
| Kani | `cargo install --locked kani-verifier && cargo kani setup`, then `cargo kani --harness name` | proves properties for **all** inputs of small kernels (bounded loops) |
| cargo-geiger | `cargo geiger` | unsafe usage counts including dependencies |

Sanitizer targets (unstable book): ASan on `x86_64`/`aarch64` Linux, `x86_64`/`aarch64` Apple
Darwin, FreeBSD x86_64, Fuchsia; TSan on the same minus Fuchsia. Kani supports x86_64 Linux and
x86_64/aarch64 macOS.

```rust
#[cfg(kani)]
#[kani::proof]
#[kani::unwind(9)]                                       // loop runs at most CAP = 8 times
fn push_slot_is_free() {                                  // for ALL head/tail, wrap-around included
    const CAP: usize = 8;                                 // power of two, as the API asserts
    let head: usize = kani::any();
    let tail: usize = kani::any();
    let len = tail.wrapping_sub(head);
    kani::assume(len < CAP);                              // not full, so push writes slot tail & mask
    for k in 0..CAP {
        if k < len { assert_ne!(head.wrapping_add(k) & (CAP - 1), tail & (CAP - 1)); }
    }
}
```

The same property brute-forced on stable over 1024 states (bases 0, 5, 2^40, `usize::MAX - 20`)
holds; with capacity 6 and mask 5 it fails at head 0, tail 2 (`2 & 5 == 0`), which is why
`channel()` asserts `cap.is_power_of_two()`.

## 9. Lint policy

```toml
[lints.rust]
unsafe_op_in_unsafe_fn = "deny"
[lints.clippy]
undocumented_unsafe_blocks = "deny"      # restriction: every unsafe block needs a // SAFETY: comment
multiple_unsafe_ops_per_block = "warn"   # restriction: one unsafe op per block, one proof per op
missing_safety_doc = "deny"              # style (warn by default): pub unsafe fn needs a # Safety section
unnecessary_safety_comment = "warn"      # restriction: SAFETY comment on code that is not unsafe
```

Crates with no unsafe declare `#![forbid(unsafe_code)]` (cannot be re-allowed inside, unlike
`deny`). Also on by default: clippy `not_unsafe_ptr_arg_deref` (correctness, deny) rejects a `pub`
safe fn that dereferences a raw-pointer argument. Measured: one `unsafe { *p + *p.add(1) }` block
triggers both "unsafe block missing a safety comment" and "this `unsafe` block contains 3 unsafe
operations, expected only one" (two derefs plus `add`).

## 10. SAFETY comments and the worked example

```rust
// SAFETY:
// - `idx < self.len` is checked on the line above, so `ptr.add(idx)` stays in the allocation.
// - Elements 0..len are initialised (invariant kept by `push` and `truncate`).
// - We hold `&self`, and no method hands out `&mut` to elements while `&self` exists.
unsafe { &*self.ptr.as_ptr().add(idx) }
```

A comment that restates the operation ("dereferencing the pointer") fails review. `pub unsafe fn`
gets a `/// # Safety` section listing what the caller must guarantee.

**Worked example: Miri finds an aliasing bug in a hand-written ring buffer.** A single-producer
single-consumer ring with `&self` methods so both threads can share it:

```rust
pub struct Ring<T> { buf: Box<[MaybeUninit<T>]>, head: AtomicUsize, tail: AtomicUsize }
unsafe impl<T: Send> Sync for Ring<T> {}
impl<T> Ring<T> {
    pub fn push(&self, v: T) -> Result<(), T> {
        let tail = self.tail.load(Relaxed);
        if tail - self.head.load(Acquire) == self.buf.len() { return Err(v); }
        let slots = self.buf.as_ptr() as *mut MaybeUninit<T>;          // BUG
        unsafe { slots.add(tail % self.buf.len()).write(MaybeUninit::new(v)) };
        self.tail.store(tail + 1, Release);
        Ok(())
    }
    // pop: reads self.buf[head % len].assume_init_read(), then head.store(head + 1, Release)
}
```

`cargo +nightly miri test` (a test that pushes one `String` and pops it):

```text
error: Undefined Behavior: attempting a write access using <1151> at alloc326[0x0], but that tag only grants SharedReadOnly permission for this location
19 |         unsafe { slots.add(tail % self.buf.len()).write(MaybeUninit::new(v)) };
help: <1151> was created by a SharedReadOnly retag at offsets [0x0..0x60]
18 |         let slots = self.buf.as_ptr() as *mut MaybeUninit<T>; // BUG: write through a shared borrow
```

`MIRIFLAGS=-Zmiri-tree-borrows` agrees: "write access through <1122> at alloc326[0x0] is forbidden
... the accessed tag <1122> has state Frozen which forbids this child write access". Diagnosis: the
pointer comes from `&[MaybeUninit<T>]` (read-only), so the write is UB whatever the ordering. The
audit (step 3) finds a second bug Miri cannot see in a one-thread test: `push(&self)` lets two
producers race on one slot through a `Sync` type.

Fix: `UnsafeCell` slots, power-of-two capacity with mask arithmetic on wrapping counters, and
non-`Clone` `Producer`/`Consumer` handles whose `&mut self` methods enforce one producer and one
consumer:

```rust
struct Ring<T> { slots: Box<[UnsafeCell<MaybeUninit<T>>]>, mask: usize, head: AtomicUsize, tail: AtomicUsize }
// SAFETY: only one Producer and one Consumer exist (not Clone, methods take &mut self); slot
// ownership moves via Release/Acquire on `tail` (to the consumer) and `head` (back to the producer).
unsafe impl<T: Send> Sync for Ring<T> {}
pub struct Producer<T> { ring: Arc<Ring<T>> }
pub struct Consumer<T> { ring: Arc<Ring<T>> }

impl<T> Producer<T> {
    pub fn push(&mut self, v: T) -> Result<(), T> {
        let r = &*self.ring;
        let tail = r.tail.load(Relaxed);                                   // only we write tail
        if tail.wrapping_sub(r.head.load(Acquire)) == r.slots.len() { return Err(v); }
        // SAFETY: `tail & mask < len` (len is a power of two, mask = len - 1); the slot is empty
        // and unaliased: the consumer finished it before its Release store to `head`, which our
        // Acquire load observed; `&mut self` rules out a second producer.
        unsafe { (*r.slots[tail & r.mask].get()).write(v) };
        r.tail.store(tail.wrapping_add(1), Release);                       // publish the slot
        Ok(())
    }
}
// Consumer::pop mirrors it with assume_init_read and head; Drop for Ring drops slots head..tail.
```

Verification, all on Miri nightly 2026-10-18: a two-thread test sending 200 `String`s through
capacity 4, then leaving two items in the ring, prints "received 200 in order" and reports no UB
and no leak under Stacked Borrows and under Tree Borrows; deleting `impl Drop for Ring` turns it
into "memory leaked: ... (Rust heap, size: 6, align: 1)". Mutation check: weakening the publishing store to
`r.tail.store(tail.wrapping_add(1), Relaxed)` makes Miri report "Data race detected between (1)
retag write on thread `unnamed-1` and (2) retag read of type `std::mem::MaybeUninit<std::string::String>`
on thread `main`", so the test does exercise the ordering. Next: `-Zmiri-many-seeds` in CI, a loom
model of push/pop, and the Kani harness above for the index arithmetic.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Miri "only grants SharedReadOnly permission" / "has state Frozen" | write through a pointer derived from `&T` or `as_ptr()` | `UnsafeCell`, or derive from `&mut`/`as_mut_ptr()` |
| UB with zero-length input | `from_raw_parts(ptr::null(), 0)` | `NonNull::dangling()` |
| double drop after a panic in user code | `len` or init state updated after calling user code | leak amplification or a repair guard |
| sound in tests, racy in production | `unsafe impl Sync` justified by "callers only use one thread" | encode the rule in the type system (handles, `&mut self`, `!Sync` markers) |
| "Data race detected" from Miri | `Relaxed` where `Release`/`Acquire` publication is needed | pair Release with Acquire on the same atomic |
| Miri passes, production crashes in FFI | Miri cannot execute FFI | ASan/TSan builds, a pure-Rust fake under Miri |
| `transmute` breaks on another target | size, endianness or layout assumed (`repr(Rust)` has no fixed layout) | `#[repr(C)]`, `bytemuck`/`zerocopy`, `from_le_bytes` |
| `Vec::from_raw_parts` corrupts the heap | parts not from a `Vec` with the same `T` and allocator | `ManuallyDrop::new(vec)` then take `as_mut_ptr`, `len`, `capacity` from it |
| SAFETY comment no longer matches the code | the invariant changed in a safe function of the module | audit the whole module on every change; `undocumented_unsafe_blocks` only checks presence |
| lock-free structure intermittently fails | ABA or missing memory reclamation | `crossbeam-epoch`, or a `Mutex` |

Related: `rust-ffi-bindings`, `rust-testing-fuzzing`, `rust-ownership-lifetimes`, `rust-async-tokio`,
`rust-performance`, hub `rust-craft`.
