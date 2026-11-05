import importlib.util
from pathlib import Path
import unittest
import tempfile
import subprocess
import sys

spec = importlib.util.spec_from_file_location('pgo_fit', Path(__file__).resolve().parents[1] / 'pgo_fit.py')
fit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fit)


class PgoFitTests(unittest.TestCase):
    def test_legacy_add_accepts_flag_starting_with_dash(self):
        result = subprocess.run([sys.executable, str(Path(spec.origin)), '--add', '-DREX_TEST=1', '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ninja_parser_skips_pch_and_unescapes_source_spaces(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            (build / 'build.ninja').write_text(
                'build CMakeFiles/test.dir/pch.gch: CXX_COMPILER__test x/pch.cxx\n'
                '  FLAGS = -fprofile-use=G:/pgo\n\n'
                'build CMakeFiles/test.dir/source.cpp.obj: CXX_COMPILER__test G$:/Other$ Folder/source.cpp || deps\n'
                '  FLAGS = -fprofile-use=G:/pgo\n\n')
            result = fit.statements(build)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0][1], 'G:/Other Folder/source.cpp')

    def test_windows_quotes_and_backslashes_preserved(self):
        text = r'-DREXGLUE_BUILD_CONFIG=\"Release\" "-IG:/Other Folder/sdk" -fprofile-use=G:\repo\pgo'
        self.assertEqual(fit.compiler_tokens(text), ['-DREXGLUE_BUILD_CONFIG="Release"',
                         '-IG:/Other Folder/sdk', r'-fprofile-use=G:\repo\pgo'])

    def test_missing_function_is_not_missing_file(self):
        diagnostics = "x.cpp: warning: profile for function 'void sub_12345678()' not found in profile data [-Wmissing-profile]"
        report = fit.profile_diagnostics(diagnostics)
        self.assertFalse(report['missing_file'])
        self.assertEqual(report['absent'], 1)
        self.assertEqual(report['guest_absent'], 1)

    def test_missing_file_is_failure(self):
        report = fit.profile_diagnostics("x.cpp: warning: 'x.gcda' profile count data file not found [-Wmissing-profile]")
        self.assertTrue(report['missing_file'])

    def test_source_location_warning_is_separate_from_cfg_loss(self):
        report = fit.profile_diagnostics("x: warning: source locations for function 'foo' have changed [-Wcoverage-mismatch]\n"
                                         "x: warning: number of counters in profile data for function 'bar' does not match [-Wcoverage-mismatch]")
        self.assertEqual(report['moved_lines'], 1)
        self.assertEqual(report['lost'], 1)
        self.assertFalse(report['missing_file'])

    def test_helper_loss_is_separate_from_guest_loss(self):
        report = fit.profile_diagnostics("x: warning: profile for function 'void helper()' not found in profile data [-Wmissing-profile]\n"
                                         "x: warning: the control flow of function 'void __imp__sub_12345678()' does not match its profile data [-Wcoverage-mismatch]")
        self.assertEqual(report['absent'], 1)
        self.assertEqual(report['guest_absent'], 0)
        self.assertEqual(report['guest_lost'], 1)

    def test_guest_symbol_in_template_argument_is_not_guest_function(self):
        report = fit.profile_diagnostics("x: warning: profile for function 'void {anonymous}::Draw(PPCContext&, uint8_t*) [with void (* Original)(PPCContext&, uint8_t*) = __imp__sub_829F29C8]' not found in profile data [-Wmissing-profile]")
        self.assertEqual(report['absent'], 1)
        self.assertEqual(report['guest_absent'], 0)


if __name__ == '__main__':
    unittest.main()
