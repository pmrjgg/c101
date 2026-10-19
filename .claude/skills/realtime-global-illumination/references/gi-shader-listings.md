# GI shader listings

Companion to the `realtime-global-illumination` skill. HLSL; view space is +x right, +y up,
+z forward, camera at the origin; standard Z (0 = near) unless stated.

## GTAO (structure follows XeGTAO; Jimenez et al. 2016)

```hlsl
// radius R in metres; falloff starts at 38.5% of R (falloff range 0.615 R)
float GTAO(float2 uv, uint2 px) {
  float3 P = ViewPos(uv);                                     // view-space position of the pixel
  float3 V = normalize(-P);
  float3 N = ViewNormal(px);
  float radiusPx = R / (P.z * gPixelSizeAtUnitDepth);         // screen radius in pixels
  if (radiusPx < 1.0) return 1.0;
  float falloffRange = 0.615 * R, falloffFrom = R - falloffRange;
  float fMul = -1.0 / falloffRange, fAdd = falloffFrom / falloffRange + 1.0;
  float noiseSlice = IGN(px), noiseStep = frac(noiseSlice + 0.5 * IGN(px.yx));
  float vis = 0.0;
  for (int s = 0; s < SLICES; ++s) {
    float phi = (s + noiseSlice) * PI / SLICES;
    float2 omega = float2(cos(phi), -sin(phi)) * radiusPx * gInvViewportSize;  // screen y is down
    float3 dir = float3(cos(phi), sin(phi), 0);
    float3 ortho = dir - dot(dir, V) * V;
    float3 axis = normalize(cross(ortho, V));
    float3 projN = N - axis * dot(N, axis);
    float projLen = length(projN);
    float cosN = saturate(dot(projN, V) / projLen);
    float n = sign(dot(ortho, projN)) * acos(cosN);
    float low0 = cos(n + HALF_PI), low1 = cos(n - HALF_PI);  // unoccluded horizons
    float hc0 = low0, hc1 = low1;
    for (int j = 0; j < STEPS; ++j) {
      float t = (j + noiseStep) / STEPS; t = t * t + 1.0 / radiusPx;   // denser near the pixel
      float3 d0 = ViewPos(uv + omega * t) - P, d1 = ViewPos(uv - omega * t) - P;
      float l0 = length(d0), l1 = length(d1);
      float c0 = lerp(low0, dot(d0 / l0, V), saturate(l0 * fMul + fAdd));
      float c1 = lerp(low1, dot(d1 / l1, V), saturate(l1 * fMul + fAdd));
      hc0 = max(hc0, c0); hc1 = max(hc1, c1);
    }
    float h0 = -acos(hc1), h1 = acos(hc0);                   // negative side, positive side
    float a0 = (cosN + 2 * h0 * sin(n) - cos(2 * h0 - n)) * 0.25;
    float a1 = (cosN + 2 * h1 * sin(n) - cos(2 * h1 - n)) * 0.25;
    vis += projLen * (a0 + a1);
  }
  return saturate(vis / SLICES);
}
```

Use the depth mip chain for distant samples (mip = log2 of the step length in pixels minus ~3)
to keep cache hits high; add a 3x3 edge-aware spatial filter before upsampling.

## Hi-Z screen-space trace

```hlsl
// o: start (pixel xy at mip 0, device depth z); d: direction scaled so max(|d.x|, |d.y|) = 1
// pixel per unit t (device depth is affine in screen space, so z interpolates linearly).
// gHiZ mip m holds the MIN device depth (closest surface) of each 2^m x 2^m block.
float HiZTrace(float3 o, float3 d, int maxLevel, int maxIter, float2 size) {
  int level = 0; float t = 0.0;
  float2 dd = float2(d.x >= 0 ? max(d.x, 1e-6) : min(d.x, -1e-6),
                     d.y >= 0 ? max(d.y, 1e-6) : min(d.y, -1e-6));
  for (int i = 0; i < maxIter; ++i) {
    float3 p = o + d * t;
    if (any(p.xy < 0) || any(p.xy >= size) || p.z >= 1.0) return -1.0;
    float cs = exp2(level);
    float2 cell = floor(p.xy / cs);
    float2 bound = (cell + float2(d.x >= 0, d.y >= 0)) * cs;
    float2 tb = (bound - o.xy) / dd;
    float tExit = min(tb.x, tb.y) + 1e-3;                     // just inside the next cell
    float zMin = gHiZ.Load(int3(cell, level));
    if (p.z >= zMin) {                                        // behind the closest surface here
      if (level == 0) return t;
      --level; continue;
    }
    float tSurf = d.z > 0 ? (zMin - o.z) / d.z : 1e30;        // reaches the cell's closest depth
    if (tSurf < tExit) { t = tSurf; if (level == 0) return t; --level; }
    else               { t = tExit; level = min(level + 1, maxLevel); }
  }
  return -1.0;
}
```

Caller: build o and d by projecting the view-space start and start + R * L (clip the end against
the near plane) to (pixel, device depth); on a hit, accept only if linear(ray z) - linear(scene z)
< thickness (0.1-0.5 m, or proportional to depth). For reversed-Z build a MAX pyramid and flip
the comparisons.

