---
name: pbr-microfacet-brdf
description: "GGX/Trowbridge-Reitz microfacet BRDF and BSDF implementation with D, height-correlated Smith G2, Schlick vs exact Fresnel, glTF/OpenPBR/Disney parameter mapping, VNDF sampling and mixture pdfs, multiple-scattering energy compensation, rough dielectric transmission, real-time specular antialiasing and the furnace, reciprocity and chi-square tests. Load when writing, porting or debugging a physically based material."
when_to_use: "A material renders too dark, too bright, plasticky or wrong at grazing angles; implementing or porting GGX/Cook-Torrance, Disney principled, glTF KHR_materials_* or OpenPBR/MaterialX; roughness-to-alpha questions; furnace, reciprocity or chi-square failures in a BSDF; fireflies traced to a lobe pdf; rough glass, clearcoat, sheen or anisotropy; specular aliasing or half-precision overflow in shaders."
---

# PBR microfacet BRDF

Rule zero: a BSDF is not done until it passes the furnace, reciprocity and chi-square tests of
section 9; judge it by eye only after that. Numbers below come from the NumPy harness in
[references/numpy-harness.md](references/numpy-harness.md) (float64, Apple M3 Ultra).

## 1. Conventions and invariants

- Shading frame: n = (0,0,1), tangent x, bitangent y. v = ω_o (toward the viewer) and l = ω_i (toward
  the light) are unit and point away from the surface; h = normalize(v + l); μ = cos θ = z.
- Every pdf is per unit solid angle unless written p_A. f has units 1/sr; the estimator weight is
  f |n·l| / pdf.
- Roughness remap, pinned per asset format in one function (never inline it):

| Format | Authored value | GGX α |
|---|---|---|
| glTF 2.0, Disney principled, Unreal, OpenPBR | perceptual roughness r | r² |
| Unity (Standard, URP, HDRP) | smoothness s | (1 − s)² |
| raw GGX papers, measured fits | α | α |

- Clamp α ≥ 1e-3 in float32 path tracers; in half-precision shaders clamp r ≥ 0.089 (section 7).
- The three BRDF invariants are unit tests with fixed seeds:
  1. Non-negativity: f(v, l) ≥ 0 for 1e5 random pairs, and f = 0 when either direction is below the horizon.
  2. Reciprocity: |f(v,l) − f(l,v)| ≤ 1e-5 · max(|f(v,l)|, |f(l,v)|). Refraction obeys the generalized
     form f_t(v→l)/η_l² = f_t(l→v)/η_v². Turquin compensation (section 5) is not reciprocal: exempt it
     from this test or use Kulla-Conty.
  3. Energy: directional albedo E(v) = ∫ f |n·l| dω_l ≤ 1 (within 3 standard errors) for every v.

## 2. Formula sheet

```text
Lambert          f_d = ρ/π
GGX D            D(h) = α² / (π ((n·h)²(α² − 1) + 1)²)
GGX D aniso      D(h) = 1 / (π αx αy ((hx/αx)² + (hy/αy)² + hz²)²)
Smith Λ          Λ(ω) = (−1 + sqrt(1 + (αx² ωx² + αy² ωy²)/ωz²)) / 2        isotropic: α² tan²θ
G1, G2           G1(ω) = 1/(1 + Λ(ω));  G2 = 1/(1 + Λ(v) + Λ(l)) height-correlated (use this)
                 G2 = G1(v) G1(l) separable: darker at grazing, legacy engines only
Specular         f_s = D G2 F / (4 (n·l)(n·v))
Visibility       V = G2/(4 (n·l)(n·v)) = 0.5 / (NoL sqrt(NoV²(1 − α²) + α²) + NoV sqrt(NoL²(1 − α²) + α²))
Schlick          F = F0 + (1 − F0)(1 − v·h)^5      v·h for lights; n·v only inside split-sum IBL
Dielectric F0    ((η − 1)/(η + 1))²; η = 1.5 gives 0.04
```

Exact dielectric Fresnel with η = η_t/η_i, c = |v·h|, g² = η² − 1 + c² (g² < 0 is total internal
reflection, F = 1): F = ½ ((g − c)/(g + c))² (1 + ((c(g + c) − 1)/(c(g − c) + 1))²).

Conductor with complex IOR η = n + ik relative to the outside medium, cos_i = v·h, complex arithmetic:

