# Kotlin: Java interop, Multiplatform and Compose

## 1. Java calling Kotlin

| Kotlin construct | What Java sees | Make it Java-friendly |
|---|---|---|
| top-level functions in `Utils.kt` | `UtilsKt.fn()` | `@file:JvmName("Utils")` |
| companion object members | `Foo.Companion.bar()` | `@JvmStatic`; constants `const val` or `@JvmField` |
| default arguments | one method with all params | `@JvmOverloads` (constructors and functions) |
| properties | `getX()`/`setX()`; `isX()` for `isX` booleans | `@JvmField` to expose a field, `@get:JvmName` to rename |
| `suspend fun` | extra `Continuation` parameter, returns `Object` | provide `fun loadAsync(): CompletableFuture<T> = scope.future { load() }` |
| value class parameters | mangled method names (`foo-abc123`), not callable | avoid in Java-facing APIs; `@JvmName` on functions taking value classes; 2.2+ `@JvmExposeBoxed` (experimental) |
| `object` singleton | `Foo.INSTANCE.method()` | `@JvmStatic` on members |
| checked exceptions | not declared | `@Throws(IOException::class)` so Java can catch them |
| `internal` | public in bytecode with mangled name | do not rely on it for encapsulation from Java |
| `Nothing`, `Unit` | `Void`, `void`/`Unit` instance | keep Java-facing signatures plain |
| read-only `List<T>` | `java.util.List<T>` (mutable interface) | Java can mutate it; hand out copies or immutable collections |
| `sealed` classes | abstract classes/interfaces | Java callers should not rely on exhaustiveness; keep a fallback branch on the Java side |
| function types `(A) -> B` | `Function1<A, B>`; Unit-returning lambdas need `return Unit.INSTANCE` | use `fun interface` for Java-implemented callbacks |

## 2. Kotlin calling Java

- Platform types (`T!`): Kotlin will not stop you calling methods on a null. Annotate Java with
  JSpecify (`@NullMarked` package/class, `@Nullable`), or declare explicit Kotlin types at the
  boundary. Legacy annotations (JSR-305, JetBrains, Android) are understood too; Spring uses
  JSpecify (Framework 7) or JSR-305 (`-Xjsr305=strict` makes it enforced).
- SAM conversion works for Java functional interfaces: `executor.execute { run() }`.
- Java getters/setters appear as properties (`user.name`); `is`-prefixed booleans keep the name.
- Java `static` members are accessed as `JavaClass.member`; no companion involved.
- Java collections are mutable platform collections; copy before exposing as Kotlin read-only types.
- Checked exceptions are not enforced in Kotlin; document and handle the important ones.

Framework compiler plugins:

| Plugin | Purpose |
|---|---|
| `kotlin("plugin.spring")` | all-open for Spring-annotated classes (proxies need non-final) |
| `kotlin("plugin.jpa")` | no-arg constructors for `@Entity`/`@Embeddable` |
| `kotlin("plugin.serialization")` | kotlinx.serialization code generation |
| `jackson-module-kotlin` (library) | Jackson support for Kotlin constructors, nullability, default values |

JPA entities: regular classes (not data classes) with `var` fields and identity-based
`equals`/`hashCode`; data classes break with lazy proxies and mutable IDs.

## 3. Kotlin Multiplatform project shape

```kotlin
kotlin {
    jvmToolchain(21)
    androidTarget()
    jvm()
    iosArm64(); iosSimulatorArm64()
    listOf(iosArm64(), iosSimulatorArm64()).forEach {
        it.binaries.framework { baseName = "Shared"; isStatic = true }
    }
    sourceSets {
        commonMain.dependencies {
            implementation(libs.kotlinx.coroutines.core)
            implementation(libs.kotlinx.serialization.json)
            implementation(libs.ktor.client.core)
        }
        androidMain.dependencies { implementation(libs.ktor.client.okhttp) }
        iosMain.dependencies { implementation(libs.ktor.client.darwin) }
        commonTest.dependencies { implementation(kotlin("test")) }
    }
}
```

