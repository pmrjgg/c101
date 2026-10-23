#!/usr/bin/env python3
"""WCAG 2.x contrast audit toolkit (stdlib only; Pillow is needed just for `scrim --image`).

  ratio  FG BG [FG BG ...] [--target 4.5]  ratio per pair and what it may be used for
  matrix pairs.csv [--level AA|AAA] [--margin 0]
         report table with fixes; CSV header: fg,bg,usage,size_px,weight,kind[,move]
         kind = text | ui | decorative | logo ; move = fg (default) | bg  (which colour a fix changes)
  fix    FG BG --move fg|bg [--target 4.5] [--margin 0]
         smallest OKLCH-L change (hue and chroma kept; chroma is reduced only where the colour would
         leave sRGB, and the output says so) that reaches target + margin
  scrim  TEXT (--worst HEX | --image IMG --box x0,y0,x1,y1) [--scrim '#000000'] [--target 4.5]
         least alpha a (0.01 steps) so blended = a*scrim + (1-a)*bg passes at the WORST pixel
  cvd    HEX HEX ...    Machado et al. 2009 protan/deutan/tritan (severity 1.0) + grayscale pass
  apca   TEXT BG        APCA-W3 0.0.98G-4g Lc, an advisory second opinion, never a WCAG 2 verdict

Ratios print with two decimals, or more when rounding would hide a fail (4.497 prints 4.497,
never 4.50); pass/fail always uses the unrounded value, as WCAG requires.
Exit 1 when a pair fails (ratio, matrix), a scrim cannot reach the target, or cvd finds a FAIL.
"""
import argparse
import csv
import math
import sys


def parse_hex(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        sys.exit("bad colour %r (use #RGB or #RRGGBB)" % h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb):
    return "#%02X%02X%02X" % tuple(int(round(c)) for c in rgb)


def lin(c8):
    c = c8 / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def enc(c):
    c = min(max(c, 0.0), 1.0)
    return 255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055)


def lum(rgb):
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    lo, hi = sorted((lum(a), lum(b)))
    return (hi + 0.05) / (lo + 0.05)


def fmt(q, *targets):
    """Two decimals, or more when rounding up would hide a fail against one of `targets`."""
    for nd in (2, 3, 4):
        s = "%.*f" % (nd, q)
        if not any(q < t <= float(s) for t in targets):
            break
    return s


M1 = ((0.4122214708, 0.5363325363, 0.0514459929), (0.2119034982, 0.6806995451, 0.1073969566),
      (0.0883024619, 0.2817188376, 0.6299787005))
M2 = ((0.2104542553, 0.7936177850, -0.0040720468), (1.9779984951, -2.4285922050, 0.4505937099),
      (0.0259040371, 0.7827717662, -0.8086757660))


def oklab(rgb):
    lrgb = [lin(c) for c in rgb]
    lms = [max(sum(m * v for m, v in zip(row, lrgb)), 0.0) ** (1 / 3) for row in M1]
    return tuple(sum(m * v for m, v in zip(row, lms)) for row in M2)


