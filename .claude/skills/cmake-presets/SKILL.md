---
name: cmake-presets
description: "Modern CMake builds: target-based rules, CMakePresets.json with configure, build, test and workflow presets, toolchains with a vcpkg manifest or Conan 2, FetchContent vs find_package, warning, hardening and sanitizer presets, clang-tidy and ccache, install/export packaging, and C++20 modules. Load when creating, fixing or modernizing a CMake build."
when_to_use: "Editing CMakeLists.txt, *.cmake, CMakePresets.json, CMakeUserPresets.json, vcpkg.json or conanfile.*; errors like 'Compatibility with CMake < 3.5 has been removed', 'requires target ... that is not in any export set', 'does not provide a way to discover the import graph dependencies'; adding CI, sanitizer or -Werror presets; packaging a library for find_package; cross-compiling or universal macOS builds."
---

# CMake presets and modern builds

Baseline: `cmake_minimum_required(VERSION 3.25...4.4)` (workflow presets need 3.25, C++ modules
3.28). The presets, install/export and worked example ran on CMake 4.4 + Ninja 1.13. Split:
`CMakeLists.txt` describes targets and their usage requirements; build-variant policy (build
type, sanitizers, `-Werror`, toolchain, launcher) lives in presets.

Deep material: [preset catalogue](references/preset-catalogue.md) | [dependencies, packaging and CI](references/deps-packaging-ci.md)

```bash
cmake --version; ninja --version
ls CMakePresets.json CMakeUserPresets.json vcpkg.json conanfile.* .clang-tidy 2>/dev/null
cmake --list-presets=all 2>/dev/null
grep -rnE 'CMAKE_CXX_FLAGS|include_directories\(|add_definitions\(|link_libraries\(|file\(GLOB' \
  --include=CMakeLists.txt --include='*.cmake' . | grep -v '/build/' | head -20
# record: minimum version, generator, dependency manager, existing presets, global-flag smells
```

## 1. Target-based rules

| Directory-global (remove) | Per target (write) |
|---|---|
| `set(CMAKE_CXX_FLAGS "... -std=c++17")` | `target_compile_features(geo PUBLIC cxx_std_20)` + `set(CMAKE_CXX_EXTENSIONS OFF)` before the targets (else `-std=gnu++20`) |
| `include_directories(include)` | `target_sources(geo PUBLIC FILE_SET HEADERS BASE_DIRS include FILES ...)` or `target_include_directories` with `$<BUILD_INTERFACE:>`/`$<INSTALL_INTERFACE:>` |
| `add_definitions(-DX)` | `target_compile_definitions(geo PUBLIC X)` |
| `link_libraries(pthread)`, `-lpthread` | `find_package(Threads REQUIRED)` + `target_link_libraries(app PRIVATE Threads::Threads)` |
| `-Wall` in `CMAKE_CXX_FLAGS` | INTERFACE warnings target (section 4) |
| `-fsanitize=`, `-Werror`, `-O3` in CMakeLists | presets (section 2) |
| `file(GLOB SRCS src/*.cpp)` | explicit source list |

Scope: `PRIVATE` = used to build this target only (implementation deps, warnings); `INTERFACE` =
consumers only (header-only libraries); `PUBLIC` = both, only when the dependency's types appear in
your public headers.

| Need | Generator expression |
|---|---|
| per compiler | `$<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wshadow>` |
| per configuration | `$<$<CONFIG:Debug>:GEO_CHECKS=1>` |
| language and compiler | `$<$<COMPILE_LANG_AND_ID:CXX,MSVC>:/permissive->` |
| build tree vs installed paths | `$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>` / `$<INSTALL_INTERFACE:include>` |
| private helper target that is not exported | `$<BUILD_INTERFACE:geo::warnings>` |
| inspect a genex | `file(GENERATE OUTPUT dbg.txt CONTENT "$<TARGET_PROPERTY:geo,COMPILE_OPTIONS>")` |

Every library gets `add_library(geo::geo ALIAS geo)`; consumers link `geo::geo` in-tree and after
`find_package`, and since a `::` name must be a target (CMP0028) a typo fails at configure time
instead of becoming `-lgeo`.

