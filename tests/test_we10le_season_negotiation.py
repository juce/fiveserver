"""Community extension through production framing, auth and PES6 room handlers.

Only the existing persistence/clock fixture is fake. These tests compare declared
identities; they do not attest client RAM or establish a peer-to-peer match.
"""

import struct

import pytest
from twisted.internet.error import ConnectionDone
from twisted.python.failure import Failure

from fiveserver.model import lobby, user
from fiveserver.protocol import we10le

from test_we10le_lobby_flow import (Client, enter_main, lengths, session,
                                    two_peer_room)


IDENTITY = bytes(range(32))
OTHER_IDENTITY = IDENTITY[:16] + b'edited-card-data'


def declaration(identity=IDENTITY, base=69, season=0, magic=b'W10S',
                version=3, flags=0, nonce=1):
    assert len(identity) == 32
    return struct.pack('!4sHH32sHHI', magic, version, flags, identity, base, season, nonce)


def snapshots(replies):
    result = []
    for packet_id, data in replies:
        if packet_id != we10le.SEASON_RESPONSE:
            continue
        assert len(data) == 84
        magic, version, status, identity, room_id, count = struct.unpack(
            '!4sHH32sII', data[:48])
        assert magic == b'W10S' and version == 3 and count <= 4
        entries = [struct.unpack_from('!IHH', data, 48 + i * 8)
                   for i in range(count)]
        assert data[48 + 8 * count:80] == b'\0' * (32 - count * 8)
        result.append((status, identity, room_id, entries))
    return result


def negotiate(client, other=None, **kwargs):
    client.season_nonce = getattr(client, 'season_nonce', 0) + 1
    replies = client.send(0x4f10, declaration(nonce=client.season_nonce, **kwargs))
    assert struct.unpack('!I', replies[0][1][80:84]) == (client.season_nonce,)
    reply = snapshots(replies)
    assert len(reply) == 1
    if other is not None:
        other.drain()
    return reply[0]


def participate(client, other):
    replies = client.send(0x4363, b'\x01')
    peer = other.drain()
    for who, packets in ((client, replies), (other, peer)):
        if not who.protocol._seasonCapable:
            assert snapshots(packets) == []
    ack = next(data for packet_id, data in replies if packet_id == 0x4364)
    return struct.unpack('!IBB', ack), snapshots(replies)


def matching_room(session, *, host_season=1, guest_season=0):
    host, guest, room, _, _ = two_peer_room(session)
    assert negotiate(host, guest, season=host_season)[0] == 0
    assert negotiate(guest, host, season=guest_season)[0] == 0
    assert participate(host, guest)[0] == (0, 1, 0)
    assert participate(guest, host)[0] == (0, 1, 1)
    return host, guest, room


def ready_pair(host, guest):
    host.send(0x436f, b'\x01')
    guest.drain()
    replies = guest.send(0x436f, b'\x01')
    host.drain()
    return replies


def team_selection_phase(host, guest, room):
    started = host.send(0x4360)
    assert snapshots(started)[0][0] == 0
    assert lengths([(pid, data) for pid, data in started if pid != 0x4f11]) == [
        (0x4362, 37), (0x4306, 131), (0x4361, 4)]
    guest.drain()
    assert room.phase == lobby.RoomState.ROOM_MATCH_SIDE_SELECT
    ready_pair(host, guest)
    assert room.phase == lobby.RoomState.ROOM_MATCH_SETTINGS_SELECT
    sides = (struct.pack('!i4B', 101, 0, 0, 0, 0) +
             struct.pack('!i4B', 102, 1, 0, 0, 0) + b'\0' * 16)
    host.send(0x4369, sides)
    guest.drain()
    settings = bytes([0, 30, 3, 1, 2, 1, 3, 0, 1, 0, 1, 0, 0, 0, 0, 0])
    host.send(0x436c, settings)
    guest.drain()
    ready_pair(host, guest)
    assert room.phase == lobby.RoomState.ROOM_MATCH_TEAM_SELECT


