"""Common Sixserver/WE10LE room and settings regressions over real wire frames.

Only SQL results are faked; configuration, profile logic, models, dispatch,
packet checksums, transports, room mutations, and settings compression are real.
"""

from hashlib import md5
from pathlib import Path
import struct
from types import SimpleNamespace
import zlib

import pytest
from twisted.internet import defer, task
from twisted.internet.address import IPv4Address
from twisted.internet.testing import StringTransport

from fiveserver import config, data6, logic
from fiveserver.model import lobby, user
from fiveserver.protocol import PacketServiceFactory, pes5, pes6, we10le


ROOT = Path(__file__).resolve().parents[1]


def request_frame(packet_id, payload=b''):
    header = struct.pack('!HHI', packet_id, len(payload), 1)
    plain = header + md5(header + payload).digest() + payload
    return bytes(value ^ b'\xa6\x77\x95\x7c'[i % 4] for i, value in enumerate(plain))


def responses(transport):
    wire = transport.value()
    result = []
    while wire:
        assert len(wire) >= 24
        header = bytes(value ^ b'\xa6\x77\x95\x7c'[i % 4]
                       for i, value in enumerate(wire[:8]))
        packet_id, size, counter = struct.unpack('!HHI', header)
        assert len(wire) >= size + 24
        plain = bytes(value ^ b'\xa6\x77\x95\x7c'[i % 4]
                      for i, value in enumerate(wire[:size + 24]))
        assert plain[8:24] == md5(plain[:8] + plain[24:]).digest()
        result.append((packet_id, plain[24:]))
        wire = wire[size + 24:]
    return result


def exchange(protocol, packet_id, payload=b''):
    protocol.transport.clear()
    protocol.dataReceived(request_frame(packet_id, payload))
    return responses(protocol.transport)


class MemorySQL:
    """The SQL boundary used by the real data6 and ProfileLogic classes."""

    def __init__(self):
        self.reads = []
        self.writes = []
        self.settings = {}

    def dbRead(self, key, sql, *args):
        self.reads.append(sql)
        if sql.startswith('SELECT settings1, settings2 FROM settings'):
            rows = [self.settings[args[0]]] if args[0] in self.settings else []
        elif sql.startswith('SELECT count('):
            rows = [(0,)]
        elif sql.startswith('SELECT sum('):
            rows = [(0, 0)]
        elif sql.startswith('SELECT wins, best FROM streaks'):
            rows = []
        elif sql.startswith('SELECT match_id, team_id_home'):
            rows = []
        else:
            raise AssertionError('Unexpected SQL read in the room/settings regression')
        return defer.succeed(rows)

    def dbWrite(self, key, sql, *args):
        self.writes.append(sql)
        assert sql.startswith('INSERT INTO settings ')
        profile_id, first, second, updated_first, updated_second = args
        assert (first, second) == (updated_first, updated_second)
        self.settings[profile_id] = (first, second)
        return defer.succeed([])


