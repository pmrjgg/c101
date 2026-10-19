# Build levers, PGO/BOLT, binary size, compile time and CI benchmarks

Measure every lever on the real workload; keep a table of before/after numbers in the PR.

## 1. Profiles

```toml
[profile.release]
lto = "fat"              # "thin" for faster links; false = thin-local (default)
codegen-units = 1        # default 16 for release
# panic = "abort"        # only for binaries that never rely on unwinding

[profile.profiling]      # cargo build --profile profiling
inherits = "release"
debug = true

[profile.min-size]       # cargo build --profile min-size
inherits = "release"
opt-level = "z"
lto = true
codegen-units = 1
panic = "abort"
strip = true             # "symbols"; "debuginfo" keeps the symbol table

[profile.dev.package."*"]
opt-level = 2            # optimise dependencies in dev builds (not workspace members)
```

Notes from the Cargo reference: per-package overrides cannot set `panic`, `lto` or `rpath`;
`[profile.dev.build-override]` tunes build scripts and proc macros; tests and benches ignore
`panic` and always unwind. `overflow-checks` is off in release: use explicit `checked_*`
arithmetic where wrap-around is a bug.

## 2. CPU targeting

- `rustc --print target-cpus` lists names; `rustc --print cfg -C target-cpu=x86-64-v3` shows the
  enabled features.
- Fleet binaries: pick a microarchitecture level (`x86-64-v2` ~ SSE4.2/POPCNT, `x86-64-v3` ~
  AVX2/FMA/BMI2) per target in `.cargo/config.toml`:

```toml
[target.x86_64-unknown-linux-gnu]
rustflags = ["-C", "target-cpu=x86-64-v3"]
```

- Per-function opt-in with `#[target_feature(enable = "...")]` plus runtime detection keeps one
  portable binary (see SKILL.md section 6).

## 3. PGO and BOLT

With cargo-pgo:

```bash
cargo install cargo-pgo && rustup component add llvm-tools-preview
cargo pgo info                         # checks llvm-profdata / llvm-bolt availability
cargo pgo build                        # instrumented release build
./target/<triple>/release/app <representative workload>    # repeat for several inputs
cargo pgo optimize                     # rebuild with the merged profile
# BOLT on top (Linux ELF, experimental, needs llvm-bolt and merge-fdata):
cargo pgo bolt build --with-pgo
./target/<triple>/release/app-bolt-instrumented <workload>
cargo pgo bolt optimize --with-pgo     # produces app-bolt-optimized
```

Manual PGO (rustc book workflow; `--target` keeps build scripts uninstrumented):

```bash
rm -rf /tmp/pgo-data
RUSTFLAGS="-Cprofile-generate=/tmp/pgo-data" cargo build --release --target=x86_64-unknown-linux-gnu
./target/x86_64-unknown-linux-gnu/release/app input1 && ./target/x86_64-unknown-linux-gnu/release/app input2
llvm-profdata merge -o /tmp/pgo-data/merged.profdata /tmp/pgo-data
RUSTFLAGS="-Cprofile-use=/tmp/pgo-data/merged.profdata -Cllvm-args=-pgo-warn-missing-function" \
  cargo build --release --target=x86_64-unknown-linux-gnu
```

Use absolute paths for profile data; regenerate profiles when the code changes materially; never
strip a binary before BOLT.

## 4. Global allocators

```rust
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;          // mimalloc = "0.1"
// or, not on MSVC targets:
// static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;   // "0.7"
```

Compare throughput, p99 latency and RSS under a realistic concurrent load; allocator wins on
microbenchmarks often vanish or invert under fragmentation. Since Rust 1.93 a global allocator
may use thread-local storage and `std::thread::current()`.

## 5. Binary size

```bash
cargo install --locked cargo-bloat cargo-llvm-lines
cargo bloat --release --crates            # size by crate
cargo bloat --release -n 30               # 30 largest functions
cargo llvm-lines --release | head -30     # LLVM IR lines per generic instantiation
```

Levers in order of typical payoff: drop unused dependencies and default features, `opt-level = "z"`
or `"s"`, `lto = true` + `codegen-units = 1`, `panic = "abort"`, `strip = true`, de-generify hot
generic functions (inner non-generic `fn` taking `&dyn Trait` or concrete types), avoid
`format!`/`Debug` derives in no_std/embedded hot spots.

## 6. Compile time

```bash
cargo build --timings          # target/cargo-timings/cargo-timing.html: critical path, codegen vs frontend
cargo check                    # type-check only; the inner dev loop
```

| Lever | Effect |
|---|---|
| split a large crate (see `cargo-workspaces-features`) | parallel and incremental builds per crate |
| `[profile.dev] debug = "line-tables-only"` (or `0`) | less debug info to generate and link |
| lld (default on x86_64 Linux since 1.90) / mold (`-C link-arg=-fuse-ld=mold`) | faster links |
| `sccache` (`RUSTC_WRAPPER=sccache` or `[build] rustc-wrapper = "sccache"`) | cache across clean builds and CI |
| fewer proc-macro-heavy deps, `default-features = false` | less to compile |
| `cargo llvm-lines` hot generics | less codegen |
| Cranelift backend | nightly only (`-Zcodegen-backend`) |

Cargo 1.99: incremental compilation is disabled by default when the `CI` environment variable is
set (it rarely pays off on fresh CI machines).

## 7. CI benchmarks

Instruction counts with gungraun (Valgrind/Callgrind; formerly iai-callgrind):

```toml
[dev-dependencies]
gungraun = "0.20"
[[bench]]
name = "parse_ic"
harness = false
```

```rust
use gungraun::prelude::*;
use std::hint::black_box;

#[library_benchmark]
#[bench::small(1_000)]
#[bench::large(100_000)]
fn total(lines: usize) -> u64 {
    let input = lineparse::make_input(lines);
    black_box(lineparse::total_v2(black_box(input.as_bytes())).unwrap())
}

library_benchmark_group!(name = parse_group, benchmarks = total);
main!(library_benchmark_groups = parse_group);
```

Install the runner with the same version (`cargo install gungraun-runner --version 0.20.0`) and
Valgrind on the CI image; results land in `target/gungraun`. Setup code inside the benchmark
function is counted too: move expensive setup into `setup =` arguments per the gungraun docs.

CodSpeed: rename the dependency (`criterion = { package = "codspeed-criterion-compat", version = "..." }`
or the divan equivalent), then in CI `cargo codspeed build` and `cargo codspeed run` inside the
CodSpeed GitHub Action. Modes: `simulation` (default, CPU simulation), `walltime`, `memory`.

Self-hosted wall-clock: dedicated runner, fixed CPU governor (`cpupower frequency-set -g performance`),
turbo off, isolated cores (`taskset`), at least 3 repeated runs; compare medians against the
saved baseline and alert on > 5% regressions only after a confirming rerun.
