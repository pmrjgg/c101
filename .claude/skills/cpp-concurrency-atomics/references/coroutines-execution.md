# Coroutines and std::execution

## Coroutine anatomy in one table

| Piece | Who writes it | Role |
|---|---|---|
| return type (`Task<T>`, `generator<T>`) | library | owns the `std::coroutine_handle`, exposes awaiting or iteration |
| `promise_type` | library | `get_return_object`, `initial_suspend` (lazy: `suspend_always`), `final_suspend` (must be `noexcept`), `return_value`/`return_void`, `unhandled_exception`, optional `yield_value`, optional `operator new` |
| awaiter | library or user | `await_ready()` (skip suspension?), `await_suspend(h)` returning `void` (stay suspended), `bool` (false = resume immediately) or `coroutine_handle<>` (symmetric transfer to that coroutine), `await_resume()` (result of the `co_await` expression) |
| coroutine frame | compiler | heap-allocated (unless elided) copy of parameters and locals that live across suspensions |

Lifetime facts that cause most bugs:

1. Parameters are copied into the frame **by their declared type**: a `const T&` parameter copies
   the reference, not the object.
2. A lambda coroutine's captures live in the closure object, not in the frame; the frame holds
   only the closure's `this`. Fix: pass state as parameters, or C++23
   `[x](this auto self) -> Task<> { ... }` (the explicit object parameter is copied into the frame).
3. Temporaries in the full-expression containing `co_await` (including the awaiter) live in the
   frame until that full-expression completes.
4. After `await_suspend` publishes the handle (to a queue, another thread, an I/O completion),
   the coroutine may resume and even be destroyed before `await_suspend` returns: do not touch the
   awaiter or the frame after publishing.
5. `final_suspend` returning `suspend_always` keeps the frame alive so the owner can read the
   result; the owner must then `destroy()` it (RAII task type). Returning `suspend_never` frees the
   frame immediately: nobody may touch the handle afterwards.

## A lazy task with symmetric transfer (checked)

Compiled with Apple clang 21 at `-O0` and `-O2`: a loop of 1,000,000 synchronously completing
`co_await one()` calls finished with `sum=1000000`; the same task written with
`await_suspend` returning `void` and calling `resume()` crashed with a stack overflow
(exit 139) at both optimisation levels. Exceptions propagate through `co_await`.

```cpp
template <class T>
class Task {
public:
    struct promise_type {
        std::optional<T> value;
        std::exception_ptr error;
        std::coroutine_handle<> continuation = std::noop_coroutine();
        Task get_return_object() { return Task{std::coroutine_handle<promise_type>::from_promise(*this)}; }
        std::suspend_always initial_suspend() noexcept { return {}; }          // lazy start
        struct FinalAwaiter {
            bool await_ready() noexcept { return false; }
            std::coroutine_handle<> await_suspend(std::coroutine_handle<promise_type> h) noexcept {
                return h.promise().continuation;                               // symmetric transfer
            }
            void await_resume() noexcept {}
        };
        FinalAwaiter final_suspend() noexcept { return {}; }
        void return_value(T v) { value.emplace(std::move(v)); }
        void unhandled_exception() { error = std::current_exception(); }
    };

    explicit Task(std::coroutine_handle<promise_type> h) : h_(h) {}
    Task(Task&& o) noexcept : h_(std::exchange(o.h_, {})) {}
    Task& operator=(Task&&) = delete;
    ~Task() { if (h_) h_.destroy(); }

    bool await_ready() const noexcept { return false; }
    std::coroutine_handle<> await_suspend(std::coroutine_handle<> awaiting) noexcept {
        h_.promise().continuation = awaiting;
        return h_;                                                             // start the child
    }
    T await_resume() {
        if (h_.promise().error) std::rethrow_exception(h_.promise().error);
        return std::move(*h_.promise().value);
    }
    T sync_run() { h_.resume(); return await_resume(); }   // top level, synchronous work only
private:
    std::coroutine_handle<promise_type> h_;
};

Task<int> one() { co_return 1; }
Task<long> sum_loop(long n) {
    long total = 0;
    for (long i = 0; i < n; ++i) total += co_await one();
    co_return total;
}
```

`sync_run` is only valid when nothing suspends on real I/O; a production `sync_wait` blocks on a
latch or condition variable until the final awaiter signals it. Prefer a library task type.

## Libraries

| Library | Task type | Run it | Notes |
|---|---|---|---|
| Asio / Boost.Asio | `asio::awaitable<T>` | `asio::co_spawn(executor, f(), asio::detached)` then `io_context.run()` | completion token `asio::use_awaitable`; strands serialise handlers; `asio::experimental::awaitable_operators` gives `&&`/`\|\|` (check the version) |
| libcoro | `coro::task<T>` | `coro::sync_wait(task)` | `coro::thread_pool`, `coro::scheduler`, `coro::when_all`, `coro::mutex`, `coro::latch` |
| folly | `folly::coro::Task<T>` | `folly::coro::blockingWait(task)` | executors, cancellation, `collectAll` |
| C++23 standard | `std::generator<T>` | range-for | libstdc++ 14, MSVC 19.43; not in libc++ |
| C++26 standard | `std::execution::task<T>` (P3552) | `sync_wait`, `spawn` | no shipping implementation listed yet; stdexec provides `exec::task` |

