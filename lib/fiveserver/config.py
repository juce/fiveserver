"""
Configuration classes for packet server
"""


from twisted.internet import reactor, defer
from twisted.web import client
from xml.dom import minidom
from datetime import datetime, timedelta
import time
import random
import struct
import socket

from fiveserver.model import lobby, user
from fiveserver import storagecontroller, errors, rating, log
import yaml
import os


class YamlConfig:
    def __init__(self, yamlFile, newYamlFile=None):
        self._cfg = dict()
        if yamlFile is not None:
            self._yamlFile = yamlFile
            inf = open(yamlFile)
            cfg = yaml.load(inf.read(), Loader=yaml.SafeLoader)
            inf.close()
            if cfg is not None:
                self._cfg.update(cfg)
        elif newYamlFile is not None:
            self._yamlFile = newYamlFile
        else:
            raise Exception(
                'Need at least one of yamlFile, newYamlFile '
                'keyword parameters')
        for k, v in self._cfg.items():
            setattr(self, k, v)

    def __iter__(self):
        for pair in self.__dict__.items():
            yield pair

    def __setattr__(self, name, value):
        self.__dict__[name] = value
        if name[0]!='_':
            try: self._cfg[name] = value
            except AttributeError: pass

    def __getitem__(self, name):
        return self._cfg[name]

    def get(self, name, defaultValue=None):
        return self._cfg.get(name, defaultValue)

    def save(self):
        outf = open(self._yamlFile,'wt')
        outf.write(yaml.dump(self._cfg))
        outf.close()


class ConnectionPoolConfig:

    def __init__(self, minConnections=3, maxConnections=5, reconnect=True,
                 keepAliveQuery=storagecontroller.KEEPALIVE_QUERY, 
                 keepAliveInterval=storagecontroller.KEEPALIVE_INTERVAL):
        self.minConnections = minConnections
        self.maxConnections = maxConnections
        self.reconnect = reconnect
        self.keepAliveQuery = keepAliveQuery
        self.keepAliveInterval = keepAliveInterval
        # validate config
        if self.minConnections < 1:
            raise errors.ConfigurationError(
                'minConnections must be >= 1')
        if self.maxConnections > 100:
            raise errors.ConfigurationError(
                'maxConnections must be <= 100')
        if self.keepAliveInterval < storagecontroller.MIN_KEEPALIVE_INTERVAL:
            raise errors.ConfigurationError(
                'maxConnections is specified in seconds. '
                'It must be >= %s' % storagecontroller.MIN_KEEPALIVE_INTERVAL)


class DatabaseConfig:

    def __init__(self, name=None, readServers=None, writeServers=None, 
                 user=None, password=None, port=3306, sharePool=False,
                 ConnectionPool=None):
        self._readPool = None
        self._writePool = None
        self.name = name
        self.port = port
        self.sharePool = sharePool
        self.readServers = readServers
        self.writeServers = writeServers
        self.user = user
        self.password = password
        if ConnectionPool is not None:
            self.ConnectionPool = ConnectionPoolConfig(**ConnectionPool)
        else:
            self.ConnectionPool = ConnectionPoolConfig()

        # validate config
        if self.name is None:
            raise errors.ConfigurationError(
                'DB.name is None or missing')
        if self.readServers is None or not self.readServers:
            raise errors.ConfigurationError(
                'DB.readServers is None or empty list or missing')
        if self.writeServers is None or not self.writeServers:
            raise errors.ConfigurationError(
                'DB.writeServers is None or empty list or missing')
        if self.user is None:
            raise errors.ConfigurationError(
                'DB.user is None or missing')
        if self.password is None:
            raise errors.ConfigurationError(
                'DB.password is None or missing')
        
    def getReadPool(self):
        if self._readPool is not None:
            return self._readPool
        if self.sharePool and self.readServers == self.writeServers:
            self._readPool = self.getWritePool()
        else:
            self._readPool = storagecontroller.getDbPool(self.readServers,
                db=self.name, user=self.user, passwd=self.password,
                port=self.port, reconnect=self.ConnectionPool.reconnect,
                min_connections=self.ConnectionPool.minConnections,
                max_connections=self.ConnectionPool.maxConnections)
        return self._readPool
                
    def getWritePool(self):
        if self._writePool is not None:
            return self._writePool
        self._writePool = storagecontroller.getDbPool(self.readServers,
            db=self.name, user=self.user, passwd=self.password,
            port=self.port, reconnect=self.ConnectionPool.reconnect,
            min_connections=self.ConnectionPool.minConnections,
            max_connections=self.ConnectionPool.maxConnections)
        return self._writePool

 
