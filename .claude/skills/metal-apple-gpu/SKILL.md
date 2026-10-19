---
name: metal-apple-gpu
description: "Metal 3 and Metal 4 on Apple silicon: device, queue and command setup (MTL4 command allocators, argument tables, residency sets), storage modes and heaps, TBDR-aware render passes (load/store actions, memoryless targets, tile shaders, programmable blending), argument buffers and bindless, MSL specifics, porting, shader validation and Xcode capture. Load when writing, porting or profiling Metal or metal-cpp code."
when_to_use: "Swift or metal-cpp Metal code; MTKView or CAMetalLayer setup; porting a Vulkan, D3D12 or OpenGL renderer to Apple platforms; MTL4CommandQueue, argument tables or residency sets; argument-buffer bindless; garbage reads or GPU page faults; memoryless or on-tile deferred rendering; EDR/HDR output; .gputrace captures, Metal HUD, Instruments Metal System Trace; MSL compile errors."
---

# Metal on Apple GPUs

Rule zero: gate every Metal 4 path on a family check, keep a Metal 3 path for older OS releases,
and run with API and shader validation in every debug build. Metal 4 spellings below were
checked for the drawable, event, argument-table address and barrier calls; verify the remaining
MTL4 method names against the SDK headers or Apple's "Drawing a triangle with Metal 4" sample.

## 1. Version and feature gate

| Level | OS | GPUs | Adds |
|---|---|---|---|
| Metal 3 | macOS 13+, iOS 16+ | Apple silicon, A13+, recent AMD/Intel Macs | mesh shaders, MetalFX upscaling, fast resource loading (MTLIO), offline compilation |
| Metal 3.2 | macOS 15+, iOS 18+ | as Metal 3 | residency sets, shader logging |
| Metal 4 | OS 26 releases | Apple M1 / A14 and later | `MTL4CommandQueue`, `MTL4CommandBuffer` + `MTL4CommandAllocator`, `MTL4ArgumentTable`, `MTL4Compiler`, explicit barriers, tensors in shaders, MetalFX frame interpolation and denoised upscaling |

```swift
guard let device = MTLCreateSystemDefaultDevice() else { fatalError("no Metal") }
let hasMetal3 = device.supportsFamily(.metal3)
let isApple7Plus = device.supportsFamily(.apple7)      // A14 / M1 and later
// Metal 4: check the OS 26 SDK family (e.g. .metal4) at runtime before creating MTL4 types
if #available(macOS 26, iOS 26, *), device.supportsFamily(.metal4) { useMetal4 = true }
```

## 2. Setup recipes

Swift, Metal 3 path, shaders precompiled into a metallib:

```swift
let queue = device.makeCommandQueue()!
let lib = try device.makeLibrary(URL: Bundle.main.url(forResource: "shaders", withExtension: "metallib")!)
let vd = MTLVertexDescriptor()
vd.attributes[0].format = .float3; vd.attributes[0].offset = 0;  vd.attributes[0].bufferIndex = 0
vd.attributes[1].format = .half2;  vd.attributes[1].offset = 12; vd.attributes[1].bufferIndex = 0
vd.layouts[0].stride = 16
let pd = MTLRenderPipelineDescriptor()
pd.label = "forward"; pd.vertexDescriptor = vd
pd.vertexFunction = lib.makeFunction(name: "vs_main"); pd.fragmentFunction = lib.makeFunction(name: "fs_main")
pd.colorAttachments[0].pixelFormat = .bgra8Unorm_srgb; pd.depthAttachmentPixelFormat = .depth32Float
let pso = try device.makeRenderPipelineState(descriptor: pd)

layer.device = device
layer.pixelFormat = .bgra8Unorm_srgb      // hardware sRGB encode on store
layer.maximumDrawableCount = 3            // 2 = lower latency, 3 = smoother under load
layer.displaySyncEnabled = true           // macOS; false allows tearing
layer.framebufferOnly = true              // false only if compute touches the drawable

let maxInFlight = 3
let inFlight = DispatchSemaphore(value: maxInFlight)
func frame() {
    inFlight.wait()
    let slot = frameNo % maxInFlight
    writeUniforms(into: uniformBuffers[slot])                 // never a slot the GPU may read
    let cb = queue.makeCommandBuffer()!
    cb.addCompletedHandler { [inFlight] _ in inFlight.signal() }
    guard let drawable = layer.nextDrawable() else { cb.commit(); return }  // handler still signals
    encodePasses(cb, drawable.texture, slot)
    cb.present(drawable); cb.commit(); frameNo += 1
}
```

metal-cpp mirrors the API with explicit ownership (`new*`/`alloc` return +1 references):