## 2. CMakePresets.json

| `version` | CMake | Adds |
|---|---|---|
| 6 | 3.25 | workflow and package presets, `outputJUnitFile` (3: `condition`, `toolchainFile`; 4: `include`) |
| 8 / 10 | 3.28 / 3.31 | `$schema` / `$comment`, `graphviz` |
| 12 | 4.4 | `testPassthroughArguments`, `errors.uninitialized`, `dev` renamed `author` |

Use the lowest version you need (6 for workflows). Template, validated with `cmake --workflow`:

```json
{
  "version": 6,
  "cmakeMinimumRequired": { "major": 3, "minor": 25, "patch": 0 },
  "configurePresets": [
    { "name": "base", "hidden": true, "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/${presetName}",
      "cacheVariables": { "CMAKE_EXPORT_COMPILE_COMMANDS": "ON" } },
    { "name": "dev", "inherits": "base", "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug" } },
    { "name": "ci", "inherits": "dev", "cacheVariables": { "CMAKE_COMPILE_WARNING_AS_ERROR": "ON" } },
    { "name": "release", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo", "CMAKE_INTERPROCEDURAL_OPTIMIZATION": "ON" } },
    { "name": "asan", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "CMAKE_CXX_FLAGS": "-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer",
        "CMAKE_EXE_LINKER_FLAGS": "-fsanitize=address,undefined",
        "CMAKE_SHARED_LINKER_FLAGS": "-fsanitize=address,undefined" } },
    { "name": "tsan", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "CMAKE_CXX_FLAGS": "-fsanitize=thread -fno-omit-frame-pointer",
        "CMAKE_EXE_LINKER_FLAGS": "-fsanitize=thread", "CMAKE_SHARED_LINKER_FLAGS": "-fsanitize=thread" } }
  ],
  "buildPresets": [
    { "name": "dev", "configurePreset": "dev" }, { "name": "ci", "configurePreset": "ci" },
    { "name": "release", "configurePreset": "release" },
    { "name": "asan", "configurePreset": "asan" }, { "name": "tsan", "configurePreset": "tsan" }
  ],
  "testPresets": [
    { "name": "base", "hidden": true, "output": { "outputOnFailure": true },
      "execution": { "jobs": 8, "noTestsAction": "error", "timeout": 300 } },
    { "name": "dev", "inherits": "base", "configurePreset": "dev" },
    { "name": "ci", "inherits": "base", "configurePreset": "ci", "output": { "outputJUnitFile": "junit.xml" } },
    { "name": "asan", "inherits": "base", "configurePreset": "asan",
      "environment": { "ASAN_OPTIONS": "abort_on_error=1:detect_stack_use_after_return=1",
                       "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1" } },
    { "name": "asan-leaks", "inherits": "asan",
      "condition": { "type": "equals", "lhs": "${hostSystemName}", "rhs": "Linux" },
      "environment": { "ASAN_OPTIONS": "detect_leaks=1:abort_on_error=1:detect_stack_use_after_return=1" } },
    { "name": "tsan", "inherits": "base", "configurePreset": "tsan",
      "environment": { "TSAN_OPTIONS": "halt_on_error=1:second_deadlock_stack=1" } }
  ],
  "workflowPresets": [
    { "name": "ci", "steps": [ {"type": "configure", "name": "ci"}, {"type": "build", "name": "ci"}, {"type": "test", "name": "ci"} ] },
    { "name": "asan", "steps": [ {"type": "configure", "name": "asan"}, {"type": "build", "name": "asan"}, {"type": "test", "name": "asan"} ] },
    { "name": "tsan", "steps": [ {"type": "configure", "name": "tsan"}, {"type": "build", "name": "tsan"}, {"type": "test", "name": "tsan"} ] }
  ]
}
```

```bash
cmake --preset dev && cmake --build --preset dev && ctest --preset dev
cmake --workflow asan                 # 3.31+; on 3.25-3.30: cmake --workflow --preset asan
cmake --preset ci --fresh --compile-no-warning-as-error   # new cache (3.24+), -Werror off locally
```

