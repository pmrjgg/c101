---
name: kotlin-java-interop
description: "Kotlin-Java interoperability. Covers platform types and JSpecify nullness, exposing Kotlin APIs to Java with the @Jvm* annotations, value-class name mangling and @JvmExposeBoxed, suspend functions as CompletableFuture, collection views, Spring and JPA compiler plugins on Spring Boot 4, Lombok interop and removal, and incremental Java-to-Kotlin migration with ABI checks. Load for mixed Kotlin/Java codebases or Kotlin on Spring."
when_to_use: "Mixed src/main/java + src/main/kotlin modules, Java callers of a Kotlin library, J2K conversions, Spring/JPA entities in Kotlin, lombok.config; errors such as 'getName(...) must not be null', 'Platform declaration clash', 'exception IOException is never thrown in body of corresponding try statement', JSpecify nullability mismatch errors after a Kotlin or Spring Boot 4 upgrade, Unresolved reference to Lombok getters, final-class proxy failures, mangled names like foo-abc123 or foo$module."
---

# Kotlin and Java interop

Baseline (October 2026): Kotlin 2.4.x, JSpecify 1.0, Spring Boot 4.1 / Framework 7.0 (Kotlin 2.2+
baseline, JSpecify nullness, Jackson 3, JUnit 6), kotlinx.coroutines 1.11. Inspect what Java really sees
with `javap -cp build/classes/kotlin/main com.acme.Foo` before and after every API change.

Deep material: [what Java sees](references/what-java-sees.md) (construct-by-construct matrix, bytecode
names) | [migration checklists](references/migration-checklists.md) (J2K review, Lombok removal, ABI tooling).

## 1. Calling Java from Kotlin

| Java declaration | Kotlin type | Action |
|---|---|---|
| unannotated `String getName()` | `String!` (platform: `String` or `String?`) | declare the type at the boundary: `val name: String? = user.name` |
| inside `@NullMarked` (JSpecify) | `String` | trust it |
| `@Nullable` (JSpecify, JetBrains, AndroidX, JSR-305, Jakarta...) | `String?` | handle null |
| `List<String> getTags()` | `(Mutable)List<String!>!` | copy at the boundary: `user.tags?.toList().orEmpty()` |
| `java.lang.Integer` / `int[]` / `String[]` | `Int?` / `IntArray` / `Array<(out) String!>` | Java varargs need the spread: `f(*array)` |

Assigning a null platform value to a non-null Kotlin type fails at that line with
`NullPointerException: getName(...) must not be null`, far from the Java code that produced it.

JSpecify handling:
- Annotate Java with `@NullMarked` on the package (`package-info.java`) or class, `@Nullable` on the
  exceptions, `@NullUnmarked` to opt a scope back out, `<T extends @Nullable Object>` for nullable type args.
- Since Kotlin 2.1 JSpecify mismatches are errors by default (it is the only flavour strict by default).
  Downgrade during a migration with `-Xjspecify-annotations=warn` (or
  `-Xnullability-annotations=@org.jspecify.annotations:warn`), then remove the flag.
- JSR-305 annotations default to warnings; `-Xjsr305=strict` enforces them (Spring 6 / Boot 3 era).
  Kotlin 2.4 turns `jakarta.annotation.Nullable/Nonnull` mismatches into errors as well.

Other rules:
- SAM conversion works for Java interfaces with one abstract method: `executor.execute { work() }`,
  `Comparator<User> { a, b -> a.age - b.age }`; never for abstract classes.
- Getters/setters become properties (`user.name`, `user.name = "x"`); an `isActive()`/`setActive()` pair
  becomes `user.isActive`; a setter without a getter is not a property.
- Java `void` returns `Unit`; checked exceptions are unchecked in Kotlin, so catch the ones that matter.
- Java `static` members are called as `JavaClass.member` (no companion involved).
- Java identifiers that are Kotlin keywords need backticks: `` Mockito.`when`(repo.find(1)) ``.

## 2. Exposing Kotlin to Java

