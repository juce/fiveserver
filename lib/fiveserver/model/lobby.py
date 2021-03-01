"""
Lobby and related classes
"""

from datetime import datetime, timedelta
import struct
import random

from fiveserver import log
from fiveserver.model import util, user


MAX_MESSAGES = 50
MAX_AGE_DAYS = 5

SYSTEM_PROFILE = user.Profile(0)
SYSTEM_PROFILE.name = 'SYSTEM'
SYSTEM_PROFILE.id = 0

SECONDS_CANCELLED_FORCED_PARTICIATION = 10

class ChatMessage:

    def __init__(self, fromProfile, text, toProfile=None, special=None):
        self.fromProfile = fromProfile
        self.text = text
        self.toProfile = toProfile
        self.special = special
        self.timestamp  = datetime.now()


class Lobby:

    def __init__(self, name, maxPlayers):
        self.name = name
        self.maxPlayers = maxPlayers
        self.players = dict()
        self.rooms = dict()
        self.typeStr = None
        self.typeCode = 0
        self.showMatches = True
        self.checkRosterHash = True
        self.roomOrdinal = 0
        self.chatHistory = list()

    def __bytes__(self):
        """
        return serialized representation to be used in packets
        """
        return b'%s%s%s' % (
                struct.pack('!B',self.typeCode),
                util.padWithZeros(self.name,32),
                struct.pack('!H',len(self.players)))

    def getPlayerByProfileId(self, id):
        for usr in self.players.values():
            if usr.profile.id == id:
                return usr
        return None

    def addToChatHistory(self, chatMessage):
        self.chatHistory.append(chatMessage)
        # keep only last MAX_MESSAGES messages. We don't want this
        # to be a memory leak
        del self.chatHistory[0:-MAX_MESSAGES] 

    def purgeOldChat(self):
        """
        This method should be called periodically to purge
        old chat messages. (It may be that there is no 
        conversation going on, and displaying messages that
        are over week old is probably useless)
        """
        newHistory = []
        now = datetime.now()
        maxAge = timedelta(days=MAX_AGE_DAYS)
        for chatMessage in self.chatHistory:
            age = now - chatMessage.timestamp 
            if age < maxAge:
                newHistory.append(chatMessage)
        self.chatHistory = newHistory

    def addRoom(self, room):
        self.roomOrdinal += 1
        room.id = self.roomOrdinal
        self.rooms[room.name] = room

    def renameRoom(self, room, newName):
        try:
            del self.rooms[room.name]
            oldName, room.name = room.name, newName
            self.rooms[room.name] = room
            log.msg('Room(id=%d, name=%s) was renamed to: %s' % (
                room.id, oldName, room.name))
        except KeyError:
            log.msg('Room(id=%d, name=%s) cannot be renamed. '
                    'This lobby does not know anything about it' % (
                room.id, room.name))

    def deleteRoom(self, room):
        try: 
            del self.rooms[room.name]
            log.msg('Room(id=%d, name=%s) destroyed' % (
                    room.id, room.name))
        except KeyError:
            pass

    def getRoom(self, name):
        return self.rooms[name]

    def getRoomById(self, roomId):
        for room in self.rooms.values():
            if room.id == roomId:
                return room
        return None
        
    def isRoom(self, name):
        return self.rooms.has_key(name)

    def enter(self, usr, lobbyConnection):
        usr.lobbyConnection = lobbyConnection
        self.players[usr.hash] = usr

    def exit(self, usr):
        try: del self.players[usr.hash]
        except KeyError:
            pass
        usr.lobbyConnection = None


