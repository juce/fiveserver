"""Wire-level regressions for the statically researched Korean PS2 adapter.

The fixtures construct frames independently of fiveserver's serializer and use
real Twisted transports/Deferreds and real PyCryptodome Blowfish.
"""

import binascii
from datetime import timedelta
from hashlib import md5
import struct
from types import SimpleNamespace

import pytest
from Crypto.Cipher import Blowfish
from twisted.internet import defer
from twisted.internet.address import IPv4Address
from twisted.internet.error import ConnectionDone
from twisted.internet.testing import StringTransport
from twisted.python.failure import Failure

from fiveserver import errors
from fiveserver.config import FiveServerConfig
from fiveserver.model import user
from fiveserver.model.util import PacketFormatter
from fiveserver.protocol import PacketServiceFactory, pes6, we10le


CIPHER_KEY = bytes.fromhex(
    '27501fd04e6b82c831024dac5c6305221974deb9388a2190'
    '1d576cbbe2f377ef23d75486010f37819afe6c321a0146d2'
    '1544ec365bf7289a')
XOR_KEY = bytes.fromhex('a677957c')
USERNAME = 'koreatest'
PASSWORD = 'football'


def xor_bytes(data):
    return bytes(value ^ XOR_KEY[index % 4]
                 for index, value in enumerate(data))


def request_frame(packet_id, data=b'', count=1):
    header = struct.pack('!HHI', packet_id, len(data), count)
    return xor_bytes(header + md5(header + data).digest() + data)


def response_frames(data):
    """Decode independent frames, checking checksums and declared lengths."""
    replies = []
    while data:
        assert len(data) >= 24
        header = xor_bytes(data[:8])
        packet_id, length, count = struct.unpack('!HHI', header)
        assert len(data) >= length + 24
        raw = xor_bytes(data[:length + 24])
        assert raw[8:24] == md5(raw[:8] + raw[24:]).digest()
        replies.append((packet_id, raw[24:], count))
        data = data[length + 24:]
    return replies


def encrypted_auth(username=USERNAME, password=PASSWORD,
                   challenge=b'\0' * 16):
    username_bytes = username.encode('ascii')
    digest = md5(username_bytes + challenge + password.encode('ascii')).digest()
    # The disc builds58 bytes then zero-pads to eight-byte Blowfish blocks.
    plain = username_bytes.ljust(32, b'\0') + digest + b'\0\x01' + b'PS2TEST!' + b'\0' * 6
    assert len(plain) == 64
    return Blowfish.new(CIPHER_KEY, Blowfish.MODE_ECB).encrypt(plain)


class FakeConfiguration:
    def __init__(self):
        self.serverConfig = SimpleNamespace(
            Debug=False, ShowStats=True, AuthMode='password',
            GamePorts={'we10le': 10881},
            NetworkServer={'mainService': 20210, 'networkMenuService': 20211,
                           'loginService': {'we10le': 20212}},
            Roster={'enforceHash': False, 'compareHash': False})
        self.configuration = self
        self.serverIP_wan = '192.0.2.15'
        self.VERSION = 'test'
        self.cipherKey = CIPHER_KEY.hex()
        self.onlineUsers = {}
        self.infos = {}
        self.lookups = []
        self.profile_stats = user.Stats(101, 7, 3, 2, 25, 11, 4, 6)
        self.profileLogic = SimpleNamespace(
            getStats=lambda profile_id: defer.succeed(self.profile_stats))
        self.matchData = SimpleNamespace(getGames=lambda profile_id: defer.succeed(12))
        self.ratingMath = SimpleNamespace(getDivision=lambda points: 2)
        account_hash = binascii.hexlify(encrypted_auth()[32:48])
        self.account = user.User(account_hash)
        self.account.username = USERNAME
        self.account.id = 1
        self.account.profiles = [user.Profile(index) for index in range(3)]
        profile = self.account.profiles[0]
        profile.id = 101
        profile.name = 'Korean Profile With More Than Sixteen Letters'
        profile.points = 1234
        profile.disconnects = 5
        profile.rank = 9
        profile.rating = 876
        profile.playTime = timedelta(seconds=3600)
        profile.comment = 'Profile test comment'

    def isBanned(self, address):
        return False

    def atCapacity(self):
        return False

    def getUser(self, account_hash):
        self.lookups.append(account_hash)
        if account_hash != self.account.hash:
            return defer.fail(errors.UnknownUserError('unknown test account'))
        return defer.succeed(self.account)

    def isUserOnline(self, account):
        return account.hash in self.onlineUsers

    def userOnline(self, account):
        self.onlineUsers[account.hash] = account

    def userOffline(self, account):
        if account is not None:
            self.onlineUsers.pop(account.hash, None)

    def setUserInfo(self, account, info):
        self.infos[account.username] = info

    def getNumUsersOnline(self):
        return len(self.onlineUsers)


