---
name: kotlin-craft
description: "Kotlin expertise pack covering null safety, data, value and sealed classes, coroutines and Flow, structured concurrency, DSL builders and context parameters, Kotlin Multiplatform, Jetpack and Compose Multiplatform basics, Gradle Kotlin DSL, Kotest and MockK, and Java interop pitfalls. Load when writing, reviewing, debugging or building Kotlin code for JVM, Android or Multiplatform."
when_to_use: "Any task touching .kt/.kts files, build.gradle.kts or libs.versions.toml, coroutine or Flow bugs (leaks, cancellation, hot/cold confusion), Compose UI state, KMP source sets, Kotlin-Java interop, or Kotlin test suites."
---

# Kotlin craft

Baseline: Kotlin 2.x with the K2 compiler. 2.2 stabilized guard conditions in `when`,
non-local `break`/`continue` and multi-dollar interpolation; 2.3 (Dec 2025) stabilized nested
type aliases and data-flow-based `when` exhaustiveness and added an experimental unused-return-
value checker; 2.4 (Jul 2026) made context parameters and explicit backing fields stable.
kotlinx.coroutines 1.10+. Check `kotlin` and coroutines versions in `libs.versions.toml` before
using newer features, and confirm library APIs (Ktor, Compose, Kotest) with
`mcp__context7__resolve-library-id` then `mcp__context7__query-docs`.

Deep material:
[coroutines and Flow](references/coroutines-flow.md) |
[Java interop, Multiplatform and Compose](references/interop-kmp-compose.md) |
[Gradle KTS and testing](references/gradle-testing.md)

## 1. Orient in a repo

```bash
./gradlew --version
cat gradle/libs.versions.toml 2>/dev/null | grep -nE 'kotlin|coroutines|compose|kotest|mockk|ktor'
ls settings.gradle.kts build-logic buildSrc 2>/dev/null
grep -rn 'kotlin("multiplatform")\|kotlin.multiplatform\|androidTarget\|iosArm64' --include=*.kts . | head
grep -rn 'freeCompilerArgs\|explicitApi\|allWarningsAsErrors' --include=*.kts . | head
```

Record: Kotlin and AGP versions, targets (JVM, Android, iOS, JS/Wasm), convention plugins,
compiler flags, test stack (JUnit 5 + Kotest/MockK, kotlin.test, Turbine), lint (detekt, ktlint/ktfmt).

## 2. The gate

| Step | Command | Blocks when |
|---|---|---|
| Build + tests | `./gradlew build` (KMP: `./gradlew allTests`) | failure |
| Static analysis | `./gradlew detekt` | new findings |
| Format | `./gradlew ktlintCheck` or `spotlessCheck` (ktfmt) | diff |
| Warnings | `compilerOptions { allWarningsAsErrors.set(true) }` in CI | any warning |
| Public API (libraries) | `explicitApi()` + binary-compatibility validator (`apiCheck`) or KGP ABI validation | unreviewed API change |
| Android | `./gradlew lint testDebugUnitTest` | errors |

## 3. Null safety

Rules:
1. `!!` is banned in production code (detekt `UnsafeCallOnNullableType`); allowed in tests.
2. Use `requireNotNull(x) { "why" }` for argument preconditions, `checkNotNull` for state,
   `?: return`/`?: throw` for early exits, `?.let { }` only when it reads better than `if`.
3. `lateinit` only for framework/DI injection and test setup; never for "set later" state
   (use nullable or a constructor parameter).
4. Java APIs return platform types (`String!`). Annotate the Java side with JSpecify
   (`@NullMarked`, `@Nullable`); Kotlin enforces JSpecify (configurable with
   `-Xjspecify-annotations=strict|warn|ignore`). For unannotated Java, declare the Kotlin-side
   type explicitly at the boundary: `val name: String? = javaObj.getName()`.
5. Collections: `List<String?>` (nullable elements) vs `List<String>?` (nullable list): choose
   deliberately; `filterNotNull()`, `mapNotNull { }`.

