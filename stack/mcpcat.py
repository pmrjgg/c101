"""The stack's MCP server catalog (config/mcp.servers.json) and its inline copies in agent frontmatter.

Servers are lazy: instead of living in .mcp.json (connected for the whole session and visible to the main
conversation), each one is defined inline in the ``mcpServers`` of the agents that use it. Claude Code
connects an inline server when such a subagent starts and disconnects it when the subagent finishes.
``sync`` re-renders those inline copies from the catalog; ``drift`` reports copies that differ.

A *shared* server (catalog ``shared``: server -> owner agent) is inline only in its owner, a main-thread agent,
so it connects for sessions that run the owner as the main thread; every other agent names it and shares
that one connection (one process per session).
"""
from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Union

from . import frontmatter, paths

CATALOG = os.path.join(paths.CONFIG_DIR, "mcp.servers.json")
Entry = Union[str, dict]


def _load(path: Optional[str] = None) -> dict:
    try:
        with open(path or CATALOG, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def catalog(path: Optional[str] = None) -> Dict[str, dict]:
    return _load(path).get("servers", {})


def shared(path: Optional[str] = None) -> Dict[str, str]:
    """Shared server -> owner agent."""
    return _load(path).get("shared", {})


def entry_name(e: Entry) -> Optional[str]:
    """Server name of a frontmatter entry: the string itself, or the single key of an inline definition."""
    if isinstance(e, dict):
        return next(iter(e)) if len(e) == 1 else None
    return e


def _inline_here(name: str, agent: Optional[str], owners: Dict[str, str]) -> bool:
    return name not in owners or owners[name] == agent


def render(entries: List[Entry], cat: Dict[str, dict], agent: Optional[str] = None,
           owners: Optional[Dict[str, str]] = None) -> List[Entry]:
    """Inline catalog servers (shared ones only in their owner); keep other entries as they are."""
    owners = owners or {}
    out: List[Entry] = []
    for e in entries:
        name = entry_name(e)
        if name in cat:
            out.append({name: cat[name]} if _inline_here(name, agent, owners) else name)
        else:
            out.append(e)
    return out


def drift(entries: List[Entry], cat: Dict[str, dict], agent: Optional[str] = None,
          owners: Optional[Dict[str, str]] = None) -> List[str]:
    """Catalog servers whose entry is not what ``render`` would write (missing, stale, or wrongly inline)."""
    return [entry_name(e) for e, want in zip(entries, render(entries, cat, agent, owners)) if e != want]


LOOKUP = 'd="${CLAUDE_PROJECT_DIR:-$PWD}"'


def pin_repo(cfg: dict, repo: str) -> dict:
    """The same server config with the launcher lookup fixed to ``repo`` (SDK sessions outside the repo)."""
    return json.loads(json.dumps(cfg).replace(json.dumps(LOOKUP)[1:-1], json.dumps('d="%s"' % repo)[1:-1]))


def agent_files() -> List[str]:
    return sorted(glob.glob(os.path.join(paths.REPO, ".claude", "agents", "**", "*.md"), recursive=True))


def sync(dry_run: bool = False) -> List[str]:
    """Re-render inline servers in every agent file; return the files that changed (or would change)."""
    from .doctor import _as_list
    cat, owners = catalog(), shared()
    changed = []
    for f in agent_files():
        fm = frontmatter.read(f)
        entries, agent = _as_list(fm.get("mcpServers")), str(fm.get("name", ""))
        if entries and drift(entries, cat, agent, owners):
            changed.append(f)
            if not dry_run:
                frontmatter.update_file(f, {"mcpServers": render(entries, cat, agent, owners)})
    return changed