def test_authentication_bound_main_identity_echo_and_legacy_fallback(session):
    main = Client(session, we10le.MainService, 'hostid')
    denied = snapshots(main.send(0x4f10, declaration()))
    assert denied == [(4, b'\0' * 32, 0, [])]
    assert main.protocol._seasonIdentity is None
    main.authenticate()
    assert negotiate(main) == (0, IDENTITY, 0, [])
    assert main.protocol._seasonIdentity == IDENTITY
    assert main.protocol._seasonSelection == (69, 0)
    # No account hash, DB row or old RosterHash field is repurposed.
    assert session.database.accounts[0].hash == b'stored-hash-1'
    assert session.config.getUserInfo(main.protocol._user).rosterHash == b''
    main.send(0x0003, b'\0')
    main.protocol.connectionLost(Failure(ConnectionDone()))
    assert main.protocol._seasonIdentity is None
    fresh = Client(session, we10le.MainService, 'hostid')
    fresh.authenticate()
    assert not fresh.protocol._seasonCapable
    assert fresh.protocol._seasonIdentity is None


@pytest.mark.parametrize('role', [we10le.LoginService, we10le.NetworkMenuService])
def test_extension_is_main_only_and_four_zero_fallback_is_not_a_snapshot(session, role):
    client = Client(session, role, 'hostid')
    client.authenticate()
    assert 0x4f10 not in client.protocol._handlers
    replies = client.send(0x4f10, declaration())
    assert replies == [(0x4f11, b'\0' * 4)]
    with pytest.raises(AssertionError):
        snapshots(replies)


def test_matching_clients_get_recipient_first_choices_and_keep_native_team_wire(session):
    host, guest, room = matching_room(session)
    first = negotiate(host, guest, season=1)
    assert first == (0, IDENTITY, room.id, [(101, 69, 1), (102, 69, 0)])
    second = negotiate(guest, host)
    assert second == (0, IDENTITY, room.id, [(102, 69, 0), (101, 69, 1)])
    team_selection_phase(host, guest, room)
    # Identity-only agreement is insufficient while native choices are stale.
    rejected = host.send(0x436f, b'\x01')
    guest.drain()
    assert rejected[0] == (0x4370, struct.pack('!I', 2))
    assert room.readyCount == 0 and room.phase == 4
    # Original automatically follows native4373, including its untouched option.
    original = guest.send(0x4373, struct.pack('!HH', 64, 0xbeef))
    peer = host.drain()
    assert lengths(original) == [(0x4f11, 84), (0x4374, 4), (0x4306, 131)]
    assert snapshots(original)[0][0] == 0
    assert room.teamSelection.away_team_id == 64
    assert guest.protocol._seasonSelection == (64, 0)
    assert snapshots(peer)[0][3] == [(101, 69, 1), (102, 64, 0)]
    custom = host.send(0x4373, struct.pack('!HH', 69, 0x1234))
    guest.drain()
    assert custom[0][0] == 0x4f11 and snapshots(custom)[0][0] == 6
    assert custom[1] == (0x4374, b'\0' * 4)
    assert room.teamSelection.home_team_id == 69  # Never virtual296 on the wire.
    ready_pair(host, guest)
    assert room.phase == lobby.RoomState.ROOM_MATCH_STRIP_SELECT
    locked = negotiate(host, guest, season=0)
    assert locked[0] == 5 and host.protocol._seasonSelection == (69, 1)
    assert negotiate(host, guest, season=1)[0] == 6  # Fresh idempotent final polling.


