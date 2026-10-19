# Pre-filtered maps, virtual shadow maps and ray-traced shadows: code

Companion to the `realtime-shadows` skill (sections 5, 7 and 8). HLSL, linear light-space depth
z in [0, 1] unless stated.

## VSM

```hlsl
// Shadow pass pixel shader (or a resolve pass): first two moments, with the in-texel variance
// from the depth slope (GPU Gems 3 ch. 8) so flat sloped receivers do not self-shadow.
float2 VSMMoments(float z) {
  float dx = ddx(z), dy = ddy(z);
  return float2(z, z * z + 0.25 * (dx * dx + dy * dy));
}
float Chebyshev(float2 m, float t, float minVar, float bleed) {
  float var = max(m.y - m.x * m.x, minVar);
  float d = t - m.x;
  float p = var / (var + d * d);
  p = saturate((p - bleed) / (1.0 - bleed));   // light-bleeding reduction, bleed 0.1-0.4
  return t <= m.x ? 1.0 : p;
}
```

Format: RG32F. RG16F has too little precision for z^2 except over tiny depth ranges.
Filtering order: render moments -> optional MSAA resolve -> separable Gaussian (5-9 taps) ->
generate mips -> sample with trilinear + 16x anisotropic. Never apply Chebyshev before filtering:
the moments are what filter linearly.

## EVSM (4 components)

```hlsl
static const float2 kExp = float2(40.0, 5.0);   // fp32: c+ ~40 (limit 44.4), c- 5-40; fp16: <= 5.54
float2 Warp(float z) { z = 2.0 * z - 1.0; return float2(exp(kExp.x * z), -exp(-kExp.y * z)); }
float4 EVSMStore(float z) { float2 w = Warp(z); return float4(w.x, w.x * w.x, w.y, w.y * w.y); }
float EVSM(float4 m, float z, float bias, float bleed) {        // bias ~0.01, tune per scene
  float2 w = Warp(z);
  float2 minVar = (bias * kExp * w) * (bias * kExp * w);        // variance floor scaled by dw/dz
  return min(Chebyshev(m.xy, w.x, minVar.x, bleed), Chebyshev(m.zw, w.y, minVar.y, bleed));
}
```

The positive warp kills most VSM light bleeding; the negative warp fixes the remaining
artefacts where the receiver is just in front of a blocker. EVSM2 (positive only) is the cheap
variant and the only one that fits fp16 (c ~5.5).

## Moment shadow maps (Hamburger 4MSM, Peters and Klein 2015)

Store b = (z, z^2, z^3, z^4) through the paper's optimized quantization (four 16-bit channels),
filter like VSM. Lookup: bias the moments slightly toward a fixed reference vector (the paper's
moment bias), solve the 3x3 Hankel system B c = (1, z_f, z_f^2) by Cholesky, take the two roots
of c0 + c1 z + c2 z^2 = 0, and return the three-point lower bound of the shadow CDF. Port the
paper's supplementary HLSL rather than re-deriving it; validate against EVSM on a scene with
three overlapping occluders, where VSM visibly leaks and MSM should not.

## Virtual shadow maps

Layout: 16384^2 virtual texels per map, 128^2-texel pages, 128 x 128 page table per map; physical
pool of P pages (P = 4096 -> 8192^2 texels -> 256 MiB at D32, 128 MiB at 16 bits).

