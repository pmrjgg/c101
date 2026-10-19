#!/usr/bin/env python3
"""Icon set audit: ink coverage vs a peer median, live-area bounds, style attributes, pixel sheet.

Needs Pillow and resvg-py (both in the stack venv):
    PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python
    "$PY" -I icon_audit.py new/*.svg [--ref set/a.svg set/b.svg] [--size 24] [--pad 2]
                           [--tol 0.10] [--sheet sheet.png] [--json]

coverage = mean alpha of a 4x render (ink fraction of the canvas, 0..1).
  MASS    coverage outside (median of --ref, or of all files) +/- tol, relative
  BOUNDS  ink outside the live area (canvas minus --pad) in the 1x render
  STYLE   stroke-width / linecap / linejoin differ from the most common value,
          or a transform or a paint other than none/currentColor is present
--sheet writes a contact sheet: each icon at 1x (size) and at 16 px, magnified 4x with
nearest-neighbour so half-covered pixels stay visible, live area outlined in red.
Exit 1 when any audited icon is flagged.
"""
import argparse
import io
import json
import re
import statistics
import sys
from collections import Counter

import resvg_py
from PIL import Image, ImageDraw

ATTRS = ("stroke-width", "stroke-linecap", "stroke-linejoin")


def render(text, px):
    png = bytes(resvg_py.svg_to_bytes(svg_string=text, width=px))
    return Image.open(io.BytesIO(png)).convert("RGBA")


def coverage(text, size):
    a = render(text, size * 4).getchannel("A")
    return sum(i * n for i, n in enumerate(a.histogram())) / 255 / (a.width * a.height)


def style_of(text):
    out = {a: ",".join(sorted(set(re.findall(r'%s="([^"]+)"' % a, text)))) or "-" for a in ATTRS}
    paints = set(re.findall(r'(?:fill|stroke)="([^"]+)"', text)) - {"none", "currentColor"}
    out["paint"] = ",".join(sorted(paints)) or "ok"
    out["transform"] = "transform=" in text
    return out


def tile(text, px, pad, size, zoom=4):
    im = render(text, px)
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    big = bg.convert("RGB").resize((px * zoom, px * zoom), Image.NEAREST)
    p = pad * px / size * zoom
    ImageDraw.Draw(big).rectangle([p, p, px * zoom - p - 1, px * zoom - p - 1], outline=(230, 60, 60))
    return big


def write_sheet(path, files, texts, size, pad):
    z, gap, lab = 4, 8, 14
    cell_w = size * z + 16 * z + 3 * gap
    out = Image.new("RGB", (cell_w * min(4, len(files)), (size * z + lab + gap) * -(-len(files) // 4)), "white")
    d = ImageDraw.Draw(out)
    for i, (f, t) in enumerate(zip(files, texts)):
        x, y = (i % 4) * cell_w, (i // 4) * (size * z + lab + gap)
        d.text((x + gap, y), f.split("/")[-1][:28], fill=(0, 0, 0))
        out.paste(tile(t, size, pad, size), (x + gap, y + lab))
        out.paste(tile(t, 16, pad, size), (x + 2 * gap + size * z, y + lab))
    out.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--ref", nargs="*", default=None, help="peer icons whose median sets the MASS band")
    ap.add_argument("--size", type=int, default=24)
    ap.add_argument("--pad", type=float, default=2)
    ap.add_argument("--tol", type=float, default=0.10)
    ap.add_argument("--sheet")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    texts = [open(f, encoding="utf-8").read() for f in a.files]
    rows = []
    for f, text in zip(a.files, texts):
        bbox = render(text, a.size).getchannel("A").getbbox()
        rows.append({"file": f, "coverage": coverage(text, a.size), "bbox": bbox, **style_of(text)})
    ref = [coverage(open(f, encoding="utf-8").read(), a.size) for f in a.ref] if a.ref else [r["coverage"] for r in rows]
    med = statistics.median(ref)
    common = {k: Counter(r[k] for r in rows).most_common(1)[0][0] for k in ATTRS}
    lo, hi, bad = a.pad, a.size - a.pad, 0
    for r in rows:
        r["vs_median"] = r["coverage"] / med - 1
        b = r["bbox"]
        r["flags"] = [n for n, hit in (
            ("MASS", abs(r["vs_median"]) > a.tol),
            ("BOUNDS", b is None or b[0] < lo or b[1] < lo or b[2] > hi or b[3] > hi),
            ("STYLE", any(r[k] != common[k] for k in ATTRS) or r["paint"] != "ok" or r["transform"]),
        ) if hit]
        bad += bool(r["flags"])
    if a.sheet:
        write_sheet(a.sheet, a.files, texts, a.size, a.pad)
    if a.json:
        print(json.dumps({"median": med, "common": common, "icons": rows}, indent=1))
    else:
        print("median %.4f (%s); band +/-%d%%; common %s" % (med, "ref" if a.ref else "all", a.tol * 100, common))
        for r in rows:
            print("%-24s cov %.4f %+6.1f%%  bbox %-18s %s" % (
                r["file"].split("/")[-1], r["coverage"], 100 * r["vs_median"], r["bbox"], " ".join(r["flags"]) or "ok"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
