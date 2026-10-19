---
name: denoising-taa-upscaling
description: "Reconstructing clean frames from noisy or aliased input covering OIDN and OptiX offline denoising, demodulation, SVGF/A-SVGF and NRD real-time denoisers, MSAA/FXAA/SMAA, TAA jitter and history rejection, motion vectors for every object, and DLSS/FSR/XeSS/MetalFX integration via jitter, exposure and reactive masks. Load when renders are noisy, edges crawl, TAA ghosts or blurs, or a denoiser or upscaler is being integrated."
when_to_use: "Noisy 1-64 spp path-traced frames; integrating OIDN, the OptiX denoiser, NRD or SVGF; ghosting, smearing, flicker, crawling edges or shimmering specular; jitter, motion-vector sign or reversed-Z questions; DLSS, FSR, XeSS, MetalFX or TSR integration; mip/LOD bias and sharpening choices; UI or post effects placed wrongly relative to TAA or upscaling."
---

# Denoising, TAA and upscaling

Rule zero: reconstruction gets linear, pre-tonemap, NaN-free HDR plus correct guide buffers and motion.
Most denoiser and upscaler bugs are input-contract bugs, so validate the inputs before tuning anything.

## 1. Decision table

| Situation | Use | Notes |
|---|---|---|
| offline final frames | OIDN 2.x `RT` filter (HDR, albedo + normal) or the OptiX 9 AOV / temporal AOV denoiser | prefilter noisy guides, then `cleanAux` |
| interactive progressive viewport | OIDN balanced or fast quality, or OptiX every N samples | blend toward the raw image as spp grows |
| real time, 1 spp ray-traced signals | SVGF/A-SVGF, or NRD (ReBLUR diffuse/specular, ReLAX for ReSTIR-style input, SIGMA shadows) | separate signals, hit distances |
| real time, vendor ML | DLSS Ray Reconstruction, FSR Redstone ray regeneration (availability per SDK version) | they replace denoiser plus upscaler; do not chain your own denoiser in front |
| forward renderer | MSAA 4×, plus TAA for shading aliasing | resolve with Karis weights |
| deferred or visibility buffer | TAA or an upscaler | MSAA is impractical |
| low end, no history buffers | FXAA 3.11 or SMAA 1x after tonemapping | no temporal stability |

## 2. Input contract

| Buffer | Requirement |
|---|---|
| colour | linear HDR before tonemapping and UI; exposure known; NaN and Inf removed; fireflies clamped before temporal accumulation (real time only) |
| albedo | BSDF albedo at the first non-specular hit (follow mirrors and glass), linear, in [0, 1] |
| normal | the space each API expects: OIDN world or view; OptiX AOV and temporal models world space (legacy LDR/HDR models camera space); NRD packed with roughness |
| roughness | linear α or perceptual, as the SDK documents |
| depth | linear view Z (NRD) or device depth with a reversed-Z flag (DLSS, FSR) |
| motion vectors | screen space, from unjittered matrices, object motion included; units (pixels or UV) and sign (current to previous or the reverse) as documented |
| hit distance | per signal, primary to secondary hit (NRD normalises it with hit-distance parameters) |
| exposure | the pre-exposure used when rendering, or the SDK's auto-exposure, never both |
| reactive and transparency masks | particles, alpha-blended surfaces, animated textures, anything without valid motion |
| jitter | the per-frame subpixel offset in pixels, sign per SDK |

## 3. OIDN and OptiX

```cpp
#include <OpenImageDenoise/oidn.hpp>
oidn::DeviceRef device = oidn::newDevice();               // best available CPU or GPU backend
device.commit();
oidn::BufferRef color = device.newBuffer(size_t(w) * h * 3 * sizeof(float));   // likewise albedo, normal, output
oidn::FilterRef filter = device.newFilter("RT");
filter.setImage("color", color, oidn::Format::Float3, w, h);
filter.setImage("albedo", albedo, oidn::Format::Float3, w, h);
filter.setImage("normal", normal, oidn::Format::Float3, w, h);
filter.setImage("output", output, oidn::Format::Float3, w, h);
filter.set("hdr", true);
filter.set("cleanAux", true);                             // only after prefiltering albedo and normal (below)
filter.set("quality", oidn::Quality::High);               // Balanced; Fast since 2.3 (RT filter only)
filter.commit();
filter.execute();
const char* msg;
if (device.getError(msg) != oidn::Error::None) std::fprintf(stderr, "OIDN: %s\n", msg);
```

