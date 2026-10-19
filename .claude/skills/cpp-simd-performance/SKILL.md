---
name: cpp-simd-performance
description: "C++ performance engineering: benchmarking with Google Benchmark and nanobench; profiling with perf, VTune, Instruments and Tracy; compiler levers (LTO, PGO, BOLT, -march levels, target_clones); data layout; vectorizable loops checked with optimization remarks; and explicit SIMD with std::simd, Highway, xsimd or intrinsics. Load when a C++ hot path, allocation pattern or vectorization needs a measured speedup."
when_to_use: "A C++ benchmark regressed or must get faster; perf, VTune or Instruments points at a hot loop, malloc or cache misses; remarks say 'loop not vectorized' (-Rpass-missed=loop-vectorize, -fopt-info-vec-missed); choosing -march, LTO, PGO or BOLT; writing SIMD with Highway, std::simd, xsimd, <immintrin.h> or <arm_neon.h>; reviewing C++ for performance smells."
---

# C++ performance and SIMD

Loop: measure, profile, fix the top item, re-measure, keep only statistically clear wins. Build
exactly like production (`-O2`/`-O3`, same `-march`, LTO and PGO state) plus `-g
-fno-omit-frame-pointer`; Debug numbers are meaningless. Root-only machine tuning (governor,
turbo, `isolcpus`) is never done by the agent: list it as an Open doubt for the user.

Deep material: [profiling and compiler recipes](references/profiling-recipes.md) | [SIMD kernels and dispatch](references/simd-kernels.md)

## 1. Measurement discipline

```cpp
#include <benchmark/benchmark.h>
static void BM_Parse(benchmark::State& state) {
    auto input = make_input(state.range(0));
    for (auto _ : state) {
        auto r = parse(input);
        benchmark::DoNotOptimize(r);        // non-const lvalue: the const& overload is deprecated
    }
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(input.size()));
}
BENCHMARK(BM_Parse)->RangeMultiplier(8)->Range(64, 1 << 20)->Unit(benchmark::kMicrosecond);
BENCHMARK_MAIN();
```

`DoNotOptimize(x)` forces `x` to be materialized; `benchmark::ClobberMemory()` is a compiler
barrier that makes pending stores count as observed (use it after kernels that only write memory).
`state.PauseTiming()` / `ScopedPauseTiming` read the clock on every call, which swamps short
bodies: set up outside the loop or per batch. Aggregates include mean, median, stddev and CV.

```bash
./bench --benchmark_filter='BM_Parse/4096' --benchmark_repetitions=20 \
  --benchmark_enable_random_interleaving=true --benchmark_min_time=0.5s \
  --benchmark_report_aggregates_only=true --benchmark_out=new.json --benchmark_out_format=json
python3 tools/compare.py benchmarks old.json new.json      # ships with google/benchmark; needs scipy
python3 tools/compare.py filters ./bench BM_Old BM_New      # A/B two functions in one binary
```

`--benchmark_min_time` takes `0.5s` (seconds) or `100x` (iterations). `--benchmark_perf_counters=
CYCLES,INSTRUCTIONS` needs a libpfm-enabled build (Linux).

| Evidence | Verdict |
|---|---|
| compare.py U-test p < alpha (default 0.05, `--alpha`) and median delta well above the run-to-run CV | real; keep if the end-to-end metric agrees |
| p >= alpha, or the delta is inside the CV | no effect: keep only if the code is simpler |
| fewer than 9 repetitions | the U test is not meaningful (compare.py says so) |
| microbenchmark win, end-to-end flat | caches or branch predictor were warmer than in production: re-test in context |

nanobench (single header, quick A/B with relative output):

```cpp
#define ANKERL_NANOBENCH_IMPLEMENT          // in exactly one .cpp
#include <nanobench.h>
ankerl::nanobench::Bench b;
b.minEpochIterations(200).relative(true);
b.run("aos", [&] { step_aos(ps, dt); ankerl::nanobench::doNotOptimizeAway(ps); });
b.run("soa", [&] { step_soa(s, dt); ankerl::nanobench::doNotOptimizeAway(s); });
```

