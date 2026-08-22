"""LoRA Test Studio - checkpoint x strength sweep over the Z-Image pipeline.

MVP of the « Studio de test de LoRA » (design 2026-06-12) : pour un dataset
entraîné, balaye une grille checkpoint x strength en générations Z-Image
(seed fixe, 1 prompt identité), note 👍/👎 chaque cellule et persiste les
réglages gagnants sur le FaceDataset.

Clones the dataset fan-out mechanics exactly:
  - row committed BEFORE enqueue (no orphan jobs),
  - queue jobs tagged with metadata ``is_lora_test`` and linked back on
    completion/failure/cancel by ``link_completed_test_image`` (called from
    job_queue, same anchor point as ``is_dataset``),
  - completed files moved to the per-dataset folder,
  - free (never debited) but hard-capped (MAX_TEST_IMAGES per run, one active
    run per dataset, refused while training/vision holds the GPU).

This module is the COORDINATOR. The work lives in siblings, and this file
re-exports their entry points so routes, tests, and the sibling modules
themselves reach one stable surface:
  - ``studio_discovery``  - which checkpoints/bases exist for a dataset+family;
  - ``studio_scoring``    - votes, rankings, feedback, best settings;
  - ``studio_payload``    - the poll payloads;
  - ``studio_lifecycle``  - cancel/resume;
  - ``studio_cells`` / ``studio_launch`` / ``studio_storage`` - the launch path.
Those siblings receive THIS module as their ``runtime`` argument, so a name they
call resolves through this module's globals - which is what keeps
``monkeypatch.setattr(lts, 'get_krea_models', ...)`` working. Anything extracted
out of here must stay reachable as an attribute of this module for that reason.

Workflow JSON is resolved live (``cfg.BACKEND_DIR / 'workflows' / '<name>.json'``),
as is the ComfyUI output dir (`_comfy_output_dir()`), so a config change needs no
reimport. Single-user app: `_run_owned` / `_owned_test_image` are deliberate
no-ops kept as the single place a multi-user check would land.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import random
import re
import sys
import threading
import uuid
from pathlib import Path

from .. import config as cfg
from ..extensions import db
from ..domain_errors import DomainValidationError
from ..gpu_window import GpuBusyError
from ..models import FaceDataset, LoraTestImage
from . import face_dataset_service as fds
from . import lora_training as lt
from . import trash
from .studio_launch import LaunchOptions, LaunchSubject, launch_matrix
from . import studio_discovery as _discovery
from . import studio_scoring as _scoring
from . import studio_payload as _payload
from . import studio_storage as _storage
from . import studio_lifecycle as _lifecycle
from ..job_queue import queue_manager
from ..utils.comfyui import (KREA_ALLOWED_SAMPLERS, KREA_ALLOWED_SCHEDULERS,
                             KREA_ALLOWED_WEIGHT_DTYPES, apply_optimal_sampler_params,
                             family_of_lora, get_krea_loras,
                             get_krea_models, get_sdxl_loras,
                             get_zimage_models, inject_krea2t_enhancer,
                             load_workflow_local, resolve_checkpoint_ckpt_name)
from ..utils.zimage_helper import apply_zimage_settings

logger = logging.getLogger(__name__)

# Plafond dur d'images par run (~4-6 min de GPU max en Z-Image Turbo).
MAX_TEST_IMAGES = 24
_STUDIO_LAUNCH_LOCK = threading.Lock()


def _serialized_studio_launch(fn):
    """Make Studio admission plus row/job creation one in-process critical section."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with _STUDIO_LAUNCH_LOCK:
            return fn(*args, **kwargs)
    return wrapped

# Prompt preset d'identité (le trigger word du dataset est substitué).
IDENTITY_PROMPT_TEMPLATE = "{trigger}, close-up portrait, neutral expression, looking at camera"

# Résolution du workflow ZTurbo (constante implicite du design).
TEST_WIDTH, TEST_HEIGHT = 832, 1216

# Chemins des workflows (copies verbatim de SRC/workflows/image-generation/).
WORKFLOW_ZTURBO_PATH = cfg.BACKEND_DIR / 'workflows' / 'ZImage_bigLove_ZT3_optimal.json'
WORKFLOW_HQ_PATH = cfg.BACKEND_DIR / 'workflows' / 'image_real_HQ.json'
WORKFLOW_KREA_TURBO_PATH = cfg.BACKEND_DIR / 'workflows' / 'krea2_turbo.json'


def _comfy_output_dir():
    d = cfg.comfyui_dir('output')
    return str(d) if d else None


comfy_output_dir = _comfy_output_dir
_STORAGE_RUNTIME = sys.modules[__name__]
_LIFECYCLE_RUNTIME = sys.modules[__name__]


# Formats testables (≈1 MP, multiples de 64 - sûrs pour Z-Image). Le cadrage peut
# influencer le rendu du LoRA (« la balance »), d'où le choix laissé à l'utilisateur.
TEST_ASPECTS = {
    '9:16': (832, 1216),
    '3:4':  (896, 1152),
    '1:1':  (1024, 1024),
    '4:3':  (1152, 896),
    '16:9': (1216, 832),
}
# SDXL : MÊMES formats, mais côté long plafonné à 1024 = la base SDXL qui ne duplique
# pas (les buckets ≈1 MP de Z-Image, côté long 1216, déforment les merges/DMD SDXL type
# bigLove/mopMix). Multiples de 64. Choix utilisateur 2026-06-24 (« SDXL-safe ≤1024 »).
TEST_ASPECTS_SDXL = {
    '9:16': (576, 1024),
    '3:4':  (768, 1024),
    '1:1':  (1024, 1024),
    '4:3':  (1024, 768),
    '16:9': (1024, 576),
}
DEFAULT_ASPECT = '9:16'
# Paliers de résolution (parité Generate) - mêmes clés que resolution.py/_TIERS. NULL =
# table de formats fixe historique (comportement inchangé si le front n'envoie rien).
RESOLUTION_TIERS = ('fast', 'standard', 'hq', 'max')
# Table de correspondance format studio ('9:16'…) → vocabulaire nommé de compute_tier_dims
# ('square','landscape'…). Le studio n'expose que ces 5 ratios.
_ASPECT_TO_TIER_RATIO = {
    '1:1': 'square', '4:3': 'landscape', '3:4': 'portrait',
    '16:9': 'widescreen', '9:16': 'tall',
}


def _aspect_dims(aspect, train_type=None, resolution_tier=None):
    """(width, height) d'un format. Si `resolution_tier` (fast|standard|hq|max) est fourni,
    délègue à `compute_tier_dims` (ratio nommé + mégapixels du palier, comme Generate) ;
    sinon table fixe par famille (SDXL côté long ≤1024, sinon table Z-Image historique).
    Format inconnu → défaut. SDXL + palier : on re-borne le côté long à 1024 (bande
    SDXL-safe, multiples de 64) car compute_tier_dims monte jusqu'à 1536 (safe Z-Image,
    déforme les merges/DMD SDXL)."""
    if resolution_tier in RESOLUTION_TIERS:
        named = _ASPECT_TO_TIER_RATIO.get(aspect)
        if named:
            from ..utils.resolution import compute_tier_dims
            w, h = compute_tier_dims(named, resolution_tier)
            if (train_type or '').lower() == 'sdxl':
                longest = max(w, h)
                if longest > 1024:
                    sc = 1024.0 / longest
                    w = max(64, int(round(w * sc / 64)) * 64)
                    h = max(64, int(round(h * sc / 64)) * 64)
            return w, h
    table = TEST_ASPECTS_SDXL if (train_type or '').lower() == 'sdxl' else TEST_ASPECTS
    return table.get(aspect, table[DEFAULT_ASPECT])


aspect_dims = _aspect_dims

# Axes optionnels CFG / steps (Z-Image Turbo : défaut cfg=1.0, 8 steps). Tester
# plusieurs valeurs aide à trouver le réglage qui tient le mieux l'identité.
DEFAULT_CFG = 1.0
DEFAULT_STEPS = 8
CFG_CHOICES = [1.0, 1.5, 2.0, 2.5, 3.0]
STEPS_CHOICES = [6, 8, 10, 12, 16, 20, 24, 32, 40]


# Basename tolerant to ComfyUI's backslash-relative LoRA paths, and the Wilson
# ranking metric: both OWNED by the sibling that uses them, aliased here because
# this module is the runtime surface the payload/tests reach through.
_basename = _discovery.basename
_wilson_lower_bound = _scoring._wilson_lower_bound


def identity_prompt(ds) -> str:
    return IDENTITY_PROMPT_TEMPLATE.format(trigger=(ds.trigger_word or '').strip())


