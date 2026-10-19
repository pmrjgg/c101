"""MCP tool implementations for the ``image`` server.

Operation tools call exactly the endpoint/model configured for their operation in
``~/.claude/stack.env`` (IMAGE_<OP>_URL / _KEY / _MODEL; read at call time, no fallbacks).
Local tools need no model. Every tool returns a ``CallToolResult`` whose single text block
is a JSON payload::

    {ok, tool, op?, adapter?, url_host?, model?, files: [{path, mime, bytes, width?, height?}],
     notes, warnings, ...}

Failures return ``ok: false`` with an ``error`` (and ``missing_env`` for unconfigured
operations), flagged ``isError``. Docstrings and ``Field`` descriptions become the tool
descriptions an LLM sees. Keys never appear in results, sidecars or logs.

(No ``from __future__ import annotations`` here: the SDK introspects these signatures at
registration time.)
"""

import functools
import json
import sys
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, Field

from . import http
from .config import (
    DEFAULT_OUTPUT_DIR,
    OP_SPECS,
    OPS,
    ConfigError,
    OpConfig,
    env_file_path,
    load_all,
    load_op,
    redact,
    require,
)
from .config import RESERVED_PARAM_KEYS
from .imaging import (
    DRIFT_WARN,
    ImageDataError,
    MaskError,
    boxes_to_mask,
    canonical_mask,
    composite_preserving,
    convert_canonical,
    display_size,
    fit_to_size,
    has_transparency,
    image_info as raster_info,
    image_size,
    normalize_boxes,
    normalize_mask_output,
    normalize_raster_input,
    prepare_mask,
    to_png_bytes,
    transfer_alpha,
    upscale_drift,
    white_fraction,
)
from .io import (
    InputError,
    InputFile,
    OutputBlob,
    WrittenFile,
    file_stem,
    new_file_path,
    output_directory,
    resolve_input,
    resolve_local_path,
    sanitize,
    unique_path,
    write_output,
)
from .providers import AdapterError, AdapterResult, ImageJob, get_adapter, supported_ops
from .providers.base import validate_svg
from .render import RenderError, bounded_width, render_svg, svg_to_pdf_layers
from .svg import SvgError, optimize_svg
from .svgtools import ComposeLayer, appearance_delta, compose, describe_layers, inspect, layerize, load_svg

MAX_SVG_TRANSFORM_BYTES = 512 * 1024
# Rendering differences after layering above these are reported as warnings (below: AA seams).
APPEARANCE_WARN_FRACTION = 0.01
APPEARANCE_WARN_MEAN = 1.5

# --- plumbing ----------------------------------------------------------------------------


class ToolFailure(Exception):
    """Anticipated failure with a structured payload."""

    def __init__(self, message: str, **payload: Any):
        super().__init__(message)
        self.payload = payload


def _payload(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"ok": True, "files": [], "notes": [], "warnings": []}
    base.update(kw)
    return base