Rules: names are unique across both files; the first `inherits` parent wins a conflict; `"VAR":
null` drops an inherited cache value; a workflow starts with configure and every later step uses
that configure preset; test presets never build; a preset whose `condition` is false (`asan-leaks`
on macOS) fails with "Cannot use disabled test preset". `CMakeUserPresets.json` (gitignored,
implicitly includes `CMakePresets.json`) holds local compiler, launcher and job tweaks. User,
multi-config, MSVC, lint, coverage and fuzz presets: [preset catalogue](references/preset-catalogue.md).

## 3. Dependencies

| Situation | Choose |
|---|---|
| many deps, Windows + Linux + macOS | vcpkg manifest mode |
| prebuilt binaries, profiles, a company Conan remote | Conan 2 |
| 1-3 small deps or an unpackaged one | FetchContent with `FIND_PACKAGE_ARGS` |
| quick start with a shared source cache | CPM.cmake |
| distro packaging | plain `find_package`; the packager supplies deps |

**vcpkg** (`vcpkg.json` next to the top CMakeLists; `vcpkg x-update-baseline --add-initial-baseline`
writes the baseline):

```json
{ "name": "geo", "version": "1.0.0",
  "dependencies": [ "fmt", { "name": "catch2", "version>=": "3.8.1" } ],
  "builtin-baseline": "<40-hex commit of microsoft/vcpkg>",
  "overrides": [ { "name": "fmt", "version": "10.2.1" } ] }
```

Hidden `vcpkg` preset: `"toolchainFile": "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"`; extra
toolchain via `VCPKG_CHAINLOAD_TOOLCHAIN_FILE`, target via `VCPKG_TARGET_TRIPLET` (`arm64-linux`).

**Conan 2**: `conanfile.txt` = `[requires] fmt/10.2.1`, `[generators] CMakeDeps CMakeToolchain`,
`[layout] cmake_layout`; `conan profile detect --force`; `conan install . --build=missing -s
build_type=Release`; `cmake --preset conan-release` (multi-config: `conan-default`) and `cmake --build
--preset conan-release`. The generated `CMakeUserPresets.json` includes Conan's presets (CMake 3.23+).
Pin with `conan lock create .`.

**FetchContent** (prefer an installed package, fall back to source):

```cmake
include(FetchContent)
FetchContent_Declare(Catch2
  GIT_REPOSITORY https://github.com/catchorg/Catch2.git
  GIT_TAG        v3.8.1          # better: the full commit SHA; tags can be moved
  SYSTEM                         # 3.25: consumers get its headers as system headers
  EXCLUDE_FROM_ALL               # 3.28: build only what is linked
  FIND_PACKAGE_ARGS 3)           # 3.24: try find_package(Catch2 3) first
FetchContent_MakeAvailable(Catch2)
```

`FETCHCONTENT_TRY_FIND_PACKAGE_MODE`: `OPT_IN` (default: only declarations with
`FIND_PACKAGE_ARGS`), `ALWAYS`, `NEVER`. Archives: `URL ...` plus `URL_HASH SHA256=...`. Offline or
local checkout: `-DFETCHCONTENT_FULLY_DISCONNECTED=ON`, `-DFETCHCONTENT_SOURCE_DIR_CATCH2=/src/Catch2`.
Direct `FetchContent_Populate(<name>)` is deprecated (CMP0169, 3.30): use `FetchContent_MakeAvailable`.

**CPM.cmake**: commit `cmake/CPM.cmake` (from the CPM.cmake releases page), then
`CPMAddPackage("gh:fmtlib/fmt#10.2.1")`; share sources with `CPM_SOURCE_CACHE=$HOME/.cache/CPM`;
`CPM_USE_LOCAL_PACKAGES=ON` tries `find_package` first; `CPMUsePackageLock(package-lock.cmake)` pins.

## 4. Warnings, hardening and sanitizers

```cmake
add_library(geo_warnings INTERFACE)
add_library(geo::warnings ALIAS geo_warnings)
target_compile_options(geo_warnings INTERFACE
  $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wnon-virtual-dtor
    -Wold-style-cast -Wcast-align -Woverloaded-virtual -Wnull-dereference -Wdouble-promotion
    -Wformat=2 -Wimplicit-fallthrough>
  $<$<CXX_COMPILER_ID:GNU>:-Wduplicated-cond -Wlogical-op -Wuseless-cast>
  $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive- /w14640 /w14265>)
```

