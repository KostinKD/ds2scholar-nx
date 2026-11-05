#!/usr/bin/env python3
"""Stage 4: finds the game's XDK Direct3D functions by their own signatures, without a reference game.

tools/d3d_match.py needs a game whose D3D functions are already named (its image and generated tree); none is on this
machine for ds2 (2026-10-16). Every Direct3D function the native renderer hooks leaves a trace in the code instead:

  swap      the callers of the kernel import VdSwap (thunk 0x83402004, logs/xex_imports.log)
  const     functions that build a 32-bit constant with lis + ori/addi (e.g. the shader container magics
            0x102A1101 vertex / 0x102A1100 pixel, checked by the Create*Shader functions)
  draws     functions that build a PM4 type-3 header 0xC0nn2200 (DRAW_INDX) or 0xC0nn3600 (DRAW_INDX_2)
  callers   the functions that call an address (bl), with the call sites

  python tools/d3d_find.py callers 0x83402004
  python tools/d3d_find.py const 0x102A1101 0x102A1100
  python tools/d3d_find.py draws

Function bounds come from the generated tree's function table (app/generated/default/ds2_init.cpp, start addresses;
a function ends where the next one starts).
"""
import argparse
import bisect
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ppc_mini import Image, decode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_LO, CODE_HI = 0x82240000, 0x83438264  # SotFS .text (REX_CODE_BASE / REX_CODE_SIZE); DS2 ended at 0x83402474


class Code:
    def __init__(self):
        self.img = Image(os.path.join(ROOT, 'out', 'default_image.bin'), 0x82000000)
        init = open(os.path.join(ROOT, 'app', 'generated', 'default', 'ds2_init.cpp'), errors='replace').read()
        self.starts = sorted({int(m, 16) for m in re.findall(r'\{ 0x([0-9A-F]{8}), sub_', init)})

    def func_of(self, addr):
        i = bisect.bisect_right(self.starts, addr) - 1
        return self.starts[i] if i >= 0 else None

    def words(self):
        for a in range(CODE_LO, CODE_HI, 4):
            yield a, self.img.word(a)

    def bl_targets(self):
        for a, w in self.words():
            if w >> 26 == 18 and w & 1:  # bl (or bla)
                li = w & 0x3FFFFFC
                if li & 0x2000000:
                    li -= 0x4000000
                yield a, (li if w & 2 else a + li) & 0xFFFFFFFF

    def constants(self, window=8):
        """(address, value, register) of every lis rX,hi followed within `window` instructions by ori/addi rY,rX,lo."""
        for a, w in self.words():
            if w >> 26 != 15 or (w >> 16) & 31 != 0:  # lis = addis rD,0,imm
                continue
            rd, hi = (w >> 21) & 31, (w & 0xFFFF) << 16
            for b in range(a + 4, min(a + 4 * (window + 1), CODE_HI), 4):
                x = self.img.word(b)
                op, rx, ra, imm = x >> 26, (x >> 21) & 31, (x >> 16) & 31, x & 0xFFFF
                if op == 24 and rx == rd:  # ori rA,rS,imm: rS is bits 21-25, rA bits 16-20
                    yield b, (hi | imm) & 0xFFFFFFFF, ra
                    break
                if op == 14 and ra == rd:  # addi rD,rA,simm
                    yield b, (hi + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF, rx
                    break


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('callers')
    c.add_argument('addr', nargs='+')
    k = sub.add_parser('const')
    k.add_argument('value', nargs='+')
    sub.add_parser('draws')
    a = ap.parse_args()
    code = Code()

    if a.cmd == 'callers':
        wanted = {int(x, 16) for x in a.addr}
        by = collections.defaultdict(list)
        for site, target in code.bl_targets():
            if target in wanted:
                by[target].append(site)
        for t in sorted(wanted):
            sites = by.get(t, [])
            funcs = collections.Counter(code.func_of(s) for s in sites)
            print(f'0x{t:08X}: {len(sites)} calls from {len(funcs)} functions')
            for f, n in funcs.most_common():
                print(f'    sub_{f:08X}  x{n}  sites ' + ' '.join(f'0x{s:08X}' for s in sites if code.func_of(s) == f))

    elif a.cmd == 'const':
        wanted = {int(x, 16) for x in a.value}
        hits = collections.defaultdict(list)
        for site, value, _ in code.constants():
            if value in wanted:
                hits[value].append(site)
        for v in sorted(wanted):
            funcs = collections.Counter(code.func_of(s) for s in hits.get(v, []))
            print(f'0x{v:08X}: {len(hits.get(v, []))} sites in {len(funcs)} functions')
            for f, n in funcs.most_common(20):
                print(f'    sub_{f:08X}  x{n}')

    elif a.cmd == 'draws':
        hits = collections.defaultdict(list)
        for site, value, _ in code.constants():
            if value >> 24 == 0xC0 and (value & 0xFF) == 0 and ((value >> 8) & 0xFF) in (0x22, 0x36):
                hits[code.func_of(site)].append((site, value))
        for f, lst in sorted(hits.items(), key=lambda kv: -len(kv[1])):
            print(f'sub_{f:08X}: ' + ', '.join(f'0x{v:08X}@{s:08X}' for s, v in lst[:6]))


if __name__ == '__main__':
    main()
