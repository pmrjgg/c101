"""Input resolution, MIME sniffing, output naming and sidecar hygiene."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from stack_mcp.image_router import http
from stack_mcp.image_router.io import (
    InputError,
    OutputBlob,
    file_stem,
    output_directory,
    resolve_input,
    sanitize,
    slugify,
    sniff_mime,
    to_data_uri,
    write_output,
)

from .conftest import FAKE_KEYS, OPENROUTER_URL, png_bytes


def test_sniff_mime():
    import io as _io

    from PIL import Image

    assert sniff_mime(png_bytes()) == "image/png"
    for fmt, mime in (("JPEG", "image/jpeg"), ("WEBP", "image/webp"), ("GIF", "image/gif")):
        buf = _io.BytesIO()
        Image.new("RGB", (2, 2)).save(buf, format=fmt)
        assert sniff_mime(buf.getvalue()) == mime
    assert sniff_mime(b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>') == "image/svg+xml"
    assert sniff_mime(b"\xef\xbb\xbf  <svg></svg>") == "image/svg+xml"
    assert sniff_mime(b"hello") is None


def test_resolve_inputs_all_kinds(isolated, mock_http, monkeypatch):
    data = png_bytes(3, 2)
    (isolated / "sub").mkdir()
    (isolated / "sub" / "a.png").write_bytes(data)
    home = isolated / "home"
    home.mkdir()
    (home / "b.png").write_bytes(data)
    monkeypatch.setenv("HOME", str(home))
    mock_http(lambda req: httpx.Response(200, content=data, headers={"content-type": "application/octet-stream"}))

    async def go():
        async with http.new_client() as client:
            return [
                await resolve_input("sub/a.png", client),  # relative to CLAUDE_PROJECT_DIR
                await resolve_input("~/b.png", client),
                await resolve_input((isolated / "sub" / "a.png").as_uri(), client),
                await resolve_input(to_data_uri(data, "image/png"), client),
                await resolve_input("https://cdn.example.com/x/c.png?sig=abc", client),
            ]

    files = asyncio.run(go())
    for f in files:
        assert f.data == data and f.mime == "image/png"
    assert files[0].name == "a.png" and files[0].source == str(isolated / "sub" / "a.png")
    assert files[3].source.startswith("data:image/png (")  # never the payload
    assert files[4].source == "https://cdn.example.com/x/c.png"  # query (signatures) stripped


def test_resolve_missing_file():
    with pytest.raises(InputError, match="file not found"):
        asyncio.run(resolve_input("nope.png"))


def test_output_directory_default_and_explicit(isolated):
    d = output_directory(None, ".stack/images", datetime(2026, 10, 19, 12, 0, 0))
    assert d == isolated / ".stack" / "images" / "20261019"
    assert output_directory("out/x", ".stack/images") == isolated / "out" / "x"
    assert output_directory(str(isolated / "abs"), ".stack/images") == isolated / "abs"


def test_slug_and_stem():
    assert slugify("A Cat, on a  Mat! (ünïcode)") == "a-cat-on-a-mat-unicode"
    assert slugify("!!!") == "image"
    stem = file_stem(None, "Red fox logo", "gen", datetime(2026, 1, 2, 3, 4, 5))
    assert stem == "red-fox-logo-030405-gen"
    assert file_stem("hero", "ignored", "edit", datetime(2026, 1, 2, 3, 4, 5)) == "hero-030405-edit"


def test_write_output_collision_free_and_sidecar_clean(isolated, stack_env):
    for op in ("GEN", "EDIT"):
        stack_env.configure(op, OPENROUTER_URL, "m")
    directory = isolated / "out"
    blob = OutputBlob(png_bytes(4, 3), "image/png", "https://storage.example.test/files/x.png?token=zzz")
    big_b64 = "A" * 500
    sidecar = {
        "tool": "image_generate",
        "op": "GEN",
        "adapter": "openrouter",
        "url_host": "openrouter.ai",
        "model": "google/gemini-nano-banana-2.1",
        "prompt": "a red fox",
        "params": {
            "n": 1,
            "params": {"api_key": "should-not-appear", "note": f"leak {FAKE_KEYS['GEN']} here", "blob": big_b64},
            "image": to_data_uri(png_bytes(), "image/png"),
        },
        "inputs": [{"source": "data:image/png (68 bytes)", "mime": "image/png", "bytes": 68}],
    }
    a = write_output(blob, directory, "red-fox-120000-gen", sidecar)
    b = write_output(blob, directory, "red-fox-120000-gen", sidecar)
    assert a.path.name == "red-fox-120000-gen.png"
    assert b.path.name == "red-fox-120000-gen-2.png"
    assert (a.width, a.height, a.mime) == (4, 3, "image/png")

    text = Path(str(a.path) + ".json").read_text()
    meta = json.loads(text)
    assert meta["tool"] == "image_generate" and meta["op"] == "GEN" and meta["prompt"] == "a red fox"
    assert meta["url_host"] == "openrouter.ai" and meta["model"].startswith("google/") and meta["created"]
    assert meta["inputs"][0]["mime"] == "image/png"
    assert meta["source_url"] == "https://storage.example.test/files/x.png"
    # no key material, no base64 payloads
    for op in ("GEN", "EDIT"):
        assert FAKE_KEYS[op] not in text
    assert "should-not-appear" not in text
    assert big_b64 not in text and "base64," not in text
    assert meta["params"]["params"]["api_key"] == "<redacted>"


def test_sanitize_nested():
    out = sanitize({"a": ["data:image/png;base64,AAAA", {"token": "x"}], "b": b"123", "c": 1.5})
    assert out == {"a": ["<data:image/png;base64 26 chars>", {"token": "<redacted>"}], "b": "<3 bytes>", "c": 1.5}


def test_sanitize_strips_url_credentials_everywhere():
    from stack_mcp.image_router.io import display_url, redact_urls

    signed = "https://cdn.example.com/a/b.png?X-Amz-Signature=SIG&X-Amz-Credential=CRED#frag"
    out = sanitize({"request": {"input_references": [{"image_url": {"url": signed}}], "image": signed},
                    "note": f"fetched {signed} ok", "auth": "https://user:pass@host.example/x"})
    text = json.dumps(out)
    for secret in ("SIG", "CRED", "frag", "user:pass"):
        assert secret not in text
    assert out["request"]["image"] == "https://cdn.example.com/a/b.png?<redacted>#<redacted>"
    assert out["note"] == "fetched https://cdn.example.com/a/b.png?<redacted>#<redacted> ok"
    assert display_url(signed) == "https://cdn.example.com/a/b.png"
    assert display_url("https://u:p@h.example:8443/x?y=1") == "https://h.example:8443/x"
    assert redact_urls("no urls here") == "no urls here"
