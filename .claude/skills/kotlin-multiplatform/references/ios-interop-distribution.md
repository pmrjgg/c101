# iOS interop and distribution

Companion to the `kotlin-multiplatform` skill: what Swift sees, how SKIE and Swift export change it, and
how the framework reaches an Xcode project. Kotlin 2.4.x, SKIE 0.10.x, Xcode 26.x (October 2026).

## What Swift sees (Objective-C export)

| Kotlin | Swift | Notes |
|---|---|---|
| `class` | `class` | final unless `open`; constructors become initializers |
| `interface` | `protocol` | no generics on protocols |
| `enum class` | `class` | `switch` needs `default` (SKIE: real enum) |
| `object Foo` / `companion object` | `Foo.shared` / `Bar.companion` | `Foo()` access is deprecated |
| `Int`, `Long`, `Boolean`, `Double` | `Int32`, `Int64`, `Bool`, `Double` | |
| `Int?`, `Boolean?`, generic `T` with primitives | `KotlinInt?`, `KotlinBoolean?` (NSNumber subclasses) | cast manually: `NSNumber` is not auto-converted back |
| `String` | `String` | |
| `List`, `Set`, `Map` | `[T]`, `Set<T>`, `[K: V]` | mutable variants map to `NSMutable*` / `KotlinMutable*` |
| function type `(Int) -> Unit` | `(KotlinInt) -> KotlinUnit` | primitives boxed in lambdas; return `KotlinUnit()` |
| value (inline) class | unsupported | passed as the underlying type or `id`; keep off the facade |
| top-level `fun f()` in `Repo.kt` | `RepoKt.f()` | the file name becomes the Swift facade class: name facade files deliberately |
| extension on a Kotlin class | Swift extension | extensions on Kotlin interfaces or built-ins become `...Kt` static helpers |
| `suspend fun` | `completionHandler:` / `async` (experimental) | needs `@Throws` for errors other than cancellation |

Generics exist only on classes ("lightweight generics"); variance is lost; declare `T : Any` to keep a
generic non-null in the header. `-Xno-objc-generics` turns them off entirely.

## Exceptions

- Non-suspend function without `@Throws`: no Kotlin exception propagates; any exception terminates.
- With `@Throws(A::class, B::class)`: instances of `A`, `B` and subclasses become `NSError` (`throws` in
  Swift); others terminate.
- Suspend function without `@Throws`: only `CancellationException` propagates (as `NSError`).
- Swift errors do not become Kotlin exceptions in the reverse direction.

Pattern for a facade:

```kotlin
class ApiError(message: String) : Exception(message)

@Throws(CancellationException::class, ApiError::class)
suspend fun loadProfile(id: String): Profile = try {
    api.profile(id)
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    throw ApiError(e.message ?: "profile failed")           // the only error type Swift has to handle
}
```

## SKIE

Applied with `id("co.touchlab.skie") version "0.10.15"` in the module that builds the framework (Maven
Central must be in `pluginManagement` repositories). It also instruments exported dependencies.

| Feature | Swift result |
|---|---|
| sealed classes and interfaces | `switch onEnum(of: value) { case .loading: ...; case .error(let e): ... }`, exhaustive; non-exported subclasses fall into `.else` |
| enums | real Swift enums |
| `Flow<T>`, `StateFlow<T>`, `MutableStateFlow<T>` | `SkieSwiftFlow<T>`, `SkieSwiftStateFlow<T>`, `SkieSwiftMutableStateFlow<T>`; `Flow<Int?>` becomes `SkieSwiftOptionalFlow<Int>` |
| `suspend fun` | Swift `async`, callable from any thread; cancelling the Swift `Task` cancels the coroutine; Kotlin-side cancellation surfaces as `CancellationError` |
| default arguments | extra overloads, disabled by default (enable per declaration with SKIE annotations); at most 5 defaults (31 extra functions) per function |

Flow cancellation semantics: when Kotlin cancels a Flow, SKIE does not throw; the Swift `for await` loop
just ends. Use `withTaskCancellationHandler` if Swift must react.

```kotlin
// configure features per package prefix
import co.touchlab.skie.configuration.FlowInterop
skie {
    features {
        group("com.example.shared.internal") { FlowInterop.Enabled(false) }
    }
}
```

Per-declaration annotations (`@FlowInterop.Enabled`, `@FlowInterop.Disabled`, ...) need the SKIE
`configuration-annotations` dependency in the source set; annotations override Gradle groups unless the
group sets `overridesAnnotations = true`. Disable SKIE completely with `skie { isEnabled.set(false) }`.

Kotlin upgrade rule: SKIE hooks into compiler internals, so each SKIE release lists the Kotlin versions it
supports (0.10.15 added 2.4.20). Bump Kotlin and SKIE in the same change, after checking SKIE's release
notes.

## Swift export (Alpha in Kotlin 2.4)

```kotlin
kotlin {
    iosArm64(); iosSimulatorArm64()
    swiftExport {
        moduleName = "Shared"
        flattenPackage = "com.example.shared"            // drop the package prefix in Swift
        export(project(":core:model")) { moduleName = "Model"; flattenPackage = "com.example.model" }
        configure { freeCompilerArgs.add("-Xexpect-actual-classes") }
    }
}
```

Xcode: in the Run Script phase replace `embedAndSignAppleFrameworkForXcode` with
`./gradlew :shared:embedSwiftExportForXcode`. Requirements and status:

