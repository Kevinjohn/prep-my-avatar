"""Append-only curation history and transaction-safe undo."""
from __future__ import annotations

import json
import threading
import uuid
from functools import wraps

from ..extensions import db
from ..models import CurationEvent, FaceDataset, FaceDatasetImage
from ..utils.time import utcnow
from .caption_origin import CAPTION_FIELDS, set_caption

_UNDO_FIELDS = {
    'status', *CAPTION_FIELDS, 'anchor_decision', 'coverage_json', 'framing',
    'coverage_value', 'coverage_provenance', 'variation_label', 'source_rights',
    'watermark_state', 'watermark_bbox', 'watermark_regions',
}
_CURATION_TRANSACTION_LOCK = threading.RLock()


def serialized(function):
    """Serialize curation snapshots, mutations, history rows, and undo.

    The application runs one local server process but serves concurrent request
    threads.  Entry points acquire this lock before loading ORM state, ensuring
    each event's ``before`` snapshot observes the preceding committed edit.
    """
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _CURATION_TRANSACTION_LOCK:
            return function(*args, **kwargs)
    return wrapped


def new_batch_id() -> str:
    return str(uuid.uuid4())


def snapshot(image: FaceDatasetImage, fields) -> dict:
    return {field: getattr(image, field) for field in fields if field in _UNDO_FIELDS}


def record(user_id, image: FaceDatasetImage, action: str, before: dict, after: dict,
           *, batch_id: str | None = None) -> CurationEvent | None:
    """Stage one history row in the caller's current transaction."""
    before = {k: v for k, v in before.items() if k in _UNDO_FIELDS}
    after = {k: v for k, v in after.items() if k in _UNDO_FIELDS}
    changed = {key for key in before | after if before.get(key) != after.get(key)}
    if changed.intersection(CAPTION_FIELDS):
        changed.update(key for key in CAPTION_FIELDS if key in before or key in after)
    if not changed:
        return None
    before = {key: before.get(key) for key in sorted(changed)}
    after = {key: after.get(key) for key in sorted(changed)}
    event = CurationEvent(
        dataset_id=image.dataset_id, image_id=image.id,
        batch_id=batch_id or new_batch_id(), actor_user_id=str(user_id),
        action=str(action)[:40],
        before_state=json.dumps(before, ensure_ascii=False, sort_keys=True),
        after_state=json.dumps(after, ensure_ascii=False, sort_keys=True),
    )
    db.session.add(event)
    return event


def _owned_dataset(user_id, dataset_id):
    ds = db.session.get(FaceDataset, int(dataset_id))
    return ds if (ds is not None and ds.trashed_at is None
                  and str(ds.user_id) == str(user_id)) else None


def decode_snapshot(value):
    """Decode the persisted, undo-compatible curation snapshot schema."""
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or any(key not in _UNDO_FIELDS for key in parsed):
        return None
    return parsed


def decode_snapshot_pair(before_state, after_state):
    """Return a compatible before/after pair, or ``None`` when corrupted."""
    before = decode_snapshot(before_state)
    after = decode_snapshot(after_state)
    if before is None or after is None or set(before) != set(after):
        return None
    return before, after


