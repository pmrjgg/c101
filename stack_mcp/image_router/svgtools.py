"""Local SVG document tools: inspect, layers, layerize, compose and PDF layer units.

Layers are top-level ``<g id="layer-..." inkscape:groupmode="layer" inkscape:label="...">``
groups: Inkscape-native, and Illustrator imports top-level groups as layers. When a document
has no ``inkscape:groupmode="layer"`` markers, every top-level ``<g>`` counts as a layer.

``layerize`` rewrites a document into layers while preserving ``<defs>``, z-order and
appearance:

* ``by="group"``   - top-level groups become layers (a single wrapper group is descended into);
  consecutive loose elements become "Ungrouped N" layers. Nothing is reordered.
* ``by="color"``   - one layer per paint colour (fill, else stroke; gradients/patterns by id).
* ``by="mapping"`` - ``{layer_name: [element ids or CSS-like selectors]}``; the rest goes to "Other".

For colour and mapping layering, groups whose effect is not distributive (opacity, filter, mask,
clip-path in objectBoundingBox units, blend modes, referenced by id - including ``#id`` selectors
in ``<style>``) stay whole; other groups are flattened and their transform / presentation
attributes (and a userSpaceOnUse clip-path, which distributes over children) are re-applied
through wrapper groups, so each leaf renders exactly as before. Leaves are assigned greedily in
document order; a leaf may only join an earlier layer of its key when it does not overlap anything
drawn in between (overlap = rasterised coverage at ~384 px, any alpha; thick shapes are eroded by
one grid pixel so the anti-aliasing / spline slivers along edges shared by neighbouring shapes do
not count, while thin shapes keep their full coverage; a visible leaf too small to show at that
grid is treated as covering everything, so it is never moved). With ``strict_z_order`` (default) a
conflicting leaf opens a new layer of the same key ("#ff0000 (2)") instead, so z-order and
appearance are preserved (up to those edge slivers); the result is re-rendered and compared with
the original (``appearance``).

Paint and visibility are resolved like a browser does for the subset that matters here: inline
``style`` > ``<style>`` rules (specificity, then order; ``!important`` wins) > presentation
attributes > inheritance, so stylesheet-coloured files (Illustrator's "Export As SVG" classes)
get correct colour keys and palettes.
"""

from __future__ import annotations

import copy
import io as _stdio
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .svg import SvgError

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
XML_NS = "http://www.w3.org/XML/1998/namespace"
INK_GROUPMODE = f"{{{INKSCAPE_NS}}}groupmode"
INK_LABEL = f"{{{INKSCAPE_NS}}}label"
HREF_ATTRS = ("href", f"{{{XLINK_NS}}}href")
PREFIXES = {"inkscape": INKSCAPE_NS, "sodipodi": SODIPODI_NS, "xlink": XLINK_NS, "xml": XML_NS, "svg": SVG_NS}

NON_RENDERING = frozenset(
    """defs style title desc metadata script linearGradient radialGradient pattern clipPath mask filter
    marker symbol font font-face color-profile cursor view namedview""".split()
)
SHAPES = frozenset("path rect circle ellipse line polyline polygon text image use".split())
NON_DISTRIBUTIVE = ("opacity", "filter", "mask", "clip-path", "mix-blend-mode", "isolation")
PAINT_PROPS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color", "color")
WRAPPER_DROP = {"id", INK_GROUPMODE, INK_LABEL, f"{{{SODIPODI_NS}}}insensitive", f"{{{INKSCAPE_NS}}}highlight-color"}

for _p, _uri in (("", SVG_NS), ("xlink", XLINK_NS), ("inkscape", INKSCAPE_NS), ("sodipodi", SODIPODI_NS)):
    ET.register_namespace(_p, _uri)


def Q(local: str) -> str:  # noqa: N802 - mirrors ET's {ns}tag notation
    return f"{{{SVG_NS}}}{local}"


def local_name(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""  # comments / processing instructions
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


# --- parsing / serialisation ---------------------------------------------------------------------


def load_svg(data: bytes | str) -> ET.Element:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if b"<!ENTITY" in raw:
        raise SvgError("SVG declares XML entities; refusing to process it")
    try:
        for _event, (prefix, uri) in ET.iterparse(_stdio.BytesIO(raw), events=("start-ns",)):
            if prefix and uri not in (SVG_NS,):
                try:
                    ET.register_namespace(prefix, uri)
                except ValueError:
                    pass
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SvgError(f"not well-formed XML: {exc}") from None
    if root.tag == "svg":  # no namespace: renderers would ignore it - repair
        text = raw.decode("utf-8", "replace")
        text = re.sub(r"<svg\b", f'<svg xmlns="{SVG_NS}"', text, count=1)
        root = ET.fromstring(text.encode("utf-8"))
    if root.tag != Q("svg"):
        raise SvgError(f"root element is <{local_name(root.tag)}>, not an SVG <svg>")
    return root


def serialize(root: ET.Element) -> str:
    ET.register_namespace("", SVG_NS)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


# --- style / paint helpers -----------------------------------------------------------------------


def parse_style(style: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for decl in (style or "").split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            if k.strip():
                out[k.strip().lower()] = v.strip()
    return out


_IMPORTANT_RE = re.compile(r"\s*!\s*important\s*$", re.I)


def parse_declarations(text: str | None) -> dict[str, tuple[str, bool]]:
    """CSS declarations -> {property: (value, important)}."""
    out: dict[str, tuple[str, bool]] = {}
    for k, v in parse_style(text).items():
        important = bool(_IMPORTANT_RE.search(v))
        out[k] = (_IMPORTANT_RE.sub("", v).strip(), important)
    return out


def format_style(d: Mapping[str, str]) -> str:
    return ";".join(f"{k}:{v}" for k, v in d.items())


def prop(el: ET.Element, name: str, sheet: StyleSheet | None = None) -> str | None:
    """A presentation property: inline style > stylesheet rules > the attribute.

    Without a ``sheet`` only the style attribute and the presentation attribute are read.
    """
    if sheet is not None:
        return sheet.prop(el, name)
    st = parse_style(el.get("style"))
    if name in st:
        return _IMPORTANT_RE.sub("", st[name]).strip()
    return el.get(name)


NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "lime": "#00ff00", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "cyan": "#00ffff", "aqua": "#00ffff", "magenta": "#ff00ff",
    "fuchsia": "#ff00ff", "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0", "maroon": "#800000",
    "olive": "#808000", "navy": "#000080", "purple": "#800080", "teal": "#008080", "orange": "#ffa500",
    "pink": "#ffc0cb", "brown": "#a52a2a", "gold": "#ffd700", "indigo": "#4b0082", "violet": "#ee82ee",
}


def norm_color(value: str | None) -> str | None:
    """Normalise a paint value: '#rrggbb', 'url(#id)', 'currentcolor', or None for no paint."""
    if value is None:
        return None
    v = value.strip().lower().replace(" !important", "")
    if v in ("", "none", "transparent", "inherit"):
        return None
    if v.startswith("url("):
        m = re.match(r"url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)", v)
        return f"url(#{m.group(1)})" if m else v
    if re.fullmatch(r"#[0-9a-f]{3,4}", v):
        return "#" + "".join(c * 2 for c in v[1:4])
    if re.fullmatch(r"#[0-9a-f]{6}([0-9a-f]{2})?", v):
        return v[:7]
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()][:3]
        try:
            vals = [round(float(p[:-1]) * 2.55) if p.endswith("%") else round(float(p)) for p in parts]
            return "#" + "".join(f"{max(0, min(255, x)):02x}" for x in vals)
        except ValueError:
            return v
    return NAMED_COLORS.get(v, v)


def paint_values(el: ET.Element, sheet: StyleSheet | None = None) -> Iterable[tuple[str, str]]:
    """(property, normalised colour) pairs declared on one element (style, stylesheet, attribute)."""
    for name in PAINT_PROPS:
        c = norm_color(prop(el, name, sheet))
        if c:
            yield name, c


def palette(elements: Iterable[ET.Element], limit: int | None = None, sheet: StyleSheet | None = None) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for el in elements:
        for _name, c in paint_values(el, sheet):
            if c.startswith("#"):
                counts[c] += 1
    items = counts.most_common(limit)
    return [{"color": c, "count": n} for c, n in items]


def refs_in(el: ET.Element) -> set[str]:
    """ids referenced by url(#id) or href="#id" on one element."""
    ids: set[str] = set()
    for k, v in el.attrib.items():
        if k in HREF_ATTRS and v.startswith("#"):
            ids.add(v[1:])
        elif "url(" in v:
            ids.update(m.group(1) for m in re.finditer(r"url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)", v))
    if local_name(el.tag) == "style" and el.text:
        ids.update(m.group(1) for m in re.finditer(r"url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)", el.text))
    return ids


def is_hidden(el: ET.Element, sheet: StyleSheet | None = None) -> bool:
    return (prop(el, "display", sheet) or "").strip() == "none" or (prop(el, "visibility", sheet) or "").strip() in (
        "hidden", "collapse")


def opacity_of(el: ET.Element, sheet: StyleSheet | None = None) -> float:
    """The element's own ``opacity`` (1.0 when unset or unparseable)."""
    raw = (prop(el, "opacity", sheet) or "").strip()
    if not raw:
        return 1.0
    try:
        v = float(raw[:-1]) / 100 if raw.endswith("%") else float(raw)
    except ValueError:
        return 1.0
    return max(0.0, min(1.0, v))


