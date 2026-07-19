"""Small dependency-free backend regression gate for in-app updates.

The full pytest matrix remains a release/CI gate. This suite exercises critical
runtime contracts using only production dependencies, so source checkouts that
do not install pytest still reject a broken update before restart.
"""
from __future__ import annotations

from sqlalchemy import text


def run(application) -> None:
    from . import _MIGRATIONS
    from .extensions import db

    client = application.test_client()
    live = client.get('/api/health/live')
    ready = client.get('/api/health/ready')
    if live.status_code != 200 or live.get_json() != {'ok': True, 'status': 'live'}:
        raise RuntimeError('liveness contract failed')
    ready_body = ready.get_json(silent=True) or {}
    if (ready.status_code != 200 or ready_body.get('status') != 'ready'
            or not all(component.get('ok')
                       for component in (ready_body.get('components') or {}).values())):
        raise RuntimeError('readiness contract failed')
    missing = client.get('/api/update-selftest-not-found',
                         headers={'X-Request-ID': 'update-selftest-request'})
    missing_body = missing.get_json(silent=True) or {}
    if (missing.status_code != 404
            or missing_body.get('error_code') != 'http_404'
            or missing_body.get('request_id') != 'update-selftest-request'):
        raise RuntimeError('structured API error contract failed')
    with application.app_context():
        migrations = db.session.execute(text(
            'SELECT version FROM schema_migration ORDER BY version')).scalars().all()
        if migrations != [migration[0] for migration in _MIGRATIONS]:
            raise RuntimeError('schema migration ledger is incomplete')
        triggers = set(db.session.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )).scalars())
        required = {
            'trg_face_dataset_coverage_integrity_insert',
            'trg_face_dataset_coverage_integrity_update',
        }
        if not required.issubset(triggers):
            raise RuntimeError('coverage-integrity database guards are missing')