It prints `ns/op`, `op/s`, `err%` (rows above 5% are flagged unstable) and, on Linux with perf
events, `ins/op`, `cyc/op`, `IPC`, `bra/op`, `miss%`.

Noise control: Linux `taskset -c 2 ./bench`, quiet machine, more repetitions, random
interleaving; report median and spread, never the best run. Heterogeneous cores (Apple silicon,
Intel P/E): warm up first; a cold start measured the same SoA kernel at 0.712 ns/particle vs
0.143 after a 500 ms warm-up on an M3 Ultra. macOS has no CPU pinning: AC power, no other load.

## 2. Profiling toolbox

| Question | Tool | Command |
|---|---|---|
| where is CPU time | perf | `perf record -F 999 -g ./app` (frame pointers; `--call-graph dwarf` without them), `perf report --stdio --no-children --percent-limit 2 \| head -60` (full report to `.stack/out/<agent>/`) |
| flame graph | perf + FlameGraph / Hotspot | `perf script \| stackcollapse-perf.pl \| flamegraph.pl > f.svg` |
| hardware counters | perf stat | `perf stat -e cycles,instructions,cache-references,cache-misses,branches,branch-misses ./app` (add `L1-dcache-load-misses,LLC-load-misses` for detail) |
| micro-architecture bottleneck | top-down | `perf stat --topdown` (Intel; newer perf: `-M TopdownL1`), VTune, AMD uProf |
| hotspots and memory access on Intel | VTune | `vtune -collect hotspots -r r1 -- ./app`, `-collect uarch-exploration`, `-collect memory-access`; `vtune -report hotspots -r r1` |
| heap allocations | heaptrack | `heaptrack ./app; heaptrack_print heaptrack.app.*.zst > .stack/out/<agent>/heaptrack.txt`, read "MOST CALLS" / "PEAK MEMORY" |
| cache simulation | cachegrind | `valgrind --tool=cachegrind ./app` |
| frame timeline, instrumented | Tracy | `ZoneScoped;` per function, `FrameMark;` per frame, build with `TRACY_ENABLE` (`Tracy::TracyClient`), headless `tracy-capture -o run.tracy`, `tracy-csvexport` |
| macOS | Instruments | `xcrun xctrace record --template 'Time Profiler' --launch -- ./app`; counters: `--template 'CPU Counters'` |
| loop throughput, static | llvm-mca | section 9 |
| compile time | Clang | `-ftime-trace`, open the JSON in Perfetto |

Derived metrics: IPC = instructions / cycles; branch-miss rate = branch-misses / branches. Rules
of thumb, not laws: IPC well below 1 on a wide core means stalls (memory or mispredicts); a miss
rate above a few percent on a hot branch means data-dependent branching; many LLC misses per
element means layout or access order, not arithmetic.

| Profile symptom | First fix |
|---|---|
| `malloc` / `operator new` hot | `reserve`, reuse buffers, `std::pmr::monotonic_buffer_resource` per request, small-buffer types |
| `shared_ptr` refcount atomics hot | unique ownership where possible; pass `T&` / `const T&`; move instead of copy |
| node containers (`std::map`, `std::list`, `std::unordered_map`) hot | sorted `std::vector`, `std::flat_map` (C++23), open-addressing maps |
| virtual calls in an inner loop | `std::variant` + `std::visit`, templates, or sort by type and batch |
| high branch-miss rate | branchless select, sort or partition data, `[[likely]]` only with measurement |
| loop not vectorized | read the remark (section 5); fix aliasing, stride, early exits |
| string building | `std::format_to` into a reserved buffer, `std::string_view` slicing |

## 3. Compiler and link levers