def make_visible(el: ET.Element) -> None:
    if el.get("display") == "none":
        del el.attrib["display"]
    if el.get("visibility") in ("hidden", "collapse"):
        del el.attrib["visibility"]
    st = parse_style(el.get("style"))
    changed = False
    if st.get("display") == "none":
        del st["display"]
        changed = True
    if st.get("visibility") in ("hidden", "collapse"):
        del st["visibility"]
        changed = True
    if changed:
        if st:
            el.set("style", format_style(st))
        else:
            el.attrib.pop("style", None)


def slug(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].rstrip("-") or "layer")


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    m = re.fullmatch(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(px|pt|mm|cm|in|pc|em|ex)?\s*", value)
    if not m:
        return None
    v = float(m.group(1))
    # CSS reference pixel: 96 dpi (resvg renders with dpi=96, see render.render_svg); em = 16px default
    return v * {"pt": 4 / 3, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0, "pc": 16.0, "em": 16.0, "ex": 8.0}.get(
        m.group(2) or "", 1.0)


def doc_size(root: ET.Element) -> tuple[float, float, tuple[float, float, float, float] | None]:
    """(width, height) in px plus the viewBox (if any). CSS default 300x150 when unknown."""
    vb = None
    raw = root.get("viewBox")
    if raw:
        parts = [p for p in re.split(r"[\s,]+", raw.strip()) if p]
        if len(parts) == 4:
            try:
                x, y, w, h = (float(p) for p in parts)
                if w > 0 and h > 0:
                    vb = (x, y, w, h)
            except ValueError:
                vb = None
    w, h = _num(root.get("width")), _num(root.get("height"))
    if vb:
        if w is None and h is None:
            w, h = vb[2], vb[3]
        elif w is None:
            w = h * vb[2] / vb[3]
        elif h is None:
            h = w * vb[3] / vb[2]
    return (w or 300.0), (h or 150.0), vb


# --- layers --------------------------------------------------------------------------------------


def is_layer_group(el: ET.Element) -> bool:
    return local_name(el.tag) == "g" and el.get(INK_GROUPMODE) == "layer"


def top_level_layers(root: ET.Element) -> tuple[list[ET.Element], str]:
    marked = [c for c in root if is_layer_group(c)]
    if marked:
        return marked, "inkscape"
    groups = [c for c in root if local_name(c.tag) == "g"]
    return groups, ("groups" if groups else "none")


def layer_label(el: ET.Element, index: int) -> str:
    return el.get(INK_LABEL) or el.get("id") or f"Layer {index}"


def drawables(el: ET.Element) -> Iterable[ET.Element]:
    """Rendering elements below (and including) ``el`` - skips defs-like subtrees."""
    stack = [el]
    while stack:
        cur = stack.pop()
        name = local_name(cur.tag)
        if not name or name in NON_RENDERING:
            continue
        yield cur
        stack.extend(reversed(list(cur)))


@dataclass(slots=True)
class LayerUnit:
    label: str
    elements: list[ET.Element]
    visible: bool = True
    is_layer: bool = True
    id: str | None = None


def layer_units(root: ET.Element, sheet: StyleSheet | None = None) -> tuple[list[LayerUnit], str]:
    """Top-level render units in document order: layers, plus runs of loose content."""
    layers, mode = top_level_layers(root)
    if mode == "none":
        return [], mode
    layer_set = {id(x) for x in layers}
    units: list[LayerUnit] = []
    run: list[ET.Element] = []
    loose_n = 0

    def flush() -> None:
        nonlocal loose_n, run
        if run:
            loose_n += 1
            units.append(LayerUnit(f"Unlayered {loose_n}" if loose_n > 1 else "Unlayered", run, True, False))
            run = []

    n = 0
    for c in root:
        name = local_name(c.tag)
        if not name or name in NON_RENDERING:
            continue
        if id(c) in layer_set:
            flush()
            n += 1
            units.append(LayerUnit(layer_label(c, n), [c], not is_hidden(c, sheet), True, c.get("id")))
        else:
            run.append(c)
    flush()
    return units, mode


def describe_layers(root: ET.Element) -> dict[str, Any]:
    sheet = StyleSheet(root)
    units, mode = layer_units(root, sheet)
    out = []
    for u in units:
        els = [d for e in u.elements for d in drawables(e)]
        out.append(
            {
                "id": u.id,
                "label": u.label,
                "visible": u.visible,
                "kind": ("inkscape-layer" if mode == "inkscape" else "group") if u.is_layer else "loose",
                "element_count": len(els),
                "shape_count": sum(1 for e in els if local_name(e.tag) in SHAPES),
                "palette": [p["color"] for p in palette(els, 8, sheet)],
            }
        )
    loose = sum(len(u.elements) for u in units if not u.is_layer)
    if mode == "none":
        loose = sum(1 for c in root if local_name(c.tag) and local_name(c.tag) not in NON_RENDERING)
    return {"mode": mode, "layers": out, "layer_count": sum(1 for u in units if u.is_layer), "loose_elements": loose}


# --- pdf units --------------------------------------------------------------------------------


@dataclass(slots=True)
class UnitDoc:
    label: str
    svg_text: str  # a full SVG document that draws only this unit
    visible: bool = True
    opacity: float = 1.0  # the unit's own group opacity, applied by the PDF writer (svglib ignores it)
    is_layer: bool = True
    nested_opacity: int = 0  # elements inside the unit with their own opacity (lost by svglib)


def _closure_elements(start: Iterable[ET.Element], ids: Mapping[str, ET.Element]) -> list[ET.Element]:
    """Elements transitively referenced (url(#id), href="#id") from ``start``'s subtrees."""
    seen: set[str] = set()
    todo = [i for el in start for node in el.iter() if local_name(node.tag) for i in refs_in(node)]
    out: list[ET.Element] = []
    while todo:
        ident = todo.pop()
        if ident in seen or ident not in ids:
            continue
        seen.add(ident)
        target = ids[ident]
        out.append(target)
        todo.extend(i for node in target.iter() if local_name(node.tag) for i in refs_in(node))
    return out


def _segments(root: ET.Element, sheet: StyleSheet) -> list[LayerUnit]:
    """Non-layered drawing order: runs of top-level content, with every top-level element that
    has its own opacity in a unit of its own (so the PDF writer can apply that opacity)."""
    units: list[LayerUnit] = []
    run: list[ET.Element] = []
    for c in root:
        name = local_name(c.tag)
        if not name or name in NON_RENDERING:
            continue
        if opacity_of(c, sheet) < 1.0:
            if run:
                units.append(LayerUnit("Drawing", run, True, False))
                run = []
            units.append(LayerUnit("Drawing", [c], True, False))
        else:
            run.append(c)
    if run:
        units.append(LayerUnit("Drawing", run, True, False))
    return units


def unit_documents(root: ET.Element, *, layered: bool = True) -> list[UnitDoc]:
    """One SVG document per render unit, for the PDF writer.

    ``layered``: one unit per top-level layer (plus runs of loose content); otherwise (or when the
    file has no layers) runs of top-level content. Each document holds the unit itself plus only
    what it needs from elsewhere: every ``<style>`` and the transitive closure of the ids it
    references (gradients, clip paths, ``<use>`` targets in other layers, ...) in a ``<defs>`` -
    not copies of every other unit, which made layered exports quadratic in the number of layers.
    Hidden layers are made visible (the PDF OCG carries the initial visibility instead). A unit
    that is a single element with its own ``opacity`` has it removed and reported in
    ``UnitDoc.opacity`` so the PDF writer can apply it as a transparency group.
    """
    sheet = StyleSheet(root)
    units, _mode = layer_units(root, sheet) if layered else ([], "none")
    if not units:
        units = _segments(root, sheet)
    # one pass over the document: ids, parents, document order and each node's top-level child
    ids: dict[str, ET.Element] = {}
    parent: dict[int, ET.Element] = {}
    order: dict[int, int] = {}
    top_index: dict[int, int] = {}
    styles: list[ET.Element] = []
    tops = list(root)
    for i, c in enumerate(tops):
        for n in c.iter():
            if not local_name(n.tag):
                continue
            order[id(n)] = len(order)
            top_index[id(n)] = i
            for k in n:
                parent[id(k)] = n
            if n.get("id"):
                ids.setdefault(n.get("id"), n)
            if local_name(n.tag) == "style":
                styles.append(n)
    out: list[UnitDoc] = []
    for unit in units:
        members = {id(n) for e in unit.elements for n in e.iter()}
        need = [e for e in _closure_elements(unit.elements, ids) if id(e) not in members]
        need_ids = {id(e) for e in need}

        def inside_needed(el: ET.Element) -> bool:
            up = parent.get(id(el))
            while up is not None:
                if id(up) in need_ids:
                    return True
                up = parent.get(id(up))
            return False

        # what this unit's document holds besides the unit: every <style> (CSS applies document-wide)
        # and the referenced elements, each at its original top-level position (document order)
        extras: dict[int, list[tuple[int, str, ET.Element]]] = {}
        for st in styles:
            if id(st) not in members and not inside_needed(st):
                extras.setdefault(top_index[id(st)], []).append((order[id(st)], "style", st))
        for e in need:
            if not inside_needed(e) and id(e) in top_index:
                extras.setdefault(top_index[id(e)], []).append((order[id(e)], "defs", e))
        unit_tops = sorted(top_index[id(e)] for e in unit.elements)
        doc = ET.Element(root.tag, dict(root.attrib))
        copies: list[ET.Element] = []
        for i in sorted(set(extras) | {unit_tops[0]}):
            if i == unit_tops[0]:
                for e in unit.elements:
                    cc = copy.deepcopy(e)
                    if unit.is_layer:
                        make_visible(cc)
                    doc.append(cc)
                    copies.append(cc)
            holder: ET.Element | None = None
            for _o, kind, el in sorted(extras.get(i, []), key=lambda t: t[0]):
                if kind == "style":
                    doc.append(copy.deepcopy(el))
                else:
                    if holder is None:
                        holder = ET.SubElement(doc, Q("defs"))
                    holder.append(copy.deepcopy(el))
        opacity = 1.0
        handled: set[int] = set()
        if len(unit.elements) == 1 and copies:
            opacity = opacity_of(unit.elements[0], sheet)
            if opacity < 1.0:
                _drop_opacity(copies[0])
                handled.add(id(unit.elements[0]))
        nested = sum(
            1 for e in unit.elements for n in e.iter()
            if local_name(n.tag) and id(n) not in handled and opacity_of(n, sheet) < 1.0
        )
        out.append(UnitDoc(unit.label, serialize(doc), unit.visible, opacity, unit.is_layer, nested))
    return out


LEAF_SHAPES = frozenset("path rect circle ellipse line polyline polygon text".split())


def _inherited(el: ET.Element, name: str, sheet: StyleSheet, parent: Mapping[int, ET.Element]) -> str | None:
    node: ET.Element | None = el
    while node is not None:
        v = sheet.prop(node, name)
        if v is not None and v.strip().lower() != "inherit":
            return v
        node = parent.get(id(node))
    return None


def _rasterise_svg_image(data: bytes, el: ET.Element) -> bytes:
    from .render import render_svg

    w = _num(el.get("width")) or 256.0
    return render_svg(data, width=int(max(16, min(2048, w * 2))))


def inline_local_images(root: ET.Element, base_dir: Any = None, *, rasterize_svg: bool = False) -> list[str]:
    """Embed local raster files referenced by ``<image>`` / ``<feImage>`` as data URIs (in place).

    Relative hrefs resolve against ``base_dir`` (the source SVG's folder), as a browser or
    resvg would; ``file://`` URLs and absolute paths are read as given. Only files that are
    images are embedded (anything else is left out with a warning, so an SVG can never pull
    an arbitrary local file into an output). PNG and JPEG are kept, other formats become PNG,
    and with ``rasterize_svg`` nested SVG images become PNG too (svglib cannot draw them).
    Returns warnings for references that could not be embedded.
    """
    from pathlib import Path
    from urllib.parse import unquote, urlparse

    from .imaging import ensure_png
    from .io import MAX_INPUT_BYTES, sniff_mime, to_data_uri

    missing: list[str] = []
    not_images: list[str] = []
    remote: list[str] = []
    failed: list[str] = []
    for el in root.iter():
        if local_name(el.tag) not in ("image", "feImage"):
            continue
        attr = next((a for a in HREF_ATTRS if el.get(a)), None)
        if attr is None:
            continue
        href = el.get(attr, "").strip()
        if not href or href.startswith("#"):
            continue
        if href.startswith("data:"):
            if rasterize_svg and href[5:].lower().startswith("image/svg+xml"):
                from .io import parse_data_uri

                try:
                    data, _mime = parse_data_uri(href)
                    el.set(attr, to_data_uri(_rasterise_svg_image(data, el), "image/png"))
                except Exception:
                    failed.append("embedded SVG image")
            continue
        if re.match(r"^(https?:)?//", href, re.I):
            remote.append(href.split("?", 1)[0][:120])
            continue
        if href.lower().startswith("file:"):
            path = Path(unquote(urlparse(href).path))
        else:
            rel = Path(unquote(href.split("#", 1)[0].split("?", 1)[0]))
            if rel.is_absolute():
                path = rel
            elif base_dir is None:
                missing.append(href[:120])
                continue
            else:
                path = Path(base_dir) / rel
        try:
            if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
                missing.append(href[:120])
                continue
            data = path.read_bytes()
        except OSError:
            missing.append(href[:120])
            continue
        mime = sniff_mime(data)
        if not mime or not mime.startswith("image/"):
            not_images.append(href[:120])
            continue
        try:
            if mime == "image/svg+xml":
                if rasterize_svg:
                    data, mime = _rasterise_svg_image(data, el), "image/png"
            elif mime not in ("image/png", "image/jpeg"):
                data, mime = ensure_png(data), "image/png"
        except Exception:
            failed.append(href[:120])
            continue
        el.set(attr, to_data_uri(data, mime))
    warnings = []
    if missing:
        warnings.append(f"{len(missing)} linked image(s) could not be found and are missing from the output: {missing[:5]}")
    if not_images:
        warnings.append(f"{len(not_images)} <image> reference(s) are not image files and were not embedded: {not_images[:5]}")
    if remote:
        warnings.append(f"{len(remote)} remote image(s) are not embedded (download them and link local files): {remote[:5]}")
    if failed:
        warnings.append(f"{len(failed)} linked image(s) could not be converted: {failed[:5]}")
    return warnings


def prepare_for_pdf(root: ET.Element, base_dir: Any = None) -> list[str]:
    """Rewrite a document (in place) into what svglib can draw, and list what it still cannot.

    * linked images are embedded (:func:`inline_local_images`, nested SVGs rasterised);
    * ``opacity`` on a single shape is folded into its fill-/stroke-opacity, which svglib does
      honour (exact for a shape painted with only fill or only stroke; approximate where the
      stroke overlaps the fill);
    * masks, filters, pattern fills, ``<foreignObject>`` and blend modes are reported: svglib
      ignores them, so the PDF differs from svg_render there.
    Group opacity is handled by the PDF writer for top-level units; nested group opacity is
    reported by :func:`unit_documents`.
    """
    warnings = inline_local_images(root, base_dir, rasterize_svg=True)
    sheet = StyleSheet(root)
    parent = {id(c): p for p in root.iter() for c in p}
    approximated = 0
    for el in root.iter():
        if local_name(el.tag) not in LEAF_SHAPES:
            continue
        o = opacity_of(el, sheet)
        if o >= 1.0:
            continue
        st = parse_style(el.get("style"))
        painted = 0
        for paint in ("fill", "stroke"):
            value = _inherited(el, paint, sheet, parent)
            if paint == "fill" and value is None and local_name(el.tag) != "line":
                value = "#000000"
            if norm_color(value) is None:
                continue
            painted += 1
            raw = (_inherited(el, f"{paint}-opacity", sheet, parent) or "1").strip()
            try:
                current = float(raw[:-1]) / 100 if raw.endswith("%") else float(raw)
            except ValueError:
                current = 1.0
            st[f"{paint}-opacity"] = f"{max(0.0, min(1.0, current)) * o:.4g}"
        if painted == 2:
            approximated += 1
        el.attrib.pop("opacity", None)
        st["opacity"] = "1"
        el.set("style", format_style(st))
    if approximated:
        warnings.append(
            f"{approximated} shape(s) with opacity and both fill and stroke: the PDF approximates their opacity "
            "per paint (the stroke's inner half over the fill differs slightly)"
        )
    counts: Counter[str] = Counter()
    ids = {el.get("id"): el for el in root.iter() if local_name(el.tag) and el.get("id")}
    for el in root.iter():
        name = local_name(el.tag)
        if not name:
            continue
        if name == "foreignObject":
            counts["<foreignObject>"] += 1
            continue
        for p_, label in (("mask", "mask"), ("filter", "filter")):
            v = (sheet.prop(el, p_) or "").strip().lower()
            if v and v != "none":
                counts[label] += 1
        blend = (sheet.prop(el, "mix-blend-mode") or "").strip().lower()
        if blend and blend != "normal":
            counts["mix-blend-mode"] += 1
        for paint in ("fill", "stroke"):
            m = re.match(r"url\(\s*['\"]?#([^)'\"]+)", (sheet.prop(el, paint) or "").strip())
            target = ids.get(m.group(1)) if m else None
            if target is None:
                continue
            if local_name(target.tag) == "pattern":
                counts["pattern fill"] += 1
            elif (local_name(target.tag) == "radialGradient"
                  and (target.get("gradientUnits") or "objectBoundingBox") == "objectBoundingBox"
                  and not _square_shape(el)):
                counts["radial gradient on a non-square shape (drawn as a circle)"] += 1
    if counts:
        listed = ", ".join(f"{n} x{c}" for n, c in counts.most_common())
        warnings.append(
            f"svglib (the PDF converter) ignores {listed}: those parts look different in the PDF than in "
            "svg_render - flatten them first (e.g. rasterise effects into an <image>) if they matter"
        )
    return warnings


def _square_shape(el: ET.Element) -> bool:
    """True for shapes whose bounding box is known to be square (circle, square rect/ellipse)."""
    name = local_name(el.tag)
    if name == "circle":
        return True
    if name == "rect":
        return _num(el.get("width")) is not None and _num(el.get("width")) == _num(el.get("height"))
    if name == "ellipse":
        return _num(el.get("rx")) is not None and _num(el.get("rx")) == _num(el.get("ry"))
    return False


def _drop_opacity(el: ET.Element) -> None:
    """Neutralise an element's own ``opacity`` (the PDF writer applies it to the whole unit)."""
    el.attrib.pop("opacity", None)
    st = parse_style(el.get("style"))
    st["opacity"] = "1"  # inline style also beats a stylesheet rule
    el.set("style", format_style(st))


# --- CSS-like selectors (mapping) -------------------------------------------------------------

_COMPOUND_RE = re.compile(r"(\*|[A-Za-z_][\w\-:]*)?((?:#[\w\-]+|\.[\w\-]+|\[[^\]]+\])*)$")


def _attr_name(name: str) -> str:
    if ":" in name:
        p, n = name.split(":", 1)
        if p in PREFIXES:
            return f"{{{PREFIXES[p]}}}{n}"
    return name


@dataclass(slots=True)
class Compound:
    tag: str | None
    ids: list[str]
    classes: list[str]
    attrs: list[tuple[str, str | None]]

    def matches(self, el: ET.Element, resolver: Callable[[ET.Element, str], str | None] | None = None) -> bool:
        """``resolver`` reads paint properties for [fill=...] tests (mapping mode resolves styles and
        stylesheets); without it attribute selectors read the attribute, as CSS does."""
        name = local_name(el.tag)
        if not name:
            return False
        if self.tag and self.tag != "*" and self.tag != name:
            return False
        if any(el.get("id") != i for i in self.ids):
            return False
        if self.classes and not set(self.classes) <= set((el.get("class") or "").split()):
            return False
        for a, v in self.attrs:
            actual = (resolver(el, a) if resolver else el.get(a)) if a in PAINT_PROPS else el.get(_attr_name(a))
            if actual is None:
                return False
            if v is not None:
                if a in PAINT_PROPS:
                    if norm_color(actual) != norm_color(v):
                        return False
                elif actual != v:
                    return False
        return True


def parse_selector(text: str) -> list[tuple[str, Compound]]:
    """'g.logo > path[fill=#f00]' -> [(combinator, compound), ...] (left to right)."""
    tokens = re.findall(r"\[[^\]]*\]|>|[^\s>\[]+(?:\[[^\]]*\])*|\s+", text.strip())
    parts: list[tuple[str, Compound]] = []
    comb = " "
    buf = ""
    for tok in tokens + [" "]:
        if tok.isspace() or tok == ">":
            if buf:
                parts.append((comb, _compound(buf)))
                buf = ""
                comb = " "
            if tok == ">":
                comb = ">"
            continue
        buf += tok
    if not parts:
        raise SvgError(f"empty selector {text!r}")
    return parts


def _compound(text: str) -> Compound:
    m = _COMPOUND_RE.match(text)
    if not m:
        raise SvgError(f"unsupported selector {text!r} (use tag, #id, .class, [attr] or [attr=value])")
    tag, rest = m.group(1), m.group(2) or ""
    ids = re.findall(r"#([\w\-]+)", re.sub(r"\[[^\]]*\]", "", rest))
    classes = re.findall(r"\.([\w\-]+)", re.sub(r"\[[^\]]*\]", "", rest))
    attrs: list[tuple[str, str | None]] = []
    for a in re.findall(r"\[([^\]]+)\]", rest):
        if "=" in a:
            k, v = a.split("=", 1)
            attrs.append((k.strip(), v.strip().strip("'\"")))
        else:
            attrs.append((a.strip(), None))
    return Compound(tag, ids, classes, attrs)


def selector_matches(
    parts: list[tuple[str, Compound]],
    el: ET.Element,
    parent: Mapping[int, ET.Element],
    resolver: Callable[[ET.Element, str], str | None] | None = None,
) -> bool:
    def match_at(i: int, node: ET.Element) -> bool:
        comb, comp = parts[i]
        if not comp.matches(node, resolver):
            return False
        if i == 0:
            return True
        up = parent.get(id(node))
        if comb == ">":
            return up is not None and match_at(i - 1, up)
        while up is not None:
            if match_at(i - 1, up):
                return True
            up = parent.get(id(up))
        return False

    return match_at(len(parts) - 1, el)


# --- stylesheets ---------------------------------------------------------------------------------


def css_rules(text: str) -> Iterable[tuple[str, str]]:
    """(selector list, declaration block) for every plain rule; @-rules (media, font-face, ...) are skipped."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    i, n = 0, len(text)
    while i < n:
        brace = text.find("{", i)
        if brace == -1:
            return
        prelude = text[i:brace].strip()
        if prelude.startswith("@"):
            depth, j = 0, brace
            while j < n:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            i = j + 1
            continue
        end = text.find("}", brace)
        end = n if end == -1 else end
        yield prelude, text[brace + 1 : end]
        i = end + 1


def specificity(parts: list[tuple[str, Compound]]) -> tuple[int, int, int]:
    ids = sum(len(c.ids) for _, c in parts)
    classes = sum(len(c.classes) + len(c.attrs) for _, c in parts)
    tags = sum(1 for _, c in parts if c.tag and c.tag != "*")
    return ids, classes, tags


@dataclass(slots=True)
class CssRule:
    parts: list[tuple[str, Compound]]
    declarations: dict[str, tuple[str, bool]]
    specificity: tuple[int, int, int]
    order: int


class StyleSheet:
    """The document's ``<style>`` rules, matched with the supported selector subset.

    Selectors outside that subset (pseudo-classes, sibling combinators, attribute operators)
    are skipped. ``id_selectors`` lists every id a rule selects by ``#id`` (even in skipped
    selectors): restructuring must keep those elements' ids.
    """

    def __init__(self, root: ET.Element, parent: Mapping[int, ET.Element] | None = None):
        self.parent = parent if parent is not None else {id(c): p for p in root.iter() for c in p}
        self.rules: list[CssRule] = []
        self.id_selectors: set[str] = set()
        order = 0
        for el in root.iter():
            if local_name(el.tag) != "style":
                continue
            for prelude, block in css_rules("".join(el.itertext())):
                decls = parse_declarations(block)
                for sel in prelude.split(","):
                    sel = sel.strip()
                    if not sel:
                        continue
                    self.id_selectors |= set(re.findall(r"#([\w-]+)", re.sub(r"\[[^\]]*\]", "", sel)))
                    if not decls:
                        continue
                    try:
                        parts = parse_selector(sel)
                    except SvgError:
                        continue  # unsupported selector syntax: ignored, as for unknown CSS
                    self.rules.append(CssRule(parts, decls, specificity(parts), order))
                    order += 1
        # index by the rightmost compound (as browsers do), so an element is only tested against
        # rules that can match it: by id, by class, by tag, plus the universal ones
        self._index: dict[tuple[str, str], list[CssRule]] = {}
        self._universal: list[CssRule] = []
        for rule in self.rules:
            last = rule.parts[-1][1]
            if last.ids:
                self._index.setdefault(("id", last.ids[0]), []).append(rule)
            elif last.classes:
                self._index.setdefault(("class", last.classes[0]), []).append(rule)
            elif last.tag and last.tag != "*":
                self._index.setdefault(("tag", last.tag), []).append(rule)
            else:
                self._universal.append(rule)
        self._cache: dict[int, dict[str, tuple[str, bool]]] = {}

    def _candidates(self, el: ET.Element) -> list[CssRule]:
        found = list(self._universal)
        if el.get("id"):
            found += self._index.get(("id", el.get("id")), [])
        for cls in (el.get("class") or "").split():
            found += self._index.get(("class", cls), [])
        found += self._index.get(("tag", local_name(el.tag)), [])
        return found

    def declarations(self, el: ET.Element) -> dict[str, tuple[str, bool]]:
        """The winning stylesheet declaration per property for ``el`` (no inheritance)."""
        if not self.rules:
            return {}
        key = id(el)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        best: dict[str, tuple[tuple[bool, tuple[int, int, int], int], str, bool]] = {}
        for rule in self._candidates(el):
            if selector_matches(rule.parts, el, self.parent):
                for name, (value, important) in rule.declarations.items():
                    rank = (important, rule.specificity, rule.order)
                    if name not in best or rank > best[name][0]:
                        best[name] = (rank, value, important)
        out = {k: (v[1], v[2]) for k, v in best.items()}
        self._cache[key] = out
        return out

    def prop(self, el: ET.Element, name: str) -> str | None:
        inline = parse_declarations(el.get("style"))
        sheet = self.declarations(el).get(name)
        mine = inline.get(name)
        if mine is not None and (mine[1] or not (sheet and sheet[1])):
            return mine[0]
        if sheet is not None:
            return sheet[0]
        if mine is not None:
            return mine[0]
        return el.get(name)


# --- flatten + leaves ---------------------------------------------------------------------------


@dataclass(slots=True)
class Leaf:
    el: ET.Element
    chain: tuple[ET.Element, ...]  # flattened ancestor groups, outermost first
    index: int
    key: str = ""
    label: str = ""


@dataclass(slots=True)
class LayerOut:
    key: str
    label: str
    leaves: list[Leaf] = field(default_factory=list)
    mask: int | None = None
    id: str = ""
    promote: bool = False  # by=group: the single top-level <g> leaf becomes the layer itself


class SvgDoc:
    def __init__(self, root: ET.Element):
        self.root = root
        self.ids: dict[str, ET.Element] = {}
        self.parent: dict[int, ET.Element] = {}
        self.referenced: set[str] = set()
        for el in root.iter():
            if not local_name(el.tag):
                continue
            if el.get("id"):
                self.ids.setdefault(el.get("id"), el)
            for c in el:
                self.parent[id(c)] = el
            self.referenced |= refs_in(el)
        self.sheet = StyleSheet(root, self.parent)
        # ids selected by #id rules in <style>: restructuring would drop them (wrappers carry no
        # id), so those groups stay whole
        self.referenced |= self.sheet.id_selectors

    @classmethod
    def parse(cls, data: bytes | str) -> SvgDoc:
        return cls(load_svg(data))

    def prop(self, el: ET.Element, name: str) -> str | None:
        return self.sheet.prop(el, name)

    def non_distributive(self, g: ET.Element) -> str | None:
        """Why group ``g`` must stay whole (its effect does not distribute over its children), or None."""
        if g.get("id") and g.get("id") in self.referenced:
            return f"referenced by id ({g.get('id')})"
        for p in NON_DISTRIBUTIVE:
            v = (self.prop(g, p) or "").strip().lower()
            if not v:
                continue
            if p == "opacity" and opacity_of(g, self.sheet) >= 1.0:
                continue
            if (p in ("filter", "mask", "clip-path") and v == "none") or (p == "mix-blend-mode" and v == "normal") or (
                p == "isolation" and v == "auto"
            ):
                continue
            if p == "clip-path" and self._user_space_clip(v):
                continue  # a userSpaceOnUse clip distributes: every wrapper copy is clipped identically
            return f"{p} {v}"
        return None

    def _user_space_clip(self, value: str) -> bool:
        m = re.match(r"url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)$", value)
        target = self.ids.get(m.group(1)) if m else None
        if target is None or local_name(target.tag) != "clipPath":
            return False
        return (target.get("clipPathUnits") or "userSpaceOnUse").strip() == "userSpaceOnUse"

    def flattenable(self, g: ET.Element) -> bool:
        if local_name(g.tag) != "g":
            return False
        return self.non_distributive(g) is None

    def flatten(self, stop: Callable[[ET.Element], bool] | None = None) -> tuple[list[ET.Element], list[Leaf], int]:
        """(preamble, leaves, dropped) - preamble = non-rendering elements in document order."""
        preamble: list[ET.Element] = []
        leaves: list[Leaf] = []
        dropped = 0

        def visit(el: ET.Element, chain: tuple[ET.Element, ...]) -> None:
            nonlocal dropped
            name = local_name(el.tag)
            if not name:
                return
            if name in NON_RENDERING:
                if chain and name in ("title", "desc", "metadata"):
                    dropped += 1  # a flattened group's own tooltip/metadata
                else:
                    preamble.append(el)
                return
            if self.flattenable(el) and not (stop and stop(el)):
                for c in el:
                    visit(c, chain + (el,))
                return
            leaves.append(Leaf(el, chain, len(leaves)))

        for c in self.root:
            visit(c, ())
        return preamble, leaves, dropped

    # --- paint keys ------------------------------------------------------------------------
    def effective(self, name: str, el: ET.Element, chain: tuple[ET.Element, ...]) -> str | None:
        """The property's value on ``el`` (inline style, stylesheet, attribute), else inherited."""
        for node in (el, *reversed(chain), self.root):
            v = self.prop(node, name)
            if v is not None and v.strip().lower() != "inherit":
                return v
        return None

    def hidden(self, el: ET.Element, chain: tuple[ET.Element, ...] = ()) -> bool:
        return any(is_hidden(n, self.sheet) for n in (el, *chain))

    def paint_key(self, el: ET.Element, chain: tuple[ET.Element, ...]) -> tuple[str, str]:
        name = local_name(el.tag)
        if name == "image":
            return "raster", "raster"
        if name in ("g", "a", "switch", "svg", "symbol") or (name not in SHAPES and len(el)):
            keys = self._shape_keys(el, chain)
            keys.discard("none")
            if len(keys) == 1:
                k = keys.pop()
                return k, self._label(k)
            return ("mixed", "mixed") if keys else ("none", "no paint")
        if name == "use" and len(chain) < 16:
            href = next((el.get(a) for a in HREF_ATTRS if el.get(a)), None)
            target = self.ids.get(href[1:]) if href and href.startswith("#") else None
            if target is not None and target is not el:
                # the referenced content inherits from the <use> element and its ancestors
                return self.paint_key(target, chain + (el,))
        fill = self.effective("fill", el, chain)
        fill_c = None if name == "line" else norm_color(fill if fill is not None else "#000000")  # lines have no fill area
        if fill_c == "currentcolor":
            fill_c = norm_color(self.effective("color", el, chain) or "#000000")
        if fill_c:
            return fill_c, self._label(fill_c)
        stroke_c = norm_color(self.effective("stroke", el, chain))
        if stroke_c == "currentcolor":
            stroke_c = norm_color(self.effective("color", el, chain) or "#000000")
        if stroke_c:
            return f"stroke {stroke_c}", self._label(f"stroke {stroke_c}")
        return "none", "no paint"

    def _shape_keys(self, el: ET.Element, chain: tuple[ET.Element, ...]) -> set[str]:
        """Paint keys of every shape below a container, each with its full inheritance chain."""
        keys: set[str] = set()
        stack = [(c, chain + (el,)) for c in el]
        while stack:
            node, ch = stack.pop()
            nm = local_name(node.tag)
            if not nm or nm in NON_RENDERING:
                continue
            if nm in SHAPES:
                keys.add(self.paint_key(node, ch)[0])
            elif len(ch) < 64:
                stack.extend((c, ch + (node,)) for c in node)
        return keys

    def _label(self, key: str) -> str:
        if key.startswith("url(#"):
            target = self.ids.get(key[5:-1])
            kind = local_name(target.tag) if target is not None else "paint"
            kind = {"linearGradient": "gradient", "radialGradient": "gradient"}.get(kind, kind)
            return f"{kind} {key[5:-1]}"
        if key.startswith("stroke url(#"):
            return f"stroke {self._label(key[7:])}"
        return key


