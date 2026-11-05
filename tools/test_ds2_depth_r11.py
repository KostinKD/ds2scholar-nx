"""Compile the real EDRAM shader and verify its storage-image format."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DepthR11(unittest.TestCase):
    def test_depth_export_storage_formats(self):
        compiler = ROOT / 'out/glslang/StandAlone/glslangValidator.exe'
        source = ROOT / 'app/src/me/native/shaders/me_edram_depth_to_16f.comp'
        with tempfile.TemporaryDirectory(dir=ROOT / 'out') as folder:
            for define, expected in (('rgba16f', 2), ('r11f_g11f_b10f', 8)):
                dest = Path(folder) / (define + '.spv')
                subprocess.run([str(compiler), '-V', '-DDST_FMT=' + define,
                                '-o', str(dest), str(source)], check=True, capture_output=True)
                raw = dest.read_bytes()
                words = struct.unpack(f'<{len(raw)//4}I', raw)
                formats = []
                i = 5
                while i < len(words):
                    count, opcode = words[i] >> 16, words[i] & 65535
                    if opcode == 25 and count >= 9:  # OpTypeImage
                        formats.append(words[i + 8])
                    i += count
                self.assertIn(expected, formats, define)
                self.assertNotIn(8 if expected == 2 else 2, formats, define)


if __name__ == '__main__':
    unittest.main()
