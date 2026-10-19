# Kotlin coroutines and Flow in production

kotlinx.coroutines 1.10.x semantics. Verify newer APIs against the version in the project.

## 1. Scopes and ownership

| Context | Scope | Cancelled when |
|---|---|---|
| Android ViewModel | `viewModelScope` | ViewModel cleared |
| Android UI | `lifecycleScope` + `repeatOnLifecycle(Lifecycle.State.STARTED) { }` | lifecycle destroyed (collection paused below STARTED) |
| Ktor server request | the handler's coroutine (`call` scope) | request completes or client disconnects |
| Spring WebFlux / MVC suspend handlers | request coroutine | request ends |
| background service component | `CoroutineScope(SupervisorJob() + Dispatchers.Default + CoroutineName("indexer"))` | your `close()`/shutdown hook calls `scope.cancel()` |
| one-shot parallel work inside a suspend function | `coroutineScope { }` / `supervisorScope { }` | block exits |
| tests | `runTest { }` (+ `backgroundScope` for never-ending collectors) | test ends |

`GlobalScope` and `runBlocking` inside suspend code are review blockers. `runBlocking` is for
`main` functions, tests on old setups, and bridging blocking APIs at the outermost edge.

## 2. Exception propagation

| Builder | Exception goes to | Notes |
|---|---|---|
| `launch` in a regular `Job` scope | parent; cancels siblings and parent | root `launch` reports to `CoroutineExceptionHandler` |
| `launch` in `SupervisorJob`/`supervisorScope` | its own handler only | siblings unaffected |
| `async` | stored until `await()`; also cancels parent in a regular scope | in `coroutineScope`, the failure propagates even if you never call `await` |
| `coroutineScope { }` | rethrown to the caller after cancelling children | |
| `supervisorScope { }` | child failures do not cancel siblings; handle each | |

```kotlin
suspend fun loadDashboard(id: UserId): Dashboard = coroutineScope {
    val user = async { userRepo.get(id) }
    val orders = async { orderRepo.recent(id) }
    Dashboard(user.await(), orders.await())          // either failure cancels the other and propagates
}

suspend fun refreshAll(sources: List<Source>) = supervisorScope {
    sources.forEach { s ->
        launch {
            try { s.refresh() }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { log.warn("refresh ${s.name} failed", e) }   // one failure does not stop others
        }
    }
}
```

Safe `runCatching` for suspend code:

```kotlin
suspend inline fun <T> suspendRunCatching(block: () -> T): Result<T> =
    try { Result.success(block()) }
    catch (e: CancellationException) { throw e }
    catch (e: Throwable) { Result.failure(e) }
```

## 3. Cancellation mechanics

- Cancellation is cooperative: suspending functions from kotlinx.coroutines check it; your CPU
  loops must call `ensureActive()` or `yield()`.
- Blocking calls (JDBC, `Thread.sleep`, file I/O) are not interrupted by cancellation; use
  `runInterruptible(Dispatchers.IO) { blockingCall() }` to translate cancellation into thread
  interruption where the API honours interrupts.
- After cancellation, any suspend call in `finally` throws immediately: wrap required suspending
  cleanup in `withContext(NonCancellable) { }`.
- `Job.cancelAndJoin()` to wait until a cancelled job has finished its cleanup.
- `withTimeout(d) { }` throws `TimeoutCancellationException`; `withTimeoutOrNull` returns null.
  Resources acquired inside a timed-out block must be released in `finally` (the result of a
  completed block can be lost if the timeout fires just after it).

## 4. Dispatchers

| Dispatcher | Threads | Use |
|---|---|---|
| `Dispatchers.Default` | cores (min 2) | CPU work |
| `Dispatchers.IO` | 64 or cores (elastic, shares threads with Default) | blocking I/O |
| `Dispatchers.IO.limitedParallelism(n)` | view with at most n concurrent | bound access to a DB pool or legacy blocking client |
| `Dispatchers.Main` / `Main.immediate` | UI thread | UI updates; `immediate` avoids redispatch when already on Main |
| `Dispatchers.Unconfined` | caller thread until first suspension | tests and special operators only |
| `newSingleThreadContext` / `Executor.asCoroutineDispatcher()` | own threads | must be closed |

Inject dispatchers rather than hard-coding them:

```kotlin
class Repo(private val io: CoroutineDispatcher = Dispatchers.IO) {
    suspend fun load(id: String): Item = withContext(io) { dao.load(id) }
}
```

## 5. Shared mutable state

