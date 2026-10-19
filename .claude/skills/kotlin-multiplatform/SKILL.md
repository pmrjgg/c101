---
name: kotlin-multiplatform
description: "Kotlin Multiplatform engineering: target and source-set layout with the default hierarchy template and the Android-KMP library plugin, expect/actual vs interfaces with DI, KMP-ready libraries, iOS interop (@Throws, SKIE, Swift export), distribution as an XCFramework or SPM package, Kotlin/Native memory and build speed, and allTests CI. Load when sharing code across Android, iOS, JVM, desktop or web."
when_to_use: "Editing a kotlin { } block with android/androidTarget, iosArm64, iosSimulatorArm64, jvm or wasmJs targets, commonMain/iosMain source sets, expect/actual, XCFramework or Package.swift publishing; AGP 9 errors about androidTarget or com.android.library with KMP, 'The Default Kotlin Hierarchy Template was not applied', 'Module with the Main dispatcher is missing', iOS crashes from uncaught Kotlin exceptions, slow iOS link tasks, Undefined symbols linker errors."
---

# Kotlin Multiplatform

Baseline (October 2026): Kotlin 2.4.x (latest 2.4.21), Gradle 9.x, AGP 9.x with the Android-KMP library
plugin, Compose Multiplatform 1.12, SKIE 0.10.x, Ktor 3.x, SQLDelight 2.x, Room 2.8 and 3.0. Read the pins
in `gradle/libs.versions.toml` before writing code: KMP tooling changes every Kotlin release, so check DSL
names against the "What's new" page for the Kotlin version in use. Gradle mechanics live in
`kotlin-gradle-builds`; shared UI lives in `kotlin-compose`.

Deep material: [build recipes and Kotlin/Native tuning](references/build-and-native.md) |
[iOS interop and distribution](references/ios-interop-distribution.md)

## 1. Orient

```bash
./gradlew --version
grep -nE '^(kotlin|agp|compose|skie|ktor|sqldelight|room|coroutines) *=' gradle/libs.versions.toml
grep -rnE 'androidTarget|androidLibrary|kotlin\.android|iosArm64|iosSimulatorArm64|iosX64|wasmJs|js\(|jvm\(' --include=*.kts .
grep -rln '^expect ' --include=*.kt . | head                          # platform seams
grep -nE 'kotlin\.(mpp|native|incremental)|org\.gradle' gradle.properties
./gradlew :shared:tasks --all | grep -E 'XCFramework|embedAndSign|embedSwiftExport|Test$' | head -20
```

Record: targets, the one module that builds the Apple framework, the DI approach, how iOS consumes the
framework (direct integration, SPM, CocoaPods) and whether SKIE or Swift export is on.

## 2. Project shape

| Target | Declaration | Notes |
|---|---|---|
| Android library | `kotlin { android { } }` + plugin `com.android.kotlin.multiplatform.library` | required on AGP 9; `androidTarget()` with `com.android.library` is a configuration error there |
| JVM / desktop | `jvm()` | fastest test loop (`jvmTest`) |
| iOS device, simulator | `iosArm64()`, `iosSimulatorArm64()` | Tier 1 |
| Intel iOS simulator | `iosX64()` | Tier 3 since 2.3; Compose Multiplatform 1.11+ dropped it. Omit unless a dependency forces it |
| `macosX64`, `tvosX64`, `watchosX64` | | deprecated since 2.3.20, scheduled for removal; `watchosArm32` deprecated since 2.4.20 |
| Browser | `wasmJs { browser() }`, `js { browser() }` | section 9 |

Kotlin 2.4 raised Apple minimums to iOS/tvOS 15.0, macOS 12.0, watchOS 8.0.

