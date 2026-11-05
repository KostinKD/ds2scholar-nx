import copy
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock


TOOL = Path(__file__).resolve().parents[1] / 'forwarder.py'
TITLE = 0x01445332534F0000


def nro_bytes():
    icon = b'\xff\xd8test-icon\xff\xd9'
    nacp = bytearray(0x4000)
    nacp[:8] = b'DS2 test'
    nacp[0x3060:0x3065] = b'1.2.3'
    data = bytearray(0x100 + 0x38 + len(icon) + len(nacp))
    data[0x10:0x14] = b'NRO0'
    struct.pack_into('<I', data, 0x18, 0x100)
    data[0x100:0x104] = b'ASET'
    struct.pack_into('<QQQQ', data, 0x108, 0x38, len(icon), 0x38+len(icon), len(nacp))
    data[0x138:0x138+len(icon)] = icon
    data[0x138+len(icon):] = nacp
    return bytes(data), icon, bytes(nacp)


def npdm_bytes(max_cpu=3):
    data = bytearray(0x380)
    data[:4] = b'META'
    data[0xC] = 1 | (3 << 1)
    struct.pack_into('<IIII', data, 0x70, 0x80, 0x50, 0x100, 0x260)
    data[0x80:0x84] = b'ACI0'
    data[0x300:0x304] = b'ACID'
    struct.pack_into('<Q', data, 0x90, TITLE)
    struct.pack_into('<QQ', data, 0x310, TITLE, TITLE)
    struct.pack_into('<II', data, 0xB0, 0x38, 4)
    struct.pack_into('<II', data, 0x330, 0x240, 4)
    flags = (max_cpu << 24) | (28 << 10) | (59 << 4) | 7
    struct.pack_into('<I', data, 0xB8, flags)
    struct.pack_into('<I', data, 0x340, flags)
    return data


def pfs0_bytes(names):
    strings = b''
    entries = b''
    for index,name in enumerate(names):
        entries += struct.pack('<QQII',index*4,4,len(strings),0)
        strings += name.encode()+b'\0'
    return struct.pack('<4sIII',b'PFS0',len(names),len(strings),0)+entries+strings+b'data'*len(names)


def jpeg_header(width=256,height=256,marker=0xC0):
    frame = bytes([8])+struct.pack('>HHB',height,width,3)+bytes([1,0x11,0,2,0x11,1,3,0x11,1])
    return b'\xff\xd8\xff'+bytes([marker])+struct.pack('>H',len(frame)+2)+frame+b'\xff\xd9'


class ForwarderTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL.is_file(), 'forwarder preparation and verification tool is missing')
        spec = importlib.util.spec_from_file_location('forwarder', TOOL)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def test_extracts_exact_assets_and_preserves_version(self):
        data, icon, nacp = nro_bytes()
        self.assertEqual(self.tool.read_nro_assets(data), (icon, nacp))
        control = self.tool.make_control(nacp)
        self.assertEqual(control[0x3025], 1)
        self.assertEqual(control[:0x3025], nacp[:0x3025])
        self.assertEqual(control[0x3060:0x3070], nacp[0x3060:0x3070])

    def test_rejects_truncated_asset_and_wrong_magic(self):
        data, _, _ = nro_bytes()
        for bad in (data[:20], data[:-1], b'bad!' + data[4:16] + b'FAIL' + data[20:]):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                self.tool.read_nro_assets(bad)

    def test_rejects_asset_pointing_inside_header(self):
        data = bytearray(nro_bytes()[0])
        struct.pack_into('<Q', data, 0x108, 0)
        with self.assertRaises(ValueError):
            self.tool.read_nro_assets(data)

    def test_loader_policy_does_not_mutate_template(self):
        template = {'kernel_capabilities': [
            {'type':'kernel_flags','value':{'highest_cpu_id':2,'lowest_cpu_id':0,'highest_thread_priority':59,'lowest_thread_priority':28}},
            {'type':'application_type','value':2}]}
        old = copy.deepcopy(template)
        configured = self.tool.loader_config(template, TITLE, 3)
        self.assertEqual(template, old)
        self.assertEqual(configured['address_space_type'], 3)
        self.assertEqual(configured['kernel_capabilities'][0]['value']['highest_cpu_id'], 3)
        self.assertEqual(configured['kernel_capabilities'][1]['value'], 1)
        self.assertEqual(int(configured['program_id'],16), TITLE)

    def test_loader_policy_requires_single_core_descriptor(self):
        with self.assertRaises(ValueError):
            self.tool.loader_config({'kernel_capabilities':[]}, TITLE, 3)

    def test_validates_both_permission_tables(self):
        result = self.tool.check_npdm(bytes(npdm_bytes()), TITLE, 3)
        self.assertEqual(result['address_space_bits'], 39)
        for table in ('ACI0','ACID'):
            self.assertEqual(result[table]['cpu_range'], [0,3])

    def test_rejects_wrong_address_space_or_id_or_second_cpu_table(self):
        bad_space = npdm_bytes()
        bad_space[0xC] = 1 | (1 << 1)
        bad_id = npdm_bytes()
        struct.pack_into('<Q', bad_id, 0x310, TITLE+1)
        bad_core = npdm_bytes()
        struct.pack_into('<I', bad_core, 0x340, (2 << 24) | (28 << 10) | (59 << 4) | 7)
        for bad in (bad_space,bad_id,bad_core):
            with self.subTest(header=bad[:16]), self.assertRaises(ValueError):
                self.tool.check_npdm(bytes(bad), TITLE, 3)

    def test_rejects_out_of_bounds_permission_table(self):
        bad = npdm_bytes()
        struct.pack_into('<I', bad, 0x330, 0x10000)
        with self.assertRaises(ValueError):
            self.tool.check_npdm(bytes(bad), TITLE, 3)

    def test_target_path_is_fixed_and_no_keys_in_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            loader = target/'loader'
            loader.mkdir()
            (loader/'hbl.json').write_text('{"kernel_capabilities":[{"type":"kernel_flags","value":{}},{"type":"application_type","value":2}]}')
            self.tool.prepare(nro_bytes()[0], loader, target, TITLE, 3)
            self.assertEqual((target/'romfs/nextNroPath').read_text(), 'sdmc:/switch/ds2scholar-nx/ds2.nro')
            self.assertEqual((target/'control/control.nacp').read_bytes()[0x3025], 1)
            self.assertFalse(list(target.rglob('*.keys')))

    def test_extracts_only_required_packing_keys(self):
        self.assertTrue(hasattr(self.tool,'packing_keys'), 'minimal private packing key handling is missing')
        original = 'header_key = '+ '11'*32+'\nkey_area_key_application_00 = '+'22'*16+'\nother_secret = keep-private\n'
        minimal = self.tool.packing_keys(original)
        self.assertIn('header_key',minimal)
        self.assertNotIn('other_secret',minimal)
        for invalid in ('header_key = invalid', 'header_key = '+'11'*32):
            with self.assertRaises(ValueError):
                self.tool.packing_keys(invalid)

    def test_packer_error_suppresses_output_and_removes_temporary_keys(self):
        self.assertTrue(hasattr(self.tool,'pack_nsp'), 'private packer invocation is missing')
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            stage = base/'stage'
            stage.mkdir()
            keys = base/'original.keys'
            original = 'header_key = '+'11'*32+'\nkey_area_key_application_00 = '+'22'*16+'\n'
            keys.write_text(original)
            fake = mock.Mock(returncode=7,stdout=b'private-key-value')
            with mock.patch.object(self.tool.subprocess,'run',return_value=fake):
                with self.assertRaises(RuntimeError) as raised:
                    self.tool.pack_nsp(base/'packer.exe',keys,stage,base/'output',TITLE)
            self.assertNotIn('private-key-value',str(raised.exception))
            self.assertEqual(keys.read_text(),original)
            self.assertEqual(list(base.rglob('*.keys')),[keys])

    @unittest.skipUnless(os.name=='nt','Windows toolchain junction')
    def test_msys_path_preserves_toolchain_alias_without_spaces(self):
        self.assertEqual(self.tool.msys_path(Path('G:/devkitPro')), '/g/devkitPro')

    def test_nsp_container_rejects_truncation_and_non_nca_payload(self):
        self.assertTrue(hasattr(self.tool,'check_nsp'), 'NSP container validation is missing')
        names = ['a'*32+'.nca','b'*32+'.nca','c'*32+'.cnmt.nca']
        valid = pfs0_bytes(names)
        self.assertEqual([entry['name'] for entry in self.tool.check_nsp(valid)],names)
        for bad in (valid[:-1],pfs0_bytes(names[:2]+['prod.keys'])):
            with self.assertRaises(ValueError):
                self.tool.check_nsp(bad)

    def test_dependency_export_excludes_untracked_build_inputs(self):
        self.assertTrue(hasattr(self.tool,'export_source'), 'tracked-only dependency export is missing')
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base/'repo'
            repo.mkdir()
            subprocess.run(['git','init','-q',str(repo)],check=True)
            (repo/'source').mkdir()
            (repo/'source/tracked.c').write_text('int tracked;')
            subprocess.run(['git','-C',str(repo),'add','.'],check=True)
            subprocess.run(['git','-C',str(repo),'-c','user.name=test','-c','user.email=test@example.invalid',
                            'commit','--no-gpg-sign','-qm','fixture'],check=True)
            revision = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
            (repo/'source/injected.c').write_text('int injected;')
            (repo/'stale.o').write_bytes(b'object')
            self.tool.export_source(repo,base/'export',revision)
            self.assertEqual((base/'export/source/tracked.c').read_text(),'int tracked;')
            self.assertFalse((base/'export/source/injected.c').exists())
            self.assertFalse((base/'export/stale.o').exists())

    def test_verify_output_supports_explicit_title_id(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            custom = TITLE+0x1000
            npdm = npdm_bytes()
            for offset in (0x90,0x310,0x318):
                struct.pack_into('<Q',npdm,offset,custom)
            (target/'main.npdm').write_bytes(npdm)
            (target/'control.nacp').write_bytes(self.tool.make_control(nro_bytes()[2]))
            nsp = pfs0_bytes(['a'*32+'.nca','b'*32+'.nca','c'*32+'.cnmt.nca'])
            (target/'test.nsp').write_bytes(nsp)
            (target/'validation.json').write_text(json.dumps({'nsp_sha256':hashlib.sha256(nsp).hexdigest(),'nro_path':self.tool.NRO_PATH}))
            (target/'SHA256SUMS.txt').write_text(hashlib.sha256(nsp).hexdigest()+'  test.nsp\n')
            self.assertIn('title_id',__import__('inspect').signature(self.tool.verify_output).parameters,
                          'explicit title IDs cannot be verified')
            result = self.tool.verify_output(target,3,custom)
            self.assertEqual(result['npdm']['title_id'],f'{custom:016X}')

    def test_custom_icon_must_be_baseline_256_square_jpeg(self):
        self.assertTrue(hasattr(self.tool,'validate_icon'), 'custom HOME icon validation is missing')
        self.assertEqual(self.tool.validate_icon(jpeg_header()),jpeg_header())
        for bad in (b'not jpeg',jpeg_header(64,64),jpeg_header(256,128),jpeg_header(marker=0xC2),jpeg_header()[:-1]):
            with self.assertRaises(ValueError):
                self.tool.validate_icon(bad)

    def test_icon_override_is_used_without_changing_identity(self):
        self.assertIn('icon_data',__import__('inspect').signature(self.tool.prepare).parameters,
                      'custom icon cannot be passed to preparation')
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            loader = stage/'loader'
            loader.mkdir()
            (loader/'hbl.json').write_text('{"kernel_capabilities":[{"type":"kernel_flags","value":{}},{"type":"application_type","value":2}]}')
            self.tool.prepare(nro_bytes()[0],loader,stage,TITLE,3,icon_data=jpeg_header())
            self.assertEqual((stage/'control/icon_AmericanEnglish.dat').read_bytes(),jpeg_header())
            self.assertEqual((stage/'control/control.nacp').read_bytes(),self.tool.make_control(nro_bytes()[2]))


if __name__ == '__main__':
    unittest.main()
