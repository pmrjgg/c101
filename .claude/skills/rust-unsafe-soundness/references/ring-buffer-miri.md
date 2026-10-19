# Ring buffer under Miri: full listings and transcripts

Both programs were run with Miri on nightly 1.101.0 (2026-10-18) through the Rust Playground, once
with the default Stacked Borrows model and once with Tree Borrows. Locally the equivalent commands
are `cargo +nightly miri run` and `MIRIFLAGS=-Zmiri-tree-borrows cargo +nightly miri run` (or
`miri test` with the `main` body moved into a `#[test]`).

## 1. Buggy version

```rust
use std::mem::MaybeUninit;
use std::sync::atomic::{AtomicUsize, Ordering::{Acquire, Relaxed, Release}};

pub struct Ring<T> {
    buf: Box<[MaybeUninit<T>]>,
    head: AtomicUsize, // next slot to read
    tail: AtomicUsize, // next slot to write
}
unsafe impl<T: Send> Sync for Ring<T> {}

impl<T> Ring<T> {
    pub fn new(cap: usize) -> Self {
        Ring { buf: (0..cap).map(|_| MaybeUninit::uninit()).collect(), head: AtomicUsize::new(0), tail: AtomicUsize::new(0) }
    }
    pub fn push(&self, v: T) -> Result<(), T> {
        let tail = self.tail.load(Relaxed);
        if tail - self.head.load(Acquire) == self.buf.len() { return Err(v); }
        let slots = self.buf.as_ptr() as *mut MaybeUninit<T>; // BUG: write through a shared borrow
        unsafe { slots.add(tail % self.buf.len()).write(MaybeUninit::new(v)) };
        self.tail.store(tail + 1, Release);
        Ok(())
    }
    pub fn pop(&self) -> Option<T> {
        let head = self.head.load(Relaxed);
        if head == self.tail.load(Acquire) { return None; }
        let v = unsafe { self.buf[head % self.buf.len()].assume_init_read() };
        self.head.store(head + 1, Release);
        Some(v)
    }
}

fn main() {
    let r = Ring::new(4);
    r.push(String::from("a")).unwrap();
    println!("{:?}", r.pop());
}
```

Stacked Borrows:

```text
error: Undefined Behavior: attempting a write access using <1151> at alloc326[0x0], but that tag only grants SharedReadOnly permission for this location
  --> src/main.rs:19:18
   |
19 |         unsafe { slots.add(tail % self.buf.len()).write(MaybeUninit::new(v)) };
   |                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ this error occurs as part of an access at alloc326[0x0..0x18]
   |
   = help: this indicates a potential bug in the program: it performed an invalid operation, but the Stacked Borrows rules it violated are still experimental
help: <1151> was created by a SharedReadOnly retag at offsets [0x0..0x60]
  --> src/main.rs:18:21
   |
18 |         let slots = self.buf.as_ptr() as *mut MaybeUninit<T>; // BUG: write through a shared borrow
   |                     ^^^^^^^^^^^^^^^^^
```

Tree Borrows:

```text
error: Undefined Behavior: write access through <1122> at alloc326[0x0] is forbidden
  --> src/main.rs:19:18
   = help: this indicates a potential bug in the program: it performed an invalid operation, but the Tree Borrows rules it violated are still experimental
   = help: the accessed tag <1122> has state Frozen which forbids this child write access
help: the accessed tag <1122> was created here, in the initial state Frozen
  --> src/main.rs:18:21
```

Reading the report: the tag number identifies one pointer; "created by a SharedReadOnly retag" /
"initial state Frozen" points at the line that derived it from a shared reference. The fix is always
at that creation site, not at the write.

Second, independent soundness bug (found by audit, not by this test): `push(&self)` and
`pop(&self)` on a `Sync` type let two threads push at once. Both read the same `tail`, both write
the same slot, one value is overwritten without being dropped and the other is read twice. A
single-threaded Miri test cannot see it; the type system has to rule it out.

