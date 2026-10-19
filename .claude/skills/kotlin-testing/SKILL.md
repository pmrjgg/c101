---
name: kotlin-testing
description: "Kotlin testing stack. Covers Kotest 6 specs, data-driven and property tests, kotlin.test with JUnit 5/6, MockK at boundaries, runTest virtual time with injected dispatchers, Turbine for flows, the Android Main-dispatcher rule, Robolectric, Compose and Roborazzi tests, Kover coverage gates and Konsist architecture checks. Load when writing, fixing or de-flaking Kotlin tests."
when_to_use: "Editing *Test.kt, *Spec.kt, src/test, commonTest or androidTest; failures such as 'Detected use of different schedulers', 'After waiting for 1m ... Use TestScope.backgroundScope', 'Module with the Main dispatcher is missing', Turbine 'Unconsumed events found' or 'Timed out waiting for 3s', 'MockKException: no answer found for'; flaky coroutine or Flow tests; adding koverVerify gates or Konsist rules."
---

# Kotlin testing

Baseline (October 2026; read `gradle/libs.versions.toml` before using anything newer than the project pins):

| Library | Current | Notes |
|---|---|---|
| kotlinx-coroutines-test | 1.11.0 | `runTest` total timeout 60 s by default |
| Kotest | 6.2.x | needs JDK 11+ and Kotlin 2.2+ |
| JUnit | 6.1.x (5.x still common) | same `org.junit.jupiter` API; JUnit 6 accepts `suspend` test methods (real time) |
| MockK | 1.14.x | `io.mockk:mockk`; `mockk-android` for instrumented tests |
| Turbine | 1.2.1 | every await has a 3 s wall-clock timeout |
| Kover / Konsist | 0.9.x / 0.18.x | Gradle plugin / test-scope library |
| Robolectric / Roborazzi | 4.17 / 1.7x | JVM Android tests and screenshots |

Deep material: [Kotest cookbook](references/kotest-cookbook.md) (styles, data-test variants, generators,
project config) | [Android, Compose and screenshot tests](references/android-compose-tests.md) (Gradle,
Robolectric, Compose v2 rules, Roborazzi workflow).

## 1. Choose the stack

| Situation | Choose | Why |
|---|---|---|
| KMP `commonTest` | `kotlin("test")` + `runTest` | runs on every target; add Kotest via the `io.kotest` Gradle plugin + KSP if specs are wanted |
| JVM/Android module, JUnit habits, Spring Boot 4 (JUnit 6 default) | `kotlin("test")` on Jupiter + MockK + Turbine | best IDE/CI support, `@ParameterizedTest` for tables |
| many table cases, nested contexts, rich matchers | Kotest `FunSpec` | `withTests`, `assertSoftly`, `eventually` |
| invariants over input spaces | `kotest-property` (also inside JUnit tests: `checkAll` is a suspend fun) | shrinking, replayable seeds |

One style per module. Kotest 6 changes that bite during upgrades from 5.x:
- Project config is found only at `io.kotest.provided.ProjectConfig` (or `-Dkotest.framework.config.fqn`);
  classpath scanning and `@AutoScan` are gone. Register extensions in that config
  (`override val extensions = listOf(...)`, a `val` now) or with `@ApplyExtension(...)` on a spec.
- `withData` lives in the core engine (drop `kotest-framework-datatest`); 6.1 added per-style variants
  (`withTests`/`withContexts` in `FunSpec`). `table`/`forAll(row(...))` moved to `kotest-assertions-table`.
- New `IsolationMode.InstancePerRoot`; `InstancePerTest` and `InstancePerLeaf` are deprecated.
- Multiplatform needs no compiler plugin: apply `id("io.kotest")` and `id("com.google.devtools.ksp")`, depend
  on `kotest-framework-engine` in `commonTest`.

JVM Gradle setup:

