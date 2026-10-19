---
name: kotlin-coroutines-flow
description: "Kotlin coroutines and Flow under structured concurrency: scope ownership, exception propagation and SupervisorJob, cancellation hygiene, dispatchers, Mutex/Semaphore, callback bridging, cold flow vs StateFlow/SharedFlow/Channel, operator semantics, stateIn/shareIn and lifecycle-aware collection. Load when writing or debugging suspend code, flows, leaked jobs or swallowed cancellation."
when_to_use: "Code using launch/async/withContext, CoroutineScope, Flow, StateFlow, SharedFlow, Channel, callbackFlow or viewModelScope; symptoms such as work continuing after a screen closes, shutdown hangs, a job that silently stops, 'Flow invariant is violated', 'awaitClose { yourCallbackOrListener.cancel() } should be used in the end of callbackFlow block', UI not updating or missing events, duplicate network calls per collector, ANRs from runBlocking, thread-pool starvation."
---

# Kotlin coroutines and Flow

Baseline: kotlinx.coroutines 1.11.0 (May 2026; 1.10.x is still common), Kotlin 2.4.x. Several Flow
operators are opt-in: `debounce`/`sample` need `@OptIn(FlowPreview::class)`; `flatMapLatest`,
`flatMapMerge`, `flatMapConcat`, `mapLatest`, `transformLatest`, `chunked` need
`@OptIn(ExperimentalCoroutinesApi::class)`. Tests for everything here: `kotlin-testing`.

Deep material: [operator reference](references/operator-reference.md) (timing, fusion, sharing
parameters) | [concurrency recipes](references/concurrency-recipes.md) (app scopes, bridges, actors,
fan-out, retry, shutdown).

## 1. Scope ownership

Every coroutine belongs to a scope whose lifetime is owned by something that cancels it.

| Context | Scope | Cancelled when |
|---|---|---|
| Android ViewModel | `viewModelScope` (`Dispatchers.Main.immediate`) | ViewModel cleared |
| Android UI | `lifecycleScope` + `repeatOnLifecycle(STARTED)` | lifecycle destroyed; collection paused below STARTED |
| Ktor or Spring request | the handler's coroutine | request completes or client disconnects |
| long-lived component | `CoroutineScope(SupervisorJob() + Dispatchers.Default + CoroutineName("indexer"))` | its `close()`/shutdown hook calls `scope.cancel()` |
| parallel work inside a suspend fun | `coroutineScope { }` / `supervisorScope { }` | block exits |
| tests | `runTest { }`, `backgroundScope` for endless collectors | test ends |

```kotlin
class Indexer(private val docs: DocRepo, dispatcher: CoroutineDispatcher = Dispatchers.Default) : AutoCloseable {
    private val scope = CoroutineScope(SupervisorJob() + dispatcher + CoroutineName("indexer"))
    fun start() { scope.launch { docs.changes().collect { index(it) } } }
    override fun close() { scope.cancel() }          // Spring @PreDestroy, Ktor ApplicationStopped, shutdown hook
}
```

| | `coroutineScope { }` | `supervisorScope { }` |
|---|---|---|
| a child fails | siblings cancelled, exception rethrown to the caller | siblings keep running; the child's exception goes to its handler |
| use for | all-or-nothing decomposition (load user AND orders) | independent tasks (refresh N sources) |
| returns | after every child completes | same |

Review blockers: `GlobalScope` (nobody cancels it), `runBlocking` inside suspend code, and passing a `Job`
to a builder (`launch(Job())`, `launch(NonCancellable)`), which detaches the child from its parent;
kotlinx.coroutines 1.11 deprecates that for `launch`/`async`/`produce`. For work that must finish once
started use `launch(start = CoroutineStart.ATOMIC) { withContext(NonCancellable) { ... } }`. detekt's
coroutines rules (`GlobalCoroutineUsage`, `InjectDispatcher`, `SleepInsteadOfDelay`,
`SuspendFunSwallowedCancellation`, `SuspendFunWithFlowReturnType`) plus `TooGenericExceptionCaught` flag
most of these mechanically.

## 2. Exception propagation

