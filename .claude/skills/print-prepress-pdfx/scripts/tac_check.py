#!/usr/bin/env python3
"""Peak total area coverage (TAC) per page, from Ghostscript tiffsep separations.

    PY="$HOME/.claude/stack/.venv/bin/python"; [ -x "$PY" ] || PY=.venv/bin/python
    "$PY" -I tac_check.py flyer.pdf [--limit 300] [--dpi 150] [--keep DIR]

`gs -sDEVICE=ink_cov` reports page AVERAGES only; this finds the PEAKS a printer's preflight
rejects. Every page is rendered with `gs -sDEVICE=tiffsep` (one 8-bit grayscale file per
colorant, 255 = no ink, 0 = 100 %, overprint honoured); process inks are summed per pixel.
Per page it prints the max TAC and where it sits (mm from the top-left of the MediaBox), the
area share above --limit (1 % tolerance for 8-bit quantisation) and the peak of every spot
separation. Exit 1 if any page exceeds the limit. Needs Ghostscript on PATH and Pillow.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

PROCESS = ("Cyan", "Magenta", "Yellow", "Black")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--limit", type=float, default=300.0, help="TAC limit in %% from the printer")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--keep", help="directory for the separations (default: a temp dir)")
    a = ap.parse_args()
    out = a.keep or tempfile.mkdtemp(prefix="tac_")
    os.makedirs(out, exist_ok=True)
    subprocess.run(["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=tiffsep", "-r%d" % a.dpi,
                    "-sOutputFile=" + os.path.join(out, "p%03d.tif"), a.pdf], check=True)
    over = False
    for comp in sorted(glob.glob(os.path.join(out, "p[0-9][0-9][0-9].tif"))):
        stem = comp[:-4]
        seps = {re.search(r"\((.*)\)\.tif$", f).group(1): f for f in glob.glob(glob.escape(stem) + "(*).tif")}
        missing = [c for c in PROCESS if c not in seps]
        if missing:
            sys.exit("page %s: no separation for %s" % (stem[-3:], ", ".join(missing)))
        chans = [Image.open(seps[c]).convert("L") for c in PROCESS]
        w, h = chans[0].size
        sums = list(map(sum, zip(*(ch.tobytes() for ch in chans))))   # sum of 8-bit values; low = ink
        thr = 1020 - (a.limit + 1.0) / 100 * 255
        lo = min(sums)
        i = sums.index(lo)
        share = sum(1 for s in sums if s < thr) / len(sums)
        peak = (1020 - lo) / 255 * 100
        bad = share > 0
        over |= bad
        print("page %d: max TAC %.0f %% at (%.1f, %.1f) mm; %.2f %% of the area above %.0f %% -> %s" % (
            int(stem[-3:]), peak, (i % w) / a.dpi * 25.4, (i // w) / a.dpi * 25.4,
            100 * share, a.limit, "OVER" if bad else "ok"))
        for name, f in sorted(seps.items()):
            if name not in PROCESS:
                print("        spot %s: max %.0f %%" % (name, (255 - min(Image.open(f).convert("L").tobytes())) / 255 * 100))
    if a.keep:
        print("separations kept in", out)
    else:
        shutil.rmtree(out, ignore_errors=True)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
