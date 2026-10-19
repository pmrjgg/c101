---
name: cpp-testing-fuzzing
description: "C++ test engineering: Catch2 v3 and GoogleTest/GMock patterns, parameterized and death tests, libFuzzer and FuzzTest harnesses, RapidCheck properties, coverage with llvm-cov or gcovr, and running suites under sanitizers through CTest. Load when adding or restructuring C++ tests, or fuzzing a parser or decoder."
when_to_use: "Writing or fixing C++ tests (TEST_CASE, TEST_F, TEST_P, FUZZ_TEST, RC_GTEST_PROP); an LLVMFuzzerTestOneInput harness or a crash-<sha1> artifact; gtest_discover_tests / catch_discover_tests setup; flaky or order-dependent tests; coverage reports or CI thresholds; Apple clang link error 'libclang_rt.fuzzer_osx.a not found'; golden-file or approval tests."
---

# C++ testing and fuzzing

Done means: unit tests green, the same suite green under ASan+UBSan (and TSan for threaded code),
every parser or decoder of untrusted bytes has a fuzz target, and every fuzz crash has become a
regression test. Build and preset mechanics live in `cmake-presets`; this skill covers test code.

Deep material: [GoogleTest and Catch2 cheat sheet](references/framework-cheatsheet.md) | [fuzzing and property-testing playbook](references/fuzzing-playbook.md)

## 1. Framework choice

| Framework | Strengths | CMake target | Discovery |
|---|---|---|---|
| Catch2 v3 | `SECTION` trees, `GENERATE`, matchers, `BENCHMARK`, fast to write | `Catch2::Catch2WithMain` | `include(Catch)` + `catch_discover_tests(t)` |
| GoogleTest + GMock (1.17 needs C++17) | fixtures, `TEST_P`, typed tests, death tests, mocks, FuzzTest and RapidCheck integration | `GTest::gtest_main`, `GTest::gmock` | `include(GoogleTest)` + `gtest_discover_tests(t)` |
| doctest | header-light, fastest compile, tests can live next to code | `doctest::doctest` (`doctest::doctest_with_main`) | `include(doctest)` + `doctest_discover_tests(t)` |

Pick one per repository. Use GoogleTest when you need mocks or FuzzTest; Catch2 when tests are
mostly value-based tables. With FetchContent, `include(Catch)` needs
`list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)` first. Discovery options worth
setting: `DISCOVERY_MODE PRE_TEST` (cross-compiling, emulators), Catch2 `ADD_TAGS_AS_LABELS`
(tags become `ctest -L` labels), `TEST_PREFIX` when several binaries share test names.

## 2. GoogleTest and GMock

`EXPECT_*` records and continues; `ASSERT_*` returns from the test (only from `void` functions).
Prefer `EXPECT_THAT(value, matcher)`: failures print the value and what was expected. Fixtures:
`class F : public ::testing::Test` with `SetUp()`/`TearDown()`, then `TEST_F(F, Name)`; every test
gets a fresh fixture object (`SetUpTestSuite()` for expensive shared setup).

| Need | Matcher |
|---|---|
| exact sequence / any order | `ElementsAre(1, 2, 3)`, `UnorderedElementsAre(...)`, `ElementsAreArray(v)` |
| struct fields positionally / by member | `FieldsAre(640, 480, 3, _)` (one matcher per field), `Field(&Header::width, Gt(0))`, `Property(&T::size, 3)` |
| `std::optional` / pointer / variant | `Optional(Eq(5))`, `Pointee(Eq(5))`, `VariantWith<int>(5)` |
| strings | `HasSubstr("x")`, `StartsWith("IMG")`, `MatchesRegex(R"(\d+)")` |
| floating point | `DoubleNear(1.0, 1e-9)`, `FloatEq(x)` (4 ULP), `NanSensitiveDoubleEq(x)` |
| containers | `SizeIs(3)`, `IsEmpty()`, `Contains(42)`, `Each(Gt(0))` |
| exceptions | `EXPECT_THAT([] { f(); }, ThrowsMessage<std::invalid_argument>(HasSubstr("width")))` |
| combine | `AllOf(...)`, `AnyOf(...)`, `Not(...)`, `Truly(pred)` |

