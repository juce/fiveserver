"""
Protocol implementations for PES6
"""

from twisted.internet import reactor, defer
from twisted.application import service
from twisted.web import client

from Crypto.Cipher import Blowfish
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
from fiveserver.protocol import pes5


CHAT_HISTORY_DELAY = 3  # seconds

ERRORS = [
    b'\xff\xff\xfd\xb6', # owner cancelled
    b'\xff\xff\xfd\xbb', # only 4 players can participate
    b'\xff\xff\xfe\x00', # deadline passed
]

def getHomePlayerNames(match):
    home_players = [match.teamSelection.home_captain]
    home_players.extend(match.teamSelection.home_more_players)
    return ','.join([x.name for x in home_players])

def getAwayPlayerNames(match):
    away_players = [match.teamSelection.away_captain]
    away_players.extend(match.teamSelection.away_more_players)
    return ','.join([x.name for x in away_players])


class NewsProtocol(pes5.NewsProtocol):
    """
    News-service for PES6
    """

    GREETING = {
        'title': 'SYSTEM: Fiveserver v%s',
        'text': ('Welcome to Fiveserver -\r\n'
                 'independent community server\r\n'
                 'supporting PES6/WE2007 games.\r\n'
                 'Have a good time, play some nice\r\n'
                 'football and try to score goals.\r\n'
                 '\r\n'
                 'Credits:\r\n'
                 'Protocol analysis: reddwarf, juce\r\n'
                 'Server programming: juce, reddwarf')
    }

    SERVER_NAME = 'Fiveserver'

    NEW_FEATURES = {
        '0.4.1': (
            'NEW features in 0.4.1:',
            '* introducing PES6 support!\r\n')
    }

    def register(self):
        pes5.NewsProtocol.register(self)
        self.addHandler(0x2200, self.getWebServerList_2200)

    def getServerList_2005(self, pkt):
        myport = self.transport.getHost().port
        gameName = None
        for name,port in self.factory.serverConfig.GamePorts.items():
            if port == myport:
                gameName = name
                break
        serverIP = self.factory.configuration.serverIP_wan
        servers = [
            (-1,2,'LOGIN',serverIP,
             self.factory.serverConfig.NetworkServer['loginService'][gameName],
             0,2),
            (-1,3,self.SERVER_NAME,serverIP,
             self.factory.serverConfig.NetworkServer['mainService'],
             max(0, self.factory.getNumUsersOnline()-1),3),
            (-1,8,'NETWORK_MENU',serverIP,
             self.factory.serverConfig.NetworkServer['networkMenuService'],
             0,8),
        ]
        data = b''.join(['%s%s%s%s%s%s%s' % (
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

    def getWebServerList_2200(self, pkt):
        self.sendZeros(0x2201,4)
        #self.sendData(0x2202,data) #TODO
        self.sendZeros(0x2203,4)


class RosterHandler:
    """
    Provide means of extracting roster hash
    from the client auth packet data.
    """

    def getRosterHash(self, pkt_data):
        return pkt_data[58:74]


class LoginService(RosterHandler, pes5.LoginService):
    """
    Login-service for PES6
    """

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
            b'%(division)s%(points)s%(rating)s%(games)s' % {
                b'index':struct.pack('!B', i),
                b'id':struct.pack('!i', profile.id),
                b'name':util.padWithZeros(profile.name, 48),
                b'division':struct.pack('!B', 
                    self.factory.ratingMath.getDivision(profile.points)),
                b'playTime':struct.pack('!i', int(profile.playTime.total_seconds())),
                b'points':struct.pack('!i', profile.points),
                b'games':struct.pack('!H', games),
                b'rating':struct.pack('!H',profile.rating),
                } 
            for (_, games), (i, profile) in zip(
                results, enumerate(profiles))])
        self.sendData(0x3012, data)
        defer.returnValue(None)

    def getMatchResults_3070(self, pkt):
        self.sendZeros(0x3071,4)
        self.sendZeros(0x3073,4)

    def do_3120(self, pkt):
        self.sendZeros(0x3121,4)
        self.sendZeros(0x3123,0)


class LoginServicePES6(LoginService):
    """
    Specific implementation of login service for PES6
    """

    def __init__(self):
        LoginService.__init__(self)
        self.gameName = 'pes6'


class LoginServiceWE2007(LoginService):
    """
    Specific implementation of login service for WE2007
    """

    def __init__(self):
        LoginService.__init__(self)
        self.gameName = 'we2007'


class NetworkMenuService(RosterHandler, pes5.NetworkMenuService):
    """
    PES6 implementation.
    The service that communicates with the player, when
    he/she is in the "NETWORK MENU" mode.
    """

class MainService(RosterHandler, pes5.MainService):
    """
    PES6 implementation
    The main game server, which keeps track of matches, goals
    and other important statistics.
    """

    @defer.inlineCallbacks
    def connectionLost(self, reason):
        pes5.LoginService.connectionLost(self, reason)
        if self._user.state:
            room = self._user.state.room
            if room:
                room.cancelParticipation(self._user)
                yield self.exitingRoom(room, self._user)
                # update participation of remaining players in room
                data = self.formatRoomParticipationStatus(room)
                for player in room.players:                
                    player.sendData(0x4365, data)
            self.exitingLobby(self._user)
    
    def formatPlayerInfo(self, usr, roomId, stats=None):
        if stats is None:
            stats = user.Stats(usr.profile.id, 0,0,0,0,0,0,0)
        return (b'%(id)s%(name)s%(groupid)s%(groupname)s'
                b'%(groupmemberstatus)s%(division)s%(roomid)s'
                b'%(points)s%(rating)s%(matches)s%(wins)s'
                b'%(losses)s%(draws)s%(pad1)s' % {
            b'id': struct.pack('!i',usr.profile.id),
            b'name': util.padWithZeros(usr.profile.name,48),
            b'groupid': struct.pack('!i',0),
            b'groupname': b'\0'*48,
            b'groupmemberstatus': struct.pack('!B',0),
            b'division': struct.pack('!B', 
                self.factory.ratingMath.getDivision(usr.profile.points)),
            b'roomid': struct.pack('!i',roomId),
            b'points': struct.pack('!i',usr.profile.points),
            b'rating': struct.pack('!H',0),
            b'matches': struct.pack('!H',
                stats.wins + stats.losses + stats.draws),
            b'wins': struct.pack('!H',stats.wins),
            b'losses': struct.pack('!H',stats.losses),
            b'draws': struct.pack('!H',stats.draws),
            b'pad1': b'\0'*3,
        })

    def formatProfileInfo(self, profile, stats):
        if not self.factory.serverConfig.ShowStats:
            profile = self.makePristineProfile(profile)
        return (b'%(id)s%(name)s%(groupid)s%(groupname)s'
                    b'%(groupmemberstatus)s%(division)s'
                    b'%(points)s%(rating)s%(matches)s'
                    b'%(wins)s%(losses)s%(draws)s%(win-strk)s'
                    b'%(win-best)s%(disconnects)s'
                    b'%(goals-scored)s%(goals-allowed)s'
                    b'%(comment)s%(rank)s'
                    b'%(competition-gold-medals)s%(competition-silver-medals)s'
                    b'%(unknown1)s'
                    b'%(winnerscup-gold-medals)s%(winnerscup-silver-medals)s'
                    b'%(unknown2)s%(unknown3)s'
                    b'%(language)s%(recent-used-teams)s' % {
                b'id': struct.pack('!i',profile.id),
                b'name': util.padWithZeros(profile.name,48),
                b'groupid': struct.pack('!i',0),
                b'groupname': util.padWithZeros('Playmakers',48),
                b'groupmemberstatus': struct.pack('!B',1),
                b'division': struct.pack('!B', 
                    self.factory.ratingMath.getDivision(profile.points)),
                b'points': struct.pack('!i',profile.points),
                b'rating': struct.pack('!H',profile.rating),
                b'matches': struct.pack('!H',
                    stats.wins + stats.losses + stats.draws),
                b'wins': struct.pack('!H',stats.wins),
                b'losses': struct.pack('!H',stats.losses),
                b'draws': struct.pack('!H',stats.draws),
                b'win-strk': struct.pack('!H', stats.streak_current),
                b'win-best': struct.pack('!H', stats.streak_best),
                b'disconnects': struct.pack(
                    '!H', profile.disconnects),
                b'goals-scored': struct.pack('!i', stats.goals_scored),
                b'goals-allowed': struct.pack('!i', stats.goals_allowed),
                b'comment': util.padWithZeros((
                    profile.comment or 'Fiveserver rules!'), 256),
                b'rank': struct.pack('!i',profile.rank),
                b'competition-gold-medals': struct.pack('!H', 0),
                b'competition-silver-medals': struct.pack('!H', 0),
                b'unknown1': struct.pack('!H', 0),
                b'winnerscup-gold-medals': struct.pack('!H', 0),
                b'winnerscup-silver-medals': struct.pack('!H', 0),
                b'unknown2': struct.pack('!H', 0),
                b'unknown3': struct.pack('!B', 0),
                b'language': struct.pack('!B', 0),
                b'recent-used-teams': b''.join([struct.pack('!H', team) 
                    for team in stats.teams]) + b'\xff\xff'*(5-len(stats.teams)) 
            })
            
    def formatHomeOrAway(self, room, usr):
        if room.teamSelection:
            return room.teamSelection.getHomeOrAway(usr)
        return 0xff

    def formatTeamsAndGoals(self, room):
        homeTeam, awayTeam = 0xffff, 0xffff
        if room.teamSelection:
            homeTeam = (room.teamSelection.home_team_id
            if room.teamSelection.home_team_id != None else 0xffff)
            awayTeam = (room.teamSelection.away_team_id
            if room.teamSelection.away_team_id != None else 0xffff)
        (homeGoals1st, homeGoals2nd, homeGoalsEt1, 
         homeGoalsEt2, homeGoalsPen) = 0, 0, 0, 0, 0
        (awayGoals1st, awayGoals2nd, awayGoalsEt1, 
         awayGoalsEt2, awayGoalsPen) = 0, 0, 0, 0, 0
        if room.match:
            homeGoals1st = room.match.score_home_1st
            homeGoals2nd = room.match.score_home_2nd
            homeGoalsEt1 = room.match.score_home_et1
            homeGoalsEt2 = room.match.score_home_et2
            homeGoalsPen = room.match.score_home_pen
            awayGoals1st = room.match.score_away_1st
            awayGoals2nd = room.match.score_away_2nd
            awayGoalsEt1 = room.match.score_away_et1
            awayGoalsEt2 = room.match.score_away_et2
            awayGoalsPen = room.match.score_away_pen
        return b'%s%s%s%s%s%s%s%s%s%s%s%s' % (
            struct.pack('!H', homeTeam),
            struct.pack('!B', homeGoals1st), # 1st
            struct.pack('!B', homeGoals2nd), # 2nd
            struct.pack('!B', homeGoalsEt1), # et1
            struct.pack('!B', homeGoalsEt2), # et2
            struct.pack('!B', homeGoalsPen), # pen
            struct.pack('!H', awayTeam),
            struct.pack('!B', awayGoals1st), # 1st
            struct.pack('!B', awayGoals2nd), # 2nd
            struct.pack('!B', awayGoalsEt1), # et1
            struct.pack('!B', awayGoalsEt2), # et2
            struct.pack('!B', awayGoalsPen)) # pen

    def formatRoomInfo(self, room):
        n = len(room.players)
        if room.match:
            match_state = room.match.state
            match_clock = room.match.clock
        else:
            match_state, match_clock = 0, 0
        return b'%s%s%s%s%s%s%s%s%s%s%s' % (
            struct.pack('!i',room.id),
            struct.pack('!B',room.phase),
            struct.pack('!B',match_state),
            util.padWithZeros(room.name,64),
            struct.pack('!B',match_clock),
            b''.join([b'%s%s%s%s%s%s%s' % (
                struct.pack('!i',usr.profile.id),
                struct.pack('!B',room.isOwner(usr)),
                # matchstarter or 1st host?
                struct.pack('!B',room.isMatchStarter(usr)), 
                struct.pack('!B',self.formatHomeOrAway(room, usr)), # team
                struct.pack('!B',usr.state.spectator), # spectator
                struct.pack('!B',room.getPlayerPosition(usr)), # pos in room
                struct.pack('!B',room.getPlayerParticipate(usr))) # participate
                for usr in room.players]),
            b'\0\0\0\0\0\0\xff\0\0\xff'*(4-n), # empty players
            self.formatTeamsAndGoals(room),
            b'\0', #padding
            struct.pack('!B', int(room.usePassword)), # room locked
            b'\0\x02\0\0') # competition flag, match chat setting, 2 unknowns
            
    def formatRoomParticipationStatus(self, room):
        """
        Used to format the 0x4365 payload
        """
        
        n = len(room.players)
        data = b'%s%s' % (
            b''.join(['%s%s%s' % (
                struct.pack('!i',usr.profile.id),
                struct.pack('!B',room.getPlayerPosition(usr)),
                struct.pack('!B',room.getPlayerParticipate(usr)))
                for usr in room.players]),
            b'\0\0\0\0\0\xff'*(4-n))
        return data        

    def becomeSpectator_4366(self, pkt):
        self._user.state.spectator = 1
        self.sendZeros(0x4367, 4)

    def do_4351(self, pkt):
        """
        Contains connection information of playing players
        Received from hosting player
        Send to possible spectators
        """
        data = bytes(pkt.data)
        room = self._user.state.room
        if room:
            spectatingPlayers = (player for player in room.players 
                if player not in room.participatingPlayers)
            for player in spectatingPlayers:
                player.sendData(0x4351, data)
        self.sendZeros(0x4352, 4)

    def backToMatchMenu_4383(self, pkt):
        """
        Contains old,added,new points & rating
        For players and groups
        """
        room = self._user.state.room
        n = len(room.participatingPlayers)
        data = b'\0\0\0\0%s%s%s' % (
            b''.join([b'%s%s%s%s%s%s%s%s%s' % (
                struct.pack('!i',usr.profile.id),
                struct.pack('!H',0), # added points
                struct.pack('!i',0), # new points
                struct.pack('!H',0), # ?
                struct.pack('!H',0), # ?
                struct.pack('!H',0), # ?
                struct.pack('!H',0), # ?
                struct.pack('!H',0), # new rating
                struct.pack('!H',0)) # old rating
                for usr in room.participatingPlayers]),
            b'\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0'*(4-n),
            b''.join(b'%s%s%s%s%s%s' % (
                struct.pack('!i',0), # group1 id
                struct.pack('!H',0), # group1 added points
                struct.pack('!i',0), # group1 new points
                struct.pack('!i',0), # group2 id
                struct.pack('!H',0), # group2 added points
                struct.pack('!i',0)))) # group2 new points
        self.sendData(0x4384, data)

    def quickGameSearch_6020(self, pkt):
        self.sendZeros(0x6021,0)

    def getStunInfo_4345(self, pkt):    
        self.sendZeros(0x4346, 0)
        roomId = struct.unpack('!i',pkt.data[0:4])[0]
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        room = thisLobby.getRoomById(roomId)
        if room is not None:
            # send stun info of players in room to requester
            for usr in room.players:
                data = (b'%(pad1)s%(ip1)s%(port1)s'
                    b'%(ip2)s%(port2)s%(id)s'
                    b'%(someField)s%(participate)s') % {
                b'pad1': b'\0'*32,
                b'ip1': util.padWithZeros(usr.state.ip1, 16),
                b'port1': struct.pack('!H', usr.state.udpPort1),
                b'ip2': util.padWithZeros(usr.state.ip2, 16),
                b'port2': struct.pack('!H', usr.state.udpPort2),
                b'id': struct.pack('!i', usr.profile.id),
                b'someField': struct.pack('!H', 0),
                b'participate': struct.pack('!B', 
                    room.getPlayerParticipate(usr)),
                }
                self.sendData(0x4347, data)
                self.do_4330(room)
        self.sendZeros(0x4348, 0)        

    def chat_4400(self, pkt):
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        chatType = pkt.data[0:2]
        message = util.stripZeros(pkt.data[10:])
        data = b'%s%s%s%s%s' % (
                chatType,
                pkt.data[2:6],
                struct.pack('!i',self._user.profile.id),
                util.padWithZeros(self._user.profile.name,48),
                #util.padWithZeros(message, 128))
                message[:126]+b'\0\0')
        if chatType==b'\x00\x01':
            # add to lobby chat history
            thisLobby.addToChatHistory(
                lobby.ChatMessage(self._user.profile, message.decode('utf-8')))
            # lobby chat
            for usr in thisLobby.players.values():
                usr.sendData(0x4402, data)
        elif chatType==b'\x01\x08':
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
        elif chatType==b'\x01\x05':
            # match chat
            room = self._user.state.room
            if room:
                for usr in room.players:
                    usr.sendData(0x4402, data)
        elif chatType==b'\x01\x07':
            # stadium chat    
            room = self._user.state.room
            if room:
                for usr in room.players:
                    usr.sendData(0x4402, data)

    def sendChatHistory(self, aLobby, who):
        if aLobby is None or who is None:
            return
        for chatMessage in list(aLobby.chatHistory):
            chatType = b'\0\1'
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
                    util.padWithZeros(chatMessage.fromProfile.name,48),
                    chatMessage.text.encode('utf-8')[:126]+b'\0\0')
            who.sendData(0x4402, data)

    def broadcastSystemChat(self, aLobby, text):
        chatMessage = lobby.ChatMessage(lobby.SYSTEM_PROFILE, text)
        for usr in aLobby.players.values():
            data = b'%s%s%s%s%s' % (
                    b'\0\1',
                    b'\0\0\0\0',
                    struct.pack('!i', chatMessage.fromProfile.id),
                    util.padWithZeros(chatMessage.fromProfile.name,48),
                    chatMessage.text.encode('utf-8')[:126]+b'\0\0')
            usr.sendData(0x4402, data)
        aLobby.addToChatHistory(chatMessage)

    def broadcastRoomChat(self, room, text):
        chatMessage = lobby.ChatMessage(lobby.SYSTEM_PROFILE, text)
        for usr in room.players:
            data = b'%s%s%s%s%s' % (
                    b'\x01\x08',
                    b'\0\0\0\0',
                    struct.pack('!i', chatMessage.fromProfile.id),
                    util.padWithZeros(chatMessage.fromProfile.name,48),
                    chatMessage.text.encode('utf-8')[:126]+b'\0\0')
            usr.sendData(0x4402, data)
         
    def sendRoomUpdate(self, room):
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        data = self.formatRoomInfo(room)
        for usr in thisLobby.players.values():
            usr.sendData(0x4306,data)

    @defer.inlineCallbacks
    def sendPlayerUpdate(self, roomId):
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        stats = yield self.getStats(self._user.profile.id)
        data = self.formatPlayerInfo(self._user, roomId, stats)
        for usr in thisLobby.players.values():
            usr.sendData(0x4222,data)

    @defer.inlineCallbacks
    def getUserList_4210(self, pkt):
        self.sendZeros(0x4211,4)
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        for usr in thisLobby.players.values():
            if usr.state.inRoom == 1:
                roomId = usr.state.room.id
            else:
                roomId = 0
            stats = yield self.getStats(usr.profile.id)
            data = self.formatPlayerInfo(usr, roomId, stats)
            self.sendData(0x4212,data)
        self.sendZeros(0x4213,4)
        yield defer.succeed(None)

    def createRoom_4310(self, pkt):
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        roomName = util.stripZeros(pkt.data[0:64])
        try: 
            existing = thisLobby.getRoom(roomName)
            self.sendData(0x4311,b'\xff\xff\xff\x10')
        except KeyError:
            room = lobby.Room(thisLobby)
            room.name = roomName
            room.usePassword = struct.unpack('!B',pkt.data[64:65])[0] == 1
            if room.usePassword:
                room.password = util.stripZeros(pkt.data[65:80])
            # put room creator into the room
            room.enter(self._user)
            # add room to the lobby
            thisLobby.addRoom(room)
            log.msg('Room created: %s' % repr(room))
            # notify all users in the lobby about the new room
            self.sendRoomUpdate(room)
            # notify all users in the lobby that player is now in a room
            self.sendPlayerUpdate(room.id)
            self.sendZeros(0x4311,4)
        
    def getRoomList_4300(self, pkt):
        self.sendZeros(0x4301,4)
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        for room in thisLobby.rooms.values():
            data = self.formatRoomInfo(room)
            self.sendData(0x4302, data)
        self.sendZeros(0x4303,4)

    def setOwner_4349(self, pkt):
        newOwnerProfileId = struct.unpack('!i',pkt.data[0:4])[0]
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        room = self._user.state.room
        if room:
            usr = thisLobby.getPlayerByProfileId(newOwnerProfileId)
            if not usr:
                log.msg('WARN: player %s cannot become owner: not in the room.')
            else:
                room.setOwner(usr)
                self.sendRoomUpdate(room)
        self.sendZeros(0x434a,4)

    def setRoomName_434d(self, pkt):
        newName = util.stripZeros(pkt.data[0:63])
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        room = self._user.state.room
        data = b'\0\0\0\0'
        if room:
            if newName != room.name:
                # prevent renaming to existing rooms
                if thisLobby.isRoom(newName):
                    data = b'\xff\xff\xff\xff'
                else:
                    thisLobby.renameRoom(room, newName)
            room.usePassword = struct.unpack('!B',pkt.data[64:65])[0] == 1
            if room.usePassword:
                room.password = util.stripZeros(pkt.data[65:80])            
            self.sendRoomUpdate(room)
        self.sendData(0x434e,data)
        
    def do_4330(self, room):
        """
        Notify people INSIDE room of
        ip,ports and participation status
        """
        for otherUsr in room.players:
            if otherUsr == self._user:
                continue
            data = (b'%(pad1)s%(ip1)s%(port1)s'
            b'%(ip2)s%(port2)s%(id)s'
            b'%(someField)s%(participate)s') % {
            b'pad1': b'\0'*36,
            b'ip1': util.padWithZeros(self._user.state.ip1, 16),
            b'port1': struct.pack('!H', self._user.state.udpPort1),
            b'ip2': util.padWithZeros(self._user.state.ip2, 16),
            b'port2': struct.pack('!H', self._user.state.udpPort2),
            b'id': struct.pack('!i', self._user.profile.id),
            b'someField': struct.pack('!H', 0),
            b'participate': struct.pack('!B', 
                room.getPlayerParticipate(self._user)),
            }
            otherUsr.sendData(0x4330, data)        

    def joinRoom_4320(self, pkt):
        roomId = struct.unpack('!i',pkt.data[0:4])[0]
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        room = thisLobby.getRoomById(roomId)
        if room is None:
            log.msg('ERROR: Room (id=%d) does not exist.' % roomId)
            self.sendData(0x4321,b'\0\0\0\1')
        else:
            if room.usePassword:
                enteredPassword = util.stripZeros(pkt.data[4:19])
                if enteredPassword != room.password:
                    log.msg(
                        'ERROR: Room (id=%d) password does not match.' % roomId)
                    self.sendData(0x4321,b'\xff\xff\xfd\xda')
                else:
                    room.enter(self._user)
            else:
                room.enter(self._user)
                
            self.sendRoomUpdate(room)
            self.sendPlayerUpdate(room.id)
            data = b'\0\0\0\0'
            if room.matchSettings:
                data += room.matchSettings.match_time
            self.sendData(0x4321, data)
        # give players in room stun of joiner
        # special 4330 packet
        self.do_4330(room)
        # give joiner stun of players in room
        self.sendZeros(0x4346, 0)
        for otherUsr in room.players:
            if otherUsr == self._user:
                continue
            data = (b'%(pad1)s%(ip1)s%(port1)s'
            b'%(ip2)s%(port2)s%(id)s'
            b'%(someField)s%(participate)s') % {
            b'pad1': b'\0'*32,
            b'ip1': util.padWithZeros(otherUsr.state.ip1, 16),
            b'port1': struct.pack('!H', otherUsr.state.udpPort1),
            b'ip2': util.padWithZeros(otherUsr.state.ip2, 16),
            b'port2': struct.pack('!H', otherUsr.state.udpPort2),
            b'id': struct.pack('!i', otherUsr.profile.id),
            b'someField': struct.pack('!H', 0),
            b'participate': struct.pack('!B', 
                room.getPlayerParticipate(otherUsr)),
            }
            self.sendData(0x4347, data)
        self.sendZeros(0x4348, 0)

    def exitingLobby(self, usr):
        usrLobby = self.factory.getLobbies()[usr.state.lobbyId]
        usrLobby.exit(usr)
        # user now considered OFFLINE
        self.factory.userOffline(usr)
        # notify every remaining occupant in the lobby
        for otherUsr in usrLobby.players.values():
            otherUsr.sendData(0x4221,struct.pack('!i', usr.profile.id))
 
    def exitingRoom(self, room, usr):
        usrLobby = self.factory.getLobbies()[usr.state.lobbyId]
        room = usr.state.room
        room.exit(usr)
        
        self.sendRoomUpdate(room)
        self.sendPlayerUpdate(room.id)
        self.sendZeros(0x432b,4)

        # destroy the room, if none left in it
        if room.isEmpty():
            # notify users in lobby that the room is gone
            data = struct.pack('!i',room.id)
            for otherUsr in usrLobby.players.values():
                otherUsr.sendData(0x4305,data)
            usrLobby.deleteRoom(room)

    def exitRoom_432a(self, pkt):
        if self._user.state.inRoom == 0:
            log.msg('WARN: user not in a room.')
            self.sendZeros(0x432b,4)
        else:
            return self.exitingRoom(
                self._user.state.room, self._user)
  
    def toggleParticipate_4363(self, pkt):
        participate = (struct.unpack('!B', pkt.data[0:1])[0] == 1)
        room = self._user.state.room
        packetPayload = b'\0\0\0\0' # success
        if room:
            if participate:
                # check roster-hash match with host
                rosterHashMismatch = False
                if room.participatingPlayers:
                    gameHost = room.participatingPlayers[0]
                    rosterHashMismatch = (
                        room.lobby.checkRosterHash and not self.checkHashes(
                            gameHost, self._user))
                if rosterHashMismatch:
                    packetPayload = b'\0\0\0\1'
                    text = (
                        'Roster mismatch: %s vs %s. '
                        'Player %s cannot participate.' % (
                            gameHost.profile.name,
                            self._user.profile.name,
                            self._user.profile.name))
                    log.msg(text)
                    self.broadcastRoomChat(room, text.encode('utf-8'))
                elif room.isForcedCancelledParticipation(self._user):
                    packetPayload = b'\xff\xff\xfd\xb6' # still cancelled
                else:
                    room.participate(self._user)
            else:
                room.cancelParticipation(self._user)
            # share participation status with players in room
            data = self.formatRoomParticipationStatus(room)
            for player in room.players:
                player.sendData(0x4365, data)
        data = b'%s%s%s' % (
               packetPayload,
               struct.pack('!B', participate),
               struct.pack('!B', room.getPlayerParticipate(self._user)))
        self.sendData(0x4364, data)
        
    def forcedCancelParticipation_4380(self, pkt):
        profileId = struct.unpack('!i',pkt.data[0:4])[0]
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        room = self._user.state.room
        if room:
            usr = thisLobby.getPlayerByProfileId(profileId)
            room.cancelParticipation(usr)
            usr.state.timeCancelledParticipation = datetime.now()
            data = self.formatRoomParticipationStatus(room)
            for player in room.players:                
                player.sendData(0x4365, data)
        self.sendZeros(0x4381,4)


    def startMatch_4360(self, pkt):
        thisLobby = self.factory.getLobbies()[self._user.state.lobbyId]
        room = self._user.state.room
        if room:
            data = b'%s%s' % (
                b'\x02',
                b''.join([b'%s' % (
                    struct.pack('!i',usr.profile.id))
                    for usr in room.participatingPlayers]))
            data = util.padWithZeros(data, 37)        
            for player in room.players:
                player.sendData(0x4362, data)
            
            # Tell everyone of new phase of room
            room.phase = lobby.RoomState.ROOM_MATCH_SIDE_SELECT
            room.setMatchStarter(self._user)
            room.readyCount = 0
            self.sendRoomUpdate(room)
        self.sendZeros(0x4361, 4)
        
    def updateRoomPhase(self, room):
        if room.readyCount == len(room.participatingPlayers):
            room.phase += 1
            
            data = struct.pack('B', room.phase)
            for usr in room.players:
                usr.sendData(0x4344, data)
            # reset count
            room.readyCount = 0
            # Tell everyone of new phase of room
            self.sendRoomUpdate(room)
        
    def toggleReady_436f(self, pkt):
        payload = struct.unpack('!B', pkt.data[0:1])[0]
        room = self._user.state.room
        if room:
            # phase 2-6: match not really started
            if room.isAtPregameSettings(room):
                if payload == 1:
                    room.readyCount += 1
                elif payload == 0:
                    room.readyCount -= 1
            
            # phase 7-8: match finished
            elif room.phase > lobby.RoomState.ROOM_MATCH_FORMATION_SELECT:
                # exit match
                if payload == 0:
                    room.cancelParticipation(self._user)
                    if len(room.participatingPlayers) == 0:
                        room.phase = lobby.RoomState.ROOM_IDLE
                        room.match = None
                    else: # there's still a player in the endmatch screen
                        room.phase = lobby.RoomState.ROOM_MATCH_SERIES_ENDING
                # play again different teams
                elif payload == 3:
                    room.phase = lobby.RoomState.ROOM_MATCH_TEAM_SELECT
                    room.match = None
                # play again same teams
                elif payload == 4:
                    room.phase = lobby.RoomState.ROOM_MATCH_FORMATION_SELECT
                    room.match = None
                self.sendRoomUpdate(room)
                    
            for usr in room.players:
                if usr == self._user:
                    continue
                data = b'%s%s' % (
                    struct.pack('!i',self._user.profile.id),
                    pkt.data[0])
                usr.sendData(0x4371, data)
        self.sendZeros(0x4370,4)

        # if all participating players are ready, next screen
        if room.isAtPregameSettings(room):
            self.updateRoomPhase(room)

            
    @defer.inlineCallbacks
    def setPlayerSettings_4369(self, pkt):
        # Packet contains which players are in team1 & team2
        self.sendZeros(0x436a, 4)
        room = self._user.state.room
        for usr in room.players:
            data = b'%s%s' % (
                b'\0',
                pkt.data)
            usr.sendData(0x436b, data)
        # create new TeamSelection object
        room.teamSelection = lobby.TeamSelection()
        for x in range(4):
            profile_id = struct.unpack('!i',pkt.data[x*8:x*8+4])[0]
            away = b'\x01'==pkt.data[x*8+4]
            if profile_id!=0:
                profile = yield self.factory.getPlayerProfile(profile_id)
                if x in [0,1]:
                    if not away:
                        room.teamSelection.home_captain = profile
                    else:
                        room.teamSelection.away_captain = profile
                else:
                    if not away:
                        room.teamSelection.home_more_players.append(profile)
                    else:
                        room.teamSelection.away_more_players.append(profile)
        self.sendRoomUpdate(room)

    def setGameSettings_436c(self, pkt):
        # Packet contains game settings(time,injuries,penalty etcetera)
        self.sendZeros(0x436d, 4)
        room = self._user.state.room
        data = bytes(pkt.data)
        room.matchSettings = lobby.MatchSettings(*pkt.data)
        for usr in room.players:
            usr.sendData(0x436e, data)
        self.sendRoomUpdate(room)

    def goalScored_4375(self, pkt):
        room = self._user.state.room
        if not room.match:
            log.msg('ERROR: Goal reported, but no match in the room.')
        else:
            if pkt.data[0] == 0:
                log.msg('GOAL SCORED by HOME team %d (%s)' % (
                    room.teamSelection.home_team_id, 
                    getHomePlayerNames(room.match)))
                room.match.goalHome()
            else:
                log.msg('GOAL SCORED by AWAY team %d (%s)' % (
                    room.teamSelection.away_team_id, 
                    getAwayPlayerNames(room.match)))
                room.match.goalAway()
            log.msg(
                'UPDATE: Team %d (%s) vs Team %d (%s) - %d:%d (in progress)' % (
                    room.teamSelection.home_team_id, 
                    getHomePlayerNames(room.match),
                    room.teamSelection.away_team_id, 
                    getAwayPlayerNames(room.match),
                    room.match.score_home, room.match.score_away))
        self.sendZeros(0x4376, 4)
        # let others in the lobby know
        self.sendRoomUpdate(room)

    def matchClockUpdate_4385(self, pkt):
        clock = struct.unpack('!B', pkt.data[0:1])[0]
        room = self._user.state.room
        if not room or not room.match:
            log.msg('ERROR: got clock update, but no match')
        else:
            room.match.clock = clock
            log.msg('CLOCK: Team %d (%s) vs Team %d (%s). Minute: %d' % (
                room.teamSelection.home_team_id, 
                getHomePlayerNames(room.match),
                room.teamSelection.away_team_id, 
                getAwayPlayerNames(room.match),
                room.match.clock))
        self.sendZeros(0x4386, 4)
        # let others in the lobby know
        self.sendRoomUpdate(room)

    @defer.inlineCallbacks
    def recordMatchResult(self, room):
        match = room.match
        duration = datetime.now() - match.startDatetime
        log.msg('MATCH FINISHED: '
                'Team %d (%s) - Team %d (%s)  %d:%d. '
                'Match time: %s.' % (
            match.teamSelection.home_team_id, getHomePlayerNames(match),
            match.teamSelection.away_team_id, getAwayPlayerNames(match),
            match.score_home, match.score_away,
            duration))
        # check if match result should be stored
        thisLobby = self.factory.getLobbies()[
            self._user.state.lobbyId]
        if thisLobby.typeCode != 0x20: # no-stats
            # record the match in DB
            yield self.factory.matchData.store(match)
            participants = [match.teamSelection.home_captain,
                match.teamSelection.away_captain]
            participants.extend(match.teamSelection.home_more_players)
            participants.extend(match.teamSelection.away_more_players)
            for profile in participants:
                # update player play time
                profile.playTime += duration
                # re-calculate points
                stats = yield self.getStats(profile.id)
                rm = self.factory.ratingMath
                profile.points = rm.getPoints(stats)
                # store updated profile
                yield self.factory.storeProfile(profile)
        else:
            yield defer.succeed(None)

    def matchStateUpdate_4377(self, pkt):
        state = struct.unpack('!B', pkt.data[0:1])[0]
        room = self._user.state.room
        if not room or not room.teamSelection:
            log.msg(
                'ERROR: got match state update, '
                'but no room or team-selection')
        else:
            if room.match is not None:
                room.match.state = state
            # check if match just started
            if state == lobby.MatchState.FIRST_HALF:
                match = lobby.Match6(room.teamSelection)
                log.msg('NEW MATCH started: Team %d (%s) vs Team %d (%s)' % (
                    room.teamSelection.home_team_id, 
                    getHomePlayerNames(room),
                    room.teamSelection.away_team_id,
                    getAwayPlayerNames(room)))
                match.startDatetime = datetime.now()
                match.home_team_id = match.teamSelection.home_team_id
                match.away_team_id = match.teamSelection.away_team_id
                room.match = match
                room.match.state = state
            # check if match is done
            elif state == lobby.MatchState.FINISHED and room.match:
                room.phase = lobby.RoomState.ROOM_MATCH_FINISHED
                self.recordMatchResult(room)
            # let others in the lobby know
            self.sendRoomUpdate(room)
        self.sendZeros(0x4378, 4)

    def teamSelected_4373(self, pkt):
        team = struct.unpack('!H', pkt.data[0:2])[0]
        log.msg('Team selected: %d' % team)
        room = self._user.state.room
        if not room.teamSelection:
            log.msg('ERROR: room has no TeamSelection object')
        else:
            ts = room.teamSelection
            if self._user.profile.id == ts.home_captain.id:
                ts.home_team_id = team
            elif self._user.profile.id == ts.away_captain.id:
                ts.away_team_id = team
        self.sendData(0x4374,b'\0\0\0\0')
        self.sendRoomUpdate(room)

    @defer.inlineCallbacks
    def setComment_4110(self, pkt):
        self._user.profile.comment = pkt.data
        yield self.factory.storeProfile(self._user.profile)
        self.sendZeros(0x4111,4)

    def relayRoomSettings_4350(self, pkt):
        if not self._user.state:
            return
        room = self._user.state.room
        if room:
            if pkt.data[0:4] == b'\0\0\1\3': #TODO clean this up (3 - phase?)
                # extract info that we care about
                room.matchTime = 5*(struct.unpack('!B', pkt.data[12])[0] + 1)
                log.msg('match time set to: %d minutes' % room.matchTime)
            # send to others
            for usr in self._user.state.room.players:
                if usr == self._user:
                    continue
                usr.sendData(0x4350, pkt.data)

    def do_3087(self, pkt):
        """
        Do nothing.
        Overriden here to mask pes5 logic
        """
    
    def register(self):
        pes5.MainService.register(self)
        self.addHandler(0x6020, self.quickGameSearch_6020)
        self.addHandler(0x4110, self.setComment_4110)
        self.addHandler(0x4345, self.getStunInfo_4345)
        self.addHandler(0x4400, self.chat_4400)
        self.addHandler(0x4310, self.createRoom_4310)
        self.addHandler(0x4300, self.getRoomList_4300)
        self.addHandler(0x4320, self.joinRoom_4320)
        self.addHandler(0x4363, self.toggleParticipate_4363)
        self.addHandler(0x4360, self.startMatch_4360)
        self.addHandler(0x436f, self.toggleReady_436f)
        self.addHandler(0x4369, self.setPlayerSettings_4369)
        self.addHandler(0x436c, self.setGameSettings_436c)
        self.addHandler(0x4373, self.teamSelected_4373)
        self.addHandler(0x4375, self.goalScored_4375)
        self.addHandler(0x4377, self.matchStateUpdate_4377)
        self.addHandler(0x4385, self.matchClockUpdate_4385)
        self.addHandler(0x4349, self.setOwner_4349)
        self.addHandler(0x434d, self.setRoomName_434d)
        self.addHandler(0x4366, self.becomeSpectator_4366)
        self.addHandler(0x4351, self.do_4351)
        self.addHandler(0x4383, self.backToMatchMenu_4383)
        self.addHandler(0x4380, self.forcedCancelParticipation_4380)

