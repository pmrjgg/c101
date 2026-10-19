"""Generic OpenAI-compatible Images API adapter (any other ``IMAGE_<OP>_URL`` host).

* ``POST {URL}/images/generations`` JSON ``{model, prompt, n, size, quality, background,
  output_format}`` - text-to-image and transparent generation;
* ``POST {URL}/images/edits`` multipart: ``image[]`` (repeated), ``mask``, ``prompt``, ``model``,
  ``background``, ``output_format``, ``size``, ``n`` - references, edits, cut-outs, upscales,
  rendered masks;
* response ``data[].b64_json`` or ``data[].url``.

Mask convention: an RGBA PNG the size of the first image where transparent = edit
(``alpha-transparent``); the first image is sent as PNG so the formats match.
VECTOR and TRACE default to the chat strategy (``{URL}/chat/completions``): the Images API
has no SVG output.
"""

from __future__ import annotations

import json
from typing import Any

from ..imaging import convert_canonical, ensure_png, to_png_bytes
from . import geometry
from .base import (
    MASK_PROMPT,
    REMOVE_BG_PROMPT,
    UPSCALE_PROMPT,
    Adapter,
    AdapterError,
    AdapterResult,
    ImageJob,
    Unsupported,
    summarize_body,
)

QUALITIES = ("low", "medium", "high", "xhigh", "max", "auto", "standard", "hd")
MAX_IMAGES = 16
ALL_OPS = frozenset({"GEN", "REF", "EDIT", "TRANSPARENT", "SEGMENT", "BG_REMOVAL", "UPSCALE", "VECTOR", "TRACE", "VECTOR_MANIPULATION"})


def _round16(x: float) -> int:
    return max(16, int(round(x / 16.0)) * 16)


# GPT Image 2+ (and the default for unknown models): any WxH that is a multiple of 16, at most
# 3840 px on an edge, at most 3:1, between 655,360 and 8,294,400 pixels (OpenAI's documented
# limits, mirrored by Opper's catalog size_constraints for openai/gpt-image-2*).
GPT_IMAGE_LIMITS = geometry.SizeConstraints(
    multiple_of=16, max_edge=3840, max_ratio=3, min_pixels=655_360, max_pixels=8_294_400
)
# Models that accept only fixed sizes.
FIXED_SIZES = {
    "gpt-image-1": ("1024x1024", "1536x1024", "1024x1536"),  # gpt-image-1, -1-mini, -1.5
    "dall-e-3": ("1024x1024", "1792x1024", "1024x1792"),
    "dall-e-2": ("256x256", "512x512", "1024x1024"),
}


def fixed_sizes_for(model: str | None) -> tuple[str, ...] | None:
    m = (model or "").lower()
    for prefix, sizes in FIXED_SIZES.items():
        if prefix in m:
            return sizes
    return None


def openai_size(size: str | None, aspect_ratio: str | None, model: str | None = None) -> tuple[str | None, str | None]:
    """Canonical size/aspect -> an OpenAI size string the model accepts, plus an optional note.

    gpt-image-1.x / dall-e take only their fixed sizes (the nearest by ratio is used; 'auto'
    is kept for gpt-image-1.x). Other models get a computed WxH that meets the GPT Image 2
    limits (multiple of 16, 655,360-8,294,400 pixels, edge <= 3840, ratio <= 3); explicit
    sizes for them are passed through as given.
    """
    fixed = fixed_sizes_for(model)
    s = size.strip().lower().replace(" ", "") if size else None
    if s == "auto":
        if fixed and "dall-e" in (model or "").lower():
            return None, f"size 'auto' is not offered by {model}; its default size is used"
        return "auto", None
    explicit = geometry.parse_size(s) if s else None
    if s and not explicit and geometry.tier_long_edge(s) is None:
        return None, f"size {size!r} not understood; use WxH, 1K/2K/4K or auto"
    if explicit and not fixed:
        return f"{explicit[0]}x{explicit[1]}", None
    if aspect_ratio and aspect_ratio != "auto" and not explicit:
        r = geometry.parse_ratio(aspect_ratio)
        if r is None:
            return None, f"aspect_ratio {aspect_ratio!r} not understood"
    elif explicit:
        r = explicit[0] / explicit[1]
    else:
        r = None
    if r is None and not s:
        return None, None  # provider default
    r = r or 1.0
    if not (1 / 3 <= r <= 3):
        return None, f"aspect_ratio {aspect_ratio or size} outside the 1:3..3:1 range OpenAI accepts"
    if fixed:
        choice = geometry.nearest_preset(list(fixed), r)
        wanted = f"{explicit[0]}x{explicit[1]}" if explicit else None
        if wanted == choice:
            return choice, None
        return choice, f"{model} accepts only {', '.join(fixed)}: using {choice}"
    tier_edge = geometry.tier_long_edge(s) if s else None
    long_edge = min(tier_edge, 3840) if tier_edge else (1536 if abs(r - 1) > 0.01 else 1024)
    terms = geometry.ratio_terms(aspect_ratio) if aspect_ratio and aspect_ratio != "auto" else (1, 1)
    w, h = GPT_IMAGE_LIMITS.snap(*geometry.size_for_ratio(r, long_edge), terms)
    return f"{w}x{h}", None


