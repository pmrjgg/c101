# Kotlin Gradle troubleshooting cookbook

Companion to the `kotlin-gradle-builds` skill. Reproduce with `--stacktrace` (or `--info` for task
decisions), change one thing at a time, and keep a build scan or `--profile` report of before and after.

## Dependency resolution

```bash
./gradlew :app:dependencyInsight --dependency okhttp --configuration releaseRuntimeClasspath
./gradlew :app:dependencies --configuration releaseRuntimeClasspath > after.txt && diff before.txt after.txt
```

`dependencyInsight` prints the selected version and why: requested versions, "By conflict resolution:
between versions ...", "By constraint", "Selected by rule", forced or strict versions. Fix with the
least force that works:

| Tool | Use when |
|---|---|
| `platform(...)` BOM (`org.jetbrains.kotlin:kotlin-bom`, `kotlinx-coroutines-bom`, Compose BOM, OkHttp BOM) | a family of artifacts must share one version |
| `constraints { implementation("g:a:v") { because("...") } }` | raise a transitive version (CVE fix) without declaring a direct dependency |
| `version { strictly("x") }` | you must stay on exactly that version; fails loudly if something needs another |
| `exclude(group = "...", module = "...")` | a transitive artifact must not be on the classpath at all |
| `resolutionStrategy.failOnVersionConflict()` | audit run to list every conflict; remove afterwards |
| `capabilitiesResolution.withCapability("g:a") { selectHighestVersion() }` | two modules provide the same capability (relocated artifacts) |

Classic failures:

| Error | Cause | Fix |
|---|---|---|
| `Duplicate class kotlin.collections.jdk8.CollectionsJDK8Kt found in modules kotlin-stdlib-... and kotlin-stdlib-jdk8-...` | old `kotlin-stdlib-jdk7/jdk8` next to a newer stdlib that absorbed them | `implementation(platform("org.jetbrains.kotlin:kotlin-bom:<kotlin>"))` or upgrade the dependency pulling old stdlib |
| `Cannot select module with conflict on capability` | two artifacts declare the same capability | capability resolution rule (table above) |
| runtime `NoSuchMethodError` / `NoClassDefFoundError` from a library | a transitive upgrade or downgrade | `dependencyInsight`, then align with a BOM or constraint |
| `Could not resolve` only on CI | repository missing in `dependencyResolutionManagement`, or credentials | central repositories in settings with `FAIL_ON_PROJECT_REPOS` |

## Build-logic classpath

| Symptom | Cause | Fix |
|---|---|---|
| "The Kotlin Gradle plugin was loaded multiple times in different subprojects" | plugins applied with versions in several subprojects (separate classloaders) | declare in the root with `apply false`; subprojects apply without versions |
| `ClassNotFoundException` / `NoSuchMethodError` inside a plugin | plugin built against an API the current AGP/Gradle removed | upgrade the plugin; check `./gradlew buildEnvironment` for duplicate or unexpected versions |
| warning that `kotlin-dsl` relies on a different Kotlin than requested | build-logic forces a Kotlin version on its own compilation | let `kotlin-dsl` use Gradle's embedded Kotlin; KGP is only a `compileOnly` library there |
| convention plugin edits rebuild every module | conventions live in `buildSrc` or apply through `allprojects` | included build + per-module plugins |

## Configuration cache problems

Run `./gradlew <task> --configuration-cache` and open the HTML report linked at the end of the output.

| Problem (report wording) | Typical cause | Fix |
|---|---|---|
| "invocation of 'Task.project' at execution time is unsupported" | `doLast { project.version }`, `project.file(...)` in task actions | capture values at configuration time or declare `@Input`/`@InputFile` properties |
| "Starting an external process ... during configuration time is unsupported" | `Runtime.exec("git ...")` or `exec { }` in a build script | `providers.exec { commandLine(...) }.standardOutput.asText` |
| "cannot serialize object of type ... DefaultProject" | task field holding `Project`, `Configuration` or similar | store providers, file collections or plain values |
| build listener registration (`gradle.buildFinished`, `addBuildListener`) | legacy lifecycle hooks | build services or the dataflow-actions API |
| cache entry discarded every run although no problems | configuration reads a changing input (timestamp, git sha, env var) | read it lazily as a task input via providers; keep volatile values out of configuration |
| third-party plugin incompatible | plugin not ready | upgrade it; as a last resort mark its tasks with `notCompatibleWithConfigurationCache("reason")` |

`org.gradle.configuration-cache.problems=warn` lets the migration proceed, but Gradle 9 discards the
entry for incompatible tasks even in warning mode; do not ship with `warn`.

## Build cache misses

