# SIMD kernels and runtime dispatch

One kernel (`p[i] += v[i] * dt`, the particle `axpy`) written every way the main skill lists.
Status per snippet: the AVX2 and NEON intrinsic kernels were compiled with Clang 21 (x86-64 and
arm64; disassembly showed `vfmadd213ps` on `ymm` and `fmla.4s` on `q` registers). The Highway,
xsimd and std::simd snippets follow each project's documented API and were not compiled in the
authoring environment: compile-check them on the target toolchain.

## Choosing a dispatch strategy

| Need | Strategy |
|---|---|
| one known deployment CPU (HPC cluster, own servers) | compile with `-march=<that level>`; no dispatch |
| x86 fleet with mixed AVX2 / AVX-512 | `target_clones` on a few hot functions, or Highway `HWY_DYNAMIC_DISPATCH` |
| many kernels, several ISAs including ARM | Highway (per-target namespaces, one binary) |
| xtensor / Arrow code base | xsimd `dispatch` |
| hand-tuned intrinsics | separate TU per ISA compiled with `-mavx2 -mfma` etc., chosen once at startup via `__builtin_cpu_supports("avx2")` (GCC/Clang x86) or `__cpuid` (MSVC) |

Rules: never let code compiled with `-mavx2` run before the CPU check (keep it in its own TU or
`__attribute__((target("avx2,fma")))` functions); resolve the function pointer once, not per call;
test every dispatched path in CI (Highway: `HWY_COMPILE_ALL_ATTAINABLE` plus its test utilities;
Intel SDE can emulate newer ISAs on older CI machines).

## Tail handling

| Technique | Cost | Notes |
|---|---|---|
| scalar remainder loop | up to `lanes - 1` scalar iterations | simplest; what the examples use |
| masked/partial load and store | one extra vector op | Highway `LoadN`/`StoreN`, C++26 `partial_load`/`partial_store`, AVX-512 masks |
| overlapping last vector | one redundant vector | only for idempotent element-wise ops on `n >= lanes` |
| pad allocations to a multiple of the lane count | zero | own the allocation; keep padding initialized |

## Intrinsics (verified to compile)

```cpp
#include <cstddef>
#if defined(__x86_64__)
#include <immintrin.h>
__attribute__((target("avx2,fma")))
void axpy_avx2(float dt, const float* __restrict v, float* __restrict p, std::size_t n) {
    const __m256 vdt = _mm256_set1_ps(dt);
    std::size_t i = 0;
    for (; i + 8 <= n; i += 8)
        _mm256_storeu_ps(p + i, _mm256_fmadd_ps(_mm256_loadu_ps(v + i), vdt, _mm256_loadu_ps(p + i)));
    for (; i < n; ++i) p[i] += v[i] * dt;
}
#elif defined(__aarch64__)
#include <arm_neon.h>
void axpy_neon(float dt, const float* __restrict v, float* __restrict p, std::size_t n) {
    std::size_t i = 0;
    for (; i + 4 <= n; i += 4)
        vst1q_f32(p + i, vfmaq_n_f32(vld1q_f32(p + i), vld1q_f32(v + i), dt));
    for (; i < n; ++i) p[i] += v[i] * dt;
}
#endif
```

Manual dispatch for the x86 version:

```cpp
using AxpyFn = void (*)(float, const float*, float*, std::size_t);
AxpyFn pick_axpy() {
    __builtin_cpu_init();                                  // needed if called before main (GCC)
    return __builtin_cpu_supports("avx2") && __builtin_cpu_supports("fma") ? axpy_avx2 : axpy_scalar;
}
static const AxpyFn axpy = pick_axpy();                    // resolved once
```

Measured lesson (M3 Ultra, see the main worked example): this NEON loop, not unrolled, ran 0.193
ns/particle in cache vs 0.142 for the plain C++ loop that Clang vectorized with width 4 and
interleave 4. Unroll explicit kernels 2-4x so several independent loads and FMAs are in flight.

## Google Highway with runtime dispatch

```cpp
// sim_hwy.cc  (one TU; foreach_target.h re-includes it once per enabled target)
#undef HWY_TARGET_INCLUDE
#define HWY_TARGET_INCLUDE "sim_hwy.cc"
#include "hwy/foreach_target.h"            // before highway.h
#include "hwy/highway.h"

HWY_BEFORE_NAMESPACE();
namespace sim {
namespace HWY_NAMESPACE {                  // unique per target, e.g. N_AVX2
namespace hn = hwy::HWY_NAMESPACE;

void Axpy(float dt, const float* HWY_RESTRICT v, float* HWY_RESTRICT p, size_t n) {
    const hn::ScalableTag<float> d;         // full native vector; lane count may be runtime (SVE, RVV)
    const size_t N = hn::Lanes(d);
    const auto vdt = hn::Set(d, dt);
    size_t i = 0;
    for (; i + 2 * N <= n; i += 2 * N) {
        hn::StoreU(hn::MulAdd(hn::LoadU(d, v + i), vdt, hn::LoadU(d, p + i)), d, p + i);
        hn::StoreU(hn::MulAdd(hn::LoadU(d, v + i + N), vdt, hn::LoadU(d, p + i + N)), d, p + i + N);
    }
    for (; i < n; i += N) {                 // masked tail: at most N lanes per step
        const size_t m = HWY_MIN(N, n - i);
        hn::StoreN(hn::MulAdd(hn::LoadN(d, v + i, m), vdt, hn::LoadN(d, p + i, m)), d, p + i, m);
    }
}
}  // namespace HWY_NAMESPACE
}  // namespace sim
HWY_AFTER_NAMESPACE();

#if HWY_ONCE                                // compiled once, after all targets
namespace sim {
HWY_EXPORT(Axpy);                           // table of per-target function pointers
void axpy(float dt, const float* v, float* p, size_t n) { HWY_DYNAMIC_DISPATCH(Axpy)(dt, v, p, n); }
}  // namespace sim
#endif
```

