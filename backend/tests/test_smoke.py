import pytest


def test_health(client):
    assert client.get('/api/health').get_json() == {'ok': True}


def test_restart_probe_identifies_the_replacement_process(client, monkeypatch):
    monkeypatch.setenv('LDS_RESTART_NONCE', 'replacement-nonce')
    ready = client.get('/api/health/ready')
    assert ready.get_json()['restart_nonce'] == 'replacement-nonce'
    probe = client.get('/api/health/restart/replacement-nonce.gif')
    assert probe.status_code == 200
    assert probe.mimetype == 'image/gif'
    assert client.get('/api/health/restart/wrong.gif').status_code == 404


def test_liveness_and_readiness_are_distinct(client):
    live = client.get('/api/health/live')
    ready = client.get('/api/health/ready')
    assert live.status_code == 200 and live.get_json() == {'ok': True, 'status': 'live'}
    assert ready.status_code == 200
    body = ready.get_json()
    assert body['ok'] is True and body['status'] == 'ready'
    assert all(component['ok'] for component in body['components'].values())


def test_ready_process_acknowledges_exact_restart_handoff(client, monkeypatch):
    from app.services import updater
    acknowledgements = []
    monkeypatch.setenv('LDS_RESTART_NONCE', 'a' * 32)
    monkeypatch.setattr(
        updater, 'acknowledge_restart_readiness',
        lambda nonce: acknowledgements.append(nonce) or True)

    response = client.get('/api/health/ready')

    assert response.status_code == 200
    assert response.get_json()['restart_acknowledged'] is True
    assert response.get_json()['restart_nonce'] == 'a' * 32
    assert acknowledgements == ['a' * 32]


def test_multiple_ready_pollers_observe_same_restart_receipt(client, monkeypatch):
    from app.services import updater
    monkeypatch.setenv('LDS_RESTART_NONCE', 'a' * 32)
    monkeypatch.setattr(updater, 'acknowledge_restart_readiness', lambda nonce: True)

    first = client.get('/api/health/ready').get_json()
    second = client.get('/api/health/ready').get_json()

    assert first['restart_acknowledged'] is True
    assert second['restart_acknowledged'] is True
    assert first['restart_nonce'] == second['restart_nonce'] == 'a' * 32


def test_readiness_fails_when_frontend_build_is_missing(client, monkeypatch, tmp_path):
    import app as app_module
    monkeypatch.setattr(app_module, 'FRONTEND_DIST', tmp_path / 'missing-dist')
    response = client.get('/api/health/ready')
    assert response.status_code == 503
    assert response.get_json()['components']['frontend']['ok'] is False


def test_readiness_exercises_storage_write_access(client, monkeypatch):
    import app as app_module

    def fail_mkstemp(**_kwargs):
        raise OSError('read-only')

    monkeypatch.setattr(app_module.tempfile, 'mkstemp', fail_mkstemp)
    response = client.get('/api/health/ready')
    assert response.status_code == 503
    assert response.get_json()['components']['storage']['ok'] is False


def test_readiness_requires_the_exact_migration_ledger(client, app):
    from sqlalchemy import text
    from app.extensions import db

    with app.app_context():
        db.session.execute(text('DELETE FROM schema_migration WHERE version = 11'))
        db.session.execute(text(
            "INSERT INTO schema_migration(version, name, applied_at) "
            "VALUES (999, 'future or corrupt', '2026-01-01T00:00:00Z')"))
        db.session.commit()
    response = client.get('/api/health/ready')
    database = response.get_json()['components']['database']
    assert response.status_code == 503
    assert database['missing_migrations'] == [11]
    assert database['unexpected_migrations'] == [999]


def test_api_errors_have_request_id_and_structured_detail(client):
    request_id = 'client-request-1234'
    response = client.get('/api/does-not-exist', headers={'X-Request-ID': request_id})
    body = response.get_json()
    assert response.status_code == 404
    assert response.headers['X-Request-ID'] == request_id
    assert response.headers['Server-Timing'].startswith('app;dur=')
    assert body['ok'] is False
    assert body['error_code'] == 'http_404'
    assert body['request_id'] == request_id
    assert body['error_detail'] == {
        'code': 'http_404', 'message': body['error'], 'request_id': request_id,
    }


