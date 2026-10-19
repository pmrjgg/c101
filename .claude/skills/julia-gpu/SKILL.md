---
name: julia-gpu
description: "GPU programming in Julia. Covers CUDA.jl arrays and broadcast, custom kernels with launch configuration, vendor-agnostic KernelAbstractions (AMDGPU, Metal, oneAPI), CUBLAS/CUFFT/CUSPARSE through standard interfaces, profiling and memory management, and the common pitfalls. Load when moving Julia array code to a GPU, or writing or optimizing GPU kernels."
when_to_use: "Porting Julia loops or array code to CuArray, ROCArray, MtlArray or oneArray; writing @cuda or KernelAbstractions @kernel functions; 'Scalar indexing is disallowed' errors; InvalidIRError or KernelError when a kernel compiles; GPU code slower than the CPU version; OutOfGPUMemoryError; choosing the backend at runtime; testing GPU code on CI machines without a GPU."
---

# Julia GPU programming

GPUs win on data-parallel work with at least ~1e5-1e6 elements per launch and data that stays on
the device. A kernel launch costs ~5-20 µs and host-device copies run at PCIe speed
(~10-25 GB/s) against 200-3000 GB/s of device bandwidth, so a port that copies every iteration
or launches thousands of tiny kernels loses to the CPU.

Baseline: CUDA.jl 5.x, KernelAbstractions.jl 0.9/0.10, AMDGPU.jl, Metal.jl, oneAPI.jl. Check
each README for supported Julia and driver versions; the APIs below are stable across these
series unless marked.

| Work | Approach | Section |
|---|---|---|
| elementwise maps, broadcasts, reductions, scans, sorts | array programming | 2 |
| dense/sparse linear algebra, FFT, convolutions | vendor libraries via standard interfaces | 5 |
| stencils, scatter/gather, irregular per-element logic, portable code | KernelAbstractions kernel | 4 |
| warp shuffles, explicit shared-memory tiling, CUDA-only intrinsics | CUDA.jl kernel | 3 |

## 1. Setup checks

```julia
using CUDA
CUDA.functional()            # false: no usable driver/device; read the warning, then:
CUDA.versioninfo()           # driver, runtime artifacts, devices, memory
CUDA.device()                # current device; CUDA.device!(1) switches it for the current task
CUDA.set_runtime_version!(v"12.6")   # CUDA.jl 5: pins the runtime in LocalPreferences.toml; restart Julia
```

| Vendor | Package | Array | KernelAbstractions backend | Check | Float64 |
|---|---|---|---|---|---|
| NVIDIA | CUDA.jl | `CuArray` | `CUDABackend()` | `CUDA.functional()` | yes, slow on consumer cards |
| AMD | AMDGPU.jl | `ROCArray` | `ROCBackend()` | `AMDGPU.functional()` | yes |
| Apple | Metal.jl | `MtlArray` | `MetalBackend()` | `Metal.functional()` | no |
| Intel | oneAPI.jl | `oneArray` | `oneAPIBackend()` | `oneAPI.functional()` | device-dependent |
| CPU | KernelAbstractions | `Array` | `CPU()` | always | yes |
| fake GPU for CI | JLArrays | `JLArray` | `JLBackend()` (GPUArrays 11+) | always | yes |

Choose the backend at runtime by asking the data, not by branching on vendors:

```julia
using KernelAbstractions
backend = get_backend(x)                                  # CPU(), CUDABackend(), MetalBackend(), ...
y = KernelAbstractions.zeros(backend, Float32, size(x))   # allocate on the same device as x
```

Callers pick the device once (`CuArray(x_host)`, `MtlArray(x_host)`). Libraries load vendor
packages only through package extensions (`[weakdeps]`), never as hard dependencies. Structs that
hold arrays move with Adapt.jl: `Adapt.@adapt_structure MyParams`, then `adapt(CuArray, p)`.

## 2. Array programming first

```julia
x = CUDA.rand(Float32, 10^7)            # generated on the device
y = similar(x)
y .= 2f0 .* x .+ sin.(x)                # one fused kernel launch
s = sum(abs2, x)                        # device mapreduce; the scalar result comes back to the host
m = maximum(x; dims = 1)                # stays on the device
A = CuArray(rand(1000, 1000))           # keeps Float64
B = cu(rand(1000, 1000))                # converts to Float32 (meant for ML)
host = Array(y)                         # one transfer, at the end
```

- Dot every operation (or `@.`) so the whole expression fuses into one kernel; preallocate
  outputs and use in-place `.=`, `map!`, `mul!`.
