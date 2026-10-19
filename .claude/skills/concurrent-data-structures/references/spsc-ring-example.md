# SPSC ring buffer: full code, loom tests, benchmark

Companion to section 12 of the skill. Shape: Rust 2021 or later, `crossbeam-utils` for
`CachePadded`, `loom` 0.7 behind `--cfg loom`, `core_affinity` for the benchmark.

## Cargo.toml

```toml
[package]
name = "spsc"
edition = "2021"

[dependencies]
crossbeam-utils = "0.8"

[target.'cfg(loom)'.dependencies]
loom = "0.7"

[dev-dependencies]
core_affinity = "0.8"

[[bench]]
name = "spsc"
harness = false

[lints.rust]
unexpected_cfgs = { level = "warn", check-cfg = ['cfg(loom)', 'cfg(spsc_relaxed)'] }
```

## src/lib.rs

```rust
use std::mem::MaybeUninit;
use std::ops::Deref;
use std::sync::atomic::Ordering::{self, Acquire, Relaxed, Release};

pub use crossbeam_utils::CachePadded;
#[cfg(loom)]
use loom::{cell::UnsafeCell, sync::atomic::AtomicUsize, sync::Arc};
#[cfg(not(loom))]
pub use std::sync::{atomic::AtomicUsize, Arc};

// std UnsafeCell with loom's closure API, so one code base runs under both.
#[cfg(not(loom))]
struct UnsafeCell<T>(std::cell::UnsafeCell<T>);
#[cfg(not(loom))]
impl<T> UnsafeCell<T> {
    fn new(v: T) -> Self { Self(std::cell::UnsafeCell::new(v)) }
    fn with<R>(&self, f: impl FnOnce(*const T) -> R) -> R { f(self.0.get()) }
    fn with_mut<R>(&self, f: impl FnOnce(*mut T) -> R) -> R { f(self.0.get()) }
}

// The orderings that publish a slot. `--cfg spsc_relaxed` breaks them on purpose for the loom demo.
#[cfg(not(spsc_relaxed))]
const PUBLISH: (Ordering, Ordering) = (Release, Acquire);
#[cfg(spsc_relaxed)]
const PUBLISH: (Ordering, Ordering) = (Relaxed, Relaxed);

/// Index holder: `CachePadded<AtomicUsize>` (one line each) or bare `AtomicUsize` (shared line).
pub trait Index: Deref<Target = AtomicUsize> + From<AtomicUsize> {}
impl<I: Deref<Target = AtomicUsize> + From<AtomicUsize>> Index for I {}

struct Ring<T, I: Index> {
    buf: Box<[UnsafeCell<MaybeUninit<T>>]>,
    head: I, // next slot to read; written only by the consumer
    tail: I, // next slot to write; written only by the producer
}

// Safety: each slot is owned by exactly one side at a time; ownership moves through the
// Release/Acquire pairs on `tail` (slot full) and `head` (slot free). T crosses threads: T: Send.
unsafe impl<T: Send, I: Index + Sync> Sync for Ring<T, I> {}

impl<T, I: Index> Ring<T, I> {
    fn push(&self, v: T) -> Result<(), T> {
        let t = self.tail.load(Relaxed);
        let h = self.head.load(Acquire);                   // slot released by the consumer
        if t.wrapping_sub(h) == self.buf.len() { return Err(v); }
        self.buf[t % self.buf.len()].with_mut(|p| unsafe { (*p).write(v); });
        self.tail.store(t.wrapping_add(1), PUBLISH.0);     // publish: LP of push
        Ok(())
    }
    fn pop(&self) -> Option<T> {
        let h = self.head.load(Relaxed);
        let t = self.tail.load(PUBLISH.1);                 // pairs with the publish
        if h == t { return None; }                         // LP of an empty pop
        let v = self.buf[h % self.buf.len()].with(|p| unsafe { (*p).assume_init_read() });
        self.head.store(h.wrapping_add(1), Release);       // hand the slot back: LP of pop
        Some(v)
    }
}

impl<T, I: Index> Drop for Ring<T, I> {
    fn drop(&mut self) {
        // &mut self: both handles are gone, no concurrent access is possible.
        let (mut h, t) = (self.head.load(Relaxed), self.tail.load(Relaxed));
        while h != t {
            self.buf[h % self.buf.len()].with_mut(|p| unsafe { (*p).assume_init_drop() });
            h = h.wrapping_add(1);
        }
    }
}

/// Handles are not Clone and take &mut self: one producer and one consumer, enforced by types.
pub struct Producer<T, I: Index = CachePadded<AtomicUsize>>(Arc<Ring<T, I>>);
pub struct Consumer<T, I: Index = CachePadded<AtomicUsize>>(Arc<Ring<T, I>>);

pub fn channel<T, I: Index>(capacity: usize) -> (Producer<T, I>, Consumer<T, I>) {
    assert!(capacity > 0);
    let buf = (0..capacity).map(|_| UnsafeCell::new(MaybeUninit::uninit())).collect();
    let ring = Arc::new(Ring { buf, head: I::from(AtomicUsize::new(0)), tail: I::from(AtomicUsize::new(0)) });
    (Producer(ring.clone()), Consumer(ring))
}

impl<T, I: Index> Producer<T, I> {
    pub fn push(&mut self, v: T) -> Result<(), T> { self.0.push(v) }
}
impl<T, I: Index> Consumer<T, I> {
    pub fn pop(&mut self) -> Option<T> { self.0.pop() }
}

#[cfg(all(test, loom))]
mod loom_tests {
    use super::*;

    #[test]
    fn fifo_without_races() {
        loom::model(|| {
            let (mut p, mut c) = channel::<u32, CachePadded<AtomicUsize>>(2);
            let prod = loom::thread::spawn(move || {
                for i in 0..3 { while p.push(i).is_err() { loom::thread::yield_now(); } }
            });
            let mut got = Vec::new();
            while got.len() < 3 {
                match c.pop() { Some(v) => got.push(v), None => loom::thread::yield_now() }
            }
            prod.join().unwrap();
            assert_eq!(got, [0, 1, 2]);
        });
    }
}
```

