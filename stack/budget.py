"""Global token budgets: whole delegation tree, per session and per user prompt.

Scopes and limits (config/policy.json -> token_budget):

    session  min_global_tokens  soft_global_tokens  max_global_tokens
    prompt   min_prompt_tokens  soft_prompt_tokens  max_prompt_tokens

* below ``min``   -- never throttled; a demanding task is entitled to at least this much;
* ``soft``        -- agents are told to converge: no new exploratory branches, finish and verify;
* ``max``         -- the pre-agent hook denies new spawns (except the finishing set) and tells
                     the caller to wrap up with what it has.

Usage is summed over the main transcript and every subagent transcript of the
session (``<session>/subagents/**/agent-*.jsonl``), scanned *incrementally*: a
state file remembers each file's byte offset, so a hook call only reads what was
appended since the previous call.  A response is a unique ``message.id``; its
input side (input + cache creation + cache read) is counted once and its output
side grows to max(reported, content-length estimate) because sidechain records
often carry streaming placeholders.  Each response is attributed to the most
recent ``promptId`` seen in its file (only user records carry it).
"""
from __future__ import annotations

import fcntl
import glob
import json
import math
import os
import time
from typing import Dict, Optional, Tuple

from . import paths

CHARS_PER_TOKEN = 3.6
FIELDS = ("input", "cache_creation", "cache_read", "output")

DEFAULTS = {
    "cache_read_weight": 1.0,
    "min_global_tokens": 400_000_000,
    "soft_global_tokens": 1_200_000_000,
    "max_global_tokens": 1_600_000_000,
    "min_prompt_tokens": 30_000_000,
    "soft_prompt_tokens": 90_000_000,
    "max_prompt_tokens": 120_000_000,
    "finishing_agents": ["file-summarizer", "quality-control", "validator", "source-summarizer"],
}


def policy() -> dict:
    try:
        with open(os.path.join(paths.CONFIG_DIR, "policy.json"), encoding="utf-8") as fh:
            tb = json.load(fh).get("token_budget", {})
    except (OSError, ValueError):
        tb = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in tb.items() if not k.startswith("_")})
    return out


def _zero() -> Dict[str, float]:
    return {k: 0 for k in FIELDS}


def effective(t: Dict[str, float], cache_read_weight: float) -> int:
    return int(t["input"] + t["cache_creation"] + t["output"] + cache_read_weight * t["cache_read"])


def _content_chars(block: dict) -> int:
    t = block.get("type")
    if t == "text":
        return len(block.get("text") or "")
    if t == "thinking":
        return len(block.get("thinking") or "")
    if t == "tool_use":
        return len(json.dumps(block.get("input") or {}, separators=(",", ":")))
    return 0


def _state_path(session_id: str) -> str:
    d = os.path.join(paths.data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.usage.json" % session_id)


def _session_files(transcript_path: str):
    files = [transcript_path] if os.path.isfile(transcript_path) else []
    sdir = transcript_path[: -len(".jsonl")] if transcript_path.endswith(".jsonl") else transcript_path
    files += sorted(glob.glob(os.path.join(sdir, "subagents", "**", "agent-*.jsonl"), recursive=True))
    return files


def _add(bucket: Dict[str, float], field: str, n: float) -> None:
    bucket[field] = bucket.get(field, 0) + n


def _scan_file(path: str, fst: dict, totals: Dict[str, float], prompts: Dict[str, Dict[str, float]]) -> None:
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    off = fst.get("offset", 0)
    if size < off:  # truncated/rotated: start over for this file (rare)
        fst.clear()
        off = 0
    if size == off:
        return
    with open(path, "rb") as fh:
        fh.seek(off)
        chunk = fh.read(size - off)
    end = chunk.rfind(b"\n")
    if end < 0:
        return  # no complete line yet
    fst["offset"] = off + end + 1
    for raw in chunk[: end + 1].splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if row.get("promptId"):
            fst["prompt"] = row["promptId"]
        if row.get("type") != "assistant":
            continue
        m = row.get("message") or {}
        mid = m.get("id") or row.get("requestId") or row.get("uuid")
        u = m.get("usage") or {}
        pid = fst.get("prompt") or "unknown"
        pb = prompts.setdefault(pid, _zero())
        if mid != fst.get("mid"):
            fst.update(mid=mid, out=0, chars=0)
            for field, key in (("input", "input_tokens"), ("cache_creation", "cache_creation_input_tokens"),
                               ("cache_read", "cache_read_input_tokens")):
                n = u.get(key) or 0
                _add(totals, field, n)
                _add(pb, field, n)
        for b in m.get("content") or []:
            if isinstance(b, dict):
                fst["chars"] = fst.get("chars", 0) + _content_chars(b)
        out = max(u.get("output_tokens") or 0, int(math.ceil(fst.get("chars", 0) / CHARS_PER_TOKEN)))
        delta = out - fst.get("out", 0)
        if delta > 0:
            fst["out"] = out
            _add(totals, "output", delta)
            _add(pb, "output", delta)


def session_usage(session_id: str, transcript_path: Optional[str]) -> dict:
    """Incrementally update and return {'session': totals, 'prompts': {id: totals}}."""
    path = _state_path(session_id or "unknown")
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = {"files": {}, "session": _zero(), "prompts": {}}
        if transcript_path:
            for f in _session_files(transcript_path):
                _scan_file(f, st["files"].setdefault(f, {}), st["session"], st["prompts"])
        st["updated_at"] = time.time()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        os.replace(tmp, path)
    return st


def learned_limits() -> dict:
    """Raise-only overrides learned from history (written by `stack learn update`)."""
    try:
        with open(os.path.join(paths.data_dir(), "budgets.json"), encoding="utf-8") as fh:
            return (json.load(fh).get("_global") or {}).get("applied", {})
    except (OSError, ValueError):
        return {}


def limits(pol: Optional[dict] = None) -> dict:
    pol = pol or policy()
    out = {k: int(pol[k]) for k in DEFAULTS if k.endswith("_tokens")}
    for k, v in learned_limits().items():
        if k in out and isinstance(v, (int, float)) and v > out[k]:
            out[k] = int(v)
    return out


def level(used: int, lo: int, soft: int, hi: int) -> str:
    if used < lo:
        return "ok"
    if used >= hi:
        return "hard"
    if used >= soft:
        return "soft"
    return "ok"


def status(session_id: str, transcript_path: Optional[str], prompt_id: Optional[str]) -> dict:
    pol = policy()
    lim = limits(pol)
    st = session_usage(session_id, transcript_path)
    w = float(pol["cache_read_weight"])
    s_used = effective(st["session"], w)
    p_tot = st["prompts"].get(prompt_id or "", None)
    p_used = effective(p_tot, w) if p_tot else 0
    s_lvl = level(s_used, lim["min_global_tokens"], lim["soft_global_tokens"], lim["max_global_tokens"])
    p_lvl = level(p_used, lim["min_prompt_tokens"], lim["soft_prompt_tokens"], lim["max_prompt_tokens"])
    order = {"ok": 0, "soft": 1, "hard": 2}
    worst = max((s_lvl, p_lvl), key=lambda x: order[x])
    return {"session_tokens": s_used, "prompt_tokens": p_used, "session_level": s_lvl, "prompt_level": p_lvl,
            "level": worst, "limits": lim, "finishing_agents": pol["finishing_agents"]}


def fmt(n: int) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= div:
            return "%.3g%s" % (n / div, unit)
    return str(n)
