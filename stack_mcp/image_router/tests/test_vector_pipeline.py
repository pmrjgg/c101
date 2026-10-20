"""VECTOR strategies 'trace' and 'layerize' (raster model -> TRACE, Ideogram text as live SVG), the text
layer builder, the layered PDF of the result, and alpha reattachment for upscales."""

from __future__ import annotations

import asyncio
import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pikepdf
from PIL import Image

from stack_mcp.image_router import textlayer, tools

from .conftest import json_response, open_png, payload_of

QUEUE = "https://queue.fal.run"
SVG = "{http://www.w3.org/2000/svg}"
INK = "{http://www.inkscape.org/namespaces/inkscape}"
LAYERIZE = "fal-ai/ideogram/v3/layerize-text"
CONTAINERS = [{"id": "container_01", "items": [{
    "x": 20, "y": 30, "angle": 0, "width": 60, "height": 10, "alignment": "center", "font_size": 12,
    "line_height": 1.2, "font_file": "Montserrat-Bold.ttf", "style_class": "h1",
    "font_candidates": ["font__montserrat__700", "font__poppins__700"],
    "spans": [{"text": "I love cats", "color": "#020202", "font_fx": ["bold"]}]}]}]


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def flat_png(w: int = 100, h: int = 60, text_band: bool = True) -> bytes:
    """Two flat colour blocks (traceable) and, optionally, a dark band where the 'text' would be."""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    for x in range(10, 45):
        for y in range(5, 25):
            im.putpixel((x, y), (220, 40, 40))
    for x in range(55, 90):
        for y in range(5, 25):
            im.putpixel((x, y), (40, 40, 220))
    if text_band:
        for x in range(30, 70):
            for y in range(32, 38):
                im.putpixel((x, y), (2, 2, 2))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def openapi_for(endpoint: str, properties: dict) -> dict:
    return {
        "paths": {f"/{endpoint}": {"post": {"requestBody": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Input"}}}}}}},
        "components": {"schemas": {"Input": {"type": "object", "properties": properties}}},
    }


class MultiFal:
    """fal queue API for several endpoints: endpoint -> (input properties, result JSON); CDN files by URL."""

    def __init__(self, endpoints: dict[str, tuple[dict, dict]], files: dict[str, bytes]):
        self.endpoints, self.files = endpoints, files
        self.requests: list[httpx.Request] = []

    def body(self, endpoint: str) -> dict:
        return json.loads(next(r for r in self.requests if r.method == "POST" and str(r.url) == f"{QUEUE}/{endpoint}").content)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith("https://fal.ai/api/openapi/"):
            endpoint = url.split("endpoint_id=", 1)[1]
            return json_response(openapi_for(endpoint, self.endpoints[endpoint][0]))
        if url in self.files:
            return httpx.Response(200, content=self.files[url], headers={"content-type": "image/png"})
        for endpoint, (_props, result) in self.endpoints.items():
            base = f"{QUEUE}/{endpoint}"
            if request.method == "POST" and url == base:
                return json_response({"request_id": "r", "status_url": f"{base}/requests/r/status",
                                      "response_url": f"{base}/requests/r", "cancel_url": f"{base}/requests/r/cancel"})
            if url == f"{base}/requests/r/status":
                return json_response({"status": "COMPLETED"})
            if url == f"{base}/requests/r":
                return json_response(result)
        return httpx.Response(404, json={"detail": f"unexpected {request.method} {url}"})


def ideogram_fal(draft: bytes, artwork: bytes | None = None) -> MultiFal:
    props = {"prompt": {"type": "string"}, "image_size": {"type": "string"}, "num_images": {"type": "integer"},
             "quality": {"type": "string", "enum": ["low", "medium", "high"]}}
    endpoints = {"ideogram/v4.5": (props, {"images": [{"url": "https://v3.fal.media/files/t/draft.png"}]})}
    files = {"https://v3.fal.media/files/t/draft.png": draft}
    if artwork is not None:
        endpoints[LAYERIZE] = ({"image_url": {"type": "string"}, "prompt": {"type": "string"}},
                               {"image": {"url": "https://v3.fal.media/files/t/art.png"}, "prompt": "x", "seed": 1,
                                "text_containers": CONTAINERS, "image_layers": [], "text_html": "<div></div>"})
        files["https://v3.fal.media/files/t/art.png"] = artwork
    return MultiFal(endpoints, files)


def layers_of(svg_path: Path) -> list[str]:
    root = ET.parse(svg_path).getroot()
    return [el.get(f"{INK}label") for el in root if el.get(f"{INK}groupmode") == "layer"]


# --- text layer ------------------------------------------------------------------------------------

def test_text_layer_maps_boxes_into_the_viewbox():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120"><path d="M0 0h5v5z" fill="#f00"/></svg>'
    out, info = textlayer.compose(svg, CONTAINERS, (100, 60), split_colors=False)
    assert info == {"text_elements": 1, "layers": ["Artwork", "Text"], "notes": []}
    root = ET.fromstring(out)
    block = root.find(f".//{SVG}g[@id='text-1']")
    assert block.get("font-family") == "'Montserrat', sans-serif" and block.get("font-weight") == "700"
    assert block.get("text-anchor") == "middle" and block.get("font-size") == "24"  # 12 px x scale 2
    text = block.find(f"{SVG}text")
    assert text.get("x") == "100"  # centre of the 20..80 box, x2
    assert abs(float(text.get("y")) - (30 + 5 + 0.35 * 12) * 2) < 0.01  # centred in the box, baseline 0.35 em down
    tspan = text.find(f"{SVG}tspan")
    assert tspan.text == "I love cats" and tspan.get("fill") == "#020202" and tspan.get("font-weight") == "bold"


def test_text_layer_lines_spans_rotation_and_untrusted_values():
    containers = [{"id": "c<1>", "items": [{
        "x": 0, "y": 0, "width": 100, "height": 40, "alignment": "right", "angle": 15, "font_size": 10,
        "line_height": 1.5, "font_file": "Evil\"Font<script>.ttf",
        "spans": [{"text": "Hello ", "color": "red;fill:url(javascript:x)"},
                  {"text": "<b>World</b>\nsecond", "color": "#00ff00", "font_fx": ["italic", "underline"]}]}]}]
    out, info = textlayer.compose('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40"/>',
                                  containers, (100, 40), split_colors=False)
    assert info["text_elements"] == 2
    root = ET.fromstring(out)
    block = root.find(f".//{SVG}g[@id='text-1']")
    assert block.get("transform") == "rotate(15 50 20)" and block.get("text-anchor") == "end"
    assert all(ch not in block.get("font-family") for ch in '<>"')
    first, second = block.findall(f"{SVG}text")
    assert first.get("x") == "100" and float(second.get("y")) - float(first.get("y")) == 15  # line height
    spans = first.findall(f"{SVG}tspan")
    assert spans[0].get("fill") is None  # an invalid colour is dropped, never copied into markup
    assert spans[1].text == "<b>World</b>" and spans[1].get("font-style") == "italic"
    assert spans[1].get("text-decoration") == "underline"
    assert "<b>" not in out and "&lt;b&gt;World" in out  # escaped text, no injected markup


def test_text_layer_absent_without_text_and_artwork_split_by_colour():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><linearGradient id="g"/></defs>'
           '<path d="M0 0h5v5z" fill="#ff0000"/><path d="M5 5h5v5z" fill="#0000ff"/></svg>')
    out, info = textlayer.compose(svg, [], (10, 10), split_colors=True)
    assert info["text_elements"] == 0
    assert info["layers"] == ["Artwork #ff0000", "Artwork #0000ff"]
    root = ET.fromstring(out)
    assert root[0].tag == f"{SVG}defs"  # defs stay at the root, outside the layers


def test_font_names_from_candidates_or_file():
    assert textlayer.font_of({"font_candidates": ["font__be-vietnam-pro__900italic"]}) == ("Be Vietnam Pro", 900, True)
    assert textlayer.font_of({"font_file": "NosiferCaps-Regular.ttf"}) == ("Nosifer Caps", 400, False)
    assert textlayer.font_of({"font_file": "Inter-SemiBoldItalic.otf"}) == ("Inter", 600, True)


# --- vector_generate strategies -------------------------------------------------------------------------

def test_layerize_strategy_end_to_end_and_layered_pdf(stack_env, mock_http, isolated):
    stack_env.configure("VECTOR", QUEUE, "ideogram/v4.5", params={"strategy": "layerize", "quality": "medium"})
    stack_env.set(IMAGE_TRACE_API="local")
    fake = ideogram_fal(flat_png(), artwork=flat_png(text_band=False))
    mock_http(fake)

    is_error, payload = call(tools.vector_generate, prompt="poster that says I love cats", aspect_ratio="16:9")
    assert not is_error, payload
    draw = fake.body("ideogram/v4.5")
    assert draw["quality"] == "medium" and "strategy" not in draw and "layerize_model" not in draw
    lay = fake.body(LAYERIZE)
    assert lay["image_url"].startswith("data:image/png;base64,") and "I love cats" in lay["prompt"]

    svg_path = isolated / payload["files"][0]["path"]
    assert layers_of(svg_path) == ["Artwork", "Text"]
    assert "I love cats" in svg_path.read_text()
    assert payload["layers"][0]["text_elements"] == 1
    assert len(payload["intermediates"]) == 2 and all((isolated / p).exists() for p in payload["intermediates"])
    sidecar = json.loads(Path(f"{svg_path}.json").read_text())
    pipe = sidecar["pipeline"][0]
    assert pipe["strategy"] == "layerize" and pipe["draw"]["model"] == "ideogram/v4.5"
    assert pipe["layerize"]["model"] == LAYERIZE and pipe["trace"]["adapter"] == "local"
    assert any("Montserrat-Bold.ttf" in n for n in payload["notes"])

    is_error, pdf = call(tools.export_pdf, svg_path=str(svg_path.relative_to(isolated)))
    assert not is_error, pdf
    with pikepdf.open(isolated / pdf["files"][0]["path"]) as doc:
        assert [str(o.Name) for o in doc.Root.OCProperties.OCGs] == ["Artwork", "Text"]
        content = b"".join(page.Contents.read_bytes() if not isinstance(page.Contents, pikepdf.Array)
                           else b"".join(c.read_bytes() for c in page.Contents) for page in doc.pages)
        assert b"Tj" in content or b"TJ" in content  # the lettering is PDF text, not outlines


def test_trace_strategy_has_no_text_layer(stack_env, mock_http, isolated):
    stack_env.configure("VECTOR", QUEUE, "ideogram/v4.5", params={"strategy": "trace"})
    stack_env.set(IMAGE_TRACE_API="local")
    fake = ideogram_fal(flat_png())
    mock_http(fake)
    is_error, payload = call(tools.vector_generate, prompt="flat logo", layered=True)
    assert not is_error, payload
    assert not any(str(r.url).startswith(f"{QUEUE}/{LAYERIZE}") for r in fake.requests)
    labels = layers_of(isolated / payload["files"][0]["path"])
    assert labels and all(lbl.startswith("Artwork") for lbl in labels) and len(labels) >= 2  # split by colour


def test_layerize_needs_fal_and_trace_needs_trace_config(stack_env, mock_http, isolated):
    stack_env.configure("VECTOR", "https://openrouter.ai/api/v1", "ideogram/ideogram-v3", params={"strategy": "layerize"})
    stack_env.set(IMAGE_TRACE_API="local")
    is_error, payload = call(tools.vector_generate, prompt="x")
    assert is_error and "fal" in payload["error"]

    stack_env.set(IMAGE_TRACE_API="")
    stack_env.configure("VECTOR", QUEUE, "ideogram/v4.5", params={"strategy": "trace"})
    is_error, payload = call(tools.vector_generate, prompt="x")
    assert is_error and "TRACE" in payload["error"]


# --- upscale keeps transparency ---------------------------------------------------------------------------

def _rgba_source() -> bytes:
    im = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
    for x in range(5, 15):
        for y in range(2, 8):
            im.putpixel((x, y), (200, 30, 30, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _opaque(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_upscale_reattaches_source_alpha(stack_env, mock_http, isolated):
    endpoint = "topaz/upscale/image/precision"
    # "model" is router-reserved, so Topaz's own model field keeps its default (Standard V2)
    stack_env.configure("UPSCALE", QUEUE, endpoint, params={"upscale_factor": 2.5})
    fake = MultiFal({endpoint: ({"image_url": {"type": "string"}, "upscale_factor": {"type": "number"},
                                 "model": {"type": "string"}}, {"image": {"url": "https://v3.fal.media/files/t/up.png"}})},
                    {"https://v3.fal.media/files/t/up.png": _opaque(50, 25)})
    mock_http(fake)
    (isolated / "logo.png").write_bytes(_rgba_source())
    is_error, payload = call(tools.image_upscale, image="logo.png", scale=2.5)
    assert not is_error, payload
    assert fake.body(endpoint)["upscale_factor"] == 2.5
    out = open_png((isolated / payload["files"][0]["path"]).read_bytes())
    assert out.size == (50, 25) and out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0 and out.getpixel((25, 12))[3] == 255
    assert any("transparency" in n for n in payload["notes"])


def test_upscale_leaves_opaque_sources_opaque(stack_env, mock_http, isolated):
    endpoint = "topaz/upscale/image/precision"
    stack_env.configure("UPSCALE", QUEUE, endpoint)
    mock_http(MultiFal({endpoint: ({"image_url": {"type": "string"}}, {"image": {"url": "https://v3.fal.media/files/t/up.png"}})},
                       {"https://v3.fal.media/files/t/up.png": _opaque(40, 20)}))
    (isolated / "photo.png").write_bytes(_opaque(20, 10))
    is_error, payload = call(tools.image_upscale, image="photo.png", scale=2)
    assert not is_error, payload
    assert open_png((isolated / payload["files"][0]["path"]).read_bytes()).mode == "RGB"
