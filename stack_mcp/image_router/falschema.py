"""Endpoint input schemas and canonical-parameter mapping.

fal publishes one OpenAPI document per endpoint
(``https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>``). We fetch
it once (memory cache + ``<project>/.stack/cache/fal-schemas/``), find the POST
request-body schema for the endpoint and map the router's canonical params
onto whatever names that endpoint actually uses. Canonical params the schema
lacks are dropped and reported as ignored; caller ``params`` are merged last,
unfiltered. Replicate model schemas (``latest_version.openapi_schema``) are
mapped the same way.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import http
from .config import project_dir

SCHEMA_TTL_SECONDS = 7 * 24 * 3600
FAILURE_COOLDOWN_SECONDS = 300.0  # a failed lookup is retried after this long
_memory: dict[str, dict[str, Any] | None] = {}
_failed_at: dict[str, float] = {}


# --- fetching ------------------------------------------------------------------------


def cache_dir() -> Path:
    return project_dir() / ".stack" / "cache" / "fal-schemas"


def _cache_file(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:120]
    digest = hashlib.sha1(key.encode()).hexdigest()[:8]
    return cache_dir() / f"{safe}-{digest}.json"


def clear_memory_cache() -> None:
    _memory.clear()
    _failed_at.clear()


def _cached(key: str) -> tuple[bool, dict[str, Any] | None]:
    if key in _memory:
        return True, _memory[key]
    if key in _failed_at and time.monotonic() - _failed_at[key] < FAILURE_COOLDOWN_SECONDS:
        return True, None
    return False, None


def _read_disk(key: str) -> dict[str, Any] | None:
    path = _cache_file(key)
    try:
        if time.time() - path.stat().st_mtime > SCHEMA_TTL_SECONDS:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_disk(key: str, doc: Mapping[str, Any]) -> None:
    try:
        path = _cache_file(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
    except OSError as exc:
        print(f"image-router: schema cache write failed: {exc}", file=sys.stderr)


def resolve_ref(doc: Mapping[str, Any], node: Any, _seen: frozenset[str] = frozenset()) -> Any:
    """Follow a local ``#/a/b`` $ref (one level, cycle-safe)."""
    if isinstance(node, Mapping) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        if not ref.startswith("#/") or ref in _seen:
            return node
        target: Any = doc
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, Mapping) or part not in target:
                return node
            target = target[part]
        return resolve_ref(doc, target, _seen | {ref})
    return node


def input_schema_from_openapi(doc: Mapping[str, Any], endpoint_id: str) -> dict[str, Any] | None:
    """Locate the POST request-body schema for ``endpoint_id`` (queue submit path)."""
    paths = doc.get("paths") or {}
    candidates = [f"/{endpoint_id.strip('/')}"]
    # otherwise: any POST whose path does not contain /requests/
    candidates += [p for p in paths if p not in candidates and "/requests/" not in p]
    for p in candidates:
        op = (paths.get(p) or {}).get("post")
        if not op:
            continue
        body = resolve_ref(doc, op.get("requestBody") or {})
        content = (body.get("content") or {}) if isinstance(body, Mapping) else {}
        media = content.get("application/json") or next(iter(content.values()), None)
        if not media:
            continue
        schema = resolve_ref(doc, media.get("schema") or {})
        if isinstance(schema, Mapping):
            return _inline(doc, schema)
    return None


