"""Run the shared PES6 session through real PS2 framing and model objects.

Only persistence and the reactor clock are replaced. Authentication, profile
hydration/statistics, dispatch, room membership and phase changes are production
code. These are server flow regressions, not a claim of a two-console match.
"""

import struct
from types import SimpleNamespace

import pytest
from twisted.internet import defer, task
from twisted.internet.error import ConnectionDone
from twisted.python.failure import Failure

from fiveserver import logic, rating
from fiveserver.config import FiveServerConfig
from fiveserver.model import lobby, user
from fiveserver.protocol import pes5, we10le

from test_we10le import (CIPHER_KEY, connected, encrypted_auth, request_frame,
                        response_frames)


class MemoryDatabase:
    """DB boundary returning real User/Profile instances and Deferred results."""

    def __init__(self):
        self.accounts = []
        self.profiles = []
        self.calls = []
        for account_id, name in enumerate(('hostid', 'guestid'), 1):
            account = user.User(('stored-hash-%d' % account_id).encode('ascii'))
            account.id = account_id
            account.username = name
            self.accounts.append(account)
            profile = user.Profile(0)
            profile.id = 100 + account_id
            profile.userId = account_id
            profile.name = 'Player_%d' % account_id
            self.profiles.append(profile)

    def result(self, name, argument, value):
        self.calls.append((name, argument))
        return defer.succeed(value)

    def findByUsername(self, name):
        return self.result('username', name,
                           [x for x in self.accounts if x.username == name])

    def getByUserId(self, account_id):
        return self.result('profiles', account_id,
                           [x for x in self.profiles if x.userId == account_id])

    def get(self, profile_id):
        return self.result('profile', profile_id,
                           [x for x in self.profiles if x.id == profile_id])

    def getGames(self, profile_id):
        return self.result('games', profile_id, 0)

    def getWins(self, profile_id):
        return self.result('wins', profile_id, 0)

    def getLosses(self, profile_id):
        return self.result('losses', profile_id, 0)

    def getDraws(self, profile_id):
        return self.result('draws', profile_id, 0)

    def getGoalsHome(self, profile_id):
        return self.result('goals_home', profile_id, (0, 0))

    def getGoalsAway(self, profile_id):
        return self.result('goals_away', profile_id, (0, 0))

    def getStreaks(self, profile_id):
        return self.result('streaks', profile_id, (0, 0))

    def getLastTeamsUsed(self, profile_id, limit):
        assert limit == 5
        return self.result('teams', profile_id, [])


@pytest.fixture
def session(monkeypatch):
    database = MemoryDatabase()
    config = object.__new__(FiveServerConfig)
    config.serverConfig = SimpleNamespace(
        Debug=False, TraceProtocol=False, ShowStats=True, AuthMode='username',
        MaxUsers=100, StoreSettings=False,
        Roster={'enforceHash': False, 'compareHash': False},
        Chat={'bannedWords': [], 'warningMessage': 'Message blocked'})
    config.cipherKey = CIPHER_KEY.hex()
    config.userData = database
    config.profileData = database
    config.matchData = database
    config.profileLogic = logic.ProfileLogic(database, database)
    config.ratingMath = rating.RatingMath(0.44, 0.56)
    config.fastBannedList = []
    config.onlineUsers = {}
    config._latestUserInfo = {}
    config.lobbies = [lobby.Lobby('WE10LE Lobby', 100)]
    config.lobbies[0].typeCode = 0x20
    config.lobbies[0].checkRosterHash = False
    config.lobbies[0].addToChatHistory(
        lobby.ChatMessage(lobby.SYSTEM_PROFILE, 'Welcome'))
    clock = task.Clock()
    monkeypatch.setattr(pes5, 'reactor', clock)
    return SimpleNamespace(config=config, database=database, clock=clock)


