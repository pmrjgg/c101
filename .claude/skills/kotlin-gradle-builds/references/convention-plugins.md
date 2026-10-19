# Convention plugin templates (build-logic)

Companion to the `kotlin-gradle-builds` skill. Targets Gradle 9.x, AGP 9.x (new DSL, built-in Kotlin),
KGP 2.4.x, KSP 2.3.x. Adapt names (`acme.*`) and SDK levels to the project.

## Layout

```
settings.gradle.kts                  pluginManagement { includeBuild("build-logic") }
build.gradle.kts                     plugins { ... apply false } for every third-party plugin
gradle/libs.versions.toml            versions, libraries, plugin artifacts, convention plugin ids
build-logic/
  settings.gradle.kts                repositories + versionCatalogs { create("libs") { from(files("../gradle/libs.versions.toml")) } }
  convention/
    build.gradle.kts                 `kotlin-dsl`, compileOnly plugin artifacts, gradlePlugin { plugins { register(...) } }
    src/main/kotlin/*.kt             one class per convention + shared helpers
```

## build-logic/convention/build.gradle.kts

```kotlin
plugins { `kotlin-dsl` }

java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }

dependencies {
    compileOnly(libs.android.gradlePlugin)              // com.android.tools.build:gradle
    compileOnly(libs.kotlin.gradlePlugin)               // org.jetbrains.kotlin:kotlin-gradle-plugin
    compileOnly(libs.compose.gradlePlugin)              // org.jetbrains.kotlin:compose-compiler-gradle-plugin
    compileOnly(libs.ksp.gradlePlugin)                  // com.google.devtools.ksp:com.google.devtools.ksp.gradle.plugin
    compileOnly(libs.room.gradlePlugin)                 // androidx.room:room-gradle-plugin
    compileOnly(libs.detekt.gradlePlugin)               // io.gitlab.arturbosch.detekt:detekt-gradle-plugin
    compileOnly(libs.mavenPublish.gradlePlugin)         // com.vanniktech:gradle-maven-publish-plugin
}

tasks.validatePlugins {
    enableStricterValidation = true
    failOnWarning = true
}

gradlePlugin {
    plugins {
        register("jvmLibrary") { id = "acme.jvm.library"; implementationClass = "JvmLibraryConventionPlugin" }
        register("androidLibrary") { id = "acme.android.library"; implementationClass = "AndroidLibraryConventionPlugin" }
        register("androidCompose") { id = "acme.android.compose"; implementationClass = "AndroidComposeConventionPlugin" }
        register("androidRoom") { id = "acme.android.room"; implementationClass = "AndroidRoomConventionPlugin" }
        register("kmpLibrary") { id = "acme.kmp.library"; implementationClass = "KmpLibraryConventionPlugin" }
        register("detekt") { id = "acme.detekt"; implementationClass = "DetektConventionPlugin" }
        register("publishing") { id = "acme.publishing"; implementationClass = "PublishingConventionPlugin" }
    }
}
```

`compileOnly` keeps plugin versions decided in one place: the root `build.gradle.kts` must then put the
real plugins on the classpath with `alias(libs.plugins.x) apply false`. Precompiled script plugins that
apply a plugin in their own `plugins { }` block need it as `implementation` instead.

## Shared helper

```kotlin
// src/main/kotlin/ProjectExtensions.kt
import org.gradle.api.Project
import org.gradle.api.artifacts.VersionCatalog
import org.gradle.api.artifacts.VersionCatalogsExtension
import org.gradle.kotlin.dsl.getByType

internal val Project.libs: VersionCatalog
    get() = extensions.getByType<VersionCatalogsExtension>().named("libs")

internal fun Project.warningsAsErrors() =
    providers.gradleProperty("warningsAsErrors").map(String::toBoolean).orElse(false)
```

`libs.findLibrary("alias-with-dashes").get()`, `libs.findVersion("x").get().requiredVersion`,
`libs.findPlugin("x").get().get().pluginId`, `libs.findBundle("x").get()`.

## JVM library

```kotlin
class JvmLibraryConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("org.jetbrains.kotlin.jvm")
            extensions.configure<KotlinJvmProjectExtension> {
                jvmToolchain(21)
                compilerOptions { allWarningsAsErrors.set(warningsAsErrors()) }
            }
            dependencies {
                add("testImplementation", libs.findLibrary("kotlinx-coroutines-test").get())
                add("testImplementation", kotlin("test"))
            }
            tasks.withType<Test>().configureEach { useJUnitPlatform() }
        }
    }
}
```

## Android library (AGP 9 new DSL, built-in Kotlin)

```kotlin
import com.android.build.api.dsl.LibraryExtension          // new DSL type; the legacy implementation types are hidden in AGP 9
import org.jetbrains.kotlin.gradle.tasks.KotlinCompilationTask

class AndroidLibraryConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("com.android.library")      // no org.jetbrains.kotlin.android: Kotlin is built in
            extensions.configure<LibraryExtension> {
                compileSdk = 36
                defaultConfig { minSdk = 24 }
                compileOptions {
                    sourceCompatibility = JavaVersion.VERSION_17
                    targetCompatibility = JavaVersion.VERSION_17   // Kotlin jvmTarget follows this
                }
                testOptions { unitTests { isReturnDefaultValues = true } }
                lint { warningsAsErrors = true; abortOnError = true }
            }
            tasks.withType<KotlinCompilationTask<*>>().configureEach {
                compilerOptions.allWarningsAsErrors.set(warningsAsErrors())
            }
            dependencies { add("testImplementation", libs.findLibrary("kotlinx-coroutines-test").get()) }
        }
    }
}
```

