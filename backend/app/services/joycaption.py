"""JoyCaption Beta One — captioning de dataset LoRA via subprocess.

Le modèle (Llava 8B NF4) tourne dans le PYTHON DU VENV ai-toolkit (torch+transformers
+bitsandbytes), pas le Python de Flask. Le protocole subprocess/JSON lui-meme vit
dans app/services/ml_worker.py — ici on n'ajoute que HF_HOME et le cwd du script. On
caption tout le dataset en UN seul chargement de modèle (batch), sinon recharger le
8B par image serait inexploitable. Non-fatal : en cas d'indispo/échec, retourne {} et
le caller (`face_dataset_service.caption_images`) retombe sur Qwen3-VL (ou honore le
backend choisi dans les réglages)."""
from __future__ import annotations

import logging
import os
import time

from .. import config as cfg
from .ml_worker import run_json_worker

logger = logging.getLogger(__name__)

# joycaption_infer.py vit dans backend/infer/ (pas app/services/).
_SCRIPT = cfg.BACKEND_DIR / 'infer' / 'joycaption_infer.py'
MODEL_REVISION = 'ae2f01e137d62154dfa7192cc21d1c618023a2a2'


class CaptionResults(dict):
    """Caption mapping with per-image generation provenance."""

    def __init__(self, captions, provenance=None):
        super().__init__(captions)
        self.provenance = provenance or {}


def is_available() -> bool:
    """JoyCaption est utilisable si le venv ai-toolkit ET le script existent."""
    venv = cfg.aitoolkit_path('venv_python')
    return bool(venv) and venv.exists() and _SCRIPT.exists()


def caption_images_joycaption(paths, prompt: str | None = None,
                              max_tokens: int = 300, timeout: int = 1800,
                              seed: int | None = None,
                              revision: str = MODEL_REVISION) -> dict:
    """Caption une LISTE d'images en un seul chargement de modèle.
    Retourne {chemin: caption}. Vide si indispo/échec (non-fatal)."""
    paths = [p for p in (paths or []) if p and os.path.isfile(p)]
    if not paths or not is_available():
        return {}
    script = str(_SCRIPT)
    # HF_HOME = même cache que l'entraînement (modèle déjà téléchargé là).
    env = dict(os.environ, HF_HOME=str(cfg.aitoolkit_path('hf_home')), PYTHONIOENCODING='utf-8')
    started = time.monotonic()
    logger.info('joycaption: starting batch (%d image(s), timeout=%ss)', len(paths), timeout)
    data, error = run_json_worker(
        cfg.aitoolkit_path('venv_python'), script,
        {'images': paths, 'prompt': prompt, 'max_tokens': max_tokens,
         'seed': seed, 'revision': revision},
        timeout=timeout, logger=logger, label='joycaption', noun='captioner',
        env=env, cwd=os.path.dirname(script))
    if error is not None:
        # One ERROR line for every way the batch can die, carrying the two facts
        # the shared runner cannot know: how long the user waited, and over how
        # many images. An 1800s timeout with no elapsed time is unreadable.
        logger.error('joycaption: batch failed after %.1fs (%d image(s)): %s',
                     time.monotonic() - started, len(paths), error['detail'])
        return {}
    errors = data.get('errors') or {}
    captions_data = data.get('captions') or {}
    if not isinstance(errors, dict) or not isinstance(captions_data, dict):
        logger.warning('joycaption: invalid captions/errors schema')
        return {}
    if errors:
        logger.info('joycaption: %d erreur(s) image : %s',
                    len(errors), list(errors.values())[:3])
    if any(not isinstance(k, str) or not isinstance(v, str)
           for k, v in captions_data.items()):
        logger.warning('joycaption: invalid caption entry schema')
        return {}
    captions = {k: v.strip() for k, v in captions_data.items() if v}
    provenance = data.get('provenance') or {}
    if not isinstance(provenance, dict):
        logger.warning('joycaption: invalid provenance schema')
        return {}
    logger.info('joycaption: batch finished (%d/%d captioned, elapsed=%.1fs)',
                len(captions), len(paths), time.monotonic() - started)
    return CaptionResults(captions, provenance)
