#!/usr/bin/env python3
"""Uploads files to the Switch over FTP (the same server tools/switch_logs.py reads).

  python tools/switch_upload.py out/nx/ds2.nro app/ds2_switch.toml=ds2.toml [--remote /switch/ds2scholar-nx]

Each argument is LOCAL[=REMOTE_NAME]. A file is written as NAME.upload.tmp, its size checked, then renamed over NAME, so an
interrupted transfer never leaves a truncated NRO. With --backup the replaced file is first downloaded to
out/switch_upload/backup/. Run from PowerShell: Git Bash rewrites /switch/... arguments into Windows paths.
"""
import argparse
import ftplib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def remote_size(ftp, name):
    try:
        return ftp.size(name)
    except ftplib.error_perm:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='+', help='LOCAL[=REMOTE_NAME]')
    ap.add_argument('--host', default='192.168.1.76')
    ap.add_argument('--port', type=int, default=5000)
    ap.add_argument('--remote', default='/switch/ds2scholar-nx')
    ap.add_argument('--backup', action='store_true', help='download each replaced file to out/switch_upload/backup/')
    a = ap.parse_args()

    pairs = []
    for spec in a.files:
        local, sep, name = spec.partition('=')
        name = name or os.path.basename(local)
        if not os.path.isfile(local):
            sys.exit(f'no such file: {local}')
        pairs.append((local, name))

    ftp = ftplib.FTP()
    ftp.connect(a.host, a.port, timeout=180)
    ftp.login()
    ftp.cwd(a.remote)
    ftp.voidcmd('TYPE I')
    for local, name in pairs:
        size = os.path.getsize(local)
        exists = remote_size(ftp, name) is not None  # this server's NLST returns no names
        if a.backup and exists:
            os.makedirs(os.path.join(ROOT, 'out', 'switch_upload', 'backup'), exist_ok=True)
            with open(os.path.join(ROOT, 'out', 'switch_upload', 'backup', name), 'wb') as out:
                ftp.retrbinary('RETR ' + name, out.write, blocksize=64 * 1024)
            print(f'backed up {a.remote}/{name}')
        part = name + '.upload.tmp'
        try:
            ftp.delete(part)
        except Exception:
            pass
        sent = 0
        last_pct = 0
        def on_chunk(chunk):
            nonlocal sent, last_pct
            sent += len(chunk)
            pct = int(sent * 100 / size)
            if pct >= last_pct + 10 or sent == size:
                last_pct = pct
                print(f'  uploading {name}: {sent // (1024*1024)}/{size // (1024*1024)} MB ({pct}%)', flush=True)

        with open(local, 'rb') as src:
            ftp.storbinary('STOR ' + part, src, blocksize=64 * 1024, callback=on_chunk)
        got = remote_size(ftp, part)
        if got != size:
            sys.exit(f'{part}: {got} bytes on the console, {size} locally - left as .upload.tmp')
        if exists:
            try:
                ftp.delete(name)
            except Exception as e:
                print(f'warning: failed to delete existing {name} ({e}), trying rename anyway', flush=True)
        ftp.rename(part, name)
        print(f'{local} -> {a.remote}/{name} ({size} bytes)')
    ftp.quit()


if __name__ == '__main__':
    main()
