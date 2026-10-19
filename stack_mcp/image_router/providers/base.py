"""Adapter interface shared by the openrouter, opper, openai and local adapters.

An *ImageJob* is an adapter-neutral request: inputs already resolved to bytes,
the mask already validated as a canonical L image (white = edit). Each adapter
declares the operations it supports and implements ``run(job)``, raising

* ``Unsupported``  - the configured adapter cannot perform this operation/task
  (a clear configuration message; nothing else is tried), or
* ``AdapterError`` - the call failed (HTTP, timeout, unparseable result).

Messages name the adapter, the URL *host* and the model tag only - never the
key, the URL path or query.
"""

from __future__ import annotations

import base64
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx
from PIL import Image

from .. import http
from ..config import RESERVED_PARAM_KEYS, OpConfig, redact
from ..io import InputFile, OutputBlob, download, is_public_url, redact_urls, sniff_mime

SVG_NS = "http://www.w3.org/2000/svg"


class AdapterError(RuntimeError):
    """The adapter call failed."""


class Unsupported(AdapterError):
    """The configured adapter cannot do this operation (no silent fallback)."""


# Prompts used when an operation is approximated by an image model --------------------------

MASK_PROMPT = (
    "Create a segmentation mask of this image. Paint {subject} pure white (#FFFFFF) and everything else "
    "pure black (#000000). Keep exactly the same framing, size and aspect ratio as the input. Output only "
    "the flat black-and-white mask: no shading, no outlines, no text, no other colours."
)
REMOVE_BG_PROMPT = (
    "Remove the background completely and make it transparent. Keep the subject exactly as it is: same "
    "position, size, pose, colours and details; do not redraw, crop or move it."
)
UPSCALE_PROMPT = (
    "Reproduce this image exactly at a higher resolution. Preserve every detail, colour, texture, text and "
    "the composition; add no new content and do not change the framing."
)
TRACE_PROMPT = (
    "Faithful vector (SVG) version of the reference image: same shapes, colours and composition, flat "
    "fills, no additions or omissions."
)
EDIT_MASK_INSTRUCTION = (
    "Image 2 is a black-and-white mask for image 1. Edit ONLY the region that is white in the mask; keep "
    "every pixel in the black region exactly as it is in image 1. Do not reproduce the mask itself. "
    "Return image 1 with the edit applied."
)

SVG_SYSTEM_PROMPT = (
    "You write SVG. Reply with exactly one complete, standalone, well-formed SVG 1.1 document "
    "(<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=...>...</svg>) and nothing else: no prose, no markdown."
)


@dataclass(slots=True)
class ImageJob:
    op: str  # GEN | REF | EDIT | TRANSPARENT | SEGMENT | BG_REMOVAL | UPSCALE | VECTOR | TRACE | VECTOR_MANIPULATION
    task: str  # generate | references | edit | mask | transparent | remove_background | upscale | vector | trace | svg_transform
    prompt: str = ""
    image: InputFile | None = None
    mask: Image.Image | None = None  # canonical L mask (white = edit), source size
    references: list[InputFile] = field(default_factory=list)
    n: int = 1
    size: str | None = None
    aspect_ratio: str | None = None
    quality: str | None = None
    seed: int | None = None
    output_format: str | None = None
    style: str | None = None
    target_size: tuple[int, int] | None = None  # upscale
    svg_text: str | None = None  # svg_transform input
    call_params: dict[str, Any] = field(default_factory=dict)  # tool-call `params`, merged last
    options: dict[str, Any] = field(default_factory=dict)  # task options (e.g. vtracer settings, layered)

    @property
    def inputs(self) -> list[InputFile]:
        return ([self.image] if self.image else []) + list(self.references)


@dataclass(slots=True)
class AdapterResult:
    outputs: list[OutputBlob]
    endpoint: str  # e.g. "POST /images" (path only, never the host's credentials or query)
    notes: list[str] = field(default_factory=list)
    request: dict[str, Any] = field(default_factory=dict)  # body summary for the sidecar (sanitised later)
    text: str | None = None  # chat replies (svg_transform, detect)
    boxes: list[tuple[float, float, float, float]] | None = None  # SEGMENT detect strategy
    warnings: list[str] = field(default_factory=list)  # e.g. some of several split requests failed


# --- helpers ----------------------------------------------------------------------------------


def deep_merge(base: Mapping[str, Any], extra: Mapping[str, Any] | None) -> dict[str, Any]:
    """Recursive dict merge: ``extra`` wins; nested objects are merged, not replaced."""
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def input_ref(f: InputFile) -> str:
    """How an input reaches a JSON API: its public URL when unmodified, else a data URI."""
    if f.url and is_public_url(f.url):
        return f.url
    return f.data_uri


