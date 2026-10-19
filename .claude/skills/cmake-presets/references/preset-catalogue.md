# Preset catalogue, hardening target and clang-tidy baseline

Everything here was validated with `cmake --list-presets=all` on CMake 4.4; the multi-config
workflow (configure, build, test, package) and the clang coverage preset were run end to end.
Merge the snippets you need into the main `CMakePresets.json` (keep its `"version": 6`).

## Local overrides: CMakeUserPresets.json (never committed)

```json
{ "version": 6,
  "configurePresets": [ { "name": "my-dev", "inherits": "base",
    "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug", "CMAKE_CXX_COMPILER": "clang++",
                        "CMAKE_CXX_COMPILER_LAUNCHER": "ccache" } } ],
  "buildPresets": [ { "name": "my-dev", "configurePreset": "my-dev", "jobs": 12 } ] }
```

It may inherit hidden presets from `CMakePresets.json` (implicit include). Conan 2 generates
this file when a `layout()` is declared, but skips it if one already exists that Conan did not
generate; then add `"include": ["build/Release/generators/CMakePresets.json"]` yourself (the path
depends on the layout), or redirect Conan with the `user_presets_path` toolchain attribute.

## Ninja Multi-Config plus a package step

```json
"configurePresets": [
  { "name": "multi", "generator": "Ninja Multi-Config", "binaryDir": "${sourceDir}/build/multi",
    "cacheVariables": { "CMAKE_CONFIGURATION_TYPES": "Debug;RelWithDebInfo;Release",
                        "CMAKE_DEFAULT_BUILD_TYPE": "Debug" } } ],
"buildPresets": [
  { "name": "multi-debug", "configurePreset": "multi", "configuration": "Debug" },
  { "name": "multi-release", "configurePreset": "multi", "configuration": "Release" } ],
"testPresets": [
  { "name": "multi-release", "configurePreset": "multi", "configuration": "Release",
    "output": { "outputOnFailure": true } } ],
"packagePresets": [
  { "name": "release-tgz", "configurePreset": "multi", "generators": [ "TGZ" ], "configurations": [ "Release" ] } ],
"workflowPresets": [
  { "name": "multi-release", "steps": [ {"type": "configure", "name": "multi"},
    {"type": "build", "name": "multi-release"}, {"type": "test", "name": "multi-release"},
    {"type": "package", "name": "release-tgz"} ] } ]
```

Needs `include(CPack)` at the end of the top-level CMakeLists. `cmake --workflow multi-release`
produced `build/multi/geo-1.0.0-Darwin.tar.gz`. One build tree holds every configuration, so
`CMAKE_BUILD_TYPE` is ignored and each build/test/package preset names its configuration.

## Windows / MSVC

```json
{ "name": "msvc", "inherits": "base",
  "condition": { "type": "equals", "lhs": "${hostSystemName}", "rhs": "Windows" },
  "cacheVariables": { "CMAKE_CXX_COMPILER": "cl", "CMAKE_BUILD_TYPE": "Debug" } },
{ "name": "msvc-asan", "inherits": "msvc",
  "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo", "CMAKE_CXX_FLAGS": "/fsanitize=address /Zi /EHsc" } }
```

Ninja with `cl` needs a Developer Command Prompt environment (`vcvarsall.bat x64`, or
`ilammy/msvc-dev-cmd` in GitHub Actions). Setting `CMAKE_CXX_FLAGS` replaces CMake's default
`/EHsc`, hence it is repeated. MSVC has ASan only (no UBSan/TSan). For the Visual Studio generator
use `"generator": "Visual Studio 17 2022"`, `"architecture": { "value": "x64", "strategy": "set" }`.

## Lint, coverage, fast iteration, vcpkg

```json
{ "name": "lint", "inherits": "base",
  "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug", "CMAKE_CXX_CLANG_TIDY": "clang-tidy" } },
{ "name": "cov-clang", "inherits": "base",
  "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug", "CMAKE_CXX_COMPILER": "clang++",
    "CMAKE_CXX_FLAGS": "-fprofile-instr-generate -fcoverage-mapping",
    "CMAKE_EXE_LINKER_FLAGS": "-fprofile-instr-generate" } },
{ "name": "cov-gcc", "inherits": "base",
  "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug", "CMAKE_CXX_COMPILER": "g++",
    "CMAKE_CXX_FLAGS": "--coverage", "CMAKE_EXE_LINKER_FLAGS": "--coverage" } },
{ "name": "fast", "inherits": "base",
  "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug", "CMAKE_CXX_COMPILER_LAUNCHER": "ccache",
                      "CMAKE_UNITY_BUILD": "ON", "CMAKE_LINKER_TYPE": "LLD" } },
{ "name": "vcpkg", "hidden": true, "toolchainFile": "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" },
{ "name": "dev-vcpkg", "inherits": ["vcpkg", "base"], "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug" } }
```

