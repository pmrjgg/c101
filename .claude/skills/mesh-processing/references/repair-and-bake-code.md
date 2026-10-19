# Repair, batch, bake and export scripts

Companion to the `mesh-processing` skill. Python 3 with numpy/scipy unless stated. Run
`mesh_stats` (SKILL.md section 1) after every block.

## Orientation by BFS plus outward flip

```python
from collections import deque, defaultdict
import numpy as np

def orient_faces(V, F):
    """Make winding consistent across manifold edges, then make closed components face outward."""
    F = F.copy()
    owners = defaultdict(list)
    for f, (a, b, c) in enumerate(F):
        for u, v in ((a, b), (b, c), (c, a)):
            owners[(min(u, v), max(u, v))].append(f)
    adj = defaultdict(list)
    for fs in owners.values():
        if len(fs) == 2:                                  # traverse manifold edges only
            adj[fs[0]].append(fs[1]); adj[fs[1]].append(fs[0])
    directed = lambda f: {(F[f][0], F[f][1]), (F[f][1], F[f][2]), (F[f][2], F[f][0])}
    comp = np.full(len(F), -1)
    for seed in range(len(F)):
        if comp[seed] >= 0:
            continue
        comp[seed] = seed; q = deque([seed])
        while q:
            f = q.popleft(); df = directed(f)
            for g in adj[f]:
                if comp[g] >= 0:
                    continue
                if df & directed(g):                      # shared edge used in the same direction
                    F[g] = F[g][::-1].copy()
                comp[g] = seed; q.append(g)
    vol = np.einsum("ij,ij->i", V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])) / 6.0
    for c in np.unique(comp):                             # signed volume is meaningful only for
        sel = comp == c                                   # closed components: check boundary first
        if vol[sel].sum() < 0:
            F[sel] = F[sel][:, ::-1]
    return F
```

Pure-Python BFS handles about a million faces per minute; for multi-million-face scans prefer
`trimesh.repair.fix_winding(m)` followed by `trimesh.repair.fix_inversion(m)`, or PyMeshLab.

## Tolerance weld with a KD-tree

```python
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

def weld_kdtree(V, F, tol, attr=None, attr_tol=1e-5):
    pairs = cKDTree(V).query_pairs(tol, output_type="ndarray")
    if attr is not None and len(pairs):                    # never merge across UV/normal seams
        pairs = pairs[np.abs(attr[pairs[:, 0]] - attr[pairs[:, 1]]).max(1) <= attr_tol]
    n = len(V)
    A = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    lab = connected_components(A, directed=False)[1]
    first = np.unique(lab, return_index=True)[1]          # one representative per cluster
    F2 = lab[F]
    keep = (F2[:, 0] != F2[:, 1]) & (F2[:, 1] != F2[:, 2]) & (F2[:, 2] != F2[:, 0])
    return V[first], F2[keep]
```

Clusters are transitive (a chain of points each within tol can span more than tol); keep tol
well below the smallest feature and edge length.

## PyMeshLab batch (scan cleanup, remesh, decimate)

Filter and parameter names as in PyMeshLab 2022.2 and later (the current docs list
`PureValue` and `PercentageValue` as value classes). If a call raises AttributeError, look the
filter up on the PyMeshLab "List of Filters" page for the installed version.

```python
import pymeshlab as ml
ms = ml.MeshSet(); ms.load_new_mesh("scan.ply")
print(ms.get_topological_measures())
ms.meshing_remove_unreferenced_vertices()
ms.meshing_merge_close_vertices()
ms.meshing_remove_duplicate_faces(); ms.meshing_remove_null_faces()
ms.meshing_repair_non_manifold_edges(); ms.meshing_repair_non_manifold_vertices()
ms.meshing_remove_connected_component_by_face_number(mincomponentsize=1000)   # scan floaters
ms.meshing_close_holes(maxholesize=200)
ms.meshing_isotropic_explicit_remeshing(iterations=5, targetlen=ml.PureValue(0.0028))
ms.meshing_decimation_quadric_edge_collapse(targetfacenum=100000, preserveboundary=True,
    preservenormal=True, preservetopology=True, optimalplacement=True, planarquadric=True)
print(ms.get_topological_measures())
ms.save_current_mesh("lod0.ply")
```

## Normal and colour bake in Blender (run inside Blender's Python)

```python
import bpy
hi, lo = bpy.data.objects["scan_hi"], bpy.data.objects["scan_lod0"]
scene = bpy.context.scene
scene.render.engine = "CYCLES"; scene.cycles.samples = 16
img = bpy.data.images.new("normal", 2048, 2048)
img.colorspace_settings.name = "Non-Color"
nodes = lo.active_material.node_tree.nodes
tex = nodes.new("ShaderNodeTexImage"); tex.image = img; nodes.active = tex   # bake target
bpy.ops.object.select_all(action="DESELECT")
hi.select_set(True); lo.select_set(True); bpy.context.view_layer.objects.active = lo
bpy.ops.object.bake(type="NORMAL", use_selected_to_active=True, cage_extrusion=0.003, margin=8)
img.filepath_raw = "//normal.png"; img.file_format = "PNG"; img.save()
# colour: a second sRGB image as the active node, then
# bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_selected_to_active=True,
#                     cage_extrusion=0.003, margin=8)
```

Blender bakes tangent-space normals in MikkTSpace with the OpenGL (Y+) convention, matching
glTF. cage_extrusion must exceed the largest LOD0-to-scan deviation, or rays start inside the
high-res surface and the bake shows black speckles.

## Export with gltf-transform

```bash
npm i -g @gltf-transform/cli
gltf-transform inspect lod0.glb                 # vertex/index counts, component types, sizes
gltf-transform weld lod0.glb s1.glb
gltf-transform tangents s1.glb s2.glb           # MikkTSpace
gltf-transform quantize s2.glb s3.glb
gltf-transform uastc s3.glb s4.glb              # normal maps; restrict textures with the slot filter in -h
gltf-transform etc1s s4.glb s5.glb              # colour textures; both need KTX-Software installed
gltf-transform meshopt s5.glb final.glb
gltf-transform validate final.glb
```

Run `inspect` after each step: if `meshopt` in your version already quantizes, drop the
separate `quantize`. `gltf-transform optimize in.glb out.glb` bundles most of these steps
(flags per `optimize -h`). Ship only with 0 validator errors and review every warning.
