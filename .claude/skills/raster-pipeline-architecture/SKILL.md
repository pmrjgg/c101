---
name: raster-pipeline-architecture
description: "Real-time raster renderer architecture: forward, forward+/tiled and clustered light culling, deferred G-buffer layouts, visibility buffer, depth prepass, reversed-Z infinite projection, render graphs with transient aliasing, GPU-driven meshlet culling, and transparency. Load when designing, extending or debugging a raster frame."
when_to_use: "Choosing forward vs clustered vs deferred vs visibility buffer; hundreds of dynamic lights; G-buffer formats or bandwidth budgets; z-fighting or depth-precision bugs; render-graph, barrier or transient-aliasing design; meshlet, HiZ occlusion or indirect-draw culling; order-independent transparency; mobile TBDR load/store and on-tile G-buffer planning."
---

# Raster pipeline architecture

Rule zero: pick an architecture from measured per-pass GPU timestamps and bytes per pixel on the
target GPU class, never from a blog benchmark. Conventions here: right-handed view space looking
down -Z, `z` = positive view distance, reversed-Z depth in [0,1] unless stated.

## 1. Architecture decision

| Criterion | Forward | Forward+ (tiled) / clustered | Deferred | Visibility buffer |
|---|---|---|---|---|
| Lights per pixel | < 8 total | 100s-10k, culled | 100s-10k, culled | 100s-10k, culled |
| Material count | any | any (one shader per material) | one uber G-buffer model | many, binned per tile |
| MSAA | native | native | expensive (per-sample lighting) | possible, costly resolve |
| Transparency | same path | shares light lists | separate forward pass | separate forward pass |
| Bandwidth (B/px, opaque) | 8-12 | 12-16 | 20-28 + HDR | 8 + material fetch |
| Desktop IMR | small scenes, VR | default choice | uniform materials, heavy post | dense meshlets, Nanite-like |
| Mobile TBDR | default | good | only with on-tile G-buffer | rarely worth it |

Procedure: (1) list the hard constraints (MSAA, VR, transparency share, target GPUs); (2) estimate
bytes per pixel and light evaluations per pixel (sections 3-4); (3) prototype the two survivors
behind a render graph so they share passes; (4) measure (section 11) and choose.

## 2. Reversed-Z with an infinite far plane

Map near to 1 and infinity to 0: `d = n / z`. Projection (column vectors, Vulkan [0,1] depth):

```cpp
// f = 1 / tan(fovY / 2); a = width / height; n = near plane (> 0)
glm::mat4 reversedInfinite(float fovY, float a, float n) {
    float f = 1.0f / std::tan(fovY * 0.5f);
    glm::mat4 P(0.0f);              // glm is column-major: P[col][row]
    P[0][0] = f / a;
    P[1][1] = f;                    // Vulkan: use -f, or a negative-height viewport
    P[2][3] = -1.0f;                // w_clip = -z_view
    P[3][2] = n;                    // z_clip = n  ->  z_ndc = n / z
    return P;
}
// depth: VK_FORMAT_D32_SFLOAT, compareOp GREATER (or GREATER_OR_EQUAL), clear depth to 0.0
// linear distance from a depth sample: z = n / d
```

Precision of a depth step at distance z (n = 0.1 m):

| Setup | Step at 10 m | Step at 100 m | Step at 1 km |
|---|---|---|---|
| Standard Z, D24 (`dz = z^2 * 2^-24 / n`) | 0.06 mm | 6 mm | 0.6 m |
| Standard Z, D32F (values crowd near 1.0: no gain) | ~0.06 mm | ~6 mm | ~0.6 m |
| Reversed-Z, D32F (`dz ~ z * 2^-23`, relative) | 1.2 µm | 12 µm | 0.12 mm |

Clip-space conventions: Vulkan NDC y points down, depth [0,1]; D3D and Metal y up, [0,1]; OpenGL
y up, [-1,1] unless `glClipControl(GL_LOWER_LEFT, GL_ZERO_TO_ONE)` (GL 4.5); WebGPU y up, [0,1].
Reversed-Z on GL needs that clip control, otherwise the [-1,1] remap destroys the gain.

## 3. Tiled and clustered light culling

Tiled (forward+): 16x16 px tiles; a compute pass reduces each tile's depth to min/max
(reversed-Z: min value = farthest), builds 4 side planes from tile corners plus the depth bounds,
and tests each light sphere. Discontinuous tiles (foreground over sky) waste work; clusters fix it.

