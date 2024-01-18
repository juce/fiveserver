"""
Protocol implementations for PES5
"""

from twisted.internet import reactor, defer
from twisted.application import service
from twisted.web import client

from datetime import datetime, timedelta
from hashlib import md5
import binascii
import struct
import time
import re
import zlib

from fiveserver.model import packet, user, lobby, util
from fiveserver.model.util import PacketFormatter
from fiveserver import log, stream, errors
from fiveserver.protocol import PacketDispatcher, isSameGame


CHAT_HISTORY_DELAY = 3  # seconds


class NewsProtocol(PacketDispatcher):

    GREETING = {
        'title': 'SYSTEM: Favaserver v%s',
        'text': ('Bienvenido -\r\n'
                 'Peron\r\n'
                 'Roman\r\n'
                 'El Indio\r\n'
                 'Maradona y Messi\r\n'
                 '\r\n'
                 'Credits:\r\n'
                 'Protocol analysis: reddwarf, juce\r\n'
                 'Server programming: juce, reddwarf')
    }

    SERVER_NAME = 'Favaserver'

    NEW_FEATURES = {}


    def _send(self, result, pkt):
        return self.send(pkt)

    def register(self):
        self.addHandler(0x2008, self.getNews_2008)
        self.addHandler(0x2005, self.getServerList_2005)
        self.addHandler(0x2006, self.getTime_2006)

    def getNews_2008(self, pkt):
        self.sendZeros(0x2009,4)
        # checked banned list
        banned = self.factory.configuration.isBanned(self.addr.host)
        if not banned:
            # check server capacity
            if not self.factory.configuration.atCapacity():
                # greetings message
                data = b'\0'*4 + b'\x01\x01'
                data += util.padWithZeros(str(datetime.utcnow()), 19)
                data += util.padWithZeros(
                    self.GREETING['title'] % self.factory.VERSION, 64)
                data += util.stripZeros(util.padWithZeros(
                    self.GREETING['text'], 512))
                self.sendData(0x200a,data)
                # whatsnew message (if applicable)
                announcement = self.NEW_FEATURES.get(self.factory.VERSION)
                if announcement:
                    title, text = announcement
                    data = b'\0'*4 + b'\x01\x01'
                    data += util.padWithZeros(str(datetime.utcnow()), 19)
                    data += util.padWithZeros(title, 64)
                    data += util.stripZeros(util.padWithZeros(text, 512))
                    self.sendData(0x200a,data)
            else:
                # server full message
                data = b'\0'*4 + b'\x01\x01'
                data += util.padWithZeros(str(datetime.utcnow()), 19)
                data += util.padWithZeros(
                    'Fiveserver (v%s)' % self.factory.VERSION, 64)
                data += util.padWithZeros(
                    'Sorry, but the server is currently at capacity.\r\n'
                    'We already have a maximum of %d users logged in,\r\n'
                    'so please come back at a later time.\r\n'
                    'Thanks.\r\n' % self.factory.getNumUsersOnline(), 512)
                self.sendData(0x200a,data)
        else:
            # sorry message
            data = b'\0'*4 + b'\x01\x01'
            data += util.padWithZeros(str(datetime.utcnow()), 19)
            data += util.padWithZeros(
                'Fiveserver (v%s)' % self.factory.VERSION, 64)
            data += util.padWithZeros(
                'Sorry, but you are currently banned\r\n'
                'from playing on this server. Please\r\n'
                'contact server administrator if you\r\n'
                'believe that there was a mistake.', 512)
            self.sendData(0x200a,data)
        self.sendZeros(0x200b,0)

    def getServerList_2005(self, pkt):
        myport = self.transport.getHost().port
        gameName = None
        for name,port in self.factory.serverConfig.GamePorts.items():
            if port == myport:
                gameName = name
                break
        serverIP = self.factory.configuration.serverIP_wan
        servers = [
            (-1,2,self.SERVER_NAME,serverIP,
             self.factory.serverConfig.NetworkServer['mainService'],
             max(0, self.factory.getNumUsersOnline()-1),2),
            (-1,3,'NETWORK_MENU',serverIP,
             self.factory.serverConfig.NetworkServer['networkMenuService'],
             0,3),
            (-1,1,'LOGIN',serverIP,
             self.factory.serverConfig.NetworkServer['loginService'][gameName],
             0,1),
        ]
        data = b''.join([b'%s%s%s%s%s%s%s' % (
                struct.pack('!i',a),
                struct.pack('!i',b),
                b'%s%s' % (name.encode('utf-8'),b'\0'*(32-len(name[:32]))),
                b'%s%s' % (ip.encode('utf-8'),b'\0'*(15-len(ip))),
                struct.pack('!H',port),
                struct.pack('!H',c),
                struct.pack('!H',d)) for a,b,name,ip,port,c,d in servers])
        self.sendZeros(0x2002,4)
        self.sendData(0x2003,data)
        self.sendZeros(0x2004,4)

    def getTime_2006(self, pkt):
        data = struct.pack('!I',int(time.time()))
        self.sendData(0x2007,data)