def test_card_catalog_clubs_and_multiple_season_codes_finalize_without_virtual_ids(session):
    host, guest, room = matching_room(session)
    assert negotiate(host, guest, base=64, season=2011)[0] == 0
    assert negotiate(guest, host, base=203, season=65534)[0] == 0
    team_selection_phase(host, guest, room)
    first = host.send(0x4373, struct.pack('!HH', 64, 0x1234))
    guest.drain()
    assert snapshots(first)[0][0] == 0
    second = guest.send(0x4373, struct.pack('!HH', 203, 0xabcd))
    host.drain()
    assert snapshots(second)[0][0] == 6
    assert room.teamSelection.home_team_id == 64
    assert room.teamSelection.away_team_id == 203
    assert negotiate(host, guest, base=64, season=2011)[3] == [
        (101, 64, 2011), (102, 203, 65534)]
    ready_pair(host, guest)
    assert room.phase == lobby.RoomState.ROOM_MATCH_STRIP_SELECT


@pytest.mark.parametrize('modded_host', [False, True])
def test_legacy_and_mod_client_cannot_participate_together(session, modded_host):
    host, guest, room, _, _ = two_peer_room(session)
    modded, legacy = (host, guest) if modded_host else (guest, host)
    negotiate(modded, legacy)
    assert participate(host, guest)[0] == (0, 1, 0)
    ack, _ = participate(guest, host)
    assert ack == (2, 1, 0xff)
    assert room.participatingPlayers == [host.protocol._user]
    assert legacy.protocol._seasonCapable is False
    # Peers never receive an unsolicited unknown packet unless they negotiated.
    assert all(packet_id != 0x4f11 for packet_id, _ in legacy.drain())


def test_different_runtime_card_identity_is_rejected_then_matching_retry_works(session):
    host, guest, room, _, _ = two_peer_room(session)
    negotiate(host, guest)
    negotiate(guest, host, identity=OTHER_IDENTITY)
    participate(host, guest)
    assert participate(guest, host)[0] == (1, 1, 0xff)
    assert room.participatingPlayers == [host.protocol._user]
    negotiate(guest, host)
    assert participate(guest, host)[0] == (0, 1, 1)
    # A changed declaration is checked again at start, not just on joining.
    status = negotiate(guest, host, identity=OTHER_IDENTITY)[0]
    assert status == 1
    blocked = host.send(0x4360)
    guest.drain()
    assert blocked[0] == (0x4361, struct.pack('!I', 1))
    assert not any(packet_id == 0x4362 for packet_id, _ in blocked)
    assert room.phase == 1 and room.matchStarter is None
    negotiate(guest, host)
    assert any(pid == 0x4362 for pid, _ in host.send(0x4360))
    guest.drain()


@pytest.mark.parametrize('bad', [
    b'', declaration()[:-1], declaration() + b'\0',
    declaration(magic=b'NOPE'), declaration(version=2), declaration(flags=1),
    declaration(identity=b'\0' * 32), declaration(season=65535),
    declaration(base=63, season=1), declaration(base=204, season=1),
    declaration(base=296, season=0), declaration(nonce=0)])
def test_malformed_or_unsupported_declaration_revokes_old_identity_fail_closed(session, bad):
    host, guest, room = matching_room(session)
    old_selection = host.protocol._seasonSelection
    replies = host.send(0x4f10, bad)
    peer = guest.drain()
    assert snapshots(replies)[0][0:2] == (3, b'\0' * 32)
    assert len(snapshots(replies)) == 1
    assert snapshots(peer)[0][0] == 2
    assert host.protocol._seasonCapable and host.protocol._seasonIdentity is None
    assert host.protocol._seasonSelection == old_selection
    denied = guest.send(0x4360)
    host.drain()
    assert denied[0] == (0x4361, struct.pack('!I', 2))
    assert room.phase == 1


