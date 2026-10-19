# Sanitizer CI: presets, suppressions, MSan libc++, workflows

## CMakePresets.json (schema 6+, CMake >= 3.25)

Sanitizer flags are build-variant policy: they live in presets, never in `CMakeLists.txt`.
`RelWithDebInfo` keeps optimisation-dependent UB visible and gives symbolised stacks.

```json
{
  "version": 6,
  "configurePresets": [
    { "name": "base", "hidden": true, "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/${presetName}",
      "cacheVariables": { "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
                          "CMAKE_COMPILE_WARNING_AS_ERROR": "ON" } },
    { "name": "asan", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "CMAKE_CXX_FLAGS": "-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer",
        "CMAKE_EXE_LINKER_FLAGS": "-fsanitize=address,undefined",
        "CMAKE_SHARED_LINKER_FLAGS": "-fsanitize=address,undefined" } },
    { "name": "tsan", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "CMAKE_CXX_FLAGS": "-fsanitize=thread -fno-omit-frame-pointer",
        "CMAKE_EXE_LINKER_FLAGS": "-fsanitize=thread",
        "CMAKE_SHARED_LINKER_FLAGS": "-fsanitize=thread" } },
    { "name": "msan", "inherits": "base",
      "condition": { "type": "equals", "lhs": "${hostSystemName}", "rhs": "Linux" },
      "cacheVariables": { "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "CMAKE_CXX_COMPILER": "clang++",
        "CMAKE_CXX_FLAGS": "-fsanitize=memory -fsanitize-memory-track-origins=2 -fno-omit-frame-pointer -stdlib=libc++ -nostdinc++ -isystem $env{MSAN_LIBCXX}/include/c++/v1",
        "CMAKE_EXE_LINKER_FLAGS": "-fsanitize=memory -stdlib=libc++ -L$env{MSAN_LIBCXX}/lib -Wl,-rpath,$env{MSAN_LIBCXX}/lib" } },
    { "name": "ubsan-trap", "inherits": "base",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "Release",
        "CMAKE_CXX_FLAGS": "-fsanitize=undefined -fsanitize-trap=all" } }
  ],
  "buildPresets": [
    { "name": "asan", "configurePreset": "asan" },
    { "name": "tsan", "configurePreset": "tsan" },
    { "name": "msan", "configurePreset": "msan" },
    { "name": "ubsan-trap", "configurePreset": "ubsan-trap" }
  ],
  "testPresets": [
    { "name": "asan", "configurePreset": "asan", "output": { "outputOnFailure": true },
      "environment": { "ASAN_OPTIONS": "abort_on_error=1:detect_stack_use_after_return=1:check_initialization_order=1:strict_string_checks=1",
                       "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1:suppressions=${sourceDir}/ci/ubsan.supp" } },
    { "name": "asan-leaks", "inherits": "asan",
      "condition": { "type": "equals", "lhs": "${hostSystemName}", "rhs": "Linux" },
      "environment": { "ASAN_OPTIONS": "detect_leaks=1:abort_on_error=1:detect_stack_use_after_return=1",
                       "LSAN_OPTIONS": "suppressions=${sourceDir}/ci/lsan.supp" } },
    { "name": "tsan", "configurePreset": "tsan", "output": { "outputOnFailure": true },
      "environment": { "TSAN_OPTIONS": "halt_on_error=1:second_deadlock_stack=1:history_size=7:suppressions=${sourceDir}/ci/tsan.supp" } },
    { "name": "msan", "configurePreset": "msan", "output": { "outputOnFailure": true },
      "environment": { "MSAN_OPTIONS": "halt_on_error=1" } }
  ],
  "workflowPresets": [
    { "name": "asan", "steps": [ { "type": "configure", "name": "asan" },
                                 { "type": "build", "name": "asan" },
                                 { "type": "test", "name": "asan" } ] },
    { "name": "tsan", "steps": [ { "type": "configure", "name": "tsan" },
                                 { "type": "build", "name": "tsan" },
                                 { "type": "test", "name": "tsan" } ] },
    { "name": "msan", "steps": [ { "type": "configure", "name": "msan" },
                                 { "type": "build", "name": "msan" },
                                 { "type": "test", "name": "msan" } ] }
  ]
}
```

