---
name: mesh-processing
description: "Polygon mesh processing for rendering and geometry pipelines: validation and repair, vertex normals and MikkTSpace tangents, welding and seams, QEM simplification and LOD chains, isotropic and quad remeshing, UV unwrapping and atlasing, booleans, and GPU-ready optimization and compression with meshoptimizer and gltf-transform. Load when importing, cleaning, decimating, remeshing or exporting meshes."
when_to_use: "Imported meshes with holes, flipped or inconsistent normals, non-manifold edges, cracks or duplicate vertices; shading seams or normal-map artefacts on mirrored UVs; decimating scans or building LOD chains; isotropic or quad remeshing; UV unwrapping, xatlas packing or lightmap UVs; failing mesh booleans; preparing glTF/GLB with meshoptimizer, meshlets, quantization, EXT_meshopt_compression, Draco or KTX2 via gltf-transform; glTF-Validator errors."
---

# Mesh processing

Rule zero: print the stats report (section 1) before and after every step and stop at the first
step that breaks an invariant. Most "simplifier/UV/boolean bugs" are bad input topology.
Hub: `computer-graphics` section 8. Longer listings: [repair, PyMeshLab batch, bake and export scripts](references/repair-and-bake-code.md)

## 1. Stats and validation report

Euler characteristic per connected, orientable surface: V - E + F = 2 - 2g - b (g genus,
b boundary loops); summed over C components: chi = 2C - 2g - b, so g = (2C - b - chi) / 2.
A non-integer or negative g means non-manifold input, not a strange shape.

```python
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

def _ncomp(edges, n, verts):
    A = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(n, n))
    return len(np.unique(connected_components(A, directed=False)[1][verts]))

def mesh_stats(V, F):
    F = np.asarray(F, np.int64); n = len(V)
    he = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])      # directed half-edges
    und, cnt = np.unique(np.sort(he, 1), axis=0, return_counts=True)
    dcnt = np.unique(he, axis=0, return_counts=True)[1]
    used, bnd = np.unique(F), und[cnt == 1]
    a2 = np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
    C = _ncomp(und, n, used); b = _ncomp(bnd, n, np.unique(bnd)) if len(bnd) else 0
    chi = len(used) - len(und) + len(F)
    return dict(V=len(used), E=len(und), F=len(F), components=C, boundary_loops=b,
                nonmanifold_edges=int((cnt > 2).sum()), nonmanifold_vertices=nonmanifold_vertices(F),
                flipped_edges=int((dcnt > 1).sum()),          # same directed edge twice: winding clash
                degenerate=int((a2 <= 1e-12 * max(a2.max(), 1e-30)).sum()),
                duplicate_faces=len(F) - len(np.unique(np.sort(F, 1), axis=0)),
                unreferenced=n - len(used), euler=chi, genus=(2 * C - b - chi) / 2)

def nonmanifold_vertices(F):                  # bowties: the link of the vertex has > 1 component
    v = F.reshape(-1); a = F[:, [1, 2, 0]].reshape(-1); c = F[:, [2, 0, 1]].reshape(-1)
    keys, inv = np.unique(np.concatenate([np.stack([v, a], 1), np.stack([v, c], 1)]),
                          axis=0, return_inverse=True)
    inv = inv.reshape(-1); m = len(v)
    A = coo_matrix((np.ones(m), (inv[:m], inv[m:])), shape=(len(keys), len(keys)))
    lab = connected_components(A, directed=False)[1]
    fans = np.unique(np.stack([keys[:, 0], lab], 1), axis=0)[:, 0]
    return int((np.bincount(fans) > 1).sum())
```

Library cross-checks: trimesh `m = trimesh.load(p, force="mesh", process=False)` (process=False
keeps seams and duplicates so the stats are honest), then `m.is_watertight`,
`m.is_winding_consistent`, `m.euler_number`, `m.body_count`; PyMeshLab
`ms.get_topological_measures()` (print the whole dict); libigl `igl.read_triangle_mesh`,
`igl.boundary_loop`, `igl.is_edge_manifold` (return types differ between binding versions).

## 2. Repair recipes

Order: drop unreferenced vertices -> weld -> remove degenerate and duplicate faces -> split or
delete non-manifold edges/vertices -> remove small floating components -> orient -> fill holes.