| Builder | The exception goes to | `CoroutineExceptionHandler` | Notes |
|---|---|---|---|
| `launch`, child of a regular `Job` | parent, cancelling siblings and the parent up to the root | only the root's | |
| root `launch` (`scope.launch`) | handler in context, else the thread's uncaught handler (crash on Android) | yes | |
| `launch` directly in `supervisorScope` or a `SupervisorJob` scope | its own handler, like a root | yes | siblings unaffected |
| `async`, child of a regular `Job` | cancels the parent immediately and is rethrown by `await()` | never | in `coroutineScope` it propagates even if nobody awaits |
| `async` as root or in a supervisor | only `await()`; never awaited means silently lost | never | |
| `coroutineScope`, `withContext` | rethrown to the caller after children are cancelled | n/a | |
| `CancellationException` | normal completion of a cancelled coroutine | ignored | |

The first exception wins; later ones are attached as suppressed. A handler cannot recover the coroutine;
use it for logging and crash reporting at roots.

```kotlin
suspend fun loadDashboard(id: UserId): Dashboard = coroutineScope {
    val user = async { userRepo.get(id) }
    val orders = async { orderRepo.recent(id) }
    Dashboard(user.await(), orders.await())            // either failure cancels the other and propagates
}

suspend fun refreshAll(sources: List<Source>) = supervisorScope {
    sources.forEach { s ->
        launch {
            try { s.refresh() }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { log.warn("refresh ${s.name} failed", e) }   // one failure does not stop the rest
        }
    }
}
```

## 3. Cancellation hygiene

1. Cancellation is cooperative: kotlinx suspend functions check it; CPU loops call `ensureActive()`
   (`currentCoroutineContext().ensureActive()` in non-scope code) or `yield()` per batch.
2. Never swallow `CancellationException`. `catch (e: Exception)`, `catch (e: Throwable)` and `runCatching`
   all catch it: rethrow, or catch the specific types you handle.
3. Blocking calls (JDBC, `Thread.sleep`, file I/O) ignore cancellation: `runInterruptible(Dispatchers.IO) { }`
   turns cancellation into thread interruption for APIs that honour it.
4. After cancellation every suspend call in `finally` throws at once: wrap suspending cleanup in
   `withContext(NonCancellable) { }`. Wait for cleanup with `job.cancelAndJoin()`.
5. `withTimeout` throws `TimeoutCancellationException`, a `CancellationException`: uncaught inside `launch`
   it ends the coroutine silently. Prefer `withTimeoutOrNull` (returns null) or catch it explicitly. A value
   acquired inside the block can be lost if the timeout fires just after it completes: release in `finally`.

```kotlin
suspend inline fun <T> suspendRunCatching(block: () -> T): Result<T> =
    try { Result.success(block()) }
    catch (e: CancellationException) { throw e }
    catch (e: Throwable) { Result.failure(e) }

suspend fun upload(file: Path) {
    val session = storage.open()
    try { session.write(file) }
    finally { withContext(NonCancellable) { session.close() } }   // runs even when cancelled
}
```

## 4. Dispatchers and shared state

| Dispatcher | Threads | Use |
|---|---|---|
| `Dispatchers.Default` | number of cores (at least 2) | CPU work; never block on it |
| `Dispatchers.IO` | max(64, cores) (`kotlinx.coroutines.io.parallelism`); shares threads with Default | blocking I/O |
| `Dispatchers.IO.limitedParallelism(n, "db")` | view of at most n; IO views are elastic (not capped by the 64) | a DB pool or legacy blocking client |
| `Dispatchers.Main` / `Main.immediate` | UI thread | UI updates; `immediate` skips redispatch when already on Main |
| `Dispatchers.Unconfined` | caller thread until first suspension | special operators, never app code |
| `Executor.asCoroutineDispatcher()`, `newSingleThreadContext` | own threads | must be closed |

Main-safety: a suspend function that blocks switches context itself (`withContext(io) { dao.load(id) }`), so
callers on any dispatcher can call it. Inject dispatchers through constructors
(`class Repo(private val io: CoroutineDispatcher = Dispatchers.IO)`) so tests pass a test dispatcher.
`limitedParallelism` limits threads, not coroutines: a coroutine that suspends lets another start, so it is
not a mutex.

