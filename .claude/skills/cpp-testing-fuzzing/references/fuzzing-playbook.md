# Fuzzing and property-testing playbook

## What to fuzz first

| Target | Oracle besides "no sanitizer report" |
|---|---|
| parsers, decoders, deserializers of untrusted bytes | round trip: `parse(serialize(parse(x))) == parse(x)` |
| two implementations of one thing (fast and reference, old and new) | differential: both return the same result |
| compressors, codecs, encoders | `decode(encode(x)) == x` |
| data structures | invariant check after each operation driven by `FuzzedDataProvider` |
| text formats with grammar | structure-aware: libprotobuf-mutator, or a custom mutator via `LLVMFuzzerCustomMutator` |

Harness rules: deterministic (no time, no global RNG, no threads unless that is the target), no
state carried between calls, no `exit()`, reject oversize inputs early, keep each input under a
few milliseconds (slow inputs show up as `slow-unit-` artifacts or timeouts).

## Build matrix

| Build | Flags | Purpose |
|---|---|---|
| fuzz (default) | `-fsanitize=fuzzer,address,undefined -fno-sanitize-recover=all -g -O1` | memory errors and UB |
| fuzz-msan | `-fsanitize=fuzzer,memory -fsanitize-memory-track-origins` (Linux; every library instrumented) | uninitialized reads |
| library under test | `-fsanitize=fuzzer-no-link,address,undefined` | coverage feedback and ASan checks inside it |
| replay (any compiler) | the harness plus a `main` that reads files and calls `LLVMFuzzerTestOneInput` | run regressions on GCC/MSVC/Apple clang |

A replay `main` for toolchains without libFuzzer:

```cpp
#include <cstdint>
#include <fstream>
#include <iterator>
#include <vector>
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t*, std::size_t);
int main(int argc, char** argv) {
    for (int i = 1; i < argc; ++i) {
        std::ifstream f(argv[i], std::ios::binary);
        std::vector<std::uint8_t> buf((std::istreambuf_iterator<char>(f)), {});   // exact-size heap buffer
        LLVMFuzzerTestOneInput(buf.data(), buf.size());
    }
}
```

The exact-size heap copy matters: ASan only flags reads past the end when the buffer ends where
the input ends, which is also how libFuzzer passes inputs. (Compile it into a separate executable;
it must not be linked together with `-fsanitize=fuzzer`, which provides its own `main`.)

## Corpus workflow

```bash
mkdir -p corpus seeds && cp testdata/*.img seeds/            # valid samples, small and diverse
./fuzz_header -dict=header.dict -max_len=512 corpus/ seeds/  # writes new inputs into corpus/ only
./fuzz_header -jobs=8 -workers=8 -max_total_time=3600 corpus/ seeds/   # parallel, 1 hour
mkdir corpus_min && ./fuzz_header -merge=1 corpus_min corpus seeds     # keep only coverage-adding inputs
./fuzz_header -minimize_crash=1 -runs=100000 -exact_artifact_path=min.bin crash-<sha1>
./fuzz_header min.bin                                         # replay one file (no fuzzing)
./fuzz_header -print_final_stats=1 -runs=0 corpus_min/        # execute the corpus once and report
```

Commit the merged corpus (or store it as a CI artifact if large) and every minimized crash under
`fuzz/regressions/`; replaying the regressions is an ordinary CTest test. Dictionary format, one
token per line: `magic="IMG1"`, `kw2="\xF7\xF8"`, `"tag"`; `#` starts a comment. Sanitizer
coverage for comparisons (`-use_value_profile=1`) helps with magic numbers and checksums; for
checksums, better compute them in the harness or add a fuzzing build flag that skips the check.

## CI fuzzing

| Cadence | Run |
|---|---|
| every PR | replay `fuzz/regressions/*` and the committed corpus with the fuzz binary (seconds) |
| every PR, optional | `-max_total_time=60` per target on changed parsers |
| nightly | `-jobs=N -max_total_time=3600` per target, merge the corpus back, upload `crash-*` artifacts |
| continuous | OSS-Fuzz for open-source projects; ClusterFuzzLite for private repositories |

## FuzzedDataProvider reference (`<fuzzer/FuzzedDataProvider.h>`)

