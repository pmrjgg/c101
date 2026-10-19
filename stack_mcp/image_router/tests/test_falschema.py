"""OpenAPI lookup and canonical-parameter mapping against a fixture document."""

from __future__ import annotations

import asyncio
import json

import httpx

from stack_mcp.image_router import falschema as schema, http
from stack_mcp.image_router.falschema import Canonical, input_schema_from_openapi, map_params

from .conftest import FIXTURES, json_response

ENDPOINT = "fal-ai/test-model/edit"


def _doc() -> dict:
    return json.loads((FIXTURES / "fal_openapi_edit.json").read_text())


def _schema() -> dict:
    s = input_schema_from_openapi(_doc(), ENDPOINT)
    assert s is not None
    return s


def test_locates_post_body_and_resolves_refs():
    s = _schema()
    assert s["title"] == "TestEditInput"
    assert {"prompt", "image_urls", "mask_url", "image_size"} <= set(s["properties"])
    # the ImageSize $ref inside anyOf is inlined
    any_of = s["properties"]["image_size"]["anyOf"]
    assert any(set(p.get("properties") or {}) == {"width", "height"} for p in any_of)


def test_edit_mapping_prepends_source_to_list_and_maps_everything():
    c = Canonical(
        prompt="make it blue",
        image="data:image/png;base64,SRC",
        references=["https://x/ref1.png", "https://x/ref2.png"],
        mask="data:image/png;base64,MASK",
        aspect_ratio="16:9",  # not in schema -> ignored
        size="1024x1536",  # -> ImageSize object
        n=2,
        seed=7,
        transparent_background=True,
        quality="HIGH",  # case-insensitive enum match
        scale=2,  # not in schema -> ignored
    )
    m = map_params(c, _schema(), {"sync_mode": True, "num_images": 3})
    p = m.payload
    assert p["prompt"] == "make it blue"
    assert p["image_urls"] == ["data:image/png;base64,SRC", "https://x/ref1.png", "https://x/ref2.png"]
    assert p["mask_url"] == "data:image/png;base64,MASK"
    assert p["image_size"] == {"width": 1024, "height": 1536}
    assert p["seed"] == 7
    assert p["background"] == "transparent" and p["output_format"] == "png"
    assert p["quality"] == "high"
    # caller params merged last (override canonical n)
    assert p["sync_mode"] is True and p["num_images"] == 3
    assert "aspect_ratio" not in p and "upscale_factor" not in p
    assert set(m.ignored) == {"aspect_ratio", "scale"}


def test_enum_size_passthrough_and_rejection():
    s = _schema()
    ok = map_params(Canonical(prompt="x", size="landscape_4_3"), s)
    assert ok.payload["image_size"] == "landscape_4_3" and not ok.ignored
    bad = map_params(Canonical(prompt="x", size="2K"), s)
    assert "image_size" not in bad.payload
    assert bad.ignored == ["size"]
    assert any("size='2K'" in n for n in bad.notes)


def test_single_image_field_with_reference_list():
    ideogram_like = {
        "properties": {
            "prompt": {"type": "string"},
            "image_url": {"type": "string"},
            "reference_image_urls": {"type": "array", "items": {"type": "string"}},
            "mask_url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "resolution": {"type": "string", "enum": ["1K", "2K", "4K"]},
            "num_images": {"type": "integer"},
        }
    }
    m = map_params(Canonical(prompt="p", image="SRC", references=["R1"], mask="M", size="2k", n=1), ideogram_like)
    assert m.payload["image_url"] == "SRC"
    assert m.payload["reference_image_urls"] == ["R1"]
    assert m.payload["mask_url"] == "M"
    assert m.payload["resolution"] == "2K"  # case-insensitive enum
    assert m.payload["num_images"] == 1
    assert not m.ignored


def test_references_only_and_missing_fields_reported():
    t2i = {"properties": {"prompt": {"type": "string"}, "aspect_ratio": {"type": "string"}}}
    m = map_params(Canonical(prompt="p", references=["R"], transparent_background=True, mask="M"), t2i)
    assert set(m.ignored) == {"references", "transparent_background", "mask"}


def test_upscale_and_mask_only_hints():
    s = {
        "properties": {
            "image_url": {"type": "string"},
            "upscale_factor": {"type": "number"},
            "prompt": {"type": "string"},
            "apply_mask": {"type": "boolean"},
            "output_format": {"type": "string", "enum": ["jpeg", "png"]},
        }
    }
    m = map_params(Canonical(image="SRC", scale=4.0, prompt="car", mask_only=True), s)
    assert m.payload == {"image_url": "SRC", "upscale_factor": 4.0, "prompt": "car", "apply_mask": False, "output_format": "png"}


def test_fallback_uses_common_names_when_schema_missing():
    m = map_params(Canonical(prompt="p", image="SRC", references=["R"], mask="M", size="2048x1024", n=2), None)
    p = m.payload
    assert p["image_url"] == "SRC" and p["image_urls"] == ["SRC", "R"]
    assert p["mask_url"] == "M" and p["num_images"] == 2
    assert p["image_size"] == {"width": 2048, "height": 1024}
    assert any("schema unavailable" in n for n in m.notes)


def test_fetch_caches_in_memory_and_on_disk(mock_http, isolated):
    seen = mock_http(lambda req: json_response(_doc()))

    async def go():
        async with http.new_client() as client:
            a = await schema.fetch_fal_input_schema(client, ENDPOINT, "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=")
            b = await schema.fetch_fal_input_schema(client, ENDPOINT, "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=")
            return a, b

    a, b = asyncio.run(go())
    assert a is b and a["title"] == "TestEditInput"
    assert len(seen) == 1
    assert seen[0].url.params["endpoint_id"] == ENDPOINT
    cached = list((isolated / ".stack" / "cache" / "fal-schemas").glob("*.json"))
    assert len(cached) == 1
    # a fresh process (memory cleared) reads the disk cache without HTTP
    schema.clear_memory_cache()
    mock_http(lambda req: httpx.Response(500))

    async def again():
        async with http.new_client() as client:
            return await schema.fetch_fal_input_schema(client, ENDPOINT, "https://fal.ai/x?endpoint_id=")

    assert asyncio.run(again())["title"] == "TestEditInput"


def test_fetch_failure_returns_none(mock_http):
    mock_http(lambda req: httpx.Response(404, json={"detail": "nope"}))

    async def go():
        async with http.new_client() as client:
            return await schema.fetch_fal_input_schema(client, "fal-ai/missing", "https://fal.ai/x?endpoint_id=")

    assert asyncio.run(go()) is None
