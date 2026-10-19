# Two-joint arm experiment: LBS vs DQS

Reproduces the table in section 11 of the `skeletal-animation-skinning` skill. numpy only; run
with `uv run --no-project --with numpy python arm.py`. Quaternions are (w, x, y, z).

```python
import math
import numpy as np

def quat_from_matrix(R):                      # Shepperd's method, robust for any rotation
    tr = np.trace(R)
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return np.array([0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s])
    i = int(np.argmax(np.diag(R))); j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
    q = np.zeros(4)
    q[0] = (R[k, j] - R[j, k]) / s; q[1 + i] = 0.25 * s
    q[1 + j] = (R[j, i] + R[i, j]) / s; q[1 + k] = (R[k, i] + R[i, k]) / s
    return q

def qmul(a, b):
    return np.r_[a[0] * b[0] - a[1:] @ b[1:], a[0] * b[1:] + b[0] * a[1:] + np.cross(a[1:], b[1:])]

def skin_lbs(V, W, M):
    return np.einsum("nj,jab,nb->na", W, M, np.c_[V, np.ones(len(V))])[:, :3]

def skin_dqs(V, W, M):
    R = np.array([quat_from_matrix(m[:3, :3]) for m in M])
    D = np.array([0.5 * qmul(np.r_[0.0, m[:3, 3]], r) for m, r in zip(M, R)])
    sgn = np.sign(R[np.argmax(W, 1)] @ R.T); sgn[sgn == 0] = 1
    br, bd = (W * sgn) @ R, (W * sgn) @ D
    n = np.linalg.norm(br, axis=1, keepdims=True); br, bd = br / n, bd / n
    w, v, we, ve = br[:, :1], br[:, 1:], bd[:, :1], bd[:, 1:]
    return V + 2 * np.cross(v, np.cross(v, V) + w * V) + 2 * (w * ve - we * v + np.cross(v, ve))

# arm mesh: 121 rings x 48 segments, radius 5 cm, length 0.6 m, capped
nr, ns, r0, length = 121, 48, 0.05, 0.6
xs = np.linspace(0, length, nr); ph = np.linspace(0, 2 * np.pi, ns, endpoint=False)
V = np.array([[x, r0 * math.cos(p), r0 * math.sin(p)] for x in xs for p in ph] + [[0, 0, 0], [length, 0, 0]])
F = []
for i in range(nr - 1):
    for j in range(ns):
        a, b = i * ns + j, i * ns + (j + 1) % ns
        F += [[a, b, a + ns], [b, b + ns, a + ns]]           # outward winding
c0, c1 = nr * ns, nr * ns + 1
for j in range(ns):
    F += [[c0, (j + 1) % ns, j], [c1, (nr - 1) * ns + j, (nr - 1) * ns + (j + 1) % ns]]
F = np.array(F)

def volume(P):
    return np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum() / 6

def ring_area(P, i):
    ring = P[i * ns:(i + 1) * ns]; c = ring.mean(0)
    return 0.5 * np.linalg.norm(np.cross(ring - c, np.roll(ring, -1, 0) - c).sum(0))

t = np.clip((V[:, 0] - 0.25) / 0.1, 0, 1); w1 = t * t * (3 - 2 * t)
W = np.c_[1 - w1, w1]                                          # shoulder, elbow
elbow = np.array([0.3, 0, 0])

def palette(R):                                                # shoulder identity, elbow rotates about itself
    M1 = np.eye(4); M1[:3, :3] = R; M1[:3, 3] = elbow - R @ elbow
    return np.array([np.eye(4), M1])

def rot(axis, deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return {"z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]),
            "x": np.array([[1.0, 0, 0], [0, c, -s], [0, s, c]])}[axis]

V0, A0 = volume(V), ring_area(V, 60)
print(f"vertices {len(V)} triangles {len(F)} bind volume {V0 * 1e6:.1f} cm^3 "
      f"(analytic {math.pi * r0 * r0 * length * 1e6:.1f})")
for name, R in (("bend 90", rot("z", 90)), ("bend 120", rot("z", 120)),
                ("twist 90", rot("x", 90)), ("twist 180", rot("x", 180))):
    M = palette(R)
    row = [f"{k}: volume {volume(f(V, W, M)) / V0:.3f} ring {ring_area(f(V, W, M), 60) / A0:.3f}"
           for k, f in (("lbs", skin_lbs), ("dqs", skin_dqs))]
    print(f"{name:10s}", " | ".join(row))
M = palette(np.eye(3))
print("identity pose max error: lbs %.1e dqs %.1e" % (np.abs(skin_lbs(V, W, M) - V).max(),
                                                       np.abs(skin_dqs(V, W, M) - V).max()))
```

Recorded output (numpy 2.x):

```text
vertices 5810 triangles 11616 bind volume 4698.9 cm^3 (analytic 4712.4)
bend 90    lbs: volume 0.978 ring 0.707 | dqs: volume 1.000 ring 1.000
bend 120   lbs: volume 0.967 ring 0.500 | dqs: volume 0.999 ring 1.000
twist 90   lbs: volume 0.957 ring 0.500 | dqs: volume 1.000 ring 1.000
twist 180  lbs: volume 0.914 ring 0.000 | dqs: volume 1.000 ring 1.000
identity pose max error: lbs 6.9e-18 dqs 0.0e+00
```

Variations worth running before choosing a method: widen the blend zone (0.2-0.4 m) and watch
the ring area stay at cos(theta/2) while the crease softens; add a twist helper joint at
x = 0.45 m carrying half the twist and confirm the 180-degree ring area rises to
cos^2(45) = 0.5 per blend zone instead of 0.
