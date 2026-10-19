---
name: computer-graphics
description: "Computer graphics working pack: radiometry and the rendering equation, BRDFs (Lambert, GGX microfacet, Disney/OpenPBR), Monte Carlo path tracing with importance sampling, MIS and Russian roulette, BVH construction and traversal, raster pipeline design (forward+, deferred, visibility buffer, reversed-Z), Vulkan/Metal/WebGPU/DX12 concepts and synchronization, shader languages, color science and tonemapping, geometry processing, SDFs, numerical robustness, and GPU debugging with RenderDoc, Nsight, PIX and Xcode. Load for any rendering, shading, GPU API, color pipeline or mesh-processing task."
when_to_use: "Writing or reviewing a renderer, shader, BRDF, sampler, BVH or GPU pipeline; diagnosing noise, fireflies, acne, banding, NaNs, black frames, sync hazards or color shifts; choosing an API or render architecture; validating a renderer against a reference."
---

# Computer graphics

Graphics bugs are rarely crashes; they are images that look almost right. The discipline this skill
enforces: write down the quantity (with units) each buffer holds, derive every estimator weight
on paper before coding it, and prove convergence against a reference before tuning for speed.

## 0. Triage

| Symptom or request | Go to |
|---|---|
| Physically based shading, energy loss at high roughness, too-bright rims | sections 1-2, [BRDF and sampling formulas](references/brdf-and-sampling.md) |
| Noise, fireflies, slow convergence, biased result | section 3 |
| Slow ray tracing, BVH quality, animated geometry | section 4 |
| Raster architecture, z-fighting, shadows, AA, upscaling | section 5 |
| API choice, barriers, descriptors, validation errors, GPU hangs | section 6, [GPU API map](references/gpu-api-map.md) |
| Washed-out, too-dark, hue-shifted or banded images, HDR output | section 7, [color pipeline](references/color-pipeline.md) |
| Mesh cleanup, normals, decimation, UVs, SDFs | sections 8-9 |
| Acne, light leaks, holes between triangles, jitter far from origin | section 10 |
| Black screen, wrong frame, perf regression | section 11 |

## 1. Radiometry you must keep straight

| Quantity | Symbol | Unit | Used for |
|---|---|---|---|
| Radiant flux | Φ | W | light power, photon mapping |
| Irradiance | E | W/m² | light arriving at a surface (all directions) |
| Radiance | L | W/(m² sr) | what a camera pixel and a ray carry; constant along a ray in vacuum |
| Intensity | I | W/sr | point lights; E = I cosθ / d² |
| BRDF | f_r | 1/sr | ratio dL_o / dE_i |

Rendering equation (surface, no participating media):

```
L_o(x, ω_o) = L_e(x, ω_o) + ∫_Ω f_r(x, ω_i, ω_o) L_i(x, ω_i) (n·ω_i) dω_i
```

Physical BRDF requirements, each a unit test: non-negativity; reciprocity f(ω_i, ω_o) = f(ω_o, ω_i);
energy conservation (directional albedo ρ(ω_o) = ∫ f cosθ_i dω_i ≤ 1 for every ω_o).
Photometric units (lux, nits = cd/m²) appear at the camera and display end; keep the renderer in
one system and convert once (683 lm/W at 555 nm).

## 2. Material models

| Model | Use | Key facts |
|---|---|---|
| Lambert | rough diffuse, baselines | f = ρ/π; albedo ρ ≤ 1 |
| GGX (Trowbridge-Reitz) microfacet | default specular, metals, dielectrics | f = D G F / (4 (n·l)(n·v)), α = roughness² (perceptual remap) |
| Disney principled (Burley 2012/2015) | art-directable, film | baseColor, metallic, roughness, specular, sheen, clearcoat, transmission |
| OpenPBR Surface (ASWF, v1.0 2024) | interchange standard, MaterialX | layered: coat, fuzz, specular, diffuse/subsurface, thin-film; use for new pipelines |
| glTF 2.0 metallic-roughness + KHR extensions | real-time asset delivery | F0 = mix(0.04, baseColor, metallic); diffuse = baseColor (1 - metallic) |

GGX essentials (full derivations, sampling routines and pdfs in
[BRDF and sampling formulas](references/brdf-and-sampling.md)):

```
D(h)  = α² / (π ((n·h)² (α² - 1) + 1)²)
Λ(ω)  = (-1 + sqrt(1 + α² tan²θ_ω)) / 2
G2    = 1 / (1 + Λ(v) + Λ(l))                      height-correlated Smith
F(θ)  = F0 + (1 - F0)(1 - cos θ_d)^5                Schlick, θ_d = angle between v and h
F0    = ((η - 1)/(η + 1))²                          η = 1.5 gives 0.04
```

