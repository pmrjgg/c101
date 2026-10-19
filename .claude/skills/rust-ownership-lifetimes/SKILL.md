---
name: rust-ownership-lifetimes
description: "Rust borrow-checker and lifetime playbook. Covers parameter and smart-pointer choice tables, fix recipes for each borrow error code (E0382 to E0716, E0373, non-Send across .await), split borrows, elision, 'static and variance, the edition-2024 capture and temporary-drop rules, arenas for graphs, closures and NLL false positives. Load when a borrow or lifetime error blocks a build, or when choosing ownership for a new API."
when_to_use: "rustc errors E0382, E0499, E0502, E0505, E0506, E0507, E0597, E0716, E0373, E0106, 'lifetime may not live long enough', 'future cannot be sent between threads safely', a 'RefCell already borrowed' panic, impl Trait borrow errors after an edition-2024 migration, or designing signatures, reference-holding structs, graphs and self-referential data in .rs files."
---

# Rust ownership and lifetimes

Baseline: stable Rust, edition 2024 (rustc >= 1.85). Every error message quoted below was reproduced
on rustc 1.99.1 (October 2026). Full repros with compiler output:
[borrow error catalog](references/borrow-error-catalog.md).

Procedure when the borrow checker says no: (1) read the error code and the three spans (where the
borrow starts, the conflicting use, where the borrow is still needed); (2) find the row in section 3;
(3) apply the first fix that keeps the design; (4) only then consider `clone()`, `Rc`/`Arc` or
`RefCell`. Never reach for `unsafe` to silence the borrow checker.

## 1. Choose the signature first

| The function needs to | Take | Note |
|---|---|---|
| read | `&T`, `&str`, `&[T]`, `&Path`, `&OsStr` | never `&String`, `&Vec<T>`, `&PathBuf` (clippy `ptr_arg`, warn by default); `&String` coerces to `&str` for free |
| mutate in place | `&mut T`, `&mut [T]` | `&mut Vec<T>` only when it must push or pop |
| store or consume | `T` (owned) | the caller decides whether to clone; no hidden clones inside |
| store, accept `&str` and `String` | `impl Into<String>` | at most one allocation; owned callers pay nothing |
| return usually-unchanged text | `Cow<'a, str>` | `Cow::Borrowed` on the fast path, `Cow::Owned` when modified |
| iterate any collection | `impl IntoIterator<Item = T>` | accepts `Vec`, arrays, ranges, iterators |
| accept path-like values | `impl AsRef<Path>` | forward to a private `fn inner(p: &Path)` to limit monomorphization |
| call back, not stored | `impl Fn(A) -> B` / `F: FnMut(A) -> B` | static dispatch, inlinable |
| call back, stored or heterogeneous | `Box<dyn Fn(A) -> B + Send + Sync>` | `Box<dyn ..>` means `+ 'static` unless a lifetime is written |
| async callback that borrows its argument | `impl AsyncFn(&Req) -> Resp` (1.85) | `F: Fn(&Req) -> Fut` cannot tie `Fut` to the borrow |
| return a view into `self` | `&T`, `impl Iterator<Item = &T>` | edition 2024 RPIT already captures `'_` |

Return owned data unless the result is a view into an input. A struct that holds references
(`struct Parser<'a> { src: &'a str }`) is right for short-lived views (parsers, iterators, guards);
long-lived state holds owned data or indices (section 7).

## 2. Sharing and interior mutability

| Need | Use | Caveat |
|---|---|---|
| single owner on the heap, recursive type, cheap move of a big value | `Box<T>` | |
| shared, one thread | `Rc<T>`; mutate via `Cell<T>` (Copy values) or `RefCell<T>` | `RefCell` checks at run time and panics: "RefCell already borrowed" |
| back-pointers, caches, observers | `Weak<T>` (`Rc::downgrade`, `upgrade()`) | strong cycles leak |
| shared across threads, immutable | `Arc<T>`; `Arc<str>`, `Arc<[T]>` | `Arc<str>` is one allocation less than `Arc<String>` |
| shared, mutable, short critical sections | `Arc<Mutex<T>>` / `Arc<RwLock<T>>` (std or `parking_lot`) | no guard across `.await` (see `rust-async-tokio`) |
| read-mostly config replaced as a whole | `arc_swap::ArcSwap<T>`: `load()`, `store(Arc::new(v))`, `rcu(\|old\| ..)` | readers never block |
| initialise-once global | `std::sync::LazyLock` (1.80) / `OnceLock` | never `static mut` (references to it are denied in 2024) |
| counters and flags | `AtomicU64`, `AtomicBool` (`Relaxed` for pure counters) | orderings: `rust-unsafe-soundness` |
| hand data to another thread or task | channels: `std::sync::mpsc`, crossbeam, `tokio::sync::mpsc` | message passing beats shared state |

