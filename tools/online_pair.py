#!/usr/bin/env python3
"""Disposable two-client PC probe. Copies binaries and saves, never game assets.

Run outside tools/win/run.ps1: gameplay must not inherit its output pipe.
Each run owns its processes, logs, cache and saves under out/bot_pair/.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XUID = 0xB13EBABEBABEBABE
TEST_XUIDS = (0xB13EBABEBABEBAC0, 0xB13EBABEBABEBAC1)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=240)
    parser.add_argument('--identity-only', action='store_true',
                        help='8-second offline default/override profile check')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--p2p-diagnostics', action='store_true')
    parser.add_argument('--p2p-guest-log', action='store_true')
    parser.add_argument('--p2p-game-trace', action='store_true')
    parser.add_argument('--p2p-name-trace', action='store_true')
    parser.add_argument('--user-name-lookup', action='store_true')
    parser.add_argument('--p2p-summon-name-probe', action='store_true')
    parser.add_argument('--p2p-lan', action='store_true')
    parser.add_argument('--p2p-title-identity', action='store_true')
    parser.add_argument('--p2p-relay', action='store_true',
                        help='P2P through the server relay (net_p2p_relay + net_p2p_session_addresses)')
    parser.add_argument('--native', action='store_true', help='use the native Vulkan renderer')
    parser.add_argument('--shot-every', type=int, default=0,
                        help='capture every N seconds in addition to startup captures')
    parser.add_argument('--server', default='127.0.0.1')
    parser.add_argument('--runtime-dir', type=Path,
                        help='optional freshly built SDK DLL directory')
    parser.add_argument('--seed', type=Path, default=ROOT / 'out/pc/userdata')
    parser.add_argument('--script', default='88:start,105:a,130:a,145:a',
                        help='bootstrap for an existing save with the EULA accepted')
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error('--seconds must be positive')
    build = ROOT / 'out/pc'
    runtime_dir = args.runtime_dir or build
    # Restrict seed copying to saved-game content. In particular, never copy DLC
    # (00000002), assets/game_root, or an entire arbitrary user data directory.
    source = args.seed.resolve() / f'{DEFAULT_XUID:016X}/465307E4/00000001'
    if not source.is_dir():
        parser.error(f'no saved-game seed: {source}')
    original_hashes = {str(p): digest(p) for p in source.rglob('*') if p.is_file()}
    if not original_hashes:
        parser.error('saved-game seed is empty')
    run = ROOT / 'out/bot_pair' / time.strftime('%Y%m%d_%H%M%S')
    run.mkdir(parents=True, exist_ok=False)
    records = []
    processes = []
    streams = []
    xuids = (DEFAULT_XUID, TEST_XUIDS[1]) if args.identity_only else TEST_XUIDS
    try:
        for role, xuid in zip(('host', 'bot'), xuids):
            folder = run / role
            folder.mkdir()
            for name, origin in (
                ('ds2.exe', build), ('ds2.toml', build),
                ('rexruntimerd.dll', runtime_dir), ('rexgpu-xenosrd.dll', runtime_dir)
            ):
                shutil.copy2(origin / name, folder / name)
            if args.native:
                for name in ('sa2_shaders.mesp', 'sa2_shaders.mesp.idx'):
                    shutil.copy2(build / name, folder / name)
            target = folder / f'userdata/{xuid:016X}/465307E4/00000001'
            shutil.copytree(source, target)
            # SotFS requires Compatibility Pack even in base-game zones. Share
            # the existing all-users DLC namespace by a directory link; do not
            # duplicate game data into the probe. Game-created saves stay local.
            shared_content = args.seed.resolve() / '0000000000000000'
            if shared_content.is_dir():
                link = folder / 'userdata/0000000000000000'
                if os.name == 'nt':
                    subprocess.run(['cmd', '/c', 'mklink', '/J', str(link),
                                    str(shared_content)], check=True, capture_output=True)
                else:
                    link.symlink_to(shared_content, target_is_directory=True)
            elif not args.identity_only:
                parser.error(f'Compatibility Pack namespace missing: {shared_content}')
            record = {'role': role, 'xuid': f'{xuid:016X}', 'folder': str(folder)}
            records.append(record)
            if args.prepare_only:
                continue
            env = os.environ.copy()
            env.update({
                'REX_AUDIO_MUTE': 'true', 'REX_WINDOW_START_MINIMIZED': 'true',
                'REX_GAME_DATA_ROOT': str(ROOT / 'assets/game_root'),
                'REX_USER_DATA_ROOT': str(folder / 'userdata'),
                'REX_CACHE_ROOT': str(folder / 'cache'),
                'REX_CONTENT_BACKUP_ROOT': '',
                'REX_NET_PROFILE_XUID': str(0 if args.identity_only and role == 'host' else xuid),
                'REX_NET_ONLINE_PROBE': 'false' if args.identity_only else 'true',
                'REX_NET_DNS_ADDRESS': args.server, 'REX_NET_TITLE_SERVER_COUNT': '1',
                'REX_NET_P2P_DIAGNOSTICS': 'true' if args.p2p_diagnostics else 'false',
                'REX_NET_P2P_GUEST_LOG': 'true' if args.p2p_guest_log else 'false',
                'REX_NET_P2P_GAME_TRACE': 'true' if args.p2p_game_trace else 'false',
                'REX_NET_P2P_NAME_TRACE': 'true' if args.p2p_name_trace else 'false',
                'REX_NET_USER_NAME_LOOKUP': 'true' if args.user_name_lookup else 'false',
                'REX_NET_USER_NAME_DIRECTORY': ';'.join(f'{v:016X}=User' for v in TEST_XUIDS)
                    if args.user_name_lookup else '',
                'REX_NET_P2P_SUMMON_NAME_PROBE': 'true' if args.p2p_summon_name_probe else 'false',
                'REX_NET_P2P_LAN': 'true' if args.p2p_lan else 'false',
                'REX_NET_P2P_TITLE_IDENTITY': 'true' if args.p2p_title_identity else 'false',
                'REX_NET_P2P_RELAY': 'true' if args.p2p_relay else 'false',
                'REX_NET_P2P_SESSION_ADDRESSES': 'true' if args.p2p_relay else 'false',
                'REX_NET_P2P_ADDRESS': '127.0.0.2' if role == 'host' else '127.0.0.3',
                'REX_NET_P2P_PEER_ADDRESS': '127.0.0.3' if role == 'host' else '127.0.0.2',
                'REX_NET_P2P_PEER_XUID': str(TEST_XUIDS[1] if role == 'host' else TEST_XUIDS[0]),
                'REX_NET_P2P_PORT': '3074',
                'REX_DS2_SOCKET_BUFFER_ENDIAN': 'true',
                'REX_SA2_RENDERER_NATIVE': 'true' if args.native else 'false',
                'REX_NET_PROBE_INPUT_FILE': str(folder / 'pad.txt'),
                'REX_DS2_INPUT_SCRIPT': '' if args.identity_only else args.script,
                'REX_DS2_SHOT_S': '' if args.identity_only else ','.join(map(str, sorted(
                    {90, 140, 190, 230} | (set(range(args.shot_every, args.seconds, args.shot_every))
                                         if args.shot_every > 0 else set())))),
            })
            output = (folder / 'process.log').open('wb')
            streams.append(output)
            startup = None
            if os.name == 'nt':
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 7  # SW_SHOWMINNOACTIVE
            process = subprocess.Popen([str(folder / 'ds2.exe')], cwd=folder,
                                       env=env, stdout=output, stderr=subprocess.STDOUT,
                                       startupinfo=startup)
            processes.append(process)
            record['pid'] = process.pid
        print(f'run={run}', flush=True)
        print(json.dumps(records), flush=True)
        (run / 'manifest.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        if not args.prepare_only:
            deadline = time.monotonic() + (8 if args.identity_only else args.seconds)
            while time.monotonic() < deadline:
                if (run / 'stop').exists():
                    break
                if all(p.poll() is not None for p in processes):
                    break
                time.sleep(1)
    finally:
        for record, process in zip(records, processes):
            record['exited_before_cleanup'] = process.poll() is not None
            record['exit_code_before_cleanup'] = process.returncode
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        for stream in streams:
            stream.close()
        changed = [p for p, before in original_hashes.items()
                   if not Path(p).is_file() or digest(Path(p)) != before]
        if changed:
            raise RuntimeError(f'seed changed during probe: {changed}')
    failures = []
    for record in records:
        folder = Path(record['folder'])
        logs = list((folder / 'logs').glob('*.log'))
        identity = []
        for path in logs:
            with path.open(encoding='utf-8', errors='replace') as stream:
                for line in stream:
                    if '[profile] XUID=' in line:
                        identity.append(line.rstrip())
                        break
        record['identity_log'] = identity
        print(f"{record['role']}: {identity}", flush=True)
        if not args.prepare_only and not any(f"XUID={record['xuid']}" in s for s in identity):
            failures.append(f"{record['role']}: expected profile was not observed")
        if record.get('exited_before_cleanup'):
            failures.append(f"{record['role']}: exited early, code={record['exit_code_before_cleanup']}")
    (run / 'result.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print('seed unchanged; own processes stopped', flush=True)
    if failures:
        raise RuntimeError('; '.join(failures))


if __name__ == '__main__':
    main()
