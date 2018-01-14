"""
Data-layer
"""

from twisted.internet import defer
from datetime import timedelta
from model import user


class UserData:

    def __init__(self, dbController):
        self.dbController = dbController

    @defer.inlineCallbacks
    def get(self, id):
        sql = ('SELECT id,username,serial,hash,reset_nonce,updated_on '
               'FROM users WHERE deleted = 0 AND id = %s')
        rows = yield self.dbController.dbRead(0, sql, id)
        results = []
        for row in rows:
            usr = user.User(row[3])
            usr.id = row[0]
            usr.username = row[1]
            usr.serial = row[2]
            usr.hash = row[3]
            usr.nonce = row[4]
            usr.updatedOn = row[5]
            results.append(usr)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def browse(self, offset=0, limit=30):
        sql = ('SELECT count(id) '
               'FROM users WHERE deleted = 0')
        rows = yield self.dbController.dbRead(0, sql)
        total = int(rows[0][0])
        sql = ('SELECT id,username,serial,hash,reset_nonce,updated_on '
               'FROM users WHERE deleted = 0 '
               'ORDER BY username LIMIT %s OFFSET %s')
        rows = yield self.dbController.dbRead(0, sql, limit, offset)
        results = []
        for row in rows:
            usr = user.User(row[3])
            usr.id = row[0]
            usr.username = row[1]
            usr.serial = row[2]
            usr.hash = row[3]
            usr.nonce = row[4]
            usr.updatedOn = row[5]
            results.append(usr)
        defer.returnValue((total, results))

    @defer.inlineCallbacks
    def store(self, usr):
        sql = ('INSERT INTO users (id,username,serial,hash,reset_nonce) '
               'VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE '
               'deleted=0, username=%s, serial=%s, hash=%s, reset_nonce=%s')
        params = (usr.id, usr.username, usr.serial, usr.hash,
                  usr.nonce, usr.username, usr.serial, usr.hash,
                  usr.nonce)
        yield self.dbController.dbWrite(0, sql, *params)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def delete(self, usr):
        sql = 'UPDATE users SET deleted = 1 WHERE id = %s'
        params = (usr.id,)
        yield self.dbController.dbWrite(0, sql, *params)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def findByUsername(self, username):
        sql = ('SELECT id,username,serial,hash,reset_nonce,updated_on '
               'FROM users WHERE deleted = 0 AND username = %s')
        rows = yield self.dbController.dbRead(0, sql, username)
        results = []
        for row in rows:
            usr = user.User(row[3])
            usr.id = row[0]
            usr.username = row[1]
            usr.serial = row[2]
            usr.hash = row[3]
            usr.nonce = row[4]
            usr.updatedOn = row[5]
            results.append(usr)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def findByHash(self, hash):
        sql = ('SELECT id,username,serial,hash,reset_nonce,updated_on '
               'FROM users WHERE deleted = 0 AND hash = %s')
        rows = yield self.dbController.dbRead(0, sql, hash)
        results = []
        for row in rows:
            usr = user.User(row[3])
            usr.id = row[0]
            usr.username = row[1]
            usr.serial = row[2]
            usr.hash = row[3]
            usr.nonce = row[4]
            usr.updatedOn = row[5]
            results.append(usr)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def findByNonce(self, nonce):
        sql = ('SELECT id,username,serial,hash,reset_nonce,updated_on '
               'FROM users WHERE deleted = 0 AND reset_nonce = %s')
        rows = yield self.dbController.dbRead(0, sql, nonce)
        results = []
        for row in rows:
            usr = user.User(row[3])
            usr.id = row[0]
            usr.username = row[1]
            usr.serial = row[2]
            usr.hash = row[3]
            usr.nonce = row[4]
            usr.updatedOn = row[5]
            results.append(usr)
        defer.returnValue(results)


