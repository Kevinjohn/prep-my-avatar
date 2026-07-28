"""Family-specific ai-toolkit job configuration assembly."""
from __future__ import annotations

from . import face_dataset_service as fds
from .lora_training import (
    _STYLE_CAPTION_DROPOUT, _ema_fields, _flux2klein_is_9b,
    _grad_accum, _is_custom_weights, _krea_is_raw, _lora_rank,
    _lr_eff, _lr_sched_fields, _mask_fields, _network_block,
    _optimizer_eff, _output_dir, _run_name, _safe_trigger, _sample_every,
    _sample_prompts, _save_every, _max_step_saves, _timestep_type_eff,
    _sdxl_base_path, _train_res, _train_type,
)

def _apply_style_overrides(ds, process: dict) -> dict:
    """Mute la config d'UN process ai-toolkit pour un dataset style. No-op sinon."""
    if not fds.is_style(ds):
        return process
    process.pop('trigger_word', None)
    for d in process.get('datasets', ()):
        d['caption_dropout_rate'] = _STYLE_CAPTION_DROPOUT
    # timestep_type 'sigmoid' est la reco LoRA de SUJET (cf commentaire zimage) ;
    # pour un style on retombe sur le défaut ai-toolkit de la famille.
    if process.get('train', {}).get('timestep_type') == 'sigmoid':
        process['train'].pop('timestep_type')
    return process


