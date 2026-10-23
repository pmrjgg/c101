#!/usr/bin/env python3
"""Utopia-style fluid type scale -> CSS custom properties (stdlib only).

python3 -I typescale.py --min-w 360 --max-w 1440 --min-base 16 --max-base 16 \
    --min-ratio 1.2 --max-ratio 1.25 --steps=-1..5 [--lh 1.5] [--grid 4]
"""
import argparse
import math


def fmt(x):
    return ("%.4f" % x).rstrip("0").rstrip(".")


def clamp_css(s1, s2, w1, w2, rem=16.0):
    """Fluid size from s1 px at w1 to s2 px at w2: clamp(min, intercept + slope*100vw, max)."""
    slope = (s2 - s1) / (w2 - w1)
    intercept = s1 - slope * w1
    lo, hi = sorted((s1, s2))
    if abs(slope) < 1e-9:
        return fmt(s1 / rem) + "rem"
    return "clamp(%srem, %srem %s %svw, %srem)" % (
        fmt(lo / rem), fmt(intercept / rem), "+" if slope >= 0 else "-", fmt(abs(slope) * 100), fmt(hi / rem))


def snap(x, unit):
    return math.floor(x / unit + 0.5) * unit  # half-up, not banker's rounding


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-w", type=float, default=360); ap.add_argument("--max-w", type=float, default=1440)
    ap.add_argument("--min-base", type=float, default=16); ap.add_argument("--max-base", type=float, default=16)
    ap.add_argument("--min-ratio", type=float, default=1.2); ap.add_argument("--max-ratio", type=float, default=1.25)
    ap.add_argument("--steps", default="-1..5"); ap.add_argument("--round", type=float, default=0.5)
    ap.add_argument("--lh", type=float, default=0, help="target line-height ratio; prints leading snapped to --grid")
    ap.add_argument("--grid", type=float, default=4)
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.steps.split(".."))
    print(":root {")
    for k in range(lo, hi + 1):
        s1 = snap(a.min_base * a.min_ratio ** k, a.round)
        s2 = snap(a.max_base * a.max_ratio ** k, a.round)
        note = "%g -> %g px" % (s1, s2)
        if a.lh:
            note += "; line-height %g/%g px" % (snap(s1 * a.lh, a.grid), snap(s2 * a.lh, a.grid))
        print("  --step-%s: %s; /* %s */" % (str(k).replace("-", "n"), clamp_css(s1, s2, a.min_w, a.max_w), note))
    print("}")


if __name__ == "__main__":
    main()