def _prompt_with_trigger(prompt, trigger_word):
    """Préfixe le trigger word du dataset au prompt (même ordre que
    IDENTITY_PROMPT_TEMPLATE), SAUF si prompt/trigger vide ou si le trigger est déjà
    présent comme TOKEN entier (insensible à la casse) → dédup, pas de doublon.

    Utilisé UNIQUEMENT au montage du workflow (`_build_cell_workflow`) : le prompt
    stocké sur la cellule reste BRUT (menu « prompts récents » propre)."""
    p = (prompt or '').strip()
    t = (trigger_word or '').strip()
    if not p or not t:
        return p
    # Python's ``\w``/``\W`` boundaries are Unicode-aware, unlike the former
    # ASCII-only character class which treated adjacent CJK/Cyrillic letters as
    # separators and mistook embedded trigger prefixes for complete tokens.
    if re.search(r'(?<!\w)' + re.escape(t) + r'(?!\w)', p, re.IGNORECASE):
        return p
    return f'{t}, {p}'


# --- Discovery ---------------------------------------------------------------

FAMILIES = _discovery.FAMILIES
list_test_checkpoints = _discovery.list_test_checkpoints
available_families = _discovery.available_families
permanent_lora_candidates = _discovery.permanent_lora_candidates
_resolve_family = _discovery.resolve_family
list_sdxl_base_models = _discovery.list_sdxl_base_models
list_all_testable_checkpoints = _discovery.list_all_testable_checkpoints
basename = _basename
resolve_family = _resolve_family


# --- Guards ------------------------------------------------------------------
def gpu_busy_reason() -> str | None:
    """Return a human error when the GPU is held by a long-running exclusive
    task (LoRA training / vision pass), else None. The queue itself serializes
    normal generations, so no further locking is needed."""
    if queue_manager._get_system_state('training_in_progress', False):
        return "LoRA training in progress - the studio is unavailable (GPU busy)."
    if queue_manager._get_system_state('vision_in_progress', False):
        return "Vision pass in progress (GPU busy) - try again in a moment."
    return None


def _active_run_count(dataset_id=None) -> int:
    """In-flight cells (pending, no file yet). dataset_id=None → garde GLOBALE
    (tous datasets confondus, ce qu'exige une comparaison multi-LoRA) ; fourni →
    une seule run active par dataset (comportement historique)."""
    q = (LoraTestImage.query
         .filter_by(status='pending')
         .filter(LoraTestImage.filename.is_(None)))
    if dataset_id is not None:
        q = q.filter_by(dataset_id=dataset_id)
    return q.count()


def build_matrix(checkpoints, strengths, aspects=None, cfgs=None, steps_list=None, steps2_list=None) -> list[tuple]:
    """Materialize the (checkpoint, strength, aspect) grid cells, validated:
    non-empty checkpoint/strength axes, strengths in [0.0, 2.0] (0 = base model /
    LoRA off, a valid control column) (deduped, order
    kept), aspects within the whitelist (deduped, défaut 9:16). The materialized
    base matrix is bounded before allocation; later axes are checked again by
    the run creator."""
    cps = [c for c in (checkpoints or []) if isinstance(c, str) and c.strip()]
    sts = []
    for s in (strengths or []):
        try:
            v = round(float(s), 2)
        except (TypeError, ValueError):
            raise ValueError(f'invalid strength: {s!r}')
        if not 0.0 <= v <= 2.0:
            raise ValueError(f'strength out of range [0.0, 2.0]: {v}')
        if v not in sts:
            sts.append(v)
    asp = []
    for a in (aspects or []):
        if a in TEST_ASPECTS and a not in asp:
            asp.append(a)
    if not asp:
        asp = [DEFAULT_ASPECT]
    cfs = []
    for v in (cfgs or []):
        try:
            fv = round(float(v), 2)
        except (TypeError, ValueError):
            continue
        if 1.0 <= fv <= 15.0 and fv not in cfs:
            cfs.append(fv)
    if not cfs:
        cfs = [DEFAULT_CFG]
    sps = []
    for v in (steps_list or []):
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= iv <= 50 and iv not in sps:
            sps.append(iv)
    if not sps:
        sps = [DEFAULT_STEPS]
    # Axe steps2 (SDXL : 2e passe / detail daemon, node 57). Optionnel : sans valeurs
    # → [None] (la 2e passe retombe sur les steps de la 1re ; Z-Image n'a pas de 2e passe).
    sps2 = []
    for v in (steps2_list or []):
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= iv <= 50 and iv not in sps2:
            sps2.append(iv)
    if not sps2:
        sps2 = [None]
    if not cps or not sts:
        raise ValueError('at least one checkpoint and one strength are required')
    base_count = len(cps) * len(sts) * len(asp) * len(cfs) * len(sps) * len(sps2)
    if base_count > MAX_TEST_IMAGES:
        raise ValueError(
            f'test grid has {base_count} cells; maximum is {MAX_TEST_IMAGES}. '
            'Reduce checkpoints or sweep axes.')
    return [(c, s, a, cf, sp, sp2)
            for c in cps for s in sts for a in asp for cf in cfs for sp in sps for sp2 in sps2]


def _check_final_cell_budget(total: int) -> None:
    if total > MAX_TEST_IMAGES:
        raise ValueError(
            f'test run would create {total} images; maximum is {MAX_TEST_IMAGES}. '
            'Reduce axes, base models, batch LoRAs, or images per config.')


# Domaine des seeds ComfyUI : [1, 2^31-1]. Partagé par la validation d'entrée, la
# dérivation des seeds d'un run et le repli du resume - ils DOIVENT s'accorder,
# sinon un seed accepté à la création devient hors domaine au resume.
SEED_MAX = 2**31 - 1


def _validated_seed(seed) -> int:
    try:
        value = int(seed) if seed is not None else random.randint(1, SEED_MAX)
    except (TypeError, ValueError):
        raise ValueError(f'invalid seed: {seed!r}')
    if not 1 <= value <= SEED_MAX:
        raise ValueError(f'seed out of range [1, {SEED_MAX}]: {value}')
    return value


def _run_seed_series(seed, count) -> tuple[int, list[int]]:
    """(count borné, seeds) d'un run. N seeds DISTINCTS, PARTAGÉS par toutes les
    configs du run : c'est ce qui rend la comparaison équitable (deux configs jugées
    sur le même bruit). Borné 1..4 images par config."""
    try:
        count = max(1, min(int(count or 1), 4))
    except (TypeError, ValueError):
        count = 1
    return count, [1 + ((seed + i - 1) % SEED_MAX) for i in range(count)]


def _base_model_pool(family, *, require=False) -> list:
    """Pool de modèles de BASE d'une famille - la seule définition de cette règle.

    SDXL → les checkpoints SDXL de Generate ; Krea → ``None`` EN TÊTE (= le UNET
    câblé dans le node 20 du workflow, défaut historique et repli) puis les bases
    Krea locales ; sinon les modèles Z-Image. Ce ``None`` de tête est le contrat :
    une cellule Krea legacy (``z_model`` NULL) doit retomber sur le UNET câblé, jamais
    sur un modèle arbitraire - un resume qui le perdrait re-générerait silencieusement
    sur une autre base.

    La POLITIQUE de pool vide reste chez l'appelant : la création refuse
    (``require=True``), le resume se rabat et ne lève jamais en cours de run."""
    if family == 'sdxl':
        models = [m['filename'] for m in list_sdxl_base_models()]
    elif family == 'krea':
        models = [None] + get_krea_models()
    else:
        models = get_zimage_models()
    if require and not models:
        raise ValueError('no SDXL checkpoint available' if family == 'sdxl'
                         else 'no Z-Image model available')
    return models


def _validated_permanent_loras(permanent_loras, run_family) -> list[dict]:
    """LoRA « always-on » (style/utilitaire) appliqués à CHAQUE cellule (hors batch),
    validés contre les candidats de la famille (anti path-injection) + strength clampé.
    Une entrée hors whitelist est ignorée, pas une erreur."""
    allowed = {c['filename'] for c in permanent_lora_candidates(run_family)}
    out = []
    for e in (permanent_loras or []):
        fn = str((e or {}).get('filename') or '')
        if fn not in allowed:
            continue
        out.append({'filename': fn, 'strength': _extra_lora_strength(e, run_family)})
    return out


def _krea_rebalance_value(run_family, rebalance, rebalance_strength):
    """NSFW / texture rebalance (node 30) - Krea UNIQUEMENT (les autres familles n'ont
    pas ce node). Encodage en UN seul FLOAT, PERSISTÉ sur la ligne et rejoué tel quel
    par le resume - les deux chemins de création doivent donc l'encoder pareil :
        rebalance=False   → 1.0 (OFF, passthrough SFW)
        rebalance=True    → rebalance_strength clampé 1..8 (ON, défaut 4.0)
        None / non-Krea   → None (défaut ON du workflow, node intact)"""
    if run_family != 'krea' or rebalance is None:
        return None
    if not rebalance:
        return 1.0
    try:
        return max(1.0, min(8.0, float(
            rebalance_strength if rebalance_strength is not None else 4.0)))
    except (TypeError, ValueError):
        return 4.0