def test_changed_submitted_choice_requires_fresh_native_team_confirmation_before_final(session):
    host, guest, room = matching_room(session)
    team_selection_phase(host, guest, room)
    bad = host.send(0x4373, struct.pack('!HH', 64, 0))
    guest.drain()
    assert bad[0] == (0x4374, struct.pack('!I', 1))
    assert room.teamSelection.home_team_id is None
    host.send(0x4373, struct.pack('!HH', 69, 0))
    guest.drain()
    assert host.protocol._seasonSubmitted is not None
    # Same native base, new season: old native submission must not finalize it.
    negotiate(host, guest, season=0)
    assert host.protocol._seasonSubmitted is None
    partial = guest.send(0x4373, struct.pack('!HH', 69, 0))
    host.drain()
    assert snapshots(partial)[0][0] == 0
    denied = host.send(0x436f, b'\x01')
    guest.drain()
    assert denied[0] == (0x4370, struct.pack('!I', 2))
    assert room.readyCount == 0
    assert room.phase == 4
    final = host.send(0x4373, struct.pack('!HH', 69, 0))
    peer_final = guest.drain()
    assert final[0][0] == peer_final[0][0] == 0x4f11
    assert snapshots(final)[0][0] == snapshots(peer_final)[0][0] == 6
    assert negotiate(guest, host, season=1)[0] == 5
    assert guest.protocol._seasonSelection == (69, 0)
    ready_pair(host, guest)
    assert room.phase == 5


def test_final_barrier_waits_for_both_native_requests_and_freezes_latest_peer_season(session):
    host, guest, room = matching_room(session)
    team_selection_phase(host, guest, room)
    first = host.send(0x4373, struct.pack('!HH', 69, 0))
    peer = guest.drain()
    assert snapshots(first)[0][0] == snapshots(peer)[0][0] == 0
    assert not room._we10leSeasonFinalized
    # Peer changes0->1 while native base stays69: a prior OK snapshot is not
    # final and cannot authorize preparation of the old Original roster.
    assert negotiate(guest, host, season=1)[0] == 0
    final = guest.send(0x4373, struct.pack('!HH', 69, 0))
    host_final = host.drain()
    assert final[0][0] == host_final[0][0] == 0x4f11
    assert snapshots(final)[0] == (6, IDENTITY, room.id,
                                  [(102, 69, 1), (101, 69, 1)])
    assert snapshots(host_final)[0] == (6, IDENTITY, room.id,
                                       [(101, 69, 1), (102, 69, 1)])
    assert room.phase == 4 and room._we10leSeasonFinalized
    assert negotiate(guest, host, season=0)[0] == 5
    assert guest.protocol._seasonSelection == (69, 1)


def test_fresh_nonce_echo_is_per_recipient_and_idempotent_poll_preserves_final_barrier(session):
    host, guest, room = matching_room(session)
    team_selection_phase(host, guest, room)
    for client, other in ((host, guest), (guest, host)):
        client.send(0x4373, struct.pack('!HH', 69, 0))
        other.drain()
    submitted = [client.protocol._seasonSubmitted for client in (host, guest)]
    host_reply = host.send(0x4f10, declaration(season=1, nonce=0x10002003))
    guest_reply = guest.drain()
    assert snapshots(host_reply)[0][0] == snapshots(guest_reply)[0][0] == 6
    assert struct.unpack('!I', host_reply[0][1][80:84]) == (0x10002003,)
    assert struct.unpack('!I', guest_reply[0][1][80:84]) == (guest.season_nonce,)
    guest_reply = guest.send(0x4f10, declaration(nonce=0xffffffff))
    host_reply = host.drain()
    assert struct.unpack('!I', guest_reply[0][1][80:84]) == (0xffffffff,)
    assert struct.unpack('!I', host_reply[0][1][80:84]) == (0x10002003,)
    assert [client.protocol._seasonSubmitted for client in (host, guest)] == submitted
    assert room._we10leSeasonFinalized


