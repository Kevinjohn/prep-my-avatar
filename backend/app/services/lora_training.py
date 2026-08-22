"""Automatisation de l'entraînement LoRA Z-Image via ai-toolkit.

L'app prépare (export dataset + job-config) et lance l'UI ai-toolkit ; elle ne
réimplémente pas l'entraîneur. Pause GPU via le flag system_state
`training_in_progress` honoré par le superviseur ComfyUI.

Lifted from the parent project's app/services/lora_training.py (1288 lines)
for LoRA Dataset Studio: SRC's module-level AITOOLKIT_DIR/HF_HOME/DATASETS_DIR/
OUTPUT_DIR/LORA_DEST_DIR* constants become live `cfg.aitoolkit_path(...)` /
`cfg.comfyui_dir(...)` accessors below, each raising a clean RuntimeError when
its backend isn't configured yet (so config.json edits apply without a
restart, and routes can map the RuntimeError to a 409). `UI_URL` (ai-toolkit's
web UI, unused - this app drives the CLI) and the whole ownership subsystem
(`record_lora_ownership`, the ownership-filtered checkpoint listing) are
dropped - single local user, cf. plan's Global Constraints.
"""
from __future__ import annotations
import hashlib
import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from PIL import Image

from .. import config as cfg
from ..domain_errors import DomainValidationError
from ..models import FaceDataset, FaceDatasetImage
from ..job_queue import queue_manager
from . import face_dataset_service as fds
from .person_mask import generate_person_masks

logger = logging.getLogger(__name__)

# Résolution + VRAM Krea 2 (modèle 12B). MESURÉ 2026-06-26 : à 1024 SANS unload TE la VRAM
# sature (24,0/24,5 Go) → ~180 s/it (ETA ~7 j, inexploitable) ; à 768 → 3,5 s/it (~50× plus
# rapide → goulot = ACTIVATIONS, pas le streaming des poids). Stratégie qualité : on GARDE 1024
# mais on libère le Qwen3-VL via cache_text_embeddings + unload_text_encoder (~4-8 Go) pour
# tenir sans offload. Si 1024 sature encore → baisser ce SEUL curseur à 896 (mesurer), puis 768
# (cadence prouvée). Curseur de tuning #1, un seul endroit.
KREA_TRAIN_RESOLUTION = 1024

# TTL des flags system_state d'un run (training_in_progress / _pid / _dataset_id /
# _target_step). L'anti-concurrence repose sur le PID VIVANT, mais le GARDE lit
# d'abord le flag `training_in_progress` (cf. is-training checks) : si son TTL
# expire AU MILIEU d'un run, le flag retombe à False, le garde rouvre la porte et
# la file lance un 2e entraînement par-dessus le 1er (collision mémoire → « page
# file too small »). Un run Krea-2-Raw (non distillé, CFG 4 / 25 steps de preview)
# dépasse 4 h → l'ancien TTL 4 h expirait avant la fin ET privait le snapshot du
# checkpoint final de son target_step. 12 h couvre le plus long run réaliste ;
# `process_training_queue` re-arme de toute façon les flags à chaque poll tant que
# le PID vit, donc c'est une ceinture, pas la bretelle.
_TRAIN_STATE_TTL = 12 * 3600
# Serialize the whole read-admit-snapshot-spawn sequence. The process lock keeps
# a second server away from this data directory, but Flask can still serve two
# launch requests on different threads; checking the durable flag without this
# lock lets both requests observe an idle GPU and start competing trainers.
_TRAIN_LAUNCH_LOCK = threading.Lock()
_LOCAL_STAGING_PREFIX = '.lds-local-launch-'
_LOCAL_STAGING_OWNER = 'owner.json'
_TRAINING_GPU_LEASE_TTL = 120


def _atomic_copy(source, destination) -> None:
    """Publish a complete copy without exposing or truncating a partial file."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f'.{destination.name}.', suffix='.tmp', dir=destination.parent)
    os.close(fd)
    try:
        shutil.copy2(source, temporary)
        # Windows rejects fsync on a read-only descriptor with EBADF.
        with open(temporary, 'rb+') as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        try:
            directory = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            # Some supported filesystems/platforms cannot fsync directories;
            # atomic replace still prevents a visible partial checkpoint.
            pass
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


# --- Path accessors (replace SRC's module-level AITOOLKIT_DIR/HF_HOME/... constants) --

def _aitoolkit_dir():
    d = cfg.aitoolkit_path('dir')
    if not d:
        raise RuntimeError('ai-toolkit is not configured')
    return d


def _hf_home():
    d = cfg.aitoolkit_path('hf_home')
    if not d:
        raise RuntimeError('ai-toolkit is not configured')
    return d


def _datasets_dir():
    d = cfg.aitoolkit_path('datasets')
    if not d:
        raise RuntimeError('ai-toolkit is not configured')
    return d


def _output_dir():
    d = cfg.aitoolkit_path('output')
    if not d:
        raise RuntimeError('ai-toolkit is not configured')
    return d


def _venv_python():
    p = cfg.aitoolkit_path('venv_python')
    if not p:
        raise RuntimeError('ai-toolkit is not configured')
    return p


def _jobs_dir():
    d = cfg.aitoolkit_path('jobs')
    if not d:
        raise RuntimeError('ai-toolkit is not configured')
    d.mkdir(parents=True, exist_ok=True)
    return d


# ComfyUI-side destinations (deploy target for a trained LoRA, and the SDXL base
# checkpoint pool). Distinct error message from the aitoolkit accessors above:
# a dataset can be trainable (aitoolkit OK) while ComfyUI itself is unconfigured,
# and the two are gated independently by the Settings/capabilities probe.
def _lora_dest_dir_zimage():
    d = cfg.comfyui_dir('loras')
    if not d:
        raise RuntimeError('ComfyUI is not configured')
    return d / 'z image'


def _lora_dest_dir_sdxl():
    d = cfg.comfyui_dir('loras')
    if not d:
        raise RuntimeError('ComfyUI is not configured')
    return d / 'sdxl'


def _lora_dest_dir_krea():
    d = cfg.comfyui_dir('loras')
    if not d:
        raise RuntimeError('ComfyUI is not configured')
    return d / 'krea'


def _lora_dest_dir_flux():
    d = cfg.comfyui_dir('loras')
    if not d:
        raise RuntimeError('ComfyUI is not configured')
    return d / 'flux'


def _lora_dest_dir_flux2klein():
    d = cfg.comfyui_dir('loras')
    if not d:
        raise RuntimeError('ComfyUI is not configured')
    return d / 'flux2klein'


def _sdxl_checkpoints_dir():
    d = cfg.comfyui_dir('models')
    if not d:
        raise RuntimeError('ComfyUI is not configured')
    return d / 'checkpoints'


def is_installed() -> bool:
    """ai-toolkit est-il installé (venv python présent) ?"""
    p = cfg.aitoolkit_path('venv_python')
    return bool(p) and p.is_file()


def _aitoolkit_declares_arch(arch_pattern: str) -> bool:
    """L'ai-toolkit installé déclare-t-il une arch dont le nom matche
    `arch_pattern` ? Scan des sources d'archs (extensions_built_in), lecture
    fraîche à chaque appel → un `git pull` du mainteneur passe la détection à
    True sans redémarrage. Le motif est ancré sur `arch = "<nom>"` par
    l'appelant : une mention incidente (commentaire, variable) ne doit jamais
    faire un faux positif. Voir _aitoolkit_supports_krea pour l'enjeu."""
    root = cfg.aitoolkit_path('dir')
    if not root:
        return False
    ext_root = root / 'extensions_built_in'
    if not ext_root.is_dir():
        return False
    pat = re.compile(r'arch\s*=\s*[\'"]' + arch_pattern + r'[\'"]')
    for dp, _dn, files in os.walk(str(ext_root)):
        for fn in files:
            if not fn.endswith('.py'):
                continue
            try:
                with open(os.path.join(dp, fn), encoding='utf-8', errors='ignore') as fh:
                    if pat.search(fh.read()):
                        return True
            except OSError:
                continue
    return False


def _aitoolkit_supports_krea() -> bool:
    """L'ai-toolkit installé connaît-il l'arch Krea 2 ? C'est CRITIQUE : ai-toolkit
    fait `if ModelClass.arch == config.arch` puis, sans match, retombe
    SILENCIEUSEMENT sur le loader SD legacy (get_model.py:get_model_class) - aucune
    erreur levée. Une config `arch:'krea2'` sur un ai-toolkit pas à jour chargerait
    donc Krea-2-Turbo comme un checkpoint SD et planterait de façon confuse. On
    scanne les sources d'archs (extensions_built_in) ; lecture fraîche → dès que
    le mainteneur fait `git pull`, la détection passe à True sans redémarrage.

    On exige l'arch EXACTE `arch = "krea2"` (la chaîne émise par _build_job_config_krea),
    pas la simple sous-chaîne « krea » : sinon une mention incidente (commentaire,
    variable) ferait un FAUX POSITIF, et surtout si l'arch upstream diffère (ex.
    « krea2_turbo ») la garde donnerait un feu vert alors que get_model_class ne
    matcherait pas → fallback SD silencieux, précisément ce qu'on veut empêcher."""
    return _aitoolkit_declares_arch(r'krea2')


def _aitoolkit_supports_flux2klein() -> bool:
    """L'ai-toolkit installé connaît-il FLUX.2 Klein ? Même enjeu CRITIQUE que
    _aitoolkit_supports_krea (lire son commentaire) : les archs flux2_klein_4b/9b
    sont des EXTENSIONS (extensions_built_in/diffusion_models/flux2), pas des archs
    cœur comme 'flux' — un ai-toolkit pas à jour ne les connaît pas et
    get_model_class retomberait SILENCIEUSEMENT sur le loader SD legacy → LoRA
    corrompu. On exige l'arch EXACTE `arch = "flux2_klein_4b"` ou `"..._9b"` (les
    chaînes émises par _build_job_config_flux2klein), jamais la sous-chaîne
    « klein » seule — une mention incidente ferait un faux positif. Lecture
    fraîche : un `git pull` du mainteneur passe la détection à True sans restart."""
    return _aitoolkit_declares_arch(r'flux2_klein_(?:4b|9b)')


def _safe_trigger(ds) -> str:
    t = (ds.trigger_word or f'dataset{ds.id}').strip()
    return ''.join(c if (c.isalnum() or c in '_-') else '_' for c in t) or f'dataset{ds.id}'


def _train_type(ds, family=None) -> str:
    """Famille de modèle entraînée : 'zimage' (défaut/None), 'sdxl', 'krea',
    'flux' ou 'flux2klein'.
    `family` (override) prime sur le train_type persisté quand fourni (non vide) -
    c'est ce qui permet au sélecteur de famille de l'UI de piloter la lecture des
    runs/checkpoints/déploiements SANS écraser le train_type persisté du dataset."""
    return ((family or None) or getattr(ds, 'train_type', None) or 'zimage').lower()


def _lora_dest_dir(ds, family=None) -> str:
    """Dossier loras ComfyUI où DÉPLOYER le LoRA entraîné, routé par famille :
    krea → loras/krea/ (pour qu'il apparaisse dans le menu de génération Krea via
    get_krea_loras), sdxl → loras/sdxl/, zimage (défaut) → « z image/ ». Garde les
    familles séparées (un LoRA Krea ne doit pas polluer le Test Studio Z-Image)."""
    fam = _train_type(ds, family)
    if fam == 'sdxl':
        return str(_lora_dest_dir_sdxl())
    if fam == 'krea':
        return str(_lora_dest_dir_krea())
    if fam == 'flux':
        return str(_lora_dest_dir_flux())
    if fam == 'flux2klein':
        return str(_lora_dest_dir_flux2klein())
    return str(_lora_dest_dir_zimage())


def _sdxl_base_choices() -> set:
    """Whitelist serveur des bases SDXL = basenames des checkpoints ComfyUI.
    include_hidden=True pour ne pas exclure un checkpoint masqué légitime, et
    pour récupérer une forme stable quelle que soit la variante de retour."""
    from ..utils.comfyui import get_checkpoint_models
    out = set()
    for c in (get_checkpoint_models(include_hidden=True) or []):
        out.add(c['name'] if isinstance(c, dict) else c)
    return out


def _sdxl_base_path(base_model: str) -> str:
    """Résout le .safetensors SDXL sous models/checkpoints. get_checkpoint_models
    APLATIT en basename (l'info de sous-dossier - ex. Biglove/ - est perdue) → on
    cherche récursivement le basename. Refuse chemin absolu / '..' (anti-traversal ;
    la whitelist amont _sdxl_base_choices garantit déjà un basename connu)."""
    name = str(base_model or '')
    parts = name.replace('\\', '/').split('/')
    if os.path.isabs(name) or '..' in parts:
        raise ValueError('invalid SDXL base path')
    checkpoints_dir = str(_sdxl_checkpoints_dir())
    cand = os.path.join(checkpoints_dir, name)
    if os.path.exists(cand):
        return cand
    base = os.path.basename(name.replace('\\', '/'))
    for root, _dirs, files in os.walk(checkpoints_dir):
        if base in files:
            return os.path.join(root, base)
    return name  # fallback (ne devrait pas arriver : base whitelistée + existante)


