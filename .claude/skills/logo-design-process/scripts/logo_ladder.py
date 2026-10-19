#!/usr/bin/env python3
"""Logo size ladder: render a vector master at small sizes, measure counters, write a sheet.

Needs Pillow and resvg-py (both in the stack venv):
    PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python
    "$PY" -I logo_ladder.py mark.svg --counter 32,21,47,27 [--counter ...] \
        [--sizes 16,24,32,64,256] [--sheet ladder.png] [--bg white|black]

--counter x0,y0,x1,y1 is a box in viewBox units inside one counter (hole). For every size the
pixels whose centres fall inside the box are sampled: min alpha <= 0.25 open, <= 0.60 closing,
else closed (the hole has filled in). The sheet shows each size magnified with nearest-neighbour
so grey, half-covered pixels stay visible. Exit 1 when any counter is closing or closed.
"""
import argparse
import io
import re
import sys

import resvg_py
from PIL import Image, ImageDraw


def render(text, px):
    png = bytes(resvg_py.svg_to_bytes(svg_string=text, width=px))
    return Image.open(io.BytesIO(png)).convert("RGBA")


def viewbox(text):
    m = re.search(r'viewBox="\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)', text)
    if not m:
        sys.exit("SVG has no viewBox")
    return [float(v) for v in m.groups()]


def verdict(a):
    return "open" if a <= 0.25 else ("closing" if a <= 0.60 else "closed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--sizes", default="16,24,32,64,256")
    ap.add_argument("--counter", action="append", default=[])
    ap.add_argument("--sheet")
    ap.add_argument("--bg", default="white")
    a = ap.parse_args()
    text = open(a.svg, encoding="utf-8").read()
    vx, vy, vw, vh = viewbox(text)
    sizes = [int(s) for s in a.sizes.split(",")]
    bad = 0
    tiles = []
    for px in sizes:
        im = render(text, px)
        alpha = im.getchannel("A")
        s = px / vw
        for c in a.counter:
            x0, y0, x1, y1 = (float(v) for v in c.split(","))
            vals = [alpha.getpixel((x, y)) / 255
                    for y in range(im.height) for x in range(px)
                    if x0 <= vx + (x + 0.5) / s <= x1 and y0 <= vy + (y + 0.5) / s <= y1]
            if not vals:
                print("%4dpx counter %s: no pixel centre inside the box (smaller than 1 px): closed" % (px, c))
                bad += 1
                continue
            v = verdict(min(vals))
            bad += v != "open"
            print("%4dpx counter %s: min %.2f mean %.2f -> %s" % (px, c, min(vals), sum(vals) / len(vals), v))
        bg = Image.new("RGBA", im.size, a.bg)
        bg.alpha_composite(im)
        z = max(1, 256 // px)
        tiles.append((px, bg.convert("RGB").resize((px * z, im.height * z), Image.NEAREST)))
    if a.sheet:
        w = sum(t.width for _, t in tiles) + 16 * (len(tiles) + 1)
        h = max(t.height for _, t in tiles) + 32
        out = Image.new("RGB", (w, h), (235, 235, 235))
        d, x = ImageDraw.Draw(out), 16
        for px, t in tiles:
            d.text((x, 4), "%d px" % px, fill=(0, 0, 0))
            out.paste(t, (x, 24))
            x += t.width + 16
        out.save(a.sheet)
        print(a.sheet)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
