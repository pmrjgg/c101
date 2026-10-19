---
name: sdf-modeling-raymarching
description: "Signed distance fields for modeling and rendering: exact 2D/3D primitives and operators, smooth blends, domain repetition and deformation with Lipschitz bounds, sphere tracing with relaxation, normals, soft shadows and AO, mesh/SDF conversion, sparse SDF storage, and MSDF text rendering. Load for raymarched scenes, procedural modeling, SDF collisions, or SDF fonts and UI."
when_to_use: "Raymarched or Shadertoy-style scenes showing holes, banding, stalls or slow frames; writing SDF primitives, smooth unions, domain repetition, twists or bends; soft shadows and AO from distance fields; SDF to mesh (marching cubes, dual contouring, surface nets) or mesh to SDF (winding numbers, OpenVDB, NanoVDB, brick maps); SDF collision queries; MSDF/MTSDF fonts and UI with msdfgen or msdf-atlas-gen."
---

# SDF modeling and raymarching

Rule zero: the field you march must be 1-Lipschitz (|d(p) - d(q)| <= |p - q|). Check it
numerically (section 9) before tuning epsilons, step counts or relaxation.
Hub: `computer-graphics` section 9. Reproducible worked example: [twisted-column experiment](references/twisted-columns-experiment.md)

## 1. Primitives and operators

```glsl
float sdSphere(vec3 p, float r) { return length(p) - r; }
float sdBox(vec3 p, vec3 b) { vec3 q = abs(p) - b; return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0); }
float sdRoundBox(vec3 p, vec3 b, float r) {      // b = outer half-size, r = edge radius
  vec3 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0) - r; }
float sdCapsule(vec3 p, vec3 a, vec3 b, float r) {
  vec3 pa = p - a, ba = b - a; float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h) - r; }
float sdTorus(vec3 p, vec2 t) { vec2 q = vec2(length(p.xz) - t.x, p.y); return length(q) - t.y; }
float sdPlane(vec3 p, vec3 n, float h) { return dot(p, n) + h; }          // |n| = 1
float sdBox2(vec2 p, vec2 b) { vec2 d = abs(p) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }
float opU(float a, float b) { return min(a, b); }
float opI(float a, float b) { return max(a, b); }
float opS(float a, float b) { return max(a, -b); }                        // A minus B
float sminQ(float a, float b, float k) { float h = max(k - abs(a - b), 0.0) / k; return min(a, b) - h * h * k * 0.25; }
float sminC(float a, float b, float k) { float h = max(k - abs(a - b), 0.0) / k; return min(a, b) - h * h * h * k / 6.0; }
float sminE(float a, float b, float k) { return -k * log2(exp2(-a / k) + exp2(-b / k)); }
```

| Operation | Distance quality | Notes |
|---|---|---|
| sphere, box, round box, capsule, torus, plane | exact | |
| union min | exact outside, bound inside | |
| intersection max, subtraction max(a, -b) | exact inside, bound outside | |
| smooth min (quadratic, cubic, exponential) | bound, still 1-Lipschitz | gradient weights sum to 1; max deviation at a = b: k/4, k/6, k |
| rounding d - r, onion abs(d) - t | exact outside, bound inside | from an exact d |

Bounds are safe to march (they never overestimate) but converge slower, and soft shadows, AO
and collision offsets read them as distances, so they come out too dark or too thick.

## 2. Domain operations

| Operation | Code | Result |
|---|---|---|
| rigid transform | d(R^T (p - t)) | exact |
| uniform scale s | d(p / s) * s | exact |
| non-uniform scale | d(p / s) * min(s.x, s.y, s.z) | bound |
| infinite repetition | q = p - s * round(p / s) | exact only for symmetric content well inside its cell; else check neighbours |
| limited repetition | q = p - s * clamp(round(p / s), -l, l) | same |
| mirror | p.x = abs(p.x) | exact if content does not cross the plane |
| twist about y, rate k | rotate p.xz by k * p.y | not Lipschitz 1: L = (s + sqrt(s^2 + 4)) / 2 with s = k * rho_max (shear bound) |
| bend, displacement d + h(p) | | displacement: L <= 1 + Lip(h); bend: estimate L by sampling |

```glsl
vec3 opTwistY(vec3 p, float k) { float c = cos(k * p.y), s = sin(k * p.y); return vec3(c * p.x - s * p.z, p.y, s * p.x + c * p.z); }
float repNeighbours(vec3 p, float s) {          // asymmetric content: own cell + neighbour toward p
  vec3 id = round(p / s), o = sign(p - s * id);
  float d = 1e20;
  for (int k = 0; k < 2; ++k) for (int j = 0; j < 2; ++j) for (int i = 0; i < 2; ++i) {
    vec3 rid = id + vec3(i, j, k) * o;
    d = min(d, sdCell(p - s * rid, rid));
  }
  return d;
}
```

