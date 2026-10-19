# Spring Boot 3.x to 4.0 migration (detail)

Boot 4.0 (November 2025): Spring Framework 7, Jakarta EE 11, Spring Security 7, Hibernate 7,
Jackson 3, JUnit 6, Testcontainers 2; Java 17 remains the minimum. Read the official migration
guide for the release you target; this file is the working checklist.

## Order of work

1. **Reach the latest 3.5.x first.** 4.0 removes what 3.x deprecated. Build with deprecation
   warnings visible (`-Xlint:deprecation`) and fix every one on 3.5.
2. **Report renamed properties.** Add `org.springframework.boot:spring-boot-properties-migrator`
   with runtime scope, start the app, read the report it logs, update `application.yml`, then
   remove the dependency.
3. **Automate the mechanical part.**

   ```bash
   ./mvnw -U org.openrewrite.maven:rewrite-maven-plugin:dryRun \
     -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:RELEASE \
     -Drewrite.activeRecipes=org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0
   ```

   Review `target/rewrite/rewrite.patch`, then run `:run`. The recipe chains the 3.5 migration and
   the Framework 7 / Security 7 steps; run `org.openrewrite.java.testing.junit6.JUnit5to6Migration`
   separately if tests still use JUnit 5 APIs that changed.
4. **Starters and modules.** Auto-configuration is split into per-technology modules.
   `spring-boot-starter-web` becomes `spring-boot-starter-webmvc` (the old name is deprecated);
   each technology has a matching test starter (for example `spring-boot-starter-webmvc-test`).
   The classic starters (`spring-boot-starter-classic`, `spring-boot-starter-test-classic`)
   restore the 3.x all-in-one classpath as a temporary bridge; plan their removal.
   Auto-configuration classes and test-slice annotations moved to per-module packages: fix
   imports (the recipe does most of them).
5. **Jakarta EE 11.** Servlet 6.1 containers only: Tomcat 11 or Jetty 12.1; Undertow support is
   gone. JPA 3.2 with Hibernate 7 (check native queries, removed legacy APIs, ID generator
   changes), Bean Validation 3.1.
6. **Jackson 3.** Maven group `tools.jackson.core`, Java packages `tools.jackson.*`; annotations
   remain `com.fasterxml.jackson.annotation`. `ObjectMapper` usage moves toward the immutable
   `JsonMapper` builder; Boot's builder customizers become `JsonMapperBuilderCustomizer`. Several
   serialization defaults changed: pin the wire format with `@JsonTest` snapshots of real
   payloads before upgrading and diff them after. `spring-boot-jackson2` keeps Jackson 2 as a
   deprecated stop-gap.
7. **Null safety.** Spring APIs carry JSpecify annotations (`org.jspecify.annotations.Nullable`)
   instead of `org.springframework.lang`. NullAway in JSpecify mode and Kotlin callers now see
   real nullness: expect new compile errors where code ignored nullable returns.
8. **Tests.** `@MockBean`/`@SpyBean` are removed: use `@MockitoBean`/`@MockitoSpyBean`
   (`org.springframework.test.context.bean.override.mockito`). JUnit 6 needs Java 17. Testcontainers
   2 renamed artifacts (`testcontainers-postgresql`) and moved classes to module packages.
   Framework 7 adds `RestTestClient` (Boot: `@AutoConfigureRestTestClient`) as the newer
   alternative to `TestRestTemplate`.
9. **Security 7.** Lambda DSL only: no `and()` chaining, no `authorizeRequests` (use
   `authorizeHttpRequests`). Re-run the security tests for every `SecurityFilterChain`.
10. **Observability.** Boot 4 adds an OpenTelemetry starter and reorganised some `management.*`
    keys; let the properties migrator and the reference docs confirm each key you set.
11. **Ship.** Full unit, slice and integration suites; contract tests against consumers; a
    canary deploy watching error rate, latency and serialization errors before full rollout.

## Done when

- No dependency on classic starters, `spring-boot-jackson2` or the properties migrator remains,
  or each has a dated removal ticket.
- `./mvnw -B -ntp verify` is green with `-Werror`, and recorded JSON payloads are unchanged or the
  change is agreed with consumers.
