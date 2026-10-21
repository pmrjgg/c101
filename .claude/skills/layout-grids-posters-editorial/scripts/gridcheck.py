#!/usr/bin/env python3
"""Grid maths, grid overlays, squint renders and spacing-scale audits for layouts.

`columns`, `modular`, `spacing` are stdlib-only (python3 -I is fine). `overlay` and `squint`
need Pillow: run them with the stack venv,
    PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python

Lengths accept a unit suffix (px, mm, pt, in); bare numbers use --unit (default px).
Overlay converts everything to image pixels with --ppi (default 96: CSS px = image px at 1x;
use the export resolution for PDFs rendered with pdftoppm -r).

Subcommands
  columns W N --gutter G --margin M [--snap] [--base 4]
        column width = (W - 2M - (N-1)G) / N, column edges; --snap lists margins on the base
        step that give whole-pixel columns
  modular H --leading L --rows N [--min-margin m]
        row height k x L with one leading between rows; for each k the text-area height
        (N*k + N - 1) * L and what is left for top + bottom margins
  overlay IMG OUT --cols N --gutter G --margin M [--margin-top T] [--margin-bottom B]
        [--rows R] [--row-gutter RG] [--baseline BL] [--baseline-start Y0] [--unit mm --ppi 100]
        red column/row fields, cyan baselines; Read OUT and check every edge lands on a line
  squint IMG OUT [--radius R] [--scale 0.25]
        blurred greyscale render: the first blob you see must be the primary message
  spacing FILE... [--scale 0,2,4,8,12,16,24,32,48,64,96,128] [--rem 16] [--allow 1]
        off-scale margin/padding/gap/inset values in CSS, SCSS, JSX/TSX or JSON specs
        (Figma-style itemSpacing, paddingLeft ...); exit 1 when any is found

Exit codes: 0 ok, 1 check failed (spacing found off-scale values), 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys

UNIT_PX = {"px": 1.0, "in": 96.0, "mm": 96.0 / 25.4, "pt": 96.0 / 72.0}  # CSS reference units
LEN_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(px|mm|pt|in)?\s*$")


def to_unit(value: str, unit: str) -> float:
    """Parse '14pt', '4.94mm', '24' (assumed `unit`) and return it expressed in `unit`."""
    m = LEN_RE.match(str(value))
    if not m:
        raise SystemExit("bad length %r (use e.g. 24, 24px, 4.94mm, 14pt)" % value)
    num, u = float(m.group(1)), m.group(2) or unit
    return num * UNIT_PX[u] / UNIT_PX[unit]


def fmt(x: float) -> float:
    return round(x, 3)


# ---------------------------------------------------------------- columns
def cmd_columns(a) -> int:
    u = a.unit
    W, G, M = to_unit(a.width, u), to_unit(a.gutter, u), to_unit(a.margin, u)
    n = a.n
    col = (W - 2 * M - (n - 1) * G) / n
    if col <= 0:
        print(json.dumps({"error": "margins and gutters exceed the width"}))
        return 1
    edges = [{"col": i + 1, "x0": fmt(M + i * (col + G)), "x1": fmt(M + i * (col + G) + col)} for i in range(n)]
    out = {"unit": u, "width": fmt(W), "columns": n, "gutter": fmt(G), "margin": fmt(M),
           "column": fmt(col), "content_width": fmt(W - 2 * M), "edges": edges}
    if a.snap:
        cands = []
        lo, hi = max(0.0, M - 4 * a.base), M + 4 * a.base
        m = math.ceil(lo / a.base) * a.base
        while m <= hi:
            c = (W - 2 * m - (n - 1) * G) / n
            if c > 0 and abs(c - round(c)) < 1e-9:
                cands.append({"margin": fmt(m), "column": int(round(c)), "delta": fmt(m - M)})
            m += a.base
        out["snap"] = sorted(cands, key=lambda d: abs(d["delta"]))[:6]
    print(json.dumps(out, indent=2))
    return 0


# ---------------------------------------------------------------- modular
def cmd_modular(a) -> int:
    u = a.unit
    H, L = to_unit(a.height, u), to_unit(a.leading, u)
    n = a.rows
    min_m = to_unit(a.min_margin, u) if a.min_margin else 0.0
    rows = []
    k = 1
    while True:
        text = (n * k + n - 1) * L
        left = H - text
        if left < 2 * min_m:
            break
        rows.append({"k_lines_per_module": k, "module": fmt(k * L), "row_gap": fmt(L),
                     "text_area": fmt(text), "baselines": n * k + n - 1,
                     "margins_total": fmt(left), "each_if_equal": fmt(left / 2)})
        k += 1
    print(json.dumps({"unit": u, "height": fmt(H), "leading": fmt(L), "rows": n,
                      "options_tightest_last": rows}, indent=2))
    return 0 if rows else 1


# ---------------------------------------------------------------- overlay
def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageOps  # noqa: F401
        return Image, ImageDraw, ImageFilter, ImageOps
    except ImportError:
        sys.stderr.write("Pillow missing: run with the stack venv python\n")
        sys.exit(2)


def cmd_overlay(a) -> int:
    Image, ImageDraw, _, _ = _pil()
    try:
        im = Image.open(a.img).convert("RGBA")
    except OSError as e:
        sys.stderr.write("cannot read %s: %s\n" % (a.img, e))
        return 2
    W, H = im.size
    px = lambda v: to_unit(v, a.unit) * (UNIT_PX[a.unit] * a.ppi / 96.0)  # noqa: E731
    G, M = px(a.gutter), px(a.margin)
    MT = px(a.margin_top) if a.margin_top is not None else M
    MB = px(a.margin_bottom) if a.margin_bottom is not None else MT
    col = (W - 2 * M - (a.cols - 1) * G) / a.cols
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    report = {"image": [W, H], "column_px": fmt(col), "columns": []}
    for i in range(a.cols):
        x0 = M + i * (col + G)
        d.rectangle([x0, 0, x0 + col, H], fill=(255, 0, 64, 28))
        d.line([(x0, 0), (x0, H)], fill=(255, 0, 64, 160), width=1)
        d.line([(x0 + col, 0), (x0 + col, H)], fill=(255, 0, 64, 160), width=1)
        report["columns"].append([fmt(x0), fmt(x0 + col)])
    if a.rows:
        RG = px(a.row_gutter) if a.row_gutter is not None else G
        rowh = (H - MT - MB - (a.rows - 1) * RG) / a.rows
        report["row_px"], report["rows"] = fmt(rowh), []
        for r in range(a.rows):
            y0 = MT + r * (rowh + RG)
            d.line([(0, y0), (W, y0)], fill=(255, 0, 64, 160), width=1)
            d.line([(0, y0 + rowh), (W, y0 + rowh)], fill=(255, 0, 64, 160), width=1)
            report["rows"].append([fmt(y0), fmt(y0 + rowh)])
    else:
        d.line([(0, MT), (W, MT)], fill=(255, 0, 64, 160), width=1)
        d.line([(0, H - MB), (W, H - MB)], fill=(255, 0, 64, 160), width=1)
    if a.baseline:
        B = px(a.baseline)
        y = px(a.baseline_start) if a.baseline_start is not None else MT
        count = 0
        while y <= H:
            d.line([(0, y), (W, y)], fill=(0, 170, 255, 120), width=1)
            y += B
            count += 1
        report["baseline_px"], report["baselines"] = fmt(B), count
    Image.alpha_composite(im, lay).convert("RGB").save(a.out)
    report["out"] = a.out
    print(json.dumps(report, indent=2))
    return 0


# ---------------------------------------------------------------- squint
def cmd_squint(a) -> int:
    Image, _, ImageFilter, ImageOps = _pil()
    try:
        im = Image.open(a.img).convert("RGB")
    except OSError as e:
        sys.stderr.write("cannot read %s: %s\n" % (a.img, e))
        return 2
    if a.scale and a.scale != 1:
        im = im.resize((max(1, round(im.width * a.scale)), max(1, round(im.height * a.scale))), Image.LANCZOS)
    r = a.radius if a.radius is not None else max(2.0, max(im.size) / 120.0)
    out = ImageOps.grayscale(im).filter(ImageFilter.GaussianBlur(r))
    out.save(a.out)
    print(json.dumps({"out": a.out, "size": out.size, "blur_radius_px": fmt(r)}))
    return 0


# ---------------------------------------------------------------- spacing
CSS_PROP = re.compile(
    r"(?<![\w-])((?:margin|padding|inset|scroll-margin|scroll-padding)(?:-[a-z-]+)?|gap|row-gap|column-gap|"
    r"grid-gap|top|right|bottom|left)\s*:\s*([^;{}]+)", re.I)
JS_PROP = re.compile(r"""(?<![\w-])["']?((?:margin|padding|inset|gap|rowGap|columnGap|itemSpacing|counterAxisSpacing|spacing)"""
                     r"""[A-Za-z]*)["']?\s*:\s*["']?(-?\d+(?:\.\d+)?(?:px|rem)?)["']?""")
