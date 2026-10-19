#!/usr/bin/env python3
"""Morphological box with cross-consistency pruning and weighted scoring (stdlib only, Python 3.9+).

Usage:
  python3 morph_box.py BOX.json [--top 10] [--diverse 5] [--json]

BOX.json:
{
  "parameters": {"selection": ["all", "affected", "ml-predicted"], "execution": ["single", "sharded"]},
  "incompatible": [["selection=ml-predicted", "execution=single", "reason text"]],
  "requires":     [["execution=remote", "cache=remote", "reason text"]],
  "criteria": {"speed": 0.5, "confidence": 0.3, "cost": 0.2},
  "scores": {"selection=affected": {"speed": 4, "confidence": 3, "cost": 4}}
}

- incompatible: pairs that may not co-occur (cross-consistency assessment, Ritchey-style GMA).
- requires: "A requires B" (if A is chosen, B must be chosen for B's parameter).
- scores: per value, per criterion, 1..5 (missing = 3, neutral). A configuration's score is the
  weighted sum over criteria of the mean of its values' scores. Additive scoring ignores
  interactions; treat the ranking as a shortlist generator, not a verdict.

Prints box size, pairwise-matrix size, surviving count, top-N by score, and a diverse shortlist
(greedy max-min Hamming distance among the top quartile).
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from typing import Dict, List, Tuple


def parse_ref(ref: str, params: Dict[str, List[str]]) -> Tuple[str, str]:
    if "=" not in ref:
        sys.exit("bad reference %r (want parameter=value)" % ref)
    p, v = ref.split("=", 1)
    if p not in params or v not in params[p]:
        sys.exit("unknown parameter/value %r" % ref)
    return p, v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("box")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--diverse", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with open(a.box, encoding="utf-8") as fh:
        spec = json.load(fh)
    params: Dict[str, List[str]] = spec["parameters"]
    names = list(params)
    bad = set()
    for item in spec.get("incompatible", []):
        x, y = parse_ref(item[0], params), parse_ref(item[1], params)
        bad.add((x, y))
        bad.add((y, x))
    req = [(parse_ref(i[0], params), parse_ref(i[1], params)) for i in spec.get("requires", [])]
    crit: Dict[str, float] = spec.get("criteria", {})
    scores: Dict[str, Dict[str, float]] = spec.get("scores", {})

    total = 1
    for v in params.values():
        total *= len(v)
    pairs = sum(len(params[p]) * len(params[q]) for p, q in itertools.combinations(names, 2))

    survivors: List[Dict[str, str]] = []

    def consistent(partial: Dict[str, str], p: str, v: str) -> bool:
        for q, w in partial.items():
            if ((p, v), (q, w)) in bad:
                return False
        return True

    def satisfies_requires(cfg: Dict[str, str]) -> bool:
        for (p, v), (q, w) in req:
            if cfg.get(p) == v and cfg.get(q) != w:
                return False
        return True

    def backtrack(i: int, partial: Dict[str, str]) -> None:
        if i == len(names):
            if satisfies_requires(partial):
                survivors.append(dict(partial))
            return
        p = names[i]
        for v in params[p]:
            if consistent(partial, p, v):
                partial[p] = v
                backtrack(i + 1, partial)
                del partial[p]

    backtrack(0, {})

    def score(cfg: Dict[str, str]) -> float:
        if not crit:
            return 0.0
        s = 0.0
        for c, w in crit.items():
            vals = [scores.get("%s=%s" % (p, v), {}).get(c, 3) for p, v in cfg.items()]
            s += w * (sum(vals) / len(vals))
        return round(s, 4)

    ranked = sorted(survivors, key=lambda c: (-score(c), [c[n] for n in names]))
    top = ranked[: a.top]

    pool = ranked[: max(a.diverse, len(ranked) // 4)]
    diverse: List[Dict[str, str]] = []
    if pool:
        diverse.append(pool[0])
        while len(diverse) < min(a.diverse, len(pool)):
            def mind(c: Dict[str, str]) -> int:
                return min(sum(c[n] != d[n] for n in names) for d in diverse)
            cand = max((c for c in pool if c not in diverse), key=lambda c: (mind(c), score(c)))
            diverse.append(cand)

    out = {
        "box_size": total,
        "pairwise_cells": pairs,
        "incompatible_pairs": len(bad) // 2,
        "requires_rules": len(req),
        "surviving": len(survivors),
        "pruned_share": round(1 - len(survivors) / total, 4) if total else 0,
        "top": [{"score": score(c), **c} for c in top],
        "diverse": [{"score": score(c), **c} for c in diverse],
    }
    if a.json:
        print(json.dumps(out, indent=2))
        return
    print("box size %d, pairwise cells %d, incompatible pairs %d, requires rules %d"
          % (total, pairs, out["incompatible_pairs"], len(req)))
    print("surviving %d (pruned %.1f%%)" % (len(survivors), 100 * out["pruned_share"]))
    for title, rows in (("top", out["top"]), ("diverse shortlist", out["diverse"])):
        print("\n%s:" % title)
        for r in rows:
            print("  %.2f  %s" % (r["score"], "  ".join("%s=%s" % (n, r[n]) for n in names)))


if __name__ == "__main__":
    main()
