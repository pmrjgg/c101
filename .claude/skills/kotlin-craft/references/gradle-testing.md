# Kotlin: Gradle Kotlin DSL and testing (Kotest, MockK, kotlin.test)

## 1. Version catalog

```toml
# gradle/libs.versions.toml
[versions]
kotlin = "2.4.0"
coroutines = "1.10.2"
kotest = "6.0.0"
mockk = "1.14.0"

[libraries]
kotlinx-coroutines-core = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-core", version.ref = "coroutines" }
kotlinx-coroutines-test = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-test", version.ref = "coroutines" }
kotest-runner-junit5 = { module = "io.kotest:kotest-runner-junit5", version.ref = "kotest" }
kotest-assertions-core = { module = "io.kotest:kotest-assertions-core", version.ref = "kotest" }
kotest-property = { module = "io.kotest:kotest-property", version.ref = "kotest" }
mockk = { module = "io.mockk:mockk", version.ref = "mockk" }
turbine = { module = "app.cash.turbine:turbine", version = "1.2.0" }
kotlin-gradle-plugin = { module = "org.jetbrains.kotlin:kotlin-gradle-plugin", version.ref = "kotlin" }

[plugins]
kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version.ref = "kotlin" }
kotlin-multiplatform = { id = "org.jetbrains.kotlin.multiplatform", version.ref = "kotlin" }
kotlin-serialization = { id = "org.jetbrains.kotlin.plugin.serialization", version.ref = "kotlin" }
compose-compiler = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
ksp = { id = "com.google.devtools.ksp", version = "<match the Kotlin version line>" }
```

The version numbers above illustrate the layout; use the versions the project already pins or
the current releases (check before bumping).

## 2. Convention plugin (build-logic included build)

```kotlin
// settings.gradle.kts
pluginManagement { includeBuild("build-logic") }

// build-logic/build.gradle.kts
plugins { `kotlin-dsl` }
dependencies { implementation(libs.kotlin.gradle.plugin) }   // catalog: kotlin-gradle-plugin = { module = "org.jetbrains.kotlin:kotlin-gradle-plugin", version.ref = "kotlin" }

// build-logic/src/main/kotlin/kotlin-jvm-conventions.gradle.kts
plugins { id("org.jetbrains.kotlin.jvm") }
kotlin {
    jvmToolchain(21)
    compilerOptions {
        allWarningsAsErrors.set(providers.gradleProperty("warningsAsErrors").map(String::toBoolean).orElse(false))
        freeCompilerArgs.addAll("-Xjsr305=strict")
    }
}
tasks.withType<Test>().configureEach { useJUnitPlatform() }

// any module
plugins { id("kotlin-jvm-conventions") }
```

Accessing the version catalog from inside `build-logic` needs a `versionCatalogs` entry in
`build-logic/settings.gradle.kts` (`from(files("../gradle/libs.versions.toml"))`). Plugins applied
by precompiled script plugins must be on build-logic's classpath as regular dependencies, as above.

Rules:
- `compilerOptions { }` replaces the removed `kotlinOptions { }`.
- `jvmToolchain(N)` sets both the JDK used to compile and the bytecode target; keep Java and
  Kotlin targets aligned (mismatches fail the build by default).
- Libraries: `kotlin { explicitApi() }` forces visibility modifiers and return types on public API.
- KSP for annotation processing (Room, Moshi codegen, Dagger/Hilt via KSP); kapt is in
  maintenance mode.
- Enable the configuration cache (`org.gradle.configuration-cache=true` in `gradle.properties`)
  and the build cache; avoid `afterEvaluate` and cross-project configuration.
- `./gradlew :module:dependencies --configuration runtimeClasspath` and
  `dependencyInsight` to debug version resolution.

## 3. Kotest

```kotlin
class PricingTest : FunSpec({
    val pricing = Pricing(taxRate = "0.20".toBigDecimal())

    test("adds tax") {
        pricing.gross("10.00".toBigDecimal()) shouldBe "12.00".toBigDecimal()
    }

    test("rejects negative amounts") {
        shouldThrow<IllegalArgumentException> { pricing.gross("-1".toBigDecimal()) }
            .message shouldContain "negative"
    }

    context("data-driven") {
        withData(
            nameFn = { (net, gross) -> "$net -> $gross" },
            "0.00" to "0.00", "1.00" to "1.20", "0.05" to "0.06",
        ) { (net, gross) -> pricing.gross(net.toBigDecimal()) shouldBe gross.toBigDecimal() }
    }

    test("gross is monotonic") {
        val money = Arb.long(0L..100_000_000L).map { BigDecimal.valueOf(it, 2) }   // 0.00 .. 1,000,000.00
        checkAll(money, money) { a, b ->
            if (a <= b) (pricing.gross(a) <= pricing.gross(b)) shouldBe true
        }
    }
})
```

