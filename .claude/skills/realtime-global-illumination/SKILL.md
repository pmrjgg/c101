---
name: realtime-global-illumination
description: "Real-time indirect lighting: GTAO/RTAO, screen-space reflections, irradiance and reflection probes with SH and split-sum prefiltering, DDGI probe volumes, surface-cache and radiance-cascade approaches, and ReSTIR GI with radiance caching, plus leak and lag control. Load when choosing, implementing or debugging GI, AO or reflections in a real-time renderer."
when_to_use: "Choosing a GI technique for a platform and millisecond budget; GTAO or RTAO; SSR with Hi-Z tracing and fallbacks; IBL prefiltering, BRDF LUT or box-projected reflection probes; SH L2 irradiance probes; DDGI volumes that leak light through walls, lag behind moving lights or flicker; Lumen-style surface caches or radiance cascades; ReSTIR GI, ReLAX/ReBLUR denoising, SHaRC or NRC radiance caches; interiors too bright, glowing crevices or double-counted ambient."
---

# Real-time global illumination

Rule zero: validate every GI change on three fixed scenes, not screenshots: a sealed room (leaks),
a furnace (energy) and a moving light (lag), each with per-pass GPU timestamps.
Hub: `computer-graphics` sections 1-3. Deep material: [GTAO, Hi-Z SSR, IBL and SH listings](references/gi-shader-listings.md)

## 1. Decision table

| Platform / GI budget | Technique | Dynamic lights / geometry | Main risk |
|---|---|---|---|
| Mobile, VR, Switch-class, < 1 ms | baked lightmaps (directional or SH) + SH light probes + box reflection probes | no / probes only for movers | stale lighting, bake time |
| Raster console/PC without RT, 1-3 ms | GTAO + SSR + baked or relit probes; DDGI traced against SDFs or voxels | partial | leaks, screen-space gaps |
| Hardware RT, mid budget, 2-4 ms | DDGI with RT probe updates + GTAO or RTAO + SSR/RT reflections | yes, with lag | leaks, lag |
| Large dynamic worlds, 4-8 ms | surface cache + screen-space probes + world radiance cache (Lumen-style) | yes | complexity, multi-frame latency |
| 2D or top-down games | radiance cascades | yes | memory at high resolution |
| High-end RT, 6-10 ms | 1-spp RT GI + ReSTIR GI + ReLAX/ReBLUR + radiance cache (SHaRC/NRC) | yes | noise, denoiser lag |
| Legacy | voxel cone tracing (Crassin 2011) | yes | voxel leaks, memory; prefer DDGI today |

AO and SSR are add-ons to every row except full RT; diffuse probes and reflection probes remain
the fallback layer even with RT.

## 2. Ambient occlusion

**GTAO** (Jimenez et al. 2016). Per pixel: 2-4 slice directions phi (rotated per frame, so TAA
sees 16+), 4-8 steps per side up to a world radius R = 0.5-2 m projected to pixels; keep the
largest horizon cosine per side with a distance falloff. With n = signed angle of the normal
projected into the slice (from the view vector) and horizon angles h1 <= 0 <= h2 clamped to
[n - pi/2, n + pi/2]:

    a(h1, h2, n) = 1/4 (-cos(2 h1 - n) + cos n + 2 h1 sin n) + 1/4 (-cos(2 h2 - n) + cos n + 2 h2 sin n)

Visibility = mean over slices of |n_proj| * a (cosine-weighted). The bent normal (mean of the
unoccluded horizon bisectors) feeds probe lookups and specular occlusion. Run at half
resolution (R8), then depth-aware bilateral upsampling: w_i = bilinear_i * max(1e-3,
1 - |z - z_i| / (0.05 z)). Multi-bounce approximation per channel, albedo rho:
a = 2.0404 rho - 0.3324, b = -4.7951 rho + 0.6417, c = 2.7552 rho + 0.6903,
AO' = max(AO, ((AO a + b) AO + c) AO).
**RTAO**: cosine-weighted rays of 0.5-1 m (local occlusion only; GI covers the rest), one ray per
pixel at half resolution, AO = fraction unoccluded, denoised (NRD REBLUR occlusion mode or a
bilateral + temporal filter). **Specular occlusion**: SO = saturate((NoV + AO)^(exp2(-16 r - 1))
- 1 + AO) (Lagarde 2014, r = roughness), or the bent-normal cone versus specular-lobe intersection.
Apply AO only to indirect diffuse and SO only to indirect specular, never to direct lights.

