# Fuzzing and mutation testing reference

## Fuzz harness rules

- Deterministic: no clocks, no global state carried between inputs, no network or disk writes.
- Fast: aim for > 1000 executions per second; reject or cap huge inputs early (`if len(data) > 1<<16 { return }`).
- Oracle beyond "no crash": inside the harness, check round-trips, invariants, or differential agreement.
- Expected errors are not crashes: return on documented error types; let everything else fail.
- Sanitizers on (ASan + UBSan for C/C++/unsafe Rust); without them memory bugs go silent.
- Seed corpus: real-world samples (small, diverse), plus every past crash.
- Dictionary for token formats (keywords, magic bytes, delimiters), libFuzzer format:
  ```
  kw_get="GET"
  kw_http="HTTP/1.1"
  magic_png="\x89PNG"
  ```

## Go native fuzzing
```go
func FuzzParseDuration(f *testing.F) {
    for _, s := range []string{"1h30m", "0s", "999h59m59s", ""} {
        f.Add(s)
    }
    f.Fuzz(func(t *testing.T, s string) {
        d, err := ParseDuration(s)
        if err != nil {
            return
        }
        back, err := ParseDuration(FormatDuration(d))
        if err != nil || back != d {
            t.Fatalf("round trip %q -> %v -> %v (%v)", s, d, back, err)
        }
    })
}
```
- `go test -fuzz=FuzzParseDuration -fuzztime=60s ./duration` (one package, one target per invocation).
- Failing inputs land in `testdata/fuzz/FuzzParseDuration/`; commit them, and plain `go test` replays them.
- `-parallel` controls workers; `GOCACHE/fuzz` holds the generated corpus.

## Rust: cargo-fuzz
```bash
cargo install cargo-fuzz
cargo fuzz init && cargo fuzz add parse
cargo +nightly fuzz run parse -- -max_total_time=300 -dict=fuzz/parse.dict
cargo +nightly fuzz tmin parse fuzz/artifacts/parse/crash-<hash>     # minimize a crash
cargo +nightly fuzz cmin parse                                       # minimize the corpus
cargo +nightly fuzz coverage parse                                   # coverage of the corpus
```
```rust
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    if let Ok(s) = std::str::from_utf8(data) {
        if let Ok(v) = mycrate::parse(s) {
            assert_eq!(mycrate::parse(&v.to_string()).unwrap(), v);
        }
    }
});
```
Structure-aware fuzzing: derive `arbitrary::Arbitrary` on an input struct and take it as the closure
argument. Also consider `bolero` (one harness for libFuzzer, AFL, and property tests).

## C and C++: libFuzzer and AFL++
```cpp
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    parse_message(data, size);
    return 0;
}
```
```bash
clang++ -g -O1 -fsanitize=fuzzer,address,undefined harness.cc parser.cc -o fuzz_parse
./fuzz_parse -max_total_time=600 -jobs=8 -workers=8 corpus/ seeds/
./fuzz_parse -minimize_crash=1 -runs=100000 crash-<hash>
# AFL++
afl-clang-fast -g -O1 target.c -o target
afl-fuzz -i seeds -o findings -- ./target @@
afl-tmin -i findings/default/crashes/id:000000* -o min.bin -- ./target @@
```

## Python: Atheris
```python
import sys, atheris
with atheris.instrument_imports():
    import mylib

def TestOneInput(data: bytes):
    fdp = atheris.FuzzedDataProvider(data)
    s = fdp.ConsumeUnicodeNoSurrogates(256)
    try:
        mylib.parse(s)
    except mylib.ParseError:
        pass

atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
```
Run: `python fuzz_parse.py -max_total_time=300 corpus/`. Native extensions need building with
sanitizer-instrumented compilers to find memory bugs.

## JVM: Jazzer
```java
class ParserFuzzTest {
    @FuzzTest
    void parse(FuzzedDataProvider data) {
        try {
            Parser.parse(data.consumeRemainingAsString());
        } catch (ParseException expected) {
        }
    }
}
```
By default `@FuzzTest` runs the stored inputs as regression tests; set `JAZZER_FUZZ=1` to fuzz.
Jazzer also flags injection-style sinks (deserialization, expression language, OS command) it reaches.

## Budgets and scheduling

| Context | Budget per target |
|---|---|
| PR smoke (changed parsers only) | 60-300 s |
| Nightly | 1-8 h, corpus persisted between runs |
| Continuous | OSS-Fuzz (open source) or ClusterFuzzLite in CI |

Coverage plateau (no new edges for ~1 h) means the harness, dictionary or seeds limit progress, not
time. Inspect coverage (`cargo fuzz coverage`, `-print_coverage=1`) to find unreached branches.

## Crash triage

1. Deduplicate by the top 3-5 symbolized stack frames and the sanitizer report type.
2. Minimize (`tmin`, `-minimize_crash=1`).
3. Classify: assertion/panic (logic bug), sanitizer report (memory/UB, potentially security-relevant),
   OOM (unbounded allocation from input size fields), timeout (algorithmic complexity on input).
4. Turn it into a unit test that feeds the minimized input; fix; keep the input in the seed corpus.
5. Memory-safety crashes in code reachable from untrusted input go to `security-auditor` for severity.

## Mutation testing

| Ecosystem | Tool | Command |
|---|---|---|
| Python | mutmut | `mutmut run` then `mutmut results`, `mutmut show <id>` |
| Rust | cargo-mutants | `cargo mutants --in-diff changes.diff` or `cargo mutants -f src/billing.rs` |
| JS/TS, C#, Scala | Stryker | `npx stryker run` (incremental mode reuses previous results) |
| Java/Kotlin (JVM) | PIT | `mvn org.pitest:pitest-maven:mutationCoverage -DtargetClasses='com.acme.billing.*'` |
| Go | gremlins | `gremlins unleash ./...` |
| C/C++ | Mull | clang plugin; see project docs for the toolchain version |

Produce the diff for `--in-diff` with `git diff origin/main...HEAD > changes.diff`.

Interpreting outcomes:

| Outcome | Meaning | Action |
|---|---|---|
| Killed | A test failed | Good |
| Survived | No test noticed the change | Add an assertion that distinguishes the behaviour, or prove equivalence |
| Timeout | Mutant caused a hang | Usually counts as killed (infinite loop detected) |
| No coverage | No test executes the line | Write a test first; mutation analysis is premature |
| Equivalent | Mutant cannot change observable behaviour (e.g. `i < n` vs `i != n` in a counted loop) | Document and exclude |

Targets: for code changed in this task, zero surviving non-equivalent mutants in critical logic; for a
whole module, 70-80% mutation score is a strong suite. Do not run mutation testing over the whole
codebase in a PR loop; scope it to the diff.