```text
sin²_t = (1 − cos_i²)/η²;  cos_t = sqrt(1 − sin²_t)
r_par = (η cos_i − cos_t)/(η cos_i + cos_t);  r_perp = (cos_i − η cos_t)/(cos_i + η cos_t)
F = (|r_par|² + |r_perp|²)/2
```

Artist-friendly conductor (Gulbrandsen 2014), per channel from reflectivity r = F0 and edge tint g:
n = g (1 − r)/(1 + r) + (1 − g)(1 + √r)/(1 − √r), k = sqrt((r (n + 1)² − (n − 1)²)/(1 − r)); it maps
back to F(0) = r exactly for any g.

```glsl
float D_GGX(float NoH, float a2) { float d = NoH * NoH * (a2 - 1.0) + 1.0; return a2 / (PI * d * d); }
float V_SmithGGXCorrelated(float NoV, float NoL, float a2) {
    float gv = NoL * sqrt(NoV * NoV * (1.0 - a2) + a2);
    float gl = NoV * sqrt(NoL * NoL * (1.0 - a2) + a2);
    return 0.5 / (gv + gl);
}
vec3 F_Schlick(vec3 f0, float VoH) { return f0 + (1.0 - f0) * pow(1.0 - VoH, 5.0); }
vec3 specularBRDF(vec3 n, vec3 v, vec3 l, vec3 f0, float alpha) {    // caller multiplies by NoL
    float NoL = dot(n, l);
    if (NoL <= 0.0) return vec3(0.0);
    float NoV = max(dot(n, v), 1e-4);
    vec3 h = normalize(v + l);
    float a2 = alpha * alpha;
    return D_GGX(max(dot(n, h), 0.0), a2) * V_SmithGGXCorrelated(NoV, NoL, a2) * F_Schlick(f0, max(dot(v, h), 0.0));
}
```

## 3. Parameter mapping

glTF core (spec appendix B): F0 = mix(0.04, baseColor, metallic), c_diff = baseColor (1 − metallic),
α = roughness²; material = mix(dielectric, metal, metallic), dielectric = fresnel_mix(ior 1.5,
base = Lambert(baseColor), layer = GGX) = base (1 − F) + layer F, metal = GGX with F0 = baseColor.

| KHR extension | Parameters (texture channel) | Mapping |
|---|---|---|
| `KHR_materials_ior` | `ior` (1.5) | dielectric F0 = ((ior − 1)/(ior + 1))² |
| `KHR_materials_specular` | `specularFactor` (A), `specularColorFactor` (RGB, sRGB) | F0 = min(F0_ior · specularColor, 1) · specular; F90 = specular |
| `KHR_materials_transmission` | `transmissionFactor` (R) | diffuse replaced by specular transmission; thin-walled unless volume |
| `KHR_materials_volume` | `thicknessFactor` (G), `attenuationDistance`, `attenuationColor` | σ_a = −ln(attenuationColor)/attenuationDistance (Beer-Lambert) |
| `KHR_materials_clearcoat` | `clearcoatFactor` (R), `clearcoatRoughnessFactor` (G), coat normal | GGX layer at IOR 1.5: base (1 − c F_c) + c f_coat |
| `KHR_materials_sheen` | `sheenColorFactor` (RGB), `sheenRoughnessFactor` (A) | Charlie sheen on top; base scaled by 1 − max(sheenColor) E_sheen |
| `KHR_materials_iridescence` | factor (R), `iridescenceIor` (1.3), thickness 100-400 nm (G) | thin-film Fresnel (Belcour-Barla 2017) replaces F |
| `KHR_materials_anisotropy` | strength, rotation, texture (RG direction, B strength) | α_t = mix(α, 1, strength²), α_b = α |
| `KHR_materials_dispersion` | `dispersion` = 20/V_d (Abbe number) | per-wavelength IOR from the extension's Cauchy-style formula |

- Disney principled (Burley 2012): Cspec0 = mix(0.08 · specular · mix(1, tint, specularTint), baseColor,
  metallic), so specular 0.5 gives F0 0.04; α = roughness²; aspect = sqrt(1 − 0.9 anisotropic),
  αx = α/aspect, αy = α · aspect; clearcoat = GTR1 with α_c = mix(0.1, 0.001, clearcoatGloss), F0 0.04,
  weight 0.25 · clearcoat; diffuse uses the retro-reflective term with F_D90 = 0.5 + 2 r cos²θ_d.
