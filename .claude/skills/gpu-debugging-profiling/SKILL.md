---
name: gpu-debugging-profiling
description: "Shader debugging and GPU profiling across APIs: RenderDoc captures, pixel history and Python replay, Nsight Graphics/Systems/Aftermath, PIX with DRED, Xcode Metal debugger, Radeon GPU Profiler, Tracy GPU zones, shader printf, debug views, the black-screen checklist, and per-pass timestamp methodology. Load when a frame is wrong, a GPU hangs or crashes, or a pass is too slow; general method lives in debugging-method and performance-optimization."
when_to_use: "Black or wrong pixels, flicker, NaN sparkles or corrupted geometry; VK_ERROR_DEVICE_LOST, DXGI_ERROR_DEVICE_REMOVED, TDR or Metal command-buffer faults; a pass or frame over budget; choosing between RenderDoc, Nsight, PIX, RGP, Xcode or Tracy; shader printf or GPU asserts; debug visualization modes; image-diff regression tests from captures; CPU-bound vs GPU-bound questions."
---

# GPU debugging and profiling

Rule zero: capture exactly the failing frame with every pass labelled and every resource named,
and never trust a GPU number that is not a median of many frames at fixed clocks. Generic
hypothesis-driven method: `debugging-method`; generic measurement discipline:
`performance-optimization`.

## 1. Tool selection

| Tool | APIs / vendor | Best for |
|---|---|---|
| RenderDoc | Vulkan, D3D11, D3D12, OpenGL, GLES (any vendor) | frame capture, pixel history, shader debugging (not GL), mesh viewer, Python replay |
| Nsight Graphics | NVIDIA; Vulkan, D3D12, GL | GPU Trace (unit throughputs, limiter), shader profiler with stall reasons, RT inspector |
| Nsight Systems | NVIDIA + CPU | CPU-GPU timeline, queue gaps, frame pacing (`nsys`) |
| Nsight Aftermath | NVIDIA | GPU crash dumps with faulting shader line and markers |
| PIX | D3D12 (Windows, Xbox) | captures, timing captures, DRED analysis, GPU-based validation |
| Xcode Metal debugger + Instruments | Apple | frame capture, dependency viewer, per-line shader cost, Metal System Trace |
| RGP, RGA, Radeon Developer Panel | AMD | wave occupancy, barrier/cache-flush timing, ISA and VGPR counts |
| Intel GPA | Intel | frame analysis and metrics on Intel GPUs |
| Arm Performance Studio, AGI (Android GPU Inspector) | Mali, Adreno, Android | mobile counters, bandwidth, tiler cost |
| Tracy | Vulkan, D3D12, GL, Metal, CUDA zones | continuous CPU+GPU zones in a live build |
| Browser tooling | WebGPU | error scopes, `chrome://gpu`, Safari Web Inspector |

## 2. Capture procedure

Grab the failing frame from code, not by hand (agents: use the in-application API and return
the capture path; never launch the interactive `qrenderdoc` UI from an agent):

```cpp
#include "renderdoc_app.h"
RENDERDOC_API_1_6_0* rdoc = nullptr;
#ifdef _WIN32
if (HMODULE m = GetModuleHandleA("renderdoc.dll"))
    ((pRENDERDOC_GetAPI)GetProcAddress(m, "RENDERDOC_GetAPI"))(eRENDERDOC_API_Version_1_6_0, (void**)&rdoc);
#else
if (void* m = dlopen("librenderdoc.so", RTLD_NOW | RTLD_NOLOAD))   // present when launched under RenderDoc
    ((pRENDERDOC_GetAPI)dlsym(m, "RENDERDOC_GetAPI"))(eRENDERDOC_API_Version_1_6_0, (void**)&rdoc);
#endif
if (rdoc) rdoc->SetCaptureFilePathTemplate(".stack/out/gpu/capture");
if (rdoc && frame == badFrame) rdoc->StartFrameCapture(nullptr, nullptr);
renderFrame();
if (rdoc && frame == badFrame) rdoc->EndFrameCapture(nullptr, nullptr);
```

