---
name: cpp-concurrency-atomics
description: "C++ concurrency and the memory model: choosing mutex, atomic, condition variable, latch or semaphore; memory orders with publication patterns; lock discipline; jthread and stop_token; false sharing; safe memory reclamation; coroutine lifetime rules; std::execution; and TSan-driven testing. Load for threaded C++ code, lock-free structures, data races or deadlocks."
when_to_use: "C++ code using std::thread/jthread, mutexes, std::atomic, condition variables, thread pools, coroutines (co_await, asio::awaitable) or senders; ThreadSanitizer 'data race' or 'lock-order-inversion' reports; deadlocks, hangs, lost wakeups, heisenbugs that vanish under a debugger or only appear on ARM; reviewing memory_order arguments or a lock-free queue."
---

# C++ concurrency, atomics and the memory model

Ground rule: two conflicting accesses (same memory, at least one write) from different threads
without a happens-before edge are a **data race, which is UB**, not "a stale read". Every shared
mutable object is either protected by a mutex, atomic, or handed over through a synchronising
operation (queue, `join`, promise). `volatile` is not synchronisation.

Library gaps to check first: `std::atomic<std::shared_ptr>` exists in libstdc++ 12+ and MSVC
19.27+ but not in libc++ (Apple clang included); `std::jthread` is complete in libc++ 20;
C++26 `<hazard_pointer>`, `<rcu>` and `std::execution` have no shipping standard-library
implementation listed as of October 2026 (use folly, liburcu and NVIDIA stdexec).

Deep material: [memory-model patterns: SPSC ring, seqlock, Dekker, fences, lock hierarchy](references/memory-model-patterns.md) |
[coroutines and std::execution](references/coroutines-execution.md)

## 1. Choosing the tool

| Need | Tool | Notes |
|---|---|---|
| protect compound state | `std::mutex` + `std::scoped_lock` (`std::unique_lock` when you must unlock early or wait) | default choice; uncontended lock/unlock is a few atomic ops |
| many readers, rare writers, long reads | `std::shared_mutex` + `std::shared_lock` | measure: for short sections it is often slower than `std::mutex` |
| several mutexes at once | `std::scoped_lock lk(a, b);` | deadlock-avoidance algorithm, any argument order |
| wait for a condition | `std::condition_variable` (with `std::unique_lock<std::mutex>`) or `std::condition_variable_any` | `cv_any.wait(lk, stop_token, pred)` also wakes on stop requests |
| wait for one atomic to change | `a.wait(old)` / `a.notify_one()` (C++20) | futex-backed on Linux; ABA-blind: returns only when the value differs from `old` when it re-checks |
| one-shot rendezvous / countdown | `std::latch` (`count_down`, `wait`, `arrive_and_wait`) | not reusable |
| repeated phases | `std::barrier<F>` (`arrive_and_wait`, `arrive_and_drop`) | completion function must be `noexcept` |
| bound concurrent access | `std::counting_semaphore<N>`, `std::binary_semaphore` | `acquire`, `try_acquire_for`, `release(n)` |
| counters, flags, single-word state | `std::atomic<T>` | `is_always_lock_free` true for word-sized `T`; large `T` uses a hidden lock |
| atomic access to a plain object | `std::atomic_ref<T>` (C++20) | object aligned to `atomic_ref<T>::required_alignment`; while any `atomic_ref` exists, all accesses must go through one |
| lazy one-time init | function-local `static` (thread-safe since C++11), `std::call_once` | `call_once` retries if the initialiser throws |
| per-thread state | `thread_local` | destructor runs at thread exit; access in other TUs can go through a TLS wrapper call |
| cancellable worker | `std::jthread` + `std::stop_token` + `std::stop_callback` | `jthread` requests stop and joins in its destructor |
| task parallelism | thread pool library, C++26 `std::execution` (stdexec today) | section 4, 8 |
| data-parallel loops | `std::for_each(std::execution::par_unseq, ...)`, OpenMP, `tbb::parallel_for` | libstdc++ needs the TBB backend for parallel execution policies |

## 2. Memory orders