```cpp
#define NS_PRIVATE_IMPLEMENTATION
#define MTL_PRIVATE_IMPLEMENTATION
#define CA_PRIVATE_IMPLEMENTATION
#include <Metal/Metal.hpp>
#include <QuartzCore/QuartzCore.hpp>
MTL::Device* dev = MTL::CreateSystemDefaultDevice();
MTL::CommandQueue* q = dev->newCommandQueue();
NS::Error* err = nullptr;
MTL::Library* lib = dev->newLibrary(NS::String::string("shaders.metallib", NS::UTF8StringEncoding), &err);
// per frame: NS::AutoreleasePool* pool = NS::AutoreleasePool::alloc()->init(); ... pool->release();
```

Metal 4 frame (allocator per frame slot, argument table instead of per-encoder binds, completion
tracked with an `MTLSharedEvent` because MTL4 command buffers have no completion handlers):

```swift
cb4.beginCommandBuffer(allocator: allocators[slot])        // allocator reset only after event >= its frame
let enc = cb4.makeRenderCommandEncoder(descriptor: passDesc)!
table.setAddress(uniformBuffers[slot].gpuAddress, index: 0)
table.setTexture(albedo.gpuResourceID, index: 0)
enc.setArgumentTable(table, stages: [.vertex, .fragment])
// after a compute dispatch that produced data the fragment stage reads:
enc.barrier(afterQueueStages: .dispatch, beforeStages: .fragment, visibilityOptions: .device)
enc.endEncoding(); cb4.endCommandBuffer()
queue4.waitForDrawable(drawable)
queue4.commit([cb4])
queue4.signalDrawable(drawable)
drawable.present()
queue4.signalEvent(frameEvent, value: UInt64(frameNo))     // CPU waits on this before reusing slot
```

## 3. Storage modes and memory

| Mode | CPU | GPU | Use |
|---|---|---|---|
| `.shared` | read/write | read/write | uniforms, dynamic vertex data, staging (unified memory) |
| `.private` | none | read/write | render targets, static meshes/textures after a blit upload (enables lossless compression) |
| `.memoryless` | none | tile only | depth, MSAA and G-buffer targets that never leave tile memory |
| `.managed` | mirrored | mirrored | Intel/AMD Macs only; never on Apple silicon |

Heaps: `MTLHeapDescriptor` with `type = .placement` for explicit offsets and aliasing (or
`makeAliasable()` on resources from automatic heaps). Hazard tracking: device resources are
tracked by default; `.hazardTrackingModeUntracked` (heaps or resource options) removes CPU
overhead but then you order work yourself: `MTLFence` between encoders on one queue
(`updateFence` / `waitForFence`), `MTLEvent` / `MTLSharedEvent` across queues or with the CPU.
Metal 4 command buffers do not track hazards: use barriers (above) or fences.

## 4. Residency

Resources reached only through argument buffers (or GPU addresses) must be made resident:
- Metal 3: `encoder.useResource(tex, usage: .read, stages: .fragment)` or `useHeap(heap, stages:)`
  each encoder; prefer heaps (one call covers thousands of textures).
- macOS 15 / iOS 18+ and Metal 4: an `MTLResidencySet` built once, attached to the queue:

```swift
let rsd = MTLResidencySetDescriptor(); rsd.initialCapacity = 256
let rs = try device.makeResidencySet(descriptor: rsd)
rs.addAllocation(materialHeap); rs.addAllocation(meshBuffer)
rs.commit()                         // adds/removes take effect only after commit
queue.addResidencySet(rs)           // every command buffer on the queue sees it
// Metal 4: also add the CAMetalLayer's residency set so drawables are resident
```

Missing residency produces zeros, garbage or GPU page faults that vary by run and vanish under
capture (capture makes everything resident). Shader validation reports many of them.

## 5. Argument buffers (tier 2) for bindless

All Apple silicon reports `device.argumentBuffersSupport == .tier2`. Since Metal 3, write
`gpuResourceID` and `gpuAddress` directly into a buffer; no `MTLArgumentEncoder` needed:

```metal
struct Material {                       // must match the Swift layout byte for byte
    texture2d<float> albedo;            // 8 bytes (MTLResourceID)
    texture2d<float> normal;
    constant float4* params;            // 8-byte GPU address
    float roughness; uint flags;
};
fragment float4 fs_main(VOut in [[stage_in]], constant Material* mats [[buffer(1)]],
                        sampler s [[sampler(0)]]) {
    constant Material& m = mats[in.materialIndex];
    return m.albedo.sample(s, in.uv) * m.params[0];
}
```

