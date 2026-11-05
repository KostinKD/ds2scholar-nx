import hashlib
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from give_invasion_orbs import give_orbs


def fixture():
    data = bytearray(111308)
    data[960:968] = 'test'.encode('utf-16-be')
    for offset, item, qty in ((0x1E2C, 62160000, 1), (0x1E3C, 60010000, 12)):
        struct.pack_into('>IIHHI', data, offset, item, 0, qty, 0, 0)
    data[-16:] = hashlib.md5(data[:-16]).digest()
    return bytes(data)


class GiveOrbsTests(unittest.TestCase):
    def test_new_stack_and_exact_changed_region(self):
        old = fixture()
        new, report = give_orbs(old, 50, 'test')
        self.assertEqual(struct.unpack_from('>IIHHI', new, 0x1E4C), (62060000, 0, 50, 0, 0))
        self.assertEqual(new[:0x1E4C], old[:0x1E4C])
        self.assertEqual(new[0x1E5C:-16], old[0x1E5C:-16])
        self.assertEqual(hashlib.md5(new[:-16]).digest(), new[-16:])
        self.assertEqual(report['name'], 'test')

    def test_idempotent_and_existing_stack_preserves_flags(self):
        data, _ = give_orbs(fixture(), 50, 'test')
        self.assertEqual(give_orbs(data, 50, 'test')[0], data)
        self.assertEqual(struct.unpack_from('>H', data, 0x1E4C + 8)[0], 50)

    def test_reject_invalid_input(self):
        for data, count, name in ((b'BND4', 50, 'test'), (bytes(111308), 50, 'test'),
                                  (fixture(), 100, 'test'), (fixture(), 50, 'other')):
            with self.subTest(length=len(data), count=count, name=name), self.assertRaises(ValueError):
                give_orbs(data, count, name)


if __name__ == '__main__':
    unittest.main()
