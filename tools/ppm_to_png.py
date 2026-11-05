#!/usr/bin/env python3
"""Converts the binary PPM (P6) shots of the PC build (app/src/ds2_shot.cpp, out/pc/captures/shot_<s>s.ppm) to PNG,
next to each input. Standard library only (zlib for the IDAT stream).

  python tools/ppm_to_png.py out/pc/captures/*.ppm
"""
import struct
import sys
import zlib


def read_ppm(path):
    data = open(path, 'rb').read()
    fields, pos = [], 0
    while len(fields) < 4:  # magic, width, height, maxval; '#' comments are not written by ds2_shot.cpp
        while data[pos:pos + 1].isspace():
            pos += 1
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end
    if fields[0] != b'P6' or fields[3] != b'255':
        sys.exit(f'{path}: not an 8-bit binary PPM')
    width, height = int(fields[1]), int(fields[2])
    return width, height, data[pos + 1:pos + 1 + width * height * 3]


def write_png(path, width, height, rgb):
    def chunk(tag, body):
        return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF)
    raw = b''.join(b'\0' + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
    open(path, 'wb').write(png)


if __name__ == '__main__':
    for name in sys.argv[1:]:
        w, h, pixels = read_ppm(name)
        out = name[:-4] + '.png' if name.lower().endswith('.ppm') else name + '.png'
        write_png(out, w, h, pixels)
        print(f'{out} ({w}x{h})')
