# BRDF and sampling formulas

Conventions: shading frame with n = (0,0,1); v = ω_o (towards the viewer), l = ω_i (towards the light),
both unit and pointing away from the surface; h = normalize(v + l); μ = cosθ = z component.
All pdfs are per unit solid angle unless marked p_A (per unit area).

## 1. Diffuse

```
f_lambert = ρ / π
cosine hemisphere sampling:  r = sqrt(u1), φ = 2π u2, l = (r cosφ, r sinφ, sqrt(1 - u1))
pdf(l) = cosθ_l / π
weight f cos / pdf = ρ
```

Prefer the concentric (Shirley-Chiu) disk map followed by projection up (Malley's method) when
stratification matters: it preserves sample-point adjacency.

## 2. GGX microfacet (isotropic and anisotropic)

```
D(h)      = α² / (π ((n·h)² (α² - 1) + 1)²)
D_aniso(h)= 1 / (π αx αy ((hx/αx)² + (hy/αy)² + hz²)²)
Λ(ω)      = (-1 + sqrt(1 + α(ω)² tan²θ_ω)) / 2,  α(ω)² = αx² cos²φ + αy² sin²φ  (isotropic: α²)
G1(ω)     = 1 / (1 + Λ(ω))
G2 height-correlated = 1 / (1 + Λ(v) + Λ(l))        (preferred)
G2 separable          = G1(v) G1(l)                  (slightly darker, older engines)
f_spec    = D G2 F / (4 (n·l)(n·v))
```

Real-time visibility form (height-correlated, Filament style), V = G2 / (4 (n·l)(n·v)):

```
V = 0.5 / ( NdotL * sqrt(NdotV² (1 - α²) + α²) + NdotV * sqrt(NdotL² (1 - α²) + α²) )
```

Fresnel:
- Schlick: F = F0 + (1 - F0)(1 - (v·h))^5. Fine for conductors via RGB F0 and dielectrics with η ≈ 1.3-1.7.
- Exact dielectric (unpolarised), with c = |v·h| and g² = η² - 1 + c² (total internal reflection if g² < 0, F = 1):

```
F = 0.5 ((g - c)/(g + c))² (1 + ((c (g + c) - 1)/(c (g - c) + 1))²)
```

- Conductors with measured complex IOR (n, k) per wavelength: use the full conductor Fresnel or
  the Gulbrandsen 2014 artist-friendly mapping (reflectivity + edge tint).

Energy-loss reference values (height-correlated GGX, F0 = 1, directional albedo E_ss(μ)),
numerically integrated with VNDF sampling, 1e5 samples each:

| α | μ = 0.1 | μ = 0.5 | μ = 1.0 |
|---|---|---|---|
| 0.1 | 0.88 | 0.97 | 0.99 |
| 0.5 | 0.86 | 0.70 | 0.69 |
| 0.81 | 0.80 | 0.54 | 0.42 |
| 1.0 | 0.76 | 0.45 | 0.31 |

Use these as regression values for your own E_ss LUT.

Multiple-scattering compensation:
- Turquin 2019: f_total = f_ss · (1 + F0 (1 - E_ss(μ_o)) / E_ss(μ_o)). One 2D LUT (μ, α). Cheap, real-time.
- Kulla-Conty 2017: f_ms = (1 - E(μ_o))(1 - E(μ_i)) / (π (1 - E_avg)), times a Fresnel term
  F_avg² E_avg / (1 - F_avg (1 - E_avg)). Reciprocal, used in film renderers.

## 3. Sampling GGX

### 3a. Distribution of normals (classic, high variance at grazing)

```
tan²θ_h = α² u1 / (1 - u1),  φ_h = 2π u2
pdf(h)  = D(h) (n·h)
pdf(l)  = pdf(h) / (4 |v·h|)          reflection Jacobian
```

### 3b. Visible normals, spherical-cap method (Dupuy and Benyoub 2023)

Validated against Heitz 2018 (identical albedo tables above). GLSL-style pseudocode:

```glsl
vec3 sampleVndfHemisphere(vec2 u, vec3 wi) {       // wi: stretched view dir, unit, z > 0
    float phi = 2.0 * PI * u.x;
    float z = (1.0 - u.y) * (1.0 + wi.z) - wi.z;     // uniform on spherical cap
    float s = sqrt(clamp(1.0 - z * z, 0.0, 1.0));
    vec3 c = vec3(s * cos(phi), s * sin(phi), z);
    return c + wi;                                   // unnormalised half-vector
}
vec3 sampleGgxVndf(vec2 u, vec3 v, vec2 alpha) {
    vec3 wiStd = normalize(vec3(v.xy * alpha, v.z));
    vec3 hStd  = sampleVndfHemisphere(u, wiStd);
    return normalize(vec3(hStd.xy * alpha, hStd.z));
}
// l = reflect(-v, h); reject if l.z <= 0
// pdf(l) = G1(v) D(h) / (4 n·v)
// weight f cos / pdf = F(v·h) * G2(v,l) / G1(v)
```

Heitz 2018 (Sampling the GGX Distribution of Visible Normals, JCGT) gives the original
polar-coordinate version with the same pdf; either is fine, the cap version is shorter and faster.

### 3c. Lobe selection

For a layered material (diffuse + specular + coat), pick a lobe with probability proportional to
an estimate of its albedo (e.g. Fresnel at v·n times tint luminance), then evaluate the full
mixture pdf `Σ_k P(k) pdf_k(l)` for MIS. Using only the chosen lobe's pdf is the single most common
source of bias in hand-written materials.

## 4. Transmission (rough dielectric, Walter et al. 2007)

```
h_t = -normalize(η_i l + η_o v)          generalized half-vector, oriented to n
f_t = (|l·h||v·h| / (|l·n||v·n|)) · η_o² (1 - F) G2 D / (η_i (l·h) + η_o (v·h))²
dω_h / dω_o = η_o² |v·h| / (η_i (l·h) + η_o (v·h))²
```

When tracing from the camera, radiance crossing an interface scales by (η_t/η_i)² and importance
does not; mixing the two conventions makes glass too bright or too dark by η².

## 5. Light sampling

| Light | Sampling | pdf |
|---|---|---|
| Point / spot | deterministic | delta (no MIS) |
| Directional (sun as delta) | deterministic | delta |
| Sun with angular radius θ_s | uniform cone | 1 / (2π (1 - cos θ_s)) |
| Sphere radius r at distance d | uniform cone, cos θ_max = sqrt(1 - (r/d)²) | 1 / (2π (1 - cos θ_max)) |
| Triangle (area) | b0 = 1 - sqrt(u1), b1 = u2 sqrt(u1) | p_A = 1/A, p_ω = p_A d² / abs(cos θ_light) |
| Triangle (better) | spherical triangle sampling (Arvo 1995) | 1 / solid angle |
| Rectangle | spherical rectangle (Ureña 2013) | 1 / solid angle |
| Environment | 2D piecewise-constant CDF over (u, v) weighted by sinθ | p_uv / (2π² sinθ) |
| Many lights | light BVH (Conty-Kulla 2018), alias table over power, or ReSTIR | product of selection prob and per-light pdf |

Area-measure shortcuts break at small d (pdf explodes); solid-angle sampling of spheres and
spherical triangles avoids the singular d² factor.

## 6. Path tracer skeleton with NEE and MIS

```
L = 0; β = 1; ray = camera ray; prev_pdf_bsdf = 0; prev_specular = true
for bounce in 0..max_depth:
    hit = intersect(ray)
    if miss: L += β * w_env(prev_pdf_bsdf, prev_specular) * Le_env(ray.d); break
    if hit is emissive:
        w = prev_specular ? 1 : power_heuristic(prev_pdf_bsdf, pdf_light_solid_angle(hit))
        L += β * w * Le(hit)
    # next-event estimation
    (ls, pdf_l) = sample_light(hit)               # includes light-selection probability
    if pdf_l > 0 and visible(hit, ls):
        f = bsdf.eval(v, ls.dir) * |n·ls.dir|
        w = ls.is_delta ? 1 : power_heuristic(pdf_l, bsdf.pdf(v, ls.dir))
        L += β * w * f * ls.Le / pdf_l
    # continue path
    (l, pdf_b, f, specular) = bsdf.sample(v)
    if pdf_b == 0: break
    β *= f * |n·l| / pdf_b
    prev_pdf_bsdf = pdf_b; prev_specular = specular
    if bounce >= 3:
        q = min(1, max(β.r, β.g, β.b)); if rand() > q: break; β /= q
    ray = spawn_ray(hit, l)                      # robust offset, not epsilon
```

The emissive-hit MIS weight and the NEE weight must use the same light-selection probability and
the same measure; test by rendering a scene twice with only BSDF sampling and only light sampling
(both unbiased, same mean) and then with MIS (same mean, lower variance).

## 7. Testing a sampler (chi-square)

1. Fix v (several angles including grazing μ = 0.05) and α (0.05, 0.3, 1.0).
2. Draw N = 1e6 samples, bin l into a (cosθ, φ) grid, e.g. 32 × 64.
3. Expected count per bin = N × ∫_bin pdf(l) dω, integrated numerically (adaptive Simpson or 16×16
   sub-samples per bin). Merge bins with expected count < 5.
4. Pearson χ² with dof = bins - 1. Reject if p < 0.01 / (number of tests) (Bonferroni).
5. Also check ∫ pdf dω = 1 - (probability of rejected samples), and that `sample()` and `pdf()`
   agree pointwise on the returned direction (relative error < 1e-4).

Mitsuba 3 ships a ChiSquareTest helper; PBRT-v4 has equivalent unit tests. Reuse them rather than
writing a new statistical harness.

## 8. Sample sequences

| Sequence | Use | Note |
|---|---|---|
| Independent uniform | debugging | slowest convergence |
| Stratified / jittered | small dimension counts | curse of dimensionality |
| Halton (scrambled) | progressive, many dimensions | correlations in high bases without scrambling |
| Sobol, Owen-scrambled (Burley 2020 hash) | production default | RMSE down to O(N^-1.5) for smooth low-dimensional integrands vs O(N^-0.5) random; still a clear win on discontinuous pixel integrals; use power-of-two sample counts |
| Blue-noise dithered (Heitz-Belcour 2019, spatiotemporal blue noise) | real-time 1-4 spp | perceptually better error distribution, pairs well with denoisers |

Assign dimensions deterministically per bounce (camera 2, lens 2, then per bounce: light select 1,
light 2, BSDF lobe 1, BSDF 2, roulette 1) so the same dimension never serves two decisions.
