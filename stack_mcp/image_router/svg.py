"""Local, dependency-free SVG optimisation.

Only transformations that cannot change what renders (beyond the requested
number rounding) are applied:

* parse with xml.etree (rejects malformed XML and internal ENTITY declarations);
* drop comments, processing instructions, ``<metadata>`` and editor cruft
  (Inkscape, Sodipodi, Sketch elements and attributes) - except the layer markers
  ``inkscape:groupmode`` / ``inkscape:label`` on groups, which carry the layer structure
  (pass ``keep_layers=False`` to drop them too);
* round numbers in path data and numeric geometry attributes to ``precision``
  decimals (arc flags and integers are left untouched). Transform lists are rounded per
  role, as svgo does: translations (and rotation centres) are coordinates and get
  ``precision`` decimals, while matrix / scale / rotate / skew coefficients keep at least
  5 significant digits (rounding 0.26458333 to 0.26 would shrink a subtree by 1.7%).
  Unit-interval values (opacities, gradient stop offsets) keep at least 2 decimals, so a
  low precision never turns opacity 0.5 into 0;
* add ``viewBox="0 0 W H"`` from unit-less/px width and height when missing;
* drop whitespace-only text nodes outside text content and serialise compactly.
"""

from __future__ import annotations

import io as _stdio
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
LAYER_ATTRS = frozenset({f"{{{INKSCAPE_NS}}}groupmode", f"{{{INKSCAPE_NS}}}label"})
EDITOR_NAMESPACES = frozenset(
    {
        "http://www.inkscape.org/namespaces/inkscape",
        "http://inkscape.sourceforge.net/DTD/sodipodi-0.dtd",
        "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
        "http://www.bohemiancoding.com/sketch/ns",
    }
)
# Attributes holding plain numbers / number lists / lengths (style is left alone on purpose).
NUMERIC_ATTRS = frozenset(
    """x y x1 y1 x2 y2 cx cy r rx ry fx fy fr dx dy width height points viewBox
    stroke-width stroke-dashoffset stroke-dasharray stroke-miterlimit font-size
    letter-spacing word-spacing refX refY markerWidth markerHeight textLength startOffset radius""".split()
)
# Transform lists: rounded per role (see round_transform).
TRANSFORM_ATTRS = frozenset({"transform", "gradientTransform", "patternTransform"})
# Values in 0..1 (and filter coefficients): at least UNIT_DECIMALS decimals whatever the precision.
UNIT_ATTRS = frozenset(
    """opacity fill-opacity stroke-opacity stop-opacity flood-opacity offset k k1 k2 k3 k4 scale
    baseFrequency stdDeviation""".split()
)
UNIT_DECIMALS = 2
COEFFICIENT_DIGITS = 5  # significant digits kept for transform coefficients
TEXT_TAGS = frozenset({"text", "tspan", "textPath", "style", "script", "title", "desc"})

_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_CMDS = frozenset("MmLlHhVvCcSsQqTtAaZz")


class SvgError(ValueError):
    """Input is not a well-formed SVG document."""


@dataclass(slots=True)
class SvgStats:
    bytes_in: int
    bytes_out: int
    removed_elements: int
    removed_attributes: int
    added_viewbox: bool


def _fmt(token: str, precision: int) -> str:
    """Round one numeric token; integers (and arc flags) stay byte-identical."""
    if "." not in token and "e" not in token and "E" not in token:
        return token.lstrip("+") or token
    value = round(float(token), precision)
    text = f"{value:.{precision}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", "", "-"):
        text = "0"
    return text


def round_path(d: str, precision: int) -> str:
    """Round path data, respecting single-character arc flags (A/a args 4 and 5)."""
    out: list[str] = []
    i, n = 0, len(d)
    cmd: str | None = None
    arg = 0
    while i < n:
        c = d[i]
        if c in _PATH_CMDS:
            cmd, arg = c, 0
            out.append(c)
            i += 1
            continue
        if c in " \t\r\n,":
            i += 1
            continue
        if cmd in ("A", "a") and arg % 7 in (3, 4) and c in "01":
            tok = c
            i += 1
        else:
            m = _NUM_RE.match(d, i)
            if not m:
                raise SvgError(f"unparseable path data near {d[i:i + 12]!r}")
            tok = _fmt(m.group(), precision)
            i = m.end()
        arg += 1
        if out and out[-1][-1] not in _PATH_CMDS and not tok.startswith("-"):
            out.append(" ")
        out.append(tok)
    return "".join(out)


def _fmt_significant(token: str, digits: int, min_decimals: int) -> str:
    """Round one coefficient to ``digits`` significant digits (never fewer than ``min_decimals``
    decimals); integers stay byte-identical."""
    if "." not in token and "e" not in token and "E" not in token:
        return token.lstrip("+") or token
    value = float(token)
    if value == 0:
        return "0"
    decimals = max(min_decimals, digits - 1 - math.floor(math.log10(abs(value))))
    return _fmt(token, min(decimals, 12))


_TRANSFORM_FN_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
# Which arguments of each transform function are coordinates (rounded like coordinates); the
# others are coefficients (significant digits kept).
_COORD_ARGS = {"matrix": {4, 5}, "translate": {0, 1}, "scale": set(), "rotate": {1, 2}, "skewX": set(), "skewY": set()}


