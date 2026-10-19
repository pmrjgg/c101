---
name: java-build-maven-gradle
description: "Java build engineering with Maven and Gradle. Covers wrappers and toolchains, BOMs and dependency management, convergence enforcement, the surefire/failsafe split, version catalogs and the configuration cache, Error Prone with NullAway, Spotless, reproducible builds, SBOMs and vulnerability scans, multi-module layout and OpenRewrite migrations. Load when creating, fixing, speeding up or upgrading a Java build."
when_to_use: "Editing pom.xml, build.gradle.kts, settings.gradle.kts or gradle/libs.versions.toml; NoSuchMethodError or NoClassDefFoundError from version drift; enforcer dependencyConvergence failures; slow builds (mvnd, -T, configuration cache, build cache); wiring Error Prone, NullAway, SpotBugs, Spotless or JaCoCo; failsafe integration tests; --enable-preview errors; SBOM, CVE scan or reproducible-build requests; OpenRewrite upgrades to Java 21/25, Spring Boot 4 or JUnit 6."
---

# Java builds with Maven and Gradle

Maven 3.9.x is the production line and runs on Java 8+. Maven 4 runs on Java 17+, adds POM model
4.1.0 (`<subprojects>` instead of `<modules>`, a flattened consumer POM, native `${revision}`) and
is worth adopting only after every plugin in the build is verified on it. Gradle 9 needs Java 17+
to run the daemon (toolchains still compile older targets), uses Kotlin 2 for the DSL, treats the
configuration cache as the preferred mode and removed long-deprecated APIs. Full Gradle
`build-logic` skeleton: [convention plugins](references/gradle-convention-plugins.md).

## 1. Orientation

```bash
./mvnw -v 2>/dev/null || ./gradlew --version          # build tool + the JDK that runs it
grep -h distributionUrl .mvn/wrapper/maven-wrapper.properties gradle/wrapper/gradle-wrapper.properties 2>/dev/null
grep -rnE 'maven.compiler.(release|source|target)|<release>' --include=pom.xml . | head
grep -rnE 'languageVersion|options.release|sourceCompatibility' --include='*.gradle.kts' . | head
./mvnw -q help:evaluate -Dexpression=maven.compiler.release -DforceStdout   # effective value
```

| Setting | Effect | Verdict |
|---|---|---|
| `maven.compiler.release=21` / `options.release = 21` | compiles against the Java 21 API whatever JDK runs javac | Maven default choice |
| Gradle `java.toolchain.languageVersion = JavaLanguageVersion.of(21)` | Gradle selects or provisions JDK 21 for compile, test and javadoc | Gradle default choice |
| `source`/`target` without `release` | links against the newer JDK's API, then `NoSuchMethodError` on the older runtime | never |
| `maven-toolchains-plugin` + `~/.m2/toolchains.xml` | build JVM differs from the compile/test JDK | only when the build tool must run on another JDK |

Wrappers are part of the build: commit them, pin checksums, never call a system `mvn`/`gradle` in CI.

```bash
mvn -N wrapper:wrapper -Dmaven=3.9.11                  # mvnw + .mvn/wrapper/maven-wrapper.properties
./gradlew wrapper --gradle-version 9.1.0 --distribution-type bin
./gradlew wrapper                                       # second run lets the new version regenerate scripts/jar
```

Add `distributionSha256Sum` to both properties files; validate `gradle-wrapper.jar` in CI
(`gradle/actions/wrapper-validation`).

## 2. Maven

**Dependency management.** Put every version in the parent's `<dependencyManagement>`; modules
declare coordinates only. Among imported BOMs the first one declared wins a conflict; an explicit
`<dependency>` entry beats any import.

```xml
<dependencyManagement><dependencies>
  <dependency><groupId>com.fasterxml.jackson</groupId><artifactId>jackson-bom</artifactId>
    <version>${jackson.version}</version><type>pom</type><scope>import</scope></dependency>
  <dependency><groupId>org.junit</groupId><artifactId>junit-bom</artifactId>
    <version>${junit.version}</version><type>pom</type><scope>import</scope></dependency>
  <dependency><groupId>com.acme</groupId><artifactId>shop-api</artifactId>
    <version>${project.version}</version></dependency>          <!-- own modules too -->
</dependencies></dependencyManagement>
```

With `spring-boot-starter-parent`, override a managed version through its property
(`<jackson-bom.version>`); with an imported `spring-boot-dependencies` BOM, property overrides do
nothing, so declare the BOM you want to win before it.

