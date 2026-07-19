"""'Share configuration' for a training run — a paste-safe text recipe.

Every card on the 🏋️ Runs hub (cloud AND local) can produce a downloadable
`.txt` listing EVERYTHING that launch sent to ai-toolkit (family/variant/base,
rank/alpha/lr/optimizer/resolution/steps/save_every/timestep/masked/…) plus the
run's outcome, so it can be shared as a recipe or pasted verbatim into a
Discord/GitHub help thread.

Two run worlds share one addressing scheme (see resolve_run):
  - `cloud-<CloudTrainingRun.id>`  — every cloud run (active, finished, legacy)
  - `rec-<TrainingRunRecord.id>`   — local runs (they exist only in the registry)

Retrofit + graceful degradation: a run recorded before the settings snapshot
existed has no `settings` blob, so the "Training parameters" section reads
"not recorded on this run" instead of failing. NOTHING secret (HF/vast keys,
auth tokens) is ever emitted, and the whole text is run through the shared
home-path redaction so no local `C:\\Users\\<name>\\…` path leaks.
"""
import json
import ntpath
import os
import re

from ..extensions import db
from ..models import CloudTrainingRun, TrainingRunRecord
from ..utils.time import utcnow
from ..utils.redact import redact_user_paths
from ..version import APP_VERSION
from . import cloud_training as ct

_FAMILY_LABEL = {'zimage': 'Z-Image', 'krea': 'Krea 2', 'sdxl': 'SDXL',
                 'flux': 'FLUX.1', 'flux2klein': 'FLUX.2 Klein'}

_NOT_RECORDED = 'not recorded on this run'


def resolve_run(run_key):
    """(crun, rec) for a share key — either may be None; (None, None) = unknown.

    `cloud-<id>` resolves the CloudTrainingRun and back-links its registry row
    (for the settings snapshot) via cloud_run_id. `rec-<id>` resolves the
    TrainingRunRecord and its CloudTrainingRun (if it was a cloud launch)."""
    kind, _, sid = (run_key or '').partition('-')
    if not sid.isdigit():
        return None, None
    rid = int(sid)
    if kind == 'cloud':
        crun = db.session.get(CloudTrainingRun, rid)
        if crun is None:
            return None, None
        rec = (TrainingRunRecord.query
               .filter_by(cloud_run_id=crun.id)
               .order_by(TrainingRunRecord.id.desc()).first())
        return crun, rec
    if kind == 'rec':
        rec = db.session.get(TrainingRunRecord, rid)
        if rec is None:
            return None, None
        crun = (db.session.get(CloudTrainingRun, rec.cloud_run_id)
                if rec.cloud_run_id else None)
        return crun, rec
    return None, None


# --- value formatting --------------------------------------------------------

def _fmt_resolution(v):
    if isinstance(v, (list, tuple)):
        return ' + '.join(str(x) for x in v) + ' px'
    return f'{v} px'


def _fmt_lr(v):
    try:
        return f'{float(v):g}'
    except (TypeError, ValueError):
        return str(v)


def _fmt_steps(v):
    return f'{v} steps'


# (snapshot key, human label, formatter). Rendered in this order; any snapshot
# key NOT listed here is still emitted generically below, so future snapshot
# enrichment shows up in the file without a change here.
_SETTING_ROWS = [
    ('trigger', 'Trigger word', str),
    ('rank', 'LoRA rank', str),
    ('alpha', 'LoRA alpha', str),
    ('network_type', 'Network type', str),
    ('resolution', 'Resolution', _fmt_resolution),
    ('save_every', 'Save every', _fmt_steps),
    ('max_step_saves', 'Max saved checkpoints', str),
    ('optimizer', 'Optimizer', str),
    ('lr', 'Learning rate', _fmt_lr),
    ('lr_scheduler', 'LR scheduler', str),
    ('warmup', 'Warmup steps', str),
    ('grad_accum', 'Gradient accumulation', str),
    ('timestep_type', 'Timestep type', str),
    ('dropout', 'LoRA dropout', str),
    ('ema', 'EMA decay', str),
    ('sample_every', 'Sample every', _fmt_steps),
]
_KNOWN_SETTING_KEYS = {k for k, _, _ in _SETTING_ROWS}


def _fmt_dt(dt):
    return dt.strftime('%Y-%m-%d %H:%M UTC') if dt else 'unknown'


def _slug(s):
    s = re.sub(r'[^\w.-]+', '_', (s or '').strip().lower())
    return s.strip('_') or 'dataset'


def _family_label(fam):
    return _FAMILY_LABEL.get(fam, fam or 'LoRA')


def _variant_label(variant):
    if not variant:
        return None
    return 'Raw' if variant == 'base' else variant


def _shared_value(key, value):
    """Remove machine-specific paths while retaining the useful file identity."""
    text = str(value)
    looks_path = (os.path.isabs(text) or ntpath.isabs(text)
                  or text.startswith(('~/', '~\\')))
    path_key = any(token in key.lower() for token in (
        'path', 'model', 'vae', 'encoder', 'directory', 'folder'))
    if looks_path or (path_key and ('/' in text or '\\' in text)):
        basename = ntpath.basename(text.replace('/', '\\')) or 'custom file'
        return f'{basename} (custom local file)'
    return value


# --- rendering ---------------------------------------------------------------

