#!/usr/bin/env python3
"""Bounded, noncombat summon stages for a disposable online_pair run.

Only sends pad input to the two clients named in that run's manifest. Does not
modify guest memory, saves, or global client binaries. A failed stage is an error.
"""
import argparse
import json
from pathlib import Path
import time

from coop_combat_probe import Guest, send_pad


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('stage', choices=('first', 'again', 'leave', 'snapshot'))
    args = parser.parse_args()
    records = json.loads((args.run / 'manifest.json').read_text())
    guests = {record['role']: Guest(record) for record in records}
    host, bot = guests['host'], guests['bot']

    def status():
        state = {role: guest.snapshot() for role, guest in guests.items()}
        print(time.strftime('%H:%M:%S'), json.dumps(state), flush=True)
        return state

    def pad(guest, button, ms=200, delay=0.9):
        deadline = time.monotonic() + 2
        while True:
            try:
                send_pad(guest.folder, button, ms)
                break
            except PermissionError:
                # The Windows guest briefly holds pad.txt without delete share.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        time.sleep(delay)

    try:
        if args.stage == 'snapshot':
            status()
            return
        if args.stage == 'leave':
            if status()['bot']['state'] != 3:
                raise RuntimeError('bot must be a summoned phantom before crystal exit')
            time.sleep(10)  # Let the arrival transition release the inventory input.
            pad(bot, 'a')  # Dismiss the "Summoned to the world" notification.
            # Verified on this seed: inventory starts at Estus, followed by
            # Lifegem, Darksign, White Soapstone, Black Separation Crystal.
            for button in ('start', 'rb', 'a', 'a', 'right', 'right', 'right', 'right',
                           'a', 'a', 'left', 'a'):
                pad(bot, button)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                state = status()
                if all(value['state'] == 0 and value['session'] == 0 for value in state.values()):
                    # Returning from the world still needs a loading transition.
                    time.sleep(20)
                    status()  # Also proves both guest processes still exist.
                    print('PASS leave: both sessions closed', flush=True)
                    return
                time.sleep(3)
            raise TimeoutError('crystal exit did not close both sessions')
        if args.stage == 'first':
            deadline = time.monotonic() + 300
            while not all(any('shot at 230 s:' in log.read_text(errors='replace')
                              for log in (guest.folder / 'logs').glob('*.log'))
                          for guest in guests.values()):
                if time.monotonic() >= deadline:
                    raise TimeoutError('230-second bootstrap checkpoint not reached')
                time.sleep(2)
        initial = status()
        if any(state['state'] != 0 for state in initial.values()):
            raise RuntimeError('both clients must be outside a session before placing the sign')
        for button in ('start', 'rb', 'a', 'a', 'right', 'right', 'right', 'a', 'a'):
            pad(bot, button)
        time.sleep(5)
        for _ in range(3):
            pad(bot, 'b')
        # snapshot.pending describes requests after interaction, not visible
        # signs. Both copied seeds stand at the same bonfire position, so the
        # sign is under the host's feet: allow a list refresh, then touch it.
        time.sleep(60)
        pad(host, 'a', delay=2)
        pad(host, 'a')
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = status()
            if state['bot']['state'] == 3 and state['host']['session']:
                print(f'PASS {args.stage}: phantom entered host world', flush=True)
                return
            time.sleep(3)
        raise TimeoutError(f'{args.stage} summon did not reach phantom state 3')
    finally:
        for guest in guests.values():
            guest.close()


if __name__ == '__main__':
    main()
