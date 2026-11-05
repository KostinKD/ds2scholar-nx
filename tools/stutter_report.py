#!/usr/bin/env python3
"""Stage 3 stutter analysis of a PC build log: per ds2_swap_log interval, the presented-frame rate (VdSwap) next to
what else the log says happened in the same window (slow file I/O, new shaders and pipelines, loads), so a hitch can
be matched to its cause. Prints only the windows below --fps or with events.

  python tools/stutter_report.py out/pc/logs/ds2_029.log [--fps 57]
"""
import argparse
import datetime as dt
import re

ap = argparse.ArgumentParser()
ap.add_argument('log')
ap.add_argument('--fps', type=float, default=57.0)
a = ap.parse_args()

lines = open(a.log, encoding='utf-8', errors='replace').read().splitlines()


def ts(line):
    try:
        return dt.datetime.strptime(line[1:24], '%Y-%m-%d %H:%M:%S.%f')
    except ValueError:
        return None


swaps = []
events = []
for line in lines:
    t = ts(line)
    if t is None:
        continue
    m = re.search(r'\[ds2\] VdSwap: \d+ in ([0-9.]+) s \(([0-9.]+)/s\)', line)
    if m:
        swaps.append((t, float(m.group(1)), float(m.group(2))))
    elif 'SLOW' in line or re.search(r'(?i)shader|pipeline|compil|load', line):
        events.append((t, line))

if not swaps:
    raise SystemExit('no [ds2] VdSwap lines (ds2_swap_log_s off?)')
t0 = swaps[0][0]
for t, interval, rate in swaps:
    window = [l for e, l in events if t - dt.timedelta(seconds=interval) < e <= t]
    slow = [l for l in window if 'SLOW' in l]
    slow_ms = sum(float(m.group(1)) for l in slow for m in [re.search(r'took ([0-9.]+) ms', l)] if m)
    other = [l for l in window if 'SLOW' not in l]
    if rate < a.fps or window:
        names = sorted({m.group(1).replace(chr(92), '/').split('/')[-1]
                        for l in slow for m in [re.search(r"(?:open|of) '([^']+)'", l)] if m})
        print(f'{(t - t0).total_seconds():6.0f} s {rate:5.1f}/s  slow io {len(slow):2d} ({slow_ms:5.0f} ms)'
              f' {", ".join(names)[:70]}')
        for l in other[:3]:
            print('          ' + l[26:180])
