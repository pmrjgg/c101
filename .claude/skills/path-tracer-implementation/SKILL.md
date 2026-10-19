---
name: path-tracer-implementation
description: "Building a correct, then fast, unidirectional path tracer on CPU or GPU covering camera and film, the NEE plus MIS integrator loop, Russian roulette, robust ray spawning and watertight intersection, BSDF and media hooks, spectral vs RGB, megakernel vs wavefront on hardware RT, progressive accumulation and the furnace, convergence and reference validation suite. Load when writing or fixing an offline or interactive path tracer."
when_to_use: "Writing or porting a path tracer on Embree, OptiX, DXR, Vulkan ray query, Metal RT or plain compute; fireflies, energy loss or gain, NaN or Inf pixels, self-intersection acne, light leaks, dark terminators; furnace or reference-match failures; megakernel vs wavefront, shader execution reordering or tile-size decisions; adding glass, participating media, spectral rendering or denoiser AOVs."
---

# Path tracer implementation

Rule zero: correctness first. The validation suite of section 7 passes before any performance work,
and every performance change re-runs it.

## 1. Architecture decision table

| Target | Choose | Notes |
|---|---|---|
| CPU, offline or interactive | Embree 4 + TBB tiles, ISPC for SIMD shading | `rtcIntersect1`/`rtcOccluded1` or ray packets; `RTC_SCENE_FLAG_ROBUST` when watertightness matters |
| GPU without RT cores | compute shaders over your own BVH | LBVH or PLOC build, CWBVH traversal (`bvh-build-traversal`) |
| Vulkan | `VK_KHR_ray_query` inline in compute, or `VK_KHR_ray_tracing_pipeline` | ray query is simplest; pipelines when many hit shaders need an SBT |
| D3D12 | DXR 1.1 inline `RayQuery`, or DXR 1.2 | 1.2 adds shader execution reordering (`HitObject`, `MaybeReorderThread`, SM 6.9) and opacity micromaps |
| CUDA | OptiX 9 | programmable pipeline plus the bundled AI denoiser |
| Apple | Metal ray tracing | `intersector<>` in compute, intersection function tables for custom primitives |

| Kernel style | When | Cost |
|---|---|---|
| megakernel (whole path loop in one kernel) | few materials, prototypes | divergence and register pressure grow with material count |
| wavefront (Laine et al. 2013): generate, extend, shade per material, shadow queues | many complex materials, offline GPU | 100-200 B of path state per path in memory, more passes |
| inline ray queries inside a compute megakernel | real time with a compact material model | simplest on modern APIs |

Shader execution reordering (DXR 1.2 `MaybeReorderThread`, Vulkan `VK_NV_ray_tracing_invocation_reorder`
with `reorderThreadNV`) pays off when hit shading diverges (many materials, incoherent secondary
bounces); the gain is hardware-dependent, so A/B it with GPU timestamps on every target.

## 2. Camera and film

```cpp
Ray pinhole(const Camera& c, int x, int y, Vec2 u) {           // u: pixel-filter offset in [0,1)^2
  const float sx = (2.0f * (x + u.x) / c.width - 1.0f) * c.tanHalfFovY * c.aspect;
  const float sy = (1.0f - 2.0f * (y + u.y) / c.height) * c.tanHalfFovY;
  return {c.pos, normalize(c.fwd + sx * c.right + sy * c.up)};
}
Ray thinLens(const Camera& c, Ray r, Vec2 uLens) {               // focus plane at focusDist along fwd
  const Vec2 d = c.lensRadius * concentricDisk(uLens);
  const Vec3 pFocus = r.o + r.d * (c.focusDist / dot(r.d, c.fwd));
  const Vec3 o = r.o + d.x * c.right + d.y * c.up;
  return {o, normalize(pFocus - o)};
}
```

- Pixel filter: a 1-pixel box is the baseline; prefer filter importance sampling of a smoother filter
  (draw the offset from the filter, weight f/p, no splatting, no inter-pixel correlation, which
  denoisers need): Gaussian radius 1.5 px with σ 0.5 (PBRT-v4 default) or Blackman-Harris width 1.5 px
  (Cycles default). Splat only filters with negative lobes.
- Film: float32 linear HDR, running mean m_n = m_{n−1} + (x − m_{n−1})/n; float32 holds to about 1e5 spp.
- AOVs for denoisers: albedo at the first non-specular hit (follow mirrors and glass), world-space normal,
  view depth, motion vectors, object and material IDs; average them over samples.
- RNG: seed = hash(x, y, frameIndex); dimensions from the fixed map in `importance-sampling-mis-restir`.

```c
uint pcgHash(uint v) { uint s = v * 747796405u + 2891336453u; uint w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u; return (w >> 22u) ^ w; }
```