```kotlin
// shared/build.gradle.kts
plugins {
    alias(libs.plugins.kotlin.multiplatform)
    alias(libs.plugins.android.kmp.library)        // com.android.kotlin.multiplatform.library
    alias(libs.plugins.kotlin.serialization)
}
kotlin {
    jvmToolchain(17)
    android {                                       // AGP < 8.12 spells it androidLibrary { }
        namespace = "com.example.shared"
        compileSdk = 36
        minSdk = 24
        withHostTest { }                            // Android tests are off by default
    }
    jvm()
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
        jvmMain.dependencies { implementation(libs.ktor.client.java) }
        iosMain.dependencies { implementation(libs.ktor.client.darwin) }
        commonTest.dependencies {
            implementation(kotlin("test"))
            implementation(libs.kotlinx.coroutines.test)
        }
    }
}
```

The default hierarchy template creates the intermediate source sets that match the declared targets:

```
common ─┬─ native ─┬─ apple ─┬─ ios / macos / tvos / watchos
        │          ├─ linux, mingw, androidNative
        └─ web ─── js, wasmJs            (webMain/webTest since Kotlin 2.2.20)
```

- Never add `dependsOn` between template source sets: one explicit edge disables the template and Gradle
  warns "The Default Kotlin Hierarchy Template was not applied to '<project>'".
- Need a set the template lacks (code shared by JVM and Android only)? Call `applyDefaultHierarchyTemplate()`,
  then create the extra set (recipe in [build-and-native](references/build-and-native.md)).
- Opt out wholesale only with `kotlin.mpp.applyDefaultHierarchyTemplate=false`, then wire every set by hand.

AGP 9 migration (recipe in the reference): move the app entry point (`com.android.application`,
`MainActivity`) into an `androidApp` module; swap `com.android.library` for the Android-KMP plugin and fold
`android { }` plus `androidTarget { }` into `kotlin { android { } }`; tests move to `androidHostTest` /
`androidDeviceTest`; there are no variants (`debugImplementation(x)` becomes `androidRuntimeClasspath(x)`;
no BuildConfig, view binding or `externalNativeBuild`; `withJava()` and `androidResources { enable = true }`
are opt-in). The stopgap `android.enableLegacyVariantApi=true` disappears in AGP 10.

## 3. Platform abstraction

| Need | Use | Why |
|---|---|---|
| tiny stateless shim (UUID, locale, file directory) | `expect fun` / `expect val` | one implementation per target, no lifecycle |
| stateful service (keychain, Bluetooth, location, analytics SDK) | interface in common + one class per platform, injected | several implementations, fakes in tests |
| choose an implementation at runtime (flag, A/B) | interface | expect/actual is compile time only |
| platform type in common signatures | `expect class` | Beta: warns unless `-Xexpect-actual-classes`; prefer interface + factory |
| a Swift-only API (pure Swift SDK, CryptoKit) | Kotlin interface implemented in Swift and passed in at startup | cinterop sees only Objective-C (or `@objc`-exported) APIs |

```kotlin
// commonMain
expect fun deviceName(): String                                       // shim
interface SecureStore { fun put(key: String, value: String); fun get(key: String): String? }
class SessionManager(private val store: SecureStore)
val sharedModule = module { singleOf(::SessionManager) }             // Koin 4
fun initKoin(platform: Module) = startKoin { modules(sharedModule, platform) }
// iosMain: Swift calls initKoinIos once at launch with its Keychain-backed SecureStore
actual fun deviceName(): String = UIDevice.currentDevice.name
fun initKoinIos(store: SecureStore) = initKoin(module { single<SecureStore> { store } })
```

Manual DI (one `SharedGraph` class built per app) suits small modules; Hilt and Dagger are JVM-only.

## 4. KMP-ready libraries

