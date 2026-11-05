#!/usr/bin/env python3
"""Pull Switch logs over passive FTP; standard library only. See docs/switch-logs.md."""
import argparse
from datetime import datetime
import ftplib
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'out' / 'switch_logs'
CONFIG_KEYS = ('host', 'port', 'user', 'remote', 'interval', 'timeout')


def report(message):
    print(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}', flush=True)


def safe_name(name):
    """Reject remote entries that cannot safely become Windows path components."""
    if (not name or name in ('.', '..') or name.endswith((' ', '.'))
            or any(c in name for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in name)
            or name.split('.')[0].upper() in {
                'CON', 'PRN', 'AUX', 'NUL',
                *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}):
        raise ValueError(f'Unsafe remote filename: {name!r}')
    return name


def log_files(ftp, relative=Path(), depth=0):
    """Use CWD + MLSD: some Switch servers ignore path arguments to listings."""
    if depth > 8:
        raise ValueError('Remote log directory nesting exceeds 8 levels')
    entries = sorted(ftp.mlsd())
    for name, facts in entries:
        kind = facts.get('type')
        if kind in ('cdir', 'pdir') or name.startswith('._'):
            continue
        safe_name(name)
        if kind == 'dir':
            parent = ftp.pwd()
            ftp.cwd(name)
            yield from log_files(ftp, relative / name, depth + 1)
            ftp.cwd(parent)
        elif kind == 'file' and Path(name).suffix.lower() in ('.log', '.err', '.txt'):
            yield relative / name, name


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').digest()


def download(ftp, remote_name, relative, output, snapshot):
    """Only publish a completed transfer; retain every observed content change."""
    latest = output / 'latest' / relative
    latest.parent.mkdir(parents=True, exist_ok=True)
    # Refuse existing symlinks/junctions that would redirect writes outside output.
    latest.resolve().relative_to(output.resolve())
    fd, filename = tempfile.mkstemp(prefix='.download-', dir=latest.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, 'wb') as target:
            ftp.retrbinary('RETR ' + remote_name, target.write)
        if latest.is_file() and digest(temporary) == digest(latest):
            return False
        archived = output / 'history' / snapshot / relative
        archived.resolve().relative_to(output.resolve())
        archived.parent.mkdir(parents=True, exist_ok=True)
        # Each poll has a unique snapshot directory. Archive before replacing latest.
        with archived.open('xb') as target, temporary.open('rb') as source:
            shutil.copyfileobj(source, target)
        temporary.replace(latest)
        report(f'Saved {relative.as_posix()} ({latest.stat().st_size} bytes)')
        return True
    finally:
        temporary.unlink(missing_ok=True)


def collect(args):
    snapshot = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    changed = scanned = 0
    with ftplib.FTP(timeout=args.timeout) as ftp:
        ftp.connect(args.host, args.port)
        ftp.login(args.user, args.password)
        ftp.set_pasv(True)
        ftp.cwd(args.remote)
        for relative, remote_name in log_files(ftp):
            scanned += 1
            changed += download(ftp, remote_name, relative, args.output, snapshot)
    report(f'Checked {scanned} logs; saved {changed} changed files')
    return changed


def arguments():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--config', type=Path, default=DEFAULT_OUTPUT / 'connection.json')
    known, _ = pre.parse_known_args()
    parser = argparse.ArgumentParser(description=__doc__, parents=[pre])
    parser.add_argument('--host', help='Console IP address (without ftp://)')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--user', default='anonymous')
    parser.add_argument('--ask-password', action='store_true')
    parser.add_argument('--remote', default='/switch/ds2scholar-nx/logs')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--interval', type=float, default=15)
    parser.add_argument('--timeout', type=float, default=8)
    parser.add_argument('--once', action='store_true', help='Collect once and exit')
    parser.add_argument('--save-config', action='store_true', help='Save connection settings without password')
    if known.config.exists():
        try:
            settings = json.loads(known.config.read_text(encoding='utf-8'))
            parser.set_defaults(**{key: settings[key] for key in CONFIG_KEYS if key in settings})
        except (OSError, ValueError, TypeError) as error:
            parser.error(f'Cannot read config: {error}')
    args = parser.parse_args()
    if not isinstance(args.host, str) or not args.host or any(c in args.host for c in '/\\\r\n'):
        parser.error('Provide --host CONSOLE_IP (or save it with --save-config)')
    if not isinstance(args.port, int) or not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535')
    for key in ('interval', 'timeout'):
        value = getattr(args, key)
        if not isinstance(value, (int, float)) or not 0 < value < 86400:
            parser.error(f'{key} must be greater than 0 and less than 86400 seconds')
    if not isinstance(args.remote, str) or not args.remote.startswith('/') or any(c in args.remote for c in '\r\n'):
        parser.error('--remote must be an absolute FTP directory')
    if not isinstance(args.user, str) or any(c in args.user for c in '\r\n'):
        parser.error('Invalid FTP username')
    args.output = args.output.resolve()
    args.password = getpass.getpass('FTP password: ') if args.ask_password else os.environ.get('SWITCH_FTP_PASSWORD', '')
    if args.save_config:
        args.config.parent.mkdir(parents=True, exist_ok=True)
        args.config.write_text(json.dumps({key: getattr(args, key) for key in CONFIG_KEYS}, indent=2) + '\n', encoding='utf-8')
    return args


def main():
    args = arguments()
    report(f'FTP {args.host}:{args.port}{args.remote} -> {args.output}')
    report('Press Ctrl+C to stop. Console files are only read.')
    try:
        while True:
            try:
                collect(args)
            except (OSError, EOFError, ftplib.Error, ValueError) as error:
                report(f'Collection failed: {error}')
                if args.once:
                    return 1
                report(f'Will reconnect in {args.interval:g}s')
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        report('Stopped')
        return 0


if __name__ == '__main__':
    sys.exit(main())