## IBL: BRDF LUT and prefiltered environment

```hlsl
float2 Hammersley(uint i, uint n) { return float2((i + 0.5) / n, reversebits(i) * 2.3283064365386963e-10); }
float3 SampleGGX(float2 u, float a) {                       // half vector, tangent space, a = rough^2
  float phi = 6.2831853 * u.x;
  float cosT = sqrt((1 - u.y) / (1 + (a * a - 1) * u.y)), sinT = sqrt(1 - cosT * cosT);
  return float3(sinT * cos(phi), sinT * sin(phi), cosT);
}
float G1(float NoX, float k) { return NoX / (NoX * (1 - k) + k); }
float2 IntegrateBRDF(float NoV, float rough) {              // LUT texel (NoV, rough) -> (A, B)
  float a = rough * rough, k = a * 0.5;                     // IBL remap of k (Karis 2013)
  float3 V = float3(sqrt(1 - NoV * NoV), 0, NoV);
  float A = 0, B = 0; const uint N = 1024;
  for (uint i = 0; i < N; ++i) {
    float3 H = SampleGGX(Hammersley(i, N), a);
    float3 L = 2 * dot(V, H) * H - V;
    float NoL = saturate(L.z), NoH = saturate(H.z), VoH = saturate(dot(V, H));
    if (NoL > 0) {
      float Gv = G1(NoV, k) * G1(NoL, k) * VoH / (NoH * NoV);
      float Fc = pow(1 - VoH, 5);
      A += (1 - Fc) * Gv; B += Fc * Gv;
    }
  }
  return float2(A, B) / N;
}
float3 Prefilter(float3 R, float rough, uint N, float faceSize) {   // one output texel
  float a = rough * rough, saTexel = 4 * PI / (6 * faceSize * faceSize);
  float3 sum = 0; float wsum = 0;
  for (uint i = 0; i < N; ++i) {
    float3 H = TangentToWorld(SampleGGX(Hammersley(i, N), a), R);   // n = v = R
    float3 L = 2 * dot(R, H) * H - R;
    float NoL = dot(R, L);
    if (NoL > 0) {
      float NoH = saturate(dot(R, H));
      float pdf = D_GGX(NoH, a) * 0.25;                     // D NoH / (4 VoH) with VoH = NoH
      float mip = rough == 0 ? 0 : max(0.5 * log2(1.0 / (N * pdf * saTexel)) + 1.0, 0.0);
      sum += gEnv.SampleLevel(gLinear, L, mip).rgb * NoL; wsum += NoL;
    }
  }
  return sum / wsum;
}
```

## SH projection (C++)

```cpp
void SHBasis9(float x, float y, float z, float Y[9]) {
  Y[0] = 0.282095f;
  Y[1] = 0.488603f * y; Y[2] = 0.488603f * z; Y[3] = 0.488603f * x;
  Y[4] = 1.092548f * x * y; Y[5] = 1.092548f * y * z; Y[6] = 0.315392f * (3 * z * z - 1);
  Y[7] = 1.092548f * x * z; Y[8] = 0.546274f * (x * x - y * y);
}
void ProjectCube(const Cube& c, float3 L[9]) {              // L: RGB coefficients
  float wsum = 0, Y[9];
  for (int f = 0; f < 6; ++f) for (int j = 0; j < c.size; ++j) for (int i = 0; i < c.size; ++i) {
    float u = 2 * (i + 0.5f) / c.size - 1, v = 2 * (j + 0.5f) / c.size - 1;
    float3 d = normalize(FaceDir(f, u, v));
    float dw = 4.0f / (c.size * c.size) / std::pow(1 + u * u + v * v, 1.5f);
    SHBasis9(d.x, d.y, d.z, Y);
    for (int k = 0; k < 9; ++k) L[k] += c.texel(f, i, j) * (Y[k] * dw);
    wsum += dw;
  }
  for (int k = 0; k < 9; ++k) L[k] *= 4 * PI / wsum;        // discrete solid angles sum to ~4 pi
}
```

## DDGI helpers

```hlsl
float3 SphericalFibonacci(uint i, uint n) {                 // ray i of n; rotate by a random
  float phi = 6.2831853 * frac(i * 0.6180339887);           // rotation matrix every frame
  float cosT = 1.0 - (2.0 * i + 1.0) / n, sinT = sqrt(saturate(1.0 - cosT * cosT));
  return float3(cos(phi) * sinT, sin(phi) * sinT, cosT);
}
```

Octahedral borders (interior N x N at 1..N, border at 0 and N+1): top row dst(x, 0) =
src(N+1-x, 1); bottom dst(x, N+1) = src(N+1-x, N); left dst(0, y) = src(1, N+1-y); right
dst(N+1, y) = src(N, N+1-y); each corner copies the diagonally opposite interior corner
(dst(0,0) = src(N,N), dst(N+1,0) = src(1,N), dst(0,N+1) = src(N,1), dst(N+1,N+1) = src(1,1)).
Without borders, bilinear lookups near octahedron edges blend unrelated directions (visible as
seams in probe-lit surfaces along certain normal directions).