Highway is production-grade (used by libjxl and Chromium among others). API notes: `Load` requires vector-size alignment (may fault otherwise), `LoadU` needs only element
alignment; `MulAdd(a, b, c)` = `a * b + c`; `ReduceSum(d, v)` for horizontal sums; `HWY_RESTRICT`
expands to the compiler's restrict keyword; `HWY_STATIC_DISPATCH` picks the best target enabled by
the compile flags instead of dispatching at runtime. CMake: `find_package(hwy CONFIG REQUIRED)`,
`target_link_libraries(sim PRIVATE hwy::hwy)`; vcpkg port `highway`.

## xsimd with dispatch

```cpp
// axpy.hpp
#include <xsimd/xsimd.hpp>
struct axpy_k {
    template <class Arch> void operator()(Arch, float dt, const float* v, float* p, std::size_t n);
};
extern template void axpy_k::operator()<xsimd::avx2>(xsimd::avx2, float, const float*, float*, std::size_t);
extern template void axpy_k::operator()<xsimd::sse2>(xsimd::sse2, float, const float*, float*, std::size_t);

// axpy_impl.hpp: the out-of-class definition (in-class definitions defeat extern templates)
template <class Arch>
void axpy_k::operator()(Arch, float dt, const float* v, float* p, std::size_t n) {
    using B = xsimd::batch<float, Arch>;
    std::size_t i = 0;
    for (; i + B::size <= n; i += B::size)
        xsimd::fma(B::load_unaligned(v + i), B(dt), B::load_unaligned(p + i)).store_unaligned(p + i);
    for (; i < n; ++i) p[i] += v[i] * dt;
}
// axpy_avx2.cpp (compiled with -mavx2 -mfma): template void axpy_k::operator()<xsimd::avx2>(...);
// axpy_sse2.cpp (compiled with -msse2):      template void axpy_k::operator()<xsimd::sse2>(...);

// caller, no special flags:
auto axpy = xsimd::dispatch<xsimd::arch_list<xsimd::avx2, xsimd::sse2>>(axpy_k{});
axpy(dt, v, p, n);
```

## std::simd: Parallelism TS 2 today, C++26 next

```cpp
// libstdc++ 11+ (GCC): std::experimental::simd
#include <experimental/simd>
namespace stdx = std::experimental;
void axpy_ts(float dt, const float* v, float* p, std::size_t n) {
    using V = stdx::native_simd<float>;
    std::size_t i = 0;
    for (; i + V::size() <= n; i += V::size()) {
        V x(v + i, stdx::element_aligned), y(p + i, stdx::element_aligned);
        (x * dt + y).copy_to(p + i, stdx::element_aligned);
    }
    for (; i < n; ++i) p[i] += v[i] * dt;
}

// C++26 <simd>: GCC 16 ships an experimental implementation (x86 only, -std=c++26,
// __cpp_lib_simd not yet defined); signatures below follow its headers.
#include <simd>
namespace sm = std::simd;
void axpy_26(float dt, const float* v, float* p, std::size_t n) {
    using V = sm::vec<float>;                                   // native width by default
    std::size_t i = 0;
    for (; i + V::size() <= n; i += V::size())
        sm::unchecked_store(sm::unchecked_load<V>(v + i, V::size()) * dt
                            + sm::unchecked_load<V>(p + i, V::size()), p + i, V::size());
    if (i < n)                                                  // masked tail, zero-filled lanes
        sm::partial_store(sm::partial_load<V>(v + i, n - i) * dt
                          + sm::partial_load<V>(p + i, n - i), p + i, n - i);
}
```

Apple libc++ (Clang 21) provides `<experimental/simd>` only behind `-fexperimental-library` and
without arithmetic operators or `reduce`, so on macOS use Highway, xsimd or NEON intrinsics.

## OpenMP SIMD pragmas (no runtime, `-fopenmp-simd`)

```cpp
float dot(const float* a, const float* b, std::size_t n) {
    float s = 0.f;
    #pragma omp simd reduction(+ : s)     // permits reassociating this reduction only
    for (std::size_t i = 0; i < n; ++i) s += a[i] * b[i];
    return s;
}
```

Other clauses: `aligned(p : 64)`, `simdlen(8)`, `safelen(k)` for loops with a known minimum
dependence distance, `#pragma omp declare simd` on functions called inside such loops. Clang also
accepts `#pragma clang loop vectorize(enable) interleave_count(4)`; GCC has `#pragma GCC ivdep`.
