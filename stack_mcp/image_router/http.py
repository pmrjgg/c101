"""Shared httpx.AsyncClient factory with retries/backoff and a test seam.

Every provider call goes through ``request()`` so retry policy lives in one
place, with exponential backoff (honouring Retry-After):

* idempotent methods (GET/HEAD/PUT/DELETE/OPTIONS: polls, downloads, schema
  lookups, cancels) retry every transport error and 429/5xx;
* non-idempotent methods (POST/PATCH: paid generations) retry only failures
  that cannot have reached the origin - connect errors/timeouts, pool
  timeouts, and 429/503/522/529 ("not processed"). A dropped connection, a
  read timeout or a 500/502/504/520/524 may mean the provider is already
  generating (and billing), so those are final.

Tests install an ``httpx.MockTransport`` with ``set_transport()`` and set
``BACKOFF_SCALE = 0`` so polling and retries run instantly.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from collections.abc import Mapping
from typing import Any

import httpx

from . import __version__

USER_AGENT = f"stack-image-router/{__version__}"

# connect/write/pool are short; read is long because synchronous image APIs
# (GPT Image at high quality, 4K outputs; OpenRouter documents ~94 s) can take minutes.
DEFAULT_TIMEOUT = httpx.Timeout(connect=20.0, read=300.0, write=120.0, pool=30.0)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 520, 522, 524, 529})
# Statuses that mean the request was not processed, so even a paid POST may be resent:
# 429 rate limited, 503 unavailable/overloaded, 522 (Cloudflare) origin TCP connect timed out,
# 529 overloaded. 500/502/504/520/524 can arrive while the origin is still working.
UNPROCESSED_STATUSES = frozenset({429, 503, 522, 529})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})
# Transport failures where the request never reached the origin.
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# Deterministic client-side failures: resending cannot help.
_NEVER_RETRY = (httpx.UnsupportedProtocol, httpx.LocalProtocolError)
MAX_RETRIES = int(os.environ.get("IMAGE_ROUTER_HTTP_RETRIES", "3"))
BACKOFF_BASE = 1.5  # seconds; doubled per attempt, jittered, capped
BACKOFF_CAP = 30.0
# Multiplier for every sleep in this package (retries and polling). Tests set 0.
BACKOFF_SCALE = float(os.environ.get("IMAGE_ROUTER_BACKOFF_SCALE", "1"))

_transport: httpx.AsyncBaseTransport | None = None


class HttpError(RuntimeError):
    """A provider returned a non-success status (after retries)."""

    def __init__(self, status: int, url: str, detail: str):
        self.status = status
        self.url = url
        self.detail = detail
        super().__init__(f"HTTP {status} from {_short_url(url)}: {detail}")


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Install (or clear) a transport used by every client this module creates."""
    global _transport
    _transport = transport


def new_client(*, timeout: httpx.Timeout | float | None = None) -> httpx.AsyncClient:
    """One client per tool call; closed by the caller (``async with``)."""
    return httpx.AsyncClient(
        timeout=timeout or DEFAULT_TIMEOUT,
        transport=_transport,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


async def sleep(seconds: float) -> None:
    """Scaled sleep; every wait in the router goes through here."""
    if seconds > 0 and BACKOFF_SCALE > 0:
        await asyncio.sleep(seconds * BACKOFF_SCALE)
    else:
        await asyncio.sleep(0)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, min(float(value), BACKOFF_CAP))
    except ValueError:
        return None


def _backoff(attempt: int) -> float:
    return min(BACKOFF_CAP, BACKOFF_BASE * (2**attempt)) * (0.75 + random.random() / 2)


def _short_url(url: str) -> str:
    # never echo query strings, fragments or user info (presigned signatures and tokens live there)
    u = str(url).split("?", 1)[0].split("#", 1)[0]
    if "://" in u:
        scheme, rest = u.split("://", 1)
        authority, sep, path = rest.partition("/")
        u = f"{scheme}://{authority.rsplit('@', 1)[-1]}{sep}{path}"
    return u


def error_detail(resp: httpx.Response, limit: int = 500) -> str:
    """Best-effort human message from an error response body."""
    try:
        body: Any = resp.json()
    except Exception:
        text = resp.text.strip()
        return (text[:limit] + "...") if len(text) > limit else text or resp.reason_phrase
    if isinstance(body, Mapping):
        for key in ("detail", "error", "message", "errors"):
            if key in body and body[key]:
                val = body[key]
                if isinstance(val, Mapping):
                    val = val.get("message") or val
                text = val if isinstance(val, str) else str(val)
                return text[:limit]
    text = str(body)
    return text[:limit]


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int | None = None,
    raise_for_status: bool = True,
    idempotent: bool | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send with retries (see the module docstring for what is retried).

    ``idempotent`` overrides the method-based default, e.g. for a POST that is
    safe to resend.
    """
    retries = MAX_RETRIES if retries is None else retries
    safe = method.upper() in IDEMPOTENT_METHODS if idempotent is None else idempotent
    retry_errors: tuple[type[Exception], ...] = (httpx.TransportError,) if safe else _NOT_SENT_ERRORS
    retry_statuses = RETRY_STATUSES if safe else UNPROCESSED_STATUSES
    attempt = 0
    while True:
        try:
            resp = await client.request(method, url, **kwargs)
        except retry_errors as exc:
            if attempt >= retries or isinstance(exc, _NEVER_RETRY):
                raise
            delay = _backoff(attempt)
            print(f"image-router: {type(exc).__name__} on {_short_url(url)}; retry in {delay:.1f}s", file=sys.stderr)
        else:
            if resp.status_code in retry_statuses and attempt < retries:
                delay = _retry_after(resp) or _backoff(attempt)
                print(
                    f"image-router: HTTP {resp.status_code} from {_short_url(url)}; retry in {delay:.1f}s",
                    file=sys.stderr,
                )
            else:
                if raise_for_status and resp.status_code >= 400:
                    raise HttpError(resp.status_code, url, error_detail(resp))
                return resp
        attempt += 1
        await sleep(delay)
