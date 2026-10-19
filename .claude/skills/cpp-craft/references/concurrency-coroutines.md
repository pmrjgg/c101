# C++ concurrency, memory model and coroutines

## 1. Choosing a synchronization tool

| Need | Tool |
|---|---|
| protect compound state | `std::mutex` + `std::scoped_lock` / `std::unique_lock` |
| many readers, rare writers, long reads | `std::shared_mutex` (measure: often slower than a mutex for short sections) |
| wait for a condition | `std::condition_variable_any` with `std::stop_token` (wakes on stop) |
| one-time init | function-local static (thread-safe), `std::call_once` |
| counters, flags, stats | `std::atomic<T>` with relaxed or acq/rel orderings |
| wait on an atomic value | `atomic.wait(old)` / `notify_one()` (C++20, futex-backed on Linux) |
| N threads rendezvous | `std::barrier` (reusable), `std::latch` (one-shot) |
| bounded resource | `std::counting_semaphore<N>` |
| cancellable thread | `std::jthread` + `std::stop_token` / `std::stop_callback` |
| immutable snapshot publication | `std::atomic<std::shared_ptr<const T>>` (gate on `__cpp_lib_atomic_shared_ptr`; libc++ lacks it: mutex-guarded `shared_ptr`), RCU (C++26 `<rcu>`) |
| task parallelism | thread pool library (TBB `task_group`, BS::thread_pool), `std::execution` (C++26) with stdexec today |
| data-parallel loops | `std::for_each(std::execution::par_unseq, ...)` (requires TBB backend on libstdc++), OpenMP, TBB `parallel_for` |

## 2. Memory orders

| Order | Guarantees | Canonical use |
|---|---|---|
| `memory_order_relaxed` | atomicity only; no ordering with other memory | statistics counters, unique ID generation |
| `memory_order_release` (store) | all prior writes visible to a thread that acquires this value | publish data then set flag |
| `memory_order_acquire` (load) | subsequent reads see writes released before the matching store | read flag then read data |
| `memory_order_acq_rel` (RMW) | both | refcount decrement, lock-free queue CAS |
| `memory_order_seq_cst` | acq/rel plus a single total order of all seq_cst ops | default; needed for Dekker/Peterson-style "store then load other flag" |
| `memory_order_consume` | deprecated (C++26); compilers treat as acquire | do not use |

Publication pattern:

```cpp
Data payload;                         // plain memory
std::atomic<bool> ready{false};
// producer
payload = compute();
ready.store(true, std::memory_order_release);
// consumer
while (!ready.load(std::memory_order_acquire)) { ready.wait(false, std::memory_order_acquire); }
use(payload);                         // guaranteed to see compute()'s result
```

Reference count (as in `shared_ptr` implementations):

```cpp
void retain() { count.fetch_add(1, std::memory_order_relaxed); }
void release() {
    if (count.fetch_sub(1, std::memory_order_acq_rel) == 1) delete this;
}
```

Rules:
- Write the happens-before argument in a comment next to every non-seq_cst atomic.
- Check `std::atomic<T>::is_always_lock_free` for types on hot paths; large `T` uses a lock.
- `compare_exchange_weak` in loops (may fail spuriously), `compare_exchange_strong` otherwise.
- False sharing: put independently written atomics on separate cache lines:
  `struct alignas(64) PaddedCounter { std::atomic<uint64_t> v; };` (use 128 on Apple M-series).
  `std::hardware_destructive_interference_size` exists but GCC warns it is ABI-unstable.
- x86 is strongly ordered (TSO); ARM is not. Code "tested on x86" with relaxed orderings is
  untested. Run TSan and, for lock-free code, model checkers (CDSChecker/GenMC) or relacy.

## 3. Lock discipline

1. Keep critical sections short; never do I/O, allocation-heavy work, or callbacks under a lock.
2. Acquire multiple locks with `std::scoped_lock lk(a, b);` (deadlock-avoidance algorithm).
3. A documented lock hierarchy (level numbers) for anything with more than two mutexes.
4. Annotate with Clang thread-safety analysis (`GUARDED_BY(mu)`, `REQUIRES(mu)`, `-Wthread-safety`)
   in codebases that use Clang; it turns lock discipline into compile errors.
5. Condition variables: always wait with a predicate: `cv.wait(lk, [&]{ return !q.empty(); });`.

