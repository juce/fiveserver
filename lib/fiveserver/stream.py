"""
Stream classes
"""

import operator
import struct


XOR_KEY = b'\xa6\x77\x95\x7c'


def xorData(data, start=0):
    bs = []
    key_size = len(XOR_KEY)
    for i,c in enumerate(data):
        bs.append(struct.pack('!B', operator.xor(
            XOR_KEY[(start+i) % key_size], c)
        ))
    return b''.join(bs)
 

class XorStream:

    def __init__(self, s):
        self._stream = s

    def read(self, numBytes=None):
        start = self._stream.tell()
        if numBytes is None:
            data = self._stream.read()
        else:
            data = self._stream.read(numBytes)
        return xorData(data, start)

    def __getattr__(self, name):
        return getattr(self._stream, name)