def build_job_config(ds, dataset_folder: str, steps: int = 3000, training_folder=None) -> dict:
    """Job-config ai-toolkit pour le preset officiel `zimage:turbo`
    (« Z-Image Turbo w/ Training Adapter »). Clés alignées sur ce que génère
    l'UI ai-toolkit (ui/src/app/jobs/new/options.ts) + structure LoRA 24 Go de
    référence - vérifiées au runtime contre la version installée (cf. spec §3).
    Points non négociables : arch='zimage', name_or_path='Tongyi-MAI/Z-Image-Turbo',
    assistant_lora_path = l'adapter de training (retiré à l'inférence),
    quantize qfloat8 + low_vram pour tenir sur 24 Go.

    SDXL (train_type='sdxl') part dans une branche dédiée (_build_job_config_sdxl) -
    le chemin zimage ci-dessous reste strictement inchangé.

    `training_folder` (cloud seam) : utilisé TEL QUEL comme process.training_folder
    dans les 3 familles - aucun appel à _output_dir() (pas d'ai-toolkit local requis).
    Défaut (None) = comportement historique inchangé (_output_dir() / _run_name(ds))."""
    if _train_type(ds) == 'sdxl':
        cfg_ = _build_job_config_sdxl(ds, dataset_folder, steps, training_folder=training_folder)
        _apply_style_overrides(ds, cfg_['config']['process'][0])
        return cfg_
    if _train_type(ds) == 'krea':
        cfg_ = _build_job_config_krea(ds, dataset_folder, steps, training_folder=training_folder)
        _apply_style_overrides(ds, cfg_['config']['process'][0])
        return cfg_
    if _train_type(ds) == 'flux':
        cfg_ = _build_job_config_flux(ds, dataset_folder, steps, training_folder=training_folder)
        _apply_style_overrides(ds, cfg_['config']['process'][0])
        return cfg_
    if _train_type(ds) == 'flux2klein':
        cfg_ = _build_job_config_flux2klein(ds, dataset_folder, steps, training_folder=training_folder)
        _apply_style_overrides(ds, cfg_['config']['process'][0])
        return cfg_
    trigger = _safe_trigger(ds)
    base_model = getattr(ds, 'train_base_model', None)
    variant = (getattr(ds, 'train_variant', None) or 'turbo').lower()

    # Base : officielle (repo HF diffusers) OU merge ComfyUI converti en diffusers.
    model = {'arch': 'zimage', 'quantize': True, 'quantize_te': True,
             'low_vram': True, 'qtype': 'qfloat8'}
    if base_model:
        from .zimage_convert import converted_dir
        model['name_or_path'] = converted_dir(base_model)       # dossier diffusers converti
        model['extras_name_or_path'] = 'Tongyi-MAI/Z-Image-Turbo'  # tokenizer/TE/VAE partagés
    else:
        model['name_or_path'] = 'Tongyi-MAI/Z-Image-Turbo'
    # Adapter de dé-distillation : UNIQUEMENT pour la variante Turbo (distillée).
    # Base / De-Turbo sont déjà non distillés → pas d'adapter (chargé à -1.0 sinon).
    if variant == 'turbo':
        model['assistant_lora_path'] = ('ostris/zimage_turbo_training_adapter/'
                                        'zimage_turbo_training_adapter_v2.safetensors')
    # Previews : Turbo = 8 steps / cfg 1 ; non-distillé = plus de steps + CFG réel.
    sample_steps, guidance = (8, 1) if variant == 'turbo' else (25, 4)
    _zrank = _lora_rank(ds, 'zimage')   # défaut 16 (choix user) ; éditable via train_settings

    cfg_ = {
        'job': 'extension',
        'config': {
            'name': f'lora_{trigger}',
            'process': [{
                'type': 'sd_trainer',
                'training_folder': (training_folder if training_folder
                                    else str(_output_dir() / _run_name(ds))),
                'device': 'cuda:0',
                'trigger_word': trigger,
                'network': _network_block(ds, _zrank, 'zimage'),
                'save': {'dtype': 'float16', 'save_every': _save_every(ds),
                         'max_step_saves_to_keep': _max_step_saves(ds)},
                'datasets': [{
                    'folder_path': dataset_folder,
                    'caption_ext': 'txt',
                    # 5% de dropout caption : le modèle voit parfois le trigger seul,
                    # ce qui renforce l'association trigger→identité (reco LoRA de
                    # sujet ; l'identité doit vivre dans le trigger, pas les mots).
                    'caption_dropout_rate': 0.05,
                    'cache_latents_to_disk': True,
                    'resolution': _train_res(ds),
                    **_mask_fields(dataset_folder),
                }],
                'train': {
                    'batch_size': 1,
                    'steps': steps,
                    'gradient_accumulation': _grad_accum(ds),
                    'train_unet': True,
                    'train_text_encoder': False,
                    'gradient_checkpointing': True,
                    'noise_scheduler': 'flowmatch',
                    # 'sigmoid' = reco runbook pour un LoRA de sujet (l'exemple
                    # ai-toolkit confirme : "for just subject, change to sigmoid").
                    'timestep_type': _timestep_type_eff(ds, 'sigmoid'),
                    'optimizer': _optimizer_eff(ds),
                    'lr': _lr_eff(ds),
                    'dtype': 'bf16',
                    **_lr_sched_fields(ds),
                    **_ema_fields(ds),
                },
                'model': model,
                'sample': {
                    'sampler': 'flowmatch',
                    'neg': '',   # cohérence avec SDXL : défaut ai-toolkit = False (booléen) → fragile
                    'sample_every': _sample_every(ds),
                    'guidance_scale': guidance,
                    'sample_steps': sample_steps,
                    'prompts': _sample_prompts(ds, trigger),
                },
            }],
        },
    }
    _apply_style_overrides(ds, cfg_['config']['process'][0])
    return cfg_


