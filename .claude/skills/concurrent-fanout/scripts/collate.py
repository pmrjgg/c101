#!/usr/bin/env python3
"""Collate fan-out item results into a markdown table, coverage line and totals (stdlib only).

Input: a JSON file (or stdin) holding either a list of item results, or the object /fanout returns
({results: [{index, ref, attempts, result}], failed: [{index, ref, attempts, reason}], skipped: [...]}).
Each item result follows the concurrent-fanout schema:
  {"id", "status": done|partial|blocked, "summary", "data": {...flat...}, "file", "confidence", "error",
   "attempts"?}
Task-specific numeric fields may sit in "data" or at the top level.

Usage:
  python3 .claude/skills/concurrent-fanout/scripts/collate.py results.json [--expect i01 i02 ...]
      [--metrics endpoints unauthenticated] [--md out.md]

--expect lists every item id that was launched, so items with no result at all are reported as
failed instead of disappearing. Totals are computed over items with status "done" only.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List

CORE = {"id", "status", "summary", "data", "file", "confidence", "error", "attempts"}


def unwrap(entry) -> dict:
    """Accept a bare item result, or a /fanout results[] entry {index, ref, attempts, result}."""
    if isinstance(entry, dict) and "result" in entry and ("index" in entry or "ref" in entry):
        res = entry.get("result")
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except ValueError:
                res = {"summary": res}
        res = dict(res) if isinstance(res, dict) else {"summary": str(res)}
        res.setdefault("id", entry.get("ref") or "#%s" % entry.get("index"))
        res.setdefault("status", "done")
        res.setdefault("attempts", entry.get("attempts", ""))
        return res
    return entry if isinstance(entry, dict) else {"id": str(entry), "status": "failed", "error": "unparseable entry"}


def flat(item: dict) -> Dict[str, object]:
    out = {k: v for k, v in item.items() if k not in CORE}
    if isinstance(item.get("data"), dict):
        out.update(item["data"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="JSON file; stdin when omitted")
    ap.add_argument("--expect", nargs="*", default=[], help="all launched item ids")
    ap.add_argument("--metrics", nargs="*", help="numeric fields to show and total (default: all numeric fields)")
    ap.add_argument("--md", help="also write the full table to this markdown file")
    a = ap.parse_args()

    raw = json.load(open(a.path, encoding="utf-8") if a.path else sys.stdin)
    failed_extra: List[dict] = []
    if isinstance(raw, dict):
        items = [unwrap(r) for r in raw.get("results", []) if r]
        for f in (raw.get("failed") or []) + (raw.get("skipped") or []):
            if isinstance(f, dict):
                failed_extra.append({"id": str(f.get("id") or f.get("ref") or "#%s" % f.get("index")),
                                     "error": f.get("reason") or f.get("error") or "no result",
                                     "attempts": f.get("attempts", "")})
            else:
                failed_extra.append({"id": str(f), "error": "no result"})
    else:
        items = [unwrap(r) for r in raw if r]

    seen = {str(i.get("id")) for i in items}
    for f in failed_extra:
        if str(f.get("id")) not in seen:
            items.append({"id": str(f.get("id")), "status": "failed", "summary": "", "error": f.get("error", "no result"),
                          "attempts": f.get("attempts", "")})
            seen.add(str(f.get("id")))
    for eid in a.expect:
        if eid not in seen:
            items.append({"id": eid, "status": "failed", "summary": "", "error": "no result returned"})

    items.sort(key=lambda i: str(i.get("id")))
    metrics = a.metrics
    if metrics is None:
        metrics = sorted({k for i in items for k, v in flat(i).items()
                          if isinstance(v, (int, float)) and not isinstance(v, bool)})

    head = "| # | id | status | att | summary | %s | file |" % " | ".join(metrics) if metrics else "| # | id | status | att | summary | file |"
    rows = [head, "|" + "---|" * (head.count("|") - 1)]
    totals = {m: 0 for m in metrics}
    counts: Dict[str, List[str]] = {}
    for n, i in enumerate(items, 1):
        st = str(i.get("status", "failed"))
        counts.setdefault(st, []).append(str(i.get("id")))
        f = flat(i)
        summ = str(i.get("summary") or i.get("error") or "").replace("|", "/").replace("\n", " ")[:160]
        vals = []
        for m in metrics:
            v = f.get(m, "")
            vals.append(str(v))
            if st == "done" and isinstance(v, (int, float)) and not isinstance(v, bool):
                totals[m] += v
        cells = [str(n), str(i.get("id")), st, str(i.get("attempts", "")), summ] + vals + [str(i.get("file", "") or "")]
        rows.append("| " + " | ".join(cells) + " |")

    total = len(items)
    parts = ["%d/%d done" % (len(counts.get("done", [])), total)]
    for st in sorted(k for k in counts if k != "done"):
        parts.append("%d %s (%s)" % (len(counts[st]), st, ", ".join(counts[st])))
    coverage = "Coverage: " + ", ".join(parts) + "."
    tot = "Totals (done items only): " + ", ".join("%s %s" % (m, round(v, 6)) for m, v in totals.items()) if metrics else ""

    table = "\n".join(rows)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write("# Fan-out results\n\n## Summary\n%s\n%s\n\n## Items\n%s\n" % (coverage, tot, table))
    print(table)
    print()
    print(coverage)
    if tot:
        print(tot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