# --- Custom weights (V1 « Custom weights… », local-only) ----------------------
# A base VALUE that is a free ABSOLUTE local path to a .safetensors is the
# opt-in custom-weights field: krea/flux/flux2klein/sdxl load it as name_or_path
# (same architecture, TE/VAE still official for the non-sdxl families). It is
# distinguished from a ComfyUI-relative base name (SDXL whitelist basename,
# Z-Image merge value) purely by being ABSOLUTE — those are never absolute. Only
# the families below expose it; Z-Image keeps its own conversion path untouched.
CUSTOM_WEIGHTS_FAMILIES = ('sdxl', 'krea', 'flux', 'flux2klein')
# SDXL is the ONLY family where ai-toolkit honours a top-level vae_path /
# te_name_or_path override (stable_diffusion_model.py). Every other family
# bundles its TE/VAE (Z-Image extras_name_or_path, Klein's hardcoded MISTRAL_PATH
# → a silent no-op) so exposing them there would lie — strict per-family whitelist.
VAE_TE_OVERRIDE_FAMILIES = ('sdxl',)


def _is_custom_weights(value) -> bool:
    """True when `value` is the opt-in custom-weights path (a free ABSOLUTE local
    path), as opposed to a ComfyUI-relative base/merge name or the official base."""
    return bool(value) and os.path.isabs(str(value))


_SAFETENSORS_MAX_HEADER = 64 * 1024 * 1024   # 64 MB — a real header is < ~10 MB


def _read_safetensors_header(path):
    """(`__metadata__` dict, tensor-NAME set) of a .safetensors file, read from
    its header WITHOUT loading a single weight (8-byte LE length + JSON metadata
    block). Raises ValueError when the file isn't a readable safetensors
    container. The metadata block is where ai-toolkit stamps ss_base_model_version
    (the strongest architecture signal); the tensor names are the fallback sniff."""
    try:
        with open(path, 'rb') as fh:
            raw = fh.read(8)
            if len(raw) != 8:
                raise ValueError('file too short to be a safetensors container')
            n = struct.unpack('<Q', raw)[0]
            if n <= 0 or n > _SAFETENSORS_MAX_HEADER:
                raise ValueError('implausible safetensors header length')
            blob = fh.read(n)
            if len(blob) != n:
                raise ValueError('truncated safetensors header')
            meta = json.loads(blob.decode('utf-8'))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise ValueError(f'not a readable .safetensors file ({e})')
    if not isinstance(meta, dict):
        raise ValueError('not a readable .safetensors file (header is not an object)')
    md = meta.get('__metadata__')
    if not isinstance(md, dict):
        md = {}
    return md, {k for k in meta if k != '__metadata__'}


def _safetensors_tensor_keys(path) -> set:
    """The tensor NAMES of a .safetensors file, read from its header WITHOUT
    loading a single weight. Raises ValueError when the file isn't a readable
    safetensors container."""
    return _read_safetensors_header(path)[1]


def _detect_safetensors_arch(keys) -> str | None:
    """Best-effort architecture family from tensor NAMES only. Returns one of
    'sdxl' | 'sd15' | 'flux' | 'krea2', or None when undetectable. 'flux' covers
    BOTH FLUX.1 and FLUX.2 Klein — their DiT stream blocks are named identically,
    so a name-only sniff cannot tell them apart (an honest V1 limitation; a wrong
    FLUX.1↔FLUX.2 file still fails loudly at load, on a shape mismatch)."""
    def has(sub):
        return any(sub in k for k in keys)
    # SDXL LDM single-file checkpoint: the tell is the SECOND (OpenCLIP bigG) text
    # encoder — SD1.5 has a single encoder under cond_stage_model.
    if has('conditioner.embedders.1.'):
        return 'sdxl'
    if has('cond_stage_model.'):
        return 'sd15'
    # Krea2 SingleStreamDiT MMDiT: 'txtfusion' is unique to it.
    if has('txtfusion.'):
        return 'krea2'
    # FLUX-family DiT (FLUX.1 / FLUX.2 Klein): double + single stream blocks
    # (BFL layout) or the diffusers export naming.
    if (has('double_blocks.') and has('single_blocks.')) \
            or has('single_transformer_blocks.'):
        return 'flux'
    return None


# --- Trained-LoRA architecture detector (the deploy/Studio guardrail) ---------
# The base sniff above targets full UNET checkpoints (a BASE); a TRAINED LoRA has
# a different, prefixed key layout (lora_A/lora_B, lokr_w*, kohya lora_unet_*). A
# wrong-arch LoRA is invisible to ComfyUI: it drops every incompatible key
# SILENTLY, so the whole grid renders as if the LoRA were off (the 2026-07-13
# incident — a Z-Image LoRA mislabelled Krea produced 117 no-op tiles). We read
# the real arch from the header and check it wherever a LoRA is deployed or run.
#
# Verdict = FAMILY key ('zimage'|'sdxl'|'krea'|'flux'|'flux2klein') or None
# (undetectable → callers MUST NOT block; the guarantee is simply absent).
_LORA_ARCH_LABEL = {'zimage': 'Z-Image', 'sdxl': 'SDXL', 'krea': 'Krea 2',
                    'flux': 'FLUX.1', 'flux2klein': 'FLUX.2 Klein'}
# Key-namespace GROUP: two families in the SAME group share the tensor namespace,
# so a wrong file loads its keys (a version mismatch then fails LOUDLY on a shape
# error, not silently). Different groups = disjoint names = SILENT drop = the
# danger we block. FLUX.1 and FLUX.2 Klein share the double/single-stream layout,
# so they're one group (a name-only sniff can't tell them apart anyway).
_LORA_ARCH_NAMESPACE = {'zimage': 'zimage', 'sdxl': 'sdxl', 'krea': 'krea',
                        'flux': 'flux', 'flux2klein': 'flux'}


def _family_from_base_model_version(value) -> str | None:
    """Map ai-toolkit's ss_base_model_version metadata to a FAMILY key. Real
    values observed on deployed LoRAs (C:\\ai-toolkit: toolkit/metadata.py stamps
    'sdxl_1.0'/'sd_1.5'/'sd_2.1'; each newer arch's get_base_model_version returns
    'zimage' / 'krea2' / 'flux' / 'flux2_klein_4b' / 'flux2_klein_9b'). SD1.5/2.1
    and any foreign value → None (not one of our trainable families)."""
    v = str(value or '').strip().lower()
    if not v:
        return None
    if v.startswith(('flux2_klein', 'flux2klein')):
        return 'flux2klein'
    if v.startswith('flux'):
        return 'flux'
    if 'zimage' in v or 'z_image' in v or 'z-image' in v:
        return 'zimage'
    if 'krea' in v:                      # 'krea2'
        return 'krea'
    if v.startswith(('sdxl', 'sd_xl')):
        return 'sdxl'
    return None


def _lora_arch_from_keys(keys) -> str | None:
    """Best-effort FAMILY from a trained LoRA's tensor NAMES (fallback when the
    metadata is absent/foreign). Signatures verified against real deployed LoRAs:
      - kohya SD/SDXL: 'lora_unet_*' / 'lora_te*' prefixes                → sdxl
      - FLUX-family DiT: 'double_blocks.'/'single_blocks.' (BFL) or the
        diffusers 'single_transformer_blocks.' — FLUX.1 AND FLUX.2 Klein  → flux
      - Krea2 SingleStreamDiT: 'txtfusion' is unique to it (present even
        in a header-only stub); or diffusion_model.blocks.*.attn.{wk,wq,gate} → krea
      - Z-Image NextDiT: 'diffusion_model.layers.*' (adaLN / attention.to_*) → zimage
    A name-only sniff can't separate FLUX.1 from FLUX.2 Klein → 'flux' for both."""
    def has(sub):
        return any(sub in k for k in keys)
    if has('lora_unet_') or has('lora_te'):
        return 'sdxl'
    if has('double_blocks.') or has('single_blocks.') \
            or has('single_transformer_blocks.'):
        return 'flux'
    if has('txtfusion') or (has('diffusion_model.blocks.')
                            and (has('.attn.wk') or has('.attn.wq')
                                 or has('.attn.gate'))):
        return 'krea'
    if has('diffusion_model.layers.'):
        return 'zimage'
    return None


# Header reads are pure functions of the file bytes; a deployed LoRA never mutates
# in place. Cache the verdict by (abspath, mtime_ns, size) so repeated listing /
# preflight passes read each header at most once.
_LORA_ARCH_CACHE: dict = {}


def detect_lora_arch(path) -> str | None:
    """The real FAMILY of a trained LoRA .safetensors, read from its header
    WITHOUT loading a single weight. Returns 'zimage'|'sdxl'|'krea'|'flux'|
    'flux2klein', or None when undetectable (unreadable/foreign header, or a
    layout we don't recognize) — callers treat None as 'no guarantee, do not
    block'. Never raises. Metadata (ss_base_model_version) wins over the tensor
    sniff; only the sniff can appear when the metadata was stripped."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    if key in _LORA_ARCH_CACHE:
        return _LORA_ARCH_CACHE[key]
    fam = None
    try:
        md, keys = _read_safetensors_header(path)
        fam = _family_from_base_model_version(md.get('ss_base_model_version'))
        if fam is None:
            fam = _lora_arch_from_keys(keys)
    except ValueError:
        fam = None
    _LORA_ARCH_CACHE[key] = fam
    return fam


def lora_arch_conflicts(detected, family) -> bool:
    """True only when a POSITIVELY-detected LoRA arch cannot be loaded by
    `family`'s pipeline (different key namespace → ComfyUI drops every key
    SILENTLY → the LoRA is a no-op). None/unknown on either side → False (never a
    false block). flux vs flux2klein share a namespace (a wrong version fails
    LOUDLY on a shape error) → not a conflict."""
    if not detected:
        return False
    dg = _LORA_ARCH_NAMESPACE.get(detected)
    fg = _LORA_ARCH_NAMESPACE.get((family or '').lower())
    if dg is None or fg is None:
        return False
    return dg != fg


_FAMILY_EXPECTED_ARCH = {'sdxl': 'sdxl', 'krea': 'krea2',
                         'flux': 'flux', 'flux2klein': 'flux'}
_ARCH_LABEL = {'sdxl': 'an SDXL', 'sd15': 'a Stable Diffusion 1.5',
               'flux': 'a FLUX', 'krea2': 'a Krea 2'}
# Confirmable-refusal marker (mirrors UNCAPTIONED:/MISMATCH_CAPTION:): the UI
# strips it, asks window.confirm, and retries with allow_unverified_weights.
_UNVERIFIED_MARKER = 'CUSTOM_WEIGHTS_UNVERIFIED: '


def _looks_like_local_path(s) -> bool:
    """A te_name_or_path may be a HF repo id ('org/name') OR a local dir/file.
    Treat it as LOCAL (and therefore existence-checkable) only when it is an
    absolute path, already exists, or carries a Windows backslash — a bare
    'org/name' repo id stays unverifiable (accepted as-is)."""
    s = str(s)
    return bool(s) and (os.path.isabs(s) or os.path.exists(s) or '\\' in s)


def preflight_custom_paths(family, weights=None, vae_path=None, te_path=None,
                           allow_unverified_weights=False) -> None:
    """Validate the custom base/vae/te BEFORE any run dir or spawn (guardrail).

    HARD failures (→ ValueError, mapped to 400): a provided path that does not
    exist, or a .safetensors whose header can't be parsed. A file whose
    architecture can't be POSITIVELY matched to `family` raises a CONFIRMABLE
    ValueError (the _UNVERIFIED_MARKER) unless `allow_unverified_weights` — the
    same confirm-and-retry contract as UNCAPTIONED. vae_path/te_path are only
    ever passed for SDXL (the caller enforces the per-family whitelist)."""
    fam_label = _FAMILY_LABEL.get(family, family)
    if _is_custom_weights(weights):
        if not os.path.isfile(weights):
            raise ValueError(f'custom weights file not found: {weights}')
        keys = _safetensors_tensor_keys(weights)   # raises on unreadable header
        detected = _detect_safetensors_arch(keys)
        expected = _FAMILY_EXPECTED_ARCH.get(family)
        if expected is None or detected != expected:
            if not allow_unverified_weights:
                if detected and detected in _ARCH_LABEL:
                    why = (f'this file looks like {_ARCH_LABEL[detected]} checkpoint, '
                           f'not {fam_label}')
                else:
                    why = (f'cannot verify this file matches {fam_label} — it carries '
                           f'no recognizable {fam_label} signature')
                raise ValueError(f'{_UNVERIFIED_MARKER}{why}.')
    # VAE override (SDXL): a local file/dir must exist; a .safetensors must parse.
    if vae_path:
        if not os.path.exists(vae_path):
            raise ValueError(f'VAE file not found: {vae_path}')
        if os.path.isfile(vae_path) and str(vae_path).endswith('.safetensors'):
            _safetensors_tensor_keys(vae_path)     # raises on unreadable header
    # TE override (SDXL): a LOCAL path must exist; a bare HF repo id is accepted.
    if te_path and _looks_like_local_path(te_path) and not os.path.exists(te_path):
        raise ValueError(f'text-encoder path not found: {te_path}')


# Sentinelle « base non fournie » : distingue l'absence d'argument (→ base
# PERSISTÉE du dataset) de la valeur '' (= base officielle, un choix explicite).
_PERSISTED = object()


def _effective_vae_te(ds, family, vae_path, te_path):
    """Triplet VAE/TE effectif d'un lancement OU d'une mise en file.

    VAE/TE ne sont honorés QUE par SDXL (ai-toolkit) → toute autre famille
    REFUSE explicitement un override fourni, jamais d'ignore silencieux.
    `_PERSISTED` = « non fourni par l'appelant » → on garde la valeur persistée
    (continue/queue) ; une valeur explicite (même vide) remplace.

    La file et le lancement doivent appliquer EXACTEMENT la même règle : sinon
    la file accepte un job que le lanceur refusera au démarrage.
    """
    prov_vae = vae_path is not _PERSISTED and (vae_path or '').strip()
    prov_te = te_path is not _PERSISTED and (te_path or '').strip()
    if family not in VAE_TE_OVERRIDE_FAMILIES:
        if prov_vae or prov_te:
            raise ValueError('VAE / text-encoder overrides are SDXL-only')
        return None, None
    return ((ds.train_vae_path if vae_path is _PERSISTED
             else ((vae_path or '').strip() or None)),
            (ds.train_te_path if te_path is _PERSISTED
             else ((te_path or '').strip() or None)))


def _base_tag_for(base_model) -> str:
    """Suffixe de run pour une base EXPLICITE ('' / None = officiel → '')."""
    if not base_model:
        return ''
    base = os.path.basename(str(base_model).replace('\\', '/')).rsplit('.', 1)[0]
    safe = ''.join(c if (c.isalnum() or c in '_-') else '_' for c in base)
    return f'_{safe}' if safe else ''


def _base_tag(ds) -> str:
    """Suffixe de run dérivé de la base d'entraînement PERSISTÉE (vide = officiel).
    Isole les checkpoints d'un run sur merge de ceux du run officiel du même
    dataset (sinon ai-toolkit auto-resume depuis le mauvais base → mélange)."""
    return _base_tag_for(getattr(ds, 'train_base_model', None))


KREA_BASE_LABEL = 'Krea-2-Turbo'   # mirrors name_or_path 'krea/Krea-2-Turbo'
# Flux a une seule base officielle (FLUX.1-dev). Sans point dans le label (sinon
# _base_tag_for le prendrait pour une extension et tronquerait à « FLUX ») → tag
# stable '_FLUX-1-dev' qui isole les runs/LoRA Flux des runs Z-Image officiels
# (tag vide) au même trigger — même garde anti-collision que Krea (cf. _dest_base_tag).
FLUX_BASE_LABEL = 'FLUX-1-dev'
# FLUX.2 Klein a DEUX bases officielles (4B et 9B) → tags DISTINCTS obligatoires :
# les poids 4B et 9B sont incompatibles, et un même trigger entraîné sur les deux
# variantes partagerait sinon le même dossier de run (auto-resume croisé → LoRA
# corrompu) et le même nom de LoRA déployé. Sans point dans les labels (même piège
# d'extension que FLUX_BASE_LABEL : _base_tag_for tronque après un '.').
FLUX2KLEIN_BASE_LABELS = {'4b': 'FLUX2-Klein-4B', '9b': 'FLUX2-Klein-9B'}


def _krea_is_raw(ds) -> bool:
    """Krea 2 training base. `train_variant` 'base'/'raw' → Krea-2-Raw (non-distilled,
    the official recommendation « train on Raw, validate on Turbo » — best quality,
    the LoRA transfers to Turbo at inference); 'turbo' → Krea-2-Turbo + Ostris adapter
    (VRAM-friendly). Default RAW when unset — that's the chosen product default, so the
    tag and the job-config never disagree even if train_variant was never persisted."""
    return (getattr(ds, 'train_variant', None) or 'base').lower() in ('base', 'raw')


def _flux2klein_is_9b(ds) -> bool:
    """FLUX.2 Klein model size. `train_variant` '9b' → the 9B base (32-48 GB VRAM,
    the cloud-first lane); anything else → the 4B base (16-24 GB, the local lane).
    Default 4B when unset — the chosen product default (mirrors _default_variant_for),
    so the run tag and the job-config never disagree even if train_variant was
    never persisted."""
    return (getattr(ds, 'train_variant', None) or '4b').lower() == '9b'


def _default_variant_for(family) -> str:
    """Variante par défaut d'une famille quand aucune n'est fournie NI persistée :
    Krea → 'base' (Raw, reco officielle), FLUX.2 Klein → '4b' (la voie locale
    16-24 Go ; le 9B est la voie cloud), sinon 'turbo'. Utilisé par tous les
    chemins de lancement (direct / file / reprise / cloud) pour que le défaut
    tienne de bout en bout, pas seulement quand l'UI envoie explicitement la variante."""
    fam = family or 'zimage'
    if fam == 'krea':
        return 'base'
    if fam == 'flux2klein':
        return '4b'
    return 'turbo'


