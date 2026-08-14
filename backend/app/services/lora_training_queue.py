"""Durable local-training queue lifecycle and background scheduler.

This module owns queue persistence, delayed admission, process identity recovery,
completion hand-off, final-checkpoint snapshots, and the process-owned ticker.
The launch/configuration implementation remains in ``lora_training`` and is
consumed through the explicit imports below.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime

from .. import config as cfg
from ..job_queue import queue_manager
from ..models import FaceDataset
from . import face_dataset_service as fds
from . import lora_training as training
from .training_jobs import EffectiveTrainingJob
from .lora_training import (
    _PERSISTED,
    _TRAINING_GPU_LEASE_TTL,
    _TRAIN_STATE_TTL,
    _atomic_copy,
    _default_variant_for,
    _effective_vae_te,
    _is_custom_weights,
    _output_dir,
    _run_name,
    _safe_trigger,
    _sdxl_base_choices,
    _train_type,
    cleanup_abandoned_local_training_staging,
)
from .lora_training_process import (
    _clear_failed_training_state,
    _discard_failed_launch_record,
    _restore_fresh_archive,
    _trash_failed_launch_inputs,
)

logger = logging.getLogger(__name__)

# --- File d'attente d'entraînement -------------------------------------------
TRAIN_QUEUE_KEY = 'lora_train_queue'
_queue_lock = threading.RLock()


def _pid_alive(pid) -> bool:
    try:
        import psutil
        return bool(pid) and psutil.pid_exists(int(pid))
    except Exception:
        return False


def _process_identity(pid, config_path=None) -> dict | None:
    try:
        import psutil
        process = psutil.Process(int(pid))
        return {
            'pid': process.pid,
            'created_at': process.create_time(),
            'config_path': str(config_path) if config_path else None,
        }
    except Exception:
        return None


def _owned_training_process_alive(pid=None) -> bool:
    """Validate the trainer PID against its durable creation identity.

    For the crash-after-spawn/before-PID window, discover exactly the child whose
    command line contains the immutable launch config path and adopt it.
    """
    launch = queue_manager._get_system_state('training_launch', None) or {}
    identity = launch.get('process_identity') if isinstance(launch, dict) else None
    candidate_pid = pid or (identity or {}).get('pid')
    try:
        import psutil
        if candidate_pid and identity:
            process = psutil.Process(int(candidate_pid))
            if abs(process.create_time() - float(identity['created_at'])) < 0.01:
                return process.is_running()
            return False
        if candidate_pid and (not launch or launch.get('phase') == 'running'):
            # psutil can be unavailable in minimal installs. Preserve legacy
            # supervision, while installations with psutil get reuse-proof
            # creation-time validation above.
            return training._pid_alive(candidate_pid)
        config_path = launch.get('config_path') if isinstance(launch, dict) else None
        if launch.get('phase') == 'spawning' and config_path:
            for process in psutil.process_iter(('pid', 'create_time', 'cmdline')):
                if str(config_path) not in (process.info.get('cmdline') or []):
                    continue
                identity = {
                    'pid': process.info['pid'],
                    'created_at': process.info['create_time'],
                    'config_path': str(config_path),
                }
                launch = dict(launch, phase='running', process_identity=identity)
                queue_manager._set_system_state('training_launch', launch, ttl_seconds=None)
                queue_manager._set_system_state(
                    'training_pid', process.info['pid'], ttl_seconds=None)
                return True
    except Exception:
        return False
    return False


def get_train_queue() -> list:
    q = queue_manager._get_system_state(TRAIN_QUEUE_KEY, [])
    return q if isinstance(q, list) else []


def _save_queue(q: list) -> None:
    queue_manager._set_system_state(TRAIN_QUEUE_KEY, q, ttl_seconds=None)


def enqueue_training(user_id, dataset_id, extra_steps=None,
                     base_model=_PERSISTED, variant=None, train_type=None,
                     allow_caption_mismatch=False, not_before=None, masked=True,
                     steps=None, allow_uncaptioned=False,
                     vae_path=_PERSISTED, te_path=_PERSISTED,
                     allow_unverified_weights=False, fresh=False) -> dict:
    """Ajoute un dataset à la file (lancé à la fin du training courant).

    `base_model`/`variant` permettent de CHOISIR explicitement la base du job en
    file (absent → base persistée). Sans ça, on ne pouvait pas choisir le modèle
    d'un job mis en file pendant qu'un autre entraînement tourne (le sélecteur
    était masqué et l'enqueue réutilisait silencieusement la base persistée).

    `steps` = cible ABSOLUE de steps pour un lancement neuf (None → adaptatif via
    recommended_steps). À NE PAS confondre avec `extra_steps` (mode « continuer »
    = +N steps depuis le dernier checkpoint). Snapshotté dans la file pour que le
    lancement différé respecte le même plafond (ex. « s'arrêter à 2000 »)."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    # Pas de mise en file si le dataset n'est pas prêt (captions manquantes, etc.).
    if extra_steps is None:
        training.assert_trainable(dataset_id, train_type=train_type,
                         allow_caption_mismatch=allow_caption_mismatch,
                         allow_uncaptioned=allow_uncaptioned)
    ttype = _train_type(ds, train_type)
    base = (ds.train_base_model if base_model is _PERSISTED else base_model) or None
    var = (variant or ds.train_variant or _default_variant_for(ttype))
    # Base custom (merge) Z-Image = doit être convertie AVANT (SDXL = single-file
    # direct, pas de conversion → on saute la vérif). Refus immédiat et lisible.
    if extra_steps is None and base and ttype == 'zimage':
        from .zimage_convert import is_converted
        if not is_converted(base):
            raise ValueError('custom base not converted - prepare it first (button "Convert base")')
    # SDXL : whitelist serveur de la base (anti path-traversal). Un chemin ABSOLU
    # = « Custom weights… » (validé par le preflight) → contourne la whitelist.
    if base and ttype == 'sdxl' and not _is_custom_weights(base) and base not in _sdxl_base_choices():
        raise ValueError('unknown SDXL checkpoint')
    # Custom vae/te : whitelist STRICTE par famille (SDXL-only), persistance et
    # preflight — même contrat qu'au lancement, pour ne pas mettre en file un job
    # voué à un refus 400 (ou à un chemin fantôme) au moment de son démarrage.
    eff_vae, eff_te = _effective_vae_te(ds, ttype, vae_path, te_path)
    if extra_steps is None:
        training.preflight_custom_paths(ttype, weights=base, vae_path=eff_vae, te_path=eff_te,
                               allow_unverified_weights=allow_unverified_weights)
    # Krea 2 : même garde qu'au lancement - pas de mise en file d'un job qui
    # tomberait dans le fallback SD legacy faute d'arch krea2 dans l'ai-toolkit.
    if ttype == 'krea' and not training._aitoolkit_supports_krea():
        raise ValueError(
            "ai-toolkit doesn't support Krea 2 yet (krea2 arch missing) - "
            "update it (git pull) before queuing a Krea LoRA.")
    # FLUX.2 Klein : même garde qu'au lancement (archs d'extension, cf. launch).
    if ttype == 'flux2klein' and not training._aitoolkit_supports_flux2klein():
        raise ValueError(
            "ai-toolkit doesn't support FLUX.2 Klein yet (flux2_klein arch missing) - "
            "update it (git pull) before queuing a FLUX.2 Klein LoRA.")
    # Même garde-fou de collision qu'au lancement : pas de mise en file d'un job
    # qui partagerait le dossier de run d'un autre dataset (même trigger + base).
    clash = training.find_run_collision(user_id, dataset_id, base_model=base)
    if clash:
        raise ValueError(f"training collision with '{clash.name}' (#{clash.id}): "
                         f"same trigger + same base. Change the trigger_word before queuing.")
    # Snapshot de la base/variante/type CHOISIE au moment de la mise en file (le
    # lancement différé doit garder CE choix, pas relancer sur l'officiel/zimage).
    # `not_before` (ISO, heure locale serveur) = entraînement PROGRAMMÉ : le job
    # reste en file jusqu'à l'échéance ; s'il devient dû pendant qu'un autre
    # entraînement tourne, il attend simplement son tour (jamais d'erreur).
    # Cible de steps ABSOLUE (plafond choisi côté UI) - coercition défensive : un
    # '' / 0 / non-numérique retombe sur None (= adaptatif), jamais de crash JSON.
    try:
        steps_target = int(steps) if steps else None
    except (TypeError, ValueError):
        steps_target = None
    job = EffectiveTrainingJob(
        job_id=uuid.uuid4().hex, dataset_id=int(dataset_id), user_id=str(user_id),
        extra_steps=extra_steps, base_model=base, variant=var, train_type=ttype,
        not_before=not_before, masked=bool(masked), steps=steps_target,
        fresh=bool(fresh), vae_path=eff_vae, te_path=eff_te,
        allow_unverified_weights=bool(allow_unverified_weights),
        allow_caption_mismatch=bool(allow_caption_mismatch),
        allow_uncaptioned=bool(allow_uncaptioned))
    item = job.queue_record()
    with _queue_lock:
        q = training.get_train_queue()
        if any(int(it.get('dataset_id', -1)) == int(dataset_id) for it in q):
            return {'queued': False, 'reason': 'already queued'}
        q.append(item)
        training._save_queue(q)
        return {'queued': True, 'position': len(q), 'not_before': not_before}


def dequeue_training(dataset_id) -> int:
    with _queue_lock:
        q = training.get_train_queue()
        new = [it for it in q if int(it.get('dataset_id', -1)) != int(dataset_id)]
        training._save_queue(new)
        return len(q) - len(new)


def train_queue_view(user_id) -> list:
    out = []
    for it in training.get_train_queue():
        ds = fds.get_dataset(it.get('user_id', user_id), it.get('dataset_id'))
        bm = it.get('base_model')
        base_label = (os.path.basename(str(bm).replace('\\', '/')).rsplit('.', 1)[0]
                      if bm else 'Official')
        out.append({'dataset_id': it.get('dataset_id'),
                    'name': ds.name if ds else f"#{it.get('dataset_id')}",
                    'extra_steps': it.get('extra_steps'),
                    # Cible de steps absolue choisie à la mise en file (None = adaptatif).
                    'steps': it.get('steps'),
                    'train_type': it.get('train_type'),
                    'variant': it.get('variant'),
                    'base_model': bm, 'base_label': base_label,
                    # Échéance de programmation (ISO local) - None = dès que possible.
                    'not_before': it.get('not_before'),
                    'status': it.get('status', 'queued'),
                    'error': it.get('error')})
    return out


def _launch_queued_item(item) -> None:
    job = EffectiveTrainingJob.from_queue_record(item, persisted=_PERSISTED)
    if job.continuation:
        kwargs = job.continuation_kwargs()
        kwargs.pop('user_id')
        kwargs.pop('dataset_id')
        training.continue_training(job.user_id, job.dataset_id, **kwargs)
    else:
        kwargs = job.launch_kwargs()
        kwargs.pop('user_id')
        kwargs.pop('dataset_id')
        training.launch_training(job.user_id, job.dataset_id, **kwargs)


def process_training_queue() -> str | None:
    """Avance la file : si le training courant est FINI (process mort mais flag
    encore levé), lance le suivant ; sinon, si rien ne tourne et la file n'est pas
    vide, lance le prochain. À appeler périodiquement (le poll de /train/status le
    fait). Retourne un libellé d'action ou None. SÉRIALISÉ par _queue_lock : sans
    ça, le watcher et un poll /train/status peuvent avancer la file en même temps
    → double-lancement du même entraînement."""
    with _queue_lock:
        return training._advance_training_queue()


def _snapshot_final_checkpoint(dataset_id, step) -> str | None:
    """Copie le final bare `lora_<trigger>.safetensors` vers son nom NUMÉROTÉ
    `lora_<trigger>_<step:09d>.safetensors`. ai-toolkit écrit le résultat final SANS
    numéro de step ; sans ce snapshot :
      - continuer un entraînement écrase ce final sans aucune trace (perte) ;
      - list_checkpoints sous-estime le step de reprise (il compte le bare au DERNIER
        numéro existant, pas à son vrai step) → `continue_training` repart trop bas.
    Le snapshot rend chaque final permanent ET visible à son vrai step. Idempotent
    (ne réécrit jamais un numéroté existant). Retourne le nom créé, ou None."""
    try:
        step = int(step)
    except (TypeError, ValueError):
        return None
    if step <= 0 or dataset_id is None:
        return None
    run = queue_manager._get_system_state('training_checkpoint_dir', None)
    trigger = queue_manager._get_system_state('training_trigger', None)
    if not run or not trigger:
        ds = fds.db.session.get(FaceDataset, int(dataset_id))
        if not ds:
            return None
        trigger = _safe_trigger(ds)
        run = str(_output_dir() / _run_name(ds) / f'lora_{trigger}')
    final = os.path.join(run, f'lora_{trigger}.safetensors')
    numbered = os.path.join(run, f'lora_{trigger}_{step:09d}.safetensors')
    if not os.path.isfile(final) or os.path.exists(numbered):
        return None
    try:
        _atomic_copy(final, numbered)
        logger.info('snapshot final → %s (step %d)', numbered, step)
        return os.path.basename(numbered)
    except OSError as e:
        logger.warning('snapshot final échoué : %s', e)
        return None


def _due_index(q) -> int | None:
    """Index du premier job DÛ de la file : sans `not_before`, ou dont l'échéance
    (ISO, heure locale serveur) est atteinte. Un job PROGRAMMÉ pour plus tard ne
    bloque pas ceux placés derrière lui. `not_before` illisible → dû (fail-open)."""
    now = datetime.now()
    for i, it in enumerate(q):
        if it.get('status') == 'failed':
            continue
        nb = it.get('not_before')
        if not nb:
            return i
        try:
            if datetime.fromisoformat(str(nb)) <= now:
                return i
        except (TypeError, ValueError):
            return i
    return None


def _compensate_unstarted_launch() -> bool:
    """Roll back durable preparation when no exact trainer process exists."""
    launch = queue_manager._get_system_state('training_launch', None)
    if not isinstance(launch, dict) or launch.get('phase') not in ('prepared', 'spawning'):
        return False
    dataset_id = launch.get('dataset_id')
    ds = fds.get_dataset(cfg.LOCAL_USER, dataset_id) if dataset_id is not None else None
    record_id = launch.get('launch_record_id')
    if record_id:
        from ..models import TrainingRunRecord
        record = fds.db.session.get(TrainingRunRecord, record_id)
        _discard_failed_launch_record(record)
    archived = launch.get('archived_run')
    if archived and ds is not None:
        _restore_fresh_archive(ds, archived)
    _trash_failed_launch_inputs(
        launch.get('config_path'), launch.get('dataset_folder'))
    _clear_failed_training_state()
    logger.warning(
        'recovered unstarted local training launch %s (%s)',
        launch.get('token'), launch.get('phase'))
    return True


def _prepare_queued_launch(q, due):
    item = dict(q[due])
    item.setdefault('id', uuid.uuid4().hex)
    item['status'] = 'launching'
    q = q[:due] + [item] + q[due + 1:]
    _save_queue(q)
    queue_manager._set_system_state(
        'training_queue_launch_id', item['id'], ttl_seconds=None)
    return q, item


def _try_launch_due(q, due, label: str, log_lead: str) -> str | None:
    """Lancer l'item dû, puis solder la file. Partagé par les DEUX chemins
    d'avancement (run qui vient de finir / rien en cours) : la comptabilité
    d'échec (`status='failed'`, `training_queue_error`, remise à zéro de
    `training_queue_launch_id`) doit rester identique sur les deux, sinon l'UI
    rapporte les échecs de file différemment selon le chemin emprunté.

    Retour : `f'{label}:{dataset_id}'` si lancé, None si l'échec a été enregistré.
    """
    q, nxt = _prepare_queued_launch(q, due)
    try:
        training._launch_queued_item(nxt)  # remet le flag + un nouveau pid (pas de flap GPU)
        training._save_queue(q[:due] + q[due + 1:])  # retirer SEULEMENT après lancement réussi
        queue_manager._set_system_state(
            'training_queue_launch_id', None, ttl_seconds=1)
        logger.info(f"File training : {log_lead} dataset {nxt['dataset_id']}")
        return f"{label}:{nxt['dataset_id']}"
    except Exception as e:
        nxt = dict(nxt, status='failed', error=str(e))
        training._save_queue(q[:due] + [nxt] + q[due + 1:])
        queue_manager._set_system_state(
            'training_queue_launch_id', None, ttl_seconds=1)
        queue_manager._set_system_state(
            'training_queue_error',
            {'dataset_id': nxt.get('dataset_id'), 'error': str(e)}, ttl_seconds=3600)
        logger.error(f"File training : échec lancement {nxt.get('dataset_id')}: {e}")
        return None


def _advance_training_queue() -> str | None:
    flag = bool(queue_manager._get_system_state('training_in_progress', False))
    pid = queue_manager._get_system_state('training_pid', None)
    vision_busy = bool(queue_manager._get_system_state('vision_in_progress', False))
    q = training.get_train_queue()

    if flag:
        if training._owned_training_process_alive(pid):
            launch = queue_manager._get_system_state('training_launch', None) or {}
            queue_item_id = launch.get('queue_item_id') if isinstance(launch, dict) else None
            if queue_item_id:
                remaining = [item for item in q if item.get('id') != queue_item_id]
                if len(remaining) != len(q):
                    training._save_queue(remaining)
                    q = remaining
                queue_manager._set_system_state(
                    'training_queue_launch_id', None, ttl_seconds=1)
            # Re-arm state on every poll: without this, a run longer than the
            # 12-hour _TRAIN_STATE_TTL would lose its progress metadata,
            # and the GPU gate (job_queue / gpu_busy_reason) would think
            # nothing is running and let the queue/vision grab the GPU back.
            queue_manager._set_system_state('training_in_progress', True, ttl_seconds=None)
            queue_manager._set_system_state('training_pid', pid, ttl_seconds=None)
            lease_token = queue_manager._get_system_state('training_gpu_lease', None)
            if lease_token:
                if not queue_manager._renew_gpu_lease(
                        lease_token, _TRAINING_GPU_LEASE_TTL):
                    logger.error('training GPU lease was lost while trainer pid %s is alive', pid)
            else:
                # Legacy/restart state predating the unified lease. Claim it
                # before allowing generation or vision work to overlap.
                lease_token = queue_manager._acquire_gpu_lease(
                    'training', _TRAINING_GPU_LEASE_TTL)
                if lease_token:
                    queue_manager._set_system_state(
                        'training_gpu_lease', lease_token, ttl_seconds=None)
            cur_dataset_id = queue_manager._get_system_state('training_dataset_id', None)
            if cur_dataset_id is not None:
                queue_manager._set_system_state(
                    'training_dataset_id', cur_dataset_id, ttl_seconds=None)
            cur_target_step = queue_manager._get_system_state('training_target_step', None)
            if cur_target_step is not None:
                queue_manager._set_system_state('training_target_step', cur_target_step, ttl_seconds=_TRAIN_STATE_TTL)
            for key in ('training_log_path', 'training_checkpoint_dir',
                        'training_trigger'):
                value = queue_manager._get_system_state(key, None)
                if value is not None:
                    queue_manager._set_system_state(
                        key, value, ttl_seconds=_TRAIN_STATE_TTL)
            return None  # toujours en cours
        _compensate_unstarted_launch()
        # Process mort alors que le flag est levé → training terminé.
        # Snapshot du final en nom NUMÉROTÉ (immuable) AVANT d'enchaîner/libérer :
        # sinon un futur « continuer » écrase ce final sans trace. Idempotent, et ce
        # point tourne aussi via le poll /train/status (robuste à un restart Flask).
        try:
            training._snapshot_final_checkpoint(
                queue_manager._get_system_state('training_dataset_id', None),
                queue_manager._get_system_state('training_target_step', None))
        except Exception as e:
            logger.warning('snapshot final (advance) échoué : %s', e)
        due = _due_index(q)
        if due is not None and not vision_busy:
            return _try_launch_due(q, due, 'next', 'terminé → lancement')
        # File vide (ou uniquement des jobs programmés plus tard) → libérer le GPU
        # (le superviseur relance ComfyUI ; le ticker relancera le job à l'échéance).
        queue_manager._set_system_state('training_in_progress', False, ttl_seconds=1)
        queue_manager._set_system_state('training_pid', None, ttl_seconds=1)
        lease_token = queue_manager._get_system_state('training_gpu_lease', None)
        if lease_token:
            queue_manager._release_gpu_lease(lease_token)
        queue_manager._set_system_state('training_gpu_lease', None, ttl_seconds=1)
        logger.info("File training : terminé, aucune suite due → flag libéré")
        return 'released'

    due = _due_index(q)
    if due is not None and not vision_busy:
        return _try_launch_due(q, due, 'launched', 'lancement')
    return None


# --- Programmation d'entraînements (jour + heure) -----------------------------
_scheduler_started = False
_scheduler_stop = threading.Event()
_scheduler_thread = None


def start_training_scheduler(app, interval_seconds=60):
    """Ticker de fond : avance la file toutes les `interval_seconds` MÊME sans
    navigateur ouvert. Sans lui, seul le watcher de fin de process ferait avancer
    la file - un entraînement programmé à 3 h du matin ne serait jamais parti.
    Idempotent (un seul thread par process)."""
    global _scheduler_started, _scheduler_thread
    if _scheduler_started:
        return
    cleanup_abandoned_local_training_staging()
    _scheduler_stop.clear()
    _scheduler_started = True

    def _tick():
        while not _scheduler_stop.wait(interval_seconds):
            try:
                with app.app_context():
                    process_training_queue()
            except Exception as e:  # jamais fatal - le tick suivant réessaie
                logger.debug('training scheduler tick: %s', e)

    _scheduler_thread = threading.Thread(
        target=_tick, daemon=True, name='train-scheduler')
    _scheduler_thread.start()
    logger.info('Training scheduler démarré (tick %ss)', interval_seconds)


def stop_training_scheduler(timeout=5) -> None:
    """Stop the process-owned scheduler and permit a clean restart."""
    global _scheduler_started, _scheduler_thread
    _scheduler_stop.set()
    thread = _scheduler_thread
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout)
    _scheduler_thread = None
    _scheduler_started = False