Command line (only for an app that exits by itself): `renderdoccmd capture -w ./app <app args>`.
PIX: call `PIXLoadLatestWinPixGpuCapturerLibrary()` before creating the device, then
`PIXBeginCapture(PIX_CAPTURE_GPU, &params)` (with `params.GpuCaptureParameters.FileName`) and
`PIXEndCapture(FALSE)`. Metal: `MTLCaptureManager` to a `.gputrace` (see `metal-apple-gpu`).

| API | Pass labels | Resource names |
|---|---|---|
| Vulkan | `vkCmdBeginDebugUtilsLabelEXT` / `vkCmdEndDebugUtilsLabelEXT` | `vkSetDebugUtilsObjectNameEXT` |
| D3D12 | `PIXBeginEvent(cmd, PIX_COLOR_INDEX(n), "Bloom")` / `PIXEndEvent` | `ID3D12Object::SetName` |
| Metal | `pushDebugGroup` / `popDebugGroup` | `.label` |
| WebGPU | `pushDebugGroup` / `popDebugGroup` | `label` in every descriptor |
| OpenGL | `glPushDebugGroup` / `glPopDebugGroup` | `glObjectLabel` |

## 3. Wrong-pixel workflow (RenderDoc; same shape in PIX, Nsight, Xcode)

1. Texture viewer on the final target: pick the bad pixel, open Pixel History. It lists every
   event touching it, with depth/stencil/scissor/culling/discard results.
2. Jump to the last event that wrote it, or to the expected event that failed a test.
3. Pipeline state at that event: topology; viewport and scissor; cull mode and front face;
   depth test, compare op, write mask, clear value; blend factors and write masks; bound formats.
4. Debug the pixel from the history entry and step the shader; watch for NaN, zero lengths,
   wrong branches, sampling of the wrong mip.
5. Inputs: descriptor/resource inspector (right texture? right mip/slice?); buffer viewer with
   a format string, e.g. `float4x4 viewProj; float3 camPos; float exposure;`, to read constants.
6. Mesh viewer: VS input vs VS output; NaN or zero `w`, collapsed or mirrored geometry, winding.

## 4. Shader printf and asserts

Vulkan (validation layer Debug Printf enabled, see `vulkan-setup-synchronization`):

```glsl
#extension GL_EXT_debug_printf : enable
if (all(equal(ivec2(gl_FragCoord.xy), ivec2(640, 360))))   // one pixel only: output is limited
    debugPrintfEXT("n=%v3f rough=%f", n, roughness);
```

HLSL compiled with `dxc -spirv`: `printf("rough=%f", roughness);`. Metal: `os_log_default` in
MSL (Metal 3.2+). WGSL (no printf): a debug storage buffer read back with `mapAsync`:

```wgsl
struct Dbg { count: atomic<u32>, data: array<vec4<f32>> };
@group(3) @binding(0) var<storage, read_write> dbg: Dbg;     // zero `count` every frame
fn dbg_write(v: vec4<f32>) {
  let i = atomicAdd(&dbg.count, 1u);
  if (i < arrayLength(&dbg.data)) { dbg.data[i] = v; }
}
// GPU assert: if (!(len > 0.0)) { dbg_write(vec4<f32>(f32(ASSERT_ZERO_NORMAL), pos.xy, 0.0)); }
```

Out-of-bounds descriptor or buffer access: Vulkan GPU-assisted validation, D3D12 GPU-based
validation (`ID3D12Debug1::SetEnableGPUBasedValidation(TRUE)`), Metal shader validation.

## 5. Debug visualization views

Compile the views into the final shading pass behind one define; bind a key to cycle them.

