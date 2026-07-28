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


def _identity(kind, dedupe_key) -> tuple[str, str]:
    """Validate an identity exactly as it is persisted.

    Silently truncating these values aliases otherwise distinct operations and
    also makes a subsequent ``latest`` lookup with the original key fail.
    """
    normalized_kind = str(kind).strip()
    normalized_key = str(dedupe_key).strip()
    if not normalized_kind or not normalized_key:
        raise ValueError('background jobs require a kind and dedupe key')
    if len(normalized_kind) > 32:
        raise ValueError('background-job kind must be at most 32 characters')
    if len(normalized_key) > 160:
        raise ValueError('background-job dedupe key must be at most 160 characters')
    return normalized_kind, normalized_key


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
    normalized_kind, normalized_key = _identity(kind, dedupe_key)
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
    normalized_kind, normalized_key = _identity(kind, dedupe_key)
    return (BackgroundJob.query
            .filter_by(kind=normalized_kind, dedupe_key=normalized_key)
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
    values = {'heartbeat_at': now, 'updated_at': now}
    if state is not None:
        if state not in (*ACTIVE_STATES, *TERMINAL_STATES):
            raise ValueError(f'unknown background-job state: {state}')
        values['state'] = state
    if result is not None:
        values['result'] = json.dumps(result, ensure_ascii=False)
    if error is not None:
        values['error'] = str(error)[:4000]
    if error_code is not None:
        values['error_code'] = str(error_code)[:64]
    if progress is not None:
        values['progress'] = json.dumps(progress, ensure_ascii=False)
    if log is not None:
        lines = _loads(row.log, [])
        if not isinstance(lines, list):
            lines = []
        lines.append(str(log).rstrip('\n')[-4000:])
        values['log'] = json.dumps(lines[-_LOG_MAX:], ensure_ascii=False)
    if state in TERMINAL_STATES:
        values['completed_at'] = now

    # The state predicate is the database-level terminal immutability guard.
    # A session-local check alone can race another worker that commits after
    # this row was loaded.
    updated = (db.session.query(BackgroundJob)
               .filter(BackgroundJob.id == row.id)
               .filter(BackgroundJob.state.in_(ACTIVE_STATES))
               .update(values, synchronize_session=False))
    if updated != 1:
        db.session.rollback()
        current = get(job_id)
        if current is None:
            return None
        raise RuntimeError(
            f'background job {current.id} is already terminal ({current.state})')
    db.session.commit()
    return get(job_id)


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
        'resumable': bool(row.resumable),
        'attempts': row.attempts,
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'started_at': row.started_at.isoformat() if row.started_at else None,
        'completed_at': row.completed_at.isoformat() if row.completed_at else None,
    }


def recover_interrupted() -> int:
    """Close request-spawned jobs whose daemon died with the old process.

    ``resumable`` records are exposed to callers as retry-eligible metadata,
    but are still interrupted: this generic ledger has no operation-specific
    replay callback and must not imply that replay occurred. Retrying remote
    writes automatically can duplicate paid generations or
    publish a repository twice.  The durable terminal state therefore explains
    the interruption and lets the owning UI offer an explicit retry.
    """
    now = utcnow()
    updated = (db.session.query(BackgroundJob)
               .filter(BackgroundJob.state.in_(ACTIVE_STATES))
               .update({
                   'state': 'interrupted',
                   'error_code': 'process_restarted',
                   'error': ('The app restarted while this operation was running. '
                             'Its final remote state is unknown; inspect the '
                             'provider before retrying.'),
                   'completed_at': now,
                   'heartbeat_at': now,
                   'updated_at': now,
               }, synchronize_session=False))
    if updated:
        db.session.commit()
    return updated
