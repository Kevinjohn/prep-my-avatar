"""Provenance registry for training runs — "which VERSION of the dataset
produced this checkpoint?"

Every training LAUNCH (local or cloud) records a TrainingRunRecord carrying a
FINGERPRINT of the dataset's training-relevant state (kept images + captions +
exact file-content hashes + trigger + kind). A fingerprint never seen for this
(dataset, family) allocates the next human version (v1, v2, ...); re-running an
unchanged dataset keeps its version. The stored MANIFEST lets the UI say WHAT
changed since a version ("+2 images, 3 captions edited"), not just that it did.

Current local and cloud launches require registration before work starts.
Legacy baseline backfill remains best-effort because it reconstructs historical
evidence rather than authorizing a new run."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from functools import wraps

from ..extensions import db
from ..models import FaceDatasetImage, TrainingRunRecord
from ..utils.time import utcfromtimestamp
from . import face_dataset_service as fds

logger = logging.getLogger(__name__)
_REGISTRATION_LOCK = threading.RLock()


def _serialized_registration(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        # The application enforces one server process per data directory; this
        # lock therefore serializes every local, cloud, and legacy allocation
        # that can target the same SQLite registry.
        with _REGISTRATION_LOCK:
            return func(*args, **kwargs)
    return wrapped


def _caption_hash(text) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def _file_hash(dataset_id, filename) -> str:
    """SHA-256 of the exact admitted bytes; missing files use a sentinel."""
    if not filename:
        return '-'
    try:
        from .. import config as cfg
        p = cfg.dataset_images_root() / str(dataset_id) / filename
        digest = hashlib.sha256()
        with p.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return '-'


def dataset_manifest(dataset_id) -> list:
    """[[image_id, caption_hash, content_sha256], ...] for admitted images."""
    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id, status='keep')
            .order_by(FaceDatasetImage.id.asc()).all())
    return [[r.id, _caption_hash(r.caption), _file_hash(dataset_id, r.filename)]
            for r in rows]


def fingerprint_of(manifest, trigger='', kind='') -> str:
    blob = json.dumps([trigger or '', kind or '', manifest],
                      separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def manifest_diff(old, new) -> dict:
    """What changed between two manifests: image ids added/removed, captions
    edited, image files edited (same id, different content hash)."""
    old_by_id = {e[0]: e for e in (old or [])}
    new_by_id = {e[0]: e for e in (new or [])}
    added = sorted(set(new_by_id) - set(old_by_id))
    removed = sorted(set(old_by_id) - set(new_by_id))
    captions = sum(1 for i in set(old_by_id) & set(new_by_id)
                   if old_by_id[i][1] != new_by_id[i][1])
    edited = sum(1 for i in set(old_by_id) & set(new_by_id)
                 if len(old_by_id[i]) > 2 and len(new_by_id[i]) > 2
                 and old_by_id[i][2] != new_by_id[i][2])
    return {'images_added': len(added), 'images_removed': len(removed),
            'captions_changed': captions, 'images_edited': edited}


@_serialized_registration
def register_launch(user_id, dataset_id, family, source, base_model='',
                    variant=None, masked=True, steps=None, cloud_run_id=None,
                    settings=None, manifest=None, preflight=None, overrides=None,
                    *, trigger=None, kind=None, required=False):
    """Record a training launch and return its TrainingRunRecord.

    Best-effort callers receive ``None`` on failure. Current launch paths pass
    ``required=True`` and fail closed because training without provenance would
    make later checkpoint and Studio comparisons ambiguous.
    """
    try:
        ds = fds.get_dataset(user_id, dataset_id)
        if ds is None:
            if required:
                raise ValueError('dataset disappeared before provenance registration')
            return None
        manifest = manifest if manifest is not None else dataset_manifest(dataset_id)
        trigger = ds.trigger_word if trigger is None else trigger
        kind = (getattr(ds, 'kind', None) or 'character') if kind is None else kind
        fp = fingerprint_of(manifest, trigger, kind)
        legacy_fp = fingerprint_of(
            manifest, trigger, '' if kind == 'character' else kind)[:16]
        # SQLite never enforced the former VARCHAR(16) declaration. Match the
        # legacy prefix once so upgrading an unchanged dataset keeps its human
        # version; every new record stores the complete SHA-256.
        same = (TrainingRunRecord.query
                .filter_by(dataset_id=dataset_id, family=family)
                .filter(TrainingRunRecord.fingerprint.in_((fp, fp[:16], legacy_fp)))
                .first())
        if same is not None:
            version = same.version
        else:
            newest = (TrainingRunRecord.query
                      .filter_by(dataset_id=dataset_id, family=family)
                      .order_by(TrainingRunRecord.version.desc()).first())
            version = (newest.version + 1) if newest else 1
        rec = TrainingRunRecord(
            dataset_id=dataset_id, family=family, source=source,
            cloud_run_id=cloud_run_id, base_model=base_model or '',
            variant=variant, masked=bool(masked), steps=steps,
            settings=json.dumps(settings) if settings else None,
            preflight=json.dumps(preflight) if preflight else None,
            overrides=json.dumps(overrides) if overrides else None,
            fingerprint=fp, manifest=json.dumps(manifest), version=version)
        db.session.add(rec)
        db.session.commit()
        # Materialize server-assigned fields before releasing the registration
        # lock. Callers often need the version/id immediately, and returning an
        # expired ORM row would otherwise trigger a second read after another
        # concurrent registration has begun.
        db.session.refresh(rec)
        return rec
    except Exception as exc:
        logger.exception('training run registration failed (launch continues)')
        db.session.rollback()
        if required:
            raise RuntimeError(
                'could not record the immutable training launch provenance') from exc
        return None


def latest_record(dataset_id, family):
    return (TrainingRunRecord.query
            .filter_by(dataset_id=dataset_id, family=family)
            .order_by(TrainingRunRecord.id.desc()).first())


def ensure_baseline(user_id, dataset_id, family, had_training) -> None:
    """Retrofit for PRE-FEATURE datasets: a dataset that was ALREADY trained
    before the registry existed has checkpoints but no records — without this,
    versioning would only ever apply to future work (deployed-project rule:
    always catch the past up). When training evidence exists and nothing is
    registered, record the CURRENT state as the v1 baseline (source 'legacy'):
    existing checkpoints display as v1 and the next dataset change bumps v2.
    The true historical state is unknowable — 'now' is the honest baseline.
    Best-effort and idempotent."""
    try:
        if not had_training or latest_record(dataset_id, family) is not None:
            return
        register_launch(user_id, dataset_id, family, source='legacy')
    except Exception:
        logger.exception('baseline backfill failed (non-fatal)')


def backfill_legacy_baselines(user_id) -> int:
    """Register legacy v1 baselines outside request handling.

    Older installs can have local checkpoints or cloud runs without immutable
    provenance records.  Inspect that historical evidence during application
    startup so every GET endpoint remains read-only.  Returns the number of
    newly registered dataset/family baselines for diagnostics and tests.
    """
    from ..models import CloudTrainingRun, FaceDataset
    from . import cloud_training as ct
    from . import lora_training as lt

    created = 0
    datasets = (FaceDataset.query
                .filter_by(user_id=user_id, trashed_at=None)
                .order_by(FaceDataset.id.asc()).all())
    for dataset in datasets:
        cloud_runs = CloudTrainingRun.query.filter_by(dataset_id=dataset.id).all()
        cloud_families = {
            ct._run_family(run) or lt._train_type(dataset)
            for run in cloud_runs
        }
        for family in fds.TRAIN_TYPES:
            if latest_record(dataset.id, family) is not None:
                continue
            try:
                local_evidence = bool(lt.list_checkpoints(
                    user_id, dataset.id, family=family))
            except (OSError, ValueError):
                logger.exception(
                    'could not inspect legacy checkpoints dataset=%s family=%s',
                    dataset.id, family)
                local_evidence = False
            if not local_evidence and family not in cloud_families:
                continue
            ensure_baseline(user_id, dataset.id, family, had_training=True)
            if latest_record(dataset.id, family) is not None:
                created += 1
    return created


def start_legacy_backfill(app) -> None:
    """Start one best-effort provenance backfill thread for this app."""
    marker = 'checkpoint_registry_legacy_backfill_started'
    if app.extensions.get(marker):
        return
    app.extensions[marker] = True

    def _run():
        try:
            from ..config import LOCAL_USER
            with app.app_context():
                count = backfill_legacy_baselines(LOCAL_USER)
                if count:
                    logger.info('registered %s legacy training baselines', count)
        except Exception:
            logger.exception('legacy training baseline backfill failed (non-fatal)')

    threading.Thread(
        target=_run, daemon=True, name='checkpoint-baseline-backfill').start()


def record_for_mtime(dataset_id, family, mtime_ts):
    """The run record a FILE most plausibly belongs to: the newest record
    created BEFORE the file was written (records are created at launch, files
    after). A file older than EVERY record predates the registry — its most
    plausible owner is the OLDEST record (the legacy baseline), not the
    newest (live sighting: yesterday's local checkpoints wore a ☁ chip
    because a cloud launch happened to be the latest record). None when
    nothing is registered."""
    recs = (TrainingRunRecord.query
            .filter_by(dataset_id=dataset_id, family=family)
            .order_by(TrainingRunRecord.created_at.desc()).all())
    if not recs:
        return None
    try:
        ts = utcfromtimestamp(mtime_ts)
        for r in recs:
            if r.created_at and r.created_at <= ts:
                return r
    except (OverflowError, OSError, ValueError):
        pass
    return recs[-1]


def dataset_state(user_id, dataset_id, family) -> dict:
    """Current-vs-latest-version comparison for the UI: {registered, version,
    fingerprint, changed, diff} — `changed` is True when the CURRENT dataset
    differs from the latest registered version's manifest."""
    ds = fds.get_dataset(user_id, dataset_id)
    if ds is None:
        return {'registered': False}
    manifest = dataset_manifest(dataset_id)
    kind = getattr(ds, 'kind', None) or 'character'
    fp = fingerprint_of(manifest, ds.trigger_word, kind)
    legacy_fp = fingerprint_of(
        manifest, ds.trigger_word, '' if kind == 'character' else kind)[:16]
    latest = latest_record(dataset_id, family)
    if latest is None:
        return {'registered': False, 'fingerprint': fp}
    try:
        old = json.loads(latest.manifest or '[]')
    except ValueError:
        old = []
    changed = latest.fingerprint not in (fp, fp[:16], legacy_fp)
    return {'registered': True, 'version': latest.version,
            'fingerprint': fp, 'changed': changed,
            'diff': manifest_diff(old, manifest) if changed else None}