- OpenPBR Surface 1.x (MaterialX 1.39 ships `open_pbr_surface`): base (metal or dielectric by
  `base_metalness`; dielectric = specular over transmission, subsurface or diffuse), `thin_film_*` on
  the specular interface, `coat_*` above it (`coat_ior` default 1.6, `coat_darkening`), `fuzz_*` on top,
  `geometry_thin_walled`. Build the node graph in MaterialX and use its GLSL/MSL/OSL/MDL generators
  instead of hand-porting the layering.
- Unreal: `Specular` (default 0.5) gives F0 = 0.08 · Specular for dielectrics, α = roughness²; Substrate
  in UE 5.x replaces the legacy shading models. Unity: α = (1 − smoothness)².

## 4. Sampling

```glsl
// Dupuy and Benyoub 2023 spherical caps: same distribution as Heitz 2018 VNDF. v in the local frame.
vec3 sampleGgxVndf(vec2 u, vec3 v, vec2 alpha) {
    vec3 wi = normalize(vec3(v.xy * alpha, v.z));            // stretch to the hemisphere configuration
    float phi = 2.0 * PI * u.x;
    float z = (1.0 - u.y) * (1.0 + wi.z) - wi.z;             // uniform on the spherical cap
    float s = sqrt(clamp(1.0 - z * z, 0.0, 1.0));
    vec3 hStd = vec3(s * cos(phi), s * sin(phi), z) + wi;
    return normalize(vec3(hStd.xy * alpha, hStd.z));         // unstretch
}
// l = reflect(-v, h); reject if l.z <= 0
// pdf(l) = G1(v) D(h) / (4 n·v)
// weight = f (n·l) / pdf = F(v·h) G2(v, l) / G1(v)          bounded by F
```

The classic distribution-of-normals sampler draws tan²θ_h = α² u1/(1 − u1), φ_h = 2π u2, with
pdf(h) = D(h)(n·h) and pdf(l) = D(h)(n·h)/(4 |v·h|). The 1/(4 |v·h|) reflection Jacobian is the term most
often lost (worked example in `path-tracer-implementation`); this sampler also has high variance at
grazing v, so prefer VNDF.

Lobe selection: pick a lobe with probability proportional to its estimated albedo at this v, then
always evaluate the whole mixture.

```cpp
const float wSpec = luminance(fresnelSchlick(f0, NoV)), wDiff = luminance(cDiff) * (1.0f - maxComponent(f0));
const float pSpec = wSpec / std::max(wSpec + wDiff, 1e-6f);
// sample: u0 < pSpec ? VNDF specular : cosine hemisphere (pdf cos/π)
// pdf(l) = pSpec * pdfSpec(l) + (1 - pSpec) * pdfDiff(l)   the mixture, also inside pdf() used by MIS
// f(l)   = fSpec(l) + fDiff(l)                             the sum of all lobes, whichever was sampled
```

## 5. Energy compensation

Single-scattering GGX loses energy as α grows. Build E_ss(μ, r) once: F = 1, α = r², 32 × 32 bins at
cell centres, 128 × 128 stratified VNDF samples per cell (2 s in NumPy):

```python
def build_ess_lut(n_mu=32, n_r=32, strata=128):
    g = (np.arange(strata) + 0.5) / strata
    u1, u2 = [a.ravel() for a in np.meshgrid(g, g, indexing="ij")]
    lut = np.zeros((n_r, n_mu))
    for j in range(n_r):
        for i in range(n_mu):   # vndf_weight = F G2 / G1(v) with F = 1, zero below the horizon
            lut[j, i] = vndf_weight((i + 0.5) / n_mu, ((j + 0.5) / n_r) ** 2, u1, u2).mean()
    return lut                  # ship as a 32 x 32 R16F texture; bilinear lookup at (mu, r)
```

- Turquin 2019 (real-time default): f = f_ss (1 + F0 (1 − E_ss(μ_o))/E_ss(μ_o)); one LUT; not reciprocal.
- Kulla-Conty 2017 (film, reciprocal): E_avg(α) = 2 ∫ E(μ) μ dμ; f_ms(μ_o, μ_i) = (1 − E(μ_o))(1 − E(μ_i))
  / (π (1 − E_avg)); F_avg = (20 F0 + 1)/21 for Schlick; add F_ms · f_ms with
  F_ms = F_avg² E_avg / (1 − F_avg (1 − E_avg)). With F = 1 the furnace then sums to exactly 1.