For non-Lipschitz operators divide the affected sub-tree, not the whole scene, by L, and wrap
it in a bounding volume whose exact distance is used outside (the worked example shows why).

## 3. Sphere-tracing loop

```glsl
uniform float uPixelAngle;          // 2 * tan(fovY / 2) / viewportHeight
float map(vec3 p);                  // 1-Lipschitz: offending sub-trees already divided by their L
float trace(vec3 ro, vec3 rd, float tmin, float tmax) {   // tmin/tmax from a scene bounding box
  float omega = 1.2, t = tmin, prevR = 0.0, stepLen = 0.0;   // over-relaxation (Keinert et al. 2014)
  for (int i = 0; i < 192; ++i) {                          // 128-256
    float d = map(ro + rd * t), r = abs(d);
    if (omega > 1.0 && r + prevR < stepLen) {   // unbounding spheres do not overlap: may have skipped
      t += prevR - stepLen;                     // back to the last guaranteed-safe point
      stepLen = prevR; omega = 1.0; continue;   // and continue unrelaxed
    }
    if (d < 0.5 * uPixelAngle * t) return t;    // error below half a pixel footprint
    stepLen = omega * d; prevR = r; t += stepLen;
    if (t > tmax) break;
  }
  return -1.0;                                  // or keep the t with the smallest d/t as a candidate
}
```

Epsilon = 0.5 * pixelAngle * t: a fixed epsilon is too fine far away (stalls) and too coarse near
the camera (bloat). omega 1.2-1.6; relaxation pays on long grazing rays and costs one wasted
evaluation per failure, so measure (section 11). Early exits: clip [tmin, tmax] against the
scene bounds and stop rays that leave them.

## 4. Normals and shading

```glsl
vec3 calcNormal(vec3 p, float t) {                // 4-tap tetrahedron gradient
  float h = 0.5 * uPixelAngle * t; const vec2 k = vec2(1.0, -1.0);
  return normalize(k.xyy * map(p + k.xyy * h) + k.yyx * map(p + k.yyx * h) +
                   k.yxy * map(p + k.yxy * h) + k.xxx * map(p + k.xxx * h));
}
float softShadow(vec3 ro, vec3 rd, float mint, float maxt, float k) {   // k 4-32: penumbra hardness
  float res = 1.0, t = mint, ph = 1e20;
  for (int i = 0; i < 64 && t < maxt; ++i) {
    float h = map(ro + rd * t);
    if (h < 0.001) return 0.0;
    float y = h * h / (2.0 * ph), d = sqrt(h * h - y * y);   // improved: closest approach between samples
    res = min(res, k * d / max(0.0, t - y));                 // classic: res = min(res, k * h / t)
    ph = h; t += h;
  }
  return clamp(res, 0.0, 1.0);
}
float calcAO(vec3 p, vec3 n) {                    // 5 samples along the normal
  float occ = 0.0, sca = 1.0;
  for (int i = 0; i < 5; ++i) {
    float h = 0.01 + 0.12 * float(i) / 4.0;
    occ += (h - map(p + h * n)) * sca; sca *= 0.95;
  }
  return clamp(1.0 - 3.0 * occ, 0.0, 1.0);
}
```

Central differences cost 6 taps; analytic gradients (chain rule through transforms, the box
gradient, smin weights) are exact and cheapest for small trees. 2D edge antialiasing:
alpha = clamp(0.5 - d / fwidth(d), 0.0, 1.0). For raymarched silhouettes track the minimum of
d / (pixelAngle * t) along the ray and use it as partial coverage.

## 5. Performance

| Lever | Pays when | How |
|---|---|---|
| per-object bounds | many objects | evaluate a cheap bound first; skip the object when bound > current best d |
| BVH over primitives | dozens to thousands of primitives | point query ordered by bound distance, prune when bound > best (see `bvh-build-traversal`) |
| cone marching / low-res depth prepass | primary rays, open scenes | 1/4-res pass marches cones of radius t * 4 pixelAngle; full res starts at that t minus the cone radius |
| shader specialization | SDF tree fixed per frame or level | generate GLSL from the tree, constant-fold transforms, no interpreter loop |
| per-pixel budget | always | evals = pixels x mean steps: 1920 x 1080 x 20.5 = 42.5M per frame; a 5 ms slot on a 10 TFLOP/s GPU leaves ~1,200 flops per evaluation |