def _valid_variants_for(family) -> tuple:
    """Variantes acceptées au lancement, PAR FAMILLE : flux2klein n'a que ses deux
    tailles de modèle ('4b'/'9b') ; les familles historiques gardent l'enum
    turbo/base/deturbo (comportement inchangé). Une variante hors liste retombe
    sur le défaut de la famille (jamais d'erreur) : c'est ce qui neutralise une
    variante PERSISTÉE d'une autre famille quand l'utilisateur change de type
    (ex. un dataset ex-Krea avec train_variant='base' lancé en flux2klein)."""
    return ('4b', '9b') if (family or 'zimage') == 'flux2klein' \
        else ('turbo', 'base', 'deturbo')


# --- Réglages ai-toolkit avancés, éditables par dataset (persistés en JSON dans
#     `train_settings`). Absent/NULL → défaut family-aware issu de la recherche
#     (cf. Research vault 2026-07-10). Toute valeur hors des listes autorisées
#     retombe sur le défaut : on ne pousse JAMAIS une config invalide à ai-toolkit. ---
_DEFAULT_RANK = {'zimage': 16, 'krea': 32, 'sdxl': 32, 'flux': 16, 'flux2klein': 16}   # Z-Image reste 16 (choix user) ; Krea/SDXL 32 ; Flux/FLUX.2 Klein 16 (défaut des exemples officiels)
_RANK_CHOICES = (8, 16, 24, 32, 48, 64)
# multi-échelle par défaut ; '768' seul = LE levier basse-VRAM (Krea 12B : 1024
# sature un 24 GB à ~180 s/it, 768 mesuré ~3,5 s/it — cf. commentaire de tête).
_RES_CHOICES = {'768,1024': [768, 1024], '1024': [1024], '768': [768]}
_SAVE_CHOICES = (250, 500, 1000)
# --- Expert levers (train_settings, ALL default to current behaviour when absent,
#     so a newcomer who never touches them gets the exact same config as before) ---
_DROPOUT_CHOICES = (0.05, 0.1, 0.15, 0.2, 0.3)          # LoRA network dropout ; absent = off
_ALPHA_CHOICES = (1, 2, 4, 8, 16, 24, 32, 48, 64)       # alpha découplé du rank ; absent = dérivé
_TIMESTEP_TYPE_CHOICES = ('sigmoid', 'linear', 'weighted', 'shift')  # pondération flowmatch ; SDXL le désactive
_DEFAULT_TIMESTEP = {'zimage': 'sigmoid', 'krea': 'linear', 'flux': 'sigmoid',
                     'flux2klein': 'weighted'}   # ce que « Auto » résout (sdxl : aucun) ; flux subject → sigmoid (reco ai-toolkit) ; flux2klein → weighted (défaut canonique options.ts, PAS sigmoid)
# Batch 2 — optimiseur / planning du LR / batch effectif (valeurs VÉRIFIÉES dans
# ai-toolkit : get_optimizer + toolkit/scheduler.py). CAME n'est PAS supporté.
_OPTIMIZER_CHOICES = ('adamw8bit', 'adafactor', 'automagic', 'prodigy')
_LR_SCHEDULER_CHOICES = ('constant', 'linear', 'cosine', 'cosine_with_restarts', 'constant_with_warmup')
_WARMUP_CHOICES = (50, 100, 200, 500)          # num_warmup_steps ; UNIQUEMENT avec constant_with_warmup
_GRAD_ACCUM_CHOICES = (1, 2, 4)
# Network variant + EMA — both VÉRIFIÉS arch-génériques dans ai-toolkit installé :
#   - network.type='lokr' : LoRASpecialNetwork choisit LokrModule pour TOUTE arch
#     (toolkit/lora_special.py L384 `elif self.network_type.lower() == "lokr"`) et
#     'lokr' est dans le Literal NetworkType (toolkit/config_modules.py L165). Aucune
#     famille exclue → PAS de whitelist. lokr_factor reste au défaut -1 (auto = plus
#     grand facteur) donc non émis. NB : use_old_lokr_format diffère selon l'arch
#     (nommage des poids seulement, pas le support) — krea2/flux2_klein = nouveau
#     format, zimage/sdxl/flux = ancien ; les deux s'entraînent et se chargent.
#   - train.ema_config={use_ema, ema_decay} : knob niveau TrainConfig, arch-agnostique
#     (config_modules.py L525-533 + EMAConfig L794-797, défaut ema_decay=0.999).
# Recette communautaire (Krea-2) : LoKr + rank bas + EMA 0.99 → ressemblance ~step 500.
_NETWORK_TYPE_CHOICES = ('lora', 'lokr')
_EMA_CHOICES = (0.99, 0.999)


from .lora_training_settings import (  # noqa: E402
    _DEFAULT_SAMPLE_PROMPTS_CHARACTER,
    _DEFAULT_SAMPLE_PROMPTS_CONCEPT,
    _DEFAULT_SAMPLE_PROMPTS_STYLE,
    _MAX_SAMPLE_PROMPTS,
    _MAX_SAVES_CHOICES,
    _SAMPLE_EVERY_CHOICES,
    _default_sample_prompts,
    _ema_eff,
    _ema_fields,
    _grad_accum,
    _inject_trigger,
    _lora_alpha,
    _lora_alpha_eff,
    _lora_rank,
    _lr_eff,
    _lr_sched_fields,
    _max_step_saves,
    _network_block,
    _network_type_eff,
    _optimizer_eff,
    _resolved_default_sample_prompts,
    _sample_every,
    _sample_prompts,
    _save_every,
    _timestep_type_eff,
    _train_res,
    _train_settings,
    effective_train_settings,
    launch_settings_snapshot,
)




