#!/usr/bin/env python3
"""Audit, snapshot, what-if and rollback helpers for the stack's Bayesian self-tuning.

Uses the stack's own learner code (stack/learn), so numbers match `bin/stack learn`.
Stdlib only; Python 3.9+. Reads $CLAUDE_STACK_DATA (default ~/.claude/stack-data); never writes
agent files itself -- it prints the `bin/stack` commands to run.

  history  [--agent A ...] [--since-days N] [--json]
           every applied change from changes.jsonl, oldest first, with reasons and n_eff
  snapshot [--out PATH]
           current model/effort/maxTurns of every agent -> JSON (take one before enabling auto_apply)
  revert-plan --agent A [--steps N] [--snapshot PATH]
           values in force before the last N applied changes of A, as `bin/stack agents set` commands,
           plus the config/learning.json bounds that would pin them
  whatif   --agent A [--set key=value ...] [--bounds maxTurns=LO,HI] [--bounds effort=LO,HI]
           recommendation under modified learning.json keys/bounds vs the current config,
           computed on the stored observations (no files are changed)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
if not os.path.isfile(os.path.join(REPO, "stack", "learn", "model.py")):
    sys.stderr.write("cannot locate the stack repo from %s\n" % HERE)
    sys.exit(2)
sys.path.insert(0, REPO)

from stack import frontmatter, paths  # noqa: E402
from stack.learn import engine, model  # noqa: E402


def _changes():
    p = os.path.join(paths.data_dir(), "changes.jsonl")
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return sorted(out, key=lambda c: c.get("ts", 0))


def _iso(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "?"


def cmd_history(a) -> int:
    ch = _changes()
    if a.agent:
        ch = [c for c in ch if c.get("agent") in a.agent]
    if a.since_days:
        cut = time.time() - a.since_days * 86400
        ch = [c for c in ch if c.get("ts", 0) >= cut]
    if a.json:
        print(json.dumps(ch, indent=2))
        return 0
    if not ch:
        print("no applied changes recorded")
        return 0
    for c in ch:
        upd = " ".join("%s=%s" % kv for kv in sorted(c.get("updates", {}).items()))
        why = "; ".join("%s: %s" % kv for kv in sorted((c.get("reasons") or {}).items()) if kv[1])
        print("%s  %-26s %-28s n_eff=%-6s %s" % (_iso(c.get("ts")), c.get("agent"), upd, c.get("n_eff"), why))
    return 0


def _agent_rows():
    rows = {}
    for f in paths.all_agent_files():
        try:
            fm = frontmatter.read(f)
        except (OSError, frontmatter.FrontmatterError):
            continue
        rows[fm.get("name")] = {k: fm.get(k) for k in ("model", "effort", "maxTurns")}
        rows[fm.get("name")]["path"] = os.path.relpath(f, REPO)
    return rows


def cmd_snapshot(a) -> int:
    out = a.out
    if not out:
        d = os.path.join(REPO, ".stack", "out", "stack-tuner")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "%s-agent-baseline.json" % time.strftime("%Y%m%d-%H%M"))
    data = {"taken_at": time.time(), "agents": _agent_rows()}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(out)
    return 0


def cmd_revert_plan(a) -> int:
    name = a.agent
    ch = [c for c in _changes() if c.get("agent") == name]
    if not ch:
        print("no applied changes for %s" % name)
        return 0
    steps = max(1, min(a.steps, len(ch)))
    undone, earlier = ch[-steps:], ch[:-steps]
    keys = sorted({k for c in undone for k in c.get("updates", {})})
    snap = {}
    if a.snapshot:
        with open(a.snapshot, encoding="utf-8") as fh:
            snap = json.load(fh).get("agents", {}).get(name, {})
    target, unknown = {}, []
    for k in keys:
        prev = [c["updates"][k] for c in earlier if k in c.get("updates", {})]
        if prev:
            target[k] = prev[-1]
        elif snap.get(k) not in (None, ""):
            target[k] = snap[k]
        else:
            unknown.append(k)
    cur = _agent_rows().get(name, {})
    print("agent %s  current: %s" % (name, " ".join("%s=%s" % (k, cur.get(k)) for k in keys)))
    print("undoing %d change(s) from %s to %s" % (steps, _iso(undone[0].get("ts")), _iso(undone[-1].get("ts"))))
    if target:
        print("run:   bin/stack agents set %s %s" % (name, " ".join("%s=%s" % kv for kv in sorted(target.items()))))
        pin = {}
        if "maxTurns" in target:
            pin["maxTurns"] = [int(target["maxTurns"]), int(target["maxTurns"])]
        if "effort" in target:
            pin["effort"] = [target["effort"], target["effort"]]
        print("pin:   config/learning.json agents.%s = %s   (or {\"learn\": false})" % (name, json.dumps(pin)))
    for k in unknown:
        print("unknown pre-learner %s: use `git log -p -- %s` or a snapshot (--snapshot PATH)" % (k, cur.get("path", "<agent file>")))
    return 0


def _parse_set(pairs):
    out = {}
    for kv in pairs or []:
        k, v = kv.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def _summ(rec: dict) -> dict:
    if rec.get("status") != "ok":
        return {"status": rec.get("status")}
    t, mt, ef = rec.get("turns", {}), rec.get("maxTurns", {}), rec.get("effort", {})
    return {"maxTurns": "%s -> %s (%s)" % (mt.get("current"), mt.get("recommended"), mt.get("reason")),
            "effort": "%s -> %s (%s)" % (ef.get("current"), ef.get("recommended"), ef.get("reason")),
            "turns q50/q95": "%s / %s" % (t.get("q50"), t.get("q95")), "n_eff": t.get("n_eff"),
            "n_capped": t.get("n_capped"), "gamma": rec.get("window", {}).get("gamma"),
            "P(fail)": ef.get("p_fail_mean"), "budget": rec.get("budget")}


def cmd_whatif(a) -> int:
    cfg = engine.load_config()
    obs = engine.load_observations().get(a.agent, [])
    if not obs:
        print("no observations for %s; run `bin/stack learn ingest --all` first" % a.agent)
        return 1
    obs = sorted(obs, key=lambda r: r.get("started_at") or 0.0)[-cfg["max_history_per_agent"]:]
    cur = engine._agent_current(a.agent)
    bounds = dict(cfg["default_bounds"])
    bounds.update(cfg["agents"].get(a.agent, {}))
    base = model.recommend_agent(a.agent, obs, cur, cfg, bounds)
    cfg2 = dict(cfg)
    cfg2.update(_parse_set(a.set))
    b2 = dict(bounds)
    for spec in a.bounds or []:
        k, v = spec.split("=", 1)
        lo, hi = [x.strip() for x in v.split(",")]
        b2[k] = [int(lo), int(hi)] if k == "maxTurns" else [lo, hi]
    alt = model.recommend_agent(a.agent, obs, cur, cfg2, b2)
    print(json.dumps({"agent": a.agent, "n": len(obs), "baseline": _summ(base), "whatif": _summ(alt),
                      "changed_config": _parse_set(a.set), "bounds": b2}, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("history"); x.add_argument("--agent", action="append"); x.add_argument("--since-days", type=float)
    x.add_argument("--json", action="store_true"); x.set_defaults(fn=cmd_history)
    x = s.add_parser("snapshot"); x.add_argument("--out"); x.set_defaults(fn=cmd_snapshot)
    x = s.add_parser("revert-plan"); x.add_argument("--agent", required=True); x.add_argument("--steps", type=int, default=1)
    x.add_argument("--snapshot"); x.set_defaults(fn=cmd_revert_plan)
    x = s.add_parser("whatif"); x.add_argument("--agent", required=True); x.add_argument("--set", action="append")
    x.add_argument("--bounds", action="append"); x.set_defaults(fn=cmd_whatif)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
