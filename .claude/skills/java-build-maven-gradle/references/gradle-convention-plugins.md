# Gradle convention plugins (`build-logic`)

Shared build logic lives in an included build so every module applies one plugin id instead of
copying blocks or using `allprojects {}`. Works with the configuration cache and project isolation.

```
build-logic/
├── settings.gradle.kts
├── build.gradle.kts
└── src/main/kotlin/acme.java-conventions.gradle.kts
```

```kotlin
// build-logic/settings.gradle.kts
dependencyResolutionManagement {
    repositories { gradlePluginPortal(); mavenCentral() }
    versionCatalogs { create("libs") { from(files("../gradle/libs.versions.toml")) } }
}
rootProject.name = "build-logic"
```

```kotlin
// build-logic/build.gradle.kts: plugin *artifacts* go on the classpath so precompiled scripts can apply them
plugins { `kotlin-dsl` }
dependencies {
    implementation(libs.errorprone.gradle.plugin)   // net.ltgt.gradle:gradle-errorprone-plugin
    implementation(libs.spotless.gradle.plugin)     // com.diffplug.spotless:spotless-plugin-gradle
}
```

```kotlin
// build-logic/src/main/kotlin/acme.java-conventions.gradle.kts
import net.ltgt.gradle.errorprone.CheckSeverity
import net.ltgt.gradle.errorprone.errorprone

plugins {
    `java-library`
    jacoco
    id("net.ltgt.errorprone")
    id("com.diffplug.spotless")
}

// type-safe `libs` accessors are not generated inside precompiled script plugins
val libs = the<VersionCatalogsExtension>().named("libs")

java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }

dependencies {
    errorprone(libs.findLibrary("errorprone-core").get())
    errorprone(libs.findLibrary("nullaway").get())
    api(libs.findLibrary("jspecify").get())
    testImplementation(platform(libs.findLibrary("junit-bom").get()))
    testImplementation(libs.findLibrary("junit-jupiter").get())
    testRuntimeOnly(libs.findLibrary("junit-platform-launcher").get())
}

tasks.withType<JavaCompile>().configureEach {
    options.compilerArgs.addAll(listOf("-Xlint:all,-processing", "-Werror", "-parameters"))
    options.errorprone {
        disableWarningsInGeneratedCode = true
        check("NullAway", CheckSeverity.ERROR)
        option("NullAway:OnlyNullMarked", "true")
        option("NullAway:JSpecifyMode", "true")
    }
}
tasks.named<JavaCompile>("compileTestJava") { options.errorprone.check("NullAway", CheckSeverity.OFF) }

tasks.withType<Test>().configureEach {
    useJUnitPlatform()
    maxParallelForks = (Runtime.getRuntime().availableProcessors() / 2).coerceAtLeast(1)
}

spotless { java { palantirJavaFormat(); removeUnusedImports() } }

configurations.configureEach { resolutionStrategy.failOnDynamicVersions() }
```

Catalog entries the plugin expects (`gradle/libs.versions.toml`, pin current releases):

```toml
[libraries]
errorprone-core = { module = "com.google.errorprone:error_prone_core", version.ref = "errorprone" }
nullaway = { module = "com.uber.nullaway:nullaway", version.ref = "nullaway" }
jspecify = { module = "org.jspecify:jspecify", version = "1.0.0" }
errorprone-gradle-plugin = { module = "net.ltgt.gradle:gradle-errorprone-plugin", version.ref = "errorpronePlugin" }
spotless-gradle-plugin = { module = "com.diffplug.spotless:spotless-plugin-gradle", version.ref = "spotless" }
```

## Integration tests (the Gradle analogue of Failsafe)

```kotlin
testing {
    suites {
        val test by getting(JvmTestSuite::class) { useJUnitJupiter() }
        register<JvmTestSuite>("integrationTest") {
            dependencies { implementation(project()) }
            targets { all { testTask.configure { shouldRunAfter(test) } } }
        }
    }
}
tasks.named("check") { dependsOn(testing.suites.named("integrationTest")) }
```

Sources go in `src/integrationTest/java`; `./gradlew integrationTest` runs only that suite and
`./gradlew build` runs both.

## CI

```yaml
- uses: actions/setup-java@v4
  with: { distribution: temurin, java-version: '21' }
- uses: gradle/actions/setup-gradle@v4     # caches and validates the wrapper
- run: ./gradlew build
```

Checks before trusting a build cache hit rate: `./gradlew build --configuration-cache` twice in a
row; the second run should report "Reusing configuration cache" and mostly `UP-TO-DATE`/`FROM-CACHE`
tasks.
