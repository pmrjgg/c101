#!/usr/bin/env python3
"""Tally mediator ballots: plurality, Borda, approval, Schulze, log opinion pool.

Stdlib only, Python 3.9+.  Deterministic: no randomness, ties are reported, never broken.

Input (JSON file or '-' for stdin):
{
  "candidates": ["S1", "S2", "S3"],
  "exclusive": true,                 # candidates are mutually exclusive answers (default true)
  "ballots": [
    {"voter": "V1",
     "ranking": ["S2", ["S1", "S3"]],  # best first; a nested list is a tie; unranked = tied last
     "approvals": ["S2"],
     "p_correct": {"S1": 0.3, "S2": 0.8, "S3": 0.2},
     "weight": 1.0,                  # optional calibration weight (default 1)
     "author_of": "S1"}              # optional; enables the --no-self robustness run
  ]
}

Usage:
  python3 tally.py ballots.json --method schulze           # one method + robustness block
  python3 tally.py ballots.json --method all               # every method side by side
  python3 tally.py ballots.json --method logpool --extremize 1.3 --clip 0.02
  python3 tally.py ballots.json --method borda --no-self   # drop each voter's own candidate
Output: JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Dict, List, Optional, Sequence, Tuple

METHODS = ("plurality", "borda", "approval", "schulze", "logpool")
NEAR_TIE = {"plurality": 0.2, "approval": 0.2, "borda": 0.1, "schulze": 0.2, "logpool": 0.1}
EPS = 1e-12


# ----------------------------------------------------------------------------- input
def load(path: str) -> dict:
    fh = sys.stdin if path == "-" else open(path, encoding="utf-8")
    with fh:
        data = json.load(fh)
    cands = data.get("candidates")
    if not cands:
        seen: List[str] = []
        for b in data.get("ballots", []):
            for g in _groups(b.get("ranking", [])):
                for c in g:
                    if c not in seen:
                        seen.append(c)
        cands = seen
    data["candidates"] = [str(c) for c in cands]
    data.setdefault("exclusive", True)
    return data


def _groups(ranking: Sequence) -> List[List[str]]:
    return [[str(x) for x in g] if isinstance(g, list) else [str(g)] for g in ranking]


def tiers(ballot: dict, cands: List[str], drop: Optional[str] = None) -> List[List[str]]:
    """Ranking as tiers of tied candidates, best first; unranked candidates form a last tier."""
    out, placed = [], set()
    for g in _groups(ballot.get("ranking", [])):
        g = [c for c in g if c in cands and c not in placed and c != drop]
        if g:
            out.append(g)
            placed.update(g)
    rest = [c for c in cands if c not in placed and c != drop]
    if rest:
        out.append(rest)
    return out


def weight(b: dict) -> float:
    w = float(b.get("weight", 1.0))
    if w < 0:
        raise SystemExit("negative weight for voter %r" % b.get("voter"))
    return w


# ----------------------------------------------------------------------------- methods
def plurality(data: dict, no_self: bool) -> Dict[str, float]:
    cands = data["candidates"]
    s = {c: 0.0 for c in cands}
    for b in data["ballots"]:
        t = tiers(b, cands, b.get("author_of") if no_self else None)
        if t:
            for c in t[0]:
                s[c] += weight(b) / len(t[0])
    return s


def borda(data: dict, no_self: bool) -> Dict[str, float]:
    """n-1 points for first place ... 0 for last; tied candidates share the average.
    With --no-self the voter's own candidate gets the neutral midpoint (n-1)/2."""
    cands = data["candidates"]
    n = len(cands)
    s = {c: 0.0 for c in cands}
    for b in data["ballots"]:
        own = b.get("author_of") if no_self else None
        w = weight(b)
        pos = 0
        for g in tiers(b, cands):
            pts = sum(n - 1 - (pos + i) for i in range(len(g))) / len(g)
            for c in g:
                s[c] += w * ((n - 1) / 2.0 if c == own else pts)
            pos += len(g)
    return s


def approval(data: dict, no_self: bool) -> Dict[str, float]:
    cands = data["candidates"]
    s = {c: 0.0 for c in cands}
    for b in data["ballots"]:
        own = b.get("author_of") if no_self else None
        for c in set(map(str, b.get("approvals", []))):
            if c in s and c != own:
                s[c] += weight(b)
    return s


def pairwise(data: dict, no_self: bool) -> Dict[str, Dict[str, float]]:
    """d[x][y] = total weight of voters ranking x strictly above y (own-candidate pairs abstain)."""
    cands = data["candidates"]
    d = {x: {y: 0.0 for y in cands} for x in cands}
    for b in data["ballots"]:
        own = b.get("author_of") if no_self else None
        rank = {}
        for i, g in enumerate(tiers(b, cands)):
            for c in g:
                rank[c] = i
        for x in cands:
            for y in cands:
                if x != y and x != own and y != own and rank[x] < rank[y]:
                    d[x][y] += weight(b)
    return d


