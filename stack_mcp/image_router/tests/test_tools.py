"""Tool layer: exposure, status, not-configured errors, svg_transform, local tools, secret hygiene."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from stack_mcp.image_router import tools
from stack_mcp.image_router.server import build_server, main, status_lines

from .conftest import COMPAT_URL, FAKE_KEYS, FIXTURES, OPENROUTER_URL, OPPER_URL, open_png, payload_of, png_bytes, rgba_cutout
from .fakes import FakeCompat, FakeOpenRouter, FakeOpper, body_of, chain

OP_TOOL_NAMES = {
    "image_generate", "image_generate_with_references", "image_edit", "image_segment", "image_generate_transparent",
    "image_remove_background", "image_upscale", "vector_generate", "image_vectorize",
}
LOCAL_TOOL_NAMES = {
    "image_ops_status", "image_info", "mask_convert", "svg_optimize", "svg_inspect", "svg_render", "svg_layers",
    "svg_layerize", "layers_compose", "export_pdf",
}


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def listed() -> set[str]:
    return {t.name for t in asyncio.run(build_server().list_tools())}


# --- exposure ----------------------------------------------------------------------------------------


def test_tool_exposure_follows_configuration(stack_env):
    assert listed() == LOCAL_TOOL_NAMES  # nothing configured: status + local tools only
    stack_env.configure("GEN", OPENROUTER_URL, "google/gemini-nano-banana-2.1")
    assert listed() == LOCAL_TOOL_NAMES | {"image_generate"}
    stack_env.set(IMAGE_TRACE_API="local")  # local adapter: no URL/KEY/MODEL needed
    assert "image_vectorize" in listed()
    stack_env.set(IMAGE_VECTOR_MANIPULATION_MODEL="openai/gpt-5.4")  # a model alone is not a configuration
    assert "svg_transform" not in listed()
    stack_env.configure("VECTOR_MANIPULATION", OPENROUTER_URL, "openai/gpt-5.4")
    assert "svg_transform" in listed()
    stack_env.set(IMAGE_VECTOR_MANIPULATION_MODEL="claude")
    assert "svg_transform" not in listed()
    stack_env.configure("SEGMENT", "https://queue.fal.run", "fal-ai/sam-3/image")
    assert "image_segment" in listed()
    stack_env.set(IMAGE_GEN_KEY="")  # removing a key hides the tool again, without a restart
    assert "image_generate" not in listed()
    stack_env.configure("GEN", OPENROUTER_URL, "m")
    stack_env.configure_cutout(OPENROUTER_URL, "m")
    for op in ("REF", "EDIT", "UPSCALE", "VECTOR"):
        stack_env.configure(op, OPENROUTER_URL, "m")
    assert listed() == OP_TOOL_NAMES | LOCAL_TOOL_NAMES


def test_tool_metadata(stack_env):
    for op in ("GEN", "REF", "EDIT", "UPSCALE", "VECTOR"):
        stack_env.configure(op, OPENROUTER_URL, "m")
    stack_env.configure_cutout(OPENROUTER_URL, "m")
    stack_env.configure("SEGMENT", OPENROUTER_URL, "m")
    stack_env.set(IMAGE_TRACE_API="local")
    server = build_server()
    assert server.name == "image"
    tools_ = {t.name: t for t in asyncio.run(server.list_tools())}
    gen = tools_["image_generate"]
    assert "prompt" in gen.input_schema["required"] and "IMAGE_GEN_URL" in gen.description
    assert gen.annotations.open_world_hint is True and gen.annotations.read_only_hint is False
    status = tools_["image_ops_status"]
    assert status.annotations.read_only_hint is True and status.annotations.open_world_hint is False
    assert tools_["image_generate_with_references"].input_schema["properties"]["references"]["minItems"] == 1


# --- status + not configured ------------------------------------------------------------------------


def test_image_ops_status_reports_without_keys(stack_env, env_file):
    key = stack_env.configure("GEN", OPENROUTER_URL, "google/gemini-nano-banana-2.1")
    stack_env.configure("EDIT", OPPER_URL, "openai/gpt-image-2.5-sunburst", params={"mask_convention": "alpha-transparent"})
    stack_env.set(IMAGE_TRACE_API="local", IMAGE_REF_URL=COMPAT_URL)
    is_error, payload = call(tools.image_ops_status)
    assert not is_error
    ops = payload["ops"]
    assert ops["GEN"] == {
        "op": "GEN", "tools": ["image_generate"], "configured": True, "adapter": "openrouter",
        "adapter_source": "detected", "url_host": "openrouter.ai", "model": "google/gemini-nano-banana-2.1",
        "params_keys": [], "directives": {}, "missing_env": [],
        "env": ["IMAGE_GEN_URL", "IMAGE_GEN_KEY", "IMAGE_GEN_MODEL", "IMAGE_GEN_API", "IMAGE_GEN_PARAMS"],
    }
    assert ops["EDIT"]["adapter"] == "opper" and ops["EDIT"]["directives"] == {"mask_convention": "alpha-transparent"}
    assert ops["TRACE"]["configured"] and ops["TRACE"]["adapter"] == "local"
    assert ops["REF"]["missing_env"] == ["IMAGE_REF_MODEL", "IMAGE_REF_KEY"]
    assert ops["TRANSPARENT"]["tools"] == ["image_generate_transparent"]
    assert ops["BG_REMOVAL"]["tools"] == ["image_remove_background"]
    assert ops["SEGMENT"]["tools"] == ["image_segment"]
    assert ops["VECTOR_MANIPULATION"]["mode"] == "claude" and payload["svg_transform_exposed"] is False
    assert set(payload["configured"]) == {"GEN", "EDIT", "TRACE", "VECTOR_MANIPULATION"}
    assert payload["env_file"] == str(env_file) and payload["env_file_exists"] is True
    assert set(payload["adapters"]["local"]) == {"TRACE", "UPSCALE"}
    text = json.dumps(payload)
    assert key not in text and FAKE_KEYS["EDIT"] not in text


def test_not_configured_error_names_env_vars():
    is_error, payload = call(tools.image_generate, prompt="a red fox")
    assert is_error and payload["ok"] is False and payload["tool"] == "image_generate"
    assert payload["missing_env"] == ["IMAGE_GEN_URL", "IMAGE_GEN_MODEL", "IMAGE_GEN_KEY"]
    assert "IMAGE_GEN_URL" in payload["error"] and "stack.env" in payload["error"] and "No fallback" in payload["error"]
    is_error, payload = call(tools.image_remove_background, image="x.png")
    assert is_error and payload["op"] == "BG_REMOVAL" and "IMAGE_BG_REMOVAL_KEY" in payload["missing_env"]


def test_bad_input_is_a_clean_error(stack_env):
    stack_env.configure("EDIT", OPENROUTER_URL, "m")
    is_error, payload = call(tools.image_edit, image="missing.png", instruction="x")
    assert is_error and "file not found" in payload["error"]


def test_server_check_mode(stack_env, capsys):
    stack_env.configure("GEN", OPENROUTER_URL, "m")
    assert main(["--check", "--mode", "all"]) == 0
    err = capsys.readouterr().err
    assert "GEN" in err and "openrouter openrouter.ai m" in err and FAKE_KEYS["GEN"] not in err
    assert any("NOT CONFIGURED" in line for line in status_lines())


# --- svg_transform -------------------------------------------------------------------------------------


def test_svg_transform_disabled_while_claude(isolated):
    (isolated / "a.svg").write_bytes((FIXTURES / "scene.svg").read_bytes())
    is_error, payload = call(tools.svg_transform, svg_path="a.svg", instruction="make it blue")
    assert is_error and "svg_transform is disabled" in payload["error"] and "Read/Edit" in payload["error"]


def test_svg_transform_external_model(stack_env, mock_http, isolated):
    key = stack_env.configure("VECTOR_MANIPULATION", COMPAT_URL, "gpt-5.4")
    src = (FIXTURES / "scene.svg").read_bytes()
    (isolated / "a.svg").write_bytes(src)
    reply = "```svg\n" + src.decode().replace("#e63946", "#2a9d8f").split("?>", 1)[1] + "\n```"
    fake = FakeCompat(chat=reply)
    mock_http(chain(fake))
    is_error, payload = call(tools.svg_transform, svg_path="a.svg", instruction="recolour the square teal")
    assert not is_error, payload
    req = fake.requests[0]
    assert str(req.url) == "https://llm.example.test/v1/chat/completions" and req.headers["authorization"] == f"Bearer {key}"
    body = body_of(req)
    assert body["model"] == "gpt-5.4" and "recolour the square teal" in body["messages"][1]["content"]
    assert "#e63946" in body["messages"][1]["content"]  # the SVG text was sent
    out = Path(payload["files"][0]["path"])
    assert "#2a9d8f" in out.read_text() and (isolated / "a.svg").read_bytes() == src  # input untouched
    assert payload["op"] == "VECTOR_MANIPULATION" and payload["url_host"] == "llm.example.test"


def test_svg_transform_rejects_malformed_reply(stack_env, mock_http, isolated):
    stack_env.configure("VECTOR_MANIPULATION", OPENROUTER_URL, "anthropic/claude-sonnet-4.5")
    (isolated / "a.svg").write_bytes((FIXTURES / "flat.svg").read_bytes())
    mock_http(chain(FakeOpenRouter(chat="<svg><g></svg>")))
    is_error, payload = call(tools.svg_transform, svg_path="a.svg", instruction="x")
    assert is_error and "not well-formed" in payload["error"]
    assert not list(isolated.rglob("*-transformed-*.svg"))  # nothing written for an invalid reply
    mock_http(chain(FakeOpenRouter(chat="Sorry, I can't.")))
    is_error, payload = call(tools.svg_transform, svg_path="a.svg", instruction="x")
    assert is_error and "no <svg>" in payload["error"]


# --- local tools ------------------------------------------------------------------------------------------


def test_image_info(isolated):
    (isolated / "c.png").write_bytes(rgba_cutout(12, 8))
    is_error, payload = call(tools.image_info, image="c.png")
    assert not is_error
    assert (payload["width"], payload["height"], payload["mode"], payload["format"]) == (12, 8, "RGBA", "PNG")
    assert payload["has_alpha"] and payload["alpha_used"] and payload["bytes"] == len(rgba_cutout(12, 8))
    (isolated / "s.svg").write_bytes((FIXTURES / "scene.svg").read_bytes())
    is_error, payload = call(tools.image_info, image="s.svg")
    assert not is_error and payload["format"] == "SVG" and payload["layer_count"] == 3


def test_mask_convert_all_conventions(isolated):
    from PIL import Image

    m = Image.new("L", (10, 6), 0)
    m.paste(255, (0, 0, 5, 6))
    m.save(isolated / "m.png")
    (isolated / "big.png").write_bytes(png_bytes(20, 12))
    is_error, payload = call(tools.mask_convert, mask="m.png", to="alpha-transparent")
    assert not is_error
    out = open_png(Path(payload["files"][0]["path"]).read_bytes())
    assert Path(payload["files"][0]["path"]).name == "m.alpha-transparent.png"
    assert out.mode == "RGBA" and out.getpixel((1, 1))[3] == 0 and out.getpixel((8, 1))[3] == 255
    is_error, payload = call(tools.mask_convert, mask=payload["files"][0]["path"], to="black-edit", output_path="bk.png")
    bk = open_png((isolated / "bk.png").read_bytes())
    assert bk.getpixel((1, 1)) == 0 and bk.getpixel((8, 1)) == 255  # round trip through alpha
    is_error, payload = call(tools.mask_convert, mask="m.png", to="white-edit", invert=True, match_image="big.png", output_path="w.png")
    w = open_png((isolated / "w.png").read_bytes())
    assert w.size == (20, 12) and w.getpixel((2, 2)) == 0 and w.getpixel((15, 2)) == 255


# --- secret hygiene -------------------------------------------------------------------------------------


def test_no_secrets_in_results_sidecars_or_errors(stack_env, mock_http, isolated, capsys):
    keys = [
        stack_env.configure("GEN", OPENROUTER_URL, "google/gemini-nano-banana-2.1"),
        stack_env.configure("EDIT", OPPER_URL, "openai/gpt-image-2.5-sunburst"),
    ]
    (isolated / "src.png").write_bytes(png_bytes(8, 8))
    (isolated / "mask.png").write_bytes(png_bytes(8, 8, (255, 255, 255)))
    mock_http(chain(FakeOpenRouter(png_bytes(8, 8)), FakeOpper(png_bytes(8, 8))))
    results = [
        call(tools.image_generate, prompt="fox", params={"api_key": "should-not-appear", "token": keys[0]}),
        call(tools.image_edit, image="src.png", instruction="hat", mask="mask.png"),
    ]
    sidecars = [Path(f["path"] + ".json").read_text() for _, p in results for f in p["files"]]
    assert len(sidecars) == 2
    side = json.loads(sidecars[0])
    assert side["url_host"] == "openrouter.ai" and side["model"] == "google/gemini-nano-banana-2.1"
    assert side["op"] == "GEN" and side["adapter"] == "openrouter" and side["prompt"] == "fox" and side["created"]
    assert side["params"]["params"]["api_key"] == "<redacted>"
    edit_side = json.loads(sidecars[1])
    assert edit_side["request"]["image"].startswith("<data:image/png;base64")  # no payloads in sidecars
    # an error whose provider message echoes the key
    mock_http(chain(FakeOpenRouter(status=401, error={"error": {"code": 401, "message": f"invalid key {keys[0]}"}})))
    err = call(tools.image_generate, prompt="x")
    everything = json.dumps([r for _, r in results]) + "".join(sidecars) + json.dumps(err[1]) + capsys.readouterr().err
    for key in keys:
        assert key not in everything
    assert "should-not-appear" not in everything and "base64," not in "".join(sidecars)
    assert err[0] and "check IMAGE_GEN_KEY" in err[1]["error"] and "***" in err[1]["error"]


def test_svg_inputs_are_rendered_for_raster_ops(stack_env, mock_http, isolated):
    stack_env.configure("UPSCALE", OPENROUTER_URL, "m")
    (isolated / "icon.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><rect width="20" height="10" fill="#f00"/></svg>')
    fake = FakeOpenRouter(png_bytes(40, 20))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_upscale, image="icon.svg", scale=2)
    assert not is_error, payload
    ref = body_of(fake.requests[0])["input_references"][0]["image_url"]["url"]
    assert ref.startswith("data:image/png;base64,")
    side = json.loads(Path(payload["files"][0]["path"] + ".json").read_text())
    assert "rendered to PNG" in side["inputs"][0]["source"]


def test_svg_transform_exact_output_path(stack_env, mock_http, isolated):
    stack_env.configure("VECTOR_MANIPULATION", COMPAT_URL, "gpt-5.4")
    (isolated / "a.svg").write_bytes((FIXTURES / "flat.svg").read_bytes())
    (isolated / "out").mkdir()
    (isolated / "out" / "b.svg").write_text("old")
    mock_http(chain(FakeCompat(chat='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')))
    is_error, payload = call(tools.svg_transform, svg_path="a.svg", instruction="simplify", output_path="out/b.svg")
    assert not is_error, payload
    assert payload["files"][0]["path"] == str(isolated / "out" / "b.svg")
    assert "viewBox" in (isolated / "out" / "b.svg").read_text() and (isolated / "out" / "b.svg.json").is_file()
    is_error, payload = call(tools.svg_transform, svg_path="a.svg", instruction="x", output_path="a.svg")
    assert is_error and "must differ" in payload["error"]
