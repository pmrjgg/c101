#!/usr/bin/env python3
"""Validate a planning-dag plan (JSON) and compute waves, schedule and critical path.

Usage:
  python3 .claude/skills/planning-dag/scripts/dag.py PLAN.json             human report
  python3 .claude/skills/planning-dag/scripts/dag.py PLAN.json --json      machine-readable report
  python3 .claude/skills/planning-dag/scripts/dag.py PLAN.json --ready     ids launchable now, one per line
  python3 .claude/skills/planning-dag/scripts/dag.py PLAN.json --mermaid   mermaid flowchart (critical path highlighted)

Exit status: 0 valid (warnings allowed), 1 validation errors, 2 usage or I/O error.
Stdlib only, Python 3.9+. Format: ../references/plan-schema.md. Accepted aliases:
writes | write_set | outputs, est_turns | estimate, risk.impact | risk.severity, verify as object or string,
status PASS/FAIL/SKIPPED (any case).
"""
from __future__ import annotations

import fnmatch
import json
import os
import sys
from typing import Dict, List, Optional, Set

STATUS_ALIASES = {"pass": "done", "passed": "done", "ok": "done", "fail": "failed", "error": "failed",
                  "in_progress": "running", "todo": "pending", "canceled": "cancelled"}
STATUSES = {"pending", "running", "done", "failed", "blocked", "skipped", "cancelled"}
FINISHED = {"done", "skipped"}
HUMAN_OWNERS = {"user", "caller", "human"}
BUILTIN_AGENTS = {"general-purpose", "Explore", "Plan"}
MAX_WAVE_WIDTH = 20
GLOB_CHARS = "*?["


def known_agents(start: str) -> Optional[Set[str]]:
    """Agent names from the nearest .claude/agents directory above `start` (None if not found)."""
    d = os.path.abspath(start)
    while True:
        base = os.path.join(d, ".claude", "agents")
        if os.path.isdir(base):
            names: Set[str] = set()
            for _root, _dirs, files in os.walk(base):
                names.update(f[:-3] for f in files if f.endswith(".md"))
            return names
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        data = {"nodes": data}
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ValueError("plan must be an object with a 'nodes' array (or a bare array of nodes)")
    return data


def _components(p: str) -> List[str]:
    return [c for c in p.strip().strip("/").split("/") if c not in ("", ".")]


def _static_prefix(p: str) -> List[str]:
    out = []
    for c in _components(p):
        if any(ch in c for ch in GLOB_CHARS):
            break
        out.append(c)
    return out


def overlap(a: str, b: str) -> Optional[str]:
    """'certain' when two write paths collide, 'possible' for glob overlaps, None otherwise."""
    ga, gb = any(ch in a for ch in GLOB_CHARS), any(ch in b for ch in GLOB_CHARS)
    ca, cb = _components(a), _components(b)
    if not ga and not gb:
        n = min(len(ca), len(cb))
        return "certain" if ca[:n] == cb[:n] else None  # equal, or one is a directory of the other
    if ga and not gb:
        return "possible" if fnmatch.fnmatch("/".join(cb), "/".join(ca)) or _prefix_rel(_static_prefix(a), cb) else None
    if gb and not ga:
        return overlap(b, a)
    pa, pb = _static_prefix(a), _static_prefix(b)
    n = min(len(pa), len(pb))
    return "possible" if pa[:n] == pb[:n] else None


def _prefix_rel(prefix: List[str], comps: List[str]) -> bool:
    # A glob such as dir/** or dir/* may cover anything below its static prefix.
    return len(prefix) < len(comps) and comps[:len(prefix)] == prefix


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return None
    return float(v)


