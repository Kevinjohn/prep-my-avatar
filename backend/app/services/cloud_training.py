"""Cloud LoRA training orchestrator (vast.ai ephemeral pod).

State machine (CloudTrainingRun.status):
  preparing -> provisioning -> uploading -> training -> downloading
  -> terminating -> done | stopped | error | error_pod_kept

Leak-safety invariant: every path between create_instance() and run
completion must end in destroy_instance() -- enforced here (provision
try/except), by the max-runtime cap (monitor, Task 6) and by boot
reconciliation. The local training path is untouched: a cloud run never sets
'training_in_progress', so local generation/captioning stay available."""
import hashlib
import json
import logging
import os
import re
import secrets as pysecrets
import shutil
import threading
import time
from pathlib import Path

from .. import config as cfg
from ..extensions import db
from ..models import CloudTrainingRun, TrainingRunRecord
from . import face_dataset_service as fds
from . import gpu_speed
from . import lora_training as lt
from . import vast_client
from .aitoolkit_remote import RemoteAiToolkit
from ..utils.time import utcnow

logger = logging.getLogger(__name__)

ACTIVE_STATES = ('preparing', 'provisioning', 'uploading', 'training',
                 'downloading', 'terminating')

_stop_events = {}        # run_id -> threading.Event
_monitor_threads = {}    # run_id -> threading.Thread
_LAUNCH_LOCK = threading.Lock()
_BAD_HOSTS_LOCK = threading.RLock()
_RECONCILE_LOCK = threading.Lock()
_reconciler_started = False
_reconciler_lock = threading.Lock()


def _stop_event_for(run_id):
    return _stop_events.setdefault(int(run_id), threading.Event())


def _staging_root() -> Path:
    # face_dataset_service has no DATA_DIR of its own (its image root is
    # cfg.dataset_images_root() = DATA_DIR/datasets); the actual data root
    # lives in config.py as the private _data_dir() (same convention already
    # used by services.chatgpt_oauth). cloud_runs is a sibling of datasets/.
    root = cfg._data_dir() / 'cloud_runs'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        try:
            root.chmod(0o700)
        except OSError:
            pass
    return root


def _capture_training_snapshot(user_id, dataset_id, destination):
    """Test seam around the immutable launch-time snapshot implementation."""
    from . import training_snapshot
    return training_snapshot.capture(user_id, dataset_id, destination)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _reusable_run_snapshot(run, *, required=False):
    """Return a validated immutable snapshot and its recorded preflight.

    Retry/Continue must not silently substitute today's curated dataset for the
    bytes that produced the source run.  A snapshot is reusable only when the
    source run also owns the required provenance record; this prevents a
    partial pre-registration launch folder from being mistaken for admitted
    training input.
    """
    try:
        params = json.loads(run.train_params or '{}')
    except (TypeError, ValueError):
        params = {}
    record_id = params.get('record_id') if isinstance(params, dict) else None
    source = Path(run.staging_dir) / 'snapshot' if run.staging_dir else None
    try:
        record = db.session.get(TrainingRunRecord, int(record_id))
    except (TypeError, ValueError):
        record = None
    try:
        from . import training_snapshot
        manifest = training_snapshot.load(source) if source is not None else None
    except (OSError, TypeError, ValueError):
        manifest = None
    valid = bool(
        manifest
        and manifest.get('dataset_id') == run.dataset_id
        and record is not None
        and record.dataset_id == run.dataset_id
        and record.cloud_run_id == run.id
    )
    if not valid:
        if required:
            raise ValueError(
                'the source run no longer has its verified training snapshot; '
                'restore its cloud staging data before continuing')
        return None, None
    try:
        preflight = json.loads(record.preflight or '{}')
    except (TypeError, ValueError):
        preflight = {}
    if not isinstance(preflight, dict):
        preflight = {}
    return source, preflight


def _admit_cloud_run(user_id, dataset_id, ds, fam, *,
                     allow_caption_mismatch, allow_uncaptioned,
                     preflight_override=None):
    """Atomically enforce launch limits and reserve one preparing row."""
    with _LAUNCH_LOCK:
        actives = get_active_runs()
        limit = max(1, int((cfg.get('cloud.max_concurrent_runs') or 1)))
        if any(r.dataset_id == dataset_id and (_run_family(r) or fam) == fam
               for r in actives):
            raise RuntimeError(f'this dataset already has an active {fam} cloud run')
        if len(actives) >= limit:
            raise RuntimeError(
                f'cloud run limit reached ({len(actives)}/{limit} active) — '
                'raise cloud.max_concurrent_runs in Settings')
        budget = float(cfg.get('cloud.monthly_budget_usd') or 0)
        if budget > 0:
            spent = month_spend_usd()
            if spent >= budget:
                raise RuntimeError(
                    f'monthly cloud budget reached (${spent:.2f} of ${budget:.2f}) — '
                    'raise cloud.monthly_budget_usd in Settings')
        if preflight_override is None:
            preflight = lt.assert_trainable(
                dataset_id, train_type=fam,
                allow_caption_mismatch=allow_caption_mismatch,
                allow_uncaptioned=allow_uncaptioned)
        else:
            preflight = dict(preflight_override)
        run = CloudTrainingRun(
            dataset_id=dataset_id, status='preparing',
            run_name=lt._run_name(ds, family=fam))
        db.session.add(run)
        db.session.commit()
        return run, preflight


def get_active_runs():
    return (CloudTrainingRun.query
            .filter(CloudTrainingRun.status.in_(ACTIVE_STATES))
            .order_by(CloudTrainingRun.id.asc()).all())


def get_active_run():
    """Compat alias for single-run callers/tests: the first of the active
    runs (or None). Multi-run-aware code uses get_active_runs()."""
    actives = get_active_runs()
    return actives[0] if actives else None


def _run_param(run, key):
    """One key of the run's train_params JSON. None when the params are absent
    or corrupted — a pre-feature row, or the 'preparing' window before launch
    stamps them. Valid-but-non-dict JSON ('"x"', '[1]', '3') must degrade to
    None too, not AttributeError — one corrupt row would 500 cloud_status."""
    try:
        parsed = json.loads(run.train_params or '{}')
        return parsed.get(key) if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


def _run_family(run):
    """Family ('zimage'/'krea'/...) stamped in the run's train_params."""
    return _run_param(run, 'train_type')


class _RunConfigDataset:
    """Read-only view of a dataset with launch-time attributes frozen.

    The cloud monitor builds the pod job through this view so the job's
    complete training recipe comes from what the run was LAUNCHED with — never
    from the dataset's current row. The monitor may rebuild the config minutes
    later, after settings or even the trigger/kind have been edited. The view
    keeps legacy rows working by delegating attributes they did not stamp.
    """

    def __init__(self, ds, overrides):
        self._ds = ds
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._ds, name)


def _run_config_dataset(ds, params):
    """Return the run's frozen recipe, with a legacy family/variant fallback."""
    snapshot = params.get('config_snapshot')
    if isinstance(snapshot, dict):
        overrides = snapshot
    else:
        overrides = {
            key: params[key]
            for key in ('train_type', 'train_variant')
            if key in params
        }
        if 'variant' in params and 'train_variant' not in overrides:
            overrides['train_variant'] = params['variant']
    if not overrides:
        return ds
    return _RunConfigDataset(ds, overrides)


def _validated_config_snapshot(raw, snapshot, dataset_id, user_id, fam, variant):
    """Validate the frozen recipe before applying it to a reused snapshot."""
    if not isinstance(raw, dict):
        raise ValueError('source run has an invalid frozen training config')
    if (raw.get('id') != int(dataset_id)
            or raw.get('user_id') != user_id
            or raw.get('trigger_word') != snapshot.get('trigger_word')
            or raw.get('kind') != snapshot.get('kind')
            or fds.normalize_train_type(raw.get('train_type')) != fam
            or raw.get('train_variant') != variant):
        raise ValueError('source run training config does not match its snapshot')
    if (raw.get('train_base_model') or raw.get('train_vae_path')
            or raw.get('train_te_path')):
        raise ValueError('source cloud run contains unsupported custom weights')
    allowed = {
        'id', 'user_id', 'trigger_word', 'kind', 'fidelity', 'train_type',
        'train_variant', 'train_base_model', 'train_vae_path', 'train_te_path',
        'train_settings',
    }
    return {key: raw.get(key) for key in allowed}


def latest_run_for(dataset_id, train_type=None):
    """Newest run of the dataset; with train_type, the newest run OF THAT
    FAMILY. Falls back to the plain newest when none matches (or the filter
    is absent) so rows without a stamped family stay reachable."""
    q = (CloudTrainingRun.query.filter_by(dataset_id=dataset_id)
         .order_by(CloudTrainingRun.id.desc()))
    runs = q.all()
    newest = runs[0] if runs else None
    if not train_type:
        return newest
    fam = fds.normalize_train_type(train_type)
    legacy = None
    for r in runs:
        if _run_family(r) == fam:
            return r
        if _run_family(r) is None and legacy is None:
            legacy = r
    return legacy


def _set(run, **fields):
    for k, v in fields.items():
        setattr(run, k, v)
    run.updated_at = utcnow()
    db.session.commit()


def _reconcile_before_launch(app):
    """Seam around the launch-time reconcile_orphans() call (defined below).
    A thin indirection rather than calling reconcile_orphans directly so
    tests can no-op launch's reconcile call without also neutering tests
    that exercise reconcile_orphans() itself -- both are the same module-level
    name, so patching that name would silence both call sites at once."""
    reconcile_orphans(app)


def retry_cloud_run(user_id, run_id) -> dict:
    """Relance un run TERMINÉ EN ERREUR avec les paramètres exacts persistés au
    lancement d'origine (train_params) — le bouton ↻ Retry de la page Cloud.
    C'est un VRAI launch_cloud_training (pod frais, mêmes garde-fous : limite
    de runs actifs, budget, unicité par famille), pas une réanimation du pod
    mort. Les confirms captions ne re-bloquent pas : le lancement d'origine
    les avait déjà passés ou fait confirmer."""
    run = db.session.get(CloudTrainingRun, int(run_id))
    if not run:
        raise ValueError('unknown cloud run')
    if run.status != 'error':
        raise ValueError('only a failed run can be retried')
    try:
        p = json.loads(run.train_params or '{}')
    except (TypeError, ValueError):
        p = {}
    if not isinstance(p, dict):
        p = {}
    snapshot_source, preflight = _reusable_run_snapshot(
        run, required=bool(p.get('record_id')))
    return launch_cloud_training(
        user_id, run.dataset_id,
        steps=p.get('steps'),
        variant=p.get('variant'),
        train_type=p.get('train_type'),
        masked=p.get('masked', True),
        allow_caption_mismatch=True, allow_uncaptioned=True,
        gpu_name=p.get('requested_gpu'),
        _snapshot_source=snapshot_source,
        _preflight_override=preflight,
        _config_snapshot=p.get('config_snapshot'))


def _run_staging_checkpoints(run) -> list:
    """This run's HARVESTED checkpoints that still live in staging (NOT the
    trash — trashed saves are moved out of staging_dir): list of
    {'filename', 'step', 'path'}, step-sorted ascending. Mirrors
    cloud_checkpoints' step extraction so 'continue' resumes from the exact same
    checkpoint the hub lists. The unsuffixed FINAL save (no _<step> suffix) is
    the run's target step count."""
    sd = run.staging_dir
    if not sd or not os.path.isdir(sd):
        return []
    target = int(_run_param(run, 'steps') or 0)
    out = []
    for name in os.listdir(sd):
        if not name.lower().endswith('.safetensors'):
            continue
        m = re.search(r'_(\d{6,})\.safetensors$', name)
        out.append({'filename': name,
                    'step': int(m.group(1)) if m else target,
                    'path': os.path.join(sd, name)})
    # step asc; a suffixed save wins ties over the unsuffixed final (deterministic).
    out.sort(key=lambda e: (e['step'], bool(re.search(r'_(\d{6,})\.safetensors$',
                                                       e['filename']))))
    return out


