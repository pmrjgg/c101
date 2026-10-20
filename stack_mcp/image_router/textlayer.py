"""Live SVG text from Ideogram layerize output, composed over a traced drawing.

``vector_generate`` with ``IMAGE_VECTOR_PARAMS={"strategy": "layerize"}`` draws a raster with the VECTOR
model, asks Ideogram's layerize endpoint to separate the lettering from the artwork, traces the text-free
artwork with the TRACE configuration and rebuilds the lettering here as real ``<text>`` elements, so it stays
editable (wording, font, size, colour) in Illustrator, Inkscape, by Claude as SVG text, and as text in a
layered PDF (``export_pdf``).

Layerize reports text in the draft raster's pixel space: one container per text block, each item a box
(``x``, ``y``, ``width``, ``height``, ``angle``, ``alignment``, ``font_size``, ``line_height``, ``font_file``,
``font_candidates``) holding styled ``spans`` (``text``, ``color``, ``font_fx``). Boxes are mapped onto the
traced SVG's viewBox. Lines are centred in their box (layerize boxes hug the glyphs) with the baseline 0.35 em
below each line's centre; the visual-reviewer loop corrects any residual drift.

The result always has named top-level layers (``inkscape:groupmode="layer"``): the artwork (one layer, or
one per colour when split) and ``Text`` on top. Model output is untrusted: text is XML-escaped by
ElementTree, colours, font names and numbers are validated, and nothing from it becomes markup.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from typing import Any

from .svgtools import INK_GROUPMODE, INK_LABEL, SVG_NS, layerize, load_svg, serialize

_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_CANDIDATE = re.compile(r"^font__([a-z0-9][a-z0-9-]{0,60})__([a-z0-9]{1,20})$")
_SAFE_FONT = re.compile(r"[^A-Za-z0-9 \-]")
_WEIGHTS = {"thin": 100, "hairline": 100, "extralight": 200, "ultralight": 200, "light": 300, "regular": 400,
            "normal": 400, "book": 400, "medium": 500, "semibold": 600, "demibold": 600, "bold": 700,
            "extrabold": 800, "ultrabold": 800, "black": 900, "heavy": 900}
_ANCHOR = {"left": "start", "start": "start", "justify": "start", "center": "middle", "centre": "middle",
           "right": "end", "end": "end"}
# Baseline relative to a line's vertical centre, as a fraction of the font size
# (cap-height/2 for typical Latin fonts; Montserrat, Inter, Roboto land within ~0.05 em).
BASELINE_FROM_CENTRE = 0.35
MAX_TEXT_ITEMS = 200


def _num(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _title(slug: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in slug.split("-") if w)


def font_of(item: Mapping[str, Any]) -> tuple[str, int | None, bool]:
    """(family, weight, italic) for an item: the first ``font__<family>__<weight>`` candidate, else the
    font file name (``Montserrat-BoldItalic.ttf``)."""
    for cand in item.get("font_candidates") or []:
        m = _CANDIDATE.match(str(cand))
        if m:
            token = m.group(2)
            digits = re.match(r"\d{3}", token)
            weight = int(digits.group(0)) if digits else _WEIGHTS.get(token.replace("italic", "") or "regular")
            return _SAFE_FONT.sub("", _title(m.group(1)))[:60], weight, "italic" in token
        break  # only the top candidate is the chosen font
    stem = re.sub(r"\.(ttf|otf|woff2?)$", "", str(item.get("font_file") or ""), flags=re.I)
    family, _, style = stem.partition("-")
    family = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", family)  # NosiferCaps -> Nosifer Caps
    style_l = style.lower()
    italic = "italic" in style_l or "oblique" in style_l
    weight = _WEIGHTS.get(style_l.replace("italic", "").replace("oblique", "") or "regular")
    return _SAFE_FONT.sub("", family)[:60], weight, italic


def _lines(spans: Iterable[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Split styled spans into lines at newlines, keeping each piece's style."""
    lines: list[list[Mapping[str, Any]]] = [[]]
    for span in spans:
        parts = str(span.get("text") or "").split("\n")
        for i, part in enumerate(parts):
            if i:
                lines.append([])
            if part:
                lines[-1].append({**span, "text": part})
    return [ln for ln in lines if ln] or []


def _span_style(span: Mapping[str, Any], el: ET.Element) -> None:
    color = str(span.get("color") or "")
    if _COLOR.match(color):
        el.set("fill", color)
    fx = {str(f).lower() for f in span.get("font_fx") or []}
    if "bold" in fx:
        el.set("font-weight", "bold")
    if "italic" in fx:
        el.set("font-style", "italic")
    deco = (["underline"] if "underline" in fx else []) + (["line-through"] if fx & {"line-through", "strikethrough"} else [])
    if deco:
        el.set("text-decoration", " ".join(deco))


