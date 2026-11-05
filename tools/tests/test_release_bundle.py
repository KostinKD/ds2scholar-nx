import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from test_forwarder import nro_bytes, npdm_bytes, pfs0_bytes

SOURCE = Path(__file__).resolve().parents[1]


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        path = SOURCE/'release_bundle.py'
        self.assertTrue(path.is_file(), 'public release bundler is missing')
        spec = importlib.util.spec_from_file_location('release_bundle',path)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'repo'
        self.root.mkdir()
        for name in ('tools','app','docs/players','sdk/example','assets'):
            (self.root/name).mkdir(parents=True)
        shutil.copyfile(SOURCE/'make_public_config.py',self.root/'tools/make_public_config.py')
        for name in ('god_extract.py','extract_iso.py','stfs_extract.py'):
            (self.root/'tools'/name).write_text('# extractor fixture\n')
        (self.root/'app/ds2_switch.toml').write_text('log_to_file = true\n# Online and P2P LAN Co-op\nnet_dns_address = "192.168.1.1"\nnet_profile_xuid = "private"\n')
        (self.root/'app/online_public.toml').write_text('net_dns_address = "ds2scholar.download"\nnet_p2p_relay = true\n')
        (self.root/'docs/players/README.md').write_text('Install from HOME. Preserve ds2/.\n')
        for name in ('LICENSE','THIRD_PARTY_NOTICES.md','sdk/example/LICENSE.txt'):
            (self.root/name).write_text('license fixture\n')
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        subprocess.run(['git','-C',str(self.root),'add','LICENSE','THIRD_PARTY_NOTICES.md','sdk/example/LICENSE.txt'],check=True)
        (self.root/'assets/default.xex').write_bytes(b'XEX2private game')
        (self.root/'prod.keys').write_text('private console key fixture')
        self.nro = self.root/'ds2.nro'
        self.nro.write_bytes(nro_bytes()[0])
        self.shaders = self.root/'shader-input'
        self.shaders.mkdir()
        for name in ('sa2_shaders.mesp','sa2_shaders.mesp.idx'):
            (self.shaders/name).write_bytes(b'shader fixture')
        self.output = self.root/'release'

    def forwarder(self, mismatch=False):
        folder = self.root/'forwarder'
        folder.mkdir()
        nsp = pfs0_bytes(['a'*32+'.nca','b'*32+'.nca','c'*32+'.cnmt.nca'])
        (folder/'ds2.nsp').write_bytes(nsp)
        (folder/'main.npdm').write_bytes(npdm_bytes())
        control = bytearray(nro_bytes()[2]); control[0x3025] = 1
        (folder/'control.nacp').write_bytes(control)
        report = {'nsp_sha256':hashlib.sha256(nsp).hexdigest(),'nro_path':'sdmc:/switch/ds2scholar-nx/ds2.nro',
                  'nro_sha256':('0'*64 if mismatch else hashlib.sha256(self.nro.read_bytes()).hexdigest()),'nro_version':'1.2.3'}
        (folder/'validation.json').write_text(json.dumps(report))
        (folder/'SHA256SUMS.txt').write_text(hashlib.sha256(nsp).hexdigest()+'  ds2.nsp\n')
        for name in ('LICENSE-Forwarder-Mod.txt','LICENSE-hacBrewPack.txt'):
            (folder/name).write_text('forwarder license')
        return folder

    def test_complete_zip_includes_forwarder_licenses_and_public_config_only(self):
        archive = self.tool.package(self.root,self.nro,self.shaders,self.output,self.forwarder())
        with zipfile.ZipFile(archive) as packed:
            self.assertIsNone(packed.testzip())
            names = set(packed.namelist())
            self.assertIn('switch/ds2scholar-nx/ds2scholar-forwarder.nsp',names)
            self.assertIn('licenses/sdk/example/LICENSE.txt',names)
            self.assertIn('licenses/forwarder/LICENSE-Forwarder-Mod.txt',names)
            self.assertIn('SHA256SUMS.txt',names)
            config = packed.read('switch/ds2scholar-nx/ds2.toml').decode()
            self.assertIn('ds2scholar.download',config)
            self.assertNotIn('192.168.1.1',config)
            self.assertNotIn('net_profile_xuid',config)
            self.assertFalse(any('assets/' in name or name.endswith('.keys') for name in names))
            for line in packed.read('SHA256SUMS.txt').decode().splitlines():
                digest,name = line.split('  ',1)
                self.assertEqual(hashlib.sha256(packed.read(name)).hexdigest(),digest)

    def test_rejects_forwarder_for_different_nro_before_creating_output(self):
        with self.assertRaisesRegex(ValueError,'NRO|nro'):
            self.tool.package(self.root,self.nro,self.shaders,self.output,self.forwarder(mismatch=True))
        self.assertFalse(self.output.exists())

    def test_missing_shader_does_not_create_partial_release(self):
        (self.shaders/'sa2_shaders.mesp.idx').unlink()
        with self.assertRaises((ValueError,FileNotFoundError)):
            self.tool.package(self.root,self.nro,self.shaders,self.output)
        self.assertFalse(self.output.exists())

    def test_existing_release_is_preserved(self):
        self.output.mkdir()
        (self.output/'keep').write_text('original')
        with self.assertRaises(ValueError):
            self.tool.package(self.root,self.nro,self.shaders,self.output)
        self.assertEqual((self.output/'keep').read_text(),'original')

    def test_runtime_only_mode_does_not_require_forwarder(self):
        archive = self.tool.package(self.root,self.nro,self.shaders,self.output)
        with zipfile.ZipFile(archive) as packed:
            self.assertFalse(any(name.endswith('.nsp') for name in packed.namelist()))

    def test_player_zip_document_links_do_not_point_outside_the_package(self):
        (self.root/'docs/players/README.md').write_text('See [PGO](../pgo-profile.md) and [rebuild](../rebuild.md).\n')
        (self.root/'THIRD_PARTY_NOTICES.md').write_text('[SDK license](sdk/example/LICENSE.txt)\n[Workflow](docs/workflow.md)\n')
        archive = self.tool.package(self.root,self.nro,self.shaders,self.output)
        with zipfile.ZipFile(archive) as packed:
            guide = packed.read('README.md').decode()
            notices = packed.read('THIRD_PARTY_NOTICES.md').decode()
            self.assertNotIn('../',guide)
            self.assertIn('SOURCE_BUILD.md',packed.namelist())
            self.assertIn('(licenses/sdk/example/LICENSE.txt)',notices)
            self.assertNotIn('(docs/workflow.md)',notices)


if __name__=='__main__':
    unittest.main()
