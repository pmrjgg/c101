---
name: realtime-shadows
description: "Real-time shadows: cascaded shadow maps (split schemes, stabilization, bias), PCF/PCSS soft shadows, VSM/EVSM/MSM filtering, point/spot shadow atlases, virtual shadow maps, contact shadows, and ray-traced shadows with denoising. Load when fixing shadow acne, peter-panning, shimmering or light leaks, or when shadows cost too much."
when_to_use: "Shadow acne or moire on lit surfaces, peter-panning, shadow edges that shimmer or swim while the camera moves, light leaking under walls, blocky or uniformly hard shadows, choosing PCF vs PCSS vs VSM/EVSM/MSM, cascade split or texel-snapping code, depth-bias settings (vkCmdSetDepthBias, D3D12 rasterizer state), point-light cube maps and shadow atlases, virtual shadow map page budgets, ray-traced or screen-space contact shadows, or a shadow pass that dominates GPU time."
---

# Real-time shadows

Rule zero: never tune bias blind. Capture a frame (RenderDoc, PIX, Nsight), turn on the cascade
overlay and the texel-density view (section 10), change one parameter at a time, and replay the
same camera-strafe sequence after every change. Hub: `computer-graphics` section 5.
Deep material: [VSM/EVSM/MSM code, virtual shadow map internals, RT shadow code](references/prefiltered-virtual-rt.md)

## 1. Technique decision table

| Light / situation | Default | Upgrade when | Watch |
|---|---|---|---|
| Spot | one perspective map in an atlas, 256-2048 px | PCSS for large emitters | push the near plane out; D32F |
| Directional, outdoor | CSM: 3-4 cascades, 2048^2, 150-300 m | > 4 cascades or dense geometry: virtual shadow maps | shimmering; beyond range use baked, SDF or heightfield shadows |
| Point | cube map (6 faces) with per-face culling, in an atlas | tetrahedral (4 faces) to cut passes | face seams; cache static casters |
| Huge worlds, dense geometry, many shadowed lights | virtual shadow maps: 16k^2 virtual, 128^2 pages | | needs GPU-driven culling; cost = dirty pages |
| Area lights, contact hardening, hardware RT | 1 ray/pixel/light + denoiser | | noise, alpha-tested foliage cost |
| Small-scale contact (feet, fingers, grass) | screen-space contact shadows as an add-on | | on-screen occluders only; never alone |

Budget target: all shadow work <= 15-20% of the frame. Over budget, cache static casters
(section 6) before dropping resolution.

## 2. Cascaded shadow maps

**Splits** (practical split scheme, Zhang 2006), near n, shadow distance f, N cascades:

    C_i = lambda * n * (f/n)^(i/N) + (1 - lambda) * (n + (f - n) * i/N),   i = 0..N

lambda 0.5-0.9 (higher = more texels near the camera), N = 3-4. n = 0.1 wastes most of the log
term on the first metre; use n_split = 0.5-2 m when the camera never gets that close.

**Fit**: enclose each slice [C_i, C_i+1] in a bounding sphere (rotation-invariant: the light-space
extent never changes when the camera turns), then snap the light-space origin to whole texels
(translation-invariant). Both are required; either alone still shimmers.

```cpp
// k2 = tan(fovX/2)^2 + tan(fovY/2)^2 (symmetric frustum); the centre lies on the view axis.
Sphere SliceSphere(float ni, float fi, float k2, float3 camPos, float3 camFwd) {
  float zc = 0.5f * (fi + ni) * (1.0f + k2), r;
  if (zc >= fi) { zc = fi; r = fi * std::sqrt(k2); }          // wide FOV: centre on the far plane
  else          { r = std::sqrt((fi - zc) * (fi - zc) + fi * fi * k2); }
  r = std::ceil(r * 16.0f) / 16.0f;                            // radius must not jitter per frame
  return { camPos + camFwd * zc, r };
}
float4x4 CascadeMatrix(const Sphere& s, float3 lightDir, int size, float casterReach) {
  float3 up = std::abs(lightDir.y) < 0.99f ? float3(0, 1, 0) : float3(1, 0, 0); // never camera up
  float4x4 view = LookAt(s.center - lightDir * (s.r + casterReach), s.center, up);
  float4x4 m = Ortho(-s.r, s.r, -s.r, s.r, 0.0f, 2.0f * s.r + casterReach) * view; // column vectors
  float4 o = m * float4(0, 0, 0, 1);                           // world origin in NDC (w = 1)
  float2 tex = float2(o.x, o.y) * (size * 0.5f);
  float2 off = (round(tex) - tex) * (2.0f / size);
  m[3][0] += off.x; m[3][1] += off.y;                          // shift by the sub-texel remainder
  return m;
}
```

