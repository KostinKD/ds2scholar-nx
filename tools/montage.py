"""2x2 (or 1xN) montage of shots at half size: python -I tools/montage.py <out.png> <shot> [<shot> ...]
Shots: .ppm or .png (8-bit RGB). Used to compare A/B runs of tools/win/native_ab.ps1 at a glance."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from yellow_metric import read  # noqa: E402
from ppm_to_png import write_png  # noqa: E402

out, shots = sys.argv[1], sys.argv[2:]
imgs = [read(p) for p in shots]
w, h = imgs[0][0] // 2, imgs[0][1] // 2
cols = 2 if len(imgs) > 1 else 1
rows = (len(imgs) + cols - 1) // cols
W, H = w * cols, h * rows
buf = bytearray(W * H * 3)
for k, (iw, ih, px) in enumerate(imgs):
    ox, oy = (k % cols) * w, (k // cols) * h
    for y in range(h):
        src = (2 * y) * iw * 3
        dst = ((oy + y) * W + ox) * 3
        row = px[src:src + iw * 3]
        buf[dst:dst + w * 3] = b''.join(row[6 * x:6 * x + 3] for x in range(w))
write_png(out, W, H, bytes(buf))
print(out, W, H)