## Running the checks

| Command | Expected |
|---|---|
| `RUSTFLAGS="--cfg loom" LOOM_MAX_PREEMPTIONS=3 cargo test --release fifo_without_races` | passes: every schedule within 3 preemptions keeps FIFO order and no slot access races |
| `RUSTFLAGS="--cfg loom --cfg spsc_relaxed" LOOM_MAX_PREEMPTIONS=3 cargo test --release fifo_without_races` | loom panics with a causality violation on a slot `UnsafeCell` (write and read not ordered) |
| `cargo +nightly miri test` (non-loom unit tests) | no UB on the executed schedules; add `MIRIFLAGS="-Zmiri-many-seeds"` to vary them |

Notes: loom needs `yield_now()` in spin loops or it explores unbounded spinning. A larger bound
(`LOOM_MAX_PREEMPTIONS=4`) costs much more time; record the bound you used next to the result.

## Benchmark: padded vs unpadded indices (benches/spsc.rs)

```rust
use spsc::{channel, AtomicUsize, CachePadded, Index};
use std::time::Instant;

const N: u64 = 100_000_000;

fn run<I: Index + Send + Sync + 'static>(label: &str, prod_core: usize, cons_core: usize) {
    let cores = core_affinity::get_core_ids().expect("core ids");
    let (mut p, mut c) = channel::<u64, I>(1024);
    let start = Instant::now();
    let producer = std::thread::spawn({
        let core = cores[prod_core];
        move || {
            core_affinity::set_for_current(core);
            for i in 0..N { while p.push(i).is_err() { std::hint::spin_loop(); } }
        }
    });
    core_affinity::set_for_current(cores[cons_core]);
    let mut sum = 0u64;
    for _ in 0..N {
        loop {
            if let Some(v) = c.pop() { sum = sum.wrapping_add(v); break; }
            std::hint::spin_loop();
        }
    }
    producer.join().unwrap();
    let secs = start.elapsed().as_secs_f64();
    assert_eq!(sum, N * (N - 1) / 2);
    println!("{label}: {:.1} Mops/s", N as f64 / secs / 1e6);
}

fn main() {
    // Pick two different physical cores (check `lscpu -e` or hwloc: SMT siblings share L1/L2).
    for _ in 0..5 {
        run::<CachePadded<AtomicUsize>>("padded  ", 2, 4);
        run::<AtomicUsize>("unpadded", 2, 4);
    }
}
```

Run `cargo bench --bench spsc`. Report the median of the repetitions per variant, the CPU model, the
core placement (same core complex, different complex, different socket) and the message type.

Interpretation:

- Unpadded `head` and `tail` share a line with each other (and with the `Arc` counts), so every push
  and pop invalidates the other core's copy. `perf c2c record -- target/release/deps/spsc-*` then
  `perf c2c report` should show that line at the top with high HITM.
- Next step after padding: cache the remote index in the handle. The producer keeps `cached_head`
  and reloads `head` (Acquire) only when `t - cached_head == capacity`; the consumer mirrors it with
  `cached_tail`. This removes most cross-core reads (rtrb and folly's queue do this).
- Batching (push or pop several slots per index update) trades latency for throughput; measure
  latency percentiles separately if the queue carries requests rather than bulk data.
