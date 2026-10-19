# ReSTIR toy experiment

NumPy model of many-light direct illumination used for the worked example in SKILL.md. 10,000 small
one-sided emitters ("triangles" treated as points with area) 2-5 m above a 10 x 10 m Lambert floor
(albedo 0.5) sampled at 64 x 64 shading points; radiance is log-normal (sigma 1.5) with 1% of lights
x100, so power max/median is about 2,900; 12 horizontal occluder slabs shadow 47% of point-light pairs.
The target p_hat is the unshadowed contribution f Le A cos_x cos_l / d^2; visibility is exact and binary.
The reference sums every light with visibility, so relMSE needs no converged render.

ReSTIR modes: `none` = no visibility reuse and 1/M weights (unbiased here because every p_hat is
positive); `biased` = visibility reuse of the initial and final sample with 1/M weights; `unbiased` =
the same reuse with Bitterli's 1/Z normalisation, where Z sums M over the domains whose support contains
the selected sample (one shadow ray per spatial neighbour). Costs are counted as shadow rays per pixel;
candidate evaluation is treated as free, so this is a proxy for an equal-time GPU comparison.

Run: `uv run --no-project --with numpy python restir_toy.py` (about 2 s).

## Script

```python
#!/usr/bin/env python3
"""Toy many-light DI experiment: 10k small one-sided emissive triangles (point-like, facing down), a
64x64 floor of Lambert shading points and 12 rectangular occluders. Compares uniform light selection,
a power-proportional alias table (Vose), RIS with 32 candidates and ReSTIR DI (RIS-32 + temporal +
spatial reuse) with three visibility/normalisation modes. Target p_hat = unshadowed contribution;
shading uses exact binary visibility. The reference is the exact sum over all lights with visibility.
Run: uv run --no-project --with numpy python restir_toy.py"""
import math
import time

import numpy as np

rng = np.random.default_rng(2024)
W = H = 64
P = W * H
NL = 10_000
rows = np.arange(P)
px, py = rows % W, rows // W
X = np.stack([(px + 0.5) * 10.0 / W, (py + 0.5) * 10.0 / H, np.zeros(P)], 1).astype(np.float32)
F_LAMBERT = 0.5 / math.pi
Lpos = np.stack([rng.uniform(-2, 12, NL), rng.uniform(-2, 12, NL), rng.uniform(2, 5, NL)], 1).astype(np.float32)
Larea = rng.uniform(1e-3, 1e-2, NL)
Le = np.exp(rng.normal(0.0, 1.5, NL))
Le[rng.random(NL) < 0.01] *= 100.0
Phi = math.pi * Le * Larea  # power of a one-sided Lambertian emitter
OCC = []
for _ in range(12):
    cx, cy = rng.uniform(1, 9, 2)
    sx, sy = rng.uniform(0.5, 1.5, 2)
    OCC.append((cx - sx, cx + sx, cy - sy, cy + sy, rng.uniform(0.5, 1.5)))


def contributions(xs):
    d = Lpos[None, :, :] - xs[:, None, :]
    d2 = (d * d).sum(-1)
    dz = d[..., 2]
    ph = (F_LAMBERT * Le * Larea)[None, :] * dz * dz / (d2 * d2)  # f Le A cos_x cos_l / d^2, cos = dz/d
    vis = np.ones(ph.shape, bool)
    for x0, x1, y0, y1, h in OCC:
        t = h / dz
        qx = xs[:, None, 0] + t * d[..., 0]
        qy = xs[:, None, 1] + t * d[..., 1]
        vis &= ~((qx >= x0) & (qx <= x1) & (qy >= y0) & (qy <= y1))
    return ph.astype(np.float32), vis


t0 = time.time()
PH = np.empty((P, NL), np.float32)
V = np.empty((P, NL), bool)
for s in range(0, P, 256):
    PH[s:s + 256], V[s:s + 256] = contributions(X[s:s + 256])
REF = (PH * V).sum(1, dtype=np.float64)
print(f"precompute {time.time() - t0:.1f} s; shadowed pairs {1 - V.mean():.3f}; "
      f"power max/median {Phi.max() / np.median(Phi):.0f}")


def build_alias(w):
    """Vose alias table: O(n) build, O(1) sampling."""
    n = len(w)
    p = w * (n / w.sum())
    prob, alias = np.ones(n), np.arange(n)
    small = [i for i in range(n) if p[i] < 1.0]
    large = [i for i in range(n) if p[i] >= 1.0]
    while small and large:
        s, l = small.pop(), large.pop()
        prob[s], alias[s] = p[s], l
        p[l] = (p[l] + p[s]) - 1.0
        (small if p[l] < 1.0 else large).append(l)
    return prob, alias  # leftovers keep prob 1 (round-off)


PROB, ALIAS = build_alias(Phi)
PMF = Phi / Phi.sum()


def sample_alias(shape):
    i = np.minimum((rng.random(shape) * NL).astype(np.int64), NL - 1)
    return np.where(rng.random(shape) < PROB[i], i, ALIAS[i])


freq = np.bincount(sample_alias(4_000_000), minlength=NL) / 4e6
print(f"alias check: max |freq - pmf| {np.abs(freq - PMF).max():.2e} (max pmf {PMF.max():.2e})")


def relmse(est):
    m = REF.mean()
    r, e = REF / m, est / m
    return float(np.mean((e - r) ** 2 / (r * r + 1e-2)))


def shade(y, wc):
    return PH[rows, y] * V[rows, y] * wc  # one shadow ray for the survivor


def pick(ws):
    tot = ws.sum(1)
    k = np.minimum((np.cumsum(ws, 1) <= (rng.random(P) * tot)[:, None]).sum(1), ws.shape[1] - 1)
    return k, tot


def ris(m=32):
    j = sample_alias((P, m))
    ws = PH[rows[:, None], j] / (m * PMF[j])  # m_i p_hat / p with m_i = 1/M
    k, tot = pick(ws)
    y = j[rows, k]
    ph = PH[rows, y]
    return y, np.where(ph > 0, tot / np.maximum(ph, 1e-30), 0.0), np.full(P, float(m))


def combine(res, z_mode=False):
    """res: list of (y, W, M, domain_pixel). Selection weight M_i p_hat_q(y_i) W_i; then W = sum / (D p_hat_q(y))
    with D = sum M (the '1/M' weights) or D = Z(y) = sum of M_i over domains whose support contains y
    (Bitterli 2020 '1/Z', one shadow ray per domain)."""
    ws = np.stack([r[2] * PH[rows, r[0]] * r[1] for r in res], 1)
    ys = np.stack([r[0] for r in res], 1)
    k, tot = pick(ws)
    y = ys[rows, k]
    ph = PH[rows, y]
    msum = sum(r[2] for r in res)
    d = sum(r[2] * V[r[3], y] for r in res) if z_mode else msum
    return y, np.where((tot > 0) & (ph > 0) & (d > 0), tot / np.maximum(d * ph, 1e-30), 0.0), msum


def neighbour_pixels(radius=5.0, k=5):
    out = []
    for _ in range(k):
        r = radius * np.sqrt(rng.random(P))
        a = 2 * math.pi * rng.random(P)
        nx = np.clip(px + np.rint(r * np.cos(a)).astype(int), 0, W - 1)
        ny = np.clip(py + np.rint(r * np.sin(a)).astype(int), 0, H - 1)
        out.append(ny * W + nx)
    return out


FRAMES, WARM = 24, 8


def run_static(fn):
    errs, means = [], []
    for _ in range(FRAMES - WARM):
        est = fn()
        errs.append(relmse(est))
        means.append(est.mean())
    return float(np.mean(errs)), float(np.mean(means) / REF.mean() - 1.0)


def uniform():
    j = rng.integers(0, NL, P)
    return NL * PH[rows, j] * V[rows, j]


def alias_est(n=1):
    acc = np.zeros(P)
    for _ in range(n):
        j = sample_alias(P)
        acc += PH[rows, j] * V[rows, j] / PMF[j]
    return acc / n


def restir(mode, m_cap=20 * 32):
    """mode 'none': no visibility reuse, 1/M (unbiased here: every p_hat > 0). 'biased': visibility reuse of the
    initial and the final sample, 1/M. 'unbiased': same reuse, 1/Z with ray-traced Z in the spatial pass."""
    vis = mode != "none"
    prev, errs, means = None, [], []
    for f in range(FRAMES):
        y, wc, m = ris(32)
        if vis:  # trace the survivor before reuse, zero W if occluded
            wc = np.where(V[rows, y], wc, 0.0)
        if prev is not None:  # temporal: same pixel, both supports are {V_q = 1}, so 1/M equals 1/Z
            y, wc, m = combine([(y, wc, m, rows), (prev[0], prev[1], np.minimum(prev[2], m_cap), rows)])
        nb = [(y[i], wc[i], m[i], i) for i in neighbour_pixels()]
        y, wc, m = combine([(y, wc, m, rows)] + nb, z_mode=(mode == "unbiased"))
        est = shade(y, wc)
        if vis:  # final visibility reuse: the shading ray also restricts the stored reservoir
            wc = np.where(V[rows, y], wc, 0.0)
        prev = (y, wc, m)
        if f >= WARM:
            errs.append(relmse(est))
            means.append(est.mean())
    return float(np.mean(errs)), float(np.mean(means) / REF.mean() - 1.0)


results = [
    ("uniform selection", 1, 1, *run_static(uniform)),
    ("power alias table", 1, 1, *run_static(alias_est)),
    ("power alias table, 2 samples", 2, 2, *run_static(lambda: alias_est(2))),
    ("power alias table, 7 samples", 7, 7, *run_static(lambda: alias_est(7))),
    ("RIS, 32 candidates", 1, 32, *run_static(lambda: shade(*ris(32)[:2]))),
    ("ReSTIR DI T+S, no visibility reuse", 1, 38, *restir("none")),
    ("ReSTIR DI T+S, visibility reuse, 1/M", 2, 38, *restir("biased")),
    ("ReSTIR DI T+S, visibility reuse, 1/Z", 7, 38, *restir("unbiased")),
]
print(f"{'strategy':38s} {'rays/px':>7s} {'cand/px':>7s} {'relMSE':>10s} {'mean bias':>10s}")
for name, rays, cand, err, bias in results:
    print(f"{name:38s} {rays:7d} {cand:7d} {err:10.4f} {bias:+10.4f}")
```