def schulze(data: dict, no_self: bool) -> Tuple[Dict[str, float], dict]:
    """Winning-votes link strength + Floyd-Warshall widest paths."""
    cands = data["candidates"]
    d = pairwise(data, no_self)
    p = {x: {y: 0.0 for y in cands} for x in cands}
    for x in cands:
        for y in cands:
            if x != y and d[x][y] > d[y][x]:
                p[x][y] = d[x][y]
    for i in cands:
        for j in cands:
            if j == i:
                continue
            for k in cands:
                if k == i or k == j:
                    continue
                p[j][k] = max(p[j][k], min(p[j][i], p[i][k]))
    # X beats Y iff p[X][Y] > p[Y][X] (a strict partial order).  Each tier is the set of remaining
    # candidates beaten by no remaining candidate; the first tier is the Schulze winner set.  A count of
    # strongest-path wins is NOT equivalent: in 2xA>B>C, 2xB>C>A, 1xC>A>B it names B alone although A and
    # B are both unbeaten.  The wins count is kept only as a display score.
    wins = {x: float(sum(1 for y in cands if y != x and p[x][y] > p[y][x])) for x in cands}
    tiers_: List[List[str]] = []
    rest = list(cands)
    while rest:
        top = [x for x in rest if all(y == x or p[x][y] >= p[y][x] for y in rest)] or list(rest)
        tiers_.append(sorted(top))
        rest = [x for x in rest if x not in top]
    condorcet = [x for x in cands if all(d[x][y] > d[y][x] for y in cands if y != x)]
    return wins, {"pairwise": d, "strongest_paths": p, "tiers": tiers_,
                  "condorcet_winner": condorcet[0] if condorcet else None}


def logpool(data: dict, no_self: bool, d_extremize: float, clip: float) -> Dict[str, float]:
    """Weighted geometric pool of p_correct.  Exclusive: normalised distribution over candidates.
    Non-exclusive: per-candidate logit pool, P = sigmoid(d * sum_i w_i logit p_i / sum_i w_i)."""
    cands, excl = data["candidates"], bool(data.get("exclusive", True))
    acc = {c: [0.0, 0.0] for c in cands}  # [sum w*log-or-logit, sum w]
    for b in data["ballots"]:
        pc = {str(k): float(v) for k, v in (b.get("p_correct") or {}).items() if str(k) in acc}
        if not pc:
            continue
        own = b.get("author_of") if no_self else None
        pc = {k: min(1 - clip, max(clip, v)) for k, v in pc.items()}
        if excl:
            z = sum(pc.values())
            pc = {k: v / z for k, v in pc.items()}
        w = weight(b)
        for c, v in pc.items():
            if c == own:
                continue
            acc[c][0] += w * (math.log(v) if excl else math.log(v / (1 - v)))
            acc[c][1] += w
    score = {c: (a / ws if ws > 0 else None) for c, (a, ws) in acc.items()}
    if excl:
        known = {c: s for c, s in score.items() if s is not None}
        if not known:
            return {c: 0.0 for c in cands}
        m = max(known.values())
        e = {c: math.exp(d_extremize * (s - m)) for c, s in known.items()}
        z = sum(e.values())
        return {c: (e[c] / z if c in e else 0.0) for c in cands}
    return {c: (1 / (1 + math.exp(-d_extremize * s)) if s is not None else 0.0) for c, s in score.items()}


# ----------------------------------------------------------------------------- tally
def total_weight(data: dict) -> float:
    return sum(weight(b) for b in data["ballots"]) or 1.0


def order(scores: Dict[str, float]) -> List[List[str]]:
    """Group candidates into tiers by descending score (exact ties share a tier)."""
    out: List[List[str]] = []
    for c in sorted(scores, key=lambda c: (-scores[c], c)):
        if out and abs(scores[out[-1][0]] - scores[c]) < 1e-9:
            out[-1].append(c)
        else:
            out.append([c])
    return out


