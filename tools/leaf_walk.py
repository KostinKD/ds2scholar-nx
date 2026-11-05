#!/usr/bin/env python3
"""Bounds of a leaf without .pdata that discovery split at an early `blr` (docs/ds2-nx/analysis/codegen.md, "разрезанный
лист"): walks every branch from the entry and reports the range, whether every word of it is reached, which
branches leave it, and whether the next word starts a registered function. ds2-nx did these walks by hand.

  python tools/leaf_walk.py 0x82646FB0 [0x... ...] [--ignore 0x82646FF0,...]
      (needs out/default_image.bin and app/generated/default; --ignore: registered starts to treat as plain code,
      e.g. the fragments the leaf as one function would replace)

A branch to a registered function start is a tail call and ends the path; a conditional return (beqlr...) does not.
The walk stops at the first registered function start after the entry (the limit of the leaf).
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from ppc_mini import Image, decode  # noqa: E402


def registered():
    starts = set()
    for path in glob.glob(os.path.join(ROOT, 'app', 'generated', 'default', '*recomp*.cpp')):
        starts |= {int(m, 16) for m in re.findall(r'^DEFINE_REX_FUNC\(sub_([0-9A-F]+)\)', open(path, errors='replace').read(), re.M)}
    return starts


def walk(img, starts, entry):
    limit = min(s for s in starts if s > entry)
    seen, todo, leaves, tails = set(), [entry], [], []
    while todo:
        a = todo.pop()
        while a not in seen:
            if not entry <= a < limit:
                leaves.append(a)
                break
            seen.add(a)
            ins = decode(img.word(a), a)
            if ins.op == 'b' and not ins.link:
                if ins.target in starts and ins.target != entry:
                    tails.append((a, ins.target))
                    break
                a = ins.target
                continue
            if ins.op == 'bc' and not ins.link:
                if ins.unconditional:
                    a = ins.target
                    continue
                todo.append(ins.target)
            if ins.op in ('bclr', 'bcctr') and ins.unconditional:
                break
            a += 4
    end = max(seen) + 4
    missing = [x for x in range(entry, end, 4) if x not in seen and img.word(x) != 0]
    return end, limit, missing, leaves, tails


def main():
    img = Image(os.path.join(ROOT, 'out', 'default_image.bin'), 0x82000000)
    args = sys.argv[1:]
    ignore = set()
    if '--ignore' in args:
        i = args.index('--ignore')
        ignore = {int(x, 16) for x in args[i + 1].split(',')}
        del args[i:i + 2]
    starts = registered() - ignore
    for arg in args:
        entry = int(arg, 16)
        end, limit, missing, leaves, tails = walk(img, starts, entry)
        print(f'0x{entry:08X}-0x{end:08X} size 0x{end - entry:X}; next registered start 0x{limit:08X}'
              f'{" (= end)" if limit == end else ""}; unreached words {["0x%08X" % m for m in missing]}; '
              f'branches out {["0x%08X" % x for x in leaves]}; tail calls {[f"0x{a:08X}->0x{t:08X}" for a, t in tails]}; '
              f'registered starts inside {["0x%08X" % s for s in sorted(starts) if entry < s < end]}')


if __name__ == '__main__':
    main()
