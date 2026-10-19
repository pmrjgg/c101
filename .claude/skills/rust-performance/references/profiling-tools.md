# Profiling tools by question and OS

Build once with the profiling profile (`inherits = "release"`, `debug = true`) and profile
`target/profiling/<bin>`. Debug builds have different hot spots; plain release builds lack
symbols for line attribution. Write artefacts under `.stack/out/<agent>/`.

## 1. CPU sampling

| OS | Tool | Commands | Agent-friendly output |
|---|---|---|---|
| Linux | perf | `perf record -F 999 --call-graph dwarf -o perf.data ./target/profiling/app args` then `perf report --stdio --no-children --percent-limit 2 > report.txt` | yes (text) |
| Linux | perf counters | `perf stat -e cycles,instructions,cache-misses,branch-misses ./app` (IPC = instructions / cycles; < 1 usually means memory-bound) | yes |
| Linux/macOS/Windows | samply | `samply record --save-only -o prof.json.gz -- ./app args`; later `samply load prof.json.gz` (browser); `-p <pid>` attaches; `--rate` (default 1000 Hz), `--duration`, `--presymbolicate` | humans (Firefox Profiler UI) |
| Linux (perf) / macOS (dtrace, root) | cargo-flamegraph | `cargo flamegraph --profile profiling --bin app -o flame.svg -- args` | SVG; return as an Open doubt on macOS (needs root) |
| macOS | sample (built in) | `./target/profiling/app & /usr/bin/sample $! 5 -file sample.txt` | yes: call tree + "Sort by top of stack" table |

Linux permissions: `sudo sysctl kernel.perf_event_paranoid=1` for perf as a user; samply may
need `sudo setcap 'cap_perfmon+ep' "$(which samply)"`. macOS: `samply setup` codesigns samply so
it can attach to running processes. Frame-pointer call graphs (`perf --call-graph fp`) need
`RUSTFLAGS="-C force-frame-pointers=yes"`.

Symbol names: Rust 1.97+ uses v0 mangling (`_RNvCs..._9lineparse8total_v0`). Tools that do not
understand it print raw names (macOS `sample` does). Demangle with `rustfilt`
(`cargo install rustfilt`; `rustfilt < sample.txt`).

### Reading the macOS `sample` output (real excerpt, names shortened, allocation-bound parser)

```text
2141 _RNvCse3nKN08oCBV_3hot4main  (in hot) + 340  hot.rs:10
  559 _RNv..._9lineparse8total_v0  (in hot) + 1408
  + 390 _xzm_free_main  (in libsystem_malloc.dylib) + 736
  + ! 387 mach_absolute_time  (in libsystem_kernel.dylib)
  368 _RNv..._9lineparse8total_v0  (in hot) + 852,840,...      <- self time
  287 _RNv..._9lineparse8total_v0  (in hot) + 1004
  + 143 _xzm_xzone_malloc_tiny  (in libsystem_malloc.dylib)
  112 _RNv..._9lineparse8total_v0  (in hot) + 232
  + 112 _RNvNtNtCs..._4core5slice6memchr14memchr_aligned  (in hot)
```

Sum samples per callee family (malloc*, free*, memchr, memmove) and divide by the root count.
Here allocator paths were 65% of 2141 samples: fix allocation before anything else.

## 2. Instruction level

```bash
cargo install --locked cargo-show-asm
cargo asm -p mycrate --lib 'mycrate::parse::total'      # function must exist (add #[inline(never)])
cargo asm -p mycrate --lib --rust 'mycrate::parse::total' # interleave source lines
cargo asm -p mycrate --lib --callers-of panic             # every function that can panic
cargo asm -p mycrate --lib --mca 'mycrate::parse::total'  # llvm-mca throughput estimate
# without cargo-show-asm:
cargo rustc --release --lib -- --emit asm && grep -c panic_bounds_check target/release/deps/mycrate-*.s
```

What to look for: calls into `__rust_alloc`/`__rust_dealloc` inside loops, `panic_bounds_check`
and `slice_*_fail` calls in hot loops, scalar loads where you expected vector registers
(`ymm`/`zmm` on x86, `q`/`v` registers on aarch64), and calls to functions you expected inlined.

## 3. Heap profiling

dhat (any OS, in-process):

```toml
[features]
dhat-heap = ["dep:dhat"]
[dependencies]
dhat = { version = "0.3", optional = true }
```

```rust
#[cfg(feature = "dhat-heap")]
#[global_allocator]
static ALLOC: dhat::Alloc = dhat::Alloc;

fn main() {
    #[cfg(feature = "dhat-heap")]
    let _profiler = dhat::Profiler::new_heap();   // writes dhat-heap.json on drop
    run();
}
```

Run `cargo run --profile profiling --features dhat-heap`, open `dhat-heap.json` in the DHAT
viewer (`dh_view.html`). In tests, `dhat::Profiler::builder().testing().build()` plus
`dhat::HeapStats::get()` lets you assert allocation counts.

heaptrack (Linux): `heaptrack ./target/profiling/app args`, then
`heaptrack_print heaptrack.app.<pid>.zst | head -60` (top allocation sites, peak, leaks).

Allocation counts in benches: divan `AllocProfiler` prints allocs/deallocs/bytes per iteration.

## 4. Async runtimes

- Stable tokio metrics (tokio 1.5x): `Handle::current().metrics()` exposes `num_workers`,
  `num_alive_tasks`, `global_queue_depth`, `worker_total_busy_duration`, `worker_park_count`;
  poll-time histograms, steal counts and `worker_mean_poll_time` need `--cfg tokio_unstable`.
- Busy-loop watchdog: a task that sleeps 100 ms and records how late it wakes; lateness > 10 ms
  means some task blocks a worker.
- tokio-console (humans): `console-subscriber` + `console_subscriber::init()` and
  `RUSTFLAGS="--cfg tokio_unstable"`; flags tasks with long polls.

## 5. Benchmark harness templates

criterion 0.8:

```toml
[dev-dependencies]
criterion = { version = "0.8", features = ["html_reports"] }
[[bench]]
name = "parse"
harness = false
```

```rust
use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use std::hint::black_box;

fn bench(c: &mut Criterion) {
    let mut g = c.benchmark_group("parse");
    for size in [1_000, 100_000] {
        let input = make_input(size);
        g.throughput(Throughput::Bytes(input.len() as u64));
        g.bench_with_input(BenchmarkId::from_parameter(size), &input, |b, i| b.iter(|| parse(black_box(i))));
    }
    g.finish();
}
criterion_group!(benches, bench);
criterion_main!(benches);
```

```bash
cargo bench --bench parse -- --save-baseline main      # base commit
cargo bench --bench parse -- --baseline main           # candidate: prints change % and p-value
cargo bench --bench parse -- 'parse/100000' --noplot    # filter one benchmark
```

Interpreting: `time: [low mid high]` is the confidence interval (default 95%) of the
per-iteration time estimate; `change: [...] (p = 0.00 < 0.05)` plus "Performance has improved/regressed" is significant;
"Change within noise threshold" or "No change in performance detected" means do not claim it.