| Need | Tool |
|---|---|
| state observed by UI | `MutableStateFlow` + `update { it.copy(...) }` (atomic CAS loop; the lambda may run more than once) |
| mutual exclusion across suspension | `Mutex().withLock { }` (not reentrant: nested `withLock` deadlocks) |
| bound concurrency | `Semaphore(n).withPermit { }` |
| counters and flags | `AtomicLong`/`AtomicReference`; atomicfu or `kotlin.concurrent.atomics` (experimental) in common code |
| confinement | one coroutine owns the state and receives commands through a `Channel` (recipe in references) |
| serialise short sections | `limitedParallelism(1)` (sequential between suspensions only) |

Never hold `synchronized` or a `java.util.concurrent` lock across a suspension point.

## 5. Bridging and fan-out

```kotlin
suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    enqueue(object : Callback {
        override fun onResponse(call: Call, response: Response) =
            cont.resume(response) { _, value, _ -> value.close() }      // closed if the caller was cancelled
        override fun onFailure(call: Call, e: IOException) = cont.resumeWithException(e)
    })
    cont.invokeOnCancellation { cancel() }                                // cancel the HTTP call too
}
```

- Java futures: `future.await()` cancels the future when the coroutine is cancelled;
  `future.asDeferred().await()` does not. Exposing coroutines to Java: `kotlin-java-interop`.
- `runBlocking` belongs in `main`, tests and the outermost bridge from blocking code; on the Android main
  thread it freezes the UI and deadlocks if the inner code needs Main.

```kotlin
suspend fun fetchAll(ids: List<Id>, maxInFlight: Int = 8): List<Item> = coroutineScope {
    val permits = Semaphore(maxInFlight)
    ids.map { id -> async { permits.withPermit { api.fetch(id) } } }.awaitAll()   // ordered, 8 at a time
}
fun fetchStream(ids: Flow<Id>): Flow<Item> =
    ids.flatMapMerge(concurrency = 8) { id -> flow { emit(api.fetch(id)) } }       // unordered, streaming
```

`flatMapMerge` defaults to 16 concurrent inner flows. Unbounded `ids.map { async { } }` over thousands of
ids floods the downstream service.

## 6. Flow type choice: state versus events

| Need | Type |
|---|---|
| recomputed per collector (DB query, paging, polling) | cold `flow { emit(...) }` |
| screen state: always has a value, conflated, equality-deduplicated | `StateFlow` (`MutableStateFlow`, or `stateIn`) |
| broadcast to many subscribers, may be missed when nobody listens | `SharedFlow` (`MutableSharedFlow(replay, extraBufferCapacity, onBufferOverflow)`) |
| exactly-once events to one consumer (navigate, snackbar) | `Channel(Channel.BUFFERED)` exposed as `receiveAsFlow()` |

Model as much as possible as state (a `userMessage` field the UI clears through `onMessageShown()`); a
`StateFlow` drops repeated equal events and a `SharedFlow(replay = 0)` loses events emitted while the UI is
stopped. `receiveAsFlow()` fans out (each event reaches one collector); `consumeAsFlow()` may be collected
only once.

## 7. Operator semantics

| Operator | Semantics |
|---|---|
| `flowOn(ctx)` | changes the context of everything upstream only; the collector keeps its own |
| `catch { }` | handles upstream exceptions only, never downstream or cancellation; may `emit` a fallback |
| `onCompletion { cause -> }` | sees success (`null`), failure or cancellation, upstream or downstream; does not handle it |
| `retry(n) { }`, `retryWhen { cause, attempt -> }` | resubscribe upstream; `attempt` starts at 0 and is never reset by later successes; `delay` inside for backoff |
| `buffer(capacity, onBufferOverflow)` | producer runs in a separate coroutine ahead of the collector |
| `conflate()` | keep only the latest value while the collector is busy |
| `collectLatest { }`, `mapLatest`, `flatMapLatest` | cancel the previous block when a new value arrives |
| `debounce(ms)` | emit after `ms` of silence; `sample(ms)` emits the latest value every period |
| `combine(a, b) { }` | latest of each, once all have emitted; re-emits on any change |
| `zip(other) { }` | pairs in lockstep; ends when either ends |
| `merge(a, b)` | interleave as they come |
| `flatMapConcat` / `flatMapMerge(n)` / `flatMapLatest` | sequential / bounded concurrent, unordered / switch to newest |
| `distinctUntilChanged()` | drop consecutive equals (`StateFlow` already does this) |
| `onStart { }`, `onEach { }` | side effects before collection / per value; `onStart { emit(Loading) }` prepends a value |

