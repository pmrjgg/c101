---
name: java-testing-junit
description: "Java test engineering. Covers JUnit 5/6 Jupiter features, AssertJ fluent assertions, Mockito on JDK 21+, Testcontainers, WireMock, Awaitility, ArchUnit architecture rules, jqwik properties, PIT mutation testing, JaCoCo thresholds and flaky-test triage. Load when writing or restructuring Java tests, or stabilizing a flaky suite."
when_to_use: "Writing or reviewing *Test.java or *IT.java files; @ParameterizedTest, @Nested or junit-platform.properties changes; Mockito self-attaching agent warnings or UnnecessaryStubbingException; Testcontainers start-up cost or Docker errors; WireMock stubs; Thread.sleep in tests; ArchUnit layering rules; jqwik or PIT setup; JaCoCo coverage gates; tests that fail only in CI, in parallel or in another order."
---

# Java testing with JUnit, AssertJ and friends

JUnit 5.x and JUnit 6 (September 2025) share the Jupiter API (`org.junit.jupiter.api`). JUnit 6
requires Java 17, gives Platform, Jupiter and Vintage one version number, deprecates Vintage and
ships JSpecify nullness annotations. Spring Boot 4 manages JUnit 6, Boot 3.x manages 5.x; import
`org.junit:junit-bom` either way and never mix Platform and Jupiter versions. Unit tests are
`*Test` (Surefire / Gradle `test`), container and HTTP tests `*IT` (Failsafe / an
`integrationTest` suite), wired as in `java-build-maven-gradle`. Copy-ready Maven/Gradle wiring
for Mockito, PIT, JaCoCo and test-retry: [tooling snippets](references/tooling-snippets.md).

## 1. Jupiter features

```java
class FeeCalculatorTest {
    private final FeeCalculator calc = new FeeCalculator(FeeTable.standard());
    @ParameterizedTest(name = "[{index}] {0} {1} -> {2}")
    @CsvSource(textBlock = """
        CARD, 100.00, 2.90
        SEPA, 100.00, 0.35
        CARD,   0.01, 0.30
        """)
    void computesFee(Method method, BigDecimal amount, BigDecimal expected) {
        assertThat(calc.fee(method, amount)).isEqualByComparingTo(expected);
    }
    @ParameterizedTest
    @EnumSource(value = Method.class, names = {"CARD", "SEPA"}, mode = EnumSource.Mode.EXCLUDE)
    void otherMethodsAreFree(Method method) {
        assertThat(calc.fee(method, new BigDecimal("50"))).isEqualByComparingTo("0");
    }
    static Stream<Arguments> refunds() { return Stream.of(arguments("100.00", "30.00", "70.00")); }
    @ParameterizedTest @MethodSource("refunds")
    void remainingAfterRefund(BigDecimal paid, BigDecimal refund, BigDecimal remaining) { /* ... */ }
    @Nested class WhenCurrencyDiffers {                      // non-static inner class
        @Test void convertsBeforeApplyingFee() { /* ... */ }
    }
    @TestFactory                                              // one dynamic test per fixture file
    Stream<DynamicTest> everyWebhookFixtureParses() throws IOException {
        return Files.list(Path.of("src/test/resources/webhooks"))
            .map(p -> dynamicTest(p.getFileName().toString(), () -> assertThat(Webhook.parse(p)).isNotNull()));
    }

    @Test @Tag("slow") @Timeout(value = 5, threadMode = Timeout.ThreadMode.SEPARATE_THREAD)
    void settlesLargeBatch() { /* ... */ }
}
```

| Data shape | Source |
|---|---|
| scalar rows | `@CsvSource(textBlock = ...)`, `@CsvFileSource` |
| enum constants | `@EnumSource` (with `names`/`mode`) |
| objects, builders, many columns | `@MethodSource`, `@FieldSource` (5.11+) |
| null and empty edge cases | `@NullAndEmptySource` + `@ValueSource` |
| same tests for several configurations | `@ParameterizedClass` (5.13+) |

Tags: Surefire `-Dgroups=fast` / `-DexcludedGroups=slow`; Gradle `useJUnitPlatform { excludeTags("slow") }`.
Extensions: `@ExtendWith` for stateless ones, static `@RegisterExtension` fields when they need
configuration; `@TempDir Path dir`; `@AutoClose` (5.11+). Parallel execution in
`src/test/resources/junit-platform.properties` (classes in parallel, methods of a class
sequential: the safe starting point):