class Room:

    def __init__(self, lobby=None):
        self.id = 0
        self.name = 'unnamed'
        self.matchTime = 5
        self.matchSettings = None
        self.usePassword = False
        self.password = None
        self.players = list()
        self.readyCount = 0
        self.owner = None
        self.match = None
        self.matchStarter = None
        self.teamSelection = None
        self.lobby = lobby
        
        self.participatingPlayers = list()
        self.phase = 1 # Phase of room and used in 0x4344

    def __cmp__(self, another):
        if another is None:
            return -1
        if isinstance(another, Room):
            if self.match is not None and another.match is not None:
                if self.match.startDatetime is None:
                    return 1
                if another.match.startDatetime is None:
                    return -1
                return -cmp(
                    self.match.startDatetime,
                    another.match.startDatetime)
        return 0

    def enter(self, usr):
        usr.state.inRoom = 1
        usr.state.room = self
        usr.state.spectator = 0
        usr.state.timeCancelledParticipation = None
        if not self.players:
            self.owner = usr
        self.players.append(usr)

    def exit(self, usr):
        usr.state.inRoom = 0
        usr.state.noLobbyChat = 0
        usr.state.room = None
        try: 
            exiting = self.players.pop(self.getPlayerPosition(usr))
        except ValueError:
            log.msg(
                'WARN: player (%s) exiting, but was not in the room' % (
                    usr.profile.name))
        else:
            if self.isOwner(exiting):
                # owner is exiting: assign new owner, if anybody
                # is still left in the room.
                if self.players:
                    self.setOwner(self.players[0])

    def getPlayerPosition(self, usr):
        return self.players.index(usr)
        
    def getPlayerParticipate(self, usr):
        try:
            return self.participatingPlayers.index(usr)
        except ValueError:
            return 0xff

    def participate(self, usr):
        try:
            return self.participatingPlayers.index(usr)
        except ValueError:
            self.participatingPlayers.append(usr)
            return len(self.participatingPlayers)-1

    def cancelParticipation(self, usr):
        try:
            self.participatingPlayers.pop(
                self.participatingPlayers.index(usr))
        except ValueError:
            log.msg(
                'WARN player (%s) is cancelling participation, '
                'but was not among participants.' % (
                    usr.profile.name))
        return 0xff
    
    def isForcedCancelledParticipation(self, usr):
        if usr.state.timeCancelledParticipation is not None:
            duration = datetime.now() - usr.state.timeCancelledParticipation
            if duration.seconds > SECONDS_CANCELLED_FORCED_PARTICIATION:
                usr.state.timeCancelledParticipation = None
                return False
            return True
        return False

    def setOwner(self, usr):
        self.owner = usr

    def isOwner(self, usr):
        if self.owner is None:
            return False
        return self.owner.profile.name == usr.profile.name
        
    def setMatchStarter(self, usr):
        self.matchStarter = usr
        
    def isMatchStarter(self, usr):
        if self.matchStarter is None:
            return False
        return self.matchStarter.profile.name == usr.profile.name

    def isEmpty(self):
        if self.players:
            return False
        return True
    
    def isAtPregameSettings(self, room):
        return RoomState.ROOM_IDLE < room.phase < RoomState.ROOM_MATCH_STARTED
    
    def __repr__(self):
        return 'Room(id=%d, name="%s", players=%d)' % (
                self.id, self.name, len(self.players))


class MatchSettings:
    """
    Holds match settings
    """
    
    def __init__(self, match_time, time_limit, number_of_pauses,
                 chat_during_gameplay, condition, injuries,
                 max_no_of_substitutions, match_type_ex, match_type_pk,
                 time, season, weather, *unknown):
        self.match_time = match_time
        self.time_limit = time_limit
        self.number_of_pauses = number_of_pauses
        self.chat_during_gameplay = chat_during_gameplay
        self.condition = condition
        self.injuries = injuries
        self.max_no_of_substitutions = max_no_of_substitutions
        self.match_type_ex = match_type_ex
        self.match_type_pk = match_type_pk
        self.time = time
        self.season = season
        self.weather = weather

class RoomState:
    """
    Holds room state constants
    """
    
    ROOM_IDLE = 1
    ROOM_MATCH_SIDE_SELECT = 2
    ROOM_MATCH_SETTINGS_SELECT = 3
    ROOM_MATCH_TEAM_SELECT = 4
    ROOM_MATCH_STRIP_SELECT = 5
    ROOM_MATCH_FORMATION_SELECT = 6
    ROOM_MATCH_STARTED = 7
    ROOM_MATCH_FINISHED = 8
    ROOM_MATCH_SERIES_ENDING = 10
    
    stateText = {
        ROOM_IDLE: 'Room idle',
        ROOM_MATCH_SIDE_SELECT: 'Sides selection',
        ROOM_MATCH_SETTINGS_SELECT: 'Match settings',
        ROOM_MATCH_TEAM_SELECT: 'Team selection',
        ROOM_MATCH_STRIP_SELECT: 'Strip/kit selection',
        ROOM_MATCH_FORMATION_SELECT: 'Formation settings',
        ROOM_MATCH_STARTED: 'Match started',
        ROOM_MATCH_FINISHED: 'Match finished',
        ROOM_MATCH_SERIES_ENDING: 'Match series ended'
    }

