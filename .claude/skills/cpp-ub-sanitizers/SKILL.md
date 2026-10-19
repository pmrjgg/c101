---
name: cpp-ub-sanitizers
description: "Hunting undefined behavior in C and C++: a UB catalogue by category; ASan, UBSan, TSan and MSan plus Clang's TySan and RTSan with their runtime options; hardened standard-library modes and -fhardened; -ftrivial-auto-var-init; static analyzers; and sanitizer report triage. Load for crashes, heisenbugs, Release-only failures, or before shipping native code."
when_to_use: "Segfault/SIGBUS/SIGILL, heap corruption, 'AddressSanitizer: heap-use-after-free', 'runtime error: signed integer overflow', 'ThreadSanitizer: data race', MemorySanitizer use-of-uninitialized-value, crashes only at -O2/Release or with another compiler, choosing warning flags, clang-tidy checks or hardening flags for .c/.cpp code, wiring sanitizer builds into CMake presets or CI."
---

# Undefined behavior and sanitizers in C and C++

UB means the compiler may assume it never happens. Optimisers exploit that, so symptoms appear
far from the cause, change with `-O` level, compiler and unrelated edits, and tests at `-O0`
stay green. The procedure: catalogue the suspects, run the right sanitizer at `-O1`/`-O2`,
triage the first report, fix the design, keep a regression test that runs under the sanitizer.

Deep material: [full UB catalogue with triggers and detectors](references/ub-catalogue.md) |
[sanitizer CI: presets, suppressions, MSan libc++, GitHub Actions](references/sanitizer-ci.md)

## 1. UB catalogue (top offenders per category)

| Category | UB | Typical trigger | Detector |
|---|---|---|---|
| memory | out-of-bounds read/write | `v[v.size()]`, index from input | ASan; hardened library modes |
| memory | use-after-free / double free / `new[]`-`delete` mismatch | reference or iterator kept across `push_back`; manual ownership | ASan |
| lifetime | use-after-return / use-after-scope | returning `&local`, `[&]` lambda or `string_view` outliving its scope | ASan (`detect_stack_use_after_return`), Clang `-Wdangling*` |
| lifetime | reading an object outside its lifetime | old pointer after placement-new, type-punned buffer | review; `std::launder`, C++23 `std::start_lifetime_as` |
| lifetime | uninitialised read | `int x; if (c) x = 1; return x;` | MSan; `-Wuninitialized`; `-ftrivial-auto-var-init=pattern` in tests; erroneous behavior in C++26 (still a bug) |
| arithmetic | signed overflow | `INT_MAX + 1`, `i * stride` index math | UBSan `signed-integer-overflow` |
| arithmetic | shift by negative or >= width | `1 << 32` | UBSan `shift` |
| arithmetic | division by zero, `INT_MIN / -1`, `INT_MIN % -1` | user-controlled divisor | UBSan `integer-divide-by-zero` |
| arithmetic | float to int out of range | `(int)1e20` | UBSan `float-cast-overflow` (Clang's `undefined` includes it, GCC's does not) |
| types | strict-aliasing violation | `*reinterpret_cast<float*>(&u32)` | TySan (Clang 20+); `-Wstrict-aliasing`; use `std::bit_cast`/`memcpy` |
| types | misaligned access | `*(uint32_t*)(buf + 1)` | UBSan `alignment` |
| types | invalid `bool`/enum value, wrong function type, bad downcast | bytes read into `bool`, `static_cast<Derived&>(base)` | UBSan `bool`, `enum`, `function`, `vptr` |
| concurrency | data race | unsynchronised conflicting access | TSan |
| library | precondition violated | `front()` on empty, `*opt` empty, `*expected` holding an error, non-strict-weak comparator in `sort` | hardened library modes, `_GLIBCXX_DEBUG` |
| program | ODR violation | two definitions of one inline function/struct across TUs | ASan `detect_odr_violation`, LTO `-Wodr` |
| program | side-effect-free loop assumed to terminate | `while (!flag) {}` on a plain `bool` | atomic flag; C++26 defines only trivial `while (true);` loops |
| program | `[[assume(e)]]` / `std::unreachable()` reached with `e` false | wrong assumption | assert first, assume only after proof |