def png_data_uri(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def b64decode(data: str) -> bytes:
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    data = re.sub(r"\s+", "", data)
    return base64.b64decode(data + "=" * (-len(data) % 4))


def extract_svg(text: str) -> str:
    """The <svg>...</svg> document inside a chat reply (code fences and prose stripped)."""
    m = re.search(r"<svg[\s>].*</svg\s*>", text or "", re.S | re.I) or re.search(r"<svg\b[^>]*/>", text or "", re.I)
    if not m:
        raise AdapterError("the model reply contains no <svg>...</svg> document")
    return m.group(0)


_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>\s*")


def validate_svg(text: str) -> str:
    """Well-formed SVG or AdapterError; adds the SVG namespace when the model forgot it.

    A leading byte-order mark and any existing XML declaration (which may name another
    encoding) are dropped: the result always starts with a UTF-8 declaration, matching how
    it is written.
    """
    text = text.lstrip("\ufeff")
    text = _XML_DECL_RE.sub("", text, count=1).lstrip("\ufeff")
    if "<!ENTITY" in text:
        raise AdapterError("returned SVG declares XML entities; refusing it")
    if not re.search(r"<svg\b[^>]*\sxmlns\s*=", text):
        text = re.sub(r"<svg\b", f'<svg xmlns="{SVG_NS}"', text, count=1)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise AdapterError(f"returned SVG is not well-formed XML: {exc}") from None
    if root.tag != f"{{{SVG_NS}}}svg":
        raise AdapterError(f"returned document root is <{root.tag.rsplit('}', 1)[-1]}>, not an SVG <svg> element")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n' + text.lstrip()
    return text if text.endswith("\n") else text + "\n"


def chat_content(payload: Any) -> str:
    """choices[0].message.content as text (string or list of parts)."""
    try:
        msg = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise AdapterError(f"chat response has no choices[0].message: {str(payload)[:300]}") from None
    content = msg.get("content")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, Mapping))
    if not isinstance(content, str) or not content.strip():
        raise AdapterError("chat response message has no text content")
    return content


def first_json_object(text: str) -> Any:
    """The first JSON object in a reply (fenced or bare)."""
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    raise AdapterError(f"no JSON object in the model reply: {text[:200]!r}")


def parse_boxes(obj: Any) -> list[tuple[float, float, float, float]]:
    """{"objects":[{x_min,y_min,x_max,y_max}]} (moondream /detect) or a few close variants.

    Gemini's native ``{"box_2d": [y_min, x_min, y_max, x_max]}`` (per-mille, y first) is
    converted to 0-1 (x_min, y_min, x_max, y_max) here; every other form is returned in the
    model's own units and normalised later (:func:`..imaging.normalize_boxes`).
    """
    items: Any = obj
    if isinstance(obj, Mapping):
        for k in ("objects", "boxes", "detections", "results"):
            if isinstance(obj.get(k), list):
                items = obj[k]
                break
    boxes: list[tuple[float, float, float, float]] = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, Mapping) and isinstance(it.get("box_2d"), list | tuple) and len(it["box_2d"]) == 4:
            y0, x0, y1, x1 = (float(v) / 1000.0 for v in it["box_2d"])
            boxes.append((x0, y0, x1, y1))
            continue
        if isinstance(it, Mapping):
            b = it.get("box") or it.get("bbox") or it
            if isinstance(b, Mapping) and all(k in b for k in ("x_min", "y_min", "x_max", "y_max")):
                boxes.append((float(b["x_min"]), float(b["y_min"]), float(b["x_max"]), float(b["y_max"])))
            elif isinstance(b, list | tuple) and len(b) == 4:
                boxes.append(tuple(float(v) for v in b))  # type: ignore[arg-type]
        elif isinstance(it, list | tuple) and len(it) == 4:
            boxes.append(tuple(float(v) for v in it))  # type: ignore[arg-type]
    return boxes


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_urls(value)
    if isinstance(value, Mapping):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(v) for v in value]
    return value


def summarize_body(body: Mapping[str, Any]) -> dict[str, Any]:
    """Request body for sidecars (a copy).

    Input URLs a provider fetches itself (input_references[].image_url.url, image, mask,
    reference_images) keep only scheme://host/path: presigned signatures and tokens in their
    query, fragment or user info never reach a sidecar. Data URIs and base64 are replaced by
    io.sanitize later.
    """
    return {k: _redact_value(v) for k, v in body.items() if k not in ("messages",)}


