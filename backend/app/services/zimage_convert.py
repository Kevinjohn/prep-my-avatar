"""Conversion d'un checkpoint Z-Image ComfyUI (.safetensors single-file) vers le
format diffusers attendu par ai-toolkit, pour entraîner un LoRA sur un merge
custom.

S'appuie sur convert_comfy_zimage_to_diffusers.py (mapping OFFICIEL ComfyUI,
gate validé : 0 clé manquante), lancé avec le python d'ai-toolkit (diffusers
requis). Conversion lourde (~12 Go, quelques minutes) → faite une fois et mise
en cache sous <aitoolkit dir>/converted/<name>/, en thread d'arrière-plan.

Lifted from the parent project's app/services/zimage_convert.py for LoRA
Dataset Studio: the module-level CONVERTED_ROOT (hardcoded `F:\\AI\\aitoolkit\\
converted`) and the COMFYUI_OUTPUT_DIR-derived models root become live
`cfg`-backed accessors (no machine-specific default paths, per the plan's
Global Constraints) -- the converted-cache root now lives under the
configured ai-toolkit dir instead of a separate hardcoded drive.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .. import config as cfg
from ..job_queue import queue_manager
from .lora_training import (_aitoolkit_dir, _hf_home, _venv_python,
                            assert_free_disk, MIN_FREE_GB_CONVERT)

logger = logging.getLogger(__name__)

_CONVERTER = str(cfg.BACKEND_DIR / 'infer' / 'convert_comfy_zimage_to_diffusers.py')
_CONVERT_KEY = 'zimage_base_convert'  # system_state : statut de conversion en cours
_convert_lock = threading.Lock()      # sérialise l'acquisition du verrou de conversion
_active_conversions: set[str] = set()
_COMPLETE_MARKER = '.conversion-complete'


def _converted_root():
    return _aitoolkit_dir() / 'converted'


def _official_config() -> str | None:
    """config.json du transformer Z-Image-Turbo officiel (cache HF d'ai-toolkit).
    Présent dès qu'un entraînement officiel a tourné une fois."""
    g = glob.glob(os.path.join(str(_hf_home()), 'hub', 'models--Tongyi-MAI--Z-Image-Turbo',
                               'snapshots', '*', 'transformer', 'config.json'))
    return g[0] if g else None


def _resolve_merge(z_model: str) -> str | None:
    """Chemin absolu du .safetensors ComfyUI depuis une valeur z_model
    (ex. 'z image\\bigLove_zt3.safetensors'). Anti path-traversal : refuse '..'
    et les chemins absolus, et CONFINE le résultat sous models/ (realpath +
    commonpath) - un z_model forgé ne peut pas sortir du dossier des modèles."""
    if not z_model or os.path.isabs(z_model) or '..' in z_model.replace('\\', '/'):
        return None
    root = cfg.comfyui_dir('models')
    if not root:
        return None
    root_real = os.path.realpath(str(root))
    rel = z_model.replace('/', '\\')
    base = os.path.basename(rel)
    for sub in ('unet', 'diffusion_models'):
        for cand in (os.path.join(root_real, sub, rel), os.path.join(root_real, sub, 'z image', base)):
            real = os.path.realpath(cand)
            if os.path.isfile(real) and os.path.commonpath([root_real, real]) == root_real:
                return real
    return None


def _safe_name(z_model: str) -> str:
    """Nom du dossier de conversion dérivé du chemin COMPLET (sous-dossier inclus),
    pas du seul basename - sinon deux merges homonymes dans des sous-dossiers
    différents écraseraient la même conversion."""
    rel = z_model.replace('\\', '/').rsplit('.', 1)[0]
    safe = ''.join(c if (c.isalnum() or c in '_-') else '_' for c in rel).strip('_')
    return safe or 'base'


def converted_dir(z_model: str) -> str:
    return str(_converted_root() / _safe_name(z_model))


def _transformer_ready(root: Path) -> bool:
    """Le dossier diffusers porte-t-il un transformer utilisable (poids ET config
    présents et non vides) ?

    La MÊME question est posée aux deux bouts de la conversion : `convert` la pose
    au staging pour décider s'il pose le marqueur, `is_converted` la pose à la
    racine finale pour décider si la conversion peut être réutilisée. Les deux
    doivent s'accorder par contrat — une règle plus stricte d'un côté ferait poser
    un marqueur sur un dossier que l'autre refuserait ensuite (reconversion
    silencieuse à chaque lancement), et l'inverse ferait entraîner sur un
    transformer tronqué. Elle est donc écrite une fois."""
    weights = root / 'transformer' / 'diffusion_pytorch_model.safetensors'
    config = root / 'transformer' / 'config.json'
    return (weights.is_file() and weights.stat().st_size > 0
            and config.is_file() and config.stat().st_size > 0)


def _publish_convert_state(z_model, status: str, error: str | None = None) -> dict:
    """Écrit l'état de conversion lu par le poll UI, et le retourne.

    Clé et TTL énoncés une seule fois : les cinq points d'écriture (démarrage,
    succès, échec, échec de démarrage du worker, réconciliation post-crash)
    décrivent la même entrée system_state, et un TTL divergent sur l'un d'eux
    ferait disparaître le statut d'une conversion de 12 Go sous les yeux de
    l'utilisateur."""
    state = {'z_model': z_model, 'status': status}
    if error is not None:
        state['error'] = error
    queue_manager._set_system_state(_CONVERT_KEY, state, ttl_seconds=3600)
    return state


def is_converted(z_model: str) -> bool:
    root = Path(converted_dir(z_model))
    return (root / _COMPLETE_MARKER).is_file() and _transformer_ready(root)


def convert(z_model: str) -> str:
    """Convertit (BLOQUANT, plusieurs minutes). Retourne le dossier diffusers
    racine (à passer en name_or_path). Lève ValueError si échec."""
    if is_converted(z_model):
        return converted_dir(z_model)
    merge = _resolve_merge(z_model)
    if not merge:
        raise ValueError(f'base model not found on disk: {z_model}')
    official_config_path = _official_config()
    if not official_config_path:
        raise ValueError("config.json for Z-Image-Turbo is missing from the HF cache - first run "
                         "a training on the official base (this downloads the model)")
    final = Path(converted_dir(z_model))
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{final.name}.', suffix='.staging', dir=final.parent))
    logger.info(f'conversion base {z_model} -> {final}')
    try:
        proc = subprocess.run(
            [str(_venv_python()), _CONVERTER, merge, official_config_path,
             '--save', str(staging)], capture_output=True, text=True, timeout=2400)
        if proc.returncode != 0 or not _transformer_ready(staging):
            tail = (proc.stdout or '')[-600:] + ' | ' + (proc.stderr or '')[-600:]
            raise ValueError(f'conversion failed: {tail}')
        (staging / _COMPLETE_MARKER).write_text('ok\n', encoding='utf-8')
        previous = final.with_name(f'.{final.name}.previous')
        if previous.exists():
            shutil.rmtree(previous)
        if final.exists():
            final.replace(previous)
        try:
            staging.replace(final)
        except Exception:
            if previous.exists() and not final.exists():
                previous.replace(final)
            raise
        if previous.exists():
            shutil.rmtree(previous)
        return str(final)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


# --- Conversion en arrière-plan + statut (poll UI) ----------------------------
def convert_status() -> dict:
    state = queue_manager._get_system_state(_CONVERT_KEY, {}) or {}
    if state.get('status') != 'running':
        return state
    z_model = state.get('z_model')
    with _convert_lock:
        active = isinstance(z_model, str) and z_model in _active_conversions
    if active:
        return state
    if isinstance(z_model, str) and is_converted(z_model):
        return _publish_convert_state(z_model, 'done')
    return _publish_convert_state(z_model, 'error',
                                  'conversion was interrupted; retry the conversion')


def start_convert_async(app, z_model: str) -> None:
    """Lance la conversion dans un thread daemon ; statut suivi dans system_state
    (running/done/error). Refuse si une conversion tourne déjà."""
    if not _resolve_merge(z_model):
        raise ValueError(f'base model not found: {z_model}')
    # ~12 Go écrits : refuser tout de suite plutôt qu'un crash à 90 % qui laisse
    # un dossier diffusers incomplet (is_converted=False mais 10 Go consommés).
    assert_free_disk(_converted_root(), MIN_FREE_GB_CONVERT, 'the base conversion (~12 GB)')
    # Acquisition ATOMIQUE du verrou (check-then-set sous lock) : empêche deux
    # conversions 12 Go concurrentes (double-clic / 2 datasets en même temps).
    with _convert_lock:
        state = queue_manager._get_system_state(_CONVERT_KEY, {}) or {}
        if state.get('status') == 'running' and state.get('z_model') in _active_conversions:
            raise ValueError('a conversion is already in progress')
        _active_conversions.add(z_model)
        _publish_convert_state(z_model, 'running')

    def _run():
        with app.app_context():
            try:
                convert(z_model)
                _publish_convert_state(z_model, 'done')
                logger.info(f'conversion base terminée : {z_model}')
            except Exception as e:
                _publish_convert_state(z_model, 'error', str(e))
                logger.error(f'conversion base échouée ({z_model}) : {e}')
            finally:
                with _convert_lock:
                    _active_conversions.discard(z_model)

    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception as exc:
        with _convert_lock:
            _active_conversions.discard(z_model)
        _publish_convert_state(z_model, 'error',
                               f'conversion worker failed to start: {exc}')
        raise