# --- coverage (overlap oracle for z-order-safe grouping) ----------------------------------------


def _force_opaque(el: ET.Element) -> None:
    """In place: paints -> opaque black, opacities -> 1 (coverage only depends on geometry)."""
    for node in el.iter():
        if not local_name(node.tag):
            continue
        for p in ("fill", "stroke"):
            v = node.get(p)
            if v is not None and v.strip().lower() != "none":
                node.set(p, "#000")
        for p in ("opacity", "fill-opacity", "stroke-opacity"):
            node.attrib.pop(p, None)
        st = parse_style(node.get("style"))
        for p in ("fill", "stroke"):
            if p in st and st[p].strip().lower() != "none":
                st[p] = "#000"
        st.update({"opacity": "1", "fill-opacity": "1", "stroke-opacity": "1"})
        node.set("style", format_style(st))


class Coverage:
    """Rasterised coverage bitmasks (Python ints) per leaf, rendered with resvg."""

    def __init__(self, doc: SvgDoc, max_side: int = 384):
        self.doc = doc
        w, h, _vb = doc_size(doc.root)
        scale = max_side / max(w, h)
        self.width = max(1, round(w * scale))
        self.height = max(1, round(h * scale))
        self.bits = self.width * self.height
        self.full = (1 << self.bits) - 1
        self.cache: dict[int, int] = {}
        self.renders = 0
        self.failures = 0
        self.unresolved = 0  # visible leaves too small for the grid: treated as covering everything
        self.styles = [copy.deepcopy(s) for s in doc.root.iter(Q("style"))]

    def _closure(self, start: Iterable[ET.Element]) -> list[ET.Element]:
        seen: set[str] = set()
        todo = [i for el in start for node in el.iter() for i in refs_in(node)]
        out: list[ET.Element] = []
        while todo:
            ident = todo.pop()
            if ident in seen or ident not in self.doc.ids:
                continue
            seen.add(ident)
            target = self.doc.ids[ident]
            out.append(target)
            todo.extend(i for node in target.iter() for i in refs_in(node))
        return out

    def mask(self, leaf: Leaf) -> int:
        if leaf.index in self.cache:
            return self.cache[leaf.index]
        from PIL import Image, ImageFilter

        from .render import RenderError, render_svg

        root = ET.Element(Q("svg"), {k: v for k, v in self.doc.root.attrib.items() if k != "id"})
        _force_opaque(root)
        for s in self.styles:
            root.append(copy.deepcopy(s))
        defs = ET.SubElement(root, Q("defs"))
        closure = self._closure([leaf.el, *leaf.chain])
        for ref in closure:
            defs.append(copy.deepcopy(ref))
        parent = root
        for g in leaf.chain:
            w = ET.SubElement(parent, Q("g"), {k: v for k, v in g.attrib.items() if k not in WRAPPER_DROP})
            parent = w
        leaf_copy = copy.deepcopy(leaf.el)
        if leaf_copy.get("id") in {c.get("id") for c in closure}:
            leaf_copy.attrib.pop("id", None)  # already present in <defs>; otherwise keep it for #id CSS rules
        parent.append(leaf_copy)
        for top in list(root)[len(self.styles) + 1 :]:  # chain wrappers + leaf (not styles/defs)
            _force_opaque(top)
        has_text = local_name(leaf.el.tag) == "text" or leaf.el.find(f".//{Q('text')}") is not None
        self.renders += 1
        try:
            png = render_svg(serialize(root), width=self.width, system_fonts=has_text)
            im = Image.open(_stdio.BytesIO(png))
            alpha = im.getchannel("A") if im.mode == "RGBA" else im.convert("L")
            if alpha.size != (self.width, self.height):
                alpha = alpha.resize((self.width, self.height))
            # Any coverage counts: small text and hairlines in large documents only reach a few
            # percent of a grid pixel, and a 50% threshold made them "cover nothing".
            solid = alpha.point(lambda v: 255 if v > 0 else 0)
            # Seam tolerance: adjacent shapes (traces, flat art) overlap by anti-aliasing / spline
            # slivers along shared edges. Thick shapes are eroded by one grid pixel so such slivers
            # do not count as overlaps; thin shapes (lines, hairlines) keep their full coverage.
            eroded = solid.filter(ImageFilter.MinFilter(3))
            area, eroded_area = solid.histogram()[255], eroded.histogram()[255]
            if area and eroded_area >= 0.5 * area:
                solid = eroded
            value = int.from_bytes(solid.convert("1").tobytes(), "big")
        except (RenderError, OSError, ValueError):
            self.failures += 1
            value = self.full  # unknown geometry: assume it covers everything (never reorders it)
        if not value and self._visible(leaf):
            # drawn, but invisible at this grid (or its font is missing): unknown geometry, so it
            # is never moved across anything rather than treated as covering nothing
            self.unresolved += 1
            value = self.full
        self.cache[leaf.index] = value
        return value

    def _visible(self, leaf: Leaf) -> bool:
        if self.doc.hidden(leaf.el, leaf.chain):
            return False
        return self.doc.paint_key(leaf.el, leaf.chain)[0] != "none"

    def layer_mask(self, layer: LayerOut) -> int:
        if layer.mask is None:
            acc = 0
            for lf in layer.leaves:
                acc |= self.mask(lf)
            layer.mask = acc
        return layer.mask

    def add(self, layer: LayerOut, leaf: Leaf) -> None:
        if layer.mask is not None:
            layer.mask |= self.mask(leaf)

    def overlaps_any(self, leaf: Leaf, layers: Iterable[LayerOut]) -> bool:
        m = self.mask(leaf)
        if not m:
            return False
        return any(m & self.layer_mask(lay) for lay in layers)


