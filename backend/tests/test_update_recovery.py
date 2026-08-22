import json
import hashlib
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

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


def _attach_database_snapshot(journal, database, snapshot):
    payload = json.loads(journal.read_text(encoding='utf-8'))
    payload['migration_database_snapshot'] = {
        'database': str(database.resolve()),
        'snapshot': str(snapshot.resolve()),
        'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        'size': snapshot.stat().st_size,
    }
    journal.write_text(json.dumps(payload), encoding='utf-8')


def test_recovery_bootstrap_restores_clean_interrupted_checkout(tmp_path):
    root, tracked, before, _after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)

    assert update_recovery.recover(root, data) is True

    assert _git(root, 'rev-parse', 'HEAD') == before
    assert tracked.read_text(encoding='utf-8') == 'before\n'
    assert not journal.exists()


def test_recovery_restores_pre_migration_database_before_finishing_rollback(tmp_path):
    root, _tracked, before, _after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    database = data / 'studio.db'
    snapshot = data / 'backups' / 'studio-pre-migration.db'
    snapshot.parent.mkdir()
    with closing(sqlite3.connect(snapshot)) as connection, connection:
        connection.execute(
            'CREATE TABLE schema_migration (version INTEGER PRIMARY KEY)')
        connection.execute('INSERT INTO schema_migration VALUES (1)')
        connection.execute('CREATE TABLE user_data (value TEXT)')
        connection.execute("INSERT INTO user_data VALUES ('before')")
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            'CREATE TABLE schema_migration (version INTEGER PRIMARY KEY)')
        connection.execute('INSERT INTO schema_migration VALUES (999)')
        connection.execute('CREATE TABLE user_data (value TEXT, newer TEXT)')
        connection.execute("INSERT INTO user_data VALUES ('after', 'new schema')")
    Path(f'{database}-wal').write_bytes(b'newer wal')
    Path(f'{database}-shm').write_bytes(b'newer shm')
    _attach_database_snapshot(journal, database, snapshot)

    assert update_recovery.recover(root, data) is True

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            'SELECT version FROM schema_migration').fetchall() == [(1,)]
        assert connection.execute('SELECT value FROM user_data').fetchone() == ('before',)
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    assert not snapshot.exists()
    assert not Path(f'{database}-wal').exists()
    assert not Path(f'{database}-shm').exists()
    assert not journal.exists()


def test_database_restore_failure_keeps_journal_snapshot_and_new_database(tmp_path):
    root, _tracked, before, _after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    database = data / 'studio.db'
    snapshot = data / 'studio-pre-migration.db'
    database.write_bytes(b'new database remains')
    snapshot.write_bytes(b'not sqlite')
    _attach_database_snapshot(journal, database, snapshot)
    before_database = database.read_bytes()

    with pytest.raises(update_recovery.RecoveryError, match='restore|integrity|verification'):
        update_recovery.recover(root, data)

    assert database.read_bytes() == before_database
    assert snapshot.exists()
    assert journal.exists()


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


def test_recovery_accepts_partial_checkout_materialized_by_updater(tmp_path):
    root, tracked, before, after = _repository(tmp_path)
    _git(root, 'reset', '--hard', before)
    tracked.write_text('after\n', encoding='utf-8')
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    payload = json.loads(journal.read_text(encoding='utf-8'))
    payload['target'] = after
    journal.write_text(json.dumps(payload), encoding='utf-8')

    assert update_recovery.recover(root, data) is True

    assert _git(root, 'rev-parse', 'HEAD') == before
    assert tracked.read_text(encoding='utf-8') == 'before\n'
    assert not journal.exists()


def test_committed_journal_is_retained_as_multi_observer_receipt(tmp_path):
    root, _tracked, before, _after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    payload = json.loads(journal.read_text(encoding='utf-8'))
    payload['state'] = 'committed'
    journal.write_text(json.dumps(payload), encoding='utf-8')
    assert update_recovery.recover(root, data) is False
    assert journal.exists()


def test_unacknowledged_restart_rolls_back_to_previous_revision(tmp_path):
    root, tracked, before, after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    payload = json.loads(journal.read_text(encoding='utf-8'))
    payload.update({
        'state': 'awaiting_restart',
        'target': after,
        'restart_nonce': 'a' * 32,
    })
    journal.write_text(json.dumps(payload), encoding='utf-8')

    assert update_recovery.recover(root, data) is True
    assert _git(root, 'rev-parse', 'HEAD') == before
    assert tracked.read_text(encoding='utf-8') == 'before\n'
    assert not journal.exists()


def test_exact_replacement_nonce_preserves_handoff_until_readiness(tmp_path):
    root, tracked, before, after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    payload = json.loads(journal.read_text(encoding='utf-8'))
    payload.update({
        'state': 'awaiting_restart',
        'target': after,
        'restart_nonce': 'a' * 32,
    })
    journal.write_text(json.dumps(payload), encoding='utf-8')

    assert update_recovery.recover(
        root, data, restart_nonce='a' * 32) is False
    assert _git(root, 'rev-parse', 'HEAD') == after
    assert tracked.read_text(encoding='utf-8') == 'after\n'
    assert journal.exists()


def test_wrong_replacement_nonce_rolls_back(tmp_path):
    root, _tracked, before, after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    payload = json.loads(journal.read_text(encoding='utf-8'))
    payload.update({
        'state': 'awaiting_restart',
        'target': after,
        'restart_nonce': 'a' * 32,
    })
    journal.write_text(json.dumps(payload), encoding='utf-8')

    assert update_recovery.recover(
        root, data, restart_nonce='b' * 32) is True
    assert _git(root, 'rev-parse', 'HEAD') == before


def test_recovery_refuses_staged_post_update_edit(tmp_path):
    root, tracked, before, after = _repository(tmp_path)
    data = tmp_path / 'data'
    journal = _journal(data, root, before)
    payload = json.loads(journal.read_text(encoding='utf-8'))
    payload['target'] = after
    journal.write_text(json.dumps(payload), encoding='utf-8')
    tracked.write_text('my staged edit\n', encoding='utf-8')
    _git(root, 'add', 'tracked.txt')
    tracked.write_text('after\n', encoding='utf-8')

    with pytest.raises(update_recovery.RecoveryError, match='protect local work'):
        update_recovery.recover(root, data)

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
