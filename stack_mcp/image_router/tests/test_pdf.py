"""export_pdf: layered PDFs carry one OCG per SVG layer; non-layered SVGs give plain PDFs."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pikepdf
import pytest

from stack_mcp.image_router import tools
from stack_mcp.image_router.render import RenderError, page_size_pt, pdf_layer_names, svg_to_pdf_layers
from stack_mcp.image_router.svgtools import ComposeLayer, compose

from .conftest import FIXTURES, payload_of, rgba_cutout


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def ocg_state(pdf: bytes) -> tuple[list[str], list[str], list[str]]:
    with pikepdf.open(io.BytesIO(pdf)) as doc:
        ocp = doc.Root.OCProperties
        names = [str(o.Name) for o in ocp.OCGs]
        on = [str(o.Name) for o in ocp.D.ON]
        off = [str(o.Name) for o in ocp.D.OFF]
        assert [str(o.Name) for o in ocp.D.Order] == names
        page = doc.pages[0]
        props = page.Resources.Properties
        assert sorted(props.keys()) == [f"/oc{i}" for i in range(len(names))]
        content = page.Contents.read_bytes()
        assert content.count(b"BDC") == len(names) == content.count(b"EMC")
        for i in range(len(names)):
            assert f"/OC /oc{i} BDC".encode() in content
        assert doc.Root.PageMode == pikepdf.Name.UseOC
    return names, on, off


def test_layered_pdf_has_one_ocg_per_layer(isolated):
    (isolated / "scene.svg").write_bytes((FIXTURES / "scene.svg").read_bytes())
    is_error, payload = call(tools.export_pdf, svg_path="scene.svg")
    assert not is_error, payload
    path = Path(payload["files"][0]["path"])
    assert path == isolated / "scene.pdf" and path.read_bytes().startswith(b"%PDF")
    names, on, off = ocg_state(path.read_bytes())
    assert names == ["Background", "Shapes", "Text"]
    assert on == ["Background", "Shapes"] and off == ["Text"]  # hidden SVG layer starts OFF
    assert payload["layers"] == 3 and payload["layer_names"] == names and payload["hidden_layers"] == ["Text"]
    assert pdf_layer_names(path) == names
    with pikepdf.open(path) as doc:
        assert [float(v) for v in doc.pages[0].mediabox] == [0, 0, 150, 90]  # 200x120 px -> pt


def test_non_layered_pdf(isolated):
    (isolated / "flat.svg").write_bytes((FIXTURES / "flat.svg").read_bytes())
    is_error, payload = call(tools.export_pdf, svg_path="flat.svg")  # no layers in the SVG
    assert not is_error and payload["layers"] == 0 and "single-layer" in payload["notes"][0]
    pdf = Path(payload["files"][0]["path"]).read_bytes()
    assert pdf_layer_names(pdf) == []
    with pikepdf.open(io.BytesIO(pdf)) as doc:
        assert "/OCProperties" not in doc.Root
    (isolated / "scene.svg").write_bytes((FIXTURES / "scene.svg").read_bytes())
    is_error, payload = call(tools.export_pdf, svg_path="scene.svg", layered=False, output_path="out/plain.pdf")
    assert not is_error and pdf_layer_names((isolated / "out" / "plain.pdf").read_bytes()) == []


def test_layerize_then_export_and_loose_content_units():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        b'width="40" height="40"><rect width="40" height="40" fill="#eee"/>'
        b'<g id="l1" inkscape:groupmode="layer" inkscape:label="One"><rect width="10" height="10"/></g>'
        b'<circle cx="30" cy="30" r="5"/></svg>'
    )
    pdf, stats = svg_to_pdf_layers(svg)
    names, on, off = ocg_state(pdf)
    assert names == ["Unlayered", "One", "Unlayered 2"] and off == []


def test_page_sizes():
    assert page_size_pt("auto", (100, 50)) is None
    w, h = page_size_pt("A4", (100, 50))
    assert round(w) == 842 and round(h) == 595  # landscape drawing -> landscape A4
    assert page_size_pt("letter", (50, 100)) == (612.0, 792.0)
    w, h = page_size_pt("100x50mm", (1, 1))
    assert round(w, 1) == 283.5 and round(h, 1) == 141.7
    with pytest.raises(RenderError):
        page_size_pt("huge", (1, 1))
    pdf, stats = svg_to_pdf_layers((FIXTURES / "scene.svg").read_bytes(), page_size="A4")
    with pikepdf.open(io.BytesIO(pdf)) as doc:
        mb = [round(float(v)) for v in doc.pages[0].mediabox]
    assert mb == [0, 0, 842, 595] and stats["scale"] > 1


def test_raster_layers_keep_alpha_in_pdf():
    text, _ = compose(
        [ComposeLayer("Base", b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect width="4" height="4" fill="#00f"/></svg>', "image/svg+xml"),
         ComposeLayer("Cutout", rgba_cutout(16, 16), "image/png", x=10, y=10, width=40)],
        100, 100,
    )
    pdf, stats = svg_to_pdf_layers(text)
    assert stats["layer_names"] == ["Base", "Cutout"]
    with pikepdf.open(io.BytesIO(pdf)) as doc:
        xobjs = list(doc.pages[0].Resources.XObject.values())
        assert xobjs and all(x.get("/SMask") is not None for x in xobjs)


def test_export_pdf_rejects_bad_page_size(isolated):
    (isolated / "scene.svg").write_bytes((FIXTURES / "scene.svg").read_bytes())
    is_error, payload = call(tools.export_pdf, svg_path="scene.svg", page_size="tabloidish")
    assert is_error and "page_size" in payload["error"]


# --- regression: opacity, linked images, reference closure, svglib losses ----------------------------------

import shutil  # noqa: E402
import subprocess  # noqa: E402

from PIL import Image  # noqa: E402

from stack_mcp.image_router.svgtools import load_svg, unit_documents  # noqa: E402

GS = shutil.which("gs")


def gs_pixel(pdf: bytes, tmp: Path, at: tuple[float, float]) -> tuple[int, int, int]:
    (tmp / "p.pdf").write_bytes(pdf)
    subprocess.run([GS, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m", "-r96",
                    f"-sOutputFile={tmp / 'p.png'}", str(tmp / "p.pdf")], check=True)
    im = Image.open(tmp / "p.png").convert("RGB")
    return im.getpixel((int(im.width * at[0]), int(im.height * at[1])))


def test_layer_opacity_survives_in_the_pdf(isolated, tmp_path):
    (isolated / "paper.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#ffffff"/></svg>')
    Image.new("RGB", (50, 50), (0, 0, 255)).save(isolated / "blue.png")
    is_error, payload = call(tools.layers_compose, layers=[{"source": "paper.svg", "name": "Paper"},
                                                         {"source": "blue.png", "name": "Tint", "opacity": 0.3, "width": 100, "height": 100}],
                             width=100, height=100, output_path="comp.svg")
    assert not is_error, payload
    for layered in (True, False):
        is_error, payload = call(tools.export_pdf, svg_path="comp.svg", layered=layered, output_path=f"comp-{layered}.pdf")
        assert not is_error, payload
        pdf = (isolated / f"comp-{layered}.pdf").read_bytes()
        with pikepdf.open(io.BytesIO(pdf)) as doc:
            res = doc.pages[0].Resources
            forms = [x for x in res.XObject.values() if x.get("/Subtype") == pikepdf.Name.Form]
            assert forms and all(f.Group.S == pikepdf.Name.Transparency for f in forms)
            alphas = [float(g.get("/ca")) for g in res.ExtGState.values() if g.get("/ca") is not None]
            assert any(abs(a - 0.3) < 1e-6 for a in alphas), alphas
        if GS:
            r, g, b = gs_pixel(pdf, tmp_path, (0.5, 0.5))
            assert b > 240 and 160 < r < 195 and 160 < g < 195, (r, g, b)  # 30% blue over white, not opaque blue


def test_group_opacity_is_composited_as_a_group(tmp_path):
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="200" height="100">'
           b'<rect width="200" height="100" fill="#ffffff"/>'
           b'<g inkscape:groupmode="layer" inkscape:label="Top" opacity="0.5"><rect width="120" height="100" fill="#0000ff"/>'
           b'<rect x="80" width="120" height="100" fill="#ff0000"/></g></svg>')
    pdf, stats = svg_to_pdf_layers(svg)
    assert not stats["warnings"]
    if GS:
        assert gs_pixel(pdf, tmp_path, (0.5, 0.5)) == pytest.approx((255, 127, 127), abs=3)  # red over blue, then 50%


def test_unit_documents_hold_only_what_they_reference():
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
             'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="1000" height="1000">'
             '<defs><linearGradient id="grad"><stop offset="0" stop-color="#f00"/></linearGradient></defs>']
    for i in range(40):
        parts.append(f'<g id="l{i}" inkscape:groupmode="layer" inkscape:label="L{i}">')
        parts += [f'<path id="p{i}-{j}" d="M{j} {i} l10 0 l0 10 z" fill="#{(i * 40 + j) % 0xffffff:06x}"/>' for j in range(20)]
        parts.append("</g>")
    parts.append('<g id="lx" inkscape:groupmode="layer" inkscape:label="Uses"><use xlink:href="#p3-4" x="5"/>'
                 '<rect width="5" height="5" fill="url(#grad)"/></g></svg>')
    svg = "".join(parts).encode()
    docs = unit_documents(load_svg(svg))
    assert len(docs) == 41
    total = sum(len(d.svg_text) for d in docs)
    assert total < 2 * len(svg), (total, len(svg))  # linear: was ~40x the input (every other layer copied)
    uses = load_svg(docs[-1].svg_text)
    ids = {el.get("id") for el in uses.iter() if el.get("id")}
    assert {"p3-4", "grad"} <= ids and "p0-0" not in ids  # the closure, and nothing else
    pdf, stats = svg_to_pdf_layers(svg)
    assert pdf_layer_names(pdf)[-1] == "Uses"


def test_linked_images_are_embedded_in_the_pdf(isolated):
    art = isolated / "art"
    art.mkdir()
    Image.new("RGB", (20, 20), (0, 128, 255)).save(art / "photo.png")
    (art / "poster.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="100" height="100" viewBox="0 0 100 100">'
        '<g id="l1" inkscape:groupmode="layer" inkscape:label="Photo"><image xlink:href="photo.png" x="10" y="10" width="80" height="80"/></g>'
        '<g id="l2" inkscape:groupmode="layer" inkscape:label="Title"><image xlink:href="missing.png" width="10" height="10"/></g></svg>')
    is_error, payload = call(tools.export_pdf, svg_path="art/poster.svg")
    assert not is_error, payload
    with pikepdf.open(payload["files"][0]["path"]) as doc:
        page = doc.pages[0]
        images = [x for x in page.Resources.XObject.values() if x.get("/Subtype") == pikepdf.Name.Image]
        assert len(images) == 1 and b" Do" in page.Contents.read_bytes()
    assert any("missing.png" in w for w in payload["warnings"])


def test_pdf_reports_what_svglib_cannot_draw(isolated):
    (isolated / "fx.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="200" height="100">'
        '<defs><mask id="m"><rect width="100" height="100" fill="#fff"/></mask><filter id="f"><feGaussianBlur stdDeviation="2"/></filter>'
        '<radialGradient id="rg"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#000"/></radialGradient></defs>'
        '<g inkscape:groupmode="layer" inkscape:label="L"><rect width="200" height="100" fill="#f00" mask="url(#m)"/>'
        '<rect width="10" height="10" filter="url(#f)"/><rect width="200" height="50" fill="url(#rg)"/>'
        '<g opacity="0.5"><rect width="5" height="5"/></g>'
        '<text x="10" y="90" font-family="Helvetica" font-size="20">你好</text></g></svg>', encoding="utf-8")
    is_error, payload = call(tools.export_pdf, svg_path="fx.svg")
    assert not is_error, payload
    text = " | ".join(payload["warnings"])
    for needle in ("mask x1", "filter x1", "radial gradient", "own opacity", "characters the PDF font cannot show"):
        assert needle in text, (needle, text)
    plain = isolated / "plain.svg"
    plain.write_bytes((FIXTURES / "scene.svg").read_bytes())
    is_error, payload = call(tools.export_pdf, svg_path="plain.svg")
    assert not is_error and payload["warnings"] == []  # nothing lost: no noise


def test_shape_opacity_is_folded_into_paint_opacity(tmp_path):
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="#fff"/>'
           b'<rect width="200" height="100" fill="#0000ff" opacity="0.5"/></svg>')
    pdf, stats = svg_to_pdf_layers(svg, layered=False)
    assert not stats["warnings"]
    if GS:
        assert gs_pixel(pdf, tmp_path, (0.5, 0.5)) == pytest.approx((127, 127, 255), abs=3)
