---
name: webgpu-wgsl
description: "WebGPU and WGSL in browsers (Chrome, Firefox, Safari) and natively (wgpu, Dawn): adapter limits and features, WGSL alignment rules, bind-group design, render and compute pipelines, uniformity analysis, canvas and HDR configuration, error scopes, timestamp queries, naga/Tint tooling and GLSL/HLSL ports. Load for any WebGPU, WGSL, wgpu or three.js WebGPURenderer task."
when_to_use: "Writing or porting WGSL; navigator.gpu, GPUDevice or wgpu code; 'must only be called from uniform control flow' errors; uniform struct offsets wrong or buffer size mismatches; bind-group layout or dynamic-offset validation errors; canvas format, sRGB or HDR output; device lost or uncaptured errors; timestamp profiling; GLSL/HLSL to WGSL conversion; three.js WebGPURenderer or TSL."
---

# WebGPU and WGSL

Rule zero: every object gets a `label`, every frame runs under error reporting in debug, and
optional features are detected, never assumed. wgpu (Rust) breaks its API in most major
releases: pin the version in Cargo.toml and check signatures with context7 before writing code.

## 1. Platform matrix

| Runtime | Status | Notes |
|---|---|---|
| Chrome / Edge | shipped since 113 (desktop), later Android | Dawn; `chrome://gpu` shows status |
| Firefox | Windows since 141; other platforms rolling out | wgpu-based |
| Safari | 26 (macOS, iOS, iPadOS, visionOS) | Metal backend; Web Inspector graphics tab |
| wgpu (Rust) | native Vulkan/Metal/D3D12/GL + wasm | breaking releases; pin version |
| Dawn (C++) | native, `webgpu.h` | also Node bindings (`webgpu` npm package) |
| three.js `WebGPURenderer` + TSL, Babylon.js | engines | TSL compiles node graphs to WGSL (or GLSL fallback) |

Detection: `if (!('gpu' in navigator)) fallback();` then `requestAdapter()` may still return null
(blocklisted GPU); `adapter.features.has('shader-f16')` per feature.

## 2. Device setup and limits

```js
const adapter = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' });
if (!adapter) throw new Error('no WebGPU adapter');
const wanted = ['shader-f16', 'timestamp-query', 'subgroups', 'float32-filterable', 'bgra8unorm-storage'];
const device = await adapter.requestDevice({
  label: 'main',
  requiredFeatures: wanted.filter((f) => adapter.features.has(f)),
  requiredLimits: {                       // ask only for what you use, capped by the adapter
    maxStorageBufferBindingSize: adapter.limits.maxStorageBufferBindingSize,
    maxComputeWorkgroupStorageSize: Math.min(32768, adapter.limits.maxComputeWorkgroupStorageSize),
  },
});
device.lost.then((i) => { console.error('device lost:', i.reason, i.message); if (i.reason !== 'destroyed') reinit(); });
device.addEventListener('uncapturederror', (e) => console.error('WebGPU:', e.error.message));
```

| Default limit | Value | Default limit | Value |
|---|---|---|---|
| maxBindGroups | 4 | maxComputeInvocationsPerWorkgroup | 256 |
| maxUniformBufferBindingSize | 64 KiB | maxComputeWorkgroupSizeX/Y/Z | 256/256/64 |
| maxStorageBufferBindingSize | 128 MiB | maxComputeWorkgroupStorageSize | 16 KiB |
| maxBufferSize | 256 MiB | maxComputeWorkgroupsPerDimension | 65535 |
| min{Uniform,Storage}BufferOffsetAlignment | 256 B | maxStorageBuffersPerShaderStage | 8 |
| maxDynamicUniformBuffersPerPipelineLayout | 8 | maxSampledTexturesPerShaderStage | 16 |
| maxDynamicStorageBuffersPerPipelineLayout | 4 | maxStorageTexturesPerShaderStage | 4 |
| maxColorAttachments | 8 | maxColorAttachmentBytesPerSample | 32 |
| maxTextureDimension2D | 8192 | maxTextureArrayLayers | 256 |
| maxVertexBuffers / maxVertexAttributes | 8 / 16 | maxInterStageShaderVariables | 16 |

Code written against the defaults runs everywhere; raising a limit excludes devices.

## 3. WGSL memory layout

| Type | Align | Size | Type | Align | Size |
|---|---|---|---|---|---|
| f32, i32, u32 | 4 | 4 | vec4<f32> | 16 | 16 |
| f16 (`enable f16;`) | 2 | 2 | mat3x3<f32> | 16 | 48 |
| vec2<f32> | 8 | 8 | mat4x4<f32> | 16 | 64 |
| vec3<f32> | 16 | 12 | array<T, N> | align(T) | N x roundUp(align, size) |

