"""Dedicated experimental service for the Korean PS2 disc SLKA-25153."""

import os

from twisted.application.internet import TCPServer
from twisted.application.service import Application
from twisted.web.server import Site

from fiveserver import data6, log, logic, storagecontroller
from fiveserver.config import FiveServerConfig, YamlConfig, DatabaseConfig
from fiveserver.protocol import PacketServiceFactory, we10le
from fiveserver.register import RegistrationResource


application = Application('WE10LE Korea application')
fsroot = os.environ.get('FSROOT', '.')
scfg = YamlConfig(os.environ.get(
    'WE10LE_CONFIG', fsroot + '/etc/conf/we10le.yaml'))
if scfg.GamePorts != {'we10le': we10le.GATE_PORT}:
    raise ValueError('WE10LE requires its own TCP 10881 listener')
if scfg.Roster.get('enforceHash') or scfg.Roster.get('compareHash'):
    raise ValueError('WE10LE PS2 does not send a PC roster checksum')
log.setDebug(scfg.Debug)
dbConfig = DatabaseConfig(**scfg.DB)
storageController = storagecontroller.StorageController(
    dbConfig.getReadPool(), dbConfig.getWritePool())
keepAliveManager = storagecontroller.KeepAliveManager(
    storageController, dbConfig.ConnectionPool.keepAliveInterval,
    dbConfig.ConnectionPool.keepAliveQuery)
keepAliveManager.start()

userData = data6.UserData(storageController)
profileData = data6.ProfileData(storageController)
matchData = data6.MatchData(storageController)
profileLogic = logic.ProfileLogic(matchData, profileData)
config = FiveServerConfig(
    scfg, dbConfig, userData, profileData, matchData, profileLogic)

for protocol, port in [
        (we10le.NewsProtocol, we10le.GATE_PORT),
        (we10le.LoginService, scfg.NetworkServer['loginService']['we10le']),
        (we10le.NetworkMenuService, scfg.NetworkServer['networkMenuService']),
        (we10le.MainService, scfg.NetworkServer['mainService'])]:
    factory = PacketServiceFactory(config)
    factory.protocol = protocol
    listener = TCPServer(port, factory, interface=config.interface)
    listener.setServiceParent(application)

# Reuse the existing account store and MD5 asset, with the PS2 hash form.
registrationServer = Site(RegistrationResource(
    config, fsroot + '/web6', formFile='form-we10le.html'))
registrationService = TCPServer(
    scfg.WebInterface['port'], registrationServer, interface=config.interface)
registrationService.setServiceParent(application)