def group_leaves(leaves: list[Leaf], coverage: Coverage, strict: bool) -> tuple[list[LayerOut], dict[str, int]]:
    """Greedy z-order-safe assignment of leaves (document order) to keyed layers."""
    layers: list[LayerOut] = []
    last: dict[str, int] = {}
    count: Counter[str] = Counter()
    stats = {"conflicts": 0, "splits": 0}
    for leaf in leaves:
        li = last.get(leaf.key)
        if li is not None and li != len(layers) - 1:
            if coverage.overlaps_any(leaf, layers[li + 1 :]):
                stats["conflicts"] += 1
                if strict:
                    stats["splits"] += 1
                    li = None
        if li is None:
            count[leaf.key] += 1
            label = leaf.label if count[leaf.key] == 1 else f"{leaf.label} ({count[leaf.key]})"
            layers.append(LayerOut(leaf.key, label, [leaf]))
            last[leaf.key] = len(layers) - 1
        else:
            layers[li].leaves.append(leaf)
            coverage.add(layers[li], leaf)
    return layers, stats


# --- rebuild ------------------------------------------------------------------------------------


def _unique_id(base: str, taken: set[str]) -> str:
    ident, n = base, 2
    while ident in taken:
        ident = f"{base}-{n}"
        n += 1
    taken.add(ident)
    return ident


