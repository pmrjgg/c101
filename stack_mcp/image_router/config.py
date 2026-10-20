"""Per-operation configuration, read from ``~/.claude/stack.env`` at call time.

Every image operation (OP) has its own endpoint, key and model tag::

    IMAGE_<OP>_URL     base URL of the router (https://openrouter.ai/api/v1, https://api.opper.ai, ...)
    IMAGE_<OP>_KEY     API key for that URL
    IMAGE_<OP>_MODEL   model tag sent to that URL
    IMAGE_<OP>_API     optional: openrouter | opper | openai (| local for TRACE and UPSCALE);
                       default detected from the URL host
    IMAGE_<OP>_PARAMS  optional JSON object merged into every request for that OP

There are no fallbacks: an operation uses exactly its configured endpoint and
model, and an unset operation reports the env names to set.

The env file (``$CLAUDE_STACK_ENV`` or ``~/.claude/stack.env``) is parsed with
the same rules as ``stack/envfile.py`` (KEY=VALUE, optional ``export``, matching
quotes, inline `` # comment`` on unquoted values) every time a value is needed,
so edits take effect without restarting the server. A non-empty value in the
file wins; otherwise ``os.environ`` is used - except for the values that
``bin/mcp-run`` copied from the file into the environment at launch (see
:func:`snapshot_boot_env`): those follow the file, so deleting or blanking a line
takes effect too.

Key values only ever leave this module through :meth:`OpConfig.key` (request
headers). Everything that can reach a tool result, a sidecar or a log uses
:meth:`OpConfig.describe`, which reports the URL host and model tag only.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]  # .../stack_mcp/image_router -> repo root
OPS_DOC_PATH = REPO_ROOT / "config" / "image-ops.json"
DEFAULT_OUTPUT_DIR = ".stack/images"

APIS = ("openrouter", "opper", "openai", "fal", "local")
# Directive keys inside IMAGE_<OP>_PARAMS that steer the router and are never sent.
DIRECTIVE_KEYS = frozenset({"strategy", "mask_convention", "layerize_model"})
# Request fields the router owns: the model comes from IMAGE_<OP>_MODEL and the prompt / input
# images from the tool call. Neither IMAGE_<OP>_PARAMS nor a tool call's `params` may set them
# (that would be a silent per-call model switch, and sidecars would record the wrong model).
RESERVED_PARAM_KEYS = frozenset(
    {"model", "prompt", "messages", "input_references", "image", "image[]", "mask", "reference_images"}
)
CLAUDE_MANIPULATION = "claude"


class ConfigError(RuntimeError):
    """An operation is not configured, or configured inconsistently."""

    def __init__(self, message: str, *, missing_env: list[str] | None = None, op: str | None = None):
        super().__init__(message)
        self.missing_env = list(missing_env or [])
        self.op = op


@dataclass(frozen=True, slots=True)
class OpSpec:
    op: str
    tools: tuple[str, ...]
    purpose: str
    local_ok: bool = False  # IMAGE_<OP>_API=local is allowed


OP_SPECS: dict[str, OpSpec] = {
    s.op: s
    for s in (
        OpSpec("GEN", ("image_generate",), "text -> image"),
        OpSpec("REF", ("image_generate_with_references",), "generation guided by 1..N reference images"),
        OpSpec("EDIT", ("image_edit",), "instruction edit; masked inpaint when a mask is given"),
        OpSpec("TRANSPARENT", ("image_generate_transparent",), "transparent (RGBA) generation"),
        OpSpec("SEGMENT", ("image_segment",), "segmentation: prompt -> white-on-black mask PNG of the source size"),
        OpSpec(
            "BG_REMOVAL",
            ("image_remove_background",),
            "background removal -> RGBA cutout (alpha transferred onto the original pixels)",
        ),
        OpSpec("UPSCALE", ("image_upscale",), "faithful upscaling", local_ok=True),
        OpSpec("VECTOR", ("vector_generate",), "native SVG generation"),
        OpSpec("TRACE", ("image_vectorize",), "raster -> SVG tracing", local_ok=True),
        OpSpec(
            "VECTOR_MANIPULATION",
            ("svg_transform",),
            "SVG edits by an external model (default 'claude': the agent edits the SVG itself)",
        ),
    )
}
OPS: tuple[str, ...] = tuple(OP_SPECS)
# Earlier env prefixes still read when the current one is unset (deprecated; image_ops_status says so).
DEPRECATED_ALIASES: dict[str, str] = {"SEGMENT": "MASK", "TRANSPARENT": "RGBA", "BG_REMOVAL": "RGBA"}


def env_names(op: str) -> dict[str, str]:
    p = f"IMAGE_{op}_"
    return {"url": p + "URL", "key": p + "KEY", "model": p + "MODEL", "api": p + "API", "params": p + "PARAMS"}


# --- env file ------------------------------------------------------------------------------

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def env_file_path() -> Path:
    override = os.environ.get("CLAUDE_STACK_ENV")
    if override:
        return Path(override).expanduser()
    return Path(os.path.expanduser("~")) / ".claude" / "stack.env"


def parse_env_text(text: str) -> dict[str, str]:
    """Same rules as stack/envfile.py and bin/mcp-run; the file is never executed."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.lstrip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        if not _KEY_RE.match(key):
            continue
        m = re.match(r'^"(.*)"$', val) or re.match(r"^'(.*)'$", val)
        if m:
            val = m.group(1)
        else:
            val = re.split(r"\s#", val, maxsplit=1)[0].strip()
        out[key] = val
    return out


