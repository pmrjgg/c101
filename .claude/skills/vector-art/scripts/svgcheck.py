#!/usr/bin/env python3
"""Validate, inspect and clean SVG files. Stdlib only (Python 3.9+), deterministic.

Subcommands
  check FILE... [--budget icon|logo|illustration] [--json]
        well-formedness, root <svg>, viewBox, element and path counts, coordinate precision,
        palette, gradients/filters, embedded rasters, unsafe content (script, foreignObject,
        on* handlers, external or javascript: hrefs), duplicate ids, dangling #refs, size.
        Exit 1 if any ERROR.
  palette FILE                              color usage histogram (normalised hex)
  remap FILE OUT [--map '#aaa=#000,#bbb=#111'] [--merge DIST] [--max-colors K]
        palette reduction: explicit map, merge colors closer than DIST (RGB euclidean, 0..441)
        into the more used one, and/or keep only the K most used colors (others -> nearest kept)
  currentcolor FILE OUT                     every solid fill/stroke -> currentColor (mono icons)
  prefix-ids FILE OUT --prefix P            rename ids to P-id and update url(#..)/href refs
  sanitize FILE OUT                         drop script, foreignObject, metadata, editor
                                            namespaces, on* attributes, external hrefs, DTDs
  precision FILE OUT [--digits 2]           round numbers in geometry attributes
  fit FILE OUT --size 24 [--pad 0]          rescale content into viewBox "0 0 S S" (centred)

Files containing <!ENTITY declarations are refused (entity-expansion attacks).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zlib
from collections import Counter

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
EDITOR_NS = {
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "sketch": "http://www.bohemiancoding.com/sketch/ns",
    "serif": "http://www.serif.com/",
    "figma": "https://www.figma.com/figma/ns",
}
OTHER_NS = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "cc": "http://creativecommons.org/ns#",
            "dc": "http://purl.org/dc/elements/1.1/"}
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)
for _p, _u in list(EDITOR_NS.items()) + list(OTHER_NS.items()):
    ET.register_namespace(_p, _u)

COLOR_PROPS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color", "color")
GEOM_ATTRS = ("d", "points", "transform", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
              "width", "height", "stroke-width", "viewBox", "offset")
BUDGETS = {  # bytes, paths, max decimals
    "icon": (4_000, 40, 2),
    "logo": (20_000, 150, 3),
    "illustration": (150_000, 2_500, 3),
}
NUM_RE = re.compile(r"-?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][-+]?\d+)?")
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+\s*)?\)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if isinstance(tag, str) and tag.startswith("{") else ""


def load(path: str):
    with open(path, "rb") as fh:
        raw = fh.read()
    if b"<!ENTITY" in raw:
        raise ValueError("refusing file with <!ENTITY> declarations")
    return raw, ET.ElementTree(ET.fromstring(raw))


def save(tree: ET.ElementTree, out: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tree.write(out, encoding="utf-8", xml_declaration=False)
    print(out)


def norm_color(v: str):
    v = v.strip()
    lv = v.lower()
    if not lv or lv in ("none", "currentcolor", "inherit", "transparent") or lv.startswith("url("):
        return None
    m = HEX_RE.fullmatch(v)
    if m:
        h = lv[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h
    m = RGB_RE.fullmatch(lv)
    if m:
        return "#%02x%02x%02x" % tuple(min(255, int(x)) for x in m.groups())
    return lv  # named color


def _style_items(style: str):
    out = []
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out.append((k.strip(), v.strip()))
    return out


def _style_join(items) -> str:
    return ";".join("%s:%s" % kv for kv in items)


def iter_colors(root):
    for el in root.iter():
        for p in COLOR_PROPS:
            if p in el.attrib:
                c = norm_color(el.attrib[p])
                if c:
                    yield el, "attr", p, c
        if "style" in el.attrib:
            for k, v in _style_items(el.attrib["style"]):
                if k in COLOR_PROPS:
                    c = norm_color(v)
                    if c:
                        yield el, "style", k, c
        if _local(el.tag) == "style" and el.text:
            for m in HEX_RE.finditer(el.text):
                yield el, "css", "", norm_color(m.group(0))


def _href(el):
    return el.attrib.get("href") or el.attrib.get("{%s}href" % XLINK_NS)


def check(path: str, budget=None) -> dict:
    rep = {"file": path, "errors": [], "warnings": []}
    try:
        raw, tree = load(path)
    except (ValueError, ET.ParseError, OSError) as e:
        rep["errors"].append("not well-formed or unsafe: %s" % e)
        return rep
    root = tree.getroot()
    if _local(root.tag) != "svg" or _ns(root.tag) != SVG_NS:
        rep["errors"].append("root is %r, expected <svg> in the SVG namespace" % root.tag)
    rep["bytes"] = len(raw)
    rep["gzip_bytes"] = len(zlib.compress(raw, 9))
    vb = root.attrib.get("viewBox")
    if vb:
        try:
            nums = [float(x) for x in re.split(r"[\s,]+", vb.strip())]
            assert len(nums) == 4 and nums[2] > 0 and nums[3] > 0
            rep["viewBox"] = nums
        except (ValueError, AssertionError):
            rep["errors"].append("invalid viewBox %r" % vb)
    else:
        rep["warnings"].append("no viewBox: the SVG will not scale; add viewBox='0 0 W H'")
    rep["width"], rep["height"] = root.attrib.get("width"), root.attrib.get("height")
    tags = Counter(_local(el.tag) for el in root.iter())
    rep["elements"] = sum(tags.values())
    rep["tags"] = dict(tags.most_common())
    paths = [el for el in root.iter() if _local(el.tag) == "path"]
    rep["paths"] = len(paths)
    rep["path_data_chars"] = sum(len(el.attrib.get("d", "")) for el in paths)
    maxdec = 0
    for el in root.iter():
        for a in GEOM_ATTRS:
            v = el.attrib.get(a)
            if v:
                for m in NUM_RE.finditer(v):
                    t = m.group(0).split("e")[0].split("E")[0]
                    if "." in t:
                        maxdec = max(maxdec, len(t.split(".")[1]))
    rep["max_decimals"] = maxdec
    pal = Counter(c for _, _, _, c in iter_colors(root))
    rep["colors"] = dict(pal.most_common())
    rep["n_colors"] = len(pal)
    rep["gradients"] = tags.get("linearGradient", 0) + tags.get("radialGradient", 0)
    rep["filters"] = tags.get("filter", 0)
    # Safety.
    for el in root.iter():
        ln = _local(el.tag)
        if ln in ("script", "foreignObject"):
            rep["errors"].append("unsafe element <%s>" % ln)
        if ln in ("animate", "set") and el.attrib.get("attributeName", "").split(":")[-1] == "href":
            rep["errors"].append("<%s> animates href (script-injection vector)" % ln)
        for k, v in el.attrib.items():
            lk = _local(k)
            if lk.lower().startswith("on"):
                rep["errors"].append("event handler attribute %s on <%s>" % (lk, ln))
            if lk == "href":
                vv = v.strip().lower()
                if vv.startswith("javascript:"):
                    rep["errors"].append("javascript: href on <%s>" % ln)
                elif vv.startswith(("http:", "https:", "//", "file:")):
                    rep["errors"].append("external reference %s on <%s>" % (v[:60], ln))
        if ln == "image":
            h = _href(el) or ""
            rep["warnings"].append("embedded raster <image> (%s): not a true vector" % ("data URI" if h.startswith("data:") else h[:40]))
        if ln == "style" and el.text and ("@import" in el.text or re.search(r"url\(\s*['\"]?https?:", el.text)):
            rep["errors"].append("<style> loads external resources")
    # Ids and references.
    ids = Counter(el.attrib["id"] for el in root.iter() if "id" in el.attrib)
    dup = [i for i, c in ids.items() if c > 1]
    if dup:
        rep["errors"].append("duplicate ids: %s" % ", ".join(dup[:10]))
    refs = set()
    for el in root.iter():
        for k, v in el.attrib.items():
            refs.update(re.findall(r"url\(\s*#([^)\s]+)\s*\)", v))
            if _local(k) == "href" and v.startswith("#"):
                refs.add(v[1:])
    missing = sorted(r for r in refs if r not in ids)
    if missing:
        rep["warnings"].append("references to missing ids: %s" % ", ".join(missing[:10]))
    rep["ids"] = len(ids)
    if any(_ns(el.tag) in EDITOR_NS.values() for el in root.iter()) or \
            any(_ns(k) in EDITOR_NS.values() for el in root.iter() for k in el.attrib):
        rep["warnings"].append("editor metadata present (inkscape/sodipodi/sketch/...): run sanitize")
    if b"<!DOCTYPE" in raw:
        rep["warnings"].append("DOCTYPE present: remove it")
    if budget:
        mb, mp, md = BUDGETS[budget]
        if rep["bytes"] > mb:
            rep["warnings"].append("%d bytes > %s budget %d" % (rep["bytes"], budget, mb))
        if rep["paths"] > mp:
            rep["warnings"].append("%d paths > %s budget %d" % (rep["paths"], budget, mp))
        if maxdec > md:
            rep["warnings"].append("%d decimals > %s budget %d: run precision or svg_optimize" % (maxdec, budget, md))
    return rep


def _hex_rgb(h: str):
    if not (h.startswith("#") and len(h) in (7, 9)):
        return None
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _apply_color_map(root, cmap) -> int:
    n = 0
    for el in root.iter():
        for p in COLOR_PROPS:
            if p in el.attrib:
                c = norm_color(el.attrib[p])
                if c in cmap:
                    el.attrib[p] = cmap[c]
                    n += 1
        if "style" in el.attrib:
            items = []
            for k, v in _style_items(el.attrib["style"]):
                c = norm_color(v) if k in COLOR_PROPS else None
                if c in cmap:
                    v = cmap[c]
                    n += 1
                items.append((k, v))
            el.attrib["style"] = _style_join(items)
        if _local(el.tag) == "style" and el.text:
            def sub(m):
                c = norm_color(m.group(0))
                return cmap.get(c, m.group(0))
            el.text = HEX_RE.sub(sub, el.text)
    return n


def cmd_remap(a) -> int:
    _, tree = load(a.file)
    root = tree.getroot()
    pal = Counter(c for _, _, _, c in iter_colors(root))
    cmap = {}
    if a.map:
        for pair in a.map.split(","):
            src, dst = pair.split("=", 1)
            cmap[norm_color(src)] = dst.strip()
    hexes = [c for c, _ in pal.most_common() if _hex_rgb(c)]
    if a.merge:
        kept = []
        for c in hexes:  # most used first
            near = [k for k in kept if _dist(_hex_rgb(c), _hex_rgb(k)) < a.merge]
            if near:
                cmap.setdefault(c, near[0])
            else:
                kept.append(c)
        hexes = kept
    if a.max_colors and len(hexes) > a.max_colors:
        kept = hexes[: a.max_colors]
        for c in hexes[a.max_colors:]:
            cmap.setdefault(c, min(kept, key=lambda k: _dist(_hex_rgb(c), _hex_rgb(k))))
    n = _apply_color_map(root, cmap)
    sys.stderr.write("remapped %d color uses; map: %s\n" % (n, json.dumps(cmap)))
    save(tree, a.out)
    return 0


def cmd_currentcolor(a) -> int:
    _, tree = load(a.file)
    root = tree.getroot()
    pal = Counter(c for _, _, _, c in iter_colors(root))
    n = _apply_color_map(root, {c: "currentColor" for c in pal})
    sys.stderr.write("replaced %d color uses with currentColor\n" % n)
    save(tree, a.out)
    return 0


def cmd_prefix_ids(a) -> int:
    _, tree = load(a.file)
    root = tree.getroot()
    ids = {el.attrib["id"] for el in root.iter() if "id" in el.attrib}
    ren = {i: "%s-%s" % (a.prefix, i) for i in ids}
    for el in root.iter():
        if "id" in el.attrib:
            el.attrib["id"] = ren[el.attrib["id"]]
        for k, v in list(el.attrib.items()):
            nv = re.sub(r"url\(\s*#([^)\s]+)\s*\)", lambda m: "url(#%s)" % ren.get(m.group(1), m.group(1)), v)
            if _local(k) == "href" and v.startswith("#"):
                nv = "#" + ren.get(v[1:], v[1:])
            el.attrib[k] = nv
        if _local(el.tag) == "style" and el.text:
            el.text = re.sub(r"#([A-Za-z_][\w.-]*)", lambda m: "#" + ren[m.group(1)] if m.group(1) in ren else m.group(0), el.text)
    save(tree, a.out)
    return 0


def cmd_sanitize(a) -> int:
    _, tree = load(a.file)
    root = tree.getroot()
    removed = Counter()
    editor = set(EDITOR_NS.values())

    def walk(parent):
        for ch in list(parent):
            ln, ns = _local(ch.tag), _ns(ch.tag)
            animates_href = ln in ("animate", "set") and ch.attrib.get("attributeName", "").split(":")[-1] == "href"
            if not isinstance(ch.tag, str) or ln in ("script", "foreignObject", "metadata") or ns in editor \
                    or animates_href:
                parent.remove(ch)
                removed[ln or "comment"] += 1
                continue
            for k in list(ch.attrib):
                lk, v = _local(k), ch.attrib[k].strip().lower()
                if lk.lower().startswith("on") or _ns(k) in editor or \
                        (lk == "href" and (v.startswith(("javascript:", "http:", "https:", "//", "file:")))):
                    del ch.attrib[k]
                    removed["@" + lk] += 1
            walk(ch)

    for k in list(root.attrib):
        if _ns(k) in editor or _local(k).lower().startswith("on"):
            del root.attrib[k]
            removed["@" + _local(k)] += 1
    walk(root)
    sys.stderr.write("removed: %s\n" % json.dumps(dict(removed)))
    save(tree, a.out)
    return 0


def cmd_precision(a) -> int:
    _, tree = load(a.file)
    fmt = "%%.%df" % a.digits

    def rnd(m):
        s = fmt % float(m.group(0))
        s = s.rstrip("0").rstrip(".") if "." in s else s
        return "0" if s in ("-0", "") else s

    for el in tree.getroot().iter():
        for k in GEOM_ATTRS:
            if k in el.attrib:
                el.attrib[k] = NUM_RE.sub(rnd, el.attrib[k])
        if "style" in el.attrib:
            el.attrib["style"] = _style_join(
                (k, NUM_RE.sub(rnd, v) if k in GEOM_ATTRS else v) for k, v in _style_items(el.attrib["style"]))
    save(tree, a.out)
    return 0


def cmd_fit(a) -> int:
    _, tree = load(a.file)
    root = tree.getroot()
    vb = root.attrib.get("viewBox")
    if vb:
        mx, my, w, h = [float(x) for x in re.split(r"[\s,]+", vb.strip())]
    else:
        try:
            mx, my = 0.0, 0.0
            w = float(re.sub(r"[a-z%]+$", "", root.attrib["width"]))
            h = float(re.sub(r"[a-z%]+$", "", root.attrib["height"]))
        except (KeyError, ValueError):
            sys.stderr.write("no viewBox and no numeric width/height: cannot fit\n")
            return 2
    S, pad = float(a.size), float(a.pad)
    inner = S - 2 * pad
    s = min(inner / w, inner / h)
    tx = pad + (inner - w * s) / 2 - mx * s
    ty = pad + (inner - h * s) / 2 - my * s
    g = ET.Element("{%s}g" % SVG_NS, {"transform": "translate(%s %s) scale(%s)" % (
        round(tx, 4), round(ty, 4), round(s, 6))})
    keep_top = ("defs", "title", "desc", "style")
    for ch in list(root):
        if _local(ch.tag) not in keep_top:
            root.remove(ch)
            g.append(ch)
    root.append(g)
    root.attrib["viewBox"] = "0 0 %g %g" % (S, S)
    root.attrib["width"], root.attrib["height"] = "%g" % S, "%g" % S
    save(tree, a.out)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("check"); x.add_argument("files", nargs="+")
    x.add_argument("--budget", choices=sorted(BUDGETS)); x.add_argument("--json", action="store_true")
    x = s.add_parser("palette"); x.add_argument("file")
    x = s.add_parser("remap"); x.add_argument("file"); x.add_argument("out"); x.add_argument("--map")
    x.add_argument("--merge", type=float); x.add_argument("--max-colors", type=int)
    x = s.add_parser("currentcolor"); x.add_argument("file"); x.add_argument("out")
    x = s.add_parser("prefix-ids"); x.add_argument("file"); x.add_argument("out"); x.add_argument("--prefix", required=True)
    x = s.add_parser("sanitize"); x.add_argument("file"); x.add_argument("out")
    x = s.add_parser("precision"); x.add_argument("file"); x.add_argument("out"); x.add_argument("--digits", type=int, default=2)
    x = s.add_parser("fit"); x.add_argument("file"); x.add_argument("out"); x.add_argument("--size", type=float, required=True)
    x.add_argument("--pad", type=float, default=0.0)
    a = p.parse_args(argv)
    try:
        if a.cmd == "check":
            reps = [check(f, a.budget) for f in a.files]
            if a.json:
                print(json.dumps(reps, indent=2))
            else:
                for r in reps:
                    print("%s: %s, %s paths, %s colors, %s bytes, max %s decimals" % (
                        r["file"], "ERROR" if r["errors"] else "ok", r.get("paths", "?"), r.get("n_colors", "?"),
                        r.get("bytes", "?"), r.get("max_decimals", "?")))
                    for e in r["errors"]:
                        print("  ERROR " + e)
                    for w in r["warnings"]:
                        print("  warn  " + w)
            return 1 if any(r["errors"] for r in reps) else 0
        if a.cmd == "palette":
            _, tree = load(a.file)
            print(json.dumps(dict(Counter(c for _, _, _, c in iter_colors(tree.getroot())).most_common()), indent=2))
            return 0
        return {"remap": cmd_remap, "currentcolor": cmd_currentcolor, "prefix-ids": cmd_prefix_ids,
                "sanitize": cmd_sanitize, "precision": cmd_precision, "fit": cmd_fit}[a.cmd](a)
    except (ValueError, ET.ParseError, OSError) as e:
        sys.stderr.write("error: %s\n" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