- Spec styles: `FunSpec` (default choice), `StringSpec`, `BehaviorSpec` (given/when/then),
  `DescribeSpec`. Pick one per codebase.
- Matchers: `shouldBe`, `shouldContainExactly`, `shouldBeInstanceOf<T>()`, `shouldNotBeNull()`,
  `shouldBeEqualToComparingFields`; soft assertions with `assertSoftly { }`.
- Property testing: `checkAll` (assert), `forAll` (boolean); generators `Arb.int(range)`,
  `Arb.string(1..20, Codepoint.alphanumeric())`, `Arb.list(gen, 0..100)`, custom
  `arbitrary { Order(Arb.uuid().bind(), ...) }`; failing seeds are printed for replay.
- `withData` for table tests (module `kotest-framework-datatest` in Kotest 5; part of the core
  framework in newer versions: check the version in use).
- Coroutine tests: Kotest test bodies are suspend functions; enable virtual time with
  `coroutineTestScope = true` in the test config or use `runTest`.

## 4. MockK

```kotlin
val repo = mockk<OrderRepo>()
val events = mockk<EventBus>(relaxUnitFun = true)            // Unit-returning functions auto-stubbed
val service = OrderService(repo, events)

coEvery { repo.find(OrderId("o1")) } returns order
coEvery { repo.save(any()) } answers { firstArg() }

service.confirm(OrderId("o1"))

val saved = slot<Order>()
coVerify(exactly = 1) { repo.save(capture(saved)) }
saved.captured.status shouldBe Status.CONFIRMED
verify { events.publish(match { it is OrderConfirmed && it.id == OrderId("o1") }) }
confirmVerified(events)
```

| Need | MockK |
|---|---|
| suspend functions | `coEvery`, `coVerify`, `coAnswers` |
| objects / singletons | `mockkObject(Singleton)`; `unmockkObject` after |
| top-level / extension functions | `mockkStatic("com.acme.UtilsKt")` or `mockkStatic(String::toSlug)` |
| constructors | `mockkConstructor(Client::class)` then `every { anyConstructed<Client>().call() }` |
| partial mocks | `spyk(real)` |
| argument capture | `slot<T>()`, `mutableListOf<T>()` with `capture(list)` |
| ordering | `verifyOrder { }`, `verifySequence { }` |
| cleanup | `clearAllMocks()` / `unmockkAll()` in `afterTest` |

Prefer fakes (small in-memory implementations of an interface) for repositories and clocks;
mocks for verifying interactions at boundaries. Over-mocked tests that mirror implementation
calls break on every refactor.

## 5. kotlin.test and JUnit 5

- `kotlin("test")` maps to JUnit 5 on JVM (`kotlin-test-junit5`) and to native/JS runners in KMP;
  annotations `@Test`, `@BeforeTest`, assertions `assertEquals`, `assertFailsWith<T> { }`,
  `assertIs<T>()`.
- Backtick test names (`` fun `rejects negative amounts`() ``) work on JVM; KMP native targets
  have restrictions on some characters: keep names simple in `commonTest`.

## 6. Static analysis

| Tool | Gradle | Notes |
|---|---|---|
| detekt | `io.gitlab.arturbosch.detekt` plugin, `./gradlew detekt` | baseline file for legacy code; enable `UnsafeCallOnNullableType`, `TooGenericExceptionCaught`, `GlobalCoroutineUsage`, `SuspendFunWithFlowReturnType` (coroutines rule set) |
| ktlint | `org.jlleitschuh.gradle.ktlint` or Spotless | style; `.editorconfig` driven |
| ktfmt | Spotless `ktfmt()` | deterministic Google-style formatting |
| Android Lint | AGP `lint` | includes Compose and coroutine checks |
| compiler unused-return checker | 2.3+ experimental flag | catches ignored results of pure functions |