**Enforcer** (binds to `validate`, so it fails before compiling):

```xml
<plugin><artifactId>maven-enforcer-plugin</artifactId><version>3.5.0</version>
  <executions><execution><id>enforce</id><goals><goal>enforce</goal></goals><configuration><rules>
    <requireMavenVersion><version>[3.9.6,)</version></requireMavenVersion>
    <requireJavaVersion><version>[21,)</version></requireJavaVersion>
    <dependencyConvergence/>
    <banDuplicatePomDependencyVersions/>
    <requirePluginVersions/>
    <bannedDependencies><excludes><exclude>commons-logging:commons-logging</exclude></excludes></bannedDependencies>
  </rules></configuration></execution></executions></plugin>
```

**Surefire vs Failsafe.**

| | Surefire | Failsafe |
|---|---|---|
| goals / phase | `test` | `integration-test`, then `verify` |
| default includes | `**/Test*.java`, `**/*Test.java`, `**/*Tests.java`, `**/*TestCase.java` | `**/IT*.java`, `**/*IT.java`, `**/*ITCase.java` |
| on failure | fails at once | records, lets `post-integration-test` tear down, `verify` fails |
| select / skip | `-Dtest=PaymentTest#refunds` / `-DskipTests` | `-Dit.test=PaymentIT` / `-DskipITs` |

Always run `./mvnw verify`, never `mvn integration-test` (it skips the goal that fails the build).
With JaCoCo or a `-javaagent`, write `<argLine>@{argLine} -javaagent:...</argLine>` and define an
empty `<argLine/>` property so the late-bound `@{argLine}` resolves when JaCoCo is skipped.

**Profiles** only for environment toggles (release signing, native image, CI-only heavy scans);
never for dependency versions or code variants. Check with `./mvnw help:active-profiles`.

**Speed.**

| Lever | How | Note |
|---|---|---|
| parallel modules | `./mvnw -T 1C verify` | Maven warns about plugins not marked thread-safe |
| daemon | `mvnd verify` | warm JVM, parallel by default; local loop only |
| one module + what it needs | `./mvnw -pl shop-core -am verify` | `-amd` adds dependents |
| no snapshot checks / offline | `-nsu` / `-o` | |
| CI cache | `actions/setup-java` with `cache: maven` | keys on the POM hash |
| incremental | `maven-build-cache-extension` in `.mvn/extensions.xml` | prove it on a branch first |

## 3. Gradle

```kotlin
// settings.gradle.kts
pluginManagement { includeBuild("build-logic") }
plugins { id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0" }
dependencyResolutionManagement {
    repositoriesMode = RepositoriesMode.FAIL_ON_PROJECT_REPOS
    repositories { mavenCentral() }
}
include("shop-api", "shop-core", "shop-app")

// shop-core/build.gradle.kts  (logic lives in the convention plugin)
plugins { id("acme.java-conventions") }
dependencies {
    api(project(":shop-api"))
    implementation(platform(libs.jackson.bom))
    implementation(libs.jackson.databind)
    testImplementation(platform(libs.junit.bom))
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.platform.launcher)
}
```

```toml
# gradle/libs.versions.toml
[versions]
jackson = "2.18.2"
junit = "5.13.4"
[libraries]
jackson-bom = { module = "com.fasterxml.jackson:jackson-bom", version.ref = "jackson" }
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind" }   # version from the BOM
junit-bom = { module = "org.junit:junit-bom", version.ref = "junit" }
junit-jupiter = { module = "org.junit.jupiter:junit-jupiter" }
junit-platform-launcher = { module = "org.junit.platform:junit-platform-launcher" }
```

```properties
# gradle.properties
org.gradle.configuration-cache=true
org.gradle.caching=true
org.gradle.parallel=true
org.gradle.jvmargs=-Xmx2g
```

- Convention plugins in `build-logic/` replace `allprojects {}`/`subprojects {}` (which break
  project isolation and the configuration cache).
- Configuration-cache migration: `org.gradle.configuration-cache.problems=warn`, fix each reported
  problem (no `project` access at execution time, no eager `tasks.getByName`), then back to fail.
- Locking: `dependencyLocking { lockAllConfigurations() }`, then
  `./gradlew dependencies --write-locks`; commit `gradle.lockfile`.
