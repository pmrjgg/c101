"""SVG rasterisation (resvg) and vector PDF export with layers (svglib + reportlab + pikepdf).

* :func:`render_svg` - resvg-py (MIT; resvg itself is MIT/Apache-2.0): PNG bytes; text, gradients,
  transforms, masks and filters are rendered; system fonts are loaded for text. Physical units
  (mm, cm, in, pt, pc) are resolved at the CSS reference 96 dpi (resvg-py's default dpi of 0 would
  make every such length 0 px and the SVG unrenderable). The output size is bounded
  (:func:`bounded_width`, :data:`MAX_RENDER_PIXELS`) so one SVG with huge declared dimensions
  cannot exhaust memory.
* :func:`svg_to_pdf_layers` - svglib (LGPL-3.0, used unmodified as a library) turns SVG into
  ReportLab drawings (BSD); each top-level layer is drawn inside its own marked-content sequence
  ``/OC /ocN BDC ... EMC`` and pikepdf (MPL-2.0) adds one Optional Content Group per layer
  (``/OCProperties`` with ``/Order``, ``/ON``/``/OFF``), so the layers are toggleable in
  Acrobat/Illustrator. Raster ``<image>`` elements are drawn as image XObjects with their alpha
  (soft mask) preserved. A layer's group opacity (svglib ignores ``opacity``) is applied by
  drawing the layer into a Form XObject marked as a transparency group and painting it with that
  constant alpha. Linked images are embedded first; what svglib still cannot draw (masks,
  filters, patterns, nested group opacity, glyphs missing from the PDF font) is returned as
  warnings. A non-layered SVG becomes a single-layer PDF (no OCGs).
"""

from __future__ import annotations

import io as _stdio
import logging
import math
import re
import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RenderError(RuntimeError):
    """The SVG could not be rasterised or converted."""


# --- raster -----------------------------------------------------------------------------------

RENDER_DPI = 96.0  # CSS reference pixel: matches svgtools._num / doc_size
DEFAULT_MAX_SIDE = 4096  # longest side when no width is given (svg_render, SVG inputs to raster ops)
SOFT_MAX_PIXELS = 64_000_000  # cap applied to requested widths (svg_render) with a note
MAX_RENDER_PIXELS = 128_000_000  # hard limit inside render_svg


def natural_size(svg: str | bytes) -> tuple[float, float] | None:
    """The SVG's own size in px (96 dpi), or None when it cannot be parsed."""
    from .svgtools import doc_size, load_svg

    try:
        w, h, _vb = doc_size(load_svg(svg))
    except Exception:
        return None
    return (w, h) if w > 0 and h > 0 else None


def bounded_width(
    svg: str | bytes,
    width: int | None,
    *,
    max_side: int = DEFAULT_MAX_SIDE,
    max_pixels: int = SOFT_MAX_PIXELS,
) -> tuple[int | None, str | None]:
    """The width to render at (None = natural size) and a note when it had to be reduced.

    Without a width, a drawing whose declared size exceeds ``max_side`` px on its longest side
    (or ``max_pixels`` in all) is rendered smaller; a requested width is reduced only when the
    height it implies would push the image past ``max_pixels``.
    """
    size = natural_size(svg)
    if size is None:
        return width, None
    dw, dh = size
    if width:
        h = width * dh / dw
        if width * h <= max_pixels:
            return width, None
        w2 = max(1, int(math.sqrt(max_pixels * dw / dh)))
        return w2, (f"width {width} would make a {width}x{round(h)} image; rendered at {w2}x{round(w2 * dh / dw)} "
                    f"(limit {max_pixels:,} pixels)")
    scale = min(1.0, max_side / max(dw, dh), math.sqrt(max_pixels / (dw * dh)))
    if scale >= 1.0:
        return None, None
    w2 = max(1, int(dw * scale))
    return w2, (f"the SVG declares {round(dw)}x{round(dh)} px; rendered at {w2}x{max(1, round(dh * scale))} "
                f"(pass width for another size, up to the {max_pixels:,}-pixel limit)")


