"""Studio cancellation and faithful persisted-cell resume lifecycle."""
from __future__ import annotations

import random
from typing import Protocol

from ..extensions import db
from ..gpu_window import GpuBusyError
from ..job_queue import queue_manager
from ..models import LoraTestImage
from ..utils.comfyui import family_of_lora
from . import face_dataset_service as fds
from .studio_cells import EffectiveStudioCell


class LifecycleRuntime(Protocol):
    """Coordinator functionality needed by lifecycle operations."""

    MAX_TEST_IMAGES: int
    TEST_ASPECTS: dict[str, tuple[int, int]]
    DEFAULT_ASPECT: str

    def gpu_busy_reason(self) -> str | None: ...
    def active_run_count(self, dataset_id=None) -> int: ...
    def list_test_checkpoints(self, dataset, family=None) -> list[dict]: ...
    def list_sdxl_base_models(self) -> list[dict]: ...
    def get_krea_models(self) -> list[str]: ...
    def get_zimage_models(self) -> list[str]: ...
    def aspect_dims(self, aspect, family=None, resolution_tier=None): ...
    def identity_prompt(self, dataset) -> str: ...
    def launch_effective_cell(self, user_id, cell, allowed, *, row=None): ...


def run_owned(user_id, run_id) -> bool:
    """Single-user app: every run belongs to the local user - no cross-user
    ownership DB to consult (SRC checked every cell's dataset against
    `user_id`)."""
    return True


def cancel_run(runtime, user_id, dataset_id=None, run_id=None) -> int:
    """Stoppe les cellules en vol : annule les jobs de queue et marque les
    cellules 'cancelled' (au lieu de les supprimer) pour pouvoir REPRENDRE le
    run plus tard avec leurs réglages exacts (prompt/seed/modèle/format).
    Retourne le nombre stoppé.

    Cible : si `run_id` est fourni, opère sur ce run ; sinon, comportement
    historique par `dataset_id`."""
    if run_id is not None:
        if not run_owned(user_id, run_id):
            return 0
        rows = (LoraTestImage.query
                .filter_by(run_id=run_id, status='pending')
                .filter(LoraTestImage.filename.is_(None)).all())
    else:
        ds = fds.get_dataset(user_id, dataset_id)
        if not ds:
            return 0
        rows = (LoraTestImage.query
                .filter_by(dataset_id=dataset_id, status='pending')
                .filter(LoraTestImage.filename.is_(None)).all())
    n = 0
    for img in rows:
        if img.job_id:
            try:
                queue_manager.cancel_job(img.job_id, str(user_id), 'image')
            except Exception:
                pass
        img.status = 'cancelled'
        img.job_id = None
        n += 1
    db.session.commit()
    return n