- Strictness for libraries: `configurations.configureEach { resolutionStrategy { failOnVersionConflict(); failOnDynamicVersions() } }`.
  It is noisy on large BOM-driven apps; there, add a `constraints {}` entry per reported conflict.
- `java-library` plugin: `api` only for types exposed in public signatures, `implementation` otherwise.

## 4. Static analysis wiring

| Tool | Catches | Cost | Wire as |
|---|---|---|---|
| Error Prone | bug patterns at compile time | +10-30% compile | javac plugin, every build |
| NullAway (JSpecify mode) | null dereferences | small | Error Prone check, `@NullMarked` packages |
| SpotBugs | bytecode bug patterns | slow | CI only, `spotbugs:check` / `spotbugsMain` |
| Checkstyle **or** PMD | Checkstyle conventions / PMD design smells | medium | pick one; with Spotless, PMD adds more |
| Spotless | formatting drift | fast | `spotless:apply` locally, `check` in CI |

```xml
<plugin><artifactId>maven-compiler-plugin</artifactId><version>3.13.0</version><configuration>
  <release>21</release><parameters>true</parameters>
  <compilerArgs>
    <arg>-Xlint:all,-processing</arg><arg>-Werror</arg>
    <arg>-XDcompilePolicy=simple</arg><arg>--should-stop=ifError=FLOW</arg>
    <arg>-Xplugin:ErrorProne -XepDisableWarningsInGeneratedCode -Xep:NullAway:ERROR -XepOpt:NullAway:OnlyNullMarked=true -XepOpt:NullAway:JSpecifyMode=true</arg>
  </compilerArgs>
  <annotationProcessorPaths>   <!-- once set, Lombok/MapStruct/etc. must be listed here too -->
    <path><groupId>com.google.errorprone</groupId><artifactId>error_prone_core</artifactId><version>${errorprone.version}</version></path>
    <path><groupId>com.uber.nullaway</groupId><artifactId>nullaway</artifactId><version>${nullaway.version}</version></path>
  </annotationProcessorPaths>
</configuration></plugin>
```

On JDK 16+ Maven also needs `.mvn/jvm.config` exporting javac internals (one flag per line):
`--add-exports jdk.compiler/com.sun.tools.javac.{api,file,main,model,parser,processing,tree,util}=ALL-UNNAMED`
(expand to eight lines) plus `--add-opens jdk.compiler/com.sun.tools.javac.code=ALL-UNNAMED` and
`--add-opens jdk.compiler/com.sun.tools.javac.comp=ALL-UNNAMED`. Gradle's `net.ltgt.errorprone`
plugin handles this itself. Upgrade Error Prone together with the JDK; old releases break on new
javac internals. NullAway needs `org.jspecify:jspecify` and `@NullMarked` in `package-info.java`;
roll it out one package or module at a time.

Spotless: Maven `com.diffplug.spotless:spotless-maven-plugin` with `<java><palantirJavaFormat/>`
(or `<googleJavaFormat/>`) `<removeUnusedImports/></java>` and `<ratchetFrom>origin/main</ratchetFrom>`
to format only changed files in a legacy codebase; Gradle `spotless { java { palantirJavaFormat() } }`.
google-java-format = 2-space Google style; palantir = 4-space, 120 columns, lambda-friendly.

## 5. Compiler flags

- `-Xlint:all -Werror`; silence a category explicitly (`-Xlint:all,-processing,-serial`), never
  drop `-Werror`. Migrating a legacy module: fix warnings once, then lock with `-Werror`.
- `-parameters`: Spring Framework 6.1+ resolves `@PathVariable`/`@RequestParam`/constructor binding
  names from it; Boot's parent and Gradle plugin set it, plain builds must.
- `--enable-preview` must appear everywhere bytecode is compiled or run, and preview code needs
  `release` equal to the compiling JDK's feature version:

| Where | Maven | Gradle |
|---|---|---|
| compile | `<compilerArgs><arg>--enable-preview</arg>` | `options.compilerArgs.add("--enable-preview")` |
| tests | surefire + failsafe `<argLine>@{argLine} --enable-preview</argLine>` | `tasks.withType<Test> { jvmArgs("--enable-preview") }` |
| run | `spring-boot:run -Dspring-boot.run.jvmArguments=--enable-preview`, `exec:exec` args | `application { applicationDefaultJvmArgs = listOf("--enable-preview") }`, `JavaExec` |
| javadoc | `<additionalOptions>--enable-preview</additionalOptions>`, same release as javac | `(options as CoreJavadocOptions).addBooleanOption("-enable-preview", true)` |

