---
name: java-virtual-threads
description: "Java concurrency on Project Loom: virtual threads vs platform pools, bounding concurrency with semaphores, pinning detection (JEP 491 and what still pins), structured concurrency with the JDK 25 preview API, ScopedValue, CompletableFuture executors, the java.util.concurrent toolbox, Java Memory Model essentials, thread dumps and jcstress testing. Load when migrating to virtual threads or debugging Java concurrency."
when_to_use: "Replacing Executors.newFixedThreadPool or thread-per-request code with virtual threads; spring.threads.virtual.enabled; jdk.VirtualThreadPinned events or carrier starvation; StructuredTaskScope or ScopedValue code and --enable-preview errors; CompletableFuture on the common pool; deadlocks, lost updates, ConcurrentHashMap 'Recursive update', thread dumps (jcmd Thread.dump_to_file); flaky async tests; jcstress."
---

# Java virtual threads and concurrency

Virtual threads are final since 21; `synchronized` stops pinning in 24 (JEP 491); scoped values
are final in 25 (JEP 506); structured concurrency is still preview (25: JEP 505, 26: JEP 525,
27: JEP 533) and its API changes every release. Version-by-version API differences and a custom
joiner: [structured concurrency by JDK](references/structured-concurrency-versions.md);
memory-model test recipes: [jcstress recipes](references/jcstress-recipes.md).

## 1. Pick the execution model per workload