| Order | Guarantees | Canonical use |
|---|---|---|
| `seq_cst` (default) | acquire/release plus one total order of all `seq_cst` operations | default; required for store-then-load-other-flag protocols (Dekker, Peterson) |
| `release` (stores, RMW) | prior writes become visible to a thread whose acquire reads this value | publish data, then set a flag/pointer |
| `acquire` (loads, RMW) | later reads see what was released before the matched store | read flag/pointer, then read data |
| `acq_rel` (RMW) | both | refcount decrement, `exchange`/CAS in queues where a thread both consumes and publishes |
| `relaxed` | atomicity only, no ordering of other memory | statistics counters, ID generation, values read only after `join()` |
| `consume` | deprecated in C++26; compilers treat it as `acquire` | do not use |

Publication (the pattern behind most lock-free code):

```cpp
Payload payload;                                   // plain memory
std::atomic<bool> ready{false};
// producer
payload = compute();
ready.store(true, std::memory_order_release);      // (1) publishes payload
ready.notify_one();                                // without it a blocked waiter may never wake
// consumer
ready.wait(false, std::memory_order_acquire);      // (2) returns only after an acquire load saw true:
use(payload);                                      //     synchronises-with (1), sees compute()'s result
```

Reference count, as `shared_ptr` implementations do it:

```cpp
void retain() { count_.fetch_add(1, std::memory_order_relaxed); }   // owner already has a ref
void release() {
    if (count_.fetch_sub(1, std::memory_order_acq_rel) == 1) delete this;  // last owner sees all writes
}
```

CAS loop (`compare_exchange_weak` may fail spuriously, so loop; it reloads `cur` on failure):

```cpp
void update_max(std::atomic<int>& m, int v) {     // C++26 adds m.fetch_max(v)
    int cur = m.load(std::memory_order_relaxed);
    while (cur < v && !m.compare_exchange_weak(cur, v, std::memory_order_relaxed)) {}
}
```

Rules:
1. Write the happens-before argument next to every non-`seq_cst` operation:
   `// relaxed: only read after workers are joined; join() synchronises`.
2. Fences (`std::atomic_thread_fence(release)` before a relaxed store pairs with an acquire fence
   after a relaxed load) are for batching many relaxed operations; ThreadSanitizer does not
   support `atomic_thread_fence` and can report false positives (GCC documents this).
3. x86 is TSO (stores are not reordered with stores, loads not with loads), ARM and POWER are
   not: relaxed code "tested on x86" is untested. Run TSan, and model checkers for lock-free code.
4. `memory_order` mistakes involving only atomics are not data races, so TSan stays silent; it
   reports them only when they leave a plain access unordered (section 11).

## 3. Lock discipline

1. One lock hierarchy: number every mutex with a level, acquire in strictly decreasing level
   order, and enforce it in debug builds (checking mutex in
   [memory-model-patterns](references/memory-model-patterns.md)). Two mutexes at the same
   level are only ever taken together through `std::scoped_lock(a, b)`.
2. Never call unknown code under a lock: callbacks, virtual functions, signals/observers,
   allocation-heavy or I/O work. Copy what you need, unlock, then call.
3. Minimal critical sections: compute outside, lock, swap/commit, unlock.
4. Condition variables: always wait with a predicate (`cv.wait(lk, [&] { return !q.empty(); })`)
   to absorb spurious wakeups; modify the predicate's state while holding the mutex, even if the
   variable is atomic, or the notification can fall between the waiter's check and its sleep
   (lost wakeup).
5. Clang codebases: thread-safety annotations turn the discipline into compile errors
   (`GUARDED_BY(mu)`, `REQUIRES(mu)`, `ACQUIRE()`/`RELEASE()` macros over `capability`
   attributes, `-Wthread-safety`); abseil's `absl::Mutex` ships annotated.
6. Deadlock diagnosis: TSan reports lock-order inversions (`detect_deadlocks=1` is the default;
   add `second_deadlock_stack=1`); a hung process: `gdb -p <pid> -batch -ex 'thread apply all bt'`
   or `lldb -p <pid> --batch -o 'thread backtrace all'`, then look for two threads each holding
   what the other waits for.