class LoginService(PacketDispatcher):

    def __init__(self):
        self._user = None
        self.gameName = None

    def connectionMade(self):
        PacketDispatcher.connectionMade(self)
        # check banned list
        banned = self.factory.configuration.isBanned(self.addr.host)
        if banned:
            log.msg('NOTICE: disconnecting banned IP (%s)' % self.addr.host)
            self.transport.loseConnection('this IP is banned')
        # check server capacity
        if self.factory.configuration.atCapacity():
            log.msg(
                'NOTICE: disconnecting user from IP (%s). '
                'Server is at capacity.' % self.addr.host)
            self.transport.loseConnection('server at capacity')

    def connectionLost(self, reason):
        PacketDispatcher.connectionLost(self, reason)
        if self._user:
            # user now considered OFFLINE
            self.factory.userOffline(self._user)

    @defer.inlineCallbacks
    def getStats(self, profileId):
        if self.factory.serverConfig.ShowStats:
            stats = yield self.factory.profileLogic.getStats(profileId)
        else:
            stats = yield defer.succeed(
                user.Stats(0, 0, 0, 0, 0, 0, 0, 0))
        defer.returnValue(stats)

    def do_3001(self, pkt):
        self.send(
            packet.Packet(packet.PacketHeader(
                0x3002,16,self._count),b'\0'*16))

    def checkRosterHash(self, clientRosterHash):
        try:
            enforceHash = self.factory.serverConfig.Roster['enforceHash']
        except AttributeError:
            return True
        except KeyError:
            return True
        if enforceHash:
            # heuristic to check if indeed the hash was provided:
            # if the hash has 4 zero-bytes together in it - then VERY LIKELY
            # this is not an MD5 checksum.
            if clientRosterHash.find(b'\0\0\0\0') != -1:
                return False
        return True

    @defer.inlineCallbacks
    def authenticate_3003(self, pkt):
        clientRosterHash = binascii.b2a_hex(pkt.data[48:64])
        userHash =  binascii.b2a_hex(pkt.data[32:48])
        log.msg('userHash: %s' % userHash)
        log.msg('clientRosterHash: %s' % clientRosterHash)
        
        try:
            self._user = yield self.factory.getUser(userHash)
            log.msg('This user is: {%s} (profiles: %s)' % (
                    self._user.hash,
                    ','.join([x.name for x in self._user.profiles])))
            if self.factory.isUserOnline(self._user):
                # already logged in
                log.msg('User already logged in!')
                self.sendData(0x3004,struct.pack('!I',0xffffff11))
            elif self.checkRosterHash(clientRosterHash):
                # user is now LOGGED IN
                self.factory.userOnline(self._user)
                if clientRosterHash != '':
                    self.factory.setUserInfo(
                        self._user,
                        user.UserInfo(self.gameName, clientRosterHash))
                self.sendZeros(0x3004,4)
            else:
                # server is configured to not allow players
                # without proper roster-hashes
                log.msg(
                    'Roster-hash check FAILED for user {%s, username=%s} '
                    'Disconnecting.' % (
                        self._user.hash, self._user.username))
                self.sendData(0x3004,struct.pack('!I',0xffffff12))
        except errors.UnknownUserError as info:
            # authentication error
            log.msg('UnknownUserError: %s' % info)
            self.sendData(0x3004,struct.pack('!I',0xffffff10))
        defer.returnValue(None)

    def makePristineProfile(self, profile):
        p = user.Profile(profile.index)
        p.name = profile.name
        p.id = profile.id
        return p

    @defer.inlineCallbacks
    def getProfiles_3010(self, pkt):
        if self.factory.serverConfig.ShowStats:
            results = yield defer.DeferredList([
                self.factory.matchData.getGames(
                    profile.id) for profile in self._user.profiles])
            profiles = self._user.profiles
        else:
            # hide all stats
            results = yield defer.succeed([(True, 0)
                for profile in self._user.profiles])
            profiles = [self.makePristineProfile(profile)
                for profile in self._user.profiles]
        data = b'\0'*4 + b''.join([
            b'%(index)s%(id)s%(name)s%(playTime)s'
            b'%(division)s%(points)s%(games)s' % {
                b'index':struct.pack('!B', i),
                b'id':struct.pack('!i', profile.id),
                b'name':util.padWithZeros(profile.name, 16),
                b'playTime':struct.pack('!i', int(profile.playTime.total_seconds())),
                b'division':struct.pack('!B',
                    self.factory.ratingMath.getDivision(profile.points)),
                b'points':struct.pack('!i', profile.points),
                b'games':struct.pack('!H', games)}
            for (_, games), (i, profile) in zip(
                results, enumerate(profiles))])
        self.sendData(0x3012, data)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def createProfile_3020(self, pkt):
        profileIndex = struct.unpack('!B',pkt.data[0:1])[0]  # 0-2
        playerName = util.stripZeros(pkt.data[1:])            # 16-char name
        playerName = playerName.decode('utf-8')
        profileNameExists = yield self.factory.profileNameExists(playerName)
        if profileNameExists:
            log.msg('ProfileNameExistsError: %s' % playerName)
            self.sendData(0x3022, struct.pack('!I',0xfffffefc))
        else:
            self._user.profiles[profileIndex].name = playerName
            self._user.profiles[profileIndex].points = 0
            profile = yield self.factory.storeProfile(
                self._user.profiles[profileIndex])
            self._user.profiles[profileIndex] = profile
            self.sendZeros(0x3022,4)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def deleteProfile_3030(self, pkt):
        profileIndex = struct.unpack('!B', pkt.data[0:1])[0]
        yield self.factory.deleteProfile(
            self._user.profiles[profileIndex])
        self._user.profiles[profileIndex].id = 0
        self._user.profiles[profileIndex].name = ''
        self._user.profiles[profileIndex].points = 0
        self.sendZeros(0x3032,4)
        defer.returnValue(None)

    def do_3060(self, pkt):
        #self.sendZeros(0x3062,14)
        #self.sendData(0x3062,'\0\0\0\0')
        self.sendData(0x3062,b'\0')

    def selectProfile_3040(self, pkt):
        id = struct.unpack('!i',pkt.data[0:4])[0]
        index, self._user.profile = self._user.getProfileById(id)
        if self._user.profile is None:
            log.msg('ERROR: user profile not found for id: %d', id)
            self.sendZeros(0x3041,4)
        else:
            data = b'\0'*4 + util.padWithZeros(
                self._user.profile.name, 16) + b'\0'*(0x18e-20)
            self.sendData(0x3042, data)

    def do_3050(self, pkt):
        self.sendZeros(0x3052,0x47)

    def getMatchResults_3070(self, pkt):
        self.sendZeros(0x3072,4)

    @defer.inlineCallbacks
    def askForSettings_308a(self, pkt):
        if not self.factory.isStoreSettingsEnabled():
            data = struct.pack('!I',0xfffffedd)
            self.sendData(0x3087, data)
        else:
            settings = yield self.factory.profileData.getSettings(
                self._user.profile.id)
            if settings.settings1 is None or settings.settings2 is None:
                data = struct.pack('!I',0xfffffedd)
                self.sendData(0x3087, data)
            else:
                data = b'%s%s' % (
                    b'\0\0\0\0',
                    struct.pack('!I', self._user.profile.id))
                self.sendData(0x3087, data)
                # send settings
                data = zlib.decompress(settings.settings1)
                self.sendData(0x3088, data)
                data = zlib.decompress(settings.settings2)
                self.sendData(0x3088, data)
                self.sendZeros(0x3089, 0)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def do_3087(self, pkt):
        # also sent at 'Exit match series'
        if self._user.state is not None:
            room = self._user.state.room
            if room and room.match is not None:
                # remove match reference from room data structure
                match, room.match = room.match, None
                duration = datetime.now() - match.startDatetime
                # check match exit flags
                if match.home_exit == 1 and match.away_exit == 1:
                    log.msg('MUTUAL DISCONNECT: '
                            'Team %d (%s) - Team %d (%s) %d:%d. '
                            'Match time: %s. MATCH DISREGARDED' % (
                        match.home_team_id, match.home_profile.name,
                        match.away_team_id, match.away_profile.name,
                        match.score_home, match.score_away,
                        duration))
                elif self.factory.serverConfig.Disconnects.get(
                        'CountAsLoss').get('Enabled',False) or (
                        match.home_exit is None and match.away_exit is None):
                    log.msg('MATCH FINISHED: '
                            'Team %d (%s) - Team %d (%s)  %d:%d. '
                            'Match time: %s.' % (
                        match.home_team_id, match.home_profile.name,
                        match.away_team_id, match.away_profile.name,
                        match.score_home, match.score_away,
                        duration))
                    # check if match result should be stored
                    thisLobby = self.factory.getLobbies()[
                        self._user.state.lobbyId]
                    if thisLobby.typeCode != 0x20: # no-stats
                        # record the match in DB
                        yield self.factory.matchData.store(match)
                        # update player play time
                        match.home_profile.playTime += duration
                        match.away_profile.playTime += duration
                        # re-calculate points
                        results = yield defer.DeferredList([
                            self.getStats(match.home_profile.id),
                            self.getStats(match.away_profile.id)])
                        (_,home_stats), (_,away_stats) = results
                        rm = self.factory.ratingMath
                        match.home_profile.points = rm.getPoints(home_stats)
                        match.away_profile.points = rm.getPoints(away_stats)
                        # store updated profiles
                        yield self.factory.storeProfile(match.home_profile)
                        yield self.factory.storeProfile(match.away_profile)
        yield defer.succeed(None)
        defer.returnValue(None)

    def do_3088(self, pkt):
        if pkt.data[2] == b'\3':
            # update settings
            settings1 = zlib.compress(pkt.data)
            self._user.profile.settings.settings1 = settings1
        else:
            # update settings
            settings2 = zlib.compress(pkt.data)
            self._user.profile.settings.settings2 = settings2

    @defer.inlineCallbacks
    def do_3089(self, pkt):
        self.sendZeros(0x308b,4)
        if self.factory.isStoreSettingsEnabled():
            # store settings
            yield self.factory.profileData.storeSettings(
                self._user.profile.id, self._user.profile.settings)
        defer.returnValue(None)

    def do_3090(self, pkt):
        self.sendZeros(0x3091,4)

    def do_3100(self, pkt):
        self.sendZeros(0x3101,4)

    def do_3120(self, pkt):
        self.sendZeros(0x3121,4)
        self.sendZeros(0x3123,0)

    def disconnect_0003(self, pkt):
        # disconnect (no reply needed)
        self.factory.userOffline(self._user)

    def defaultHandler(self, pkt):
        self.sendZeros(pkt.header.id+1,4)

    def register(self):
        self.addHandler(0x3001, self.do_3001)
        self.addHandler(0x3003, self.authenticate_3003)
        self.addHandler(0x3010, self.getProfiles_3010)
        self.addHandler(0x3020, self.createProfile_3020)
        self.addHandler(0x3030, self.deleteProfile_3030)
        self.addHandler(0x3040, self.selectProfile_3040)
        self.addHandler(0x3050, self.do_3050)
        self.addHandler(0x3060, self.do_3060)
        self.addHandler(0x3070, self.getMatchResults_3070)
        self.addHandler(0x308a, self.askForSettings_308a)
        self.addHandler(0x3087, self.do_3087)
        self.addHandler(0x3088, self.do_3088)
        self.addHandler(0x3089, self.do_3089)
        self.addHandler(0x3090, self.do_3090)
        self.addHandler(0x3100, self.do_3100)
        self.addHandler(0x3120, self.do_3120)
        self.addHandler(0x0003, self.disconnect_0003)