Placement matters: `catch` must sit below the operator that throws; inside `flatMapLatest` it isolates
one inner flow, while at the end of the chain it completes the whole flow after the first error.

## 8. Sharing and callback APIs

```kotlin
val results: StateFlow<UiState> = repo.observe()
    .catch { emit(UiState.Error(it)) }                                    // an upstream failure must not reach the scope
    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), UiState.Loading)
```

| `SharingStarted` | Upstream runs | Use |
|---|---|---|
| `WhileSubscribed(5_000)` | from the first subscriber until 5 s after the last leaves | UI state: survives rotation without restarting work |
| `Eagerly` | from creation until the scope ends | must start before anyone collects |
| `Lazily` | from the first subscriber until the scope ends | expensive, keep once started |

- `shareIn(scope, started, replay)` for a `SharedFlow`; the suspending `stateIn(scope)` waits for the first value.
- `StateFlow` compares with `equals`: setting an equal value, or mutating the object held inside, notifies
  nobody. Emit new immutable copies: `_state.update { it.copy(loading = false) }`.
- `MutableSharedFlow()` with defaults (no replay, no extra buffer, `SUSPEND`): `tryEmit` returns false
  whenever a subscriber exists (the value is lost), and returns true but drops the value when none exists.
  Give it `extraBufferCapacity` and `BufferOverflow.DROP_OLDEST`, or call the suspending `emit`.
- An exception escaping `stateIn`/`shareIn` upstream goes to the scope (on `viewModelScope`, a crash); put
  `catch` before sharing.

```kotlin
fun locationUpdates(client: LocationClient, dispatcher: CoroutineDispatcher = Dispatchers.Default): Flow<Location> =
    callbackFlow {
        val listener = LocationListener { loc -> trySend(loc) }      // non-suspending, any thread; dropped if closed
        client.register(listener)
        awaitClose { client.unregister(listener) }                    // runs on cancellation or close
    }.buffer(Channel.CONFLATED)                                       // keep only the newest location
     .flowOn(dispatcher)
```

Test it with a fake client: `locationUpdates(fake, StandardTestDispatcher(testScheduler)).test { runCurrent();
fake.emit(a); assertEquals(a, awaitItem()); cancelAndIgnoreRemainingEvents() }` (`runCurrent()` lets `register`
run before the emit), then assert `fake.listenerCount == 0`: `test { }` returns only after `awaitClose` ran.

`callbackFlow` without `awaitClose` fails with "'awaitClose { yourCallbackOrListener.cancel() }' should be
used in the end of callbackFlow block". Use `channelFlow { }` when several coroutines must emit into one flow.
`flow { }` must emit from its own coroutine: `withContext` around `emit` fails with "Flow invariant is
violated: Flow was collected in ..., but emission happened in .... Please refer to 'flow' documentation or use
'flowOn' instead"; emitting from a launched child fails with "Emission from another coroutine is detected".

## 9. Android collection and debugging

```kotlin
lifecycleScope.launch {                                               // Fragment: viewLifecycleOwner.lifecycleScope
    repeatOnLifecycle(Lifecycle.State.STARTED) { vm.state.collect(::render) }   // stops below STARTED, restarts above
}
@Composable fun Screen(vm: SearchViewModel) {
    val state by vm.state.collectAsStateWithLifecycle()               // lifecycle-runtime-compose
}
```

`launchWhenStarted` and bare `lifecycleScope.launch { flow.collect { } }` keep upstream work alive in the
background; use the two forms above.

