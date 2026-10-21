#!/usr/bin/env python3
"""Plan swarm shards from `wc -l`-style input (stdlib only, Python 3.9+).

Reads lines of "<size> <path>" on stdin (the output of `xargs wc -l`; "total" lines are
ignored), groups files by their leading directory components, splits groups larger than
the capacity into contiguous chunks, then bin-packs with first-fit-decreasing.

Prints JSON: {"universe": {...}, "balance": {...}, "shards": [{"id", "brief", "units", "size", "scope"}]}.
The "shards" list can be passed straight to /swarm-run as args.shards (id + brief).

Example:
  git ls-files -z '*.go' ':!:*_test.go' ':!:vendor/*' | xargs -0 wc -l \
    | python3 .claude/skills/swarm-execution/scripts/shard_plan.py --capacity 20000 --group-depth 2 \
        --list-dir .stack/out/swarm-coordinator/go-leaks-shards
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Tuple


def parse(stream) -> List[Tuple[int, str]]:
    out = []
    for raw in stream:
        parts = raw.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        size, path = int(parts[0]), parts[1].strip()
        if path == "total":
            continue
        out.append((size, path))
    return out


def group_key(path: str, depth: int) -> str:
    comps = path.split("/")[:-1]  # directory components only
    return "/".join(comps[:depth]) if comps else "."


def build_items(files: List[Tuple[int, str]], depth: int, cap: int) -> List[dict]:
    groups: Dict[str, List[Tuple[int, str]]] = {}
    for size, path in files:
        groups.setdefault(group_key(path, depth), []).append((size, path))
    items = []
    for g, members in groups.items():
        total = sum(s for s, _ in members)
        if total <= cap:
            items.append({"group": g, "whole": True, "files": [p for _, p in members], "size": total})
            continue
        chunk, csize = [], 0
        for size, path in sorted(members, key=lambda m: m[1]):  # contiguous by path keeps neighbours together
            if chunk and csize + size > cap:
                items.append({"group": g, "whole": False, "files": chunk, "size": csize})
                chunk, csize = [], 0
            chunk.append(path)
            csize += size
        if chunk:
            items.append({"group": g, "whole": False, "files": chunk, "size": csize})
    return items


def ffd(items: List[dict], cap: int) -> List[List[dict]]:
    bins: List[List[dict]] = []
    loads: List[int] = []
    for it in sorted(items, key=lambda i: (-i["size"], i["group"])):
        for i, load in enumerate(loads):
            if load + it["size"] <= cap:
                bins[i].append(it)
                loads[i] += it["size"]
                break
        else:
            bins.append([it])
            loads.append(it["size"])
    return bins


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capacity", type=int, required=True, help="max size units (e.g. LOC) per shard")
    ap.add_argument("--group-depth", type=int, default=2, help="directory components that define a cohesion group")
    ap.add_argument("--unit", default="LOC", help="label for the size unit in briefs")
    ap.add_argument("--list-dir", help="write each shard's file list to <dir>/<id>.txt and reference it in the brief")
    ap.add_argument("--inline-max", type=int, default=12, help="inline at most this many explicit files per brief")
    a = ap.parse_args()

    files = parse(sys.stdin)
    if not files:
        print(json.dumps({"error": "no '<size> <path>' lines on stdin"}))
        return 1
    bins = ffd(build_items(files, a.group_depth, a.capacity), a.capacity)
    if a.list_dir:
        os.makedirs(a.list_dir, exist_ok=True)

    shards = []
    width = max(2, len(str(len(bins))))
    for n, b in enumerate(bins, 1):
        sid = "s%0*d" % (width, n)
        globs = sorted("%s/**" % it["group"] if it["group"] != "." else "./* (top level)" for it in b if it["whole"])
        explicit = sorted(p for it in b if not it["whole"] for p in it["files"])
        all_files = sorted(p for it in b for p in it["files"])
        size = sum(it["size"] for it in b)
        scope = list(globs)
        if explicit:
            if a.list_dir:
                lp = os.path.join(a.list_dir, sid + ".txt")
                with open(lp, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(explicit) + "\n")
                scope.append("files listed in %s" % lp)
            elif len(explicit) <= a.inline_max:
                scope.extend(explicit)
            else:
                scope.append("%d files under %s (first: %s, last: %s)" % (
                    len(explicit), ", ".join(sorted({it["group"] for it in b if not it["whole"]})), explicit[0], explicit[-1]))
        brief = "SCOPE: %s (%d files, %d %s)" % ("; ".join(scope), len(all_files), size, a.unit)
        oversize = size > a.capacity
        if oversize:
            brief += " [over capacity: single file larger than %d; review by symbol or split further]" % a.capacity
        shards.append({"id": sid, "brief": brief, "units": len(all_files), "size": size, "scope": scope,
                       "oversize": oversize})

    sizes = [s["size"] for s in shards]
    mean = sum(sizes) / len(sizes)
    print(json.dumps({
        "universe": {"files": len(files), "size": sum(s for s, _ in files), "unit": a.unit},
        "balance": {"shards": len(shards), "max": max(sizes), "mean": round(mean, 1),
                    "max_over_mean": round(max(sizes) / mean, 2) if mean else None},
        "shards": shards,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
