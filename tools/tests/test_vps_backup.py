from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vps_backup import backup


class BackupTests(unittest.TestCase):
    def test_backup_is_consistent_and_closes_database_before_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            saved, dest = root/'saved', root/'backups'
            saved.mkdir()
            with closing(sqlite3.connect(saved/'database.sqlite')) as db:
                db.execute('CREATE TABLE TestData (value INTEGER)')
                db.execute('INSERT INTO TestData VALUES (73)')
                db.commit()
            for name in ('config.json', 'private.key', 'public.key'):
                (saved/name).write_text('synthetic fixture')
            original = (saved/'database.sqlite').read_bytes()
            path = backup(saved, dest)
            self.assertTrue(path.is_file())
            self.assertEqual(list(dest.glob('ds2_backup_stage_*')), [])
            self.assertEqual((saved/'database.sqlite').read_bytes(), original)
            with tarfile.open(path) as archive:
                self.assertEqual(set(archive.getnames()), {
                    'default/config.json', 'default/database.sqlite',
                    'default/private.key', 'default/public.key', 'default/manifest.json'})
                exported = root/'exported.sqlite'
                exported.write_bytes(archive.extractfile('default/database.sqlite').read())
            with closing(sqlite3.connect(exported)) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('SELECT value FROM TestData').fetchone()[0], 73)

    def test_incomplete_source_cannot_create_backup(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            saved = root/'saved'
            saved.mkdir()
            with self.assertRaises(ValueError):
                backup(saved, root/'backups')
            self.assertFalse((root/'backups').exists())

    def test_archive_failure_never_publishes_partial_backup(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            saved, dest = root/'saved', root/'backups'
            saved.mkdir()
            with closing(sqlite3.connect(saved/'database.sqlite')) as db:
                db.execute('CREATE TABLE TestData (value INTEGER)')
                db.commit()
            for name in ('config.json', 'private.key', 'public.key'):
                (saved/name).write_text('synthetic fixture')
            with patch('vps_backup.tarfile.open', side_effect=OSError('simulated archive failure')):
                with self.assertRaises(OSError):
                    backup(saved, dest)
            self.assertEqual(list(dest.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