Run: `cmake --workflow --preset asan`, then on Linux `ctest --preset asan-leaks` for LeakSanitizer
(Apple clang's runtime aborts on `detect_leaks=1`). `CMAKE_COMPILE_WARNING_AS_ERROR` (CMake 3.24+)
can be overridden locally with `--compile-no-warning-as-error`. Developer tweaks go in the
untracked `CMakeUserPresets.json`. MSVC: a separate preset with `"CMAKE_CXX_FLAGS": "/fsanitize=address /Zi"`
and no `/RTC` or edit-and-continue debug format.

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

Run on changed files in CI:
`git diff --name-only origin/main -- '*.cpp' | xargs clang-tidy -p build/asan`, or the whole tree
with `run-clang-tidy -p build/asan -quiet`. High-value checks for UB hunting:
`bugprone-use-after-move`, `bugprone-dangling-handle`, `bugprone-exception-escape`,
`bugprone-undefined-memory-manipulation`, `bugprone-sizeof-expression`,
`bugprone-unchecked-optional-access`, `cppcoreguidelines-owning-memory`,
`performance-unnecessary-copy-initialization`, `performance-move-const-arg`,
`concurrency-mt-unsafe`. Clang static analyzer over the whole build: scan-build works by substituting `CC`/`CXX`, which
CMake caches at configure time, so configure a fresh directory under it:
`scan-build cmake -S . -B build-scan -G Ninja && scan-build -o scan-out cmake --build build-scan`
(HTML reports in `scan-out/`).

## Suppression and ignore files

Every entry carries a reason and an issue link; CI fails on unexplained entries.

```text
# ci/tsan.supp  (types: race, race_top, mutex, thread, signal, deadlock, called_from_lib)
# libfoo stats counter is racy by design upstream: https://example.org/libfoo/issues/1234
race:libfoo::Stats::bump
# prebuilt vendor library without TSan instrumentation
called_from_lib:libvendor.so

# ci/ubsan.supp  (check:location; only recoverable checks; groups like "undefined" are rejected)
# legacy codec relies on wraparound, rewrite tracked in PROJ-567
signed-integer-overflow:src/legacy/codec.cpp

# ci/lsan.supp
# fontconfig caches allocations for the process lifetime
leak:libfontconfig.so
```

Compile-time ignore lists remove instrumentation instead of hiding reports; use them for
deliberately racy or hot code only (`-fsanitize-ignorelist=ci/asan_ignore.txt`):

```text
[address]
fun:*simd_kernel_hot*
src:third_party/legacy/*
```

## MemorySanitizer with an instrumented libc++ (Linux, Clang; not run here)

MSan reports every byte that flows from uninstrumented code, so the C++ standard library itself
must be built with MSan. libc++ ships a cache file for exactly this (`Generic-msan.cmake` sets
`LLVM_USE_SANITIZER=MemoryWithOrigins` and keeps the system unwinder):

```bash
git clone --depth=1 --branch release/<clang-major>.x https://github.com/llvm/llvm-project.git
cmake -G Ninja -S llvm-project/runtimes -B msan-libcxx \
  -C llvm-project/libcxx/cmake/caches/Generic-msan.cmake \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
  -DLLVM_ENABLE_RUNTIMES="libcxx;libcxxabi"
ninja -C msan-libcxx cxx cxxabi
export MSAN_LIBCXX=$PWD/msan-libcxx           # consumed by the msan preset above
```

Match the branch to your Clang major version. Every other C++ dependency (gtest, zlib, ...) must
be built with the same flags; prebuilt system libraries produce false positives.

## GitHub Actions job

```yaml
name: sanitizers
on: [pull_request]
jobs:
  sanitize:
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false
      matrix:
        preset: [asan, tsan]
    env:
      CC: clang
      CXX: clang++
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get update && sudo apt-get install -y ninja-build clang llvm
      - run: cmake --workflow --preset ${{ matrix.preset }}
      - if: matrix.preset == 'asan'
        run: ctest --preset asan-leaks
```

If TSan or ASan abort at start-up with "unexpected memory mapping" on a kernel with high ASLR
entropy and an older compiler-rt, lower it on the runner (`sudo sysctl vm.mmap_rnd_bits=28`) or
upgrade the toolchain. Nightly: add the fuzzers (`-fsanitize=fuzzer,address,undefined`,
`-max_total_time=600`, persisted corpus), the msan preset, and stress repetitions
(`ctest --preset tsan --repeat until-fail:50`).

## Minimising a reproducer with cvise

```bash
cat > interesting.sh <<'EOF'
#!/usr/bin/env bash
# exit 0 while the candidate still compiles and shows the same UBSan report
clang++ -std=c++23 -O2 -g -fsanitize=undefined -fno-sanitize-recover=all repro.cpp -o repro 2>/dev/null || exit 1
./repro 100 2147483600 2>&1 | grep -q 'signed integer overflow'
EOF
chmod +x interesting.sh
cvise ./interesting.sh repro.cpp          # creduce takes the same arguments
```

The script runs in a scratch copy, so refer to the file by its bare name. Keep the predicate
specific (exact message, ideally function name) or the reducer will "find" unrelated crashes.