```properties
junit.jupiter.execution.parallel.enabled=true
junit.jupiter.execution.parallel.mode.default=same_thread
junit.jupiter.execution.parallel.mode.classes.default=concurrent
junit.jupiter.execution.parallel.config.strategy=dynamic
junit.jupiter.execution.parallel.config.dynamic.factor=1
junit.jupiter.execution.timeout.default=60s
```

Guard shared resources with `@ResourceLock("payments-db")`; `@Isolated` for tests that touch
global state (system properties, default `TimeZone`/`Locale`).

## 2. AssertJ

```java
assertThat(payments)
    .extracting(Payment::orderId, Payment::status)
    .containsExactlyInAnyOrder(tuple("o-1", CAPTURED), tuple("o-2", REFUNDED));

assertThat(actual).usingRecursiveComparison()
    .ignoringFields("id", "createdAt")
    .withComparatorForType(BigDecimal::compareTo, BigDecimal.class)   // 2.9 == 2.90
    .isEqualTo(expected);

assertThatThrownBy(() -> service.refund(id, Money.eur("-1")))
    .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("amount");

SoftAssertions.assertSoftly(softly -> {
    softly.assertThat(receipt.status()).isEqualTo(CAPTURED);
    softly.assertThat(receipt.fee()).isEqualByComparingTo("2.90");
});
```

When the same checks repeat across tests, write a custom assertion extending
`AbstractAssert<PaymentAssert, Payment>` (example in the snippets file). Rules:
`isEqualByComparingTo` for `BigDecimal`; `containsExactly` only when order is part of the
contract; `singleElement()` instead of `hasSize(1)` + `get(0)`; never `assertTrue(a.equals(b))`.

## 3. Mockito

| Collaborator | Double |
|---|---|
| remote API client, message publisher | Mockito mock (unit), WireMock or a container (integration) |
| repository | in-memory fake or Testcontainers DB; mock only in pure orchestration tests |
| records, value objects, DTOs | real instances, never mocks |
| time | `Clock.fixed(...)` or a mutable test clock (section 6) |
| the class under test | never spy or partially mock it |
| third-party types you do not own | wrap behind your own interface, mock that |

```java
@ExtendWith(MockitoExtension.class)            // strict stubs: an unused stub fails the test
class RefundServiceTest {
    @Mock PaymentRepository repo;
    @Mock PaymentGateway gateway;
    @Captor ArgumentCaptor<RefundRequest> request;
    RefundService service;
    @BeforeEach void setUp() { service = new RefundService(repo, gateway, Clock.fixed(NOW, ZoneOffset.UTC)); }
    @Test void refundsThroughGateway() {
        given(repo.find(ID)).willReturn(Optional.of(captured(ID, Money.eur("100"))));
        given(gateway.refund(any())).willReturn(new GatewayResult("rf_1", OK));
        service.refund(ID, Money.eur("30"));
        then(gateway).should().refund(request.capture());
        assertThat(request.getValue().amount()).isEqualTo(Money.eur("30"));
        then(gateway).shouldHaveNoMoreInteractions();
    }
}
```

JDK 21+ prints "A Java agent has been loaded dynamically" because Mockito 5's inline mock maker
self-attaches, and future JDKs will refuse. Load it as an agent: Maven runs
`maven-dependency-plugin:properties` and passes
`<argLine>@{argLine} -javaagent:${org.mockito:mockito-core:jar}</argLine>` to Surefire; Gradle
adds a `mockitoAgent` configuration and `jvmArgs("-javaagent:${mockitoAgent.asPath}")`.

## 4. Testcontainers

- `@Testcontainers` + `@Container static` field: one container per class; an instance field
  restarts it per test. `@Testcontainers(disabledWithoutDocker = true)` skips where Docker is absent.
- Many IT classes: one singleton per JVM, removed by Ryuk at exit.

```java
abstract class PostgresIT {
    static final PostgreSQLContainer<?> PG = new PostgreSQLContainer<>("postgres:17-alpine")
        .withTmpFs(Map.of("/var/lib/postgresql/data", "rw"));   // RAM-backed data dir
    static { PG.start(); }
}
```