## 2. Fixed version

```rust
use std::cell::UnsafeCell;
use std::mem::MaybeUninit;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering::{Acquire, Relaxed, Release}};

struct Ring<T> {
    slots: Box<[UnsafeCell<MaybeUninit<T>>]>,
    mask: usize,
    head: AtomicUsize, // next slot to read; written only by the consumer
    tail: AtomicUsize, // next slot to write; written only by the producer
}

// SAFETY: slots are accessed by at most one producer and one consumer (enforced by the
// non-Clone Producer/Consumer handles); slot ownership is handed over through the
// Release store / Acquire load on `tail` (producer -> consumer) and `head` (consumer -> producer).
// T: Send because values move from the producer thread to the consumer thread.
unsafe impl<T: Send> Sync for Ring<T> {}

pub struct Producer<T> { ring: Arc<Ring<T>> }
pub struct Consumer<T> { ring: Arc<Ring<T>> }

pub fn channel<T>(cap: usize) -> (Producer<T>, Consumer<T>) {
    assert!(cap.is_power_of_two(), "capacity must be a power of two");
    let slots = (0..cap).map(|_| UnsafeCell::new(MaybeUninit::uninit())).collect();
    let ring = Arc::new(Ring { slots, mask: cap - 1, head: AtomicUsize::new(0), tail: AtomicUsize::new(0) });
    (Producer { ring: Arc::clone(&ring) }, Consumer { ring })
}

impl<T> Producer<T> {
    pub fn push(&mut self, v: T) -> Result<(), T> {
        let r = &*self.ring;
        let tail = r.tail.load(Relaxed);               // only we write tail
        if tail.wrapping_sub(r.head.load(Acquire)) == r.slots.len() { return Err(v); }
        // SAFETY:
        // - `tail & mask < slots.len()` because len is a power of two and mask = len - 1.
        // - The slot is empty and unaliased: the consumer finished reading it before its
        //   Release store to `head`, which our Acquire load above observed; `&mut self`
        //   guarantees no second producer.
        unsafe { (*r.slots[tail & r.mask].get()).write(v) };
        r.tail.store(tail.wrapping_add(1), Release);   // publish the slot
        Ok(())
    }
}

impl<T> Consumer<T> {
    pub fn pop(&mut self) -> Option<T> {
        let r = &*self.ring;
        let head = r.head.load(Relaxed);               // only we write head
        if head == r.tail.load(Acquire) { return None; }
        // SAFETY:
        // - index is in bounds (mask, as in push).
        // - The slot was initialised by the producer before its Release store to `tail`,
        //   observed by our Acquire load; `&mut self` guarantees no second consumer.
        // - We advance `head` right after, so the value is read exactly once.
        let v = unsafe { (*r.slots[head & r.mask].get()).assume_init_read() };
        r.head.store(head.wrapping_add(1), Release);   // hand the slot back
        Some(v)
    }
}

impl<T> Drop for Ring<T> {
    fn drop(&mut self) {
        // &mut self: both handles are gone, no concurrent access.
        let (mut head, tail) = (*self.head.get_mut(), *self.tail.get_mut());
        while head != tail {
            // SAFETY: slots in head..tail are initialised and never read (invariant above).
            unsafe { self.slots[head & self.mask].get_mut().assume_init_drop() };
            head = head.wrapping_add(1);
        }
    }
}

fn main() {
    let (mut tx, mut rx) = channel::<String>(4);
    let producer = std::thread::spawn(move || {
        for i in 0..200 {
            let mut v = format!("msg-{i}");
            loop { match tx.push(v) { Ok(()) => break, Err(back) => { v = back; std::thread::yield_now(); } } }
        }
        tx                                   // hand the producer back to main
    });
    let mut got = 0;
    while got < 200 {
        match rx.pop() { Some(s) => { assert_eq!(s, format!("msg-{got}")); got += 1; } None => std::thread::yield_now() }
    }
    let mut tx = producer.join().unwrap();
    tx.push("left-1".into()).unwrap();       // two items stay in the ring: Drop for Ring must free them
    tx.push("left-2".into()).unwrap();
    println!("received {got} in order");
}
```

