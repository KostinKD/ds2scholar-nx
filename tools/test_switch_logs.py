"""Regression checks for content changes, incomplete transfers and nested FTP logs."""
from pathlib import Path
import tempfile
import unittest

import switch_logs


class FakeFTP:
    def __init__(self, data=b'first', fail=False):
        self.data = data
        self.fail = fail
        self.directory = '/logs'

    def retrbinary(self, command, callback):
        callback(self.data)
        if self.fail:
            raise EOFError('Connection lost')

    def pwd(self):
        return self.directory

    def cwd(self, directory):
        self.directory = directory if directory.startswith('/') else self.directory + '/' + directory

    def mlsd(self):
        if self.directory == '/logs':
            return [('rex', {'type': 'dir'}), ('game.log', {'type': 'file'}),
                    ('dump.bin', {'type': 'file'}), ('..', {'type': 'pdir'})]
        return [('rex_profile.log', {'type': 'file'})]


class DownloadTests(unittest.TestCase):
    def test_changes_and_truncation_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            relative = Path('rex/rex_profile.log')
            for snapshot, data, expected in [('1', b'first', True), ('2', b'first', False),
                                              ('3', b'other', True), ('4', b'', True)]:
                self.assertEqual(switch_logs.download(FakeFTP(data), 'rex_profile.log',
                                                      relative, output, snapshot), expected)
            self.assertEqual((output / 'latest' / relative).read_bytes(), b'')
            self.assertEqual((output / 'history/1' / relative).read_bytes(), b'first')
            self.assertEqual((output / 'history/3' / relative).read_bytes(), b'other')
            self.assertFalse((output / 'history/2').exists())

    def test_interrupted_transfer_preserves_latest(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            relative = Path('game.log')
            switch_logs.download(FakeFTP(), 'game.log', relative, output, '1')
            with self.assertRaises(EOFError):
                switch_logs.download(FakeFTP(b'partial', fail=True), 'game.log', relative, output, '2')
            self.assertEqual((output / 'latest' / relative).read_bytes(), b'first')
            self.assertFalse((output / 'history/2').exists())
            self.assertEqual(list((output / 'latest').glob('.download-*')), [])

    def test_nested_listing_restores_directory(self):
        ftp = FakeFTP()
        self.assertEqual([path.as_posix() for path, _ in switch_logs.log_files(ftp)],
                         ['game.log', 'rex/rex_profile.log'])
        self.assertEqual(ftp.pwd(), '/logs')

    def test_remote_path_escape_rejected(self):
        for name in ('../escape.log', '/absolute.log', 'C:bad.log', 'NUL.log', 'a\\b.log', 'bad\r\nRETR'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                switch_logs.safe_name(name)


if __name__ == '__main__':
    unittest.main()
