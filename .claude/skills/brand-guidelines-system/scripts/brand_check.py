#!/usr/bin/env python3
"""Brand checks against colour tokens: accessibility pairs table and screenshot drift audit.

    python3 -I brand_check.py pairs brand.tokens.json color.text.body/color.bg.page ...
        Markdown table of WCAG 2.x ratios for token pairs (stdlib only), with permitted use.
    PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python
    "$PY" -I brand_check.py drift shot.png brand.tokens.json [--k 12] [--min-share 0.005]
        [--logo-box x0,y0,x1,y1 --clear 24]
        Dominant colours of a screenshot (Pillow median cut) -> nearest token by deltaE_OK:
        <= 0.02 match (about one JND), <= 0.05 near (tint, compression, anti-aliasing),
        > 0.05 OFF (not in the palette). --logo-box/--clear checks the clear-space band for
        foreign ink (> 0.5% of band pixels farther than 0.10 from the band's main colour).

Tokens: DTCG .tokens.json (colour $value objects with hex, or srgb/oklch components, or hex
strings; aliases like "{color.pink.600}" are resolved) or a flat {"name": "#hex"} map.
Exit 1 on a failing pair (< 3:1), an OFF colour above --min-share, or a clear-space breach.
"""
import argparse
import json
import math
import sys
from collections import Counter


def lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def oklab(rgb255):
    r, g, b = (lin(c / 255) for c in rgb255)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklch_to_rgb255(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin_rgb = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
               -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
               -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    enc = lambda c: 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return tuple(round(255 * min(max(enc(max(c, 0.0)), 0.0), 1.0)) for c in lin_rgb)


def hex_rgb(h):
    h = h.strip().lstrip("#")
    if len(h) in (3, 4):  # CSS shorthand #abc / #abcd
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb255):
    r, g, b = (lin(c / 255) for c in rgb255)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = sorted((luminance(a), luminance(b)))
    return (lb + 0.05) / (la + 0.05)


def load_tokens(path):
    data, raw = json.load(open(path, encoding="utf-8")), {}

    def walk(node, name):
        if isinstance(node, str):
            raw[name] = node
        elif isinstance(node, dict) and "$value" in node:
            raw[name] = node["$value"]
        elif isinstance(node, dict):
            for k, child in node.items():
                if not k.startswith("$"):
                    walk(child, name + "." + k if name else k)

    walk(data, "")

    def resolve(v, depth=0):
        if isinstance(v, str) and v.startswith("{") and v.endswith("}") and depth < 10:
            return resolve(raw.get(v[1:-1]), depth + 1)
        if isinstance(v, str) and v.startswith("#"):
            return hex_rgb(v)
        if isinstance(v, dict):
            if v.get("hex"):
                return hex_rgb(v["hex"])
            if v.get("colorSpace") == "srgb":
                return tuple(round(255 * (0 if c == "none" else c)) for c in v["components"])
            if v.get("colorSpace") == "oklch":
                return oklch_to_rgb255(*(0 if c == "none" else c for c in v["components"]))
        return None

    return {n: c for n, c in ((n, resolve(v)) for n, v in raw.items()) if c is not None}


def cmd_pairs(a):
    toks, bad = load_tokens(a.tokens), 0
    print("| Foreground | Background | Ratio | Permitted |\n|---|---|---|---|")
    for p in a.pair:
        fg, bg = p.split("/")
        missing = [n for n in (fg, bg) if n not in toks]
        if missing:
            sys.exit("unknown colour token(s) %s; known: %s" % (", ".join(missing), ", ".join(sorted(toks))))
        r = ratio(toks[fg], toks[bg])
        use = (("all text, AA and AAA" if r >= 7 else "all text AA; large text AAA") if r >= 4.5 else
               "large text >= 24 px or >= 18.66 px bold, UI and icons" if r >= 3 else "decorative only")
        bad += r < 3
        print("| %s #%02X%02X%02X | %s #%02X%02X%02X | %.2f | %s |" % (fg, *toks[fg], bg, *toks[bg], r, use))
    return 1 if bad else 0


def cmd_drift(a):
    from PIL import Image  # only this subcommand needs Pillow

    toks = {n: (rgb, oklab(rgb)) for n, rgb in load_tokens(a.tokens).items()}
    im = Image.open(a.image).convert("RGB")
    q = im.quantize(colors=a.k, method=Image.Quantize.MEDIANCUT)
    pal, total, bad = q.getpalette(), im.width * im.height, 0
    print("share   colour   nearest token              dE_OK  verdict")
    for count, idx in sorted(q.getcolors(a.k), reverse=True):
        share = count / total
        if share < a.min_share:
            continue
        rgb = tuple(pal[3 * idx:3 * idx + 3])
        name, (trgb, tlab) = min(toks.items(), key=lambda t: math.dist(oklab(rgb), t[1][1]))
        d = math.dist(oklab(rgb), tlab)
        v = "match" if d <= 0.02 else ("near" if d <= 0.05 else "OFF")
        bad += v == "OFF"
        print("%5.1f%%  #%02X%02X%02X  %-26s %.3f  %s" % (100 * share, *rgb, name + " #%02X%02X%02X" % trgb, d, v))
    if a.logo_box and a.clear:
        x0, y0, x1, y1 = (int(v) for v in a.logo_box.split(","))
        c = a.clear
        band = [(x, y) for y in range(max(0, y0 - c), min(im.height, y1 + c))
                for x in range(max(0, x0 - c), min(im.width, x1 + c))
                if not (x0 <= x < x1 and y0 <= y < y1)]
        px = [im.getpixel(p) for p in band]
        base = oklab(Counter(px).most_common(1)[0][0])
        foreign = sum(math.dist(oklab(p), base) > 0.10 for p in px) / len(px)
        breach = foreign > 0.005
        bad += breach
        print("clear space %d px around %s: %.2f%% foreign pixels -> %s" % (
            c, a.logo_box, 100 * foreign, "BREACH" if breach else "ok"))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("pairs"); x.add_argument("tokens"); x.add_argument("pair", nargs="+")
    x = sp.add_parser("drift"); x.add_argument("image"); x.add_argument("tokens")
    x.add_argument("--k", type=int, default=12); x.add_argument("--min-share", type=float, default=0.005)
    x.add_argument("--logo-box"); x.add_argument("--clear", type=int, default=0)
    a = ap.parse_args()
    return cmd_pairs(a) if a.cmd == "pairs" else cmd_drift(a)


if __name__ == "__main__":
    sys.exit(main())
