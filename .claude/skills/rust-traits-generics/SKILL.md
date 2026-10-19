---
name: rust-traits-generics
description: "Rust trait and generic API design. Covers generics vs dyn vs enum dispatch with measured costs, associated types vs type parameters, GATs, dyn-compatibility and trait upcasting, sealed and extension traits, newtypes for the orphan rule, async fn in traits with Send bounds, diagnostic attributes, typestate and semver hazards. Load when designing or reviewing a Rust public API or trait hierarchy."
when_to_use: "Designing or reviewing pub traits, generic functions or plugin registries in .rs files; errors E0038 'not dyn compatible', E0117/E0210 orphan rule, E0119 conflicting impls, E0107 turbofish on impl Trait, the async_fn_in_trait lint, 'future cannot be sent' from a trait method; choosing Box<dyn Trait> vs generics vs enum; preparing a library release with cargo-semver-checks."
---

# Rust traits and generics

Baseline: stable Rust, edition 2024. Feature versions are given where they matter; every code
shape below compiled (or failed as stated) on rustc 1.99.1 in October 2026.

## 1. Static, dynamic or enum dispatch

| Criterion | Generics (`T: Trait`, `impl Trait`) | `dyn Trait` | `enum` of known types |
|---|---|---|---|
| call cost | inlined, zero overhead | indirect call, no inlining across it | `match` jump, inlinable arms |
| measured, trivial body (section 10) | n/a | 1.92 ns/call | 0.62 ns/call |
| heterogeneous collection | no (one `T` per container) | `Vec<Box<dyn Trait>>` | `Vec<Enum>` |
| open set (downstream crates add types) | yes | yes | **no**: closed set, adding a variant is a breaking change |
| compile time and binary size | grows per instantiation | one copy | one copy |
| element size | `size_of::<T>()` | 16-byte fat pointer plus a heap allocation | largest variant plus tag, no allocation |
| object rules | none | must be dyn compatible (section 3) | none |
| hide the concrete type in a return | `-> impl Trait` | `-> Box<dyn Trait>` | return the enum |

Rules: generics for hot paths and small APIs; `dyn` for plugin points owned by other crates, for
long-lived heterogeneous collections, and to cut compile time; an enum when the set of types is
closed and the call is hot (macro help: `enum_dispatch`). Measure bloat before refactoring:

```bash
cargo llvm-lines --release | head -30     # lines of LLVM IR per generic instantiation
cargo bloat --release --crates            # binary size by crate
```

Fight monomorphization bloat with a non-generic inner function (std's `fs::read` does this):
`pub fn load(p: impl AsRef<Path>) -> io::Result<Vec<u8>> { fn inner(p: &Path) -> .. { .. } inner(p.as_ref()) }`.

## 2. Associated type, type parameter or associated const

| Use | When | Example |
|---|---|---|
| associated type | each implementor has exactly one natural choice; callers should not have to name it | `Iterator::Item`, `Deref::Target` |
| type parameter | one type implements the trait several ways | `From<T>`, `Add<Rhs>`, `AsRef<T>` |
| both | parameterised input, determined output | `trait Add<Rhs = Self> { type Output; }` |
| associated const | per-type compile-time value | `const ID: u16;` (makes the trait non-dyn-compatible) |
| generic associated type (1.65) | the associated type borrows from `self` | lending iterators, borrowed views |

```rust
trait LendingIter {
    type Item<'a> where Self: 'a;                       // the where-clause is required
    fn next(&mut self) -> Option<Self::Item<'_>>;
}
struct Windows { buf: Vec<u8>, pos: usize }
impl LendingIter for Windows {
    type Item<'a> = &'a mut [u8] where Self: 'a;
    fn next(&mut self) -> Option<&mut [u8]> {
        if self.pos + 2 > self.buf.len() { return None; }
        self.pos += 1;
        Some(&mut self.buf[self.pos - 1..self.pos + 1])   // overlapping &mut windows: impossible with Iterator
    }
}
// usage: while let Some(w) = it.next() { w[0] += 10; }   (no for-loop: not an Iterator)
```

GAT traits are not dyn compatible, and generic code over them often needs higher-ranked bounds;
use them only where `Iterator` plus collect or an index-based API does not work.

## 3. dyn compatibility (formerly "object safety")

A trait can be used as `dyn Trait` when: no supertrait requires `Sized`; it has no associated consts
and no GATs; every method either has a receiver of `&self`, `&mut self`, `Box<Self>`, `Rc<Self>`,
`Arc<Self>` or `Pin<P>` and no type parameters, no `Self` outside the receiver, no `async fn` and no
`-> impl Trait`, or is opted out with `where Self: Sized`. Violations are E0038 "the trait `X` is not
dyn compatible" with a note per culprit ("...because it contains associated const `ID`",
"...because method `it` references an `impl Trait` type in its return type").

