#!/usr/bin/env python3
"""Extracts an Xbox 360 Games on Demand package (content type 0x00007000, SVOD volume) into a folder.

A GoD package is a LIVE/CON header file plus a `<header>.data/` folder of Data0000, Data0001, ... files. The data
files hold the disc's XDVDFS partition in 0x800-byte blocks, interleaved with SVOD hash tables:

    each DataNNNN (max 0xA290000 bytes) = 0x1000 level-1 hash table
                                         + up to 0xCB groups of [0x1000 level-0 hash table + 0x198 * 0x800 data]

This exposes the data blocks, with the hash tables stripped, as one seekable stream and walks it with the XDVDFS
code of extract_iso.py. It only reads the package; it does not check the hashes.

Usage:
    python tools/god_extract.py <GoD header file>                    extract into assets/game_root
    python tools/god_extract.py <GoD header file> -o some/folder     extract somewhere else
    python tools/god_extract.py <GoD header file> --list             list the files, extract nothing
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_iso  # noqa: E402

BLOCK = 0x800
HASH_BLOCK = 0x1000
BLOCKS_PER_L0 = 0x198
BLOCKS_PER_FILE = 0x14388           # 0xCB groups * 0x198 blocks
DATA_PER_FILE = BLOCKS_PER_FILE * BLOCK


def read_header(path):
    with open(path, "rb") as fh:
        h = fh.read(0x1800)
    if h[:4] not in (b"LIVE", b"PIRS", b"CON "):
        raise extract_iso.ExtractError("%s is not a LIVE/PIRS/CON package (magic %r)" % (path, h[:4]))
    u32 = lambda o: struct.unpack_from(">I", h, o)[0]
    info = {
        "magic": h[:4].decode("latin-1"),
        "content_type": u32(0x344),
        "media_id": u32(0x354),
        "version": u32(0x358),
        "base_version": u32(0x35C),
        "title_id": u32(0x360),
        "disc": (h[0x366], h[0x367]),
        "volume_type": u32(0x3A9),              # 0 = STFS, 1 = SVOD
        "svod_flags": h[0x379 + 0x18],          # 0x40 = enhanced GDF layout
        "data_file_count": u32(0x39D),
        "data_file_size": struct.unpack_from(">Q", h, 0x3A1)[0],
        "display_name": h[0x411:0x411 + 0x80].decode("utf-16-be", "replace").split("\0")[0],
    }
    return info


class SvodStream:
    """Read-only view of the data blocks of an SVOD volume, hash tables removed."""

    def __init__(self, data_dir, count):
        self.files = [open(os.path.join(data_dir, "Data%04d" % i), "rb") for i in range(count)]
        last = os.path.getsize(self.files[-1].name)
        self.size = (count - 1) * DATA_PER_FILE + self._data_bytes(last)
        self.pos = 0

    @staticmethod
    def _data_bytes(physical):
        """Data bytes in a data file of `physical` bytes."""
        body = max(physical - HASH_BLOCK, 0)
        full, rest = divmod(body, HASH_BLOCK + BLOCKS_PER_L0 * BLOCK)
        return full * BLOCKS_PER_L0 * BLOCK + max(rest - HASH_BLOCK, 0)

    def seek(self, offset, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            self.pos = offset
        elif whence == os.SEEK_CUR:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        out = bytearray()
        while n > 0 and self.pos < self.size:
            index, in_file = divmod(self.pos, DATA_PER_FILE)
            group, in_group = divmod(in_file, BLOCKS_PER_L0 * BLOCK)
            physical = HASH_BLOCK + group * (HASH_BLOCK + BLOCKS_PER_L0 * BLOCK) + HASH_BLOCK + in_group
            take = min(n, BLOCKS_PER_L0 * BLOCK - in_group, self.size - self.pos)
            fh = self.files[index]
            fh.seek(physical)
            chunk = fh.read(take)
            if not chunk:
                break
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def close(self):
        for fh in self.files:
            fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extracts an Xbox 360 Games on Demand (SVOD) package.")
    parser.add_argument("header", help="the GoD header file (the one next to the <name>.data folder)")
    parser.add_argument("-o", "--output", default=extract_iso.default_output(),
                        help="destination folder (default: assets/game_root of this repository)")
    parser.add_argument("--list", action="store_true", help="list the contents, extract nothing")
    args = parser.parse_args(argv)

    try:
        info = read_header(args.header)
        print("== GoD package ==")
        print("  magic %s, content type 0x%08X, volume type %d (%s), SVOD flags 0x%02X"
              % (info["magic"], info["content_type"], info["volume_type"],
                 {0: "STFS", 1: "SVOD"}.get(info["volume_type"], "?"), info["svod_flags"]))
        print("  title id %08X, media id %08X, version %08X, base version %08X, disc %d/%d"
              % (info["title_id"], info["media_id"], info["version"], info["base_version"], *info["disc"]))
        print("  name %r, %d data files, %s bytes" % (info["display_name"], info["data_file_count"],
                                                     f"{info['data_file_size']:,}"))
        if info["volume_type"] != 1:
            raise extract_iso.ExtractError("not an SVOD volume; use stfs_extract.py")
        if info["svod_flags"] & 0x40:
            raise extract_iso.ExtractError("enhanced GDF layout is not supported")
        data_dir = args.header + ".data"
        stream = SvodStream(data_dir, info["data_file_count"])
        print("  data stream %s bytes\n" % f"{stream.size:,}")
        with stream as fh:
            base, description = extract_iso.find_partition(fh)
            print("Game partition at stream offset 0x%08X  (%s)" % (base, description))
            root_sector, root_size = extract_iso.read_volume_descriptor(fh, base)
            entries = list(extract_iso.walk(fh, base, root_sector, root_size))
            files = [(p, e) for p, e in entries if not e["is_dir"]]
            print("%d files, %d directories, %s bytes in total\n"
                  % (len(files), len(entries) - len(files), f"{sum(e['size'] for _, e in files):,}"))
            if args.list:
                for path, entry in entries:
                    print("  [dir]  %s" % path if entry["is_dir"] else "  %12s  %s" % (f"{entry['size']:,}", path))
                return 0
            for path, entry in entries:
                if entry["is_dir"]:
                    os.makedirs(extract_iso._safe_destination(args.output, path), exist_ok=True)
            for done, (path, entry) in enumerate(files, 1):
                extract_iso.extract_file(fh, base, entry, extract_iso._safe_destination(args.output, path))
                if done % 50 == 0:
                    print("  ... %d files" % done)
            print("\n%d files extracted into %s" % (len(files), args.output))
        xex = os.path.join(args.output, "default.xex")
        if os.path.exists(xex):
            print()
            extract_iso.print_xex_info(xex)
    except extract_iso.ExtractError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
