# Dependencies, packaging, cross-compiling and CI

## vcpkg manifest mode in depth

| Task | How |
|---|---|
| start a manifest | `vcpkg new --application` (writes `vcpkg.json` and a `vcpkg-configuration.json` whose `default-registry` carries the baseline), then `vcpkg add port fmt` |
| pin the registry | either that configuration baseline or `"builtin-baseline": "<commit>"` in `vcpkg.json`; `vcpkg x-update-baseline --add-initial-baseline` adds the latter, `vcpkg x-update-baseline` bumps baselines (experimental command) |
| minimum version | `{ "name": "catch2", "version>=": "3.8.1" }` |
| exact version | `"overrides": [ { "name": "fmt", "version": "10.2.1" } ]` |
| optional dependency groups | `"features": { "tests": { "description": "...", "dependencies": ["catch2"] } }` + `VCPKG_MANIFEST_FEATURES=tests` |
| patched or private port | overlay: `VCPKG_OVERLAY_PORTS=${sourceDir}/ports` (cache variable) |
| target triplet | `VCPKG_TARGET_TRIPLET=x64-windows-static`, `arm64-linux`, `arm64-osx` |
| your own toolchain as well | `VCPKG_CHAINLOAD_TOOLCHAIN_FILE=<file>` (vcpkg's toolchain stays `CMAKE_TOOLCHAIN_FILE`) |

Binary caching (`VCPKG_BINARY_SOURCES`, semicolon-separated, evaluated before `--binarysource`):

| Source | Use |
|---|---|
| `clear` | drop the defaults first |
| `files,<absolute path>,readwrite` | shared disk or a directory cached by CI |
| `nuget,<feed>,readwrite` / `nugetconfig,<path>` | GitHub Packages, Azure Artifacts (vcpkg team's recommendation for GitHub) |
| `http,<url template>,readwrite[,<header>]` | any HTTP store; template variables `{name}`, `{version}`, `{sha}`, `{triplet}` |
| `x-azblob`, `x-gcs`, `x-aws`, `x-cos` | cloud buckets (experimental) |
| `x-gha` | removed in vcpkg 2025.06.13 after the GitHub cache API change; migrate |

The ABI hash covers port files, triplet, compiler, features, dependency hashes and the CMake
version; a compiler upgrade therefore misses the cache once. Use a vcpkg checkout pinned by the
repo (submodule or a fixed commit), not whatever copy a CI image happens to ship.

## Conan 2

```ini
# conanfile.txt
[requires]
fmt/10.2.1
[generators]
CMakeDeps
CMakeToolchain
[layout]
cmake_layout
```

```bash
conan profile detect --force                 # writes ~/.conan2/profiles/default from the local compiler
conan install . --build=missing -s build_type=Release
cmake --preset conan-release                  # multi-config generators: cmake --preset conan-default
cmake --build --preset conan-release
conan lock create .                           # conan.lock pins the full graph; commit it
```

Generated: `conan_toolchain.cmake`, `<pkg>-config.cmake` files from `CMakeDeps`, a
`CMakePresets.json` in the generators folder and a top-level `CMakeUserPresets.json` that includes
it. Settings (`-s compiler.cppstd=20`) and options (`-o fmt/*:shared=True`) live in profiles, not
in CMakeLists. Never point one build at both Conan and vcpkg toolchains.

## FetchContent and CPM details

```cmake
include(FetchContent)
FetchContent_Declare(fmt
  URL      https://github.com/fmtlib/fmt/releases/download/10.2.1/fmt-10.2.1.zip
  URL_HASH SHA256=<sha256 of that archive>      # `shasum -a 256 fmt-10.2.1.zip`
  FIND_PACKAGE_ARGS 10.2)
FetchContent_MakeAvailable(fmt)
```

- Declarations are first-come: the top-level project can pin a version that sub-projects also
  declare, because later `FetchContent_Declare` calls for the same name are ignored.
- `FETCHCONTENT_SOURCE_DIR_<UPPERNAME>=/path` uses a local checkout (debugging a dependency);
  `FETCHCONTENT_FULLY_DISCONNECTED=ON` forbids network access after the first populate;
  `FETCHCONTENT_TRY_FIND_PACKAGE_MODE=ALWAYS` makes every declaration try `find_package` first.
- Dependency providers (3.24): `cmake_language(SET_DEPENDENCY_PROVIDER ...)` from a file listed in
  `CMAKE_PROJECT_TOP_LEVEL_INCLUDES` lets a package manager intercept `find_package` and
  `FetchContent_MakeAvailable` without editing the project.
- CPM.cmake: `CPMAddPackage("gh:fmtlib/fmt#10.2.1")` (`GIT_TAG` defaults to `v<VERSION>` when only
  a version is given); `CPM_SOURCE_CACHE` env var shares downloads across build trees;
  `CPM_LOCAL_PACKAGES_ONLY=ON` errors instead of downloading; `CPMUsePackageLock(package-lock.cmake)`
  plus the `cpm-update-package-lock` target writes the lock file.

## Install/export extras

- Build-tree export for sibling projects without installing:
  `export(EXPORT geoTargets NAMESPACE geo:: FILE ${CMAKE_CURRENT_BINARY_DIR}/geoTargets.cmake)`.
- Version ranges on the consumer side: `find_package(geo 1.0...<2.0 REQUIRED)` (3.19+).
- Components: `install(TARGETS geo_io EXPORT geoTargets COMPONENT io)` plus
  `check_required_components(geo)` in the config file; consumers ask `find_package(geo COMPONENTS io)`.
- Shared libraries: set `VERSION`/`SOVERSION` target properties; on Linux pair with
  `CMAKE_INSTALL_RPATH` (`$ORIGIN/../lib`) for relocatable installs; on macOS `@rpath`.
- Header-only library: `add_library(geo INTERFACE)`, `FILE_SET HEADERS`, and
  `write_basic_package_version_file(... ARCH_INDEPENDENT)`.
- CPack: set `CPACK_GENERATOR` (`TGZ`, `ZIP`, `DEB`, `RPM`, `WIX`, `DragNDrop`), `include(CPack)`
  last; drive it with a package preset (`generators`, `configurations`, `packageDirectory`) and a
  workflow step of type `package`.

## Cross-compiling toolchain file (aarch64 Linux)

```cmake
# cmake/toolchains/aarch64-linux-gnu.cmake
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
set(CMAKE_SYSROOT /opt/sysroots/aarch64)               # when you have one
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)           # build tools come from the host
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(CMAKE_CROSSCOMPILING_EMULATOR qemu-aarch64;-L;/usr/aarch64-linux-gnu)   # ctest runs target binaries
```

Pair it with `DISCOVERY_MODE PRE_TEST` in `gtest_discover_tests`/`catch_discover_tests` so test
discovery happens under the emulator at `ctest` time instead of failing at build time. With Clang
use `CMAKE_CXX_COMPILER clang++` plus `CMAKE_CXX_COMPILER_TARGET aarch64-linux-gnu`.

macOS universal: `CMAKE_OSX_ARCHITECTURES="arm64;x86_64"` in the preset, `CMAKE_OSX_DEPLOYMENT_TARGET`
for the minimum OS. Every linked library must contain both slices (`lipo -archs libfoo.a`); vcpkg
has no universal triplet, so build `arm64-osx` and `x64-osx` trees and `lipo -create` the outputs,
or build those dependencies from source with FetchContent.

## GitHub Actions matrix driven by workflow presets

```yaml
name: ci
on: [push, pull_request]
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - { os: ubuntu-latest,  workflow: ci }
          - { os: ubuntu-latest,  workflow: asan }
          - { os: ubuntu-latest,  workflow: tsan }
          - { os: macos-latest,   workflow: ci }
          - { os: windows-latest, workflow: ci-msvc }
    runs-on: ${{ matrix.os }}
    env:
      VCPKG_BINARY_SOURCES: "clear;files,${{ github.workspace }}/.vcpkg-cache,readwrite"
    steps:
      - uses: actions/checkout@v4
        with: { submodules: true }                    # vcpkg pinned as a submodule
      - uses: lukka/get-cmake@latest                  # current CMake and Ninja
      - uses: ilammy/msvc-dev-cmd@v1                  # cl.exe environment for Ninja
        if: runner.os == 'Windows'
      - uses: actions/cache@v4
        with:
          path: .vcpkg-cache
          key: vcpkg-${{ runner.os }}-${{ hashFiles('vcpkg.json', 'vcpkg-configuration.json') }}
          restore-keys: vcpkg-${{ runner.os }}-
      - run: cmake --workflow ${{ matrix.workflow }}
        env: { VCPKG_ROOT: "${{ github.workspace }}/vcpkg" }
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: "junit-${{ matrix.os }}-${{ matrix.workflow }}", path: "build/*/junit.xml" }
```

`ci-msvc` is a workflow over the MSVC presets from the preset catalogue. The cache key ignores the
compiler version; the vcpkg ABI hash still rebuilds what changed. A whole-tree `actions/cache` of
`vcpkg_installed` is the fallback when no binary source is available, at the cost of rebuilding
everything when one port changes.