## 4. Thread lifecycle

```cpp
std::jthread worker([&q](std::stop_token st) {           // jthread passes its stop_token first
    while (auto item = q.pop_wait(st)) process(*item);    // pop_wait: cv_any.wait(lk, st, pred)
});                                                       // ~jthread: request_stop() then join()
```

- Never `detach()` a thread that touches objects with bounded lifetimes; prefer `jthread`
  members declared **last** in a class so they are destroyed (joined) first.
- An exception escaping a thread function calls `std::terminate`. Carry it out:

```cpp
std::exception_ptr err;                                   // one slot per worker
std::jthread t([&] { try { run(); } catch (...) { err = std::current_exception(); } });
t.join();                                                 // join synchronises the write to err
if (err) std::rethrow_exception(err);
```

- Thread pools: BS::thread_pool v5 (single header `BS_thread_pool.hpp`, C++17+):
  `BS::thread_pool pool;` then `auto f = pool.submit_task([] { return 42; });` (future),
  `pool.detach_task(fn)`, `pool.submit_loop(0, n, fn)` / `pool.detach_loop(...)`, `pool.wait()`.
  oneTBB: `tbb::task_group g; g.run(fn); g.wait();`, `tbb::parallel_for`, `tbb::task_arena a(4);
  a.execute(fn)` to cap concurrency, `tbb::global_control` for a process-wide cap.
- Oversubscription: one pool per process sized from configuration (fallback
  `std::thread::hardware_concurrency()`, which may return 0 and ignores container CPU quotas);
  never block a pool thread waiting on another task in the same pool (all workers waiting =
  deadlock); do not mix OpenMP, TBB and a private pool in one hot path.

## 5. False sharing

Independent data written by different threads must sit on different cache lines. Measured
(Apple M-series, 4 threads x 20M relaxed `fetch_add` on adjacent counters): packed 8-byte slots
**887 ms**, `alignas(64)` 64 ms, `alignas(128)` 39 ms (this CPU reports
`hw.cachelinesize: 128`).

```cpp
struct alignas(128) Slot { std::atomic<std::uint64_t> v{0}; };   // 64 = x86 line; 128 for Apple silicon and Intel adjacent-line prefetch
std::vector<Slot> slots(n_threads);                               // C++17 aligned new honours alignas
// better: per-thread plain accumulators, merged once at the end
std::vector<Slot> partial(n_threads);
// worker i: local sum in a register, then partial[i].v.store(sum, relaxed); merge after join()
```

`std::hardware_destructive_interference_size` is a compile-time constant that varies by target
and compiler (Apple clang 21, arm64: 256 destructive / 64 constructive) and GCC warns
(`-Winterference-size`) about using it in ABI-visible layouts; a project constant (64 or 128) is
more predictable. Put a producer's and a consumer's hot fields (e.g. queue head and tail) on
separate lines too.

## 6. Lock-free code and memory reclamation

Default answer: do not write it. Use a mutex or an existing library (folly, boost.lockfree,
moodycamel::ConcurrentQueue) unless a profile shows lock contention dominating **and** a
published algorithm fits. Lock-free is about progress guarantees, not speed.

| Problem | What goes wrong | Mitigation |
|---|---|---|
| ABA | CAS sees the same pointer value after the node was freed and reused | never free while others may hold it (reclamation below); tagged pointer + counter with a double-width CAS (`std::atomic<16-byte struct>`: lock-free on arm64 here, needs `cmpxchg16b`/`-mcx16` on x86-64 and may still go through libatomic) |
| use-after-free on pop | a reader dereferences a node another thread just deleted | hazard pointers, RCU/epochs, or a design where only one thread frees (section 11) |
| reclamation cost | refcounting every node (`shared_ptr`) is slow and not lock-free | hazard pointers (bounded garbage) or RCU (cheap readers) |

C++26 APIs (no shipping std implementation listed; `folly::hazptr`, folly RCU and liburcu today):

