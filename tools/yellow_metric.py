"""Share of saturated-yellow pixels (R and G >= 230, B <= 40) in the scene area of a shot (.ppm or .png).

Stage 4 (2026-10-16): with the native renderer the Majula scene comes out saturated yellow (B lost, R and G clipped);
the emulated GPU gives about 0. Used by tools/win/native_ab.ps1 to bisect renderer cvars.

  python -I tools/yellow_metric.py <shot> [...]
"""
import sys
import zlib


def read(path):
    data = open(path, 'rb').read()
    if data[:2] == b'P6':
        parts = data.split(maxsplit=4)
        w, h = int(parts[1]), int(parts[2])
        return w, h, parts[4][:w * h * 3]
    assert data[:8] == b'\x89PNG\r\n\x1a\n', path
    pos, idat, w = 8, b'', 0
    while pos < len(data):
        n = int.from_bytes(data[pos:pos + 4], 'big')
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if tag == b'IHDR':
            w, h = int.from_bytes(body[:4], 'big'), int.from_bytes(body[4:8], 'big')
            assert body[8] == 8 and body[9] == 2, 'only 8-bit RGB'
        elif tag == b'IDAT':
            idat += body
        pos += 12 + n
    raw, out, prev, stride = zlib.decompress(idat), bytearray(), bytearray(w * 3), w * 3
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 3] if i >= 3 else 0
            b = prev[i]
            c = prev[i - 3] if i >= 3 else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    return w, h, bytes(out)


if __name__ == '__main__':
    for path in sys.argv[1:]:
        w, h, px = read(path)
        yellow = total = 0
        for y in range(h // 6, h * 5 // 6, 2):  # the scene, away from the HUD corners
            row = y * w * 3
            for x in range(w // 3, w * 2 // 3 + w // 6, 2):
                r, g, b = px[row + x * 3], px[row + x * 3 + 1], px[row + x * 3 + 2]
                total += 1
                yellow += r >= 230 and g >= 230 and b <= 40
        print(f'{path}: yellow {100.0 * yellow / total:.1f}%')
