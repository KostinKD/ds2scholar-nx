#!/usr/bin/env python3
"""Light every SotFS Xbox 360 bonfire in a COPY of a USER_DATA0b..14 file.

Only the 77 lit bytes in each of the two verified arrays and the trailing
MD5 are changed. Profile, world events and Bonfire Ascetic counters are kept.
PC .sl2 containers are intentionally rejected. Input is never overwritten.

Layout evidence: two BE u16 ID arrays at 0x282C8/0x2E324 in the Heide seed;
lit bytes at array+512 identify only 2650, 4650, 31655 as lit in that seed.
The relative layout agrees with the independently documented PC structure:
https://github.com/Hapfel1/er-save-manager/blob/main/src/er_save_manager/games/DS2/save.py
IDs below were compared against the complete Xbox arrays, including DLC.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

BONFIRE_IDS = (
    2650, 4650, 10655, 10660, 10670, 10675, 11650, 11655, 11660, 11670,
    14650, 14655, 14660, 15650, 15655, 16650, 16655, 16660, 16665, 16670,
    16675, 16685, 17650, 17655, 17665, 17670, 17675, 18650, 19650, 19655,
    19660, 19665, 21650, 21655, 21660, 21665, 23650, 23655, 23660, 23665,
    24650, 24655, 25650, 25655, 25660, 25665, 27650, 27655, 29650, 31650,
    31655, 31660, 32655, 32660, 33655, 33660, 34650, 34655, 35650, 35655,
    35665, 35670, 35675, 35680, 35685, 36650, 36655, 36660, 36665, 36670,
    36675, 37650, 37660, 37665, 37670, 37675, 37685,
)
WORLD_SIZE = 499976
ID_CAPACITY = 256


def unlock_bonfires(original: bytes) -> tuple[bytes, dict]:
    if len(original) != WORLD_SIZE or original[:4] == b'BND4':
        raise ValueError('Expected a 499976-byte Xbox 360 world slot, not a PC .sl2')
    if hashlib.md5(original[:-16]).digest() != original[-16:]:
        raise ValueError('Input MD5 mismatch; refusing to edit')
    signature = struct.pack('>' + 'H' * len(BONFIRE_IDS), *BONFIRE_IDS)
    anchors = []
    start = 0
    while (found := original.find(signature, start)) != -1:
        anchors.append(found)
        start = found + len(signature)
    if len(anchors) != 2:
        raise ValueError(f'Expected exactly two bonfire ID arrays, found {len(anchors)}')
    bases = [anchor + ID_CAPACITY * 2 for anchor in anchors]
    if any(base + ID_CAPACITY * 2 > len(original) - 16 for base in bases):
        raise ValueError('Bonfire arrays extend outside the slot')
    states = [original[base:base + len(BONFIRE_IDS)] for base in bases]
    if states[0] != states[1] or max(states[0]) > 99:
        raise ValueError('Lit state copies disagree or contain implausible values')
    data = bytearray(original)
    for base in bases:
        for index, value in enumerate(states[0]):
            if value == 0:
                data[base + index] = 1
    data[-16:] = hashlib.md5(data[:-16]).digest()
    return bytes(data), {
        'total': len(BONFIRE_IDS),
        'previously_lit': sum(bool(v) for v in states[0]),
        'newly_lit': states[0].count(0),
        'anchors': [hex(anchor) for anchor in anchors],
        'sha256_before': hashlib.sha256(original).hexdigest(),
        'sha256_after': hashlib.sha256(data).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Output must be a separate file')
    patched, report = unlock_bonfires(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(patched)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