```python
def weld(V, F, attrs, tol):
    """Merge vertices equal within tol in position AND in every attribute (keeps UV/normal seams).
    attrs: [(array, tol_attr)], e.g. [(UV, 1e-5), (N, 1e-3)]."""
    key = np.round(V / tol).astype(np.int64)
    for A, t in attrs:
        key = np.hstack([key, np.round(A / t).astype(np.int64)])
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return V[first], inv.reshape(-1)[F], [A[first] for A, _ in attrs]
```

Tolerance: 1e-6 x bbox diagonal for exporter float noise, 1e-5 to 1e-4 x diagonal for scan
cracks. Grid rounding misses pairs that straddle a cell; for large tolerances use
`scipy.spatial.cKDTree(V).query_pairs(tol)` plus union-find. Degenerates: repeated indices or
2 x area <= 1e-12 x diag^2. Orientation: BFS over faces across manifold edges; a neighbour that
uses a shared edge in the same direction gets its winding reversed; then flip any closed
component whose signed volume sum(v0 . (v1 x v2))/6 is negative (code in references; trimesh
`trimesh.repair.fix_winding` and `fix_inversion` do the same). Holes: fill only small ones
(<= 100-200 boundary edges) with triangulate + refine + fair (CGAL
`Polygon_mesh_processing::triangulate_refine_and_fair_hole`, PyMeshLab `meshing_close_holes`);
large scan holes need Poisson reconstruction or manual retopology.
PyMeshLab batch filters (names since 2022.2; confirm on the List of Filters page for your
version): `meshing_remove_unreferenced_vertices`, `meshing_merge_close_vertices`,
`meshing_remove_duplicate_faces`, `meshing_remove_null_faces`,
`meshing_repair_non_manifold_edges`, `meshing_repair_non_manifold_vertices`,
`meshing_close_holes`, plus the coherent re-orientation filter (its spelling changed between
releases).

## 3. Normals

```python
def vertex_normals(V, F):                       # angle-weighted (Thuermer-Wuethrich)
    e0 = V[F[:, 1]] - V[F[:, 0]]; e1 = V[F[:, 2]] - V[F[:, 1]]; e2 = V[F[:, 0]] - V[F[:, 2]]
    fn = np.cross(e0, -e2); fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-30
    ang = lambda a, b: np.arctan2(np.linalg.norm(np.cross(a, b), axis=1), (a * b).sum(1))
    N = np.zeros_like(V)
    for k, w in enumerate((ang(e0, -e2), ang(e1, -e0), ang(e2, -e1))):
        np.add.at(N, F[:, k], fn * w[:, None])
    return N / (np.linalg.norm(N, axis=1, keepdims=True) + 1e-30)
```

- Creases: per corner, average only incident faces whose normal is within the crease angle of
  the corner's face (30-60 deg; 30 for hard-surface, 60 for organic), then weld equal corner
  normals. Smoothing groups from DCC files override the angle rule.