def test_api_http_errors_preserve_protocol_headers(client):
    response = client.post('/api/health')
    assert response.status_code == 405
    assert response.is_json
    assert {'GET', 'HEAD'}.issubset(set(response.headers['Allow'].split(', ')))


def test_readiness_requires_database_write_access(client, app):
    from sqlalchemy import text
    from app.extensions import db
    with app.app_context():
        db.session.execute(text('PRAGMA query_only=ON'))
    try:
        response = client.get('/api/health/ready')
        assert response.status_code == 503
        assert response.get_json()['components']['database']['ok'] is False
    finally:
        with app.app_context():
            db.session.rollback()
            db.session.execute(text('PRAGMA query_only=OFF'))


def test_startup_rejects_unknown_migration_before_mutation(tmp_path, monkeypatch):
    import sqlite3
    data_dir = tmp_path / 'future-data'
    data_dir.mkdir()
    database = data_dir / 'studio.db'
    with sqlite3.connect(database) as connection:
        connection.execute(
            'CREATE TABLE schema_migration ('
            'version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)')
        connection.execute(
            "INSERT INTO schema_migration VALUES (999, 'future', '2026-01-01')")
        connection.execute('CREATE TABLE future_marker (value TEXT)')
        connection.execute("INSERT INTO future_marker VALUES ('unchanged')")
    before = database.read_bytes()
    monkeypatch.setenv('LDS_DATA_DIR', str(data_dir))
    from app import create_app
    with pytest.raises(RuntimeError, match='unknown migration versions'):
        create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
    assert database.read_bytes() == before


def test_schema_migrations_are_versioned_and_current(app):
    from sqlalchemy import text
    from app.extensions import db
    from app import _MIGRATIONS
    with app.app_context():
        rows = db.session.execute(text(
            'SELECT version, name FROM schema_migration ORDER BY version')).all()
    assert [row[0] for row in rows] == [migration[0] for migration in _MIGRATIONS]
    assert all(row[1] for row in rows)


def test_existing_database_is_backed_up_before_create_all_mutates_schema(
        tmp_path, monkeypatch):
    import sqlite3
    data_dir = tmp_path / 'legacy-data'
    data_dir.mkdir()
    database = data_dir / 'studio.db'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE legacy_marker (value TEXT)')
        connection.execute("INSERT INTO legacy_marker VALUES ('before')")
    monkeypatch.setenv('LDS_DATA_DIR', str(data_dir))
    monkeypatch.setenv('LDS_CONFIG', str(tmp_path / 'legacy-config.json'))
    monkeypatch.setenv('LDS_ENV', str(tmp_path / 'legacy.env'))
    import app.config as config
    monkeypatch.setattr(config, 'ENV_PATH', tmp_path / 'legacy.env')
    monkeypatch.setattr(config, '_cache', None)
    from app import create_app

    application = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
    backups = list((data_dir / 'backups').glob('studio-pre-migration-*.db'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        marker = connection.execute('SELECT value FROM legacy_marker').fetchone()
    assert marker == ('before',)
    assert 'schema_migration' not in tables
    assert 'background_job' not in tables
    assert 'curation_event' not in tables
    with application.app_context():
        from app.extensions import db
        db.session.remove()
        db.engine.dispose()


def test_update_startup_records_real_migration_snapshot_and_recovery_reopens_it(
        tmp_path, monkeypatch):
    from contextlib import closing
    import json
    import sqlite3
    import subprocess
    from pathlib import Path
    import app as app_module
    import app.config as config
    import update_recovery

    root = tmp_path / 'checkout'
    root.mkdir()

    def git(*args):
        return subprocess.run(
            ['git', '-C', str(root), *args], check=True,
            capture_output=True, text=True).stdout.strip()

    git('init')
    git('config', 'user.email', 'tests@example.invalid')
    git('config', 'user.name', 'Tests')
    tracked = root / 'tracked.txt'
    tracked.write_text('before\n', encoding='utf-8')
    git('add', 'tracked.txt')
    git('commit', '-m', 'before')
    before = git('rev-parse', 'HEAD')
    tracked.write_text('after\n', encoding='utf-8')
    git('commit', '-am', 'after')
    target = git('rev-parse', 'HEAD')

    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    database = data_dir / 'studio.db'
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('CREATE TABLE legacy_marker (value TEXT)')
        connection.execute("INSERT INTO legacy_marker VALUES ('before migration')")
    journal = data_dir / 'update-transaction.json'
    journal.write_text(json.dumps({
        'version': 2,
        'state': 'awaiting_restart',
        'root': str(root.resolve()),
        'before': before,
        'target': target,
        'restart_nonce': 'a' * 32,
        'changed_files': ['tracked.txt'],
    }), encoding='utf-8')
    monkeypatch.setenv('LDS_DATA_DIR', str(data_dir))
    monkeypatch.setenv('LDS_CONFIG', str(tmp_path / 'config.json'))
    monkeypatch.setenv('LDS_ENV', str(tmp_path / '.env'))
    monkeypatch.setattr(config, 'ENV_PATH', tmp_path / '.env')
    monkeypatch.setattr(config, '_cache', None)
    monkeypatch.setattr(config, 'REPO_ROOT', root)

    migrated = app_module.create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
    with migrated.app_context():
        app_module.db.session.remove()
        app_module.db.engine.dispose()

    recorded = json.loads(journal.read_text(encoding='utf-8'))
    metadata = recorded['migration_database_snapshot']
    snapshot = Path(metadata['snapshot'])
    assert snapshot.is_file()
    assert Path(metadata['database']) == database.resolve()
    with closing(sqlite3.connect(snapshot)) as connection:
        assert connection.execute(
            'SELECT value FROM legacy_marker').fetchone() == ('before migration',)
        assert 'schema_migration' not in {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}

    assert update_recovery.recover(root, data_dir) is True
    assert not journal.exists() and not snapshot.exists()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            'SELECT value FROM legacy_marker').fetchone() == ('before migration',)
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)

    reopened = app_module.create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
    with reopened.app_context():
        assert app_module.db.session.execute(
            app_module.text('SELECT value FROM legacy_marker')).scalar_one() \
            == 'before migration'
        app_module.db.session.remove()
        app_module.db.engine.dispose()


