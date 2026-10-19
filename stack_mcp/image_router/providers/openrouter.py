"""OpenRouter Image API adapter (``IMAGE_<OP>_URL=https://openrouter.ai/api/v1``).

Research notes (2026-10-19, scratchpad/opper_openrouter.json):

* one endpoint ``POST {URL}/images`` - there is NO /images/edits (404);
* headers ``Authorization: Bearer KEY``, ``Content-Type: application/json``, optional
  ``HTTP-Referer`` and ``X-OpenRouter-Title`` (``X-Title`` still accepted);
* body ``model, prompt, n (<=10), aspect_ratio, resolution | size, quality, background
  (auto|transparent|opaque; transparent needs png/webp), output_format (png|jpeg|webp|svg),
  seed, input_references: [{"type": "image_url", "image_url": {"url": <https|data URL>}}]``
  (objects, never bare strings) and provider options under ``provider.options.<slug>``;
* response ``{data: [{b64_json, media_type}], usage}``; for SVG the base64 decodes to UTF-8 markup;
* edits are generations with the source as the first input reference. There is no mask
  parameter, no background removal, segmentation, tracing or upscale model: those ops are
  approximated by regeneration (the router post-processes for fidelity and says so in notes);
* segmentation alternative: ``POST {URL}/chat/completions`` with a vision model returning
  boxes (e.g. moondream ``/detect``) - ``IMAGE_MASK_PARAMS={"strategy": "detect"}``;
* ``GET {URL}/images/models`` (public) lists each model's ``supported_parameters`` (typed
  descriptors: ``n {min,max}``, ``aspect_ratio {values}``, ``background {values}``, ...; a
  missing key means no endpoint of the model supports it). The adapter caches it for an hour
  and uses it to split ``n`` for single-image models (most declare ``n`` 1..1; the API rejects
  ``n > 1`` there), to snap ``aspect_ratio`` to the model's values, to keep the source framing
  for edit-type tasks, and to refuse ``background=transparent`` before paying when the model
  cannot produce it.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import anyio

from .. import http
from ..config import current_env
from ..imaging import image_size, mask_png_rgb
from ..io import OutputBlob
from . import geometry
from .base import (
    EDIT_MASK_INSTRUCTION,
    MASK_PROMPT,
    REMOVE_BG_PROMPT,
    TRACE_PROMPT,
    UPSCALE_PROMPT,
    Adapter,
    AdapterError,
    AdapterResult,
    ImageJob,
    Unsupported,
    input_ref,
    png_data_uri,
    summarize_body,
)

QUALITIES = ("auto", "low", "medium", "high", "xhigh", "max")
TIERS = {"512": "512", "768": "768", "1k": "1K", "1.5k": "1.5K", "2k": "2K", "4k": "4K"}
DEFAULT_REFERER = "http://localhost/claude-stack"  # override with OPENROUTER_APP_URL
DEFAULT_TITLE = "claude-stack image"
ALL_OPS = frozenset({"GEN", "REF", "EDIT", "TRANSPARENT", "SEGMENT", "BG_REMOVAL", "UPSCALE", "VECTOR", "TRACE", "VECTOR_MANIPULATION"})
# Tasks whose output must keep the source framing (see build_body).
GEOMETRY_TASKS = frozenset({"edit", "remove_background", "upscale", "mask", "trace"})
CATALOG_TTL = 3600.0
_catalog_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def clear_catalog_cache() -> None:
    _catalog_cache.clear()


def supported_parameters(entry: Mapping[str, Any] | None) -> dict[str, Any]:
    sp = (entry or {}).get("supported_parameters")
    return dict(sp) if isinstance(sp, Mapping) else {}


def enum_values(sp: Mapping[str, Any], name: str) -> list[str] | None:
    spec = sp.get(name)
    if isinstance(spec, Mapping) and isinstance(spec.get("values"), list):
        return [str(v) for v in spec["values"]]
    return None


def max_n(sp: Mapping[str, Any]) -> int:
    """Largest n the model accepts in one request (1 when the model declares no n)."""
    spec = sp.get("n")
    if isinstance(spec, Mapping):
        try:
            return max(1, int(spec.get("max") or 1))
        except (TypeError, ValueError):
            return 1
    return 1


def reference_objects(urls: list[str]) -> list[dict[str, Any]]:
    return [{"type": "image_url", "image_url": {"url": u}} for u in urls]


def resolution_tier(long_edge: int) -> str:
    if long_edge <= 1024:
        return "1K"
    if long_edge <= 2048:
        return "2K"
    return "4K"


class OpenRouterAdapter(Adapter):
    name = "openrouter"
    supports = ALL_OPS
    default_strategy = {"SEGMENT": "render", "VECTOR": "image", "TRACE": "image"}

    # --- URLs / headers ------------------------------------------------------------------
    def root(self) -> str:
        base = self.cfg.base_url
        if not urlparse(base).path.strip("/"):
            base += "/api/v1"  # IMAGE_<OP>_URL=https://openrouter.ai
        return base

    def images_url(self) -> str:
        return f"{self.root()}/images"

    def chat_url(self) -> str:
        return f"{self.root()}/chat/completions"

    def headers(self) -> dict[str, str]:
        env = current_env()
        title = env.get("OPENROUTER_APP_TITLE") or DEFAULT_TITLE
        return {
            **self.auth_headers(),
            "HTTP-Referer": env.get("OPENROUTER_APP_URL") or DEFAULT_REFERER,
            "X-OpenRouter-Title": title,
            "X-Title": title,
        }

    # --- catalog ---------------------------------------------------------------------------
    async def catalog_entry(self) -> dict[str, Any] | None:
        """This model's record from the public GET {URL}/images/models (cached; None if unavailable)."""
        root = self.root()
        cached = _catalog_cache.get(root)
        if cached is None or time.monotonic() - cached[0] > CATALOG_TTL:
            try:
                resp = await http.request(self.client, "GET", f"{root}/images/models", retries=1)
                payload = resp.json()
                models = [m for m in (payload.get("data") if isinstance(payload, Mapping) else payload) or []
                          if isinstance(m, Mapping)]
            except Exception:
                models = []
            if not models:
                return None  # do not cache failures
            _catalog_cache[root] = (time.monotonic(), models)
            cached = _catalog_cache[root]
        tag = self.cfg.model or ""
        return next((dict(m) for m in cached[1] if m.get("id") == tag or m.get("canonical_slug") == tag), None)

    # --- request body ----------------------------------------------------------------------
    async def build_body(self, job: ImageJob) -> tuple[dict[str, Any], list[str], int]:
        """(body, notes, copies): ``copies`` > 1 means send the body that many times (n split)."""
        notes: list[str] = []
        prompt = job.prompt or ""
        refs: list[str] = []
        body: dict[str, Any] = {"model": self.cfg.model}
        fmt = (job.output_format or "").lower() or None
        geometry_task = job.task in GEOMETRY_TASKS and not (job.size or job.aspect_ratio)
        needs_catalog = bool(
            (job.n and job.n > 1) or job.aspect_ratio or geometry_task or job.task in ("transparent", "remove_background")
        )
        entry = await self.catalog_entry() if needs_catalog else None
        sp = supported_parameters(entry)
        if needs_catalog and entry is None:
            notes.append("OpenRouter model catalog unavailable or model not listed: parameters sent unvalidated")
        if entry is not None and job.task in ("transparent", "remove_background"):
            backgrounds = enum_values(sp, "background")
            if "background" not in sp or (backgrounds is not None and "transparent" not in backgrounds):
                what = f"background options are {backgrounds}" if backgrounds else "declares no background option"
                raise Unsupported(
                    f"{self.where()}: the model {what}, so it cannot return a transparent background; set "
                    f"IMAGE_{job.op}_MODEL to a model with transparent output (e.g. openai/gpt-image-2.5-flare)"
                )
            formats = enum_values(sp, "output_format")
            if formats is not None and not {"png", "webp"} & set(formats):
                raise Unsupported(f"{self.where()}: transparency needs png or webp output, but the model only offers {formats}")

        match job.task:
            case "generate":
                pass
            case "references":
                refs = [input_ref(f) for f in job.references]
            case "edit":
                assert job.image is not None
                refs = [input_ref(job.image)]
                if job.mask is not None:
                    refs.append(png_data_uri(mask_png_rgb(job.mask)))
                    prompt = f"{prompt}\n\n{EDIT_MASK_INSTRUCTION}"
                    notes.append(
                        "OpenRouter has no mask parameter: the mask was sent as input reference 2 with an "
                        "explicit 'edit only the white region' instruction"
                    )
                refs += [input_ref(f) for f in job.references]
            case "transparent":
                body["background"] = "transparent"
                fmt = fmt if fmt in ("png", "webp") else "png"
            case "remove_background":
                assert job.image is not None
                refs = [input_ref(job.image)]
                prompt = f"{REMOVE_BG_PROMPT} {prompt}".strip()
                body["background"] = "transparent"
                fmt = fmt if fmt in ("png", "webp") else "png"
                notes.append("OpenRouter has no background-removal model: the cut-out is a regeneration with background=transparent")
            case "upscale":
                assert job.image is not None and job.target_size is not None
                refs = [input_ref(job.image)]
                prompt = f"{UPSCALE_PROMPT} {prompt}".strip()
                if not job.size:
                    tier = resolution_tier(max(job.target_size))
                    res_values = enum_values(sp, "resolution")
                    if entry is None or (res_values is None and "resolution" in sp):
                        body["resolution"] = tier
                    elif res_values:
                        edge = geometry.tier_long_edge(tier) or 1024
                        body["resolution"] = tier if tier in res_values else min(
                            res_values, key=lambda v: abs((geometry.tier_long_edge(v) or 1024) - edge))
                    else:
                        notes.append("the model has no resolution tiers: it regenerates at its default size")
                notes.append("OpenRouter has no upscaler: the image is regenerated at a higher resolution")
            case "mask":
                assert job.image is not None
                refs = [input_ref(job.image)]
                prompt = MASK_PROMPT.format(subject=job.prompt)
                notes.append("mask rendered by the image model (strategy 'render') and normalised locally")
            case "vector":
                fmt = "svg"
                if job.style:
                    prompt = f"{prompt}\nStyle: {job.style}"
            case "trace":
                assert job.image is not None
                refs = [input_ref(job.image)]
                prompt = f"{TRACE_PROMPT} {prompt}".strip()
                fmt = "svg"
                notes.append("OpenRouter has no tracing model: an SVG model redraws the reference image")
            case _:
                raise Unsupported(f"openrouter adapter has no images mapping for task {job.task}")

        body["prompt"] = prompt
        if refs:
            body["input_references"] = reference_objects(refs)
        explicit_pixels = bool(job.size and re.fullmatch(r"\s*\d+\s*[xX]\s*\d+\s*", job.size))
        if job.size:
            s = job.size.strip()
            body["size"] = TIERS.get(s.lower(), s.lower() if explicit_pixels else s)
        ratios = enum_values(sp, "aspect_ratio")
        if job.aspect_ratio:
            if explicit_pixels:
                notes.append("explicit WxH size wins; aspect_ratio dropped (OpenRouter rejects mismatches)")
            elif entry is not None and not ratios:
                notes.append(f"aspect_ratio {job.aspect_ratio} dropped: the model declares no aspect ratios")
            elif ratios and job.aspect_ratio not in ratios:
                r = geometry.parse_ratio(job.aspect_ratio)
                choice = geometry.nearest_ratio(ratios, r) if r else None
                if choice:
                    body["aspect_ratio"] = choice
                    notes.append(f"aspect_ratio {job.aspect_ratio} is not offered by the model; using the nearest {choice}")
                else:
                    notes.append(f"aspect_ratio {job.aspect_ratio!r} is not offered by the model {ratios}; dropped")
            else:
                body["aspect_ratio"] = job.aspect_ratio
        elif geometry_task and job.image is not None:
            # keep the source framing: without it the model's default (often square) frame comes
            # back and the local fidelity steps would have to crop it
            if ratios:
                try:
                    sw, sh = image_size(job.image.data)
                except Exception:
                    sw = sh = 0
                if sw and sh:
                    choice = geometry.nearest_ratio(ratios, sw / sh)
                    if choice and geometry.ratio_distance(geometry.parse_ratio(choice) or 1.0, sw / sh) > 0.02 and "auto" in ratios:
                        choice = "auto"
                    if choice:
                        body["aspect_ratio"] = choice
                        notes.append(f"aspect_ratio {choice} keeps the {sw}x{sh} source framing")
            elif entry is None:
                notes.append("pass aspect_ratio to keep the source framing (the model catalog could not be checked)")
        if job.quality:
            q = job.quality.lower()
            if q in QUALITIES:
                body["quality"] = q
            else:
                notes.append(f"quality {job.quality!r} ignored (expected one of {', '.join(QUALITIES)})")
        if fmt:
            body["output_format"] = fmt
        copies = 1
        if job.n and job.n > 1:
            limit = max_n(sp) if entry is not None else 1
            if limit >= job.n:
                body["n"] = job.n
            else:
                copies = job.n
                why = (f"the model generates at most {limit} image(s) per request" if entry is not None
                       else "the model catalog could not be checked for n support")
                notes.append(f"n={job.n} sent as {job.n} single-image requests ({why})")
        if job.seed is not None:
            body["seed"] = job.seed
        return self.merged(body, job), notes, copies

    # --- run -------------------------------------------------------------------------------
    async def run(self, job: ImageJob) -> AdapterResult:
        self.ensure_supported(job)
        if job.task == "svg_transform":
            return await self.chat_svg(job)
        if job.task == "mask" and self.strategy("SEGMENT") == "detect":
            return await self.detect_mask(job)
        if job.task in ("vector", "trace") and self.strategy(job.op) == "chat":
            return await self.chat_svg(job)
        strategy = self.strategy(job.op) if job.op in self.default_strategy else "image"
        if strategy not in ("image", "render"):
            raise Unsupported(f"IMAGE_{job.op}_PARAMS strategy {strategy!r} is not known to the openrouter adapter")

        body, notes, copies = await self.build_body(job)
        warnings: list[str] = []
        # https://openrouter.ai/docs/guides/overview/multimodal/image-generation.md
        if copies == 1:
            outputs = await self.generate(body)
        else:
            bodies = [dict(body) for _ in range(copies)]
            if isinstance(body.get("seed"), int):
                # the same seed would make every split request return the same image
                for i, b in enumerate(bodies):
                    b["seed"] = body["seed"] + i
                notes.append(f"split requests use seeds {body['seed']}..{body['seed'] + copies - 1}")
            outputs, failures = await self.generate_split(bodies)
            if failures:
                warnings.append(f"{len(failures)} of {copies} requests failed, {len(outputs)} image(s) returned: {failures[0]}")
        if job.task in ("vector", "trace"):
            bad = [o.mime for o in outputs if (o.mime or "") != "image/svg+xml"]
            if bad:
                raise AdapterError(
                    f"{self.where()} returned {bad[0]} instead of SVG; use an SVG model (e.g. a recraft *-vector "
                    f"model) or set IMAGE_{job.op}_PARAMS={{\"strategy\": \"chat\"}} with an LLM"
                )
        return AdapterResult(outputs, "POST /images", notes, summarize_body(body), warnings=warnings)

    async def generate(self, body: dict[str, Any]) -> list[OutputBlob]:
        resp = await self.call("POST", self.images_url(), json=body)
        return await self.parse_image_data(self.json_body(resp), mime_key="media_type")

    async def generate_split(self, bodies: list[dict[str, Any]]) -> tuple[list[OutputBlob], list[str]]:
        """Concurrent single-image requests, one per body. Images already generated (and billed)
        are kept when some requests fail; only when all fail is the first error raised."""
        results: list[list[OutputBlob] | BaseException | None] = [None] * len(bodies)

        async def one(i: int) -> None:
            try:
                results[i] = await self.generate(bodies[i])
            except AdapterError as exc:
                results[i] = exc

        async with anyio.create_task_group() as tg:
            for i in range(len(bodies)):
                tg.start_soon(one, i)
        outputs = [o for r in results if isinstance(r, list) for o in r]
        failures = [str(r) for r in results if isinstance(r, BaseException)]
        if not outputs:
            first = next(r for r in results if isinstance(r, BaseException))
            raise first
        return outputs, failures
