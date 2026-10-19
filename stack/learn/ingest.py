"""Turn Claude Code session transcripts into per-agent observations.

Layout (Claude Code 2.1.x, verified on this machine):

    ~/.claude/projects/<project-slug>/<session-id>.jsonl              main thread
    ~/.claude/projects/<project-slug>/<session-id>/subagents/**/agent-<id>.jsonl
    ~/.claude/projects/<project-slug>/<session-id>/subagents/**/agent-<id>.meta.json
        {"agentType": "...", "description": "...", "spawnDepth": 1, ...}

Each API response is written as one JSONL line *per content block*, all sharing
``message.id`` and the same ``usage`` snapshot, so an API response is a unique
``message.id``.  ``maxTurns`` counts *tool-use round trips* (responses that call
at least one tool; parallel calls in one response are one round), recorded as
``tool_rounds``; ``turns`` keeps the raw response count.  Main-thread lines carry final usage (``stop_reason`` set);
sidechain lines are often written from the stream's ``message_start`` snapshot
(``stop_reason`` null, ``output_tokens`` a handful), so output tokens are then
estimated from the content length and flagged ``output_estimated``.  Input-side
counts (input + cache read + cache creation) are complete either way and give
the context-window size of each turn.
"""
from __future__ import annotations

import glob
import json
import math
import os
from collections import Counter
from datetime import datetime
from typing import Dict, Iterable, List, Optional

CHARS_PER_TOKEN = 3.6
AGENT_TOOL_NAMES = ("Agent", "Task")


def _iter_jsonl(path: str) -> Iterable[dict]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _ts(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _content_chars(block: dict) -> int:
    t = block.get("type")
    if t == "text":
        return len(block.get("text") or "")
    if t == "thinking":
        return len(block.get("thinking") or "")
    if t == "tool_use":
        return len(json.dumps(block.get("input") or {}, separators=(",", ":")))
    return 0


def summarize_transcript(path: str) -> Optional[dict]:
    """Aggregate one transcript (main thread or a subagent) into a record."""
    msgs: Dict[str, dict] = {}
    order: List[str] = []
    efforts: Counter = Counter()
    models: Counter = Counter()
    tool_calls = 0
    tool_errors = 0
    agent_spawns: Counter = Counter()
    first_ts = last_ts = None
    max_turns_hit = False
    session_id = agent_id = None

    for row in _iter_jsonl(path):
        t = _ts(row.get("timestamp"))
        if t is not None:
            first_ts = t if first_ts is None else min(first_ts, t)
            last_ts = t if last_ts is None else max(last_ts, t)
        session_id = session_id or row.get("sessionId")
        agent_id = agent_id or row.get("agentId")
        typ = row.get("type")
        if typ == "assistant":
            m = row.get("message") or {}
            mid = m.get("id") or row.get("requestId") or row.get("uuid")
            if mid not in msgs:
                msgs[mid] = {"usage": m.get("usage") or {}, "stop": m.get("stop_reason"), "chars": 0, "tools": 0}
                order.append(mid)
                if row.get("effort"):
                    efforts[row["effort"]] += 1
                if m.get("model"):
                    models[m["model"]] += 1
            rec = msgs[mid]
            u = m.get("usage") or {}
            if (u.get("output_tokens") or 0) >= (rec["usage"].get("output_tokens") or 0):
                rec["usage"] = u
            if m.get("stop_reason"):
                rec["stop"] = m.get("stop_reason")
            for b in m.get("content") or []:
                if isinstance(b, dict):
                    rec["chars"] += _content_chars(b)
                    if b.get("type") == "tool_use":
                        tool_calls += 1
                        rec["tools"] += 1
                        if b.get("name") in AGENT_TOOL_NAMES:
                            inp = b.get("input") or {}
                            agent_spawns[inp.get("subagent_type") or "general-purpose"] += 1
        elif typ == "user":
            content = (row.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                        tool_errors += 1
        elif typ == "system":
            txt = json.dumps(row.get("content") or "").lower()
            if "max turns" in txt or "maxturns" in txt or "max_turns" in txt:
                max_turns_hit = True
        if row.get("subtype") in ("error_max_turns",):
            max_turns_hit = True

    if not order:
        return None

    out_tokens = 0
    out_max_turn = 0
    thinking = 0
    estimated = False
    ctx_peak = 0
    input_total = 0
    for mid in order:
        rec = msgs[mid]
        u = rec["usage"]
        ctx = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + \
              (u.get("cache_creation_input_tokens") or 0)
        ctx_peak = max(ctx_peak, ctx)
        input_total += ctx
        reported = u.get("output_tokens") or 0
        est = int(math.ceil(rec["chars"] / CHARS_PER_TOKEN))
        if rec["stop"] is None and est > reported:
            turn_out = est
            estimated = True
        else:
            turn_out = reported
        out_tokens += turn_out
        out_max_turn = max(out_max_turn, turn_out)
        thinking += ((u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)

    return {
        "session_id": session_id,
        "agent_id": agent_id,
        # maxTurns counts tool-use round trips (responses that call tools), not API responses.
        "tool_rounds": sum(1 for mid in order if msgs[mid]["tools"] > 0),
        "turns": len(order),
        "output_tokens": out_tokens,
        "output_max_turn": out_max_turn,
        "output_estimated": estimated,
        "thinking_tokens": thinking,
        "ctx_peak": ctx_peak,
        "input_tokens_total": input_total,
        "tokens_total": input_total + out_tokens,
        "tool_calls": tool_calls,
        "tool_errors": tool_errors,
        "agent_spawns": dict(agent_spawns),
        "effort": efforts.most_common(1)[0][0] if efforts else None,
        "model": models.most_common(1)[0][0] if models else None,
        "duration_s": (last_ts - first_ts) if (first_ts is not None and last_ts is not None) else None,
        "started_at": first_ts,
        "max_turns_hit": max_turns_hit,
    }


def _read_meta(jsonl_path: str) -> dict:
    meta_path = jsonl_path[: -len(".jsonl")] + ".meta.json"
    try:
        with open(meta_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def session_dir_for(transcript_path: str) -> str:
    return transcript_path[: -len(".jsonl")] if transcript_path.endswith(".jsonl") else transcript_path


def ingest_session(transcript_path: str, main_agent: str = "main") -> List[dict]:
    """Observations for the main thread and every subagent of one session."""
    records: List[dict] = []
    main = summarize_transcript(transcript_path) if os.path.isfile(transcript_path) else None
    if main:
        main.update(agent_type=main_agent, spawn_depth=0, source="main", workflow=None,
                    transcript=transcript_path)
        main["agent_id"] = "main"
        records.append(main)
    sdir = os.path.join(session_dir_for(transcript_path), "subagents")
    for path in sorted(glob.glob(os.path.join(sdir, "**", "agent-*.jsonl"), recursive=True)):
        rec = summarize_transcript(path)
        if not rec:
            continue
        meta = _read_meta(path)
        rel = os.path.relpath(path, sdir)
        wf = rel.split(os.sep)[1] if rel.startswith("workflows" + os.sep) else None
        rec.update(
            agent_type=meta.get("agentType") or "unknown",
            spawn_depth=meta.get("spawnDepth"),
            description=meta.get("description"),
            source="subagent",
            workflow=wf,
            transcript=path,
        )
        if not rec.get("agent_id"):
            rec["agent_id"] = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        records.append(rec)
    return records


def find_session_transcripts(projects_root: str, since_ts: float = 0.0) -> List[str]:
    paths = glob.glob(os.path.join(projects_root, "*", "*.jsonl"))
    return sorted(p for p in paths if os.path.getmtime(p) >= since_ts)
