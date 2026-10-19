---
name: skeletal-animation-skinning
description: "Skeletal animation and skinning: joint hierarchies, bind poses and inverse bind matrices, linear blend skinning and its artefacts, dual-quaternion skinning, GPU skinning, keyframe interpolation (slerp), blending and state machines, IK (two-bone, CCD, FABRIK), glTF 2.0 skins and animations, retargeting. Load when implementing or debugging character animation."
when_to_use: "Skinned characters that explode, collapse, float or lag a frame; candy-wrapper twisting or volume loss at elbows, knees or wrists; choosing LBS vs DQS; inverse bind matrix or bind-pose bugs; vertex-shader vs compute skinning, joint palette limits, 4 vs 8 influences; keyframe sampling, slerp/nlerp, CUBICSPLINE tangents; crossfades, additive layers, blend trees, state machines, root motion; two-bone, CCD or FABRIK IK; importing glTF 2.0 skins and animations; retargeting between skeletons; bone and weight-heatmap debug views."
---

# Skeletal animation and skinning

Rule zero: first prove the bind pose. With every animation off, the skinning palette must be
identity and the skinned mesh must equal the bind mesh (max error < 1e-5 x bbox). Almost every
"exploding character" fails this check. Hub: `computer-graphics`.
Full reproducible numbers for section 11: [two-joint arm experiment](references/two-joint-arm-experiment.md)

## 1. Skeleton data

- Joints stored topologically sorted (parent[j] < j, root -1), so one forward pass computes
  globals. Local pose per joint: translation, rotation quaternion, scale (TRS).
- Global G_j = G_parent * L_j. Bind pose: the globals B_j when the mesh was bound.
  Inverse bind matrix IBM_j = B_j^-1 maps bind (mesh) space into joint j's space.
- Palette P_j = G_j * IBM_j maps bind-space vertices to the current pose; in the bind pose
  P_j = identity.

```cpp
struct Skeleton { std::vector<int> parent; std::vector<float4x4> inverseBind; std::vector<std::string> name; };
void BuildPalette(const Skeleton& sk, const float3* t, const quat* r, const float3* s,
                  float4x4* global, float4x4* palette) {          // column vectors: M * v
  for (size_t j = 0; j < sk.parent.size(); ++j) {
    float4x4 L = Translate(t[j]) * Rotate(r[j]) * Scale(s[j]);
    global[j] = sk.parent[j] < 0 ? L : global[sk.parent[j]] * L;
    palette[j] = global[j] * sk.inverseBind[j];
  }
}
```

Non-uniform scale on a parent with a rotated child produces shear that TRS cannot hold: keep
globals as matrices, never decompose them back to TRS per frame.

## 2. Linear blend skinning