def resume_run(runtime, user_id, dataset_id=None, run_id=None, family=None) -> dict:
    """Reprend un run stoppé : ré-enfile toutes les cellules 'cancelled'/'failed'
    avec LEURS réglages stockés (même prompt/seed/modèle/format/strength). C'est
    le « relancer l'ancien run avec le même prompt » demandé.

    Cible : si `run_id` est fourni, ré-enfile ce run ; sinon, comportement
    historique par `dataset_id`."""
    if run_id is not None:
        if not run_owned(user_id, run_id):
            raise ValueError('run not found')
        reason = runtime.gpu_busy_reason()
        if reason:
            raise GpuBusyError(reason)
        if runtime.active_run_count():
            raise ValueError('a test run is already in progress')
        rows = (LoraTestImage.query.filter_by(run_id=run_id)
                .filter(LoraTestImage.status.in_(['cancelled', 'failed'])).all())
    else:
        ds = fds.get_dataset(user_id, dataset_id)
        if not ds:
            raise ValueError('dataset not found')
        reason = runtime.gpu_busy_reason()
        if reason:
            raise GpuBusyError(reason)
        if runtime.active_run_count(dataset_id):
            raise ValueError('a test run is already in progress')
        rows = (LoraTestImage.query.filter_by(dataset_id=dataset_id)
                .filter(LoraTestImage.status.in_(['cancelled', 'failed'])).all())
        if family:
            requested_family = str(family).lower()
            rows = [row for row in rows
                    if (family_of_lora(row.checkpoint) or '').lower() == requested_family]
    # A resume consumes the shared generation queue just like a new launch and
    # therefore observes the same per-action image budget.
    remaining = max(0, len(rows) - runtime.MAX_TEST_IMAGES)
    rows = rows[:runtime.MAX_TEST_IMAGES]
    if not rows:
        raise ValueError('no cell to resume')
    # Le run_id peut couvrir plusieurs datasets (run multi-LoRA) → on résout le
    # dataset PAR cellule, avec un cache. La FAMILLE de chaque cellule est déduite du
    # dossier de son checkpoint (sdxl/krea/z image) - pas du train_type du dataset, qui
    # peut différer quand le même dataset a été entraîné sous plusieurs pipelines. La
    # whitelist est donc cachée par (dataset, famille).
    ds_cache, allowed_cache = {}, {}
    _sdxl_bases = None  # liste des bases SDXL, calculée à la demande (cache)

    def _ds(did):
        if did not in ds_cache:
            ds_cache[did] = fds.get_dataset(user_id, did)
        return ds_cache[did]

    def _allowed(did, fam):
        key = (did, fam)
        if key not in allowed_cache:
            d = _ds(did)
            allowed_cache[key] = {c['filename'] for c in runtime.list_test_checkpoints(d, fam)} if d else set()
        return allowed_cache[key]
    n = 0
    for img in rows:
        cell_ds = _ds(img.dataset_id)
        # Famille = dossier du checkpoint (repli train_type) → whitelist + base + dims + workflow.
        cell_family = (family_of_lora(img.checkpoint)
                       or getattr(cell_ds, 'train_type', None) or 'zimage').lower()
        allowed = _allowed(img.dataset_id, cell_family)
        if not cell_ds or img.checkpoint not in allowed:
            continue  # dataset/checkpoint disparu → on saute
        # Pool de bases selon la famille de CETTE cellule (SDXL → bases SDXL ; Krea →
        # base fixe ; sinon Z-Image), sinon un resume SDXL retomberait sur une base Z-Image.
        if cell_family == 'sdxl':
            if _sdxl_bases is None:
                _sdxl_bases = [m['filename'] for m in runtime.list_sdxl_base_models()]
            cell_models = _sdxl_bases
        elif cell_family == 'krea':
            # None en tête : les cellules legacy (z_model NULL) et celles dont la
            # base locale a disparu du disque retombent sur le UNET câblé, jamais
            # sur un modèle arbitraire.
            cell_models = [None] + runtime.get_krea_models()
        else:
            cell_models = runtime.get_zimage_models()
        z_model = (img.z_model if (img.z_model and img.z_model in cell_models)
                   else (cell_models[0] if cell_models else None))
        aspect = img.aspect if img.aspect in runtime.TEST_ASPECTS else runtime.DEFAULT_ASPECT
        # Palier de résolution persisté → mêmes dims qu'au 1er run (sinon table fixe).
        width, height = runtime.aspect_dims(aspect, cell_family, getattr(img, 'resolution_tier', None))
        prompt = (img.prompt or '').strip() or runtime.identity_prompt(cell_ds)
        seed = img.seed or random.randint(1, 2**31 - 1)
        cell = EffectiveStudioCell.from_row(
            img, family=cell_family, width=width, height=height,
            z_model=z_model, prompt=prompt, seed=seed,
            trigger_word=getattr(cell_ds, 'trigger_word', None))
        try:
            runtime.launch_effective_cell(user_id, cell, allowed, row=img)
            n += 1
        except Exception as e:
            img.status = 'failed'
            img.error = str(e)[:400] or 'resume failed'
            db.session.commit()
    return {'resumed': n, 'remaining_resumable': remaining}