| Kotlin | Java sees by default | Fix |
|---|---|---|
| default arguments | one method with every parameter | `@JvmOverloads` (functions and `class C @JvmOverloads constructor(...)`); drops trailing defaulted params one at a time; not allowed on abstract or interface methods |
| companion function | `C.Companion.create()` | `@JvmStatic` (static method plus companion instance method) |
| companion constant | `C.Companion.getMAX()` | `const val` (primitives, String) or `@JvmField` -> static field |
| property | `getX()`/`setX()`, `isX()` for `isX` | `@JvmField` (not private/open/override/const/delegated), `@get:JvmName("x")` |
| top-level functions in `Strings.kt` | `StringsKt.slug()` | `@file:JvmName("Strings")`; `@file:JvmMultifileClass` to merge files into one facade |
| erased signature clash | compile error "Platform declaration clash" | `@JvmName("filterValidInt") fun List<Int>.filterValid()` |
| thrown checked exception | not declared, Java `catch` fails to compile | `@Throws(IOException::class)` |
| `data class` | getters, `equals`, `copy(all params)` | `@JvmRecord data class` for a real record (JVM 16+ target, no superclass, only constructor-backed fields; not binary compatible to add later) |
| `object Registry` | `Registry.INSTANCE.lookup()` | `@JvmStatic` on members |
| `internal fun recompute()` | public `recompute$<module>` | never rely on `internal` to hide from Java; names change when the module is renamed |
| `(A) -> Unit` parameter | `Function1<A, Unit>`, Java must `return Unit.INSTANCE` | declare a `fun interface` |
| `fun fail(): Nothing` | returns `Void` | |
| `fun f(xs: List<Animal>)` with open `Animal` | `List<? extends Animal>` | `@JvmSuppressWildcards` (frameworks needing exact types); `@JvmWildcard` forces one |
| Kotlin-only API (suspend, inline, reified) | callable or confusing | `@JvmSynthetic` hides a member from Java sources |
| interface method with a body | Java default method (Kotlin 2.2+ default `-jvm-default=enable`, plus `DefaultImpls` bridges) | `compilerOptions { jvmDefault = JvmDefaultMode.NO_COMPATIBILITY }` for new libraries without old Kotlin clients |

## 3. Value classes

```kotlin
@JvmInline value class AccountId(val raw: String)

fun close(id: AccountId) { }                                     // bytecode close-<hash>(String): Java cannot call it
@JvmName("reopenAccount") fun reopen(id: AccountId) { }          // unmangled: Java calls reopenAccount(String)

@OptIn(ExperimentalStdlibApi::class)
@JvmExposeBoxed                                                   // Kotlin 2.2+: also emits suspendAccount(AccountId)
fun suspendAccount(id: AccountId) { }
```

- Functions taking value classes and getters of value-class properties get a hyphenated hash suffix
  (`close-<hashcode>`; a `kotlin.time.Duration` property becomes `getTimeout-<hashcode>()`), which no Java
  source can call; Java cannot call the value class's own constructor or constructors taking it either.
- Fixes, in order: keep value classes out of Java-facing signatures (take `String`, convert inside);
  `@JvmName` per function (Java passes the raw underlying value, so validation must not live only in the
  value-class `init`); `@JvmExposeBoxed` (experimental since 2.2, opt-in `ExperimentalStdlibApi`) on a
  function, constructor or class, which also gives Java a public constructor that runs `init`;
  `-Xjvm-expose-boxed` applies it to a whole module; inherited functions need an override to get a boxed
  variant.
- Boxing happens whenever the value is used as another type: generic (`List<AccountId>`, `T`), nullable
  (`AccountId?`) or interface. Java code holding a `List<AccountId>` holds wrapper objects; unchecked
  casts that put raw `String`s in end in `ClassCastException`. Avoid value classes in hot generic code.
- Framework binding of value classes is limited (Spring property binding cannot use a value class
  default; check Jackson/kotlinx.serialization support for the version in use).

## 4. Coroutines for Java callers

| Kotlin shape | Java-facing shape |
|---|---|
| `suspend fun load(id): T` | `fun loadAsync(id): CompletableFuture<T> = scope.future { load(id) }` |
| `Flow<T>` | `flow.asPublisher()` (kotlinx-coroutines-reactive) or `flow.asFlux()` (kotlinx-coroutines-reactor) |
| fire-and-forget work | `CompletableFuture<Unit>` from `future { }`, never a leaked `launch` |

