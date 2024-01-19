from twisted.application import service, internet
from twisted.web import static, server, resource
from xml.sax.saxutils import escape
from Crypto.Cipher import Blowfish

from fiveserver import log
from fiveserver.model import util
import binascii


XML_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="/xsl/style.xsl"?>
"""


def getFormContent(webDir):
    try:
        f = open('%s/form.html' % webDir)
    except IOError:
        f = open('%s/form-sample.html' % webDir)
    return f.read()


def getResultContent(webDir):
    try:
        f = open('%s/result.html' % webDir)
    except IOError:
        f = open('%s/result-sample.html' % webDir)
    return f.read()


class RegistrationResource(resource.Resource):
    isLeaf = True
    def __init__(self, config, webDir):
        self.xsl = open('%s/style.xsl' % webDir).read()
        self.config = config
        self.webDir = webDir
        self.cipher = Blowfish.new(binascii.a2b_hex(self.config.cipherKey), Blowfish.MODE_ECB)

    def render_GET(self, request):
        if request.path == b'/xsl/style.xsl':
            request.setHeader('Content-Type','text/xml')
            return self.xsl.encode('utf-8')
        elif request.path.startswith(b'/modifyUser/'):
            def _found(results):
                if not results:
                    username,nonce,serial = '','',''
                else:
                    usr = results[0]
                    username,nonce,serial = usr.username,usr.nonce,usr.serial
                s = getFormContent(self.webDir)
                s = s % {'username':username,
                         'nonce':nonce,
                         'serial':serial}
                request.write(s.encode('utf-8'))
                request.finish()
            request.setHeader('Content-Type','text/html')
            nonce = request.path.split(b'/')[-1]
            d = self.config.userData.findByNonce(nonce)
            d.addCallback(_found)
            return server.NOT_DONE_YET

        elif request.path == b'/md5.js':
            request.setHeader('Content-Type','text/javascript')
            return open('%s/md5.js' % self.webDir).read().encode('utf-8')
        else:
            request.setHeader('Content-Type','text/html')
            s = getFormContent(self.webDir)
            s = s % {'username':'','nonce':'','serial':''}
            return s.encode('utf-8')
 
    def sendHtmlResponse(self, request, message):
        request.setHeader('Content-Type','text/html')
        s = getResultContent(self.webDir)
        s = s.decode('utf-8') % {'result': message}
        return s.encode('utf-8')

    def sendXmlResponse(self, request, message):
        request.setHeader('Content-Type','text/xml')
        s = '%s<result text="%s" />' % (XML_HEADER, message)
        return s.encode('utf-8')

    def sendResponse(self, fmt, request, message):
        if fmt == 'html':
            return self.sendHtmlResponse(request, message)
        return self.sendXmlResponse(request, message)

    def render_POST(self, request):
        def _created(usr):
            request.write(self.sendResponse(
                fmt, request, 'SUCCESS: Registration complete'))
            request.finish()
        def _failed(error):
            log.msg('ERROR: %s' % str(error.value))
            request.setResponseCode(500)
            request.write(self.sendResponse(
                fmt, request, 'ERROR: Unable to register: server errror'))
            request.finish()
        def _modifyUser(results, serial, username, hash, nonce):
            if not results:
                request.setResponseCode(404)
                request.write(
                    self.sendResponse(
                        fmt, request, 
                        'ERROR: Cannot modify user: invalid nonce'))
                request.finish()
                return
            d = self.config.createUser(username, serial, hash, nonce)
            d.addCallback(_created)
            d.addErrback(_failed)
            return d
        def _createNew(results, serial, username, hash):
            if results:
                request.setResponseCode(409)
                request.write(
                    self.sendResponse(
                        fmt, request, 
                        'ERROR: Cannot register: username taken'))
                request.finish()
                return
            d = self.config.createUser(username, serial, hash, None)
            d.addCallback(_created)
            d.addErrback(_failed)
            return d
        serial = request.args[b'serial'][0].decode('utf-8')
        username = request.args[b'user'][0].decode('utf-8')
        hash = request.args[b'hash'][0].decode('utf-8')
        nonce = request.args[b'nonce'][0].decode('utf-8')
        try: fmt = request.args[b'format'][0].decode('utf-8')
        except: fmt = None
        #userKey = '%s-%s' % (
        #        binascii.b2a_hex(
        #            self.cipher.encrypt(util.padWithZeros(serial,24))),
        #        binascii.b2a_hex(
        #            self.cipher.encrypt(binascii.a2b_hex(hash))))
        #print 'userKey: {%s}' % userKey
        hash = binascii.b2a_hex(self.cipher.encrypt(binascii.a2b_hex(hash)))
        log.msg('userHash: {%s}' % hash)
        request.setHeader('Content-Type','text/xml')
        if self.config.isBanned(request.getClientIP()):
            request.setResponseCode(403)
            return self.sendResponse(
                fmt, request, 'ERROR: Cannot register: your IP is banned')
        elif nonce in [None,'']:
            # create new
            d = self.config.userData.findByUsername(username)
            d.addCallback(_createNew, serial, username, hash)
            d.addErrback(_failed)
            return server.NOT_DONE_YET
        else:
            # modify existing
            d = self.config.userData.findByNonce(nonce)
            d.addCallback(_modifyUser, serial, username, hash, nonce) 
            d.addErrback(_failed)
            return server.NOT_DONE_YET

