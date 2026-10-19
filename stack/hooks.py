"""Claude Code hook entry points (``bin/stack hook <name>``).

Every handler reads the hook JSON from stdin and must never break the session:
on any internal error it exits 0 silently (fail-open), except the depth guard,
which only *denies* when it is certain a limit is exceeded.

Handlers return the hook JSON (or None); ``main`` prints it for command hooks and
``run_handler`` returns it to in-process callers such as ``stack_sdk``.

pre-agent      PreToolUse on Agent|Task.  Computes the child's depth from the
               native spawnDepth of the calling agent, denies spawns beyond
               CLAUDE_STACK_MAX_DEPTH or the per-session spawn budget, and
               prepends a one-line <stack-context> header to the child's prompt
               so every agent knows its depth, its parent and its budget.
subagent-stop  SubagentStop (async).  Re-ingests the session's observations and
               periodically refreshes posteriors (debounced, lock-protected).
session-start  SessionStart.  Adds a short status line (missing keys, recent
               learned changes) as context.
session-end    SessionEnd.  Detaches a background `learn run` so the 1.5 s
               SessionEnd budget is never at risk.
"""
from __future__ import annotations

import fcntl
import glob
import json
import os
import subprocess
import sys
import time
from typing import Optional

from . import paths

AGENT_TOOLS = ("Agent", "Task")


