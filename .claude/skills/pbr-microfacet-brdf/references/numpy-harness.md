# NumPy BRDF test harness

Self-contained script (NumPy only) behind the numbers in SKILL.md: height-correlated GGX directional
albedo E_ss by midpoint quadrature and by VNDF Monte Carlo, the 32x32 E_ss LUT with the
Turquin-compensated furnace, and a Pearson chi-square test of `sample()` against `pdf()`. Its colour
section is the one used by `color-pipeline-tonemapping`.

Run: `uv run --no-project --with numpy python checks_brdf_color.py` (about 2 s on an Apple M3 Ultra).

Notes
- Chi-square bins are uniform in (sqrt(1 - cos theta), phi), so lobes at the pole are resolved, and the
  expected counts integrate the pdf on a 24 x 192 sub-grid per bin. With a 24 x 24 sub-grid the case
  mu = 0.05, alpha = 0.05 failed spuriously (chi2 13986 on 511 dof): at grazing incidence the reflected
  lobe is only about 2 alpha cos(theta_d) wide in azimuth. Refine the integration before blaming a sampler.
- The p-value uses the Wilson-Hilferty normal approximation; prefer `scipy.stats.chi2.sf` when available.
- To test your own BSDF, replace `make_samplers` with wrappers around your `sample()` and `pdf()`.

## Script