Struct: align = max member align; size rounded up to it. Extra `uniform` rules: array stride must
be a multiple of 16 (`array<f32, N>` is invalid there; use `array<vec4<f32>, N/4>` or a storage
buffer), and a member after a struct-typed member starts at least `roundUp(16, size)` later.

```wgsl
struct Camera {                 // offset size
  view_proj: mat4x4<f32>,       //   0    64
  position: vec3<f32>,          //  64    12
  exposure: f32,                //  76     4  (fills the vec3 tail)
  viewport: vec2<f32>,          //  80     8
  time: f32,                    //  88     4   -> size 96 (padded to 16)
};
struct PointLight { position: vec3<f32>, radius: f32, color: vec3<f32>, intensity: f32 }; // 32 B
struct Frame {
  camera: Camera,               //   0    96
  light_count: u32,             //  96     4
  lights: array<PointLight, 16>,// 112   512  (stride 32)  -> total 624
};
@group(0) @binding(0) var<uniform> frame: Frame;
```

```js
const buf = new ArrayBuffer(624), f = new Float32Array(buf), u = new Uint32Array(buf);
f.set(viewProj, 0); f.set(camPos, 16); f[19] = exposure; f[20] = w; f[21] = h; f[22] = time;
u[24] = lights.length;                                   // byte 96
lights.forEach((L, i) => { const o = 28 + 8 * i;         // byte 112 + 32 i
  f.set(L.pos, o); f[o + 3] = L.radius; f.set(L.color, o + 4); f[o + 7] = L.intensity; });
device.queue.writeBuffer(frameUbo, 0, buf);
```

Do not hand-compute offsets for big structs: webgpu-utils (`makeShaderDataDefinitions` +
`makeStructuredView`) or wgsl_reflect in JS; in Rust, `encase` (`#[derive(ShaderType)]`, writes
WGSL layout) or `bytemuck` with `#[repr(C)]` and explicit padding fields, plus a size assert.

## 4. Bind-group strategy

| Group | Frequency | Typical contents |
|---|---|---|
| 0 | per frame | camera/frame UBO, samplers, environment maps |
| 1 | per pass | shadow maps, cluster lists, pass constants |
| 2 | per material | material textures + material UBO |
| 3 | per draw | object UBO ring with `hasDynamicOffset: true`; `setBindGroup(3, g, [i * 256])` |

```js
const bglFrame = device.createBindGroupLayout({ label: 'bgl.frame', entries: [
  { binding: 0, visibility: GPUShaderStage.VERTEX | GPUShaderStage.FRAGMENT, buffer: { type: 'uniform' } },
  { binding: 1, visibility: GPUShaderStage.FRAGMENT, sampler: { type: 'filtering' } } ] });
const layout = device.createPipelineLayout({ label: 'pl.main', bindGroupLayouts: [bglFrame, bglPass, bglMat, bglDraw] });
```

`layout: 'auto'` pitfalls: each pipeline gets its own layouts, so bind groups from
`pipeline.getBindGroupLayout(n)` cannot be shared across pipelines, and bindings the shader does
not statically use are dropped, so `createBindGroup` with them fails. Use explicit layouts
beyond prototypes. No bindless in core: use `texture_2d_array` (same size and format), atlases
with padding, or <= 16 sampled textures per stage.

## 5. Uniformity analysis

`textureSample`, `textureSampleBias`, `textureSampleCompare`, `dpdx`/`dpdy`/`fwidth`,
`workgroupBarrier` and `storageBarrier` must run in uniform control flow. Errors read like
"'textureSample' must only be called from uniform control flow". Fixes, in order of preference:

```wgsl
// 1. hoist: sample first, branch on the result
let c = textureSample(t, s, in.uv);
if (in.alpha > 0.5) { color = c; }
// 2. explicit LOD or gradients computed in uniform flow
let ddx = dpdx(in.uv); let ddy = dpdy(in.uv);
if (in.alpha > 0.5) { color = textureSampleGrad(t, s, in.uv, ddx, ddy); }   // or textureSampleLevel(t, s, uv, 0.0)
// 3. a workgroup-shared value made uniform (also acts as a barrier)
let n = workgroupUniformLoad(&shared_count);
for (var i = 0u; i < n; i++) { /* ... */ workgroupBarrier(); }
```

Last resort, with a comment: `diagnostic(off, derivative_uniformity);` (derivatives only).

## 6. Compute

- Workgroup size 64 (1D) or 8x8 / 16x16 (2D); `@workgroup_size` x*y*z <= 256 by default;
  dispatch `ceil(n / size)` groups with a bounds check; <= 65535 per dimension.
