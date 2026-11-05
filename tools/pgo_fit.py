#!/usr/bin/env python3
"""Check actual GCC profile use without linking an NRO.

python tools/pgo_fit.py --build-dir out/nx_pgo --all --jobs 5 --strict
python tools/pgo_fit.py --build-dir out/nx_pgo 0 40 sdk/src/ui/rex_app.cpp

Compiles with the configured Switch flags in a scratch folder, without LTO
or the precompiled header, enabling profile diagnostics. Missing GCDA files
always fail; --strict also rejects functions with missing/mismatched counts.
Source-location-only warnings are reported separately from lost CFG profiles.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
QUOTED = re.compile("['‘]([^'’]*)['’]")


def compiler_tokens(text):
    if os.name != 'nt':
        return shlex.split(text)
    # Ninja writes Windows command-line quoting, not POSIX shell quoting.
    import ctypes
    argc = ctypes.c_int()
    parse = ctypes.windll.shell32.CommandLineToArgvW
    parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = parse('compiler ' + text, ctypes.byref(argc))
    if not argv:
        raise OSError('CommandLineToArgvW failed')
    try:
        return [argv[i] for i in range(1, argc.value)]
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(argv)


def statements(build):
    result = []
    lines = (build / 'build.ninja').read_text(encoding='utf-8').splitlines()
    for i, line in enumerate(lines):
        if not line.startswith('build ') or ': CXX_COMPILER__' not in line:
            continue
        obj, command = line[6:].split(': ', 1)
        if obj.endswith('.gch'):
            continue
        source = command.split(' ', 1)[1].split(' |', 1)[0]
        parts = {}
        for following in lines[i + 1:i + 12]:
            if not following:
                break
            for key in ('DEFINES', 'FLAGS', 'INCLUDES'):
                if following.startswith('  ' + key + ' = '):
                    parts[key] = following[len(key) + 5:]
        if '-fprofile-use=' in parts.get('FLAGS', ''):
            unescape = lambda s: s.replace('$ ', ' ').replace('$:', ':').replace('$$', '$')
            result.append((unescape(obj), unescape(source), parts))
    return result


def compile_one(statement, compiler, scratch, extra):
    obj, source, parts = statement
    command = [str(compiler)]
    for key in ('DEFINES', 'INCLUDES', 'FLAGS'):
        skip = False
        for option in compiler_tokens(parts.get(key, '')):
            if skip:
                skip = False
            elif option == '-include':
                skip = True
            elif option in ('-flto', '-fno-fat-lto-objects', '-Winvalid-pch',
                            '-Wno-coverage-mismatch', '-Wno-missing-profile'):
                continue
            elif option.startswith('-fprofile-prefix-path='):
                command.append('-fprofile-prefix-path=' + str(scratch).replace('/', '\\'))
            else:
                command.append(option)
    target = scratch / obj
    target.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, LC_ALL='C', LANG='C')
    process = subprocess.run(command + extra + ['-Wcoverage-mismatch', '-Wno-error=coverage-mismatch',
                             '-Wmissing-profile', '-c', source, '-o', obj], cwd=scratch,
                             capture_output=True, text=True, errors='replace', env=env)
    target.with_suffix('.warnings.txt').write_text(process.stderr, encoding='utf-8')
    functions = len(re.findall(r'^DEFINE_REX_FUNC\((sub_[0-9A-F]{8}|xstart)\)',
                              Path(source).read_text(encoding='utf-8'), re.M))
    result = {'object': obj, 'guest_functions': functions, 'exit_code': process.returncode,
              **profile_diagnostics(process.stderr)}
    print(json.dumps(result), flush=True)
    if process.returncode:
        print(process.stderr[-3000:], flush=True)
    return result


def profile_diagnostics(stderr):
    lost, absent, moved = set(), set(), set()
    other_mismatches = []
    for line in stderr.splitlines():
        if 'warning:' not in line:
            continue
        match = QUOTED.search(line.split('warning:', 1)[1])
        name = match.group(1) if match else line
        if 'source locations' in line:
            moved.add(name)
        elif 'control flow' in line or 'number of counters' in line:
            lost.add(name)
        elif 'not found in profile data' in line:
            absent.add(name)
        elif '-Wcoverage-mismatch' in line:
            other_mismatches.append(line)
    moved -= lost
    return {'missing_file': 'profile count data file not found' in stderr,
            'lost': len(lost), 'absent': len(absent), 'moved_lines': len(moved),
            'guest_lost': sum(bool(re.search(r'\b(?:__imp__)?(?:sub_[0-9A-F]{8}|xstart)\s*\(', n)) for n in lost),
            'guest_absent': sum(bool(re.search(r'\b(?:__imp__)?(?:sub_[0-9A-F]{8}|xstart)\s*\(', n)) for n in absent),
            'other_mismatches': len(other_mismatches)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'out/nx')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--jobs', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--strict-guest', action='store_true', help='fail on lost/new guest profiles; report helper losses separately')
    parser.add_argument('--add', action='append', default=[])
    parser.add_argument('sources', nargs='*', help='generated file numbers or source path suffixes')
    argv = sys.argv[1:]
    # Preserve the original tool's '--add -DNAME=VALUE' interface.
    i = 0
    while i < len(argv):
        if argv[i] == '--add' and i + 1 < len(argv):
            argv[i:i + 2] = ['--add=' + argv[i + 1]]
        i += 1
    args = parser.parse_args(argv)
    build = args.build_dir.resolve()
    available = statements(build)
    if not available:
        parser.error('build tree has no DS2_PGO=use compile statements')
    selected = available if args.all else []
    for wanted in args.sources:
        suffix = 'generated/default/ds2_recomp.' + wanted + '.cpp' if wanted.isdecimal() else wanted.replace('\\', '/')
        found = [s for s in available if s[1].replace('\\', '/').endswith('/' + suffix)]
        if len(found) != 1:
            parser.error('expected one configured PGO source: ' + wanted)
        if found[0] not in selected:
            selected.append(found[0])
    if not selected:
        parser.error('specify file numbers/source suffixes or --all')
    scratch = ROOT / 'out/pgo_fit' / build.name
    compiler = Path(os.environ.get('DEVKITPRO', 'G:/devkitPro')) / 'devkitA64/bin/aarch64-none-elf-g++.exe'
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda s: compile_one(s, compiler, scratch, args.add), selected))
    totals = {key: sum(r[key] for r in results) for key in
              ('guest_functions', 'lost', 'absent', 'guest_lost', 'guest_absent', 'moved_lines', 'other_mismatches')}
    totals.update(objects=len(results), compile_failures=sum(r['exit_code'] != 0 for r in results),
                  missing_files=sum(r['missing_file'] for r in results))
    (scratch / 'report.json').write_text(json.dumps({'totals': totals, 'objects': results}, indent=2), encoding='utf-8')
    print('TOTAL: ' + json.dumps(totals))
    failed = totals['compile_failures'] or totals['missing_files']
    if args.strict:
        failed = failed or totals['lost'] or totals['absent'] or totals['other_mismatches']
    if args.strict_guest:
        failed = failed or totals['guest_lost'] or totals['guest_absent'] or totals['other_mismatches']
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
