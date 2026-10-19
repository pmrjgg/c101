"""fal.ai through its queue API (``IMAGE_<OP>_API=fal``, or detected from a fal.run / fal.ai URL).

Configuration per operation: URL ``https://queue.fal.run``, KEY = the fal key, MODEL = the fal
endpoint id (``fal-ai/bria/background/remove``, ``fal-ai/sam-3/image``, ...). One endpoint per
operation, no fallbacks.

Flow (https://fal.ai/docs/model-apis/model-endpoints/queue):
  POST {URL}/{endpoint}        Authorization: Key <KEY>, JSON input
    -> {request_id, status_url, response_url, cancel_url}
  GET  status_url   until status == COMPLETED (IN_QUEUE / IN_PROGRESS before);
                    a failed run is COMPLETED with "error" / "error_type"
  GET  response_url -> model-specific JSON; every {"url": ...} in it is an output.

Parameter names come from the endpoint's live OpenAPI schema (falschema.py, cached under
.stack/cache/fal-schemas): prompt, image_url(s), mask_url, image_size, num_images, background,
upscale_factor... Canonical inputs the endpoint has no field for are reported in ``notes``;
inputs the job cannot do without (source image, mask, prompt) make the call fail instead.
Masks are sent white = edit unless ``IMAGE_<OP>_PARAMS={"mask_convention": "black-edit"}``.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Mapping
from typing import Any, ClassVar

from .. import http, imaging
from ..falschema import Canonical, fetch_fal_input_schema, map_params
from ..io import sniff_mime
from .base import Adapter, AdapterError, AdapterResult, ImageJob, Unsupported, input_ref, png_data_uri, summarize_body

POLL_START = 1.0
POLL_FACTOR = 1.5
POLL_MAX = 8.0
SCHEMA_URL = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="
_URL_RE = re.compile(r"^(https?://|data:)", re.I)


def fal_timeout() -> float:
    try:
        return max(10.0, float(os.environ.get("IMAGE_ROUTER_FAL_TIMEOUT", "900")))
    except ValueError:
        return 900.0


def collect_urls(obj: Any, *, key_hint: str = "url") -> list[str]:
    """Every ``{"url": ...}`` value in a JSON result, depth-first, de-duplicated."""
    found: list[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, Mapping):
            v = o.get(key_hint)
            if isinstance(v, str) and _URL_RE.match(v):
                found.append(v)
            for k, child in o.items():
                if k != key_hint:
                    walk(child)
        elif isinstance(o, list | tuple):
            for child in o:
                walk(child)

    walk(obj)
    seen: set[str] = set()
    return [u for u in found if not (u in seen or seen.add(u))]


class FalAdapter(Adapter):
    name: ClassVar[str] = "fal"
    # svg_transform needs a chat model; fal endpoints are image models.
    supports: ClassVar[frozenset[str]] = frozenset(
        {"GEN", "REF", "EDIT", "TRANSPARENT", "SEGMENT", "BG_REMOVAL", "UPSCALE", "VECTOR", "TRACE"}
    )

    def auth_headers(self) -> dict[str, str]:
        key = self.cfg.key()
        return {"Authorization": f"Key {key}"} if key else {}

    @property
    def endpoint(self) -> str:
        return (self.cfg.model or "").strip("/")

    def _mask_uri(self, job: ImageJob) -> str | None:
        if job.mask is None:
            return None
        conv = str(self.cfg.directives.get("mask_convention") or "white-edit")
        return png_data_uri(imaging.to_png_bytes(imaging.convert_canonical(job.mask, conv)))

    def _scale(self, job: ImageJob) -> float | None:
        if job.task != "upscale" or not job.target_size or not job.image:
            return None
        w, _ = imaging.display_size(job.image.data)
        return round(job.target_size[0] / max(1, w), 3)

    def canonical(self, job: ImageJob) -> Canonical:
        return Canonical(
            prompt=job.prompt or None,
            image=input_ref(job.image) if job.image else None,
            references=[input_ref(r) for r in job.references],
            mask=self._mask_uri(job),
            aspect_ratio=job.aspect_ratio,
            size=job.size,
            n=job.n if job.task in ("generate", "references", "edit", "transparent", "vector") else None,
            seed=job.seed,
            transparent_background=job.task == "transparent",
            output_format=job.output_format,
            quality=job.quality,
            scale=self._scale(job),
            mask_only=job.task == "mask",
        )

    async def run(self, job: ImageJob) -> AdapterResult:
        self.ensure_supported(job)
        if not self.endpoint:
            raise Unsupported(f"IMAGE_{self.cfg.op}_MODEL must be a fal endpoint id (e.g. fal-ai/bria/background/remove)")
        canon = self.canonical(job)
        extra = self.merged({}, job)  # IMAGE_<OP>_PARAMS <- tool-call params (router-owned keys refused)
        schema = await fetch_fal_input_schema(self.client, self.endpoint, SCHEMA_URL)
        mapped = map_params(canon, schema, extra)
        essentials = ["image", "mask"] + (["references"] if job.task == "references" else [])
        if job.task in ("generate", "references", "edit", "transparent", "vector", "mask"):
            essentials.append("prompt")
        lost = [e for e in essentials if e in mapped.ignored]
        if lost:
            raise Unsupported(f"fal endpoint {self.endpoint} has no input for {', '.join(lost)}; pick an endpoint "
                              f"for this operation in IMAGE_{self.cfg.op}_MODEL")
        if job.task == "transparent" and "transparent_background" in mapped.ignored:
            raise Unsupported(f"fal endpoint {self.endpoint} cannot output a transparent background")
        result = await self.submit_and_wait(mapped.payload)
        urls = collect_urls(result)
        if not urls:
            raise AdapterError(f"{self.where()} returned no output URLs: {str(result)[:300]}")
        outputs = []
        for u in urls[: max(1, job.n) if job.task != "mask" else len(urls)]:
            blob = await self.fetch(u)
            blob.mime = sniff_mime(blob.data) or blob.mime
            outputs.append(blob)
        notes = list(mapped.notes)
        if mapped.ignored:
            notes.append(f"{self.endpoint} has no input for: {', '.join(sorted(mapped.ignored))} (not sent)")
        return AdapterResult(outputs, f"POST /{self.endpoint}", notes=notes, request=summarize_body(mapped.payload))

    async def submit_and_wait(self, payload: dict[str, Any]) -> Any:
        """Queue submit, poll status with backoff, fetch the result JSON."""
        sub = self.json_body(await self.call("POST", f"{self.cfg.base_url}/{self.endpoint}", json=payload))
        request_id, status_url, response_url = sub.get("request_id"), sub.get("status_url"), sub.get("response_url")
        if not request_id or not status_url or not response_url:
            raise AdapterError(f"{self.where()}: queue submit response lacks request_id/status_url: {str(sub)[:300]}")
        timeout = fal_timeout()
        deadline = time.monotonic() + timeout
        delay = POLL_START
        while True:
            st = self.json_body(await self.call("GET", status_url))
            status = str(st.get("status", "")).upper()
            if status == "COMPLETED":
                if st.get("error"):
                    raise AdapterError(f"{self.where()} failed ({st.get('error_type', 'error')}): {str(st['error'])[:300]}")
                break
            if status not in ("IN_QUEUE", "IN_PROGRESS"):
                raise AdapterError(f"{self.where()}: request {request_id} ended with status {status or '?'}")
            if time.monotonic() > deadline:
                await self._cancel(sub.get("cancel_url"))
                raise AdapterError(f"{self.where()}: request {request_id} timed out after {timeout:.0f}s "
                                   "(IMAGE_ROUTER_FAL_TIMEOUT)")
            await http.sleep(delay)
            delay = min(POLL_MAX, delay * POLL_FACTOR)
        result = self.json_body(await self.call("GET", response_url))
        if isinstance(result, Mapping) and result.get("detail") and not collect_urls(result):
            raise AdapterError(f"{self.where()}: result error: {str(result['detail'])[:300]}")
        return result

    async def _cancel(self, cancel_url: str | None) -> None:
        if not cancel_url:
            return
        try:
            await http.request(self.client, "PUT", cancel_url, headers=self.headers(), retries=0, raise_for_status=False)
        except Exception:  # best effort
            pass