## 3. Screen-space reflections

Pipeline: (1) Hi-Z pyramid of the depth buffer (min depth for standard Z, max for reversed-Z);
(2) per pixel draw H from the GGX visible-normal distribution (Heitz 2018) with blue noise,
L = reflect(-V, H); skip SSR above roughness 0.6-0.7 (probes only); (3) Hi-Z trace, 64-128
iterations, accept a hit only within a thickness of the depth surface (listing in the
references); (4) resolve: reuse the hits of 4-9 neighbours weighted by f(V, L_j)/pdf_j,
divide by the summed weights, multiply by the BRDF LUT term (ratio estimator, Stachowiak 2015);
(5) temporal accumulation reprojecting the reflected hit point (its parallax differs from the
surface's) with neighbourhood clamping; (6) composite through the fallback chain.

```hlsl
float3 SampleGGXVNDF(float3 Ve, float ax, float ay, float2 u) {   // tangent space, z = normal
  float3 Vh = normalize(float3(ax * Ve.x, ay * Ve.y, Ve.z));
  float lensq = Vh.x * Vh.x + Vh.y * Vh.y;
  float3 T1 = lensq > 0 ? float3(-Vh.y, Vh.x, 0) * rsqrt(lensq) : float3(1, 0, 0);
  float3 T2 = cross(Vh, T1);
  float r = sqrt(u.x), phi = 6.2831853 * u.y;
  float t1 = r * cos(phi), t2 = r * sin(phi), s = 0.5 * (1 + Vh.z);
  t2 = (1 - s) * sqrt(1 - t1 * t1) + s * t2;
  float3 Nh = t1 * T1 + t2 * T2 + sqrt(max(0, 1 - t1 * t1 - t2 * t2)) * Vh;
  return normalize(float3(ax * Nh.x, ay * Nh.y, max(0, Nh.z)));    // pdf(L) = G1(V) D(H) / (4 V.z)
}
```

Fallback chain: SSR -> parallax-corrected local probe -> sky probe, blended by a confidence
c = hit * edgeFade * facingFade, never added. edgeFade = saturate(min(uv, 1 - uv) / 0.1)
(both axes); facingFade = 1 - smoothstep(0.25, 0.5, dot(L, V)) (rays back toward the camera
leave the screen); reject hits where dot(N_hit, L) > 0 (back faces).

## 4. Image-based lighting

Split sum (Karis 2013): integral of L_i f cos ~ [prefiltered L(R, roughness)] * [F0 * A + B].
The first factor is the environment convolved with GGX assuming n = v = r, stored in cube mips
(mip m holds perceptual roughness m / (mips - 1)); the second is a 2D LUT over (NoV, roughness)
with A = mean (1 - Fc) Gv, B = mean Fc Gv, Fc = (1 - VoH)^5, Gv = G VoH / (NoH NoV).
Prefilter by importance sampling GGX with pdf-based mip selection (Colbert and Krivanek 2007):
pdf = D/4 (since n = v), solid angle per sample Os = 1 / (N pdf), per texel Op = 4 pi / (6 w^2),
mip = 0.5 log2(Os / Op) + 1. 64-256 samples per texel; mip 0 is a copy.

```hlsl
float3 BoxProject(float3 P, float3 R, float3 bmin, float3 bmax, float3 capturePos) {
  float3 tf = max((bmax - P) / R, (bmin - P) / R);          // per-slab exit distances
  float t = min(min(tf.x, tf.y), tf.z);
  return P + R * t - capturePos;                            // lookup direction from the capture point
}
float3 SpecularIBL(float3 P, float3 N, float3 V, float3 F0, float rough) {   // perceptual roughness
  float3 R = BoxProject(P, reflect(-V, N), gBoxMin, gBoxMax, gCapturePos);
  float3 pre = gProbe.SampleLevel(gLinear, R, rough * (gMipCount - 1)).rgb;
  float2 AB = gBrdfLut.SampleLevel(gClamp, float2(saturate(dot(N, V)), rough), 0).rg;
  return pre * (F0 * AB.x + AB.y);
}
```

Probe blending: influence boxes with a 10-20% blend margin, w_i = saturate(distance inside the
box / margin), at most 2-4 probes per pixel from a clustered list, normalise, and give the sky
probe the remainder 1 - sum(w). Fade box projection toward plain lookups for rough surfaces.

## 5. SH irradiance probes

Real L2 basis (9 coefficients per channel), unit direction (x, y, z): Y00 = 0.282095;
Y1-1 = 0.488603 y, Y10 = 0.488603 z, Y11 = 0.488603 x; Y2-2 = 1.092548 xy, Y2-1 = 1.092548 yz,
Y20 = 0.315392 (3z^2 - 1), Y21 = 1.092548 xz, Y22 = 0.546274 (x^2 - y^2).
Projection L_lm = sum over texels of L Y_lm dw, with cube-texel solid angle
dw = (2/size)^2 / (1 + u^2 + v^2)^(3/2), renormalised so sum dw = 4 pi. Irradiance
(Ramamoorthi-Hanrahan 2001): E(n) = sum_lm A_l L_lm Y_lm(n), A0 = pi, A1 = 2 pi/3, A2 = pi/4;
outgoing diffuse = albedo / pi * E.
Ringing: a bright sun makes E negative on the far side. Multiply band l by a window, e.g. Hann
(1, 0.75, 0.25) or Lanczos (1, 0.83, 0.41), and pick the weakest window for which min E over
~1000 Fibonacci directions is >= 0. Storage: 27 values -> seven RGBA16F 3D textures; hardware
trilinear filtering is valid because SH is linear. A 64 x 32 x 64 grid (131,072 probes) is
7.3 MB at L2 fp16, 3.1 MB at L1 (12 values). Grid probes inside walls leak exactly like DDGI
probes (section 6): store a validity bit and renormalise trilinear weights over valid probes.

## 6. DDGI (Majercik et al. 2019)

| Parameter | Typical |
|---|---|
| probe spacing D | 0.5-1 m interiors, 2-4 m exteriors; scrolling or cascaded volumes for big worlds |
| rays per probe per frame | 128-256, spherical Fibonacci set rotated randomly every frame |
| irradiance texels | 6 x 6 octahedral + 1-texel border = 8 x 8 (RGB10A2, R11G11B10F or RGBA16F) |
| distance texels | 14 x 14 + border = 16 x 16, RG16F (mean, mean^2) |
| hysteresis | 0.97: time constant 1/(1 - h) = 33 frames, 1% residual after ln 0.01 / ln 0.97 = 151 frames |
| surface bias | normal 0.1 D + view 0.2 D (about 0.3 D in total) |

Per frame: (1) trace active probes; hit radiance = direct light with shadows + albedo times the
volume's own previous-frame irradiance at the hit (infinite bounces over frames); misses return
the sky; back-face hits are flagged. (2) Blend irradiance texels: for texel direction n,
new = sum L_r max(0, n.w_r) / sum max(0, n.w_r), the cosine-weighted mean radiance (= E/pi, so
diffuse = albedo * value); blend distance texels with weight max(0, n.w_r)^50 over
(d, d^2), d = min(hit distance, max distance). (3) value = lerp(new, old, hysteresis).
(4) Copy octahedral borders. (5) Relocate. (6) Classify.

```hlsl
float2 OctEncode(float3 d) {                     // unit vector -> [-1,1]^2
  d /= abs(d.x) + abs(d.y) + abs(d.z);
  if (d.z < 0) d.xy = (1 - abs(d.yx)) * float2(d.x >= 0 ? 1 : -1, d.y >= 0 ? 1 : -1);
  return d.xy;
}
float3 DDGISample(float3 P, float3 N, float3 V /*to camera*/) {
  float3 Pb = P + N * gNormalBias + V * gViewBias;              // lookup point off the surface
  int3 base = clamp(int3(floor((Pb - gOrigin) / gSpacing)), 0, gCounts - 2);
  float3 alpha = saturate((Pb - (gOrigin + base * gSpacing)) / gSpacing);
  float3 sum = 0; float wsum = 0;
  [unroll] for (int i = 0; i < 8; ++i) {
    int3 off = int3(i, i >> 1, i >> 2) & 1;
    int probe = ProbeIndex(base + off);
    if (!ProbeActive(probe)) continue;
    float3 Pp = ProbePosition(probe);                           // grid position + relocation offset
    float wb = (dot(normalize(Pp - P), N) + 1) * 0.5;
    float w = wb * wb + 0.2;                                    // smooth back-face weight
    float3 v = Pb - Pp; float r = length(v);
    float2 m = gDist.SampleLevel(gLinear, ProbeUV(probe, OctEncode(v / r), 14), 0).rg;
    if (r > m.x) {                                              // Chebyshev visibility
      float var = abs(m.y - m.x * m.x), d = r - m.x;
      float cheb = var / (var + d * d);
      w *= max(cheb * cheb * cheb, 0.0);
    }
    w = max(w, 1e-6);
    if (w < 0.2) w *= w * w / 0.04;                             // crush near-invisible probes
    float3 tri = lerp(1 - alpha, alpha, off);
    w *= tri.x * tri.y * tri.z + 0.001;
    sum += w * gIrr.SampleLevel(gLinear, ProbeUV(probe, OctEncode(N), 6), 0).rgb; wsum += w;
  }
  return sum / max(wsum, 1e-6);                                 // diffuse = albedo * result
}
```

**Relocation**: a probe whose rays hit back faces more than 25% of the time is inside geometry;
move it through the closest back face (offset += dir * (dist + 0.1 D)); a probe whose closest
front-face hit is under 0.2 D moves away from it; clamp offsets to 0.45 D per axis so probes stay
in their cells. **Classification**: deactivate probes still inside geometry and probes with no
hit inside their cell (nothing to light); inactive probes are not traced and get zero weight.

## 7. Surface caches and radiance cascades

**Surface cache (Lumen-style)**: each mesh is captured into a few oriented low-resolution
"cards" (albedo, normal, depth, emissive) packed in an atlas; direct and indirect lighting are
computed in card space under a fixed per-frame update budget. Screen-space probes on a coarse
pixel grid (for example one per 16 x 16 tile, extra probes at depth discontinuities) gather an
octahedral radiance map each by tracing screen depth, then distance fields, then card lighting;
a world-space radiance cache serves long rays. Results are filtered spatially and temporally,
so lighting changes need several frames; memory is the card atlas plus probe buffers.
**Radiance cascades** (Sannikov 2023): cascade i has probe spacing D * 2^i and traces only the
ray interval [t_i, t_i+1) with geometrically growing intervals; finer angular resolution goes
with coarser spacing (the penumbra condition: spatial step proportional to distance, angular
step inversely proportional). Merge from the coarsest cascade down: radiance = interval
radiance + interval transmittance * bilinearly interpolated, direction-averaged radiance of the
next cascade. 2D variants usually use 4x directions per cascade (memory constant per cascade,
interval length x4); 3D is used as screen-space probes with depth. Trade-offs: no temporal
accumulation needed (stable, no lag) but memory grows with resolution and ringing appears at
interval boundaries (bilinear-fix variants trace to each of the next cascade's probes).

## 8. Ray-traced GI with ReSTIR GI

1. **Initial sample**: one BRDF- or cosine-sampled ray per pixel from the visible point x_v;
   at hit x_s compute outgoing radiance L_o with next-event estimation plus a radiance-cache
   lookup for further bounces. Store (x_v, n_v, x_s, n_s, L_o); weight w = p_hat / pdf with
   p_hat = luminance(L_o) (optionally times BRDF * cos at x_v).
2. **Temporal reuse**: merge the reprojected previous reservoir (reject on normal/depth
   mismatch), clamp its M to ~20-30 so it stays responsive.
3. **Spatial reuse**: 3-5 neighbours within ~30 px with normal dot > 0.9 and relative depth
   difference < 0.1; reconnection shift weight w = p_hat_q(z) * W_n * M_n * |J| with
   |J| = (cos phi_q / cos phi_n) * (|x_n - x_s|^2 / |x_q - x_s|^2), phi = angle at x_s between
   n_s and the direction to the respective visible point (Ouyang et al. 2021); trace a visibility
   ray x_q -> x_s or accept bias and leaks.
4. **Shade** with the final reservoir: L = f * cos * L_o(z) * W, W = wSum / (M * p_hat(z)).
5. **Denoise** demodulated irradiance (divide by albedo) with NRD ReLAX (built for ReSTIR
   signals) or ReBLUR, then remodulate.
6. **Multi-bounce**: SHaRC (spatially hashed world-space radiance cache, updated by a small
   fraction of paths, queried at the second vertex to terminate paths) or a neural radiance
   cache (Mueller et al. 2021); RTXGI 2.x ships both.

```hlsl
struct Reservoir { GISample z; float wSum; float M; float W; };
bool Update(inout Reservoir r, GISample s, float w, float u) {   // u: uniform random
  r.wSum += w; r.M += 1;
  if (u * r.wSum < w) { r.z = s; return true; }
  return false;
}
```

## 9. Pitfalls

- Light leaking through walls thinner than ~0.25 D: thicken walls, bias, relocate, or split
  volumes per room; SSR and SH grids leak the same way.
- Lag and ghosting under moving lights: h = 0.97 needs ln 0.1 / ln 0.97 = 76 frames to reach 90%
  of a change (1.3 s at 60 Hz); drop hysteresis toward 0.8 (10 frames) for texels whose change
  exceeds a threshold (e.g. 25% luminance).
- Double counting: AO multiplied onto GI that already includes large-scale occlusion (keep the AO
  radius below the probe spacing); SSR added on top of probe specular instead of lerped.
- Missing specular occlusion: glowing crevices and bright reflections inside dark rooms; apply
  SO or normalise probe specular by local diffuse irradiance.
- Sky visibility indoors: an unshadowed sky or ambient term lights closed rooms; sky light must
  arrive only through probes, RT or baked visibility.
- Energy errors: irradiance probes storing E but shaded as radiance (factor pi off), or SH
  evaluated without the A_l factors.

## 10. Worked example: indoor DDGI leaks at wall corners

Scene: room 12 x 8 x 4 m with 0.2 m walls centred on the room boundary, sun and sky outside. DDGI
volume over the room, D = 1 m: 13 x 9 x 5 = 585 probes, 256 rays each = 149,760 rays per
frame; atlases: 585 x 8^2 x 8 B = 293 KiB irradiance (RGBA16F), 585 x 16^2 x 4 B = 585 KiB
distance (RG16F). 585 - 11 x 7 x 3 = 354 probes (60%) lie on the boundary planes, inside walls.

1. **Leak test** (sealed room, sun and sky on, interior lights off; ground truth inside = 0):
   seal windows and doors, sample `DDGISample` at 10,000 random interior surface points
   (albedo 1) and at lit exterior ground. Metric: mean interior / mean exterior, and the maximum
   over corner points (within 0.5 m of two walls). Record the baseline.
2. **Visibility**: confirm Chebyshev weighting is enabled and the distance atlas holds wall
   distances (debug-view the 14 x 14 mean-distance octahedra; uniform max distance means the
   distance blend is not running).
3. **Bias**: normal 0.1 m + view 0.2 m (0.3 D). The biased lookup point moves into the room, so
   an outside probe's mean distance (to the wall) is now shorter than its distance to the point
   and Chebyshev rejects it.
4. **Relocate and classify**: the 354 boundary probes report > 25% back-face hits; relocation
   moves them through the nearest wall face into the room (offsets <= 0.45 m). Re-run until no
   active probe has > 25% back-face hits.
5. **Accept**: interior/exterior ratio < 0.5% mean and < 2% at any corner point.
6. **Energy (furnace) test**: sun and sky off, every interior surface emits Le = 1 with albedo
   0.5, so radiance converges to Le / (1 - rho) = 2. Each frame contracts the error by
   h + (1 - h) rho = 0.985, so 1% residual takes ln 0.01 / ln 0.985 = 305 frames (5.1 s at
   60 Hz); accept 2.0 +- 5% after that. Too low means energy loss in blending or bias; too high
   means double counting.
7. **Timings**: GPU timestamps around trace, irradiance blend, distance blend, border copy,
   relocation, classification and the lighting-pass lookup, before and after; classification
   must not add more than it saves in tracing.

Related: `realtime-shadows`, `importance-sampling-mis-restir`, `denoising-taa-upscaling`, `pbr-microfacet-brdf`, `raster-pipeline-architecture`, `path-tracer-implementation`, hub `computer-graphics`
