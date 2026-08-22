"""Scoring de ressemblance faciale via InsightFace antelopev2, en SUBPROCESS dans un
interprete DEDIE (insightface absent du venv Flask). Le protocole subprocess/JSON
lui-meme vit dans app/services/ml_worker.py. CPU -> ne touche pas le GPU/ComfyUI."""
from __future__ import annotations
import logging
import os
import sys

from .. import config as cfg
from .ml_worker import run_json_worker

logger = logging.getLogger(__name__)

# face_score_infer.py vit dans backend/infer/ (pas app/services/).
_SCRIPT = str(cfg.BACKEND_DIR / 'infer' / 'face_score_infer.py')


def _scoring_python() -> str:
    return cfg.get('face_scoring.python') or sys.executable


def is_available() -> bool:
    from ..capabilities import probe_face_scoring
    return probe_face_scoring()['ok']


def score_dataset_faces(ref_path, image_paths, timeout: int = 900, ref_paths=None):
    """Retourne ({path: {state, sim?, det, bbox_frac, yaw}}, error|None).

    `error` est None quand le scorer a tourne, sinon {'kind', 'detail'} :
    'unavailable' (extras ML absents), 'failed' (subprocess/JSON casse — detail
    = derniere ligne du traceback), 'ref_unusable' (la reference n'a pas de
    visage exploitable). Les echecs restent NON-fatals ({} + error) mais
    doivent etre VISIBLES : les avaler en {} muet transformait un scorer casse
    en « Face scoring done — 0/14 » avec toast vert (user-reported)."""
    image_paths = [p for p in (image_paths or []) if p and os.path.isfile(p)]
    if not ref_path or not os.path.isfile(ref_path) or not image_paths:
        return {}, None
    if not is_available():
        return {}, {'kind': 'unavailable',
                    'detail': 'face scoring is not installed (Quality tools step in Setup)'}
    refs = []
    for candidate in list(ref_paths or []) + [ref_path]:
        if candidate and os.path.isfile(candidate) and candidate not in refs:
            refs.append(candidate)
    data, error = run_json_worker(
        _scoring_python(), _SCRIPT,
        {"ref": ref_path, "refs": refs, "images": image_paths,
         "models_root": cfg.get('face_scoring.models_root') or None},
        timeout=timeout, logger=logger, label='face_similarity', noun='scorer')
    if error is not None:
        return {}, error
    if not data.get('ref_ok'):
        logger.warning('face_similarity: ref inutilisable : %s', data.get('error'))
        return {}, {'kind': 'ref_unusable',
                    'detail': data.get('error') or 'no usable face in the reference photo'}
    results = data.get('results') or {}
    if (not isinstance(results, dict)
            or any(not isinstance(key, str) or not isinstance(value, dict)
                   for key, value in results.items())):
        return {}, {'kind': 'failed', 'detail': 'invalid scorer results schema'}
    return results, None