```rust
trait Codec {
    fn name(&self) -> &str;                                            // dispatchable
    fn encode<W: std::io::Write>(&self, w: W) where Self: Sized;       // escape hatch: not callable on dyn
    fn boxed_clone(&self) -> Self where Self: Sized;
}
let c: &dyn Codec = &Json;            // OK; c.encode(..) is unavailable through the vtable
```

Trait upcasting (1.86): `trait Plugin: Debug + Send + Sync` lets `Box<dyn Plugin>` coerce to
`Box<dyn Debug + Send + Sync>`, `&dyn Plugin` to `&dyn Debug`.

Choosing bounds: put `Send + Sync` as supertraits when every implementor must be shareable
(`trait Plugin: Send + Sync`), then `Arc<dyn Plugin>` is thread-safe without repeating bounds.
Otherwise write them at the use site: `Box<dyn Handler + Send>`. `Box<dyn Trait>` is
`Box<dyn Trait + 'static>`; `&'a dyn Trait` is `+ 'a`; write `Box<dyn Trait + 'a>` to store
borrowing implementors. Errors crossing threads: `Box<dyn Error + Send + Sync + 'static>`.

## 4. Orphan rule, coherence, specialization

- You may `impl Trait for Type` only if the trait or the type is local. `impl From<Local> for Vec<u8>`
  is allowed (a local type appears as the first trait parameter); `impl Display for Vec<Local>` is
  not (E0117). Workaround: a newtype `pub struct Lines(pub Vec<Line>);` with the impls you need.
- Newtype plus `Deref` to the inner type is tempting but violates C-DEREF: it exposes every inner
  method (a `SortedVec` with `DerefMut` to `Vec` lets callers `push` out of order). Forward the
  methods you want, implement `AsRef`/`IntoIterator`, or expose `as_inner()`.
- Blanket impls (`impl<T: Display> Render for T`) block downstream impls for any `Display` type
  (E0119 conflicting implementations) and are a semver commitment: add them before 1.0 or never.
- Specialization is nightly-only (`min_specialization` is used inside std). Workarounds: a default
  method that specific impls override; separate traits or explicitly named methods; `TypeId`
  checks on `'static` types (folded away after monomorphization); autoref-based specialization only
  inside macros.

## 5. Patterns

```rust
// Sealed trait: downstream can use but not implement (C-SEALED)
mod private { pub trait Sealed {} }
pub trait Backend: private::Sealed { fn id(&self) -> u8; }
impl private::Sealed for Mem {}
impl Backend for Mem { fn id(&self) -> u8 { 0 } }

// Extension trait: add methods to foreign types
pub trait IterExt: Iterator {
    fn sum_sq(self) -> u64 where Self: Sized, Self::Item: Into<u64> {
        self.map(|x| { let v: u64 = x.into(); v * v }).sum()
    }
}
impl<I: Iterator> IterExt for I {}

// Typestate builder: build() exists only after url() was called
pub struct NoUrl; pub struct HasUrl;
pub struct ReqBuilder<S> { url: Option<String>, _s: std::marker::PhantomData<S> }
impl ReqBuilder<NoUrl> {
    pub fn new() -> Self { Self { url: None, _s: std::marker::PhantomData } }
    pub fn url(self, u: &str) -> ReqBuilder<HasUrl> { ReqBuilder { url: Some(u.into()), _s: std::marker::PhantomData } }
}
impl ReqBuilder<HasUrl> { pub fn build(self) -> String { self.url.expect("typestate guarantees url") } }
```

| Pattern | Use for | Note |
|---|---|---|
| marker trait | capability flags (`trait Pod: Copy + 'static {}`) | `unsafe trait` when implementors promise an invariant |
| `PhantomData<T>` | "owns a T" for variance and drop check | `PhantomData<fn() -> T>` covariant without owning; `PhantomData<*const ()>` makes a type `!Send + !Sync` |
| `From<A> for B` | infallible, value-preserving conversion | implement `From`, never `Into`; `Into` comes free |
| `TryFrom<A>` | fallible conversion | `type Error` should be a real error type |
| `AsRef<T>` | cheap reference-to-reference in generic parameters | `fn open(p: impl AsRef<Path>)` |
| `Borrow<Q>` | map lookups by borrowed form (`HashMap<String, V>::get(&str)`) | `Eq`, `Hash` and `Ord` must agree between owned and borrowed forms |

## 6. Async fn in traits

