# Compose performance diagnostics

Companion to the `kotlin-compose` skill. Measure first: only chase stability when recomposition counts,
traces or frame metrics show a real problem.

## Workflow

1. Reproduce on a release-like build (minified, `debuggable false`, baseline profile installed).
2. Layout Inspector: turn on recomposition counts, reset, run one scripted interaction (a fling, a
   toggle), read counts and skips per composable. A composable that recomposes once per frame while its
   inputs did not change is the lead.
3. Compiler reports: explain why that composable cannot skip (unstable parameter, unstable class).
4. Fix the cause (section below), rerun the same interaction, compare counts.
5. Lock in with a Macrobenchmark (`FrameTimingMetric`) and a baseline profile.

## Compose compiler reports

```kotlin
// module build.gradle.kts
composeCompiler {
    reportsDestination = layout.buildDirectory.dir("compose_compiler")
    metricsDestination = layout.buildDirectory.dir("compose_compiler")
}
```

Build a release variant (`./gradlew :app:assembleRelease`); debug builds give misleading numbers.

| File | Contains |
|---|---|
| `<module>-classes.txt` | stability of every class: `stable`, `unstable`, `runtime` per property and overall |
| `<module>-composables.txt` | each composable: `restartable`, `skippable`, and each parameter as `stable`, `unstable` or `@static` default |
| `<module>-composables.csv` | the same as a table for scripts and spreadsheets |
| metrics JSON (`metricsDestination`) | module totals: composables, restartable, skippable counts |

```
restartable skippable scheme("[androidx.compose.ui.UiComposable]") fun SnackCollection(
  stable snackCollection: SnackCollection
  stable onSnackClick: Function1<Long, Unit>
  stable modifier: Modifier? = @static Companion
)
unstable class Snack {
  stable val id: Long
  unstable val tags: Set<String>
  <runtime stability> = Unstable
}
```

Read it as: a `restartable` function without `skippable` re-runs whenever its parent recomposes; an
`unstable` parameter is compared by identity under strong skipping; `<runtime stability>` on generic
classes means stability is decided per type argument at runtime.

## Fix ladder for unstable parameters

1. Make the type truly immutable: `val` only, `ImmutableList`/`ImmutableSet`/`ImmutableMap` from
   `org.jetbrains.kotlinx:kotlinx-collections-immutable` (`persistentListOf()`, `toImmutableList()`).
2. Map data-layer types to UI models in the UI module (keeps Compose out of the domain layer).
3. Stability configuration file for types you do not own (`java.time.*`, model modules):

```kotlin
composeCompiler {
    stabilityConfigurationFiles.add(rootProject.layout.projectDirectory.file("stability_config.conf"))
}
```

   Entries are full names with `*` (one segment) or `**` (any depth) wildcards and optional generic
   masks (`com.example.Page<*,_>` = stable based on the first type parameter only). Partial-segment
   patterns such as `*Model` are not supported. The single-file property `stabilityConfigurationFile`
   also exists.
4. Data module compiled with the Compose compiler (only the runtime dependency is needed) so its
   classes can be inferred or annotated with `@Stable` / `@Immutable`.
5. `@Immutable` wrapper class around a `List` when nothing else fits.

Annotations and config entries are contracts, never checked: a mutable class declared stable stops the UI
from updating.

## Compose compiler feature flags (Kotlin 2.4)

| Flag | Status |
|---|---|
| `StrongSkipping` | default on since 2.0.20; ERROR-deprecated in 2.4 (cannot be disabled), removal in 2.5 |
| `IntrinsicRemember` | ERROR-deprecated in 2.4, removal in 2.5 |
| `OptimizeNonSkippingGroups` | deprecated in 2.4, removal in 2.6 |
| `PausableComposition` | deprecated in 2.4, removal in 2.6 |

Kotlin 2.4 also infers stability of `internal` types across files at runtime for consistent incremental
compilation (slightly larger artifacts until R8 strips them). Since Kotlin 2.3 the compiler adds Compose
group keys to R8 mapping files (`includeComposeMappingFile`, on by default); with Compose runtime 1.10+
call `Composer.setDiagnosticStackTraceMode(ComposeStackTraceMode.GroupKeys)` before any composition to
get readable stack traces from minified builds.

## Composition tracing

Add `androidx.compose.runtime:runtime-tracing` (debug or benchmark variant), record a system trace with
the Android Studio profiler or Perfetto, and composable names appear as trace sections. Look for long
`Recomposer` frames and for the same composable repeating every frame.

## Macrobenchmark

Module: `com.android.test` targeting `:app`; the app needs a `benchmark` build type (`initWith(release)`,
debug signing), must be `profileable`, and must include ProfileInstaller 1.3+. Run on a physical device.

```kotlin
@LargeTest
@RunWith(AndroidJUnit4::class)
class InboxScrollBenchmark {
    @get:Rule val rule = MacrobenchmarkRule()

    @Test fun scrollInbox() = rule.measureRepeated(
        packageName = "com.example.app",
        metrics = listOf(FrameTimingMetric()),
        iterations = 5,
        startupMode = StartupMode.WARM,
        compilationMode = CompilationMode.Partial(),
        setupBlock = { pressHome() },
    ) {
        startActivityAndWait()
        val list = device.findObject(By.res("inbox"))      // needs testTagsAsResourceId on a parent
        list.setGestureMargin(device.displayWidth / 5)
        list.fling(Direction.DOWN)
    }
}
```

Expose test tags to UI Automator once, near the root: `Modifier.semantics { testTagsAsResourceId = true }`.
Run with `./gradlew :macrobenchmark:connectedCheck`; results (JSON and traces) land under
`build/outputs/connected_android_test_additional_output/`. Compare `frameDurationCpuMs` and
`frameOverrunMs` percentiles before and after a change. Use `StartupTimingMetric` with
`StartupMode.COLD` for startup.

## Baseline profiles

```kotlin
// :baselineprofile module
plugins { id("com.android.test"); id("androidx.baselineprofile") }
android { targetProjectPath = ":app" }

// :app
plugins { id("androidx.baselineprofile") }
dependencies { baselineProfile(project(":baselineprofile")) }
```

```kotlin
@RunWith(AndroidJUnit4::class)
class BaselineProfileGenerator {
    @get:Rule val rule = BaselineProfileRule()
    @Test fun generate() = rule.collect(packageName = "com.example.app") {
        startActivityAndWait()
        device.findObject(By.res("inbox")).fling(Direction.DOWN)    // cover the critical scroll path
    }
}
```

`./gradlew :app:generateBaselineProfile` writes `src/<variant>/generated/baselineProfiles/baseline-prof.txt`
(the release variant). Profiles only apply to release builds; verify the gain with the Macrobenchmark
using `CompilationMode.Partial()` versus `CompilationMode.None()`.

## Jank causes beyond stability

| Cause | Sign | Fix |
|---|---|---|
| heavy work in composition (sorting, formatting, regex) | long composition sections in traces | move to the ViewModel or `remember(inputs)` |
| image decoding on the main thread | long draw/measure frames on first display | async image loading library with sized requests |
| nested scrolling containers in the same direction | measure exceptions or huge measure passes | one lazy list with heterogeneous item types |
| `SubcomposeLayout`/`BoxWithConstraints` in every row | expensive measure per item | measure once at the list level, pass sizes down |
| missing `contentType` in mixed lists | item compositions not reused | `contentType = { it.kind }` |
| first scroll janky, later smooth | JIT warm-up | baseline profile covering the scroll |