- `sum`, `mapreduce`, `accumulate`, `cumsum`, `sort!`, `findall`, `any`/`all` run on the device.
- Element types must be isbits (`Float32`, `Int32`, immutable structs of isbits fields).
- No host loops over elements: `for i in eachindex(x) ... x[i]` is scalar indexing, an error by
  default in non-interactive sessions and microseconds per element when allowed.
- Contiguous `view`s are cheap; strided or index-vector views can hit slow generic paths.

## 3. Custom CUDA kernels

```julia
using CUDA: i32
function stencil_kernel!(out, inp)
    i = (blockIdx().x - 1i32) * blockDim().x + threadIdx().x     # x walks the first (contiguous) index
    j = (blockIdx().y - 1i32) * blockDim().y + threadIdx().y
    nx, ny = size(inp)
    if 1 < i < nx && 1 < j < ny                                    # guard: the grid overshoots
        @inbounds out[i, j] = 0.25f0 * (inp[i-1, j] + inp[i+1, j] + inp[i, j-1] + inp[i, j+1])
    end
    return nothing                                                 # kernels must return nothing
end

kernel = @cuda launch=false stencil_kernel!(out, inp)
config = launch_configuration(kernel.fun)                          # occupancy-based suggestion
tx = 32; ty = max(1, config.threads ÷ tx)
kernel(out, inp; threads = (tx, ty), blocks = (cld(size(inp, 1), tx), cld(size(inp, 2), ty)))
```

Reduction with warp shuffles, shared memory and one atomic per block:

```julia
function sum_kernel!(out, x)                      # launch with threads = 256
    tid = threadIdx().x
    i = (blockIdx().x - 1i32) * blockDim().x + tid
    v = i <= length(x) ? @inbounds(x[i]) : 0f0
    offset = 16i32
    while offset > 0i32                           # tree reduction inside each 32-lane warp
        v += shfl_down_sync(0xffffffff, v, offset)
        offset ÷= 2i32
    end
    partial = CuStaticSharedArray(Float32, 8)     # one slot per warp (256 / 32)
    lane, warp = (tid - 1i32) % 32i32 + 1i32, (tid - 1i32) ÷ 32i32 + 1i32
    lane == 1i32 && (partial[warp] = v)
    sync_threads()
    if tid == 1i32
        s = 0f0
        for w in 1:8
            s += partial[w]
        end
        CUDA.@atomic out[1] += s
    end
    return nothing
end
out = CUDA.zeros(Float32, 1)
@cuda threads = 256 blocks = cld(length(x), 256) sum_kernel!(out, x)
```

| Rule | Why |
|---|---|
| `return nothing`; no allocation, no string exceptions, `@cuprintln` instead of `println` | otherwise `KernelError` or `InvalidIRError` |
| isbits or device-convertible arguments (`CuArray` becomes `CuDeviceArray`) | host `Array` arguments do not compile |
| `Float32` literals (`0.25f0`) | `0.25` promotes the expression to Float64 |
| `1i32` in index arithmetic | Int64 index math costs registers |
| type-stable body, no non-const globals or untyped closures | no dynamic dispatch on the device |
| `sync_threads()` between shared-memory writes and reads | data races otherwise |
| `CuDynamicSharedArray(Float32, n)` plus `shmem = n * sizeof(Float32)` at launch | size known only at runtime |
| grid-stride loop (`i += blockDim().x * gridDim().x`) | one fixed grid covers any length |

## 4. KernelAbstractions (portable kernels)

```julia
using KernelAbstractions
@kernel function axpy_ka!(y, a, @Const(x))
    i = @index(Global)                               # linear global index
    @inbounds y[i] += a * x[i]
end

@kernel function stencil_ka!(out, @Const(inp))
    i, j = @index(Global, NTuple)
    nx, ny = size(inp)
    if 1 < i < nx && 1 < j < ny
        @inbounds out[i, j] = 0.25f0 * (inp[i-1, j] + inp[i+1, j] + inp[i, j-1] + inp[i, j+1])
    end
end

backend = get_backend(y)
axpy_ka!(backend, 256)(y, 2f0, x; ndrange = length(y))           # static workgroup size 256
stencil_ka!(backend, (16, 16))(out, inp; ndrange = size(inp))
KernelAbstractions.synchronize(backend)                           # launches are asynchronous
```

- `ndrange` is the iteration space and need not be a multiple of the workgroup size: the excess
  work-items are masked (unless the kernel opts out with `@kernel unsafe_indices=true`).
- Workgroups: 256 (1D) or (16, 16)/(32, 8) (2D) on GPUs; on `CPU()` use 1024 or more to amortise
  task overhead.
- In kernels: `@localmem Float32 (256,)` (shared memory), `@synchronize`, `@index(Local, Linear)`,
  `@groupsize()`, `@private`, `@uniform`; atomics through Atomix.jl (`Atomix.@atomic a[i] += v`).