Clustered: 16 x 9 x 24 = 3,456 clusters with exponential depth slices:

```
slice(z) = floor( log(z) * S / log(f/n) - S * log(n) / log(f/n) )      S = 24
z_k     = n * (f/n)^(k/S)        // slice k spans [z_k, z_k+1]; n=0.1, f=1000 -> x1.468 per slice
```

Use a culling far plane `f` (e.g. 1000 m) even with an infinite projection; clamp z to [n, f].

```glsl
// one invocation per cluster; aabbMin/aabbMax precomputed in view space
bool sphereAabb(vec3 c, float r, vec3 bmin, vec3 bmax) {
    vec3 d = max(vec3(0.0), max(bmin - c, c - bmax));
    return dot(d, d) <= r * r;
}
// spot cone (apex, unit dir, range, half-angle) vs the cluster's bounding sphere (s, rs)
bool coneSphere(vec3 apex, vec3 dir, float range, float ang, vec3 s, float rs) {
    vec3 v = s - apex; float vlen2 = dot(v, v); float v1 = dot(v, dir);
    float dist = cos(ang) * sqrt(max(vlen2 - v1 * v1, 0.0)) - v1 * sin(ang);
    return !(dist > rs || v1 > rs + range || v1 < -rs);
}
layout(local_size_x = 64) in;
void main() {
    uint cid = gl_GlobalInvocationID.x; if (cid >= clusterCount) return;
    uint local[MAX_PER_CLUSTER]; uint cnt = 0;               // MAX_PER_CLUSTER = 128
    for (uint i = 0; i < lightCount && cnt < MAX_PER_CLUSTER; ++i)
        if (sphereAabb(lights[i].posView, lights[i].radius, aabbMin[cid], aabbMax[cid]))
            local[cnt++] = i;
    uint off = atomicAdd(globalIndexCount, cnt);              // compute-built index list
    clusterGrid[cid] = uvec2(off, cnt);
    for (uint j = 0; j < cnt; ++j) lightIndices[off + j] = local[j];
    if (cnt == MAX_PER_CLUSTER) atomicAdd(overflowCounter, 1); // assert 0 in debug builds
}
```

For > ~2k lights, cull lights in shared-memory batches of 64 per workgroup, or build a
light BVH/z-binned list (lights sorted by z, per-slice min/max index, per-tile bitmasks).
Fragment lookup: `cluster = (x / tileW) + (y / tileH) * 16 + slice(z) * 16 * 9`.
Heatmap debug view: `color = turbo(clamp(count / 64.0, 0, 1))`; budget: green < 8, yellow
8-32, red > 32 lights per pixel; check the heatmap whenever light radii change.

## 4. G-buffer layout in bytes

| Target | Format | B/px | Content |
|---|---|---|---|
| GB0 | RGBA8_SRGB | 4 | base color rgb, specular occlusion |
| GB1 | RG16_UNORM octahedral (or RGB10A2: 10:10 oct + 2-bit flags) | 4 | world normal |
| GB2 | RGBA8_UNORM | 4 | roughness, metalness, AO, material id |
| GB3 | RG16F | 4 | screen-space motion vector |
| Depth | D32_SFLOAT | 4 | reversed-Z |
| Lit HDR (not G-buffer) | R11G11B10F / RGBA16F | 4 / 8 | lighting result |

Total 20 B/px. Per frame, write once, read once, write HDR RGBA16F:
1080p (2,073,600 px): 41.5 MB G-buffer, ~100 MB traffic, 6.0 GB/s at 60 Hz.
4K (8,294,400 px): 165.9 MB G-buffer, ~398 MB traffic, 23.9 GB/s at 60 Hz (x overdraw in the
G-buffer pass without a prepass; x4 storage with 4x MSAA).

```glsl
vec2 octWrap(vec2 v) { return (1.0 - abs(v.yx)) * vec2(v.x >= 0.0 ? 1.0 : -1.0, v.y >= 0.0 ? 1.0 : -1.0); }
vec2 encodeOct(vec3 n) {                       // n must be unit length
    n /= abs(n.x) + abs(n.y) + abs(n.z);
    vec2 e = n.z >= 0.0 ? n.xy : octWrap(n.xy);
    return e * 0.5 + 0.5;                      // UNORM storage
}
vec3 decodeOct(vec2 e) {
    e = e * 2.0 - 1.0;
    vec3 n = vec3(e, 1.0 - abs(e.x) - abs(e.y));
    float t = clamp(-n.z, 0.0, 1.0);
    n.xy += vec2(n.x >= 0.0 ? -t : t, n.y >= 0.0 ? -t : t);
    return normalize(n);                       // always renormalize after decode
}
```