def connected(protocol_class=we10le.LoginService, config=None, port=20212):
    config = config or FakeConfiguration()
    factory = PacketServiceFactory(config)
    factory.protocol = protocol_class
    peer = IPv4Address('TCP', '192.0.2.44', 45000)
    protocol = factory.buildProtocol(peer)
    transport = StringTransport(
        hostAddress=IPv4Address('TCP', '192.0.2.15', port),
        peerAddress=peer)
    protocol.makeConnection(transport)
    return protocol, transport, config


def exchange(protocol, transport, packet_id, data=b''):
    transport.clear()
    protocol.dataReceived(request_frame(packet_id, data))
    return response_frames(transport.value())


def assert_reply(replies, packet_id, data):
    assert len(replies) == 1
    assert replies[0][:2] == (packet_id, data)


def test_fragmented_challenge_and_coalesced_ps2_auth_use_real_wire_frames():
    protocol, transport, config = connected()
    challenge = request_frame(0x3001)
    protocol.dataReceived(challenge[:5])
    assert transport.value() == b''
    protocol.dataReceived(challenge[5:19])
    assert transport.value() == b''
    protocol.dataReceived(challenge[19:] + request_frame(0x3f01, encrypted_auth(), 2))
    replies = response_frames(transport.value())
    assert replies == [(0x3002, b'\0' * 16, 1), (0x3f02, b'\0' * 4, 2)]
    assert protocol._user is config.account
    assert config.onlineUsers[config.account.hash] is config.account
    assert config.lookups == [config.account.hash]
    assert config.infos[USERNAME].gameName == 'we10le'
    assert config.infos[USERNAME].rosterHash == b''


@pytest.mark.parametrize('protocol_class', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
def test_all_services_register_ps2_auth_instead_of_pc_auth(protocol_class):
    protocol, transport, config = connected(protocol_class)
    assert protocol.gameName == 'we10le'
    assert 0x3f01 in protocol._handlers
    assert 0x3003 not in protocol._handlers
    assert_reply(exchange(protocol, transport, 0x3001), 0x3002, b'\0' * 16)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth()),
                 0x3f02, b'\0' * 4)
    assert protocol._user is config.account


@pytest.mark.parametrize('auth_data', [b'', b'bad', b'\0' * 63, b'\0' * 65])
def test_wrong_auth_length_is_rejected_without_database_lookup(auth_data):
    protocol, transport, config = connected()
    assert_reply(exchange(protocol, transport, 0x3f01, auth_data),
                 0x3f02, struct.pack('!I', 0xffffff10))
    assert protocol._user is None
    assert config.lookups == []
    assert not config.onlineUsers


def test_wrong_password_rejected_without_marking_user_online():
    protocol, transport, config = connected()
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth(password='incorrect')),
                 0x3f02, struct.pack('!I', 0xffffff10))
    assert protocol._user is None
    assert not config.onlineUsers


def test_ciphertext_digest_cannot_be_replayed_under_another_username():
    protocol, transport, config = connected()
    # ECB lets the username blocks be substituted independently of the digest.
    # Verify the clear username is also bound to the returned account.
    cipher = Blowfish.new(CIPHER_KEY, Blowfish.MODE_ECB)
    plain = cipher.decrypt(encrypted_auth())
    forged = cipher.encrypt(b'another-user'.ljust(32, b'\0') + plain[32:])
    assert_reply(exchange(protocol, transport, 0x3f01, forged),
                 0x3f02, struct.pack('!I', 0xffffff10))
    assert config.lookups == [config.account.hash]
    assert protocol._user is None
    assert not config.onlineUsers


def test_non_ascii_auth_username_is_rejected_without_lookup():
    protocol, transport, config = connected()
    cipher = Blowfish.new(CIPHER_KEY, Blowfish.MODE_ECB)
    plain = cipher.decrypt(encrypted_auth())
    invalid = cipher.encrypt(b'\xff' + plain[1:])
    assert_reply(exchange(protocol, transport, 0x3f01, invalid),
                 0x3f02, struct.pack('!I', 0xffffff10))
    assert not config.lookups


