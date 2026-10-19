# Java concurrency: virtual threads, structured concurrency, scoped values, JMM

## 1. Virtual threads

Creation:

```java
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    executor.submit(() -> handle(request));
}                                               // close() waits for submitted tasks
Thread t = Thread.ofVirtual().name("worker-", 0).start(task);
ThreadFactory tf = Thread.ofVirtual().name("io-", 0).factory();
```

Framework switches: Spring Boot 3.2+ `spring.threads.virtual.enabled=true` (Tomcat/Jetty request
threads, `@Async`, schedulers); Quarkus `@RunOnVirtualThread` on endpoints; Helidon 4 is built
on virtual threads.

What changes and what does not:

| Topic | Guidance |
|---|---|
| throughput | improves only when threads mostly wait on I/O; CPU-bound work gains nothing |
| pooling | never pool virtual threads; create one per task |
| limiting concurrency | `Semaphore` around the scarce resource; DB pools (HikariCP) cap DB concurrency |
| `ThreadLocal` | works, but millions of threads x large cached values = memory; use `ScopedValue` or pass context |
| `synchronized` | JDK 24+ no longer pins (JEP 491); on 21-23, blocking inside `synchronized` pins the carrier: use `ReentrantLock` in hot paths |
| native calls / class initializers | still pin; keep blocking out of `<clinit>` and JNI upcalls |
| carrier pool size | defaults to cores; `-Djdk.virtualThreadScheduler.parallelism=N` (rarely needed) |
| pinning diagnostics | JFR `jdk.VirtualThreadPinned` (threshold 20 ms by default); the old `-Djdk.tracePinnedThreads` was removed in 24 |
| thread dumps | `jcmd <pid> Thread.dump_to_file -format=json out.json` (virtual threads grouped by container) |
| `Thread.sleep`, blocking queues, sockets, JDBC | unmount the virtual thread (JDK-integrated blocking) |
| `Object.wait()` | no longer pins as of 24 |

Migration checklist for a thread-per-request service:
1. Upgrade to JDK 24+ if possible (pinning fix); otherwise audit `synchronized` + I/O.
2. Enable virtual threads in the framework; keep the same code.
3. Add `Semaphore`s or pool limits for every downstream (DB, rate-limited APIs).
4. Load test: watch DB pool wait time, downstream error rates, heap (stacks now on heap).
5. Remove now-pointless async/reactive complexity only after the load test passes.

## 2. Structured concurrency (preview through JDK 25; API reshaped in 25)

JDK 25 (JEP 505) form, compiled and run with `--enable-preview`:

```java
record Dashboard(User user, List<Order> orders) {}

Dashboard load(long userId) throws InterruptedException {
    try (var scope = StructuredTaskScope.open()) {           // default joiner: all succeed or first failure cancels
        Subtask<User> user = scope.fork(() -> users.find(userId));
        Subtask<List<Order>> recentOrders = scope.fork(() -> orders.recent(userId));
        scope.join();                                       // throws FailedException if a subtask failed
        return new Dashboard(user.get(), recentOrders.get());
    }                                                       // close(): cancels unfinished subtasks, waits for them
}
```

Other joiners (`StructuredTaskScope.Joiner`): `awaitAllSuccessfulOrThrow()` (the default
policy), `anySuccessfulResultOrThrow()` (first success wins, rest cancelled), `awaitAll()`,
`allSuccessfulOrThrow()` (returns the subtasks), `allUntil(predicate)`. A timeout is configured
when opening the scope (`open(joiner, cf -> cf.withTimeout(Duration.ofSeconds(2)))`). JDK 21-24
used `new StructuredTaskScope.ShutdownOnFailure()` with `throwIfFailed()`; that code does not
compile on 25. Because the API is preview and changes between releases, pin the JDK version
and verify names against its Javadoc before writing code.

Without preview features, the equivalent with an executor:

