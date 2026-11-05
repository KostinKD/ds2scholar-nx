#!/usr/bin/env python3
"""Pack/install SotFS GCDA counts with hashes and relocatable CMake object names.

The ZIP is a separate build input, never game files or generated game code.
Run --help for commands. Existing profile folders are never overwritten.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOKEN = '@REPO@'
SOURCE_PATHS = ['app', 'sdk', 'tools', ':(exclude)tools/pgo_bundle.py',
                ':(exclude)tools/pgo_fit.py', ':(exclude)tools/rebuild_switch.py',
                ':(exclude)tools/win/rebuild_switch.ps1', ':(exclude)tools/tests',
                # Release/probe programs do not participate in the game's GCC build.
                ':(exclude)tools/forwarder.py', ':(exclude)tools/release_bundle.py',
                ':(exclude)tools/extract_iso.py',
                ':(exclude)tools/win/package_switch.ps1', ':(exclude)tools/win/build_forwarder.ps1',
                ':(exclude)tools/win/build_forwarder_probe.ps1', ':(exclude)tools/switch/forwarder_icon_probe.c']


def check_sources(repo, revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('invalid source revision')
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo, stderr=subprocess.PIPE).decode().strip()
    try:
        git('cat-file', '-e', revision + '^{commit}')
        changed = git('diff', '--name-only', '--no-ext-diff', revision, '--', *SOURCE_PATHS)
        # Also permit an identical file present but not yet tracked by an older clone.
        for name in changed.splitlines():
            if not (Path(repo) / name).is_file() or git('hash-object', '--path', name, name) != git(
                    'rev-parse', revision + ':' + name):
                raise ValueError('source inputs differ from profile revision: ' + name)
    except subprocess.CalledProcessError as exc:
        raise ValueError('cannot verify source revision; fetch the matching project commit') from exc


def encoded_root(repo):
    # CMake object names for absolute Windows source paths, as emitted by GCC.
    path = PureWindowsPath(str(repo))
    if not path.drive or path.drive.startswith('\\') or not path.is_absolute():
        raise ValueError('profile relocation currently supports absolute Windows drive paths')
    return '#'.join([path.drive.replace(':', '_'), *path.parts[1:]])


def validate_name(name):
    if (not name.startswith('CMakeFiles#') or not name.endswith('.gcda') or
            any(c in name for c in '/\\:\0') or '..' in name):
        raise ValueError('invalid GCDA object name: ' + name)


def validate_data(data, compiler):
    if compiler != '16.1.0':
        raise ValueError('this profile format requires compiler GCC 16.1.0')
    if len(data) < 16 or data[:8] != b'adcg*16B':
        raise ValueError('invalid GCDA header/version for GCC 16.1.0')


def validate_layout(data):
    layout = json.loads(data)
    if (not isinstance(layout, dict) or layout.get('version') != 2 or
            type(layout.get('file_count')) is not int or layout['file_count'] < 1 or
            type(layout.get('max_file_bytes')) is not int or layout['max_file_bytes'] < 1 or
            not isinstance(layout.get('assignments'), dict) or not layout['assignments']):
        raise ValueError('invalid codegen partition layout')
    for address, index in layout['assignments'].items():
        if (not re.fullmatch(r'[0-9A-F]{8}', address) or type(index) is not int or
                not 0 <= index < layout['file_count']):
            raise ValueError('invalid codegen partition assignment')


def pack(profile_dir, output, repo, revision, compiler, layout_path):
    profile_dir, output = Path(profile_dir), Path(output)
    if output.exists():
        raise ValueError('output already exists: ' + str(output))
    entries = {}
    prefix = 'CMakeFiles#ds2.dir#' + encoded_root(repo) + '#'
    for path in sorted(profile_dir.glob('*.gcda')):
        name = path.name
        validate_name(name)
        if TOKEN in name:
            raise ValueError('input already contains relocation token')
        if name.startswith(prefix):
            name = name.replace(prefix, 'CMakeFiles#ds2.dir#' + TOKEN + '#', 1)
        elif re.match(r'CMakeFiles#[^#]+#[A-Za-z]_#', name):
            raise ValueError('profile contains an absolute path from another repository: ' + name)
        data = path.read_bytes()
        validate_data(data, compiler)
        if name in entries:
            raise ValueError('duplicate portable profile name')
        entries[name] = data
    if not entries:
        raise ValueError('no GCDA profiles found')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('invalid source revision')
    layout_data = Path(layout_path).read_bytes()
    validate_layout(layout_data)
    manifest = {'schema': 2, 'profile': 'sotfs-v4', 'compiler': compiler,
                'source_revision': revision,
                'layout': {'size': len(layout_data), 'sha256': hashlib.sha256(layout_data).hexdigest()},
                'files': {n: {'size': len(d), 'sha256': hashlib.sha256(d).hexdigest()}
                          for n, d in entries.items()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        # Fixed timestamps make identical input packages byte-for-byte reproducible.
        for name, data in [('manifest.json', json.dumps(manifest, indent=2).encode() + b'\n'),
                           ('codegen.partition.json', layout_data),
                           *[('profiles/' + n, d) for n, d in entries.items()]]:
            info = zipfile.ZipInfo(name, (2026, 10, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return manifest


def install(archive, destination, repo, compiler):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('destination already exists; preserve or move your old profile first')
    entries, relocated = {}, 0
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate ZIP member')
        manifest = json.loads(z.read('manifest.json'))
        if not isinstance(manifest, dict) or manifest.get('schema') != 2 or manifest.get('compiler') != compiler:
            raise ValueError('profile schema/compiler mismatch')
        files = manifest.get('files')
        if not isinstance(files, dict) or not files:
            raise ValueError('empty or invalid profile manifest')
        if set(names) != {'manifest.json', 'codegen.partition.json', *('profiles/' + n for n in files)}:
            raise ValueError('unexpected ZIP member')
        layout_data = z.read('codegen.partition.json')
        layout_meta = manifest['layout']
        if (len(layout_data) != layout_meta['size'] or
                hashlib.sha256(layout_data).hexdigest() != layout_meta['sha256']):
            raise ValueError('codegen layout size/checksum mismatch')
        validate_layout(layout_data)
        for name, meta in files.items():
            validate_name(name)
            data = z.read('profiles/' + name)
            if len(data) != meta['size'] or hashlib.sha256(data).hexdigest() != meta['sha256']:
                raise ValueError('profile size/checksum mismatch: ' + name)
            validate_data(data, compiler)
            if TOKEN in name:
                if not name.startswith('CMakeFiles#ds2.dir#' + TOKEN + '#') or name.count(TOKEN) != 1:
                    raise ValueError('invalid relocation token')
                name = name.replace(TOKEN, encoded_root(repo))
                relocated += 1
            elif re.match(r'CMakeFiles#[^#]+#[A-Za-z]_#', name):
                raise ValueError('nonportable absolute GCDA path')
            validate_name(name)
            if name in entries:
                raise ValueError('duplicate relocated profile name')
            entries[name] = data
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pgo-install-', dir=destination.parent) as temp:
        staged = Path(temp) / 'profile'
        staged.mkdir()
        for name, data in entries.items():
            (staged / name).write_bytes(data)
        (staged / 'codegen.partition.json').write_bytes(layout_data)
        (staged / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        staged.rename(destination)
    return {'files': len(entries), 'relocated': relocated,
            'bytes': sum(map(len, entries.values())), 'source_revision': manifest['source_revision']}


def prepare_codegen(profiles, repo):
    profiles, repo = Path(profiles), Path(repo)
    manifest = json.loads((profiles / 'manifest.json').read_text(encoding='utf-8'))
    data = (profiles / 'codegen.partition.json').read_bytes()
    if (len(data) != manifest['layout']['size'] or
            hashlib.sha256(data).hexdigest() != manifest['layout']['sha256']):
        raise ValueError('installed codegen layout checksum mismatch')
    validate_layout(data)
    target = repo / 'app/generated/default/codegen.partition.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists() and target.read_bytes() != data:
        folder = repo / 'out/pgo-layout-backups'
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='codegen.partition-', suffix='.json', dir=folder, delete=False) as f:
            f.write(target.read_bytes())
            backup = f.name
    with tempfile.NamedTemporaryFile(prefix='partition-', dir=target.parent, delete=False) as f:
        f.write(data)
        temporary = Path(f.name)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'layout': str(target), 'backup': backup, 'codegen_required': True}


def install_for_repo(archive, destination, repo, compiler):
    result = install(archive, destination, Path(repo).resolve(), compiler)
    try:
        result.update(prepare_codegen(destination, repo))
    except (OSError, ValueError) as exc:
        raise ValueError(f'Profiles installed in {destination}, but layout preparation failed: {exc}. '
                         f'After fixing the cause, run pgo_bundle.py --repo "{repo}" '
                         f'prepare-codegen --profiles "{destination}"') from exc
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--compiler', type=Path, help='devkitA64 g++.exe (default: DEVKITPRO or G:/devkitPro)')
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('pack')
    export.add_argument('--profiles', type=Path, default=ROOT / 'pgo')
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--source-revision', required=True)
    export.add_argument('--layout', type=Path, default=ROOT / 'app/generated/default/codegen.partition.json')
    load = commands.add_parser('install')
    load.add_argument('archive', type=Path)
    load.add_argument('--destination', type=Path, help='default: <repo>/pgo')
    seed = commands.add_parser('prepare-codegen', help='restore installed layout before regenerating code')
    seed.add_argument('--profiles', type=Path, help='default: <repo>/pgo')
    args = parser.parse_args()
    compiler = args.compiler or Path(os.environ.get('DEVKITPRO', 'G:/devkitPro')) / 'devkitA64/bin/aarch64-none-elf-g++.exe'
    try:
        version = subprocess.check_output([str(compiler), '-dumpfullversion'], text=True).strip()
        if args.command == 'pack':
            revision = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options',
                                                args.source_revision + '^{commit}'], cwd=args.repo, text=True).strip()
            check_sources(args.repo, revision)
            result = pack(args.profiles, args.output, args.repo.resolve(), revision, version, args.layout)
            result = {k: v for k, v in result.items() if k != 'files'} | {'files': len(result['files'])}
        elif args.command == 'install':
            with zipfile.ZipFile(args.archive) as z:
                revision = json.loads(z.read('manifest.json'))['source_revision']
            check_sources(args.repo, revision)
            destination = args.destination or args.repo / 'pgo'
            result = install_for_repo(args.archive, destination, args.repo, version)
        else:
            profiles = args.profiles or args.repo / 'pgo'
            manifest = json.loads((profiles / 'manifest.json').read_text(encoding='utf-8'))
            if manifest['compiler'] != version:
                raise ValueError('profile compiler mismatch')
            check_sources(args.repo, manifest['source_revision'])
            result = prepare_codegen(profiles, args.repo)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