def test_failed_backup_publication_leaves_no_final_or_temporary_file(
        tmp_path, monkeypatch):
    from pathlib import Path
    import app as app_module
    import app.config as config

    data_dir = tmp_path / 'data'
    monkeypatch.setenv('LDS_DATA_DIR', str(data_dir))
    monkeypatch.setattr(config, 'ENV_PATH', tmp_path / '.env')
    monkeypatch.setattr(config, '_cache', None)
    application = app_module.create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
    backup_dir = data_dir / 'backups'
    published_before = set(backup_dir.glob('studio-pre-migration-*.db'))
    stale = backup_dir / '.studio-pre-migration-old.db.abandoned.incomplete'
    stale.write_bytes(b'partial')

    original_replace = Path.replace

    def fail_publication(path, target):
        if str(path).endswith('.incomplete'):
            raise OSError('simulated publication failure')
        return original_replace(path, target)

    monkeypatch.setattr(Path, 'replace', fail_publication)
    with application.app_context(), pytest.raises(OSError, match='publication failure'):
        app_module._backup_database_before_migration()

    assert set(backup_dir.glob('studio-pre-migration-*.db')) == published_before
    assert not list(backup_dir.glob('*.incomplete'))
    assert not stale.exists()
    with application.app_context():
        app_module.db.session.remove()
        app_module.db.engine.dispose()


def test_migration_backup_retention_keeps_newest_five(tmp_path):
    import app as app_module

    database = tmp_path / 'studio.db'
    backups = tmp_path / 'backups'
    backups.mkdir()
    for index in range(7):
        (backups / f'studio-pre-migration-2026010{index}-000000.db').write_bytes(
            str(index).encode())

    app_module._prune_migration_backups(database)

    remaining = sorted(backups.glob('studio-pre-migration-*.db'))
    assert len(remaining) == 5
    assert remaining[0].name.endswith('20260102-000000.db')