Asio skeleton (echo session; not compiled here, Asio 1.2x+ / Boost 1.8x+ API):

```cpp
asio::awaitable<void> session(asio::ip::tcp::socket s) {      // socket by value: owned by the frame
    std::array<char, 4096> buf;
    for (;;) {
        std::size_t n = co_await s.async_read_some(asio::buffer(buf), asio::use_awaitable);
        co_await asio::async_write(s, asio::buffer(buf.data(), n), asio::use_awaitable);
    }
}
// acceptor loop: asio::co_spawn(io_ctx, session(std::move(sock)), asio::detached);
```

Timeouts: `using namespace asio::experimental::awaitable_operators;` then
`co_await (op() || timer.async_wait(asio::use_awaitable));` (the loser is cancelled; check that
your Asio version ships the operators).

`std::generator` (C++23, libstdc++ 14+):

```cpp
std::generator<std::string_view> lines(std::string_view text) {   // text must outlive iteration
    while (!text.empty()) {
        auto pos = text.find('\n');
        co_yield text.substr(0, pos);
        text = pos == std::string_view::npos ? std::string_view{} : text.substr(pos + 1);
    }
}
```

## Coroutine pitfalls (extended)

| Pitfall | Why | Fix |
|---|---|---|
| reference parameter dangles | the frame stores the reference; the caller's temporary dies at the first suspension | by-value parameters; clang-tidy `cppcoreguidelines-avoid-reference-coroutine-parameters` |
| capturing lambda coroutine | captures die with the closure | parameters or `this auto self`; clang-tidy `cppcoreguidelines-avoid-capturing-lambda-coroutines` |
| `co_await` while holding a `std::mutex` lock | the coroutine may resume on another thread, and `std::mutex` must be unlocked by its owner thread; other tasks on this thread deadlock | release before `co_await`, or a coroutine-aware mutex (`coro::mutex`, Asio strand) |
| `co_await` in a `catch` block | ill-formed | store `std::current_exception()`, `co_await` after the handler |
| exceptions disappear | `unhandled_exception` swallows them | store and rethrow in `await_resume` |
| frame leak | handle never destroyed when `final_suspend` suspends | RAII task type that destroys in its destructor |
| detached work outlives its data | fire-and-forget (`asio::detached`, `start_detached`) | structured scopes: `counting_scope`, Asio `co_spawn` with completion handlers that join |
| allocation per call on a hot path | frame allocation, HALO elision not guaranteed | promise `operator new` with a pool or arena; batch work per coroutine |

## std::execution (C++26) quick reference

Status: adopted (P2300 in 2024; `async_scope` P3149, `parallel_scheduler` P2079 and the
coroutine `task` P3552 in June 2025). No standard library ships it as of October 2026; NVIDIA
stdexec (header-only, C++20, GCC 12+ / Clang 16+ / MSVC 14.43+ / Xcode 16+) is the reference
implementation, under namespace `stdexec` with extras in `exec::`.

| Concept | Meaning |
|---|---|
| sender | lazy description of work that completes with values, an error, or "stopped" |
| receiver | the continuation that gets `set_value` / `set_error` / `set_stopped` |
| operation state | `connect(sender, receiver)` result; `start()` runs it; must stay alive until completion |
| scheduler | `schedule(sch)` returns a sender that completes on that execution resource |

Structured fire-and-forget with a join point (P3149):

```cpp
namespace ex = std::execution;
void run(ex::scheduler auto sch) {
    ex::counting_scope scope;
    ex::spawn(ex::on(sch, ex::just() | ex::then(work)), scope.get_token());   // returns void
    ex::sender auto fut = ex::spawn_future(ex::just(42), scope.get_token());   // eager, result later
    std::this_thread::sync_wait(ex::when_all(scope.join(), std::move(fut)));    // join() is a sender
}
```

stdexec version of a parallel fan-out (from the stdexec README):

```cpp
namespace ex = stdexec;
auto sched = ex::get_parallel_scheduler();
auto fun = [](int i) { return i * i; };
auto work = ex::when_all(ex::on(sched, ex::just(0) | ex::then(fun)),
                         ex::on(sched, ex::just(1) | ex::then(fun)),
                         ex::on(sched, ex::just(2) | ex::then(fun)));
auto [i, j, k] = ex::sync_wait(std::move(work)).value();   // 0 1 4
```

Migration table:

| Futures / threads | Senders |
|---|---|
| `std::async(std::launch::async, f)` | `ex::starts_on(sch, ex::just() \| ex::then(f))` |
| `fut.get()` | `std::this_thread::sync_wait(sndr)` (returns `optional<tuple<...>>`, rethrows errors) |
| hand-written `.then` chains | `sndr \| ex::then(f)`; dependent async step: `ex::let_value(f)` where `f` returns a sender |
| waiting for N futures | `ex::when_all(s1, s2, ...)` (cancels siblings on error) |
| detached thread | `ex::spawn(sndr, scope.get_token())` + `scope.join()` |
| `std::stop_token` plumbing by hand | stop tokens flow through receivers' environments automatically |

Names changed during standardisation (`transfer` became `continues_on`, `on` was split into
`starts_on` and a new `on`, `ensure_started`/`start_detached` were removed in favour of
`spawn_future`/`spawn`): match the API of the stdexec commit you pin.
