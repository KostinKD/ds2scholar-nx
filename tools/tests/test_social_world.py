import json
import math
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from social_world import read_ngp, read_msb_objects, plan_zone, require_deployable, decode_position, validate_world_draft


def ngp_fixture():
    b = bytearray(200)
    b[:4] = b'NVG2'
    struct.pack_into('>H', b, 4, 1)
    struct.pack_into('>I', b, 8, 1)
    struct.pack_into('>I', b, 48, 52)
    struct.pack_into('>Ih', b, 52 + 36, 3, 1)
    struct.pack_into('>III', b, 52 + 52, 128, 164, 168)
    for i, v in enumerate(((0, 6, 0), (12, 6, 0), (0, 6, 12))):
        struct.pack_into('>3f', b, 128 + 12 * i, *v)
    struct.pack_into('>6h', b, 168, 0, 1, 2, 0, 0, 0)
    return bytes(b)


class SocialWorldTests(unittest.TestCase):
    def test_saved_world_draft_reopens_and_rejects_floating_point(self):
        meshes = read_ngp(ngp_fixture())
        draft = plan_zone(meshes, dict(x=4, z=4, radius=8, min_y=5, max_y=7,
                                     count=3, kinds=['message'], seed=1))
        draft['source_ngp_sha256'] = 'fixture'
        checked = validate_world_draft(meshes, draft, 'fixture')
        self.assertEqual(checked['placements'], draft['placements'])
        with self.assertRaises(ValueError):
            validate_world_draft(meshes, draft, 'different-game-data')
        for count in ('13', -1, 1000000):
            with self.subTest(count=count), self.assertRaises(ValueError):
                validate_world_draft(meshes, draft | {'zone': draft['zone'] | {'count': count}}, 'fixture')
        draft['placements'][0]['position'][1] += 2
        with self.assertRaises(ValueError):
            validate_world_draft(meshes, draft, 'fixture')

    def test_xbox_position_is_signed_fixed_point_not_float(self):
        stain = struct.pack('>II3hH', 0x0039000B, 17, 40, -64, 160, 0)
        self.assertEqual(decode_position(stain, 'blood'), [1.25, -2., 5.])
        message = struct.pack('>I3h', 2, -40, 64, -160) + bytes(14)
        self.assertEqual(decode_position(message, 'message'), [-1.25, 2., -5.])
        ghost = struct.pack('>I3hI', 0x0039000A, 80, -128, 320, 0)
        self.assertEqual(decode_position(ghost, 'ghost'), [2.5, -4., 10.])
        for data, kind in ((stain[:10], 'blood'), (b'\0'*16, 'blood'), (ghost, 'bad')):
            with self.assertRaises(ValueError):
                decode_position(data, kind)

    def test_ngp_real_layout_and_fail_closed(self):
        result = read_ngp(ngp_fixture())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['vertices'][1], [12., 6., 0.])
        self.assertEqual(result[0]['faces'], [[0, 1, 2]])
        for bad in (b'', b'NOPE' + ngp_fixture()[4:], ngp_fixture()[:140]):
            with self.assertRaises(ValueError):
                read_ngp(bad)
        b = bytearray(ngp_fixture())
        struct.pack_into('>h', b, 168, 99)
        with self.assertRaises(ValueError):
            read_ngp(b)
        b = bytearray(ngp_fixture())
        struct.pack_into('>f', b, 128, math.nan)
        with self.assertRaises(ValueError):
            read_ngp(b)

    def test_msb_rejects_corrupt_offsets(self):
        with self.assertRaises(ValueError):
            read_msb_objects(b'\0' * 48)

    def test_balanced_deterministic_surface_only(self):
        meshes = read_ngp(ngp_fixture())
        zone = dict(x=4, z=4, radius=8, min_y=5, max_y=7,
                    count=13, kinds=['message', 'blood', 'ghost'], seed=513416692)
        a = plan_zone(meshes, zone)
        self.assertEqual(a, plan_zone(meshes, zone))
        self.assertEqual(len(a['placements']), 13)
        counts = {k: sum(p['kind'] == k for p in a['placements']) for k in zone['kinds']}
        self.assertEqual(sorted(counts.values()), [4, 4, 5])
        for p in a['placements']:
            x, y, z = p['position']
            self.assertAlmostEqual(y, 6)
            self.assertGreater(x, 0)
            self.assertGreater(z, 0)
            self.assertLess(x + z, 12)
            self.assertLessEqual(math.hypot(x-4, z-4), 8)
        self.assertFalse(a['deployable'])
        with self.assertRaises(ValueError):
            require_deployable(a)

    def test_floor_filter_and_empty_surface(self):
        meshes = read_ngp(ngp_fixture())
        zone = dict(x=4, z=4, radius=8, min_y=-20, max_y=-10,
                    count=13, kinds=['message'], seed=1)
        result = plan_zone(meshes, zone)
        self.assertEqual(result['placements'], [])
        self.assertEqual(result['unplaced'], 13)

    def test_invalid_zone(self):
        good = dict(x=4, z=4, radius=8, min_y=5, max_y=7,
                    count=13, kinds=['message'], seed=1)
        for changes in ({'radius': -1}, {'x': math.inf}, {'kinds': []},
                        {'kinds': ['invalid']}, {'count': 1000000}, {'min_y': 8}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                plan_zone(read_ngp(ngp_fixture()), good | changes)


if __name__ == '__main__':
    unittest.main()