def _build_job_config_krea(ds, dataset_folder: str, steps: int, training_folder=None) -> dict:
    """Job-config ai-toolkit pour Krea 2. Deux bases selon `train_variant` (cf.
    _krea_is_raw), toutes deux arch='krea2', alignées sur l'UI ai-toolkit
    (ui/src/app/jobs/new/options.ts) :

    - RAW (défaut, reco officielle « train on Raw, validate on Turbo ») :
      name_or_path='krea/Krea-2-Raw' (non distillé), AUCUN assistant_lora_path (rien
      à dé-distiller), previews en CFG 4 / 25 steps (le Raw a besoin d'un vrai CFG).
      1er run = download des poids Raw (~24 Go) et run > 4 h → d'où _TRAIN_STATE_TTL 12 h.
    - TURBO (opt-in, VRAM-friendly) : name_or_path='krea/Krea-2-Turbo' + l'adapter de
      training Ostris (retiré à l'inférence, comme Z-Image), previews CFG 1 / 8 steps.

    Commun : quantize qfloat8 + low_vram pour tenir sur 24 Go. ⚠️ Requiert ai-toolkit
    À JOUR (commit « Add support for Krea2 », arch 'krea2') sinon l'arch est inconnue
    (garde _aitoolkit_supports_krea). Réseau = 'lora' : VÉRIFIÉ canonique 2026-06-26.
    Résolution KREA_TRAIN_RESOLUTION (1024, TE déchargé) car 768 seul tenait sinon."""
    trigger = _safe_trigger(ds)
    is_raw = _krea_is_raw(ds)
    _krank = _lora_rank(ds, 'krea')   # défaut 32/32 (recherche) ; éditable via train_settings
    # Custom weights (local-only, same krea2 arch) override name_or_path; the TE/VAE
    # stay official (Krea bundles them). The variant still drives the adapter/CFG.
    _kbase = getattr(ds, 'train_base_model', None)
    model = {
        'arch': 'krea2',
        'name_or_path': (_kbase if _is_custom_weights(_kbase)
                         else ('krea/Krea-2-Raw' if is_raw else 'krea/Krea-2-Turbo')),
        'quantize': True, 'quantize_te': True, 'low_vram': True, 'qtype': 'qfloat8',
    }
    # Adapter de dé-distillation : Turbo UNIQUEMENT (le Raw est déjà non distillé →
    # rien à retirer ; le charger dessus dégraderait le training).
    if not is_raw:
        model['assistant_lora_path'] = ('ostris/krea2_turbo_training_adapter/'
                                        'krea2_turbo_training_adapter_v1.safetensors')
    return {
        'job': 'extension',
        'config': {
            'name': f'lora_{trigger}',
            'process': [{
                'type': 'sd_trainer',
                'training_folder': (training_folder if training_folder
                                    else str(_output_dir() / _run_name(ds))),
                'device': 'cuda:0',
                'trigger_word': trigger,
                'network': _network_block(ds, _krank, 'krea'),
                'save': {'dtype': 'float16', 'save_every': _save_every(ds),
                         'max_step_saves_to_keep': _max_step_saves(ds)},
                'datasets': [{
                    'folder_path': dataset_folder,
                    'caption_ext': 'txt',
                    'caption_dropout_rate': 0.05,
                    'cache_latents_to_disk': True,
                    # Pré-cache les embeddings du Qwen3-VL pour pouvoir le DÉCHARGER pendant le
                    # training (cf. unload_text_encoder) → libère ~4-8 Go → 1024 tient sans offload.
                    # Valide ici car train_text_encoder=False (sorties figées → cachables sans perte).
                    'cache_text_embeddings': True,
                    'resolution': _train_res(ds),
                    **_mask_fields(dataset_folder),
                }],
                'train': {
                    'batch_size': 1,
                    'steps': steps,
                    'gradient_accumulation': _grad_accum(ds),
                    'train_unet': True,
                    'train_text_encoder': False,
                    'unload_text_encoder': True,  # décharge le Qwen3-VL après caching → VRAM pour le DiT 12B → 1024 rapide
                    'gradient_checkpointing': True,
                    'noise_scheduler': 'flowmatch',
                    'timestep_type': _timestep_type_eff(ds, 'linear'),  # défaut canonique krea2 (options.ts)
                    'optimizer': _optimizer_eff(ds),
                    'lr': _lr_eff(ds),
                    'dtype': 'bf16',
                    **_lr_sched_fields(ds),
                    **_ema_fields(ds),
                },
                'model': model,
                'sample': {
                    'sampler': 'flowmatch',
                    'neg': '',
                    'sample_every': _sample_every(ds),
                    # Turbo (distillé) : cfg 1 / 8 steps ; Raw (non distillé) : cfg 4 / 25 steps.
                    'guidance_scale': 4 if is_raw else 1,
                    'sample_steps': 25 if is_raw else 8,
                    'prompts': _sample_prompts(ds, trigger),
                },
            }],
        },
    }


