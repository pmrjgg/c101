# Dispatch benchmark: dyn vs enum, full program and criterion harness

## Quick program (std only)

This is the exact program behind the numbers in SKILL.md section 10. Run it with
`cargo run --release` (or on the Rust Playground in release mode). It reports the median of 15 runs
in ns per plugin call.

```rust
use std::hint::black_box;
use std::time::Instant;

pub trait Plugin: Send + Sync { fn apply(&self, x: f64) -> f64; }
pub struct Scale(pub f64);
pub struct Offset(pub f64);
pub struct Clamp { pub lo: f64, pub hi: f64 }
impl Plugin for Scale { #[inline] fn apply(&self, x: f64) -> f64 { x * self.0 } }
impl Plugin for Offset { #[inline] fn apply(&self, x: f64) -> f64 { x + self.0 } }
impl Plugin for Clamp { #[inline] fn apply(&self, x: f64) -> f64 { x.clamp(self.lo, self.hi) } }

pub enum AnyPlugin { Scale(Scale), Offset(Offset), Clamp(Clamp) }
impl AnyPlugin {
    #[inline]
    pub fn apply(&self, x: f64) -> f64 {
        match self { AnyPlugin::Scale(p) => p.apply(x), AnyPlugin::Offset(p) => p.apply(x), AnyPlugin::Clamp(p) => p.apply(x) }
    }
}

fn run_dyn(reg: &[Box<dyn Plugin>], xs: &[f64]) -> f64 {
    xs.iter().map(|&x| reg.iter().fold(x, |acc, p| p.apply(acc))).sum()
}
fn run_enum(reg: &[AnyPlugin], xs: &[f64]) -> f64 {
    xs.iter().map(|&x| reg.iter().fold(x, |acc, p| p.apply(acc))).sum()
}
fn median(mut v: Vec<f64>) -> f64 { v.sort_by(|a, b| a.partial_cmp(b).unwrap()); v[v.len() / 2] }

fn main() {
    let n_plugins = 64;
    let xs: Vec<f64> = (0..20_000).map(|i| i as f64 * 0.001).collect();
    let mut dynreg: Vec<Box<dyn Plugin>> = Vec::new();
    let mut enumreg: Vec<AnyPlugin> = Vec::new();
    for i in 0..n_plugins {
        match i % 3 {
            0 => { dynreg.push(Box::new(Scale(1.0001))); enumreg.push(AnyPlugin::Scale(Scale(1.0001))); }
            1 => { dynreg.push(Box::new(Offset(0.5))); enumreg.push(AnyPlugin::Offset(Offset(0.5))); }
            _ => { dynreg.push(Box::new(Clamp { lo: -1e9, hi: 1e9 })); enumreg.push(AnyPlugin::Clamp(Clamp { lo: -1e9, hi: 1e9 })); }
        }
    }
    let calls = (n_plugins * xs.len()) as f64;
    let (mut td, mut te) = (vec![], vec![]);
    for _ in 0..15 {
        let t = Instant::now(); black_box(run_dyn(black_box(&dynreg), black_box(&xs))); td.push(t.elapsed().as_nanos() as f64 / calls);
        let t = Instant::now(); black_box(run_enum(black_box(&enumreg), black_box(&xs))); te.push(t.elapsed().as_nanos() as f64 / calls);
    }
    println!("dyn  median {:.3} ns/call", median(td));
    println!("enum median {:.3} ns/call", median(te));
    println!("size_of Box<dyn Plugin> = {}, AnyPlugin = {}",
        std::mem::size_of::<Box<dyn Plugin>>(), std::mem::size_of::<AnyPlugin>());
}
```

Output (Rust Playground, stable 1.99.1, release, three runs, identical to two decimals):

```text
dyn  median 1.920 ns/call
enum median 0.621 ns/call
size_of Box<dyn Plugin> = 16, AnyPlugin = 24
```

Heavy-body variant: replace the `Scale` body with `(x * self.0).sin().abs() + x.sqrt()` and the
`Offset` body with `(x + self.0).ln_1p().cos() + x`. Output: `dyn 19.21`, `enum 19.17` ns/call.

Why the trivial case differs by 3x: the fold is a serial dependency chain, so each indirect call
adds its full latency; the enum `match` is inlined and the branch predictor learns the round-robin
pattern. With 19 ns of floating-point work per call the extra 1.3 ns disappears in the noise.

## Criterion harness (for the decision on real hardware)

```toml
# Cargo.toml
[dev-dependencies]
criterion = "0.8"

[[bench]]
name = "dispatch"
harness = false
```

```rust
// benches/dispatch.rs
use criterion::{criterion_group, criterion_main, Criterion};
use std::hint::black_box;
use mycrate::registry::{make_dyn_registry, make_enum_registry, run_dyn, run_enum};

fn bench(c: &mut Criterion) {
    let xs: Vec<f64> = (0..20_000).map(|i| i as f64 * 0.001).collect();
    let (d, e) = (make_dyn_registry(64), make_enum_registry(64));
    let mut g = c.benchmark_group("registry");
    g.bench_function("dyn", |b| b.iter(|| run_dyn(black_box(&d), black_box(&xs))));
    g.bench_function("enum", |b| b.iter(|| run_enum(black_box(&e), black_box(&xs))));
    g.finish();
}
criterion_group!(benches, bench);
criterion_main!(benches);
```

```bash
git stash && cargo bench --bench dispatch -- --save-baseline before   # current dyn implementation
git stash pop && cargo bench --bench dispatch -- --baseline before    # after the refactor; reports change % and p-value
```

Decision rule: accept the refactor only if criterion reports a change beyond the noise threshold
(p < 0.05) on the end-to-end benchmark that matters, not just this micro-benchmark. Check compile
time and size as well: `cargo build --release --timings`, `cargo llvm-lines --release | head`.

## Variants worth measuring when the answer is close

| Variant | Expectation |
|---|---|
| group plugins by kind (`Vec<Scale>`, `Vec<Offset>`, ..) and loop per kind | removes dispatch entirely; only valid if order between kinds does not matter |
| `enum AnyPlugin { Builtin(..), External(Box<dyn Plugin>) }` | builtin calls inline; external plugins still possible |
| `enum_dispatch` crate | same codegen as the hand-written `match`, less boilerplate |
| batch API on the trait: `fn apply_all(&self, xs: &mut [f64])` | one virtual call per batch instead of per element; often the biggest win while keeping `dyn` |
