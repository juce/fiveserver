"""
Data-layer for PES6
"""

from twisted.internet import defer
from datetime import timedelta
from fiveserver.model import user
from fiveserver import data


class UserData(data.UserData):
    """
    Same as PES5 UserData
    """

class ProfileData(data.ProfileData):
    """
    Not quite the same as PES ProfileData, because
    of new fields: rating, comment
    """

    def __init__(self, dbController):
        self.dbController = dbController

    @defer.inlineCallbacks
    def get(self, id):
        sql = ('SELECT id,user_id,ordinal,name,`rank`,'
               'rating,points,disconnects,updated_on,seconds_played,comment '
               'FROM profiles WHERE deleted = 0 AND id = %s')
        rows = yield self.dbController.dbRead(0, sql, id)
        results = []
        for row in rows:
            (id, userId, ordinal, name, rank, rating, 
             points, disconnects, updatedOn, secondsPlayed, comment) = row
            playTime = timedelta(seconds=secondsPlayed)
            p = user.Profile(ordinal)
            p.id = id
            p.userId = userId
            p.name = name
            p.rank = rank
            p.rating = rating
            p.points = points
            p.disconnects = disconnects
            p.updatedOn = updatedOn
            p.playTime = playTime
            p.comment = comment
            results.append(p)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def getByUserId(self, userId):
        sql = ('SELECT id,user_id,ordinal,name,`rank`,'
               'rating,points,disconnects,updated_on,seconds_played,comment '
               'FROM profiles WHERE deleted = 0 AND user_id = %s '
               'ORDER BY updated_on ASC')
        rows = yield self.dbController.dbRead(0, sql, userId)
        results = []
        for row in rows:
            (id, userId, ordinal, name, rank, rating, 
             points, disconnects, updatedOn, secondsPlayed, comment) = row
            playTime = timedelta(seconds=secondsPlayed)
            p = user.Profile(ordinal)
            p.id = id
            p.userId = userId
            p.name = name
            p.rank = rank
            p.rating = rating
            p.points = points
            p.disconnects = disconnects
            p.updatedOn = updatedOn
            p.playTime = playTime
            p.comment = comment
            results.append(p)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def browse(self, offset=0, limit=30):
        sql = ('SELECT count(id) '
               'FROM profiles WHERE deleted = 0')
        rows = yield self.dbController.dbRead(0, sql)
        total = int(rows[0][0])
        sql = ('SELECT id,user_id,ordinal,name,`rank`,'
               'rating,points,disconnects,updated_on,seconds_played,comment '
               'FROM profiles WHERE deleted = 0 '
               'ORDER BY name LIMIT %s OFFSET %s')
        rows = yield self.dbController.dbRead(0, sql, limit, offset)
        results = []
        for row in rows:
            (id, userId, ordinal, name, rank, rating, 
             points, disconnects, updatedOn, secondsPlayed, comment) = row
            playTime = timedelta(seconds=secondsPlayed)
            p = user.Profile(ordinal)
            p.id = id
            p.userId = userId
            p.name = name
            p.rank = rank
            p.rating = rating
            p.points = points
            p.disconnects = disconnects
            p.updatedOn = updatedOn
            p.playTime = playTime
            p.comment = comment
            results.append(p)
        defer.returnValue((total, results))

    @defer.inlineCallbacks
    def store(self, p):
        sql = ('INSERT INTO profiles (id,user_id,ordinal,name,'
               '`rank`,rating,points,disconnects,seconds_played,comment) '
               'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
               'ON DUPLICATE KEY UPDATE '
               'deleted=0, user_id=%s, ordinal=%s, name=%s, '
               '`rank`=%s, rating=%s, points=%s, '
               'disconnects=%s, seconds_played=%s, comment=%s')
        params = (p.id, p.userId, p.index, p.name, 
                  p.rank, p.rating, p.points, p.disconnects, int(p.playTime.total_seconds()),
                  p.comment, p.userId, p.index, p.name, p.rank,
                  p.rating, p.points, p.disconnects, int(p.playTime.total_seconds()),
                  p.comment)
        yield self.dbController.dbWrite(0, sql, *params)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def findByName(self, profileName):
        sql = ('SELECT id,user_id,ordinal,name, '
               '`rank`,rating,points,disconnects,updated_on,'
               'seconds_played,comment '
               'FROM profiles WHERE deleted = 0 AND name = %s')
        rows = yield self.dbController.dbRead(0, sql, profileName)
        results = []
        for row in rows:
            (id, userId, ordinal, name, rank, rating, 
             points, disconnects, updatedOn, secondsPlayed, comment) = row
            playTime = timedelta(seconds=secondsPlayed)
            p = user.Profile(ordinal)
            p.id = id
            p.userId = userId
            p.name = name
            p.rank = rank
            p.rating = rating
            p.points = points
            p.disconnects = disconnects
            p.updatedOn = updatedOn
            p.playTime = playTime
            p.comment = comment
            results.append(p)
        defer.returnValue(results)


