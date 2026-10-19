"""Input resolution, MIME sniffing, data URIs and output writing.

Inputs may be local paths (relative to CLAUDE_PROJECT_DIR or the cwd, with ~
expansion), file:// URLs, http(s) URLs or data URIs. Outputs are written under
``output_dir`` (default: ``<project>/<default_output_dir>/<YYYYMMDD>``) with
slugged, collision-free names and a ``<file>.json`` sidecar that records what
produced the file. Sidecars never contain key material or base64 payloads.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import mimetypes
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import anyio
import httpx

from . import http
from .config import project_dir, secret_values

MAX_INPUT_BYTES = 64 * 1024 * 1024  # refuse absurd inputs early

EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
    "application/pdf": ".pdf",
}


class InputError(ValueError):
    """An input reference could not be resolved."""


@dataclass(slots=True)
class InputFile:
    data: bytes
    mime: str
    name: str
    source: str  # the caller's reference, sanitised for sidecars (no data-URI payloads, no query)
    # Full original http(s) URL, set only when ``data`` is exactly what that URL serves, so a
    # provider may fetch it itself instead of receiving the bytes. May carry signatures in its
    # query string: never written to sidecars, results or logs (request summaries and sanitize()
    # strip URL queries). Converted/derived inputs (masks, PNG re-encodes, EXIF-rotated copies)
    # must leave it None so their bytes are sent.
    url: str | None = None
    notes: list[str] = field(default_factory=list)  # how the input was normalised (orientation, format)

    @property
    def data_uri(self) -> str:
        return to_data_uri(self.data, self.mime)

    def describe(self) -> dict[str, Any]:
        d: dict[str, Any] = {"source": self.source, "mime": self.mime, "bytes": len(self.data)}
        if self.notes:
            d["notes"] = list(self.notes)
        return d


@dataclass(slots=True)
class OutputBlob:
    """A provider result before it is written: bytes plus a MIME hint."""

    data: bytes
    mime: str | None = None
    source_url: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


# --- sniffing / data URIs -------------------------------------------------------------


def sniff_mime(data: bytes) -> str | None:
    """Identify png, jpeg, webp, gif and svg by magic bytes (plus a few extras)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith(b"%PDF"):
        return "application/pdf"
    head = data[:2048].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith((b"<svg", b"<?xml", b"<!--", b"<!DOCTYPE svg", b"<!doctype svg")) and b"<svg" in data[:8192]:
        return "image/svg+xml"
    return None


def to_data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


# --- URLs in anything that is shown or persisted ------------------------------------------

# An http(s) URL inside arbitrary text: scheme, authority (may hold user:password@), path, query, fragment.
_URL_RE = re.compile(r"\b(https?)://([^\s/?#'\"<>]+)([^\s?#'\"<>]*)(\?[^\s#'\"<>]*)?(#[^\s'\"<>]*)?", re.I)


def display_url(url: str) -> str:
    """``scheme://host[:port]/path`` of an http(s) URL: no user info, query or fragment.

    Presigned / token URLs carry their credentials in exactly those parts, so this is the
    form used for sidecars, results, errors and logs.
    """
    m = _URL_RE.match(url.strip())
    if not m:
        return url.split("?", 1)[0].split("#", 1)[0]
    scheme, authority, path = m.group(1), m.group(2), m.group(3)
    return f"{scheme}://{authority.rsplit('@', 1)[-1]}{path}"


def redact_urls(text: str) -> str:
    """Every http(s) URL in ``text`` reduced to :func:`display_url` (+ a marker where a query,
    fragment or user info was removed)."""
    if "://" not in text:
        return text

    def repl(m: re.Match[str]) -> str:
        scheme, authority, path, query, fragment = m.groups()
        host = authority.rsplit("@", 1)[-1]
        out = f"{scheme}://{'<redacted>@' if '@' in authority else ''}{host}{path}"
        if query:
            out += "?<redacted>"
        if fragment:
            out += "#<redacted>"
        return out

    return _URL_RE.sub(repl, text)


def parse_data_uri(uri: str) -> tuple[bytes, str]:
    m = re.match(r"^data:([^;,]*)((?:;[^;,=]+=[^;,]*)*)(;base64)?,(.*)$", uri, re.S)
    if not m:
        raise InputError("malformed data URI")
    mime, _params, is_b64, payload = m.groups()
    try:
        data = base64.b64decode(payload, validate=False) if is_b64 else unquote(payload).encode("utf-8")
    except (binascii.Error, ValueError) as exc:
        raise InputError(f"data URI is not valid base64: {exc}") from None
    return data, (mime or sniff_mime(data) or "application/octet-stream")