```kotlin
dependencies {
    testImplementation(kotlin("test"))                                   // kotlin-test-junit5 under useJUnitPlatform()
    testImplementation(platform("org.junit:junit-bom:6.1.3"))            // kotlin-test-junit5 pins Jupiter 5.10: align it
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")       // declare it explicitly on Gradle 8+
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
    testImplementation("io.mockk:mockk:1.14.11")
    testImplementation("app.cash.turbine:turbine:1.2.1")
    testImplementation("io.kotest:kotest-runner-junit5:6.2.6")           // only with Kotest specs
    testImplementation("io.kotest:kotest-property:6.2.6")
}
tasks.test {
    useJUnitPlatform()
    jvmArgs("-XX:+EnableDynamicAgentLoading")                            // JDK 21+ warning from MockK's agent
}
tasks.named<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>("compileTestKotlin") {
    compilerOptions.optIn.add("kotlinx.coroutines.ExperimentalCoroutinesApi")  // currentTime, advanceTimeBy, setMain...
}
```

## 2. Kotest specs, matchers, isolation, extensions

| Style | Shape | Use |
|---|---|---|
| `FunSpec` | `context("...") { test("...") { } }` | default |
| `StringSpec` | `"name" { }` | flat lists of small tests |
| `BehaviorSpec` | `Given/When/Then` (capitalised forms avoid backticks) | acceptance wording |
| `DescribeSpec` | `describe/it` | teams from JS/Ruby |

```kotlin
class PricingSpec : FunSpec({
    val pricing = Pricing(taxRate = "0.20".toBigDecimal())        // gross() rounds HALF_EVEN to 2 places

    test("adds tax") { pricing.gross("10.00".toBigDecimal()) shouldBe "12.00".toBigDecimal() }

    test("rejects negative amounts") {
        shouldThrow<IllegalArgumentException> { pricing.gross("-1".toBigDecimal()) }
            .message shouldContain "negative"
    }

    context("net to gross") {
        withTests(nameFn = { (net, gross) -> "$net -> $gross" },     // Kotest 6.1+; withData before
            "0.00" to "0.00", "1.00" to "1.20", "0.05" to "0.06",
        ) { (net, gross) -> pricing.gross(net.toBigDecimal()) shouldBe gross.toBigDecimal() }
    }

    test("slow path").config(timeout = 2.seconds, invocations = 3) { /* ... */ }
})
```

- Matchers: `shouldBe`, `shouldThrow<T> { }` (returns the exception), `shouldThrowExactly`, `shouldThrowAny`,
  `shouldContainExactly`, `shouldContainExactlyInAnyOrder`, `shouldBeInstanceOf<T>()` (smart-casts),
  `shouldNotBeNull()`, `shouldBeLessThanOrEqualTo`; BigDecimal `equals` includes scale, so use
  `shouldBeEqualIgnoringScale`. `assertSoftly { }` reports every failure in the block.
- `eventually(5.seconds) { outbox.sent() shouldContain "order-42" }` (package
  `io.kotest.assertions.nondeterministic`) retries in real time; `eventuallyConfig { duration; interval;
  initialDelay; retries; expectedExceptions }`. Use it for external effects (embedded server, file watcher),
  never for coroutine code you can drive with virtual time.
- Isolation: `SingleInstance` (default) shares spec-body state between tests, so reset it in `beforeTest`
  or set `isolationMode = IsolationMode.InstancePerRoot` in the spec body (or `override val isolationMode`
  in `ProjectConfig`, or `-Dkotest.framework.isolation.mode`).
- Hooks: `beforeTest { }`, `afterTest { }`, `beforeSpec { }`, `afterSpec { }`; reusable logic as an extension.

## 3. Property testing

| Element | API | Default |
|---|---|---|
| assertion property | `checkAll(arbA, arbB) { a, b -> ... }` | 1000 iterations (`kotest.proptest.default.iteration.count`) |
| boolean property | `forAll(arb) { it.isValid() }` | same |
| config | `PropTestConfig(iterations, seed, minSuccess, maxFailure, shrinkingMode, edgeConfig)` | `maxFailure = 0` |
| edge cases | mixed into random values | probability 0.02 |
| shrinking | `ShrinkingMode.Bounded(n)`, `Unbounded`, `Off` | `Bounded(1000)` |
| failed seeds | printed; written under `~/.kotest/seeds/` and replayed until the test passes | `PropertyTesting.writeFailedSeed = true` |