def update_train_settings(user_id, dataset_id, patch: dict, *, commit=True) -> dict:
    """Valide + fusionne un patch {rank?, resolution?, save_every?, sample_every?,
    sample_prompts?} dans train_settings. Une clé à None/'auto'/vide est RETIRÉE
    (retour au défaut). Retourne les réglages effectifs pour la famille courante."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise DomainValidationError('dataset not found')
    cur = _train_settings(ds)
    if 'rank' in patch:
        r = patch['rank']
        if r in (None, 'auto'):
            cur.pop('rank', None)
        elif r in _RANK_CHOICES:
            cur['rank'] = r
        else:
            raise DomainValidationError(f'rank must be one of {_RANK_CHOICES} (or auto)')
    if 'resolution' in patch:
        v = patch['resolution']
        if v in _RES_CHOICES:
            cur['resolution'] = v
        else:
            raise DomainValidationError(f'resolution must be one of {list(_RES_CHOICES)}')
    if 'save_every' in patch:
        v = patch['save_every']
        if v in _SAVE_CHOICES:
            cur['save_every'] = v
        else:
            raise DomainValidationError(f'save_every must be one of {_SAVE_CHOICES}')
    if 'max_step_saves' in patch:
        v = patch['max_step_saves']
        if v in (None, 'auto'):
            cur.pop('max_step_saves', None)
        elif v in _MAX_SAVES_CHOICES:
            cur['max_step_saves'] = v
        else:
            raise DomainValidationError(f'max_step_saves must be one of {_MAX_SAVES_CHOICES}')
    if 'sample_every' in patch:
        v = patch['sample_every']
        if v in _SAMPLE_EVERY_CHOICES:
            cur['sample_every'] = v
        else:
            raise DomainValidationError(f'sample_every must be one of {_SAMPLE_EVERY_CHOICES}')
    if 'sample_prompts' in patch:
        v = patch['sample_prompts']
        # Accepte aussi une string multi-lignes (une par prompt) pour le confort UI.
        if isinstance(v, str):
            v = v.splitlines()
        if v in (None, ''):
            cur.pop('sample_prompts', None)               # vide → retour aux défauts kind-aware
        elif isinstance(v, list):
            if any(not isinstance(x, str) for x in v):
                raise DomainValidationError(
                    'sample_prompts must be a list of strings (or empty to reset)')
            cleaned = [x.strip() for x in v if x.strip()][:_MAX_SAMPLE_PROMPTS]
            if cleaned:
                cur['sample_prompts'] = cleaned
            else:
                cur.pop('sample_prompts', None)
        else:
            raise DomainValidationError(
                'sample_prompts must be a list of strings (or empty to reset)')
    if 'dropout' in patch:
        v = patch['dropout']
        if v in (None, 0, 0.0, 'off', ''):
            cur.pop('dropout', None)                       # off → clé retirée
        elif v in _DROPOUT_CHOICES:
            cur['dropout'] = v
        else:
            raise DomainValidationError(
                f'dropout must be one of {_DROPOUT_CHOICES} (or off)')
    if 'alpha' in patch:
        v = patch['alpha']
        if v in (None, 'auto'):
            cur.pop('alpha', None)                         # auto → alpha dérivé du rank
        elif v in _ALPHA_CHOICES:
            cur['alpha'] = v
        else:
            raise DomainValidationError(f'alpha must be one of {_ALPHA_CHOICES} (or auto)')
    if 'timestep_type' in patch:
        v = patch['timestep_type']
        if v in (None, 'auto', ''):
            cur.pop('timestep_type', None)                 # auto → défaut family-aware
        elif v in _TIMESTEP_TYPE_CHOICES:
            cur['timestep_type'] = v
        else:
            raise DomainValidationError(
                f'timestep_type must be one of {_TIMESTEP_TYPE_CHOICES} (or auto)')
    if 'optimizer' in patch:
        v = patch['optimizer']
        if v in (None, 'auto', '', 'adamw8bit'):
            cur.pop('optimizer', None)                     # défaut → clé retirée
        elif v in _OPTIMIZER_CHOICES:
            cur['optimizer'] = v
        else:
            raise DomainValidationError(
                f'optimizer must be one of {_OPTIMIZER_CHOICES} (or auto)')
    if 'lr_scheduler' in patch:
        v = patch['lr_scheduler']
        if v in (None, 'auto', '', 'constant'):
            cur.pop('lr_scheduler', None)                  # constant = défaut → clé retirée
        elif v in _LR_SCHEDULER_CHOICES:
            cur['lr_scheduler'] = v
        else:
            raise DomainValidationError(
                f'lr_scheduler must be one of {_LR_SCHEDULER_CHOICES} (or auto)')
    if 'warmup' in patch:
        v = patch['warmup']
        if v in (None, 0, 'off', ''):
            cur.pop('warmup', None)
        elif v in _WARMUP_CHOICES:
            cur['warmup'] = v
        else:
            raise DomainValidationError(f'warmup must be one of {_WARMUP_CHOICES} (or off)')
    if 'grad_accum' in patch:
        v = patch['grad_accum']
        if v in (None, 1, 'auto'):
            cur.pop('grad_accum', None)                    # 1 = défaut → clé retirée
        elif v in _GRAD_ACCUM_CHOICES:
            cur['grad_accum'] = v
        else:
            raise DomainValidationError(
                f'grad_accum must be one of {_GRAD_ACCUM_CHOICES} (or auto)')
    if 'network_type' in patch:
        v = patch['network_type']
        if v in (None, 'auto', '', 'lora'):
            cur.pop('network_type', None)                  # lora = défaut → clé retirée
        elif v in _NETWORK_TYPE_CHOICES:
            cur['network_type'] = v
        else:
            raise DomainValidationError(
                f'network_type must be one of {_NETWORK_TYPE_CHOICES} (or auto)')
    if 'ema' in patch:
        v = patch['ema']
        if v in (None, 'off', '', 0, 0.0):
            cur.pop('ema', None)                           # off → clé retirée
        elif v in _EMA_CHOICES:
            cur['ema'] = v
        else:
            raise DomainValidationError(f'ema must be one of {_EMA_CHOICES} (or off)')
    ds.train_settings = json.dumps(cur) if cur else None
    if commit:
        fds.db.session.commit()
    return effective_train_settings(ds)


# Every key update_train_settings knows how to validate — KEEP IN SYNC when a
# new expert lever is added above. This is what makes presets schema-tolerant:
# a preset key outside this list is IGNORED (and reported), never fatal.
TRAIN_SETTING_KEYS = ('rank', 'resolution', 'save_every', 'max_step_saves',
                      'sample_every', 'sample_prompts', 'dropout', 'alpha',
                      'timestep_type', 'optimizer', 'lr_scheduler', 'warmup',
                      'grad_accum', 'network_type', 'ema')

# Built-in presets: shipped with the app (every install sees them), read-only,
# versioned with the code. The recommended character recipe: the researched
# family defaults pinned explicitly, plus the checkpoint-SELECTION machinery —
# a save + a probe preview at every 250 steps and no snapshot cap, because on
# character sets the quality comes from picking the earliest checkpoint that
# holds the identity, not from exotic hyper-parameters. Steps stay adaptive
# (~120 × kept images). A test asserts every builtin applies with zero
# ignored/rejected keys, so a drifting choice-list can't silently break them.
BUILTIN_TRAIN_PRESETS = [
    {
        'id': 'builtin-krea-character',
        'name': 'Krea character — recommended',
        'train_type': 'krea',
        'builtin': True,
        'settings': {
            'rank': 32,                    # Krea researched default (alpha derives = 32)
            'resolution': '768,1024',      # multi-scale: close-up → full body
            'save_every': 250,
            'max_step_saves': 10,          # keep every snapshot — all sweet-spot candidates
            'sample_every': 250,           # one probe sheet per checkpoint
            'sample_prompts': [            # identity AND flexibility probes — overfit
                                           # (waxy skin, frozen pose) shows here first
                '{trigger}, close-up portrait, neutral expression, soft studio light',
                '{trigger}, headshot, golden hour sunlight, slight smile',
                '{trigger}, bust shot, profile view, window light',
                '{trigger}, full body, walking outdoors in a park, casual jeans and t-shirt',
                '{trigger}, full body, elegant evening dress, dim moody lighting',
                '{trigger}, sitting at a cafe table, laughing, candid photo',
                '{trigger}, sportswear, stretching in a gym, harsh fluorescent light',
                '{trigger}, wide shot, standing on a beach at dusk, wind in hair',
            ],
        },
    },
    # Concept/style runs scale SUB-linearly (recommended_steps: 475·√n clamped
    # [2000, 12000] — code anchors: ~30-40 images → ~3000 steps, ~400 → ~9500).
    # save/sample every 500 (vs 250 for characters) is the coverage compromise:
    # max_step_saves keeps the N most RECENT saves (ai-toolkit deletes the
    # oldest), so 10×500 spans the last 5000 steps — the whole run at the small
    # anchor, the second half at the large one — while halving the preview GPU
    # cost of long runs (1 image per prompt per interval). Probes exercise the
    # concept across framings, contexts and lighting: a concept LoRA that only
    # reproduces its training context has overfit.
    {
        'id': 'builtin-concept',
        'name': 'Concept — recommended',
        'train_type': 'zimage',
        'builtin': True,
        'settings': {
            'resolution': '768,1024',
            'save_every': 500,
            'max_step_saves': 10,
            'sample_every': 500,
            'sample_prompts': [
                '{trigger}',
                '{trigger}, close-up, high detail, sharp focus',
                '{trigger}, wide shot showing the full scene',
                '{trigger}, in an unusual setting, outdoors',
                '{trigger}, soft natural window light',
                '{trigger}, night scene, artificial light',
                '{trigger}, seen from a high angle',
                '{trigger}, cinematic composition, shallow depth of field',
            ],
        },
    },
    # Same steps scale and save/preview cadence as concept (same 475·√n
    # recipe drives both). Style previews carry NO trigger — a style LoRA has
    # none and the export strips `{trigger}` on style datasets — so varied
    # CONTENT is the probe: if the aesthetic shows on a portrait AND a night
    # street AND a still life, the style generalized instead of memorizing
    # its training scenes.
    {
        'id': 'builtin-style',
        'name': 'Style — recommended',
        'train_type': 'zimage',
        'builtin': True,
        'settings': {
            'resolution': '768,1024',
            'save_every': 500,
            'max_step_saves': 10,
            'sample_every': 500,
            'sample_prompts': [
                'a woman reading in a sunlit cafe',
                'a city street at night, rain, neon reflections',
                'a mountain landscape, wide shot, morning mist',
                'a still life of fruit on a wooden table',
                'a cozy interior, warm lamp light',
                'a runner mid-stride on a bridge, motion',
                'a cat sleeping on a windowsill',
                'a modern building facade, strong shadows',
            ],
        },
    },
]


def snapshot_train_settings(user_id, dataset_id) -> dict:
    """The dataset's RAW explicit settings (what a preset captures) — only the
    keys the user actually changed, not the effective/derived view."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    return _train_settings(ds)


def apply_train_settings_dict(user_id, dataset_id, settings: dict):
    """REPLACE the dataset's explicit settings with a preset's dict, running
    every key through the validated update_train_settings path. Content is
    never fatal: unknown keys (newer/older app versions) are ignored, invalid
    values collected — both reported so the UI can say what didn't land.
    Returns (effective_settings, ignored_keys, rejected)."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    ignored = sorted(k for k in settings if k not in TRAIN_SETTING_KEYS)
    rejected = []
    try:
        ds.train_settings = None      # a preset REPLACES, it doesn't overlay
        for k in TRAIN_SETTING_KEYS:
            if k not in settings:
                continue
            try:
                update_train_settings(
                    user_id, dataset_id, {k: settings[k]}, commit=False)
            except ValueError as e:
                rejected.append({'key': k, 'reason': str(e)})
        # Publish the complete validated replacement in one durable commit.
        fds.db.session.commit()
    except BaseException:
        # SystemExit/KeyboardInterrupt model abrupt termination between keys too:
        # neither may leave the old preset cleared or a prefix committed.
        fds.db.session.rollback()
        raise
    return (effective_train_settings(fds.get_dataset(user_id, dataset_id)),
            ignored, rejected)


def _dest_base_tag(ds, base_model=_PERSISTED, family=None) -> str:
    """Deployment-name suffix, family-aware. Like _base_tag, but for Krea
    (which has no base column - always Krea-2-Turbo) falls back to a constant tag
    so the LoRA carries the model name like SDXL does. `family` override permet au
    sélecteur UI de router vers Krea même si le train_type persisté diffère."""
    tag = _base_tag(ds) if base_model is _PERSISTED else _base_tag_for(base_model)
    if not tag and _train_type(ds, family) == 'krea':
        # Raw and Turbo are DIFFERENT base checkpoints → distinct tags so their
        # run folders / deployed LoRA names never collide (same trigger, same
        # family, but incompatible weights would otherwise share a folder).
        tag = _base_tag_for('Krea-2-Raw' if _krea_is_raw(ds) else KREA_BASE_LABEL)
    # Même garde pour Flux : sa base officielle donne un tag vide, qui télescoperait
    # un run Z-Image officiel du même trigger (même dossier `u{user}_{trigger}` →
    # ai-toolkit auto-resume le mauvais run, poids mélangés). Le tag `_FLUX-1-dev`
    # isole le run et le LoRA déployé de la famille Z-Image.
    if not tag and _train_type(ds, family) == 'flux':
        tag = _base_tag_for(FLUX_BASE_LABEL)
    # FLUX.2 Klein : même garde, mais le tag encode AUSSI la variante (4B vs 9B
    # sont deux checkpoints incompatibles) — sans ça, deux runs du même trigger
    # sur les deux tailles partageraient dossier de run et nom déployé.
    if not tag and _train_type(ds, family) == 'flux2klein':
        tag = _base_tag_for(
            FLUX2KLEIN_BASE_LABELS['9b' if _flux2klein_is_9b(ds) else '4b'])
    return tag + _custom_combo_hash(ds, base_model, family)


def _custom_combo_hash(ds, base_model=_PERSISTED, family=None) -> str:
    """Short hash of the full (custom weights, VAE, TE) TRIPLET, appended to the
    run tag so two different custom combos NEVER share a run folder (ai-toolkit
    auto-resumes from the folder — a shared one would blend incompatible weights).
    Empty when nothing custom is in play, so every official/whitelist run keeps
    its exact historical folder name. VAE/TE only count for SDXL (the only family
    that honours them) — a stale value on another family can't perturb its tag."""
    fam = _train_type(ds, family)
    weights = getattr(ds, 'train_base_model', None) if base_model is _PERSISTED else base_model
    vae = getattr(ds, 'train_vae_path', None) if fam in VAE_TE_OVERRIDE_FAMILIES else None
    te = getattr(ds, 'train_te_path', None) if fam in VAE_TE_OVERRIDE_FAMILIES else None
    if not (_is_custom_weights(weights) or vae or te):
        return ''
    raw = f'{weights or ""}|{vae or ""}|{te or ""}'
    return '_h' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]


def _run_name(ds, base_model=_PERSISTED, family=None) -> str:
    """Nom de dossier de run unique par (user, trigger, base, FAMILLE) - évite qu'un
    même trigger_word chez deux datasets partage/écrase les dossiers, isole un run
    sur base custom du run officiel, ET isole les familles entre elles. `base_model`
    absent → base persistée ; fourni (même '') → cette base précise.

    Fix B (2026-07-01) : le tag vient de `_dest_base_tag` (et non `_base_tag`), donc
    un run **Krea** porte le suffixe `_Krea-2-Turbo` dans le NOM DE DOSSIER. Sans ça,
    Z-Image base-officielle (tag vide) et Krea (base vide) au même trigger tombaient
    dans le même dossier `u{user}_{trigger}` → ai-toolkit mélangeait les deux runs et
    l'import récupérait le mauvais checkpoint. zimage/sdxl restent nommés à l'identique."""
    tag = _dest_base_tag(ds, base_model, family)
    return f'u{ds.user_id}_{_safe_trigger(ds)}{tag}'