```cpp
struct Config : std::hazard_pointer_obj_base<Config> { /* ... */ };
std::atomic<Config*> current;
// reader                                              // writer
std::hazard_pointer hp = std::make_hazard_pointer();   // Config* old = current.exchange(fresh);
Config* c = hp.protect(current);                       // old->retire();   // freed when unprotected
use(*c);

struct Table : std::rcu_obj_base<Table> { /* ... */ };
{ std::scoped_lock rd(std::rcu_default_domain());      // read-side critical section
  use(*table.load(std::memory_order_acquire)); }
// writer: Table* old = table.exchange(fresh, std::memory_order_acq_rel); old->retire();
//         std::rcu_synchronize() blocks until pre-existing readers finished
```

`std::atomic<std::shared_ptr<const T>>` publishes immutable snapshots simply, but check
`is_lock_free()`: libstdc++ implements it with an internal lock bit (not lock-free), libc++ does
not provide it. Gate on `__cpp_lib_atomic_shared_ptr`; fallbacks: a mutex-guarded `shared_ptr`
(TSan-checked listing in [memory-model-patterns](references/memory-model-patterns.md)), the
`std::atomic_load` free functions (deprecated in C++20, removed in C++26), or
`folly::atomic_shared_ptr` / `boost::atomic_shared_ptr`. Readers never see a half-built snapshot
because it is fully constructed before publication and immutable afterwards.

## 7. Coroutines

Checked under ASan with a lazily started task type (Apple clang 21):

| Rule | Failure when broken | Fix |
|---|---|---|
| take parameters by value | `Task f(const std::string& s)` called with a temporary: the frame keeps a dangling reference (ASan: stack-use-after-scope) | `Task f(std::string s)` |
| no state in lambda captures | `[name]() -> Task { ... }` : the closure dies, the frame only holds `this` (ASan: stack-use-after-scope) | pass state as parameters, or C++23 `[name](this auto self) -> Task { ... }`: `self` is a by-value parameter copied into the frame (checked: works) |
| awaiter does not touch itself after handing off the handle | `await_suspend` enqueues the handle; another thread resumes and destroys the frame while `await_suspend` is still running | publish the handle as the last action of `await_suspend` |
| no `co_await` inside a `catch` block | ill-formed | store `std::current_exception()`, `co_await` after the handler |
| symmetric transfer for chains | resuming continuations from `await_suspend` recursively overflows the stack | `await_suspend` returns `std::coroutine_handle<>` of the next coroutine |
| frames are heap allocations | allocation per call, elision (HALO) not guaranteed | promise `operator new` with a pool; keep coroutines off the hottest paths |
| resumption thread is wherever the operation completed | data touched on the "wrong" thread | executor-aware awaitables (Asio strands, `co_spawn(strand, ...)`), re-schedule explicitly |

Libraries (you need one; the language provides only machinery): Asio / Boost.Asio
(`asio::awaitable<T>`, `asio::co_spawn(ex, coro(), asio::detached)`, `asio::use_awaitable`),
libcoro (`coro::task<T>`, `coro::sync_wait`, `coro::thread_pool`, `coro::when_all`), folly
(`folly::coro::Task<T>`, `folly::coro::blockingWait`), C++23 `std::generator` (libstdc++ 14,
MSVC 19.43; not libc++), C++26 `std::execution::task` (P3552). Details and an Asio skeleton in
[coroutines-execution](references/coroutines-execution.md).

## 8. std::execution (C++26)

Model: a **scheduler** produces senders (`schedule(sch)`); **senders** describe lazy work and
compose; nothing runs until a sender is connected and started (`sync_wait`, `spawn`).

| Algorithm | Role |
|---|---|
| `just(v...)` | sender of values |
| `then(f)` | transform values synchronously |
| `let_value(f)` | `f` returns a sender: dependent asynchronous step |
| `when_all(s...)` | run concurrently, join values; first error or stop cancels the rest |
| `starts_on(sch, s)`, `continues_on(s, sch)`, `on(sch, s)` | choose where work and continuations run |
| `std::this_thread::sync_wait(s)` | block; returns `std::optional<std::tuple<...>>` (empty if stopped), rethrows errors |
| `get_parallel_scheduler()` (P2079) | system thread pool |
| `counting_scope` + `spawn` / `spawn_future` (P3149) | structured fire-and-forget with a join point (`start_detached` and `ensure_started` were removed) |