```swift
struct MaterialGPU { var albedo: MTLResourceID; var normal: MTLResourceID
                     var params: UInt64; var roughness: Float; var flags: UInt32 }
let p = matBuffer.contents().bindMemory(to: MaterialGPU.self, capacity: count)
p[i] = MaterialGPU(albedo: a.gpuResourceID, normal: n.gpuResourceID,
                   params: paramBuf.gpuAddress + UInt64(i * 16), roughness: 0.5, flags: 0)
```

Texture arrays: `struct TextureTable { texture2d<float> tex[4096]; };` bound once and indexed by
material id. CPU writes race in-flight frames: either N copies of the table (one per frame
slot) or only write entries no in-flight frame references (free-list with frame tags).

## 6. TBDR optimization

| Attachment | loadAction | storeAction | storageMode |
|---|---|---|---|
| drawable / final color | `.clear` or `.dontCare` if fully overwritten | `.store` | private |
| depth used only in this pass | `.clear` (0.0 for reversed-Z) | `.dontCare` | `.memoryless` |
| MSAA color | `.clear` | `.multisampleResolve` | `.memoryless` |
| G-buffer read in the same pass | `.dontCare` | `.dontCare` | `.memoryless` |

`.load` costs a full read of the attachment from memory; `.store` a full write. Programmable
blending reads the current pixel's attachments in the fragment shader, so G-buffer and lighting
run in one render pass:

```metal
struct GBufOut { half4 lit [[color(0)]]; half4 albedo [[color(1), raster_order_group(0)]];
                 half4 normal [[color(2), raster_order_group(0)]]; float depth [[color(3), raster_order_group(0)]]; };
struct GBufIn  { half4 albedo [[color(1)]]; half4 normal [[color(2)]]; float depth [[color(3)]]; };
fragment half4 light_fs(LightOut in [[stage_in]], GBufIn g,      // reads on-tile data
                        constant Light* lights [[buffer(0)]]) {
    return shadePointLight(lights[in.lightId], g, in.position.xy); // additive blend into color(0)
}
```

Raster order groups (`[[raster_order_group(n)]]`) order overlapping fragments' accesses to the
same pixel. Tile shaders (`MTLTileRenderPipelineDescriptor`, `dispatchThreadsPerTile`) with
imageblocks run compute on tile memory mid-pass, e.g. per-tile light culling.

## 7. MSL compared with HLSL and GLSL

| Concept | MSL | HLSL | GLSL |
|---|---|---|---|
| address spaces | `device`, `constant`, `threadgroup`, `thread` | implicit, `groupshared` | `buffer`, `uniform`, `shared` |
| binding | `[[buffer(n)]]`, `[[texture(n)]]`, `[[sampler(n)]]` | `register(b0/t0/s0/u0, spaceN)` | `layout(set, binding)` |
| thread id | `[[thread_position_in_grid]]` | `SV_DispatchThreadID` | `gl_GlobalInvocationID` |
| SIMD | `simd_sum`, `simd_shuffle`, `simd_prefix_exclusive_sum` | `WaveActiveSum`, `WaveReadLaneAt` | `subgroupAdd`, `subgroupShuffle` |
| specialization | `[[function_constant(n)]]` | defines | specialization constants |
| reduced precision | `half` (native, fewer registers) | `min16float` | `mediump` |

```metal
constant bool kShadows [[function_constant(0)]];   // dead code removed per specialization
```

```swift
let fc = MTLFunctionConstantValues(); var on = true
fc.setConstantValue(&on, type: .bool, index: 0)
let fs = try lib.makeFunction(name: "fs_main", constantValues: fc)
```

Use `half` for colors, normals and BRDF terms (bandwidth, registers); keep `float` for positions,
depth and UV math on large textures. Porting: SPIR-V via `spirv-cross shader.spv --msl`; HLSL
codebases via Metal Shader Converter (DXIL to metallib, `metal-shaderconverter`). Build:

```bash
xcrun -sdk macosx metal -c -frecord-sources shaders.metal -o shaders.air   # sources visible in captures
xcrun -sdk macosx metallib shaders.air -o shaders.metallib
```

## 8. Debugging and profiling

- `MTL_DEBUG_LAYER=1` (API validation) and `MTL_SHADER_VALIDATION=1` (out-of-bounds, nil
  resources, residency; slow) in the scheme or environment; `MTL_HUD_ENABLED=1` for the Metal
  Performance HUD (FPS, GPU time, memory).
- Shader logging (Metal 3.2, macOS 15 / iOS 18+): compile with `-fmetal-enable-logging` (or the
  logging option in `MTLCompileOptions`), call `os_log_default.log_debug("v=%f", v)` in MSL,
  attach an `MTLLogState` (from an `MTLLogStateDescriptor` with `level` and `bufferSize`) to
  `MTLCommandBufferDescriptor.logState`, read via `addLogHandler`; without handlers messages
  go to the unified log (Console.app, Xcode). Setting `MTL_LOG_LEVEL` is reported to help.