Full tables with triggers, symptoms and prevention: [ub-catalogue](references/ub-catalogue.md).

## 2. Sanitizer build matrix

Baseline for ASan+UBSan: `-fsanitize=address,undefined -fno-sanitize-recover=all
-fno-omit-frame-pointer -g -O1` (compile **and** link flags).

| Sanitizer | Flag | Toolchains | Cost | Combine with |
|---|---|---|---|---|
| AddressSanitizer (+LeakSanitizer on Linux) | `-fsanitize=address` | GCC, Clang, Apple clang, MSVC (`/fsanitize=address`) | ~2x CPU, about 3x memory | UBSan |
| UndefinedBehaviorSanitizer | `-fsanitize=undefined` | GCC, Clang | small | ASan, TSan, MSan |
| ThreadSanitizer | `-fsanitize=thread` | GCC, Clang on Linux, macOS, FreeBSD, NetBSD, Android (64-bit) | 5-15x CPU, 5-10x memory | UBSan only; separate build |
| MemorySanitizer | `-fsanitize=memory -fsanitize-memory-track-origins=2` | Clang on Linux/BSD; every linked library, libc++ included, must be instrumented | ~3x | UBSan only; separate build |
| TypeSanitizer | `-fsanitize=type` | Clang 20+, experimental | 2-3x best case, ~8x memory | not with ASan or TSan |
| RealtimeSanitizer | `-fsanitize=realtime` + `[[clang::nonblocking]]` (`[[clang::blocking]]` marks your own unsafe calls) | Clang 20+ | negligible; reports malloc, locks and blocking calls made inside nonblocking functions | not documented: run it in its own job |
| HWAddressSanitizer | `-fsanitize=hwaddress` | Clang and GCC on AArch64 (Linux, Android) | ASan-like detection, lower memory | replaces ASan |
| LeakSanitizer standalone | `-fsanitize=leak` | Linux | ~none until exit | |

Group contents differ by compiler (checked on Apple clang 21): Clang's `-fsanitize=undefined`
**no longer includes `vptr`** (a bad `static_cast` downcast was silent until
`-fsanitize=undefined,vptr`), and excludes `unsigned-integer-overflow`, `implicit-conversion`,
`local-bounds`, `float-divide-by-zero` and `nullability-*`; GCC's group includes `vptr` but not
`float-cast-overflow` or `float-divide-by-zero`. Extra Clang groups: `-fsanitize=integer`
(adds unsigned overflow and implicit truncation/sign changes: defined behaviour, often bugs),
`-fsanitize=implicit-conversion`. Production builds that must keep checks:
`-fsanitize=undefined -fsanitize-trap=all` (no runtime, traps with SIGILL/SIGTRAP) or
`-fsanitize-minimal-runtime`.

Apple clang 21 (Xcode toolchain) facts, checked: ASan, UBSan, TSan work; `-fsanitize=memory`,
`realtime`, `hwaddress` and `leak` are "unsupported option" for arm64-apple-darwin;
`-fsanitize=type` compiles but the runtime dylib is missing at link; `-fhardened` is unknown
(GCC-only). Use Linux CI (or upstream LLVM) for MSan, LSan, RTSan and TySan.

## 3. Runtime options

