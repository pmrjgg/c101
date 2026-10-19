#!/usr/bin/env python3
"""OKLCH palette tool. Stdlib only (Python 3.9+), deterministic.

Subcommands
  info HEX...                      OKLab, OKLCH and WCAG relative luminance per colour
  contrast FG BG                   WCAG 2.x contrast ratio (1..21)
  sweep HEX [--bg HEX] [--lo 0.30] [--hi 0.96] [--step 0.02]
                                   lightness sweep at the colour's own chroma and hue,
                                   every sample gamut-mapped to sRGB; ratio against --bg
  map L C H [--gamut srgb|p3]      CSS Color 4 gamut mapping (binary search, local MINDE)
  pairs FG/BG...                   WCAG ratio and class for every intended pair
  ramp HEX [--name N] [--peak-c C] [--hue-shift DEG] [--neutral C] [--no-anchor]
           [--surfaces HEX,HEX] [--p3] [--p3-peak-c C] [--format table|css|json|dtcg]
                                   11-step ramp 50..950: target L table, chroma taper,
                                   sRGB gamut mapping, contrast vs white, black and surfaces;
                                   dtcg = DTCG 2025.10 colour tokens (oklch components + hex)
                                   The input colour is pinned to its nearest step unless
                                   --peak-c or --no-anchor is given.

Contrast classes per pair: text (>= 4.5), large/UI (>= 3.0), deco (< 3.0).
"""
import argparse
import json
import math
import sys

# ---------------------------------------------------------------- sRGB and WCAG
def lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def enc(c):
    if c < 0:
        return -enc(-c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def hexs(v):
    return "#" + "".join("%02X" % round(min(max(c, 0.0), 1.0) * 255) for c in v)


def lum(v):
    r, g, b = map(lin, v)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# ---------------------------------------------------------------- OKLab (Ottosson matrices, as in CSS Color 4)
def lin_srgb_to_oklab(r, g, b):
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklab_to_lin_srgb(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


# linear sRGB -> XYZ (D65) -> linear Display P3 (CSS Color 4 matrices)
SRGB_XYZ = ((506752 / 1228815, 87881 / 245763, 12673 / 70218),
            (87098 / 409605, 175762 / 245763, 12673 / 175545),
            (7918 / 409605, 87881 / 737289, 1001167 / 1053270))
XYZ_P3 = ((446124 / 178915, -333277 / 357830, -72051 / 178915),
          (-14852 / 17905, 63121 / 35810, 423 / 17905),
          (11844 / 330415, -50337 / 660830, 316169 / 330415))
P3_XYZ = ((608311 / 1250200, 189793 / 714400, 198249 / 1000160),
          (35783 / 156275, 247089 / 357200, 198249 / 2500400),
          (0, 32229 / 714400, 5220557 / 5000800))
XYZ_SRGB = ((12831 / 3959, -329 / 214, -1974 / 3959),
            (-851781 / 878810, 1648619 / 878810, 36519 / 878810),
            (705 / 12673, -2585 / 12673, 705 / 667))


def mul(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def oklch_to_oklab(L, C, h):
    return L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h))


def oklab_to_oklch(L, a, b):
    C = math.hypot(a, b)
    h = math.degrees(math.atan2(b, a)) % 360 if C > 1e-7 else 0.0
    return L, C, h


def to_space(lab, space):
    """OKLab -> gamma-encoded RGB in 'srgb' or 'p3' (unclamped)."""
    lin_rgb = oklab_to_lin_srgb(*lab)
    if space == "p3":
        lin_rgb = mul(XYZ_P3, mul(SRGB_XYZ, lin_rgb))
    return tuple(enc(c) for c in lin_rgb)


def from_space(v, space):
    lin_rgb = tuple(math.copysign(lin(abs(c)), c) for c in v)
    if space == "p3":
        lin_rgb = mul(XYZ_SRGB, mul(P3_XYZ, lin_rgb))
    return lin_srgb_to_oklab(*lin_rgb)


def hex_to_oklch(h):
    return oklab_to_oklch(*lin_srgb_to_oklab(*map(lin, rgb(h))))


def delta_eok(p, q):
    return math.dist(p, q)


# ---------------------------------------------------------------- CSS Color 4 gamut mapping
def gamut_map(L, C, h, space="srgb", jnd=0.02, eps=0.0001):
    """Binary search with local MINDE (CSS Color 4, 14.2.2). Returns RGB in [0,1]."""
    if L >= 1:
        return (1.0, 1.0, 1.0)
    if L <= 0:
        return (0.0, 0.0, 0.0)

    def inside(v, t=1e-6):
        return all(-t <= c <= 1 + t for c in v)

    def clip(v):
        return tuple(min(max(c, 0.0), 1.0) for c in v)

    cur = oklch_to_oklab(L, C, h)
    v = to_space(cur, space)
    if inside(v):
        return clip(v)
    clipped = clip(v)
    if delta_eok(from_space(clipped, space), cur) < jnd:
        return clipped
    lo, hi, lo_in = 0.0, C, True
    while hi - lo > eps:
        c = (lo + hi) / 2
        cur = oklch_to_oklab(L, c, h)
        v = to_space(cur, space)
        if lo_in and inside(v):
            lo = c
            continue
        clipped = clip(v)
        e = delta_eok(from_space(clipped, space), cur)
        if e < jnd:
            if jnd - e < eps:
                return clipped
            lo_in, lo = False, c
        else:
            hi = c
    return clipped


def oklch_parts(lab):
    L, C, h = oklab_to_oklch(*lab)
    return [round(L, 3), round(C, 3), round(h, 1)]


def css_oklch(lab):
    L, C, h = oklab_to_oklch(*lab)
    return "oklch(%.3f %.3f %.1f)" % (L, C, h)


# ---------------------------------------------------------------- ramp
STEPS = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)
TARGET_L = dict(zip(STEPS, (0.97, 0.93, 0.87, 0.79, 0.71, 0.63, 0.55, 0.47, 0.39, 0.31, 0.25)))
TAPER = dict(zip(STEPS, (0.10, 0.22, 0.42, 0.66, 0.88, 1.00, 1.00, 0.92, 0.80, 0.66, 0.52)))
WHITE, BLACK = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)


