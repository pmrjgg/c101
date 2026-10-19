"""Resolve the project's .mcp.json for SDK sessions that run outside this repository.

Inside the repo the CLI reads .mcp.json itself (SDK sessions load project servers
without an approval prompt). Elsewhere we hand the servers over explicitly, with
every ``${CLAUDE_PROJECT_DIR...}`` placeholder rewritten to this repo's absolute
path so the launchers (``bin/mcp-run``, ``bin/image-router``) and the
``bin/mcp-headers`` helper are found from any working directory.

Secrets never appear here: the SDK passes MCP config to the CLI on its command
line, so auth stays behind ``headersHelper`` (remote) and ``bin/mcp-run``
(stdio), both of which read ``~/.claude/stack.env`` at connection time.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable

from stack import paths

_PLACEHOLDER = re.compile(r"\$\{CLAUDE_PROJECT_DIR(?::-[^}]*)?\}")


def _resolve(value: Any) -> Any:
    if isinstance(value, str):
        return _PLACEHOLDER.sub(paths.REPO, value)
    if isinstance(value, list):
        return [_resolve(v) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v) for k, v in value.items() if not k.startswith("_")}
    return value


def project_servers(path: str | None = None) -> dict[str, dict[str, Any]]:
    with open(path or os.path.join(paths.REPO, ".mcp.json"), encoding="utf-8") as fh:
        return json.load(fh).get("mcpServers", {})


def load_mcp_servers(include: Iterable[str] | None = None, path: str | None = None) -> dict[str, dict[str, Any]]:
    """{name: config} for ``ClaudeAgentOptions(mcp_servers=...)`` with absolute launcher paths."""
    wanted = set(include) if include is not None else None
    out = {}
    for name, cfg in project_servers(path).items():
        if wanted is not None and name not in wanted:
            continue
        cfg = _resolve(cfg)
        if cfg.get("type", "stdio") == "stdio":
            cfg.setdefault("type", "stdio")
        out[name] = cfg
    return out
