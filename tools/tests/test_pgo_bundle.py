import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

MODULE = Path(__file__).resolve().parents[1] / 'pgo_bundle.py'
spec = importlib.util.spec_from_file_location('pgo_bundle', MODULE)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class PgoBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profiles = self.root / 'original'
        self.profiles.mkdir()
        self.payload = struct.pack('<4s4sII', b'adcg', b'*16B', 7, 13)
        self.relative = 'CMakeFiles#ds2_recomp.dir#generated#default#ds2_recomp.0.cpp.gcda'
        self.absolute = 'CMakeFiles#ds2.dir#G_#Owner Folder#port#sdk#src#ui#rex_app.cpp.gcda'
        for name in [self.relative, self.absolute]:
            (self.profiles / name).write_bytes(self.payload)
        self.archive = self.root / 'profile.zip'
        self.layout = self.root / 'codegen.partition.json'
        self.layout.write_text(json.dumps({'version': 2, 'file_count': 1, 'max_file_bytes': 1048576,
                                          'assignments': {'83391DE0': 0}}))

    def pack(self):
        bundle.pack(self.profiles, self.archive, 'G:/Owner Folder/port', 'a' * 40, '16.1.0', self.layout)

    def install(self, compiler='16.1.0'):
        return bundle.install(self.archive, self.root / 'installed', 'D:/Other Folder/port', compiler)

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.archive) as z:
            data = {n: z.read(n) for n in z.namelist()}
        mutate(data)
        with zipfile.ZipFile(self.archive, 'w') as z:
            for name, payload in data.items():
                z.writestr(name, payload)

    def test_round_trip_preserves_data_and_remaps_only_root(self):
        self.pack()
        result = self.install()
        self.assertEqual(result['files'], 2)
        self.assertEqual(result['relocated'], 1)
        expected = self.absolute.replace('G_#Owner Folder#port', 'D_#Other Folder#port')
        self.assertEqual((self.root / 'installed' / expected).read_bytes(), self.payload)
        self.assertEqual((self.root / 'installed' / self.relative).read_bytes(), self.payload)
        self.assertEqual((self.profiles / self.absolute).read_bytes(), self.payload)
        with zipfile.ZipFile(self.archive) as z:
            self.assertFalse(any('Owner Folder' in n for n in z.namelist()))

    def test_corrupt_file_rejected_before_creating_destination(self):
        self.pack()
        self.rewrite(lambda d: d.__setitem__('profiles/' + self.relative, self.payload + b'x'))
        with self.assertRaisesRegex(ValueError, 'checksum|size'):
            self.install()
        self.assertFalse((self.root / 'installed').exists())

    def test_wrong_compiler_rejected(self):
        self.pack()
        with self.assertRaisesRegex(ValueError, 'compiler'):
            self.install('15.2.0')

    def test_nonempty_destination_is_preserved(self):
        self.pack()
        target = self.root / 'installed'
        target.mkdir()
        (target / 'mine.gcda').write_bytes(b'mine')
        with self.assertRaisesRegex(ValueError, 'exists|empty'):
            self.install()
        self.assertEqual((target / 'mine.gcda').read_bytes(), b'mine')

    def test_path_escape_and_extra_member_rejected(self):
        self.pack()
        self.rewrite(lambda d: d.__setitem__('profiles/../../escape.gcda', self.payload))
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse((self.root / 'escape.gcda').exists())

    def test_duplicate_zip_member_rejected(self):
        self.pack()
        with zipfile.ZipFile(self.archive, 'a') as z:
            z.writestr('profiles/' + self.relative, self.payload)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.install()

    def test_invalid_gcda_rejected(self):
        (self.profiles / self.relative).write_bytes(b'not a profile')
        with self.assertRaisesRegex(ValueError, 'GCDA|gcda'):
            self.pack()

    def test_codegen_layout_is_installed_and_old_layout_backed_up(self):
        self.pack()
        self.install()
        repo = self.root / 'target_repo'
        target = repo / 'app/generated/default/codegen.partition.json'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'old layout')
        result = bundle.prepare_codegen(self.root / 'installed', repo)
        self.assertEqual(target.read_bytes(), self.layout.read_bytes())
        self.assertEqual(Path(result['backup']).read_bytes(), b'old layout')

    def test_invalid_layout_rejected(self):
        self.layout.write_text(json.dumps({'version': 2, 'file_count': 1, 'max_file_bytes': 1048576,
                                          'assignments': {'83391DE0': 4}}))
        with self.assertRaisesRegex(ValueError, 'partition|layout'):
            self.pack()

    def test_failed_layout_preparation_preserves_profiles_and_can_resume(self):
        self.pack()
        repo = self.root / 'blocked_repo'
        repo.mkdir()
        (repo / 'app').write_bytes(b'old user file')
        destination = self.root / 'installed'
        with self.assertRaisesRegex(ValueError, 'prepare-codegen'):
            bundle.install_for_repo(self.archive, destination, repo, '16.1.0')
        self.assertEqual((destination / self.relative).read_bytes(), self.payload)
        self.assertEqual((repo / 'app').read_bytes(), b'old user file')
        (repo / 'app').unlink()
        bundle.prepare_codegen(destination, repo)
        self.assertEqual((repo / 'app/generated/default/codegen.partition.json').read_bytes(),
                         self.layout.read_bytes())

    def test_source_check_allows_docs_but_rejects_changed_build_inputs(self):
        import subprocess
        repo = self.root / 'repo'
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-c', 'user.name=Test', '-c',
                                            'user.email=test@example.invalid', *args], cwd=repo)
        git('init', '-q')
        (repo / 'app').mkdir()
        (repo / 'app/input.txt').write_text('original')
        git('add', '.')
        git('commit', '-qm', 'baseline')
        revision = git('rev-parse', 'HEAD').decode().strip()
        (repo / 'README.md').write_text('new docs')
        bundle.check_sources(repo, revision)
        (repo / 'app/input.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'source|input'):
            bundle.check_sources(repo, revision)

    def test_release_and_forwarder_tools_do_not_invalidate_game_profiles(self):
        import subprocess
        repo = self.root/'source-repo'
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git','-C',str(repo),'-c','user.name=test',
                                            '-c','user.email=test@example.invalid',*args])
        git('init','-q')
        (repo/'tools').mkdir()
        (repo/'tools/post_codegen.py').write_text('original game-code preparation')
        git('add','.'); git('commit','--no-gpg-sign','-qm','baseline')
        revision = git('rev-parse','HEAD').decode().strip()
        for name in ('tools/forwarder.py','tools/release_bundle.py','tools/extract_iso.py','tools/win/package_switch.ps1',
                     'tools/win/build_forwarder.ps1','tools/win/build_forwarder_probe.ps1',
                     'tools/switch/forwarder_icon_probe.c'):
            path = repo/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('packaging only')
        git('add','.'); git('commit','--no-gpg-sign','-qm','release tools')
        try:
            bundle.check_sources(repo,revision)
        except ValueError as error:
            self.fail('packaging tools incorrectly invalidate game profiles: '+str(error))
        (repo/'tools/post_codegen.py').write_text('changed generated game code')
        with self.assertRaisesRegex(ValueError,'source inputs differ'):
            bundle.check_sources(repo,revision)


if __name__ == '__main__':
    unittest.main()
