"""Adapter registry: ``IMAGE_<OP>_API`` (explicit or detected from the URL host) -> class."""

from __future__ import annotations

import httpx

from ..config import OpConfig
from .base import AdapterError, AdapterResult, ImageJob, Unsupported
from .fal import FalAdapter
from .local import LocalAdapter
from .openai import OpenAIAdapter
from .openrouter import OpenRouterAdapter
from .opper import OpperAdapter

ADAPTERS = {cls.name: cls for cls in (OpenRouterAdapter, OpperAdapter, OpenAIAdapter, FalAdapter, LocalAdapter)}


def get_adapter(cfg: OpConfig, client: httpx.AsyncClient) -> OpenRouterAdapter | OpperAdapter | OpenAIAdapter | FalAdapter | LocalAdapter:
    try:
        cls = ADAPTERS[cfg.api or ""]
    except KeyError:
        raise Unsupported(f"no adapter {cfg.api!r} for IMAGE_{cfg.op}; known: {', '.join(ADAPTERS)}") from None
    return cls(cfg, client)


def supported_ops() -> dict[str, list[str]]:
    return {name: sorted(cls.supports) for name, cls in ADAPTERS.items()}


__all__ = [
    "ADAPTERS",
    "AdapterError",
    "AdapterResult",
    "ImageJob",
    "Unsupported",
    "get_adapter",
    "supported_ops",
]
