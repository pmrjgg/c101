---
name: kotlin-gradle-builds
description: "Gradle Kotlin DSL for Kotlin, Android and KMP: version catalogs, build-logic convention plugins, compilerOptions and toolchains, moving from kapt to KSP2, configuration and build caches, explicitApi with ABI validation, detekt, ktlint and ktfmt, Dokka, and diagnosing slow or broken builds. Load when setting up, upgrading or speeding up a Kotlin Gradle build."
when_to_use: "Editing build.gradle.kts, settings.gradle.kts, gradle.properties, gradle/libs.versions.toml or build-logic/; errors like 'Inconsistent JVM-target compatibility detected', 'The Kotlin Gradle plugin was loaded multiple times', kotlinOptions errors after a Kotlin 2.2+ bump, configuration cache problems, kotlin-kapt failing under AGP 9 built-in Kotlin, 'Could not connect to kotlin daemon', daemon OutOfMemoryError, version conflicts; slow builds; upgrading Kotlin, AGP or Gradle."
---

# Kotlin Gradle builds

Baseline (October 2026): Gradle 9.x (9.8 current; the daemon needs JVM 17+), Kotlin Gradle plugin 2.4.x
(2.4.20-2.4.21 tested with Gradle 7.6.3-9.7.0 and AGP 8.5.2-9.3.1), AGP 9.x (9.4 current, needs Gradle
9.6), KSP 2.3.x, detekt 1.23.8 (2.0 in alpha), Dokka 2.x. Newer combinations usually work with
deprecation warnings. KMP targets live in `kotlin-multiplatform`; the `composeCompiler { }` block in
`kotlin-compose`.

Deep material: [convention plugin templates](references/convention-plugins.md) |
[troubleshooting cookbook](references/troubleshooting.md)

## 1. Orient and the gate

```bash
./gradlew --version                                     # Gradle, its embedded Kotlin, daemon JVM
sed -n '1,40p' gradle/libs.versions.toml
ls settings.gradle.kts build-logic buildSrc gradle.properties 2>/dev/null
grep -rnE 'allprojects|subprojects|afterEvaluate|kotlinOptions|kapt\(|kotlin\("kapt"\)|kotlin-kapt' --include=*.kts . | head
grep -nE '^(org\.gradle|kotlin\.|android\.)' gradle.properties
./gradlew help --configuration-cache                    # can the configuration be cached at all?
```

| Step | Command | Blocks when |
|---|---|---|
| build and tests | `./gradlew build` (KMP: `./gradlew allTests`) | failure |
| static analysis | `./gradlew detekt` | findings beyond the baseline |
| format | `./gradlew spotlessCheck` (or `ktlintCheck`) | any diff |
| warnings | `./gradlew build -PwarningsAsErrors=true` (wired to `allWarningsAsErrors`) | any warning |
| public API (libraries) | `explicitApi()` + `./gradlew checkKotlinAbi` (or BCV `apiCheck`) | unreviewed API change |
| Android | `./gradlew lint testDebugUnitTest` | errors |
| configuration cache | `./gradlew build --configuration-cache` | any problem |

## 2. Version catalog

```toml
# gradle/libs.versions.toml (pins are examples; keep what the project has, bump deliberately)
[versions]
kotlin = "2.4.21"
agp = "9.3.1"
ksp = "2.3.12"
coroutines = "1.11.0"
ktor = "3.6.0"
room = "2.8.5"

[libraries]
kotlinx-coroutines-core = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-core", version.ref = "coroutines" }
kotlinx-coroutines-test = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-test", version.ref = "coroutines" }
ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }
ktor-client-content-negotiation = { module = "io.ktor:ktor-client-content-negotiation", version.ref = "ktor" }
androidx-room-runtime = { module = "androidx.room:room-runtime", version.ref = "room" }
androidx-room-compiler = { module = "androidx.room:room-compiler", version.ref = "room" }
# plugin artifacts for build-logic's classpath
android-gradlePlugin = { module = "com.android.tools.build:gradle", version.ref = "agp" }
kotlin-gradlePlugin = { module = "org.jetbrains.kotlin:kotlin-gradle-plugin", version.ref = "kotlin" }
compose-gradlePlugin = { module = "org.jetbrains.kotlin:compose-compiler-gradle-plugin", version.ref = "kotlin" }
ksp-gradlePlugin = { module = "com.google.devtools.ksp:com.google.devtools.ksp.gradle.plugin", version.ref = "ksp" }

[bundles]
ktor-client = ["ktor-client-core", "ktor-client-content-negotiation"]

[plugins]
kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version.ref = "kotlin" }
compose-compiler = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
android-application = { id = "com.android.application", version.ref = "agp" }
android-library = { id = "com.android.library", version.ref = "agp" }
ksp = { id = "com.google.devtools.ksp", version.ref = "ksp" }
room = { id = "androidx.room", version.ref = "room" }
acme-android-library = { id = "acme.android.library" }       # convention plugin from build-logic: no version
```

