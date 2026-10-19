# Color pipeline checks

Self-contained NumPy script behind the numbers in SKILL.md: sRGB and PQ transfer functions, physical
exposure, primaries-derived matrices with Bradford adaptation, OKLab and OKLCh gamut mapping, Khronos
PBR Neutral, CIEDE2000 (validated on Sharma's first test pair) and a simulated ColorChecker render under
a uniform white environment of radiance 1 (diffuse x 0.96 plus a specular albedo of 0.0367 for a glTF
dielectric with roughness 0.5). Patch references are the nominal 8-bit sRGB values of the 24-patch chart.

Run: `uv run --no-project --with numpy python color_checks.py`

## Script

```python
#!/usr/bin/env python3
"""Color-pipeline checks: transfer functions, PQ, exposure, matrices, OKLab gamut mapping, tonemapper fidelity, CIEDE2000."""
import math

import numpy as np

# ---------------------------------------------------------------- colour
def srgb_decode(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_encode(x):
    x = np.clip(np.asarray(x, float), 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def pbr_neutral(c):
    c = np.array(c, float, ndmin=2)
    start, desat = 0.8 - 0.04, 0.15
    x = c.min(axis=1, keepdims=True)
    c = c - np.where(x < 0.08, x - 6.25 * x * x, 0.04)
    peak = c.max(axis=1, keepdims=True)
    d = 1.0 - start
    new_peak = 1.0 - d * d / (peak + d - start)
    comp = c * (new_peak / np.maximum(peak, 1e-9))
    g = 1.0 - 1.0 / (desat * (peak - new_peak) + 1.0)
    comp = comp * (1 - g) + new_peak * g
    return np.where(peak < start, c, comp)


def rgb_to_xyz(prim, white):
    m = np.array([[x / y for x, y in prim], [1.0, 1.0, 1.0], [(1 - x - y) / y for x, y in prim]])
    w = np.array([white[0] / white[1], 1.0, (1 - white[0] - white[1]) / white[1]])
    return m * np.linalg.solve(m, w)


BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])


def bradford(src, dst):
    xyz = lambda w: np.array([w[0] / w[1], 1.0, (1 - w[0] - w[1]) / w[1]])
    return np.linalg.inv(BRADFORD) @ np.diag((BRADFORD @ xyz(dst)) / (BRADFORD @ xyz(src))) @ BRADFORD


D65, ACES_W = (0.3127, 0.3290), (0.32168, 0.33767)
M709 = rgb_to_xyz(((0.64, 0.33), (0.30, 0.60), (0.15, 0.06)), D65)
M2020 = rgb_to_xyz(((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)), D65)
MAP1 = rgb_to_xyz(((0.713, 0.293), (0.165, 0.830), (0.128, 0.044)), ACES_W)


def lab(lin_rgb):
    xyz = (M709 @ np.atleast_2d(lin_rgb).T).T / (M709 @ np.ones(3))
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def de2000(l1, l2):
    L1, a1, b1 = l1.T
    L2, a2, b2 = l2.T
    cbar = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    G = 0.5 * (1 - np.sqrt(cbar**7 / (cbar**7 + 25.0**7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(c1p * c2p == 0, 0.0, dh)
    dHp = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    Lbp, Cbp = (L1 + L2) / 2, (c1p + c2p) / 2
    hs = h1p + h2p
    hbp = np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2))
    hbp = np.where(c1p * c2p == 0, hs, hbp)
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dtheta = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp**7 / (Cbp**7 + 25.0**7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


CHECKER = np.array([[115, 82, 68], [194, 150, 130], [98, 122, 157], [87, 108, 67], [133, 128, 177],
                    [103, 189, 170], [214, 126, 44], [80, 91, 166], [193, 90, 99], [94, 60, 108],
                    [157, 188, 64], [224, 163, 46], [56, 61, 150], [70, 148, 73], [175, 54, 60],
                    [231, 199, 31], [187, 86, 149], [8, 133, 161], [243, 243, 242], [200, 200, 200],
                    [160, 160, 160], [122, 122, 121], [85, 85, 85], [52, 52, 52]], float) / 255.0


E_SPEC = 0.03665878  # specular albedo of the glTF dielectric lobe (F0 0.04, roughness 0.5) at normal view (BRDF harness)


def pq_encode(nits):
    m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
    y = np.power(np.clip(np.asarray(nits, float) / 10000.0, 0.0, 1.0), m1)
    return np.power((c1 + c2 * y) / (1.0 + c3 * y), m2)


def pq_decode(e):
    m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
    p = np.power(np.clip(np.asarray(e, float), 0.0, 1.0), 1.0 / m2)
    return 10000.0 * np.power(np.maximum(p - c1, 0.0) / (c2 - c3 * p), 1.0 / m1)


M_LMS = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                  [0.2119034982, 0.6806995451, 0.1073969566],
                  [0.0883024619, 0.2817188376, 0.6299787005]])
M_LAB = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                  [1.9779984951, -2.4285922050, 0.4505937099],
                  [0.0259040371, 0.7827717662, -0.8086757660]])


def oklab(rgb):
    """Linear sRGB (Rec.709) to OKLab (Ottosson 2020)."""
    return M_LAB @ np.cbrt(M_LMS @ np.asarray(rgb, float))


def oklab_inv(lab_):
    return np.linalg.solve(M_LMS, np.linalg.solve(M_LAB, np.asarray(lab_, float)) ** 3)


def gamut_map_oklch(rgb, iters=16):
    """Reduce OKLCh chroma at constant L and h until linear Rec.709 lies in [0, 1] (display-referred input)."""
    rgb = np.asarray(rgb, float)
    if (rgb >= 0).all() and (rgb <= 1).all():
        return rgb
    L, a, b = oklab(rgb)
    L = min(max(L, 0.0), 1.0)
    C, h = math.hypot(a, b), math.atan2(b, a)
    lo, hi = 0.0, C
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        c = oklab_inv([L, mid * math.cos(h), mid * math.sin(h)])
        if (c >= -1e-6).all() and (c <= 1 + 1e-6).all():
            lo = mid
        else:
            hi = mid
    return np.clip(oklab_inv([L, lo * math.cos(h), lo * math.sin(h)]), 0.0, 1.0)


def hue_deg(rgb):
    _, a, b = oklab(rgb)
    return math.degrees(math.atan2(b, a))


def main():
    np.set_printoptions(precision=6, suppress=True)
    print("0.18 linear -> sRGB code", float(srgb_encode(0.18)) * 255)
    r = float(srgb_decode(0.5))
    print(f"roughness 0.5 decoded as sRGB -> {r:.4f}, alpha {r * r:.4f} instead of 0.25")
    print("PQ code for 100 / 203 / 1000 / 10000 nits:", pq_encode([100.0, 203.0, 1000.0, 10000.0]))
    print("PQ round trip of 203 nits:", float(pq_decode(pq_encode(203.0))))
    ev = math.log2(16.0 ** 2 / (1.0 / 100.0)) - math.log2(100.0 / 100.0)
    lmax = 1.2 * 2.0 ** ev
    print(f"sunny 16 (f/16, 1/100 s, ISO 100): EV100 {ev:.2f}, L_max {lmax:.0f} cd/m2; "
          f"white diffuse 0.9 x 1e5 lux / pi -> {0.9e5 / math.pi / lmax:.3f}, 18% grey -> {0.18e5 / math.pi / lmax:.3f}")
    print("sRGB->XYZ\n", M709)
    print("Rec.709->Rec.2020\n", np.linalg.inv(M2020) @ M709)
    print("lin sRGB->ACEScg (Bradford)\n", np.linalg.inv(MAP1) @ bradford(D65, ACES_W) @ M709)
    np.set_printoptions(precision=10, suppress=True)
    print("OKLab of white:", oklab([1.0, 1.0, 1.0]))
    print("inverse M_LAB\n", np.linalg.inv(M_LAB))
    print("inverse M_LMS\n", np.linalg.inv(M_LMS))
    np.set_printoptions(precision=4, suppress=True)
    g = np.linalg.inv(M709) @ M2020 @ np.array([0.0, 1.0, 0.0])
    clipped, mapped = np.clip(g, 0.0, 1.0), gamut_map_oklch(g)
    print("Rec.2020 green in linear Rec.709:", g)
    print(f"  per-channel clip {clipped} hue shift {hue_deg(clipped) - hue_deg(g):+.2f} deg")
    print(f"  OKLCh chroma reduction {mapped} hue shift {hue_deg(mapped) - hue_deg(g):+.2f} deg, "
          f"L {oklab(g)[0]:.4f} -> {oklab(mapped)[0]:.4f}")
    t = de2000(np.array([[50.0, 2.6772, -79.7751]]), np.array([[50.0, 0.0, -82.7485]]))
    print("CIEDE2000 Sharma pair 1 (expect 2.0425):", round(float(t[0]), 4))
    gray = 0.18 * 0.96 + E_SPEC
    print(f"grey card rendered {gray:.4f}; UNORM, no encode -> code {gray * 255:.1f}; "
          f"PBR Neutral + sRGB -> code {float(srgb_encode(pbr_neutral([[gray] * 3])[0, 0])) * 255:.1f}; ideal 117.6")
    x = srgb_decode(CHECKER) * 0.96 + E_SPEC
    ref = lab(srgb_decode(CHECKER))
    aces = np.clip(x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)
    for name, out in (("before (UNORM, no encode)", np.clip(x, 0, 1)),
                      ("after (PBR Neutral + sRGB)", srgb_encode(pbr_neutral(x))),
                      ("Reinhard per channel + sRGB", srgb_encode(x / (1 + x))),
                      ("Narkowicz ACES fit + sRGB", srgb_encode(aces))):
        d = de2000(ref, lab(srgb_decode(out)))
        print(f"ColorChecker dE2000 {name:28s} mean {d.mean():5.2f} max {d.max():5.2f} (patch {int(d.argmax()) + 1})")


if __name__ == "__main__":
    main()
```

## Recorded output

```text
0.18 linear -> sRGB code 117.64581302261261
roughness 0.5 decoded as sRGB -> 0.2140, alpha 0.0458 instead of 0.25
PQ code for 100 / 203 / 1000 / 10000 nits: [0.508078 0.580689 0.751827 1.      ]
PQ round trip of 203 nits: 203.00000000000213
sunny 16 (f/16, 1/100 s, ISO 100): EV100 14.64, L_max 30720 cd/m2; white diffuse 0.9 x 1e5 lux / pi -> 0.933, 18% grey -> 0.187
sRGB->XYZ
 [[0.412391 0.357584 0.180481]
 [0.212639 0.715169 0.072192]
 [0.019331 0.119195 0.950532]]
Rec.709->Rec.2020
 [[0.627404 0.329283 0.043313]
 [0.069097 0.91954  0.011362]
 [0.016391 0.088013 0.895595]]
lin sRGB->ACEScg (Bradford)
 [[0.613097 0.339523 0.047379]
 [0.070194 0.916354 0.013452]
 [0.020616 0.10957  0.869815]]
OKLab of white: [0.9999999935 0.0000000001 0.0000000373]
inverse M_LAB
 [[ 0.9999999985  0.3963377922  0.2158037581]
 [ 1.0000000089 -0.1055613423 -0.0638541748]
 [ 1.0000000547 -0.0894841821 -1.2914855379]]
inverse M_LMS
 [[ 4.0767416613 -3.3077115904  0.2309699287]
 [-1.2684380041  2.6097574007 -0.3413193963]
 [-0.0041960865 -0.7034186145  1.7076147009]]
Rec.2020 green in linear Rec.709: [-0.5876  1.1329 -0.1006]
  per-channel clip [0. 1. 0.] hue shift -10.10 deg
  OKLCh chroma reduction [0.     0.849  0.2099] hue shift -0.00 deg, L 0.8298 -> 0.8298
CIEDE2000 Sharma pair 1 (expect 2.0425): 2.0425
grey card rendered 0.2095; UNORM, no encode -> code 53.4; PBR Neutral + sRGB -> code 114.4; ideal 117.6
ColorChecker dE2000 before (UNORM, no encode)    mean 18.50 max 24.70 (patch 21)
ColorChecker dE2000 after (PBR Neutral + sRGB)   mean  1.14 max  1.72 (patch 19)
ColorChecker dE2000 Reinhard per channel + sRGB  mean  7.16 max 14.10 (patch 19)
ColorChecker dE2000 Narkowicz ACES fit + sRGB    mean  9.35 max 12.86 (patch 4)
```
