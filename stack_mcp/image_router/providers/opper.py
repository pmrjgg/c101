"""Opper image adapter (``IMAGE_<OP>_URL=https://api.opper.ai``).

Research notes (2026-10-19, scratchpad/opper_openrouter.json):

* ``POST {URL}/v3/images``, ``Authorization: Bearer KEY`` (runtime keys start ``op-``);
  Opper has no OpenAI-compatible images route (``/v3/compat/images/generations`` 404s) and the
  Python SDK's ``generate_image`` goes through the function API, so this is plain httpx;
* body ``model, prompt (required), n (<=4), size (WxH) | aspect_ratio, resolution, quality,
  response_format (b64_json | url), store, async, image (string), mask (string),
  reference_images (strings)`` - strings are http(s) URLs, data URIs or ``file_<id>``;
  provider pass-through goes in ``parameters`` (e.g. ``{"background": "transparent",
  "output_format": "png"}`` for GPT Image models);
* response ``{id, model, data: [{b64_json, mime_type, revised_prompt?, url?}], usage}`` - read
  ``mime_type`` (Gemini returns JPEG);
* sync deadline 3 min (504). With ``async: true`` -> 202 ``{id, status_url}``; poll
  ``GET {URL}/v3/artifacts/{id}/status`` until ``status`` is completed|failed, then download ``url``;
* ``GET {URL}/v3/images/models`` (public) lists per-model sizes / aspect ratios / qualities /
  passthrough parameters: used here to normalise size vs aspect_ratio and to check that
  ``background=transparent`` is allowed before paying for a call;
* masks: supported by fal/ideogram-v4.5-edit (black = edit) and GPT Image edits upstream (alpha
  PNG, transparent = edit); the convention is chosen from the model tag, overridable with
  ``IMAGE_EDIT_PARAMS={"mask_convention": "white-edit|black-edit|alpha-transparent"}``;
* no background-removal / upscale / segmentation / tracing models: those ops are approximated
  (regeneration, or a vision chat model via ``/v3/compat/chat/completions``).
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin, urlparse

from .. import http
from ..imaging import convert_canonical, ensure_png, image_size, to_png_bytes
from ..io import OutputBlob
from . import geometry
from .base import (
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

ALL_OPS = frozenset({"GEN", "REF", "EDIT", "TRANSPARENT", "SEGMENT", "BG_REMOVAL", "UPSCALE", "VECTOR", "TRACE", "VECTOR_MANIPULATION"})
# Tasks whose output must keep the source framing: without size/aspect_ratio from the caller,
# the output geometry is derived from the source (a model's default is often square).
GEOMETRY_TASKS = frozenset({"edit", "remove_background", "upscale", "mask", "trace"})
CATALOG_TTL = 3600.0
POLL_TIMEOUT = float(os.environ.get("IMAGE_OPPER_POLL_TIMEOUT", "900"))
POLL_INTERVAL = 2.0
_catalog_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def clear_catalog_cache() -> None:
    _catalog_cache.clear()


def mask_convention_for(model: str | None, override: str | None = None) -> str:
    if override:
        return override
    m = (model or "").lower()
    if "gpt-image" in m or m.startswith("openai/"):
        return "alpha-transparent"
    if "ideogram" in m:
        return "black-edit"
    return "white-edit"


# --- catalog parsing (defensive: only documented field names are relied on loosely) -------------


def _catalog_models(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, Mapping)]
    if isinstance(payload, Mapping):
        for k in ("data", "models", "items", "results"):
            if isinstance(payload.get(k), list):
                return [m for m in payload[k] if isinstance(m, Mapping)]
    return []


def _entry_for(models: list[dict[str, Any]], tag: str) -> dict[str, Any] | None:
    for m in models:
        names = {str(m.get(k)) for k in ("id", "name", "model", "slug", "identifier") if m.get(k)}
        prov, name = m.get("provider"), m.get("name") or m.get("model")
        if prov and name:
            names.add(f"{prov}/{name}")
        if tag in names:
            return m
    return None


def image_params(entry: Mapping[str, Any] | None) -> dict[str, Any]:
    if not entry:
        return {}
    params = entry.get("params")
    if isinstance(params, Mapping) and isinstance(params.get("image"), Mapping):
        return dict(params["image"])
    for k in ("image_params", "image"):
        if isinstance(entry.get(k), Mapping):
            return dict(entry[k])
    return {}


def _list(img: Mapping[str, Any], *keys: str) -> list[str]:
    for k in keys:
        v = img.get(k)
        if isinstance(v, list):
            return [str(x) for x in v]
    return []


def parameter_enum(img: Mapping[str, Any], name: str) -> list[str] | None:
    """Enum of a passthrough parameter (list of {name, enum} or {name: {enum}})."""
    params = img.get("parameters")
    spec: Any = None
    if isinstance(params, list):
        spec = next((p for p in params if isinstance(p, Mapping) and p.get("name") == name), None)
    elif isinstance(params, Mapping):
        spec = params.get(name)
    if isinstance(spec, Mapping):
        enum = spec.get("enum") or spec.get("values")
        if isinstance(enum, list):
            return [str(x) for x in enum]
    return None


def declared_parameters(img: Mapping[str, Any]) -> set[str]:
    """Names of the passthrough ``parameters`` a catalog entry declares (empty when none)."""
    params = img.get("parameters")
    if isinstance(params, list):
        return {str(p["name"]) for p in params if isinstance(p, Mapping) and p.get("name")}
    if isinstance(params, Mapping):
        return {str(k) for k in params}
    return set()


def _ci(options: list[str], value: str) -> str | None:
    """The option equal to ``value`` ignoring case (as the catalog spells it)."""
    return next((o for o in options if o.lower() == value.strip().lower()), None)


def normalise_dimensions(
    size: str | None,
    aspect_ratio: str | None,
    img: Mapping[str, Any],
    *,
    source: tuple[int, int] | None = None,
    target: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """size / aspect_ratio / resolution fields for one model, from its catalog ``params.image``.

    * ``size_constraints`` (GPT Image 2/2.5): any explicit WxH meeting them is sent as is; one
      that does not is snapped (multiple_of, edges, pixels) keeping its ratio; an aspect ratio
      becomes a WxH of exactly that ratio (16:9 -> 1536x864); a tier becomes a WxH of that long
      edge.
    * presets (``sizes``): explicit sizes must be listed, else the nearest preset by ratio;
      'auto' is a size value when listed.
    * ``aspect_ratios``: sent as is when listed, else the nearest one.
    * tiers (1K/2K/4K) map to ``resolution`` only when listed there, to ``quality`` when the
      model expresses them as a quality (Gemini '4k'; returned under ``fields['quality']`` for
      the caller to reconcile), to a size by long edge when the model takes sizes, else they
      are dropped with a note.
    * With neither size nor aspect_ratio, ``source`` (an edit-type input, W x H) or ``target``
      (an upscale) sets the output geometry, so the result keeps the source framing.

    A field is never sent as null: when nothing fits, it is left out and a note says why.
    With no catalog information at all (catalog unavailable, or an entry without
    ``params.image``) the values are sent as given (the caller notes that they are unvalidated).
    """
    fields: dict[str, Any] = {}
    notes: list[str] = []
    if not img:
        explicit_px = geometry.parse_size(size) if size else None
        if size and size.strip():
            if explicit_px:
                fields["size"] = f"{explicit_px[0]}x{explicit_px[1]}"
            elif size.strip().lower() == "auto":
                fields["size"] = "auto"
            else:
                fields["resolution"] = size.strip().lower()
        if aspect_ratio:
            if explicit_px:
                notes.append("explicit size wins; aspect_ratio dropped")
            else:
                fields["aspect_ratio"] = aspect_ratio
        return fields, notes
    sizes = _list(img, "sizes", "allowed_sizes", "size")
    ratios = _list(img, "aspect_ratios", "allowed_aspect_ratios", "aspect_ratio")
    resolutions = _list(img, "resolutions", "allowed_resolutions", "resolution")
    qualities = _list(img, "qualities", "quality")
    limits = geometry.SizeConstraints.from_mapping(img.get("size_constraints"))
    pixel_presets = geometry.presets(sizes)
    auto_size = _ci(sizes, "auto")
    auto_ratio = _ci(ratios, "auto")
    default = geometry.parse_size(str(img.get("default") or ""))
    default_area = float(default[0] * default[1]) if default else 1024.0 * 1024.0

    def base_long_edge(r: float) -> float:
        """Long edge of the model's ordinary output for ratio r (nearest normal-size preset)."""
        normal = [f"{w}x{h}" for w, h in pixel_presets if w * h <= 2 * default_area]
        choice = geometry.nearest_preset(normal, r, area=default_area)
        if choice:
            return float(max(geometry.parse_size(choice) or (1024, 1024)))
        edge = math.sqrt(default_area)
        return edge * (1.5 if abs(math.log(r)) > 0.05 else 1.0)

    def constrained(w: float, h: float, terms: tuple[int, int] | None) -> str:
        assert limits is not None
        W, H = limits.snap(w, h, terms)
        return f"{W}x{H}"

    def from_ratios(r: float, label: str, *, exact_or_auto: bool = False) -> None:
        """aspect_ratio field for ratio r on an aspect-ratio model."""
        choice = geometry.nearest_ratio(ratios, r)
        if choice is None:
            return
        if exact_or_auto and auto_ratio and geometry.ratio_distance(geometry.parse_ratio(choice) or r, r) > 0.02:
            choice = auto_ratio
        fields["aspect_ratio"] = choice
        notes.append(f"{label}: aspect_ratio {choice}")

    explicit = geometry.parse_size(size) if size else None
    wants_auto = bool(size) and size.strip().lower() == "auto"
    tier_edge = geometry.tier_long_edge(size) if size and not explicit else None

    # --- an explicit size ----------------------------------------------------------------
    if wants_auto:
        if auto_size:
            fields["size"] = auto_size
        elif auto_ratio:
            fields["aspect_ratio"] = auto_ratio
        else:
            notes.append("size 'auto' is not offered by the model; its default size is used")
        if aspect_ratio:
            notes.append(f"size 'auto' given: aspect_ratio {aspect_ratio} dropped")
        return fields, notes
    if explicit:
        w, h = explicit
        s = f"{w}x{h}"
        if _ci(sizes, s) or (limits and limits.meets(w, h)):
            fields["size"] = s
        elif limits:
            fields["size"] = constrained(w, h, geometry.terms_of(w, h))
            notes.append(f"size {s} does not meet the model's size constraints ({'; '.join(limits.problems(w, h))}): "
                         f"sent as {fields['size']}")
        elif pixel_presets:
            choice = geometry.nearest_preset(sizes, w / h, area=float(w * h))
            fields["size"] = choice
            notes.append(f"size {s} is not offered by the model; using the nearest allowed size {choice}")
        elif ratios:
            from_ratios(w / h, f"model takes aspect ratios, not pixel sizes: size {s} sent as")
        elif auto_size:
            fields["size"] = auto_size
            notes.append(f"the model only takes size '{auto_size}': size {s} dropped")
        else:
            fields["size"] = s
            notes.append(f"the model's catalog lists no sizes: size {s} sent unvalidated")
        if aspect_ratio:
            notes.append("explicit size wins; aspect_ratio dropped")
        return fields, notes

    r_req = geometry.parse_ratio(aspect_ratio) if aspect_ratio else None
    terms_req = geometry.ratio_terms(aspect_ratio) if aspect_ratio else None

    # --- a resolution tier (1K / 2K / 4K ...) -------------------------------------------------
    if size and tier_edge is None:
        notes.append(f"size {size!r} not understood (use WxH, 1K/2K/4K or auto); dropped")
    elif tier_edge is not None:
        tier = size.strip()
        if match := _ci(resolutions, tier):
            fields["resolution"] = match
        elif resolutions:
            scored = [(abs(math.log((geometry.tier_long_edge(x) or tier_edge) / tier_edge)), x) for x in resolutions]
            choice = min(scored)[1]
            fields["resolution"] = choice
            notes.append(f"resolution {tier} is not offered (the model lists {resolutions}); using {choice}")
        elif match := _ci(qualities, tier):
            fields["quality"] = match
            notes.append(f"{tier} is a quality tier on this model: sent as quality {match!r}")
        elif limits:
            r = r_req or 1.0
            fields["size"] = constrained(*geometry.size_for_ratio(r, tier_edge), terms_req or (1, 1))
            notes.append(f"{tier} sent as size {fields['size']}")
        elif pixel_presets:
            r = r_req or 1.0
            choice = geometry.nearest_preset(sizes, r, long_edge=tier_edge)
            fields["size"] = choice
            notes.append(f"{tier} sent as the preset size {choice} (the model has no resolution tiers)")
        else:
            notes.append(f"the model offers no {tier} option (no resolutions or sizes in its catalog); dropped")
        if "size" in fields:
            if aspect_ratio:
                notes.append(f"aspect_ratio {aspect_ratio} applied through the size")
            return fields, notes

    # --- an aspect ratio -------------------------------------------------------------------------
    if aspect_ratio:
        if aspect_ratio.strip().lower() == "auto":
            if auto_ratio:
                fields["aspect_ratio"] = auto_ratio
            elif auto_size and "resolution" not in fields:
                fields["size"] = auto_size
            else:
                notes.append("aspect_ratio 'auto' is not offered by the model; its default is used")
            return fields, notes
        if r_req is None:
            if _ci(ratios, aspect_ratio):
                fields["aspect_ratio"] = _ci(ratios, aspect_ratio)
            else:
                notes.append(f"aspect_ratio {aspect_ratio!r} not understood (use W:H); dropped")
            return fields, notes
        if _ci(ratios, aspect_ratio):
            fields["aspect_ratio"] = _ci(ratios, aspect_ratio)
        elif ratios:
            choice = geometry.nearest_ratio(ratios, r_req)
            fields["aspect_ratio"] = choice
            notes.append(f"aspect_ratio {aspect_ratio} not offered; using the nearest {choice}")
        elif "resolution" in fields or "quality" in fields:
            notes.append(f"the model takes no aspect ratio with a resolution tier: aspect_ratio {aspect_ratio} dropped")
        elif limits:
            fields["size"] = constrained(*geometry.size_for_ratio(r_req, base_long_edge(r_req)), terms_req)
            notes.append(f"model takes pixel sizes: aspect_ratio {aspect_ratio} sent as size {fields['size']}")
        elif pixel_presets:
            choice = geometry.nearest_preset(sizes, r_req, area=default_area)
            fields["size"] = choice
            notes.append(f"model takes pixel sizes: aspect_ratio {aspect_ratio} sent as size {choice}")
        elif auto_size:
            notes.append(f"the model only takes size '{auto_size}': aspect_ratio {aspect_ratio} dropped")
        else:
            fields["aspect_ratio"] = aspect_ratio
            notes.append(f"the model's catalog lists no aspect ratios or sizes: aspect_ratio {aspect_ratio} sent unvalidated")
        return fields, notes
    if fields:
        return fields, notes

    # --- no size or aspect: keep the source framing (edit-type tasks) -----------------------------
    if target:
        tw, th = target
        r = tw / th
        if limits:
            fields["size"] = constrained(tw, th, geometry.terms_of(tw, th))
            notes.append(f"output size {fields['size']} requested for the {tw}x{th} target")
        elif resolutions:
            scored = [(abs(math.log((geometry.tier_long_edge(x) or 1024) / max(tw, th))), x) for x in resolutions]
            fields["resolution"] = min(scored)[1]
            if ratios:
                from_ratios(r, "source framing", exact_or_auto=True)
        elif (q4k := _ci(qualities, "4k")) and max(tw, th) > 2048:
            fields["quality"] = q4k
            notes.append(f"quality {q4k!r} requested for the {tw}x{th} target")
            if ratios:
                from_ratios(r, "source framing", exact_or_auto=True)
        elif pixel_presets:
            fields["size"] = geometry.nearest_preset(sizes, r, long_edge=max(tw, th))
            notes.append(f"output size {fields['size']} (preset nearest the {tw}x{th} target)")
        elif auto_size:
            fields["size"] = auto_size
        elif ratios:
            from_ratios(r, "source framing", exact_or_auto=True)
        return fields, notes
    if source:
        sw, sh = source
        r = sw / sh
        if limits:
            fields["size"] = constrained(*geometry.size_for_ratio(r, base_long_edge(r)), geometry.terms_of(sw, sh))
            notes.append(f"output size {fields['size']} keeps the {sw}x{sh} source's aspect ratio")
        elif auto_size:
            fields["size"] = auto_size
            notes.append(f"size '{auto_size}' so the model keeps the source framing")
        elif pixel_presets:
            fields["size"] = geometry.nearest_preset(sizes, r, area=default_area)
            notes.append(f"output size {fields['size']} (preset nearest the {sw}x{sh} source's aspect ratio)")
        elif ratios:
            from_ratios(r, f"keeps the {sw}x{sh} source framing", exact_or_auto=True)
    return fields, notes