| Method | Returns |
|---|---|
| `ConsumeIntegral<T>()`, `ConsumeIntegralInRange<T>(lo, hi)` | integers (taken from the end of the data) |
| `ConsumeBool()`, `ConsumeEnum<E>()` (enum needs `kMaxValue`), `ConsumeProbability<T>()` | flags, enums, [0, 1] |
| `ConsumeFloatingPoint<T>()`, `ConsumeFloatingPointInRange<T>(lo, hi)` | floats |
| `ConsumeBytes<T>(n)`, `ConsumeBytesWithTerminator<T>(n, term)`, `ConsumeRemainingBytes<T>()` | `std::vector<T>` (from the front) |
| `ConsumeBytesAsString(n)`, `ConsumeRandomLengthString(max)`, `ConsumeRemainingBytesAsString()` | `std::string` |
| `PickValueInArray(arr)` / `PickValueInArray({a, b, c})` | one element |
| `ConsumeData(dst, n)`, `remaining_bytes()` | raw copy, bytes left |

```cpp
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    FuzzedDataProvider p(data, size);
    Ring<int> r(p.ConsumeIntegralInRange<std::size_t>(1, 64));
    std::deque<int> model;                                   // reference implementation
    while (p.remaining_bytes() > 0) {
        switch (p.ConsumeIntegralInRange<int>(0, 2)) {
            case 0: { int v = p.ConsumeIntegral<int>(); r.push(v); model.push_back(v);
                      if (model.size() > r.capacity()) model.pop_front(); break; }
            case 1: if (!model.empty()) { if (r.pop() != model.front()) __builtin_trap(); model.pop_front(); } break;
            case 2: if (r.size() != model.size()) __builtin_trap(); break;
        }
    }
    return 0;
}
```

## Google FuzzTest reference

| Item | Value |
|---|---|
| macro | `FUZZ_TEST(Suite, Function).WithDomains(...).WithSeeds({...})` inside a GoogleTest binary |
| domains | `Arbitrary<T>()`, `InRange(a, b)`, `Positive<T>()`, `NonNegative<T>()`, `Finite<T>()`, `ElementOf({...})`, `String()`, `AsciiString()`, `PrintableAsciiString()`, `VectorOf(d).WithMinSize(a).WithMaxSize(b)`, `Arbitrary<std::vector<int>>().WithSize(n)`, `Filter(pred, d)`, `Map(fn, d...)`, `StructOf<T>(d...)`, `ConstructorOf<T>(d...)` |
| CMake | `add_subdirectory(fuzztest)` first, `fuzztest_setup_fuzzing_flags()`, `link_fuzztest(t)`, `gtest_discover_tests(t)` |
| modes | default build = unit-test mode (short random runs in ctest); `-DFUZZTEST_FUZZING_MODE=on` = coverage-guided (Clang only); `-DFUZZTEST_COMPATIBILITY_MODE=libfuzzer` (experimental) |
| run | `./t --fuzz=Suite.Function` (until a crash or Ctrl-C), `--fuzz_for=60s`, `--rss_limit_mb=`, `--time_limit_per_input=10s` |

## RapidCheck reference

| Item | Value |
|---|---|
| property | `rc::check("desc", [](const std::vector<int>& v) { RC_ASSERT(...); })` returns `bool` |
| preconditions | `RC_PRE(cond)` discards the case (too many discards fail the property; `max_discard_ratio`) |
| failure helpers | `RC_ASSERT_THROWS_AS(expr, E)`, `RC_FAIL(msg)`, `RC_TAG(x)` / `RC_CLASSIFY(cond)` for distribution stats |
| generators | `*gen::arbitrary<T>()`, `*gen::inRange(lo, hi)` (hi exclusive), `gen::container<C>(g)`, `gen::container<C>(n, g)`, `gen::nonEmpty(g)`, `gen::element(a, b, c)`, `gen::suchThat(g, pred)`, `gen::just(v)`, `gen::map(g, f)`, `gen::tuple(g...)`, `gen::string<std::string>()` |
| GoogleTest | `RC_GTEST_PROP(Suite, Name, (args))`, `RC_GTEST_FIXTURE_PROP(Fixture, Name, (args))`; include `rapidcheck/gtest.h` after `gtest/gtest.h`; link `rapidcheck_gtest` (`-DRC_ENABLE_GTEST=ON`) |
| config (`RC_PARAMS`) | `seed=`, `max_success=` (default 100), `max_size=` (default 100), `max_discard_ratio=` (default 10), `noshrink=1`, `verbose_progress=1`, `verbose_shrinking=1`, `reproduce=<string printed on failure>` |

Shrinking is automatic: a failing vector of 80 elements is reported as the smallest variant that
still fails, which is usually the regression test to commit.
