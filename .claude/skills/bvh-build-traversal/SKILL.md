---
name: bvh-build-traversal
description: "Bounding volume hierarchies for ray tracing and spatial queries covering the SAH cost model and quality metrics, binned SAH, SBVH and early split clipping, LBVH/PLOC GPU builds, wide and compressed BVHs, robust slab traversal, refit vs rebuild, two-level TLAS/BLAS and hardware acceleration-structure flags, compaction and scratch. Load when building, tuning or debugging a BVH or acceleration structure."
when_to_use: "Slow ray tracing or picking; writing a BVH builder or traversal kernel for CPU, CUDA or compute shaders; choosing between median split, binned SAH, SBVH, LBVH, PLOC, BVH4/BVH8 or CWBVH; rays missing triangles at box edges, NaN slab tests, stack overflows; animated meshes that need refit or rebuild; Vulkan or DXR acceleration-structure flags, compaction, scratch sizing, instance masks; broad-phase collision or nearest-neighbour structure choice."
---

# BVH build and traversal

Rule zero: report SAH cost, box and triangle tests per ray and Mrays/s on a named machine before and
after every builder change, and assert identical hits (count and sum of t) across builders. Tested
harness and recorded runs: [references/bvh-benchmark.md](references/bvh-benchmark.md).

## 1. SAH cost model and quality metrics

```text
split cost  C = C_trav + (A_L/A) N_L C_isect + (A_R/A) N_R C_isect        leaf cost C_isect N
tree cost   C_tree = Σ_inner (A_n/A_root) C_trav + Σ_leaf (A_l/A_root) N_l C_isect
```

- A is surface area. C_trav/C_isect ≈ 1 for scalar binary nodes (the benchmark uses 1/1), lower with
  SIMD triangle tests, higher for wide nodes; state the constants next to every reported cost.
- Leaf rule: stop when C_isect N ≤ the best split cost or N ≤ 1-2, but force a split above a cap (16
  here) so a degenerate SAH estimate cannot create huge leaves.
- Report: SAH cost, end-point overlap (EPO, Aila-Karras-Laine 2013, which predicts traversal cost better
  than SAH when boxes overlap), box and triangle tests per ray for primary and diffuse rays, Mrays/s,
  build ms, nodes and bytes, max depth, and a node-visit heatmap per builder (PGM or EXR).

## 2. Builder decision table

| Need | Builder | Notes |
|---|---|---|
| production CPU tracing | Embree 4 (`RTC_BUILD_QUALITY_HIGH` uses spatial splits) or tinybvh | do not ship a hand-rolled builder |
| static scene, offline quality | binned SAH with 16-32 bins | O(n log n); the baseline for comparisons |
| long thin or large triangles (cables, hair cards, terrain quads) | SBVH (Stich et al. 2009): spatial splits only where child overlap / root area > α ≈ 1e-5 | duplicates references |
| quick fix without SBVH | early split clipping (Ernst-Greiner 2007) of oversized triangles | +4% references in the benchmark |
| GPU build every frame | LBVH: 30-bit Morton codes (10 bits per axis) and a radix tree (Karras 2012) | fastest build, about 10-30% worse traversal than SAH |
| GPU build, better quality | PLOC (Meister-Bittner 2018), H-PLOC (HPG 2024) | near-SAH quality at GPU build speed |
| deforming meshes | refit plus periodic rebuild | section 6 |
| hardware ray tracing | the driver's builder with the right flags | section 7 |

## 3. Binned SAH build

Excerpt of the tested builder: 32-byte nodes, iterative stack, references with a triangle indirection.