- Command-buffer error reports (which encoder faulted):

```swift
let cbd = MTLCommandBufferDescriptor(); cbd.errorOptions = .encoderExecutionStatus
let cb = queue.makeCommandBuffer(descriptor: cbd)!
cb.addCompletedHandler { cb in
    guard let e = cb.error as NSError? else { return }
    let infos = e.userInfo[MTLCommandBufferEncoderInfoErrorKey] as? [MTLCommandBufferEncoderInfo] ?? []
    for i in infos where i.errorState == .faulted { print("faulted:", i.label, i.debugSignposts) }
}
```

- Programmatic capture of exactly one frame (needs `MTL_CAPTURE_ENABLED=1` outside Xcode):

```swift
let cd = MTLCaptureDescriptor()
cd.captureObject = device; cd.destination = .gpuTraceDocument
cd.outputURL = URL(fileURLWithPath: ".stack/out/metal/frame-\(frameNo).gputrace")
try MTLCaptureManager.shared().startCapture(with: cd)
frame()
MTLCaptureManager.shared().stopCapture()
```

- Xcode GPU frame capture: dependency viewer (pass graph, load/store per attachment), shader
  debugger, per-line shader cost, performance counters. Instruments:
  `xcrun xctrace record --template 'Metal System Trace' --launch -- ./MyApp` for CPU-GPU
  timeline, encoder durations and GPU counters (limiters, bytes read/written to main memory).
- Label everything: `label` on resources/encoders, `pushDebugGroup` around passes.

## 9. Pitfalls

- Writing a `.shared` buffer the GPU is still reading: flicker under load; use per-slot buffers.
- Wrong sRGB drawable format: `bgra8Unorm` plus a manual encode twice (washed out) or never.
- HDR without EDR setup: needs `wantsExtendedDynamicRangeContent = true`, `pixelFormat =
  .rgba16Float`, `colorspace = CGColorSpace(name: CGColorSpace.extendedLinearDisplayP3)`, and
  the screen's EDR headroom as the tonemapper's peak.
- Threadgroup memory over 32 KiB (`maxThreadgroupMemoryLength`) fails pipeline creation.
- `half` for world positions or depth: 11-bit mantissa, centimetre error at 10 m, metres at 10 km.
- `.load` on attachments that are cleared or overwritten anyway: a full-screen memory read.

## 10. Worked example: Vulkan deferred renderer to on-tile Metal

Baseline port (direct translation): G-buffer pass writes albedo RGBA8, normal RGBA16F, material
RGBA8, depth D32 to `.private` textures with `.store`; a lighting pass samples them.
Target: one render pass, memoryless G-buffer and depth, programmable-blending lighting.

Analytic traffic at 2560x1600 (4,096,000 px): baseline stores 4 + 8 + 4 + 4 = 20 B/px and
reloads 20 B/px: 164 MB/frame, 19.7 GB/s at 120 Hz. On-tile: only the final 4 B/px color is
stored: 16.4 MB/frame (-90%). Memoryless also frees 82 MB of private textures.

Steps:
1. Memoryless G-buffer: `td.storageMode = .memoryless; td.usage = .renderTarget` per target.
2. Pass descriptor per section 6: G-buffer attachments and depth `.dontCare` store, depth clear
   0.0 (reversed-Z), color(0) `.clear` / `.store`.
3. G-buffer fragment writes `GBufOut`; light volumes in the same encoder read `GBufIn` with
   additive blending on color(0); fullscreen directional light first.
4. Validate: API + shader validation clean; Xcode dependency viewer shows one pass, no stores
   for color(1..3) and depth.
5. Measure on a named GPU (for example "Apple M2 Pro, 19-core GPU, macOS 26.x"), same scene and
   camera, 300 frames after 60 warm-up, median of 3 runs: GPU frame time from Metal System Trace
   and bytes read/written to main memory from the GPU counters.

Record (fill with your measurements; expected direction from the analysis above):

| Variant | GPU ms (median) | Main-memory writes/frame | Main-memory reads/frame |
|---|---|---|---|
| Direct port, stored G-buffer | measured | ~ 82 MB G-buffer + 16 MB color | ~ 82 MB G-buffer + textures |
| On-tile, memoryless + programmable blending | measured | ~ 16 MB color | textures only |

Accept the change if bytes written drop by roughly the predicted 82 MB/frame and frame time does
not regress; if not, check for a stray `.store` or `.load` in the dependency viewer.

Related: `raster-pipeline-architecture`, `vulkan-setup-synchronization`, `gpu-debugging-profiling`, `gpu-compute-patterns`, `webgpu-wgsl`, `color-pipeline-tonemapping`, `cpp-memory-raii`, hub `computer-graphics`
