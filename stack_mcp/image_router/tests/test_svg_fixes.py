"""Regression tests: physical units (dpi), z-order safety for small content, stylesheet colours,
userSpaceOnUse clip paths, compose clipping and linked images, CSS id selectors, render size
bounds, collision-free default outputs and transform rounding."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from stack_mcp.image_router import tools
from stack_mcp.image_router.render import RenderError, render_svg
from stack_mcp.image_router.server import build_server
from stack_mcp.image_router.svg import optimize_svg
from stack_mcp.image_router.svgtools import (
    INK_GROUPMODE,
    INK_LABEL,
    ComposeLayer,
    StyleSheet,
    appearance_delta,
    compose,
    inspect,
    layerize,
    load_svg,
)

from .conftest import FIXTURES, open_png, payload_of


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def labels(text: str) -> list[str]:
    return [c.get(INK_LABEL) for c in ET.fromstring(text) if c.get(INK_GROUPMODE) == "layer"]


def layer_of(text: str, element_id: str) -> int:
    layers = [c for c in ET.fromstring(text) if c.get(INK_GROUPMODE) == "layer"]
    return next(i for i, lay in enumerate(layers) if any(e.get("id") == element_id for e in lay.iter()))


# --- physical units ------------------------------------------------------------------------------------

A4 = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297">'
    b'<rect width="210" height="297" fill="#ffffff"/>'
    b'<rect x="10" y="10" width="50" height="50" fill="#ff0000"/>'
    b'<rect x="100" y="10" width="50" height="50" fill="#0000ff"/>'
    b'<rect x="10" y="100" width="50" height="50" fill="#ff0000"/></svg>'
)


def test_mm_documents_render_layer_and_feed_raster_ops(stack_env, isolated):
    assert open_png(render_svg(A4)).size == (794, 1123)  # 96 dpi, as in a browser
    for unit in (b'50mm" height="25mm', b'72pt" height="36pt', b'2in" height="1in', b'5cm" height="2cm'):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="' + unit + b'"><rect width="100%" height="100%"/></svg>'
        assert open_png(render_svg(svg, width=200)).width == 200
    (isolated / "a4.svg").write_bytes(A4)
    is_error, payload = call(tools.svg_render, svg_path="a4.svg")
    assert not is_error and (payload["width"], payload["height"]) == (794, 1123)
    is_error, payload = call(tools.svg_layerize, svg_path="a4.svg", by="color")
    assert not is_error and "error" not in payload["appearance"] and not payload["warnings"]
    assert [lay["label"] for lay in payload["layers"]] == ["#ffffff", "#ff0000", "#0000ff"]  # no spurious split
    assert payload["z_order"]["conflicts"] == 0
    stack_env.set(IMAGE_UPSCALE_API="local")
    is_error, payload = call(tools.image_upscale, image="a4.svg", scale=2)
    assert not is_error and (payload["files"][0]["width"], payload["files"][0]["height"]) == (1588, 2246)
    is_error, payload = call(tools.export_pdf, svg_path="a4.svg")
    assert not is_error and [round(v) for v in payload["page_pt"]] == [595, 842]


def test_appearance_errors_become_warnings():
    assert "could not be verified" in tools.appearance_warning({"error": "resvg could not render the SVG"})


# --- z-order safety for content smaller than the coverage grid -------------------------------------------

BANNER = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="4000" height="2000" viewBox="0 0 4000 2000">'
    b'<rect id="bg" width="4000" height="2000" fill="#ffffff"/>'
    b'<rect id="badge" x="100" y="100" width="400" height="120" rx="20" fill="#1d71b8"/>'
    b'<text id="label" x="120" y="170" font-family="Helvetica, Arial, sans-serif" font-size="14" fill="#ffffff">LIMITED EDITION</text>'
    b'</svg>'
)
THIN = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="4000" height="4000" viewBox="0 0 4000 4000">'
    b'<rect width="4000" height="4000" fill="#ffffff"/>'
    b'<rect id="corner" width="800" height="800" fill="#ff0000"/>'
    b'<rect id="square" x="1000" y="1000" width="2000" height="2000" fill="#0000ff"/>'
    b'<rect id="bar" x="1200" y="2000" width="1600" height="3" fill="#ff0000"/></svg>'
)


def test_small_text_and_thin_bars_keep_their_stacking():
    text, report = layerize(BANNER, by="color")
    assert layer_of(text, "label") > layer_of(text, "badge")  # the white text stays above the badge
    text, report = layerize(THIN, by="color")
    assert layer_of(text, "bar") > layer_of(text, "square")
    assert report["z_order"]["split_layers"] == 1
    before = open_png(render_svg(THIN, width=4000)).convert("RGB").getpixel((2000, 2001))
    after = open_png(render_svg(text, width=4000)).convert("RGB").getpixel((2000, 2001))
    assert before == after == (255, 0, 0)


# --- stylesheets ----------------------------------------------------------------------------------------------

ILLUSTRATOR = b'''<?xml version="1.0" encoding="UTF-8"?>
<svg id="Layer_1" data-name="Layer 1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <defs><style>.cls-1{fill:#e30613;}.cls-2{fill:#1d71b8;}.cls-3{fill:none;stroke:#009640;stroke-width:4px;}</style></defs>
  <rect class="cls-1" width="50" height="50"/>
  <rect class="cls-2" x="50" width="50" height="50"/>
  <circle class="cls-1" cx="50" cy="75" r="20"/>
  <circle class="cls-3" cx="80" cy="80" r="10"/>
</svg>'''


def test_stylesheet_colours_drive_layers_and_palettes():
    text, report = layerize(ILLUSTRATOR, by="color")
    assert labels(text) == ["#e30613", "#1d71b8", "stroke #009640"]
    assert appearance_delta(ILLUSTRATOR, text)["changed_fraction"] < 0.001
    pal = {p["color"] for p in inspect(ILLUSTRATOR)["palette"]}
    assert pal == {"#e30613", "#1d71b8", "#009640"}
    text, _ = layerize((FIXTURES / "wrapper.svg").read_bytes(), by="color")
    assert labels(text) == ["#264653", "#e9c46a", "#999999", "#2a9d8f"]  # .a / .b classes, inherited #999999


def test_stylesheet_cascade_order():
    root = load_svg(
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>rect{fill:#111111} .x{fill:#222222} #y{fill:#333333}'
        b' .imp{fill:#444444 !important}</style>'
        b'<rect id="a" class="x" fill="#999999"/><rect id="y" class="x"/><rect id="s" class="x" style="fill:#555555"/>'
        b'<rect id="i" class="imp" style="fill:#666666"/><rect id="p" fill="#777777"/></svg>'
    )
    sheet = StyleSheet(root)
    get = {el.get("id"): el for el in root.iter() if el.get("id")}
    assert sheet.prop(get["a"], "fill") == "#222222"  # class rule beats the presentation attribute
    assert sheet.prop(get["y"], "fill") == "#333333"  # id beats class
    assert sheet.prop(get["s"], "fill") == "#555555"  # inline style beats the sheet
    assert sheet.prop(get["i"], "fill") == "#444444"  # !important beats inline
    assert sheet.prop(get["p"], "fill") == "#111111"  # a type selector still beats the attribute


CSS_ID = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<style>#art rect{fill:#e30613} #art circle{fill:#1d71b8}</style>
<g id="art"><g id="a"><rect width="60" height="60"/></g><g id="b"><circle cx="60" cy="60" r="30"/></g></g>
</svg>'''


@pytest.mark.parametrize("by", ["group", "color"])
def test_groups_selected_by_css_id_stay_whole(by):
    text, report = layerize(CSS_ID, by=by)
    assert appearance_delta(CSS_ID, text)["changed_fraction"] < 0.001


# --- clip paths ---------------------------------------------------------------------------------------------

FIGMA = b'''<svg width="200" height="100" viewBox="0 0 200 100" fill="none" xmlns="http://www.w3.org/2000/svg">
<g clip-path="url(#clip0_1_2)">
<rect width="200" height="100" fill="white"/>
<g id="Logo"><rect x="10" y="10" width="80" height="80" fill="#E30613"/></g>
<g id="Badge"><circle cx="150" cy="50" r="40" fill="#1D71B8"/></g>
<path d="M0 95H200" stroke="#009640" stroke-width="4"/>
</g>
<defs>
<clipPath id="clip0_1_2"><rect width="200" height="100" fill="white"/></clipPath>
</defs>
</svg>'''


def test_figma_clip_group_is_layerized():
    text, report = layerize(FIGMA, by="group")
    assert "Logo" in labels(text) and "Badge" in labels(text)
    assert appearance_delta(FIGMA, text)["changed_fraction"] < 0.001
    text, report = layerize(FIGMA, by="color")
    assert labels(text) == ["#ffffff", "#e30613", "#1d71b8", "stroke #009640"]
    assert appearance_delta(FIGMA, text)["changed_fraction"] < 0.001
    # an objectBoundingBox clip does not distribute: the group stays whole, and a note says why
    bbox = FIGMA.replace(b'<clipPath id="clip0_1_2">', b'<clipPath id="clip0_1_2" clipPathUnits="objectBoundingBox">')
    bbox = bbox.replace(b'<rect width="200" height="100" fill="white"/></clipPath>', b'<rect width="1" height="1"/></clipPath>')
    text, report = layerize(bbox, by="group")
    assert len(labels(text)) == 1 and any("kept whole" in n for n in report["notes"])


# --- compose -----------------------------------------------------------------------------------------------------

OVER = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect x="-20" y="-20" width="60" height="60" fill="#ff0000"/><circle cx="5" cy="5" r="3" fill="#0000ff"/></svg>'
BASE = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#00ff00"/></svg>'


def test_compose_clips_svg_sources_to_their_box():
    text, _ = compose([ComposeLayer("Base", BASE, "image/svg+xml"),
                       ComposeLayer("Icon", OVER, "image/svg+xml", x=40, y=40, width=20, height=20)], 100, 100)
    im = open_png(render_svg(text, background="white")).convert("RGB")
    assert im.getpixel((10, 10)) == (0, 255, 0) and im.getpixel((50, 50)) == (0, 0, 255)
    wide = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10" preserveAspectRatio="xMidYMid slice"><rect width="20" height="10" fill="#ff0000"/></svg>'
    text, _ = compose([ComposeLayer("Base", BASE, "image/svg+xml"),
                       ComposeLayer("Wide", wide, "image/svg+xml", x=40, y=40, width=20, height=20)], 100, 100)
    im = open_png(render_svg(text, background="white")).convert("RGB")
    assert im.getpixel((35, 50)) == (0, 255, 0) and im.getpixel((50, 50)) == (255, 0, 0)
    visible = OVER.replace(b'viewBox="0 0 10 10"', b'viewBox="0 0 10 10" overflow="visible"')
    text, _ = compose([ComposeLayer("Icon", visible, "image/svg+xml", x=40, y=40, width=20, height=20)], 100, 100)
    assert open_png(render_svg(text, background="white")).convert("RGB").getpixel((10, 10)) == (255, 0, 0)


def test_compose_embeds_linked_images_and_refuses_non_images(isolated):
    art = isolated / "art"
    art.mkdir()
    Image.new("RGB", (20, 20), (0, 128, 255)).save(art / "photo.png")
    (art / "secret.txt").write_text("API_KEY=do-not-embed")
    (art / "card.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="100" height="100" '
        'viewBox="0 0 100 100"><image xlink:href="photo.png" width="100" height="50"/>'
        '<image xlink:href="secret.txt" y="50" width="100" height="50"/></svg>'
    )
    is_error, payload = call(tools.layers_compose, layers=[{"source": "art/card.svg", "name": "Card"}], width=100, height=100,
                             output_path="out/comp.svg")
    assert not is_error, payload
    text = (isolated / "out" / "comp.svg").read_text()
    assert "photo.png" not in text and "data:image/png;base64," in text
    assert "do-not-embed" not in text and "secret.txt" in text
    assert any("not image files" in w for w in payload["warnings"])
    assert open_png(render_svg(text)).convert("RGB").getpixel((50, 25)) == (0, 128, 255)


# --- render size bounds ---------------------------------------------------------------------------------------------


def test_default_render_size_is_bounded(isolated):
    (isolated / "big.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20000" height="10000" viewBox="0 0 10 5"><rect width="10" height="5" fill="red"/></svg>')
    is_error, payload = call(tools.svg_render, svg_path="big.svg")
    assert not is_error and (payload["width"], payload["height"]) == (4096, 2048)
    assert any("20000x10000" in n for n in payload["notes"])
    (isolated / "tall.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="1000"><rect width="10" height="1000"/></svg>')
    is_error, payload = call(tools.svg_render, svg_path="tall.svg", width=8192)
    assert not is_error and payload["width"] * payload["height"] <= 64_000_000 and payload["notes"]
    with pytest.raises(RenderError, match="pass a smaller width"):
        render_svg(b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="1000"/>', width=8000, max_pixels=1_000_000)


# --- default output names --------------------------------------------------------------------------------------------


def test_default_outputs_never_overwrite_existing_files(isolated):
    (isolated / "logo.svg").write_bytes((FIXTURES / "scene.svg").read_bytes())
    (isolated / "logo.pdf").write_bytes(b"%PDF designer's own file")
    is_error, payload = call(tools.export_pdf, svg_path="logo.svg")
    assert not is_error and Path(payload["files"][0]["path"]).name == "logo-2.pdf"
    assert (isolated / "logo.pdf").read_bytes() == b"%PDF designer's own file"
    assert any("logo.pdf already exists" in n for n in payload["notes"])
    is_error, payload = call(tools.export_pdf, svg_path="logo.svg", output_path="logo.pdf")  # explicit: overwrites
    assert not is_error and (isolated / "logo.pdf").read_bytes().startswith(b"%PDF-")
    first = call(tools.svg_render, svg_path="logo.svg")[1]["files"][0]["path"]
    second = call(tools.svg_render, svg_path="logo.svg")[1]["files"][0]["path"]
    assert Path(first).name == "logo.preview.png" and Path(second).name == "logo.preview-2.png"
    for tool, kwargs in ((tools.svg_optimize, {}), (tools.svg_layerize, {"by": "group"})):
        a = call(tool, svg_path="logo.svg", **kwargs)[1]["files"][0]["path"]
        b = call(tool, svg_path="logo.svg", **kwargs)[1]["files"][0]["path"]
        assert a != b and Path(a).is_file() and Path(b).is_file()


def test_writing_tools_are_annotated_as_destructive():
    server = build_server()
    annotations = {t.name: t.annotations for t in asyncio.run(server.list_tools())}
    for name in ("svg_optimize", "mask_convert", "svg_render", "svg_layerize", "layers_compose", "export_pdf"):
        assert annotations[name].destructive_hint is True and annotations[name].idempotent_hint is False, name
    for name in ("image_ops_status", "image_info", "svg_inspect", "svg_layers"):
        assert annotations[name].read_only_hint is True and annotations[name].idempotent_hint is True, name


# --- svg_optimize transforms -------------------------------------------------------------------------------------------


def test_optimize_keeps_transform_coefficients():
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800">'
           b'<rect width="800" height="800" fill="#ffffff"/>'
           b'<g transform="matrix(0.26458333,0,0,0.26458333,10.123456,0)"><rect x="2000" y="2000" width="1000" height="1000" fill="#ff0000"/></g>'
           b'<path d="M 10 790 L 790 790" stroke="#000" stroke-width="2" transform="rotate(0.4 400.123 400)"/>'
           b'<rect width="10" height="10" opacity="0.5" fill="#00f"/></svg>')
    out, _ = optimize_svg(svg, precision=2)
    assert 'transform="matrix(0.26458 0 0 0.26458 10.12 0)"' in out
    assert 'transform="rotate(0.4 400.12 400)"' in out
    delta = appearance_delta(svg, out, max_side=800)
    assert delta["changed_fraction"] < 0.001, delta
    low, _ = optimize_svg(svg, precision=0)
    assert 'opacity="0.5"' in low and "matrix(0.26458 0 0 0.26458 10 0)" in low
