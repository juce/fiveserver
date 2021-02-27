"""
User-related data
"""

from datetime import timedelta
import struct
from fiveserver import log
from fiveserver.model import util


class Profile:

    def __init__(self, index):
        self.index = index   # 1
        self.id = 0          # 4
        self.name = ''       # 16 bytes
        self.favPlayer = 0   # 2 bytes, PES5 only
        self.favTeam = 0     # 2 bytes, PES5 only
        self.points = 0      # 4 bytes
        self.disconnects = 0 # 2 bytes
        self.userId = None
        self.rank = 0
        self.rating = 0 # PES6 only
        self.playTime = timedelta(seconds=0)
        self.settings = ProfileSettings(None, None)
        self.comment = None


class ProfileSettings:
    
    def __init__(self, settings1, settings2):
        self.settings1 = settings1
        self.settings2 = settings2


class UserInfo:

    def __init__(self, gameName, rosterHash):
        self.gameName = gameName
        self.rosterHash = rosterHash


class User:
    
    def __init__(self, hash):
        self.hash = hash
        self.configElement = None
        self.profiles = []
        self.lobbyOrdinal = None
        self.lobbyConnection = None
        self.gameVersion = None
        self.room = None
        self.nonce = None
        self.state = None
        self.needsLobbyChatReplay = False

    def sendData(self, packetId, data):
        if self.lobbyConnection is None:
            log.msg(
                'WARN: Cannot send data to user {%s}: '
                'no lobby connection' % self.hash)
        else:
            self.lobbyConnection.sendData(packetId, data)

    def getProfileById(self, profileId):
        for i, profile in enumerate(self.profiles):
            if profile.id == profileId:
                return i, profile
        return -1, None
            
    def getRoomId(self):
        try: return self.state.room.id
        except AttributeError:
            return 0


class UserState:
    """
    Encapsulate current state of the user:
    IP-addresses, ports, lobby Id, etc.
    """

    #def tostr(self, v):
    #    return util.stripZeros(str(v)).decode('utf-8')

    def __repr__(self):
        return 'UserState(%s)' % ','.join(["%s=%s" % (k,v) 
                for k,v in self.__dict__.items()])


class Stats:
    """
    Holder object of various stats for a user profile:
    wins, losses, draws, goals, etc.
    """

    def __init__(self, profile_id, wins, losses, draws,
                 goals_scored, goals_allowed,
                 streak_current, streak_best, teams=None):
        self.profile_id = profile_id
        self.wins = wins
        self.losses = losses
        self.draws = draws
        self.goals_scored = goals_scored
        self.goals_allowed = goals_allowed
        self.streak_current = streak_current
        self.streak_best = streak_best
        if not teams:
            self.teams = []
        else:
            self.teams = teams