`casterReach` pulls the near plane toward the light so off-screen casters (cliffs, towers behind
the camera) are captured. Alternative, **pancaking**: depth clamp in the shadow pass (Vulkan
`depthClampEnable` with the `depthClamp` feature; D3D12 `DepthClipEnable = FALSE`) clamps casters
in front of the near plane to depth 0 so they still occlude, and the depth range can hug the
sphere. Vertex-shader pancaking (clamping z per vertex) distorts long triangles that cross the
plane; prefer the hardware clamp.

**Blend bands**: blend cascade i into i+1 over the last 10% (5-20%) of its range.

```hlsl
float ShadowCSM(float3 posWS, float3 nWS, float viewZ, uint2 pixel) {  // gSplit[0..N] = C_0..C_N
  uint i = 0;
  [unroll] for (uint c = 1; c < NUM_CASCADES; ++c) i += viewZ > gSplit[c];
  float s = SampleCascade(i, posWS, nWS);
  float band = 0.1 * (gSplit[i + 1] - gSplit[i]);
  float f = saturate((viewZ - (gSplit[i + 1] - band)) / band);
  if (f > 0 && i + 1 < NUM_CASCADES)          // dithered variant: f > IGN(pixel) picks one (TAA)
    s = lerp(s, SampleCascade(i + 1, posWS, nWS), f);
  return s;
}
```

With heavily overlapping spheres, select by containment (|P - centre_i| < r_i - kernel margin)
instead of view depth: it always uses the sharpest cascade that covers the point.

## 3. Bias toolkit

