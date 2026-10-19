# Kotest cookbook (Kotest 6.x)

Companion to `kotlin-testing`. Kotest 6.2 is current (October 2026); 6.0 needs JDK 11+ and Kotlin 2.2+.

## 1. Spec styles side by side

```kotlin
class CartFunSpec : FunSpec({
    context("an empty cart") {
        test("has zero total") { Cart().total() shouldBe Money.ZERO }
    }
})

class CartStringSpec : StringSpec({
    "an empty cart has zero total" { Cart().total() shouldBe Money.ZERO }
})

class CartBehaviorSpec : BehaviorSpec({
    Given("a cart with one book") {
        val cart = Cart().apply { add(book) }
        When("the book is removed") {
            cart.remove(book.sku)
            Then("the total is zero") { cart.total() shouldBe Money.ZERO }
        }
    }
})

class CartDescribeSpec : DescribeSpec({
    describe("Cart.total") {
        it("is zero when empty") { Cart().total() shouldBe Money.ZERO }
    }
})
```

Under the default `SingleInstance` isolation, `val cart` inside `Given` is shared by every nested
`When`/`Then`; mutate it only in one leaf, or switch the spec to `IsolationMode.InstancePerRoot`.

## 2. Data-driven tests (6.1+ per-style functions)

| Spec style | Container variants | Leaf variants |
|---|---|---|
| `FunSpec` | `withContexts` | `withTests` |
| `StringSpec` | | `withData` |
| `DescribeSpec` | `withContexts`, `withDescribes` | `withIts` |
| `ShouldSpec` | `withContexts` | `withShoulds` |
| `WordSpec` | `withWhens`, `withShoulds` | |
| `BehaviorSpec` | `withContexts`, `withGivens`, `withWhens`, `withAnds` (inside given) | `withThens` |
| `FreeSpec` | `withContexts` | `withTests` |
| `ExpectSpec` | `withContexts` | `withExpects` |
| `FeatureSpec` | `withFeatures` | `withScenarios` |

The older single `withData` still works and maps onto these. Data tests nest inside containers (and
inside other data tests) but never inside a leaf; on Native and JS the innermost level must be a leaf
variant.

```kotlin
data class Conversion(val celsius: Int, val fahrenheit: Int)

class TemperatureSpec : FunSpec({
    context("celsius to fahrenheit") {
        withTests(Conversion(0, 32), Conversion(100, 212), Conversion(-40, -40)) { (c, f) ->
            cToF(c) shouldBe f
        }
    }
})
```

Test names: the row's `toString()` when Kotest considers the type stable (data classes, primitives,
strings), otherwise the class name. Options, in order of preference:
- implement `WithDataTestName` and return a label from `dataTestName()`;
- pass `nameFn = { row -> "..." }` (add the type parameter if inference fails);
- pass a `mapOf("freezing" to Conversion(0, 32), ...)` whose keys are the names;
- annotate the row type with `@IsStableType` to force `toString()`.
Names must be stable across a run, or the IDE and reports lose track of tests.

## 3. Matchers that matter

| Area | Matchers |
|---|---|
| general | `shouldBe`, `shouldNotBe`, `shouldBeNull()`, `shouldNotBeNull()`, `shouldBeInstanceOf<T>()` |
| comparables | `shouldBeLessThan`, `shouldBeLessThanOrEqualTo`, `shouldBeGreaterThan`, `shouldBeGreaterThanOrEqualTo`, `shouldBeEqualComparingTo`, `shouldBeBetween` |
| BigDecimal | `shouldBeEqualIgnoringScale`, `shouldHaveScale`, `shouldHavePrecision`, `shouldBePositive`, `shouldBeZero`, `shouldBeInRange` |
| exceptions | `shouldThrow<T> { }`, `shouldThrowExactly<T> { }`, `shouldThrowAny { }`, `shouldThrowMessage(msg) { }` |
| collections | `shouldContainExactly`, `shouldContainExactlyInAnyOrder`, `shouldContain`, `shouldHaveSize` |
| grouping | `assertSoftly { }` (all failures), `withClue("order 42") { }` (context in the message) |

Kotlin 2.2+ power-assert (`kotlin("plugin.power-assert")`, experimental) prints every sub-expression of
a failing assertion; Kotest 6 integrates it with `shouldBe`. For kotlin.test add the functions:
`powerAssert { functions = listOf("kotlin.assert", "kotlin.test.assertTrue", "kotlin.test.assertEquals") }`.