def test_duplicate_login_does_not_overwrite_an_online_session():
    config = FakeConfiguration()
    config.userOnline(config.account)
    protocol, transport, _ = connected(config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth()),
                 0x3f02, struct.pack('!I', 0xffffff11))
    assert protocol._user is None
    assert config.onlineUsers[config.account.hash] is config.account


def test_profile_selection_3042_matches_ps2_offsets_without_rating():
    protocol, transport, config = connected()
    protocol._user = config.account
    replies = exchange(protocol, transport, 0x3040, struct.pack('!i', 101))
    assert len(replies) == 1
    packet_id, payload, _ = replies[0]
    assert packet_id == 0x3042
    assert len(payload) == 396
    assert payload[:4] == b'\0' * 4
    profile = config.account.profiles[0]
    assert payload[4:52] == profile.name.encode('ascii').ljust(48, b'\0')
    assert payload[52:105] == b'\0' * 53
    assert payload[105] == 2
    assert struct.unpack_from('!i', payload, 106) == (1234,)
    assert struct.unpack_from('!7H', payload, 110) == (12, 7, 3, 2, 4, 6, 5)
    assert struct.unpack_from('!ii', payload, 124) == (25, 11)
    assert payload[132:388] == profile.comment.encode('ascii').ljust(256, b'\0')
    assert struct.unpack_from('!i', payload, 388) == (9,)
    assert payload[392:396] == b'\0' * 4
    assert protocol._user.profile is profile


def test_unknown_profile_selection_returns_ps2_error_message():
    protocol, transport, config = connected()
    protocol._user = config.account
    assert_reply(exchange(protocol, transport, 0x3040, struct.pack('!i', 999)),
                 0x3042, struct.pack('!I', 0xfffffefc))


@pytest.mark.parametrize('protocol_class', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
def test_profile_list_3012_has_48_byte_names_and_66_byte_records(protocol_class):
    protocol, transport, config = connected(protocol_class)
    protocol._user = config.account
    replies = exchange(protocol, transport, 0x3010)
    assert len(replies) == 1
    packet_id, payload, _ = replies[0]
    assert packet_id == 0x3012
    assert len(payload) == 4 + 3 * 66
    assert payload[:4] == b'\0' * 4
    assert payload[4] == 0
    assert struct.unpack_from('!i', payload, 5) == (101,)
    assert payload[9:57] == config.account.profiles[0].name.encode().ljust(48, b'\0')
    assert struct.unpack_from('!IBiHH', payload, 57) == (3600, 2, 1234, 876, 12)


@pytest.mark.parametrize('request_id,response_id,length', [
    (0x3050, 0x3052, 75), (0x3060, 0x3062, 4)])
def test_empty_optional_profile_replies_match_client_read_lengths(request_id, response_id, length):
    protocol, transport, _ = connected()
    assert_reply(exchange(protocol, transport, request_id, b'\0' * 4),
                 response_id, b'\0' * length)


def test_binary_gate_serverlist_contains_three_61_byte_records():
    protocol, transport, config = connected(we10le.NewsProtocol, port=10881)
    replies = exchange(protocol, transport, 0x2005, b'\0')
    assert [reply[0] for reply in replies] == [0x2002, 0x2003, 0x2004]
    assert [reply[2] for reply in replies] == [1, 2, 3]
    payload = replies[1][1]
    assert len(payload) == 3 * 61
    records = [payload[index:index + 61] for index in range(0, len(payload), 61)]
    decoded = []
    for record in records:
        server_id, service_type = struct.unpack_from('!ii', record)
        name = record[8:40].split(b'\0', 1)[0]
        address = record[40:55].split(b'\0', 1)[0]
        port, players, service_code = struct.unpack_from('!HHH', record, 55)
        assert server_id == -1
        assert address == config.serverIP_wan.encode('ascii')
        assert players == 0
        assert service_type == service_code
        decoded.append((service_type, name, port))
    assert decoded == [(2, b'LOGIN', 20212), (3, b'WE10LE Korea', 20210),
                       (8, b'NETWORK_MENU', 20211)]


@pytest.mark.parametrize('trace_setting', [None, False])
def test_protocol_trace_is_opt_in(trace_setting, monkeypatch):
    messages = []
    monkeypatch.setattr(we10le.log, 'msg', messages.append)
    config = FakeConfiguration()
    if trace_setting is not None:
        config.serverConfig.TraceProtocol = trace_setting
    protocol, transport, _ = connected(config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth()),
                 0x3f02, b'\0' * 4)
    assert not any(message.startswith('WE10LE TRACE') for message in messages)