def _inline(doc: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the object schema with each property's top-level $ref/allOf resolved."""
    out = dict(schema)
    if "allOf" in out and "properties" not in out:
        merged: dict[str, Any] = {"properties": {}, "required": []}
        for part in out["allOf"]:
            part = resolve_ref(doc, part)
            merged["properties"].update(part.get("properties") or {})
            merged["required"] += part.get("required") or []
        out.update(merged)
    props: dict[str, Any] = {}
    for name, prop in (out.get("properties") or {}).items():
        prop = dict(resolve_ref(doc, prop))
        for key in ("anyOf", "oneOf", "allOf"):
            if key in prop:
                prop[key] = [resolve_ref(doc, p) for p in prop[key]]
        props[name] = prop
    out["properties"] = props
    return out


async def fetch_fal_input_schema(
    client: httpx.AsyncClient, endpoint_id: str, schema_url_prefix: str
) -> dict[str, Any] | None:
    """Input schema for a fal endpoint, or None if it cannot be fetched/parsed."""
    key = f"fal:{endpoint_id}"
    hit, cached = _cached(key)
    if hit:
        return cached
    doc = _read_disk(key)
    if doc is None:
        try:
            resp = await http.request(client, "GET", f"{schema_url_prefix}{endpoint_id}", retries=1)
            doc = resp.json()
        except Exception as exc:  # network, 404, bad JSON: fall back to common names
            print(f"image-router: schema fetch failed for {endpoint_id}: {type(exc).__name__}", file=sys.stderr)
            _failed_at[key] = time.monotonic()
            return None
        if isinstance(doc, Mapping) and doc.get("paths"):
            _write_disk(key, doc)
    schema = input_schema_from_openapi(doc, endpoint_id) if isinstance(doc, Mapping) else None
    _memory[key] = schema
    return schema


async def fetch_replicate_input_schema(
    client: httpx.AsyncClient, base: str, model: str, headers: Mapping[str, str]
) -> dict[str, Any] | None:
    """latest_version.openapi_schema.components.schemas.Input for owner/name."""
    key = f"replicate:{model}"
    hit, cached = _cached(key)
    if hit:
        return cached
    try:
        # https://replicate.com/docs/reference/http#models.get
        resp = await http.request(client, "GET", f"{base}/models/{model}", headers=dict(headers), retries=1)
        doc = resp.json()
        openapi = ((doc.get("latest_version") or {}).get("openapi_schema")) or {}
        schema = resolve_ref(openapi, ((openapi.get("components") or {}).get("schemas") or {}).get("Input"))
        schema = _inline(openapi, schema) if isinstance(schema, Mapping) else None
    except Exception as exc:
        print(f"image-router: replicate schema fetch failed for {model}: {type(exc).__name__}", file=sys.stderr)
        _failed_at[key] = time.monotonic()
        return None
    _memory[key] = schema
    return schema


# --- mapping ---------------------------------------------------------------------------


@dataclass(slots=True)
class Canonical:
    """Provider-neutral request. URLs/data URIs are already strings here."""

    prompt: str | None = None
    image: str | None = None  # source image (edits, bg removal, upscale, masks)
    references: list[str] = field(default_factory=list)
    mask: str | None = None
    aspect_ratio: str | None = None
    size: str | None = None
    n: int | None = None
    seed: int | None = None
    transparent_background: bool = False
    output_format: str | None = None
    quality: str | None = None
    scale: float | None = None
    mask_only: bool = False  # segmentation endpoints: ask for the bare mask


@dataclass(slots=True)
class Mapped:
    payload: dict[str, Any]
    ignored: list[str]
    notes: list[str]


# Candidate names per canonical param, in priority order (spec + observed fal schemas).
NAMES = {
    "references": ("image_urls", "image_url", "reference_image_urls", "input_references"),
    "image": ("image_url", "image_urls"),
    "mask": ("mask_url", "mask_image_url"),
    "size": ("image_size", "resolution", "size"),
    "n": ("num_images", "max_images", "n"),
    "scale": ("upscale_factor", "scale", "upscaling_factor"),
}
REPLICATE_NAMES = {
    "references": ("image_input", "input_images", "reference_images", "image_urls", "images"),
    "image": ("image", "input_image", "image_url", "image_input"),
    "mask": ("mask", "mask_image", "mask_url"),
    "size": ("size", "resolution", "image_size"),
    "n": ("num_outputs", "num_images", "max_images", "n"),
    "scale": ("scale", "upscale_factor", "scale_factor"),
}


def _is_array(prop: Mapping[str, Any]) -> bool:
    if prop.get("type") == "array":
        return True
    return any(isinstance(p, Mapping) and p.get("type") == "array" for p in prop.get("anyOf") or ())


def _enum_values(prop: Mapping[str, Any]) -> list[Any] | None:
    values: list[Any] = list(prop.get("enum") or [])
    for p in prop.get("anyOf") or prop.get("oneOf") or ():
        if isinstance(p, Mapping):
            values += list(p.get("enum") or [])
            if p.get("type") in ("string", "integer", "number") and not p.get("enum"):
                return None  # free-form alternative accepted
    if prop.get("type") in ("string", "integer", "number") and not prop.get("enum") and not values:
        return None
    return values or None


def _accepts_wh_object(prop: Mapping[str, Any]) -> bool:
    for p in [prop, *(prop.get("anyOf") or ()), *(prop.get("oneOf") or ())]:
        if isinstance(p, Mapping) and {"width", "height"} <= set((p.get("properties") or {}).keys()):
            return True
    return False


_WH_RE = re.compile(r"^\s*(\d{2,5})\s*[x×*]\s*(\d{2,5})\s*$", re.I)


def coerce(prop: Mapping[str, Any], value: Any) -> tuple[bool, Any]:
    """Fit ``value`` to ``prop``: enum (case-insensitive), WxH -> {width,height}."""
    if isinstance(value, str) and (m := _WH_RE.match(value)) and _accepts_wh_object(prop):
        enum = _enum_values(prop) or []
        if value not in enum:
            return True, {"width": int(m.group(1)), "height": int(m.group(2))}
    enum = _enum_values(prop)
    if enum is None or value in enum:
        return True, value
    if isinstance(value, str):
        for e in enum:
            if isinstance(e, str) and e.lower() == value.lower():
                return True, e
    if isinstance(value, int | float) and not isinstance(value, bool):
        for e in enum:
            if isinstance(e, int | float) and float(e) == float(value):
                return True, e
    return False, enum


def map_params(
    canonical: Canonical,
    schema: Mapping[str, Any] | None,
    caller_params: Mapping[str, Any] | None = None,
    *,
    names: Mapping[str, tuple[str, ...]] = NAMES,
) -> Mapped:
    """Map canonical params onto the endpoint's input properties."""
    payload: dict[str, Any] = {}
    ignored: list[str] = []
    notes: list[str] = []

    if schema is None or not schema.get("properties"):
        payload = _fallback(canonical, names)
        notes.append("input schema unavailable; sent common parameter names")
        payload.update(dict(caller_params or {}))
        return Mapped(payload, ignored, notes)

    props: Mapping[str, Mapping[str, Any]] = schema["properties"]

    def first(*cands: str) -> str | None:
        return next((c for c in cands if c in props), None)

    def put(canon_name: str, prop_name: str | None, value: Any) -> None:
        if prop_name is None:
            ignored.append(canon_name)
            return
        ok, fitted = coerce(props[prop_name], value)
        if ok:
            payload[prop_name] = fitted
        else:
            ignored.append(canon_name)
            notes.append(f"{canon_name}={value!r} not accepted by {prop_name}; allowed: {fitted}")

    if canonical.prompt is not None:
        put("prompt", first("prompt", "text_prompt"), canonical.prompt)

    # Source image + references. When only a list field exists the source goes first.
    refs = list(canonical.references)
    ref_list = next((c for c in names["references"] if c in props and _is_array(props[c])), None)
    if canonical.image is not None:
        single = next((c for c in names["image"] if c in props and not _is_array(props[c])), None)
        if single is not None:
            payload[single] = canonical.image
            if refs:
                other = next(
                    (c for c in names["references"] if c in props and _is_array(props[c]) and c != single), None
                )
                if other:
                    payload[other] = refs
                else:
                    ignored.append("references")
        else:
            arr = next((c for c in names["image"] if c in props and _is_array(props[c])), None) or ref_list
            if arr:
                payload[arr] = [canonical.image, *refs]
            else:
                ignored.append("image")
    elif refs:
        single_ref = next((c for c in names["references"] if c in props and not _is_array(props[c])), None)
        if ref_list:
            payload[ref_list] = refs
        elif single_ref:
            payload[single_ref] = refs[0]
            if len(refs) > 1:
                notes.append(f"endpoint takes a single reference image; used the first of {len(refs)}")
        else:
            ignored.append("references")

    if canonical.mask is not None:
        put("mask", first(*names["mask"]), canonical.mask)
    if canonical.aspect_ratio:
        put("aspect_ratio", first("aspect_ratio"), canonical.aspect_ratio)
    if canonical.size:
        _put_size(canonical.size, props, names["size"], payload, ignored, notes)
    if canonical.n is not None:
        nn = first(*names["n"])
        if nn is not None:
            put("n", nn, canonical.n)
        elif canonical.n != 1:
            ignored.append("n")
    if canonical.seed is not None:
        put("seed", first("seed"), canonical.seed)
    if canonical.transparent_background:
        if "background" in props and coerce(props["background"], "transparent")[0]:
            payload["background"] = "transparent"
            if "output_format" in props:
                fmt = canonical.output_format if canonical.output_format in ("png", "webp") else "png"
                if canonical.output_format and canonical.output_format != fmt:
                    notes.append("transparent output needs png or webp; using png")
                ok, fitted = coerce(props["output_format"], fmt)
                if ok:
                    payload["output_format"] = fitted
        else:
            ignored.append("transparent_background")
    if canonical.output_format and "output_format" not in payload:
        put("output_format", first("output_format", "format"), canonical.output_format)
    if canonical.quality:
        put("quality", first("quality"), canonical.quality)
    if canonical.scale is not None:
        put("scale", first(*names["scale"]), canonical.scale)
    if canonical.mask_only:
        # segmentation endpoints: bare binary mask, no overlay (not reported if absent)
        if "mask_only" in props:
            payload["mask_only"] = True
        if "apply_mask" in props:
            payload["apply_mask"] = False
        if "output_format" in props and coerce(props["output_format"], "png")[0]:
            payload.setdefault("output_format", "png")

    payload.update(dict(caller_params or {}))
    return Mapped(payload, ignored, notes)


def _put_size(
    size: str,
    props: Mapping[str, Mapping[str, Any]],
    candidates: tuple[str, ...],
    payload: dict[str, Any],
    ignored: list[str],
    notes: list[str],
) -> None:
    """Try each size-like property until one accepts the value."""
    tried: list[str] = []
    for name in candidates:
        if name not in props:
            continue
        ok, fitted = coerce(props[name], size)
        if ok:
            payload[name] = fitted
            return
        tried.append(f"{name} allows {fitted}")
    ignored.append("size")
    if tried:
        notes.append(f"size={size!r} not accepted ({'; '.join(tried)})")


def _fallback(c: Canonical, names: Mapping[str, tuple[str, ...]]) -> dict[str, Any]:
    p: dict[str, Any] = {}
    if c.prompt is not None:
        p["prompt"] = c.prompt
    if c.image is not None:
        p[names["image"][0]] = c.image
        p[names["references"][0]] = [c.image, *c.references]
    elif c.references:
        p[names["references"][0]] = list(c.references)
    if c.mask is not None:
        p[names["mask"][0]] = c.mask
    if c.aspect_ratio:
        p["aspect_ratio"] = c.aspect_ratio
    if c.size:
        m = _WH_RE.match(c.size)
        p[names["size"][0]] = {"width": int(m.group(1)), "height": int(m.group(2))} if m else c.size
    if c.n is not None:
        p[names["n"][0]] = c.n
    if c.seed is not None:
        p["seed"] = c.seed
    if c.transparent_background:
        p["background"] = "transparent"
        p["output_format"] = c.output_format if c.output_format in ("png", "webp") else "png"
    elif c.output_format:
        p["output_format"] = c.output_format
    if c.quality:
        p["quality"] = c.quality
    if c.scale is not None:
        p[names["scale"][0]] = c.scale
    if c.mask_only:
        p["mask_only"] = True
        p["apply_mask"] = False
    return p