def find_run_collision(user_id, dataset_id, base_model=_PERSISTED):
    """Autre dataset du MÊME user qui produirait le même dossier de run
    (`u{user}_{trigger}{base_tag}`) que (dataset_id, base_model). C'est la source
    de collision : ai-toolkit auto-resume depuis ce dossier → LoRA mélangés, et
    deux lancements simultanés corrompent l'`optimizer.pt` partagé (incident
    Test/Test 2, 2026-06-16). Retourne le FaceDataset en conflit, ou None.

    La clé de collision est le dossier (trigger + base) ; la variante
    (turbo/deturbo) n'y entre PAS → deux datasets « même trigger + même base » se
    télescopent quoi qu'il arrive. On compare le run-name CIBLE (base en cours de
    sélection) aux run-names PERSISTÉS des autres datasets du user."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        return None
    target = _run_name(ds) if base_model is _PERSISTED else _run_name(ds, base_model)
    others = (FaceDataset.query
              .filter(FaceDataset.user_id == str(ds.user_id),
                      FaceDataset.id != int(ds.id))
              .all())
    for o in others:
        if _run_name(o) == target:
            return o
    return None


from .lora_training_export import (  # noqa: E402
    _EXPORTED_MANIFEST,
    _STYLE_CAPTION_DROPOUT,
    _mask_fields,
    _masks_dir,
    _materialize_local_training_dataset,
    _sha256_file,
    cleanup_abandoned_local_training_staging,
    export_dataset_to_aitoolkit,
    export_registry_manifest,
)




from .lora_training_config_builder import (  # noqa: E402
    _apply_style_overrides,
    _build_job_config_flux,
    _build_job_config_flux2klein,
    _build_job_config_krea,
    _build_job_config_sdxl,
    build_job_config,
)

from .lora_training_checkpoints import (  # noqa: E402
    _run_dir,
    delete_imported_checkpoint,
    import_checkpoint,
    list_checkpoints,
    list_imported_checkpoints,
    open_training_folder,
)






def _local_training_active_for(dataset_id) -> bool:
    """True while THIS dataset trains locally — its run dir is being written
    (deleting a checkpoint ai-toolkit is about to rewrite invites corruption)."""
    try:
        if not queue_manager._get_system_state('training_in_progress'):
            return False
        active_ds = queue_manager._get_system_state('training_dataset_id')
        return active_ds is not None and int(active_ds) == int(dataset_id)
    except Exception:
        return False


def delete_checkpoint(user_id, dataset_id, filename, base_model=_PERSISTED,
                      family=None) -> str:
    """Move ONE run-dir checkpoint to the trash. Whitelisted against
    list_checkpoints (anti path-traversal), refused while this dataset trains
    locally. Returns the trashed filename."""
    if _local_training_active_for(dataset_id):
        raise ValueError('this dataset is training right now — stop the run '
                         'before deleting its checkpoints')
    allowed = {c['filename'] for c in
               list_checkpoints(user_id, dataset_id, base_model, family)}
    if filename not in allowed:
        raise ValueError('unknown checkpoint')
    run_dir = _run_dir(user_id, dataset_id, base_model, family)
    from . import trash
    trash.send_to_trash(os.path.join(run_dir, filename),
                        context=f'ckpt_ds{dataset_id}')
    return filename


def cleanup_checkpoints(user_id, dataset_id, keep, base_model=_PERSISTED,
                        family=None) -> dict:
    """'Clean up this run': trash every run-dir checkpoint NOT in `keep`
    (typically the final + the best-epoch pick). Returns {'removed', 'kept'}."""
    if _local_training_active_for(dataset_id):
        raise ValueError('this dataset is training right now — stop the run '
                         'before cleaning its checkpoints')
    keep_set = {str(k) for k in (keep or [])}
    run_dir = _run_dir(user_id, dataset_id, base_model, family)
    from . import trash
    removed = 0
    for c in list_checkpoints(user_id, dataset_id, base_model, family):
        if c['filename'] in keep_set:
            continue
        try:
            trash.send_to_trash(os.path.join(run_dir, c['filename']),
                                context=f'cleanup_ds{dataset_id}')
            removed += 1
        except OSError as e:
            logger.warning('cleanup: could not trash %s: %s', c['filename'], e)
    return {'removed': removed, 'kept': sorted(keep_set)}


def _dir_size(path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def dataset_disk_usage(user_id, dataset_id, base_model=_PERSISTED, family=None) -> dict:
    """Where this dataset's training bytes live: the selected run dir, the
    immutable materialized inputs, cloud staging dirs, and deployed LoRA."""
    out = {'run_dir_bytes': 0, 'training_dataset_bytes': 0,
           'local_staging_bytes': 0,
           'cloud_staging_bytes': 0, 'deployed_bytes': 0}
    try:
        rd = _run_dir(user_id, dataset_id, base_model, family)
        if os.path.isdir(rd):
            out['run_dir_bytes'] = _dir_size(rd)
    except Exception:
        pass
    try:
        ds = fds.get_dataset(user_id, dataset_id)
        prefix = _run_name(ds, base_model, family)
        root = _datasets_dir()
        if root.is_dir():
            for candidate in root.iterdir():
                if (candidate.is_dir() and not candidate.is_symlink()
                        and candidate.name.startswith(_LOCAL_STAGING_PREFIX)):
                    try:
                        owner = json.loads((candidate / _LOCAL_STAGING_OWNER)
                                           .read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        owner = None
                    if (isinstance(owner, dict)
                            and owner.get('dataset_id') == dataset_id):
                        out['local_staging_bytes'] += _dir_size(candidate)
                    continue
                # Includes the legacy exact folder, immutable launch-token
                # folders, and their `_masks` companions for this selected run.
                if (candidate.is_dir() and not candidate.is_symlink()
                        and _trigger_boundary(candidate.name, prefix)):
                    out['training_dataset_bytes'] += _dir_size(candidate)
    except Exception:
        pass
    try:
        from ..models import CloudTrainingRun
        for r in CloudTrainingRun.query.filter_by(dataset_id=dataset_id).all():
            if r.staging_dir and os.path.isdir(r.staging_dir):
                out['cloud_staging_bytes'] += _dir_size(r.staging_dir)
    except Exception:
        pass
    try:
        ds = fds.get_dataset(user_id, dataset_id)
        root = _lora_dest_dir(ds, family)
        for c in list_imported_checkpoints(user_id, dataset_id, family=family):
            p = os.path.join(os.path.dirname(root),
                             c['filename'].replace('\\', os.sep))
            try:
                out['deployed_bytes'] += os.path.getsize(p)
            except OSError:
                pass
    except Exception:
        pass
    out['total_bytes'] = sum(v for k, v in out.items() if k.endswith('_bytes'))
    return out


def _trigger_boundary(name: str, prefix: str) -> bool:
    """`name` commence par `prefix` ET la suite est vide ou commence par `_`/`.` -
    frontière de trigger EXACTE. Évite que « Lola » attrape « Lola2 »/« Lola69382 »
    (le caractère après le préfixe doit être un séparateur, pas un chiffre/lettre)."""
    if not name.startswith(prefix):
        return False
    rest = name[len(prefix):]
    return rest == '' or rest[0] in '_.'


def purge_training_artifacts(user_id, trigger_safe) -> list[str]:
    """Move every matching training artifact into one recoverable Trash entry.

    This is an explicit cleanup utility (dataset soft-deletion deliberately
    retains training runs): deployed ComfyUI LoRAs, ai-toolkit run/export
    folders, and generated job configs are moved together transactionally.

    Sécurité : matching sur la FRONTIÈRE EXACTE du trigger (jamais un sibling type
    Lola vs Lola2) ; les noms viennent d'os.listdir (bare, pas de path-traversal) ;
    trigger vide → no-op (sinon `u{user}_` balaierait tout). Retourne les chemins
    retirés (pour log/affichage). Idempotent : un 2e appel ne retire plus rien.

    Each backend (ComfyUI loras dir / ai-toolkit output+datasets dirs) is probed
    independently; an unconfigured backend just yields no roots to sweep."""
    trigger_safe = (trigger_safe or '').strip()
    if not trigger_safe or user_id in (None, ''):
        return []
    targets: list[Path] = []
    run_prefix = f'u{user_id}_{trigger_safe}'    # ex. u1_Lola69382
    lora_prefix = f'lora_{trigger_safe}'         # ex. lora_Lola69382
    # 1) LoRA déployés dans ComfyUI (z image + sdxl + krea + flux + flux2klein séparés)
    lora_roots = []
    for accessor in (_lora_dest_dir_zimage, _lora_dest_dir_sdxl, _lora_dest_dir_krea,
                     _lora_dest_dir_flux, _lora_dest_dir_flux2klein):
        try:
            lora_roots.append(str(accessor()))
        except RuntimeError:
            pass
    for root in lora_roots:
        if not os.path.isdir(root):
            continue
        for fn in os.listdir(root):
            p = os.path.join(root, fn)
            if fn.endswith('.safetensors') and _trigger_boundary(fn, lora_prefix) and os.path.isfile(p):
                path = Path(p)
                if not path.is_symlink():
                    targets.append(path)
    # 2) run output + 3) export datasets (dossiers entiers)
    output_datasets_roots = []
    for accessor in (_output_dir, _datasets_dir):
        try:
            output_datasets_roots.append(str(accessor()))
        except RuntimeError:
            pass
    for root in output_datasets_roots:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            p = os.path.join(root, name)
            if _trigger_boundary(name, run_prefix) and os.path.isdir(p):
                path = Path(p)
                if not path.is_symlink():
                    targets.append(path)
    # 4) job configs : nommés d'après le run name (base/famille), donc un même
    #    trigger peut en avoir plusieurs (ex. un run zimage + un run krea). On
    #    balaie tout config dont le stem est sur la frontière de ce trigger,
    #    comme les étapes 2-3 pour les dossiers.
    try:
        jobs_dir = str(_jobs_dir())
    except RuntimeError:
        jobs_dir = None
    if jobs_dir and os.path.isdir(jobs_dir):
        for fn in os.listdir(jobs_dir):
            if not fn.endswith('.json'):
                continue
            p = os.path.join(jobs_dir, fn)
            if _trigger_boundary(fn[:-len('.json')], run_prefix) and os.path.isfile(p):
                path = Path(p)
                if not path.is_symlink():
                    targets.append(path)
    removed = [str(path) for path in targets]
    if targets:
        from . import trash
        trash.send_paths_to_trash(
            targets, context=f'training-artifacts-{user_id}-{trigger_safe}', metadata={
                'kind': 'training_artifacts',
                'user_id': str(user_id),
                'trigger': trigger_safe,
                'label': f'Training artifacts: {trigger_safe}',
            })
    logger.info('purge_training_artifacts u%s/%s : %d artefact(s) retiré(s)',
                user_id, trigger_safe, len(removed))
    return removed


def write_job_config(ds, dataset_folder: str, steps: int = 3000,
                     launch_token: str | None = None) -> str:
    job_cfg = build_job_config(ds, dataset_folder, steps=steps)
    # Name by the base/family-aware run name, NOT the trigger alone: a zimage run
    # and a krea run of the same trigger have distinct run names everywhere else
    # (training_folder, dataset_folder), so keying this file by trigger only made
    # the second launch silently clobber the first's config record.
    suffix = ''
    if launch_token is not None:
        token = str(launch_token)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', token):
            raise ValueError('invalid launch config token')
        suffix = f'_{token}'
    path = _jobs_dir() / f'{_run_name(ds)}{suffix}.json'
    # Atomic replace prevents a crash or full disk from leaving a truncated
    # config. Normal launches supply a unique token, preserving the exact config
    # of every attempt rather than overwriting the previous launch's evidence.
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(job_cfg, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return str(path)


def recommended_steps(dataset_id) -> int:
    """Steps cibles selon le *type* de dataset — la recette suit le dataset, pas l'inverse.

    Character (défaut) : ~120 steps/image, bornés [1500, 3500]. On verrouille une
    identité sur un petit set curé (~100-150 vues/image, consensus des guides
    ai-toolkit/Z-Image) ; un 3000 fixe surentraînait les petits datasets et
    sous-entraînait les gros. À 25 images (preset équilibré) ça redonne 3000.

    Concept / style : échelle SOUS-LINÉAIRE (√n), bornée [2000, 12000]. Un concept
    doit généraliser, pas mémoriser : plus le set grossit, moins chaque image doit
    être vue. Appliquer le taux « character » (120/img) à 400 images donnerait
    48 000 steps (overfit garanti) ; le clamp à 3500 donnait l'inverse (sous-
    entraîné). 475·√n colle aux deux points d'ancrage du consensus : ~30-40 images
    de style → ~3000 steps (guides Z-Image/SDXL), ~400 images → ~9500 steps
    (~24 vues/image, retours communautaires sur les gros sets concept/style).
    """
    ds = fds.db.session.get(FaceDataset, dataset_id)
    n = FaceDatasetImage.query.filter_by(dataset_id=dataset_id, status='keep').count()
    if ds is not None and (ds.kind or 'character') in ('concept', 'style'):
        target = int(round(475 * math.sqrt(max(n, 1)), -2))
        return max(2000, min(12000, target))
    target = int(round(n * 120, -2))  # ~120 steps/image, arrondi à la centaine
    return max(1500, min(3500, target))


def default_steps(ds) -> int:
    """Adaptive step count for a dataset — single source of truth shared by
    local launch_training and cloud training (parity guarantee). Thin ds-based
    wrapper over recommended_steps(dataset_id) (the calc used by launch_training
    when steps=None) so callers holding the ds object don't need the id."""
    return recommended_steps(ds.id)


def recommended_steps_info(dataset_id) -> dict:
    """Version « transparente » de recommended_steps pour l'UI : le nombre + le
    pourquoi, afin que l'app apprenne au débutant au lieu de décider en boîte
    noire. Ne mute rien."""
    ds = fds.db.session.get(FaceDataset, dataset_id)
    n = FaceDatasetImage.query.filter_by(dataset_id=dataset_id, status='keep').count()
    kind = (ds.kind or 'character') if ds is not None else 'character'
    steps = recommended_steps(dataset_id)
    if kind in ('concept', 'style'):
        views = round(steps / n, 1) if n else 0
        what = 'style' if kind == 'style' else 'concept'
        rationale = (f"{what.capitalize()} — {n} images kept. Sublinear scaling (475·√n, "
                     f"clamped 2000–12000): the bigger the set, the fewer views per "
                     f"image (~{views}/img here), so the LoRA generalizes the {what} "
                     f"instead of memorizing shots. Variety matters more than count.")
    else:
        rationale = (f"Character — {n} images kept. ~120 steps/image (clamped "
                     f"1500–3500): a small curated set seen many times locks the "
                     f"identity without drifting.")
    return {'steps': steps, 'kind': kind, 'n_images': n, 'rationale': rationale}


# --- Preflight d'entraînement (garde-fous, lecture seule) -----------------------
# Plancher DUR / recommandé par famille. Sous le plancher → blocker ; entre les
# deux → warning à confirmer. 10 images fixes pour tout le monde sous-estimait
# SDXL (booru, plus gourmand en variété) et laissait passer des runs voués au
# surapprentissage.
TRAIN_MIN_IMAGES = {'zimage': (12, 20), 'sdxl': (20, 30), 'krea': (15, 20), 'flux': (15, 20),
                    'flux2klein': (15, 20)}
_FAMILY_LABEL = {'zimage': 'Z-Image', 'sdxl': 'SDXL', 'krea': 'Krea 2', 'flux': 'FLUX.1',
                 'flux2klein': 'FLUX.2 Klein'}