Link it `PRIVATE` (wrapped in `$<BUILD_INTERFACE:>` on exported libraries) so third-party code is
untouched; include third-party headers as `SYSTEM`. `-Werror` comes only from
`CMAKE_COMPILE_WARNING_AS_ERROR=ON` (3.24; property `COMPILE_WARNING_AS_ERROR`) in the `ci` preset,
so local builds show warnings without blocking; `LINK_WARNING_AS_ERROR` (4.0) does the same for links.
The variable initializes every target created later, FetchContent dependencies included; exempt them:

```cmake
set(CMAKE_COMPILE_WARNING_AS_ERROR OFF)   # normal variable shadows the cache entry
FetchContent_MakeAvailable(fmt)
unset(CMAKE_COMPILE_WARNING_AS_ERROR)     # the preset's cache value applies again
```

| Hardening (release presets; all low cost) | Effect |
|---|---|
| `-D_GLIBCXX_ASSERTIONS` / `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST` | libstdc++ / libc++ 18+ bounds and precondition checks (`_EXTENSIVE`, `_DEBUG` for tests) |
| `-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3` | checked libc calls; needs `-O1`+, the `-U` avoids redefinition warnings |
| `-fstack-protector-strong -fstack-clash-protection` | stack smashing and clash protection |
| `-fcf-protection=full` (x86) / `-mbranch-protection=standard` (AArch64) | CET / PAC+BTI; guard by `CMAKE_SYSTEM_PROCESSOR` |
| `-ftrivial-auto-var-init=zero` | no stack info leaks (tests use `=pattern` so bugs still show) |
| `-fhardened` (GCC 14+) | bundles most of the above |
| `LINKER:-z,relro,-z,now`, `POSITION_INDEPENDENT_CODE ON` + `check_pie_supported()` | RELRO, PIE/ASLR (ELF) |
| MSVC `/sdl /guard:cf`, link `/guard:cf /CETCOMPAT` | SDL checks, CFG, CET |
| as code | `option(GEO_HARDENING)`-gated INTERFACE target in [preset catalogue](references/preset-catalogue.md) |

Sanitizers get their own presets and build trees: ASan+UBSan together, TSan alone (not combinable
with ASan), MSVC `/fsanitize=address` only; no `_FORTIFY_SOURCE` there. Leak checks run on Linux only
(`asan-leaks`): Apple Clang's ASan aborts with "detect_leaks is not supported on this platform".

## 5. Tooling

| Tool | Setting | Notes |
|---|---|---|
| clangd, clang-tidy, IDEs | `CMAKE_EXPORT_COMPILE_COMMANDS=ON` | Makefile and Ninja generators only; `ln -sf build/dev/compile_commands.json .` |
| clang-tidy during the build | `"CMAKE_CXX_CLANG_TIDY": "clang-tidy"` in a separate `lint` preset | slows every compile; `SKIP_LINTING` source property (3.27) for generated files |
| clang-tidy on changed files | `git diff --name-only origin/main -- '*.cpp' \| xargs clang-tidy -p build/dev` | `run-clang-tidy -p build/dev -quiet` for the whole tree |
| ccache / sccache | `CMAKE_CXX_COMPILER_LAUNCHER=ccache` (or `sccache`) | ccache default max size 5 GiB; PCH needs `sloppiness = pch_defines,time_macros` (and `-fno-pch-timestamp` with Clang) |
| Ninja Multi-Config | `"generator": "Ninja Multi-Config"`, `CMAKE_CONFIGURATION_TYPES` | `CMAKE_BUILD_TYPE` ignored; build/test presets set `"configuration"` |
| unity builds | `CMAKE_UNITY_BUILD=ON` (batch size default 8) | clashing `static`/anonymous-namespace names break; `SKIP_UNITY_BUILD_INCLUSION` per file; module-scanned sources are excluded |
| precompiled headers | `target_precompile_headers(geo PRIVATE <vector> <string>)`, `REUSE_FROM other` | reuse only between targets with identical flags |
| faster linker | `CMAKE_LINKER_TYPE=LLD` or `MOLD` (3.29) | per target: `LINKER_TYPE` |
| slow-build triage | Clang `-ftime-trace`, open JSON in Perfetto | then modules or PCH, forward declarations, `extern template` |
| `.clang-tidy` baseline | checks, `WarningsAsErrors`, `HeaderFilterRegex` | in [preset catalogue](references/preset-catalogue.md) |

