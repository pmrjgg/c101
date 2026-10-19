---
name: vulkan-setup-synchronization
description: "Vulkan 1.3/1.4 bring-up and correctness: instance/device/queue selection with vk-bootstrap and volk, VMA memory, swapchain and frames in flight, dynamic rendering, synchronization2 barrier recipes, timeline semaphores, bindless and push descriptors, pipelines and shader toolchain, and the validation and sync-validation workflow. Load when writing Vulkan host code or fixing validation errors, flicker or device-lost."
when_to_use: "New Vulkan renderer or engine backend; VUID or SYNC-HAZARD validation messages; flicker, garbage or corruption only on some vendors or under load; VK_ERROR_DEVICE_LOST or TDR; swapchain OUT_OF_DATE, resize or present-mode issues; VMA allocation, staging or ReBAR questions; descriptor indexing, descriptor buffer or push descriptors; ash, vulkano or Vulkan-Hpp code."
---

# Vulkan setup and synchronization

Rule zero: validation (core + synchronization) is on in every debug run, and every message is a
bug. Target Vulkan 1.3 core features; use 1.4 core (push descriptors, dynamic rendering local
read) only after checking `apiVersion` of the selected device. Verify signatures with context7
(Vulkan-Hpp, ash, vulkano) before writing against an extension.

## 1. Bring-up checklist

1. Install the Vulkan SDK 1.4.x; check the device with `vulkaninfo --summary`.
2. Load entry points with volk; build instance and device with vk-bootstrap:

```cpp
VK_CHECK(volkInitialize());
auto inst = vkb::InstanceBuilder{}.set_app_name("app").require_api_version(1, 3, 0)
    .request_validation_layers(kDebug).use_default_debug_messenger().build().value();
volkLoadInstance(inst.instance);
VkPhysicalDeviceVulkan13Features f13{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
f13.dynamicRendering = VK_TRUE; f13.synchronization2 = VK_TRUE;
VkPhysicalDeviceVulkan12Features f12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
f12.timelineSemaphore = VK_TRUE; f12.bufferDeviceAddress = VK_TRUE;
f12.descriptorIndexing = VK_TRUE; f12.runtimeDescriptorArray = VK_TRUE;
f12.descriptorBindingPartiallyBound = VK_TRUE; f12.shaderSampledImageArrayNonUniformIndexing = VK_TRUE;
f12.descriptorBindingSampledImageUpdateAfterBind = VK_TRUE;
auto phys = vkb::PhysicalDeviceSelector{inst}.set_surface(surface).set_minimum_version(1, 3)
    .set_required_features_13(f13).set_required_features_12(f12).select().value();
auto dev = vkb::DeviceBuilder{phys}.build().value();
volkLoadDevice(dev.device);
VkQueue gfx = dev.get_queue(vkb::QueueType::graphics).value();
uint32_t gfxFamily = dev.get_queue_index(vkb::QueueType::graphics).value();
```