- `future { }` lives in kotlinx-coroutines-core (`kotlinx.coroutines.future`). Cancelling or completing
  the returned future cancels the coroutine; failures surface as `ExecutionException` from `get()`;
  `CoroutineStart.LAZY` throws `IllegalArgumentException`.
- `future` behaves like `async`: in a scope with a plain `Job`, one failed call cancels the scope and every
  later call. Back Java-facing futures with `CoroutineScope(SupervisorJob() + Dispatchers.IO)` and cancel
  it in `close()`.
- Kotlin consuming Java futures: `future.await()` suspends and cancels the future when the coroutine is
  cancelled; `future.asDeferred().await()` waits without cancelling it.
- Blocking wrappers (`fun loadBlocking() = runBlocking { load() }`) only for Java callers on their own
  threads: never from a coroutine, a `Dispatchers.Default` worker (pool starvation) or a UI thread; name
  them `...Blocking`. Prefer returning the future and letting Java decide (`get(5, SECONDS)`).
- Wrap blocking Java calls invoked from coroutines in `runInterruptible(Dispatchers.IO) { legacy.call() }`
  so cancellation interrupts them.

## 5. Collections across the boundary

| Java | Kotlin read-only | Kotlin mutable | Loaded from Java as |
|---|---|---|---|
| `java.util.List<T>` | `List<T>` | `MutableList<T>` | `(Mutable)List<T>!` |
| `Set`, `Collection`, `Iterable`, `Iterator`, `Map`, `Map.Entry` | same names | `Mutable...` | `(Mutable)...!` |

Read-only is a compile-time view: every Kotlin `List` is a `java.util.List`, and what a Java `add()` does
depends on the runtime class (an implementation detail; never rely on it):

| Kotlin expression | Runtime class today | Java `add` |
|---|---|---|
| `emptyList()`, `listOf()` | `kotlin.collections.EmptyList` | `UnsupportedOperationException` |
| `listOf(x)` | `Collections.singletonList` | throws |
| `listOf(a, b)` | array-backed `Arrays.asList` | throws (`set` succeeds) |
| `mutableListOf()`, `map { }`, `filter { }`, `toList()` with 2+ elements | `java.util.ArrayList` | succeeds and mutates your "read-only" list |

Rules: return `items.toList()` (a copy) or `Collections.unmodifiableList(items)` from Java-facing APIs; copy
Java-provided collections on entry (`javaList.toList()`) because the caller may keep mutating them;
validate elements (`requireNoNulls()`), since Java can put nulls into a `List<String>`; use
kotlinx.collections.immutable when immutability is part of the contract.

## 6. Spring with Kotlin

```kotlin
plugins {
    kotlin("jvm") version "2.4.21"
    kotlin("plugin.spring") version "2.4.21"      // all-open: @Component (+ meta: @Service, @Configuration...), @Async, @Transactional, @Cacheable, @SpringBootTest
    kotlin("plugin.jpa") version "2.4.21"         // synthetic no-arg constructor for @Entity, @Embeddable, @MappedSuperclass
    id("org.springframework.boot") version "4.1.1"
}
allOpen {                                         // entities must be open for lazy proxies
    annotation("jakarta.persistence.Entity")
    annotation("jakarta.persistence.MappedSuperclass")
    annotation("jakarta.persistence.Embeddable")
}
dependencies {
    implementation("org.jetbrains.kotlin:kotlin-reflect")                  // required by Spring's Kotlin support
    implementation("tools.jackson.module:jackson-module-kotlin")           // Jackson 3 (Boot 4); com.fasterxml.jackson.module on Boot 3
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-reactor")    // suspend handlers, Flow responses
    testImplementation("com.ninja-squad:springmockk:<version>")           // @MockkBean / @SpykBean
}
// Kotlin 2.2/2.3 only (default since 2.4): kotlin.compilerOptions.freeCompilerArgs.add("-Xannotation-default-target=param-property")
```

