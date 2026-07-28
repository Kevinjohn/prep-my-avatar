"""Normalization and effective-value policy for training settings."""
from __future__ import annotations

import json

from . import face_dataset_service as fds
from .lora_training import (
    VAE_TE_OVERRIDE_FAMILIES,
    _ALPHA_CHOICES,
    _DEFAULT_RANK,
    _DEFAULT_TIMESTEP,
    _DROPOUT_CHOICES,
    _EMA_CHOICES,
    _GRAD_ACCUM_CHOICES,
    _LR_SCHEDULER_CHOICES,
    _NETWORK_TYPE_CHOICES,
    _OPTIMIZER_CHOICES,
    _RANK_CHOICES,
    _RES_CHOICES,
    _SAVE_CHOICES,
    _TIMESTEP_TYPE_CHOICES,
    _WARMUP_CHOICES,
    _is_custom_weights,
    _safe_trigger,
    _train_type,
)

def _train_settings(ds) -> dict:
    """Parse le blob JSON `train_settings` en dict (jamais lève ; {} si absent/cassé)."""
    raw = getattr(ds, 'train_settings', None)
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def _lora_rank(ds, family) -> int:
    r = _train_settings(ds).get('rank')
    return r if r in _RANK_CHOICES else _DEFAULT_RANK.get(family, 32)