def test_rematch_clears_previous_round_native_submissions_even_with_same_base_ids(session):
    host, guest, room = matching_room(session)
    team_selection_phase(host, guest, room)
    for client, other in ((host, guest), (guest, host)):
        client.send(0x4373, struct.pack('!HH', 69, 0))
        other.drain()
    for phase in (5, 6, 7):
        ready_pair(host, guest)
        assert room.phase == phase
    host.send(0x4377, bytes([lobby.MatchState.FIRST_HALF]))
    guest.drain()
    host.send(0x4377, bytes([lobby.MatchState.FINISHED]))
    guest.drain()
    assert room.phase == 8
    rematch = host.send(0x436f, b'\x03')
    peer = guest.drain()
    assert snapshots(rematch)[0][0] == snapshots(peer)[0][0] == 0
    assert room.phase == 4 and not room._we10leSeasonFinalized
    assert host.protocol._seasonSubmitted is guest.protocol._seasonSubmitted is None
    # Old room.teamSelection still contains69/69, but cannot satisfy barrier.
    assert room.teamSelection.home_team_id == room.teamSelection.away_team_id == 69
    host.send(0x4373, struct.pack('!HH', 69, 0))
    guest.drain()
    denied = host.send(0x436f, b'\x01')
    guest.drain()
    assert denied[0] == (0x4370, struct.pack('!I', 2))
    assert room.phase == 4 and room.readyCount == 0
    final = guest.send(0x4373, struct.pack('!HH', 69, 0))
    host.drain()
    assert snapshots(final)[0][0] == 6


@pytest.mark.parametrize('revoke_identity', [False, True])
def test_same_teams_rematch_reuses_only_current_frozen_agreement_with_fresh_nonce(session, revoke_identity):
    host, guest, room = matching_room(session)
    team_selection_phase(host, guest, room)
    for client, other in ((host, guest), (guest, host)):
        client.send(0x4373, struct.pack('!HH', 69, 0))
        other.drain()
    for phase in (5, 6, 7):
        ready_pair(host, guest)
        assert room.phase == phase
    host.send(0x4377, bytes([lobby.MatchState.FIRST_HALF]))
    guest.drain()
    host.send(0x4377, bytes([lobby.MatchState.FINISHED]))
    guest.drain()
    assert room.phase == 8
    submitted = [client.protocol._seasonSubmitted for client in (host, guest)]
    if revoke_identity:
        guest.send(0x4f10, declaration(version=99))
        host.drain()
        denied = host.send(0x436f, b'\x04')
        guest.drain()
        assert denied[0] == (0x4370, struct.pack('!I', 2))
        assert room.phase == 8
        return
    for client, other in ((host, guest), (guest, host)):
        client.send(0x436f, b'\x04')
        other.drain()
    assert room.phase == 6 and room._we10leSeasonFinalized
    assert [client.protocol._seasonSubmitted for client in (host, guest)] == submitted
    assert negotiate(host, guest, season=1)[0] == 6
    assert negotiate(guest, host, season=0)[0] == 6
    ready_pair(host, guest)
    assert room.phase == 7


def test_leaving_and_disconnecting_remove_peer_snapshots_and_stale_room_choice(session):
    host, guest, room = matching_room(session)
    leaving = guest.send(0x432a)
    peer = host.drain()
    assert snapshots(leaving)[0] == (0, IDENTITY, 0, [])
    assert snapshots(peer)[0][3] == [(101, 69, 1)]
    assert room.participatingPlayers == [host.protocol._user]
    assert guest.protocol._seasonSelection == (0xffff, 0)
    assert guest.protocol._seasonIdentity == IDENTITY
    single = host.send(0x4360)
    assert single[0] == (0x4361, struct.pack('!I', 2))
    assert room.phase == 1
    host.protocol.connectionLost(Failure(ConnectionDone()))
    guest.drain()
    assert not host.protocol._seasonCapable
    assert host.protocol._seasonIdentity is None
    assert room.participatingPlayers == [] and room.players == []
    assert session.config.lobbies[0].rooms == {}