- Constructor injection: one primary constructor with `private val` dependencies, no `@Autowired`;
  `lateinit var` only for injected test fields. `@ConfigurationProperties("acme.rates") data class
  RatesProperties(val url: URI, val ttl: Duration)` binds through the constructor.
- Boot 4 nullness: Spring APIs carry JSpecify annotations, so Kotlin sees exact types
  (`jdbc.queryForObject(...)` returns `T?`); upgrade errors are real nullability bugs. Boot 3 relied on
  JSR-305 meta-annotations plus `-Xjsr305=strict`.
- Annotations on constructor properties: Kotlin 2.4 applies an unqualified annotation to the parameter and
  the property, or the field when `property` does not apply (always the case for Java annotations such as
  `@NotBlank`); before 2.4 only the parameter got it, so write `@field:NotBlank` or use the flag above, or
  Bean Validation silently skips the check.
- Coroutines: `suspend fun` handlers and `Flow<T>` return values work in MVC and WebFlux controllers with
  kotlinx-coroutines-reactor on the classpath; `coRouter { }` for functional routes;
  `TransactionalOperator.executeAndAwait { }` for reactive transactions. JPA transactions and persistence
  contexts are thread-bound: keep `@Transactional` JPA services non-suspending and call them from
  coroutines through `withContext(Dispatchers.IO)`.

## 7. JPA entities in Kotlin

| Rule | Reason |
|---|---|
| a regular `class`, never `data class` | data-class `equals`/`hashCode` span mutable fields and lazy associations, `toString` triggers lazy loading, `copy` makes detached twins |
| open (allOpen as above) | Hibernate proxies subclass the entity; final entities lose lazy to-one loading |
| generated id: `var id: Long? = null` with `protected set` | null means "new"; `lateinit` is illegal on `Long` and throws before persist; all-open makes properties open and open properties cannot have `private set` |
| assigned id (`val id: UUID = UUID.randomUUID()`) | add `@Version var version: Long? = null` or implement `Persistable`, or Spring Data `save()` merges with an extra SELECT |
| `equals` on id with proxy-aware class check, constant `hashCode` per class | stable across persist and flush, safe in `HashSet` |
| `toString` with id and simple columns only | no lazy loading in logs |

```kotlin
@Entity @Table(name = "orders")
class Order(
    @Column(nullable = false) var customerId: String,
    @Enumerated(EnumType.STRING) var status: Status = Status.NEW,
) {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    var id: Long? = null
        protected set

    final override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other == null || effectiveClass(this) != effectiveClass(other)) return false
        return id != null && id == (other as Order).id
    }
    final override fun hashCode(): Int = effectiveClass(this).hashCode()
    override fun toString() = "Order(id=$id, status=$status)"
}

fun effectiveClass(o: Any): Class<*> =
    if (o is HibernateProxy) o.hibernateLazyInitializer.persistentClass else o.javaClass   // no proxy initialisation
```

## 8. Lombok in mixed modules

Kotlin compiles before javac and reads Java sources directly, so it cannot see members Lombok will
generate: Kotlin code calling `getName()` on a `@Getter` class in the same module fails with an unresolved
reference. The Kotlin Lombok plugin teaches kotlinc those members (other modules see compiled bytecode and
need nothing).

```kotlin
plugins {
    kotlin("plugin.lombok") version "2.4.21"
    id("io.freefair.lombok") version "9.5.0"        // or compileOnly + annotationProcessor org.projectlombok:lombok
}
kotlinLombok { lombokConfigurationFile(file("lombok.config")) }   // only if the module has one
```

Supported: `@Getter`, `@Setter`, `@Builder`, `@SuperBuilder`, `@NoArgsConstructor`,
`@RequiredArgsConstructor`, `@AllArgsConstructor`, `@Data`, `@With`, `@Value`. Not `@Tolerate`. Lombok
annotations written in Kotlin files are ignored. With kapt set `kapt { keepJavacAnnotationProcessors = true }`.

