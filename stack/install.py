"""`bin/stack install` — wire the stack into ~/.claude.

Base install (always, idempotent):
  * ~/.claude/stack            -> symlink to this repo (stable path for user-scope configs)
  * ~/.claude/stack.env        <- created from config/stack.env.example if missing (mode 600)
  * ~/.claude/stack-data/      learning data directory

--user        make agents, skills and workflows available in every project (per-file symlinks
              under ~/.claude/agents/stack/, ~/.claude/skills/<name>, ~/.claude/workflows/),
              register the MCP servers at user scope (via `claude mcp add-json`), and merge env +
              hooks into ~/.claude/settings.json (backup written first).
--main-agent  set "agent": "delegator" in ~/.claude/settings.json so every session's main thread
              is the delegator (undo with --no-main-agent).
--enforce-models  restrict every project to the tier models from ~/.claude/settings.json: availableModels (from
              config/models.json; prefix match outside managed settings), enforceAvailableModels and the
              PreModelSwitch guard (pins a stack main agent to its exact tier model). Works alone (nothing
              else is installed) or with --user. Undo with --no-enforce-models. Exact matching for every
              model needs managed settings: `sudo bin/stack managed-settings --install`.
--packs a,b   with --user: link only these install packs (+ core and requirements); see
              `bin/stack packs list`. Default: all packs.
--dry-run     print what would change.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from typing import List, Optional

from . import paths

HOME = os.path.expanduser("~")
CLAUDE = paths.HOME_CLAUDE
LINK = os.path.join(CLAUDE, "stack")
HOOK_MARK = "/.claude/stack/bin/stack hook"


class Ctx:
    def __init__(self, dry: bool) -> None:
        self.dry = dry
        self.log: List[str] = []

    def do(self, msg: str, fn=None) -> None:
        self.log.append(("would " if self.dry else "") + msg)
        print(("[dry-run] " if self.dry else "") + msg)
        if fn and not self.dry:
            fn()


def _symlink(ctx: Ctx, target: str, link: str) -> None:
    if os.path.islink(link):
        if os.path.realpath(link) == os.path.realpath(target):
            return
        ctx.do("relink %s -> %s" % (link, target), lambda: (os.unlink(link), os.symlink(target, link)))
    elif os.path.exists(link):
        print("skip %s: exists and is not a symlink (move it away to let the stack manage it)" % link)
    else:
        ctx.do("link %s -> %s" % (link, target),
               lambda: (os.makedirs(os.path.dirname(link), exist_ok=True), os.symlink(target, link)))


def base(ctx: Ctx) -> None:
    _symlink(ctx, paths.REPO, LINK)
    env = os.path.join(CLAUDE, "stack.env")
    if not os.path.exists(env):
        def mk():
            shutil.copyfile(os.path.join(paths.CONFIG_DIR, "stack.env.example"), env)
            os.chmod(env, stat.S_IRUSR | stat.S_IWUSR)
        ctx.do("create %s from template (mode 600) — fill in your keys" % env, mk)
    else:
        mode = stat.S_IMODE(os.stat(env).st_mode)
        if mode & 0o077:
            ctx.do("tighten %s permissions to 600" % env, lambda: os.chmod(env, 0o600))
    d = os.path.join(CLAUDE, "stack-data")
    if not os.path.isdir(d):
        ctx.do("create %s" % d, lambda: os.makedirs(d, exist_ok=True))


def link_components(ctx: Ctx, selected: Optional[List[str]] = None) -> None:
    from . import packs as packs_mod
    sel = packs_mod.resolve(selected or ["all"])
    want_skills = packs_mod.skills_of(sel)
    want_agents = packs_mod.agents_of(sel)
    print("packs: %s (%d skills, %d agents)" % (", ".join(sel), len(want_skills), len(want_agents)))
    src_agents = os.path.join(paths.REPO, ".claude", "agents")
    for root, _dirs, files in os.walk(src_agents):
        for f in files:
            if f.endswith(".md") and f[:-3] in want_agents:
                rel = os.path.relpath(os.path.join(root, f), src_agents)
                _symlink(ctx, os.path.join(root, f), os.path.join(CLAUDE, "agents", "stack", rel))
    src_skills = os.path.join(paths.REPO, ".claude", "skills")
    for name in sorted(os.listdir(src_skills)):
        if os.path.isdir(os.path.join(src_skills, name)) and name in want_skills:
            _symlink(ctx, os.path.join(src_skills, name), os.path.join(CLAUDE, "skills", name))
    src_wf = os.path.join(paths.REPO, ".claude", "workflows")
    if os.path.isdir(src_wf):
        for f in sorted(os.listdir(src_wf)):
            if f.endswith(".js"):
                _symlink(ctx, os.path.join(src_wf, f), os.path.join(CLAUDE, "workflows", f))


def _user_mcp_entry(cfg: dict) -> dict:
    """Rewrite project-relative launcher paths to the stable ~/.claude/stack link."""
    s = json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")})
    s = s.replace("${CLAUDE_PROJECT_DIR:-.}", LINK)
    s = s.replace("${CLAUDE_PROJECT_DIR:-$HOME/.claude/stack}", LINK)
    return json.loads(s)


def register_mcp(ctx: Ctx) -> None:
    claude = shutil.which("claude")
    with open(os.path.join(paths.REPO, ".mcp.json"), encoding="utf-8") as fh:
        servers = json.load(fh)["mcpServers"]
    from . import mcpcat
    lazy = sorted(mcpcat.catalog())
    if lazy:
        print("MCP servers %s load lazily inside the agents that use them (config/mcp.servers.json); nothing to "
              "register for them. If an earlier install registered them at user scope, remove those so they stop "
              "connecting for every session: claude mcp remove --scope user <name>" % ", ".join(lazy))
    for name, cfg in servers.items():
        entry = json.dumps(_user_mcp_entry(cfg))
        if not claude:
            print("claude CLI not on PATH; add manually: claude mcp add-json --scope user %s '%s'" % (name, entry))
            continue

        def add(name=name, entry=entry):
            subprocess.run([claude, "mcp", "remove", "--scope", "user", name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            r = subprocess.run([claude, "mcp", "add-json", "--scope", "user", name, entry],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print("  failed to register %s: %s" % (name, (r.stderr or r.stdout).strip()))
        ctx.do("register MCP server %s at user scope" % name, add)


def _load_settings(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_settings(ctx: Ctx, path: str, data: dict, why: str) -> None:
    def w():
        if os.path.exists(path):
            shutil.copyfile(path, "%s.bak-%d" % (path, int(time.time())))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    ctx.do("update %s (%s; backup kept)" % (path, why), w)


def merge_settings(ctx: Ctx, enforce_models: bool = False) -> None:
    user_path = os.path.join(CLAUDE, "settings.json")
    user = _load_settings(user_path)
    with open(os.path.join(paths.REPO, ".claude", "settings.json"), encoding="utf-8") as fh:
        proj = json.load(fh)
    env = user.setdefault("env", {})
    for k, v in proj.get("env", {}).items():
        env.setdefault(k, v)
    if enforce_models:
        for k in ("availableModels", "enforceAvailableModels"):  # availableModelsMatch: managed settings only
            if k in proj:
                user[k] = proj[k]
    hooks = user.setdefault("hooks", {})
    for event, groups in proj.get("hooks", {}).items():
        if event == "PreModelSwitch" and not enforce_models:
            continue
        cur = hooks.setdefault(event, [])
        # drop previous stack hooks, then add fresh ones pointing at ~/.claude/stack
        cur[:] = [g for g in cur if not any(HOOK_MARK in h.get("command", "") for h in g.get("hooks", []))]
        for g in groups:
            g2 = json.loads(json.dumps(g))
            for h in g2.get("hooks", []):
                h["command"] = h.get("command", "").replace('"$CLAUDE_PROJECT_DIR"/bin/stack',
                                                            '"$HOME"/.claude/stack/bin/stack')
            cur.append(g2)
    _write_settings(ctx, user_path, user, "stack env + hooks")


MODEL_HOOK = '"$HOME"/.claude/stack/bin/stack hook model-switch'


def enforce_models_global(ctx: Ctx, on: bool) -> None:
    """Restrict every project to the tier models from ~/.claude/settings.json, without installing anything else.

    Writes availableModels (rendered from config/models.json), enforceAvailableModels and the PreModelSwitch
    guard. availableModels matches by prefix outside managed settings and enforceAvailableModels is read only while
    no managed settings exist; the guard blocks non-tier switches and pins a stack main agent to its exact tier
    model. availableModelsMatch is dropped: Claude Code ignores it outside managed settings.
    """
    from . import tiers
    user_path = os.path.join(CLAUDE, "settings.json")
    user = _load_settings(user_path)
    groups = user.setdefault("hooks", {}).setdefault("PreModelSwitch", [])
    groups[:] = [g for g in groups if not any(MODEL_HOOK in h.get("command", "") for h in g.get("hooks", []))]
    user.pop("availableModelsMatch", None)
    if on:
        user["availableModels"] = sorted(tiers.allowed_models())
        user["enforceAvailableModels"] = True
        groups.append({"hooks": [{"type": "command", "command": MODEL_HOOK, "timeout": 10}]})
    else:
        user.pop("availableModels", None)
        user.pop("enforceAvailableModels", None)
    if not groups:
        user["hooks"].pop("PreModelSwitch")
    if not user["hooks"]:
        user.pop("hooks")
    _write_settings(ctx, user_path, user, "tier-model enforcement %s" % ("on" if on else "off"))


def set_main_agent(ctx: Ctx, on: bool) -> None:
    user_path = os.path.join(CLAUDE, "settings.json")
    user = _load_settings(user_path)
    if on:
        user["agent"] = "delegator"
    else:
        user.pop("agent", None)
    _write_settings(ctx, user_path, user, "main agent %s" % ("delegator" if on else "default"))


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="stack install")
    p.add_argument("--user", action="store_true")
    p.add_argument("--main-agent", action="store_true")
    p.add_argument("--no-main-agent", action="store_true")
    p.add_argument("--enforce-models", action="store_true")
    p.add_argument("--no-enforce-models", action="store_true")
    p.add_argument("--packs", help="comma-separated packs for --user (default: all); core is always included")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    ctx = Ctx(a.dry_run)
    base(ctx)
    if a.user:
        link_components(ctx, [x.strip() for x in a.packs.split(",")] if a.packs else None)
        register_mcp(ctx)
        merge_settings(ctx, enforce_models=a.enforce_models)
    if a.enforce_models or a.no_enforce_models:
        enforce_models_global(ctx, a.enforce_models)
    if a.main_agent or a.no_main_agent:
        set_main_agent(ctx, a.main_agent)
    if not ctx.log:
        print("nothing to do; already installed")
    print("\nnext: fill ~/.claude/stack.env, then `bin/stack keys` and `bin/stack doctor`.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