## 6. Testing with CTest

```cmake
include(CTest)                       # enable_testing() + BUILD_TESTING option (ON by default)
if(BUILD_TESTING)
  add_executable(geo_tests tests/test_geo.cpp)
  target_link_libraries(geo_tests PRIVATE geo::geo Catch2::Catch2WithMain)
  include(Catch)                     # FetchContent: list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
  catch_discover_tests(geo_tests ADD_TAGS_AS_LABELS DISCOVERY_MODE PRE_TEST)
  add_test(NAME db.setup COMMAND geo_tests "[db-setup]")
  add_test(NAME db.query COMMAND geo_tests "[db]")
  set_tests_properties(db.setup PROPERTIES FIXTURES_SETUP db)
  set_tests_properties(db.query PROPERTIES FIXTURES_REQUIRED db LABELS "integration" TIMEOUT 60)
endif()
```

GoogleTest: `include(GoogleTest)` + `gtest_discover_tests(t DISCOVERY_MODE PRE_TEST)` (3.18).
`PRE_TEST` discovers at `ctest` time instead of post-build: required when cross-compiling or when
the binary cannot run at build time. `RESOURCE_LOCK` serializes tests sharing a port or file.

```bash
ctest --preset dev -j 8 --output-on-failure      # flags override the preset
ctest --preset dev -L unit -LE slow              # label regex include/exclude
ctest --preset dev --repeat until-fail:50 --schedule-random   # flush flakes and order deps
ctest --preset dev --rerun-failed --output-on-failure
ctest --test-dir build/dev --no-tests=error --output-junit junit.xml
```

Preset equivalents: `"execution": {"repeat": {"mode": "until-fail", "count": 50}, "scheduleRandom": true}`.

## 7. Install and export

```cmake
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)
install(TARGETS geo EXPORT geoTargets FILE_SET HEADERS)        # lib, archive, headers
install(EXPORT geoTargets NAMESPACE geo:: DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/geo)
configure_package_config_file(cmake/geoConfig.cmake.in ${CMAKE_CURRENT_BINARY_DIR}/geoConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/geo)
write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/geoConfigVersion.cmake
  COMPATIBILITY SameMajorVersion)          # AnyNewerVersion|SameMinorVersion|ExactVersion; ARCH_INDEPENDENT for header-only
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/geoConfig.cmake ${CMAKE_CURRENT_BINARY_DIR}/geoConfigVersion.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/geo)
```

`cmake/geoConfig.cmake.in`:

```cmake
@PACKAGE_INIT@
include(CMakeFindDependencyMacro)
find_dependency(fmt 10)                    # one line per PUBLIC (and static-lib PRIVATE) dependency
include("${CMAKE_CURRENT_LIST_DIR}/geoTargets.cmake")
check_required_components(geo)
```

Verify like a consumer: `cmake --install build/release --prefix stage`, then a tiny project doing
`find_package(geo 1.0 REQUIRED)` + `target_link_libraries(c PRIVATE geo::geo)` with
`-DCMAKE_PREFIX_PATH=<abs>/stage`. "install(EXPORT ...) includes target geo which requires target
geo_warnings that is not in any export set": wrap the helper in `$<BUILD_INTERFACE:>`. CPack and
package presets: [deps, packaging and CI](references/deps-packaging-ci.md).

## 8. C++20 modules

```cmake
cmake_minimum_required(VERSION 3.28...4.4)
add_library(mathm)
target_sources(mathm PUBLIC FILE_SET CXX_MODULES FILES src/math.cppm)
target_compile_features(mathm PUBLIC cxx_std_20)
install(TARGETS mathm EXPORT mT FILE_SET CXX_MODULES DESTINATION ${CMAKE_INSTALL_LIBDIR}/cxx/mathm)
install(EXPORT mT NAMESPACE m:: DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/m CXX_MODULES_DIRECTORY cxx-modules)
```

