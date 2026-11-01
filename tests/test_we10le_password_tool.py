"""The operator's password repair must use the game's existing auth format."""
from hashlib import md5
from pathlib import Path
import runpy

import pytest
from Crypto.Cipher import Blowfish


TOOL = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tools/we10le_set_password.py'))


def test_repaired_credential_matches_game_auth_ciphertext():
    username, password = 'Player01', 'ABCDEFGHIJKL'
    digest = md5(username.encode() + b'\0' * 16 + password.encode()).digest()
    # The game encrypts 64 bytes; the stored credential is its digest blocks.
    clear = username.encode().ljust(32, b'\0') + digest + b'\0' * 16
    packet = Blowfish.new(TOOL['CIPHER_KEY'], Blowfish.MODE_ECB).encrypt(clear)
    assert TOOL['account_hash'](username, password) == packet[32:48].hex()


@pytest.mark.parametrize('password', ['', 'abc', '123', 'M', 'A L', 'A' * 32, '한글'])
def test_unenterable_game_password_is_rejected(password):
    with pytest.raises(ValueError):
        TOOL['account_hash']('Player01', password)


@pytest.mark.parametrize('password', ['A', 'L' * 31])
def test_actual_game_password_boundaries(password):
    assert len(TOOL['account_hash']('Player01', password)) == 32