def continue_cloud_run(user_id, run_id, extra_steps=1000) -> dict:
    """Reprend un run cloud TERMINÉ (done) depuis son DERNIER checkpoint harvesté
    et vise dernier_step + extra_steps — le pendant cloud de
    lora_training.continue_training. C'est un VRAI launch_cloud_training (pod
    frais, mêmes garde-fous : limite de runs actifs, budget, unicité par
    famille) avec les paramètres persistés du run source (variante/famille/
    masked/GPU class, comme retry_cloud_run) ; son monitor, AVANT de démarrer le
    job, dépose le checkpoint dans le save_root du job sur le pod pour déclencher
    l'auto-resume d'ai-toolkit. Le job config reprend la recette et le snapshot
    immuables du run source (les anciennes lignes antérieures à la provenance
    retombent sur le dataset courant) ; register_launch reste un launch cloud
    normal — le resume est un détail d'exécution."""
    run = db.session.get(CloudTrainingRun, int(run_id))
    if not run:
        raise ValueError('unknown cloud run')
    if run.status != 'done':
        raise ValueError('only a finished (done) run can be continued')
    cks = _run_staging_checkpoints(run)
    if not cks:
        raise ValueError('no harvested checkpoint to continue from — its staging '
                         'was cleaned; relaunch a fresh cloud run instead')
    latest = cks[-1]
    try:
        extra = max(100, int(extra_steps))
    except (TypeError, ValueError):
        extra = 1000
    try:
        p = json.loads(run.train_params or '{}')
    except ValueError:
        p = {}
    if not isinstance(p, dict):
        p = {}
    # Pre-provenance legacy rows never owned an immutable snapshot. Keep their
    # historical Continue behavior, while current rows fail closed instead of
    # silently resuming against a different dataset after staging was removed.
    snapshot_source, preflight = _reusable_run_snapshot(
        run, required=bool(p.get('record_id')))
    res = launch_cloud_training(
        user_id, run.dataset_id,
        steps=latest['step'] + extra,
        variant=p.get('variant'),
        train_type=p.get('train_type'),
        masked=p.get('masked', True),
        allow_caption_mismatch=True, allow_uncaptioned=True,
        gpu_name=p.get('requested_gpu'),
        resume_ckpt_path=latest['path'], resume_step=latest['step'],
        _snapshot_source=snapshot_source,
        _preflight_override=preflight,
        _config_snapshot=p.get('config_snapshot'))
    res['resumed_from'] = latest['step']
    res['target_steps'] = latest['step'] + extra
    return res


def launch_cloud_training(user_id, dataset_id, steps=None, base_model='',
                          variant=None, train_type=None, masked=True,
                          allow_caption_mismatch=False, allow_uncaptioned=False,
                          gpu_name=None, resume_ckpt_path=None, resume_step=None,
                          _snapshot_source=None, _preflight_override=None,
                          _config_snapshot=None) -> dict:
    if not cfg.secret('VAST_API_KEY'):
        raise RuntimeError('vast.ai API key is not configured — add it in Settings')
    # A user launching after days away is exactly when an expired
    # error_pod_kept pod (past its recovery window) should be reaped, not
    # just at boot. reconcile_orphans() never raises, so this is safe; routed
    # through the _reconcile_before_launch seam (rather than calling
    # reconcile_orphans directly) so tests can no-op *this* call site without
    # also neutering tests that exercise reconcile_orphans() itself.
    from flask import current_app
    # Finish reconciliation before a provider instance can be created.  A
    # detached reconcile used to snapshot the DB, race this launch's
    # create/register window, and destroy the brand-new pod as an orphan.
    _reconcile_before_launch(current_app._get_current_object())
    if base_model:
        raise ValueError('custom weights are local-only — cloud training '
                         'uses the official Hugging Face bases')
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    source_manifest = None
    if _snapshot_source is not None:
        from . import training_snapshot
        source_manifest = training_snapshot.load(_snapshot_source)
        if source_manifest.get('dataset_id') != int(dataset_id):
            raise ValueError('source training snapshot belongs to another dataset')
    # A dataset carrying a PERSISTED custom base (absolute-path weights) or an
    # SDXL VAE/TE override must not silently fall back to the official base in the
    # cloud (the exact mute divergence the feature forbids) — refuse explicitly.
    if (source_manifest is None
            and (getattr(ds, 'train_base_model', None)
            or getattr(ds, 'train_vae_path', None)
            or getattr(ds, 'train_te_path', None))):
        raise ValueError('custom weights are local-only — cloud training '
                         'uses the official Hugging Face bases')
    fam = fds.normalize_train_type(train_type or getattr(ds, 'train_type', None))
    if fam == 'sdxl':
        raise ValueError('SDXL training needs a local base checkpoint — '
                         'cloud training supports Z-Image, Krea and FLUX.2 Klein')
    # flux2klein n'est PAS bloqué (contrairement à flux) : ses bases sont des repos
    # HF officiels que le pod télécharge lui-même — le 9B (32-48 GB VRAM) est même
    # la voie cloud principale de la famille.
    if fam == 'flux':
        raise ValueError('FLUX.1 training is local-only for now — '
                         'cloud training supports Z-Image, Krea and FLUX.2 Klein')
    # Run-count, per-dataset uniqueness, budget, preflight, and row reservation
    # are one in-process critical section. The app-wide process lock guarantees
    # there is only one server process for this data directory.
    run, preflight_report = _admit_cloud_run(
        user_id, dataset_id, ds, fam,
        allow_caption_mismatch=allow_caption_mismatch,
        allow_uncaptioned=allow_uncaptioned,
        preflight_override=_preflight_override if source_manifest else None)
    rec = None
    params = {}
    try:
        # Anything failing past this point (params, thread start) must not
        # strand the 'preparing' row forever — that would deadlock the
        # single-active-run guard above. Flip it to 'error' and re-raise.
        # NOTE: conversion and rembg mask generation happen in the monitor
        # thread (_prepare_staging). This request still performs the required
        # immutable raw snapshot copy, so launch latency scales with admitted
        # input bytes; the UI deliberately remains in its Launching state.
        _set(run, vast_label=f'lds-{run.id}',
             job_name=f'lds{run.id}_{lt._run_name(ds, family=fam)}')
        # Mirror the LOCAL launch: persist this dataset's family/variant as its
        # remembered selection (launch_training does the same; two launch tests
        # assert it). This is now ONLY the dataset's default selection — the
        # monitor builds the pod job from the run's STAMPED params (see
        # _run_config_dataset at the build site), so a later launch overwriting
        # this row can no longer retarget an already-provisioning run's arch.
        variant = (variant or '').strip().lower()
        # Enum PAR FAMILLE (flux2klein : '4b'/'9b') — même validation que le
        # lancement local, hors-liste → défaut family-aware (jamais d'erreur).
        if variant not in lt._valid_variants_for(fam):
            variant = lt._default_variant_for(fam)
        ds.train_type = fam
        ds.train_variant = variant
        db.session.commit()
        # Same floor as the local path — a sub-500 target produces a run with
        # zero usable snapshots.
        n_steps = max(500, int(steps)) if steps else lt.default_steps(ds)
        # requested_gpu (from the launch-time speed picker) is a PREFERENCE, not
        # an offer-id lock: _provision re-searches live offers and rents a
        # reliable one of this class, or a similarly fast class if the exact
        # class sold out. It never silently downgrades to a much slower GPU.
        params = {'steps': n_steps, 'variant': variant,
                  'train_type': fam, 'masked': bool(masked)}
        if gpu_name:
            params['requested_gpu'] = str(gpu_name)
        # Continue-in-cloud: the monitor seeds this checkpoint into the pod job's
        # save_root before start_job so ai-toolkit auto-resumes from it. Absent
        # on a normal launch (the seed step is then a no-op).
        # Capture the exact admitted bytes/captions before returning from launch.
        # The monitor may start minutes later, while curation remains editable.
        staging = _staging_root() / f'run_{run.id}'
        (staging / 'samples').mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != 'nt':
            for private_dir in (staging, staging / 'samples'):
                try:
                    private_dir.chmod(0o700)
                except OSError:
                    pass
        # Persist ownership before copying. If snapshot capture fails, the
        # terminal row still points at the partial folder so cleanup can recover it.
        _set(run, staging_dir=str(staging))
        if source_manifest is None:
            snapshot = _capture_training_snapshot(
                user_id, dataset_id, staging / 'snapshot')
        else:
            from . import training_snapshot
            shutil.copytree(_snapshot_source, staging / 'snapshot')
            snapshot = training_snapshot.load(staging / 'snapshot')
        if resume_ckpt_path:
            source_checkpoint = Path(resume_ckpt_path)
            if source_checkpoint.is_symlink() or not source_checkpoint.is_file():
                raise ValueError('resume checkpoint is missing or unsafe')
            resume_dir = staging / 'resume'
            resume_dir.mkdir(mode=0o700)
            copied_checkpoint = resume_dir / source_checkpoint.name
            before_hash = _file_sha256(source_checkpoint)
            shutil.copy2(source_checkpoint, copied_checkpoint)
            if (_file_sha256(copied_checkpoint) != before_hash
                    or _file_sha256(source_checkpoint) != before_hash):
                raise RuntimeError('resume checkpoint changed while it was copied')
            if os.name != 'nt':
                try:
                    copied_checkpoint.chmod(0o600)
                except OSError:
                    pass
            params['resume_ckpt_path'] = str(copied_checkpoint)
            if resume_step is not None:
                params['resume_step'] = int(resume_step)
        captured_training = snapshot.get('training_config')
        if not isinstance(captured_training, dict):
            captured_training = {}
        captured_config_snapshot = {
            'id': int(ds.id),
            'user_id': ds.user_id,
            'trigger_word': snapshot.get('trigger_word', ds.trigger_word),
            'kind': snapshot.get('kind', getattr(ds, 'kind', None) or 'character'),
            'fidelity': snapshot.get('fidelity', getattr(ds, 'fidelity', None)),
            'train_type': fam,
            'train_variant': variant,
            # Cloud always uses official bases; any persisted local override was
            # rejected before admission.
            'train_base_model': None,
            'train_vae_path': None,
            'train_te_path': None,
            'train_settings': captured_training.get(
                'train_settings', getattr(ds, 'train_settings', None)),
        }
        if _config_snapshot is None:
            config_snapshot = captured_config_snapshot
        else:
            config_snapshot = _validated_config_snapshot(
                _config_snapshot, snapshot, dataset_id, user_id, fam, variant)
        params['config_snapshot'] = config_snapshot
        launch_settings = lt.launch_settings_snapshot(
            _RunConfigDataset(ds, config_snapshot), fam)
        effective_masked = bool(masked and snapshot.get('kind') not in ('concept', 'style'))
        params['masked'] = effective_masked
        # Provenance registry (same as local launches): dataset version at
        # launch time, stamped into the params so payloads can expose it.
        from . import checkpoint_registry
        rec = checkpoint_registry.register_launch(
            user_id, dataset_id, family=fam, source='cloud',
            variant=variant, masked=effective_masked, steps=n_steps,
            cloud_run_id=run.id, settings=launch_settings,
            manifest=snapshot['registry_manifest'],
            preflight=preflight_report,
            overrides={
                'allow_caption_mismatch': bool(allow_caption_mismatch),
                'allow_uncaptioned': bool(allow_uncaptioned),
                'masked': effective_masked,
                'masked_requested': bool(masked),
                'resumed': bool(resume_ckpt_path),
            },
            trigger=snapshot['trigger_word'], kind=snapshot['kind'],
            required=True)
        params['version'] = rec.version
        params['record_id'] = rec.id
        _set(run, train_params=json.dumps(params))
        _stop_event_for(run.id).clear()
        _start_monitor(run.id)
    except Exception as e:
        # A failed commit leaves SQLAlchemy unusable until rollback. Also remove
        # provenance allocated immediately before monitor startup: no provider
        # work can exist yet, so retaining that row would falsely label a
        # checkpoint version as trained.
        db.session.rollback()
        failed_run = db.session.get(CloudTrainingRun, run.id)
        try:
            if rec is not None:
                stored_record = db.session.get(TrainingRunRecord, rec.id)
                if stored_record is not None and stored_record.cloud_run_id == run.id:
                    db.session.delete(stored_record)
                params.pop('record_id', None)
                params.pop('version', None)
                if failed_run is not None:
                    failed_run.train_params = json.dumps(params) if params else None
            if failed_run is not None:
                failed_run.status = 'error'
                failed_run.error = f'launch failed: {e}'
                failed_run.finished_at = utcnow()
                failed_run.updated_at = utcnow()
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('could not close failed cloud launch %s', run.id)
        raise
    return {'run_id': run.id, 'status': run.status,
            'job_name': run.job_name, 'steps': n_steps}