| Workload | Use | Limit / note |
|---|---|---|
| many concurrent blocking calls (HTTP, JDBC, RPC, files) | a virtual thread per task: `Executors.newVirtualThreadPerTaskExecutor()` | blocking unmounts the virtual thread; stacks live on the heap |
| CPU-bound parallel work | `ForkJoinPool`, parallel streams, or a fixed pool of `availableProcessors()` platform threads | virtual threads add nothing; carriers = cores |
| I/O fan-out followed by heavy CPU work | virtual threads for I/O, hand CPU work to a bounded platform pool | CPU hogs on carriers delay every virtual thread |
| a downstream allows N concurrent calls | `Semaphore(N)` around the call (or the client's connection pool) | never a pool of virtual threads |
| request-scoped context | `ScopedValue` | `ThreadLocal` x millions of threads = memory |
| periodic tasks | `ScheduledExecutorService` (platform) that submits work to a virtual executor | no `Timer` |
| event-loop frameworks (Netty, Vert.x, Quarkus reactive) | keep the loop non-blocking; offload blocking work to virtual threads | a blocked loop stalls every connection it serves |

Capacity check with Little's law: in-flight calls L = arrival rate x latency. 2,000 req/s x 50 ms
DB time = 100 concurrent queries; if the database sustains ~20 (HikariCP's starting point:
cores x 2 + effective spindles), cap at 20 and accept queueing, or fix the query.

## 2. Migration recipe

1. Prefer JDK 24+ (no `synchronized` pinning). On 21-23 audit `synchronized` blocks that do I/O.
2. Replace I/O thread pools with a virtual-thread-per-task executor; close it (try-with-resources
   for request-scoped fan-out, or on application shutdown for a long-lived one).
3. Framework switches: Spring Boot 3.2+ `spring.threads.virtual.enabled=true` (web server
   threads, `@Async`, schedulers); Quarkus `@RunOnVirtualThread`; Helidon 4 runs on virtual threads.
4. Bound every downstream: `Semaphore` per remote API, HikariCP `maximumPoolSize` plus a
   `connectionTimeout`, HTTP client pool limits. Concurrency now equals offered load.
5. Remove thread-count assumptions: per-thread caches in `ThreadLocal` (buffers, `SimpleDateFormat`),
   monitoring via `Thread.getAllStackTraces()` (platform threads only), thread-name-based logic.
6. Load test and watch: pool wait time, downstream 429/5xx, heap (stacks), `jdk.VirtualThreadPinned`.
7. Remove reactive or callback complexity only after the load test passes.

```java
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {   // close() waits for tasks
    executor.submit(() -> handle(request));
}
ThreadFactory io = Thread.ofVirtual().name("io-", 0).factory();      // named: io-0, io-1, ...
ExecutorService named = Executors.newThreadPerTaskExecutor(io);
```

## 3. Pinning

A pinned virtual thread blocks while holding its carrier, so carriers (default count = cores,
`-Djdk.virtualThreadScheduler.parallelism=N`) run out.

| Cause | JDK 21-23 | JDK 24+ |
|---|---|---|
| blocking inside `synchronized` / `Object.wait()` | pins | no longer pins (JEP 491) |
| native method or FFM downcall that calls back into Java and blocks | pins | pins |
| blocking inside a class initializer (`<clinit>`), waiting for another thread's class init | pins | pins |
| diagnostics | JFR `jdk.VirtualThreadPinned` (enabled, threshold 20 ms); `-Djdk.tracePinnedThreads=full` | JFR event only; `jdk.tracePinnedThreads` was removed |

```bash
jcmd <pid> JFR.start name=pin settings=profile jdk.VirtualThreadPinned#threshold=5ms duration=5m filename=/tmp/pin.jfr
jfr view pinned-threads /tmp/pin.jfr                     # method, count, longest, total pinned time
jfr print --events jdk.VirtualThreadPinned --stack-depth 30 /tmp/pin.jfr
```

On 21-23, convert hot `synchronized` sections that block to `ReentrantLock`:

```java
private final ReentrantLock lock = new ReentrantLock();
Token refresh() throws IOException, InterruptedException {
    lock.lock();
    try { return token = authClient.fetchToken(); }      // blocking I/O no longer pins
    finally { lock.unlock(); }
}
```

Keep blocking out of static initializers; move one-time I/O to an explicit lazy method.

## 4. Structured concurrency (preview, JDK 25 API)

Compile and run with `--enable-preview` on exactly the JDK you compiled for (`javac --release 25
--enable-preview`, Surefire `argLine` too). The default `open()` policy waits for all subtasks
and fails fast on the first failure.

```java
import java.util.concurrent.StructuredTaskScope;
import java.util.concurrent.StructuredTaskScope.Joiner;
import java.util.concurrent.StructuredTaskScope.Subtask;   // not .*: its TimeoutException clashes with j.u.c.TimeoutException

record Dashboard(User user, List<Order> orders) {}

Dashboard load(long userId) throws InterruptedException {
    try (var scope = StructuredTaskScope.open()) {
        Subtask<User> user = scope.fork(() -> users.find(userId));
        Subtask<List<Order>> orders = scope.fork(() -> orderClient.recent(userId));
        scope.join();                        // FailedException (cause = first failure) cancels the rest
        return new Dashboard(user.get(), orders.get());
    }                                        // close(): cancels stragglers and waits for their threads
}
```

| JDK 25 joiner (`StructuredTaskScope.Joiner`) | `join()` returns | On failure |
|---|---|---|
| default `open()` / `awaitAllSuccessfulOrThrow()` | `null` | first failure cancels the scope, `FailedException` |
| `allSuccessfulOrThrow()` | `Stream<Subtask<T>>` (26+: `List<T>`) | same |
| `anySuccessfulResultOrThrow()` (26+: `anySuccessfulOrThrow()`) | first successful result `T` | `FailedException` only if all fail |
| `awaitAll()` (removed in 27) | `null`; inspect each `Subtask.state()` | never cancels |
| `allUntil(predicate)` | `Stream<Subtask<T>>` of all subtasks | cancels when the predicate returns true |

```java
try (var scope = StructuredTaskScope.open(
        Joiner.<Price>anySuccessfulResultOrThrow(),
        cf -> cf.withTimeout(Duration.ofMillis(800)).withName("price-race"))) {
    mirrors.forEach(m -> scope.fork(() -> m.price(sku)));
    return scope.join();                     // StructuredTaskScope.TimeoutException after 800 ms
}
```

Semantics: only the owner thread may `fork`, `join` and `close`; `fork` after `join` throws
`IllegalStateException`; cancellation interrupts unfinished subtasks, and `close()` waits for
all of them, so subtasks must respond to interruption; `Subtask.get()` is legal only after
`join()` and only in state `SUCCESS` (`exception()` for `FAILED`). In 27 `join()` throws
`ExecutionException` by default. Without preview, use `ExecutorService.invokeAll(tasks, timeout,
unit)` (cancels unfinished tasks at the deadline) or `invokeAny` (first success wins).

## 5. ScopedValue (final in 25)

```java
static final ScopedValue<RequestContext> CTX = ScopedValue.newInstance();
static final ScopedValue<Locale> LOCALE = ScopedValue.newInstance();

void handle(Request req) {
    ScopedValue.where(CTX, RequestContext.from(req)).run(() -> service.process(req));
}
Invoice render(Order o) throws IOException {
    return ScopedValue.where(LOCALE, Locale.GERMANY).call(() -> renderer.render(o));  // result + checked exception
}
RequestContext ctx = CTX.get();              // NoSuchElementException if unbound; isBound(), orElse(non-null)
```

Bindings are immutable and last for the `run`/`call`; a callee may rebind for its own callees.
Subtasks forked in a `StructuredTaskScope` inherit bindings without copying; plain executors and
`ForkJoinPool` do not. Migrate `ThreadLocal`s used for one-way, caller-to-callee context; keep
`ThreadLocal` for two-way or per-thread caches on platform pools. Logging MDC is `ThreadLocal`-based:
set it at task start and clear it in `finally`.

## 6. CompletableFuture

| Rule | Code |
|---|---|
| always pass an executor (default is the common pool, or a new thread per task when parallelism < 2) | `supplyAsync(() -> fetch(id), ioExecutor)`, `thenApplyAsync(fn, executor)` |
| bound waiting | `orTimeout(2, SECONDS)` fails with `TimeoutException`; `completeOnTimeout(fallback, 2, SECONDS)` |
| handle failures once, at the end of the chain | `handle((v, ex) -> ex == null ? v : fallback(ex))`; `exceptionally` for the error path only |
| unwrap | `join()` throws `CompletionException`, `get()` throws `ExecutionException`: use `getCause()` |
| never block inside a pooled task | no `join()`/`get()` in tasks on the common pool or on a bounded pool the awaited task also needs |
| combine | `allOf(cfs).thenApply(v -> cfs.stream().map(CompletableFuture::join).toList())` |

Stages after `orTimeout` may run on the JDK's internal delay-scheduler thread: use the `*Async`
variants with your executor for real work. With virtual threads, plain blocking code in a
virtual thread is usually clearer than a `CompletableFuture` chain.

## 7. java.util.concurrent toolbox

| Need | Tool | Rule |
|---|---|---|
| atomic per-key update | `ConcurrentHashMap.compute`, `merge`, `computeIfAbsent` | function runs under the bin lock: short, no I/O, never touches the same map (`IllegalStateException: Recursive update`) |
| hot counters | `LongAdder` (`map.computeIfAbsent(k, key -> new LongAdder()).increment()`) | `AtomicLong` when contention is low or you need CAS |
| lock with timeout, fairness, conditions | `ReentrantLock.tryLock(50, MILLISECONDS)`, `Condition` | always `unlock()` in `finally` |
| read-mostly data | `ReentrantReadWriteLock`; `StampedLock` optimistic reads for tiny sections | `StampedLock` is not reentrant |
| concurrency cap | `Semaphore`, `tryAcquire(timeout)` | release in `finally` only if acquired |
| one-shot gate | `CountDownLatch` | cannot be reset |
| repeated phases, dynamic parties | `Phaser` (`register`, `arriveAndAwaitAdvance`, `arriveAndDeregister`); `CyclicBarrier` for fixed parties | |
| hand-off between producer and consumer | see queue table | |

| Queue | Bounded | Use |
|---|---|---|
| `ArrayBlockingQueue` | yes (fixed array) | default producer/consumer with back-pressure |
| `LinkedBlockingQueue` | optional (default `Integer.MAX_VALUE`) | always pass a capacity |
| `SynchronousQueue` | zero capacity | direct hand-off |
| `LinkedTransferQueue` | no | producers that may wait for a consumer (`transfer`) |
| `PriorityBlockingQueue`, `DelayQueue` | no | ordering by priority or delay |

## 8. Java Memory Model essentials

Happens-before edges: unlock -> later lock of the same monitor or `Lock`; `volatile` write -> later
read of that variable; `Thread.start()` -> actions of the started thread; thread's actions ->
`join()` return; task submission -> task execution; task completion -> `Future.get()` return;
end of a constructor -> any thread seeing `final` fields of a safely obtained reference.

- `volatile` gives visibility and ordering for one variable, not atomic compound actions
  (`count++` on a volatile still loses updates: use `AtomicInteger`/`LongAdder`).
- Safe publication: `final` fields, a `volatile` or `AtomicReference` field, a static
  initializer, a concurrent collection, or a lock on both sides. Do not let `this` escape the
  constructor (javac `-Xlint:this-escape`, since 21).
- Records with final fields of immutable types are safe to share once constructed.
- `VarHandle` acquire/release/opaque modes only in measured lock-free code.
- Lazy constants without hand-written double-checked locking: holder idiom below, or the
  preview `StableValue` (25) / `LazyConstant` (26+) API where preview is acceptable.

```java
private volatile Config config;                     // double-checked locking needs volatile
Config config() {
    Config c = config;
    if (c == null) {
        synchronized (this) {
            c = config;
            if (c == null) config = c = Config.load();
        }
    }
    return c;
}
private static final class Holder { static final Registry INSTANCE = new Registry(); }   // lazy holder idiom
static Registry registry() { return Holder.INSTANCE; }
```

## 9. Diagnostics

```bash
jcmd <pid> Thread.dump_to_file -format=json /tmp/threads.json     # includes virtual threads
jq -r '[.threadDump.threadContainers[].threads[] | select(.virtual == true) | .state]
       | group_by(.) | map("\(.[0]) \(length)") | .[]' /tmp/threads.json
jq -r '.threadDump.threadContainers[].threads[] | select(.virtual == true)
       | .stack[0:4] | join(" <- ")' /tmp/threads.json | sort | uniq -c | sort -rn | head
# JDK 21-24 dumps carry only tid, name, stack: select(.stack[-1] // "" | test("VirtualThread.run"))
jcmd <pid> Thread.print -l                    # platform threads, j.u.c. lock owners, deadlock report
jcmd <pid> JFR.start settings=profile duration=2m filename=/tmp/c.jfr
jfr view contention-by-site /tmp/c.jfr        # jdk.JavaMonitorEnter (profile threshold 10 ms)
jfr view latencies-by-type /tmp/c.jfr         # park, monitor wait, socket and file I/O
```

`Thread.print` and `ThreadMXBean.findDeadlockedThreads()` cover platform threads only; a cycle
of virtual threads is visible only in the JSON dump (25+: per-thread `state`, `blockedOn`,
`parkBlocker`, `carrier`; earlier JDKs: compare stacks).
JFR `jdk.ThreadPark` shows `ReentrantLock`/queue waits; `jdk.VirtualThreadSubmitFailed`
signals the scheduler could not start or unpark a virtual thread.

## 10. Testing concurrent code

- Memory-model properties of lock-free code: jcstress (`@JCStressTest`, `@Actor`, `@Outcome`),
  run with `java -jar target/jcstress.jar -t <Test>`; see [jcstress recipes](references/jcstress-recipes.md).
- Async assertions: Awaitility `await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> ...)`,
  never `Thread.sleep` followed by an assert.
- Deterministic unit tests: inject `Executor` and `Clock`; use `Runnable::run` (same thread)
  or a queue-backed executor stepped by the test; assert concurrency limits with a high-water mark.
- Stress: `@RepeatedTest(500)` on many cores; thread-leak check by comparing live threads
  before and after.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| downstream overwhelmed, DB pool timeouts after migration | concurrency now equals load | `Semaphore` or pool sizing per downstream |
| throughput flat, carriers busy | CPU-bound work on virtual threads, or pinning | platform pool for CPU work; JFR pinned-threads |
| heap growth with many virtual threads | large `ThreadLocal` values, deep stacks retained | `ScopedValue`, pass context explicitly, keep stacks shallow |
| shutdown hangs, interrupts lost | `InterruptedException` swallowed | re-interrupt or propagate; Error Prone `InterruptedExceptionSwallowed` (experimental: enable it) |
| pool starvation or deadlock | tasks block on futures of the same bounded pool; I/O in `parallelStream` | separate pools, virtual threads, no blocking on the common pool |
| work silently on the common pool | `CompletableFuture.*Async` without executor | pass an executor |
| exceptions vanish | `CompletableFuture` chain never joined and without `handle`/`exceptionally` | attach handling or join at the end of every chain |
| memory leak or stale context on pooled threads | `ThreadLocal` set but never removed | `remove()` in `finally`, or `ScopedValue` |
| thread explosion under load | `newCachedThreadPool` | bounded pool, or virtual threads + semaphore |
| JVM does not exit, thread leak | `ExecutorService` never shut down | try-with-resources (`AutoCloseable` since 19) |
| lost updates | check-then-act on `ConcurrentHashMap` | `merge`, `compute`, `putIfAbsent` |
| corrupted state under concurrency | `SimpleDateFormat`, `HashMap`, `ArrayList` shared | `DateTimeFormatter`, concurrent collections, confinement |
| `StructuredTaskScope` code stops compiling after a JDK upgrade | preview API changed (25 -> 26 -> 27) | pin the JDK; read [structured concurrency by JDK](references/structured-concurrency-versions.md) |

Review checklist: no shared mutable state without a lock, atomic or confinement; virtual
threads never pooled; every downstream bounded (semaphore or pool) and every remote call timed
out; `InterruptedException` propagated or re-asserted; executors closed; no blocking on the
common pool or inside `synchronized` on 21-23.

## 12. Worked example: 200-thread pool -> virtual threads + Semaphore(64) -> structured scope

Before: each pricing request fans out to ~40 vendors on a shared fixed pool of 200 platform
threads; unbounded queue, no timeouts, failures and interrupts swallowed.

```java
private final ExecutorService pool = Executors.newFixedThreadPool(200);

List<Quote> fetchQuotes(List<Vendor> vendors) {
    List<Future<Quote>> fs = vendors.stream().map(v -> pool.submit(() -> client.quote(v))).toList();
    List<Quote> quotes = new ArrayList<>();
    for (Future<Quote> f : fs) {
        try { quotes.add(f.get()); } catch (Exception e) { /* ignored */ }
    }
    return quotes;
}
```

Sizing: the vendor gateway allows 64 concurrent connections from us; mean call time 80 ms, so
the ceiling is 64 / 0.08 s = 800 calls/s, i.e. 20 pricing requests/s at 40 vendors each.
Beyond that requests must queue (fast) or be shed, not pile up as hung threads.

Step 1 (Java 21+, no preview): virtual thread per call, global permit, per-call timeouts.

```java
private static final Semaphore VENDOR_PERMITS = new Semaphore(64);   // gateway's concurrency limit
private static final Duration CALL_TIMEOUT = Duration.ofSeconds(2);

List<Quote> fetchQuotes(List<Vendor> vendors) throws InterruptedException {
    try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
        List<Future<Quote>> futures = new ArrayList<>(vendors.size());
        for (Vendor v : vendors) futures.add(executor.submit(() -> quoteWithPermit(v)));
        List<Quote> quotes = new ArrayList<>(futures.size());
        for (Future<Quote> f : futures) {
            try {
                quotes.add(f.get());                                  // InterruptedException propagates
            } catch (ExecutionException e) {
                log.warn("quote failed", e.getCause());               // partial results are acceptable
            }
        }
        return quotes;
    }
}

private Quote quoteWithPermit(Vendor v) throws Exception {
    if (!VENDOR_PERMITS.tryAcquire(500, TimeUnit.MILLISECONDS))       // waiting counts against the budget
        throw new TimeoutException("no vendor permit within 500 ms");
    try {
        return client.quote(v, CALL_TIMEOUT);                         // HttpRequest.newBuilder(uri).timeout(t)
    } finally {
        VENDOR_PERMITS.release();
    }
}
```

Test the limit deterministically: a fake client increments an `AtomicInteger`, records the
peak with `peak.accumulateAndGet(now, Math::max)`, sleeps 10 ms, decrements; call
`fetchQuotes` with 1,000 vendors and assert `quotes` has 1,000 entries and `peak.get() <= 64`.

Step 2 (JDK 25, `--enable-preview`): the same shape as a structured scope, so cancellation and
the overall deadline are explicit and a thread dump shows the subtasks under their owner.

```java
List<Quote> fetchQuotes(List<Vendor> vendors) throws InterruptedException {
    try (var scope = StructuredTaskScope.open(
            Joiner.<Quote>awaitAll(),                                 // collect successes, never cancel on failure
            cf -> cf.withTimeout(Duration.ofSeconds(3)).withName("vendor-quotes"))) {
        List<Subtask<Quote>> tasks = vendors.stream()
            .map(v -> scope.fork(() -> quoteWithPermit(v)))
            .toList();
        scope.join();                                                 // TimeoutException after 3 s fails the call
        return tasks.stream()
            .filter(t -> t.state() == Subtask.State.SUCCESS)
            .map(Subtask::get)
            .toList();
    }
}
```

Per-call limits (0.5 s permit wait + 2 s call) keep the 3 s scope deadline a backstop. On JDK 26
a custom joiner can return partial results on timeout (`Joiner.onTimeout()`); on 27 replace
`awaitAll()` and expect `ExecutionException`: see [structured concurrency by JDK](references/structured-concurrency-versions.md).
Verify after deploy: `jcmd <pid> Thread.dump_to_file -format=json` shows the `vendor-quotes`
container, JFR shows no `jdk.VirtualThreadPinned`, and the gateway's concurrent-connection
metric never exceeds 64.

Related: `java-modern-language`, `java-jvm-tuning-jfr`, `java-spring-boot`, `java-testing-junit`,
`java-build-maven-gradle`, hub `java-craft`.