# --- adapter base -----------------------------------------------------------------------------


class Adapter:
    """Base class: holds the op config and the shared client; subclasses implement run()."""

    name: ClassVar[str] = "base"
    supports: ClassVar[frozenset[str]] = frozenset()
    # Default strategy per op when IMAGE_<OP>_PARAMS has no "strategy".
    default_strategy: ClassVar[dict[str, str]] = {}

    def __init__(self, cfg: OpConfig, client: httpx.AsyncClient):
        self.cfg = cfg
        self.client = client

    # --- configuration ----------------------------------------------------------------
    def ensure_supported(self, job: ImageJob) -> None:
        if job.op not in self.supports:
            raise Unsupported(
                f"the {self.name} adapter cannot perform {job.op} ({job.task}); set IMAGE_{job.op}_URL / "
                f"IMAGE_{job.op}_API to an adapter that supports it (see image_ops_status). No fallback is attempted."
            )

    def strategy(self, op: str) -> str:
        return self.cfg.strategy(self.default_strategy.get(op, "image"))

    def merged(self, body: Mapping[str, Any], job: ImageJob) -> dict[str, Any]:
        """Adapter body <- IMAGE_<OP>_PARAMS <- tool-call params (deep merge, later wins).

        Neither may set the router-owned fields (model, prompt, messages, input images): the
        model is exactly IMAGE_<OP>_MODEL - a per-call switch would be a silent fallback and
        the sidecar would record the wrong model.
        """
        reserved = sorted(set(job.call_params) & RESERVED_PARAM_KEYS)
        if reserved:
            raise Unsupported(
                f"params may not set {', '.join(reserved)}: the model is IMAGE_{self.cfg.op}_MODEL "
                f"({self.cfg.model}) and the prompt and input images come from the tool's own arguments"
            )
        out = deep_merge(deep_merge(body, self.cfg.params), job.call_params)
        if "model" in body and out.get("model") != self.cfg.model:  # pragma: no cover - guarded above
            raise AdapterError(f"{self.where()}: refusing to send a model other than IMAGE_{self.cfg.op}_MODEL")
        return out

    def auth_headers(self) -> dict[str, str]:
        key = self.cfg.key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def headers(self) -> dict[str, str]:
        return self.auth_headers()

    def where(self) -> str:
        return f"{self.name} {self.cfg.op} call to {self.cfg.host or '?'} (model {self.cfg.model or '?'})"

    # --- HTTP -------------------------------------------------------------------------
    async def call(self, method: str, url: str, **kw: Any) -> httpx.Response:
        """HTTP with the shared retry policy; errors name the host and model only."""
        kw.setdefault("headers", self.headers())
        try:
            return await http.request(self.client, method, url, **kw)
        except http.HttpError as exc:
            hint = self.status_hint(exc.status)
            raise AdapterError(redact(f"{self.where()} failed: HTTP {exc.status}: {exc.detail}{hint}")) from None
        except httpx.TimeoutException as exc:
            raise AdapterError(f"{self.where()} timed out ({type(exc).__name__})") from None
        except httpx.HTTPError as exc:
            raise AdapterError(redact(f"{self.where()} failed: {type(exc).__name__}")) from None

    def status_hint(self, status: int) -> str:
        op = self.cfg.op
        if status in (401, 403):
            return f" - check IMAGE_{op}_KEY"
        if status == 402:
            return " - the account has no credits for this model"
        if status == 404:
            return f" - check IMAGE_{op}_URL / IMAGE_{op}_MODEL"
        return ""

    def json_body(self, resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            raise AdapterError(f"{self.where()}: response was not JSON ({resp.text[:200]!r})") from None

    async def fetch(self, url: str, *, auth: bool = False) -> OutputBlob:
        """Download an output URL; credentials only go to the configured host itself."""
        if url.startswith("data:"):
            raw = b64decode(url)
            return OutputBlob(raw, sniff_mime(raw))
        from urllib.parse import urlparse

        same_host = (urlparse(url).hostname or "").lower() == (self.cfg.host or "")
        headers = self.auth_headers() if (auth and same_host) else {}
        try:
            data, mime = await download(self.client, url, headers)
        except http.HttpError as exc:
            raise AdapterError(f"{self.where()}: downloading the output failed: HTTP {exc.status}") from None
        except httpx.HTTPError as exc:
            raise AdapterError(f"{self.where()}: downloading the output failed: {type(exc).__name__}") from None
        return OutputBlob(data, mime, source_url=url)

    async def parse_image_data(self, payload: Any, mime_key: str = "media_type") -> list[OutputBlob]:
        """OpenAI-style ``data[i].b64_json`` (+ media type) or ``data[i].url``."""
        outputs: list[OutputBlob] = []
        items = (payload or {}).get("data") if isinstance(payload, Mapping) else None
        for item in items or []:
            if not isinstance(item, Mapping):
                continue
            mime = item.get(mime_key) or item.get("media_type") or item.get("mime_type")
            if item.get("b64_json"):
                raw = b64decode(item["b64_json"])
                outputs.append(OutputBlob(raw, sniff_mime(raw) or mime))
            elif item.get("url"):
                blob = await self.fetch(item["url"])
                blob.mime = blob.mime or mime
                outputs.append(blob)
        if not outputs:
            err = payload.get("error") if isinstance(payload, Mapping) else None
            raise AdapterError(f"{self.where()} returned no images: {str(err or payload)[:300]}")
        return outputs

    # --- chat completions (svg_transform, chat strategies, detect) -----------------------
    def chat_url(self) -> str:
        return f"{self.cfg.base_url}/chat/completions"

    async def chat(self, job: ImageJob, messages: list[dict[str, Any]], *, extra: Mapping[str, Any] | None = None) -> AdapterResult:
        body = self.merged({"model": self.cfg.model, "messages": messages, **dict(extra or {})}, job)
        resp = await self.call("POST", self.chat_url(), json=body)
        text = chat_content(self.json_body(resp))
        req = {k: v for k, v in body.items() if k != "messages"}
        return AdapterResult([], f"POST {self.chat_path()}", request=req, text=text)

    def chat_path(self) -> str:
        return "/chat/completions"

    async def chat_svg(self, job: ImageJob) -> AdapterResult:
        """VECTOR / TRACE (chat strategy) and svg_transform: an LLM writes the SVG."""
        if job.task == "svg_transform":
            user: Any = (
                f"Instruction: {job.prompt}\n\nApply the instruction to the SVG below and return the complete "
                "modified SVG document. Preserve ids, layer groups (inkscape:groupmode / inkscape:label), "
                "<defs> and everything the instruction does not ask to change.\n\n```svg\n"
                f"{job.svg_text}\n```"
            )
        elif job.task == "trace":
            assert job.image is not None
            user = [
                {"type": "text", "text": f"{TRACE_PROMPT} {job.prompt}".strip()},
                {"type": "image_url", "image_url": {"url": input_ref(job.image)}},
            ]
        else:
            text = f"Draw this as an SVG: {job.prompt}"
            if job.style:
                text += f"\nStyle: {job.style}"
            if job.aspect_ratio:
                text += f"\nAspect ratio (viewBox): {job.aspect_ratio}"
            if job.options.get("layered"):
                text += "\nGroup the drawing into meaningful top-level <g> groups with descriptive ids (one per part)."
            user = text
        messages = [{"role": "system", "content": SVG_SYSTEM_PROMPT}, {"role": "user", "content": user}]
        res = await self.chat(job, messages)
        svg = validate_svg(extract_svg(res.text or ""))
        res.outputs = [OutputBlob(svg.encode("utf-8"), "image/svg+xml")]
        res.notes.append("SVG written by a chat model (chat strategy) and validated as well-formed XML")
        return res

    async def detect_mask(self, job: ImageJob) -> AdapterResult:
        """SEGMENT strategy 'detect': a vision chat model returns boxes, rasterised locally."""
        assert job.image is not None
        url = input_ref(job.image)
        model = (self.cfg.model or "").lower()
        if "moondream" in model:
            text = "/detect " + json.dumps({"object": job.prompt})
        else:
            try:
                from ..imaging import image_size

                w, h = image_size(job.image.data)
                dims = f"The image is {w}x{h} pixels. "
            except Exception:
                dims = ""
            text = (
                f"{dims}Find every instance of: {job.prompt}. Reply with JSON only: "
                '{"objects":[{"x_min":0.0,"y_min":0.0,"x_max":1.0,"y_max":1.0}]} with coordinates as '
                "fractions (0-1) of the image width and height, from the top-left corner (not pixels). "
                "Reply {\"objects\":[]} if there is none."
            )
        messages = [{"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]}]
        res = await self.chat(job, messages)
        boxes = parse_boxes(first_json_object(res.text or ""))
        res.request["detect_boxes"] = len(boxes)
        res.notes.append(f"detect strategy: {len(boxes)} box(es) rasterised into the mask (boxes, not pixel-exact outlines)")
        res.boxes = boxes
        return res

    # --- interface --------------------------------------------------------------------
    async def run(self, job: ImageJob) -> AdapterResult:  # pragma: no cover - abstract
        raise NotImplementedError
