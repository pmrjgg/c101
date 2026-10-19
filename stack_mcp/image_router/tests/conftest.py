"""Shared fixtures: isolated env file + project dir, no real keys, instant backoff, mock HTTP."""

from __future__ import annotations

import base64
import io
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from PIL import Image

from stack_mcp.image_router import config, http
from stack_mcp.image_router.config import OPS
from stack_mcp.image_router.providers import openrouter, opper

FIXTURES = Path(__file__).parent / "fixtures"

# Obviously fake values, long enough for the redaction helpers to track them.
FAKE_KEYS = {op: f"sk-test-{op.lower()}-0123456789abcdef" for op in OPS}
EXTRA_ENV = ("OPENROUTER_API_KEY", "OPPER_API_KEY", "OPENAI_API_KEY", "OPENROUTER_APP_URL", "OPENROUTER_APP_TITLE")

OPENROUTER_URL = "https://openrouter.ai/api/v1"
OPPER_URL = "https://api.opper.ai"
COMPAT_URL = "https://llm.example.test/v1"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Every test: empty env file, empty project dir, no IMAGE_* vars, zero backoff, fresh caches.

    Yields the project directory (CLAUDE_PROJECT_DIR).
    """
    for k in list(os.environ):
        if k.startswith("IMAGE_") or k in EXTRA_ENV:
            monkeypatch.delenv(k, raising=False)
    env_file = tmp_path / "stack.env"
    monkeypatch.setenv("CLAUDE_STACK_ENV", str(env_file))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(http, "BACKOFF_SCALE", 0.0)
    http.set_transport(None)
    opper.clear_catalog_cache()
    openrouter.clear_catalog_cache()
    config.reset_boot_env()
    yield project
    http.set_transport(None)
    opper.clear_catalog_cache()
    openrouter.clear_catalog_cache()
    config.reset_boot_env()


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    return tmp_path / "stack.env"


class StackEnv:
    """Writes ~/.claude/stack.env stand-in lines; values accumulate across calls."""

    def __init__(self, path: Path):
        self.path = path
        self.values: dict[str, str] = {}

    def set(self, **values: str) -> None:
        self.values.update(values)
        self.path.write_text("".join(f"{k}={v}\n" for k, v in self.values.items()), encoding="utf-8")

    def configure(self, op: str, url: str, model: str, *, key: str | None = None, api: str | None = None,
                  params: dict | None = None) -> str:
        key = FAKE_KEYS[op] if key is None else key
        vals = {f"IMAGE_{op}_URL": url, f"IMAGE_{op}_MODEL": model, f"IMAGE_{op}_KEY": key}
        if api:
            vals[f"IMAGE_{op}_API"] = api
        if params is not None:
            vals[f"IMAGE_{op}_PARAMS"] = "'" + json.dumps(params) + "'"
        self.set(**vals)
        return key

    def configure_cutout(self, url: str, model: str, **kw) -> str:
        """TRANSPARENT and BG_REMOVAL on the same endpoint (one RGBA-capable model)."""
        self.configure("TRANSPARENT", url, model, **kw)
        return self.configure("BG_REMOVAL", url, model, **kw)


@pytest.fixture
def stack_env(env_file: Path) -> StackEnv:
    return StackEnv(env_file)


@pytest.fixture
def mock_http() -> Callable[[Callable[[httpx.Request], httpx.Response]], list[httpx.Request]]:
    """Install a MockTransport; returns the list that records every request."""

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            request.read()
            seen.append(request)
            return handler(request)

        http.set_transport(httpx.MockTransport(wrapped))
        return seen

    return install


def png_bytes(w: int = 8, h: int = 8, color=(255, 0, 0), mode: str = "RGB") -> bytes:
    im = Image.new(mode, (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def pattern_png(w: int = 32, h: int = 24) -> bytes:
    """A deterministic, non-uniform RGB image (so pixel preservation is meaningful)."""
    im = Image.new("RGB", (w, h))
    for x in range(w):
        for y in range(h):
            im.putpixel((x, y), ((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def rgba_cutout(w: int = 8, h: int = 8, color=(200, 10, 10)) -> bytes:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for x in range(w // 4, 3 * w // 4):
        for y in range(h // 4, 3 * h // 4):
            im.putpixel((x, y), (*color, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def open_png(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def json_response(obj, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(obj).encode(), headers={"content-type": "application/json"})


def parse_multipart(request: httpx.Request) -> list[tuple[str, str | None, str | None, bytes]]:
    """(name, filename, content_type, data) for each part of a multipart/form-data request."""
    ctype = request.headers["content-type"]
    boundary = ctype.split("boundary=", 1)[1].strip('"').encode()
    parts = []
    for chunk in request.content.split(b"--" + boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        head, _, body = chunk.partition(b"\r\n\r\n")
        headers = head.decode("utf-8", "replace")
        name = filename = ptype = None
        for line in headers.split("\r\n"):
            low = line.lower()
            if low.startswith("content-disposition"):
                for item in line.split(";"):
                    item = item.strip()
                    if item.startswith("name="):
                        name = item[5:].strip('"')
                    elif item.startswith("filename="):
                        filename = item[9:].strip('"')
            elif low.startswith("content-type"):
                ptype = line.split(":", 1)[1].strip()
        parts.append((name or "", filename, ptype, body))
    return parts


def payload_of(result) -> dict:
    return json.loads(result.content[0].text)