@pytest.fixture(params=[pes6.MainService, we10le.MainService], ids=['pes6', 'we10le'])
def game(request, monkeypatch):
    clock = task.Clock()
    monkeypatch.setattr(config, 'reactor', clock)
    monkeypatch.setattr(pes5, 'reactor', clock)
    monkeypatch.setenv('FSROOT', str(ROOT))
    server_config = config.YamlConfig(str(ROOT / 'etc/conf/we10le.yaml'))
    sql = MemorySQL()
    profiles = data6.ProfileData(sql)
    matches = data6.MatchData(sql)
    configuration = config.FiveServerConfig(
        server_config, config.DatabaseConfig(**server_config.DB),
        data6.UserData(sql), profiles, matches, logic.ProfileLogic(matches, profiles))
    factory = PacketServiceFactory(configuration)
    factory.protocol = request.param

    def connected(profile_id):
        peer = IPv4Address('TCP', '192.0.2.40', 40000 + profile_id)
        protocol = factory.buildProtocol(peer)
        protocol.makeConnection(StringTransport(
            hostAddress=IPv4Address('TCP', '192.0.2.15', 20210), peerAddress=peer))
        account = user.User(('fixture-%d' % profile_id).encode('ascii'))
        account.username = 'fixture%d' % profile_id
        profile = user.Profile(0)
        profile.id, profile.name = profile_id, 'Fixture%d' % profile_id
        account.profiles, account.profile = [profile], profile
        protocol._user = account  # Pre-authenticated session: this regression starts at lobby entry.
        configuration.userOnline(account)
        configuration.setUserInfo(account, user.UserInfo('we10le', b''))
        payload = (b'\0' + b'192.0.2.40'.ljust(16, b'\0') + struct.pack('!H', 5739)
                   + b'198.51.100.40'.ljust(16, b'\0') + struct.pack('!HH', 5740, 0))
        assert exchange(protocol, 0x4202, payload)[0] == (0x4203, b'\0' * 4)
        return protocol

    host, joiner = connected(101), connected(102)
    host.transport.clear()
    joiner.transport.clear()
    sql.reads.clear()
    return SimpleNamespace(configuration=configuration, sql=sql,
                           host=host, joiner=joiner, lobby=configuration.getLobbies()[0])


def create_room(game, password=b''):
    payload = b'Room fixture'.ljust(64, b'\0') + bytes([bool(password)]) + password.ljust(15, b'\0')
    replies = exchange(game.host, 0x4310, payload)
    assert replies.count((0x4311, b'\0' * 4)) == 1
    room = game.host._user.state.room
    assert isinstance(room, lobby.Room)
    assert room.players == [game.host._user]
    game.host.transport.clear()
    game.joiner.transport.clear()
    game.sql.reads.clear()
    return room


def room_state(room):
    return (room.id, room.name, room.usePassword, room.password, tuple(room.players),
            tuple(room.participatingPlayers), room.owner, room.phase, room.matchSettings)


def test_missing_room_sends_only_error_and_does_not_mutate_lobby(game):
    before = dict(game.lobby.rooms), dict(game.lobby.players)
    replies = exchange(game.joiner, 0x4320, struct.pack('!i', 999) + b'\0' * 15)
    assert replies == [(0x4321, b'\0\0\0\1')]
    assert (game.lobby.rooms, game.lobby.players) == before
    assert game.joiner._user.state.room is None
    assert game.joiner._user.state.inRoom == 0
    assert game.host.transport.value() == b''
    assert game.sql.reads == []


def test_wrong_room_password_sends_only_error_and_preserves_room(game):
    room = create_room(game, b'AL')
    before = room_state(room), dict(game.lobby.rooms)
    replies = exchange(game.joiner, 0x4320, struct.pack('!i', room.id) + b'wrong'.ljust(15, b'\0'))
    assert replies == [(0x4321, b'\xff\xff\xfd\xda')]
    assert (room_state(room), game.lobby.rooms) == before
    assert game.joiner._user.state.room is None
    assert game.joiner._user.state.inRoom == 0
    assert game.host.transport.value() == b''
    assert game.sql.reads == []


@pytest.mark.parametrize('password', [b'', b'AL'], ids=['open-room', 'password-room'])
@pytest.mark.parametrize('match_time', [None, 2], ids=['default-time', 'configured-time'])
def test_successful_join_is_sent_once_and_packs_integer_match_time(game, password, match_time):
    room = create_room(game, password)
    if match_time is not None:
        room.matchSettings = lobby.MatchSettings(*([match_time] + [0] * 11))
    replies = exchange(game.joiner, 0x4320,
                       struct.pack('!i', room.id) + password.ljust(15, b'\0'))
    assert [(code, payload) for code, payload in replies if code == 0x4321] == [
        (0x4321, b'\0' * 4 + bytes([0 if match_time is None else match_time]))]
    assert room.players == [game.host._user, game.joiner._user]
    assert game.joiner._user.state.room is room
    assert game.joiner._user.state.inRoom == 1
    assert [code for code, _ in replies] == [0x4306, 0x4222, 0x4321, 0x4346, 0x4347, 0x4348]
    assert [code for code, _ in responses(game.host.transport)] == [0x4306, 0x4222, 0x4330]
    assert game.sql.reads


