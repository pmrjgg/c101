# Borrow error catalog: minimal repros, compiler output, fixes

Every repro below was compiled on rustc 1.99.1 stable, edition 2024 (Rust Playground, October 2026)
unless a line says otherwise. Messages are trimmed to the headline and the decisive note. Use the
repro to confirm you are looking at the same shape before applying the fix.

## E0382 borrow of moved value

```rust
fn consume(_v: Vec<u8>) {}
fn main() { let v = vec![1u8]; consume(v); println!("{}", v.len()); }
// error[E0382]: borrow of moved value: `v`
```

Fix: `consume(&v)` with `fn consume(v: &[u8])` if the callee only reads; otherwise move after the
last use, or `consume(v.clone())` when the clone is cheap and rare.

## E0499 two mutable borrows

```rust
struct S { a: Vec<u8>, b: Vec<u8> }
impl S { fn a_mut(&mut self) -> &mut Vec<u8> { &mut self.a } fn b_mut(&mut self) -> &mut Vec<u8> { &mut self.b } }
let a = s.a_mut(); let b = s.b_mut(); a.push(1); b.push(2);
// error[E0499]: cannot borrow `s` as mutable more than once at a time
```

Fix: access the fields directly (`let S { a, b } = &mut s;`) or add one method returning both:
`fn parts_mut(&mut self) -> (&mut Vec<u8>, &mut Vec<u8>) { (&mut self.a, &mut self.b) }`.

## E0502 mutable borrow while shared borrow is alive

```rust
let mut v = vec![1, 2, 3]; let first = &v[0]; v.push(4); println!("{first}");
// error[E0502]: cannot borrow `v` as mutable because it is also borrowed as immutable
```

Fix: `let first = v[0];` (copy), or finish using `first` before `push`. `push` may reallocate, so
the reference would dangle: this error is a real bug, not a false positive.

## E0505 / E0506 move or assign while borrowed

```rust
let s = String::from("x"); let r = &s; let t = s; println!("{r} {t}");
// error[E0505]: cannot move out of `s` because it is borrowed
let mut n = 1; let r = &n; n = 2; println!("{r} {n}");
// error[E0506]: cannot assign to `n` because it is borrowed
```

Fix: end the borrow first (last use of `r` before the move or assignment), or copy what `r` needs.

## E0507 move out of a borrow

```rust
struct Conn { buf: Vec<u8> }
impl Conn { fn take_buf(&mut self) -> Vec<u8> { self.buf } }
// error[E0507]: cannot move out of `self.buf` which is behind a mutable reference
// help: consider cloning the value if the performance cost is acceptable
```

Fix (ignore the clone hint): `std::mem::take(&mut self.buf)` leaves an empty `Vec`;
`self.slot.take()` for `Option`; `std::mem::replace(&mut self.state, State::Closed)` for types
without `Default`. For enum state machines, `match std::mem::replace(&mut self.state, State::Poisoned)`
then assign the next state.

## E0597 does not live long enough

```rust
let r; { let s = String::from("x"); r = &s; } println!("{r}");
// error[E0597]: `s` does not live long enough
//   `s` dropped here while still borrowed
```

Fix: declare `s` in the outer scope, or make `r` own the data (`let r = s;`).

## E0716 temporary dropped while borrowed

```rust
let parts: Vec<&str> = String::from("a b").split(' ').collect();   // E0716
let r: &String; r = &String::from("y");                            // E0716 (assignment, no extension)
let s: &str = &String::from("x").to_uppercase();                   // OK: `let x = &temp` extends temp
// help: consider using a `let` binding to create a longer lived value
```

Fix: `let line = String::from("a b"); let parts: Vec<&str> = line.split(' ').collect();`.

## E0373 closure may outlive the current function

```rust
let v = vec![1, 2, 3]; let h = std::thread::spawn(|| println!("{v:?}"));
// error[E0373]: closure may outlive the current function, but it borrows `v`, which is owned by the current function
```

Fixes: `thread::spawn(move || ..)` (moves `v`); share with `let v = Arc::new(v);` plus
`let v2 = Arc::clone(&v);` before the `move`; or borrow without moving:

```rust
let total = std::thread::scope(|s| s.spawn(|| data.iter().sum::<i32>()).join().unwrap());
println!("{total} {data:?}");   // `data` still usable: scoped threads are joined before scope returns
```

## E0277 not Send (threads) and the async variant

