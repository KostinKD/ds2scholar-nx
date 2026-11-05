#!/usr/bin/env python3
"""Bisection of the loop barriers by guest function (stage 5, CPU step 2, 2026-10-18; docs/progress.md entry 34).

On the console the step 1 build plus tools/loop_barriers.py alone (volatile kept: DS2_GUEST_VOLATILE=ON) breaks the
world image (models' shaders from FlverShader.bnd hold foreign data: "unidentified pixel shader" > 0 in the ds2 log,
0 in good runs); the PC is clean. A compiler barrier does not change correct code, so some function's GCC output is
wrong once barriers move its code around. This keeps the barriers only in a range of the functions that have them, so
console runs can halve the range until one function is left.

  python tools/barrier_bisect.py snapshot  # after loop_barriers.py on the whole tree: saves the full-barrier files
                                           # (out/bisect_full/) and the ordered list of functions with barriers
  python tools/barrier_bisect.py apply LO HI  # barriers only in functions [LO, HI) of that list (0-based)
  python tools/barrier_bisect.py restore      # every barrier back (the snapshot)

Files are written only when their text changes, so a build recompiles only them. The pch keeps the REX_LOOP_BARRIER
macro in every state. State: logs/barrier_bisect.txt (function list) and logs/barrier_bisect_state.txt (last range).
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, 'app', 'generated', 'default')
FULL = os.path.join(ROOT, 'out', 'bisect_full')
LIST = os.path.join(ROOT, 'logs', 'barrier_bisect.txt')
STATE = os.path.join(ROOT, 'logs', 'barrier_bisect_state.txt')
FUNC = re.compile(r'^DEFINE_REX_FUNC\((sub_[0-9A-F]{8})\)')
BARRIER = '\tREX_LOOP_BARRIER();'


def cpp_files(folder):
    return sorted(f for f in os.listdir(folder) if re.match(r'ds2_recomp\.\d+\.cpp$', f))


def functions_with_barriers(text):
    """Names of the functions of one file that contain a barrier line, in file order."""
    out, cur = [], None
    for line in text.split('\n'):
        m = FUNC.match(line)
        if m:
            cur = m.group(1)
        elif line == BARRIER and cur and (not out or out[-1] != cur):
            out.append(cur)
    return out


def strip(text, keep):
    """The text without the barrier lines of the functions not in `keep`."""
    lines, cur, res = text.split('\n'), None, []
    for line in lines:
        m = FUNC.match(line)
        if m:
            cur = m.group(1)
        if line == BARRIER and cur not in keep:
            continue
        res.append(line)
    return '\n'.join(res)


def write_if_changed(path, text):
    old = open(path, encoding='utf-8', newline='').read()
    if old == text:
        return False
    open(path, 'w', encoding='utf-8', newline='\n').write(text)
    return True


def snapshot():
    if 'REX_LOOP_BARRIER()' not in open(os.path.join(GEN, 'ds2_pch.h'), encoding='utf-8').read():
        sys.exit('barrier_bisect: the pch has no REX_LOOP_BARRIER macro: run tools/loop_barriers.py first')
    os.makedirs(FULL, exist_ok=True)
    names = []
    for f in cpp_files(GEN):
        text = open(os.path.join(GEN, f), encoding='utf-8', newline='').read()
        shutil.copyfile(os.path.join(GEN, f), os.path.join(FULL, f))
        names += functions_with_barriers(text)
    names.sort()
    with open(LIST, 'w', encoding='utf-8', newline='\n') as out:
        out.write('\n'.join(names) + '\n')
    print(f'barrier_bisect: {len(names)} functions with barriers, snapshot in {FULL}')


def apply(lo, hi):
    names = open(LIST, encoding='utf-8').read().split()
    lo, hi = max(0, lo), min(len(names), hi)
    keep = set(names[lo:hi])
    changed = 0
    for f in cpp_files(FULL):
        text = open(os.path.join(FULL, f), encoding='utf-8', newline='').read()
        changed += write_if_changed(os.path.join(GEN, f), strip(text, keep))
    with open(STATE, 'w', encoding='utf-8', newline='\n') as out:
        out.write(f'{lo} {hi} {names[lo] if lo < hi else "-"} {names[hi - 1] if lo < hi else "-"}\n')
    print(f'barrier_bisect: barriers in functions [{lo}, {hi}) of {len(names)} '
          f'({names[lo] if lo < hi else "-"} .. {names[hi - 1] if lo < hi else "-"}), {changed} files written')


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == 'snapshot':
        snapshot()
    elif sys.argv[1] == 'apply' and len(sys.argv) == 4:
        apply(int(sys.argv[2]), int(sys.argv[3]))
    elif sys.argv[1] == 'restore':
        apply(0, 1 << 30)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