```python
#!/usr/bin/env python3
"""Numerical checks: GGX E_ss table (quadrature + VNDF Monte Carlo), a 32x32 E_ss LUT and the Turquin
compensated furnace, a chi-square sampler test with and without the 1/(4|v.h|) Jacobian, and colour numbers."""
import math

import numpy as np

PI = math.pi


def lam(mu, a2):
    """Smith Lambda for isotropic GGX; mu = cos(theta) of the direction."""
    mu = np.clip(mu, 1e-7, 1.0)
    return 0.5 * (-1.0 + np.sqrt(1.0 + a2 * (1.0 - mu * mu) / (mu * mu)))


def ggx_d(nh, a2):
    return a2 / (PI * (nh * nh * (a2 - 1.0) + 1.0) ** 2)


def e_ss_quadrature(mu_o, alpha, f0=None, nth=2048, nph=1024):
    """Directional albedo of height-correlated GGX (F = 1, or Schlick f0) by midpoint quadrature over l."""
    a2 = alpha * alpha
    th = (np.arange(nth) + 0.5) * (0.5 * PI / nth)
    ph = (np.arange(nph) + 0.5) * (PI / nph)  # half the azimuth range, doubled by symmetry
    T, P = np.meshgrid(th, ph, indexing="ij")
    st = np.sin(T)
    lx, ly, lz = st * np.cos(P), st * np.sin(P), np.cos(T)
    vx, vz = math.sqrt(max(0.0, 1.0 - mu_o * mu_o)), mu_o
    hx, hy, hz = lx + vx, ly, lz + vz
    inv = 1.0 / np.sqrt(hx * hx + hy * hy + hz * hz)
    hx, hy, hz = hx * inv, hy * inv, hz * inv
    vh = vx * hx + vz * hz
    F = 1.0 if f0 is None else f0 + (1.0 - f0) * (1.0 - vh) ** 5
    G2 = 1.0 / (1.0 + lam(mu_o, a2) + lam(lz, a2))
    integrand = ggx_d(hz, a2) * G2 * F / (4.0 * mu_o)  # f * cos(theta_l)
    return 2.0 * float(np.sum(integrand * st)) * (0.5 * PI / nth) * (PI / nph)


def sample_vndf(vx, vz, alpha, u1, u2):
    """Dupuy-Benyoub 2023 spherical-cap VNDF sampling, isotropic alpha, v in the xz plane."""
    wx, wz = vx * alpha, vz
    n = math.hypot(wx, wz)
    wx, wz = wx / n, wz / n
    phi = 2.0 * PI * u1
    z = (1.0 - u2) * (1.0 + wz) - wz
    s = np.sqrt(np.clip(1.0 - z * z, 0.0, 1.0))
    hx, hy, hz = (s * np.cos(phi) + wx) * alpha, s * np.sin(phi) * alpha, z + wz
    inv = 1.0 / np.sqrt(hx * hx + hy * hy + hz * hz)
    return hx * inv, hy * inv, hz * inv


def vndf_weight(mu, alpha, u1, u2):
    a2 = alpha * alpha
    vx, vz = math.sqrt(max(0.0, 1.0 - mu * mu)), mu
    hx, hy, hz = sample_vndf(vx, vz, alpha, u1, u2)
    vh = vx * hx + vz * hz
    lz = 2.0 * vh * hz - vz
    lv = lam(np.float64(mu), a2)
    return np.where(lz > 0.0, (1.0 + lv) / (1.0 + lv + lam(np.maximum(lz, 1e-7), a2)), 0.0)  # F G2 / G1(v)


def e_ss_vndf(mu, alpha, n=1_000_000, seed=1):
    rng = np.random.default_rng(seed)
    w = vndf_weight(mu, alpha, rng.random(n), rng.random(n))
    return float(w.mean()), float(w.std() / math.sqrt(n))


def build_ess_lut(n_mu=32, n_r=32, strata=128):
    """E_ss[j, i] at mu_i = (i+.5)/n_mu and perceptual roughness r_j = (j+.5)/n_r, alpha = r^2."""
    g = (np.arange(strata) + 0.5) / strata
    U1, U2 = np.meshgrid(g, g, indexing="ij")
    u1, u2 = U1.ravel(), U2.ravel()
    lut = np.zeros((n_r, n_mu))
    for j in range(n_r):
        for i in range(n_mu):
            lut[j, i] = vndf_weight((i + 0.5) / n_mu, ((j + 0.5) / n_r) ** 2, u1, u2).mean()
    return lut


def lut_lookup(lut, mu, r):
    n_r, n_mu = lut.shape
    x = min(max(mu * n_mu - 0.5, 0.0), n_mu - 1.0)
    y = min(max(r * n_r - 0.5, 0.0), n_r - 1.0)
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, n_mu - 1), min(y0 + 1, n_r - 1)
    fx, fy = x - x0, y - y0
    top = lut[y0, x0] * (1 - fx) + lut[y0, x1] * fx
    bot = lut[y1, x0] * (1 - fx) + lut[y1, x1] * fx
    return top * (1 - fy) + bot * fy


def make_samplers(mu, alpha):
    vx, vz = math.sqrt(max(0.0, 1.0 - mu * mu)), mu
    a2 = alpha * alpha

    def reflect(hx, hy, hz):
        vh = vx * hx + vz * hz
        return 2 * vh * hx - vx, 2 * vh * hy, 2 * vh * hz - vz

    def s_classic(u1, u2):  # h ~ D(h)(n.h)
        t2 = a2 * u1 / (1.0 - u1)
        ct = 1.0 / np.sqrt(1.0 + t2)
        st = np.sqrt(np.maximum(0.0, 1.0 - ct * ct))
        phi = 2 * PI * u2
        return reflect(st * np.cos(phi), st * np.sin(phi), ct)

    def s_vndf(u1, u2):
        return reflect(*sample_vndf(vx, vz, alpha, u1, u2))

    def half(lx, ly, lz):
        hx, hy, hz = lx + vx, ly, lz + vz
        inv = 1.0 / np.sqrt(hx * hx + hy * hy + hz * hz)
        return hx * inv, hy * inv, hz * inv

    def p_classic(lx, ly, lz, jac=True):
        hx, hy, hz = half(lx, ly, lz)
        p = ggx_d(hz, a2) * hz
        if jac:
            p = p / (4 * np.abs(vx * hx + vz * hz))
        return np.where(lz > 0, p, 0.0)

    def p_vndf(lx, ly, lz):
        hx, hy, hz = half(lx, ly, lz)
        g1 = 1.0 / (1.0 + lam(np.float64(vz), a2))
        return np.where(lz > 0, g1 * ggx_d(hz, a2) / (4 * vz), 0.0)

    return s_classic, s_vndf, p_classic, p_vndf


def chi2(sample, pdf, n=1_000_000, nz=16, nphi=32, sub_z=24, sub_phi=192, seed=5):
    """Pearson chi-square of sample() against pdf(); bins in (sqrt(1 - cos theta), phi) to resolve the pole."""
    rng = np.random.default_rng(seed)
    lx, ly, lz = sample(rng.random(n), rng.random(n))
    ok = lz > 0
    zb = np.minimum((np.sqrt(1.0 - lz[ok]) * nz).astype(int), nz - 1)
    pb = np.minimum(((np.arctan2(ly[ok], lx[ok]) + PI) / (2 * PI) * nphi).astype(int), nphi - 1)
    obs = np.bincount(zb * nphi + pb, minlength=nz * nphi).astype(float)
    z = (np.arange(nz * sub_z) + 0.5) / (nz * sub_z)
    ph = (np.arange(nphi * sub_phi) + 0.5) / (nphi * sub_phi) * 2 * PI - PI
    Z, PHI = np.meshgrid(z, ph, indexing="ij")
    c = 1.0 - Z * Z
    s = np.sqrt(np.maximum(0.0, 1.0 - c * c))
    dens = pdf(s * np.cos(PHI), s * np.sin(PHI), c) * 2.0 * Z  # d omega = d cos d phi = 2 z dz d phi
    cell = (1.0 / (nz * sub_z)) * (2 * PI / (nphi * sub_phi))
    exp = (dens * cell).reshape(nz, sub_z, nphi, sub_phi).sum(axis=(1, 3)).ravel() * n
    lo = exp < 5.0
    o = np.append(obs[~lo], obs[lo].sum())
    e = np.append(exp[~lo], exp[lo].sum())
    keep = e > 0
    x2 = float(((o - e) ** 2 / np.where(keep, e, 1.0))[keep].sum())
    dof = int(keep.sum()) - 1
    zz = ((x2 / dof) ** (1 / 3) - (1 - 2 / (9 * dof))) / math.sqrt(2 / (9 * dof))  # Wilson-Hilferty
    return x2, dof, 0.5 * math.erfc(zz / math.sqrt(2)), float(ok.mean()), float(exp.sum() / n)


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


def main():
    np.set_printoptions(precision=6, suppress=True)
    print("== E_ss(mu, alpha), height-correlated GGX, F = 1 (quadrature) ==")
    for a in (0.1, 0.5, 0.81, 1.0):
        print(f"alpha {a:4}: " + "  ".join(f"mu={m}: {e_ss_quadrature(m, a):.4f}" for m in (0.1, 0.5, 1.0)))
    print("analytic alpha=1, mu=1: 1 - ln 2 =", 1 - math.log(2))
    for m, a in ((1.0, 0.81), (0.5, 0.81), (1.0, 1.0), (0.1, 0.5)):
        print(f"VNDF MC mu={m} alpha={a}: %.4f +- %.4f" % e_ss_vndf(m, a))

    lut = build_ess_lut()
    print("== 32x32 LUT (mu, r = sqrt(alpha)), Turquin-compensated furnace at roughness 0.9 (alpha 0.81) ==")
    for m in (1.0, 0.5, 0.1):
        e_true, e_lut = e_ss_quadrature(m, 0.81), lut_lookup(lut, m, 0.9)
        print(f"mu={m}: E_ss {e_true:.4f}  LUT {e_lut:.4f}  compensated {e_true * (1 + (1 - e_lut) / e_lut):.4f}")
    j = int(0.9 * 32)
    mus = (np.arange(32) + 0.5) / 32
    print("E_avg(alpha~0.81) =", float(2 * np.sum(lut[j] * mus) / 32), "(row r=%.4f)" % ((j + 0.5) / 32))

    print("== chi-square, mu=0.5 alpha=0.3, N=1e6 ==")
    s_c, s_v, p_c, p_v = make_samplers(0.5, 0.3)
    for name, s, p in (("classic D(h)(n.h)/(4|v.h|)", s_c, p_c),
                       ("classic, Jacobian missing", s_c, lambda x, y, z: p_c(x, y, z, False)),
                       ("VNDF G1 D/(4 n.v)", s_v, p_v)):
        x2, dof, pv, acc, integ = chi2(s, p)
        print(f"{name:30s} chi2 {x2:12.1f} dof {dof:4d} p {pv:.3g}  accepted {acc:.4f}  integral(pdf) {integ:.4f}")
    print("== VNDF chi-square grid (Bonferroni threshold 0.01/9) ==")
    for m in (0.05, 0.5, 1.0):
        for a in (0.05, 0.3, 1.0):
            _, s_v, _, p_v = make_samplers(m, a)
            x2, dof, pv, acc, integ = chi2(s_v, p_v)
            print(f"mu={m:4} alpha={a:4}: chi2 {x2:8.1f} dof {dof:4d} p {pv:.3f} {'PASS' if pv > 0.01 / 9 else 'FAIL'}")

    print("== colour ==")
    print("sRGB->XYZ\n", M709)
    print("Rec.709->Rec.2020\n", np.linalg.inv(M2020) @ M709)
    print("lin sRGB->ACEScg (Bradford D65->ACES white)\n", np.linalg.inv(MAP1) @ bradford(D65, ACES_W) @ M709)
    print("0.18 encodes to", float(srgb_encode(0.18)), "=", float(srgb_encode(0.18)) * 255, "/255")
    t = de2000(np.array([[50.0, 2.6772, -79.7751]]), np.array([[50.0, 0.0, -82.7485]]))
    print("CIEDE2000 Sharma pair 1 (expect 2.0425):", float(t[0]))
    e_spec = e_ss_quadrature(1.0, 0.25, f0=0.04)
    print("specular albedo, F0 0.04, roughness 0.5, mu=1:", e_spec)
    gray = 0.18 * 0.96 + e_spec
    print("grey card rendered (unit white env):", gray, " before code:", gray * 255,
          " after (PBR Neutral + sRGB) code:", float(srgb_encode(pbr_neutral([[gray] * 3])[0, 0])) * 255)
    rendered = srgb_decode(CHECKER) * 0.96 + e_spec
    ref = lab(srgb_decode(CHECKER))
    before = lab(srgb_decode(np.clip(rendered, 0, 1)))  # linear values written to a UNORM target, shown as sRGB
    after = lab(srgb_decode(srgb_encode(pbr_neutral(rendered))))
    for name, l in (("before", before), ("after", after)):
        d = de2000(ref, l)
        print(f"ColorChecker dE2000 {name}: mean {d.mean():.2f} max {d.max():.2f} (patch {int(d.argmax()) + 1})")


if __name__ == "__main__":
    main()
```

