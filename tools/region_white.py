"""Share of near-white pixels (R, G, B >= 220) in a rectangle of shots: bisecting a white artefact.
  python -I tools/region_white.py <x0> <y0> <x1> <y1> <shot> [...]"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from yellow_metric import read  # noqa: E402

x0, y0, x1, y1 = map(int, sys.argv[1:5])
for p in sys.argv[5:]:
    w, h, px = read(p)
    n = t = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = (y * w + x) * 3
            t += 1
            n += px[i] >= 220 and px[i + 1] >= 220 and px[i + 2] >= 220
    print(f'{p}: white {100.0 * n / t:.1f}%')