def test_legacy_room_start_remains_the_shared_protocol_without_extension_notifications(session):
    host, guest, room, _, _ = two_peer_room(session)
    assert participate(host, guest)[0] == (0, 1, 0)
    assert participate(guest, host)[0] == (0, 1, 1)
    replies = host.send(0x4360)
    assert snapshots(replies) == [] and snapshots(guest.drain()) == []
    assert lengths(replies) == [(0x4362, 37), (0x4306, 131), (0x4361, 4)]
    assert room.phase == 2


def test_original_team_cannot_change_after_kit_selection_or_hide_stale_snapshot(session):
    host, guest, room = matching_room(session)
    team_selection_phase(host, guest, room)
    for client, other in ((host, guest), (guest, host)):
        client.send(0x4373, struct.pack('!HH', 69, 0))
        other.drain()
    ready_pair(host, guest)
    rejected = guest.send(0x4373, struct.pack('!HH', 64, 0))
    host.drain()
    assert rejected[0] == (0x4374, struct.pack('!I', 5))
    assert guest.protocol._seasonSelection == (69, 0)
    assert room.teamSelection.away_team_id == 69 and room.phase == 5


def test_forced_cancellation_updates_both_views_and_does_not_leave_stale_agreement(session):
    host, guest, room = matching_room(session)
    replies = host.send(0x4380, struct.pack('!i', 102))
    peer = guest.drain()
    assert snapshots(replies)[0][3] == [(101, 69, 1)]
    assert snapshots(peer)[0][3] == []
    assert room.participatingPlayers == [host.protocol._user]
    denied = host.send(0x4360)
    guest.drain()
    assert denied[0] == (0x4361, struct.pack('!I', 2))


def extra_main(session, number):
    account = user.User(('stored-hash-%d' % number).encode('ascii'))
    account.id = number
    account.username = 'extra%d' % number
    profile = user.Profile(0)
    profile.id = 100 + number
    profile.userId = number
    profile.name = 'Player_%d' % number
    session.database.accounts.append(account)
    session.database.profiles.append(profile)
    client = Client(session, we10le.MainService, account.username)
    client.authenticate()
    client.send(0x4100, b'\0\x22\x33')
    client.send(0x4200, b'\0')
    ip = ('192.0.2.%d' % number).encode('ascii').ljust(16, b'\0')
    client.send(0x4202, b'\0' + ip + struct.pack('!H', 3658) +
                ip + struct.pack('!HH', 3658, 0))
    return client


@pytest.mark.parametrize('modded_observer', [False, True])
@pytest.mark.parametrize('departure', ['room-exit', 'disconnect', 'logout', 'forced-cancel'])
def test_spectator_departure_preserves_final_agreement_and_ready_state(
        session, modded_observer, departure):
    host, guest, room = matching_room(session)
    observer = extra_main(session, 3)
    host.drain()
    guest.drain()
    observer.send(0x4320, struct.pack('!i', room.id) + b'\0' * 16)
    host.drain()
    guest.drain()
    if modded_observer:
        negotiate(observer)
        host.drain()
        guest.drain()
    assert observer.protocol._user not in room.participatingPlayers
    team_selection_phase(host, guest, room)
    for client, other in ((host, guest), (guest, host)):
        client.send(0x4373, struct.pack('!HH', 69, 0))
        other.drain()
    submitted = [client.protocol._seasonSubmitted for client in (host, guest)]
    host.send(0x436f, b'\x01')
    guest.drain()
    observer.drain()
    assert room._we10leSeasonFinalized and room.readyCount == 1

    if departure == 'room-exit':
        observer.send(0x432a)
    elif departure == 'forced-cancel':
        host.send(0x4380, struct.pack('!i', 103))
    else:
        if departure == 'logout':
            observer.send(0x0003, b'\0')
        observer.protocol.connectionLost(Failure(ConnectionDone()))
    host.drain()
    guest.drain()
    observer.drain()

    assert room.participatingPlayers == [host.protocol._user, guest.protocol._user]
    assert room._we10leSeasonFinalized and room.readyCount == 1
    assert [client.protocol._seasonSubmitted for client in (host, guest)] == submitted
    assert negotiate(host, guest, season=1)[0] == we10le.SEASON_FINAL
    assert negotiate(guest, host, season=0)[0] == we10le.SEASON_FINAL
    # The other participant can finish readying without resubmitting4373.
    guest.send(0x436f, b'\x01')
    host.drain()
    assert room.phase == lobby.RoomState.ROOM_MATCH_STRIP_SELECT