# VRAM mesurée : Krea 2 (12B) sature un 24 GB à 1024 (cf. KREA_TRAIN_RESOLUTION). Flux
# est un DiT de même classe (12B) → même seuil recommandé.
_KREA_MIN_VRAM_GB = 24
# flux2klein est VOLONTAIREMENT absent : le check est variant-aveugle (la variante
# se choisit au lancement, après ce preflight) et le défaut 4B tient en 16-24 Go —
# un warning « il faut ~24 GB » serait un faux positif sur la voie locale normale.
# Le 9B (32-48 Go) est la voie cloud ; un seuil 24 le sous-estimerait de toute façon.
_VRAM24_FAMILIES = ('krea', 'flux')   # familles 12B qui recommandent ~24 GB à 1024


def training_preflight(user_id, dataset_id, train_type=None) -> dict:
    """Pre-launch sanity report: {'blockers': [...], 'warnings': [...]}. Blockers
    stop the launch (too few images for the family); warnings ask for one explicit
    confirm in the UI. Pure reads — never mutates, never raises on probe failures
    (an unknown GPU must not block a run).

    Émet AUSSI `checks` (liste structurée {id,label,status,detail,target}) +
    `verdict` ('ready'|'warnings'|'blocked') pour la pastille de préparation du
    workspace — construits DANS LA MÊME PASSE que blockers/warnings (une seule
    source de vérité, aucune règle dupliquée). `target` = id de section du
    workspace (gf-generate/gf-images) où corriger — None quand rien à cibler.
    NB : le check 'captioned' (images gardées sans caption) est un fail dans
    `checks` (assert_trainable refusera le launch) mais volontairement PAS un
    blocker ici — le flux modal existant (launch → erreur explicite) est conservé."""
    from .face_variations import caption_has_concept_leak, caption_has_identity_leak
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    ttype = _train_type(ds, train_type)
    label = _FAMILY_LABEL.get(ttype, ttype)
    blockers, warnings = [], []
    checks = []

    def _check(cid, clabel, status, detail, target=None):
        checks.append({'id': cid, 'label': clabel, 'status': status,
                       'detail': detail, 'target': target})

    rows = FaceDatasetImage.query.filter_by(dataset_id=dataset_id).all()
    kept = [r for r in rows if r.status == 'keep' and r.filename]
    n = len(kept)
    # CONCEPT / STYLE : plusieurs dimensions ci-dessous (équilibre de composition,
    # fuite d'identité) sont des heuristiques de LoRA PERSONNAGE sans objet quand
    # l'invariant du set n'est pas une identité — on les saute pour ne pas générer
    # de faux avertissements.
    concept = fds.is_conceptual(ds)
    coverage_profile = (ds.coverage_profile or 'balanced').lower()

    # 1) minimum d'images par famille
    floor, reco = TRAIN_MIN_IMAGES.get(ttype, (12, 20))
    if coverage_profile == 'strict':
        floor = reco
    elif coverage_profile == 'experimental':
        floor = max(4, int(math.ceil(floor * 0.7)))
        reco = max(floor, int(math.ceil(reco * 0.7)))
    if n < floor:
        blockers.append(f'{n} kept image(s) — the hard minimum for a {label} LoRA is {floor}. '
                        'Generate or import more before training.')
        _check('images', 'Enough images', 'fail',
               f'{n} kept — the hard minimum for {label} is {floor}', 'gf-generate')
    elif n < reco:
        warnings.append(f'{n} kept image(s) — {reco} recommended for a solid {label} LoRA.')
        _check('images', 'Enough images', 'warn',
               f'{n} kept — {reco}+ recommended for a solid {label} LoRA', 'gf-generate')
    else:
        _check('images', 'Enough images', 'ok', f'{n} kept ({reco}+ recommended)')

    # 2) équilibre de composition — heuristique PERSONNAGE (viser un mix face/bust/body/
    # back pour rendre un visage à toutes les distances). Sans objet pour un CONCEPT (il
    # s'apprend sur les cadrages tels quels), et un dataset non classé (framing=None) y
    # déclencherait un faux « tout en gros plan visage » → on saute pour les concepts.
    if n and not concept:
        comp = {'face': 0, 'bust': 0, 'body': 0, 'back': 0}
        for r in kept:
            if r.framing in comp:
                comp[r.framing] += 1
        _comp_ok = True
        if comp['bust'] + comp['body'] + comp['back'] == 0:
            warnings.append('every kept image is a face shot — the LoRA will struggle to '
                            'render busts and full-body scenes.')
            _check('composition', 'Framing balance', 'warn',
                   'all kept images are face shots — add bust/body shots', 'gf-generate')
            _comp_ok = False
        if fds.is_body_fidelity(ds) and comp['body'] == 0:
            warnings.append('body fidelity is ON but there is no full-body shot — the body '
                            "can't be learned without body images.")
            if _comp_ok:
                _check('composition', 'Framing balance', 'warn',
                       'body fidelity is ON but there is no full-body shot', 'gf-generate')
                _comp_ok = False
        if _comp_ok:
            _check('composition', 'Framing balance', 'ok',
                   f"face {comp['face']} · bust {comp['bust']} · body {comp['body']} · back {comp['back']}")

    # 3bis) toutes les gardées ont une caption — WARN, plus un mur : le launch
    # demande un confirm (« train anyway ») au lieu de refuser (UNCAPTIONED:
    # dans assert_trainable). Les captions restent fortement recommandées.
    uncaptioned = sum(1 for r in kept if not (r.caption or '').strip())
    if n:
        if uncaptioned:
            warnings.append(f'{uncaptioned}/{n} kept image(s) have no caption — '
                            'strongly recommended; launching will ask you to confirm.')
            _check('captioned', 'Every kept image captioned', 'warn',
                   f'{uncaptioned}/{n} kept image(s) have no caption — launching asks to confirm', 'gf-images')
        else:
            _check('captioned', 'Every kept image captioned', 'ok', f'{n}/{n} captioned')

    # 3) captions suspectes (trop courtes / dupliquées)
    caps = [(r.caption or '').strip() for r in kept if (r.caption or '').strip()]
    if caps:
        _cap_ok = True
        short = sum(1 for c in caps if len(c.split()) < 8)
        if short / len(caps) > 0.3:
            warnings.append(f'{short}/{len(caps)} caption(s) are very short (<8 words) — '
                            'weak captions weaken prompt control.')
            _check('caption_quality', 'Caption quality', 'warn',
                   f'{short}/{len(caps)} captions are very short (<8 words)', 'gf-images')
            _cap_ok = False
        if len(set(c.lower() for c in caps)) < len(caps) * 0.7:
            warnings.append('many captions are identical — the model learns nothing from '
                            'repeated text; re-caption for variety.')
            if _cap_ok:
                _check('caption_quality', 'Caption quality', 'warn',
                       'many captions are identical — re-caption for variety', 'gf-images')
                _cap_ok = False
        if _cap_ok:
            _check('caption_quality', 'Caption quality', 'ok',
                   'varied, ≥8 words')

    # 4) fuite d'identité — on RETIENT les images fautives (pas juste le compte) pour
    # que l'UI liste lesquelles au moment du preflight, éditables sur place.
    # CONCEPT : décrire l'identité (visage/cheveux/corps) est VOULU — c'est le concept,
    # pas le visage, qui se lie au trigger → la « fuite d'identité » n'a aucun sens ici.
    # On saute entièrement cette dimension (comme le badge caption_leak du payload), sinon
    # CHAQUE caption concept déclenche un faux avertissement au preflight.
    body = fds.is_body_fidelity(ds)
    if fds.is_concept(ds):
        leak_images = [
            {'id': r.id, 'filename': r.filename, 'caption': (r.caption or '').strip()}
            for r in kept if (r.caption or '').strip()
            and caption_has_concept_leak(
                (r.caption or '').strip(), ds.concept_desc, ds.concept_terms)]
    elif fds.is_style(ds):
        leak_images = []
    else:
        leak_images = [
            {'id': r.id, 'filename': r.filename, 'caption': (r.caption or '').strip()}
            for r in kept if (r.caption or '').strip()
            and caption_has_identity_leak((r.caption or '').strip(), body=body)]
    if leak_images:
        leak_kind = 'concept' if fds.is_concept(ds) else 'identity'
        message = (f'{len(leak_images)} caption(s) explicitly name the concept — remove '
                   'those terms so the trigger learns it.' if fds.is_concept(ds) else
                   f'{len(leak_images)} caption(s) still describe the identity — it will '
                   'bind to those words instead of the trigger.')
        warnings.append(message)
        _check('leaks', f'No {leak_kind} leaks', 'warn', message, 'gf-images')
    elif caps and not fds.is_style(ds):
        _check('leaks', f'No {"concept" if fds.is_concept(ds) else "identity"} leaks',
               'ok', '0 leaking caption')

    if fds.is_concept(ds):
        if not (ds.concept_desc or '').strip():
            blockers.append('concept datasets require a concrete concept description before training.')
            _check('concept_definition', 'Concept explicitly defined', 'fail',
                   'concept description is empty', 'ds-more-settings')
        else:
            _check('concept_definition', 'Concept explicitly defined', 'ok', ds.concept_desc[:120])
    if fds.is_conceptual(ds) and n:
        source_labels = {(r.source_name or '').strip().lower() for r in kept
                         if (r.source_name or '').strip()}
        if len(source_labels) < 3:
            warnings.append('concept/style admission has fewer than 3 distinct source labels — '
                            'broaden the corpus to reduce source-specific overfitting.')
            _check('source_diversity', 'Source diversity', 'warn',
                   f'{len(source_labels)}/3 distinct source labels', 'ds-add-import')
        else:
            _check('source_diversity', 'Source diversity', 'ok',
                   f'{len(source_labels)} distinct source labels')

    # 5) quasi-doublons parmi les kept (dHash pairwise, n<=~60 -> négligeable). On
    # retient les PAIRES (leurs deux images) pour que l'UI montre lesquelles rejeter.
    dup_pairs = []
    try:
        hp = []  # [(row, dhash)] pour les kept lisibles sur disque
        for r in kept:
            p = fds._img_path(r)
            if p and os.path.exists(p):
                # La colonne perceptual_hash EST le dHash de ces octets-là (elle
                # est écrite depuis les octets normalisés au moment de l'import,
                # et remise à None quand l'image est remplacée). La lire évite un
                # décodage Pillow COMPLET par image kept à chaque preflight — et
                # le preflight tourne à l'ouverture de l'onglet, à chaque
                # lancement et à chaque mise en file. Fallback = décoder, comme
                # _existing_dhash_rows côté corpus.
                value = fds._stored_hash_int(r.perceptual_hash)
                if value is None:
                    with Image.open(p) as im:
                        value = fds._dhash(im)
                hp.append((r, value))
        for i in range(len(hp)):
            for j in range(i + 1, len(hp)):
                if fds._hamming(hp[i][1], hp[j][1]) <= fds.SCRAPE_DHASH_MAX_DISTANCE:
                    ra, rb = hp[i][0], hp[j][0]
                    dup_pairs.append({'a': {'id': ra.id, 'filename': ra.filename},
                                      'b': {'id': rb.id, 'filename': rb.filename}})
        if dup_pairs:
            warnings.append(f'{len(dup_pairs)} pair(s) of kept images are near-duplicates — '
                            'the model overfits repeated content; reject one of each pair.')
            _check('duplicates', 'No near-duplicates', 'warn',
                   f'{len(dup_pairs)} near-duplicate pair(s) — reject one of each', 'gf-images')
        elif n:
            _check('duplicates', 'No near-duplicates', 'ok', '0 pair')
    except Exception:
        pass   # best-effort: an unreadable file must not block the preflight

    # 6) The training set is an admitted projection of the corpus. Surface the
    # quality signals on those admitted rows; acceptance remains a human choice,
    # but a red face crop or unverified identity must never be invisible at launch.
    quality_images = []
    if n:
        technical_red = [r for r in kept if (r.training_usefulness or '').lower() == 'red']
        technical_amber = [r for r in kept if (r.training_usefulness or '').lower() == 'amber']
        technical_unknown = [r for r in kept if not r.training_usefulness]
        face_red, face_amber, face_unknown = [], [], []
        for r in kept:
            face_quality = (fds.parse_analysis(r.analysis_json).get('face') or {}).get('quality')
            if face_quality == 'red':
                face_red.append(r)
            elif face_quality == 'amber':
                face_amber.append(r)
            elif face_quality != 'green':
                # Legacy rows may have a face state/score but no face-region pixel
                # assessment.  That is still unchecked, never implicitly clean.
                face_unknown.append(r)
        flagged = {r.id: r for r in (
            technical_red + technical_amber + technical_unknown
            + face_red + face_amber + face_unknown)}
        quality_images = [
            {'id': r.id, 'filename': r.filename,
             'technical': r.training_usefulness,
             'face_quality': (fds.parse_analysis(r.analysis_json).get('face') or {}).get('quality')}
            for r in flagged.values()]
        if technical_red or face_red:
            warnings.append(
                f'{len({r.id for r in technical_red + face_red})} kept image(s) have red '
                'technical or face-region quality — reject them or verify at 100%.')
            _check('pixel_quality', 'Training pixels are clean', 'warn',
                   f'{len({r.id for r in technical_red + face_red})} red QA image(s)', 'gf-images')
        elif technical_amber or face_amber:
            _check('pixel_quality', 'Training pixels are clean', 'warn',
                   f'{len({r.id for r in technical_amber + face_amber})} amber QA image(s)', 'gf-images')
        elif technical_unknown or face_unknown:
            warnings.append(
                f'{len({r.id for r in technical_unknown + face_unknown})} kept image(s) '
                'have incomplete technical or face-region QA — refresh corpus analysis '
                'before training.')
            _check('pixel_quality', 'Training pixels are clean', 'warn',
                   f'{len({r.id for r in technical_unknown + face_unknown})} image(s) '
                   'not fully analysed', 'gf-images')
        else:
            _check('pixel_quality', 'Training pixels are clean', 'ok', 'no red/amber QA signal')

    if n and not concept:
        orange = cfg.get('face_scoring.orange')
        try:
            orange = float(orange)
        except (TypeError, ValueError):
            orange = 0.45
        unscored = [r for r in kept if not r.face_state]
        non_scorable = [r for r in kept if r.face_state and r.face_state != 'scorable']
        missing_score = [r for r in kept
                         if r.face_state == 'scorable' and r.face_score is None]
        low_identity = [r for r in kept if r.face_state == 'scorable'
                        and r.face_score is not None and r.face_score < orange]
        if unscored or non_scorable or missing_score or low_identity:
            warnings.append(
                f'identity QA needs review: {len(unscored)} unscored, '
                f'{len(non_scorable)} non-scorable, {len(missing_score)} missing a score, '
                f'{len(low_identity)} below the identity threshold.')
            _check('identity_quality', 'Identity verified', 'warn',
                   f'{len(unscored)} unscored · {len(non_scorable)} non-scorable · '
                   f'{len(missing_score)} missing score · '
                   f'{len(low_identity)} below {orange:.2f}', 'gf-images')
        else:
            _check('identity_quality', 'Identity verified', 'ok',
                   f'{n}/{n} accepted images checked')

    watermark_risk = [r for r in kept if r.watermark_state in ('detected', 'failed')]
    watermark_unscanned = [r for r in kept if r.watermark_state is None]
    if watermark_risk:
        warnings.append(f'{len(watermark_risk)} kept image(s) still have a detected or failed '
                        'watermark check — clean, crop, or reject them.')
        _check('watermarks', 'No unresolved watermarks', 'warn',
               f'{len(watermark_risk)} kept image(s) still flagged', 'gf-curation')
    elif watermark_unscanned:
        warnings.append(f'{len(watermark_unscanned)} kept image(s) have not been scanned '
                        'for overlaid watermarks.')
        _check('watermarks', 'No unresolved watermarks', 'warn',
               f'{len(watermark_unscanned)} image(s) not scanned', 'gf-curation')
    elif n:
        _check('watermarks', 'No unresolved watermarks', 'ok', '0 unresolved flag')

    enlarged = [r for r in kept if (r.upscale_ratio or 0) >= fds.UPSCALE_WARN_THRESHOLD]
    if enlarged:
        warnings.append(f'{len(enlarged)} kept image(s) were enlarged by at least '
                        f'{fds.UPSCALE_WARN_THRESHOLD:g}× during crop — inspect facial texture at 100%.')
        _check('native_resolution', 'Enough native detail', 'warn',
               f'{len(enlarged)} heavily enlarged crop(s)', 'gf-images')
    elif n:
        _check('native_resolution', 'Enough native detail', 'ok', 'no heavily enlarged crop')

    # Provenance sanity: one source/reconstruction pair may contribute one row,
    # and a mostly generated corpus should be an explicit decision, not an accident.
    by_id = {r.id: r for r in rows}
    improve_groups = {}
    for candidate in rows:
        if candidate.derivation_kind != fds.KLEIN_IMAGE_IMPROVE:
            continue
        source = by_id.get(candidate.parent_image_id)
        # An orphaned legacy reconstruction is an ordinary retained image so the
        # owner can reject/delete it; it is not an unresolvable exclusive pair.
        if source and source.dataset_id == candidate.dataset_id:
            improve_groups.setdefault(source.id, []).append(candidate)
    exclusive_pair_ids = set()
    both_kept = []
    unresolved_improvements = []
    for source_id, candidates in improve_groups.items():
        source = by_id[source_id]
        exclusive_pair_ids.add(source.id)
        exclusive_pair_ids.update(candidate.id for candidate in candidates)
        if source.status == 'keep' and any(c.status == 'keep' for c in candidates):
            both_kept.append(source_id)
        if fds._image_improvement_resolved_choice(source, candidates) is None:
            unresolved_improvements.append(source_id)
    if both_kept:
        blockers.append(f'{len(both_kept)} reconstruction pair(s) have both source and '
                        'candidate kept — resolve each pair before training.')
        _check('provenance_pairs', 'One version per reconstruction', 'fail',
               f'{len(both_kept)} pair(s) double-counted', 'gf-curation')
    elif unresolved_improvements:
        warnings.append(f'{len(unresolved_improvements)} reconstruction comparison(s) are '
                        'unresolved and excluded from training.')
        _check('provenance_pairs', 'One version per reconstruction', 'warn',
               f'{len(unresolved_improvements)} comparison(s) unresolved', 'gf-curation')
    elif improve_groups:
        _check('provenance_pairs', 'One version per reconstruction', 'ok',
               'every reconstruction has one admitted version')

    small_candidates = [r for r in rows if r.derivation_kind == fds.KLEIN_SMALL_IMAGE]
    unresolved_small = []
    for candidate in small_candidates:
        source = by_id.get(candidate.parent_image_id)
        if not source or source.derivation_kind != fds.SMALL_IMAGE_SOURCE:
            continue
        exclusive_pair_ids.update((source.id, candidate.id))
        resolved = ((source.status == 'keep' and candidate.status == 'reject')
                    or (source.status == 'reject' and candidate.status in ('keep', 'reject')))
        if not resolved:
            unresolved_small.append(candidate)
    if unresolved_small:
        warnings.append(f'{len(unresolved_small)} small-image rescue comparison(s) are '
                        'unresolved and excluded from training.')
        _check('rescue_pairs', 'Small-image rescues resolved', 'warn',
               f'{len(unresolved_small)} comparison(s) unresolved', 'gf-curation')
    elif small_candidates:
        _check('rescue_pairs', 'Small-image rescues resolved', 'ok',
               'every rescue has one admitted version')

    if n and not concept:
        synthetic = [r for r in kept if r.source == 'generated']
        real = [r for r in kept if r.source == 'import']
        share = len(synthetic) / n
        if not real:
            warnings.append('the accepted set contains no imported real photo — generated '
                            'images can reinforce one another’s artifacts and identity drift.')
            _check('source_mix', 'Real-photo foundation', 'warn',
                   '0 accepted imported photos', 'ds-add-import')
        elif share > 0.40:
            warnings.append(f'{len(synthetic)}/{n} kept images are generated or reconstructed '
                            f'({share:.0%}) — keep synthetic supplementation below the real-photo majority.')
            _check('source_mix', 'Real-photo foundation', 'warn',
                   f'{len(real)} real · {len(synthetic)} generated/reconstructed', 'gf-images')
        else:
            _check('source_mix', 'Real-photo foundation', 'ok',
                   f'{len(real)} real · {len(synthetic)} generated/reconstructed')

    if n:
        imported_kept = [r for r in kept if r.source == 'import']
        unknown_rights = [r for r in imported_kept
                          if (fds._safe_json(r.source_rights) or {}).get('basis', 'unknown')
                          == 'unknown']
        if unknown_rights:
            detail = f'{len(unknown_rights)}/{len(imported_kept)} imported image(s) have unknown rights'
            if coverage_profile == 'strict':
                blockers.append(detail + ' — record ownership, licence, public-domain basis, or consent.')
                _check('source_rights', 'Source rights recorded', 'fail', detail, 'ds-corpus-review')
            else:
                warnings.append(detail + ' — record the source basis before sharing or training.')
                _check('source_rights', 'Source rights recorded', 'warn', detail, 'ds-corpus-review')
        elif imported_kept:
            _check('source_rights', 'Source rights recorded', 'ok',
                   f'{len(imported_kept)}/{len(imported_kept)} imported images documented')

        mapped = [r for r in imported_kept if fds.parse_coverage(r.coverage_json)]
        low_confidence = []
        for row in mapped:
            evidence = fds._safe_json(row.coverage_provenance) or {}
            confidence = [float(value) for value in (evidence.get('confidence') or {}).values()
                          if isinstance(value, (int, float)) and not isinstance(value, bool)]
            if not evidence or (confidence and sum(confidence) / len(confidence) < 0.7):
                low_confidence.append(row)
        if low_confidence:
            _check('coverage_evidence', 'Coverage labels have evidence', 'warn',
                   f'{len(low_confidence)} mapped image(s) missing or below 0.70 confidence',
                   'ds-corpus-review')
        elif mapped:
            _check('coverage_evidence', 'Coverage labels have evidence', 'ok',
                   f'{len(mapped)} mapped image(s) carry provenance')

    # 11) images encore en attente de tri (elles ne s'entraînent PAS)
    untriaged = sum(1 for r in rows
                    if r.status == 'pending' and r.filename
                    and r.id not in exclusive_pair_ids)
    if untriaged:
        warnings.append(f'{untriaged} image(s) still await triage (✓/✕) — they will NOT '
                        'be part of the training.')
        _check('triage', 'Everything triaged', 'warn',
               f'{untriaged} image(s) still await ✓/✕ — they will NOT train', 'gf-images')
    elif rows:
        _check('triage', 'Everything triaged', 'ok', 'no image awaiting ✓/✕')

    # 7) VRAM (Krea 2 mesuré à 24 GB ; None = inconnu, jamais bloquant)
    try:
        from .. import capabilities
        vram = capabilities.gpu_vram_gb()
        if vram is not None and ttype in _VRAM24_FAMILIES and vram < _KREA_MIN_VRAM_GB:
            warnings.append(f'{label} training needs ~{_KREA_MIN_VRAM_GB} GB of VRAM at 1024 '
                            f'— this GPU reports {vram} GB; expect OOM or extreme slowness. '
                            'Drop the resolution to 768 in Advanced options to fit.')
            _check('vram', 'GPU memory', 'warn',
                   f'{label} needs ~{_KREA_MIN_VRAM_GB} GB VRAM — this GPU reports {vram} GB')
    except Exception:
        pass

    # Verdict agrégé pour la pastille : un fail = 🔴, sinon un warn = 🟡, sinon 🟢.
    statuses = {c['status'] for c in checks}
    verdict = ('blocked' if 'fail' in statuses
               else 'warnings' if 'warn' in statuses else 'ready')

    return {'blockers': blockers, 'warnings': warnings,
            # Détail « lesquelles » pour l'UI : images dont la caption fuit, et paires
            # quasi-doublons — le message reste agrégé, mais on peut drill-down + agir.
            'leak_images': leak_images, 'dup_pairs': dup_pairs,
            'quality_images': quality_images,
            'checks': checks, 'verdict': verdict,
            'kept': n, 'floor': floor, 'recommended': reco}


