---
name: gpu-compute-patterns
description: "Data-parallel GPU compute building blocks across CUDA, HLSL, GLSL/Vulkan, Metal and WGSL: thread-hierarchy mapping, coalescing and bank conflicts, reductions, prefix scans (reduce-then-scan vs decoupled look-back), radix sort, stream compaction, histograms, atomics, tiled shared memory, subgroup/wave intrinsics, indirect dispatch, libraries and verification. Load when writing or optimizing a compute kernel or porting one between APIs."
when_to_use: "Writing a compute shader or CUDA kernel; sum/min/max reductions, prefix sums, sorting, compaction, histograms or matrix tiling on the GPU; wave/subgroup/simdgroup intrinsics; porting kernels between CUDA, HLSL, GLSL, MSL and WGSL; low GB/s or occupancy; nondeterministic float results; hangs from spin-waiting kernels; choosing CUB, rocPRIM, FidelityFX or hand-written code."
---

# GPU compute patterns

Rule zero: every kernel has a CPU reference and an edge-size test before it gets optimized, and
every optimization is judged in effective GB/s (or keys/s) against the device's peak.

## 1. Terminology map

| Concept | CUDA | HLSL | GLSL (Vulkan) | Metal | WGSL |
|---|---|---|---|---|---|
| thread | thread | thread | invocation | thread | invocation |
| SIMD unit | warp | wave | subgroup | simdgroup | subgroup (feature) |
| group | block | thread group | workgroup | threadgroup | workgroup |
| group memory | `__shared__` | `groupshared` | `shared` | `threadgroup` | `var<workgroup>` |
| group barrier | `__syncthreads()` | `GroupMemoryBarrierWithGroupSync()` | `barrier()` | `threadgroup_barrier(mem_flags::mem_threadgroup)` | `workgroupBarrier()` |
| global id | `blockIdx.x*blockDim.x+threadIdx.x` | `SV_DispatchThreadID` | `gl_GlobalInvocationID` | `[[thread_position_in_grid]]` | `global_invocation_id` |
| local index | `threadIdx.x` | `SV_GroupIndex` | `gl_LocalInvocationIndex` | `[[thread_index_in_threadgroup]]` | `local_invocation_index` |
| lane / width | `%laneid` / `warpSize` | `WaveGetLaneIndex()` / `WaveGetLaneCount()` | `gl_SubgroupInvocationID` / `gl_SubgroupSize` | `[[thread_index_in_simdgroup]]` / `[[threads_per_simdgroup]]` | `subgroup_invocation_id` / `subgroup_size` |

Widths: NVIDIA 32; AMD 64 (GCN) or 32/64 (RDNA, driver-chosen); Apple 32; Intel 8/16/32
(compiler-chosen); Mali 16 (Valhall); Adreno 64/128; WebGPU: whatever the device reports.
Query the width at runtime; never bake 32 into correctness (only into tuning).

## 2. Launch sizing

- Group size 64-256, a multiple of 64 (full waves on AMD wave64, two warps elsewhere).
- `groups = ceil(n / size)`; guard with `active = i < n`. Never `return` early before a barrier;
  keep inactive threads alive through barriers and mask their loads and stores.
- Grid-stride loop when n is huge or unknown: `for (i = gid; i < n; i += threadsInGrid)`, grid =
  SM count x 4-8 resident groups.
- Occupancy: resident warps per SM are limited by registers (65,536 per SM on recent NVIDIA:
  64 regs/thread gives 65536 / (64 x 32) = 32 warps), shared memory per group and groups per SM.
  Low occupancy is fine for ILP-heavy kernels; it hurts latency-bound ones.
- Groups per dimension: 65,535 guaranteed in Vulkan, D3D12 and WebGPU (CUDA x: 2^31-1). Beyond
  that, 2D dispatch and `group = gid.x + gid.y * groupsX`.
- Watchdogs: Windows TDR (~2 s per submission), browsers and mobile drivers kill long work;
  split dispatches to < ~100 ms each.

## 3. Memory rules

- Coalescing: lane i touching address `base + 4i` is one 128-byte transaction per 32 lanes;
  stride k costs ~k transactions. Prefer SoA (`x[], y[], z[]`) over AoS when kernels read a
  subset of fields; use 16-byte vector loads (`float4`/`uint4`/`vec4<u32>`) for streaming.