def ext_for(mime: str | None, data: bytes | None = None) -> str:
    if data is not None and (sniffed := sniff_mime(data)):
        mime = sniffed
    if mime and mime in EXT_BY_MIME:
        return EXT_BY_MIME[mime]
    guess = mimetypes.guess_extension(mime or "") if mime else None
    return guess or ".bin"


# --- input resolution -----------------------------------------------------------------


_PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".test", ".invalid")


def is_public_url(url: str) -> bool:
    """True if a remote provider could plausibly fetch ``url`` itself.

    Loopback, private, link-local and reserved IP literals, ``localhost``,
    single-label hosts and private-use suffixes are not public. No DNS lookup
    is made (a public name resolving to a private address is not detected).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host != "localhost" and "." in host and not host.endswith(_PRIVATE_SUFFIXES)
    return ip.is_global


def resolve_local_path(ref: str, base: Path | None = None) -> Path:
    p = Path(os.path.expanduser(ref))
    if not p.is_absolute():
        p = (base or project_dir()) / p
    return p.resolve()


async def resolve_input(ref: str, client: httpx.AsyncClient | None = None, base: Path | None = None) -> InputFile:
    """Turn a caller reference into bytes + MIME + a display name."""
    if not isinstance(ref, str) or not ref.strip():
        raise InputError("empty image reference")
    ref = ref.strip()
    if ref.startswith("data:"):
        data, mime = parse_data_uri(ref)
        return InputFile(data, sniff_mime(data) or mime, "inline", f"data:{mime} ({len(data)} bytes)")
    if ref.startswith(("http://", "https://")):
        if client is None:
            async with http.new_client() as c:
                return await resolve_input(ref, c, base)
        shown = display_url(ref)
        try:
            data, mime = await download(client, ref)
        except http.HttpError as exc:
            raise InputError(
                f"could not download input {shown}: HTTP {exc.status} ({exc.detail[:200]}); "
                "pass a reachable URL, a local path or a data URI"
            ) from None
        except httpx.HTTPError as exc:
            raise InputError(
                f"could not download input {shown}: {type(exc).__name__}"
                f"{': ' + str(exc)[:200] if str(exc) else ''}; "
                "pass a reachable URL, a local path or a data URI"
            ) from None
        name = Path(urlparse(ref).path).name or "download"
        return InputFile(data, mime, name, shown, url=ref)
    if ref.startswith("file://"):
        parsed = urlparse(ref)
        path = Path(unquote(parsed.path))
    else:
        path = resolve_local_path(ref, base)
    if not path.is_file():
        raise InputError(f"file not found: {path}")
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise InputError(f"{path} is {size} bytes; limit is {MAX_INPUT_BYTES}")
    # off the event loop: inputs can be tens of MB
    data = await anyio.to_thread.run_sync(path.read_bytes)
    mime = sniff_mime(data) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return InputFile(data, mime, path.name, str(path))


async def download(
    client: httpx.AsyncClient, url: str, headers: Mapping[str, str] | None = None
) -> tuple[bytes, str]:
    resp = await http.request(client, "GET", url, headers=dict(headers or {}))
    data = resp.content
    if len(data) > MAX_INPUT_BYTES * 2:
        raise InputError(f"download from {display_url(url)} is too large ({len(data)} bytes)")
    ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    mime = sniff_mime(data) or (ctype if ctype and ctype != "application/octet-stream" else None)
    return data, mime or "application/octet-stream"


# --- output writing -------------------------------------------------------------------


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0] or text[:max_len]
    return text or "image"


def output_directory(output_dir: str | None, default_output_dir: str, now: datetime | None = None) -> Path:
    """Explicit output_dir (relative to the project) or <project>/<default>/<YYYYMMDD>."""
    base = project_dir()
    if output_dir:
        d = Path(os.path.expanduser(output_dir))
        return d if d.is_absolute() else base / d
    now = now or datetime.now()
    return base / default_output_dir / now.strftime("%Y%m%d")


def unique_path(directory: Path, stem: str, ext: str) -> Path:
    """A new, empty, collision-free file ``<directory>/<stem>[-N]<ext>`` (created atomically)."""
    directory.mkdir(parents=True, exist_ok=True)
    return _exclusive_path(directory, slugify(stem, 80), ext)


def new_file_path(directory: Path, stem: str, ext: str) -> Path:
    """Like :func:`unique_path` but keeps ``stem`` as given (derived names such as logo.preview)."""
    directory.mkdir(parents=True, exist_ok=True)
    return _exclusive_path(directory, stem, ext)


def _exclusive_path(directory: Path, stem: str, ext: str) -> Path:
    """Create the file atomically (O_EXCL) so concurrent calls never collide."""
    for i in range(1, 10_000):
        name = f"{stem}{ext}" if i == 1 else f"{stem}-{i}{ext}"
        path = directory / name
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        return path
    raise OSError(f"could not find a free filename for {stem}{ext} in {directory}")


_B64_RE = re.compile(r"[A-Za-z0-9+/=_-]{200,}")  # long base64(url) runs
_LINE_BREAKS_RE = re.compile(r"[\r\n]+")


def _looks_base64(value: str) -> bool:
    """Long base64/base64url text, also MIME-style wrapped (76-char lines).

    Only line breaks are ignored, not spaces, so long prose never matches.
    """
    if len(value) < 200:
        return False
    return _B64_RE.fullmatch(_LINE_BREAKS_RE.sub("", value.strip())) is not None
_SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|authorization|credential)", re.I)


def sanitize(value: Any, secrets: list[str] | None = None, _depth: int = 0) -> Any:
    """Strip base64 blobs, data URIs, anything key-shaped and URL credentials from a JSON-able value.

    http(s) URLs anywhere in a string lose their query, fragment and user info (presigned
    signatures, tokens): see :func:`redact_urls`.
    """
    secrets = secret_values() if secrets is None else secrets
    if _depth > 12:
        return "<nested>"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _SECRET_KEY_RE.search(str(k)):
                out[str(k)] = "<redacted>"
            else:
                out[str(k)] = sanitize(v, secrets, _depth + 1)
        return out
    if isinstance(value, list | tuple):
        return [sanitize(v, secrets, _depth + 1) for v in value]
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    if isinstance(value, str):
        if value.startswith("data:"):
            head = value.split(",", 1)[0]
            return f"<{head} {len(value)} chars>"
        if _looks_base64(value):
            return f"<base64 {len(value)} chars>"
        for s in secrets:
            if s in value:
                value = value.replace(s, "***")
        # presigned / token URLs (inputs a provider fetched itself, storage links): never persist
        # their query, fragment or user info
        return redact_urls(value)
    if isinstance(value, int | float | bool) or value is None:
        return value
    return str(value)


@dataclass(slots=True)
class WrittenFile:
    path: Path
    mime: str
    bytes: int
    width: int | None = None
    height: int | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"path": str(self.path), "mime": self.mime, "bytes": self.bytes}
        if self.width is not None:
            d["width"] = self.width
        if self.height is not None:
            d["height"] = self.height
        return d


def write_output(
    blob: OutputBlob,
    directory: Path,
    stem: str,
    sidecar: Mapping[str, Any],
    *,
    exact_path: Path | None = None,
) -> WrittenFile:
    """Write bytes + <file>.json sidecar; returns path, mime and dimensions.

    ``exact_path`` (a caller-chosen output path) is written as given, replacing any file there;
    otherwise a collision-free ``<directory>/<stem>[-N].<ext>`` is created.
    """
    from .imaging import image_size  # local import: imaging pulls in Pillow

    mime = sniff_mime(blob.data) or blob.mime or "application/octet-stream"
    if exact_path is not None:
        exact_path.parent.mkdir(parents=True, exist_ok=True)
        path = exact_path
    else:
        directory.mkdir(parents=True, exist_ok=True)
        path = _exclusive_path(directory, slugify(stem, 80), ext_for(mime, blob.data))
    path.write_bytes(blob.data)
    width = height = None
    if mime.startswith("image/") and mime != "image/svg+xml":
        try:
            width, height = image_size(blob.data)
        except Exception:
            pass
    meta = dict(sidecar)
    meta.setdefault("created", datetime.now().astimezone().isoformat(timespec="seconds"))
    meta["file"] = path.name
    meta["mime"] = mime
    meta["bytes"] = len(blob.data)
    if width:
        meta["width"], meta["height"] = width, height
    if blob.source_url and not blob.source_url.startswith("data:"):
        meta["source_url"] = display_url(blob.source_url)
    sidecar_path = path.with_name(path.name + ".json")
    sidecar_path.write_text(json.dumps(sanitize(meta), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return WrittenFile(path, mime, len(blob.data), width, height)


def file_stem(prefix: str | None, text: str | None, tag: str, now: datetime | None = None) -> str:
    """<prefix|slug(prompt)>-<HHMMSS>-<tag>; uniqueness comes from _exclusive_path."""
    now = now or datetime.now()
    head = slugify(prefix, 40) if prefix else slugify(text or "image", 40)
    return f"{head}-{now.strftime('%H%M%S')}-{slugify(tag, 16)}"
