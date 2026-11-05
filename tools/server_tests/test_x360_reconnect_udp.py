"""Exercise repeat Xbox logins against an ISOLATED server with a disposable DB.

Requires the server fork's Tools/Tests/x360_udp_client.py via --client-dir.
Use --legacy to verify the default (replacement disabled) behavior.
Never point this at the public game service: it creates diagnostic accounts.
"""
import argparse
from pathlib import Path
import socket
import sys
import time
import zlib


def close_peer(peer):
    """Bound test teardown and ACK outstanding data before the reciprocal FIN."""
    peer.s.settimeout(0.25)
    peer.send(0x36, peer.local, peer.remote)
    deadline = time.monotonic() + 3
    try:
        while time.monotonic() < deadline:
            try:
                packet = peer.s.recv(65535)
            except socket.timeout:
                continue
            seq = packet[2] | (packet[3] >> 4) << 8
            if packet[5] in (4, 0x34, 8, 0x38, 6, 0x36):
                peer.send(0x31, 0, seq)
            if packet[5] in (6, 0x36):
                break
    finally:
        peer.s.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-dir', required=True, type=Path)
    parser.add_argument('--login', type=int, default=23300)
    parser.add_argument('--legacy', action='store_true')
    parser.add_argument('--regression-suite', action='store_true')
    parser.add_argument('--relay', type=int, default=23302)
    args = parser.parse_args()
    if args.login == 1000:
        parser.error('Use an isolated test login port, not the public service')
    sys.path.insert(0, str(args.client_dir))
    from x360_udp_client import Peer, field, fields

    if args.regression_suite:
        import runpy
        Peer.close = close_peer
        for name, extra in (
            ('test_x360_names_udp.py', ['--port', str(args.login)]),
            ('test_x360_breakin_udp.py', ['--port', str(args.login)]),
            ('test_x360_relay_udp.py', ['--login', str(args.login), '--relay', str(args.relay)]),
        ):
            sys.argv = [name, *extra]
            runpy.run_path(str(args.client_dir / name), run_name='__main__')
        return

    peers = []
    live_games = {}
    account = '0xD531000000000001'
    other = '0xD531000000000002'
    area, cell = 10310000, 8387584

    def login(identity):
        ticket = (identity.encode() + b'ReconnectTest').ljust(35, b'\0')
        auth = Peer(args.login)
        peers.append(auth)
        response = auth.request(3, ticket)
        assert len(response) == 56
        game = Peer(int.from_bytes(response[14:16], 'big'), response[:8], ticket)
        peers.append(game)
        player_id = ping(game, identity)
        live_games[identity] = game
        return game, player_id

    def ping(game, identity):
        body = field(1, identity) + field(2, 1) + field(3, 0) + field(4, 1) + field(5, 2)
        answer = fields(game.request(0x386, body))
        assert answer[1] == [identity.encode()], answer
        assert answer[2][0] > 0, answer
        return answer[2][0]

    def check_retired(game):
        start = time.monotonic()
        # Read a complete server-initiated close rather than treating a timeout
        # as proof that the session was removed.
        deadline = start + 2
        game.s.settimeout(0.25)
        while time.monotonic() < deadline:
            try:
                packet = game.s.recv(65535)
            except socket.timeout:
                continue
            if packet[5] in (6, 0x36):
                seq = packet[2] | (packet[3] >> 4) << 8
                game.send(0x31, 0, seq)
                print(f'old session: server close after {time.monotonic() - start:.3f}s')
                return
        raise AssertionError('old authenticated session was not closed within 2 seconds')

    matching = b''.join(field(k, v) for k, v in (
        (1, 20200), (2, 10), (3, 0), (4, 0), (6, 0), (7, 2),
        (8, 0), (9, 1), (10, 0), (11, 0), (12, 1000)))

    def create_sign(game):
        # Synthetic empty metadata stays inside the disposable test service.
        request = field(1, area) + field(2, matching) + field(3, b'') + field(4, cell) + field(5, 1)
        return fields(game.request(0x394, request))[1][0]

    def sign_ids(game):
        request = (field(1, area) + field(2, field(1, cell) + field(3, 100)) +
                   field(3, 100) + field(4, matching) + field(5, 1) + field(6, 1) + field(7, 0))
        answer = fields(game.request(0x397, request))
        ids = {fields(row)[2][0] for row in answer.get(1, [])}
        ids.update(fields(fields(row)[1][0])[2][0] for row in answer.get(2, []))
        return ids

    def summon_push(game, expected_sign, requester):
        chunks = {}
        deadline = time.monotonic() + 3
        game.s.settimeout(0.5)
        while time.monotonic() < deadline:
            try:
                packet = game.s.recv(65535)
            except socket.timeout:
                continue
            if packet[5] not in (4, 0x34, 8, 0x38):
                continue
            seq = packet[2] | (packet[3] >> 4) << 8
            game.remote = seq
            game.send(0x31, 0, seq)
            fragment = packet[7:]
            compressed, index = bool(fragment[2]), fragment[9]
            total = int.from_bytes(fragment[6:8], 'big')
            chunks[index] = fragment[16:] if compressed and index == 0 else fragment[12:]
            if sum(map(len, chunks.values())) < total:
                continue
            message = b''.join(chunks[k] for k in sorted(chunks))
            if compressed:
                message = zlib.decompress(message)
            chunks = {}
            if int.from_bytes(message[4:8], 'big') != 0x320:
                continue
            body = fields(message[12:])
            if body.get(1) == [0x39B]:
                assert body[2] == [requester] and body[3] == [expected_sign], body
                return
        raise AssertionError('summon push did not reach the replacement session')

    try:
        first, player_id = login(account)
        neighbor, neighbor_id = login(other)
        assert neighbor_id != player_id
        current = first
        current_sign = create_sign(current)
        neighbor_sign = create_sign(neighbor)
        assert {current_sign, neighbor_sign} <= sign_ids(neighbor)
        for attempt in range(3):
            old_sign = current_sign
            replacement, repeated_id = login(account)
            assert repeated_id == player_id, 'repeat login created a different player'
            if args.legacy:
                assert ping(current, account) == player_id
                print('legacy: both sessions still respond')
            else:
                check_retired(current)
            current_sign = create_sign(replacement)
            visible = sign_ids(neighbor)
            assert current_sign in visible and neighbor_sign in visible
            assert (old_sign in visible) == args.legacy, 'old sign cleanup disagrees with replacement mode'
            assert ping(replacement, account) == player_id
            assert ping(neighbor, other) == neighbor_id, 'unrelated player disconnected'
            time.sleep(0.03)
            assert {current_sign, neighbor_sign} <= sign_ids(neighbor), 'later cleanup removed a current sign'
            current = replacement
            print(f'PASS repeat {attempt + 1}: stable ID, correct old sign cleanup; new and unrelated signs survive')
        if not args.legacy:
            neighbor.request(0x398, field(1, area) + field(2, field(1, player_id) + field(2, current_sign)) +
                             field(3, b'') + field(4, cell))
            summon_push(current, current_sign, neighbor_id)
            print('PASS summon push: delivered to the replacement connection')
        print('PASS legacy' if args.legacy else 'PASS replacement')
    finally:
        for game in live_games.values():
            close_peer(game)
        for peer in reversed(peers):
            # Test containers own these disposable sockets; avoid adding 3s per
            # already-closed session during teardown.
            peer.s.close()


if __name__ == '__main__':
    main()
