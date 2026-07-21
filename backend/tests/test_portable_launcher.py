import importlib.util
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
        tmp_path, '127.0.0.1', 5050) == ('0.0.0.0', 6123)
    assert not request.exists()
    assert launcher._browser_url('0.0.0.0', 6123) == 'http://127.0.0.1:6123/'


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
        tmp_path, '127.0.0.1', 5050) == ('127.0.0.1', 5050)
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