@pytest.mark.parametrize('protocol_class', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
def test_safe_trace_records_metadata_and_accepts_pad_password(protocol_class, monkeypatch):
    messages = []
    monkeypatch.setattr(we10le.log, 'msg', messages.append)

    def raw_formatter_forbidden(*args, **kwargs):
        pytest.fail('Safe protocol tracing called the legacy raw packet formatter')

    monkeypatch.setattr(PacketFormatter, 'format', raw_formatter_forbidden)
    config = FakeConfiguration()
    config.serverConfig.TraceProtocol = True
    config.serverConfig.Debug = True  # Safe trace must still suppress raw logging.
    pad_password = 'ABCDEFGHIJKL'
    auth = encrypted_auth(password=pad_password)
    config.account.hash = binascii.hexlify(auth[32:48])
    protocol, transport, _ = connected(protocol_class, config=config)
    assert_reply(exchange(protocol, transport, 0x3001), 0x3002, b'\0' * 16)
    assert_reply(exchange(protocol, transport, 0x3f01, auth), 0x3f02, b'\0' * 4)
    events = [message.split(' ', 3)[3] for message in messages]
    assert events == [
        'CONNECT service=%s port=20212' % protocol_class.__name__,
        'RECV id=0x3001 length=0', 'SEND id=0x3002 length=16',
        'RECV id=0x3f01 length=64', 'AUTH outcome=accepted',
        'SEND id=0x3f02 length=4',
    ]
    assert len({message.split(' ', 3)[2] for message in messages}) == 1
    rendered = '\n'.join(messages)
    for secret in [USERNAME, pad_password, auth.hex(), config.account.hash.decode(),
                   CIPHER_KEY.hex(), 'PS2TEST!']:
        assert secret not in rendered


@pytest.mark.parametrize('outcome', [
    'invalid_length', 'non_ascii', 'unknown_account',
    'username_mismatch', 'already_online'])
def test_safe_trace_reports_rejections_without_credential_data(outcome, monkeypatch):
    messages = []
    monkeypatch.setattr(we10le.log, 'msg', messages.append)
    config = FakeConfiguration()
    config.serverConfig.TraceProtocol = True
    auth = encrypted_auth()
    if outcome == 'invalid_length':
        auth = b'secret-invalid-payload'
    elif outcome == 'unknown_account':
        auth = encrypted_auth(password='secret-wrong-password')
    elif outcome in ('non_ascii', 'username_mismatch'):
        cipher = Blowfish.new(CIPHER_KEY, Blowfish.MODE_ECB)
        plain = cipher.decrypt(auth)
        replacement = (b'\xff' + plain[1:32] if outcome == 'non_ascii'
                       else b'secret-other-user'.ljust(32, b'\0'))
        auth = cipher.encrypt(replacement + plain[32:])
    elif outcome == 'already_online':
        config.userOnline(config.account)
    protocol, transport, _ = connected(config=config)
    status = 0xffffff11 if outcome == 'already_online' else 0xffffff10
    assert_reply(exchange(protocol, transport, 0x3f01, auth),
                 0x3f02, struct.pack('!I', status))
    assert [message.split(' ', 3)[3] for message in messages] == [
        'CONNECT service=LoginService port=20212',
        'RECV id=0x3f01 length=%d' % len(auth),
        'AUTH outcome=%s' % outcome, 'SEND id=0x3f02 length=4',
    ]
    rendered = '\n'.join(messages)
    for secret in [USERNAME, PASSWORD, config.account.hash.decode(), auth.hex(),
                   'secret-invalid-payload', 'secret-wrong-password', 'secret-other-user']:
        assert secret not in rendered


def test_safe_trace_preserves_heartbeat_and_logs_pre_auth_close(monkeypatch):
    messages = []
    monkeypatch.setattr(we10le.log, 'msg', messages.append)
    config = FakeConfiguration()
    config.serverConfig.TraceProtocol = True
    protocol, transport, _ = connected(we10le.MainService, config=config)
    payload = b'private-heartbeat-data'
    assert_reply(exchange(protocol, transport, 0x0005, payload), 0x0005, payload)
    protocol.connectionLost(Failure(ConnectionDone()))
    events = [message.split(' ', 3)[3] for message in messages
              if message.startswith('WE10LE TRACE')]
    assert events == [
        'CONNECT service=MainService port=20212',
        'RECV id=0x0005 length=22', 'SEND id=0x0005 length=22', 'CLOSE',
    ]
    assert payload.decode() not in '\n'.join(messages)


def username_configuration(profile_count=0, auth_mode='username'):
    """Use the real config lookup/hydration with only repository reads faked."""
    config = FakeConfiguration()
    if auth_mode is None:
        del config.serverConfig.AuthMode
    else:
        config.serverConfig.AuthMode = auth_mode
    config.account.profiles = []
    database_profiles = []
    for index in range(profile_count):
        profile = user.Profile(index)
        profile.id = 101 + index
        profile.userId = config.account.id
        profile.name = 'Korea_%d' % index
        database_profiles.append(profile)
    config.username_lookups = []
    config.profile_reads = []

    def find_by_username(username):
        config.username_lookups.append(username)
        # Simulate a case-insensitive database collation. The actual config
        # method must still enforce the exact spelling of the registered ID.
        accounts = ([config.account] if username.casefold() == USERNAME.casefold()
                    else [])
        return defer.succeed(accounts)

    def get_profiles(account_id):
        config.profile_reads.append(account_id)
        return defer.succeed(database_profiles)

    config.userData = SimpleNamespace(findByUsername=find_by_username)
    config.profileData = SimpleNamespace(getByUserId=get_profiles)
    config.getUserByUsername = lambda name: FiveServerConfig.getUserByUsername(config, name)
    config._hydrateUserProfiles = lambda account: FiveServerConfig._hydrateUserProfiles(config, account)
    return config


@pytest.mark.parametrize('protocol_class', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
@pytest.mark.parametrize('profile_count', [0, 3])
@pytest.mark.parametrize('auth_mode', [None, 'username'])
def test_username_mode_ignores_digest_but_restores_registered_account(
        protocol_class, profile_count, auth_mode, monkeypatch):
    messages = []
    monkeypatch.setattr(we10le.log, 'msg', messages.append)
    config = username_configuration(profile_count, auth_mode)
    config.serverConfig.TraceProtocol = True
    config.serverConfig.Debug = True
    stored_hash = config.account.hash
    different_password = 'LLLLLLLLLLLL'
    auth = encrypted_auth(password=different_password)
    assert binascii.hexlify(auth[32:48]) != stored_hash
    protocol, transport, _ = connected(protocol_class, config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, auth), 0x3f02, b'\0' * 4)
    assert protocol._user is config.account
    assert config.username_lookups == [USERNAME]
    assert config.lookups == []
    assert config.profile_reads == [config.account.id]
    assert config.account.hash == stored_hash
    assert list(config.onlineUsers) == [stored_hash]
    assert [profile.index for profile in config.account.profiles] == [0, 1, 2]
    expected_ids = [101, 102, 103] if profile_count else [0, 0, 0]
    assert [profile.id for profile in config.account.profiles] == expected_ids
    assert all(profile.userId == config.account.id for profile in config.account.profiles)
    replies = exchange(protocol, transport, 0x3010)
    assert len(replies) == 1 and replies[0][0] == 0x3012
    assert len(replies[0][1]) == 202
    assert [struct.unpack_from('!i', replies[0][1], 5 + i * 66)[0]
            for i in range(3)] == expected_ids
    rendered = '\n'.join(messages)
    for secret in [USERNAME, PASSWORD, different_password, stored_hash.decode(), auth.hex(), 'Korea_0']:
        assert secret not in rendered


@pytest.mark.parametrize('username', ['unregistered-id', USERNAME.upper()])
def test_username_mode_rejects_unknown_or_wrong_case_id_without_creating_account(username):
    config = username_configuration()
    stored_hash = config.account.hash
    protocol, transport, _ = connected(config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth(username=username)),
                 0x3f02, struct.pack('!I', 0xffffff10))
    assert protocol._user is None
    assert not config.onlineUsers
    assert config.username_lookups == [username]
    assert not config.profile_reads
    assert not config.lookups
    assert config.account.hash == stored_hash