def _prepare_staging(run):
    """Heavy part of the launch, run from the MONITOR thread: staging dirs +
    dataset export (rembg masks — ~1-2 s/image). No-op when staging already
    exists (resume). A failure propagates to the monitor's generic error
    handler (run flips to 'error', slot freed)."""
    if (run.staging_dir
            and os.path.isfile(os.path.join(run.staging_dir, 'dataset',
                                            '.snapshot-complete'))):
        return
    _set(run, phase_detail='Preparing dataset (masks)…')
    params = json.loads(run.train_params or '{}')
    staging = Path(run.staging_dir) if run.staging_dir else _staging_root() / f'run_{run.id}'
    (staging / 'samples').mkdir(parents=True, exist_ok=True)
    snapshot_dir = staging / 'snapshot'
    kwargs = {'masked': bool(params.get('masked', True)),
              'dest_dir': str(staging / 'dataset')}
    if (snapshot_dir / 'training-snapshot.json').is_file():
        kwargs['snapshot_dir'] = str(snapshot_dir)
    lt.export_dataset_to_aitoolkit('local', run.dataset_id, **kwargs)
    dataset_dir = staging / 'dataset'
    dataset_dir.mkdir(parents=True, exist_ok=True)
    actual_masked = bool(params.get('masked', True)
                         and lt._mask_fields(str(dataset_dir)))
    if actual_masked != bool(params.get('masked', True)):
        # Mask generation can fall back after admission (for example when
        # rembg is unavailable). Stamp the effective value into both the run
        # payload and immutable provenance before any provider is rented.
        from ..models import TrainingRunRecord
        record = db.session.get(TrainingRunRecord, params.get('record_id'))
        if record is None or record.cloud_run_id != run.id:
            raise RuntimeError('cloud training provenance record is missing')
        try:
            overrides = json.loads(record.overrides or '{}')
        except (TypeError, ValueError):
            overrides = {}
        if not isinstance(overrides, dict):
            overrides = {}
        overrides['masked'] = actual_masked
        overrides['mask_fallback'] = 'generation_unavailable'
        record.masked = actual_masked
        record.overrides = json.dumps(overrides)
        params['masked'] = actual_masked
        _set(run, train_params=json.dumps(params))
    (staging / 'dataset' / '.snapshot-complete').write_text('1', encoding='ascii')
    _set(run, staging_dir=str(staging))


def _register_instance(run, instance_id, offer, token):
    """Isolated so provisioning tests can inject a post-create failure."""
    params = json.loads(run.train_params or '{}')
    gpu_name = offer.get('gpu_name')
    price = offer.get('dph_total')
    estimated_minutes = gpu_speed.estimate_minutes(
        gpu_name or 'GPU', params.get('train_type') or 'zimage',
        int(params.get('steps') or 3000))
    overhead = float((cfg.get('cloud') or {}).get('pod_overhead_minutes') or 0)
    _set(run, vast_instance_id=str(instance_id), auth_token=token,
         gpu_name=gpu_name, price_per_hour=price, billing_started_at=utcnow(),
         estimated_minutes=estimated_minutes,
         estimated_cost_usd=(round(price * (estimated_minutes + overhead) / 60.0, 2)
                             if price is not None else None),
         status='provisioning', phase_detail='Instance created — booting')


# --- Offer quality layer (2026-07-13, after a dead-cheap 5090 host froze in
# --- 'loading'): the absolute cheapest host of a class is adversely selected
# --- more often than not. Bait prices are excluded, recently-failed hosts are
# --- blacklisted, and at similar price the more RELIABLE host wins. ----------

_PRICE_BAIT_RATIO = 0.60      # offers < 60% of their class median are suspect
_SIMILAR_PRICE_WINDOW = 1.10  # within +10% of cheapest -> reliability decides


def _bad_hosts_path() -> Path:
    return _staging_root() / 'bad_hosts.json'


def _run_machine_id(run):
    """machine_id stamped by _provision into train_params. Defensive like
    _run_family: absent/corrupt params -> None, never an exception (this is
    called from stop/timeout paths that must not fail)."""
    try:
        parsed = json.loads(run.train_params or '{}')
        return parsed.get('machine_id') if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