On AGP 8.x the same plugin additionally applies `org.jetbrains.kotlin.android`.

## Compose (Android)

```kotlin
import com.android.build.api.dsl.ApplicationExtension
import com.android.build.api.dsl.LibraryExtension
import org.jetbrains.kotlin.compose.compiler.gradle.ComposeCompilerGradlePluginExtension

class AndroidComposeConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("org.jetbrains.kotlin.plugin.compose")
            pluginManager.withPlugin("com.android.library") {
                extensions.configure<LibraryExtension> { buildFeatures { compose = true } }
            }
            pluginManager.withPlugin("com.android.application") {
                extensions.configure<ApplicationExtension> { buildFeatures { compose = true } }
            }
            extensions.configure<ComposeCompilerGradlePluginExtension> {
                stabilityConfigurationFiles.add(rootProject.layout.projectDirectory.file("stability_config.conf"))
                if (providers.gradleProperty("composeReports").isPresent) {      // ./gradlew assembleRelease -PcomposeReports
                    reportsDestination.set(layout.buildDirectory.dir("compose_compiler"))
                    metricsDestination.set(layout.buildDirectory.dir("compose_compiler"))
                }
            }
            dependencies {
                val bom = libs.findLibrary("androidx-compose-bom").get()
                add("implementation", platform(bom))
                add("androidTestImplementation", platform(bom))
            }
        }
    }
}
```

## KSP + Room

```kotlin
import androidx.room.gradle.RoomExtension
import com.google.devtools.ksp.gradle.KspExtension

class AndroidRoomConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("com.google.devtools.ksp")
            pluginManager.apply("androidx.room")
            extensions.configure<RoomExtension> { schemaDirectory("$projectDir/schemas") }   // commit the JSON schemas
            extensions.configure<KspExtension> { arg("room.generateKotlin", "true") }       // processor options go here (default already true)
            dependencies {
                add("implementation", libs.findLibrary("androidx-room-runtime").get())
                add("ksp", libs.findLibrary("androidx-room-compiler").get())
            }
        }
    }
}
```

Hilt follows the same pattern: apply `com.google.devtools.ksp` and `com.google.dagger.hilt.android`, add
`hilt-android` to `implementation` and `hilt-compiler` to `ksp` (Dagger 2.60+ for stable KSP support).

## Kotlin Multiplatform library

```kotlin
class KmpLibraryConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("org.jetbrains.kotlin.multiplatform")
            pluginManager.apply("com.android.kotlin.multiplatform.library")
            extensions.configure<KotlinMultiplatformExtension> {
                jvmToolchain(17)
                jvm()
                iosArm64()
                iosSimulatorArm64()
                compilerOptions { allWarningsAsErrors.set(warningsAsErrors()) }
                sourceSets.commonTest.dependencies { implementation(kotlin("test")) }
            }
        }
    }
}
```

Each module still declares `kotlin { android { namespace = "..." } }` itself (namespaces differ per module);
see `kotlin-multiplatform` for the Android-KMP DSL.

## detekt

```kotlin
import io.gitlab.arturbosch.detekt.Detekt
import io.gitlab.arturbosch.detekt.extensions.DetektExtension

class DetektConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("io.gitlab.arturbosch.detekt")
            extensions.configure<DetektExtension> {
                buildUponDefaultConfig = true                     // start from defaults, override in the yml
                config.setFrom(rootProject.files("config/detekt/detekt.yml"))
                baseline = file("detekt-baseline.xml")            // ./gradlew detektBaseline to (re)create
                parallel = true
            }
            tasks.withType<Detekt>().configureEach {
                jvmTarget = "17"
                reports { sarif { required.set(true) }; html { required.set(true) } }
            }
        }
    }
}
```

## Publishing to Maven Central (vanniktech)

```kotlin
import com.vanniktech.maven.publish.MavenPublishBaseExtension

class PublishingConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("com.vanniktech.maven.publish")
            extensions.configure<MavenPublishBaseExtension> {
                publishToMavenCentral()
                signAllPublications()
                coordinates("com.example", project.name, providers.gradleProperty("VERSION_NAME").get())
                pom {
                    name.set(project.name)
                    description.set(providers.gradleProperty("POM_DESCRIPTION"))
                    url.set("https://github.com/acme/core")
                    licenses { license { name.set("Apache-2.0"); url.set("https://www.apache.org/licenses/LICENSE-2.0") } }
                    developers { developer { id.set("acme"); name.set("Acme team") } }
                    scm {
                        url.set("https://github.com/acme/core")
                        connection.set("scm:git:git://github.com/acme/core.git")
                    }
                }
            }
        }
    }
}
```

Credentials and the signing key come from `ORG_GRADLE_PROJECT_*` environment variables on CI, never from
files in the repository.

## Precompiled script plugin variant

```kotlin
// build-logic/convention/src/main/kotlin/acme.kotlin-jvm.gradle.kts
plugins { id("org.jetbrains.kotlin.jvm") }        // needs implementation(libs.kotlin.gradlePlugin) in build-logic
kotlin { jvmToolchain(21) }
tasks.withType<Test>().configureEach { useJUnitPlatform() }
```

The type-safe `libs` accessor is not generated inside precompiled script plugins; use the
`VersionCatalogsExtension` lookup from the helper above.

## Testing convention plugins

Functional tests with Gradle TestKit (`gradleTestKit()` dependency, `GradleRunner.create()
.withProjectDir(dir).withPluginClasspath().withArguments("build", "--configuration-cache").build()`)
catch configuration cache regressions in the conventions themselves before every module pays for them.