```kotlin
class CsvSpec : FunSpec({
    val cell = Arb.string(0..12, Codepoint.printableAscii())       // includes commas, quotes, empty string
    test("csv line round-trips") {
        checkAll(PropTestConfig(iterations = 2_000), Arb.list(cell, 0..8)) { cells ->
            parseCsvLine(renderCsvLine(cells)) shouldBe cells
        }
    }
})
val arbOrder = arbitrary { Order(Arb.uuid().bind(), Arb.list(arbLine, 0..20).bind()) }  // custom generator
```

Property shapes: round trip (`decode(encode(x)) == x`), invariant (`total >= 0`), oracle (fast impl equals
naive impl), idempotence (`f(f(x)) == f(x)`). To reproduce, pin `PropTestConfig(seed = <printed seed>)`
while debugging, then remove it; set `-Dkotest.proptest.seed.fail-if-set=true` on CI so a committed seed fails.

## 4. MockK at boundaries

```kotlin
val repo = mockk<OrderRepo>()                                     // strict: unstubbed call -> MockKException
val events = mockk<EventBus>(relaxUnitFun = true)                 // Unit functions auto-stubbed
coEvery { repo.find(OrderId("o1")) } returns order
coEvery { repo.save(any()) } answers { firstArg() }
OrderService(repo, events).confirm(OrderId("o1"))
val saved = slot<Order>()
coVerify(exactly = 1) { repo.save(capture(saved)) }
saved.captured.status shouldBe Status.CONFIRMED
verify { events.publish(match { it is OrderConfirmed && it.id == OrderId("o1") }) }
confirmVerified(events)                                           // no unexpected calls
```

| Need | MockK |
|---|---|
| suspend functions | `coEvery`, `coVerify`, `coAnswers { delay(50); x }`, `coJustRun` |
| answer sequences | `returnsMany listOf(a, b)`, `throws e andThen x`, `throwsMany listOf(e1, e2) andThen x` |
| loose mocks | `relaxUnitFun = true` (preferred) or `relaxed = true` (every call returns a default) |
| objects / top-level fns | `mockkObject(Obj)`, `mockkStatic(::topLevelFn)` or `mockkStatic("pkg.FileKt")` |
| constructors | `mockkConstructor(Client::class)` + `every { anyConstructed<Client>().call() }` |
| argument capture | `slot<T>()` + `capture(slot)` (last call); `mutableListOf<T>()` + `capture(list)` (every call) |
| partial / ordering | `spyk(real)`; `verifyOrder { }`, `verifySequence { }` |
| asynchronous calls | `verify(timeout = 1_000) { ... }` (real milliseconds) |
| JUnit Jupiter | `@ExtendWith(MockKExtension::class)`, `@MockK`, `@RelaxedMockK`, `@InjectMockKs`, `@MockKExtension.ConfirmVerification`, `@MockKExtension.CheckUnnecessaryStub` |

`mockkObject`/`mockkStatic`/`mockkConstructor` patch JVM-global state: use the scoped forms
(`mockkObject(Clock) { ... }`) or `unmockkAll()` in teardown, and never in parallel tests. Prefer fakes
(small in-memory implementations) for repositories, clocks, ID generators and feature flags; mock only the
outbound side effects you must verify; over-mocked tests that mirror implementation calls break on every
refactor. Wrap third-party SDKs behind your own interface and fake that.

## 5. Coroutine tests: runTest and virtual time

1. `@Test fun x() = runTest { }`: `delay` is skipped on dispatchers that share the test scheduler; code on
   real `Dispatchers.Default`/`IO` runs in real time, so dispatchers must be constructor-injected.
2. Pass `StandardTestDispatcher(testScheduler)` for every injected dispatcher. A dispatcher with its own
   scheduler fails with "Detected use of different schedulers. If you need to use several test coroutine
   dispatchers, create one `TestCoroutineScheduler` and pass it to each of them."
3. Clock control: `runCurrent()` runs tasks due now; `advanceTimeBy(ms)` runs tasks due in
   `[now, now + ms)` (call `runCurrent()` for the boundary); `advanceUntilIdle()` drains everything (never
   with an infinite poller); read `currentTime`; give `TimeSource` users `testTimeSource`.
4. When the test body suspends (awaiting a result, `job.join()`, a Turbine await), `runTest` advances
   virtual time to the next task by itself.
5. Never-ending collectors go in `backgroundScope.launch { }`; otherwise the test fails after 60 s with
   "After waiting for 1m, there were active child jobs: [...]. Use `TestScope.backgroundScope` ...".
   Override the timeout with `runTest(timeout = 10.seconds)` or `-Dkotlinx.coroutines.test.default_timeout=30s`.