def _result(payload: dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    text = json.dumps(sanitize(payload), indent=2, ensure_ascii=False)
    return CallToolResult(content=[TextContent(type="text", text=redact(text))], is_error=is_error)


def _error(tool: str, message: str, **extra: Any) -> CallToolResult:
    payload = {"ok": False, "tool": tool, "error": redact(message), **extra}
    return _result(payload, is_error=True)


EXPECTED_ERRORS = (
    ConfigError,
    AdapterError,
    InputError,
    MaskError,
    ImageDataError,
    SvgError,
    RenderError,
    ValueError,
)


def tool_entry(fn: Callable[..., Awaitable[dict[str, Any]]]) -> Callable[..., Awaitable[CallToolResult]]:
    """Turn payload dicts / anticipated exceptions into CallToolResults."""
    name = fn.__name__

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> CallToolResult:
        try:
            payload = await fn(*args, **kwargs)
        except ToolFailure as exc:
            print(f"image: {name} failed: {redact(str(exc))[:300]}", file=sys.stderr)
            return _error(name, str(exc), **exc.payload)
        except ConfigError as exc:
            print(f"image: {name} not configured: {redact(str(exc))[:300]}", file=sys.stderr)
            extra: dict[str, Any] = {"op": exc.op}
            if exc.missing_env:
                extra["missing_env"] = exc.missing_env
            return _error(name, str(exc), **extra)
        except EXPECTED_ERRORS as exc:
            print(f"image: {name} rejected: {redact(str(exc))[:300]}", file=sys.stderr)
            return _error(name, str(exc))
        except Exception as exc:  # unexpected: traceback on stderr, short message to the caller
            traceback.print_exc(file=sys.stderr)
            return _error(name, f"internal error in {name}: {type(exc).__name__}: {exc}")
        payload.setdefault("tool", name)
        print(f"image: {name} ok ({len(payload.get('files') or [])} file(s))", file=sys.stderr)
        return _result(payload)

    return wrapper


def _op_fields(cfg: OpConfig) -> dict[str, Any]:
    return {"op": cfg.op, "adapter": cfg.api, "url_host": cfg.host, "model": cfg.model}


async def _run(cfg: OpConfig, job: ImageJob, client: Any) -> AdapterResult:
    adapter = get_adapter(cfg, client)
    return await adapter.run(job)


def _write_outputs(
    outputs: list[OutputBlob],
    *,
    tool: str,
    cfg: OpConfig,
    res: AdapterResult,
    text_key: str,
    text: str | None,
    prefix: str | None,
    output_dir: str | None,
    inputs: list[InputFile],
    params: dict[str, Any],
    notes: list[str],
    warnings: list[str],
    extra: dict[str, Any] | None = None,
    ext_tag: str | None = None,
) -> list[dict[str, Any]]:
    directory = output_directory(output_dir, DEFAULT_OUTPUT_DIR)
    stem = file_stem(prefix, text, ext_tag or cfg.op.lower())
    files: list[dict[str, Any]] = []
    for i, blob in enumerate(outputs):
        sidecar = {
            "tool": tool,
            **_op_fields(cfg),
            "endpoint": res.endpoint,
            **({text_key: text} if text is not None else {}),
            "params": {k: v for k, v in params.items() if v is not None},
            "op_params": cfg.params,
            "directives": cfg.directives,
            "request": res.request,
            "inputs": [f.describe() for f in inputs],
            "notes": notes,
            "warnings": warnings,
            "index": i,
            **(extra or {}),
        }
        files.append(write_output(blob, directory, stem, sidecar).as_dict())
    return files


async def _inputs(refs: list[str] | None, client: Any) -> list[InputFile]:
    return [await _raster(await resolve_input(r, client)) for r in refs or []]


async def _raster(f: InputFile) -> InputFile:
    """Every raster-op input, normalised once so providers and the local fidelity steps agree.

    * SVG inputs are rendered to PNG (resvg; at most 4096 px on the longest side by default);
    * EXIF orientation is applied, so a phone photo is processed (and sent) upright, as the user
      sees it - sizes, masks, composites and outputs all use the displayed orientation;
    * formats the routers do not accept (TIFF, BMP, AVIF, HEIC, ...) become PNG.

    A converted input gets ``url=None`` (its bytes are sent, not the original URL) and notes.
    """
    if f.mime == "image/svg+xml":
        load_svg(f.data)
        width, note = bounded_width(f.data, None)
        png = await anyio.to_thread.run_sync(lambda: render_svg(f.data, width=width))
        notes = [f"{f.name}: SVG rendered to PNG" + (f" ({note})" if note else "")]
        return InputFile(png, "image/png", Path(f.name).with_suffix(".png").name, f"{f.source} (rendered to PNG)", notes=notes)
    fixed = await anyio.to_thread.run_sync(lambda: normalize_raster_input(f.data, f.mime))
    if fixed is None:
        return f
    data, mime, notes = fixed
    suffix = ".jpg" if mime == "image/jpeg" else ".png"
    what = "upright" if any("orientation" in n for n in notes) else "PNG"
    return InputFile(data, mime, Path(f.name).with_suffix(suffix).name, f"{f.source} (converted: {what})",
                     notes=[f"{f.name}: {n}" for n in notes])


def _input_notes(*inputs: InputFile | None) -> list[str]:
    return [n for f in inputs if f is not None for n in f.notes]


def _aspect_warning(what: str, stats: dict[str, Any], source: tuple[int, int]) -> str | None:
    if not stats.get("aspect_mismatch"):
        return None
    mw, mh = stats.get("model_size") or ("?", "?")
    return (
        f"the model returned a {mw}x{mh} {what} for a {source[0]}x{source[1]} source (another aspect ratio): it was "
        "scaled to cover the source frame and centre-cropped, not stretched, so its content may not line up with the "
        "source - pass aspect_ratio or size so the model keeps the source framing, and check the result"
    )


async def _raster_input(ref: str, client: Any) -> InputFile:
    return await _raster(await resolve_input(ref, client))


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# Shared parameter annotations ---------------------------------------------------------------------

ImageRef = Annotated[
    str,
    Field(description="Image: a local path (relative to the project directory, ~ allowed), file:// URL, http(s) URL or data URI."),
]
SvgPath = Annotated[str, Field(description="SVG file (path relative to the project directory).")]
OutputDir = Annotated[
    str | None,
    Field(description="Directory for results (relative to the project). Default <project>/.stack/images/<YYYYMMDD>/; each file gets a <file>.json sidecar."),
]
Prefix = Annotated[str | None, Field(description="File name prefix; default is a slug of the prompt.")]
Params = Annotated[
    dict[str, Any] | None,
    Field(description="Extra request fields for the configured endpoint, deep-merged last (after IMAGE_<OP>_PARAMS), e.g. {'provider': {'options': {...}}} on OpenRouter or {'parameters': {...}} on Opper. Reserved (rejected): " + ", ".join(sorted(RESERVED_PARAM_KEYS)) + " - the model is always IMAGE_<OP>_MODEL and the prompt/images come from the tool's own arguments."),
]
AspectRatio = Annotated[str | None, Field(description="e.g. '1:1', '16:9', '9:16', '4:3', '3:2'.")]
Size = Annotated[str | None, Field(description="A tier '1K'/'2K'/'4K' or explicit 'WIDTHxHEIGHT' (validated per model where the router can).")]
Quality = Annotated[str | None, Field(description="auto | low | medium | high (| xhigh | max on models that offer them).")]
Count = Annotated[int, Field(ge=1, le=4, description="Number of images (1-4). Each image is billed.")]
Seed = Annotated[int | None, Field(description="Seed for reproducibility where the model supports it.")]
OutputFormat = Annotated[Literal["png", "jpeg", "webp"] | None, Field(description="Output raster format (default: the model's).")]
OutputPath = Annotated[str | None, Field(description="Where to write (relative to the project); default next to the input.")]


# --- operation tools -----------------------------------------------------------------------------


async def _generate(tool: str, op: str, task: str, *, prompt: str, references: list[str] | None, aspect_ratio, size, n, quality, seed, output_format, output_dir, filename_prefix, params) -> dict[str, Any]:
    cfg = require(op, tool)
    async with http.new_client() as client:
        refs = await _inputs(references, client)
        job = ImageJob(
            op=op, task=task, prompt=prompt, references=refs, n=n, size=size, aspect_ratio=aspect_ratio,
            quality=quality, seed=seed, output_format=output_format, call_params=dict(params or {}),
        )
        res = await _run(cfg, job, client)
    notes, warnings = _input_notes(*refs) + list(res.notes), list(res.warnings)
    if task == "transparent":
        opaque = sum(1 for o in res.outputs if not _safe_transparency(o.data))
        if opaque:
            warnings.append(
                f"{opaque} of {len(res.outputs)} output(s) have no transparent pixels: the configured model "
                f"({cfg.model}) may not support transparent backgrounds"
            )
    files = _write_outputs(
        res.outputs, tool=tool, cfg=cfg, res=res, text_key="prompt", text=prompt, prefix=filename_prefix,
        output_dir=output_dir, inputs=refs, notes=notes, warnings=warnings,
        params=_clean({"aspect_ratio": aspect_ratio, "size": size, "n": n, "quality": quality, "seed": seed,
                       "output_format": output_format, "params": params}),
    )
    return _payload(files=files, notes=notes, warnings=warnings, **_op_fields(cfg))


def _safe_transparency(data: bytes) -> bool:
    try:
        return has_transparency(data)
    except ImageDataError:
        return False


@tool_entry
async def image_generate(
    prompt: Annotated[str, Field(description="What to draw: subject, composition, style, lighting, any text to render.")],
    aspect_ratio: AspectRatio = None,
    size: Size = None,
    n: Count = 1,
    quality: Quality = None,
    seed: Seed = None,
    output_format: OutputFormat = None,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Text -> image with the model configured for GEN (IMAGE_GEN_URL / _KEY / _MODEL).

    Exactly that endpoint and model are used (no fallback); if GEN is not configured the error names
    the env vars to set. Files are saved under .stack/images/<date>/ with a JSON sidecar (op, adapter,
    URL host, model tag, prompt, params - never keys). Returns JSON {ok, files, op, adapter, url_host,
    model, notes, warnings}.
    """
    return await _generate("image_generate", "GEN", "generate", prompt=prompt, references=None,
                           aspect_ratio=aspect_ratio, size=size, n=n, quality=quality, seed=seed,
                           output_format=output_format, output_dir=output_dir, filename_prefix=filename_prefix, params=params)


@tool_entry
async def image_generate_with_references(
    prompt: Annotated[str, Field(description="What to make; refer to references by order, e.g. 'the person in image 1 wearing the jacket from image 2'.")],
    references: Annotated[list[str], Field(min_length=1, max_length=16, description="1..N reference images (paths, URLs or data URIs) for subject, character, product or style consistency.")],
    aspect_ratio: AspectRatio = None,
    size: Size = None,
    n: Count = 1,
    quality: Quality = None,
    seed: Seed = None,
    output_format: OutputFormat = None,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Generation guided by 1..N reference images, with the model configured for REF.

    References go to the endpoint as input_references (OpenRouter), reference_images (Opper) or
    image[] (OpenAI-compatible). Per-model reference limits apply (e.g. 16 for GPT Image, 14 for
    Gemini image models). Returns JSON {ok, files, op, adapter, url_host, model, notes, warnings}.
    """
    return await _generate("image_generate_with_references", "REF", "references", prompt=prompt, references=references,
                           aspect_ratio=aspect_ratio, size=size, n=n, quality=quality, seed=seed,
                           output_format=output_format, output_dir=output_dir, filename_prefix=filename_prefix, params=params)


@tool_entry
async def image_generate_transparent(
    prompt: Annotated[str, Field(description="The isolated subject to draw (no background).")],
    aspect_ratio: AspectRatio = None,
    size: Size = None,
    n: Count = 1,
    quality: Quality = None,
    seed: Seed = None,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Generate an RGBA PNG with a transparent background, with the model configured for TRANSPARENT.

    Sends background=transparent + output_format=png (OpenRouter / OpenAI) or parameters.background
    (Opper; checked against the model catalog first). Use a model with native alpha (e.g. GPT Image
    2.5 flare/sunburst). Outputs without transparent pixels are flagged in warnings.
    """
    return await _generate("image_generate_transparent", "TRANSPARENT", "transparent", prompt=prompt, references=None,
                           aspect_ratio=aspect_ratio, size=size, n=n, quality=quality, seed=seed, output_format="png",
                           output_dir=output_dir, filename_prefix=filename_prefix, params=params)


@tool_entry
async def image_edit(
    image: ImageRef,
    instruction: Annotated[str, Field(description="What to change, in plain words (e.g. 'replace the sky with a sunset').")],
    mask: Annotated[
        str | None,
        Field(description="Optional mask the size of the image: WHITE = edit, BLACK = keep (an RGBA mask with transparent pixels also works: transparent = edit). Converted per adapter. Make one with image_segment."),
    ] = None,
    references: Annotated[list[str] | None, Field(description="Extra reference images (style, objects to insert).")] = None,
    preserve_unmasked: Annotated[
        bool,
        Field(description="With a mask: resize the result to the source and composite it through the mask (feathered inwards) so every pixel outside the mask stays identical to the source."),
    ] = True,
    feather: Annotated[float, Field(ge=0, le=8, description="Inward feather of the mask edge in px when compositing (1-2 is typical).")] = 1.5,
    resize_mask: Annotated[bool, Field(description="Resize a mask of a different size to the image (nearest) instead of failing.")] = False,
    n: Count = 1,
    size: Size = None,
    aspect_ratio: AspectRatio = None,
    quality: Quality = None,
    output_format: OutputFormat = None,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Edit an image with an instruction (model configured for EDIT); masked inpainting when `mask` is given.

    Masks: OpenAI-compatible endpoints get an alpha mask (transparent = edit); Opper gets the model's
    convention (alpha for GPT Image, black = edit for Ideogram, else white = edit); OpenRouter has no
    mask parameter, so the mask is sent as a second input image with an explicit instruction. With
    preserve_unmasked (default) the output is composited locally so pixels outside the mask are
    unchanged. Returns JSON {ok, files, op, adapter, url_host, model, notes, warnings, fidelity}.
    """
    tool = "image_edit"
    cfg = require("EDIT", tool)
    async with http.new_client() as client:
        src = await _raster_input(image, client)
        refs = await _inputs(references, client)
        # the mask goes through the same normalisation (upright, PNG) so it matches the upright source
        mask_file = await _raster_input(mask, client) if mask else None
        mask_l = prepare_mask(mask_file.data, image_size(src.data), resize=resize_mask) if mask_file else None
        job = ImageJob(
            op="EDIT", task="edit", prompt=instruction, image=src, mask=mask_l, references=refs, n=n, size=size,
            aspect_ratio=aspect_ratio, quality=quality, output_format=output_format, call_params=dict(params or {}),
        )
        res = await _run(cfg, job, client)
    notes, warnings = _input_notes(src, *refs, mask_file) + list(res.notes), list(res.warnings)
    outputs = res.outputs
    fidelity: list[dict[str, Any]] = []
    if mask_l is not None:
        if preserve_unmasked:
            fixed = []
            for o in outputs:
                data, stats = composite_preserving(src.data, o.data, mask_l, feather)
                fixed.append(OutputBlob(data, "image/png", meta=o.meta))
                fidelity.append(stats)
            outputs = fixed
            warnings += list(dict.fromkeys(
                w for s_ in fidelity if (w := _aspect_warning("result", s_, image_size(src.data)))))
            drift = max(s["drift_outside_mask"] for s in fidelity)
            notes.append(
                f"preserve_unmasked: result composited through the mask (feather {feather}px); pixels outside the "
                f"mask are identical to the source (model drift there was {drift:.1f}/255 and was discarded)"
            )
            if all(s["change_inside_mask"] < 1.0 for s in fidelity):
                warnings.append("the model changed almost nothing inside the mask; the edit may have been ignored")
        else:
            warnings.append("preserve_unmasked=false: pixels outside the mask may differ from the source")
    files = _write_outputs(
        outputs, tool=tool, cfg=cfg, res=res, text_key="instruction", text=instruction, prefix=filename_prefix,
        output_dir=output_dir, inputs=[src, *refs, *([mask_file] if mask_file else [])], notes=notes, warnings=warnings,
        params=_clean({"masked": mask is not None, "preserve_unmasked": preserve_unmasked if mask else None,
                       "feather": feather if mask else None, "n": n, "size": size, "aspect_ratio": aspect_ratio,
                       "quality": quality, "output_format": output_format, "params": params}),
        extra={"fidelity": fidelity} if fidelity else None,
    )
    return _payload(files=files, notes=notes, warnings=warnings, fidelity=fidelity or None, **_op_fields(cfg))


@tool_entry
async def image_segment(
    image: ImageRef,
    prompt: Annotated[str, Field(description="The object/region to select, e.g. 'the red car', 'sky', 'the person on the left'.")],
    invert: Annotated[bool, Field(description="Invert: white = everything EXCEPT the prompted object.")] = False,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Segmentation with the model configured for SEGMENT: a white-on-black PNG mask of the source size.

    WHITE = the prompted object (the region an edit should change), BLACK = keep; pass it straight to
    image_edit(mask=...). Strategy 'render' (default) asks the image model for a pure black/white mask
    and normalises it locally (threshold + resize to the source); IMAGE_SEGMENT_PARAMS={"strategy":"detect"}
    uses a vision chat model that returns boxes (e.g. moondream), rasterised into the mask.
    """
    tool = "image_segment"
    cfg = require("SEGMENT", tool)
    async with http.new_client() as client:
        src = await _raster_input(image, client)
        job = ImageJob(op="SEGMENT", task="mask", prompt=prompt, image=src, call_params=dict(params or {}))
        res = await _run(cfg, job, client)
    notes, warnings = _input_notes(src) + list(res.notes), list(res.warnings)
    size = image_size(src.data)
    if res.boxes is not None:
        boxes, space = normalize_boxes(res.boxes, size)
        data = boxes_to_mask(size, boxes)
        covered = white_fraction(data)
        if invert:
            from PIL import ImageOps

            data = to_png_bytes(ImageOps.invert(canonical_mask(data)))
        stats: dict[str, Any] = {"boxes": len(res.boxes), "coordinates": space, "white_fraction": white_fraction(data)}
        if space != "0-1":
            notes.append(f"the model answered in {space} coordinates, not 0-1 fractions: boxes rescaled to the {size[0]}x{size[1]} image")
        if not res.boxes:
            warnings.append(f"the model found no '{prompt}': the mask is empty")
        elif covered in (0.0, 1.0):
            warnings.append(
                f"the {len(res.boxes)} box(es) cover {'none' if covered == 0 else 'all'} of the image: "
                "check the model's coordinates (mask_stats) before using this mask"
            )
    else:
        if not res.outputs:
            raise ToolFailure("the model returned no mask image", **_op_fields(cfg))
        data, stats = normalize_mask_output(res.outputs[0].data, size, invert=invert)
        if stats["binary_fraction"] < 0.8:
            warnings.append(
                f"the model output is only {stats['binary_fraction']:.0%} pure black/white: it may be a picture rather "
                "than a mask - inspect it, or use a segmentation-capable model / the 'detect' strategy"
            )
        if stats["white_fraction"] in (0.0, 1.0):
            warnings.append("the normalised mask is all black or all white")
        if w := _aspect_warning("mask", stats, size):
            warnings.append(w)
    files = _write_outputs(
        [OutputBlob(data, "image/png")], tool=tool, cfg=cfg, res=res, text_key="prompt", text=prompt,
        prefix=filename_prefix or f"mask-{prompt}", output_dir=output_dir, inputs=[src], notes=notes,
        warnings=warnings, params=_clean({"invert": invert, "params": params}), extra={"mask_stats": stats},
    )
    return _payload(files=files, notes=notes, warnings=warnings, mask_stats=stats, **_op_fields(cfg))


@tool_entry
async def image_remove_background(
    image: ImageRef,
    preserve_pixels: Annotated[
        bool,
        Field(description="Put the model's alpha onto the ORIGINAL pixels (the model's re-rendered RGB is discarded); drift is measured and reported."),
    ] = True,
    prompt: Annotated[str | None, Field(description="Optional guidance, e.g. 'keep the shadow'.")] = None,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Cut out the subject as an RGBA PNG, with the model configured for BG_REMOVAL.

    The routers have no dedicated matting model, so the configured image model regenerates the image
    with a transparent background; with preserve_pixels (default) only its alpha is kept and applied
    to the original pixels, and RGB drift inside the alpha is reported (warning when high).
    """
    tool = "image_remove_background"
    cfg = require("BG_REMOVAL", tool)
    async with http.new_client() as client:
        src = await _raster_input(image, client)
        job = ImageJob(op="BG_REMOVAL", task="remove_background", prompt=prompt or "", image=src, output_format="png",
                       call_params=dict(params or {}))
        res = await _run(cfg, job, client)
    notes, warnings = _input_notes(src) + list(res.notes), list(res.warnings)
    outputs: list[OutputBlob] = []
    fidelity: list[dict[str, Any]] = []
    for o in res.outputs:
        if not _safe_transparency(o.data):
            warnings.append("the model output has no transparent pixels: background removal failed with this model")
            outputs.append(o)
            continue
        if not preserve_pixels:
            outputs.append(o)
            continue
        data, stats = transfer_alpha(src.data, o.data)
        fidelity.append(stats)
        if data is None:
            warnings.append(f"alpha not transferred ({stats.get('reason')}); the model's own pixels are kept")
            outputs.append(o)
            continue
        outputs.append(OutputBlob(data, "image/png"))
        notes.append(f"preserve_pixels: the model's alpha was applied to the original pixels (RGB drift {stats['drift']:.1f}/255)")
        if stats["drift"] > DRIFT_WARN:
            warnings.append(
                f"high drift ({stats['drift']:.1f}/255): the model re-rendered or moved the subject, so the transferred "
                "alpha may not fit the original exactly - check the edges"
            )
    files = _write_outputs(
        outputs, tool=tool, cfg=cfg, res=res, text_key="prompt", text=prompt, prefix=filename_prefix or f"{Path(src.name).stem}-cutout",
        output_dir=output_dir, inputs=[src], notes=notes, warnings=warnings,
        params=_clean({"preserve_pixels": preserve_pixels, "params": params}), extra={"fidelity": fidelity} if fidelity else None,
    )
    return _payload(files=files, notes=notes, warnings=warnings, fidelity=fidelity or None, **_op_fields(cfg))


@tool_entry
async def image_upscale(
    image: ImageRef,
    scale: Annotated[float, Field(gt=1.0, le=8.0, description="Upscale factor (e.g. 2 or 4).")] = 2.0,
    prompt: Annotated[str | None, Field(description="Optional guidance for model-based upscalers.")] = None,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Upscale an image by `scale` with the UPSCALE configuration.

    IMAGE_UPSCALE_API=local uses Pillow Lanczos (faithful, no invented detail). Remote models
    regenerate the image at a higher resolution; the result is resized to exactly scale x the
    source and its drift from the source is reported (warning when high).
    """
    tool = "image_upscale"
    cfg = require("UPSCALE", tool)
    async with http.new_client() as client:
        src = await _raster_input(image, client)
        w0, h0 = image_size(src.data)
        target = (max(1, round(w0 * scale)), max(1, round(h0 * scale)))
        if max(target) > 16384 or target[0] * target[1] > 8192 * 8192 * 2:
            raise ToolFailure(f"target size {target[0]}x{target[1]} is too large (max edge 16384 px)")
        job = ImageJob(op="UPSCALE", task="upscale", prompt=prompt or "", image=src, target_size=target,
                       call_params=dict(params or {}))
        res = await _run(cfg, job, client)
    notes, warnings = _input_notes(src) + list(res.notes), list(res.warnings)
    outputs = []
    fidelity: list[dict[str, Any]] = []
    for o in res.outputs:
        data, stats = fit_to_size(o.data, target)
        if not cfg.is_local:
            stats["drift"] = upscale_drift(src.data, data)
            if stats.get("resized_to"):
                notes.append(f"model output {stats['model_size'][0]}x{stats['model_size'][1]} resized (Lanczos) to {target[0]}x{target[1]}")
            if stats["drift"] > DRIFT_WARN:
                warnings.append(f"high drift from the source ({stats['drift']:.1f}/255): the model changed the content")
            if w := _aspect_warning("image", stats, (w0, h0)):
                warnings.append(w)
        fidelity.append(stats)
        outputs.append(OutputBlob(data, "image/png"))
    files = _write_outputs(
        outputs, tool=tool, cfg=cfg, res=res, text_key="prompt", text=prompt, prefix=filename_prefix or f"{Path(src.name).stem}-x{scale:g}",
        output_dir=output_dir, inputs=[src], notes=notes, warnings=warnings,
        params=_clean({"scale": scale, "target": f"{target[0]}x{target[1]}", "params": params}), extra={"fidelity": fidelity},
    )
    return _payload(files=files, notes=notes, warnings=warnings, fidelity=fidelity, **_op_fields(cfg))


def _svg_outputs(outputs: list[OutputBlob], *, layered: bool, by: str, notes: list[str]) -> tuple[list[OutputBlob], list[dict[str, Any]]]:
    """Validate SVG outputs; optionally layerize them (by colour for traces, by group for generations)."""
    fixed: list[OutputBlob] = []
    reports: list[dict[str, Any]] = []
    for o in outputs:
        try:
            text = o.data.decode("utf-8-sig")  # a byte-order mark is dropped, not kept as U+FEFF
        except UnicodeDecodeError:
            raise AdapterError("the model output is not UTF-8 SVG text") from None
        text = validate_svg(text)
        if layered:
            original = text
            text, report = layerize(text, by=by)
            appearance = appearance_delta(original, text)
            reports.append({"by": by, "layer_count": report["layer_count"], "layers": report["layers"][:50],
                            "z_order": report.get("z_order"), "appearance": appearance, "notes": report["notes"]})
        fixed.append(OutputBlob(text.encode("utf-8"), "image/svg+xml"))
    if layered and reports:
        notes.append(f"layered by {by}: {', '.join(str(r['layer_count']) for r in reports)} layer(s) (inkscape:groupmode=layer)")
    return fixed, reports


def appearance_warning(appearance: dict[str, Any] | None) -> str | None:
    """A warning when layering visibly changed the rendering (beyond anti-aliasing seams), or when
    the change could not be measured."""
    if not appearance:
        return None
    if "error" in appearance:
        return f"appearance could not be verified: {appearance['error']} - compare with svg_render"
    if appearance["changed_fraction"] > APPEARANCE_WARN_FRACTION or appearance["mean_abs_diff"] > APPEARANCE_WARN_MEAN:
        return (f"layering changed the rendering on {appearance['changed_fraction']:.2%} of pixels "
                f"(mean diff {appearance['mean_abs_diff']:.2f}/255) - compare with svg_render")
    return None


@tool_entry
async def vector_generate(
    prompt: Annotated[str, Field(description="Icon, logo or illustration to draw as an SVG.")],
    style: Annotated[str | None, Field(description="Style hint (e.g. 'flat icon', 'line art'), folded into the prompt.")] = None,
    aspect_ratio: AspectRatio = None,
    layered: Annotated[bool, Field(description="Rewrite the SVG into top-level layers (by group) for Illustrator/Inkscape; follow with export_pdf for a layered PDF.")] = False,
    n: Count = 1,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Native SVG generation with the model configured for VECTOR.

    OpenRouter: an SVG model (e.g. recraft/recraft-v4.1-vector) with output_format=svg. Opper: the
    image endpoint must return image/svg+xml, or set IMAGE_VECTOR_PARAMS={"strategy":"chat"} to have
    an LLM write the SVG (the default for OpenAI-compatible endpoints). Output is validated as
    well-formed SVG. Returns JSON {ok, files, op, adapter, url_host, model, notes, warnings, layers?}.
    """
    tool = "vector_generate"
    cfg = require("VECTOR", tool)
    async with http.new_client() as client:
        job = ImageJob(op="VECTOR", task="vector", prompt=prompt, style=style, aspect_ratio=aspect_ratio, n=n,
                       call_params=dict(params or {}), options={"layered": layered})
        res = await _run(cfg, job, client)
    notes, warnings = list(res.notes), list(res.warnings)
    outputs, reports = _svg_outputs(res.outputs, layered=layered, by="group", notes=notes)
    warnings += [w for r in reports if (w := appearance_warning(r.get("appearance")))]
    files = _write_outputs(
        outputs, tool=tool, cfg=cfg, res=res, text_key="prompt", text=prompt, prefix=filename_prefix,
        output_dir=output_dir, inputs=[], notes=notes, warnings=warnings,
        params=_clean({"style": style, "aspect_ratio": aspect_ratio, "layered": layered, "n": n, "params": params}),
        extra={"layers": reports} if reports else None,
    )
    return _payload(files=files, notes=notes, warnings=warnings, layers=reports or None, **_op_fields(cfg))


@tool_entry
async def image_vectorize(
    image: ImageRef,
    layered: Annotated[bool, Field(description="One layer per colour (inkscape:groupmode=layer); z-order and appearance preserved. Follow with export_pdf for a layered PDF.")] = False,
    colormode: Annotated[Literal["color", "binary"], Field(description="Local vtracer only: colour or black-and-white tracing.")] = "color",
    prompt: Annotated[str | None, Field(description="Optional guidance for model-based tracing.")] = None,
    output_dir: OutputDir = None,
    filename_prefix: Prefix = None,
    params: Params = None,
) -> dict[str, Any]:
    """Raster -> SVG tracing with the TRACE configuration.

    IMAGE_TRACE_API=local runs vtracer (MIT) locally - faithful tracing, settings via
    IMAGE_TRACE_PARAMS/params (filter_speckle, color_precision, mode, ...). Router models redraw the
    image as SVG (OpenRouter SVG models with the image as reference; Opper/OpenAI-compatible via a
    vision LLM, strategy 'chat'), which is an approximation. Output is validated as SVG.
    """
    tool = "image_vectorize"
    cfg = require("TRACE", tool)
    async with http.new_client() as client:
        src = await _raster_input(image, client)
        job = ImageJob(op="TRACE", task="trace", prompt=prompt or "", image=src, call_params=dict(params or {}),
                       options={"layered": layered, "colormode": colormode})
        res = await _run(cfg, job, client)
    notes, warnings = _input_notes(src) + list(res.notes), list(res.warnings)
    if not cfg.is_local:
        warnings.append("model-based tracing redraws the image: shapes may differ from the source (IMAGE_TRACE_API=local traces faithfully)")
    outputs, reports = _svg_outputs(res.outputs, layered=layered, by="color", notes=notes)
    warnings += [w for r in reports if (w := appearance_warning(r.get("appearance")))]
    files = _write_outputs(
        outputs, tool=tool, cfg=cfg, res=res, text_key="prompt", text=prompt, prefix=filename_prefix or f"{Path(src.name).stem}-vector",
        output_dir=output_dir, inputs=[src], notes=notes, warnings=warnings,
        params=_clean({"layered": layered, "colormode": colormode, "params": params}),
        extra={"layers": reports} if reports else None,
    )
    return _payload(files=files, notes=notes, warnings=warnings, layers=reports or None, **_op_fields(cfg))


@tool_entry
async def svg_transform(
    svg_path: SvgPath,
    instruction: Annotated[str, Field(description="The change to make, e.g. 'make the outline 2px and recolour the leaf #2a9d8f'.")],
    output_path: Annotated[str | None, Field(description="Where to write; default .stack/images/<date>/<name>-transformed-<time>.svg.")] = None,
    params: Params = None,
) -> dict[str, Any]:
    """Edit an SVG with the external model configured for VECTOR_MANIPULATION (chat completions).

    Only available when IMAGE_VECTOR_MANIPULATION_MODEL is set to something other than 'claude'. The
    SVG text and the instruction are sent; the reply must be a complete SVG, which is validated as
    well-formed before it is written. The input file is never modified.
    """
    tool = "svg_transform"
    cfg = load_op("VECTOR_MANIPULATION")
    if cfg.is_claude:
        raise ToolFailure(
            "svg_transform is disabled: IMAGE_VECTOR_MANIPULATION_MODEL is 'claude' (the default), so edit the SVG "
            "directly with Read/Edit (svg_inspect / svg_render / svg_layers help). Set IMAGE_VECTOR_MANIPULATION_URL, "
            "_KEY and _MODEL to use an external model instead.",
            op="VECTOR_MANIPULATION",
        )
    cfg = require("VECTOR_MANIPULATION", tool)
    src = resolve_local_path(svg_path)
    if not src.is_file():
        raise InputError(f"file not found: {src}")
    raw = src.read_bytes()
    if len(raw) > MAX_SVG_TRANSFORM_BYTES:
        raise ToolFailure(f"{src.name} is {len(raw)} bytes; svg_transform accepts up to {MAX_SVG_TRANSFORM_BYTES} (run svg_optimize first)")
    load_svg(raw)  # well-formed input only
    async with http.new_client() as client:
        job = ImageJob(op="VECTOR_MANIPULATION", task="svg_transform", prompt=instruction, svg_text=raw.decode("utf-8"),
                       call_params=dict(params or {}))
        res = await _run(cfg, job, client)
    notes, warnings = list(res.notes), []
    blob = res.outputs[0]
    if output_path:
        dest = resolve_local_path(output_path)
        if dest == src:
            raise ToolFailure("output_path must differ from svg_path (the input is never modified)")
        written = write_output(blob, dest.parent, dest.stem, {
            "tool": tool, **_op_fields(cfg), "endpoint": res.endpoint, "instruction": instruction,
            "params": _clean({"params": params}), "inputs": [{"source": str(src), "bytes": len(raw)}],
            "notes": notes, "request": res.request,
        }, exact_path=dest)
        files = [written.as_dict()]
    else:
        files = _write_outputs(
            [blob], tool=tool, cfg=cfg, res=res, text_key="instruction", text=instruction, prefix=f"{src.stem}-transformed",
            output_dir=None, inputs=[InputFile(raw, "image/svg+xml", src.name, str(src))], notes=notes, warnings=warnings,
            params=_clean({"params": params}),
        )
    return _payload(files=files, notes=notes, warnings=warnings, **_op_fields(cfg))


# --- local tools -----------------------------------------------------------------------------------


@tool_entry
async def image_ops_status() -> dict[str, Any]:
    """Per image operation: configured (bool), adapter, URL host, model tag and the missing env names.

    Read from ~/.claude/stack.env (CLAUDE_STACK_ENV) at call time - edits apply without a restart.
    Never shows keys. Also says whether svg_transform is exposed (IMAGE_VECTOR_MANIPULATION_MODEL
    other than 'claude') and which operations each adapter supports.
    """
    cfgs = load_all()
    ops = {op: cfg.describe() for op, cfg in cfgs.items()}
    vm = cfgs["VECTOR_MANIPULATION"]
    env_path = env_file_path()
    notes = [
        "set IMAGE_<OP>_URL, IMAGE_<OP>_KEY and IMAGE_<OP>_MODEL per operation (OpenRouter: https://openrouter.ai/api/v1, "
        "Opper: https://api.opper.ai); optional IMAGE_<OP>_API (openrouter|opper|openai, local for TRACE/UPSCALE) and "
        "IMAGE_<OP>_PARAMS (JSON merged into every request)",
        "no fallbacks: each operation uses exactly its configured endpoint and model",
    ]
    unconfigured = [op for op, c in cfgs.items() if not c.configured]
    if unconfigured:
        notes.append(f"not configured: {', '.join(unconfigured)}")
    return _payload(
        env_file=str(env_path),
        env_file_exists=env_path.is_file(),
        ops=ops,
        configured=[op for op, c in cfgs.items() if c.configured],
        vector_manipulation="claude" if vm.is_claude else "external",
        svg_transform_exposed=not vm.is_claude,
        adapters=supported_ops(),
        local_tools=sorted(LOCAL_TOOL_NAMES),
        notes=notes,
    )


@tool_entry
async def image_info(image: ImageRef) -> dict[str, Any]:
    """Size, mode, alpha (present / actually used), format and file size of an image (no model call).

    SVG inputs report their declared size, viewBox and layer count (use svg_inspect for details).
    """
    async with http.new_client() as client:
        f = await resolve_input(image, client)
    base = {"source": f.source, "mime": f.mime, "bytes": len(f.data)}
    if f.mime == "image/svg+xml":
        root = load_svg(f.data)
        lay = describe_layers(root)
        return _payload(**base, format="SVG", width=root.get("width"), height=root.get("height"),
                        viewBox=root.get("viewBox"), layer_count=lay["layer_count"])
    return _payload(**base, **raster_info(f.data))


@tool_entry
async def mask_convert(
    mask: Annotated[str, Field(description="Mask image (path/URL/data URI): white/black or RGBA (transparent = edit).")],
    to: Annotated[Literal["white-edit", "black-edit", "alpha-transparent"], Field(description="Target convention: white-edit (white = edit), black-edit (black = edit), alpha-transparent (RGBA, transparent = edit; OpenAI).")],
    invert: Annotated[bool, Field(description="Swap edit and keep regions before converting.")] = False,
    match_image: Annotated[str | None, Field(description="Optional image whose size the mask must have (resized nearest-neighbour if different).")] = None,
    output_path: OutputPath = None,
) -> dict[str, Any]:
    """Convert a mask between conventions (local, free). The input is read as: transparent pixels =
    edit when it has transparency, else luminance >= 128 = edit; then optionally inverted/resized."""
    from PIL import ImageOps

    async with http.new_client() as client:
        f = await resolve_input(mask, client)
        ref = await resolve_input(match_image, client) if match_image else None
    mf = await _raster(f)  # upright, PNG-readable (SVG masks are rendered)
    notes: list[str] = list(mf.notes)
    m = canonical_mask(mf.data)
    if ref is not None:
        size = image_size((await _raster(ref)).data) if ref.mime == "image/svg+xml" else display_size(ref.data)
        if m.size != size:
            from PIL import Image

            m = m.resize(size, Image.Resampling.NEAREST)
            notes.append(f"resized to {size[0]}x{size[1]} (nearest)")
    if invert:
        m = ImageOps.invert(m)
    data = to_png_bytes(convert_canonical(m, to))
    if output_path:
        dest = resolve_local_path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
    elif f.source.startswith(("data:", "http")):
        dest = unique_path(output_directory(None, DEFAULT_OUTPUT_DIR), f"mask-{to}", ".png")
    else:
        dest, note = _default_output(Path(f.source), f".{to}.png")
        if note:
            notes.append(note)
    dest.write_bytes(data)
    white = m.histogram()[255] / (m.width * m.height or 1)
    notes.append(f"edit region covers {white:.1%} of the image")
    return _payload(files=[WrittenFile(dest, "image/png", len(data), m.width, m.height).as_dict()], convention=to, notes=notes)


@tool_entry
async def svg_optimize(
    svg_path: SvgPath,
    precision: Annotated[int, Field(ge=0, le=8, description="Decimals kept in coordinates (2 is visually lossless for most icons).")] = 2,
    output_path: Annotated[str | None, Field(description="Where to write; default <name>.min.svg next to the input (input untouched).")] = None,
) -> dict[str, Any]:
    """Optimise an SVG locally (no API call, free).

    Checks well-formedness, strips comments, <metadata> and editor data (keeping the inkscape layer
    markers), rounds path data and numeric attributes to `precision` decimals, adds a viewBox from
    width/height when missing, and serialises compactly.
    """
    src = _svg_file(svg_path)
    out_text, stats = optimize_svg(src.read_bytes(), precision)
    dest, where = _derived(src, ".min.svg", output_path)
    dest.write_text(out_text, encoding="utf-8")
    saved = 100 * (1 - stats.bytes_out / stats.bytes_in) if stats.bytes_in else 0.0
    notes = [
        f"{stats.bytes_in} -> {stats.bytes_out} bytes ({saved:.1f}% smaller)",
        f"removed {stats.removed_elements} element(s) and {stats.removed_attributes} attribute(s)",
    ] + ([where] if where else [])
    if stats.added_viewbox:
        notes.append("added viewBox from width/height")
    return _payload(files=[WrittenFile(dest, "image/svg+xml", stats.bytes_out).as_dict()], notes=notes)


def _svg_file(svg_path: str) -> Path:
    src = resolve_local_path(svg_path)
    if not src.is_file():
        raise InputError(f"file not found: {src}")
    return src


def _default_output(src: Path, suffix: str) -> tuple[Path, str | None]:
    """``<src stem><suffix>`` next to ``src``, created atomically; never an existing file.

    When the default name is taken (e.g. a designer's own logo.pdf next to logo.svg) a free
    ``-2``, ``-3`` ... variant is used and a note says so: only an explicit output_path
    overwrites.
    """
    ext = suffix[suffix.rfind(".") :]  # ".pdf", ".preview.png" -> ".png" (Path(".pdf").suffix is "")
    stem = f"{src.stem}{suffix[: len(suffix) - len(ext)]}"
    default = src.with_name(f"{stem}{ext}")
    dest = new_file_path(src.parent, stem, ext)
    if dest != default:
        return dest, f"{default.name} already exists: wrote {dest.name} instead (pass output_path to overwrite)"
    return dest, None


def _derived(src: Path, suffix: str, output_path: str | None) -> tuple[Path, str | None]:
    """Output path for a local tool: the explicit ``output_path`` (may overwrite; never the input
    itself) or a collision-free default next to the input. Returns (path, note)."""
    if output_path:
        dest = resolve_local_path(output_path)
        if dest.resolve() == src.resolve():
            raise ToolFailure("output_path must differ from the input file")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest, None
    return _default_output(src, suffix)


@tool_entry
async def svg_inspect(svg_path: SvgPath) -> dict[str, Any]:
    """Inspect an SVG (local): well-formedness, size/viewBox, element and path counts, palette, layers,
    text elements and fonts, embedded rasters, approximate complexity, and a list of common problems
    (missing viewBox, scripts, external refs, broken references, duplicate ids, editor cruft, ...)."""
    src = _svg_file(svg_path)
    data = await anyio.to_thread.run_sync(src.read_bytes)
    info = await anyio.to_thread.run_sync(inspect, data)
    ok = info.get("well_formed", False)
    payload = _payload(path=str(src), **{k: v for k, v in info.items() if k != "problems"})
    payload["problems"] = info.get("problems", [])
    if not ok:
        raise ToolFailure(info.get("error") or "not a well-formed SVG", path=str(src), problems=payload["problems"])
    return payload


@tool_entry
async def svg_render(
    svg_path: SvgPath,
    width: Annotated[int | None, Field(ge=8, le=8192, description="Output width in px (height follows the aspect ratio). Default: the SVG's own size.")] = None,
    background: Annotated[str | None, Field(description="Background colour (e.g. 'white', '#f0f0f0'); default transparent.")] = None,
    output_path: Annotated[str | None, Field(description="PNG path; default <name>.preview.png next to the SVG.")] = None,
) -> dict[str, Any]:
    """Render an SVG to a PNG preview with resvg (local; text, gradients, transforms, masks, filters).

    Use it to look at vectors: Read the returned PNG path to view it.
    """
    src = _svg_file(svg_path)
    data = await anyio.to_thread.run_sync(src.read_bytes)
    load_svg(data)
    if output_path and resolve_local_path(output_path).resolve() == src.resolve():
        raise ToolFailure("output_path must differ from the input file")
    width_px, size_note = bounded_width(data, width)
    png = await anyio.to_thread.run_sync(lambda: render_svg(data, width=width_px, background=background, resources_dir=src.parent))
    dest, where = _derived(src, ".preview.png", output_path)
    dest.write_bytes(png)
    w, h = image_size(png)
    notes = [n for n in (size_note, where) if n]
    return _payload(files=[WrittenFile(dest, "image/png", len(png), w, h).as_dict()], width=w, height=h, notes=notes)


@tool_entry
async def svg_layers(svg_path: SvgPath) -> dict[str, Any]:
    """List an SVG's top-level layers: id, label, visibility, element count and palette.

    Layers are <g inkscape:groupmode="layer"> groups (Inkscape), or every top-level <g> when the file
    has no layer markers (how Illustrator imports SVG). Loose top-level elements are reported too.
    """
    src = _svg_file(svg_path)
    root = load_svg(await anyio.to_thread.run_sync(src.read_bytes))
    info = describe_layers(root)
    notes = []
    if info["mode"] == "none":
        notes.append("no layers: use svg_layerize to create them")
    elif info["mode"] == "groups":
        notes.append("no inkscape layer markers: top-level groups are treated as layers (svg_layerize by='group' adds the markers)")
    return _payload(path=str(src), **info, notes=notes)


@tool_entry
async def svg_layerize(
    svg_path: SvgPath,
    by: Annotated[Literal["color", "group", "mapping"], Field(description="color: one layer per paint colour; group: top-level groups become layers; mapping: your own layer assignment.")] = "group",
    mapping: Annotated[
        dict[str, list[str]] | None,
        Field(description="For by='mapping': {layer_name: [element ids or CSS-like selectors ('#logo', '.cls-1', 'text', 'g.icons path', '[fill=#ff0000]')]}; unmatched elements go to 'Other'."),
    ] = None,
    strict_z_order: Annotated[bool, Field(description="Never move an element across an overlapping element of another layer (opens an extra layer instead). false = fewer layers, appearance may change.")] = True,
    output_path: Annotated[str | None, Field(description="Where to write; default <name>.layered.svg next to the input.")] = None,
) -> dict[str, Any]:
    """Rewrite an SVG into top-level layers (<g id="layer-..." inkscape:groupmode="layer" inkscape:label="...">):
    Inkscape-native and imported as layers by Illustrator. Preserves <defs>, z-order and appearance; the
    result is re-rendered and compared with the original (`appearance`). Follow with export_pdf for a
    layered PDF."""
    src = _svg_file(svg_path)
    data = await anyio.to_thread.run_sync(src.read_bytes)
    if output_path and resolve_local_path(output_path).resolve() == src.resolve():
        raise ToolFailure("output_path must differ from the input file")
    text, report = await anyio.to_thread.run_sync(lambda: layerize(data, by=by, mapping=mapping, strict_z_order=strict_z_order))
    dest, where = _derived(src, ".layered.svg", output_path)
    dest.write_text(text, encoding="utf-8")
    appearance = await anyio.to_thread.run_sync(lambda: appearance_delta(data, text))
    warnings = [w] if (w := appearance_warning(appearance)) else []
    return _payload(
        files=[WrittenFile(dest, "image/svg+xml", len(text.encode("utf-8"))).as_dict()],
        by=by, layer_count=report["layer_count"], layers=report["layers"], z_order=report.get("z_order"),
        appearance=appearance, notes=report["notes"] + ([where] if where else []), warnings=warnings,
    )


class LayerSpec(BaseModel):
    source: str = Field(description="SVG or raster (PNG/JPEG/WebP) path, URL or data URI.")
    name: str = Field(description="Layer label.")
    opacity: float | None = Field(default=None, ge=0, le=1, description="Layer opacity 0-1.")
    visible: bool = Field(default=True, description="false = hidden layer (display:none; OFF in the PDF).")
    x: float | None = Field(default=None, description="Left edge on the canvas (default 0).")
    y: float | None = Field(default=None, description="Top edge on the canvas (default 0).")
    width: float | None = Field(default=None, description="Width on the canvas (default: SVG = canvas, raster = its pixel width; keeps aspect when only one of width/height is given).")
    height: float | None = Field(default=None, description="Height on the canvas.")


@tool_entry
async def layers_compose(
    layers: Annotated[list[LayerSpec], Field(min_length=1, description="Layers bottom-to-top: [{source, name, opacity?, visible?, x?, y?, width?, height?}].")],
    width: Annotated[float, Field(gt=0, le=100000, description="Canvas width (px / user units).")],
    height: Annotated[float, Field(gt=0, le=100000, description="Canvas height.")],
    output_path: Annotated[str | None, Field(description="Where to write; default .stack/images/<date>/composition-<time>.svg.")] = None,
) -> dict[str, Any]:
    """Compose SVG and raster sources into ONE layered SVG (first layer at the bottom).

    SVG sources keep their vectors (ids prefixed and <style> rules scoped so sources cannot clash),
    fitted into their box with their own preserveAspectRatio; raster sources are embedded as <image>
    data URIs in their own layer. Follow with export_pdf for a layered PDF.
    """
    specs = [s if isinstance(s, LayerSpec) else LayerSpec.model_validate(s) for s in layers]
    async with http.new_client() as client:
        resolved = [await resolve_input(s.source, client) for s in specs]
    comp = []
    for s, f in zip(specs, resolved, strict=True):
        if not (f.mime.startswith("image/")):
            raise InputError(f"layer {s.name!r}: {f.source} is not an image ({f.mime})")
        local = not f.source.startswith(("data:", "http://", "https://"))
        comp.append(ComposeLayer(s.name, f.data, f.mime, s.opacity, s.visible, s.x, s.y, s.width, s.height,
                                 base_dir=Path(f.source).parent if local else None))
    text, summary = await anyio.to_thread.run_sync(lambda: compose(comp, width, height))
    if output_path:
        dest = resolve_local_path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
    else:
        dest = unique_path(output_directory(None, DEFAULT_OUTPUT_DIR), f"composition-{datetime.now():%H%M%S}", ".svg")
    dest.write_text(text, encoding="utf-8")
    warnings = [f"layer {lay['label']!r}: {w}" for lay in summary for w in lay.get("warnings", [])]
    notes = [f"{len(summary)} layer(s), canvas {width:g}x{height:g}"]
    notes += [f"layer {lay['label']!r}: {n}" for lay in summary for n in lay.get("notes", [])]
    return _payload(files=[WrittenFile(dest, "image/svg+xml", len(text.encode("utf-8"))).as_dict()], layers=summary,
                    notes=notes, warnings=warnings)


@tool_entry
async def export_pdf(
    svg_path: SvgPath,
    output_path: Annotated[str | None, Field(description="PDF path; default <name>.pdf next to the SVG.")] = None,
    layered: Annotated[bool, Field(description="Every top-level SVG layer becomes a PDF Optional Content Group (toggleable in Acrobat/Illustrator).")] = True,
    page_size: Annotated[str, Field(description="'auto' (page = drawing), 'A4', 'letter' (orientation follows the drawing) or 'WxHmm' (e.g. '210x297mm'); the drawing is scaled to fit and centred.")] = "auto",
) -> dict[str, Any]:
    """Export an SVG to a vector PDF (local: svglib + reportlab + pikepdf).

    With layered=true each top-level layer is drawn in its own marked-content section bound to an
    Optional Content Group named after the layer label (hidden SVG layers start OFF). An SVG without
    layers becomes a single-layer PDF. Raster <image>s keep their alpha.
    """
    src = _svg_file(svg_path)
    data = await anyio.to_thread.run_sync(src.read_bytes)
    if output_path and resolve_local_path(output_path).resolve() == src.resolve():
        raise ToolFailure("output_path must differ from the input file")
    pdf, stats = await anyio.to_thread.run_sync(
        lambda: svg_to_pdf_layers(data, layered=layered, page_size=page_size, title=src.stem, base_dir=src.parent))
    dest, where = _derived(src, ".pdf", output_path)
    dest.write_bytes(pdf)
    notes = []
    if layered and not stats["layers"]:
        notes.append("the SVG has no top-level layers: wrote a single-layer PDF (svg_layerize first for layers)")
    if stats.get("layer_names"):
        notes.append(f"PDF layers (OCGs): {', '.join(stats['layer_names'])}")
    if where:
        notes.append(where)
    warnings = stats.pop("warnings", [])
    return _payload(files=[{"path": str(dest), "mime": "application/pdf", "bytes": len(pdf)}], **stats, notes=notes,
                    warnings=warnings)


# --- registry ------------------------------------------------------------------------------------

OP_TOOLS: tuple[Callable[..., Any], ...] = (
    image_generate,
    image_generate_with_references,
    image_edit,
    image_segment,
    image_generate_transparent,
    image_remove_background,
    image_upscale,
    vector_generate,
    image_vectorize,
)
LOCAL_TOOLS: tuple[Callable[..., Any], ...] = (
    image_ops_status,
    image_info,
    mask_convert,
    svg_optimize,
    svg_inspect,
    svg_render,
    svg_layers,
    svg_layerize,
    layers_compose,
    export_pdf,
)
CONDITIONAL_TOOLS: tuple[Callable[..., Any], ...] = (svg_transform,)
LOCAL_TOOL_NAMES = frozenset(f.__name__ for f in LOCAL_TOOLS)
READ_ONLY_TOOLS = frozenset({"image_ops_status", "image_info", "svg_inspect", "svg_layers"})
ALL_TOOLS = OP_TOOLS + LOCAL_TOOLS + CONDITIONAL_TOOLS


def svg_transform_enabled() -> bool:
    """svg_transform is listed only when VECTOR_MANIPULATION is configured with an external model."""
    cfg = load_op("VECTOR_MANIPULATION")
    return cfg.configured and not cfg.is_claude


def hidden_tools() -> frozenset[str]:
    """Op tools the server does not list right now.

    An operation's tool is listed only while the operation is configured: IMAGE_<OP>_URL, _KEY and
    _MODEL all set (or IMAGE_<OP>_API=local for TRACE / UPSCALE). svg_transform is hidden while
    vector manipulation is 'claude'. image_ops_status and the local tools are always listed. A
    client that calls a hidden tool from a stale list still gets the 'not configured' error.
    """
    hidden: set[str] = set()
    for op, cfg in load_all().items():
        if (op == "VECTOR_MANIPULATION" and cfg.is_claude) or not cfg.configured:
            hidden.update(OP_SPECS[op].tools)
    return frozenset(hidden)


# every tool named in the op table is implemented (and nothing else is an op tool)
assert {f.__name__ for f in OP_TOOLS + CONDITIONAL_TOOLS} == {t for op in OPS for t in OP_SPECS[op].tools}
