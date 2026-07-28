"""Bounded Studio poll and run-history payload assembly."""
from __future__ import annotations

from typing import Any, Protocol

from ..extensions import db
from ..models import FaceDataset, LoraTestImage
from ..utils.comfyui import family_of_lora, format_trained_lora_label
from . import face_dataset_service as fds
from .studio_scoring import _wilson_lower_bound


class PayloadRuntime(Protocol):
    """Explicit interface supplied by the Studio coordinator."""

    TEST_ASPECTS: dict[str, tuple[int, int]]
    DEFAULT_ASPECT: str
    CFG_CHOICES: list[float]
    DEFAULT_CFG: float
    STEPS_CHOICES: list[int]
    DEFAULT_STEPS: int
    MAX_TEST_IMAGES: int

    def available_families(self, dataset) -> list[dict]: ...
    def resolve_family(self, dataset, requested, families=None) -> str: ...
    def list_sdxl_base_models(self) -> list[dict]: ...
    def krea_alt_base_models(self) -> list[str]: ...
    def basename(self, path: str) -> str: ...
    def get_zimage_models(self) -> list[str]: ...
    def list_test_checkpoints(self, dataset, family=None) -> list[dict]: ...
    def permanent_lora_candidates(self, family) -> list[dict]: ...
    def identity_prompt(self, dataset) -> str: ...
    def active_run_count(self, dataset_id=None) -> int: ...
    def user_recent_prompts(self, user_id, limit=10) -> list[dict]: ...
    def gpu_busy_reason(self) -> str | None: ...
    def batch_lora_label(self, row) -> str | None: ...
    def cell_scores(self, dataset_id, family=None, rows=None) -> list[dict]: ...
    def training_feedback(self, user_id, dataset_id, family=None) -> dict | None: ...
    def best_for_family(self, dataset, family) -> dict | None: ...
    def __getattr__(self, name: str) -> Any: ...


