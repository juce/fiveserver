"""
Model classes for PES5/PES6 packet server.
(headers, packets, etc.)
"""

import hashlib
import struct
import binascii

from fiveserver import errors


def makePacketHeader(bs):
    """
    Create a packet header from a string buffer
    """
    id = struct.unpack('!H', bs[0:2])[0]
    length = struct.unpack('!H', bs[2:4])[0]
    packet_count = struct.unpack('!I',bs[4:8])[0]
    return PacketHeader(id, length, packet_count)
     

def readPacketHeader(stream):
    """
    Read bytes from the stream and create a packet header
    """
    return makePacketHeader(stream.read(8))
 

def makePacket(bs):
    """
    Read bytes from the stream and create a packet
    """
    header = makePacketHeader(bs[0:8])
    md5 = bs[8:24]
    data = bs[24:24 + header.length]
    p = Packet(header, data)
    if p.md5.digest() != md5:
        raise errors.NetworkError(
            'Wrong MD5-checksum! (expected: %s, got: %s)' % (
            p.md5.hexdigest(),
            binascii.b2a_hex(md5)))
    return p


def readPacket(stream):
    """
    Read bytes from the stream and create a packet
    """
    header = readPacketHeader(stream)
    md5 = stream.read(16)
    data = stream.read(header.length)
    p = Packet(header, data)
    if p.md5.digest() != md5:
        raise errors.NetworkError(
            'Wrong MD5-checksum! (expected: %s, got: %s)' % (
            p.md5.hexdigest(),
            binascii.b2a_hex(md5)))
    return p
 

class PacketHeader:
    """
    Packet header (id, length, packet-counter)
    """
    def __init__(self, id, length, packet_count):
        self.id = id
        self.length = length
        self.packet_count = packet_count

    def __bytes__(self):
        return b'%s%s%s' % (
                struct.pack('!H',self.id),
                struct.pack('!H',self.length),
                struct.pack('!I',self.packet_count))

    def __repr__(self):
        return 'PacketHeader(0x%04x,%d,%d)' % (
                self.id,
                self.length,
                self.packet_count)


class Packet:
    """ 
    Encapsulates a PES packet, which consists 
    of three things: header, md5, data
    """
    def __init__(self, header, data):
        self.header = header
        self.data = data
        print("self.header:", self.header)
        print("self.data:", self.data)
        self.md5 = hashlib.md5(b'%s%s' % (header,data))
        
    def __bytes__(self):
        return b'%s%s%s' % (
                self.header,
                self.md5.digest(),
                self.data)

    def __repr__(self): 
        return 'Packet(%s,md5="%s",data:"%s")' % (
                repr(self.header),
                self.md5.hexdigest(),
                binascii.b2a_hex(self.data))

