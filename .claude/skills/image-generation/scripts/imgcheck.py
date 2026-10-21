#!/usr/bin/env python3
"""Inspect, gate, annotate and compare generated images.

Needs Pillow: run with the stack's venv interpreter, e.g.
    PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python

Subcommands
  info FILE...                         JSON per file: size, mode, aspect, alpha coverage, sha
  expect FILE --aspect 16:9 [--tol 0.02] [--min-side 1024] [--alpha] [--opaque] [--max-mb 8]
                                       exit 0 when every gate passes, 1 otherwise (prints reasons)
  sidecar FILE [--set k=v ...] [--json-file extra.json] [--sidecar PATH]
                                       create or merge FILE.json (the router's sidecar) or PATH;
                                       your keys go under "agent", router-written keys are kept
  sheet OUT FILE... [--cols 3] [--cell 512]
                                       labelled contact sheet; transparency shown on a checkerboard,
                                       so one Read call reviews N variants

Exit codes: 0 ok, 1 gate failed, 2 usage or unreadable file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from fractions import Fraction

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    sys.stderr.write("Pillow missing: use the stack venv python (.venv/bin/python)\n")
    sys.exit(2)


def _open(path: str) -> Image.Image:
    try:
        im = Image.open(path)
        im.load()
        return im
    except (OSError, ValueError) as e:
        sys.stderr.write("cannot read %s: %s\n" % (path, e))
        sys.exit(2)


def _aspect_label(w: int, h: int) -> str:
    fr = Fraction(w, h).limit_denominator(32)
    return "%d:%d" % (fr.numerator, fr.denominator)


def info(path: str) -> dict:
    im = _open(path)
    w, h = im.size
    has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    out = {
        "path": path, "format": im.format, "mode": im.mode, "width": w, "height": h,
        "megapixels": round(w * h / 1e6, 2), "aspect": _aspect_label(w, h), "ratio": round(w / h, 4),
        "has_alpha_channel": has_alpha, "bytes": os.path.getsize(path),
    }
    if has_alpha:
        a = im.convert("RGBA").getchannel("A")
        hist = a.histogram()
        n = float(w * h)
        out["alpha_transparent_frac"] = round(hist[0] / n, 4)          # fully transparent
        out["alpha_partial_frac"] = round(sum(hist[1:255]) / n, 4)     # soft edges / fringes
        out["alpha_opaque_frac"] = round(hist[255] / n, 4)
        # An "RGBA" file that is fully opaque is not a cutout.
        out["alpha_effective"] = hist[255] < n
    with open(path, "rb") as fh:
        out["sha256_12"] = hashlib.sha256(fh.read()).hexdigest()[:12]
    return out


def _parse_aspect(s: str) -> float:
    if ":" in s:
        a, b = s.split(":", 1)
        return float(a) / float(b)
    return float(s)


def expect(a) -> int:
    d = info(a.file)
    fails = []
    if a.aspect:
        want = _parse_aspect(a.aspect)
        rel = abs(d["ratio"] - want) / want
        if rel > a.tol:
            fails.append("aspect %s (%.4f) differs from %s by %.1f%%" % (d["aspect"], d["ratio"], a.aspect, 100 * rel))
    if a.min_side and min(d["width"], d["height"]) < a.min_side:
        fails.append("short side %d < %d" % (min(d["width"], d["height"]), a.min_side))
    if a.alpha and not d.get("alpha_effective"):
        fails.append("no effective transparency (mode %s)" % d["mode"])
    if a.opaque and d.get("alpha_effective"):
        fails.append("has transparent pixels but opaque output was required")
    if a.max_mb and d["bytes"] > a.max_mb * 1e6:
        fails.append("file %.1f MB > %.1f MB" % (d["bytes"] / 1e6, a.max_mb))
    print(json.dumps({"file": a.file, "pass": not fails, "fails": fails, "info": d}, indent=2))
    return 1 if fails else 0


def _sidecar_path(img: str) -> str:
    # Same convention as the image router: "<file>.json" next to the file (e.g. a.png.json).
    return img + ".json"


def _coerce(v: str):
    try:
        return json.loads(v)
    except ValueError:
        return v


def sidecar(a) -> int:
    if not os.path.exists(a.file):
        sys.stderr.write("no such image %s\n" % a.file)
        return 2
    p = a.sidecar or _sidecar_path(a.file)
    data = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except ValueError:
                sys.stderr.write("existing sidecar %s is not JSON; refusing to overwrite\n" % p)
                return 2
    extra = {}
    if a.json_file:
        with open(a.json_file, encoding="utf-8") as fh:
            extra = json.load(fh)
    for kv in a.set or []:
        if "=" not in kv:
            sys.stderr.write("expected key=value, got %s\n" % kv)
            return 2
        k, v = kv.split("=", 1)
        extra[k] = _coerce(v)
    # Router-written keys win on conflict unless the agent namespaces its own under "agent".
    agent_block = dict(data.get("agent", {}))
    agent_block.update(extra)
    data["agent"] = agent_block
    data.setdefault("file", os.path.basename(a.file))
    data["check"] = info(a.file)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, p)
    print(p)
    return 0


def _checker(size, step=16):
    bg = Image.new("RGB", size, (235, 235, 235))
    d = ImageDraw.Draw(bg)
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            if (x // step + y // step) % 2:
                d.rectangle([x, y, x + step - 1, y + step - 1], fill=(200, 200, 200))
    return bg


def sheet(a) -> int:
    files = a.files
    cols = max(1, min(a.cols, len(files)))
    rows = math.ceil(len(files) / cols)
    cell, label_h = a.cell, 22
    out = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (255, 255, 255))
    d = ImageDraw.Draw(out)
    for i, f in enumerate(files):
        im = _open(f).convert("RGBA")
        im.thumbnail((cell, cell), Image.LANCZOS)
        # Letterbox stays white; the checkerboard sits only under the image, so it marks real alpha.
        tile = Image.new("RGB", (cell, cell), (255, 255, 255))
        ox, oy = (cell - im.width) // 2, (cell - im.height) // 2
        tile.paste(_checker(im.size), (ox, oy))
        tile.paste(im, (ox, oy), im)
        x, y = (i % cols) * cell, (i // cols) * (cell + label_h)
        out.paste(tile, (x, y + label_h))
        label = "%d %s" % (i + 1, os.path.basename(f))
        d.text((x + 4, y + 4), label[: cell // 7], fill=(0, 0, 0))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out.save(a.out)
    print(a.out)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("info")
    pi.add_argument("files", nargs="+")
    pe = sub.add_parser("expect")
    pe.add_argument("file")
    pe.add_argument("--aspect")
    pe.add_argument("--tol", type=float, default=0.02)
    pe.add_argument("--min-side", type=int, default=0)
    pe.add_argument("--alpha", action="store_true")
    pe.add_argument("--opaque", action="store_true")
    pe.add_argument("--max-mb", type=float, default=0)
    ps = sub.add_parser("sidecar")
    ps.add_argument("file")
    ps.add_argument("--set", action="append")
    ps.add_argument("--json-file")
    ps.add_argument("--sidecar")
    pc = sub.add_parser("sheet")
    pc.add_argument("out")
    pc.add_argument("files", nargs="+")
    pc.add_argument("--cols", type=int, default=3)
    pc.add_argument("--cell", type=int, default=512)
    a = p.parse_args(argv)
    if a.cmd == "info":
        print(json.dumps([info(f) for f in a.files], indent=2))
        return 0
    if a.cmd == "expect":
        return expect(a)
    if a.cmd == "sidecar":
        return sidecar(a)
    return sheet(a)


if __name__ == "__main__":
    sys.exit(main())
