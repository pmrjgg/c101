---
name: importance-sampling-mis-restir
description: "Monte Carlo sampling for rendering covering estimator variance and efficiency, measure conversions, light sampling (cones, spherical triangles and rectangles, env-map CDFs), MIS heuristics, Owen-scrambled Sobol and blue noise, many-light selection (alias tables, light BVH) and RIS/ReSTIR DI/GI/PT with unbiased reuse. Load when noise, fireflies or bias trace back to how samples and weights are chosen."
when_to_use: "Fireflies or noise that does not fall as 1/sqrt(spp); BSDF-only, light-only and MIS renders that disagree; area vs solid-angle pdf confusion; environment-map importance sampling; thousands of emissive triangles; alias tables, light trees or lightcuts; Sobol, Halton or blue-noise dimension bugs; implementing or debugging RIS, ReSTIR DI/GI/PT or RTXDI reservoirs; boiling or darkening after spatiotemporal reuse."
---

# Importance sampling, MIS and ReSTIR

Rule zero: change one estimator at a time and compare at equal time against a converged reference with
a numeric metric; a less noisy image whose mean moved is a bug, not a win. Experiment code and recorded
output: [references/restir-toy.md](references/restir-toy.md).

## 1. Estimator core

```text
F_N = (1/N) Σ f(X_k)/p(X_k)        unbiased iff p(x) > 0 wherever f(x) ≠ 0
Var[F_N] = σ²/N, σ² = ∫ f²/p dx − I²;  stderr = σ/√N;  zero variance at p* = |f| / ∫|f|
efficiency = 1 / (variance × time)  compare strategies at equal time, never at equal spp
```

| Measure conversion | Formula |
|---|---|
| area to solid angle | p_ω = p_A d² / abs(cos θ_l), θ_l at the light between its normal and −ω |
| lat-long environment, u ↦ φ = 2πu, v ↦ θ = πv | p_ω = p_uv / (2π² sin θ) |
| discrete light choice | p(y) = P(light j) · p(y given j), both factors in the same measure |
| delta lights, specular (delta) lobes | no density: the strategy that samples them gets MIS weight 1, no other strategy can hit them |

| Symptom | Usual estimator bug |
|---|---|
| fireflies at grazing angles or near small lights | pdf too small somewhere: Jacobian missing, wrong measure |
| too bright near lights | double counting: NEE and BSDF hits both at full weight |
| too dark in one lighting regime | p = 0 where f ≠ 0 (black env texels, culled lights) |
| structured patterns, correlated noise | one random dimension used for two decisions |

## 2. Light sampling

| Light | Strategy | pdf |
|---|---|---|
| point, spot, directional | deterministic | delta (MIS weight 1) |
| sun disk, angular radius θ_s | uniform cone: cos θ = 1 − u1 (1 − cos θ_s), φ = 2π u2 | 1/(2π (1 − cos θ_s)) |
| sphere, radius r, centre distance d > r | uniform cone with cos θ_max = sqrt(1 − (r/d)²) | 1/(2π (1 − cos θ_max)); area sampling when inside |
| triangle, uniform area | b0 = 1 − sqrt(u1), b1 = u2 sqrt(u1) | p_A = 1/A, p_ω = d²/(A abs(cos θ_l)) |
| triangle, spherical (Arvo 1995) | PBRT-v4 `SampleSphericalTriangle` | 1/Ω |
| rectangle, spherical (Ureña 2013) | PBRT-v4 `SampleSphericalRectangle` | 1/Ω |
| environment | 2D piecewise-constant CDF weighted by sin θ | p_uv/(2π² sin θ) |
| many lights | alias table or light tree, then the per-light pdf | P(j) p(y given j) |

Triangle solid angle from unit vertex directions a, b, c (Van Oosterom-Strackee):
tan(Ω/2) = |a·(b × c)| / (1 + a·b + b·c + c·a). Area sampling has a d² singularity near the light;
spherical sampling removes it but loses precision for tiny Ω, so fall back to area sampling there
(PBRT-v4 switches below about 3e-4 sr).