```cpp
class CacheTest : public ::testing::TestWithParam<std::size_t> {};
TEST_P(CacheTest, EvictsLeastRecentlyUsed) {
    LruCache<int, int> c(GetParam());
    for (int i = 0; i <= static_cast<int>(GetParam()); ++i) c.put(i, i);
    EXPECT_FALSE(c.get(0).has_value());
}
INSTANTIATE_TEST_SUITE_P(Sizes, CacheTest, ::testing::Values(1, 2, 64),
                         ::testing::PrintToStringParamName());

template <class T> class CodecTest : public ::testing::Test {};
using Codecs = ::testing::Types<Utf8Codec, Utf16Codec>;
TYPED_TEST_SUITE(CodecTest, Codecs);
TYPED_TEST(CodecTest, RoundTrips) { TypeParam c; EXPECT_EQ(c.decode(c.encode("hi")), "hi"); }
```

`::testing::Combine(Values(...), Bool())` builds a cartesian product (`std::tuple` params).
Death tests check contract violations only (`assert`, `std::terminate`, C++26 contract failures):

```cpp
TEST(RingDeathTest, PopOnEmptyAborts) {           // *DeathTest suites run first
    Ring<int> r(2);
    EXPECT_DEATH(r.pop(), "empty");                 // regex matched against stderr
    EXPECT_EXIT(fatal_config("x"), ::testing::ExitedWithCode(2), "bad config");
}
```

Each death assertion forks a child (milliseconds each, far more under ASan); with threads use
`--gtest_death_test_style=threadsafe`, which re-executes the binary up to that test. Under
`NDEBUG` an `assert`-based death test fails because nothing dies: guard with `#ifndef NDEBUG` or
use `EXPECT_DEBUG_DEATH`.

Mocks: mock interfaces at boundaries you own (clock, transport, repository), never value types or
third-party classes you do not control (wrap them first).

```cpp
struct MockClock : Clock { MOCK_METHOD(std::chrono::nanoseconds, now, (), (const, override)); };
::testing::NiceMock<MockClock> clock;                 // uninteresting calls are fine
ON_CALL(clock, now).WillByDefault(::testing::Return(std::chrono::seconds(5)));
EXPECT_CALL(clock, now()).Times(::testing::AtLeast(1));
```

`StrictMock` fails on any unexpected call (protocol tests); `NaggyMock` (default) warns. Use
`ON_CALL` for behaviour, `EXPECT_CALL` only for interactions the test is about. Runner flags:
`--gtest_filter='Cache*:-*Slow*'`, `--gtest_shuffle --gtest_repeat=50` (order dependencies,
flakes), `--gtest_fail_fast`, `--gtest_break_on_failure`; `GTEST_SKIP() << "reason"`.

## 3. Catch2 v3

```cpp
#include <catch2/catch_test_macros.hpp>
#include <catch2/generators/catch_generators.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

TEST_CASE("ring buffer", "[ring]") {
    Ring<int> r(2);                                  // re-run for every leaf SECTION
    SECTION("push within capacity") { r.push(1); CHECK(r.size() == 1); }
    SECTION("overflow drops oldest") { r.push(1); r.push(2); r.push(3); CHECK(r.front() == 2); }
}

TEST_CASE("parse rejects malformed input", "[parse]") {
    auto bad = GENERATE(as<std::string>{}, "", "{", "[1,]", "\xff");
    CAPTURE(bad);
    REQUIRE_FALSE(parse(bad).has_value());
}

TEST_CASE("area table", "[geo]") {
    auto [w, h, area] = GENERATE(table<int, int, int>({ {2, 3, 6}, {0, 5, 0}, {7, 1, 7} }));
    CHECK(rect_area(w, h) == area);
}

TEST_CASE("mean is stable", "[stats]") {
    using Catch::Matchers::WithinRel, Catch::Matchers::WithinAbs;
    CHECK_THAT(mean({0.1, 0.2, 0.3}), WithinRel(0.2, 1e-12) || WithinAbs(0.2, 1e-15));
}
```