# --- Garde-fou espace disque ---------------------------------------------------
# Un run plein (10 checkpoints ~0,3-2 Go + latents/samples) et une conversion
# diffusers (~12 Go) qui crashent à 90 % pour cause de disque plein laissent des
# artefacts corrompus. On refuse AVANT, avec un message actionnable.
MIN_FREE_GB_TRAIN = 10
MIN_FREE_GB_CONVERT = 15


from .lora_training_process import (  # noqa: E402
    _log_tail,
    _launch_training,
    _terminate_training_process,
    _watch_training,
    archive_previous_run,
    assert_free_disk,
    continue_training,
    free_disk_gb,
    launch_training,
    stop_training,
)




def _dataset_name(dataset_id):
    if dataset_id is None:
        return None
    ds = fds.db.session.get(FaceDataset, int(dataset_id))
    return ds.name if ds else f'#{dataset_id}'


def kept_uncaptioned_count(dataset_id) -> int:
    """Nombre d'images GARDÉES (status keep) sans caption - bloque l'entraînement."""
    return (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id, status='keep')
            .filter((FaceDatasetImage.caption.is_(None))
                    | (fds.db.func.trim(FaceDatasetImage.caption) == ''))
            .count())


def assert_trainable(dataset_id, train_type=None, allow_caption_mismatch=False,
                     allow_uncaptioned=False, check_captions=True) -> dict:
    """Lève ValueError si le dataset n'est pas prêt : trop peu d'images gardées,
    captions manquantes, ou STYLE de caption incohérent avec le type de modèle
    (SDXL booru-native attend des tags booru ; Z-Image attend de la prose). Le
    `train_type` effectif est passé par l'appelant car il n'est persisté qu'APRÈS
    cet appel. `allow_caption_mismatch=True` = override explicite (bouton « forcer »).
    `allow_uncaptioned=True` = confirm explicite « train anyway » : les captions
    manquantes ne sont plus un mur, juste un « êtes-vous sûr ? » (demande
    utilisateur — pouvoir expérimenter), le préfixe UNCAPTIONED: déclenche le
    confirm côté front comme MISMATCH_CAPTION:."""
    ds_ = fds.db.session.get(FaceDataset, dataset_id)
    if ds_ is None or ds_.trashed_at is not None:
        raise ValueError('dataset not found')
    report = training_preflight(str(ds_.user_id), dataset_id, train_type=train_type)
    if report['blockers']:
        raise ValueError('PREFLIGHT_BLOCKED: ' + ' | '.join(report['blockers']))
    if not check_captions:
        return report
    # STYLE : les captions sont OPTIONNELLES (le rendu se lie au LoRA, pas aux mots ;
    # dropout à 30 % de toute façon) → on ne bloque PAS sur les captions manquantes.
    # Mais si des captions EXISTENT, le garde prose↔booru plus bas reste pertinent
    # (un style SDXL captionné en prose = même mismatch qu'un character).
    style = fds.is_style(ds_)
    missing = kept_uncaptioned_count(dataset_id)
    if missing and not style and not allow_uncaptioned:
        raise ValueError(
            f"UNCAPTIONED: {missing} kept image(s) have no caption. Captions are "
            "strongly recommended — whatever a caption does NOT explain binds to "
            "the trigger — but you can train without them.")
    if allow_caption_mismatch:
        return report
    # Garde-fou style ↔ type : un LoRA SDXL entraîné sur des captions PROSE = mismatch
    # booru-native → « images disjointes » (recherche 2026-06-14) ; et l'inverse pour Z-Image.
    ttype = (train_type or '').strip().lower()
    if not ttype:
        ds = fds.db.session.get(FaceDataset, dataset_id)
        ttype = (getattr(ds, 'train_type', None) or 'zimage').lower() if ds else 'zimage'
    expected = 'booru' if ttype == 'sdxl' else 'prose'
    from .face_variations import caption_style
    caps = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id, status='keep')
            .filter(FaceDatasetImage.caption.isnot(None)).all())
    sample = [c.caption for c in caps if c.caption and c.caption.strip()][:12]
    if sample:
        booru_n = sum(1 for s in sample if caption_style(s) == 'booru')
        actual = 'booru' if booru_n * 2 >= len(sample) else 'prose'   # vote majoritaire
        if actual != expected:
            if expected == 'booru':
                raise ValueError(
                    "MISMATCH_CAPTION: this SDXL dataset has PROSE captions, but a booru "
                    "model (bigLove type) is prompted with tags. Re-caption in 'Booru tags' mode "
                    "before training, or force the training.")
            raise ValueError(
                "MISMATCH_CAPTION: this Z-Image dataset has booru TAG captions, but Z-Image "
                "expects prose. Re-caption in 'Prose' mode, or force the training.")
    return report


