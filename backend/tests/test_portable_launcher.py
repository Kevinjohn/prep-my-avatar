import importlib.util
import io
import json
from pathlib import Path

import pytest


@pytest.fixture(scope='module')
def launcher():
    path = Path(__file__).resolve().parents[2] / 'packaging' / 'launcher.py'
    spec = importlib.util.spec_from_file_location('portable_launcher_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_restart_request_updates_bind_and_is_consumed(launcher, tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    request = data / 'restart-request.json'
    request.write_text(json.dumps({'host': '0.0.0.0', 'port': 6123}), encoding='utf-8')

    assert launcher._consume_restart_request(
        tmp_path, '127.0.0.1', 5050) == ('0.0.0.0', 6123, None)
    assert not request.exists()
    assert launcher._browser_url('0.0.0.0', 6123) == 'http://127.0.0.1:6123/'


def test_recovery_bootstrap_forwards_restart_nonce(launcher, tmp_path, monkeypatch):
    python = tmp_path / 'python' / 'bin' / 'python'
    python.parent.mkdir(parents=True)
    python.touch()
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'update-recovery.py').touch()
    captured = {}

    class Result:
        returncode = 0
        stdout = ''
        stderr = ''

    monkeypatch.setattr(
        launcher.subprocess, 'run',
        lambda command, **kwargs: captured.update(command=command, **kwargs) or Result())
    assert launcher.run_recovery_bootstrap(tmp_path, 'a' * 32) == (True, '')
    assert captured['command'][-2:] == ['--restart-nonce', 'a' * 32]


def test_initial_bind_honours_saved_server_settings(launcher, tmp_path, monkeypatch):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'config.json').write_text(
        json.dumps({'server': {'host': '0.0.0.0', 'port': 6123}}), encoding='utf-8')
    monkeypatch.setattr(launcher, '_port_free', lambda port: port == 6123)
    assert launcher.initial_bind(tmp_path) == ('0.0.0.0', 6123)


@pytest.mark.parametrize('payload', (
    {'host': '', 'port': 6123},
    {'host': '127.0.0.1', 'port': 0},
    {'host': '127.0.0.1', 'port': 70000},
    {'host': 'bad\x00host', 'port': 6123},
))
def test_invalid_restart_request_keeps_current_bind(
        launcher, tmp_path, payload):
    data = tmp_path / 'data'
    data.mkdir(exist_ok=True)
    request = data / 'restart-request.json'
    request.write_text(json.dumps(payload), encoding='utf-8')

    assert launcher._consume_restart_request(
        tmp_path, '127.0.0.1', 5050) == ('127.0.0.1', 5050, None)
    assert not request.exists()


def test_start_server_passes_supervision_contract_and_closes_parent_log(
        launcher, tmp_path, monkeypatch):
    (tmp_path / 'python' / 'bin').mkdir(parents=True)
    (tmp_path / 'python' / 'bin' / 'python').touch()
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend' / 'run.py').touch()
    captured = {}
    sentinel = object()

    def popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        return sentinel

    monkeypatch.setattr(launcher.subprocess, 'Popen', popen)

    assert launcher.start_server(tmp_path, '127.0.0.1', 5050) is sentinel
    assert captured['env']['LDS_LAUNCHER_SUPERVISED'] == '1'
    assert captured['env']['LDS_HOST'] == '127.0.0.1'
    assert captured['env']['LDS_PORT'] == '5050'
    assert captured['stdout'] is captured['stderr']
    assert captured['stdout'].closed is True
    assert Path(captured['command'][-1]) == tmp_path / 'backend' / 'run.py'


def test_restart_readiness_requires_acknowledged_nonce(launcher, monkeypatch):
    responses = iter((
        {'ok': True, 'restart_acknowledged': True, 'restart_nonce': 'b' * 32},
        {'ok': True, 'restart_acknowledged': True, 'restart_nonce': 'a' * 32},
    ))

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return json.dumps(next(responses)).encode()

    class Process:
        @staticmethod
        def poll():
            return None

    monkeypatch.setattr(launcher.urllib.request, 'urlopen', lambda *_a, **_k: Response())
    assert launcher.wait_until_up(
        'http://127.0.0.1/ready', Process(), timeout=1,
        restart_nonce='a' * 32) is True


def test_readiness_timeout_is_reported_while_process_is_still_running(launcher):
    class Process:
        @staticmethod
        def poll():
            return None

    updates = []
    opened = launcher.report_startup_result(
        False, Process(), 'http://127.0.0.1:5050/',
        lambda message, **kwargs: updates.append((message, kwargs)), False)

    assert opened is False
    assert updates == [(
        '⚠️ The server is running but did not become ready.\n'
        'See data\\server.log for details.',
        {},
    )]


def test_smoke_test_starts_runtime_checks_frontend_and_stops(launcher, tmp_path, monkeypatch):
    (tmp_path / 'python' / 'bin').mkdir(parents=True)
    (tmp_path / 'python' / 'bin' / 'python').touch()

    class Process:
        terminated = False

        @staticmethod
        def poll():
            return None

        def terminate(self):
            self.terminated = True

        @staticmethod
        def wait(timeout):
            assert timeout == 8
            return 0

    class Response(io.BytesIO):
        status = 200
        headers = {'Content-Type': 'text/html; charset=utf-8'}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    process = Process()
    monkeypatch.setattr(launcher, 'bundle_dir', lambda: tmp_path)
    monkeypatch.setattr(launcher, 'initial_bind', lambda bundle: ('127.0.0.1', 6123))
    monkeypatch.setattr(launcher, 'start_server', lambda *args: process)
    monkeypatch.setattr(launcher, 'wait_until_up', lambda *args: True)
    monkeypatch.setattr(
        launcher.urllib.request, 'urlopen',
        lambda url, timeout: Response(b'<!doctype html><html></html>'))

    assert launcher.smoke_test() == 0
    assert process.terminated is True
