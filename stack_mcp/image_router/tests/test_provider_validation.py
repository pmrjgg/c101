"""Regression tests: provider requests validated against the live (fixture) catalogs, n splitting,
source framing for edit-type tasks, reserved params, signed input URLs and SVG encodings.

The catalogs are trimmed copies of the public GET https://api.opper.ai/v3/images/models and
GET https://openrouter.ai/api/v1/images/models (2026-10-19), see fixtures/.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from stack_mcp.image_router import tools
from stack_mcp.image_router.providers import geometry
from stack_mcp.image_router.providers.base import validate_svg
from stack_mcp.image_router.providers.openai import openai_size
from stack_mcp.image_router.providers.opper import image_params, normalise_dimensions
from stack_mcp.image_router.svgtools import load_svg

from .conftest import COMPAT_URL, OPENROUTER_URL, OPPER_URL, json_response, payload_of, png_bytes
from .fakes import OPENROUTER_CATALOG, OPPER_CATALOG, FakeCompat, FakeOpenRouter, FakeOpper, body_of, chain

SIGNED = "https://cdn.example.com/private/photo.png?X-Amz-Signature=SECRETSIG123&X-Amz-Credential=AKIAEXAMPLE"


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def opper_img(model: str) -> dict:
    return image_params(next(m for m in OPPER_CATALOG["models"] if m["id"] == model))


def posts(fake) -> list[httpx.Request]:
    return [r for r in fake.requests if r.method == "POST"]


def wide_png(w: int = 160, h: int = 90) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, "PNG")
    return buf.getvalue()


# --- Opper: quality (finding: quality sent unvalidated) ------------------------------------------


def test_opper_quality_is_validated_without_size_or_aspect(stack_env, mock_http):
    stack_env.configure("GEN", OPPER_URL, "openai/gpt-image-2.5-flare")
    fake = FakeOpper(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x", quality="ultra")
    assert not is_error, payload
    assert [r for r in fake.requests if r.method == "GET"], "the catalog must be consulted for quality alone"
    assert "quality" not in body_of(posts(fake)[-1])
    assert any("quality ultra not offered" in n for n in payload["notes"])

    is_error, payload = call(tools.image_generate, prompt="x", quality="XHIGH")
    assert body_of(posts(fake)[-1])["quality"] == "xhigh"  # sent as the catalog spells it

    # seedream declares no quality tiers at all: Opper rejects any quality there
    stack_env.configure("GEN", OPPER_URL, "bytedance:ap/seedream-5")
    is_error, payload = call(tools.image_generate, prompt="x", quality="high", size="2048x2048")
    body = body_of(posts(fake)[-1])
    assert not is_error and "quality" not in body and body["size"] == "2048x2048"
    assert any("declares no quality tiers" in n for n in payload["notes"])


def test_opper_quality_sent_unvalidated_only_without_catalog(stack_env, mock_http):
    stack_env.configure("GEN", OPPER_URL, "openai/gpt-image-2.5-flare")
    fake = FakeOpper(png_bytes(), catalog={"models": []})
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x", quality="high", seed=5)
    body = body_of(posts(fake)[-1])
    assert not is_error and body["quality"] == "high" and body["parameters"] == {"seed": 5}
    assert any("catalog unavailable" in n for n in payload["notes"])


# --- Opper: passthrough parameters (seed / output_format) ----------------------------------------


def test_opper_passthrough_parameters_need_a_declaration(stack_env, mock_http):
    stack_env.configure("GEN", OPPER_URL, "openai/gpt-image-2.5-flare")
    fake = FakeOpper(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x", seed=7, output_format="webp")
    body = body_of(posts(fake)[-1])
    assert not is_error and body["parameters"] == {"output_format": "webp"}  # GPT Image declares no seed
    assert any("seed dropped" in n for n in payload["notes"])

    stack_env.configure("GEN", OPPER_URL, "vertexai/gemini-3.1-flash-image")
    is_error, payload = call(tools.image_generate, prompt="x", output_format="png")
    assert not is_error and "parameters" not in body_of(posts(fake)[-1])
    assert any("output_format dropped" in n for n in payload["notes"])

    stack_env.configure("GEN", OPPER_URL, "fal/flux-2-pro")  # declares seed and output_format
    is_error, payload = call(tools.image_generate, prompt="x", seed=7, output_format="png")
    assert body_of(posts(fake)[-1])["parameters"] == {"seed": 7, "output_format": "png"}


# --- Opper: size constraints, tiers, aspect ratios -------------------------------------------------


def test_opper_dimensions_follow_size_constraints():
    flare = opper_img("openai/gpt-image-2.5-flare")
    limits = geometry.SizeConstraints.from_mapping(flare["size_constraints"])
    for legal in ("3840x2160", "2048x2048", "2048x1152", "1536x864"):
        assert normalise_dimensions(legal, None, flare) == ({"size": legal}, [])  # legal sizes are kept
    fields, notes = normalise_dimensions(None, "16:9", flare)
    assert fields == {"size": "1536x864"} and notes  # exactly 16:9, not the 3:2 preset 1536x1024
    fields, _ = normalise_dimensions("2K", None, flare)
    assert fields == {"size": "2048x2048"}  # a tier on a constraints model: a size of that long edge
    fields, _ = normalise_dimensions("4K", "16:9", flare)
    assert fields == {"size": "3840x2160"}
    for odd in ("1000x1000", "5000x1000", "100x100"):
        fields, notes = normalise_dimensions(odd, None, flare)
        w, h = geometry.parse_size(fields["size"])
        assert limits.meets(w, h) and any("size constraints" in n for n in notes), (odd, fields)
    fields, _ = normalise_dimensions("1000x1000", None, flare)
    assert fields == {"size": "1008x1008"}  # ratio kept, rounded to the multiple of 16


def test_opper_dimensions_tiers_and_presets():
    gemini = opper_img("vertexai/gemini-3.1-flash-image")
    fields, notes = normalise_dimensions("4K", None, gemini)
    assert fields == {"quality": "4k"} and any("quality tier" in n for n in notes)  # Gemini's 4K is a quality
    fields, notes = normalise_dimensions("2K", "16:9", gemini)
    assert fields == {"aspect_ratio": "16:9"} and any("no 2K option" in n for n in notes)
    grok = opper_img("xai/grok-imagine-image")
    assert normalise_dimensions("2K", None, grok)[0] == {"resolution": "2k"}
    fields, notes = normalise_dimensions("4K", None, grok)
    assert fields == {"resolution": "2k"} and notes
    flux = opper_img("fal/flux-2-pro")
    assert normalise_dimensions("1000x700", None, flux)[0] == {"size": "1536x1024"}  # nearest preset by ratio
    assert normalise_dimensions(None, "16:9", flux)[0] == {"size": "1280x720"}
    assert normalise_dimensions("2K", None, flux)[0] == {"size": "2048x2048"}  # tier -> preset by long edge
    # 'auto' is a size value; a model that only takes 'auto' never gets size: null
    ideo = opper_img("fal/ideogram-v4.5-edit")
    assert normalise_dimensions("auto", None, ideo)[0] == {"size": "auto"}
    fields, notes = normalise_dimensions(None, "16:9", ideo)
    assert fields == {} and any("only takes size 'auto'" in n for n in notes)
    for size, aspect in (("1K", None), ("2K", "3:2"), (None, "21:9"), ("640x480", None)):
        fields, _ = normalise_dimensions(size, aspect, ideo)
        assert all(v is not None for v in fields.values())


def test_opper_dimensions_without_catalog_information_are_sent_as_given():
    # catalog unavailable (or an entry without params.image): nothing to validate against
    assert normalise_dimensions("2K", "16:9", {}) == ({"resolution": "2k", "aspect_ratio": "16:9"}, [])
    assert normalise_dimensions("1000x700", "16:9", {})[0] == {"size": "1000x700"}
    assert normalise_dimensions("auto", None, {})[0] == {"size": "auto"}


def test_opper_dimension_request_body(stack_env, mock_http):
    stack_env.configure("GEN", OPPER_URL, "fal/ideogram-v4.5-edit")
    fake = FakeOpper(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x", aspect_ratio="16:9")
    body = body_of(posts(fake)[-1])
    assert not is_error and "size" not in body and "aspect_ratio" not in body


# --- Opper: transparency check before paying --------------------------------------------------------


def test_opper_transparent_refused_when_model_declares_no_background(stack_env, mock_http):
    stack_env.configure_cutout(OPPER_URL, "vertexai/gemini-3.1-flash-image")
    fake = FakeOpper(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate_transparent, prompt="x")
    assert is_error and "declares no background option" in payload["error"]
    assert not posts(fake)  # refused before paying
    is_error, payload = call(tools.image_remove_background, image="data:image/png;base64," + base64.b64encode(png_bytes()).decode())
    assert is_error and not posts(fake)


# --- source framing for edit-type tasks ----------------------------------------------------------------


def test_opper_edit_keeps_the_source_framing(stack_env, mock_http, isolated):
    (isolated / "wide.png").write_bytes(wide_png(160, 90))
    fake = FakeOpper(wide_png(160, 90))
    mock_http(chain(fake))
    expected = {
        "openai/gpt-image-2.5-flare": ("size", "1536x864"),
        "fal/ideogram-v4.5-edit": ("size", "auto"),
        "vertexai/gemini-3.1-flash-image": ("aspect_ratio", "16:9"),
        "fal/flux-kontext-pro": ("size", "1280x720"),
    }
    for model, (key, value) in expected.items():
        stack_env.configure("EDIT", OPPER_URL, model)
        is_error, payload = call(tools.image_edit, image="wide.png", instruction="make it blue")
        assert not is_error, payload
        body = body_of(posts(fake)[-1])
        assert body.get(key) == value, (model, body)

    stack_env.configure("UPSCALE", OPPER_URL, "openai/gpt-image-2")
    (isolated / "photo.png").write_bytes(wide_png(1000, 750))
    fake.image = wide_png(1600, 1200)
    is_error, payload = call(tools.image_upscale, image="photo.png", scale=2)
    assert not is_error, payload
    w, h = geometry.parse_size(body_of(posts(fake)[-1])["size"])
    assert w % 16 == 0 and h % 16 == 0 and abs(w / h - 4 / 3) < 0.01 and w * h >= 655_360
    assert (payload["files"][0]["width"], payload["files"][0]["height"]) == (2000, 1500)


def test_openrouter_edit_keeps_the_source_framing(stack_env, mock_http, isolated):
    (isolated / "wide.png").write_bytes(wide_png(160, 90))
    (isolated / "pano.png").write_bytes(wide_png(1000, 370))
    fake = FakeOpenRouter(wide_png(160, 90), catalog=OPENROUTER_CATALOG)
    mock_http(chain(fake))
    stack_env.configure("EDIT", OPENROUTER_URL, "krea/k3-edit")
    is_error, payload = call(tools.image_edit, image="wide.png", instruction="add a hat")
    assert not is_error, payload
    assert body_of(fake.requests[-1])["aspect_ratio"] == "16:9"
    assert any("keeps the 160x90 source framing" in n for n in payload["notes"])
    # no listed ratio within 2% of 2.7:1, and the model offers 'auto': the provider keeps the framing
    stack_env.configure("EDIT", OPENROUTER_URL, "openai/gpt-image-2.5-sunburst")
    call(tools.image_edit, image="pano.png", instruction="x")
    assert body_of(fake.requests[-1])["aspect_ratio"] == "auto"
    # an explicit aspect_ratio is snapped to the model's own values
    stack_env.configure("GEN", OPENROUTER_URL, "krea/k3-edit")
    is_error, payload = call(tools.image_generate, prompt="x", aspect_ratio="21:9")
    assert body_of(fake.requests[-1])["aspect_ratio"] == "16:9"
    assert any("not offered by the model" in n for n in payload["notes"])
    # without the catalog nothing is guessed, but the caller is told how to keep the framing
    fake.catalog = None
    from stack_mcp.image_router.providers import openrouter

    openrouter.clear_catalog_cache()
    is_error, payload = call(tools.image_edit, image="wide.png", instruction="x")
    assert "aspect_ratio" not in body_of(fake.requests[-1])
    assert any("pass aspect_ratio to keep the source framing" in n for n in payload["notes"])


# --- OpenRouter: n, transparency --------------------------------------------------------------------


def test_openrouter_n_is_split_only_for_single_image_models(stack_env, mock_http):
    fake = FakeOpenRouter(png_bytes(4, 4), catalog=OPENROUTER_CATALOG)
    mock_http(chain(fake))
    stack_env.configure("GEN", OPENROUTER_URL, "openai/gpt-image-2.5-flare")  # n 1..10
    is_error, payload = call(tools.image_generate, prompt="x", n=3)
    assert not is_error and len(fake.requests) == 1 and body_of(fake.requests[0])["n"] == 3
    assert len(payload["files"]) == 3
    stack_env.configure("GEN", OPENROUTER_URL, "krea/k3-edit")  # declares no n at all
    is_error, payload = call(tools.image_generate, prompt="x", n=2)
    assert not is_error and len(fake.requests) == 3 and all("n" not in body_of(r) for r in fake.requests[1:])
    assert len(payload["files"]) == 2


def test_openrouter_split_keeps_images_when_some_requests_fail(stack_env, mock_http):
    stack_env.configure("GEN", OPENROUTER_URL, "google/gemini-nano-banana-2.1")
    seen = {"posts": 0}

    def handler(req: httpx.Request):
        if req.method == "GET":
            return json_response(OPENROUTER_CATALOG)
        seen["posts"] += 1
        if seen["posts"] == 2:
            return json_response({"error": {"code": 500, "message": "provider hiccup"}}, 500)
        return json_response({"data": [{"b64_json": base64.b64encode(png_bytes()).decode(), "media_type": "image/png"}]})

    mock_http(handler)
    is_error, payload = call(tools.image_generate, prompt="x", n=3)
    assert not is_error and len(payload["files"]) == 2
    assert any("1 of 3 requests failed" in w for w in payload["warnings"])


def test_openrouter_transparency_checked_before_paying(stack_env, mock_http):
    fake = FakeOpenRouter(png_bytes(), catalog=OPENROUTER_CATALOG)
    mock_http(chain(fake))
    for model, needle in (("openai/gpt-image-2", "background options are"),
                          ("google/gemini-nano-banana-2.1", "declares no background option"),
                          ("sourceful/riverflow-v2.5-fast", "needs png or webp")):
        stack_env.configure_cutout(OPENROUTER_URL, model)
        is_error, payload = call(tools.image_generate_transparent, prompt="x")
        assert is_error and needle in payload["error"], (model, payload)
    assert not fake.requests


# --- Opper: vector style ------------------------------------------------------------------------------


SVG_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect width="4" height="4" fill="#f00"/></svg>'


def test_opper_vector_uses_recraft_style_parameter(stack_env, mock_http):
    stack_env.configure("VECTOR", OPPER_URL, "fal/recraft-v3")
    fake = FakeOpper(SVG_BYTES, mime_type="image/svg+xml")
    mock_http(chain(fake))
    is_error, payload = call(tools.vector_generate, prompt="a mountain logo", style="flat icon")
    assert not is_error, payload
    body = body_of(posts(fake)[-1])
    assert body["parameters"] == {"style": "vector_illustration"}
    assert "Style: flat icon" in body["prompt"]
    assert any("vector styles are billed" in n for n in payload["notes"])
    call(tools.vector_generate, prompt="x", style="vector_illustration/line_art")
    assert body_of(posts(fake)[-1])["parameters"] == {"style": "vector_illustration/line_art"}
    # a model without a style parameter keeps the prompt hint only
    stack_env.configure("VECTOR", OPPER_URL, "fal/flux-2-pro")
    call(tools.vector_generate, prompt="x", style="flat icon")
    body = body_of(posts(fake)[-1])
    assert "parameters" not in body and "Style: flat icon" in body["prompt"]


# --- OpenAI-compatible sizes --------------------------------------------------------------------------------


def test_openai_sizes_meet_model_limits(stack_env, mock_http):
    for size, aspect in (("1K", "16:9"), ("1K", "21:9"), ("1K", "9:16"), (None, "3:1"), ("4K", "1:1"), ("4K", "16:9")):
        out, _ = openai_size(size, aspect)
        w, h = geometry.parse_size(out)
        assert w % 16 == 0 and h % 16 == 0 and 655_360 <= w * h <= 8_294_400 and max(w, h) <= 3840, (size, aspect, out)
    assert openai_size(None, "16:9", "gpt-image-1")[0] == "1536x1024"
    assert openai_size("1024x768", None, "gpt-image-1.5")[0] == "1536x1024"
    assert openai_size("1536x1024", None, "gpt-image-1-mini") == ("1536x1024", None)
    assert openai_size("auto", None, "gpt-image-1") == ("auto", None)
    assert openai_size(None, "16:9", "dall-e-3")[0] == "1792x1024"
    stack_env.configure("GEN", COMPAT_URL, "gpt-image-1.5")
    fake = FakeCompat(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x", aspect_ratio="16:9")
    assert not is_error and body_of(fake.requests[0])["size"] == "1536x1024"
    assert any("accepts only" in n for n in payload["notes"])


# --- reserved params -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("params", [{"model": "openai/gpt-image-1"}, {"prompt": "something else"},
                                    {"input_references": []}, {"messages": []}])
def test_call_params_cannot_switch_model_or_inputs(stack_env, mock_http, params):
    stack_env.configure("GEN", OPENROUTER_URL, "google/gemini-nano-banana-2.1")
    fake = FakeOpenRouter(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="fox", params=params)
    assert is_error and "params may not set" in payload["error"] and "IMAGE_GEN_MODEL" in payload["error"]
    assert not fake.requests


def test_op_params_cannot_set_the_model(stack_env, mock_http):
    stack_env.configure("GEN", OPENROUTER_URL, "google/gemini-nano-banana-2.1", params={"model": "x", "quality": "high"})
    seen = mock_http(lambda req: json_response({"error": {"message": "must not be called"}}, 418))
    is_error, payload = call(tools.image_generate, prompt="fox")
    assert is_error and "IMAGE_GEN_PARAMS may not set model" in payload["error"]
    assert not seen


# --- signed input URLs never reach sidecars ------------------------------------------------------------------


def test_signed_input_urls_are_redacted_in_sidecars_and_results(stack_env, mock_http):
    stack_env.configure("EDIT", OPENROUTER_URL, "krea/k3-edit")
    stack_env.configure("REF", OPPER_URL, "vertexai/gemini-3.1-flash-image")
    src = png_bytes(8, 8)

    def cdn(req: httpx.Request):
        if req.url.host == "cdn.example.com":
            return httpx.Response(200, content=src, headers={"content-type": "image/png"})
        return None

    orf, opf = FakeOpenRouter(png_bytes(8, 8)), FakeOpper(png_bytes(8, 8))
    mock_http(chain(cdn, orf, opf))
    results = [call(tools.image_edit, image=SIGNED, instruction="add a hat"),
               call(tools.image_generate_with_references, prompt="same", references=[SIGNED])]
    # the provider itself receives the full URL (it fetches the image)
    assert body_of(orf.requests[0])["input_references"][0]["image_url"]["url"] == SIGNED
    assert body_of(posts(opf)[-1])["reference_images"] == [SIGNED]
    for is_error, payload in results:
        assert not is_error, payload
        side = Path(payload["files"][0]["path"] + ".json").read_text()
        everything = side + json.dumps(payload)
        assert "SECRETSIG123" not in everything and "AKIAEXAMPLE" not in everything
        assert "https://cdn.example.com/private/photo.png?<redacted>" in side


# --- SVG encodings ---------------------------------------------------------------------------------------------


def test_validate_svg_drops_bom_and_foreign_declaration():
    text = '﻿<?xml version="1.0" encoding="ISO-8859-1"?>\n<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
    out = validate_svg(text)
    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>') and out.count("<?xml") == 1 and "﻿" not in out
    load_svg(out.encode("utf-8"))


@pytest.mark.parametrize("layered", [False, True])
def test_vector_output_with_bom_is_written_well_formed(stack_env, mock_http, layered):
    stack_env.configure("VECTOR", OPENROUTER_URL, "recraft/recraft-v4.1-vector")
    raw = ('﻿<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
           '<g id="a"><rect width="5" height="5" fill="#f00"/></g><g id="b"><circle cx="7" cy="7" r="2" fill="#00f"/></g></svg>')
    mock_http(chain(FakeOpenRouter(raw.encode("utf-8"), media_type="image/svg+xml")))
    is_error, payload = call(tools.vector_generate, prompt="logo", layered=layered)
    assert not is_error, payload
    data = Path(payload["files"][0]["path"]).read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and data.count(b"<?xml") == 1
    load_svg(data)
