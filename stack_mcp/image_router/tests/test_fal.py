"""fal adapter: queue submit -> status polling -> result -> CDN download, schema-driven inputs."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx

from stack_mcp.image_router import tools

from .conftest import FAKE_KEYS, json_response, open_png, pattern_png, payload_of, rgba_cutout

QUEUE = "https://queue.fal.run"
CDN = "https://v3.fal.media/files/test/out.png"


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def openapi_for(endpoint: str, properties: dict) -> dict:
    return {
        "paths": {f"/{endpoint}": {"post": {"requestBody": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Input"}}}}}}},
        "components": {"schemas": {"Input": {"type": "object", "properties": properties}}},
    }


class FakeFal:
    """Queue API: the first status poll says IN_PROGRESS, the second COMPLETED."""

    def __init__(self, endpoint: str, properties: dict, result: dict, output: bytes):
        self.endpoint, self.properties, self.result, self.output = endpoint, properties, result, output
        self.requests: list[httpx.Request] = []
        self.polls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith("https://fal.ai/api/openapi/"):
            return json_response(openapi_for(self.endpoint, self.properties))
        base = f"{QUEUE}/{self.endpoint}"
        if request.method == "POST" and url == base:
            return json_response({"request_id": "req-1", "status_url": f"{base}/requests/req-1/status",
                                  "response_url": f"{base}/requests/req-1", "cancel_url": f"{base}/requests/req-1/cancel"})
        if url.endswith("/requests/req-1/status"):
            self.polls += 1
            return json_response({"status": "IN_PROGRESS" if self.polls == 1 else "COMPLETED"})
        if url.endswith("/requests/req-1"):
            return json_response(self.result)
        if url == CDN:
            return httpx.Response(200, content=self.output, headers={"content-type": "image/png"})
        return httpx.Response(404, json={"detail": f"unexpected {request.method} {url}"})


def test_fal_background_removal_queue_flow(stack_env, mock_http, isolated):
    endpoint = "fal-ai/bria/background/remove"
    key = stack_env.configure("BG_REMOVAL", QUEUE, endpoint)
    fake = FakeFal(endpoint, {"image_url": {"type": "string"}, "sync_mode": {"type": "boolean"}},
                   {"image": {"url": CDN, "content_type": "image/png"}}, rgba_cutout(16, 16, color=(10, 200, 10)))
    mock_http(fake)
    src = pattern_png(16, 16)
    (isolated / "photo.png").write_bytes(src)

    is_error, payload = call(tools.image_remove_background, image="photo.png")
    assert not is_error, payload

    submit = next(r for r in fake.requests if r.method == "POST")
    assert submit.headers["authorization"] == f"Key {key}"
    body = json.loads(submit.content)
    assert body["image_url"].startswith("data:image/png;base64,")
    assert base64.b64decode(body["image_url"].split(",", 1)[1]) == src
    assert "model" not in body and "prompt" not in body  # the endpoint id is the model; no prompt field
    assert fake.polls == 2
    cdn = next(r for r in fake.requests if str(r.url) == CDN)
    assert "authorization" not in cdn.headers  # credentials only go to the queue host
    out = open_png(Path(payload["files"][0]["path"]).read_bytes())
    assert out.mode == "RGBA" and out.getpixel((0, 0))[3] == 0
    assert out.getpixel((8, 8))[:3] == open_png(src).convert("RGB").getpixel((8, 8))  # original pixels kept
    assert key not in json.dumps(payload) and FAKE_KEYS["GEN"] not in json.dumps(payload)


def test_fal_missing_essential_input_is_refused(stack_env, mock_http, isolated):
    endpoint = "fal-ai/some/text-to-image"
    stack_env.configure("BG_REMOVAL", QUEUE, endpoint)
    fake = FakeFal(endpoint, {"prompt": {"type": "string"}}, {}, b"")
    mock_http(fake)
    (isolated / "photo.png").write_bytes(pattern_png(8, 8))
    is_error, payload = call(tools.image_remove_background, image="photo.png")
    assert is_error and "has no input for image" in payload["error"]
    assert not any(r.method == "POST" for r in fake.requests)  # nothing paid for


def test_fal_failed_run_reports_the_error(stack_env, mock_http, isolated):
    endpoint = "fal-ai/flux-pro/v1.1-ultra"
    stack_env.configure("GEN", QUEUE, endpoint)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://fal.ai/api/openapi/"):
            return json_response(openapi_for(endpoint, {"prompt": {"type": "string"}, "num_images": {"type": "integer"}}))
        if request.method == "POST":
            base = f"{QUEUE}/{endpoint}"
            return json_response({"request_id": "r", "status_url": f"{base}/requests/r/status", "response_url": f"{base}/requests/r"})
        if url.endswith("/status"):
            return json_response({"status": "COMPLETED", "error": "content policy", "error_type": "validation"})
        return httpx.Response(404)

    mock_http(handler)
    is_error, payload = call(tools.image_generate, prompt="a fox")
    assert is_error and "content policy" in payload["error"] and "fal" in payload["error"]