- Storage buffers for structured data; storage textures only in formats listed for storage
  (`rgba8unorm`, `rgba16float`, `r32float`, `rgba32float`, ...; `bgra8unorm` needs
  `bgra8unorm-storage`; no `-srgb` storage: write linear to an `rgba8unorm` view and encode in
  the shader, or copy to an sRGB texture). `read_write` storage textures are limited (r32 formats).
- Atomics: `atomic<u32>`/`atomic<i32>` in storage or workgroup space; no float atomics in core
  (CAS loop with `atomicCompareExchangeWeak` on bitcast values).
- Subgroups: feature `subgroups` + `enable subgroups;`, builtins `subgroup_invocation_id`,
  `subgroup_size`, `subgroupAdd`, `subgroupExclusiveAdd`, `subgroupBallot`. Size varies by
  device (4-128): never hard-code 32.
- Indirect: `pass.dispatchWorkgroupsIndirect(buf, offset)`; buffer usage `INDIRECT | STORAGE`.
- Readback with frame latency (ring of 2-3 staging buffers; never `await` in the frame loop):

```js
const staging = device.createBuffer({ size, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
enc.copyBufferToBuffer(result, 0, staging, 0, size);
device.queue.submit([enc.finish()]);
staging.mapAsync(GPUMapMode.READ).then(() => {
  const out = new Float32Array(staging.getMappedRange().slice(0)); staging.unmap(); consume(out); });
```

## 7. Canvas and color

```js
const ctx = canvas.getContext('webgpu');
const format = navigator.gpu.getPreferredCanvasFormat();      // usually 'bgra8unorm'
ctx.configure({ device, format, viewFormats: [`${format}-srgb`], alphaMode: 'premultiplied' });
const view = ctx.getCurrentTexture().createView({ format: `${format}-srgb` }); // hardware encode
// HDR / wide gamut, where supported:
ctx.configure({ device, format: 'rgba16float', colorSpace: 'display-p3',
                toneMapping: { mode: 'extended' }, alphaMode: 'opaque' });
// gate on matchMedia('(dynamic-range: high)').matches; values > 1.0 use display headroom
```

`alphaMode: 'premultiplied'` requires premultiplied output, otherwise edges glow over the page.

## 8. Errors and profiling

```js
device.pushErrorScope('validation');
const pipeline = device.createRenderPipeline(desc);
const err = await device.popErrorScope();          // scopes form a stack: pop in reverse order
if (err) throw new Error(`pipeline ${desc.label}: ${err.message}`);

const mod = device.createShaderModule({ label: 'blur.wgsl', code });
for (const m of (await mod.getCompilationInfo()).messages)  // fail tests on 'error'
  console[m.type === 'error' ? 'error' : 'warn'](`blur.wgsl:${m.lineNum}:${m.linePos} ${m.message}`);

const qs = device.createQuerySet({ type: 'timestamp', count: 2 });   // needs 'timestamp-query'
const pass = enc.beginComputePass({ label: 'blur.h',
  timestampWrites: { querySet: qs, beginningOfPassWriteIndex: 0, endOfPassWriteIndex: 1 } });
// ... pass.end(); enc.resolveQuerySet(qs, 0, 2, resolveBuf, 0);  -> BigInt64Array, nanoseconds
```

Timestamps are quantized for privacy (Chrome: coarse unless "WebGPU Developer Features" is
enabled in `chrome://flags`); use medians over many frames. Prefer `createRenderPipelineAsync`
/ `createComputePipelineAsync`. Tools: `chrome://gpu`, Safari Web Inspector, RenderDoc or PIX
on a native Dawn/wgpu build, `pushDebugGroup` labels on encoders.

## 9. Tooling and porting

```bash
cargo install naga-cli
naga blur.wgsl                    # validate (non-zero exit on error)
naga blur.wgsl blur.spv           # also .metal, .hlsl; GLSL output needs an entry point/profile (naga --help)
naga blur.comp blur.wgsl          # GLSL input: stage taken from the extension (.vert/.frag/.comp)
```

Tint is Dawn's compiler (validation in Chrome); wgsl-analyzer is the editor LSP.

| GLSL | WGSL |
|---|---|
| implicit int -> float | explicit `f32(i)`; no implicit conversions |
| `sampler2D` | `texture_2d<f32>` + `sampler`; `textureSample(t, s, uv)` |
| `texelFetch(t, p, 0)` / `imageStore` | `textureLoad(t, p, 0)` / `textureStore` |
| `shared float a[N]` / `barrier()` | `var<workgroup> a: array<f32, N>` / `workgroupBarrier()` |
| `c ? a : b` | `select(b, a, c)` (false value first) |
| `mod(x, y)` (floor) | `x - y * floor(x / y)`; WGSL `%` truncates |
| `dFdx` | `dpdx` |
| framebuffer origin bottom-left, NDC z [-1,1] | origin top-left, NDC y up, z [0,1] |