class LoginServicePES5(LoginService):
    """
    Specific implementation of login service for PES5
    """

    def __init__(self):
        LoginService.__init__(self)
        self.gameName = 'pes5'


class LoginServiceWE9(LoginService):
    """
    Specific implementation of login service for WE9
    """

    def __init__(self):
        LoginService.__init__(self)
        self.gameName = 'we9'


class LoginServiceWE9LE(LoginService):
    """
    Specific implementation of login service for WE9LE
    """

    def __init__(self):
        LoginService.__init__(self)
        self.gameName = 'we9le'


class NetworkMenuService(LoginService):
    """
    The service that communicates with the player, when
    he/she is in the "NETWORK MENU" mode.
    """

    def connectionLost(self, reason):
        LoginService.connectionLost(self, reason)
        if self._user and self._user.lobbyConnection and self._user.state:
            try: thisLobby = self.factory.getLobbies()[
                self._user.state.lobbyId]
            except IndexError:
                log.msg('Unknown lobby: %d' % self._user.state.lobbyId)
                return
            room = self._user.state.room
            if room:
                # check for in-match disconnect
                if room.match is not None:
                    if room.match.home_team_id is not None and \
                            room.match.away_team_id is not None:
                        # record the disconnect in DB
                        self._user.profile.disconnects += 1
                        self.factory.storeProfile(self._user.profile)
                    # configuration determines how to treat disconnects:
                    if self.factory.serverConfig.Disconnects.get(
                            'CountAsLoss',{}).get('Enabled',False):
                        # set the match score as a loss of the player
                        # that has just disconnected
                        if (room.match.home_profile.id ==
                                self._user.profile.id):
                            room.match.score_home = (
                                self.factory.serverConfig.Disconnects[
                                    'CountAsLoss']['Score']['player'])
                            room.match.score_away = (
                                self.factory.serverConfig.Disconnects[
                                    'CountAsLoss']['Score']['opponent'])
                        else:
                            room.match.score_home = (
                                self.factory.serverConfig.Disconnects[
                                    'CountAsLoss']['Score']['opponent'])
                            room.match.score_away = (
                                self.factory.serverConfig.Disconnects[
                                    'CountAsLoss']['Score']['player'])
                    else:
                        # make sure abandoned match isn't recorded
                        room.match = None

                # exit room
                room.exit(self._user)
                # notify room owner
                if not room.isEmpty():
                    data = b'%s%s' % (
                            util.padWithZeros(self._user.profile.name, 16),
                            util.padWithZeros(room.name, 32))
                    room.owner.sendData(0x4331,data)
                # send room update
                for usr in thisLobby.players.values():
                    n = len(room.players)
                    data = b'%s%s%s%s%s%s%s' % (
                            struct.pack('!i',room.id),
                            struct.pack('!B',1),
                            struct.pack('!B',int(room.usePassword)),
                            util.padWithZeros(room.name,32),
                            struct.pack('!B',int(room.matchTime/5)),
                            b''.join([b'%s%s\0\0\0\0\0' % (
                                        struct.pack('!i',x.profile.id),
                                        struct.pack('!H',x.state.teamId))
                                    for x in room.players]),
                            b'\0'*(48-n*11))
                    usr.sendData(0x4306,data)
                # notify all users in the lobby that
                # player is now back in lobby (not in room)
                for usr in thisLobby.players.values():
                    data = self.formatPlayerInfo(self._user, room.id)
                    usr.sendData(0x4222,data)
                self.sendZeros(0x432b,4)
                # destroy the room, if none left in it
                if room.isEmpty():
                    # notify users in lobby that the room is gone
                    data = struct.pack('!i',room.id)
                    for usr in thisLobby.players.values():
                        usr.sendData(0x4305,data)
                    thisLobby.deleteRoom(room)
            # exit lobby
            thisLobby.exit(self._user)
            # notify every remaining occupant in the lobby
            for usr in thisLobby.players.values():
                usr.sendData(0x4221,struct.pack('!i',self._user.profile.id))


    def formatPlayerInfo(self, usr, roomId, stats=None):
        return b'%s%s%s%s%s%s%s' % (
            struct.pack('!i',usr.profile.id),
            util.padWithZeros(usr.profile.name,16),
            struct.pack('!B',usr.state.inRoom),
            struct.pack('!i',roomId),
            struct.pack('!i',usr.state.noLobbyChat),
            struct.pack('!B',0),
            struct.pack('!B',0))

    def formatProfileInfo(self, profile, stats):
        if not self.factory.serverConfig.ShowStats:
            profile = self.makePristineProfile(profile)
        return (b'%(id)s%(name)s%(division)s%(points)s%(games)s'
                b'%(wins)s%(losses)s%(draws)s%(win-strk)s'
                b'%(win-best)s%(disconnects)s%(PAD1)s'
                b'%(goals-scored)s%(PAD2)s%(goals-allowed)s'
                b'%(fav-team)s%(fav-player)s%(rank)s' % {
                    b'id': struct.pack('!i',profile.id),
                    b'name': util.padWithZeros(profile.name, 16),
                    b'division': struct.pack('!B',
                        self.factory.ratingMath.getDivision(profile.points)),
                    b'points': struct.pack('!i', profile.points),
                    b'games': struct.pack('!H',
                        stats.wins+stats.losses+stats.draws),
                    b'wins': struct.pack('!H', stats.wins),
                    b'losses': struct.pack('!H', stats.losses),
                    b'draws': struct.pack('!H', stats.draws),
                    b'win-strk': struct.pack('!H', stats.streak_current),
                    b'win-best': struct.pack('!H', stats.streak_best),
                    b'disconnects': struct.pack(
                        '!H', profile.disconnects),
                    b'PAD1': b'\0\0',
                    b'goals-scored': struct.pack('!H', stats.goals_scored),
                    b'PAD2': b'\0\0',
                    b'goals-allowed': struct.pack('!H', stats.goals_allowed),
                    b'fav-team': struct.pack('!H', profile.favTeam),
                    b'fav-player': struct.pack('!i', profile.favPlayer),
                    b'rank': struct.pack('!i', profile.rank),
                })

    def formatRoomSettings(self, settings):
        return (b'\0\0\1\1\0\0\0\x0e'
                b'%(matchTime)s%(timeLimit)s%(pauses)s%(condition)s'
                b'%(injuries)s%(maxSubs)s%(extraTime)s%(penalties)s'
                b'%(dayTime)s%(seasonWeather)s%(randomInt)s%(pad1)s' % {
            b'matchTime':struct.pack('!B', settings.matchTime),
            b'timeLimit':struct.pack('!B', settings.timeLimit),
            b'pauses':struct.pack('!B', settings.pauses),
            b'condition':struct.pack('!B', settings.condition),
            b'injuries':struct.pack('!B', settings.injuries),
            b'maxSubs':struct.pack('!B', settings.maxSubs),
            b'extraTime':struct.pack('!B', settings.extraTime),
            b'penalties':struct.pack('!B', settings.penalties),
            b'dayTime':struct.pack('!B', settings.dayTime),
            b'seasonWeather':struct.pack('!B', settings.seasonWeather),
            b'randomInt':struct.pack('!i', 0),
            b'pad1':b'\0'*50})

    @defer.inlineCallbacks
    def do_4100(self, pkt):
        profileIndex = struct.unpack('!B',pkt.data[0:1])[0]
        self._user.profile = self._user.profiles[profileIndex]
        #data = '\0'*4+struct.pack('!i',self._user.profile.id)+\
        data = b'%s%s' % (
            b'\0'*4, struct.pack('!i',self._user.profile.id))
        data += b'\xff'*7+b'\x80'+b'\xff'*15+b'\xc0'+b'\2\2\2\2\2\2\2\1\0'#+'%s' % (
        #    struct.pack(
        #        '!B', self.factory.ratingMath.getDivision(
        #            self._user.profile.points)))
        self.sendData(0x4101, data)

        profile = yield self.factory.getPlayerProfile(
            self._user.profile.id)
        if profile:
            stats = yield self.getStats(profile.id)
            data = b'\0\0\0\0%s' % self.formatProfileInfo(profile, stats)
            self.sendData(0x4103, data)
        else:
            self.sendZeros(0x4103,0)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def getProfile_4102(self, pkt):
        profileId = struct.unpack('!i', pkt.data[0:4])[0]
        profile = yield self.factory.getPlayerProfile(profileId)
        if profile:
            stats = yield self.getStats(profile.id)
            data = b'\0\0\0\0%s' % self.formatProfileInfo(profile, stats)
            #data += ''.join([chr(c) for c in range(0x5d-len(data))])
            self.sendData(0x4103, data)
        else:
            self.sendZeros(0x4103,0)
        defer.returnValue(None)

    def getLobbies_4200(self, pkt):
        self._user.gameVersion = struct.unpack('!B',pkt.data[0:1])[0]
        data = b'%s%s' % (
            struct.pack('!H',len(self.factory.getLobbies())),
            b''.join([bytes(x) for x in self.factory.getLobbies()]))
        self.sendData(0x4201, data)

    def sendChatHistory(self, aLobby, who):
        if aLobby is None or who is None:
            return
        for chatMessage in list(aLobby.chatHistory):
            chatType = b'\0'
            if chatMessage.toProfile is not None:
                if who.profile.id not in [
                    chatMessage.fromProfile.id, chatMessage.toProfile.id]:
                    continue
                special = chatMessage.special
            else:
                special = b'\0\0\0\0'
            data = b'%s%s%s%s%s' % (
                    chatType,
                    special,
                    struct.pack('!i', chatMessage.fromProfile.id),
                    util.padWithZeros(chatMessage.fromProfile.name,16),
                    chatMessage.text.encode('utf-8')[:126]+b'\0\0')
            who.sendData(0x4402, data)

    def broadcastSystemChat(self, aLobby, text):
        chatMessage = lobby.ChatMessage(lobby.SYSTEM_PROFILE, text)
        for usr in aLobby.players.values():
            data = b'%s%s%s%s%s' % (
                    b'\0',
                    b'\0\0\0\0',
                    struct.pack('!i', chatMessage.fromProfile.id),
                    util.padWithZeros(chatMessage.fromProfile.name,16),
                    chatMessage.text.encode('utf-8')[:126]+b'\0\0')
            usr.sendData(0x4402, data)
        aLobby.addToChatHistory(chatMessage)

    @defer.inlineCallbacks
    def selectLobby_4202(self, pkt):
        self._user.state = user.UserState()
        self._user.state.lobbyId = struct.unpack('!B',pkt.data[0:1])[0]
        self._user.state.ip1 = pkt.data[1:17]
        self._user.state.ip2 = pkt.data[19:35]
        self._user.state.udpPort1 = struct.unpack('!H',pkt.data[17:19])[0]
        self._user.state.udpPort2 = struct.unpack('!H',pkt.data[35:37])[0]
        self._user.state.someField = struct.unpack('!H',pkt.data[37:39])[0]
        self._user.state.inRoom = 0
        self._user.state.noLobbyChat = 0
        self._user.state.room = None
        self._user.state.teamId = 0
        log.msg('self._user: %s, state: %s' % (
                self._user.profile.name, self._user.state))
        self.sendZeros(0x4203,4)

        # user is now considered REALLY ONLINE.
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        # enter the lobby
        log.msg('User {%s} entering lobby %d' % (
                self._user.profile.name, self._user.state.lobbyId+1))
        thisLobby.enter(self._user, self)
        # notify all in the lobby
        stats = yield self.getStats(self._user.profile.id)
        data = self.formatPlayerInfo(self._user, 0, stats)
        for usr in thisLobby.players.values():
            usr.sendData(0x4220, data)
        # send chat history
        reactor.callLater(
            CHAT_HISTORY_DELAY, self.sendChatHistory, thisLobby, self._user)

    def getUserList_4210(self, pkt):
        self.sendZeros(0x4211,4)
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        for usr in thisLobby.players.values():
            if usr.state.inRoom == 1:
                roomId = usr.state.room.id
            else:
                roomId = 0
            data = self.formatPlayerInfo(usr, roomId)
            self.sendData(0x4212,data)
        self.sendZeros(0x4213,4)

    def getRoomList_4300(self, pkt):
        self.sendZeros(0x4301,4)
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        for room in thisLobby.rooms.values():
            n = len(room.players)
            data = b'%s%s%s%s%s%s%s' % (
                    struct.pack('!i',room.id),
                    struct.pack('!B',1),
                    struct.pack('!B',int(room.usePassword)),
                    util.padWithZeros(room.name,32),
                    struct.pack('!B',int(room.matchTime/5)),
                    b''.join([struct.pack('!i',usr.profile.id)
                            for usr in room.players]),
                    b'\0'*(48-n*4))
            self.sendData(0x4302, data)
        self.sendZeros(0x4303,4)

    def do_3080(self, pkt):
        self.sendZeros(0x3082,4)
        self.sendZeros(0x3086,0)

    def getFriends_4580(self, pkt):
        self.sendZeros(0x4581,4)
        self.sendZeros(0x4583,4)

    @defer.inlineCallbacks
    def setFavouriteTeam_4110(self, pkt):
        self._user.profile.favTeam = struct.unpack('!H', pkt.data[0:2])[0]
        yield self.factory.storeProfile(self._user.profile)
        self.sendZeros(0x4112,4)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def setFavouritePlayer_4114(self, pkt):
        self._user.profile.favPlayer = struct.unpack('!i', pkt.data[0:4])[0]
        yield self.factory.storeProfile(self._user.profile)
        self.sendZeros(0x4116,4)
        defer.returnValue(None)

    def searchPlayers_4600(self, pkt):
        name = util.stripZeros(pkt.data[1:17])
        log.msg('Searching for player: %s' % name)
        self.sendZeros(0x4601,4)
        self.sendZeros(0x4603,4)

    def getInboxMessages_4780(self, pkt):
        self.sendZeros(0x4781,4)
        self.sendZeros(0x4783,4)

    def quickMatchSearch_4a00(self, pkt):
        self.sendData(0x4a01,b'\0\0\0\1')  # "no results"
        try: thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        except IndexError:
            log.msg('Unknown lobby id: %d' % self._user.state.lobbyId)
        except AttributeError:
            log.msg('User may not have a defined state yet')
        else:
            log.msg('User {%s} exiting lobby %d' % (
                    self._user.profile.name, self._user.state.lobbyId+1))
            thisLobby.exit(self._user)
            # notify every remaining occupant in the lobby
            for usr in thisLobby.players.values():
                usr.sendData(0x4221,struct.pack('!i',self._user.profile.id))

    def disconnect_0003(self, pkt):
        try: thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        except IndexError:
            log.msg('Unknown lobby id: %d' % self._user.state.lobbyId)
        except AttributeError:
            log.msg('User may not have a defined state yet')
        else:
            log.msg('User {%s} exiting lobby %d' % (
                    self._user.profile.name, self._user.state.lobbyId+1))
            thisLobby.exit(self._user)
            # user now considered OFFLINE
            self.factory.userOffline(self._user)
            # notify every remaining occupant in the lobby
            for usr in thisLobby.players.values():
                usr.sendData(0x4221,struct.pack('!i',self._user.profile.id))
 
    def register(self):
        LoginService.register(self) # also handle all parent packets
        self.addHandler(0x4100, self.do_4100)
        self.addHandler(0x4102, self.getProfile_4102)
        self.addHandler(0x4200, self.getLobbies_4200)
        self.addHandler(0x4202, self.selectLobby_4202)
        self.addHandler(0x4210, self.getUserList_4210)
        self.addHandler(0x4300, self.getRoomList_4300)
        self.addHandler(0x3080, self.do_3080)
        self.addHandler(0x4580, self.getFriends_4580)
        self.addHandler(0x4110, self.setFavouriteTeam_4110)
        self.addHandler(0x4114, self.setFavouritePlayer_4114)
        self.addHandler(0x4600, self.searchPlayers_4600)
        self.addHandler(0x4780, self.getInboxMessages_4780)
        self.addHandler(0x4a00, self.quickMatchSearch_4a00)
        self.addHandler(0x0003, self.disconnect_0003)