| Need | Tool |
|---|---|
| state holder observed by UI | `MutableStateFlow` with `update { it.copy(...) }` (atomic CAS loop) |
| mutual exclusion around suspending sections | `kotlinx.coroutines.sync.Mutex` (`withLock`), not reentrant |
| limit concurrency | `Semaphore(n)` with `withPermit` |
| confinement | all access on one single-threaded dispatcher (`limitedParallelism(1)`) |
| counters | `AtomicLong` / `atomicfu` (KMP) |
| actor-like serialization | a `Channel` consumed by one coroutine |

Never hold a `java.util.concurrent` lock or `synchronized` block across a suspension point.

## 6. Flow building blocks

Cold flow with retry and backoff:

```kotlin
fun prices(symbol: String): Flow<Price> = flow {
    while (true) {
        emit(api.price(symbol))
        delay(1_000)
    }
}.retryWhen { cause, attempt ->
    if (cause is IOException && attempt < 5) { delay(200L shl attempt.toInt()); true } else false
}.flowOn(Dispatchers.IO)
```

State for UI:

```kotlin
class QuoteViewModel(repo: QuoteRepo) : ViewModel() {
    private val query = MutableStateFlow("")
    val results: StateFlow<UiState> = query
        .debounce(300)
        .distinctUntilChanged()
        .flatMapLatest { q -> if (q.isBlank()) flowOf(UiState.Empty) else repo.search(q).map(UiState::Results) }
        .catch { emit(UiState.Error(it)) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), UiState.Empty)
    fun onQuery(q: String) { query.value = q }
}
```

`WhileSubscribed(5_000)` keeps the upstream alive 5 s after the last subscriber leaves (survives
configuration changes without restarting work); `Eagerly`/`Lazily` keep it until the scope ends.

Operator cheat-sheet:

| Goal | Operator |
|---|---|
| combine latest of several | `combine(a, b) { x, y -> }` |
| pairwise in lockstep | `zip` |
| switch to the newest inner flow | `flatMapLatest` |
| bounded concurrent inner flows | `flatMapMerge(concurrency = 4)` |
| sequential inner flows | `flatMapConcat` |
| drop intermediate values when slow | `conflate()` or `collectLatest` |
| decouple producer from consumer | `buffer(capacity, onBufferOverflow)` |
| rate limit / batching | `debounce`, `sample`, `chunked(n)` (1.9+ experimental: check) |
| side effects | `onEach`, `onStart`, `onCompletion` |
| errors | `catch` (upstream only), `retry`, `retryWhen` |

## 7. SharedFlow configuration

```kotlin
private val _events = MutableSharedFlow<Event>(
    replay = 0, extraBufferCapacity = 64, onBufferOverflow = BufferOverflow.DROP_OLDEST)
val events: SharedFlow<Event> = _events.asSharedFlow()
fun publish(e: Event) { _events.tryEmit(e) }    // with replay=0 and no buffer, tryEmit always fails
```

`replay = 1` approximates `StateFlow` without equality conflation. Subscribers that arrive late
miss events with `replay = 0`: use a `Channel` (single consumer) when every event must be
delivered exactly once.

## 8. Testing coroutines and flows

```kotlin
class RepoTest {
    @Test fun `retries then succeeds`() = runTest {          // virtual time: delays skip instantly
        val api = FakeApi(failures = 2)
        val repo = Repo(api, io = StandardTestDispatcher(testScheduler))
        val result = repo.loadWithRetry("x")
        assertEquals("x", result.id)
        assertEquals(3, api.calls)
        assertEquals(600, currentTime)                       // 200 + 400 ms of virtual backoff
    }

    @Test fun `search emits results`() = runTest {
        val vm = QuoteViewModel(FakeRepo())
        vm.results.test {                                    // Turbine
            assertEquals(UiState.Empty, awaitItem())
            vm.onQuery("ab")
            advanceTimeBy(301)
            assertIs<UiState.Results>(awaitItem())
            cancelAndIgnoreRemainingEvents()
        }
    }
}
```

- All dispatchers in a test should share `testScheduler` (pass `StandardTestDispatcher(testScheduler)`).
- Android: `Dispatchers.setMain(StandardTestDispatcher())` in setup, `resetMain()` in teardown
  (a JUnit rule or Kotest extension).
- `UnconfinedTestDispatcher` for eager collection of hot flows; `backgroundScope.launch { flow.collect { } }`
  for collectors that never complete.
- `advanceUntilIdle()`, `advanceTimeBy(ms)`, `runCurrent()` control virtual time.
- `kotlinx-coroutines-debug` `DebugProbes.install()` + `DebugProbes.dumpCoroutines()` to find
  leaked or stuck coroutines in integration tests.
