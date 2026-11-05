#!/usr/bin/env python3
"""Autonomous PVE combat & session leave/re-summon probe for SotFS online pair."""
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

k = c.WinDLL('kernel32', use_last_error=True)
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
k.ReadProcessMemory.restype = w.BOOL
k.CloseHandle.argtypes = [w.HANDLE]

class Guest:
    def __init__(self, record):
        self.role = record['role']
        self.folder = Path(record['folder'])
        self.handle = k.OpenProcess(0x0010, False, record['pid'])
        if not self.handle:
            raise c.WinError(c.get_last_error())
        log = next((self.folder / 'logs').glob('*.log')).read_text(errors='replace')
        match = re.search(r'arena mapped: virtual base 0x([0-9A-Fa-f]+)', log)
        if not match:
            raise RuntimeError(f'{self.role}: arena mapped base not found in log')
        self.base = int(match[1], 16)

    def read(self, address, size):
        buf = c.create_string_buffer(size)
        got = c.c_size_t()
        if not k.ReadProcessMemory(self.handle, self.base + address, buf, size, c.byref(got)) or got.value != size:
            raise OSError(f'{self.role}: unreadable {address:08X}')
        return buf.raw

    def u32(self, address):
        return int.from_bytes(self.read(address, 4), 'big')

    def snapshot(self):
        root = self.u32(0x834ABB44)
        if not root:
            return {'root': 0, 'manager': 0, 'session': 0, 'state': 0, 'pending': []}
        manager = self.u32(root)
        if not manager:
            return {'root': root, 'manager': 0, 'session': 0, 'state': 0, 'pending': []}
        packet = self.u32(manager + 96)
        session = self.u32(manager + 104)
        state = self.u32(manager + 164)
        mode = self.u32(manager + 100)
        summon = self.u32(root + 12)
        pending = []
        if summon:
            first, last = self.u32(summon + 40), self.u32(summon + 44)
            if first and first <= last <= first + 128:
                for slot in range(first, last, 4):
                    obj = self.u32(slot)
                    if obj:
                        pending.append({
                            'object': obj,
                            'vtable': self.u32(obj),
                            'phase': self.u32(obj + 200),
                            'flag': self.u32(obj + 268),
                            'name_len': self.u32(obj + 76),
                            'name_data': self.read(obj + 60, 16).hex(),
                        })
        return {
            'root': root, 'manager': manager, 'mode': mode,
            'session': session, 'state': state, 'packet': packet,
            'pending': pending
        }

    def close(self):
        if self.handle:
            k.CloseHandle(self.handle)
            self.handle = None


def send_pad(client_dir, button, ms=200):
    BUTTONS = dict(a=0x1000, b=0x2000, x=0x4000, y=0x8000, start=0x10, back=0x20,
                   up=1, down=2, left=4, right=8, lb=0x100, rb=0x200, release=0)
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
    print(f"[{time.strftime('%H:%M:%S')}] {client_dir.name}: {button} {ms}ms", flush=True)