```cpp
struct EnvSampler {                       // lat-long W x H luminance; row y covers theta in [y, y+1) pi/H
  int W, H; float total;
  std::vector<float> cond, marg, rowSum;  // cond: H rows of W+1 CDF entries; marg: H+1 entries
  EnvSampler(const float* lum, int w, int h) : W(w), H(h), cond(size_t(h) * (w + 1)), marg(h + 1), rowSum(h) {
    for (int y = 0; y < H; ++y) {
      const float s = std::sin(PI * (y + 0.5f) / H);          // solid-angle weight of the row
      float* c = &cond[size_t(y) * (W + 1)];
      c[0] = 0.0f;
      for (int x = 0; x < W; ++x) c[x + 1] = c[x] + lum[size_t(y) * W + x] * s;
      rowSum[y] = c[W];
      for (int x = 1; x <= W; ++x) c[x] = rowSum[y] > 0.0f ? c[x] / rowSum[y] : float(x) / W;
    }
    marg[0] = 0.0f;
    for (int y = 0; y < H; ++y) marg[y + 1] = marg[y] + rowSum[y];
    total = marg[H];
    for (int y = 1; y <= H; ++y) marg[y] /= total;
  }
  // p_uv(texel x, y) = W * H * lum(x, y) * sin(theta_row) / total. Sample y from marg (binary search),
  // x from row y, jitter inside the texel; pdf_omega = p_uv / (2 pi^2 sin(theta of the sample)).
  // pdf() must reuse exactly these numbers. Mix in 5-10% uniform sampling if visible texels are black.
};
```

## 3. Multiple importance sampling

```text
balance      w_i = n_i p_i / Σ_k n_k p_k
power (β=2)  w_i = (n_i p_i)² / Σ_k (n_k p_k)²           default (Veach 1997)
NEE + BSDF   L += w_l f Le |cos| / p_l (light sample) + w_b f Le |cos| / p_b (BSDF ray that hits a light)
one-sample   choose strategy i with probability c_i;  F = f(X) / Σ_k c_k p_k(X)
defensive    p = (1 − ε) p_good + ε p_safe, ε ≈ 0.05-0.1, keeps p > 0 wherever f ≠ 0
```

Both weights of a pair are evaluated for the same direction, in solid angle, and p_l includes the
light-selection probability P(j) that the sampler would use from that shading point.

```cpp
inline float powerHeuristic(float pa, float pb) {     // delta strategies are handled before this call
  const float a = pa * pa, b = pb * pb;
  return a + b > 0.0f ? a / (a + b) : 0.0f;
}
```

Regression test: render BSDF-only, light-only and MIS with fixed seeds; the three image means agree
within 3 standard errors and 32 × 32 tile means give z-scores that look like N(0, 1). A mismatch means a
missing P(j), a measure mismatch, or a strategy that cannot reach part of f.

## 4. Sample sequences and dimension budgeting

```cpp
uint32_t laineKarras(uint32_t x, uint32_t seed) {     // Burley 2020, hash-based Owen scrambling
  x += seed; x ^= x * 0x6c50b47cu; x ^= x * 0xb82f1e52u; x ^= x * 0xc7afe638u; x ^= x * 0x8d22f6e6u;
  return x;
}
uint32_t owen(uint32_t x, uint32_t seed) { return reverseBits(laineKarras(reverseBits(x), seed)); }
uint32_t sobol0(uint32_t i) { return reverseBits(i); }
uint32_t sobol1(uint32_t i) { uint32_t r = 0; for (uint32_t v = 1u << 31; i; i >>= 1, v ^= v >> 1) if (i & 1) r ^= v; return r; }
float2 sample2D(uint32_t i, uint32_t pixelSeed, uint32_t pair) {   // padding: shuffle the index per pair
  const uint32_t s = hash(pixelSeed, pair), idx = owen(i, s);
  return float2(owen(sobol0(idx), hash(s, 1)) >> 8, owen(sobol1(idx), hash(s, 2)) >> 8) * 0x1p-24f;
}
```