def _extra_lora_strength(entry, run_family) -> float:
    """Validate utility LoRA strength using the same ranges as the shared UI."""
    filename = str((entry or {}).get('filename') or '')
    maximum = 2.0
    if (run_family or '').lower() == 'krea':
        maximum = 20.0 if 'filterbypass' in filename.lower() else 6.0
    try:
        value = round(float((entry or {}).get('strength', 1.0)), 2)
    except (TypeError, ValueError):
        raise ValueError(f'invalid strength for {filename}: {(entry or {}).get("strength")!r}')
    if not 0.0 <= value <= maximum:
        raise ValueError(f'strength out of range [0.0, {maximum}]: {value}')
    return value


# --- Workflow build + enqueue -------------------------------------------------
def apply_sdxl_lora_test_settings(workflow, *, base_ckpt, lora_name, strength,
                                  prompt, seed, width, height, cfg=None, steps=None,
                                  steps2=None, batch_size=1, filename_prefix=None,
                                  allowed_bases=None, allowed_loras=None,
                                  detail_amount=None):
    """Configure une cellule de test sur le workflow HQ (SDXL) : checkpoint de base
    (node 1) + LoRA testé via le LoraLoader subtle (node 25) + prompt/seed/dims/steps.
    Le workflow HQ a DEUX passes : `steps` = passe 1 (KSampler node 5) ; `steps2` =
    passe 2 (detail daemon, BasicScheduler node 57). `steps2=None` → la passe 2 retombe
    sur `steps`. Node IDs = ceux d'app/main/routes.py. Mutate en place. Lève ValueError
    si le checkpoint/LoRA n'est pas dans sa whitelist (anti path-injection)."""
    if allowed_bases is not None and base_ckpt not in allowed_bases:
        raise ValueError(f"unknown SDXL checkpoint: {base_ckpt}")
    if allowed_loras is not None and lora_name not in allowed_loras:
        raise ValueError(f"unknown SDXL LoRA: {lora_name}")

    def _set(node_id, key, value):
        n = workflow.get(node_id)
        if isinstance(n, dict) and key in n.get("inputs", {}):
            n["inputs"][key] = value

    # base_ckpt est un BASENAME (get_checkpoint_models dépouille le dossier) ; le loader
    # ComfyUI veut le chemin relatif (ex. 'Biglove\\…') → résoudre, sinon 400.
    _set("1", "ckpt_name", resolve_checkpoint_ckpt_name(base_ckpt))
    _set("25", "lora_name", lora_name)
    _set("25", "strength_model", float(strength))
    _set("25", "strength_clip", float(strength))
    _set("3", "text", prompt)
    _set("5", "seed", int(seed))
    if steps is not None:
        _set("5", "steps", int(steps))          # passe 1 (KSampler)
    # passe 2 (detail daemon, node 57) : steps2 si fourni, sinon retombe sur steps.
    _pass2 = steps2 if steps2 is not None else steps
    if _pass2 is not None:
        _set("57", "steps", int(_pass2))
    if cfg is not None:
        _set("5", "cfg", float(cfg))
    _set("6", "width", int(width))
    _set("6", "height", int(height))
    _set("6", "batch_size", int(batch_size))
    # DetailDaemon (classe DetailDaemonSamplerNode, node scanné par type comme la route
    # generate) : la valeur du slider EST le détail effectif (fade=0). Clamp défensif
    # [0,1] ; None → défaut du workflow conservé. Bande SDXL-safe ≈ 0-0.25.
    if detail_amount is not None:
        try:
            _da = max(0.0, min(1.0, float(detail_amount)))
        except (TypeError, ValueError):
            _da = None
        if _da is not None:
            for _n in workflow.values():
                if (isinstance(_n, dict) and _n.get("class_type") == "DetailDaemonSamplerNode"
                        and "detail_amount" in _n.get("inputs", {})):
                    _n["inputs"]["detail_amount"] = _da
    if filename_prefix is not None:
        _set("9", "filename_prefix", filename_prefix)


# Basename du UNET câblé dans krea2_turbo.json (node 20) : l'entrée « Official »
# des sélecteurs le représente déjà (valeur vide → on ne touche pas au node), donc
# les listes de bases ALTERNATIVES l'excluent pour ne pas montrer le même modèle
# deux fois. La whitelist de validation, elle, garde TOUT get_krea_models().
_KREA_DEFAULT_BASE = 'krea2_turbo_fp8.safetensors'


def krea_alt_base_models() -> list:
    """Bases Krea locales ALTERNATIVES au UNET câblé du workflow : les checkpoints
    trouvés par get_krea_models() moins le défaut. Vide → aucun choix à offrir
    (les sélecteurs restent cachés, comportement historique)."""
    return [m for m in get_krea_models()
            if _basename(m).lower() != _KREA_DEFAULT_BASE]


def apply_krea_lora_test_settings(workflow, *, lora_name, strength, prompt, seed,
                                  width, height, cfg=None, steps=None, batch_size=1,
                                  filename_prefix=None, allowed_loras=None, extra_loras=None,
                                  rebalance=None, sampler=None, scheduler=None,
                                  weight_dtype=None, enhancer_strength=None,
                                  base_model=None, allowed_bases=None):
    """Configure une cellule de test sur le workflow Krea 2 Turbo : le LoRA testé est
    injecté après le UNETLoader (node 20 → KSampler node 26), + prompt/seed/dims/steps/cfg.
    `extra_loras` = LoRA « always-on » (style/utilitaire) chaînés EN PLUS dans le même
    maillon (appliqués tels quels à cette cellule, hors batch). Krea est MONO-passe (pas
    de steps2).

    `rebalance` (node 30, NSFW/texture rebalance) - même sémantique que la génération
    (routes.py) : None = on NE touche PAS le node, défaut ON du workflow ; ≤1.0 = OFF
    (multiplier=1.0 + per_layer_weights neutres → passthrough SFW) ; >1.0 = ON à cette
    force (clampé 1..8). Mutate en place. Lève ValueError si le LoRA testé n'est pas dans
    sa whitelist (anti path-injection).

    `base_model` : UNET Krea local à charger dans le node 20 à la place du défaut
    câblé du workflow — même mécanique de base que SDXL (`base_ckpt`) / Z-Image
    (`z_model`). None = on ne touche pas au node (défaut). Validé contre
    `allowed_bases` (anti path-injection, comme le LoRA)."""
    if allowed_loras is not None and lora_name not in allowed_loras:
        raise ValueError(f"unknown Krea LoRA: {lora_name}")
    if base_model and allowed_bases is not None and base_model not in allowed_bases:
        raise ValueError(f"unknown Krea base model: {base_model}")

    def _set(node_id, key, value):
        n = workflow.get(node_id)
        if isinstance(n, dict) and key in n.get("inputs", {}):
            n["inputs"][key] = value

    if base_model:
        _set("20", "unet_name", base_model)

    _set("23", "text", prompt)                    # prompt (CLIPTextEncode Krea)
    _set("25", "width", int(width))
    _set("25", "height", int(height))
    _set("25", "batch_size", int(batch_size))
    _set("26", "seed", int(seed))
    if steps is not None:
        _set("26", "steps", max(1, min(50, int(steps))))
    if cfg is not None:
        _set("26", "cfg", max(1.0, min(10.0, float(cfg))))
    # Sampler / scheduler (node 26) + précision UNET (node 20) - validés contre les
    # MÊMES whitelists que la génération (anti-injection ; hors liste = ignoré).
    if sampler in KREA_ALLOWED_SAMPLERS:
        _set("26", "sampler_name", sampler)
    if scheduler in KREA_ALLOWED_SCHEDULERS:
        _set("26", "scheduler", scheduler)
    if weight_dtype in KREA_ALLOWED_WEIGHT_DTYPES:
        _set("20", "weight_dtype", weight_dtype)
    if filename_prefix is not None:
        _set("28", "filename_prefix", filename_prefix)
    # Node 30 (Krea2RebalanceConditioning) : reweight des taps de conditioning Qwen3-VL.
    # ON (>1) relève les taps filtrés-sécurité → sortie non censurée + peau moins « plastique » ;
    # OFF (≤1) = passthrough identité (SFW). None = laisser le défaut du workflow (ON 4.0).
    if rebalance is not None and isinstance(workflow.get("30"), dict):
        m = max(1.0, min(8.0, float(rebalance)))
        if m <= 1.0:
            _set("30", "multiplier", 1.0)
            _set("30", "per_layer_weights", "1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0")
        else:
            _set("30", "multiplier", m)
    # LoRA testé + always-on : une seule chaîne node 20 → 26 (même mécanique que la
    # génération Krea). `allowed` contient TOUT le pool Krea (les always-on y sont).
    from ..utils.comfyui import inject_krea_loras
    requested = [{"filename": lora_name, "strength": float(strength)}]
    for e in (extra_loras or []):
        fn = str((e or {}).get("filename") or "")
        if not fn:
            continue
        try:
            st = float(e.get("strength", 1.0))
        except (TypeError, ValueError):
            st = 1.0
        requested.append({"filename": fn, "strength": st})
    allowed = set(allowed_loras) if allowed_loras is not None else {r["filename"] for r in requested}
    inject_krea_loras(workflow, requested, allowed=allowed)
    # Krea2T-Enhancer (patcher texte-adhérence) injecté APRÈS les LoRA (wire-aware :
    # se branche sur ce qui alimente KSampler.model). enhancer_strength None = OFF ;
    # sinon ON à cette force (clampée 0..2 dans inject_krea2t_enhancer).
    if enhancer_strength is not None:
        inject_krea2t_enhancer(workflow, True, enhancer_strength)