| Lever | Typical gain | Notes |
|---|---|---|
| `-O2` -> `-O3` | 0-10% | more unrolling and code size; GCC 12+ already vectorizes at `-O2` (very-cheap cost model) |
| `-march=x86-64-v3` | 0-30% on vectorizable code | SIGILL on older CPUs; use multiversioning for portable builds |
| LTO | 5-15% | `CMAKE_INTERPROCEDURAL_OPTIMIZATION=ON` gives `-flto=thin` (Clang) / `-flto=auto` (GCC 10+); `check_ipo_supported()` first |
| PGO | 10-30% on branchy code | instrument, run a representative workload, rebuild (recipe below) |
| AutoFDO | much of PGO's gain, no instrumented build | sample production with `perf record -b`, convert, `-fprofile-sample-use=` (Clang) |
| BOLT | 5-15% on large binaries | post-link layout, ELF x86-64 and AArch64 |
| `-fno-plt`, `-fvisibility=hidden` | small | fewer indirections in shared libraries |
| `-ffast-math` | varies | breaks IEEE semantics (section 5); prefer `-fno-math-errno`, `-ffp-contract=fast` |

| x86-64 level | Adds | AArch64 counterpart |
|---|---|---|
| `x86-64-v2` | SSE3/SSSE3/SSE4.1/SSE4.2, POPCNT, CMPXCHG16B | baseline AArch64 already has NEON |
| `x86-64-v3` | AVX, AVX2, FMA, BMI1/2, F16C, LZCNT, MOVBE | tune per core: `-mcpu=neoverse-v2`, Clang `-mcpu=apple-m1` |
| `x86-64-v4` | AVX-512 F/BW/CD/DQ/VL | SVE/SVE2 via `-march=armv9-a` (vector length is runtime) |

PGO: Clang IR-level (best for optimization) `-fprofile-generate` -> run with
`LLVM_PROFILE_FILE=prof/%p-%m.profraw` -> `llvm-profdata merge -output=app.profdata prof/*.profraw`
(always merge, it converts the format) -> rebuild with `-fprofile-use=app.profdata`; the
frontend `-fprofile-instr-generate` flavour is for source correlation and coverage. GCC
`-fprofile-generate` (`-fprofile-update=atomic` for threads) -> run -> `-fprofile-use`
(`-fprofile-partial-training` keeps untrained code optimized). Stale profiles only warn: retrain.

BOLT: link with `-Wl,--emit-relocs`; `perf record -e cycles:u -j any,u -o perf.data -- ./app`;
`perf2bolt -p perf.data -o perf.fdata ./app`; `llvm-bolt ./app -o app.bolt -data=perf.fdata
-reorder-blocks=ext-tsp -reorder-functions=cdsort -split-functions -split-all-cold -split-eh -dyno-stats`.

Function multiversioning (ifunc dispatch, GCC and Clang on x86 ELF; MSVC needs manual dispatch):

```cpp
__attribute__((target_clones("arch=x86-64-v4", "arch=x86-64-v3", "default")))
void saxpy(float a, const float* __restrict x, float* __restrict y, std::size_t n);
```

Clang emitted `.arch_x86-64-v4.0`, `.arch_x86-64-v3.1`, `.default.2` clones plus a resolver for
this. On AArch64, FMV support is newer and compiler-specific: check with `nm` that clones exist.

## 4. Data layout

| Pattern | Use when | Check |
|---|---|---|
| struct of arrays (SoA) | hot loop reads 1-3 fields of many objects | bytes touched per element before/after |
| array of structs (AoS) | each iteration uses most of the object | |
| hot/cold split | rarely used fields (names, debug info) inflate the hot struct | `sizeof` of the hot part, `static_assert` it |
| reorder members large to small | padding holes | `pahole -C Particle ./app` (DWARF), `-Wpadded` for a one-off survey |
| `alignas(std::hardware_destructive_interference_size)` | per-thread counters written concurrently | false sharing shows as HITM in `perf c2c` |