```cpp
struct Node { V3 lo; uint32_t leftFirst; V3 hi; uint32_t count; };  // count > 0: leaf, else leftFirst = left child
struct Ref { AABB box; uint32_t tri; };                            // possibly clipped triangle reference
// per node: centroid bounds cb over refs[first, first + count)
for (int a = 0; a < 3; ++a) {
  const float lo = get(cb.lo, a), ext = get(cb.hi, a) - lo;
  if (!(ext > 0.0f)) continue;
  const float scale = float(bins) / ext;                           // k = floor(B (c - min)/(max - min)), clamped
  AABB bb[64]; uint32_t bc[64] = {};
  for (uint32_t i = first; i < first + count; ++i) {
    const int k = std::min(bins - 1, int((get(refs[i].box.center(), a) - lo) * scale));
    ++bc[k]; bb[k].grow(refs[i].box);
  }
  float leftArea[64]; uint32_t leftCount[64]; AABB acc; uint32_t sum = 0;
  for (int k = 0; k < bins - 1; ++k) { acc.grow(bb[k]); sum += bc[k]; leftArea[k] = acc.area(); leftCount[k] = sum; }
  acc = AABB(); sum = 0;
  for (int k = bins - 1; k >= 1; --k) {                            // plane between bin k-1 and bin k
    acc.grow(bb[k]); sum += bc[k];
    if (sum == 0 || leftCount[k - 1] == 0) continue;
    const float cost = float(leftCount[k - 1]) * leftArea[k - 1] + float(sum) * acc.area();
    if (cost < best) { best = cost; bestAxis = a; bestBin = k; }
  }
}
const float splitCost = C_TRAV + C_ISECT * best / nodeBox.area(), leafCost = C_ISECT * float(count);
if (bestAxis >= 0 && (splitCost < leafCost || count > MAX_LEAF)) {
  const float lo = get(cb.lo, bestAxis), scale = float(bins) / (get(cb.hi, bestAxis) - lo);
  // partition in place by recomputing the SAME bin index, never by comparing with a float plane
  auto it = std::partition(refs.begin() + first, refs.begin() + first + count, [&](const Ref& r) {
    return std::min(bins - 1, int((get(r.box.center(), bestAxis) - lo) * scale)) < bestBin; });
}
```

- Children are allocated as a pair (right = left + 1), so a node stores one index; leaves store `first`
  into a `leafTri` array that maps reference slots to triangle ids (the indirection).
- Build with an explicit stack, push both children, and compute child boxes from the (clipped) reference
  boxes, not from triangle boxes.
- Median-split baseline: `nth_element` on the longest centroid axis, leaves of at most 4.

## 4. Traversal

```cpp
inline float safeRcp(float x) { return 1.0f / (std::fabs(x) > 1e-20f ? x : std::copysign(1e-20f, x)); }  // no 0 * inf
constexpr float kEps = FLT_EPSILON * 0.5f, kGamma3 = 3.0f * kEps / (1.0f - 3.0f * kEps);
inline float slab(const Ray& r, const Node& n) {                 // entry distance, or INF on a miss
  const float tx0 = (n.lo.x - r.o.x) * r.rd.x, tx1 = (n.hi.x - r.o.x) * r.rd.x;
  const float ty0 = (n.lo.y - r.o.y) * r.rd.y, ty1 = (n.hi.y - r.o.y) * r.rd.y;
  const float tz0 = (n.lo.z - r.o.z) * r.rd.z, tz1 = (n.hi.z - r.o.z) * r.rd.z;
  const float tn = std::max(std::max(std::min(tx0, tx1), std::min(ty0, ty1)), std::min(tz0, tz1));
  const float tf = std::min(std::min(std::max(tx0, tx1), std::max(ty0, ty1)), std::max(tz0, tz1)) * (1.0f + 2.0f * kGamma3);
  return (tn <= tf && tf > 0.0f && tn < r.t) ? tn : INF;         // Ize 2013: grazing rays never slip through
}
void trace(const BVH& b, const std::vector<Tri>& tris, Ray& r) {
  struct Entry { uint32_t node; float t; } stack[64]; int sp = 0; // assert max depth < 64 at build time
  if (slab(r, b.nodes[0]) == INF) return;
  uint32_t ni = 0;
  for (;;) {
    const Node& n = b.nodes[ni];
    if (n.count) {
      for (uint32_t i = n.leftFirst; i < n.leftFirst + n.count; ++i) hitTri(r, tris[b.leafTri[i]], b.leafTri[i]);
    } else {
      uint32_t c0 = n.leftFirst, c1 = c0 + 1;
      float d0 = slab(r, b.nodes[c0]), d1 = slab(r, b.nodes[c1]);
      if (d0 > d1) { std::swap(d0, d1); std::swap(c0, c1); }    // nearer child first
      if (d0 != INF) { if (d1 != INF) stack[sp++] = {c1, d1}; ni = c0; continue; }
    }
    for (;;) {                                                   // pop, skipping entries beyond the shrunken t
      if (sp == 0) return;
      const Entry e = stack[--sp];
      if (e.t < r.t) { ni = e.node; break; }
    }
  }
}
```

- γ(n) = nε/(1 − nε) with ε = 2⁻²⁴; scaling t_far by 1 + 2γ(3) makes the slab test conservative.
- Shadow rays: any-hit early-out (return on the first hit, skip the child ordering).
- GPU variants: short stacks in registers with a restart or spill path, stackless traversal with parent
  links, while-while loops for warp coherence (Aila-Laine 2009), persistent threads for incoherent rays.