def _build_cell_workflow(user_id, checkpoint, strength, prompt, seed, z_model,
                         allowed_loras, width=TEST_WIDTH, height=TEST_HEIGHT,
                         cfg=None, steps=None, steps2=None, dataset_id=None, train_type='zimage',
                         extra_loras=None, rebalance=None, negative=None, sampler=None,
                         scheduler=None, weight_dtype=None, enhancer_strength=None,
                         detail_amount=None, trigger_word=None):
    """Load the ZTurbo (Z-Image) / HQ (SDXL) / Krea workflow and configure one grid cell.
    `extra_loras` = LoRA « always-on » (style/utilitaire) appliqués à CETTE cellule en plus
    du checkpoint testé (hors batch). `rebalance` = node 30 NSFW/texture (Krea uniquement,
    None ailleurs). Raises ValueError if the workflow file is unloadable.

    Le filename_prefix inclut le dataset_id ET un uuid court par cellule : sans
    ça, le compteur ComfyUI (qui repart de 0 à chaque restart) produisait des
    noms identiques entre datasets (`{uid}_LoraTest_00022_`) → collisions de
    cache navigateur et confusion visuelle entre LoRA (ex. images eva6938 vues
    dans le studio d'un autre LoRA). L'uuid garantit l'unicité même au sein d'un
    dataset (re-runs après restart ComfyUI)."""
    # Trigger word auto-injecté ICI (montage seul) - le prompt reste brut en base.
    prompt = _prompt_with_trigger(prompt, trigger_word)
    ds_tag = f"d{dataset_id}_" if dataset_id is not None else ""
    fname = f"{user_id}_{ds_tag}LoraTest_{uuid.uuid4().hex[:8]}"
    extra_loras = extra_loras or []
    if (train_type or 'zimage').lower() == 'sdxl':
        workflow = load_workflow_local(str(WORKFLOW_HQ_PATH))
        if not workflow:
            raise ValueError('HQ workflow not found/unreadable')
        from ..utils.comfyui import get_checkpoint_models, inject_sdxl_loras
        allowed_bases = {m.get('name') for m in get_checkpoint_models() if m.get('name')}
        allowed_sdxl_loras = {lora['filename'] for lora in get_sdxl_loras()}
        # Comme la génération SDXL normale : régler sampler/scheduler/cfg ET surtout
        # toggler le LoRA DMD2 (ON pour checkpoints DMD-distillés type bigLove/mop, OFF
        # pour SDXL full) selon le modèle de base. Sans ça, sortie cassée. Appliqué AVANT
        # l'injection de test pour que la cfg/les steps du studio (axes) gagnent ensuite.
        apply_optimal_sampler_params(workflow, z_model)
        apply_sdxl_lora_test_settings(
            workflow, base_ckpt=z_model, lora_name=checkpoint, strength=strength,
            prompt=prompt, seed=seed, width=width, height=height, cfg=cfg, steps=steps,
            steps2=steps2, batch_size=1, filename_prefix=fname,
            allowed_bases=allowed_bases, allowed_loras=allowed_sdxl_loras,
            detail_amount=detail_amount,
        )
        if extra_loras:  # always-on chaînés après le Style LoRA (node 25)
            inject_sdxl_loras(workflow, extra_loras, {e['filename'] for e in extra_loras})
        return workflow
    if (train_type or 'zimage').lower() == 'krea':
        workflow = load_workflow_local(str(WORKFLOW_KREA_TURBO_PATH))
        if not workflow:
            raise ValueError('Krea workflow not found/unreadable')
        allowed_krea = {lora['filename'] for lora in get_krea_loras()}
        apply_krea_lora_test_settings(
            workflow, lora_name=checkpoint, strength=strength, prompt=prompt,
            seed=seed, width=width, height=height, cfg=cfg, steps=steps,
            batch_size=1, filename_prefix=fname, allowed_loras=allowed_krea,
            extra_loras=extra_loras, rebalance=rebalance,
            sampler=sampler, scheduler=scheduler, weight_dtype=weight_dtype,
            enhancer_strength=enhancer_strength,
            # Base Krea locale optionnelle (z_model, même canal que SDXL/Z-Image) ;
            # None = UNET câblé du workflow. Whitelist = scan disque (anti-injection).
            base_model=z_model, allowed_bases=set(get_krea_models()),
        )
        return workflow
    workflow = load_workflow_local(str(WORKFLOW_ZTURBO_PATH))
    if not workflow:
        raise ValueError('ZTurbo workflow not found/unreadable')
    apply_zimage_settings(
        workflow,
        z_model=z_model,
        z_loras=[{'filename': checkpoint, 'strength': strength}] + list(extra_loras),
        prompt=prompt,
        negative=negative,
        seed=seed,
        width=width, height=height, batch_size=1,
        z_cfg=cfg, z_steps=steps,
        filename_prefix=fname,
        # always-on inclus dans la whitelist (sinon inject_zimage_loras les filtrerait).
        allowed_loras=(set(allowed_loras) | {e['filename'] for e in extra_loras}) if extra_loras else allowed_loras,
    )
    return workflow


def _enqueue_cell(user_id, dataset_id, workflow, prompt, job_id=None) -> str:
    """Enqueue one cell as a normal (serialized) image job. Free: never
    debited - the failure path in job_queue skips the refund for
    is_lora_test jobs exactly like is_dataset (no credit minting)."""
    job_id = job_id or str(uuid.uuid4())
    queue_manager.add_job(job_type='image', user_id=str(user_id),
                          workflow_data=workflow, prompt=prompt, job_id=job_id,
                          metadata={'model_name': 'zimage_lora_test',
                                    'is_lora_test': True,
                                    'dataset_id': dataset_id})
    return job_id


def _sanitize_gen_knobs(run_family, *, negative=None, sampler=None, scheduler=None,
                        weight_dtype=None, enhancer=None, enhancer_strength=None,
                        detail_amount=None, resolution_tier=None, init_image=None,
                        denoise=None) -> dict:
    """Normalise + valide les réglages de génération GLOBAUX d'un run (parité Generate),
    filtrés PAR FAMILLE (un sampler Krea n'a aucun sens en Z-Image). Renvoie un dict prêt
    à la fois à persister sur LoraTestImage ET à passer à `_build_cell_workflow`. Chaque
    valeur hors périmètre/whitelist retombe à None (le workflow garde alors son défaut).

    Encodages : `enhancer_strength` NULL = Krea2T OFF (sinon force ON, clampée 0..2, défaut
    1.0 quand `enhancer` truthy sans force) ; `negative` vide → None ;
    `resolution_tier` doit être dans RESOLUTION_TIERS. Krea img2img is rejected
    until Studio has an executable workflow that can honor those settings."""
    fam = (run_family or 'zimage').lower()
    if fam == 'krea' and (init_image is not None or denoise is not None):
        raise ValueError('Krea img2img settings are not supported by Studio')
    neg = ((negative or '').strip() or None) if fam == 'zimage' else None
    smp = sampler if (fam == 'krea' and sampler in KREA_ALLOWED_SAMPLERS) else None
    sch = scheduler if (fam == 'krea' and scheduler in KREA_ALLOWED_SCHEDULERS) else None
    wdt = weight_dtype if (fam == 'krea' and weight_dtype in KREA_ALLOWED_WEIGHT_DTYPES) else None
    enh = None
    if fam == 'krea' and enhancer:
        try:
            enh = max(0.0, min(2.0, float(enhancer_strength if enhancer_strength is not None else 1.0)))
        except (TypeError, ValueError):
            enh = 1.0
    dta = None
    if fam == 'sdxl' and detail_amount is not None:
        try:
            dta = max(0.0, min(1.0, float(detail_amount)))
        except (TypeError, ValueError):
            dta = None
    tier = resolution_tier if resolution_tier in RESOLUTION_TIERS else None
    return {'negative': neg, 'sampler': smp, 'scheduler': sch, 'weight_dtype': wdt,
            'enhancer_strength': enh, 'detail_amount': dta, 'resolution_tier': tier,
            'init_image': None, 'denoise': None}