## 3. Integrator skeleton (NEE + power-heuristic MIS)

```cpp
Spectrum Li(Ray ray, Sampler& s) {
  Spectrum L(0.0f), beta(1.0f);
  float prevPdf = 0.0f, etaScale = 1.0f; bool prevDelta = true; Point3 prevP;
  for (int depth = 0; depth < kMaxDepth; ++depth) {
    Hit hit;
    if (!scene.intersect(ray, hit)) {                          // miss: environment, MIS against BSDF sampling
      const float pl = prevDelta ? 0.0f : pSelect(envLight, prevP) * envLight.pdf(ray.d);
      L += beta * (prevDelta ? 1.0f : powerHeuristic(prevPdf, pl)) * envLight.Le(ray.d);
      break;
    }
    if (hit.isEmissive()) {                                    // BSDF sampling reached an area light
      const float pl = prevDelta ? 0.0f : pSelect(hit.light, prevP) * hit.light.pdfSolidAngle(prevP, hit);
      L += beta * (prevDelta ? 1.0f : powerHeuristic(prevPdf, pl)) * hit.Le(-ray.d);
    }
    const BSDF bsdf = hit.bsdf();
    const Vec3 wo = -ray.d;
    if (!bsdf.isDelta()) {                                     // next-event estimation
      const LightSample ls = sampleLight(hit, s.get1D(Dim::LightSelect), s.get2D(Dim::Light));  // pdf: P(j) x solid angle
      if (ls.pdf > 0.0f) {
        const Spectrum f = bsdf.eval(wo, ls.wi) * absDot(ls.wi, hit.ns);
        if (!f.isBlack() && scene.unoccluded(spawnShadowRay(hit, ls))) {
          const float w = ls.isDelta ? 1.0f : powerHeuristic(ls.pdf, bsdf.pdf(wo, ls.wi));
          L += beta * f * ls.Le * (w / ls.pdf);
        }
      }
    }
    const auto bs = bsdf.sample(wo, s.get1D(Dim::Lobe), s.get2D(Dim::Bsdf));
    if (!bs || bs->pdf == 0.0f) break;
    beta *= bs->f * absDot(bs->wi, hit.ns) / bs->pdf;          // delta lobes return a consistent f/pdf pair
    if (bs->isTransmission) etaScale *= sqr(bs->eta);          // undo radiance scaling for roulette only
    prevPdf = bs->pdf; prevDelta = bs->isDelta; prevP = hit.p;
    if (depth >= kRouletteStart) {                             // 3-5
      const float q = std::clamp(maxComponent(beta * etaScale), 0.05f, 1.0f);   // survival probability
      if (s.get1D(Dim::Roulette) >= q) break;
      beta /= q;
    }
    ray = spawnRay(hit, bs->wi);
  }
  return L;
}
```

Invariants: `pSelect` in the emissive-hit and miss weights is the probability that `sampleLight` would
pick that light from `prevP`; every pdf is solid angle; `prevDelta` starts true so camera rays and mirror
chains see emitters at weight 1.

## 4. Robust intersection and spawning

```cpp
// Wachter and Binder 2019 (Ray Tracing Gems, ch. 6): offset along the geometric normal in float ulps.
float3 offsetRay(float3 p, float3 n) {                         // n: geometric normal on the side of the new ray
  constexpr float origin = 1.0f / 32.0f, floatScale = 1.0f / 65536.0f, intScale = 256.0f;
  const int3 of = int3(intScale * n.x, intScale * n.y, intScale * n.z);
  const float3 pi = float3(asfloat(asint(p.x) + (p.x < 0 ? -of.x : of.x)),
                           asfloat(asint(p.y) + (p.y < 0 ? -of.y : of.y)),
                           asfloat(asint(p.z) + (p.z < 0 ? -of.z : of.z)));
  return float3(fabs(p.x) < origin ? p.x + floatScale * n.x : pi.x,
                fabs(p.y) < origin ? p.y + floatScale * n.y : pi.y,
                fabs(p.z) < origin ? p.z + floatScale * n.z : pi.z);
}
```

- Hit points from barycentrics (b0 p0 + b1 p1 + b2 p2), not o + t d. Flip n to the side of the outgoing
  direction (transmission offsets inward). Offset both ends of a shadow ray, or use
  tmax = (1 − 1e-4) · distance. No global epsilon.