def _build_job_config_flux(ds, dataset_folder: str, steps: int, training_folder=None) -> dict:
    """Job-config ai-toolkit pour FLUX.1-dev (arch='flux'). Valeurs VÉRIFIÉES contre
    l'ai-toolkit installé : `ui/.../options.ts` (entrée 'flux' : name_or_path
    'black-forest-labs/FLUX.1-dev', quantize + quantize_te True, sampler /
    noise_scheduler 'flowmatch') ET le notebook officiel `FLUX_1_dev_LoRA_Training`
    (linear/alpha 16, lr 1e-4, previews guidance 4 / 20 steps).

    arch='flux' est une arch CŒUR d'ai-toolkit (toolkit/config_modules.py) — supportée
    par tout ai-toolkit, donc AUCUNE garde de version (contrairement à krea2, extension).
    FLUX.1-dev est un modèle GATED sur Hugging Face : le 1er run télécharge ~24 Go et
    exige un HF_TOKEN ayant accepté la licence (même mécanique que Krea, aussi gated).

    VRAM : Flux est un DiT 12B (même classe que Krea 2). On ajoute low_vram + qfloat8
    (comme Krea, dont la mesure LDS a montré la nécessité à 24 Go) au-dessus des defaults
    options.ts — curseur basse-VRAM = la résolution 768 (cf. _train_res / KREA_TRAIN)."""
    trigger = _safe_trigger(ds)
    _frank = _lora_rank(ds, 'flux')   # défaut 16 (exemple flux officiel) ; éditable via train_settings
    # Custom weights (local-only, same flux arch) override name_or_path; TE/VAE stay
    # official (ai-toolkit's flux loader resolves them from the official repo).
    _fbase = getattr(ds, 'train_base_model', None)
    model = {
        'arch': 'flux',
        'name_or_path': (_fbase if _is_custom_weights(_fbase)
                         else 'black-forest-labs/FLUX.1-dev'),
        'quantize': True, 'quantize_te': True, 'low_vram': True, 'qtype': 'qfloat8',
    }
    return {
        'job': 'extension',
        'config': {
            'name': f'lora_{trigger}',
            'process': [{
                'type': 'sd_trainer',
                'training_folder': (training_folder if training_folder
                                    else str(_output_dir() / _run_name(ds))),
                'device': 'cuda:0',
                'trigger_word': trigger,
                'network': _network_block(ds, _frank, 'flux'),
                'save': {'dtype': 'float16', 'save_every': _save_every(ds),
                         'max_step_saves_to_keep': _max_step_saves(ds)},
                'datasets': [{
                    'folder_path': dataset_folder,
                    'caption_ext': 'txt',
                    'caption_dropout_rate': 0.05,
                    'cache_latents_to_disk': True,
                    'resolution': _train_res(ds),
                    **_mask_fields(dataset_folder),
                }],
                'train': {
                    'batch_size': 1,
                    'steps': steps,
                    'gradient_accumulation': _grad_accum(ds),
                    'train_unet': True,
                    'train_text_encoder': False,
                    'gradient_checkpointing': True,
                    'noise_scheduler': 'flowmatch',
                    # 'sigmoid' = reco LoRA de SUJET pour les modèles flowmatch (l'exemple
                    # flux d'ai-toolkit documente ce choix ; identique à Z-Image).
                    'timestep_type': _timestep_type_eff(ds, 'sigmoid'),
                    'optimizer': _optimizer_eff(ds),
                    'lr': _lr_eff(ds),
                    'dtype': 'bf16',
                    **_lr_sched_fields(ds),
                    **_ema_fields(ds),
                },
                'model': model,
                'sample': {
                    'sampler': 'flowmatch',
                    'neg': '',
                    'sample_every': _sample_every(ds),
                    'guidance_scale': 4,   # FLUX.1-dev : guidance ~4 (notebook officiel)
                    'sample_steps': 20,
                    'prompts': _sample_prompts(ds, trigger),
                },
            }],
        },
    }