v' = sum_i w_i P_i v,  n' = normalize(sum_i w_i P_i' n), with P_i' the upper 3x3 (rigid joints)
or its inverse transpose (scaled joints); weights >= 0 and sum to 1.
Artefact math: blending identity and a rotation R(theta) at weight 1/2 gives
(I + R(theta)) / 2 = cos(theta/2) R(theta/2) in the rotation plane. A **bend** of theta scales
the elbow cross-section by cos(theta/2) along one axis (area 0.707 at 90 deg, 0.5 at 120 deg).
A **twist** about the bone scales both axes: area cos^2(theta/2), 0.5 at 90 deg and 0 at 180 deg:
the candy wrapper.

| Fix | Cost | Effect |
|---|---|---|
| twist helper joints (split a 180-deg twist over 3 joints) | rig work, joints | each blend sees 60 deg: area cos^2(30) = 0.75 |
| corrective blend shapes / pose-space deformation | artist time, memory | best elbows and knees |
| DQS (section 3) | ~2x ALU, no scale | preserves cross-section, slight bulge at bends |
| wider weight falloff | none | softer crease, same volume loss |

## 3. Dual-quaternion skinning

Rigid palette entry (rotation quaternion q_r, translation t): real part q_r, dual part
q_d = 1/2 (0, t) q_r (quaternion product, t as a pure quaternion). Blend
b = sum_i w_i s_i (q_r,i, q_d,i) with s_i = sign(q_r,pivot . q_r,i) (antipodality: q and -q are
the same rotation but blend to garbage, even to zero length); divide both parts by |b_r|.
With normalized real part (r_w, r_v) and dual part (d_w, d_v):
p' = p + 2 r_v x (r_v x p + r_w p) + 2 (r_w d_v - d_w r_v + r_v x d_v).

```glsl
layout(std430, binding = 0) readonly buffer DQ { vec4 dq[]; };     // per joint: real, dual (xyz, w)
vec3 dqsTransform(uvec4 j, vec4 w, vec3 p, inout vec3 n) {
  vec4 piv = dq[2u * j.x], br = vec4(0.0), bd = vec4(0.0);
  for (int i = 0; i < 4; ++i) {
    vec4 r = dq[2u * j[i]], d = dq[2u * j[i] + 1u];
    float s = dot(r, piv) < 0.0 ? -w[i] : w[i];                   // antipodality
    br += s * r; bd += s * d;
  }
  float len = length(br); br /= len; bd /= len;
  n += 2.0 * cross(br.xyz, cross(br.xyz, n) + br.w * n);
  return p + 2.0 * cross(br.xyz, cross(br.xyz, p) + br.w * p)
           + 2.0 * (br.w * bd.xyz - bd.w * br.xyz + cross(br.xyz, bd.xyz));
}
```

Choose DQS for twist-heavy tubes (forearms, necks, tails, tentacles) without helper joints;
keep LBS when joints scale (squash and stretch) or when correctives already fix the volume.
DQS bulges slightly on the outside of strong bends; blending LBS and DQS per vertex is a common
compromise. Scale: apply per-joint scale with a separate linear blend before the DQ transform.

## 4. GPU skinning

```glsl
layout(std430, binding = 0) readonly buffer Palette { mat4 uPalette[]; };   // mat3x4 saves 25%
layout(location = 0) in vec3 aPos; layout(location = 1) in vec3 aNormal;
layout(location = 4) in uvec4 aJoints; layout(location = 5) in vec4 aWeights;
void main() {
  mat4 M = aWeights.x * uPalette[aJoints.x] + aWeights.y * uPalette[aJoints.y]
         + aWeights.z * uPalette[aJoints.z] + aWeights.w * uPalette[aJoints.w];
  vec3 n = normalize(mat3(M) * aNormal);                  // rigid joints
  gl_Position = uViewProj * (M * vec4(aPos, 1.0));
}
```

| Choice | Use when |
|---|---|
| vertex-shader skinning | mesh drawn once or twice per frame |
| compute pre-skinning to a buffer (position, normal, tangent, previous position) | drawn 3+ times (depth prepass, shadow cascades, G-buffer), ray tracing (BLAS refit needs skinned positions), meshlet pipelines |

| Palette entry | Bytes | 16 KiB UBO (GLES 3.0 and Vulkan spec minimum) | 64 KiB (D3D constant buffer) |
|---|---|---|---|
| mat4 | 64 | 256 joints | 1024 joints |
| mat3x4 | 48 | 341 | 1365 |
| dual quaternion | 32 | 512 | 2048 |

Storage buffers lift the limit: crowds put every palette in one buffer indexed by instance.
Influences: 4 (JOINTS_0/WEIGHTS_0) is the default; 8 (adds JOINTS_1/WEIGHTS_1) for faces and
hands costs two more attribute streams and four more blends. At import drop weights below
~0.01, renormalize, sort descending, and quantize UNORM8 weights so they sum to exactly 255
(add the rounding residual to the largest).

## 5. Keyframe sampling

Find the key interval with a cached cursor (playback is monotonic) or binary search;
s = (t - t_k) / (t_k+1 - t_k).

```cpp
quat Nlerp(quat a, quat b, float s) { if (dot(a, b) < 0) b = -b; return normalize(a * (1 - s) + b * s); }
quat Slerp(quat a, quat b, float s) {
  float c = dot(a, b); if (c < 0) { b = -b; c = -c; }                 // shortest path
  if (c > 0.9995f) return Nlerp(a, b, s);                            // nearly parallel
  float th = std::acos(c), sn = std::sin(th);
  return a * (std::sin((1 - s) * th) / sn) + b * (std::sin(s * th) / sn);
}
template <class T> T Hermite(T v0, T outTan0, T v1, T inTan1, float s, float dt) {  // glTF CUBICSPLINE
  float s2 = s * s, s3 = s2 * s;
  return (2*s3 - 3*s2 + 1) * v0 + (s3 - 2*s2 + s) * dt * outTan0 + (-2*s3 + 3*s2) * v1 + (s3 - s2) * dt * inTan1;
}
```

STEP holds v_k. Slerp has constant angular velocity; nlerp is cheaper, commutative and close
enough for keys a few degrees apart and for weighted blending. Normalize cubic-spline rotation
results. Long clips: resample to a fixed rate and compress (curve fitting or a library such as
ACL) under a per-joint error budget measured at the skin, not in angle space.

## 6. Blending, state machines, root motion

- **Crossfade** over 0.1-0.3 s: per joint lerp translation and scale, nlerp rotation (sign
  fixed) with alpha(t) ramping 0 -> 1. Inertialization (decay the pose offset at the transition
  instead of evaluating both clips) halves the cost and avoids foot sliding from mismatched phases.
- **Additive layers**: delta = reference^-1 * anim per joint (r_d = r_ref^-1 r_anim,
  t_d = t_anim - t_ref); apply r = r_base * slerp(identity, r_d, w), t = t_base + w t_d.
  Per-bone masks restrict layers (upper body aim, breathing).
- **Blend trees**: 1D by speed using each clip's measured root speed, 2D by direction and speed
  (barycentric weights over triangulated parameters); sync clips by normalized phase or foot
  markers so feet do not slide.
- **State machines**: states hold clips or blend trees; transitions have conditions,
  crossfade durations and optional exit times; keep the graph data-driven and log transitions.
- **Root motion**: per frame extract the root's horizontal translation and yaw delta, zero them
  in the pose, apply them to the character controller; on loop wrap add (end - previous) +
  (current - start).

## 7. Inverse kinematics

```cpp
// Two-bone (shoulder S, elbow E, wrist W), target T, pole P: new elbow E2 and wrist W2.
void TwoBoneIK(float3 S, float3 E, float3 W, float3 T, float3 P, float3& E2, float3& W2) {
  float a = length(E - S), b = length(W - E);
  float3 d = T - S; float c = clamp(length(d), std::abs(a - b) + 1e-4f, a + b - 1e-4f);
  float3 dir = normalize(d);
  float cosA = (a * a + c * c - b * b) / (2 * a * c);                  // law of cosines at S
  float3 pole = (P - S) - dot(P - S, dir) * dir;                       // pole in the bend plane
  float3 bend = length(pole) > 1e-6f ? normalize(pole) : PreviousBendDir();
  E2 = S + a * (cosA * dir + std::sqrt(std::max(0.0f, 1 - cosA * cosA)) * bend);
  W2 = S + c * dir;
}
```

Convert positions to rotations: rotate the shoulder by FromTo(E - S, E2 - S) in global space,
recompute the elbow's global, rotate it by FromTo(W' - E2, W2 - E2), then local = inverse(parent
global) * global. FromTo(u, v) = normalize(1 + u.v, u x v) for unit u, v (handle u = -v).
- **CCD**: for j from the effector's parent to the root, rotate joint j by
  FromTo(effector - p_j, target - p_j), clamp to limits; 10-20 sweeps or until the error is
  below tolerance. Cheap, but it curls the chain toward the tip.