| Topic | Catch2 v3 facts |
|---|---|
| sections | each leaf `SECTION` runs the test case from the top: setup is fresh per leaf |
| generators | `GENERATE(1, 3, 5)`, `table<...>`, `take(100, random(-1000, 1000))` (`catch_generators_random.hpp`, `_adapters.hpp`), `range(a, b[, step])`; variables inside need `GENERATE_COPY` / `GENERATE_REF` |
| floating point | `WithinRel(x, eps)` relative, `WithinAbs` for values near 0, `WithinULP(x, n)`; legacy `Catch::Approx` in `<catch2/catch_approx.hpp>` |
| matchers | `ContainsSubstring`, `StartsWith`, `Matches` (regex), `RangeEquals` / `UnorderedRangeEquals` (3.3+), `SizeIs`, `AllMatch`; `REQUIRE_THROWS_MATCHES(f(), E, Message("..."))` |
| tags and CLI | `"[slow]"`, hidden `"[.]"`; `./t "[parse]" "~[slow]"`; default `--order rand` with `--rng-seed` (print and reuse it); `--shard-count 4 --shard-index 1`; `-r junit::out=report.xml` |
| benchmarks | `<catch2/benchmark/catch_benchmark.hpp>`, `BENCHMARK("name") { return f(); };`, `--skip-benchmarks` in CI unit runs |

## 4. Testable design

| Dependency | Seam | Test double |
|---|---|---|
| time | `Clock` interface or `template <class Clock = std::chrono::steady_clock>` | fake clock advanced by the test |
| filesystem | pass a root `std::filesystem::path` or a small `Fs` interface | unique temp dir per test (`std::filesystem::temp_directory_path() / unique name`) |
| network | `Transport` interface (send/receive bytes) | in-memory pipe; record/replay for protocols |
| randomness | inject `std::mt19937_64&` or a seed | fixed seed, logged on failure |
| environment / config | pass a config struct, do not read `getenv` deep inside | construct configs in tests |
| threads / executors | inject an executor | inline executor that runs tasks synchronously |

No singletons or mutable globals: pass dependencies through constructors. For legacy singletons,
add a constructor seam first, keep `instance()` as a thin adapter, migrate callers gradually.
Link seams (a fake `.cpp` linked only into the test binary) work for C APIs.

## 5. libFuzzer

Clang only. Apple's Xcode clang ships no libFuzzer runtime ("library
'.../libclang_rt.fuzzer_osx.a' not found"): use Homebrew or upstream LLVM, or Linux. The
original authors moved to Centipede, so libFuzzer receives bug fixes, not features; it remains the
standard harness interface (OSS-Fuzz, FuzzTest compatibility mode).

```cpp
// fuzz/fuzz_header.cpp
#include "img/header.hpp"
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    const auto h = parse_header({data, size});
    if (!h) return 0;                                   // rejecting garbage is fine
    const auto bytes = serialize(*h);
    const auto again = parse_header(bytes);
    if (!again || *again != *h) __builtin_trap();       // round-trip oracle
    return 0;                                           // never keep state between calls
}
```

```cmake
option(IMG_FUZZ "libFuzzer targets (Clang)" OFF)
if(IMG_FUZZ)
  target_compile_options(img PRIVATE -fsanitize=fuzzer-no-link,address,undefined)   # instrument the code under test
  add_executable(fuzz_header fuzz/fuzz_header.cpp)
  target_link_libraries(fuzz_header PRIVATE img)
  target_compile_options(fuzz_header PRIVATE -fsanitize=fuzzer,address,undefined -fno-sanitize-recover=all)
  target_link_options(fuzz_header PRIVATE -fsanitize=fuzzer,address,undefined)
endif()
```

| Flag | Use |
|---|---|
| `corpus/ seeds/` (directories) | first dir is read and written; others only read |
| `-max_total_time=600`, `-runs=N` | time or iteration budget (default: forever) |
| `-jobs=8 -workers=4` | 8 runs to completion, 4 at a time (workers default min(jobs, cores/2)); logs in `fuzz-<n>.log` |
| `-fork=8 -ignore_crashes=1` | experimental: keep going after crashes, OOMs, timeouts |
| `-dict=header.dict` | tokens: `magic="IMG1"`, `"\x89PNG"` |
| `-max_len=4096`, `-timeout=5`, `-rss_limit_mb=2048` | input size cap, per-input seconds (default 1200), memory cap |
| `-use_value_profile=1` | treat new comparison operands as coverage (magic numbers, checksums) |
| `-artifact_prefix=out/`, `-exact_artifact_path=crash.bin` | where `crash-<sha1>`, `leak-`, `timeout-`, `oom-` files go |
| `-merge=1 new/ old/` | minimize a corpus: keep inputs adding coverage |
| `-minimize_crash=1 -runs=100000 crash-<sha1>` | shrink a crashing input |
| `file1 file2` (files, not dirs) | replay only, no fuzzing: the CI regression mode |
| `-help=1` | every flag of this build |