def _build_job_config_flux2klein(ds, dataset_folder: str, steps: int, training_folder=None) -> dict:
    """Job-config ai-toolkit pour FLUX.2 Klein. Deux tailles selon `train_variant`
    (cf. _flux2klein_is_9b) : arch='flux2_klein_4b' (défaut, voie locale 16-24 Go)
    ou 'flux2_klein_9b' (32-48 Go, voie cloud surtout). Valeurs VÉRIFIÉES contre
    l'ai-toolkit installé : `ui/.../options.ts` (entrées flux2_klein_4b/9b) et
    `extensions_built_in/diffusion_models/flux2/flux2_klein_model.py`.

    Divergences vs le chemin flux (options.ts fait foi) :
    - timestep_type 'weighted' — le défaut canonique des deux entrées Klein
      (PAS 'sigmoid' comme flux/zimage) ;
    - model_kwargs {'match_target_res': False} — clé propre à cette arch,
      absente du chemin flux ;
    - base NON distillée (flux2_is_guidance_distilled=False côté ai-toolkit) →
      les previews utilisent un VRAI CFG : guidance 4 / 25 steps (les défauts
      « non distillé » de l'UI ai-toolkit — même duo que Krea Raw), là où
      FLUX.1-dev (guidance-distillé) sample en guidance 4 / 20 steps.

    Les deux name_or_path sont des modèles GATED sur Hugging Face : accepter la
    licence + HF_TOKEN avant le 1er run, même mécanique que FLUX.1-dev et Krea.
    ⚠️ Contrairement à 'flux' (arch CŒUR), flux2_klein_* sont des EXTENSIONS →
    garde de version obligatoire (_aitoolkit_supports_flux2klein) sinon
    get_model_class retombe en silence sur le loader SD legacy (LoRA corrompu).
    quantize/low_vram/qfloat8 comme les autres familles ; curseur basse-VRAM =
    la résolution 768 (cf. _train_res)."""
    trigger = _safe_trigger(ds)
    is_9b = _flux2klein_is_9b(ds)
    _fkrank = _lora_rank(ds, 'flux2klein')   # défaut 16 ; éditable via train_settings
    # Custom weights (local-only, same flux2_klein arch) override name_or_path; the
    # TE (Mistral, hardcoded MISTRAL_PATH in ai-toolkit) and VAE stay official.
    _fkbase = getattr(ds, 'train_base_model', None)
    model = {
        'arch': 'flux2_klein_9b' if is_9b else 'flux2_klein_4b',
        'name_or_path': (_fkbase if _is_custom_weights(_fkbase)
                         else ('black-forest-labs/FLUX.2-klein-base-9B' if is_9b
                               else 'black-forest-labs/FLUX.2-klein-base-4B')),
        'quantize': True, 'quantize_te': True, 'low_vram': True, 'qtype': 'qfloat8',
        'model_kwargs': {'match_target_res': False},
    }
    return {
        'job': 'extension',
        'config': {
            'name': f'lora_{trigger}',
            'process': [{
                'type': 'sd_trainer',
                'training_folder': (training_folder if training_folder
                                    else str(_output_dir() / _run_name(ds))),
                'device': 'cuda:0',
                'trigger_word': trigger,
                'network': _network_block(ds, _fkrank, 'flux2klein'),
                'save': {'dtype': 'float16', 'save_every': _save_every(ds),
                         'max_step_saves_to_keep': _max_step_saves(ds)},
                'datasets': [{
                    'folder_path': dataset_folder,
                    'caption_ext': 'txt',
                    'caption_dropout_rate': 0.05,
                    'cache_latents_to_disk': True,
                    'resolution': _train_res(ds),
                    **_mask_fields(dataset_folder),
                }],
                'train': {
                    'batch_size': 1,
                    'steps': steps,
                    'gradient_accumulation': _grad_accum(ds),
                    'train_unet': True,
                    'train_text_encoder': False,
                    'gradient_checkpointing': True,
                    'noise_scheduler': 'flowmatch',
                    'timestep_type': _timestep_type_eff(ds, 'weighted'),
                    'optimizer': _optimizer_eff(ds),
                    'lr': _lr_eff(ds),
                    'dtype': 'bf16',
                    **_lr_sched_fields(ds),
                    **_ema_fields(ds),
                },
                'model': model,
                'sample': {
                    'sampler': 'flowmatch',
                    'neg': '',
                    'sample_every': _sample_every(ds),
                    # Base non distillée → vrai CFG (cf. docstring) : 4 / 25 steps.
                    'guidance_scale': 4,
                    'sample_steps': 25,
                    'prompts': _sample_prompts(ds, trigger),
                },
            }],
        },
    }