Step heatmap: output steps / maxSteps through a perceptual colormap, capped rays in magenta;
hot silhouettes and grazing floors are normal, hot flat interiors mean a bad bound or L.

## 6. SDF to mesh

```python
import numpy as np
from skimage.measure import marching_cubes
h = 0.01; xs = np.arange(-1.0, 1.0 + h, h)
P = np.stack(np.meshgrid(xs, xs, xs, indexing="ij"), -1)
verts, faces, normals, _ = marching_cubes(sdf(P), level=0.0, spacing=(h, h, h))
verts += xs[0]                                   # grid origin
```

PyMCubes: `mcubes.marching_cubes(vol, 0.0)`. Marching cubes needs a consistent case table
(ambiguous faces otherwise crack) and rounds sharp edges by ~h. Dual contouring keeps sharp
features: one vertex per cell minimising sum (n_i . (x - p_i))^2 over edge crossings, solved
around the mass point c with truncated SVD (drop singular values < 0.1 sigma_max), clamped to
the cell. Surface nets: vertex at the centroid of the crossings (smooth, no sharp features).
Resolution: h <= thinnest feature / 3, otherwise thin parts vanish or break apart.

## 7. Mesh to SDF

```python
def winding_number(Q, V, F):     # generalized winding number (Jacobson 2013); O(|Q| |F|): chunk Q
    a, b, c = (V[F[:, i]][None] - Q[:, None] for i in range(3))
    la, lb, lc = (np.linalg.norm(x, axis=-1) for x in (a, b, c))
    det = np.einsum("qfi,qfi->qf", a, np.cross(b, c))
    den = la * lb * lc + (a * b).sum(-1) * lc + (b * c).sum(-1) * la + (c * a).sum(-1) * lb
    return (2.0 * np.arctan2(det, den)).sum(1) / (4.0 * np.pi)   # > 0.5 means inside
```

Sign from winding numbers survives holes and self-intersections where ray parity fails; use
fast winding numbers (Barill 2018, in libigl) beyond toy sizes. Unsigned distance: BVH
closest-point queries (`trimesh.proximity.closest_point`, Open3D `RaycastingScene`, Embree).
Note `trimesh.proximity.signed_distance` returns positive inside, the opposite of the shading
convention. Grid fill: exact distances in a narrow band, then fast sweeping (Gauss-Seidel
Eikonal sweeps in 8 orderings). OpenVDB:
`openvdb::tools::meshToLevelSet<openvdb::FloatGrid>(*xform, points, triangles, quads, 3.0f)`
(narrow band of 3 voxels; watertight input). GPU: convert to NanoVDB (conversion API names
changed between releases) and sample through the PNanoVDB shader header, or use dense 3D
textures (64^3-256^3 R16F per object) or brick maps (8^3 bricks with 8-bit distances quantized
over +-band, plus an indirection grid).

## 8. 2D SDFs for UI and text

```bash
msdf-atlas-gen -font Inter.ttf -charset charset.txt -type mtsdf -size 48 -pxrange 6 \
  -format png -imageout atlas.png -json atlas.json
```

```glsl
float median(float r, float g, float b) { return max(min(r, g), min(max(r, g), b)); }
float screenPxRange(vec2 uv) {                   // uPxRange must equal the generator's -pxrange
  vec2 unitRange = vec2(uPxRange) / vec2(textureSize(uAtlas, 0));
  return max(0.5 * dot(unitRange, vec2(1.0) / fwidth(uv)), 1.0);
}
vec4 shadeGlyph(vec2 uv) {
  vec4 s = texture(uAtlas, uv); float spr = screenPxRange(uv);
  float d = spr * (median(s.r, s.g, s.b) - 0.5);                // screen pixels, > 0 inside
  float fill = clamp(d + 0.5, 0.0, 1.0);
  float outline = clamp(d + uOutlinePx + 0.5, 0.0, 1.0);        // shape grown by uOutlinePx
  float glow = exp(-max(-spr * (s.a - 0.5), 0.0) / uGlowPx);   // MTSDF alpha: true SDF for soft effects
  return mix(uOutlineColor, uFillColor, fill) * outline + uGlowColor * glow * (1.0 - outline);
}
```

Effects can reach only pxRange/2 atlas pixels beyond the edge: with -size 48 -pxrange 6 that is
3 atlas px = 0.0625 em, i.e. 1.5 screen px at a 24 px font. Use larger pxRange (or a separate
blurred field) for wide glows and shadows; use the true-SDF alpha, not the median, far from edges.

## 9. Validation