def build_run_config_text(run_key):
    """{'filename', 'text'} for a run key, or None when the key is unknown
    (route -> 404). The text is markdown-light and fully redacted."""
    crun, rec = resolve_run(run_key)
    if crun is None and rec is None:
        return None

    # --- resolve fields from whichever source has them (rec preferred) ------
    is_cloud = crun is not None or (rec is not None and rec.source == 'cloud')
    dataset_id = (rec.dataset_id if rec is not None else crun.dataset_id)
    family = (rec.family if rec is not None else ct._run_family(crun)) or None
    variant = (rec.variant if rec is not None
               else ct._run_param(crun, 'variant'))
    base_model = (rec.base_model if rec is not None else '') or ''
    steps = (rec.steps if rec is not None else ct._run_param(crun, 'steps'))
    if rec is not None:
        masked = bool(rec.masked)
    else:
        mp = ct._run_param(crun, 'masked')
        masked = None if mp is None else bool(mp)
    version = (rec.version if rec is not None
               else ct._run_param(crun, 'version'))
    created = (rec.created_at if rec is not None else None) or \
        (crun.created_at if crun is not None else None)
    dataset_name = ct._dataset_name(dataset_id)

    settings = None
    if rec is not None and rec.settings:
        try:
            settings = json.loads(rec.settings)
        except ValueError:
            settings = None
    if not isinstance(settings, dict):
        settings = None

    admission = None
    overrides = None
    if rec is not None:
        try:
            admission = json.loads(rec.preflight) if rec.preflight else None
        except (TypeError, ValueError):
            admission = None
        try:
            overrides = json.loads(rec.overrides) if rec.overrides else None
        except (TypeError, ValueError):
            overrides = None
    if not isinstance(admission, dict):
        admission = None
    if not isinstance(overrides, dict):
        overrides = None

    image_count = None
    if rec is not None and rec.manifest:
        try:
            man = json.loads(rec.manifest)
            if isinstance(man, list):
                image_count = len(man)
        except ValueError:
            pass

    L = []
    L.append('# LoRA Dataset Studio — training configuration')
    L.append('')
    L.append(f'App version:   {APP_VERSION}')
    L.append(f'Run date:      {_fmt_dt(created)}')
    L.append(f'Source:        {"cloud (vast.ai)" if is_cloud else "local"}')
    fam_line = _family_label(family)
    vlabel = _variant_label(variant)
    if vlabel:
        fam_line += f'  (variant: {vlabel})'
    L.append(f'Model family:  {fam_line}')
    L.append('Base model:    '
             + ('official Hugging Face base' if not base_model
                else str(_shared_value('base_model', base_model))))
    ds_bits = [dataset_name or f'#{dataset_id}']
    meta = []
    if version is not None:
        meta.append(f'version v{version}')
    if image_count is not None:
        meta.append(f'{image_count} image(s)')
    if meta:
        ds_bits.append('(' + ', '.join(meta) + ')')
    L.append(f'Dataset:       {" ".join(ds_bits)}')

    # --- training parameters -------------------------------------------------
    L.append('')
    L.append('## Training parameters (ai-toolkit)')
    L.append('')
    if settings is None:
        L.append(f'Training parameters are {_NOT_RECORDED} — it predates the '
                 'settings snapshot feature.')
    else:
        for key, label, fmt in _SETTING_ROWS:
            if key in settings and settings[key] is not None:
                L.append(f'{label + ":":<24}{_shared_value(key, fmt(settings[key]))}')
        # any enrichment key not in the known table -> generic line
        for key in sorted(settings):
            if key not in _KNOWN_SETTING_KEYS and settings[key] is not None:
                L.append(f'{key + ":":<24}{_shared_value(key, settings[key])}')
    # masked lives on the run row (not the snapshot) — always known for records.
    if masked is not None:
        L.append(f'{"Masked training:":<24}{"yes" if masked else "no"}')

    # --- admission decision -------------------------------------------------
    L.append('')
    L.append('## Admission decision')
    L.append('')
    if admission is None:
        L.append(f'Preflight snapshot is {_NOT_RECORDED}.')
    else:
        verdict = admission.get('verdict') or 'passed'
        L.append(f'{"Preflight verdict:":<24}{verdict}')
        if admission.get('kept') is not None:
            L.append(f'{"Admitted images:":<24}{admission["kept"]}')
        for label, key in (('Blockers', 'blockers'), ('Warnings', 'warnings')):
            values = admission.get(key)
            if isinstance(values, list):
                L.append(f'{label + ":":<24}{len(values)}')
                for value in values:
                    L.append(f'- {value}')
    if overrides is None:
        L.append(f'Explicit overrides:      {_NOT_RECORDED}')
    else:
        enabled = sorted(key for key, value in overrides.items() if value is True)
        L.append(f'{"Explicit overrides:":<24}{", ".join(enabled) if enabled else "none"}')

    # --- run outcome ---------------------------------------------------------
    L.append('')
    L.append('## Run outcome')
    L.append('')
    if steps is not None:
        L.append(f'{"Target steps:":<24}{steps}')
    if crun is not None:
        L.append(f'{"Status:":<24}{crun.status}')
        if crun.error:
            L.append(f'{"Error:":<24}{crun.error}')
        if crun.gpu_name:
            L.append(f'{"GPU:":<24}{crun.gpu_name}')
        if crun.price_per_hour:
            L.append(f'{"Cost:":<24}~${ct._cost_estimate(crun):.2f} '
                     f'(${crun.price_per_hour}/h)')
        if crun.finished_at:
            L.append(f'{"Finished:":<24}{_fmt_dt(crun.finished_at)}')
    else:
        L.append(f'{"Status:":<24}not recorded (local run history)')

    L.append('')
    L.append(f'Generated by LoRA Dataset Studio v{APP_VERSION} — '
             'paste-safe, no local paths or keys.')

    text = redact_user_paths('\n'.join(L) + '\n')
    date = created.strftime('%Y%m%d') if created else utcnow().strftime('%Y%m%d')
    filename = (f'lds-config-{_slug(dataset_name)}-{_slug(family)}'
                f'-v{version if version is not None else "na"}-{date}.txt')
    return {'filename': filename, 'text': text}