Removing Lombok step by step: inventory annotations per package; delombok the classes about to convert
(`java -jar lombok.jar delombok src/main/java/com/acme/billing -d build/delombok`, or IntelliJ Refactor |
Delombok) so J2K sees real code; convert leaf classes using the mapping in
[migration checklists](references/migration-checklists.md) (`@Value` to a `data class`, `@Builder` to named and
default arguments plus `@JvmOverloads` or a kept builder for Java callers, `@Slf4j` to a logger property,
`@SneakyThrows` deleted but `@Throws` added for Java callers); drop the plugins and `lombok.config` with the
last annotated class.

## 9. Migration strategy

1. Order: tests and leaf classes (no Java dependents) first, then inward; one package per PR. Mixed
   source sets compile in both directions, so partial migrations are fine.
2. Freeze the Java-facing API before converting: `./gradlew apiDump` (binary-compatibility-validator,
   maintenance mode) or KGP `kotlin { abiValidation() }` with `updateKotlinAbi` (2.4 task names;
   2.2 used `updateLegacyAbi`/`checkLegacyAbi`). Commit the dump.
3. Convert with Code | Convert Java File to Kotlin File (Ctrl+Alt+Shift+K, Cmd+Alt+Shift+K on macOS).
4. Review the J2K output (full list in the reference):
   - every `!!` and platform-typed field gets a deliberate nullability decision;
   - statics became companion members: add `@JvmStatic`/`@JvmField`/`const` for Java callers;
   - overloads collapsed into default arguments: add `@JvmOverloads` or keep explicit overloads;
   - thrown checked exceptions that Java catches: `@Throws`;
   - `MutableList` vs `List` chosen on purpose; getters became properties (check `isX` boolean names);
   - `equals`/`hashCode`/`toString` kept or replaced by a `data class` only for value types (not entities);
   - `synchronized` blocks, `Optional`, streams and static nested vs inner classes translated correctly.
5. Compile the Java callers and run `./gradlew apiCheck` (or `checkKotlinAbi`, which `check` runs): the
   diff must be empty or explicitly approved. For released libraries also compare against the last release
   jar with japicmp. Add new default parameters with `@IntroducedAt("1.4")` (Kotlin 2.3+, not combinable
   with `@JvmOverloads`) to keep old binaries linking.

## 10. Worked example: a Java-friendly Kotlin service

```kotlin
package com.acme.rates
// imports: java.time.{Clock, Duration, Instant} (not kotlin.time), java.math.{BigDecimal, RoundingMode},
// java.io.IOException, java.util.concurrent.*, kotlinx.coroutines.*, kotlinx.coroutines.future.future

fun interface RateSource {
    @Throws(IOException::class)                       // lets Java lambdas throw IOException
    fun fetch(currency: String): BigDecimal
}

class RateService @JvmOverloads constructor(
    private val source: RateSource,
    private val ttl: Duration = DEFAULT_TTL,          // java.time.Duration: Java-friendly
    private val clock: Clock = Clock.systemUTC(),
) : AutoCloseable {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO + CoroutineName("rates"))
    private val cache = ConcurrentHashMap<String, Pair<BigDecimal, Instant>>()

    @JvmSynthetic                                     // Kotlin API; Java uses rateAsync
    suspend fun rate(currency: String): BigDecimal {
        require(currency.length == CURRENCY_CODE_LENGTH) { "ISO 4217 code expected: $currency" }
        cache[currency]?.let { (value, at) -> if (Duration.between(at, clock.instant()) < ttl) return value }
        val fresh = runInterruptible(Dispatchers.IO) { source.fetch(currency) }
        cache[currency] = fresh to clock.instant()
        return fresh
    }

    fun rateAsync(currency: String): CompletableFuture<BigDecimal> = scope.future { rate(currency) }

    @JvmOverloads
    fun convertAsync(amount: BigDecimal, currency: String, scale: Int = 2): CompletableFuture<BigDecimal> =
        scope.future { (amount * rate(currency)).setScale(scale, RoundingMode.HALF_EVEN) }

    override fun close() = scope.cancel()              // cancels in-flight futures

    companion object {
        @JvmField val DEFAULT_TTL: Duration = Duration.ofMinutes(5)
        const val CURRENCY_CODE_LENGTH = 3
        @JvmStatic fun fixed(rate: BigDecimal): RateService = RateService(RateSource { rate })
    }
}
```

