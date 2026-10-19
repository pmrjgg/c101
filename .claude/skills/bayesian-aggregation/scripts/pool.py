#!/usr/bin/env python3
"""Opinion pooling toolkit: linear/log pools, extremizing, calibration weights, N_eff, verbal mapping.

Stdlib only, Python 3.9+.  Deterministic.  All output is JSON on stdout.

Subcommands
  binary     --p 0.6 0.7 0.9 [--w 1 1 2] [--d 1.5] [--clip 0.02]
  multi      --dist 0.5,0.3,0.2 0.6,0.3,0.1 [--w ...] [--d 1.0] [--labels A,B,C]
  clusters   --p 0.9 0.9 0.6 --cluster m1 m1 m2 [--rho 0.8] [--w ...]
  weights    --ledger ledger.jsonl [--scheme skill|hedge] [--shrink 20] [--cap 4] [--since 2026-01-01]
  recal      --ledger ledger.jsonl --agent NAME       (fit logit(p') = a + b*logit(p))
  neff       --n 5 --rho 0.6
  verbal     "very likely" ["roughly even chance" ...]
  quantiles  --q 80,120,200 100,150,260 90,130,400 [--levels 0.1,0.5,0.9]

Ledger format (one JSON object per line, binary events):
  {"agent": "fact-checker", "model": "sonnet", "qid": "q-0193", "p": 0.8, "outcome": 1, "resolved": "2026-09-02"}
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Dict, List, Optional, Sequence

# ICD 203 bands (US ODNI, 2015) -> midpoint; plus common LLM phrasings mapped to the nearest band.
VERBAL = {
    "almost no chance": 0.03, "remote": 0.03,
    "very unlikely": 0.12, "highly improbable": 0.12,
    "unlikely": 0.32, "improbable": 0.32, "probably not": 0.32,
    "roughly even chance": 0.50, "even chance": 0.50, "about as likely as not": 0.50, "toss-up": 0.50,
    "likely": 0.67, "probable": 0.67, "probably": 0.67,
    "very likely": 0.87, "highly probable": 0.87,
    "almost certain": 0.97, "almost certainly": 0.97, "nearly certain": 0.97,
}


def clip(p: float, c: float) -> float:
    return min(1.0 - c, max(c, p))


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def norm_w(w: Optional[Sequence[float]], n: int) -> List[float]:
    w = [1.0] * n if not w else [float(x) for x in w]
    if len(w) != n:
        raise SystemExit("need %d weights, got %d" % (n, len(w)))
    s = sum(w)
    return [x / s for x in w]


def out(o: dict) -> None:
    json.dump(o, sys.stdout, indent=1)
    sys.stdout.write("\n")


# ----------------------------------------------------------------------------- pools
def cmd_binary(a) -> None:
    ps = [clip(float(p), a.clip) for p in a.p]
    w = norm_w(a.w, len(ps))
    lin = sum(wi * p for wi, p in zip(w, ps))
    lg = sum(wi * logit(p) for wi, p in zip(w, ps))
    res = {"inputs": ps, "weights": [round(x, 4) for x in w],
           "linear": round(lin, 4), "log_pool": round(sigmoid(lg), 4),
           "spread": round(max(ps) - min(ps), 4)}
    if a.d and a.d != 1.0:
        res["extremized_log_pool"] = round(sigmoid(a.d * lg), 4)
        res["d"] = a.d
    if res["spread"] >= 0.4:
        res["warning"] = "spread >= 0.4: find the crux before trusting any pool"
    out(res)


def cmd_multi(a) -> None:
    dists = [[float(x) for x in s.split(",")] for s in a.dist]
    k = len(dists[0])
    if any(len(d) != k for d in dists):
        raise SystemExit("all distributions need the same number of outcomes")
    dists = [[clip(x, a.clip) for x in d] for d in dists]
    dists = [[x / sum(d) for x in d] for d in dists]
    w = norm_w(a.w, len(dists))
    lin = [sum(w[i] * dists[i][j] for i in range(len(dists))) for j in range(k)]
    lg = [a.d * sum(w[i] * math.log(dists[i][j]) for i in range(len(dists))) for j in range(k)]
    m = max(lg)
    e = [math.exp(x - m) for x in lg]
    z = sum(e)
    labels = a.labels.split(",") if a.labels else ["o%d" % j for j in range(k)]
    out({"labels": labels, "weights": [round(x, 4) for x in w],
         "linear": dict(zip(labels, [round(x, 4) for x in lin])),
         "log_pool": dict(zip(labels, [round(x / z, 4) for x in e])), "d": a.d})


def cmd_clusters(a) -> None:
    """Pool within each correlated cluster (log pool), give the cluster an effective weight
    sum(w) * neff(m, rho) / m, then log-pool across clusters."""
    ps = [clip(float(p), a.clip) for p in a.p]
    if len(a.cluster) != len(ps):
        raise SystemExit("--cluster needs one label per probability")
    w = [1.0] * len(ps) if not a.w else [float(x) for x in a.w]
    groups: Dict[str, List[int]] = {}
    for i, g in enumerate(a.cluster):
        groups.setdefault(g, []).append(i)
    rows, num, den = [], 0.0, 0.0
    for g, idx in groups.items():
        sw = sum(w[i] for i in idx)
        inner = sum(w[i] * logit(ps[i]) for i in idx) / sw
        m = len(idx)
        neff = m / (1.0 + (m - 1) * a.rho)
        ew = sw * neff / m
        rows.append({"cluster": g, "members": m, "pooled": round(sigmoid(inner), 4),
                     "neff": round(neff, 3), "effective_weight": round(ew, 3)})
        num += ew * inner
        den += ew
    naive = sum(logit(p) for p in ps) / len(ps)
    out({"clusters": rows, "cluster_aware_log_pool": round(sigmoid(num / den), 4),
         "naive_equal_log_pool": round(sigmoid(naive), 4), "rho": a.rho})


# ----------------------------------------------------------------------------- calibration
def read_ledger(path: str, since: Optional[str]) -> List[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            if r.get("outcome") not in (0, 1) or r.get("p") is None:
                continue
            if since and str(r.get("resolved", "")) < since:
                continue
            rows.append(r)
    if not rows:
        raise SystemExit("ledger has no resolved rows")
    return rows


def cmd_weights(a) -> None:
    rows = read_ledger(a.ledger, a.since)
    by: Dict[str, List[dict]] = {}
    for r in rows:
        by.setdefault(r["agent"], []).append(r)
    base = sum(r["outcome"] for r in rows) / len(rows)
    bs_ref = base * (1 - base) or 0.25
    stats = {}
    for ag, rs in by.items():
        bs = sum((float(r["p"]) - r["outcome"]) ** 2 for r in rs) / len(rs)
        ll = -sum(math.log(clip(float(r["p"]) if r["outcome"] else 1 - float(r["p"]), 0.01)) for r in rs) / len(rs)
        stats[ag] = {"n": len(rs), "brier": round(bs, 4), "log_loss": round(ll, 4),
                     "bss": round(1 - bs / bs_ref, 4), "cum_brier": bs * len(rs)}
    n_ag = len(stats)
    raw: Dict[str, float] = {}
    if a.scheme == "hedge":
        T = max(s["n"] for s in stats.values())
        eta = math.sqrt(8 * math.log(max(2, n_ag)) / T)
        # compare on per-question average loss scaled to T so agents with fewer rows are not favoured
        for ag, s in stats.items():
            raw[ag] = math.exp(-eta * s["brier"] * T)
        stats["_eta"] = round(eta, 4)
    else:
        for ag, s in stats.items():
            raw[ag] = max(0.05, s["bss"])
    z = sum(raw.values())
    uniform = 1.0 / n_ag
    w = {}
    for ag, v in raw.items():
        n = stats[ag]["n"]
        w[ag] = (n * (v / z) + a.shrink * uniform) / (n + a.shrink)
    lo = max(w.values()) / a.cap
    w = {ag: max(v, lo) for ag, v in w.items()}
    z = sum(w.values())
    w = {ag: round(v / z, 4) for ag, v in w.items()}
    for s in stats.values():
        if isinstance(s, dict):
            s.pop("cum_brier", None)
    out({"base_rate": round(base, 4), "brier_reference": round(bs_ref, 4), "scheme": a.scheme,
         "shrink_k": a.shrink, "cap": a.cap, "stats": stats, "weights": w})


def cmd_recal(a) -> None:
    rows = [r for r in read_ledger(a.ledger, a.since) if r["agent"] == a.agent]
    if len(rows) < 30:
        out({"agent": a.agent, "n": len(rows), "a": 0.0, "b": 1.0,
             "note": "fewer than 30 resolved rows: do not recalibrate, use identity"})
        return
    xs = [logit(clip(float(r["p"]), 0.01)) for r in rows]
    ys = [float(r["outcome"]) for r in rows]
    A, B = 0.0, 1.0
    for _ in range(50):  # Newton-Raphson for 2-parameter logistic regression
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            p = sigmoid(A + B * x)
            r = y - p
            v = p * (1 - p)
            g0 += r
            g1 += r * x
            h00 += v
            h01 += v * x
            h11 += v * x * x
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        dA = (h11 * g0 - h01 * g1) / det
        dB = (-h01 * g0 + h00 * g1) / det
        A, B = A + dA, B + dB
        if abs(dA) + abs(dB) < 1e-8:
            break
    out({"agent": a.agent, "n": len(rows), "a": round(A, 4) + 0.0, "b": round(B, 4) + 0.0,
         "reading": "b<1 overconfident (shrink), b>1 underconfident, a>0 biased low",
         "apply": "p' = sigmoid(a + b * logit(p))"})


def cmd_neff(a) -> None:
    n, rho = a.n, a.rho
    out({"n": n, "rho": rho, "neff": round(n / (1.0 + (n - 1) * rho), 4)})


def cmd_verbal(a) -> None:
    res = {}
    for phrase in a.phrases:
        k = phrase.strip().lower()
        res[phrase] = VERBAL.get(k)
    out({"mapping": res, "scale": "ICD 203 band midpoints", "unknown": [p for p, v in res.items() if v is None]})


def cmd_quantiles(a) -> None:
    levels = [float(x) for x in a.levels.split(",")]
    qs = [[float(x) for x in s.split(",")] for s in a.q]
    if any(len(q) != len(levels) for q in qs):
        raise SystemExit("each --q needs one value per level")
    w = norm_w(a.w, len(qs))
    vinc = [sum(w[i] * qs[i][j] for i in range(len(qs))) for j in range(len(levels))]
    med = []
    for j in range(len(levels)):
        col = sorted(q[j] for q in qs)
        m = len(col)
        med.append(col[m // 2] if m % 2 else (col[m // 2 - 1] + col[m // 2]) / 2.0)
    out({"levels": levels, "vincentized_mean": [round(x, 4) for x in vinc],
         "quantile_median": [round(x, 4) for x in med],
         "envelope": [[min(q[j] for q in qs), max(q[j] for q in qs)] for j in range(len(levels))]})


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("binary")
    b.add_argument("--p", nargs="+", type=float, required=True)
    b.add_argument("--w", nargs="+", type=float)
    b.add_argument("--d", type=float, default=1.0)
    b.add_argument("--clip", type=float, default=0.02)
    m = sp.add_parser("multi")
    m.add_argument("--dist", nargs="+", required=True)
    m.add_argument("--w", nargs="+", type=float)
    m.add_argument("--d", type=float, default=1.0)
    m.add_argument("--clip", type=float, default=0.02)
    m.add_argument("--labels")
    c = sp.add_parser("clusters")
    c.add_argument("--p", nargs="+", type=float, required=True)
    c.add_argument("--cluster", nargs="+", required=True)
    c.add_argument("--rho", type=float, default=0.8)
    c.add_argument("--w", nargs="+", type=float)
    c.add_argument("--clip", type=float, default=0.02)
    w = sp.add_parser("weights")
    w.add_argument("--ledger", required=True)
    w.add_argument("--scheme", choices=("skill", "hedge"), default="skill")
    w.add_argument("--shrink", type=float, default=20.0)
    w.add_argument("--cap", type=float, default=4.0)
    w.add_argument("--since")
    r = sp.add_parser("recal")
    r.add_argument("--ledger", required=True)
    r.add_argument("--agent", required=True)
    r.add_argument("--since")
    n = sp.add_parser("neff")
    n.add_argument("--n", type=int, required=True)
    n.add_argument("--rho", type=float, required=True)
    v = sp.add_parser("verbal")
    v.add_argument("phrases", nargs="+")
    q = sp.add_parser("quantiles")
    q.add_argument("--q", nargs="+", required=True)
    q.add_argument("--levels", default="0.1,0.5,0.9")
    q.add_argument("--w", nargs="+", type=float)
    a = ap.parse_args(argv)
    {"binary": cmd_binary, "multi": cmd_multi, "clusters": cmd_clusters, "weights": cmd_weights,
     "recal": cmd_recal, "neff": cmd_neff, "verbal": cmd_verbal, "quantiles": cmd_quantiles}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
