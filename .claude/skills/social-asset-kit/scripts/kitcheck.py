#!/usr/bin/env python3
"""Plan, derive, check and package a multi-placement social / ad kit from one master image.

`plan` is stdlib-only; everything else needs Pillow (stack venv):
    PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python

Kit file (JSON):
  {"campaign": "orbit", "message": "launch", "version": 1,
   "master": {"file": "master.png", "w": 3840, "h": 2160, "focus": [x0, y0, x1, y1]},
   "copy": {"headline": "...", "sub": "...", "cta": "..."}, "alt": "...",
   "variants": {"b": {"variable": "headline", "headline": "..."}},
   "placements": [{"name": "feed", "w": 1080, "h": 1350, "fill": 0.6, "anchor": [0.5, 0.62],
                   "safe": {"top": 0.0, "bottom": 0.0, "left": 0.03, "right": 0.03}}]}
  fill    share of the placement's safe width the focal box spans (omit: largest crop that fits)
  fill_h  same for height; when both are given the larger window wins
  anchor  where the focal-box centre sits inside the safe box (0..1, 0..1); default centre
  safe    keep-out insets as fractions of the placement (platform UI, grid crops, ad frames)

Subcommands
  plan KIT.json            per placement: crop window in master px, scale, outpaint pads and new-area
                           share, safe box in master px, focus check, free copy bands (placement px);
                           then the intersection of all safe boxes. Exit 1 if a focal box is unsafe.
  derive KIT.json OUTDIR [--master FILE] [--variant b]
                           crop + Lanczos resize every crop placement to
                           <campaign>_<message>_<placement>_<W>x<H>_v<n>.png; for outpaint placements
                           write <...>_prepad.png and print the pad -> outpaint -> resize steps
  resize IMG OUT WxH       exact Lanczos resize; refuses an aspect change above 1%
  contrast IMG --box x0,y0,x1,y1 --text '#FFFFFF' [--blur 1.0] [--large] [--target 4.5]
                           WCAG ratio of the text colour against the pixels under the box: worst point
                           (after a light blur), 5th percentile, mean. Exit 1 below target.
  scrim IMG OUT --box x0,y0,x1,y1 --text '#FFFFFF' [--target 4.5] [--margin 0.3]
        [--color '#000000'] [--fade 0.6] [--side auto|top|bottom]
                           smallest scrim alpha that lifts the worst point to target + margin; flat from
                           the box to the image edge on --side, linear fade over fade x box height; applied
  export IMG OUT [--max-kb 150] [--quality 88] [--min-quality 60] [--bg '#FFFFFF'] [--subsampling N]
                           sRGB, metadata dropped, format from the extension (.jpg .webp .avif .png);
                           steps quality down until the file is under --max-kb (kB = 1000 bytes)
  manifest KIT.json OUT.(json|csv) FILE...
                           one row per file: name fields, size, bytes, copy, alt, variant + variable,
                           model, seed, references (from <file>.json, else the master's sidecar)

Exit codes: 0 ok, 1 check failed, 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys

NAME_RE = re.compile(r"^(?P<campaign>[^_]+)_(?P<message>[^_-]+)(?:-(?P<variant>[^_]+))?_(?P<placement>[^_]+)_"
                     r"(?P<w>\d+)x(?P<h>\d+)_v(?P<version>\d+)\.(?P<ext>[A-Za-z0-9]+)$")


def die(msg: str, code: int = 2) -> int:
    sys.stderr.write(msg + "\n")
    return code


def load_kit(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        kit = json.load(fh)
    for key in ("campaign", "message", "master", "placements"):
        if key not in kit:
            raise SystemExit("kit is missing %r" % key)
    return kit


def r2(x: float) -> float:
    return round(x, 2)


# ------------------------------------------------------------------ planning
def window(master: dict, pl: dict) -> dict:
    W, H = master["w"], master["h"]
    fx0, fy0, fx1, fy1 = master["focus"]
    fw, fh = fx1 - fx0, fy1 - fy0
    w, h = pl["w"], pl["h"]
    s = pl.get("safe", {})
    st, sb, sl, sr = (s.get(k, 0.0) for k in ("top", "bottom", "left", "right"))
    a = w / h
    cands = []
    if "fill" in pl:
        cands.append(fw / (pl["fill"] * (1 - sl - sr)))           # window width from width share
    if "fill_h" in pl:
        cands.append(fh / (pl["fill_h"] * (1 - st - sb)) * a)     # window width from height share
    if cands:
        ww = max(cands)
    else:
        ww = W if W / H <= a else H * a                            # largest crop that fits
    wh = ww / a
    ax, ay = pl.get("anchor", [0.5, 0.5])
    # focal centre at the anchor inside the safe box
    cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
    sx0, sy0 = ww * sl, wh * st
    sw, sh = ww * (1 - sl - sr), wh * (1 - st - sb)
    x0, y0 = cx - (sx0 + ax * sw), cy - (sy0 + ay * sh)
    # clamp inside the master when the window fits; otherwise it needs outpainting
    if ww <= W:
        x0 = min(max(x0, 0.0), W - ww)
    if wh <= H:
        y0 = min(max(y0, 0.0), H - wh)
    x1, y1 = x0 + ww, y0 + wh
    pads = {"left": max(0.0, -x0), "right": max(0.0, x1 - W), "top": max(0.0, -y0), "bottom": max(0.0, y1 - H)}
    inter = max(0.0, min(x1, W) - max(x0, 0.0)) * max(0.0, min(y1, H) - max(y0, 0.0))
    new_share = 1 - inter / (ww * wh)
    k = w / ww                                                     # master px -> placement px
    safe_m = [x0 + sx0, y0 + sy0, x0 + sx0 + sw, y0 + sy0 + sh]
    focus_ok = fx0 >= safe_m[0] - 0.5 and fy0 >= safe_m[1] - 0.5 and fx1 <= safe_m[2] + 0.5 and fy1 <= safe_m[3] + 0.5
    fp = [(fx0 - x0) * k, (fy0 - y0) * k, (fx1 - x0) * k, (fy1 - y0) * k]   # focus in placement px
    sp = [w * sl, h * st, w * (1 - sr), h * (1 - sb)]
    bands = {"top": [sp[0], sp[1], sp[2], fp[1]], "bottom": [sp[0], fp[3], sp[2], sp[3]],
             "left": [sp[0], sp[1], fp[0], sp[3]], "right": [fp[2], sp[1], sp[2], sp[3]]}
    bands = {n: [round(v) for v in b] for n, b in bands.items() if b[2] - b[0] >= 1 and b[3] - b[1] >= 1}
    return {"name": pl["name"], "size": [w, h],
            "method": "outpaint" if any(v > 0.5 for v in pads.values()) else ("resize" if abs(ww - W) < 1 and abs(wh - H) < 1 else "crop"),
            "window": [r2(x0), r2(y0), r2(x1), r2(y1)], "scale": round(k, 4),
            "pads_master_px": {n: round(v) for n, v in pads.items()}, "new_area_share": round(new_share, 3),
            "safe_master": [r2(v) for v in safe_m], "focus_ok": focus_ok,
            "focus_px": [round(v) for v in fp], "copy_bands_px": bands}


def cmd_plan(a) -> int:
    kit = load_kit(a.kit)
    rows = [window(kit["master"], pl) for pl in kit["placements"]]
    W, H = kit["master"]["w"], kit["master"]["h"]
    ix0 = max([0.0] + [r["safe_master"][0] for r in rows]); iy0 = max([0.0] + [r["safe_master"][1] for r in rows])
    ix1 = min([float(W)] + [r["safe_master"][2] for r in rows]); iy1 = min([float(H)] + [r["safe_master"][3] for r in rows])
    fx0, fy0, fx1, fy1 = kit["master"]["focus"]
    inside = ix0 <= fx0 and iy0 <= fy0 and fx1 <= ix1 and fy1 <= iy1
    warn = [r["name"] + ": outpaint adds %.0f%% new area" % (100 * r["new_area_share"]) for r in rows
            if r["new_area_share"] > 0.4]
    out = {"placements": rows,
           "safe_in_all_master_px": [r2(ix0), r2(iy0), r2(ix1), r2(iy1)] if ix1 > ix0 and iy1 > iy0 else None,
           "focus_inside_all": inside, "warnings": warn}
    print(json.dumps(out, indent=2))
    return 0 if all(r["focus_ok"] for r in rows) else 1


# ------------------------------------------------------------------ pixels
def _pil():
    try:
        from PIL import Image, ImageFilter  # noqa: F401
        return Image, ImageFilter
    except ImportError:
        raise SystemExit("Pillow missing: run with the stack venv python")


def fname(kit: dict, pl: dict, suffix: str = "", ext: str = "png", variant: str = "") -> str:
    msg = kit["message"] + ("-" + variant if variant else "")
    return "%s_%s_%s_%dx%d_v%d%s.%s" % (kit["campaign"], msg, pl["name"], pl["w"], pl["h"],
                                        kit.get("version", 1), suffix, ext)


def cmd_derive(a) -> int:
    Image, _ = _pil()
    kit = load_kit(a.kit)
    src = a.master or kit["master"].get("file")
    try:
        im = Image.open(src)
        im.load()
    except (OSError, TypeError) as e:
        return die("cannot read master %s: %s" % (src, e))
    if list(im.size) != [kit["master"]["w"], kit["master"]["h"]]:
        return die("master is %dx%d, kit says %dx%d" % (*im.size, kit["master"]["w"], kit["master"]["h"]))
    os.makedirs(a.outdir, exist_ok=True)
    report = []
    for pl in kit["placements"]:
        r = window(kit["master"], pl)
        x0, y0, x1, y1 = r["window"]
        if r["method"] != "outpaint":
            out = os.path.join(a.outdir, fname(kit, pl, variant=a.variant))
            im.resize((pl["w"], pl["h"]), Image.LANCZOS, box=(x0, y0, x1, y1)).save(out)
            report.append({"placement": pl["name"], "file": out, "method": r["method"]})
            continue
        box = (max(0, round(x0)), max(0, round(y0)), min(im.width, round(x1)), min(im.height, round(y1)))
        pre = os.path.join(a.outdir, fname(kit, pl, "_prepad", variant=a.variant))
        im.crop(box).save(pre)
        p = r["pads_master_px"]
        padded, mask = pre.replace("_prepad.png", "_padded.png"), pre.replace("_prepad.png", "_padmask.png")
        report.append({"placement": pl["name"], "file": pre, "method": "outpaint",
                       "new_area_share": r["new_area_share"],
                       "next": ['masktool pad %s %s %s --left %d --right %d --top %d --bottom %d --overlap 24'
                                % (pre, padded, mask, p["left"], p["right"], p["top"], p["bottom"]),
                                "image_edit {image: %s, mask: %s, preserve_unmasked: true, instruction: "
                                "'Extend the background naturally into the masked area ...; add no new objects'}"
                                % (padded, mask),
                                "kitcheck resize <edited> %s %dx%d" % (os.path.join(a.outdir, fname(kit, pl, variant=a.variant)),
                                                                     pl["w"], pl["h"])]})
    print(json.dumps(report, indent=2))
    return 0


def cmd_resize(a) -> int:
    Image, _ = _pil()
    try:
        w, h = (int(v) for v in a.size.lower().split("x"))
        im = Image.open(a.img)
        im.load()
    except (OSError, ValueError) as e:
        return die("resize: %s" % e)
    if abs((im.width / im.height) / (w / h) - 1) > 0.01:
        return die("aspect %.4f -> %.4f differs by more than 1%%: crop or outpaint first"
                   % (im.width / im.height, w / h), 1)
    im.resize((w, h), Image.LANCZOS).save(a.out)
    print(json.dumps({"out": a.out, "size": [w, h]}))
    return 0


def _lut():
    return [(c / 255 / 12.92) if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in range(256)]


LIN = _lut()


def hex_rgb(h: str):
    h = h.lstrip("#")
    if len(h) != 6:
        raise SystemExit("colour must be #RRGGBB")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(rgb) -> float:
    return 0.2126 * LIN[rgb[0]] + 0.7152 * LIN[rgb[1]] + 0.0722 * LIN[rgb[2]]


def ratio(l1: float, l2: float) -> float:
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def parse_box(s: str):
    try:
        x0, y0, x1, y1 = (int(round(float(v))) for v in s.split(","))
    except ValueError:
        raise SystemExit("--box must be x0,y0,x1,y1")
    return x0, y0, x1, y1


def measure(region, text_l: float):
    """region: RGB image of the pixels under the text box. Returns (worst, p5, mean, worst_xy, worst_rgb)."""
    px = list(getattr(region, "get_flattened_data", region.getdata)())   # getdata is deprecated in Pillow 13
    rs = [ratio(text_l, lum(p)) for p in px]
    i = min(range(len(rs)), key=rs.__getitem__)
    srt = sorted(rs)
    return srt[0], srt[int(0.05 * (len(srt) - 1))], sum(rs) / len(rs), (i % region.width, i // region.width), px[i]


def _region(img, box, blur, ImageFilter):
    reg = img.crop(box)
    return reg.filter(ImageFilter.GaussianBlur(blur)) if blur > 0 else reg


def cmd_contrast(a) -> int:
    Image, ImageFilter = _pil()
    try:
        img = Image.open(a.img).convert("RGB")
    except OSError as e:
        return die("cannot read %s: %s" % (a.img, e))
    box = parse_box(a.box)
    target = a.target or (3.0 if a.large else 4.5)
    tl = lum(hex_rgb(a.text))
    worst, p5, mean, (wx, wy), wrgb = measure(_region(img, box, a.blur, ImageFilter), tl)
    out = {"image": a.img, "box": box, "text": a.text, "target": target, "worst": round(worst, 2),
           "p5": round(p5, 2), "mean": round(mean, 2), "worst_at": [box[0] + wx, box[1] + wy],
           "worst_rgb": "#%02X%02X%02X" % wrgb, "pass": worst >= target}
    print(json.dumps(out, indent=2))
    return 0 if out["pass"] else 1


def cmd_scrim(a) -> int:
    Image, ImageFilter = _pil()
    try:
        img = Image.open(a.img).convert("RGB")
    except OSError as e:
        return die("cannot read %s: %s" % (a.img, e))
    box = parse_box(a.box)
    goal = a.target + a.margin
    tl, sc = lum(hex_rgb(a.text)), hex_rgb(a.color)
    raw = img.crop(box)
    solid = Image.new("RGB", raw.size, sc)
    before = measure(_region(img, box, a.blur, ImageFilter), tl)[0]

    def worst_at(level: int) -> float:
        # same integer compositing path as the final apply, then the same blur as the measurement
        mixed = Image.composite(solid, raw, Image.new("L", raw.size, level))
        return measure(mixed.filter(ImageFilter.GaussianBlur(a.blur)) if a.blur > 0 else mixed, tl)[0]

    if worst_at(255) < goal:
        return die("even an opaque %s scrim gives %.2f:1 < %.2f: change the scrim or text colour" %
                   (a.color, worst_at(255), goal), 1)
    lo, hi = 0, 255                                # smallest mask level whose worst point reaches goal
    if before >= goal:
        hi = 0
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if worst_at(mid) >= goal else (mid, hi)
    level = hi
    alpha = level / 255
    side = a.side
    if side == "auto":
        side = "bottom" if (box[1] + box[3]) / 2 >= img.height / 2 else "top"
    fade = max(1, round(a.fade * (box[3] - box[1])))
    mask = Image.new("L", img.size, 0)
    col = []
    for y in range(img.height):
        if side == "bottom":
            t = 1.0 if y >= box[1] else max(0.0, 1 - (box[1] - y) / fade)
        else:
            t = 1.0 if y <= box[3] else max(0.0, 1 - (y - box[3]) / fade)
        col.append(round(level * t))
    mask.putdata([v for v in col for _ in range(img.width)])
    out_img = Image.composite(Image.new("RGB", img.size, sc), img, mask)
    out_img.save(a.out)
    after = measure(_region(out_img, box, a.blur, ImageFilter), tl)[0]
    print(json.dumps({"out": a.out, "side": side, "scrim": a.color, "alpha": round(alpha, 3),
                      "fade_px": fade, "worst_before": round(before, 2), "worst_after": round(after, 2),
                      "goal": round(goal, 2), "pass": after >= a.target}, indent=2))
    return 0 if after >= a.target else 1


def cmd_export(a) -> int:
    Image, _ = _pil()
    try:
        im = Image.open(a.img)
        im.load()
    except OSError as e:
        return die("cannot read %s: %s" % (a.img, e))
    icc = im.info.get("icc_profile")
    if icc:
        from PIL import ImageCms
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        mode = "RGBA" if im.mode in ("RGBA", "LA", "PA") else "RGB"
        im = ImageCms.profileToProfile(im.convert(mode), src, ImageCms.createProfile("sRGB"), outputMode=mode)
    ext = os.path.splitext(a.out)[1].lower()
    fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".avif": "AVIF", ".png": "PNG"}.get(ext)
    if not fmt:
        return die("unsupported extension %s" % ext)
    has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    if fmt == "JPEG" or (has_alpha and a.flatten):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, hex_rgb(a.bg) + (255,))
        im = Image.alpha_composite(bg, rgba).convert("RGB")
    elif not has_alpha:
        im = im.convert("RGB")
    im.info = {}                                   # drop EXIF, XMP, ICC, text chunks
    cap = a.max_kb * 1000 if a.max_kb else None
    tried = []

    def encode(q):
        b = io.BytesIO()
        if fmt == "JPEG":
            kw = {"quality": q, "optimize": True, "progressive": True}
            if a.subsampling is not None:
                kw["subsampling"] = a.subsampling
            im.save(b, fmt, **kw)
        elif fmt == "WEBP":
            im.save(b, fmt, quality=q, method=6)
        elif fmt == "AVIF":
            im.save(b, fmt, quality=q)
        else:
            im.save(b, fmt, optimize=True)
        return b.getvalue()

    if fmt == "PNG":
        data = encode(None)
        tried.append([None, len(data)])
        if cap and len(data) > cap:
            im = im.convert("RGBA" if has_alpha else "RGB").quantize(256)
            data = encode(None)
            tried.append(["quantize256", len(data)])
    else:
        q = a.quality
        data = encode(q)
        tried.append([q, len(data)])
        while cap and len(data) > cap and q - 4 >= a.min_quality:
            q -= 4
            data = encode(q)
            tried.append([q, len(data)])
    with open(a.out, "wb") as fh:
        fh.write(data)
    ok = not cap or len(data) <= cap
    print(json.dumps({"out": a.out, "format": fmt, "size": list(im.size), "bytes": len(data),
                      "cap_bytes": cap, "pass": ok, "tried": tried}, indent=2))
    return 0 if ok else 1


def _sidecar(path: str):
    try:
        with open(path + ".json", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def cmd_manifest(a) -> int:
    Image, _ = _pil()
    kit = load_kit(a.kit)
    master_sc = _sidecar(kit["master"].get("file", "")) or {}
    rows = []
    for f in a.files:
        m = NAME_RE.match(os.path.basename(f))
        if not m:
            return die("%s does not follow <campaign>_<message>[-variant]_<placement>_<W>x<H>_v<n>.<ext>" % f)
        g = m.groupdict()
        try:
            with Image.open(f) as im:
                size = im.size
                fmt = im.format
        except OSError as e:
            return die("cannot read %s: %s" % (f, e))
        if list(size) != [int(g["w"]), int(g["h"])]:
            return die("%s is %dx%d, its name says %sx%s" % (f, size[0], size[1], g["w"], g["h"]), 1)
        sc = _sidecar(f) or master_sc
        agent = sc.get("agent", {}) if isinstance(sc, dict) else {}
        copy = dict(kit.get("copy", {}))
        var = kit.get("variants", {}).get(g["variant"] or "", {})
        copy.update({k: v for k, v in var.items() if k != "variable"})
        pl = next((p for p in kit["placements"] if p["name"] == g["placement"]), {})
        rows.append({"file": os.path.basename(f), "campaign": g["campaign"], "message": g["message"],
                     "variant": g["variant"] or "", "variable": var.get("variable", ""),
                     "placement": g["placement"], "width": size[0], "height": size[1], "format": fmt,
                     "bytes": os.path.getsize(f), "headline": copy.get("headline", ""), "sub": copy.get("sub", ""),
                     "cta": copy.get("cta", ""), "alt": pl.get("alt", kit.get("alt", "")),
                     "model": sc.get("model", ""), "seed": (sc.get("params") or {}).get("seed", agent.get("seed", "")),
                     "references": json.dumps(agent.get("references", sc.get("inputs", [])), ensure_ascii=False),
                     "derived_from": "" if _sidecar(f) else kit["master"].get("file", "")})
    if a.out.endswith(".csv"):
        with open(a.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["file"])
            w.writeheader()
            w.writerows(rows)
    else:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"campaign": kit["campaign"], "assets": rows}, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    print(json.dumps({"out": a.out, "rows": len(rows)}))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("plan"); x.add_argument("kit"); x.set_defaults(fn=cmd_plan)
    x = s.add_parser("derive"); x.add_argument("kit"); x.add_argument("outdir"); x.add_argument("--master")
    x.add_argument("--variant", default="")
    x.set_defaults(fn=cmd_derive)
    x = s.add_parser("resize"); x.add_argument("img"); x.add_argument("out"); x.add_argument("size")
    x.set_defaults(fn=cmd_resize)
    for name, fn in (("contrast", cmd_contrast), ("scrim", cmd_scrim)):
        x = s.add_parser(name); x.add_argument("img")
        if name == "scrim":
            x.add_argument("out"); x.add_argument("--margin", type=float, default=0.3)
            x.add_argument("--color", default="#000000"); x.add_argument("--fade", type=float, default=0.6)
            x.add_argument("--side", choices=["auto", "top", "bottom"], default="auto")
            x.add_argument("--target", type=float, default=4.5)
        else:
            x.add_argument("--target", type=float); x.add_argument("--large", action="store_true")
        x.add_argument("--box", required=True); x.add_argument("--text", required=True)
        x.add_argument("--blur", type=float, default=1.0); x.set_defaults(fn=fn)
    x = s.add_parser("export"); x.add_argument("img"); x.add_argument("out")
    x.add_argument("--max-kb", type=float); x.add_argument("--quality", type=int, default=88)
    x.add_argument("--min-quality", type=int, default=60); x.add_argument("--bg", default="#FFFFFF")
    x.add_argument("--flatten", action="store_true"); x.add_argument("--subsampling", type=int, choices=[0, 1, 2])
    x.set_defaults(fn=cmd_export)
    x = s.add_parser("manifest"); x.add_argument("kit"); x.add_argument("out"); x.add_argument("files", nargs="+")
    x.set_defaults(fn=cmd_manifest)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