## 4. Thread lifecycle

```cpp
std::jthread worker([&q](std::stop_token st) {
    while (!st.stop_requested()) {
        auto item = q.pop_wait(st);       // queue wait honours stop_token
        if (!item) break;
        process(*item);
    }
});                                       // destructor requests stop and joins
```

- Never `detach()` threads that touch objects with bounded lifetimes.
- Exceptions escaping a thread function call `std::terminate`; catch at the top of the thread
  function and forward via `std::promise` / an error channel.

## 5. Coroutines

The language provides the machinery; you need a library type (`std::generator` in C++23,
`std::execution` task types in C++26, or Asio `awaitable`, folly `coro::Task`, cppcoro-like
libraries) for real use.

```cpp
std::generator<std::string_view> lines(std::string_view text) {
    while (!text.empty()) {
        auto pos = text.find('\n');
        co_yield text.substr(0, pos);
        text = pos == text.npos ? std::string_view{} : text.substr(pos + 1);
    }
}
for (auto line : lines(buf)) { ... }      // buf must outlive the loop
```

Pitfalls:

| Pitfall | Why | Fix |
|---|---|---|
| reference parameter dangles | the frame stores the reference; caller's temporary dies at the first suspension | take parameters by value in coroutines that suspend |
| lambda captures dangle | the closure object can be destroyed while the coroutine frame lives | pass state as coroutine parameters (by value), not captures; or keep the lambda alive |
| `co_await` in a `catch` block | ill-formed | capture `std::exception_ptr`, `co_await` after the handler |
| stack overflow in long synchronous chains | resumption recursion | symmetric transfer: `await_suspend` returns `std::coroutine_handle<>` |
| heap allocation per coroutine | frame allocation; HALO elision not guaranteed | custom `operator new` in the promise, pooling, or avoid coroutines on the hottest paths |
| lost exceptions | promise `unhandled_exception` swallowing | store `std::current_exception()` and rethrow on `await_resume` |
| thread hopping surprises | resuming on whichever thread completed the I/O | executor-aware awaitables (Asio `co_spawn(strand, ...)`), re-schedule explicitly |
| destroying a suspended coroutine leaks owned resources only if the frame owns raw resources | frame destroy runs destructors of live locals | RAII locals; own handles with an RAII task type |

Asio C++20 coroutine skeleton (Asio / Boost.Asio 1.8x+):

```cpp
asio::awaitable<void> session(asio::ip::tcp::socket s) {
    std::array<char, 4096> buf;
    for (;;) {
        auto n = co_await s.async_read_some(asio::buffer(buf), asio::use_awaitable);
        co_await asio::async_write(s, asio::buffer(buf.data(), n), asio::use_awaitable);
    }
}
// asio::co_spawn(io_ctx, session(std::move(sock)), asio::detached);
```

Timeouts with Asio coroutines: `using namespace asio::experimental::awaitable_operators;` then
`co_await (op() || timer.async_wait(asio::use_awaitable))`; check the Asio version for the
operator support.

## 6. std::execution (senders/receivers, C++26)

- Model: `scheduler` → `schedule()` returns a sender; compose with `then`, `let_value`,
  `when_all`, `continues_on`/`starts_on`; consume with `sync_wait` (blocking) or `start_detached`.
- Structured: work cannot outlive its scope; cancellation via stop tokens propagates.
- Reference implementation today: NVIDIA `stdexec` (`#include <stdexec/execution.hpp>`), which
  also targets GPUs via `nvexec`. Names have changed during standardization (`transfer` became
  `continues_on`, `on` became `starts_on`): match the library version in use.

```cpp
auto work = stdexec::when_all(
    stdexec::schedule(pool.get_scheduler()) | stdexec::then([] { return load_a(); }),
    stdexec::schedule(pool.get_scheduler()) | stdexec::then([] { return load_b(); }));
auto [a, b] = stdexec::sync_wait(std::move(work)).value();
```

## 7. Testing concurrent code

- TSan on every test run that touches threads (separate CI job).
- Stress tests: loop the test 1000x with random sleeps/yields injected at boundaries; run under
  `taskset` with 1 and with many cores.
- Deterministic schedule exploration for lock-free code: relacy, CDSChecker, GenMC.
- Never "fix" a flaky concurrent test with a sleep; find the missing happens-before edge.