Clones that are fine: `Arc::clone(&x)` (one atomic increment; clippy `clone_on_ref_ptr`, a
restriction lint, enforces this spelling so reviewers see a refcount bump); a small value (a few
words) copied out once outside hot loops; one clone per spawned task at the boundary. Clones that are
not fine: a `Vec`, `String` or map cloned inside a loop to silence E0502.

## 3. Error code to cause to fix

| Code and message | Typical cause | Fix, in order of preference |
|---|---|---|
| E0382 borrow of moved value | value moved into a call, closure or `for x in v`, then used | pass `&v`; iterate `&v`; move after the last use; `clone()` only if cheap |
| E0499 cannot borrow `s` as mutable more than once at a time | two `&mut` paths, e.g. two `&mut self` getters | split borrows (section 4); end the first borrow sooner |
| E0502 cannot borrow `v` as mutable because it is also borrowed as immutable | a reference into a collection is alive across a write | copy the small value out (`let x = v[0];`), collect keys first, entry API, indices |
| E0505 cannot move out of `s` because it is borrowed | move while a reference lives | end the borrow (inner block) or move after the last use |
| E0506 cannot assign to `n` because it is borrowed | assignment while a reference lives | compute the new value, let the reference die, then assign |
| E0507 cannot move out of `self.buf` which is behind a mutable reference | taking a field out of `&mut self` | `mem::take(&mut self.buf)` (needs `Default`), `self.opt.take()`, `mem::replace(&mut self.state, State::Idle)` |
| E0597 `s` does not live long enough | a reference outlives the local it points to | move the owner to the outer scope; return owned data |
| E0716 temporary value dropped while borrowed | `let parts: Vec<&str> = String::from(line).split(' ').collect();` or `r = &String::new();` (assignment) | bind the temporary with its own `let`; `let s = &make();` is fine (the `let` extends the temporary) |
| E0373 closure may outlive the current function, but it borrows `v` | `thread::spawn`/`tokio::spawn` closure borrows locals | `move` plus owned or `Arc` data; `std::thread::scope` to borrow |
| E0277 `Rc<i32>` cannot be sent between threads safely | `!Send` value moved into a thread | `Arc`; keep the value on its thread |
| (no code) future cannot be sent between threads safely | `Rc`, `RefCell` borrow or std `MutexGuard` alive across `.await` in a spawned future | end its scope before the `.await`; `Arc`; tokio `Mutex`; `spawn_local` |
| (no code) lifetime may not live long enough | output tied to the wrong input; help may suggest `'b: 'a` | link the output to the input it borrows from; add the bound only if true |
| E0106 missing lifetime specifier | two input references and an output reference | name the lifetime of the input the output borrows from |

