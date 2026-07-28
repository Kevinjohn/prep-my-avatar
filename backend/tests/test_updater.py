"""Self-updater service: git-behind status + apply (pull/deps). git is fully mocked —
no network, no real pull, no restart (schedule_restart is never called here)."""
import pytest
import json
import sqlite3

from app.services import updater

_REAL_VERIFY_APP_STARTUP = updater._verify_app_startup


class _R:
    def __init__(self, stdout='', stderr='', rc=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, rc


def _patch_git(monkeypatch, resp):
    monkeypatch.setattr(updater, 'is_git_checkout', lambda root=None: True)
    monkeypatch.setattr(updater, '_git', lambda root, *a, **k: resp(a))


@pytest.fixture(autouse=True)
def _isolated_transaction(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, '_journal_path',
                        lambda root: tmp_path / 'update-transaction.json')
    monkeypatch.setattr(updater, '_run_checked',
                        lambda *a, **k: (True, ''))
    monkeypatch.setattr(updater, '_verify_frontend',
                        lambda *a, **k: (True, ''))
    monkeypatch.setattr(updater, '_verify_app_startup',
                        lambda *a, **k: (True, ''))
    monkeypatch.setattr(
        updater, '_pip_environment_snapshot',
        lambda: ({'freeze': ['Flask==3.1.3'],
                  'packages': {'flask': '3.1.3'}}, ''),
    )
    monkeypatch.setattr(updater, '_restore_python_environment',
                        lambda *a, **k: True)
    monkeypatch.setattr(updater, '_install_recovery_bootstrap',
                        lambda *a, **k: (True, ''))


def test_status_none_when_not_a_git_checkout(monkeypatch):
    monkeypatch.setattr(updater, 'is_git_checkout', lambda root=None: False)
    assert updater.git_update_status() is None


def test_status_reports_commits_behind(monkeypatch):
    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'fetch':
            return _R()
        if a[0] == 'rev-list':
            return _R('3\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('aaaaaaa\n')
        if a[0] == 'rev-parse':
            return _R('bbbbbbb\n')      # origin/main short sha
        return _R()
    _patch_git(monkeypatch, resp)
    s = updater.git_update_status()
    assert s['is_git'] and s['behind'] == 3 and s['update_available'] is True
    assert s['current_sha'] == 'aaaaaaa' and s['remote_sha'] == 'bbbbbbb'
    # commit links so the user can read what the pending update contains
    assert s['repo'] and s['repo'] in s['commits_url']
    assert s['compare_url'].endswith('/compare/aaaaaaa...bbbbbbb')


def test_status_no_compare_url_when_up_to_date(monkeypatch):
    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'fetch':
            return _R()
        if a[0] == 'rev-list':
            return _R('0\n')
        return _R('aaaaaaa\n')
    _patch_git(monkeypatch, resp)
    s = updater.git_update_status()
    # up to date -> no incoming range to compare, but the history link stays
    assert 'compare_url' not in s
    assert s['commits_url'].endswith('/commits/main')


def test_status_up_to_date(monkeypatch):
    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'fetch':
            return _R()
        if a[0] == 'rev-list':
            return _R('0\n')
        return _R('aaaaaaa\n')
    _patch_git(monkeypatch, resp)
    assert updater.git_update_status()['update_available'] is False


@pytest.mark.parametrize('failing_command', [
    'branch', 'rev-list', 'local-sha', 'remote-sha',
])
def test_status_reports_failed_comparison_as_unavailable(monkeypatch, failing_command):
    def resp(a):
        key = ('branch' if a[:2] == ('rev-parse', '--abbrev-ref')
               else 'rev-list' if a[0] == 'rev-list'
               else 'local-sha' if a[-1] == 'HEAD'
               else 'remote-sha' if a[0] == 'rev-parse'
               else 'fetch')
        if key == failing_command:
            return _R('', 'failed', rc=1)
        if key == 'branch':
            return _R('main\n')
        if key == 'rev-list':
            return _R('1\n')
        if key in {'local-sha', 'remote-sha'}:
            return _R('aaaaaaa\n')
        return _R()

    _patch_git(monkeypatch, resp)
    result = updater.git_update_status()

    assert result['update_available'] is False
    assert result['ok'] is False
    assert 'reason' in result
    assert 'behind' not in result


def test_status_rejects_malformed_comparison_output(monkeypatch):
    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-list':
            return _R('not-a-count\n')
        if a[0] == 'rev-parse':
            return _R('aaaaaaa\n')
        return _R()

    _patch_git(monkeypatch, resp)
    result = updater.git_update_status()

    assert result['update_available'] is False
    assert 'invalid' in result['reason'].lower()


def test_apply_manual_when_not_git(monkeypatch):
    monkeypatch.setattr(updater, 'is_git_checkout', lambda root=None: False)
    r = updater.apply_update()
    assert r['ok'] is False and r['manual'] is True and 'releases' in r['url']


def test_supervised_restart_writes_handoff_then_exits_reserved_code(
        monkeypatch, tmp_path):
    exits = []

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setenv('LDS_LAUNCHER_SUPERVISED', '1')
    monkeypatch.setenv('LDS_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('LDS_HOST', '0.0.0.0')
    monkeypatch.setenv('LDS_PORT', '6123')
    monkeypatch.setattr(updater.threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(updater.os, '_exit', lambda code: exits.append(code))

    updater.schedule_restart(delay=0)

    payload = json.loads(
        (tmp_path / 'restart-request.json').read_text(encoding='utf-8'))
    assert payload == {'host': '0.0.0.0', 'port': 6123}
    assert exits == [updater.RESTART_EXIT_CODE]


def test_source_restart_does_not_exit_when_helper_creation_fails(monkeypatch):
    exits = []

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.delenv('LDS_LAUNCHER_SUPERVISED', raising=False)
    monkeypatch.setattr(updater.threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(
        updater.subprocess, 'Popen',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('cannot spawn')))
    monkeypatch.setattr(updater.os, '_exit', lambda code: exits.append(code))
    updater.schedule_restart(delay=0)
    assert exits == []


def test_source_restart_installs_private_pair_before_spawning_helper(
        monkeypatch, tmp_path):
    events = []

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.delenv('LDS_LAUNCHER_SUPERVISED', raising=False)
    monkeypatch.setenv('LDS_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(
        updater, '_install_recovery_bootstrap',
        lambda root: events.append(('install', root)) or (True, ''))
    monkeypatch.setattr(updater.threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(
        updater.subprocess, 'Popen',
        lambda *_args, **_kwargs: events.append(('spawn', None)) or object())
    monkeypatch.setattr(updater.os, '_exit', lambda code: events.append(('exit', code)))

    updater.schedule_restart(delay=0)

    assert [event[0] for event in events] == ['install', 'spawn', 'exit']


def test_source_restart_keeps_server_alive_when_private_pair_install_fails(
        monkeypatch):
    monkeypatch.delenv('LDS_LAUNCHER_SUPERVISED', raising=False)
    monkeypatch.setattr(
        updater, '_install_recovery_bootstrap', lambda _root: (False, 'disk full'))
    monkeypatch.setattr(
        updater.threading, 'Thread',
        lambda *_args, **_kwargs: pytest.fail('restart thread must not start'))

    with pytest.raises(RuntimeError, match='server remains running.*disk full'):
        updater.schedule_restart(delay=0)


def test_source_restart_helper_is_valid_and_carries_nonce(monkeypatch):
    commands = []

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    class Helper:
        pass

    monkeypatch.delenv('LDS_LAUNCHER_SUPERVISED', raising=False)
    monkeypatch.setattr(updater.threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(
        updater.subprocess, 'Popen',
        lambda command, **_kwargs: commands.append(command) or Helper())
    monkeypatch.setattr(updater.os, '_exit', lambda _code: None)

    updater.schedule_restart(delay=0, restart_nonce='a' * 32)

    helper_source = commands[0][2]
    compile(helper_source, '<restart-helper>', 'exec')
    assert 'LDS_RESTART_NONCE' in helper_source
    assert 'a' * 32 in helper_source
    assert 'source-launcher.py' in helper_source
    assert 'backend/run.py' not in helper_source


def test_supervised_restart_persists_restart_nonce(monkeypatch, tmp_path):
    exits = []

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setenv('LDS_LAUNCHER_SUPERVISED', '1')
    monkeypatch.setenv('LDS_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(updater.threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(updater.os, '_exit', lambda code: exits.append(code))

    updater.schedule_restart(delay=0, restart_nonce='a' * 32)

    payload = json.loads(
        (tmp_path / 'restart-request.json').read_text(encoding='utf-8'))
    assert payload['restart_nonce'] == 'a' * 32
    assert exits == [updater.RESTART_EXIT_CODE]


def test_apply_no_change(monkeypatch):
    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse':
            return _R('samesha\n')      # before == after
        return _R()
    _patch_git(monkeypatch, resp)
    r = updater.apply_update()
    assert r['ok'] is True and r['changed'] is False


def test_apply_changed_no_deps(monkeypatch):
    state = {'merged': False}

    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('bbbbbbb\n' if state['merged'] else 'aaaaaaa\n')
        if a[0] == 'rev-parse' and a[-1] == 'origin/main':
            return _R('bbbbbbb\n')
        if a[0] == 'merge':
            state['merged'] = True
            return _R('Updating aaaaaaa..bbbbbbb\n')
        if a[0] == 'diff':
            return _R('backend/app/services/foo.py\n')
        return _R()
    _patch_git(monkeypatch, resp)
    r = updater.apply_update()
    assert r['ok'] and r['changed'] is True and r['deps_changed'] is False
    assert len(r['restart_nonce']) == 32
    journal = json.loads(updater._journal_path(None).read_text(encoding='utf-8'))
    assert journal['state'] == 'awaiting_restart'
    assert journal['restart_nonce'] == r['restart_nonce']


def test_restart_readiness_ack_requires_exact_nonce_and_target(monkeypatch):
    path = updater._journal_path(None)
    path.write_text(json.dumps({
        'state': 'awaiting_restart',
        'restart_nonce': 'a' * 32,
        'target': 'bbbbbbb',
    }), encoding='utf-8')
    monkeypatch.setattr(
        updater, '_git', lambda *_args, **_kwargs: _R('bbbbbbb\n'))

    assert updater.acknowledge_restart_readiness('b' * 32) is False
    assert path.is_file()
    assert updater.acknowledge_restart_readiness('a' * 32) is True
    assert path.is_file()
    assert json.loads(path.read_text(encoding='utf-8'))['state'] == 'committed'
    assert updater.acknowledge_restart_readiness('a' * 32) is True


def test_stale_nonce_cannot_observe_committed_handoff(monkeypatch):
    path = updater._journal_path(None)
    path.write_text(json.dumps({
        'state': 'committed',
        'restart_nonce': 'a' * 32,
        'target': 'bbbbbbb',
    }), encoding='utf-8')
    monkeypatch.setattr(
        updater, '_git', lambda *_args, **_kwargs: _R('bbbbbbb\n'))
    assert updater.acknowledge_restart_readiness('b' * 32) is False
    assert updater.acknowledge_restart_readiness('a' * 32) is True
    assert path.is_file()


def test_manual_restart_without_update_journal_publishes_durable_receipt():
    path = updater._journal_path(None)

    assert updater.acknowledge_restart_readiness('c' * 32) is True
    receipt = path.with_name('restart-readiness.json')
    assert json.loads(receipt.read_text(encoding='utf-8'))['restart_nonce'] == 'c' * 32
    assert updater.acknowledge_restart_readiness('c' * 32) is True


def test_apply_reinstalls_when_requirements_change(monkeypatch):
    state = {'merged': False}

    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('bbbbbbb\n' if state['merged'] else 'aaaaaaa\n')
        if a[0] == 'rev-parse' and a[-1] == 'origin/main':
            return _R('bbbbbbb\n')
        if a[0] == 'merge':
            state['merged'] = True
            return _R('Updating\n')
        if a[0] == 'diff':
            return _R('backend/requirements.txt\nbackend/app/x.py\n')
        return _R()
    _patch_git(monkeypatch, resp)
    commands = []
    monkeypatch.setattr(updater, '_run_checked',
                        lambda command, **k: (commands.append(command) or True, ''))
    r = updater.apply_update()
    assert r['changed'] is True and r['deps_changed'] is True
    assert commands and 'pip' in ' '.join(commands[0])   # pip install was invoked


def test_apply_updates_installed_optional_group_only(monkeypatch, tmp_path):
    state = {'merged': False}
    backend = tmp_path / 'backend'
    backend.mkdir()
    (backend / 'requirements-ml.txt').write_text(
        'insightface==0.7.4\nonnxruntime==1.27.0\nrembg[cpu]==2.0.75\n'
        'torch==2.13.0\npillow==12.3.0\nnumpy==2.3.3\n'
        'opencv-python-headless==4.13.0.92\n', encoding='utf-8')

    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('bbbbbbb\n' if state['merged'] else 'aaaaaaa\n')
        if a[0] == 'rev-parse':
            return _R('bbbbbbb\n')
        if a[0] == 'diff':
            return _R('backend/requirements-ml.txt\n')
        if a[0] == 'merge':
            state['merged'] = True
            return _R('updated\n')
        return _R()

    _patch_git(monkeypatch, resp)
    monkeypatch.setattr(updater, '_ml_python_supported', lambda: True)
    monkeypatch.setattr(
        updater, '_pip_environment_snapshot',
        lambda: ({'freeze': ['insightface==0.7.3'],
                  'packages': {'insightface': '0.7.3', 'numpy': '1.26.4'}}, ''),
    )
    commands = []
    monkeypatch.setattr(updater, '_run_checked',
                        lambda command, **k: (commands.append(command) or True, ''))

    result = updater.apply_update(tmp_path)

    install = next(command for command in commands if 'install' in command)
    rendered = ' '.join(install)
    assert result['ok'] is True
    assert 'insightface==0.7.4' in rendered
    assert 'rembg' not in rendered and 'torch' not in rendered


def test_optional_ml_update_removes_legacy_lama_wrapper(monkeypatch, tmp_path):
    backend = tmp_path / 'backend'
    backend.mkdir()
    (backend / 'requirements-ml.txt').write_text(
        'torch==2.13.0\npillow==12.3.0\nnumpy==2.3.3\n'
        'opencv-python-headless==4.13.0.92\n', encoding='utf-8')
    snapshot = {
        'packages': {
            'simple-lama-inpainting': '0.1.2',
            'torch': '2.1.2',
        },
    }
    monkeypatch.setattr(updater, '_ml_python_supported', lambda: True)

    commands = updater._optional_python_install_commands(
        tmp_path, ['backend/requirements-ml.txt'], snapshot)

    assert commands[0][-3:] == ['uninstall', '-y', 'simple-lama-inpainting']
    assert 'torch==2.13.0' in commands[1]
    assert 'pillow==12.3.0' in commands[1]


def test_optional_ml_update_skips_unsupported_app_python(monkeypatch, tmp_path):
    backend = tmp_path / 'backend'
    backend.mkdir()
    (backend / 'requirements-ml.txt').write_text(
        'torch==2.13.0\nnumpy==2.3.3\n', encoding='utf-8')
    monkeypatch.setattr(updater, '_ml_python_supported', lambda: False)

    commands = updater._optional_python_install_commands(
        tmp_path, ['backend/requirements-ml.txt'],
        {'packages': {'torch': '2.1.2'}})

    assert commands == []


def test_apply_verifies_frontend_sources_against_committed_bundle(monkeypatch):
    state = {'merged': False}

    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('bbbbbbb\n' if state['merged'] else 'aaaaaaa\n')
        if a[0] == 'rev-parse':
            return _R('bbbbbbb\n')
        if a[0] == 'diff':
            return _R('frontend/src/App.jsx\nfrontend/dist/index.html\n')
        if a[0] == 'merge':
            state['merged'] = True
            return _R('updated\n')
        return _R()

    calls = []
    _patch_git(monkeypatch, resp)
    monkeypatch.setattr(updater, '_pnpm_command', lambda root: ['pnpm'])
    monkeypatch.setattr(
        updater, '_verify_frontend',
        lambda root, pnpm, logs: (calls.append((root, pnpm)) or True, ''),
    )

    result = updater.apply_update()

    assert result['ok'] is True
    assert result['frontend_sources_changed'] is True
    assert calls and calls[0][1] == ['pnpm']


def test_apply_verifies_dist_only_update(monkeypatch):
    state = {'merged': False}

    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('bbbbbbb\n' if state['merged'] else 'aaaaaaa\n')
        if a[0] == 'rev-parse':
            return _R('bbbbbbb\n')
        if a[0] == 'diff':
            return _R('frontend/dist/index.html\n')
        if a[0] == 'merge':
            state['merged'] = True
            return _R('updated\n')
        return _R()

    calls = []
    _patch_git(monkeypatch, resp)
    monkeypatch.setattr(
        updater, '_verify_frontend_bundle',
        lambda root: (calls.append(root) or True, ''),
    )

    result = updater.apply_update()

    assert result['ok'] is True
    assert result['frontend_sources_changed'] is False
    assert calls


def test_startup_smoke_failure_rolls_update_back(monkeypatch):
    state = {'merged': False}

    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('bbbbbbb\n' if state['merged'] else 'aaaaaaa\n')
        if a[0] == 'rev-parse':
            return _R('bbbbbbb\n')
        if a[0] == 'diff':
            return _R('backend/app/routes/broken.py\n')
        if a[0] == 'merge':
            state['merged'] = True
            return _R('updated\n')
        if a[0] == 'reset':
            state['merged'] = False
            return _R('restored\n')
        return _R()

    _patch_git(monkeypatch, resp)
    monkeypatch.setattr(
        updater, '_verify_app_startup',
        lambda *a, **k: (False, 'Updated application failed isolated startup verification.'),
    )

    result = updater.apply_update()

    assert result['ok'] is False and result['rolled_back'] is True
    assert state['merged'] is False
    assert 'startup' in result['reason'].lower()


def test_startup_verification_uses_safe_copy_of_current_database(
        monkeypatch, tmp_path):
    data = tmp_path / 'live-data'
    data.mkdir()
    database = data / 'studio.db'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE legacy_state (value TEXT)')
        connection.execute("INSERT INTO legacy_state VALUES ('preserved')")

    observed = {}

    def checked(_command, **kwargs):
        copied = __import__('pathlib').Path(kwargs['env']['LDS_DATA_DIR']) / 'studio.db'
        with sqlite3.connect(copied) as connection:
            observed['value'] = connection.execute(
                'SELECT value FROM legacy_state').fetchone()[0]
            connection.execute("UPDATE legacy_state SET value = 'migrated-copy'")
        return True, ''

    monkeypatch.setenv('LDS_DATA_DIR', str(data))
    monkeypatch.setattr(updater, '_run_checked', checked)
    logs = []
    assert _REAL_VERIFY_APP_STARTUP(tmp_path, logs) == (True, '')
    assert observed['value'] == 'preserved'
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT value FROM legacy_state').fetchone()[0] == 'preserved'


def test_apply_pull_failure_is_reported_not_raised(monkeypatch):
    calls = []
    def resp(a):
        calls.append(a)
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('aaaaaaa\n')
        if a[0] == 'rev-parse' and a[-1] == 'origin/main':
            return _R('bbbbbbb\n')
        if a[0] == 'merge':
            return _R('', 'error: Your local changes would be overwritten', rc=1)
        return _R()
    _patch_git(monkeypatch, resp)
    r = updater.apply_update()
    assert r['ok'] is False and r['rolled_back'] is True and 'log' in r
    assert ('reset', '--hard', 'aaaaaaa') in calls


def test_apply_refuses_dirty_checkout_before_fetch(monkeypatch):
    calls = []
    def resp(a):
        calls.append(a)
        if a[0] == 'status':
            return _R(' M backend/app/config.py\n')
        return _R()
    _patch_git(monkeypatch, resp)

    result = updater.apply_update()

    assert result['ok'] is False and result['dirty'] is True
    assert not any(call[0] == 'fetch' for call in calls)


def test_dependency_failure_rolls_code_back_and_prevents_restart(monkeypatch):
    state = {'merged': False}
    calls = []
    def resp(a):
        calls.append(a)
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('bbbbbbb\n' if state['merged'] else 'aaaaaaa\n')
        if a[0] == 'rev-parse':
            return _R('bbbbbbb\n')
        if a[0] == 'diff':
            return _R('backend/requirements.txt\n')
        if a[0] == 'merge':
            state['merged'] = True
            return _R('updated\n')
        if a[0] == 'reset':
            state['merged'] = False
            return _R('restored\n')
        return _R()
    _patch_git(monkeypatch, resp)
    monkeypatch.setattr(updater, '_run_checked',
                        lambda *a, **k: (False, 'resolver failed'))

    result = updater.apply_update()

    assert result['ok'] is False and result['rolled_back'] is True
    assert result['changed'] is False and state['merged'] is False
    assert ('reset', '--hard', 'aaaaaaa') in calls


def test_rollback_refuses_to_destroy_changes_created_during_update(monkeypatch):
    calls = []

    def resp(a):
        calls.append(a)
        if a[0] == 'status':
            # First status starts clean; the rollback check sees the new edit.
            return _R('' if len([c for c in calls if c[0] == 'status']) == 1
                      else ' M backend/app/config.py\n')
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('aaaaaaa\n')
        if a[0] == 'rev-parse':
            return _R('bbbbbbb\n')
        if a[0] == 'diff':
            return _R('backend/app/x.py\n')
        if a[0] == 'merge':
            return _R('', 'merge failed', rc=1)
        return _R()

    _patch_git(monkeypatch, resp)
    result = updater.apply_update()

    assert result['recovery_required'] is True
    assert result['rolled_back'] is False
    assert not any(call[0] == 'reset' for call in calls)


def test_failed_dependency_restore_keeps_recovery_journal(monkeypatch):
    state = {'merged': False, 'install_calls': 0}

    def resp(a):
        if a[:2] == ('rev-parse', '--abbrev-ref'):
            return _R('main\n')
        if a[0] == 'rev-parse' and a[-1] == 'HEAD':
            return _R('bbbbbbb\n' if state['merged'] else 'aaaaaaa\n')
        if a[0] == 'rev-parse':
            return _R('bbbbbbb\n')
        if a[0] == 'diff':
            return _R('backend/requirements.txt\n')
        if a[0] == 'merge':
            state['merged'] = True
            return _R('updated\n')
        if a[0] == 'reset':
            state['merged'] = False
            return _R('restored\n')
        return _R()

    def fail_installs(*_args, **_kwargs):
        state['install_calls'] += 1
        return False, 'resolver failed'

    _patch_git(monkeypatch, resp)
    monkeypatch.setattr(updater, '_run_checked', fail_installs)
    monkeypatch.setattr(
        updater, '_restore_python_environment',
        lambda *_args, **_kwargs: fail_installs()[0],
    )
    result = updater.apply_update()

    assert state['install_calls'] == 2  # update attempt plus old-env restore
    assert result['rolled_back'] is True
    assert result['environment_restored'] is False
    assert result['recovery_required'] is True
    assert updater._journal_path(None).is_file()