```rust
let rc = Rc::new(5); std::thread::spawn(move || println!("{rc}"));
// error[E0277]: `Rc<i32>` cannot be sent between threads safely

tokio::spawn(async move { let g = m.lock().unwrap(); tick().await; println!("{}", *g); });
// error: future cannot be sent between threads safely
//   = help: ... the trait `Send` is not implemented for `std::sync::MutexGuard<'_, i32>`
// note: future is not `Send` as this value is used across an await
//   7 | let g = m.lock().unwrap();   - has type `std::sync::MutexGuard<'_, i32>` which is not `Send`
//   8 | tick().await;                ^^^^^ await occurs here, with `g` maybe used later
```

Fix: scope the guard so it is dropped before the await:
`let v = { let g = m.lock().unwrap(); *g }; tick().await;`. More patterns: `rust-async-tokio`.

## Lifetime may not live long enough (no code)

```rust
fn longest<'a, 'b>(x: &'a str, y: &'b str) -> &'a str { if x.len() > y.len() { x } else { y } }
// error: lifetime may not live long enough
//   function was supposed to return data with lifetime `'a` but it is returning data with lifetime `'b`
//   = help: consider adding the following bound: `'b: 'a`
```

Fix: one lifetime for both inputs (`fn longest<'a>(x: &'a str, y: &'a str) -> &'a str`). Add
`'b: 'a` only when that relation is really part of the contract.

Elision rule 3 variant:

```rust
impl Store { fn pick(&self, key: &str) -> &str { if key.is_empty() { &self.prefix } else { key } } }
// error: lifetime may not live long enough
// help: consider introducing a named lifetime parameter and update trait if needed
```

Fix: `fn pick<'a>(&'a self, key: &'a str) -> &'a str`.

## E0106 missing lifetime specifier

```rust
fn find_or_push(v: &mut Vec<String>, needle: &str) -> &mut String { .. }
// error[E0106]: missing lifetime specifier
//   = help: this function's return type contains a borrowed value, but the signature does not say
//           whether it is borrowed from `v` or `needle`
struct Doc { text: String, first: &str }    // E0106 in a struct field
```

Fix: `fn find_or_push<'a>(v: &'a mut Vec<String>, needle: &str) -> &'a mut String`. The compiler
suggests putting `'a` on every input; tie it only to the input that is actually returned, or callers
get needlessly restricted. For the struct, store `Range<usize>` into `text` instead of `&str`.

## Variance: invariance of `&mut T`

```rust
fn push_short<'a>(v: &mut Vec<&'a str>, s: &'a str) { v.push(s); }
let mut names: Vec<&'static str> = vec!["static"];
let owned = String::from("short-lived");
push_short(&mut names, &owned);
// error[E0597]: `owned` does not live long enough  (argument requires that `owned` is borrowed for `'static`)
```

`'a` must equal `'static` because `&mut Vec<&'a str>` is invariant in `'a`. Fix: declare
`let mut names: Vec<&str> = vec!["static"];` so the element lifetime is inferred.

## Edition 2024 behaviour changes (both editions compiled)

```rust
// 1. RPIT capture: 2021 OK, 2024 E0597 at the call site ("`key` does not live long enough")
fn indices(data: &[u32], key: &str) -> impl Iterator<Item = usize> { /* returns owned Vec iter */ }
let it = { let key = String::from("abcd"); indices(&data, &key) };
// fix: -> impl Iterator<Item = usize> + use<>        (captures nothing)
//      -> impl Iterator<Item = &'d u32> + use<'d>    (captures only the data borrow)
// traits (1.87+): fn ids(&self) -> impl Iterator<Item = u32> + use<Self>;

// 2. if-let rescope: 2021 panics "RefCell already borrowed", 2024 prints "filled"
if let Some(v) = *cache.borrow() { println!("hit {v}"); }
else { *cache.borrow_mut() = Some(1); println!("filled"); }

// 3. tail-expression temporaries: 2021 E0597 "`c` does not live long enough", 2024 OK
fn len() -> usize { let c = RefCell::new(String::from("abc")); c.borrow().len() }
```

## NLL problem case #3 across channels (October 2026)

| Toolchain | `if let Some(d) = cache.get(key) { return d; } cache.insert(..)` | loop `for s in v.iter_mut() { if .. { return s; } } v.push(..)` |
|---|---|---|
| stable 1.99.1 | E0502 | E0499 (twice) |
| beta 1.100.0 | E0502 | E0499 |
| nightly 1.101.0 (2026-10-18), Polonius Alpha default | compiles | compiles |

Stable workaround for the loop shape:

```rust
fn find_or_push<'a>(v: &'a mut Vec<String>, needle: &str) -> &'a mut String {
    if let Some(i) = v.iter().position(|s| s == needle) { return &mut v[i]; }
    v.push(needle.to_owned());
    v.last_mut().unwrap()   // just pushed, so non-empty
}
```

## Benchmark used for the worked example

```rust
// cargo run --release; hashbrown 0.15 (std's HashMap is built on hashbrown but does not expose entry_ref)
use std::hash::{BuildHasher, RandomState};
use std::{hint::black_box, time::Instant};
use hashbrown::{DefaultHashBuilder, HashMap};
fn load(k: &str) -> u64 { k.len() as u64 }
fn a<'a, S: BuildHasher>(c: &'a mut HashMap<String, u64, S>, k: &str) -> &'a u64 { c.entry(k.to_owned()).or_insert_with(|| load(k)) }
fn b<'a, S: BuildHasher>(c: &'a mut HashMap<String, u64, S>, k: &str) -> &'a u64 {
    if !c.contains_key(k) { c.insert(k.to_owned(), load(k)); }
    &c[k]
}
fn c<'a, S: BuildHasher>(m: &'a mut HashMap<String, u64, S>, k: &str) -> &'a u64 { m.entry_ref(k).or_insert_with(|| load(k)) }
// For each hasher in [RandomState::new(), DefaultHashBuilder::default()] and key length in [8, 64]:
// fill 1000 keys, then time 200_000 hit lookups (keys[(i * 7919) % 1000]) through a, b and c,
// black_box the key and the summed result, repeat 9 times, report the median ns per lookup.
```

Treat the numbers in the SKILL.md table as relative, not absolute: shared Playground hardware,
x86_64, no CPU pinning. For a decision on real code use criterion with your key distribution.