- Aliases split on `-` or `_` into accessors: `kotlinx-coroutines-core` becomes
  `libs.kotlinx.coroutines.core`, plugins `alias(libs.plugins.kotlin.jvm)`, versions
  `libs.versions.kotlin.get()`, bundles `libs.bundles.ktor.client`.
- Rich versions when a range matters, in `[versions]`: `mylib = { strictly = "[1.0, 2.0[", prefer = "1.2" }`
  (also `require`, `reject`), referenced with `version.ref = "mylib"`.
- Never dynamic versions (`1.+`, `latest.release`): non-reproducible builds and slow resolution.
- Updates: Renovate understands `libs.versions.toml` (group Kotlin, KSP, the Compose compiler plugin and
  SKIE into one PR); or `nl.littlerobots.version-catalog-update` (`./gradlew versionCatalogUpdate`,
  `--interactive` then `versionCatalogApplyUpdates`, `# @pin` / `# @keep` comments); or
  `com.github.ben-manes.versions` (`./gradlew dependencyUpdates`) for a report only.

## 3. Convention plugins in build-logic

```kotlin
// settings.gradle.kts (root)
pluginManagement { includeBuild("build-logic"); repositories { google(); mavenCentral(); gradlePluginPortal() } }
plugins { id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0" }   // JDK auto-provisioning
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() }
}

// build-logic/settings.gradle.kts
dependencyResolutionManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
    versionCatalogs { create("libs") { from(files("../gradle/libs.versions.toml")) } }
}
include(":convention")

// build-logic/convention/build.gradle.kts
plugins { `kotlin-dsl` }
dependencies { compileOnly(libs.android.gradlePlugin); compileOnly(libs.kotlin.gradlePlugin); compileOnly(libs.ksp.gradlePlugin) }
gradlePlugin {
    plugins {
        register("jvmLibrary") { id = "acme.jvm.library"; implementationClass = "JvmLibraryConventionPlugin" }
        register("androidLibrary") { id = "acme.android.library"; implementationClass = "AndroidLibraryConventionPlugin" }
    }
}
```

```kotlin
// build-logic/convention/src/main/kotlin/JvmLibraryConventionPlugin.kt
class JvmLibraryConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("org.jetbrains.kotlin.jvm")
            extensions.configure<KotlinJvmProjectExtension> {
                jvmToolchain(21)
                compilerOptions {
                    allWarningsAsErrors.set(providers.gradleProperty("warningsAsErrors").map(String::toBoolean).orElse(false))
                }
            }
            val libs = extensions.getByType<VersionCatalogsExtension>().named("libs")
            dependencies { add("testImplementation", libs.findLibrary("kotlinx-coroutines-test").get()) }
            tasks.withType<Test>().configureEach { useJUnitPlatform() }
        }
    }
}
// any module: plugins { id("acme.jvm.library") }   (or a catalog alias without version, section 2)
```

Rules:
- No `allprojects { }`, `subprojects { }` or cross-project configuration: they break the configuration
  cache, project isolation and parallel configuration. Each module opts into conventions explicitly.