Reference implementation today: NVIDIA stdexec (`#include <stdexec/execution.hpp>`, namespace
`stdexec`, extensions such as `exec::static_thread_pool` in `<exec/...>`); names changed during
standardisation (`transfer` became `continues_on`), so match the stdexec version you pin.

```cpp
namespace ex = stdexec;
auto sch = ex::get_parallel_scheduler();
auto work = ex::when_all(ex::on(sch, ex::just(1) | ex::then(load_a)),
                         ex::on(sch, ex::just(2) | ex::then(load_b)));
auto [a, b] = ex::sync_wait(std::move(work)).value();
```

Migrating from futures: `std::async` + `get()` becomes `starts_on(sch, just() | then(f))` +
`sync_wait`; chained `.then` (never standardised) becomes `| then(f)`; manual "wait for all
futures" becomes `when_all`; exceptions travel on the error channel; cancellation comes from
stop tokens, which futures never had.

## 9. Testing concurrent code

1. TSan in its own build and CI job (not combinable with ASan or MSan): `-fsanitize=thread -O1 -g`,
   `TSAN_OPTIONS=halt_on_error=1:second_deadlock_stack=1`; without `halt_on_error` the process
   exits with status 66 when it reported anything. Expect 5-15x slowdown and 5-10x memory;
   everything, including third-party code, should be instrumented.
2. Stress: run each concurrent test 100-1000 times (`--gtest_repeat=1000 --gtest_shuffle`,
   `ctest --repeat until-fail:100`), inject `std::this_thread::yield()` or tiny random sleeps at
   synchronisation points behind a test-only macro, and run with many cores and with one
   (`taskset -c 0` on Linux).
3. Model checking for lock-free algorithms: Relacy (header-only; replaces `std::atomic` with its
   own types and explores interleavings and weak-memory outcomes), CDSChecker, GenMC (LLVM-based);
   herd7/CppMem for small litmus tests.
4. Deterministic schedulers in unit tests: inject the executor and clock; tests use a manual
   executor that runs queued tasks in a chosen order (or a single-threaded `run_loop` /
   `io_context`) so a race becomes a reproducible ordering.
5. Reproduce a heisenbug on Linux with `rr record --chaos ./test`, then replay deterministically.
6. Never "fix" a flaky test with a sleep: find the missing happens-before edge.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| flag polled in a loop never seen, or loop deleted by the optimiser | `volatile bool` / plain `bool` flag | `std::atomic<bool>` (or `std::stop_token`) |
| singleton half-constructed on another thread | double-checked locking on a plain pointer | function-local `static`, `std::call_once`, or acquire/release atomics (patterns reference) |
| waiter sleeps forever | wait without a predicate, or predicate state changed without the mutex | `cv.wait(lk, pred)`; update state under the lock |
| `std::async(f)` never runs, `wait_for` loop spins | default policy may defer: `wait_for` returns `future_status::deferred` | pass `std::launch::async` explicitly |
| "parallel" `std::async` calls run one by one | discarded temporary future blocks in its destructor | keep the futures, or use a pool / `when_all` |
| crash at exit in a worker | threads still running while statics are destroyed | join all threads before `main` returns; jthread members; leak (`static auto& x = *new T;`) objects threads use during shutdown |
| `std::terminate` from a thread | exception escaped the thread function, or `std::thread` destroyed while joinable | catch and forward via `exception_ptr`; `std::jthread` |
| data race on `shared_ptr` | one thread assigns `sp` while another copies it | `std::atomic<std::shared_ptr<T>>` or a mutex |
| scaling collapses with more threads | false sharing, one hot mutex or atomic | padding, sharding, per-thread accumulation |
| TSan report inside a fence-based algorithm | TSan does not model `atomic_thread_fence` | express the edge with acquire/release operations, or suppress with a reason |