The E0277 code appears when the `Send` bound is checked directly (`thread::spawn`); `tokio::spawn`
prints the uncoded form plus a note naming the value ("has type `MutexGuard<'_, i32>` which is not
`Send`") and the `.await` that keeps it alive.

## 4. Split borrows

```rust
// Struct fields: destructure, then borrow each field independently.
let Game { players, scores, .. } = self;
for p in players.iter() { *scores.entry(*p).or_default() += 1; }

// Slices
let (left, right) = buf.split_at_mut(mid);          // two disjoint &mut halves
if let Some((first, rest)) = buf.split_first_mut() { *first = rest.len() as u8; }
for pair in buf.chunks_exact_mut(2) { pair.swap(0, 1); }   // remainder via into_remainder()

// get_disjoint_mut (1.86)
let [a, b] = v.get_disjoint_mut([0, 3])?;           // Result<_, GetDisjointMutError>
let [lo, hi] = v.get_disjoint_mut([0..2, 4..6])?;   // ranges too
let [x, y] = map.get_disjoint_mut(["a", "b"]);      // HashMap: [Option<&mut V>; N]
```

| Technique | When | Watch out |
|---|---|---|
| destructure `self` | a method touches two fields | a call to `self.other_method()` borrows all of `self` |
| `split_at_mut`, `split_first_mut`, `split_last_mut`, `chunks_exact_mut`, `iter_mut` | disjoint parts of one slice | `split_at_mut` panics if `mid > len` |
| slice `get_disjoint_mut` | N arbitrary elements or ranges | returns `Err(OverlappingIndices)` or `Err(IndexOutOfBounds)` |
| `HashMap::get_disjoint_mut` | N entries of one map | **panics** on duplicate keys ("duplicate keys found") |
| indices instead of references | graph-like access in a `Vec` | stale after `remove`; use generational keys (section 7) |
| collect keys, then mutate | remove or update while iterating | prefer `retain`, `Vec::extract_if` (1.87), `HashMap::extract_if` (1.88) |
| two-phase borrows | `v.push(v.len())` compiles | covers implicit `&mut` (method receivers, compound assignment), not an explicit `let r = &mut v;` |

## 5. Lifetime rules

Elision in `fn` signatures:
1. Each elided input lifetime becomes its own lifetime parameter.
2. Exactly one input lifetime: it is given to every elided output lifetime.
3. Several inputs, one of them `&self` or `&mut self`: `self`'s lifetime goes to every elided output.

Anything else is E0106. Rule 3 bites: `fn pick(&self, key: &str) -> &str` cannot return `key`
("lifetime may not live long enough"); write `fn pick<'k>(&self, key: &'k str) -> &'k str`, or
`fn pick<'a>(&'a self, key: &'a str) -> &'a str` when either may be returned.

Name lifetimes when the output could come from two inputs, in structs and enums holding references,
for trait-object bounds (`Box<dyn Trait + 'a>`) and in `where T: 'a` bounds. Write `'_` in paths
(`Formatter<'_>`, `impl Parser<'_>`) so elided lifetimes stay visible.

`T: 'static` means T holds no non-`'static` borrows: `String`, `Vec<u8>`, `Arc<T>` are `'static`;
it does not mean "lives forever". `&'static T` is a reference valid for the whole program (literals,
statics, `Box::leak`). `thread::spawn`, `tokio::spawn` and `Box<dyn Any>` need `'static`: move
owned data or `Arc` in, never `Box::leak` per request.

| Type | Variance in its lifetime | Variance in `T` |
|---|---|---|
| `&'a T` | covariant | covariant |
| `&'a mut T` | covariant | **invariant** |
| `Box<T>`, `Vec<T>`, `Rc<T>`, `Arc<T>`, `*const T`, `PhantomData<T>` | | covariant |
| `Cell<T>`, `RefCell<T>`, `UnsafeCell<T>`, `Mutex<T>`, `*mut T` | | **invariant** |
| `fn(T) -> U` | | contravariant in `T`, covariant in `U` |
| `dyn Trait<T> + 'a` | covariant | invariant |

Invariance in practice: `push_short(&mut names, &owned)` where `names: Vec<&'static str>` and
`fn push_short<'a>(v: &mut Vec<&'a str>, s: &'a str)` fails with E0597 ("argument requires that
`owned` is borrowed for `'static`"), because `&mut Vec<&'a str>` cannot shrink `'static` to `'a`.

Higher-ranked bounds: `F: for<'a> Fn(&'a str) -> &'a str` means "for every caller lifetime";
elided `Fn(&str) -> &str` already means exactly that. Write `for<'a>` explicitly in where clauses
such as `where for<'a> &'a C: IntoIterator<Item = &'a T>`.

## 6. Edition 2024 changes that affect borrowing

| Change | Edition 2021 | Edition 2024 | Action |
|---|---|---|---|
| return-position `impl Trait` captures | type parameters only, unless a lifetime is named | **every** in-scope generic and lifetime | narrow with `+ use<'a, T>` or `+ use<>` (1.82; in traits since 1.87) |
| `if let` scrutinee temporaries | live to the end of the whole `if`/`else` | dropped before `else` | lint `if_let_rescope` rewrites to `match` where drop order matters |
| tail-expression temporaries | dropped after the block's locals | dropped before them | lint `tail_expr_drop_order` flags changed drops |

Verified on 1.99.1: `fn indices(data: &[u32], key: &str) -> impl Iterator<Item = usize>` compiles in
2021 but in 2024 the iterator captures `key`, giving E0597 at the call site; `-> impl Iterator<Item =
usize> + use<>` fixes it, `+ use<'d>` keeps only the data borrow. `if let Some(v) = *cache.borrow()
{ .. } else { *cache.borrow_mut() = .. }` panics with "RefCell already borrowed" in 2021 and works in
2024. `fn len() -> usize { let c = RefCell::new(String::new()); c.borrow().len() }` is E0597 in 2021,
fine in 2024.

Migration:

```bash
cargo fix --edition --all-targets --all-features   # still on 2021: applies rust_2024_compatibility fixes
# then set edition = "2024" in Cargo.toml (or [workspace.package])
cargo build --all-targets --all-features && cargo test
cargo fmt                                           # the 2024 style edition reformats some code
git diff                                            # review every added use<..> and if-let -> match
```

Review the diff: `impl_trait_overcaptures` adds `use<..>` conservatively to keep 2021 behaviour
(often removable later); `if_let_rescope` matters where the scrutinee holds a lock guard or `Ref`,
since an `else` that used to run with the guard alive now runs after it is released.

## 7. Self-referential and graph data

| Shape | Use | Notes |
|---|---|---|
| graph with deletions, stable handles | `slotmap::SlotMap` + `new_key_type! { struct NodeId; }` | generational keys: a removed key stays invalid even when the slot is reused; `SecondaryMap` for side data; `HopSlotMap` is deprecated |
| built once, freed together, one type | `typed_arena::Arena<T>`; links as `Cell<Option<&'a Node<'a>>>` | `alloc` returns `&mut T`; cycles are fine |
| many small mixed allocations per request or frame | `bumpalo::Bump` | **does not run `Drop`** for `alloc`ed values; use `bumpalo::boxed::Box` (feature `boxed`) when drop matters |
| simple tree | `Vec<Node>` with `parent: Option<usize>` | indices are not lifetime-checked; tombstone instead of `remove` |
| owner plus borrowed view (`String` plus parsed `&str` tokens) | store `Range<usize>` offsets, or `self_cell!` | `#[covariant]` gives `borrow_dependent()`, `#[not_covariant]` only `with_dependent()` |
| same, richer API | `ouroboros` | |
| shared ownership with parent links | `Rc<RefCell<Node>>` children, `Weak` parent | single-threaded; `Arc<Mutex<..>>` across threads |

Soundness history to check before adopting (RustSec): `self_cell` RUSTSEC-2023-0070 (fixed in 0.10.3
and 1.0.2), `ouroboros` RUSTSEC-2023-0042 (fixed in 0.16.0), `owning_ref` RUSTSEC-2022-0040 (no
fix), `rental` unmaintained (RUSTSEC-2021-0134), `bumpalo` RUSTSEC-2022-0078 (fixed in 3.11.1).
Run `cargo deny check advisories` after adding any of them. Never hand-roll self-references with raw
pointers: moving the struct invalidates them.

## 8. Closures

- The body decides the capture (`&`, `&mut`, by value) and the trait: `Fn` reads captures, `FnMut`
  mutates them, `FnOnce` moves out of them. Every closure is `FnOnce`; accept the weakest bound you
  need (`FnOnce` for run-once callbacks, `FnMut` for loops, `Fn` for shared or concurrent calls).
- `move` captures everything used by value. Clone first, then move the clone:
  `let tx = tx.clone(); thread::spawn(move || tx.send(1))`.
- Disjoint field capture (2021+): `|| self.cfg.len()` captures only `self.cfg`, so `self.buf` stays
  usable; a method call inside the closure still captures all of `self`.
- Async closures (1.85): `async |x| { .. }` and `async move || { .. }` with bounds `AsyncFn`,
  `AsyncFnMut`, `AsyncFnOnce` (in the prelude). The returned future may borrow the closure's
  captures, so `F: AsyncFnMut() -> Option<u32>` can mutate a captured counter across calls, which
  `F: FnMut() -> Fut` cannot express.

## 9. Known borrow-checker false positives

NLL "problem case #3": a borrow returned conditionally (from `if let`, `match` or a loop) is treated
as live on every path, so the other path cannot mutate. Both shapes below are rejected by stable
1.99.1 and beta 1.100 and accepted by nightly 1.101 (2026-10-18), where the Polonius Alpha borrow
checker has been on by default since August 2026 (opt out: `-Zpolonius=off`; stabilization targeted
for the end of 2026, re-check on every toolchain bump).

```rust
// E0502: map case            // E0499: loop case
if let Some(d) = cache.get(key) { return d; }    for s in v.iter_mut() { if s == needle { return s; } }
cache.insert(key.to_owned(), load(key));         v.push(needle.to_owned());
```

Workarounds on stable: (1) look up, then borrow (`contains_key`, or `position` then `&mut v[i]`);
(2) the entry API; (3) return an index or key instead of a reference; (4) the `polonius-the-crab`
crate (0.6) for cases with no cheap second lookup; (5) never launder the reference through a raw
pointer.

## 10. Worked example: get_or_load cache rejected with E0502

```rust
fn get_or_load<'a>(cache: &'a mut HashMap<String, Data>, key: &str) -> &'a Data {
    if let Some(d) = cache.get(key) { return d; }
    cache.insert(key.to_owned(), load(key));
    &cache[key]
}
```

```text
error[E0502]: cannot borrow `*cache` as mutable because it is also borrowed as immutable
4 |     if let Some(d) = cache.get(key) { return d; }
  |                      -----                   - returning this value requires that `*cache` is borrowed for `'a`
5 |     cache.insert(key.to_owned(), load(key));
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ mutable borrow occurs here
```

```rust
// A: entry API; one hash lookup, but allocates the key String on every call, hits included
cache.entry(key.to_owned()).or_insert_with(|| load(key))

// B: contains_key + insert; no allocation on hits, but 2 lookups per hit (3 per miss)
if !cache.contains_key(key) { cache.insert(key.to_owned(), load(key)); }
&cache[key]

// C: hashbrown::HashMap::entry_ref; 1 lookup, allocates only on a miss (needs K: From<&Q>)
cache.entry_ref(key).or_insert_with(|| load(key))
```

Hit-path cost, ns per lookup (Rust Playground, stable 1.99.1 release, 1000 keys, 200 000 hits,
median of 9 runs; all three variants on the same hasher):

| Variant | SipHash (std default), 8-byte keys | SipHash, 64-byte keys | foldhash (hashbrown default), 8 B | foldhash, 64 B |
|---|---|---|---|---|
| A `entry(key.to_owned())` | 22.2 | 37.7 | 20.9 | 28.2 |
| B `contains_key` + index | 33.2 | 58.8 | 12.9 | 23.7 |
| C `entry_ref` | 13.6 | 28.1 | 7.1 | 12.4 |

Decision: C if a `hashbrown` dependency is acceptable. With std's SipHash, A beats B (allocating the
key costs less than a second SipHash pass); with a fast hasher B beats A. Once Polonius ships on
stable, the original code becomes legal and is as cheap as C on hits (one lookup, no allocation).
Re-measure on your own key sizes and hit ratio with criterion (`rust-performance`) before choosing.

## 11. Review checklist

- [ ] Parameters borrow by default; owned only where stored or consumed; no `&String`/`&Vec`/`&PathBuf`.
- [ ] No `clone()` of collections in hot paths to silence E0502/E0499; `Arc::clone(&x)` spelled out.
- [ ] No `RefCell` borrow alive across a call that can re-enter (callbacks, observers, `Drop`): copy
      the value out, release the borrow, then call.
- [ ] No `static mut`; globals use `LazyLock`/`OnceLock`/atomics.
- [ ] Structs with lifetimes are short-lived views; long-lived graphs use arenas, slotmap or indices.
- [ ] `Rc`/`RefCell` never cross threads or `.await` in spawned futures.
- [ ] Edition-2024 `use<..>` bounds are as narrow as the API allows; no leftover 2021-preserving captures.
- [ ] Every `unsafe` added "for the borrow checker" is removed; real unsafe follows `rust-unsafe-soundness`.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| panic "RefCell already borrowed" | overlapping `borrow_mut`, a re-entrant callback, or a 2021 `if let` scrutinee guard alive in `else` | shorten borrows; copy out before calling back; edition 2024 |
| memory grows with `Rc`/`Arc` graphs | strong reference cycle | `Weak` back-pointers, arena or slotmap |
| `impl Trait` borrow errors after migrating to 2024 | RPIT now captures every lifetime | `+ use<..>` listing only what the value borrows |
| deadlock or double-borrow appears or vanishes after migration | `if let` / tail temporaries now drop earlier | read the `if_let_rescope` / `tail_expr_drop_order` warnings |
| `HashMap::get_disjoint_mut` panics | duplicate keys | dedupe keys first or use the slice version, which returns `Err` |
| `spawn` demands `'static` | closure borrows locals | `move` owned or `Arc` data, `thread::scope`; never `Box::leak` per call |
| wrong element mutated after `Vec::remove` | stale indices | generational keys (slotmap) or tombstones |
| files or sockets never closed | values allocated in `bumpalo::Bump` skip `Drop` | `bumpalo::boxed::Box` or a typed arena |
| `mem::take` does not compile | field type has no `Default` | `mem::replace` with a sentinel, or wrap in `Option` and `take()` |
| `Vec<&'static str>` rejects a short-lived `&str` through `&mut` | invariance of `&mut T` in `T` | make the element lifetime generic or store `String` |

Related: `rust-traits-generics`, `rust-error-handling`, `rust-async-tokio`, `rust-unsafe-soundness`,
`rust-performance`, hub `rust-craft`.
