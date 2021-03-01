from twisted.internet import reactor
from twisted.enterprise import adbapi

from time import time
from random import uniform
from fiveserver import log


KEEPALIVE_QUERY = "SELECT (1)"
KEEPALIVE_INTERVAL = 60
MIN_KEEPALIVE_INTERVAL = 15
REFRESH_WEIGHTS = 60 # once per minute


def getDbPool(db_servers, user, passwd, db, port=3306, reconnect=True,
              min_connections=3, max_connections=5):
    """
    Return a sequence of MySQL ConnectionPools.
    """
    return [
        adbapi.ConnectionPool("MySQLdb", db=db,
                              host=db_server, user=user, passwd=passwd,
                              charset='utf8', use_unicode=True, port=port,
                              cp_reconnect=reconnect,
                              cp_min=min_connections,
                              cp_max=max_connections)
        for db_server in db_servers]


class WeightedPoolItem:
    def __init__(self, value):
        self.value = value
        self._sum  = 1
        self._count = 1
        self._lastRefresh = time()
        
    def getWeight(self):
        return self._sum/self._count

    def addStat(self, stat):
        if REFRESH_WEIGHTS < self._lastRefresh - time():
            self._sum = stat
            self._count = 1
            return

        self._sum+= stat
        self._count+= 1


class WeightedPool:
    def __init__(self, items):
        self._items = []
        for item in items:
            self._items.append(WeightedPoolItem(item))

    def weightedChoice(self, choices):
        sumWeight = 0
        for choice, (cumulative, count) in choices.items():
            sumWeight+= cumulative/count

    def getPoolItem(self):
        if 0==len(self._items):
            log.msg('WARN: item requested from an empty pool')
            raise Exception()
        sumWeight = 0
        for item in self._items:
            sumWeight+= item.getWeight()
        n = uniform(0, sumWeight)
        for item in self._items:
            if n < sumWeight:
                break
            n = n - item.getWeight()
        return item
        

class KeepAliveManager:
    def __init__(self, storageController, interval=KEEPALIVE_INTERVAL,
                 query=KEEPALIVE_QUERY):
        self.storageController = storageController
        self.interval = interval
        self.query = query
        
    def start(self):
        reactor.callLater(self.interval, self._keepAlive)
        
    def _keepAlive(self):
        log.debug(
            'DEBUG: KeepAliveManager:: keep-alive query: %s' % self.query)
        for item in self.storageController.readPool._items:
            item.value.runQuery(self.query)
        if self.storageController.writePool is not \
                self.storageController.readPool:
            for item in self.storageController.writePool._items:
                item.value.runQuery(self.query)
        self.start()
            

class StorageController:
    name = 'StorageController'
    
    def __init__(self, readPool=None, writePool=None):
        if readPool is None: readPool = []
        self.readPool = WeightedPool(readPool)
        if readPool is writePool:
            self.writePool = self.readPool
        else:
            if writePool is None: writePool = []
            self.writePool = WeightedPool(writePool)

    def dbWrite(self, key, sqlQuery, *args):
        startTime = time()
        poolItem = self.writePool.getPoolItem()
        #log.msg('dbWrite-DEBUG: sql: %s' % sqlQuery)
        #log.msg('dbWrite-DEBUG: args: %s' % str(args))
        d = poolItem.value.runQuery(sqlQuery, args)
        d.addCallback(self.dbWriteSuccess, poolItem, startTime)
        d.addErrback(self.dbWriteError, poolItem, startTime)
        return d
        
    def dbWriteSuccess(self, results, poolItem, startTime):
        poolItem.addStat(time()-startTime)
        return results

    def dbInsert(self, key, sqlQuery, *args):
        startTime = time()
        poolItem = self.writePool.getPoolItem()
        #log.msg('dbInsert-DEBUG: sql: %s' % sqlQuery)
        #log.msg('dbInsert-DEBUG: args: %s' % str(args))
        d = poolItem.value.runInteraction(self._insert, sqlQuery, args)
        d.addCallback(self.dbWriteSuccess, poolItem, startTime)
        d.addErrback(self.dbWriteError, poolItem, startTime)
        return d
    
    def _insert(self, trans, query, query_args):
        trans.execute(query,query_args)
        trans.execute('SELECT LAST_INSERT_ID()')
        data = trans.fetchall()
        lastInsertID = data[0][0]
        return lastInsertID
    
    def dbRead(self, key, sqlQuery, *args):
        startTime = time()
        poolItem = self.readPool.getPoolItem()
        #log.msg('dbRead-DEBUG: sql: %s' % sqlQuery)
        #log.msg('dbRead-DEBUG: args: %s' % str(args))
        d = poolItem.value.runQuery(sqlQuery, args)
        d.addCallback(self.dbReadSuccess, poolItem, startTime)
        d.addErrback(self.dbReadError, poolItem, startTime)
        return d

    def dbReadSuccess(self, results, poolItem, startTime):
        poolItem.addStat(time()-startTime)
        return results

    def dbReadInteraction(self, key, interaction, *args):
        startTime = time()
        poolItem = self.writePool.getPoolItem()
        d = poolItem.value.runInteraction(interaction, *args)
        d.addCallback(self.dbReadSuccess, poolItem, startTime)
        d.addErrback(self.dbReadError, poolItem, startTime)
        return d

    def dbWriteInteraction(self, key, interaction, *args):
        startTime = time()
        poolItem = self.writePool.getPoolItem()
        d = poolItem.value.runInteraction(interaction, *args)
        d.addCallback(self.dbWriteSuccess, poolItem, startTime)
        d.addErrback(self.dbWriteError, poolItem, startTime)
        return d

    def error(self, error):
        log.msg('ERROR: error in DB retrieval: %s' % error.value)
        error.raiseException()

    def dbReadError(self, error, startTime, poolItem):
        log.msg(
            'ALERT: dbReadError: %s (type: %s)' % (
            error.value, error.value.__class__))
        return error

    def dbWriteError(self, error, startTime, poolItem):
        log.msg(
            'ALERT: dbWriteError: %s (type: %s)' % (
            error.value, error.value.__class__))
        log.msg(error.getTraceback())
        return error