2x8-bit octahedral bands visibly on smooth speculars; use 2x10 or 2x16 bits.

## 5. Visibility buffer

Pass 1 writes one R32_UINT per pixel: `(clusterOrInstance << 7) | triangleInMeshlet` (meshlets
of <= 128 triangles leave 25 bits for 33M meshlet instances); clear to 0xFFFFFFFF; depth as usual.
Software rasterization packs `depth << 32 | id` into 64-bit atomics instead.
Pass 2 (classify): per 8x8 tile, a compute pass collects the material ids present and appends
the tile to each material's tile list (atomics), then writes indirect dispatch arguments.
Pass 3 (resolve): per material, one dispatch over its tiles: fetch the 3 vertices of the
triangle, transform, compute perspective-correct barycentrics and their screen derivatives:

```hlsl
float3 PerspBary(float4 c0, float4 c1, float4 c2, float2 p)     // p and the s_i in NDC
{
    float2 s0 = c0.xy / c0.w, s1 = c1.xy / c1.w, s2 = c2.xy / c2.w;
    float2 e1 = s1 - s0, e2 = s2 - s0, d = p - s0;
    float det = e1.x * e2.y - e2.x * e1.y;
    float b1 = (d.x * e2.y - e2.x * d.y) / det;
    float b2 = (e1.x * d.y - d.x * e1.y) / det;
    float3 b = float3(1 - b1 - b2, b1, b2) / float3(c0.w, c1.w, c2.w);
    return b / (b.x + b.y + b.z);
}
// derivatives = finite differences one pixel apart (exact for the hardware's quad convention)
float3 l   = PerspBary(c0, c1, c2, ndc);
float3 ldx = PerspBary(c0, c1, c2, ndc + float2(2.0 / W, 0)) - l;
float3 ldy = PerspBary(c0, c1, c2, ndc + float2(0, 2.0 / H * ySign)) - l; // ySign: +1 Vulkan, -1 D3D/Metal
float2 uv    = l.x * uv0 + l.y * uv1 + l.z * uv2;
float2 duvdx = ldx.x * uv0 + ldx.y * uv1 + ldx.z * uv2;
float2 duvdy = ldy.x * uv0 + ldy.y * uv1 + ldy.z * uv2;
float4 albedo = tex.SampleGrad(samp, uv, duvdx, duvdy);         // never implicit-LOD Sample here
```

It beats deferred when triangles approach pixel size (2x2 quad overshading can shade 4x the
pixels), materials number in the dozens or more, or bandwidth is tight (8 B/px vs 20+). It
loses with few large triangles and few materials (the re-transform per pixel costs ALU).

## 6. Render graph

```cpp
auto& gb = graph.addPass("gbuffer", Queue::Graphics, [&](PassBuilder& b) {
    albedo = b.create("albedo", {W, H, VK_FORMAT_R8G8B8A8_SRGB}, Usage::ColorWrite);
    depth  = b.write(depth, Usage::DepthWrite);
}, [=](Cmd& cmd, const Res& r) { drawOpaque(cmd); });
graph.addPass("lighting", Queue::Graphics, [&](PassBuilder& b) {
    b.read(albedo, Usage::SampledFragment); b.read(depth, Usage::SampledFragment);
    hdr = b.write(hdr, Usage::ColorWrite);
}, [=](Cmd& cmd, const Res& r) { fullscreen(cmd); });
graph.markOutput(hdr);
```

Compile steps: (1) every write creates a new resource version, giving a DAG; (2) cull: reference
counting from outputs, drop passes nobody reads; (3) order topologically, keeping submission
order for side effects; (4) lifetimes = [first, last] pass index per transient; (5) alias:
sort transients by size, place greedily into heaps where lifetimes do not overlap; an aliased
resource starts in UNDEFINED with a discard or clear as its first use; (6) barriers: track the last
(stage, access, layout, queue) per subresource and emit one batched sync2 barrier per pass;
(7) async compute: move independent compute (light culling, SSAO, HiZ) to the compute queue
beside fixed-function-bound graphics work (shadow maps, prepass) with timeline-semaphore edges.
Expect 30-50% transient memory savings from aliasing in a typical post chain.

## 7. GPU-driven rendering