| Variable | Option | Effect / default |
|---|---|---|
| `ASAN_OPTIONS` | `detect_leaks=1` | LSan at exit; on by default with ASan on Linux; on macOS the runtime aborts with "detect_leaks is not supported on this platform" (checked) |
| | `detect_stack_use_after_return=1` | use-after-return via fake stacks; on by default on Linux in recent Clang, set it explicitly elsewhere |
| | `check_initialization_order=1` (+ `strict_init_order=1`) | static-init-order fiasco; checked on macOS: reports `initialization-order-fiasco` |
| | `strict_string_checks=1` | string arguments must be NUL-terminated |
| | `detect_odr_violation=2` | default 2 (1 compares sizes only) |
| | `detect_container_overflow=1` | default on; false positives when some TUs using the container are not instrumented |
| | `alloc_dealloc_mismatch=1` | malloc/delete mismatches; default off on Darwin and Windows |
| | `abort_on_error=1`, `halt_on_error` | core dumps / debugger break; `halt_on_error=0` needs `-fsanitize-recover=address` |
| | `quarantine_size_mb=256` | default 256; raise to catch older use-after-free |
| | `log_path=asan.log`, `suppressions=asan.supp` | per-pid log files; runtime suppressions |
| `UBSAN_OPTIONS` | `print_stacktrace=1:halt_on_error=1` | stack per report (needs `-fno-omit-frame-pointer` and `llvm-symbolizer` on `PATH`); stop at the first |
| | `suppressions=ubsan.supp` | lines `check:location`, e.g. `signed-integer-overflow:legacy_codec.cpp`; recoverable checks only |
| `TSAN_OPTIONS` | `halt_on_error=1:second_deadlock_stack=1:history_size=7` | stop at first race, both stacks for lock inversions, deeper history (0-7) |
| | `exitcode=66` (default), `suppressions=tsan.supp` | types `race`, `race_top`, `mutex`, `thread`, `signal`, `deadlock`, `called_from_lib` |
| `LSAN_OPTIONS` | `suppressions=lsan.supp` | lines `leak:libthirdparty.so` |
| `TYSAN_OPTIONS`, `RTSAN_OPTIONS` | `print_stacktrace=1`, `halt_on_error=1`, `suppressions=...` | RTSan halts on the first error by default |

Symbolize with `ASAN_SYMBOLIZER_PATH=$(command -v llvm-symbolizer)` when frames show only
addresses. Suppression policy: a checked-in file, one entry per line, each with a comment
naming the reason and the upstream bug; an unexplained suppression is a review blocker.

## 4. Hardening (keep in release builds)

| Flag | Effect | Notes |
|---|---|---|
| `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST` | libc++ security-critical precondition checks (bounds, null) | `_EXTENSIVE` adds non-security UB checks (benchmark first), `_DEBUG` for tests; does not change the ABI; failures trap (quick-enforce) in fast/extensive |
| `-D_GLIBCXX_ASSERTIONS` | libstdc++ precondition checks (`operator[]`, `front`, ...) | cheap; ABI-neutral |
| `-D_GLIBCXX_DEBUG` | libstdc++ safe iterators: invalidation, mismatched containers | **changes the ABI**: whole-program debug builds only |
| `-D_FORTIFY_SOURCE=3` (with `-O1`+) | checked libc string/memory calls using `__builtin_dynamic_object_size` | needs GCC 12+ or Clang 9+ and a recent glibc; falls back to level 2 otherwise |
| `-fstack-protector-strong`, `-fstack-clash-protection` | canaries, stack-clash probes | low cost |
| `-fcf-protection=full` (x86) / `-mbranch-protection=standard` (AArch64) | CET / PAC+BTI | needs OS/CPU support to enforce |
| `-ftrivial-auto-var-init=zero` / `=pattern` | initialises automatic variables | measured Clang `pattern`: `0xaaaaaaaa` ints, `0xaaaaaaaaaaaaaaaa` pointers; use `pattern` in tests (garbage-looking values crash early), `zero` in production (removes info leaks); it hides MSan/`-Wuninitialized` findings |
| `-fhardened` (GCC 14+, GNU/Linux only) | enables `-D_FORTIFY_SOURCE=3 -D_GLIBCXX_ASSERTIONS -ftrivial-auto-var-init=zero -fPIE -pie -Wl,-z,relro,-z,now -fstack-protector-strong -fstack-clash-protection -fcf-protection=full` (x86 GNU/Linux) | only flags not already given; uses `_FORTIFY_SOURCE=2` with glibc < 2.35; list with `gcc --help=hardened` |
| `-Wl,-z,relro,-z,now`, `-fPIE -pie` | full RELRO, ASLR | |

C++26 standardises two of these ideas: **hardened implementations** (P3471) turn listed
library preconditions (`operator[]`, `front`, `back`, `optional::operator*` ...) into checked
contract assertions, and **erroneous behavior** (P2795; GCC 16 implements it) makes reading an
uninitialised automatic variable a diagnosable bug with an implementation-chosen value instead of
UB; `[[indeterminate]]` opts a variable back out. Until your compilers ship them, the vendor
macros and `-ftrivial-auto-var-init` are the way to get the behaviour.