def klass(r):
    return "text" if r >= 4.5 else ("ui" if r >= 3.0 else "deco")


def build_ramp(hx, peak_c=None, hue_shift=0.0, neutral=None, anchor=True, surfaces=(), p3=False, p3_peak_c=None):
    L0, C0, h0 = hex_to_oklch(hx)
    peak = neutral if neutral is not None else (peak_c if peak_c is not None else C0)
    p3peak = neutral if neutral is not None else (p3_peak_c if p3_peak_c is not None else peak)
    anchor_step = min(STEPS, key=lambda s: abs(TARGET_L[s] - L0)) if anchor and neutral is None else None
    rows = []
    for s in STEPS:
        L = L0 if s == anchor_step else TARGET_L[s]
        shade = max(0.0, (L0 - L) / max(L0 - TARGET_L[950], 1e-6)) if L < L0 else 0.0
        h = (h0 + hue_shift * shade) % 360
        C = peak if neutral is not None else peak * TAPER[s]
        if s == anchor_step and peak_c is None:
            v = tuple(rgb(hx))
        else:
            v = gamut_map(L, C, h, "srgb")
        lab = from_space(v, "srgb")
        row = {"step": s, "hex": hexs(v), "oklch": css_oklch(lab), "parts": oklch_parts(lab), "target_c": round(C, 3),
               "vs_white": round(contrast(v, WHITE), 2), "vs_black": round(contrast(v, BLACK), 2)}
        for sh in surfaces:
            row["vs_" + sh.upper()] = round(contrast(v, rgb(sh)), 2)
        if p3:
            Cp = p3peak if neutral is not None else p3peak * TAPER[s]
            vp = gamut_map(L, Cp, h, "p3")
            row["p3"] = css_oklch(from_space(vp, "p3"))
        rows.append(row)
    return rows, anchor_step


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("info"); x.add_argument("hex", nargs="+")
    x = sp.add_parser("contrast"); x.add_argument("fg"); x.add_argument("bg")
    x = sp.add_parser("sweep"); x.add_argument("hex"); x.add_argument("--bg", default="#FFFFFF")
    x.add_argument("--lo", type=float, default=0.30); x.add_argument("--hi", type=float, default=0.96)
    x.add_argument("--step", type=float, default=0.02)
    x = sp.add_parser("pairs"); x.add_argument("pair", nargs="+", help="FG/BG, e.g. '#FFFFFF/#D63151'")
    x = sp.add_parser("map"); x.add_argument("L", type=float); x.add_argument("C", type=float)
    x.add_argument("H", type=float); x.add_argument("--gamut", choices=("srgb", "p3"), default="srgb")
    x = sp.add_parser("ramp"); x.add_argument("hex"); x.add_argument("--name", default="brand")
    x.add_argument("--peak-c", type=float); x.add_argument("--hue-shift", type=float, default=0.0)
    x.add_argument("--neutral", type=float, help="constant chroma (0.005-0.02) for a tinted neutral ramp")
    x.add_argument("--no-anchor", action="store_true", help="do not pin the input colour to its nearest step")
    x.add_argument("--surfaces", default="", help="comma-separated extra backgrounds, e.g. #121212,#F7F7F8")
    x.add_argument("--p3", action="store_true", help="add a Display P3 gamut-mapped oklch() per step")
    x.add_argument("--p3-peak-c", type=float, help="peak chroma of the P3 tier (implies --p3); the sRGB tier keeps --peak-c")
    x.add_argument("--format", choices=("table", "css", "json", "dtcg"), default="table")
    a = ap.parse_args(argv)

    if a.cmd == "info":
        for h in a.hex:
            L, A, B = lin_srgb_to_oklab(*map(lin, rgb(h)))
            _, C, H = oklab_to_oklch(L, A, B)
            print("%s oklab(%.4f %.4f %.4f) oklch(%.4f %.4f %.2f) Y=%.4f" % (h.upper(), L, A, B, L, C, H, lum(rgb(h))))
    elif a.cmd == "contrast":
        print("%.2f" % contrast(rgb(a.fg), rgb(a.bg)))
    elif a.cmd == "sweep":
        L0, C0, h0 = hex_to_oklch(a.hex)
        bg = rgb(a.bg)
        n = int(round((a.hi - a.lo) / a.step))
        for i in range(n + 1):
            t = a.lo + i * a.step
            v = gamut_map(t, C0, h0, "srgb")
            c_out = oklab_to_oklch(*from_space(v, "srgb"))[1]
            print("L=%.2f %s C=%.3f %.2f:1 %s" % (t, hexs(v), c_out, contrast(v, bg), klass(contrast(v, bg))))
    elif a.cmd == "pairs":
        for p in a.pair:
            fg, bg = p.split("/")
            r = contrast(rgb(fg), rgb(bg))
            print("%s on %s  %.2f:1  %s" % (fg.upper(), bg.upper(), r, klass(r)))
    elif a.cmd == "map":
        v = gamut_map(a.L, a.C, a.H, a.gamut)
        lab = from_space(v, a.gamut)
        out = hexs(v) if a.gamut == "srgb" else "color(display-p3 %.4f %.4f %.4f)" % v
        print(out, css_oklch(lab))
    elif a.cmd == "ramp":
        surf = [s for s in a.surfaces.split(",") if s.strip()]
        a.p3 = a.p3 or a.p3_peak_c is not None
        rows, anchor = build_ramp(a.hex, a.peak_c, a.hue_shift, a.neutral, not a.no_anchor, surf, a.p3, a.p3_peak_c)
        if a.format == "dtcg":
            grp = {str(r["step"]): {"$value": {"colorSpace": "oklch", "components": r["parts"],
                                               "hex": r["hex"].lower()}} for r in rows}
            print(json.dumps({"color": {"$type": "color", a.name: grp}}, indent=1))
        elif a.format == "json":
            print(json.dumps({"name": a.name, "anchor": anchor, "steps": rows}, indent=1))
        elif a.format == "css":
            print(":root {")
            for r in rows:
                print("  --%s-%d: %s; /* %s | W %.2f B %.2f */" % (a.name, r["step"], r["hex"], r["oklch"], r["vs_white"], r["vs_black"]))
            print("}")
            if a.p3:
                print("@media (color-gamut: p3) {\n  :root {")
                for r in rows:
                    print("    --%s-%d: %s;" % (a.name, r["step"], r["p3"]))
                print("  }\n}")
        else:
            keys = [k for k in rows[0] if k.startswith("vs_")]
            print("step  hex      oklch                    " + "  ".join("%-12s" % k for k in keys) + ("  p3" if a.p3 else ""))
            for r in rows:
                cells = "  ".join("%5.2f %-6s" % (r[k], klass(r[k])) for k in keys)
                mark = "*" if r["step"] == anchor else " "
                print("%-4d%s %s  %-24s %s%s" % (r["step"], mark, r["hex"], r["oklch"], cells, ("  " + r["p3"]) if a.p3 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