## 10. Pitfalls

- `writeBuffer` size or offset not a multiple of 4: validation error.
- One texture as render attachment and as a binding in the same pass: usage conflict; use a copy.
- `depth32float` is not filterable: `textureLoad`, or a comparison sampler with `texture_depth_2d`.
- `copyTextureToBuffer`: `bytesPerRow` must be a multiple of 256; pad rows and strip on read.
- Synchronous pipeline creation in the frame loop: stalls of 10-100+ ms; create async up front.
- vec3 in a uniform struct packed tightly on the host: every later field shifts by 4 bytes.

## 11. Worked example: GLSL separable Gaussian blur to WGSL

Source GLSL: `layout(local_size_x = 128)`, `uniform Params { int radius; float weights[17]; }`,
`rgba8` image load/store. Port issues: (1) `array<f32, 17>` in a uniform is invalid (stride 4),
so weights become `array<vec4<f32>, 5>`; the host had packed 17 tight floats, which std140 also
broke; (2) image loads become `textureLoad`; (3) add a shared tile with apron.

```wgsl
const R_MAX: u32 = 16u;
const WG: u32 = 128u;
struct Params { radius: u32, horizontal: u32, _p0: u32, _p1: u32, weights: array<vec4<f32>, 5> }; // 96 B
@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var src: texture_2d<f32>;
@group(0) @binding(2) var dst: texture_storage_2d<rgba8unorm, write>;  // rgba32float in the test build
var<workgroup> tile: array<vec4<f32>, 160>;                           // WG + 2 * R_MAX

fn wgt(i: u32) -> f32 { return P.weights[i / 4u][i % 4u]; }

@compute @workgroup_size(128)
fn main(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_index) li: u32) {
  let size = vec2<i32>(textureDimensions(src));
  let h = P.horizontal != 0u;
  let len = select(size.y, size.x, h);          // texels along the blurred axis
  let line = i32(wg.y);                         // row (h) or column (v)
  let base = i32(wg.x * WG) - i32(R_MAX);
  for (var j = 0u; j < 2u; j++) {               // 160 texels with 128 threads: 2 rounds
    let k = li + j * WG;
    if (k < WG + 2u * R_MAX) {
      let t = clamp(base + i32(k), 0, len - 1); // clamp-to-edge
      tile[k] = textureLoad(src, select(vec2<i32>(line, t), vec2<i32>(t, line), h), 0);
    }
  }
  workgroupBarrier();                           // uniform: no early return before it
  let x = i32(wg.x * WG + li);
  if (x >= len) { return; }
  var acc = tile[li + R_MAX] * wgt(0u);
  for (var i = 1u; i <= P.radius; i++) {
    acc += (tile[li + R_MAX - i] + tile[li + R_MAX + i]) * wgt(i);
  }
  textureStore(dst, select(vec2<i32>(line, x), vec2<i32>(x, line), h), acc);
}
```

Host: `radius = 8` (assert `<= R_MAX`), `sigma = radius / 3`, `w_i = exp(-i^2 / (2 sigma^2))`
normalized so `w_0 + 2 * sum(w_1..w_r) = 1`, written into 5 vec4 slots (20 floats, last 3 zero).
Dispatch: horizontal `dispatchWorkgroups(ceil(W / 128), H)`, vertical
`dispatchWorkgroups(ceil(H / 128), W)` with `horizontal = 0`, through an intermediate texture.

Validation and test:
1. `naga blur.wgsl` exits 0 (CI step); `getCompilationInfo()` has no errors in the browser.
2. Headless test (Deno exposes `navigator.gpu`; older Deno needs `--unstable-webgpu`; or Node
   with the Dawn-based `webgpu` package): 256x256 random rgba32float input, test build with
   `rgba32float` storage, both passes, read back with `bytesPerRow = 256 * 16` (multiple of 256).
3. CPU reference: the same weights and clamp-to-edge, two separable passes in float64.
4. Assert `max |gpu - cpu| <= 1e-3` over all channels (float32 sums typically land near 1e-6);
   add sizes 1x1, 129x7 and 300x300 to hit partial workgroups.

Related: `gpu-compute-patterns`, `gpu-debugging-profiling`, `raster-pipeline-architecture`, `vulkan-setup-synchronization`, `metal-apple-gpu`, `color-pipeline-tonemapping`, `rust-craft`, hub `computer-graphics`