- Spring Boot 3.1+: `@ServiceConnection` on the container wires connection properties
  (`java-spring-boot`). Quarkus: Dev Services start the database for `@QuarkusTest` when no URL
  is configured (`java-quarkus`).
- Testcontainers 2.x (managed by Boot 4): artifacts renamed (`org.testcontainers:testcontainers-postgresql`,
  `testcontainers-junit-jupiter`), classes moved to module packages
  (`org.testcontainers.postgresql.PostgreSQLContainer`), JUnit 4 support removed; OpenRewrite's
  Testcontainers 2 recipes rewrite coordinates and imports. Snippets here use 1.21 names; on 2.x
  let the compiler confirm the new classes' generic signature.

Start-up cost, biggest wins first: static or singleton containers (one start per JVM), truncating
tables per test instead of new containers, pinned slim tags (`postgres:17-alpine`), fewer forks
(each starts its own containers), and locally only `withReuse(true)` with
`testcontainers.reuse.enable=true` in `~/.testcontainers.properties` (never in CI).

## 5. HTTP fakes

```java
@RegisterExtension
static WireMockExtension gateway = WireMockExtension.newInstance().options(wireMockConfig().dynamicPort()).build();
gateway.stubFor(post(urlEqualTo("/v1/charges")).withHeader("Idempotency-Key", matching(".+"))
    .willReturn(okJson("""
        {"id":"ch_1","status":"succeeded"}
        """)));
gateway.stubFor(post(urlEqualTo("/v1/refunds")).willReturn(aResponse().withFault(Fault.CONNECTION_RESET_BY_PEER)));
gateway.verify(1, postRequestedFor(urlEqualTo("/v1/charges")));
URI base = URI.create(gateway.getRuntimeInfo().getHttpBaseUrl());
```

WireMock 3 is `org.wiremock:wiremock`; use `org.wiremock:wiremock-standalone` (shaded) when its
Jetty clashes with the application's. OkHttp's MockWebServer is the lighter choice for queued
canned responses. Always stub the failure modes: delay beyond the client timeout, connection
reset, 429 with `Retry-After`, 5xx, malformed JSON.

Contract tests: Pact (consumer tests write pact files, the provider verifies them via a broker;
many or polyglot consumers) or Spring Cloud Contract (producer-written contracts generate provider
tests plus a WireMock stub jar; Spring on both sides).

## 6. Async and time

```java
await().atMost(Duration.ofSeconds(5)).pollInterval(Duration.ofMillis(50))
       .untilAsserted(() -> assertThat(outbox.pending()).isEmpty());
final class TestClock extends Clock {                       // inject instead of Clock.systemUTC()
    private volatile Instant now;
    TestClock(Instant start) { now = start; }
    void advance(Duration d) { now = now.plus(d); }
    @Override public Instant instant() { return now; }
    @Override public ZoneId getZone() { return ZoneOffset.UTC; }
    @Override public Clock withZone(ZoneId zone) { return Clock.fixed(now, zone); }   // snapshot
}
```

- No `Thread.sleep` to wait for work: Awaitility, `CountDownLatch`, or `executor.close()`
  (waits for submitted tasks; `ExecutorService` is `AutoCloseable` since Java 19).
- Inject the `ExecutorService`; virtual-thread tests pass `newVirtualThreadPerTaskExecutor()` and close it first.
- `ThreadLocal` context (MDC, security) is not inherited by new virtual threads; assert
  propagation. Pinning and carrier starvation: `java-virtual-threads`.

## 7. ArchUnit

```java
@AnalyzeClasses(packages = "com.acme.payments", importOptions = ImportOption.DoNotIncludeTests.class)
class ArchitectureTest {
    @ArchTest static final ArchRule layers = layeredArchitecture().consideringAllDependencies()
        .layer("Web").definedBy("..web..")
        .layer("Application").definedBy("..application..")
        .layer("Persistence").definedBy("..persistence..")
        .whereLayer("Web").mayNotBeAccessedByAnyLayer()
        .whereLayer("Application").mayOnlyBeAccessedByLayers("Web")
        .whereLayer("Persistence").mayOnlyBeAccessedByLayers("Application");
    @ArchTest static final ArchRule noCycles = slices().matching("com.acme.payments.(*)..").should().beFreeOfCycles();
}
```

