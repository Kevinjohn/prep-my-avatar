"""Materialization and durable export of local training datasets."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image

from ..job_queue import queue_manager
from ..models import FaceDatasetImage
from . import face_dataset_service as fds
from . import lora_training as training
from .lora_training import (
    _LOCAL_STAGING_OWNER, _LOCAL_STAGING_PREFIX, _TRAIN_STATE_TTL,
    _datasets_dir, _run_name,
)

logger = logging.getLogger(__name__)


def _masks_dir(dataset_folder: str) -> str:
    """Dossier des masques d'un export (convention mask_path ai-toolkit : dossier
    frère, mêmes noms de fichiers)."""
    return f'{dataset_folder}_masks'


def _mask_fields(dataset_folder: str) -> dict:
    """Champs `mask_path`/`mask_min_value` à fusionner dans l'entrée datasets de la
    job-config SI des masques ont été exportés (masked training, méthode jandordoe :
    fond pondéré à 10 % de la loss → l'identité se lie au sujet, pas au décor).
    Dossier absent/vide → {} (l'entraînement reste strictement l'historique)."""
    md = _masks_dir(dataset_folder)
    try:
        if os.path.isdir(md) and any(f.lower().endswith('.png') for f in os.listdir(md)):
            return {'mask_path': md, 'mask_min_value': 0.1}
    except OSError:
        pass
    return {}


_EXPORTED_MANIFEST = '.training-manifest.json'


def _sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def export_registry_manifest(dataset_folder) -> list:
    """Return provenance for the exact PNG/caption pairs handed to ai-toolkit."""
    try:
        payload = json.loads(Path(dataset_folder, _EXPORTED_MANIFEST).read_text(
            encoding='utf-8'))
        manifest = payload.get('registry_manifest')
        return manifest if isinstance(manifest, list) else []
    except (OSError, ValueError):
        return []


def export_dataset_to_aitoolkit(user_id, dataset_id, masked: bool = True, dest_dir=None,
                                snapshot_dir=None) -> str:
    """Écrit les images `keep` en paires .png/.txt dans
    DATASETS_DIR/<trigger>. Le caption = caption éditée + trigger (le trigger
    est toujours présent même si la caption est vide). Retourne le dossier.

    `masked` (défaut ON) : génère aussi un masque « personne » par image (rembg
    u2net, subprocess CPU - cf app/services/person_mask) dans `<dossier>_masks` →
    la job-config passe en MASKED TRAINING (fond à 10 %). Échec des masques =
    jamais bloquant : l'entraînement part simplement sans masques (loggé).

    `dest_dir` (cloud seam) : exporte LÀ au lieu de DATASETS_DIR/<run_name> - ne
    requiert PAS ai-toolkit configuré localement (pas d'appel à _datasets_dir()).
    Défaut (None) = comportement historique inchangé."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    snapshot = None
    if snapshot_dir is not None:
        from . import training_snapshot
        snapshot = training_snapshot.load(snapshot_dir)
        if int(snapshot.get('dataset_id')) != int(dataset_id):
            raise ValueError('training snapshot belongs to another dataset')
    snapshot_kind = snapshot.get('kind') if snapshot else None
    if masked and ((snapshot_kind in ('concept', 'style')) if snapshot else fds.is_conceptual(ds)):
        # A person-mask would erase the very thing we want the LoRA to learn (the
        # recurring act for a concept; the whole-image rendering for a style - which
        # lives as much in backgrounds as in people). Force masked training OFF for
        # concept AND style datasets even if the caller/UI asked for it -- server guard.
        logger.info('dataset %s %s -> masked training forced OFF (server guard)',
                    dataset_id, ds.kind)
        masked = False
    trigger_value = snapshot.get('trigger_word') if snapshot else ds.trigger_word
    trigger = ''.join(
        char if (char.isalnum() or char in '_-') else '_'
        for char in (trigger_value or f'dataset{dataset_id}').strip()
    ) or f'dataset{dataset_id}'
    out = str(dest_dir) if dest_dir else str(_datasets_dir() / _run_name(ds))
    if os.path.isdir(out):
        shutil.rmtree(out)  # ré-export propre
    masks_out = _masks_dir(out)
    if os.path.isdir(masks_out):
        shutil.rmtree(masks_out)  # jamais de masques périmés (ré-export ou toggle OFF)
    os.makedirs(out, exist_ok=True)
    if snapshot is not None:
        from . import training_snapshot
        inputs = [
            (entry['image_id'], training_snapshot.entry_path(snapshot_dir, entry),
             entry.get('caption') or '')
            for entry in snapshot['entries']
        ]
    else:
        kept = (FaceDatasetImage.query
                .filter_by(dataset_id=dataset_id, status='keep')
                .filter(FaceDatasetImage.filename.isnot(None))
                .order_by(FaceDatasetImage.id.asc()).all())
        inputs = [(img.id, Path(fds._img_path(img)), img.caption or '') for img in kept]
    if not inputs:
        raise ValueError('no kept images to export')
    n = 0
    exported = []
    registry_manifest = []
    for image_id, src, caption in inputs:
        if not Path(src).is_file():
            continue
        stem = f'{trigger}_{n:03d}'
        dst = os.path.join(out, f'{stem}.png')
        with Image.open(src) as opened, opened.convert('RGB') as converted:
            converted.save(dst, 'PNG')
        exported.append(dst)
        cap = caption.strip()
        body = f'{trigger}, {cap}' if cap else trigger
        with open(os.path.join(out, f'{stem}.txt'), 'w', encoding='utf-8') as fh:
            fh.write(body)
        registry_manifest.append([
            image_id,
            hashlib.sha256(caption.encode('utf-8')).hexdigest(),
            _sha256_file(dst),
        ])
        n += 1
    if n == 0:
        raise ValueError('no valid image file found on disk')
    masked_ok = False
    if masked:
        # generate_person_masks returns a DICT ({"ok", "written", "results"}, or {}
        # on any failure/unavailability) -- a non-empty dict is always truthy, so a
        # verbatim `if wrote:` on the return value would never take the cleanup
        # branch. Read the actual count instead.
        res = training.generate_person_masks(exported, masks_out)
        wrote = int(res.get('written') or 0) if isinstance(res, dict) else 0
        if wrote:
            masked_ok = True
            logger.info(f'export dataset {dataset_id}: {wrote}/{n} masque(s) personne -> {masks_out}')
        else:
            logger.warning(f'export dataset {dataset_id}: masques indisponibles - training SANS masked loss')
            if os.path.isdir(masks_out):
                shutil.rmtree(masks_out, ignore_errors=True)
    # A REQUESTED masked run that produced no masks (rembg missing, or generation
    # crashed at runtime) silently trains UNMASKED. Record it per-run so the live
    # progress view can warn — instead of the fallback being invisible. `masked` is
    # the FINAL intent: concept/style were already forced OFF above (by design), so
    # they never set this flag.
    queue_manager._set_system_state('training_masks_skipped', bool(masked and not masked_ok),
                                    ttl_seconds=_TRAIN_STATE_TTL)
    Path(out, _EXPORTED_MANIFEST).write_text(json.dumps({
        'format': 'prep-my-avatar-materialized-training-set',
        'version': 1,
        'dataset_id': dataset_id,
        'registry_manifest': registry_manifest,
    }, indent=2), encoding='utf-8')
    logger.info(f'export dataset {dataset_id} -> {out} ({n} paires)')
    return out


def _materialize_local_training_dataset(user_id, dataset_id, *, masked, destination):
    """Freeze local inputs before the potentially slow conversion/mask pass."""
    from . import training_snapshot
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(
        prefix=_LOCAL_STAGING_PREFIX, dir=destination.parent))
    owner = {
        'format': 'prep-my-avatar-local-training-staging',
        'version': 1,
        'pid': os.getpid(),
        'dataset_id': dataset_id,
        'created_at': datetime.now().astimezone().isoformat(),
    }
    (temporary / _LOCAL_STAGING_OWNER).write_text(
        json.dumps(owner), encoding='utf-8')
    try:
        snapshot_dir = temporary / 'snapshot'
        snapshot = training_snapshot.capture(
            user_id, dataset_id, snapshot_dir)
        output = export_dataset_to_aitoolkit(
            user_id, dataset_id, masked=masked, dest_dir=destination,
            snapshot_dir=snapshot_dir)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return output, snapshot


def cleanup_abandoned_local_training_staging() -> int:
    """Remove launch staging whose durable owner process is no longer alive.

    Normal exception unwinding removes these directories in ``finally``.  The
    owner record makes SIGKILL/power-loss leftovers discoverable on the next
    startup without deleting staging still owned by a live process.
    """
    try:
        root = _datasets_dir()
    except RuntimeError:
        return 0
    if not root.is_dir():
        return 0
    removed = 0
    for candidate in root.glob(f'{_LOCAL_STAGING_PREFIX}*'):
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        try:
            owner = json.loads(
                (candidate / _LOCAL_STAGING_OWNER).read_text(encoding='utf-8'))
            pid = owner.get('pid') if isinstance(owner, dict) else None
        except (OSError, ValueError):
            pid = None
        if pid is not None and training._pid_alive(pid):
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        if not candidate.exists():
            removed += 1
    if removed:
        logger.info('removed %s abandoned local-training staging directories', removed)
    return removed


# --- Overrides STYLE (communs aux 3 familles) -----------------------------------
# Un LoRA de style n'a PAS de trigger (il teinte toute image dès qu'il est chargé) :
# on retire trigger_word de la config pour qu'ai-toolkit n'injecte rien dans les
# captions. Et on monte le caption dropout à 30 % : le modèle voit régulièrement
# l'image SANS caption, ce qui lie le rendu au LoRA lui-même plutôt qu'aux mots —
# la reco usuelle des styles sans trigger (le 5 % character sert l'association
# trigger→identité, sans objet ici).
_STYLE_CAPTION_DROPOUT = 0.30