- Bank conflicts: 32 banks x 4 bytes; column access to `float tile[32][32]` is a 32-way conflict;
  pad to `tile[32][33]`.
- Read-only data: `const __restrict__` (CUDA) for the read-only cache; textures for 2D locality
  and free filtering; uniform/constant buffers only for data all lanes read at the same address
  (divergent indexing into constant memory serializes).

## 4. Reduction

Order: per-lane accumulation (grid-stride) -> subgroup reduce -> shared memory across subgroups
-> one atomic per group, or per-group partials plus a second pass.

```cuda
__global__ void sumKernel(const float* __restrict__ x, float* out, int n) {
    float acc = 0.f;
    for (int i = blockIdx.x * blockDim.x + threadIdx.x; i < n; i += blockDim.x * gridDim.x) acc += x[i];
    for (int o = 16; o > 0; o >>= 1) acc += __shfl_down_sync(0xffffffffu, acc, o);  // warp reduce
    __shared__ float warpSums[32];
    int lane = threadIdx.x & 31, warp = threadIdx.x >> 5;
    if (lane == 0) warpSums[warp] = acc;
    __syncthreads();
    if (warp == 0) {
        acc = lane < (blockDim.x >> 5) ? warpSums[lane] : 0.f;
        for (int o = 16; o > 0; o >>= 1) acc += __shfl_down_sync(0xffffffffu, acc, o);
        if (lane == 0) atomicAdd(out, acc);       // nondeterministic order: see below
    }
}
```

Subgroup reduce elsewhere: `WaveActiveSum` (HLSL), `subgroupAdd` (GLSL, WGSL), `simd_sum` (MSL),
`__reduce_add_sync` (CUDA, integers, sm_80+). Floats: atomic order changes the last bits run to
run; for determinism write `partial[blockIdx.x]` and reduce in a fixed order. Tree reduction is
pairwise (error grows ~log n); use Kahan per lane for very long grid-stride sums.

## 5. Prefix scan

Work-efficient Blelloch scan of one tile in shared memory (exclusive; 256 threads, 512 items):

```hlsl
#define N 512
groupshared uint s[N];
uint BlellochExclusive(uint gi) {              // s[] already loaded; returns the tile total
    uint offset = 1;
    for (uint d = N >> 1; d > 0; d >>= 1) {    // up-sweep
        GroupMemoryBarrierWithGroupSync();
        if (gi < d) { uint ai = offset * (2 * gi + 1) - 1, bi = offset * (2 * gi + 2) - 1; s[bi] += s[ai]; }
        offset <<= 1;
    }
    GroupMemoryBarrierWithGroupSync();
    uint total = s[N - 1];
    GroupMemoryBarrierWithGroupSync();
    if (gi == 0) s[N - 1] = 0;
    for (uint d = 1; d < N; d <<= 1) {         // down-sweep
        offset >>= 1;
        GroupMemoryBarrierWithGroupSync();
        if (gi < d) { uint ai = offset * (2 * gi + 1) - 1, bi = offset * (2 * gi + 2) - 1;
                      uint t = s[ai]; s[ai] = s[bi]; s[bi] += t; }
    }
    GroupMemoryBarrierWithGroupSync();
    return total;
}
```

Faster in-group variant: subgroup inclusive/exclusive scans (`WavePrefixSum`,
`subgroupExclusiveAdd`, `simd_prefix_exclusive_sum`) plus a scan of per-subgroup totals.
Across groups:
- **Reduce-then-scan (portable default)**: (1) reduce each tile to `tileSums`; (2) scan
  `tileSums` (one group, or recursively); (3) scan each tile again and add its offset. ~3n
  memory traffic, no inter-group waiting, works on every API.
- **Decoupled look-back (Merrill-Garland 2016)**: single pass, ~2n traffic; each tile publishes
  its aggregate and inclusive prefix with status flags and spins on predecessors. It needs
  forward-progress guarantees between groups and acquire/release atomics: fine in CUDA (CUB),
  not guaranteed on Apple, mobile GPUs or WebGPU (WGSL atomics are relaxed only), where it can
  hang or read stale data.

## 6. Radix sort

