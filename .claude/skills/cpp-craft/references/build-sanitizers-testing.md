# CMake presets, warnings, hardening, sanitizers and tests

## 1. Target-based CMake rules

- `cmake_minimum_required(VERSION 3.28)` or newer for modules support; CMake 4.x removed
  compatibility with policies older than 3.5.
- Everything per target: `target_compile_features(lib PUBLIC cxx_std_23)`,
  `target_include_directories`, `target_link_libraries(... PRIVATE ...)`. Never set global
  `CMAKE_CXX_FLAGS` in `CMakeLists.txt`; flags that are build-variant policy go in presets.
- `PUBLIC` only for what consumers need in their own compile; everything else `PRIVATE`.
- Warnings as an INTERFACE target so third-party code is not affected:

```cmake
add_library(project_warnings INTERFACE)
target_compile_options(project_warnings INTERFACE
  $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wnon-virtual-dtor
    -Wold-style-cast -Wcast-align -Woverloaded-virtual -Wnull-dereference -Wdouble-promotion
    -Wformat=2 -Wimplicit-fallthrough>
  $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive- /w14640 /w14265>)
target_link_libraries(mylib PRIVATE project_warnings)
```

- Third-party headers included as `SYSTEM` (`target_include_directories(... SYSTEM ...)`) so their
  warnings do not fail the build.
- Dependencies: vcpkg manifest (`vcpkg.json` + `CMAKE_TOOLCHAIN_FILE` in the preset), Conan 2
  (`conan install . --build=missing` then the generated toolchain preset), or
  `FetchContent_Declare(name GIT_REPOSITORY ... GIT_TAG <sha> FIND_PACKAGE_ARGS)` which prefers
  an installed package and falls back to fetching. Pin to commit SHAs or release tags.

## 2. CMakePresets.json template (schema version 6+, CMake >= 3.25)

```json
{
  "version": 6,
  "configurePresets": [
    { "name": "base", "hidden": true, "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/${presetName}",
      "cacheVariables": { "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
                          "CMAKE_COMPILE_WARNING_AS_ERROR": "ON" } },
    { "name": "dev", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug" } },
    { "name": "release", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo",
                          "CMAKE_INTERPROCEDURAL_OPTIMIZATION": "ON" } },
    { "name": "asan", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "CMAKE_CXX_FLAGS": "-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer",
        "CMAKE_EXE_LINKER_FLAGS": "-fsanitize=address,undefined",
        "CMAKE_SHARED_LINKER_FLAGS": "-fsanitize=address,undefined" } },
    { "name": "tsan", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "CMAKE_CXX_FLAGS": "-fsanitize=thread",
        "CMAKE_EXE_LINKER_FLAGS": "-fsanitize=thread",
        "CMAKE_SHARED_LINKER_FLAGS": "-fsanitize=thread" } }
  ],
  "buildPresets": [
    { "name": "dev", "configurePreset": "dev" },
    { "name": "asan", "configurePreset": "asan" },
    { "name": "tsan", "configurePreset": "tsan" }
  ],
  "testPresets": [
    { "name": "dev", "configurePreset": "dev", "output": { "outputOnFailure": true },
      "execution": { "jobs": 8 } },
    { "name": "asan", "configurePreset": "asan", "output": { "outputOnFailure": true },
      "environment": { "ASAN_OPTIONS": "abort_on_error=1:detect_stack_use_after_return=1",
                       "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1" } },
    { "name": "asan-leaks", "inherits": "asan",
      "condition": { "type": "equals", "lhs": "${hostSystemName}", "rhs": "Linux" },
      "environment": { "ASAN_OPTIONS": "detect_leaks=1:abort_on_error=1:detect_stack_use_after_return=1" } },
    { "name": "tsan", "configurePreset": "tsan", "output": { "outputOnFailure": true },
      "environment": { "TSAN_OPTIONS": "halt_on_error=1:second_deadlock_stack=1" } }
  ],
  "workflowPresets": [
    { "name": "asan", "steps": [ { "type": "configure", "name": "asan" },
                                 { "type": "build", "name": "asan" },
                                 { "type": "test", "name": "asan" } ] },
    { "name": "tsan", "steps": [ { "type": "configure", "name": "tsan" },
                                 { "type": "build", "name": "tsan" },
                                 { "type": "test", "name": "tsan" } ] }
  ]
}
```

Leak checks run only on Linux (`ctest --preset asan-leaks` after the asan build): Apple Clang's ASan
runtime aborts with "detect_leaks is not supported on this platform" when `detect_leaks=1` is set.
`CMAKE_COMPILE_WARNING_AS_ERROR` (CMake 3.24+) can be overridden locally with
`cmake --preset dev --compile-no-warning-as-error`. Developer-specific tweaks go into the
untracked `CMakeUserPresets.json`.

## 3. Hardening flags (production builds)