| Concern | Common artifact | Platform pieces and notes |
|---|---|---|
| async | `kotlinx-coroutines-core` | `Dispatchers.Main` off Android needs `kotlinx-coroutines-swing` (desktop) or `Dispatchers.setMain` (tests). `Dispatchers.IO` is an extension on JVM and Native only: `import kotlinx.coroutines.IO`; inject a dispatcher when JS/Wasm are targets |
| JSON | `kotlinx-serialization-json` + plugin `org.jetbrains.kotlin.plugin.serialization` (Kotlin version) | no reflection, every target |
| time | stdlib `kotlin.time.Instant`/`Clock` + `kotlinx-datetime` for `LocalDate`, `TimeZone` | kotlinx-datetime 0.7 moved `Instant`/`Clock` into the stdlib; `0.7.1-0.6.x-compat` keeps the old classes for lagging dependencies |
| HTTP | Ktor 3 `ktor-client-core`, `-content-negotiation`, `ktor-serialization-kotlinx-json` | engines: OkHttp or Android (Android), Darwin (Apple), Java/OkHttp (JVM), Js (browser JS), CIO (every target incl. wasmJs). `HttpClient()` without an engine picks the highest-priority engine on the classpath; tests use `ktor-client-mock` |
| SQL | SQLDelight 2 or Room KMP | table below |
| key-value | `androidx.datastore:datastore-preferences-core` (1.1+) | only Preferences DataStore is KMP; file path from `Context.filesDir` / `NSDocumentDirectory`; one instance per file |
| DI | Koin 4 (`koin-core`, `koin-compose-viewmodel`) or constructors | start from `Application.onCreate` and from the Swift `App` initializer |

| Criterion | SQLDelight 2.x | Room 2.8 KMP / Room 3.0 |
|---|---|---|
| source of truth | `.sq` SQL files generate typed queries | annotated entities and DAOs, KSP |
| targets | Android, JVM, Apple/native, JS (web worker) | Android, iOS, JVM, macOS, Linux; watchOS/tvOS in 2.8; JS and WasmJs in 3.0 |
| codegen | Gradle plugin, no annotation processing | KSP per target: `add("kspIosArm64", libs.room.compiler)` |
| flows | `asFlow().mapToList(dispatcher)` (`coroutines-extensions`) | DAO functions returning `Flow` |
| migrations | `.sqm` files, `verifyMigrations` | versioned `@Database`, auto-migrations, schema JSON |
| pick when | SQL-first team, explicit queries, JS target | Android team already on Room; Room 3 (`androidx.room3`) is KSP-only, coroutine-first, needs a `SQLiteDriver` |

## 5. iOS interop

| Kotlin declaration | Swift sees | Undeclared exception at the boundary |
|---|---|---|
| `fun f()` | non-throwing function | terminates the app |
| `@Throws(ApiError::class) fun f()` | `throws` | listed types and subclasses become `NSError`; others terminate |
| `suspend fun f()` | completion handler / `async throws` | only `CancellationException` propagates; anything else terminates |
| `@Throws(CancellationException::class, ApiError::class) suspend fun f()` | `async throws` | listed types become `Error` |

Rule: facade functions catch everything except `CancellationException` and return a sealed result, or
declare `@Throws` with `CancellationException::class` (or a supertype such as `Exception::class`) listed.

| Kotlin | Objective-C export | + SKIE | Swift export (Alpha in 2.4) |
|---|---|---|---|
| generic class `Box<T>` | lightweight generics, `T` nullable unless `T : Any` | same | erased to the upper bound |
| generic interface or function | generics lost | same | erased |
| sealed class / interface | class hierarchy, `switch` needs `default` | `switch onEnum(of: x)` exhaustive | Swift `enum` via `.sealedType()` (2.4.20) |
| `enum class` | class, `switch` needs `default` | real Swift enum | Swift enum |
| `suspend fun` | completion handler; `async` experimental | `async` with two-way cancellation, callable from any thread | `async` |
| `Flow<T>` | opaque, element type lost | `SkieSwiftFlow<T>` (an `AsyncSequence`); `StateFlow` → `SkieSwiftStateFlow` | `AsyncSequence` via `.asAsyncSequence()` |
| default arguments | every argument required | opt-in overloads (off by default, max 5 defaults) | |