# --- Studio preflight (model files on disk + custom nodes in ComfyUI) ---------
# Klein already preflights its assets (KleinModelsMissing → 409 + auto-download);
# Krea/SDXL/Z-Image did NOT — the studio workflows hardcode the developer's own
# VAE / text-encoder / accelerator-LoRA names (none of which exist on
# a fresh install), so a fresh user launched a grid and every tile failed ComfyUI
# validation SILENTLY (empty grid, no reason). This block gives each family the
# same up-front check: verify (a) every model file the BUILT workflow references
# is on disk (via the exact filenames the workflow will send — zero divergence),
# and (b) every custom node the workflow uses exists in the target ComfyUI
# (/object_info), and raises StudioAssetsMissing so the route answers ONE
# actionable 409 instead.

class StudioAssetsMissing(Exception):
    """A Studio family's workflow references model files not on disk, or custom
    nodes the target ComfyUI doesn't expose, so every grid tile would fail ComfyUI
    validation and land as a silently-empty cell. Raised BEFORE any row/job is
    created so the caller can answer one actionable 409 (same spirit as Klein's
    KleinModelsMissing).

    `.family` = pipeline key ('zimage'/'sdxl'/'krea'); `.missing_files` =
    [{path, kind}] with `path` a display path like 'models/vae/…'; `.missing_nodes`
    = [class_type]."""
    def __init__(self, family, missing_files, missing_nodes):
        self.family = family
        self.missing_files = list(missing_files)
        self.missing_nodes = list(missing_nodes)
        n_f, n_n = len(self.missing_files), len(self.missing_nodes)
        super().__init__(f'{family} studio assets missing: {n_f} file(s), {n_n} node(s)')


class StudioArchMismatch(Exception):
    """A selected checkpoint's REAL architecture (read from its safetensors header)
    contradicts the family whose pipeline the Studio would run it under. ComfyUI
    silently drops every incompatible LoRA key, so the entire grid renders as if
    the LoRA were off (strength 0) with no error anywhere — the 2026-07-13
    incident (a Z-Image LoRA mislabelled Krea produced 117 no-op tiles). Raised
    BEFORE any row/job is created so the caller answers one actionable 409 (same
    spirit as StudioAssetsMissing).

    `.family` = the Studio's pipeline key; `.detected` = the checkpoint's real
    family; `.checkpoint` = the LoraLoader-form path that mismatched."""
    def __init__(self, family, detected, checkpoint):
        self.family = family
        self.detected = detected
        self.checkpoint = checkpoint
        super().__init__(f'{checkpoint} is a {detected} LoRA, not {family}')


class StudioPartialLaunch(Exception):
    """A comparison published some cells before a later enqueue failed."""

    def __init__(self, run_id, created, reason):
        self.run_id = run_id
        self.created = created
        self.reason = reason
        super().__init__(reason)


class StudioPartialPromptDelete(Exception):
    """Global prompt deletion failed after reporting exact completed scope."""

    def __init__(self, deleted, completed_dataset_ids, failed_dataset_id, reason):
        self.deleted = deleted
        self.completed_dataset_ids = completed_dataset_ids
        self.failed_dataset_id = failed_dataset_id
        self.reason = reason
        super().__init__(reason)


def _resolve_lora_abs_path(checkpoint):
    return _discovery.resolve_lora_path(checkpoint)


def _preflight_checkpoint_arch(run_family, checkpoints):
    """Raise StudioArchMismatch if any selected checkpoint's REAL arch (safetensors
    header) contradicts `run_family`. family_of_lora keys off the FOLDER, which is
    exactly the blind spot a mislabelled deploy exploits — so we read the header
    here. Undetectable/foreign headers pass (no false block); only a POSITIVE
    cross-namespace contradiction stops the run."""
    for cp in checkpoints:
        p = _resolve_lora_abs_path(cp)
        if not p:
            continue
        detected = lt.detect_lora_arch(p)
        if lt.lora_arch_conflicts(detected, run_family):
            raise StudioArchMismatch(run_family, detected, cp)


# ComfyUI loader class_type -> (input keys carrying a model FILENAME, the models/
# subfolders that loader lists files from, human kind). A loader lists files
# relative to ONE of these subfolders; the file counts as present if it resolves
# under any (a UNET lives in unet/ OR diffusion_models/ on shared installs). Only
# loaders the studio workflows actually use are mapped.
_STUDIO_MODEL_LOADERS = {
    'UNETLoader': (('unet_name',), ('unet', 'diffusion_models'), 'diffusion model'),
    'CheckpointLoaderSimple': (('ckpt_name',), ('checkpoints',), 'checkpoint'),
    'VAELoader': (('vae_name',), ('vae',), 'VAE'),
    'CLIPLoader': (('clip_name',), ('text_encoders', 'clip'), 'text encoder'),
    'DualCLIPLoader': (('clip_name1', 'clip_name2'), ('text_encoders', 'clip'), 'text encoder'),
    'LoraLoader': (('lora_name',), ('loras',), 'LoRA'),
    'LoraLoaderModelOnly': (('lora_name',), ('loras',), 'LoRA'),
}


def _models_root():
    try:
        d = cfg.comfyui_dir('models')
    except Exception:
        return None
    return str(d) if d else None


def _ci_join_exists(root, rel):
    """os.path.exists(root/rel) with each component matched case-INSENSITIVELY
    below `root`. ComfyUI on Windows is case-insensitive and the workflow templates
    carry mixed folder casing (node refs 'Z image\\…' / 'Krea\\…' vs the on-disk
    'z image' / 'krea') — a case-sensitive filesystem (cloud) must NOT read those
    as missing. `root` is assumed to exist."""
    cur = root
    for part in rel.split(os.sep):
        if not part or part == '.':
            continue
        nxt = os.path.join(cur, part)
        if os.path.exists(nxt):
            cur = nxt
            continue
        try:
            match = next((e for e in os.listdir(cur) if e.lower() == part.lower()), None)
        except OSError:
            return False
        if match is None:
            return False
        cur = os.path.join(cur, match)
    return os.path.exists(cur)


def _model_file_present(models_root, subfolders, ref):
    """True if `ref` (a loader value, possibly with its own subfolder prefix)
    resolves to a real file under models_root/<subfolder>/ for any candidate
    subfolder."""
    rel_ref = (ref or '').replace('\\', os.sep).replace('/', os.sep).lstrip(os.sep)
    if not rel_ref:
        return True  # empty ref = loader left at a wired default upstream — not our miss
    return any(_ci_join_exists(models_root, os.path.join(sub, rel_ref)) for sub in subfolders)


def _scan_workflow_assets(workflow, models_root):
    """(missing_files, class_types) for a BUILT cell workflow. missing_files =
    [{path, kind}] for every model-loader reference NOT on disk (skipped entirely
    when models_root is unknown — the base-pool guards already caught that case);
    class_types = every node class in the graph (for the /object_info node check)."""
    missing, classes = [], set()
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        ct = node.get('class_type')
        if not ct:
            continue
        classes.add(ct)
        spec = _STUDIO_MODEL_LOADERS.get(ct)
        if not (spec and models_root):
            continue
        keys, subfolders, kind = spec
        inputs = node.get('inputs', {}) if isinstance(node.get('inputs'), dict) else {}
        for k in keys:
            ref = inputs.get(k)
            if not isinstance(ref, str) or not ref.strip():
                continue
            if _model_file_present(models_root, subfolders, ref):
                continue
            entry = {'path': f'models/{subfolders[0]}/{ref}'.replace('\\', '/'), 'kind': kind}
            if entry not in missing:
                missing.append(entry)
    return missing, classes


def preflight_family(family, workflows):
    """Raise StudioAssetsMissing if the target ComfyUI is missing any model file or
    custom node the family's BUILT workflow(s) need. `workflows` = representative
    built cell workflow(s) (one per base) — checking the ACTUAL built graph means
    zero divergence from what will be enqueued. Best-effort: only raises on a
    CONCRETE absence; a build that couldn't be produced or an unreachable
    /object_info fails OPEN (the per-tile error capture still surfaces the reason).
    """
    models_root = _models_root()
    missing_files, all_classes = [], set()
    for wf in workflows:
        if not wf:
            continue
        mf, classes = _scan_workflow_assets(wf, models_root)
        for e in mf:
            if e not in missing_files:
                missing_files.append(e)
        all_classes |= classes
    # Custom nodes: compare the graph's class_types to /object_info. Fail-OPEN when
    # it can't be fetched (None) — never block on a transient probe failure.
    missing_nodes = []
    from ..utils.comfyui import fetch_object_info_classes
    available = fetch_object_info_classes()
    if available is not None and all_classes:
        missing_nodes = sorted(c for c in all_classes if c not in available)
    if missing_files or missing_nodes:
        raise StudioAssetsMissing(family, missing_files, missing_nodes)