class Client:
    def __init__(self, session, role, account_name):
        self.protocol, self.transport, _ = connected(
            role, config=session.config,
            port={we10le.LoginService: 20212,
                  we10le.NetworkMenuService: 20211,
                  we10le.MainService: 20210}[role])
        self.name = account_name
        self.count = 1
        self.server_count = 1

    def drain(self):
        replies = response_frames(self.transport.value())
        self.transport.clear()
        assert [count for _, _, count in replies] == list(range(
            self.server_count, self.server_count + len(replies)))
        self.server_count += len(replies)
        return [(packet_id, data) for packet_id, data, _ in replies]

    def send(self, packet_id, data=b''):
        assert not self.transport.disconnecting
        assert self.transport.value() == b'', 'Drain notifications before a request'
        self.protocol.dataReceived(request_frame(packet_id, data, self.count))
        self.count += 1
        return self.drain()

    def authenticate(self):
        assert self.send(0x3001) == [(0x3002, b'\0' * 16)]
        assert self.send(0x3f01, encrypted_auth(
            username=self.name, password='ABCDEFGHIJKL')) == [
                (0x3f02, b'\0' * 4)]


def lengths(replies):
    return [(packet_id, len(data)) for packet_id, data in replies]


def enter_main(session, account_number, *, bootstrap=True, peer_address=None):
    name = ('hostid', 'guestid')[account_number - 1]
    profile_id = 100 + account_number
    if bootstrap:
        login = Client(session, we10le.LoginService, name)
        login.authenticate()
        assert lengths(login.send(0x3010)) == [(0x3012, 202)]
        assert lengths(login.send(0x3040, struct.pack('!i', profile_id))) == [
            (0x3042, 396)]
        assert lengths(login.send(0x3050)) == [(0x3052, 75)]
        assert login.send(0x3060) == [(0x3062, b'\0' * 4)]
        assert login.send(0x3070, struct.pack('!i', profile_id)) == [
            (0x3071, b'\0' * 4), (0x3073, b'\0' * 4)]
        assert login.send(0x308a, struct.pack('!i', profile_id)) == [
            (0x3087, struct.pack('!I', 0xfffffedd))]
        assert login.send(0x3087, b'\0' * 8) == []
        assert login.send(0x3088, b'\0\0\x03' + b'\0' * 1021) == []
        assert login.send(0x3088, b'\0\0\x01' + b'\0' * 273) == []
        assert login.send(0x3089) == [(0x308b, b'\0' * 4)]
        assert login.send(0x3090, b'\0' * 5) == [(0x3091, b'\0' * 4)]
        assert login.send(0x3100, b'\0' * 5) == [(0x3101, b'\0' * 4)]
        assert login.send(0x3120, struct.pack('!i', profile_id)) == [
            (0x3121, b'\0' * 4), (0x3123, b'')]
        assert login.send(0x0003, b'\0') == [(0x0004, b'\0' * 4)]
        assert login.transport.disconnecting
        login.protocol.connectionLost(Failure(ConnectionDone()))
    main = Client(session, we10le.MainService, name)
    main.authenticate()
    assert lengths(main.send(0x4100, b'\0\x22\x33')) == [(0x4101, 96), (0x4103, 422)]
    replies = main.send(0x4200, b'\0')
    assert lengths(replies) == [(0x4201, 37)]
    assert struct.unpack_from('!H', replies[0][1]) == (1,)
    if peer_address is None:
        address = '192.0.2.%d' % (40 + account_number)
        peer_address = (address, 5700 + account_number,
                        address, 5800 + account_number)
    ip1, port1, ip2, port2 = peer_address
    enter = (b'\0' + ip1.encode('ascii').ljust(16, b'\0') + struct.pack('!H', port1) +
             ip2.encode('ascii').ljust(16, b'\0') + struct.pack('!HH', port2, 0))
    assert lengths(main.send(0x4202, enter)) == [(0x4203, 4), (0x4220, 127)]
    assert main.protocol._user.state.lobbyId == 0
    assert main.protocol._user.lobbyConnection is main.protocol
    return main