```java
// src/test/java/com/acme/rates/RateServiceJavaTest.java: compiles only if the API is Java-friendly
// imports: org.junit.jupiter.api.Test, static org.junit.jupiter.api.Assertions.*, java.io.IOException,
// java.math.BigDecimal, java.time.Duration, java.util.concurrent.*, java.util.concurrent.atomic.AtomicInteger
class RateServiceJavaTest {
    @Test
    void javaSeesPlainOverloadsStaticsAndFutures() throws Exception {
        RateSource source = currency -> new BigDecimal("1.25");             // fun interface as a lambda
        try (RateService service = new RateService(source)) {               // @JvmOverloads constructor
            assertEquals(new BigDecimal("1.25"), service.rateAsync("EUR").get(1, TimeUnit.SECONDS));
            assertEquals(new BigDecimal("12.50"),                           // overload without scale
                service.convertAsync(BigDecimal.TEN, "EUR").get(1, TimeUnit.SECONDS));
        }
        assertEquals(Duration.ofMinutes(5), RateService.DEFAULT_TTL);       // @JvmField
        assertEquals(3, RateService.CURRENCY_CODE_LENGTH);                  // const val
        try (RateService fixed = RateService.fixed(BigDecimal.ONE)) {       // @JvmStatic
            assertEquals(BigDecimal.ONE, fixed.rateAsync("USD").join());
        }
    }

    @Test
    void failuresArriveAsCausesAndTheServiceSurvives() throws Exception {
        AtomicInteger calls = new AtomicInteger();
        RateSource flaky = currency -> {                                    // throwing IOException is legal
            if (calls.getAndIncrement() == 0) throw new IOException("rates down");   // thanks to @Throws
            return new BigDecimal("1.25");
        };
        try (RateService service = new RateService(flaky, Duration.ofSeconds(1))) {
            ExecutionException e = assertThrows(ExecutionException.class,
                () -> service.rateAsync("EUR").get(1, TimeUnit.SECONDS));
            assertInstanceOf(IOException.class, e.getCause());
            assertEquals(new BigDecimal("1.25"), service.rateAsync("EUR").get(1, TimeUnit.SECONDS));
        }
    }
}
```

```bash
./gradlew test --tests 'com.acme.rates.RateServiceJavaTest'   # Java test sources compile against Kotlin main
./gradlew apiDump && git diff api/                             # review: 3 constructors, 2 convertAsync, static fixed
```

Each annotation is load-bearing: without `@JvmOverloads` the `new RateService(source)` line does not
compile; without `@JvmStatic` Java must write `RateService.Companion.fixed(...)`; without `@Throws` the
lambda fails with "unreported exception IOException"; without `SupervisorJob` the second test's failure
would cancel the scope and the second `rateAsync` would fail too; `@JvmSynthetic` keeps the
`Continuation`-taking `rate` invisible to Java sources.

## Pitfalls

- A `List<T>` returned to Java gets mutated by the caller; return copies or unmodifiable views.
- `@JvmOverloads` only drops trailing parameters; put defaulted parameters last or overloads are missing.
- Adding a default parameter changes the JVM signature and breaks compiled Java callers; use `@IntroducedAt`
  or keep the old overload.
- `const val` values are inlined into Java callers at compile time; changing them needs Java recompiles.
- Heavy `object`/`companion` initialisers run on first access from Java too (class initialisation, often on a
  request thread); keep them cheap and side-effect free.
- A value class in a public signature silently removes that function from the Java API.
- `-Xjspecify-annotations=warn` left in the build hides real nullability bugs; remove it after migrating.
- `runBlocking` in a Java-facing method called from a WebFlux event loop or a coroutine thread blocks that
  thread and can deadlock; expose the future instead.
- `data class` entities with `@OneToMany` recurse in `hashCode`/`toString` (StackOverflowError) and load
  collections lazily in logs.
- `open` entities with `private set` fail to compile under all-open; use `protected set`.

Related: `kotlin-coroutines-flow` (scopes and cancellation behind the futures), `kotlin-testing`,
`kotlin-gradle-builds` (compiler flags, ABI validation setup), `java-craft`, `java-modern-language`,
`refactoring-playbook`; hub `kotlin-craft`.