SKIE (`id("co.touchlab.skie")`, only in the module that builds the framework) rewrites the generated
Swift API; each release supports specific Kotlin versions (0.10.15 added 2.4.20), so bump Kotlin only when
SKIE supports it. Swift export replaces the Objective-C header path: `kotlin { swiftExport { moduleName =
"Shared"; flattenPackage = "com.example.shared" } }` plus the Xcode phase
`./gradlew :shared:embedSwiftExportForXcode`; it works only with direct integration and is Alpha. Use one
of the two per framework.

Facade rules: (1) one module builds the Apple framework and `export(project(":core:model"))`s only types
Swift must name, never `transitiveExport = true`; (2) expose use-case classes with suspend functions and
Flows of plain data classes, keeping generics and value classes off the surface; (3) rename with
`@ObjCName(swiftName = "ArticleStore")` (opt-in `ExperimentalObjCName`), hide helpers with `@HiddenFromObjC`
and mark functions that get a Swift wrapper with `@ShouldRefineInSwift` (opt-in
`ExperimentalObjCRefinement`); `internal` declarations are never exported.

## 6. Distribution to iOS

| Option | Mechanism | Use when |
|---|---|---|
| direct integration | Xcode Run Script `./gradlew :shared:embedAndSignAppleFrameworkForXcode`, placed before Compile Sources, User Script Sandboxing off | monorepo, iOS developers build Kotlin locally |
| XCFramework + SwiftPM binary target | `assembleSharedReleaseXCFramework`, zip, `swift package compute-checksum`, `.binaryTarget(url:checksum:)` | separate iOS repo, consumers without a JDK |
| KMMBridge (Touchlab) | Gradle plugin automating XCFramework publishing to SPM (or CocoaPods) via GitHub releases, Maven or S3 | CI publishes every version |
| CocoaPods plugin `kotlin("native.cocoapods")` | podspec generation | legacy: CocoaPods trunk goes read-only (planned 2 December 2026); Kotlin 2.4 tooling can migrate a CocoaPods setup to SwiftPM |

```kotlin
import org.jetbrains.kotlin.gradle.plugin.mpp.apple.XCFramework
kotlin {
    val xcf = XCFramework("Shared")
    listOf(iosArm64(), iosSimulatorArm64()).forEach {
        it.binaries.framework {
            baseName = "Shared"
            binaryOption("bundleId", "com.example.shared")
            isStatic = true
            xcf.add(this)
        }
    }
}
```

```bash
./gradlew :shared:assembleSharedReleaseXCFramework     # shared/build/XCFrameworks/release/Shared.xcframework
cd shared/build/XCFrameworks/release && zip -qr Shared.xcframework.zip Shared.xcframework
swift package compute-checksum Shared.xcframework.zip  # paste into Package.swift with the upload URL
```

Ship one Kotlin framework per app: two frameworks each embed a Kotlin runtime and their own copy of shared
types (`A.User` and `B.User` are unrelated in Swift), so build an umbrella module. Kotlin 2.4 also consumes
Swift packages via `swiftPMDependencies { swiftPackage(...) }`. Package.swift template, KMMBridge and the
CocoaPods exit plan: [ios-interop-distribution](references/ios-interop-distribution.md).

## 7. Kotlin/Native runtime and build speed

Memory: objects cross threads freely. Freezing was deprecated in 1.7.20 and the legacy memory manager was
removed in 1.9.20, so delete `freeze()`, `ensureNeverFrozen()` and `FreezableAtomicReference` (use
`AtomicReference`). The concurrent mark-and-sweep collector is the default since 2.4.0; revert with
`kotlin.native.binary.gc=pmcs`. In Kotlin loops that create many Objective-C objects, wrap the body in
`autoreleasepool { }`. Binary options for GC, allocator and diagnostics are listed in
[build-and-native](references/build-and-native.md).

