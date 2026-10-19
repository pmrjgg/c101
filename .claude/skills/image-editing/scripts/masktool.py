#!/usr/bin/env python3
"""Deterministic mask, compositing and verification helpers for image edits.

Canonical mask convention (same as the image router): single-channel "L" PNG, same size as the
image, WHITE (255) = edit, BLACK (0) = keep. Convert only at the edge with `convert`.

Needs Pillow: PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python

Mask creation
  rect IMG OUT --box x0,y0,x1,y1 [--ellipse]     white box/ellipse over IMG-sized black canvas
  polygon IMG OUT --points x,y x,y x,y ...       white polygon
  from-alpha RGBA OUT [--keep-subject]           transparent area -> white (edit the background);
                                                 --keep-subject inverts (edit the subject)
Mask refinement
  invert IN OUT
  threshold IN OUT [--t 128]                     hard 0/255 mask (fill models want binary)
  grow IN OUT --px N                             dilate N px (negative N erodes)
  feather IN OUT --px N                          gaussian soft edge for blending
  convert MASK OUT --to white-edit|black-edit|alpha-transparent [--image IMG]
                                                 alpha-transparent = RGBA where edit area alpha=0
                                                 (OpenAI style); RGB taken from --image if given
Outpainting
  pad IMG OUT_IMG OUT_MASK --left L --right R --top T --bottom B [--overlap 16] [--fill edge|black|white]
Compositing
  composite ORIG EDITED MASK OUT                 OUT = EDITED inside mask, ORIG outside (exact pixels)
  over FG BG OUT [--x X --y Y] [--scale S]       alpha-composite an RGBA cutout onto a background
  split-alpha RGBA OUT_RGB OUT_ALPHA             for upscaling RGBA safely
  merge-alpha RGB ALPHA OUT                      alpha is resized (LANCZOS) to RGB size first
Inspection
  overlay IMG MASK OUT                           red tint over the edit area, for a visual check
  diff ORIG EDITED [--mask MASK] [--t 8]         JSON: mean abs error and changed-pixel fraction,
                                                 inside vs outside the mask (0..255 scale)

Exit codes: 0 ok, 1 check failed (diff with --max-outside), 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat
except ImportError:  # pragma: no cover
    sys.stderr.write("Pillow missing: use the stack venv python (.venv/bin/python)\n")
    sys.exit(2)


def _open(p: str) -> Image.Image:
    try:
        im = Image.open(p)
        im.load()
        return im
    except (OSError, ValueError) as e:
        sys.stderr.write("cannot read %s: %s\n" % (p, e))
        sys.exit(2)


def _save(im: Image.Image, p: str) -> None:
    d = os.path.dirname(os.path.abspath(p))
    os.makedirs(d, exist_ok=True)
    im.save(p)
    print(p)


def _mask(p: str, size=None) -> Image.Image:
    m = _open(p)
    if m.mode in ("RGBA", "LA"):
        # A mask given as RGBA: treat transparent as edit (OpenAI style) only if RGB is uniform.
        lum = m.convert("L")
        if ImageStat.Stat(lum).extrema[0][0] == ImageStat.Stat(lum).extrema[0][1]:
            m = ImageOps.invert(m.getchannel("A"))
        else:
            m = lum
    else:
        m = m.convert("L")
    if size and m.size != size:
        sys.stderr.write("mask %s is %sx%s, image is %sx%s: resizing with NEAREST\n"
                         % (p, m.size[0], m.size[1], size[0], size[1]))
        m = m.resize(size, Image.NEAREST)
    return m


def cmd_rect(a):
    im = _open(a.img)
    m = Image.new("L", im.size, 0)
    x0, y0, x1, y1 = [int(v) for v in a.box.split(",")]
    d = ImageDraw.Draw(m)
    (d.ellipse if a.ellipse else d.rectangle)([x0, y0, x1, y1], fill=255)
    _save(m, a.out)


def cmd_polygon(a):
    im = _open(a.img)
    m = Image.new("L", im.size, 0)
    pts = [tuple(int(v) for v in p.split(",")) for p in a.points]
    ImageDraw.Draw(m).polygon(pts, fill=255)
    _save(m, a.out)


def cmd_from_alpha(a):
    im = _open(a.rgba).convert("RGBA")
    alpha = im.getchannel("A")
    m = alpha if a.keep_subject else ImageOps.invert(alpha)
    _save(m.point(lambda v: 255 if v >= 128 else 0), a.out)


def cmd_invert(a):
    _save(ImageOps.invert(_mask(a.inp)), a.out)


def cmd_threshold(a):
    _save(_mask(a.inp).point(lambda v: 255 if v >= a.t else 0), a.out)


def cmd_grow(a):
    m = _mask(a.inp)
    n = abs(a.px)
    if n:
        f = ImageFilter.MaxFilter if a.px > 0 else ImageFilter.MinFilter
        # Repeated 3x3 passes approximate a disk better than one big square kernel.
        for _ in range(n):
            m = m.filter(f(3))
    _save(m, a.out)


def cmd_feather(a):
    _save(_mask(a.inp).filter(ImageFilter.GaussianBlur(a.px)), a.out)


def cmd_convert(a):
    m = _mask(a.mask)
    if a.to == "white-edit":
        out = m
    elif a.to == "black-edit":
        out = ImageOps.invert(m)
    else:  # alpha-transparent: RGBA, alpha 0 where we edit
        base = _open(a.image).convert("RGB") if a.image else Image.new("RGB", m.size, (0, 0, 0))
        if base.size != m.size:
            sys.stderr.write("image and mask sizes differ\n")
            sys.exit(2)
        out = base.copy()
        out.putalpha(ImageOps.invert(m))
    _save(out, a.out)


def cmd_pad(a):
    im = _open(a.img).convert("RGB")
    w, h = im.size
    W, H = w + a.left + a.right, h + a.top + a.bottom
    if a.fill == "edge":
        canvas = im.resize((W, H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(24))
    else:
        canvas = Image.new("RGB", (W, H), (0, 0, 0) if a.fill == "black" else (255, 255, 255))
    canvas.paste(im, (a.left, a.top))
    m = Image.new("L", (W, H), 255)
    ov = a.overlap
    keep = [a.left + (ov if a.left else 0), a.top + (ov if a.top else 0),
            a.left + w - (ov if a.right else 0) - 1, a.top + h - (ov if a.bottom else 0) - 1]
    ImageDraw.Draw(m).rectangle(keep, fill=0)
    _save(canvas, a.out_img)
    _save(m, a.out_mask)


def cmd_composite(a):
    orig = _open(a.orig)
    edited = _open(a.edited)
    if edited.size != orig.size:
        sys.stderr.write("edited is %sx%s, original %sx%s: resizing edited with LANCZOS\n"
                         % (edited.size + orig.size))
        edited = edited.resize(orig.size, Image.LANCZOS)
    mode = "RGBA" if "A" in orig.mode or "A" in edited.mode else "RGB"
    out = Image.composite(edited.convert(mode), orig.convert(mode), _mask(a.mask, orig.size))
    _save(out, a.out)


def cmd_over(a):
    fg = _open(a.fg).convert("RGBA")
    bg = _open(a.bg).convert("RGBA")
    if a.scale and a.scale != 1.0:
        fg = fg.resize((max(1, round(fg.width * a.scale)), max(1, round(fg.height * a.scale))), Image.LANCZOS)
    x = a.x if a.x is not None else (bg.width - fg.width) // 2
    y = a.y if a.y is not None else (bg.height - fg.height) // 2
    layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    layer.paste(fg, (x, y), fg)
    _save(Image.alpha_composite(bg, layer), a.out)


def cmd_split_alpha(a):
    im = _open(a.rgba).convert("RGBA")
    _save(im.convert("RGB"), a.out_rgb)
    _save(im.getchannel("A"), a.out_alpha)


def cmd_merge_alpha(a):
    rgb = _open(a.rgb).convert("RGB")
    al = _open(a.alpha).convert("L")
    if al.size != rgb.size:
        al = al.resize(rgb.size, Image.LANCZOS)
    rgb.putalpha(al)
    _save(rgb, a.out)


def cmd_overlay(a):
    im = _open(a.img).convert("RGB")
    m = _mask(a.mask, im.size)
    red = Image.new("RGB", im.size, (255, 0, 0))
    tint = Image.blend(im, red, 0.45)
    _save(Image.composite(tint, im, m), a.out)


def _region_stats(diff_l: Image.Image, region: Image.Image, t: int):
    """Mean abs error and fraction of pixels with error > t, restricted to region (L, 255=in)."""
    hist_all = diff_l.histogram(mask=region)
    n = sum(hist_all)
    if n == 0:
        return None
    mae = sum(i * c for i, c in enumerate(hist_all)) / n
    changed = sum(hist_all[t + 1:]) / n
    return {"pixels": n, "mae": round(mae, 3), "changed_frac": round(changed, 5)}


def cmd_diff(a):
    o = _open(a.orig).convert("RGB")
    e = _open(a.edited).convert("RGB")
    res = {"orig": a.orig, "edited": a.edited, "orig_size": o.size, "edited_size": e.size,
           "same_size": o.size == e.size}
    if e.size != o.size:
        e = e.resize(o.size, Image.LANCZOS)
    # Per-pixel max channel difference, 0..255.
    r, g, b = ImageChops.difference(o, e).split()
    d = ImageChops.lighter(ImageChops.lighter(r, g), b)
    if a.mask:
        m = _mask(a.mask, o.size).point(lambda v: 255 if v >= 128 else 0)
        res["inside"] = _region_stats(d, m, a.t)
        res["outside"] = _region_stats(d, ImageOps.invert(m), a.t)
    else:
        res["all"] = _region_stats(d, Image.new("L", o.size, 255), a.t)
    fails = []
    if a.max_outside is not None and res.get("outside") and res["outside"]["mae"] > a.max_outside:
        fails.append("outside-mask MAE %.3f > %.3f" % (res["outside"]["mae"], a.max_outside))
    if a.min_inside is not None and res.get("inside") and res["inside"]["mae"] < a.min_inside:
        fails.append("inside-mask MAE %.3f < %.3f: the edit barely changed the target" % (res["inside"]["mae"], a.min_inside))
    res["fails"] = fails
    print(json.dumps(res, indent=2))
    return 1 if fails else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("rect"); x.add_argument("img"); x.add_argument("out"); x.add_argument("--box", required=True)
    x.add_argument("--ellipse", action="store_true"); x.set_defaults(fn=cmd_rect)
    x = s.add_parser("polygon"); x.add_argument("img"); x.add_argument("out")
    x.add_argument("--points", nargs="+", required=True); x.set_defaults(fn=cmd_polygon)
    x = s.add_parser("from-alpha"); x.add_argument("rgba"); x.add_argument("out")
    x.add_argument("--keep-subject", action="store_true"); x.set_defaults(fn=cmd_from_alpha)
    x = s.add_parser("invert"); x.add_argument("inp"); x.add_argument("out"); x.set_defaults(fn=cmd_invert)
    x = s.add_parser("threshold"); x.add_argument("inp"); x.add_argument("out")
    x.add_argument("--t", type=int, default=128); x.set_defaults(fn=cmd_threshold)
    x = s.add_parser("grow"); x.add_argument("inp"); x.add_argument("out")
    x.add_argument("--px", type=int, required=True); x.set_defaults(fn=cmd_grow)
    x = s.add_parser("feather"); x.add_argument("inp"); x.add_argument("out")
    x.add_argument("--px", type=float, required=True); x.set_defaults(fn=cmd_feather)
    x = s.add_parser("convert"); x.add_argument("mask"); x.add_argument("out")
    x.add_argument("--to", choices=["white-edit", "black-edit", "alpha-transparent"], required=True)
    x.add_argument("--image"); x.set_defaults(fn=cmd_convert)
    x = s.add_parser("pad"); x.add_argument("img"); x.add_argument("out_img"); x.add_argument("out_mask")
    for side in ("left", "right", "top", "bottom"):
        x.add_argument("--" + side, type=int, default=0)
    x.add_argument("--overlap", type=int, default=16)
    x.add_argument("--fill", choices=["edge", "black", "white"], default="edge"); x.set_defaults(fn=cmd_pad)
    x = s.add_parser("composite"); x.add_argument("orig"); x.add_argument("edited"); x.add_argument("mask")
    x.add_argument("out"); x.set_defaults(fn=cmd_composite)
    x = s.add_parser("over"); x.add_argument("fg"); x.add_argument("bg"); x.add_argument("out")
    x.add_argument("--x", type=int); x.add_argument("--y", type=int); x.add_argument("--scale", type=float, default=1.0)
    x.set_defaults(fn=cmd_over)
    x = s.add_parser("split-alpha"); x.add_argument("rgba"); x.add_argument("out_rgb"); x.add_argument("out_alpha")
    x.set_defaults(fn=cmd_split_alpha)
    x = s.add_parser("merge-alpha"); x.add_argument("rgb"); x.add_argument("alpha"); x.add_argument("out")
    x.set_defaults(fn=cmd_merge_alpha)
    x = s.add_parser("overlay"); x.add_argument("img"); x.add_argument("mask"); x.add_argument("out")
    x.set_defaults(fn=cmd_overlay)
    x = s.add_parser("diff"); x.add_argument("orig"); x.add_argument("edited"); x.add_argument("--mask")
    x.add_argument("--t", type=int, default=8)
    x.add_argument("--max-outside", type=float); x.add_argument("--min-inside", type=float)
    x.set_defaults(fn=cmd_diff)
    a = p.parse_args(argv)
    if a.cmd == "pad" and not (a.left or a.right or a.top or a.bottom):
        sys.stderr.write("pad: give at least one of --left/--right/--top/--bottom\n")
        return 2
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