def oklch(rgb):
    L, a, b = oklab(rgb)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def oklch_linear(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def from_oklch(L, C, h):
    """8-bit sRGB for an OKLCH colour; chroma is bisected down only if it is outside sRGB."""
    inside = lambda c: all(-1e-6 <= v <= 1 + 1e-6 for v in oklch_linear(L, c, h))
    if not inside(C):
        lo, hi = 0.0, C
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if inside(mid) else (lo, mid)
        C = lo
    return tuple(round(enc(v)) for v in oklch_linear(L, C, h)), C


def is_large(size_px, weight):
    return size_px >= 24 or (size_px >= 18.66 and weight >= 700)


def target_for(kind, size_px, weight, level):
    if kind in ("decorative", "logo"):
        return None                     # exempt from 1.4.3 / 1.4.11
    if kind == "ui":
        return 3.0                      # 1.4.11 (no AAA non-text criterion exists)
    return {("AA", False): 4.5, ("AA", True): 3.0,
            ("AAA", False): 7.0, ("AAA", True): 4.5}[(level, is_large(size_px, weight))]


def fix(fixed, moving, goal):
    """Smallest OKLCH-L step of `moving` (0.001 resolution, either direction) reaching `goal`."""
    L0, C, h = oklch(moving)
    best = None
    for sign in (-1, 1):
        for i in range(1, 1001):
            L = L0 + sign * i / 1000
            if not 0 <= L <= 1:
                break
            rgb, c_used = from_oklch(L, C, h)
            if ratio(rgb, fixed) >= goal:
                if best is None or i < best[0]:
                    best = (i, rgb, L, c_used)
                break
    return None if best is None else (best[1], best[2], C, best[3], h)


def describe_fix(fixed, moving, goal, which):
    res = fix(fixed, moving, goal)
    if res is None:
        return "no L value works: change the other colour"
    rgb, L, C, c_used, h = res
    note = "" if c_used >= C - 1e-3 else ", chroma cut to %.3f for sRGB" % c_used
    L0 = oklch(moving)[0]
    return "%s %s (L %.3f) -> %s oklch(%.3f %.3f %.1f) = %s:1%s" % (
        which, to_hex(moving), L0, to_hex(rgb), L, c_used, h, fmt(ratio(rgb, fixed), goal), note)


def cmd_ratio(a):
    if len(a.colours) % 2:
        sys.exit("give colours as fg bg pairs")
    bad = 0
    for fg, bg in zip(a.colours[::2], a.colours[1::2]):
        q = ratio(parse_hex(fg), parse_hex(bg))
        uses = [n for n, t in (("text AA", 4.5), ("text AAA", 7.0), ("large text AA + UI 3:1", 3.0),
                               ("large text AAA", 4.5)) if q >= t]
        bad += q < a.target
        print("%s on %s  %s:1  %s" % (fg, bg, fmt(q, 3.0, 4.5, 7.0, a.target), ", ".join(uses) or "decorative only"))
    return 1 if bad else 0


def cmd_matrix(a):
    with open(a.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print("| Pair (fg / bg) | Usage | Size / weight | Ratio | Target | Pass | Fix |")
    print("|---|---|---|---|---|---|---|")
    bad = 0
    for r in rows:
        fg, bg = parse_hex(r["fg"]), parse_hex(r["bg"])
        size, weight = float(r.get("size_px") or 0), int(float(r.get("weight") or 400))
        kind = (r.get("kind") or "text").strip()
        t = target_for(kind, size, weight, a.level)
        q = ratio(fg, bg)
        ok = t is None or q >= t
        fixtxt = ""
        if not ok:
            bad += 1
            move = (r.get("move") or "fg").strip()
            fixed, moving = (bg, fg) if move == "fg" else (fg, bg)
            fixtxt = describe_fix(fixed, moving, t + a.margin, move)
        sw = "%g px / %d" % (size, weight) if kind == "text" else kind
        print("| %s / %s | %s | %s | %s | %s | %s | %s |" % (
            to_hex(fg), to_hex(bg), r.get("usage", ""), sw, fmt(q, *([t] if t else [])),
            "exempt" if t is None else "%g" % t, "yes" if ok else "**no**", fixtxt))
    return 1 if bad else 0


def cmd_fix(a):
    fg, bg = parse_hex(a.fg), parse_hex(a.bg)
    fixed, moving = (bg, fg) if a.move == "fg" else (fg, bg)
    print("now %s:1; goal %.2f:1" % (fmt(ratio(fg, bg), a.target + a.margin), a.target + a.margin))
    print(describe_fix(fixed, moving, a.target + a.margin, a.move))
    return 0


def blend(c, s, alpha):
    return tuple(alpha * sc + (1 - alpha) * cc for cc, sc in zip(c, s))


def cmd_scrim(a):
    text, scrim = parse_hex(a.text), parse_hex(a.scrim)
    if a.image:
        from PIL import Image
        x0, y0, x1, y1 = (int(v) for v in a.box.split(","))
        reg = Image.open(a.image).convert("RGB").crop((x0, y0, x1, y1))
        colours = [c for _, c in reg.getcolors(reg.width * reg.height)]
    elif a.worst:
        colours = [parse_hex(a.worst)]
    else:
        sys.exit("give --worst HEX or --image IMG --box x0,y0,x1,y1")
    w0 = min(colours, key=lambda c: ratio(c, text))
    print("worst pixel under the text: %s, %s:1 against %s without a scrim" % (
        to_hex(w0), fmt(ratio(w0, text), a.target), a.text))
    cands = sorted(colours, key=lambda c: ratio(c, text))[:256]
    while True:
        alpha = next((i / 100 for i in range(101)
                      if all(ratio(blend(c, scrim, i / 100), text) >= a.target for c in cands)), None)
        if alpha is None:
            print("scrim %s cannot reach %.1f:1 even when opaque" % (a.scrim, a.target))
            return 1
        failing = [c for c in colours if ratio(blend(c, scrim, alpha), text) < a.target]
        if not failing:
            break
        cands += failing[:256]
    w = min(colours, key=lambda c: ratio(blend(c, scrim, alpha), text))
    r, g, b = scrim
    print("scrim alpha >= %.2f -> worst blended %s = %s:1 (target %.1f)" % (
        alpha, to_hex(blend(w, scrim, alpha)), fmt(ratio(blend(w, scrim, alpha), text), a.target), a.target))
    print("CSS: background: rgb(%d %d %d / %.2f) behind the text box (a gradient must reach %.2f there)" % (
        r, g, b, alpha, alpha))
    return 0


MACHADO = {  # Machado, Oliveira and Fernandes 2009, severity 1.0; operate on LINEAR sRGB
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602),
               (0.004733, 0.691367, 0.303900)),
}


