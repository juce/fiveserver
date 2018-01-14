"""
Simple logger module to wrap twisted.python.log
and to provide additional levels of logging, i.e. debug
"""

from twisted.python import log


_debug = False


def getDebug():
    return _debug


def setDebug(value):
    global _debug
    _debug = value
    log.msg('SYSTEM: Debug is %s' % {
        True:'ON', False:'OFF'}.get(_debug))

def msg(message):
    log.msg(message)


def debug(message):
    if _debug:
        log.msg(message)
    