6. `StandardTestDispatcher` queues work (deterministic, default); `UnconfinedTestDispatcher` runs launches
   eagerly, which suits a hot-flow collector (`backgroundScope.launch(UnconfinedTestDispatcher(testScheduler))`)
   and hides ordering bugs everywhere else.

`Dispatchers.Main` (anything using `viewModelScope`) must be replaced; if it is set to a `TestDispatcher`
before `runTest`, `runTest` reuses its scheduler, so ViewModel delays run on virtual time too:

```kotlin
class MainDispatcherRule(val dispatcher: TestDispatcher = StandardTestDispatcher()) : TestWatcher() {
    override fun starting(description: Description) = Dispatchers.setMain(dispatcher)    // JUnit 4: @get:Rule
    override fun finished(description: Description) = Dispatchers.resetMain()
}
class MainDispatcherExtension(val dispatcher: TestDispatcher = StandardTestDispatcher()) :
    BeforeEachCallback, AfterEachCallback {                       // Jupiter: @JvmField @RegisterExtension
    override fun beforeEach(context: ExtensionContext) = Dispatchers.setMain(dispatcher)
    override fun afterEach(context: ExtensionContext) = Dispatchers.resetMain()
}
// Kotest spec body: beforeTest { Dispatchers.setMain(StandardTestDispatcher()) }; afterTest { Dispatchers.resetMain() }
```

Kotest virtual time: `test("x").config(coroutineTestScope = true) { ... }` (or `coroutineTestScope = true` in
the spec body / `ProjectConfig`), then use `testCoroutineScheduler` (from `io.kotest.core.test`).
JUnit 6 `suspend fun` tests run in real time without a `TestScope`; keep `runTest` for virtual time.

## 6. Flow tests with Turbine

| API | Meaning |
|---|---|
| `flow.test { }` | collect, run the block, then cancel and fail on unconsumed events |
| `awaitItem()`, `awaitComplete()`, `awaitError()` | next event must be that kind |
| `skipItems(n)`, `expectMostRecentItem()` | drop intermediates |
| `expectNoEvents()` | nothing pending right now |
| `cancelAndIgnoreRemainingEvents()`, `cancelAndConsumeRemainingEvents()` | end for hot or infinite flows |
| `turbineScope { a = f1.testIn(backgroundScope); b = f2.testIn(backgroundScope) }` | several flows; `testIn` requires `turbineScope` (1.0+) |
| `Turbine<T>()` | standalone channel for fakes and callbacks |
| `test(timeout = 10.seconds)`, `withTurbineTimeout(10.seconds) { }` | wall-clock timeout (default 3 s) |

- Inside `runTest`, Turbine collects on `UnconfinedTestDispatcher(testScheduler)`: it sees each emission
  immediately, yet `StateFlow` still conflates values set twice before its producer runs and never re-emits
  an equal value. A `StateFlow`'s first item is its current value: always `awaitItem()` it first.
- `SharedFlow(replay = 0)`: enter `test { }` before triggering emissions or they are lost.
- Finite flows end with `awaitComplete()`; hot flows with `cancelAndIgnoreRemainingEvents()`.

## 7. Android and Compose

| Layer | Tool | Source set |
|---|---|---|
| ViewModel, repository | JUnit + `runTest` + `MainDispatcherRule` | `src/test` |
| Compose UI on the JVM | Robolectric + `createComposeRule()` (`androidx.compose.ui.test.junit4.v2`, ui-test 1.11+) | `src/test` with `isIncludeAndroidResources = true` |
| screenshots | Roborazzi `captureRoboImage()`, `@GraphicsMode(GraphicsMode.Mode.NATIVE)` | `src/test`, goldens in git |
| real device behaviour | `createAndroidComposeRule<MainActivity>()` instrumented | `src/androidTest` |

The v2 Compose test APIs run composition on `StandardTestDispatcher` (v1 used `UnconfinedTestDispatcher`):
synchronise with `waitForIdle()`/`runOnIdle { }` or `mainClock.advanceTimeBy(ms)`. `createComposeRule`
plus `runTest` gives two clocks; use `runComposeUiTest { }`, which runs the body inside its own `runTest`.
Roborazzi: `./gradlew recordRoborazziDebug` writes goldens, `verifyRoborazziDebug` fails on diffs.