- `@Const` marks read-only inputs, enabling read-only caches.
- One kernel runs on CUDA, AMDGPU, Metal, oneAPI and CPU; warp intrinsics are the reason to drop
  to section 3.

## 5. Vendor libraries through standard interfaces

| Operation | Call | NVIDIA library |
|---|---|---|
| GEMM, GEMV | `mul!(C, A, B)`, `A * B` | CUBLAS |
| batched matmul | `NNlib.batched_mul(A, B)` | CUBLAS batched |
| factorizations, solves | `lu!(A)`, `qr(A)`, `cholesky(Hermitian(A))`, `A \ b` | CUSOLVER |
| FFT | `using AbstractFFTs; p = plan_fft!(x); p * x` | CUFFT |
| sparse | `S = CUSPARSE.CuSparseMatrixCSR(A_sparse); mul!(y, S, x)` | CUSPARSE |
| conv, pooling, softmax | NNlib calls with `using cuDNN` loaded | cuDNN |
| random numbers | `CUDA.rand`, `CUDA.randn`, `rand!(x)` | CURAND |

AMDGPU and Metal back the same generic calls with their libraries where supported (rocBLAS, MPS);
coverage varies by element type, so check before relying on Float16 or complex. Look for a
library call before writing a kernel: a hand-written GEMM rarely reaches 30% of CUBLAS.

## 6. Performance

| Lever | Rule or threshold |
|---|---|
| `Float32` | consumer NVIDIA FP64 runs at 1/32-1/64 of FP32 throughput; Metal has no Float64 |
| coalescing | the fastest thread index (`threadIdx().x`, first `@index` component) walks the first array dimension |
| residency | inside loops: zero `Array(...)` calls and zero scalar reads |
| launch count | fuse broadcasts; kernels with under ~10 µs of work are launch-bound, merge them |
| bandwidth check | achieved GB/s = bytes moved / time; memory-bound kernels should reach 60-80% of peak |
| memory pool | `CUDA.memory_status()`; `CUDA.unsafe_free!(tmp)` for large temporaries in loops; `GC.gc(); CUDA.reclaim()` before a huge allocation |
| concurrency | every Julia task has its own stream: `@sync for c in chunks; Threads.@spawn work!(c); end` overlaps independent kernels and copies |
| occupancy | start from `launch_configuration`; Int32 math and less live state lower register use |

## 7. Profiling and debugging

```julia
CUDA.@time f!(y, x)                          # wall time and GPU allocations; synchronizes
t = CUDA.@elapsed f!(y, x)                   # device time from events
using BenchmarkTools
@btime CUDA.@sync f!($y, $x)                 # always synchronize inside benchmarks
CUDA.@profile f!(y, x)                       # integrated profiler: host API calls and kernel table
CUDA.@profile trace=true f!(y, x)            # per-launch timeline
# Nsight Systems: run Julia under nsys and wrap the region in CUDA.@profile external=true
@device_code_warntype @cuda launch=false kernel!(args...)   # instability inside the kernel
@device_code_llvm @cuda launch=false kernel!(args...)       # also @device_code_ptx, @device_code_sass
CUDA.allowscalar(false)                      # make scalar indexing an error, also in the REPL
```

| Error | Cause | Fix |
|---|---|---|
| `Scalar indexing is disallowed` | host code reads `x[i]` from a device array | broadcast or `mapreduce`; `CUDA.@allowscalar` only for one-off debugging |
| `InvalidIRError` (dynamic function invocation, unsupported call) | instability, non-const global, unsupported function | `@device_code_warntype`; pass values as arguments |
| `KernelError: passing non-bitstype argument` | host `Array` or struct holding arrays | `CuArray`; `Adapt.@adapt_structure` |
| `KernelError` about the return value | missing `return nothing` | add it |
| `OutOfGPUMemoryError` | batch too large, temporaries piling up | chunk, `unsafe_free!`, `CUDA.reclaim()` |
| results differ run to run | race: missing barrier or non-atomic accumulation | `sync_threads`/`@synchronize`, atomics |

## 8. Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| scalar indexing | error, or seconds-long loops when allowed | vectorize (section 2) |
| Float64 throughput on consumer GPUs | 10-30x slower than expected | `Float32` data and literals |
| timing without synchronization | impossibly fast numbers (launch only) | `CUDA.@sync`, `CUDA.@elapsed`, `synchronize(backend)` |
| out-of-memory | `OutOfGPUMemoryError` mid-run | chunk data, free temporaries, watch `CUDA.memory_status()` |
| type-unstable kernels | `InvalidIRError`, or slow kernels | `@device_code_warntype`; concrete argument types |
| `cu` changing the element type | Float64 silently becomes Float32 | `CuArray(x)` keeps it |
| transfers inside the loop | GPU idle most of the profile | keep data resident |
| uncoalesced access | bandwidth far below peak | first index on the fastest thread dimension |
| Float64 on Metal | compile error | Float32 only |
| first call timed | compilation counted | warm up first, or `@belapsed` |

