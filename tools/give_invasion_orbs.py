#!/usr/bin/env python3
"""Ensure a stack of Cracked Red Eye Orbs in a COPY of an Xbox SotFS profile.

Evidence: live Xbox USER_DATA01 files (2026-10-28) have the 16-byte item list
at 0x1E2C, black crystal 62160000 x1 and Lifegem 60010000 x10/x12. Consumable
quantity is a BE u16 at +8, NOT the PC editor's LE u32. Item 62060000 exists
in this game's embedded ItemParam.param (row table offset 0x2F8C); its name
is independently catalogued by er-save-manager/games/DS2/item_database.py.
Only one item record and the trailing MD5 can change. Never overwrites input.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

PROFILE_SIZE = 111308
INVENTORY_START = 0x1E2C
INVENTORY_END = 0x10E1C
STRIDE = 16
ORB = 62060000


def give_orbs(original: bytes, count: int = 50, expected_name: str | None = None):
    if len(original) != PROFILE_SIZE or hashlib.md5(original[:-16]).digest() != original[-16:]:
        raise ValueError('Expected an intact 111308-byte Xbox profile with trailing MD5')
    if not 1 <= count <= 99:
        raise ValueError('Quantity must be 1..99')
    name = original[960:992].decode('utf-16-be').split('\0', 1)[0]
    if expected_name is not None and name != expected_name:
        raise ValueError(f'Wrong character: expected {expected_name!r}, found {name!r}')
    records = [(offset, struct.unpack_from('>IIHHI', original, offset))
               for offset in range(INVENTORY_START, INVENTORY_END, STRIDE)]
    if not any(record == (62160000, 0, 1, 0, 0) for _, record in records):
        raise ValueError('Xbox inventory layout not verified: missing black crystal anchor')
    if not any(record[0] == 60010000 and record[1] == 0 and 1 <= record[2] <= 99
               and record[3:] == (0, 0) for _, record in records):
        raise ValueError('Xbox u16 quantity layout not verified: missing Lifegem anchor')
    existing = [(offset, record) for offset, record in records if record[0] == ORB and record[1] == 0]
    if len(existing) > 1:
        raise ValueError('Ambiguous duplicate carried stacks')
    if existing:
        offset, record = existing[0]
        if record[3:] != (0, 0) or not 1 <= record[2] <= 99:
            raise ValueError('Unexpected existing orb record')
        before = record[2]
        count = max(count, before)
    else:
        used = [offset for offset, record in records if any(record)]
        offset = max(used, default=INVENTORY_START - STRIDE) + STRIDE
        if offset >= INVENTORY_END or any(original[offset:offset + STRIDE]):
            raise ValueError('No empty slot after the last item')
        before = 0
    result = bytearray(original)
    struct.pack_into('>IIHHI', result, offset, ORB, 0, count, 0, 0)
    result[-16:] = hashlib.md5(result[:-16]).digest()
    return bytes(result), {'name': name, 'item_id': ORB, 'before': before,
                           'after': count, 'offset': hex(offset),
                           'sha256_before': hashlib.sha256(original).hexdigest(),
                           'sha256_after': hashlib.sha256(result).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--name', required=True)
    parser.add_argument('--count', type=int, default=50)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Output must be a separate copy')
    data, report = give_orbs(args.input.read_bytes(), args.count, args.name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as output:
        output.write(data)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
