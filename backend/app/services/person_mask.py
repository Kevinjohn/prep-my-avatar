"""Génération de masques « personne » via rembg (u2net), en SUBPROCESS dans un
interprete DEDIE (rembg absent du venv Flask). Le protocole subprocess/JSON
lui-meme vit dans app/services/ml_worker.py. CPU (onnxruntime) → ne touche pas le
GPU/ComfyUI.

Sert le MASKED TRAINING (méthode jandordoe) : un masque par image d'entraînement,
le fond pondéré à mask_min_value (0.1) côté ai-toolkit → l'identité se lie au
sujet, pas au décor."""
from __future__ import annotations
import logging
import os
import sys

from .. import config as cfg
from .ml_worker import run_json_worker

logger = logging.getLogger(__name__)

# mask_infer.py vit dans backend/infer/ (pas app/services/).
_SCRIPT = str(cfg.BACKEND_DIR / 'infer' / 'mask_infer.py')


def _mask_python() -> str:
    return cfg.get('masks.python') or sys.executable


def is_available() -> bool:
    from ..capabilities import probe_masks
    return probe_masks()['ok']


def generate_person_masks(image_paths, out_dir, timeout: int = 1200) -> dict:
    """Génère un masque PNG (même nom de base) par image dans `out_dir`.
    Retourne {'ok': bool, 'written': N, 'results': {path: state}}.
    Vide ({}) si indisponible/échec (JAMAIS bloquant — un entraînement sans
    masques reste un entraînement valide)."""
    image_paths = [p for p in (image_paths or []) if p and os.path.isfile(p)]
    if not image_paths or not is_available():
        return {}
    data, error = run_json_worker(
        _mask_python(), _SCRIPT, {"images": image_paths, "out_dir": out_dir},
        timeout=timeout, logger=logger, label='person_mask', noun='mask worker')
    if error is not None:
        # Non-blocking by contract: the caller trains without masks. The shared
        # runner has already logged WHY, which is the part that used to be lost.
        return {}
    if not data.get('ok'):
        logger.warning('person_mask: échec : %s', data.get('error'))
        return {}
    written = data.get('written')
    results = data.get('results')
    if (not isinstance(written, int) or isinstance(written, bool) or written < 0
            or not isinstance(results, dict)
            or any(not isinstance(k, str) or not isinstance(v, (str, dict))
                   for k, v in results.items())):
        logger.warning('person_mask: invalid worker response schema')
        return {}
    return data
