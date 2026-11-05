from pathlib import Path
import struct,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from social_seed import cell_id, message_payload, network_grid, translate_replay, replay_positions


class SeedCodecTests(unittest.TestCase):
    def test_replay_translates_pose_and_impact_without_changing_animation(self):
        # Synthetic v57 body: fixed appearance, two event indices, pose+impact packets.
        body=bytearray(504)
        struct.pack_into('>HHII',body,0,57,2,17,33)
        struct.pack_into('>II',body,496,0x00010000,0x0002000e)
        pose=struct.pack('>H3h6s',12,32,64,96,b'ABCDEF')
        impact=bytearray(24);struct.pack_into('>3h',impact,8,40,48,88)
        body.extend(pose+pose+struct.pack('>H',7*1024+24)+impact)
        raw=struct.pack('>I3h2xI',0x0039000A,32,64,96,17)+body
        shifted=translate_replay(raw,'ghost',(11,22,33),77,400)
        self.assertEqual(replay_positions(shifted,'ghost'),[(11.,22.,33.),(11.,22.,33.)])
        self.assertEqual(struct.unpack_from('>I',shifted,12)[0],77)
        self.assertEqual(struct.unpack_from('>II',shifted,20),(77,400))
        self.assertEqual(shifted[16+12:16+496],raw[16+12:16+496])
        self.assertEqual(shifted[16+496:16+504],raw[16+496:16+504])
        self.assertEqual(shifted[-24:-16],raw[-24:-16])
        self.assertEqual(struct.unpack_from('>3h',shifted,len(shifted)-16),(360,688,1048))
        self.assertEqual(shifted[-10:],raw[-10:])
        with self.assertRaises(ValueError):translate_replay(raw[:-1],'ghost',(11,22,33),77,400)
        with self.assertRaises(ValueError):translate_replay(raw,'ghost',(2000,22,33),77,400)
    def test_cell_matches_sotfs_30_20_30_partition(self):
        grid=(30.,20.,30.,0.,0.,0.)
        self.assertEqual(cell_id((10.5,5.90625,-16.25),grid),0xffc00000)
        self.assertEqual(cell_id((-35.3125,11.9375,-48.03125),grid),0xff8003fe)
        self.assertEqual(cell_id((175.375,-23.75,46.84375),grid),0x7ff805)
        self.assertEqual(cell_id((-0.001,0.,0.),grid),1023)
        with self.assertRaises(ValueError):cell_id((20000.,0.,0.),grid)

    def test_message_changes_only_proven_fields(self):
        donor=struct.pack('>I3h2B6H',2,32,64,96,19,0,0,65535,1000,65535,65280,0)
        data=message_payload(donor,(-1.02,2.5,3.1),3,4040)
        self.assertEqual(struct.unpack_from('>3h',data,4),(-32,80,99))
        self.assertEqual(struct.unpack_from('>H',data,12)[0],3)
        self.assertEqual(struct.unpack_from('>H',data,16)[0],4040)
        self.assertEqual(data[:4],donor[:4])
        self.assertEqual(data[10:12],donor[10:12])
        self.assertEqual(data[14:16],donor[14:16])
        self.assertEqual(data[18:],donor[18:])
        for p in ((float('nan'),0,0),(2048.,0,0)):
            with self.assertRaises(ValueError):message_payload(donor,p,0,1000)
        with self.assertRaises(ValueError):message_payload(bytes(24),(0,0,0),0,1000)

    def test_grid_reads_actual_param_layout(self):
        b=bytearray(104);struct.pack_into('>H',b,10,1)
        b[12:30]=b'NETWORK_AREA_PARAM'
        struct.pack_into('>III',b,64,10040000,76,0)
        struct.pack_into('>6f',b,76,30,20,30,0,0,0)
        self.assertEqual(network_grid(b,10040000),(30.,20.,30.,0.,0.,0.))
        with self.assertRaises(ValueError):network_grid(b,999)


if __name__=='__main__':unittest.main()
