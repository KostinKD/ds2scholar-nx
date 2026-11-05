#!/usr/bin/env python3
"""Share of near-black pixels in a band of a PPM shot (app/src/ds2_shot.cpp), for A/B runs of a rendering defect.

Stage 3, Majula's black sky (2026-10-16): the sky above the horizon renders black, with a blocky edge. A pixel is
"black" when max(R, G, B) < --threshold. Default band: rows 0..--rows (the sky above Majula from the bonfire).

  python tools/shot_metric.py out/pc/captures/shot_112s.ppm [--rows 120] [--threshold 12]
"""
import argparse
import sys

sys.path.insert(0, __file__.rsplit('tools', 1)[0] + 'tools')
from ppm_to_png import read_ppm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('ppm', nargs='+')
ap.add_argument('--rows', type=int, default=120)
ap.add_argument('--threshold', type=int, default=12)
a = ap.parse_args()
for name in a.ppm:
    w, h, rgb = read_ppm(name)
    rows = min(a.rows, h)
    black = 0
    for y in range(rows):
        row = rgb[y * w * 3:(y + 1) * w * 3]
        black += sum(1 for x in range(0, w * 3, 3) if max(row[x], row[x + 1], row[x + 2]) < a.threshold)
    print(f'{name}: {100.0 * black / (w * rows):.1f} % black in rows 0..{rows}')