Pitfalls:
- Single-scattering GGX loses energy as α grows (directional albedo at normal incidence is about
  0.69 at α = 0.5 and 0.31 at α = 1 for F0 = 1), so rough metals look dark.
  Add multiple-scattering compensation (Kulla-Conty 2017, or the Turquin 2019 scale 1 + F0 (1/E_ss - 1))
  using a precomputed 1D/2D albedo LUT.
- Using `roughness` directly as α. Decide the remap once and document it per asset format.
- Clamping n·v to 0 creates NaN in 1/(n·v); clamp to a small positive (1e-4) or use `abs` with a
  geometric-normal check for back-facing shading normals.
- Normal maps can make n·l > 0 while the geometric normal says the light is below the surface:
  reject or use a shadow-terminator fix (e.g. Chiang 2019 shading-normal correction) consistently.

## 3. Monte Carlo path tracing

Estimator for I = ∫ f(x) dx with samples X_k ~ p:

```
F_N = (1/N) Σ f(X_k) / p(X_k)        unbiased iff p > 0 wherever f ≠ 0
stderr ≈ σ/√N                         4x samples halve noise; 2x speedup = 2x samples, not 1.41x quality
```

Sampling decision table:

| Situation | Sample by | Why |
|---|---|---|
| Diffuse surface, large/env light | cosine hemisphere, p = cosθ/π | weight f cos/p = ρ exactly |
| Glossy GGX | visible-normal distribution (VNDF; Heitz 2018, spherical-cap variant Dupuy-Benyoub 2023) | weight = F G2/G1(v), bounded |
| Small bright light, rough surface | light sampling (area, solid angle for spheres) | BSDF sampling rarely hits it |
| Sharp glossy + large light | BSDF sampling | light samples land outside the lobe |
| Both regimes in one scene (always) | multiple importance sampling | robust across the table |
| Thousands or millions of lights | light BVH / light tree, or ReSTIR DI (Bitterli 2020) | sample proportional to estimated contribution |
| Real-time GI at 1 spp | ReSTIR GI (2021) / ReSTIR PT (2022) + denoiser | spatiotemporal reuse; watch bias from reuse |
| Env map | piecewise-constant 2D (marginal + conditional CDF), weight by sinθ for lat-long | pdf conversion: p_ω = p_uv / (2π² sinθ) |

MIS with one sample from each strategy:

```
balance:  w_i(x) = p_i(x) / Σ_k p_k(x)
power(β=2): w_i(x) = p_i(x)² / Σ_k p_k(x)²       (default; Veach 1997)
contribution = w_light · f·L·cos / p_light  +  w_bsdf · f·L·cos / p_bsdf
```

Convert every pdf to the same measure before combining: area pdf to solid angle is
`p_ω = p_A · d² / |cos θ_light|`. Delta lights and perfectly specular BSDFs have no density: give
them weight 1 and skip the other strategy.

Russian roulette after bounce 3-5: continue with probability q = min(1, max(throughput RGB)) (or
luminance), divide throughput by q. Never let q drop below ~0.05 on paths with large throughput:
that is a firefly generator.

Firefly checklist (in order): (1) a pdf mismatch between sampling routine and `pdf()` function
(test numerically: histogram samples vs analytic pdf, chi-square test as in PBRT/Mitsuba test
suites); (2) missing MIS on a small light reached by BSDF sampling; (3) caustic paths
(diffuse-specular-light) that only BSDF sampling finds; (4) Russian roulette q too low;
(5) shading-normal artifacts. Clamping radiance (e.g. per-sample luminance ≤ 10-20 × exposure) is
a biased last resort; document it in the output and never apply it to reference renders.

Sample generators: Owen-scrambled Sobol (Burley 2020 hash-based) or blue-noise screen-space
dithered sequences for real-time; independent random only for debugging. Decorrelate dimensions
per bounce; reusing the same dimension for light selection and BSDF lobe selection causes structured
artifacts.

Validation suite (run before any perf work):
- White furnace: uniform environment L = 1, BSDF with albedo 1 (or white Lambert) on a closed or
  convex object: every pixel must converge to exactly 1. Lower values show energy loss, higher
  values show energy gain or double counting.
- Reciprocity: swap ω_i and ω_o in random tests; |f(a,b) - f(b,a)| below 1e-5 relative.
- Reference match: same scene in PBRT-v4 or Mitsuba 3 at 4k-64k spp; compare with relMSE and
  NVIDIA FLIP, not by eye.