## Recorded output (BRDF part)

```text
== E_ss(mu, alpha), height-correlated GGX, F = 1 (quadrature) ==
alpha  0.1: mu=0.1: 0.8835  mu=0.5: 0.9692  mu=1.0: 0.9883
alpha  0.5: mu=0.1: 0.8601  mu=0.5: 0.6983  mu=1.0: 0.6878
alpha 0.81: mu=0.1: 0.7985  mu=0.5: 0.5353  mu=1.0: 0.4200
alpha  1.0: mu=0.1: 0.7602  mu=0.5: 0.4507  mu=1.0: 0.3069
analytic alpha=1, mu=1: 1 - ln 2 = 0.3068528194400547
VNDF MC mu=1.0 alpha=0.81: 0.4199 +- 0.0004
VNDF MC mu=0.5 alpha=0.81: 0.5352 +- 0.0004
VNDF MC mu=1.0 alpha=1.0: 0.3068 +- 0.0004
VNDF MC mu=0.1 alpha=0.5: 0.8603 +- 0.0002
== 32x32 LUT (mu, r = sqrt(alpha)), Turquin-compensated furnace at roughness 0.9 (alpha 0.81) ==
mu=1.0: E_ss 0.4200  LUT 0.4225  compensated 0.9941
mu=0.5: E_ss 0.5353  LUT 0.5354  compensated 0.9998
mu=0.1: E_ss 0.7985  LUT 0.7992  compensated 0.9991
E_avg(alpha~0.81) = 0.5116906470509466 (row r=0.8906)
== chi-square, mu=0.5 alpha=0.3, N=1e6 ==
classic D(h)(n.h)/(4|v.h|)     chi2        524.7 dof  511 p 0.328  accepted 0.8015  integral(pdf) 0.8021
classic, Jacobian missing      chi2     547236.3 dof  511 p 0  accepted 0.8015  integral(pdf) 1.7502
VNDF G1 D/(4 n.v)              chi2        502.4 dof  511 p 0.599  accepted 0.9113  integral(pdf) 0.9111
== VNDF chi-square grid (Bonferroni threshold 0.01/9) ==
mu=0.05 alpha=0.05: chi2    504.4 dof  511 p 0.574 PASS
mu=0.05 alpha= 0.3: chi2    574.4 dof  511 p 0.027 PASS
mu=0.05 alpha= 1.0: chi2    546.3 dof  511 p 0.136 PASS
mu= 0.5 alpha=0.05: chi2    514.4 dof  494 p 0.254 PASS
mu= 0.5 alpha= 0.3: chi2    502.4 dof  511 p 0.599 PASS
mu= 0.5 alpha= 1.0: chi2    526.0 dof  511 p 0.313 PASS
mu= 1.0 alpha=0.05: chi2    519.4 dof  511 p 0.389 PASS
mu= 1.0 alpha= 0.3: chi2    531.4 dof  511 p 0.257 PASS
mu= 1.0 alpha= 1.0: chi2    535.5 dof  511 p 0.219 PASS
```