- Noisy guides (depth of field, motion blur, low spp): run one `RT` filter on the albedo image and one on
  the normal image (each as its own `color` and `output`), then denoise the beauty with `cleanAux`.
  Never set `cleanAux` on raw noisy guides.
- Fast quality (OIDN 2.3+) is about 1.5-2× faster than balanced for previews and falls back to balanced
  where it is not implemented (prefiltering).
- CLI checks: `oidnDenoise --hdr color.pfm --alb albedo.pfm --nrm normal.pfm [--clean_aux] -q high -o out.pfm`.
- OptiX: model kinds `OPTIX_DENOISER_MODEL_KIND_AOV` (single frame) and `OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV`
  (adds flow and the previous output's internal guide layer; `flowTrustworthiness` since 7.7), plus 2×
  upscaling kinds. Compute the HDR intensity or average colour every frame
  (`optixDenoiserComputeIntensity`, `optixDenoiserComputeAverageColor`). Check the flow sign with a
  horizontal pan; developer-forum reports say it runs opposite to DLSS-style motion vectors.

## 4. Demodulation and signal separation

```hlsl
float3 demod(float3 radiance, float3 albedo) { return radiance / (albedo + 1e-3); }   // before filtering
float3 remod(float3 filtered, float3 albedo) { return filtered * (albedo + 1e-3); }   // after filtering
```

- Textures are noise-free and high-frequency; filtering them blurs detail. Denoise demodulated
  irradiance and remodulate afterwards.
- Separate diffuse (divide by diffuse albedo), specular (divide by the pre-integrated specular term
  E_spec(n·v, roughness, F0) from the split-sum LUT) and shadow or visibility signals (penumbra width from
  hit distance, SIGMA style). Add emission after denoising: it is not noisy.
- Specular cannot follow surface motion: reproject reflections with the hit distance (virtual-image
  motion) or rely on the denoiser's specular history logic.

## 5. SVGF, A-SVGF and NRD

SVGF (Schied 2017):
1. Temporal: reproject colour and moments (μ1 = luminance, μ2 = luminance²) with motion vectors; accept
   a bilinear tap only if depth agrees (a few % relative), n·n_prev > 0.9 and the mesh ID matches;
   α = max(0.2, 1/historyLength); a disocclusion resets the history.
2. Variance: σ² = μ2 − μ1² from the temporal moments; with fewer than 4 history frames estimate it
   spatially (7 × 7 bilateral).
3. À-trous: 5 passes of the 5 × 5 B3-spline kernel (1/16, 1/4, 3/8, 1/4, 1/16) with step 2^i, weighted by

```text
w_z = exp(−|z_p − z_q| / (σ_z |∇z_p · (p − q)| + ε))          σ_z = 1
w_n = max(0, n_p · n_q)^σ_n                                    σ_n = 128
w_l = exp(−|l_p − l_q| / (σ_l sqrt(g3x3(Var(l_p))) + ε))      σ_l = 4
```

   Filter the variance with squared weights in every pass; the first pass's output becomes the next
   frame's colour history.
4. Remodulate, then run TAA.

A-SVGF (Schied 2018): forward-project one previous sample per 3 × 3 stratum, re-shade it with the same
random numbers, form the temporal gradient δ = L_new − L_old and λ = |δ|/max(L_new, L_old), filter λ with
a few à-trous passes, and set the per-pixel α = (1 − λ) α_0 + λ, so history drops where lighting changed
(moving lights, opening doors) instead of lagging.

NRD: denoisers ReBLUR, ReLAX, SIGMA and REFERENCE (plain accumulation for comparison). Pack inputs with
the `NRD.hlsli` front-end helpers (`NRD_FrontEnd_PackNormalAndRoughness`,
`REBLUR_FrontEnd_PackRadianceAndNormHitDist`, `RELAX_FrontEnd_PackRadianceAndHitDist`,
`SIGMA_FrontEnd_PackShadow`) and set the common settings every frame: current and previous view-to-clip
and world-to-view matrices, current and previous jitter, motion-vector scale, frame index and the
accumulation mode (restart or clear-and-restart on camera cuts). Names follow recent NRD releases.

## 6. MSAA, FXAA, SMAA

- HDR MSAA resolve (Karis): weight each sample by 1/(1 + luma), equivalently tonemap c/(1 + luma),
  average, invert with c/(1 − luma); one bright sample can no longer dominate an edge.
- Alpha-to-coverage for foliage under MSAA; sharpen alpha with a' = (a − cutoff)/max(fwidth(a), 1e-4) + 0.5.
- FXAA 3.11: after tonemapping, on perceptual luma (stored in alpha or taken from green);
  `FXAA_QUALITY__PRESET` 10-15, 20-29 or 39 (12 default, 39 best); cheap, softens texture detail.
- SMAA: edge detection (luma, colour or depth), blending-weight calculation (AreaTex and SearchTex
  lookups), neighbourhood blending; presets LOW/MEDIUM/HIGH/ULTRA; T2x adds 2-phase temporal jitter,
  S2x combines with MSAA 2×, 4x = S2x + T2x.

## 7. TAA

```cpp
float halton(uint32_t i, uint32_t b) { float f = 1.0f, r = 0.0f; for (; i > 0; i /= b) { f /= b; r += f * (i % b); } return r; }
// phase n = 1 + frame % N, N = 8-16 at native resolution; jitter in pixels
const float2 j = {halton(n, 2) - 0.5f, halton(n, 3) - 0.5f};
// translate after projection so it works with any matrix convention: x_clip += t_x * w_clip
const Mat4 jitteredProj = translation(2.0f * j.x / renderWidth, -2.0f * j.y / renderHeight, 0.0f) * proj;
```

Check the y sign with a one-pixel test pattern, and build motion vectors from the unjittered matrices of
both frames. Native TAA uses no mip bias or a small negative one (about −0.5); upscalers need more
(section 9).

```hlsl
float3 RGBToYCoCg(float3 c) { return float3(dot(c, float3(0.25, 0.5, 0.25)), dot(c, float3(0.5, 0.0, -0.5)), dot(c, float3(-0.25, 0.5, -0.25))); }
float3 clipTowardMean(float3 hist, float3 mu, float3 extent) {       // variance clipping (Salvi 2016)
    float3 d = hist - mu;
    float3 r = abs(d) / max(extent, 1e-5);
    float m = max(r.x, max(r.y, r.z));
    return m > 1.0 ? mu + d / m : hist;
}
// resolve: mv = MV of the closest-depth pixel in the 3x3 (dilation); hist = CatmullRom5Tap(history, uv - mv)
// mu, sigma of the current 3x3 in YCoCg; hist = clipTowardMean(hist, mu, gamma * sigma), gamma ~ 1
// alpha = 0.05-0.1, alpha = 1 on disocclusion (uv - mv off screen, depth mismatch) or a camera cut
// out = lerp(hist, cur, alpha), with per-sample weights 1/(1 + luma) against fireflies (Karis)
```

- Dilated motion vectors keep silhouettes from dragging background history.
- Catmull-Rom history sampling (5 taps) avoids the blur of repeated bilinear resampling.
- Clip in YCoCg against μ ± γσ with γ ≈ 1 (0.75-1.25); clipping toward the mean shifts colour less
  than a per-channel clamp.
- Reset (α = 1) on disocclusion and camera cuts; reactive-mask pixels get a higher α.

## 8. Motion vectors for everything

- Rigid objects: keep the previous model matrix per instance and update it after the frame.
- Skinned meshes: keep the previous frame's joint palette (or previous skinned positions) and output
  current minus previous clip position per vertex.
- Vertex animation (wind, morph targets, GPU particles): evaluate the animation at t − Δt for the
  previous position.
- Particles, alpha-blended surfaces, UV scrolling, animated textures, reflections: no valid surface
  motion, so write the reactive or transparency mask and let TAA trust the current frame more there.
- Background and sky: camera-only vectors from depth reprojection (far plane for the sky).
- Clear the MV target to camera motion and overwrite per object; RG16F; document units and sign.

## 9. Upscaler integration

- Render scale per axis: Quality 1.5× (66.7%), Balanced 1.7× (58.8%), Performance 2× (50%), Ultra
  Performance 3× (33.3%), native AA 1×; query the SDK, because XeSS and newer releases use other ratios.
- Order: jittered render at render resolution → opaque and transparent passes (masks written) →
  upscaler on linear HDR with pre-exposure → post effects that need display resolution → tonemap if not
  done yet → UI at display resolution. Never upscale or jitter the UI.
- Texture LOD bias for material samplers = log2(render width / display width), about −0.585 at
  Quality; confirm per SDK (some integration guides add a further negative offset). Not for UI, post
  effects or shadow maps.
- Jitter: use the SDK's sequence helper; the phase count grows with the upscale ratio.
- Exposure: pass the exposure used for tonemapping (or enable the SDK's auto-exposure); a mismatch causes
  ghosting and flicker.
- Sharpening: the upscaler's own (FSR RCAS) or one CAS pass in post, never both.
- Entry points: DLSS 4 through Streamline (tag resources, set per-frame constants, evaluate the feature);
  FSR 3.1/4 through the FidelityFX API (create a context; dispatch the upscale with jitter, motion-vector
  scale, render size, pre-exposure and reset); the XeSS 2 SDK; the MetalFX temporal scaler (jitter
  offset, motion-vector scale, reversed depth and reset properties); Unreal's built-in TSR. Field names
  change between releases.

## 10. Evaluation

```python
def relmse(img, ref, eps=1e-2):            # linear HDR; scale the reference to mean 1 first
    return float(np.mean((img - ref) ** 2 / (ref ** 2 + eps)))

def flicker(frames):                        # (T, H, W) tonemapped luminance, static camera and scene
    return float(np.mean(np.std(frames, axis=0)) / np.mean(frames))

def ghost_error(frames, refs, masks):       # mean error inside masks trailing the moving object
    return float(np.mean([np.abs(f - r)[m].mean() for f, r, m in zip(frames, refs, masks)]))
```

- Reference: accumulate 4096+ frames with time frozen (or 64k spp offline) at display resolution.
- FLIP (HDR-FLIP on linear images, LDR-FLIP after tonemapping) and relMSE for 1, 4 and 16 spp inputs.
- Flicker on 60 frames of a static camera; ghosting with a moving light and a rotating object in front
  of a high-contrast background.
- Save crops, error maps and a metrics JSON under `.stack/out/<agent>/`.

## 11. Pitfalls

- Tonemapped or sRGB-encoded input to a denoiser or upscaler.
- NaN or Inf poisoning history: one bad pixel spreads through à-trous and TAA; sanitise the inputs.
- Fireflies not clamped before temporal accumulation (real time): persistent bright blotches.
- Motion vectors with the wrong sign or units (pixels vs UV, flipped y).
- Jitter applied twice (projection plus an engine-level offset) or left inside the motion vectors.
- Specular denoised with diffuse settings (no hit distance, no roughness): smeared reflections.
- UI drawn before TAA or the upscaler: ghosted, blurred text.
- History kept across camera cuts or lighting changes.

## 12. Worked example: flickering 1-spp GI and a ghosting fan

Report: ray-traced GI at 1 spp flickers and smears texture detail, and TAA leaves trails behind a
rotating fan.

1. Baseline captures: 60 frames on a static camera and the fan sequence; record the flicker metric, FLIP
   against a 4096-frame accumulated reference and the trail length in pixels behind the blades.
2. Smeared textures: the denoiser received albedo-modulated radiance. Demodulate by albedo + 1e-3 before
   filtering and remodulate afterwards.
3. Flicker and blur at contacts: no hit distance, so the filter radius ignored the distance to the
   occluder. Provide hit distance (NRD normalised hit distance, or drive the SVGF kernel with it).
4. Lag after a light switches on: the history never resets. Add A-SVGF temporal gradients so α rises
   where lighting changed.
5. Fan trails: the blades rotate through a transform without a previous-frame matrix, so their motion
   vectors are camera-only. Store per-object previous transforms, dilate motion vectors and clip the
   history in YCoCg with γ = 1.
6. Re-measure with the same captures and settings and report before and after values for flicker, FLIP
   and trail length. This skill carries no engine measurements for this case; the gates are flicker
   within 10% of the accumulated reference, no trail longer than 2 px, and static-frame FLIP no worse
   than before.

Expected magnitudes (analytic, i.i.d. per-frame noise): an exponential history with weight α reduces
noise standard deviation by sqrt((2 − α)/α), which is 3.0× at SVGF's α = 0.2, 4.4× at α = 0.1 and 6.2× at
α = 0.05. A stale value decays as (1 − α)^k, taking 22 frames to fall below 10% at α = 0.1. A blade tip
at 200 px radius turning 5 times per second moves 105 px per frame at 60 fps, so without motion vectors
the trail spans much of the blade arc unless clipping rejects the history.

Related: `path-tracer-implementation`, `importance-sampling-mis-restir`, `realtime-global-illumination`, `raster-pipeline-architecture`, `color-pipeline-tonemapping`, `gpu-debugging-profiling`, hub `computer-graphics`
