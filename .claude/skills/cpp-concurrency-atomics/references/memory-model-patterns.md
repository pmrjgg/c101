# Memory-model patterns

Every listing marked "checked" compiled with Apple clang 21 (`-std=c++23`) and ran clean under
`-fsanitize=thread` (`halt_on_error=1`) and at `-O2`.

## Litmus tests worth memorising

| Name | Threads | Outcome to rule out | Minimum ordering |
|---|---|---|---|
| message passing (MP) | T1: `data = 1; flag.store(1)`; T2: `if (flag.load()) r = data;` | `flag == 1 && r == 0` | release store / acquire load |
| store buffering (SB, Dekker) | T1: `x.store(1); r1 = y.load();` T2: `y.store(1); r2 = x.load();` | `r1 == 0 && r2 == 0` | `seq_cst` on all four (acquire/release is not enough; x86 also reorders store-load) |
| load buffering (LB) | T1: `r1 = x.load(); y.store(1);` T2: `r2 = y.load(); x.store(1);` | `r1 == 1 && r2 == 1` | acquire loads paired with release stores (either alone is not enough in the C++ model, although no mainstream CPU shows the outcome then) |
| IRIW | two writers, two readers reading in opposite orders | readers disagree on write order | `seq_cst` |
| coherence | any single atomic | going back in its modification order | any order (even relaxed) |

Explore small cases with herd7 or CppMem; use GenMC, CDSChecker or Relacy for whole algorithms.

## SPSC ring buffer (checked: 1,000,000 items, sum verified)

```cpp
template <class T, std::size_t N>
class SpscRing {
    static_assert((N & (N - 1)) == 0, "N must be a power of two");
    std::array<T, N> buf_{};
    alignas(128) std::atomic<std::size_t> head_{0};   // next slot to read: written by consumer
    alignas(128) std::atomic<std::size_t> tail_{0};   // next slot to write: written by producer
public:
    bool push(const T& v) {                                        // producer thread only
        const auto t = tail_.load(std::memory_order_relaxed);      // own index
        if (t - head_.load(std::memory_order_acquire) == N) return false;   // full
        buf_[t & (N - 1)] = v;                                     // consumer released this slot
        tail_.store(t + 1, std::memory_order_release);             // publish the slot
        return true;
    }
    std::optional<T> pop() {                                       // consumer thread only
        const auto h = head_.load(std::memory_order_relaxed);
        if (h == tail_.load(std::memory_order_acquire)) return std::nullopt;   // empty
        T v = buf_[h & (N - 1)];                                   // producer's write is visible
        head_.store(h + 1, std::memory_order_release);             // hand the slot back
        return v;
    }
};
```

Indices grow without wrapping logic (`size_t` overflow after 2^64 operations is irrelevant);
`t - head` works because both are unsigned. Optimisation once profiled: keep a producer-local
cached copy of `head_` and a consumer-local cached copy of `tail_`, reloading the shared one
only when the cache says full/empty; that removes most cross-core cache-line traffic.

## Seqlock for a small, frequently read value (checked: 200,000 writes, 0 torn reads)

```cpp
struct Quote { long bid, ask; };
class SeqLockQuote {                                    // single writer, many readers
    std::atomic<unsigned> seq_{0};
    std::atomic<long> bid_{0}, ask_{0};                 // data are atomics: no data race by construction
public:
    void write(Quote q) {
        const unsigned s = seq_.load(std::memory_order_relaxed);
        seq_.store(s + 1, std::memory_order_relaxed);   // odd: write in progress
        std::atomic_thread_fence(std::memory_order_release);
        bid_.store(q.bid, std::memory_order_relaxed);
        ask_.store(q.ask, std::memory_order_relaxed);
        seq_.store(s + 2, std::memory_order_release);   // even: stable
    }
    Quote read() const {
        for (;;) {
            const unsigned s1 = seq_.load(std::memory_order_acquire);
            Quote q{bid_.load(std::memory_order_relaxed), ask_.load(std::memory_order_relaxed)};
            std::atomic_thread_fence(std::memory_order_acquire);
            const unsigned s2 = seq_.load(std::memory_order_relaxed);
            if (s1 == s2 && (s1 & 1u) == 0) return q;
        }
    }
};
```

A seqlock over plain (non-atomic) data is a data race even though the retry discards torn reads:
the read itself is UB. Keep the payload in relaxed atomics (word-sized fields) or copy it with
`std::atomic_ref`. Multiple writers need a mutex around `write`. Readers can starve under a
constant stream of writes.

## Double-checked locking done right (checked)

```cpp
std::atomic<Widget*> g_instance{nullptr};
std::mutex g_init_mu;
Widget& instance() {
    Widget* p = g_instance.load(std::memory_order_acquire);    // fast path
    if (p == nullptr) {
        std::scoped_lock lk(g_init_mu);
        p = g_instance.load(std::memory_order_relaxed);        // the mutex orders this re-check
        if (p == nullptr) {
            p = new Widget;
            g_instance.store(p, std::memory_order_release);    // publish the constructed object
        }
    }
    return *p;
}
```

Prefer `static Widget& instance() { static Widget w; return w; }`: compilers implement the same
fast path (a guard variable with acquire semantics) and handle exceptions during construction.