def _load_bad_hosts() -> dict:
    """{machine_id(str): {'ts': epoch, 'reason': str}} — expired entries are
    dropped on read (TTL cloud.host_blacklist_days). Corrupt file -> empty."""
    with _BAD_HOSTS_LOCK:
        try:
            raw = json.loads(_bad_hosts_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        ttl = float(cfg.get('cloud.host_blacklist_days') or 3) * 86400
        now = _now()
        live = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            try:
                timestamp = float(value.get('ts') or 0)
            except (TypeError, ValueError):
                continue
            if now - timestamp <= ttl:
                live[str(key)] = value
        if len(live) != len(raw):
            try:
                _write_bad_hosts(live)
            except OSError:
                pass
        return live


def _write_bad_hosts(hosts):
    path = _bad_hosts_path()
    temporary = path.with_suffix('.json.tmp')
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(hosts, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _blacklist_host(machine_id, reason):
    """Remember a host whose pod never became ready so the next launch (and the
    tier list) skips it for a few days. Best-effort: never raises."""
    if not machine_id:
        return
    try:
        with _BAD_HOSTS_LOCK:
            hosts = _load_bad_hosts()
            hosts[str(machine_id)] = {'ts': _now(), 'reason': str(reason)[:200]}
            _write_bad_hosts(hosts)
        logger.warning('blacklisted vast host machine_id=%s for %s day(s): %s',
                       machine_id, cfg.get('cloud.host_blacklist_days') or 3, reason)
    except Exception:
        logger.exception('could not blacklist host %s', machine_id)


def _filter_offers(offers) -> list:
    """Drop blacklisted hosts and bait-priced offers (< 60% of their GPU
    class's median price when the class has >= 3 offers — with fewer there is
    no reliable median). Never returns [] when the input wasn't: if every
    offer got filtered, fall back to the input minus blacklisted hosts only
    (renting a suspect host beats failing the run outright)."""
    bad = _load_bad_hosts()
    not_blacklisted = [o for o in offers
                       if str(o.get('machine_id') or '') not in bad]
    by_class = {}
    for o in not_blacklisted:
        by_class.setdefault(o.get('gpu_name') or '', []).append(o)
    kept = []
    for name, group in by_class.items():
        prices = sorted(o['dph_total'] for o in group
                        if o.get('dph_total') is not None)
        if len(prices) >= 3:
            median = prices[len(prices) // 2]
            floor = median * _PRICE_BAIT_RATIO
            group = [o for o in group
                     if o.get('dph_total') is None or o['dph_total'] >= floor]
        kept.extend(group)
    kept.sort(key=lambda o: o.get('dph_total')
              if o.get('dph_total') is not None else 9e9)
    return kept or not_blacklisted


def _best_of(group):
    """Most reliable offer among those within +10% of the group's cheapest —
    a hair more money for a host that actually boots is the right trade."""
    if not group:
        raise RuntimeError('no eligible vast.ai offers remain')
    priced = [o for o in group if o.get('dph_total') is not None]
    if not priced:
        return group[0]
    cheapest = min(o['dph_total'] for o in priced)
    window = [o for o in priced if o['dph_total'] <= cheapest * _SIMILAR_PRICE_WINDOW]
    # reliability first; at equal (or absent) reliability the CHEAPEST wins —
    # offers without the field must not silently cost +10%.
    return max(window, key=lambda o: ((o.get('reliability') or 0), -o['dph_total']))


def _pick_offer(offers, requested_gpu):
    """Best offer of the requested GPU class if the user picked a speed tier
    and that class is still on the market; otherwise an offer of a
    SIMILAR-OR-BETTER speed tier (≥75% of the requested class's throughput,
    per gpu_speed). 'Best' = most reliable within +10% of the cheapest (see
    _best_of), on offers already stripped of blacklisted hosts and bait
    prices by _filter_offers.

    The historical fallback — cheapest offer of ANY class — handed a $0.13/h
    RTX 3090 to a 12B Krea run when the requested RTX PRO 6000 S sold out
    between the picker and the launch (retry path, user-reported): the
    bottom-barrel is exactly where the flaky hosts live, and the run would
    have been ~3x slower. No similar tier on the market -> actionable error,
    never a silent downgrade."""
    if requested_gpu:
        matches = [o for o in offers if (o.get('gpu_name') or '') == requested_gpu]
        if matches:
            return _best_of(matches)
        floor = gpu_speed.speed_factor(requested_gpu) * 0.75
        similar = [o for o in offers
                   if gpu_speed.speed_factor(o.get('gpu_name')) >= floor]
        if similar:
            return _best_of(similar)
        raise RuntimeError(
            f'no offers similar to {requested_gpu} right now — open the GPU '
            'picker and choose another speed tier')
    return _best_of(offers)


def _assert_projected_budget(run, offer, family, params) -> float:
    """Reserve estimated spend before renting so the configured cap is predictive."""
    price = float(offer.get('dph_total') or 0)
    estimated_minutes = gpu_speed.estimate_minutes(
        offer.get('gpu_name') or 'GPU', family,
        int(params.get('steps') or 3000))
    overhead = float((cfg.get('cloud') or {}).get('pod_overhead_minutes') or 0)
    estimate = round(price * (estimated_minutes + overhead) / 60.0, 2)
    budget = float(cfg.get('cloud.monthly_budget_usd') or 0)
    with _LAUNCH_LOCK:
        if budget > 0:
            spent = month_spend_usd()
            reserved = 0.0
            for active in get_active_runs():
                if active.id == run.id or active.estimated_cost_usd is None:
                    continue
                reserved += max(
                    0.0, float(active.estimated_cost_usd) - _cost_estimate(active))
            projected = spent + reserved + estimate
            if projected > budget:
                raise RuntimeError(
                    f'cloud run estimate would exceed the monthly budget '
                    f'(${projected:.2f} projected, ${budget:.2f} cap)')
        # Persist the reservation while still holding the admission lock. A
        # simultaneous provision now sees this estimate before either provider
        # create call begins, so two runs cannot both spend the same remainder.
        _set(run, estimated_minutes=estimated_minutes,
             estimated_cost_usd=estimate)
    return estimate


def _provision(run):
    """Search offers and create the instance, honoring the launch-time GPU
    choice when the picked class is still available.
    LEAK-SAFE: any failure after create_instance destroys the instance."""
    c = cfg.get('cloud') or {}
    params = json.loads(run.train_params or '{}')
    fam = params.get('train_type') or 'zimage'
    min_vram = (c.get('min_vram_gb') or {}).get(fam, 24)
    offers = vast_client.search_offers(
        min_vram_gb=min_vram, max_dph=c.get('max_price_per_hour', 0.80),
        min_inet_down_mbps=int(c.get('min_inet_down_mbps') or 0),
        min_reliability=float(c.get('min_reliability') or 0.98),
        min_disk_bw_mbps=int(c.get('min_disk_bw_mbps') or 0))
    if not offers:
        raise RuntimeError(
            f'no vast.ai offer matches (>= {min_vram} GB VRAM, '
            f'<= ${c.get("max_price_per_hour", 0.80)}/h) — raise the price cap in Settings')
    eligible = _filter_offers(offers)
    if not eligible:
        raise RuntimeError(
            'all matching vast.ai hosts are temporarily blacklisted after recent '
            'failures — wait for the blacklist window or clear cloud run data')
    offer = _pick_offer(eligible, params.get('requested_gpu'))
    # Search results are live and pricing is now known: enforce the predictive
    # budget at the last safe point before create_instance incurs charges.
    _assert_projected_budget(run, offer, fam, params)
    # Stamp the host identity so a boot failure can blacklist THIS machine.
    if offer.get('machine_id') is not None:
        params['machine_id'] = offer['machine_id']
        _set(run, train_params=json.dumps(params))
    template_hash = (c.get('template_hash') or '').strip()
    if template_hash:
        # Preferred path (smoke-validated 2026-07-12): the official template
        # publishes the UI behind the pod's Caddy proxy on ui_port and vast
        # generates the per-instance auth token (picked up from the instance
        # record during boot-wait). HF_TOKEN reaches the pod later via
        # ensure_settings(), not env.
        token = ''
        instance_id = vast_client.create_instance(
            offer['offer_id'], disk_gb=int(c.get('disk_gb') or 60),
            label=run.vast_label, template_hash=template_hash,
            image=(c.get('image') or None))
    else:
        # Raw-image fallback (config escape hatch): direct port publish +
        # our own bearer token on the UI itself.
        token = pysecrets.token_urlsafe(24)
        port = int(c.get('ui_port') or 18675)
        env = {'AI_TOOLKIT_AUTH': token, f'-p {port}:{port}': '1'}
        hf = cfg.secret('HF_TOKEN')
        if hf:
            env['HF_TOKEN'] = hf
        instance_id = vast_client.create_instance(
            offer['offer_id'], disk_gb=int(c.get('disk_gb') or 60),
            label=run.vast_label, image=c.get('image'), env=env,
            onstart=(c.get('onstart') or None))
    try:
        _register_instance(run, instance_id, offer, token)
    except Exception:
        # the pod exists but we failed to remember it -> kill it NOW, and make
        # the outcome observable (destroy_instance returns False on failure)
        try:
            if not vast_client.destroy_instance(instance_id):
                logger.warning('leak-safe destroy of %s FAILED — instance may still '
                               'be running; boot reconciliation will retry', instance_id)
        except Exception:
            logger.exception('leak-safe destroy of %s raised', instance_id)
        raise


def request_stop(run_id=None) -> bool:
    if run_id is not None:
        run = db.session.get(CloudTrainingRun, int(run_id))
        if not run:
            return False
        if run.status == 'error_pod_kept':
            _finish(run, 'stopped', detail='Recovery pod stopped by user',
                    error=run.error)
            return True
        if run.status == 'terminating':
            status, detail, error = _cleanup_target(run)
            _finish(run, status, detail=detail, error=error)
            return True
        if run.status not in ACTIVE_STATES:
            return False
        _stop_event_for(run.id).set()
        return True
    actives = get_active_runs()
    for run in actives:
        _stop_event_for(run.id).set()
    return bool(actives)


def _cleanup_target(run):
    try:
        params = json.loads(run.train_params or '{}')
    except (TypeError, ValueError):
        params = {}
    if not isinstance(params, dict):
        params = {}
    return (
        params.get('_cleanup_target_status') or 'error',
        params.get('_cleanup_detail') or run.phase_detail or 'Pod terminated',
        params.get('_cleanup_error'),
    )


def _clear_cleanup_metadata(run):
    try:
        params = json.loads(run.train_params or '{}')
    except (TypeError, ValueError):
        return run.train_params
    if not isinstance(params, dict):
        return run.train_params
    for key in ('_cleanup_target_status', '_cleanup_detail', '_cleanup_error'):
        params.pop(key, None)
    return json.dumps(params)


def _complete_cleanup(run, status, detail='', error=None, *, ended_at=None):
    ended_at = ended_at or utcnow()
    _set(run, status=status, phase_detail=detail, error=error,
         train_params=_clear_cleanup_metadata(run), auth_token=None,
         billing_ended_at=(ended_at if run.billing_started_at else None),
         finished_at=run.finished_at or ended_at)


def _mark_cleanup_pending(run, status, detail='', error=None):
    try:
        params = json.loads(run.train_params or '{}')
    except (TypeError, ValueError):
        params = {}
    if not isinstance(params, dict):
        params = {}
    params.update({
        '_cleanup_target_status': status,
        '_cleanup_detail': detail,
        '_cleanup_error': error,
    })
    _set(run, status='terminating',
         phase_detail='Provider cleanup pending — retrying automatically',
         error=error, train_params=json.dumps(params), finished_at=None,
         billing_ended_at=None)


def reconcile_orphans(app) -> int:
    """Boot-time safety net: destroy every 'lds-*' vast instance that no
    active run owns. GENUINELY never raises (boot must not be blocked): the
    whole body — app_context included — sits under a blanket except, so an
    unexpected failure outside the vast_client calls (db not ready, config
    error...) is logged and returns the count destroyed so far.

    error_pod_kept policy: a run in that status deliberately kept its pod
    alive (checkpoint download failed at run completion) so the user can
    recover the checkpoint manually. That pod must NOT be destroyed like a
    plain orphan -- it is spared while `run.finished_at` is within
    cloud.max_runtime_minutes of now, and only reaped past that window (with
    the run annotated, status left untouched -- terminal states stay
    terminal)."""
    destroyed = 0
    if not _RECONCILE_LOCK.acquire(blocking=False):
        return 0
    try:
        with app.app_context():
            if not cfg.secret('VAST_API_KEY'):
                return 0
            try:
                instances = vast_client.list_instances()
            except Exception as e:
                logger.warning('reconcile: cannot list vast instances: %s', e)
                return 0
            runs_with_instances = {
                str(r.vast_instance_id): r
                for r in CloudTrainingRun.query.filter(
                    CloudTrainingRun.vast_instance_id.isnot(None)).all()
            }
            keep = {
                iid for iid, run in runs_with_instances.items()
                if run.status in ACTIVE_STATES and run.status != 'terminating'
            }
            c = cfg.get('cloud') or {}
            max_seconds = int(c.get('max_runtime_minutes') or 480) * 60
            now = utcnow()
            seen_instance_ids = set()
            for inst in instances:
                label = inst.get('label') or ''
                if not label.startswith('lds-'):
                    continue
                iid = str(inst['instance_id'])
                seen_instance_ids.add(iid)
                if iid in keep:
                    continue
                associated_run = runs_with_instances.get(iid)
                kept_run = (associated_run
                            if associated_run is not None
                            and associated_run.status == 'error_pod_kept'
                            else None)
                if kept_run is not None:
                    # No finished_at (shouldn't happen -- every writer stamps it) means
                    # the recovery window can't be established: fail toward the leak-safety
                    # invariant (reap) rather than sparing an unbounded pod.
                    if kept_run.finished_at and \
                            (now - kept_run.finished_at).total_seconds() <= max_seconds:
                        continue    # still within the manual-recovery window -> spare
                    try:
                        if vast_client.destroy_instance(inst['instance_id']):
                            destroyed += 1
                            logger.warning('reconcile: reaped expired error_pod_kept '
                                           'pod %s (%s)', inst['instance_id'], label)
                            _set(kept_run, error=(kept_run.error or '') +
                                 ' — pod reaped after the recovery window',
                                 auth_token=None, billing_ended_at=now)
                    except Exception as e:
                        logger.warning('reconcile: destroy %s failed: %s',
                                       inst['instance_id'], e)
                    continue
                try:
                    if vast_client.destroy_instance(inst['instance_id']):
                        destroyed += 1
                        if associated_run is not None \
                                and associated_run.status == 'terminating':
                            target, detail, error = _cleanup_target(associated_run)
                            _complete_cleanup(associated_run, target, detail, error,
                                              ended_at=now)
                        elif associated_run is not None \
                                and not associated_run.billing_ended_at:
                            _set(associated_run, auth_token=None,
                                 billing_ended_at=now)
                        logger.warning('reconcile: destroyed cleanup/orphan pod %s (%s)',
                                       inst['instance_id'], label)
                except Exception as e:
                    logger.warning('reconcile: destroy %s failed: %s',
                                   inst['instance_id'], e)
            # A previously-kept provider instance that is no longer returned
            # by the authoritative instance list has already stopped billing
            # (for example, the user destroyed it in the vast.ai console).
            # Close that window instead of showing a perpetually growing cost.
            for iid, associated_run in runs_with_instances.items():
                if iid in seen_instance_ids or associated_run.billing_ended_at:
                    continue
                if associated_run.status == 'terminating':
                    target, detail, error = _cleanup_target(associated_run)
                    _complete_cleanup(associated_run, target, detail, error,
                                      ended_at=now)
                else:
                    suffix = ' — provider instance is no longer active'
                    _set(associated_run, billing_ended_at=now, auth_token=None,
                         error=((associated_run.error or '') + suffix))
    except Exception:
        logger.exception('reconcile failed')
    finally:
        _RECONCILE_LOCK.release()
    return destroyed


def start_reconciler(app, interval_seconds=60):
    """Start the single periodic provider cleanup worker for this process."""
    global _reconciler_started
    with _reconciler_lock:
        if _reconciler_started:
            return
        _reconciler_started = True

    def _loop():
        while True:
            try:
                reconcile_orphans(app)
            except Exception:
                logger.exception('periodic cloud reconcile failed')
            _sleep(max(15, int(interval_seconds)))

    threading.Thread(target=_loop, daemon=True,
                     name='cloud-provider-reconciler').start()


def _start_monitor_for_app(app, run_id):
    """Like _start_monitor but usable outside a request context (boot)."""
    t = threading.Thread(
        target=_monitor, args=(app, run_id), daemon=True, name=f'cloud-train-{run_id}')
    _monitor_threads[int(run_id)] = t
    t.start()


def _start_monitor(run_id):
    from flask import current_app
    _start_monitor_for_app(current_app._get_current_object(), run_id)


def boot_recover(app):
    """Called once at startup (daemon thread). Never raises: a boot recovery
    bug must not prevent the app from serving requests. (1) reconcile any
    'lds-*' pod the DB no longer accounts for; (2) if a run was active when
    the app last closed and its pod was already created, resume monitoring
    it (the pod kept training/uploading in our absence); (3) if it never got
    a pod (crashed during 'preparing'), there is nothing to resume -> flip
    it to 'error' so its slot is freed. Iterates every active run (not just
    one) so a restart with several concurrent runs resumes all of them."""
    try:
        reconcile_orphans(app)
        with app.app_context():
            if not cfg.secret('VAST_API_KEY'):
                return
            for run in get_active_runs():
                if run.vast_instance_id:
                    logger.info('resuming cloud run %s (pod %s kept training)',
                                run.id, run.vast_instance_id)
                    _start_monitor_for_app(app, run.id)
                else:
                    _set(run, status='error', finished_at=utcnow(),
                         error='app restarted before the pod was created')
    except Exception:
        logger.exception('cloud boot recovery failed')


POLL_SECONDS = 10
_CKPT_SYNC_EVERY_POLLS = 12          # mid-run checkpoint mirror every ~2 min
READY_TIMEOUT_SECONDS = 900          # 15 min: boot + image pull
UNREACHABLE_GRACE_SECONDS = 180      # tolerated mid-run network blackout
_sleep = time.sleep


def _now():
    return time.time()


def _make_remote(run) -> RemoteAiToolkit:
    return RemoteAiToolkit(run.base_url, run.auth_token)


def _cloudify_job_config(job_config: dict, job_name: str,
                         staging_dataset: str, pod_settings: dict) -> dict:
    """Rewrite the locally-built config for the pod: remote paths, remote
    trainer type (DB status updates), and the job name the pod's routes key
    on. The staging->pod path swap is done on the JSON text so every field
    referencing the staging dir (folder_path, mask_path) is rewritten at
    once, backslash-escaping included."""
    pod_ds = pod_settings['DATASETS_FOLDER'].rstrip('/') + '/' + job_name
    text = json.dumps(job_config)
    needle = json.dumps(str(staging_dataset))[1:-1]     # JSON-escaped form
    text = text.replace(needle, pod_ds)
    out = json.loads(text)
    conf = out['config']
    conf['name'] = job_name
    proc = conf['process'][0]
    proc['type'] = 'diffusion_trainer'
    proc['training_folder'] = pod_settings['TRAINING_FOLDER']
    proc['device'] = 'cuda:0'
    return out


def _finish(run, status, detail='', error=None, destroy=True):
    destroyed = not run.vast_instance_id
    if destroy and run.vast_instance_id:
        try:
            destroyed = bool(vast_client.destroy_instance(run.vast_instance_id))
            if not destroyed:
                logger.warning('terminate %s returned false; billing may still be active',
                               run.vast_instance_id)
        except Exception as e:
            logger.warning('terminate %s failed: %s', run.vast_instance_id, e)
    if destroy and not destroyed:
        # Cleanup is part of the lifecycle, not a best-effort epilogue.  Keep
        # the run active and billable so budget enforcement and the UI cannot
        # claim that a provider instance has stopped before confirmation.
        _mark_cleanup_pending(run, status, detail, error)
        return False
    # The bearer/Jupyter token only authorizes the ephemeral pod. Once that pod
    # is destroyed, retaining the credential in the long-lived history DB adds
    # exposure without any recovery value.
    _complete_cleanup(run, status, detail, error)
    return True


def _monitor(app, run_id):
    """Full run lifecycle. Runs in a daemon thread; every exit path goes
    through _finish() so the pod cannot be leaked by this thread."""
    with app.app_context():
        run = db.session.get(CloudTrainingRun, run_id)
        if not run:
            _stop_events.pop(int(run_id), None)
            _monitor_threads.pop(int(run_id), None)
            return
        stop_event = _stop_event_for(run_id)
        c = cfg.get('cloud') or {}
        max_seconds = int(c.get('max_runtime_minutes') or 480) * 60
        # The runtime cap must survive restarts: anchor it to the run's durable
        # created_at (backdate the local clock by the run's age), not to this
        # thread's start.
        now = utcnow()
        run_age = max(0.0, (now - (run.created_at or now)).total_seconds())
        cap_anchor = _now() - run_age
        # Whether we ENTER the monitor already owning a pod (app restarted while
        # it was still booting) — captured BEFORE _provision, which sets
        # vast_instance_id on a fresh launch. It decides the boot-readiness
        # anchor below.
        resuming_existing_pod = bool(run.vast_instance_id)
        try:
            # -- heavy launch work, moved off the HTTP path (see launch) ----
            _prepare_staging(run)
            # -- provision (if resuming, the instance may already exist) ----
            if not run.vast_instance_id:
                _provision(run)
            # Boot-readiness timeout anchor. A FRESH launch measures from now
            # (post-provision) so dataset staging / offer search never eat into
            # the pod's boot budget. A RESUME must NOT get a brand-new window on
            # every restart: that let a pod whose UI never answered survive
            # 37 min across two restarts instead of the 15-min READY_TIMEOUT
            # (incident 2026-07-14). On resume we anchor to the DURABLE
            # created_at (cap_anchor), so readiness measures the TOTAL time since
            # launch across every restart — the intended behaviour even for a pod
            # that was honestly still booting.
            boot_started = cap_anchor if resuming_existing_pod else _now()

            # -- wait until the pod's UI answers ----------------------------
            # Readiness is checked BEFORE the elapsed-time read: an
            # already-booted pod (the common case, and every resumed run)
            # must be able to break out on the very first iteration without
            # ever touching _now() -- a test clock that jumps in large
            # strides per call must not misfire this boot-timeout on a pod
            # that was, in fact, instantly ready.
            template_mode = bool((c.get('template_hash') or '').strip())
            ready_timeout = (int(c.get('ready_timeout_minutes') or 0) * 60
                             or READY_TIMEOUT_SECONDS)
            _set(run, phase_detail='Waiting for the pod to boot')
            port = int(c.get('ui_port') or 18675)
            if template_mode and port == 8675:
                # 8675 is the pre-template default that Settings saves may have
                # baked into config.json; the official template only publishes
                # the UI behind the pod proxy on 18675 — a stale 8675 makes the
                # boot-wait spin for its whole budget (observed live 2026-07-12).
                logger.warning('cloud.ui_port=8675 is stale for template mode — using 18675')
                port = 18675
            while True:
                # A transient vast API hiccup is just "not ready yet" -- only
                # READY_TIMEOUT_SECONDS may fail the boot wait, never a single
                # 502 that would destroy a pod about to come up fine.
                try:
                    inst = vast_client.get_instance(run.vast_instance_id)
                except vast_client.VastError as e:
                    logger.warning('boot-wait: vast API hiccup (%s) — retrying', e)
                    inst = None
                # Template launches authenticate with the vast-generated
                # per-instance token (the pod's Caddy proxy accepts it as a
                # Bearer header) — pick it up as soon as the record shows it.
                if inst and not run.auth_token and inst.get('jupyter_token'):
                    _set(run, auth_token=inst['jupyter_token'])
                base = vast_client.derive_base_url(inst, port) if inst else None
                ready = False
                if base:
                    if run.base_url != base:
                        _set(run, base_url=base)
                    ready = _make_remote(run).is_ready()
                    if ready:
                        break
                # Honor "Stop run" DURING boot too — but only on a pod that is
                # NOT ready yet (a ready pod breaks out above and the training
                # loop handles the stop normally). Without this, the boot-wait
                # spun its whole 25-min budget on a dead host while the stop
                # button silently did nothing (observed live 2026-07-13, a
                # 5090 stuck in 'loading'). No job exists yet -> terminate.
                if stop_event.is_set():
                    stop_event.clear()
                    # A user killing a boot this late is almost always a stuck
                    # host — blacklist it like a timeout would. An early stop
                    # (changed their mind) says nothing about the host.
                    if _now() - boot_started > 8 * 60:
                        _blacklist_host(_run_machine_id(run),
                                        'user stopped a boot stuck past 8 min')
                    _finish(run, 'stopped', detail='Stopped by user during boot')
                    return
                # Live telemetry: surface WHERE the boot is stuck (image pull,
                # port publication, UI warm-up) in the UI phase line and the
                # log — runs #3/#4 died blind on 'Waiting for the pod to boot'.
                st = (inst or {}).get('actual_status') or 'not listed yet'
                has_ports = bool(((inst or {}).get('ports') or {}).get(f'{port}/tcp'))
                stage = (f'pod {st}' if not has_ports
                         else 'pod up — waiting for the UI to answer')
                detail = f'Waiting for the pod to boot — {stage}'
                if run.phase_detail != detail:
                    logger.info('boot-wait run %s: status=%s port_%s_published=%s '
                                'base=%s ready=%s', run.id, st, port, has_ports,
                                base or '-', ready)
                    _set(run, phase_detail=detail)
                if _now() - boot_started > ready_timeout:
                    # This host burned the whole boot budget — skip it for the
                    # next few days so a relaunch can't land on it again.
                    _blacklist_host(_run_machine_id(run),
                                    'pod did not become ready in time')
                    raise RuntimeError('pod did not become ready in time')
                _sleep(POLL_SECONDS)

            remote = _make_remote(run)

            # -- resume contract: an already-submitted job (app restarted
            # mid-run) skips settings/upload/create/start entirely and goes
            # straight to polling the existing remote job. ------------------
            if not run.remote_job_id:
                pod_settings = remote.ensure_settings(hf_token=cfg.secret('HF_TOKEN'))

                # -- upload dataset (+ masks folder if present) --------------
                _set(run, status='uploading', phase_detail='Uploading dataset')
                staging_dataset = os.path.join(run.staging_dir, 'dataset')
                remote.upload_dataset(run.job_name, staging_dataset)
                masks_dir = staging_dataset + '_masks'
                if os.path.isdir(masks_dir) and os.listdir(masks_dir):
                    remote.upload_dataset(run.job_name + '_masks', masks_dir)

                # -- build + submit the job -----------------------------------
                # Build from the run's STAMPED family/variant, NEVER the dataset's
                # current train_type/train_variant: a later launch on the same
                # dataset (or a /train-type change) may have moved that row since
                # this run launched, and this rebuild happens minutes later at pod
                # boot. _run_config_dataset presents the run's own launch params
                # so two concurrent multi-family runs each get their own arch
                # (incident 2026-07-14 — see _RunConfigDataset).
                params = json.loads(run.train_params or '{}')
                ds = fds.get_dataset('local', run.dataset_id)
                job_config = lt.build_job_config(
                    _run_config_dataset(ds, params),
                    staging_dataset, steps=params.get('steps') or 3000,
                    training_folder='__POD__')
                job_config = _cloudify_job_config(job_config, run.job_name,
                                                  staging_dataset, pod_settings)
                job_id = remote.create_job(run.job_name, job_config)
                # Continue-in-cloud: drop the source checkpoint into the job's
                # save_root BEFORE start so ai-toolkit auto-resumes from it.
                _seed_resume_checkpoint(run, remote, pod_settings)
                remote.start_job(job_id)
                _set(run, remote_job_id=job_id, status='training',
                     training_started_at=run.training_started_at or utcnow(),
                     phase_detail='Job queued on the pod')
            else:
                job_id = run.remote_job_id
                _set(run, phase_detail='Resuming — reattaching to running job')

            # -- poll until terminal ------------------------------------------
            # Stall watchdog state: armed only once training has produced its
            # first step (before that — base download, quantization, latent
            # caching — the watchdog stays INACTIVE; those phases are covered
            # by ready_timeout + max_runtime).
            stall_seconds = int(c.get('stall_timeout_minutes') or 30) * 60
            last_step = -1
            last_progress_ts = _now()
            last_ok = _now()
            polls = 0
            while True:
                if _now() - cap_anchor > max_seconds:
                    try:
                        remote.stop_job(job_id)
                    except Exception:
                        pass
                    _try_download_checkpoint(run, remote, allow_stale=True)
                    _finish(run, 'stopped',
                            detail='Max runtime reached — pod terminated',
                            error='max runtime cap hit')
                    return
                if stop_event.is_set():
                    stop_event.clear()
                    _set(run, phase_detail='Stopping on user request')
                    try:
                        remote.stop_job(job_id)
                    except Exception:
                        pass
                    _try_download_checkpoint(run, remote, allow_stale=True)
                    _finish(run, 'stopped', detail='Stopped by user')
                    return
                try:
                    job = remote.get_job(job_id)
                    last_ok = _now()
                except Exception as e:
                    if _now() - last_ok > UNREACHABLE_GRACE_SECONDS:
                        raise RuntimeError(f'pod unreachable: {e}')
                    _sleep(POLL_SECONDS)
                    continue

                _pull_log_and_samples(run, remote, job_id)
                # Mid-run checkpoint mirror, throttled (~2 min at 10 s polls):
                # list_files is cheap, but no need to hammer it every poll —
                # the pod only writes a new save every save_every steps.
                polls += 1
                if polls % _CKPT_SYNC_EVERY_POLLS == 0:
                    _sync_latest_checkpoint(run, remote)
                status = job.get('status')
                info = job.get('info') or ''
                _set(run, phase_detail=f"{status}: {info}"[:500])

                if status == 'completed':
                    ok = _try_download_checkpoint(run, remote)
                    if not ok:
                        # A host that cannot DELIVER its result (even through
                        # the resume loop) is a bad host — skip it next time.
                        _blacklist_host(_run_machine_id(run),
                                        'could not serve the final checkpoint')
                        # LoRA > a few minutes of pod time: keep the pod for
                        # manual recovery; max-runtime/reconcile will reap it.
                        _set(run, status='error_pod_kept',
                             error='checkpoint download failed — pod kept, '
                                   f'recover manually at {run.base_url}',
                             finished_at=utcnow())
                        return
                    _download_intermediates(run, remote)
                    _import_result(run)
                    _mirror_into_local_run(run)
                    _finish(run, 'done', detail='Training complete')
                    return
                if status in ('error', 'stopped'):
                    _try_download_checkpoint(run, remote, allow_stale=True)
                    _finish(run, 'error' if status == 'error' else 'stopped',
                            detail=f'Remote job {status}', error=info or status)
                    return
                # -- stall watchdog: guiding rule — NEVER kill a run that
                # progresses. The elif keeps a progressing poll from ever
                # evaluating the stall clock (a coarse test clock jumping in
                # large strides per call must not misfire on a healthy run).
                step = job.get('step') or 0
                if step > last_step:
                    last_step = step
                    last_progress_ts = _now()
                elif last_step > 0 and (_now() - last_progress_ts) > stall_seconds:
                    try:
                        remote.stop_job(job_id)
                    except Exception:
                        pass
                    _try_download_checkpoint(run, remote, allow_stale=True)
                    _finish(run, 'error',
                            detail='Stalled — no step progress for '
                                   f'{stall_seconds // 60} min; pod terminated',
                            error='stall watchdog')
                    return
                _sleep(POLL_SECONDS)
        except Exception as e:
            logger.exception('cloud run %s failed', run_id)
            # A pod that died mid-run is a HOST-quality signal (live
            # 2026-07-13: a krea run lost at ~$0.93 when its pod went
            # unreachable) — skip this machine for the next launches.
            if 'unreachable' in str(e).lower():
                _blacklist_host(_run_machine_id(run), 'pod died mid-run (unreachable)')
            _finish(run, 'error', detail='Run failed', error=str(e)[:500])
        finally:
            # This run's slot in the module maps is done with — drop it so
            # they cannot grow unbounded across the app's lifetime with many
            # concurrent runs coming and going.
            _stop_events.pop(int(run_id), None)
            _monitor_threads.pop(int(run_id), None)
            _sync_state.pop(int(run_id), None)


def _seed_resume_checkpoint(run, remote, pod_settings):
    """Continue-in-cloud: place the source run's harvested checkpoint into THIS
    job's save_root on the pod so ai-toolkit's auto-resume finds it — it globs
    <TRAINING_FOLDER>/<job_name>/<job_name>*.safetensors, takes the newest by
    ctime, and reads the resume step from the safetensors metadata. The file is
    renamed to THIS job's prefix so the glob matches (the save the trainer would
    itself write). No resume checkpoint stamped in train_params -> no-op (a
    normal launch). A missing/failed seed RAISES: a 'continue' that cannot
    resume must fail loudly, never silently train from scratch."""
    src = _run_param(run, 'resume_ckpt_path')
    if not src:
        return
    if not os.path.isfile(src):
        raise RuntimeError(f'resume checkpoint vanished before upload: {src}')
    step = int(_run_param(run, 'resume_step') or 0)
    remote_name = f'{run.job_name}_{step:09d}.safetensors'
    training_folder = pod_settings['TRAINING_FOLDER'].rstrip('/')
    dest_dir = f'{training_folder}/{run.job_name}'
    _set(run, phase_detail='Seeding checkpoint for resume…')
    remote.seed_checkpoint(pod_settings['DATASETS_FOLDER'], dest_dir,
                           remote_name, src)
    logger.info('run %s: seeded resume checkpoint %s -> %s',
                run.id, os.path.basename(src), dest_dir)


def _pull_log_and_samples(run, remote, job_id):
    """Mirror remote log + new samples into staging so cloud_progress reuses
    the exact local parsing/serving machinery. Never raises."""
    try:
        text = remote.get_log(job_id)
        with open(os.path.join(run.staging_dir, 'training.log'), 'w',
                  encoding='utf-8', errors='replace') as fh:
            fh.write(text)
    except Exception as e:
        logger.debug('log mirror failed: %s', e)
    try:
        samples_dir = os.path.join(run.staging_dir, 'samples')
        have = set(os.listdir(samples_dir))
        for remote_path in remote.get_samples(job_id):
            name = os.path.basename(remote_path.replace('\\', '/'))
            if name and name not in have:
                remote.download_sample(remote_path,
                                       os.path.join(samples_dir, name))
    except Exception as e:
        logger.debug('sample mirror failed: %s', e)


def _newest_remote_checkpoint(remote, job_id):
    """The newest .safetensors file entry ({'path', 'size'}), or None.
    ai-toolkit zero-pads step numbers, so lexicographic order IS step order."""
    files = [f for f in remote.list_files(job_id)
             if f.get('path', '').endswith('.safetensors')]
    if not files:
        return None
    return sorted(files, key=lambda f: f['path'])[-1]


def _fetch_checkpoint(run, remote, ckpt, timeout=None, attempts=3) -> str:
    """Download the checkpoint entry ({'path','size'}) into staging and return
    the local path. Skips the transfer when this exact save is already local
    (the mid-run sync usually got there first). Two integrity layers:
    - a KILLED transfer never lands at dest (RemoteAiToolkit._download's own
      .part-then-rename; no second layer here — it produced '.part.part');
    - a TRUNCATED transfer that ends with a clean EOF (observed live
      2026-07-13: pods closing the stream after a few chunks while training)
      is caught by comparing the byte size against list_files' size — a short
      file is deleted and the fetch fails rather than registering garbage."""
    remote_path = ckpt['path']
    name = os.path.basename(remote_path.replace('\\', '/'))
    dest = os.path.join(run.staging_dir, name)
    if run.checkpoint_local_path and os.path.isfile(dest) \
            and os.path.basename(run.checkpoint_local_path) == name:
        return dest
    remote.download_public_file(remote_path, dest, timeout=timeout,
                                expected_size=ckpt.get('size'), attempts=attempts)
    want = int(ckpt.get('size') or 0)
    got = os.path.getsize(dest)
    if want and got != want:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise RuntimeError(f'truncated download of {name}: {got}/{want} bytes')
    return dest


_SYNC_DL_TIMEOUT = 60      # opportunistic pull: fail fast, the loop must not hang
_SYNC_MAX_FAILS = 3        # give up on a save after this; a NEWER save retries
_sync_state = {}           # run_id -> {'name': save filename, 'fails': int}


def _sync_latest_checkpoint(run, remote):
    """Mid-run mirror of the pod's newest SAVE: if the host dies at step 3000
    the local copy of the step-2750 save survives, instead of everything being
    lost because downloads only happened at run end (user-observed gap,
    2026-07-13). Never raises, never flips the run's status. EVERY synced save
    is KEPT (user ask: harvest ALL trained epochs) — the pod prunes its own
    saves to max_step_saves, so grabbing each one as it appears is the only
    way to collect the full epoch history; disk is reclaimed via the 🗑/🧹
    tools and the trash.

    Some pods cannot serve big files WHILE training (observed live: streams
    die after a few chunks) — after _SYNC_MAX_FAILS failed attempts on the
    same save we stop retrying it (a newer save resets the counter), and each
    attempt is capped at _SYNC_DL_TIMEOUT so a trickling stream cannot hold
    the monitor loop — and with it the stop button — for minutes."""
    try:
        ckpt = _newest_remote_checkpoint(remote, run.remote_job_id)
        if not ckpt:
            return
        name = os.path.basename(ckpt['path'].replace('\\', '/'))
        st = _sync_state.get(run.id)
        if st and st.get('name') == name and st.get('fails', 0) >= _SYNC_MAX_FAILS:
            return
        prev = run.checkpoint_local_path
        try:
            dest = _fetch_checkpoint(run, remote, ckpt,
                                     timeout=_SYNC_DL_TIMEOUT)
        except Exception as e:
            st = _sync_state.setdefault(run.id, {'name': name, 'fails': 0})
            if st.get('name') != name:
                st.update(name=name, fails=0)
            st['fails'] += 1
            # First failure at WARNING so it is visible in the log viewer;
            # repeats at DEBUG (the give-up cap bounds them anyway).
            log = logger.warning if st['fails'] == 1 else logger.debug
            log('mid-run checkpoint sync of %s failed (attempt %s/%s): %s',
                name, st['fails'], _SYNC_MAX_FAILS, e)
            return
        _sync_state.pop(run.id, None)
        if dest != prev:
            # checkpoint_local_path tracks the NEWEST save; earlier synced
            # saves stay on disk (full epoch harvest).
            _set(run, checkpoint_local_path=dest)
    except Exception as e:
        logger.debug('mid-run checkpoint sync failed: %s', e)


def _try_download_checkpoint(run, remote, allow_stale=False) -> bool:
    """Download the newest .safetensors into staging. False on failure.
    allow_stale (rescue paths — stop/stall/cap): when the pod can't serve the
    newest save anymore, an already-synced OLDER save still counts as success.
    The COMPLETION path must stay strict (allow_stale=False): falling back to
    an older save there would silently discard the final training steps —
    error_pod_kept keeps the pod so the user can recover the real result."""
    try:
        ckpt = _newest_remote_checkpoint(remote, run.remote_job_id)
        if ckpt:
            # Large attempts budget: a sick-proxy host cutting the stream
            # every ~0.5-2 MB still delivers an 85 MB file via ~100 resumed
            # connections (validated live 2026-07-13, run #7's manual rescue).
            dest = _fetch_checkpoint(run, remote, ckpt, attempts=400)
            _set(run, status='downloading', checkpoint_local_path=dest,
                 phase_detail=f'Downloaded {os.path.basename(dest)}')
            return True
    except Exception as e:
        logger.warning('checkpoint download failed: %s', e)
    return bool(allow_stale and run.checkpoint_local_path
                and os.path.isfile(run.checkpoint_local_path))


def _import_result(run):
    """Copy the downloaded checkpoint into the ComfyUI loras folder when one
    is configured; otherwise it stays in staging (served by the download
    route). Import failure must not fail the run."""
    try:
        if not run.checkpoint_local_path:
            return
        if not (cfg.get('comfyui.base_dir') or cfg.get('comfyui.loras_dir')):
            return
        params = json.loads(run.train_params or '{}')
        lt.import_checkpoint('local', run.dataset_id,
                             os.path.basename(run.checkpoint_local_path),
                             family=params.get('train_type'),
                             src_dir=run.staging_dir,
                             version=params.get('version'))
    except Exception as e:
        logger.warning('cloud import into ComfyUI failed: %s', e)


def _download_intermediates(run, remote):
    """After the FINAL checkpoint landed (strict path), also pull the pod's
    remaining intermediate saves — WITHOUT them a cloud run offered only its
    last epoch while a local run offers max_step_saves of them to pick the
    least-overfit one (user-observed parity gap, 2026-07-13). Best-effort per
    file: a failed intermediate never degrades the run's outcome."""
    try:
        files = [f for f in remote.list_files(run.remote_job_id)
                 if f.get('path', '').endswith('.safetensors')]
    except Exception as e:
        logger.warning('intermediate listing failed: %s', e)
        return
    have = os.path.basename(run.checkpoint_local_path or '')
    for f in files:
        name = os.path.basename(f['path'].replace('\\', '/'))
        if name == have:
            continue
        dest = os.path.join(run.staging_dir, name)
        want = int(f.get('size') or 0)
        try:
            if os.path.isfile(dest) and (not want or os.path.getsize(dest) == want):
                continue
            remote.download_public_file(f['path'], dest,
                                        expected_size=want or None, attempts=50)
        except Exception as e:
            logger.warning('intermediate %s not retrieved: %s', name, e)


def _mirror_into_local_run(run):
    """Copy the downloaded cloud checkpoints (final + retrieved intermediates)
    into the LOCAL ai-toolkit run dir, renamed to the local convention
    (`lora_<trigger>[_<step>].safetensors`), so cloud results behave exactly
    like local ones everywhere downstream: the panel's checkpoint list, the
    Resume-or-Fresh prompt, Continue training. No-op when ai-toolkit isn't
    configured locally; best-effort, never fails the run."""
    try:
        if not run.staging_dir or not os.path.isdir(run.staging_dir):
            return
        params = json.loads(run.train_params or '{}')
        # cloud trains on the OFFICIAL base only -> base_model=''
        run_dir = lt._run_dir('local', run.dataset_id, base_model='',
                              family=params.get('train_type'))
        os.makedirs(run_dir, exist_ok=True)
        base = os.path.basename(os.path.normpath(run_dir))     # lora_<trigger>
        for src_name in sorted(os.listdir(run.staging_dir)):
            if not src_name.lower().endswith('.safetensors'):
                continue
            _mirror_one(run, run_dir, base, src_name)
    except Exception as e:
        # RuntimeError from _run_dir = ai-toolkit not configured -> fine
        logger.debug('local run-dir mirror skipped: %s', e)


def _mirror_one(run, run_dir, base, src_name):
    try:
        m = re.search(r'_(\d{6,})\.safetensors$', src_name)
        dest_name = f'{base}_{m.group(1)}.safetensors' if m else f'{base}.safetensors'
        dest = os.path.join(run_dir, dest_name)
        if os.path.exists(dest):
            # A LOCAL run of the same dataset+family already produced this
            # exact name (the unsuffixed FINAL collides whenever both worlds
            # completed a run) — never clobber local work. The cloud result
            # stays available in staging, ComfyUI and the hub's ⬇ button.
            logger.warning('local run dir already has %s — cloud mirror skipped '
                           '(local checkpoint left untouched)', dest_name)
            return
        shutil.copy2(os.path.join(run.staging_dir, src_name), dest)
        logger.info('mirrored cloud checkpoint into local run dir: %s/%s',
                    run_dir, dest_name)
    except (OSError, re.error) as e:
        logger.warning('mirror of %s skipped: %s', src_name, e)


def _billing_window(run):
    """Return the best-known provider billing window for a run.

    New rows record the exact instance registration/destruction timestamps.
    Completed rows created before those columns existed only have
    ``created_at``/``finished_at``; treating their missing billing end as an
    active pod would make their displayed and monthly cost grow forever.  The
    recovery state is deliberately excluded because its pod is still alive.
    """
    start = run.billing_started_at or run.created_at
    # A provider id without a confirmed billing end is live regardless of the
    # local terminal label.  This also repairs cost reporting for rows written
    # by older versions after a failed one-shot destroy.
    provider_may_be_live = bool(run.vast_instance_id and not run.billing_ended_at)
    legacy_terminal_end = (run.finished_at
                           if not provider_may_be_live
                           and run.status != 'error_pod_kept' else None)
    end = run.billing_ended_at or legacy_terminal_end or utcnow()
    final = bool(run.billing_ended_at or legacy_terminal_end)
    return start, end, final


def _cost_estimate(run) -> float:
    if not run.price_per_hour:
        return 0.0
    start, end, _final = _billing_window(run)
    if not start:
        return 0.0
    hours = max(0.0, (end - start).total_seconds() / 3600.0)
    return round(run.price_per_hour * hours, 2)


def month_spend_usd() -> float:
    """Total cost of the runs STARTED since the 1st of the current month
    (UTC). A run's cost = price_per_hour x (finished_at or now - created_at);
    runs that never got a priced pod (price_per_hour NULL) count for $0."""
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    for r in CloudTrainingRun.query.all():
        start, end, _final = _billing_window(r)
        if not r.price_per_hour or not start:
            continue
        # Charge only the overlap with the current UTC month. A pod crossing
        # midnight on day one still contributes its post-boundary runtime.
        bill_start = max(start, month_start)
        bill_end = min(end, now)
        total += r.price_per_hour * max(
            0.0, (bill_end - bill_start).total_seconds() / 3600.0)
    return total


def _dataset_name(dataset_id):
    """Human-readable dataset name for the cloud-runs hub — the run only stores
    dataset_id. Best-effort: a since-deleted dataset yields None, never a crash."""
    try:
        from ..models import FaceDataset
        ds = db.session.get(FaceDataset, dataset_id)
        return ds.name if ds is not None else None
    except Exception:
        return None


def _run_payload(run) -> dict:
    now = utcnow()
    billing_start, billing_end, cost_final = _billing_window(run)
    billing_seconds = (max(0, int((billing_end - billing_start).total_seconds()))
                       if billing_start else None)
    training_end = run.finished_at or now
    training_seconds = (max(0, int((training_end - run.training_started_at).total_seconds()))
                        if run.training_started_at else None)
    return {'run_id': run.id, 'dataset_id': run.dataset_id, 'status': run.status,
            # Stable id for the per-run "Share configuration" download. Every
            # cloud row (active/finished/legacy) addresses by its pod row id;
            # local rows use 'rec-<record id>' (set in all_runs).
            'share_key': f'cloud-{run.id}',
            'run_name': run.run_name, 'dataset_name': _dataset_name(run.dataset_id),
            'vast_instance_id': run.vast_instance_id,   # for the per-run "console ↗" tooltip
            'phase_detail': run.phase_detail, 'gpu': run.gpu_name,
            'price_per_hour': run.price_per_hour,
            'cost_estimate': _cost_estimate(run), 'cost_usd': _cost_estimate(run),
            'cost_final': cost_final,
            'estimated_minutes': run.estimated_minutes,
            'estimated_cost_usd': run.estimated_cost_usd,
            'billing_seconds': billing_seconds, 'training_seconds': training_seconds,
            'billing_started_at': (run.billing_started_at.isoformat()
                                   if run.billing_started_at else None),
            'billing_ended_at': (run.billing_ended_at.isoformat()
                                 if run.billing_ended_at else None),
            'training_started_at': (run.training_started_at.isoformat()
                                    if run.training_started_at else None),
            'error': run.error,
            # isfile, not just a stored path: the user may delete staging
            # files by hand (Explorer) — a ready flag pointing at a missing
            # file yields a download button that 404s.
            'checkpoint_ready': bool(run.checkpoint_local_path
                                     and os.path.isfile(run.checkpoint_local_path)),
            'train_type': _run_family(run),
            'version': _run_param(run, 'version'),
            'created_at': run.created_at.isoformat() if run.created_at else None,
            'finished_at': run.finished_at.isoformat() if run.finished_at else None}


def cloud_status() -> dict:
    actives = get_active_runs()
    c = cfg.get('cloud') or {}
    limit = max(1, int((c.get('max_concurrent_runs') or 1)))
    last = (CloudTrainingRun.query
            .order_by(CloudTrainingRun.id.desc()).first())
    return {'configured': bool(cfg.secret('VAST_API_KEY')), 'limit': limit,
            'actives': [_run_payload(r) for r in actives],
            # compat: single 'active' field for old frontend/tests, first of actives
            'active': _run_payload(actives[0]) if actives else None,
            'total_price_per_hour': round(sum(r.price_per_hour or 0 for r in actives), 4),
            # budget guardrails: what this month already cost, the configured
            # ceiling (0 = unlimited), and the runtime cap the frontend uses
            # for its worst-case cost estimate.
            'month_spend': round(month_spend_usd(), 2),
            'monthly_budget': float(c.get('monthly_budget_usd') or 0),
            'max_runtime_minutes': int(c.get('max_runtime_minutes') or 480),
            'last': _run_payload(last) if last else None}


def all_runs(limit: int = 20) -> dict:
    """Everything the unified Runs hub needs in one call: the active cloud
    runs (manage/watch), the LIVE local training if any, and a history of
    EVERY launch — local AND cloud — from the provenance registry (each row
    carries the settings snapshot the launch actually sent to ai-toolkit).
    Cloud rows are enriched from their CloudTrainingRun (status/cost/
    checkpoint); cloud runs that predate the registry still appear via a
    fallback union, so history never shrinks."""
    from ..models import TrainingRunRecord
    from . import lora_test_studio as lts
    actives = get_active_runs()
    c = cfg.get('cloud') or {}
    limit = max(1, min(int(limit or 20), 100))
    recs = (TrainingRunRecord.query
            .order_by(TrainingRunRecord.id.desc()).limit(limit).all())
    feedback_by_record = lts.feedback_for_records(recs)
    cloud_ids = {r.cloud_run_id for r in recs if r.cloud_run_id}
    cloud_by_id = ({r.id: r for r in CloudTrainingRun.query
                    .filter(CloudTrainingRun.id.in_(cloud_ids)).all()}
                   if cloud_ids else {})
    recent = []
    for rec in recs:
        crun = cloud_by_id.get(rec.cloud_run_id)
        if crun is not None and crun.status in ACTIVE_STATES:
            continue                      # already shown in the actives section
        try:
            settings = json.loads(rec.settings) if rec.settings else None
        except ValueError:
            settings = None
        try:
            preflight = json.loads(rec.preflight) if rec.preflight else None
        except (TypeError, ValueError):
            preflight = None
        try:
            overrides = json.loads(rec.overrides) if rec.overrides else None
        except (TypeError, ValueError):
            overrides = None
        row = {'source': 'cloud' if rec.source == 'cloud' else 'local',
               'record_id': rec.id,
               'dataset_id': rec.dataset_id,
               'dataset_name': _dataset_name(rec.dataset_id),
               'train_type': rec.family, 'version': rec.version,
               'fingerprint': rec.fingerprint,
               'steps': rec.steps, 'masked': bool(rec.masked),
               'variant': rec.variant, 'base_model': rec.base_model or '',
               'settings': settings, 'preflight': preflight,
               'overrides': overrides,
               'evaluation': feedback_by_record.get(rec.id),
               # local rows live only in the registry -> addressed by record id;
               # a cloud row overrides this with 'cloud-<id>' via _run_payload.
               'share_key': f'rec-{rec.id}',
               'created_at': rec.created_at.isoformat() if rec.created_at else None}
        if crun is not None:
            # cloud enrichment wins on shared keys (status/cost/checkpoint/...)
            row.update(_run_payload(crun))
            row['settings'] = settings
            row['preflight'] = preflight
            row['overrides'] = overrides
            row['source'] = 'cloud'
        recent.append(row)
    # Legacy cloud runs that predate the provenance registry (no record row).
    seen_cloud = {r.get('run_id') for r in recent if r.get('run_id')}
    for crun in (CloudTrainingRun.query
                 .filter(CloudTrainingRun.status.notin_(ACTIVE_STATES))
                 .order_by(CloudTrainingRun.id.desc()).limit(limit).all()):
        if crun.id in seen_cloud:
            continue
        recent.append({'source': 'cloud', 'settings': None,
                       'preflight': None, 'overrides': None,
                       **_run_payload(crun)})
    recent.sort(key=lambda r: r.get('created_at') or '', reverse=True)
    recent = recent[:limit]
    # Live LOCAL training: shown as its own card next to the cloud actives;
    # its freshly-registered history row is dropped to avoid the double.
    local = lt.training_status()
    local_active = local if local.get('in_progress') else None
    if local_active and (local.get('current') or {}).get('dataset_id') is not None:
        cur_ds = local['current']['dataset_id']
        for i, r in enumerate(recent):
            if r['source'] == 'local' and r['dataset_id'] == cur_ds:
                # its freshly-registered history row is dropped to avoid the
                # double — carry its share_key onto the live card so it too can
                # produce a "Share configuration" file.
                local_active['share_key'] = recent.pop(i).get('share_key')
                local_active['record_id'] = r.get('record_id')
                local_active['evaluation'] = r.get('evaluation')
                break
    # Active cloud rows are omitted from ``recent`` above. Enrich their live
    # payloads with the immutable admission record as well, so provenance does
    # not disappear while a run is still provisioning/training.
    active_payloads = [_run_payload(r) for r in actives]
    if actives:
        active_ids = [r.id for r in actives]
        admission_by_cloud = {}
        for rec in (TrainingRunRecord.query
                    .filter(TrainingRunRecord.cloud_run_id.in_(active_ids))
                    .order_by(TrainingRunRecord.id.desc()).all()):
            admission_by_cloud.setdefault(rec.cloud_run_id, rec)
        active_feedback = lts.feedback_for_records(admission_by_cloud.values())
        for payload in active_payloads:
            rec = admission_by_cloud.get(payload.get('run_id'))
            for key in ('preflight', 'overrides'):
                value = getattr(rec, key, None) if rec is not None else None
                try:
                    payload[key] = json.loads(value) if value else None
                except (TypeError, ValueError):
                    payload[key] = None
            payload['record_id'] = rec.id if rec is not None else None
            payload['evaluation'] = (
                active_feedback.get(rec.id) if rec is not None else None)
    return {'configured': bool(cfg.secret('VAST_API_KEY')),
            'limit': max(1, int((c.get('max_concurrent_runs') or 1))),
            'actives': active_payloads,
            'local_active': local_active,
            'recent': recent,
            'total_price_per_hour': round(sum(r.price_per_hour or 0 for r in actives), 4),
            'month_spend': round(month_spend_usd(), 2),
            'monthly_budget': float(c.get('monthly_budget_usd') or 0)}


def gpu_tiers(user_id, dataset_id, train_type=None, steps=None) -> dict:
    """Live vast.ai offers for THIS dataset+family, grouped by GPU class
    (cheapest offer per class), ranked slowest -> fastest, each annotated with
    an approximate training time and total run cost. Read-only: rents nothing.
    The launch then re-searches and rents the cheapest live offer of the chosen
    class. Raises the same guards as launch (no key / dataset / SDXL)."""
    if not cfg.secret('VAST_API_KEY'):
        raise RuntimeError('vast.ai API key is not configured — add it in Settings')
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    fam = fds.normalize_train_type(train_type or getattr(ds, 'train_type', None))
    if fam == 'sdxl':
        raise ValueError('SDXL training needs a local base checkpoint — '
                         'cloud training supports Z-Image, Krea and FLUX.2 Klein')
    # flux2klein passe (cf. launch_cloud_training) — seul flux reste local-only.
    if fam == 'flux':
        raise ValueError('FLUX.1 training is local-only for now — '
                         'cloud training supports Z-Image, Krea and FLUX.2 Klein')
    n_steps = int(steps) if steps else lt.default_steps(ds)
    c = cfg.get('cloud') or {}
    min_vram = (c.get('min_vram_gb') or {}).get(fam, 24)
    price_cap = c.get('max_price_per_hour', 0.80)
    overhead_min = float(c.get('pod_overhead_minutes') or 0)
    # A wider scan than the launch default so several GPU classes surface (the
    # user is choosing between them, not taking the single cheapest). Same
    # quality filters as the launch so the shown tiers match what gets rented.
    offers = _filter_offers(vast_client.search_offers(
        min_vram_gb=min_vram, max_dph=price_cap,
        limit=int(c.get('offer_scan_limit') or 100),
        min_inet_down_mbps=int(c.get('min_inet_down_mbps') or 0),
        min_reliability=float(c.get('min_reliability') or 0.98),
        min_disk_bw_mbps=int(c.get('min_disk_bw_mbps') or 0)))
    cheapest_by_gpu = {}
    for o in offers:
        name = o.get('gpu_name') or 'GPU'
        cur = cheapest_by_gpu.get(name)
        dph = o.get('dph_total')
        if cur is None or (dph is not None and (cur.get('dph_total') is None
                           or dph < cur['dph_total'])):
            cheapest_by_gpu[name] = o
    max_runtime = int(c.get('max_runtime_minutes') or 480)
    tiers = []
    for name, o in cheapest_by_gpu.items():
        dph = o.get('dph_total')
        est_min = gpu_speed.estimate_minutes(name, fam, n_steps)
        # Cost bills the whole pod life: training + boot/download/quantize.
        est_cost = (round(dph * (est_min + overhead_min) / 60.0, 2)
                    if dph is not None else None)
        tiers.append({
            'gpu_name': name, 'offer_id': o.get('offer_id'),
            'dph_total': round(dph, 4) if dph is not None else None,
            'gpu_ram_gb': o.get('gpu_ram_gb'),
            'speed': round(gpu_speed.speed_factor(name), 2),
            'est_minutes': int(round(est_min)), 'est_cost': est_cost,
            # A tier slower than the runtime cap would be KILLED mid-training
            # (checkpoint rescued, but steps lost) — warn at pick time.
            'exceeds_cap': (est_min + overhead_min) > max_runtime,
        })
    # slowest -> fastest (matches the launch dialog); ties broken by price.
    tiers.sort(key=lambda t: (t['speed'], t['dph_total']
                              if t['dph_total'] is not None else 9e9))
    return {'tiers': tiers, 'steps': n_steps, 'family': fam,
            'max_price_per_hour': price_cap,
            'max_runtime_minutes': max_runtime}


def cloud_checkpoints(dataset_id, train_type=None) -> list:
    """Locally-synced cloud checkpoints of this dataset (+family filter),
    newest run first, step-sorted within a run — ALL the saves retrieved for a
    finished run (final + intermediates, local parity: pick the least-overfit
    epoch), and an in-progress run's latest synced save. Only files that
    actually exist are listed (hand-deleting in Explorer must not 404)."""
    fam = fds.normalize_train_type(train_type) if train_type else None
    out = []
    for run in (CloudTrainingRun.query.filter_by(dataset_id=dataset_id)
                .order_by(CloudTrainingRun.id.desc()).all()):
        if fam and (_run_family(run) or fam) != fam:
            continue
        if not run.staging_dir or not os.path.isdir(run.staging_dir):
            continue
        entries = []
        for name in os.listdir(run.staging_dir):
            if not name.lower().endswith('.safetensors'):
                continue
            m = re.search(r'_(\d{6,})\.safetensors$', name)
            step = int(m.group(1)) if m else int(_run_param(run, 'steps') or 0)
            entries.append({'filename': name, 'step': step, 'cloud': True,
                            'run_id': run.id, 'version': _run_param(run, 'version'),
                            'final': bool(not m and run.status == 'done'),
                            'active': run.status in ACTIVE_STATES,
                            'trained_at': run.created_at.isoformat()
                                          if run.created_at else None})
        entries.sort(key=lambda e: (e['step'], e['final']))
        out.extend(entries)
    return out


def delete_cloud_checkpoint(dataset_id, run_id, filename) -> str:
    """Move a cloud run's synced checkpoint to the trash. The run must belong
    to the dataset and be TERMINAL (deleting an active run's save is pointless
    — the sync re-downloads it). Clears checkpoint_local_path when it pointed
    at the trashed file."""
    run = db.session.get(CloudTrainingRun, int(run_id))
    if (not run or run.dataset_id != int(dataset_id) or not run.staging_dir
            or not os.path.isdir(run.staging_dir)):
        raise ValueError('unknown cloud run')
    if run.status in ACTIVE_STATES:
        raise ValueError('this cloud run is still active — its save would just '
                         'be re-synced; stop the run first')
    allowed = {f for f in os.listdir(run.staging_dir)
               if f.lower().endswith('.safetensors')}
    if filename not in allowed:
        raise ValueError('unknown checkpoint')
    from . import trash
    trash.send_to_trash(os.path.join(run.staging_dir, filename),
                        context=f'cloudckpt_run{run.id}')
    if run.checkpoint_local_path \
            and os.path.basename(run.checkpoint_local_path) == filename:
        _set(run, checkpoint_local_path=None)
    return filename


def purge_finished_runs() -> dict:
    """Hub 'Clean finished runs': move the staging dirs of TERMINAL runs to the
    trash — dataset copies, samples and checkpoint duplicates of results that
    are already imported/mirrored. Active runs and error_pod_kept (manual
    recovery may still be under way) are spared. DB rows stay (history)."""
    from . import trash
    purged = 0
    moved = 0
    for run in CloudTrainingRun.query.all():
        if run.status in ACTIVE_STATES or run.status == 'error_pod_kept':
            continue
        sd = run.staging_dir
        if not sd or not os.path.isdir(sd):
            continue
        try:
            size = lt._dir_size(sd)
            trash.send_to_trash(sd, context=f'staging_run{run.id}')
            moved += size
            purged += 1
            if run.checkpoint_local_path:
                _set(run, checkpoint_local_path=None)
        except (OSError, ValueError) as e:
            logger.warning('purge: could not trash %s: %s', sd, e)
    # Trash is on the same data volume, so this operation organizes bytes but
    # does not free disk. Only Empty Trash may report actual freed bytes.
    return {'purged_runs': purged, 'moved_bytes': moved, 'freed_bytes': 0}


def cloud_progress(user_id, dataset_id, train_type=None) -> dict:
    """Same shape as lt.training_progress + cloud phase/cost fields, built
    from the staging mirror (log + samples) written by the monitor. With
    train_type, reads THAT family's newest run (several families may train
    the same dataset in parallel)."""
    run = latest_run_for(dataset_id, train_type)
    empty = {'step': None, 'total': None, 'loss': None, 'speed': None,
             'eta': None, 'loss_curve': []}
    if not run:
        return {'active': False, 'log_exists': False, **empty, 'samples': [],
                'phase': None, 'phase_detail': None, 'cost_estimate': 0.0,
                'gpu': None, 'price_per_hour': None, 'checkpoint_ready': False}
    log_path = os.path.join(run.staging_dir or '', 'training.log')
    parsed = dict(empty)
    log_exists = bool(run.staging_dir) and os.path.isfile(log_path)
    if log_exists:
        try:
            with open(log_path, encoding='utf-8', errors='replace') as fh:
                parsed.update(lt._parse_training_log(fh.read()))
        except OSError:
            pass
    samples = []
    samples_dir = os.path.join(run.staging_dir or '', 'samples')
    if os.path.isdir(samples_dir):
        for f in os.listdir(samples_dir):
            m = lt._SAMPLE_RE.search(f)
            if m:
                samples.append({'filename': f, 'step': int(m.group(1)),
                                'prompt_idx': int(m.group(2))})
        samples.sort(key=lambda s: s['step'], reverse=True)
    return {'active': run.status in ACTIVE_STATES, 'log_exists': log_exists,
            **parsed, 'samples': samples, **_run_payload(run),
            'phase': run.status}