## 4. Class kinds: decision table

| Need | Kind | Notes |
|---|---|---|
| immutable data with value equality | `data class` with `val`s | `copy` calls the primary constructor (init validation runs) |
| validated single-value wrapper, zero overhead | `@JvmInline value class` | boxed when nullable, generic, or used as interface; Java sees mangled names |
| closed set of variants with data | `sealed interface` + `data class`/`data object` | exhaustive `when` without `else` |
| closed set of constants | `enum class` | iterate with `entries` (not `values()`) |
| singleton | `object` / `data object` | `data object` gives a readable `toString` in sealed hierarchies |
| behavior-only abstraction | `interface` / `fun interface` (SAM) | |
| extensibility by inheritance | `open`/`abstract class` | classes are final by default; keep them final |

```kotlin
@JvmInline
value class Email private constructor(val value: String) {
    companion object {
        fun parse(raw: String): Email? =
            raw.trim().lowercase().takeIf { it.length <= 254 && '@' in it }?.let(::Email)
    }
}

sealed interface LoadState<out T> {
    data object Loading : LoadState<Nothing>
    data class Success<T>(val value: T) : LoadState<T>
    data class Failure(val error: Throwable, val retryable: Boolean) : LoadState<Nothing>
}

fun <T> render(s: LoadState<T>): String = when (s) {
    LoadState.Loading -> "loading"
    is LoadState.Success -> "ok: ${s.value}"
    is LoadState.Failure if s.retryable -> "retry: ${s.error.message}"   // guard condition (2.2+)
    is LoadState.Failure -> "failed: ${s.error.message}"
}
```

Data-class caveats: array properties compare by reference; a private constructor still exposed
a public `copy` in older versions (2.x warns; annotate `@ConsistentCopyVisibility` to align it);
avoid `var` properties in data classes used as map keys.

## 5. Coroutines: rules (details in [coroutines-flow](references/coroutines-flow.md))

1. Every coroutine runs in a scope owned by a lifecycle: `viewModelScope`, `lifecycleScope`, a
   request scope, or an application `CoroutineScope(SupervisorJob() + Dispatchers.Default)` that
   is cancelled on shutdown. No `GlobalScope`.
2. `suspend` functions are main-safe: the function that blocks switches dispatcher internally
   (`withContext(Dispatchers.IO) { ... }`); callers never need to know.
3. Parallel decomposition: `coroutineScope { val a = async { ... }; val b = async { ... }; a.await() to b.await() }`.
   A failing child cancels siblings and the exception propagates. `supervisorScope` when children
   are independent.
4. Never swallow `CancellationException`. `catch (e: Exception)` and `runCatching` around
   suspend calls catch it: rethrow it (or call `ensureActive()` / `currentCoroutineContext().ensureActive()`).
5. `withTimeout` throws `TimeoutCancellationException` (a `CancellationException`): uncaught in a
   `launch` it silently cancels. Prefer `withTimeoutOrNull` or catch it explicitly.
6. CPU loops cooperate with cancellation: `ensureActive()` or `yield()` per iteration batch.
7. Cleanup that must suspend runs in `finally { withContext(NonCancellable) { ... } }`.
8. `CoroutineExceptionHandler` works only on root `launch` coroutines; `async` exceptions surface
   at `await()`.
9. Limit parallelism for a resource with `Dispatchers.IO.limitedParallelism(n)` or a `Semaphore`.
10. Inject dispatchers (constructor parameter) so tests can substitute `StandardTestDispatcher`.

## 6. Flow essentials

| Need | Type |
|---|---|
| cold stream recomputed per collector (DB query, network paging) | `flow { emit(...) }`, `callbackFlow` for callback APIs |
| UI/state holder, always has a current value, conflated | `StateFlow` (`MutableStateFlow`, or `stateIn(scope, SharingStarted.WhileSubscribed(5_000), initial)`) |
| events or broadcast to many collectors | `SharedFlow` (`MutableSharedFlow(replay, extraBufferCapacity, onBufferOverflow)`) |
| exactly-once events to one consumer | `Channel` exposed with `receiveAsFlow()` |