## 5. Static first line

| Layer | Use |
|---|---|
| warnings (GCC/Clang) | `-Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wnull-dereference -Wnon-virtual-dtor -Wold-style-cast -Wcast-align -Woverloaded-virtual -Wdouble-promotion -Wformat=2 -Wimplicit-fallthrough`; MSVC `/W4 /permissive-` |
| dangling family | Clang (on by default): `-Wdangling`, `-Wdangling-gsl`, `-Wdangling-capture`, `-Wreturn-stack-address`; GCC: `-Wdangling-pointer=2` and `-Wuse-after-free=2` (in `-Wall`), `-Wdangling-reference` (in `-Wextra`, GCC 13+; `[[gnu::no_dangling]]` from GCC 14 for false positives) |
| needs optimisation | GCC `-Wnull-dereference`, `-Wmaybe-uninitialized` only see paths the optimiser builds: compile the warning job at `-O2` too |
| clang-tidy | `bugprone-*`, `cert-*`, `clang-analyzer-*`, `concurrency-*`; high-value: `bugprone-use-after-move`, `bugprone-dangling-handle`, `bugprone-undefined-memory-manipulation`, `bugprone-sizeof-expression`, `bugprone-signed-char-misuse`, `bugprone-implicit-widening-of-multiplication-result`, `bugprone-narrowing-conversions`, `bugprone-unchecked-optional-access`, `cert-err33-c`; run `run-clang-tidy -p build -quiet` or on changed files |
| path-sensitive analysis | Clang static analyzer: `scan-build cmake -S . -B build-scan && scan-build -o scan-out cmake --build build-scan` (it swaps CC/CXX, so configure under it in a fresh directory) or the `clang-analyzer-*` checks; GCC `-fanalyzer` (`-Wanalyzer-use-after-free`, `-double-free`, `-null-dereference`, `-malloc-leak`, `-fd-leak`), which its docs call suitable for C only |

## 6. Triage procedure

1. **First report only.** Later reports are often consequences. Read the summary line: kind
   (`heap-use-after-free`, `stack-buffer-overflow`, `signed-integer-overflow`, `data race`),
   access (`READ of size 4`), location.
2. **First project frame.** Skip standard-library and runtime frames; the first frame in your
   code is where to look, not necessarily where to fix.
3. **Read the other stacks.** ASan: "freed by thread T0 here" and "previously allocated by" tell
   the ownership story (a `__push_back_slow_path`/`emplace_back_slow_path` in the free stack
   means reallocation invalidated your reference). TSan: both conflicting accesses, the mutexes
   held, and the thread creation stacks. MSan with `track-origins=2`: where the uninitialised
   value was created.
4. **Classify** with the catalogue: ownership/lifetime, bounds, arithmetic, aliasing, race.
5. **Minimise** when the reproducer is large: write an interestingness script that exits 0 while
   the same sanitizer message appears, then `cvise ./interesting.sh repro.cpp` (or `creduce`).
   Fuzzer crash files: `./fuzz_target -minimize_crash=1 -runs=100000 crash-<sha>`.
6. **Fix the design**, not the symptom: no extra copies to move the crash, no sleeps for races,
   no `-fno-strict-aliasing` as the fix for a punning bug.
7. **Regression test** that reproduces the bug and runs in the sanitizer CI job; re-run the full
   suite under the same sanitizer.

Delegation in this stack: save the report to a file
(`./test 2>&1 | tee .stack/out/<agent>/<YYYYMMDD-HHMM>-asan.log`) and hand the `debugger` agent
that path plus the reproducer command, never the pasted report; memory-safety review of parsers
and network-facing code goes to `security-auditor`.

## 7. Platform notes

- **MSVC**: `/fsanitize=address` (VS 2019 16.9+, x86 and x64), `/Zi` for symbolised stacks;
  incompatible with edit-and-continue (`/ZI`), `/INCREMENTAL` and `/RTC`; stack-use-after-return
  needs an extra compiler option rather than `ASAN_OPTIONS`; `ASAN_SAVE_DUMPS=name.dmp` writes a
  crash dump for offline debugging. No UBSan, TSan or MSan: run those on a Clang build of the same
  code.