def render_svg(
    svg: str | bytes,
    *,
    width: int | None = None,
    height: int | None = None,
    background: str | None = None,
    resources_dir: str | Path | None = None,
    system_fonts: bool = True,
    max_pixels: int = MAX_RENDER_PIXELS,
) -> bytes:
    """Rasterise SVG text to PNG bytes. Only one of width/height is used (aspect kept)."""
    import resvg_py

    text = svg.decode("utf-8-sig") if isinstance(svg, bytes) else svg.lstrip("\ufeff")
    size = natural_size(text)
    if size is not None:
        dw, dh = size
        if width:
            out_w, out_h = float(width), width * dh / dw
        elif height:
            out_w, out_h = height * dw / dh, float(height)
        else:
            out_w, out_h = dw, dh
        if out_w * out_h > max_pixels:
            raise RenderError(
                f"rendering would make a {round(out_w)}x{round(out_h)} image (over {max_pixels:,} pixels); "
                "pass a smaller width"
            )
    kwargs: dict[str, Any] = {"svg_string": text, "skip_system_fonts": not system_fonts, "dpi": RENDER_DPI}
    if width:
        kwargs["width"] = int(width)
    elif height:
        kwargs["height"] = int(height)
    if background:
        kwargs["background"] = background
    if resources_dir:
        kwargs["resources_dir"] = str(resources_dir)
    try:
        return bytes(resvg_py.svg_to_bytes(**kwargs))
    except BaseException as exc:  # resvg-py raises plain exceptions or pyo3 PanicException
        if isinstance(exc, KeyboardInterrupt | SystemExit):
            raise
        raise RenderError(f"resvg could not render the SVG: {type(exc).__name__}: {exc}") from None


# --- PDF --------------------------------------------------------------------------------------

PAGE_SIZES_PT = {"a4": (595.2756, 841.8898), "letter": (612.0, 792.0)}
MM_TO_PT = 72.0 / 25.4


def page_size_pt(spec: str | None, drawing_wh: tuple[float, float]) -> tuple[float, float] | None:
    """'auto' -> None (page = drawing); 'A4'/'letter' (orientation follows the drawing); 'WxHmm'."""
    if not spec or spec.strip().lower() == "auto":
        return None
    s = spec.strip().lower().replace(" ", "")
    if s in PAGE_SIZES_PT:
        w, h = PAGE_SIZES_PT[s]
        if drawing_wh[0] > drawing_wh[1]:
            w, h = h, w  # landscape drawing -> landscape page
        return w, h
    m = re.fullmatch(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)mm", s)
    if m:
        return float(m.group(1)) * MM_TO_PT, float(m.group(2)) * MM_TO_PT
    raise RenderError(f"page_size {spec!r} not understood; use auto, A4, letter or WxHmm (e.g. 210x297mm)")


def _renderer_class():
    """reportlab's PDF renderer, drawing images as XObjects with their alpha preserved."""
    import os

    from reportlab.graphics.renderPDF import _PDFRenderer
    from reportlab.lib.utils import ImageReader

    class AlphaPDFRenderer(_PDFRenderer):
        def drawImage(self, image):  # noqa: N802 - reportlab API
            path = image.path
            if path is None:
                return
            if hasattr(path, "mode") or (isinstance(path, str) and os.path.exists(path)):
                self._canvas.drawImage(
                    ImageReader(path), image.x, image.y, image.width, image.height, mask="auto"
                )

    return AlphaPDFRenderer


_SVGLIB_LOCK = threading.Lock()
# Nodes svglib skips that do not paint anything anyway, or whose uses svgtools.prepare_for_pdf
# already reports (a <mask>/<filter>/<pattern> definition only matters where it is referenced).
_BENIGN_IGNORED = frozenset(
    {"title", "desc", "metadata", "namedview", "style", "script", "defs", "mask", "filter", "pattern", "foreignObject"}
)


class _SvglibLog(logging.Handler):
    """Collects what svglib skipped or failed on during one conversion."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.ignored: Counter[str] = Counter()
        self.problems: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return
        if msg.startswith("Ignoring node: "):
            node = msg.split(": ", 1)[1].strip()
            if node.rsplit(":", 1)[-1] not in _BENIGN_IGNORED:
                self.ignored[node] += 1
        elif record.levelno >= logging.WARNING and msg not in self.problems:
            self.problems.append(msg[:300])


@contextmanager
def _svglib_capture():
    """Route svglib's log records into a collector (not stderr) for the duration of a conversion."""
    logger = logging.getLogger("svglib")
    handler = _SvglibLog()
    with _SVGLIB_LOCK:
        old = (logger.level, logger.propagate)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.addHandler(handler)
        try:
            yield handler
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old[0])
            logger.propagate = old[1]


def svg_to_drawing(svg_text: str):
    """svglib Drawing for SVG text (raises RenderError on failure)."""
    from svglib.svglib import svg2rlg

    try:
        drawing = svg2rlg(_stdio.BytesIO(svg_text.encode("utf-8")))
    except Exception as exc:
        raise RenderError(f"svglib could not convert the SVG: {type(exc).__name__}: {exc}") from None
    if drawing is None:
        raise RenderError("svglib could not convert the SVG (empty drawing)")
    return drawing