```hlsl
#if DEBUG_VIEW == DV_NAN
    if (any(isnan(color)) || any(isinf(color))) return float4(1, 0, 1, 1);      // magenta
#elif DEBUG_VIEW == DV_OVERDRAW                     // additive blend, then ramp: 16 layers = white
    return float4(1.0 / 16.0, 1.0 / 16.0, 1.0 / 16.0, 1);
#elif DEBUG_VIEW == DV_MIP
    return float4(kMipColors[min(uint(tex.CalculateLevelOfDetail(samp, uv)), 7u)], 1);
#elif DEBUG_VIEW == DV_MOTION
    return float4(0.5 + motionUV * 20.0, 0.5, 1);   // static camera and scene: flat grey
#elif DEBUG_VIEW == DV_NORMAL
    return float4(N * 0.5 + 0.5, 1);
#endif
```

| View | Healthy | Defect it exposes |
|---|---|---|
| NaN/Inf magenta | none | normalize(0), sqrt(<0), 0/0, pow(<0, x); TAA spreads it forever |
| Overdraw | < 2-3 layers opaque | missing sort, prepass, particle fill rate |
| Light-count heatmap | < 32 per pixel | light radii, cluster depth convention |
| Mip level | smooth bands with distance | missing mips, derivative bugs, LOD bias |
| Motion vectors | grey when static | jitter in MVs, missing previous transforms |
| Normals | continuous | tangent-space or decode errors, seams |
| BVH node visits | < ~100 per ray | degenerate or stale BVH |
| Shadow cascade index | stable colors | split-scheme bugs, popping at boundaries |

## 6. Black screen and crash triage

Black screen, in order: (1) validation clean? (2) clear color visible (set it to magenta)?
(3) viewport and scissor sizes; (4) depth test direction and clear value (reversed-Z clears to 0);
(5) culling and winding; (6) projection handedness and depth range ([0,1] vs [-1,1]);
(7) shader outputs written to the right location/target; (8) swapchain sRGB vs UNORM;
(9) descriptor bound for this draw; (10) exposure not 0 or NaN.

Device lost / removed:
- NVIDIA: Nsight Aftermath. Call `GFSDK_Aftermath_EnableGpuCrashDumps` before device creation
  (watched API Vulkan or DX12, crash-dump and shader-debug-info callbacks), enable
  `VK_NV_device_diagnostics_config` on Vulkan, insert markers per pass; open the `.nv-gpudmp`
  in Nsight Graphics to see the faulting shader line and last markers.
- D3D12 DRED, before device creation:

```cpp
ComPtr<ID3D12DeviceRemovedExtendedDataSettings> dred;
D3D12GetDebugInterface(IID_PPV_ARGS(&dred));
dred->SetAutoBreadcrumbsEnablement(D3D12_DRED_ENABLEMENT_FORCED_ON);
dred->SetPageFaultEnablement(D3D12_DRED_ENABLEMENT_FORCED_ON);
// after DEVICE_REMOVED: device->QueryInterface(IID_PPV_ARGS(&data)) on ID3D12DeviceRemovedExtendedData,
// then GetAutoBreadcrumbsOutput (last completed op per list) and GetPageFaultAllocationOutput
```

- Vulkan elsewhere: `VK_EXT_device_fault` (`vkGetDeviceFaultInfoEXT`). Metal:
  `MTLCommandBufferDescriptor.errorOptions = .encoderExecutionStatus` names the faulted encoder.
- TDR: Windows resets the GPU after about 2 s of one submission; split long dispatches into
  chunks under ~100 ms. Raising the timeout is a dev-machine diagnostic, never a fix.

## 7. Profiling method

1. Per-pass GPU timestamps (Vulkan `vkCmdWriteTimestamp2`, D3D12 `EndQuery` with
   `D3D12_QUERY_TYPE_TIMESTAMP`, Metal counter sample buffers, WebGPU `timestampWrites`), read
   back N frames later without stalling.
