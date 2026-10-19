"""In-process fakes for the router APIs (used with httpx.MockTransport)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from .conftest import FIXTURES, b64, json_response

# Trimmed copies of the live public catalogs (2026-10-19): GET https://api.opper.ai/v3/images/models
# and GET https://openrouter.ai/api/v1/images/models.
OPPER_CATALOG = json.loads((FIXTURES / "opper_catalog.json").read_text())
OPENROUTER_CATALOG = json.loads((FIXTURES / "openrouter_catalog.json").read_text())

Handler = Callable[[httpx.Request], httpx.Response | None]


def data_url(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{b64(data)}"


def chain(*handlers: Handler) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        for h in handlers:
            r = h(req)
            if r is not None:
                return r
        raise AssertionError(f"unexpected request {req.method} {req.url}")

    return handler


def body_of(req: httpx.Request) -> Any:
    return json.loads(req.content)


class FakeOpenRouter:
    """POST /api/v1/images -> data[].b64_json + media_type; POST /api/v1/chat/completions -> content;
    GET /api/v1/images/models -> ``catalog`` (404 when None, i.e. the catalog is unavailable).

    ``requests`` holds the POSTs only (catalog GETs are in ``catalog_requests``).
    """

    def __init__(self, image: bytes | None = None, media_type: str = "image/png", chat: str | None = None,
                 status: int = 200, error: Any = None, n_images: int | None = None, catalog: Any = None):
        self.image, self.media_type, self.chat = image, media_type, chat
        self.status, self.error, self.n_images = status, error, n_images
        self.catalog = catalog
        self.requests: list[httpx.Request] = []
        self.catalog_requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response | None:
        if req.url.host != "openrouter.ai":
            return None
        if req.method == "GET" and req.url.path == "/api/v1/images/models":
            self.catalog_requests.append(req)
            if self.catalog is None:
                return httpx.Response(404, json={"error": {"code": 404, "message": "no catalog here"}})
            return json_response(self.catalog)
        self.requests.append(req)
        if self.status != 200:
            return json_response(self.error or {"error": {"code": self.status, "message": "nope"}}, self.status)
        if req.url.path == "/api/v1/images":
            n = self.n_images or body_of(req).get("n", 1)
            return json_response({"created": 1, "data": [{"b64_json": b64(self.image), "media_type": self.media_type}] * n,
                                  "usage": {"cost": 0.01}})
        if req.url.path == "/api/v1/chat/completions":
            return json_response({"choices": [{"message": {"role": "assistant", "content": self.chat}}]})
        return httpx.Response(404, json={"error": {"code": 404, "message": "no route"}})


class FakeOpper:
    """POST /v3/images (sync or async), GET /v3/images/models, /v3/artifacts/{id}/status, storage downloads."""

    def __init__(self, image: bytes | None = None, mime_type: str = "image/png", chat: str | None = None,
                 async_job: bool = False, status: int = 200, catalog: Any = OPPER_CATALOG):
        self.image, self.mime_type, self.chat = image, mime_type, chat
        self.async_job, self.status, self.catalog = async_job, status, catalog
        self.requests: list[httpx.Request] = []
        self.polls = 0

    def __call__(self, req: httpx.Request) -> httpx.Response | None:
        host, path = req.url.host, req.url.path
        if host == "storage.opper.example":
            self.requests.append(req)
            return httpx.Response(200, content=self.image, headers={"content-type": self.mime_type})
        if host != "api.opper.ai":
            return None
        self.requests.append(req)
        if path == "/v3/images/models" and req.method == "GET":
            return json_response(self.catalog)
        if self.status != 200:
            return json_response({"error": {"code": "bad_request", "message": "model rejected the request", "details": {}}}, self.status)
        if path == "/v3/images" and req.method == "POST":
            if self.async_job:
                return json_response({"id": "gen_123", "status_url": "/v3/artifacts/gen_123/status"}, 202)
            n = body_of(req).get("n", 1)
            return json_response({"id": "img_1", "model": body_of(req)["model"],
                                  "data": [{"b64_json": b64(self.image), "mime_type": self.mime_type}] * n,
                                  "usage": {"cost": 0.02, "images": n}})
        if path == "/v3/artifacts/gen_123/status":
            self.polls += 1
            if self.polls < 2:
                return json_response({"id": "gen_123", "status": "processing"})
            return json_response({"id": "gen_123", "status": "completed", "mime_type": self.mime_type,
                                  "url": "https://storage.opper.example/gen_123.png?X-Amz-Signature=abc"})
        if path == "/v3/compat/chat/completions":
            return json_response({"choices": [{"message": {"role": "assistant", "content": self.chat}}]})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "no route"}})


class FakeCompat:
    """Generic OpenAI-compatible: /v1/images/generations (JSON), /v1/images/edits (multipart), chat."""

    def __init__(self, image: bytes | None = None, chat: str | None = None, url_output: bool = False):
        self.image, self.chat, self.url_output = image, chat, url_output
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response | None:
        host, path = req.url.host, req.url.path
        if host == "cdn.example.test":
            self.requests.append(req)
            return httpx.Response(200, content=self.image, headers={"content-type": "image/png"})
        if host != "llm.example.test":
            return None
        self.requests.append(req)
        if path in ("/v1/images/generations", "/v1/images/edits"):
            if self.url_output:
                return json_response({"data": [{"url": "https://cdn.example.test/out.png"}]})
            return json_response({"data": [{"b64_json": b64(self.image)}]})
        if path == "/v1/chat/completions":
            return json_response({"choices": [{"message": {"role": "assistant", "content": self.chat}}]})
        return httpx.Response(404, json={"error": {"message": "no route"}})
