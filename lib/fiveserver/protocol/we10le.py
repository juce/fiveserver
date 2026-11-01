"""Experimental PS2 WE10 Liveware Evolution Korea (SLKA-25153) adapter.

Wire differences were checked against the supplied disc's netlib.ovl.
See docs/WE10LE-KR.md for evidence, setup and remaining hardware checks.
"""

import binascii
from itertools import count
import struct

from Crypto.Cipher import Blowfish
from twisted.internet import defer

from fiveserver import errors, log, stream
from fiveserver.model import lobby, user, util
from fiveserver.protocol import pes5, pes6


GAME_NAME = 'we10le'
GATE_HOST = 'gate.we10le.konami-asia.com'
GATE_PORT = 10881
_TRACE_CONNECTION_IDS = count(1)

# Community extension; native 4373's second uint16 remains untouched.
SEASON_REQUEST = 0x4f10
SEASON_RESPONSE = 0x4f11
SEASON_MAGIC = b'W10S'
SEASON_VERSION = 3
SEASON_OK = 0
SEASON_MISMATCH = 1
SEASON_MISSING_PEER = 2
SEASON_INVALID = 3
SEASON_UNAVAILABLE = 4
SEASON_LOCKED = 5
SEASON_FINAL = 6


class NewsProtocol(pes6.NewsProtocol):
    GREETING = dict(pes6.NewsProtocol.GREETING, text=(
        'WE10 Liveware Evolution Korea\r\n'
        'Experimental community server\r\n'
        'SLKA-25153 / PS2\r\n'))
    SERVER_NAME = 'WE10LE Korea'


