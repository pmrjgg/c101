#!/usr/bin/env python3
"""Aggregate a judge panel: per-criterion aggregation, weighted totals, gates, agreement, grafts.

Stdlib only, Python 3.9+.  Deterministic.

Input (JSON file or '-' for stdin):
{
  "scale": [1, 5],                                   # anchor scale used by every criterion
  "criteria": {"feasibility": 0.25, "risk": 0.20, "cost": 0.15, "verifiability": 0.20, "completeness": 0.20},
  "scores": {                                        # judge -> candidate -> criterion -> score
    "J1": {"A": {"feasibility": 4, "risk": 3, ...}, "B": {...}},
    "J2": {...}
  },
  "gates": {                                         # optional: judge -> candidate -> gate -> bool
    "J1": {"A": {"has-rollback": true}, "B": {"has-rollback": false}}
  }
}

Usage:
  python3 panel.py scores.json                       # aggregator chosen from judge count
  python3 panel.py scores.json --agg trimmed --trim 0.2
  python3 panel.py scores.json --normalize z         # remove judge leniency before aggregating
  python3 panel.py scores.json --graft-step 1        # min advantage (scale points) to propose a graft
Output: JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from typing import Dict, List, Optional


def load(path: str) -> dict:
    fh = sys.stdin if path == "-" else open(path, encoding="utf-8")
    with fh:
        d = json.load(fh)
    crit = d.get("criteria") or {}
    if isinstance(crit, list):
        crit = {c: 1.0 / len(crit) for c in crit}
    tot = sum(float(w) for w in crit.values())
    if tot <= 0:
        raise SystemExit("criteria weights must sum to > 0")
    d["criteria"] = {c: float(w) / tot for c, w in crit.items()}
    d.setdefault("scale", [1, 5])
    if not d.get("scores"):
        raise SystemExit("no scores")
    return d


def trimmed_mean(xs: List[float], frac: float) -> float:
    xs = sorted(xs)
    k = int(math.floor(frac * len(xs)))
    core = xs[k:len(xs) - k] if len(xs) - 2 * k > 0 else xs
    return sum(core) / len(core)


def aggregate(xs: List[float], how: str, trim: float) -> float:
    if how == "mean":
        return sum(xs) / len(xs)
    if how == "median":
        return float(statistics.median(xs))
    return trimmed_mean(xs, trim)


def zscore(scores: dict, lo: float, hi: float) -> dict:
    """Per-judge z-scores mapped back onto the scale midpoint/spread (removes leniency/severity)."""
    mid, spread = (lo + hi) / 2.0, (hi - lo) / 4.0
    out = {}
    for j, by_c in scores.items():
        vals = [float(v) for c in by_c.values() for v in c.values()]
        mu = sum(vals) / len(vals)
        sd = statistics.pstdev(vals) or 1.0
        out[j] = {c: {k: mid + spread * (float(v) - mu) / sd for k, v in crit.items()} for c, crit in by_c.items()}
    return out


def ranks_desc(vals: Dict[str, float]) -> Dict[str, float]:
    """Rank 1 = best; ties get the average rank."""
    items = sorted(vals.items(), key=lambda kv: -kv[1])
    out, i = {}, 0
    while i < len(items):
        j = i
        while j + 1 < len(items) and abs(items[j + 1][1] - items[i][1]) < 1e-9:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            out[items[k][0]] = r
        i = j + 1
    return out


def kendall_w(per_judge_totals: Dict[str, Dict[str, float]], cands: List[str]) -> Optional[float]:
    m, n = len(per_judge_totals), len(cands)
    if m < 2 or n < 2:
        return None
    R = {c: 0.0 for c in cands}
    T = 0.0
    for totals in per_judge_totals.values():
        rk = ranks_desc({c: totals[c] for c in cands})
        for c in cands:
            R[c] += rk[c]
        groups: Dict[float, int] = {}
        for r in rk.values():
            groups[r] = groups.get(r, 0) + 1
        T += sum(t ** 3 - t for t in groups.values())
    Rbar = m * (n + 1) / 2.0
    S = sum((R[c] - Rbar) ** 2 for c in cands)
    denom = m * m * (n ** 3 - n) - m * T
    return None if denom <= 0 else 12.0 * S / denom


def kripp_alpha_interval(units: List[List[float]]) -> Optional[float]:
    """Krippendorff's alpha, interval metric. units = list of value lists (one per rated cell)."""
    units = [u for u in units if len(u) >= 2]
    vals = [v for u in units for v in u]
    n = len(vals)
    if n < 2:
        return None
    do = sum(sum((a - b) ** 2 for i, a in enumerate(u) for j, b in enumerate(u) if i != j) / (len(u) - 1)
             for u in units) / n
    de = sum((a - b) ** 2 for i, a in enumerate(vals) for j, b in enumerate(vals) if i != j) / (n * (n - 1))
    return None if de == 0 else 1.0 - do / de


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scores")
    ap.add_argument("--agg", choices=("auto", "mean", "median", "trimmed"), default="auto")
    ap.add_argument("--trim", type=float, default=0.2)
    ap.add_argument("--normalize", choices=("none", "z"), default="none")
    ap.add_argument("--disagree", type=float, default=2.0, help="range (scale points) that flags disagreement")
    ap.add_argument("--graft-step", type=float, default=1.0)
    a = ap.parse_args(argv)
    d = load(a.scores)
    lo, hi = float(d["scale"][0]), float(d["scale"][1])
    crit = d["criteria"]
    raw = d["scores"]
    judges = sorted(raw)
    cands = sorted({c for j in judges for c in raw[j]})
    S = zscore(raw, lo, hi) if a.normalize == "z" else raw
    how = a.agg
    if how == "auto":
        how = "median" if len(judges) <= 4 else "trimmed"

    missing = [(j, c, k) for j in judges for c in cands for k in crit if k not in S.get(j, {}).get(c, {})]
    if missing:
        raise SystemExit("missing scores (judge, candidate, criterion): %s" % missing[:10])

    per_crit: Dict[str, dict] = {}
    totals: Dict[str, float] = {}
    flags = []
    for c in cands:
        per_crit[c] = {}
        tot = 0.0
        for k, w in crit.items():
            xs = [float(S[j][c][k]) for j in judges]
            rx = [float(raw[j][c][k]) for j in judges]
            agg = aggregate(xs, how, a.trim)
            per_crit[c][k] = {"scores": rx, "agg": round(agg, 3), "range": max(rx) - min(rx)}
            if max(rx) - min(rx) >= a.disagree:
                flags.append({"candidate": c, "criterion": k, "scores": dict(zip(judges, rx))})
            tot += w * (agg - lo) / (hi - lo)
        totals[c] = round(100.0 * tot, 2)

    per_judge = {j: {c: 100.0 * sum(w * (float(S[j][c][k]) - lo) / (hi - lo) for k, w in crit.items())
                     for c in cands} for j in judges}

    disq = []
    gates = d.get("gates") or {}
    if gates:
        for c in cands:
            names = sorted({g for j in gates for g in gates[j].get(c, {})})
            for g in names:
                votes = [bool(gates[j][c][g]) for j in gates if g in gates[j].get(c, {})]
                if votes and sum(1 for v in votes if not v) * 2 > len(votes):
                    disq.append({"candidate": c, "gate": g, "fail_votes": sum(1 for v in votes if not v),
                                 "of": len(votes)})
    out_c = {x["candidate"] for x in disq}
    ranking = sorted([c for c in cands if c not in out_c], key=lambda c: -totals[c])
    res = {"aggregator": how, "normalize": a.normalize, "judges": judges, "weights": crit,
           "totals": totals, "ranking": ranking, "disqualified": disq, "per_criterion": per_crit,
           "per_judge_totals": {j: {c: round(v, 2) for c, v in t.items()} for j, t in per_judge.items()},
           "disagreements": flags}
    w = kendall_w(per_judge, cands)
    res["kendall_w"] = None if w is None else round(w, 3)
    al = kripp_alpha_interval([[float(raw[j][c][k]) for j in judges] for c in cands for k in crit])
    res["krippendorff_alpha"] = None if al is None else round(al, 3)
    if len(ranking) >= 2:
        win, run = ranking[0], ranking[1]
        deltas = [per_judge[j][win] - per_judge[j][run] for j in judges]
        mean = sum(deltas) / len(deltas)
        sd = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
        se = sd / math.sqrt(len(deltas)) if len(deltas) > 1 else float("inf")
        res["winner"], res["runner_up"] = win, run
        res["margin_points"] = round(totals[win] - totals[run], 2)
        res["paired_deltas"] = dict(zip(judges, [round(x, 2) for x in deltas]))
        res["paired_t"] = None if se in (0.0, float("inf")) else round(mean / se, 2)
        res["unanimous_order"] = all(x > 0 for x in deltas)
        res["decisive"] = bool(res["unanimous_order"] and res["margin_points"] >= 5.0)
        grafts = []
        for c in ranking[1:]:
            for k in crit:
                adv = per_crit[c][k]["agg"] - per_crit[win][k]["agg"]
                if adv >= a.graft_step:
                    grafts.append({"from": c, "criterion": k, "advantage": round(adv, 3),
                                   "weighted_gain_points": round(100.0 * crit[k] * adv / (hi - lo), 2)})
        res["graft_candidates"] = sorted(grafts, key=lambda g: -g["weighted_gain_points"])
    json.dump(res, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