```cpp
const size_t maxV = 64, maxT = 124; const float coneWeight = 0.25f;
size_t maxM = meshopt_buildMeshletsBound(idx.size(), maxV, maxT);
std::vector<meshopt_Meshlet> ml(maxM);
std::vector<unsigned int> mlVerts(maxM * maxV);
std::vector<unsigned char> mlTris(maxM * maxT * 3);
size_t count = meshopt_buildMeshlets(ml.data(), mlVerts.data(), mlTris.data(), idx.data(),
    idx.size(), &pos[0].x, pos.size(), sizeof(float3), maxV, maxT, coneWeight);
ml.resize(count);
for (auto& m : ml) {
    meshopt_Bounds b = meshopt_computeMeshletBounds(&mlVerts[m.vertex_offset],
        &mlTris[m.triangle_offset], m.triangle_count, &pos[0].x, pos.size(), sizeof(float3));
    // store b.center, b.radius, b.cone_axis, b.cone_cutoff per meshlet
}
```

Per meshlet in a task/compute shader, cheapest test first: (1) frustum vs sphere; (2) normal
cone: cull if `dot(center - camPos, coneAxis) >= coneCutoff * length(center - camPos) + radius`;
(3) HiZ occlusion. Two-phase: phase 1 draws what was visible last frame and builds the HiZ
pyramid from its depth; phase 2 tests everything else against it, draws the newly visible and
updates the visibility bits. HiZ test: project the sphere to a screen rect, mip =
`ceil(log2(max(wPx, hPx)))`, take the farthest of 4 texels; reversed-Z: cull when the sphere's
nearest depth `n / (z - r)` < HiZ min (with `z - r <= n`, never cull).
Submit with `vkCmdDrawIndexedIndirectCount` (count written on the GPU) or
`vkCmdDrawMeshTasksIndirectEXT`; materials are indices into bindless texture arrays.
LOD: projected error `e_px = e_world * H / (2 * tan(fovY/2) * z)`; pick the coarsest LOD with
`e_px <= 1` (0.5 for hero assets); use hierarchical (cluster DAG) LOD to avoid cracks.

## 8. Transparency

Sorted forward after opaque: sort back-to-front per object (or per meshlet), reuse cluster light
lists, test against opaque depth with writes off. Weighted blended OIT (McGuire-Bavoil 2013):

```glsl
layout(location = 0) out vec4 accum;   // RGBA16F, blend ONE, ONE; clear 0
layout(location = 1) out float reveal; // R8/R16F, blend ZERO, ONE_MINUS_SRC_COLOR; clear 1
void main() {
    vec4 c = shadePremultiplied();      // c.rgb already multiplied by c.a
    float z = viewDistance;
    float w = c.a * clamp(10.0 / (1e-5 + pow(z / 5.0, 2.0) + pow(z / 200.0, 6.0)), 1e-2, 3e3);
    accum = c * w; reveal = c.a;
}
// composite (blend SRC_ALPHA, ONE_MINUS_SRC_ALPHA over opaque):
// out = vec4(accum.rgb / max(accum.a, 1e-5), 1.0 - reveal)
```

Paper weights (z = view distance, all clamped to [1e-2, 3e3]): `10/(1e-5+(z/5)^2+(z/200)^6)`,
`10/(1e-5+(z/10)^3+(z/200)^6)`, `0.03/(1e-5+(z/200)^4)`, or `3e3*(1-d)^3` from the depth
buffer (reversed-Z: use `d^3`). Tune the scale to scene units; it fails for high-alpha layers.
Per-pixel linked lists: 4 B/px heads + 16 B nodes; 1440p x 4 layers = 236 MB pool, overflow
drops fragments, resolve sorts K <= 16 nodes per pixel. Use only for exact order of few layers.
Premultiplied alpha everywhere: blend ONE, ONE_MINUS_SRC_ALPHA; generate mips on premultiplied
texels (avoids dark fringes); additive = premultiplied with alpha 0.
Particles: render at half resolution against depth downsampled to the closest value, then
bilateral upsample: `w_i = bilinear_i / (1e-3 + |z_full - z_i|)`; at edges where all four
differ by > 10% of z, take the nearest-depth sample.

## 9. Depth prepass and mobile TBDR

