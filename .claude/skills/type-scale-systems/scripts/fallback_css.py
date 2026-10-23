#!/usr/bin/env python3
"""Metric-matched fallback @font-face (Capsize formulas), stdlib only.

    python3 -I fallback_css.py Inter Arial                 # built-in metrics
    python3 -I fallback_css.py "Source Serif 4" Georgia --generic serif
    python3 -I fallback_css.py MyFont Arial --metrics '{"MyFont": {"upm": 1000, "ascent": 950,
        "descent": -250, "lineGap": 0, "xHeight": 520, "xWidthAvg": 470}}'

size-adjust      = (web xWidthAvg / web upm) / (fallback xWidthAvg / fallback upm)
ascent-override  = web ascent      / (web upm x size-adjust)     (same for |descent|, lineGap)
The overrides are scaled by size-adjust in the browser, so they reproduce the web font's
vertical metrics on the fallback. Built-in numbers: @capsizecss/metrics 4.4.0 (hhea metrics,
xWidthAvg weighted by English letter frequency).
"""
import argparse
import json

BUILTIN = {  # upm, ascent, descent, lineGap, xHeight, capHeight, xWidthAvg; local() names
    "Inter": (2048, 1984, -494, 0, 1118, 1490, 978, ()),
    "Arial": (2048, 1854, -434, 67, 1062, 1467, 913, ("Arial", "ArialMT")),
    "Georgia": (2048, 1878, -449, 0, 986, 1419, 913, ("Georgia",)),
    "Source Serif 4": (1000, 1036, -335, 0, 475, 670, 479, ()),
    "Source Sans 3": (1000, 1024, -400, 0, 486, 660, 418, ()),
    "IBM Plex Sans": (1000, 1025, -275, 0, 516, 698, 451, ()),
    "IBM Plex Serif": (1000, 1025, -275, 0, 516, 698, 473, ()),
    "Noto Sans": (1000, 1069, -293, 0, 536, 714, 474, ()),
    "Noto Serif": (1000, 1069, -293, 0, 536, 714, 481, ()),
    "Fraunces": (2000, 1956, -510, 0, 964, 1400, 938, ()),
    "Literata": (1000, 1177, -308, 0, 507, 701, 480, ()),
}
KEYS = ("upm", "ascent", "descent", "lineGap", "xHeight", "capHeight", "xWidthAvg", "local")


def get(name, extra):
    if name in extra:
        m = dict(extra[name])
        m.setdefault("local", [name])
        return m
    return dict(zip(KEYS, BUILTIN[name]))


def pct(x):
    return "%.2f%%" % (100 * x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("font")
    ap.add_argument("fallback")
    ap.add_argument("--generic", default="sans-serif", help="generic family appended to the stack")
    ap.add_argument("--metrics", default="{}", help="JSON {name: {upm, ascent, descent, lineGap, xHeight, xWidthAvg}}")
    a = ap.parse_args()
    extra = json.loads(a.metrics)
    w, f = get(a.font, extra), get(a.fallback, extra)
    size = (w["xWidthAvg"] / w["upm"]) / (f["xWidthAvg"] / f["upm"])
    em = w["upm"] * size
    local = ", ".join('local("%s")' % n for n in (f["local"] or (a.fallback,)))
    if w.get("xHeight") and f.get("xHeight"):
        print("/* x-height/upm: %s %.3f, %s %.3f */" % (a.font, w["xHeight"] / w["upm"], a.fallback, f["xHeight"] / f["upm"]))
    print('@font-face {\n  font-family: "%s Fallback";\n  src: %s;\n  size-adjust: %s;\n'
          '  ascent-override: %s;\n  descent-override: %s;\n  line-gap-override: %s;\n}' % (
              a.font, local, pct(size), pct(w["ascent"] / em), pct(abs(w["descent"]) / em), pct(w["lineGap"] / em)))
    print('/* font-family: "%s", "%s Fallback", %s; */' % (a.font, a.font, a.generic))


if __name__ == "__main__":
    main()
