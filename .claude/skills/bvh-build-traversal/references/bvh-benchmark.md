# BVH benchmark harness

`bvh_bench.cpp` builds three BVHs over a synthetic scene of about 2M triangles and traces 1024 x 1024
pinhole primary rays plus one cosine-weighted diffuse ray per primary hit, on one thread:

- median split: longest centroid axis, `nth_element`, leaves of at most 4 triangles;
- binned SAH: 16 bins per axis, SAH leaf rule with C_trav = C_isect = 1, forced split above 16;
- binned SAH over early-split-clipped references (ESC, Ernst and Greiner 2007): triangles whose box area
  exceeds 1e-4 of the scene box area are recursively halved on the longest axis and clipped
  (Sutherland-Hodgman), a cheap stand-in for SBVH spatial splits.

Scene: 707 x 707-quad terrain (999,698 triangles), 10 clusters of 50 UV-sphere rocks (500,000, with
zero-area pole triangles), a 500 x 500-quad torus (500,000), and `cables` long thin quads (default 1,000,
i.e. 2,000 triangles up to ~140 m long and 5 cm wide). Correctness gate: every builder must report the
same hit count and sum of hit distances. A node-visit heatmap per builder is written as `heat_<i>.pgm`.

Build and run: `c++ -O3 -std=c++17 -DNDEBUG bvh_bench.cpp -o bvh_bench && ./bvh_bench <out_dir> [cables]`

## Source

