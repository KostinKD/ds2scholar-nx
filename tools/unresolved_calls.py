#!/usr/bin/env python3
"""Turns the generator's "target not in any function" errors into app/overrides.toml entries with their evidence.

Reads out/codegen.log (lines `0xTARGET from 0xSOURCE: b 0xTARGET from 0xSOURCE - target not in any function`) and the
image dump (out/default_image.bin, REXGLUE_DUMP_IMAGE of tools/codegen.ps1), and classifies each target the way
ds2-nx did by hand (docs/ds2-nx/analysis/codegen.md, "target not in any function"):
  thunk     the branch is preceded by `lwz r3,8(r3)`: an adjustor thunk tail-calling the target
  fragment  a backward `b` of at most 0x100 bytes, the target in no .pdata function: a leaf without .pdata that
            discovery split at an early `blr`; safe in the classic codegen, needs share_registers if optimised
  tail call any other `b` into unclaimed code
Targets strictly inside a .pdata function are reported and not written (not a function start).

  python tools/unresolved_calls.py --header "<comment line>" [--write]     prints the entries; --write appends them
"""
import argparse
import bisect
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x82000000


def pdata(img):
    pe = struct.unpack_from("<I", img, 0x3C)[0]
    count = struct.unpack_from("<H", img, pe + 6)[0]
    table = pe + 24 + struct.unpack_from("<H", img, pe + 20)[0]
    for i in range(count):
        name, vsize, va = struct.unpack_from("<8sII", img, table + 40 * i)
        if name.rstrip(b"\0") == b".pdata":
            out = []
            for o in range(va, va + vsize, 8):
                b, f = struct.unpack_from(">II", img, o)
                if b:
                    out.append((b, b + ((f >> 8) & 0x3FFFFF) * 4))
            return sorted(out)
    sys.exit("no .pdata in the image")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(ROOT, "out", "codegen.log"))
    ap.add_argument("--image", default=os.path.join(ROOT, "out", "default_image.bin"))
    ap.add_argument("--header", default="", help="comment written above the entries")
    ap.add_argument("--write", action="store_true", help="append to app/overrides.toml")
    args = ap.parse_args()

    img = open(args.image, "rb").read()
    funcs = pdata(img)
    starts = [f[0] for f in funcs]

    def inside(a):
        j = bisect.bisect_right(starts, a) - 1
        return j >= 0 and funcs[j][0] < a < funcs[j][1]

    word = lambda a: struct.unpack_from(">I", img, a - BASE)[0]
    pairs = {}
    for m in re.finditer(r"(0x[0-9A-F]{8}) from (0x[0-9A-F]{8}): b .* - target not in any function", open(args.log).read()):
        pairs.setdefault(int(m.group(1), 16), []).append(int(m.group(2), 16))
    lines, skipped = [], []
    for t in sorted(pairs):
        src = pairs[t][0]
        if inside(t):
            skipped.append("0x%08X (inside a .pdata function; from 0x%08X)" % (t, src))
            continue
        if word(src - 4) == 0x80630008:
            kind = "thunk: lwz r3,8(r3); b"
        elif t < src and src - t <= 0x100 and not inside(src):
            kind = "split fragment of a leaf without .pdata (backward b); share_registers if optimised"
        else:
            kind = "tail call (b)"
        srcs = ", ".join("0x%08X" % s for s in pairs[t])
        lines.append('"0x%08X" = { }  # from %s: %s' % (t, srcs, kind))
    text = "".join("# %s\n" % h for h in args.header.split("\\n") if h) + "\n".join(lines) + "\n"
    print(text)
    for s in skipped:
        print("NOT WRITTEN:", s, file=sys.stderr)
    if args.write and lines:
        with open(os.path.join(ROOT, "app", "overrides.toml"), "a", encoding="utf-8", newline="\n") as f:
            f.write("\n" + text)


if __name__ == "__main__":
    main()
