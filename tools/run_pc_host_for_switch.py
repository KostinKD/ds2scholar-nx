#!/usr/bin/env python3
"""PC Host Daemon for Switch Phantom testing.

Runs PC client as World Master (Host) at Heide Ruin Bonfire.
Automatically detects when the Nintendo Switch player places a White Sign Soapstone,
approaches the sign, touches it, and summons the Switch player into the PC world.
"""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

SWITCH_IP = '192.168.1.76'
PC_IP = '192.168.1.95'
SWITCH_XUID = 0xB13EBABEBABEBABE
PC_XUID = 0xB13EBABEBABEBAC0

k = c.WinDLL('kernel32', use_last_error=True)
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
k.ReadProcessMemory.restype = w.BOOL


def send_pad(folder: Path, button: str, ms=200, lx=0, ly=0):
    BUTTONS = {
        'a': 0x1000,
        'b': 0x2000,
        'x': 0x4000,
        'y': 0x8000,
        'start': 0x0010,
        'rs': 0x0080,
        'lb': 0x0100,
        'rb': 0x0200,
    }
    mask = BUTTONS.get(button, 0)
    pad = folder / 'pad.txt'
    stamp = time.time_ns()
    temp = pad.with_suffix('.tmp')
    temp.write_text(f"{stamp} {ms} {mask:x} {lx} {ly} 0 0\n", encoding='ascii')
    temp.replace(pad)


def main():
    build = ROOT / 'out/pc'
    runtime_dir = ROOT / 'sdk/out/win-amd64'
    if not (runtime_dir / 'rexruntimerd.dll').exists():
        runtime_dir = build

    # Heide Ruin bonfire seed save
    seed_source = ROOT / 'out/bot_pair/seed_heide_ready_20261026' / f'{0xB13EBABEBABEBABE:016X}/465307E4/00000001'

    run = ROOT / 'out/switch_host_pair' / time.strftime('%Y%m%d_%H%M%S')
    run.mkdir(parents=True, exist_ok=False)

    folder = run / 'pc_host'
    folder.mkdir()

    print(f"[{time.strftime('%H:%M:%S')}] Initializing PC Host environment in {folder}...")
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
    print(f"[{time.strftime('%H:%M:%S')}] PC Host launched (PID={process.pid}).")
    print(f"[{time.strftime('%H:%M:%S')}] Booting into Heide's Tower of Flame (~230s)...")

    try:
        log_path = folder / 'logs' / 'ds2_001.log'
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"PC Host exited unexpectedly (code {process.returncode})")
            if log_path.exists():
                text = log_path.read_text(errors='replace')
                if 'shot at 230 s:' in text:
                    print(f"[{time.strftime('%H:%M:%S')}] PC Host in-world at Heide Ruin Bonfire!")
                    break
            time.sleep(3)
        else:
            raise TimeoutError("Timeout waiting for 230s checkpoint on PC Host")

        # Open process for memory observation
        text = log_path.read_text(errors='replace')
        m = re.search(r'arena mapped: virtual base 0x([0-9A-Fa-f]+)', text)
        base = int(m[1], 16) if m else 0x100000000
        h_proc = k.OpenProcess(0x0010, False, process.pid)

        buf = c.create_string_buffer(4)
        got = c.c_size_t()
        def u32(addr):
            k.ReadProcessMemory(h_proc, base + addr, buf, 4, c.byref(got))
            return int.from_bytes(buf.raw, 'big')

        print(f"\n[{time.strftime('%H:%M:%S')}] =====================================================")
        print(f"[{time.strftime('%H:%M:%S')}] >>> PC HOST ГОТОВ ПРИНЯТЬ ПРИЗЫВ ОТ SWITCH-ИГРОКА! <<<")
        print(f"[{time.strftime('%H:%M:%S')}] Пожалуйста, поставьте БЕЛЫЙ МЕЛОК у костра на консоли.")
        print(f"[{time.strftime('%H:%M:%S')}] =====================================================\n")

        summoned = False
        scan_deadline = time.monotonic() + 86400
        while time.monotonic() < scan_deadline:
            if (run / 'stop').exists() or process.poll() is not None:
                break

            # Check for summon signs in memory
            root = u32(0x834ABB44)
            if root:
                manager = u32(root)
                summon = u32(root + 12) if root else 0
                pending_count = 0
                if summon:
                    first, last = u32(summon + 40), u32(summon + 44)
                    if first and first <= last <= first + 128:
                        pending_count = (last - first) // 4

                if pending_count > 0 and not summoned:
                    print(f"[{time.strftime('%H:%M:%S')}] ОБНАРУЖЕН ЗНАК ПРИЗЫВА ОТ SWITCH (знаков: {pending_count})!")
                    print(f"[{time.strftime('%H:%M:%S')}] PC Host делает шаг к знаку...")
                    send_pad(folder, 'b', ms=150)
                    time.sleep(0.5)
                    send_pad(folder, '', lx=0, ly=32767, ms=600)
                    time.sleep(1.0)

                    print(f"[{time.strftime('%H:%M:%S')}] PC Host активирует знак (нажатие A)...")
                    send_pad(folder, 'a', ms=250)
                    time.sleep(1.8)

                    print(f"[{time.strftime('%H:%M:%S')}] PC Host подтверждает призыв ('Yes' -> A)...")
                    send_pad(folder, 'a', ms=250)
                    time.sleep(2.0)
                    summoned = True
                    print(f"[{time.strftime('%H:%M:%S')}] Запрос на призыв отправлен! Switch загружается в мир...")

            time.sleep(2)

    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(10)
            except Exception:
                process.kill()
        log_file.close()
        print("PC Host session finished.")


if __name__ == '__main__':
    main()