```hlsl
// 1) Mark: one thread per screen pixel.
[numthreads(8, 8, 1)] void MarkPages(uint2 px : SV_DispatchThreadID) {
  float z = gDepth[px];
  if (z == FAR_DEPTH) return;
  float3 P = ReconstructWorld(px, z);
  float footprint = PixelWorldSize(px, z);                     // metres covered by this pixel
  int L = clamp((int)floor(log2(footprint / gLevel0Texel)) + gLodBias, 0, gLevels - 1);
  float2 uv = mul(gClip[L].viewProj, float4(P, 1)).xy * float2(0.5, -0.5) + 0.5;
  uint2 page = min(uint2(uv * 128.0), 127u);
  gRequest[L][page.y * 128 + page.x] = 1;                      // benign race: all writers write 1
}
// 2) Allocate (compute or CPU): requested && !cached -> pop LRU free page, write the page table
//    entry (physical page xy + valid bit), push to the dirty list. Requested && cached -> touch LRU.
// 3) Render: one indirect draw/dispatch over the dirty list; cull instances/clusters against
//    each page's light-space bounds; viewport/scissor (or mesh-shader clipping) per page.
// 4) Sample:
float SampleVirtual(float3 P, int L) {
  float3 uvz = mul(gClip[L].viewProj, float4(P, 1)).xyz;
  uint2 vt = uint2(saturate(uvz.xy * float2(0.5, -0.5) + 0.5) * 16383.0);
  uint e = gPageTable[L][(vt.y >> 7) * 128 + (vt.x >> 7)];
  if ((e & VALID_BIT) == 0) return SampleVirtual(P, min(L + 1, gLevels - 1)); // coarser fallback
  uint2 phys = uint2(e & 0x3FF, (e >> 10) & 0x3FF) * 128 + (vt & 127u);
  return gPool.Load(int3(phys, 0)) >= uvz.z - BIAS ? 1.0 : 0.0;  // PCF: per-tap Load (taps may
}                                                                  // cross pages) or 1-texel borders
```

(HLSL forbids recursion: unroll the fallback as a loop over levels in real code.)
Invalidation: keep per-instance previous bounds; when an instance moves, mark pages overlapping
old and new light-space bounds dirty. Optional static/dynamic split per page: cache static
casters' depth separately and re-render only dynamic casters into a copy, which keeps the dirty
cost proportional to moving geometry. Budget: cap dirty pages per frame; if the pool is
exhausted, bias the level selection coarser (gLodBias + 1) for the rest of the frame.

## Ray-traced shadow ray (inline, DXR 1.1 / SM 6.5)

```hlsl
RaytracingAccelerationStructure gTLAS;
float3 OffsetRay(float3 p, float3 n) {                    // Ray Tracing Gems ch. 6
  const float origin = 1.0 / 32.0, floatScale = 1.0 / 65536.0, intScale = 256.0;
  int3 ofi = int3(intScale * n);
  float3 pi = asfloat(asint(p) + int3(sign(p)) * ofi);
  return float3(abs(p.x) < origin ? p.x + floatScale * n.x : pi.x,
                abs(p.y) < origin ? p.y + floatScale * n.y : pi.y,
                abs(p.z) < origin ? p.z + floatScale * n.z : pi.z);
}
float RTShadow(float3 P, float3 Ng, float3 lightPos, float lightRadius, float2 xi /*blue noise*/) {
  float3 L = normalize(lightPos - P);
  float3 T = normalize(cross(L, abs(L.y) < 0.99 ? float3(0, 1, 0) : float3(1, 0, 0)));
  float3 B = cross(L, T);
  float r = lightRadius * sqrt(xi.x), phi = 6.2831853 * xi.y;    // point on the light's disk
  float3 target = lightPos + r * (cos(phi) * T + sin(phi) * B);
  RayDesc ray;
  ray.Origin = OffsetRay(P, Ng);
  ray.Direction = normalize(target - ray.Origin);
  ray.TMin = 0.0;
  ray.TMax = length(target - ray.Origin) * 0.999;
  RayQuery<RAY_FLAG_ACCEPT_FIRST_HIT_AND_END_SEARCH> q;
  q.TraceRayInline(gTLAS, RAY_FLAG_NONE, 0xFF, ray);
  while (q.Proceed()) {                                       // only non-opaque candidates arrive
    if (q.CandidateType() == CANDIDATE_NON_OPAQUE_TRIANGLE &&
        AlphaTestPasses(q.CandidateInstanceID(), q.CandidatePrimitiveIndex(),
                        q.CandidateTriangleBarycentrics()))
      q.CommitNonOpaqueTriangleHit();
  }
  return q.CommittedStatus() == COMMITTED_NOTHING ? 1.0 : 0.0;
}
```

Mark opaque geometry opaque in the BLAS (geometry flag) so the loop only runs for alpha-tested
materials. Denoiser inputs: visibility plus hit distance (penumbra width grows with the
occluder-to-receiver distance), view depth, normal, motion vectors. Sample count: 1 spp with a
temporal denoiser; 2-4 spp only for very large lights or no TAA.