- `-Dorg.gradle.caching.debug=true` logs the cache key and every input hash; diff two runs.
- Compare two build scans of the same commit to find the input that differs.
- Usual culprits: absolute paths in inputs (annotate custom task file inputs with
  `@PathSensitive(PathSensitivity.RELATIVE)`), timestamps or build numbers baked into generated code,
  different JDK vendors or versions (use toolchains), non-deterministic annotation processors.
- `--info` prints "Caching disabled for task ... because:" for non-cacheable tasks.

## Daemons and memory

| Message | Fix |
|---|---|
| "Expiring Daemon because JVM heap space is exhausted", `java.lang.OutOfMemoryError: Java heap space` | raise `-Xmx` in `org.gradle.jvmargs` (4-8 GB for large Android builds) |
| `java.lang.OutOfMemoryError: Metaspace`, "Daemon disappeared" | add `-XX:MaxMetaspaceSize=1g`: setting `org.gradle.jvmargs` drops Gradle's defaults |
| "Could not connect to kotlin daemon. Using fallback strategy." | Kotlin daemon died or could not start: raise `kotlin.daemon.jvmargs`, `./gradlew --stop`, check temp directory permissions |
| GC above roughly 15% of build time (Build Analyzer) | more heap; try `-XX:+UseParallelGC` |
| builds slow after hours of use | `./gradlew --stop` and compare; then find the leaking plugin with a heap dump (`-XX:+HeapDumpOnOutOfMemoryError`) |

To take the Kotlin daemon out of the picture while debugging: `kotlin.compiler.execution.strategy=in-process`.

## KSP and kapt

| Error | Cause | Fix |
|---|---|---|
| processor reports unresolved types that another processor generates | the type comes from a kapt or javac processor that KSP cannot see | migrate that processor to KSP too (Dagger docs: AutoFactory output, `androidx.hilt` processors 1.4.x) |
| `[ksp]` errors about nullability or types that kapt accepted | KSP sees real Kotlin types instead of Java stubs | fix the declarations (nullable types, explicit generics) |
| stale or missing generated code after edits | incremental processing bug | `./gradlew clean`, or temporarily `ksp.incremental=false` to confirm, then report |
| Room: schema export errors | no schema location | Room Gradle plugin `room { schemaDirectory("$projectDir/schemas") }` |
| kapt plugin rejected under AGP 9 | built-in Kotlin | KSP, or `com.android.legacy-kapt` at the AGP version |

## AGP 9 upgrade failures

| Failure | Fix |
|---|---|
| `org.jetbrains.kotlin.android` applied with built-in Kotlin / new DSL | remove the plugin; temporary opt-out needs both `android.builtInKotlin=false` and `android.newDsl=false` (gone in AGP 10) |
| `applicationVariants` / `libraryVariants` no longer accessible | rewrite with `androidComponents { onVariants { variant -> ... } }` and the `Sources` API for generated code |
| KMP module with `com.android.library` | Android-KMP library plugin and a separate app module (`kotlin-multiplatform`) |
| classes missing at runtime after R8 | strict full mode: `-keep class A` no longer keeps the default constructor; write `-keep class A { <init>(); }` |
| duplicate namespace errors | `android.uniquePackageNames` is on by default: give every module its own namespace |
| behavior changes on devices | `targetSdk` now defaults to `compileSdk`: set it explicitly |
| `android.kotlinOptions` unresolved | `kotlin { compilerOptions { } }`; `jvmTarget` defaults to `compileOptions.targetCompatibility` |

## Gradle 9 upgrade failures

| Failure | Fix |
|---|---|
| `this@Build_gradle` unresolved | use `project`, `settings` or `gradle` |
| `Property<String?>` type errors | JSpecify nullness: `Property<String>`, use `orNull` / `convention()` |
| `exec { }` or `javaexec { }` unresolved in scripts | `providers.exec { }` at configuration time, or inject `ExecOperations` into a task |
| `jcenter()` unresolved | `mavenCentral()` |
| `project.convention` / `JavaPluginConvention` | extensions: `extensions.getByType<JavaPluginExtension>()` |
| test task fails: no tests discovered | fix filters or source sets; or `failOnNoDiscoveredTests = false` on that `Test` task |
| daemon refuses to start | run Gradle itself on JDK 17+ (`JAVA_HOME`, or `org.gradle.java.home`); toolchains still compile for older targets |
| "No matching toolchains found for requested specification" | foojay resolver plugin in settings, or list local JDKs in `org.gradle.java.installations.paths` |

## Toolchain and target mismatches

"Inconsistent JVM-target compatibility detected for tasks 'compileJava' (17) and 'compileKotlin' (21)":
set one `jvmToolchain(N)` (or Android `compileOptions`) in the convention plugin; only switch
`kotlin.jvm.target.validation.mode` to `warning` as a temporary bridge.