class FiveServerConfig:
    """
    Holds central configuration and state for
    the instance of FiveServer.
    """

    VERSION = '0.5.0'
    

    def __init__(self, serverConfig, dbConfig,
                 userData, profileData, matchData, profileLogic):
        self.serverConfig = serverConfig
        self.dbConfig = dbConfig
        self.userData = userData
        self.profileData = profileData
        self.matchData = matchData
        self.profileLogic = profileLogic

        self.cipherKey = ('27501fd04e6b82c831024dac5c6305221974deb9388a2190'
                          '1d576cbbe2f377ef23d75486010f37819afe6c321a0146d2'
                          '1544ec365bf7289a')
        
        self.serverIP_lan = None
        self.serverIP_wan = None
        self.startDatetime = datetime.now()
        reactor.callLater(0, self.setIP)

        # initialize interface to listen on
        self.interface = self.serverConfig.get('ListenOn','')

        # initialize MaxUsers, set to default if missing from config
        self.serverConfig.MaxUsers = self.serverConfig.get('MaxUsers', 1000)

        self.lobbies = []
        for i, item in enumerate(serverConfig.Lobbies):
            try: name = item['name']
            except TypeError: name = str(item)
            except KeyError:
                raise errors.ConfigurationError(
                    'Structured lobby definitions must '
                    'include "name" attribute')
            try: lobbyType = item['type']
            except TypeError: lobbyType = 'open'
            except KeyError: lobbyType = 'open'
            try: showMatches = item['showMatches']
            except TypeError: showMatches = True
            except KeyError: showMatches = True
            try:
                checkRosterHash = bool(int(item['checkRosterHash']))
            except:
                checkRosterHash = True
 
            aLobby = lobby.Lobby(name, 100)
            aLobby.showMatches = showMatches
            aLobby.checkRosterHash = checkRosterHash
            aLobby.typeStr = str(lobbyType)
            if lobbyType == 'noStats':
                aLobby.typeCode = 0x20
            elif lobbyType == 'open':
                aLobby.typeCode = 0x5f
            elif isinstance(lobbyType, list):
                # restricted lobby
                divMap = {'A':0,'3B':1,'3A':2,'2':3,'1':4} 
                typeCode = 0
                for divName in lobbyType:
                    try: typeCode += 2**divMap[divName]
                    except KeyError:
                        raise errors.ConfigurationError(
                            'Invalid lobby type definition. '
                            'Unrecognized division: "%s" ' % divName)
                aLobby.typeCode = typeCode
            else:
                aLobby.typeCode = 0x5f # default: open
            self.lobbies.append(aLobby)

        # auto-IP detector site
        try: 
            self.ipDetectUri = self.serverConfig.IpDetectUri
        except AttributeError:
            self.ipDetectUri = 'http://mapote.com/cgi-bin/ip.py'

        # rating/points calculator
        self.ratingMath = rating.RatingMath(0.44, 0.56)

        # initialize online-list
        self.onlineUsers = dict()

        # initialize latest-info dict
        self._latestUserInfo = dict()

        # read banned-list, if available
        bannedYaml = self.serverConfig.BannedList
        if not bannedYaml.startswith('/'):
            fsroot = os.environ.get('FSROOT','.')
            bannedYaml = fsroot + '/' + bannedYaml
        if os.path.exists(bannedYaml):
            self.bannedList = YamlConfig(bannedYaml)
        else:
            self.bannedList = YamlConfig(None, newYamlFile=bannedYaml)
            log.msg('NOTICE: banned-list file absent.')
        try: self.bannedList.Banned
        except AttributeError:
            self.bannedList.Banned = []

        # make banned-list structure for quick checks
        self.makeFastBannedList()

        # set up periodical rank-compute
        reactor.callLater(5, self.computeRanks)

        # set up periodical date updates
        now = datetime.now()
        today = datetime(now.year, now.month, now.day)
        td = today + timedelta(days=1) - now
        reactor.callLater(0, self.systemDayChange)

    def systemDayChange(self):
        message = 'Date: %s %s' % (
            time.ctime(), time.tzname[time.localtime().tm_isdst])
        for aLobby in self.lobbies:
            try: player = next(iter(aLobby.players.values()))
            except StopIteration: 
                aLobby.addToChatHistory(
                    lobby.ChatMessage(
                        lobby.SYSTEM_PROFILE, message))
            else:
                if player.lobbyConnection:
                    player.lobbyConnection.broadcastSystemChat(
                        aLobby, message)
            # purge old chat messages
            aLobby.purgeOldChat()
        # reschedule for next day change
        now = datetime.now()
        today = datetime(now.year, now.month, now.day)
        td = today + timedelta(days=1) - now
        reactor.callLater(td.seconds+1, self.systemDayChange)

    def computeRanks(self):
        def _reschedule(result):
            log.msg('NOTICE: Ranks successfully computed for all profiles.')
            try: days = int(
                self.serverConfig.ComputeRanksInterval['days'])
            except: days = None
            try: seconds = int(
                self.serverConfig.ComputeRanksInterval['seconds'])
            except: seconds = None
            if days is None and seconds is None or \
                    days==0 and seconds==0:
                # default to re-compute every day
                days, seconds = 1, 0
            elif days is None and seconds is not None:
                days = 0
            elif seconds is None and days is not None:
                seconds = 0
            td = timedelta(days=days, seconds=seconds)
            log.msg('Rank-compute interval is: %s' % td)
            log.msg('Scheduling next rank-compute for: %s' % (
                datetime.now() + td))
            seconds = td.days*24*60*60 + td.seconds
            reactor.callLater(seconds, self.computeRanks)
        d = self.profileData.computeRanks()
        d.addCallback(_reschedule)
        return d

    def makeFastBannedList(self):
        self.fastBannedList = []
        for spec in self.bannedList.Banned:
            parts = spec.split('/')
            if len(parts)==2:
                try: net, bits = parts[0], int(parts[1])
                except ValueError: net, bits = parts[0],0
                if not bits>0:
                    log.msg(
                        'WARN: illegal spec in bannedList: '
                        '%s (skipping it)' % spec)
                    continue
            elif len(parts)==1:
                net = parts[0]
                bits = 0
            else:
                log.msg(
                    'WARN: illegal spec in bannedList: '
                    '%s (skipping it)' % spec)
                continue
            quads = [0,0,0,0]
            goodSpec = True
            for i,quad in enumerate(net.split('.')):
                if quad=='':
                    continue
                try: quads[i] = int(quad)
                except:
                    log.msg(
                        'WARN: illegal spec in bannedList: '
                        '%s (skipping it)' % spec)
                    goodSpec = False
                    break
            if not goodSpec:
                continue
            netBuf = b''.join(struct.pack('!B', quad) for quad in quads)
            net = struct.unpack('!I',netBuf)[0]
            if bits == 0:
                # determine mask based on net
                bits = sum([8 for quad in quads if quad!=0])
            mask = (2**int(bits)-1)<<(32-int(bits))
            self.fastBannedList.append((net,mask))
        # output for debugging
        for net, mask in self.fastBannedList:
            log.msg('%s, %s' % (hex(net),hex(mask)))

    def setIP(self, retryDelay=1, resetTime=True):
        def _setIP(result):
            self.serverIP_wan = result.decode('utf-8').strip()
            if resetTime:
                self.startDatetime = datetime.now()
            log.msg('Server IP-address: %s' % self.serverIP_wan)
            log.msg('Fiveserver %s ready' % FiveServerConfig.VERSION)
        def _error(error, retryDelay):
            retryDelay = min(retryDelay*2, 120)
            log.msg(
                'Failed to determine server IP-address (ERROR: %s). '
                'Trying again in %d seconds' % (str(error), retryDelay))
            reactor.callLater(retryDelay, self.setIP, retryDelay, resetTime)
        try: self.serverConfig.ServerIP
        except AttributeError:
            self.serverConfig.ServerIP = None
        if self.serverConfig.ServerIP in [None,'auto']:
            # try to determine the WAN address
            d = client.getPage(self.ipDetectUri.encode('utf-8'), timeout=10)
        else:
            # explicitly set in configuration file
            d = defer.succeed(self.serverConfig.ServerIP)
        d.addCallback(_setIP)
        d.addErrback(_error, retryDelay)
        return d

    def isStoreSettingsEnabled(self):
        try:
            value = self.serverConfig.StoreSettings
        except AttributeError:
            value = True
        return value

    @defer.inlineCallbacks
    def storePlayerData(self, usr):
        for profile in usr.profiles:
            if profile.name!='':
                yield self.profileData.store(profile)
        yield self.userData.store(usr)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def storeProfile(self, profile):
        yield self.profileData.store(profile)
        profiles = yield self.profileData.findByName(profile.name)
        defer.returnValue(profiles[0])
     
    @defer.inlineCallbacks
    def deleteProfile(self, profile):
        yield self.profileData.delete(profile)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def getUser(self, hash):
        users = yield self.userData.findByHash(hash)
        if not users:
            raise errors.UnknownUserError('Unknown user: %s' % hash)
        profiles = yield self.profileData.getByUserId(users[0].id)
        users[0].profiles = [None, None, None]
        for profile in profiles:
            users[0].profiles[profile.index] = profile
        for i in range(3):
            if users[0].profiles[i] is None:
                users[0].profiles[i] = user.Profile(i)
                users[0].profiles[i].userId = users[0].id
        defer.returnValue(users[0])

    def getLobbies(self):
        return self.lobbies

    def getLobby(self, name):
        for x in self.lobbies:
            if x.name == name:
                return x
        raise errors.PacketServerError('Unknown lobby: %s' % name)

    def userOnline(self, usr):
        self.onlineUsers[usr.hash] = usr

    def userOffline(self, usr):
        if not usr:
            return
        try: del self.onlineUsers[usr.hash]
        except KeyError:
            pass

    def isUserOnline(self, usr):
        return usr.hash in self.onlineUsers

    def getUserInfo(self, usr):
        return self._latestUserInfo[usr.username]

    def setUserInfo(self, usr, userInfo):
        self._latestUserInfo[usr.username] = userInfo

    @defer.inlineCallbacks
    def createUser(self, username, serial, hash, nonce):
        results = yield self.userData.findByHash(hash)
        if nonce in [None,'']:
            if results:
                raise Exception('duplicate user hash!')
            usr = user.User(hash)
            usr.id = None
            usr.username = username
            usr.serial = serial
            usr.hash = hash
            usr.nonce = nonce
            usr.profiles = []
            yield self.userData.store(usr)
            for i in range(3):
                profile = user.Profile(i)
                profile.id = -1
                usr.profiles.append(profile)
            defer.returnValue(usr)
        else:
            # modification
            results = yield self.userData.findByNonce(nonce)
            if not results:
                raise Exception('User not found for nonce: %s' % nonce)
            usr = results[0]
            usr.hash = hash
            usr.serial = serial
            usr.username = username
            usr.nonce = None
            yield self.userData.store(usr)
            defer.returnValue(usr)
            
    @defer.inlineCallbacks
    def lockUser(self, username):
        results = yield self.userData.findByUsername(username)
        if not results:
            raise Exception('Unknown username: %s' % username)
        usr = results[0]
        usr.nonce = ''.join([str(random.randint(1000,10000)) for x in range(4)])
        yield self.userData.store(usr)
        defer.returnValue(usr.nonce)

    @defer.inlineCallbacks
    def deleteUser(self, username):
        results = yield self.userData.findByUsername(username)
        if not results:
            raise Exception('Unknown username: %s' % username)
        usr = results[0]
        yield self.userData.delete(usr)
        log.msg('User "%s" has been DELETED.' % username)
        defer.returnValue(usr)

    @defer.inlineCallbacks
    def profileNameExists(self, profileName):
        results = yield self.profileData.findByName(profileName)
        if not results:
            defer.returnValue(False)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def getPlayerProfile(self, profileId):
        results = yield self.profileData.get(profileId)
        if not results:
            defer.returnValue(None)
        defer.returnValue(results[0])

    def isBanned(self, ipAddress):
        for net, mask in self.fastBannedList:
            ip = struct.unpack('!I',socket.inet_aton(ipAddress))[0]
            if (net & mask) == (ip & mask):
                return True
        return False

    def atCapacity(self):
        return self.serverConfig.MaxUsers <= self.getNumUsersOnline()

    def getNumUsersOnline(self):
        return len(self.onlineUsers)