`async fn` and `-> impl Trait` in traits are stable (1.75) but such traits are not dyn compatible
(E0038), and callers cannot require the returned future to be `Send`. For a `pub` trait rustc warns
(`async_fn_in_trait`): "use of `async fn` in public traits is discouraged as auto trait bounds
cannot be specified".

| Need | Declare |
|---|---|
| generic use on multi-threaded runtimes | `fn fetch(&self, id: u64) -> impl Future<Output = Result<Item>> + Send;` (impls may still write `async fn`) |
| both Send and local variants | `#[trait_variant::make(Fetch: Send)] pub trait LocalFetch { async fn fetch(&self) -> u32; }` generates `Fetch` with `+ Send` futures and a blanket impl of `LocalFetch` |
| `dyn` usage (registries, DI) | `#[async_trait::async_trait]` on trait and impls (boxes every call; `#[async_trait(?Send)]` for local), or `dynosaur` |
| bound a caller's future: `T: Fetch<fetch(..): Send>` | return-type notation: still nightly (E0658, issue #109417 on 1.99) |

```rust
pub trait Fetch { fn fetch(&self) -> impl std::future::Future<Output = u32> + Send; }
struct F;
impl Fetch for F { async fn fetch(&self) -> u32 { 7 } }      // allowed: async fn satisfies the RPITIT
tokio::spawn(async { F.fetch().await });                      // compiles: the future is Send
```

## 7. Rust API Guidelines checklist (abridged)

| ID | Rule |
|---|---|
| C-COMMON-TRAITS | derive `Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Default` where semantically valid; `Default` only with a meaningful default |
| C-DEBUG, C-DEBUG-NONEMPTY | every public type is `Debug`, never empty output |
| C-GOOD-ERR | error types implement `Error + Send + Sync + 'static` and `Display` (see `rust-error-handling`) |
| C-SEND-SYNC | types are `Send`/`Sync` where possible; test with `fn assert_send<T: Send>() {}` |
| C-CONV-TRAITS | conversions via `From`, `TryFrom`, `AsRef`, `AsMut` |
| C-SEALED, C-STRUCT-PRIVATE, C-NEWTYPE-HIDE | future-proofing: private fields, sealed traits, newtypes over exposed internals |
| C-BUILDER, C-CTOR | `new` as a static inherent method; a builder once there are more than about 3 optional parameters |
| C-CUSTOM-TYPE | arguments convey meaning through types, not `bool` or `Option` flags |
| C-DEREF | only smart pointers implement `Deref` |

