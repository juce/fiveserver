Name: Fiveserver Configuration File
Version: 1.8

Comment: |
    NOTE that GamePorts should not be changed, because the corresponding
    games have those values hardcoded into them.

ServerIP: auto
ListenOn: ""
IpDetectUri: "http://mapote.com/cgi-bin/ip.py"

Lobbies:
    - 'Russia'
    - 'England'
    - 'Italy'
    - 'Spain'
    - 'Germany'
    - 'EuroLeague'
    - name: 'Playground'
      type: ['A']
    - name: 'Training'
      type: noStats
      showMatches: False
    - 'Guest Lobby'

GamePorts:
    pes6: 10881
    #we2007: 10881

NetworkServer:
    mainService: 20200
    networkMenuService: 20201
    loginService:
        pes6: 20202
        we2007: 20203

WebInterface:
    port: 8190

Debug:
    false

DB:
    name: sixserver
    user: sixserver
    password: proevo
    readServers: [127.0.0.1]
    writeServers: [127.0.0.1]
    sharePool: True
    ConnectionPool:
        minConnections: 3
        maxConnections: 5
        keepAliveInterval: 60

BannedList: ./etc/data/banned6.yaml

Chat:
    bannedWords: []
    warningMessage: "message was removed because it contains banned words"

Roster:
    enforceHash: false
    compareHash: true

ComputeRanksInterval:
    days: 1
    seconds: 0

StoreSettings: true

ShowStats: true

#Disconnects:
#    CountAsLoss:
#        Enabled: false
#        Score:
#            player: 0
#            opponent: 3

ServerName: "Fiveserver"

Greeting:
    "text": "\
Welcome to Fiveserver -\n\
independent community server\n\
supporting PES6/WE2007 games.\n\
Have a good time, play some nice\n\
football and try to score goals.\n\
\n\
Credits:\r\n\
Protocol analysis: reddwarf, juce\n\
Server programming: juce, reddwarf"