| Habit / setting | Effect |
|---|---|
| in development build only `embedAndSignAppleFrameworkForXcode` or `linkDebugFrameworkIosSimulatorArm64`; never `build`, `assemble` or `*XCFramework` | one target, debug mode |
| `kotlin.incremental.native=true` | incremental klib compilation (Beta since 2.4.20) |
| `kotlin.native.binary.enableReleaseBinaryCache=true` and `kotlin.internal.native.enableReleaseBinaryCache=true` | caches for release links (experimental, both needed) |
| `org.gradle.jvmargs=-Xmx3g` or more, `org.gradle.caching=true`, `org.gradle.configuration-cache=true` | general Gradle wins |
| cache `~/.konan` on CI (or set `konan.data.dir`) | no toolchain re-download or cache rebuild |
| delete stale `kotlin.native.disableCompilerDaemon`, `kotlin.native.cacheKind` lines | old workarounds that disable caching |
| drop `iosX64` and unused targets; build at least twice before comparing timings | fewer link tasks; honest numbers |

| Linker error | Cause | Fix |
|---|---|---|
| `Undefined symbols for architecture arm64: _OBJC_CLASS_$_...` | Kotlin calls a cinterop'd SDK the app target does not link | add the SDK to the Xcode target or package (`swiftPMDependencies` links it for you) |
| `No such module 'Shared'` | script phase after Compile Sources, sandboxing on, `baseName` mismatch | move the phase up, disable sandboxing, `./gradlew --stop`, align `baseName` |
| duplicate classes or symbols | two Kotlin frameworks in one app | umbrella framework; more rows in the iOS reference |

## 8. Testing

```kotlin
// commonTest: kotlin.test + kotlinx-coroutines-test, runs on every target
@OptIn(ExperimentalCoroutinesApi::class)                          // Dispatchers.setMain
class GreeterTest {
    @BeforeTest fun setUp() = Dispatchers.setMain(StandardTestDispatcher())
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test fun greetsWithPlatformName() = runTest {             // virtual time: delay() is skipped
        assertEquals("Hello, iPhone", Greeter(FakeDevice("iPhone")).greet())
    }
}
```

| Command | Runs |
|---|---|
| `./gradlew :shared:allTests` | every target runnable on this host; report `shared/build/reports/tests/allTests/index.html` (Android reports are separate) |
| `./gradlew :shared:jvmTest` | JVM only: the fast loop |
| `./gradlew :shared:iosSimulatorArm64Test` | native test binary on a simulator; macOS with Xcode only |
| `./gradlew :shared:tasks --all \| grep -i hosttest` | find the Android host-test task of the Android-KMP plugin (`androidHostTest` source set) |
| `./gradlew :shared:wasmJsTest` / `jsTest` | browser tests; need a headless browser |

- MockK runs only on JVM targets: write fakes (in-memory implementations of your interfaces) in
  `commonTest`; keep MockK in `jvmTest` or `androidHostTest`.
- Keep `commonTest` names plain identifiers: some native and JS targets reject backtick names with spaces.
- CI: Linux runner for JVM, Android and web; macOS runner for Apple targets; cache Gradle and `~/.konan`.

## 9. Web targets

