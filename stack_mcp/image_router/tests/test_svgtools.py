"""svg_inspect / svg_layers / svg_layerize / layers_compose / svg_render on fixtures.

Appearance is checked by rendering before and after with resvg; z-order by the stacking of
known ids in the output.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from stack_mcp.image_router import tools
from stack_mcp.image_router.render import render_svg
from stack_mcp.image_router.svgtools import (
    INK_GROUPMODE,
    INK_LABEL,
    Q,
    appearance_delta,
    compose,
    ComposeLayer,
    describe_layers,
    inspect,
    layerize,
    load_svg,
    norm_color,
    parse_selector,
    rewrite_css,
    selector_matches,
    SvgDoc,
)

from .conftest import FIXTURES, open_png, payload_of, png_bytes, rgba_cutout


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def top_layers(text: str) -> list[ET.Element]:
    root = ET.fromstring(text)
    return [c for c in root if c.get(INK_GROUPMODE) == "layer"]


def ids_in_paint_order(text: str) -> list[str]:
    return [el.get("id") for el in ET.fromstring(text).iter() if el.get("id") and el.get("id") in "ABCDE"]


# --- helpers -----------------------------------------------------------------------------------


def test_norm_color():
    assert norm_color("RED") == "#ff0000"
    assert norm_color("#ABC") == "#aabbcc"
    assert norm_color("rgb(255, 0, 10)") == "#ff000a"
    assert norm_color("rgb(100%,0%,0%)") == "#ff0000"
    assert norm_color("#11223344") == "#112233"
    assert norm_color("url( '#g1' )") == "url(#g1)"
    assert norm_color("none") is None and norm_color(None) is None


def test_selectors():
    root = load_svg(fixture("wrapper.svg"))
    doc = SvgDoc(root)
    rects = [el for el in root.iter(Q("rect"))]
    teal = next(r for r in rects if r.get("fill") == "#2a9d8f")
    assert selector_matches(parse_selector("[fill=#2a9d8f]"), teal, doc.parent)
    assert selector_matches(parse_selector("g#title > rect"), teal, doc.parent)
    assert selector_matches(parse_selector("svg rect"), teal, doc.parent)
    assert not selector_matches(parse_selector("#logo rect"), teal, doc.parent)
    a = next(r for r in rects if r.get("class") == "a")
    assert selector_matches(parse_selector("#logo .a"), a, doc.parent)
    assert selector_matches(parse_selector("rect.a"), a, doc.parent)


def test_rewrite_css_scopes_and_renames():
    css = "/* c */ .a{fill:#fff} svg .b, #x{stroke:url(#g)} @media print{.a{fill:red}}"
    out = rewrite_css(css, {"x": "l0-x", "g": "l0-g", "fff": "l0-fff"}, "#layer-a")
    assert "#layer-a .a {fill:#fff}" in out  # colours are never renamed
    assert "#layer-a .b, #layer-a #l0-x {stroke:url(#l0-g)}" in out
    assert "@media print{.a{fill:red}}" in out


# --- inspect / layers -----------------------------------------------------------------------------


def test_inspect_scene():
    info = inspect(fixture("scene.svg"))
    assert info["well_formed"] and info["root"]["viewBox"] == "0 0 200 120"
    assert info["layers"]["layer_count"] == 3 and info["layers"]["mode"] == "inkscape"
    assert [lay["label"] for lay in info["layers"]["layers"]] == ["Background", "Shapes", "Text"]
    assert info["layers"]["layers"][2]["visible"] is False
    assert info["text"]["count"] == 1 and info["text"]["samples"] == ["Hello"]
    assert {"#3a7d44", "#e63946"} <= {p["color"] for p in info["palette"]}
    assert info["gradients"] == 1 and info["path_count"] == 1
    assert any("<text>" in p for p in info["problems"])


def test_inspect_flags_problems():
    bad = (
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="10">'
        b'<script>alert(1)</script><rect id="a" onclick="x()" fill="url(#missing)"/><rect id="a"/>'
        b'<image xlink:href="https://example.com/a.png" width="1" height="1"/><g/></svg>'
    )
    info = inspect(bad)
    problems = " | ".join(info["problems"])
    for needle in ("no viewBox", "<script>", "duplicate ids", "missing ids", "external reference", "raster image", "empty group"):
        assert needle in problems, needle
    broken = inspect(b"<svg><g></svg>")
    assert broken["well_formed"] is False and "well-formed" in broken["error"]


def test_svg_inspect_and_layers_tools(isolated):
    (isolated / "scene.svg").write_bytes(fixture("scene.svg"))
    is_error, payload = call(tools.svg_inspect, svg_path="scene.svg")
    assert not is_error and payload["element_count"] > 5 and payload["problems"]
    is_error, payload = call(tools.svg_layers, svg_path="scene.svg")
    assert not is_error and payload["layer_count"] == 3
    assert payload["layers"][1] == {
        "id": "layer-shapes", "label": "Shapes", "visible": True, "kind": "inkscape-layer",
        "element_count": 4, "shape_count": 2, "palette": ["#e63946", "#f4a261"],
    }
    (isolated / "flat.svg").write_bytes(fixture("flat.svg"))
    is_error, payload = call(tools.svg_layers, svg_path="flat.svg")
    assert payload["mode"] == "none" and payload["loose_elements"] == 7 and "svg_layerize" in payload["notes"][0]
    (isolated / "bad.svg").write_text("<svg>")
    is_error, payload = call(tools.svg_inspect, svg_path="bad.svg")
    assert is_error and payload["ok"] is False


# --- layerize ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["scene.svg", "wrapper.svg", "flat.svg"])
@pytest.mark.parametrize("by", ["group", "color"])
def test_layerize_preserves_appearance(name, by):
    data = fixture(name)
    text, report = layerize(data, by=by)
    delta = appearance_delta(data, text)
    assert delta["mean_abs_diff"] < 0.05 and delta["changed_fraction"] < 0.001, (name, by, delta)
    layers = top_layers(text)
    assert layers and all(lay.get(INK_LABEL) and lay.get("id") for lay in layers)
    assert len({lay.get("id") for lay in layers}) == len(layers)
    root = ET.fromstring(text)
    assert root.find(Q("defs")) is not None or b"<defs" not in data  # defs preserved
    assert report["layer_count"] == len(layers)


def test_layerize_color_keeps_z_order_by_splitting():
    data = fixture("flat.svg")
    text, report = layerize(data, by="color")
    labels = [lay.get(INK_LABEL) for lay in top_layers(text)]
    assert labels == ["#ffffff", "#ff0000", "#0000ff", "#ff0000 (2)", "stroke #00aa00"]
    assert report["z_order"]["conflicts"] == 1 and report["z_order"]["split_layers"] == 1
    # A and C share a layer (C moved below B: they do not overlap); E stays above D
    order = ids_in_paint_order(text)
    assert order.index("C") < order.index("B") and order.index("E") > order.index("D")


def test_layerize_color_non_strict_reports_the_change():
    data = fixture("flat.svg")
    text, report = layerize(data, by="color", strict_z_order=False)
    assert [lay.get(INK_LABEL) for lay in top_layers(text)] == ["#ffffff", "#ff0000", "#0000ff", "stroke #00aa00"]
    assert report["z_order"]["conflicts"] == 1 and report["notes"]
    assert appearance_delta(data, text)["changed_fraction"] > 0.005


def test_layerize_group_descends_into_wrapper_and_keeps_its_attributes():
    text, report = layerize(fixture("wrapper.svg"), by="group")
    layers = top_layers(text)
    assert [lay.get(INK_LABEL) for lay in layers] == ["logo", "title", "Ungrouped"]
    for lay in layers:
        wrapper = lay[0]
        assert wrapper.get("transform") == "translate(10 5) scale(0.9)" and wrapper.get("fill") == "#999999"
    assert report["notes"] and "wrapper" in report["notes"][0]


def test_layerize_group_promotes_existing_top_level_groups_in_place():
    text, _ = layerize(fixture("scene.svg"), by="group")
    layers = top_layers(text)
    assert [lay.get("id") for lay in layers] == ["layer-background", "layer-shapes", "layer-text"]
    assert layers[2].get("style") == "display:none"  # hidden layer stays hidden
    plain = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><g id="a"><rect width="2" height="2"/></g><rect x="2" width="2" height="2"/></svg>'
    text, _ = layerize(plain, by="group")
    layers = top_layers(text)
    assert [lay.get("id") for lay in layers] == ["a", "layer-ungrouped"]
    assert layers[0][0].tag == Q("rect")  # the group itself became the layer (no extra nesting)


def test_layerize_mapping():
    mapping = {"Accent": ["[fill=#2a9d8f]"], "Logo": ["#logo"], "Nothing": [".nope"]}
    data = fixture("wrapper.svg")
    text, report = layerize(data, by="mapping", mapping=mapping)
    assert [lay.get(INK_LABEL) for lay in top_layers(text)] == ["Logo", "Other", "Accent"]
    assert any("matched nothing: ['Nothing']" in n for n in report["notes"])
    assert appearance_delta(data, text)["changed_fraction"] < 0.001
    logo_layer = top_layers(text)[0]
    assert logo_layer.find(f".//{Q('g')}[@id='logo']") is not None  # matched group kept whole


def test_layerize_mapping_by_bare_id_and_errors():
    text, _ = layerize(fixture("flat.svg"), by="mapping", mapping={"Reds": ["A", "C", "E"]})
    labels = [lay.get(INK_LABEL) for lay in top_layers(text)]
    assert labels[0] == "Other" and "Reds" in labels
    with pytest.raises(Exception, match="needs mapping"):
        layerize(fixture("flat.svg"), by="mapping")
    with pytest.raises(Exception, match="by must be"):
        layerize(fixture("flat.svg"), by="size")


def test_layerize_keeps_non_distributive_groups_whole():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
        b'<g opacity="0.5"><rect width="12" height="12" fill="#ff0000"/><rect x="6" y="6" width="12" height="12" fill="#0000ff"/></g>'
        b'<rect x="2" y="14" width="4" height="4" fill="#ff0000"/></svg>'
    )
    text, report = layerize(svg, by="color")
    labels = [lay.get(INK_LABEL) for lay in top_layers(text)]
    assert labels[0] == "mixed"  # the opacity group is one unit
    assert appearance_delta(svg, text)["changed_fraction"] < 0.001


def test_svg_layerize_tool_writes_next_to_input(isolated):
    (isolated / "flat.svg").write_bytes(fixture("flat.svg"))
    is_error, payload = call(tools.svg_layerize, svg_path="flat.svg", by="color")
    assert not is_error, payload
    out = Path(payload["files"][0]["path"])
    assert out == isolated / "flat.layered.svg" and out.is_file()
    assert payload["layer_count"] == 5 and payload["appearance"]["changed_fraction"] < 0.001 and not payload["warnings"]
    is_error, payload = call(tools.svg_layerize, svg_path="flat.svg", by="color", output_path="flat.svg")
    assert is_error and "must differ" in payload["error"]


# --- compose -----------------------------------------------------------------------------------------

SVG_RED = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>.c{fill:#ff0000}</style><defs><linearGradient id="g"><stop offset="0" stop-color="#ff0000"/></linearGradient></defs><rect class="c" width="10" height="10"/></svg>'
SVG_BLUE = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>.c{fill:#0000ff}</style><defs><linearGradient id="g"><stop offset="0" stop-color="#0000ff"/></linearGradient></defs><rect class="c" width="10" height="10" stroke="url(#g)"/></svg>'


def test_compose_isolates_sources_and_keeps_order():
    sticker = rgba_cutout(20, 20, color=(0, 255, 0))
    text, summary = compose(
        [
            ComposeLayer("Red", SVG_RED, "image/svg+xml", width=100, height=100),
            ComposeLayer("Blue", SVG_BLUE, "image/svg+xml", x=100, width=100, height=100),
            ComposeLayer("Sticker", sticker, "image/png", x=80, y=30, width=40, opacity=0.9),
            ComposeLayer("Notes", png_bytes(4, 4), "image/png", visible=False),
        ],
        200,
        100,
    )
    assert [s["label"] for s in summary] == ["Red", "Blue", "Sticker", "Notes"]
    root = load_svg(text)
    lay = describe_layers(root)
    assert lay["layer_count"] == 4 and [x["visible"] for x in lay["layers"]] == [True, True, True, False]
    ids = [el.get("id") for el in root.iter() if el.get("id")]
    assert len(ids) == len(set(ids))  # the two sources' "g" gradients no longer clash
    png = open_png(render_svg(text)).convert("RGB")
    assert png.size == (200, 100)
    assert png.getpixel((20, 50)) == (255, 0, 0) and png.getpixel((180, 50)) == (0, 0, 255)
    assert png.getpixel((100, 50))[1] > 200  # sticker on top
    assert png.getpixel((85, 35)) == (255, 0, 0)  # transparent part of the sticker shows the layer below
    sticker_layer = top_layers(text)[2]
    assert sticker_layer.get("opacity") == "0.9"
    image = sticker_layer.find(Q("image"))
    assert image.get("{http://www.w3.org/1999/xlink}href").startswith("data:image/png;base64,")


def test_compose_fits_svg_with_aspect_ratio():
    wide = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="20" height="10" fill="#000"/></svg>'
    text, _ = compose([ComposeLayer("W", wide, "image/svg+xml", width=100, height=100)], 100, 100)
    png = open_png(render_svg(text, background="white")).convert("RGB")
    assert png.getpixel((50, 10)) == (255, 255, 255) and png.getpixel((50, 50)) == (0, 0, 0)  # centred, letterboxed


def test_layers_compose_tool(isolated):
    (isolated / "a.svg").write_bytes(SVG_RED)
    (isolated / "b.png").write_bytes(rgba_cutout(10, 10))
    is_error, payload = call(
        tools.layers_compose,
        layers=[{"source": "a.svg", "name": "Base"}, {"source": "b.png", "name": "Top", "x": 5, "y": 5, "width": 20}],
        width=50, height=40,
    )
    assert not is_error, payload
    path = Path(payload["files"][0]["path"])
    assert path.parent.parent == isolated / ".stack" / "images" and path.name.startswith("composition-")
    assert [lay["label"] for lay in payload["layers"]] == ["Base", "Top"]
    is_error, payload = call(tools.layers_compose, layers=[{"source": "missing.svg", "name": "x"}], width=1, height=1)
    assert is_error and "file not found" in payload["error"]


# --- render ------------------------------------------------------------------------------------------


def test_svg_render_dims_and_background(isolated):
    (isolated / "scene.svg").write_bytes(fixture("scene.svg"))
    is_error, payload = call(tools.svg_render, svg_path="scene.svg")
    assert not is_error, payload
    assert (payload["width"], payload["height"]) == (200, 120)
    assert Path(payload["files"][0]["path"]) == isolated / "scene.preview.png"
    is_error, payload = call(tools.svg_render, svg_path="scene.svg", width=500, background="white", output_path="out/p.png")
    assert not is_error and (payload["width"], payload["height"]) == (500, 300)
    im = open_png((isolated / "out" / "p.png").read_bytes())
    assert im.size == (500, 300)


def test_render_text_gradient_transform():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
        b'<defs><linearGradient id="g"><stop offset="0" stop-color="#f00"/><stop offset="1" stop-color="#00f"/></linearGradient></defs>'
        b'<rect width="200" height="100" fill="url(#g)"/>'
        b'<g transform="translate(100 50) rotate(45)"><rect x="-10" y="-10" width="20" height="20" fill="#0f0"/></g>'
        b'<text x="10" y="90" font-family="Helvetica, Arial, sans-serif" font-size="20" fill="#fff">Hello</text></svg>'
    )
    im = open_png(render_svg(svg)).convert("RGB")
    assert im.getpixel((2, 50))[0] > 240 and im.getpixel((197, 50))[2] > 240  # gradient ends
    assert im.getpixel((100, 50)) == (0, 255, 0)
    assert im.getpixel((100, 37)) == (0, 255, 0)  # rotated: the corner points up
    region = im.crop((10, 70, 80, 95))
    white = sum(1 for x in range(region.width) for y in range(region.height) if min(region.getpixel((x, y))) > 200)
    assert white > 30  # text was rendered with a system font


def test_paint_key_follows_nested_inheritance():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><g opacity="0.8" fill="#ff0000">'
        b'<g fill="#00ff00"><rect width="4" height="4"/></g><g><rect x="5" width="4" height="4" fill="#00ff00"/></g></g></svg>'
    )
    doc = SvgDoc.parse(svg)
    group = doc.root[0]
    assert doc.paint_key(group, ()) == ("#00ff00", "#00ff00")  # inner group's fill wins over the outer one


def test_layerize_ignores_antialiasing_seams_but_not_thin_lines():
    seams = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        b'<rect width="50.4" height="50" fill="#ff0000"/>'
        b'<rect x="50" width="50" height="50.4" fill="#0000ff"/>'
        b'<rect x="40" y="50" width="60" height="50" fill="#ff0000"/></svg>'  # touches the blue one by a 0.4 sliver
    )
    text, report = layerize(seams, by="color")
    assert [lay.get(INK_LABEL) for lay in top_layers(text)] == ["#ff0000", "#0000ff"]
    delta = appearance_delta(seams, text)
    assert delta["changed_fraction"] < 0.01 and delta["mean_abs_diff"] < 1.5  # only the sliver changes
    lines = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        b'<rect width="20" height="20" fill="#ff0000"/>'
        b'<rect x="30" y="30" width="60" height="60" fill="#0000ff"/>'
        b'<line x1="35" y1="60" x2="85" y2="60" stroke="#ff0000" stroke-width="0.5"/></svg>'
    )
    text, report = layerize(lines, by="color")
    labels = [lay.get(INK_LABEL) for lay in top_layers(text)]
    assert labels == ["#ff0000", "#0000ff", "stroke #ff0000"]
    hairline = lines.replace(
        b'<line x1="35" y1="60" x2="85" y2="60" stroke="#ff0000" stroke-width="0.5"/>',
        b'<rect x="35" y="60" width="50" height="0.5" fill="#ff0000"/>',
    )
    text, report = layerize(hairline, by="color")
    # the thin red shape overlaps the blue fill: it may not move below it, so it opens a 2nd red layer
    assert [lay.get(INK_LABEL) for lay in top_layers(text)] == ["#ff0000", "#0000ff", "#ff0000 (2)"]
    assert appearance_delta(hairline, text)["changed_fraction"] < 0.001