| Container need | Choose |
|---|---|
| sequence | `std::vector` (always `reserve` when the size is known); `std::deque` only for stable references |
| small sorted map, read-heavy, under ~1e5 elements | sorted vector or `std::flat_map` / `std::flat_set` (C++23: libstdc++ 15; libc++ 20 `flat_map`, 21 `flat_set`; check MSVC) |
| hash map | first `reserve` and a better hash; then open addressing: `absl::flat_hash_map`, `boost::unordered_flat_map` (1.81+), `ankerl::unordered_dense`, typically 2-5x faster than node-based `std::unordered_map` |
| bounded small collections | `boost::container::small_vector`, `absl::InlinedVector`, `std::inplace_vector` (C++26, check `__cpp_lib_inplace_vector`) |
| per-request scratch | `std::pmr::monotonic_buffer_resource` over a stack buffer, freed all at once |

```cpp
std::array<std::byte, 64 * 1024> buf;
std::pmr::monotonic_buffer_resource arena(buf.data(), buf.size());   // falls back to the heap when full
std::pmr::vector<Token> toks(&arena);
std::pmr::unordered_map<std::pmr::string, int> seen(&arena);         // nested strings use the arena too
```

## 5. Vectorizable loops

Auto-vectorization needs: a countable trip count, unit stride, no aliasing between inputs and
outputs, no early exit, only inlinable calls, and reductions the compiler may reassociate
(integers always; floats only with `-fassociative-math`/`-ffast-math` or an explicit pragma).

```bash
clang++ -O2 -Rpass=loop-vectorize -Rpass-missed=loop-vectorize -Rpass-analysis=loop-vectorize -c f.cpp
g++ -O2 -fopt-info-vec-optimized -fopt-info-vec-missed -c f.cpp           # MSVC: /Qvec-report:2
```

| Remark (Clang 21, real output) | Fix |
|---|---|
| "Cannot vectorize potentially faulting early exit loop" | search block-wise (compare a fixed-size block with no exit, OR the results, exit between blocks), or Highway `FindFirstTrue` |
| "cannot prove it is safe to reorder floating-point operations; allow reordering by specifying '#pragma clang loop vectorize(enable)' ... or ... '-ffast-math'" (x86) | `#pragma omp simd reduction(+:s)` with `-fopenmp-simd`, or several explicit accumulators |
| "vectorized loop (vectorization width: 4, interleaved count: 1)" on an AoS loop | not a win by itself: the vectorized AoS update ran 0.94 ns/particle vs 0.79 with vectorization off |
| aliasing / runtime checks | `__restrict` on the pointers (or hoist `data()` into locals) |

AArch64 trap: a float sum is reported "vectorized" without `-ffast-math`, but the asm is a strict
in-order reduction (`ldp q..` loads, then a chain of scalar `fadd s0, s0, ...`), so the add chain
stays serial. Use multiple accumulators or allow reassociation for that loop only.

```cpp
void saxpy(float a, std::span<const float> x, std::span<float> y) {
    const std::size_t n = std::min(x.size(), y.size());
    const float* __restrict xp = x.data();
    float* __restrict yp = y.data();
    for (std::size_t i = 0; i < n; ++i) yp[i] = a * xp[i] + yp[i];
}
```

Hints: `[[assume(n % 8 == 0)]]` (C++23; GCC 13+, Clang 19+) removes remainder handling;
`std::assume_aligned<64>(p)` (C++20) promises alignment, and lying is UB.
`-ffast-math` hazards: `-ffinite-math-only` folds `std::isnan(x)` to `false` (Clang 21 compiled it
to `mov w0, #0`); reassociation changes results run to run across vector widths; on some
toolchains it also sets flush-to-zero for the whole process. Prefer `-fno-math-errno` and
`-ffp-contract=fast` globally, reassociation per loop.

## 6. Explicit SIMD options

