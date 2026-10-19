"""Load this stack's .claude/agents/**/*.md files as Claude Agent SDK AgentDefinitions.

The markdown files are the single source of truth for both runtimes:

* interactive Claude Code (and SDK sessions whose ``setting_sources`` include the
  project) read them from disk;
* SDK sessions running in *another* directory get them programmatically through
  ``ClaudeAgentOptions.agents`` via :func:`load_agents`.

Field mapping is driven by the installed SDK's ``AgentDefinition`` dataclass, so
frontmatter keys the SDK does not model (``color``; and ``hooks``, ``isolation``,
``autoCompactWindow``, ``omitClaudeMd`` if ever used) are reported as dropped
rather than passed through and rejected.
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import AgentDefinition

from stack import doctor, frontmatter, paths, tiers

SDK_FIELDS = {f.name for f in dataclasses.fields(AgentDefinition)}
LIST_FIELDS = {"tools", "disallowedTools", "skills", "mcpServers"}
INT_FIELDS = {"maxTurns"}
BOOL_FIELDS = {"background"}


@dataclass
class LoadedAgent:
    name: str
    path: str
    group: str
    definition: AgentDefinition
    dropped: dict[str, Any] = field(default_factory=dict)


def _convert(key: str, value: Any) -> Any:
    if key in LIST_FIELDS:
        return doctor._as_list(value)  # handles "A, B, Agent(x, y)" and YAML lists
    if key in INT_FIELDS:
        return int(value)
    if key in BOOL_FIELDS:
        return str(value).strip().lower() in ("true", "yes", "1")
    return value


def load_agent(path: str, use_tiers: bool = True) -> LoadedAgent:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    fm = frontmatter.parse(text)
    _, body = frontmatter.split(text)
    name = str(fm["name"])
    kwargs: dict[str, Any] = {"description": str(fm.get("description", "")), "prompt": body.strip()}
    dropped: dict[str, Any] = {}
    for key, value in fm.items():
        if key in ("name", "description"):
            continue
        if key in SDK_FIELDS:
            if value not in (None, "", []):
                kwargs[key] = _convert(key, value)
        else:
            dropped[key] = value
    if use_tiers:
        model = tiers.model_for(name)
        if model:
            kwargs["model"] = model  # honours ADVANCED_MODEL/MEDIUM_MODEL/LOW_MODEL env overrides
    group = os.path.relpath(os.path.dirname(path), os.path.join(paths.REPO, ".claude", "agents"))
    return LoadedAgent(name=name, path=path, group="" if group == "." else group,
                       definition=AgentDefinition(**kwargs), dropped=dropped)


def load_all(use_tiers: bool = True) -> dict[str, LoadedAgent]:
    out: dict[str, LoadedAgent] = {}
    for path in paths.all_agent_files():
        a = load_agent(path, use_tiers=use_tiers)
        if a.name in out:
            raise ValueError("duplicate agent name %s (%s, %s)" % (a.name, out[a.name].path, path))
        out[a.name] = a
    return out


def load_agents(use_tiers: bool = True) -> dict[str, AgentDefinition]:
    """{name: AgentDefinition} ready for ``ClaudeAgentOptions(agents=...)``."""
    return {name: a.definition for name, a in load_all(use_tiers).items()}