| Flag | Effect | Cost |
|---|---|---|
| `-D_GLIBCXX_ASSERTIONS` | libstdc++ bounds/precondition checks (`operator[]`, `front`, ...) | low |
| `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST` | libc++ (18+) security-critical checks; `_EXTENSIVE` for more, `_DEBUG` for tests | low (fast) |
| `-D_FORTIFY_SOURCE=3` (with `-O2`) | checked libc string/memory calls | low |
| `-fstack-protector-strong`, `-fstack-clash-protection` | stack smashing / clash protection | low |
| `-fcf-protection=full` (x86) / `-mbranch-protection=standard` (AArch64) | CET / PAC+BTI control-flow integrity | low |
| `-ftrivial-auto-var-init=zero` | zero uninitialized stack vars (removes info leaks, hides bugs in tests: use `pattern` there) | low |
| `-fhardened` (GCC 14+) | bundles most of the above | low |
| `-Wl,-z,relro,-z,now`, `-fPIE -pie` | RELRO, ASLR | none to low |

C++26 standardizes a hardened library mode (precondition checks on `operator[]` and friends);
the vendor macros above are the way to get it today.

## 4. clang-tidy baseline

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

Run on changed files in CI: `git diff --name-only origin/main -- '*.cpp' | xargs clang-tidy -p build/dev`.
High-value checks: `bugprone-use-after-move`, `bugprone-dangling-handle`,
`bugprone-exception-escape`, `cppcoreguidelines-owning-memory`, `performance-unnecessary-copy-initialization`,
`performance-move-const-arg`, `concurrency-mt-unsafe`.

## 5. Catch2 v3

```cmake
find_package(Catch2 3 REQUIRED)            # or FetchContent
add_executable(unit_tests test_parse.cpp)
target_link_libraries(unit_tests PRIVATE mylib Catch2::Catch2WithMain)
include(Catch)
catch_discover_tests(unit_tests)
```

```cpp
#include <catch2/catch_test_macros.hpp>
#include <catch2/generators/catch_generators.hpp>

TEST_CASE("parse rejects malformed input", "[parse]") {
    auto bad = GENERATE(as<std::string>{}, "", "{", "[1,]", "\xff");
    CAPTURE(bad);
    REQUIRE_FALSE(parse(bad).has_value());
}

TEST_CASE("ring buffer", "[ring]") {
    Ring<int> r(2);
    SECTION("push within capacity") { r.push(1); CHECK(r.size() == 1); }
    SECTION("overflow drops oldest") { r.push(1); r.push(2); r.push(3); CHECK(r.front() == 2); }
}
```

Each `SECTION` re-runs the enclosing test case from the top, so setup is fresh per section.

## 6. GoogleTest / GoogleMock

```cmake
find_package(GTest REQUIRED)
add_executable(unit_tests test_cache.cpp)
target_link_libraries(unit_tests PRIVATE mylib GTest::gtest_main GTest::gmock)
include(GoogleTest)
gtest_discover_tests(unit_tests)
```

```cpp
class CacheTest : public ::testing::TestWithParam<std::size_t> {};
TEST_P(CacheTest, EvictsLeastRecentlyUsed) {
    LruCache<int, int> c(GetParam());
    for (int i = 0; i <= static_cast<int>(GetParam()); ++i) c.put(i, i);
    EXPECT_FALSE(c.get(0).has_value());
}
INSTANTIATE_TEST_SUITE_P(Sizes, CacheTest, ::testing::Values(1, 2, 64));

struct MockClock : Clock { MOCK_METHOD(std::chrono::nanoseconds, now, (), (const, override)); };
```

`EXPECT_*` continues after failure, `ASSERT_*` returns from the test. Death tests
(`EXPECT_DEATH`) for contract-violation checks. `--gtest_shuffle --gtest_repeat=50` to flush
order dependencies and flakes.

## 7. Fuzzing and property testing

```cpp
// fuzz_parse.cpp -- build with clang: -fsanitize=fuzzer,address,undefined
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    std::string_view in(reinterpret_cast<const char*>(data), size);
    auto r = parse(in);
    if (r) { auto s = serialize(*r); assert(parse(s).has_value()); }   // round-trip oracle
    return 0;
}
```

```bash
./fuzz_parse -max_total_time=600 -jobs=8 corpus/        # corpus dir persisted between runs
./fuzz_parse crash-<sha>                                # reproduce
```

Google FuzzTest integrates property-style fuzz tests into GoogleTest (`FUZZ_TEST(Suite, Prop)`);
RapidCheck provides QuickCheck-style properties. Every crash becomes a unit test.

## 8. Coverage

GCC: `--coverage` then `gcovr -r . --html-details cov.html`. Clang:
`-fprofile-instr-generate -fcoverage-mapping`, run with `LLVM_PROFILE_FILE=t.profraw`, then
`llvm-profdata merge -o t.profdata t.profraw && llvm-cov show ./unit_tests -instr-profile=t.profdata`.

## 9. Modules (C++20) status notes

- Named modules work with CMake 3.28+ and Ninja using `target_sources(lib PUBLIC FILE_SET CXX_MODULES FILES a.cppm)`.
- `import std;` is supported by recent MSVC, libc++ and libstdc++; CMake support was
  experimental behind `CMAKE_CXX_MODULE_STD` and a gate variable; verify for the CMake in use.
- Mixed header/module codebases: modularize leaf libraries first; keep macros in headers.