def _missing_glyphs(drawing) -> list[tuple[str, str]]:
    """(text sample, font) for strings whose characters the PDF font cannot show.

    svglib maps fonts to the PDF standard fonts (WinAnsi: Latin-1-ish) unless it finds a
    TrueType file; text outside that set comes out as boxes or wrong glyphs.
    """
    from reportlab.graphics.shapes import String
    from reportlab.pdfbase import pdfmetrics

    out: list[tuple[str, str]] = []
    stack = [drawing]
    while stack:
        node = stack.pop()
        if isinstance(node, String):
            text = node.text or ""
            font_name = getattr(node, "fontName", "") or ""
            try:
                font = pdfmetrics.getFont(font_name)
            except Exception:
                font = None
            face = getattr(font, "face", None)
            char_map = getattr(face, "charToGlyph", None)
            if isinstance(char_map, dict) and char_map:
                bad = [c for c in text if not c.isspace() and ord(c) not in char_map]
            else:
                bad = []
                for c in text:
                    try:
                        c.encode("cp1252")
                    except UnicodeEncodeError:
                        bad.append(c)
                if font_name in ("ZapfDingbats", "Symbol"):
                    bad = [c for c in text if not c.isspace()]
            if bad:
                out.append((text[:40], font_name))
        stack.extend(getattr(node, "contents", []) or [])
    return out


@dataclass(slots=True)
class PdfLayer:
    label: str
    svg_text: str  # a full SVG document that draws only this layer
    visible: bool = True
    opacity: float = 1.0  # group opacity of the whole layer (transparency group + constant alpha)


