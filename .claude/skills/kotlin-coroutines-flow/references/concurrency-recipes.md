# Coroutine concurrency recipes

Companion to `kotlin-coroutines-flow` (kotlinx.coroutines 1.11). Every recipe takes its dispatcher and
scope as parameters so tests can pass `StandardTestDispatcher(testScheduler)`.

## 1. Owned scopes per environment

```kotlin
// Plain JVM service: one root scope, cancelled with a deadline on shutdown
val appScope = CoroutineScope(
    SupervisorJob() + Dispatchers.Default + CoroutineName("app") +
        CoroutineExceptionHandler { _, e -> log.error("uncaught coroutine failure", e) },
)
Runtime.getRuntime().addShutdownHook(Thread {
    runBlocking { withTimeoutOrNull(10.seconds) { appScope.coroutineContext.job.cancelAndJoin() } }
})
```

| Environment | Owner | Cancel on |
|---|---|---|
| Spring bean | `private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)` | `@PreDestroy fun stop() = scope.cancel()` |
| Ktor | `Application` is itself a `CoroutineScope` | server stop (automatic) |
| Android app-wide work | a DI-provided `@ApplicationScope CoroutineScope` | process death |
| Android screen work | `viewModelScope`, `lifecycleScope` | ViewModel cleared, lifecycle destroyed |

Work that must finish even if the caller leaves (saving a draft after the screen closes) runs in the
external scope and is still awaited by the caller:

```kotlin
class DraftRepository(private val externalScope: CoroutineScope, private val io: CoroutineDispatcher) {
    suspend fun save(draft: Draft) {
        externalScope.launch(io) { store.write(draft) }.join()   // survives the ViewModel's cancellation
    }
}
```

## 2. Bridges

| Source | Kotlin side | Module |
|---|---|---|
| one-shot callback | `suspendCancellableCoroutine { cont -> ...; cont.invokeOnCancellation { cancel() } }` | core |
| listener emitting many values | `callbackFlow { trySend(v); awaitClose { unregister() } }` | core |
| `CompletableFuture` / `CompletionStage` | `await()` (cancels the future) or `asDeferred().await()` | core (`kotlinx.coroutines.future`) |
| Guava `ListenableFuture` | `await()` | kotlinx-coroutines-guava |
| Reactor `Mono` / `Flux` | `awaitSingle()`, `awaitSingleOrNull()` / `asFlow()` | kotlinx-coroutines-reactor, -reactive |
| RxJava 3 `Single` / `Observable` | `await()` / `asFlow()` | kotlinx-coroutines-rx3 |
| blocking call | `runInterruptible(Dispatchers.IO) { legacy.call() }` | core |
| `ExecutorService` | `executor.asCoroutineDispatcher()` (close it, or close the executor) | core |

Resume exactly once: `suspendCancellableCoroutine` throws `IllegalStateException` on a second resume, so
listeners that may fire twice must check `cont.isActive` or unregister on the first call.

## 3. Confinement: one coroutine owns the state

```kotlin
class Counter(scope: CoroutineScope) {
    private sealed interface Cmd
    private data object Inc : Cmd
    private class Get(val reply: CompletableDeferred<Long>) : Cmd

    private val inbox = Channel<Cmd>(Channel.UNLIMITED)
    init {
        scope.launch {
            var value = 0L                                     // touched only by this coroutine
            for (cmd in inbox) when (cmd) {
                Inc -> value++
                is Get -> cmd.reply.complete(value)
            }
        }
    }
    fun increment() { inbox.trySend(Inc) }
    suspend fun get(): Long = CompletableDeferred<Long>().also { inbox.send(Get(it)) }.await()
}
```

Prefer `MutableStateFlow.update { }` for simple values and `Mutex.withLock { }` for short critical
sections; the inbox pattern pays off when commands interleave with suspending work.

## 4. Bounded fan-out

```kotlin
// Ordered results, at most 8 calls in flight
suspend fun <T, R> List<T>.mapBounded(limit: Int, f: suspend (T) -> R): List<R> = coroutineScope {
    val permits = Semaphore(limit)
    map { item -> async { permits.withPermit { f(item) } } }.awaitAll()
}

// Worker pool with backpressure: producers suspend when the queue is full
suspend fun processAll(tasks: List<Task>, workers: Int = 4) = coroutineScope {
    val queue = Channel<Task>(capacity = 100)
    repeat(workers) { launch { for (task in queue) handle(task) } }
    tasks.forEach { queue.send(it) }
    queue.close()                                              // workers drain and exit; coroutineScope waits
}
```

`flatMapMerge(concurrency = n)` is the streaming form (unordered); `chunked(n)` plus one `async` per chunk
batches requests against APIs that accept lists.

## 5. Retry with exponential backoff and jitter

```kotlin
suspend fun <T> retrying(
    times: Int = 3,
    initial: Duration = 200.milliseconds,
    max: Duration = 5.seconds,
    random: Random = Random.Default,                           // inject a seeded Random in tests
    retryOn: (Throwable) -> Boolean = { it is IOException },
    block: suspend () -> T,
): T {
    var backoff = initial
    repeat(times - 1) {
        try { return block() }
        catch (e: CancellationException) { throw e }
        catch (e: Throwable) { if (!retryOn(e)) throw e }
        delay(backoff * random.nextDouble(0.5, 1.0))           // jitter spreads synchronized retries
        backoff = (backoff * 2).coerceAtMost(max)
    }
    return block()
}
```

Without jitter the sleeps are 200 ms and 400 ms (600 ms of virtual time in `runTest`); with jitter assert
a range or pass `Random(42)`. Retry only idempotent operations; pair retries with a per-attempt
`withTimeout` and an overall deadline.

## 6. Timeouts

| Need | Use |
|---|---|
| give up and continue | `withTimeoutOrNull(2.seconds) { call() } ?: fallback` |
| fail the operation | `withTimeout(2.seconds) { }` and catch `TimeoutCancellationException` where it is meaningful |
| deadline across several calls | one `withTimeout` around the whole sequence |
| blocking call | `withTimeout` cannot interrupt it: `runInterruptible` inside, or the client's own timeout |

## 7. Shutdown checklist

- [ ] Every owned scope is cancelled (`scope.cancel()`), and `cancelAndJoin()` waits with a deadline.
- [ ] Dispatchers from `asCoroutineDispatcher()`/`newSingleThreadContext` are closed.
- [ ] Channels are closed by their producers; consumers use `for (x in channel)`.
- [ ] `stateIn(..., Eagerly)` and `shareIn` upstreams live in a scope that is cancelled.
- [ ] Cleanup that suspends runs inside `withContext(NonCancellable)`.
