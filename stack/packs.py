"""Install packs: named groups of skills (and agents) that can be installed or enabled selectively.

config/packs.json:
    {"packs": {"<pack>": {"description": str, "requires": [pack], "skills": [name], "agents": [name]}},
     "granular_listing": "name-only" | "on"}

* ``core`` holds the protocol, orchestration, research, quality and meta skills plus every agent that
  is not a domain specialist; everything requires it.
* Domain packs hold a hub skill, its granular skills and the domain expert agent.
* Project scope: ``stack packs apply --only rust,quantum`` writes ``skillOverrides`` to
  ``.claude/settings.local.json`` (gitignored): skills of disabled packs -> "off"; granular skills of
  enabled packs -> "name-only" (listed by name to keep every session's context lean; hubs and the agents'
  preloads still carry the full text).
* User scope: ``./install.sh --user --packs rust,quantum`` links only those packs (plus requirements).
"""
from __future__ import annotations

import json
import os
from typing import Dict, Iterable, List, Optional, Set

from . import paths

CONFIG = os.path.join(paths.CONFIG_DIR, "packs.json")
LOCAL_SETTINGS = os.path.join(paths.REPO, ".claude", "settings.local.json")


def load() -> dict:
    with open(CONFIG, encoding="utf-8") as fh:
        return json.load(fh)


def resolve(selected: Iterable[str], cfg: Optional[dict] = None) -> List[str]:
    """Selected packs plus their transitive requirements (core always included)."""
    cfg = cfg or load()
    packs = cfg["packs"]
    out: List[str] = []

    def visit(p: str) -> None:
        if p in out:
            return
        if p not in packs:
            raise ValueError("unknown pack %r (known: %s)" % (p, ", ".join(sorted(packs))))
        for r in packs[p].get("requires", []):
            visit(r)
        out.append(p)

    visit("core")
    for p in selected:
        if p == "all":
            for q in packs:
                visit(q)
        else:
            visit(p)
    return out


def skills_of(pack_names: Iterable[str], cfg: Optional[dict] = None) -> Set[str]:
    cfg = cfg or load()
    return {s for p in pack_names for s in cfg["packs"][p].get("skills", [])}


def agents_of(pack_names: Iterable[str], cfg: Optional[dict] = None) -> Set[str]:
    cfg = cfg or load()
    return {a for p in pack_names for a in cfg["packs"][p].get("agents", [])}


def hubs(cfg: Optional[dict] = None) -> Set[str]:
    cfg = cfg or load()
    return {p.get("hub") for p in cfg["packs"].values() if p.get("hub")}


def granular(cfg: Optional[dict] = None) -> Set[str]:
    """Skills that are neither hubs nor preloaded by any agent: candidates for name-only listing."""
    from . import doctor, frontmatter
    cfg = cfg or load()
    preloaded: Set[str] = set()
    for f in paths.all_agent_files():
        try:
            preloaded |= set(doctor._as_list(frontmatter.read(f).get("skills")))
        except Exception:
            continue
    all_skills = {s for p in cfg["packs"].values() for s in p.get("skills", [])}
    return all_skills - preloaded - hubs(cfg)


def overrides(enabled: Iterable[str], cfg: Optional[dict] = None) -> Dict[str, str]:
    cfg = cfg or load()
    on = skills_of(resolve(enabled, cfg), cfg)
    every = skills_of(cfg["packs"].keys(), cfg)
    out = {s: "off" for s in sorted(every - on)}
    if cfg.get("granular_listing", "name-only") == "name-only":
        for s in sorted(granular(cfg) & on):
            out[s] = "name-only"
    return out


def apply_project(enabled: Iterable[str], dry_run: bool = False) -> Dict[str, str]:
    cfg = load()
    ov = overrides(enabled, cfg)
    try:
        with open(LOCAL_SETTINGS, encoding="utf-8") as fh:
            local = json.load(fh)
    except (OSError, ValueError):
        local = {}
    managed = skills_of(cfg["packs"].keys(), cfg)
    keep = {k: v for k, v in (local.get("skillOverrides") or {}).items() if k not in managed}
    keep.update(ov)
    local["skillOverrides"] = keep
    local["stackPacks"] = resolve(enabled, cfg)  # informational: what was applied
    if not dry_run:
        tmp = LOCAL_SETTINGS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(local, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, LOCAL_SETTINGS)
    return ov