def _preflight_run(user_id, run_family, checkpoint, bases, allowed, prompt, seed,
                   dataset_id, trigger_word, **workflow_kwargs):
    """Build a representative cell workflow for `run_family` (one per distinct base
    in `bases`) and run `preflight_family` on it. Raises StudioAssetsMissing when
    the target ComfyUI can't run the grid. A representative build that itself fails
    is skipped (the enqueue loop would surface that path's own error)."""
    wfs = []
    seen = set()
    for base in (bases or [None]):
        key = base or ''
        if key in seen:
            continue
        seen.add(key)
        try:
            wfs.append(_build_cell_workflow(
                user_id, checkpoint, 1.0, prompt or '', seed or 1, base, allowed,
                dataset_id=dataset_id, train_type=run_family, trigger_word=trigger_word,
                **workflow_kwargs))
        except Exception as e:  # noqa: BLE001 — a bad representative build ≠ a missing asset
            logger.warning('studio preflight: representative build failed (base=%r): %s', base, e)
    preflight_family(run_family, wfs)


# --- Run lifecycle -----------------------------------------------------------
def _batch_lora_axis(batch_loras, run_family) -> list:
    """Valide la liste « ⚖ batch axis » (mêmes règles anti path-injection que les
    always-on) et renvoie l'axe de test [None, {filename,strength}, …] - None =
    la cellule de RÉFÉRENCE sans le LoRA. Dédupé, borné à 4 LoRA (coût GPU)."""
    perm_allowed = {c['filename'] for c in permanent_lora_candidates(run_family)}
    entries = []
    for e in (batch_loras or []):
        fn = str((e or {}).get('filename') or '')
        if fn not in perm_allowed or any(x['filename'] == fn for x in entries):
            continue
        st = _extra_lora_strength(e, run_family)
        entries.append({'filename': fn, 'strength': st})
    return [None] + entries[:4] if entries else [None]


def _batch_lora_label(row):
    """Nom lisible du LoRA « batch » d'une cellule (entrée batch:true de son JSON
    extra_loras), ou None - badge de la grille/lightbox."""
    try:
        for e in json.loads(row.extra_loras or '[]'):
            if isinstance(e, dict) and e.get('batch'):
                return _basename(e.get('filename', '')).rsplit('.', 1)[0]
    except (ValueError, TypeError):
        pass
    return None


def _build_effective_cell_workflow(user_id, cell, allowed):
    return _build_cell_workflow(
        user_id, cell.checkpoint, cell.strength, cell.prompt, cell.seed,
        cell.z_model, allowed, **cell.workflow_kwargs())


def _launch_effective_cell(user_id, cell, allowed, *, row=None):
    """Persist/build/enqueue one effective cell for create, compare, and resume."""
    image = row or LoraTestImage(**cell.row_kwargs())
    job_id = str(uuid.uuid4())
    image.status = 'pending'
    image.filename = None
    image.job_id = job_id
    image.seed = cell.seed
    image.error = None
    if row is None:
        db.session.add(image)
    db.session.commit()
    try:
        workflow = _build_effective_cell_workflow(user_id, cell, allowed)
        _preflight_checkpoint_arch(cell.family, [cell.checkpoint])
        preflight_family(cell.family, [workflow])
        _enqueue_cell(
            user_id, cell.dataset_id, workflow, cell.prompt, job_id=job_id)
    except Exception as exc:
        image.status = 'failed'
        image.error = str(exc)[:400] or 'enqueue failed'
        db.session.commit()
        raise
    return image


launch_effective_cell = _launch_effective_cell