```java
try (var ex = Executors.newVirtualThreadPerTaskExecutor()) {
    Future<User> u = ex.submit(() -> users.find(id));
    Future<List<Order>> o = ex.submit(() -> orders.recent(id));
    return new Dashboard(u.get(2, SECONDS), o.get(2, SECONDS));   // no automatic sibling cancellation
}
```

## 3. Scoped values (final in JDK 25)

```java
static final ScopedValue<RequestContext> CTX = ScopedValue.newInstance();

void handle(Request req) {
    ScopedValue.where(CTX, RequestContext.from(req)).run(() -> service.process(req));
}
// anywhere below in the call tree, including subtasks forked in a StructuredTaskScope:
RequestContext ctx = CTX.get();          // NoSuchElementException if unbound; isBound() to check
```

Immutable, bounded lifetime, inherited by structured subtasks, cheap with many virtual threads.
Replace `ThreadLocal` for request context; keep `ThreadLocal` only for per-thread caches of
expensive objects on platform-thread pools.

## 4. java.util.concurrent toolbox

| Need | Tool |
|---|---|
| counters under contention | `LongAdder` (reads are sums), `AtomicLong` for low contention |
| lock with tryLock/timeouts/conditions | `ReentrantLock`, `Condition` |
| read-mostly with long reads | `ReentrantReadWriteLock`; `StampedLock` optimistic reads for tiny critical sections |
| producer/consumer | `ArrayBlockingQueue` (bounded), `LinkedTransferQueue` |
| one-shot gate | `CountDownLatch`; reusable `CyclicBarrier`/`Phaser` |
| async pipelines (non-Loom style) | `CompletableFuture` with explicit executors, `orTimeout`, `completeOnTimeout` |
| scheduled tasks | `ScheduledExecutorService` (platform threads), not `Timer` |
| concurrency cap | `Semaphore` |

## 5. Java Memory Model essentials

- Happens-before edges: monitor unlock → later lock of the same monitor; `volatile` write →
  later read of the same variable; `Thread.start`; `Thread.join`; executor submission →
  task execution; `Future.get` after completion; `final` field freeze at constructor end.
- `volatile` gives visibility and ordering for a single variable, not atomic compound ops
  (`count++` on a volatile is a race).
- Safe publication: final fields, `volatile` reference, static initializer, concurrent
  collections, or a lock. Records with final fields of immutable types are safely publishable.
- Double-checked locking needs a `volatile` field; prefer the holder-class idiom or
  `StableValue`-style lazy constants (preview in 25) when available.
- `VarHandle` for fine-grained memory ordering (acquire/release, opaque) in lock-free code only.

## 6. Common concurrency bugs

| Bug | Symptom | Fix |
|---|---|---|
| check-then-act on `ConcurrentHashMap` | duplicates or lost updates | `computeIfAbsent`, `merge`, `compute` |
| long work inside `computeIfAbsent` | contention, recursive update `IllegalStateException` | compute outside, `putIfAbsent` |
| blocking `get()` in a `ForkJoinPool` task | pool starvation | `join` within FJ, or separate executor |
| unbounded `newCachedThreadPool` | thread explosion under load | bounded pool or virtual threads + semaphore |
| `CompletableFuture` chains without executor | work runs on common pool or completing thread | `thenApplyAsync(fn, executor)` |
| lost exceptions in `CompletableFuture` | never joined, no `exceptionally` | always attach handling or join |
| `ExecutorService` never shut down | JVM does not exit, thread leak | try-with-resources (`ExecutorService` is `AutoCloseable` since 19) |
| non-thread-safe shared objects | `SimpleDateFormat`, `HashMap`, `ArrayList` under concurrent writes | `DateTimeFormatter`, concurrent collections, confinement |

## 7. Testing concurrency

- jcstress for memory-model level tests of lock-free code (`@JCStressTest`, `@Outcome`).
- Stress tests with many iterations and randomized scheduling; run on machines with many cores.
- Awaitility (`await().atMost(5, SECONDS).until(...)`) instead of `Thread.sleep` in async tests.
- Thread-leak checks: compare `Thread.getAllStackTraces()` before and after, or framework hooks.
