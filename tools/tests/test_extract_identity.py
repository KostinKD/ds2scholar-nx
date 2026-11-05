import contextlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('extract_iso',Path(__file__).resolve().parents[1]/'extract_iso.py')
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)


class ExtractIdentityTests(unittest.TestCase):
    def test_ds2_xex_is_not_reported_as_wrong_mass_effect_game(self):
        data = bytearray(0x1000)
        data[:4] = b'XEX2'
        struct.pack_into('>II',data,0x10,0x300,1)
        struct.pack_into('>II',data,0x18,0x00040006,0x200)
        struct.pack_into('>IIII',data,0x200,0x458B3E06,0x16,0,0x465307E4)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'default.xex'
            path.write_bytes(data)
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                extractor.print_xex_info(path)
        self.assertIn('465307E4',text.getvalue())
        self.assertNotIn('written for Mass Effect',text.getvalue())
        self.assertIn('shared',text.getvalue())


if __name__=='__main__':
    unittest.main()
