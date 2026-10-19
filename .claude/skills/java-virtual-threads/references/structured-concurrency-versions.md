# Structured concurrency by JDK release

`StructuredTaskScope` (package `java.util.concurrent`) is a preview API in every release so far.
Preview class files run only on the feature release that compiled them, so pin the JDK in the
toolchain, CI image and runtime image together, and re-read the Javadoc on every upgrade.

| JDK | JEP | Shape |
|---|---|---|
| 21-24 | 453, 462, 480, 499 | `new StructuredTaskScope.ShutdownOnFailure()` / `ShutdownOnSuccess<T>()`, `join().throwIfFailed()`, `joinUntil(Instant)` |
| 25 | 505 | `StructuredTaskScope.open(...)` factories, `Joiner` policies, `Configuration` (name, thread factory, timeout); `FailedException`, `TimeoutException` |
| 26 | 525 | `allSuccessfulOrThrow()` returns `List<T>`; `anySuccessfulResultOrThrow()` renamed `anySuccessfulOrThrow()`; `Joiner.onTimeout()` added; `open(Joiner, UnaryOperator<Configuration>)` |
| 27 | 533 | third type parameter `R_X` (exception thrown by `join`); default joiners throw `ExecutionException`; `Function<Throwable, R_X>` overloads; `open(UnaryOperator)`; `awaitAll()` removed; `Joiner.timeout()` replaces `onTimeout()` |

## Build flags

```xml
<!-- maven-compiler-plugin -->
<configuration>
  <release>25</release>
  <compilerArgs><arg>--enable-preview</arg></compilerArgs>
</configuration>
<!-- maven-surefire-plugin / failsafe -->
<configuration><argLine>--enable-preview</argLine></configuration>
```

```kotlin
tasks.withType<JavaCompile>().configureEach { options.compilerArgs.add("--enable-preview") }
tasks.withType<Test>().configureEach { jvmArgs("--enable-preview") }
tasks.withType<JavaExec>().configureEach { jvmArgs("--enable-preview") }
```

Runtime: `java --enable-preview -jar app.jar` (or `JDK_JAVA_OPTIONS=--enable-preview`).

## JDK 21-24 (old API, does not compile on 25)

```java
try (var scope = new StructuredTaskScope.ShutdownOnFailure()) {
    Subtask<User> user = scope.fork(() -> users.find(id));
    Subtask<List<Order>> orders = scope.fork(() -> orderClient.recent(id));
    scope.join().throwIfFailed();                 // ExecutionException with the first failure
    return new Dashboard(user.get(), orders.get());
}
```

## JDK 25

| Factory | Scope type |
|---|---|
| `open()` | `StructuredTaskScope<T, Void>`; all must succeed; first failure cancels; `join()` returns `null` |
| `open(Joiner<? super T, ? extends R>)` | `StructuredTaskScope<T, R>` |
| `open(Joiner, Function<Configuration, Configuration>)` | same, configured: `withName(String)`, `withThreadFactory(ThreadFactory)`, `withTimeout(Duration)` |

| `join()` throws | When |
|---|---|
| `StructuredTaskScope.FailedException` | the joiner's `result()` threw (cause = subtask exception) |
| `StructuredTaskScope.TimeoutException` | the configured timeout expired before or during `join()`; the scope is cancelled |
| `InterruptedException` | the owner was interrupted while waiting |
| `WrongThreadException`, `IllegalStateException` | not the owner; already joined or closed |

`fork` throws `StructureViolationException` when the current scoped-value bindings differ from
those at `open`; `close()` throws `IllegalStateException` if the owner forked but never joined.

Custom joiner (25 signatures; 26+ use `Subtask<T>` without the wildcard):

```java
final class Collecting<T> implements Joiner<T, List<T>> {
    private final Queue<T> results = new ConcurrentLinkedQueue<>();
    @Override public boolean onComplete(Subtask<? extends T> s) {   // called concurrently: thread-safe
        if (s.state() == Subtask.State.SUCCESS) results.add(s.get());
        return false;                                               // true would cancel the scope
    }
    @Override public List<T> result() { return List.copyOf(results); }
}
```

## JDK 26: partial results on timeout

`Joiner.onTimeout()` is called by `join()` when the timeout expires; the default throws
`TimeoutException`. An override that returns normally makes `join()` call `result()`:

```java
final class PartialOnTimeout<T> implements Joiner<T, List<T>> {
    private final Queue<T> results = new ConcurrentLinkedQueue<>();
    @Override public boolean onComplete(Subtask<T> s) {
        if (s.state() == Subtask.State.SUCCESS) results.add(s.get());
        return false;
    }
    @Override public void onTimeout() { }                            // keep what finished in time
    @Override public List<T> result() { return List.copyOf(results); }
}
```

## JDK 27

| Joiner | Subtask fails | Timeout |
|---|---|---|
| `allSuccessfulOrThrow()` -> `List<T>` | `ExecutionException` (cause = first failure) | `ExecutionException` (cause = `CancelledByTimeoutException`) |
| `anySuccessfulOrThrow()` -> `T` | `ExecutionException` only if all fail | same as above |
| `awaitAllSuccessfulOrThrow()` -> `null` | `ExecutionException` | same as above |
| `allUntil(predicate)` -> `List<Subtask<T>>` | does not throw | does not throw; unfinished subtasks are `UNAVAILABLE` |
| `...(Function<Throwable, R_X> esf)` overloads | throws `esf.apply(cause)` | same |

So on 27 the worked example's "collect successes, keep a deadline" becomes
`StructuredTaskScope.open(Joiner.<Quote>allUntil(t -> false), cf -> cf.withTimeout(...))` and
filtering the returned subtasks for `State.SUCCESS`.

## Without preview features

```java
try (var ex = Executors.newVirtualThreadPerTaskExecutor()) {
    List<Callable<Quote>> calls = vendors.stream().<Callable<Quote>>map(v -> () -> quoteWithPermit(v)).toList();
    List<Future<Quote>> done = ex.invokeAll(calls, 3, TimeUnit.SECONDS);   // unfinished ones are cancelled
    List<Quote> quotes = new ArrayList<>();
    for (Future<Quote> f : done) {
        if (f.state() == Future.State.SUCCESS) quotes.add(f.resultNow());   // Future.state/resultNow: 19+
    }
    return quotes;
}
```

`invokeAny(calls, timeout, unit)` returns the first successful result and cancels the rest.
Neither gives the parent-child relationship in thread dumps or scoped-value inheritance.