- Owen-scrambled Sobol is the production default (power-of-two spp; error falls faster than 1/√N on
  smooth low-dimensional integrands). Scrambled Halton suits open-ended progressive rendering.
- Spatiotemporal blue noise masks (STBN, Wolfe et al. 2022), indexed by pixel modulo the tile size and
  frame modulo the depth, for 1-4 spp real-time paths before accumulation or denoising; never for references.
- Fixed dimension map: camera 2, lens 2, time 1, then per bounce b at offset 5 + 7b: light select 1,
  light position 2, lobe select 1, BSDF direction 2, roulette 1. One dimension never serves two decisions.
- Seeds: pixelSeed = hash(x, y, frameSeed); progressive renders continue the sample index across frames.

## 5. Many-light selection

```cpp
struct Alias { std::vector<float> prob, pmf; std::vector<uint32_t> alias; };
Alias buildAlias(const std::vector<float>& w) {       // Vose: O(n) build, O(1) sample
  const size_t n = w.size();
  const double sum = std::accumulate(w.begin(), w.end(), 0.0);
  Alias t{std::vector<float>(n, 1.0f), std::vector<float>(n), std::vector<uint32_t>(n)};
  std::vector<double> p(n);
  std::vector<uint32_t> small, large;
  for (size_t i = 0; i < n; ++i) {
    t.pmf[i] = float(w[i] / sum); p[i] = w[i] * n / sum; t.alias[i] = uint32_t(i);
    (p[i] < 1.0 ? small : large).push_back(uint32_t(i));
  }
  while (!small.empty() && !large.empty()) {
    const uint32_t s = small.back(), l = large.back();
    small.pop_back(); large.pop_back();
    t.prob[s] = float(p[s]); t.alias[s] = l; p[l] = (p[l] + p[s]) - 1.0;
    (p[l] < 1.0 ? small : large).push_back(l);
  }
  return t;                                            // leftovers keep prob 1 (round-off)
}
uint32_t sampleAlias(const Alias& t, float u1, float u2) {   // P(i) = t.pmf[i], needed for MIS
  const uint32_t i = std::min(uint32_t(u1 * t.prob.size()), uint32_t(t.prob.size() - 1));
  return u2 < t.prob[i] ? i : t.alias[i];
}
```

- Weights: emitted power Φ = π Le A for one-sided Lambertian emitters (twice that if two-sided); drop
  zero-power lights.