def _build_job_config_sdxl(ds, dataset_folder: str, steps: int, training_folder=None) -> dict:
    """Job-config ai-toolkit arch='sdxl' - valeurs VÉRIFIÉES dans ai-toolkit
    ui/.../options.ts (entrée 'sdxl', 2026-06-14) : quantize/quantize_te False,
    noise_scheduler/sampler 'ddpm', timestep_type DÉSACTIVÉ, guidance 6. Base =
    checkpoint SDXL ComfyUI local (single-file, pas de conversion)."""
    trigger = _safe_trigger(ds)
    base_model = getattr(ds, 'train_base_model', None)
    if not base_model:
        raise ValueError('SDXL: a base checkpoint is required')
    # A ComfyUI-whitelist basename resolves under models/checkpoints; a free
    # ABSOLUTE path is the opt-in custom-weights file (validated by the launch
    # preflight, so it bypasses the basename whitelist deliberately).
    name_or_path = base_model if _is_custom_weights(base_model) else _sdxl_base_path(base_model)
    model = {'arch': 'sdxl', 'name_or_path': name_or_path,
             'quantize': False, 'quantize_te': False}
    # SDXL is the only family where ai-toolkit honours these top-level overrides
    # (stable_diffusion_model.py). Emitted only when set; TE may be a local path
    # or a HF repo id (AutoModel.from_pretrained accepts both).
    _svae = getattr(ds, 'train_vae_path', None)
    _ste = getattr(ds, 'train_te_path', None)
    if _svae:
        model['vae_path'] = _svae
    if _ste:
        model['te_name_or_path'] = _ste
    _srank = _lora_rank(ds, 'sdxl')   # défaut 32 ; alpha = rank/2 (demi-force, conservé)
    return {
        'job': 'extension',
        'config': {
            'name': f'lora_{trigger}',
            'process': [{
                'type': 'sd_trainer',
                'training_folder': (training_folder if training_folder
                                    else str(_output_dir() / _run_name(ds))),
                'device': 'cuda:0',
                'trigger_word': trigger,
                'network': _network_block(ds, _srank, 'sdxl'),
                'save': {'dtype': 'float16', 'save_every': _save_every(ds),
                         'max_step_saves_to_keep': _max_step_saves(ds)},
                'datasets': [{
                    'folder_path': dataset_folder,
                    'caption_ext': 'txt',
                    'caption_dropout_rate': 0.05,
                    'cache_latents_to_disk': True,
                    'resolution': _train_res(ds),
                    **_mask_fields(dataset_folder),
                }],
                'train': {
                    'batch_size': 1,
                    'steps': steps,
                    'gradient_accumulation': _grad_accum(ds),
                    'train_unet': True,
                    'train_text_encoder': False,
                    'gradient_checkpointing': True,
                    'noise_scheduler': 'ddpm',   # SDXL = epsilon/DDPM (≠ flowmatch Z-Image)
                    'optimizer': _optimizer_eff(ds),
                    'lr': _lr_eff(ds),
                    'dtype': 'bf16',
                    **_lr_sched_fields(ds),
                    **_ema_fields(ds),
                },
                'model': model,
                'sample': {
                    'sampler': 'ddpm',
                    # neg='' EXPLICITE : sans cette clé, ai-toolkit met neg=False (booléen) et le
                    # tokenizer CLIP de transformers 5.x rejette [False] → ValueError au sample
                    # baseline (« text input must be of type str »). SDXL crashait juste avant la
                    # 1re step. '' est un str valide → sample sans négatif (voulu pour un LoRA sujet).
                    'neg': '',
                    'sample_every': _sample_every(ds),
                    'guidance_scale': 6,
                    'sample_steps': 28,
                    'prompts': _sample_prompts(ds, trigger),
                },
            }],
        },
    }