- The root `build.gradle.kts` declares every third-party plugin once with `apply false` (build-logic uses
  `compileOnly`, so the root puts the plugins on the shared classpath; subprojects omit versions).
- Prefer an included `build-logic` over `buildSrc`: a `buildSrc` change invalidates every build script,
  while an included build is an ordinary build with its own tests and caching.
- Binary plugins (`Plugin<Project>` classes) compile once and are easy to test; precompiled script plugins
  (`src/main/kotlin/acme.jvm.gradle.kts`) read like build scripts but need the plugins they apply as
  `implementation` dependencies of build-logic.
- `kotlin-dsl` compiles build-logic with Gradle's embedded Kotlin (2.2 in Gradle 9): do not force another
  Kotlin version on build-logic. Android, Compose, KSP, Room and publishing templates:
  [convention-plugins](references/convention-plugins.md).

## 4. Compiler configuration

```kotlin
kotlin {
    jvmToolchain(21)                       // JDK for Kotlin and Java compilation; sets the bytecode target
    explicitApi()                          // libraries: visibility and return types required on public API
    compilerOptions {
        optIn.add("kotlinx.coroutines.ExperimentalCoroutinesApi")
        freeCompilerArgs.addAll("-Xjspecify-annotations=strict", "-Xreturn-value-checker=check")
        extraWarnings.set(true)
    }
}
```

| Topic | Rule |
|---|---|
| `kotlinOptions { }` | warning since 2.0, error since 2.2: use `compilerOptions { }`; with AGP 9, `android.kotlinOptions` becomes `kotlin.compilerOptions` |
| toolchains | `jvmToolchain(N)` in conventions; the foojay resolver plugin downloads missing JDKs; mismatched Java/Kotlin targets fail with "Inconsistent JVM-target compatibility" (`kotlin.jvm.target.validation.mode=error`, the default on Gradle 8+) |
| Android `jvmTarget` | with AGP 9 built-in Kotlin it defaults to `compileOptions.targetCompatibility`; set only `compileOptions` |
| warnings, opt-ins | `allWarningsAsErrors` from a Gradle property (`-PwarningsAsErrors=true` on CI); module-wide `optIn.add(...)` only for APIs the team adopted, otherwise `@OptIn` at use sites |
| JSpecify | `strict` is the default; `-Xjspecify-annotations=warn` while migrating Java code |
| unused return values | `-Xreturn-value-checker=check` (experimental, 2.3+); `full` checks every project declaration |
| library compatibility | pin `apiVersion` / `languageVersion` (`KotlinVersion.KOTLIN_2_2`) so consumers on older Kotlin can compile against you |

## 5. Annotation processing: kapt to KSP2

kapt generates Java stubs and runs javac processors (slow; K2 kapt is the default since 2.1.20). Under AGP
9 built-in Kotlin, `org.jetbrains.kotlin.kapt` is incompatible: migrate to KSP or, temporarily, apply
`com.android.legacy-kapt` at the AGP version. KSP 2.3.0 removed KSP1; KSP versions are no longer
prefixed by the Kotlin version (2.3.x works across Kotlin 2.x), and AGP 9 upgrades KSP older than
2.2.10-2.0.2 automatically.

| Processor | KSP route |
|---|---|
| Room 2.x | `ksp(libs.androidx.room.compiler)`; schema via Room Gradle plugin `room { schemaDirectory("$projectDir/schemas") }`; Kotlin codegen by default |
| Room 3.0 | KSP only (`androidx.room3:room3-compiler`), coroutine-first API |
| Dagger / Hilt | `ksp("com.google.dagger:hilt-compiler")`: stable with Dagger 2.60+ and KSP 2.3.9+; `androidx.hilt:hilt-compiler` 1.4.x supports KSP |
| Moshi | `ksp("com.squareup.moshi:moshi-kotlin-codegen")` |
| Glide | separate KSP artifact (check its docs) |
| Data Binding | no KSP support planned: isolate it in its own module or replace it |

