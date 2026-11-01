"""Interactively replace one WE10LE game password, preserving its profiles.

Run manually inside the application container. Never pass passwords as command
arguments. The database password comes from the existing deployment environment.
"""
import getpass
import hashlib
import os
import re
import sys

from Crypto.Cipher import Blowfish


# Public legacy protocol key, identical to FiveServerConfig.cipherKey.
CIPHER_KEY = bytes.fromhex(
    '27501fd04e6b82c831024dac5c6305221974deb9388a2190'
    '1d576cbbe2f377ef23d75486010f37819afe6c321a0146d2'
    '1544ec365bf7289a')


def account_hash(username, password):
    if re.fullmatch(r'[A-Za-z0-9]{3,31}', username) is None:
        raise ValueError('Username must contain 3-31 ASCII letters or digits.')
    if re.fullmatch(r'[A-L]{1,31}', password) is None:
        raise ValueError('The Korean game accepts 1-31 uppercase characters A-L only.')
    digest = hashlib.md5(username.encode('ascii') + b'\0' * 16 + password.encode('ascii')).digest()
    return Blowfish.new(CIPHER_KEY, Blowfish.MODE_ECB).encrypt(digest).hex()


def main():
    import pymysql

    username = input('Existing game ID (case-sensitive): ')
    password = getpass.getpass('New game password (uppercase A-L only): ')
    confirmation = getpass.getpass('Repeat new game password: ')
    if password != confirmation:
        print('Passwords do not match. Nothing was changed.', file=sys.stderr)
        return 1
    try:
        new_hash = account_hash(username, password)
    except ValueError as error:
        print(str(error) + ' Nothing was changed.', file=sys.stderr)
        return 1
    if not os.environ.get('DB_PASSWORD'):
        print('Run this tool inside the existing app container. Nothing was changed.', file=sys.stderr)
        return 1
    connection = None
    try:
        connection = pymysql.connect(
            host=os.environ.get('DB_HOST', 'db'),
            port=int(os.environ.get('DB_PORT', '3306')),
            user=os.environ.get('DB_USER', 'we10le'),
            password=os.environ['DB_PASSWORD'],
            database=os.environ.get('DB_NAME', 'we10le'),
            charset='utf8', autocommit=False,
            connect_timeout=5, read_timeout=10, write_timeout=10)
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM users WHERE deleted=0 AND BINARY username=%s FOR UPDATE', (username,))
            row = cursor.fetchone()
            if row is None:
                connection.rollback()
                print('Game ID not found with that exact spelling. Nothing was changed.', file=sys.stderr)
                return 1
            cursor.execute('UPDATE users SET hash=%s, reset_nonce=NULL WHERE id=%s', (new_hash, row[0]))
        connection.commit()
        print('Game password updated. Existing account and profiles were preserved.')
        return 0
    except (pymysql.MySQLError, ValueError):
        if connection is not None:
            try:
                connection.rollback()
            except pymysql.MySQLError:
                pass
        print('Database update failed. Check the app/database services; no credentials are displayed.', file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except pymysql.MySQLError:
                pass


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(130)