- Light BVH (Conty Estevez-Kulla 2018): nodes store bounds, Φ and an orientation cone (axis, θ_o normal
  spread, θ_e emission spread). Importance I = Φ |cos θ'_i| cos θ' / d² with θ' = max(0, θ − θ_o − θ_u)
  (zero once θ' ≥ θ_e), θ'_i = max(0, θ_i − θ_u), θ_u the angle subtended by the bounds, d clamped to
  their radius. Descend stochastically with P(child) ∝ I; P(light) is the product of the choices, and
  pdf() must replay the same descent for MIS.
- Lightcuts (Walter 2005): deterministic cuts with an error bound of about 2%; scalable offline, biased.
- The selection probability always multiplies into the light pdf used by NEE and by the emissive-hit
  MIS weight.

## 6. RIS in GRIS notation

Candidates x_1..x_M from source pdfs, target p̂, MIS weights m_i that sum to 1 (simplest 1/M):

```text
w_i = m_i p̂(x_i) W_i             W_i = 1/p_i(x_i) for a fresh candidate
select y = x_s with P(s) ∝ w_s
W_y = (1/p̂(y)) Σ_i w_i            contribution weight; estimate f(y) W_y
```

Unbiased when p̂ is positive wherever f is (or the candidates cover f's support) and the m_i form a
partition of unity (Talbot 2005, Lin et al. 2022). Direct-light target: unshadowed p̂ = f_bsdf Le G with
G = |cos θ_x| |cos θ_l| / d² in area measure; trace one shadow ray for the survivor instead of M.

## 7. ReSTIR DI (Bitterli 2020)

```hlsl
struct Reservoir { uint y; float wSum; float M; float W; };
bool update(inout Reservoir r, uint x, float w, float u) {
    r.wSum += w; r.M += 1;
    if (u * r.wSum < w) { r.y = x; return true; }
    return false;
}
// initial RIS: for 32 candidates: x = sampleLight(); update(r, x, pHat(x) / p(x), rnd());
//              r.W = pHat(r.y) > 0 ? r.wSum / (r.M * pHat(r.y)) : 0;
// visibility reuse: if (!visible(r.y)) r.W = 0;
// combine inputs r_i into s at pixel q: update(s, r_i.y, pHat_q(r_i.y) * r_i.W * r_i.M, rnd()); s.M = sum of r_i.M
//   1/M: s.W = s.wSum / (s.M * pHat_q(s.y))
//   1/Z: Z = sum of r_i.M over inputs whose domain could produce s.y (pHat_i(s.y) > 0, visible from q_i)
//        s.W = s.wSum / (Z * pHat_q(s.y))
```

- Temporal: reproject with motion vectors; keep history only when view depth differs by < 10%, normals
  by < 25° and the material or object ID matches; cap the history M at 20 × the current M.
- Spatial: 3-5 neighbours within 30 px (Bitterli used 5 for the unbiased variant) under the same
  similarity tests, no duplicate taps, a per-pixel rotated low-discrepancy pattern.
- Store the post-spatial reservoir for the next frame; the final shading ray can zero its W (final
  visibility reuse) so stored reservoirs stay inside the visible support.

| Normalisation | Extra cost | Bias |
|---|---|---|
| 1/M | none | darkens where neighbour supports differ (visibility, BSDF hemisphere, geometry) |
| 1/Z (Bitterli 2020) | one shadow ray per neighbour | unbiased |
| pairwise MIS (Bitterli 2022, Lin et al. 2022) | O(k) target evaluations | unbiased, robust to a bad canonical sample |
| generalized balance heuristic | O(k²) | unbiased, lowest variance |

Production path: RTXDI (NVIDIA) implements these passes with selectable bias-correction modes and a
boiling filter; option names change between SDK versions, so read the version you ship.

## 8. ReSTIR GI and ReSTIR PT

- ReSTIR GI (Ouyang 2021): the sample is a reconnection vertex x_s with normal n_s and outgoing radiance
  L_o(x_s); p̂ is its luminance, optionally times the visible point's BSDF and cosine. Reusing a sample
  from source pixel 1 at destination pixel 2 keeps x_s and changes the direction, with Jacobian
  |J| = (|cos θ_2| / |cos θ_1|) · (d_1² / d_2²), θ_k the angle at x_s between n_s and the direction to
  pixel k's visible point and d_k that distance. Resampling weight w = m p̂_2(y) W_1 |J|. Reject tiny d_2
  (J explodes) and trace x_v2 → x_s for visibility in the unbiased variant.
- ReSTIR PT (Lin et al. 2022) resamples whole path suffixes through shift mappings:

| Shift | Mechanism | Good for | Fails on |
|---|---|---|---|
| random replay | reuse the source path's random numbers from the new primary hit | glossy and specular chains | long diffuse paths (decorrelates) |
| reconnection | connect to the source path's vertex x_k | rough and diffuse surfaces | specular vertices, short connection edges |
| hybrid | replay until two consecutive vertices are rough and far enough apart, then reconnect | general scenes | needs roughness and distance thresholds |

- Boiling (blotchy correlated flicker): lower the M-cap (5-10× for GI), shrink the spatial radius, drop a
  spatial pass, use pairwise MIS, and tune the denoiser for correlated input (shorter history, NRD ReLAX
  for ReSTIR signals); never hide it with clamps.

## 9. Diagnostics

- Chi-square for every BSDF and light sampler (bins in (sqrt(1 − cos θ), φ), Bonferroni threshold; see
  `pbr-microfacet-brdf`) plus a pointwise check: the pdf returned by `sample()` equals `pdf()` for the
  returned direction within 1e-4 relative.
- Per-pixel variance images from 64 independent 1-spp frames, saved as EXR or PFM under the agent out_dir.
- relMSE = mean((x − r)²/(r² + ε)) with ε = 1e-2 after scaling the reference to mean 1; plus FLIP crops.
- Log-log RMSE vs spp: slope −0.5 for independent samples (steeper early for QMC); a flattening curve
  means bias. Judge bias over several seeds, because reservoirs correlate pixels and frames.

## 10. Pitfalls

- Mixing area and solid-angle pdfs inside one MIS weight.
- P(light) in the NEE pdf but not in the emissive-hit MIS weight, or the reverse.
- One random dimension serving two decisions (light select and lobe select).
- Dividing by a zero pdf: test pdf > 0 before f/p, so a valid zero contribution never becomes NaN.
- Temporal reservoirs reused across disocclusions, camera cuts or lighting changes: lag, ghost lights,
  lost energy.
- Uncapped M: stale samples dominate and the image stops reacting.
- Judging the bias of a correlated estimator from one seed's mean.

## 11. Worked example: 10k emissive triangles at 1 spp

Toy model from the reference: 10,000 one-sided emitters (power max/median 2,868) above a Lambert floor,
12 occluders shadowing 47% of light-point pairs, 64 × 64 pixels, an exact reference, relMSE averaged
over 16 frames after 8 warm-up frames. Cost proxy: shadow rays per pixel, candidates treated as free.

| Strategy | Shadow rays/px | Candidates/px | relMSE | Mean bias |
|---|---|---|---|---|
| uniform selection | 1 | 1 | 345.2 | −4.6% (noise) |
| power alias table | 1 | 1 | 5.69 | −0.1% |
| power alias table, 2 samples | 2 | 2 | 2.76 | +0.3% |
| power alias table, 7 samples | 7 | 7 | 0.789 | +0.2% |
| RIS, 32 candidates | 1 | 32 | 1.60 | +0.1% |
| ReSTIR DI temporal + spatial, no visibility reuse | 1 | 38 | 1.45 | +1.0% |
| same with visibility reuse, 1/M | 2 | 38 | 0.258 | −35.8% |
| same with visibility reuse, 1/Z | 7 | 38 | 0.559 | +3.0% (noise) |

Over 12 more seeds with 48 frames each, the mean bias was +0.07% ± 0.45% for 1/Z and −0.04% ± 0.62%
without visibility reuse (both unbiased); the 1/M variant was off by −27% to −43% on every seed tried.

Reading:
- Power-proportional selection beats uniform by 60×; RIS-32 gains another 3.5× at the same ray count.
- Reuse with an unshadowed target barely helps when visibility dominates the variance.
- Visibility reuse cuts relMSE 6× below RIS, but with 1/M it darkens the image by a third: toy neighbours
  0.8 m apart see different occluders. Screen-space neighbours are closer in real scenes, so the bias is
  smaller there but has the same sign.
- 1/Z restores the mean for 5 extra rays and still beats 7 alias samples by 1.4×.

On a GPU, repeat the comparison at equal milliseconds: time each configuration with timestamp queries
at the target resolution (median of 100 frames), give the baselines as many samples as fit in the
ReSTIR budget (relMSE scales as 1/spp for independent samples), and save the relMSE table and variance
images.

Related: `pbr-microfacet-brdf`, `path-tracer-implementation`, `denoising-taa-upscaling`, `realtime-global-illumination`, `bvh-build-traversal`, hub `computer-graphics`