def test_room_name_membership_works_through_rename_handler(game):
    room = create_room(game)
    old_name = room.name
    replies = exchange(game.host, 0x434d,
                       b'Renamed fixture'.ljust(64, b'\0') + b'\0' * 16)
    assert replies[-1] == (0x434e, b'\0' * 4)
    assert not game.lobby.isRoom(old_name)
    assert game.lobby.isRoom(b'Renamed fixture')
    assert game.lobby.getRoom(b'Renamed fixture') is room


def test_existing_room_name_is_rejected_without_mutation(game):
    room = create_room(game)
    other = lobby.Room(game.lobby)
    other.name = b'Other fixture'
    game.lobby.addRoom(other)
    before = room_state(room), dict(game.lobby.rooms)
    replies = exchange(game.host, 0x434d, other.name.ljust(64, b'\0') + b'\0' * 16)
    assert replies[-1] == (0x434e, b'\xff' * 4)
    assert (room_state(room), game.lobby.rooms) == before


def test_two_settings_fragments_round_trip_through_real_compression_and_store(game):
    game.configuration.serverConfig.StoreSettings = True
    first = b'\x01\x02\x03first-settings-fragment\0\xff'
    second = b'\x04\x05\x06second-settings-fragment\xfe\0'
    assert exchange(game.joiner, 0x3088, second) == []
    assert exchange(game.joiner, 0x3088, first) == []
    assert exchange(game.joiner, 0x3089) == [(0x308b, b'\0' * 4)]
    stored = game.sql.settings[game.joiner._user.profile.id]
    assert zlib.decompress(stored[0]) == first
    assert zlib.decompress(stored[1]) == second
    game.joiner._user.profile.settings = user.ProfileSettings(None, None)
    assert exchange(game.joiner, 0x308a) == [
        (0x3087, b'\0' * 4 + struct.pack('!I', game.joiner._user.profile.id)),
        (0x3088, first), (0x3088, second), (0x3089, b'')]
    assert len(game.sql.writes) == 1


def test_disabled_settings_storage_preserves_existing_ack_and_unavailable_reply(game):
    assert game.configuration.serverConfig.StoreSettings is False
    assert exchange(game.joiner, 0x3088, b'\0\0\x03first') == []
    assert exchange(game.joiner, 0x3088, b'\0\0\x04second') == []
    assert exchange(game.joiner, 0x3089) == [(0x308b, b'\0' * 4)]
    assert exchange(game.joiner, 0x308a) == [(0x3087, b'\xff\xff\xfe\xdd')]
    assert game.sql.writes == []
    assert game.sql.settings == {}


def test_both_players_exit_with_zero_room_id_updates_for_every_lobby_client(game):
    room = create_room(game)
    exchange(game.joiner, 0x4320, struct.pack('!i', room.id) + b'\0' * 15)
    room_id = room.id
    for leaving, observing in [(game.joiner, game.host), (game.host, game.joiner)]:
        leaving.transport.clear()
        observing.transport.clear()
        direct = exchange(leaving, 0x432a)
        broadcast = responses(observing.transport)
        assert direct.count((0x432b, b'\0' * 4)) == 1
        for frames in [direct, broadcast]:
            updates = [payload for code, payload in frames if code == 0x4222]
            assert len(updates) == 1
            # Independent PES6/PS2 player record offsets confirmed by the client parser.
            assert len(updates[0]) == 127
            assert struct.unpack('!i', updates[0][:4])[0] == leaving._user.profile.id
            assert struct.unpack('!i', updates[0][106:110])[0] == 0
        assert leaving._user.state.room is None
        assert leaving._user.state.inRoom == 0
    assert room.players == []
    assert game.lobby.getRoomById(room_id) is None
    assert set(game.lobby.players.values()) == {game.host._user, game.joiner._user}
    assert (0x4305, struct.pack('!i', room_id)) in direct
    assert (0x4305, struct.pack('!i', room_id)) in broadcast