def analyse(plan: dict, agents: Optional[Set[str]]) -> dict:
    errors: List[str] = []
    warnings: List[str] = []
    nodes: Dict[str, dict] = {}

    for i, n in enumerate(plan["nodes"]):
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not n["id"].strip():
            errors.append("node #%d has no string id" % i)
            continue
        nid = n["id"]
        if nid in nodes:
            errors.append("duplicate id %s" % nid)
            continue
        nodes[nid] = n
        owner = n.get("owner")
        if not isinstance(owner, str) or not owner:
            errors.append("%s: missing owner" % nid)
        elif agents is not None and owner not in agents and owner not in BUILTIN_AGENTS | HUMAN_OWNERS:
            warnings.append("%s: owner %r is not an agent in .claude/agents" % (nid, owner))
        acc = n.get("acceptance")
        if not isinstance(acc, list) or not [a for a in acc if isinstance(a, str) and a.strip()]:
            errors.append("%s: needs at least one acceptance criterion" % nid)
        ver = n.get("verify")
        if isinstance(ver, dict):
            vmethod = ver.get("method") or ("command" if ver.get("command") else None)
            if not (ver.get("method") or ver.get("by") or ver.get("how") or ver.get("command")):
                errors.append("%s: verify needs method, by or how" % nid)
            elif ver.get("by") and ver.get("by") == owner and vmethod != "command" and owner not in HUMAN_OWNERS:
                warnings.append("%s: verified by its own owner (%s); use an independent verifier" % (nid, owner))
        elif not (isinstance(ver, str) and ver.strip()):
            errors.append("%s: missing verify" % nid)
        writes: List[str] = []
        for key in ("writes", "write_set", "outputs"):
            v = n.get(key)
            if isinstance(v, str):
                v = [v]
            if isinstance(v, list):
                writes.extend(str(x) for x in v if str(x).strip())
        n["_writes"] = list(dict.fromkeys(writes))
        if not writes:
            warnings.append("%s: no writes listed; conflicts cannot be checked and successors cannot cite its artefact" % nid)
        est = _num(n.get("est_turns", n.get("estimate")))
        if est is None:
            warnings.append("%s: est_turns missing or not positive; using 1" % nid)
            est = 1.0
        n["_est"] = est
        st = str(n.get("status", "pending")).strip().lower()
        st = STATUS_ALIASES.get(st, st)
        if st not in STATUSES:
            errors.append("%s: unknown status %r" % (nid, n.get("status")))
            st = "pending"
        n["_status"] = st
        risk = n.get("risk")
        if isinstance(risk, dict):
            imp, lik = risk.get("impact", risk.get("severity")), risk.get("likelihood")
            if isinstance(imp, int) and isinstance(lik, int) and imp * lik >= 6:
                if not risk.get("mitigation"):
                    warnings.append("%s: high risk (%d x %d) without a mitigation" % (nid, lik, imp))
                if n.get("irreversible") and not risk.get("rollback"):
                    warnings.append("%s: irreversible high-risk node without a rollback" % nid)

    succ: Dict[str, List[str]] = {k: [] for k in nodes}
    preds: Dict[str, List[str]] = {k: [] for k in nodes}
    for nid, n in nodes.items():
        deps = n.get("deps", [])
        if not isinstance(deps, list):
            errors.append("%s: deps must be a list" % nid)
            continue
        for d in dict.fromkeys(deps):
            if d == nid:
                errors.append("%s: depends on itself" % nid)
            elif d not in nodes:
                errors.append("%s: unknown dependency %r" % (nid, d))
            else:
                preds[nid].append(d)
                succ[d].append(nid)

    # Kahn topological sort; leftovers are on or downstream of a cycle.
    indeg = {k: len(v) for k, v in preds.items()}
    order: List[str] = []
    queue = [k for k in nodes if indeg[k] == 0]
    while queue:
        k = queue.pop(0)
        order.append(k)
        for s in succ[k]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)
    if len(order) != len(nodes):
        stuck = set(nodes) - set(order)
        changed = True
        while changed:  # peel nodes that merely sit downstream of a cycle
            changed = False
            for k in list(stuck):
                if not [s for s in succ[k] if s in stuck]:
                    stuck.discard(k)
                    changed = True
        errors.append("dependency cycle through: %s" % ", ".join(sorted(stuck)))
        return {"errors": errors, "warnings": warnings, "nodes": {}, "waves": [], "critical_path": [],
                "ready": [], "status_counts": {}, "edges": 0, "length": 0, "remaining_length": 0,
                "remaining_critical_path": []}

    for k in order:  # irreversible nodes need a human checkpoint upstream
        if nodes[k].get("irreversible") and not any(nodes[p].get("owner") in HUMAN_OWNERS for p in preds[k]):
            warnings.append("%s: irreversible node without a caller/user checkpoint node among its deps" % k)

    anc: Dict[str, Set[str]] = {}
    for k in order:
        a: Set[str] = set()
        for p in preds[k]:
            a |= anc[p] | {p}
        anc[k] = a
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            if a in anc[b] or b in anc[a]:
                continue
            for wa in nodes[a]["_writes"]:
                for wb in nodes[b]["_writes"]:
                    kind = overlap(wa, wb)
                    if kind == "certain":
                        errors.append("write conflict: %s (%s) and %s (%s) can run concurrently; add an edge or split the write-set" % (a, wa, b, wb))
                    elif kind == "possible":
                        warnings.append("possible write overlap: %s (%s) and %s (%s); confirm the globs are disjoint" % (a, wa, b, wb))

    def schedule(dur: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        es: Dict[str, float] = {}
        ef: Dict[str, float] = {}
        for k in order:
            es[k] = max((ef[p] for p in preds[k]), default=0.0)
            ef[k] = es[k] + dur[k]
        length = max(ef.values(), default=0.0)
        lf: Dict[str, float] = {}
        ls: Dict[str, float] = {}
        for k in reversed(order):
            lf[k] = min((ls[s] for s in succ[k]), default=length)
            ls[k] = lf[k] - dur[k]
        return {k: {"ES": es[k], "EF": ef[k], "LS": ls[k], "LF": lf[k], "slack": round(ls[k] - es[k], 6)} for k in order}

    full = schedule({k: nodes[k]["_est"] for k in order})
    rem = schedule({k: (0.0 if nodes[k]["_status"] in FINISHED else nodes[k]["_est"]) for k in order})

    wave: Dict[str, int] = {}
    for k in order:
        wave[k] = 1 + max((wave[p] for p in preds[k]), default=-1)
    waves: List[List[str]] = [[] for _ in range(max(wave.values(), default=-1) + 1)]
    for k in order:
        waves[wave[k]].append(k)
    for i, w in enumerate(waves):
        if len(w) > MAX_WAVE_WIDTH:
            warnings.append("wave W%d has %d nodes; over %d concurrent agents: batch it, move it to a bulk node (swarm-coordinator), or (main thread only) Workflow name=fanout" % (i, len(w), MAX_WAVE_WIDTH))

    def critical(sched: Dict[str, Dict[str, float]]) -> List[str]:
        crit = {k for k, v in sched.items() if abs(v["slack"]) < 1e-9}
        starts = [k for k in order if k in crit and not [p for p in preds[k] if p in crit]]
        if not starts:
            return []
        path = [max(starts, key=lambda k: sched[k]["EF"] - sched[k]["ES"])]
        while True:
            nxt = [s for s in succ[path[-1]] if s in crit and abs(sched[s]["ES"] - sched[path[-1]]["EF"]) < 1e-9]
            if not nxt:
                return path
            path.append(max(nxt, key=lambda k: sched[k]["EF"] - sched[k]["ES"]))

    sinks = [k for k in order if not succ[k]]
    if len(sinks) > 1:
        warnings.append("%d final nodes (%s); end with a single gate such as quality-control" % (len(sinks), ", ".join(sinks)))

    ready = [k for k in order if nodes[k]["_status"] == "pending"
             and all(nodes[p]["_status"] in FINISHED for p in preds[k])]
    counts: Dict[str, int] = {}
    for k in order:
        counts[nodes[k]["_status"]] = counts.get(nodes[k]["_status"], 0) + 1

    out_nodes = {}
    for k in order:
        n = nodes[k]
        out_nodes[k] = dict(full[k], id=k, owner=n.get("owner"), title=n.get("title", ""), est_turns=n["_est"],
                            wave=wave[k], status=n["_status"], deps=preds[k], writes=n["_writes"])
    total = sum(nodes[k]["_est"] for k in order)
    length = max((v["EF"] for v in full.values()), default=0.0)
    return {
        "plan_id": plan.get("plan_id"), "plan_version": plan.get("plan_version"),
        "errors": errors, "warnings": warnings, "nodes": out_nodes, "waves": waves,
        "length": length, "total_work": total, "parallelism": round(total / length, 2) if length else 0.0,
        "critical_path": critical(full),
        "remaining_length": max((v["EF"] for v in rem.values()), default=0.0),
        "remaining_critical_path": [k for k in critical(rem) if nodes[k]["_status"] not in FINISHED],
        "ready": ready, "status_counts": counts, "edges": sum(len(v) for v in preds.values()),
    }


def fmt(x: float) -> str:
    return ("%d" % x) if float(x).is_integer() else ("%.1f" % x)


def report(r: dict) -> str:
    lines = []
    if r.get("nodes"):
        lines.append("plan %s v%s: %d nodes, %d edges, %d waves" % (
            r.get("plan_id") or "-", r.get("plan_version") or "-", len(r["nodes"]), r["edges"], len(r["waves"])))
        lines.append("")
        lines.append("waves:")
        for i, w in enumerate(r["waves"]):
            lines.append("  W%d (%d): %s" % (i, len(w), ", ".join(w)))
        lines.append("")
        lines.append("%-6s %-26s %5s %5s %5s %5s %5s %6s  %s" % ("id", "owner", "est", "ES", "EF", "LS", "LF", "slack", "status"))
        for k, v in r["nodes"].items():
            lines.append("%-6s %-26s %5s %5s %5s %5s %5s %6s  %s%s" % (
                k, v["owner"], fmt(v["est_turns"]), fmt(v["ES"]), fmt(v["EF"]), fmt(v["LS"]), fmt(v["LF"]),
                fmt(v["slack"]), v["status"], "  *critical" if k in r["critical_path"] else ""))
        lines.append("")
        lines.append("critical path (%s turns): %s" % (fmt(r["length"]), " -> ".join(r["critical_path"])))
        lines.append("total work %s turns, parallelism %.2f" % (fmt(r["total_work"]), r["parallelism"]))
        lines.append("remaining critical length: %s (%s)" % (fmt(r["remaining_length"]), " -> ".join(r["remaining_critical_path"]) or "-"))
        lines.append("status: %s" % ", ".join("%s=%d" % kv for kv in sorted(r["status_counts"].items())))
        lines.append("ready now: %s" % (", ".join(r["ready"]) or "-"))
    for w in r["warnings"]:
        lines.append("warn  " + w)
    for e in r["errors"]:
        lines.append("ERROR " + e)
    if not r["errors"]:
        lines.append("ERRORS: none")
    return "\n".join(lines)


def mermaid(r: dict) -> str:
    out = ["flowchart LR"]
    for k, v in r["nodes"].items():
        label = ("%s: %s (%s)" % (k, v["title"], v["owner"])).replace('"', "'")
        out.append('  %s["%s"]' % (k, label))
    for k, v in r["nodes"].items():
        for d in v["deps"]:
            out.append("  %s --> %s" % (d, k))
    if r["critical_path"]:
        out.append("  classDef crit stroke-width:3px")
        out.append("  class %s crit" % ",".join(r["critical_path"]))
    return "\n".join(out)


def main(argv: List[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    if len(args) != 1 or flags - {"--json", "--ready", "--mermaid"}:
        sys.stderr.write(__doc__ or "")
        return 2
    try:
        plan = load(args[0])
    except (OSError, ValueError) as e:
        sys.stderr.write("cannot read plan: %s\n" % e)
        return 2
    agents = known_agents(os.path.dirname(os.path.abspath(args[0]))) or known_agents(os.getcwd())
    r = analyse(plan, agents)
    if "--json" in flags:
        print(json.dumps(r, indent=2))
    elif "--ready" in flags:
        if not r["errors"]:
            print("\n".join(r["ready"]))
    elif "--mermaid" in flags:
        if not r["errors"]:
            print(mermaid(r))
    else:
        print(report(r))
    if r["errors"] and flags & {"--ready", "--mermaid"}:
        sys.stderr.write("\n".join("ERROR " + e for e in r["errors"]) + "\n")
    return 1 if r["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