def env_file_state() -> tuple[int, int] | None:
    """(mtime_ns, size) of the env file, or None when it does not exist (change detection)."""
    try:
        st = env_file_path().stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def read_env_file(path: Path | None = None) -> dict[str, str]:
    try:
        text = (path or env_file_path()).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    return parse_env_text(text)


# The env file as it was when the server started serving. bin/mcp-run (how .mcp.json launches
# the server) exports every line of the file into the process environment, so without this a
# line deleted or blanked later would keep applying through that inherited copy until a restart.
_BOOT_FILE: dict[str, str] = {}


def snapshot_boot_env() -> None:
    """Remember the env file's current values as the ones bin/mcp-run injected at launch.

    Called once by the server before it starts serving. Afterwards :func:`current_env` drops
    every environment value that still equals its launch-time file value, so the file alone
    decides those names: a deleted or blanked line falls back to nothing (or to auto-detection),
    not to the stale launch copy. Names the file never set keep their ``os.environ`` fallback.
    """
    global _BOOT_FILE
    _BOOT_FILE = read_env_file()


def reset_boot_env() -> None:
    """Forget the launch snapshot (tests)."""
    global _BOOT_FILE
    _BOOT_FILE = {}


def current_env() -> dict[str, str]:
    """os.environ overlaid with the non-empty values of the env file (read now).

    Environment values that bin/mcp-run copied from the file at launch (same name, same value
    as the launch snapshot) are not used as a fallback: the file as it is now decides them.
    """
    boot = _BOOT_FILE
    env = {k: v for k, v in os.environ.items() if not (k in boot and boot[k] == v)}
    for k, v in read_env_file().items():
        if v:
            env[k] = v
    return env


# --- per-op config -------------------------------------------------------------------------


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower() or None
    except ValueError:
        return None