## 5. Wide and compressed BVHs

- Collapse binary to BVH4/BVH8 top-down: open the child with the largest surface area until the node
  has W children; leaves stay closed.
- SIMD box tests: store the W child boxes as SoA (lo.x[8], hi.x[8], ...), test all at once, sort the hit
  children by distance with a small sorting network, push all but the nearest.
- CWBVH (Ylitie, Karras, Laine 2017): 8-wide, 80-byte nodes = origin p (3 × f32) + power-of-two scale
  exponents e (3 × u8) + inner mask (u8) + child and triangle base indices (2 × u32) + per-child meta
  (8 × u8) + quantized child bounds (6 × 8 × u8); child box = p + 2^e · q with conservative rounding
  (floor for lo, ceil for hi); child order from the octant of the ray direction. The default for
  incoherent rays on GPUs without RT cores.

## 6. Dynamic scenes

- Refit in O(n): leaves first, then inner nodes in reverse build order (children have higher indices in
  a top-down build). On GPU each leaf thread walks up and the second thread to reach a parent (atomic
  counter) refits it.
- Track SAH cost after every refit; rebuild when it exceeds 1.3 × the post-build cost.
- Two-level: one BLAS per mesh (static: fast-trace build plus compaction; skinned: refit every frame,
  rebuild every N frames) and one TLAS over instances rebuilt every frame. Transform rays into object
  space with the inverse instance matrix and do not renormalise the direction, so t is shared.
- Per-frame build budget (for example 1 ms): prioritise visible and near objects, amortise rebuilds.

## 7. Hardware ray-tracing acceleration structures

| Intent | Vulkan `VK_BUILD_ACCELERATION_STRUCTURE_*_KHR` | D3D12 `D3D12_RAYTRACING_ACCELERATION_STRUCTURE_BUILD_FLAG_*` |
|---|---|---|
| static geometry, best traversal | `PREFER_FAST_TRACE_BIT` | `PREFER_FAST_TRACE` |
| rebuilt every frame | `PREFER_FAST_BUILD_BIT` | `PREFER_FAST_BUILD` |
| refit later | `ALLOW_UPDATE_BIT`, then build mode UPDATE | `ALLOW_UPDATE`, then `PERFORM_UPDATE` |
| shrink after build | `ALLOW_COMPACTION_BIT` | `ALLOW_COMPACTION` |
| memory over speed | `LOW_MEMORY_BIT` | `MINIMIZE_MEMORY` |

- Sizes: `vkGetAccelerationStructureBuildSizesKHR` (accelerationStructureSize, buildScratchSize,
  updateScratchSize) or `GetRaytracingAccelerationStructurePrebuildInfo` (ResultDataMaxSizeInBytes,
  ScratchDataSizeInBytes, UpdateScratchDataSizeInBytes). Align scratch to
  `minAccelerationStructureScratchOffsetAlignment`; reuse one scratch buffer with a barrier between builds.
- Compaction: build with ALLOW_COMPACTION, query the compacted size
  (`vkCmdWriteAccelerationStructuresPropertiesKHR` with `VK_QUERY_TYPE_ACCELERATION_STRUCTURE_COMPACTED_SIZE_KHR`,
  or `EmitRaytracingAccelerationStructurePostbuildInfo`), allocate, copy in COMPACT mode, free the original.
- Instances (`VkAccelerationStructureInstanceKHR`): 3 × 4 row-major transform, 24-bit custom index, 8-bit
  mask AND-ed with the ray mask (for example bit 0 camera-visible, bit 1 shadow caster), 24-bit SBT record
  offset selecting the hit group, flags (`TRIANGLE_FACING_CULL_DISABLE`, `FORCE_OPAQUE`).
- Geometry flags: `OPAQUE` on everything without alpha (no any-hit at all);
  `NO_DUPLICATE_ANY_HIT_INVOCATION` only when any-hit must run once per primitive; opacity micromaps for
  alpha-tested foliage.
- Inspect with the Nsight Graphics acceleration-structure viewer, AMD Radeon Raytracing Analyzer and
  RGP, or PIX; avoid one world-sized BLAS that mixes static and dynamic geometry.

## 8. Non-rendering uses

| Structure | Best for | Weak at |
|---|---|---|
| BVH / dynamic AABB tree with fattened boxes | broad phase with moving objects, picking, closest point on meshes | uniform point clouds |
| k-d tree | static point kNN (for example nanoflann), photon maps | frequent updates |
| uniform grid or spatial hash | uniform particle density (SPH: cell = interaction radius) | very non-uniform scenes |
| octree or sparse voxels | LOD, voxel collision, sparse volumes | thin geometry, rebalancing |