class OpperAdapter(Adapter):
    name = "opper"
    supports = ALL_OPS
    default_strategy = {"SEGMENT": "render", "VECTOR": "image", "TRACE": "chat"}

    # --- URLs ------------------------------------------------------------------------------
    def root(self) -> str:
        base = self.cfg.base_url
        for suffix in ("/v3/compat", "/v3"):
            if base.endswith(suffix):
                return base[: -len(suffix)]
        return base

    def images_url(self) -> str:
        return f"{self.root()}/v3/images"

    def chat_url(self) -> str:
        return f"{self.root()}/v3/compat/chat/completions"

    def chat_path(self) -> str:
        return "/v3/compat/chat/completions"

    def headers(self) -> dict[str, str]:
        return self.auth_headers()

    def status_hint(self, status: int) -> str:
        if status == 504:
            return (f" - Opper's synchronous deadline is 3 minutes; set IMAGE_{self.cfg.op}_PARAMS="
                    '{"async": true} for slow models')
        return super().status_hint(status)

    # --- catalog ---------------------------------------------------------------------------
    async def catalog_entry(self) -> dict[str, Any] | None:
        root = self.root()
        cached = _catalog_cache.get(root)
        if cached is None or time.monotonic() - cached[0] > CATALOG_TTL:
            try:
                resp = await http.request(self.client, "GET", f"{root}/v3/images/models", params={"limit": 500}, retries=1)
                models = _catalog_models(resp.json())
            except Exception:
                models = []
            if not models:
                return None  # do not cache failures
            _catalog_cache[root] = (time.monotonic(), models)
            cached = _catalog_cache[root]
        return _entry_for(cached[1], self.cfg.model or "")

    # --- request body ----------------------------------------------------------------------
    async def build_body(self, job: ImageJob) -> tuple[dict[str, Any], list[str]]:
        """The /v3/images body, validated against the model's catalog entry where one is listed.

        Opper forwards ``parameters`` verbatim and the provider validates them, and rejects
        normalised fields a model does not declare (quality tiers, sizes), so everything that
        can be checked against ``GET /v3/images/models`` is checked before paying: unknown
        values are dropped or adjusted with a note; impossible requests raise Unsupported.
        Only when the catalog is unavailable are values sent unvalidated (with a note).
        """
        notes: list[str] = []
        prompt = job.prompt or ""
        body: dict[str, Any] = {"model": self.cfg.model}
        parameters: dict[str, Any] = {}
        fmt = (job.output_format or "").lower() or None
        geometry_task = job.task in GEOMETRY_TASKS and not (job.size or job.aspect_ratio)
        needs_catalog = bool(
            job.size or job.aspect_ratio or job.quality or job.seed is not None or fmt or geometry_task
            or job.task in ("transparent", "remove_background", "vector")
        )
        entry = await self.catalog_entry() if needs_catalog else None
        img = image_params(entry)
        declared = declared_parameters(img) if entry is not None else None
        if needs_catalog and entry is None:
            notes.append("Opper model catalog unavailable or model not listed; size/aspect/quality/parameters sent unvalidated")

        def passthrough(name: str, value: Any) -> bool:
            """parameters[name] = value when the model declares it (or the catalog is unavailable)."""
            if declared is None:
                parameters[name] = value
                return True
            if name in declared:
                parameters[name] = value
                return True
            notes.append(f"{name} dropped: the model declares no '{name}' parameter (Opper forwards parameters verbatim)")
            return False

        match job.task:
            case "generate":
                pass
            case "references":
                body["reference_images"] = [input_ref(f) for f in job.references]
            case "edit":
                assert job.image is not None
                if job.mask is not None:
                    conv = mask_convention_for(self.cfg.model, self.cfg.directives.get("mask_convention"))
                    body["image"] = png_data_uri(ensure_png(job.image.data)) if conv == "alpha-transparent" else input_ref(job.image)
                    body["mask"] = png_data_uri(to_png_bytes(convert_canonical(job.mask, conv)))
                    notes.append(f"mask sent as {conv} (Opper does not document per-model mask conventions)")
                else:
                    body["image"] = input_ref(job.image)
                if job.references:
                    body["reference_images"] = [input_ref(f) for f in job.references]
            case "transparent" | "remove_background":
                allowed = parameter_enum(img, "background")
                if entry is not None and declared is not None:
                    if "background" not in declared:
                        raise Unsupported(
                            f"{self.where()}: the model declares no background option, so it cannot return a "
                            "transparent background; set IMAGE_RGBA_MODEL to a model with transparent output "
                            "(e.g. openai/gpt-image-2.5-flare)"
                        )
                    if allowed is not None and "transparent" not in allowed:
                        raise Unsupported(
                            f"{self.where()}: the model's background options are {allowed}, not 'transparent'; "
                            "set IMAGE_RGBA_MODEL to a model with transparent output (e.g. openai/gpt-image-2.5-flare)"
                        )
                    if allowed is None:
                        notes.append("background=transparent sent unvalidated (the model's background parameter lists no values)")
                parameters["background"] = "transparent"
                formats = parameter_enum(img, "output_format")
                if formats is not None:
                    alpha_formats = [f for f in ("png", "webp") if f in formats]
                    if not alpha_formats:
                        raise Unsupported(
                            f"{self.where()}: transparency needs png or webp output, but the model only offers {formats}"
                        )
                    fmt = fmt if fmt in alpha_formats else alpha_formats[0]
                else:
                    fmt = fmt if fmt in ("png", "webp") else "png"
                if job.task == "remove_background":
                    assert job.image is not None
                    body["image"] = input_ref(job.image)
                    prompt = f"{REMOVE_BG_PROMPT} {prompt}".strip()
                    notes.append("Opper has no background-removal model: the cut-out is a regeneration with background=transparent")
            case "upscale":
                assert job.image is not None
                body["image"] = input_ref(job.image)
                prompt = f"{UPSCALE_PROMPT} {prompt}".strip()
                notes.append(
                    "Opper has no upscaler: the image is regenerated at the size the model allows nearest the target; "
                    "IMAGE_UPSCALE_PARAMS can set model-specific size/quality"
                )
            case "mask":
                assert job.image is not None
                body["image"] = input_ref(job.image)
                prompt = MASK_PROMPT.format(subject=job.prompt)
                notes.append("mask rendered by the image model (strategy 'render') and normalised locally")
            case "vector":
                style_param = declared is not None and "style" in declared
                if style_param:
                    # Recraft: vector output is a style (vector_illustration[/substyle]), not a prompt hint
                    enum = parameter_enum(img, "style")
                    chosen = job.style if job.style and job.style.lower().startswith("vector") else None
                    if chosen and enum and chosen not in enum:
                        chosen = None
                    if not chosen:
                        chosen = ("vector_illustration" if not enum or "vector_illustration" in enum
                                  else next((v for v in enum if v.startswith("vector")), None))
                    if chosen:
                        parameters["style"] = chosen
                        notes.append(f"vector output requested with parameters.style={chosen} (vector styles are billed "
                                     "at a higher rate on Recraft, e.g. $0.08 instead of $0.04 per image)")
                    if job.style and not job.style.lower().startswith("vector"):
                        prompt = f"{prompt}\nStyle: {job.style}"
                elif job.style:
                    prompt = f"{prompt}\nStyle: {job.style}"
            case "trace":
                assert job.image is not None
                body["image"] = input_ref(job.image)
                prompt = f"{TRACE_PROMPT} {prompt}".strip()
            case _:
                raise Unsupported(f"opper adapter has no images mapping for task {job.task}")

        body["prompt"] = prompt
        source = target = None
        if geometry_task and job.image is not None:
            if job.task == "upscale" and job.target_size:
                target = job.target_size
            else:
                try:
                    source = image_size(job.image.data)
                except Exception:
                    source = None
        qualities = _list(img, "qualities", "quality")
        dims, dim_notes = normalise_dimensions(job.size, job.aspect_ratio, img, source=source, target=target)
        tier_quality = dims.pop("quality", None)
        body.update(dims)
        notes += dim_notes
        quality = job.quality
        if tier_quality and quality:
            notes.append(f"quality {quality!r} given: the {job.size or 'target'} tier (quality {tier_quality!r}) dropped")
        elif tier_quality:
            quality = tier_quality
        if quality:
            if entry is None:
                body["quality"] = quality.lower()
            elif not qualities:
                notes.append(f"quality {quality!r} dropped: the model declares no quality tiers")
            elif match := _ci(qualities, quality):
                body["quality"] = match
            else:
                notes.append(f"quality {quality} not offered by the model {qualities}; dropped")
        if job.n and job.n > 1:
            body["n"] = min(job.n, 4)
        if job.seed is not None and passthrough("seed", job.seed) and declared is None:
            notes.append("seed sent unvalidated as parameters.seed (provider-specific on Opper)")
        if fmt and job.task not in ("vector", "trace"):
            formats = parameter_enum(img, "output_format")
            if formats is not None and fmt not in formats:
                notes.append(f"output_format {fmt} not offered by the model {formats}; dropped")
            else:
                passthrough("output_format", fmt)
        body["response_format"] = "b64_json"
        if parameters:
            body["parameters"] = parameters
        return self.merged(body, job), notes

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
            raise Unsupported(f"IMAGE_{job.op}_PARAMS strategy {strategy!r} is not known to the opper adapter")

        body, notes = await self.build_body(job)
        # https://docs.opper.ai/v3-api-reference/images/create-image
        resp = await self.call("POST", self.images_url(), json=body)
        payload = self.json_body(resp)
        if resp.status_code == 202:
            outputs = [await self.poll(payload)]
            notes.append("async job polled via /v3/artifacts/{id}/status")
        else:
            outputs = await self.parse_image_data(payload, mime_key="mime_type")
        if job.task in ("vector", "trace"):
            bad = [o.mime for o in outputs if (o.mime or "") != "image/svg+xml"]
            if bad:
                raise AdapterError(
                    f"{self.where()} returned {bad[0]} instead of SVG; Opper vector output is model-specific - "
                    f"set IMAGE_{job.op}_PARAMS={{\"strategy\": \"chat\"}} with an LLM model to have it write SVG"
                )
        return AdapterResult(outputs, "POST /v3/images", notes, summarize_body(body))

    async def poll(self, accepted: Any) -> OutputBlob:
        """202 {id, status_url} -> poll until completed|failed -> download url."""
        if not isinstance(accepted, Mapping) or not accepted.get("id"):
            raise AdapterError(f"{self.where()}: 202 without a job id: {str(accepted)[:200]}")
        job_id = str(accepted["id"])
        status_url = f"{self.root()}/v3/artifacts/{job_id}/status"
        given = accepted.get("status_url")
        if isinstance(given, str) and given:
            candidate = urljoin(self.root() + "/", given)
            if (urlparse(candidate).hostname or "").lower() == (self.cfg.host or ""):
                status_url = candidate
        deadline = time.monotonic() + POLL_TIMEOUT
        while True:
            resp = await self.call("GET", status_url)
            st = self.json_body(resp)
            status = str((st or {}).get("status") or "").lower()
            if status == "completed":
                url = st.get("url")
                if not url:
                    raise AdapterError(f"{self.where()}: async job completed without a url")
                blob = await self.fetch(url, auth=True)
                blob.mime = blob.mime or st.get("mime_type")
                return blob
            if status == "failed":
                raise AdapterError(f"{self.where()}: async job failed: {str(st.get('error'))[:300]}")
            if time.monotonic() > deadline:
                raise AdapterError(f"{self.where()}: async job {job_id} still {status or 'pending'} after {POLL_TIMEOUT:.0f}s")
            await http.sleep(POLL_INTERVAL)
