import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import subprocess

spec = importlib.util.spec_from_file_location('rebuild_switch', Path(__file__).resolve().parents[1] / 'rebuild_switch.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['assets/game_root/default.xex', 'app/ds2_manifest.toml',
                     'app/generated/rexglue.cmake', 'app/generated/default/codegen.partition.json',
                     'tools/codegen.ps1', 'tools/check_switch_build.py',
                     'out/fake-sdk/lib/libvulkan.a', 'out/nx_pgo/CMakeCache.txt']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'input')
        self.guest = 'CMakeFiles#ds2_recomp.dir#generated#default#ds2_recomp.0.cpp.gcda'
        self.init = 'CMakeFiles#ds2_recomp.dir#generated#default#ds2_init.cpp.gcda'
        (self.root / 'pgo').mkdir()
        for name in (self.guest, self.init):
            (self.root / 'pgo' / name).write_bytes(b'adcg*16B' + bytes(8))
        (self.root / 'app/generated/default/codegen.partition.json').write_text(json.dumps(
            {'version': 2, 'file_count': 1, 'max_file_bytes': 1048576, 'assignments': {'83391DE0': 0}}))
        self.build = self.root / 'out/nx_pgo'
        patch = mock.patch.dict(driver.os.environ, {'NVK_SDK': str(self.root / 'out/fake-sdk')})
        patch.start()
        self.addCleanup(patch.stop)

    def stamp(self, plan):
        (self.build / 'rebuild-state.json').write_text(json.dumps(
            {'profile': plan['profile'], 'codegen': plan['codegen'], 'validated': True,
             'rules': driver.rules_signature(self.build), 'guest_objects': driver.object_signature(self.build)}))

    def test_first_build_is_safe_and_incremental_repeat_skips_prepare_and_clean(self):
        first = driver.make_plan(self.root, self.build, self.root / 'pgo')
        self.assertTrue(first['regenerate'])
        self.assertTrue(first['clean'])
        self.stamp(first)
        before = set(self.root.rglob('*'))
        second = driver.make_plan(self.root, self.build, self.root / 'pgo')
        self.assertFalse(second['regenerate'])
        self.assertFalse(second['clean'])
        self.assertEqual(before, set(self.root.rglob('*')))

    def test_changed_profile_requires_clean_without_regenerating_guest_code(self):
        self.stamp(driver.make_plan(self.root, self.build, self.root / 'pgo'))
        (self.root / 'pgo' / self.guest).write_bytes(b'adcg*16B' + bytes(8) + b'changed counts')
        plan = driver.make_plan(self.root, self.build, self.root / 'pgo')
        self.assertTrue(plan['clean'])
        self.assertFalse(plan['regenerate'])

    def test_changed_codegen_input_regenerates(self):
        self.stamp(driver.make_plan(self.root, self.build, self.root / 'pgo'))
        (self.root / 'app/ds2_manifest.toml').write_bytes(b'new manifest')
        self.assertTrue(driver.make_plan(self.root, self.build, self.root / 'pgo')['regenerate'])

    def test_missing_profile_fails_and_never_selects_no_pgo(self):
        for path in (self.root / 'pgo').glob('*.gcda'):
            path.unlink()
        with self.assertRaisesRegex(ValueError, 'PGO'):
            driver.make_plan(self.root, self.build, self.root / 'pgo')

    def test_build_directory_must_be_a_child_of_out(self):
        with self.assertRaisesRegex(ValueError, 'out'):
            driver.make_plan(self.root, self.root / 'app', self.root / 'pgo')

    def test_runtime_config_change_does_not_trigger_codegen(self):
        (self.root / 'app/ds2_switch.toml').write_bytes(b'30fps')
        self.stamp(driver.make_plan(self.root, self.build, self.root / 'pgo'))
        (self.root / 'app/ds2_switch.toml').write_bytes(b'uncapped')
        self.assertFalse(driver.make_plan(self.root, self.build, self.root / 'pgo')['regenerate'])

    def test_only_sdk_profile_cannot_hide_missing_guest_profiles(self):
        (self.root / 'pgo' / self.guest).unlink()
        (self.root / 'pgo/sdk.gcda').write_bytes(b'adcg*16B' + bytes(8))
        with self.assertRaisesRegex(ValueError, 'guest PGO'):
            driver.make_plan(self.root, self.build, self.root / 'pgo')

    def test_keep_volatile_hook_and_xex_loader_changes_invalidate_codegen(self):
        for name in ['tools/keep_volatile.py', 'app/src/new_hook.cpp', 'sdk/src/system/xex_loader.cpp']:
            with self.subTest(name=name):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('old')
                self.stamp(driver.make_plan(self.root, self.build, self.root / 'pgo'))
                path.write_text('new hook or generator input')
                self.assertTrue(driver.make_plan(self.root, self.build, self.root / 'pgo')['regenerate'])

    def test_old_unvalidated_stamp_requires_real_profile_check(self):
        plan = driver.make_plan(self.root, self.build, self.root / 'pgo')
        (self.build / 'rebuild-state.json').write_text(json.dumps(
            {'profile': plan['profile'], 'codegen': plan['codegen']}))
        self.assertTrue(driver.make_plan(self.root, self.build, self.root / 'pgo')['validate_profile'])

    def test_cold_pipeline_invalidates_raw_stamp_and_validates_before_success_stamp(self):
        stamp = self.root / 'app/generated/default/codegen.stamp'
        stamp.write_text('cached raw output')
        (self.build / 'ds2.nro').write_bytes(b'old artifact')
        steps = []
        def child(root, name, args):
            steps.append(name)
            if name == 'Switch PGO use + LTO':
                (self.build / 'ds2').write_bytes(b'checked elf')
            if name == 'verify ELF/NRO':
                (self.build / 'ds2.nro').write_bytes(b'new checked artifact')
        with mock.patch.object(driver, 'run', side_effect=child), \
                mock.patch.object(driver.subprocess, 'check_output', return_value='16.1.0'), \
                mock.patch('builtins.print'):
            driver.execute(self.root, self.build, self.root / 'pgo', 5)
        self.assertFalse(stamp.exists())
        self.assertLess(steps.index('verify actual guest PGO use'), steps.index('verify ELF/NRO'))
        self.assertTrue(json.loads((self.build / 'rebuild-state.json').read_text())['validated'])
        self.assertEqual(next((self.root / 'out/rebuild-backups').rglob('ds2.nro')).read_bytes(), b'old artifact')

    def test_identical_verified_artifacts_reuse_binary_check(self):
        (self.build / 'ds2').write_bytes(b'elf')
        (self.build / 'ds2.nro').write_bytes(b'nro')
        state = driver.make_plan(self.root, self.build, self.root / 'pgo')
        self.stamp(state)
        stored = json.loads((self.build / 'rebuild-state.json').read_text())
        stored['artifacts'] = driver.binary_check_signature(self.root, self.build, self.root / 'out/fake-sdk')
        (self.build / 'rebuild-state.json').write_text(json.dumps(stored))
        steps = []
        with mock.patch.object(driver, 'run', side_effect=lambda root, name, argv: steps.append(name)), \
                mock.patch.object(driver.subprocess, 'check_output', return_value='16.1.0'), \
                mock.patch('builtins.print'):
            driver.execute(self.root, self.build, self.root / 'pgo', 5)
        self.assertNotIn('verify ELF/NRO', steps)
        self.assertNotIn('verify actual guest PGO use', steps)
        (self.root / 'tools/check_switch_build.py').write_bytes(b'new verification policy')
        steps.clear()
        with mock.patch.object(driver, 'run', side_effect=lambda root, name, argv: steps.append(name)), \
                mock.patch.object(driver.subprocess, 'check_output', return_value='16.1.0'), \
                mock.patch('builtins.print'):
            driver.execute(self.root, self.build, self.root / 'pgo', 5)
        self.assertIn('verify ELF/NRO', steps)

    def test_failed_profile_gate_never_marks_build_validated(self):
        steps = []
        def child(root, name, args):
            steps.append(name)
            if name == 'verify actual guest PGO use':
                raise subprocess.CalledProcessError(1, args)
        with mock.patch.object(driver, 'run', side_effect=child), \
                mock.patch.object(driver.subprocess, 'check_output', return_value='16.1.0'), \
                mock.patch('builtins.print'):
            with self.assertRaises(subprocess.CalledProcessError):
                driver.execute(self.root, self.build, self.root / 'pgo', 5)
        self.assertFalse(json.loads((self.build / 'rebuild-state.json').read_text())['validated'])
        self.assertNotIn('verify ELF/NRO', steps)
        self.assertFalse((self.build / 'rebuild.lock').exists())

    def test_matching_cache_avoids_forced_reconfigure(self):
        (self.build / 'CMakeCache.txt').write_text('DS2_PGO:STRING=use\nDS2_SWITCH_LTO:BOOL=ON\n'
            'DS2_SWITCH_LTO_JOBS:STRING=5\nDEVKITPRO:PATH=G:/devkitPro\nREXGLUE_SWITCH_NVK_SDK:PATH=G:/nvk\n'
            'CMAKE_BUILD_TYPE:STRING=Release\nDS2_PGO_DIR:PATH=' + str(self.root / 'pgo') + '\n')
        with mock.patch.dict(driver.os.environ, {'DEVKITPRO': 'G:/devkitPro', 'NVK_SDK': 'G:/nvk'}):
            self.assertFalse(driver.needs_configure(self.build, self.root / 'pgo'))
            self.assertTrue(driver.needs_configure(self.build, self.root / 'pgo', 1))
            with mock.patch.dict(driver.os.environ, {'NVK_SDK': 'G:/different_nvk'}):
                self.assertTrue(driver.needs_configure(self.build, self.root / 'pgo'))
        (self.build / 'CMakeCache.txt').write_text('DS2_PGO:STRING=\nDS2_SWITCH_LTO:BOOL=OFF\n')
        self.assertTrue(driver.needs_configure(self.build, self.root / 'pgo'))

    def test_changed_build_rules_invalidate_profile_validation(self):
        plan = driver.make_plan(self.root, self.build, self.root / 'pgo')
        self.stamp(plan)
        (self.build / 'build.ninja').write_text('new compiler flags')
        self.assertTrue(driver.make_plan(self.root, self.build, self.root / 'pgo')['validate_profile'])

    def test_recompiled_guest_object_invalidates_profile_validation(self):
        self.stamp(driver.make_plan(self.root, self.build, self.root / 'pgo'))
        obj = self.build / 'CMakeFiles/ds2_recomp.dir/generated/default/part.cpp.obj'
        obj.parent.mkdir(parents=True)
        obj.write_bytes(b'new compiler output')
        self.assertTrue(driver.make_plan(self.root, self.build, self.root / 'pgo')['validate_profile'])


if __name__ == '__main__':
    unittest.main()