def form_value(v: Any) -> str:
    """Multipart fields are strings: booleans lower-case, structures as JSON."""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, dict | list):
        return json.dumps(v)
    return str(v)


class OpenAIAdapter(Adapter):
    name = "openai"
    supports = ALL_OPS
    default_strategy = {"SEGMENT": "render", "VECTOR": "chat", "TRACE": "chat"}

    def common(self, job: ImageJob) -> tuple[dict[str, Any], list[str]]:
        body: dict[str, Any] = {"model": self.cfg.model, "prompt": job.prompt or ""}
        notes: list[str] = []
        if job.n and job.n > 1:
            body["n"] = job.n
        size, note = openai_size(job.size, job.aspect_ratio, self.cfg.model)
        if size:
            body["size"] = size
        if note:
            notes.append(note)
        if job.quality:
            if job.quality.lower() in QUALITIES:
                body["quality"] = job.quality.lower()
            else:
                notes.append(f"quality {job.quality!r} ignored (expected one of {', '.join(QUALITIES)})")
        fmt = (job.output_format or "").lower() or None
        if job.task in ("transparent", "remove_background"):
            body["background"] = "transparent"
            fmt = fmt if fmt in ("png", "webp") else "png"
        if fmt:
            body["output_format"] = fmt if fmt in ("png", "jpeg", "webp") else "png"
        if job.seed is not None:
            notes.append("seed is not part of the OpenAI Images API; ignored")
        return body, notes

    async def run(self, job: ImageJob) -> AdapterResult:
        self.ensure_supported(job)
        if job.task == "svg_transform":
            return await self.chat_svg(job)
        if job.task == "mask" and self.strategy("SEGMENT") == "detect":
            return await self.detect_mask(job)
        if job.task in ("vector", "trace"):
            if self.strategy(job.op) == "chat":
                return await self.chat_svg(job)
            raise Unsupported(
                f"the OpenAI Images API has no SVG output; set IMAGE_{job.op}_PARAMS={{\"strategy\": \"chat\"}} "
                f"(the default for this adapter) with an LLM model, or point IMAGE_{job.op}_URL at OpenRouter/Opper"
            )

        body, notes = self.common(job)
        images = []
        prompt = body["prompt"]
        match job.task:
            case "generate" | "transparent":
                pass
            case "references":
                images = list(job.references)
            case "edit":
                assert job.image is not None
                images = [job.image, *job.references]
            case "remove_background":
                assert job.image is not None
                images = [job.image]
                prompt = f"{REMOVE_BG_PROMPT} {prompt}".strip()
            case "upscale":
                assert job.image is not None
                images = [job.image]
                prompt = f"{UPSCALE_PROMPT} {prompt}".strip()
            case "mask":
                assert job.image is not None
                images = [job.image]
                prompt = MASK_PROMPT.format(subject=job.prompt)
            case _:
                raise Unsupported(f"openai adapter has no images mapping for task {job.task}")
        body["prompt"] = prompt
        if len(images) > MAX_IMAGES:
            raise AdapterError(f"{self.where()}: at most {MAX_IMAGES} input images are accepted ({len(images)} given)")

        if not images:
            body = self.merged(body, job)
            # https://platform.openai.com/docs/api-reference/images/create
            resp = await self.call("POST", f"{self.cfg.base_url}/images/generations", json=body)
            endpoint = "POST /images/generations"
        else:
            files: list[tuple[str, tuple[str, bytes, str]]] = []
            for i, f in enumerate(images):
                data, mime, name = f.data, f.mime, f.name or f"image{i}"
                if i == 0 and job.mask is not None:
                    # the mask must match the first image's format and size -> send both as PNG
                    data, mime = ensure_png(data), "image/png"
                    name = f"{name.rsplit('.', 1)[0]}.png"
                files.append(("image[]", (name, data, mime)))
            if job.mask is not None:
                files.append(("mask", ("mask.png", to_png_bytes(convert_canonical(job.mask, "alpha-transparent")), "image/png")))
                notes.append("mask sent as alpha-transparent PNG (transparent = edit)")
            body = self.merged(body, job)
            form = {k: form_value(v) for k, v in body.items() if v is not None}
            # https://platform.openai.com/docs/api-reference/images/createEdit
            resp = await self.call("POST", f"{self.cfg.base_url}/images/edits", data=form, files=files)
            endpoint = "POST /images/edits"

        outputs = await self.parse_image_data(self.json_body(resp))
        for o in outputs:
            if not o.mime:
                o.mime = f"image/{body.get('output_format') or 'png'}"
        req = summarize_body(body)
        if images:
            req["images"] = len(images)
            req["mask"] = job.mask is not None
        return AdapterResult(outputs, endpoint, notes, req)