Forbidden dependencies (`noClasses().that().resideInAPackage("..domain..").should().dependOnClassesThat()...`),
`GeneralCodingRules.NO_CLASSES_SHOULD_USE_FIELD_INJECTION`, and `FreezingArchRule.freeze(...)`
for legacy code (only new violations fail) are in the snippets file.

## 8. Property and mutation testing

```java
@Property(tries = 1000)
void splitPreservesTotal(@ForAll @BigRange(min = "0.01", max = "1000000") @Scale(2) BigDecimal amount,
                         @ForAll @IntRange(min = 1, max = 50) int parts) {
    var sum = Money.eur(amount).split(parts).stream().map(Money::amount).reduce(BigDecimal.ZERO, BigDecimal::add);
    assertThat(sum).isEqualByComparingTo(amount);
}
```

Good properties: round trip (`parse(format(x))`), invariants (totals, ordering), idempotence,
comparison against a slow reference model. jqwik (`net.jqwik:jqwik`) is its own JUnit Platform
engine and shrinks failures; confirm it supports your Platform version before moving to JUnit 6.

PIT (`pitest-maven` + `pitest-junit5-plugin`, Gradle `info.solidsoft.pitest`): scope
`targetClasses`/`targetTests` to the packages that hold business rules, never DTOs or
configuration; run `./mvnw test-compile org.pitest:pitest-maven:mutationCoverage -DwithHistory`
(incremental). Set `mutationThreshold` at today's score (typically 60-80 on domain code) and
raise it as surviving mutants get tests; read survivors, do not chase 100%.

## 9. Flaky-test triage

1. Reproduce: alone, in its class, in the module, then in random order
   (`junit.jupiter.testmethod.order.default=org.junit.jupiter.api.MethodOrderer$Random`,
   `junit.jupiter.testclass.order.default=org.junit.jupiter.api.ClassOrderer$Random`; the seed is
   logged, replay with `junit.jupiter.execution.order.random.seed`). `@RepeatedTest(200)` for races.
2. Classify:

| Symptom | Cause | Fix |
|---|---|---|
| fails only after another test | static/singleton state, leftover rows, changed system properties | reset in `@AfterEach`, unique data per test, truncate |
| fails only in CI | default time zone, locale, CPU count, slow disks | explicit `ZoneId`/`Locale.ROOT`; reproduce with `-Duser.timezone=Pacific/Kiritimati -Duser.language=tr` |
| fails near midnight, month end, DST | `now()` without a `Clock` | inject `Clock` |
| times out under load | sleeps, fixed waits, real network | Awaitility, WireMock, generous `atMost` |
| fails only in parallel | shared ports, files, fixtures | dynamic ports, `@TempDir`, `@ResourceLock` |
| order differs between runs | `HashMap`/`HashSet` iteration | `containsExactlyInAnyOrder` |

3. Retries are the last resort and must stay visible: Surefire `-Dsurefire.rerunFailingTestsCount=2`
   reports "Flakes"; Gradle's `org.gradle.test-retry` plugin with `maxRetries` and `maxFailures`.
   Quarantine with `@Tag("flaky")` plus an issue and a deadline; never a bare `@Disabled`.

## 10. Coverage with JaCoCo

`jacoco-maven-plugin` goals `prepare-agent`, `report` and `check` (Gradle `jacoco` plus
`jacocoTestCoverageVerification` wired into `check`). Gate BRANCH `COVEREDRATIO` on domain and
service modules at 0.60-0.80, exclude generated code and configuration, ratchet so it never
drops, and require high coverage of changed lines in PRs. Coverage proves code ran, not that
anything was asserted: pair it with PIT on core packages. JaCoCo must know the class-file
version (Java 25 needs 0.8.14 or later); multi-module totals come from `report-aggregate`.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Gradle 9 "Failed to load JUnit Platform" | launcher no longer implicit | `testRuntimeOnly("org.junit.platform:junit-platform-launcher")` |
| 0 tests run, build green | missing `useJUnitPlatform()`, or JUnit 4 tests without Vintage | configure the platform; migrate with OpenRewrite |
| engine discovery `NoSuchMethodError` | Platform and Jupiter versions mixed | `junit-bom` only |
| `@BeforeAll` method must be static | per-method lifecycle | static, or `@TestInstance(PER_CLASS)` |
| `UnnecessaryStubbingException` | stub not used by this test | delete or move it; no global `LENIENT` |
| `2.9` vs `2.90` assertion failure | `BigDecimal.equals` compares scale | `isEqualByComparingTo`, recursive comparator |
| Spring suite slow, many contexts | per-class `@MockitoBean` sets, `@DirtiesContext` | `java-spring-boot` context-cache rules |
| "Could not find a valid Docker environment" | no Docker socket in CI | Docker service on the runner, or `disabledWithoutDocker` |

