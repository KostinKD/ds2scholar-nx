#!/usr/bin/env python3
"""Writes every shader container of the game's shader bundles (assets/game_root/shader/*.bnd) as an input of
tools/build_shader_library.sh, so the native renderer's package covers the game's shaders before they are met.

The bundles are BND4 (big-endian, UTF-16 names); each entry (.fpo/.vpo) is a zlib stream whose data is the Xenos
shader container Direct3D receives (magic 0x102A1100 pixel / 0x102A1101 vertex). Checked 2026-10-21: all 42 containers
SotFS's runs dumped with sa2_shader_misses are byte-identical to a decompressed entry. Vertex shaders the game patches
for a vertex declaration still come from the run-time dumps (variants), not from here.

  python -I tools/bnd_shader_inputs.py [-o out/shader_inputs/sotfs_bnd] [--skip <dump folder> ...]

Names: ps_b<15 hex of SHA-1>.bin / vs_b...; the package keys shaders by content, the name only has to be unique.
--skip: folders of containers already given to the build (identical ones are not written again).
"""
import argparse
import glob
import hashlib
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bnd4_entries(path):
    d = open(path, "rb").read()
    if d[:4] != b"BND4":
        raise ValueError(f"{path}: not BND4")
    count = struct.unpack_from(">I", d, 0x0C)[0]
    entry_size = struct.unpack_from(">Q", d, 0x20)[0]
    for i in range(count):
        o = 0x40 + i * entry_size
        size = struct.unpack_from(">Q", d, o + 8)[0]
        if entry_size >= 0x24:
            _, offset, _, name_offset = struct.unpack_from(">QIiI", d, o + 0x10)
        else:
            offset, name_offset = struct.unpack_from(">II", d, o + 0x10)
        end = name_offset
        while d[end:end + 2] != b"\0\0":
            end += 2
        yield d[name_offset:end].decode("utf-16-be"), d[offset:offset + size]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, "out", "shader_inputs", "sotfs_bnd"))
    ap.add_argument("--game", default=os.path.join(ROOT, "assets", "game_root", "shader"))
    ap.add_argument("--skip", nargs="*", default=[])
    a = ap.parse_args()
    have = {hashlib.sha1(open(f, "rb").read()).hexdigest() for d in a.skip for f in glob.glob(os.path.join(d, "*.bin"))}
    os.makedirs(a.out, exist_ok=True)
    seen, written, skipped = set(), {"ps": 0, "vs": 0}, 0
    for path in sorted(glob.glob(os.path.join(a.game, "*.bnd"))):
        for name, blob in bnd4_entries(path):
            try:
                container = zlib.decompress(blob)
            except zlib.error:
                container = blob
            kind = {b"\x10\x2a\x11\x00": "ps", b"\x10\x2a\x11\x01": "vs"}.get(container[:4])
            if not kind:
                continue
            h = hashlib.sha1(container).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            if h in have:
                skipped += 1
                continue
            with open(os.path.join(a.out, f"{kind}_b{h[:15]}.bin"), "wb") as f:
                f.write(container)
            written[kind] += 1
    print(f"{len(seen)} unique containers, {skipped} already in --skip folders, written {written} to {a.out}")


if __name__ == "__main__":
    main()
