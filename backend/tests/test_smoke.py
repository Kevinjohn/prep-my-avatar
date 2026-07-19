def test_health(client):
    assert client.get('/api/health').get_json() == {'ok': True}


def test_liveness_and_readiness_are_distinct(client):
    live = client.get('/api/health/live')
    ready = client.get('/api/health/ready')
    assert live.status_code == 200 and live.get_json() == {'ok': True, 'status': 'live'}
    assert ready.status_code == 200
    body = ready.get_json()
    assert body['ok'] is True and body['status'] == 'ready'
    assert all(component['ok'] for component in body['components'].values())


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
