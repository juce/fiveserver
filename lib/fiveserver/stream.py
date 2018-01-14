"""
Stream classes
"""

import operator


XOR_KEY = '\xa6\x77\x95\x7c'


def xorData(data, start=0):
    chars = []
    key_size = len(XOR_KEY)
    for i,c in enumerate(data):
        chars.append(chr(operator.xor(
            ord(XOR_KEY[(start+i) % key_size]), ord(c))))
    return ''.join(chars)
 

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

