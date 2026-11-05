#!/usr/bin/env python3
"""Send summon key sequence to running PC Host."""
from pathlib import Path
import time
import sys

ROOT = Path(__file__).resolve().parents[1]

# Check out/pc/pad.txt first, or any active pair folder
candidates = [
    ROOT / 'out/pc/pad.txt',
]
for run_dir in (ROOT / 'out/switch_host_pair').glob('*'):
    if (run_dir / 'pc_host/pad.txt').exists():
        candidates.append(run_dir / 'pc_host/pad.txt')

pad_file = None
for p in candidates:
    if p.parent.exists():
        pad_file = p
        break

if not pad_file:
    print("Error: No active PC Host pad.txt found!")
    sys.exit(1)

def send(mask, lx=0, ly=0, ms=250, label=''):
    stamp = time.time_ns()
    temp = pad_file.with_suffix('.tmp')
    temp.write_text(f"{stamp} {ms} {mask:x} {lx} {ly} 0 0\n", encoding='ascii')
    temp.replace(pad_file)
    print(f"Sent: btn=0x{mask:X} stick=({lx},{ly}) {ms}ms ({label})", flush=True)

print(f"Sending summon commands to {pad_file}...")
# 1. Step towards sign
print("1. Stepping towards sign...")
send(0, lx=0, ly=32767, ms=500, label="step_forward")
time.sleep(1.0)

# 2. Touch sign (A button)
print("2. Touching summon sign (A)...")
send(0x1000, ms=250, label="touch_sign_A")
time.sleep(1.8)

# 3. Confirm summon dialog ('Yes' -> A)
print("3. Confirming summon ('Yes' -> A)...")
send(0x1000, ms=250, label="confirm_dialog_A")
time.sleep(1.0)

print("Done! PC Host confirmed the summon prompt.")