## 9. Testing

```julia
using Test, JLArrays, KernelAbstractions
array_types = Any[Array, JLArray]
using CUDA; CUDA.functional() && push!(array_types, CuArray)   # CUDA loads fine without a GPU

@testset "axpy on $AT" for AT in array_types
    x = AT(rand(Float32, 1000)); y = AT(zeros(Float32, 1000))
    axpy!(y, 2f0, x)                                   # library function built on get_backend
    @test Array(y) ≈ 2f0 .* Array(x)
end
```

- JLArrays (from GPUArrays.jl) is a CPU-backed array that follows GPU rules: it catches scalar
  indexing and missing `get_backend` support on CI machines without a GPU.
- Compare against a CPU reference with `≈` and Float32 tolerances (`rtol = 1e-5`), never `==`.
- Real-GPU CI needs a GPU runner (self-hosted, or JuliaGPU's Buildkite for eligible open-source
  packages); hosted GitHub runners have none.

## 10. Worked example: axpy and a 2D stencil, CPU loops to KernelAbstractions

CPU starting point:

```julia
function axpy_cpu!(y, a, x)
    @inbounds @simd for i in eachindex(y, x)
        y[i] += a * x[i]
    end
    return y
end
function stencil_cpu!(out, inp)
    nx, ny = size(inp)
    @inbounds for j in 2:ny-1, i in 2:nx-1          # i innermost: column-major
        out[i, j] = 0.25f0 * (inp[i-1, j] + inp[i+1, j] + inp[i, j-1] + inp[i, j+1])
    end
    return out
end
```

Port: the loop body becomes the body of `axpy_ka!`/`stencil_ka!` (section 4) and the loop range
becomes `ndrange`. Check correctness against the CPU version before timing:
`Array(y_dev) ≈ axpy_cpu!(copy(y_host), 2f0, x_host)`, and the stencil interior likewise.

```julia
using KernelAbstractions, BenchmarkTools
function bench(AT; n = 2^24, N = 4096)
    x, y = AT(rand(Float32, n)), AT(rand(Float32, n))
    inp = AT(rand(Float32, N, N)); out = similar(inp)
    be = get_backend(x)
    ax, st = axpy_ka!(be, 256), stencil_ka!(be, (16, 16))
    t1 = @belapsed ($ax($y, 2f0, $x; ndrange = $n); KernelAbstractions.synchronize($be))
    t2 = @belapsed ($st($out, $inp; ndrange = size($inp)); KernelAbstractions.synchronize($be))
    # axpy moves 12 bytes per element (read x, read y, write y); the ideal stencil 8 per point
    return (axpy_ms = 1e3t1, axpy_GBs = 12n / t1 / 1e9, stencil_ms = 1e3t2, stencil_GBs = 8N^2 / t2 / 1e9)
end
bench(Array)          # CPU() backend; start Julia with -t auto
bench(CuArray)        # after using CUDA; likewise MtlArray (Metal), ROCArray (AMDGPU)
```

Expected magnitudes from a bandwidth model at ~80% of peak (estimates, not measurements: record
your own numbers in this table):

| Backend (example device) | Peak bandwidth | axpy, 2^24 (201 MB) | stencil, 4096² (134 MB) |
|---|---|---|---|
| CPU loop, one thread (DDR5 desktop) | ~20-40 GB/s per core | ~5-10 ms | ~4-7 ms |
| KernelAbstractions `CPU()`, all threads | ~60-80 GB/s | ~3 ms | ~2 ms |
| Apple M-series Pro (Metal) | ~150-200 GB/s | ~1.2-1.7 ms | ~0.8-1.1 ms |
| NVIDIA RTX 4090 (CUDA) | ~1000 GB/s | ~0.25 ms | ~0.17 ms |
| AMD MI250X, one GCD (AMDGPU) | ~1600 GB/s | ~0.16 ms | ~0.1 ms |

Acceptance: GPU axpy reaches at least 60% of the device's peak bandwidth and the stencil at least
50% (neighbour reads should hit cache). Far below that: check the 2D workgroup shape (first
dimension 16-32 wide), Float64 leaking into the kernel (`@device_code_warntype`), or a missing
synchronize in the timing. If `CPU()` loses to the plain loop, the problem is too small for the
task overhead: keep the CPU loop for small sizes.

Related: `julia-performance-allocations`, `julia-type-stability`, `julia-ml-flux-lux`, `julia-sciml-diffeq`, hub `julia-craft`
