import json
import subprocess

import pytest

import update_recovery


def _git(root, *args):
    return subprocess.run(
        ['git', '-C', str(root), *args], check=True,
        capture_output=True, text=True).stdout.strip()


def _repository(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init')
    _git(root, 'config', 'user.email', 'tests@example.invalid')
    _git(root, 'config', 'user.name', 'Tests')
    tracked = root / 'tracked.txt'
    tracked.write_text('before\n', encoding='utf-8')
    _git(root, 'add', 'tracked.txt')
    _git(root, 'commit', '-m', 'before')
    before = _git(root, 'rev-parse', 'HEAD')
    tracked.write_text('after\n', encoding='utf-8')
    _git(root, 'commit', '-am', 'after')
    after = _git(root, 'rev-parse', 'HEAD')
    return root, tracked, before, after


def _journal(data, root, before):
    data.mkdir()
    path = data / 'update-transaction.json'
    path.write_text(json.dumps({
        'version': 2,
        'root': str(root.resolve()),
        'before': before,
        'state': 'merged',
        'changed_files': ['tracked.txt'],
    }), encoding='utf-8')
    return path


def test_recovery_bootstrap_restores_clean_interrupted_checkout(tmp_path):
    root, tracked, before, _after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)

    assert update_recovery.recover(root, data) is True

    assert _git(root, 'rev-parse', 'HEAD') == before
    assert tracked.read_text(encoding='utf-8') == 'before\n'
    assert not journal.exists()


def test_recovery_bootstrap_refuses_to_destroy_new_local_work(tmp_path):
    root, tracked, before, after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    tracked.write_text('my local edit\n', encoding='utf-8')

    with pytest.raises(update_recovery.RecoveryError, match='protect local work'):
        update_recovery.recover(root, data)

    assert _git(root, 'rev-parse', 'HEAD') == after
    assert tracked.read_text(encoding='utf-8') == 'my local edit\n'
    assert journal.exists()


def test_exact_environment_restore_removes_resolver_added_packages(
        tmp_path, monkeypatch):
    calls = []
    inventories = iter((
        {'flask': '3.1.3', 'resolver-extra': '1.0'},
        {'flask': '3.1.3'},
    ))

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(update_recovery, '_run', run)
    monkeypatch.setattr(
        update_recovery, '_installed_packages',
        lambda *_args, **_kwargs: next(inventories))

    update_recovery._restore_python(
        tmp_path, 'python', {
            'freeze': ['Flask==3.1.3'],
            'packages': {'flask': '3.1.3'},
        })

    assert any(command[:5] == [
        'python', '-m', 'pip', 'uninstall', '-y']
        and command[5:] == ['resolver-extra'] for command in calls)
