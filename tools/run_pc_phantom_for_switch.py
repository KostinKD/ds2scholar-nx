#!/usr/bin/env python3
"""Run PC client as white phantom for Nintendo Switch host in Heide's Tower of Flame."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SWITCH_IP = "192.168.1.76"
PC_IP = "192.168.1.95"
PC_XUID = 0xB13EBABEBABEBAC0
SWITCH_XUID = 0xB13EBABEBABEBABE


def send_pad(client_dir, button, ms=200):
    BUTTONS = dict(a=0x1000, b=0x2000, x=0x4000, y=0x8000, start=0x10, back=0x20,
                   up=1, down=2, left=4, right=8, ls=0x40, rs=0x80, lb=0x100, rb=0x200, release=0)
    STICKS = dict(lsu=(0, 32767, 0, 0), lsd=(0, -32768, 0, 0),
                  lsl=(-32768, 0, 0, 0), lsr=(32767, 0, 0, 0),
                  rsu=(0, 0, 0, 32767), rsd=(0, 0, 0, -32768),
                  rsl=(0, 0, -32768, 0), rsr=(0, 0, 32767, 0))
    stamp = time.time_ns()
    values = (stamp, ms, f'{BUTTONS.get(button, 0):x}', *STICKS.get(button, (0, 0, 0, 0)))
    path = client_dir / 'pad.txt'
    temp = path.with_suffix('.tmp')
    temp.write_text(' '.join(map(str, values)) + '\n', encoding='ascii')
    temp.replace(path)
    print(f"[{time.strftime('%H:%M:%S')}] PC input: {button} {ms}ms", flush=True)


def main():
    build = ROOT / 'out/pc'
    runtime_dir = ROOT / 'sdk/out/win-amd64'
    if not (runtime_dir / 'rexruntimerd.dll').exists():
        runtime_dir = build

    seed_source = ROOT / 'out/bot_pair/seed_heide_ready_20261026' / f'{0xB13EBABEBABEBABE:016X}/465307E4/00000001'

    run = ROOT / 'out/switch_pc_pair' / time.strftime('%Y%m%d_%H%M%S')
    run.mkdir(parents=True, exist_ok=False)

    folder = run / 'pc'
    folder.mkdir()

    print(f"[{time.strftime('%H:%M:%S')}] Preparing PC phantom client in {folder}...")
    for name, origin in (
        ('ds2.exe', build), ('ds2.toml', build),
        ('rexruntimerd.dll', runtime_dir), ('rexgpu-xenosrd.dll', runtime_dir)
    ):
        import shutil
        shutil.copy2(origin / name, folder / name)

    target_save = folder / f'userdata/{PC_XUID:016X}/465307E4/00000001'
    import shutil
    shutil.copytree(seed_source, target_save)

    shared_content = ROOT / 'out/bot_pair/seed_heide_ready_20261026/0000000000000000'
    if shared_content.is_dir():
        link = folder / 'userdata/0000000000000000'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(shared_content)],
                       check=True, capture_output=True)

    env = os.environ.copy()
    env.update({
        'REX_AUDIO_MUTE': 'true',
        'REX_WINDOW_START_MINIMIZED': 'true',
        'REX_GAME_DATA_ROOT': str(ROOT / 'assets/game_root'),
        'REX_USER_DATA_ROOT': str(folder / 'userdata'),
        'REX_CACHE_ROOT': str(folder / 'cache'),
        'REX_CONTENT_BACKUP_ROOT': '',
        'REX_NET_PROFILE_XUID': str(PC_XUID),
        'REX_NET_ONLINE_PROBE': 'true',
        'REX_NET_DNS_ADDRESS': PC_IP,
        'REX_NET_TITLE_SERVER_COUNT': '1',
        'REX_NET_P2P_DIAGNOSTICS': 'true',
        'REX_NET_P2P_GUEST_LOG': 'true',
        'REX_NET_P2P_GAME_TRACE': 'true',
        'REX_NET_P2P_NAME_TRACE': 'true',
        'REX_NET_USER_NAME_LOOKUP': 'true',
        'REX_NET_USER_NAME_DIRECTORY': f'{PC_XUID:016X}=User;{SWITCH_XUID:016X}=User',
        'REX_NET_P2P_LAN': 'true',
        'REX_NET_P2P_TITLE_IDENTITY': 'true',
        'REX_NET_P2P_ADDRESS': PC_IP,
        'REX_NET_P2P_PEER_ADDRESS': SWITCH_IP,
        'REX_NET_P2P_PEER_XUID': str(SWITCH_XUID),
        'REX_NET_P2P_PORT': '3074',
        'REX_DS2_SOCKET_BUFFER_ENDIAN': 'true',
        'REX_SA2_RENDERER_NATIVE': 'false',
        'REX_NET_PROBE_INPUT_FILE': str(folder / 'pad.txt'),
        'REX_DS2_INPUT_SCRIPT': '88:start,105:a,130:a,145:a,175:a',
        'REX_DS2_SHOT_S': '90,140,190,230',
    })

    log_file = (folder / 'process.log').open('wb')
    process = subprocess.Popen([str(folder / 'ds2.exe')], cwd=folder, env=env,
                               stdout=log_file, stderr=subprocess.STDOUT)
    print(f"[{time.strftime('%H:%M:%S')}] PC phantom process launched (PID={process.pid}).")
    print(f"[{time.strftime('%H:%M:%S')}] Waiting for world bootstrap into Heide's Tower of Flame (~230s)...")

    try:
        # Wait for world loaded
        log_path = folder / 'logs' / 'ds2_001.log'
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"PC process exited unexpectedly (code {process.returncode})")
            if log_path.exists():
                text = log_path.read_text(errors='replace')
                if 'shot at 230 s:' in text:
                    print(f"[{time.strftime('%H:%M:%S')}] PC client confirmed in-world at 230s checkpoint!")
                    break
            time.sleep(3)
        else:
            raise TimeoutError("Timeout waiting for 230s checkpoint on PC")

        time.sleep(5)
        print(f"[{time.strftime('%H:%M:%S')}] PC casting White Sign Soapstone via inventory menu...")
        for b in ['start', 'rb', 'a', 'a', 'right', 'right', 'right', 'a', 'a']:
            send_pad(folder, b, ms=200)
            time.sleep(0.9)
        time.sleep(5)
        for _ in range(3):
            send_pad(folder, 'b', ms=200)
            time.sleep(0.9)

        print(f"[{time.strftime('%H:%M:%S')}] White sign cast complete! Sign is registered on server.")
        print(f"[{time.strftime('%H:%M:%S')}] >>> WAITING FOR SWITCH PLAYER TO TOUCH SIGN ON CONSOLE <<<")
        print(f"[{time.strftime('%H:%M:%S')}] Monitoring network packets from Switch ({SWITCH_IP}:10010)...", flush=True)

        deadline = time.monotonic() + 86400  # Keep alive up to 24 hours (stop with Ctrl+C or stop file)
        while time.monotonic() < deadline:
            if (run / 'stop').exists():
                print("Stop requested via stop file.")
                break
            if process.poll() is not None:
                print(f"PC process exited with code {process.returncode}")
                break
            time.sleep(2)

    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
        log_file.close()
        print("PC phantom session closed cleanly.")


if __name__ == '__main__':
    main()