LSD radix sort of 32-bit keys: 8-bit digits in 4 passes (256 buckets); each pass is stable
(histogram -> exclusive scan of `counts[digit][tile]` -> stable scatter). Onesweep
(Adinets-Merrill 2022) computes all 4 digit histograms in one upfront pass and fuses scan and
scatter with decoupled look-back (CUDA-class GPUs). Use libraries where they exist:
CUB `cub::DeviceRadixSort::SortKeys`/`SortPairs` (call once with null temp storage to get its
size), FidelityFX Parallel Sort (portable HLSL, 4-bit digits, reduce-then-scan).
Key transforms (sort as unsigned, invert afterwards):

```c
uint32_t f2u(uint32_t b) { return b ^ ((b >> 31) ? 0xFFFFFFFFu : 0x80000000u); } // IEEE float bits
uint32_t i2u(int32_t v)  { return (uint32_t)v ^ 0x80000000u; }                    // signed ints
// descending: ~key; key-value: scatter values to the same destination as their keys
```

## 7. Stream compaction and append

```glsl
bool keep = predicate(x);
uvec4 ballot = subgroupBallot(keep);
uint n = subgroupBallotBitCount(ballot);
uint rank = subgroupBallotExclusiveBitCount(ballot);
uint base = 0;
if (subgroupElect()) base = atomicAdd(outCount, n);   // one atomic per subgroup, not per lane
base = subgroupBroadcastFirst(base);
if (keep) outItems[base + rank] = x;
```

HLSL: `WaveActiveCountBits`, `WavePrefixCountBits`, `WaveIsFirstLane`, `WaveReadLaneFirst`.
Append order differs between runs; when order matters, use scan + scatter (section 5). Feed
the count to the next stage on the GPU: a 1-thread dispatch writes `{ceil(count / 64), 1, 1}`
into an indirect-args buffer, then a compute -> INDIRECT_COMMAND_READ barrier (Vulkan).

## 8. Histograms and atomics

Privatize: each group accumulates into a shared-memory histogram, then adds each non-zero bin to
the global one (one atomic per bin per group). Few hot bins (dark images, 64-bin luminance):
per-subgroup copies or aggregate equal keys first (`__match_any_sync` on NVIDIA).

| Atomic | CUDA | Vulkan/GLSL | HLSL (D3D12) | Metal | WebGPU |
|---|---|---|---|---|---|
| 32-bit int | yes | yes | yes | yes | yes (only kind) |
| 64-bit int | yes | `shaderBufferInt64Atomics` (1.2 feature) | SM 6.6 with a capability check | limited by family | no |
| float add | yes | `VK_EXT_shader_atomic_float` | not core (CAS loop) | `atomic<float>` in recent MSL | no (CAS loop on bits) |

Ordering: shader atomics are relaxed by default. Publishing data through a flag needs release on
the writer and acquire on the reader (Vulkan memory model semantics, CUDA `cuda::atomic_ref`
with memory orders or `__threadfence()`); WGSL has no such semantics.

## 9. Tiling patterns

```cuda
template <int T>                                    // C = A * B, row-major, T x T tiles
__global__ void matmulTiled(const float* A, const float* B, float* C, int M, int N, int K) {
    __shared__ float As[T][T], Bs[T][T];            // row reads of Bs: no bank conflicts
    int r = blockIdx.y * T + threadIdx.y, c = blockIdx.x * T + threadIdx.x; float acc = 0.f;
    for (int k0 = 0; k0 < K; k0 += T) {
        As[threadIdx.y][threadIdx.x] = (r < M && k0 + threadIdx.x < K) ? A[r * K + k0 + threadIdx.x] : 0.f;
        Bs[threadIdx.y][threadIdx.x] = (c < N && k0 + threadIdx.y < K) ? B[(k0 + threadIdx.y) * N + c] : 0.f;
        __syncthreads();
        for (int k = 0; k < T; ++k) acc += As[threadIdx.y][k] * Bs[k][threadIdx.x];
        __syncthreads();
    }
    if (r < M && c < N) C[r * N + c] = acc;
}
```