@pytest.mark.parametrize('protocol_class', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
def test_username_mode_still_rejects_duplicate_session(protocol_class):
    config = username_configuration()
    stored_hash = config.account.hash
    config.userOnline(config.account)
    original_session = config.onlineUsers[stored_hash]
    protocol, transport, _ = connected(protocol_class, config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth(password='LLLLLLLLLLLL')),
                 0x3f02, struct.pack('!I', 0xffffff11))
    assert protocol._user is None
    assert config.onlineUsers == {stored_hash: original_session}
    assert config.account.hash == stored_hash


def test_password_mode_still_checks_digest_and_does_not_use_username_lookup():
    config = FakeConfiguration()
    assert config.serverConfig.AuthMode == 'password'
    config.getUserByUsername = lambda name: pytest.fail('Password mode used username-only lookup')
    stored_hash = config.account.hash
    protocol, transport, _ = connected(config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth(password='LLLLLLLLLLLL')),
                 0x3f02, struct.pack('!I', 0xffffff10))
    assert protocol._user is None and not config.onlineUsers
    assert config.account.hash == stored_hash


def test_invalid_auth_mode_does_not_fall_back_to_username_only_login():
    config = FakeConfiguration()
    config.serverConfig.AuthMode = 'invalid'
    protocol, transport, _ = connected(config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth()),
                 0x3f02, struct.pack('!I', 0xffffff10))
    assert protocol._user is None and not config.onlineUsers
    assert not config.lookups