- **FABRIK** (Aristidou and Lasenby 2011): unreachable targets give a straight chain toward
  the target; otherwise iterate: set p_n = T and walk back with
  p_i = p_i+1 + d_i normalize(p_i - p_i+1); reset p_0 = root and walk forward with
  p_i+1 = p_i + d_i normalize(p_i+1 - p_i); stop when |p_n - T| < tol (usually < 10 iterations).
- **Constraints**: hinge = project the bone direction onto the hinge plane and clamp the angle;
  ball = clamp the swing cone; twist limits via swing-twist:
  twist = normalize((w, (v . a) a)), swing = q * twist^-1 for twist axis a.

## 8. glTF 2.0 skins and animations

```json
"nodes": [{"name": "arm", "mesh": 0, "skin": 0},
          {"name": "shoulder", "children": [2]}, {"name": "elbow", "translation": [0.3, 0, 0]}],
"skins": [{"inverseBindMatrices": 5, "joints": [1, 2], "skeleton": 1}],
"meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "JOINTS_0": 2, "WEIGHTS_0": 3}, "indices": 4}]}],
"animations": [{"channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}],
                "samplers": [{"input": 6, "output": 7, "interpolation": "LINEAR"}]}]
```

- JOINTS_n values index `skin.joints`, not nodes. JOINTS_0 is VEC4 unsigned byte or short;
  WEIGHTS_0 is VEC4 float or normalized unsigned byte/short; weights non-negative, summing to 1.
- inverseBindMatrices: MAT4 float, column-major; identity when omitted.
- Only joint transforms move a skinned mesh; the transform of the node holding the mesh must
  not apply. A renderer that still multiplies by that node's model matrix uses
  jointMatrix_j = inverse(global(meshNode)) * global(joint_j) * IBM_j to cancel it.
- Samplers: input = key times in seconds; LINEAR (slerp for rotations), STEP, CUBICSPLINE
  (three outputs per key: in-tangent, value, out-tangent; tangents scale by the key interval as
  in `Hermite` above). Rotations are (x, y, z, w); paths: translation, rotation, scale, weights.