Steps per module: check support; apply `id("com.google.devtools.ksp")`; turn `kapt(x)` into `ksp(x)`;
move processor options from `kapt { arguments { arg("k", "v") } }` to `ksp { arg("k", "v") }`; when no
`kapt` dependency remains, remove the kapt plugin and `kapt { }` block (stubs disappear only then).
KMP uses per-target configurations (`add("kspAndroid", x)`, `add("kspIosArm64", x)`; the catch-all `ksp`
is deprecated there). Generated code lands in `build/generated/ksp/<variant or source set>/` and is
registered automatically: do not add it to `srcDirs` by hand. Expect a few source fixes: KSP sees exact
Kotlin types and nullability where kapt saw Java stubs.

## 6. Build performance

```properties
# gradle.properties
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8
org.gradle.parallel=true
org.gradle.caching=true
org.gradle.configuration-cache=true
kotlin.daemon.jvmargs=-Xmx3g
```

| Lever | How | Notes |
|---|---|---|
| configuration cache | flag above; fix every problem in the HTML report; `org.gradle.configuration-cache.problems=warn` only during migration | not on by default even in Gradle 9 ("preferred mode"); a reused run reports "Configuration Cache entry reused" |
| build cache | `org.gradle.caching=true`; remote `HttpBuildCache` in settings, `isPush` only on CI | `-Dorg.gradle.caching.debug=true` prints cache keys; compare two build scans to find the changing input |
| parallel execution | `org.gradle.parallel=true` | requires decoupled projects (no cross-project configuration) |
| Kotlin daemon | `kotlin.daemon.jvmargs` (overrides what it inherits from the Gradle daemon) or `kotlin { kotlinDaemonJvmArgs = listOf(...) }` | "Could not connect to kotlin daemon. Using fallback strategy." means in-process compilation; `kotlin.daemon.useFallbackStrategy=false` fails fast instead |
| incremental compilation | default on (`kotlin.incremental=true`); JVM compilation runs through the Build Tools API since 2.3.20 | `kotlin.build.report.output=file` writes reports to `build/reports/kotlin-build/` |
| lazy task APIs | `tasks.register`, `tasks.named`, `configureEach`, providers | `tasks.create`, `getByName`, `tasks.all { }` and `afterEvaluate` realize work on every invocation |
| less work | KSP instead of kapt; non-transitive R classes (default since AGP 8); `android.enableJetifier=false`; leave unused build features off | |
| measurement | `--scan` (build scan), `--profile` (HTML in `build/reports/profile/`), Android Studio Build Analyzer | run twice and compare warm builds; change one lever at a time |

If `org.gradle.jvmargs` is set, it replaces Gradle's default JVM arguments: always include
`-XX:MaxMetaspaceSize` or metaspace becomes unbounded ("Daemon disappeared" failures).

## 7. Library publishing

```kotlin
kotlin {
    explicitApi()                                           // explicitApiWarning() while migrating
    @OptIn(org.jetbrains.kotlin.gradle.dsl.abi.ExperimentalAbiValidation::class)
    abiValidation()                                         // KGP 2.2.x: abiValidation { enabled = true }
}
```

| Task | Effect |
|---|---|
| `./gradlew updateKotlinAbi` | writes the reference ABI dump; commit it and review diffs like code |
| `./gradlew checkKotlinAbi` | fails on ABI differences; runs as part of `check` |
| before 2.3.20 | `updateLegacyAbi` / `checkLegacyAbi` |
| BCV plugin `org.jetbrains.kotlinx.binary-compatibility-validator` | maintenance mode: `apiDump` / `apiCheck`, dumps in `api/`, klib dumps with `apiValidation { klib { enabled = true } }` |

On hosts that cannot compile every KMP target, KGP infers ABI for the missing ones
(`keepLocallyUnsupportedTargets`).

Docs: Dokka 2 (`id("org.jetbrains.dokka")`; v1 mode is gone): `./gradlew :dokkaGenerate`, or
`dokkaGeneratePublicationHtml` to `build/dokka/html`; aggregate with `dependencies { dokka(project(":core")) }`
in the root; for a `javadoc.jar` apply `org.jetbrains.dokka-javadoc` (Alpha format) and pack
`dokkaGeneratePublicationJavadoc` into a `Jar` with classifier `javadoc`.

