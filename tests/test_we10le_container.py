"""Container configuration and startup checks without Docker or a database."""

import importlib.util
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'we10le_container_entrypoint', ROOT / 'docker/we10le/entrypoint.py')
entrypoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entrypoint)
TEMPLATE = ROOT / 'etc/conf/we10le.yaml'


def environment(**updates):
    result = {'WE10LE_SERVER_IP': '192.168.1.50', 'DB_PASSWORD': ' private password '}
    result.update(updates)
    return result


def test_runtime_environment_overrides_only_deployment_values():
    before = TEMPLATE.read_bytes()
    original = yaml.safe_load(before)
    result = entrypoint.runtime_config(TEMPLATE, environment(
        DB_HOST='database.internal', DB_PORT='3307',
        DB_NAME='we10le_test', DB_USER='test_user'))
    assert result['ServerIP'] == '192.168.1.50'
    assert result['DB']['password'] == ' private password '
    assert result['DB']['port'] == 3307
    assert result['DB']['name'] == 'we10le_test'
    assert result['DB']['user'] == 'test_user'
    assert result['DB']['readServers'] == ['database.internal']
    assert result['DB']['writeServers'] == ['database.internal']
    assert result['DB']['ConnectionPool'] == original['DB']['ConnectionPool']
    assert result['BannedList'] == '/var/lib/we10le/banned.yaml'
    for key in original.keys() - {'ServerIP', 'DB', 'BannedList'}:
        assert result[key] == original[key]
    assert TEMPLATE.read_bytes() == before


def test_default_database_settings_and_loopback_opt_in():
    result = entrypoint.runtime_config(TEMPLATE, environment())
    assert result['TraceProtocol'] is False
    assert result['AuthMode'] == 'username'
    assert result['DB']['readServers'] == ['db']
    assert result['DB']['port'] == 3306
    assert result['DB']['name'] == result['DB']['user'] == 'we10le'
    result = entrypoint.runtime_config(TEMPLATE, environment(
        WE10LE_SERVER_IP='127.0.0.1', WE10LE_ALLOW_LOOPBACK='1'))
    assert result['ServerIP'] == '127.0.0.1'


@pytest.mark.parametrize('value,enabled', [('0', False), ('1', True)])
def test_protocol_trace_environment_is_a_separate_boolean(value, enabled):
    result = entrypoint.runtime_config(TEMPLATE, environment(WE10LE_PROTOCOL_TRACE=value))
    assert result['TraceProtocol'] is enabled
    assert result['Debug'] is False


def test_protocol_trace_environment_does_not_echo_invalid_values():
    with pytest.raises(entrypoint.RuntimeConfigError) as error:
        entrypoint.runtime_config(TEMPLATE, environment(WE10LE_PROTOCOL_TRACE='private-invalid-value'))
    assert str(error.value) == 'WE10LE_PROTOCOL_TRACE must be 0 or 1.'


def auth_template(tmp_path, mode, include=True):
    config = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8'))
    if include:
        config['AuthMode'] = mode
    else:
        config.pop('AuthMode', None)
    path = tmp_path / 'auth-template.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    return path


@pytest.mark.parametrize('mode', ['username', 'password'])
def test_auth_mode_uses_template_when_environment_is_absent(tmp_path, mode):
    template = auth_template(tmp_path, mode)
    result = entrypoint.runtime_config(template, environment())
    assert result['AuthMode'] == mode


def test_missing_template_auth_mode_defaults_to_username(tmp_path):
    template = auth_template(tmp_path, None, include=False)
    result = entrypoint.runtime_config(template, environment())
    assert result['AuthMode'] == 'username'


@pytest.mark.parametrize('mode', ['username', 'password'])
def test_auth_mode_environment_overrides_template_and_preserves_trace(tmp_path, mode):
    other_mode = 'password' if mode == 'username' else 'username'
    template = auth_template(tmp_path, other_mode)
    result = entrypoint.runtime_config(template, environment(
        WE10LE_AUTH_MODE=mode, WE10LE_PROTOCOL_TRACE='1'))
    assert result['AuthMode'] == mode
    assert result['TraceProtocol'] is True
    assert result['Debug'] is False


@pytest.mark.parametrize('mode', ['', 'USERNAME', 'password ', 'private-invalid-value'])
def test_invalid_auth_environment_does_not_echo_values(mode, capsys):
    with pytest.raises(entrypoint.RuntimeConfigError) as error:
        entrypoint.runtime_config(TEMPLATE, environment(WE10LE_AUTH_MODE=mode))
    assert str(error.value) == 'WE10LE_AUTH_MODE must be username or password.'
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('mode', [None, 1, True, [], 'private-invalid-value'])
def test_invalid_template_auth_mode_is_rejected_without_echo(tmp_path, mode, capsys):
    template = auth_template(tmp_path, mode)
    with pytest.raises(entrypoint.RuntimeConfigError) as error:
        entrypoint.runtime_config(template, environment(WE10LE_AUTH_MODE='username'))
    assert str(error.value) == 'AuthMode must be username or password.'
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('updates', [
    {'WE10LE_SERVER_IP': ''}, {'WE10LE_SERVER_IP': 'not-an-ip'},
    {'WE10LE_SERVER_IP': '::1'}, {'WE10LE_SERVER_IP': '127.0.0.1'},
    {'WE10LE_SERVER_IP': '0.0.0.0'}, {'WE10LE_SERVER_IP': '224.0.0.1'},
    {'WE10LE_SERVER_IP': '255.255.255.255'}, {'DB_PASSWORD': ''},
    {'DB_PORT': 'secret-invalid-port'}, {'DB_PORT': '65536'},
    {'DB_HOST': ''}, {'DB_NAME': 'db;drop'},
])
def test_invalid_environment_errors_do_not_echo_supplied_values(updates, capsys):
    with pytest.raises(entrypoint.RuntimeConfigError) as error:
        entrypoint.runtime_config(TEMPLATE, environment(**updates))
    assert ' private password ' not in str(error.value)
    assert 'secret-invalid-port' not in str(error.value)
    assert capsys.readouterr() == ('', '')