| Requirement | Supported |
|---|---|
| compilers (scanning) | GCC 14+, Clang 16+, MSVC toolset 14.34+ (VS 17.4); clang-cl 19.1+ from CMake 4.4 (not with VS generators) |
| generators | Ninja / Ninja Multi-Config (ninja 1.11+), Visual Studio 17 2022, Visual Studio 18 2026 |
| `import std;` (CMake 3.30+) | Clang 18.1.2+ (libc++ or libstdc++), MSVC 14.36+, GCC 15+; Ninja only; still experimental in 4.4 |
| not supported | AppleClang (no `clang-scan-deps`), header units, Makefile generators |

`import std`: set `CMAKE_EXPERIMENTAL_CXX_IMPORT_STD` to the UUID your exact CMake version
documents (it changes per release) before `project()`, then `CMAKE_CXX_MODULE_STD ON` or the
`CXX_MODULE_STD` property on a `cxx_std_23` target. Scanning costs time: `CMAKE_CXX_SCAN_FOR_MODULES
OFF` where no modules are used. AppleClang fails with "...has C++ sources that may use modules, but
the compiler does not provide a way to discover the import graph dependencies": use Homebrew LLVM.
Modularize leaf libraries first; macros stay in headers.

## 9. Cross-compiling and CI

A toolchain file sets `CMAKE_SYSTEM_NAME`, `CMAKE_SYSTEM_PROCESSOR`, the cross compilers,
`CMAKE_SYSROOT`, `CMAKE_FIND_ROOT_PATH_MODE_{PROGRAM=NEVER, LIBRARY/INCLUDE/PACKAGE=ONLY}` and,
so `ctest` can run target binaries, `CMAKE_CROSSCOMPILING_EMULATOR` (e.g. `qemu-aarch64`); full
aarch64 file in [deps, packaging and CI](references/deps-packaging-ci.md). Preset:
`"toolchainFile": "${sourceDir}/cmake/toolchains/aarch64-linux-gnu.cmake"` plus `DISCOVERY_MODE
PRE_TEST` for test discovery. With vcpkg, keep vcpkg's toolchain and pass yours as
`VCPKG_CHAINLOAD_TOOLCHAIN_FILE`. macOS universal binary: `CMAKE_OSX_ARCHITECTURES="arm64;x86_64"`
(every dependency must also be universal; vcpkg ships per-arch triplets, so build per arch and
`lipo -create` or build deps from source). Check: `lipo -archs build/release/geo_cli`.

CI: one matrix entry per (OS, workflow preset), each step is `cmake --workflow <preset>`; YAML,
MSVC environment setup and caching are in [deps, packaging and CI](references/deps-packaging-ci.md).
vcpkg binary caching: the `x-gha` GitHub Actions provider was removed (vcpkg 2025.06.13); use NuGet
on GitHub Packages (`VCPKG_BINARY_SOURCES=clear;nuget,GitHub,readwrite`) or
`clear;files,<abs dir>,readwrite` plus `actions/cache` keyed on `hashFiles('vcpkg.json')`.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `-DCMAKE_BUILD_TYPE=Release` has no effect | multi-config generator (VS, Xcode, Ninja Multi-Config) | `cmake --build --config Release`, `"configuration"` in build/test presets |
| new `.cpp` not compiled | `file(GLOB)` evaluated at configure time | list sources; `CONFIGURE_DEPENDS` is not reliable on every generator |
| "Compatibility with CMake < 3.5 has been removed" | CMake 4 dropped old policy compatibility | `cmake_minimum_required(VERSION 3.25...4.4)`; for third-party code `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` |
| duplicate symbols or ODR crashes | Conan and vcpkg (or FetchContent and a system copy) both provide a library | one dependency manager per build tree |
| flags missing for consumers | `PRIVATE` where the dependency type is in a public header | `PUBLIC` |
| `-std=gnu++20` instead of `c++20` | `CXX_EXTENSIONS` defaults ON, per target (consumers of a fixed library still get gnu++) | `set(CMAKE_CXX_EXTENSIONS OFF)` before creating targets |
| third-party code fails the `ci` preset | `CMAKE_COMPILE_WARNING_AS_ERROR` applies to FetchContent targets | shadow and unset around `FetchContent_MakeAvailable` (section 4) |
| sanitizer build links but reports nothing | flags in `CMAKE_CXX_FLAGS` only, not the linker flags | set `CMAKE_EXE_LINKER_FLAGS` and `CMAKE_SHARED_LINKER_FLAGS` too |
| cache keeps an old value after editing a preset | cache variables persist | `--fresh` |
| `find_package` finds a stale system copy | search order | `CMAKE_PREFIX_PATH`, `<Pkg>_ROOT`, `--debug-find-pkg=<Pkg>` |

