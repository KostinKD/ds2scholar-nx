#!/usr/bin/env python3
"""ds2.toml for players of a distributed build (docs/online-public-plan.md, stage D).

app/ds2_switch.toml without its online block (the owner's LAN test settings: addresses, peer XUID, traces), plus
app/online_public.toml. The performance and renderer keys stay in one file, so the two configs never drift apart.

  python -I tools/make_public_config.py out/release/ds2.toml
"""
import argparse
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = '# Online and P2P LAN Co-op'
ONLINE_KEYS = ('net_', 'ds2_socket_buffer_endian')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    base = (ROOT / 'app' / 'ds2_switch.toml').read_text(encoding='utf-8')
    public = (ROOT / 'app' / 'online_public.toml').read_text(encoding='utf-8')
    if base.count(MARKER) != 1:
        raise SystemExit(f'app/ds2_switch.toml: expected exactly one "{MARKER}" line')
    head, tail = base.split(MARKER, 1)
    # Everything after the marker must be the owner's online block: nothing else may be dropped silently.
    dropped = tomllib.loads('#' + tail)  # the rest of the marker line is still a comment
    others = [key for key in dropped if not key.startswith(ONLINE_KEYS)]
    if others:
        raise SystemExit(f'non-online keys after the online marker would be lost: {others}')
    leftover = [key for key in tomllib.loads(head) if key.startswith(ONLINE_KEYS)]
    if leftover:
        raise SystemExit(f'online keys before the marker would stay in the public config: {leftover}')
    text = head.rstrip() + '\n\n' + public.strip() + '\n'
    config = tomllib.loads(text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding='utf-8', newline='\n')
    online = {key: config[key] for key in config if key.startswith(ONLINE_KEYS)}
    print(f'written {args.output}: {len(config)} keys; dropped {len(dropped)} owner online keys; online: {online}')


if __name__ == '__main__':
    main()