| Tool | How | Shows |
|---|---|---|
| debug mode | `-Dkotlinx.coroutines.debug` (on automatically with `-ea`, so in unit tests) | coroutine name and id in thread names, recovered stack traces |
| names | `CoroutineName("indexer")` in the context | readable dumps and logs |
| debug agent (JVM only) | `kotlinx-coroutines-debug`, `DebugProbes.install()` or `-javaagent:kotlinx-coroutines-debug-<v>.jar` (no warning on JDK 21+) | `DebugProbes.dumpCoroutines()`, `printJob(job)`; set `enableCreationStackTraces = false` outside tests |
| hung tests | `@CoroutinesTimeout(5_000)` (JUnit 5, kotlinx-coroutines-debug) | coroutine dump at timeout |
| IntelliJ | Debug tool window, Coroutines tab | running, suspended and created coroutines |
| "was optimized out" variables | compiler flag `-Xdebug` (debug builds only: it can leak memory) | locals in suspend functions |

The debug agent is not supported on Android. For deadlock or leak hunts with thread dumps hand over to the
`debugger` agent.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| work continues after the screen or request ends | `GlobalScope`, a custom scope nobody cancels, `launch(Job())` | lifecycle scopes; cancel owned scopes in `close()` |
| shutdown hangs, CPU spins after cancel | `catch (e: Exception)`/`runCatching` swallowing `CancellationException` in a loop | rethrow it; catch specific exceptions; `ensureActive()` |
| a job "silently" stops | uncaught `TimeoutCancellationException` from `withTimeout` in `launch` | `withTimeoutOrNull` or explicit catch |
| CPU pool starved, everything slow | blocking calls on `Dispatchers.Default` | `withContext(Dispatchers.IO)` / `runInterruptible` |
| ANR or deadlock | `runBlocking` on Main | suspend all the way; `viewModelScope.launch` |
| `Flow invariant is violated` | `withContext` around `emit`, or emit from another coroutine | `flowOn`, `channelFlow` |
| UI misses or replays events | one-shot events in `StateFlow`, or `SharedFlow(replay = 0)` with no subscriber | state with explicit consumption, or `Channel.receiveAsFlow()` |
| UI does not update | mutating the object inside `MutableStateFlow`, or emitting an equal value | new immutable copies via `update { it.copy(...) }` |
| two network calls per screen | several collectors of one cold flow | `stateIn`/`shareIn` once in the ViewModel |
| errors still kill the stream | `catch` placed above the throwing operator, or at the end where it completes the flow | move `catch` below the operator or inside `flatMapLatest` |

## 11. Worked example: leaky poller and a search box

Before: polls forever and cannot be stopped.

```kotlin
fun startPolling() {
    GlobalScope.launch {                                   // outlives the ViewModel; each call adds a poller
        while (true) {
            try { _price.value = api.latest(); delay(5_000) }
            catch (e: Exception) { Log.w("Prices", "poll failed", e) }   // swallows CancellationException
        }
    }
}
```

If that job is ever cancelled, `delay` and `api.latest()` throw immediately, the catch logs and the loop spins
at full speed. Fixed (minimal), then idiomatic (polls only while observed):

