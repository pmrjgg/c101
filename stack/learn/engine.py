"""Ingest -> update -> apply pipeline for the self-tuning loop.

Storage (outside the repo, never committed):
    $CLAUDE_STACK_DATA (default ~/.claude/stack-data)/
        obs/<session-id>.json       observations of one session, keyed by agent id
        recommendations.json        latest per-agent posterior summaries
        budgets.json                learned token windows / max output tokens
        changes.jsonl               audit log of every frontmatter change applied
        history.jsonl               one summary line per session (per-agent runs, turns, caps, errors,
                                    tokens, effort, current vs recommended values) for analysis over time

Lifecycle: SessionEnd ingests the session, updates the posteriors and appends its history line
(``run_after_session``); SessionStart applies the pending recommendations to agent frontmatter
(``start_of_session``), so agent files never change while a session runs. ``apply_on`` in
config/learning.json moves applying to session end or turns it off; ``auto_apply: false`` disables it.
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import time
from typing import Dict, List, Optional

from .. import frontmatter, paths
from . import ingest
from .model import EFFORT_LEVELS, recommend_agent


def load_config() -> dict:
    with open(os.path.join(paths.CONFIG_DIR, "learning.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _obs_dir() -> str:
    d = os.path.join(paths.data_dir(), "obs")
    os.makedirs(d, exist_ok=True)
    return d


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _agent_current(name: str) -> Dict[str, object]:
    path = paths.find_agent_file(name)
    if not path:
        return {}
    try:
        fm = frontmatter.read(path)
    except (OSError, frontmatter.FrontmatterError):
        return {}
    return {"maxTurns": fm.get("maxTurns"), "effort": fm.get("effort"),
            "autoCompactWindow": fm.get("autoCompactWindow"), "path": path}


# --------------------------------------------------------------------------- #
def ingest_transcript(transcript_path: str, main_agent: Optional[str] = None) -> int:
    """Ingest one session (main + subagents).  Idempotent: rewrites that session's file."""
    main_agent = main_agent or os.environ.get("CLAUDE_STACK_MAIN_AGENT") or "main"
    records = ingest.ingest_session(transcript_path, main_agent=main_agent)
    if not records:
        return 0
    stops = _stop_events(records[0].get("session_id"))
    limits: Dict[str, Optional[int]] = {}
    for r in records:
        t = r["agent_type"]
        if t not in limits:
            cur = _agent_current(t).get("maxTurns")
            limits[t] = int(cur) if cur not in (None, "") else None
        lim = limits[t]
        r["limit_max_turns"] = lim
        rounds = r.get("tool_rounds", r["turns"])
        r["capped"] = bool(r.get("max_turns_hit") or (lim is not None and rounds >= lim))
        ev = stops.get(r.get("agent_id"))
        if ev and ev.get("effort"):
            r["effort_transcript"] = r.get("effort")
            r["effort"] = ev["effort"]  # level in effect per the SubagentStop payload (authoritative)
        r["ingested_at"] = time.time()
    sid = records[0].get("session_id") or os.path.basename(ingest.session_dir_for(transcript_path))
    _write_json(os.path.join(_obs_dir(), "%s.json" % sid), {r["agent_id"]: r for r in records})
    return len(records)


def _stop_events(session_id: Optional[str]) -> Dict[str, dict]:
    """agent_id -> last SubagentStop event recorded by the hook for this session."""
    out: Dict[str, dict] = {}
    if not session_id:
        return out
    p = os.path.join(paths.data_dir(), "stops", "%s.jsonl" % session_id)
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("agent_id"):
                    out[ev["agent_id"]] = ev
    except OSError:
        pass
    return out


def ingest_all(since_days: float = 0.0) -> int:
    since = time.time() - since_days * 86400 if since_days else 0.0
    total = 0
    for p in ingest.find_session_transcripts(paths.projects_root(), since):
        total += ingest_transcript(p)
    return total