def simulate(rgb, kind):
    if kind == "normal":
        return rgb
    lrgb = [lin(c) for c in rgb]
    if kind == "gray":
        y = 0.2126 * lrgb[0] + 0.7152 * lrgb[1] + 0.0722 * lrgb[2]
        return (round(enc(y)),) * 3
    return tuple(round(enc(sum(m * v for m, v in zip(row, lrgb)))) for row in MACHADO[kind])


def cmd_cvd(a):
    cols = [parse_hex(h) for h in a.colours]
    worst = 0
    for sim in ("normal", "protan", "deutan", "tritan", "gray"):
        s = [simulate(c, sim) for c in cols]
        labs = [oklab(c) for c in s]
        print("%-7s %s" % (sim, "  ".join("%s L%.2f" % (to_hex(c), lab[0]) for c, lab in zip(s, labs))))
        if sim == "normal":
            continue
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                dl, de = abs(labs[i][0] - labs[j][0]), math.dist(labs[i], labs[j])
                if dl < 0.10:
                    flag = "FAIL" if de < 0.10 else "LABEL"
                    worst = max(worst, 2 if flag == "FAIL" else 1)
                    print("        %-5s %s ~ %s  dL %.3f  dE_OK %.3f" % (
                        flag, a.colours[i], a.colours[j], dl, de))
    print("FAIL = nearly the same colour for that viewer: add text, an icon or a pattern. "
          "LABEL = hue-only difference: fine for large fills, label lines and small marks.")
    return 1 if worst == 2 else 0


def apca_lc(text, bg):
    def y(rgb):
        v = sum(k * (c / 255) ** 2.4 for k, c in zip((0.2126729, 0.7151522, 0.0721750), rgb))
        return v + (0.022 - v) ** 1.414 if v < 0.022 else v
    yt, yb = y(text), y(bg)
    if abs(yb - yt) < 0.0005:
        return 0.0
    if yb > yt:                                    # dark text on a light background
        s = (yb ** 0.56 - yt ** 0.57) * 1.14
        return 0.0 if s < 0.1 else (s - 0.027) * 100
    s = (yb ** 0.65 - yt ** 0.62) * 1.14           # light text on a dark background
    return 0.0 if s > -0.1 else (s + 0.027) * 100


def cmd_apca(a):
    lc = apca_lc(parse_hex(a.text), parse_hex(a.bg))
    band = next((n for t, n in ((75, "body text"), (60, "large / content text"),
                                (45, "headlines and non-text")) if abs(lc) >= t), "below headline level")
    print("Lc %.1f  (advisory: %s; WCAG 2 ratio %s:1 remains the conformance number)" % (
        lc, band, fmt(ratio(parse_hex(a.text), parse_hex(a.bg)))))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("ratio"); x.add_argument("colours", nargs="+"); x.add_argument("--target", type=float, default=4.5)
    x = sp.add_parser("matrix"); x.add_argument("csv"); x.add_argument("--level", choices=("AA", "AAA"), default="AA")
    x.add_argument("--margin", type=float, default=0.0)
    x = sp.add_parser("fix"); x.add_argument("fg"); x.add_argument("bg"); x.add_argument("--move", choices=("fg", "bg"), default="fg")
    x.add_argument("--target", type=float, default=4.5); x.add_argument("--margin", type=float, default=0.0)
    x = sp.add_parser("scrim"); x.add_argument("text"); x.add_argument("--worst"); x.add_argument("--image"); x.add_argument("--box")
    x.add_argument("--scrim", default="#000000"); x.add_argument("--target", type=float, default=4.5)
    x = sp.add_parser("cvd"); x.add_argument("colours", nargs="+")
    x = sp.add_parser("apca"); x.add_argument("text"); x.add_argument("bg")
    a = ap.parse_args()
    return {"ratio": cmd_ratio, "matrix": cmd_matrix, "fix": cmd_fix, "scrim": cmd_scrim,
            "cvd": cmd_cvd, "apca": cmd_apca}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
