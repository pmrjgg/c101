# Java build, test and framework recipes

## 1. Maven

```xml
<properties>
  <maven.compiler.release>21</maven.compiler.release>
  <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
</properties>
<dependencyManagement>
  <dependencies>
    <dependency>                                  <!-- align versions with a BOM -->
      <groupId>org.junit</groupId><artifactId>junit-bom</artifactId>
      <version>${junit.version}</version><type>pom</type><scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
```

| Task | Command |
|---|---|
| full build, CI-friendly output | `./mvnw -B -ntp verify` |
| parallel build | `./mvnw -T1C verify` |
| one test | `./mvnw -Dtest='OrderServiceTest#rejectsNegative' test` |
| skip tests (packaging only) | `./mvnw -DskipTests package` |
| dependency tree for one artifact | `./mvnw dependency:tree -Dincludes=com.fasterxml.jackson.core` |
| unused/undeclared deps | `./mvnw dependency:analyze` |
| updates available | `./mvnw versions:display-dependency-updates versions:display-plugin-updates` |
| effective POM | `./mvnw help:effective-pom` |
| enforce rules | maven-enforcer-plugin: `requireMavenVersion`, `requireJavaVersion`, `dependencyConvergence`, `banDuplicatePomDependencyVersions` |

Surefire runs unit tests (`*Test`), Failsafe runs integration tests (`*IT`) in `verify`.
Preview features: `<compilerArgs><arg>--enable-preview</arg></compilerArgs>` plus the same flag
in Surefire's `argLine`.

## 2. Gradle (Kotlin DSL)

```kotlin
// build.gradle.kts
plugins { java; alias(libs.plugins.spotless) }
java { toolchain { languageVersion = JavaLanguageVersion.of(25) } }
dependencies {
    implementation(platform(libs.spring.boot.bom))
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.assertj.core)
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}
tasks.withType<JavaCompile>().configureEach {
    options.release = 25
    options.compilerArgs.addAll(listOf("-Xlint:all", "-Werror"))
}
tasks.test { useJUnitPlatform(); jvmArgs("-XX:+EnableDynamicAgentLoading") }   // or a proper -javaagent for Mockito
```

| Task | Command |
|---|---|
| build with configuration cache | `./gradlew build --configuration-cache` |
| one test | `./gradlew test --tests 'com.acme.OrderServiceTest.rejectsNegative'` |
| why this version | `./gradlew dependencyInsight --dependency jackson-databind --configuration runtimeClasspath` |
| full runtime classpath | `./gradlew dependencies --configuration runtimeClasspath` |
| build profile (local) | `./gradlew build --profile` → `build/reports/profile/*.html`; a `--scan` build scan publishes to scans.gradle.com and needs terms acceptance: return it as an Open doubt for the user |
| lock dependency versions | `dependencyLocking { lockAllConfigurations() }` + `./gradlew dependencies --write-locks` |

Versions live in `gradle/libs.versions.toml`; shared build logic in convention plugins under
`build-logic/` (included build), not in `allprojects {}` blocks. Gradle 9 requires Java 17+ to
run the build and prefers the configuration cache.

## 3. Static analysis stack

| Tool | Catches | Notes |
|---|---|---|
| `javac -Xlint:all -Werror` | unchecked, deprecation, fallthrough, missing serialVersionUID | baseline |
| Error Prone | common bug patterns at compile time | runs as a javac plugin |
| NullAway + JSpecify (`@NullMarked`, `@Nullable`) | NPEs at compile time | Spring Framework 7 / Boot 4 ship JSpecify annotations |
| SpotBugs | bytecode bug patterns | slower; CI only |
| Checkstyle / Spotless (google-java-format or palantir) | style | format automatically, check in CI |
| ArchUnit | architecture rules as tests (layering, cycles) | `noClasses().that().resideInAPackage("..domain..").should().dependOnClassesThat().resideInAPackage("..web..")` |

## 4. JUnit 5/6 (Jupiter API) and AssertJ

JUnit 6 (2025) keeps the Jupiter programming model (`org.junit.jupiter.api`) and requires
Java 17; code below works on both.

