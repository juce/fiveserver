"""
Various utilities.
"""


import re


def stripZeros(s):
    izero = s.find('\0')
    if izero >= 0:
        return s[:izero]
    return s


def padWithZeros(s, total):
    if isinstance(s, unicode):
        s = s.encode('utf-8', 'replace')
    ns = str(s[:total])
    ns += '\0'*(total-len(ns))
    return ns


def toUnicode(s):
    if isinstance(s, unicode):
        return s
    return s.decode('utf-8', 'replace')


class PacketFormatter:
    """
    Pretty but slow packet formatter. Use for debugging only.
    """

    NUM_CHARS_IN_LINE = 8

    def format(pkt, cipher=None):
        headerline = 'Packet: id=0x%04x, length=0x%x, count=%d' % (
                pkt.header.id,
                pkt.header.length,
                pkt.header.packet_count)
        if pkt.header.length==0:
            return headerline
        data = pkt.data
        if cipher is not None:
            data = cipher.decrypt(data)
        return '%s\n%s' % (
                headerline,
                '\n'.join(PacketFormatter._breakPacketData(data)))
    format = staticmethod(format)

    def _breakPacketData(data):
        i, lines = 0, []
        while i<len(data):
            if i+PacketFormatter.NUM_CHARS_IN_LINE > len(data):
                chunk = data[i:]
            else:
                chunk = data[i:i+PacketFormatter.NUM_CHARS_IN_LINE] 
            hexstr = ' '.join(['%02x' % ord(c) for c in chunk])
            asciistr = re.sub(r"""[^\w .,!?'"/<>-]""",'.',chunk)
            padding = '   '*(PacketFormatter.NUM_CHARS_IN_LINE-len(chunk))
            lines.append('%s%s  %s' % (hexstr, padding, asciistr))
            i += PacketFormatter.NUM_CHARS_IN_LINE 
        return lines
    _breakPacketData = staticmethod(_breakPacketData)