Key operator semantics: `flowOn` changes the dispatcher of everything upstream; `catch` handles
only upstream errors; `collectLatest`/`mapLatest`/`flatMapLatest` cancel the previous work on a
new value; `buffer`/`conflate` decouple producer and consumer speeds; emitting from another
coroutine inside `flow {}` violates context preservation (use `channelFlow`). `StateFlow` uses
equality: emitting the same (or a mutated same) instance does not notify collectors.

## 7. DSL builders and context parameters

```kotlin
@DslMarker annotation class HtmlDsl

@HtmlDsl class Table { internal val rows = mutableListOf<Row>()
    fun row(block: Row.() -> Unit) { rows += Row().apply(block) } }
@HtmlDsl class Row { internal val cells = mutableListOf<String>()
    fun cell(text: String) { cells += text } }

fun table(block: Table.() -> Unit): Table = Table().apply(block)

val t = table {
    row { cell("a"); cell("b") }
    row { cell("c") /* row { } here is a compile error thanks to @DslMarker */ }
}
```

- `@DslMarker` prevents implicit access to outer receivers inside nested lambdas.
- `inline` builder functions with lambda parameters avoid allocation; `reified` type parameters
  for type-driven APIs (`inline fun <reified T> Json.decode(s: String): T`).
- Context parameters (stable in 2.4; preview with `-Xcontext-parameters` in 2.2-2.3) replace the
  removed context receivers:

```kotlin
interface Logger { fun info(msg: String) }
context(logger: Logger)
fun processOrder(id: String) { logger.info("processing $id") }

fun handler(logger: Logger) = with(logger) { processOrder("42") }   // resolved from scope
```

Use context parameters for ambient capabilities (logging, transactions, tracing) threaded
through many calls; not as a replacement for ordinary parameters.

## 8. Multiplatform and Compose (summary; details in [interop-kmp-compose](references/interop-kmp-compose.md))

- Put logic in `commonMain` with KMP-ready libraries (kotlinx.coroutines, kotlinx.serialization,
  kotlinx-datetime, Ktor client, SQLDelight/Room KMP); platform code in `androidMain`, `iosMain`, `jvmMain`.
- Prefer interfaces plus DI over `expect class`; use `expect fun` for small platform shims.
- iOS: functions that can throw to Swift need `@Throws(...)`; otherwise a Kotlin exception
  crossing into Swift crashes the app. Flows reach Swift via SKIE or Swift export (2.4 maps
  `Flow` to `AsyncSequence`, alpha).
- Compose: state is read in composition; hoist state, keep composables idempotent and
  side-effect free; side effects go through `LaunchedEffect`/`DisposableEffect`; collect flows
  with `collectAsStateWithLifecycle()` on Android.

## 9. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| coroutine keeps running after screen closed | `GlobalScope` or custom scope never cancelled | lifecycle scopes; cancel custom scopes |
| cancellation ignored, shutdown hangs | `catch (e: Exception)` / `runCatching` swallowing `CancellationException` | rethrow it; `ensureActive()` |
| job "silently" stops | uncaught `TimeoutCancellationException` from `withTimeout` | `withTimeoutOrNull` |
| UI misses or replays events | `StateFlow` for one-shot events | model events as state or use a `Channel` |
| UI not updating | mutating the object inside `MutableStateFlow` | emit a new immutable copy (`update { it.copy(...) }`) |
| `IllegalStateException: Flow invariant is violated` | `withContext` around `emit` | `flowOn`, `channelFlow` |
| NPE from Kotlin code | platform types from Java | JSpecify annotations, explicit nullable types at boundary |
| Spring proxies fail / `final` errors | Kotlin classes final by default | `kotlin("plugin.spring")` (all-open), `kotlin("plugin.jpa")` (no-arg) |
| Java callers cannot call function | default args, value classes, `suspend` | `@JvmOverloads`, `@JvmName`, expose `CompletableFuture` wrappers |
| `ClassCastException` around value classes in generics | boxing/unboxing at generic boundaries | avoid value classes in hot generic code; test interop |
| slow builds after adding annotation processor | kapt | migrate to KSP |
| recomposition storms | unstable parameters, reading fast-changing state high in the tree | stable/immutable types, `derivedStateOf`, defer reads with lambda modifiers |