def run(data: dict, method: str, no_self: bool = False, d_ext: float = 1.0, clip: float = 0.02) -> dict:
    W, n = total_weight(data), len(data["candidates"])
    extra: dict = {}
    if method == "plurality":
        s = plurality(data, no_self)
    elif method == "borda":
        s = borda(data, no_self)
    elif method == "approval":
        s = approval(data, no_self)
    elif method == "schulze":
        s, extra = schulze(data, no_self)
    elif method == "logpool":
        s = logpool(data, no_self, d_ext, clip)
    else:
        raise SystemExit("unknown method %r" % method)
    tiers_ = extra["tiers"] if method == "schulze" else order(s)
    top = tiers_[0]
    res = {"method": method, "scores": {c: round(v, 4) for c, v in s.items()},
           "ranking": tiers_, "winner": top[0] if len(top) == 1 else None, "tie": top if len(top) > 1 else []}
    runner = top[1] if len(top) > 1 else (tiers_[1][0] if len(tiers_) > 1 else None)
    if method == "schulze" and len(top) == 1 and len(tiers_) > 1:
        # Runner-up: the second-tier candidate with the smallest strongest-path deficit to the winner.
        sp, w = extra["strongest_paths"], top[0]
        runner = sorted(tiers_[1], key=lambda x: (sp[w][x] - sp[x][w], x))[0]
    if runner is None:
        margin = 1.0
    elif len(top) > 1:
        margin = 0.0
    elif method == "plurality" or method == "approval":
        margin = (s[top[0]] - s[runner]) / W
    elif method == "borda":
        margin = (s[top[0]] - s[runner]) / (W * max(1, n - 1))
    elif method == "schulze":
        sp = extra["strongest_paths"]
        margin = (sp[top[0]][runner] - sp[runner][top[0]]) / W   # strongest paths, never negative
        extra = {"condorcet_winner": extra["condorcet_winner"],
                 "pairwise": {x: {y: round(v, 4) for y, v in r.items()} for x, r in extra["pairwise"].items()},
                 "strongest_paths": {x: {y: round(v, 4) for y, v in r.items()} for x, r in extra["strongest_paths"].items()}}
    else:
        margin = s[top[0]] - s[runner]
    res["runner_up"] = runner
    res["margin"] = round(margin, 4)
    res["near_tie_threshold"] = NEAR_TIE[method]
    res.update(extra)
    return res


def robustness(data: dict, method: str, d_ext: float, clip: float) -> dict:
    base = run(data, method, False, d_ext, clip)
    loo = []
    for i, b in enumerate(data["ballots"]):
        sub = dict(data, ballots=[x for j, x in enumerate(data["ballots"]) if j != i])
        r = run(sub, method, False, d_ext, clip) if sub["ballots"] else {"winner": None, "tie": []}
        loo.append({"dropped": b.get("voter", "#%d" % i), "winner": r["winner"], "tie": r["tie"]})
    stable = sum(1 for r in loo if r["winner"] == base["winner"] and base["winner"] is not None)
    out = {"leave_one_out": loo, "loo_stability": round(stable / max(1, len(loo)), 3)}
    if any(b.get("author_of") for b in data["ballots"]):
        ns = run(data, method, True, d_ext, clip)
        out["no_self_winner"] = ns["winner"]
        out["no_self_tie"] = ns["tie"]
        selfrank = []
        for b in data["ballots"]:
            own = b.get("author_of")
            if own:
                t = tiers(b, data["candidates"])
                pos = next((i + 1 for i, g in enumerate(t) if own in g), None)
                selfrank.append({"voter": b.get("voter"), "own": own, "own_tier": pos})
        out["self_rank"] = selfrank
    near = (base["winner"] is None or base["margin"] < NEAR_TIE[method] or out["loo_stability"] < 1.0
            or (method == "schulze" and base.get("condorcet_winner") is None))
    out["near_tie"] = bool(near)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ballots")
    ap.add_argument("--method", default="schulze", choices=METHODS + ("all",))
    ap.add_argument("--no-self", action="store_true", help="drop each voter's own candidate from their ballot")
    ap.add_argument("--extremize", type=float, default=1.0, help="log-pool exponent d (1 = none)")
    ap.add_argument("--clip", type=float, default=0.02, help="clip probabilities to [clip, 1-clip]")
    a = ap.parse_args(argv)
    data = load(a.ballots)
    if len(data["candidates"]) < 2 or not data.get("ballots"):
        raise SystemExit("need >=2 candidates and >=1 ballot")
    methods = METHODS if a.method == "all" else (a.method,)
    out = {"candidates": data["candidates"], "voters": len(data["ballots"]), "total_weight": total_weight(data),
           "results": {}}
    for m in methods:
        if m == "logpool" and not any(b.get("p_correct") for b in data["ballots"]):
            out.setdefault("skipped", []).append("logpool: no p_correct in any ballot")
            continue
        if m == "approval" and not any(b.get("approvals") for b in data["ballots"]):
            out.setdefault("skipped", []).append("approval: no approvals in any ballot")
            continue
        r = run(data, m, a.no_self, a.extremize, a.clip)
        r["robustness"] = robustness(data, m, a.extremize, a.clip)
        out["results"][m] = r
    winners = {m: r["winner"] for m, r in out["results"].items()}
    out["method_agreement"] = winners
    out["method_sensitive"] = len(set(winners.values())) > 1
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
