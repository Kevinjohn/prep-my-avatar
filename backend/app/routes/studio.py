"""Studio blueprint: dataset-agnostic checkpoint x strength comparison runs
(run_id-driven) across every trained LoRA — the cross-dataset selector +
comparison-run lifecycle. Per-dataset /dataset/<id>/lora-test/* routes live in
datasets.py (single-dataset sweep, same service).

No login — single local user (`cfg.LOCAL_USER`). `/run` and `/run/<id>/resume`
actually enqueue ComfyUI jobs, so they're gated on `capabilities.probe()`
(409 with a UI hint) — everything else (checkpoints/prompts listings, run
status, cancel) stays reachable even when ComfyUI is offline so run history
never goes dark.
"""
from flask import Blueprint, jsonify, request

from ..config import LOCAL_USER
from ..domain_errors import DomainValidationError
from ..services import lora_test_studio as lts
from ..utils.comfyui import get_zimage_models
from ._common import (_map_error, _payload_or_404, _require_comfyui,
                      _studio_arch_mismatch_response, _studio_missing_response)

bp = Blueprint('studio', __name__, url_prefix='/api/studio')


def _json_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise DomainValidationError('JSON body must be an object')
    return data


@bp.get('/base-models')
def studio_base_models():
    kind = (request.args.get('type') or 'zimage').lower()
    if kind == 'sdxl':
        return jsonify({'models': lts.list_sdxl_base_models()})
    if kind == 'krea':
        # Bases Krea locales ALTERNATIVES au UNET câblé de krea2_turbo.json (node 20).
        # « Official » (filename vide → z_model absent → node intact) en tête = défaut.
        # Aucune alternative sur disque → liste vide, le front masque le sélecteur.
        alts = lts.krea_alt_base_models()
        if not alts:
            return jsonify({'models': []})
        out = [{'filename': '', 'label': 'Official – Krea 2 Turbo'}]
        out += [{'filename': m, 'label': m.split('\\')[-1].rsplit('.', 1)[0]} for m in alts]
        return jsonify({'models': out})
    out = [{'filename': m, 'label': m.split('\\')[-1]} for m in get_zimage_models()]
    return jsonify({'models': out})


@bp.get('/checkpoints')
def studio_checkpoints():
    return jsonify({'loras': lts.list_all_testable_checkpoints(LOCAL_USER),
                    'max_images': lts.MAX_TEST_IMAGES})


@bp.get('/recent-prompts')
def studio_recent_prompts():
    """Prompts de test récents GLOBAUX (tous datasets) — alimente le menu
    « Recent prompts » du mode comparaison ET du studio riche."""
    return jsonify({'ok': True, 'prompts': lts.user_recent_prompts(LOCAL_USER)})


@bp.post('/recent-prompts/delete')
def studio_recent_prompts_delete():
    """Supprime un prompt récent (+ cellules/images) sur TOUS les datasets."""
    try:
        d = _json_object()
        prompt = d.get('prompt')
        if not isinstance(prompt, str):
            raise DomainValidationError('prompt must be a string')
        return jsonify({'ok': True,
                        'deleted': lts.delete_prompt_everywhere(LOCAL_USER, prompt)})
    except lts.StudioPartialPromptDelete as exc:
        return jsonify({'ok': False, 'partial': True, 'error': exc.reason,
                        'deleted': exc.deleted,
                        'completed_dataset_ids': exc.completed_dataset_ids,
                        'failed_dataset_id': exc.failed_dataset_id}), 503
    except ValueError as exc:
        return _map_error(exc)


@bp.post('/run')
def studio_run():
    gate = _require_comfyui()
    if gate:
        return gate
    try:
        d = _json_object()
        selections = d.get('selections') or []
        if not isinstance(selections, list) or any(
                not isinstance(selection, dict) for selection in selections):
            raise DomainValidationError('selections must be an array of objects')
        res = lts.create_comparison_run(
            LOCAL_USER, selections, d.get('strengths') or [],
            seed=d.get('seed'), prompt=d.get('prompt'), z_model=d.get('z_model'),
            aspects=d.get('aspects'), cfgs=d.get('cfgs'), steps_list=d.get('steps'),
            steps2_list=d.get('steps2'), count=d.get('count'),
            permanent_loras=d.get('permanent_loras'), batch_loras=d.get('batch_loras'),
            rebalance=d.get('rebalance'),
            rebalance_strength=d.get('rebalance_strength'),
            # Parité Generate — réglages globaux du run.
            negative=d.get('negative'), sampler=d.get('sampler'), scheduler=d.get('scheduler'),
            weight_dtype=d.get('weight_dtype'), enhancer=d.get('enhancer'),
            enhancer_strength=d.get('enhancer_strength'), detail_amount=d.get('detail_amount'),
            resolution_tier=d.get('resolution_tier'), init_image=d.get('init_image'),
            denoise=d.get('denoise'))
    except Exception as e:
        from ..services.lora_test_studio import (StudioArchMismatch,
                                                 StudioAssetsMissing,
                                                 StudioPartialLaunch)
        if isinstance(e, StudioArchMismatch):   # wrong-arch checkpoint → actionable 409
            return _studio_arch_mismatch_response(e)
        if isinstance(e, StudioAssetsMissing):  # models/nodes absent → actionable 409
            return _studio_missing_response(e)
        if isinstance(e, StudioPartialLaunch):
            return jsonify({'ok': False, 'error': e.reason, 'partial': True,
                            'created': e.created, 'run_id': e.run_id}), 503
        return _map_error(e)
    return jsonify({'ok': True, **{k: res[k] for k in ('created', 'seed', 'count', 'run_id')}})


@bp.get('/run/<run_id>/status')
def studio_run_status(run_id):
    payload = lts.studio_payload_run(LOCAL_USER, run_id)
    return _payload_or_404(payload)


@bp.post('/run/<run_id>/cancel')
def studio_run_cancel(run_id):
    return jsonify({'ok': True, 'cancelled': lts.cancel_run(LOCAL_USER, run_id=run_id)})


@bp.post('/run/<run_id>/resume')
def studio_run_resume(run_id):
    gate = _require_comfyui()
    if gate:
        return gate
    try:
        res = lts.resume_run(LOCAL_USER, run_id=run_id)
    except Exception as e:
        return _map_error(e)
    return jsonify({'ok': True, **res})
