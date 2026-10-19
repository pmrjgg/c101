#!/usr/bin/env python3
"""Compare two benchmark samples with robust statistics (stdlib only, Python 3.9+).

Usage:
    python3 compare_bench.py BEFORE AFTER [--threshold 0.03] [--boot 10000] [--seed 1] [--lower-is-better|--higher-is-better]
        [--command CMD | --before-command CMD --after-command CMD]

BEFORE / AFTER are either:
  * hyperfine --export-json files (uses results[0].times, or the result whose command matches
    --before-command / --after-command, falling back to --command; an unmatched command is an error).
    One hyperfine JSON with both variants: pass it twice with --before-command and --after-command, or
  * text files with one number per line (blank lines and '#' comments ignored).

Prints n, median, bootstrap 95% CI of each median, coefficient of variation, the after/before ratio
of medians with a bootstrap 95% CI, a Mann-Whitney U two-sided p-value (normal approximation with
tie correction), and a verdict:
  IMPROVED   CI of the ratio lies entirely on the good side of 1 and the point effect >= threshold
  REGRESSED  CI lies entirely on the bad side of 1 and the point effect >= threshold
  NO CHANGE  CI lies within +/- threshold of 1
  INCONCLUSIVE otherwise (collect more samples; see the sample-size formula in references/statistics.md)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
from typing import List, Optional


def load(path: str, command: Optional[str]) -> List[float]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and "results" in data:
        results = data["results"]
        if command:
            sel = [r for r in results if r.get("command") == command]
            if not sel:
                raise SystemExit("%s: no hyperfine result with command %r (available: %s)"
                                 % (path, command, [r.get("command") for r in results]))
            results = sel
        elif len(results) > 1:
            print("%s: %d hyperfine results, using the first (%r); select with --before-command/--after-command"
                  % (path, len(results), results[0].get("command")), file=sys.stderr)
        return [float(x) for x in results[0]["times"]]
    vals = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            vals.append(float(line.split()[0]))
    return vals


def boot_ci(xs: List[float], rng: random.Random, b: int, stat=statistics.median):
    n = len(xs)
    reps = sorted(stat([xs[rng.randrange(n)] for _ in range(n)]) for _ in range(b))
    return reps[int(0.025 * b)], reps[int(0.975 * b) - 1]


def ratio_ci(a: List[float], c: List[float], rng: random.Random, b: int):
    na, nc = len(a), len(c)
    reps = []
    for _ in range(b):
        ma = statistics.median([a[rng.randrange(na)] for _ in range(na)])
        mc = statistics.median([c[rng.randrange(nc)] for _ in range(nc)])
        reps.append(mc / ma if ma else float("inf"))
    reps.sort()
    return reps[int(0.025 * b)], reps[int(0.975 * b) - 1]


def mann_whitney_p(a: List[float], c: List[float]) -> float:
    combined = sorted([(v, 0) for v in a] + [(v, 1) for v in c])
    n = len(combined)
    ranks = [0.0] * n
    tie_term = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and combined[j + 1][0] == combined[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = r
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    n1, n2 = len(a), len(c)
    r1 = sum(r for r, (_, g) in zip(ranks, combined) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - tie_term / (n * (n - 1)))) if n > 1 else 0
    if sigma == 0:
        return 1.0
    z = (abs(u1 - mu) - 0.5) / sigma
    return max(0.0, min(1.0, math.erfc(z / math.sqrt(2))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--command", help="hyperfine command string to select on both sides when a JSON has several results")
    ap.add_argument("--before-command", help="hyperfine command string to select in BEFORE (overrides --command)")
    ap.add_argument("--after-command", help="hyperfine command string to select in AFTER (overrides --command)")
    ap.add_argument("--threshold", type=float, default=0.03, help="practical-significance threshold (0.03 = 3%%)")
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=1)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--lower-is-better", dest="lower", action="store_true", default=True)
    g.add_argument("--higher-is-better", dest="lower", action="store_false")
    a = ap.parse_args()

    bcmd, acmd = a.before_command or a.command, a.after_command or a.command
    if os.path.abspath(a.before) == os.path.abspath(a.after) and bcmd == acmd:
        print("BEFORE and AFTER select the same samples; pass --before-command and --after-command", file=sys.stderr)
        return 2
    before, after = load(a.before, bcmd), load(a.after, acmd)
    if len(before) < 5 or len(after) < 5:
        print("need at least 5 samples per side (got %d, %d)" % (len(before), len(after)), file=sys.stderr)
        return 2
    rng = random.Random(a.seed)
    print("| variant | n | median | 95% CI of median | CV |")
    print("|---|---|---|---|---|")
    for name, xs in (("before", before), ("after", after)):
        lo, hi = boot_ci(xs, rng, a.boot)
        cv = statistics.stdev(xs) / statistics.mean(xs) if statistics.mean(xs) else float("nan")
        print("| %s | %d | %.6g | [%.6g, %.6g] | %.1f%% |" % (name, len(xs), statistics.median(xs), lo, hi, 100 * cv))
    ratio = statistics.median(after) / statistics.median(before)
    lo, hi = ratio_ci(before, after, rng, a.boot)
    p = mann_whitney_p(before, after)
    t = a.threshold
    good_lo, good_hi = (lo, hi) if a.lower else (1 / hi, 1 / lo)  # normalize so < 1 means better
    point = ratio if a.lower else 1 / ratio
    if good_hi < 1 and (1 - point) >= t:
        verdict = "IMPROVED"
    elif good_lo > 1 and (point - 1) >= t:
        verdict = "REGRESSED"
    elif good_lo >= 1 - t and good_hi <= 1 + t:
        verdict = "NO CHANGE (within +/-%.1f%%)" % (100 * t)
    else:
        verdict = "INCONCLUSIVE (collect more samples or reduce noise)"
    print()
    print("ratio after/before (medians): %.4f, 95%% bootstrap CI [%.4f, %.4f]" % (ratio, lo, hi))
    if a.lower and ratio > 0:
        print("speedup before/after: %.3fx" % (1 / ratio))
    print("Mann-Whitney U two-sided p = %.3g" % p)
    print("verdict: %s" % verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