def text_layer(containers: Any, raster_size: tuple[int, int], viewbox: tuple[float, float, float, float]) -> tuple[ET.Element, int]:
    """A ``Text`` layer <g> with one <text> per line; returns (group, number of text elements)."""
    rw, rh = max(1, raster_size[0]), max(1, raster_size[1])
    vx, vy, vw, vh = viewbox
    sx, sy = vw / rw, vh / rh
    layer = ET.Element(f"{{{SVG_NS}}}g", {"id": "text-layer", INK_GROUPMODE: "layer", INK_LABEL: "Text"})
    count = 0
    items = [(c, it) for c in containers or [] if isinstance(c, Mapping)
             for it in (c.get("items") or []) if isinstance(it, Mapping)][:MAX_TEXT_ITEMS]
    for container, item in items:
        lines = _lines(s for s in item.get("spans") or [] if isinstance(s, Mapping))
        if not lines:
            continue
        x, y = _num(item.get("x")), _num(item.get("y"))
        w, h = max(0.0, _num(item.get("width"))), max(0.0, _num(item.get("height")))
        size = max(1.0, _num(item.get("font_size"), 16.0))
        line_px = size * max(0.5, _num(item.get("line_height"), 1.2))
        anchor = _ANCHOR.get(str(item.get("alignment") or "left").lower(), "start")
        ax = x + (w / 2 if anchor == "middle" else w if anchor == "end" else 0.0)
        family, weight, italic = font_of(item)
        block = ET.SubElement(layer, f"{{{SVG_NS}}}g", {"id": f"text-{count + 1}"})
        block.set("font-family", f"'{family}', sans-serif" if family else "sans-serif")
        block.set("font-size", _fmt(size * sy))
        block.set("text-anchor", anchor)
        if weight:
            block.set("font-weight", str(weight))
        if italic:
            block.set("font-style", "italic")
        for key, attr in (("font_file", "data-font-file"), ("style_class", "data-style-class")):
            if item.get(key):
                block.set(attr, _SAFE_FONT.sub("", str(item[key]).replace(".", "-"))[:80])
        if container.get("id"):
            block.set("data-container", _SAFE_FONT.sub("", str(container["id"]))[:40])
        angle = _num(item.get("angle"))
        if angle:
            cx, cy = vx + (x + w / 2) * sx, vy + (y + h / 2) * sy
            block.set("transform", f"rotate({_fmt(angle)} {_fmt(cx)} {_fmt(cy)})")
        n = len(lines)
        for i, line in enumerate(lines):
            # lines centred in the box: right whether the box hugs the glyphs (layerize) or is the CSS line box
            baseline = y + h / 2 + (i - (n - 1) / 2) * line_px + BASELINE_FROM_CENTRE * size
            text = ET.SubElement(block, f"{{{SVG_NS}}}text", {"x": _fmt(vx + ax * sx), "y": _fmt(vy + baseline * sy)})
            text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            for span in line:
                tspan = ET.SubElement(text, f"{{{SVG_NS}}}tspan")
                tspan.text = str(span["text"])[:2000]
                _span_style(span, tspan)
            count += 1
    return layer, count


def viewbox_of(root: ET.Element, fallback: tuple[int, int]) -> tuple[float, float, float, float]:
    vb = (root.get("viewBox") or "").replace(",", " ").split()
    if len(vb) == 4:
        nums = [_num(v) for v in vb]
        if nums[2] > 0 and nums[3] > 0:
            return nums[0], nums[1], nums[2], nums[3]
    w = _num(re.sub(r"[a-z%]+$", "", root.get("width") or ""), fallback[0])
    h = _num(re.sub(r"[a-z%]+$", "", root.get("height") or ""), fallback[1])
    return 0.0, 0.0, w or fallback[0], h or fallback[1]


def compose(traced_svg: str, containers: Any, raster_size: tuple[int, int], *, split_colors: bool) -> tuple[str, dict[str, Any]]:
    """The traced artwork as named layer(s) with a live ``Text`` layer on top.

    ``split_colors`` layers the artwork by fill colour first (``Artwork <colour>`` layers, as
    ``image_vectorize(layered=true)`` does); otherwise the artwork is one ``Artwork`` layer.
    """
    notes: list[str] = []
    if split_colors:
        traced_svg, report = layerize(traced_svg, by="color")
        notes += report.get("notes") or []
    root = load_svg(traced_svg)
    viewbox = viewbox_of(root, raster_size)
    if root.get("viewBox") is None:
        root.set("viewBox", " ".join(_fmt(v) for v in viewbox))
    layers = [el for el in root if el.get(INK_GROUPMODE) == "layer"]
    if layers and split_colors:
        for el in layers:
            el.set(INK_LABEL, f"Artwork {el.get(INK_LABEL) or ''}".strip())
    else:
        art = ET.Element(f"{{{SVG_NS}}}g", {"id": "artwork-layer", INK_GROUPMODE: "layer", INK_LABEL: "Artwork"})
        keep = {f"{{{SVG_NS}}}{t}" for t in ("defs", "style", "title", "desc", "metadata")}
        for el in list(root):
            if el.tag not in keep:
                root.remove(el)
                art.append(el)
        root.append(art)
    text, count = text_layer(containers, raster_size, viewbox)
    if count:
        root.append(text)
    labels = [el.get(INK_LABEL) for el in root if el.get(INK_GROUPMODE) == "layer"]
    return serialize(root), {"text_elements": count, "layers": labels, "notes": notes}