def test_file_logging_replaces_and_closes_prior_factory_handler(tmp_path):
    import logging
    import app as app_module

    root = logging.getLogger()
    first_path = tmp_path / 'first.log'
    second_path = tmp_path / 'second.log'
    app_module._configure_file_logging(first_path)
    first = next(handler for handler in root.handlers
                 if getattr(handler, '_prep_my_avatar_factory_handler', False))
    try:
        app_module._configure_file_logging(second_path)
        owned = [handler for handler in root.handlers
                 if getattr(handler, '_prep_my_avatar_factory_handler', False)]
        assert len(owned) == 1
        assert owned[0].baseFilename == str(second_path.resolve())
        assert first.stream is None
    finally:
        for handler in list(root.handlers):
            if getattr(handler, '_prep_my_avatar_factory_handler', False):
                root.removeHandler(handler)
                handler.close()


def test_upgraded_schema_has_coverage_policy_guards(app):
    from sqlalchemy import text
    from app.extensions import db
    with app.app_context():
        triggers = {row[0] for row in db.session.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )).all()}
    assert {
        'trg_face_dataset_coverage_integrity_insert',
        'trg_face_dataset_coverage_integrity_update',
    }.issubset(triggers)


@pytest.mark.parametrize(
    ('epoch', 'objects'),
    [
        (6, ('trg_face_dataset_integrity_insert',
             'trg_face_dataset_image_integrity_insert')),
        (8, ('trg_dataset_revision_image_insert',
             'trg_dataset_revision_image_update',
             'trg_dataset_revision_image_delete')),
        (11, ('ix_lora_test_image_training_run_record_id',)),
        (12, ('trg_face_dataset_coverage_integrity_insert',
              'trg_face_dataset_coverage_integrity_update')),
    ],
)
def test_historical_epoch_upgrade_restores_constraint_parity(app, epoch, objects):
    """Exercise the distinct deployed epochs called out by the review.

    Each fixture removes the migration ledger tail and the concrete schema
    objects introduced at that epoch.  Reapplying migrations must reconstruct
    the object set and reject the same invalid writes as a fresh database.
    """
    from sqlalchemy import text
    import app as app_module
    from app.extensions import db

    with app.app_context():
        for name in objects:
            kind = 'INDEX' if name.startswith('ix_') else 'TRIGGER'
            db.session.execute(text(f'DROP {kind} IF EXISTS {name}'))
        db.session.execute(
            text('DELETE FROM schema_migration WHERE version >= :epoch'),
            {'epoch': epoch},
        )
        db.session.commit()

        app_module._apply_schema_migrations()

        catalog = {row[0] for row in db.session.execute(text(
            "SELECT name FROM sqlite_master WHERE type IN ('trigger', 'index')"
        )).all()}
        assert set(objects).issubset(catalog)
        versions = {row[0] for row in db.session.execute(
            text('SELECT version FROM schema_migration')).all()}
        assert versions == {migration[0] for migration in app_module._MIGRATIONS}

        if epoch <= 6:
            with pytest.raises(Exception, match='integrity constraint failed'):
                db.session.execute(text(
                    "INSERT INTO face_dataset "
                    "(user_id, name, trigger_word, kind, created_at, updated_at) "
                    "VALUES ('local', 'bad', 'bad', 'not-a-kind', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ))
                db.session.commit()
            db.session.rollback()


def _rebuild_as_historical_table(db, table, *, epoch, omitted=()):
    """Remove additive columns while preserving the table's historical DDL.

    ``CREATE TABLE AS`` is not a migration fixture: it silently discards every
    default, NOT NULL, CHECK and foreign-key clause. SQLite's DROP COLUMN keeps
    the unaffected historical definition, which makes parity failures useful.
    """
    from sqlalchemy import text

    triggers = [row[0] for row in db.session.execute(text(
        "SELECT name FROM sqlite_master WHERE type = 'trigger'"
    )).all()]
    for trigger in triggers:
        introduced_at_or_after_epoch = (
            epoch <= 6
            or (epoch <= 8 and trigger.startswith('trg_dataset_revision_'))
            or (epoch <= 12 and trigger.startswith(
                'trg_face_dataset_coverage_integrity_'))
            or (epoch <= 16 and trigger in {
                'trg_lora_test_training_run_insert',
                'trg_lora_test_training_run_update',
                'trg_training_run_evidence_set_null',
            })
        )
        if introduced_at_or_after_epoch:
            db.session.execute(text(f'DROP TRIGGER "{trigger}"'))
    stripped_constraints = set()
    if epoch == 6 and table == 'face_dataset_image':
        stripped_constraints = {
            'ck_face_dataset_image_status', 'ck_face_dataset_image_source',
            'ck_face_dataset_image_usefulness',
            'ck_face_dataset_image_coverage_value',
            'ck_face_dataset_image_anchor', 'ck_face_dataset_image_framing',
            'ck_face_dataset_image_watermark',
        }
    elif epoch == 12 and table == 'face_dataset':
        stripped_constraints = {'ck_face_dataset_coverage_profile'}

    if omitted or stripped_constraints:
        retained_triggers = db.session.execute(text(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='trigger' AND sql IS NOT NULL"
        )).all()
        for name, _sql in retained_triggers:
            db.session.execute(text(f'DROP TRIGGER "{name}"'))
        ddl = db.session.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=:table"),
            {'table': table},
        ).scalar_one()
        removed = set(omitted) | stripped_constraints
        lines = [line for line in ddl.splitlines()
                 if not any(name in line for name in removed)]
        lines[-2] = lines[-2].rstrip().rstrip(',')
        historical_ddl = '\n'.join(lines).replace(
            f'CREATE TABLE {table}', f'CREATE TABLE {table}_historical', 1)
        columns = [row[1] for row in db.session.execute(text(
            f'PRAGMA table_info({table})')).all() if row[1] not in omitted]
        selected = ', '.join(f'"{name}"' for name in columns)
        db.session.execute(text(historical_ddl))
        db.session.execute(text(
            f'INSERT INTO "{table}_historical" ({selected}) '
            f'SELECT {selected} FROM "{table}"'))
        db.session.execute(text(f'DROP TABLE "{table}"'))
        db.session.execute(text(
            f'ALTER TABLE "{table}_historical" RENAME TO "{table}"'))
        for _name, trigger_sql in retained_triggers:
            db.session.execute(text(trigger_sql))


def _schema_behavior_matrix(db):
    """Return behavioral schema evidence, not catalog-name approximations."""
    from sqlalchemy import text

    def accepts(statement, *, seed_dataset=False):
        db.session.execute(text('SAVEPOINT schema_matrix'))
        try:
            if seed_dataset:
                db.session.execute(text(valid_dataset))
            db.session.execute(text(statement))
            accepted = True
        except Exception:
            accepted = False
        finally:
            db.session.execute(text('ROLLBACK TO schema_matrix'))
            db.session.execute(text('RELEASE schema_matrix'))
        return accepted

    columns = {}
    for table in ('face_dataset', 'face_dataset_image', 'lora_test_image'):
        columns[table] = {
            row[1]: (str(row[4]).strip("'\"") if row[4] is not None else None)
            for row in db.session.execute(text(f'PRAGMA table_info({table})')).all()
        }
    valid_dataset = (
        "INSERT INTO face_dataset "
        "(id, user_id, name, trigger_word, kind, coverage_profile, created_at, updated_at) "
        "VALUES (9100, 'local', 'valid', 'valid', 'character', 'balanced', "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    matrix = {
        'additive_columns': {
            'revision': columns['face_dataset'].get('revision'),
            'coverage_profile': columns['face_dataset'].get('coverage_profile'),
            'training_run_record_id': columns['lora_test_image'].get(
                'training_run_record_id'),
        },
        'valid_dataset': accepts(valid_dataset),
        'invalid_kind': accepts(valid_dataset.replace("'character'", "'bogus'")),
        'invalid_coverage': accepts(valid_dataset.replace("'balanced'", "'bogus'")),
        'valid_image': accepts(
            "INSERT INTO face_dataset_image "
            "(id, dataset_id, status, source) VALUES (9200, 9100, 'keep', 'upload')",
            seed_dataset=True),
        'invalid_image_status': accepts(
            "INSERT INTO face_dataset_image "
            "(id, dataset_id, status, source) VALUES (9200, 9100, 'bogus', 'upload')",
            seed_dataset=True),
        'valid_test_image': accepts(
            "INSERT INTO lora_test_image "
            "(id, dataset_id, checkpoint, strength, rating, status) "
            "VALUES (9300, 9100, 'fixture.safetensors', 1.0, 0, 'done')",
            seed_dataset=True),
        'invalid_test_rating': accepts(
            "INSERT INTO lora_test_image "
            "(id, dataset_id, checkpoint, strength, rating, status) "
            "VALUES (9300, 9100, 'fixture.safetensors', 1.0, 9, 'done')",
            seed_dataset=True),
    }
    return matrix


@pytest.mark.parametrize(('epoch', 'table', 'omitted', 'expected_column'), [
    (6, 'face_dataset_image',
     ('coverage_provenance', 'source_rights', 'caption_provenance'),
     'caption_provenance'),
    (8, 'face_dataset', ('revision',), 'revision'),
    (11, 'lora_test_image', ('training_run_record_id',),
     'training_run_record_id'),
    (12, 'face_dataset', (), None),
])
def test_real_historical_managed_table_fixtures_upgrade(
        app, epoch, table, omitted, expected_column):
    """Each real boundary shape must behave exactly like a fresh database."""
    from sqlalchemy import text
    import app as app_module
    from app.extensions import db

    with app.app_context():
        fresh_matrix = _schema_behavior_matrix(db)
        db.session.commit()
        db.session.execute(text('PRAGMA foreign_keys=OFF'))
        _rebuild_as_historical_table(db, table, epoch=epoch, omitted=omitted)
        historical_ddl = db.session.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=:table"),
            {'table': table},
        ).scalar_one()
        if epoch == 6:
            assert 'ck_face_dataset_image_status' not in historical_ddl
        if epoch == 12:
            assert 'ck_face_dataset_coverage_profile' not in historical_ddl
            assert _schema_behavior_matrix(db)['invalid_coverage'] is True
        db.session.execute(
            text('DELETE FROM schema_migration WHERE version >= :epoch'),
            {'epoch': epoch},
        )
        db.session.commit()
        app_module._apply_schema_migrations()

        columns = {row[1] for row in db.session.execute(
            text(f'PRAGMA table_info({table})')).all()}
        if expected_column:
            assert expected_column in columns
        versions = set(db.session.execute(
            text('SELECT version FROM schema_migration')).scalars())
        assert versions == {version for version, _, _ in app_module._MIGRATIONS}
        upgraded_matrix = _schema_behavior_matrix(db)
        assert upgraded_matrix == fresh_matrix
        assert upgraded_matrix['valid_dataset'] is True
        assert upgraded_matrix['valid_image'] is True
        assert upgraded_matrix['valid_test_image'] is True
        assert upgraded_matrix['invalid_kind'] is False
        assert upgraded_matrix['invalid_coverage'] is False
        assert upgraded_matrix['invalid_image_status'] is False
        assert upgraded_matrix['invalid_test_rating'] is False


def test_caption_origin_migration_preserves_legacy_caption_and_is_retry_safe(app):
    from sqlalchemy import text
    import app as app_module
    from app.extensions import db

    with app.app_context():
        db.session.execute(text(
            "INSERT INTO face_dataset "
            "(id, user_id, name, trigger_word, kind, coverage_profile, created_at, updated_at) "
            "VALUES (9400, 'local', 'legacy', 'person', 'character', 'balanced', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        db.session.execute(text(
            "INSERT INTO face_dataset_image "
            "(id, dataset_id, status, source, caption, caption_provenance) "
            "VALUES (9401, 9400, 'keep', 'upload', :caption, :provenance)"
        ), {"caption": "  Legacy caption, byte-for-byte.  ", "provenance": '{"model":"old"}'})
        db.session.commit()

        _rebuild_as_historical_table(
            db,
            "face_dataset_image",
            epoch=17,
            omitted=("caption_origin",),
        )
        db.session.execute(text("DELETE FROM schema_migration WHERE version >= 18"))
        db.session.commit()

        app_module._apply_schema_migrations()
        columns = {
            row[1]: row
            for row in db.session.execute(text("PRAGMA table_info(face_dataset_image)"))
        }
        caption, origin, provenance = db.session.execute(text(
            "SELECT caption, caption_origin, caption_provenance "
            "FROM face_dataset_image WHERE id = 9401"
        )).one()
        assert columns["caption_origin"][2].upper() == "VARCHAR(16)"
        assert columns["caption_origin"][3] == 0
        assert (caption, origin, provenance) == (
            "  Legacy caption, byte-for-byte.  ",
            None,
            '{"model":"old"}',
        )
        assert db.session.execute(text(
            "SELECT name FROM schema_migration WHERE version = 18"
        )).scalar_one() == "caption authorship"

        db.session.execute(text("DELETE FROM schema_migration WHERE version = 18"))
        db.session.commit()
        app_module._apply_schema_migrations()
        assert db.session.execute(text(
            "SELECT COUNT(*) FROM schema_migration WHERE version = 18"
        )).scalar_one() == 1


def test_failed_migration_transaction_can_be_retried(app, monkeypatch):
    from sqlalchemy import text
    import app as app_module
    from app.extensions import db

    with app.app_context():
        final_version = app_module._MIGRATIONS[-1][0]
        db.session.execute(
            text('DELETE FROM schema_migration WHERE version = :version'),
            {'version': final_version},
        )
        db.session.commit()
        original_execute = db.session.execute
        failed = False

        def fail_ledger_once(statement, *args, **kwargs):
            nonlocal failed
            if not failed and 'INSERT INTO schema_migration' in str(statement):
                failed = True
                raise RuntimeError('simulated migration crash')
            return original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db.session, 'execute', fail_ledger_once)
        with pytest.raises(RuntimeError, match='database migration'):
            app_module._apply_schema_migrations()
        assert original_execute(
            text('SELECT COUNT(*) FROM schema_migration WHERE version = :version'),
            {'version': final_version},
        ).scalar_one() == 0

        monkeypatch.setattr(db.session, 'execute', original_execute)
        app_module._apply_schema_migrations()
        assert original_execute(
            text('SELECT COUNT(*) FROM schema_migration WHERE version = :version'),
            {'version': final_version},
        ).scalar_one() == 1