| | `wasmJs` | `js` (IR) |
|---|---|---|
| status | Beta (2.2.20); Compose Multiplatform web Beta since CMP 1.9 | Stable |
| runtime | browsers with WasmGC: all major engines since December 2024 (Chrome 119+, Firefox 120+, Safari 18.2+) | any modern browser, Node.js |
| speed | faster than JS for compute, approaching JVM | JS-engine speed |
| interop | `external` declarations restricted to Wasm-compatible types, `JsAny` | full `external`, `dynamic`, `@JsExport` with TypeScript declarations |
| choose for | Compose Multiplatform web UI, compute-heavy shared logic | libraries consumed from JS/TS, DOM-heavy apps |
| shared code | `webMain` (both targets) | `webMain` |

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `Module with the Main dispatcher is missing` in desktop or JVM tests | no Main dispatcher off Android | `kotlinx-coroutines-swing` on desktop; `Dispatchers.setMain(StandardTestDispatcher())` in tests |
| iOS app terminates on a network error | Kotlin exception not listed in `@Throws` crossed into Swift | catch in the facade and return a sealed result; list `CancellationException` |
| `Unresolved reference: IO` in `commonMain` | `Dispatchers.IO` exists on JVM and Native only | `import kotlinx.coroutines.IO`, or inject the dispatcher |
| app download grows by tens of MB | exported modules, `transitiveExport`, heavy dependencies | export only facade types; try `binaryOption("smallBinary", "true")` (experimental) |
| build breaks after a Kotlin bump | SKIE pins Kotlin versions; Compose Multiplatform needs Kotlin 2.1.0+ (native/web features need 2.2.20+ for CMP 1.10, 2.3.10+ for 1.11); klibs built by a newer compiler | move Kotlin, SKIE, CMP and the Compose compiler plugin (always = Kotlin) together |
| AGP 9 configuration error on `androidTarget` | KMP with `com.android.library`/`application` unsupported | Android-KMP plugin and an `androidApp` module (section 2) |
| Swift sees `KotlinInt?` and `KotlinBoolean` boxes | nullable primitives and generics are boxed | non-null primitives at the facade, or SKIE/Swift export |
| Swift flow loops keep running after the screen closes | collection not tied to the view | collect inside SwiftUI `.task { }`, which cancels on disappear |

## 11. Worked example: Ktor + SQLDelight repository consumed from SwiftUI through SKIE

Pins: `kotlin = "2.4.20"` (SKIE 0.10.15 supports it), `agp = "9.3.1"`, `ktor = "3.6.0"`, `sqldelight =
"2.4.0"`, `skie = "0.10.15"`; plugins `alias(libs.plugins.sqldelight)` and `alias(libs.plugins.skie)`.

```kotlin
// shared/build.gradle.kts (additions to section 2)
commonMain.dependencies { implementation(libs.ktor.client.content.negotiation)
    implementation(libs.ktor.serialization.kotlinx.json); implementation(libs.sqldelight.coroutines) }
androidMain.dependencies { implementation(libs.sqldelight.android.driver) }
iosMain.dependencies { implementation(libs.sqldelight.native.driver) }
jvmTest.dependencies { implementation(libs.sqldelight.sqlite.driver) }   // same for androidHostTest
commonTest.dependencies { implementation(libs.ktor.client.mock) }
// top level:
sqldelight { databases { register("AppDatabase") { packageName.set("com.example.shared.db") } } }
```

```sql
-- shared/src/commonMain/sqldelight/com/example/shared/db/Article.sq
CREATE TABLE Article (id TEXT NOT NULL PRIMARY KEY, title TEXT NOT NULL, updatedAt INTEGER NOT NULL);
selectAll:
SELECT * FROM Article ORDER BY updatedAt DESC;
upsert:
INSERT OR REPLACE INTO Article(id, title, updatedAt) VALUES (?, ?, ?);
```

