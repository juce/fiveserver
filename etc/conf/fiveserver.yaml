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
    pes5: 16001
    we9le: 19501
    we9: 18001

NetworkServer:
    mainService: 20100
    networkMenuService: 20101
    loginService:
        pes5: 20102
        we9: 20103
        we9le: 20104

WebInterface:
    port: 8180

Debug:
    false

DB:
    name: fiveserver
    user: fiveserver
    password: we9le
    readServers: [127.0.0.1]
    writeServers: [127.0.0.1]
    sharePool: True
    ConnectionPool:
        minConnections: 3
        maxConnections: 5
        keepAliveInterval: 60

BannedList: ./etc/data/banned.yaml

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

Disconnects:
    CountAsLoss:
        Enabled: false
        Score:
            player: 0
            opponent: 3

ServerName: "Fiveserver"

Greeting:
    "text": "\
Welcome to Fiveserver -\n\
independent community server\n\
supporting PES5/WE9/WE9LE games.\n\
Have a good time, play some nice\n\
football and try to score goals.\n\
\n\
Credits:\r\n\
Protocol analysis: reddwarf, juce\n\
Server programming: juce, reddwarf"