@pytest.mark.parametrize('role', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
@pytest.mark.parametrize('tracing', [False, True])
def test_ps2_inherits_shared_status_fallback_on_every_service(session, role, tracing):
    session.config.serverConfig.TraceProtocol = tracing
    client = Client(session, role, 'hostid')
    client.authenticate()
    for request_id, data, reply_id in (
            (0x308c, b'\x01', 0x308d),
            (0x437b, b'', 0x437c),
            (0x4387, b'\0', 0x4388)):
        assert request_id not in client.protocol._handlers
        assert client.send(request_id, data) == [(reply_id, b'\0' * 4)]
    assert not client.transport.disconnecting


@pytest.mark.parametrize('role', [we10le.NetworkMenuService, we10le.MainService])
def test_ps2_profile_permissions_keep_shared_prefix_and_complete_96_bytes(session, role):
    client = Client(session, role, 'hostid')
    client.authenticate()
    replies = client.send(0x4100, b'\0\x22\x33')
    shared_prefix = (b'\0' * 4 + struct.pack('!i', 101) + b'\xff' * 7 + b'\x80' +
                     b'\xff' * 15 + b'\xc0' + b'\x02' * 7 + b'\x01\0')
    assert len(shared_prefix) == 41
    assert replies[0] == (0x4101, shared_prefix + b'\0' * 55)
    assert replies[1][0] == 0x4103
    assert client.protocol._user.profile.id == 101
    error = struct.pack('!I', 0xffffff10)
    client.protocol.sendData(0x4101, error)
    assert client.drain() == [(0x4101, error)]


@pytest.mark.parametrize('tracing', [False, True])
def test_login_lobby_two_player_room_and_ready_share_production_flow(session, tracing):
    session.config.serverConfig.TraceProtocol = tracing
    host = enter_main(session, 1)
    assert lengths(host.send(0x4210)) == [
        (0x4211, 4), (0x4212, 127), (0x4213, 4)]
    assert host.send(0x4300) == [(0x4301, b'\0' * 4), (0x4303, b'\0' * 4)]
    assert host.send(0x3080, b'\0' * 4) == [(0x3082, b'\0' * 4), (0x3086, b'')]
    assert lengths(host.send(0x4102, struct.pack('!i', 101))) == [(0x4103, 422)]
    # The reported live freeze was exactly here: shared fallback was shadowed.
    assert host.send(0x308c, b'\x01') == [(0x308d, b'\0' * 4)]
    session.clock.advance(pes5.CHAT_HISTORY_DELAY)
    assert lengths(host.drain()) == [(0x4402, 186)]

    room_name = b'Test Room'.ljust(64, b'\0')
    assert lengths(host.send(0x4310, room_name + b'\0' + b'\0' * 16)) == [
        (0x4306, 131), (0x4222, 127), (0x4311, 4)]
    room = host.protocol._user.state.room
    assert isinstance(room, lobby.Room)
    assert room.owner is host.protocol._user and room.players == [room.owner]
    assert lengths(host.send(0x4300)) == [(0x4301, 4), (0x4302, 131), (0x4303, 4)]

    guest = enter_main(session, 2)
    assert lengths(host.drain()) == [(0x4220, 127)]
    joined = guest.send(0x4320, struct.pack('!i', room.id) + b'\0' * 16)
    assert lengths(joined) == [
        (0x4306, 131), (0x4222, 127), (0x4321, 5),
        (0x4346, 0), (0x4347, 75), (0x4348, 0)]
    # PS2 always reads this byte; raw index zero represents five minutes.
    assert joined[2] == (0x4321, b'\0' * 5)
    assert lengths(host.drain()) == [(0x4306, 131), (0x4222, 127), (0x4330, 79)]
    assert room.players == [host.protocol._user, guest.protocol._user]
    assert guest.protocol._user.state.room is room
    assert lengths(host.send(0x4363, b'\x01')) == [(0x4365, 24), (0x4364, 6)]
    assert lengths(guest.drain()) == [(0x4365, 24)]
    assert lengths(guest.send(0x4363, b'\x01')) == [(0x4365, 24), (0x4364, 6)]
    assert lengths(host.drain()) == [(0x4365, 24)]
    assert room.participatingPlayers == room.players

    assert lengths(host.send(0x4360)) == [(0x4362, 37), (0x4306, 131), (0x4361, 4)]
    assert lengths(guest.drain()) == [(0x4362, 37), (0x4306, 131)]
    assert room.phase == lobby.RoomState.ROOM_MATCH_SIDE_SELECT
    assert room.matchStarter is host.protocol._user
    assert host.send(0x436f, b'\x01') == [(0x4370, b'\0' * 4)]
    assert lengths(guest.drain()) == [(0x4371, 5)]
    assert room.readyCount == 1
    assert lengths(guest.send(0x436f, b'\x01')) == [
        (0x4370, 4), (0x4344, 1), (0x4306, 131)]
    assert lengths(host.drain()) == [(0x4371, 5), (0x4344, 1), (0x4306, 131)]
    assert room.phase == lobby.RoomState.ROOM_MATCH_SETTINGS_SELECT
    assert room.readyCount == 0

    sides = (struct.pack('!i4B', 101, 0, 0, 0, 0) +
             struct.pack('!i4B', 102, 1, 0, 0, 0) + b'\0' * 16)
    assert lengths(host.send(0x4369, sides)) == [
        (0x436a, 4), (0x436b, 33), (0x4306, 131)]
    assert lengths(guest.drain()) == [(0x436b, 33), (0x4306, 131)]
    assert room.teamSelection.home_captain.id == 101
    assert room.teamSelection.away_captain.id == 102
    settings = bytes([0, 30, 3, 1, 2, 1, 3, 0, 1, 0, 1, 0, 0, 0, 0, 0])
    assert lengths(host.send(0x436c, settings)) == [
        (0x436d, 4), (0x436e, 16), (0x4306, 131)]
    assert lengths(guest.drain()) == [(0x436e, 16), (0x4306, 131)]
    assert room.matchSettings.match_time == 0
    for client, other, team_id in ((host, guest, 11), (guest, host, 22)):
        assert lengths(client.send(0x4373, struct.pack('!HH', team_id, 0))) == [
            (0x4374, 4), (0x4306, 131)]
        assert lengths(other.drain()) == [(0x4306, 131)]
    for phase in range(lobby.RoomState.ROOM_MATCH_TEAM_SELECT,
                       lobby.RoomState.ROOM_MATCH_STARTED + 1):
        assert host.send(0x436f, b'\x01') == [(0x4370, b'\0' * 4)]
        assert lengths(guest.drain()) == [(0x4371, 5)]
        replies = guest.send(0x436f, b'\x01')
        assert lengths(replies) == [(0x4370, 4), (0x4344, 1), (0x4306, 131)]
        assert replies[1][1] == bytes([phase])
        assert lengths(host.drain()) == [(0x4371, 5), (0x4344, 1), (0x4306, 131)]
        assert room.phase == phase
    assert lengths(host.send(0x4377, bytes([lobby.MatchState.FIRST_HALF]))) == [
        (0x4306, 131), (0x4378, 4)]
    assert lengths(guest.drain()) == [(0x4306, 131)]
    assert isinstance(room.match, lobby.Match6)
    assert room.match.home_team_id == 11 and room.match.away_team_id == 22
    assert lengths(host.send(0x4375, b'\0')) == [(0x4376, 4), (0x4306, 131)]
    assert lengths(guest.drain()) == [(0x4306, 131)]
    assert room.match.score_home == 1 and room.match.score_away == 0
    assert lengths(host.send(0x4385, b'\x1e')) == [(0x4386, 4), (0x4306, 131)]
    assert lengths(guest.drain()) == [(0x4306, 131)]
    assert room.match.clock == 30
    assert session.config.getNumUsersOnline() == 2
    # Statistics and profile hydration ran through actual production helpers.
    assert ('profiles', 1) in session.database.calls
    assert ('profile', 102) in session.database.calls
    assert ('goals_home', 101) in session.database.calls
    assert all(not client.transport.disconnecting for client in (host, guest))

    for client, other in ((host, guest), (guest, host)):
        assert lengths(client.send(0x4363, b'\0')) == [(0x4365, 24), (0x4364, 6)]
        assert lengths(other.drain()) == [(0x4365, 24)]
    assert room.participatingPlayers == []
    leaving = host.send(0x432a)
    assert lengths(leaving) == [(0x4306, 131), (0x4222, 127), (0x432b, 4)]
    assert struct.unpack_from('!i', leaving[1][1], 106) == (0,)
    assert lengths(guest.drain()) == [(0x4306, 131), (0x4222, 127)]
    assert host.protocol._user.state.inRoom == 0
    assert host.protocol._user.state.room is None
    assert room.players == [guest.protocol._user]
    assert room.owner is guest.protocol._user
    leaving = guest.send(0x432a)
    assert lengths(leaving) == [
        (0x4306, 131), (0x4222, 127), (0x432b, 4), (0x4305, 4)]
    assert struct.unpack_from('!i', leaving[1][1], 106) == (0,)
    assert lengths(host.drain()) == [(0x4306, 131), (0x4222, 127), (0x4305, 4)]
    assert session.config.lobbies[0].rooms == {}
    assert guest.protocol._user.state.inRoom == 0
    assert guest.protocol._user.state.room is None
    assert host.send(0x0003, b'\0') == [(0x0004, b'\0' * 4)]
    assert guest.drain() == [(0x4221, struct.pack('!i', 101))]
    assert guest.send(0x0003, b'\0') == [(0x0004, b'\0' * 4)]
    assert all(client.transport.disconnecting for client in (host, guest))
    for client in (host, guest):
        client.protocol.connectionLost(Failure(ConnectionDone()))
        assert client.protocol._user.lobbyConnection is None
    assert session.config.onlineUsers == {}
    assert session.config.lobbies[0].players == {}


@pytest.mark.parametrize('message', [b'Hi', bytes(range(256))])
def test_ps2_chat_wire_keeps_58_byte_header_and_128_byte_message(session, message):
    client = Client(session, we10le.MainService, 'hostid')
    client.authenticate()
    header = bytes(range(58))
    client.protocol.sendData(0x4402, header + message)
    assert client.drain() == [(0x4402, header + message[:128].ljust(128, b'\0'))]
    # Chat normalization must not change arbitrary data on other operations.
    client.protocol.sendData(0x7001, header + message)
    assert client.drain() == [(0x7001, header + message)]


def test_lobby_chat_history_and_system_broadcast_use_fixed_ps2_chat_records(session):
    host = enter_main(session, 1, bootstrap=False)
    guest = enter_main(session, 2, bootstrap=False)
    assert lengths(host.drain()) == [(0x4220, 127)]
    special = b'\x01\x02\x03\x04'
    text = b'Lobby hello'
    chat = b'\0\1' + special + b'\0' * 4 + text + b'\0'
    replies = host.send(0x4400, chat)
    assert lengths(replies) == [(0x4402, 186)]
    assert guest.drain() == replies
    payload = replies[0][1]
    assert payload[:6] == b'\0\1' + special
    assert struct.unpack_from('!i', payload, 6) == (101,)
    assert payload[10:58] == b'Player_1'.ljust(48, b'\0')
    assert payload[58:] == text.ljust(128, b'\0')

    this_lobby = session.config.lobbies[0]
    assert this_lobby.chatHistory[-1].text == text.decode('ascii')
    host.protocol.broadcastSystemChat(this_lobby, 'System hello')
    broadcast = host.drain()
    assert lengths(broadcast) == [(0x4402, 186)]
    assert guest.drain() == broadcast
    assert broadcast[0][1][6:10] == b'\0' * 4
    assert broadcast[0][1][58:] == b'System hello'.ljust(128, b'\0')
    session.clock.advance(pes5.CHAT_HISTORY_DELAY)
    history = host.drain()
    assert lengths(history) == [(0x4402, 186)] * 3
    assert guest.drain() == history
    assert [body[58:].rstrip(b'\0') for _, body in history] == [
        b'Welcome', text, b'System hello']


PEER_ADDRESSES = (
    ('203.0.113.7', 31001, '192.168.1.10', 3658),
    ('203.0.113.7', 31002, '192.168.1.11', 3658))


def peer_address_fields(address):
    ip1, port1, ip2, port2 = address
    return (ip1.encode('ascii').ljust(16, b'\0') + struct.pack('!H', port1) +
            ip2.encode('ascii').ljust(16, b'\0') + struct.pack('!H', port2))


def two_peer_room(session):
    host = enter_main(session, 1, bootstrap=False, peer_address=PEER_ADDRESSES[0])
    guest = enter_main(session, 2, bootstrap=False, peer_address=PEER_ADDRESSES[1])
    assert lengths(host.drain()) == [(0x4220, 127)]
    assert lengths(host.send(0x4310, b'Peer Room'.ljust(64, b'\0') + b'\0' * 17)) == [
        (0x4306, 131), (0x4222, 127), (0x4311, 4)]
    assert lengths(guest.drain()) == [(0x4306, 131), (0x4222, 127)]
    room = host.protocol._user.state.room
    joined = guest.send(0x4320, struct.pack('!i', room.id) + b'\0' * 16)
    notices = host.drain()
    return host, guest, room, joined, notices


def test_peer_join_ping_and_stun_list_preserve_each_advertised_udp_endpoint(session):
    host, guest, room, joined, notices = two_peer_room(session)
    host_peer = (b'\0' * 32 + peer_address_fields(PEER_ADDRESSES[0]) +
                 struct.pack('!i', 101) + b'\0\0\xff')
    guest_peer = (b'\0' * 36 + peer_address_fields(PEER_ADDRESSES[1]) +
                  struct.pack('!i', 102) + b'\0\0\xff')
    assert joined[-3:] == [(0x4346, b''), (0x4347, host_peer), (0x4348, b'')]
    assert notices[-1] == (0x4330, guest_peer)
    for client, profile_id, address in (
            (host, 102, PEER_ADDRESSES[1]), (guest, 101, PEER_ADDRESSES[0])):
        assert client.send(0x4b00, struct.pack('!i', profile_id)) == [
            (0x4b01, b'\0' * 4 + peer_address_fields(address) + struct.pack('!i', profile_id))]
    for client, other in ((host, guest), (guest, host)):
        assert lengths(client.send(0x4363, b'\x01')) == [(0x4365, 24), (0x4364, 6)]
        assert lengths(other.drain()) == [(0x4365, 24)]
    replies = host.send(0x4345, struct.pack('!i', room.id))
    assert replies == [
        (0x4346, b''),
        (0x4347, host_peer[:-1] + b'\0'),
        (0x4347, b'\0' * 32 + peer_address_fields(PEER_ADDRESSES[1]) +
         struct.pack('!i', 102) + b'\0\0\x01'),
        (0x4348, b'')]
    # Preserve the existing PES6 duplicate notifications while auditing PS2:
    # do_4330 currently runs once for every record in this two-person list.
    host_notice = b'\0' * 36 + host_peer[32:-1] + b'\0'
    assert guest.drain() == [(0x4330, host_notice)] * 2


def test_room_connection_settings_relay_72_bytes_and_connection_info_for_spectators(session):
    host, guest, room, _, _ = two_peer_room(session)
    settings = b'\0\0\x01\x03' + b'\0' * 8 + b'\x01' + bytes(range(59))
    assert len(settings) == 72
    assert host.send(0x4350, settings) == []
    assert guest.drain() == [(0x4350, settings)]
    assert room.matchTime == 10
    response = b'\0\0\x01\x01' + bytes(range(68))
    assert guest.send(0x4350, response) == []
    assert host.drain() == [(0x4350, response)]
    assert lengths(host.send(0x4363, b'\x01')) == [(0x4365, 24), (0x4364, 6)]
    assert lengths(guest.drain()) == [(0x4365, 24)]
    assert guest.send(0x4366) == [(0x4367, b'\0' * 4)]
    assert guest.protocol._user.state.spectator == 1
    # The disc's relay record is five u32 fields followed by 750 raw bytes.
    # Keep it opaque here: this tests server forwarding, not client parsing.
    connection_info = struct.pack('!5I', 1, 2, 3, 4, 5) + bytes(range(250)) * 3
    assert len(connection_info) == 770
    assert host.send(0x4351, connection_info) == [(0x4352, b'\0' * 4)]
    assert guest.drain() == [(0x4351, connection_info)]