Prepass only when: measured overdraw > ~1.5x with expensive fragments; later passes need depth
first (HiZ, SSAO, tiled min/max); or alpha-tested foliage (prepass with discard, main pass with
EQUAL and no discard keeps early-Z). Skip it when GPU culling plus front-to-back order already
gives ~1.2x overdraw, when vertex cost dominates, or on Apple GPUs (HSR) unless needed.
TBDR (Apple, Mali, Adreno, PowerVR): loadOp CLEAR or DONT_CARE (never LOAD a cleared target),
storeOp DONT_CARE for depth and G-buffer, transient attachments
(`VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT` + `LAZILY_ALLOCATED` memory, Metal `memoryless`).
Read the G-buffer on-tile via subpass input attachments or `VK_KHR_dynamic_rendering_local_read`
(core in Vulkan 1.4); keep bits per pixel within the vendor's tile budget (exceeding it shrinks
tiles; check the vendor guide). Saved: 2 x 20 B/px of DRAM traffic per frame.

## 10. Pitfalls

- Standard Z with D24 and a near plane of 0.01: z-fighting beyond 100 m; use section 2.
- Light culling written for standard Z running on reversed-Z (min/max swapped): clusters cull
  every light near the camera. Convert with `z = n / d` in one shared function.
- G-buffer normals not renormalized after decode or after blending decals: speculars sparkle.
- Implicit-derivative sampling in the visibility-buffer resolve (compute has no quads): wrong
  mips and seams; always `SampleGrad`/`textureGrad` with analytic gradients.
- MSAA bolted onto deferred: per-sample lighting everywhere; detect edge pixels or go forward+.
- Skinned, morphing or vertex-animated meshes without previous-frame positions: zero motion
  vectors, TAA ghosting. Particles and UV-scrolled materials need reactive masks.
- Cluster overflow counter ignored: lights silently pop; assert it is 0 in debug builds.

## 11. Worked example: 1,000 point lights at 1440p

Setup: 2560x1440 = 3,686,400 px; 1,000 point lights (radius 2-6 m); 600-frame camera path; vsync
off; 100 warm-up frames; median of the rest; clocks locked; one stated GPU (name, driver, clocks
in the report). Three paths behind one render graph: forward (no culling), clustered forward+
(prepass + 16x9x24 clusters), deferred (20 B/px G-buffer + clustered lighting compute).

Timestamps around every pass (Vulkan 1.3):

```cpp
vkCmdResetQueryPool(cmd, pool, frame * kQ, kQ);
vkCmdWriteTimestamp2(cmd, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, pool, frame * kQ + 2 * pass);
recordPass(cmd, pass);
vkCmdWriteTimestamp2(cmd, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, pool, frame * kQ + 2 * pass + 1);
// N frames later (no stall): vkGetQueryPoolResults(..., VK_QUERY_RESULT_64_BIT)
double ms = double(t[1] - t[0]) * limits.timestampPeriod * 1e-6;   // timestampPeriod = ns/tick
```

Analytic budget before measuring:
- Forward: 3.69M px x 1,000 lights x 1.3 overdraw = 4.8 G light evaluations per frame.
- Clustered: 3,456 clusters x 1,000 lights = 3.46M sphere-AABB tests (one small dispatch);
  heatmap average 24 lights/px -> 3.69M x 24 = 88M evaluations (54x fewer).
- Deferred traffic: G-buffer 20 B/px x 3.69M = 73.7 MB written + 73.7 MB read + 29.5 MB
  RGBA16F = 177 MB/frame = 0.35 ms at 504 GB/s, but 3.5 ms at 51 GB/s on a phone-class GPU.

Record (layout of the deliverable; the timings below are illustrative placeholders showing the
expected shape, not a measurement; replace them with your captured medians):

| Path | Prepass | Cull | Opaque/G-buffer | Lighting | Total ms | DRAM B/px | Heatmap max |
|---|---|---|---|---|---|---|---|
| Forward | - | - | 21.8 | - | 21.8 | 12 | 1000 (no cull) |
| Clustered forward+ | 0.35 | 0.08 | 2.9 | - | 3.3 | 16 | 61 |
| Deferred + clustered | - | 0.08 | 1.4 | 1.6 | 3.1 | 48 | 61 |

Decision rule: a path wins only if its median total is > 10% faster across 3 runs; otherwise
take clustered forward+ (MSAA, transparency shares the light lists, 3x less traffic, which
matters on TBDR). Attach the heatmap captures and the overflow counter (must be 0).

Related: `vulkan-setup-synchronization`, `gpu-debugging-profiling`, `gpu-compute-patterns`, `realtime-shadows`, `realtime-global-illumination`, `denoising-taa-upscaling`, `metal-apple-gpu`, `webgpu-wgsl`, `mesh-processing`, hub `computer-graphics`