class ProfileData:

    def __init__(self, dbController):
        self.dbController = dbController

    @defer.inlineCallbacks
    def get(self, id):
        sql = ('SELECT id,user_id,ordinal,name,fav_player,fav_team,rank,'
               'points,disconnects,updated_on,seconds_played '
               'FROM profiles WHERE deleted = 0 AND id = %s')
        rows = yield self.dbController.dbRead(0, sql, id)
        results = []
        for row in rows:
            p = user.Profile(row[2])
            p.id = row[0]
            p.userId = row[1]
            p.name = row[3]
            p.favPlayer = row[4]
            p.favTeam = row[5]
            p.rank = row[6]
            p.points = row[7]
            p.disconnects = row[8]
            p.updatedOn = row[9]
            p.playTime = timedelta(seconds=row[10])
            results.append(p)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def getByUserId(self, userId):
        sql = ('SELECT id,user_id,ordinal,name,fav_player,fav_team,rank,'
               'points,disconnects,updated_on,seconds_played '
               'FROM profiles WHERE deleted = 0 AND user_id = %s '
               'ORDER BY updated_on ASC')
        rows = yield self.dbController.dbRead(0, sql, userId)
        results = []
        for row in rows:
            p = user.Profile(row[2])
            p.id = row[0]
            p.userId = row[1]
            p.name = row[3]
            p.favPlayer = row[4]
            p.favTeam = row[5]
            p.rank = row[6]
            p.points = row[7]
            p.disconnects = row[8]
            p.updatedOn = row[9]
            p.playTime = timedelta(seconds=row[10])
            results.append(p)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def getSettings(self, profileId):
        sql = ('SELECT settings1, settings2 '
               'FROM settings WHERE profile_id=%s')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        if len(rows)>0:
            settings = user.ProfileSettings(rows[0][0], rows[0][1])
        else:
            settings = user.ProfileSettings(None, None)
        defer.returnValue(settings)

    @defer.inlineCallbacks
    def storeSettings(self, profileId, settings):
        sql = ('INSERT INTO settings (profile_id, settings1, settings2) '
               'VALUES (%s, %s, %s) '
               'ON DUPLICATE KEY UPDATE settings1=%s, settings2=%s')
        yield self.dbController.dbWrite(
            0, sql, profileId, settings.settings1, settings.settings2,
            settings.settings1, settings.settings2)
        defer.returnValue(settings)

    @defer.inlineCallbacks
    def browse(self, offset=0, limit=30):
        sql = ('SELECT count(id) '
               'FROM profiles WHERE deleted = 0')
        rows = yield self.dbController.dbRead(0, sql)
        total = int(rows[0][0])
        sql = ('SELECT id,user_id,ordinal,name,fav_player,fav_team,rank,'
               'points,disconnects,updated_on,seconds_played '
               'FROM profiles WHERE deleted = 0 '
               'ORDER BY name LIMIT %s OFFSET %s')
        rows = yield self.dbController.dbRead(0, sql, limit, offset)
        results = []
        for row in rows:
            p = user.Profile(row[2])
            p.id = row[0]
            p.userId = row[1]
            p.name = row[3]
            p.favPlayer = row[4]
            p.favTeam = row[5]
            p.rank = row[6]
            p.points = row[7]
            p.disconnects = row[8]
            p.updatedOn = row[9]
            p.playTime = timedelta(seconds=row[10])
            results.append(p)
        defer.returnValue((total, results))

    @defer.inlineCallbacks
    def store(self, p):
        sql = ('INSERT INTO profiles (id,user_id,ordinal,name,fav_player,'
               'fav_team,rank,points,disconnects,seconds_played) '
               'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE '
               'deleted=0, user_id=%s, ordinal=%s, name=%s, '
               'fav_player=%s, fav_team=%s, rank=%s, '
               'points=%s, disconnects=%s, seconds_played=%s')
        params = (p.id, p.userId, p.index, p.name, p.favPlayer, p.favTeam,
                  p.rank, p.points, p.disconnects, p.playTime.seconds,
                  p.userId, p.index, p.name, p.favPlayer, p.favTeam, p.rank,
                  p.points, p.disconnects, p.playTime.seconds)
        yield self.dbController.dbWrite(0, sql, *params)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def delete(self, p):
        sql = 'UPDATE profiles SET deleted = 1 WHERE id = %s'
        params = (p.id,)
        yield self.dbController.dbWrite(0, sql, *params)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def findByName(self, profileName):
        sql = ('SELECT id,user_id,ordinal,name,fav_player,fav_team,'
               'rank,points,disconnects,updated_on,seconds_played '
               'FROM profiles WHERE deleted = 0 AND name = %s')
        rows = yield self.dbController.dbRead(0, sql, profileName)
        results = []
        for row in rows:
            p = user.Profile(row[2])
            p.id = row[0]
            p.userId = row[1]
            p.name = row[3]
            p.favPlayer = row[4]
            p.favTeam = row[5]
            p.rank = row[6]
            p.points = row[7]
            p.disconnects = row[8]
            p.updatedOn = row[9]
            p.playTime = timedelta(seconds=row[10])
            results.append(p)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def computeRanks(self):
        result = yield self.dbController.dbWriteInteraction(
            0, self._computeRanksTxn)
        defer.returnValue(result)

    def _computeRanksTxn(self, transaction):
        rank, count, rank_range = 1, 1, 100
        last_points = None
        limit, offset = 50, 0
        while True:
            sql = ('SELECT id, points FROM profiles '
                   'ORDER BY points DESC, seconds_played DESC '
                   'LIMIT %s OFFSET %s')
            params = [limit, offset]
            transaction.execute(sql, params)
            rows = transaction.fetchall()
            for (id, points) in rows:
                if last_points is not None:
                    # check if rank needs to be lowered
                    if last_points > points:
                        rank = count
                sql = ('UPDATE profiles SET rank=%s WHERE id=%s')
                params = [rank, id]
                transaction.execute(sql, params)
                last_points = points
                count += 1
            if len(rows) < limit:
                break
            offset += limit


