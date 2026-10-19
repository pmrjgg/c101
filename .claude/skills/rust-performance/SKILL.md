---
name: rust-performance
description: "Rust performance workflow. Covers criterion and divan baselines, a profiling build profile with samply, flamegraph, perf and dhat, a symptom-to-fix table, allocation and bounds-check tactics, SIMD with target features, rayon, release profile settings, PGO and BOLT, allocator swaps, and binary-size and compile-time tools. Load when a Rust hot path, allocation rate, binary size or build time needs measured improvement."
when_to_use: "Slow Rust code or a latency/throughput target; benches/ with criterion or divan; [profile.release] or [profile.profiling] edits; flamegraphs or samply profiles showing malloc, RawVec::grow, clone, SipHash or panic_bounds_check; cargo bloat or cargo llvm-lines output; slow cargo build or link times; PGO, BOLT, target-cpu, mimalloc/jemalloc, rayon or std::arch SIMD questions."
---

# Rust performance

Rule zero: no optimisation without a reproducible benchmark and a profile of the release build.
Numbers below were measured on rustc 1.99.1, aarch64-apple-darwin, unless marked otherwise.

Deep material: [profiling tools by OS](references/profiling-tools.md) |
[build levers, PGO, size, compile time and CI benchmarks](references/build-and-ci.md)

## 1. Procedure

1. **Reproduce with a bench.** criterion 0.8 (`harness = false`, `std::hint::black_box` on inputs;
   `criterion::black_box` is deprecated) or divan (attribute benches, `AllocProfiler` counts
   allocations). Use realistic input sizes and set `Throughput::Bytes/Elements`.
2. **Save a baseline** on the base commit: `cargo bench --bench parse -- --save-baseline before`.
3. **Profile** the `profiling` profile (section 2); fix the widest frame you own.
4. **Compare**: `cargo bench --bench parse -- --baseline before`. Keep a change only if criterion
   reports `p < 0.05` *and* the change exceeds the noise threshold (default 1%; raise it to
   0.03-0.05 on laptops/CI with `--noise-threshold`). Revert "improvements" inside the noise.
5. **Guard**: assert the same output in a unit test for every variant; record numbers in the PR.

criterion defaults: 100 samples, 3 s warm-up, 5 s measurement, 100 000 bootstrap resamples,
confidence 0.95, significance 0.05. Noise control: AC power, no other heavy processes, same
binary layout (criterion 0.8 randomises stack alignment with alloca), `--noplot` in CI,
`taskset -c 2` / `cpupower frequency-set -g performance` on Linux hosts you control.

divan:

```rust
#[global_allocator]
static ALLOC: divan::AllocProfiler = divan::AllocProfiler::system();
fn main() { divan::main(); }
#[divan::bench(args = [1_000, 100_000])]
fn parse(bencher: divan::Bencher, n: usize) {
    bencher.with_inputs(|| make_input(n)).bench_refs(|input| total(input));
}
```

divan has no saved-baseline comparison; use criterion (or CodSpeed) when you need A/B statistics.

## 2. Profiling setup

```toml
[profile.profiling]
inherits = "release"
debug = true             # or "line-tables-only" for smaller binaries
```

| Question | Tool and command |
|---|---|
| where does CPU time go (any OS) | `samply record --save-only -o .stack/out/<agent>/profile.json.gz ./target/profiling/app args` (without `--save-only` it opens a browser UI and blocks) |
| flamegraph SVG (Linux perf) | `cargo flamegraph --profile profiling --bin app -o flame.svg -- args` (macOS uses dtrace and needs root) |
| macOS without root | `/usr/bin/sample <pid> 5 -file sample.txt` gives a text call tree with sample counts |
| hot instructions | `perf record -g ./app && perf annotate`; `cargo asm -p crate --lib 'crate::f'` (add `#[inline(never)]` to see a function); `--mca` runs llvm-mca on it |
| who can panic | `cargo asm --lib --callers-of panic` or grep emitted asm for `panic_bounds_check` |
| heap profile | `dhat` crate (`#[global_allocator] static A: dhat::Alloc = dhat::Alloc;` + `let _p = dhat::Profiler::new_heap();`) or `heaptrack` on Linux |
| async stalls | tokio runtime metrics or a scheduling-delay watchdog; `tokio-console` (needs `--cfg tokio_unstable`, interactive: humans only) |

Reading a profile: width = share of samples, not call order. Look for wide towers under
allocator symbols (`malloc`, `free`, `__rust_alloc`, `RawVec::grow`), hashing (`SipHasher13`),
formatting (`fmt::write`), `memmove`/`memcpy` (clones) and locks (`pthread_mutex`, `futex`).
Self time concentrated in your function with no callees means the next step is instruction level.