VAL = re.compile(r"(-?\d*\.?\d+)(px|rem)\b")


def cmd_spacing(a) -> int:
    scale = sorted({float(s) for s in a.scale.split(",")})
    allow = {float(s) for s in a.allow.split(",")} if a.allow else set()
    bad = []
    for path in a.files:
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except OSError as e:
            sys.stderr.write("cannot read %s: %s\n" % (path, e))
            return 2
        for ln, line in enumerate(lines, 1):
            hits = []
            for prop, rhs in CSS_PROP.findall(line):
                if "calc(" in rhs or "var(" in rhs or "clamp(" in rhs:
                    continue  # token or formula: audit the token definitions instead
                hits += [(prop, float(v) * (a.rem if u == "rem" else 1.0), v + u) for v, u in VAL.findall(rhs)]
            for prop, raw in ([] if hits else JS_PROP.findall(line)):
                v = VAL.match(raw)
                num = float(v.group(1)) * (a.rem if v and v.group(2) == "rem" else 1.0) if v else float(raw)
                hits.append((prop, num, raw))
            for prop, px, raw in hits:
                ab = abs(px)
                if ab in scale or ab in allow:
                    continue
                near = min(scale, key=lambda s: abs(s - ab))
                bad.append({"file": path, "line": ln, "property": prop, "value": raw,
                            "px": fmt(px), "nearest": near})
    for b in bad:
        print("%(file)s:%(line)d  %(property)s: %(value)s (%(px)gpx) -> %(nearest)g" % b)
    print(json.dumps({"off_scale": len(bad), "scale": scale}))
    return 1 if bad else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    c = s.add_parser("columns")
    c.add_argument("width"); c.add_argument("n", type=int)
    c.add_argument("--gutter", required=True); c.add_argument("--margin", required=True)
    c.add_argument("--snap", action="store_true"); c.add_argument("--base", type=float, default=4.0)
    c.add_argument("--unit", default="px", choices=sorted(UNIT_PX)); c.set_defaults(fn=cmd_columns)
    m = s.add_parser("modular")
    m.add_argument("height"); m.add_argument("--leading", required=True); m.add_argument("--rows", type=int, required=True)
    m.add_argument("--min-margin"); m.add_argument("--unit", default="px", choices=sorted(UNIT_PX))
    m.set_defaults(fn=cmd_modular)
    o = s.add_parser("overlay")
    o.add_argument("img"); o.add_argument("out")
    o.add_argument("--cols", type=int, required=True); o.add_argument("--gutter", required=True)
    o.add_argument("--margin", required=True); o.add_argument("--margin-top"); o.add_argument("--margin-bottom")
    o.add_argument("--rows", type=int); o.add_argument("--row-gutter")
    o.add_argument("--baseline"); o.add_argument("--baseline-start")
    o.add_argument("--unit", default="px", choices=sorted(UNIT_PX)); o.add_argument("--ppi", type=float, default=96.0)
    o.set_defaults(fn=cmd_overlay)
    q = s.add_parser("squint")
    q.add_argument("img"); q.add_argument("out"); q.add_argument("--radius", type=float)
    q.add_argument("--scale", type=float, default=1.0); q.set_defaults(fn=cmd_squint)
    sp = s.add_parser("spacing")
    sp.add_argument("files", nargs="+")
    sp.add_argument("--scale", default="0,2,4,8,12,16,24,32,48,64,96,128")
    sp.add_argument("--rem", type=float, default=16.0); sp.add_argument("--allow", default="1")
    sp.set_defaults(fn=cmd_spacing)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