def _layer_group(ident: str, label: str) -> ET.Element:
    g = ET.Element(Q("g"), {"id": ident, INK_GROUPMODE: "layer", INK_LABEL: label})
    g.text = "\n"
    g.tail = "\n"
    return g


def rebuild(doc: SvgDoc, preamble: list[ET.Element], layers: list[LayerOut]) -> None:
    """Replace the root's children with the preamble followed by the layer groups."""
    root = doc.root
    for c in list(root):
        root.remove(c)
    root.text = "\n"
    for el in preamble:
        el.tail = "\n"
        root.append(el)
    taken = set(doc.ids)
    for lay in layers:
        if lay.promote and len(lay.leaves) == 1 and not lay.leaves[0].chain and local_name(lay.leaves[0].el.tag) == "g":
            g = lay.leaves[0].el
            lay.id = g.get("id") or _unique_id(f"layer-{slug(lay.label)}", taken)
            g.set("id", lay.id)
            g.set(INK_GROUPMODE, "layer")
            g.set(INK_LABEL, g.get(INK_LABEL) or lay.label)
            g.tail = "\n"
            root.append(g)
            continue
        lay.id = _unique_id(f"layer-{slug(lay.label)}", taken)
        g = _layer_group(lay.id, lay.label)
        stack: list[tuple[ET.Element, ET.Element]] = []  # (original group, wrapper)
        for leaf in lay.leaves:
            common = 0
            while common < len(stack) and common < len(leaf.chain) and stack[common][0] is leaf.chain[common]:
                common += 1
            del stack[common:]
            parent = stack[-1][1] if stack else g
            for orig in leaf.chain[common:]:
                w = ET.SubElement(parent, Q("g"), {k: v for k, v in orig.attrib.items() if k not in WRAPPER_DROP})
                stack.append((orig, w))
                parent = w
            leaf.el.tail = None
            parent.append(leaf.el)
        root.append(g)