- **macOS**: no LeakSanitizer; use `leaks --atExit -- ./prog` on a non-ASan build (exit status 1
  when leaks are found; `MallocStackLogging=1` adds allocation stacks). Guard Malloc and
  `MallocScribble=1` exist for quick checks. Xcode exposes ASan/TSan/UBSan per scheme.
- **Valgrind memcheck** when a rebuild is impossible (binary-only dependency, shipped artefact):
  `valgrind --leak-check=full --track-origins=yes --error-exitcode=1 ./prog`; Linux, roughly
  20-30x slower; catches uninitialised use and leaks without instrumentation, but not stack or
  global overflows; not available for Apple silicon macOS.

## 8. CI wiring

- Presets per sanitizer (`asan`, `tsan`, `msan`, `ubsan-trap`) in `CMakePresets.json` with
  `CMAKE_BUILD_TYPE=RelWithDebInfo` so optimisation-dependent UB shows up; test presets carry the
  `*_OPTIONS` environment. Full template in [sanitizer-ci](references/sanitizer-ci.md); general
  preset design in `cmake-presets`.
- Every PR: ASan+UBSan unit tests; TSan job if the change touches threads. Nightly: the full suite
  plus integration tests under ASan+UBSan, the fuzzers under `-fsanitize=fuzzer,address,undefined`
  with a time budget (`-max_total_time=600`), TSan stress loops, and an MSan job on Linux with an
  instrumented libc++ (fuzzing details: `cpp-testing-fuzzing`).
- Release artefacts: hardening flags from section 4; optionally a `-fsanitize-trap` build for
  canaries.
- Separate build directories and ccache namespaces per sanitizer; never mix sanitized and
  unsanitized objects in one link (container-overflow annotations misfire, and bugs in the
  uninstrumented part go unseen).

## 9. Worked example: a Release-only crash and an iterator-invalidation use-after-free

Part 1. Bug report: "`sum_window` crashes in Release, works in Debug."

```cpp
long sum_window(const std::vector<int>& v, int offset, int len) {
    if (offset < 0 || len < 0) return -1;
    const int end = offset + len;                 // signed overflow: UB when offset + len > INT_MAX
    if (end < offset) return -1;                  // "overflow check" that only works if it wraps
    if (end > static_cast<int>(v.size())) return -1;
    long s = 0;
    for (int i = offset; i != end; ++i) s += v[i];
    return s;
}
// main: v(1000, 1); prints sum_window(v, atoi(argv[1]), atoi(argv[2]))
```

Measured with Apple clang 21 for `./app 100 2147483600`: `-O0` prints `-1`; `-O1` and `-O2`
die with exit status 138 (SIGBUS). Because overflow cannot happen in a valid program, the
optimiser folds `offset + len < offset` to `len < 0`, which the first line already excluded, and
deletes the check (the `-O1` IR keeps only the `(offset | len) >= 0` and `end > size`
comparisons); the wrapped negative `end` passes the size check and the loop walks off the vector.

```bash
clang++ -std=c++23 -O2 -g -fno-omit-frame-pointer -fsanitize=undefined -fno-sanitize-recover=all app.cpp -o app_ubsan
UBSAN_OPTIONS=print_stacktrace=1 ./app_ubsan 100 2147483600
```

```text
(abridged)
app.cpp:8:28: runtime error: signed integer overflow: 100 + 2147483600 cannot be represented in type 'int'
    #0 0x0001021047d4 in sum_window(std::__1::vector<int> const&, int, int) app.cpp:8
    #1 0x00010210488c in main app.cpp:20
SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior app.cpp:8:28
```

Fix: validate without performing the overflowing operation.

```cpp
long sum_window(const std::vector<int>& v, int offset, int len) {
    const auto size = std::ssize(v);
    if (offset < 0 || len < 0 || offset > size || len > size - offset) return -1;  // no addition can overflow
    long s = 0;
    for (int i = offset; i != offset + len; ++i) s += v[i];
    return s;
}
```