```cpp
// bvh_bench.cpp: median split vs binned SAH vs binned SAH + early split clipping (ESC, a cheap
// stand-in for SBVH spatial splits) on a ~2M-triangle synthetic scene. Single thread.
// Build: c++ -O3 -std=c++17 -DNDEBUG bvh_bench.cpp -o bvh_bench && ./bvh_bench <out_dir> [cables=1000]
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <string>
#include <utility>
#include <vector>

struct V3 { float x, y, z; };
static inline V3 operator+(V3 a, V3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
static inline V3 operator-(V3 a, V3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
static inline V3 operator*(V3 a, float s) { return {a.x * s, a.y * s, a.z * s}; }
static inline float dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static inline V3 cross(V3 a, V3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
static inline V3 normalize(V3 a) { return a * (1.0f / std::sqrt(dot(a, a))); }
static inline V3 vmin(V3 a, V3 b) { return {std::min(a.x, b.x), std::min(a.y, b.y), std::min(a.z, b.z)}; }
static inline V3 vmax(V3 a, V3 b) { return {std::max(a.x, b.x), std::max(a.y, b.y), std::max(a.z, b.z)}; }
static inline float get(V3 a, int i) { return i == 0 ? a.x : (i == 1 ? a.y : a.z); }
static inline void set(V3& a, int i, float v) { (i == 0 ? a.x : (i == 1 ? a.y : a.z)) = v; }
constexpr float INF = std::numeric_limits<float>::infinity();

struct AABB {
  V3 lo{INF, INF, INF}, hi{-INF, -INF, -INF};
  void grow(V3 p) { lo = vmin(lo, p); hi = vmax(hi, p); }
  void grow(const AABB& b) { lo = vmin(lo, b.lo); hi = vmax(hi, b.hi); }
  bool empty() const { return lo.x > hi.x || lo.y > hi.y || lo.z > hi.z; }
  float area() const { if (empty()) return 0.0f; V3 e = hi - lo; return 2.0f * (e.x * e.y + e.y * e.z + e.z * e.x); }
  V3 center() const { return (lo + hi) * 0.5f; }
  int longest() const { V3 e = hi - lo; return e.x > e.y ? (e.x > e.z ? 0 : 2) : (e.y > e.z ? 1 : 2); }
};
struct Tri { V3 v0, v1, v2; };
struct Node { V3 lo; uint32_t leftFirst; V3 hi; uint32_t count; };  // 32 B; count > 0 marks a leaf
static_assert(sizeof(Node) == 32, "32-byte node");
struct Ref { AABB box; uint32_t tri; };                             // a (possibly clipped) triangle reference
struct BVH { std::vector<Node> nodes; std::vector<uint32_t> leafTri; };

constexpr float C_TRAV = 1.0f, C_ISECT = 1.0f;
constexpr uint32_t MAX_LEAF = 16;
enum class Method { Median, BinnedSAH };

static AABB triBox(const Tri& t) { AABB b; b.grow(t.v0); b.grow(t.v1); b.grow(t.v2); return b; }

static BVH build(std::vector<Ref> refs, Method method, int bins) {
  BVH b;
  const uint32_t n = uint32_t(refs.size());
  b.nodes.reserve(2 * size_t(n));
  AABB rootBox;
  for (const Ref& r : refs) rootBox.grow(r.box);
  b.nodes.push_back({rootBox.lo, 0, rootBox.hi, n});
  std::vector<uint32_t> stack{0};
  while (!stack.empty()) {
    const uint32_t ni = stack.back(); stack.pop_back();
    const uint32_t first = b.nodes[ni].leftFirst, count = b.nodes[ni].count;
    AABB cb;
    for (uint32_t i = first; i < first + count; ++i) cb.grow(refs[i].box.center());
    uint32_t mid = first;
    if (method == Method::Median) {
      if (count <= 4) continue;
      const int axis = cb.longest();
      mid = first + count / 2;
      std::nth_element(refs.begin() + first, refs.begin() + mid, refs.begin() + first + count,
                       [axis](const Ref& a, const Ref& c) { return get(a.box.center(), axis) < get(c.box.center(), axis); });
    } else {
      if (count <= 1) continue;
      float best = INF; int bestAxis = -1, bestBin = -1;
      for (int a = 0; a < 3; ++a) {
        const float lo = get(cb.lo, a), ext = get(cb.hi, a) - lo;
        if (!(ext > 0.0f)) continue;
        const float scale = float(bins) / ext;
        AABB bb[64]; uint32_t bc[64] = {};
        for (uint32_t i = first; i < first + count; ++i) {
          const int k = std::min(bins - 1, int((get(refs[i].box.center(), a) - lo) * scale));
          ++bc[k]; bb[k].grow(refs[i].box);
        }
        float leftArea[64]; uint32_t leftCount[64]; AABB acc; uint32_t sum = 0;
        for (int k = 0; k < bins - 1; ++k) { acc.grow(bb[k]); sum += bc[k]; leftArea[k] = acc.area(); leftCount[k] = sum; }
        acc = AABB(); sum = 0;
        for (int k = bins - 1; k >= 1; --k) {  // candidate plane between bin k-1 and bin k
          acc.grow(bb[k]); sum += bc[k];
          if (sum == 0 || leftCount[k - 1] == 0) continue;
          const float cost = float(leftCount[k - 1]) * leftArea[k - 1] + float(sum) * acc.area();
          if (cost < best) { best = cost; bestAxis = a; bestBin = k; }
        }
      }
      const AABB box{b.nodes[ni].lo, b.nodes[ni].hi};
      const float splitCost = C_TRAV + C_ISECT * best / box.area();
      const float leafCost = C_ISECT * float(count);
      if (bestAxis >= 0 && (splitCost < leafCost || count > MAX_LEAF)) {
        const float lo = get(cb.lo, bestAxis), scale = float(bins) / (get(cb.hi, bestAxis) - lo);
        auto it = std::partition(refs.begin() + first, refs.begin() + first + count, [&](const Ref& r) {
          return std::min(bins - 1, int((get(r.box.center(), bestAxis) - lo) * scale)) < bestBin; });
        mid = uint32_t(it - refs.begin());
      } else if (count > MAX_LEAF) {
        mid = first + count / 2;  // all centroids coincide: split the index range
      } else {
        continue;                 // SAH says leaf
      }
    }
    if (mid == first || mid == first + count) mid = first + count / 2;
    const uint32_t L = uint32_t(b.nodes.size());
    for (int side = 0; side < 2; ++side) {
      const uint32_t f = side ? mid : first, c = side ? first + count - mid : mid - first;
      AABB bx;
      for (uint32_t i = f; i < f + c; ++i) bx.grow(refs[i].box);
      b.nodes.push_back({bx.lo, f, bx.hi, c});
    }
    b.nodes[ni].leftFirst = L; b.nodes[ni].count = 0;
    stack.push_back(L); stack.push_back(L + 1);
  }
  b.leafTri.resize(n);
  for (uint32_t i = 0; i < n; ++i) b.leafTri[i] = refs[i].tri;
  return b;
}

static double sahCost(const BVH& b) {
  const double rootArea = AABB{b.nodes[0].lo, b.nodes[0].hi}.area();
  double c = 0.0;
  for (const Node& nd : b.nodes) {
    const double a = AABB{nd.lo, nd.hi}.area() / rootArea;
    c += nd.count ? a * nd.count * C_ISECT : a * C_TRAV;
  }
  return c;
}

static int maxDepth(const BVH& b) {
  std::vector<std::pair<uint32_t, int>> st{{0u, 1}};
  int md = 0;
  while (!st.empty()) {
    const auto [i, d] = st.back(); st.pop_back();
    md = std::max(md, d);
    if (!b.nodes[i].count) { st.push_back({b.nodes[i].leftFirst, d + 1}); st.push_back({b.nodes[i].leftFirst + 1, d + 1}); }
  }
  return md;
}

struct Ray { V3 o, d, rd; float t = INF; uint32_t tri = ~0u; };
static inline float safeRcp(float x) { return 1.0f / (std::fabs(x) > 1e-20f ? x : std::copysign(1e-20f, x)); }
static Ray makeRay(V3 o, V3 d) { Ray r; r.o = o; r.d = d; r.rd = {safeRcp(d.x), safeRcp(d.y), safeRcp(d.z)}; return r; }
constexpr float kEps = std::numeric_limits<float>::epsilon() * 0.5f;
constexpr float kGamma3 = 3.0f * kEps / (1.0f - 3.0f * kEps);

static inline float slab(const Ray& r, const Node& n) {  // entry distance or INF; Ize 2013 robust exit
  const float tx0 = (n.lo.x - r.o.x) * r.rd.x, tx1 = (n.hi.x - r.o.x) * r.rd.x;
  const float ty0 = (n.lo.y - r.o.y) * r.rd.y, ty1 = (n.hi.y - r.o.y) * r.rd.y;
  const float tz0 = (n.lo.z - r.o.z) * r.rd.z, tz1 = (n.hi.z - r.o.z) * r.rd.z;
  const float tn = std::max(std::max(std::min(tx0, tx1), std::min(ty0, ty1)), std::min(tz0, tz1));
  const float tf = std::min(std::min(std::max(tx0, tx1), std::max(ty0, ty1)), std::max(tz0, tz1)) * (1.0f + 2.0f * kGamma3);
  return (tn <= tf && tf > 0.0f && tn < r.t) ? tn : INF;
}

static inline void hitTri(Ray& r, const Tri& t, uint32_t id) {  // Moller-Trumbore
  const V3 e1 = t.v1 - t.v0, e2 = t.v2 - t.v0, p = cross(r.d, e2);
  const float det = dot(e1, p);
  if (std::fabs(det) < 1e-12f) return;
  const float inv = 1.0f / det;
  const V3 s = r.o - t.v0;
  const float u = dot(s, p) * inv;
  if (u < 0.0f || u > 1.0f) return;
  const V3 q = cross(s, e1);
  const float v = dot(r.d, q) * inv;
  if (v < 0.0f || u + v > 1.0f) return;
  const float tt = dot(e2, q) * inv;
  if (tt > 0.0f && tt < r.t) { r.t = tt; r.tri = id; }
}

struct Stats { uint64_t boxes = 0, tris = 0; };
static void trace(const BVH& b, const std::vector<Tri>& tris, Ray& r, Stats& st) {
  struct Entry { uint32_t node; float t; } stack[256];
  int sp = 0;
  st.boxes++;
  if (slab(r, b.nodes[0]) == INF) return;
  uint32_t ni = 0;
  for (;;) {
    const Node& n = b.nodes[ni];
    if (n.count) {
      for (uint32_t i = n.leftFirst; i < n.leftFirst + n.count; ++i) { st.tris++; hitTri(r, tris[b.leafTri[i]], b.leafTri[i]); }
    } else {
      uint32_t c0 = n.leftFirst, c1 = c0 + 1;
      float d0 = slab(r, b.nodes[c0]), d1 = slab(r, b.nodes[c1]);
      st.boxes += 2;
      if (d0 > d1) { std::swap(d0, d1); std::swap(c0, c1); }  // nearer child first
      if (d0 != INF) {
        if (d1 != INF) stack[sp++] = {c1, d1};
        ni = c0;
        continue;
      }
    }
    for (;;) {  // pop, skipping entries beyond the (shrunken) t_max
      if (sp == 0) return;
      const Entry e = stack[--sp];
      if (e.t < r.t) { ni = e.node; break; }
    }
  }
}

static AABB clipToBox(const Tri& t, const AABB& box) {  // AABB of (triangle intersect box), Sutherland-Hodgman
  V3 poly[16] = {t.v0, t.v1, t.v2}, tmp[16];
  int n = 3;
  for (int axis = 0; axis < 3 && n > 0; ++axis)
    for (int side = 0; side < 2 && n > 0; ++side) {
      const float plane = side ? get(box.hi, axis) : get(box.lo, axis);
      int m = 0;
      for (int i = 0; i < n; ++i) {
        const V3 a = poly[i], c = poly[(i + 1) % n];
        const float da = side ? plane - get(a, axis) : get(a, axis) - plane;
        const float dc = side ? plane - get(c, axis) : get(c, axis) - plane;
        if (da >= 0.0f) tmp[m++] = a;
        if ((da >= 0.0f) != (dc >= 0.0f)) tmp[m++] = a + (c - a) * (da / (da - dc));
      }
      n = m;
      std::copy(tmp, tmp + n, poly);
    }
  AABB r;
  for (int i = 0; i < n; ++i) r.grow(poly[i]);
  if (!r.empty()) { r.lo = vmax(r.lo, box.lo); r.hi = vmin(r.hi, box.hi); }
  return r;
}

static void escSplit(const Tri& t, uint32_t id, const AABB& box, float maxArea, int depth, std::vector<Ref>& out) {
  if (box.area() <= maxArea || depth >= 20) { out.push_back({box, id}); return; }
  const int axis = box.longest();
  const float mid = 0.5f * (get(box.lo, axis) + get(box.hi, axis));
  AABB l = box, r = box;
  set(l.hi, axis, mid); set(r.lo, axis, mid);
  const AABB lc = clipToBox(t, l), rc = clipToBox(t, r);
  if (!lc.empty()) escSplit(t, id, lc, maxArea, depth + 1, out);
  if (!rc.empty()) escSplit(t, id, rc, maxArea, depth + 1, out);
}

struct Rng {  // PCG32
  uint64_t s = 0, inc = 0xda3e39cb94b95bdbull;
  explicit Rng(uint64_t seed) { next(); s += seed; next(); }
  uint32_t next() {
    const uint64_t old = s; s = old * 6364136223846793005ull + inc;
    const uint32_t xs = uint32_t(((old >> 18u) ^ old) >> 27u), rot = uint32_t(old >> 59u);
    return (xs >> rot) | (xs << ((32u - rot) & 31u));
  }
  float uni() { return float(next() >> 8) * (1.0f / 16777216.0f); }
  float range(float a, float b) { return a + (b - a) * uni(); }
};

static float terrainH(float x, float y) { return 1.5f * std::sin(0.11f * x) * std::cos(0.07f * y) + 0.4f * std::sin(0.53f * x + 0.31f * y); }

static std::vector<Tri> makeScene(int cables) {
  std::vector<Tri> t;
  t.reserve(2'010'000);
  Rng rng(42);
  const float PI = 3.14159265f;
  const int G = 708;  // 707 x 707 quads = 999,698 terrain triangles over 100 m x 100 m
  auto tv = [&](int i, int j) { const float x = -50.0f + 100.0f * i / (G - 1), y = -50.0f + 100.0f * j / (G - 1); return V3{x, y, terrainH(x, y)}; };
  for (int i = 0; i < G - 1; ++i)
    for (int j = 0; j < G - 1; ++j) {
      const V3 a = tv(i, j), b = tv(i + 1, j), c = tv(i + 1, j + 1), d = tv(i, j + 1);
      t.push_back({a, b, c}); t.push_back({a, c, d});
    }
  for (int cl = 0; cl < 10; ++cl) {  // 10 clusters x 50 rocks x 1,000 triangles (UV spheres, degenerate at the poles)
    const float cx = rng.range(-40, 40), cy = rng.range(-40, 40);
    for (int k = 0; k < 50; ++k) {
      const float r = rng.range(0.5f, 3.0f), px = cx + rng.range(-6, 6), py = cy + rng.range(-6, 6), ph = rng.range(0, 6.283f);
      const V3 c{px, py, terrainH(px, py) + 0.3f * r};
      auto sv = [&](int a, int bb) {
        const float th = PI * a / 20, phi = 2 * PI * bb / 25;
        const float rr = r * (1.0f + 0.12f * std::sin(th) * std::sin(5 * th + ph) * std::cos(3 * phi + ph));
        return c + V3{std::sin(th) * std::cos(phi), std::sin(th) * std::sin(phi), std::cos(th)} * rr;
      };
      for (int a = 0; a < 20; ++a)
        for (int bb = 0; bb < 25; ++bb) {
          const V3 p00 = sv(a, bb), p10 = sv(a + 1, bb), p11 = sv(a + 1, bb + 1), p01 = sv(a, bb + 1);
          t.push_back({p00, p10, p11}); t.push_back({p00, p11, p01});
        }
    }
  }
  const V3 tc{0, 0, terrainH(0, 0) + 6.0f};  // dense torus "statue": 500 x 500 quads = 500,000 triangles
  auto torus = [&](int i, int j) {
    const float u = 2 * PI * i / 500, v = 2 * PI * j / 500;
    return tc + V3{(8.0f + 3.0f * std::cos(v)) * std::cos(u), (8.0f + 3.0f * std::cos(v)) * std::sin(u), 3.0f * std::sin(v)};
  };
  for (int i = 0; i < 500; ++i)
    for (int j = 0; j < 500; ++j) {
      const V3 a = torus(i, j), b = torus(i + 1, j), c = torus(i + 1, j + 1), d = torus(i, j + 1);
      t.push_back({a, b, c}); t.push_back({a, c, d});
    }
  for (int k = 0; k < cables; ++k) {  // long thin "cables" (default 1,000 = 2,000 triangles, up to ~140 m long, 5 cm wide)
    const V3 a{rng.range(-50, 50), rng.range(-50, 50), rng.range(5, 20)}, b{rng.range(-50, 50), rng.range(-50, 50), rng.range(5, 20)};
    const V3 side = normalize(cross(b - a, V3{0, 0, 1})) * 0.05f;
    t.push_back({a, b, b + side}); t.push_back({a, b + side, a + side});
  }
  return t;
}

static void onb(V3 n, V3& t, V3& b) {  // Duff et al. 2017
  const float s = std::copysign(1.0f, n.z), a = -1.0f / (s + n.z), c = n.x * n.y * a;
  t = {1.0f + s * n.x * n.x * a, s * c, -s * n.x};
  b = {c, s + n.y * n.y * a, -n.y};
}

static void writePGM(const std::string& path, const std::vector<uint16_t>& v, int w, int h, float scale) {
  FILE* f = std::fopen(path.c_str(), "wb");
  if (!f) return;
  std::fprintf(f, "P5\n%d %d\n255\n", w, h);
  for (uint16_t x : v) std::fputc(std::min(255, int(x * scale)), f);
  std::fclose(f);
}

int main(int argc, char** argv) {
  using clk = std::chrono::steady_clock;
  auto ms = [](clk::time_point a, clk::time_point b) { return std::chrono::duration<double, std::milli>(b - a).count(); };
  const std::string out = argc > 1 ? argv[1] : ".";
  const int cables = argc > 2 ? std::atoi(argv[2]) : 1000;
  const std::vector<Tri> tris = makeScene(cables);
  std::vector<Ref> base(tris.size());
  AABB scene;
  size_t degenerate = 0;
  for (uint32_t i = 0; i < tris.size(); ++i) {
    base[i] = {triBox(tris[i]), i};
    scene.grow(base[i].box);
    const V3 cr = cross(tris[i].v1 - tris[i].v0, tris[i].v2 - tris[i].v0);
    if (dot(cr, cr) == 0.0f) ++degenerate;
  }
  std::printf("triangles %zu (zero-area %zu), scene box area %.0f m^2\n", tris.size(), degenerate, scene.area());

  const float maxArea = scene.area() * 1e-4f;
  const auto e0 = clk::now();
  std::vector<Ref> esc;
  esc.reserve(base.size() + 400000);
  for (uint32_t i = 0; i < tris.size(); ++i) {
    if (base[i].box.area() > maxArea) escSplit(tris[i], i, base[i].box, maxArea, 0, esc);
    else esc.push_back(base[i]);
  }
  const double escMs = ms(e0, clk::now());

  const int RES = 1024;
  const V3 eye{-70, -70, 45}, target{0, 0, 0};
  const V3 fwd = normalize(target - eye), right = normalize(cross(fwd, V3{0, 0, 1})), up = cross(right, fwd);
  const float th = std::tan(0.5f * 50.0f * 3.14159265f / 180.0f);
  std::vector<Ray> primary;
  primary.reserve(size_t(RES) * RES);
  for (int y = 0; y < RES; ++y)
    for (int x = 0; x < RES; ++x) {
      const float sx = (2.0f * (x + 0.5f) / RES - 1.0f) * th, sy = (1.0f - 2.0f * (y + 0.5f) / RES) * th;
      primary.push_back(makeRay(eye, normalize(fwd + right * sx + up * sy)));
    }

  struct Config { const char* name; Method m; int bins; const std::vector<Ref>* refs; double extraMs; };
  const Config cfgs[] = {{"median split", Method::Median, 0, &base, 0.0},
                         {"binned SAH, 16 bins", Method::BinnedSAH, 16, &base, 0.0},
                         {"binned SAH + ESC", Method::BinnedSAH, 16, &esc, escMs}};
  std::vector<Ray> diffuse;  // built once from the first configuration's primary hits, reused by all
  int idx = 0;
  for (const Config& c : cfgs) {
    const auto b0 = clk::now();
    const BVH bvh = build(*c.refs, c.m, c.bins);
    const double buildMs = ms(b0, clk::now()) + c.extraMs;

    std::vector<Ray> rays = primary;
    std::vector<uint16_t> heat(rays.size());
    Stats sp;
    const auto p0 = clk::now();
    for (size_t i = 0; i < rays.size(); ++i) {
      const uint64_t before = sp.boxes;
      trace(bvh, tris, rays[i], sp);
      heat[i] = uint16_t(std::min<uint64_t>(sp.boxes - before, 65535));
    }
    const double primMs = ms(p0, clk::now());
    if (diffuse.empty()) {
      Rng rng(7);
      for (const Ray& r : rays) {
        if (!(r.t < INF)) continue;
        const Tri& t = tris[r.tri];
        V3 n = normalize(cross(t.v1 - t.v0, t.v2 - t.v0));
        if (dot(n, r.d) > 0.0f) n = n * -1.0f;
        V3 tt, bb; onb(n, tt, bb);
        const float u1 = rng.uni(), u2 = rng.uni(), rad = std::sqrt(u1), phi = 6.2831853f * u2;
        const V3 d = normalize(tt * (rad * std::cos(phi)) + bb * (rad * std::sin(phi)) + n * std::sqrt(std::max(0.0f, 1.0f - u1)));
        diffuse.push_back(makeRay(r.o + r.d * r.t + n * 1e-3f, d));
      }
    }
    std::vector<Ray> drays = diffuse;
    Stats sd;
    const auto d0 = clk::now();
    for (Ray& r : drays) trace(bvh, tris, r, sd);
    const double difMs = ms(d0, clk::now());

    size_t ph = 0, dh = 0; double pt = 0.0, dt = 0.0;
    for (const Ray& r : rays) if (r.t < INF) { ++ph; pt += r.t; }
    for (const Ray& r : drays) if (r.t < INF) { ++dh; dt += r.t; }
    std::vector<uint16_t> sorted = heat;
    std::nth_element(sorted.begin(), sorted.begin() + sorted.size() * 99 / 100, sorted.end());
    std::printf("\n[%s]\n refs %zu, nodes %zu (%.1f MB), max depth %d, build %.0f ms, SAH cost %.1f\n", c.name,
                c.refs->size(), bvh.nodes.size(), (bvh.nodes.size() * 32.0 + bvh.leafTri.size() * 4.0) / 1e6,
                maxDepth(bvh), buildMs, sahCost(bvh));
    std::printf(" primary: %zu rays, %.2f Mrays/s, %.1f box tests/ray (p99 %u), %.1f tri tests/ray, hits %zu, sum t %.6e\n",
                rays.size(), rays.size() / primMs / 1e3, double(sp.boxes) / rays.size(), unsigned(sorted[sorted.size() * 99 / 100]),
                double(sp.tris) / rays.size(), ph, pt);
    std::printf(" diffuse: %zu rays, %.2f Mrays/s, %.1f box tests/ray, %.1f tri tests/ray, hits %zu, sum t %.6e\n",
                drays.size(), drays.size() / difMs / 1e3, double(sd.boxes) / drays.size(), double(sd.tris) / drays.size(), dh, dt);
    writePGM(out + "/heat_" + std::to_string(idx++) + ".pgm", heat, RES, RES, 255.0f / 400.0f);
  }
  return 0;
}
```