## Recorded output (seed 2024)

```text
precompute 1.5 s; shadowed pairs 0.470; power max/median 2868
alias check: max |freq - pmf| 8.76e-05 (max pmf 4.63e-02)
strategy                               rays/px cand/px     relMSE  mean bias
uniform selection                            1       1   345.1534    -0.0464
power alias table                            1       1     5.6916    -0.0014
power alias table, 2 samples                 2       2     2.7605    +0.0031
power alias table, 7 samples                 7       7     0.7885    +0.0022
RIS, 32 candidates                           1      32     1.6047    +0.0007
ReSTIR DI T+S, no visibility reuse           1      38     1.4461    +0.0100
ReSTIR DI T+S, visibility reuse, 1/M         2      38     0.2584    -0.3578
ReSTIR DI T+S, visibility reuse, 1/Z         7      38     0.5594    +0.0296
```

## Bias across seeds

Six more seeds (11-16, 24 frames): the 1/M visibility-reuse mean bias ranged from -0.27 to -0.43 on
every seed; 1/Z ranged from -0.010 to +0.030. Twelve further seeds (21-32, 48 frames each), mean bias
+- standard error: no visibility reuse -0.0004 +- 0.0062, 1/Z +0.0007 +- 0.0045. A single seed's mean
bias is noisy because reservoirs are correlated across pixels and frames; judge bias over seeds.