def _lora_alpha(rank, family) -> int:
    """ai-toolkit : alpha = rank (échelle 1.0) pour zimage/krea. SDXL garde son
    choix délibéré alpha = rank/2 (« demi-force », validé par la recherche)."""
    return max(1, rank // 2) if family == 'sdxl' else rank


def _lora_alpha_eff(ds, rank, family) -> int:
    """Alpha EFFECTIF : un `alpha` explicite dans train_settings prime sur le dérivé.
    Découpler alpha du rank = levier de LR « doux » (échelle effective = alpha/rank)."""
    a = _train_settings(ds).get('alpha')
    return a if a in _ALPHA_CHOICES else _lora_alpha(rank, family)


def _network_type_eff(ds) -> str:
    """'lora' (défaut) ou 'lokr' — validé contre l'enum ai-toolkit ; inconnu → 'lora'.
    LoKr est arch-générique (LokrModule sur toutes les familles), aucune garde
    par famille nécessaire."""
    t = _train_settings(ds).get('network_type')
    return t if t in _NETWORK_TYPE_CHOICES else 'lora'


def _network_block(ds, rank, family) -> dict:
    """Bloc `network` LoRA/LoKr partagé par les 5 job-configs : type + rank + alpha
    (override-aware) + dropout optionnel (régularisateur anti-overfit, clé omise quand
    off). LoKr = même bloc, seul `type` change ; lokr_factor reste au défaut ai-toolkit
    (-1 = auto) donc non émis."""
    net = {'type': _network_type_eff(ds), 'linear': rank,
           'linear_alpha': _lora_alpha_eff(ds, rank, family)}
    d = _train_settings(ds).get('dropout')
    if isinstance(d, (int, float)) and d in _DROPOUT_CHOICES:
        net['dropout'] = d
    return net


def _timestep_type_eff(ds, default: str) -> str:
    """Pondération des timesteps : override la valeur family-default si l'utilisateur en
    a choisi une valide (gardé à l'enum ai-toolkit ; inconnu → le défaut)."""
    t = _train_settings(ds).get('timestep_type')
    return t if t in _TIMESTEP_TYPE_CHOICES else default


def _optimizer_eff(ds) -> str:
    o = _train_settings(ds).get('optimizer')
    return o if o in _OPTIMIZER_CHOICES else 'adamw8bit'


def _lr_eff(ds) -> float:
    """Prodigy pilote le LR lui-même → convention lr≈1.0 ; les autres gardent 1e-4."""
    return 1.0 if _optimizer_eff(ds).startswith('prodigy') else 1e-4


def _grad_accum(ds) -> int:
    g = _train_settings(ds).get('grad_accum')
    return g if g in _GRAD_ACCUM_CHOICES else 1


def _lr_sched_fields(ds) -> dict:
    """{} par défaut (= 'constant' d'ai-toolkit). Sinon {lr_scheduler [+ lr_scheduler_params
    {num_warmup_steps} pour constant_with_warmup]} à fusionner dans le bloc train. Le warmup
    n'est câblé QUE pour constant_with_warmup : les schedulers torch (cosine/linear/constant)
    n'acceptent pas num_warmup_steps → le passer les ferait planter (cf. toolkit/scheduler.py)."""
    s = _train_settings(ds).get('lr_scheduler')
    if s not in _LR_SCHEDULER_CHOICES or s == 'constant':
        return {}
    out = {'lr_scheduler': s}
    if s == 'constant_with_warmup':
        w = _train_settings(ds).get('warmup')
        out['lr_scheduler_params'] = {'num_warmup_steps': w if w in _WARMUP_CHOICES else 100}
    return out


def _ema_eff(ds):
    """Décroissance EMA choisie (0.99/0.999) ou None (= off). Inconnu → None."""
    v = _train_settings(ds).get('ema')
    return v if v in _EMA_CHOICES else None


def _ema_fields(ds) -> dict:
    """{} par défaut (= ai-toolkit use_ema=False) → à fusionner dans le bloc `train`.
    Sinon {ema_config: {use_ema, ema_decay}} : moyenne mobile exponentielle des poids,
    checkpoints plus lisses (clés VÉRIFIÉES config_modules.py EMAConfig L794-797)."""
    v = _ema_eff(ds)
    if v is None:
        return {}
    return {'ema_config': {'use_ema': True, 'ema_decay': v}}


def _train_res(ds) -> list:
    return _RES_CHOICES.get(_train_settings(ds).get('resolution'), [768, 1024])


def _save_every(ds) -> int:
    v = _train_settings(ds).get('save_every')
    return v if v in _SAVE_CHOICES else 250


# Combien de saves intermédiaires ai-toolkit CONSERVE pendant le run (local et
# cloud) : au-delà, il supprime les plus anciens lui-même. L'historique (10)
# laissait s'accumuler ~10 Go de checkpoints par run Krea.
_MAX_SAVES_CHOICES = (2, 3, 4, 6, 10)


def _max_step_saves(ds) -> int:
    v = _train_settings(ds).get('max_step_saves')
    return v if v in _MAX_SAVES_CHOICES else 4


# --- Prompts de preview (sample) -----------------------------------------------
# ai-toolkit génère une image par prompt tous les `sample_every` steps pendant le
# run (dossier .../samples), pour voir le LoRA converger. Les défauts historiques
# décrivaient un VISAGE (« close-up portrait, headshot… ») — hors sujet pour un
# dataset « concept ». D'où un défaut distinct selon le kind, et un override total
# par l'utilisateur (Advanced options → Preview prompts).
_SAMPLE_EVERY_CHOICES = (100, 250, 500, 1000)
_MAX_SAMPLE_PROMPTS = 8   # 1 image générée / prompt / palier → borne le coût des previews

_DEFAULT_SAMPLE_PROMPTS_CHARACTER = [
    '{trigger}, close-up portrait, neutral expression',
    '{trigger}, headshot, soft studio light',
    '{trigger}, full body, walking outdoors, smiling',
    '{trigger}, sitting in a cafe, casual outfit',
]
# Un concept n'est pas un visage : on l'exerce seul sous quelques cadrages neutres
# (le vocabulaire « portrait / headshot » tirerait un LoRA non-visage hors sujet).
_DEFAULT_SAMPLE_PROMPTS_CONCEPT = [
    '{trigger}',
    '{trigger}, high detail, sharp focus',
    '{trigger}, wide shot',
    '{trigger}, cinematic lighting',
]


# Un style n'a PAS de trigger : le LoRA teinte toute image dès qu'il est chargé.
# Les previews sont donc des scènes génériques variées — si le style s'y voit,
# l'entraînement prend ; le vocabulaire portrait/headshot tirerait hors sujet.
_DEFAULT_SAMPLE_PROMPTS_STYLE = [
    'a woman reading in a sunlit cafe',
    'a city street at night, rain',
    'a mountain landscape, wide shot',
    'a still life of fruit on a wooden table',
]


def _default_sample_prompts(ds) -> list:
    if fds.is_style(ds):
        return list(_DEFAULT_SAMPLE_PROMPTS_STYLE)
    return list(_DEFAULT_SAMPLE_PROMPTS_CONCEPT if fds.is_concept(ds)
                else _DEFAULT_SAMPLE_PROMPTS_CHARACTER)


def _inject_trigger(prompt: str, trigger: str) -> str:
    """Une preview DOIT solliciter le LoRA : si la ligne ne mentionne pas déjà le
    trigger (insensible à la casse), on le préfixe — sinon l'image teste le modèle
    de base, pas l'entraînement en cours."""
    p = (prompt or '').strip()
    if not trigger:
        return p
    if not p:
        return trigger
    return p if trigger.lower() in p.lower() else f'{trigger}, {p}'


def _resolved_default_sample_prompts(ds, trigger) -> list:
    """Défauts (selon le kind) avec `{trigger}` substitué — pour l'aperçu UI."""
    if fds.is_style(ds):   # style : pas de trigger, jamais injecté
        return list(_default_sample_prompts(ds))
    return [_inject_trigger(line.replace('{trigger}', trigger), trigger)
            for line in _default_sample_prompts(ds)]


def _sample_prompts(ds, trigger) -> list:
    """Prompts de preview effectifs : liste custom de train_settings si présente,
    sinon défaut selon le kind. `{trigger}` (placeholder explicite) ET le trigger en
    clair sont gérés ; le trigger est auto-préfixé s'il manque. Toujours ≥1 prompt,
    ≤_MAX_SAMPLE_PROMPTS (borne le nombre d'images générées par palier)."""
    raw = _train_settings(ds).get('sample_prompts')
    tmpl = raw if (isinstance(raw, list)
                   and any(isinstance(x, str) and x.strip() for x in raw)) \
        else _default_sample_prompts(ds)
    # STYLE : aucun trigger — le LoRA teinte tout, une preview générique le
    # sollicite déjà. Injecter le trigger polluerait le prompt d'un token inconnu.
    style = fds.is_style(ds)
    out = []
    for line in tmpl:
        if not isinstance(line, str) or not line.strip():
            continue
        resolved = line.replace('{trigger}', '' if style else trigger).strip(', ')
        # A style prompt may consist solely of the documented placeholder.  Once
        # the placeholder is removed there is no prompt left; do not resurrect
        # the literal ``{trigger}`` token as a fallback.
        if not resolved:
            continue
        out.append(resolved if style else _inject_trigger(resolved, trigger))
        if len(out) >= _MAX_SAMPLE_PROMPTS:
            break
    if out:
        return out
    return [_default_sample_prompts(ds)[0]] if style else [_inject_trigger('', trigger)]


def _sample_every(ds) -> int:
    v = _train_settings(ds).get('sample_every')
    return v if v in _SAMPLE_EVERY_CHOICES else 250


def launch_settings_snapshot(ds, family=None) -> dict:
    """Les réglages EFFECTIFS envoyés à ai-toolkit pour CE lancement — défauts
    résolus, pas les choix stockés. Stampé dans le registre de provenance
    (TrainingRunRecord.settings) par chaque launch local et cloud ; la page
    Runs l'affiche par run (« quels réglages sont partis ? »). Compact : les
    leviers experts n'apparaissent que s'ils dévient du défaut."""
    fam = family or _train_type(ds)
    rank = _lora_rank(ds, fam)
    snap = {
        # trigger_word is part of the reproducible RECIPE (someone re-running
        # the LoRA needs it) and is not a secret — it already appears in the
        # run name. The Share-config file surfaces it; settingsLine ignores it.
        'trigger': _safe_trigger(ds),
        'rank': rank,
        'alpha': _lora_alpha_eff(ds, rank, fam),
        'resolution': _train_res(ds),
        'save_every': _save_every(ds),
        'max_step_saves': _max_step_saves(ds),
        'optimizer': _optimizer_eff(ds),
        'lr': _lr_eff(ds),
    }
    if fam != 'sdxl':
        snap['timestep_type'] = _timestep_type_eff(ds, _DEFAULT_TIMESTEP.get(fam, 'sigmoid'))
    # Provenance: the ACTUAL custom paths that went to ai-toolkit (weights + the
    # SDXL-only VAE/TE overrides). Surfaced in the Runs hub and the ⎘ Share config
    # (both redact the home-dir prefix via redact_user_paths — no identity leaks).
    _weights = getattr(ds, 'train_base_model', None)
    if _is_custom_weights(_weights):
        snap['base_weights'] = _weights
    if fam in VAE_TE_OVERRIDE_FAMILIES:
        if getattr(ds, 'train_vae_path', None):
            snap['vae_path'] = ds.train_vae_path
        if getattr(ds, 'train_te_path', None):
            snap['te_name_or_path'] = ds.train_te_path
    s = _train_settings(ds)
    for k in ('dropout', 'lr_scheduler', 'warmup', 'grad_accum', 'sample_every'):
        if s.get(k):
            snap[k] = s[k]
    # Recipe levers surfaced only when they deviate from the default (LoRA / EMA off),
    # so the provenance line and ⎘ Share config stay compact — and the cloud run, which
    # stamps this same snapshot, carries them too.
    nt = _network_type_eff(ds)
    if nt != 'lora':
        snap['network_type'] = nt
    em = _ema_eff(ds)
    if em is not None:
        snap['ema'] = em
    return snap


def effective_train_settings(ds, family=None) -> dict:
    """Réglages pour la famille courante — ce que « Advanced options » affiche et
    ce que build_job_config enverra. `rank` = choix STOCKÉ (None = auto/défaut) pour
    que le select re-coche « Auto » ; `effective_rank`/`alpha`/`default_rank` = ce
    qui sera réellement utilisé (pour le libellé explicatif)."""
    fam = family or _train_type(ds)
    s = _train_settings(ds)
    stored_rank = s.get('rank') if s.get('rank') in _RANK_CHOICES else None
    eff_rank = stored_rank if stored_rank else _DEFAULT_RANK.get(fam, 32)
    res = s.get('resolution')
    trig = _safe_trigger(ds)
    stored_prompts = s.get('sample_prompts')
    return {'rank': stored_rank,                       # None → Auto (défaut family-aware)
            'effective_rank': eff_rank,                # ce qui part à ai-toolkit
            'alpha': _lora_alpha_eff(ds, eff_rank, fam),   # alpha EFFECTIF (override-aware) — libellé
            'default_rank': _DEFAULT_RANK.get(fam, 32),
            # --- Expert levers (None/off = comportement actuel ; le select recoche « Auto ») ---
            'alpha_setting': s.get('alpha') if s.get('alpha') in _ALPHA_CHOICES else None,
            'default_alpha': _lora_alpha(eff_rank, fam),
            'alpha_choices': list(_ALPHA_CHOICES),
            'dropout': s.get('dropout') if s.get('dropout') in _DROPOUT_CHOICES else None,
            'dropout_choices': list(_DROPOUT_CHOICES),
            'timestep_type': s.get('timestep_type') if s.get('timestep_type') in _TIMESTEP_TYPE_CHOICES else None,
            'timestep_type_choices': list(_TIMESTEP_TYPE_CHOICES),
            'default_timestep_type': _DEFAULT_TIMESTEP.get(fam),   # None pour sdxl → contrôle masqué
            'timestep_type_supported': fam != 'sdxl',
            'optimizer': s.get('optimizer') if s.get('optimizer') in _OPTIMIZER_CHOICES else None,   # None → adamw8bit
            'optimizer_choices': list(_OPTIMIZER_CHOICES),
            'lr_scheduler': s.get('lr_scheduler') if s.get('lr_scheduler') in _LR_SCHEDULER_CHOICES else None,  # None → constant
            'lr_scheduler_choices': list(_LR_SCHEDULER_CHOICES),
            'warmup': s.get('warmup') if s.get('warmup') in _WARMUP_CHOICES else None,
            'warmup_choices': list(_WARMUP_CHOICES),
            'grad_accum': s.get('grad_accum') if s.get('grad_accum') in _GRAD_ACCUM_CHOICES else None,   # None → 1
            'grad_accum_choices': list(_GRAD_ACCUM_CHOICES),
            'network_type': s.get('network_type') if s.get('network_type') in _NETWORK_TYPE_CHOICES else None,  # None → lora
            'network_type_choices': list(_NETWORK_TYPE_CHOICES),
            # LoKr is arch-generic in ai-toolkit → offered on every family. The flag
            # mirrors timestep_type_supported so the UI can gate a future family with
            # one line; today it is always True (no family refuses lokr).
            'network_type_supported': True,
            'ema': s.get('ema') if s.get('ema') in _EMA_CHOICES else None,   # None → off
            'ema_choices': list(_EMA_CHOICES),
            'resolution': res if res in _RES_CHOICES else '768,1024',
            'save_every': _save_every(ds),
            'max_step_saves': _max_step_saves(ds),
            'max_step_saves_choices': list(_MAX_SAVES_CHOICES),
            'sample_every': _sample_every(ds),
            # liste STOCKÉE brute (telle que tapée) ou [] → textarea vide = « défauts ».
            'sample_prompts': stored_prompts if isinstance(stored_prompts, list) else [],
            # défaut résolu (kind + trigger courant) : placeholder/aperçu quand vide.
            'sample_prompts_default': _resolved_default_sample_prompts(ds, trig),
            'sample_every_choices': list(_SAMPLE_EVERY_CHOICES),
            'max_sample_prompts': _MAX_SAMPLE_PROMPTS}