## 12. Worked example: payment service with Postgres, a WireMock gateway and recursive comparison

`PaymentService.capture(cmd)` writes a PENDING row, calls the gateway through `GatewayClient`
(`java.net.http.HttpClient`, 1 s request timeout, maps `HttpTimeoutException` to
`GatewayUnavailableException`), then marks the row CAPTURED. The IT wires real objects, no framework:

```java
@Testcontainers
class PaymentServiceIT {
    @Container static final PostgreSQLContainer<?> PG = new PostgreSQLContainer<>("postgres:17-alpine");
    @RegisterExtension static final WireMockExtension GATEWAY =
        WireMockExtension.newInstance().options(wireMockConfig().dynamicPort()).build();
    static final Instant NOW = Instant.parse("2025-03-01T10:15:30Z");
    JdbcPaymentRepository repo;
    PaymentService service;

    @BeforeAll static void migrate() {
        Flyway.configure().dataSource(PG.getJdbcUrl(), PG.getUsername(), PG.getPassword()).load().migrate();
    }

    @BeforeEach void wire() {
        var ds = new PGSimpleDataSource();
        ds.setUrl(PG.getJdbcUrl()); ds.setUser(PG.getUsername()); ds.setPassword(PG.getPassword());
        repo = new JdbcPaymentRepository(ds);
        repo.deleteAll();                                              // no rows leak between tests
        var client = new GatewayClient(URI.create(GATEWAY.getRuntimeInfo().getHttpBaseUrl()), Duration.ofSeconds(1));
        service = new PaymentService(repo, client, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test void capturesAndStoresPayment() {
        GATEWAY.stubFor(post(urlEqualTo("/v1/charges")).withHeader("Idempotency-Key", equalTo("order-42"))
            .willReturn(okJson("""
                {"id":"ch_123","status":"succeeded","fee":"2.90"}
                """)));
        Payment result = service.capture(new CaptureCommand("order-42", Money.eur("100.00")));
        var expected = new Payment(null, "order-42", Money.eur("100.00"), Money.eur("2.9"), CAPTURED, "ch_123", NOW);
        assertThat(result).usingRecursiveComparison().ignoringFields("id")
            .withComparatorForType(BigDecimal::compareTo, BigDecimal.class).isEqualTo(expected);
        assertThat(repo.findByOrderId("order-42")).get().usingRecursiveComparison()
            .withComparatorForType(BigDecimal::compareTo, BigDecimal.class).isEqualTo(result);
        GATEWAY.verify(1, postRequestedFor(urlEqualTo("/v1/charges")));
    }

    @Test void gatewayTimeoutLeavesPaymentPending() {
        GATEWAY.stubFor(post(urlEqualTo("/v1/charges")).willReturn(okJson("{}").withFixedDelay(2_000)));
        assertThatThrownBy(() -> service.capture(new CaptureCommand("order-43", Money.eur("10.00"))))
            .isInstanceOf(GatewayUnavailableException.class);
        assertThat(repo.findByOrderId("order-43")).get().extracting(Payment::status).isEqualTo(PENDING);
    }
}
```

Run `./mvnw verify -Dit.test=PaymentServiceIT` (or `./gradlew integrationTest --tests '*PaymentServiceIT'`).
Done when both tests pass in random order and alongside other ITs (unique order ids), the suite
has no `Thread.sleep`, the timeout test takes about 1 s rather than 2, and the recursive
comparison fails if any persisted field (fee, gateway id, timestamp) is wrong.

Related: `java-build-maven-gradle`, `java-spring-boot`, `java-quarkus`, `java-virtual-threads`, `testing-strategy`, `kotlin-testing`, hub `java-craft`
