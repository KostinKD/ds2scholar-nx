"""Prints texels of row Y of a tiled 32-bit Xenos texture dumped from guest memory (ds2_diag_guest_dump).

  python -I tools/untile_row.py <dump.bin> <pitch texels> [row] [step]

Address of texel (x, y): Xenos 2D tiling for 4-byte texels, the same formula as xenia's GetTiledOffset2D
(texture_util / the renderer's TableTile2DTexel4). Bytes are printed as stored in guest memory (big-endian words).
"""
import sys


def tiled_offset_2d(x, y, pitch, bpb_log2=2):
    pitch = (pitch + 31) & ~31
    macro = ((x >> 5) + (y >> 5) * (pitch >> 5)) << (bpb_log2 + 7)
    micro = ((x & 7) + ((y & 0xE) << 2)) << bpb_log2
    offset = macro + ((micro & ~0xF) << 1) + (micro & 0xF) + ((y & 1) << 4)
    return ((offset & ~0x1FF) << 3) + ((y & 16) << 7) + ((offset & 0x1C0) << 2) + \
        (((((y & 8) >> 2) + (x >> 3)) & 3) << 6) + (offset & 0x3F)


def main():
    data = open(sys.argv[1], 'rb').read()
    pitch = int(sys.argv[2])
    row = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    step = int(sys.argv[4]) if len(sys.argv) > 4 else 16
    out = []
    for x in range(0, pitch, step):
        a = tiled_offset_2d(x, row, pitch)
        out.append(f'[{x}]{data[a:a + 4].hex().upper()}')
    print(' '.join(out))


if __name__ == '__main__':
    main()