3. Debug-utils messenger on (vk-bootstrap's default prints to stderr); break on ERROR in debug.
4. Name every handle; captures and validation messages then show names, not hex:

```cpp
void setName(VkDevice d, VkObjectType t, uint64_t h, const char* n) {
    VkDebugUtilsObjectNameInfoEXT i{VK_STRUCTURE_TYPE_DEBUG_UTILS_OBJECT_NAME_INFO_EXT};
    i.objectType = t; i.objectHandle = h; i.pObjectName = n;
    vkSetDebugUtilsObjectNameEXT(d, &i);
}
// setName(dev, VK_OBJECT_TYPE_IMAGE, (uint64_t)gbufferAlbedo, "gbuffer.albedo");
```

5. Label passes with `vkCmdBeginDebugUtilsLabelEXT` / `vkCmdEndDebugUtilsLabelEXT`.

## 2. Memory with VMA

With volk, build VMA with `VMA_STATIC_VULKAN_FUNCTIONS 0` and `VMA_DYNAMIC_VULKAN_FUNCTIONS 1`
and pass `vkGetInstanceProcAddr`/`vkGetDeviceProcAddr` in `VmaVulkanFunctions`. Set
`VMA_ALLOCATOR_CREATE_BUFFER_DEVICE_ADDRESS_BIT`, and `..._EXT_MEMORY_BUDGET_BIT` once
`VK_EXT_memory_budget` is enabled.

| Resource | `usage` | `flags` |
|---|---|---|
| vertex/index/textures/render targets | `VMA_MEMORY_USAGE_AUTO` | 0 (`DEDICATED_MEMORY_BIT` for large RTs) |
| staging upload | AUTO | `HOST_ACCESS_SEQUENTIAL_WRITE_BIT \| MAPPED_BIT` |
| per-frame uniform ring | AUTO | `HOST_ACCESS_SEQUENTIAL_WRITE_BIT \| MAPPED_BIT` |
| readback | AUTO | `HOST_ACCESS_RANDOM_BIT \| MAPPED_BIT` |
| device-local if host-writable (ReBAR) | AUTO | `HOST_ACCESS_SEQUENTIAL_WRITE_BIT \| HOST_ACCESS_ALLOW_TRANSFER_INSTEAD_BIT \| MAPPED_BIT` |

```cpp
VkMemoryPropertyFlags props; vmaGetAllocationMemoryProperties(vma, alloc, &props);
if (props & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) {          // ReBAR or UMA: write directly
    memcpy(info.pMappedData, src, size); vmaFlushAllocation(vma, alloc, 0, size);
} else { /* staging buffer + vkCmdCopyBuffer + COPY->consumer barrier (section 5) */ }
```

Rules: sequential-write memory is write-combined, so never read it back on the CPU; persistent
mapping is fine (MAPPED_BIT); flush is a no-op on coherent memory but required otherwise.
Alias transients with `vmaCreateAliasingImage`/`vmaCreateAliasingBuffer` on one allocation sized
to the max requirement. Each frame, `vmaGetHeapBudgets` and keep usage under ~90% of budget per
heap; above that, drop texture mips instead of letting the driver page.

## 3. Swapchain

Surface format: prefer `B8G8R8A8_SRGB` + `SRGB_NONLINEAR_KHR` (hardware encodes on write); use
`B8G8R8A8_UNORM` with a manual encode only when compute writes the swapchain (sRGB formats lack
storage support on many devices). HDR10: `A2B10G10R10_UNORM_PACK32` + `HDR10_ST2084_EXT`
(instance extension `VK_EXT_swapchain_colorspace`), PQ-encode in the shader, send metadata with
`vkSetHdrMetadataEXT`.

| Present mode | Tearing | Latency | Availability |
|---|---|---|---|
| FIFO | no | up to queue depth x vsync | always (only guaranteed mode) |
| FIFO_RELAXED | when late | like FIFO | optional |
| MAILBOX | no | low, drops stale frames | common on desktop, rare on mobile |
| IMMEDIATE | yes | lowest | optional; benchmarking |

- Acquire returns `OUT_OF_DATE_KHR`: recreate now (pass `oldSwapchain`), skip the frame.
  `SUBOPTIMAL_KHR`: finish the frame, recreate after present. Extent 0 (minimized): wait.
- Acquire semaphores: one per frame in flight. Render-finished semaphores: one per swapchain
  image, indexed by `imageIndex`; reusing a per-frame one triggers the semaphore-reuse VUIDs
  because the presentation engine may still hold it after the frame fence signals.
- `VK_KHR_swapchain_maintenance1` (SDK 1.4.321+, previously `VK_EXT_swapchain_maintenance1`):
  chain a present fence (`VkSwapchainPresentFenceInfo{KHR,EXT}`) to know when present resources
  and an old swapchain can be destroyed; without it, `vkDeviceWaitIdle` before destroying.

## 4. Frames in flight

```cpp
constexpr uint32_t N = 2;                       // 3 only if the GPU starves at 2
struct Frame { VkCommandPool pool; VkCommandBuffer cmd; VkSemaphore acquired;
               uint64_t doneValue = 0; uint32_t uboOffset; VkDescriptorPool dpool; };
Frame frames[N]; VkSemaphore timeline; uint64_t nextValue = 1;   // timeline semaphore

Frame& f = frames[frameNo % N];
VkSemaphoreWaitInfo wi{VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO};
wi.semaphoreCount = 1; wi.pSemaphores = &timeline; wi.pValues = &f.doneValue;
vkWaitSemaphores(dev, &wi, UINT64_MAX);         // GPU finished this slot's previous use
deletion.flush(f.doneValue);                     // destroy what that submission referenced
vkResetCommandPool(dev, f.pool, 0); vkResetDescriptorPool(dev, f.dpool, 0);
uint32_t img; VkResult r = vkAcquireNextImageKHR(dev, swap, UINT64_MAX, f.acquired, VK_NULL_HANDLE, &img);
// record, then submit (section 6) waiting f.acquired, signalling renderDone[img] and timeline = nextValue
f.doneValue = nextValue++;
```

Uniform ring: one mapped buffer of `N x segment`, offsets aligned to
`minUniformBufferOffsetAlignment` (at most 256). Deferred deletion: push
`{timelineValueOfLastUse, destroyFn}`; run entries when `vkGetSemaphoreCounterValue` >= value.

## 5. Barrier recipes (synchronization2)

| Hazard | src stage / access | dst stage / access | Layout |
|---|---|---|---|
| RT -> sampled | COLOR_ATTACHMENT_OUTPUT / COLOR_ATTACHMENT_WRITE | FRAGMENT_SHADER / SHADER_SAMPLED_READ | COLOR_ATTACHMENT_OPTIMAL -> SHADER_READ_ONLY_OPTIMAL |
| depth -> sampled | EARLY\|LATE_FRAGMENT_TESTS / DEPTH_STENCIL_ATTACHMENT_WRITE | FRAGMENT_SHADER or COMPUTE_SHADER / SHADER_SAMPLED_READ | DEPTH_ATTACHMENT_OPTIMAL -> DEPTH_READ_ONLY_OPTIMAL |
| upload -> sample | COPY / TRANSFER_WRITE | FRAGMENT_SHADER / SHADER_SAMPLED_READ | TRANSFER_DST_OPTIMAL -> SHADER_READ_ONLY_OPTIMAL |
| compute -> compute (RAW) | COMPUTE_SHADER / SHADER_STORAGE_WRITE | COMPUTE_SHADER / SHADER_STORAGE_READ | GENERAL stays |
| compute -> indirect | COMPUTE_SHADER / SHADER_STORAGE_WRITE | DRAW_INDIRECT / INDIRECT_COMMAND_READ | buffer |
| compute -> vertex | COMPUTE_SHADER / SHADER_STORAGE_WRITE | VERTEX_ATTRIBUTE_INPUT / VERTEX_ATTRIBUTE_READ | buffer |
| before present | COLOR_ATTACHMENT_OUTPUT / COLOR_ATTACHMENT_WRITE | NONE / NONE | -> PRESENT_SRC_KHR |
| write-after-read | stage of the read / NONE | stage of the write / NONE | execution dependency only |

```cpp
void imageBarrier(VkCommandBuffer cmd, VkImage img, VkImageAspectFlags aspect,
                  VkPipelineStageFlags2 srcS, VkAccessFlags2 srcA, VkPipelineStageFlags2 dstS,
                  VkAccessFlags2 dstA, VkImageLayout oldL, VkImageLayout newL) {
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
    b.srcStageMask = srcS; b.srcAccessMask = srcA; b.dstStageMask = dstS; b.dstAccessMask = dstA;
    b.oldLayout = oldL; b.newLayout = newL;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = img; b.subresourceRange = {aspect, 0, VK_REMAINING_MIP_LEVELS, 0, VK_REMAINING_ARRAY_LAYERS};
    VkDependencyInfo dep{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    dep.imageMemoryBarrierCount = 1; dep.pImageMemoryBarriers = &b;
    vkCmdPipelineBarrier2(cmd, &dep);        // batch several barriers per call in real code
}
```

Rules: a layout transition is a write and needs the full src scope; `oldLayout = UNDEFINED`
discards contents (right for full overwrites, a bug otherwise); queue-family ownership transfer
of EXCLUSIVE resources = a release barrier (dst stage NONE) on the source queue plus a matching
acquire (src stage NONE) on the destination queue, ordered by a semaphore. Where the driver
exposes `VK_KHR_unified_image_layouts` (SDK 1.4.321+), GENERAL is efficient almost everywhere,
so most transitions disappear; keep the stage/access dependencies, which are still required.

## 6. Timeline semaphores and submission

```cpp
VkSemaphoreSubmitInfo wait[1] = {{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, nullptr, f.acquired, 0,
    VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT}};
VkSemaphoreSubmitInfo sig[2] = {
    {VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, nullptr, renderDone[img], 0, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT},
    {VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, nullptr, timeline, nextValue, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT}};
VkCommandBufferSubmitInfo cb{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO, nullptr, f.cmd};
VkSubmitInfo2 si{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};
si.waitSemaphoreInfoCount = 1; si.pWaitSemaphoreInfos = wait;
si.commandBufferInfoCount = 1; si.pCommandBufferInfos = &cb;
si.signalSemaphoreInfoCount = 2; si.pSignalSemaphoreInfos = sig;
vkQueueSubmit2(gfx, 1, &si, VK_NULL_HANDLE);
```

Async compute: the compute queue signals `timeline = V`; the graphics submit waits `V` with
`stageMask` = the first consuming stage (e.g. FRAGMENT_SHADER), not ALL_COMMANDS. CPU waits
use `vkWaitSemaphores`, host signals `vkSignalSemaphore`. Binary semaphores remain mandatory for
`vkAcquireNextImageKHR` and `vkQueuePresentKHR`. Shared resources: `SHARING_MODE_CONCURRENT`
(simple; may disable compression on some GPUs) or EXCLUSIVE plus ownership transfers.

## 7. Descriptors in 2026

| Need | Mechanism |
|---|---|
| bindless textures/buffers | descriptor indexing: runtime array, `UPDATE_AFTER_BIND` + `PARTIALLY_BOUND` (+ `VARIABLE_DESCRIPTOR_COUNT`), layout flag `UPDATE_AFTER_BIND_POOL`, `nonuniformEXT(i)` in GLSL |
| descriptors as memory you manage | `VK_EXT_descriptor_buffer` (check support; capture tools lag) |
| a few per-draw bindings | push descriptors, core in 1.4 (`vkCmdPushDescriptorSet`, layout flag `PUSH_DESCRIPTOR_BIT`) |
| buffers without descriptors | buffer device address in push constants (128 B guaranteed, 256 B common) |

Pipeline-layout compatibility: binding a pipeline keeps sets 0..k bound if their layouts and the
push-constant ranges are identical, so put per-frame data in set 0, per-pass in 1, per-material
in 2, per-draw in 3.

| Rule | std140 (UBO default) | std430 (SSBO default) | scalar (`scalarBlockLayout`) |
|---|---|---|---|
| vec3 alignment / size | 16 / 12 | 16 / 12 | 4 / 12 |
| `float a[4]` stride | 16 | 4 | 4 |
| struct alignment | max member, rounded to 16 | max member | max scalar |

## 8. Pipelines and shaders

```cpp
VkRenderingAttachmentInfo color{VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO};
color.imageView = view; color.imageLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
color.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR; color.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
VkRenderingInfo ri{VK_STRUCTURE_TYPE_RENDERING_INFO};
ri.renderArea = {{0, 0}, extent}; ri.layerCount = 1;
ri.colorAttachmentCount = 1; ri.pColorAttachments = &color; ri.pDepthAttachment = &depthAtt;
vkCmdBeginRendering(cmd, &ri); /* draws */ vkCmdEndRendering(cmd);
// pipeline side: VkPipelineRenderingCreateInfo (formats) in pNext, renderPass = VK_NULL_HANDLE
```

Dynamic state: viewport and scissor always; cull mode, front face, depth test/write/compare and
topology are core 1.3 dynamic states, which cuts pipeline permutations. Persist the pipeline
cache: `vkGetPipelineCacheData` at exit, keyed by `vendorID`, `deviceID` and
`pipelineCacheUUID`; discard on mismatch. Shader objects (`VK_EXT_shader_object`) suit
permutation-heavy engines on desktop; graphics pipeline libraries suit fast linking where
shader objects are absent; plain pipelines plus a warm cache are fine for small renderers.

```bash
glslc -O --target-env=vulkan1.3 gbuffer.frag -o gbuffer.frag.spv
dxc -spirv -fspv-target-env=vulkan1.3 -T cs_6_6 -E main blur.hlsl -Fo blur.spv
slangc lighting.slang -target spirv -entry main -stage compute -o lighting.spv
for f in build/shaders/*.spv; do spirv-val --target-env vulkan1.3 "$f" || exit 1; done
```

## 9. Validation workflow

- Configure layers with `vkconfig` (Vulkan Configurator) or in code via `VK_EXT_layer_settings`:

```cpp
const VkBool32 on = VK_TRUE;
VkLayerSettingEXT s{"VK_LAYER_KHRONOS_validation", "validate_sync", VK_LAYER_SETTING_TYPE_BOOL32_EXT, 1, &on};
VkLayerSettingsCreateInfoEXT lsci{VK_STRUCTURE_TYPE_LAYER_SETTINGS_CREATE_INFO_EXT, nullptr, 1, &s};
instanceCreateInfo.pNext = &lsci;            // and enable the VK_EXT_layer_settings extension
```

- Run core, synchronization, GPU-assisted and best-practices validation as separate sessions
  (LunarG's recommendation; GPU-AV and Debug Printf are separate settings and older SDKs refuse
  to combine them). Setting and env-var spellings for GPU-AV/printf differ across SDKs: take
  them from the `khronos_validation_layer` doc of the installed SDK.
- Debug Printf: GLSL `#extension GL_EXT_debug_printf : enable` + `debugPrintfEXT("v=%f", v);`
  HLSL `printf("v=%f", v)` via DXC `-spirv`; messages arrive through the debug messenger.
- Device lost: enable `VK_EXT_device_fault` (feature `deviceFault`) and query after the error:

```cpp
VkDeviceFaultCountsEXT counts{VK_STRUCTURE_TYPE_DEVICE_FAULT_COUNTS_EXT};
vkGetDeviceFaultInfoEXT(dev, &counts, nullptr);
std::vector<VkDeviceFaultAddressInfoEXT> addr(counts.addressInfoCount);
std::vector<VkDeviceFaultVendorInfoEXT> vend(counts.vendorInfoCount);
VkDeviceFaultInfoEXT info{VK_STRUCTURE_TYPE_DEVICE_FAULT_INFO_EXT};
info.pAddressInfos = addr.data(); info.pVendorInfos = vend.data();
vkGetDeviceFaultInfoEXT(dev, &counts, &info);   // log info.description + faulting addresses
```

  On NVIDIA add Nsight Aftermath (GPU crash dumps + markers); see `gpu-debugging-profiling`.

## 10. Pitfalls

- Acquire semaphore waited at TOP_OF_PIPE or ALL_COMMANDS (stalls) or at a stage after the first
  write (race): wait at COLOR_ATTACHMENT_OUTPUT, or COMPUTE_SHADER if compute writes the image.
- One fence for all frames: CPU and GPU serialize; one timeline value per frame slot instead.
- Writing a mapped uniform or vertex buffer slot the GPU still reads: flicker under load only.
- Vulkan NDC is y-down with [0,1] depth: a GL projection renders upside down and loses half the
  depth range; flip with a negative viewport height (core since 1.1).
- Using a feature never enabled at device creation (works on one driver, VUID on another).
- `ALL_COMMANDS -> ALL_COMMANDS` with MEMORY_WRITE/READ as a "fix": hides the bug, costs
  bubbles, and the next refactor reintroduces the race.

## 11. Worked example: flicker only on AMD

Symptom: a ping-pong blur (pass 1 reads `texA` writes `texB`; pass 2 reads `texB` writes `texA`;
pass 3 repeats pass 1) flickers on AMD, is stable on NVIDIA. AMD overlaps back-to-back dispatches
without a barrier; the code only had the RAW barrier on `texA` between passes 2 and 3.
Sync validation (`validate_sync` on) reports, abridged (format varies by SDK):

```
SYNC-HAZARD-WRITE-AFTER-READ: vkCmdDispatch writes VkImage "blur.texB"
  usage: SYNC_COMPUTE_SHADER_SHADER_STORAGE_WRITE, prior_usage: SYNC_COMPUTE_SHADER_SHADER_STORAGE_READ
```

Fix: one sync2 call carrying both dependencies; the WAR needs only an execution dependency,
and both images stay in GENERAL (no transition, so no UNDEFINED discard):

```cpp
VkImageMemoryBarrier2 b[2]{{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2}, {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2}};
for (auto& x : b) { x.oldLayout = x.newLayout = VK_IMAGE_LAYOUT_GENERAL;
    x.srcQueueFamilyIndex = x.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    x.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    x.srcStageMask = x.dstStageMask = VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT; }
b[0].image = texA;  // RAW: pass 2 wrote, pass 3 reads
b[0].srcAccessMask = VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT; b[0].dstAccessMask = VK_ACCESS_2_SHADER_STORAGE_READ_BIT;
b[1].image = texB;  // WAR: pass 2 read, pass 3 writes
b[1].srcAccessMask = VK_ACCESS_2_NONE; b[1].dstAccessMask = VK_ACCESS_2_NONE;
VkDependencyInfo dep{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
dep.imageMemoryBarrierCount = 2; dep.pImageMemoryBarriers = b;
vkCmdPipelineBarrier2(cmd, &dep);
```

Verification, in order: (1) rerun with sync validation: zero SYNC-HAZARD messages over the whole
run; (2) deterministic mode (fixed timestep and seed, static camera), read back the blur output
every frame for 500 frames and hash it; the fixed build must yield one distinct hash (before the
fix: several distinct hashes; record the count); (3) repeat on NVIDIA and AMD; (4) keep the
500-frame hash test in CI as the regression guard.

Related: `raster-pipeline-architecture`, `gpu-debugging-profiling`, `gpu-compute-patterns`, `webgpu-wgsl`, `metal-apple-gpu`, `cpp-memory-raii`, `rust-unsafe-soundness`, hub `computer-graphics`