class MatchData:

    def __init__(self, dbController):
        self.dbController = dbController

    @defer.inlineCallbacks
    def getGames(self, profileId):
        sql = ('SELECT count(id) FROM matches '
               'WHERE profile_id_home=%s OR profile_id_away=%s')
        rows = yield self.dbController.dbRead(0, sql, profileId, profileId)
        defer.returnValue(rows[0][0])

    @defer.inlineCallbacks
    def getWins(self, profileId):
        sql = ('SELECT count(id) FROM matches '
               'WHERE profile_id_home=%s AND score_home>score_away '
               'OR profile_id_away=%s AND score_home<score_away')
        rows = yield self.dbController.dbRead(0, sql, profileId, profileId)
        defer.returnValue(rows[0][0])

    @defer.inlineCallbacks
    def getLosses(self, profileId):
        sql = ('SELECT count(id) FROM matches '
               'WHERE profile_id_home=%s AND score_home<score_away '
               'OR profile_id_away=%s AND score_home>score_away')
        rows = yield self.dbController.dbRead(0, sql, profileId, profileId)
        defer.returnValue(rows[0][0])

    @defer.inlineCallbacks
    def getDraws(self, profileId):
        sql = ('SELECT count(id) FROM matches '
               'WHERE profile_id_home=%s AND score_home=score_away '
               'OR profile_id_away=%s AND score_home=score_away')
        rows = yield self.dbController.dbRead(0, sql, profileId, profileId)
        defer.returnValue(rows[0][0])

    @defer.inlineCallbacks
    def getGoalsHome(self, profileId):
        sql = ('SELECT sum(score_home),sum(score_away) FROM matches '
               'WHERE profile_id_home=%s')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        scored = rows[0][0] or 0
        allowed = rows[0][1] or 0
        defer.returnValue((int(scored), int(allowed)))

    @defer.inlineCallbacks
    def getGoalsAway(self, profileId):
        sql = ('SELECT sum(score_away),sum(score_home) FROM matches '
               'WHERE profile_id_away=%s')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        scored = rows[0][0] or 0
        allowed = rows[0][1] or 0
        defer.returnValue((int(scored), int(allowed)))

    @defer.inlineCallbacks
    def getStreaks(self, profileId):
        sql = ('SELECT wins, best FROM streaks '
               'WHERE profile_id=%s')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        wins, best = 0, 0
        if len(rows)>0:
            wins, best = rows[0][0], rows[0][1]
        defer.returnValue((wins, best))

    @defer.inlineCallbacks
    def store(self, match):
        matchId = yield self.dbController.dbWriteInteraction(
            0, self._storeTxn, match)
        defer.returnValue(matchId)

    def _storeTxn(self, transaction, match):
        def _writeStreak(profile_id, win):
            wins, best = 0, 0
            sql = ('SELECT wins, best FROM streaks '
                   'WHERE profile_id=%s')
            transaction.execute(sql, (profile_id,))
            data = transaction.fetchall()
            if len(data)>0:
                wins, best = data[0][0], data[0][1]
            if win:
                wins += 1
                best = max(wins, best)
            else:
                wins = 0
            sql = ('INSERT INTO streaks (profile_id, wins, best) '
                   'VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE '
                   'wins=%s, best=%s')
            transaction.execute(sql, (
                profile_id, wins, best, wins, best))

        # record match result
        sql = ('INSERT INTO matches (profile_id_home, profile_id_away, '
               'score_home, score_away, team_id_home, team_id_away) '
               'VALUES (%s,%s,%s,%s,%s,%s)')
        transaction.execute(sql, ( 
            match.home_profile.id, match.away_profile.id,
            match.score_home, match.score_away, 
            match.home_team_id, match.away_team_id))
        transaction.execute('SELECT LAST_INSERT_ID()')
        matchId = transaction.fetchall()[0][0]
        # update winning streaks
        if match.score_home > match.score_away:
            # home win
            _writeStreak(match.home_profile.id, True)
            _writeStreak(match.away_profile.id, False)
        elif match.score_home < match.score_away:
            # away win
            _writeStreak(match.home_profile.id, False)
            _writeStreak(match.away_profile.id, True)
        else:
            # draw
            _writeStreak(match.home_profile.id, False)
            _writeStreak(match.away_profile.id, False)
        return matchId