def _log_error(where: str, exc: BaseException) -> None:
    try:
        with open(os.path.join(paths.data_dir(), "hook-errors.log"), "a") as fh:
            fh.write("%s %s %r\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), where, exc))
    except OSError:
        pass


def _read_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except (ValueError, OSError):
        return {}


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def max_depth() -> int:
    for var in ("CLAUDE_STACK_MAX_DEPTH", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"):
        v = os.environ.get(var, "").strip()
        if v.isdigit():
            return int(v)
    return 8


def _policy() -> dict:
    p = os.path.join(paths.CONFIG_DIR, "policy.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def session_dir(transcript_path: Optional[str]) -> Optional[str]:
    if not transcript_path or not transcript_path.endswith(".jsonl"):
        return None
    return transcript_path[: -len(".jsonl")]


def depth_of(agent_id: Optional[str], transcript_path: Optional[str]) -> int:
    """Depth of the agent making the call: 0 for the main thread.

    Claude Code writes agent-<id>.meta.json with a native ``spawnDepth`` next
    to each subagent transcript; we trust it when present.
    """
    if not agent_id:
        return 0
    sdir = session_dir(transcript_path)
    if sdir:
        hits = glob.glob(os.path.join(sdir, "subagents", "**", "agent-%s.meta.json" % agent_id), recursive=True)
        for h in hits:
            try:
                with open(h, encoding="utf-8") as fh:
                    d = json.load(fh).get("spawnDepth")
                if isinstance(d, int):
                    return d
            except (OSError, ValueError):
                pass
    return 1  # inside some subagent, depth unknown: assume the shallowest


def _state_path(session_id: str) -> str:
    d = os.path.join(paths.data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.json" % (session_id or "unknown"))


def _bump_spawn_count(session_id: str, child_depth: int, child_type: str) -> int:
    path = _state_path(session_id)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = {"spawns": 0, "by_depth": {}, "by_type": {}, "max_depth_seen": 0}
        st["spawns"] += 1
        st["by_depth"][str(child_depth)] = st["by_depth"].get(str(child_depth), 0) + 1
        st["by_type"][child_type] = st["by_type"].get(child_type, 0) + 1
        st["max_depth_seen"] = max(st.get("max_depth_seen", 0), child_depth)
        st["updated_at"] = time.time()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        os.replace(tmp, path)
        return st["spawns"]


def _spawn_rule_violation(pol: dict, parent: str, child: str, child_depth: int, limit: int) -> Optional[str]:
    rules = pol.get("spawn_rules") or {}
    groups = rules.get("groups") or {}

    def expand(names):
        out = set()
        for n in names:
            out |= set(groups.get(n[1:], [])) if n.startswith("@") else {n}
        return out

    allowed = (rules.get("callers") or {}).get(parent)
    if allowed is not None and "*" not in allowed and child not in expand(allowed):
        return ("Spawn policy: %s may delegate only to %s (config/policy.json spawn_rules). "
                "Route %s through your caller instead, or handle it yourself." % (parent, ", ".join(allowed), child))
    orch = expand(["@orchestration"])
    deep = int(rules.get("orchestrators_until_depth", limit) or limit)
    if child in orch and child_depth > deep:
        return ("Spawn policy: orchestration agents (%s) are not started below depth %d; at depth %d spawn leaves "
                "(researchers, testers, summarizers) or do the work yourself." % (child, deep, child_depth))
    return None


def _apply_runtime_rules(tool_input: dict, pol: dict) -> None:
    """Tier enforcement and foreground forcing on the rewritten Agent call.

    * Tiers are authoritative: a per-call ``model``/``effort`` would override the agent's tier
      model and learned effort, so they are stripped (config/policy.json enforce_tiers).
    * Under the Agent SDK subagents default to the background; the SDK runner sets
      CLAUDE_STACK_FOREGROUND=1 so parents always receive results before continuing.
      (Interactive fork mode manages this itself, so the flag is not set there.)
    """
    if pol.get("enforce_tiers", True):
        tool_input.pop("model", None)
        tool_input.pop("effort", None)
    if os.environ.get("CLAUDE_STACK_FOREGROUND") == "1":
        tool_input["run_in_background"] = False


def pre_agent(inp: dict) -> Optional[dict]:
    if inp.get("tool_name") not in AGENT_TOOLS:
        return None
    tool_input = dict(inp.get("tool_input") or {})
    parent_type = inp.get("agent_type") or os.environ.get("CLAUDE_STACK_MAIN_AGENT") or "main"
    parent_depth = depth_of(inp.get("agent_id"), inp.get("transcript_path"))
    child_depth = parent_depth + 1
    child_type = tool_input.get("subagent_type") or "general-purpose"
    limit = max_depth()
    pol = _policy()

    if child_depth > limit:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Stack depth limit reached: %s is at depth %d and the maximum is %d. "
                "Do this part yourself, or return it to your caller as an open doubt." % (parent_type, parent_depth, limit))}}

    # Per-level spawn rules. Agent(type) allowlists in a subagent's `tools` are ignored by
    # Claude Code, so the caller -> allowed-children table is enforced here.
    deny = _spawn_rule_violation(pol, parent_type, child_type, child_depth, limit)
    if deny:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": deny}}

    # Whole-tree token budgets (session and current prompt).
    bst = None
    try:
        from . import budget as _b
        bst = _b.status(inp.get("session_id") or "unknown", inp.get("transcript_path"), inp.get("prompt_id"))
    except Exception as exc:  # budget accounting must never block work by crashing
        _log_error("budget", exc)
    if bst and bst["level"] == "hard" and child_type not in bst["finishing_agents"]:
        from . import budget as _b
        lim = bst["limits"]
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Token budget exhausted (session %s of %s, this prompt %s of %s). Do not start new work: "
                "finish with what you have, offload full output to a file and return your Result with the gaps as "
                "Open doubts. Only %s may still be spawned." % (
                    _b.fmt(bst["session_tokens"]), _b.fmt(lim["max_global_tokens"]),
                    _b.fmt(bst["prompt_tokens"]), _b.fmt(lim["max_prompt_tokens"]),
                    ", ".join(bst["finishing_agents"])))}}

    budget = int(pol.get("max_spawns_per_session", 0) or 0)
    count = _bump_spawn_count(inp.get("session_id") or "unknown", child_depth, child_type)
    if budget and count > budget:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Stack spawn budget exhausted (%d subagents this session, budget %d). "
                "Finish with what you have or ask the user to raise max_spawns_per_session in config/policy.json." % (count - 1, budget))}}

    if (not pol.get("inject_context", True) or not isinstance(tool_input.get("prompt"), str)
            or tool_input["prompt"].lstrip().startswith("<stack-context")):
        before = dict(tool_input)
        _apply_runtime_rules(tool_input, pol)
        if tool_input == before:
            return None
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                       "updatedInput": tool_input}}
    budget_attrs = ""
    if bst:
        from . import budget as _b
        lim = bst["limits"]
        budget_attrs = (' budget="%s" prompt_tokens="%s/%s" session_tokens="%s/%s"'
                        % (bst["level"], _b.fmt(bst["prompt_tokens"]), _b.fmt(lim["max_prompt_tokens"]),
                           _b.fmt(bst["session_tokens"]), _b.fmt(lim["max_global_tokens"])))
    header = ('<stack-context depth="%d" max_depth="%d" parent="%s" remaining_depth="%d" '
              'spawns_this_session="%d"%s out_dir=".stack/out/%s"/>\n'
              % (child_depth, limit, parent_type, limit - child_depth, count, budget_attrs, child_type))
    tool_input["prompt"] = header + tool_input["prompt"]
    _apply_runtime_rules(tool_input, pol)
    note = _main_effort_drift(inp)
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                  "updatedInput": tool_input}}
    if note:
        out["hookSpecificOutput"]["additionalContext"] = note
    return out