# --- layerize --------------------------------------------------------------------------------------


def _single_wrapper_path(doc: SvgDoc) -> list[ET.Element]:
    """Chain of lone top-level wrapper groups worth descending into for by=group."""
    chain: list[ET.Element] = []
    node = doc.root
    while True:
        kids = [c for c in node if local_name(c.tag) and local_name(c.tag) not in NON_RENDERING]
        if len(kids) != 1 or local_name(kids[0].tag) != "g" or not doc.flattenable(kids[0]) or is_layer_group(kids[0]):
            return chain
        inner = [c for c in kids[0] if local_name(c.tag) and local_name(c.tag) not in NON_RENDERING]
        if len(inner) < 2 and not (len(inner) == 1 and local_name(inner[0].tag) == "g"):
            return chain
        chain.append(kids[0])
        node = kids[0]


def layerize(
    data: bytes | str,
    by: str = "group",
    mapping: Mapping[str, list[str]] | None = None,
    strict_z_order: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Rewrite an SVG into top-level layers. Returns (svg text, report)."""
    doc = SvgDoc.parse(data)
    report: dict[str, Any] = {"by": by, "notes": []}
    if by == "group":
        layers, preamble = _layers_by_group(doc, report)
    elif by in ("color", "colour"):
        preamble, leaves, dropped = doc.flatten()
        for lf in leaves:
            lf.key, lf.label = doc.paint_key(lf.el, lf.chain)
        layers, preamble = _grouped(doc, preamble, leaves, strict_z_order, report)
        if dropped:
            report["notes"].append(f"dropped {dropped} nested <title>/<desc>/<metadata> of flattened groups")
        _note_whole_group(doc, leaves, report)
    elif by == "mapping":
        if not mapping:
            raise SvgError("by='mapping' needs mapping={layer_name: [ids or selectors]}")
        rules: list[tuple[str, list[list[tuple[str, Compound]] | str]]] = []
        for name, sels in mapping.items():
            if isinstance(sels, str):
                sels = [sels]
            compiled: list[Any] = []
            for sel in sels:
                sel = str(sel).strip()
                if sel in doc.ids:
                    compiled.append(sel)  # a bare element id
                    continue
                for part in sel.split(","):
                    if part.strip():
                        compiled.append(parse_selector(part.strip()))
            rules.append((str(name), compiled))

        def match_rule(el: ET.Element) -> str | None:
            for name, compiled in rules:
                for c in compiled:
                    if isinstance(c, str):
                        if el.get("id") == c:
                            return name
                    elif selector_matches(c, el, doc.parent, doc.prop):
                        return name
            return None

        preamble, leaves, dropped = doc.flatten(stop=lambda el: match_rule(el) is not None)
        unmatched = 0
        for lf in leaves:
            name = match_rule(lf.el)
            if name is None:
                name = next((n for d in lf.el.iter() if local_name(d.tag) and (n := match_rule(d))), None)
            if name is None:
                unmatched += 1
                lf.key, lf.label = "\x00other", "Other"
            else:
                lf.key, lf.label = name, name
        layers, preamble = _grouped(doc, preamble, leaves, strict_z_order, report)
        used = {lf.label for lay in layers for lf in lay.leaves}
        missing = [n for n, _ in rules if n not in used]
        if missing:
            report["notes"].append(f"mapping layers that matched nothing: {missing}")
        if unmatched:
            report["notes"].append(f"{unmatched} element(s) matched no mapping entry and went to 'Other'")
    else:
        raise SvgError("by must be 'color', 'group' or 'mapping'")
    rebuild(doc, preamble, layers)
    report["layers"] = [
        {"id": lay.id, "label": lay.label, "elements": len(lay.leaves)} for lay in layers
    ]
    report["layer_count"] = len(layers)
    return serialize(doc.root), report


def _note_whole_group(doc: SvgDoc, leaves: list[Leaf], report: dict[str, Any]) -> None:
    """Say why nothing was split when the drawing is one group that must stay whole."""
    if len(leaves) == 1 and local_name(leaves[0].el.tag) == "g":
        why = doc.non_distributive(leaves[0].el)
        if why:
            report["notes"].append(
                f"the drawing is a single group kept whole ({why}): splitting it would change its appearance, "
                "so it is one layer"
            )


def _grouped(
    doc: SvgDoc, preamble: list[ET.Element], leaves: list[Leaf], strict: bool, report: dict[str, Any]
) -> tuple[list[LayerOut], list[ET.Element]]:
    coverage = Coverage(doc, max_side=384 if len(leaves) <= 2000 else 256)
    layers, stats = group_leaves(leaves, coverage, strict)
    report["z_order"] = {
        "strict": strict,
        "conflicts": stats["conflicts"],
        "split_layers": stats["splits"],
        "coverage_renders": coverage.renders,
        "coverage_grid": [coverage.width, coverage.height],
    }
    if coverage.unresolved:
        report["z_order"]["unresolved_coverage"] = coverage.unresolved
    if stats["conflicts"] and not strict:
        report["notes"].append(
            f"{stats['conflicts']} overlapping element(s) were moved across other colours/layers "
            "(strict_z_order=false): appearance may change - see 'appearance'"
        )
    elif stats["splits"]:
        report["notes"].append(
            f"{stats['splits']} extra layer(s) were opened so overlapping elements keep their stacking order"
        )
    return layers, preamble


def _layers_by_group(doc: SvgDoc, report: dict[str, Any]) -> tuple[list[LayerOut], list[ET.Element]]:
    wrappers = _single_wrapper_path(doc)
    container = wrappers[-1] if wrappers else doc.root
    if wrappers:
        report["notes"].append(
            f"descended into {len(wrappers)} wrapper group(s); their attributes are kept on each layer's content"
        )
    preamble: list[ET.Element] = [c for c in doc.root if local_name(c.tag) in NON_RENDERING]
    for w in wrappers:
        preamble += [c for c in w if local_name(c.tag) in NON_RENDERING]
    layers: list[LayerOut] = []
    run: list[Leaf] = []
    loose = 0
    index = 0
    chain = tuple(wrappers)

    def flush() -> None:
        nonlocal run, loose
        if run:
            loose += 1
            label = "Ungrouped" if loose == 1 else f"Ungrouped {loose}"
            layers.append(LayerOut(f"\x00loose{loose}", label, run))
            run = []

    n = 0
    for c in container:
        name = local_name(c.tag)
        if not name or name in NON_RENDERING:
            continue
        leaf = Leaf(c, chain, index)
        index += 1
        if name == "g":
            flush()
            n += 1
            label = c.get(INK_LABEL) or c.get("id") or f"Layer {n}"
            # a top-level group becomes the layer itself (no restructuring); inside wrappers it is
            # wrapped so the wrappers' transform / presentation attributes still apply
            layers.append(LayerOut(f"\x00g{n}", label, [leaf], promote=not wrappers))
        else:
            run.append(leaf)
    flush()
    if not any(not lay.key.startswith("\x00loose") for lay in layers):
        report["notes"].append("no groups found: everything is in one 'Ungrouped' layer - try by='color'")
    elif not wrappers and len(layers) == 1 and local_name(layers[0].leaves[0].el.tag) == "g":
        g = layers[0].leaves[0].el
        inner = [c for c in g if local_name(c.tag) and local_name(c.tag) not in NON_RENDERING]
        why = doc.non_distributive(g)
        if why and len(inner) > 1:
            report["notes"].append(
                f"the drawing is a single group kept whole ({why}): its sub-groups cannot become layers without "
                "changing its appearance"
            )
    return layers, preamble


# --- compose ----------------------------------------------------------------------------------------


_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)#([^)'\"]+)\1\s*\)")


def _sub_urls(text: str, ids: Mapping[str, str]) -> str:
    return _CSS_URL_RE.sub(lambda m: f"url(#{ids.get(m.group(2), m.group(2))})", text)


def rewrite_css(text: str, ids: Mapping[str, str], scope: str | None) -> str:
    """Rename #id selectors / url(#id) and scope every plain rule under ``scope``.

    ``svg`` / ``:root`` selectors are mapped onto the scope itself; @-rules are copied with
    only their url() references renamed. Declarations are never touched (so ``#fff`` colours
    stay colours even when an element happens to be called ``fff``).
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        brace = text.find("{", i)
        if brace == -1:
            out.append(text[i:])
            break
        prelude = text[i:brace]
        if prelude.strip().startswith("@"):
            depth, j = 0, brace
            while j < n:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(prelude + _sub_urls(text[brace : j + 1], ids))
            i = j + 1
            continue
        end = text.find("}", brace)
        end = n - 1 if end == -1 else end
        selectors = []
        for sel in prelude.split(","):
            sel = sel.strip()
            if not sel:
                continue
            sel = re.sub(r"#([\w-]+)", lambda m: "#" + ids.get(m.group(1), m.group(1)), sel)
            if scope:
                m = re.match(r"^(svg|:root)(?![\w-])", sel)
                sel = scope + sel[m.end() :] if m else f"{scope} {sel}"
            selectors.append(sel)
        out.append(", ".join(selectors) + " " + _sub_urls(text[brace : end + 1], ids) + "\n")
        i = end + 1
    return "".join(out)


def isolate_source(root: ET.Element, prefix: str, scope: str | None = None) -> None:
    """Make an SVG safe to merge into another: prefix every id (rewriting url(#id), href="#id"
    and CSS #id selectors) and scope its <style> rules under ``scope`` (e.g. '#layer-logo')."""
    ids = {el.get("id") for el in root.iter() if local_name(el.tag) and el.get("id")}
    mapping = {i: f"{prefix}{i}" for i in ids}
    for el in root.iter():
        if not local_name(el.tag):
            continue
        if el.get("id") in mapping:
            el.set("id", mapping[el.get("id")])
        for k, v in list(el.attrib.items()):
            if k in HREF_ATTRS and v.startswith("#") and v[1:] in mapping:
                el.set(k, "#" + mapping[v[1:]])
            elif "url(" in v:
                el.set(k, _sub_urls(v, mapping))
        if local_name(el.tag) == "style" and el.text:
            el.text = rewrite_css(el.text, mapping, scope)


def _fmt(v: float) -> str:
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _placement(
    vb: tuple[float, float, float, float], box: tuple[float, float, float, float], par: str | None
) -> str:
    """transform mapping a viewBox into a box, honouring preserveAspectRatio."""
    vx, vy, vw, vh = vb
    x, y, w, h = box
    par = (par or "xMidYMid meet").strip()
    if par.startswith("none"):
        sx, sy = w / vw, h / vh
        return f"matrix({_fmt(sx)} 0 0 {_fmt(sy)} {_fmt(x - vx * sx)} {_fmt(y - vy * sy)})"
    align, _, mode = par.partition(" ")
    s = max(w / vw, h / vh) if mode.strip() == "slice" else min(w / vw, h / vh)
    ax = {"xMin": 0.0, "xMid": 0.5, "xMax": 1.0}.get(align[:4], 0.5)
    ay = {"YMin": 0.0, "YMid": 0.5, "YMax": 1.0}.get(align[4:8], 0.5)
    tx = x + (w - vw * s) * ax - vx * s
    ty = y + (h - vh * s) * ay - vy * s
    return f"matrix({_fmt(s)} 0 0 {_fmt(s)} {_fmt(tx)} {_fmt(ty)})"


SVG_ROOT_GEOMETRY = {"width", "height", "viewBox", "x", "y", "preserveAspectRatio", "version", "id", "baseProfile"}


@dataclass(slots=True)
class ComposeLayer:
    name: str
    data: bytes
    mime: str
    opacity: float | None = None
    visible: bool = True
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    base_dir: Any = None  # the SVG source's folder: relative <image> links resolve against it


def compose(layers: list[ComposeLayer], width: float, height: float) -> tuple[str, list[dict[str, Any]]]:
    """One layered SVG: first layer at the bottom. Raster sources become <image> data URIs.

    SVG sources are clipped to their box (as a nested ``<svg>`` viewport would be, unless the
    source declares ``overflow="visible"``), and their linked local images are embedded so the
    composition does not depend on its folder. Raster sources are embedded upright (EXIF
    orientation applied). Per-layer ``warnings`` appear in the summary.
    """
    import base64

    from .imaging import ensure_png, image_size, normalize_raster_input

    root = ET.Element(
        Q("svg"),
        {"version": "1.1", "width": _fmt(width), "height": _fmt(height), "viewBox": f"0 0 {_fmt(width)} {_fmt(height)}"},
    )
    root.text = "\n"
    taken: set[str] = set()
    summary: list[dict[str, Any]] = []
    for i, spec in enumerate(layers):
        ident = _unique_id(f"layer-{slug(spec.name)}", taken)
        g = _layer_group(ident, spec.name)
        if spec.opacity is not None and spec.opacity < 1:
            g.set("opacity", _fmt(max(0.0, spec.opacity)))
        if not spec.visible:
            g.set("style", "display:none")
        info: dict[str, Any] = {"id": ident, "label": spec.name, "visible": spec.visible}
        layer_warnings: list[str] = []
        if spec.mime == "image/svg+xml":
            src = load_svg(spec.data)
            sw, sh, vb = doc_size(src)
            vb = vb or (0.0, 0.0, sw, sh)
            w, h = spec.width, spec.height
            if w is None and h is None:
                w, h = width, height
            elif w is None:
                w = h * sw / sh
            elif h is None:
                h = w * sh / sw
            box = (spec.x or 0.0, spec.y or 0.0, float(w), float(h))
            layer_warnings += inline_local_images(src, spec.base_dir)
            isolate_source(src, f"l{i}-", f"#{ident}")
            holder = g
            overflow = (prop(src, "overflow") or "").strip().lower()
            if overflow not in ("visible", "auto"):
                # the source's root <svg> clipped to its viewport; a plain <g> would let content
                # outside the viewBox (or a 'slice' overflow) paint over the other layers
                clip_id = _unique_id(f"{ident}-clip", taken)
                defs = ET.SubElement(g, Q("defs"))
                clip = ET.SubElement(defs, Q("clipPath"), {"id": clip_id})
                ET.SubElement(clip, Q("rect"), {"x": _fmt(box[0]), "y": _fmt(box[1]), "width": _fmt(box[2]), "height": _fmt(box[3])})
                holder = ET.SubElement(g, Q("g"), {"clip-path": f"url(#{clip_id})"})
            inner = ET.SubElement(holder, Q("g"), {k: v for k, v in src.attrib.items() if k not in SVG_ROOT_GEOMETRY and not k.startswith("{")})
            inner.set("transform", _placement(vb, box, src.get("preserveAspectRatio")))
            for c in list(src):
                if local_name(c.tag) in ("title", "metadata", "namedview"):
                    continue
                inner.append(c)
            info.update({"kind": "svg", "box": [_fmt(v) for v in box]})
        else:
            data, mime = spec.data, spec.mime
            fixed = normalize_raster_input(data, mime)
            if fixed is not None:
                data, mime, raster_notes = fixed
                info["notes"] = raster_notes
            if mime not in ("image/png", "image/jpeg"):
                data, mime = ensure_png(data), "image/png"
            pw, ph = image_size(data)
            w, h = spec.width, spec.height
            if w is None and h is None:
                w, h = float(pw), float(ph)
            elif w is None:
                w = h * pw / ph
            elif h is None:
                h = w * ph / pw
            uri = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
            ET.SubElement(
                g,
                Q("image"),
                {
                    "x": _fmt(spec.x or 0.0),
                    "y": _fmt(spec.y or 0.0),
                    "width": _fmt(float(w)),
                    "height": _fmt(float(h)),
                    "preserveAspectRatio": "none",
                    f"{{{XLINK_NS}}}href": uri,
                },
            )
            info.update({"kind": "raster", "pixels": [pw, ph], "box": [_fmt(spec.x or 0.0), _fmt(spec.y or 0.0), _fmt(float(w)), _fmt(float(h))]})
        if layer_warnings:
            info["warnings"] = layer_warnings
        root.append(g)
        summary.append(info)
    return serialize(root), summary


# --- appearance check ---------------------------------------------------------------------------


def appearance_delta(before: bytes | str, after: bytes | str, max_side: int = 384) -> dict[str, Any] | None:
    """Render both documents (over white) and compare: mean abs diff and changed-pixel fraction."""
    from PIL import Image, ImageChops

    from .render import RenderError, render_svg

    w, h, _vb = doc_size(load_svg(before))
    width = max(1, round(w * max_side / max(w, h)))
    try:
        a = Image.open(_stdio.BytesIO(render_svg(before, width=width, background="white"))).convert("RGB")
        b = Image.open(_stdio.BytesIO(render_svg(after, width=width, background="white"))).convert("RGB")
    except (RenderError, OSError) as exc:
        return {"error": str(exc)}
    if b.size != a.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a, b)
    r, g, bl = diff.split()
    peak = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    hist = peak.histogram()
    total = a.width * a.height or 1
    mean = sum(i * n for i, n in enumerate(hist)) / total
    changed = sum(hist[25:]) / total
    return {"mean_abs_diff": round(mean, 4), "changed_fraction": round(changed, 6), "grid": [a.width, a.height]}


