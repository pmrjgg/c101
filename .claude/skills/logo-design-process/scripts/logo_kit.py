#!/usr/bin/env python3
"""Raster half of a logo export kit from an SVG master (Pillow + resvg-py, stack venv).

    PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python
    "$PY" -I logo_kit.py mark.svg --name acme-mark --out kit/ --width 240 \
        [--small mark-16.svg] [--bg '#1A1A2E'] [--fg-on-bg mark-reversed.svg]

Writes into --out:
  <name>@1x.png @2x @3x     transparent PNGs, width --width / 2x / 3x
  favicon.ico               32 px frame from the master + 16 px frame (from --small when given)
  apple-touch-icon.png      180 px, opaque --bg, mark fitted into 140 px (20 px padding)
  icon-192.png, icon-512.png  manifest 'any' icons, transparent, 8% padding
  icon-mask.png             512 px maskable: opaque --bg, every ink pixel inside the
                            central circle of radius 0.40 x 512 (the 80% safe zone)
Prints the measured ink radius of the maskable icon and the manifest/link snippets.
"""
import argparse
import io
import json
import math
import os

import resvg_py
from PIL import Image


def render(path, width):
    png = bytes(resvg_py.svg_to_bytes(svg_string=open(path, encoding="utf-8").read(), width=width))
    return Image.open(io.BytesIO(png)).convert("RGBA")


def fit(path, box, canvas, bg=None):
    """Render the mark so its ink bbox fits in a box x box square, centred on canvas x canvas."""
    probe = render(path, 1024)
    x0, y0, x1, y1 = probe.getchannel("A").getbbox()
    scale = box / max(x1 - x0, y1 - y0)
    im = render(path, max(1, round(1024 * scale)))
    bx0, by0, bx1, by1 = im.getchannel("A").getbbox()
    ink = im.crop((bx0, by0, bx1, by1))
    out = Image.new("RGBA", (canvas, canvas), bg or (0, 0, 0, 0))
    out.alpha_composite(ink, ((canvas - ink.width) // 2, (canvas - ink.height) // 2))
    return out


def ink_radius(im, alpha_min=8):
    a, c = im.getchannel("A"), (im.width - 1) / 2
    r = 0.0
    for y in range(im.height):
        for x in range(im.width):
            if a.getpixel((x, y)) > alpha_min:
                r = max(r, math.hypot(x - c, y - c) + 0.71)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default="kit")
    ap.add_argument("--width", type=int, default=240)
    ap.add_argument("--small", help="hand-fitted 16 px variant (SVG)")
    ap.add_argument("--bg", default="#FFFFFF", help="opaque background for touch and maskable icons")
    ap.add_argument("--fg-on-bg", help="reversed mark for the opaque icons (default: the master)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    p = lambda f: os.path.join(a.out, f)
    for k in (1, 2, 3):
        render(a.svg, a.width * k).save(p("%s@%dx.png" % (a.name, k)))
    i32 = fit(a.svg, 30, 32)
    i16 = fit(a.small or a.svg, 15, 16)
    i32.save(p("favicon.ico"), sizes=[(16, 16), (32, 32)], append_images=[i16])
    on_bg = a.fg_on_bg or a.svg
    fit(on_bg, 140, 180, a.bg).convert("RGB").save(p("apple-touch-icon.png"))
    fit(a.svg, round(192 * 0.84), 192).save(p("icon-192.png"))
    fit(a.svg, round(512 * 0.84), 512).save(p("icon-512.png"))
    box = 512 * 0.80 / math.sqrt(2)          # a square of side 0.8/sqrt2 fits the safe circle
    mask = fit(on_bg, round(box), 512)
    r = ink_radius(mask)
    full = Image.new("RGBA", (512, 512), a.bg)
    full.alpha_composite(mask)
    full.convert("RGB").save(p("icon-mask.png"))
    print("maskable ink radius %.1f px (limit %.1f)" % (r, 0.40 * 512))
    print(json.dumps({"icons": [
        {"src": "/icon-192.png", "type": "image/png", "sizes": "192x192"},
        {"src": "/icon-512.png", "type": "image/png", "sizes": "512x512"},
        {"src": "/icon-mask.png", "type": "image/png", "sizes": "512x512", "purpose": "maskable"}]}, indent=1))
    print('<link rel="icon" href="/favicon.ico" sizes="32x32">\n'
          '<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
          '<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
          '<link rel="manifest" href="/manifest.webmanifest">')


if __name__ == "__main__":
    main()