def list_events(user_id, dataset_id, *, limit=30, before_id=None) -> dict | None:
    # Every id below is ``ds.id``, not ``int(dataset_id)``: the ownership check
    # already resolved the row, so re-coercing the caller's argument at each site
    # would be a second, unchecked answer to a question already settled.
    ds = _owned_dataset(user_id, dataset_id)
    if ds is None:
        return None
    limit = max(1, min(int(limit or 30), 100))
    query = CurationEvent.query.filter_by(dataset_id=ds.id)
    if before_id is not None:
        query = query.filter(CurationEvent.id < int(before_id))
    rows = query.order_by(CurationEvent.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    batch_ids = {row.batch_id for row in rows}
    batch_sizes = dict(
        db.session.query(CurationEvent.batch_id, db.func.count(CurationEvent.id))
        .filter(CurationEvent.dataset_id == ds.id,
                CurationEvent.batch_id.in_(batch_ids))
        .group_by(CurationEvent.batch_id).all()
    ) if batch_ids else {}
    events = []
    for row in rows:
        snapshots = decode_snapshot_pair(row.before_state, row.after_state)
        events.append({
            'id': row.id, 'batch_id': row.batch_id, 'image_id': row.image_id,
            'batch_size': int(batch_sizes.get(row.batch_id, 1)),
            'action': row.action,
            'before': snapshots[0] if snapshots else None,
            'after': snapshots[1] if snapshots else None,
            'snapshot_valid': snapshots is not None,
            'reverted': row.reverted_at is not None,
            'created_at': row.created_at.isoformat() if row.created_at else None,
        })
    return {
        'events': events,
        'next_cursor': rows[-1].id if has_more and rows else None,
        'can_undo': (CurationEvent.query.filter_by(
            dataset_id=ds.id, reverted_at=None).first() is not None),
    }


@serialized
def undo(user_id, dataset_id, *, event_id=None) -> dict | None:
    """Undo the selected event's whole atomic batch, refusing stale state.

    A later edit to any same field means replaying the old snapshot could erase
    newer work. In that case the transaction is rejected with an actionable
    conflict instead of silently time-travelling through subsequent edits.
    """
    ds = _owned_dataset(user_id, dataset_id)
    if ds is None:
        return None
    query = CurationEvent.query.filter_by(
        dataset_id=ds.id, reverted_at=None)
    if event_id is not None:
        selected = query.filter_by(id=int(event_id)).first()
    else:
        selected = query.order_by(CurationEvent.id.desc()).first()
    if selected is None:
        return {'undone': 0, 'reason': 'nothing_to_undo'}
    events = (query.filter_by(batch_id=selected.batch_id)
              .order_by(CurationEvent.id.asc()).all())
    changes = []
    for event in events:
        image = db.session.get(FaceDatasetImage, event.image_id)
        snapshots = decode_snapshot_pair(event.before_state, event.after_state)
        if image is None or image.dataset_id != ds.id or snapshots is None:
            raise ValueError('CURATION_UNDO_CONFLICT: a referenced image or snapshot is unavailable')
        before, after = snapshots
        for field, expected in after.items():
            if getattr(image, field) != expected:
                raise ValueError(
                    f'CURATION_UNDO_CONFLICT: image {image.id} changed after this action; '
                    'undo the newer change first')
        # Current-value equality alone is insufficient: keep -> reject -> keep
        # returns to the same value while two newer decisions still exist.  An
        # older undo must not leap over any unreverted event touching the same
        # field, even when the latest value happens to match again.
        newer = (CurationEvent.query
                 .filter(CurationEvent.dataset_id == ds.id,
                         CurationEvent.image_id == event.image_id,
                         CurationEvent.id > event.id,
                         CurationEvent.reverted_at.is_(None),
                         CurationEvent.batch_id != selected.batch_id)
                 .all())
        event_fields = set(before) | set(after)
        for later in newer:
            later_before = decode_snapshot(later.before_state)
            later_after = decode_snapshot(later.after_state)
            later_fields = set(later_before or {}) | set(later_after or {})
            if event_fields & later_fields:
                raise ValueError(
                    f'CURATION_UNDO_CONFLICT: image {image.id} has a newer '
                    'curation decision; undo it first')
        changes.append((event, image, before))
    now = utcnow()
    for event, image, before in changes:
        if 'caption' in before:
            set_caption(
                image,
                before['caption'],
                origin=before.get('caption_origin'),
                provenance=before.get('caption_provenance'),
            )
        for field, value in before.items():
            if field in CAPTION_FIELDS:
                continue
            setattr(image, field, value)
        event.reverted_at = now
    db.session.commit()
    return {
        'undone': len(changes), 'batch_id': selected.batch_id,
        'action': selected.action,
        'image_ids': [event.image_id for event, _, _ in changes],
    }