The default hierarchy template creates intermediate source sets (`appleMain`, `iosMain`,
`nativeMain`) automatically; do not hand-wire `dependsOn` unless you need a custom shape.

Platform abstraction:

| Need | Approach |
|---|---|
| small platform function (UUID, time zone, file path) | `expect fun` in common, `actual fun` per platform |
| platform service with state (keychain, Bluetooth) | interface in common, implementations per platform, injected (Koin, manual DI) |
| platform type in common signatures | `expect class` (beta stability); prefer interfaces |

iOS interop rules:
- Kotlin exceptions not declared with `@Throws` crash when they reach Swift; `suspend`
  functions are exported as completion-handler / `async` functions that can throw
  `CancellationException` (declare `@Throws(CancellationException::class, MyError::class)`).
- Generics and sealed classes export imperfectly through Objective-C headers; SKIE improves
  sealed classes, flows and suspend functions; Swift export (alpha in 2.4) exports Kotlin
  directly to Swift, including `Flow` → `AsyncSequence`.
- Keep the exported API small: a facade module (`shared`) that exposes use cases, not the whole
  domain model.
- Kotlin/Native GC: the modern memory manager (default since 1.7.20) has no freezing; objects can
  be shared across threads normally.

Testing: `commonTest` with `kotlin.test` and `runTest`; run `./gradlew allTests` (all targets) or
`./gradlew jvmTest iosSimulatorArm64Test`.

## 4. Compose essentials (Jetpack Compose and Compose Multiplatform)

Mental model: composables are functions of state; Compose re-runs (recomposes) the ones whose
inputs changed. They may run often, in any order, and be skipped.

| Need | API |
|---|---|
| local UI state surviving recomposition | `var x by remember { mutableStateOf(0) }` |
| survive configuration change / process death | `rememberSaveable` |
| derived value from frequently changing state | `val show by remember { derivedStateOf { listState.firstVisibleItemIndex > 0 } }` |
| run suspend work tied to a key | `LaunchedEffect(key) { ... }` (cancelled/restarted when key changes) |
| register/unregister a listener | `DisposableEffect(key) { ...; onDispose { ... } }` |
| publish Compose state to non-Compose code | `SideEffect { }` |
| collect a flow as state (Android) | `val s by vm.state.collectAsStateWithLifecycle()` |
| launch from a callback (click) | `val scope = rememberCoroutineScope()` |
| stable list item identity | `LazyColumn { items(list, key = { it.id }) { ... } }` |

State hoisting: stateless composable `Counter(count: Int, onIncrement: () -> Unit)` plus a
stateful wrapper or ViewModel that owns the state. Screen state is one immutable `UiState` data
class exposed as `StateFlow<UiState>`.

Performance rules:
- Parameters should be stable: immutable data classes with `val`s of stable types; Kotlin
  collections from other modules are not inferred stable (use `kotlinx.collections.immutable`
  or a stability configuration file). Strong skipping mode (default with the Compose compiler
  since Kotlin 2.0.20) also skips on instance equality of unstable params.
- Defer reads of fast-changing state to layout/draw phase with lambda modifiers:
  `Modifier.offset { IntOffset(0, scroll.value) }` instead of `Modifier.offset(y = scroll.value.dp)`.
- Never write to state that was already read in the same composition (backwards write loop).
- Measure: Layout Inspector recomposition counts; compiler reports via
  `composeCompiler { reportsDestination = layout.buildDirectory.dir("compose_compiler") }`.
- `Modifier` order matters (`padding().background()` differs from `background().padding()`).

Compose Multiplatform shares UI across Android, iOS (stable since 1.8), desktop and web (Wasm);
resources via `composeResources`; platform views embedded with `UIKitView` / `AndroidView`.