class PS2Service:
    """Shared PS2 authentication and login replies on all three services.

    AuthMode defaults to 'username': registered IDs can log in without a
    password check. 'password' retains the original digest plus ID check.
    In that mode the client hashes username + challenge[16] + password, and
    the inherited 0x3001 handler supplies a zero challenge for the account
    store's stable encrypted digest. Bytes 58:64 are padding, not a roster
    checksum. Both modes retain the account's stored hash and profiles.
    """

    def __init__(self):
        super().__init__()
        self.gameName = GAME_NAME

    def _protocolTraceEnabled(self):
        return bool(getattr(self.factory.serverConfig, 'TraceProtocol', False))

    def _protocolTrace(self, event):
        if self._protocolTraceEnabled():
            log.msg('WE10LE TRACE conn=%d %s' % (
                self._traceConnection, event))

    def connectionMade(self):
        self._traceConnection = next(_TRACE_CONNECTION_IDS)
        self._protocolTrace('CONNECT service=%s port=%d' % (
            type(self).__name__, self.transport.getHost().port))
        return super().connectionMade()

    def connectionLost(self, reason):
        self._protocolTrace('CLOSE')
        return super().connectionLost(reason)

    def _packetReceived(self, pkt):
        tracing = self._protocolTraceEnabled()
        if not tracing and pkt.header.id != 0x0005:
            return super()._packetReceived(pkt)
        if tracing:
            self._protocolTrace('RECV id=0x%04x length=%d' % (
                pkt.header.id, len(pkt.data)))
        if pkt.header.id == 0x0005:
            # Packet caches its checksum when constructed. Reusing a received
            # packet after changing its counter would send a stale checksum.
            self.sendData(0x0005, pkt.data)
            return
        # Keep the raw Debug formatter out of the safe diagnostic path.
        return self.packetReceived(pkt)

    def send(self, pkt):
        if not self._protocolTraceEnabled():
            return super().send(pkt)
        self._protocolTrace('SEND id=0x%04x length=%d' % (
            pkt.header.id, len(pkt.data)))
        # Same framing/counter update as PacketReceiver.send, without its raw
        # Debug formatter (which includes packet contents and profile names).
        self.transport.write(stream.xorData(bytes(pkt), 0))
        self._count += 1

    def sendData(self, id, data):
        if id == 0x4101 and len(data) == 41:
            # The shared PES5 prefix ends at byte 40. PS2 also reads four
            # scalar bytes, a 48-byte group name and three trailing bytes.
            data = data.ljust(96, b'\0')
        elif id == 0x4402:
            # PS2 reads a fixed 128-byte message after the 58-byte sender
            # header, including for inherited history and system broadcasts.
            data = data[:186].ljust(186, b'\0')
        return super().sendData(id, data)

    def register(self):
        super().register()
        self._handlers.pop(0x3003, None)
        self.addHandler(0x3f01, self.authenticate_3f01)

    def defaultHandler(self, pkt):
        # Keep the shared fiveserver request/status fallback. The PS2 client
        # uses it for operations such as 308c -> 308d during lobby entry.
        return super().defaultHandler(pkt)

    @defer.inlineCallbacks
    def authenticate_3f01(self, pkt):
        if len(pkt.data) != 64:
            self._protocolTrace('AUTH outcome=invalid_length')
            self.sendData(0x3f02, struct.pack('!I', 0xffffff10))
            return
        cipher = Blowfish.new(
            binascii.unhexlify(self.factory.cipherKey), Blowfish.MODE_ECB)
        plain = cipher.decrypt(pkt.data)
        try:
            username = util.stripZeros(plain[:32]).decode('ascii')
        except UnicodeDecodeError:
            self._protocolTrace('AUTH outcome=non_ascii')
            self.sendData(0x3f02, struct.pack('!I', 0xffffff10))
            return
        auth_mode = getattr(self.factory.serverConfig, 'AuthMode', 'username')
        if auth_mode not in ('username', 'password'):
            self._protocolTrace('AUTH outcome=invalid_mode')
            self.sendData(0x3f02, struct.pack('!I', 0xffffff10))
            return
        try:
            if auth_mode == 'username':
                account = yield self.factory.getUserByUsername(username)
            else:
                account_hash = binascii.hexlify(pkt.data[32:48])
                account = yield self.factory.getUser(account_hash)
        except errors.UnknownUserError:
            self._protocolTrace('AUTH outcome=unknown_account')
            self.sendData(0x3f02, struct.pack('!I', 0xffffff10))
            return
        if not username or username != account.username:
            self._protocolTrace('AUTH outcome=username_mismatch')
            self.sendData(0x3f02, struct.pack('!I', 0xffffff10))
        elif self.factory.isUserOnline(account):
            self._protocolTrace('AUTH outcome=already_online')
            self.sendData(0x3f02, struct.pack('!I', 0xffffff11))
        else:
            self._user = account
            self.factory.userOnline(account)
            self.factory.setUserInfo(account, user.UserInfo(GAME_NAME, b''))
            self._protocolTrace('AUTH outcome=accepted')
            self.sendZeros(0x3f02, 4)

    @defer.inlineCallbacks
    def selectProfile_3040(self, pkt):
        profile_id = struct.unpack('!i', pkt.data[:4])[0]
        _, profile = self._user.getProfileById(profile_id)
        if profile is None:
            self.sendData(0x3042, struct.pack('!I', 0xfffffefc))
            return
        self._user.profile = profile
        stats = yield self.getStats(profile.id)
        if not self.factory.serverConfig.ShowStats:
            profile = self.makePristineProfile(profile)
        # 0x3042 differs from both PES5's 16-byte name and PES6's 0x4103.
        # Its seven uint16 stats do not include the rating field.
        data = b''.join([
            b'\0' * 4,
            util.padWithZeros(profile.name, 48),
            b'\0' * 4,
            b'\0' * 48,
            b'\0',
            struct.pack('!B', self.factory.ratingMath.getDivision(profile.points)),
            struct.pack('!i', profile.points),
            struct.pack('!7H',
                stats.wins + stats.losses + stats.draws,
                stats.wins, stats.losses, stats.draws,
                stats.streak_current, stats.streak_best, profile.disconnects),
            struct.pack('!ii', stats.goals_scored, stats.goals_allowed),
            util.padWithZeros(profile.comment or '', 256),
            struct.pack('!i', profile.rank),
            b'\0' * 4,                         # unknown client output field
        ])
        self.sendData(0x3042, data)

    def getProfiles_3010(self, pkt):
        # Menu/main also inherit PES5's login handlers upstream.
        return pes6.LoginService.getProfiles_3010(self, pkt)

    def do_3050(self, pkt):
        self.sendZeros(0x3052, 75)

    def do_3060(self, pkt):
        self.sendZeros(0x3062, 4)

    def disconnect_0003(self, pkt):
        super().disconnect_0003(pkt)
        # The inherited menu handler can leave early before lobby selection.
        # Logical logout must release this account on all three PS2 services.
        self.factory.userOffline(self._user)
        # This PS2 client waits for status 0004 and the login socket to close
        # before completing its profile/menu transition. loseConnection drains
        # the acknowledgement before the TCP FIN; abortConnection would not.
        self.sendZeros(0x0004, 4)
        self.transport.loseConnection()