Also: `Display` for user-facing text, `Debug` for developers; `#[non_exhaustive]` on public enums and
structs that will grow (downstream must use `..` and a wildcard arm; no effect inside the crate);
`#[must_use]` on functions whose result must not be dropped (`Result` is already `must_use`) and on
builders. `impl Trait` in argument position removes the turbofish for that parameter:
`collect_n::<Vec<u32>>(v)` is E0107 ("`impl Trait` cannot be explicitly specified as a generic
argument"), while explicit parameters of the same function stay nameable (`parse_into::<u32>("5")`).
Prefer named generics in public APIs where callers may need to disambiguate.

## 8. Readable trait errors

```rust
#[diagnostic::on_unimplemented(
    message = "`{Self}` is not a registered handler",
    label = "missing `impl Handler`",
    note = "implement `Handler` or wrap it with `handler_fn`"
)]
pub trait Handler { fn handle(&self); }

pub struct Wrap<T>(T);
#[diagnostic::do_not_recommend]                 // 1.85: keep this impl out of "implemented for" hints
impl<T: Fn()> Handler for Wrap<T> { fn handle(&self) { (self.0)() } }
```

`register(42u8)` then reports `error[E0277]: `u8` is not a registered handler` with the label and
the note. `on_unimplemented` (1.78) accepts `{Self}` and the trait's generic parameter names; both
attributes are hints that rustc may ignore, and malformed options only warn.

## 9. Semver hazards for traits

| Change | Breaks | Detected by `cargo semver-checks` lint |
|---|---|---|
| add a method without a default to a non-sealed trait | downstream impls | `trait_method_added` |
| add a supertrait to a non-sealed trait | downstream impls | `trait_added_supertrait` |
| make a trait non-dyn-compatible (generic method, assoc const, `async fn`) | `dyn Trait` users | `trait_no_longer_dyn_compatible` |
| seal a public trait | downstream impls | `trait_newly_sealed` |
| a type loses `Send`/`Sync`/`Unpin` through a new private field (`Rc`, `Cell`, raw pointer) | callers that spawn or share it | `auto_trait_impl_removed` |
| add a variant to an exhaustive enum | downstream `match` | `enum_variant_added` |
| add a blanket impl | downstream impls that now overlap (E0119) | no dedicated lint as of 0.51: review by hand |

```bash
cargo semver-checks --package mycrate                       # baseline: latest crates.io release
cargo semver-checks --package mycrate --baseline-rev v1.4.0 # baseline: a git revision
```

Pin auto traits in tests so a refactor cannot silently lose them:
`const _: () = { fn ok<T: Send + Sync>() {} let _ = ok::<Client>; };` (or `static_assertions`).

## 10. Worked example: plugin registry from Vec<Box<dyn Plugin>> to enum dispatch

Starting point: a registry applies every plugin to every sample.

```rust
pub trait Plugin: Send + Sync { fn apply(&self, x: f64) -> f64; }
pub struct Scale(pub f64);   impl Plugin for Scale  { fn apply(&self, x: f64) -> f64 { x * self.0 } }
pub struct Offset(pub f64);  impl Plugin for Offset { fn apply(&self, x: f64) -> f64 { x + self.0 } }
pub struct Clamp { pub lo: f64, pub hi: f64 }
impl Plugin for Clamp { fn apply(&self, x: f64) -> f64 { x.clamp(self.lo, self.hi) } }

fn run_dyn(reg: &[Box<dyn Plugin>], xs: &[f64]) -> f64 {
    xs.iter().map(|&x| reg.iter().fold(x, |acc, p| p.apply(acc))).sum()
}
```

Refactor: keep the trait (external plugins still possible), add a closed enum for built-ins.

```rust
pub enum AnyPlugin { Scale(Scale), Offset(Offset), Clamp(Clamp) }
impl AnyPlugin {
    #[inline]
    pub fn apply(&self, x: f64) -> f64 {
        match self { Self::Scale(p) => p.apply(x), Self::Offset(p) => p.apply(x), Self::Clamp(p) => p.apply(x) }
    }
}
fn run_enum(reg: &[AnyPlugin], xs: &[f64]) -> f64 {
    xs.iter().map(|&x| reg.iter().fold(x, |acc, p| p.apply(acc))).sum()
}
```

Measure: 64 plugins (round-robin kinds) times 20 000 samples = 1.28 M calls per run, 15 runs,
median, release build, inputs and registry passed through `std::hint::black_box` (full program
and a criterion harness: [dispatch benchmark](references/dispatch-benchmark.md)). Rust Playground,
stable 1.99.1, three independent executions:

| Plugin body | `Vec<Box<dyn Plugin>>` | `Vec<AnyPlugin>` | Ratio |
|---|---|---|---|
| trivial (one mul/add/clamp) | 1.92 ns/call | 0.62 ns/call | 3.1x |
| ~19 ns of math (`sin`, `sqrt`, `ln_1p`, `cos`) | 19.21 ns/call | 19.17 ns/call | 1.002x (noise) |
| element size | 16 B pointer + 8 to 16 B heap object | 24 B inline | |

Decision on these numbers: dispatch overhead is about 1.3 ns per call. Switch to the enum only
when the per-call work is under roughly 10 ns and the call is on a measured hot path; otherwise keep
`dyn` for its openness. A middle path keeps both: `enum AnyPlugin { Builtin(..), External(Box<dyn Plugin>) }`.
Re-run the criterion harness on the target hardware before committing; the ratio, not the absolute
ns, is what transfers.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| E0038 after adding a method | generic method, assoc const, `async fn` or `-> impl Trait` | `where Self: Sized` on that method, or move it to a sub-trait |
| `tokio::spawn` rejects a trait-method future | `async fn` in trait gives no `Send` guarantee | declare `-> impl Future<Output = T> + Send` or use `trait_variant` |
| compile times balloon | deep generic stacks instantiated per type | `cargo llvm-lines`; non-generic inner functions; `dyn` at boundaries |
| E0119 conflicting implementations | blanket impl overlaps a concrete impl | narrow the blanket impl, use a newtype, or drop the blanket impl |
| E0117 implementing a foreign trait for a foreign type | orphan rule | newtype wrapper |
| `Deref` newtype lets callers break invariants | C-DEREF violation | forward selected methods instead |
| `HashMap<String, V>::get(&my_key)` finds nothing | `Borrow` impl whose `Hash`/`Eq` disagree with the owned type | only implement `Borrow<Q>` when hashing and equality agree |
| callers cannot turbofish your function | `impl Trait` in argument position | named generic parameter |
| a type quietly stopped being `Send` | new `Rc`/`Cell`/raw-pointer field | compile-time auto-trait assertions; `cargo semver-checks` |
| `#[non_exhaustive]` appears to do nothing | it only restricts other crates | test exhaustiveness from an integration test or doc test |

Related: `rust-ownership-lifetimes`, `rust-error-handling`, `rust-async-tokio`, `rust-performance`,
`cargo-workspaces-features`, hub `rust-craft`.