## 10. Review checklist

- [ ] No `!!` in production code; Java boundaries typed explicitly or JSpecify-annotated.
- [ ] Data modeled with data/value/sealed types; `when` over sealed types has no `else`.
- [ ] Every coroutine has a lifecycle owner; no `GlobalScope`; dispatchers injected.
- [ ] `CancellationException` never swallowed; timeouts explicit; cleanup in `NonCancellable`.
- [ ] Flows: right hot/cold type; `stateIn`/`shareIn` with deliberate `SharingStarted`; operators on the intended side of `flowOn`.
- [ ] Public library API: `explicitApi()`, binary compatibility checked, Java-friendly annotations where Java callers exist.
- [ ] Tests: `runTest` with virtual time, Turbine for flows, MockK only at boundaries.
- [ ] Gradle: version catalog, convention plugins, no `kotlinOptions` (use `compilerOptions`), KSP over kapt.

## 11. Worked example: leaky callback wrapper to a correct Flow

Before: listener never unregistered, emissions after cancellation crash, blocking work on Main.

```kotlin
fun locationUpdates(client: LocationClient): Flow<Location> = flow {
    client.register { loc -> runBlocking { emit(loc) } }   // wrong: runBlocking, emit from foreign thread
}
```

After:

```kotlin
fun locationUpdates(client: LocationClient, dispatcher: CoroutineDispatcher = Dispatchers.Default): Flow<Location> = callbackFlow {
    val listener = LocationListener { loc ->
        trySend(loc)                                         // non-suspending, safe from any thread; dropped if closed
    }
    client.register(listener)
    awaitClose { client.unregister(listener) }              // runs on cancellation or close
}.buffer(Channel.CONFLATED)                                  // keep only the latest location
 .flowOn(dispatcher)                                         // injected (rule 10)
```

Consumers: `viewModelScope.launch { locationUpdates(client).collect { _state.update { s -> s.copy(location = it) } } }`
or share once across collectors with
`.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initialValue = null)`.
Test with Turbine inside `runTest`, injecting the test dispatcher so registration is deterministic:
`locationUpdates(fake, StandardTestDispatcher(testScheduler)).test { runCurrent(); fake.emit(a); assertEquals(a, awaitItem()); cancelAndIgnoreRemainingEvents() }`
(`runCurrent()` lets `client.register` run before the emit) and assert `fake.listenerCount == 0` afterwards.

## Delegation hints

- Coroutine deadlocks or leaks with thread dumps / `DebugProbes` output: `debugger`.
- Compose performance with recomposition counts and compiler reports: `code-optimizer`.
- Java-side API design for a mixed codebase: `java-expert` for the Java half.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `kotlin-compose` | building Compose screens or fixing recomposition, state or performance bugs |
| `kotlin-coroutines-flow` | writing or debugging suspend code, flows, leaked jobs or swallowed cancellation |
| `kotlin-gradle-builds` | setting up, upgrading or speeding up a Kotlin Gradle build |
| `kotlin-java-interop` | Kotlin-Java interoperability. Covers platform types and JSpecify nullness, exposing Kotlin APIs to Java with the @Jvm* annotations, value-class name mangling... |
| `kotlin-multiplatform` | sharing code across Android, iOS, JVM, desktop or web |
| `kotlin-testing` | writing, fixing or de-flaking Kotlin tests |
