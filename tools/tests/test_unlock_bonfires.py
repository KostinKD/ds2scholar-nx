import hashlib
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unlock_bonfires import BONFIRE_IDS, unlock_bonfires


def fixture():
    data = bytearray(499976)
    signature = struct.pack('>' + 'H' * len(BONFIRE_IDS), *BONFIRE_IDS)
    for anchor in (0x282C8, 0x2E324):
        data[anchor:anchor + len(signature)] = signature
        data[anchor + 512] = 1
        data[anchor + 513] = 2  # Preserve existing nonzero lit states.
        data[anchor + 768:anchor + 1024] = bytes(range(256))
    data[-16:] = hashlib.md5(data[:-16]).digest()
    return bytes(data)


class UnlockBonfiresTest(unittest.TestCase):
    def test_changes_only_unlit_flags_in_both_copies_and_md5(self):
        original = fixture()
        patched, report = unlock_bonfires(original)
        allowed = set(range(len(original) - 16, len(original)))
        for anchor in (0x282C8, 0x2E324):
            base = anchor + 512
            allowed.update(range(base, base + len(BONFIRE_IDS)))
            self.assertEqual(patched[base:base + 2], b'\x01\x02')
            self.assertTrue(all(patched[base:base + len(BONFIRE_IDS)]))
        self.assertTrue(all(i in allowed for i, (a, b) in enumerate(zip(original, patched)) if a != b))
        self.assertEqual(hashlib.md5(patched[:-16]).digest(), patched[-16:])
        self.assertEqual(report['newly_lit'], 75)
        self.assertEqual(report['total'], 77)

    def test_idempotent(self):
        patched, _ = unlock_bonfires(fixture())
        twice, report = unlock_bonfires(patched)
        self.assertEqual(twice, patched)
        self.assertEqual(report['newly_lit'], 0)

    def test_refuses_corrupt_checksum(self):
        data = bytearray(fixture())
        data[0] ^= 1
        with self.assertRaisesRegex(ValueError, 'MD5'):
            unlock_bonfires(bytes(data))

    def test_refuses_pc_container(self):
        with self.assertRaises(ValueError):
            unlock_bonfires(b'BND4' + bytes(7203100))

    def test_refuses_missing_or_disagreeing_copies(self):
        for change in ('signature', 'state'):
            data = bytearray(fixture())
            data[0x2E324 + (0 if change == 'signature' else 514)] ^= 1
            data[-16:] = hashlib.md5(data[:-16]).digest()
            with self.assertRaises(ValueError):
                unlock_bonfires(bytes(data))


if __name__ == '__main__':
    unittest.main()