| Option | Portability | Runtime dispatch | Fits when |
|---|---|---|---|
| `std::simd` (C++26, `<simd>`, `std::simd::vec<T>`) | ISA-portable, standard | no | toolchain has it: GCC 16 ships an experimental, x86-only implementation without `__cpp_lib_simd` |
| `std::experimental::simd` (Parallelism TS 2) | libstdc++ 11+; libc++ partial (Apple libc++ lacks operators) | no | GCC today, migrating to C++26 later |
| Google Highway | x86 SSE2..AVX-512, NEON/SVE, RVV, WASM | yes (`HWY_DYNAMIC_DISPATCH`) | production portable kernels, one binary for all CPUs |
| xsimd | x86, NEON, fixed SVE, WASM, VSX, RVV | `xsimd::dispatch` | already using xtensor or Arrow |
| EVE | C++20, x86 up to AVX-512, NEON, fixed SVE | none built in: build per ISA | algorithm-style SIMD (`eve::wide`) |
| intrinsics (`<immintrin.h>`, `<arm_neon.h>`) | one ISA | manual | last 10% on one platform; pair with dispatch |
| `#pragma omp simd` | compiler-portable hint | no | the scalar loop is right and only legality blocks it; `-fopenmp-simd` enables just the pragmas |

TS-to-C++26 renames: `<experimental/simd>` -> `<simd>`; `native_simd<T>` -> `std::simd::vec<T>`;
`copy_from`/`copy_to` -> `unchecked_load`/`unchecked_store` (`partial_load`/`partial_store` for
tails); `reduce(v)` stays.

```cpp
#include <experimental/simd>
namespace stdx = std::experimental;
float dot(std::span<const float> a, std::span<const float> b) {
    using V = stdx::native_simd<float>;
    V acc = 0.f;
    std::size_t i = 0;
    for (; i + V::size() <= a.size(); i += V::size())
        acc += V(&a[i], stdx::element_aligned) * V(&b[i], stdx::element_aligned);
    float s = stdx::reduce(acc);
    for (; i < a.size(); ++i) s += a[i] * b[i];           // scalar tail
    return s;
}
```

Highway dispatch file, AVX2 and NEON intrinsic kernels, xsimd and the `__builtin_cpu_supports`
fallback: [SIMD kernels and dispatch](references/simd-kernels.md).

## 7. Branches

| Technique | When | Example |
|---|---|---|
| branchless select | unpredictable condition, cheap both sides | `x = c ? a : b;` usually becomes `cmov`/`csel` (check the asm); `std::min`, `std::clamp` |
| sort or partition first | branch depends on data order | `std::partition` hot items to the front, then two branch-free loops |
| `[[likely]]` / `[[unlikely]]` (C++20) | only with profile evidence of a skewed branch | error paths; PGO does this better |
| lookup table | small domain, expensive per-item logic | 256-entry table for byte classification; keep it in L1 (bytes, not ints) |
| compute instead of table | table would miss cache or the math is a few cycles | bit tricks, `std::popcount`, `std::countr_zero` |

## 8. Common review findings

| Smell | Fix | clang-tidy |
|---|---|---|
| `for (auto x : vec_of_strings)` copies | `const auto&` | `performance-for-range-copy` |
| `shared_ptr` / `std::string` by value only to read | `const T&`, `std::string_view` | `performance-unnecessary-value-param` |
| `std::endl` in loops | `'\n'` (endl flushes) | `performance-avoid-endl` |
| `map.find(k)` then `map[k]` | one lookup: `try_emplace`, reuse the iterator | |
| virtual call per element in a tight loop | `std::variant` + `std::visit`, `final` classes, batch by type | |
| `s = s + a + b` in loops | `std::format_to(std::back_inserter(s), ...)` into a reserved string | `performance-inefficient-string-concatenation` |
| `vector.push_back` in a loop of known size | `reserve` | `performance-inefficient-vector-operation` |
| `std::function` in hot callbacks | template parameter or `std::function_ref` (C++26) | |
| `vector.erase(begin())` repeatedly | `std::erase_if`, `std::deque` | |
| `std::regex` on a hot path | hand parser, CTRE, RE2 | |
| exceptions for control flow; `to_string`/`stringstream` formatting | `std::expected`; `std::to_chars`, `std::format_to` | |
| locks around counters | relaxed `std::atomic` or per-thread counters merged on read | |

## 9. Inspecting codegen

