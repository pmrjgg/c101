"""svg_optimize: cleanup, rounding, viewBox, safety."""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET

import pytest

from stack_mcp.image_router import tools
from stack_mcp.image_router.svg import SvgError, optimize_svg, round_numbers, round_path

INKSCAPE_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Created with Inkscape -->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
     xmlns:sketch="http://www.bohemiancoding.com/sketch/ns"
     width="100" height="50px" inkscape:version="1.3" sodipodi:docname="x.svg">
  <metadata><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></metadata>
  <sodipodi:namedview pagecolor="#ffffff"/>
  <defs><linearGradient id="g"><stop offset="0.123456" stop-color="#f00"/></linearGradient></defs>
  <g inkscape:label="Layer 1" inkscape:groupmode="layer" sketch:type="MSPage">
    <!-- a comment -->
    <path d="M 10.123456,20.987654 L 30.5,40.25 A 5.555 5.555 0 0110.5 10.5 Z" fill="url(#g)"/>
    <circle cx="1.23456" cy="2.34567" r="0.999999" transform="translate(1.11111 2.22222)"/>
    <use xlink:href="#g" x="3.14159"/>
    <text x="1.5" y="2.5">  keep   spaces </text>
  </g>
</svg>
"""


def test_cleanup_and_rounding():
    out, stats = optimize_svg(INKSCAPE_SVG.encode(), precision=2)
    root = ET.fromstring(out)
    # layer markers survive (they carry the layer structure); other editor data is removed
    assert 'inkscape:groupmode="layer"' in out and 'inkscape:label="Layer 1"' in out
    assert "inkscape:version" not in out and "sodipodi" not in out and "sketch" not in out
    assert "<!--" not in out and "metadata" not in out and "rdf" not in out
    assert "ns0:" not in out and "xlink:href" in out
    path = root.find(".//{http://www.w3.org/2000/svg}path")
    # arc flags "0" "1" survive the compact form "0110.5"
    assert path.get("d") == "M10.12 20.99L30.5 40.25A5.55 5.55 0 0 1 10.5 10.5Z"
    circle = root.find(".//{http://www.w3.org/2000/svg}circle")
    assert circle.get("cx") == "1.23" and circle.get("r") == "1"
    assert circle.get("transform") == "translate(1.11 2.22)"
    stop = root.find(".//{http://www.w3.org/2000/svg}stop")
    assert stop.get("offset") == "0.12"
    text = root.find(".//{http://www.w3.org/2000/svg}text")
    assert text.text == "  keep   spaces "  # text content untouched
    assert root.get("viewBox") == "0 0 100 50"
    assert stats.added_viewbox and stats.removed_elements >= 2 and stats.removed_attributes >= 3
    assert stats.bytes_out < stats.bytes_in
    stripped, _ = optimize_svg(INKSCAPE_SVG.encode(), precision=2, keep_layers=False)
    assert "inkscape" not in stripped


def test_existing_viewbox_kept_and_precision_zero():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10.5 10.5"><path d="M1.6.4l.5-.5"/></svg>'
    out, stats = optimize_svg(svg, precision=0)
    assert 'viewBox="0 0 10 10"' in out  # rounded (half-to-even), not replaced
    assert not stats.added_viewbox
    # touching numbers (".6.4", ".5-.5") stay separate after rounding; -0 becomes 0
    assert ET.fromstring(out).find("{http://www.w3.org/2000/svg}path").get("d") == "M2 0l0 0"


def test_round_helpers():
    assert round_path("M0,0 C1.23456,2.34567 3,4 5.6e-3,6", 3) == "M0 0C1.235 2.346 3 4 0.006 6"
    assert round_numbers("1.5.5", 0) == "2 0"  # never "20"
    assert round_numbers("100.456%", 1) == "100.5%"
    assert round_numbers("-0.0001", 2) == "0"


def test_rejects_malformed_and_entities():
    with pytest.raises(SvgError, match="well-formed"):
        optimize_svg(b"<svg><g></svg>")
    with pytest.raises(SvgError, match="entities"):
        optimize_svg(b'<!DOCTYPE svg [<!ENTITY a "x">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>')
    with pytest.raises(SvgError, match="not <svg>"):
        optimize_svg(b"<html/>")


def test_svg_optimize_tool_writes_min_file(isolated):
    src = isolated / "icon.svg"
    src.write_text(INKSCAPE_SVG)
    result = asyncio.run(tools.svg_optimize(svg_path="icon.svg", precision=1))
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["tool"] == "svg_optimize"
    assert payload["ok"] and payload["files"][0]["path"].endswith("icon.min.svg")
    assert (isolated / "icon.min.svg").exists()
    assert src.read_text() == INKSCAPE_SVG  # input untouched


def test_svg_optimize_tool_error_is_flagged(isolated):
    (isolated / "bad.svg").write_text("<svg>")
    result = asyncio.run(tools.svg_optimize(svg_path="bad.svg"))
    assert result.is_error
    assert json.loads(result.content[0].text)["ok"] is False
