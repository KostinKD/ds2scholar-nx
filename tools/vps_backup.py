#!/usr/bin/env python3
"""Consistent DS2 server backup; never prints keys or admin credentials.

Run as a user with read access to Saved/default and write access to the backup
directory. Output files are private to that user. Existing backups are retained.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile


def backup(saved: Path, destination: Path) -> Path:
    saved = saved.resolve(strict=True)
    for name in ('database.sqlite', 'config.json', 'private.key', 'public.key'):
        if not (saved / name).is_file():
            raise ValueError(f'Missing server file: {name}')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = destination.resolve(strict=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    target = destination / f'ds2_backup_{stamp}.tar.gz'
    old_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix='ds2_backup_stage_', dir=destination) as stage_name:
            stage = Path(stage_name).resolve()
            stage.relative_to(destination)  # Cleanup is confined to our own new staging directory.
            source_uri = (saved / 'database.sqlite').as_uri() + '?mode=ro'
            with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source:
                with closing(sqlite3.connect(stage / 'database.sqlite')) as copy:
                    source.backup(copy)
                    result = copy.execute('PRAGMA integrity_check').fetchone()[0]
                    if result != 'ok':
                        raise ValueError(f'Backup integrity: {result}')
            for name in ('config.json', 'private.key', 'public.key'):
                shutil.copyfile(saved / name, stage / name)
            (stage / 'manifest.json').write_text(json.dumps(
                {'utc': stamp, 'source': str(saved), 'sqlite_integrity': result}, indent=2), encoding='utf-8')
            files = sorted(stage.iterdir())
            staged_archive = stage / 'archive.tar.gz'
            with staged_archive.open('xb') as output:
                with tarfile.open(fileobj=output, mode='w:gz') as archive:
                    for file in files:
                        archive.add(file, arcname='default/' + file.name, recursive=False)
            # Same-filesystem hard link publishes a complete archive atomically and
            # refuses to replace an existing backup. Staging cleanup removes its link.
            os.link(staged_archive, target)
            target.chmod(0o600)
    finally:
        os.umask(old_umask)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved', required=True, type=Path)
    parser.add_argument('--dest', required=True, type=Path)
    args = parser.parse_args()
    print('BACKUP_OK integrity=ok file=' + str(backup(args.saved, args.dest)))


if __name__ == '__main__':
    main()