@_serialized_studio_launch
def create_run(user_id, dataset_id, checkpoints, strengths, seed=None, prompt=None, z_model=None, z_models=None, aspects=None, cfgs=None, steps_list=None, steps2_list=None, count=1, family=None, permanent_loras=None, batch_loras=None, rebalance=None, rebalance_strength=None, negative=None, sampler=None, scheduler=None, weight_dtype=None, enhancer=None, enhancer_strength=None, detail_amount=None, resolution_tier=None, init_image=None, denoise=None) -> dict:
    """Validate + materialize the grid and enqueue every cell.

    Each row is committed BEFORE its enqueue (anti-orphan rule of the dataset
    fan-out); an enqueue failure marks that row 'failed' and re-raises -
    already-enqueued cells keep their jobs. Returns {'created', 'seed', 'count', 'ids'}."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if not (ds.trigger_word or '').strip():
        raise ValueError('trigger word is required')

    reason = gpu_busy_reason()
    if reason:
        raise GpuBusyError(reason)
    if _active_run_count(dataset_id):
        raise ValueError('a test run is already in progress on this dataset - '
                         'wait for it to finish or cancel')

    # La FAMILLE (pipeline) du run est dérivée des checkpoints sélectionnés : ils
    # vivent tous dans le même dossier loras/<famille> (le frontend ne propose qu'une
    # famille à la fois via le sélecteur). On ne peut pas mélanger ZIT/SDXL/Krea dans
    # un run (bases + workflow différents). `family` sert de repli si les checkpoints
    # n'ont pas de préfixe de dossier (anciens noms renommés).
    cps_in = [c for c in (checkpoints or []) if isinstance(c, str) and c.strip()]
    if not cps_in:
        raise ValueError('at least one checkpoint is required')
    fams = {family_of_lora(c) for c in cps_in}
    fams.discard(None)
    if len(fams) > 1:
        raise ValueError('a test run cannot mix multiple families (ZIT/SDXL/Krea)')
    run_family = (next(iter(fams), None) or family or getattr(ds, 'train_type', None) or 'zimage').lower()

    allowed = {c['filename'] for c in list_test_checkpoints(ds, run_family)}
    unknown = [c for c in cps_in if c not in allowed]
    if unknown:
        raise ValueError(f'unknown checkpoint(s) for this dataset: {unknown}')

    extra_loras = _validated_permanent_loras(permanent_loras, run_family)
    # Axe « ⚖ batch » : chaque config tourne une fois SANS puis une fois AVEC
    # chaque LoRA coché batch (les always-on ci-dessus s'appliquent partout).
    batch_axis = _batch_lora_axis(batch_loras, run_family)

    cell_rebalance = _krea_rebalance_value(run_family, rebalance, rebalance_strength)

    # Réglages de génération GLOBAUX du run (parité Generate), validés + gatés par famille.
    knobs = _sanitize_gen_knobs(
        run_family, negative=negative, sampler=sampler, scheduler=scheduler,
        weight_dtype=weight_dtype, enhancer=enhancer, enhancer_strength=enhancer_strength,
        detail_amount=detail_amount, resolution_tier=resolution_tier,
        init_image=init_image, denoise=denoise)

    if run_family != 'sdxl':
        steps2_list = None
    cells = build_matrix(checkpoints, strengths, aspects, cfgs, steps_list, steps2_list)

    models = _base_model_pool(run_family, require=True)
    # Modèle(s) de base - AXE de balayage optionnel (validés contre la whitelist).
    # z_models (liste) prioritaire ; sinon z_model unique (rétrocompat) ; sinon le 1er.
    # '' (entrée « Official » du picker Krea) ≡ None = défaut de la famille — mappé
    # AVANT validation pour que « Official + alternative » reste un axe à 2 valeurs.
    _req_models = list(z_models) if z_models else ([z_model] if z_model else [])
    _req_models = [None if m in ('', None) else m for m in _req_models]
    valid_models = [m for m in _req_models if m in models] or [models[0]]

    seed = _validated_seed(seed)
    count, seeds = _run_seed_series(seed, count)
    _check_final_cell_budget(
        len(cells) * len(valid_models) * len(batch_axis) * len(seeds))

    # Prompt custom optionnel ; sinon prompt d'identité par défaut (trigger).
    prompt = (prompt or '').strip() or identity_prompt(ds)

    # Arch guard : la famille est dérivée du DOSSIER (family_of_lora) — un LoRA
    # mal classé (ex. un Z-Image déployé dans loras/krea) passerait ce filtre et
    # tournerait comme un no-op silencieux. On lit l'arch RÉELLE de chaque
    # checkpoint sélectionné dans son en-tête AVANT toute ligne → 409 actionnable.
    _preflight_checkpoint_arch(run_family, cps_in)
    # Preflight : le ComfyUI cible a-t-il RÉELLEMENT chaque modèle + custom node
    # dont le workflow de la famille a besoin ? On construit le graphe représentatif
    # (par base) et on le vérifie AVANT de créer la moindre ligne → un utilisateur
    # frais reçoit un seul 409 actionnable au lieu d'une grille de tuiles muettes.
    # (Krea/SDXL n'avaient AUCUN preflight ; seul Klein en avait un.)
    _preflight_run(user_id, run_family, cells[0][0], valid_models, allowed,
                   prompt, seeds[0], dataset_id, ds.trigger_word,
                   extra_loras=extra_loras, rebalance=cell_rebalance,
                   negative=knobs['negative'], sampler=knobs['sampler'],
                   scheduler=knobs['scheduler'], weight_dtype=knobs['weight_dtype'],
                   enhancer_strength=knobs['enhancer_strength'],
                   detail_amount=knobs['detail_amount'])

    training_record_by_checkpoint = {
        checkpoint: training_record_for_checkpoint(dataset_id, run_family, checkpoint)
        for checkpoint in cps_in
    }
    subjects = [
        LaunchSubject(
            dataset_id=dataset_id,
            trigger_word=ds.trigger_word,
            prompt=prompt,
            checkpoint=checkpoint,
            allowed=frozenset(allowed),
            training_run_record_id=training_record_by_checkpoint.get(checkpoint),
        )
        for checkpoint in cps_in
    ]
    launch_knobs = {**knobs, 'extra_loras': extra_loras}
    ids = launch_matrix(
        subjects,
        LaunchOptions(
            family=run_family, run_seed=seed, models=tuple(valid_models),
            seeds=tuple(seeds), batch_loras=tuple(batch_axis),
            knobs=launch_knobs, rebalance=cell_rebalance),
        cells_for=lambda subject: (
            cell for cell in cells if cell[0] == subject.checkpoint),
        dimensions=_aspect_dims,
        launch=lambda cell, cell_allowed: _launch_effective_cell(
            user_id, cell, cell_allowed),
    )
    logger.info(f"lora-test: run dataset {dataset_id} -> {len(ids)} cellule(s) "
                f"({len(valid_models)} modèle(s)), base seed {seed} ×{count}")
    return {'created': len(ids), 'seed': seed, 'count': count, 'ids': ids}


@_serialized_studio_launch
def create_comparison_run(user_id, selections, strengths, seed=None, prompt=None,
                          z_model=None, aspects=None, cfgs=None, steps_list=None, steps2_list=None,
                          count=1, permanent_loras=None, batch_loras=None, rebalance=None, rebalance_strength=None,
                          negative=None, sampler=None, scheduler=None, weight_dtype=None,
                          enhancer=None, enhancer_strength=None, detail_amount=None,
                          resolution_tier=None, init_image=None, denoise=None) -> dict:
    """Lance UN run de comparaison sur plusieurs LoRA. `selections` =
    [{dataset_id, checkpoint}]. Toutes les cellules partagent un run_id + le seed
    (équité). Le prompt : `prompt` commun si fourni, sinon l'identity_prompt du
    dataset de CHAQUE cellule (chaque LoRA a son trigger). 1 selection => run mono-LoRA.

    Parité Generate (2026-07-01) : always-on LoRA, rebalance Krea, steps2 SDXL et les
    réglages globaux (négatif/sampler/scheduler/precision/enhancer/detail/tier) sont
    partagés par TOUTES les cellules du run (gatés + validés par famille via _sanitize_gen_knobs)."""
    if not selections:
        raise DomainValidationError('no LoRA selected')
    if not isinstance(selections, list) or any(
            not isinstance(selection, dict) for selection in selections):
        raise ValueError('selections must be an array of objects')
    if prompt is not None and not isinstance(prompt, str):
        raise ValueError('prompt must be a string')
    reason = gpu_busy_reason()
    if reason:
        raise GpuBusyError(reason)
    if _active_run_count():
        raise ValueError('a test run is already in progress - wait for it to finish or cancel')
    # La FAMILLE du run est dérivée du DOSSIER des checkpoints (family_of_lora), PAS du
    # scalaire `ds.train_type` (un dataset est multi-famille). Un run = une seule famille
    # (bases + workflow différents). On résout la base AVANT la boucle, selon la famille.
    fams = {family_of_lora(str(sel.get('checkpoint') or '')) for sel in (selections or [])}
    fams.discard(None)
    if len(fams) > 1:
        raise ValueError('a test run cannot mix multiple families (ZIT/SDXL/Krea)')
    run_type = (next(iter(fams), None) or 'zimage').lower()
    models = _base_model_pool(run_type, require=True)
    z_model = z_model if (z_model and z_model in models) else models[0]
    seed = _validated_seed(seed)
    count, seeds = _run_seed_series(seed, count)
    common_prompt = (prompt or '').strip() or None
    extra_loras = _validated_permanent_loras(permanent_loras, run_type)
    # Axe « ⚖ batch » : chaque config tourne une fois SANS puis une fois AVEC
    # chaque LoRA coché batch (même mécanique que create_run).
    batch_axis = _batch_lora_axis(batch_loras, run_type)
    cell_rebalance = _krea_rebalance_value(run_type, rebalance, rebalance_strength)
    # Réglages de génération GLOBAUX (parité Generate), validés + gatés par famille.
    knobs = _sanitize_gen_knobs(
        run_type, negative=negative, sampler=sampler, scheduler=scheduler,
        weight_dtype=weight_dtype, enhancer=enhancer, enhancer_strength=enhancer_strength,
        detail_amount=detail_amount, resolution_tier=resolution_tier,
        init_image=init_image, denoise=denoise)

    # Validate every selection before reading checkpoint headers or creating the
    # first durable cell. A bad later selection must not leave an earlier LoRA's
    # jobs running as a surprise partial comparison.
    validated = []
    for selection in selections:
        selected_ds = fds.get_dataset(user_id, selection.get('dataset_id'))
        if not selected_ds:
            raise ValueError(f"dataset {selection.get('dataset_id')} not found")
        selected_allowed = {
            candidate['filename']
            for candidate in list_test_checkpoints(selected_ds, run_type)
        }
        selected_checkpoint = selection.get('checkpoint')
        if selected_checkpoint not in selected_allowed:
            raise ValueError(
                f'unknown checkpoint for {selected_ds.name}: {selected_checkpoint}')
        validated.append((selected_ds, selected_checkpoint, selected_allowed))

    if run_type != 'sdxl':
        steps2_list = None
    comparison_cells = build_matrix(
        ['comparison-placeholder'], strengths, aspects, cfgs, steps_list, steps2_list)
    _check_final_cell_budget(
        len(validated) * len(comparison_cells) * len(batch_axis) * len(seeds))

    # Arch guard (même contrat que create_run) : l'arch RÉELLE de chaque
    # checkpoint sélectionné, lue dans son en-tête, doit correspondre à la famille
    # du run — sinon ComfyUI le droppe en silence (grille no-op). Vérifié AVANT
    # toute ligne → 409 actionnable.
    _preflight_checkpoint_arch(
        run_type, [checkpoint for _ds, checkpoint, _allowed in validated])
    # Preflight (même contrat que create_run) : le ComfyUI cible peut-il vraiment
    # exécuter le workflow de cette famille ? On vérifie sur la 1re sélection valable
    # (le run est mono-famille) AVANT de créer les lignes → un seul 409 actionnable.
    _pf_ds, _pf_cp, _pf_allowed = validated[0]
    _preflight_run(user_id, run_type, _pf_cp, [z_model], _pf_allowed,
                   common_prompt or identity_prompt(_pf_ds), seeds[0],
                   _pf_ds.id, getattr(_pf_ds, 'trigger_word', None),
                   extra_loras=extra_loras, rebalance=cell_rebalance,
                   negative=knobs['negative'], sampler=knobs['sampler'],
                   scheduler=knobs['scheduler'], weight_dtype=knobs['weight_dtype'],
                   enhancer_strength=knobs['enhancer_strength'],
                   detail_amount=knobs['detail_amount'])

    run_id = uuid.uuid4().hex
    subjects = [
        LaunchSubject(
            dataset_id=dataset.id,
            trigger_word=dataset.trigger_word,
            prompt=common_prompt or identity_prompt(dataset),
            checkpoint=checkpoint,
            allowed=frozenset(allowed),
            training_run_record_id=training_record_for_checkpoint(
                dataset.id, run_type, checkpoint),
        )
        for dataset, checkpoint, allowed in validated
    ]
    launch_knobs = {**knobs, 'extra_loras': extra_loras}
    ids = launch_matrix(
        subjects,
        LaunchOptions(
            family=run_type, run_seed=seed, models=(z_model,),
            seeds=tuple(seeds), batch_loras=tuple(batch_axis),
            knobs=launch_knobs, rebalance=cell_rebalance, run_id=run_id),
        cells_for=lambda subject: build_matrix(
            [subject.checkpoint], strengths, aspects, cfgs, steps_list, steps2_list),
        dimensions=_aspect_dims,
        launch=lambda cell, cell_allowed: _launch_effective_cell(
            user_id, cell, cell_allowed),
        on_error=lambda error, completed: StudioPartialLaunch(
            run_id, completed, str(error)[:400] or 'enqueue failed'),
    )
    logger.info(f"lora-test: comparison run {run_id} -> {len(ids)} cellule(s), {len(selections)} LoRA, seed {seed}")
    return {'created': len(ids), 'seed': seed, 'count': count, 'run_id': run_id, 'ids': ids}


def _run_owned(user_id, run_id):
    return _lifecycle.run_owned(user_id, run_id)

def cancel_run(user_id, dataset_id=None, run_id=None):
    return _lifecycle.cancel_run(_LIFECYCLE_RUNTIME, user_id, dataset_id, run_id)

@_serialized_studio_launch
def resume_run(user_id, dataset_id=None, run_id=None, family=None):
    return _lifecycle.resume_run(
        _LIFECYCLE_RUNTIME, user_id, dataset_id, run_id, family)


# --- Completion storage -------------------------------------------------------

def _cleanup_output_file(filename, failed):
    return _storage.cleanup_output_file(_STORAGE_RUNTIME, filename, failed)


def link_completed_test_image(job_id, filename, failed=False, reason=None):
    return _storage.link_completed_test_image(
        _STORAGE_RUNTIME, job_id, filename, failed=failed, reason=reason)


# --- Rating + analytics -------------------------------------------------------

_owned_test_image = _scoring._owned_test_image
rate_image = _scoring.rate_image
training_record_for_checkpoint = _scoring.training_record_for_checkpoint
cell_scores = _scoring.cell_scores
model_comparison = _scoring.model_comparison
checkpoint_model_breakdown = _scoring.checkpoint_model_breakdown
_feedback_for_records = _scoring._feedback_for_records
feedback_for_records = _scoring.feedback_for_records
training_feedback = _scoring.training_feedback
best_cell = _scoring.best_cell
best_preset = _scoring.best_preset
best_per_checkpoint = _scoring.best_per_checkpoint
_best_for_family = _scoring._best_for_family
best_for_family = _best_for_family
set_best_settings = _scoring.set_best_settings
clear_best_settings = _scoring.clear_best_settings
score_faces = _scoring.score_faces
face_ranking = _scoring.face_ranking

# Payload assembly receives this module as an explicit runtime interface.  The
# indirection preserves existing monkeypatch seams without making the payload
# module depend back on its coordinator.
active_run_count = _active_run_count
batch_lora_label = _batch_lora_label
_PAYLOAD_RUNTIME = sys.modules[__name__]

@trash.serialized_transaction
def delete_prompt(user_id, dataset_id, prompt) -> int:
    """Supprime toutes les cellules de test d'un PROMPT donné (+ leurs fichiers) :
    retire ce prompt du menu « prompts récents » et nettoie ses images de test.
    Annule les jobs encore en vol. Les fichiers terminés sont déplacés ensemble
    dans la corbeille récupérable avant la suppression des lignes ; un échec de
    commit restaure les fichiers. Ownership scoped (anti-IDOR). Retourne le
    nombre de cellules supprimées."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    p = (prompt or '').strip()
    if not p:
        return 0
    rows = LoraTestImage.query.filter_by(dataset_id=dataset_id, prompt=p).all()
    if not rows:
        return 0
    dataset_dir = Path(fds._dataset_dir(dataset_id)).resolve()
    paths = []
    seen_paths = set()
    for row in rows:
        if not row.filename:
            continue
        candidate = (dataset_dir / row.filename).resolve(strict=False)
        if (candidate.is_relative_to(dataset_dir) and candidate.is_file()
                and not candidate.is_symlink() and candidate not in seen_paths):
            seen_paths.add(candidate)
            paths.append(candidate)
    trashed = (trash.send_paths_to_trash(
        paths, context=f'dataset-{dataset_id}-studio-prompt', metadata={
            'kind': 'studio_prompt',
            'dataset_id': dataset_id,
            'prompt': p[:500],
            'label': f'Studio prompt: {p[:80]}',
        }) if paths else None)
    n = 0
    try:
        for r in rows:
            # Cellule encore en file → annuler le job avant de la supprimer.
            if r.status == 'pending' and r.job_id and not r.filename:
                try:
                    queue_manager.cancel_job(r.job_id, str(user_id), 'image')
                except Exception:
                    pass
            db.session.delete(r)
            n += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        if trashed is not None:
            try:
                trash.restore_entry(trashed['id'])
            except Exception:
                logger.exception('could not roll back Studio prompt trash %s', trashed['id'])
        raise
    logger.info(f"lora-test: prompt supprimé sur dataset {dataset_id} -> {n} cellule(s)")
    return n


