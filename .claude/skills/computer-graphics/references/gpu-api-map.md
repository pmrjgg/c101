# GPU API map, synchronization and tooling

Verify signatures for extensions and recently changed APIs with context7
(`mcp__context7__resolve-library-id` then `mcp__context7__query-docs`) or the official spec before
writing code; the tables below are concept-level and stable.

## 1. Concept map

| Concept | Vulkan 1.3/1.4 | D3D12 | Metal (3 / 4) | WebGPU |
|---|---|---|---|---|
| Device / queue | VkDevice, VkQueue (graphics/compute/transfer families) | ID3D12Device, command queues (direct/compute/copy) | MTLDevice, MTLCommandQueue | GPUDevice, device.queue (single queue) |
| Recording | VkCommandBuffer from VkCommandPool | ID3D12GraphicsCommandList + allocator | MTLCommandBuffer + render/compute/blit encoders (Metal 4: command allocators) | GPUCommandEncoder, render/compute pass encoders |
| Render target setup | dynamic rendering (vkCmdBeginRendering) or render passes | OMSetRenderTargets / BeginRenderPass | MTLRenderPassDescriptor | beginRenderPass descriptor |
| Pipeline | VkPipeline (+ pipeline cache), or VK_EXT_shader_object | PSO (+ pipeline library) | MTLRenderPipelineState | GPURenderPipeline (createRenderPipelineAsync) |
| Small constants | push constants (≥128 bytes guaranteed) | root constants | setVertexBytes / setFragmentBytes (≤4 KB) | none in core; use a small uniform buffer |
| Binding | descriptor sets, descriptor indexing, descriptor buffers (ext) | root signature, descriptor heaps, SM 6.6 ResourceDescriptorHeap | argument buffers (tier 2 = bindless) | bind groups (default limit 4 groups) |
| Bindless | descriptor indexing (core 1.2) | SM 6.6 dynamic resources | argument buffers tier 2 | not in core |
| Hazards | explicit pipeline barriers (synchronization2) | resource state barriers or enhanced barriers | tracked by default; untracked heaps need fences/events (Metal 4 adds explicit barriers) | automatic |
| CPU-GPU sync | VkFence, timeline semaphores | ID3D12Fence | MTLSharedEvent, addCompletedHandler | queue.onSubmittedWorkDone, buffer.mapAsync |
| Present | VkSwapchainKHR | IDXGISwapChain | CAMetalLayer drawable | GPUCanvasContext |
| Indirect | vkCmdDrawIndexedIndirect(Count) | ExecuteIndirect | indirect command buffers | drawIndirect / drawIndexedIndirect |
| Mesh shading | VK_EXT_mesh_shader | mesh/amplification shaders (SM 6.5) | object/mesh shaders (Metal 3) | not available |
| Ray tracing | VK_KHR_acceleration_structure, ray_tracing_pipeline, ray_query | DXR 1.1 (inline RayQuery), 1.2 features in SM 6.9 | MTLAccelerationStructure, intersection functions | not available |
| Timestamps | vkCmdWriteTimestamp2, query pools | EndQuery with timestamp heap | counter sample buffers | timestamp-query feature (optional) |
| Memory | VMA (Vulkan Memory Allocator) | D3D12MA | heaps, storage modes (shared/private/managed) | implicit |

## 2. Barrier recipes

Vulkan synchronization2 (`VkImageMemoryBarrier2` / `VkBufferMemoryBarrier2`), src -> dst:

| Hazard | src stage / access | dst stage / access | Layout |
|---|---|---|---|
| Render target then sampled | COLOR_ATTACHMENT_OUTPUT / COLOR_ATTACHMENT_WRITE | FRAGMENT_SHADER / SHADER_SAMPLED_READ | COLOR_ATTACHMENT_OPTIMAL -> SHADER_READ_ONLY_OPTIMAL |
| Depth write then sampled (SSAO, shadows) | LATE_FRAGMENT_TESTS / DEPTH_STENCIL_ATTACHMENT_WRITE | FRAGMENT_SHADER (or COMPUTE) / SHADER_SAMPLED_READ | DEPTH_ATTACHMENT_OPTIMAL -> DEPTH_READ_ONLY_OPTIMAL |
| Upload then sample | COPY / TRANSFER_WRITE | FRAGMENT_SHADER / SHADER_SAMPLED_READ | TRANSFER_DST_OPTIMAL -> SHADER_READ_ONLY_OPTIMAL |
| Compute writes storage buffer, next dispatch reads | COMPUTE_SHADER / SHADER_STORAGE_WRITE | COMPUTE_SHADER / SHADER_STORAGE_READ | n/a (buffer) |
| Compute writes indirect args | COMPUTE_SHADER / SHADER_STORAGE_WRITE | DRAW_INDIRECT / INDIRECT_COMMAND_READ | n/a |
| Compute writes vertices | COMPUTE_SHADER / SHADER_STORAGE_WRITE | VERTEX_ATTRIBUTE_INPUT / VERTEX_ATTRIBUTE_READ | n/a |
| Before present | COLOR_ATTACHMENT_OUTPUT / COLOR_ATTACHMENT_WRITE | NONE / NONE | -> PRESENT_SRC_KHR |
| Write-after-read (reuse) | stage of the read / NONE | stage of the write / the write access | execution dependency is enough |

Rules: layout transitions are writes and need the full src scope; `UNDEFINED` as oldLayout
discards contents (fine for full overwrites, a bug otherwise); queue-family ownership transfers
need a release barrier on one queue and an acquire on the other; swapchain acquire semaphores must
be waited at COLOR_ATTACHMENT_OUTPUT (or the stage that first writes the image).

