#!/usr/bin/env python3
"""Minimal FromSoftware reliable-UDP peer for Dark Souls II (Xbox 360) online recon (docs/progress.md, entries 68-69).

The game, with the SDK key net_online_probe, logs in to "its" Live title server at net_dns_address:1000 over UDP with
the transport ds3os documents (Frpg2ReliableUdpPacketHeader, MIT): magic F5 02, 3 bytes of 12-bit sequence counters,
an opcode, 0xFF, then the opcode's payload. This peer answers the handshake (SYN -> SYN_ACK + ACK), acknowledges data
and heartbeats, and logs every datagram in hex, so the first messages after the handshake can be read.

  python tools/frpg2_udp_server.py [--host 127.0.0.1] [--port 1000] [--log logs/frpg2_udp.log]
"""
import argparse
import selectors
import random
import socket
import time

OPS = {0x02: 'SYN', 0x03: 'RACK', 0x04: 'DAT', 0x05: 'HBT', 0x06: 'FIN', 0x07: 'RST', 0x08: 'PT_DAT_FRAG',
       0x31: 'ACK', 0x32: 'SYN_ACK', 0x34: 'DAT_ACK', 0x36: 'FIN_ACK', 0x38: 'PT_DAT_FRAG_ACK'}


def get_counters(b):
    return b[0] | ((b[1] >> 4) << 8), b[2] | ((b[1] & 0xF) << 8)


MSG = {0: 'Reply', 1: 'KeyMaterial', 2: 'GetServiceStatus', 3: 'SteamTicket', 5: 'RequestQueryLoginServerInfo',
       6: 'RequestHandshake'}


def varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def pb_field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes) and not value:
        return varint(number << 3 | 2) + b'\x00'
    return varint(number << 3 | 2) + varint(len(value)) + value


def pb_decode(data):
    """Field list of a protobuf message (number, wire type, value); strings shown when printable."""
    fields, i = [], 0
    try:
        while i < len(data):
            key, n = 0, 0
            while True:
                b = data[i]; i += 1; key |= (b & 0x7F) << n; n += 7
                if not b & 0x80: break
            num, wt = key >> 3, key & 7
            if wt == 0:
                v, n = 0, 0
                while True:
                    b = data[i]; i += 1; v |= (b & 0x7F) << n; n += 7
                    if not b & 0x80: break
                fields.append((num, v))
            elif wt == 2:
                ln, n = 0, 0
                while True:
                    b = data[i]; i += 1; ln |= (b & 0x7F) << n; n += 7
                    if not b & 0x80: break
                raw = data[i:i + ln]; i += ln
                fields.append((num, raw.decode() if raw and all(32 <= c < 127 for c in raw) else raw.hex()))
            elif wt == 1:
                fields.append((num, data[i:i + 8].hex())); i += 8
            elif wt == 5:
                fields.append((num, data[i:i + 4].hex())); i += 4
            else:
                return fields + [('?', data[i:].hex())]
    except IndexError:
        fields.append(('truncated', ''))
    return fields


def frpg2_message(payload):
    """(send counter, msg type, msg index bytes, response header or None, protobuf) of a Frpg2 packet."""
    counter = int.from_bytes(payload[0:2], 'big')
    length = int.from_bytes(payload[4:8], 'big')
    msg = payload[12:12 + length]
    msg_type = int.from_bytes(msg[4:8], 'big')
    index = msg[8:12]
    if msg_type == 0:
        return counter, msg_type, index, msg[12:28], msg[28:]
    return counter, msg_type, index, None, msg[12:]


RESPONSE_HEADER = bytes.fromhex('00000000000000010000000000000000')  # ds3os Frpg2MessageResponseHeader defaults


def frpg2_reply(counter, index, protobuf):
    msg = (12).to_bytes(4, 'big') + (0).to_bytes(4, 'big') + index + RESPONSE_HEADER
    msg += protobuf
    return (counter.to_bytes(2, 'big') + b'\x00\x00' + len(msg).to_bytes(4, 'big') + b'\x00\x00' +
            (len(msg) & 0xFFFF).to_bytes(2, 'big') + msg)