Convolution: load a `(T + 2r)^2` tile with halo cooperatively (loop over tile slots with stride
= group size), barrier, compute. Separable filters cost 2(2r+1) taps instead of (2r+1)^2.
Iterative passes ping-pong between two buffers with a barrier between dispatches. Real GEMM:
use cuBLAS/CUTLASS, MPS, or tensor/matrix cores; the kernel above is a teaching baseline.

## 10. Libraries and port table

| Primitive | CUDA (CCCL in CUDA 12/13) | HIP / ROCm | D3D12 / Vulkan | Metal | wgpu / WebGPU |
|---|---|---|---|---|---|
| reduce | `cub::DeviceReduce::Sum` | hipCUB / rocPRIM | wave ops + section 4 | `simd_sum` + section 4 | section 4 |
| scan | `cub::DeviceScan::ExclusiveSum` | rocPRIM | reduce-then-scan | reduce-then-scan | reduce-then-scan |
| sort | `cub::DeviceRadixSort`, `thrust::sort` | rocPRIM radix sort | FidelityFX Parallel Sort | hand-written (or MPSGraph sort) | hand-written (section 13) |
| histogram | `cub::DeviceHistogram` | rocPRIM | section 8 | `MPSImageHistogram` | section 8 |

Portable C++ layers: Kokkos (`parallel_reduce`, `parallel_scan`), SYCL (`reduction`, group
algorithms). Prefer a library on its home platform; hand-write only where none exists.

## 11. Verification and measurement

- CPU reference for every kernel; sizes 0, 1, 31, 32, 33, group-1, group, group+1, 2^20 and
  2^24+1 (beyond exact float integers); data: random, sorted, reversed, all equal, extremes
  (0, 0xFFFFFFFF, INT_MIN), floats with -0.0, denormals and NaN (define their order).
- Effective bandwidth = bytes that must move / kernel time; compare with peak (memory clock x
  bus width x data rate); memory-bound kernels should reach ~70-85% of peak.
- Tools: Nsight Compute (`ncu --set full -o report ./app`: speed-of-light, memory workload,
  stall reasons; it locks clocks to base by default), RGP, Xcode GPU counters.

## 12. Pitfalls

- Early `return` before a barrier: hang or undefined behavior (WGSL rejects some cases).
- Correctness that assumes 32 lanes; decoupled look-back on GPUs without forward progress.
- `atomicAdd` on floats expected to be bit-reproducible.
- Missing barrier between dispatches that share buffers (Vulkan); WebGPU orders them for you.
- Shared-memory tiles over the limit (WebGPU default 16 KiB, Metal 32 KiB, CUDA 48 KiB static).

## 13. Worked example: portable radix sort, 1M keys, WGSL and HLSL

Design: 1,048,576 u32 keys, tile = 1,024 keys (256 threads x 4), 1,024 tiles; per pass
(`shift` = 0, 8, 16, 24): `histogram` -> exclusive scan of `counts` (256 x 1,024 = 262,144
u32, digit-major, reduce-then-scan) -> `scatter` -> swap buffers. Shared memory ~6 KiB.