- Broad phase: fatten boxes by a margin (or velocity × dt) so small motions do not reinsert; rebalance
  with tree rotations.
- Closest point and nearest neighbour: best-first traversal by box distance, pruning boxes farther than
  the current best.

## 9. Pitfalls

- Degenerate or zero-area triangles (12,514 in the benchmark scene): reject det ≈ 0 in the intersector
  and drop them at build time.
- Wrong primitive indirection in leaves (triangles indexed by reference slot): wrong hits that only a
  hit-count and sum-of-t comparison across builders catches.
- Float precision in huge worlds: at 10 km the float32 spacing is about 1 mm; use camera-relative
  coordinates and rebase instances around the camera.
- TLAS not rebuilt or updated after instance edits; UPDATE needs ALLOW_UPDATE at the original build and
  an identical geometry layout.
- Refit quality decay under large deformation (explosions, cloth, fracture): rebuild on the SAH threshold.
- 0 · ∞ = NaN in slab tests for axis-parallel rays: safeRcp or NaN-aware min/max ordering.
- Traversal stack overflow: check the max depth at build time (the SAH trees below reach 28).
- A few long thin triangles can dominate traversal cost (section 10).

## 10. Worked example: median vs binned SAH vs spatial splits on 2M triangles

Machine: Apple M3 Ultra, Apple clang 21.0.0 `-O3`, one thread, scalar code. Scene: 2,001,698 triangles
(999,698 terrain, 500,000 in 500 clustered rocks, 500,000 torus, 2,000 cable triangles up to 140 m long
and 5 cm wide). Rays: 1,048,576 pinhole primaries (576,472 hits) plus one cosine-weighted diffuse ray per
hit. All builders return identical hits (576,472 primary with Σt = 5.101107e7; 136,692 diffuse with
Σt = 1.646553e6). Spatial splits are approximated by early split clipping (ESC) of triangles whose box
area exceeds 1e-4 of the scene box.

| Builder | Build ms | Nodes | SAH cost | Primary Mrays/s | Boxes/ray | Tris/ray | Diffuse Mrays/s | p99 boxes |
|---|---|---|---|---|---|---|---|---|
| median split | 329 | 1.05M | 1023.7 | 0.15 | 799 | 297.5 | 0.09 | 2259 |
| binned SAH, 16 bins | 853 | 2.06M | 510.4 | 0.37 | 365 | 151.6 | 0.19 | 1193 |
| binned SAH + ESC (+80,524 refs) | 921 | 2.14M | 115.2 | 1.11 | 114 | 4.2 | 0.76 | 475 |

Same scene without the cables (1,999,698 triangles):

| Builder | Build ms | SAH cost | Primary Mrays/s | Boxes/ray | Tris/ray | Diffuse Mrays/s |
|---|---|---|---|---|---|---|
| median split | 334 | 92.7 | 2.79 | 35.2 | 5.6 | 1.45 |
| binned SAH, 16 bins | 833 | 64.1 | 3.71 | 30.1 | 1.6 | 1.92 |
| binned SAH + ESC | 835 | 64.1 | 3.73 | 30.1 | 1.6 | 1.95 |

Reading:
- On well-behaved geometry SAH buys 1.33× over median split for primary and diffuse rays with 3.5×
  fewer triangle tests, for 2.5× the build time.
- 2,000 long thin triangles (0.1% of the scene) slow SAH traversal 10× (3.71 to 0.37 Mrays/s): their boxes
  overlap everything and object splits cannot separate them.
- Spatial splitting recovers 3× (1.11 Mrays/s) and cuts triangle tests from 152 to 4.2 per ray; the gap
  to 3.71 is the 80k small cable references the rays still visit (114 vs 30 boxes per ray). A true SBVH
  chooses its spatial splits by SAH and usually does better; measure Embree's high-quality builder or
  tinybvh's spatial-split builder on the same scene (not measured here).
- Use the per-builder heatmaps (`heat_<i>.pgm`) to see where the extra box tests happen.
- Absolute numbers are single-thread scalar; Embree with wide nodes, SIMD and all cores is one to two
  orders of magnitude faster. The ratios are what transfer.

Related: `path-tracer-implementation`, `importance-sampling-mis-restir`, `gpu-compute-patterns`, `gpu-debugging-profiling`, `vulkan-setup-synchronization`, `mesh-processing`, hub `computer-graphics`
