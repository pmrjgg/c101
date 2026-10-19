---
name: concurrent-data-structures
description: "Correct shared-memory concurrency and lock-free structures: data races vs race conditions, C++/Rust/Java/Go memory models, linearizability and progress, lock patterns, CAS loops and ABA, safe memory reclamation (hazard pointers, epochs, RCU), SPSC/MPMC queues, Treiber stack, sharded counters, false sharing, and checking with TSan, loom, Shuttle, miri, jcstress, Lincheck and GenMC. Load when building, reviewing or debugging concurrent code."
when_to_use: "Atomics with an explicit Ordering/memory_order in a diff; compare_exchange or CAS retry loops; a hand-written lock-free queue, stack or ring buffer; a test that fails only under load or only on ARM64; TSan, go test -race or miri reports; deadlocks or lock convoys; double-checked locking; choosing between Mutex, RwLock, channels and DashMap/ConcurrentHashMap; perf c2c showing HITM on a hot cache line."
---

# Concurrent data structures

Practice for shared-memory concurrency: pick the least dangerous design, get orderings right, prove it
with checkers. The theory summary stays in `cs-foundations` section 10; C++ atomics API detail in
`cpp-concurrency-atomics`; unsafe Rust soundness in `rust-unsafe-soundness`; runtimes in
`go-concurrency-context`, `java-virtual-threads`, `haskell-concurrency-stm`; replicated state across
machines in `distributed-consensus-consistency`.

Deep material: [SPSC ring buffer: full code, loom tests and benchmark](references/spsc-ring-example.md)

## 1. Decision ladder

Climb one rung only when a profile (perf, pprof mutex profile, JFR lock events) shows the current rung
is the bottleneck.

| Rung | Design | Use when | Examples |
|---|---|---|---|
| 0 | Don't share | work partitions by key, owner thread or pipeline stage | channels (`crossbeam-channel`, Go `chan`, `BlockingQueue`), per-thread state merged at the end, sharding, actors |
| 1 | One coarse lock | short critical sections, modest contention | `std::mutex`, `parking_lot::Mutex`, `sync.Mutex`, `ReentrantLock` |
| 2 | Finer locks | lock wait time dominates the profile | lock striping, per-bucket locks, `RwLock` for long read sections |
| 3 | Library concurrent structure | contention on a standard shape remains | `ConcurrentHashMap`, `DashMap`, crossbeam queues, folly, `LongAdder` |
| 4 | Custom lock-free | measured need, no library fits | only with model checking (section 9) and a second reviewer |

A futex-based mutex (parking_lot, glibc, Go, the JDK) beats naive lock-free code more often than
intuition suggests: benchmark rung 4 against rung 1 before shipping it.

## 2. Definitions that decide correctness (kept from `cs-foundations` section 10)

- **Data race**: two accesses to one location, at least one a write, at least one non-atomic, not
  ordered by happens-before. Undefined behaviour in C/C++ and unsafe Rust (safe Rust rejects it at
  compile time). Java gives racy programs weak but defined semantics; in Go a race on a multiword
  value (interface, slice, string) can corrupt memory.
- **Race condition**: the result depends on the interleaving. It needs no data race:
  `if (map.get(k) == null) map.put(k, v)` on a `ConcurrentHashMap` is all-atomic and still wrong.
- **Linearizability**: each operation appears to take effect atomically at one instant between call
  and return. Name the linearization point (LP) per operation and per outcome in a comment:
  Michael-Scott enqueue = the successful CAS on `tail.next`; dequeue = the successful CAS on `head`,
  or the read of `head.next == null` for "empty". Linearizability composes; sequential consistency
  does not.

| Progress (strongest first) | Meaning | Typical source |
|---|---|---|
| Wait-free | every thread finishes in a bounded number of its own steps | SPSC ring, `fetch_add` counters |
| Lock-free | some thread always completes; individuals may starve | CAS-loop stacks and queues |
| Obstruction-free | a thread running alone finishes | some STM designs |
| Blocking, starvation-free | every waiter eventually acquires | fair (FIFO, ticket) locks |
| Blocking, deadlock-free | some waiter acquires | ordinary mutexes |

## 3. Memory orderings