Golden E_ss values (height-correlated, F = 1; quadrature, cross-checked by 1e6-sample VNDF Monte Carlo):

| α | μ = 0.1 | μ = 0.5 | μ = 1.0 |
|---|---|---|---|
| 0.1 | 0.8835 | 0.9692 | 0.9883 |
| 0.5 | 0.8601 | 0.6983 | 0.6878 |
| 0.81 | 0.7985 | 0.5353 | 0.4200 |
| 1.0 | 0.7602 | 0.4507 | 0.3069 (= 1 − ln 2, analytic) |

Regression tolerance: ±0.003 at cell centres, ±0.005 for bilinear reads (clamping at the μ = 1 edge
reads 0.4225 instead of 0.4200). E_avg is 0.512 at r ≈ 0.89. For α ≥ 0.5 the loss is largest at normal
incidence, so a rough-metal furnace sphere is darkest in the middle and brighter at the rim.

## 6. Rough dielectric transmission (Walter 2007)

η_v and η_l are the IORs on the sides of v and of the sampled direction l.

```text
h_t       = ±normalize(η_v v + η_l l), oriented so that h_t·n > 0
f_t       = (|l·h_t| |v·h_t|)/(|l·n| |v·n|) · η_v² (1 − F(v·h_t)) G2 D(h_t) / (η_l (l·h_t) + η_v (v·h_t))²
dω_h/dω_l = η_l² |l·h_t| / (η_l (l·h_t) + η_v (v·h_t))²        pdf(l) = pdf(h_t) · dω_h/dω_l
VNDF h, transmit with probability (1 − F):  weight = (η_v/η_l)² · G2/G1(v)
```

- (η_v/η_l)² is the radiance scaling: a camera path entering glass (η_v = 1, η_l = 1.5) keeps 1/2.25 of
  its weight. Light tracing and photon mapping transport importance and omit it (PBRT-v4:
  `if (mode == TransportMode::Radiance) ft /= Sqr(etap)`). Mixing the conventions makes glass wrong by η².
- Thin-walled (leaves, paper, single-pane windows): no bending, no interior; smooth slab
  R' = R + T² R/(1 − R²), T' = 1 − R' (PBRT-v4 ThinDielectric); the transmitted direction is −v.
- Volumetric (solid glass, liquids): refract with f_t, track the interior medium and nested-dielectric
  priorities (`path-tracer-implementation`), absorb per `KHR_materials_volume` or OpenPBR transmission depth.

## 7. Real-time specifics

- Specular antialiasing (Kaplanyan 2016, Tokuyoshi-Kaplanyan 2019): widen α² by the screen-space normal
  variance; pixel-filter variance σ² ≈ 0.15-0.16 and clamp κ ≈ 0.18-0.2.

```glsl
float specularAAAlpha2(vec3 n, float alpha) {
    vec3 du = dFdx(n), dv = dFdy(n);
    float kernel = min(2.0 * 0.15 * (dot(du, du) + dot(dv, dv)), 0.18);
    return clamp(alpha * alpha + kernel, 0.0, 1.0);
}
```

- Mipped normal maps (Toksvig-style, vMF fit): from the unnormalised average normal length ρ̄ of a mip,
  κ = (3ρ̄ − ρ̄³)/(1 − ρ̄²) and α'² = α² + 2/κ; bake it into the roughness mip chain offline.
- Normal-map horizon fade: h = saturate(1 + 1.3 · dot(r, n_vertex)), specular *= h². Micro-shadowing from
  AO (Brinck-Maximov 2016): direct light *= saturate(|n·l| + 2 AO² − 1).
- Half precision: max 65504, smallest normal 6.1e-5. D(n) = 1/(πα²) overflows for α < 2.2e-3 and
  1 − (n·h)² cancels; use the Lagrange form D = (α/(|n × h|² + (n·h α)²))²/π and clamp r ≥ 0.089
  (α² = 6.3e-5, just above the denormal range).
- Split-sum IBL, prefiltered environments and the DFG LUT live in `realtime-global-illumination`.

## 8. Pitfalls

