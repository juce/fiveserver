"""Configure and run the dedicated WE10LE service inside its Linux container."""

import ipaddress
import os
from pathlib import Path
import re
import sys
import tempfile
import time

import yaml


APP_ROOT = Path('/opt/fiveserver')
TEMPLATE_PATH = APP_ROOT / 'etc/conf/we10le.yaml'
RUNTIME_CONFIG_PATH = Path('/tmp/we10le.yaml')
BANNED_PATH = Path('/var/lib/we10le/banned.yaml')


class RuntimeConfigError(ValueError):
    """A configuration error whose message never includes supplied values."""


class DatabaseNotReady(RuntimeError):
    """The database or its initialized schema did not become available."""


def runtime_config(template_path=TEMPLATE_PATH, environ=None):
    """Load the shipped template and apply only the deployment environment."""
    environ = os.environ if environ is None else environ
    address = environ.get('WE10LE_SERVER_IP', '')
    if not address:
        raise RuntimeConfigError('WE10LE_SERVER_IP is required.')
    try:
        parsed_address = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        raise RuntimeConfigError('WE10LE_SERVER_IP must be an IPv4 address.') from None
    if (parsed_address.is_unspecified or parsed_address.is_multicast or
            int(parsed_address) == 0xffffffff or
            (parsed_address.is_loopback and
             environ.get('WE10LE_ALLOW_LOOPBACK') != '1')):
        raise RuntimeConfigError(
            'WE10LE_SERVER_IP must be a reachable unicast IPv4 address. '
            'Loopback is allowed only with WE10LE_ALLOW_LOOPBACK=1 for tests.')

    password = environ.get('DB_PASSWORD')
    if password is None or password == '':
        raise RuntimeConfigError('DB_PASSWORD is required.')
    host = environ.get('DB_HOST', 'db')
    username = environ.get('DB_USER', 'we10le')
    database = environ.get('DB_NAME', 'we10le')
    if not host or '\0' in host or not username or '\0' in username:
        raise RuntimeConfigError('DB_HOST and DB_USER must be nonempty and contain no NUL.')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', database):
        raise RuntimeConfigError('DB_NAME must contain 1-64 ASCII letters, digits, or underscores.')
    try:
        port = int(environ.get('DB_PORT', '3306'))
    except (TypeError, ValueError):
        raise RuntimeConfigError('DB_PORT must be an integer from 1 to 65535.') from None
    if not 1 <= port <= 65535:
        raise RuntimeConfigError('DB_PORT must be an integer from 1 to 65535.')

    try:
        with Path(template_path).open(encoding='utf-8') as source:
            config = yaml.safe_load(source)
    except (OSError, yaml.YAMLError):
        raise RuntimeConfigError('Unable to load the WE10LE configuration template.') from None
    if not isinstance(config, dict) or not isinstance(config.get('DB'), dict):
        raise RuntimeConfigError('The WE10LE configuration template must contain a DB mapping.')
    template_auth_mode = config.get('AuthMode', 'username')
    if template_auth_mode not in ('username', 'password'):
        raise RuntimeConfigError('AuthMode must be username or password.')
    auth_mode = environ.get('WE10LE_AUTH_MODE', template_auth_mode)
    if auth_mode not in ('username', 'password'):
        raise RuntimeConfigError('WE10LE_AUTH_MODE must be username or password.')
    config['AuthMode'] = auth_mode
    config['ServerIP'] = str(parsed_address)
    config['DB'].update({
        'name': database, 'user': username, 'password': password, 'port': port,
        'readServers': [host], 'writeServers': [host],
    })
    config['BannedList'] = BANNED_PATH.as_posix()
    trace = environ.get('WE10LE_PROTOCOL_TRACE')
    if trace is not None:
        if trace not in ('0', '1'):
            raise RuntimeConfigError('WE10LE_PROTOCOL_TRACE must be 0 or 1.')
        config['TraceProtocol'] = trace == '1'
    else:
        config.setdefault('TraceProtocol', False)
    return config


def write_runtime_config(config, path=RUNTIME_CONFIG_PATH):
    """Atomically write credentials to a private file, never into the image."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=path.parent,
                prefix='.we10le-', suffix='.yaml', delete=False) as target:
            temporary = Path(target.name)
            yaml.safe_dump(config, target, allow_unicode=True, sort_keys=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise RuntimeConfigError('Unable to write the private runtime configuration.') from None
    return path


def wait_for_database(config, connect=None, timeout=120, interval=2,
                      monotonic=time.monotonic, sleep=time.sleep, report=print):
    """Wait for MariaDB initialization without exposing connector error details."""
    if timeout <= 0 or interval <= 0:
        raise ValueError('Database wait timeout and interval must be positive.')
    if connect is None:
        import pymysql
        connect = pymysql.connect
    database = config['DB']
    deadline = monotonic() + timeout
    report('Waiting for the database and initialized users/profiles tables.')
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DatabaseNotReady(
                'Database/schema readiness timed out. Check the database service, '
                'credentials, and schema initialization.')
        connection = None
        try:
            io_timeout = max(1, min(5, int(remaining)))
            connection = connect(
                host=database['readServers'][0], port=database['port'],
                user=database['user'], password=database['password'],
                database=database['name'], charset='utf8', autocommit=True,
                connect_timeout=io_timeout, read_timeout=io_timeout,
                write_timeout=io_timeout)
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.execute('SELECT id FROM users LIMIT 0')
                cursor.execute('SELECT id FROM profiles LIMIT 0')
            report('Database and schema are ready.')
            return
        except Exception:
            # Connector messages may contain credentials; retry without logging them.
            pass
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DatabaseNotReady(
                'Database/schema readiness timed out. Check the database service, '
                'credentials, and schema initialization.')
        sleep(min(interval, remaining))


def main():
    try:
        config = runtime_config()
        BANNED_PATH.parent.mkdir(parents=True, exist_ok=True)
        config_path = write_runtime_config(config)
        import pymysql
        # Twisted adbapi imports MySQLdb; install this alias before loading any TAC.
        pymysql.install_as_MySQLdb()
        wait_for_database(config, connect=pymysql.connect)
    except (RuntimeConfigError, DatabaseNotReady) as error:
        print('WE10LE startup failed: ' + str(error), file=sys.stderr, flush=True)
        return 1
    except (ImportError, OSError):
        print('WE10LE startup failed: check container dependencies and writable '
              'runtime/data directories.', file=sys.stderr, flush=True)
        return 1

    os.environ['FSROOT'] = str(APP_ROOT)
    os.environ['WE10LE_CONFIG'] = str(config_path)
    os.chdir(APP_ROOT)
    sys.argv = [
        'twistd', '-noy', str(APP_ROOT / 'tac/we10le.tac'),
        '--pidfile=/tmp/we10le.pid', '--logfile=-',
    ]
    from twisted.scripts.twistd import run
    run()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