# --- inspect -------------------------------------------------------------------------------------

_DECIMALS_RE = re.compile(r"\d\.(\d{4,})")
_PATH_CMD_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")


def inspect(data: bytes) -> dict[str, Any]:
    """Structure, palette, layers, text, rasters, complexity and common problems."""
    problems: list[str] = []
    info: dict[str, Any] = {"bytes": len(data)}
    try:
        root = load_svg(data)
    except SvgError as exc:
        return {"well_formed": False, "error": str(exc), "bytes": len(data), "problems": [str(exc)]}
    info["well_formed"] = True
    w, h, vb = doc_size(root)
    info["root"] = {
        "width": root.get("width"),
        "height": root.get("height"),
        "viewBox": root.get("viewBox"),
        "preserveAspectRatio": root.get("preserveAspectRatio"),
        "size_px": [round(w, 2), round(h, 2)],
    }
    if vb is None:
        problems.append("no viewBox: the drawing will not scale cleanly (svg_optimize adds one from width/height)")
    if root.get("width") is None or root.get("height") is None:
        problems.append("width/height missing: renderers fall back to the viewBox or 300x150")

    all_els = [el for el in root.iter() if local_name(el.tag)]
    tags = Counter(local_name(el.tag) for el in all_els)
    info["element_count"] = len(all_els)
    info["counts_by_tag"] = dict(tags.most_common(25))
    path_data = [el.get("d") or "" for el in all_els if local_name(el.tag) == "path"]
    segments = sum(len(_PATH_CMD_RE.findall(d)) for d in path_data)
    info["path_count"] = len(path_data)
    info["path_segments"] = segments
    info["path_data_bytes"] = sum(len(d) for d in path_data)

    def depth(el: ET.Element, d: int = 0) -> int:
        kids = [c for c in el if local_name(c.tag)]
        return max([depth(c, d + 1) for c in kids], default=d)

    info["max_depth"] = depth(root)
    sheet = StyleSheet(root)
    pal = palette(all_els, sheet=sheet)
    info["palette"] = pal[:24]
    info["color_count"] = len(pal)
    grads = [el.get("id") for el in all_els if local_name(el.tag) in ("linearGradient", "radialGradient")]
    info["gradients"] = len(grads)

    lay = describe_layers(root)
    info["layers"] = lay

    texts = [el for el in all_els if local_name(el.tag) == "text"]
    fonts = sorted({f for el in all_els if (f := prop(el, "font-family", sheet))})
    info["text"] = {
        "count": len(texts),
        "samples": ["".join(t.itertext()).strip()[:80] for t in texts[:8]],
        "fonts": fonts[:12],
    }
    if texts:
        problems.append(
            f"{len(texts)} <text> element(s): rendering depends on installed fonts {fonts[:4] or ''}; "
            "convert to outlines for logos/print"
        )

    rasters = []
    external = []
    for el in all_els:
        href = next((el.get(a) for a in HREF_ATTRS if el.get(a)), None)
        if not href:
            continue
        if local_name(el.tag) == "image":
            if href.startswith("data:"):
                head = href.split(",", 1)[0]
                rasters.append({"id": el.get("id"), "mime": head[5:].split(";")[0], "chars": len(href),
                                "width": el.get("width"), "height": el.get("height")})
            else:
                rasters.append({"id": el.get("id"), "href": href.split("?", 1)[0][:120]})
        if re.match(r"^(https?:)?//", href):
            external.append(href.split("?", 1)[0][:120])
    info["embedded_rasters"] = rasters
    if rasters:
        problems.append(f"{len(rasters)} raster image(s) inside the SVG: not resolution-independent")
    if external:
        info["external_refs"] = external[:20]
        problems.append(f"{len(external)} external reference(s): the file is not self-contained")
    styles_text = " ".join(el.text or "" for el in all_els if local_name(el.tag) == "style")
    if "@import" in styles_text or re.search(r"url\(\s*['\"]?https?:", styles_text):
        problems.append("<style> imports external resources")

    if tags.get("script") or any(k.lower().startswith("on") for el in all_els for k in el.attrib):
        problems.append("contains <script> or on* event attributes: unsafe for delivery; remove them")
    if tags.get("foreignObject"):
        problems.append("<foreignObject> is not supported by most design tools and PDF export")
    ids = [el.get("id") for el in all_els if el.get("id")]
    dupes = sorted(i for i, n in Counter(ids).items() if n > 1)
    if dupes:
        problems.append(f"duplicate ids: {dupes[:10]}")
    referenced: set[str] = set()
    for el in all_els:
        referenced |= refs_in(el)
    broken = sorted(r for r in referenced if r not in set(ids))
    if broken:
        problems.append(f"references to missing ids: {broken[:10]}")
    if tags.get("filter"):
        problems.append(f"{tags['filter']} <filter>(s): raster effects may export differently to PDF/other tools")
    if tags.get("mask") or tags.get("clipPath"):
        info["masks_and_clips"] = tags.get("mask", 0) + tags.get("clipPath", 0)
    editor = sum(1 for el in all_els if local_name(el.tag) in ("metadata", "namedview")) + sum(
        1 for el in all_els for k in el.attrib if k.startswith(f"{{{SODIPODI_NS}}}")
    )
    if editor:
        problems.append("editor cruft (metadata / sodipodi data): svg_optimize removes it")
    long_decimals = sum(len(_DECIMALS_RE.findall(d)) for d in path_data)
    if long_decimals > 50:
        problems.append(f"{long_decimals} coordinates with 4+ decimals: svg_optimize(precision=2) shrinks the file")
    hidden = sum(1 for el in all_els if is_hidden(el, sheet) and not is_layer_group(el))
    if hidden:
        info["hidden_elements"] = hidden
    empty_groups = sum(1 for el in all_els if local_name(el.tag) == "g" and not len(el))
    if empty_groups:
        problems.append(f"{empty_groups} empty group(s)")
    if len(pal) > 48:
        problems.append(f"{len(pal)} distinct colours: noisy for a vector (re-trace with fewer colours or merge)")
    score = len(all_els) + segments // 4 + info["path_data_bytes"] // 2000
    level = "low" if score < 300 else "medium" if score < 3000 else "high" if score < 20000 else "very high"
    info["complexity"] = {"score": score, "level": level}
    if level in ("high", "very high"):
        problems.append(f"{level} complexity ({len(all_els)} elements, {segments} path segments): slow to edit/render")
    info["problems"] = problems
    return info
