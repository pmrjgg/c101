#!/usr/bin/env python3
"""Delphi round statistics (stdlib only, Python 3.9+).

Usage:
  python3 delphi_stats.py ROUND_DIR [--prev PREV_ROUND_DIR] [--kind continuous|probability|ranking]
                          [--rel-iqr 0.2] [--prob-iqr 0.10] [--logodds-iqr 0.5] [--w 0.7]
                          [--move 0.15]
                          [--stable-share 0.15] [--json]

ROUND_DIR holds one JSON file per panelist (P1.json, P2.json, ...); only P*.json is read, and files
without a p50 or ranking key are skipped with a note on stderr. Accepted shapes:
  continuous / probability: {"panelist": "P3", "p10": 6, "p50": 10, "p90": 18}
                            (probability: values in (0, 1); "p50" is the probability; when the
                            median is < 0.1 or > 0.9 consensus uses the log-odds IQR)
  ranking:                  {"panelist": "P3", "ranking": ["opt-b", "opt-a", "opt-c"]}
Panelist ids must be stable across rounds (keep the identity map private; ids here are anonymous).

Prints the controlled-feedback statistics, consensus and stability verdicts, and a bimodality flag.
Quartiles use the inclusive (type 7, numpy 'linear') method so results match common tooling.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
import sys
from typing import Dict, List, Optional

TOL = 1e-9  # float slack so 0.30000000000000004 - 0.2 still meets a 0.10 threshold


def load(round_dir: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for f in sorted(glob.glob(os.path.join(round_dir, "P*.json"))):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        if not isinstance(d, dict) or ("p50" not in d and "ranking" not in d):
            print("skipped %s: no p50 or ranking key" % f, file=sys.stderr)
            continue
        pid = d.get("panelist") or os.path.splitext(os.path.basename(f))[0]
        out[pid] = d
    if not out:
        sys.exit("no P*.json panelist files in %s" % round_dir)
    return out


def quartiles(xs: List[float]) -> List[float]:
    if len(xs) == 1:
        return [xs[0]] * 3
    return statistics.quantiles(xs, n=4, method="inclusive")


def bimodal(xs: List[float]) -> Optional[dict]:
    """Largest-gap split; flags when both sides have >=2 members and the gap exceeds the
    spread of each side (a deliberately conservative, explainable rule)."""
    s = sorted(xs)
    if len(s) < 4:
        return None
    gaps = [(s[i + 1] - s[i], i) for i in range(len(s) - 1)]
    g, i = max(gaps)
    lo, hi = s[: i + 1], s[i + 1:]
    if len(lo) < 2 or len(hi) < 2:
        return None
    spread = max(lo[-1] - lo[0], hi[-1] - hi[0])
    if g > spread:
        return {"low_cluster": lo, "high_cluster": hi, "gap": g}
    return None


def log_odds(ps: List[float]) -> List[float]:
    eps = 1e-6
    return [math.log(min(max(p, eps), 1 - eps) / (1 - min(max(p, eps), 1 - eps))) for p in ps]


def geo_mean_odds(ps: List[float]) -> float:
    logs = log_odds(ps)
    g = math.exp(sum(logs) / len(logs))
    return g / (1 + g)


def kendall_w(rankings: List[List[str]]) -> float:
    items = sorted(set(rankings[0]))
    m, n = len(rankings), len(items)
    if n < 2:
        return 1.0
    totals = {it: 0.0 for it in items}
    for r in rankings:
        if sorted(r) != items:
            sys.exit("all rankings must rank the same item set (no ties supported)")
        for pos, it in enumerate(r, start=1):
            totals[it] += pos
    mean = m * (n + 1) / 2.0
    s = sum((t - mean) ** 2 for t in totals.values())
    return 12.0 * s / (m * m * (n ** 3 - n))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("round_dir")
    ap.add_argument("--prev")
    ap.add_argument("--kind", default="continuous", choices=["continuous", "probability", "ranking"])
    ap.add_argument("--rel-iqr", type=float, default=0.2, help="consensus threshold, continuous")
    ap.add_argument("--prob-iqr", type=float, default=0.10, help="consensus threshold, probability")
    ap.add_argument("--logodds-iqr", type=float, default=0.5,
                    help="consensus threshold in log-odds, probability with median < 0.1 or > 0.9")
    ap.add_argument("--w", type=float, default=0.7, help="consensus threshold, Kendall W")
    ap.add_argument("--move", type=float, default=0.15, help="relative move counted as a change")
    ap.add_argument("--stable-share", type=float, default=0.15,
                    help="stable when at most this share of panelists moved")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cur = load(a.round_dir)
    prev = load(a.prev) if a.prev else None
    rep: dict = {"n": len(cur), "kind": a.kind}

    if a.kind == "ranking":
        w = kendall_w([d["ranking"] for d in cur.values()])
        rep.update({"kendall_w": round(w, 4), "consensus": w >= a.w - TOL})
        if prev:
            wp = kendall_w([d["ranking"] for d in prev.values()])
            rep["delta_w"] = round(w - wp, 4)
            rep["stable"] = abs(w - wp) < 0.05
    else:
        ids = sorted(cur)
        x = [float(cur[i]["p50"]) for i in ids]
        q1, med, q3 = quartiles(x)
        iqr = q3 - q1
        rep.update({"values_sorted": sorted(x), "median": med, "q1": q1, "q3": q3, "iqr": round(iqr, 6),
                    "min": min(x), "max": max(x)})
        if a.kind == "continuous":
            rel = iqr / abs(med) if med else float("inf")
            rep["rel_iqr"] = round(rel, 4)
            rep["consensus"] = rel <= a.rel_iqr + TOL
        else:
            rep["geo_mean_odds"] = round(geo_mean_odds(x), 4)
            if med < 0.1 or med > 0.9:
                lq1, _, lq3 = quartiles(log_odds(x))
                rep["logodds_iqr"] = round(lq3 - lq1, 4)
                rep["consensus"] = lq3 - lq1 <= a.logodds_iqr + TOL
            else:
                rep["consensus"] = iqr <= a.prob_iqr + TOL
        p10s = [float(cur[i]["p10"]) for i in ids if "p10" in cur[i]]
        p90s = [float(cur[i]["p90"]) for i in ids if "p90" in cur[i]]
        if p10s and p90s:
            rep["consensus_interval"] = [statistics.median(p10s), statistics.median(p90s)]
            rep["disagreement_envelope"] = [min(p10s), max(p90s)]
        outside = [i for i in ids if float(cur[i]["p50"]) < q1 or float(cur[i]["p50"]) > q3]
        rep["outside_iqr"] = outside
        rep["bimodal"] = bimodal(x)
        if prev:
            common = [i for i in ids if i in prev]
            moved = []
            for i in common:
                old, new = float(prev[i]["p50"]), float(cur[i]["p50"])
                base = abs(old) if old else 1.0
                if abs(new - old) / base > a.move:
                    moved.append(i)
            pmed = statistics.median([float(prev[i]["p50"]) for i in prev])
            rep["median_shift_rel"] = round(abs(med - pmed) / abs(pmed), 4) if pmed else None
            rep["moved"] = moved
            rep["moved_share"] = round(len(moved) / len(common), 4) if common else None
            rep["stable"] = bool(common) and len(moved) / len(common) <= a.stable_share + TOL

    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        for k, v in rep.items():
            print("%-22s %s" % (k, v))


if __name__ == "__main__":
    main()