Hardware bias = constant * r + slope * max(|dz/dx|, |dz/dy|), limited by the clamp; r = 2^-16
(D16), 2^-24 (D24), 2^(e-23) for D32F (e = exponent of the primitive's largest depth).

```cpp
// Vulkan: rasterization depthBiasEnable = VK_TRUE + VK_DYNAMIC_STATE_DEPTH_BIAS
vkCmdSetDepthBias(cmd, /*constant*/ 1.25f, /*clamp*/ 0.0f, /*slope*/ 1.75f); // reversed-Z: negate
// D3D12_RASTERIZER_DESC: DepthBias (INT, units of r), DepthBiasClamp, SlopeScaledDepthBias = 1.75f,
// DepthClipEnable = FALSE for pancaked directional cascades.
```

Normal-offset bias, usually the best single fix: move the lookup position along the normal by
1-2 shadow texels in world units, scaled up at grazing angles.

```hlsl
// texelWorld = 2 * r_cascade / size (ortho); spot: 2 * distToLight * tan(fov/2) / size
float3 NormalOffset(float3 posWS, float3 nWS, float3 toLight, float texelWorld) {
  float NoL = saturate(dot(nWS, toLight));
  return posWS + nWS * (1.5 * texelWorld * sqrt(1.0 - NoL * NoL));
}
```

Receiver-plane depth bias for wide kernels: solve dz/du, dz/dv from screen derivatives and
compare every tap against the receiver plane instead of one depth.

```hlsl
float3 sx = ddx(shadowPos), sy = ddy(shadowPos);              // shadowPos = (u, v, depth)
float det = sx.x * sy.y - sx.y * sy.x;
float2 dzduv = float2(sy.y * sx.z - sx.y * sy.z, sx.x * sy.z - sy.x * sx.z) / det;
dzduv = clamp(dzduv, -0.01, 0.01);           // derivatives explode at silhouettes
// tap at uv + o compares against depth + dot(dzduv, o) - small constant
```

| Symptom in the capture | Cause | Fix |
|---|---|---|
| moire or stripes on lit surfaces (acne) | depth quantization + texel footprint on sloped receivers | slope bias, 1-2 texel normal offset |
| acne only at grazing light angles | slope term too small or clamped | raise slope; sin-scaled normal offset |
| acne only inside wide PCF kernels | taps compared with the centre depth | receiver-plane bias |
| shadow detached from the caster (peter-panning) | too much constant/slope bias | cut constant bias, move it into normal offset |
| light leaks at wall-floor joints | normal offset pushes receivers through thin walls | thicker walls, smaller offset, back-face casters |
| edges crawl while the camera moves | unsnapped cascade, radius jitter, camera-derived up vector | section 2 fit and snap |
| edges crawl only while the sun moves | expected | rotate the sun in small steps, rely on TAA |

Rendering back faces only (front-face culling) into the map removes most acne on closed meshes
but leaks on single-sided geometry; keep it per material.

## 4. Filtering: PCF and PCSS

Hardware PCF: a comparison sampler (LINEAR filter, LESS_EQUAL; GREATER_EQUAL with reversed-Z)
returns a bilinearly weighted 2x2 test per fetch: `sm.SampleCmpLevelZero(cmp, uv, depth)`.
Wider kernels rotate a Vogel (golden-angle) disk per pixel with interleaved gradient noise:

```hlsl
float IGN(float2 px) { return frac(52.9829189 * frac(dot(px, float2(0.06711056, 0.00583715)))); }
float2 Vogel(int i, int n, float phi) {
  float r = sqrt((i + 0.5) / n), t = i * 2.39996323 + phi; return r * float2(cos(t), sin(t)); }
float PCFDisk(Texture2DArray<float> sm, float3 uvz, uint c, float radiusUV, float2 px, float2 dzduv) {
  float phi = 6.2831853 * IGN(px + 5.588238 * gFrame);       // per-frame rotation feeds TAA
  float s = 0;
  [unroll] for (int i = 0; i < 16; ++i) {
    float2 o = Vogel(i, 16, phi) * radiusUV;
    s += sm.SampleCmpLevelZero(gCmp, float3(uvz.xy + o, c), uvz.z + dot(dzduv, o));
  }
  return s / 16;
}
```

**PCSS** (contact hardening): (1) blocker search: average depth d_b of texels closer than the
receiver inside a search region; (2) penumbra w = (d_r - d_b) * w_light / d_b; (3) PCF with radius w.
Spot light (linear light-space depths, light size in UV at the near plane): search radius =
w_light * (d_r - near) / d_r, filter radius = w * near / d_r. Directional light (ortho, linear
depth): penumbra width in metres = (d_r - d_b) * 2 tan(theta/2), theta = sun angular diameter
(0.53 deg): 4.6 mm at a 0.5 m caster gap, 18.5 mm at 2 m, 92.5 mm at 10 m.

| Penumbra in texels | Kernel |
|---|---|
| no blocker found | early out, fully lit (most pixels: this is where PCSS saves time) |
| < 1.5 | one hardware 2x2 PCF fetch |
| 1.5-4 | 8-16 disk taps |
| > 4 | 16-32 taps, rotated per frame, TAA resolves; or switch to a pre-filtered map (section 5) |

Use 16 blocker-search taps with the same rotated disk; clamp the search radius so it never
exceeds the cascade's guard band.

## 5. Pre-filterable maps (VSM, EVSM, MSM)

Store moments, blur and mip them once per frame, then sample with trilinear + anisotropic
filtering: one fetch replaces a per-pixel kernel. **VSM** stores (z, z^2):
mu = E[z], sigma^2 = E[z^2] - mu^2, and for t > mu the Chebyshev bound
p_max = sigma^2 / (sigma^2 + (t - mu)^2) (1 when t <= mu). Light-bleeding reduction:
p = saturate((p_max - a) / (1 - a)), a = 0.1-0.4; clamp sigma^2 >= a small minimum.
**EVSM** warps depth first, z+ = exp(c+ z), z- = -exp(-c- z) with z in [-1, 1], stores 4 moments,
returns min of both bounds. Overflow limits: (e^c)^2 must fit the format, so c <= ln(65504)/2 = 5.54
for fp16 and c <= ln(3.4e38)/2 = 44.4 for fp32: use ~40 (fp32) or ~5.5 (fp16).
**MSM** (Peters and Klein 2015, Hamburger 4MSM) stores z..z^4 in 64 bits with an optimized
quantization and a small moment bias; least leaking, costs a 3x3 Cholesky solve per sample.

| Method | Storage/texel | Leaks where | Mitigation |
|---|---|---|---|
| VSM | 2 x fp32 | overlapping occluders at different depths (light bleeding) | bleeding reduction (darkens penumbrae) |
| EVSM4 | 4 x fp32 (fp16 only with c ~5.5) | high depth complexity, much less | larger exponents, small blur |
| MSM 4 | 4 x 16-bit | least; 3+ overlapping layers | moment bias, depth bias |
| ESM | 1 x fp32 | near contact (receiver close to occluder) | over-darkening exponent |

Blur 5-9 tap separable Gaussian in light space; MSAA the shadow map and resolve the moments for a
free pre-filter. Code: [references](references/prefiltered-virtual-rt.md).

## 6. Point and spot lights

- **Per-face culling**: a caster sphere (centre c relative to the light, radius r) touches cube
  face +X iff c.x + sqrt(2) r > |c.y| and c.x + sqrt(2) r > |c.z| (90-degree face planes);
  permute axes and signs for the other faces. Draw each caster once with layered rendering
  (SV_RenderTargetArrayIndex, multiview) into the faces it touches.
- **Atlas allocation**: size = clamp(nextPow2(k * projectedRadiusPx), 64, 2048), k = 1-2, cube
  faces sized alike; quadtree allocator of power-of-two squares; change size class only after it
  differs for ~30 frames (hysteresis) to avoid re-render thrash.
- **Static caching**: render static casters once into a cached map (re-render on light move or
  static-geometry change); each frame copy it and draw only dynamic casters on top.
- **Update budget**: e.g. at most 12 cube faces per frame, priority = screen coverage x frames
  since update x dynamic-caster flag; distant lights update every N frames.

## 7. Virtual shadow maps

A 16384^2 virtual map per clipmap level (directional) or per local light, split into 128^2-texel
pages: 128 x 128 = 16,384 pages, page table 64 KiB per map (4 B entries). Physical pool: 4096
pages x 64 KiB (D32) = 256 MiB. Per frame: (1) **mark** pages from the depth buffer: for each
pixel choose the clipmap level whose texel (level0 * 2^L) is just below the pixel footprint and
set the request bit for its page; (2) **allocate** requested pages missing from the cache (LRU
free list); (3) **render** only dirty pages, culling instances/clusters per page; (4) **sample**
through the page table. **Invalidation**: a moved caster invalidates pages under its old and new
bounds; a moving light invalidates everything; camera motion only adds pages because clipmap
origins snap to page granularity. **Cost model**: marking is a full-screen pass; the rest scales
with dirty pages x geometry per page, so keep dirty pages a small fraction of resident pages and
cap them per frame (coarser fallback when the pool overflows). Details: [references](references/prefiltered-virtual-rt.md).

## 8. Ray-traced shadows

One ray per pixel per light toward a blue-noise point on the area light (spatiotemporal blue
noise, new pattern each frame); flags: accept-first-hit-and-end-search, no closest-hit shading;
offset the origin robustly (Ray Tracing Gems ch. 6 style), not by a fixed epsilon. Alpha-tested
geometry: any-hit alpha test (or the inline RayQuery candidate loop) is the main cost; opacity
micromaps (VK_EXT_opacity_micromap or the DXR equivalent) resolve most texels in hardware.
Denoise: NRD SIGMA (uses hit distance and light angular size to size penumbrae) or SVGF on the
visibility signal. Hybrid: RT up to 50-100 m, CSM beyond, 10% blend band; contact shadows stay
useful for sub-texel detail on the CSM side. Inline code: [references](references/prefiltered-virtual-rt.md).

## 9. Contact shadows

Short screen-space march toward the light catches occlusion below shadow-map resolution.

```hlsl
float ContactShadow(float3 posVS, float3 toLightVS, uint2 px) {   // view space, +z forward
  const int STEPS = 12; const float LEN = 0.25, THICK = 0.05;      // metres
  float3 stepV = toLightVS * (LEN / STEPS);
  float3 p = posVS + stepV * IGN(px);                               // jittered start
  [loop] for (int i = 0; i < STEPS; ++i, p += stepV) {
    float2 uv = ViewToUV(p);
    if (any(uv < 0) || any(uv > 1)) break;
    float dz = p.z - LinearDepth(gDepth.SampleLevel(gPoint, uv, 0));
    if (dz > 0 && dz < THICK) return 0.0;            // behind the depth buffer, within thickness
  }
  return 1.0;
}
```

8-16 steps over 0.1-0.5 m; thickness 2-5x the step length, scaled with distance (~0.01 * z).
Fade out with distance and multiply into the light's shadow term only.

## 10. Pitfalls and debug views

Debug views: **cascade overlay** (tint each cascade, 30% alpha); **texel density**:
tpp = SM_SIZE * max(length(ddx(uv)), length(ddy(uv))) shadow texels per screen pixel, red < 0.5
(blocky), green 0.5-2, blue > 2 (wasted, aliasing); a **bias view** (shadow factor on a lone
tilted plane, which must be 1 everywhere).

- Shimmering from unsnapped cascades, a radius recomputed from a fitted box, or an up vector
  derived from the camera.
- Reversed-Z in the shadow pass: clear to 0, GREATER_EQUAL comparison, negated bias. A flipped
  comparison gives all-shadow or all-lit, not acne.
- D16: one step = range/65536 (7.6 mm over a 500 m ortho range, fine for cascades); perspective D16
  spot maps lose precision quickly with distance: use D32F.
- A shadow frustum that misses off-screen casters (popping when turning): casterReach or pancaking.
- Main and shadow passes disagree: different LOD, skinning, alpha test or vertex animation
  produce self-shadowing that no bias fixes.
- Temporal PCF rotation without TAA reads as noise; turn it off when measuring flicker.
- Shadow-pass culling against the camera frustum instead of the light volume.

## 11. Worked example: outdoor scene with shimmering and acne

Setup: sun, 4 cascades of 2048^2, shadow distance 200 m, camera 60 deg vertical FOV at 16:9
(k2 = 1.3868). lambda = 0.9 gives splits 0.10 / 5.61 / 14.03 / 41.92 / 200 m (lambda 0.5 would
give 25.37 m for the first split: far too coarse near the camera). Computed per cascade:

| Cascade | Range (m) | Sphere radius | Texel | 1.5-texel normal offset | 10% band |
|---|---|---|---|---|---|
| 0 | 0.10-5.61 | 6.61 m | 6.5 mm | 9.7 mm | 0.55 m |
| 1 | 5.61-14.03 | 16.52 m | 16.1 mm | 24.2 mm | 0.84 m |
| 2 | 14.03-41.92 | 49.37 m | 48.2 mm | 72.3 mm | 2.79 m |
| 3 | 41.92-200 | 235.53 m | 230 mm | 345 mm | n/a |

The sun penumbra at a 2 m caster gap (18.5 mm) is 2.9 texels in cascade 0 and 0.4 in cascade 2,
so PCSS only pays in cascades 0-1; use fixed 2x2 PCF beyond.

1. **Measure first.** Pick 4096 world-space points on receivers; each frame a compute pass
   evaluates `ShadowCSM` at those points with that frame's matrices (dither and temporal rotation
   off) and writes (shadow, cascade). Record 240 frames while strafing at 2 m/s with 10 deg/s yaw,
   sun static.