## Recorded output (Apple M3 Ultra, Apple clang 21.0.0, -O3, one thread)

With the default 1,000 cables:

```text
triangles 2001698 (zero-area 12514), scene box area 29459 m^2

[median split]
 refs 2001698, nodes 1048575 (41.6 MB), max depth 20, build 329 ms, SAH cost 1023.7
 primary: 1048576 rays, 0.15 Mrays/s, 799.2 box tests/ray (p99 2259), 297.5 tri tests/ray, hits 576472, sum t 5.101107e+07
 diffuse: 576472 rays, 0.09 Mrays/s, 1097.3 box tests/ray, 408.3 tri tests/ray, hits 136692, sum t 1.646553e+06

[binned SAH, 16 bins]
 refs 2001698, nodes 2056369 (73.8 MB), max depth 28, build 853 ms, SAH cost 510.4
 primary: 1048576 rays, 0.37 Mrays/s, 364.6 box tests/ray (p99 1193), 151.6 tri tests/ray, hits 576472, sum t 5.101107e+07
 diffuse: 576472 rays, 0.19 Mrays/s, 499.8 box tests/ray, 204.8 tri tests/ray, hits 136692, sum t 1.646553e+06

[binned SAH + ESC]
 refs 2082222, nodes 2138517 (76.8 MB), max depth 28, build 921 ms, SAH cost 115.2
 primary: 1048576 rays, 1.11 Mrays/s, 114.1 box tests/ray (p99 475), 4.2 tri tests/ray, hits 576472, sum t 5.101107e+07
 diffuse: 576472 rays, 0.76 Mrays/s, 129.4 box tests/ray, 6.3 tri tests/ray, hits 136692, sum t 1.646553e+06
```