class MainService(NetworkMenuService):
    """
    The main game server, which keeps track of matches, goals
    and other important statistics.
    """

    def createRoom_4310(self, pkt):
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        roomName = util.stripZeros(pkt.data[0:32])
        try:
            existing = thisLobby.getRoom(roomName)
            self.sendData(0x4311,b'\xff\xff\xff\x10')
            return
        except KeyError:
            pass
        room = lobby.Room(thisLobby)
        room.name = roomName
        room.usePassword = struct.unpack('!B',pkt.data[33:34])[0] == 1
        if room.usePassword:
            room.password = util.stripZeros(pkt.data[34:50])
        # put room creator into the room
        room.enter(self._user)
        # add room to the lobby
        thisLobby.addRoom(room)
        log.msg('Room created: %s' % repr(room))
        # notify all users in the lobby about the new room
        for usr in thisLobby.players.values():
            n = len(room.players)
            data = b'%s%s%s%s%s%s%s' % (
                    struct.pack('!i',room.id),
                    struct.pack('!B',1),
                    struct.pack('!B',int(room.usePassword)),
                    util.padWithZeros(room.name,32),
                    struct.pack('!B',int(room.matchTime/5)),
                    b''.join([b'%s\0\0\0\0\0\0\0' % struct.pack(
                        '!i',x.profile.id)
                        for x in room.players]),
                    b'\0'*(48-n*11))
            usr.sendData(0x4306,data)
        # notify all users in the lobby that player is now in a room
        for usr in thisLobby.players.values():
            data = self.formatPlayerInfo(self._user, room.id)
            usr.sendData(0x4222,data)
        self.sendZeros(0x4311,4)

    def exitRoom_432a(self, pkt):
        if self._user.state.inRoom == 0:
            log.msg('WARN: user not in a room.')
            self.sendZeros(0x432b,4)
        else:
            room = self._user.state.room
            room.exit(self._user)
            # notify room owner
            if len(room.players)>0:
                data = b'%s%s' % (
                        util.padWithZeros(self._user.profile.name, 16),
                        util.padWithZeros(room.name, 32))
                room.owner.sendData(0x4331,data)
                self._user.needsLobbyChatReplay = True
            # send room info update
            thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
            for usr in thisLobby.players.values():
                n = len(room.players)
                data = b'%s%s%s%s%s%s%s' % (
                        struct.pack('!i',room.id),
                        struct.pack('!B',1),
                        struct.pack('!B',int(room.usePassword)),
                        util.padWithZeros(room.name,32),
                        struct.pack('!B',int(room.matchTime/5)),
                        b''.join([b'%s%s\0\0\0\0\0' % (
                                    struct.pack('!i',x.profile.id),
                                    struct.pack('!H',x.state.teamId))
                                for x in room.players]),
                        b'\0'*(48-n*11))
                usr.sendData(0x4306,data)
            # notify all users in the lobby that
            # player is now back in lobby (not in room)
            for usr in thisLobby.players.values():
                data = self.formatPlayerInfo(self._user, room.id)
                usr.sendData(0x4222,data)
            self.sendZeros(0x432b,4)
            # destroy the room, if none left in it
            if room.isEmpty():
                # notify users in lobby that the room is gone
                data = struct.pack('!i',room.id)
                for usr in thisLobby.players.values():
                    usr.sendData(0x4305,data)
                thisLobby.deleteRoom(room)
            # re-send chat history if needed
            if self._user.needsLobbyChatReplay:
                self._user.needsLobbyChatReplay = False
                reactor.callLater(
                    CHAT_HISTORY_DELAY, self.sendChatHistory,
                    thisLobby, self._user)
 
    def setMatchTime_4364(self, pkt):
        matchTime = struct.unpack('!B',pkt.data[0:1])[0] * 5
        log.debug('Match time: %d' % matchTime)
        room = self._user.state.room
        if room:
            room.matchTime = matchTime
            # send room info update
            thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
            for usr in thisLobby.players.values():
                n = len(room.players)
                data = b'%s%s%s%s%s%s%s' % (
                        struct.pack('!i',room.id),
                        struct.pack('!B',1),
                        struct.pack('!B',int(room.usePassword)),
                        util.padWithZeros(room.name,32),
                        struct.pack('!B',int(room.matchTime/5)),
                        b''.join([b'%s%s\0\0\0\0\0' % (
                                    struct.pack('!i',x.profile.id),
                                    struct.pack('!H',x.state.teamId))
                                for x in room.players]),
                        b'\0'*(48-n*11))
                usr.sendData(0x4306,data)
        self.sendZeros(0x4365,4)

    def selectTeam_4366(self, pkt):
        team = struct.unpack('!H', pkt.data[0:2])[0]
        log.msg('Team selected: %d' % team)
        room = self._user.state.room
        # create new Match structure
        room.match = lobby.Match(room.match)
        if room.isOwner(self._user):
            room.match.home_profile = self._user.profile
            room.match.home_team_id = team
        else:
            room.match.away_profile = self._user.profile
            room.match.away_team_id = team
        if room.match.home_profile and room.match.away_profile:
            log.msg('NEW MATCH starting: Team %d (%s) vs Team %d (%s)' % (
                room.match.home_team_id, room.match.home_profile.name,
                room.match.away_team_id, room.match.away_profile.name))
        self.sendData(0x4367,b'\0\0\0\1')

    def goalScored_4368(self, pkt):
        room = self._user.state.room
        if pkt.data[0] == 0:
            log.msg('GOAL SCORED by HOME team %d (%s)' % (
                room.match.home_team_id, room.match.home_profile.name))
            room.match.score_home += 1
        else:
            log.msg('GOAL SCORED by AWAY team %d (%s)' % (
                room.match.away_team_id, room.match.away_profile.name))
            room.match.score_away += 1
        log.msg('UPDATE: Team %d (%s) vs Team %d (%s) - %d:%d (in progress)' % (
            room.match.home_team_id, room.match.home_profile.name,
            room.match.away_team_id, room.match.away_profile.name,
            room.match.score_home, room.match.score_away))
        self.sendData(0x4369,b'\0\0\0\0')

    def matchExit_4370(self, pkt):
        #log.msg('[4370-RECV]: %s' % PacketFormatter.format(pkt))
        room = self._user.state.room
        if room is not None and room.match is not None:
            exitType = struct.unpack('!B', pkt.data[1])[0]
            if pkt.data[0] == 0:
                room.match.home_exit = exitType
            else:
                room.match.away_exit = exitType
        self.sendData(0x4371,b'\0\0\0\0')

    def chat_4400(self, pkt):
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        chatType = pkt.data[0:2]
        message = util.stripZeros(pkt.data[10:])
        if any(word in message.decode('utf-8')
               for word in self.factory.serverConfig.Chat['bannedWords']):
            message = b'[%s]' % self.factory.serverConfig.Chat['warningMessage'].encode('utf-8')
        data = b'%s%s%s%s%s' % (
                chatType[0:1],
                pkt.data[2:6],
                struct.pack('!i',self._user.profile.id),
                util.padWithZeros(self._user.profile.name,16),
                #util.padWithZeros(message, 128))
                message[:126]+b'\0\0')
        if chatType==b'\x00\x01':
            # add to lobby chat history
            thisLobby.addToChatHistory(
                lobby.ChatMessage(self._user.profile, message.decode('utf-8')))
            # lobby chat
            for usr in thisLobby.players.values():
                usr.sendData(0x4402, data)
        elif chatType==b'\x01\x02':
            # room chat
            room = self._user.state.room
            if room:
                for usr in room.players:
                    usr.sendData(0x4402, data)
        elif chatType==b'\x00\x02':
            # private message
            profileId = struct.unpack('!i',pkt.data[6:10])[0]
            usr = thisLobby.getPlayerByProfileId(profileId)
            if usr:
                # add to lobby chat history
                thisLobby.addToChatHistory(
                    lobby.ChatMessage(
                        self._user.profile, message.decode('utf-8'), usr.profile,
                        pkt.data[2:6]))
                usr.sendData(0x4402, data)
                if usr != self._user:
                    self._user.sendData(0x4402, data) # echo to self
            else:
                log.msg(
                    'WARN: user with profile id = '
                    '%d not found.' % profileId)

    def ping_4b00(self, pkt):
        profileId = struct.unpack('!i', pkt.data[0:4])[0]
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        usr = thisLobby.getPlayerByProfileId(profileId)
        if usr:
            ip1, udpPort1 = usr.state.ip1, usr.state.udpPort1
            ip2, udpPort2 = usr.state.ip2, usr.state.udpPort2
            """
            NOTE: Looks like the game itself is smart about
            using the internal IP in such situations. Disabling
            this server feature for now. May need more experiments.

            # check if both users are on the same LAN
            # if so --> do not send WAN ip, but send local ip twice
            if ip1 == self._user.state.ip1:
                ip1, udpPort1 = ip2, udpPort2
            """
            # send ping info
            data = b'%s%s%s%s%s%s' % (
                struct.pack('!i',0),
                util.padWithZeros(ip1, 16),
                struct.pack('!H',udpPort1),
                util.padWithZeros(ip2, 16),
                struct.pack('!H',udpPort2),
                struct.pack('!i',usr.profile.id))
            self.sendData(0x4b01,data)
        else:
            self.sendData(0x4b01,b'\xff\xff\xff\xff')

    def checkHashes(self, userA, userB):
        try: rosterSettings = self.factory.serverConfig.Roster
        except AttributeError:
            return True
        try: compareHash = rosterSettings['compareHash']
        except KeyError:
            return True
        if compareHash:
            aInfo = self.factory.getUserInfo(userA)
            bInfo = self.factory.getUserInfo(userB)
            if aInfo.rosterHash != bInfo.rosterHash:
                log.msg('INFO: Roster-hashes are different: %s(%s) != %s(%s). '
                    'Match CANCELLED.' % (
                    userA.profile.name, binascii.b2a_hex(aInfo.rosterHash),
                    userB.profile.name, binascii.b2a_hex(bInfo.rosterHash)))
            return aInfo.rosterHash == bInfo.rosterHash
        return True

    def cancelChallenge_4325(self, pkt):
        if self._user.state.inRoom == 0:
            log.msg('WARN: user not in a room.')
            self.sendZeros(0x4326,4)
        else:
            room = self._user.state.room
            room.exit(self._user)
            # notify room owner
            if len(room.players)>0:
                room.owner.sendData(0x4324, b'\0'*4)
            # send room info update
            thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
            for usr in thisLobby.players.values():
                n = len(room.players)
                data = b'%s%s%s%s%s%s%s' % (
                        struct.pack('!i',room.id),
                        struct.pack('!B',1),
                        struct.pack('!B',int(room.usePassword)),
                        util.padWithZeros(room.name,32),
                        struct.pack('!B',int(room.matchTime/5)),
                        b''.join([b'%s%s\0\0\0\0\0' % (
                                    struct.pack('!i',x.profile.id),
                                    struct.pack('!H',x.state.teamId))
                                for x in room.players]),
                        b'\0'*(48-n*11))
                usr.sendData(0x4306,data)
            # notify all users in the lobby that
            # player is now back in lobby (not in room)
            for usr in thisLobby.players.values():
                data = self.formatPlayerInfo(self._user, room.id)
                usr.sendData(0x4222,data)
            self.sendZeros(0x4326,4)
            # destroy the room, if none left in it
            if room.isEmpty():
                # notify users in lobby that the room is gone
                data = struct.pack('!i',room.id)
                for usr in thisLobby.players.values():
                    usr.sendData(0x4305,data)
                thisLobby.deleteRoom(room)

    @defer.inlineCallbacks
    def challenge_4320(self, pkt):
        roomId = struct.unpack('!i',pkt.data[0:4])[0]
        ping = pkt.data[20:21]
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        room = thisLobby.getRoomById(roomId)
        if room is None:
            log.msg('ERROR: Room (id=%d) does not exist.' % roomId)
            self.sendData(0x4321,b'\0\0\0\1')
        else:
            usr = room.owner
            if not usr:
                log.msg('ERROR: Room (id=%d) has no owner.' % roomId)
                self.sendData(0x4321,b'\0\0\0\1')
            elif not isSameGame(self.factory, self._user, usr):
                log.msg('INFO: Game version mismatch. Match CANCELLED.')
                self.sendData(0x4321,b'\0\0\0\1')
            elif room.lobby.checkRosterHash and (
                    not self.checkHashes(self._user, usr)):
                log.msg('INFO: Roster-hash mismatch. Match CANCELLED.')
                self.sendData(0x4321,b'\0\0\0\1')
            else:
                # enter room
                room.enter(self._user)

                # notify people in lobby about change
                for otherUsr in thisLobby.players.values():
                    n = len(room.players)
                    data = b'%s%s%s%s%s%s%s' % (
                            struct.pack('!i',room.id),
                            struct.pack('!B',1),
                            struct.pack('!B',int(room.usePassword)),
                            util.padWithZeros(room.name,32),
                            struct.pack('!B',int(room.matchTime/5)),
                            b''.join([b'%s%s\0\0\0\0\0' % (
                                        struct.pack('!i',x.profile.id),
                                        struct.pack('!H',x.state.teamId))
                                    for x in room.players]),
                            b'\0'*(48-n*4))
                    otherUsr.sendData(0x4306,data)
                # notify all users in the lobby that player is now in a room
                for otherUsr in thisLobby.players.values():
                    data = self.formatPlayerInfo(self._user, room.id)
                    otherUsr.sendData(0x4222,data)

                # send challenge
                stats = yield self.getStats(self._user.profile.id)
                profileInfo = self.formatProfileInfo(
                    self._user.profile, stats)

                data = b'%s%s%s%s' % (
                    profileInfo,
                    b'\0'*(0x57-len(profileInfo)),
                    ping, # copy ping
                    b'\0\0')
                usr.sendData(0x4322,data)
                usr.challenger = self._user
        defer.returnValue(None)

    def challengeResponse_4323(self, pkt):
        accepted = (struct.unpack('!B', pkt.data[0:1])[0] == 1)
        if accepted:
            # send response to challenger ("ultimate packet")
            challenger = self._user.challenger
            challenger.needsLobbyChatReplay = True
            challenger.sendData(0x4321,b'\0\0\0\0%s' % b''.join(
                [struct.pack('!B',x) for x in range(5,0x51)]))
            # send response to owner
            room = self._user.state.room
            data = b'%s%s' % (
                    util.padWithZeros(challenger.profile.name, 16),
                    util.padWithZeros(room.name, 32))
            self.sendData(0x4330,data)
            # notify the rest that two users no longer participate
            # in lobby chat
            self._user.state.noLobbyChat = 0#0xff
            challenger.state.noLobbyChat = 0#0xff
            thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
            for usr in thisLobby.players.values():
                data = self.formatPlayerInfo(self._user, room.id)
                usr.sendData(0x4222, data)
                data = self.formatPlayerInfo(challenger, room.id)
                usr.sendData(0x4222, data)
        else:
            challenger = self._user.challenger
            room = self._user.state.room
            room.exit(challenger)
            # notify people in lobby about change
            thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
            for otherUsr in thisLobby.players.values():
                n = len(room.players)
                data = b'%s%s%s%s%s%s%s' % (
                        struct.pack('!i',room.id),
                        struct.pack('!B',1),
                        struct.pack('!B',int(room.usePassword)),
                        util.padWithZeros(room.name,32),
                        struct.pack('!B',int(room.matchTime/5)),
                        b''.join([b'%s%s\0\0\0\0\0' % (
                                    struct.pack('!i',x.profile.id),
                                    struct.pack('!H',x.state.teamId))
                                for x in room.players]),
                        b'\0'*(48-n*4))
                otherUsr.sendData(0x4306,data)
            # notify all users in the lobby about player
            for otherUsr in thisLobby.players.values():
                data = self.formatPlayerInfo(challenger, 0)
                otherUsr.sendData(0x4222,data)
            # send response to challenger
            challenger.sendData(0x4321,b'\0\0\0\1')

    def relayRoomSettings_4350(self, pkt):
        if not self._user.state.room is None:
            for usr in self._user.state.room.players:
                if usr == self._user:
                    continue
                usr.sendData(0x4350, pkt.data)

    def toggleReady_4360(self, pkt):
        ready = (struct.unpack('!B', pkt.data[0:1])[0] == 1)
        # relay to others in the room
        room = self._user.state.room
        if room:
            if ready:
                room.readyCount += 1
            else:
                room.readyCount -= 1
            for usr in room.players:
                if usr == self._user:
                    continue
                usr.sendData(0x4362, pkt.data)
        self.sendZeros(0x4361,4)

        # if all players are ready, start the match
        if room.readyCount == 2:
            for usr in room.players:
                usr.sendData(0x4344, b'\4')
                usr.needsLobbyChatReplay = True
            # reset count
            room.readyCount = 0
            if room.match and room.match.startDatetime is None:
                # mark the match-start time
                room.match.startDatetime = datetime.now()

    def register(self):
        NetworkMenuService.register(self) # also handle all parent packets
        self.addHandler(0x4310, self.createRoom_4310)
        self.addHandler(0x432a, self.exitRoom_432a)
        self.addHandler(0x4364, self.setMatchTime_4364)
        self.addHandler(0x4366, self.selectTeam_4366)
        self.addHandler(0x4368, self.goalScored_4368)
        self.addHandler(0x4370, self.matchExit_4370)
        self.addHandler(0x4400, self.chat_4400)
        self.addHandler(0x4b00, self.ping_4b00)
        self.addHandler(0x4320, self.challenge_4320)
        self.addHandler(0x4323, self.challengeResponse_4323)
        self.addHandler(0x4325, self.cancelChallenge_4325)
        self.addHandler(0x4350, self.relayRoomSettings_4350)
        self.addHandler(0x4360, self.toggleReady_4360)

