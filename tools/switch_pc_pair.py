#!/usr/bin/env python3
"""Run a single PC client configured to connect with the Nintendo Switch over LAN."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SWITCH_IP = "192.168.1.76"
PC_IP = "192.168.1.95"
PC_XUID = 0xB13EBABEBABEBAC0
SWITCH_XUID = 0xB13EBABEBABEBAC1


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=1200)
    parser.add_argument('--switch-ip', default=SWITCH_IP)
    parser.add_argument('--pc-ip', default=PC_IP)
    parser.add_argument('--role', choices=['host', 'phantom'], default='host',
                        help='role of the PC client: host (summons Switch) or phantom (places sign for Switch)')
    parser.add_argument('--seed', type=Path, default=ROOT / 'out/bot_pair/seed_heide_ready_20261026')
    parser.add_argument('--script', default='88:start,105:a,130:a,145:a,175:a',
                        help='bootstrap sequence into Heide world')
    args = parser.parse_args()

    build = ROOT / 'out/pc'
    runtime_dir = ROOT / 'sdk/out/win-amd64'
    if not (runtime_dir / 'rexruntimerd.dll').exists():
        runtime_dir = build

    run = ROOT / 'out/switch_pc_pair' / time.strftime('%Y%m%d_%H%M%S')
    run.mkdir(parents=True, exist_ok=False)

    folder = run / 'pc'
    folder.mkdir()

    source = args.seed.resolve() / f'{0xB13EBABEBABEBABE:016X}/465307E4/00000001'
    original_hashes = {str(p): digest(p) for p in source.rglob('*') if p.is_file()}

    # Copy executables & DLLs
    for name, origin in (
        ('ds2.exe', build), ('ds2.toml', build),
        ('rexruntimerd.dll', runtime_dir), ('rexgpu-xenosrd.dll', runtime_dir)
    ):
        shutil.copy2(origin / name, folder / name)

    # Setup save for PC XUID
    target = folder / f'userdata/{PC_XUID:016X}/465307E4/00000001'
    shutil.copytree(source, target)

    shared_content = args.seed.resolve() / '0000000000000000'
    if shared_content.is_dir():
        link = folder / 'userdata/0000000000000000'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(shared_content)],
                       check=True, capture_output=True)

    env = os.environ.copy()
    env.update({
        'REX_AUDIO_MUTE': 'false',
        'REX_WINDOW_START_MINIMIZED': 'false',
        'REX_GAME_DATA_ROOT': str(ROOT / 'assets/game_root'),
        'REX_USER_DATA_ROOT': str(folder / 'userdata'),
        'REX_CACHE_ROOT': str(folder / 'cache'),
        'REX_CONTENT_BACKUP_ROOT': '',
        'REX_NET_PROFILE_XUID': str(PC_XUID),
        'REX_NET_ONLINE_PROBE': 'true',
        'REX_NET_DNS_ADDRESS': '127.0.0.1',
        'REX_NET_TITLE_SERVER_COUNT': '1',
        'REX_NET_P2P_DIAGNOSTICS': 'true',
        'REX_NET_P2P_GUEST_LOG': 'true',
        'REX_NET_P2P_GAME_TRACE': 'true',
        'REX_NET_P2P_NAME_TRACE': 'true',
        'REX_NET_USER_NAME_LOOKUP': 'true',
        'REX_NET_USER_NAME_DIRECTORY': f'{PC_XUID:016X}=User;{SWITCH_XUID:016X}=User',
        'REX_NET_P2P_LAN': 'true',
        'REX_NET_P2P_TITLE_IDENTITY': 'true',
        'REX_NET_P2P_ADDRESS': args.pc_ip,
        'REX_NET_P2P_PEER_ADDRESS': args.switch_ip,
        'REX_NET_P2P_PEER_XUID': str(SWITCH_XUID),
        'REX_NET_P2P_PORT': '3074',
        'REX_DS2_SOCKET_BUFFER_ENDIAN': 'true',
        'REX_SA2_RENDERER_NATIVE': 'false',
        'REX_NET_PROBE_INPUT_FILE': str(folder / 'pad.txt'),
        'REX_DS2_INPUT_SCRIPT': args.script,
        'REX_DS2_SHOT_S': '90,140,190,230',
    })

    print(f"Starting PC client in {folder} (PID pending)...", flush=True)
    print(f"Network: PC {args.pc_ip} (XUID {PC_XUID:016X}) <-> Switch {args.switch_ip} (XUID {SWITCH_XUID:016X})", flush=True)

    output = (folder / 'process.log').open('wb')
    process = subprocess.Popen([str(folder / 'ds2.exe')], cwd=folder, env=env,
                               stdout=output, stderr=subprocess.STDOUT)
    manifest = {'role': 'pc', 'xuid': f'{PC_XUID:016X}', 'pid': process.pid,
                'folder': str(folder), 'run': str(run)}
    (run / 'manifest.json').write_text(json.dumps([manifest], indent=2), encoding='utf-8')
    print(f"PC client running, PID={process.pid}. Run directory: {run}", flush=True)

    try:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            if (run / 'stop').exists():
                print("Stop requested via stop file.", flush=True)
                break
            if process.poll() is not None:
                print(f"PC process exited with code {process.returncode}", flush=True)
                break
            time.sleep(1)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        output.close()

        # Check seed integrity
        changed = [p for p, before in original_hashes.items()
                   if not Path(p).is_file() or digest(Path(p)) != before]
        if changed:
            raise RuntimeError(f"Seed corrupted during probe: {changed}")
        print("Seed verified intact. PC process cleanly stopped.", flush=True)


if __name__ == '__main__':
    main()
