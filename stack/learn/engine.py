"""Ingest -> update -> apply pipeline for the self-tuning loop.

Storage (outside the repo, never committed):
    $CLAUDE_STACK_DATA (default ~/.claude/stack-data)/
        obs/<session-id>.json       observations of one session, keyed by agent id
        recommendations.json        latest per-agent posterior summaries
        budgets.json                learned token windows / max output tokens
        changes.jsonl               audit log of every frontmatter change applied
"""
from __future__ import annotations

import glob
import json
import os
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


def run_after_session(transcript_path: Optional[str]) -> dict:
    """Hook entry: ingest this session, update posteriors, apply if configured."""
    cfg = load_config()
    if not cfg.get("enabled", True):
        return {"skipped": "learning disabled"}
    n = ingest_transcript(transcript_path) if transcript_path else 0
    rep = update()
    changes = apply() if cfg.get("auto_apply", True) else []
    return {"ingested": n, "agents": len(rep["agents"]), "changes": changes}