def test_upgraded_studio_provenance_enforces_fk_domain_and_set_null(app):
    """Migration 16 supplies SQLite parity for pre-v11 additive schemas."""
    from sqlalchemy import text
    import app as app_module
    from app.extensions import db

    with app.app_context():
        for trigger in (
                'trg_lora_test_training_run_insert',
                'trg_lora_test_training_run_update',
                'trg_training_run_evidence_set_null'):
            db.session.execute(text(f'DROP TRIGGER IF EXISTS {trigger}'))
        db.session.execute(text('DELETE FROM schema_migration WHERE version = 16'))
        db.session.commit()
        app_module._apply_schema_migrations()

        db.session.execute(text(
            "INSERT INTO face_dataset (id, user_id, name, trigger_word, revision) "
            "VALUES (9001, 'local', 'legacy', 'legacy', 0)"))
        db.session.execute(text(
            "INSERT INTO training_run_record "
            "(id, dataset_id, family, source, fingerprint, version) "
            "VALUES (7001, 9001, 'zimage', 'legacy', 'legacy', 1)"))
        db.session.execute(text(
            "INSERT INTO lora_test_image "
            "(id, dataset_id, checkpoint, strength, rating, status, "
            "training_run_record_id) VALUES "
            "(8001, 9001, 'legacy.safetensors', 1.0, 0, 'done', 7001)"))
        db.session.commit()

        with pytest.raises(Exception, match='invalid training run provenance'):
            db.session.execute(text(
                "INSERT INTO lora_test_image "
                "(dataset_id, checkpoint, strength, rating, status, "
                "training_run_record_id) VALUES "
                "(9001, 'missing.safetensors', 1.0, 0, 'done', -1)"))
            db.session.commit()
        db.session.rollback()

        db.session.execute(text('DELETE FROM training_run_record WHERE id = 7001'))
        db.session.commit()
        assert db.session.execute(text(
            'SELECT training_run_record_id FROM lora_test_image WHERE id = 8001'
        )).scalar_one() is None


def test_runtime_data_directory_and_database_are_private(app):
    import os
    from pathlib import Path
    from app import config as cfg
    from app.extensions import db
    if os.name == 'nt':
        return
    with app.app_context():
        assert cfg._data_dir().stat().st_mode & 0o777 == 0o700
        if db.engine.url.database != ':memory:':
            database = Path(db.engine.url.database)
            assert database.stat().st_mode & 0o777 == 0o600
