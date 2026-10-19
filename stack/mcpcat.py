"""The stack's MCP server catalog (config/mcp.servers.json) and its inline copies in agent frontmatter.

Servers are lazy: instead of living in .mcp.json (connected for the whole session and visible to the main
conversation), each one is defined inline in the ``mcpServers`` of the agents that use it. Claude Code
connects an inline server when such a subagent starts and disconnects it when the subagent finishes.
``sync`` re-renders those inline copies from the catalog; ``drift`` reports copies that differ.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Union

from . import frontmatter, paths

CATALOG = os.path.join(paths.CONFIG_DIR, "mcp.servers.json")
Entry = Union[str, dict]


def catalog(path: Optional[str] = None) -> Dict[str, dict]:
    try:
        with open(path or CATALOG, encoding="utf-8") as fh:
            return json.load(fh).get("servers", {})
    except (OSError, ValueError):
        return {}


def entry_name(e: Entry) -> Optional[str]:
    """Server name of a frontmatter entry: the string itself, or the single key of an inline definition."""
    if isinstance(e, dict):
        return next(iter(e)) if len(e) == 1 else None
    return e


def render(entries: List[Entry], cat: Dict[str, dict]) -> List[Entry]:
    """Inline every catalog server; keep other entries (built-ins, .mcp.json names) as they are."""
    out: List[Entry] = []
    for e in entries:
        name = entry_name(e)
        out.append({name: cat[name]} if name in cat else e)
    return out


def drift(entries: List[Entry], cat: Dict[str, dict]) -> List[str]:
    """Catalog servers whose inline copy is missing (referenced by name) or differs from the catalog."""
    return [entry_name(e) for e in entries
            if entry_name(e) in cat and (not isinstance(e, dict) or e[entry_name(e)] != cat[entry_name(e)])]


def agent_files() -> List[str]:
    return sorted(glob.glob(os.path.join(paths.REPO, ".claude", "agents", "**", "*.md"), recursive=True))


def sync(dry_run: bool = False) -> List[str]:
    """Re-render inline servers in every agent file; return the files that changed (or would change)."""
    from .doctor import _as_list
    cat = catalog()
    changed = []
    for f in agent_files():
        entries = _as_list(frontmatter.read(f).get("mcpServers"))
        if entries and drift(entries, cat):
            changed.append(f)
            if not dry_run:
                frontmatter.update_file(f, {"mcpServers": render(entries, cat)})
    return changed