- Convergence: log-log plot of error vs spp has slope -0.5 for an unbiased estimator; a plateau
  means bias (clamping, missing paths, wrong pdf).
- Two seeds: the difference image of two independent renders should look like noise with zero mean.

## 4. Acceleration structures

SAH cost for a split into L and R (child surface areas A_L, A_R of parent area A):

```
C = C_trav + (A_L/A) N_L C_isect + (A_R/A) N_R C_isect          typical C_trav/C_isect ≈ 1/1 to 1/4
```

| Need | Build | Notes |
|---|---|---|
| Static scene, offline | binned SAH (16-32 bins) + spatial splits (SBVH) | SBVH helps long thin triangles; costs memory |
| GPU build every frame | LBVH (Morton codes) or PLOC | fast build, ~10-30% worse traversal than SAH |
| Animated skinned mesh | refit bounds, rebuild when SAH cost degrades by >~30% | refit is O(n), quality decays with deformation |
| Instances | two-level: BLAS per mesh, TLAS over instances | matches DXR / Vulkan RT / Metal RT; rebuild TLAS, refit or keep BLAS |
| Hardware RT | let the driver build; choose PREFER_FAST_TRACE vs FAST_BUILD flags; compact static BLAS | measure with Nsight / RGP; avoid one giant BLAS with many materials |
| Wide BVH on CPU | BVH4/BVH8 with SIMD (Embree) | use Embree rather than writing your own for production CPU tracing |

Traversal: visit the nearer child first, keep t_max shrinking, use the robust slab test with
t_max scaled by 1 + 2γ(3) (Ize 2013) so rays grazing box edges do not miss. Cost metric to report:
average node visits and triangle tests per ray (render as a heatmap).

## 5. Raster pipeline design

| Architecture | Choose when | Costs |
|---|---|---|
| Forward | few lights, MSAA required, transparency-heavy, VR | light loop per fragment |
| Forward+ / clustered | many lights, still want MSAA and material variety | light-cluster build pass |
| Deferred (G-buffer) | many lights, uniform material model | bandwidth (4-6 RTs), no MSAA, transparency separate |
| Visibility buffer | dense geometry (meshlets, virtualized geometry), many materials | material resolve pass, derivatives computed analytically |

Depth precision: use reversed-Z (near maps to 1, far to 0) with a 32-bit float depth buffer and
GREATER depth test; with an infinite far plane this removes most z-fighting. With standard Z and
24-bit fixed depth, precision near the far plane falls with the square of distance.

Shadows: cascaded shadow maps (3-4 cascades, stabilise by snapping to texel increments, PCF or
PCSS filtering), or ray-traced shadows where hardware RT exists. Bias = constant + slope-scaled;
too little gives acne, too much gives peter-panning; normal-offset bias usually beats both.

Anti-aliasing and reconstruction: MSAA for geometry edges in forward; TAA with neighbourhood
clamping for everything else; vendor upscalers (DLSS, FSR, XeSS) need motion vectors, jittered
projection, reactive masks and correct exposure input. Ghosting means wrong or missing motion
vectors (animated textures, particles) or no disocclusion handling.

GPU-driven rendering: meshlets (64-128 vertices, 124-256 triangles; generate with meshoptimizer),
mesh/task shaders or compute culling plus indirect draws, two-phase occlusion culling with a
hierarchical Z pyramid.

## 6. GPU APIs and shader languages

Concepts map across APIs; the full table, barrier rules and validation commands are in
[GPU API map](references/gpu-api-map.md). The short version:

| Concept | Vulkan | D3D12 | Metal | WebGPU |
|---|---|---|---|---|
| Recorded work | command buffer | command list | command buffer + encoders | command encoder |
| Pipeline state | VkPipeline / shader objects | PSO | pipeline state object | GPURenderPipeline |
| Resource binding | descriptor sets / buffers, push constants | root signature, descriptor heaps | argument buffers | bind groups |
| Hazard tracking | explicit barriers (sync2) | resource/enhanced barriers | automatic by default, manual with untracked heaps | automatic |
| CPU-GPU sync | fences, timeline semaphores | fences | MTLSharedEvent, completion handlers | onSubmittedWorkDone, mapAsync |

Rules that prevent most real-world API bugs:
1. Turn on validation from day one (Vulkan validation layer with synchronization validation,
   D3D12 debug layer plus GPU-based validation, Metal API and shader validation, WebGPU error
   scopes). Treat every validation message as a bug.
2. Frames in flight: N copies of per-frame resources, a fence per frame, never write a buffer the
   GPU may still read.
3. Every write-then-read across passes needs a barrier with the right stages and access masks;
   layout transitions are writes.
