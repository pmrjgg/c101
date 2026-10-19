"""Adapter request shapes (headers, body, data URLs, multipart parts) and response parsing."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest

from stack_mcp.image_router import tools
from stack_mcp.image_router.providers.openai import openai_size
from stack_mcp.image_router.providers.opper import mask_convention_for, normalise_dimensions

from .conftest import (
    COMPAT_URL,
    FAKE_KEYS,
    OPENROUTER_URL,
    OPPER_URL,
    json_response,
    open_png,
    parse_multipart,
    pattern_png,
    payload_of,
    png_bytes,
    rgba_cutout,
)
from .fakes import OPENROUTER_CATALOG, FakeCompat, FakeOpenRouter, FakeOpper, body_of, chain

SVG_OUT = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><g id="a"><rect width="5" height="5" fill="#f00"/></g><g id="b"><circle cx="7" cy="7" r="2" fill="#00f"/></g></svg>'


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def decode_data_url(url: str) -> bytes:
    assert url.startswith("data:image/png;base64,")
    return base64.b64decode(url.split(",", 1)[1])


# --- OpenRouter ----------------------------------------------------------------------------------


def test_openrouter_generate_headers_body_and_parsing(stack_env, mock_http, isolated):
    key = stack_env.configure("GEN", OPENROUTER_URL, "google/gemini-nano-banana-2.1", params={"quality": "high"})
    fake = FakeOpenRouter(png_bytes(6, 4), catalog=OPENROUTER_CATALOG)
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="a red fox", aspect_ratio="16:9", size="2k", n=2, seed=7,
                             params={"provider": {"only": ["google-vertex"]}})
    assert not is_error, payload
    # the catalog says gemini-nano-banana-2.1 generates one image per request (n 1..1): n=2 is two requests
    assert len(fake.requests) == 2 and len(fake.catalog_requests) == 1
    assert "authorization" not in fake.catalog_requests[0].headers  # the public catalog gets no key
    req = fake.requests[0]
    assert req.method == "POST" and str(req.url) == "https://openrouter.ai/api/v1/images"
    assert req.headers["authorization"] == f"Bearer {key}"
    assert req.headers["content-type"] == "application/json"
    assert req.headers["http-referer"] and req.headers["x-openrouter-title"] and req.headers["x-title"]
    bodies = sorted((body_of(r) for r in fake.requests), key=lambda b: b["seed"])
    for i, b in enumerate(bodies):
        assert b == {
            "model": "google/gemini-nano-banana-2.1", "prompt": "a red fox", "size": "2K", "aspect_ratio": "16:9",
            "seed": 7 + i, "quality": "high", "provider": {"only": ["google-vertex"]},
        }  # one seed per split request, so the images differ
    assert any("n=2 sent as 2 single-image requests" in n for n in payload["notes"])
    assert any("seeds 7..8" in n for n in payload["notes"])
    assert payload["op"] == "GEN" and payload["adapter"] == "openrouter" and payload["url_host"] == "openrouter.ai"
    assert payload["model"] == "google/gemini-nano-banana-2.1"
    assert len(payload["files"]) == 2
    for f in payload["files"]:
        assert Path(f["path"]).is_file() and (f["width"], f["height"]) == (6, 4)
        assert Path(f["path"]).parent.parent == isolated / ".stack" / "images"


def test_openrouter_explicit_pixels_drop_aspect_ratio(stack_env, mock_http):
    stack_env.configure("GEN", OPENROUTER_URL, "m")
    fake = FakeOpenRouter(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x", size="1024X768", aspect_ratio="1:1")
    assert not is_error
    body = body_of(fake.requests[0])
    assert body["size"] == "1024x768" and "aspect_ratio" not in body
    assert any("aspect_ratio dropped" in n for n in payload["notes"])


def test_openrouter_references_are_image_url_objects(stack_env, mock_http, isolated):
    stack_env.configure("REF", OPENROUTER_URL, "openai/gpt-image-2.5-sunburst")
    (isolated / "a.png").write_bytes(png_bytes(4, 4, (1, 2, 3)))
    fake = FakeOpenRouter(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate_with_references, prompt="same character", references=["a.png", "a.png"])
    assert not is_error, payload
    refs = body_of(fake.requests[0])["input_references"]
    assert len(refs) == 2
    for r in refs:
        assert r["type"] == "image_url" and decode_data_url(r["image_url"]["url"]) == png_bytes(4, 4, (1, 2, 3))


def test_openrouter_masked_edit_sends_mask_reference_and_preserves_unmasked(stack_env, mock_http, isolated):
    stack_env.configure("EDIT", OPENROUTER_URL, "krea/k3-edit")
    src = pattern_png(32, 24)
    (isolated / "src.png").write_bytes(src)
    from PIL import Image

    mask = Image.new("L", (32, 24), 0)
    for x in range(8, 20):
        for y in range(6, 18):
            mask.putpixel((x, y), 255)
    mask.save(isolated / "mask.png")
    # the model returns a solid green image at a different size: everything changed
    fake = FakeOpenRouter(png_bytes(64, 48, (0, 255, 0)))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_edit, image="src.png", instruction="paint it green", mask="mask.png", feather=1.0)
    assert not is_error, payload
    body = body_of(fake.requests[0])
    refs = body["input_references"]
    assert decode_data_url(refs[0]["image_url"]["url"]) == src
    sent_mask = open_png(decode_data_url(refs[1]["image_url"]["url"]))
    assert sent_mask.getpixel((10, 10))[0] == 255 and sent_mask.getpixel((0, 0))[0] == 0  # white = edit
    assert "white in the mask" in body["prompt"] and body["prompt"].startswith("paint it green")
    assert any("no mask parameter" in n for n in payload["notes"])
    out = open_png(Path(payload["files"][0]["path"]).read_bytes()).convert("RGB")
    orig = open_png(src).convert("RGB")
    assert out.size == (32, 24)
    for xy in [(0, 0), (31, 23), (5, 5), (25, 20), (7, 10)]:  # outside the mask: identical
        assert out.getpixel(xy) == orig.getpixel(xy)
    assert out.getpixel((14, 12)) == (0, 255, 0)  # deep inside the mask: the edit
    assert payload["fidelity"][0]["drift_outside_mask"] > 50
    side = json.loads(Path(payload["files"][0]["path"] + ".json").read_text())
    assert side["params"]["masked"] is True and side["instruction"] == "paint it green"


def test_openrouter_edit_without_preserve_keeps_model_pixels(stack_env, mock_http, isolated):
    stack_env.configure("EDIT", OPENROUTER_URL, "m")
    (isolated / "src.png").write_bytes(pattern_png(8, 8))
    (isolated / "mask.png").write_bytes(png_bytes(8, 8, (255, 255, 255)))
    mock_http(chain(FakeOpenRouter(png_bytes(8, 8, (0, 0, 255)))))
    is_error, payload = call(tools.image_edit, image="src.png", instruction="x", mask="mask.png", preserve_unmasked=False)
    assert not is_error and payload["warnings"]


def test_openrouter_transparent_and_remove_background_alpha_transfer(stack_env, mock_http, isolated):
    stack_env.configure_cutout(OPENROUTER_URL, "openai/gpt-image-2.5-flare")
    # model returns a cut-out whose RGB differs from the source: only its alpha is used
    fake = FakeOpenRouter(rgba_cutout(16, 16, color=(10, 200, 10)))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate_transparent, prompt="a fox sticker")
    assert not is_error and not payload["warnings"]
    body = body_of(fake.requests[0])
    assert body["background"] == "transparent" and body["output_format"] == "png"

    src = pattern_png(16, 16)
    (isolated / "photo.png").write_bytes(src)
    is_error, payload = call(tools.image_remove_background, image="photo.png")
    assert not is_error, payload
    body = body_of(fake.requests[1])
    assert body["background"] == "transparent" and "Remove the background" in body["prompt"]
    assert decode_data_url(body["input_references"][0]["image_url"]["url"]) == src
    out = open_png(Path(payload["files"][0]["path"]).read_bytes())
    orig = open_png(src).convert("RGB")
    assert out.mode == "RGBA"
    assert out.getpixel((8, 8))[:3] == orig.getpixel((8, 8)) and out.getpixel((8, 8))[3] == 255  # original pixels
    assert out.getpixel((0, 0))[3] == 0  # background transparent
    assert payload["fidelity"][0]["drift"] > 18 and any("high drift" in w for w in payload["warnings"])


def test_openrouter_opaque_transparent_output_is_flagged(stack_env, mock_http):
    stack_env.configure_cutout(OPENROUTER_URL, "openai/gpt-image-2")
    mock_http(chain(FakeOpenRouter(png_bytes(4, 4))))
    is_error, payload = call(tools.image_generate_transparent, prompt="x")
    assert not is_error and "no transparent pixels" in payload["warnings"][0]


def test_openrouter_mask_render_is_normalised(stack_env, mock_http, isolated):
    stack_env.configure("SEGMENT", OPENROUTER_URL, "google/gemini-nano-banana-2.1")
    (isolated / "src.png").write_bytes(pattern_png(40, 30))
    from PIL import Image
    import io

    m = Image.new("RGB", (80, 60), (5, 5, 5))  # near-black with a light-grey object, double size
    for x in range(20, 60):
        for y in range(10, 40):
            m.putpixel((x, y), (240, 240, 240))
    buf = io.BytesIO()
    m.save(buf, "PNG")
    fake = FakeOpenRouter(buf.getvalue())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_segment, image="src.png", prompt="the cat")
    assert not is_error, payload
    body = body_of(fake.requests[0])
    assert "the cat" in body["prompt"] and "pure white" in body["prompt"] and len(body["input_references"]) == 1
    out = open_png(Path(payload["files"][0]["path"]).read_bytes())
    assert out.mode == "L" and out.size == (40, 30)
    assert sum(out.histogram()[1:255]) == 0  # strictly binary
    assert out.getpixel((20, 12)) == 255 and out.getpixel((2, 2)) == 0
    assert payload["mask_stats"]["binary_fraction"] > 0.9 and not payload["warnings"]


def test_openrouter_mask_detect_strategy_rasterises_boxes(stack_env, mock_http, isolated):
    stack_env.configure("SEGMENT", OPENROUTER_URL, "moondream/moondream3.1-9b-a2b", params={"strategy": "detect"})
    (isolated / "src.png").write_bytes(pattern_png(40, 20))
    fake = FakeOpenRouter(chat='{"objects":[{"x_min":0.5,"y_min":0.0,"x_max":1.0,"y_max":0.5}]}')
    mock_http(chain(fake))
    is_error, payload = call(tools.image_segment, image="src.png", prompt="cat", invert=False)
    assert not is_error, payload
    req = fake.requests[0]
    assert req.url.path == "/api/v1/chat/completions"
    body = body_of(req)
    content = body["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": '/detect {"object": "cat"}'}
    assert content[1]["type"] == "image_url" and content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "strategy" not in body  # directives are never sent
    out = open_png(Path(payload["files"][0]["path"]).read_bytes())
    assert out.size == (40, 20) and out.getpixel((30, 5)) == 255 and out.getpixel((5, 5)) == 0 and out.getpixel((30, 15)) == 0


def test_openrouter_vector_layered(stack_env, mock_http):
    stack_env.configure("VECTOR", OPENROUTER_URL, "recraft/recraft-v4.1-vector")
    fake = FakeOpenRouter(SVG_OUT, media_type="image/svg+xml")
    mock_http(chain(fake))
    is_error, payload = call(tools.vector_generate, prompt="logo", style="flat", layered=True)
    assert not is_error, payload
    body = body_of(fake.requests[0])
    assert body["output_format"] == "svg" and "Style: flat" in body["prompt"]
    f = payload["files"][0]
    assert f["mime"] == "image/svg+xml" and f["path"].endswith(".svg")
    text = Path(f["path"]).read_text()
    assert text.count('inkscape:groupmode="layer"') == 2
    assert payload["layers"][0]["layer_count"] == 2


def test_openrouter_vector_rejects_raster(stack_env, mock_http):
    stack_env.configure("VECTOR", OPENROUTER_URL, "google/gemini-nano-banana-2.1")
    mock_http(chain(FakeOpenRouter(png_bytes())))
    is_error, payload = call(tools.vector_generate, prompt="logo")
    assert is_error and "instead of SVG" in payload["error"] and "strategy" in payload["error"]


def test_openrouter_upscale_resizes_to_exact_target(stack_env, mock_http, isolated):
    stack_env.configure("UPSCALE", OPENROUTER_URL, "black-forest-labs/flux-3-image")
    (isolated / "small.png").write_bytes(pattern_png(20, 10))
    fake = FakeOpenRouter(png_bytes(64, 32, (100, 100, 100)))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_upscale, image="small.png", scale=3)
    assert not is_error, payload
    body = body_of(fake.requests[0])
    assert body["resolution"] == "1K" and "higher resolution" in body["prompt"]
    f = payload["files"][0]
    assert (f["width"], f["height"]) == (60, 30)
    assert payload["fidelity"][0]["drift"] > 0


def test_openrouter_error_shows_host_and_model_only(stack_env, mock_http):
    key = stack_env.configure("GEN", OPENROUTER_URL, "bad/model")
    mock_http(chain(FakeOpenRouter(status=400, error={"error": {"code": 400, "message": f"bad key {key} for model"}})))
    is_error, payload = call(tools.image_generate, prompt="x")
    assert is_error
    err = payload["error"]
    assert "openrouter GEN call to openrouter.ai (model bad/model) failed: HTTP 400" in err
    assert key not in json.dumps(payload) and "/api/v1" not in err


# --- Opper -----------------------------------------------------------------------------------------


def test_opper_generate_body_auth_and_mime(stack_env, mock_http):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (5, 5), (1, 2, 3)).save(buf, "JPEG")
    key = stack_env.configure("GEN", OPPER_URL, "vertexai/gemini-3.1-flash-image")
    fake = FakeOpper(buf.getvalue(), mime_type="image/jpeg")
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="a lighthouse", aspect_ratio="16:9", seed=3)
    assert not is_error, payload
    post = next(r for r in fake.requests if r.method == "POST")
    assert str(post.url) == "https://api.opper.ai/v3/images"
    assert post.headers["authorization"] == f"Bearer {key}"
    body = body_of(post)
    assert body["model"] == "vertexai/gemini-3.1-flash-image" and body["prompt"] == "a lighthouse"
    assert body["aspect_ratio"] == "16:9" and body["response_format"] == "b64_json"
    # Gemini declares no passthrough parameters: a seed would be forwarded verbatim and rejected
    assert "parameters" not in body
    assert any("seed dropped" in n for n in payload["notes"])
    assert payload["files"][0]["mime"] == "image/jpeg" and payload["files"][0]["path"].endswith(".jpg")
    catalog_get = next(r for r in fake.requests if r.method == "GET")
    assert catalog_get.url.path == "/v3/images/models" and "authorization" not in catalog_get.headers


def test_opper_size_normalised_against_catalog(stack_env, mock_http):
    stack_env.configure("GEN", OPPER_URL, "openai/gpt-image-2.5-flare")
    fake = FakeOpper(png_bytes())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x", aspect_ratio="3:2", quality="ultra")
    assert not is_error
    body = body_of(next(r for r in fake.requests if r.method == "POST"))
    assert body["size"] == "1536x1024" and "aspect_ratio" not in body and "quality" not in body
    assert any("sent as size 1536x1024" in n for n in payload["notes"])


def test_opper_normalise_dimensions_unit():
    img = {"aspect_ratios": ["1:1", "16:9"]}
    fields, notes = normalise_dimensions("1920x1080", None, img)
    assert fields == {"aspect_ratio": "16:9"} and notes
    fields, _ = normalise_dimensions("2K", None, {"resolutions": ["1k", "2k"]})
    assert fields == {"resolution": "2k"}
    fields, _ = normalise_dimensions(None, "21:9", {})
    assert fields == {"aspect_ratio": "21:9"}


def test_opper_masked_edit_convention_by_model(stack_env, mock_http, isolated):
    assert mask_convention_for("openai/gpt-image-2.5-sunburst") == "alpha-transparent"
    assert mask_convention_for("fal/ideogram-v4.5-edit") == "black-edit"
    assert mask_convention_for("bytedance:ap/seedream-5") == "white-edit"
    assert mask_convention_for("x", "black-edit") == "black-edit"
    stack_env.configure("EDIT", OPPER_URL, "fal/ideogram-v4.5-edit")
    (isolated / "src.png").write_bytes(pattern_png(16, 16))
    from PIL import Image

    m = Image.new("L", (16, 16), 0)
    m.paste(255, (0, 0, 8, 16))
    m.save(isolated / "m.png")
    fake = FakeOpper(png_bytes(16, 16, (9, 9, 9)))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_edit, image="src.png", instruction="add a hat", mask="m.png")
    assert not is_error, payload
    body = body_of(next(r for r in fake.requests if r.method == "POST"))
    assert decode_data_url(body["image"]) == pattern_png(16, 16)
    sent = open_png(decode_data_url(body["mask"]))
    assert sent.getpixel((2, 2)) == 0 and sent.getpixel((12, 2)) == 255  # black = edit for Ideogram
    assert "reference_images" not in body


def test_opper_transparent_checks_catalog_background(stack_env, mock_http):
    stack_env.configure_cutout(OPPER_URL, "openai/gpt-image-2")
    fake = FakeOpper(rgba_cutout())
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate_transparent, prompt="x")
    assert is_error and "not 'transparent'" in payload["error"]
    assert not [r for r in fake.requests if r.method == "POST"]  # nothing was paid for

    stack_env.configure_cutout(OPPER_URL, "openai/gpt-image-2.5-flare")
    is_error, payload = call(tools.image_generate_transparent, prompt="x", size="1024x1024")
    assert not is_error, payload
    body = body_of(next(r for r in fake.requests if r.method == "POST"))
    assert body["parameters"] == {"background": "transparent", "output_format": "png"} and body["size"] == "1024x1024"


def test_opper_async_job_polls_and_downloads_without_auth(stack_env, mock_http):
    key = stack_env.configure("GEN", OPPER_URL, "openai/gpt-image-2.5-sunburst", params={"async": True})
    fake = FakeOpper(png_bytes(3, 3), async_job=True)
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="slow one")
    assert not is_error, payload
    post = next(r for r in fake.requests if r.method == "POST")
    assert body_of(post)["async"] is True
    polls = [r for r in fake.requests if r.url.path.endswith("/status")]
    assert len(polls) == 2 and all(r.headers["authorization"] == f"Bearer {key}" for r in polls)
    download = next(r for r in fake.requests if r.url.host == "storage.opper.example")
    assert "authorization" not in download.headers  # the key never leaves api.opper.ai
    side = Path(payload["files"][0]["path"] + ".json").read_text()
    assert "X-Amz-Signature" not in side and key not in side


def test_opper_trace_defaults_to_chat_strategy(stack_env, mock_http, isolated):
    stack_env.configure("TRACE", OPPER_URL, "anthropic/claude-sonnet-4.5")
    (isolated / "logo.png").write_bytes(png_bytes(8, 8))
    fake = FakeOpper(chat="Here you go:\n```svg\n<svg viewBox='0 0 8 8'><rect width='8' height='8' fill='red'/></svg>\n```")
    mock_http(chain(fake))
    is_error, payload = call(tools.image_vectorize, image="logo.png")
    assert not is_error, payload
    req = fake.requests[0]
    assert req.url.path == "/v3/compat/chat/completions"
    msgs = body_of(req)["messages"]
    assert msgs[0]["role"] == "system" and msgs[1]["content"][1]["type"] == "image_url"
    text = Path(payload["files"][0]["path"]).read_text()
    assert 'xmlns="http://www.w3.org/2000/svg"' in text  # namespace repaired
    assert payload["warnings"]


def test_opper_error_shape(stack_env, mock_http):
    key = stack_env.configure("GEN", OPPER_URL, "fal/flux-2-pro")
    mock_http(chain(FakeOpper(status=400)))
    is_error, payload = call(tools.image_generate, prompt="x")
    assert is_error and "model rejected the request" in payload["error"] and "api.opper.ai" in payload["error"]
    assert key not in json.dumps(payload)


def test_opper_504_hint(stack_env, mock_http):
    stack_env.configure("GEN", OPPER_URL, "m")
    mock_http(lambda req: json_response({"error": {"message": "deadline"}}, 504))
    is_error, payload = call(tools.image_generate, prompt="x")
    assert is_error and '"async": true' in payload["error"]


# --- OpenAI-compatible -------------------------------------------------------------------------------


def test_openai_generations_json(stack_env, mock_http):
    key = stack_env.configure("GEN", COMPAT_URL, "gpt-image-2.5-flare")
    fake = FakeCompat(png_bytes(4, 4))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x", aspect_ratio="16:9", quality="high", output_format="webp")
    assert not is_error, payload
    req = fake.requests[0]
    assert str(req.url) == "https://llm.example.test/v1/images/generations"
    assert req.headers["authorization"] == f"Bearer {key}"
    assert body_of(req) == {"model": "gpt-image-2.5-flare", "prompt": "x", "size": "1536x864", "quality": "high",
                            "output_format": "webp"}
    assert payload["adapter"] == "openai"


def test_openai_masked_edit_multipart(stack_env, mock_http, isolated):
    stack_env.configure("EDIT", COMPAT_URL, "gpt-image-2.5-sunburst")
    import io

    from PIL import Image

    jpg = io.BytesIO()
    Image.new("RGB", (16, 12), (50, 60, 70)).save(jpg, "JPEG")
    (isolated / "src.jpg").write_bytes(jpg.getvalue())
    (isolated / "ref.png").write_bytes(png_bytes(4, 4))
    m = Image.new("L", (16, 12), 0)
    m.paste(255, (4, 4, 12, 8))
    m.save(isolated / "m.png")
    fake = FakeCompat(png_bytes(16, 12, (255, 0, 0)))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_edit, image="src.jpg", instruction="add a door", mask="m.png",
                             references=["ref.png"], n=2, params={"input_fidelity": "high"})
    assert not is_error, payload
    req = fake.requests[0]
    assert req.url.path == "/v1/images/edits" and req.headers["content-type"].startswith("multipart/form-data")
    parts = parse_multipart(req)
    fields = {n: d.decode() for n, fn, _t, d in parts if fn is None}
    assert fields == {"model": "gpt-image-2.5-sunburst", "prompt": "add a door", "n": "2", "input_fidelity": "high"}
    images = [(fn, t, d) for n, fn, t, d in parts if n == "image[]"]
    assert len(images) == 2 and images[0][1] == "image/png" and images[0][0].endswith(".png")  # source sent as PNG
    assert open_png(images[0][2]).size == (16, 12)
    mask_part = next((t, d) for n, fn, t, d in parts if n == "mask")
    mk = open_png(mask_part[1])
    assert mask_part[0] == "image/png" and mk.mode == "RGBA" and mk.size == (16, 12)
    assert mk.getpixel((6, 5))[3] == 0 and mk.getpixel((0, 0))[3] == 255  # transparent = edit


def test_openai_url_output_is_downloaded(stack_env, mock_http):
    stack_env.configure("GEN", COMPAT_URL, "m")
    fake = FakeCompat(png_bytes(3, 3), url_output=True)
    mock_http(chain(fake))
    is_error, payload = call(tools.image_generate, prompt="x")
    assert not is_error and payload["files"][0]["width"] == 3
    dl = next(r for r in fake.requests if r.url.host == "cdn.example.test")
    assert "authorization" not in dl.headers


def test_openai_vector_uses_chat_by_default(stack_env, mock_http):
    stack_env.configure("VECTOR", COMPAT_URL, "gpt-5")
    fake = FakeCompat(chat='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect width="4" height="4"/></svg>')
    mock_http(chain(fake))
    is_error, payload = call(tools.vector_generate, prompt="square")
    assert not is_error, payload
    assert fake.requests[0].url.path == "/v1/chat/completions"
    stack_env.configure("VECTOR", COMPAT_URL, "gpt-5", params={"strategy": "image"})
    is_error, payload = call(tools.vector_generate, prompt="square")
    assert is_error and "no SVG output" in payload["error"]


def test_openai_size_mapping():
    # 1024x576 would be 589,824 px, below GPT Image 2's 655,360 minimum: the next exact 16:9 size
    assert openai_size("1K", "16:9") == ("1280x720", None)
    assert openai_size(None, None) == (None, None)
    assert openai_size("1024x1024", "16:9") == ("1024x1024", None)
    size, note = openai_size(None, "5:1")
    assert size is None and "outside" in note


# --- local adapters -------------------------------------------------------------------------------


def test_local_upscale_is_lanczos_and_exact(stack_env, mock_http, isolated):
    stack_env.set(IMAGE_UPSCALE_API="local")
    (isolated / "s.png").write_bytes(rgba_cutout(10, 6))
    seen = mock_http(lambda req: (_ for _ in ()).throw(AssertionError("no HTTP for local adapters")))
    is_error, payload = call(tools.image_upscale, image="s.png", scale=2.5)
    assert not is_error, payload
    assert not seen
    f = payload["files"][0]
    assert (f["width"], f["height"]) == (25, 15) and payload["adapter"] == "local" and payload["url_host"] is None
    assert open_png(Path(f["path"]).read_bytes()).mode == "RGBA"


def test_local_trace_with_vtracer_layered_by_colour(stack_env, isolated):
    from PIL import Image

    stack_env.set(IMAGE_TRACE_API="local")
    im = Image.new("RGB", (48, 48), (255, 255, 255))
    im.paste((220, 20, 20), (4, 4, 24, 24))
    im.paste((20, 20, 220), (20, 20, 44, 44))
    im.save(isolated / "two.png")
    is_error, payload = call(tools.image_vectorize, image="two.png", layered=True, params={"filter_speckle": 2})
    assert not is_error, payload
    text = Path(payload["files"][0]["path"]).read_text()
    assert "<svg" in text and 'inkscape:groupmode="layer"' in text
    labels = [lay["label"] for lay in payload["layers"][0]["layers"]]
    assert len(labels) == len(set(labels)) >= 3  # one layer per colour, no splits needed (cutout mode)
    assert any("vtracer" in n for n in payload["notes"])
    from stack_mcp.image_router.render import render_svg

    png = open_png(render_svg(text)).convert("RGB")
    assert png.getpixel((10, 10))[0] > 180 and png.getpixel((35, 35))[2] > 180


def test_local_trace_rejects_unknown_options(stack_env, isolated):
    stack_env.set(IMAGE_TRACE_API="local", IMAGE_TRACE_PARAMS="'{\"speed\": 3}'")
    (isolated / "x.png").write_bytes(png_bytes())
    is_error, payload = call(tools.image_vectorize, image="x.png")
    assert is_error and "unknown vtracer option" in payload["error"]


def test_local_api_for_unsupported_op_is_a_config_error(stack_env):
    stack_env.set(IMAGE_EDIT_API="local", IMAGE_EDIT_URL=OPENROUTER_URL, IMAGE_EDIT_MODEL="m", IMAGE_EDIT_KEY=FAKE_KEYS["EDIT"])
    is_error, payload = call(tools.image_edit, image="x.png", instruction="y")
    assert is_error and "only available for TRACE and UPSCALE" in payload["error"]


@pytest.mark.parametrize("op_tool", ["image_generate", "image_segment", "image_upscale"])
def test_every_op_tool_reports_not_configured(op_tool):
    fn = getattr(tools, op_tool)
    kwargs = {"prompt": "x"} if op_tool == "image_generate" else {"image": "x.png", **({"prompt": "y"} if op_tool == "image_segment" else {})}
    is_error, payload = call(fn, **kwargs)
    assert is_error and "is not configured" in payload["error"] and payload["missing_env"]


# --- more branches ---------------------------------------------------------------------------------


def test_openai_reference_cutout_and_mask_paths_use_edits(stack_env, mock_http, isolated):
    for op in ("REF", "TRANSPARENT", "BG_REMOVAL", "SEGMENT"):
        stack_env.configure(op, COMPAT_URL, "gpt-image-2.5-flare")
    (isolated / "a.png").write_bytes(pattern_png(8, 8))
    fake = FakeCompat(rgba_cutout(8, 8))
    mock_http(chain(fake))
    assert not call(tools.image_generate_with_references, prompt="same", references=["a.png", "a.png"])[0]
    assert not call(tools.image_remove_background, image="a.png")[0]
    assert not call(tools.image_segment, image="a.png", prompt="the dog")[0]
    ref, cut, msk = fake.requests
    assert all(r.url.path == "/v1/images/edits" for r in (ref, cut, msk))
    ref_parts = parse_multipart(ref)
    assert [n for n, *_ in ref_parts].count("image[]") == 2 and not any(n == "mask" for n, *_ in ref_parts)
    cut_fields = {n: d.decode() for n, fn, _t, d in parse_multipart(cut) if fn is None}
    assert cut_fields["background"] == "transparent" and cut_fields["output_format"] == "png"
    assert "Remove the background" in cut_fields["prompt"]
    mask_fields = {n: d.decode() for n, fn, _t, d in parse_multipart(msk) if fn is None}
    assert "the dog" in mask_fields["prompt"] and "pure white" in mask_fields["prompt"]


def test_opper_upscale_and_async_failure(stack_env, mock_http, isolated):
    stack_env.configure("UPSCALE", OPPER_URL, "openai/gpt-image-2")
    (isolated / "s.png").write_bytes(pattern_png(10, 10))
    fake = FakeOpper(png_bytes(40, 40))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_upscale, image="s.png", scale=2)
    assert not is_error and (payload["files"][0]["width"], payload["files"][0]["height"]) == (20, 20)
    body = body_of(fake.requests[-1])
    assert body["image"].startswith("data:image/png;base64,") and "higher resolution" in body["prompt"]

    stack_env.configure("GEN", OPPER_URL, "m", params={"async": True})

    def failing(req):
        if req.url.path == "/v3/images":
            return json_response({"id": "gen_9", "status_url": "https://evil.example/steal"}, 202)
        if req.url.path == "/v3/artifacts/gen_9/status":
            assert req.url.host == "api.opper.ai"  # a foreign status_url is never followed
            return json_response({"id": "gen_9", "status": "failed", "error": "content policy"})
        return None

    mock_http(chain(failing))
    is_error, payload = call(tools.image_generate, prompt="x")
    assert is_error and "async job failed: content policy" in payload["error"]


def test_detect_strategy_generic_prompt_fenced_json_and_invert(stack_env, mock_http, isolated):
    stack_env.configure("SEGMENT", OPPER_URL, "openai/gpt-5.4", params={"strategy": "detect"})
    (isolated / "src.png").write_bytes(pattern_png(20, 20))
    fake = FakeOpper(chat='Sure!\n```json\n{"objects": [{"box": [0, 0, 0.5, 0.5]}]}\n```')
    mock_http(chain(fake))
    is_error, payload = call(tools.image_segment, image="src.png", prompt="logo", invert=True)
    assert not is_error, payload
    req = fake.requests[0]
    assert req.url.path == "/v3/compat/chat/completions"
    assert "Find every instance of: logo" in body_of(req)["messages"][0]["content"][0]["text"]
    out = open_png(Path(payload["files"][0]["path"]).read_bytes())
    assert out.getpixel((2, 2)) == 0 and out.getpixel((15, 15)) == 255  # inverted box
    fake.chat = '{"objects": []}'
    is_error, payload = call(tools.image_segment, image="src.png", prompt="unicorn")
    assert not is_error and "found no 'unicorn'" in payload["warnings"][0]
    fake.chat = "no idea"
    is_error, payload = call(tools.image_segment, image="src.png", prompt="x")
    assert is_error and "no JSON object" in payload["error"]


def test_remove_background_fallbacks_are_reported(stack_env, mock_http, isolated):
    stack_env.configure_cutout(OPENROUTER_URL, "m")
    (isolated / "p.png").write_bytes(pattern_png(16, 16))
    fake = FakeOpenRouter(rgba_cutout(32, 16))  # different aspect ratio: alpha cannot be transferred
    mock_http(chain(fake))
    is_error, payload = call(tools.image_remove_background, image="p.png")
    assert not is_error and "aspect ratio" in payload["warnings"][0]
    fake.image = rgba_cutout(16, 16)
    is_error, payload = call(tools.image_remove_background, image="p.png", preserve_pixels=False)
    assert not is_error and not payload["warnings"] and payload["fidelity"] is None
    fake.image = png_bytes(16, 16)
    is_error, payload = call(tools.image_remove_background, image="p.png")
    assert not is_error and "no transparent pixels" in payload["warnings"][0]
