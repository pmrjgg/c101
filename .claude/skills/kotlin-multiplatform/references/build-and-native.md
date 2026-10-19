# KMP build recipes and Kotlin/Native tuning

Companion to the `kotlin-multiplatform` skill. Versions as of October 2026 (Kotlin 2.4.x, AGP 9.x,
Gradle 9.x). Verify DSL names against the release notes of the versions pinned in the project.

## AGP 9 migration

With AGP 9.0+, `org.jetbrains.kotlin.multiplatform` cannot share a Gradle project with
`com.android.application` or `com.android.library`. Library code moves to the Android-KMP library plugin
(`com.android.kotlin.multiplatform.library`, AGP 8.10+); the application moves to its own module.

1. Catalog and root build file:

```toml
[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
android-kmp-library = { id = "com.android.kotlin.multiplatform.library", version.ref = "agp" }
```

```kotlin
// build.gradle.kts (root): declare every plugin once, apply nowhere
plugins {
    alias(libs.plugins.kotlin.multiplatform) apply false
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.kmp.library) apply false
}
```

2. New `androidApp` module (`include(":androidApp")` in `settings.gradle.kts`). AGP 9 compiles Kotlin
itself ("built-in Kotlin"), so the app module needs no `org.jetbrains.kotlin.android` plugin:

```kotlin
// androidApp/build.gradle.kts
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.compose.compiler)          // only if the app uses Compose
}
android {
    namespace = "com.example.app"                 // must differ from the library namespace
    compileSdk = 36
    defaultConfig { applicationId = "com.example.app"; minSdk = 24; targetSdk = 36 }
}
dependencies {
    implementation(project(":shared"))
    implementation(libs.androidx.activity.compose)
}
```

Move `shared/src/androidMain/{AndroidManifest.xml,kotlin/MainActivity.kt,res}` that belong to the app into
`androidApp/src/main/`. Keep `actual` declarations in `shared`.

3. Shared module: replace `alias(libs.plugins.android.library)` with `alias(libs.plugins.android.kmp.library)`,
delete the top-level `android { }` block and the `androidTarget { }` call, and declare:

```kotlin
kotlin {
    android {                                  // androidLibrary { } before AGP 8.12; deprecated since 9.1
        namespace = "com.example.shared"
        compileSdk = 36
        minSdk = 24
        withJava()                             // only if the module has Java sources
        withHostTest { isIncludeAndroidResources = true }
        withDeviceTest { instrumentationRunner = "androidx.test.runner.AndroidJUnitRunner" }
        androidResources { enable = true }     // Android res/ or Compose Multiplatform resources
        compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
    }
}
```

4. Rename test directories: `src/androidUnitTest` to `src/androidHostTest`, `src/androidInstrumentedTest`
to `src/androidDeviceTest`. KSP configurations follow: `kspAndroidHostTest`, `kspAndroidDeviceTest`.

5. Variant-specific dependencies have no home (single variant): `debugImplementation(libs.compose.ui.tooling)`
becomes `androidRuntimeClasspath(libs.compose.ui.tooling)`. Anything that truly needs flavors, BuildConfig,
data/view binding or `externalNativeBuild` stays in a separate `com.android.library` module.

6. Gradle 9.1.0+ for AGP 9.0 (9.3.1 for 9.1, 9.4.1 for 9.2, 9.5.0 for 9.3, 9.6.0 for 9.4). Temporary
escape hatch: `android.enableLegacyVariantApi=true`, removed in AGP 10.

## Extending the default hierarchy

```kotlin
kotlin {
    jvm(); android { /* ... */ }; iosArm64(); iosSimulatorArm64()
    applyDefaultHierarchyTemplate()            // keep iosMain, appleMain, nativeMain
    sourceSets {
        val jvmAndAndroidMain by creating { dependsOn(commonMain.get()) }
        jvmMain.get().dependsOn(jvmAndAndroidMain)
        androidMain.get().dependsOn(jvmAndAndroidMain)
    }
}
```