With `cables = 0`:

```text
triangles 1999698 (zero-area 12514), scene box area 25062 m^2

[median split]
 refs 1999698, nodes 1048575 (41.6 MB), max depth 20, build 334 ms, SAH cost 92.7
 primary: 1048576 rays, 2.79 Mrays/s, 35.2 box tests/ray (p99 151), 5.6 tri tests/ray, hits 552647, sum t 5.025123e+07
 diffuse: 552647 rays, 1.45 Mrays/s, 62.1 box tests/ray, 10.8 tri tests/ray, hits 59174, sum t 4.286749e+05

[binned SAH, 16 bins]
 refs 1999698, nodes 2056255 (73.8 MB), max depth 28, build 833 ms, SAH cost 64.1
 primary: 1048576 rays, 3.71 Mrays/s, 30.1 box tests/ray (p99 121), 1.6 tri tests/ray, hits 552647, sum t 5.025123e+07
 diffuse: 552647 rays, 1.92 Mrays/s, 54.2 box tests/ray, 3.2 tri tests/ray, hits 59174, sum t 4.286749e+05

[binned SAH + ESC]
 refs 1999698, nodes 2056255 (73.8 MB), max depth 28, build 835 ms, SAH cost 64.1
 primary: 1048576 rays, 3.73 Mrays/s, 30.1 box tests/ray (p99 121), 1.6 tri tests/ray, hits 552647, sum t 5.025123e+07
 diffuse: 552647 rays, 1.95 Mrays/s, 54.2 box tests/ray, 3.2 tri tests/ray, hits 59174, sum t 4.286749e+05
```