@pytest.mark.parametrize('departure', ['room-exit', 'disconnect', 'logout', 'forced-cancel'])
def test_actual_participant_departure_revokes_final_agreement(session, departure):
    host, guest, room = matching_room(session)
    team_selection_phase(host, guest, room)
    for client, other in ((host, guest), (guest, host)):
        client.send(0x4373, struct.pack('!HH', 69, 0))
        other.drain()
    host.send(0x436f, b'\x01')
    guest.drain()
    assert room._we10leSeasonFinalized and room.readyCount == 1
    if departure == 'room-exit':
        guest.send(0x432a)
    elif departure == 'forced-cancel':
        host.send(0x4380, struct.pack('!i', 102))
    else:
        if departure == 'logout':
            guest.send(0x0003, b'\0')
        guest.protocol.connectionLost(Failure(ConnectionDone()))
    host.drain()
    guest.drain()
    assert room.participatingPlayers == [host.protocol._user]
    assert not room._we10leSeasonFinalized and room.readyCount == 0
    assert host.protocol._seasonSubmitted is None
    assert negotiate(host, season=1)[0] != we10le.SEASON_FINAL


@pytest.mark.parametrize('mode', ['legacy', 'season', 'late'])
def test_v2_season_participation_is_exactly_two_while_legacy_four_remains_compatible(session, mode):
    host, guest, room, _, _ = two_peer_room(session)
    clients = [host, guest]
    for number in (3, 4):
        extra = extra_main(session, number)
        for existing in clients:
            existing.drain()
        extra.send(0x4320, struct.pack('!i', room.id) + b'\0' * 16)
        for existing in clients:
            existing.drain()
        clients.append(extra)
    if mode == 'season':
        for client in clients:
            negotiate(client, season=1)
            for other in clients:
                if other is not client:
                    other.drain()
    for index in range(4):
        selected = clients[index]
        replies = selected.send(0x4363, b'\x01')
        ack = next(data for packet_id, data in replies if packet_id == 0x4364)
        assert struct.unpack('!IBB', ack) == (
            (3, 1, 0xff) if mode == 'season' and index >= 2 else (0, 1, index))
        for other in clients:
            if other is not selected:
                other.drain()
    if mode == 'season':
        assert room.participatingPlayers == [c.protocol._user for c in clients[:2]]
        for index, client in enumerate(clients):
            snapshot = negotiate(client, season=1)
            for other in clients:
                if other is not client:
                    other.drain()
            expected = ([(101 + index, 69, 1), (102 - index, 69, 1)]
                        if index < 2 else [])
            assert snapshot == (0, IDENTITY, room.id, expected)
    elif mode == 'legacy':
        assert len(room.participatingPlayers) == 4
        assert host.send(0x4360)[0][0] == 0x4362
        for other in clients:
            if other is not host:
                other.drain()
        assert room.phase == 2
    else:
        # Adding v2 negotiation to an existing four-person set cannot bypass
        # the start recheck. The fixed four-entry response is error capacity.
        snapshot = negotiate(host, season=1)
        for other in clients[1:]:
            other.drain()
        assert snapshot[0] == 3 and len(snapshot[3]) == 4
        denied = host.send(0x4360)
        for other in clients[1:]:
            other.drain()
        assert denied[0] == (0x4361, struct.pack('!I', 3)) and room.phase == 1
