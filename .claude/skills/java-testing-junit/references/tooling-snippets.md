# Test tooling snippets (Maven and Gradle)

Copy-ready wiring for the tools named in the skill. Pin current releases through properties or
the version catalog.

## Mockito as a `-javaagent` (JDK 21+)

```xml
<properties><argLine/></properties>   <!-- empty default so @{argLine} resolves without JaCoCo -->

<plugin><artifactId>maven-dependency-plugin</artifactId>
  <executions><execution><goals><goal>properties</goal></goals></execution></executions></plugin>
<plugin><artifactId>maven-surefire-plugin</artifactId>
  <configuration><argLine>@{argLine} -javaagent:${org.mockito:mockito-core:jar}</argLine></configuration></plugin>
```

The `properties` goal exposes every dependency path as `groupId:artifactId:type`; repeat the
`argLine` in Failsafe if ITs use Mockito.

```kotlin
val mockitoAgent = configurations.create("mockitoAgent")
dependencies {
    testImplementation(libs.mockito.core)
    mockitoAgent(libs.mockito.core) { isTransitive = false }
}
tasks.withType<Test>().configureEach { jvmArgs("-javaagent:${mockitoAgent.asPath}") }
```

## PIT mutation testing

```xml
<plugin><groupId>org.pitest</groupId><artifactId>pitest-maven</artifactId><version>${pitest.version}</version>
  <dependencies><dependency><groupId>org.pitest</groupId><artifactId>pitest-junit5-plugin</artifactId>
    <version>${pitest-junit5.version}</version></dependency></dependencies>
  <configuration>
    <targetClasses><param>com.acme.payments.domain.*</param></targetClasses>
    <targetTests><param>com.acme.payments.domain.*</param></targetTests>
    <mutationThreshold>70</mutationThreshold>
    <coverageThreshold>80</coverageThreshold>
    <threads>4</threads>
  </configuration></plugin>
```

```kotlin
plugins { id("info.solidsoft.pitest") version "<current>" }
pitest {
    junit5PluginVersion.set("<current>")
    targetClasses.set(setOf("com.acme.payments.domain.*"))
    mutationThreshold.set(70)
    threads.set(4)
}
```

Run: `./mvnw test-compile org.pitest:pitest-maven:mutationCoverage -DwithHistory`, or
`./gradlew pitest`. Reports land in `target/pit-reports` / `build/reports/pitest`.

## JaCoCo gate

```xml
<plugin><groupId>org.jacoco</groupId><artifactId>jacoco-maven-plugin</artifactId><version>${jacoco.version}</version>
  <executions>
    <execution><id>agent</id><goals><goal>prepare-agent</goal></goals></execution>
    <execution><id>report</id><phase>verify</phase><goals><goal>report</goal></goals></execution>
    <execution><id>gate</id><goals><goal>check</goal></goals><configuration>
      <rules><rule><element>BUNDLE</element><limits><limit>
        <counter>BRANCH</counter><value>COVEREDRATIO</value><minimum>0.70</minimum>
      </limit></limits></rule></rules>
      <excludes><exclude>**/generated/**</exclude><exclude>**/config/**</exclude></excludes>
    </configuration></execution>
  </executions></plugin>
```

```kotlin
plugins { jacoco }
tasks.jacocoTestCoverageVerification {
    violationRules { rule { limit { counter = "BRANCH"; minimum = "0.70".toBigDecimal() } } }
}
tasks.check { dependsOn(tasks.jacocoTestCoverageVerification) }
```

Multi-module totals: a dedicated reporting module with `report-aggregate` (Maven) or the
`jacoco-report-aggregation` plugin (Gradle).

## Custom AssertJ assertion

```java
final class PaymentAssert extends AbstractAssert<PaymentAssert, Payment> {
    private PaymentAssert(Payment actual) { super(actual, PaymentAssert.class); }
    static PaymentAssert assertThatPayment(Payment p) { return new PaymentAssert(p); }

    PaymentAssert isCaptured() {
        isNotNull();
        if (actual.status() != Status.CAPTURED) failWithMessage("Expected CAPTURED but was <%s>", actual.status());
        return this;
    }
    PaymentAssert hasFee(String fee) {
        isNotNull();
        if (actual.fee().amount().compareTo(new BigDecimal(fee)) != 0) failWithMessage("Expected fee %s but was %s", fee, actual.fee());
        return this;
    }
}
```

## More ArchUnit rules

```java
@ArchTest static final ArchRule domainIsFrameworkFree = noClasses().that().resideInAPackage("..domain..")
    .should().dependOnClassesThat().resideInAnyPackage("org.springframework..", "..web..");
@ArchTest static final ArchRule noFieldInjection = GeneralCodingRules.NO_CLASSES_SHOULD_USE_FIELD_INJECTION;
@ArchTest static final ArchRule noStdout = GeneralCodingRules.NO_CLASSES_SHOULD_ACCESS_STANDARD_STREAMS;
@ArchTest static final ArchRule legacyLayers = FreezingArchRule.freeze(layeredRule());   // only new violations fail
```

## Gradle test retry (last resort)

```kotlin
plugins { id("org.gradle.test-retry") version "<current>" }
tasks.test {
    retry {
        maxRetries.set(2)
        maxFailures.set(10)                 // stop retrying when many tests fail: that is a real break
        failOnPassedAfterRetry.set(false)
    }
}
```