def header(local, remote, opcode):
    return bytes([0xF5, 0x02, local & 0xFF, ((local >> 8) & 0xF) << 4 | ((remote >> 8) & 0xF), remote & 0xFF,
                  opcode, 0xFF])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default='127.0.0.1', help='first address; --count addresses from it')
    ap.add_argument('--count', type=int, default=4)
    ap.add_argument('--reply-opcode', type=lambda v: int(v, 0), default=0x04,
                    help='reliable-UDP opcode of replies: 0x04 DAT (Dark Souls II 360 answers 0x34 with 0x36)')
    ap.add_argument('--port', type=int, default=1000)
    ap.add_argument('--log', default='logs/frpg2_udp.log')
    ap.add_argument('--seconds', type=float, default=600)
    ap.add_argument('--login-ip', default='127.0.0.1', help='RequestQueryLoginServerInfoResponse.server_ip')
    ap.add_argument('--login-port', type=int, default=1000, help='RequestQueryLoginServerInfoResponse.port')
    ap.add_argument('--response-header', default='00000000000000010000000000000000',
                    help='hex of the 16-byte header after the message header of a reply (ds3os: 0, 1, 0, 0)')
    ap.add_argument('--counter-echo', action='store_true', help='reply with the send counter of the request')
    # ds2scholar-nx (2026-10-25): SotFS 360's RequestQueryLoginServerInfoResponse has three varint fields (offsets 24/28/32,
    # MergePartialFromCodedStream sub_82E997B0, vtable 0x820FE7E0; IsInitialized sub_82E8C330 requires field 1) - no
    # string. --login-fields gives them: "1=1000,2=0x7F000001,3=0". Without it, the PC form { port, server_ip string }.
    ap.add_argument('--game-ip', default='127.0.0.1', help='game server address in the login reply')
    ap.add_argument('--game-port', type=int, default=1000, help='game server port in the login reply')
    ap.add_argument('--player-id', type=int, default=1, help='RequestWaitForUserLoginResponse.player_id')
    ap.add_argument('--game-reply-prefix', default='none', choices=('none', 'zero-token', 'token'),
                    help='what precedes our reliable-UDP packets on the game port (unknown for SotFS 360)')
    ap.add_argument('--compact-login', action='store_true',
                    help='login reply as token(8) + ip(4) + 0(2) + port(2) instead of the PC struct')
    ap.add_argument('--login-fields', default='',
                    help='SotFS 360 reply as varint fields, e.g. "1=1000,2=0x7F000001,3=0"')
    ap.add_argument('--message-types', default='out/ext/ds3os/Source/Server.DarkSouls2/Server/Streams/'
                                                 'DS2_Frpg2ReliableUdpMessageTypes.inc',
                    help="ds3os' DS2 message type table, for names in the log (optional)")
    a = ap.parse_args()
    try:  # DEFINE_REQUEST_RESPONSE(0x0386, RequestWaitForUserLogin, ...) / DEFINE_MESSAGE / DEFINE_PUSH_MESSAGE
        import re
        for m in re.finditer(r'DEFINE_\w+\s*\(\s*(0x[0-9A-Fa-f]+)\s*,\s*(\w+)', open(a.message_types).read()):
            MSG.setdefault(int(m.group(1), 16), m.group(2))
    except OSError:
        pass
    global RESPONSE_HEADER
    RESPONSE_HEADER = bytes.fromhex(a.response_header)
    # One socket per address (127.0.0.1 .. +3 by default: the SDK's title-server list), so that each reply leaves
    # from the address the game sent to; one socket on 0.0.0.0 answered everything from 127.0.0.1.
    sel = selectors.DefaultSelector()
    first = list(map(int, a.host.split('.')))
    # ds2scholar-nx: the game server port too (SotFS 360 refuses a second connection to the login ip:port).
    for k in range(a.count):
        host = '.'.join(map(str, first[:3] + [first[3] + k]))
        for port in sorted({a.port, a.game_port}):
            sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sk.bind((host, port))
            sk.setblocking(False)
            sel.register(sk, selectors.EVENT_READ)
    log = open(a.log, 'a', encoding='utf-8')
    t0 = time.time()

    def note(text):
        line = f'{time.time() - t0:8.3f} {text}'
        print(line, flush=True)
        log.write(line + '\n')
        log.flush()

    peers = {}  # address -> {'seq': our next sequence, 'remote': last remote sequence}
    note(f'listening on {a.count} addresses from {a.host}, port {a.port}')
    while time.time() - t0 < a.seconds:
        events = sel.select(timeout=1.0)
        if not events:
            continue
        s = events[0][0].fileobj
        try:
            data, addr = s.recvfrom(65536)
        except (BlockingIOError, ConnectionResetError):
            continue
        addr = (addr[0], addr[1], s.getsockname()[0])  # the peer, and which of our addresses it talked to
        # ds2scholar-nx: SotFS 360 game server packets (port --game-port), plain text: u64 kind (1 on the first
        # packets, which also carry the 35-byte login ticket, 0 after; little-endian) + the 8-byte login token + reliable UDP.
        wrap = None
        if s.getsockname()[1] == a.game_port and a.game_port != a.port and len(data) >= 16:
            kind, token = int.from_bytes(data[0:8], 'little'), data[8:16]  # little-endian (01 00 .. 00)
            inner = data[16 + (35 if kind == 1 else 0):]
            note(f'<- {addr} game packet kind {kind} token {token.hex()}'
                 f'{" ticket " + data[16:51].rstrip(bytes(1)).decode("latin1") if kind == 1 else ""}')
            data = inner
            if a.game_reply_prefix == 'zero-token':
                wrap = lambda o, token=token: bytes(8) + token + o
            elif a.game_reply_prefix == 'token':
                wrap = lambda o, token=token: token + o
        if len(data) < 7 or data[0:2] != b'\xF5\x02':
            note(f'<- {addr} {len(data)} bytes (not reliable UDP): {data.hex()}')
            continue
        local, remote = get_counters(data[2:5])
        op = data[5]
        payload = data[7:]
        note(f'<- {addr} {OPS.get(op, hex(op))} local {local:03X} remote {remote:03X} payload {len(payload)}: '
             f'{payload.hex()}')
        peer = peers.setdefault(addr, {'seq': random.randrange(1, 4096), 'remote': 0})
        out = []
        if op == 0x02:  # SYN: SYN_ACK with our sequence and theirs, then ACK (ds3os Handle_SYN)
            peer['remote'] = local
            out.append(header(peer['seq'], local, 0x32) + bytes([0x12, 0x10, 0x20, 0x20, 0x00, 0x01, 0x00, 0x00]))
            peer['seq'] = (peer['seq'] + 1) % 4096
            out.append(header(0, local, 0x31))
        elif op in (0x04, 0x34, 0x36):  # data (and data / fin acknowledgements carrying data): acknowledge
            peer['remote'] = local
            out.append(header(0, local, 0x31))
            if payload and op != 0x36:
                counter, msg_type, index, response, protobuf = frpg2_message(payload)
                note(f'   message {MSG.get(msg_type, msg_type)} counter {counter} index {index.hex()}'
                     f'{" response " + response.hex() if response else ""}: {pb_decode(protobuf)}')
                reply = None
                if msg_type == 5 and a.login_fields:  # SotFS 360: varint fields
                    reply = b''.join(pb_field(int(k), int(v, 0)) for k, v in
                                     (kv.split('=') for kv in a.login_fields.split(',')))
                elif msg_type == 5:  # RequestQueryLoginServerInfo -> Response { port = 1, server_ip = 2 } (PC)
                    reply = pb_field(1, a.login_port) + pb_field(2, a.login_ip)
                elif msg_type == 2:  # GetServiceStatus -> Response { id = 2, steam_id = "", unknown_1 = 0, app_version }
                    # SotFS 360: MergePartialFromCodedStream sub_82EAA260 (fields 1 varint, 2 string, 3/4 varint),
                    # IsInitialized sub_82E84EE8 (fields 1 and 2); values as ds3os AuthClient.
                    version = next((v for k, v in pb_decode(protobuf) if k == 4), 0)
                    reply = pb_field(1, 2) + pb_field(2, '') + pb_field(3, 0) + pb_field(4, version)
                elif msg_type == 0x0386:  # RequestWaitForUserLogin -> Response { steam_id = 1, player_id = 2 }
                    # ds3os DS2 proto; SotFS 360 Merge sub_82EAA798 (1 string, 2 varint required) - the same.
                    steam_id = next((v for k, v in pb_decode(protobuf) if k == 1), '')
                    reply = pb_field(1, steam_id) + pb_field(2, a.player_id)
                elif msg_type == 3:  # "SteamTicket" (360: XUID string + gamertag, raw) -> raw reply
                    # SotFS 360 Login state sub_82EEB380 takes the first 8 bytes of the reply (ld) as the login token.
                    # The rest as ds3os Frpg2GameServerInfo (AuthClient.h): ip char[16], 112 bytes, port u16 BE,
                    # padding, 11 u32 BE.
                    token = bytes(random.randrange(256) for _ in range(8))
                    if a.compact_login:  # SotFS 360: exactly 56 bytes or ignored (sub_82EEBDB8, caller sub_82EEB2F0):
                        # token u64, ip u32, u16, game port u16 (-> this+134), then ds3os' 10 u32 (all big-endian).
                        ip = bytes(int(x) for x in a.game_ip.split('.'))
                        reply = (token + ip + bytes(2) + a.game_port.to_bytes(2, 'big') +
                                 b''.join(v.to_bytes(4, 'big') for v in (0x8000, 0x8000, 0xA000, 0xA000, 0x80, 0x8000,
                                                                          0xA000, 0x493E0, 0x61A8, 0xC)))
                        assert len(reply) == 56
                    else:
                        reply = None
                    reply = reply or (token + a.game_ip.encode().ljust(16, b'\0') +
                             bytes(112) + a.game_port.to_bytes(2, 'big') + bytes(2) +
                             b''.join(v.to_bytes(4, 'big') for v in (0x8000, 0x8000, 0xA000, 0xA000, 0x80, 0x8000,
                                                                      0xA000, 0x493E0, 0x61A8, 0xC, 0)))
                if reply is not None:
                    peer['counter'] = counter if a.counter_echo else peer.get('counter', 0) + 1
                    data_out = frpg2_reply(peer['counter'], index, reply)
                    out.append(header(peer['seq'], local, a.reply_opcode) + data_out)  # ds3os: DAT_ACK (0x34)
                    peer['seq'] = (peer['seq'] + 1) % 4096
                    note(f'   reply to {MSG.get(msg_type, msg_type)}: {pb_decode(reply)}')
        elif op == 0x05:  # heartbeat: answer with one
            out.append(header(0, peer['remote'], 0x05))
        elif op == 0x06:  # FIN
            out.append(header(peer['seq'], local, 0x36))
        for o in out:
            s.sendto(wrap(o) if wrap else o, addr[:2])
            note(f'-> {addr} {OPS.get(o[5], hex(o[5]))} {o.hex()}{" (wrapped)" if wrap else ""}')


if __name__ == '__main__':
    main()