## 8. Coverage (Kover) and architecture (Konsist)

```kotlin
import kotlinx.kover.gradle.plugin.dsl.*
plugins { id("org.jetbrains.kotlinx.kover") version "0.9.11" }
dependencies { kover(project(":core")); kover(project(":feature-search")) }   // merge modules here
kover {
    reports {
        filters { excludes {
            classes("*.BuildConfig", "*ComposableSingletons*", "*_Factory")
            packages("com.acme.generated"); annotatedBy("*Generated*")   // BINARY/RUNTIME retention only
        } }
        verify {
            rule("lines") { minBound(80) }                          // LINE + COVERED_PERCENTAGE by default
            rule("branches") { minBound(65, CoverageUnit.BRANCH) }
        }
    }
}
```

`./gradlew koverHtmlReport koverVerify` (HTML in `build/reports/kover/html/`), `koverLog` prints totals,
Android variants append the variant (`koverHtmlReportDebug`). Call `koverVerify` explicitly in CI. Gate
on the merged report and raise thresholds per module; a 100% target buys getter tests, not safety.

```kotlin
@Test fun `layers`() {                                          // block bodies: Jupiter runs only void methods
    Konsist.scopeFromProduction().assertArchitecture {
        val domain = Layer("Domain", "com.acme.domain..")
        val data = Layer("Data", "com.acme.data..")
        val ui = Layer("UI", "com.acme.ui..")
        domain.dependsOnNothing(); data.dependsOn(domain); ui.dependsOn(domain)
    }
}
@Test fun `view models`() {
    Konsist.scopeFromProduction().classes().withAllParentsOf(ViewModel::class)
        .assertTrue { it.name.endsWith("ViewModel") && it.resideInPackage("..ui..") }
}
@Test fun `no sleeping tests`() {
    Konsist.scopeFromTest().files.assertFalse { it.hasTextContaining("Thread.sleep(") }
}
```

## 9. Flakiness sources

| Source | Symptom | Fix |
|---|---|---|
| real delays: `Thread.sleep`, hard-coded `Dispatchers.IO`/`Default`, `withTimeout` on a real dispatcher | slow tests, CI-only timeouts, `currentTime` stays 0 | inject dispatchers, share `testScheduler` |
| `UnconfinedTestDispatcher` everywhere | passes locally, order-dependent failures; intermediate `StateFlow` values seen or skipped | `StandardTestDispatcher` by default; unconfined only for hot-flow collectors |
| new `StandardTestDispatcher()` per class without `setMain` | "Detected use of different schedulers" or delays never advance | one scheduler per test |
| shared mutable singletons: `object` caches, `mockkObject`/`mockkStatic` left active, `setMain` not reset | passes alone, fails in suite or in parallel | scoped mocks, `unmockkAll()`/`resetMain()` in teardown, inject instead of `object` |
| Kotest `SingleInstance` spec-body state | second test sees first test's data | `InstancePerRoot` or reset in `beforeTest` |
| wall-clock reads (`System.currentTimeMillis`, `Instant.now()`) | fails near midnight or on slow CI | inject `Clock`/`TimeSource`; `testTimeSource` |
| Turbine 3 s or `eventually` timeouts on loaded CI | sporadic "Timed out waiting for 3s" | raise the timeout only after removing real waiting |

Hunt flakes with repetition: `./gradlew test --tests '*SearchViewModelTest*' --rerun-tasks` in a loop, or
Kotest `.config(invocations = 200)`.

## 10. Worked example: retry with backoff, 600 ms of virtual time

```kotlin
data class Quote(val symbol: String, val price: BigDecimal)
interface QuoteApi { suspend fun fetch(symbol: String): Quote }

class QuoteRepository(
    private val api: QuoteApi,
    private val io: CoroutineDispatcher = Dispatchers.IO,
    private val maxAttempts: Int = 3,
    private val firstBackoff: Duration = 200.milliseconds,
) {
    /** Retries IOException with 200 ms then 400 ms backoff; CancellationException is never caught. */
    suspend fun quote(symbol: String): Quote = withContext(io) {
        var backoff = firstBackoff
        repeat(maxAttempts - 1) {
            try {
                return@withContext api.fetch(symbol)
            } catch (e: IOException) {
                delay(backoff)
                backoff *= 2
            }
        }
        api.fetch(symbol)                                         // last attempt: failure reaches the caller
    }
}
```