Maven Central publishing goes through the Central Portal (OSSRH shut down on 30 June 2025). The
`com.vanniktech.maven.publish` plugin handles sources, javadoc, signing and the Portal upload:

```kotlin
plugins { id("com.vanniktech.maven.publish") }
mavenPublishing {
    publishToMavenCentral()                          // automaticRelease = true skips the manual release step
    signAllPublications()
    coordinates("com.example", "acme-core", "1.4.0")
    pom { name.set("Acme core"); url.set("https://github.com/acme/core") }   // full POM: convention reference
}
```

CI secrets: `ORG_GRADLE_PROJECT_mavenCentralUsername` / `...Password` (a Portal user token),
`ORG_GRADLE_PROJECT_signingInMemoryKey` / `...KeyPassword`. Run `./gradlew publishToMavenCentral` (manual
release) or `publishAndReleaseToMavenCentral`. Plain `maven-publish` + `signing { useInMemoryPgpKeys(...) }`
works too but needs a Portal-compatible upload step.

## 8. Static analysis

| Tool | Setup | Run |
|---|---|---|
| detekt 1.23.8 (stable) | `id("io.gitlab.arturbosch.detekt")`; `detekt { buildUponDefaultConfig = true; config.setFrom("config/detekt/detekt.yml"); baseline = file("config/detekt/baseline.xml") }` | `detekt`, `detektBaseline`, `detektMain` (with type resolution) |
| detekt 2.0 (alpha) | `id("dev.detekt")`, task type `dev.detekt.gradle.Detekt`, built against Kotlin 2.4.10 | same task names |
| ktlint via Spotless | `id("com.diffplug.spotless")`; `spotless { kotlin { ktlint() }; kotlinGradle { ktlint() } }` | `spotlessCheck`, `spotlessApply` |
| ktfmt via Spotless | `kotlin { ktfmt().googleStyle() }` (or `kotlinlangStyle()`) | same; pick ktfmt or ktlint, not both |
| ktlint Gradle plugin | `id("org.jlleitschuh.gradle.ktlint")` | `ktlintCheck`, `ktlintFormat` |
| Android lint | `android { lint { warningsAsErrors = true; abortOnError = true; checkDependencies = true; baseline = file("lint-baseline.xml") } }` | `lint`, `lintDebug`, `updateLintBaseline` |

- Enable detekt's `UnsafeCallOnNullableType`, `TooGenericExceptionCaught`, `GlobalCoroutineUsage` and
  `SuspendFunWithFlowReturnType`. detekt 1.23.8 (built against Kotlin 2.0.21) analyzes newer projects
  unless a `resolutionStrategy` forces `kotlin-compiler-embeddable` on the `detekt` configuration
  ("detekt was compiled with Kotlin X but is currently running with Y"): exclude it from forcing.
- ktlint reads `.editorconfig`: set `ktlint_code_style` explicitly (ktlint defaults to `ktlint_official`,
  Spotless presets `intellij_idea`); disable single rules with `ktlint_standard_<rule> = disabled`.
- Legacy code: baselines (detekt, lint) or Spotless `ratchetFrom("origin/main")`, never a blanket disable.

## 9. Upgrades

Order: Gradle wrapper, then AGP, then Kotlin together with the Compose compiler plugin, KSP,
serialization and SKIE, then libraries. One axis per change, CI green in between.

| AGP | Minimum Gradle | | KGP | Tested Gradle | Tested AGP |
|---|---|---|---|---|---|
| 9.4 | 9.6.0 | | 2.4.20-2.4.21 | 7.6.3-9.7.0 | 8.5.2-9.3.1 |
| 9.3 | 9.5.0 | | 2.4.0-2.4.10 | 7.6.3-9.5.0 | 8.5.2-9.1.0 |
| 9.2 | 9.4.1 | | 2.3.20-2.3.21 | 7.6.3-9.3.0 | 8.2.2-9.0.0 |
| 9.1 | 9.3.1 | | 2.3.0 | 7.6.3-9.0.0 | 8.2.2-8.13.0 |
| 9.0 | 9.1.0 (JDK 17) | | 2.2.20-2.2.21 | 7.6.3-8.14 | 7.3.1-8.11.1 |

