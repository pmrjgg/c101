# Fuzzing playbook (cargo-fuzz, arbitrary, afl.rs, ClusterFuzzLite)

## 1. Setup

```bash
cargo install cargo-fuzz             # needs a nightly toolchain to run: cargo +nightly fuzz ...
cargo +nightly fuzz init             # creates fuzz/ (its own crate, excluded from the workspace)
cargo +nightly fuzz add parse_bytes
cargo +nightly fuzz list
```

`fuzz/Cargo.toml` dependencies: `libfuzzer-sys = "0.4"`, `arbitrary = { version = "1", features = ["derive"] }`,
and the crate under test by path. Add `fuzz/` to the workspace `exclude` list if `init` did not.

## 2. Target templates

Bytes in, must never panic:

```rust
#![no_main]
use libfuzzer_sys::fuzz_target;
fuzz_target!(|data: &[u8]| {
    let _ = mycrate::decode(data);
});
```

Text formats (skip non-UTF-8 instead of wasting executions):

```rust
fuzz_target!(|data: &[u8]| {
    let Ok(text) = std::str::from_utf8(data) else { return };
    if let Ok(cfg) = confparse::parse(text) {
        let again = confparse::parse(&confparse::render(&cfg)).expect("rendered config re-parses");
        assert_eq!(again, cfg);                       // round-trip oracle
    }
});
```

Structured input with `Arbitrary`:

```rust
use std::collections::BTreeMap;

#[derive(Debug, arbitrary::Arbitrary)]
struct Input {
    root: BTreeMap<String, String>,
    sections: BTreeMap<String, BTreeMap<String, String>>,
}

fn renderable_key(k: &str) -> bool {
    !k.is_empty() && k.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

fuzz_target!(|input: Input| {
    let ok = input.root.keys().all(|k| renderable_key(k))
        && input.sections.iter().all(|(s, m)| renderable_key(s) && m.keys().all(|k| renderable_key(k)));
    if !ok { return; }                                 // outside the format's domain
    let cfg = confparse::Config { root: input.root, sections: input.sections };
    assert_eq!(confparse::parse(&confparse::render(&cfg)), Ok(cfg));
});
```

Differential oracle: run the optimised implementation and a simple reference (or the previous
release) on the same input and assert equal outputs. Stateful APIs: decode a `Vec<Op>` and apply
the operations to the real structure and a model.

## 3. Running

```bash
cargo +nightly fuzz run parse_bytes                              # until first crash
cargo +nightly fuzz run parse_bytes -- -max_total_time=600 -jobs=8 -workers=8
cargo +nightly fuzz run parse_bytes -- -dict=fuzz/conf.dict -max_len=4096
cargo +nightly fuzz run parse_bytes -s none                      # no ASan: faster for safe code
cargo +nightly fuzz run parse_bytes --release                    # -O: drop debug assertions
```

Build modes: optimised with debug assertions by default (overflow panics are found), `-O` for
release semantics, `-D` for an unoptimised build, `-s address|leak|memory|thread|none`.

Dictionary (`fuzz/conf.dict`, libFuzzer format, one `name="value"` per line):

```text
open="["
close="]"
eq="="
comment="#"
esc_n="\\n"
esc_bs="\\\\"
newline="\x0a"
```

## 4. Triage

```bash
ls fuzz/artifacts/parse_bytes/                     # crash-<sha1>, oom-<sha1>, timeout-<sha1>
cargo +nightly fuzz run parse_bytes fuzz/artifacts/parse_bytes/crash-<sha1>   # reproduce
cargo +nightly fuzz tmin parse_bytes fuzz/artifacts/parse_bytes/crash-<sha1>  # writes minimized-from-<sha1>
cargo +nightly fuzz fmt parse_bytes fuzz/artifacts/parse_bytes/minimized-from-<sha1>  # Debug view of the input
```

1. Minimise, 2. turn the input into a named regression test (inline literal for short inputs,
`include_bytes!("fuzz_regressions/<name>.bin")` for binary ones), 3. fix, 4. keep the artifact in
the corpus so the fuzzer keeps exercising the region.

`oom-*`: input makes the code allocate unboundedly (cap lengths from the input).
`timeout-*`: super-linear behaviour (nested repetition, quadratic string building).

## 5. Corpus and coverage

```bash
cargo +nightly fuzz cmin parse_bytes                         # drop redundant corpus entries
cargo +nightly fuzz coverage parse_bytes        # writes fuzz/coverage/parse_bytes/coverage.profdata
rustup +nightly component add llvm-tools-preview     # llvm-cov matching nightly's LLVM
T=$(rustc -vV | sed -n 's/^host: //p')
$(rustc +nightly --print sysroot)/lib/rustlib/$T/bin/llvm-cov show \
  target/$T/coverage/$T/release/parse_bytes \
  -instr-profile=fuzz/coverage/parse_bytes/coverage.profdata -format=html > fuzz-cov.html
```

Seed `fuzz/corpus/<target>/` with real-world samples (one file each). Cache the corpus between
CI runs; merge corpora from different machines with `cmin`.

## 6. CI with ClusterFuzzLite

```text
.clusterfuzzlite/project.yaml   language: rust
.clusterfuzzlite/Dockerfile     FROM gcr.io/oss-fuzz-base/base-builder-rust
                                COPY . $SRC/mycrate
                                WORKDIR $SRC/mycrate
                                COPY .clusterfuzzlite/build.sh $SRC/
.clusterfuzzlite/build.sh       cd $SRC/mycrate
                                cargo fuzz build -O
                                cp fuzz/target/x86_64-unknown-linux-gnu/release/parse_bytes $OUT/
```

Workflow steps use `google/clusterfuzzlite/actions/build_fuzzers@v1` and
`google/clusterfuzzlite/actions/run_fuzzers@v1` with `language: rust`; run `mode: code-change`
for 5-10 minutes on PRs and longer `batch` runs on a schedule. Open-source projects can apply to
OSS-Fuzz with the same build script.

## 7. afl.rs as a second engine

```rust
fn main() {
    afl::fuzz!(|data: &[u8]| { let _ = mycrate::decode(data); });
}
```

```bash
cargo install cargo-afl
cargo afl build --release
cargo afl fuzz -i seeds -o out target/release/fuzz_decode
```

Different mutation strategies find different bugs; run both on parsers that matter.
