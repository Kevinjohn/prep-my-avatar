"""Append-only curation history and transaction-safe undo."""
from __future__ import annotations

import json
import uuid

from ..extensions import db
from ..models import CurationEvent, FaceDataset, FaceDatasetImage
from ..utils.time import utcnow

_UNDO_FIELDS = {
    'status', 'caption', 'anchor_decision', 'coverage_json', 'framing',
    'coverage_value', 'coverage_provenance', 'variation_label', 'source_rights',
    'watermark_state', 'watermark_bbox', 'watermark_regions',
}


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


def _decode(value):
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or any(key not in _UNDO_FIELDS for key in parsed):
        return None
    return parsed


def list_events(user_id, dataset_id, *, limit=30, before_id=None) -> dict | None:
    if _owned_dataset(user_id, dataset_id) is None:
        return None
    limit = max(1, min(int(limit or 30), 100))
    query = CurationEvent.query.filter_by(dataset_id=int(dataset_id))
    if before_id is not None:
        query = query.filter(CurationEvent.id < int(before_id))
    rows = query.order_by(CurationEvent.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    batch_ids = {row.batch_id for row in rows}
    batch_sizes = dict(
        db.session.query(CurationEvent.batch_id, db.func.count(CurationEvent.id))
        .filter(CurationEvent.dataset_id == int(dataset_id),
                CurationEvent.batch_id.in_(batch_ids))
        .group_by(CurationEvent.batch_id).all()
    ) if batch_ids else {}
    events = [{
        'id': row.id, 'batch_id': row.batch_id, 'image_id': row.image_id,
        'batch_size': int(batch_sizes.get(row.batch_id, 1)),
        'action': row.action, 'before': _decode(row.before_state) or {},
        'after': _decode(row.after_state) or {},
        'reverted': row.reverted_at is not None,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    } for row in rows]
    return {
        'events': events,
        'next_cursor': rows[-1].id if has_more and rows else None,
        'can_undo': (CurationEvent.query.filter_by(
            dataset_id=int(dataset_id), reverted_at=None).first() is not None),
    }


def undo(user_id, dataset_id, *, event_id=None) -> dict | None:
    """Undo the selected event's whole atomic batch, refusing stale state.

    A later edit to any same field means replaying the old snapshot could erase
    newer work. In that case the transaction is rejected with an actionable
    conflict instead of silently time-travelling through subsequent edits.
    """
    if _owned_dataset(user_id, dataset_id) is None:
        return None
    query = CurationEvent.query.filter_by(
        dataset_id=int(dataset_id), reverted_at=None)
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
        before = _decode(event.before_state)
        after = _decode(event.after_state)
        if image is None or image.dataset_id != int(dataset_id) or before is None or after is None:
            raise ValueError('CURATION_UNDO_CONFLICT: a referenced image or snapshot is unavailable')
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
                 .filter(CurationEvent.dataset_id == int(dataset_id),
                         CurationEvent.image_id == event.image_id,
                         CurationEvent.id > event.id,
                         CurationEvent.reverted_at.is_(None),
                         CurationEvent.batch_id != selected.batch_id)
                 .all())
        event_fields = set(before) | set(after)
        for later in newer:
            later_before = _decode(later.before_state)
            later_after = _decode(later.after_state)
            later_fields = set(later_before or {}) | set(later_after or {})
            if event_fields & later_fields:
                raise ValueError(
                    f'CURATION_UNDO_CONFLICT: image {image.id} has a newer '
                    'curation decision; undo it first')
        changes.append((event, image, before))
    now = utcnow()
    for event, image, before in changes:
        for field, value in before.items():
            setattr(image, field, value)
        event.reverted_at = now
    db.session.commit()
    return {
        'undone': len(changes), 'batch_id': selected.batch_id,
        'action': selected.action,
        'image_ids': [event.image_id for event, _, _ in changes],
    }