```kotlin
// commonMain/kotlin/com/example/shared/ArticleRepository.kt
data class ArticleItem(val id: String, val title: String, val updatedAt: Long)
sealed interface RefreshResult {
    data class Success(val count: Int) : RefreshResult
    data class Failure(val message: String) : RefreshResult
}
@Serializable internal data class ArticleDto(val id: String, val title: String, val updatedAt: Long)

internal fun createHttpClient(engine: HttpClientEngine) = HttpClient(engine) {
    expectSuccess = true                                          // non-2xx throws
    install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
}

class ArticleRepository internal constructor(
    private val client: HttpClient, private val db: AppDatabase,
    private val io: CoroutineDispatcher, private val baseUrl: String,
) {
    fun articles(): Flow<List<ArticleItem>> =
        db.articleQueries.selectAll(::ArticleItem).asFlow().mapToList(io)

    @Throws(CancellationException::class)                         // kotlin.coroutines.cancellation
    suspend fun refresh(): RefreshResult = try {
        val fresh: List<ArticleDto> = client.get("$baseUrl/articles").body()
        withContext(io) {
            db.articleQueries.transaction { fresh.forEach { db.articleQueries.upsert(it.id, it.title, it.updatedAt) } }
        }
        RefreshResult.Success(fresh.size)
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        RefreshResult.Failure(e.message ?: "refresh failed")
    }
}

// iosMain/kotlin/com/example/shared/IosGraph.kt  -> Swift: IosGraphKt.createArticleRepository()
fun createArticleRepository(): ArticleRepository = ArticleRepository(
    client = createHttpClient(Darwin.create()),
    db = AppDatabase(NativeSqliteDriver(AppDatabase.Schema, "articles.db")),
    io = Dispatchers.IO, baseUrl = "https://api.example.com",
)
```

```kotlin
// commonTest. Actuals: jvmTest and androidHostTest use
//   JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY).also { AppDatabase.Schema.create(it) }
// iosTest uses the native driver's inMemoryDriver(AppDatabase.Schema)
expect fun inMemoryDriver(): SqlDriver
class ArticleRepositoryTest {
    @Test fun refreshCachesAndEmitsNewestFirst() = runTest {
        val engine = MockEngine {
            respond("""[{"id":"a1","title":"Old","updatedAt":1},{"id":"a2","title":"New","updatedAt":2}]""",
                headers = headersOf(HttpHeaders.ContentType, "application/json"))
        }
        val repo = ArticleRepository(createHttpClient(engine), AppDatabase(inMemoryDriver()),
            StandardTestDispatcher(testScheduler), "https://test")
        assertEquals(RefreshResult.Success(2), repo.refresh())
        assertEquals(listOf("a2", "a1"), repo.articles().first().map { it.id })
    }
}
```

```swift
// iOS app (SKIE): Flow -> AsyncSequence, suspend -> async, sealed -> onEnum(of:)
import SwiftUI
import Shared

@MainActor final class ArticlesModel: ObservableObject {
    @Published private(set) var items: [ArticleItem] = []
    @Published private(set) var error: String?
    private let repository = IosGraphKt.createArticleRepository()
    func observe() async { for await list in repository.articles() { items = list } }
    func refresh() async {
        guard let result = try? await repository.refresh() else { return }   // CancellationError
        switch onEnum(of: result) {
        case .success: error = nil
        case .failure(let failure): error = failure.message
        }
    }
}
struct ArticlesView: View {
    @StateObject private var model = ArticlesModel()
    var body: some View {
        List(model.items, id: \.id) { Text($0.title) }
            .task { await model.observe() }          // cancelled on disappear, cancels the Kotlin collector
            .refreshable { await model.refresh() }
    }
}
```

Run it: `./gradlew :shared:allTests` (the test passes on `jvmTest` and `iosSimulatorArm64Test`: 2 rows
cached, newest first). In Xcode the Run Script phase calls `./gradlew :shared:embedAndSignAppleFrameworkForXcode`;
a separate iOS repo gets `assembleSharedReleaseXCFramework` plus the zip/checksum steps of section 6. Swift
surface: `articles()` returns `SkieSwiftFlow<[ArticleItem]>`, `refresh()` is `async throws -> RefreshResult`,
and network errors arrive as `.failure`, never as a crash.

Related: `kotlin-gradle-builds`, `kotlin-compose`, `kotlin-coroutines-flow`, `kotlin-testing`,
`kotlin-java-interop`, hub `kotlin-craft`