class MatchData:

    def __init__(self, dbController):
        self.dbController = dbController

    @defer.inlineCallbacks
    def getGames(self, profileId):
        sql = ('SELECT count(id) FROM matches_played '
               'WHERE profile_id=%s')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        defer.returnValue(rows[0][0])

    @defer.inlineCallbacks
    def getWins(self, profileId):
        sql = ('SELECT count(matches.id) FROM matches, matches_played '
               'WHERE matches.id=matches_played.match_id AND profile_id=%s '
               'AND ((home=1 and score_home>score_away) OR '
               '(home=0 and score_home<score_away))')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        defer.returnValue(rows[0][0])

    @defer.inlineCallbacks
    def getLosses(self, profileId):
        sql = ('SELECT count(matches.id) FROM matches, matches_played '
               'WHERE matches.id=matches_played.match_id AND profile_id=%s '
               'AND ((home=1 and score_home<score_away) OR '
               '(home=0 and score_home>score_away))')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        defer.returnValue(rows[0][0])

    @defer.inlineCallbacks
    def getDraws(self, profileId):
        sql = ('SELECT count(matches.id) FROM matches, matches_played '
               'WHERE matches.id=matches_played.match_id AND profile_id=%s '
               'AND score_home=score_away')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        defer.returnValue(rows[0][0])

    @defer.inlineCallbacks
    def getGoalsHome(self, profileId):
        sql = ('SELECT sum(score_home),sum(score_away) '
               'FROM matches, matches_played '
               'WHERE matches.id=matches_played.match_id '
               'AND profile_id=%s AND home=1')
        rows = yield self.dbController.dbRead(0, sql, profileId)
        scored = rows[0][0] or 0
        allowed = rows[0][1] or 0
        defer.returnValue((int(scored), int(allowed)))

    @defer.inlineCallbacks
    def getGoalsAway(self, profileId):
        sql = ('SELECT sum(score_away),sum(score_home) '
               'FROM matches, matches_played '
               'WHERE matches.id=matches_played.match_id '
               'AND profile_id=%s AND home=0')
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
    def getLastTeamsUsed(self, profileId, numMatches):
        sql = ('SELECT match_id, team_id_home, team_id_away, home '
               'FROM matches_played, matches '
               'WHERE profile_id=%s AND matches.id=match_id '
               'ORDER BY match_id DESC LIMIT %s')
        args = (profileId, numMatches,)
        rows = yield self.dbController.dbRead(0, sql, *args)
        teams = []
        for row in rows:
            match_id, team_id_home, team_id_away, home = row
            if home:
                teams.append(team_id_home)
            else:
                teams.append(team_id_away)
        defer.returnValue(teams)

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
        sql = ('INSERT INTO matches '
               '(score_home, score_away, team_id_home, team_id_away) '
               'VALUES (%s,%s,%s,%s)')
        transaction.execute(sql, ( 
            match.score_home, match.score_away, 
            match.teamSelection.home_team_id, match.teamSelection.away_team_id))
        transaction.execute('SELECT LAST_INSERT_ID()')
        matchId = transaction.fetchall()[0][0]
        # record players of the match
        home_players = [match.teamSelection.home_captain]
        home_players.extend(match.teamSelection.home_more_players)
        away_players = [match.teamSelection.away_captain]
        away_players.extend(match.teamSelection.away_more_players)
        for profile in home_players:
            sql = ('INSERT INTO matches_played (match_id, profile_id, home) '
                   'VALUES (%s, %s, 1)')
            transaction.execute(sql, (matchId, profile.id))
        for profile in away_players:
            sql = ('INSERT INTO matches_played (match_id, profile_id, home) '
                   'VALUES (%s, %s, 0)')
            transaction.execute(sql, (matchId, profile.id))
        # update winning streaks
        if match.score_home > match.score_away:
            # home win
            for profile in home_players:
                _writeStreak(profile.id, True)
            for profile in away_players:
                _writeStreak(profile.id, False)
        elif match.score_home < match.score_away:
            # away win
            for profile in home_players:
                _writeStreak(profile.id, False)
            for profile in away_players:
                _writeStreak(profile.id, True)
        else:
            # draw
            for profile in home_players:
                _writeStreak(profile.id, False)
            for profile in away_players:
                _writeStreak(profile.id, False)
        return matchId