| C++ / Rust ordering | Guarantees | Use for | Wrong for |
|---|---|---|---|
| `relaxed` / `Relaxed` | atomicity and per-location coherence only | statistics counters, ID generators, refcount increments | a flag that guards other data |
| `release` store + `acquire` load | writes before the release are visible after an acquire load that reads it (synchronizes-with) | publishing an object, message passing, lock hand-off, SPSC indices | ordering a store before a later load of a different location |
| `acq_rel` / `AcqRel` | both, on one read-modify-write | CAS in queues and stacks, refcount decrement | |
| `seq_cst` / `SeqCst` | acquire/release plus one total order of all SeqCst operations | Dekker/Peterson flags ("store mine, then load yours"), IRIW | a default that hides missing reasoning |

Every compiler promotes `consume` to `acquire`; do not use it. Refcount pattern (what `Arc` does):
increment `Relaxed`; decrement `Release`; on reaching zero, `fence(Acquire)`, then free.

**Java** (JMM, `VarHandle` modes, weakest first): plain (no ordering; non-volatile `long`/`double`
may tear), opaque (atomic and coherent per variable, about `relaxed`), release/acquire
(`setRelease`/`getAcquire`), volatile (`volatile` fields, `getVolatile`/`setVolatile`, about
`seq_cst`). `synchronized`, `java.util.concurrent` locks and `Thread.start/join` create happens-before
edges. Final fields: a thread that obtains the reference after the constructor finished sees the
constructed final values even through a race, provided `this` did not escape during construction.

**Go**: no relaxed atomics; `sync/atomic` operations are sequentially consistent (memory model, 2022
revision); channels, `sync.Mutex`, `WaitGroup` and `Once` create happens-before edges.

**Hardware**: x86-64 is TSO (only store-to-load reordering is visible), so a missing acquire/release
often "works" there, though the compiler may still reorder. ARM64 (Apple Silicon, AWS Graviton,
Ampere) reorders freely: run stress tests and CI on ARM64 before trusting weakly ordered code.

## 4. Lock patterns

- **Deadlock** needs all four Coffman conditions (mutual exclusion, hold and wait, no preemption,
  circular wait). Break circular wait with one global order (by level, then ID or address); take two
  locks together with `std::scoped_lock(a, b)`. Detect with parking_lot's `deadlock_detection`
  feature, `jstack`, or `ThreadMXBean.findDeadlockedThreads()`.
- **Lock striping**: `locks[hash(key) & (N - 1)]`, N a power of two around 4x the core count;
  multi-key operations take stripes in index order.
- **RW locks only for long read sections**: a read acquisition still writes a shared counter, so a
  plain mutex wins for short sections. Go's `RWMutex` blocks new readers once a writer waits, so a
  recursive `RLock` deadlocks.