- only with direct integration (no XCFramework, CocoaPods or remote SPM flow yet);
- `suspend` becomes `async`; `Flow` becomes `AsyncSequence` via `.asAsyncSequence()`; suspending calls run
  on `Dispatchers.Default` unless the Kotlin code switches with `withContext`;
- sealed hierarchies map to Swift enums through `.sealedType()` (2.4.20); Swift classes may subclass
  exported `open` Kotlin classes and implement Kotlin interfaces (2.4.20);
- generic types are erased to their upper bounds; subclasses of `List`/`Set`/`Map` are skipped;
- APIs that need opt-in need module-level `compilerOptions { optIn.add("...") }`.

Pick SKIE for production apps that need a stable toolchain today; trial Swift export on a branch and
track its release notes.

## Direct integration (Xcode builds Kotlin)

Run Script phase, placed before Compile Sources, with "Based on dependency analysis" unchecked:

```sh
if [ "YES" = "$OVERRIDE_KOTLIN_BUILD_IDE_SUPPORTED" ]; then
  echo "Skipping Gradle build task invocation due to OVERRIDE_KOTLIN_BUILD_IDE_SUPPORTED environment variable set to \"YES\""
  exit 0
fi
cd "$SRCROOT/.."
./gradlew :shared:embedAndSignAppleFrameworkForXcode
```

Then disable User Script Sandboxing (Build Settings, Build Options) and run `./gradlew --stop` once if a
sandboxed daemon already exists. Custom Xcode configurations need the user-defined setting
`KOTLIN_FRAMEWORK_BUILD_TYPE` = `Debug` or `Release`. The task exists only when a `binaries.framework` is
declared for the iOS targets.

## XCFramework as a remote Swift package

```bash
./gradlew :shared:assembleSharedReleaseXCFramework
cd shared/build/XCFrameworks/release
zip -qr Shared.xcframework.zip Shared.xcframework
swift package compute-checksum Shared.xcframework.zip
# upload the zip (GitHub release asset, artifact store) and verify the link with curl
```

```swift
// swift-tools-version:5.3
import PackageDescription

let package = Package(
    name: "Shared",
    platforms: [.iOS(.v15)],                     // match the Kotlin minimum (15.0 since Kotlin 2.4)
    products: [.library(name: "Shared", targets: ["Shared"])],
    targets: [
        .binaryTarget(
            name: "Shared",
            url: "https://example.com/releases/1.4.0/Shared.xcframework.zip",
            checksum: "<output of swift package compute-checksum>")
    ]
)
```

Validate with `swift package reset && swift package show-dependencies --format json`, push, and tag the
package repository with the semantic version. Recommended layout: `Package.swift` in its own repository
(SwiftPM versions by git tag, which would collide with the Kotlin repository's tags). When the module
itself consumes SwiftPM packages, newer KGP versions can generate `Package.swift` next to the XCFramework
(documented for 2.4.20 and 2.5.0-Beta1; check the version in use).

Other tasks: `assembleXCFramework` (all build types), `assembleSharedDebugXCFramework` (development
builds). XCFramework tasks build every Apple target, so keep them off the inner development loop.

KMMBridge (Touchlab) wraps this flow in a Gradle plugin: it builds the XCFramework on CI, uploads it to
GitHub Releases, a Maven repository (including GitHub Packages) or a public S3 bucket, and updates the
SPM manifest (CocoaPods support exists but is not the focus).

## Leaving CocoaPods

CocoaPods trunk is scheduled to become read-only on 2 December 2026: existing pods keep resolving but no
new versions are published. For Kotlin projects:

- Consuming iOS SDKs from Kotlin: Kotlin 2.4 declares Swift packages in Gradle and the KMP tooling can
  migrate a CocoaPods-based setup automatically.

```kotlin
kotlin {
    swiftPMDependencies {
        swiftPackage(
            url = url("https://github.com/firebase/firebase-ios-sdk.git"),
            version = from("12.11.0"),
            products = listOf(product("FirebaseAnalytics")),
        )
    }
}
```

- Shipping the Kotlin framework: replace the generated podspec with direct integration or the
  XCFramework + SwiftPM flow above.
- cinterop still sees only Objective-C APIs (or Swift APIs exported with `@objc`); for pure Swift SDKs,
  define a Kotlin interface and implement it in Swift.

## Linker and runtime errors

| Error | Cause | Fix |
|---|---|---|
| `Undefined symbols for architecture arm64: _OBJC_CLASS_$_FIRApp` | Kotlin links against an SDK the app target does not embed | add the SDK to the app (SPM/Xcode) or declare it in `swiftPMDependencies` |
| `building for 'iOS-simulator', but linking in object file built for 'iOS'` | device framework in a simulator build | use the XCFramework, or `embedAndSign...`, which picks the slice from Xcode's SDK |
| `No such module 'Shared'` | Run Script runs after Compile Sources, sandboxing on, stale daemon | reorder, disable sandboxing, `./gradlew --stop` |
| `ld: framework 'Shared' not found` after renaming | `baseName` differs from the import name | align `baseName`, `XCFramework("Shared")` and the Swift `import` |
| duplicate symbols, two `KotlinBase` classes | two Kotlin frameworks linked into one app | one umbrella framework exporting the needed modules |
| crash log without Kotlin line numbers | no source info in the binary | `binaryOption("sourceInfoType", "libbacktrace")` for debug builds; upload dSYMs for release |
| `iosSimulatorArm64Test` cannot find or boot a simulator on CI | simulator runtime missing from the image, or Xcode outside the Kotlin version's supported range | install the runtime; pick a macOS runner image whose Xcode the Kotlin release supports |