Projects are incompatible with the template when they add custom `dependsOn` edges without calling
`applyDefaultHierarchyTemplate()` first, or name a target like a shared set (`linuxX64("linux")`).

## Kotlin/Native binary options

Set globally in `gradle.properties` as `kotlin.native.binary.<option>=<value>`, per binary with
`binaryOption("<option>", "<value>")`, or as `-Xbinary=<option>=<value>`.

| Option | Values (default first) | Use |
|---|---|---|
| `gc` | `cms` (default since 2.4.0), `pmcs`, `stwms`, `noop` | revert to `pmcs` if CMS misbehaves; `noop` only for experiments |
| `gcMarkSingleThreaded` | `false`, `true` | disable parallel marking (longer pauses on big heaps) |
| `appStateTracking` | `disabled`, `enabled` | experimental: GC on memory pressure only while the app is backgrounded |
| `objcDisposeOnMain` | `true`, `false` | `false` deinitializes Swift/Objective-C objects on a GC thread instead of main |
| `enableSafepointSignposts` | `false`, `true` | GC pauses visible in Instruments (os_signpost, subsystem `org.kotlinlang.native.runtime`) |
| `pagedAllocator` | `true`, `false` | experimental (2.2.0); `false` allocates per object |
| `latin1Strings` | `false`, `true` | experimental (2.2.0); smaller strings when all characters fit Latin-1 |
| `mmapTag` / `disableMmap` | `246` / `false` | memory tagging for Apple tooling; `malloc` instead of `mmap` |
| `smallBinary` | `false`, `true` | experimental (2.2.20); `-Oz`-style size reduction for release |
| `enableReleaseBinaryCache` | `false`, `true` | experimental (2.4.20); faster release links |
| `stackProtector` | `no`, `yes`, `strong`, `all` | stack canaries (2.2.20) |
| `sourceInfoType` | `noop`, `libbacktrace`, `coresymbolication` | file and line numbers in Kotlin exception stack traces |
| `bundleId`, `bundleShortVersionString`, `bundleVersion` | string | `Info.plist` keys of the framework |

GC diagnostics: compiler option `-Xruntime-logs=gc=info` (logs to stderr); `GC.collect()` and
`GC.lastGCInfo` (opt-in `ExperimentalStdlibApi`) to measure heap after a scenario and spot leaks.

Keep Apple minimums below the 2.4 defaults (iOS 15.0, macOS 12.0) only if you must, and test it:

```kotlin
kotlin {
    targets.withType<org.jetbrains.kotlin.gradle.plugin.mpp.KotlinNativeTarget>().configureEach {
        binaries.configureEach { freeCompilerArgs += "-Xoverride-konan-properties=minVersion.ios=14.0" }
    }
}
```

## gradle.properties for a KMP build

```properties
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -Dfile.encoding=UTF-8
org.gradle.caching=true
org.gradle.configuration-cache=true
org.gradle.parallel=true
kotlin.incremental.native=true
# experimental, both lines required:
kotlin.native.binary.enableReleaseBinaryCache=true
kotlin.internal.native.enableReleaseBinaryCache=true
```

Remove leftovers such as `kotlin.native.disableCompilerDaemon=true` and `kotlin.native.cacheKind=none`
(2.3.20 replaced `cacheKind` with the `disableNativeCache(...)` DSL for targeted opt-outs).

## CI matrix

```yaml
# .github/workflows/kmp.yml
jobs:
  jvm-android-web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: 17 }
      - uses: gradle/actions/setup-gradle@v4
      - run: ./gradlew :shared:allTests          # Apple targets are skipped on Linux; add the Android host-test task
  apple:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: 17 }
      - uses: gradle/actions/setup-gradle@v4
      - uses: actions/cache@v4
        with: { path: ~/.konan, key: konan-${{ hashFiles('gradle/libs.versions.toml') }} }
      - run: ./gradlew :shared:iosSimulatorArm64Test
```

Confirm task names locally with `./gradlew :shared:tasks --all | grep -i test` (the Android host-test task
name derives from the `androidHostTest` source set) and pin action versions per your org policy.
