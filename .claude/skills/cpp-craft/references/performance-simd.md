# C++ performance and SIMD

## 1. Measurement discipline

- Benchmark binaries are built exactly like production (`-O2`/`-O3`, same `-march`, LTO, PGO
  state). Debug numbers are meaningless.
- Google Benchmark:

```cpp
#include <benchmark/benchmark.h>
static void BM_Parse(benchmark::State& state) {
    auto input = make_input(state.range(0));
    for (auto _ : state) {
        auto r = parse(input);
        benchmark::DoNotOptimize(r);
    }
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(input.size()));
}
BENCHMARK(BM_Parse)->RangeMultiplier(8)->Range(64, 1 << 20);
BENCHMARK_MAIN();
```

```bash
./bench --benchmark_repetitions=10 --benchmark_report_aggregates_only=true \
        --benchmark_out=new.json --benchmark_out_format=json
python3 tools/compare.py benchmarks old.json new.json      # ships with google/benchmark
```

- Reduce noise: pin with `taskset -c 2`, close other workloads, use repetitions and report median
  and spread, not the best run. Fixing the CPU governor or disabling turbo (`sudo cpupower
  frequency-set -g performance`) needs root and changes the machine: return it as an Open doubt
  for the user, never run sudo yourself.
- Microbenchmarks lie about caches and branch predictors; confirm wins in an end-to-end
  benchmark or production metric.

## 2. Profiling toolbox

| Question | Tool | Command |
|---|---|---|
| where is CPU time | perf | `perf record -F 999 -g --call-graph dwarf ./app; perf report --stdio --no-children --percent-limit 2 \| head -60` |
| flame graph | perf + FlameGraph / Hotspot | `perf script | stackcollapse-perf.pl | flamegraph.pl > f.svg` |
| hardware counters | perf stat | `perf stat -e cycles,instructions,cache-misses,branch-misses,L1-dcache-load-misses ./app` |
| micro-architecture bottleneck | top-down | `perf stat --topdown` (Intel), VTune, AMD uProf |
| heap allocations | heaptrack | `heaptrack ./app; heaptrack_print heaptrack.app.*.zst > .stack/out/<agent>/heaptrack.txt`, then Grep the "MOST CALLS" / "PEAK MEMORY" sections (`heaptrack_gui` is humans only) |
| cache simulation | cachegrind | `valgrind --tool=cachegrind ./app` |
| instrumentation timeline | Tracy | `ZoneScoped;` macros, live viewer |
| loop throughput | llvm-mca | `clang++ -O2 -S -o - f.cpp | llvm-mca -mcpu=znver4` |
| macOS | Instruments | `xcrun xctrace record --template 'Time Profiler' --launch -- ./app` |
| compile time | Clang | `-ftime-trace` then open JSON in Perfetto / chrome://tracing |

Build with `-fno-omit-frame-pointer` (cheap) to get reliable stacks without DWARF unwinding.

## 3. Compiler and link-level levers

| Lever | Typical gain | Notes |
|---|---|---|
| `-O2` → `-O3` | 0-10% | can bloat code; measure |
| `-march=x86-64-v3` (AVX2, FMA, BMI2) | 0-30% on vectorizable code | binary will not run on older CPUs; use function multiversioning for portable binaries |
| LTO (`-flto=auto` / ThinLTO `-flto=thin`) | 5-15% | `CMAKE_INTERPROCEDURAL_OPTIMIZATION=ON` |
| PGO | 10-30% on branchy code | GCC `-fprofile-generate` → run → `-fprofile-use`; Clang `-fprofile-instr-generate` → `llvm-profdata merge` → `-fprofile-instr-use=` |
| BOLT post-link layout | 5-15% on large binaries | `perf record -e cycles:u -j any,u` then `llvm-bolt` |
| `-fno-plt`, `-fvisibility=hidden` | small | fewer indirections in shared libs |
| `-ffast-math` | varies | breaks IEEE semantics (NaN/Inf checks, associativity); prefer targeted `-fno-math-errno`, `-ffp-contract=fast` |

## 4. Data layout

- Contiguous beats linked: `std::vector`, `std::array`, `std::flat_map`/`std::flat_set` (C++23)
  over `std::list`, `std::map`, `std::set` for anything under ~10^5 elements or read-heavy.
- Hash maps: `std::unordered_map` allocates per node. Open addressing (`absl::flat_hash_map`,
  `boost::unordered_flat_map`, `ankerl::unordered_dense`) is typically 2-5x faster.
- Structure of arrays for hot loops touching one or two fields of many objects; array of
  structs when each iteration touches whole objects.
- Order struct members by size descending to remove padding; check with `sizeof` and
  `-Wpadded` (noisy; one-off survey).
- Small-size optimization: `boost::container::small_vector`, `absl::InlinedVector`,
  `std::inplace_vector` (C++26) for bounded small collections.