Alternatives: `__builtin_add_overflow(offset, len, &end)`, compute in `std::int64_t`, or C++26
`std::add_sat` when saturation is the intended semantics. After the fix: `-1` at `-O0` and `-O2`,
clean under UBSan.

Part 2. Second report: "split orders occasionally corrupt quantities."

```cpp
void split_large(std::vector<Order>& orders, int limit) {
    for (Order& o : orders) {                     // range-for holds iterators into `orders`
        if (o.qty > limit) {
            orders.push_back({o.id, o.qty / 2});  // may reallocate: `o` and the loop iterators dangle
            o.qty -= o.qty / 2;                   // heap-use-after-free
        }
    }
}
```

`clang++ -std=c++23 -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined uaf.cpp` and a run
with orders `{1,10},{2,500},{3,20}` (excerpt, Apple clang 21):

```text
(abridged: template arguments and some frames removed)
ERROR: AddressSanitizer: heap-use-after-free on address 0x603000000fdc ...
READ of size 4 at 0x603000000fdc thread T0
    #0 in split_large(std::vector<Order>&, int) uaf.cpp:12
0x603000000fdc is located 12 bytes inside of 24-byte region [0x603000000fd0,0x603000000fe8)
freed by thread T0 here:
    #6 in std::vector<Order>::__emplace_back_slow_path<Order>(Order&&) vector.h:1113
    #9 in std::vector<Order>::push_back(Order&&) vector.h:466
    #10 in split_large(std::vector<Order>&, int) uaf.cpp:11
previously allocated by thread T0 here:
    #8 in std::vector<Order>::vector(std::initializer_list<Order>) vector.h:277
    #10 in main uaf.cpp:18
```

Reading it: 24-byte region = the original 3 `Order`s (8 bytes each); offset 12 = element 1's
`qty`; freed by the reallocating `push_back` on line 11; the stale reference is read on line 12.
Without ASan the program usually "works" because the freed block still holds the old values.

```cpp
void split_large(std::vector<Order>& orders, int limit) {
    const std::size_t n = orders.size();          // visit only the original orders
    for (std::size_t i = 0; i < n; ++i) {         // indices survive reallocation
        if (orders[i].qty > limit) {
            const int half = orders[i].qty / 2;
            orders[i].qty -= half;
            orders.push_back({orders[i].id, half});
        }
    }
}
```

After the fix: output `1:10 2:250 3:20 2:250`, clean under ASan+UBSan. Both reproducers become
unit tests in the sanitizer job. Note that `reserve(2 * n)` alone would hide this crash but keep
the bug for any later code that pushes more.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| sanitizer build clean, Release still crashes | sanitizer run at `-O0`, or the failing path not exercised | `-O1`/`-O2` sanitizer builds; fuzz the input path |
| ASan "unknown-crash" or no stack | missing `-fno-omit-frame-pointer`/`-g`, no symbolizer | add flags; `ASAN_SYMBOLIZER_PATH` |
| UBSan prints and the test still passes | checks are recoverable by default | `-fno-sanitize-recover=all` or `halt_on_error=1` |
| bad downcast never reported by Clang | `vptr` not in Clang's `undefined` group | `-fsanitize=undefined,vptr` (needs RTTI) |
| container-overflow reports in correct code | some TUs built without ASan | instrument everything, or `detect_container_overflow=0` with a reason |
| TSan reports inside a fence-based algorithm | TSan does not model `atomic_thread_fence` | acquire/release operations instead, or a documented suppression |
| MSan floods with reports from libc++ or zlib | uninstrumented library | build the dependencies and libc++ with MSan |
| `detect_leaks is not supported on this platform` abort | `detect_leaks=1` on macOS | Linux job for LSan; `leaks --atExit` locally |
| hardening mode "does nothing" | macro defined after a header was included, or prebuilt library | pass `-D...` on the command line for every TU |
| `-ftrivial-auto-var-init` hides an MSan bug | values are now initialised | keep MSan builds without it |
| crash moves when you add a `printf` | UB: layout and optimisation changed | stop bisecting by prints; run the sanitizers |

Related: `cpp-memory-raii`, `cpp-concurrency-atomics`, `cpp-testing-fuzzing`, `cmake-presets`,
`cpp-templates-concepts`, hub `cpp-craft`.