## Lock hierarchy checker (checked: reversed order trips the assert)

```cpp
class HierarchicalMutex {
public:
    explicit HierarchicalMutex(unsigned level) : level_(level) {}
    void lock() {
        assert(level_ < current_level_ && "lock hierarchy violation: acquire lower levels only");
        m_.lock();
        previous_ = std::exchange(current_level_, level_);
    }
    void unlock() {
        current_level_ = previous_;
        m_.unlock();
    }
private:
    std::mutex m_;
    const unsigned level_;
    unsigned previous_ = 0;                             // only touched by the owning thread
    static thread_local unsigned current_level_;
};
thread_local unsigned HierarchicalMutex::current_level_ = UINT_MAX;
// HierarchicalMutex high(1000), low(100);  lock(high) then lock(low): fine; the reverse asserts
```

Unlock in reverse acquisition order (scoped locks do this). Compile the check out in release
builds if the `thread_local` access shows up in profiles.

## Clang thread-safety analysis (checked with `-Wthread-safety`)

```cpp
#define CAPABILITY(x)     __attribute__((capability(x)))
#define SCOPED_CAPABILITY __attribute__((scoped_lockable))
#define GUARDED_BY(x)     __attribute__((guarded_by(x)))
#define REQUIRES(...)     __attribute__((requires_capability(__VA_ARGS__)))
#define ACQUIRE(...)      __attribute__((acquire_capability(__VA_ARGS__)))
#define RELEASE(...)      __attribute__((release_capability(__VA_ARGS__)))

class CAPABILITY("mutex") Mutex {
public:
    void lock() ACQUIRE() { m_.lock(); }
    void unlock() RELEASE() { m_.unlock(); }
private:
    std::mutex m_;
};
class SCOPED_CAPABILITY Lock {
public:
    explicit Lock(Mutex& m) ACQUIRE(m) : m_(m) { m_.lock(); }
    ~Lock() RELEASE() { m_.unlock(); }
private:
    Mutex& m_;
};

class Account {
public:
    void deposit(long v) { Lock lk(mu_); balance_ += v; }      // ok
    void bad_deposit(long v) { balance_ += v; }                 // warning: writing variable 'balance_'
                                                                //   requires holding mutex 'mu_' exclusively
    void apply(long v) REQUIRES(mu_) { balance_ += v; }         // caller must hold mu_
private:
    Mutex mu_;
    long balance_ GUARDED_BY(mu_) = 0;
};
```

Make `-Werror=thread-safety` part of the Clang CI build once the annotations are in place. The
analysis is intra-procedural and trusts annotations; it does not replace TSan.

## Immutable snapshot publication (checked: 1 writer x 10,000 publishes, 3 readers, TSan clean)

```cpp
struct Snapshot { std::vector<int> data; };

#if defined(__cpp_lib_atomic_shared_ptr)          // libstdc++ 12+, MSVC 19.27+
class SnapshotCell {
    std::atomic<std::shared_ptr<const Snapshot>> current_;
public:
    void publish(std::shared_ptr<const Snapshot> s) { current_.store(std::move(s)); }   // seq_cst
    std::shared_ptr<const Snapshot> get() const { return current_.load(); }
};
#else                                             // libc++ (Apple clang): no atomic<shared_ptr>
class SnapshotCell {
    mutable std::mutex mu_;
    std::shared_ptr<const Snapshot> current_;
public:
    void publish(std::shared_ptr<const Snapshot> s) {
        std::scoped_lock lk(mu_);
        current_.swap(s);                         // old snapshot freed by s's destructor, after unlock
    }
    std::shared_ptr<const Snapshot> get() const { std::scoped_lock lk(mu_); return current_; }
};
#endif

SnapshotCell cell;
void publish(std::vector<int> d) { cell.publish(std::make_shared<const Snapshot>(Snapshot{std::move(d)})); }
int read_first() {
    auto s = cell.get();                          // the reader holds its own reference
    return s && !s->data.empty() ? s->data.front() : -1;
}
```

libstdc++'s `atomic<shared_ptr>` uses an internal lock bit, so `is_lock_free()` is false; on a
latency-critical read path prefer RCU or hazard pointers (C++26 `<rcu>`, `<hazard_pointer>`,
folly today). The mutex fallback keeps the critical section to a pointer copy and frees the old
snapshot outside the lock.

## Sharded counters (checked: 8 threads x 100,000 adds read back 800000)

```cpp
struct alignas(128) Shard { std::atomic<std::uint64_t> n{0}; };
class Counter {
    std::array<Shard, 16> shards_;
    static std::size_t slot() {                         // stable per thread
        static std::atomic<std::size_t> next{0};
        thread_local std::size_t mine = next.fetch_add(1, std::memory_order_relaxed);
        return mine % 16;
    }
public:
    void add(std::uint64_t v) { shards_[slot()].n.fetch_add(v, std::memory_order_relaxed); }
    std::uint64_t read() const {                        // approximate while writers run
        std::uint64_t s = 0;
        for (const auto& sh : shards_) s += sh.n.load(std::memory_order_relaxed);
        return s;
    }
};
```

`read()` is a sum of relaxed loads: exact only after writers are joined. Use it for statistics,
never for decisions that need a linearizable value.