4. Pick the shader path once: HLSL via DXC to DXIL/SPIR-V, Slang (Khronos-hosted since 2024) for
   multi-target, WGSL via Tint/Naga, MSL directly or via SPIRV-Cross. Pin compiler versions.
5. Verify current API details with `mcp__context7__query-docs` (wgpu, Vulkan-Hpp, Metal) before
   writing code against an extension or a recently changed signature.

Shader pitfalls: derivatives (ddx/dFdx, implicit-LOD sampling) inside non-uniform control flow are
undefined (WGSL rejects them via uniformity analysis); mediump/half overflow at 65504; NaN from
normalize(0) or sqrt(negative) propagates through TAA history forever; integer division by zero is
undefined; texture coordinates at exact texel centres need the half-texel offset on some paths.

## 7. Color science and tonemapping

Pipeline order: decode textures to linear (sRGB EOTF for color, none for data maps) -> shade in a
linear scene-referred space (Rec.709/sRGB primaries, or ACEScg for wide gamut) -> exposure ->
tonemap / display transform -> encode for the display (sRGB OETF, PQ or HLG for HDR).

```
sRGB decode: c ≤ 0.04045 ? c/12.92 : ((c + 0.055)/1.055)^2.4
Luminance (linear Rec.709): Y = 0.2126 R + 0.7152 G + 0.0722 B
EV100 = log2(L_avg · 100 / 12.5);  L_max = 1.2 · 2^EV100;  exposure = 1 / L_max
```

| Display transform | Character | Use |
|---|---|---|
| Reinhard x/(1+x) | desaturated, flat | debugging only |
| ACES RRT+ODT (or Narkowicz fit) | contrasty, hue skews in saturated highlights | film-style pipelines already on ACES |
| AgX (Blender 4.0 default) | graceful highlight desaturation | general-purpose default for path tracers |
| Khronos PBR Neutral (2024) | preserves base color hues for product shots | e-commerce, material preview |
| HDR10 PQ (ST 2084) | absolute nits up to 10,000 | HDR output; needs metadata and paper-white control |

Color bugs: albedo textures loaded as linear (image too dark and saturated) or normal/roughness
maps loaded as sRGB (shading wrong); blending or filtering in gamma space; non-premultiplied alpha
through a bilinear filter (dark fringes); 8-bit render targets in HDR passes (banding, use
R11G11B10F or RGBA16F); applying tonemapping twice (UI pass plus post). Details and gamut mapping:
[color pipeline](references/color-pipeline.md).

## 8. Geometry processing

| Task | Method | Library |
|---|---|---|
| Validate mesh | manifold edges, consistent winding, no degenerate or duplicate faces, watertight | trimesh, libigl, CGAL, Open3D |
| Vertex normals | angle-weighted (or area-weighted) face normals; split at creases above a threshold angle | any |
| Smoothing / fairing | cotangent Laplacian (implicit step for stability) | libigl |
| Decimation | quadric error metrics (Garland-Heckbert 1997), protect borders and UV seams | meshoptimizer `meshopt_simplify`, CGAL |
| Remeshing | isotropic remeshing (split/collapse/flip/relax) | CGAL, pmp-library |
| Parameterization | LSCM / ABF++ for charts, SLIM for low distortion | libigl, xatlas for atlas packing |
| GPU-ready mesh | vertex cache, overdraw, vertex fetch optimisation, meshlets | meshoptimizer |
| Booleans | exact arithmetic (Nef polyhedra) or mesh arrangements | CGAL, libigl (`igl::copyleft::cgal`), Manifold |

Always report mesh stats before and after: vertices, faces, boundary loops, non-manifold edges,
genus (Euler characteristic V - E + F = 2 - 2g per closed component).

## 9. Signed distance fields

- Sphere tracing step t += d(p) is safe only if d is 1-Lipschitz. Smooth-min blends, domain warps
  and non-uniform scales break the bound: divide the step by the Lipschitz constant or use a
  relaxation factor 0.5-0.9, and cap iterations (128-256) and distance.
- Primitives: sphere |p| - r; box: q = |p| - b, d = |max(q, 0)| + min(max(q.x, q.y, q.z), 0).
  Polynomial smooth min with blend radius k: h = max(k - |a - b|, 0)/k, smin = min(a, b) - h²k/4.
- Normals: central differences with ε scaled to pixel footprint, or the 4-tap tetrahedron stencil.
- Mesh extraction: marching cubes (watch ambiguous cases, use a consistent table), dual contouring
  or surface nets to keep sharp features. Mesh to SDF: winding numbers for sign on non-watertight
  input (generalised winding number, Jacobson 2013).