Structured inputs: `#include <fuzzer/FuzzedDataProvider.h>`; `FuzzedDataProvider p(data, size);`
then `p.ConsumeIntegralInRange<int>(0, 3)`, `p.ConsumeBool()`, `p.ConsumeRandomLengthString(64)`,
`p.ConsumeBytes<std::uint8_t>(n)`, `p.ConsumeRemainingBytes<std::uint8_t>()`,
`p.PickValueInArray(ops)`. Integers come from the end of the buffer, bytes from the front.
One-time setup: `extern "C" int LLVMFuzzerInitialize(int* argc, char*** argv)`.

## 6. FuzzTest and RapidCheck

Google FuzzTest: property functions inside GoogleTest; unit-test mode runs each briefly with
random inputs, fuzzing mode (Clang only, `-DFUZZTEST_FUZZING_MODE=on`) runs coverage-guided.

```cpp
#include "fuzztest/fuzztest.h"
void RoundTrips(std::uint32_t w, std::uint32_t h, const std::vector<std::string>& tags) {
    Header in{w, h, 3, tags};
    EXPECT_EQ(parse_header(serialize(in)), in);
}
FUZZ_TEST(HeaderFuzz, RoundTrips)
    .WithDomains(fuzztest::Arbitrary<std::uint32_t>(), fuzztest::InRange<std::uint32_t>(1, 1 << 16),
                 fuzztest::VectorOf(fuzztest::String().WithMaxSize(255)).WithMaxSize(255))
    .WithSeeds({{640, 480, {"sRGB"}}});
```

CMake: `add_subdirectory(fuzztest)` (before setting coverage flags), `fuzztest_setup_fuzzing_flags()`,
`link_fuzztest(target)`, `gtest_discover_tests(target)`. Run `./t --fuzz=HeaderFuzz.RoundTrips` or
`--fuzz_for=60s`. Domains: `InRange`, `Positive<T>()`, `ElementOf({...})`, `VectorOf(d).WithMaxSize(n)`,
`String()`, `AsciiString()`, `Filter(pred, d)`, `Map(fn, d...)`, `StructOf<T>(...)`.

RapidCheck: QuickCheck-style with automatic shrinking of failing cases.

```cpp
#include <rapidcheck/gtest.h>                         // after <gtest/gtest.h>; build with -DRC_ENABLE_GTEST=ON
RC_GTEST_PROP(Header, SerializeParseRoundTrips, (std::uint32_t w, std::uint32_t h)) {
    const auto n = *rc::gen::inRange(0, 8);           // max is exclusive
    const auto tags = *rc::gen::container<std::vector<std::string>>(n, rc::gen::string<std::string>());
    RC_PRE(std::ranges::all_of(tags, [](auto& t) { return t.size() < 256; }));
    const Header in{w, h, 3, tags};
    RC_ASSERT(parse_header(serialize(in)) == in);
}
```

Without GoogleTest: `REQUIRE(rc::check("round trip", [](std::uint32_t w) { RC_ASSERT(...); }));`
(`rc::check` returns `bool`). Replay or tune with `RC_PARAMS="seed=... max_success=1000"`; a
failure prints a `reproduce` string to pass back via `RC_PARAMS`.

## 7. Coverage

```bash
# Clang source-based coverage: compile with -fprofile-instr-generate -fcoverage-mapping, link with
# -fprofile-instr-generate (the cov-clang preset in the cmake-presets catalogue); its test preset sets
# LLVM_PROFILE_FILE=<build>/prof/%p-%m.profraw so parallel test processes never overwrite each other
ctest --preset cov-clang
llvm-profdata merge -sparse build/cov-clang/prof/*.profraw -o cov.profdata
llvm-cov report ./build/cov-clang/unit_tests -instr-profile=cov.profdata -ignore-filename-regex='(tests|_deps)/'
llvm-cov show ./build/cov-clang/unit_tests -instr-profile=cov.profdata -format=html -output-dir=cov-html \
  -show-line-counts-or-regions -show-branches=count
llvm-cov export ./build/cov-clang/unit_tests -instr-profile=cov.profdata -format=lcov > cov.lcov
# several test binaries: add -object=./build/cov-clang/other_tests to one report command
# GCC: --coverage preset, run tests, then
gcovr -r . --filter src/ --html-details cov.html --cobertura cov.xml --txt-summary \
  --fail-under-line 80 --fail-under-branch 60
```