- Compiler Explorer (godbolt.org): paste the kernel with the exact flags; compare GCC and Clang.
- Any platform: `llvm-objdump -d --no-show-raw-insn -C app | awk '/<step_soa/,/^$/'` (GNU
  `objdump` takes the same flags); print the whole file only into `.stack/out/<agent>/`.
- Look for: x86 `ymm`/`zmm` registers and `ps` suffixes (`vfmadd213ps`) for packed float, `ss` for
  scalar; AArch64 `q` registers and `.4s` lanes (`fmla.4s v2, v1, v0[0]`) vs `s` registers.
- llvm-mca: `clang++ -O2 -S -o - f.cpp | llvm-mca -mcpu=znver4 -timeline -bottleneck-analysis`;
  restrict to a region with `__asm volatile("# LLVM-MCA-BEGIN k":::"memory")` and
  `"# LLVM-MCA-END"` (the markers can perturb codegen). Read `Block RThroughput` (cycles per
  iteration, lower is better), IPC and uOps per cycle against the dispatch width.

## 10. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| benchmark reports ~0 ns | result optimized away | `DoNotOptimize` on a non-const lvalue, `ClobberMemory` after stores |
| first variant always slower | frequency ramp, E-core start, cold caches | warm-up phase, random interleaving, repetitions |
| "vectorized" but not faster | strided (AoS) or strict-order reductions | inspect asm, benchmark, change layout |
| speedup vanishes in production | microbenchmark kept data hot in cache | end-to-end benchmark, production counters |
| `-march=native` binary crashes elsewhere | SIGILL on older CPUs | explicit `x86-64-v3` + `target_clones` or Highway dispatch |
| results differ with `-ffast-math` | reassociation, NaN folding, flush-to-zero | per-loop pragmas instead of a global flag |
| PGO build slower | unrepresentative training run | train on production-like input; check the profile matches |

## 11. Worked example: particle update, AoS -> SoA -> explicit SIMD

Baseline: `struct ParticleAoS { float px, py, pz, vx, vy, vz, mass; int id; char tag[32]; };`
(64 bytes, `static_assert`ed); the hot loop does `p.px += p.vx * dt` (and y, z), touching 24 of
64 bytes. SoA: six `std::vector<float>` (`px..vz`); variants are one fused loop over six streams
and three `axpy(dt, v, p, n)` passes (`p[i] += v[i] * dt` with `__restrict`).

Committed benchmark (Google Benchmark), one per variant:

```cpp
static void BM_StepSoA(benchmark::State& st) {
    ParticlesSoA s = make_soa(st.range(0));
    for (auto _ : st) { step_soa_split(s, 1e-3f); benchmark::ClobberMemory(); }
    st.SetItemsProcessed(st.iterations() * st.range(0));
}
BENCHMARK(BM_StepSoA)->Arg(4096)->Arg(1 << 20)->Arg(1 << 24);
```

Measured on an Apple M3 Ultra (Apple clang 21, `-O2`, NEON), ns per particle, best of three
interleaved medians after a 500 ms warm-up (a std::chrono harness with the same structure;
Google Benchmark was not installed in that environment):

| Variant | n = 4096 (in cache) | n = 2^20 | n = 2^24 (AoS 1 GiB) |
|---|---|---|---|
| AoS, default `-O2` (loop "vectorized", width 4) | 0.94 | 0.95 | 1.02 |
| AoS, `-fno-vectorize -fno-slp-vectorize` | 0.79 | 0.83 | 0.95 |
| SoA fused, vectorization off | 0.58 | 0.86 | 0.85 |
| SoA fused, auto-vectorized | 0.143 | 0.30 | 0.30 |
| SoA split into 3 axpy passes, auto-vectorized | **0.142** | **0.247** | **0.250** |
| SoA split, NEON intrinsics (4 lanes, not unrolled) | 0.193 | 0.256 | 0.259 |

