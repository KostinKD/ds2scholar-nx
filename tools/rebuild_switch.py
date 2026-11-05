#!/usr/bin/env python3
"""Repeatable PGO+LTO build; normally run tools/win/rebuild_switch.ps1.

Requires the Windows toolchain, Mesa/NVK, own assets/game_root/default.xex,
and a PGO folder (install the separate bundle first). Outputs stay in out/.
"""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def signature(root, paths):
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(root)).replace('\\', '/').encode())
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def codegen_signature(root):
    paths = [root / 'assets/game_root/default.xex', root / 'tools/codegen.ps1']
    paths += [p for p in (root / 'app').glob('*.toml') if p.name != 'ds2_switch.toml']
    paths += list((root / 'tools').glob('*codegen*.py'))
    paths += [root / 'tools' / name for name in ('pch_no_volatile.py', 'loop_barriers.py',
                                              'keep_volatile.py', 'direct_calls.py', 'localize_native.py')]
    post = root / 'tools/post_codegen.py'
    if post.is_file():
        paths += [root / 'tools' / name for name in re.findall(r"tool\('([^']+)'\)", post.read_text(encoding='utf-8'))]
    paths += [root / 'sdk/CMakeLists.txt', root / 'sdk/thirdparty/CMakeLists.txt', root / 'out/extra_hooks.txt']
    for folder in ('sdk/src', 'sdk/include', 'sdk/resources', 'sdk/cmake', 'app/src'):
        paths += [p for p in (root / folder).rglob('*') if p.is_file()]
    layout = root / 'app/generated/default/codegen.partition.json'
    if layout.is_file():
        paths.append(layout)
    return signature(root, [p for p in paths if p.is_file()])