```kotlin
class PricesViewModel(private val api: PriceApi, private val pollEvery: Duration = 5.seconds) : ViewModel() {
    private val _price = MutableStateFlow<Price?>(null)
    val price: StateFlow<Price?> = _price.asStateFlow()
    private var poller: Job? = null

    fun startPolling() {
        if (poller?.isActive == true) return                         // idempotent
        poller = viewModelScope.launch {                             // cancelled in onCleared()
            while (isActive) {
                try { _price.value = api.latest() }
                catch (e: IOException) { Log.w("Prices", "poll failed", e) }   // cancellation passes through
                delay(pollEvery)
            }
        }
    }

    // idiomatic alternative: no start/stop calls, polls only while the UI observes
    val livePrice: StateFlow<PriceUi> = flow { while (true) { emit(PriceUi.Value(api.latest())); delay(pollEvery) } }
        .retryWhen { cause, attempt ->
            val retry = cause is IOException && attempt < 3
            if (retry) delay(1_000L shl attempt.toInt())             // 1 s, 2 s, 4 s
            retry
        }
        .catch { emit(PriceUi.Unavailable) }                         // without it the 4th failure crashes viewModelScope
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), PriceUi.Loading)
}

@OptIn(FlowPreview::class, ExperimentalCoroutinesApi::class)
class SearchViewModel(private val repo: SearchRepo) : ViewModel() {
    private val query = MutableStateFlow("")
    val state: StateFlow<SearchUi> = query
        .map { it.trim() }
        .debounce(300)                                               // 300 ms of quiet typing
        .distinctUntilChanged()                                      // same settled query is not searched twice
        .flatMapLatest { q ->                                        // a newer query cancels the running search
            if (q.length < 2) flowOf(SearchUi.Idle)
            else flow { emit(SearchUi.Loading(q)); emit(SearchUi.Results(q, repo.search(q))) }
                .catch { emit(SearchUi.Error(q, it.message ?: "search failed")) }   // inner: pipeline survives
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), SearchUi.Idle)
    fun onQueryChanged(text: String) { query.value = text }
}
```

Verified in virtual time (Main replaced by `StandardTestDispatcher()`, so `runTest` shares its scheduler;
`FakeSearchRepo` delays `latency`, records `queries`, counts `cancelled` in a `CancellationException` catch
and rethrows; `FakePriceApi` counts `calls`):

```kotlin
@get:Rule val main = MainDispatcherRule()

@Test fun `debounces typing and searches the settled query once`() = runTest {
    val repo = FakeSearchRepo(latency = 100.milliseconds)
    val vm = SearchViewModel(repo)
    vm.state.test {
        assertEquals(SearchUi.Idle, awaitItem())
        vm.onQueryChanged("ko"); advanceTimeBy(100)
        vm.onQueryChanged("kot"); vm.onQueryChanged("kotlin")
        assertEquals(SearchUi.Loading("kotlin"), awaitItem())                      // t = 100 + 300
        assertEquals(SearchUi.Results("kotlin", listOf("kotlinx.coroutines")), awaitItem())
        assertEquals(500, currentTime)                                             // + 100 ms latency
        assertEquals(listOf("kotlin"), repo.queries)                               // "ko", "kot" never searched
        cancelAndIgnoreRemainingEvents()
    }
}

@Test fun `a newer query cancels the running search`() = runTest {
    val repo = FakeSearchRepo(latency = 1.seconds)
    val vm = SearchViewModel(repo)
    vm.state.test {
        assertEquals(SearchUi.Idle, awaitItem())
        vm.onQueryChanged("kotlin")
        assertEquals(SearchUi.Loading("kotlin"), awaitItem())                      // t = 300
        advanceTimeBy(200); vm.onQueryChanged("kotlinx")
        assertEquals(SearchUi.Loading("kotlinx"), awaitItem())                     // t = 800
        assertEquals(SearchUi.Results("kotlinx", listOf("kotlinx.coroutines")), awaitItem())  // t = 1800
        assertEquals(1, repo.cancelled)
        cancelAndIgnoreRemainingEvents()
    }
}

@Test fun `poller stops with the scope`() = runTest {
    val api = FakePriceApi()
    val vm = PricesViewModel(api, pollEvery = 5.seconds)
    vm.startPolling(); vm.startPolling()                                           // second call is a no-op
    advanceTimeBy(12_000)
    assertEquals(3, api.calls)                                                     // t = 0, 5000, 10000
    vm.viewModelScope.cancel()                                                     // what onCleared() does
    advanceTimeBy(60_000)
    assertEquals(3, api.calls)
}
```

Cancel the poller before the test ends: `runTest` drains the shared scheduler at teardown, and an endless
`while`/`delay` loop on the replaced Main dispatcher would keep it busy forever.

Related: `kotlin-testing` (runTest, Turbine and Main-dispatcher mechanics), `kotlin-compose` (collecting state
in UI), `kotlin-java-interop` (futures for Java callers), `kotlin-multiplatform`, `resilience-patterns`,
`debugging-method`; hub `kotlin-craft`.