```python
def lipschitz_check(sdf, lo, hi, n=200_000, h=1e-4, seed=0):
    P = np.random.default_rng(seed).uniform(lo, hi, (n, 3))
    g = np.stack([(sdf(P + h * e) - sdf(P - h * e)) / (2 * h) for e in np.eye(3)], 1)
    gn = np.linalg.norm(g, axis=1)
    return gn.max(), np.percentile(gn, 99.9)     # marched field: max <= 1 + 1e-3
```

Sampling underestimates the supremum: use L = 1.05 x sampled max unless an analytic bound
exists. Against meshes: extract a fine reference surface (marching cubes at h/4) or use the
source mesh, compute unsigned distance on a 32^3 test grid with closest-point queries, and
require | |sdf| - dist | <= h for exact fields and |sdf| <= dist + h for bounds.

## 10. Pitfalls

- Overstepping from non-Lipschitz operations: holes at silhouettes, banding, speckled normals.
- Epsilon too small (stalls, step cap hit, hot heatmap) or too large (bloated, merged shapes).
- Precision far from the origin: float32 spacing is ~1 mm at 10 km, so footprint epsilons fall
  below representable steps; march in camera-relative coordinates.
- Normals across smooth-min seams: a gradient step wider than the blend region smears them;
  keep h near the pixel footprint.
- Repetition with asymmetric or cell-crossing content without neighbour checks overestimates.
- MSDF: a shader pxRange different from the generator's, effects wider than pxRange/2, or
  disabled error correction give corner artefacts and broken outlines.

## 11. Worked example: twisted, repeated columns with holes

Scene: 7 x 7 columns on a 3 m grid (limited repetition), square section of half-width a = 0.5 m
twisted at k = 4.14 rad/m, bounding cylinder 0.75 m, floor and ceiling at y = 0 and 4 m; camera
(-10, 2, -11) looking at (0, 1.5, 0), 60 deg vertical FOV, 480 x 270, epsilon 0.5 px footprint,
256 steps. Numbers below are from the CPU reference in the [references](references/twisted-columns-experiment.md).

1. **Estimate L**: 400,000 random points in one cell, central differences: max |grad d| =
   2.298, p99.9 2.297, median 1.433. Analytic check for an infinite twisted extrusion:
   sqrt(1 + (k a)^2) = sqrt(1 + 2.07^2) = 2.299 (with end caps the shear bound
   (s + sqrt(s^2 + 4)) / 2 = 2.474, s = k a, would apply). Use L = 2.3.
2. **Divide the step** only inside the twisted sub-tree:

```glsl
const float K = 4.14, A = 0.5, RB = 0.75, LIP = 2.3;
float column(vec3 q) {
  float rho = length(q.xz);
  if (rho > RB + 0.1) return rho - RB;                 // exact bound outside: L = 1, big steps
  vec3 t = opTwistY(q, K);
  return sdBox2(t.xz, vec2(A)) / LIP;                   // divide only this sub-tree
}
float map(vec3 p) {
  vec3 q = p - 3.0 * clamp(round(p / 3.0), vec3(-3.0, 0.0, -3.0), vec3(3.0, 0.0, 3.0));
  return min(column(q), min(p.y, 4.0 - p.y));
}
```

3. **Add the relaxation fallback** (section 3) and compare against a reference march (L 2.5,
   epsilon 0.25 px, 4,000 steps; 88,658 column pixels):

| Variant | Hole pixels | Penetrating hits | Mean steps | p95 | Max |
|---|---|---|---|---|---|
| naive, L = 1 | 9,213 (10.4% of column px) | 18,163 | 16.4 | 42 | 155 |
| whole scene / 2.3 | 0 | 0 | 35.9 | 84 | 256 (36 rays capped) |
| twisted sub-tree / 2.3 | 0 | 0 | 20.5 | 49 | 187 |
| sub-tree / 2.3, omega 1.2 | 0 | 0 | 20.0 | 48 | 188 |
| sub-tree / 2.3, omega 1.6 | 0 | 0 | 21.0 | 50 | 188 |

4. **Frame time**: at fixed resolution, march time scales with mean steps x evaluation cost,
   so the fix costs ~25% over the broken version (16.4 -> 20.5 steps) and is 43% cheaper than
   dividing the whole scene (35.9 -> 20.5). omega 1.6 loses here (failed relaxations waste
   evaluations); omega 1.2 gains 2.4%. Keep relaxation only when the GPU measurement agrees:
   median of 300 frames from timestamp queries, with step heatmaps saved before and after.

Related: `mesh-processing`, `realtime-shadows`, `realtime-global-illumination`, `gpu-debugging-profiling`, `bvh-build-traversal`, hub `computer-graphics`