Coverage test preset: `"environment": { "LLVM_PROFILE_FILE": "${sourceDir}/build/cov-clang/prof/%p-%m.profraw" }`
(one raw profile per process and binary; merge and report as in `cpp-testing-fuzzing`). A fuzz
preset is the clang preset plus `-DGEO_FUZZ=ON`; the fuzz targets add `-fsanitize=fuzzer` per target.

## Hardening INTERFACE target

```cmake
option(GEO_HARDENING "Production hardening flags" OFF)
add_library(geo_hardening INTERFACE)
add_library(geo::hardening ALIAS geo_hardening)
if(GEO_HARDENING)
  set(_gnu_like "$<CXX_COMPILER_ID:GNU,Clang,AppleClang>")
  set(_elf "$<AND:$<CXX_COMPILER_ID:GNU,Clang>,$<PLATFORM_ID:Linux>>")
  target_compile_definitions(geo_hardening INTERFACE        # each std library ignores the other's macro
    $<${_gnu_like}:_GLIBCXX_ASSERTIONS _LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST>)
  target_compile_options(geo_hardening INTERFACE
    $<${_gnu_like}:-fstack-protector-strong>
    $<${_elf}:-fstack-clash-protection>
    $<$<AND:${_elf},$<NOT:$<CONFIG:Debug>>>:-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3>   # needs optimization
    $<$<CXX_COMPILER_ID:MSVC>:/sdl /guard:cf>)
  target_link_options(geo_hardening INTERFACE
    $<${_elf}:LINKER:-z,relro,-z,now>
    $<$<CXX_COMPILER_ID:MSVC>:/guard:cf /CETCOMPAT>)
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64")
    target_compile_options(geo_hardening INTERFACE $<${_elf}:-fcf-protection=full>)
  elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
    target_compile_options(geo_hardening INTERFACE $<${_gnu_like}:-mbranch-protection=standard>)
  endif()
endif()
include(CheckPIESupported)
check_pie_supported()                      # then POSITION_INDEPENDENT_CODE ON on executables
```

On AppleClang 21 (arm64, Release) this produced `-D_GLIBCXX_ASSERTIONS
-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST -fPIE -fstack-protector-strong
-mbranch-protection=standard`. With the libc++ macro, `v[argc + 4]` on a 3-element vector trapped
(exit 133, SIGTRAP); without it the same binary returned garbage with exit 0. GCC 14+ users can
replace most of the list with `-fhardened`. C++26 standardizes a hardened standard-library mode
(precondition checks on `operator[]` and friends); until your toolchain ships it, these vendor
macros are the way to get it. Keep this target out of sanitizer presets: tests use
`-ftrivial-auto-var-init=pattern` (bugs stay visible), release uses `=zero`.

## clang-tidy baseline

```yaml
# .clang-tidy
Checks: >
  -*,bugprone-*,cert-*,clang-analyzer-*,concurrency-*,cppcoreguidelines-*,misc-*,modernize-*,
  performance-*,portability-*,readability-*,
  -modernize-use-trailing-return-type,-readability-identifier-length,
  -cppcoreguidelines-avoid-magic-numbers,-readability-magic-numbers
WarningsAsErrors: 'bugprone-*,cert-*,clang-analyzer-*,concurrency-*'
HeaderFilterRegex: '.*/(src|include)/.*'   # matched against absolute paths in CMake builds
```

High-value checks: `bugprone-use-after-move`, `bugprone-dangling-handle`,
`bugprone-exception-escape`, `cppcoreguidelines-owning-memory`,
`performance-unnecessary-copy-initialization`, `performance-move-const-arg`, `concurrency-mt-unsafe`.

```bash
git diff --name-only origin/main -- '*.cpp' | xargs clang-tidy -p build/dev   # changed files in CI
run-clang-tidy -p build/dev -quiet                                            # whole tree
git clang-format --diff origin/main                                           # format gate
```

The `lint` preset runs clang-tidy inside every compile (slow, but nothing is skipped); the
changed-files loop is the fast CI gate. Generated sources: `set_source_files_properties(gen.cpp
PROPERTIES SKIP_LINTING ON)` (3.27).