## 11. Worked example: fix the orderings of an MPSC queue, verified under TSan

A Vyukov-style unbounded multi-producer single-consumer queue arrived with every operation
`memory_order_relaxed` ("it passed the tests on x86"):

```cpp
template <class T>
class MpscQueue {
    struct Node { std::atomic<Node*> next{nullptr}; std::optional<T> value; };
    alignas(64) std::atomic<Node*> head_;     // producers swap themselves in here
    alignas(64) Node* tail_;                  // consumer only: plain pointer
public:
    MpscQueue() : head_(new Node), tail_(head_.load(std::memory_order_relaxed)) {}
    ~MpscQueue() { while (pop()) {} delete tail_; }      // precondition: producers stopped
    void push(T v) {
        Node* n = new Node;
        n->value.emplace(std::move(v));
        Node* prev = head_.exchange(n, std::memory_order_acq_rel);   // was relaxed
        prev->next.store(n, std::memory_order_release);             // was relaxed
    }
    std::optional<T> pop() {                                         // one consumer thread only
        Node* tail = tail_;
        Node* next = tail->next.load(std::memory_order_acquire);     // was relaxed
        if (next == nullptr) return std::nullopt;   // empty, or a producer is between exchange and link
        std::optional<T> out = std::move(next->value);
        next->value.reset();                        // next becomes the new stub
        tail_ = next;
        delete tail;                                // its producer already finished linking
        return out;
    }
};
```

Review, edge by edge:

| Edge | Needed because | Order |
|---|---|---|
| producer A `exchange` -> producer B `exchange` | B receives A's node as `prev` and stores into `prev->next`; that store must happen after A constructed the node (the atomic's initialisation is a plain write) | B's exchange must **acquire**, A's must **release**; every producer is both, so `acq_rel` |
| producer `next.store(n)` -> consumer `next.load()` | the consumer reads `n->value`, written with plain stores before the link | `release` / `acquire` pair |
| consumer `delete tail` | the only producer that touched `tail` did so by storing `tail->next`, which the consumer already acquired; each node is `prev` for exactly one producer, so no hazard pointers are needed | follows from the pair above |

Test driver: 4 producers x 50,000 pushes, one consumer popping until it has 200,000 items,
checking the sum. Results (`clang++ -std=c++23 -O1 -g -fsanitize=thread`, Apple clang 21, arm64):

| Variant (exchange / link store / consumer load) | TSan |
|---|---|
| relaxed / relaxed / relaxed (original) | `WARNING: ThreadSanitizer: data race`: atomic write in `push` (the `prev->next` store) vs previous write by another thread in `Node::Node()` |
| relaxed / release / acquire | same report: producer-to-producer edge missing |
| release / release / acquire and acquire / release / acquire | 1 report each: half of `acq_rel` is not enough |
| acq_rel / relaxed / acquire | `Read of size 8 ... by main thread` in `pop()` vs `Previous write` in `push()` on `value` |
| acq_rel / release / relaxed | same `value` race |
| acq_rel / release / acquire (fixed) | clean in 6 consecutive runs, `sum=19999900000 expected=19999900000`; 0.21 s for 200,000 items at `-O2` without TSan |

```bash
clang++ -std=c++23 -O1 -g -fsanitize=thread mpsc_test.cpp -o mpsc_test
for i in $(seq 1 20); do TSAN_OPTIONS=halt_on_error=1 ./mpsc_test || break; done
```

Remaining design limits to document in the header: `pop()` can report empty while a producer
sits between its `exchange` and its link (the queue is not linearizable at that instant;
consumers must tolerate a transient empty); single consumer only (assert the consumer thread id
in debug builds); unbounded memory under a slow consumer; nodes are allocated per push (pool them
if a profile says so). On Apple silicon use `alignas(128)` for `head_`/`tail_`.

Related: `cpp-memory-raii`, `cpp-ub-sanitizers`, `cpp-testing-fuzzing`, `cpp-simd-performance`,
`cpp-templates-concepts`, hub `cpp-craft`.