def draw_pdf(
    units: list[PdfLayer],
    *,
    page_size: str | None = "auto",
    title: str | None = None,
    layered: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    """Draw each unit in order on one page; returns (pdf bytes, stats).

    With ``layered`` every unit is wrapped in ``/OC /ocN BDC ... EMC`` and gets an OCG. A unit
    with ``opacity`` < 1 is drawn into a Form XObject that is marked as a transparency group and
    painted with that constant alpha, so it composites as one group (as SVG group opacity does).
    ``stats['warnings']`` lists what svglib skipped and text the PDF fonts cannot show.
    """
    from reportlab.graphics.renderbase import renderScaledDrawing
    from reportlab.pdfgen.canvas import Canvas

    if not units:
        raise RenderError("nothing to draw")
    warnings: list[str] = []
    ignored: Counter[str] = Counter()
    problems: list[str] = []
    with _svglib_capture() as log:
        drawings = [renderScaledDrawing(svg_to_drawing(u.svg_text)) for u in units]
    ignored.update(log.ignored)
    problems += log.problems
    dw, dh = float(drawings[0].width), float(drawings[0].height)
    if dw <= 0 or dh <= 0:
        raise RenderError("the SVG has no usable size (set width/height or a viewBox)")
    page = page_size_pt(page_size, (dw, dh))
    pw, ph = page or (dw, dh)
    scale = min(pw / dw, ph / dh) if page else 1.0
    tx, ty = (pw - dw * scale) / 2, (ph - dh * scale) / 2

    buf = _stdio.BytesIO()
    canvas = Canvas(buf, pagesize=(pw, ph), pageCompression=1)
    if title:
        canvas.setTitle(title)
    canvas.setCreator("claude-stack image server")
    renderer_cls = _renderer_class()
    forms: list[str] = []
    for i, (unit, drawing) in enumerate(zip(units, drawings, strict=True)):
        if unit.opacity < 1.0:
            name = f"unit{i}"
            canvas.beginForm(name, 0, 0, max(dw, float(drawing.width)), max(dh, float(drawing.height)))
            renderer_cls().draw(drawing, canvas, 0, 0, showBoundary=False)
            canvas.endForm()
            forms.append(name)
    canvas.saveState()
    if page:
        canvas.transform(scale, 0, 0, scale, tx, ty)
    for i, (unit, drawing) in enumerate(zip(units, drawings, strict=True)):
        if layered:
            canvas.addLiteral(f"/OC /oc{i} BDC")
        if unit.opacity < 1.0:
            canvas.saveState()
            canvas.setFillAlpha(unit.opacity)
            canvas.setStrokeAlpha(unit.opacity)
            canvas.doForm(f"unit{i}")
            canvas.restoreState()
        else:
            renderer_cls().draw(drawing, canvas, 0, 0, showBoundary=False)
        if layered:
            canvas.addLiteral("EMC")
    canvas.restoreState()
    canvas.showPage()
    canvas.save()
    pdf = buf.getvalue()
    stats: dict[str, Any] = {"page_pt": [round(pw, 2), round(ph, 2)], "scale": round(scale, 4), "layers": 0}
    if forms:
        pdf = mark_transparency_groups(pdf, forms)
    if layered:
        pdf = add_ocgs(pdf, [(u.label, u.visible) for u in units])
        stats["layers"] = len(units)
    glyphs = [g for d in drawings for g in _missing_glyphs(d)]
    if glyphs:
        samples = ", ".join(f"{t!r} ({f})" for t, f in glyphs[:4])
        warnings.append(
            f"{len(glyphs)} text run(s) use characters the PDF font cannot show ({samples}): convert the text to "
            "outlines, or use a font family svglib can find as a TrueType file"
        )
    if ignored:
        listed = ", ".join(f"<{n}> x{c}" for n, c in ignored.most_common(8))
        warnings.append(f"svglib skipped {listed}: those parts are missing from the PDF")
    if problems:
        warnings.append("svglib reported: " + "; ".join(problems[:5]))
    stats["warnings"] = warnings
    return pdf, stats


def mark_transparency_groups(pdf: bytes, forms: list[str]) -> bytes:
    """Mark the named Form XObjects as transparency groups, so a constant alpha painted with them
    applies to each form as a whole (SVG group opacity) rather than to every object inside."""
    import pikepdf

    with pikepdf.open(_stdio.BytesIO(pdf)) as doc:
        xobjects = doc.pages[0].obj.get("/Resources", {}).get("/XObject", {})
        for key in list(xobjects.keys()):
            if any(key.endswith(f".{name}") or key == f"/{name}" for name in forms):
                xobjects[key].Group = pikepdf.Dictionary(Type=pikepdf.Name.Group, S=pikepdf.Name.Transparency)
        out = _stdio.BytesIO()
        doc.save(out)
        return out.getvalue()


def add_ocgs(pdf: bytes, layers: list[tuple[str, bool]]) -> bytes:
    """Register one OCG per marked-content tag /ocN on page 1 and the catalog's /OCProperties."""
    import pikepdf
    from pikepdf import Array, Dictionary, Name, String

    with pikepdf.open(_stdio.BytesIO(pdf)) as doc:
        ocgs = [doc.make_indirect(Dictionary(Type=Name.OCG, Name=String(label))) for label, _ in layers]
        page = doc.pages[0]
        resources = page.obj.get("/Resources")
        if resources is None:
            resources = Dictionary()
            page.obj.Resources = resources
        props = Dictionary()
        for i, ocg in enumerate(ocgs):
            props[f"/oc{i}"] = ocg
        resources.Properties = props
        on = [o for o, (_, vis) in zip(ocgs, layers, strict=True) if vis]
        off = [o for o, (_, vis) in zip(ocgs, layers, strict=True) if not vis]
        default = Dictionary(
            Name=String("Layers"),
            Order=Array(ocgs),
            ON=Array(on),
            OFF=Array(off),
            BaseState=Name.ON,
        )
        doc.Root.OCProperties = Dictionary(OCGs=Array(ocgs), D=default)
        doc.Root.PageMode = Name.UseOC
        out = _stdio.BytesIO()
        doc.save(out)
        return out.getvalue()


def pdf_layer_names(pdf_path_or_bytes: str | Path | bytes) -> list[str]:
    """Labels of the OCGs listed in /OCProperties (empty for a non-layered PDF)."""
    import pikepdf

    src = _stdio.BytesIO(pdf_path_or_bytes) if isinstance(pdf_path_or_bytes, bytes) else pdf_path_or_bytes
    with pikepdf.open(src) as doc:
        ocp = doc.Root.get("/OCProperties")
        if ocp is None:
            return []
        return [str(o.get("/Name")) for o in ocp.OCGs]


def svg_to_pdf_layers(
    data: bytes | str,
    *,
    layered: bool = True,
    page_size: str | None = "auto",
    title: str | None = None,
    base_dir: str | Path | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """SVG -> vector PDF; with ``layered`` one OCG per top-level layer (see the module docstring).

    ``base_dir`` is the SVG's folder: relative ``<image>`` links are resolved against it and
    embedded (svglib cannot resolve them from text). ``stats['warnings']`` lists everything the
    PDF cannot reproduce.
    """
    from .svgtools import load_svg, prepare_for_pdf, unit_documents

    root = load_svg(data)
    warnings = prepare_for_pdf(root, base_dir)
    docs = unit_documents(root, layered=layered)
    has_layers = layered and any(d.is_layer for d in docs)
    layers = [PdfLayer(d.label, d.svg_text, d.visible, d.opacity) for d in docs]
    pdf, stats = draw_pdf(layers, page_size=page_size, title=title, layered=has_layers)
    if has_layers:
        stats["layer_names"] = [d.label for d in docs]
        stats["hidden_layers"] = [d.label for d in docs if not d.visible]
    nested = sum(d.nested_opacity for d in docs)
    if nested:
        warnings.append(
            f"{nested} group(s)/element(s) inside a layer have their own opacity, which svglib ignores: they are "
            "opaque in the PDF (top-level layer opacity is kept) - move the opacity onto a top-level layer or onto "
            "the shapes' fill/stroke opacity"
        )
    stats["warnings"] = warnings + stats.get("warnings", [])
    return pdf, stats