## 4. Nondeterministic helpers (real time)

```kotlin
val config = eventuallyConfig {
    duration = 5.seconds
    interval = 100.milliseconds
    initialDelay = 50.milliseconds
    expectedExceptions = setOf(AssertionError::class)   // anything else fails immediately
}
eventually(config) { mailbox.messages() shouldHaveSize 1 }
```

Also available under "Non-deterministic testing": `continually` (must keep passing for a period),
`until`, `retry`. All of them wait on the wall clock; under `coroutineTestScope = true` drive time with
`testCoroutineScheduler` instead.

## 5. Property testing details

Generators: `Arb.int(range)`, `Arb.long(range)`, `Arb.double()`, `Arb.string(range, codepoints)`,
`Arb.list(arb, sizeRange)`, `Arb.set(...)`, `Arb.enum<T>()`, `Arb.uuid()`, `Arb.element(list)`,
`Arb.choice(arbA, arbB)`, `Arb.bind(arbA, arbB) { a, b -> T(a, b) }`, `arbitrary { T(x.bind(), y.bind()) }`,
exhaustive `Exhaustive.collection(list)`, `Exhaustive.enum<T>()`, `Exhaustive.boolean()`.
Codepoint sets: `ascii()`, `printableAscii()`, `alphanumeric()`, `az()`, `hex()`, `whitespace()`, plus
script sets (`cyrillic()`, `greekCoptic()`, `hebrew()`, `arabic()`, `hiragana()`, `katakana()`, ...).

`PropTestConfig` fields (defaults from `PropertyTesting`): `seed` (null = random), `minSuccess`
(`Int.MAX_VALUE`), `maxFailure` (0), `shrinkingMode` (`Bounded(1000)`), `iterations` (null = 1000),
`listeners`, `edgeConfig` (edge-case probability 0.02), `maxDiscardPercentage` (20),
`outputClassifications`, `outputHexForUnprintableChars`.

System properties (set them on the Gradle `Test` task with `systemProperty(...)`):

| Property | Default | Effect |
|---|---|---|
| `kotest.proptest.default.iteration.count` | 1000 | iterations per property |
| `kotest.proptest.default.seed` | unset | fixed seed for every property |
| `kotest.proptest.default.shrinking.bound` | 1000 | shrink steps |
| `kotest.proptest.arb.edgecases-generation-probability` | 0.02 | share of edge cases |
| `kotest.proptest.output.generated-values` | false | print each generated input |
| `kotest.proptest.output.shrink-steps` | version-dependent | print each shrink step, not only the final value |
| `kotest.proptest.seed.write-failed` | true | persist failing seeds under `~/.kotest/seeds/` |
| `kotest.proptest.seed.fail-if-set` | false | fail properties that pin a seed (turn on in CI) |

Workflow for a failure: read the shrunk counterexample, add it as an ordinary example test, fix the
code, and keep the property. Pinning `seed = ...` is for local debugging only.

## 6. Project and package config

```kotlin
package io.kotest.provided                                   // the only location Kotest 6 looks at

class ProjectConfig : AbstractProjectConfig() {
    override val isolationMode = IsolationMode.InstancePerRoot
    override val coroutineTestScope = true                   // virtual time for every test
    override val extensions = listOf(DatabaseExtension)       // a val since 6.0
}
```

- Use another class name only with `-Dkotest.framework.config.fqn=com.acme.TestConfig`.
- `AbstractPackageConfig` subclasses share settings with a package and its sub-packages; resolution
  goes test, spec, package, parent package, global. `DefaultTestConfig` sets spec-wide defaults
  (timeout, invocations, tags).
- Spec and test concurrency modes: `Sequential` (default), `Concurrent`, `LimitedConcurrency(max)`.
  Concurrent specs and `mockkObject`/`setMain` do not mix.
- `CoroutineDebugProbeInterceptor` (6.0) installs kotlinx debug probes for selected tests.

## 7. Running

```bash
./gradlew test --tests 'com.acme.cart.CartFunSpec'      # one spec
./gradlew test --tests 'com.acme.cart.*' --rerun-tasks     # a package, ignoring the up-to-date check
```

System properties passed to Gradle do not reach the test JVM by themselves; forward them:
`tasks.test { systemProperty("kotest.proptest.default.iteration.count", providers.gradleProperty("ptIterations").getOrElse("1000")) }`.
Kotest 6.1.9 fixed single-test `--tests` filtering on Gradle 9.4; upgrade if IDE runs of one test execute the whole spec.