def training_status(user_id=None) -> dict:
    cur_id = queue_manager._get_system_state('training_dataset_id', None)
    in_progress = bool(queue_manager._get_system_state('training_in_progress', False))
    training_error = queue_manager._get_system_state('training_error', None)
    queue_error = queue_manager._get_system_state('training_queue_error', None)
    return {'in_progress': in_progress,
            'installed': is_installed(),
            'pid': queue_manager._get_system_state('training_pid', None),
            'current': ({'dataset_id': cur_id, 'name': _dataset_name(cur_id),
                         'train_type': queue_manager._get_system_state('training_train_type', None),
                         'base_model': queue_manager._get_system_state('training_base_model', None)}
                        if (in_progress and cur_id is not None) else None),
            # Dernier crash d'entraînement (rc≠0) remonté par le watcher, pour l'UI.
            'error': training_error or queue_error,
            'queue_error': queue_error,
            'queue': train_queue_view(user_id) if user_id is not None else []}


# --- Suivi de progression (log tail + loss curve + samples) -------------------
# ai-toolkit redirige tqdm dans training.log : les mises à jour sont séparées par
# des \r sur une même « ligne », d'où le split sur [\r\n]. Un segment type :
#   lora_x:   2%|▏| 60/3000 [01:23<1:07:41, 1.38s/it, lr: 1.0e+00 loss: 3.412e-01]
_PROG_STEP_RE = re.compile(r'(\d+)/(\d+)')
_PROG_LOSS_RE = re.compile(r'loss[:=]\s*([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)')
_PROG_SPEED_RE = re.compile(r'([\d.]+\s*(?:s/it|it/s))')
_PROG_ETA_RE = re.compile(r'<\s*([\d:]+)\s*,')
_SAMPLE_RE = re.compile(r'__(\d+)_(\d+)\.(?:jpg|jpeg|png|webp)$', re.IGNORECASE)
_PROG_LOG_MAX_BYTES = 4 * 1024 * 1024   # tail cap: 3000 tqdm updates ≈ 0.5 MB
_PROG_CURVE_MAX_POINTS = 200
_PROG_SAMPLES_MAX = 24


def _parse_training_log(text: str) -> dict:
    """Extract (step, total, loss, speed, eta, loss_curve) from raw log text.
    Pure function — unit-testable without a real run."""
    out = {'step': None, 'total': None, 'loss': None, 'speed': None, 'eta': None,
           'loss_curve': []}
    curve = []
    for seg in re.split(r'[\r\n]+', text):
        lm = _PROG_LOSS_RE.search(seg)
        # Only trust real tqdm segments ('%|' bar or a loss postfix) — the log also
        # contains incidental 'X/Y' text (dataset counts, resolutions) that must not
        # be read as progress.
        if '%|' not in seg and not lm:
            continue
        sm = None
        for sm in _PROG_STEP_RE.finditer(seg):
            pass                             # last step/total occurrence of the segment
        if not sm:
            continue
        step, total = int(sm.group(1)), int(sm.group(2))
        if total <= 0 or step > total:
            continue                         # e.g. '1024x1024' image sizes, not progress
        out['step'], out['total'] = step, total
        if lm:
            try:
                loss = float(lm.group(1))
            except ValueError:
                continue
            out['loss'] = loss
            if not curve or curve[-1][0] != step:
                curve.append([step, loss])
        spm = _PROG_SPEED_RE.search(seg)
        if spm:
            out['speed'] = spm.group(1).strip()
        em = _PROG_ETA_RE.search(seg)
        if em:
            out['eta'] = em.group(1)
    # Downsample evenly so the payload stays small on long runs.
    if len(curve) > _PROG_CURVE_MAX_POINTS:
        stride = len(curve) / _PROG_CURVE_MAX_POINTS
        curve = [curve[int(i * stride)] for i in range(_PROG_CURVE_MAX_POINTS - 1)] + [curve[-1]]
    out['loss_curve'] = curve
    return out


def _samples_dir(user_id, dataset_id, base_model=_PERSISTED, family=None) -> str:
    return os.path.join(_run_dir(user_id, dataset_id, base_model, family), 'samples')


def _list_training_samples_dir(directory, limit=_PROG_SAMPLES_MAX) -> list[dict]:
    if not os.path.isdir(directory):
        return []
    out = []
    for filename in os.listdir(directory):
        match = _SAMPLE_RE.search(filename)
        if match:
            out.append({'filename': filename, 'step': int(match.group(1)),
                        'prompt_idx': int(match.group(2))})
    out.sort(key=lambda sample: (-sample['step'], sample['prompt_idx']))
    return out if limit is None else out[:limit]


def list_training_samples(user_id, dataset_id, base_model=_PERSISTED, family=None,
                          limit=_PROG_SAMPLES_MAX) -> list[dict]:
    """Sample previews ai-toolkit writes every sample_every steps
    (<run>/samples/<ts>__<step>_<promptidx>.jpg). Newest steps first, capped
    (limit=None → all, for the best-epoch scoring pass)."""
    return _list_training_samples_dir(
        _samples_dir(user_id, dataset_id, base_model, family), limit=limit)


def score_checkpoint_samples(user_id, dataset_id, base_model=_PERSISTED, family=None) -> dict:
    """Best-epoch selection (jandordoe method): every training sample is an output
    of the LoRA at its step — scoring their face similarity vs the dataset
    reference (insightface, CPU, one subprocess for the whole set) tells which
    step holds the identity best. The recommended checkpoint is the saved one
    closest to that step.

    Returns {'available': bool, 'reason'?: str, 'steps': [{'step','mean_sim','n'}],
    'best_step': int|None, 'checkpoint': str|None} — never raises on missing
    prerequisites, the UI shows `reason` instead."""
    from . import face_similarity
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if not ds.ref_filename:
        return {'available': False, 'reason': 'this dataset has no reference photo'}
    ref_path = os.path.join(fds._dataset_dir(ds.id), ds.ref_filename)
    if not face_similarity.is_available():
        return {'available': False,
                'reason': 'face scoring is not installed (Quality tools step in Setup)'}
    samples = list_training_samples(user_id, dataset_id, base_model, family, limit=None)
    if not samples:
        return {'available': False, 'reason': 'no training samples yet (they appear every 250 steps)'}
    sdir = _samples_dir(user_id, dataset_id, base_model, family)
    paths = [os.path.join(sdir, s['filename']) for s in samples]
    results, scoring_error = face_similarity.score_dataset_faces(ref_path, paths)
    if not results:
        detail = (scoring_error or {}).get('detail')
        return {'available': False,
                'reason': f'face scoring failed: {detail}' if detail
                else 'face scoring failed (see server log)'}
    by_step = {}
    for s, p in zip(samples, paths):
        r = results.get(p)
        if r and r.get('state') == 'scorable' and r.get('sim') is not None:
            by_step.setdefault(s['step'], []).append(float(r['sim']))
    steps = [{'step': st, 'mean_sim': round(sum(v) / len(v), 4), 'n': len(v)}
             for st, v in sorted(by_step.items())]
    if not steps:
        return {'available': False, 'reason': 'no scorable face in the samples'}
    best = max(steps, key=lambda s: s['mean_sim'])
    # Map the winning sample step to the CLOSEST saved checkpoint (samples every
    # 250 steps, checkpoints every 500 — they rarely align exactly).
    cks = list_checkpoints(user_id, dataset_id, base_model, family)
    ck = min(cks, key=lambda c: abs(c['step'] - best['step']))['filename'] if cks else None
    return {'available': True, 'steps': steps, 'best_step': best['step'], 'checkpoint': ck}


def training_progress(user_id, dataset_id, base_model=_PERSISTED, family=None) -> dict:
    """Live view of a run: parsed log progress + sample listing. Never raises on a
    missing/unreadable log (a run that hasn't started writing yet is normal) —
    only on an unknown dataset (route → 404 via get_dataset)."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    cur_id = queue_manager._get_system_state('training_dataset_id', None)
    active = (bool(queue_manager._get_system_state('training_in_progress', False))
              and cur_id is not None and int(cur_id) == int(dataset_id)
              and _owned_training_process_alive(
                  queue_manager._get_system_state('training_pid', None)))
    if active:
        log_path = queue_manager._get_system_state('training_log_path', None)
        checkpoint_dir = queue_manager._get_system_state(
            'training_checkpoint_dir', None)
    else:
        log_path = None
        checkpoint_dir = None
    if not log_path:
        log_path = os.path.join(
            str(_output_dir() / _run_name(ds, base_model, family)), 'training.log')
    parsed = {'step': None, 'total': None, 'loss': None, 'speed': None, 'eta': None,
              'loss_curve': []}
    log_exists = os.path.isfile(log_path)
    if log_exists:
        try:
            size = os.path.getsize(log_path)
            with open(log_path, encoding='utf-8', errors='replace') as fh:
                if size > _PROG_LOG_MAX_BYTES:
                    fh.seek(size - _PROG_LOG_MAX_BYTES)
                parsed = _parse_training_log(fh.read())
        except OSError:
            log_exists = False
    samples = (_list_training_samples_dir(
        os.path.join(checkpoint_dir, 'samples'))
        if checkpoint_dir else
        list_training_samples(user_id, dataset_id, base_model, family))
    return {'active': active, 'log_exists': log_exists, **parsed,
            'masks_skipped': bool(active and queue_manager._get_system_state('training_masks_skipped', False)),
            'samples': samples}


from .lora_training_queue import (  # noqa: E402  (imports completed launch API)
    TRAIN_QUEUE_KEY,
    _advance_training_queue,
    _compensate_unstarted_launch,
    _due_index,
    _launch_queued_item,
    _owned_training_process_alive,
    _pid_alive,
    _process_identity,
    _snapshot_final_checkpoint,
    _save_queue,
    dequeue_training,
    enqueue_training,
    get_train_queue,
    process_training_queue,
    start_training_scheduler,
    stop_training_scheduler,
    train_queue_view,
)

# Public compatibility surface: routes and integrations continue importing the
# queue API from this module, while its implementation is owned by
# ``lora_training_queue``.
__all__ = (
    'TRAIN_QUEUE_KEY', '_advance_training_queue',
    '_compensate_unstarted_launch', '_due_index', '_launch_queued_item',
    '_owned_training_process_alive', '_pid_alive', '_process_identity',
    '_save_queue', '_snapshot_final_checkpoint', 'dequeue_training',
    'enqueue_training', 'get_train_queue', 'process_training_queue',
    'start_training_scheduler', 'stop_training_scheduler', 'train_queue_view',
    'delete_imported_checkpoint', 'import_checkpoint', 'list_checkpoints',
    'list_imported_checkpoints', 'open_training_folder',
    '_default_sample_prompts', '_ema_eff', '_inject_trigger', '_lora_alpha',
    '_lora_alpha_eff', '_network_type_eff',
    '_resolved_default_sample_prompts',
    '_DEFAULT_SAMPLE_PROMPTS_CHARACTER', '_DEFAULT_SAMPLE_PROMPTS_CONCEPT',
    '_DEFAULT_SAMPLE_PROMPTS_STYLE',
    '_STYLE_CAPTION_DROPOUT', '_sha256_file',
    'cleanup_abandoned_local_training_staging',
    'export_dataset_to_aitoolkit',
    'generate_person_masks', '_ema_fields', '_grad_accum', '_lora_rank',
    '_lr_eff', '_lr_sched_fields', '_max_step_saves', '_network_block',
    '_optimizer_eff', '_sample_every', '_sample_prompts', '_save_every',
    '_timestep_type_eff', '_train_res', '_apply_style_overrides',
    '_build_job_config_flux', '_build_job_config_flux2klein',
    '_build_job_config_krea', '_build_job_config_sdxl', 'build_job_config',
    'launch_settings_snapshot', '_mask_fields', '_masks_dir',
    '_materialize_local_training_dataset', 'export_registry_manifest',
    '_log_tail', '_launch_training', '_terminate_training_process',
    '_watch_training', 'archive_previous_run', 'assert_free_disk',
    'continue_training', 'free_disk_gb', 'launch_training', 'stop_training',
    'subprocess',
    '_EXPORTED_MANIFEST',
)