def bundle_tool():
    spec = importlib.util.spec_from_file_location('rebuild_pgo_bundle', ROOT / 'tools/pgo_bundle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_profiles(root, pgo, profiles):
    tool = bundle_tool()
    for path in profiles:
        tool.validate_data(path.read_bytes(), '16.1.0')
    layout = pgo / 'codegen.partition.json'
    if not layout.exists():
        layout = root / 'app/generated/default/codegen.partition.json'
    if not layout.is_file():
        raise ValueError('PGO codegen layout missing; install the portable PGO bundle')
    data = layout.read_bytes()
    tool.validate_layout(data)
    count = json.loads(data)['file_count']
    expected = ['CMakeFiles#ds2_recomp.dir#generated#default#ds2_recomp.' + str(n) + '.cpp.gcda'
                for n in range(count)]
    for name in expected:
        if not (pgo / name).is_file():
            raise ValueError('missing guest PGO file: ' + name)
    if (pgo / 'manifest.json').is_file():
        manifest = json.loads((pgo / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['schema'] != 2 or manifest['compiler'] != '16.1.0':
            raise ValueError('PGO manifest/compiler mismatch')
        tool.check_sources(root, manifest['source_revision'])
        if hashlib.sha256(data).hexdigest() != manifest['layout']['sha256']:
            raise ValueError('PGO layout checksum mismatch')
        for name, meta in manifest['files'].items():
            path = pgo / name.replace(tool.TOKEN, tool.encoded_root(root))
            if (not path.is_file() or path.stat().st_size != meta['size'] or
                    hashlib.sha256(path.read_bytes()).hexdigest() != meta['sha256']):
                raise ValueError('PGO checksum mismatch: ' + name)


def make_plan(root, build, pgo):
    root, build, pgo = root.resolve(), build.resolve(), pgo.resolve()
    if build == root / 'out' or not build.is_relative_to(root / 'out'):
        raise ValueError('build directory must be a child of this repository out/')
    if not pgo.is_relative_to(root):
        raise ValueError('PGO directory must be inside this repository')
    profiles = list(pgo.glob('*.gcda'))
    if not profiles:
        raise ValueError('PGO files missing; install the PGO bundle first (docs/pgo-profile.md)')
    if not (root / 'assets/game_root/default.xex').is_file():
        raise ValueError('own assets/game_root/default.xex is required')
    verify_profiles(root, pgo, profiles)
    try:
        state = json.loads((build / 'rebuild-state.json').read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    profile = signature(root, profiles)
    codegen = codegen_signature(root)
    generated = (root / 'app/generated/rexglue.cmake').is_file()
    return {'profile': profile, 'codegen': codegen, 'profile_files': len(profiles),
            'regenerate': not generated or state.get('codegen') != codegen,
            'validate_profile': not state.get('validated') or state.get('profile') != profile or
                                state.get('codegen') != codegen or state.get('rules') != rules_signature(build) or
                                state.get('guest_objects') != object_signature(build),
            'clean': (build / 'CMakeCache.txt').exists() and state.get('profile') != profile}


def rules_signature(build):
    path = build / 'build.ninja'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def object_signature(build):
    entries = []
    for path in sorted((build / 'CMakeFiles/ds2_recomp.dir').rglob('*.obj')):
        info = path.stat()
        entries.append((str(path.relative_to(build)), info.st_size, info.st_mtime_ns))
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def needs_configure(build, pgo, jobs=5):
    path = build / 'CMakeCache.txt'
    if not path.is_file():
        return True
    cache = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if ':' in line and '=' in line and not line.startswith(('//', '#')):
            key, value = line.split('=', 1)
            cache[key.split(':', 1)[0]] = value
    devkit = Path(os.environ.get('DEVKITPRO', 'G:/devkitPro')).resolve()
    nvk = Path(os.environ.get('NVK_SDK', 'G:/DS2Switch/mesa-switch/mesa-unified-install/opt/devkitpro/portlibs/switch')).resolve()
    return (cache.get('DS2_PGO') != 'use' or cache.get('DS2_SWITCH_LTO') != 'ON' or
            cache.get('DS2_SWITCH_LTO_JOBS') != str(jobs) or
            Path(cache.get('DEVKITPRO', '')).resolve() != devkit or
            Path(cache.get('REXGLUE_SWITCH_NVK_SDK', '')).resolve() != nvk or
            cache.get('CMAKE_BUILD_TYPE') != 'Release' or
            Path(cache.get('DS2_PGO_DIR', '')).resolve() != pgo.resolve())


def run(root, name, args):
    print('[rebuild] ' + name, flush=True)
    subprocess.run([str(a) for a in args], cwd=root, check=True)


def powershell(script, *args):
    return ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, *args]


def save_state(build, state):
    temporary = build / 'rebuild-state.tmp'
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    temporary.replace(build / 'rebuild-state.json')


def artifact_signature(build):
    return {name: hashlib.sha256((build / name).read_bytes()).hexdigest() for name in ('ds2', 'ds2.nro')}


def binary_check_signature(root, build, nvk):
    return artifact_signature(build) | {
        'checker': hashlib.sha256((root / 'tools/check_switch_build.py').read_bytes()).hexdigest(),
        'sdk-vulkan': hashlib.sha256((nvk / 'lib/libvulkan.a').read_bytes()).hexdigest()}


def execute(root, build, pgo, jobs, regenerate=False, clean=False):
    plan = make_plan(root, build, pgo)
    previous_rules = rules_signature(build)
    previous_objects = object_signature(build)
    try:
        previous_artifacts = json.loads((build / 'rebuild-state.json').read_text()).get('artifacts')
    except (FileNotFoundError, json.JSONDecodeError):
        previous_artifacts = None
    compiler = Path(os.environ.get('DEVKITPRO', 'G:/devkitPro')) / 'devkitA64/bin/aarch64-none-elf-g++.exe'
    if subprocess.check_output([str(compiler), '-dumpfullversion'], text=True).strip() != '16.1.0':
        raise ValueError('this PGO bundle requires devkitA64 GCC 16.1.0')
    build.mkdir(parents=True, exist_ok=True)
    lock = build / 'rebuild.lock'
    try:
        handle = lock.open('x')
    except FileExistsError as exc:
        raise ValueError(f'Build lock exists: {lock}; check the previous process before removing it') from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
            handle.flush()
            if regenerate or plan['regenerate']:
                run(root, 'configure host generator', ['cmake', '-S', 'sdk', '-B', 'out/host', '-G', 'Ninja',
                    '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=clang', '-DCMAKE_CXX_COMPILER=clang++',
                    '-DCMAKE_C_FLAGS=-march=x86-64-v2', '-DCMAKE_CXX_FLAGS=-march=x86-64-v2', '-DREXGLUE_BUILD_TESTS=OFF'])
                run(root, 'build host generator', ['cmake', '--build', 'out/host', '--target', 'rexglue', '-j', str(jobs)])
                if (pgo / 'manifest.json').is_file():
                    run(root, 'prepare original PGO codegen layout', [sys.executable, '-I', 'tools/pgo_bundle.py',
                        'prepare-codegen', '--profiles', pgo])
                elif not (root / 'app/generated/default/codegen.partition.json').is_file():
                    raise ValueError('Legacy PGO has no codegen layout; install the portable bundle first')
                # The generator's own cache does not cover hook scans / its executable.
                # Invalidate only the derived stamp; preserve the PGO partition sidecar.
                (root / 'app/generated/default/codegen.stamp').unlink(missing_ok=True)
                run(root, 'optimised codegen', powershell('tools/codegen.ps1', '-Flavor', 'optimised',
                    '-Rexglue', root / 'sdk/out/win-amd64/rexglue.exe'))
                plan['codegen'] = codegen_signature(root)
                # A failed later compile must not force another expensive codegen.
                prior = json.loads((build / 'rebuild-state.json').read_text()) if (build / 'rebuild-state.json').exists() else {}
                save_state(build, {'codegen': plan['codegen'], 'profile': prior.get('profile'), 'validated': False})
            run(root, 'host glslang', powershell('tools/win/build_glslang.ps1'))
            if clean or plan['clean']:
                if (build / 'CMakeCache.txt').exists():
                    backup = root / 'out/rebuild-backups' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                    for name in ('ds2', 'ds2.nro'):
                        if (build / name).is_file():
                            backup.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(build / name, backup / name)
                    run(root, 'clean (profile changed or explicitly requested)', ['cmake', '--build', build, '--target', 'clean'])
            defines = 'DS2_PGO=use,DS2_SWITCH_LTO=ON,DS2_SWITCH_LTO_JOBS=' + str(jobs) + ',DS2_PGO_DIR=' + str(pgo).replace('\\', '/')
            switches = ['-Jobs', str(jobs), '-BuildDir', build.relative_to(root), '-Define', defines]
            if needs_configure(build, pgo, jobs):
                switches.append('-Reconfigure')
            run(root, 'Switch PGO use + LTO', powershell('tools/win/build_switch.ps1', *switches))
            if (regenerate or plan['regenerate'] or plan['validate_profile'] or
                    rules_signature(build) != previous_rules or object_signature(build) != previous_objects):
                run(root, 'verify actual guest PGO use', [sys.executable, '-I', 'tools/pgo_fit.py',
                    '--build-dir', build, '--all', '--jobs', str(jobs), '--strict-guest'])
            nvk = Path(os.environ.get('NVK_SDK', 'G:/DS2Switch/mesa-switch/mesa-unified-install/opt/devkitpro/portlibs/switch'))
            if binary_check_signature(root, build, nvk) != previous_artifacts:
                run(root, 'verify ELF/NRO', [sys.executable, '-I', 'tools/check_switch_build.py', '--elf', build / 'ds2',
                    '--nro', build / 'ds2.nro', '--sdk-vulkan', nvk / 'lib/libvulkan.a'])
            else:
                print('[rebuild] ELF/NRO bytes unchanged; previous binary check retained', flush=True)
            save_state(build, {'profile': plan['profile'], 'codegen': plan['codegen'], 'validated': True,
                               'rules': rules_signature(build), 'guest_objects': object_signature(build),
                               'artifacts': binary_check_signature(root, build, nvk)})
            nro = build / 'ds2.nro'
            print(json.dumps({'nro': str(nro), 'bytes': nro.stat().st_size,
                'sha256': hashlib.sha256(nro.read_bytes()).hexdigest()}, indent=2))
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--build-dir', type=Path, default=Path('out/nx_pgo'))
    parser.add_argument('--pgo-dir', type=Path, default=Path('pgo'))
    parser.add_argument('--jobs', type=int, choices=range(1, 6), default=5)
    parser.add_argument('--regenerate', action='store_true')
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--plan', action='store_true', help='read-only preflight, do not build')
    args = parser.parse_args()
    root = args.root.resolve()
    build, pgo = (root / args.build_dir).resolve(), (root / args.pgo_dir).resolve()
    try:
        if args.plan:
            print(json.dumps(make_plan(root, build, pgo) | {'jobs': args.jobs, 'PGO': 'use', 'LTO': True}, indent=2))
        else:
            execute(root, build, pgo, args.jobs, args.regenerate, args.clean)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