def main():
    if len(sys.argv) < 2:
        print("Usage: python coop_combat_probe.py <run_folder> [--re-summon]")
        sys.exit(1)

    run = Path(sys.argv[1]).resolve()
    re_summon_test = '--re-summon' in sys.argv

    manifest_path = run / 'manifest.json'
    deadline = time.monotonic() + 60
    while not manifest_path.exists():
        if time.monotonic() > deadline:
            print(f"Error: manifest.json not found in {run}")
            sys.exit(1)
        time.sleep(1)

    records = json.loads(manifest_path.read_text())
    guests = {r['role']: Guest(r) for r in records}
    host_guest = guests['host']
    bot_guest = guests['bot']

    log_file = (run / 'combat_probe.log').open('w', encoding='utf-8')
    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_file.write(line + '\n')
        log_file.flush()

    try:
        log("Waiting for world bootstrap on both host and bot (shot at 230 s)...")
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            ready = True
            for r in ['host', 'bot']:
                log_path = run / r / 'logs' / 'ds2_001.log'
                if not log_path.exists() or 'shot at 230 s:' not in log_path.read_text(errors='replace'):
                    ready = False
                    break
            if ready:
                log("Both players confirmed in-world at 230s checkpoint!")
                break
            time.sleep(3)
        else:
            raise TimeoutError("World bootstrap (230s) timed out")

        # Stable wait before sign placement
        time.sleep(5)

        def cast_sign():
            log("Bot casting summon sign via menu sequence...")
            # start -> rb -> a -> a -> right -> right -> right -> a -> a
            menu_seq = ['start', 'rb', 'a', 'a', 'right', 'right', 'right', 'a', 'a']
            for b in menu_seq:
                send_pad(bot_guest.folder, b, ms=200)
                time.sleep(0.9)
            time.sleep(5)
            # Close menu
            for _ in range(3):
                send_pad(bot_guest.folder, 'b', ms=200)
                time.sleep(0.9)
            log("Summon sign cast complete. Waiting for sign discovery...")

        def summon_bot():
            log("Waiting for summon sign in host pending signs...")
            deadline = time.monotonic() + 90
            found_sign = False
            while time.monotonic() < deadline:
                h_snap = host_guest.snapshot()
                if h_snap['pending']:
                    log(f"Sign visible on host: {len(h_snap['pending'])} pending sign(s)")
                    found_sign = True
                    break
                time.sleep(2)

            if not found_sign:
                log("Warning: sign not yet detected in pending memory, proceeding with approach")

            time.sleep(2)
            log("Host stepping towards summon sign...")
            send_pad(host_guest.folder, 'b', ms=200)
            time.sleep(1.0)
            send_pad(host_guest.folder, 'lsu', ms=800)
            time.sleep(1.5)
            log("Host touching summon sign (A)...")
            send_pad(host_guest.folder, 'a', ms=200)
            time.sleep(2.0)
            log("Host confirming summon dialog ('Yes') (A)...")
            send_pad(host_guest.folder, 'a', ms=200)

            log("Waiting for white phantom to enter host world (bot state -> 3)...")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                b_snap = bot_guest.snapshot()
                h_snap = host_guest.snapshot()
                log(f"Status: bot state={b_snap['state']}, host session={h_snap['session']}")
                if b_snap['state'] == 3:
                    log("SUCCESS: White phantom successfully entered world (bot state=3)!")
                    return True
                time.sleep(3)
            return False

        # Phase 1: Initial Summon
        cast_sign()
        time.sleep(15)
        if not summon_bot():
            raise RuntimeError("Initial summon failed")

        time.sleep(10)

        # Phase 2: Combat & Damage Synchronization Test
        log("=== Starting Combat & Damage Synchronization Test ===")
        # Host moves slightly forward to frame the combat area
        log("Host stepping forward to view combat area...")
        send_pad(host_guest.folder, 'lsu', ms=1200)
        time.sleep(2)

        # Bot runs forward out of gazebo towards Old Knight
        log("Bot running forward towards Old Knight (lsu 3800ms)...")
        send_pad(bot_guest.folder, 'lsu', ms=3800)
        time.sleep(4.5)

        # First attack
        log("Bot executing light attack 1 (rb)...")
        send_pad(bot_guest.folder, 'rb', ms=300)
        time.sleep(1.2)

        # Second attack
        log("Bot executing light attack 2 (rb combo)...")
        send_pad(bot_guest.folder, 'rb', ms=300)
        time.sleep(1.2)

        # Evade roll / step back
        log("Bot rolling back (b)...")
        send_pad(bot_guest.folder, 'b', ms=200)
        time.sleep(1.5)

        # Third attack
        log("Bot executing light attack 3 (rb)...")
        send_pad(bot_guest.folder, 'rb', ms=300)
        time.sleep(2.0)

        log("Combat action sequence executed. Waiting for combat sync & enemy reactions...")
        time.sleep(15)

        # Phase 3: Session Termination & Re-Summoning Test
        if re_summon_test:
            log("=== Starting Session Termination & Re-Summoning Test ===")
            # Move bot into Old Knight range to take damage or trigger session exit
            log("Bot standing near Old Knight to observe hit sync or departure...")
            send_pad(bot_guest.folder, 'lsu', ms=1500)
            
            # Wait for either phantom death or session leave
            log("Observing session termination (phantom return to own world)...")
            deadline = time.monotonic() + 120
            session_ended = False
            while time.monotonic() < deadline:
                b_snap = bot_guest.snapshot()
                if b_snap['state'] == 0:
                    log(f"Session cleanly ended: bot state returned to 0 (own world)!")
                    session_ended = True
                    break
                time.sleep(2)

            if not session_ended:
                log("Session still active after 120s; triggering disconnect from bot via menu")
                send_pad(bot_guest.folder, 'start', ms=200)
                time.sleep(1)

            time.sleep(15)
            log("=== Attempting Re-Summoning in Same Process Session ===")
            cast_sign()
            time.sleep(15)
            if summon_bot():
                log("SUCCESS: Re-summoning completed successfully in the same process session!")
            else:
                log("Re-summoning did not complete within deadline")

        log("Combat probe completed successfully.")

    finally:
        for g in guests.values():
            g.close()
        log_file.close()

if __name__ == '__main__':
    main()