@pytest.mark.parametrize('protocol_class', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
@pytest.mark.parametrize('tracing', [False, True])
def test_ps2_heartbeat_rebuilds_checksum_for_server_counter(protocol_class, tracing):
    config = FakeConfiguration()
    config.serverConfig.TraceProtocol = tracing
    protocol, transport, _ = connected(protocol_class, config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth()),
                 0x3f02, b'\0' * 4)
    # Two responses to one request ensure the directions' counters differ.
    replies = exchange(protocol, transport, 0x3120, b'\0' * 4)
    assert [(packet_id, payload, count) for packet_id, payload, count in replies] == [
        (0x3121, b'\0' * 4, 2), (0x3123, b'', 3)]
    transport.clear()
    payload = b'heartbeat-payload'
    protocol.dataReceived(request_frame(0x0005, payload, count=91))
    # This independent decoder verifies MD5(header+payload), not only the ID.
    assert response_frames(transport.value()) == [(0x0005, payload, 4)]
    assert protocol._count == 5
    assert not transport.disconnecting


@pytest.mark.parametrize('protocol_class', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
@pytest.mark.parametrize('tracing', [False, True])
def test_ps2_profile_transition_acknowledges_logout_before_graceful_close(
        protocol_class, tracing, monkeypatch):
    config = FakeConfiguration()
    config.serverConfig.TraceProtocol = tracing
    protocol, transport, _ = connected(protocol_class, config=config)
    assert_reply(exchange(protocol, transport, 0x3f01, encrypted_auth()),
                 0x3f02, b'\0' * 4)
    assert config.isUserOnline(config.account)
    # Preserve the existing empty-list termination order before logout.
    assert exchange(protocol, transport, 0x3120, b'\0' * 4) == [
        (0x3121, b'\0' * 4, 2), (0x3123, b'', 3)]
    close_calls = []
    original_close = transport.loseConnection

    def graceful_close():
        # The acknowledgement must already be queued when close is requested.
        close_calls.append(response_frames(transport.value()))
        original_close()

    def abort_forbidden():
        pytest.fail('PS2 logout aborted TCP before flushing its acknowledgement')

    monkeypatch.setattr(transport, 'loseConnection', graceful_close)
    monkeypatch.setattr(transport, 'abortConnection', abort_forbidden, raising=False)
    transport.clear()
    protocol.dataReceived(request_frame(0x0003, b'\0', count=91))
    expected = [(0x0004, b'\0' * 4, 4)]
    assert response_frames(transport.value()) == expected
    assert close_calls == [expected]
    assert protocol._count == 5
    assert not config.isUserOnline(config.account)
    assert transport.disconnecting


@pytest.mark.parametrize('protocol_class', [
    we10le.LoginService, we10le.NetworkMenuService, we10le.MainService])
def test_ps2_pre_auth_cancel_also_acknowledges_and_closes(protocol_class):
    protocol, transport, config = connected(protocol_class)
    assert exchange(protocol, transport, 0x0003, b'\0') == [(0x0004, b'\0' * 4, 1)]
    assert not config.onlineUsers
    assert transport.disconnecting


def test_pc_login_logout_keeps_its_original_no_ack_behavior():
    protocol, transport, config = connected(pes6.LoginService)
    protocol._user = config.account
    config.userOnline(config.account)
    assert exchange(protocol, transport, 0x0003, b'\0') == []
    assert not config.isUserOnline(config.account)
    assert not transport.disconnecting
