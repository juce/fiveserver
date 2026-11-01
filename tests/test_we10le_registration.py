"""Registration and application-wiring checks; no external database required."""

import binascii
from hashlib import md5
from pathlib import Path
import runpy
from types import SimpleNamespace

from Crypto.Cipher import Blowfish
from twisted.application.service import IServiceCollection
from twisted.internet import defer, task
from twisted.web.server import NOT_DONE_YET
from twisted.web.test.requesthelper import DummyRequest

from fiveserver import config, register, storagecontroller
from fiveserver.model import user


ROOT = Path(__file__).resolve().parents[1]
KEY = ('27501fd04e6b82c831024dac5c6305221974deb9388a2190'
       '1d576cbbe2f377ef23d75486010f37819afe6c321a0146d2'
       '1544ec365bf7289a')


def request(method, path):
    req = DummyRequest([])
    req.method = method
    req.path = path
    req.getClientIP = lambda: '127.0.0.1'
    return req


def test_form_hook_preserves_pc_registration():
    cfg = SimpleNamespace(cipherKey=KEY)
    pc = register.RegistrationResource(cfg, str(ROOT / 'web6'))
    ps2 = register.RegistrationResource(
        cfg, str(ROOT / 'web6'), formFile='form-we10le.html')
    assert b'Sixserver Registration Form' in pc.render_GET(request(b'GET', b'/'))
    form = ps2.render_GET(request(b'GET', b'/'))
    assert b'SLKA-25153' in form
    assert b"username + '\\0'.repeat(16) + password" in form
    assert b'/md5.js' in form
    assert b'function hex_md5' in ps2.render_GET(request(b'GET', b'/md5.js'))


def test_registration_hash_authentication_and_nonce_form():
    records = []
    account = user.User(b'')
    account.username, account.nonce, account.serial = 'Player01', 'nonce42', 'SLKA-25153'
    cfg = SimpleNamespace(
        cipherKey=KEY,
        isBanned=lambda ip: False,
        userData=SimpleNamespace(
            findByUsername=lambda name: defer.succeed([]),
            findByNonce=lambda nonce: defer.succeed([account])))

    def create(username, serial, credential_hash, nonce):
        records.append((username, serial, credential_hash, nonce))
        return defer.succeed(account)

    cfg.createUser = create
    resource = register.RegistrationResource(
        cfg, str(ROOT / 'web6'), formFile='form-we10le.html')
    digest = md5(b'Player01' + b'\0' * 16 + b' space ').digest()
    req = request(b'POST', b'/register')
    req.args = {b'serial': [b'SLKA-25153'], b'user': [b'Player01'],
                b'hash': [digest.hex().encode()], b'nonce': [b''],
                b'format': [b'html']}
    assert resource.render_POST(req) == NOT_DONE_YET
    encrypted = Blowfish.new(binascii.unhexlify(KEY), Blowfish.MODE_ECB).encrypt(digest)
    assert records == [('Player01', 'SLKA-25153', encrypted.hex().encode(), None)]
    assert req.finished
    assert b'SUCCESS' in b''.join(req.written)

    req = request(b'GET', b'/modifyUser/nonce42')
    assert resource.render_GET(req) == NOT_DONE_YET
    assert req.finished
    assert b'value="Player01"' in b''.join(req.written)
    assert b'value="nonce42"' in b''.join(req.written)


def test_tac_binds_separate_ps2_services(monkeypatch):
    # Use the actual YAML/config/service constructors. Only database creation
    # and timer execution are isolated; constructing does not open TCP ports.
    clock = task.Clock()
    monkeypatch.setattr(config, 'reactor', clock)
    monkeypatch.setattr(storagecontroller, 'reactor', clock)
    monkeypatch.setattr(storagecontroller, 'getDbPool', lambda *a, **kw: [])
    monkeypatch.setenv('FSROOT', str(ROOT))
    result = runpy.run_path(str(ROOT / 'tac/we10le.tac'))
    services = IServiceCollection(result['application']).services
    assert len(services) == 5
    by_port = {svc.args[0]: svc.args[1] for svc in services}
    assert set(by_port) == {10881, 20210, 20211, 20212, 8195}
    from fiveserver.protocol import we10le
    assert by_port[10881].protocol is we10le.NewsProtocol
    assert by_port[20210].protocol is we10le.MainService
    assert by_port[20211].protocol is we10le.NetworkMenuService
    assert by_port[20212].protocol is we10le.LoginService
    assert by_port[8195].resource.formFile == 'form-we10le.html'
    assert result['config'].serverConfig.Roster == {
        'enforceHash': False, 'compareHash': False}