- Roughness used directly as α: lobes too wide, assets disagree with every other renderer.
- NaN from 1/(n·v) at grazing angles: clamp NoV to 1e-4, or use |n·v| with a geometric-normal check.
- Back-facing shading normals (direction above the geometric surface, below the shading normal): apply
  the Chiang 2019 terminator term g = min(1, (n_g·l)/((n_s·l)(n_g·n_s))), G = −g³ + g² + g, or bend the
  shading normal; never let the two normals disagree silently.
- Metallic applied twice to diffuse (c_diff already holds 1 − metallic): partial metals turn dark.
- F0 or baseColor left in sRGB: decode the texture before mix(0.04, baseColor, metallic).
- Specular lobe evaluated without the cosine: NEE needs f · NoL; only the VNDF weight folds it in.
- The chosen lobe's pdf used in MIS instead of the mixture pdf: biased and firefly-prone.
- Chi-square failures at grazing μ with tiny α can be under-resolved expected counts, not a bad sampler
  (harness notes).

## 9. Test harness

```python
def furnace(mu, alpha, n=100_000, seed=1):          # F = 1 gives E_ss; with compensation it must reach 1
    rng = np.random.default_rng(seed)
    w = vndf_weight(mu, alpha, rng.random(n), rng.random(n))
    return w.mean(), w.std() / np.sqrt(n)             # report mean and standard error

def random_hemisphere(rng, n):                        # uniform directions with z > 0
    z, phi = rng.random(n), 2 * np.pi * rng.random(n)
    s = np.sqrt(1 - z * z)
    return np.stack([s * np.cos(phi), s * np.sin(phi), z], 1)

def reciprocity_fuzz(f, n=100_000, seed=2):          # f(v, l) -> values; must return <= 1e-5
    rng = np.random.default_rng(seed)
    v, l = random_hemisphere(rng, n), random_hemisphere(rng, n)
    a, b = f(v, l), f(l, v)
    return np.max(np.abs(a - b) / np.maximum(np.maximum(np.abs(a), np.abs(b)), 1e-12))
```

Chi-square of `sample()` against `pdf()` for μ ∈ {0.05, 0.5, 1} × α ∈ {0.05, 0.3, 1}: 1e6 samples,
16 × 32 bins in (sqrt(1 − cos θ), φ), expected counts integrated on a 24 × 192 sub-grid per bin, bins with
expected count < 5 pooled, reject at p < 0.01/9 (Bonferroni). Also check that ∫ pdf dω equals the
acceptance rate and that the pdf returned by `sample()` equals `pdf()` within 1e-4 relative. Recorded:
all nine VNDF cases pass (p from 0.027 to 0.60). For production code reuse Mitsuba 3's `mitsuba.chi2`
(`ChiSquareTest`, `BSDFAdapter`, `SphericalDomain`; check argument names for your version) or the
PBRT-v4 BSDF tests.

## 10. Worked example: a roughness 0.9 metal renders too dark

1. Furnace with F0 = 1, α = 0.81: the sphere converges to 0.4200 at the centre (μ = 1), 0.5353 at
   μ = 0.5 and 0.7985 at μ = 0.1 (VNDF Monte Carlo 0.4199 ± 0.0004). These match the golden table, so
   sampling is correct and the darkening is single-scattering energy loss.
2. Build the 32 × 32 E_ss LUT and ship it as a texture or a constant array.
3. Multiply the specular lobe by 1 + F0 (1 − E_ss)/E_ss with E_ss = LUT(μ_o, r).
4. Re-run the furnace: 0.9941 (μ = 1), 0.9998 (μ = 0.5), 0.9991 (μ = 0.1). The residual 0.6% at normal
   incidence comes from bilinear clamping at the last μ cell (0.984); 64 μ bins or a μ axis that
   includes 1.0 removes it.
5. Output contract: root cause (missing multiple scattering, not a sampling bug); evidence (furnace
   0.420/0.535 before and 0.994/1.000 after, golden-table match); fix (Turquin LUT, or Kulla-Conty when a
   bidirectional renderer needs reciprocity); residual bias 0.6% at μ = 1; clamps none.

Related: `importance-sampling-mis-restir`, `path-tracer-implementation`, `realtime-global-illumination`, `color-pipeline-tonemapping`, `denoising-taa-upscaling`, hub `computer-graphics`
