"""Local trainer process preparation, launch, continuation, and teardown."""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

from ..job_queue import queue_manager
from ..models import FaceDataset
from . import face_dataset_service as fds
from . import lora_training as training
from .training_jobs import EffectiveTrainingJob
from .lora_training import (
    MIN_FREE_GB_TRAIN, _PERSISTED,
    _TRAINING_GPU_LEASE_TTL, _TRAIN_LAUNCH_LOCK, _aitoolkit_dir, _aitoolkit_supports_flux2klein, _aitoolkit_supports_krea,
    _datasets_dir, _default_variant_for, _effective_vae_te, _hf_home,
    _is_custom_weights,
    _jobs_dir, _mask_fields, _masks_dir,
    _output_dir, _run_name, _safe_trigger,
    _sdxl_base_choices, _train_type, _valid_variants_for, _venv_python,
    export_registry_manifest, find_run_collision, is_installed,
    launch_settings_snapshot, preflight_custom_paths,
    write_job_config,
)

logger = logging.getLogger(__name__)

def free_disk_gb(path) -> float | None:
    """Free space (GB) on the drive holding `path` (climbs to the nearest existing
    parent — the target dir may not exist yet). None if it can't be determined
    (never blocks on a stat failure)."""
    try:
        p = os.path.abspath(str(path))
        while p and not os.path.exists(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return None


def assert_free_disk(path, min_gb, what) -> None:
    """Raise ValueError when the drive holding `path` has under `min_gb` GB free."""
    free = free_disk_gb(path)
    if free is not None and free < min_gb:
        raise ValueError(
            f'not enough disk space for {what}: {free:.1f} GB free on the target drive, '
            f'~{min_gb} GB needed - free up space and retry')


def _log_tail(path: str, n: int = 120) -> str:
    """Dernières `n` lignes d'un fichier log (pour remonter une erreur ai-toolkit)."""
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return ''.join(fh.readlines()[-n:]).strip()
    except OSError:
        return '(log illisible)'


def _watch_training(app, proc, log_path, dataset_id) -> None:
    """Thread daemon : attend la fin du process ai-toolkit puis fait avancer la
    file (libère ComfyUI / lance le suivant) DÈS la fin, sans dépendre du polling
    client. Sur un crash (rc≠0), remonte la fin du log. process_training_queue()
    reste le filet de secours si Flask redémarre (le watcher meurt, le flag est
    rattrapé au prochain poll ou à l'expiration du TTL)."""
    try:
        proc.wait()
        rc = proc.returncode
    except Exception:
        return
    try:
        with app.app_context():
            if rc not in (0, None):
                tail = _log_tail(log_path)
                logger.error("Entraînement ai-toolkit dataset %s terminé en ERREUR (rc=%s). "
                             "Fin du log :\n%s", dataset_id, rc, tail)
                # Surface l'erreur à l'UI (sinon un crash = juste « terminé » silencieux).
                queue_manager._set_system_state(
                    'training_error', {'dataset_id': dataset_id, 'rc': rc, 'log_tail': tail},
                    ttl_seconds=3600)
            else:
                logger.info("Entraînement ai-toolkit dataset %s terminé (rc=%s).", dataset_id, rc)
            training.process_training_queue()  # libère le GPU / enchaîne la file immédiatement
    except Exception as e:
        logger.warning("watcher training : post-traitement échoué : %s", e)


def archive_previous_run(ds) -> str | None:
    """Écarte le dossier du run existant (rename en `*_archived_<horodatage>`,
    jamais de suppression) pour que le prochain lancement reparte de ZÉRO au lieu
    de l'auto-resume ai-toolkit — le cas « j'ai remanié le dataset, je veux un
    LoRA neuf ». Les checkpoints archivés restent sur disque (récupérables à la
    main) et restent éligibles au nettoyage explicite et récupérable : le nom
    conserve la frontière de trigger que purge_training_artifacts balaie. Les copies déjà importées
    dans ComfyUI (loras/<famille>) ne sont pas touchées. None si aucun run."""
    run_dir = _output_dir() / _run_name(ds)
    if not run_dir.is_dir():
        return None
    dest = f'{run_dir}_archived_{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}'
    try:
        os.rename(run_dir, dest)
    except OSError as e:
        # Dossier verrouillé (ex. antivirus, explorateur ouvert) → message actionnable.
        raise ValueError(f'could not archive the previous run ({e}) - close anything '
                         f'using "{run_dir}" and retry')
    logger.info('fresh training: previous run archived -> %s', dest)
    return dest


def _discard_failed_launch_record(record) -> None:
    if record is None:
        return
    try:
        fds.db.session.delete(record)
        fds.db.session.commit()
    except Exception:
        fds.db.session.rollback()
        logger.exception('could not remove provenance row for a launch that never started')


def _clear_failed_training_state() -> None:
    lease_token = queue_manager._get_system_state('training_gpu_lease', None)
    if lease_token:
        try:
            queue_manager._release_gpu_lease(lease_token)
        except Exception:
            logger.exception('could not release failed training GPU lease')
    for key in ('training_in_progress', 'training_pid', 'training_dataset_id',
                'training_target_step', 'training_log_path',
                'training_checkpoint_dir', 'training_trigger',
                'training_gpu_lease', 'training_launch'):
        try:
            queue_manager._set_system_state(key, False if key == 'training_in_progress' else None,
                                            ttl_seconds=None)
        except Exception:
            logger.exception('could not clear failed training state %s', key)


def _restore_fresh_archive(ds, archived: str | None) -> None:
    """Put the previous run back if a fresh launch fails before a process exists."""
    if not archived:
        return
    archived_path = Path(archived)
    run_dir = _output_dir() / _run_name(ds)
    try:
        if run_dir.exists():
            from . import trash
            trash.send_paths_to_trash(
                [run_dir], context=f'failed-fresh-training-{ds.id}', metadata={
                    'kind': 'failed_training_launch',
                    'dataset_id': ds.id,
                    'label': f'Failed fresh training launch for dataset {ds.id}',
                })
        os.rename(archived_path, run_dir)
    except Exception:
        logger.exception('could not restore previous run after failed fresh launch: %s',
                         archived)


def _restore_previous_training_log(log_path: str | None,
                                   previous_log: Path | None) -> None:
    """Undo log rotation when a resume fails before the trainer process exists."""
    if previous_log is None:
        return
    current = Path(log_path) if log_path else None
    try:
        if current is not None and current.exists():
            from . import trash
            trash.send_paths_to_trash(
                [current], context='failed-training-log', metadata={
                    'kind': 'failed_training_launch',
                    'label': 'Failed training launch log',
                })
        os.rename(previous_log, current)
    except Exception:
        logger.exception('could not restore previous training log %s', previous_log)


def _trash_failed_launch_inputs(config_path: str | None,
                                dataset_folder: str | Path | None) -> None:
    """Retain prepared config/dataset artifacts without leaving live orphans."""
    try:
        jobs_root = _jobs_dir().resolve()
        datasets_root = _datasets_dir().resolve()
        candidates = []
        if config_path:
            candidates.append(Path(config_path))
        if dataset_folder:
            candidates.extend([
                Path(dataset_folder), Path(_masks_dir(str(dataset_folder))),
            ])
        safe = []
        for candidate in candidates:
            if not candidate.exists() or candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if (resolved.is_relative_to(jobs_root)
                    or resolved.is_relative_to(datasets_root)):
                safe.append(candidate)
        if safe:
            from . import trash
            trash.send_paths_to_trash(
                safe, context='failed-training-inputs', metadata={
                    'kind': 'failed_training_launch',
                    'label': 'Prepared inputs for a training launch that did not start',
                })
    except Exception:
        logger.exception('could not retain prepared inputs for failed training launch')


def launch_training(user_id, dataset_id, steps: int | None = None, check_captions: bool = True,
                    base_model=None, variant: str | None = None, train_type: str | None = None,
                    allow_caption_mismatch: bool = False, masked: bool = True,
                    fresh: bool = False, allow_uncaptioned: bool = False,
                    vae_path=_PERSISTED, te_path=_PERSISTED,
                    allow_unverified_weights: bool = False) -> dict:
    job = EffectiveTrainingJob(
        user_id=user_id, dataset_id=dataset_id, steps=steps,
        check_captions=check_captions, base_model=base_model, variant=variant,
        train_type=train_type, allow_caption_mismatch=allow_caption_mismatch,
        masked=masked, fresh=fresh, allow_uncaptioned=allow_uncaptioned,
        vae_path=vae_path, te_path=te_path,
        allow_unverified_weights=allow_unverified_weights)
    with _TRAIN_LAUNCH_LOCK:
        return training._launch_training(**job.launch_kwargs())


def _launch_training(user_id, dataset_id, steps: int | None = None,
                     check_captions: bool = True, base_model=None,
                     variant: str | None = None, train_type: str | None = None,
                     allow_caption_mismatch: bool = False, masked: bool = True,
                     fresh: bool = False, allow_uncaptioned: bool = False,
                     vae_path=_PERSISTED, te_path=_PERSISTED,
                     allow_unverified_weights: bool = False) -> dict:
    """Export + config + pause ComfyUI (flag) + lance l'entraînement ai-toolkit
    en CLI headless (`run.py <config>`).

    ``steps`` = step cible (None → calculé par recommended_steps selon le nombre
    d'images). ai-toolkit reprend AUTOMATIQUEMENT depuis le dernier checkpoint
    présent dans le training_folder (get_latest_save_path), donc relancer avec un
    steps > dernier_step continue l'entraînement. ``fresh=True`` écarte d'abord le
    run existant (archive_previous_run) → repart de zéro sur le dataset actuel.

    Retourne {pid, config_path, log_path}. Raises RuntimeError if ai-toolkit isn't
    installed/configured (route maps this to 409, not 400 - it's a backend
    availability problem, not a bad request)."""
    if not is_installed():
        raise RuntimeError('ai-toolkit is not configured')
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    # Reject invalid request combinations before environment/model-access gates,
    # so the webpage names the user's actual mistake instead of an unrelated
    # Hugging Face blocker that would only matter for a valid launch.
    launch_fam = _train_type(ds, train_type)
    eff_vae, eff_te = _effective_vae_te(ds, launch_fam, vae_path, te_path)
    # Disque plein à mi-run = checkpoints corrompus ; refuser AVANT d'exporter.
    assert_free_disk(_output_dir(), MIN_FREE_GB_TRAIN, 'a training run')
    # Garde-fou anti double-lancement : un entraînement DÉJÀ vivant (flag levé +
    # pid en vie) → refuser. Deux process sur le même GPU/dossier corrompent
    # l'optimizer partagé (incident Test/Test 2). Un pid mort avec flag encore
    # levé (avance de file) passe : on ne bloque que sur un process réellement vivant.
    if (queue_manager._get_system_state('training_in_progress', False)
            and training._owned_training_process_alive(
                queue_manager._get_system_state('training_pid', None))):
        raise ValueError('a training is already in progress - wait for it to finish or queue this dataset')
    # One authoritative admission gate for every launch. ``check_captions`` is
    # retained for continuation/internal callers, but it now skips only caption
    # rules; hard preflight blockers (family floor, unresolved double-admission)
    # can no longer be bypassed through the service API.
    preflight_report = training.assert_trainable(
        dataset_id, train_type=train_type,
        allow_caption_mismatch=allow_caption_mismatch,
        allow_uncaptioned=allow_uncaptioned,
        check_captions=check_captions)
    # Base d'entraînement : None/'' = officielle ; sinon un merge ComfyUI qui DOIT
    # avoir été converti en diffusers d'abord (gate). On persiste le choix sur le
    # dataset → _run_name/_run_dir/list_checkpoints deviennent base-aware (run isolé).
    base_model = (base_model or '').strip() or None
    variant = (variant or '').strip().lower()
    # La famille de CE lancement vient du param train_type s'il est donné, sinon du
    # dataset — c'est elle qui fixe l'enum de variantes valide (flux2klein : 4b/9b ;
    # les autres : turbo/base/deturbo) et le défaut (Krea → Raw, flux2klein → 4B).
    if variant not in _valid_variants_for(launch_fam):
        variant = _default_variant_for(launch_fam)
    if train_type is not None:
        ds.train_type = train_type
    # Conversion diffusers : UNIQUEMENT pour Z-Image (SDXL = single-file direct,
    # pas de conversion → on ne bloque pas sur is_converted).
    if base_model and _train_type(ds) == 'zimage':
        from .zimage_convert import is_converted
        if not is_converted(base_model):
            raise ValueError('custom base not converted - prepare it first (button "Convert base")')
    # SDXL : la base vient brute du body → whitelist serveur (anti path-traversal,
    # comme prepare-base le fait pour Z-Image). Refus immédiat si inconnue. Un
    # chemin ABSOLU est le champ « Custom weights… » (validé par le preflight
    # ci-dessous) → il contourne délibérément la whitelist de basenames.
    if (base_model and _train_type(ds) == 'sdxl' and not _is_custom_weights(base_model)
            and base_model not in _sdxl_base_choices()):
        raise ValueError('unknown SDXL checkpoint')
    # --- Custom base/vae/te : whitelist STRICTE par famille + preflight avant spawn.
    # Une famille non-SDXL n'emporte jamais de VAE/TE (cf. _effective_vae_te, qui
    # porte la MÊME règle pour la mise en file).
    # Preflight (fichier existe, header safetensors lisible, sniff d'arch) — un
    # sniff non concluant lève un refus CONFIRMABLE (_UNVERIFIED_MARKER), levé par
    # `allow_unverified_weights` exactement comme UNCAPTIONED.
    preflight_custom_paths(launch_fam, weights=base_model, vae_path=eff_vae,
                           te_path=eff_te,
                           allow_unverified_weights=allow_unverified_weights)
    # Krea 2 : refuser TÔT si l'ai-toolkit installé n'a pas l'arch krea2 (sinon
    # fallback silencieux vers le loader SD legacy → mauvais modèle, plantage confus).
    if _train_type(ds) == 'krea' and not _aitoolkit_supports_krea():
        raise ValueError(
            "ai-toolkit doesn't support Krea 2 yet (krea2 arch missing) - "
            "update it (git pull) before training a Krea LoRA.")
    # FLUX.2 Klein : même garde que Krea (archs d'EXTENSION, fallback SD silencieux
    # sur un ai-toolkit pas à jour → LoRA corrompu, cf. _aitoolkit_supports_flux2klein).
    if _train_type(ds) == 'flux2klein' and not _aitoolkit_supports_flux2klein():
        raise ValueError(
            "ai-toolkit doesn't support FLUX.2 Klein yet (flux2_klein arch missing) - "
            "update it (git pull) before training a FLUX.2 Klein LoRA.")
    # Garde-fou anti-collision de dossier : un AUTRE dataset du user avec le même
    # (trigger, base) écrirait dans le même run → LoRA mélangés. Refuser AVANT de
    # persister/lancer, en nommant le conflit pour que l'utilisateur change un trigger.
    clash = find_run_collision(user_id, dataset_id, base_model=base_model)
    if clash:
        raise ValueError(
            f"training collision: dataset '{clash.name}' (#{clash.id}) already uses "
            f"the same trigger '{ds.trigger_word}' on the same base - they would write "
            f"to the same folder. Change the trigger_word of one of the two before training.")
    ds.train_base_model = base_model
    ds.train_variant = variant
    # Persist the resolved SDXL VAE/TE overrides (None on every other family) so the
    # run-dir tag, the config, and continue/queue replays all read the same triplet.
    ds.train_vae_path = eff_vae
    ds.train_te_path = eff_te
    fds.db.session.commit()
    fds.db.session.refresh(ds)
    # Freeze every persisted column used by path/config builders. A settings
    # request racing after admission may change the dataset for the *next* run,
    # but it cannot retarget this launch after its immutable input capture.
    launch_ds = SimpleNamespace(**{
        column.name: getattr(ds, column.name)
        for column in FaceDataset.__table__.columns
    })
    launch_settings = launch_settings_snapshot(launch_ds, launch_fam)
    # Steps adaptatifs si non imposés ; sinon override borné (jamais < 500).
    steps = training.default_steps(launch_ds) if steps is None else max(500, int(steps))
    launch_token = f'{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}-{uuid.uuid4().hex[:8]}'
    # masked (défaut ON) : masques personne exportés à côté du dataset → la
    # job-config passe en masked training (fond 10 %). OFF ou indispo = historique.
    # Every launch gets its own materialized folder. Reusing the run-name folder
    # made an unchanged resume overwrite the exact bytes referenced by every
    # earlier config/provenance record, so old runs were not actually immutable.
    dataset_destination = _datasets_dir() / f'{_run_name(launch_ds)}_{launch_token}'
    assert_free_disk(
        dataset_destination.parent, MIN_FREE_GB_TRAIN,
        'an immutable training dataset snapshot')
    dataset_folder = None
    config_path = None
    archived = None
    launch_record = None
    log_path = None
    previous_log = None
    gpu_lease_token = None
    try:
        dataset_folder, admitted_snapshot = training._materialize_local_training_dataset(
            user_id, dataset_id, masked=masked, destination=dataset_destination)
        effective_masked = bool(masked and _mask_fields(dataset_folder))
        config_path = write_job_config(
            launch_ds, dataset_folder, steps=steps, launch_token=launch_token)
        launch_state = {
            'phase': 'prepared',
            'token': launch_token,
            'dataset_id': int(dataset_id),
            'config_path': str(config_path),
            'dataset_folder': str(dataset_folder),
            'queue_item_id': queue_manager._get_system_state(
                'training_queue_launch_id', None),
        }
        queue_manager._set_system_state('training_launch', launch_state, ttl_seconds=None)
        gpu_lease_token = queue_manager._acquire_gpu_lease(
            'training', _TRAINING_GPU_LEASE_TTL)
        if gpu_lease_token is None:
            raise ValueError('the GPU is already in use')
        queue_manager._set_system_state(
            'training_gpu_lease', gpu_lease_token, ttl_seconds=None)
        # Provenance registry: record WHICH immutable dataset version this launch
        # trains on (fingerprint + manifest -> human version v1/v2/...). Required:
        # an unregistered launch would make its checkpoints ambiguous.
        from . import checkpoint_registry
        # Archive only after every snapshot/config preparation succeeds. From here
        # through Popen, provenance + filesystem state are rolled back together if
        # no trainer process is created.
        archived = archive_previous_run(launch_ds) if fresh else None
        launch_record = checkpoint_registry.register_launch(
            user_id, dataset_id, family=_train_type(launch_ds), source='local',
            base_model=base_model or '', variant=variant, masked=effective_masked,
            steps=int(steps), settings=launch_settings,
            manifest=export_registry_manifest(dataset_folder),
            preflight=preflight_report,
            overrides={
                'allow_caption_mismatch': bool(allow_caption_mismatch),
                'allow_uncaptioned': bool(allow_uncaptioned),
                'check_captions': bool(check_captions),
                'allow_unverified_weights': bool(allow_unverified_weights),
                'masked': effective_masked,
                'masked_requested': bool(masked),
                'fresh': bool(fresh),
            },
            trigger=admitted_snapshot['trigger_word'],
            kind=admitted_snapshot['kind'],
            required=True)
        launch_state.update({
            'phase': 'spawning',
            'archived_run': archived,
            'launch_record_id': getattr(launch_record, 'id', None),
        })
        queue_manager._set_system_state('training_launch', launch_state, ttl_seconds=None)
        # Pause GPU longue durée : le superviseur stoppe ComfyUI -> comfyui_ready=False
        # -> le dispatch worker se met en pause tout seul.
        queue_manager._set_system_state('training_error', None, ttl_seconds=1)
        queue_manager._set_system_state(
            'training_in_progress', True, ttl_seconds=None)
        queue_manager._set_system_state(
            'training_dataset_id', int(dataset_id), ttl_seconds=None)
        # DBR-0006 (review 2): run-scoped metadata the UI reads for the WHOLE
        # run — a TTL shorter than a multi-hour run made reads fall back to
        # defaults mid-run. These keys are explicitly cleared on completion /
        # failure, so no expiry is needed.
        queue_manager._set_system_state(
            'training_train_type', _train_type(launch_ds), ttl_seconds=None)
        queue_manager._set_system_state(
            'training_base_model', getattr(launch_ds, 'train_base_model', None) or '',
            ttl_seconds=None)
        # Step cible : sert à snapshotter le final en nom NUMÉROTÉ à la fin.
        queue_manager._set_system_state(
            'training_target_step', int(steps), ttl_seconds=None)
        # HF_HOME routes base/adapter weights to the configured disk.
        env = dict(os.environ, HF_HOME=str(_hf_home()), PYTHONIOENCODING='utf-8')
        run_dir = _output_dir() / _run_name(launch_ds)
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = str(run_dir / 'training.log')
        checkpoint_dir = run_dir / f'lora_{_safe_trigger(launch_ds)}'
        queue_manager._set_system_state(
            'training_log_path', log_path, ttl_seconds=None)
        queue_manager._set_system_state(
            'training_checkpoint_dir', str(checkpoint_dir), ttl_seconds=None)
        queue_manager._set_system_state(
            'training_trigger', _safe_trigger(launch_ds), ttl_seconds=None)
        if Path(log_path).is_file():
            previous_log = run_dir / f'training-{launch_token}-previous.log'
            os.rename(log_path, previous_log)
        with open(log_path, 'w', encoding='utf-8') as logf:
            proc = subprocess.Popen([str(_venv_python()), 'run.py', config_path],
                                    cwd=str(_aitoolkit_dir()), env=env, shell=False,
                                    stdout=logf, stderr=subprocess.STDOUT,
                                    start_new_session=(os.name != 'nt'),
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as exc:
        _clear_failed_training_state()
        _discard_failed_launch_record(launch_record)
        if archived:
            _restore_fresh_archive(launch_ds, archived)
        else:
            _restore_previous_training_log(log_path, previous_log)
        _trash_failed_launch_inputs(config_path, dataset_folder or dataset_destination)
        if isinstance(exc, (FileNotFoundError, OSError)):
            raise ValueError(f"could not start training: {exc}") from exc
        raise
    # Ownership truth must survive an arbitrarily long web-server outage. The
    # scheduler reconciles this durable PID after restart; TTL expiry must never
    # make a detached trainer invisible to GPU admission.
    queue_manager._set_system_state('training_pid', proc.pid, ttl_seconds=None)
    launch_state.update({
        'phase': 'running',
        'process_identity': training._process_identity(proc.pid, config_path),
    })
    queue_manager._set_system_state('training_launch', launch_state, ttl_seconds=None)
    # Watcher event-driven : libère ComfyUI / enchaîne la file dès la fin du
    # process (le poll de /train/status reste le filet de secours).
    try:
        from flask import current_app
        threading.Thread(target=training._watch_training,
                         args=(current_app._get_current_object(), proc, log_path, int(dataset_id)),
                         daemon=True).start()
    except Exception as e:
        logger.warning("watcher training non démarré : %s", e)
    return {'started': True, 'pid': proc.pid, 'config_path': config_path, 'steps': steps,
            'dataset_folder': dataset_folder, 'log_path': log_path,
            'fresh': bool(fresh), 'archived_run': archived}


def continue_training(user_id, dataset_id, extra_steps: int = 1000,
                      base_model=_PERSISTED, variant=None, train_type=None,
                      masked=True, fresh=False, allow_caption_mismatch=False,
                      allow_uncaptioned=False, vae_path=_PERSISTED,
                      te_path=_PERSISTED, allow_unverified_weights=None) -> dict:
    """Reprend l'entraînement depuis le dernier checkpoint de la base ciblée et
    vise ``dernier_step + extra_steps``. ai-toolkit auto-resume depuis le
    training_folder ; il faut donc qu'au moins un checkpoint existe POUR CETTE BASE.

    `base_model` absent → base persistée du dataset (ex. file d'attente). Fourni
    (sélection UI) → on reprend le run DE CETTE base précise : sinon on proposait
    « Continuer » sur une base sans run et on relançait en fait l'ancienne base."""
    if queue_manager._get_system_state('training_in_progress', False):
        raise ValueError('a training is already in progress')
    ds = fds.get_dataset(user_id, dataset_id)
    base = (ds.train_base_model if ds else None) if base_model is _PERSISTED else base_model
    var = (variant or (ds.train_variant if ds else None) or 'turbo')
    cks = training.list_checkpoints(
        user_id, dataset_id, base_model=base, family=train_type)
    if not cks:
        raise ValueError("no checkpoint to resume for this base - run a training first")
    latest = max(c['step'] for c in cks)
    try:
        extra = max(100, int(extra_steps))
    except (TypeError, ValueError):
        extra = 1000
    # Reprendre AVEC la base/variante ciblée - sinon launch_training les remettrait
    # à l'officiel et ai-toolkit reprendrait depuis le mauvais run. vae/te restent
    # _PERSISTED (on garde le triplet du run). allow_unverified_weights=True : la
    # base custom a DÉJÀ franchi le sniff au 1er lancement (un checkpoint existe) —
    # ne pas re-buter sur le refus confirmable, que ce chemin ne saurait confirmer.
    res = training.launch_training(
        user_id, dataset_id, steps=latest + extra, check_captions=False,
        base_model=base, variant=var, train_type=train_type, masked=masked,
        fresh=fresh, allow_caption_mismatch=allow_caption_mismatch,
        allow_uncaptioned=allow_uncaptioned, vae_path=vae_path, te_path=te_path,
        # A queued snapshot preserves the caller's explicit decision. Historical
        # direct continuations retain the old already-verified behavior.
        allow_unverified_weights=(True if allow_unverified_weights is None
                                  else bool(allow_unverified_weights)))
    res['resumed_from'] = latest
    res['target_steps'] = latest + extra
    return res


def _terminate_training_process(pid, timeout=10.0) -> bool:
    """Terminate a trainer and every descendant, waiting for confirmation."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if os.name == 'nt':
        result = subprocess.run(
            ['taskkill', '/F', '/T', '/PID', str(pid)], shell=False,
            capture_output=True)
        return result.returncode == 0 or not training._pid_alive(pid)
    try:
        import psutil
        parent = psutil.Process(pid)
        processes = parent.children(recursive=True) + [parent]
        for process in processes:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        _gone, alive = psutil.wait_procs(processes, timeout=max(0.1, timeout))
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        if alive:
            _gone, alive = psutil.wait_procs(alive, timeout=2.0)
        return not alive
    except ImportError:
        # New launches are session leaders, so the group contains the trainer
        # and its dataloaders without including this server process.
        try:
            pgid = os.getpgid(pid)
            if pgid == pid:
                os.killpg(pgid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            if not training._pid_alive(pid):
                return True
            time.sleep(0.1)
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        return not training._pid_alive(pid)
    except Exception as exc:
        logger.warning('stop_training: process-tree termination failed: %s', exc)
        return not training._pid_alive(pid)


def stop_training(*, clear_queue: bool = True) -> None:
    """Tue le process d'entraînement (s'il tourne) PUIS lève le flag → le
    superviseur relance ComfyUI. L'ordre compte : si on levait le flag d'abord,
    ComfyUI reprendrait le GPU pendant que l'entraînement tourne encore."""
    pid = queue_manager._get_system_state('training_pid', None)
    if pid and not training._owned_training_process_alive(pid):
        raise RuntimeError(
            'the recorded training PID no longer matches the owned process; '
            'refusing to terminate an unrelated process')
    if pid and not _terminate_training_process(pid):
        raise RuntimeError(
            'the training process is still running; ComfyUI remains paused')
    # Queue cancellation is an explicit caller policy.  Historically every stop
    # silently erased all deferred work; callers can now retain it.
    if clear_queue:
        training._save_queue([])
    _clear_failed_training_state()