class MatchState:
    """
    Holds state constants
    """

    NOT_STARTED = 0
    FIRST_HALF = 1
    HALF_TIME = 2
    SECOND_HALF = 3
    BEFORE_EXTRA_TIME = 4
    ET_FIRST_HALF = 5
    ET_BREAK = 6
    ET_SECOND_HALF = 7
    BEFORE_PENALTIES = 8
    PENALTIES = 9
    FINISHED = 10

    stateText = {
        NOT_STARTED: 'Not started',
        FIRST_HALF: '1st half',
        HALF_TIME: 'Half-time',
        SECOND_HALF: '2nd half',
        BEFORE_EXTRA_TIME: 'Normal time finished',
        ET_FIRST_HALF: 'Extra-time 1st half',
        ET_BREAK: 'Extra-time intermission',
        ET_SECOND_HALF: 'Extra-time 2nd half',
        BEFORE_PENALTIES: 'Before penalties',
        PENALTIES: 'Penalties',
        FINISHED: 'Finished',
    }

    
class Match:

    def __init__(self, match=None):
        self.home_profile = None
        self.away_profile = None
        self.home_team_id = None
        self.away_team_id = None
        self.score_home = 0
        self.score_away = 0
        self.startDatetime = None
        self.home_exit = None
        self.away_exit = None
        if match is not None:
            if match.home_profile is not None:
                self.home_profile = match.home_profile
            if match.away_profile is not None:
                self.away_profile = match.away_profile
            if match.home_team_id is not None:
                self.home_team_id = match.home_team_id
            if match.away_team_id is not None:
                self.away_team_id = match.away_team_id


class TeamSelection:

    def __init__(self):
        self.participants = dict()
        self.home_team_id = None
        self.away_team_id = None
        self.home_captain = None
        self.away_captain = None
        # pes6 only: for 2v2, 2v1 or 3v1 matches
        self.home_more_players = [] 
        self.away_more_players = []
        
    def getHomeOrAway(self, usr):
        if (usr.profile.id == self.home_captain.id or 
            any(prof for prof in self.home_more_players 
                if prof.id == usr.profile.id)):
            return 0x00
        if (usr.profile.id == self.away_captain.id or 
            any(prof for prof in self.away_more_players 
                if prof.id == usr.profile.id)):
            return 0x01
        return 0xff

class Match6:

    def __init__(self, teamSelection):
        self.state = MatchState.NOT_STARTED
        self.clock = 0
        self.score_home_1st = 0
        self.score_home_2nd = 0
        self.score_home_et1 = 0
        self.score_home_et2 = 0
        self.score_home_pen = 0
        self.score_away_1st = 0
        self.score_away_2nd = 0
        self.score_away_et1 = 0
        self.score_away_et2 = 0
        self.score_away_pen = 0
        self.teamSelection = teamSelection
        self.startDatetime = None
        self.home_exit = None
        self.away_exit = None

    def getScoreHome(self):
        return (
            self.score_home_1st +
            self.score_home_2nd +
            self.score_home_et1 +
            self.score_home_et2 +
            self.score_home_pen)
    score_home = property(getScoreHome)

    def getScoreAway(self):
        return (
            self.score_away_1st +
            self.score_away_2nd +
            self.score_away_et1 +
            self.score_away_et2 +
            self.score_away_pen)
    score_away = property(getScoreAway)

    def goalHome(self):
        state = self.state
        if state == MatchState.FIRST_HALF:
            self.score_home_1st += 1
        elif state == MatchState.SECOND_HALF:
            self.score_home_2nd += 1
        elif state == MatchState.ET_FIRST_HALF:
            self.score_home_et1 += 1
        elif state == MatchState.ET_SECOND_HALF:
            self.score_home_et2 += 1
        elif state == MatchState.PENALTIES:
            self.score_home_pen += 1

    def goalAway(self):
        state = self.state
        if state == MatchState.FIRST_HALF:
            self.score_away_1st += 1
        elif state == MatchState.SECOND_HALF:
            self.score_away_2nd += 1
        elif state == MatchState.ET_FIRST_HALF:
            self.score_away_et1 += 1
        elif state == MatchState.ET_SECOND_HALF:
            self.score_away_et2 += 1
        elif state == MatchState.PENALTIES:
            self.score_away_pen += 1