D3D12: legacy transitions (`RENDER_TARGET -> PIXEL_SHADER_RESOURCE`), UAV barriers between
dependent dispatches on the same resource, aliasing barriers when placed resources share memory.
Enhanced barriers (`D3D12_BARRIER_SYNC_*`, `D3D12_BARRIER_ACCESS_*`, `D3D12_BARRIER_LAYOUT_*`)
mirror Vulkan's model; prefer them in new code where the Agility SDK is available.

Metal: resources created from the device are hazard-tracked; resources sub-allocated from heaps
with untracked hazard mode need `MTLFence` (within a queue) or `MTLEvent` (across queues).
Metal 4 moves toward explicit allocators, residency sets and barriers: check the current docs.

WebGPU: no manual barriers; costs appear as validation failures instead (e.g. a texture used as
both render attachment and binding in one pass).

## 3. Frames in flight

```
N = 2 or 3
per frame i: command allocator/pool, uniform ring segment, descriptor pool, fence[i]
frame loop: wait fence[i] -> reset pool -> acquire swapchain image -> record -> submit (signal fence[i]) -> present
```

Bugs: writing a persistently mapped uniform buffer for frame i+N while the GPU still reads frame i
(flicker, garbage under load only); one fence for all frames (serialises CPU and GPU);
destroying resources referenced by in-flight command buffers (use a deferred-deletion queue keyed
by frame index or timeline value).

## 4. Validation and crash tooling

| API | Turn on | Notes |
|---|---|---|
| Vulkan | `VK_INSTANCE_LAYERS=VK_LAYER_KHRONOS_validation`, or Vulkan Configurator (`vkconfig`) to add synchronization validation, GPU-assisted validation, best-practices | `vulkaninfo --summary` for device features; VK_EXT_device_fault and Nsight Aftermath for device-lost |
| D3D12 | `D3D12GetDebugInterface` -> `EnableDebugLayer()`; `ID3D12Debug1::SetEnableGPUBasedValidation(TRUE)` | DRED auto-breadcrumbs and page-fault reporting for DEVICE_REMOVED |
| Metal | env `MTL_DEBUG_LAYER=1`, `MTL_SHADER_VALIDATION=1`, or Xcode scheme diagnostics | shader validation catches out-of-bounds and nil resource access |
| WebGPU | `device.pushErrorScope('validation')` ... `await device.popErrorScope()`; `device.addEventListener('uncapturederror', ...)`; `device.lost.then(...)` | messages include the label you gave each object: always set `label` |
| OpenGL | `glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS)` + `glDebugMessageCallback` | requires a debug context |

## 5. Shader toolchain commands

```bash
dxc -T ps_6_6 -E main shader.hlsl -Fo shader.dxil                       # D3D12
dxc -spirv -fspv-target-env=vulkan1.3 -T ps_6_6 -E main shader.hlsl -Fo shader.spv
glslc shader.frag -O -o shader.frag.spv                                 # shaderc; or glslangValidator -V
spirv-val shader.spv && spirv-dis shader.spv | less                     # validate and inspect
spirv-opt -O shader.spv -o shader.opt.spv
spirv-cross shader.spv --msl --output shader.metal                      # SPIR-V to MSL (also --hlsl)
slangc shader.slang -target spirv -entry main -stage fragment -o shader.spv
xcrun -sdk macosx metal -c shader.metal -o shader.air && xcrun -sdk macosx metallib shader.air -o shader.metallib
```

WGSL: compile and validate with Naga (wgpu) or Tint (Dawn); browsers validate at
`createShaderModule`, so call `getCompilationInfo()` and surface messages in tests.

Pin compiler versions in the build (DXC releases change codegen and warnings). Keep shader
compilation in CI with `-Werror`-equivalent flags and spirv-val on every output.

## 6. Capture and profile commands

```bash
renderdoccmd capture -w ./app --arg1                 # only for an app that exits on its own (frame limit / auto-quit); run under a Bash timeout
# qrenderdoc capture.rdc opens the interactive UI: human use only, never from an agent (it hangs headless/SDK runs).
# Agents capture via the in-application API below and return the .rdc path for inspection as an Open doubt.
nsys profile -t vulkan,nvtx,osrt --stats=true -o run ./app    # CPU-GPU timeline (Nsight Systems)
```

In-app capture: the RenderDoc in-application API (`StartFrameCapture` / `EndFrameCapture`) lets
tests capture exactly the failing frame; PIX has `PIXBeginCapture`/`PIXEndCapture`; Xcode supports
`MTLCaptureManager` programmatic captures. Nsight Graphics ships a CLI for automated captures;
check its `--help` for the current activity names.

Annotate passes (VK_EXT_debug_utils labels, PIX events, Metal debug groups, WebGPU `pushDebugGroup`)
so captures and timelines show names instead of draw indices.

## 7. Performance triage order

1. GPU timestamps per pass, median of 100 frames, fixed resolution, vsync off.
2. Is the frame CPU-bound? (GPU idle gaps in Nsight Systems / Metal System Trace / PIX timing.)
3. In the slowest pass: occupancy (registers, shared memory), memory bandwidth (render target
   formats, overdraw, texture formats and mips), ALU, or fixed-function (ROP, rasteriser, small
   triangles under ~10 pixels).
4. Common wins: compress textures (BC7/BC5/ASTC), R11G11B10F instead of RGBA16F where alpha is
   unused, meshlet cone culling, depth prepass only when overdraw is high, async compute for
   independent passes, fewer barriers (batch them), avoid read-back stalls (`mapAsync` / readback
   ring with N-frame latency).
5. Re-measure with at least 3 runs; report the GPU, driver version and clocks.