2. Fixed conditions: vsync off, fixed resolution, scripted camera path, warm-up 100+ frames
   (shader caches, clocks), then the median of 100+ frames; report p95 too.
3. Lock clocks: `nvidia-smi --lock-gpu-clocks=<base>,<base>` (admin; read base with
   `nvidia-smi -q -d CLOCK`; undo with `nvidia-smi --reset-gpu-clocks`); D3D12
   `ID3D12Device::SetStablePowerState(TRUE)` (Developer Mode, profiling builds only); Nsight's
   lock-to-base option. Apple: no clock lock, so AC power, long runs, medians.
4. CPU-bound vs GPU-bound: `nsys profile -t vulkan,nvtx,osrt --stats=true -o run ./app`; GPU
   idle gaps between frames, or GPU busy < ~90% of frame time, mean the CPU or a sync stall.
5. Change one thing, re-measure 3 runs; report GPU, driver version and clocks with the medians.

Tracy for always-on zones: `TracyVkContext` + `TracyVkZone(ctx, cmd, "Bloom")` +
`TracyVkCollect(ctx, cmd)` (D3D12 and GL have equivalent macros).

## 8. Reading the bottleneck

Nsight GPU Trace: per-unit throughput as % of peak; the top unit is the limiter. Shader profiler:
warp stall reasons (long scoreboard = memory/texture latency; short scoreboard = shared memory
or special functions; barrier; math pipe throttle). Occupancy falls with registers per thread
and shared memory per group. RGP: wave occupancy over time, barrier and cache-flush cost, VGPR
counts per shader. Xcode: per-line shader cost and limiter counters.

| Limiter | Signal | Fixes |
|---|---|---|
| DRAM bandwidth | VRAM/DRAM throughput > ~70% | smaller formats (R11G11B10F, BC/ASTC), merge full-screen passes, lower-res passes |
| ALU | SM/ALU throughput high | simplify math, half precision, move work per-vertex/per-tile, LUTs |
| Texture | L1TEX/TEX high, long-scoreboard stalls | fewer taps, separable or mip-chain filters, gathers, mips |
| ROP | CROP/ZROP high | less overdraw and blending, smaller targets, early-Z |
| Raster / small triangles | primitive/raster units high, triangles < ~10 px | LOD, meshlet culling, visibility buffer |
| Latency / occupancy | everything low, few warps resident | cut registers, smaller shared memory, overlap with async compute |

## 9. Regression automation (RenderDoc Python replay)

```python
# export_passes.py  -- PYTHONPATH must contain RenderDoc's renderdoc module (built for this Python)
import sys, renderdoc as rd
cap_path, out_dir, passes = sys.argv[1], sys.argv[2], set(sys.argv[3].split(','))
rd.InitialiseReplay(rd.GlobalEnvironment(), [])
cap = rd.OpenCaptureFile()
if cap.OpenFile(cap_path, '', None) != rd.ResultCode.Succeeded:   # rd.ReplayStatus on old builds
    sys.exit('cannot open capture')
status, ctrl = cap.OpenCapture(rd.ReplayOptions(), None)
sf = ctrl.GetStructuredFile()
def walk(actions):
    for a in actions:
        yield a; yield from walk(a.children)
def last_event(a):
    while a.children: a = a.children[-1]
    return a.eventId
for a in walk(ctrl.GetRootActions()):
    name = a.GetName(sf)
    if name in passes and a.children:              # a debug-label marker region
        ctrl.SetFrameEvent(last_event(a), True)
        for i, t in enumerate(ctrl.GetPipelineState().GetOutputTargets()):
            rid = getattr(t, 'resource', None) or getattr(t, 'resourceId', None)
            if rid is None or rid == rd.ResourceId.Null(): continue
            ts = rd.TextureSave(); ts.resourceId = rid; ts.destType = rd.FileType.EXR
            ctrl.SaveTexture(ts, f'{out_dir}/{name}.rt{i}.exr')
ctrl.Shutdown(); cap.Shutdown(); rd.ShutdownReplay()
```