Gate llvm-cov in CI with the JSON summary: `llvm-cov export ... -summary-only | python3 -c
"import json,sys; t=json.load(sys.stdin)['data'][0]['totals']; sys.exit(t['lines']['percent'] < 80)"`.
Merge gcovr runs with `--json cov-<job>.json` per job, then `gcovr --json-add-tracefile "cov-*.json" --html-details cov.html` (quote the glob).
MC/DC: Clang `-fcoverage-mcdc` plus `llvm-cov report -show-mcdc-summary`. Thresholds ratchet:
fail on a drop from the main-branch value, not on an absolute number set once.

## 8. Sanitized and flaky runs

Test presets from `cmake-presets` (`asan`, `tsan`, `asan-leaks` on Linux) set `ASAN_OPTIONS=
abort_on_error=1:detect_stack_use_after_return=1`, `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`,
`TSAN_OPTIONS=halt_on_error=1:second_deadlock_stack=1`; `cmake --workflow asan` builds and runs
them. MSan (uninitialized reads) needs Clang on Linux and every linked library instrumented.

```bash
ctest --preset dev --repeat until-fail:200 --schedule-random -R 'Cache|Ring' --output-on-failure
./unit_tests --gtest_shuffle --gtest_repeat=100 --gtest_random_seed=12345 --gtest_filter='Cache*'
./unit_tests --order rand --rng-seed 12345 "[ring]"
```

| Flake cause | Signature | Fix |
|---|---|---|
| order dependence | fails only shuffled | per-test setup; no statics; fresh fixture |
| sleeps and timeouts | fails under load or sanitizers | fake clock; wait on a condition with a generous deadline |
| shared port, file, temp dir | fails with `-j` | `RESOURCE_LOCK`, unique names, port 0 |
| data race | fails rarely, TSan reports | fix the race; TSan preset in CI |
| uninitialized memory | differs between builds | MSan, `-ftrivial-auto-var-init=pattern` in test builds |
| floating point | differs across compilers or flags | `WithinRel`/`DoubleNear`, no exact equality |

Quarantine with a label (`LABELS quarantine`, run with `-LE quarantine`) plus a ticket; never `DISABLED_` silently.

## 9. Golden and approval tests

For text output, reports and generated code, compare against a checked-in expected file:

```cpp
void check_golden(const std::filesystem::path& golden, const std::string& actual) {
    if (std::getenv("UPDATE_GOLDENS")) { std::ofstream(golden, std::ios::binary) << actual; return; }
    std::ifstream in(golden, std::ios::binary);
    const std::string expected{std::istreambuf_iterator<char>(in), {}};
    INFO("regenerate with UPDATE_GOLDENS=1, then review: git diff -- " << golden.string());
    CHECK(actual == expected);
}
```

Normalize before comparing (timestamps, absolute paths, pointer values, hash-map iteration order,
`\r\n`). Regenerate with `UPDATE_GOLDENS=1 ctest -R golden` and review the diff like code. For
generated C++, also compile the golden in a test target so it cannot rot. ApprovalTests.cpp
automates the files: `#define APPROVALS_CATCH2_V3` (or `APPROVALS_GOOGLETEST`) before
`#include "ApprovalTests.hpp"` in one TU, then `ApprovalTests::Approvals::verify(text)`; it writes
`*.received.*` next to `*.approved.*` on mismatch.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| fuzzer never gets past the magic bytes | no seeds or dictionary | seed corpus of valid files, `-dict`, `-use_value_profile=1` |
| fuzz crash not reproducible | harness keeps state between inputs, or uses time/randomness | stateless harness; seed everything from the input |
| OOB in the library not reported | only the harness was built with ASan | instrument the library (`fuzzer-no-link,address`) |
| death test passes in Debug, fails in Release | `assert` compiled out (`NDEBUG`) | `EXPECT_DEBUG_DEATH`, or test a real contract check |
| tests vanish from ctest after a crash in discovery | `POST_BUILD` discovery ran a crashing binary | `DISCOVERY_MODE PRE_TEST`, fix the static-init crash |
| coverage shows 0% | `.profraw` overwritten or not merged | `%p-%m` in `LLVM_PROFILE_FILE`, `llvm-profdata merge` |
| mocks make refactoring painful | mocking internals or value types | mock only owned boundaries; fakes for everything else |