Result under both aliasing models: `received 200 in order`, no UB, no leak report. The two items
pushed after the join stay in the ring until it is dropped; deleting `impl Drop for Ring` makes
Miri fail with `error: memory leaked: alloc113124 (Rust heap, size: 6, align: 1)` (the "left-1"
buffer). Leave something in the ring deterministically, as here: an earlier version of this test
pushed its leftover from the producer thread while the ring could be full, so whether `Drop` had
anything to free depended on the schedule, and the missing-`Drop` mutation passed.

## 3. Mutation check: weaken the publishing store

Change `r.tail.store(tail.wrapping_add(1), Release);` to `Relaxed` and rerun Miri:

```text
error: Undefined Behavior: Data race detected between (1) retag write on thread `unnamed-1` and (2) retag read of type `std::mem::MaybeUninit<std::string::String>` on thread `main` at alloc328
  --> src/main.rs:55:26
55 |         let v = unsafe { (*r.slots[head & r.mask].get()).assume_init_read() };
   |                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ (2) just happened here
help: and (1) occurred earlier here
  --> src/main.rs:39:18
39 |         unsafe { (*r.slots[tail & r.mask].get()).write(v) };
```

A test suite that still passes after a deliberate ordering bug is not testing the ordering. Keep a
mutation like this in review notes, and run `MIRIFLAGS="-Zmiri-many-seeds=0..32"` in CI because a
single schedule may miss a race that needs a particular interleaving.

## 4. Loom model (sketch, adapt before use)

loom replaces `std::sync` types and checks every interleaving of a small test. Its `UnsafeCell`
has no `get()`; access goes through closures, so wrap the cell once:

```rust
#[cfg(loom)]
pub(crate) use loom::{cell::UnsafeCell, sync::{Arc, atomic::{AtomicUsize, Ordering}}, thread};
#[cfg(not(loom))]
pub(crate) use {shim::UnsafeCell, std::sync::{Arc, atomic::{AtomicUsize, Ordering}}, std::thread};
#[cfg(not(loom))]
pub(crate) mod shim {
    pub struct UnsafeCell<T>(std::cell::UnsafeCell<T>);
    impl<T> UnsafeCell<T> {
        pub fn new(v: T) -> Self { Self(std::cell::UnsafeCell::new(v)) }
        pub fn with_mut<R>(&self, f: impl FnOnce(*mut T) -> R) -> R { f(self.0.get()) }
        pub fn with<R>(&self, f: impl FnOnce(*const T) -> R) -> R { f(self.0.get()) }
    }
}

#[cfg(loom)]
#[test]
fn spsc_two_items() {
    loom::model(|| {
        let (mut tx, mut rx) = channel::<u32>(2);
        let t = thread::spawn(move || { tx.push(1).unwrap(); tx.push(2).unwrap(); });
        let mut got = Vec::new();
        while got.len() < 2 { if let Some(v) = rx.pop() { got.push(v); } else { thread::yield_now(); } }
        t.join().unwrap();
        assert_eq!(got, [1, 2]);
    });
}
```

Then rewrite every slot access through the closures, e.g.
`r.slots[i].with_mut(|p| unsafe { (*p).write(v) })` and
`r.slots[i].with(|p| unsafe { (*p).assume_init_read() })` (reading through `*const` is fine: the
value is moved out bit-wise and the slot counts as uninitialised afterwards).

Run: `RUSTFLAGS="--cfg loom" cargo test --release --test loom_ring` with `loom` under
`[target.'cfg(loom)'.dev-dependencies]`. Keep models tiny (2 threads, 2 or 3 operations); the state
space grows exponentially. `LOOM_MAX_PREEMPTIONS=3` bounds it. This sketch was not executed while
writing the skill (loom is not available on the Playground); compile it in the target crate first.