- Watertight triangle test (Woop, Benthin, Wald 2013): per ray kz = argmax |d|, kx = kz + 1 mod 3,
  ky = kx + 1 mod 3, swap kx and ky if d[kz] < 0, S = (d[kx]/d[kz], d[ky]/d[kz], 1/d[kz]). Per triangle,
  shear the vertices relative to the origin, U = Cx By − Cy Bx, V = Ax Cy − Ay Cx, W = Bx Ay − By Ax
  (redo in double if any is exactly 0); miss if their signs differ; det = U + V + W;
  T = U Az + V Bz + W Cz with Az = S.z A[kz] and so on; reject T outside (0, tmax · det) taken in the sign
  of det; then t = T/det and barycentrics (U, V, W)/det for vertices (A, B, C). Shared edges are never missed.
- Sidedness: a direction is valid only if the geometric and shading normals agree on its side; otherwise
  reject the sample (no light leaks) or apply the terminator fix from `pbr-microfacet-brdf`.
- Alpha: any-hit shaders for alpha-tested geometry (stochastic alpha for semi-transparency), the OPAQUE
  flag everywhere else, and opacity micromaps (`VK_EXT_opacity_micromap`, DXR 1.2) for foliage so only
  "unknown" micro-triangles invoke any-hit.

## 5. Materials and media hooks

```cpp
struct BSDFSample { Vec3 wi; Spectrum f; float pdf; float eta; bool isDelta, isTransmission; };
struct BSDF {
  Spectrum eval(Vec3 wo, Vec3 wi) const;                       // no cosine; 0 for delta lobes
  float pdf(Vec3 wo, Vec3 wi) const;                           // solid-angle mixture pdf; 0 for delta lobes
  std::optional<BSDFSample> sample(Vec3 wo, float uLobe, Vec2 u) const;
};
// Contract test for every material and random wo, non-delta samples:
//   |s.pdf - pdf(wo, s.wi)| <= 1e-4 * s.pdf and s.f == eval(wo, s.wi); plus the chi-square test.
```

- Two-sided opaque materials flip the shading frame to the side of wo; transmissive materials keep the
  orientation and invert η on exit.
- Nested dielectrics (Schmidt and Budge 2002): each medium has a priority and the path keeps a small stack
  of media it is inside. A surface hit whose priority is below the highest current medium is a false hit
  (continue the ray, no BSDF event); η on each side comes from the highest-priority medium there. Liquid
  in a glass then needs no exactly coincident surfaces.
- Homogeneous media: free flight t = −ln(1 − u)/σ_t, transmittance exp(−σ_t d); with chromatic σ_t pick
  the channel by throughput and use spectral MIS over channels.
- Heterogeneous media with a majorant σ̄ ≥ σ_t(x): delta tracking for scattering (step
  t −= ln(1 − u)/σ̄; a real collision with probability σ_t(x)/σ̄, else continue); ratio tracking for
  shadow rays, T = Π (1 − σ_t(x_i)/σ̄) over tentative collisions (Novák 2014; residual ratio tracking
  with a control majorant for thick media).
- Henyey-Greenstein: p(cos θ) = (1/4π)(1 − g²)/(1 + g² − 2g cos θ)^{3/2}, θ from the propagation
  direction (g > 0 forward). Sample cos θ = (1 + g² − ((1 − g²)/(1 − g + 2gξ))²)/(2g), or 1 − 2ξ when
  |g| < 1e-3. The phase function is its own pdf, so the weight is the single-scattering albedo.

## 6. Spectral vs RGB

| Need | Choose |
|---|---|
| dispersion, thin-film iridescence, metamerism checks, measured spectral data | spectral, hero wavelength (Wilkie 2014) |
| everything else | RGB in linear Rec.709 or ACEScg (the wider gamut reduces RGB product error for saturated colours) |

- Hero wavelength: sample λ_h (PBRT-v4 draws visible wavelengths with pdf ∝ 1/cosh²(0.0072 (λ − 538))
  over 360-830 nm), add C − 1 companions λ_j = λ_min + ((λ_h − λ_min + jΔ/C) mod Δ), C = 4, combine with
  spectral MIS, and terminate the companions at a dispersive interface.
- RGB uplifting (Jakob-Hanika 2019): s(λ) = S(c0 λ² + c1 λ + c2), S(x) = ½ + x/(2 sqrt(1 + x²)), with
  coefficients from a precomputed 3D table per colour space; reflectances stay in [0, 1]; emitters are a
  scale times the sigmoid times the illuminant spectrum.

## 7. Validation suite

| Test | Pass criterion |
|---|---|
| white furnace: uniform environment L = 1, every BSDF at albedo 1 (white Lambert, compensated F0 = 1 conductor, smooth glass) | every pixel equals 1 within 3 standard errors; below 1 is energy loss, above is gain or double counting |
| two seeds | the difference image has mean within 3 standard errors of 0 and no spatial structure |
| convergence | log-log RMSE vs spp (16-1024) has slope −0.5 ± 0.05; a plateau means bias |
| reference | relMSE and HDR-FLIP vs PBRT-v4 or Mitsuba 3 at 4k-64k spp on the same scene, per crop |
| Cornell box | matches a trusted reference render of the same scene description |
| NaN/Inf counters | atomic counters per pass for NaN, Inf and negative radiance stay at zero in CI |