## 6. Dependency troubleshooting

```bash
./mvnw dependency:tree -Dverbose -Dincludes=com.fasterxml.jackson.core   # "omitted for conflict with"
./mvnw dependency:analyze                          # used-undeclared / declared-unused
./gradlew :shop-app:dependencyInsight --dependency jackson-databind --configuration runtimeClasspath
./gradlew :shop-app:dependencies --configuration runtimeClasspath | grep -- '->'   # conflict resolutions
```

Maven resolves conflicts by nearest-wins (then first declaration); Gradle picks the highest
version. Same graph, different classpath: compare before porting a build.

| Fix | When | Avoid when |
|---|---|---|
| pin in `dependencyManagement` / Gradle `constraints { implementation("g:a:v") { because("CVE-...") } }` | wrong version wins | never; this is the default fix |
| exclusion | the artifact must not be present at all (commons-logging next to `spring-jcl`) | you only want another version |
| shading/relocation (`maven-shade-plugin`, `com.gradleup.shadow`) | a library or plugin must coexist with a host's conflicting version | apps: it hides CVEs from scanners and breaks reflection/`ServiceLoader` names |

## 7. Supply chain

- SBOM: Maven `org.cyclonedx:cyclonedx-maven-plugin` goal `makeAggregateBom` at `package`
  (writes `target/bom.json`/`bom.xml`); Gradle `id("org.cyclonedx.bom")`, task `cyclonedxBom`
  (output under `build/reports`, path varies by plugin version). Attach the SBOM to the release.
- CVEs: `osv-scanner scan source -r .` (reads `pom.xml`, `gradle.lockfile`) is fast and keyless;
  OWASP `dependency-check-maven` goal `check` with `failBuildOnCVSS` = 7 is heavier and needs an
  NVD API key from a CI secret. Gate on high/critical, triage reachability, record suppressions
  with an expiry.
- Updates: Dependabot (`package-ecosystem: maven` or `gradle`, weekly, `groups` per framework) or
  Renovate (`config:recommended`, group Spring/Jackson/Netty, automerge patch-level test deps).
- Reproducible builds: Maven sets `<project.build.outputTimestamp>2025-01-01T00:00:00Z</project.build.outputTimestamp>`
  (the release plugin bumps it), verify with `./mvnw clean install` then
  `./mvnw clean verify artifact:compare`; `artifact:check-buildplan` flags non-reproducible
  plugins. Gradle 9 makes archives reproducible by default; on 8.x set
  `tasks.withType<AbstractArchiveTask>().configureEach { isPreserveFileTimestamps = false; isReproducibleFileOrder = true }`.

## 8. Multi-module layout

```
shop/
├── pom.xml | settings.gradle.kts   parent: plugin versions, BOMs, enforcer
├── shop-bom/        optional, published: consumers import it (no parent inheritance)
├── shop-api/        records, interfaces, exceptions; no framework dependencies
├── shop-core/       implementation; depends on shop-api
├── shop-testkit/    fakes and builders for other modules' tests (test scope)
└── shop-app/        Spring Boot / Quarkus wiring and configuration only
```

- Dependencies point inward (app -> core -> api); cycles mean a missing module.
- Gradle `java-test-fixtures`: fixtures in `src/testFixtures/java`, consumed with
  `testImplementation(testFixtures(project(":shop-core")))`. Maven `test-jar` does not carry the
  fixtures' own dependencies; prefer a `*-testkit` module.
- JPMS `module-info.java`: worth it for published libraries with internal packages or jlink
  images; skip for Spring/Quarkus apps (classpath, reflection). At minimum set
  `Automatic-Module-Name` in a library's manifest.

## 9. Migrations with OpenRewrite

| Migration | Recipe | Recipe artifact |
|---|---|---|
| Java 17 -> 21 | `org.openrewrite.java.migrate.UpgradeToJava21` | `rewrite-migrate-java` |
| -> Java 25 | `org.openrewrite.java.migrate.UpgradeToJava25` | `rewrite-migrate-java` |
| Boot 3.x -> 3.5 | `org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5` | `rewrite-spring` |
| Boot 3.5 -> 4.0 | `org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0` | `rewrite-spring` |
| JUnit 4 -> 5 / 5 -> 6 | `org.openrewrite.java.testing.junit5.JUnit4to5Migration` / `...junit6.JUnit5to6Migration` | `rewrite-testing-frameworks` |