class LoginService(PS2Service, pes6.LoginService):
    pass


class NetworkMenuService(PS2Service, pes6.NetworkMenuService):
    pass


class MainService(PS2Service, pes6.MainService):
    def __init__(self):
        super().__init__()
        self._resetSeasonNegotiation()

    def _resetSeasonNegotiation(self):
        # Connection-local declarations, never account/DB authentication data.
        self._seasonCapable = False
        self._seasonIdentity = None
        self._seasonSelection = (0xffff, 0)
        self._seasonSubmitted = None
        self._seasonNonce = 0

    def register(self):
        super().register()
        self.addHandler(SEASON_REQUEST, self.seasonSelection_4f10)

    def _seasonRoom(self):
        state = getattr(self._user, 'state', None)
        return getattr(state, 'room', None)

    @staticmethod
    def _seasonConnection(usr):
        connection = getattr(usr, 'lobbyConnection', None)
        if (isinstance(connection, MainService) and
                connection._user is usr and
                not connection.transport.disconnecting):
            return connection
        return None

    def _seasonStatus(self, players):
        connections = [self._seasonConnection(usr) for usr in players]
        if not any(c is not None and c._seasonCapable for c in connections):
            return SEASON_OK  # Legacy-to-legacy games retain shared behavior.
        if len(players) > 2:
            return SEASON_INVALID  # v1 client prepares exactly one opponent.
        if any(c is None or c._seasonIdentity is None for c in connections):
            return SEASON_MISSING_PEER
        if len({c._seasonIdentity for c in connections}) != 1:
            return SEASON_MISMATCH
        return SEASON_OK

    def _clearSeasonRound(self, room, reset_ready=True):
        if room is None:
            return
        room._we10leSeasonFinalized = False
        if reset_ready:
            room.readyCount = 0
        for usr in room.players:
            connection = self._seasonConnection(usr)
            if connection is not None:
                connection._seasonSubmitted = None

    def _seasonSubmissionsMatch(self, room):
        players = room.participatingPlayers
        if len(players) != 2 or self._seasonStatus(players) != SEASON_OK:
            return False
        selection = room.teamSelection
        if (selection is None or selection.home_captain is None or
                selection.away_captain is None or
                {selection.home_captain.id, selection.away_captain.id} !=
                {p.profile.id for p in players}):
            return False
        return all(self._seasonConnection(p)._seasonSubmitted == (
            room, self._seasonConnection(p)._seasonIdentity,
            self._seasonConnection(p)._seasonSelection) for p in players)

    def _seasonFinalized(self, room):
        return (getattr(room, '_we10leSeasonFinalized', False) and
                self._seasonSubmissionsMatch(room))

    def _sendSeasonSnapshot(self, status=None):
        if not self._seasonCapable:
            return
        room = self._seasonRoom()
        players = []
        if room is not None and self._user in room.participatingPlayers:
            players = [self._user] + sorted(
                (p for p in room.participatingPlayers if p is not self._user),
                key=lambda p: p.profile.id)
        if status is None:
            status = (SEASON_INVALID if self._seasonIdentity is None else
                      self._seasonStatus(players) if players else SEASON_OK)
            if status == SEASON_OK and players and self._seasonFinalized(room):
                status = SEASON_FINAL
        entries = []
        for usr in players[:4]:
            connection = self._seasonConnection(usr)
            base, season = ((0xffff, 0) if connection is None else
                            connection._seasonSelection)
            entries.append(struct.pack('!IHH', usr.profile.id, base, season))
        data = (struct.pack('!4sHH', SEASON_MAGIC, SEASON_VERSION, status) +
                (self._seasonIdentity or b'\0' * 32) +
                struct.pack('!II', room.id if room is not None else 0,
                            min(len(players), 4)) +
                b''.join(entries).ljust(32, b'\0') +
                struct.pack('!I', self._seasonNonce))
        self.sendData(SEASON_RESPONSE, data)

    def _broadcastSeasonSnapshots(self, room, exclude=None):
        if room is None:
            if self is not exclude:
                self._sendSeasonSnapshot()
            return
        for usr in list(room.players):
            connection = self._seasonConnection(usr)
            if connection is not None and connection is not exclude:
                connection._sendSeasonSnapshot()

    def seasonSelection_4f10(self, pkt):
        # A four-zero default ACK from an older server is not this protocol:
        # modified clients require84 bytes, magic/version, identity and nonce.
        self._seasonCapable = True
        nonce = struct.unpack('!I', pkt.data[44:48])[0] if len(pkt.data) == 48 else 0
        if nonce:
            self._seasonNonce = nonce
        if self._user is None or self.transport.disconnecting:
            self._sendSeasonSnapshot(SEASON_UNAVAILABLE)
            return
        if len(pkt.data) != 48:
            self._seasonIdentity = None
            self._seasonSubmitted = None
            self._sendSeasonSnapshot(SEASON_INVALID)
            self._broadcastSeasonSnapshots(self._seasonRoom(), exclude=self)
            return
        magic, version, flags = struct.unpack('!4sHH', pkt.data[:8])
        identity = pkt.data[8:40]
        selection = struct.unpack('!HH', pkt.data[40:44])
        if (magic != SEASON_MAGIC or version != SEASON_VERSION or flags != 0 or not nonce or
                identity == b'\0' * 32 or selection[0] > 295 or selection[1] == 65535 or
                (selection[1] and not 64 <= selection[0] <= 203)):
            self._seasonIdentity = None
            self._seasonSubmitted = None
            self._sendSeasonSnapshot(SEASON_INVALID)
            self._broadcastSeasonSnapshots(self._seasonRoom(), exclude=self)
            return
        room = self._seasonRoom()
        changed = (identity != self._seasonIdentity or
                   selection != self._seasonSelection)
        if (room is not None and changed and
                (getattr(room, '_we10leSeasonFinalized', False) or
                 lobby.RoomState.ROOM_MATCH_STRIP_SELECT <= room.phase <=
                 lobby.RoomState.ROOM_MATCH_STARTED)):
            self._sendSeasonSnapshot(SEASON_LOCKED)
            return
        self._seasonIdentity = identity
        self._seasonSelection = selection
        if changed:
            self._seasonSubmitted = None
        if changed and room is not None:
            room.readyCount = 0
        self._broadcastSeasonSnapshots(room)

    def createRoom_4310(self, pkt):
        result = super().createRoom_4310(pkt)
        self._broadcastSeasonSnapshots(self._seasonRoom())
        return result

    def joinRoom_4320(self, pkt):
        result = super().joinRoom_4320(pkt)
        self._broadcastSeasonSnapshots(self._seasonRoom())
        return result

    def toggleParticipate_4363(self, pkt):
        room = self._seasonRoom()
        previous = list(room.participatingPlayers) if room is not None else []
        if room is not None and pkt.data[:1] == b'\x01':
            candidates = list(room.participatingPlayers)
            if self._user not in candidates:
                candidates.append(self._user)
            status = self._seasonStatus(candidates)
            if status != SEASON_OK:
                self.sendData(0x4364, struct.pack(
                    '!IBB', status, 1, room.getPlayerParticipate(self._user)))
                self._broadcastSeasonSnapshots(room)
                return
        result = super().toggleParticipate_4363(pkt)
        if room is not None and room.participatingPlayers != previous:
            self._clearSeasonRound(room)
        self._broadcastSeasonSnapshots(room)
        return result

    def _seasonMatchStatus(self, room):
        players = room.participatingPlayers
        status = self._seasonStatus(players)
        if status == SEASON_OK and len(players) < 2 and any(
                (self._seasonConnection(p) is not None and
                 self._seasonConnection(p)._seasonCapable) for p in players):
            return SEASON_MISSING_PEER
        return status

    def startMatch_4360(self, pkt):
        room = self._seasonRoom()
        if room is not None:
            status = self._seasonMatchStatus(room)
            if status != SEASON_OK:
                self.sendData(0x4361, struct.pack('!I', status))
                self._broadcastSeasonSnapshots(room)
                return
            self._clearSeasonRound(room)
            self._broadcastSeasonSnapshots(room)
        return super().startMatch_4360(pkt)

    def forcedCancelParticipation_4380(self, pkt):
        room = self._seasonRoom()
        previous = list(room.participatingPlayers) if room is not None else []
        result = super().forcedCancelParticipation_4380(pkt)
        if room is not None and room.participatingPlayers != previous:
            self._clearSeasonRound(room)
        self._broadcastSeasonSnapshots(room)
        return result

    def _seasonTeamsMatch(self, room):
        selection = room.teamSelection
        if selection is None:
            return False
        for captain, base in ((selection.home_captain, selection.home_team_id),
                              (selection.away_captain, selection.away_team_id)):
            players = [p for p in room.participatingPlayers if
                       captain is not None and p.profile.id == captain.id]
            if len(players) != 1:
                return False
            connection = self._seasonConnection(players[0])
            if connection is None or connection._seasonSelection[0] != base:
                return False
        return True

    def toggleReady_436f(self, pkt):
        room = self._seasonRoom()
        previous = list(room.participatingPlayers) if room is not None else []
        if room is not None and pkt.data[:1] == b'\x01':
            status = self._seasonMatchStatus(room)
            modded = any((self._seasonConnection(p) is not None and
                          self._seasonConnection(p)._seasonCapable)
                         for p in room.participatingPlayers)
            if (status == SEASON_OK and modded and
                    lobby.RoomState.ROOM_MATCH_TEAM_SELECT <= room.phase <=
                    lobby.RoomState.ROOM_MATCH_FORMATION_SELECT and
                    (not self._seasonFinalized(room) or
                     not self._seasonTeamsMatch(room))):
                status = SEASON_MISSING_PEER
            if status != SEASON_OK:
                self.sendData(0x4370, struct.pack('!I', status))
                self._broadcastSeasonSnapshots(room)
                return
        if (room is not None and pkt.data[:1] == b'\x04' and
                room.phase > lobby.RoomState.ROOM_MATCH_FORMATION_SELECT and any(
                    self._seasonConnection(p) is not None and
                    self._seasonConnection(p)._seasonCapable
                    for p in room.participatingPlayers)):
            if not self._seasonFinalized(room) or not self._seasonTeamsMatch(room):
                self.sendData(0x4370, struct.pack('!I', SEASON_MISSING_PEER))
                self._broadcastSeasonSnapshots(room)
                return
            # Same-teams rematch explicitly reuses the frozen choices. A fresh
            # nonce poll attests this current server snapshot to the client.
        if room is not None and (
                (pkt.data[:1] == b'\x03' and
                 room.phase > lobby.RoomState.ROOM_MATCH_FORMATION_SELECT) or
                (pkt.data[:1] == b'\x01' and
                 room.phase == lobby.RoomState.ROOM_MATCH_SETTINGS_SELECT and
                 room.readyCount + 1 == len(room.participatingPlayers))):
            self._clearSeasonRound(room, reset_ready=False)
            self._broadcastSeasonSnapshots(room)
        result = super().toggleReady_436f(pkt)
        if room is not None and room.participatingPlayers != previous:
            self._clearSeasonRound(room)
            self._broadcastSeasonSnapshots(room)
        return result

    def teamSelected_4373(self, pkt):
        room = self._seasonRoom()
        if room is not None and self._seasonCapable:
            status = self._seasonMatchStatus(room)
            if self._user not in room.participatingPlayers:
                status = SEASON_UNAVAILABLE
            elif len(pkt.data) != 4 or self._seasonIdentity is None:
                status = SEASON_MISMATCH
            elif ((getattr(room, '_we10leSeasonFinalized', False) or
                   lobby.RoomState.ROOM_MATCH_STRIP_SELECT <= room.phase <=
                   lobby.RoomState.ROOM_MATCH_STARTED) and
                  struct.unpack('!H', pkt.data[:2])[0] != self._seasonSelection[0]):
                status = SEASON_LOCKED
            elif self._seasonSelection[1] == 0:
                # Vanilla club cursor movement need not call the extension.
                self._seasonSelection = (struct.unpack('!H', pkt.data[:2])[0], 0)
            elif struct.unpack('!H', pkt.data[:2])[0] != self._seasonSelection[0]:
                status = SEASON_MISMATCH
            if status != SEASON_OK:
                self.sendData(0x4374, struct.pack('!I', status))
                self._broadcastSeasonSnapshots(room)
                return
            if room.phase == lobby.RoomState.ROOM_MATCH_TEAM_SELECT:
                self._seasonSubmitted = (room, self._seasonIdentity,
                                         self._seasonSelection)
                if self._seasonSubmissionsMatch(room):
                    room._we10leSeasonFinalized = True
            # Final snapshot precedes the vanilla ACK/room update. Waiting for
            # it in native preparation does not prevent the independent TCP
            # task from flushing either player's queued4373 request.
            self._broadcastSeasonSnapshots(room)
            return super().teamSelected_4373(pkt)
        result = super().teamSelected_4373(pkt)
        self._broadcastSeasonSnapshots(room)
        return result

    def exitingRoom(self, room, usr):
        if usr in room.participatingPlayers:
            self._clearSeasonRound(room)
            room.cancelParticipation(usr)
        result = super().exitingRoom(room, usr)
        connection = self._seasonConnection(usr)
        if connection is not None:
            connection._seasonSelection = (0xffff, 0)
            connection._sendSeasonSnapshot()
        self._broadcastSeasonSnapshots(room)
        return result

    def disconnect_0003(self, pkt):
        self._resetSeasonNegotiation()
        return super().disconnect_0003(pkt)

    def connectionLost(self, reason):
        # PES6 removes participation before calling exitingRoom. Capture the
        # departure here so participant disconnects still revoke agreement,
        # while an unrelated spectator cannot reset final/ready state.
        room = self._seasonRoom()
        if room is not None and self._user in room.participatingPlayers:
            self._clearSeasonRound(room)
        self._resetSeasonNegotiation()
        # PES6's cleanup assumes authentication completed; a PS2 can leave
        # during login or after a rejected credential packet.
        if self._user is None:
            self._protocolTrace('CLOSE')
            return pes5.LoginService.connectionLost(self, reason)
        return super().connectionLost(reason)
