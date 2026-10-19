# Twisted-column experiment (CPU reference)

Reproduces the numbers in section 11 of the `sdf-modeling-raymarching` skill: a vectorised numpy
sphere tracer over the same scene, comparing step strategies against a conservative reference.
Run with `uv run --no-project --with numpy python twisted_columns.py` (a few seconds). The
counts depend on the camera and resolution; the ratios are what transfer to the GPU version.

```python
import math
import numpy as np

A, K, RB, CELL, LIM = 0.5, 4.14, 0.75, 3.0, 3       # half-width, twist rad/m, bound, cell, +-cells

def col_local(q):                                    # twisted square column, infinite in y
    x, y, z = q[..., 0], q[..., 1], q[..., 2]
    c, s = np.cos(K * y), np.sin(K * y)
    dx, dz = np.abs(c * x - s * z) - A, np.abs(s * x + c * z) - A
    return np.hypot(np.maximum(dx, 0), np.maximum(dz, 0)) + np.minimum(np.maximum(dx, dz), 0)

def scene(p, L_tw, global_div=1.0, ret_id=False):
    idx = np.clip(np.round(p[..., [0, 2]] / CELL), -LIM, LIM)
    q = p.copy(); q[..., 0] -= idx[..., 0] * CELL; q[..., 2] -= idx[..., 1] * CELL
    rho = np.hypot(q[..., 0], q[..., 2])
    dcol = np.where(rho > RB + 0.1, rho - RB, col_local(q) / L_tw)   # divide the sub-tree only
    dplanes = np.minimum(p[..., 1], 4.0 - p[..., 1])
    d = np.minimum(dcol, dplanes) / global_div
    return (d, np.where(dcol <= dplanes, 0, 1)) if ret_id else d

# 1) Lipschitz estimate by sampling
rng = np.random.default_rng(1)
P = np.column_stack([rng.uniform(-1.5, 1.5, 400_000), rng.uniform(0, 4, 400_000),
                     rng.uniform(-1.5, 1.5, 400_000)])
g = np.stack([(col_local(P + 1e-4 * e) - col_local(P - 1e-4 * e)) / 2e-4 for e in np.eye(3)], 1)
gn = np.linalg.norm(g, axis=1)
print(f"max {gn.max():.3f} p99.9 {np.percentile(gn, 99.9):.3f} median {np.median(gn):.3f} "
      f"analytic {math.sqrt(1 + (K * A) ** 2):.3f}")

# 2) camera rays
W, H = 480, 270
tanh = math.tan(math.radians(60) / 2)
ro0, tgt = np.array([-10.0, 2.0, -11.0]), np.array([0.0, 1.5, 0.0])
fwd = (tgt - ro0) / np.linalg.norm(tgt - ro0)
right = np.cross(fwd, [0, 1, 0]); right /= np.linalg.norm(right); up = np.cross(right, fwd)
ii, jj = np.meshgrid(np.arange(W), np.arange(H))
u = (2 * (ii + 0.5) / W - 1) * tanh * W / H; v = (1 - 2 * (jj + 0.5) / H) * tanh
rd = fwd + u[..., None] * right + v[..., None] * up
rd = (rd / np.linalg.norm(rd, axis=-1, keepdims=True)).reshape(-1, 3)
ro = np.broadcast_to(ro0, rd.shape)
pix = 2 * tanh / H                                   # pixel angle

def trace(L_tw, omega=1.0, max_steps=256, eps_px=0.5, tmax=60.0, global_div=1.0):
    n = len(rd)
    t = np.full(n, 0.05); steps = np.zeros(n, int); done = np.zeros(n, bool); hit = np.zeros(n, bool)
    prev_r = np.zeros(n); step = np.zeros(n); om = np.full(n, omega)
    for _ in range(max_steps):
        a = np.nonzero(~done)[0]
        if a.size == 0:
            break
        d = scene(ro[a] + rd[a] * t[a, None], L_tw, global_div); steps[a] += 1
        r = np.abs(d)
        fail = (om[a] > 1) & (r + prev_r[a] < step[a])          # relaxation fallback
        fa = a[fail]
        t[fa] += prev_r[fa] - step[fa]; step[fa] = prev_r[fa]; om[fa] = 1.0
        ok, dok = a[~fail], d[~fail]
        h = dok < eps_px * pix * t[ok]
        hit[ok[h]] = True; done[ok[h]] = True
        go, dg = ok[~h], dok[~h]
        step[go] = om[go] * dg; prev_r[go] = np.abs(dg); t[go] += step[go]
        done[go[t[go] > tmax]] = True
    return t, hit, steps, ~done

t_ref, hit_ref, _, _ = trace(2.5, 1.0, 4000, 0.25)   # conservative reference
_, oid = scene(ro + rd * t_ref[:, None], 2.5, ret_id=True)
colpix = hit_ref & (oid == 0)
for name, L, om_, gd in (("naive L=1", 1.0, 1.0, 1.0), ("global /2.3", 1.0, 1.0, 2.3),
                         ("local /2.3", 2.3, 1.0, 1.0), ("local /2.3 omega 1.2", 2.3, 1.2, 1.0),
                         ("local /2.3 omega 1.6", 2.3, 1.6, 1.0)):
    t, hit, st, cap = trace(L, om_, 256, 0.5, global_div=gd)
    holes = colpix & (~hit | (t > t_ref + 0.05))       # passed through a column
    pen = hit & (scene(ro + rd * t[:, None], 1.0) < -0.5 * pix * t)   # stopped inside geometry
    print(f"{name:22s} holes {holes.sum():5d} penetrating {pen.sum():6d} capped {cap.sum():3d} "
          f"mean {st.mean():5.1f} p95 {np.percentile(st, 95):4.0f} max {st.max()}")
```

Recorded output (numpy 2.x, CPU):

```text
max 2.298 p99.9 2.297 median 1.433 analytic 2.299
naive L=1              holes  9213 penetrating  18163 capped   0 mean  16.4 p95   42 max 155
global /2.3            holes     0 penetrating      0 capped  36 mean  35.9 p95   84 max 256
local /2.3             holes     0 penetrating      0 capped   0 mean  20.5 p95   49 max 187
local /2.3 omega 1.2   holes     0 penetrating      0 capped   0 mean  20.0 p95   48 max 188
local /2.3 omega 1.6   holes     0 penetrating      0 capped   0 mean  21.0 p95   50 max 188
```

Porting notes: the GLSL `map()` in the skill is the same field; on the GPU replace the step
counters with a per-pixel step-count output for the heatmap and time the pass with timestamp
queries (median over 300 frames).