- **Seqlocks** for small read-mostly data with one writer. Readers retry; the data fields must be
  atomics, or the racy read is UB (Boehm's fence formulation):

```cpp
// writer (single writer, or serialised by a mutex)
auto s = seq.load(std::memory_order_relaxed);
seq.store(s + 1, std::memory_order_relaxed);               // odd: write in progress
std::atomic_thread_fence(std::memory_order_release);
x.store(nx, std::memory_order_relaxed); y.store(ny, std::memory_order_relaxed);
seq.store(s + 2, std::memory_order_release);
// reader
do {
  s0 = seq.load(std::memory_order_acquire);
  rx = x.load(std::memory_order_relaxed); ry = y.load(std::memory_order_relaxed);
  std::atomic_thread_fence(std::memory_order_acquire);
  s1 = seq.load(std::memory_order_relaxed);
} while ((s0 & 1) || s0 != s1);
```

- **Lazy init**: C++ function-local `static` or `std::call_once`; Rust `OnceLock`/`LazyLock`; Java
  holder idiom (`private static class Holder { static final Foo I = new Foo(); }`); Go `sync.Once`,
  `sync.OnceValue`. Hand-rolled double-checked locking needs acquire/release (C++) or `volatile`
  (Java); use the library instead.
- **Condition variables**: wait in a predicate loop (`cv.wait(lk, [&]{ return !q.empty() || closed; })`)
  and change the predicate under the same mutex before notifying; this covers spurious and lost
  wakeups.
- **Priority inversion**: a low-priority holder preempted by medium-priority work blocks a
  high-priority waiter; use priority-inheritance mutexes (`PTHREAD_PRIO_INHERIT`) in real-time code.
- **No lock across await, I/O or foreign callbacks**: a `std::sync::MutexGuard` held across `.await`
  makes the future `!Send`; `tokio::sync::Mutex` allows it but serialises the I/O; Java
  `synchronized` pinned virtual threads before JDK 24 (JEP 491).

## 5. CAS loops and ABA

```rust
use std::sync::atomic::{AtomicU64, Ordering::{AcqRel, Acquire}};
use crossbeam_utils::Backoff;

/// Applies `f` atomically. `f` must be pure: it may run many times.
fn update(a: &AtomicU64, f: impl Fn(u64) -> Option<u64>) -> Result<u64, u64> {
    let backoff = Backoff::new();
    let mut cur = a.load(Acquire);
    loop {
        let Some(new) = f(cur) else { return Err(cur) };       // precondition failed
        match a.compare_exchange_weak(cur, new, AcqRel, Acquire) {
            Ok(prev) => return Ok(prev),                        // LP: the successful CAS
            Err(actual) => { cur = actual; backoff.spin(); }    // lost the race: back off
        }
    }
}
```

`fetch_update` is the same loop without backoff. Use `_weak` inside loops (spurious failure is cheap
on LL/SC machines). Under heavy contention, add exponential backoff or switch to a combining or
sharded design: retry storms are the lock-free version of a convoy.

ABA needs node reuse. Treiber `pop`: T1 reads `head = A, next = B`; T2 pops A, pops B, frees B,
pushes A again (same address); T1's `CAS(head, A, B)` succeeds and installs freed B.

| Fix | How | Limits |
|---|---|---|
| Tagged pointer / version counter | counter in unused pointer bits (x86-64 user space uses 47, or 57 with 5-level paging) or alignment bits | counter wrap; platform-specific bit budget |
| DWCAS | 128-bit CAS of (pointer, counter): `cmpxchg16b`, ARMv8.1 `CASP` | check `is_always_lock_free` (GCC routes 16-byte atomics through libatomic); Rust needs `portable-atomic` |
| LL/SC | ARM `LDXR/STXR`, POWER, RISC-V `LR/SC` fail on any intervening write | not exposed by C++ or Rust |
| Safe reclamation | A cannot be freed or reused while T1 may hold it (section 6) | the usual answer for pointer ABA |

Garbage-collected runtimes (Java, Go, C#) cannot recycle a node that a thread still references, so
pointer ABA disappears unless you pool nodes yourself; value ABA (a state integer) remains.

## 6. Safe memory reclamation

Lock-free code without a reclamation scheme is a use-after-free or a leak.

| Scheme | Read-side cost | Garbage bound | A stalled thread... | Libraries |
|---|---|---|---|---|
| Hazard pointers | publish the pointer, store-load fence per protected load (asymmetric fences can remove it) | bounded: threads x slots | blocks only the nodes it protects | folly `hazptr`, C++26 `<hazard_pointer>`, `haphazard` (Rust) |
| Epoch-based (EBR) | pin/unpin per operation, cheap | unbounded while any thread stays pinned | blocks all reclamation | `crossbeam-epoch`, `seize` (used by papaya) |
| RCU | near zero for readers | one grace period | delays reclamation | liburcu, the Linux kernel, folly RCU, C++26 `<rcu>` |
| Split / deferred refcounts | an RMW per access, contended | immediate | nothing | `arc-swap`, `std::atomic<std::shared_ptr>` (often lock-based) |

C++26 library support for `<hazard_pointer>` and `<rcu>` is still arriving; use folly or liburcu today.

## 7. Design catalogue

| Need | Design | Library picks | Notes |
|---|---|---|---|
| 1 producer, 1 consumer | SPSC ring: two indices, acquire/release | `rtrb`, `boost::lockfree::spsc_queue`, `folly::ProducerConsumerQueue` | wait-free; cache the other side's index |
| Bounded MPMC | Vyukov array queue with a sequence number per slot | crossbeam `ArrayQueue` | not strictly lock-free: a producer stalled after claiming a slot blocks that slot's consumer |
| Unbounded MPMC | Michael-Scott queue (dummy node, two CAS) | Java `ConcurrentLinkedQueue`; crossbeam `SegQueue` (segmented) | needs reclamation outside a GC |
| Stack | Treiber stack (CAS on head) | usually a mutex-protected `Vec` wins | ABA-prone; elimination backoff for contention |
| Very high queue throughput | LCRQ (fetch-and-add on ring segments) | research code | needs DWCAS |
| Map | striped or lock-free hash map | `ConcurrentHashMap`, `DashMap` (sharded RwLocks), `papaya` (lock-free reads), folly `ConcurrentHashMap`, libcuckoo | do check-then-act through `compute`/`entry` |
| Hot counter | per-thread or per-CPU shards summed on read | `LongAdder`, Linux `percpu_counter` | reads are not linearizable snapshots |
| Read-mostly snapshot | atomic pointer swap of an immutable value | `arc-swap`, `left-right`, RCU, `CopyOnWriteArrayList` | writers pay a copy |

Vyukov enqueue (dequeue mirrors it with `seq == pos + 1` and stores `pos + capacity`):

```text
pos = enq.load(relaxed)
loop: cell = buf[pos & mask]; dif = cell.seq.load(acquire) - pos
      dif == 0 -> if enq.cas_weak(pos, pos + 1, relaxed) break       // slot claimed
      dif <  0 -> return FULL
      else     -> pos = enq.load(relaxed)
cell.value = v; cell.seq.store(pos + 1, release)                     // publish to consumers
```

## 8. False sharing

- Two hot variables on one cache line written by different cores ping-pong the line. Lines are 64
  bytes on most x86 and ARM servers, 128 bytes on Apple M-series, and Intel's adjacent-line
  prefetcher pairs 64-byte lines, so pad hot fields to 128 bytes on x86-64 and aarch64 (crossbeam
  `CachePadded` does exactly this).
- C++: `alignas(std::hardware_destructive_interference_size)` (GCC warns that the constant is not
  ABI-stable; many codebases hard-code 64 or 128). Go: `golang.org/x/sys/cpu.CacheLinePad`. Java:
  `@jdk.internal.vm.annotation.Contended` with `-XX:-RestrictContended` for application classes.
- Measure, do not guess: `perf c2c record -- ./bench` then `perf c2c report`, and look for lines with
  high HITM (loads that hit a line modified in another core's cache).

## 9. Checking toolbox

Stress tests find bugs; only exhaustive checking within bounds shows their absence.

| Tool | Scope | Command or entry point |
|---|---|---|
| ThreadSanitizer | C/C++ races on executed paths | `clang++ -fsanitize=thread -g -O1` (gcc accepts the same flag) |
| Go race detector | Go races on executed paths | `go test -race ./...` |
| TSan for Rust | unsafe code and FFI | `RUSTFLAGS="-Zsanitizer=thread" cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu` |
| loom | Rust, every interleaving up to a preemption bound, C11-style model | `RUSTFLAGS="--cfg loom" LOOM_MAX_PREEMPTIONS=3 cargo test --release` |
| Shuttle | Rust, randomised schedulers (PCT) for larger tests | `shuttle::check_pct(test, 10_000, 3)` |
| miri | Rust UB, including data races and some weak-memory outcomes | `MIRIFLAGS="-Zmiri-many-seeds" cargo +nightly miri test` |
| jcstress | Java: observable outcomes under the JMM on real hardware and JITs | `@JCStressTest` with `@Outcome(id = ..., expect = FORBIDDEN)` |
| Lincheck | Kotlin/Java linearizability by stress and model checking | `@Operation` methods plus `ModelCheckingOptions().check(this::class)` |
| GenMC | C11 programs, exhaustive under RC11/IMM weak memory | small client programs with assertions |
| Porcupine | linearizability of a recorded history (any language) | `porcupine.CheckOperations(model, history)` in Go |
| ARM64 stress | reorderings hidden by x86 TSO | CI runners on Graviton or Apple Silicon |

loom's README lists limits: SeqCst accesses are modelled as AcqRel (possible false alarms) and load
buffering is not modelled, so loom can miss some relaxed-memory bugs; cross-check with GenMC or miri.

## 10. Benchmarking concurrent structures

- Plot throughput against thread count from 1 to 2x the core count (oversubscription), threads pinned
  (`taskset`, `core_affinity`), same-socket and cross-socket placements.
- Record per-operation latency percentiles under contention (HdrHistogram), not only means.
- Contention collapse signature: throughput peaks at a few threads, then falls as CAS failure rate and
  cache-line transfers rise. Count CAS failures; compare with a plain-mutex baseline.
- Warm-up, repetitions, confidence intervals and noise control: `performance-optimization`.

## 11. Pitfalls

- A `Relaxed` flag guarding non-atomic data: use Release on the store and Acquire on the load.
- `volatile` as synchronisation in C/C++: it orders nothing between threads; use `std::atomic`.
- Check-then-act on concurrent maps: use `computeIfAbsent`, `merge`, `entry()`, `putIfAbsent`,
  Go `sync.Map.LoadOrStore`.
- Iterating while mutating: Java `HashMap` throws `ConcurrentModificationException`, CHM iterators
  are weakly consistent, and a `DashMap` reference held across an insert into the same shard
  deadlocks.
- User-space spinlocks without backoff on preemptible threads: the holder gets descheduled and
  everyone spins; use a futex-based mutex or spin-then-park.
- Assuming `std::atomic<std::shared_ptr>` is lock-free: libstdc++ uses an internal spin lock; check
  `is_lock_free()` or use arc-swap, folly or hazard pointers.
- Copying a Go `sync.Mutex` (`go vet` copylocks) or locking on a boxed `Integer`/interned `String` in Java.

## 12. Worked example: SPSC ring buffer in Rust

Indices grow without bound and wrap modulo the capacity. Only the producer writes `tail` and only the
consumer writes `head`. Full code with the `UnsafeCell` shim, Producer/Consumer handles and `Drop`:
[the SPSC reference](references/spsc-ring-example.md).

```rust
pub fn push(&self, v: T) -> Result<(), T> {                 // producer only
    let t = self.tail.load(Relaxed);                        // own index
    let h = self.head.load(Acquire);                        // (2) slot was released by the consumer
    if t.wrapping_sub(h) == self.buf.len() { return Err(v); }
    self.buf[t % self.buf.len()].with_mut(|p| unsafe { (*p).write(v); });
    self.tail.store(t.wrapping_add(1), Release);            // (1) publish the slot
    Ok(())
}
pub fn pop(&self) -> Option<T> {                            // consumer only
    let h = self.head.load(Relaxed);
    let t = self.tail.load(Acquire);                        // (1) pairs with the producer's Release
    if h == t { return None; }
    let v = self.buf[h % self.buf.len()].with(|p| unsafe { (*p).assume_init_read() });
    self.head.store(h.wrapping_add(1), Release);            // (2) hand the slot back
    Some(v)
}
```

Happens-before proof:

1. Edge (1), read-after-write: the producer's slot write W is sequenced before its Release store of
   `tail = t + 1`. A consumer Acquire load that reads `t + 1` (or a later Release store, also
   sequenced after W) synchronizes with it, so W happens-before the consumer's slot read R. No race.
2. Edge (2), write-after-read: the consumer's read of slot `h` is sequenced before its Release store
   `head = h + 1`; the producer reuses that slot only at `t = h + capacity`, and its full check lets
   it proceed only after an Acquire load of `head` returned at least `h + 1`. So the read
   happens-before the overwrite.
3. Weaken either side of either edge to `Relaxed` and the slot accesses become unordered: a data race,
   UB, even if x86 runs it correctly.

loom test (3 items through capacity 2, so the indices wrap):

```rust
#[cfg(loom)]
#[test]
fn spsc_loom() {
    loom::model(|| {
        let q = loom::sync::Arc::new(Ring::<u32>::with_capacity(2));
        let p = q.clone();
        let prod = loom::thread::spawn(move || {
            for i in 0..3 { while p.push(i).is_err() { loom::thread::yield_now(); } }
        });
        let mut got = Vec::new();
        while got.len() < 3 {
            match q.pop() { Some(v) => got.push(v), None => loom::thread::yield_now() }
        }
        prod.join().unwrap();
        assert_eq!(got, [0, 1, 2]);
    });
}
```

Run `RUSTFLAGS="--cfg loom" LOOM_MAX_PREEMPTIONS=3 cargo test --release spsc_loom`. With `Relaxed`
on the `tail` store and load, loom panics with a causality violation on the slot's `UnsafeCell`
(concurrent write and read); with Acquire/Release it explores every schedule within the bound and
passes. Report the preemption bound with the result.

Benchmark: pin producer and consumer to different physical cores, move 10^8 `u64`s, and compare
`CachePadded<AtomicUsize>` indices with plain adjacent `AtomicUsize` fields; also try the cached
remote index (rtrb and folly do this). Expect the unpadded variant to lose by a wide margin from line
ping-pong; publish your measured numbers with the core placement, and confirm the cause with
`perf c2c`. Harness in [the SPSC reference](references/spsc-ring-example.md).

Related: `cpp-concurrency-atomics`, `rust-unsafe-soundness`, `go-concurrency-context`, `java-virtual-threads`, `haskell-concurrency-stm`, `formal-verification-tla-dafny`, `distributed-consensus-consistency`, `performance-optimization`, hub `cs-foundations`