```kotlin
class QuoteRepositoryTest {
    private val api = mockk<QuoteApi>()
    private val acme = Quote("ACME", "42.00".toBigDecimal())

    @Test fun `retries twice then succeeds`() = runTest {
        coEvery { api.fetch("ACME") } throws IOException("503") andThenThrows IOException("503") andThen acme
        val repo = QuoteRepository(api, io = StandardTestDispatcher(testScheduler))

        assertEquals(acme, repo.quote("ACME"))
        assertEquals(600, currentTime)                            // t=0 fail, t=200 fail, t=600 success
        coVerify(exactly = 3) { api.fetch("ACME") }
        confirmVerified(api)
    }

    @Test fun `gives up after three attempts`() = runTest {
        coEvery { api.fetch(any()) } throws IOException("down")
        val repo = QuoteRepository(api, io = StandardTestDispatcher(testScheduler))

        assertEquals("down", assertFailsWith<IOException> { repo.quote("ACME") }.message)
        assertEquals(600, currentTime)                            // no sleep after the last attempt
    }

    @Test fun `cancellation during backoff stops retrying`() = runTest {
        coEvery { api.fetch(any()) } throws IOException("503")
        val job = launch { QuoteRepository(api, io = StandardTestDispatcher(testScheduler)).quote("ACME") }
        advanceTimeBy(150)                                        // attempt 1 at t=0, sleeping until t=200
        job.cancelAndJoin()

        assertTrue(job.isCancelled)
        assertEquals(150, currentTime)
        coVerify(exactly = 1) { api.fetch("ACME") }
    }
}
```

```bash
./gradlew test --tests 'com.acme.quotes.QuoteRepositoryTest'    # 1.35 s of simulated waiting, ~ms of wall clock
```

What the numbers prove: replacing exponential with constant backoff fails the first test with
`expected: <600> but was: <400>`; defaulting `io` to `Dispatchers.IO` leaves `currentTime` at 0 and makes the
test wait 600 real milliseconds; swallowing cancellation (`runCatching { delay(backoff) }`) makes the third
test record 3 calls instead of 1. The Kotest form is identical: `coroutineTestScope = true` in the spec body,
`StandardTestDispatcher(testCoroutineScheduler)` and `testCoroutineScheduler.currentTime shouldBe 600`.

## Pitfalls

- `advanceTimeBy(200)` does not run a task due at exactly t=200: follow it with `runCurrent()`.
- `advanceUntilIdle()` on a `while (isActive) { delay(...) }` poller never returns: advance by a bounded amount.
- `runBlocking` or `Thread.sleep` inside `runTest` blocks the only test thread and stalls virtual time.
- `relaxed = true` mocks return `0`/`""`/empty and hide missing stubs; prefer `relaxUnitFun = true`.
- `coEvery { }` stubs that never match (wrong argument) surface as "no answer found for"; check equality of
  value objects or use `any()`/`match { }`.
- `verify(timeout = ...)` waits in real time even under `runTest`.
- Several tests sharing one `Turbine` or `MutableSharedFlow` fake leak events between tests: create per test.
- A Kotest spec that defines `val` state in the body runs it once for all tests under `SingleInstance`.
- Robolectric tests are JUnit 4 (`@RunWith(AndroidJUnit4::class)`); on the JUnit Platform they need the
  deprecated but still shipped Vintage engine.
- `kotlin("test")` without `useJUnitPlatform()` resolves to the JUnit 4 flavour and Jupiter tests are skipped.
- Backtick names with spaces work on the JVM, but other KMP targets restrict characters and DEX before API 30
  rejects spaces in method names (instrumented tests): keep `commonTest`/`androidTest` names plain.

Related: `kotlin-coroutines-flow` (what these tests verify), `kotlin-compose` (UI test details),
`kotlin-multiplatform` (commonTest across targets), `kotlin-gradle-builds` (test task and convention setup),
`kotlin-java-interop`, `testing-strategy`; hub `kotlin-craft`.
