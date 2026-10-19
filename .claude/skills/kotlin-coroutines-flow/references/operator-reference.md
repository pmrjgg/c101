# Flow operator reference

Companion to `kotlin-coroutines-flow` (kotlinx.coroutines 1.11). Opt-ins: `@FlowPreview` for `debounce`
and `sample`; `@ExperimentalCoroutinesApi` for `flatMapLatest`, `flatMapMerge`, `flatMapConcat`,
`mapLatest`, `transformLatest`, `chunked`.

## 1. Builders

| Builder | Kind | Rules |
|---|---|---|
| `flow { emit(x) }` | cold, sequential | emit only from the builder's own coroutine and context; cancellable on each `emit` |
| `flowOf(a, b)`, `list.asFlow()`, `(1..n).asFlow()` | cold | `asFlow()` sources do not check cancellation: add `.cancellable()` for long ranges |
| `channelFlow { launch { send(x) } }` | cold, concurrent | several producer coroutines; buffered channel underneath |
| `callbackFlow { trySend(x); awaitClose { unregister() } }` | cold | callback and listener APIs; `awaitClose` is mandatory |
| `MutableStateFlow(initial)` | hot | always has a value; conflated; equality-deduplicated |
| `MutableSharedFlow(replay, extraBufferCapacity, onBufferOverflow)` | hot | broadcast; emitting costs O(subscribers) |
| `Channel(capacity).receiveAsFlow()` | hot | each element to exactly one collector |
| `stateIn` / `shareIn` | hot | one upstream collection shared by all subscribers |

## 2. Context, buffering and fusion

- `flowOn(ctx)` with a different dispatcher runs the upstream in another coroutine connected by a channel
  with the default buffer (64, `kotlinx.coroutines.channels.defaultBuffer`). Each `flowOn` affects the
  operators above it up to the previous `flowOn`: in `src.flowOn(IO).map { }.flowOn(Default)` the source
  runs on IO and `map` on Default.
- Adjacent `channelFlow`, `flowOn`, `buffer` and `produceIn` fuse into one channel:
  `flowOn(Dispatchers.IO).buffer(10)` uses a single channel of capacity 10. `conflate()` is
  `buffer(Channel.CONFLATED)`.
- On a `SharedFlow`, `flowOn`, `buffer(RENDEZVOUS)` and `cancellable()` have no effect: configure buffering
  on `MutableSharedFlow` itself.
- `buffer(capacity, onBufferOverflow = BufferOverflow.DROP_OLDEST)` turns a slow collector into dropped
  intermediate values instead of a suspended producer.

## 3. Timing operators

Input: `a@0 b@100 c@250 d@650` (milliseconds), the source stays open.

| Operator | Output | Notes |
|---|---|---|
| `debounce(300)` | `c@550`, `d@950` | each value restarts the window; when the source completes, the pending value is emitted at once |
| `sample(200)` | `b@200`, `c@400`, `d@800` | ticks from subscription; a tick with no new value emits nothing; a value pending at completion is dropped |
| `conflate()`, collector busy 300 ms per value | `a@0`, `c@300`, `d@650` | `b` is skipped: only the newest waiting value is kept |
| `collectLatest { delay(200); handle(it) }` | handled: `c@450`, `d@850` | `a`'s block is cancelled at 100, `b`'s at 250 |
| `mapLatest`, `flatMapLatest`, `transformLatest` | same cancellation rule, results flow downstream | the previous block is cancelled and joined before the next starts |
| `chunked(2)` (1.9+) | `[a, b]@100`, `[c, d]@650` | a partial last chunk is emitted on completion |

## 4. Combining

| Operator | Emits | Completes |
|---|---|---|
| `combine(a, b) { x, y -> }` | after both emitted once, on every change of either | when all complete |
| `a.zip(b) { x, y -> }` | pairs in order: (a1, b1), (a2, b2) | when either completes |
| `merge(a, b)` | every value of both as it arrives | when all complete |
| `flatMapConcat { }` | inner flows one after another, in order | after the last inner flow |
| `flatMapMerge(concurrency = 16) { }` | inner flows concurrently (default 16), interleaved | after all |
| `flatMapLatest { }` | only the newest inner flow; older ones cancelled | after the outer and the last inner |

`combine` with a `StateFlow` input emits immediately (it already has a value); with a cold flow that never
emits, `combine` never emits at all.

## 5. Exceptions

- `catch { }` sees exceptions from upstream only; place it below the operator that throws and before
  `stateIn`/`shareIn`/`launchIn`. It does not see `CancellationException` from cancellation.
- `retryWhen { cause, attempt -> }`: `attempt` starts at 0 and only grows; successful values between failures
  do not reset it. For an endless poller count consecutive failures yourself (reset on success) or put the
  retry inside the polling loop around the single request.
- Exception transparency: a `try { emit(x) } catch (e: Exception) { emit(fallback) }` inside `flow { }`
  catches downstream failures and then emits again, which fails with "Flow exception transparency is
  violated: Previous 'emit' call has thrown exception ..., but then emission attempt of value ... has been
  detected." Use the `catch` operator.
- `onCompletion { cause -> }` runs on success (`cause == null`), failure and cancellation, and does not
  swallow the exception; `onCompletion { emit(x) }` can append a final value on normal completion.
- Terminal operators rethrow: `collect` throws whatever escaped; `launchIn(scope)` hands it to the scope
  (crash on `viewModelScope` unless a `catch` exists).

## 6. Sharing parameters

| API | Parameters | Behaviour |
|---|---|---|
| `stateIn(scope, started, initialValue)` | `started`: `Eagerly`, `Lazily`, `WhileSubscribed(stopTimeoutMillis = 0, replayExpirationMillis = Long.MAX_VALUE)` | returns `StateFlow`; the value persists after the upstream stops unless `replayExpirationMillis` resets it to `initialValue` |
| `stateIn(scope)` (suspending) | none | waits for the first value; starts eagerly |
| `shareIn(scope, started, replay = 0)` | as above + `replay` | returns `SharedFlow`; replay cache for late subscribers |
| `SharingStarted.WhileSubscribed(5_000)` | | keeps the upstream 5 s after the last subscriber leaves (rotation-proof) |

`WhileSubscribed(5_000, replayExpirationMillis = 0)` resets the cached value when the upstream stops, so a
screen returning after a long time shows the initial value instead of stale data.

## 7. StateFlow and SharedFlow details

- `MutableStateFlow.value = x` is thread-safe; `update { }` is an atomic compare-and-set loop: its lambda can
  run more than once, so keep it pure.
- `compareAndSet(expect, update)` for lock-free state machines.
- `MutableSharedFlow.tryEmit` with no buffer: false with subscribers present, true (value dropped) without.
- `subscriptionCount: StateFlow<Int>` on mutable shared/state flows drives custom start/stop logic.
- `replay = 1` approximates `StateFlow` without equality conflation and without an initial value.
