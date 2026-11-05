#!/usr/bin/env python3
"""Dumps every optional header of an XEX2 executable, raw and decoded.

Stage 1 analysis: title id, version, XDK build (from the static library list and the import library versions),
timestamp, original PE name, resources, TLS, system flags and the security info. Reads only the header; the PE
image itself stays encrypted and compressed.

Usage: python tools/xex_headers.py assets/game_root/default.xex
"""

import datetime
import struct
import sys

NAMES = {
    0x000002FF: "Resource info", 0x000003FF: "File format info", 0x000005FF: "Delta patch descriptor",
    0x00004004: "Base reference", 0x000080FF: "Bounding path", 0x00008105: "Device ID",
    0x00010001: "Original base address", 0x00010100: "Entry point", 0x00010201: "Image base address",
    0x000103FF: "Import libraries", 0x00018002: "Checksum / timestamp", 0x00018102: "Enabled for callcap",
    0x00018200: "Enabled for fastcap", 0x000183FF: "Original PE name", 0x000200FF: "Static libraries",
    0x00020104: "TLS info", 0x00020200: "Default stack size", 0x00020301: "Default filesystem cache size",
    0x00020401: "Default heap size", 0x00028002: "Page heap size and flags", 0x00030000: "System flags",
    0x00030100: "System flags 32", 0x00030200: "System flags 64",
    0x00040006: "Execution info", 0x00040201: "Title workspace size", 0x00040310: "Game ratings",
    0x00040404: "LAN key", 0x000405FF: "Xbox 360 logo", 0x000406FF: "Multidisc media IDs",
    0x000407FF: "Alternate title IDs", 0x00040801: "Additional title memory", 0x00E10402: "Exports by name",
}


def u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def lib_version(v):
    return "%d.%d.%d.%d" % ((v >> 28) & 0xF, (v >> 24) & 0xF, (v >> 8) & 0xFFFF, v & 0xFF)


def cstr(b):
    return b.split(b"\0")[0].decode("latin-1")


def main(path):
    data = open(path, "rb").read()
    if data[:4] != b"XEX2":
        sys.exit("not an XEX2 file")
    module_flags, pe_offset, _reserved, sec_offset, count = struct.unpack_from(">5I", data, 4)
    print("file %s, %d bytes" % (path, len(data)))
    print("module flags 0x%08X, PE data at 0x%X, security info at 0x%X, %d optional headers\n"
          % (module_flags, pe_offset, sec_offset, count))
    headers = [struct.unpack_from(">II", data, 0x18 + i * 8) for i in range(count)]
    for key, value in headers:
        name = NAMES.get(key, "?")
        kind = key & 0xFF
        print("[%08X] %-30s %s" % (key, name, ("value 0x%08X" % value) if kind in (0, 1) else ("@0x%X" % value)))
        if kind in (0, 1):
            continue
        size = u32(data, value) if kind == 0xFF else kind * 4
        blob = data[value:value + size]
        if key == 0x000200FF:
            for o in range(4, size, 16):
                lname = cstr(blob[o:o + 8])
                major, minor, build, tail = struct.unpack_from(">4H", blob, o + 8)
                print("    %-8s %d.%d.%d.%d  approval %d" % (lname, major, minor, build, tail & 0xFF, tail >> 13))
        elif key == 0x000103FF:
            strtab_size, lib_count = u32(blob, 4), u32(blob, 8)
            names, o = [], 12
            while o < 12 + strtab_size:
                s = cstr(blob[o:])
                if s:
                    names.append(s)
                o += max(len(s) + 1, 1)
                while o % 4:
                    o += 1
            o = 12 + strtab_size
            for _ in range(lib_count):
                lsize = u32(blob, o)
                _import_id, ver, ver_min = struct.unpack_from(">III", blob, o + 0x18)
                name_index, rec_count = struct.unpack_from(">HH", blob, o + 0x24)
                print("    %-12s version %s (min %s), %d imports"
                      % (names[name_index] if name_index < len(names) else "#%d" % name_index,
                         lib_version(ver), lib_version(ver_min), rec_count))
                o += lsize
        elif key == 0x00018002:
            checksum, ts = u32(blob, 0), u32(blob, 4)
            print("    checksum 0x%08X, timestamp 0x%08X = %s UTC"
                  % (checksum, ts, datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()))
        elif key in (0x000183FF, 0x000080FF):
            print("    %r" % cstr(blob[4:]))
        elif key == 0x00040006:
            media, ver, base_ver, title = struct.unpack_from(">4I", blob, 0)
            plat, exe_type, disc, discs = blob[16:20]
            print("    media id %08X, version %s, base version %s, title id %08X, platform %d, exe type %d, "
                  "disc %d/%d, savegame id %08X" % (media, lib_version(ver), lib_version(base_ver), title, plat,
                                                     exe_type, disc, discs, u32(blob, 20)))
        elif key == 0x000002FF:
            for o in range(4, size, 16):
                print("    resource %-8s at 0x%08X, %d bytes" % (cstr(blob[o:o + 8]), u32(blob, o + 8),
                                                                 u32(blob, o + 12)))
        elif key == 0x00020104:
            print("    slots %d, raw data at 0x%08X, data size %d, raw data size %d" % struct.unpack(">4I", blob))
        elif key == 0x000407FF:
            print("    " + ", ".join("%08X" % u32(blob, o) for o in range(4, size, 4)))
        elif key == 0x000003FF:
            print("    info size %d, encryption %d, compression %d" % (u32(blob, 0), u16(blob, 4), u16(blob, 6)))
        else:
            print("    " + blob[:64].hex())
    sec = data[sec_offset:sec_offset + 0x184]
    print("\nsecurity info: header size 0x%X, image size 0x%X, image flags 0x%08X, load address 0x%08X"
          % (u32(sec, 0), u32(sec, 4), u32(sec, 0x10C), u32(sec, 0x110)))
    print("  import table count %d, game region 0x%08X, allowed media 0x%08X, page descriptors %d"
          % (u32(sec, 0x128), u32(sec, 0x178), u32(sec, 0x17C), u32(sec, 0x180)))


if __name__ == "__main__":
    main(sys.argv[1])
