#!/usr/bin/env python3
"""Churn x complexity hotspot ranking from git history (stdlib only, Python 3.9+).

Usage (run from anywhere inside the target git repository; resolve the stack root first with
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"):
    python3 "$STACK/.claude/skills/code-quality-metrics/scripts/hotspots.py"
                        [--since 12.months] [--top 25] [--complexity-csv lizard.csv]
                        [--include 'src/**'] [--exclude 'vendor/**' ...] [--format md|tsv]

Complexity source, in order of preference:
  1. --complexity-csv FILE: either `lizard --csv` output (per-function rows; CCN is summed and
     maxed per file) or a two-column CSV `path,score`.
  2. Fallback: indentation complexity per file (sum of leading-indent levels of non-blank lines),
     a language-agnostic proxy that correlates well with cyclomatic complexity.

Score = churn_percentile x complexity_percentile (0..1). Files with both high churn and high
complexity rank first. Bug-fix churn (commits whose subject matches fix|bug|hotfix|regression)
is reported separately as a defect signal. Renames split history: commits made before a rename
count under the old path, which is dropped because it is no longer tracked.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import os
import re
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

FIX_RE = re.compile(r"\b(fix|fixes|fixed|bug|hotfix|regression|patch)\b", re.I)
DEFAULT_EXCLUDES = [
    "vendor/**", "node_modules/**", "third_party/**", "dist/**", "build/**", "target/**",
    "*.lock", "*.min.js", "*.svg", "*.png", "*.jpg", "*.pdf", "*.json", "*.md", "*.txt",
    "**/generated/**", "*_pb2.py", "*.pb.go", "package-lock.json", "yarn.lock", "go.sum",
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def matches(path: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(os.path.basename(path), p) for p in patterns)


def churn(since: str) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    """Return (commits per file, lines changed per file, fix commits per file)."""
    out = git("log", "--since=" + since, "--no-merges", "--numstat", "--format=@@%s")
    commits: Dict[str, int] = defaultdict(int)
    lines: Dict[str, int] = defaultdict(int)
    fixes: Dict[str, int] = defaultdict(int)
    is_fix = False
    for row in out.splitlines():
        if row.startswith("@@"):
            is_fix = bool(FIX_RE.search(row[2:]))
            continue
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        if "=>" in path:  # rename: keep the new path
            path = re.sub(r"\{[^}]*=> ([^}]*)\}", r"\1", path)
            path = path.split(" => ")[-1]
        commits[path] += 1
        if added.isdigit() and deleted.isdigit():
            lines[path] += int(added) + int(deleted)
        if is_fix:
            fixes[path] += 1
    return commits, lines, fixes


def indentation_complexity(path: str) -> Optional[int]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            total = 0
            for line in fh:
                if not line.strip():
                    continue
                expanded = line.expandtabs(4)
                indent = len(expanded) - len(expanded.lstrip(" "))
                total += indent // 4 if indent >= 4 else (1 if indent else 0)
            return total
    except OSError:
        return None


def load_complexity_csv(path: str, tracked: set) -> Dict[str, Tuple[int, int]]:
    """Return {file: (sum_ccn, max_ccn)} from lizard --csv or {file: (score, score)} from path,score."""
    res: Dict[str, List[int]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            if len(row) == 2:
                f, score = row[0][2:] if row[0].startswith("./") else row[0], row[1]
                if score.strip().lstrip("-").isdigit():
                    res[f].append(int(score))
                continue
            # lizard: NLOC, CCN, ... ; locate the column that is a tracked path
            if len(row) < 3 or not row[1].strip().isdigit():
                continue
            ccn = int(row[1])
            f = next((c[2:] if c.startswith("./") else c for c in row[2:]
                      if (c[2:] if c.startswith("./") else c) in tracked), None)
            if f:
                res[f].append(ccn)
    return {f: (sum(v), max(v)) for f, v in res.items() if v}


def percentile_ranks(values: Dict[str, float]) -> Dict[str, float]:
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 0:
        return {}
    ranks: Dict[str, float] = {}
    i = 0
    while i < n:  # average rank for ties
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        r = ((i + j) / 2 + 1) / n
        for k in range(i, j + 1):
            ranks[items[k][0]] = r
        i = j + 1
    return ranks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="12.months")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--complexity-csv")
    ap.add_argument("--include", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--format", choices=["md", "tsv"], default="md")
    a = ap.parse_args()
    if a.complexity_csv:
        a.complexity_csv = os.path.abspath(a.complexity_csv)

    try:
        root = git("rev-parse", "--show-toplevel").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("error: not inside a git repository", file=sys.stderr)
        return 2
    os.chdir(root)
    tracked = set(git("ls-files").splitlines())
    excludes = DEFAULT_EXCLUDES + a.exclude

    commits, lines, fixes = churn(a.since)
    files = [f for f in commits if f in tracked and not matches(f, excludes)
             and (not a.include or matches(f, a.include))]
    if not files:
        print("no tracked source files changed since %s" % a.since, file=sys.stderr)
        return 1

    if a.complexity_csv:
        cx = load_complexity_csv(a.complexity_csv, tracked)
        source = "csv (sum CCN)"
        comp = {f: float(cx[f][0]) for f in files if f in cx}
        maxc = {f: cx[f][1] for f in files if f in cx}
    else:
        source = "indentation"
        comp, maxc = {}, {}
        for f in files:
            v = indentation_complexity(f)
            if v is not None:
                comp[f] = float(v)
    files = [f for f in files if f in comp]
    churn_pr = percentile_ranks({f: float(commits[f]) for f in files})
    comp_pr = percentile_ranks(comp)
    scored = sorted(files, key=lambda f: churn_pr[f] * comp_pr[f], reverse=True)[: a.top]

    hdr = ["rank", "file", "score", "commits", "lines_changed", "fix_commits", "complexity(%s)" % source, "max_fn_ccn"]
    rows = []
    for i, f in enumerate(scored, 1):
        rows.append([str(i), f, "%.2f" % (churn_pr[f] * comp_pr[f]), str(commits[f]), str(lines[f]),
                     str(fixes[f]), "%d" % comp[f], str(maxc.get(f, "-"))])
    if a.format == "tsv":
        print("\t".join(hdr))
        for r in rows:
            print("\t".join(r))
    else:
        print("| " + " | ".join(hdr) + " |")
        print("|" + "---|" * len(hdr))
        for r in rows:
            print("| " + " | ".join(r) + " |")
        print("\nwindow: --since=%s; files considered: %d; complexity source: %s" % (a.since, len(files), source))
    return 0


if __name__ == "__main__":
    sys.exit(main())