```java
class PriceCalculatorTest {
    private final PriceCalculator calc = new PriceCalculator(new FixedRates(Map.of("EUR", "1.10")));

    @ParameterizedTest(name = "{0} x {1} = {2}")
    @CsvSource({ "10.00, 1, 10.00", "10.00, 3, 30.00", "0.10, 3, 0.30" })
    void multipliesExactly(BigDecimal unit, int qty, BigDecimal expected) {
        assertThat(calc.total(unit, qty)).isEqualByComparingTo(expected);
    }

    @Test
    void rejectsNegativeQuantity() {
        assertThatThrownBy(() -> calc.total(BigDecimal.ONE, -1))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("quantity");
    }

    @Nested
    class WithDiscounts {
        @Test void appliesBestDiscountOnly() {
            var result = calc.quote(cart(), List.of(pct(10), pct(15)));
            assertThat(result.discounts()).singleElement().extracting(Discount::percent).isEqualTo(15);
        }
    }
}
```

Useful AssertJ: `containsExactly`, `containsExactlyInAnyOrder`, `extracting(...).containsOnly`,
`usingRecursiveComparison().ignoringFields("id")`, `satisfies`, `SoftAssertions.assertSoftly`.
JUnit: `@TempDir Path dir`, `@Timeout(5)`, `@RepeatedTest(100)` for flakiness hunts,
`@MethodSource` for complex parameters, `@EnabledIfEnvironmentVariable` for gated tests.

Property-based testing: jqwik (`@Property`, `@ForAll`) runs on the JUnit Platform.

## 5. Testcontainers

```java
@Testcontainers
class OrderRepositoryIT {
    @Container
    static PostgreSQLContainer<?> pg = new PostgreSQLContainer<>("postgres:17-alpine");
    // plain JDBC: pg.getJdbcUrl(), pg.getUsername(), pg.getPassword()
}
```

Spring Boot: annotate the container field with `@ServiceConnection` and the connection
properties are wired automatically. Reuse containers across test classes with a static base
class or singleton pattern; pin image tags.

## 6. Mockito

- Mock collaborators at architectural boundaries (HTTP clients, repositories), not value
  objects or the class under test.
- `when(repo.find(id)).thenReturn(Optional.of(user))`; `verify(mailer).send(argThat(m -> m.to().equals(email)))`;
  `ArgumentCaptor` for complex arguments; strict stubs (`MockitoExtension` default) fail on
  unused stubs.
- JDK 21+ warns about dynamically loaded agents; configure Mockito's jar as `-javaagent` in
  Surefire `argLine` / Gradle `jvmArgs` (Mockito documents the exact setup for each tool).

## 7. Spring Boot essentials (3.x / 4.x)

| Topic | Rule |
|---|---|
| injection | constructor injection, `final` fields; no field `@Autowired` |
| configuration | `@ConfigurationProperties` on records with validation (`@Validated`) |
| transactions | `@Transactional` works through proxies: self-invocation bypasses it; checked exceptions do not roll back by default (`rollbackFor`); `readOnly = true` for queries |
| JPA | `spring.jpa.open-in-view=false`; avoid N+1 with fetch joins / `@EntityGraph`; log SQL in tests; never expose entities in APIs (map to records) |
| HTTP clients | `RestClient` (6.1+) or declarative `@HttpExchange` interfaces; set connect/read timeouts |
| observability | Actuator + Micrometer; health groups for liveness/readiness |
| tests | slices (`@WebMvcTest`, `@DataJpaTest`, `@JsonTest`) before `@SpringBootTest`; Testcontainers with `@ServiceConnection` |
| virtual threads | `spring.threads.virtual.enabled=true` (3.2+) |
| Boot 4 changes | Spring Framework 7, Jakarta EE 11, Jackson 3 by default (new `tools.jackson` packages), JSpecify null-safety, modular auto-configuration; read the migration guide before upgrading |

## 8. Quarkus essentials

| Topic | Rule |
|---|---|
| DI | build-time CDI (ArC): `@ApplicationScoped` beans; avoid private member injection (reflection) |
| config | `@ConfigMapping` interfaces |
| dev loop | `quarkus dev` / `./mvnw quarkus:dev` with continuous testing; Dev Services start containers automatically |
| threading | Quarkus REST (formerly RESTEasy Reactive): the return type decides. `Uni`/`Multi`/`CompletionStage` run on the event loop, synchronous signatures on a worker thread; override with `@Blocking`/`@NonBlocking`, `@RunOnVirtualThread` for virtual threads |
| native image | `./mvnw package -Dnative` (GraalVM/Mandrel); register reflection with `@RegisterForReflection`; test with `@QuarkusIntegrationTest` |
| tests | `@QuarkusTest`, `@InjectMock` |

Never block the event loop: a blocking call on an I/O thread stalls every request sharing it;
Quarkus logs a warning when it detects this.