def round_transform(value: str, precision: int) -> str:
    """Round a transform list: translations at ``precision`` decimals, coefficients at
    ``COEFFICIENT_DIGITS`` significant digits. Unknown syntax is returned unchanged."""
    out: list[str] = []
    pos = 0
    for m in _TRANSFORM_FN_RE.finditer(value):
        if value[pos : m.start()].strip(" \t\r\n,"):
            return value  # something we do not understand between functions
        fn, args = m.group(1), m.group(2)
        nums = _NUM_RE.findall(args)
        if _NUM_RE.sub("", args).strip(" \t\r\n,"):
            return value
        coords = _COORD_ARGS[fn]
        parts = [_fmt(t, precision) if i in coords else _fmt_significant(t, COEFFICIENT_DIGITS, precision)
                 for i, t in enumerate(nums)]
        out.append(f"{fn}({' '.join(parts)})")
        pos = m.end()
    if value[pos:].strip(" \t\r\n,") or not out:
        return value
    return " ".join(out)


def round_numbers(value: str, precision: int) -> str:
    """Round every decimal number inside an attribute value; keeps units and separators."""
    parts: list[str] = []
    last = 0
    for m in _NUM_RE.finditer(value):
        start = m.start()
        between = value[last:start]
        tok = _fmt(m.group(), precision)
        # Two numbers that touched (e.g. "1.5.5") must stay distinct after rounding.
        if not between and parts and parts[-1] and (parts[-1][-1].isdigit() or parts[-1][-1] == ".") and not tok.startswith("-"):
            between = " "
        parts.append(between)
        parts.append(tok)
        last = m.end()
    parts.append(value[last:])
    return "".join(parts)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _ns(tag: str) -> str | None:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else None


def _length_px(value: str | None) -> str | None:
    if not value:
        return None
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(px)?\s*", value)
    return m.group(1) if m else None


def optimize_svg(data: bytes | str, precision: int = 2, keep_layers: bool = True) -> tuple[str, SvgStats]:
    if not 0 <= precision <= 8:
        raise SvgError("precision must be between 0 and 8")
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if b"<!ENTITY" in raw:
        raise SvgError("SVG declares XML entities; refusing to process it")

    # Collect namespace prefixes so the output keeps readable prefixes (xlink:href, ...).
    namespaces: dict[str, str] = {}
    try:
        for _event, (prefix, uri) in ET.iterparse(_stdio.BytesIO(raw), events=("start-ns",)):
            namespaces.setdefault(prefix, uri)
        root = ET.fromstring(raw)  # comments and PIs are discarded by the default parser
    except ET.ParseError as exc:
        raise SvgError(f"not well-formed XML: {exc}") from None
    if _local(root.tag) != "svg":
        raise SvgError(f"root element is <{_local(root.tag)}>, not <svg>")

    for prefix, uri in namespaces.items():
        if uri in EDITOR_NAMESPACES:
            continue
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass  # reserved prefixes like ns0
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    ET.register_namespace("inkscape", INKSCAPE_NS)

    removed_el = removed_attr = 0

    def walk(el: ET.Element, in_text: bool) -> None:
        nonlocal removed_el, removed_attr
        for child in list(el):
            ns = _ns(child.tag)
            if _local(child.tag) == "metadata" or (ns and ns in EDITOR_NAMESPACES):
                # keep the tail text (it belongs to the parent's content)
                if child.tail and child.tail.strip():
                    prev_tail = child.tail
                    idx = list(el).index(child)
                    if idx > 0:
                        sib = el[idx - 1]
                        sib.tail = (sib.tail or "") + prev_tail
                    else:
                        el.text = (el.text or "") + prev_tail
                el.remove(child)
                removed_el += 1
                continue
            walk(child, in_text or _local(child.tag) in TEXT_TAGS)
        for name in list(el.attrib):
            ns = _ns(name)
            if ns and ns in EDITOR_NAMESPACES:
                if keep_layers and name in LAYER_ATTRS and _local(el.tag) == "g":
                    continue
                del el.attrib[name]
                removed_attr += 1
                continue
            local = _local(name)
            value = el.attrib[name]
            if local == "d" and ns is None:
                try:
                    el.attrib[name] = round_path(value, precision)
                except SvgError:
                    pass  # leave unknown syntax untouched rather than risk breaking it
            elif local in TRANSFORM_ATTRS and ns is None:
                el.attrib[name] = round_transform(value, precision)
            elif local in UNIT_ATTRS and ns is None:
                el.attrib[name] = round_numbers(value, max(precision, UNIT_DECIMALS))
            elif local in NUMERIC_ATTRS and ns is None:
                el.attrib[name] = round_numbers(value, precision)
        if not in_text and _local(el.tag) not in TEXT_TAGS:
            if el.text is not None and not el.text.strip():
                el.text = None
            for child in el:
                if child.tail is not None and not child.tail.strip():
                    child.tail = None

    walk(root, False)
    root.tail = None

    added_viewbox = False
    if "viewBox" not in root.attrib:
        w, h = _length_px(root.attrib.get("width")), _length_px(root.attrib.get("height"))
        if w and h:
            root.set("viewBox", f"0 0 {_fmt(w, precision)} {_fmt(h, precision)}")
            added_viewbox = True

    text = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    out = text + "\n"
    stats = SvgStats(len(raw), len(out.encode("utf-8")), removed_el, removed_attr, added_viewbox)
    return out, stats