def _main_effort_drift(inp: dict) -> Optional[str]:
    """Hooks cannot block /effort, so flag main-thread effort drift on its next delegation."""
    main = _main_agent()
    if not main or inp.get("agent_id"):
        return None
    eff = inp.get("effort")
    level = eff.get("level") if isinstance(eff, dict) else None
    try:
        from . import tiers
        want = tiers.main_thread(main)["effort"]
    except Exception:
        return None
    if level and want and level != want:
        return ("Stack policy: the %s main thread must run at effort %s (now %s). Run /effort %s."
                % (main, want, level, want))
    return None


def _detach(args) -> None:
    log = open(os.path.join(paths.data_dir(), "learn.log"), "a")
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                     start_new_session=True, close_fds=True, cwd=paths.REPO)


def _stack_cmd(*args: str):
    return [sys.executable, "-m", "stack.cli"] + list(args)


def _record_stop(inp: dict) -> None:
    """Append the authoritative per-agent facts only this payload carries (effort in effect)."""
    sid = inp.get("session_id")
    if not sid or not inp.get("agent_id"):
        return
    eff = inp.get("effort")
    level = eff.get("level") if isinstance(eff, dict) else (eff if isinstance(eff, str) else None)
    d = os.path.join(paths.data_dir(), "stops")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "%s.jsonl" % sid), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"agent_id": inp.get("agent_id"), "agent_type": inp.get("agent_type") or "",
                             "effort": level, "ts": time.time()}) + "\n")