- Memory resources: `std::pmr::monotonic_buffer_resource` backed by a stack buffer for
  per-request allocations, freed all at once.

## 5. Writing vectorizable loops

Auto-vectorization succeeds when the loop has a countable trip count, unit stride, no aliasing
between input and output, no early exits, no function calls that cannot be inlined, and
reductions the compiler is allowed to reassociate (integers always; floats only with
`-ffast-math`/`-fassociative-math` or explicit `#pragma omp simd reduction(+:s)`).

```cpp
void saxpy(float a, std::span<const float> x, std::span<float> y) {
    const std::size_t n = std::min(x.size(), y.size());
    const float* __restrict xp = x.data();
    float* __restrict yp = y.data();
    for (std::size_t i = 0; i < n; ++i) yp[i] = a * xp[i] + yp[i];
}
```

Diagnose: Clang `-Rpass=loop-vectorize -Rpass-missed=loop-vectorize -Rpass-analysis=loop-vectorize`;
GCC `-fopt-info-vec-optimized -fopt-info-vec-missed`. Verify in Compiler Explorer or with
`objdump -d` (look for `ymm`/`zmm` registers on x86, `v` registers/`fmla` on ARM).

## 6. Explicit SIMD options

| Option | Portability | Notes |
|---|---|---|
| `std::simd` (C++26) / `std::experimental::simd` (libstdc++ 11+, Parallelism TS 2) | ISA-portable, standard | width via `simd<float>::size()`; check library support |
| Google Highway | x86, ARM (NEON/SVE), RISC-V V, WASM; runtime dispatch | production-grade (used in libjxl, Chromium) |
| xsimd | x86, ARM, WASM | used by xtensor, Apache Arrow |
| intrinsics (`<immintrin.h>`, `<arm_neon.h>`) | one ISA | maximal control; pair with runtime dispatch |
| OpenMP `#pragma omp simd` | compiler-portable hints | `-fopenmp-simd` enables only the SIMD pragmas |

`std::experimental::simd` example:

```cpp
#include <experimental/simd>
namespace stdx = std::experimental;
float dot(std::span<const float> a, std::span<const float> b) {
    using V = stdx::native_simd<float>;
    V acc = 0.f;
    std::size_t i = 0;
    for (; i + V::size() <= a.size(); i += V::size()) {
        V va(&a[i], stdx::element_aligned), vb(&b[i], stdx::element_aligned);
        acc += va * vb;
    }
    float s = stdx::reduce(acc);
    for (; i < a.size(); ++i) s += a[i] * b[i];          // scalar tail
    return s;
}
```

Runtime dispatch for portable binaries:

```cpp
__attribute__((target_clones("avx512f", "avx2", "default")))
void kernel(float* __restrict out, const float* __restrict in, std::size_t n);
```

(GCC and Clang on x86 ELF; MSVC needs manual dispatch with `__cpuid`.)

## 7. Common performance bugs in review

| Smell | Fix |
|---|---|
| `std::endl` in loops | `'\n'` (endl flushes) |
| `std::function` in hot callbacks | template parameter or `std::function_ref` |
| passing `std::string` by value to read | `std::string_view` |
| `map.find` then `map[key]` | single lookup: `try_emplace`, iterator reuse |
| `vector.erase(begin())` in a loop | `std::deque`, or erase-remove in one pass (`std::erase_if`) |
| `shared_ptr` everywhere | unique ownership + references |
| `std::regex` in hot paths | hand parser, CTRE (compile-time regex), RE2 |
| exceptions for control flow | `std::expected` |
| `std::to_string`/`stringstream` formatting | `std::format_to`, `std::to_chars` |
| `virtual` on tiny leaf functions | final classes (`final` enables devirtualization), variant |
| locks around counters | `std::atomic` relaxed or per-thread counters merged on read |

## 8. Worked example: AoS → SoA

Before: `struct Particle { Vec3 pos, vel; float mass; int id; std::string name; };` and the hot
loop updates `pos += vel * dt` for 10^6 particles. Each iteration loads ~64+ bytes to use 24.

After:

```cpp
struct Particles {
    std::vector<float> px, py, pz, vx, vy, vz;   // hot
    std::vector<float> mass;                      // warm
    std::vector<std::string> name;                // cold
};
void step(Particles& p, float dt) {
    const std::size_t n = p.px.size();
    for (std::size_t i = 0; i < n; ++i) { p.px[i] += p.vx[i] * dt; }
    for (std::size_t i = 0; i < n; ++i) { p.py[i] += p.vy[i] * dt; }
    for (std::size_t i = 0; i < n; ++i) { p.pz[i] += p.vz[i] * dt; }
}
```

Each loop is unit-stride and vectorizes; memory traffic drops to the bytes actually used.
Expect 3-8x on the loop in isolation; validate end-to-end since other code may now pay to
gather fields.