def detect_api(url: str | None) -> str:
    host = _host(url) or ""
    if host == "openrouter.ai" or host.endswith(".openrouter.ai"):
        return "openrouter"
    if host == "opper.ai" or host.endswith(".opper.ai"):
        return "opper"
    if host in ("fal.run", "fal.ai") or host.endswith((".fal.run", ".fal.ai")):
        return "fal"
    return "openai"


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class OpConfig:
    op: str
    url: str | None
    model: str | None
    api: str | None
    api_source: str  # "explicit" | "detected" | "default"
    params: dict[str, Any] = field(default_factory=dict)  # sent with every request
    directives: dict[str, Any] = field(default_factory=dict)  # router-only (strategy, mask_convention)
    missing_env: tuple[str, ...] = ()
    error: str | None = None
    deprecated_env: tuple[str, ...] = ()  # old IMAGE_MASK_* / IMAGE_RGBA_* names that supplied values
    _key: str | None = field(default=None, repr=False, compare=False)

    # --- derived ----------------------------------------------------------------------
    @property
    def spec(self) -> OpSpec:
        return OP_SPECS[self.op]

    @property
    def host(self) -> str | None:
        return _host(self.url)

    @property
    def is_local(self) -> bool:
        return self.api == "local"

    @property
    def is_claude(self) -> bool:
        """VECTOR_MANIPULATION handled by the agent itself (svg_transform hidden)."""
        return self.op == "VECTOR_MANIPULATION" and (self.model or CLAUDE_MANIPULATION).strip().lower() == CLAUDE_MANIPULATION

    @property
    def configured(self) -> bool:
        return not self.missing_env and self.error is None

    @property
    def base_url(self) -> str:
        return (self.url or "").rstrip("/")

    def key(self) -> str:
        """The key value, for request headers only. Never log or return it."""
        return self._key or ""

    def strategy(self, default: str) -> str:
        return str(self.directives.get("strategy") or default).strip().lower()

    def describe(self) -> dict[str, Any]:
        """Everything about this op that may be shown: never the key, only the URL host."""
        names = env_names(self.op)
        d: dict[str, Any] = {
            "op": self.op,
            "tools": list(self.spec.tools),
            "configured": self.configured,
            "adapter": self.api,
            "adapter_source": self.api_source,
            "url_host": self.host,
            "model": self.model,
            "params_keys": sorted(self.params),
            "directives": dict(self.directives),
            "missing_env": list(self.missing_env),
            "env": [names["url"], names["key"], names["model"], names["api"], names["params"]],
        }
        if self.op == "VECTOR_MANIPULATION":
            d["mode"] = "claude" if self.is_claude else "external"
            if self.is_claude:
                d["tools"] = []
                d["adapter"] = None
        if self.error:
            d["error"] = self.error
        if self.deprecated_env:
            d["deprecated_env"] = list(self.deprecated_env)
            d["note"] = f"rename {', '.join(self.deprecated_env)} to IMAGE_{self.op}_*"
        return d

    def label(self) -> str:
        """'<adapter> <host> <model>' for error messages (no key, no path)."""
        parts = [p for p in (self.api, self.host, self.model and f"model {self.model}") if p]
        return " ".join(parts) or self.op