```wgsl
const WG = 256u; const KPT = 4u; const TILE = 1024u;
struct Params { n: u32, shift: u32, num_tiles: u32, _pad: u32 };
@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> keys_in: array<u32>;
@group(0) @binding(2) var<storage, read_write> keys_out: array<u32>;
@group(0) @binding(3) var<storage, read_write> counts: array<u32>;   // [digit][tile]; scanned in place
var<workgroup> s_hist: array<atomic<u32>, 256>;
var<workgroup> s_keys: array<u32, 1024>;
var<workgroup> s_sum: array<u32, 256>;
var<workgroup> s_total: u32;
var<workgroup> s_start: array<u32, 256>;
fn digit(k: u32) -> u32 { return (k >> P.shift) & 0xFFu; }

@compute @workgroup_size(256)
fn histogram(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_index) li: u32) {
  atomicStore(&s_hist[li], 0u);
  workgroupBarrier();
  for (var j = 0u; j < KPT; j++) {
    let i = wg.x * TILE + j * WG + li;                       // coalesced
    if (i < P.n) { atomicAdd(&s_hist[digit(keys_in[i])], 1u); }
  }
  workgroupBarrier();
  counts[li * P.num_tiles + wg.x] = atomicLoad(&s_hist[li]);
}

fn wg_exclusive_scan(li: u32, v: u32) -> u32 {              // Hillis-Steele over 256 lanes
  s_sum[li] = v;
  workgroupBarrier();
  for (var off = 1u; off < WG; off <<= 1u) {
    var t = 0u;
    if (li >= off) { t = s_sum[li - off]; }
    workgroupBarrier();
    s_sum[li] += t;
    workgroupBarrier();
  }
  if (li == WG - 1u) { s_total = s_sum[li]; }
  workgroupBarrier();
  return s_sum[li] - v;
}

@compute @workgroup_size(256)
fn scatter(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_index) li: u32) {
  let base = wg.x * TILE;
  var k: array<u32, 4>;
  for (var j = 0u; j < KPT; j++) {                           // blocked: thread owns 4 slots
    let i = base + li * KPT + j;
    if (i < P.n) { k[j] = keys_in[i]; } else { k[j] = 0xFFFFFFFFu; }   // padding sorts last
  }
  for (var b = 0u; b < 8u; b++) {                            // 8 stable 1-bit splits = digit sort
    var f: array<u32, 4>; var zeros = 0u;
    for (var j = 0u; j < KPT; j++) { f[j] = 1u - ((k[j] >> (P.shift + b)) & 1u); zeros += f[j]; }
    let zb = wg_exclusive_scan(li, zeros);
    var zpos = zb; var opos = s_total + li * KPT - zb;
    for (var j = 0u; j < KPT; j++) {
      if (f[j] == 1u) { s_keys[zpos] = k[j]; } else { s_keys[opos] = k[j]; }
      zpos += f[j]; opos += 1u - f[j];
    }
    workgroupBarrier();
    for (var j = 0u; j < KPT; j++) { k[j] = s_keys[li * KPT + j]; }
    workgroupBarrier();
  }
  for (var j = 0u; j < KPT; j++) {                           // first slot of each digit in the tile
    let p = li * KPT + j;
    if (p == 0u || digit(s_keys[p - 1u]) != digit(k[j])) { s_start[digit(k[j])] = p; }
  }
  workgroupBarrier();
  let real = min(TILE, P.n - base);
  for (var j = 0u; j < KPT; j++) {
    let p = li * KPT + j; let d = digit(k[j]);
    if (p < real) { keys_out[counts[d * P.num_tiles + wg.x] + p - s_start[d]] = k[j]; }
  }
}
```

HLSL port: the same kernels with `StructuredBuffer<uint>` / `RWStructuredBuffer<uint>`,
`groupshared`, `GroupMemoryBarrierWithGroupSync()`, `InterlockedAdd(sHist[d], 1)`,
`[numthreads(256, 1, 1)]`, `SV_GroupID` / `SV_GroupIndex`; replace `wg_exclusive_scan` with
`WavePrefixSum` plus a shared array of per-wave totals (keep the shared-memory version as the
fallback). Compile with `dxc -T cs_6_6` (D3D12) or `dxc -spirv` (Vulkan); validate WGSL with
`naga radix.wgsl`.

Validation: same seed (`std::mt19937 rng(42)`), copy, `std::sort` on the CPU, `memcmp` against
the GPU result for n = 0, 1, 1023, 1024, 1025, 1,048,576, 16,777,217, and for all-equal,
sorted, reversed, all-0xFFFFFFFF (collides with padding) and single-digit inputs.

Measurement: GPU timestamps around the 4 passes, 3 warm-ups, median of 20;
`Mkeys/s = n / t / 1e6`. Bound: ~15 MB moved per pass (keys read twice, written once, counts
scanned) -> ~60 MB per sort -> 0.15 ms at 400 GB/s (~7,000 Mkeys/s ceiling); the 8 barrier-heavy
splits per pass keep this design well below it. Record on two named GPUs (for example one
NVIDIA desktop GPU via Vulkan/HLSL and one Apple GPU via WebGPU), with driver/OS versions, next
to CUB `DeviceRadixSort` as the ceiling on NVIDIA; report numbers measured, never estimated.

Related: `webgpu-wgsl`, `vulkan-setup-synchronization`, `metal-apple-gpu`, `gpu-debugging-profiling`, `raster-pipeline-architecture`, `cpp-simd-performance`, `julia-performance-allocations`, hub `computer-graphics`