```bash
./mvnw -U org.openrewrite.maven:rewrite-maven-plugin:dryRun \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-migrate-java:RELEASE \
  -Drewrite.activeRecipes=org.openrewrite.java.migrate.UpgradeToJava21
less target/rewrite/rewrite.patch          # review, then repeat with :run instead of :dryRun
```

Gradle: `plugins { id("org.openrewrite.rewrite") version "<current>" }`,
`rewrite { activeRecipe("...") }`, `dependencies { rewrite("org.openrewrite.recipe:rewrite-migrate-java:latest.release") }`,
then `./gradlew rewriteDryRun` and `rewriteRun`. One recipe per commit on a clean tree; review it
as an ordinary diff; full build and tests between recipes. For Boot 4, first reach the latest
3.5.x with zero deprecation warnings.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `NoSuchMethodError` only in the packaged app | nearest-wins picked an old transitive version | pin in `dependencyManagement`, add `dependencyConvergence` |
| Lombok/MapStruct silently stop generating | `annotationProcessorPaths` set for Error Prone | list every processor there |
| `@{argLine}` in the JVM command line | late-bound property undefined (JaCoCo skipped) | empty `<argLine/>` property |
| ITs "pass" but failures ignored | ran `integration-test` or Failsafe lacks the `verify` goal | bind both goals, run `verify` |
| `UnsupportedClassVersionError` in tests | tests forked on another JDK than compile | Gradle toolchain / Maven `jvm` or toolchains |
| Configuration cache discarded every run | build script reads env/system properties at configuration time | `providers.environmentVariable(...)`, fix reported problems |
| `Preview features are not enabled` at test time | flag only on javac | add to every row of the table in section 5 |
| snapshot or `+`/`latest` versions | unreproducible build | lock or pin; `failOnDynamicVersions()` |

## 11. Worked example: drifting Maven multi-module to a CI-ready `./mvnw verify`

Start: `shop-api` declares `jackson-databind:2.15.2` and `junit-jupiter:5.9.3`, `shop-core`
declares `2.17.1` and `5.10.2` and gets `2.16.1` through an HTTP client; `shop-app` throws
`NoSuchMethodError` from Jackson at startup; no wrapper; `mvn` 3.6 on the CI image.

1. Measure: `mvn -q dependency:tree -Dverbose -Dincludes=com.fasterxml.jackson.core,org.junit.jupiter -pl shop-app -am`
   shows three databind versions and "omitted for conflict" lines.
2. Pin the tool: `mvn -N wrapper:wrapper -Dmaven=3.9.11`; commit `mvnw`, `.mvn/`.
3. Make drift fail: add the enforcer block from section 2 to the parent; `./mvnw -q validate`
   now fails with "Dependency convergence error" listing each path. This is the regression guard.
4. Introduce the BOM: parent `<dependencyManagement>` imports `jackson-bom` 2.18.2 and
   `junit-bom` 5.13.4 and lists `shop-api`/`shop-core` at `${project.version}`; delete every
   `<version>` from module dependencies (`grep -n '<version>' shop-*/pom.xml` must only show the
   parent reference). Pin plugin versions in `<pluginManagement>` (`requirePluginVersions`).
5. Add Error Prone + NullAway (section 4) and `.mvn/jvm.config`; add
   `@NullMarked package com.acme.shop.api;` to `shop-api` only; fix findings; extend module by module.
6. Split tests: rename container tests `*IT`, bind Failsafe `integration-test` + `verify`.
7. Verify locally: `./mvnw -B -ntp verify` green; `./mvnw -q dependency:tree -Dincludes=com.fasterxml.jackson.core -pl shop-app`
   shows one version; the `NoSuchMethodError` is gone.
8. CI:

```yaml
- uses: actions/checkout@v4
- uses: actions/setup-java@v4
  with: { distribution: temurin, java-version: '21', cache: maven }
- run: ./mvnw -B -ntp verify
```

Done when: enforcer, Error Prone and tests all run inside `verify`, CI uses the wrapper, and a
deliberately added `<version>2.15.2</version>` in a module fails the build at `validate`.

Related: `java-testing-junit`, `java-spring-boot`, `java-quarkus`, `java-modern-language`, `kotlin-gradle-builds`, `dependency-upgrades`, `ci-pipelines`, hub `java-craft`
