"""Durable lifecycle ledger for request-spawned background operations."""
from __future__ import annotations

import json
import threading
import uuid

from ..extensions import db
from ..models import BackgroundJob
from ..utils.time import utcnow

ACTIVE_STATES = ('pending', 'running')
TERMINAL_STATES = ('done', 'error', 'cancelled', 'interrupted')
_LOG_MAX = 400
_CREATE_LOCK = threading.Lock()


def _loads(value, fallback):
    try:
        parsed = json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback
    return parsed


def create(kind, dedupe_key, payload=None, *, resumable=False) -> BackgroundJob:
    """Create a running job, refusing a duplicate active key."""
    return create_or_get(kind, dedupe_key, payload, resumable=resumable)[0]


def create_or_get(kind, dedupe_key, payload=None, *, resumable=False) \
        -> tuple[BackgroundJob, bool]:
    """Return ``(job, created)`` so callers never launch a second worker for an
    already-active durable key."""
    normalized_kind = str(kind).strip()[:32]
    normalized_key = str(dedupe_key).strip()[:160]
    if not normalized_kind or not normalized_key:
        raise ValueError('background jobs require a kind and dedupe key')
    with _CREATE_LOCK:
        active = (BackgroundJob.query
                  .filter_by(kind=normalized_kind, dedupe_key=normalized_key)
                  .filter(BackgroundJob.state.in_(ACTIVE_STATES))
                  .order_by(BackgroundJob.created_at.desc()).first())
        if active is not None:
            return active, False
        now = utcnow()
        row = BackgroundJob(
            id=str(uuid.uuid4()), kind=normalized_kind, dedupe_key=normalized_key,
            state='running', payload=json.dumps(payload or {}, ensure_ascii=False),
            log='[]', resumable=bool(resumable), started_at=now,
            heartbeat_at=now, updated_at=now,
        )
        db.session.add(row)
        db.session.commit()
        return row, True


def latest(kind, dedupe_key) -> BackgroundJob | None:
    return (BackgroundJob.query
            .filter_by(kind=str(kind), dedupe_key=str(dedupe_key))
            .order_by(BackgroundJob.created_at.desc()).first())


def get(job_id) -> BackgroundJob | None:
    return db.session.get(BackgroundJob, str(job_id))


def touch(job_id, *, state=None, result=None, error=None, error_code=None,
          progress=None, log=None) -> BackgroundJob | None:
    row = get(job_id)
    if row is None:
        return None
    if row.state in TERMINAL_STATES:
        mutation = any(value is not None for value in (
            result, error, error_code, progress, log,
        ))
        # Permit only a genuinely idempotent observation. A late worker must
        # not rewrite the result/log after recovery or another worker has made
        # the job terminal.
        if mutation or (state is not None and state != row.state):
            raise RuntimeError(
                f'background job {row.id} is already terminal ({row.state})')
        return row
    now = utcnow()
    if state is not None:
        if state not in (*ACTIVE_STATES, *TERMINAL_STATES):
            raise ValueError(f'unknown background-job state: {state}')
        row.state = state
    if result is not None:
        row.result = json.dumps(result, ensure_ascii=False)
    if error is not None:
        row.error = str(error)[:4000]
    if error_code is not None:
        row.error_code = str(error_code)[:64]
    if progress is not None:
        row.progress = json.dumps(progress, ensure_ascii=False)
    if log is not None:
        lines = _loads(row.log, [])
        if not isinstance(lines, list):
            lines = []
        lines.append(str(log).rstrip('\n')[-4000:])
        row.log = json.dumps(lines[-_LOG_MAX:], ensure_ascii=False)
    row.heartbeat_at = now
    row.updated_at = now
    if row.state in TERMINAL_STATES:
        row.completed_at = row.completed_at or now
    db.session.commit()
    return row


def snapshot(row: BackgroundJob | None) -> dict:
    if row is None:
        return {'state': 'idle'}
    result = _loads(row.result, {})
    if not isinstance(result, dict):
        result = {}
    progress = _loads(row.progress, None)
    lines = _loads(row.log, [])
    if not isinstance(lines, list):
        lines = []
    return {
        **result,
        'job_id': row.id,
        'state': row.state,
        'kind': row.kind,
        'key': row.dedupe_key,
        'error': row.error,
        'error_code': row.error_code,
        'log': lines,
        'progress': progress,
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'started_at': row.started_at.isoformat() if row.started_at else None,
        'completed_at': row.completed_at.isoformat() if row.completed_at else None,
    }


def recover_interrupted() -> int:
    """Close request-spawned jobs whose daemon died with the old process.

    Retrying remote writes automatically can duplicate paid generations or
    publish a repository twice.  The durable terminal state therefore explains
    the interruption and lets the owning UI offer an explicit retry.
    """
    rows = BackgroundJob.query.filter(BackgroundJob.state.in_(ACTIVE_STATES)).all()
    for row in rows:
        row.state = 'interrupted'
        row.error_code = 'process_restarted'
        row.error = ('The app restarted while this operation was running. Its final '
                     'remote state is unknown; inspect the provider before retrying.')
        row.completed_at = utcnow()
        row.heartbeat_at = row.completed_at
        row.updated_at = row.completed_at
    if rows:
        db.session.commit()
    return len(rows)