def load_observations() -> Dict[str, List[dict]]:
    by_agent: Dict[str, List[dict]] = {}
    for f in glob.glob(os.path.join(_obs_dir(), "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for rec in data.values():
            t = rec.get("agent_type")
            if not t or t == "unknown":
                continue  # internal agents (prompt suggestions, /btw) report an empty type
            by_agent.setdefault(t, []).append(rec)
    return by_agent


def update(only: Optional[List[str]] = None) -> dict:
    cfg = load_config()
    by_agent = load_observations()
    recs: Dict[str, dict] = {}
    budgets: Dict[str, dict] = {}
    for name, obs in sorted(by_agent.items()):
        if only and name not in only:
            continue
        obs = sorted(obs, key=lambda r: r.get("started_at") or 0.0)[-cfg["max_history_per_agent"]:]
        cur = _agent_current(name)
        bounds = dict(cfg["default_bounds"])
        bounds.update(cfg["agents"].get(name, {}))
        rec = recommend_agent(name, obs, cur, cfg, bounds)
        rec["managed"] = bool(cur.get("path")) and bool(bounds.get("learn", True))
        rec["path"] = cur.get("path")
        recs[name] = rec
        if rec.get("tokens"):
            budgets[name] = dict(rec.get("budget", {}), tokens=rec["tokens"])
    out = {"generated_at": time.time(), "agents": recs, "global": global_budgets()}
    budgets["_global"] = out["global"]
    _write_json(os.path.join(paths.data_dir(), "recommendations.json"), out)
    _write_json(os.path.join(paths.data_dir(), "budgets.json"), budgets)
    return out


def global_budgets() -> dict:
    """Evidence about whole-session and whole-prompt token use; raise-only recommendations.

    The configured limits in config/policy.json are floors chosen for demanding work. History can
    only push them up (when real sessions/prompts keep running into them), never down.
    """
    from .. import budget
    from .bayes import LogNormalGrid, LogNormalPrior, Obs
    pol = budget.policy()
    w = float(pol["cache_read_weight"])
    sessions, prompts = [], []
    for f in glob.glob(os.path.join(paths.data_dir(), "sessions", "*.usage.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            continue
        sessions.append(budget.effective(st.get("session") or budget._zero(), w))
        prompts.extend(budget.effective(t, w) for pid, t in (st.get("prompts") or {}).items() if pid != "unknown")
    out = {"n_sessions": len(sessions), "n_prompts": len(prompts), "recommended": {}, "applied": {}}

    def fit(vals, typical, need):
        vals = [v for v in vals if v > 0]
        if len(vals) < need:
            return None
        m = LogNormalGrid(LogNormalPrior.around(typical, spread_factor=3.0)).fit(Obs(float(v)) for v in vals)
        return {"n": len(vals), "q50": int(m.predictive_quantile(0.5)), "q90": int(m.predictive_quantile(0.9)),
                "q95": int(m.predictive_quantile(0.95))}

    for scope, vals, key, need in (("session", sessions, "global", 5), ("prompt", prompts, "prompt", 10)):
        q = fit(vals, pol["soft_%s_tokens" % key] / 3.0, need)
        if not q:
            continue
        out[scope] = q
        cfg_soft, cfg_max = int(pol["soft_%s_tokens" % key]), int(pol["max_%s_tokens" % key])
        # raise-only, and at most x2 per update so one outlier session cannot blow the budget open
        rec_soft = min(max(cfg_soft, int(q["q90"] * 1.25)), 2 * cfg_soft)
        rec_max = min(max(cfg_max, int(q["q95"] * 1.5), rec_soft), 2 * cfg_max)
        out["recommended"].update({"soft_%s_tokens" % key: rec_soft, "max_%s_tokens" % key: rec_max})
    if pol.get("learn_global") == "apply":
        out["applied"] = dict(out["recommended"])
    return out


def apply(dry_run: bool = False, only: Optional[List[str]] = None) -> List[dict]:
    """Write recommended maxTurns/effort into agent frontmatter (managed agents only)."""
    cfg = load_config()
    path = os.path.join(paths.data_dir(), "recommendations.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        recs = json.load(fh).get("agents", {})
    changes = []
    for name, rec in sorted(recs.items()):
        if only and name not in only:
            continue
        if not rec.get("managed") or rec.get("status") != "ok" or not rec.get("path"):
            continue
        upd: Dict[str, Optional[str]] = {}
        mt = rec.get("maxTurns", {})
        if mt.get("recommended") and mt.get("recommended") != mt.get("current"):
            upd["maxTurns"] = str(mt["recommended"])
        ef = rec.get("effort", {})
        if ef.get("recommended") in EFFORT_LEVELS and ef.get("recommended") != ef.get("current"):
            upd["effort"] = ef["recommended"]
        acw = (rec.get("budget") or {}).get("autoCompactWindow")
        if acw and cfg.get("apply_compact_window", True):
            upd["autoCompactWindow"] = str(acw)
        if not upd:
            continue
        change = {"agent": name, "path": rec["path"], "updates": upd, "ts": time.time(),
                  "reasons": {"maxTurns": mt.get("reason"), "effort": ef.get("reason")},
                  "n_eff": rec.get("turns", {}).get("n_eff")}
        if not dry_run:
            frontmatter.update_file(rec["path"], upd)
            with open(os.path.join(paths.data_dir(), "changes.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(change) + "\n")
        changes.append(change)
    return changes


def apply_on(cfg: Optional[dict] = None) -> str:
    """When learned values are written: 'session_start' (default), 'session_end' or 'never'."""
    cfg = cfg or load_config()
    if not cfg.get("enabled", True) or not cfg.get("auto_apply", True):
        return "never"
    return cfg.get("apply_on", "session_start")


def _history_path() -> str:
    return os.path.join(paths.data_dir(), "history.jsonl")


def record_session(session_id: str) -> Optional[dict]:
    """Append (or replace) this session's summary line in history.jsonl."""
    p = os.path.join(_obs_dir(), "%s.json" % session_id)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        records = list(json.load(fh).values())
    recs: Dict[str, dict] = {}
    rp = os.path.join(paths.data_dir(), "recommendations.json")
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as fh:
            recs = json.load(fh).get("agents", {})
    agents: Dict[str, dict] = {}
    for r in records:
        a = agents.setdefault(r["agent_type"], {"runs": 0, "turns": [], "tool_rounds": [], "capped": 0,
                                                "tool_errors": 0, "tokens_total": 0, "output_tokens": 0,
                                                "duration_s": 0.0, "effort": {}, "models": set()})
        a["runs"] += 1
        a["turns"].append(int(r.get("turns") or 0))
        a["tool_rounds"].append(int(r.get("tool_rounds") or 0))
        a["capped"] += int(bool(r.get("capped")))
        a["tool_errors"] += int(r.get("tool_errors") or 0)
        a["tokens_total"] += int(r.get("tokens_total") or 0)
        a["output_tokens"] += int(r.get("output_tokens") or 0)
        a["duration_s"] += float(r.get("duration_s") or 0.0)
        if r.get("effort"):
            a["effort"][r["effort"]] = a["effort"].get(r["effort"], 0) + 1
        if r.get("model"):
            a["models"].add(r["model"])
    for name, a in agents.items():
        a["turns_median"] = statistics.median(a["turns"]) if a["turns"] else 0
        a["turns_max"] = max(a["turns"]) if a["turns"] else 0
        a["tool_rounds_median"] = statistics.median(a["tool_rounds"]) if a["tool_rounds"] else 0
        a["tool_rounds_max"] = max(a["tool_rounds"]) if a["tool_rounds"] else 0
        a["duration_s"] = round(a["duration_s"], 1)
        a["models"] = sorted(a["models"])
        del a["turns"], a["tool_rounds"]
        rec = recs.get(name) or {}
        if rec:
            a["maxTurns"] = {k: (rec.get("maxTurns") or {}).get(k) for k in ("current", "recommended")}
            a["effort_setting"] = {k: (rec.get("effort") or {}).get(k) for k in ("current", "recommended")}
    starts = [r.get("started_at") for r in records if r.get("started_at")]
    line = {"session_id": session_id, "recorded_at": time.time(),
            "started_at": min(starts) if starts else None,
            "project": os.path.basename(os.path.dirname(records[0].get("transcript") or "")),
            "runs": len(records), "tokens_total": sum(a["tokens_total"] for a in agents.values()),
            "agents": agents}
    hp = _history_path()
    kept = []
    if os.path.exists(hp):
        with open(hp, encoding="utf-8") as fh:
            kept = [ln for ln in fh if ln.strip() and json.loads(ln).get("session_id") != session_id]
    tmp = hp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.writelines(kept)
        fh.write(json.dumps(line, sort_keys=True) + "\n")
    os.replace(tmp, hp)
    return line


def run_after_session(transcript_path: Optional[str]) -> dict:
    """SessionEnd: ingest this session, update posteriors and record its history line.

    Values are applied at the next session start (``start_of_session``) unless ``apply_on`` is
    'session_end'.
    """
    cfg = load_config()
    if not cfg.get("enabled", True):
        return {"skipped": "learning disabled"}
    n = ingest_transcript(transcript_path) if transcript_path else 0
    rep = update()
    sid = None
    if transcript_path:
        sid = os.path.splitext(os.path.basename(transcript_path))[0]
    line = record_session(sid) if sid else None
    changes = apply() if apply_on(cfg) == "session_end" else []
    return {"ingested": n, "agents": len(rep["agents"]), "recorded": bool(line), "changes": changes}


def start_of_session() -> List[dict]:
    """SessionStart: write the pending recommendations into agent frontmatter."""
    return apply() if apply_on() == "session_start" else []


def history(agent: Optional[str] = None, since_days: float = 0.0, by: str = "week") -> Dict[str, List[dict]]:
    """Per-agent trend rows from history.jsonl, one per period ('week', 'day' or 'session')."""
    hp = _history_path()
    if not os.path.exists(hp):
        return {}
    cutoff = time.time() - since_days * 86400 if since_days else 0
    with open(hp, encoding="utf-8") as fh:
        lines = [json.loads(ln) for ln in fh if ln.strip()]
    lines = sorted((ln for ln in lines if (ln.get("started_at") or ln.get("recorded_at") or 0) >= cutoff),
                   key=lambda ln: ln.get("started_at") or ln.get("recorded_at") or 0)
    fmt = {"week": "%G-W%V", "day": "%Y-%m-%d"}.get(by)
    buckets: Dict[str, Dict[str, dict]] = {}
    for ln in lines:
        ts = ln.get("started_at") or ln.get("recorded_at") or 0
        period = time.strftime(fmt, time.localtime(ts)) if fmt else ln["session_id"][:8]
        for name, a in ln.get("agents", {}).items():
            if agent and name != agent:
                continue
            b = buckets.setdefault(name, {}).setdefault(period, {
                "period": period, "sessions": 0, "runs": 0, "capped": 0, "tool_errors": 0, "tokens_total": 0,
                "turns_median": [], "turns_max": 0, "effort": {}, "maxTurns": None, "effort_setting": None})
            b["sessions"] += 1
            b["runs"] += a.get("runs", 0)
            b["capped"] += a.get("capped", 0)
            b["tool_errors"] += a.get("tool_errors", 0)
            b["tokens_total"] += a.get("tokens_total", 0)
            b["turns_median"].append(a.get("turns_median", 0))
            b["turns_max"] = max(b["turns_max"], a.get("turns_max", 0))
            for k, v in (a.get("effort") or {}).items():
                b["effort"][k] = b["effort"].get(k, 0) + v
            b["maxTurns"] = a.get("maxTurns") or b["maxTurns"]
            b["effort_setting"] = a.get("effort_setting") or b["effort_setting"]
    out: Dict[str, List[dict]] = {}
    for name, periods in sorted(buckets.items()):
        rows = []
        for b in periods.values():
            b["turns_median"] = round(statistics.median(b["turns_median"]), 1) if b["turns_median"] else 0
            b["cap_rate"] = round(b["capped"] / b["runs"], 3) if b["runs"] else 0.0
            b["tokens_per_run"] = int(b["tokens_total"] / b["runs"]) if b["runs"] else 0
            rows.append(b)
        out[name] = rows
    return out