## 11. Worked example: fuzz a binary header parser

Format `IMG1`: magic, `u32` width, `u32` height (little endian), `u8` channels, `u8` tag count,
then per tag `u8` length + bytes. The parser checked the 14-byte fixed part, then per tag:

```cpp
const std::size_t len = in[pos++];
h.tags.emplace_back(reinterpret_cast<const char*>(in.data() + pos), len);   // header.cpp:22
pos += len;                                                                // no bounds check on len
```

1. Harness: the section 5 round-trip target. Seeds: one valid 19-byte file (`IMG1`, 640x480, 3
   channels, tag `sRGB`) in `corpus/`; `header.dict` contains `magic="IMG1"`.
2. Fuzz (Linux or upstream Clang, preset with `-DIMG_FUZZ=ON`):
   `./fuzz_header -dict=header.dict -max_len=512 -max_total_time=300 corpus/`. libFuzzer stops at
   the first ASan report and writes `crash-<sha1>` in the working directory.
3. Minimize: `./fuzz_header -minimize_crash=1 -runs=100000 -exact_artifact_path=min.bin crash-<sha1>`.
   The shortest crashing input is 15 bytes (14 fixed bytes plus a non-zero length byte); the one
   replayed below is `494d4731 01000000 01000000 03 01 c8`: one tag claiming 200 bytes, none present.
4. Replaying that input through the harness built with `-fsanitize=address,undefined` (on macOS via a
   file-replay `main`, since Apple clang has no libFuzzer runtime) gives:

```text
==51283==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x6020000009ff ...
READ of size 200 at 0x6020000009ff thread T0
    #0 0x000104f93b40 in __asan_memmove+0x19c (libclang_rt.asan_osx_dynamic.dylib:arm64e+0x8fb40)
    ...
    #12 0x0001023a0cc8 in parse_header(std::__1::span<unsigned char const, 18446744073709551615ul>) header.cpp:22
```

5. Fix, before the `emplace_back`: `if (len > in.size() - pos) return std::nullopt;`
   (`pos < in.size()` is already guaranteed by the loop check, so the subtraction cannot wrap).
6. Regression test, plus the input kept as a fuzz regression file:

```cpp
#include <catch2/catch_test_macros.hpp>
#include <array>
#include "img/header.hpp"

TEST_CASE("parse_header rejects a tag longer than the input", "[header][regression]") {
    // minimized libFuzzer crash: 1 tag declaring 200 bytes, 0 bytes present
    constexpr std::array<std::uint8_t, 15> in{'I', 'M', 'G', '1', 1, 0, 0, 0, 1, 0, 0, 0, 3, 1, 200};
    CHECK_FALSE(parse_header(in).has_value());
}

TEST_CASE("parse_header round-trips a valid header", "[header]") {
    const Header h{640, 480, 3, {"sRGB"}};
    const auto again = parse_header(serialize(h));
    REQUIRE(again.has_value());
    CHECK(*again == h);
}
```

```cmake
if(IMG_FUZZ)   # replay every saved crash on each CI run; files (not dirs) mean no fuzzing
  add_test(NAME fuzz_header.regressions
           COMMAND fuzz_header ${CMAKE_CURRENT_SOURCE_DIR}/fuzz/regressions/header-tag-overflow.bin)
endif()
```

7. Verify: after the fix the ASan replay of the seed and the crash input printed `ok` for both and
   the two test bodies passed (checked with plain `assert`). Then run `ctest --preset asan` and a
   10-minute fuzz run on the grown corpus, and `-merge=1` the corpus before committing it.

Related: `cmake-presets` (sanitizer, coverage and fuzz presets, CTest), `cpp-ub-sanitizers`
(reading ASan/UBSan/TSan reports), `cpp-simd-performance` (benchmarks), `cpp-memory-raii`,
`cpp-concurrency-atomics` (TSan-clean concurrency), `testing-strategy`, hub `cpp-craft`.