```python
import numpy as np
S = np.load("probe_shadow.npy")     # [frames, points] shadow factor 0..1
C = np.load("probe_cascade.npy")    # [frames, points] cascade index used
d = np.abs(np.diff(S, axis=0)); same = C[1:] == C[:-1]   # ignore cascade switches
toggle = (d > 0.1) & same
print(f"toggle {toggle.sum() / same.sum():.4%}  rms {np.sqrt((d[same]**2).mean()):.4f}  "
      f"worst point {toggle.mean(0).max():.2%}")
```

2. **Snap.** Replace the box fit with `SliceSphere` (radius ceil to 1/16 m) and `CascadeMatrix`
   (fixed up vector, origin snapping). With a static sun the texel grid is now fixed in world
   space, so world-locked values must not change: accept toggle <= 0.05% of point-frames and
   rms <= 0.01. Remaining toggles should sit only on points that enter a blend band.
3. **Bias.** Normal offset 1.5 texels of the point's cascade (9.7 mm in cascade 0, 345 mm in
   cascade 3), slope bias 1.75, constant 1.25 (Vulkan units). Acne check: a lone plane tilted
   0-80 deg to the sun must read shadow = 1 at every pixel in every cascade. Peter-panning check:
   the light gap under a 1 m cube resting on that plane must be <= 1 texel (6.5 mm in cascade 0).
4. **Blend band** of 10% (table): the toggle rate of points inside bands must match the rest;
   if the transition shows, widen to 15-20% or dither.
5. **Report** the before/after toggle, rms and worst-point values, the acne and gap checks, and
   GPU time of the shadow pass (timestamp queries) so the fix is not paid for in another way.

Related: `raster-pipeline-architecture`, `denoising-taa-upscaling`, `realtime-global-illumination`, `gpu-debugging-profiling`, `bvh-build-traversal`, hub `computer-graphics`