- Conventions: right-handed, +Y up, metres, asset front faces +Z. Left-handed Y-up targets:
  x -> -x for positions, normals and translations, quaternion (x, y, z, w) -> (x, -y, -z, w),
  matrices S M S with S = diag(-1, 1, 1), and reverse triangle winding. Z-up targets: one
  rotation at the root, never per joint.

## 9. Retargeting and debugging

Retarget: (1) map joints by semantic name to a humanoid template (unmapped joints keep rest);
(2) with global rest rotations Rs0 (source) and Rt0 (target), each frame set
Rt = Rs * Rs0^-1 * Rt0 (global), then local = parentGlobal^-1 * Rt (the world-space rotation
change transfers whatever the local axis conventions); (3) scale root translation by the
hip-height ratio; (4) re-plant feet and hands with IK on the source contacts; (5) for A-pose vs
T-pose rigs, pose the target into the source rest pose once and store that as Rt0.
Debug views: bones as lines to the parent plus axis triads (X red, Y green, Z blue, 10% of bone
length) in bind and animated pose; weight heatmap for a picked joint; influence-count and
weight-sum views (|sum - 1| > 1e-3 in red); the bind-pose identity test from rule zero.

## 10. Pitfalls

- IBMs missing or computed from the wrong pose: mesh offset or exploded.
- Applying the mesh node's transform twice (glTF), or skinning in world space then applying the
  model matrix again.
- Quaternion sign flips: pops in blends, garbage DQS blends; always align hemispheres.
- Weights not summing to 1 after quantization: mesh shrinks or swells.
- `skin.joints` order mixed up with skeleton order when building the palette.
- Root motion applied both by the controller and in the pose (double speed, drift).
- Previous-frame skinning missing for motion vectors: TAA ghosting on moving limbs.
- Bounds from the bind pose: culling pops; use per-clip animated bounds or joint-sphere unions.

## 11. Worked example: two-joint arm, LBS vs DQS

Arm: cylinder 0.6 m long, radius 5 cm, 121 rings x 48 segments + 2 cap centres (5,810 vertices,
11,616 triangles). Shoulder joint at x = 0, elbow at x = 0.3 m; weights
w_elbow = smoothstep(0.25, 0.35, x), w_shoulder = 1 - w_elbow. Bind volume 4,699 cm^3 (analytic
4,712; polygon approximation). Elbow palette entry = rotation about the elbow point.

```python
def skin_lbs(V, W, M):                       # V (n,3), W (n,J), M (J,4,4) palette
    return np.einsum("nj,jab,nb->na", W, M, np.c_[V, np.ones(len(V))])[:, :3]

def skin_dqs(V, W, M):                       # quaternions as (w, x, y, z)
    R = np.array([quat_from_matrix(m[:3, :3]) for m in M])
    D = np.array([0.5 * qmul(np.r_[0.0, m[:3, 3]], r) for m, r in zip(M, R)])
    sgn = np.sign(R[np.argmax(W, 1)] @ R.T); sgn[sgn == 0] = 1       # align to the main joint
    br, bd = (W * sgn) @ R, (W * sgn) @ D
    n = np.linalg.norm(br, axis=1, keepdims=True); br, bd = br / n, bd / n
    w, v, we, ve = br[:, :1], br[:, 1:], bd[:, :1], bd[:, 1:]
    return V + 2 * np.cross(v, np.cross(v, V) + w * V) + 2 * (w * ve - we * v + np.cross(v, ve))
```

Measured (volume and mid-ring cross-section area relative to bind; mid ring at the elbow):

| Pose | LBS volume | LBS ring area | DQS volume | DQS ring area | Analytic LBS area |
|---|---|---|---|---|---|
| bend 90 deg | 0.978 | 0.707 | 1.000 | 1.000 | cos 45 = 0.707 |
| bend 120 deg | 0.967 | 0.500 | 0.999 | 1.000 | cos 60 = 0.5 |
| twist 90 deg | 0.957 | 0.500 | 1.000 | 1.000 | cos^2 45 = 0.5 |
| twist 180 deg | 0.914 | 0.000 | 1.000 | 1.000 | cos^2 90 = 0 |

Identity pose: max vertex error 6.9e-18 (LBS) and 0 (DQS), so palettes and IBMs are right.
Reading: whole-mesh volume hides the problem (2-9% loss) because only the 10 cm blend zone
deforms; the ring area shows the real collapse, so measure cross-sections. Decision for this
rig: forearm twist -> DQS or three twist joints (ring area >= 0.75); elbow bend -> LBS plus a
corrective shape keyed at 90 deg, or DQS if no correctives are budgeted.

Related: `mesh-processing`, `raster-pipeline-architecture`, `gpu-compute-patterns`, `denoising-taa-upscaling`, `bvh-build-traversal`, hub `computer-graphics`