def load_op(op: str, env: Mapping[str, str] | None = None) -> OpConfig:
    """Resolve one operation's configuration from the env file + os.environ (read now)."""
    op = op.upper()
    if op not in OP_SPECS:
        raise ValueError(f"unknown image operation {op!r}; expected one of {', '.join(OPS)}")
    env = current_env() if env is None else env
    names = env_names(op)

    alias = DEPRECATED_ALIASES.get(op)
    used_alias: list[str] = []

    def get(name: str) -> str | None:
        v = (env.get(name) or "").strip()
        if not v and alias:
            old = name.replace(f"IMAGE_{op}_", f"IMAGE_{alias}_", 1)
            v = (env.get(old) or "").strip()
            if v:
                used_alias.append(old)
        return v or None

    url, key, model = get(names["url"]), get(names["key"]), get(names["model"])
    api_raw = get(names["api"])
    params_raw = get(names["params"])
    errors: list[str] = []

    params: dict[str, Any] = {}
    directives: dict[str, Any] = {}
    if params_raw:
        try:
            parsed = json.loads(params_raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{names['params']} is not valid JSON ({exc.msg} at char {exc.pos})")
            parsed = {}
        if not isinstance(parsed, dict):
            errors.append(f"{names['params']} must be a JSON object")
            parsed = {}
        reserved = sorted(set(parsed) & RESERVED_PARAM_KEYS)
        if reserved:
            errors.append(
                f"{names['params']} may not set {', '.join(reserved)}: the model comes from {names['model']} "
                "and the prompt and input images from the tool call"
            )
        for k, v in parsed.items():
            if k in RESERVED_PARAM_KEYS:
                continue
            (directives if k in DIRECTIVE_KEYS else params)[k] = v

    if api_raw:
        api = api_raw.lower()
        api_source = "explicit"
        if api not in APIS:
            errors.append(f"{names['api']}={api_raw!r} is not one of {', '.join(a for a in APIS if a != 'local')}"
                          + (", local" if OP_SPECS[op].local_ok else ""))
        elif api == "local" and not OP_SPECS[op].local_ok:
            errors.append(f"{names['api']}=local is only available for TRACE and UPSCALE")
    elif url:
        api, api_source = detect_api(url), "detected"
    else:
        api, api_source = None, "default"

    missing: list[str] = []
    if op == "VECTOR_MANIPULATION" and (model or CLAUDE_MANIPULATION).lower() == CLAUDE_MANIPULATION:
        pass  # the agent edits SVG itself; nothing else is needed
    elif api == "local":
        pass  # vtracer / Pillow: no URL, key or model
    else:
        if not url:
            missing.append(names["url"])
        if not model:
            missing.append(names["model"])
        if not key and not (api == "openai" and _is_loopback(_host(url))):
            missing.append(names["key"])
        if url and urlparse(url).scheme not in ("http", "https"):
            errors.append(f"{names['url']} must be an http(s) URL")

    return OpConfig(
        op=op,
        url=url,
        model=model,
        api=api,
        api_source=api_source,
        params=params,
        directives=directives,
        missing_env=tuple(missing),
        error="; ".join(errors) or None,
        deprecated_env=tuple(sorted(set(used_alias))),
        _key=key,
    )


def load_all(env: Mapping[str, str] | None = None) -> dict[str, OpConfig]:
    env = current_env() if env is None else env
    return {op: load_op(op, env) for op in OPS}


def require(op: str, tool: str, env: Mapping[str, str] | None = None) -> OpConfig:
    """The op's config, or a ConfigError that names exactly what to set."""
    cfg = load_op(op, env)
    if cfg.error:
        raise ConfigError(f"{tool}: IMAGE_{op} configuration error: {cfg.error}", op=op)
    if cfg.missing_env:
        hint = (
            "OpenRouter: https://openrouter.ai/api/v1, Opper: https://api.opper.ai"
            + ("; or IMAGE_" + op + "_API=local for the local adapter" if cfg.spec.local_ok else "")
        )
        raise ConfigError(
            f"{tool} is not configured: set {', '.join(cfg.missing_env)} in {env_file_path()} "
            f"(IMAGE_{op}_URL is the router base URL - {hint}). No fallback is attempted.",
            missing_env=list(cfg.missing_env),
            op=op,
        )
    return cfg


# --- secrets / redaction -------------------------------------------------------------------

_EXTRA_SECRET_NAMES = ("OPENROUTER_API_KEY", "OPPER_API_KEY", "OPENAI_API_KEY")


def secret_values(env: Mapping[str, str] | None = None) -> list[str]:
    """Every key value currently configured (file + environment), longest first.

    Without an explicit ``env`` this also covers values still present in the raw process
    environment or the launch snapshot (e.g. a key line deleted from the file since launch),
    so a stale key can never leak through a message either.
    """
    names = {env_names(op)["key"] for op in OPS} | {f"IMAGE_{a}_KEY" for a in DEPRECATED_ALIASES.values()}
    names |= set(_EXTRA_SECRET_NAMES)
    sources: list[Mapping[str, str]] = [env] if env is not None else [current_env(), os.environ, _BOOT_FILE]
    vals = {(src.get(n) or "").strip() for src in sources for n in names}
    return sorted((v for v in vals if len(v) >= 6), key=len, reverse=True)


def redact(text: str, secrets: list[str] | None = None) -> str:
    """Replace any key value that leaked into a string with ***."""
    for v in secret_values() if secrets is None else secrets:
        if v in text:
            text = text.replace(v, "***")
    return text


# --- project paths -------------------------------------------------------------------------


def project_dir() -> Path:
    """CLAUDE_PROJECT_DIR when set (Claude Code exports it), else the cwd."""
    pd = os.environ.get("CLAUDE_PROJECT_DIR")
    if pd:
        p = Path(pd).expanduser()
        if p.is_dir():
            return p.resolve()
    return Path.cwd().resolve()