- Transforms: n' = normalize(inverse(transpose(M3)) n); for det(M) < 0 also flip triangle
  winding (glTF defines winding by the sign of the node's determinant).
- Renormalize after barycentric interpolation, after octahedral or int8 decode, and after
  skinning or morphing.

## 4. Tangents

- MikkTSpace everywhere: glTF says clients SHOULD compute MikkTSpace tangents when TANGENT is
  absent, and bakers (Blender, Substance, Marmoset) bake in it. Generate tangents after the
  final UVs and welding, then never re-weld across tangent splits.
- TANGENT is vec4: w = +-1 encodes handedness; bitangent = w * cross(N, T.xyz). Mirrored UV
  islands get w = -1, so vertices on the mirror seam must be split.
- Reproduce the baker exactly: per pixel B = w * cross(N_interp, T_interp) from the
  unnormalized interpolated vectors, then normalize the perturbed normal.
- Conventions: OpenGL Y+ (glTF, Blender, Unity) vs DirectX Y- (Unreal): flip the green channel
  when moving maps between them.

| Symptom after import | Cause |
|---|---|
| seams along UV island borders | tangents from a different algorithm, or computed before welding |
| one mirrored half lit from the wrong side | w ignored or bitangent not flipped |
| faceted low-poly despite a correct bake | renderer normals differ from baker normals (recomputed or re-triangulated) |
| bumps inverted everywhere | Y+/Y- convention mismatch |

## 5. Simplification and LOD chains

QEM (Garland-Heckbert 1997): plane p = (a, b, c, d), a^2 + b^2 + c^2 = 1; K_p = p p^T;
Q_v = sum of K_p over incident planes; collapse (v1, v2) with Q = Q1 + Q2 and place v at the
solution of the 4x4 system [Q's upper 3x4 rows; 0 0 0 1] v = (0, 0, 0, 1)^T, or the best of the
endpoints and midpoint when it is singular; cost v^T Q v. Attribute-aware variants append
normals/UVs to the quadric; borders and UV seams are locked or penalised.

```cpp
float scale = meshopt_simplifyScale(&vtx[0].px, vcount, sizeof(Vertex));  // relative -> object space
const float attrW[3] = {0.5f, 0.5f, 0.5f};                                // normal weights
std::vector<std::vector<unsigned>> lods{idx}; std::vector<float> lodErr{0.0f};
while (lods.size() < 5) {
  const auto& src = lods.back();
  std::vector<unsigned> dst(src.size()); float err = 0;
  size_t n = meshopt_simplifyWithAttributes(dst.data(), src.data(), src.size(), &vtx[0].px, vcount,
      sizeof(Vertex), &vtx[0].nx, sizeof(Vertex), attrW, 3, /*vertex_lock*/ nullptr,
      src.size() / 2 / 3 * 3, /*target_error*/ 1e-2f, /*options*/ 0, &err);
  if (n == 0 || n > src.size() * 9 / 10) break;     // stalled: seams/borders block collapses
  dst.resize(n); lods.push_back(dst); lodErr.push_back(lodErr.back() + err * scale);
}
```

`meshopt_simplify` is the position-only variant; target_error is relative to mesh extents
(1e-2 = 1%) unless `meshopt_SimplifyErrorAbsolute`; `meshopt_SimplifyLockBorder` protects open
borders (cracks between independently simplified chunks); `meshopt_simplifySloppy` ignores
topology (far LODs, proxies, shadow casters). Select by projected error: pixels =
err * H / (2 tan(fovY/2) d); use the coarsest LOD under 1 px (0.5 px for silhouette-critical).

## 6. Remeshing

Isotropic (Botsch-Kobbelt 2004), target edge length L, 5-10 iterations of: split edges longer
than 4/3 L; collapse edges shorter than 4/5 L unless that creates edges above 4/3 L; flip edges
when it moves valences toward 6 (4 on borders); tangential relaxation (move each vertex to its
neighbours' centroid projected onto the tangent plane); project back onto the input surface.
Face count after remeshing: F ~ 2.309 A / L^2 (equilateral triangles over area A).

```cpp
namespace PMP = CGAL::Polygon_mesh_processing;   // CGAL::Surface_mesh<K::Point_3> mesh
PMP::isotropic_remeshing(faces(mesh), 0.0028 /*L*/, mesh,
    CGAL::parameters::number_of_iterations(5).protect_constraints(true));
```

pmp-library offers uniform and adaptive remeshing (free functions in recent releases).
Quads: Instant Meshes (field-aligned, fast, CLI `-f` target faces, `-d` deterministic) or
QuadriFlow (`-i in -o out -f faces`, `-sharp` keeps creases); feed them a clean manifold
triangle mesh. Voxel remeshing (OpenVDB or a DCC voxel remesher) turns arbitrary soups into
watertight meshes at a fixed voxel size and loses detail below ~2 voxels.

## 7. Parameterization

Per chart: LSCM (fast, conformal, free boundary), ABF++ (lower angle distortion), SLIM
(bijective, low isometric distortion). Atlas with xatlas:

```cpp
xatlas::Atlas* atlas = xatlas::Create();
xatlas::MeshDecl decl;
decl.vertexCount = vcount; decl.vertexPositionData = &vtx[0].px; decl.vertexPositionStride = sizeof(Vertex);
decl.indexCount = (uint32_t)idx.size(); decl.indexData = idx.data(); decl.indexFormat = xatlas::IndexFormat::UInt32;
if (xatlas::AddMesh(atlas, decl) != xatlas::AddMeshError::Success) return false;
xatlas::PackOptions po; po.resolution = 2048; po.padding = 8; po.bilinear = true; po.blockAlign = true;
xatlas::Generate(atlas, xatlas::ChartOptions(), po);
// atlas->meshes[0].vertexArray[i].xref = source vertex, .uv in texels of atlas->width x atlas->height
xatlas::Destroy(atlas);
```

Mip-safe padding: a gutter of 2^m texels at mip 0 is 1 texel at mip m, so padding 8 keeps
charts apart down to mip 3; dilate baked texels into gutters. Texel density
rho = sqrt(sum uv area x W x H / sum 3D area) texels per metre; every chart within 0.8-1.25 x the
mean. Lightmap UVs: unique (no overlaps, no mirroring), gutters >= 2 texels at the final
lightmap resolution (4-texel alignment for BC6H), charts split at hard edges, uniform density.

## 8. Booleans

Inputs must be closed, oriented, and free of self-intersections; check first (CGAL
`is_closed`, `PMP::does_self_intersect`, `PMP::does_bound_a_volume`).

```cpp
manifold::Manifold A(meshGLa), B(meshGLb);           // MeshGL: vertProperties (xyz...), triVerts
if (A.Status() != manifold::Manifold::Error::NoError) { /* repair input first */ }
manifold::MeshGL out = (A - B).GetMeshGL();          // + union, ^ intersection; output manifold
// CGAL: PMP::corefine_and_compute_difference(meshA, meshB, result) -> false on failure
```

Manifold: fast, robust, guaranteed manifold output (include path differs between major
versions). CGAL corefinement: exact predicates, preserves input vertices. Nef polyhedra
(`CGAL::Nef_polyhedron_3` with an exact kernel): handles coplanar and degenerate cases, orders of
magnitude slower. Python: trimesh booleans with the manifold3d engine.

## 9. GPU-ready pipeline

```cpp
std::vector<unsigned> remap(indexCount);
size_t vcount = meshopt_generateVertexRemap(remap.data(), indices, indexCount, verts, vertexCount, sizeof(Vertex));
meshopt_remapIndexBuffer(idx.data(), indices, indexCount, remap.data());
meshopt_remapVertexBuffer(vtx.data(), verts, vertexCount, sizeof(Vertex), remap.data());
meshopt_optimizeVertexCache(idx.data(), idx.data(), indexCount, vcount);
meshopt_optimizeOverdraw(idx.data(), idx.data(), indexCount, &vtx[0].px, vcount, sizeof(Vertex), 1.05f);
vcount = meshopt_optimizeVertexFetch(vtx.data(), idx.data(), indexCount, vtx.data(), vcount, sizeof(Vertex));
// meshlets: 64 vertices / 124 triangles (newer releases recommend 64/126; <= v0.25 needs triangles % 4 == 0)
size_t maxM = meshopt_buildMeshletsBound(indexCount, 64, 124);
std::vector<meshopt_Meshlet> ml(maxM); std::vector<unsigned> mv(maxM * 64); std::vector<unsigned char> mt(maxM * 124 * 3);
size_t nm = meshopt_buildMeshlets(ml.data(), mv.data(), mt.data(), idx.data(), indexCount,
                                  &vtx[0].px, vcount, sizeof(Vertex), 64, 124, /*cone_weight*/ 0.25f);
for (size_t i = 0; i < nm; ++i) {
  meshopt_Bounds b = meshopt_computeMeshletBounds(&mv[ml[i].vertex_offset], &mt[ml[i].triangle_offset],
                                                  ml[i].triangle_count, &vtx[0].px, vcount, sizeof(Vertex));
  // cull: dot(normalize(b.cone_apex - cam), b.cone_axis) >= b.cone_cutoff, or sphere b.center/b.radius
}
```

Then quantize (KHR_mesh_quantization: int16 positions with a dequantizing node transform, int8
normals/tangents, int16/uint16 UVs, typically 48 -> 20 bytes per vertex), compress with
EXT_meshopt_compression (fast decode, pairs with quantization) or Draco (smaller for
static meshes, slower decode), and textures as KTX2 (UASTC for normal maps, ETC1S for colour).
gltf-transform commands: `inspect`, `weld`, `tangents` (MikkTSpace), `simplify`, `reorder`,
`quantize`, `meshopt`, `draco`, `uastc`, `etc1s` (need KTX-Software installed), `optimize`
(bundled pipeline), `validate`; check each command's flags with `-h`. Ship only with 0
glTF-Validator errors.

## 10. Pitfalls

- Welding across UV or normal seams (smeared textures, smoothed hard edges): weld on position
  and attributes together.
- Simplifying or remeshing non-manifold input: collapses stall or tear; repair first.
- Tangents generated before welding or before the final UVs.
- Flipped normals after mirroring (negative determinant) or after a BFS orientation seeded
  inside-out.
- Dropping JOINTS/WEIGHTS or morph targets: plain simplifiers ignore them; carry them as
  attributes, lock heavily weighted vertices, or simplify per skin cluster.
- Precision on large coordinates: float32 has ~7 digits, so 10 km from the origin the step is
  ~1 mm; recentre per mesh and store the offset in the node transform.

## 11. Worked example: 3.2M-triangle scan to a real-time glTF

Assume a statue-sized scan, surface area A = 4 m^2, base colour in vertex colours or textures.

| Step | Triangles | Vertices | Gate before continuing |
|---|---|---|---|
| 0 input | 3.2M | ~1.6M (F ~ 2V) | stats recorded: components, holes, non-manifold, genus |
| 1 repair | ~3.2M | ~1.6M | 1 component, 0 non-manifold edges/vertices, 0 degenerate, intended boundary loops only |
| 2 isotropic remesh, L = 2.8 mm | 2.309 x 4 / 0.0028^2 = 1.18M | ~0.59M | >= 95% of edges within [4/5 L, 4/3 L]; Hausdorff to step 1 < 0.5 mm |
| 3 QEM LOD0 + LOD1-3 | 100k / 50k / 25k / 12.5k | ~50k for LOD0 | lodErr monotonic; LOD0 mean edge 9.6 mm |
| 4 xatlas, 2048^2, padding 8 | 100k | ~55-65k (seam splits) | no overlaps; density ~857 texels/m (70% packing); charts 0.8-1.25 x mean |
| 5 bake normal + colour from step 1 | - | - | MikkTSpace in baker and engine; cage extrusion >= max LOD0 deviation |
| 6 tangents, meshopt, KTX2, validate | 100k | ~60k | glTF-Validator 0 errors; size budget met |

1. Stats: `mesh_stats(V, F)` on the raw scan; keep the dict as the step-0 row.
2. Repair (section 2), deleting components under 1000 faces (scan floaters).
3. Remesh to L = 2.8 mm (CGAL call in section 6); check the edge-length histogram.
4. Simplify to 100k with attributes and build LODs (section 5). Switch distances at 1080p and 60
   deg: pixels = err x 935 / d, so an LOD with 2 mm error is used beyond 1.9 m.
5. UVs with xatlas (section 7) on LOD0; LOD1-3 reuse LOD0's maps only when simplified with
   attributes (UV seams locked), else unwrap per LOD.
6. Bake normal and colour from the repaired high-res mesh onto LOD0 (Blender Cycles
   selected-to-active; script in references); store the normal map Y+ for glTF.
7. Export and finish: `gltf-transform tangents`, `quantize`, `meshopt`, `uastc` (normal map),
   `etc1s` (colour), then `gltf-transform validate` and the Khronos glTF-Validator. Expected
   geometry: 60k vertices x 20 B (quantized) = 1.2 MB + 300k uint16 indices = 0.6 MB, before
   meshopt compression (vs ~3.5 MB unquantized float); normal map 2048^2 UASTC = 4 MiB GPU memory
   (5.3 MiB with mips).
8. Report the table with measured values in every cell, plus Hausdorff distances per LOD.

Related: `skeletal-animation-skinning`, `sdf-modeling-raymarching`, `raster-pipeline-architecture`, `bvh-build-traversal`, `gpu-compute-patterns`, hub `computer-graphics`