- Compose compiler: since Kotlin 2.0 the plugin `org.jetbrains.kotlin.plugin.compose` at the Kotlin version;
  delete `composeOptions.kotlinCompilerExtensionVersion`. Compose libraries (BOM) move independently.
- Gradle 9: daemon on JVM 17+; scripts compile with Kotlin 2.2 (no `this@Build_gradle` labels); JSpecify
  API nullness (`Property<String?>` is invalid); `Project.exec`/`javaexec`, the Convention API and
  `jcenter()` removed (use `providers.exec { }` or injected `ExecOperations`); reproducible archives;
  `test` fails when it discovers no tests (`failOnNoDiscoveredTests = false`); minimum KGP 2.0.0, AGP 8.4.0.
- AGP 9: built-in Kotlin (`android.builtInKotlin=true`; drop `org.jetbrains.kotlin.android`; modules
  without Kotlin set `android { enableKotlin = false }`); new DSL (`android.newDsl=true`, legacy
  `applicationVariants` gone); opting out of both needs `android.builtInKotlin=false` and
  `android.newDsl=false` and ends in AGP 10; KGP older than 2.2.10 is upgraded automatically; `targetSdk`
  defaults to `compileSdk`; stricter R8 keep-rule semantics; KMP modules move to the Android-KMP plugin.

## 10. Troubleshooting

```bash
./gradlew :app:dependencyInsight --dependency kotlinx-coroutines-core --configuration releaseRuntimeClasspath
./gradlew :app:dependencies --configuration releaseRuntimeClasspath > deps.txt     # full tree, diff before/after
./gradlew buildEnvironment                       # plugin classpath: duplicate or conflicting plugin versions
./gradlew --status && ./gradlew --stop           # list and stop daemons
./gradlew :app:assembleDebug --scan              # or --profile without network
```

```kotlin
dependencies {
    implementation(platform("org.jetbrains.kotlinx:kotlinx-coroutines-bom:1.11.0"))   // align a family
    implementation("com.squareup.okio:okio") { version { strictly("3.9.1") } }        // pin with intent
    constraints { implementation("com.fasterxml.jackson.core:jackson-databind:2.18.2") { because("CVE fix") } }
}
configurations.configureEach { resolutionStrategy.failOnVersionConflict() }          // audit mode only
```

| Failure | First check |
|---|---|
| wrong library version at runtime | `dependencyInsight` shows who requested what and the conflict resolution reason |
| `NoSuchMethodError` in build logic, plugin version surprises | `buildEnvironment`; plugin declared with different versions in several places |
| Gradle daemon `OutOfMemoryError`, "Daemon disappeared" | `org.gradle.jvmargs` heap and `-XX:MaxMetaspaceSize` |
| Kotlin daemon OOM, fallback warning | `kotlin.daemon.jvmargs`, then `./gradlew --stop` |
| "No matching toolchains found" | foojay resolver plugin in settings, or install the JDK |

More recipes (configuration cache problems, cache misses, KSP errors, AGP 9 and Gradle 9 upgrade
failures): [troubleshooting](references/troubleshooting.md).

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| "The Kotlin Gradle plugin was loaded multiple times in different subprojects" | plugin applied with a version in several subprojects | declare once in the root with `apply false` |
| "Inconsistent JVM-target compatibility detected for tasks 'compileJava' (17) and 'compileKotlin' (21)" | Java and Kotlin targets differ | one `jvmToolchain(N)` in the convention plugin |
| `kotlinOptions` errors after a Kotlin bump | DSL is an error since 2.2 | `compilerOptions { }` |
| configuration cache never reused | configuration-time inputs change (timestamps, `git` calls, environment read in task setup) | providers / `ValueSource`, move work to execution time |
| kapt plugin fails on AGP 9 | built-in Kotlin | KSP, or `com.android.legacy-kapt` as a stopgap |
| every module rebuilds after a tiny convention edit | logic in `buildSrc` or `allprojects` | included `build-logic` with per-module plugins |
| CI and local builds differ | dynamic versions, unpinned JDK, `--offline` caches | exact catalog versions, toolchains, Gradle wrapper validation |