Rust >= 1.97 emits v0-mangled symbols (`_RNv...`); older or non-Rust tools print them raw. Pipe
through `rustfilt` or use a current samply/perf. Always profile release code: debug builds have
different hot spots.

## 3. Symptom to fix

| Symptom in profile | Likely fix |
|---|---|
| `malloc`/`free`, `RawVec::grow`, `__rust_realloc` hot | `Vec::with_capacity`, reuse buffers with `clear()`, borrow instead of `to_owned`, `SmallVec`/`arrayvec` for small N |
| `clone`, `to_string`, `format!`, `memcpy` hot | borrow or `Cow`, `write!` into a reused `String`, `Arc<str>` for shared immutable text |
| `SipHash` (`hash_one`, `SipHasher13::write`) hot | `rustc_hash::FxHashMap` or `foldhash`/`ahash` when keys are not attacker-controlled (hashbrown's default is already foldhash) |
| `panic_bounds_check` in a tight loop | iterate (`zip`, `chunks_exact`, `as_chunks`), re-slice once, assert lengths up front (section 5) |
| `dyn` calls / indirect branches in an inner loop | generics or enum dispatch |
| cache misses, pointer chasing | struct-of-arrays, `Vec<T>` over `Vec<Box<T>>` and `LinkedList`, `Box` the large enum variant, indices into an arena |
| lock contention (`futex`, `pthread_mutex_lock`) | shard the map, per-thread accumulation then merge, `parking_lot`, fewer and shorter critical sections |
| per-item async overhead (`poll`, waker, scheduler) | batch items per task; one task per connection, not per tiny item |
| `memchr` absent but byte-by-byte scanning hot | `memchr::memchr` / `memchr_iter` / `memmem::Finder` (SIMD) |
| `str::from_utf8`, `chars()` on ASCII data | work on `&[u8]` and validate once at the boundary |

## 4. Allocation tactics

- `Vec::with_capacity(n)` / `String::with_capacity(n)` when the size is known or estimable;
  `reserve` before a loop of pushes.
- Reuse: hoist buffers out of loops and `clear()` them; `BufRead::read_until(b'\n', &mut buf)`
  instead of `lines()` (one `String` per line).
- Small collections: `SmallVec<[T; 8]>` (inline up to 8, smallvec 1.x syntax), `ArrayVec<T, CAP>`
  when a hard bound exists.
- `Cow<'_, str>` for "usually borrowed, sometimes modified"; `Arc<str>`/`Arc<[T]>` instead of
  `Arc<String>` (one allocation, one indirection).
- Arenas: `bumpalo::Bump` for many short-lived objects freed together (per request, per parse).
- Interning: map repeated strings to `u32` symbols (`lasso`, `string-interner`) when the same
  keys repeat millions of times.
- Keep hot enums small and assert it: `const _: () = assert!(std::mem::size_of::<Msg>() <= 32);`.
- Count allocations in a test with `divan::AllocProfiler` or `dhat::HeapStats` and assert them.

## 5. Bounds checks and autovectorisation (measured)

LLVM removes or hoists checks for simple `for i in 0..a.len()` loops by versioning the loop.
Measured, 100 000 `u32`, criterion point estimates:

| Loop | indexed `a[i] * b[i]` | re-sliced `let b = &b[..a.len()]` | `zip` |
|---|---|---|---|
| dot product (reduction) | 6.52 µs | 6.57 µs | 6.52 µs |
| stencil `a[i] + a[i+1] + a[i+2]` into `out[i]` | 7.45 µs | **6.52 µs (-12%)** | 7.24 µs (`windows(3)`) |

So: do not rewrite simple loops on faith (an element-wise `out[i] = a[i] + b[i]` loop also
measured identical across the three styles). Checks still cost when indices are computed
(`a[i + k]` stencils as above, `a[idx[i]]` gathers) or in parsers indexing by found positions. Tactics: re-slice to the exact length once
(`let a = &a[..n + 2];`), `assert!(a.len() >= n)` before the loop, `chunks_exact(N)` /
`as_chunks::<N>()` (stable 1.88) for fixed-width blocks, iterator adaptors instead of indices.
Confirm in the asm (`panic_bounds_check` gone, vector instructions present), then benchmark.

## 6. Explicit SIMD

- Stable path: `std::arch` intrinsics inside `#[target_feature(enable = "avx2")]` functions.
  Since 1.86 such functions can be safe `fn`s; calling them is safe only from code that enables
  the same features, otherwise it needs `unsafe` plus a runtime check:

```rust
pub fn sum(xs: &[f32]) -> f32 {
    #[cfg(target_arch = "x86_64")]
    if std::arch::is_x86_feature_detected!("avx2") {
        // SAFETY: the CPU supports AVX2, checked on the line above.
        return unsafe { sum_avx2(xs) };
    }
    xs.iter().sum()
}
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
fn sum_avx2(xs: &[f32]) -> f32 { xs.iter().sum() } // compiled with AVX2 available
```

- aarch64 has NEON in the baseline; detect extras with `is_aarch64_feature_detected!`.
- Portable crates on stable: `wide` (fixed-width types like `f32x8`), `pulp` (runtime dispatch),
  `memchr`/`simdutf8`-style specialised crates first. `std::simd` is still nightly
  (`portable_simd`).
- Floating-point reductions do not autovectorise (no reassociation); accumulate into several
  lanes manually or use integer/fixed-point where exactness allows.

## 7. Parallelism

- rayon: `par_iter()`, `par_chunks(4096)`; `with_min_len(n)` stops splitting work so small that
  scheduling dominates; configure once with `ThreadPoolBuilder::new().num_threads(n).build_global()`
  or `RAYON_NUM_THREADS`.
- With tokio in the same process: do not run rayon work on runtime workers; bridge with
  `tokio::sync::oneshot` and size the rayon pool so tokio workers + rayon threads ~= cores
  (oversubscription shows as context switches and p99 spikes).
- Shared maps: `DashMap` (sharded `RwLock`s) for read-heavy concurrent access; never hold its
  `Ref`/`RefMut` across `.await` or while touching the same map. For write-heavy counters,
  per-thread `HashMap`s merged at the end beat any shared map.
- Verify scaling: run the bench at 1, 2, 4, N threads; < 1.5x at 4 threads means contention or
  memory bandwidth, not a lack of threads.

## 8. Build levers (measure each one)

```toml
[profile.release]
lto = "fat"              # or "thin": most of the gain, much faster links
codegen-units = 1        # better inlining; slower builds
panic = "abort"          # only if nothing relies on catch_unwind (see Pitfalls)
# opt-level = 3 is the release default
```

- `-C target-cpu=native` only for binaries that never leave the build host's CPU family; for
  fleets pick a level such as `-C target-cpu=x86-64-v3` and document the minimum CPU.
- PGO: `cargo pgo build`, run representative workloads, `cargo pgo optimize` (needs
  `rustup component add llvm-tools-preview`). BOLT on top (Linux ELF only, experimental):
  `cargo pgo bolt build --with-pgo`, run, `cargo pgo bolt optimize --with-pgo`; do not strip
  symbols before BOLT. Gains are workload-specific: profile with production-like inputs only.
- Allocator swap for allocation-heavy servers:
  `#[global_allocator] static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;` or
  `tikv_jemallocator::Jemalloc` (not on MSVC). Benchmark p50/p99 and RSS, not just throughput.
Commands and manual PGO steps: [build-and-ci](references/build-and-ci.md).

## 9. Binary size and compile time

| Goal | Tool / setting |
|---|---|
| what is big, by crate / function | `cargo bloat --release --crates`, `cargo bloat --release -n 30` |
| monomorphisation bloat | `cargo llvm-lines --release \| head -30`; move non-generic bodies out of generic fns, `dyn` at cold boundaries |
| smaller binary | `opt-level = "z"` (or `"s"`), `lto = true`, `codegen-units = 1`, `panic = "abort"`, `strip = true` |
| where build time goes | `cargo build --timings` (HTML in `target/cargo-timings/`) |
| faster links | lld is the default on `x86_64-unknown-linux-gnu` since 1.90; mold via `-C link-arg=-fuse-ld=mold` |
| faster dev builds | `[profile.dev] debug = "line-tables-only"`, `[profile.dev.package."*"] opt-level = 2` for heavy deps, `sccache` (`RUSTC_WRAPPER=sccache`) |
| CI caching | `Swatinem/rust-cache@v2`; Cargo 1.99 disables incremental when `CI` is set |

## 10. CI benchmark stability

Wall-clock benches on shared runners drift 5-10% run to run: never gate merges on them.
Options: instruction counts with gungraun (formerly iai-callgrind; Valgrind/Callgrind based, run
it on Linux CI, needs the `gungraun-runner` binary of the same version); CodSpeed
(`cargo codspeed build` / `run`; default measurement mode `simulation`, also `walltime` and
`memory`; swap criterion/divan for the `codspeed-criterion-compat` / `codspeed-divan-compat`
crates); or a dedicated runner with a pinned governor. Gate on instruction-count regressions > 2-3%; read wall-clock trends only.

## 11. Worked example: an 8.7x faster line parser

Task: sum the second column of 100 000 `id,score,name` lines (1.84 MiB).

```rust
// v0: idiomatic first draft
pub fn total_v0(input: &str) -> u64 {
    let mut total = 0;
    for line in input.lines() {
        let fields: Vec<String> = line.split(',').map(str::to_owned).collect();
        total += fields[1].parse::<u64>().unwrap();
    }
    total
}
```

`cargo bench --bench current -- --save-baseline before`: **11.221 ms (163.9 MiB/s)**.
Profile (`sample` on a `profiling` build looping v0, 2141 samples): allocator 65% (free paths
828 samples, malloc paths 547), self 17%, `memchr_aligned` (inside `lines`/`split`) 8.5%,
`memmove` (the `to_owned` copies) 6%. The asm of `total_v0` calls `__rust_alloc`,
`__rust_dealloc`, `__rust_realloc`, `panic_bounds_check` (`fields[1]`) and `unwrap_failed`.
divan's `AllocProfiler` (the section 1 snippet) counted 400 000 allocations (11.22 MB) per call:
four per line, the `Vec` plus three `String`s. Diagnosis: allocation-bound, then UTF-8 and
char-pattern overhead.

```rust
// v1: borrow, do not allocate (same parsing)              -> 2.094 ms (5.4x)
pub fn total_v1(input: &str) -> Option<u64> {
    let mut total = 0;
    for line in input.lines() {
        total += line.split(',').nth(1)?.parse::<u64>().ok()?;
    }
    Some(total)
}

// v2: bytes + memchr + manual digits, no UTF-8 checks     -> 1.289 ms (8.7x)
pub fn total_v2(input: &[u8]) -> Option<u64> {
    let mut total = 0u64;
    let mut rest = input;
    while !rest.is_empty() {
        let end = memchr::memchr(b'\n', rest).unwrap_or(rest.len());
        let (line, tail) = rest.split_at(end);
        rest = tail.get(1..).unwrap_or_default();
        let (_, after_id) = line.split_at(memchr::memchr(b',', line)? + 1);
        let score = &after_id[..memchr::memchr(b',', after_id)?];
        total += parse_u64(score)?;
    }
    Some(total)
}

fn parse_u64(digits: &[u8]) -> Option<u64> {
    if digits.is_empty() || digits.len() > 19 { return None; }   // 19 digits always fit in u64
    let mut n = 0u64;
    for &b in digits {                                             // iterator: no bounds checks
        let d = b.wrapping_sub(b'0');
        if d > 9 { return None; }
        n = n * 10 + u64::from(d);
    }
    Some(n)
}
```

`cargo bench --bench current -- --baseline before` after switching to v2:

```text
parse/total             time:   [1.2841 ms 1.2886 ms 1.2934 ms]
                        thrpt:  [1.3886 GiB/s 1.3937 GiB/s 1.3985 GiB/s]
                 change:
                        time:   [-88.499% -88.451% -88.395%] (p = 0.00 < 0.05)
                        Performance has improved.
```

In a flamegraph of v0 the same data shows as wide `malloc`/`free` towers stacked on `total_v0`
(about two thirds of the width) next to thin `memchr` and `memmove` columns: the shape that
says "allocation-bound". After: the profile is flat (2298 of 2301 samples are self time in
`total_v2`, memchr inlined) and the asm has no calls at all, so no allocation and no panic path.
Streaming variant: reading the same data through `BufRead::lines()` took 5.32 ms; `read_until`
into one reused `Vec<u8>` plus v2 took 2.37 ms (2.2x). divan reports no allocations for v2.
A unit test asserts all variants return the same total, including input without a trailing
newline and a non-digit score (`None`).

## 12. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| bench shows 0 ns or absurd speed-up | optimiser removed the work | `black_box` inputs and consume outputs |
| win disappears in production | bench input unrealistic (too small, cache-hot, uniform) | bench with production-sized, production-shaped data |
| "improvement" flips sign on rerun | noise larger than the effect | more samples, quieter host, instruction counts |
| flamegraph shows only `[unknown]` frames | no debug info / frame pointers | `profiling` profile; `-C force-frame-pointers=yes` for perf `--call-graph fp` |
| symbols print as `_RNv...` | v0 mangling (1.97+) in an old tool | `rustfilt`, newer profiler |
| destructors skipped, `catch_unwind` ineffective | `panic = "abort"` | keep `unwind` for libraries, FFI/PyO3 crates and servers that isolate panics |
| `target-cpu=native` binary crashes with SIGILL elsewhere | instructions the target CPU lacks | portable level (`x86-64-v2/v3`) or runtime dispatch |
| PGO build slower than plain release | profile from unrepresentative workload or stale profile | regenerate profiles per release from real traffic |
| rayon makes it slower | tasks too small or oversubscribed with tokio | `with_min_len`, coarser chunks, separate pools |
| integer overflow silently wraps in release | overflow checks off by default in release | `checked_*`/`wrapping_*` explicitly or `overflow-checks = true` |

Related: `rust-async-tokio`, `rust-testing-fuzzing`, `cargo-workspaces-features`,
`rust-ownership-lifetimes`, `rust-unsafe-soundness`, hub `rust-craft`.