Evidence and reading:
1. Layout alone (both builds without vectorization: 0.79->0.58, 0.83->0.86, 0.95->0.85) gave
   0.97-1.4x; layout plus vectorization gave 6.6x in cache and 3.8-4.1x out of cache. The remark
   says `axpy` vectorized with width 4, interleave 4; its loop body is two `ldp q, q` pairs per
   array, four `fmla.4s vN, vM, v0[0]` and `stp q, q` stores: 16 floats per iteration.
2. AoS costs about the same in and out of cache (0.94 vs 1.02): it is bound by strided shuffles,
   not memory, so prefetch tuning would not have helped it.
3. Bytes per particle drop from 128 (a 64-byte line read and written back) to 36 (24 read, 12
   written). Split SoA at 2^24 moves 36 B in 0.25 ns, about 144 GB/s from one core: compare with a
   STREAM-style copy on the same machine before spending more SIMD effort; past that point only
   fewer bytes (float16 velocities, fusing with the next pass) help.
4. Fission beat fusion out of cache (0.247 vs 0.30): two streams per pass prefetch better than six.
5. The hand-written NEON kernel lost to the compiler in cache (0.193 vs 0.142) because the
   compiler interleaved 4 vectors per iteration; explicit SIMD only after remarks show a miss, and
   unroll it.

On Linux confirm with counters, per variant binary: `perf stat -e
cycles,instructions,L1-dcache-load-misses,LLC-load-misses ./bench --benchmark_filter=BM_StepSoA/16777216`
and expect instructions and LLC misses per particle to fall with the time. Portable explicit
version for x86 fleets (Highway, runtime dispatch to SSE2/AVX2/AVX-512, i.e. 4/8/16 float lanes):

```cpp
// sim_hwy.cc
#undef HWY_TARGET_INCLUDE
#define HWY_TARGET_INCLUDE "sim_hwy.cc"
#include "hwy/foreach_target.h"           // must precede highway.h
#include "hwy/highway.h"
HWY_BEFORE_NAMESPACE();
namespace sim::HWY_NAMESPACE {
namespace hn = hwy::HWY_NAMESPACE;
void Axpy(float dt, const float* HWY_RESTRICT v, float* HWY_RESTRICT p, size_t n) {
    const hn::ScalableTag<float> d;
    const size_t N = hn::Lanes(d);
    const auto vdt = hn::Set(d, dt);
    size_t i = 0;
    for (; i + 2 * N <= n; i += 2 * N) {                      // unrolled x2, see finding 5
        hn::StoreU(hn::MulAdd(hn::LoadU(d, v + i), vdt, hn::LoadU(d, p + i)), d, p + i);
        hn::StoreU(hn::MulAdd(hn::LoadU(d, v + i + N), vdt, hn::LoadU(d, p + i + N)), d, p + i + N);
    }
    for (; i < n; ++i) p[i] += v[i] * dt;                     // or hn::LoadN / hn::StoreN
}
}  // namespace sim::HWY_NAMESPACE
HWY_AFTER_NAMESPACE();
#if HWY_ONCE
namespace sim {
HWY_EXPORT(Axpy);
void step_soa_hwy(ParticlesSoA& s, float dt) {
    for (auto [v, p] : {std::pair{&s.vx, &s.px}, {&s.vy, &s.py}, {&s.vz, &s.pz}})
        HWY_DYNAMIC_DISPATCH(Axpy)(dt, v->data(), p->data(), p->size());
}
}  // namespace sim
#endif
```

Link `hwy::hwy` (`find_package(hwy CONFIG REQUIRED)`; vcpkg port `highway`). Benchmark it as one
more `BM_` variant on the target machines; keep it only if it beats the auto-vectorized split loop
there (it was not measured on the M3, where the compiler already emits NEON).

Related: `cmake-presets` (LTO, PGO and `-march` presets), `cpp-testing-fuzzing` (benchmarks in
CTest, Catch2 `BENCHMARK`), `cpp-concurrency-atomics` (false sharing, contention),
`cpp-memory-raii` (allocation ownership), `performance-optimization`, `computer-graphics`, hub `cpp-craft`.