# --- Payload (poll) ------------------------------------------------------------
def studio_payload(runtime, user_id, dataset_id, family=None, run_id=None) -> dict | None:
    """Everything the studio panel needs in one poll, SCOPÉ à une FAMILLE (pipeline).

    `family` = ZIT/SDXL/Krea sélectionnée par l'utilisateur ; résolue à la famille
    effective (parmi celles réellement présentes pour ce dataset). Checkpoints, grille,
    scores, best et bases sont tous restreints à cette famille - un même dataset
    entraîné sous plusieurs pipelines n'en mélange plus les résultats. `available_families`
    liste les familles présentes (pour le sélecteur) ; `family` renvoie l'effective."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        return None
    fams = runtime.available_families(ds)
    eff = runtime.resolve_family(ds, family, fams)
    if run_id:
        rows = (LoraTestImage.query.filter_by(dataset_id=dataset_id, run_id=run_id)
                .order_by(LoraTestImage.id.asc()).all())
        rows = [row for row in rows
                if (family_of_lora(row.checkpoint) or 'zimage') == eff]
    else:
        # Inspect only a bounded recent window to select the newest run for this
        # family. The hot poll then returns and aggregates that run alone.
        recent = (LoraTestImage.query.filter_by(dataset_id=dataset_id)
                  .order_by(LoraTestImage.id.desc()).limit(500).all())
        latest = next((row for row in recent
                       if (family_of_lora(row.checkpoint) or 'zimage') == eff), None)
        selected = latest.run_id if latest else None
        if selected:
            rows = [row for row in recent if row.run_id == selected]
            rows.reverse()
        elif latest:
            legacy_key = (latest.run_seed, latest.prompt)
            rows = [row for row in recent
                    if row.run_id is None and (row.run_seed, row.prompt) == legacy_key]
            rows.reverse()
        else:
            rows = []
    selected_run_id = rows[0].run_id if rows else None
    best = runtime.best_for_family(ds, eff)
    # Pool de bases selon la FAMILLE effective : SDXL → checkpoints SDXL (forme
    # {value,label}) ; Krea → base fixe (UNET du workflow, aucun sélecteur) ; sinon
    # modèles Z-Image. `train_type` = famille effective (le front adapte picker + handoff).
    if eff == 'sdxl':
        z_models = [{'value': m['filename'], 'label': m['label']}
                    for m in runtime.list_sdxl_base_models()]
    elif eff == 'krea':
        # Bases Krea locales ALTERNATIVES au UNET câblé. « Official » (value vide →
        # z_model None → node 20 intact) reste en tête = défaut. Aucune alternative
        # sur disque → liste vide, le front cache le sélecteur (comportement historique).
        _alts = runtime.krea_alt_base_models()
        z_models = ([{'value': '', 'label': 'Official – Krea 2 Turbo'}]
                    + [{'value': m, 'label': runtime.basename(m).rsplit('.', 1)[0]} for m in _alts]
                    if _alts else [])
    else:
        z_models = [{'value': m, 'label': runtime.basename(m).rsplit('.', 1)[0]}
                    for m in runtime.get_zimage_models()]
    return {
        'checkpoints': runtime.list_test_checkpoints(ds, eff),
        'trigger_word': ds.trigger_word,
        'train_type': eff,
        'family': eff,
        # Familles entraînées de ce dataset (sélecteur) : [{family,label,count}].
        'available_families': fams,
        # LoRA « always-on » disponibles pour cette famille (style/utilitaire, hors batch).
        'permanent_loras': runtime.permanent_lora_candidates(eff),
        'prompt': runtime.identity_prompt(ds),
        'z_models': z_models,
        'aspects': list(runtime.TEST_ASPECTS.keys()),
        'default_aspect': runtime.DEFAULT_ASPECT,
        'cfg_choices': runtime.CFG_CHOICES, 'default_cfg': runtime.DEFAULT_CFG,
        'steps_choices': runtime.STEPS_CHOICES, 'default_steps': runtime.DEFAULT_STEPS,
        # 2e passe (detail daemon) : exposée UNIQUEMENT pour SDXL (le workflow HQ a deux
        # passes). NULL sinon → le frontend ne montre pas le 2e picker de steps.
        'steps2_choices': (runtime.STEPS_CHOICES if eff == 'sdxl' else None),
        'default_steps2': (runtime.DEFAULT_STEPS if eff == 'sdxl' else None),
        'max_images': runtime.MAX_TEST_IMAGES,
        'selected_run_id': selected_run_id,
        'cells': [{'id': r.id, 'checkpoint': r.checkpoint,
                   'label': format_trained_lora_label(r.checkpoint) or runtime.basename(r.checkpoint).rsplit('.', 1)[0],
                   'strength': r.strength, 'aspect': r.aspect, 'filename': r.filename,
                   'rating': r.rating, 'seed': r.seed, 'run_seed': r.run_seed,
                   'run_id': r.run_id, 'status': r.status,
                   'training_run_record_id': r.training_run_record_id,
                   'prompt': r.prompt, 'z_model': r.z_model,
                   'z_model_label': (runtime.basename(r.z_model).rsplit('.', 1)[0] if r.z_model else None),
                   'cfg': r.cfg, 'steps': r.steps, 'steps2': r.steps2,
                   'batch_lora': runtime.batch_lora_label(r),
                   # Why the tile is empty (failed cells only) → shown on hover (P0-b).
                   'error': r.error if r.status == 'failed' else None,
                   'face_score': r.face_score, 'face_state': r.face_state}
                  for r in rows],
        # cell_scores scanne la table une fois (filtré famille) → partagé entre
        # best_cell/best_preset/best_per_checkpoint (sinon 4 scans identiques).
        'scores': (_scores := runtime.cell_scores(dataset_id, family=eff, rows=rows)),
        'best_cell': runtime.best_cell(dataset_id, scores=_scores),
        'best_preset': runtime.best_preset(dataset_id, scores=_scores),
        'best_per_model': runtime.best_per_checkpoint(dataset_id, scores=_scores),
        # Comparaison équitable des bases (par z_model) + détail par (checkpoint, base).
        'model_comparison': runtime.model_comparison(dataset_id, scores=_scores),
        'checkpoint_breakdown': runtime.checkpoint_model_breakdown(dataset_id, scores=_scores),
        # Classement facial objectif des checkpoints (« best epoch », cellules scorées).
        'face_ranking': runtime.face_ranking(dataset_id, eff, rows=rows),
        'pending': runtime.active_run_count(dataset_id),
        # This payload and its resume control are scoped to the selected family.
        'resumable': min(runtime.MAX_TEST_IMAGES, sum(
            1 for r in rows if r.status in ('cancelled', 'failed'))),
        # Prompts récents distincts (family-agnostiques) pour recharger/relancer un
        # run - GLOBAUX à l'utilisateur (tous datasets), plus cloisonnés par dataset.
        'recent_prompts': runtime.user_recent_prompts(ds.user_id),
        'gpu_busy': runtime.gpu_busy_reason(),
        'best_settings': best,
        # Human votes tied back to immutable training launches, with
        # evidence-gated next-run recommendations.
        'training_feedback': runtime.training_feedback(user_id, dataset_id, eff),
    }


def studio_run_history(runtime, user_id, dataset_id, family=None, cursor=None, limit=20) -> dict | None:
    """Return bounded run summaries for explicit history selection."""
    ds = fds.get_dataset(user_id, dataset_id)
    if ds is None:
        return None
    eff = runtime.resolve_family(ds, family, runtime.available_families(ds))
    limit = max(1, min(100, int(limit)))
    query = (db.session.query(LoraTestImage.run_id, db.func.max(LoraTestImage.id))
             .filter(LoraTestImage.dataset_id == dataset_id,
                     LoraTestImage.run_id.isnot(None)))
    if cursor is not None:
        query = query.filter(LoraTestImage.id < int(cursor))
    candidates = query.group_by(LoraTestImage.run_id).order_by(
        db.func.max(LoraTestImage.id).desc()).limit(limit * 4 + 1).all()
    runs = []
    for run_id_value, newest_id in candidates:
        newest = db.session.get(LoraTestImage, newest_id)
        if newest is None or (family_of_lora(newest.checkpoint) or 'zimage') != eff:
            continue
        rows = LoraTestImage.query.filter_by(
            dataset_id=dataset_id, run_id=run_id_value).all()
        runs.append({
            'run_id': run_id_value,
            'newest_id': newest_id,
            'prompt': newest.prompt,
            'cells': len(rows),
            'pending': sum(row.status == 'pending' and not row.filename for row in rows),
        })
        if len(runs) > limit:
            break
    page = runs[:limit]
    return {
        'runs': page,
        'next_cursor': page[-1]['newest_id'] if len(runs) > limit else None,
        'family': eff,
    }


def lora_net_scores(runtime, run_id) -> list[dict]:
    """Classement PAR-LoRA d'un run : agrège les votes des cellules par dataset_id
    (= un LoRA). Trié par score net (likes - dislikes) puis likes, décroissant."""
    rows = LoraTestImage.query.filter_by(run_id=run_id).filter(
        LoraTestImage.filename.isnot(None)).all()
    agg = {}
    for r in rows:
        a = agg.setdefault(r.dataset_id, {'dataset_id': r.dataset_id, 'likes': 0,
                                          'dislikes': 0, 'voted': 0, 'total': 0,
                                          'lora_label': format_trained_lora_label(r.checkpoint)
                                          or runtime.basename(r.checkpoint).rsplit('.', 1)[0]})
        a['total'] += 1
        if r.rating == 1:
            a['likes'] += 1
            a['voted'] += 1
        elif r.rating == -1:
            a['dislikes'] += 1
            a['voted'] += 1
    for a in agg.values():
        a['net'] = a['likes'] - a['dislikes']
        a['wilson'] = _wilson_lower_bound(a['likes'], a['voted'])
        ds = db.session.get(FaceDataset, a['dataset_id'])
        a['dataset_name'] = ds.name if ds else f"#{a['dataset_id']}"
    return sorted(agg.values(), key=lambda a: (a['net'], a['likes']), reverse=True)


def studio_payload_run(runtime, user_id, run_id) -> dict | None:
    """Payload d'un run (mono ou multi-LoRA). Requêté par run_id + ajoute le
    classement par-LoRA et la liste des LoRA présents."""
    rows = (LoraTestImage.query.filter_by(run_id=run_id)
            .order_by(LoraTestImage.id.asc()).all())
    if not rows:
        return None
    ds_ids = {r.dataset_id for r in rows}
    owned = {d.id for d in FaceDataset.query.filter(FaceDataset.user_id == str(user_id),
             FaceDataset.id.in_(ds_ids)).all()}
    if ds_ids - owned:
        return None
    def _lbl(d):
        return next((runtime.basename(r.checkpoint).rsplit('.', 1)[0] for r in rows if r.dataset_id == d), str(d))
    def _name(d):
        ds = db.session.get(FaceDataset, d)
        return ds.name if ds else str(d)
    return {
        'run_id': run_id,
        'loras': [{'dataset_id': d, 'lora_label': _lbl(d), 'dataset_name': _name(d)}
                  for d in sorted(ds_ids)],
        'cells': [{'id': r.id, 'dataset_id': r.dataset_id, 'checkpoint': r.checkpoint,
                   'label': runtime.basename(r.checkpoint).rsplit('.', 1)[0], 'strength': r.strength,
                   'aspect': r.aspect, 'filename': r.filename, 'rating': r.rating, 'seed': r.seed,
                   'run_seed': r.run_seed, 'status': r.status, 'prompt': r.prompt,
                   'training_run_record_id': r.training_run_record_id,
                   'z_model': r.z_model, 'cfg': r.cfg, 'steps': r.steps, 'steps2': r.steps2,
                   'batch_lora': runtime.batch_lora_label(r),
                   'error': r.error if r.status == 'failed' else None} for r in rows],
        'lora_ranking': lora_net_scores(runtime, run_id),
        'pending': sum(1 for r in rows if r.status == 'pending' and not r.filename),
        'resumable': sum(1 for r in rows if r.status in ('cancelled', 'failed')),
        'gpu_busy': runtime.gpu_busy_reason(),
    }
