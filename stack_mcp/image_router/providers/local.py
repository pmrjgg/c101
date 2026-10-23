"""Opt-in local adapters (``IMAGE_TRACE_API=local``, ``IMAGE_UPSCALE_API=local``).

Never chosen automatically: an operation only runs locally when its ``IMAGE_<OP>_API`` says so.

* TRACE: vtracer (MIT, prebuilt wheels) - raster -> SVG. ``IMAGE_TRACE_PARAMS`` / ``params`` take
  vtracer settings (colormode, hierarchical, mode, filter_speckle, color_precision,
  layer_difference, corner_threshold, length_threshold, max_iterations, splice_threshold,
  path_precision). ``layered=true`` uses ``hierarchical="cutout"`` (shapes never overlap) so
  one layer per colour preserves the appearance exactly.
* UPSCALE: Pillow Lanczos resampling to exactly ``scale`` x the source size (faithful: no new
  detail is invented).
"""

from __future__ import annotations

from typing import Any

import anyio

from ..imaging import ensure_png_rgba, lanczos_resize
from ..io import OutputBlob
from ..svg import optimize_svg
from .base import Adapter, AdapterError, AdapterResult, ImageJob, Unsupported

# Parameter order of vtracer.convert_raw_image_to_svg after (img_bytes, img_format).
VTRACER_ARGS = (
    "colormode",
    "hierarchical",
    "mode",
    "filter_speckle",
    "color_precision",
    "layer_difference",
    "corner_threshold",
    "length_threshold",
    "max_iterations",
    "splice_threshold",
    "path_precision",
)
VTRACER_OPTIONS = frozenset(VTRACER_ARGS)


def trace_png(png: bytes, options: dict[str, Any]) -> str:
    import vtracer  # local import: only needed when IMAGE_TRACE_API=local

    # Positional on purpose: vtracer 0.6.15's CPython 3.14 wheel segfaults on any keyword argument.
    # None is vtracer's own default for every parameter.
    return vtracer.convert_raw_image_to_svg(png, "png", *(options.get(k) for k in VTRACER_ARGS))


class LocalAdapter(Adapter):
    name = "local"
    supports = frozenset({"TRACE", "UPSCALE"})

    async def run(self, job: ImageJob) -> AdapterResult:
        self.ensure_supported(job)
        if job.task == "trace":
            return await self.trace(job)
        if job.task == "upscale":
            return await self.upscale(job)
        raise Unsupported(f"the local adapter cannot perform {job.task}")

    async def trace(self, job: ImageJob) -> AdapterResult:
        assert job.image is not None
        opts: dict[str, Any] = {}
        if job.options.get("colormode"):
            opts["colormode"] = job.options["colormode"]
        if job.options.get("layered"):
            opts["hierarchical"] = "cutout"
        opts.update(self.cfg.params)
        opts.update(job.call_params)
        unknown = sorted(set(opts) - VTRACER_OPTIONS)
        if unknown:
            raise AdapterError(
                f"unknown vtracer option(s) {unknown} in IMAGE_TRACE_PARAMS/params; allowed: {sorted(VTRACER_OPTIONS)}"
            )
        opts.setdefault("path_precision", 3)
        png = ensure_png_rgba(job.image.data)
        try:
            raw = await anyio.to_thread.run_sync(trace_png, png, opts)
        except Exception as exc:  # vtracer raises plain exceptions for bad options/images
            raise AdapterError(f"local vtracer trace failed: {type(exc).__name__}: {exc}") from None
        svg, _stats = optimize_svg(raw, precision=3)  # drops the generator comment, adds a viewBox
        notes = [f"traced locally with vtracer ({', '.join(f'{k}={v}' for k, v in sorted(opts.items()))})"]
        return AdapterResult([OutputBlob(svg.encode("utf-8"), "image/svg+xml")], "local vtracer", notes, {"vtracer": opts})

    async def upscale(self, job: ImageJob) -> AdapterResult:
        assert job.image is not None and job.target_size is not None
        data = await anyio.to_thread.run_sync(lanczos_resize, job.image.data, job.target_size)
        w, h = job.target_size
        return AdapterResult(
            [OutputBlob(data, "image/png")],
            "local lanczos",
            [f"upscaled locally with Pillow Lanczos to {w}x{h} (faithful resampling; no new detail is invented)"],
            {"resample": "lanczos", "size": f"{w}x{h}"},
        )