## 11. Worked example: legacy CMakeLists to targets, presets and an asan workflow

Before (configure fails under CMake 4.4 with the "< 3.5" error above):

```cmake
cmake_minimum_required(VERSION 2.8)
project(geo)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17 -Wall -O2")
include_directories(include)
add_definitions(-DGEO_USE_DOUBLE)
file(GLOB SRCS src/*.cpp)
add_library(geo ${SRCS})
add_executable(geo_cli app/main.cpp)
target_link_libraries(geo_cli geo)
enable_testing()
add_executable(geo_tests tests/test_geo.cpp)
target_link_libraries(geo_tests geo)
add_test(geo_tests geo_tests)
```

After:

```cmake
cmake_minimum_required(VERSION 3.25...4.4)
project(geo VERSION 1.0.0 LANGUAGES CXX)
include(GNUInstallDirs)
set(CMAKE_CXX_EXTENSIONS OFF)                       # every target: -std=c++20, not gnu++20
include(cmake/warnings.cmake)                       # section 4 INTERFACE target
add_library(geo src/area.cpp)
add_library(geo::geo ALIAS geo)
target_compile_features(geo PUBLIC cxx_std_20)
target_compile_definitions(geo PUBLIC GEO_USE_DOUBLE)
target_sources(geo PUBLIC FILE_SET HEADERS BASE_DIRS include FILES include/geo/geo.hpp)
target_link_libraries(geo PRIVATE $<BUILD_INTERFACE:geo::warnings>)
add_executable(geo_cli app/main.cpp)
target_link_libraries(geo_cli PRIVATE geo::geo geo::warnings)
include(CTest)
if(BUILD_TESTING)
  add_executable(geo_tests tests/test_geo.cpp)
  target_link_libraries(geo_tests PRIVATE geo::geo geo::warnings)
  add_test(NAME geo.area COMMAND geo_tests)
  set_tests_properties(geo.area PROPERTIES LABELS "unit" TIMEOUT 30)
endif()
# + the section 7 install/export block
```

`CMakePresets.json` is the section 2 template; `-O2` left CMakeLists (build types own it). Run:

```bash
cmake --list-presets=all            # dev ci release asan tsan + workflows ci asan tsan
cmake --workflow asan
```

The old test had always passed; the asan workflow failed it at once:

```text
==40980==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x6040000003c8 ...
READ of size 8 at 0x6040000003c8 thread T0
    #0 0x000102906e60 in geo::polygon_area(std::__1::vector<geo::Pt, std::__1::allocator<geo::Pt>> const&) area.cpp:9
0% tests passed, 1 tests failed out of 1
	  1 - geo.area (Subprocess aborted)                     unit
```

`area.cpp:9` read `pts[i + 1]` on the last vertex. Fix: `pts[(i + 1) % pts.size()]`. Then the
`asan`, `tsan` and `ci` workflows (compile line now `-std=c++20 ... -Wshadow -Werror`) report "100%
tests passed"; `cmake --install build/release --prefix stage` plus a `find_package(geo 1.0
REQUIRED)` consumer built and printed the expected area. CI runs the same workflows per OS.

Related: `cpp-testing-fuzzing` (test frameworks, fuzz targets, coverage presets),
`cpp-ub-sanitizers` (reading sanitizer reports), `cpp-simd-performance` (LTO, PGO, `-march`
presets), `cpp-memory-raii`, `cpp-concurrency-atomics`, hub `cpp-craft`.