def subagent_stop(inp: dict) -> Optional[dict]:
    _record_stop(inp)
    tp = inp.get("transcript_path")
    if not tp:
        return None
    from .learn import engine
    lockp = os.path.join(paths.data_dir(), "learn.lock")
    with open(lockp, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None  # another ingest is running; it will see this agent too
        # Debounce: a 500-agent workflow must not re-parse the session 500 times.
        # SessionEnd always does a final full ingest, so skipping here loses nothing.
        ingest_stamp = os.path.join(paths.data_dir(), "last_ingest")
        debounce = float(_policy().get("ingest_debounce_seconds", 60))
        if os.path.exists(ingest_stamp) and time.time() - os.path.getmtime(ingest_stamp) < debounce:
            return None
        engine.ingest_transcript(tp)
        open(ingest_stamp, "w").close()
        stamp = os.path.join(paths.data_dir(), "last_update")
        interval = float(_policy().get("midsession_update_minutes", 30)) * 60
        last = os.path.getmtime(stamp) if os.path.exists(stamp) else 0
        if time.time() - last > interval:
            engine.update()
            if engine.load_config().get("auto_apply", True):
                engine.apply()
            open(stamp, "w").close()
    return None


def session_end(inp: dict) -> Optional[dict]:
    tp = inp.get("transcript_path")
    if tp:
        _detach(_stack_cmd("learn", "run", "--transcript", tp))
    return None


def _missing_keys(want: Optional[list] = None) -> list:
    from . import envfile
    if want is None:
        want = _policy().get("expected_keys", [])
    return envfile.missing(want)


def session_start(inp: dict) -> Optional[dict]:
    parts = ["Agent stack active: max delegation depth %d." % max_depth()]
    miss = _missing_keys()
    if miss:
        parts.append("Missing keys in ~/.claude/stack.env: %s (those MCP servers run anonymous or fail)." % ", ".join(miss))
    ch = os.path.join(paths.data_dir(), "changes.jsonl")
    if os.path.exists(ch) and time.time() - os.path.getmtime(ch) < 7 * 86400:
        try:
            with open(ch, encoding="utf-8") as fh:
                last = [json.loads(x) for x in fh.readlines()[-5:]]
            parts.append("Recently self-tuned: " + "; ".join(
                "%s %s" % (c["agent"], ",".join("%s=%s" % kv for kv in c["updates"].items())) for c in last))
        except (OSError, ValueError, KeyError):
            pass
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": " ".join(parts)}}


def prompt_submit(inp: dict) -> Optional[dict]:
    """UserPromptSubmit: tell the main thread where the session's token budget stands."""
    from . import budget as _b
    bst = _b.status(inp.get("session_id") or "unknown", inp.get("transcript_path"), inp.get("prompt_id"))
    lim = bst["limits"]
    msg = ("Token budget: session %s used of %s (soft %s); this prompt may use up to %s (soft %s, guaranteed %s). "
           "Optimise for context usage, not speed." % (
               _b.fmt(bst["session_tokens"]), _b.fmt(lim["max_global_tokens"]), _b.fmt(lim["soft_global_tokens"]),
               _b.fmt(lim["max_prompt_tokens"]), _b.fmt(lim["soft_prompt_tokens"]), _b.fmt(lim["min_prompt_tokens"])))
    if bst["session_level"] != "ok":
        msg += " SESSION BUDGET %s: converge, do not open new branches." % bst["session_level"].upper()
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}


def _main_agent() -> Optional[str]:
    a = os.environ.get("CLAUDE_STACK_MAIN_AGENT")
    return a if a and a != "main" else None


def model_switch(inp: dict) -> Optional[dict]:
    """PreModelSwitch: keep the main thread on its agent's tier model; only tier models anywhere."""
    from . import tiers
    to = str(inp.get("to_model") or inp.get("requested_model") or "")
    allowed = tiers.allowed_models()
    if os.environ.get("CLAUDE_STACK_ALLOW_MODEL_SWITCH") == "1":
        return None
    main = _main_agent()
    want = tiers.main_thread(main)["model"] if main else None
    ok = (to == want) if want else any(to == m or to.startswith(m + "-") or to.startswith(m + "[") for m in allowed)
    if ok:
        return None
    reason = ("Model switch to %r blocked: %s. Change the tier in config/models.json (bin/stack agents set %s tier=...) "
              "or set CLAUDE_STACK_ALLOW_MODEL_SWITCH=1 for this session." % (
                  to, ("the main thread runs %s on its tier model %s" % (main, want)) if want else
                  ("only the tier models %s are allowed" % ", ".join(allowed)), main or "<agent>"))
    return {"_exit": 2, "_stderr": reason}


HANDLERS = {
    "model-switch": model_switch,
    "prompt-submit": prompt_submit,
    "pre-agent": pre_agent,
    "subagent-stop": subagent_stop,
    "session-end": session_end,
    "session-start": session_start,
}


def main(name: str) -> int:
    inp = _read_stdin()
    fn = HANDLERS.get(name)
    if not fn:
        sys.stderr.write("unknown hook %s\n" % name)
        return 0
    try:
        out = fn(inp)
    except Exception as exc:  # fail open: a broken hook must never wedge a session
        _log_error(name, exc)
        return 0
    if out and "_exit" in out:
        sys.stderr.write(out.get("_stderr", "") + "\n")
        return int(out["_exit"])
    if out:
        _emit(out)
    return 0


def run_handler(name: str, inp: dict) -> Optional[dict]:
    """In-process entry point (used by the Agent SDK hook callbacks). Fails open like main()."""
    fn = HANDLERS.get(name)
    if not fn:
        return None
    try:
        return fn(inp)
    except Exception as exc:
        _log_error(name, exc)
        return None
