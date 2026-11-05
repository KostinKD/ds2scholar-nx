#!/usr/bin/env python3
"""The most expensive shader pairs of a console log, for picking which game shaders to optimise.

  python tools/switch_shader_top.py out/switch_logs/latest/ds2_NNN.log [--top 25] [--from HH:MM:SS] [--to HH:MM:SS]

Reads the renderer's 10-second "GPU time by pass (category, first draw's shaders)" lines (sa2_gpu_marks_categories =
true, on in app/ds2_switch.toml): each item is a pass category and the vertex / pixel shader of the pass's first draw
with its GPU time in that window (raw timestamp ms; x1.627 for real ms on the Switch). Prints, per pair: the total over
the log, the worst 10 s window and when, the share of all listed GPU time, and the pixel shader's container hash (the
"library nN: PS container ..." lines), which names the file in out/shaders/hlsl (ps_<hash>.hlsl).

Categories (sa2_native_targets.cpp kNames): 0 other, 1 shadows, 2 scene, 3 640, 4 320, 5 smaller, 6 copies, 7 clears,
8 scene_no_z, 9 gap, 10 edram_import, 11 edram_export, 12 edram_alias, 13 edram_import9, 14 edram_resolve_depth,
15 edram_resolve_bias. VS0 PS0 = not a draw (copies, transfers).
"""
import argparse
import collections
import re
import sys

NAMES = ['other', 'shadows', 'scene', '640', '320', 'smaller', 'copies', 'clears', 'scene_no_z', 'gap',
         'edram_import', 'edram_export', 'edram_alias', 'edram_import9', 'edram_resolve_depth', 'edram_resolve_bias']
REAL = 1.627
LINE = re.compile(r'^\[\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d)\.\d+\].*GPU time by pass \(category, first draw\'s shaders\), 10 s: (.*)$')
ITEM = re.compile(r'\[cat (\d+) VS(\d+) PS(\d+): ([\d.]+) ms\]')
CONTAINER = re.compile(r'library n(\d+): (VS|PS) container ([0-9a-f]+)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('log')
    ap.add_argument('--top', type=int, default=25)
    ap.add_argument('--from', dest='start', default='00:00:00')
    ap.add_argument('--to', dest='end', default='99:99:99')
    a = ap.parse_args()
    total = collections.Counter()
    worst = {}
    windows = 0
    containers = {}
    for line in open(a.log, encoding='utf-8', errors='replace'):
        m = CONTAINER.search(line)
        if m:
            containers[(m.group(2), int(m.group(1)))] = m.group(3)
            continue
        m = LINE.match(line)
        if not m or not (a.start <= m.group(1) <= a.end):
            continue
        windows += 1
        for cat, vs, ps, ms in ITEM.findall(m.group(2)):
            key = (int(cat), int(vs), int(ps))
            v = float(ms) * REAL
            total[key] += v
            if v > worst.get(key, (0, ''))[0]:
                worst[key] = (v, m.group(1))
    if not windows:
        sys.exit('no "GPU time by pass" lines (sa2_gpu_marks_categories off, or outside --from/--to)')
    grand = sum(total.values())
    print(f'{windows} windows of 10 s; real GPU ms (x{REAL}); share of all listed time')
    print(f'{"pass":<20} {"VS":>5} {"PS":>5} {"total":>9} {"share":>6} {"worst 10 s":>11} {"at":>9}  PS container')
    for (cat, vs, ps), v in total.most_common(a.top):
        w, t = worst[(cat, vs, ps)]
        name = NAMES[cat] if cat < len(NAMES) else str(cat)
        hash_ps = containers.get(('PS', ps), '-') if ps else '-'
        print(f'{name:<20} {vs:>5} {ps:>5} {v:>9.1f} {100 * v / grand:>5.1f}% {w:>11.1f} {t:>9}  {hash_ps}')


if __name__ == '__main__':
    main()
