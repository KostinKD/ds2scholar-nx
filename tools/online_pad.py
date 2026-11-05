#!/usr/bin/env python3
"""Send a bounded command to one online_pair client, without focusing its window."""
import argparse
from pathlib import Path
import time

BUTTONS = dict(a=0x1000, b=0x2000, x=0x4000, y=0x8000, start=0x10, back=0x20,
               up=1, down=2, left=4, right=8, ls=0x40, rs=0x80, lb=0x100, rb=0x200, release=0)
STICKS = dict(lsu=(0, 32767, 0, 0), lsd=(0, -32768, 0, 0),
              lsl=(-32768, 0, 0, 0), lsr=(32767, 0, 0, 0),
              rsu=(0, 0, 0, 32767), rsd=(0, 0, 0, -32768),
              rsl=(0, 0, -32768, 0), rsr=(0, 0, 32767, 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client', type=Path, help='client folder containing ds2.exe and logs/')
    parser.add_argument('button', choices=sorted(BUTTONS.keys() | STICKS.keys()))
    parser.add_argument('--ms', type=int, default=200)
    args = parser.parse_args()
    if not 0 <= args.ms <= 10000:
        parser.error('--ms must be in 0..10000')
    if not (args.client / 'ds2.exe').is_file():
        parser.error('not a prepared client folder')
    stamp = time.time_ns()
    values = (stamp, args.ms, f'{BUTTONS.get(args.button, 0):x}',
              *STICKS.get(args.button, (0, 0, 0, 0)))
    path = args.client / 'pad.txt'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(' '.join(map(str, values)) + '\n', encoding='ascii')
    temporary.replace(path)
    print(f'{args.client.name}: {args.button} {args.ms}ms id={stamp}')


if __name__ == '__main__':
    main()