## 12. Worked example: buildSrc + kapt to build-logic + KSP + configuration cache

Starting point: `:app`, `:core:database` (Room via kapt), `:core:network` (Moshi codegen via kapt),
`:feature:inbox` (Hilt via kapt); `buildSrc/` holds `Deps.kt` constants and an `android-library.gradle.kts`
precompiled plugin; the root `allprojects { }` sets `kotlinOptions.jvmTarget`. The AGP 9.3.1 upgrade is
blocked because `kotlin-kapt` is incompatible with built-in Kotlin.

1. Measure (save the outputs):

```bash
./gradlew :app:assembleDebug --dry-run | grep -ci kapt        # kapt tasks in the graph: 9
./gradlew help --configuration-cache                           # "4 problems were found storing the configuration cache"
./gradlew :app:assembleDebug --profile                         # build/reports/profile/profile-<timestamp>.html
```

2. Move `Deps.kt` constants into `gradle/libs.versions.toml` (section 2), including the plugin artifacts.
3. Create `build-logic` (section 3) with `acme.android.library`, `acme.android.hilt`, `acme.android.room`
   and `acme.jvm.library`; `includeBuild("build-logic")`; delete `buildSrc/` and the root `allprojects { }`;
   declare third-party plugins in the root with `apply false`.
4. Replace kapt module by module:

```kotlin
// core/database/build.gradle.kts
plugins { alias(libs.plugins.acme.android.library); alias(libs.plugins.ksp); alias(libs.plugins.room) }
room { schemaDirectory("$projectDir/schemas") }               // replaces kapt arg "room.schemaLocation"
dependencies { implementation(libs.androidx.room.runtime); ksp(libs.androidx.room.compiler) }   // was kapt(...)
```

   `:core:network`: `ksp(libs.moshi.kotlin.codegen)`. `:app` and `:feature:inbox`:
   `ksp(libs.hilt.compiler)` on Dagger 2.60+. Delete `kotlin("kapt")` and `kapt { correctErrorTypes = true }`.
5. Make the configuration cacheable. The report pointed at two patterns:

```kotlin
// before: an external process at configuration time (reported as a configuration cache problem)
val gitSha = Runtime.getRuntime().exec("git rev-parse --short HEAD").inputStream.reader().readText().trim()
// after: a provider, evaluated lazily and tracked as a configuration input
val gitSha = providers.exec { commandLine("git", "rev-parse", "--short", "HEAD") }
    .standardOutput.asText.map { it.trim() }

// before: tasks.register("printVersion") { doLast { println(project.version) } }
// after: capture the value at configuration time
tasks.register("printVersion") { val v = project.version.toString(); doLast { println(v) } }
```

6. Upgrade AGP to 9.3.1 and Gradle to 9.5.0+ (built-in Kotlin: remove `org.jetbrains.kotlin.android`).
7. Verify:

```bash
./gradlew :app:assembleDebug --dry-run | grep -ci kapt         # 0
./gradlew :app:assembleDebug && ./gradlew :app:assembleDebug    # second run: "Configuration Cache entry reused"
ls core/database/build/generated/ksp/debug/kotlin               # Room DAO implementations from KSP
./gradlew :app:assembleDebug --profile
```

Example measurements from this scenario (yours will differ; compare warm runs):

| Metric | Before | After |
|---|---|---|
| kapt tasks in the debug graph | 9 | 0 |
| configuration phase, no changes | 11.8 s | 0.4 s (cache reused) |
| incremental build after editing one `:feature:inbox` file | 46 s | 19 s |
| AGP 9.3.1 upgrade | blocked by kotlin-kapt | done |

Related: `kotlin-multiplatform`, `kotlin-compose`, `kotlin-testing`, `kotlin-java-interop`,
`kotlin-coroutines-flow`, hub `kotlin-craft`