CI: capture frame N of a scripted scene, export the listed passes, compare each image with its
golden by RMSE (linear values; fail > 1e-3) and NVIDIA FLIP mean error (fail > ~0.01; check the
FLIP README for the current CLI or Python API); any NaN fails. Store diff images as artefacts.

## 10. Pitfalls

- Profiling with validation layers, GPU-AV or a debug runtime on: numbers are meaningless.
- Captures serialize work and change timing; races that disappear under capture are races
  (use sync validation instead).
- Comparing numbers across driver versions, power states or resolutions.
- CPU timers around GPU work measure submission, not execution.
- Single-run measurements; first frames include shader compilation.
- Unnamed resources: a capture full of "Texture 1234" costs hours.

## 11. Worked example: a 3 ms post-processing regression

Setup: commit A vs commit B, 2560x1440, scripted 600-frame camera path, vsync off, 100 warm-up
frames, clocks locked to base, 3 runs each. Per-pass timestamps isolate the regression to bloom.
Nsight GPU Trace on the bloom pass: L1TEX throughput near peak, DRAM moderate, SM low, long-
scoreboard stalls dominant: texture-bound. The shader takes 16 full-resolution taps per pixel in
each of 2 passes: 3,686,400 px x 16 x 2 = 118M RGBA16F fetches per frame.

Fix: a downsampled mip chain (13-tap downsample, 3x3 tent upsample with additive blend, 6 levels):

```hlsl
float3 Down13(Texture2D<float3> src, SamplerState s, float2 uv, float2 t) {  // t = 1 / source size
    float3 a = src.SampleLevel(s, uv + t * float2(-2, -2), 0), b = src.SampleLevel(s, uv + t * float2(0, -2), 0);
    float3 c = src.SampleLevel(s, uv + t * float2( 2, -2), 0), d = src.SampleLevel(s, uv + t * float2(-2, 0), 0);
    float3 e = src.SampleLevel(s, uv, 0),                      f = src.SampleLevel(s, uv + t * float2( 2, 0), 0);
    float3 g = src.SampleLevel(s, uv + t * float2(-2,  2), 0), h = src.SampleLevel(s, uv + t * float2(0,  2), 0);
    float3 i = src.SampleLevel(s, uv + t * float2( 2,  2), 0), j = src.SampleLevel(s, uv + t * float2(-1, -1), 0);
    float3 k = src.SampleLevel(s, uv + t * float2( 1, -1), 0), l = src.SampleLevel(s, uv + t * float2(-1,  1), 0);
    float3 m = src.SampleLevel(s, uv + t * float2( 1,  1), 0);
    return e * 0.125 + (a + c + g + i) * 0.03125 + (b + d + f + h) * 0.0625 + (j + k + l + m) * 0.125;
}
// upsample: 3x3 tent, weights [1 2 1; 2 4 2; 1 2 1] / 16, added onto the next larger level
```

Work after: chain pixels = 3.69M x (1/4 + 1/16 + ...) = 1.23M; downsample 1.23M x 13 = 16M
fetches, upsample 1.23M x 9 = 11M, composite 3.7M: about 31M fetches (3.8x fewer), at low
resolution where they hit cache.

Report (format; the values are illustrative placeholders, not a measurement):

| Pass | A median ms | B median ms | B + fix median ms |
|---|---|---|---|
| bloom | 0.41 | 3.47 | 0.38 |
| frame total | 9.80 | 12.86 | 9.77 |

Footer of the real report: GPU model, driver version, locked clock (MHz), resolution, runs x
frames, and FLIP/RMSE of the bloom output against A, reviewed visually because the filter
changed.

Related: `vulkan-setup-synchronization`, `metal-apple-gpu`, `webgpu-wgsl`, `raster-pipeline-architecture`, `gpu-compute-patterns`, `debugging-method`, `performance-optimization`, hub `computer-graphics`