## 10. Numerical robustness

| Problem | Robust fix | Avoid |
|---|---|---|
| Self-intersection (acne) on secondary rays | offset origin along the geometric normal by an error-bounded amount (Wächter-Binder, Ray Tracing Gems ch. 6) | a global epsilon tuned to one scene scale |
| Cracks between adjacent triangles | watertight ray-triangle test (Woop-Benthin-Wald 2013) | Möller-Trumbore when watertightness matters |
| Missed hits at box edges | conservative slab test, t_max · (1 + 2γ(3)) | plain float slab test |
| Jitter far from origin | camera-relative rendering, double precision on CPU for world transforms | float32 world positions beyond ~1e5 units |
| Quadratic solves (spheres, cones) | stable form q = -0.5 (b + sign(b) sqrt(disc)), roots q/a and c/q | textbook formula (cancellation) |
| NaN/Inf | assert in debug, render a magenta NaN view, sanitise at buffer write | letting NaN reach temporal accumulation |
| Interpolated normals | renormalise after interpolation and after normal-map decode | assuming interpolated vectors are unit length |

## 11. Debugging and profiling

| Tool | Platform | Use it for |
|---|---|---|
| RenderDoc | Vulkan, D3D11/12, OpenGL, GLES | frame capture, pipeline state, mesh viewer, pixel history, shader debugging |
| Nsight Graphics / Nsight Systems | NVIDIA | GPU trace, shader profiler, RT inspector; CPU-GPU timeline and stalls |
| PIX | D3D12 on Windows | captures, timing, DRED for device-removed errors |
| Xcode Metal debugger / Instruments | Apple | frame capture, shader debugger, Metal System Trace |
| Radeon GPU Profiler / Intel GPA | AMD / Intel | wave occupancy, barriers, cache behaviour |
| Browser WebGPU tooling | Chrome, Safari | error scopes, `chrome://gpu`, Safari Web Inspector graphics |

Black-screen checklist: (1) validation output clean? (2) clear color visible (change it to magenta)?
(3) viewport and scissor sizes, (4) depth test direction and clear value (reversed-Z clears to 0),
(5) culling and winding order, (6) projection handedness and clip-space depth range (0..1 vs -1..1),
(7) shader outputs written to the right location / render target, (8) swapchain format sRGB vs
UNORM, (9) descriptor actually bound for this draw, (10) exposure not 0 or NaN.

Perf method: GPU timestamps per pass first (find the pass), then a capture of that pass (find the
bottleneck: occupancy, bandwidth, ALU, texture, ROP), then change one thing and re-measure with
at least 3 runs and fixed clocks where the tooling allows it.

## 12. Worked example: rough metal looks too dark and noisy

Report: GGX metal at roughness 0.9 renders darker than the reference and shows fireflies near a
small area light.

1. Furnace test with F0 = 1, α = 0.81 (roughness 0.9 squared): the sphere converges to ~0.42 at
   its centre (μ = 1) and ~0.54 at μ = 0.5 instead of 1 everywhere (numerically integrated E_ss
   for height-correlated GGX). Diagnosis: single-scattering energy loss, an expected property of
   the model, not a sampling bug.
   Fix: precompute E_ss(μ, α) as a 32×32 LUT and multiply specular by 1 + F0 (1 - E_ss)/E_ss.
   Re-run: furnace converges to 0.99-1.0.
2. Fireflies: BSDF-sampled rays hitting the small light are counted at full weight, while light
   sampling also counts it: the light is double counted only if MIS weights are missing; here the
   weights exist but `pdf_bsdf()` returns the half-vector pdf D(h)(n·h) without the 1/(4 |v·h|)
   Jacobian. Chi-square test of the sampler against `pdf_bsdf()` fails at p < 1e-6.
   Fix the Jacobian (or switch to VNDF sampling with pdf G1(v) D(h) / (4 n·v)); test passes.
3. Verify: relMSE against Mitsuba 3 at 16k spp drops from 0.11 to 0.004 at equal 256 spp; the
   log-log error curve has slope -0.49.

Report in the output contract: the two root causes, the tests that show them, before/after
metrics, and the remaining known bias (none) or clamp (none).

## Quality gate before returning

- [ ] Every new BRDF passes reciprocity, non-negativity and furnace tests.
- [ ] Every sampler passes a chi-square test against its `pdf()`.
- [ ] Results compared to a reference renderer or analytic case with a numeric metric.
- [ ] Validation layers clean; no NaN in a NaN-view capture.
- [ ] Color spaces stated for every texture input and render target.
- [ ] Perf claims include GPU, driver, resolution, timing method and run count.