# --- Payload (poll) ------------------------------------------------------------

def studio_payload(user_id, dataset_id, family=None, run_id=None):
    return _payload.studio_payload(_PAYLOAD_RUNTIME, user_id, dataset_id, family, run_id)

def studio_run_history(user_id, dataset_id, family=None, cursor=None, limit=20):
    return _payload.studio_run_history(_PAYLOAD_RUNTIME, user_id, dataset_id, family, cursor, limit)

def lora_net_scores(run_id):
    return _payload.lora_net_scores(_PAYLOAD_RUNTIME, run_id)

def studio_payload_run(user_id, run_id):
    return _payload.studio_payload_run(_PAYLOAD_RUNTIME, user_id, run_id)

def _recent_prompts(rows, limit=6) -> list[dict]:
    """Prompts distincts utilisés (récent→ancien) AVEC une vignette : une image 👍
    générée avec ce prompt (à défaut, la plus récente terminée), + le nombre d'images.
    Permet de voir ce que fait chaque prompt dans le menu. `thumb_dataset_id` porte
    le dataset de la vignette (nécessaire quand les rows couvrent PLUSIEURS datasets).
    Retour: [{prompt, thumbnail(filename|None), thumb_dataset_id, thumb_rating, count}]."""
    seen = {}  # prompt -> dict (ordre d'insertion = récent→ancien)
    for r in sorted(rows, key=lambda x: -x.id):  # plus récent d'abord
        p = (r.prompt or '').strip()
        if not p:
            continue
        if p not in seen:
            if len(seen) >= limit:
                continue
            seen[p] = {'prompt': p, 'thumbnail': None, 'thumb_dataset_id': None,
                       'thumb_rating': 0, 'count': 0}
        e = seen[p]
        if r.filename:
            e['count'] += 1
            if r.rating == 1 and e['thumb_rating'] != 1:      # préférer un 👍 (le + récent)
                e['thumbnail'], e['thumb_rating'] = r.filename, 1
                e['thumb_dataset_id'] = r.dataset_id
            elif e['thumbnail'] is None:                       # sinon la 1re terminée vue (= + récente)
                e['thumbnail'], e['thumb_rating'] = r.filename, (r.rating or 0)
                e['thumb_dataset_id'] = r.dataset_id
    return list(seen.values())


def user_recent_prompts(user_id, limit=10) -> list[dict]:
    """Prompts de test récents de l'UTILISATEUR, TOUS datasets confondus (demande
    2026-07-03 : la mémoire des prompts/presets ne doit plus être cloisonnée par
    dataset - un prompt réglé sur Emma doit se recharger sur Adele). Scan borné aux
    1500 dernières cellules (perf) ; chaque entrée porte `thumb_dataset_id` pour que
    le front construise l'URL de vignette du BON dataset."""
    ds_ids = [d.id for d in FaceDataset.query.filter_by(user_id=str(user_id)).all()]
    if not ds_ids:
        return []
    rows = (LoraTestImage.query.filter(LoraTestImage.dataset_id.in_(ds_ids))
            .order_by(LoraTestImage.id.desc()).limit(1500).all())
    return _recent_prompts(rows, limit=limit)


def delete_prompt_everywhere(user_id, prompt) -> int:
    """Supprime un prompt récent (et ses cellules/images de test) sur TOUS les
    datasets de l'utilisateur - pendant « suppression » de la liste globale."""
    p = (prompt or '').strip()
    if not p:
        return 0
    n = 0
    completed = []
    for d in FaceDataset.query.filter_by(user_id=str(user_id)).all():
        try:
            n += delete_prompt(user_id, d.id, p)
        except ValueError:
            continue
        except Exception as exc:
            raise StudioPartialPromptDelete(
                n, completed, d.id, str(exc) or 'prompt deletion failed') from exc
        completed.append(d.id)
    return n