def test_runtime_credentials_are_written_privately(tmp_path):
    result = entrypoint.runtime_config(TEMPLATE, environment())
    target = tmp_path / 'runtime.yaml'
    assert entrypoint.write_runtime_config(result, target) == target
    assert yaml.safe_load(target.read_text(encoding='utf-8')) == result
    assert list(tmp_path.iterdir()) == [target]
    if os.name != 'nt':
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


class Clock:
    def __init__(self):
        self.now = 0
        self.delays = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.now += seconds


class Connection:
    def __init__(self, fail_query=None):
        self.fail_query = fail_query
        self.queries = []
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query):
        self.queries.append(query)
        if query == self.fail_query:
            raise RuntimeError('secret-connector-detail')

    def close(self):
        self.closed = True


def test_database_wait_retries_until_schema_exists_without_leaking_errors(capsys):
    config = entrypoint.runtime_config(TEMPLATE, environment())
    incomplete = Connection(fail_query='SELECT id FROM profiles LIMIT 0')
    ready = Connection()
    connections = iter([incomplete, ready])
    calls = []
    clock = Clock()
    messages = []

    def connect(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError(' private password ')
        return next(connections)

    entrypoint.wait_for_database(
        config, connect=connect, timeout=10, interval=2,
        monotonic=clock.monotonic, sleep=clock.sleep, report=messages.append)
    assert clock.delays == [2, 2]
    assert incomplete.closed and ready.closed
    assert ready.queries == [
        'SELECT 1', 'SELECT id FROM users LIMIT 0', 'SELECT id FROM profiles LIMIT 0']
    assert all(call['password'] == ' private password ' for call in calls)
    assert all(call['connect_timeout'] <= 5 for call in calls)
    assert ' private password ' not in ''.join(messages)
    assert 'secret-connector-detail' not in ''.join(messages)
    assert capsys.readouterr() == ('', '')


def test_database_wait_stops_at_deadline_and_suppresses_connector_details(capsys):
    clock = Clock()
    config = entrypoint.runtime_config(TEMPLATE, environment())
    calls = []

    def connect(**kwargs):
        calls.append(kwargs)
        raise RuntimeError(' private password ')

    with pytest.raises(entrypoint.DatabaseNotReady) as error:
        entrypoint.wait_for_database(
            config, connect=connect, timeout=5, interval=2,
            monotonic=clock.monotonic, sleep=clock.sleep)
    assert clock.now == 5
    assert clock.delays == [2, 2, 1]
    assert len(calls) == 3
    captured = capsys.readouterr()
    assert ' private password ' not in captured.out + captured.err + str(error.value)


def test_startup_installs_mysql_alias_before_importing_twisted(monkeypatch, tmp_path):
    events = []
    config = entrypoint.runtime_config(TEMPLATE, environment())
    monkeypatch.setattr(entrypoint, 'APP_ROOT', tmp_path)
    monkeypatch.setattr(entrypoint, 'BANNED_PATH', tmp_path / 'data/banned.yaml')
    monkeypatch.setattr(entrypoint, 'runtime_config', lambda: config)
    monkeypatch.setattr(entrypoint, 'write_runtime_config', lambda cfg: tmp_path / 'runtime.yaml')
    driver = SimpleNamespace(
        install_as_MySQLdb=lambda: events.append('mysql-alias'),
        connect=object())
    monkeypatch.setitem(sys.modules, 'pymysql', driver)

    def wait(cfg, connect):
        assert cfg is config and connect is driver.connect
        assert events == ['mysql-alias']
        events.append('database-ready')

    def run():
        assert events == ['mysql-alias', 'database-ready']
        assert os.environ['FSROOT'] == str(tmp_path)
        assert os.environ['WE10LE_CONFIG'] == str(tmp_path / 'runtime.yaml')
        assert sys.argv == [
            'twistd', '-noy', str(tmp_path / 'tac/we10le.tac'),
            '--pidfile=/tmp/we10le.pid', '--logfile=-']
        events.append('twisted')

    monkeypatch.setattr(entrypoint, 'wait_for_database', wait)
    monkeypatch.setitem(sys.modules, 'twisted.scripts.twistd', SimpleNamespace(run=run))
    monkeypatch.setenv('FSROOT', 'before-test')
    monkeypatch.setenv('WE10LE_CONFIG', 'before-test')
    monkeypatch.setattr(sys, 'argv', ['before-test'])
    monkeypatch.chdir(tmp_path)
    assert entrypoint.main() == 0
    assert events == ['mysql-alias', 'database-ready', 'twisted']