```python
def furnace_ok(img):                                  # img: per-pixel means of a furnace render, expected 1
    mean, se = img.mean(), img.std() / np.sqrt(img.size)
    return abs(mean - 1.0) < 3 * se + 1e-4, mean, se
```

## 8. Firefly and bias triage order

1. Sample/pdf mismatch: chi-square plus the pointwise contract test.
2. Missing or inconsistent MIS: BSDF-only, NEE-only and MIS renders must share one mean.
3. Caustic paths (diffuse → specular → small light): expected with unidirectional tracing; use path
   guiding, regularisation or manifold NEE, never a hidden clamp.
4. Roulette q too low or computed without etaScale: check the 0.05 floor and the survival formula.
5. Shading-normal artifacts: sidedness rule and terminator fix.

Clamping per-sample luminance (for example to 10-20 × exposure-normalised white) is a documented last
resort for previews; it is biased and never used for references or validation runs.

## 9. Performance

- Report rays/s and samples/s per named GPU or CPU with driver, resolution, spp, scene and timing method
  (GPU timestamps, median of 10 runs).
- Wavefront: path regeneration refills finished lanes with new camera paths; stream compaction by prefix
  sum over alive flags; sort or bin by material ID (16-bit radix keys), or use SER.
- BVH node-visit heatmaps locate pathological geometry (`bvh-build-traversal`).
- Progressive accumulation resets on camera motion, scene or material edits and resolution changes; keep
  frameIndex running for RNG decorrelation.
- CPU: 16 × 16 or 32 × 32 tiles with dynamic scheduling (TBB `parallel_for`), Embree packets or streams
  for coherent primary rays, ISPC for shading loops.

## 10. Pitfalls

- Emitters counted twice (NEE and BSDF hits both at full weight), or P(light) missing from one MIS weight.
- Self-intersection handled with a global epsilon along the ray: acne at small scales, leaks at large ones.
- o + t d hit points in large scenes; delta lights or delta lobes fed to the power heuristic (inf/inf).
- Accumulation not reset after edits (ghosting); the same RNG sequence every frame (frozen noise).
- Radiance η² scaling applied in light tracing, or missing in camera tracing (`pbr-microfacet-brdf`).
- f/p evaluated when p = 0: guard before dividing; one NaN poisons accumulation and the denoiser.

## 11. Worked example: fireflies around a small area light

Incident (hub worked example, steps 2-3): a GGX metal at roughness 0.9 next to a small rectangular light
shows fireflies around the light's reflection and does not match Mitsuba 3.

1. Split the estimator: BSDF-only and NEE-only renders (each should be unbiased) disagree in mean, so a
   strategy is wrong, not just noisy.
2. Chi-square of `sample()` against `pdf()` (harness in `pbr-microfacet-brdf`, μ = 0.5, α = 0.3, 1e6
   samples): χ² = 547,236 on 511 dof, p far below 1e-6, and ∫ pdf dω = 1.75 while the acceptance rate
   is 0.80. `pdf_bsdf()` returns the half-vector density D(h)(n·h) without the 1/(4 |v·h|) Jacobian.
3. Why fireflies: the reported pdf is 4|v·h| times the true density. For most directions it is too
   large, so the power heuristic trusts BSDF sampling where it should trust NEE, and the rare BSDF rays
   that hit the small, bright light carry nearly full weight; where |v·h| < 0.25 it is too small and
   f cos/pdf explodes.
4. Fix: pdf = D(h)(n·h)/(4 |v·h|), or switch to VNDF sampling with pdf G1(v) D(h)/(4 n·v). Re-test:
   χ² = 524.7 (p = 0.33) for the classic sampler and 502.4 (p = 0.60) for VNDF.
5. Verify end to end: relMSE against a 16k-spp Mitsuba 3 reference at equal 256 spp falls from 0.11 to
   0.004 and the log-log error slope is −0.49 (figures from the hub incident; regenerate them for your
   scene). Furnace and two-seed tests stay green.
6. Output contract: root cause (missing Jacobian), failing and passing test numbers, fix, metrics,
   remaining bias (none), clamps (none).

Related: `pbr-microfacet-brdf`, `importance-sampling-mis-restir`, `bvh-build-traversal`, `denoising-taa-upscaling`, `color-pipeline-tonemapping`, `gpu-debugging-profiling`, hub `computer-graphics`
