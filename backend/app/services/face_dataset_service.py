"""Face-dataset orchestration: CRUD, fan-out, import, classify, caption, export.

The vision passes (classify/caption) call describe_image_ollama; the CALLER (the
route) is responsible for wrapping them in the GPU-exclusive window. The ComfyUI
output dir is resolved via `cfg.comfyui_dir('output')` so tests can monkeypatch cfg.
"""
from __future__ import annotations
from decimal import Decimal
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import threading
import time
import tempfile
import uuid
import zipfile
from pathlib import Path
from datetime import datetime, timezone

from PIL import Image

from ..extensions import db
from ..models import FaceDataset, FaceDatasetImage
from .. import config as cfg
from . import dataset_activity
from . import image_processing
from . import trash
from .import_analysis import analyse_image_bytes, analysis_json, parse_analysis
from .perceptual_hash import DHashIndex as _DHashIndex, dhash as _dhash, hamming as _hamming

# Garde le modèle vision chaud entre les images d'un même batch caption/classify
# (sinon Ollama le recharge - cold start ~10s - à CHAQUE image). Déchargé en fin
# de batch pour rendre la VRAM à ComfyUI. ComfyUI est déjà en pause pendant la passe.
_VISION_BATCH_KEEPALIVE = '5m'
from .face_variations import (  # noqa: E402 - constant is declared before the large import
                              CAPTION_REFINE_CONCEPT_PROMPT, CAPTION_LEAK_FIX_PROMPT,
                              EXPAND_CONCEPT_TERMS_PROMPT,
                              CLASSIFY_PROMPT, WATERMARK_BBOX_PROMPT,
                              aspect_for_label, caption_prompt_for,
                              caption_prompt_for_style, caption_prompt_for_concept,
                              caption_has_identity_leak, caption_has_concept_leak,
                              concept_lexical_field,
                              drop_identity_sentences, drop_identity_tags,
                              is_nsfw_label, prompt_by_label, wrap_variation,
                              VARIATION_CATALOG,
                              wrap_variation_klein)

logger = logging.getLogger(__name__)


def _comfy_output_dir():
    d = cfg.comfyui_dir('output')
    return str(d) if d else None


# Longueur max d'une caption stockée (colonne TEXT, pas de contrainte DB). 600 coupait
# les captions buste/environnement en plein mot ; 800 laisse passer la phrase d'ambiance
# finale tout en restant sous la fenêtre tokenizer (~512 tokens) à l'export trigger inclus.
CAPTION_MAX_CHARS = 800

# Padding du head-crop AUTO de la référence (côté du carré = grand côté de la bbox
# tête × pad). Volontairement plus large que l'ancien 1.7 (jugé « trop serré ») pour
# garder épaules + contexte par défaut ; le recadrage manuel depuis l'original permet
# d'ajuster ensuite dans les deux sens. Ne concerne QUE la référence (les imports
# gardent le défaut 1.7 de face_crop_to_square_webp).
REF_CROP_PAD = 2.0

# Un crop dont le côté source fait moins de size/1.5 se retrouve agrandi ≥50% par le
# LANCZOS du resize final — au-delà, la texture visible est majoritairement inventée
# par l'upscale plutôt que capturée du sujet. Seuil d'avertissement composition_upscaled
# (dataset_payload), pas un blocage : un unique gros plan upscalé n'est pas un problème,
# un dataset qui n'en a QUE des upscalés l'est (biais loss vers ce patch, cf. issue GitHub).
UPSCALE_WARN_THRESHOLD = 1.5


def _dataset_dir(dataset_id) -> str:
    d = str(cfg.dataset_images_root() / str(dataset_id))
    os.makedirs(d, exist_ok=True)
    return d


def _img_path(img) -> str:
    return os.path.join(_dataset_dir(img.dataset_id), img.filename)


def _atomic_write_bytes(path, data) -> None:
    """Durably publish bytes without exposing a partial destination file."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f'.{destination.name}.', suffix='.tmp', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(bytes(data))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


def _store_original_bytes(user_id, dataset_id, raw) -> str:
    """Persist the exact uploaded bytes under a generated, safe relative name."""
    format_ext = {
        'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'BMP': '.bmp',
        'GIF': '.gif', 'TIFF': '.tiff', 'AVIF': '.avif',
    }
    try:
        with Image.open(io.BytesIO(raw)) as image:
            ext = format_ext.get((image.format or '').upper(), '.bin')
    except (OSError, ValueError):
        ext = '.bin'
    filename = f"{user_id}_original_{uuid.uuid4().hex[:12]}{ext}"
    relative = os.path.join('originals', filename)
    path = os.path.join(_dataset_dir(dataset_id), relative)
    _atomic_write_bytes(path, raw)
    return relative


def _ref_path(ds) -> str:
    return os.path.join(_dataset_dir(ds.id), ds.ref_filename)

_VALID_STATUS = ('pending', 'keep', 'reject', 'failed')
MAX_FANOUT = 60
SMALL_IMAGE_SOURCE = 'small_image_source'
KLEIN_SMALL_IMAGE = 'klein_small_image'
KLEIN_IMAGE_IMPROVE = 'klein_image_improve'
KLEIN_IMAGE_IMPROVE_PROMPT = (
    'Restore this exact photograph at higher resolution. Preserve the exact identity, '
    'facial proportions, expression, pose, framing, lighting, clothing, background and '
    'camera character. Remove only compression artifacts, noise and recoverable blur. '
    'Do not beautify, restyle, change age, invent skin texture, or add new details.')
_SMALL_IMAGE_DERIVATIONS = (SMALL_IMAGE_SOURCE, KLEIN_SMALL_IMAGE)
_EXCLUSIVE_DERIVATIONS = (*_SMALL_IMAGE_DERIVATIONS, KLEIN_IMAGE_IMPROVE)
# A striped in-process lock is sufficient for LDS's single local server process
# and makes the active-candidate check + row creation + enqueue one critical
# section.  In particular, a second simultaneous lightbox click waits until the
# first row has its job_id, then takes the idempotent return path below.
_IMAGE_IMPROVE_LOCKS = tuple(threading.Lock() for _ in range(64))


class KleinNodesMissing(Exception):
    """Klein graph preflight failure carried from the service to the HTTP mapper."""

    def __init__(self, missing, missing_nodes):
        self.missing = list(missing or [])
        self.missing_nodes = list(missing_nodes or [])
        super().__init__('Klein custom nodes are missing')


# Références ADDITIONNELLES par dataset (au-delà de la principale) : servent
# UNIQUEMENT Nano Banana (multi-images d'entrée) - Klein/crop/scoring restent
# sur la principale. Cap bas pour garder des payloads API légers.
MAX_EXTRA_REFS = 3
# The corpus itself is intentionally unbounded (within the import guardrails).
# This is the default number of images packed into one API request: enough to
# cover several framings without blindly sending every photo in a large corpus.
# Keep it easy to tune as providers change their multi-image limits without
# changing the data model: LDS_MAX_GENERATION_REFERENCES=14 is the default.
try:
    MAX_GENERATION_REFERENCES = max(
        1, int(os.environ.get('LDS_MAX_GENERATION_REFERENCES', '14')))
except (TypeError, ValueError):
    MAX_GENERATION_REFERENCES = 14


def extra_ref_filenames(ds) -> list:
    """Références additionnelles du dataset (JSON en base, parse tolérant)."""
    try:
        v = json.loads(ds.ref_extra_filenames or '[]')
    except (ValueError, TypeError):
        return []
    return [f for f in v if isinstance(f, str)] if isinstance(v, list) else []


def _all_ref_bytes(ds) -> list:
    """Bytes de la référence principale puis des extras présents sur disque
    (ordre stable, principale d'abord - c'est elle que Gemini doit prioriser).
    Un extra au fichier manquant est ignoré silencieusement (jamais bloquant)."""
    with open(_ref_path(ds), 'rb') as fh:
        out = [fh.read()]
    for fn in extra_ref_filenames(ds):
        p = os.path.join(_dataset_dir(ds.id), fn)
        try:
            with open(p, 'rb') as fh:
                out.append(fh.read())
        except OSError:
            logger.warning(f"dataset {ds.id}: extra ref missing on disk: {fn}")
    return out


def _parse_generation_anchor_ids(value) -> list[int]:
    """Parse the durable imported-anchor list without trusting DB contents."""
    try:
        raw = json.loads(value or '[]')
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        try:
            image_id = int(item)
        except (TypeError, ValueError):
            continue
        if image_id > 0 and image_id not in out:
            out.append(image_id)
    return out


def _parse_generation_anchor_metadata(value) -> list[dict]:
    """Return safe, displayable anchor provenance descriptors from the DB."""
    try:
        raw = json.loads(value or '[]')
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        image_id = item.get('image_id')
        if image_id is not None:
            try:
                image_id = int(image_id)
            except (TypeError, ValueError):
                image_id = None
        filename = item.get('filename')
        if not isinstance(filename, str) or not filename:
            continue
        out.append({
            'image_id': image_id if image_id and image_id > 0 else None,
            'filename': filename[:255],
            'role': str(item.get('role') or 'import')[:32],
            'source_name': str(item.get('source_name') or '')[:255],
            'selection_reason': str(item.get('selection_reason') or '')[:120],
            'sha256': (str(item.get('sha256') or '')[:64]
                       if re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256') or ''))
                       else ''),
            'byte_size': (int(item.get('byte_size'))
                          if isinstance(item.get('byte_size'), int)
                          and item.get('byte_size') >= 0 else None),
        })
    return out


def _parse_json_list(value) -> list:
    try:
        parsed = json.loads(value or '[]')
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_generation_gap_ids(value) -> list[str]:
    out = []
    for item in _parse_json_list(value):
        if isinstance(item, str) and item and item not in out:
            out.append(item[:120])
    return out


ANCHOR_DECISIONS = ('auto', 'pinned', 'excluded')
COVERAGE_VALUES = {
    'angle': ('front', 'three-quarter', 'profile', 'back', 'other'),
    'expression': ('neutral', 'smile', 'laugh', 'serious', 'surprised', 'pensive', 'other'),
    'lighting': ('daylight', 'indoor', 'studio', 'golden-hour', 'low-light', 'mixed', 'other'),
    'pose': ('standing', 'sitting', 'moving', 'headshot', 'other'),
    'background': ('plain', 'indoor', 'outdoor', 'studio', 'crowded', 'other'),
    'occlusion': ('none', 'minor', 'major'),
}


def parse_coverage(value) -> dict:
    try:
        parsed = json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    out = {}
    for key, allowed in COVERAGE_VALUES.items():
        raw = str(parsed.get(key) or '').strip().lower()
        if raw in allowed:
            out[key] = raw
    return out


def normalize_coverage(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError('coverage must be an object')
    out = {}
    for key, allowed in COVERAGE_VALUES.items():
        raw = str(value.get(key) or '').strip().lower()
        if not raw:
            continue
        if raw not in allowed:
            raise ValueError(f'invalid {key}: {raw}')
        out[key] = raw
    return out


def _anchor_quality_score(img) -> float:
    """Cheap deterministic rank for imported identity anchors.

    Technical analysis is deliberately only a ranking signal. It never replaces
    the user's review decision, and a red image is retained as a last-resort
    fallback when a corpus contains no better candidates.
    """
    usefulness = {'green': 300.0, 'amber': 200.0, 'red': 100.0}.get(
        (img.training_usefulness or '').lower(), 0.0)
    analysis = parse_analysis(img.analysis_json) or {}
    metrics = analysis.get('metrics') if isinstance(analysis, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    numeric = []
    for key in ('sharpness', 'exposure', 'resolution'):
        try:
            numeric.append(max(0.0, min(100.0, float(metrics.get(key, 0)))))
        except (TypeError, ValueError):
            numeric.append(0.0)
    framing_bonus = {'face': 4.0, 'bust': 3.0, 'body': 2.0, 'back': 1.0}.get(
        (img.framing or '').lower(), 0.0)
    return usefulness + sum(numeric) / len(numeric) + framing_bonus


def _coerce_image_ids(value) -> list[int]:
    if isinstance(value, str):
        return _parse_generation_anchor_ids(value)
    out = []
    for item in value or []:
        try:
            image_id = int(item)
        except (TypeError, ValueError):
            continue
        if image_id > 0 and image_id not in out:
            out.append(image_id)
    return out


def _planned_anchor_rows(rows, *, preferred_ids=None, limit=MAX_GENERATION_REFERENCES):
    """Return ``[(row, reason)]`` for the imported part of an anchor pack.

    Explicitly preferred rows (regeneration) lead, then user-pinned rows, then a
    quality-ranked framing round-robin. Auto selection avoids near-duplicate
    siblings and technical red flags when cleaner alternatives exist. A user's
    pin is authoritative and may intentionally override both safeguards.
    """
    limit = max(0, int(limit or 0))
    eligible = [row for row in rows
                if row.filename and row.status == 'keep'
                and (row.anchor_decision or 'auto') != 'excluded']
    by_id = {row.id: row for row in eligible}
    planned = []
    used_ids = set()

    def add_manual(row, reason):
        if row is None or row.id in used_ids or len(planned) >= limit:
            return
        planned.append((row, reason))
        used_ids.add(row.id)

    for image_id in _coerce_image_ids(preferred_ids):
        add_manual(by_id.get(image_id), 'reused from original generation')
    pinned = sorted((row for row in eligible if row.anchor_decision == 'pinned'),
                    key=lambda row: (-_anchor_quality_score(row), row.id))
    for row in pinned:
        add_manual(row, 'pinned by user')

    remaining = [row for row in eligible if row.id not in used_ids]
    if any(row.training_usefulness != 'red' for row in remaining):
        remaining = [row for row in remaining if row.training_usefulness != 'red']
    ranked = sorted(remaining, key=lambda row: (-_anchor_quality_score(row), row.id))
    groups = {}
    group_order = ('face', 'bust', 'body', 'back', 'unknown')
    for row in ranked:
        groups.setdefault((row.framing or 'unknown').lower(), []).append(row)

    duplicate_roots = {row.duplicate_of_id or row.id for row, _reason in planned}
    while any(groups.values()) and len(planned) < limit:
        progressed = False
        for key in (*group_order, *sorted(set(groups) - set(group_order))):
            bucket = groups.get(key) or []
            while bucket:
                row = bucket.pop(0)
                root = row.duplicate_of_id or row.id
                if root in duplicate_roots:
                    continue
                planned.append((row, 'technical quality + framing diversity'))
                used_ids.add(row.id)
                duplicate_roots.add(root)
                progressed = True
                break
            if len(planned) >= limit:
                break
        if not progressed:
            break
    return planned[:limit]


def build_anchor_plan(ds, images, *, max_images=MAX_GENERATION_REFERENCES) -> dict:
    """Payload-safe preview of the exact imported anchors a new API request uses."""
    explicit = (1 if ds.ref_filename else 0) + len(extra_ref_filenames(ds))
    remaining = max(0, int(max_images) - explicit)
    imported = [row for row in images if row.source == 'import']
    planned = _planned_anchor_rows(imported, limit=remaining)
    selected_ids = [row.id for row, _reason in planned]
    return {
        'limit': int(max_images),
        'explicit_references': explicit,
        'selected_import_ids': selected_ids,
        'selected_total': min(int(max_images), explicit + len(selected_ids)),
        'pinned': sum(1 for row in imported if row.anchor_decision == 'pinned'),
        'excluded': sum(1 for row in imported if row.anchor_decision == 'excluded'),
        'eligible': sum(1 for row in imported if row.filename and row.status == 'keep'
                        and (row.anchor_decision or 'auto') != 'excluded'),
        'items': [
            {'image_id': row.id, 'source_name': row.source_name or '',
             'framing': row.framing or 'unknown',
             'technical': row.training_usefulness or 'unknown', 'reason': reason}
            for row, reason in planned
        ],
    }


def select_generation_references(ds, *, preferred_ids=None,
                                 max_images=MAX_GENERATION_REFERENCES) -> list[dict]:
    """Build a bounded, diverse reference pack for an API generation request.

    The dataset remains the complete reference pool. This function only chooses
    the request-sized anchor set: explicit primary/additional refs first, then
    reviewed imported photos ranked by technical usefulness and round-robined by
    framing. Returned descriptors contain bytes for the API and imported row ids
    for provenance; no source filesystem paths leave this service.
    """
    try:
        limit = max(1, int(max_images))
    except (TypeError, ValueError):
        limit = MAX_GENERATION_REFERENCES
    anchors = []
    seen_files = set()

    def add_file(filename, role, image_id=None, source_name=None, selection_reason=''):
        if not isinstance(filename, str) or not filename or filename in seen_files:
            return False
        path = os.path.join(_dataset_dir(ds.id), filename)
        try:
            with open(path, 'rb') as fh:
                raw = fh.read()
        except OSError:
            logger.warning('dataset %s: generation anchor missing on disk: %s', ds.id, filename)
            return False
        if not raw:
            return False
        seen_files.add(filename)
        anchors.append({'bytes': raw, 'filename': filename, 'image_id': image_id,
                        'role': role, 'source_name': source_name,
                        'selection_reason': selection_reason,
                        'sha256': hashlib.sha256(raw).hexdigest(),
                        'byte_size': len(raw)})
        return True

    # The explicit reference workflow keeps its ordering semantics: the main
    # reference is the first input, followed by the hand-picked extras.
    if ds.ref_filename:
        add_file(ds.ref_filename, 'primary_reference',
                 selection_reason='explicit primary reference')
    for filename in extra_ref_filenames(ds):
        if len(anchors) >= limit:
            break
        add_file(filename, 'additional_reference',
                 selection_reason='explicit additional reference')

    if len(anchors) >= limit:
        return anchors[:limit]

    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=ds.id, source='import')
            .filter(FaceDatasetImage.filename.isnot(None)).all())
    remaining = max(0, limit - len(anchors))
    for row, reason in _planned_anchor_rows(
            rows, preferred_ids=preferred_ids, limit=remaining):
        if len(anchors) >= limit:
            break
        add_file(row.filename, 'import', image_id=row.id, source_name=row.source_name,
                 selection_reason=reason)
    return anchors[:limit]


def _generation_anchor_ids_json(anchors) -> str:
    """Serialize imported row ids used by a generated candidate."""
    return json.dumps([a['image_id'] for a in anchors if a.get('image_id') is not None])


def _generation_anchor_metadata_json(anchors) -> str:
    """Serialize request-local anchor provenance without persisting file paths."""
    return json.dumps([
        {'image_id': anchor.get('image_id'), 'filename': anchor.get('filename'),
         'role': anchor.get('role'), 'source_name': anchor.get('source_name') or '',
         'selection_reason': anchor.get('selection_reason') or '',
         'sha256': anchor.get('sha256') or hashlib.sha256(anchor['bytes']).hexdigest(),
         'byte_size': anchor.get('byte_size', len(anchor['bytes']))}
        for anchor in anchors
    ], ensure_ascii=False)


def _explicit_reference_metadata_json(ds) -> str:
    items = []
    if ds.ref_filename:
        items.append({'image_id': None, 'filename': ds.ref_filename,
                      'role': 'primary_reference', 'source_name': '',
                      'selection_reason': 'explicit primary reference'})
    items.extend({'image_id': None, 'filename': filename,
                  'role': 'additional_reference', 'source_name': '',
                  'selection_reason': 'explicit additional reference'}
                 for filename in extra_ref_filenames(ds))
    return json.dumps(items, ensure_ascii=False)


def _write_reference_file(path: Path, data: bytes) -> None:
    """Create one private, uniquely named reference file without overwriting."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@trash.serialized_transaction
def set_primary_reference(user_id, dataset_id, original_webp: bytes,
                          cropped_webp: bytes) -> str:
    """Atomically replace the primary reference and retain an undoable Trash entry.

    Both new files are durable before the database pointer changes. Superseded
    files move to Trash; any write, move, or commit failure restores the previous
    filesystem/database state.
    """
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    dataset_root = Path(_dataset_dir(dataset_id)).resolve()
    original_name = f"{user_id}_datasetreforig_{uuid.uuid4().hex[:8]}.webp"
    reference_name = f"{user_id}_datasetref_{uuid.uuid4().hex[:8]}.webp"
    original_path = dataset_root / original_name
    reference_path = dataset_root / reference_name
    created = []
    trashed = None
    try:
        _write_reference_file(original_path, bytes(original_webp))
        created.append(original_path)
        _write_reference_file(reference_path, bytes(cropped_webp))
        created.append(reference_path)

        old_names = []
        for name in (ds.ref_filename, ds.ref_original_filename):
            if (isinstance(name, str) and Path(name).name == name
                    and name not in old_names):
                old_names.append(name)
        old_paths = [dataset_root / name for name in old_names
                     if (dataset_root / name).is_file()
                     and not (dataset_root / name).is_symlink()]
        if old_paths:
            from . import trash
            trashed = trash.send_paths_to_trash(
                old_paths, context=f'dataset-{dataset_id}-primary-reference', metadata={
                    'kind': 'dataset_primary_reference',
                    'dataset_id': dataset_id,
                    'ref_filename': (ds.ref_filename
                                     if ds.ref_filename in old_names else None),
                    'ref_original_filename': (
                        ds.ref_original_filename
                        if ds.ref_original_filename in old_names else None),
                    'label': f'Dataset {dataset_id} primary reference',
                })

        ds.ref_original_filename = original_name
        ds.ref_filename = reference_name
        db.session.commit()
    except Exception:
        db.session.rollback()
        for path in created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception('could not remove failed reference write %s', path)
        if trashed is not None:
            try:
                from . import trash
                trash.restore_entry(trashed['id'])
            except Exception:
                logger.exception('could not roll back primary-reference trash %s',
                                 trashed['id'])
        raise
    return reference_name


@trash.serialized_transaction
def restore_trashed_primary_reference(user_id, entry_id):
    """Swap a superseded primary reference back in without destroying the current one."""
    from . import trash
    metadata = trash.entry_metadata(entry_id)
    if metadata.get('kind') != 'dataset_primary_reference':
        raise ValueError('not a primary reference trash entry')
    try:
        dataset_id = int(metadata.get('dataset_id'))
    except (TypeError, ValueError):
        raise ValueError('trash entry has no valid dataset id')
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('the original dataset is no longer available')
    dataset_root = Path(_dataset_dir(dataset_id)).resolve()

    restored_names = []
    for key in ('ref_filename', 'ref_original_filename'):
        name = metadata.get(key)
        if name is not None and (not isinstance(name, str) or Path(name).name != name):
            raise ValueError('primary reference trash entry is invalid')
        if name and name not in restored_names:
            restored_names.append(name)
    recorded_targets = {
        str(Path(item.get('original_path', '')).resolve(strict=False))
        for item in (metadata.get('files') or []) if item.get('original_path')
    }
    expected_targets = {str(dataset_root / name) for name in restored_names}
    if not restored_names or recorded_targets != expected_targets:
        raise ValueError('primary reference trash entry is invalid')

    current_names = []
    for name in (ds.ref_filename, ds.ref_original_filename):
        if (isinstance(name, str) and Path(name).name == name
                and name not in current_names):
            current_names.append(name)
    current_paths = [dataset_root / name for name in current_names
                     if (dataset_root / name).is_file()
                     and not (dataset_root / name).is_symlink()]
    current_trash = None
    restored_metadata = None
    try:
        if current_paths:
            current_trash = trash.send_paths_to_trash(
                current_paths, context=f'dataset-{dataset_id}-primary-reference', metadata={
                    'kind': 'dataset_primary_reference',
                    'dataset_id': dataset_id,
                    'ref_filename': (ds.ref_filename
                                     if ds.ref_filename in current_names else None),
                    'ref_original_filename': (
                        ds.ref_original_filename
                        if ds.ref_original_filename in current_names else None),
                    'label': f'Dataset {dataset_id} primary reference',
                })
        restored_metadata = trash.restore_entry(entry_id, consume=False)['metadata']
        ds.ref_filename = metadata.get('ref_filename')
        ds.ref_original_filename = metadata.get('ref_original_filename')
        db.session.commit()
    except Exception:
        db.session.rollback()
        if restored_metadata is not None:
            try:
                trash.rollback_restored_entry(entry_id, restored_metadata)
            except Exception:
                logger.exception('could not roll back primary-reference restore %s', entry_id)
        if current_trash is not None:
            try:
                trash.restore_entry(current_trash['id'])
            except Exception:
                logger.exception('could not restore current primary reference %s',
                                 current_trash['id'])
        raise
    try:
        trash.remove_entry(entry_id)
    except OSError:
        logger.exception('restored primary reference but could not consume trash entry %s',
                         entry_id)
    return ds


def _variation_gap_ids_json(variation) -> str:
    value = variation.get('id') if isinstance(variation, dict) else None
    return json.dumps([str(value)[:120]]) if value else '[]'


def add_extra_ref(user_id, dataset_id, image_bytes) -> str:
    """Ajoute une référence additionnelle. Normalisée WEBP ratio conservé, SANS
    head-crop GPU : un plan buste/corps est une bonne réf d'identité pour Nano
    Banana, et l'upload ne doit pas dépendre de la fenêtre GPU. Retourne le nom
    de fichier ; ValueError si dataset absent, réf principale manquante ou cap."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if not ds.ref_filename:
        raise ValueError('set the primary reference first')
    extras = extra_ref_filenames(ds)
    if len(extras) >= MAX_EXTRA_REFS:
        raise ValueError(f'{MAX_EXTRA_REFS} extra references max')
    normalized = normalize_to_webp(image_bytes)
    fn = f"{user_id}_datasetrefx_{uuid.uuid4().hex[:8]}.webp"
    path = Path(_dataset_dir(dataset_id)) / fn
    with open(path, 'wb') as fh:
        fh.write(normalized)
    ds.ref_extra_filenames = json.dumps(extras + [fn])
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        raise
    return fn


@trash.serialized_transaction
def remove_extra_ref(user_id, dataset_id, filename) -> bool:
    """Move one additional reference to recoverable Trash and detach it.

    The file move and database edit behave as one transaction: a failed commit
    restores the file and keeps the old list.  A dedicated restore path below
    reattaches the filename as well as its bytes.
    """
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return False
    extras = extra_ref_filenames(ds)
    if filename not in extras:
        return False
    from . import trash
    path = Path(_dataset_dir(dataset_id)) / filename
    trashed = None
    if path.is_file() and not path.is_symlink():
        trashed = trash.send_paths_to_trash(
            [path], context=f'dataset-{dataset_id}-extra-reference', metadata={
                'kind': 'dataset_extra_reference',
                'dataset_id': dataset_id,
                'filename': filename,
                'label': filename,
            })
    ds.ref_extra_filenames = json.dumps([f for f in extras if f != filename])
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if trashed is not None:
            try:
                trash.restore_entry(trashed['id'])
            except Exception:
                logger.exception('could not roll back extra-reference trash %s', trashed['id'])
        raise
    return True


@trash.serialized_transaction
def restore_trashed_extra_reference(user_id, entry_id):
    """Restore an extra-reference Trash entry and reattach it to its dataset."""
    from . import trash
    metadata = trash.entry_metadata(entry_id)
    if metadata.get('kind') != 'dataset_extra_reference':
        raise ValueError('not an extra reference trash entry')
    try:
        dataset_id = int(metadata.get('dataset_id'))
    except (TypeError, ValueError):
        raise ValueError('trash entry has no valid dataset id')
    filename = metadata.get('filename')
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError('trash entry has no valid reference filename')
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('the original dataset is no longer available')
    extras = extra_ref_filenames(ds)
    if filename in extras:
        raise ValueError('the reference is already attached')
    if len(extras) >= MAX_EXTRA_REFS:
        raise ValueError(f'{MAX_EXTRA_REFS} extra references max')
    dataset_root = Path(_dataset_dir(dataset_id)).resolve()
    files = metadata.get('files') or []
    if len(files) != 1:
        raise ValueError('extra reference trash entry is invalid')
    original = files[0].get('original_path')
    if (not original
            or not Path(original).resolve(strict=False).is_relative_to(dataset_root)
            or Path(original).name != filename):
        raise ValueError('trash restore target is outside the dataset')
    restored_metadata = trash.restore_entry(entry_id, consume=False)['metadata']
    ds.ref_extra_filenames = json.dumps(extras + [filename])
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            trash.rollback_restored_entry(entry_id, restored_metadata)
        except Exception:
            logger.exception('could not roll back extra-reference restore %s', entry_id)
        raise
    try:
        trash.remove_entry(entry_id)
    except OSError:
        logger.exception('restored extra reference but could not consume trash entry %s', entry_id)
    return ds


# --- CRUD ------------------------------------------------------------------
# Natures de dataset. 'concept' inverse la logique personnage (cf import_images /
# caption_images). 'style' = esthétique globale : captions de CONTENU pur (le style
# n'est jamais décrit → il est absorbé par le LoRA), pas de trigger dans la config,
# dropout de caption élevé. Tout le reste (dont NULL) = 'character' (défaut historique).
DATASET_KINDS = ('character', 'concept', 'style')


def normalize_kind(kind) -> str | None:
    """'concept'/'style' -> tels quels ; tout le reste -> None (character, stocké NULL)."""
    k = (kind or '').strip().lower()
    return k if k in ('concept', 'style') else None


def _safe_json(text):
    """None-safe json.loads for TEXT columns holding JSON (never raises)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _watermark_regions_payload(img) -> dict:
    """Return the nullable stored override and the editor's always-list value."""
    stored = _safe_json(img.watermark_regions)
    if not isinstance(stored, list):
        stored = None
    if stored is not None:
        effective = stored
    else:
        bbox = _safe_json(img.watermark_bbox)
        effective = ([bbox] if img.watermark_state == 'detected'
                     and isinstance(bbox, list) and len(bbox) == 4 else [])
    return {
        'watermark_regions': stored,
        'effective_watermark_regions': effective,
    }


def is_concept(ds) -> bool:
    return bool(ds) and (getattr(ds, 'kind', None) or '').lower() == 'concept'


def is_style(ds) -> bool:
    return bool(ds) and (getattr(ds, 'kind', None) or '').lower() == 'style'


def is_conceptual(ds) -> bool:
    """Concept OU style : les kinds où l'invariant du set n'est PAS une identité.
    Regroupe les comportements communs : heuristiques personnage (équilibre de
    composition, fuite d'identité) sans objet, masques personne interdits (ils
    effaceraient ce qu'on apprend), barème de steps sous-linéaire (√n)."""
    return is_concept(ds) or is_style(ds)


# Cibles de fidélité (datasets personnage). 'body' = le LoRA reproduit AUSSI la
# morphologie : captions bannissent en plus les marques corporelles permanentes
# (elles se lient au trigger), composition recommandée plus corps/buste, import
# plein cadre par défaut.
FIDELITIES = ('face', 'body')


def normalize_fidelity(f) -> str:
    f = (f or '').strip().lower()
    return f if f in FIDELITIES else 'face'


def is_body_fidelity(ds) -> bool:
    return bool(ds) and (getattr(ds, 'fidelity', None) or 'face').lower() == 'body'


COMPOSITION_TARGET_FACE = {'face': 12, 'bust': 6, 'body': 6, 'back': 1}
COMPOSITION_TARGET_BODY = {'face': 8, 'bust': 8, 'body': 8, 'back': 2}
COVERAGE_PROFILES = ('strict', 'balanced', 'experimental')
_PROFILE_SCALE = {'strict': 1.25, 'balanced': 1.0, 'experimental': 0.65}


def coverage_targets(ds) -> dict:
    """Return the authoritative framing target for this dataset's fidelity."""
    base = COMPOSITION_TARGET_BODY if is_body_fidelity(ds) else COMPOSITION_TARGET_FACE
    profile = ((getattr(ds, 'coverage_profile', None) or 'balanced').lower()
               if ds else 'balanced')
    scale = _PROFILE_SCALE.get(profile, 1.0)
    targets = {key: max(1, int(math.ceil(value * scale))) for key, value in base.items()}
    custom = _safe_json(getattr(ds, 'coverage_targets', None)) if ds else None
    for key, value in ((custom or {}).get('framing') or {}).items():
        if key in targets and isinstance(value, int) and not isinstance(value, bool):
            targets[key] = max(0, min(100, value))
    return targets


COVERAGE_DIMENSION_TARGETS = {
    'angle': {'front': 4, 'three-quarter': 4, 'profile': 2, 'back': 1},
    'expression': {'neutral': 4, 'smile': 2, 'serious': 2, 'laugh': 1,
                   'surprised': 1, 'pensive': 1},
    'lighting': {'daylight': 3, 'indoor': 2, 'studio': 2,
                 'golden-hour': 1, 'low-light': 1},
    'pose': {'headshot': 4, 'standing': 2, 'sitting': 2, 'moving': 1},
    'background': {'plain': 2, 'indoor': 2, 'outdoor': 2, 'studio': 1},
}


def normalize_coverage_targets(targets) -> dict:
    """Validate and canonicalize a user- or backup-supplied coverage override."""
    if targets is not None and not isinstance(targets, dict):
        raise ValueError('coverage targets must be an object')
    clean = {'framing': {}, 'dimensions': {}}
    for key, value in ((targets or {}).get('framing') or {}).items():
        if key not in COMPOSITION_TARGET_FACE or isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'invalid framing target: {key}')
        clean['framing'][key] = max(0, min(100, value))
    for dimension, values in ((targets or {}).get('dimensions') or {}).items():
        if dimension not in COVERAGE_DIMENSION_TARGETS or not isinstance(values, dict):
            raise ValueError(f'invalid coverage dimension: {dimension}')
        clean['dimensions'][dimension] = {}
        for value, target in values.items():
            if (value not in COVERAGE_DIMENSION_TARGETS[dimension]
                    or isinstance(target, bool) or not isinstance(target, int)):
                raise ValueError(f'invalid {dimension} target: {value}')
            clean['dimensions'][dimension][value] = max(0, min(100, target))
    return clean


def _variation_coverage_hint(entry) -> dict:
    """Read catalogue-authored structured metadata; prompt prose is not parsed."""
    return normalize_coverage(entry.get('coverage') or {})


def coverage_dimension_targets(ds) -> dict:
    profile = ((getattr(ds, 'coverage_profile', None) or 'balanced').lower()
               if ds else 'balanced')
    scale = _PROFILE_SCALE.get(profile, 1.0)
    targets = {
        dimension: {value: max(1, int(math.ceil(target * scale)))
                    for value, target in values.items()}
        for dimension, values in COVERAGE_DIMENSION_TARGETS.items()
    }
    custom = _safe_json(getattr(ds, 'coverage_targets', None)) if ds else None
    for dimension, values in ((custom or {}).get('dimensions') or {}).items():
        if dimension not in targets or not isinstance(values, dict):
            continue
        for value, target in values.items():
            if (value in targets[dimension] and isinstance(target, int)
                    and not isinstance(target, bool)):
                targets[dimension][value] = max(0, min(100, target))
    return targets


def _dimension_plans(accepted, targets_by_dimension) -> list[dict]:
    parsed = [(img, parse_coverage(img.coverage_json)) for img in accepted]
    result = []
    for dimension, targets in targets_by_dimension.items():
        classified = sum(1 for _img, values in parsed if values.get(dimension))
        items = []
        for value, target in targets.items():
            count = sum(1 for _img, values in parsed if values.get(dimension) == value)
            state = ('covered' if count >= target else 'weak' if count
                     else 'missing' if classified else 'unknown')
            items.append({'id': f'{dimension}:{value}', 'value': value,
                          'have': count, 'target': target,
                          'deficit': max(0, target - count), 'state': state})
        result.append({'id': dimension, 'classified': classified,
                       'unknown': max(0, len(accepted) - classified), 'items': items})
    return result


def _conceptual_coverage_plan(ds, images):
    profile = (ds.coverage_profile or 'balanced').lower()
    target_by_profile = {'strict': 30, 'balanced': 20, 'experimental': 12}
    accepted = [img for img in images if img.filename and img.status == 'keep']
    # Source diversity is an admission signal, so rejected/pending corpus rows
    # must not make the trainable set look more diverse than it really is.
    imported = [img for img in accepted if img.source == 'import']
    captioned = [img for img in accepted if (img.caption or '').strip()]
    distinct_sources = len({(img.source_name or '').strip().lower() for img in imported
                            if (img.source_name or '').strip()})
    target = target_by_profile.get(profile, 20)
    return {
        'available': True,
        'mode': 'style' if is_style(ds) else 'concept',
        'profile': profile,
        'targets': {'usable': target, 'source_diversity': 3},
        'summary': {
            'usable': len(accepted), 'imported': len(imported),
            'captioned': len(captioned), 'uncaptioned': len(accepted) - len(captioned),
            'source_diversity': distinct_sources,
            'near_duplicates': sum(1 for img in imported if img.duplicate_of_id),
            'gaps': int(len(accepted) < target) + int(distinct_sources < 3),
        },
        'admission': [
            {'id': 'usable', 'label': 'Accepted examples', 'have': len(accepted),
             'target': target, 'state': 'covered' if len(accepted) >= target else 'weak'},
            {'id': 'sources', 'label': 'Distinct source labels', 'have': distinct_sources,
             'target': 3, 'state': 'covered' if distinct_sources >= 3 else 'weak'},
            {'id': 'captions', 'label': 'Captioned examples', 'have': len(captioned),
             'target': len(accepted),
             'state': 'covered' if len(captioned) == len(accepted) else 'weak'},
        ],
        'recommendations': ([{
            'kind': 'import', 'score': 1.0,
            'reason': f'Add {max(0, target - len(accepted))} more admitted examples',
            'estimated_remote_cost_usd': 0,
        }] if len(accepted) < target else []),
    }


def build_coverage_plan(ds, images) -> dict:
    """Describe what the corpus covers and what generation could fill.

    This is intentionally conservative: an imported photo with no vision
    classification is ``unknown`` for a catalogue combination, not falsely
    counted as missing. Only genuinely empty framing buckets become automatic
    generation recommendations, so the plan does not spend API calls to solve
    uncertainty that a human review or later classifier can resolve.
    """
    if is_conceptual(ds):
        return _conceptual_coverage_plan(ds, images)
    profile = (ds.coverage_profile or 'balanced').lower()
    targets = coverage_targets(ds)
    # Only accepted rows count as covered. Pending generations are candidates,
    # not members of the training set yet.
    accepted = [img for img in images if img.filename and img.status == 'keep']
    composition = {framing: sum(1 for img in accepted if img.framing == framing)
                   for framing in targets}
    imported = [img for img in accepted if img.source == 'import']
    all_imported = [img for img in images if img.source == 'import' and img.filename]
    generated = [img for img in accepted if img.source == 'generated']
    pending_generated = [img for img in images if img.source == 'generated'
                         and img.filename and img.status == 'pending']
    technical = {'green': 0, 'amber': 0, 'red': 0, 'unknown': 0}
    for img in all_imported:
        key = (img.training_usefulness or 'unknown').lower()
        technical[key if key in technical else 'unknown'] += 1

    framing_gaps = []
    for framing, target in targets.items():
        have = composition[framing]
        framing_gaps.append({
            'id': f'framing:{framing}',
            'framing': framing,
            'have': have,
            'target': target,
            'deficit': max(0, target - have),
            'state': 'covered' if have >= target else 'weak' if have else 'missing',
            'imported': sum(1 for img in imported if img.framing == framing),
            'generated': sum(1 for img in generated if img.framing == framing),
        })

    dimension_plans = _dimension_plans(accepted, coverage_dimension_targets(ds))
    labels = []
    for entry in VARIATION_CATALOG:
        framing = entry.get('framing')
        existing = sum(1 for img in generated
                       if img.variation_label == entry.get('label'))
        hint = _variation_coverage_hint(entry)
        matching_import = any(
            img.framing == framing
            and all(parse_coverage(img.coverage_json).get(key) == value
                    for key, value in hint.items())
            for img in imported)
        frame_unknown = any(img.framing in (None, 'unknown')
                            or (img.framing == framing and not parse_coverage(img.coverage_json))
                            for img in imported)
        if existing:
            state = 'covered'
        elif hint and matching_import:
            state = 'covered'
        elif frame_unknown or not hint:
            state = 'unknown'
        else:
            state = 'missing'
        labels.append({
            'id': entry['id'], 'label': entry['label'], 'framing': framing,
            'axis': entry.get('axis'), 'state': state, 'generated': existing,
            'coverage_hint': hint,
        })

    deficits = {gap['framing']: gap['deficit'] for gap in framing_gaps}
    recommended = sorted(
        (entry for entry in labels if entry['state'] == 'missing'),
        key=lambda entry: (-deficits.get(entry['framing'], 0),
                           entry.get('axis') or '', entry['id']))
    # Keep the default plan useful and affordable: a handful of distinct gap
    # shots is preselected in the catalogue, while the complete list remains
    # visible for manual expansion.
    recommendation_limit = {'strict': 6, 'balanced': 8, 'experimental': 12}.get(profile, 8)
    recommended = recommended[:recommendation_limit]
    unclassified = [img for img in all_imported
                    if img.framing in (None, 'unknown')
                    or len(parse_coverage(img.coverage_json)) < 6]
    low_confidence = []
    for img in all_imported:
        provenance = _safe_json(img.coverage_provenance) or {}
        values = [float(value) for value in (provenance.get('confidence') or {}).values()
                  if isinstance(value, (int, float)) and not isinstance(value, bool)]
        if values and sum(values) / len(values) < 0.7:
            low_confidence.append(img)
    joint = []
    seen_joint = set()
    for entry in VARIATION_CATALOG:
        hint = _variation_coverage_hint(entry)
        signature = tuple((key, hint.get(key)) for key in ('angle', 'expression', 'lighting')
                          if hint.get(key))
        if len(signature) < 2 or signature in seen_joint:
            continue
        seen_joint.add(signature)
        have = sum(1 for img in accepted if all(
            parse_coverage(img.coverage_json).get(key) == value for key, value in signature))
        joint.append({'id': '|'.join(f'{key}:{value}' for key, value in signature),
                      'values': dict(signature), 'have': have, 'target': 1,
                      'state': 'covered' if have else 'missing'})
    recommendations = []
    if unclassified or low_confidence:
        recommendations.append({
            'kind': 'classify', 'score': 1.0,
            'reason': f'Review {len(set(unclassified + low_confidence))} unknown/low-confidence image(s) before spending',
            'estimated_remote_cost_usd': 0,
        })
    for rank, entry in enumerate(recommended):
        recommendations.append({
            'kind': 'generate', 'variation_id': entry['id'],
            'score': round(max(0.1, 1.0 - rank * 0.07), 2),
            'reason': f"Missing {entry['framing']} coverage ({entry.get('axis') or 'composition'})",
            'estimated_remote_cost_usd': {'nanobanana': 0.04, 'chatgpt': 0.04},
        })
    return {
        'available': True,
        'mode': 'character',
        'profile': profile,
        'targets': targets,
        'framing': framing_gaps,
        'dimensions': dimension_plans,
        'combinations': labels,
        'joint_coverage': joint,
        'recommendations': recommendations,
        'recommended_variation_ids': [entry['id'] for entry in recommended],
        'summary': {
            'usable': len(accepted), 'imported': len(imported),
            'reference_pool': len(all_imported), 'generated': len(generated),
            'pending_candidates': len(pending_generated),
            'gaps': sum(1 for gap in framing_gaps if gap['deficit'] > 0),
            'dimension_gaps': sum(1 for dimension in dimension_plans
                                  for item in dimension['items']
                                  if item['state'] in ('missing', 'weak')),
            'missing_combinations': sum(1 for entry in labels if entry['state'] == 'missing'),
            'unknown_combinations': sum(1 for entry in labels if entry['state'] == 'unknown'),
            'originals_preserved': sum(1 for img in all_imported if img.original_filename),
            'unclassified': len(unclassified),
            'low_confidence': len(low_confidence),
            'near_duplicates': sum(1 for img in all_imported if img.duplicate_of_id),
            'duplicate_groups': len({img.duplicate_of_id for img in all_imported
                                     if img.duplicate_of_id}),
        },
        'technical': technical,
        'anchor_limit': MAX_GENERATION_REFERENCES,
    }


def set_fidelity(user_id, dataset_id, fidelity) -> bool:
    """Switch face-only <-> full-body fidelity later. Affects FUTURE captions
    (re-caption to apply) + the composition target + the import crop default."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return False
    ds.fidelity = normalize_fidelity(fidelity)
    db.session.commit()
    return True


def set_coverage_policy(user_id, dataset_id, profile, targets=None) -> bool:
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return False
    normalized = str(profile or 'balanced').strip().lower()
    if normalized not in COVERAGE_PROFILES:
        raise ValueError('coverage profile must be strict, balanced, or experimental')
    clean = normalize_coverage_targets(targets)
    ds.coverage_profile = normalized
    ds.coverage_targets = json.dumps(clean, ensure_ascii=False, sort_keys=True)
    db.session.commit()
    return True


# Familles de modèle entraînables (= pipeline ai-toolkit). Source de vérité côté UI
# ET validation : choisie à la création, drive le format de caption (sdxl→booru, sinon
# prose) et le regroupement du menu. Reste modifiable ensuite (TrainingPanel).
# NB : 'flux2klein' (FLUX.2 Klein) — PAS 'klein' : ce namespace est déjà pris par
# le moteur de GÉNÉRATION (engines.klein, unet/klein/) ; un train_type 'klein'
# télescoperait les résolveurs de modèles et les chemins loras du Studio.
TRAIN_TYPES = ('zimage', 'sdxl', 'krea', 'flux', 'flux2klein')


def normalize_train_type(t) -> str:
    """Famille valide en minuscules, défaut 'zimage' (toute valeur inconnue/None)."""
    t = (t or '').strip().lower()
    return t if t in TRAIN_TYPES else 'zimage'


def create_dataset(user_id, name, trigger_word, kind=None, concept_desc=None, train_type=None,
                   fidelity=None):
    k = normalize_kind(kind)
    desc = (concept_desc or '').strip()
    if k == 'concept' and not desc:
        # The concept description is what the captioner OMITS; without it the
        # inverted-caption logic has nothing to bind the trigger to. Required.
        raise ValueError('concept_desc required for a concept dataset')
    ds = FaceDataset(user_id=str(user_id), name=(name or '').strip()[:100],
                     trigger_word=(trigger_word or '').strip()[:60] or 'zchar',
                     # concept_desc n'a de sens que pour un concept ; un STYLE n'a rien
                     # à omettre nommément (les captions décrivent le contenu, jamais le
                     # rendu — c'est le prompt de caption qui porte cette règle).
                     kind=k, concept_desc=(desc[:500] if k == 'concept' else None),
                     train_type=normalize_train_type(train_type),
                     # fidelity ne concerne que les personnages (concept : l'acte est
                     # omis ; style : les sujets varient, aucune identité à protéger).
                     fidelity=(normalize_fidelity(fidelity) if k is None else None))
    db.session.add(ds)
    db.session.commit()
    if k == 'style' and not (trigger_word or '').strip():
        # Un style n'exige pas de trigger (l'UI le présente comme facultatif), mais
        # `_run_name`/`lora_{trigger}` nomment le run d'entraînement avec : deux styles
        # créés sans trigger retomberaient tous deux sur 'zchar' → le garde anti-
        # collision bloquerait le 2e entraînement. On sale le défaut avec l'id.
        ds.trigger_word = f'zsty_{ds.id}'
        db.session.commit()
    return ds


def set_train_type(user_id, dataset_id, train_type) -> bool:
    """Change the target model family later (kept in sync with the TrainingPanel
    selector so the menu re-groups). Normalizes; unknown -> zimage. False if absent."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return False
    ds.train_type = normalize_train_type(train_type)
    db.session.commit()
    return True


def update_dataset_settings(user_id, dataset_id, *, name=None, trigger_word=None,
                            concept_desc=None):
    """Edit a dataset's identity AFTER creation. Returns {'ok', 'concept_desc_changed'}
    or None if the dataset is absent; raises ValueError on invalid input.

    Changing the **trigger word** is safe and needs NO re-caption: captions are stored
    without it (it's prepended at export). Changing a concept dataset's **description**
    (what the captions must omit) invalidates the cached LLM avoid-list (concept_terms)
    so it regenerates — but images already captioned keep the OLD omission until
    re-captioned (same 'future captions' contract as set_fidelity)."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return None
    if name is not None:
        n = (name or '').strip()
        if n:
            ds.name = n[:100]
    if trigger_word is not None:
        t = (trigger_word or '').strip()
        if not t:
            raise ValueError('trigger_word cannot be empty')
        ds.trigger_word = t[:60]
    concept_changed = False
    if concept_desc is not None and is_concept(ds):
        d = (concept_desc or '').strip()
        if not d:
            raise ValueError('concept_desc required for a concept dataset')
        if d[:500] != (ds.concept_desc or ''):
            ds.concept_desc = d[:500]
            ds.concept_terms = None   # invalidate the cached LLM avoid-list → regenerated next caption
            concept_changed = True
    db.session.commit()
    return {'ok': True, 'concept_desc_changed': concept_changed}


def get_dataset(user_id, dataset_id):
    ds = db.session.get(FaceDataset, dataset_id)
    return ds if (ds and ds.trashed_at is None
                  and str(ds.user_id) == str(user_id)) else None


def list_datasets(user_id):
    return (FaceDataset.query.filter_by(user_id=str(user_id))
            .filter(FaceDataset.trashed_at.is_(None))
            .order_by(FaceDataset.updated_at.desc()).all())


def dataset_list_stats(user_id):
    """Per-dataset aggregates for the library page — image counts and the
    families ever trained — in two grouped queries (never one per dataset).
    Returns {dataset_id: {'images_total', 'images_kept', 'images_captioned',
    'trained_families': [str]}}; datasets absent from a map just have zeros."""
    from sqlalchemy import case, func
    from ..models import TrainingRunRecord
    owned = (db.session.query(FaceDataset.id)
             .filter_by(user_id=str(user_id))
             .filter(FaceDataset.trashed_at.is_(None))).subquery()
    stats = {}
    img_rows = (db.session.query(
        FaceDatasetImage.dataset_id,
        func.count(FaceDatasetImage.id),
        func.sum(case((FaceDatasetImage.status == 'keep', 1), else_=0)),
        func.sum(case(((FaceDatasetImage.status == 'keep')
                       & (func.coalesce(FaceDatasetImage.caption, '') != ''), 1), else_=0)))
        .filter(FaceDatasetImage.dataset_id.in_(db.session.query(owned.c.id)))
        .filter(FaceDatasetImage.status != 'trashed')
        .group_by(FaceDatasetImage.dataset_id).all())
    for ds_id, total, kept, captioned in img_rows:
        stats[ds_id] = {'images_total': int(total or 0), 'images_kept': int(kept or 0),
                        'images_captioned': int(captioned or 0), 'trained_families': []}
    fam_rows = (db.session.query(TrainingRunRecord.dataset_id, TrainingRunRecord.family)
                .filter(TrainingRunRecord.dataset_id.in_(db.session.query(owned.c.id)))
                .distinct().all())
    for ds_id, fam in fam_rows:
        entry = stats.setdefault(ds_id, {'images_total': 0, 'images_kept': 0,
                                         'images_captioned': 0, 'trained_families': []})
        if fam and fam not in entry['trained_families']:
            entry['trained_families'].append(fam)
    for entry in stats.values():
        entry['trained_families'].sort()
    return stats


def _clear_watermark_metadata(img):
    img.watermark_state = None
    img.watermark_bbox = None
    img.watermark_regions = None


def set_image_status(user_id, image_id, status):
    if status not in _VALID_STATUS:
        raise ValueError('invalid status')
    img = _owned_image(user_id, image_id)
    if not img:
        return False
    if img.derivation_kind in _SMALL_IMAGE_DERIVATIONS:
        raise ValueError('resolve small-image rescue pairs with the dedicated review action')
    if _has_image_improvement_pair(img):
        raise ValueError('resolve reconstructed image pairs with the dedicated comparison action')
    from . import curation_history
    fields = ('status', 'watermark_state', 'watermark_bbox', 'watermark_regions')
    before = curation_history.snapshot(img, fields)
    if status == 'reject':
        _clear_watermark_metadata(img)
    img.status = status
    curation_history.record(
        user_id, img, f'status:{status}', before,
        curation_history.snapshot(img, fields))
    db.session.commit()
    return True


def _owned_image(user_id, image_id):
    img = db.session.get(FaceDatasetImage, image_id)
    if not img or img.status == 'trashed':
        return None
    ds = db.session.get(FaceDataset, img.dataset_id)
    return img if (ds and ds.trashed_at is None
                   and str(ds.user_id) == str(user_id)) else None


def _has_image_improvement_pair(img) -> bool:
    if not img:
        return False
    if img.derivation_kind == KLEIN_IMAGE_IMPROVE:
        if not img.parent_image_id:
            return False
        return (FaceDatasetImage.query.filter_by(
            id=img.parent_image_id, dataset_id=img.dataset_id).first() is not None)
    return (FaceDatasetImage.query.filter_by(
        dataset_id=img.dataset_id, parent_image_id=img.id,
        derivation_kind=KLEIN_IMAGE_IMPROVE).first() is not None)


def _image_improvement_candidates(source):
    if not source:
        return []
    return (FaceDatasetImage.query.filter_by(
        dataset_id=source.dataset_id, parent_image_id=source.id,
        derivation_kind=KLEIN_IMAGE_IMPROVE)
        .order_by(FaceDatasetImage.id.asc()).all())


def _image_improvement_resolved_choice(source, candidates, selected_id=None):
    """Return the terminal group choice, accounting for legacy sibling rows."""
    if not source or not candidates:
        return None
    statuses = [candidate.status for candidate in candidates]
    if source.status == 'keep' and all(status == 'reject' for status in statuses):
        return 'original'
    if source.status == 'reject' and all(status == 'reject' for status in statuses):
        return 'reject'
    kept = [candidate for candidate in candidates if candidate.status == 'keep']
    if (source.status == 'reject' and len(kept) == 1
            and all(candidate.status in ('keep', 'reject') for candidate in candidates)):
        if selected_id is None or kept[0].id == selected_id:
            return 'improved'
        return f'improved:{kept[0].id}'
    return None


def _unresolved_image_improvement_ids(dataset_id):
    candidates = (FaceDatasetImage.query.filter_by(
        dataset_id=dataset_id, derivation_kind=KLEIN_IMAGE_IMPROVE)
        .order_by(FaceDatasetImage.id.asc()).all())
    by_parent = {}
    for candidate in candidates:
        by_parent.setdefault(candidate.parent_image_id, []).append(candidate)
    ids = set()
    for parent_id, siblings in by_parent.items():
        source = db.session.get(FaceDatasetImage, parent_id) if parent_id else None
        if source and _image_improvement_resolved_choice(source, siblings) is None:
            ids.add(source.id)
            ids.update(candidate.id for candidate in siblings)
    return ids


def _is_unresolved_image_improvement_row(img):
    if not img:
        return False
    if img.derivation_kind == KLEIN_IMAGE_IMPROVE:
        source = (db.session.get(FaceDatasetImage, img.parent_image_id)
                  if img.parent_image_id else None)
    else:
        source = img
    if not source:
        return False
    candidates = _image_improvement_candidates(source)
    return bool(candidates) and _image_improvement_resolved_choice(source, candidates) is None


def normalize_legacy_image_improvement_rows(dataset_id=None):
    """Normalize pre-exclusive reconstruction siblings without deleting their files.

    Old releases allowed several independently curated candidates for one source.
    Coherent groups are left untouched. Ambiguous groups are reduced to one latest
    review candidate; every competitor is retained as rejected provenance.
    """
    # Some additive-migration tests (and very early installations) have a skeletal
    # image table that predates most ORM columns. An ORM entity query selects every
    # mapped column, so defer normalization until that historical schema has been
    # upgraded instead of making app startup fail on an unrelated missing column.
    from sqlalchemy import inspect
    existing_columns = {
        column['name'] for column in inspect(db.engine).get_columns('face_dataset_image')
    }
    mapped_columns = {column.name for column in FaceDatasetImage.__table__.columns}
    if not mapped_columns.issubset(existing_columns):
        logger.info('skipping reconstruction normalization for incomplete legacy image schema')
        return 0

    query = FaceDatasetImage.query.filter_by(derivation_kind=KLEIN_IMAGE_IMPROVE)
    if dataset_id is not None:
        query = query.filter_by(dataset_id=dataset_id)
    candidates = query.order_by(FaceDatasetImage.id.asc()).all()
    groups = {}
    for candidate in candidates:
        groups.setdefault((candidate.dataset_id, candidate.parent_image_id), []).append(candidate)
    normalized = 0
    for (ds_id, parent_id), siblings in groups.items():
        if len(siblings) < 2 or not parent_id:
            continue
        source = FaceDatasetImage.query.filter_by(id=parent_id, dataset_id=ds_id).first()
        if not source:
            continue  # orphan candidates intentionally remain independently cleanable
        choice = _image_improvement_resolved_choice(source, siblings)
        if choice in ('original', 'reject', 'improved'):
            continue
        kept = [candidate for candidate in siblings if candidate.status == 'keep']
        if source.status == 'reject' and len(kept) == 1:
            canonical = kept[0]
            for sibling in siblings:
                if sibling.id != canonical.id:
                    sibling.status = 'reject'
                    _clear_watermark_metadata(sibling)
            normalized += 1
            continue
        canonical = max(
            siblings,
            key=lambda candidate: (candidate.filename is not None, candidate.id))
        source.status = 'pending'
        for sibling in siblings:
            if sibling.id == canonical.id:
                if sibling.filename:
                    sibling.status = 'pending'
                elif sibling.status != 'pending' or not sibling.job_id:
                    sibling.status = 'failed'
                    sibling.fail_reason = (sibling.fail_reason
                                           or 'Legacy reconstruction requires review; no result file is available.')
            else:
                sibling.status = 'reject'
                _clear_watermark_metadata(sibling)
        normalized += 1
    if normalized:
        db.session.commit()
        logger.info('normalized %s legacy reconstruction sibling group(s)', normalized)
    return normalized


def resolve_small_image_rescue(user_id, dataset_id, candidate_id, choice):
    """Resolve an original/Klein rescue pair in one DB commit.

    The pair is deliberately not mutable through the generic single/batch status
    paths: exactly one of these three decisions is the source of truth.
    Returns None when the owned dataset/candidate does not exist.
    """
    if choice not in ('original', 'klein', 'reject'):
        raise ValueError('choice must be original, klein, or reject')

    def _load_pair():
        ds = get_dataset(user_id, dataset_id)
        if not ds:
            return None, None
        candidate = (FaceDatasetImage.query
                     .filter_by(id=candidate_id, dataset_id=dataset_id).first())
        if not candidate:
            return None, None
        if candidate.derivation_kind != KLEIN_SMALL_IMAGE or not candidate.parent_image_id:
            raise ValueError('image is not a Klein small-image rescue candidate')
        source = (FaceDatasetImage.query
                  .filter_by(id=candidate.parent_image_id, dataset_id=dataset_id,
                             derivation_kind=SMALL_IMAGE_SOURCE).first())
        if not source:
            raise ValueError('small-image rescue source is missing or invalid')
        return source, candidate

    def _resolved_as(source, candidate):
        states = (source.status, candidate.status)
        return {('keep', 'reject'): 'original',
                ('reject', 'keep'): 'klein',
                ('reject', 'reject'): 'reject'}.get(states)

    def _payload(source, candidate):
        return {'choice': choice,
                'source': {'id': source.id, 'status': source.status},
                'candidate': {'id': candidate.id, 'status': candidate.status}}

    # Cancel before touching pair statuses: queue_manager uses the same scoped DB
    # session and commits its job row, so calling it after mutations would split
    # the supposedly atomic source/candidate decision.
    source, candidate = _load_pair()
    if source is None:
        return None
    already = _resolved_as(source, candidate)
    if already:
        result = _payload(source, candidate)
        db.session.rollback()
        if already != choice:
            raise RuntimeError(f'small-image rescue was already resolved as {already}')
        return result  # idempotent retry
    job_id = (candidate.job_id if choice != 'klein' and not candidate.filename else None)
    db.session.rollback()  # close the preflight read transaction before queue cancellation
    if job_id:
        try:
            from ..job_queue import queue_manager
            queue_manager.cancel_job(job_id, str(user_id), 'image')
        except Exception:
            logger.exception('small-image rescue: failed to cancel job %s', job_id)
    db.session.rollback()

    # SQLite's BEGIN IMMEDIATE serializes competing resolutions before either one
    # reads the transition state. The second caller therefore observes the first
    # committed choice and follows the idempotent/conflict branch.
    from sqlalchemy import text
    try:
        db.session.execute(text('BEGIN IMMEDIATE'))
        source, candidate = _load_pair()
        if source is None:
            db.session.rollback()
            return None
        already = _resolved_as(source, candidate)
        if already:
            if already != choice:
                raise RuntimeError(f'small-image rescue was already resolved as {already}')
            result = _payload(source, candidate)
            db.session.rollback()
            return result
        if source.status != 'pending' or candidate.status not in ('pending', 'failed'):
            raise RuntimeError('small-image rescue is not in a resolvable state')
        from . import curation_history
        fields = ('status', 'watermark_state', 'watermark_bbox', 'watermark_regions')
        before = {row.id: curation_history.snapshot(row, fields)
                  for row in (source, candidate)}
        if job_id and not candidate.filename and before[candidate.id].get('status') == 'pending':
            # Undo must not recreate a pending row whose queue job was already
            # cancelled outside this transaction.
            before[candidate.id]['status'] = 'failed'
        if choice == 'klein':
            if candidate.status == 'failed' or not candidate.filename:
                raise ValueError('Klein rescue result is not ready')
            source.status, candidate.status = 'reject', 'keep'
            _clear_watermark_metadata(source)
        elif choice == 'original':
            source.status, candidate.status = 'keep', 'reject'
            _clear_watermark_metadata(candidate)
        else:
            source.status = candidate.status = 'reject'
            _clear_watermark_metadata(source)
            _clear_watermark_metadata(candidate)
        batch_id = curation_history.new_batch_id()
        for row in (source, candidate):
            curation_history.record(
                user_id, row, f'small_rescue:{choice}', before[row.id],
                curation_history.snapshot(row, fields), batch_id=batch_id)
        db.session.commit()
        result = _payload(source, candidate)
    except Exception:
        db.session.rollback()
        raise
    _sync_generate_activity(dataset_id)
    return result


def resolve_image_improvement(user_id, dataset_id, candidate_id, choice):
    """Atomically admit the source, admit its reconstruction, or reject both.

    A reconstruction and the pixels it derives from are one evidence item, never two
    independent training samples. Generic status/delete paths therefore refuse either
    row and this resolver is the only way to make a training decision.
    """
    if choice not in ('original', 'improved', 'reject'):
        raise ValueError('choice must be original, improved, or reject')

    def _load_pair():
        ds = get_dataset(user_id, dataset_id)
        if not ds:
            return None, None, []
        candidate = FaceDatasetImage.query.filter_by(
            id=candidate_id, dataset_id=dataset_id,
            derivation_kind=KLEIN_IMAGE_IMPROVE).first()
        if not candidate or not candidate.parent_image_id:
            raise ValueError('image is not a reconstruction candidate')
        source = FaceDatasetImage.query.filter_by(
            id=candidate.parent_image_id, dataset_id=dataset_id).first()
        if not source:
            raise ValueError('reconstruction source is missing')
        siblings = _image_improvement_candidates(source)
        return source, candidate, siblings

    source, candidate, siblings = _load_pair()
    if source is None:
        return None
    already = _image_improvement_resolved_choice(source, siblings, candidate.id)
    if already:
        result = {'choice': already,
                  'source': {'id': source.id, 'status': source.status},
                  'candidate': {'id': candidate.id, 'status': candidate.status}}
        db.session.rollback()
        if already.startswith('improved:'):
            raise RuntimeError(
                f'image reconstruction was already resolved with candidate {already.split(":", 1)[1]}')
        if already != choice:
            raise RuntimeError(f'image reconstruction was already resolved as {already}')
        return result
    if choice == 'improved' and not candidate.filename:
        db.session.rollback()
        raise ValueError('the reconstructed candidate is not ready')
    cancel_job_ids = [
        sibling.job_id for sibling in siblings
        if sibling.job_id and not sibling.filename
        and (choice != 'improved' or sibling.id != candidate.id)
    ]
    db.session.rollback()
    for job_id in cancel_job_ids:
        try:
            from ..job_queue import queue_manager
            queue_manager.cancel_job(job_id, str(user_id), 'image')
        except Exception:
            logger.exception('image reconstruction: failed to cancel job %s', job_id)
    db.session.rollback()

    from sqlalchemy import text
    try:
        db.session.execute(text('BEGIN IMMEDIATE'))
        source, candidate, siblings = _load_pair()
        if source is None:
            db.session.rollback()
            return None
        already = _image_improvement_resolved_choice(source, siblings, candidate.id)
        if already:
            if already.startswith('improved:'):
                raise RuntimeError(
                    f'image reconstruction was already resolved with candidate {already.split(":", 1)[1]}')
            if already != choice:
                raise RuntimeError(f'image reconstruction was already resolved as {already}')
        else:
            from . import curation_history
            fields = ('status', 'watermark_state', 'watermark_bbox', 'watermark_regions')
            affected = [source, *siblings]
            before = {row.id: curation_history.snapshot(row, fields) for row in affected}
            cancelled = set(cancel_job_ids)
            for row in siblings:
                if (row.job_id in cancelled and not row.filename
                        and before[row.id].get('status') == 'pending'):
                    before[row.id]['status'] = 'failed'
            if choice == 'improved' and not candidate.filename:
                raise ValueError('the reconstructed candidate is not ready')
            source.status = 'keep' if choice == 'original' else 'reject'
            for sibling in siblings:
                sibling.status = ('keep' if choice == 'improved'
                                  and sibling.id == candidate.id else 'reject')
                if sibling.status == 'reject':
                    _clear_watermark_metadata(sibling)
            if source.status == 'reject':
                _clear_watermark_metadata(source)
            batch_id = curation_history.new_batch_id()
            for row in affected:
                curation_history.record(
                    user_id, row, f'image_improvement:{choice}', before[row.id],
                    curation_history.snapshot(row, fields), batch_id=batch_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    if cancel_job_ids:
        _sync_generate_activity(dataset_id)
    return {'choice': choice,
            'source': {'id': source.id, 'status': source.status},
            'candidate': {'id': candidate.id, 'status': candidate.status}}


def set_image_caption(user_id, image_id, caption):
    img = _owned_image(user_id, image_id)
    if not img:
        return False
    from . import curation_history
    before = curation_history.snapshot(img, ('caption',))
    img.caption = (caption or '').strip()[:CAPTION_MAX_CHARS] or None
    curation_history.record(
        user_id, img, 'caption', before,
        curation_history.snapshot(img, ('caption',)))
    db.session.commit()
    return True


def _crop_resize_file(path, x, y, w, h, size=1024, dst=None):
    """Crop the file at `path` to (x,y,w,h) and resize the crop so its LONG side
    equals `size`, PRESERVING the box's aspect ratio: a square box keeps the
    historical size x size output, a 2:3 box yields 683x1024 — no padding, no
    distortion (ai-toolkit buckets handle non-square training images). Writes to
    `dst` (default: overwrite `path`). Passing a distinct `dst` lets the reference
    crop read the untouched full-frame ORIGINAL and write the derived crop — so a
    re-crop can widen back out instead of only tightening the previous crop.

    Returns (ok, upscale_ratio) — ratio is size / long_side_of_box (>1 means the
    box was smaller than `size` and got enlarged), or None on failure."""
    if not os.path.exists(path):
        return False, None
    with Image.open(path) as opened, opened.convert('RGB') as src:
        box = (max(0, int(x)), max(0, int(y)), min(src.width, int(x + w)), min(src.height, int(y + h)))
        if box[2] <= box[0] or box[3] <= box[1]:
            return False, None
        bw, bh = box[2] - box[0], box[3] - box[1]
        if bw >= bh:
            out_w, out_h = size, max(1, round(size * bh / bw))
        else:
            out_w, out_h = max(1, round(size * bw / bh)), size
        scale = size / max(bw, bh)
        out = io.BytesIO()
        with src.crop(box) as cropped, cropped.resize((out_w, out_h), Image.LANCZOS) as resized:
            resized.save(out, 'WEBP', quality=92)
    with open(dst or path, 'wb') as fh:
        fh.write(out.getvalue())
    return True, scale


def crop_image(user_id, image_id, x, y, w, h):
    """Crop a dataset image to (x,y,w,h), resized to 1024 (no pad). Returns bool."""
    img = _owned_image(user_id, image_id)
    if not img or not img.filename:
        return False
    if _is_unresolved_image_improvement_row(img):
        raise ValueError('resolve the reconstruction comparison before cropping either version')
    ok, scale = _crop_resize_file(_img_path(img), x, y, w, h)
    if ok:
        _clear_watermark_metadata(img)
        img.upscale_ratio = scale
        db.session.commit()
    return ok


@trash.serialized_transaction
def delete_image(user_id, image_id):
    """Move a dataset image to the recoverable app trash.

    The row remains as a hidden tombstone so restoring the files can also
    restore captions, curation, analysis, and provenance without lossy JSON
    reconstruction. Pending generation jobs are cancelled first.
    """
    img = _owned_image(user_id, image_id)
    if not img:
        return False
    if img.derivation_kind in _SMALL_IMAGE_DERIVATIONS:
        raise ValueError('resolve the small-image rescue pair before cleanup')
    if _has_image_improvement_pair(img):
        raise ValueError('reconstruction provenance pairs cannot be deleted independently')
    if img.status == 'pending' and not img.filename and img.job_id:
        try:
            from ..job_queue import queue_manager
            queue_manager.cancel_job(img.job_id, str(user_id), 'image')
        except Exception:
            pass
    from . import trash
    paths = []
    if img.filename:
        path = Path(_img_path(img))
        if path.exists():
            paths.append(path)
    if img.original_filename:
        path = Path(_dataset_dir(img.dataset_id)) / img.original_filename
        if path.exists() and path not in paths:
            paths.append(path)
    metadata = {
        'kind': 'dataset_image',
        'image_id': img.id,
        'dataset_id': img.dataset_id,
        'previous_status': img.status,
        'label': img.source_name or img.variation_label or img.filename or f'image {img.id}',
    }
    if paths:
        trashed = trash.send_paths_to_trash(
            paths, context=f'dataset-{img.dataset_id}-image-{img.id}', metadata=metadata)
    else:
        trashed = trash.store_bytes(
            'image-record.json', json.dumps({'image_id': img.id}).encode('utf-8'),
            context=f'dataset-{img.dataset_id}-image-{img.id}', metadata=metadata)
    img.status = 'trashed'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            file_meta = trash.entry_metadata(trashed['id']).get('files') or []
            if file_meta and all(item.get('original_path') for item in file_meta):
                trash.restore_entry(trashed['id'])
            else:
                trash.remove_entry(trashed['id'])
        except Exception:
            logger.exception('could not roll back image trash entry %s', trashed['id'])
        raise
    return True


@trash.serialized_transaction
def restore_trashed_image(user_id, entry_id):
    """Restore one soft-deleted image and its original bytes from Trash."""
    from . import trash
    metadata = trash.entry_metadata(entry_id)
    if metadata.get('kind') != 'dataset_image':
        raise ValueError('not a dataset image trash entry')
    try:
        image_id = int(metadata.get('image_id'))
    except (TypeError, ValueError):
        raise ValueError('trash entry has no valid image id')
    img = db.session.get(FaceDatasetImage, image_id)
    ds = db.session.get(FaceDataset, img.dataset_id) if img else None
    if (not img or not ds or ds.trashed_at is not None
            or str(ds.user_id) != str(user_id) or img.status != 'trashed'):
        raise ValueError('the original dataset image is no longer restorable')
    dataset_root = (cfg.dataset_images_root() / str(ds.id)).resolve()
    files = metadata.get('files') or []
    for item in files:
        original = item.get('original_path')
        if original and not Path(original).resolve(strict=False).is_relative_to(dataset_root):
            raise ValueError('trash restore target is outside the dataset')
    restored_metadata = None
    if files and all(item.get('original_path') for item in files):
        restored_metadata = trash.restore_entry(entry_id, consume=False)['metadata']
    previous = metadata.get('previous_status')
    img.status = previous if previous in _VALID_STATUS else 'reject'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if restored_metadata is not None:
            try:
                trash.rollback_restored_entry(entry_id, restored_metadata)
            except Exception:
                logger.exception('could not roll back image restore %s', entry_id)
        raise
    try:
        trash.remove_entry(entry_id)
    except OSError:
        logger.exception('restored image but could not consume trash entry %s', entry_id)
    return img


@trash.serialized_transaction
def restore_regenerated_image(user_id, entry_id):
    """Swap a prior generated version back into its stable image row."""
    metadata = trash.entry_metadata(entry_id)
    if metadata.get('kind') != 'regenerated_image':
        raise ValueError('not a regenerated image trash entry')
    try:
        image_id = int(metadata.get('image_id'))
    except (TypeError, ValueError):
        raise ValueError('regenerated image entry has no valid image id')
    previous = metadata.get('previous_state')
    if not isinstance(previous, dict) or not previous.get('filename'):
        raise ValueError('regenerated image entry has no restorable row state')
    img = db.session.get(FaceDatasetImage, image_id)
    ds = db.session.get(FaceDataset, img.dataset_id) if img else None
    if (img is None or ds is None or ds.trashed_at is not None
            or str(ds.user_id) != str(user_id)):
        raise ValueError('the generated image is no longer restorable')
    dataset_root = Path(_dataset_dir(ds.id)).resolve()
    for item in metadata.get('files') or []:
        original = item.get('original_path')
        if original and not Path(original).resolve(strict=False).is_relative_to(dataset_root):
            raise ValueError('trash restore target is outside the dataset')

    replacement_entry = None
    current_path = ((dataset_root / Path(img.filename).name).resolve(strict=False)
                    if img.filename else None)
    if (current_path is not None and current_path.is_relative_to(dataset_root)
            and current_path.is_file() and not current_path.is_symlink()):
        replacement_entry = trash.send_paths_to_trash(
            [current_path], context=f'dataset-{img.dataset_id}-regeneration', metadata={
                'kind': 'regenerated_image',
                'dataset_id': img.dataset_id,
                'image_id': img.id,
                'previous_state': _replacement_state(img),
                'label': img.variation_label or current_path.name,
            })
    restored = trash.restore_entry(entry_id, consume=False)
    try:
        for field in _REPLACEMENT_STATE_FIELDS:
            if field in previous:
                setattr(img, field, previous[field])
        img.job_id = None
        img.fail_reason = None
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            trash.rollback_restored_entry(entry_id, restored['metadata'])
            if replacement_entry is not None:
                trash.restore_entry(replacement_entry['id'])
        except Exception:
            logger.exception('could not roll back regenerated version restore %s', entry_id)
        raise
    try:
        trash.remove_entry(entry_id)
    except OSError:
        logger.exception('restored generated version but could not consume %s', entry_id)
    return img


@trash.serialized_transaction
def delete_dataset(user_id, dataset_id):
    """Move a complete dataset backup and source folder to recoverable Trash.

    Training runs, exported trainer folders, and deployed LoRAs are deliberately
    retained.  This is a soft delete: restoring the dataset must restore the
    complete usable project, not just its source images and database rows.
    """
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return False
    # Build the portable DB+file snapshot before mutating either source. The raw
    # directory is moved into the same trash entry as a second recovery layer.
    # Write the ZIP directly to the temporary file: a corpus may be gigabytes,
    # so materialising the entire archive as one ``bytes`` value is unsafe.
    from . import trash
    dsdir = Path(_dataset_dir(dataset_id))
    cfg._data_dir().mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        prefix=f'dataset-{dataset_id}-', suffix='.zip',
        dir=cfg._data_dir(), delete=False)
    archive_path = Path(tmp.name)
    try:
        build_backup_zip(user_id, dataset_id, destination=tmp)
        tmp.flush()
        os.fsync(tmp.fileno())
    except Exception:
        tmp.close()
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        tmp.close()

    # Cancel queue-backed work before moving the dataset folder. API-backed
    # requests cannot be recalled, so _commit_generated_replacement also checks
    # the dataset tombstone after this serialized transaction completes.
    imgs = FaceDatasetImage.query.filter_by(dataset_id=dataset_id).all()
    for img in imgs:
        if img.status == 'pending' and not img.filename and img.job_id:
            try:
                from ..job_queue import queue_manager
                queue_manager.cancel_job(img.job_id, str(user_id), 'image')
            except Exception:
                logger.exception('could not cancel dataset image job %s', img.job_id)
    targets = [archive_path]
    if dsdir.exists():
        targets.append(dsdir)
    try:
        trashed = trash.send_paths_to_trash(
            targets, context=f'dataset-{dataset_id}-{ds.name}', metadata={
                'kind': 'dataset_backup',
                'dataset_id': dataset_id,
                'dataset_name': ds.name,
                'backup_name': archive_path.name,
            })
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    ds.trashed_at = datetime.now(timezone.utc)
    ds.trash_entry_id = trashed['id']
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            trash.restore_entry(trashed['id'])
            archive_path.unlink(missing_ok=True)
        except Exception:
            logger.exception('could not roll back dataset trash entry %s', trashed['id'])
        raise
    return True


@trash.serialized_transaction
def restore_trashed_dataset(user_id, entry_id):
    """Restore a soft-deleted dataset, preserving its stable database graph."""
    from . import trash
    metadata = trash.entry_metadata(entry_id)
    if metadata.get('kind') != 'dataset_backup':
        raise ValueError('not a dataset backup trash entry')
    backup_name = metadata.get('backup_name')
    if not isinstance(backup_name, str) or Path(backup_name).name != backup_name:
        raise ValueError('dataset backup entry is invalid')
    try:
        dataset_id = int(metadata.get('dataset_id'))
    except (TypeError, ValueError):
        raise ValueError('dataset backup entry has no valid dataset id')
    dataset = db.session.get(FaceDataset, dataset_id)
    if dataset is not None:
        if str(dataset.user_id) != str(user_id) or dataset.trashed_at is None:
            raise ValueError('the dataset is not restorable from this entry')
        result = trash.restore_entry(entry_id, consume=False)
        dataset.trashed_at = None
        dataset.trash_entry_id = None
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            try:
                trash.rollback_restored_entry(entry_id, result['metadata'])
            except Exception:
                logger.exception('could not roll back dataset restore %s', entry_id)
            raise
        for item in result['metadata'].get('files') or []:
            if item.get('stored_name') != backup_name or not item.get('original_path'):
                continue
            try:
                Path(item['original_path']).unlink(missing_ok=True)
            except OSError:
                logger.exception('restored dataset but could not remove backup %s',
                                 item['original_path'])
        try:
            trash.remove_entry(entry_id)
        except OSError:
            logger.exception('restored dataset but could not consume trash entry %s',
                             entry_id)
        return dataset

    # Disaster-recovery fallback for a trash folder copied alongside a lost DB.
    with trash.open_entry_file(entry_id, backup_name) as backup:
        restored = import_backup_zip(user_id, backup)
    try:
        trash.remove_entry(entry_id)
    except OSError:
        logger.exception('restored backup but could not consume trash entry %s', entry_id)
    return restored


def purge_trashed_record(user_id, metadata, entry_id) -> None:
    """Hard-delete the tombstone owned by an entry before Empty Trash.

    Training/cloud provenance intentionally survives dataset deletion, but the
    live dataset graph must not retain rows that can no longer be restored.
    """
    kind = metadata.get('kind')
    from ..models import CurationEvent, LoraTestImage
    if kind == 'dataset_image':
        try:
            image_id = int(metadata.get('image_id'))
        except (TypeError, ValueError):
            raise ValueError('dataset image trash entry has no valid image id')
        image = db.session.get(FaceDatasetImage, image_id)
        if image is None:
            return
        dataset = db.session.get(FaceDataset, image.dataset_id)
        if (dataset is None or str(dataset.user_id) != str(user_id)
                or image.status != 'trashed'):
            raise ValueError('dataset image tombstone is not purgeable')
        CurationEvent.query.filter_by(image_id=image.id).delete(
            synchronize_session=False)
        db.session.delete(image)
    elif kind == 'dataset_backup':
        try:
            dataset_id = int(metadata.get('dataset_id'))
        except (TypeError, ValueError):
            raise ValueError('dataset backup entry has no valid dataset id')
        dataset = db.session.get(FaceDataset, dataset_id)
        if dataset is None:
            return
        if (str(dataset.user_id) != str(user_id)
                or dataset.trashed_at is None
                or dataset.trash_entry_id != entry_id):
            raise ValueError('dataset tombstone is not purgeable')
        CurationEvent.query.filter_by(dataset_id=dataset.id).delete(
            synchronize_session=False)
        LoraTestImage.query.filter_by(dataset_id=dataset.id).delete(
            synchronize_session=False)
        FaceDatasetImage.query.filter_by(dataset_id=dataset.id).delete(
            synchronize_session=False)
        db.session.delete(dataset)
    else:
        return
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def cancel_pending(user_id, dataset_id):
    """Cancel all in-flight (pending) generations of a dataset and drop their
    rows. Returns the number cancelled."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return 0
    # Only in-flight generations (pending AND no result file yet) - leave
    # completed-but-uncurated images alone.
    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id, status='pending')
            .filter(FaceDatasetImage.filename.is_(None)).all())
    n = 0
    for img in rows:
        if img.job_id:  # Klein rows only - API rows never carry a job_id
            try:
                from ..job_queue import queue_manager
                queue_manager.cancel_job(img.job_id, str(user_id), 'image')
            except Exception:
                pass
        if img.derivation_kind in (KLEIN_SMALL_IMAGE, KLEIN_IMAGE_IMPROVE):
            # Preserve the review pair and its original file. A cancelled rescue
            # or reconstruction is equivalent to an engine failure: the source
            # can still be admitted through the dedicated comparison.
            img.status = 'failed'
            img.fail_reason = ('Klein small-image rescue was cancelled.'
                               if img.derivation_kind == KLEIN_SMALL_IMAGE
                               else 'Image reconstruction was cancelled.')
        else:
            db.session.delete(img)
        n += 1
    db.session.commit()
    # Stop deleted the in-flight rows: clear the Klein 'generate' indicator now
    # (its completion callbacks won't fire for cancelled jobs). An API batch's own
    # begin/end entry is untouched — its worker unwinds and end()s on its own.
    _sync_generate_activity(dataset_id)
    return n


def purge_unused(user_id, dataset_id):
    """Move all rejected and failed images to recoverable Trash."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return 0
    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id)
            .filter(FaceDatasetImage.status.in_(('reject', 'failed')))
            .filter(FaceDatasetImage.derivation_kind.notin_(_SMALL_IMAGE_DERIVATIONS)
                    | FaceDatasetImage.derivation_kind.is_(None)).all())
    rows = [row for row in rows if not _has_image_improvement_pair(row)]
    n = 0
    for img in rows:
        if delete_image(user_id, img.id):
            n += 1
    return n


# --- Sauvegarde / restauration complète d'un dataset ---------------------------
# ZIP portable (≠ export d'entraînement) : manifest + réglages + images dérivées,
# exact uploaded originals, and statuts/captions/scores — for archiving or moving
# a dataset between machines.
BACKUP_FORMAT = 'lds-dataset-backup'
BACKUP_VERSION = 1
# Each imported row can contribute one normalized image plus one exact original.
# The corpus itself has no lifetime cap, so backups must not become the smaller
# hidden ceiling. The 2 GB uncompressed guard remains authoritative.
_BACKUP_MAX_FILES = 10050
_BACKUP_MAX_ROWS = 5000
_BACKUP_MAX_BYTES = 2 * 1024 * 1024 * 1024   # 2 GB uncompressed (zip-bomb guard)
_BACKUP_MAX_METADATA_BYTES = 64 * 1024 * 1024
_BACKUP_MAX_TEXT_VALUE_BYTES = 1024 * 1024
_BACKUP_NAME_RE = re.compile(
    r'^[\w.-]+\.(webp|jpg|jpeg|png|bmp|gif|tif|tiff|avif|bin)$', re.IGNORECASE)

# Champs snapshotés tels quels par ligne image (job_id/klein_model exclus : liés
# à la machine source — un backup restauré ne peut pas « regénérer »).
_BACKUP_IMG_FIELDS = ('filename', 'source', 'framing', 'variation_label', 'status',
                      'caption', 'variation_prompt', 'face_score', 'face_state',
                      'watermark_state', 'watermark_bbox', 'watermark_regions',
                      'parent_image_id', 'derivation_kind',
                      'fail_reason', 'source_name', 'original_filename',
                      'source_sha256', 'analysis_json',
                      'training_usefulness', 'coverage_value', 'upscale_ratio',
                      'perceptual_hash', 'duplicate_of_id', 'anchor_decision',
                      'coverage_json', 'generation_anchor_ids',
                      'coverage_provenance', 'source_rights',
                      'generation_anchor_metadata', 'generation_engine',
                      'generation_gap_ids', 'generation_provenance')


def build_backup_zip(user_id, dataset_id, *, destination=None):
    """Self-contained backup of one dataset: manifest.json (settings) +
    images.json (rows) + ref/ + images/ files. Ordinary rows without a file are
    skipped, but exclusive-review metadata rows are retained so their pair can
    never become orphaned after restore."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    dsdir = _dataset_dir(dataset_id)
    from sqlalchemy import or_
    rows = (FaceDatasetImage.query.filter_by(dataset_id=dataset_id)
            .filter(FaceDatasetImage.status != 'trashed')
            .filter(or_(FaceDatasetImage.filename.isnot(None),
                        FaceDatasetImage.derivation_kind.in_(_EXCLUSIVE_DERIVATIONS)))
            .all())
    manifest = {
        'format': BACKUP_FORMAT, 'version': BACKUP_VERSION,
        'name': ds.name, 'trigger_word': ds.trigger_word,
        'kind': ds.kind, 'fidelity': ds.fidelity,
        'coverage_profile': ds.coverage_profile,
        'coverage_targets': ds.coverage_targets,
        'concept_desc': ds.concept_desc, 'concept_terms': ds.concept_terms,
        'train_type': ds.train_type, 'train_base_model': ds.train_base_model,
        'train_variant': ds.train_variant, 'train_vae_path': ds.train_vae_path,
        'train_te_path': ds.train_te_path, 'train_settings': ds.train_settings,
        'best_settings': ds.best_settings,
        'ref_filename': ds.ref_filename, 'ref_original_filename': ds.ref_original_filename,
        'ref_extra_filenames': ds.ref_extra_filenames,
    }
    # backup_image_id is archive-local only. It lets restore remap parent_image_id
    # to the newly allocated row ids instead of retaining ids from the source DB.
    images_meta = []
    for img in rows:
        values = {field: getattr(img, field) for field in _BACKUP_IMG_FIELDS}
        if values.get('original_filename'):
            # ZIP names are POSIX paths. Normalize this one nested DB path too,
            # otherwise a Windows-created backup loses originals on macOS/Linux.
            values['original_filename'] = values['original_filename'].replace('\\', '/')
        images_meta.append({'backup_image_id': img.id, **values})
    buf = destination if destination is not None else io.BytesIO()
    dataset_root = Path(dsdir).resolve()
    written_arcnames = set()
    written_relatives = set()

    def add_file(z, relative, arcname):
        if not isinstance(relative, str) or not relative:
            return
        candidate = Path(dsdir) / relative
        try:
            candidate.resolve().relative_to(dataset_root)
        except (OSError, ValueError):
            logger.warning('dataset %s: unsafe backup path skipped: %s', dataset_id,
                           relative)
            return
        normalized_relative = candidate.resolve()
        if (candidate.is_symlink() or not candidate.is_file()
                or arcname in written_arcnames
                or normalized_relative in written_relatives):
            return
        z.write(candidate, arcname)
        written_arcnames.add(arcname)
        written_relatives.add(normalized_relative)

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=1))
        z.writestr('images.json', json.dumps(images_meta, ensure_ascii=False, indent=1))
        ref_names = [n for n in (ds.ref_filename, ds.ref_original_filename) if n]
        try:
            ref_names += list(json.loads(ds.ref_extra_filenames or '[]'))
        except ValueError:
            pass
        for n in dict.fromkeys(ref_names):
            add_file(z, n, f'ref/{n}')
        for img in rows:
            if not img.filename:
                continue   # metadata-only small-rescue candidate
            add_file(z, img.filename, f'images/{img.filename}')
        for img in rows:
            if not img.original_filename:
                continue
            add_file(z, img.original_filename,
                     f'originals/{os.path.basename(img.original_filename)}')
    return buf if destination is not None else buf.getvalue()


def import_backup_zip(user_id, zip_source):
    """Restore a backup as a NEW dataset (never merges into an existing one).
    Hardened: manifest format/version check, per-entry filename whitelist (no
    separators/traversal), file-count and uncompressed-size caps. Returns the
    created FaceDataset."""
    try:
        source = io.BytesIO(zip_source) if isinstance(zip_source, (bytes, bytearray)) else zip_source
        z = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError, TypeError):
        raise ValueError('not a zip file')
    state = {}
    try:
        return _import_backup_archive(user_id, z, state)
    except Exception:
        # create_dataset commits to allocate its id. Any later extraction or DB
        # failure must remove that partial import instead of leaving a visible,
        # half-restored dataset and untracked files behind.
        db.session.rollback()
        dataset_id = state.get('dataset_id')
        if dataset_id is not None:
            try:
                FaceDatasetImage.query.filter_by(dataset_id=dataset_id).delete(
                    synchronize_session=False)
                dataset = db.session.get(FaceDataset, dataset_id)
                if dataset is not None:
                    db.session.delete(dataset)
                db.session.commit()
                shutil.rmtree(_dataset_dir(dataset_id), ignore_errors=True)
            except Exception:
                db.session.rollback()
                logger.exception('could not clean up failed backup import dataset %s',
                                 dataset_id)
        raise
    finally:
        z.close()


def _import_backup_archive(user_id, z, state):
    archive_infos = z.infolist()
    names = [info.filename for info in archive_infos]
    if len(names) != len(set(names)):
        raise ValueError('backup contains duplicate archive paths')
    if len(archive_infos) > _BACKUP_MAX_FILES + 2:
        raise ValueError(f'too many files in backup (max {_BACKUP_MAX_FILES + 2})')
    if any(info.flag_bits & 0x1 for info in archive_infos):
        raise ValueError('encrypted backup entries are not supported')
    if sum(info.file_size for info in archive_infos) > _BACKUP_MAX_BYTES:
        raise ValueError('backup too large (max 2 GB uncompressed)')
    by_name = {info.filename: info for info in archive_infos}
    metadata_infos = [by_name.get('manifest.json'), by_name.get('images.json')]
    if any(info is None for info in metadata_infos):
        raise ValueError(
            'not a dataset backup (manifest.json/images.json missing or invalid)')
    if sum(info.file_size for info in metadata_infos) > _BACKUP_MAX_METADATA_BYTES:
        raise ValueError('backup metadata is too large')
    try:
        manifest = json.loads(z.read('manifest.json').decode('utf-8'))
        images_meta = json.loads(z.read('images.json').decode('utf-8'))
    except (KeyError, ValueError, UnicodeError, zipfile.BadZipFile, RuntimeError):
        raise ValueError('not a dataset backup (manifest.json/images.json missing or invalid)')
    if not isinstance(manifest, dict):
        raise ValueError('invalid backup manifest')
    if manifest.get('format') != BACKUP_FORMAT:
        raise ValueError('not a dataset backup')
    try:
        raw_version = manifest.get('version') or 0
        if isinstance(raw_version, bool):
            raise ValueError
        version = int(raw_version)
    except (TypeError, ValueError):
        raise ValueError('invalid backup version')
    if version < 1:
        raise ValueError('invalid backup version')
    if version > BACKUP_VERSION:
        raise ValueError('backup made by a newer version of the app - update first')
    for field, value in manifest.items():
        if field == 'version':
            continue
        if value is not None and not isinstance(value, str):
            raise ValueError(f'invalid backup manifest field: {field}')
        if (isinstance(value, str)
                and len(value.encode('utf-8')) > _BACKUP_MAX_TEXT_VALUE_BYTES):
            raise ValueError(f'backup manifest field is too large: {field}')
    if manifest.get('kind') not in (None, '', 'character', 'concept', 'style'):
        raise ValueError('invalid backup dataset kind')
    if manifest.get('fidelity') not in (None, '', 'face', 'body'):
        raise ValueError('invalid backup dataset fidelity')
    if manifest.get('train_type') not in (None, '', *TRAIN_TYPES):
        raise ValueError('invalid backup training family')
    if manifest.get('coverage_profile') not in (
            None, '', *COVERAGE_PROFILES):
        raise ValueError('invalid backup coverage profile')
    if manifest.get('coverage_targets'):
        try:
            parsed_targets = json.loads(manifest['coverage_targets'])
            clean_targets = normalize_coverage_targets(parsed_targets)
        except (TypeError, ValueError):
            raise ValueError('invalid backup coverage targets')
        manifest['coverage_targets'] = json.dumps(
            clean_targets, ensure_ascii=False, sort_keys=True)
    if not isinstance(images_meta, list):
        raise ValueError('invalid backup image metadata')
    if len(images_meta) > _BACKUP_MAX_ROWS:
        raise ValueError(f'too many image rows in backup (max {_BACKUP_MAX_ROWS})')
    seen_backup_ids = set()
    rescue_sources = set()
    rescue_parent_counts = {}
    for meta in images_meta:
        if not isinstance(meta, dict):
            raise ValueError('invalid backup image metadata')
        # Early version-1 fixtures did not stamp source; preserve their
        # historical generated-row default while validating all new backups.
        if meta.get('source') is None:
            meta['source'] = 'generated'
        for field in _BACKUP_IMG_FIELDS:
            value = meta.get(field)
            if field in ('parent_image_id', 'duplicate_of_id'):
                valid_type = (value is None or (
                    isinstance(value, int) and not isinstance(value, bool) and value > 0))
            elif field in ('face_score', 'upscale_ratio'):
                valid_type = (value is None or (
                    isinstance(value, (int, float)) and not isinstance(value, bool)))
            else:
                valid_type = value is None or isinstance(value, str)
            if not valid_type:
                raise ValueError(f'invalid backup image field: {field}')
            if (isinstance(value, str)
                    and len(value.encode('utf-8')) > _BACKUP_MAX_TEXT_VALUE_BYTES):
                raise ValueError(f'backup image field is too large: {field}')
        backup_id = meta.get('backup_image_id')
        if backup_id is not None:
            if isinstance(backup_id, bool) or not isinstance(backup_id, int) or backup_id <= 0:
                raise ValueError('invalid backup image id')
            if backup_id in seen_backup_ids:
                raise ValueError('duplicate backup image id')
            seen_backup_ids.add(backup_id)
        derivation = meta.get('derivation_kind')
        if derivation not in (None, SMALL_IMAGE_SOURCE, KLEIN_SMALL_IMAGE,
                              KLEIN_IMAGE_IMPROVE):
            raise ValueError('invalid image derivation in backup')
        if derivation == SMALL_IMAGE_SOURCE:
            if backup_id is None or meta.get('parent_image_id') is not None:
                raise ValueError('invalid small-image source provenance')
            rescue_sources.add(backup_id)
        elif derivation == KLEIN_SMALL_IMAGE:
            parent_id = meta.get('parent_image_id')
            if backup_id is None or isinstance(parent_id, bool) or not isinstance(parent_id, int):
                raise ValueError('invalid Klein rescue provenance')
            rescue_parent_counts[parent_id] = rescue_parent_counts.get(parent_id, 0) + 1
            if rescue_parent_counts[parent_id] > 1:
                raise ValueError('multiple Klein rescue candidates for one source')
        elif derivation == KLEIN_IMAGE_IMPROVE:
            parent_id = meta.get('parent_image_id')
            # New schemas use ON DELETE SET NULL for a hard-removed legacy
            # source. A surviving reconstruction with pixels is intentionally
            # accepted below and restored as an ordinary generated image.
            if (backup_id is None or isinstance(parent_id, bool)
                    or (parent_id is not None and not isinstance(parent_id, int))):
                raise ValueError('invalid reconstruction provenance')
        if meta.get('status') not in _VALID_STATUS:
            raise ValueError('invalid image status in backup')
        if meta.get('source') not in ('generated', 'import', 'upload'):
            raise ValueError('invalid image source in backup')
        if meta.get('framing') not in (None, 'face', 'bust', 'body', 'back', 'unknown'):
            raise ValueError('invalid image framing in backup')
        if meta.get('training_usefulness') not in (None, 'green', 'amber', 'red'):
            raise ValueError('invalid image usefulness in backup')
        if meta.get('coverage_value') not in (None, 'green', 'amber', 'unknown'):
            raise ValueError('invalid image coverage value in backup')
        if meta.get('anchor_decision') not in (None, '', 'auto', 'pinned', 'excluded'):
            raise ValueError('invalid image anchor decision in backup')
        if meta.get('watermark_state') not in (
                None, 'none', 'detected', 'dismissed', 'cleaned', 'failed'):
            raise ValueError('invalid image watermark state in backup')
    if any(parent_id not in rescue_sources for parent_id in rescue_parent_counts):
        raise ValueError('Klein rescue candidate has no valid source')
    infos = [i for i in archive_infos
             if i.filename.startswith(('ref/', 'images/', 'originals/'))]
    if len(infos) > _BACKUP_MAX_FILES:
        raise ValueError(f'too many files in backup (max {_BACKUP_MAX_FILES})')
    if sum(i.file_size for i in infos) > _BACKUP_MAX_BYTES:
        raise ValueError('backup too large (max 2 GB uncompressed)')
    destinations = []
    for info in infos:
        prefix, _, tail = info.filename.partition('/')
        base = os.path.basename(info.filename)
        if (prefix not in ('ref', 'images', 'originals') or not tail
                or not _BACKUP_NAME_RE.match(base) or base != tail):
            continue
        destinations.append(base if prefix in ('ref', 'images')
                            else os.path.join(prefix, base))
    if len(destinations) != len(set(destinations)):
        raise ValueError('backup file destinations collide')
    name = (manifest.get('name') or 'Restored dataset')[:100]
    trigger = (manifest.get('trigger_word') or 'restored')[:60]
    ds = create_dataset(user_id, name, trigger, kind=manifest.get('kind'),
                        concept_desc=manifest.get('concept_desc'),
                        train_type=manifest.get('train_type'))
    state['dataset_id'] = ds.id
    for field in ('concept_terms', 'train_base_model', 'train_variant',
                  'train_vae_path', 'train_te_path', 'train_settings', 'best_settings',
                  'coverage_profile', 'coverage_targets',
                  'ref_filename', 'ref_original_filename', 'ref_extra_filenames', 'fidelity'):
        setattr(ds, field, manifest.get(field))
    dsdir = _dataset_dir(ds.id)
    os.makedirs(dsdir, exist_ok=True)
    extracted = {'ref': set(), 'images': set(), 'originals': set()}
    for info in infos:
        prefix, _, tail = info.filename.partition('/')
        base = os.path.basename(info.filename)
        if (prefix not in ('ref', 'images', 'originals') or not tail
                or not _BACKUP_NAME_RE.match(base) or base != tail):
            continue   # nested path or weird name -> skip, never traverse
        # Legacy backup layout restores refs and normalized images at the
        # dataset root. Exact uploaded originals are the only nested payload.
        relative = base if prefix in ('ref', 'images') else os.path.join(prefix, base)
        destination = os.path.join(dsdir, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with z.open(info) as src, open(destination, 'wb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        extracted[prefix].add(base)
    n_rows = 0
    restored_rows = []
    valid_source_ids = {
        meta.get('backup_image_id') for meta in images_meta
        if isinstance(meta, dict)
        and meta.get('derivation_kind') == SMALL_IMAGE_SOURCE
        and meta.get('filename') in extracted['images']
    }
    valid_image_ids = {
        meta.get('backup_image_id') for meta in images_meta
        if isinstance(meta, dict) and meta.get('filename') in extracted['images']
    }
    for meta in images_meta:
        if not isinstance(meta, dict):
            continue
        fn = meta.get('filename')
        derivation = meta.get('derivation_kind')
        is_candidate = derivation in (KLEIN_SMALL_IMAGE, KLEIN_IMAGE_IMPROVE)
        if fn and fn not in extracted['images']:
            continue
        if not fn and not is_candidate:
            continue   # in-flight exclusive-review candidates are metadata-only
        valid_parents = (valid_source_ids if derivation == KLEIN_SMALL_IMAGE
                         else valid_image_ids)
        parent_valid = not is_candidate or meta.get('parent_image_id') in valid_parents
        if derivation == KLEIN_SMALL_IMAGE and not parent_valid:
            continue   # a small-rescue candidate has no standalone meaning
        if derivation == KLEIN_IMAGE_IMPROVE and not parent_valid and not fn:
            continue   # metadata-only orphan has neither source nor recoverable pixels
        values = {f: meta.get(f) for f in _BACKUP_IMG_FIELDS
                  if f not in ('filename', 'parent_image_id', 'duplicate_of_id')}
        if derivation == KLEIN_IMAGE_IMPROVE and not parent_valid:
            # Old releases allowed deleting a reconstruction source independently.
            # Preserve the surviving pixels as an ordinary generated row so the
            # restored backup remains usable and the row can be curated/deleted.
            values['derivation_kind'] = None
            values['fail_reason'] = (values.get('fail_reason')
                                     or 'Recovered from orphaned reconstruction provenance.')
        original_filename = values.get('original_filename')
        if isinstance(original_filename, str):
            original_filename = original_filename.replace('\\', '/')
            values['original_filename'] = original_filename
        if (not isinstance(original_filename, str)
                or not original_filename.startswith('originals/')
                or Path(original_filename).name not in extracted['originals']):
            values['original_filename'] = None
        if is_candidate and not fn and values.get('status') in ('pending', 'keep'):
            values['status'] = 'failed'
            values['fail_reason'] = (
                'Klein rescue was in flight when this backup was created; '
                'the original image is preserved, but the job must be started again.'
                if derivation == KLEIN_SMALL_IMAGE else
                'Image reconstruction was in flight when this backup was created; '
                'the source is preserved and can still be selected in review.'
            )
        img = FaceDatasetImage(dataset_id=ds.id,
                               **values,
                               filename=fn)
        db.session.add(img)
        restored_rows.append((img, meta))
        n_rows += 1
    # Allocate new ids first, then restore the graph strictly within this backup.
    # A missing/skipped parent clears the relationship rather than pointing at an
    # unrelated row that happens to reuse the old numeric id.
    db.session.flush()
    id_map = {meta.get('backup_image_id'): img.id for img, meta in restored_rows
              if meta.get('backup_image_id') is not None}
    for img, meta in restored_rows:
        img.parent_image_id = id_map.get(meta.get('parent_image_id'))
        img.duplicate_of_id = id_map.get(meta.get('duplicate_of_id'))
        # Imported anchor ids are local to the source database. Keep only ids
        # that were restored into this new dataset and remap them to new rows.
        old_anchor_ids = _parse_generation_anchor_ids(img.generation_anchor_ids)
        img.generation_anchor_ids = json.dumps(
            [id_map[old_id] for old_id in old_anchor_ids if old_id in id_map])
        old_metadata = _parse_generation_anchor_metadata(img.generation_anchor_metadata)
        remapped_metadata = []
        for anchor in old_metadata:
            old_id = anchor.get('image_id')
            if old_id is not None:
                if old_id not in id_map:
                    continue
                anchor = {**anchor, 'image_id': id_map[old_id]}
            remapped_metadata.append(anchor)
        img.generation_anchor_metadata = json.dumps(remapped_metadata, ensure_ascii=False)
    # Refs referenced by the manifest but absent from the zip -> clear (no dangling).
    if ds.ref_filename and ds.ref_filename not in extracted['ref']:
        ds.ref_filename = None
    if ds.ref_original_filename and ds.ref_original_filename not in extracted['ref']:
        ds.ref_original_filename = None
    try:
        extra_refs = json.loads(ds.ref_extra_filenames or '[]')
    except (TypeError, ValueError):
        extra_refs = []
    if not isinstance(extra_refs, list):
        extra_refs = []
    ds.ref_extra_filenames = json.dumps([
        name for name in extra_refs
        if isinstance(name, str) and Path(name).name == name and name in extracted['ref']
    ], ensure_ascii=False)
    db.session.commit()
    normalize_legacy_image_improvement_rows(ds.id)
    logger.info(f"dataset backup restored: '{name}' -> #{ds.id} ({n_rows} image rows)")
    return ds


def replace_in_captions(user_id, dataset_id, find, replace, mode='text'):
    """Bulk-edit the captions of KEPT images (the ones that train). Two modes:

    - 'text': plain substring replace, case-sensitive.
    - 'tag':  the caption is treated as a comma-separated tag list (booru); `find`
      must match a WHOLE tag (trimmed, case-insensitive) and is replaced by
      `replace` — or dropped when `replace` is empty. Avoids the ', ,' artifacts a
      substring removal would leave in tag captions. Result is deduped
      case-insensitively (keeping first occurrence / original casing).

    Returns the number of captions actually changed."""
    if mode not in ('text', 'tag'):
        raise ValueError('invalid mode')
    find = (find or '').strip() if mode == 'tag' else (find or '')
    if not find:
        raise ValueError('find is required')
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return 0
    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id, status='keep')
            .filter(FaceDatasetImage.caption.isnot(None)).all())
    from . import curation_history
    batch_id = curation_history.new_batch_id()
    changed = 0
    for img in rows:
        old = img.caption or ''
        if mode == 'text':
            new = old.replace(find, replace or '')
        else:
            tags = [t.strip() for t in old.split(',')]
            out, seen = [], set()
            for t in tags:
                if not t:
                    continue
                nt = (replace or '').strip() if t.lower() == find.lower() else t
                if not nt or nt.lower() in seen:
                    continue
                seen.add(nt.lower())
                out.append(nt)
            new = ', '.join(out)
        new = new.strip()[:CAPTION_MAX_CHARS] or None
        if new != img.caption:
            before = curation_history.snapshot(img, ('caption',))
            img.caption = new
            curation_history.record(
                user_id, img, f'caption_replace:{mode}', before,
                curation_history.snapshot(img, ('caption',)), batch_id=batch_id)
            changed += 1
    if changed:
        db.session.commit()
    return changed


# Batch curation (multi-select in the grid). 'pending' = reset the triage state.
BATCH_ACTIONS = ('keep', 'reject', 'pending', 'delete', 'clear_caption')


def batch_image_action(user_id, dataset_id, image_ids, action):
    """Apply one whitelisted action to a set of this dataset's images in one call
    (the grid's multi-select). Ownership is checked once on the dataset; ids that
    don't belong to it (or don't exist) are silently skipped, so a stale selection
    after a poll refresh can't touch another dataset's rows. Returns the number of
    images actually affected."""
    if action not in BATCH_ACTIONS:
        raise ValueError('invalid action')
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return 0
    ids = [int(i) for i in (image_ids or []) if isinstance(i, (int, float, str)) and str(i).lstrip('-').isdigit()]
    if not ids:
        return 0
    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id)
            .filter(FaceDatasetImage.id.in_(ids)).all())
    n = 0
    if action != 'clear_caption' and any(
            img.derivation_kind in _SMALL_IMAGE_DERIVATIONS for img in rows):
        raise ValueError('resolve small-image rescue pairs with the dedicated review action')
    if action != 'clear_caption' and any(_has_image_improvement_pair(img) for img in rows):
        raise ValueError('resolve reconstructed image pairs with the dedicated comparison action')
    if action == 'delete':
        # Per-image path: reuses delete_image (file removal + pending-job cancel).
        for img in rows:
            if delete_image(user_id, img.id):
                n += 1
        return n
    from . import curation_history
    fields = ('caption',) if action == 'clear_caption' else (
        'status', 'watermark_state', 'watermark_bbox', 'watermark_regions')
    batch_id = curation_history.new_batch_id()
    for img in rows:
        before = curation_history.snapshot(img, fields)
        if action == 'clear_caption':
            img.caption = None
        else:
            # Never resurrect a failed generation into keep/reject — the tile has
            # no file; regenerate is the only way out of 'failed'.
            if img.status == 'failed':
                continue
            if action == 'reject':
                _clear_watermark_metadata(img)
            img.status = action
        event = curation_history.record(
            user_id, img, f'batch:{action}', before,
            curation_history.snapshot(img, fields), batch_id=batch_id)
        if event is not None:
            n += 1
    db.session.commit()
    return n


def _ref_crop_source_path(ds) -> str:
    """The image a manual/auto re-crop reads from: the full-frame ORIGINAL when we
    kept one, else the cropped ref (legacy datasets uploaded before we stored the
    original — they can still be re-cropped, only not wider than the existing crop)."""
    name = ds.ref_original_filename or ds.ref_filename
    return os.path.join(_dataset_dir(ds.id), name)


def crop_reference(user_id, dataset_id, x, y, w, h):
    """Manually crop the dataset reference to (x,y,w,h), resized to 1024. The box is
    in the ORIGINAL's pixel space (the editor shows the original), and we write the
    derived square to ref_filename WITHOUT touching the original — so the user can
    re-crop wider or tighter any number of times."""
    ds = get_dataset(user_id, dataset_id)
    if not ds or not ds.ref_filename:
        return False
    ok, _scale = _crop_resize_file(_ref_crop_source_path(ds), x, y, w, h, dst=_ref_path(ds))
    return ok


def recrop_reference_auto(user_id, dataset_id):
    """Re-run the automatic head-crop on the ORIGINAL, overwriting ref_filename.
    Returns (ok, head_detected). CALLER holds the GPU vision window. Lets the user
    reset to the auto framing after manual edits, without re-uploading the photo."""
    ds = get_dataset(user_id, dataset_id)
    if not ds or not ds.ref_filename:
        return False, False
    try:
        with open(_ref_crop_source_path(ds), 'rb') as fh:
            raw = fh.read()
    except OSError:
        return False, False
    webp, detected = face_crop_to_square_webp(raw, pad=REF_CROP_PAD, return_detected=True)
    with open(_ref_path(ds), 'wb') as fh:
        fh.write(webp)
    return True, detected


def _payload_watermark_route(img):
    """The route Clean WOULD take for a 'detected' image ('crop' | 'lama' | 'review'),
    or None. It needs the pixel dims (the grid doesn't carry them), so it opens the
    file -- but ONLY for 'detected' rows (a bounded subset), so the single-dataset
    payload never reads every image header. Lets the review lightbox and the 🚩 tooltip
    name the EXACT planned action without duplicating _route_watermark in JS. Defensive:
    any read/parse error yields None and the UI falls back to the generic hint."""
    if img.watermark_state != 'detected':
        return None
    bbox = _safe_json(img.watermark_bbox)
    if not (isinstance(bbox, list) and len(bbox) == 4):
        return None
    try:
        with Image.open(_img_path(img)) as im:
            W, H = im.size
    except (OSError, ValueError):
        return None
    route, _box = _route_watermark(tuple(bbox), W, H)
    return route


def _caption_leaks_for_dataset(ds, img) -> bool:
    if img.status != 'keep' or not img.caption:
        return False
    if is_concept(ds):
        return caption_has_concept_leak(img.caption, ds.concept_desc, ds.concept_terms)
    if is_style(ds):
        return False
    return caption_has_identity_leak(img.caption, body=is_body_fidelity(ds))


def _dataset_image_payload(img, *, leak=False) -> dict:
    """Stable image representation shared by full and paginated endpoints."""
    return {
        'id': img.id, 'filename': img.filename, 'source': img.source,
        'framing': img.framing, 'variation_label': img.variation_label,
        'status': img.status, 'caption': img.caption, 'fail_reason': img.fail_reason,
        'parent_image_id': img.parent_image_id, 'derivation_kind': img.derivation_kind,
        'upscale_ratio': img.upscale_ratio, 'variation_prompt': img.variation_prompt,
        'leak': bool(leak), 'face_score': img.face_score, 'face_state': img.face_state,
        'source_name': img.source_name, 'original_filename': img.original_filename,
        'source_sha256': img.source_sha256, 'perceptual_hash': img.perceptual_hash,
        'duplicate_of_id': img.duplicate_of_id,
        'anchor_decision': img.anchor_decision or 'auto',
        'coverage': parse_coverage(img.coverage_json),
        'coverage_provenance': _safe_json(img.coverage_provenance),
        'source_rights': (_safe_json(img.source_rights) or
                          ({'basis': 'generated'} if img.source == 'generated'
                           else {'basis': 'unknown'})),
        'generation_anchor_ids': _parse_generation_anchor_ids(img.generation_anchor_ids),
        'generation_anchor_metadata': _parse_generation_anchor_metadata(
            img.generation_anchor_metadata),
        'generation_engine': img.generation_engine or (
            img.klein_model if img.source == 'generated' else None),
        'generation_gap_ids': _parse_generation_gap_ids(img.generation_gap_ids),
        'generation_provenance': _safe_json(img.generation_provenance),
        'analysis': parse_analysis(img.analysis_json),
        'training_usefulness': img.training_usefulness,
        'coverage_value': img.coverage_value,
        'watermark_state': img.watermark_state,
        'watermark_bbox': _safe_json(img.watermark_bbox),
        **_watermark_regions_payload(img),
        'watermark_route': _payload_watermark_route(img),
    }


def dataset_images_page(user_id, dataset_id, *, cursor=None, limit=100, status=None):
    """Cursor-paginated image collection, newest first."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return None
    try:
        limit = max(1, min(250, int(limit)))
    except (TypeError, ValueError):
        limit = 100
    query = FaceDatasetImage.query.filter_by(dataset_id=dataset_id)
    if status:
        if status not in _VALID_STATUS:
            raise ValueError(f'invalid image status: {status}')
        query = query.filter_by(status=status)
    else:
        query = query.filter(FaceDatasetImage.status != 'trashed')
    if cursor is not None:
        try:
            query = query.filter(FaceDatasetImage.id < int(cursor))
        except (TypeError, ValueError) as exc:
            raise ValueError('cursor must be an image id') from exc
    rows = query.order_by(FaceDatasetImage.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        'images': [_dataset_image_payload(
            row, leak=_caption_leaks_for_dataset(ds, row)) for row in rows],
        'page': {
            'limit': limit,
            'has_more': has_more,
            'next_cursor': rows[-1].id if has_more and rows else None,
        },
    }


def dataset_change_state(user_id, dataset_id):
    """Small, uncached state used by the dataset event stream."""
    row = (db.session.query(
        FaceDataset.revision, FaceDataset.name, FaceDataset.trigger_word,
        FaceDataset.kind, FaceDataset.concept_desc, FaceDataset.fidelity,
        FaceDataset.train_type, FaceDataset.ref_filename,
        FaceDataset.ref_extra_filenames, FaceDataset.coverage_profile,
        FaceDataset.coverage_targets)
           .filter(FaceDataset.id == dataset_id,
                   FaceDataset.user_id == str(user_id),
                   FaceDataset.trashed_at.is_(None)).first())
    if row is None:
        return None
    metadata_payload = json.dumps(
        list(row[1:]), ensure_ascii=False, separators=(',', ':'), default=str)
    return {
        'revision': int(row[0] or 0),
        # Image triggers drive ``revision``. Dataset-level edits need their own
        # deterministic marker so another tab receives names, trigger, policy,
        # references and training-family changes immediately too.
        'metadata_revision': hashlib.sha256(
            metadata_payload.encode('utf-8')).hexdigest()[:16],
        'activity': dataset_activity.get(dataset_id),
    }


_DATASET_AGGREGATE_CACHE = {}
_DATASET_AGGREGATE_CACHE_MAX = 128


def _dataset_aggregate_key(ds):
    # The cache is process-global while tests and embedders may create several
    # Flask apps, each with an independent SQLite database whose primary keys
    # and revisions begin at the same values. Include the bound engine identity
    # so an aggregate from database A can never be returned for database B.
    return (
        id(db.engine), ds.id, int(ds.revision or 0), ds.kind, ds.fidelity, ds.train_type,
        ds.ref_filename, ds.ref_extra_filenames, ds.concept_desc, ds.concept_terms,
        ds.coverage_profile, ds.coverage_targets,
    )


def _dataset_navigation_counts(imgs):
    """Whole-dataset counts for panels whose loaded image window is paginated."""
    by_id = {image.id: image for image in imgs}
    visible_ids = set(by_id)
    rescue_review = 0

    # The generic grid hides every rescue provenance row unless the pair has a
    # resolved winner. Unresolved pairs live exclusively in Curation.
    for image in imgs:
        if image.derivation_kind in _SMALL_IMAGE_DERIVATIONS:
            visible_ids.discard(image.id)
    for candidate in (image for image in imgs
                      if image.derivation_kind == KLEIN_SMALL_IMAGE):
        original = by_id.get(candidate.parent_image_id)
        if not original or original.derivation_kind != SMALL_IMAGE_SOURCE:
            continue
        winner = None
        if original.status == 'keep' and candidate.status == 'reject':
            winner = original
        elif original.status == 'reject' and candidate.status == 'keep':
            winner = candidate
        elif not (original.status == 'reject' and candidate.status == 'reject'):
            rescue_review += 1
        if winner:
            visible_ids.add(winner.id)

    # Reconstruction comparisons follow the same exclusive-review contract,
    # but may have multiple historical candidates attached to one source.
    improvement_groups = {}
    for candidate in (image for image in imgs
                      if image.derivation_kind == KLEIN_IMAGE_IMPROVE):
        original = by_id.get(candidate.parent_image_id)
        if original:
            improvement_groups.setdefault(original.id, []).append(candidate)
    for original_id, candidates in improvement_groups.items():
        original = by_id[original_id]
        visible_ids.discard(original_id)
        for candidate in candidates:
            visible_ids.discard(candidate.id)
        terminal = all(candidate.status in {'keep', 'reject'} for candidate in candidates)
        kept = [candidate for candidate in candidates if candidate.status == 'keep']
        if original.status == 'keep' and terminal and not kept:
            visible_ids.add(original.id)
        elif original.status == 'reject' and terminal and len(kept) == 1:
            visible_ids.add(kept[0].id)

    return {
        'selectable': sum(1 for image in imgs
                          if image.id in visible_ids and bool(image.filename)),
        'small_image_rescue': rescue_review,
    }


def _compute_dataset_aggregates(ds, imgs):
    comp = {'face': 0, 'bust': 0, 'body': 0, 'back': 0}
    # Combien, PAR bucket, sont des crops fortement agrandis (upscale_ratio >=
    # UPSCALE_WARN_THRESHOLD) plutôt que du natif : le compte `comp` seul traite un
    # gros plan natif et un gros plan upscalé x3 comme équivalents vis-à-vis de la
    # cible — ce sous-compte permet à l'UI de signaler un dataset qui « remplit »
    # sa cible face/bust surtout avec de la texture fabriquée par le resize.
    comp_upscaled = {'face': 0, 'bust': 0, 'body': 0, 'back': 0}
    for i in imgs:
        # Composition counts only usable images: rejected and failed ones don't
        # contribute to the training-target tally the UI tracks deficits against.
        if i.framing in comp and i.status == 'keep':
            comp[i.framing] += 1
            if (i.upscale_ratio or 0) >= UPSCALE_WARN_THRESHOLD:
                comp_upscaled[i.framing] += 1
    # concept OU style : le champ `fidelity`/`concept_desc` du payload est gouverné par
    # is_conceptual (character-only). La DÉTECTION de fuite, elle, est spécifique au KIND :
    #   - character : fuite d'IDENTITÉ (hair/skin/eyes)  → caption_has_identity_leak
    #   - concept   : fuite de CONCEPT (le set nomme le concept au lieu du trigger) →
    #                 caption_has_concept_leak — on ne force PLUS 0 (le badge « 0 leak »
    #                 faussement rassurant de l'incident leg_behind)
    #   - style     : rien (la description des sujets EST le contenu contrôlable) → 0 honnête
    def _img_leaks(i):
        return _caption_leaks_for_dataset(ds, i)

    exclusive_ids = set()
    for image in imgs:
        if image.derivation_kind in _SMALL_IMAGE_DERIVATIONS:
            exclusive_ids.add(image.id)
            if image.parent_image_id:
                exclusive_ids.add(image.parent_image_id)
        if image.derivation_kind == KLEIN_IMAGE_IMPROVE:
            exclusive_ids.add(image.id)
            if image.parent_image_id:
                exclusive_ids.add(image.parent_image_id)
    image_summary = {
        'total': len(imgs),
        'kept': sum(1 for i in imgs if i.status == 'keep'),
        'kept_captioned': sum(
            1 for i in imgs if i.status == 'keep' and bool((i.caption or '').strip())),
        'pending_generation': sum(
            1 for i in imgs if i.id not in exclusive_ids
            and i.status == 'pending' and not i.filename),
        'awaiting_triage': sum(
            1 for i in imgs if i.id not in exclusive_ids
            and i.status == 'pending' and bool(i.filename)),
        'unused': sum(1 for i in imgs if i.id not in exclusive_ids
                      and i.status in {'reject', 'failed'}),
        'watermark_detected': sum(
            1 for i in imgs if i.watermark_state == 'detected'),
        **_dataset_navigation_counts(imgs),
    }
    return {
        'composition': comp,
        'composition_upscaled': comp_upscaled,
        'coverage_plan': build_coverage_plan(ds, imgs),
        'anchor_plan': build_anchor_plan(ds, imgs),
        'image_summary': image_summary,
        'caption_leak': {
            'leaking': sum(1 for i in imgs if _img_leaks(i)),
            'captioned': sum(1 for i in imgs if i.status == 'keep' and i.caption),
        },
    }


def dataset_payload(user_id, dataset_id, *, include_images=True):
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return None
    cache_key = _dataset_aggregate_key(ds)
    aggregates = _DATASET_AGGREGATE_CACHE.get(cache_key)
    imgs = None
    if include_images or aggregates is None:
        imgs = (FaceDatasetImage.query.filter_by(dataset_id=dataset_id)
                .filter(FaceDatasetImage.status != 'trashed')
                .order_by(FaceDatasetImage.id.desc()).all())
    if aggregates is None:
        aggregates = _compute_dataset_aggregates(ds, imgs)
        _DATASET_AGGREGATE_CACHE[cache_key] = aggregates
        while len(_DATASET_AGGREGATE_CACHE) > _DATASET_AGGREGATE_CACHE_MAX:
            _DATASET_AGGREGATE_CACHE.pop(next(iter(_DATASET_AGGREGATE_CACHE)))

    concept = is_conceptual(ds)
    return {
        'id': ds.id, 'name': ds.name, 'trigger_word': ds.trigger_word,
        'revision': int(ds.revision or 0),
        'train_type': (ds.train_type or 'zimage'),
        'kind': (ds.kind or 'character'),
        'coverage_profile': (ds.coverage_profile or 'balanced'),
        'coverage_targets_custom': (_safe_json(ds.coverage_targets)
                                    or {'framing': {}, 'dimensions': {}}),
        'fidelity': (ds.fidelity or 'face') if not concept else 'face',
        'concept_desc': (ds.concept_desc or '') if concept else '',
        'ref_filename': ds.ref_filename,
        'ref_original_filename': ds.ref_original_filename or '',
        'ref_extra_filenames': extra_ref_filenames(ds),
        'composition': aggregates['composition'],
        'composition_upscaled': aggregates['composition_upscaled'],
        'coverage_plan': aggregates['coverage_plan'],
        'anchor_plan': aggregates['anchor_plan'],
        # Réglages gagnants du Studio (JSON → objet). Manquait du payload : le badge
        # ★ du workspace ne s'affichait jamais, et le garde-fou « suppression d'un
        # checkpoint référencé » en a besoin.
        'best_settings': _safe_json(ds.best_settings),
        'face_thresholds': {'green': cfg.get('face_scoring.green'), 'orange': cfg.get('face_scoring.orange')},
        # Metadata-only clients fetch this route with include_images=0 and page
        # through /images. The default remains backward-compatible for scripts,
        # tests, and older frontends.
        'images': ([_dataset_image_payload(
            i, leak=_caption_leaks_for_dataset(ds, i)) for i in imgs]
                   if include_images else []),
        'image_summary': aggregates['image_summary'],
        # Kind-specific leak count (see _img_leaks): character = identity, concept = the
        # caption naming the concept (NEVER forced 0 any more), style = 0 (not applicable).
        # `captioned` bounds the badge ("N leaking / M checked") so a 0 reads as a real
        # result on M captions, not a check that never ran.
        'caption_leak': aggregates['caption_leak'],
        # Live server-side batch on this dataset (watermark detect/clean, caption/
        # re-caption, face analysis, framing classify) as {kind, done, total,
        # started_at} — or None. The front-end RESTORES the in-progress button state
        # from this on reload and polls the payload until it clears (the indicator was
        # React-local before, so a refresh mid-batch dropped it). In-memory registry:
        # empty after a server restart, so a batch killed with the process leaves no
        # phantom indicator.
        'activity': dataset_activity.get(dataset_id),
    }


# --- Image normalization ---------------------------------------------------
def normalize_to_webp(image_bytes: bytes, size: int = 1024) -> bytes:
    return image_processing.normalize_to_webp(image_bytes, size=size)


def detect_head_bbox(image_bytes):
    """Return normalized (x1, y1, x2, y2) of the main head via Qwen3-VL, or None.

    None also covers Ollama being unreachable/misconfigured (describe_image_ollama
    never raises) -- the caller (face_crop_to_square_webp) already treats "no
    detection" as a normal case and falls back to a centered crop, so uploads
    keep working (degraded but functional)."""
    return image_processing.detect_head_bbox(image_bytes)


# Marge d'elargissement de la bbox watermark (fraction du cote). Les bbox VLM sont
# GROSSIERES et souvent trop serrees : sans marge, le crop/inpaint laisse un lisere du
# watermark. 2.5% de chaque cote = filet de securite sans engloutir le sujet.
_WATERMARK_BBOX_MARGIN = image_processing.WATERMARK_BBOX_MARGIN


def _parse_watermark_bbox(raw):
    """PURE parser for a WATERMARK_BBOX_PROMPT answer. Returns a MARGIN-EXPANDED
    normalized (x1,y1,x2,y2) in [0,1], or None (no watermark / unparseable). Split out
    from the vision call so the batch can tell an EMPTY vision output (Ollama down ->
    leave the state untouched) apart from a clean 'present:false' answer (-> 'none').

    Same bbox handling as detect_head_bbox: 0-1000 grid, swapped corners normalized to
    min/max. A `present:false` (or a missing/invalid box) -> None. VLM boxes run tight,
    so we pad by _WATERMARK_BBOX_MARGIN and clamp -- the router needs the whole mark."""
    return image_processing.parse_watermark_bbox(raw)


def detect_watermark_bbox(image_bytes, *, keep_alive=0):
    """Return normalized (x1, y1, x2, y2) of an OVERLAID watermark via Qwen3-VL, or
    None (no overlaid watermark, or the model is unreachable / the JSON won't parse).
    fmt='json' forces Ollama's grammar mode, same as detect_head_bbox.

    The prompt targets watermark/logo/URL/username text ADDED ON TOP of the photo, NOT
    scene text (signs, clothing prints) -- see WATERMARK_BBOX_PROMPT. Box is margin-
    expanded (see _parse_watermark_bbox). `keep_alive` mirrors describe_image_ollama:
    0 unloads after this call; a batch passes a duration and unloads at the end."""
    return image_processing.detect_watermark_bbox(image_bytes, keep_alive=keep_alive)


def face_crop_to_square_webp(image_bytes: bytes, size: int = 1024, pad: float = 1.7,
                             *, return_detected: bool = False, use_vision: bool = True,
                             return_scale: bool = False):
    """Head-crop (Qwen3-VL bbox, generous padding for hair + shoulders) into a
    SQUARE that FILLS `size` - no black padding, no distortion (the square is
    shrunk to fit inside the image so it never needs letterboxing). Falls back to
    a centered-square crop if no head is detected. CALLER holds the GPU window.

    `return_detected=True` -> (webp_bytes, head_detected) so the caller can WARN the
    user when it silently fell back to a centered crop (e.g. vision model not pulled)
    instead of leaving them puzzled by a body-centered reference.

    `return_scale=True` -> also returns the upscale ratio applied to reach `size`
    (>1 means the detected/fallback box was smaller than `size` and got LANCZOS-
    enlarged — see UPSCALE_WARN_THRESHOLD). Additive and independent from
    `return_detected` so existing 2-tuple callers (the /ref route) are unaffected.

    `use_vision=False` -> skip the bbox detection entirely (fast pure-PIL centered
    square, no GPU window needed) — the manual-first reference flow."""
    return image_processing.face_crop_to_square_webp(
        image_bytes,
        size=size,
        pad=pad,
        return_detected=return_detected,
        use_vision=use_vision,
        return_scale=return_scale,
        detector=detect_head_bbox,
    )


# --- Import + classify (Qwen3-VL) ------------------------------------------
def import_images(user_id, dataset_id, files_bytes, crop=False, dedupe=False, stats=None):
    """Normalize (or head-crop) + persist + create import rows.

    Character photos enter the master corpus as ``pending``: import means preserve and
    inspect, not silently admit to training. Concept/style imports retain their previous
    accepted-by-default behaviour because identity scoring does not apply to them.
    When crop=True, each image is auto head-cropped via Qwen3-VL - the CALLER
    must then hold the GPU-exclusive window - and is by construction a face,
    so framing='face' is set directly (no classify pass needed).

    dedupe=True skips byte-identical source files by SHA-256. Perceptually similar
    burst frames are deliberately retained and linked as a duplicate group for
    human review — a large real corpus should not silently lose a useful sharper
    frame merely because it resembles the first file encountered.

    Returns (ids, failed_count)."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return [], 0
    # Sans head-crop, on préserve TOUJOURS le ratio (normalize_to_webp) : l'ancien
    # chemin « carré padé » ajoutait des bandes noires que le LoRA apprendrait, et
    # forçait tous les imports personnage en carré — un plan buste/corps importé
    # doit rester tel quel (ai-toolkit gère le bucketing multi-ratios).
    hash_rows = _existing_dhash_rows(dataset_id) if dedupe else []
    hash_index = _DHashIndex(hash_rows)
    exact_hashes = {row.source_sha256 for row, _value in hash_rows if row.source_sha256}
    ids = []
    failed = 0
    created_paths = []
    for index, item in enumerate(files_bytes):
        if isinstance(item, tuple) and len(item) == 2:
            source_name, raw = item
        else:
            source_name, raw = None, item
        if not isinstance(raw, (bytes, bytearray)):
            failed += 1
            continue
        try:
            analysis = analyse_image_bytes(raw, source_name=source_name)
        except (OSError, ValueError, TypeError) as e:
            failed += 1
            logger.warning(f"dataset import: analysis skipped ({source_name or index}): {e}")
            continue
        if dedupe and analysis.get('source_sha256') in exact_hashes:
            if stats is not None:
                stats['duplicates'] = stats.get('duplicates', 0) + 1
            logger.info('dataset import: exact source duplicate skipped (dataset %s)', dataset_id)
            continue
        # Garde-fou qualité : ai-toolkit ne fait que RÉDUIRE — une image sous
        # 768 px de petit côté reste floue à l'entraînement. Comptée (toast),
        # jamais bloquée : c'est parfois la seule photo disponible.
        if stats is not None:
            try:
                with Image.open(io.BytesIO(raw)) as im0:
                    if min(im0.size) < SCRAPE_IMPORT_MIN_SIDE:
                        stats['small'] = stats.get('small', 0) + 1
            except Exception:
                pass
        try:
            if crop:
                webp, scale = face_crop_to_square_webp(raw, return_scale=True)
            else:
                webp, scale = normalize_to_webp(raw), None
        except Exception as e:
            failed += 1
            logger.warning(f"dataset import: image skipped (dataset {dataset_id}): {e}")
            continue
        fp = None
        duplicate_of_id = None
        if dedupe:
            try:
                with Image.open(io.BytesIO(webp)) as im:
                    fp = _dhash(im)
            except (OSError, ValueError):
                fp = None   # unreadable output would have failed above; belt & braces
            if fp is not None and hash_index:
                match, _distance = hash_index.nearest_within(fp)
                if match is not None:
                    duplicate_of_id = match[0].duplicate_of_id or match[0].id
                    if stats is not None:
                        stats['near_duplicates'] = stats.get('near_duplicates', 0) + 1
        try:
            original_filename = _store_original_bytes(user_id, dataset_id, raw)
            created_paths.append(os.path.join(_dataset_dir(dataset_id), original_filename))
        except OSError as e:
            failed += 1
            logger.warning(f"dataset import: original preservation failed ({source_name or index}): {e}")
            continue
        fn = f"{user_id}_dataset_{uuid.uuid4().hex[:8]}.webp"
        normalized_path = os.path.join(_dataset_dir(dataset_id), fn)
        try:
            _atomic_write_bytes(normalized_path, webp)
            created_paths.append(normalized_path)
        except OSError as e:
            failed += 1
            original_path = os.path.join(_dataset_dir(dataset_id), original_filename)
            try:
                os.remove(original_path)
            except OSError:
                pass
            if original_path in created_paths:
                created_paths.remove(original_path)
            logger.warning(
                'dataset import: normalized write failed (%s): %s',
                source_name or index, e)
            continue
        img = FaceDatasetImage(
            dataset_id=dataset_id,
            source='import',
            status='keep' if is_conceptual(ds) else 'pending',
            filename=fn,
            source_name=analysis.get('source_name') or None,
            original_filename=original_filename,
            source_sha256=analysis.get('source_sha256'),
            analysis_json=analysis_json(analysis),
            training_usefulness=analysis.get('training_usefulness'),
            coverage_value=analysis.get('coverage_value'),
            perceptual_hash=f'{fp:016x}' if fp is not None else None,
            duplicate_of_id=duplicate_of_id,
            framing='face' if crop else None,
            upscale_ratio=scale,
        )
        db.session.add(img)
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            for path in created_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise
        ids.append(img.id)
        exact_hashes.add(analysis.get('source_sha256'))
        if fp is not None:
            hash_rows.append((img, fp))
            hash_index.add(img, fp)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        for path in created_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return ids, failed


# --- Import d'un dataset d'entraînement existant (ZIP kohya-style / dossier) --
# Des images + sidecars .txt de même nom (la convention kohya/ai-toolkit), soit
# dans un ZIP uploadé, soit dans un dossier du disque du serveur (app locale
# mono-user : le chemin est SON disque). Les images gardent leur ratio
# (normalize_to_webp, pas de crop), les captions atterrissent sur les rows,
# dédup perceptuelle vs le lot ET le dataset. Les fichiers sont réécrits sous
# des noms générés (jamais celui de la source → aucune traversée possible),
# profondeur de dossiers libre (le ZIP accepte toute arborescence ; le dossier
# est parcouru récursivement pour rester aligné).
DATASET_ZIP_MAX_FILES = 400
DATASET_ZIP_MAX_BYTES = 2 * 1024 * 1024 * 1024
_DATASET_ZIP_IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')


def _merge_training_images(user_id, dataset_id, entries, captions, stats=None):
    """Cœur commun ZIP/dossier : `entries` = liste de (stem, display_name, getter)
    où `getter()` rend les bytes de l'image, `captions` = {stem: texte}. Chaque
    image lisible devient une row 'import' (status=keep, ratio préservé), la
    caption de même stem est attachée (tronquée à CAPTION_MAX_CHARS), les
    exact source duplicates are skipped; perceptual siblings are retained and
    grouped for review.
    Returns (ids, failed)."""
    hash_rows = _existing_dhash_rows(dataset_id)
    hash_index = _DHashIndex(hash_rows)
    exact_hashes = {row.source_sha256 for row, _value in hash_rows if row.source_sha256}
    ids, failed = [], 0
    created_paths = []
    for stem, display, getter in entries:
        try:
            raw = getter()
        except (OSError, zipfile.BadZipFile):
            failed += 1
            continue
        if stats is not None:   # même garde qualité que l'import de photos
            try:
                with Image.open(io.BytesIO(raw)) as im0:
                    if min(im0.size) < SCRAPE_IMPORT_MIN_SIDE:
                        stats['small'] = stats.get('small', 0) + 1
            except Exception:
                pass
        try:
            analysis = analyse_image_bytes(raw, source_name=display)
        except (OSError, ValueError, TypeError) as e:
            failed += 1
            logger.warning(f"dataset import: analysis skipped ({display}): {e}")
            continue
        if analysis.get('source_sha256') in exact_hashes:
            if stats is not None:
                stats['duplicates'] = stats.get('duplicates', 0) + 1
            continue
        try:
            webp = normalize_to_webp(raw)
        except Exception as e:
            failed += 1
            logger.warning(f"dataset import: image skipped ({display}): {e}")
            continue
        try:
            with Image.open(io.BytesIO(webp)) as im:
                fp = _dhash(im)
        except (OSError, ValueError):
            fp = None
        duplicate_of_id = None
        if fp is not None and hash_index:
            match, _distance = hash_index.nearest_within(fp)
            if match is not None:
                duplicate_of_id = match[0].duplicate_of_id or match[0].id
                if stats is not None:
                    stats['near_duplicates'] = stats.get('near_duplicates', 0) + 1
        try:
            original_filename = _store_original_bytes(user_id, dataset_id, raw)
            created_paths.append(os.path.join(_dataset_dir(dataset_id), original_filename))
        except OSError as e:
            failed += 1
            logger.warning(f"dataset import: original preservation failed ({display}): {e}")
            continue
        fn = f"{user_id}_dsimport_{uuid.uuid4().hex[:8]}.webp"
        normalized_path = os.path.join(_dataset_dir(dataset_id), fn)
        try:
            _atomic_write_bytes(normalized_path, webp)
            created_paths.append(normalized_path)
        except OSError as e:
            failed += 1
            original_path = os.path.join(_dataset_dir(dataset_id), original_filename)
            try:
                os.remove(original_path)
            except OSError:
                pass
            if original_path in created_paths:
                created_paths.remove(original_path)
            logger.warning(
                'dataset import: normalized write failed (%s): %s', display, e)
            continue
        cap = (captions.get(stem) or '').strip() or None
        if cap:
            cap = cap[:CAPTION_MAX_CHARS]
            if stats is not None:
                stats['captions'] = stats.get('captions', 0) + 1
        img = FaceDatasetImage(
            dataset_id=dataset_id,
            source='import',
            status='keep',
            filename=fn,
            source_name=analysis.get('source_name') or None,
            original_filename=original_filename,
            source_sha256=analysis.get('source_sha256'),
            analysis_json=analysis_json(analysis),
            training_usefulness=analysis.get('training_usefulness'),
            coverage_value=analysis.get('coverage_value'),
            perceptual_hash=f'{fp:016x}' if fp is not None else None,
            duplicate_of_id=duplicate_of_id,
            caption=cap,
        )
        db.session.add(img)
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            for path in created_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise
        ids.append(img.id)
        exact_hashes.add(analysis.get('source_sha256'))
        if fp is not None:
            hash_rows.append((img, fp))
            hash_index.add(img, fp)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        for path in created_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return ids, failed


def import_dataset_zip(user_id, dataset_id, zip_source, stats=None):
    """Import an existing training dataset into THIS dataset (merge, not create):
    every image in the zip becomes an 'import' row (status=keep), a same-stem
    .txt sidecar becomes its caption (truncated to CAPTION_MAX_CHARS). Returns
    (ids, failed). ValueError on a non-zip / oversized archive."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    try:
        source = io.BytesIO(zip_source) if isinstance(zip_source, (bytes, bytearray)) else zip_source
        z = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError, TypeError):
        raise ValueError('not a zip file')
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > DATASET_ZIP_MAX_FILES:
        raise ValueError(f'too many files in the zip (max {DATASET_ZIP_MAX_FILES})')
    if sum(i.file_size for i in infos) > DATASET_ZIP_MAX_BYTES:
        raise ValueError('zip too large (max 2 GB uncompressed)')
    captions = {}
    for i in infos:
        if i.filename.lower().endswith('.txt') and i.file_size <= 64 * 1024:
            try:
                captions[os.path.splitext(i.filename)[0]] = \
                    z.read(i).decode('utf-8', 'replace').strip()
            except (OSError, zipfile.BadZipFile):
                pass
    entries = [(os.path.splitext(i.filename)[0], i.filename, lambda i=i: z.read(i))
               for i in infos if i.filename.lower().endswith(_DATASET_ZIP_IMG_EXTS)]
    try:
        return _merge_training_images(user_id, dataset_id, entries, captions, stats=stats)
    finally:
        z.close()


def import_dataset_folder(user_id, dataset_id, folder, stats=None):
    """Same merge as import_dataset_zip but straight from a folder on the
    server's disk — no need to zip an existing kohya dataset first. Recursive
    (the zip accepts any folder depth, the folder walk mirrors that); non-image
    files are ignored, same-stem .txt sidecars become captions. Returns
    (ids, failed). ValueError on a missing folder / oversized content."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    # Windows «Copier en tant que chemin» colle le chemin entre guillemets —
    # on les retire pour que le coller-direct marche du premier coup.
    folder = (folder or '').strip().strip('"\'')
    if not folder or not os.path.isdir(folder):
        raise ValueError(f'folder not found or not readable: {folder or "(empty)"}')
    paths = []
    for root, _dirs, files in os.walk(folder):
        paths.extend(os.path.join(root, f) for f in files)
    if len(paths) > DATASET_ZIP_MAX_FILES:
        raise ValueError(f'too many files in the folder (max {DATASET_ZIP_MAX_FILES})')
    sizes = {}
    for p in paths:
        try:
            sizes[p] = os.path.getsize(p)
        except OSError:
            sizes[p] = 0
    if sum(sizes.values()) > DATASET_ZIP_MAX_BYTES:
        raise ValueError('folder too large (max 2 GB)')
    captions = {}
    for p in paths:
        if p.lower().endswith('.txt') and sizes.get(p, 0) <= 64 * 1024:
            try:
                with open(p, 'rb') as fh:
                    captions[os.path.splitext(p)[0]] = \
                        fh.read().decode('utf-8', 'replace').strip()
            except OSError:
                pass

    def _read(p):
        with open(p, 'rb') as fh:
            return fh.read()

    entries = [(os.path.splitext(p)[0], p, lambda p=p: _read(p))
               for p in paths if p.lower().endswith(_DATASET_ZIP_IMG_EXTS)]
    return _merge_training_images(user_id, dataset_id, entries, captions, stats=stats)


# --- Scrape direct → dataset concept ----------------------------------------
# Construction de dataset AUTONOME : on scanne une URL de galerie (routes scrape
# READ-ONLY, /api/scrape/scan + /thumb) et on télécharge les images choisies
# DIRECTEMENT dans le dataset — le pool scrape partagé de l'app source n'est PAS
# porté (cette app ne scrape que pour construire des datasets concept). Filtres :
# dedup perceptuel + résolution + ratio = les 3 filtres « toujours rentables » ;
# flou/watermark restent une décision HUMAINE (la sélection dans la grille de scan).
SCRAPE_IMPORT_MAX = 60             # cap par import (download synchrone parallélisé)
SCRAPE_IMPORT_MIN_SIDE = 768       # ai-toolkit ne fait que downscaler : 768 reste exploitable
SCRAPE_IMPORT_MAX_RATIO = 3.0      # au-delà de 3:1, aucun bucket trainer ne gère proprement
SCRAPE_DHASH_MAX_DISTANCE = 8      # Hamming ≤ 8 sur 64 bits = doublon perceptuel
_SCRAPE_DL_TYPES = ('image/jpeg', 'image/jpg', 'image/png', 'image/webp')  # pas de gif/svg
_SCRAPE_DL_MAX_BYTES = 25 * 1024 * 1024
_SCRAPE_DL_WORKERS = 6


def _existing_dhashes(dataset_id) -> _DHashIndex:
    """Indexed dHashes of existing keep/pending images, with legacy backfill."""
    out = _DHashIndex()
    rows = FaceDatasetImage.query.filter(
        FaceDatasetImage.dataset_id == dataset_id,
        FaceDatasetImage.status.in_(('keep', 'pending'))).all()
    for r in rows:
        if not r.filename:
            continue
        try:
            with Image.open(os.path.join(_dataset_dir(dataset_id), r.filename)) as im:
                value = _dhash(im)
        except (OSError, ValueError):
            continue
        out.add(None, value)
    return out


def _existing_dhash_rows(dataset_id) -> list:
    """Return ``[(row, hash_int)]`` and backfill hashes in memory when needed."""
    out = []
    rows = FaceDatasetImage.query.filter(
        FaceDatasetImage.dataset_id == dataset_id,
        FaceDatasetImage.status.in_(('keep', 'pending'))).all()
    for row in rows:
        if not row.filename:
            continue
        value = _stored_hash_int(row.perceptual_hash)
        if value is None:
            try:
                with Image.open(os.path.join(_dataset_dir(dataset_id), row.filename)) as image:
                    value = _dhash(image)
            except (OSError, ValueError):
                continue
        out.append((row, value))
    return out


def _stored_hash_int(value):
    try:
        return int(value, 16) if value else None
    except (TypeError, ValueError):
        return None


def analyze_corpus(user_id, dataset_id) -> dict:
    """Refresh local technical metadata and durable near-duplicate groups.

    This pass is CPU/Pillow-only and safe for a large import. It never deletes
    an image. Within each perceptual cluster, the highest quality row becomes
    the representative and siblings point to it through ``duplicate_of_id``.
    """
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id, source='import')
            .filter(FaceDatasetImage.filename.isnot(None)).all())
    analyzed = failed = 0
    for row in rows:
        normalized_path = _img_path(row)
        original_path = (os.path.join(_dataset_dir(dataset_id), row.original_filename)
                         if row.original_filename else '')
        try:
            source_path = original_path if original_path and os.path.isfile(original_path) else normalized_path
            with open(source_path, 'rb') as fh:
                raw = fh.read()
            previous = parse_analysis(row.analysis_json)
            analysis = analyse_image_bytes(raw, source_name=row.source_name)
            if previous.get('face'):
                analysis['face'] = previous['face']
            with Image.open(normalized_path) as image:
                row.perceptual_hash = f'{_dhash(image):016x}'
            row.source_sha256 = row.source_sha256 or analysis.get('source_sha256')
            row.analysis_json = analysis_json(analysis)
            row.training_usefulness = analysis.get('training_usefulness')
            analyzed += 1
        except (OSError, ValueError, TypeError):
            failed += 1
            logger.exception('corpus analysis failed for image %s', row.id)

    # Best technical row leads each cluster, so a weaker burst frame points to
    # the sharp/high-resolution representative instead of whichever imported first.
    ordered = sorted((row for row in rows if _stored_hash_int(row.perceptual_hash) is not None),
                     key=lambda row: (-_anchor_quality_score(row), row.id))
    representatives = _DHashIndex()
    for row in rows:
        row.duplicate_of_id = None
    duplicate_pairs = 0
    for row in ordered:
        value = _stored_hash_int(row.perceptual_hash)
        match, _distance = representatives.nearest_within(value)
        if match is None:
            representatives.add(row, value)
        else:
            row.duplicate_of_id = match[0].id
            duplicate_pairs += 1
    db.session.commit()
    return {'analyzed': analyzed, 'failed': failed,
            'duplicate_groups': len({row.duplicate_of_id for row in rows if row.duplicate_of_id}),
            'near_duplicates': duplicate_pairs}


def set_anchor_decision(user_id, image_id, decision) -> bool:
    img = _owned_image(user_id, image_id)
    if not img or img.source != 'import':
        return False
    normalized = str(decision or 'auto').strip().lower()
    if normalized not in ANCHOR_DECISIONS:
        raise ValueError('anchor decision must be auto, pinned, or excluded')
    from . import curation_history
    before = curation_history.snapshot(img, ('anchor_decision',))
    img.anchor_decision = None if normalized == 'auto' else normalized
    curation_history.record(
        user_id, img, f'anchor:{normalized}', before,
        curation_history.snapshot(img, ('anchor_decision',)))
    db.session.commit()
    return True


def set_image_coverage(user_id, image_id, values) -> bool:
    img = _owned_image(user_id, image_id)
    if not img or img.source != 'import':
        return False
    if not isinstance(values, dict):
        raise ValueError('coverage must be an object')
    from . import curation_history
    coverage_fields = ('framing', 'coverage_json', 'coverage_value',
                       'coverage_provenance', 'variation_label')
    before = curation_history.snapshot(img, coverage_fields)
    framing = str(values.get('framing') or '').strip().lower()
    if framing:
        if framing not in ('face', 'bust', 'body', 'back', 'unknown'):
            raise ValueError(f'invalid framing: {framing}')
        img.framing = framing
    coverage = normalize_coverage(values)
    img.coverage_json = json.dumps(coverage, ensure_ascii=False, sort_keys=True)
    img.coverage_value = 'green' if coverage else 'unknown'
    now = datetime.now(timezone.utc).isoformat()
    img.coverage_provenance = json.dumps({
        'source': 'manual', 'recorded_at': now,
        'confidence': {key: 1.0 for key in coverage},
    }, ensure_ascii=False, sort_keys=True)
    label = ', '.join(coverage.get(key) for key in ('angle', 'expression')
                      if coverage.get(key))
    if label:
        img.variation_label = label[:120]
    curation_history.record(
        user_id, img, 'coverage', before,
        curation_history.snapshot(img, coverage_fields))
    db.session.commit()
    return True


SOURCE_RIGHTS_BASES = ('owned', 'licensed', 'consented', 'public-domain', 'unknown')


def set_image_rights(user_id, image_id, values) -> bool:
    img = _owned_image(user_id, image_id)
    if not img or not isinstance(values, dict):
        return False
    basis = str(values.get('basis') or 'unknown').strip().lower()
    if basis not in SOURCE_RIGHTS_BASES:
        raise ValueError('rights basis must be owned, licensed, consented, public-domain, or unknown')
    payload = {
        'basis': basis,
        'license': str(values.get('license') or '').strip()[:160],
        'consent_confirmed': bool(values.get('consent_confirmed')),
        'notes': str(values.get('notes') or '').strip()[:500],
        'recorded_at': datetime.now(timezone.utc).isoformat(),
    }
    from . import curation_history
    before = curation_history.snapshot(img, ('source_rights',))
    img.source_rights = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    curation_history.record(
        user_id, img, f'rights:{basis}', before,
        curation_history.snapshot(img, ('source_rights',)))
    db.session.commit()
    return True


def _accept_scrape_bytes(raw, seen_hashes, skipped, rescue_small=False):
    """Filtre une image téléchargée : résolution / ratio / dedup perceptuel.
    Retourne les bytes si acceptée (et enregistre son dHash dans seen_hashes),
    sinon None en incrémentant le compteur skipped adéquat. Quand rescue_small
    est vrai, une petite image continue vers ratio+dedup au lieu d'être rejetée;
    elle ne sera jamais importée directement dans l'entraînement."""
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            w, h = im.size
            if min(w, h) < SCRAPE_IMPORT_MIN_SIDE and not rescue_small:
                skipped['low_res'] += 1
                return None
            if max(w, h) > SCRAPE_IMPORT_MAX_RATIO * min(w, h):
                skipped['extreme_ratio'] += 1
                return None
            fp = _dhash(im)
    except (OSError, ValueError):
        skipped['errors'] += 1
        return None
    if isinstance(seen_hashes, _DHashIndex):
        duplicate = seen_hashes.nearest_within(fp)[0] is not None
    else:
        duplicate = any(_hamming(fp, s) <= SCRAPE_DHASH_MAX_DISTANCE for s in seen_hashes)
    if duplicate:
        skipped['duplicates'] += 1
        return None
    if isinstance(seen_hashes, _DHashIndex):
        seen_hashes.add(None, fp)
    else:
        seen_hashes.append(fp)
    return raw


def _scrape_resolution_key(downloaded):
    """Sort key for rescue batches: the best-resolution duplicate must win."""
    reason, raw = downloaded
    if reason != 'ok' or not raw:
        return (0, 0)
    try:
        with Image.open(io.BytesIO(raw)) as im:
            return (min(im.size), im.width * im.height)
    except (OSError, ValueError):
        return (0, 0)


def _save_small_scrape_pair(user_id, dataset_id, raw, prompt):
    """Persist the untouched scrape source and enqueue one Klein candidate.

    Returns True when queued, False when enqueue failed. The original and result
    rows are committed before enqueue so a failed queue operation never loses the
    source file or leaves an untracked job.
    """
    from .klein_edit_helper import enqueue_klein_edit

    with Image.open(io.BytesIO(raw)) as im:
        ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}.get(im.format)
    if not ext:
        raise ValueError('unsupported scrape image format')
    filename = f"{user_id}_scrape_small_{uuid.uuid4().hex[:8]}{ext}"
    source_path = os.path.join(_dataset_dir(dataset_id), filename)
    with open(source_path, 'wb') as fh:
        fh.write(raw)

    source = FaceDatasetImage(
        dataset_id=dataset_id, source='import', status='pending', filename=filename,
        derivation_kind=SMALL_IMAGE_SOURCE,
        variation_label='Small scraped image · original',
    )
    db.session.add(source)
    db.session.flush()
    label = 'Klein rescue · small scraped image'
    candidate = FaceDatasetImage(
        dataset_id=dataset_id, source='generated', status='pending',
        parent_image_id=source.id, derivation_kind=KLEIN_SMALL_IMAGE,
        variation_label=label, variation_prompt=prompt,
    )
    db.session.add(candidate)
    db.session.commit()

    try:
        job_id = enqueue_klein_edit(
            user_id=str(user_id), source_filename=filename, source_path=source_path,
            edit_prompt=prompt,
            extra_metadata={'is_dataset': True, 'dataset_id': dataset_id,
                            'variation_label': label,
                            'derivation_kind': KLEIN_SMALL_IMAGE,
                            'parent_image_id': source.id},
        )
    except Exception as exc:
        candidate.status = 'failed'
        candidate.fail_reason = f'Klein small-image rescue could not be queued: {exc}'
        db.session.commit()
        logger.exception('small-image rescue enqueue failed for dataset %s source %s',
                         dataset_id, source.id)
        return False
    candidate.job_id = job_id
    db.session.commit()
    return True


def _download_scrape_item(item):
    """Télécharge UNE image d'un item de scan ({url,title}) en mémoire, durci
    anti-SSRF (mêmes garanties que /thumb). Retourne (reason, data|None) où
    reason ∈ {'ok','not_image','errors'}. Sûr hors app-context (thread pool)."""
    from ..scrape.netfetch import fetch_hardened_bytes, _validate_public_http_url
    url = (item or {}).get('url')
    if not url:
        return ('errors', None)
    ok_url, _err = _validate_public_http_url(url)
    if not ok_url:
        return ('errors', None)
    ok, data, _ctype, reason = fetch_hardened_bytes(
        url, allowed_types=_SCRAPE_DL_TYPES, max_bytes=_SCRAPE_DL_MAX_BYTES,
        require_image_magic=True)
    if not ok:
        # 'type'/'noimage' = pas une vraie image raster ; le reste = erreur réseau.
        return ('not_image' if reason in ('type', 'noimage') else 'errors', None)
    return ('ok', data)


def scrape_import_urls(user_id, dataset_id, items, rescue_small=False):
    """Télécharge les images scannées SÉLECTIONNÉES directement dans le dataset
    concept — flux AUTONOME. `items` = [{'url','title'}]. Download parallélisé
    (borné), puis filtre + dedup séquentiels (état partagé), puis import brut
    aspect-kept via import_images(crop=False). Renvoie
    {'imported': n, 'rescue_queued': n, 'rescue_failed': n,
     'skipped': {duplicates, low_res, extreme_ratio, not_image, errors}}."""
    from concurrent.futures import ThreadPoolExecutor
    skipped = {'duplicates': 0, 'low_res': 0, 'extreme_ratio': 0,
               'not_image': 0, 'errors': 0}
    items = [it for it in (items or []) if isinstance(it, dict) and it.get('url')]
    if not items:
        return {'imported': 0, 'rescue_queued': 0, 'rescue_failed': 0,
                'skipped': skipped}
    with ThreadPoolExecutor(max_workers=_SCRAPE_DL_WORKERS) as pool:
        downloaded = list(pool.map(_download_scrape_item, items))

    # In rescue mode a low-resolution duplicate must never claim the dHash first
    # and make the usable HD source look like the duplicate. The legacy path keeps
    # request order exactly as before.
    if rescue_small:
        downloaded.sort(key=_scrape_resolution_key, reverse=True)

    seen_hashes = _existing_dhashes(dataset_id)
    accepted, rescue_candidates = [], []
    for reason, data in downloaded:
        if reason != 'ok':
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        ok_bytes = _accept_scrape_bytes(data, seen_hashes, skipped,
                                        rescue_small=rescue_small)
        if ok_bytes is not None:
            if rescue_small:
                try:
                    with Image.open(io.BytesIO(ok_bytes)) as im:
                        is_small = min(im.size) < SCRAPE_IMPORT_MIN_SIDE
                except (OSError, ValueError):
                    skipped['errors'] += 1
                    continue
                (rescue_candidates if is_small else accepted).append(ok_bytes)
            else:
                accepted.append(ok_bytes)

    # Capacity and model preflight happen once, after every quality/dedup filter,
    # but before creating a source/result pair. No small candidate => no Klein scan.
    if rescue_candidates:
        in_flight = (FaceDatasetImage.query
                     .filter_by(dataset_id=dataset_id, status='pending')
                     .filter(FaceDatasetImage.filename.is_(None)).count())
        if in_flight + len(rescue_candidates) > MAX_FANOUT:
            raise ValueError(f'too many generations in flight ({in_flight}), wait or cancel')
        from .klein_edit_helper import (KLEIN_REQUIRED, KleinModelsMissing,
                                        klein_missing_assets)
        missing = klein_missing_assets()
        if any(asset in missing for asset in KLEIN_REQUIRED):
            raise KleinModelsMissing(missing)

    ids, failed = import_images(user_id, dataset_id, accepted, crop=False)
    skipped['errors'] += failed
    raw_prompt = cfg.get('klein.small_image_prompt', '')
    prompt = '' if raw_prompt is None else str(raw_prompt)
    rescue_queued = rescue_failed = 0
    for raw in rescue_candidates:
        try:
            queued = _save_small_scrape_pair(user_id, dataset_id, raw, prompt)
        except Exception:
            rescue_failed += 1
            logger.exception('small-image rescue save failed for dataset %s', dataset_id)
            continue
        if queued:
            rescue_queued += 1
        else:
            rescue_failed += 1
    if rescue_candidates:
        _sync_generate_activity(dataset_id)
    return {'imported': len(ids), 'rescue_queued': rescue_queued,
            'rescue_failed': rescue_failed, 'skipped': skipped}


def _parse_classify(raw):
    try:
        start = raw.index('{')
        obj = json.loads(raw[start:raw.index('}', start) + 1])
    except (ValueError, AttributeError):
        return 'unknown', None, {}, {}
    fr = obj.get('framing')
    fr = fr if fr in ('face', 'bust', 'body', 'back') else 'unknown'
    coverage = {}
    aliases = {
        'angle': {'3/4': 'three-quarter', 'three quarter': 'three-quarter'},
        'lighting': {'golden hour': 'golden-hour', 'low light': 'low-light'},
    }
    for key, allowed in COVERAGE_VALUES.items():
        value = str(obj.get(key) or '').strip().lower()
        value = aliases.get(key, {}).get(value, value)
        if value in allowed:
            coverage[key] = value
    # Preserve the historical human-facing label verbatim (e.g. "3/4, smile")
    # while storing normalized machine values ("three-quarter") in coverage_json.
    label = ', '.join(str(obj.get(k)).strip() for k in ('angle', 'expression') if obj.get(k))
    confidence = {}
    raw_confidence = obj.get('confidence') if isinstance(obj.get('confidence'), dict) else {}
    for key in ('framing', *COVERAGE_VALUES):
        value = raw_confidence.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            confidence[key] = round(max(0.0, min(1.0, float(value))), 3)
    return fr, (label or None), coverage, confidence


def classify_images(user_id, dataset_id):
    """Classify imported corpus coverage via Qwen3-VL. Returns count."""
    try:
        from .vision_ollama import describe_image_ollama, unload_vision_model
    except ImportError:
        raise RuntimeError('vision (Ollama) service not configured/available yet')
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return 0
    candidates = FaceDatasetImage.query.filter_by(
        dataset_id=dataset_id, source='import').all()
    rows = [row for row in candidates
            if row.filename and (not row.framing or len(parse_coverage(row.coverage_json)) < 6)]
    n = 0
    # Persistent progress indicator (survives a page reload): try/finally guarantees
    # end() runs even if the batch raises → no phantom "Classifying…" spinner.
    token = dataset_activity.begin(dataset_id, 'classify', total=len(rows))
    try:
        for i, img in enumerate(rows):
            dataset_activity.progress(token, done=i + 1)
            path = _img_path(img) if img.filename else ''
            if not os.path.exists(path):
                continue
            with open(path, 'rb') as fh:
                raw = describe_image_ollama(fh.read(), CLASSIFY_PROMPT, num_predict=1200,
                                            prefer_json=True, keep_alive=_VISION_BATCH_KEEPALIVE)
            if not (raw or '').strip():
                # Échec vision (Ollama indisponible) ≠ « framing indéterminé » :
                # on laisse framing=None (retry possible) au lieu d'écrire 'unknown'
                # définitivement, qui bloquerait toute reclassification.
                continue
            framing, label, coverage, confidence = _parse_classify(raw)
            img.framing = framing
            img.variation_label = label
            img.coverage_json = json.dumps(coverage, ensure_ascii=False, sort_keys=True)
            img.coverage_value = 'green' if coverage else 'unknown'
            img.coverage_provenance = json.dumps({
                'source': 'vision',
                'model': cfg.get('ollama.vision_model'),
                'recorded_at': datetime.now(timezone.utc).isoformat(),
                'confidence': confidence,
            }, ensure_ascii=False, sort_keys=True)
            db.session.commit()
            n += 1
    finally:
        unload_vision_model()  # libère la VRAM pour ComfyUI en fin de batch
        dataset_activity.end(token)
    return n


# --- Captioning (JoyCaption / Qwen3-VL, backend picked in Settings) --------
# --- Concept-omission guarantee (ban-list + verify + corrective rewrite) -----
# Negative prompting ALONE leaks (~35% measured e2e on 3 unseen concepts): the
# robustness comes from a deterministic OUTPUT check + targeted correction. Pipeline
# per caption: regex detection (ban-list) -> if leak, Qwen rewrite naming the leaked
# words (<=2 tries) -> mechanical safety net (drop the offending clause). The Qwen
# calls are threaded in via `describe` (our vision seam is a local import inside the
# caption batch); `describe=None` degrades to mechanical scrub only (backend 'joycaption').

# The abliterated Qwen3-VL SOMETIMES emits its reasoning trace ("the task says... we
# need to remove...") or an infinite loop instead of the refined caption - seen ~1/4
# of images. We detect these unusable outputs to fall back on a DIRECT Qwen caption.
# Matches the reasoning/meta phrasings the abliterated Qwen leaks INSTEAD of a caption.
# Widened after real leaks slipped through ("Yes, this describes…", "The original caption
# says…", "Now, check for…", "I think this works"): allow words between "the task/caption"
# and its verb, and add the yes/now/check/i-think markers. Descriptive prose essentially
# never contains these, so a false reject just falls back to a direct caption - cheap.
_REFINE_REASONING_RE = re.compile(
    r'(?:'
    r'\bthe (?:problem|instruction|task|draft|original|caption)(?:\s+\w+){0,4}\s+'
    r'(?:says?|said|mentions?|has|reads?|describes?|is)\b'
    r'|\bwe (?:need|can|should) to (?:remove|rephrase|avoid|describe|keep)'
    r'|\bso we (?:need|can|should)\b'
    r'|\blet me\b|\brephrase\b|\bwait,|\bnow,\s|\bcheck for\b'
    r'|\bi think\b|\bi need to\b|\byes,\s+(?:this|that|the|we|it|but)'
    r')', re.I)

# A concept caption is scene-exhaustive prose; anything this short is a degenerate
# output (e.g. "taking a picture") that just names the concept - never a real caption.
_MIN_CONCEPT_CAPTION_CHARS = 40


def _refine_output_ok(text, prior) -> bool:
    """True if `text` looks like a CLEAN caption - not the Qwen reasoning trace, not a
    degenerate one-liner, not a loop/rambling (bounded to ~2x the source caption `prior`)."""
    t = (text or '').strip()
    if len(t) < _MIN_CONCEPT_CAPTION_CHARS or _REFINE_REASONING_RE.search(t):
        return False
    return len(t) <= 2 * len(prior or '') + 400


def _usable_caption(text) -> bool:
    """A committable concept caption: non-empty prose that is NOT a reasoning trace.
    Length is deliberately NOT gated here - a legitimately terse caption left after the
    clause-scrub must still commit; only the refine-vs-fallback choice (_refine_output_ok)
    weighs length. A degenerate "taking a picture" is handled upstream: the ban-list
    scrubs the concept out, leaving an empty string this rejects."""
    t = (text or '').strip()
    return bool(t) and not _REFINE_REASONING_RE.search(t)


# Words from concept_desc that are never discriminating (articles + generic adjectives
# a legit caption uses elsewhere: "bare shoulders", "full-body"...).
_TERMS_STOP = frozenset((
    'the', 'a', 'an', 'and', 'or', 'of', 'in', 'on', 'at', 'by', 'with', 'to', 'from',
    'that', 'this', 'as', 'is', 'are', 'his', 'her', 'their', 'its', 'it', 'one',
    'act', 'shown', 'worn', 'being', 'person', 'subject', 'focal', 'point', 'visible',
    'bare', 'exposed', 'full', 'close', 'closeup', 'close-up', 'wearing', 'showing'))


# A concept training caption must describe the SUBJECT, never the act of image capture.
# The abliterated Qwen reliably leaks capture-language ("holding a phone to frame the
# shot", "point-of-view mirror", "capturing her reflection") that the LLM ban-list
# expansion never fully enumerates - for "a candid mirror selfie" it returned only
# mirror/self-* variants, so phone/smartphone/camera/reflection leaked into ~45/54
# captions. This DETERMINISTIC lexicon is unioned into the ban-list whenever the concept
# is photographic (selfie/mirror/photo/portrait/pov/camera/phone), so those words are
# ALWAYS scrubbed regardless of the LLM. Reproducible from a fresh clone - no reliance on
# the flaky expansion for words we already know.
_CAPTURE_TRIGGERS = ('selfie', 'mirror', 'photo', 'picture', 'portrait', 'camera',
                     'phone', 'pov', 'point of view', 'snapshot', 'webcam', 'pic ')
_CAPTURE_LEXICON = frozenset((
    'selfie', 'self-portrait', 'self-portraiture', 'self-photograph', 'self-shot',
    'mirror', 'reflection', 'reflected', 'reflective surface',
    'phone', 'smartphone', 'cellphone', 'cell phone', 'mobile phone', 'iphone',
    'camera', 'webcam', 'front-facing', 'pov', 'point of view', 'point-of-view'))


def _fallback_concept_terms(desc) -> list:
    """Minimal ban-list WITHOUT the LLM: the meaningful words of concept_desc itself
    (always included, even when the LLM expansion succeeds - the user's words are the
    ground truth), PLUS the capture lexicon when the concept is photographic, PLUS the
    derived body/pose lexical field (so a POSE concept's periphrases - "knees lifted",
    "feet raised", "thighs" for "leg behind head position" - are scrubbed even though the
    description never spells them, and the LLM expansion is FORBIDDEN from listing pose
    words). Deterministic, reproducible from a fresh clone - the leg_behind fix."""
    d = (desc or '').lower()
    words = re.split(r'[^a-zA-Z-]+', d)
    terms = {w.strip('-') for w in words
             if len(w.strip('-')) >= 3 and w.strip('-') not in _TERMS_STOP}
    if any(k in d for k in _CAPTURE_TRIGGERS):
        terms |= _CAPTURE_LEXICON
    terms |= set(concept_lexical_field(desc))
    return sorted(terms)


def _concept_terms_re(terms):
    """Leak-detection regex: word boundaries, space/hyphen interchangeable ("two-piece"
    <-> "two piece"), plurals/-s/-es/-ing/-ed tolerated. None if the list is empty."""
    pats = []
    for t in terms or []:
        t = (t or '').strip().lower()
        if len(t) < 3:
            continue
        p = re.escape(t).replace(r'\ ', r'[\s-]+').replace(r'\-', r'[\s-]+')
        pats.append(p)
    if not pats:
        return None
    return re.compile(r'\b(?:' + '|'.join(pats) + r')(?:e?s|ing|ed)?\b', re.I)


def _scrub_concept_clauses(caption, leak_re):
    """MECHANICAL net: drop the clauses (segments between , ; .) containing a forbidden
    term - the whole clause, not just the word, to keep grammatical prose. If it destroys
    too much (<30 chars), remove only the words."""
    parts = re.split(r'([.;,])', caption or '')
    kept = []
    for i in range(0, len(parts), 2):
        seg = parts[i]
        punc = parts[i + 1] if i + 1 < len(parts) else ''
        if seg.strip() and leak_re.search(seg):
            continue
        kept.append(seg + punc)
    out = re.sub(r'\s{2,}', ' ', ''.join(kept)).strip(' ,;')
    if len(out) >= 30:
        return out
    out = re.sub(r'\s{2,}', ' ', leak_re.sub('', caption or '')).strip(' ,;')
    return out


def _parse_terms_json(raw) -> list:
    """Extract the term list from an LLM blocklist reply. Tolerates noise around the
    object AND — critically for the abliterated Qwen, which frequently LOOPS and never
    closes the JSON array (so json.loads fails) — salvages the quoted strings directly,
    KEEPING their order: the model emits the good, concept-specific terms first, then
    combinatorial padding ("mirror selfie shot", "self-portrait photograph"…). Ordered
    de-dup (the loop repeats), stopwords dropped, capped so the padding can't dominate."""
    raw = raw or ''
    terms = None
    start, end = raw.find('{'), raw.rfind('}')
    if 0 <= start < end:
        try:
            data = json.loads(raw[start:end + 1])
            if isinstance(data, dict) and isinstance(data.get('terms'), list):
                terms = data['terms']
        except ValueError:
            terms = None
    if terms is None:
        # Unclosed/looping array → pull the quoted strings after "terms" in order.
        m = re.search(r'"terms"\s*:\s*\[(.*)', raw, re.S)
        terms = re.findall(r'"([^"\\]{1,60})"', m.group(1) if m else raw)
    out, seen = [], set()
    for t in terms:
        if not isinstance(t, str):
            continue
        t = t.strip().lower()
        if 3 <= len(t) <= 40 and t not in _TERMS_STOP and t not in seen:
            seen.add(t)
            out.append(t)
            if len(out) >= 25:
                break
    return out


def _get_concept_terms(ds, image_path=None, describe=None) -> list:
    """Dataset ban-list: union of (LLM expansion cached in ds.concept_terms) and (words
    of concept_desc). The expansion runs ONCE (vision model already warm in the GPU
    window, the image is just a vehicle - the prompt ignores it) and is cached ONLY if it
    succeeds (a failure retries next batch). `describe` is our describe_image_ollama seam;
    None -> fallback words only (no LLM call)."""
    base = _fallback_concept_terms(ds.concept_desc)
    stored = []
    if getattr(ds, 'concept_terms', None):
        try:
            stored = [t for t in json.loads(ds.concept_terms) if isinstance(t, str)]
        except ValueError:
            stored = []
    if stored:
        return sorted(set(stored) | set(base))
    if image_path and describe is not None:
        try:
            with open(image_path, 'rb') as fh:
                raw = describe(
                    fh.read(),
                    EXPAND_CONCEPT_TERMS_PROMPT.format(concept=(ds.concept_desc or '').strip()),
                    # 1200 is ample for a 6-15 term list; keeping it tight bounds the
                    # abliterated model's combinatorial loop so the salvage in
                    # _parse_terms_json keeps the good leading terms.
                    num_predict=1200, prefer_json=True, fmt='json',
                    keep_alive=_VISION_BATCH_KEEPALIVE)
        except OSError:
            raw = ''
        expanded = _parse_terms_json(raw)
        if expanded:
            ds.concept_terms = json.dumps(expanded)
            db.session.commit()
            logger.info('concept terms: %d terms generated for ds%s', len(expanded), ds.id)
            return sorted(set(expanded) | set(base))
        logger.info('concept terms: empty LLM expansion for ds%s -> desc fallback', ds.id)
    return base


def _enforce_concept_omission(caption, leak_re, image_bytes, concept_desc, describe=None):
    """Guarantee omission: detect forbidden terms in `caption`, ask Qwen for a rewrite
    that NAMES the offending words (<=2 tries, kept by _refine_output_ok), then a
    mechanical net (clause drop). Returns the caption (unchanged if no leak). `describe`
    is the vision seam; None -> skip the LLM fix, go straight to the mechanical scrub."""
    if not leak_re or not (caption or '').strip():
        return caption
    if describe is not None:
        for _ in range(2):
            leaked = sorted({m.group(0).lower() for m in leak_re.finditer(caption)})
            if not leaked:
                return caption
            fixed = ''
            try:
                fixed = describe(
                    image_bytes,
                    CAPTION_LEAK_FIX_PROMPT.format(existing=caption, concept=concept_desc,
                                                   leaked=', '.join(leaked)),
                    num_predict=5000, keep_alive=_VISION_BATCH_KEEPALIVE)
            except Exception:  # noqa: BLE001 - best-effort correction
                fixed = ''
            fixed = (fixed or '').strip().strip('"').strip()
            if _refine_output_ok(fixed, caption):
                caption = fixed
    if leak_re.search(caption):
        caption = _scrub_concept_clauses(caption, leak_re)
    return caption


def _caption_concept(ds, force, backend, token=None):
    """Concept caption pipeline (INVERTED logic): describe everything INCLUDING identity
    but OMIT the recurring act so it binds to the trigger. JoyCaption is literal (it NAMES
    the act/fluids/watermark) -> its drafts are REFINED by Qwen, then every caption passes
    the ban-list omission guarantee. Backend gating is honored:
      - 'joycaption' -> Joy drafts only + mechanical scrub (no Qwen calls);
      - 'ollama'     -> Joy skipped, every image direct-Qwen + enforcement;
      - 'auto'       -> Joy drafts refined by Qwen, no-Joy images direct-Qwen, all enforced."""
    concept_desc = (ds.concept_desc or '').strip()
    # Dynamic omission clause: for a POSE concept the generic "describe their pose and
    # body position" line would instruct the VLM to describe the very concept - the
    # builder folds in a concept-specific negative ("do NOT describe the position of the
    # legs/knees/feet…") that overrides it. Byte-identical to the old prompt for non-body
    # concepts. This is the generation-side half of the leg_behind fix.
    cap_prompt = caption_prompt_for_concept(concept_desc)
    q = FaceDatasetImage.query.filter_by(dataset_id=ds.id, status='keep')
    if not force:
        q = q.filter((FaceDatasetImage.caption.is_(None)) | (FaceDatasetImage.caption == ''))
    todo = [(img, _img_path(img)) for img in q.all() if img.filename]
    todo = [(img, p) for img, p in todo if p and os.path.exists(p)]
    if not todo:
        return 0
    # Total for the persistent progress indicator (token owned by the caller).
    dataset_activity.progress(token, total=len(todo),
                              detail=f'Preparing {len(todo)} concept caption(s)…')
    n = 0
    remaining = list(todo)
    refine_targets = []  # (img, p, joycap) -> Joy draft refined by Qwen
    # 1) JoyCaption batch (draft) when the backend allows it.
    if backend in ('auto', 'joycaption'):
        jc = {}
        try:
            from .joycaption import caption_images_joycaption, is_available
            if is_available():
                dataset_activity.progress(
                    token, detail=f'Loading JoyCaption model and captioning {len(todo)} images…')
                jc = caption_images_joycaption([p for _, p in todo], prompt=cap_prompt)
            elif backend == 'joycaption':
                raise RuntimeError('JoyCaption backend is not available - check the ai-toolkit folder in Settings')
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning('caption concept: JoyCaption indisponible (%s)', e)
        still = []
        for img, p in remaining:
            cap = (jc.get(p) or '').strip().strip('"').strip()
            if cap:
                refine_targets.append((img, p, cap))
            else:
                still.append((img, p))
        remaining = still
    # 2a) Backend 'joycaption' forced: no Qwen. Store Joy drafts scrubbed mechanically
    #     (leak_re from the desc words only) - respects "no Ollama fallback".
    if backend == 'joycaption':
        leak_re = _concept_terms_re(_fallback_concept_terms(concept_desc))
        for img, p, joycap in refine_targets:
            dataset_activity.bump(token)
            try:
                with open(p, 'rb') as fh:
                    data = fh.read()
            except OSError:
                data = b''
            final = _enforce_concept_omission(joycap, leak_re, data, concept_desc) or joycap
            img.caption = final[:CAPTION_MAX_CHARS]
            db.session.commit()
            n += 1
        return n
    # 2b) Qwen passes ('auto'/'ollama'): refine Joy drafts, direct-caption the rest, all
    #     enforced. One model load -> unload once at the end.
    if refine_targets or remaining:
        try:
            from .vision_ollama import describe_image_ollama, unload_vision_model
        except ImportError:
            raise RuntimeError('vision (Ollama) service not configured/available yet')
        # Ban-list (LLM expansion cached + desc words) -> leak regex, compiled ONCE per
        # batch, AFTER the Joy subprocess finished (never two models in VRAM at once).
        sample = refine_targets[0][1] if refine_targets else remaining[0][1]
        leak_re = _concept_terms_re(_get_concept_terms(ds, image_path=sample,
                                                       describe=describe_image_ollama))
        try:
            for img, p, joycap in refine_targets:
                dataset_activity.bump(token)
                with open(p, 'rb') as fh:
                    data = fh.read()
                refined = ''
                try:
                    refined = describe_image_ollama(
                        data, CAPTION_REFINE_CONCEPT_PROMPT.format(existing=joycap,
                                                                   concept=concept_desc),
                        num_predict=5000, keep_alive=_VISION_BATCH_KEEPALIVE,
                        timeout=(10, 300))
                except Exception as e:  # noqa: BLE001 - refine best-effort
                    logger.warning('caption concept: Qwen refine failed (%s)', e)
                refined = (refined or '').strip().strip('"').strip()
                if _refine_output_ok(refined, joycap):
                    final = refined
                else:
                    # Unusable refine (reasoning trace / loop) -> direct Qwen caption
                    # (natively omits the concept), else keep the Joy draft.
                    logger.info('caption concept: refine rejected -> direct Qwen (image %s)', img.id)
                    alt = ''
                    try:
                        alt = describe_image_ollama(data, cap_prompt, num_predict=2000,
                                                    keep_alive=_VISION_BATCH_KEEPALIVE,
                                                    timeout=(10, 300))
                    except Exception:  # noqa: BLE001
                        alt = ''
                    alt = (alt or '').strip().strip('"').strip()
                    final = alt or joycap
                final = _enforce_concept_omission(final, leak_re, data, concept_desc,
                                                  describe=describe_image_ollama) or final
                if not _usable_caption(final):
                    # Refine AND direct both unusable → fall back to the Joy draft (clean
                    # prose), scrubbed of any leak; leave blank if even that fails.
                    final = _enforce_concept_omission(joycap, leak_re, data, concept_desc,
                                                      describe=describe_image_ollama) or joycap
                    if not _usable_caption(final):
                        # force=re-do-all: overwrite any stale pre-fix caption with blank
                        # (trigger-only is valid for a concept LoRA) rather than retain it.
                        if force and (img.caption or ''):
                            img.caption = ''
                            db.session.commit()
                        logger.info('caption concept: no usable caption for image %s -> left blank', img.id)
                        continue
                img.caption = final[:CAPTION_MAX_CHARS]
                db.session.commit()
                n += 1
            for img, p in remaining:
                dataset_activity.bump(token)
                with open(p, 'rb') as fh:
                    data = fh.read()
                cap = describe_image_ollama(
                    data, cap_prompt, num_predict=2000,
                    keep_alive=_VISION_BATCH_KEEPALIVE,
                    auto_start_local=True, timeout=(10, 300))
                cap = (cap or '').strip().strip('"').strip()
                if cap:
                    cap = _enforce_concept_omission(cap, leak_re, data, concept_desc,
                                                    describe=describe_image_ollama) or cap
                if _usable_caption(cap):
                    img.caption = cap[:CAPTION_MAX_CHARS]
                    db.session.commit()
                    n += 1
                else:
                    if force and (img.caption or ''):
                        img.caption = ''
                        db.session.commit()
                    logger.info('caption concept: no usable direct caption for image %s -> left blank', img.id)
        finally:
            unload_vision_model()  # libère la VRAM pour ComfyUI en fin de batch
    return n


def caption_images(user_id, dataset_id, force=False, mode=None):
    """Caption les images gardees. Defaut: seulement celles SANS caption ; force=True
    re-capte TOUTES les gardees (ecrase) - pour rejouer apres un changement de prompt.
    Chaque caption passe par drop_identity_sentences (retire une eventuelle phrase
    d'identite isolee).

    `captioning.backend` (réglages) pilote qui capte quoi :
      - 'none'       -> désactivé, RuntimeError (mappée 409 par la route).
      - 'joycaption' -> JoyCaption seul, PAS de repli Ollama.
      - 'ollama'     -> Ollama (Qwen3-VL) seul, JoyCaption jamais tenté.
      - 'auto'       -> comportement historique : JoyCaption en priorité,
                        fallback Ollama pour les images qu'il n'a pas captées."""
    backend = (cfg.get('captioning.backend') or 'auto').lower()
    if backend == 'none':
        raise RuntimeError('No captioning backend configured')
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return 0
    # Dataset CONCEPT : logique INVERSÉE (décrire tout SAUF l'acte récurrent → il se lie
    # au trigger). Pipeline dédié Joy→Qwen + garantie d'omission (ban-list) : entièrement
    # à part du chemin character ci-dessous. Respecte le backend gating.
    # The persistent indicator is owned HERE (begin/finally) so the concept body stays
    # unindented; it only feeds progress via the passed token.
    if is_concept(ds):
        token = dataset_activity.begin(
            dataset_id, 'recaption' if force else 'caption',
            detail='Preparing concept captioning…')
        started = time.monotonic()
        logger.info('captioning started: dataset=%s backend=%s force=%s kind=concept',
                    dataset_id, backend, force)
        try:
            n = _caption_concept(ds, force, backend, token=token)
            logger.info('captioning finished: dataset=%s backend=%s captioned=%s elapsed=%.1fs',
                        dataset_id, backend, n, time.monotonic() - started)
            return n
        except Exception:
            logger.exception('captioning failed: dataset=%s backend=%s kind=concept elapsed=%.1fs',
                             dataset_id, backend, time.monotonic() - started)
            raise
        finally:
            dataset_activity.end(token)
    # Style de caption : prose (Z-Image) vs tags booru (SDXL booru-native type bigLove).
    # Défaut AUTO selon le type entraîné ; un mode explicite (UI) l'emporte.
    ttype = (getattr(ds, 'train_type', None) or 'zimage').lower()
    mode = (mode or ('booru' if ttype == 'sdxl' else 'prose')).lower()
    style = is_style(ds)
    if style:
        # Dataset STYLE : captions de CONTENU pur — le rendu n'est jamais décrit (le
        # prompt porte la règle) pour qu'il soit absorbé par le LoRA. AUCUN nettoyage
        # d'identité : les sujets varient, leur description EST le contenu contrôlable.
        cap_prompt = caption_prompt_for_style(mode)
        def cleaner(text):
            return text
    else:
        # Fidélité corps : le prompt bannit EN PLUS les marques corporelles permanentes
        # (tatouages/cicatrices/piercings…) et le post-filtre les retire — elles doivent
        # se lier au trigger, pas aux mots (même principe que le visage).
        body = is_body_fidelity(ds)
        cap_prompt = caption_prompt_for(mode, body=body)
        base_cleaner = drop_identity_tags if mode == 'booru' else drop_identity_sentences
        def cleaner(text):
            return base_cleaner(text, body=body)
    q = FaceDatasetImage.query.filter_by(dataset_id=dataset_id, status='keep')
    if not force:
        q = q.filter((FaceDatasetImage.caption.is_(None)) | (FaceDatasetImage.caption == ''))
    rows = q.all()
    todo = [(img, _img_path(img)) for img in rows if img.filename]
    todo = [(img, p) for img, p in todo if p and os.path.exists(p)]
    if not todo:
        return 0
    # Persistent progress indicator (survives a page reload): 'recaption' when force
    # overwrites existing captions, else 'caption'. try/finally guarantees end() runs
    # even if the vision pass raises → no phantom "Captioning…" spinner after a crash.
    token = dataset_activity.begin(
        dataset_id, 'recaption' if force else 'caption', total=len(todo),
        detail=f'Preparing to caption {len(todo)} image(s)…')
    started = time.monotonic()
    logger.info('captioning started: dataset=%s backend=%s mode=%s force=%s images=%s',
                dataset_id, backend, mode, force, len(todo))
    try:
        n = 0
        remaining = todo
        # 1) JoyCaption en BATCH (un seul chargement du 8B NF4, via le venv ai-toolkit) -
        # sauté entièrement quand le backend force 'ollama'.
        if backend in ('auto', 'joycaption'):
            jc = {}
            try:
                from .joycaption import caption_images_joycaption, is_available
                if is_available():
                    dataset_activity.progress(
                        token,
                        detail=f'Loading JoyCaption model and captioning {len(todo)} images…')
                    # Consigne « ne décris pas le visage » → les traits se lient au trigger,
                    # pas aux mots de la caption (deep-research 2026-06-14).
                    jc = caption_images_joycaption([p for _, p in todo], prompt=cap_prompt)
                elif backend == 'joycaption':
                    # Explicit choice, explicit failure: a user who forced 'joycaption' in
                    # Settings must be told it's unavailable, not get a silent 0 (only
                    # 'auto' is allowed to fall back to Ollama quietly).
                    raise RuntimeError('JoyCaption backend is not available - check the ai-toolkit folder in Settings')
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning('caption_images: JoyCaption indisponible (%s)', e)
            still = []
            for img, p in remaining:
                cap = (jc.get(p) or '').strip().strip('"').strip()
                if cap:
                    cleaned = cleaner(cap) or cap
                    img.caption = cleaned[:CAPTION_MAX_CHARS]
                    db.session.commit()
                    n += 1
                    dataset_activity.bump(token)   # this image is captioned (done)
                else:
                    still.append((img, p))
            remaining = still
            dataset_activity.progress(
                token, detail=f'JoyCaption finished; {len(remaining)} image(s) remaining…')
            if backend == 'joycaption':  # backend forcé JoyCaption -> pas de repli Ollama
                logger.info('captioning finished: dataset=%s backend=%s captioned=%s elapsed=%.1fs',
                            dataset_id, backend, n, time.monotonic() - started)
                return n
        # 2) Ollama (Qwen3-VL) pour les images non couvertes par JoyCaption ('auto'),
        # ou pour TOUT le lot si le backend force 'ollama'.
        if remaining:
            try:
                from .vision_ollama import describe_image_ollama, unload_vision_model
            except ImportError:
                raise RuntimeError('vision (Ollama) service not configured/available yet')
            try:
                for index, (img, p) in enumerate(remaining, 1):
                    dataset_activity.progress(
                        token,
                        detail=f'Captioning with Ollama — image {index}/{len(remaining)}…')
                    with open(p, 'rb') as fh:
                        cap = describe_image_ollama(
                            fh.read(), cap_prompt, num_predict=2000,
                            keep_alive=_VISION_BATCH_KEEPALIVE,
                            auto_start_local=(index == 1), timeout=(10, 300))
                    cap = (cap or '').strip().strip('"').strip()
                    if cap:
                        cleaned = cleaner(cap) or cap
                        img.caption = cleaned[:CAPTION_MAX_CHARS]
                        db.session.commit()
                        n += 1
                    dataset_activity.bump(token)   # image handled (captioned or not)
            finally:
                unload_vision_model()  # libère la VRAM pour ComfyUI en fin de batch
        logger.info('captioning finished: dataset=%s backend=%s captioned=%s elapsed=%.1fs',
                    dataset_id, backend, n, time.monotonic() - started)
        return n
    except Exception:
        logger.exception('captioning failed: dataset=%s backend=%s elapsed=%.1fs',
                         dataset_id, backend, time.monotonic() - started)
        raise
    finally:
        dataset_activity.end(token)


# --- Face similarity scoring (InsightFace antelopev2, CPU subprocess) -------
def _identity_reference_paths(ds) -> list[str]:
    ref_path = _ref_path(ds)
    paths = [ref_path] if os.path.exists(ref_path) else []
    for filename in extra_ref_filenames(ds):
        candidate = os.path.join(_dataset_dir(ds.id), filename)
        if os.path.exists(candidate) and candidate not in paths:
            paths.append(candidate)
    pinned = (FaceDatasetImage.query.filter_by(
        dataset_id=ds.id, status='keep', anchor_decision='pinned')
        .filter(FaceDatasetImage.filename.isnot(None)).all())
    for anchor in pinned[:4]:
        candidate = _img_path(anchor)
        if os.path.exists(candidate) and candidate not in paths:
            paths.append(candidate)
    return paths


def _face_result_payload(result):
    face = {key: result.get(key) for key in (
        'state', 'sim', 'det', 'bbox_frac', 'yaw', 'face_count',
        'face_sharpness', 'face_exposure', 'face_clipped',
        'face_width', 'face_height') if result.get(key) is not None}
    state = face.get('state')
    sharp = face.get('face_sharpness')
    exposure = face.get('face_exposure')
    if state in ('low_det', 'unreadable', 'error') or (
            sharp is not None and sharp < 25) or (
            exposure is not None and exposure < 25):
        face['quality'] = 'red'
    elif state in ('no_face', 'too_small', 'extreme_pose', 'multi_face') or (
            sharp is not None and sharp < 45) or (
            exposure is not None and exposure < 45):
        face['quality'] = 'amber'
    else:
        face['quality'] = 'green'
    return face


def _persist_face_result(img, result):
    img.face_state = result.get('state')
    img.face_score = result.get('sim')
    analysis = parse_analysis(img.analysis_json)
    face = _face_result_payload(result)
    analysis['face'] = face
    img.analysis_json = analysis_json(analysis)


def analyze_faces(user_id, dataset_id) -> dict:
    """Score reviewable images vs a small identity reference set (InsightFace CPU).
    Persiste face_score (cosinus brut, None si non note) + face_state. Lot A : AUCUNE
    suppression. Tourne sur CPU -> pas de fenetre GPU. Retourne {state: count}."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if not ds.ref_filename:
        raise ValueError('reference photo missing')
    ref_path = _ref_path(ds)
    if not os.path.exists(ref_path):
        raise ValueError('reference photo missing')
    rows = (FaceDatasetImage.query.filter_by(dataset_id=dataset_id)
            .filter(FaceDatasetImage.status.in_(('pending', 'keep')))
            .filter(FaceDatasetImage.filename.isnot(None)).all())
    # A reconstruction comparison is a frozen QA snapshot. Re-running the general
    # face pass must not overwrite either side's score while its recommendation is
    # awaiting a decision; resolved winners can be scored normally after editing.
    unresolved_improvement_ids = _unresolved_image_improvement_ids(dataset_id)
    rows = [row for row in rows if row.id not in unresolved_improvement_ids]
    by_path = {}
    for img in rows:
        p = _img_path(img)
        if os.path.exists(p):
            by_path[p] = img
    try:
        from .face_similarity import score_dataset_faces
    except ImportError:
        raise RuntimeError('face scoring service not configured/available yet')
    # scoring_error ({kind, detail} | None) remonte jusqu'au toast : un scorer
    # cassé doit dire POURQUOI, pas « 0 analyzed » en vert.
    # Persistent indicator (survives reload). The scoring is a single CPU subprocess
    # (opaque — done stays 0 during it, then fills as results are committed); try/
    # finally clears the indicator even if scoring raises.
    token = dataset_activity.begin(dataset_id, 'analyze_faces', total=len(by_path))
    try:
        # Primary + explicit reference photos + pinned, accepted imports form a
        # conservative identity centroid. This is more stable than trusting a single
        # expression or camera angle while keeping the set human-controlled.
        ref_paths = _identity_reference_paths(ds)
        results, scoring_error = score_dataset_faces(
            ref_path, list(by_path.keys()), ref_paths=ref_paths)
        counts = {}
        for p, img in by_path.items():
            dataset_activity.bump(token)
            r = results.get(p)
            if not r:
                continue
            _persist_face_result(img, r)
            db.session.commit()
            counts[img.face_state] = counts.get(img.face_state, 0) + 1
        return counts, scoring_error
    finally:
        dataset_activity.end(token)


# --- Watermark auto-correction (V1) ----------------------------------------
# Scraped images often carry an OVERLAID watermark (site logo, URL, @username, studio
# text) that the LoRA would learn. V1 = detect (Qwen3-VL bbox) then route removal by
# cost/risk: CROP a border-band mark (PIL pur, invents no pixel), LaMa-inpaint a small
# off-center mark (non-generative, only masked pixels change), else leave it for manual
# review. NO YOLO, NO generative inpaint -- those are V2.
WATERMARK_BORDER_BAND = 0.20       # a mark within this outer strip is croppable
WATERMARK_MAX_INPAINT_AREA = 0.10  # bbox area above this fraction -> manual review
WATERMARK_MIN_SIDE = 768           # never crop a side below this (ai-toolkit only downscales)
WATERMARK_REGION_LIMIT = 32
WATERMARK_REGION_MIN_SIDE = 0.005


def normalize_watermark_regions(value, *, allow_null=True) -> list[list[float]] | None:
    if value is None:
        if allow_null:
            return None
        raise ValueError('regions must be a list')
    if not isinstance(value, list) or len(value) > WATERMARK_REGION_LIMIT:
        raise ValueError('regions must contain at most 32 boxes')
    out = []
    for box in value:
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError('each region must be [x1,y1,x2,y2]')
        try:
            invalid_number = any(
                isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) for v in box
            )
        except OverflowError:
            invalid_number = True
        if invalid_number:
            raise ValueError('region coordinates must be finite numbers')
        x1, y1, x2, y2 = map(float, box)
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError('region coordinates must be ordered within [0,1]')
        min_side = Decimal(str(WATERMARK_REGION_MIN_SIDE))
        if (Decimal(str(x2)) - Decimal(str(x1)) < min_side
                or Decimal(str(y2)) - Decimal(str(y1)) < min_side):
            raise ValueError('region is too small')
        out.append([round(v, 4) for v in (x1, y1, x2, y2)])
    return out


def set_watermark_regions(user_id, dataset_id, image_id, regions) -> dict | None:
    """Atomically replace a detected image's manual watermark-region override."""
    owned_query = (FaceDatasetImage.query
                   .join(FaceDataset, FaceDatasetImage.dataset_id == FaceDataset.id)
                   .filter(FaceDatasetImage.id == image_id,
                           FaceDatasetImage.dataset_id == dataset_id,
                           FaceDataset.user_id == str(user_id)))
    img = owned_query.one_or_none()
    if not img:
        return None
    if img.watermark_state != 'detected':
        raise RuntimeError('image is no longer detected')
    normalized = normalize_watermark_regions(regions)
    stored = json.dumps(normalized) if normalized is not None else None
    from . import curation_history
    before = curation_history.snapshot(img, ('watermark_regions',))
    updated = (FaceDatasetImage.query
               .filter_by(id=img.id, watermark_state='detected')
               .update({'watermark_regions': stored}, synchronize_session=False))
    if updated != 1:
        db.session.rollback()
        if owned_query.one_or_none() is None:
            return None
        raise RuntimeError('image is no longer detected')
    curation_history.record(
        user_id, img, 'watermark_regions', before,
        {'watermark_regions': stored})
    db.session.commit()
    return _watermark_regions_payload(img)


def _route_watermark(bbox, W, H, *, min_side=WATERMARK_MIN_SIDE):
    """Decide how to remove the watermark at normalized `bbox` (x1,y1,x2,y2) on a
    W x H image. Returns ('crop', (left, top, right, bottom)) | ('lama', None) |
    ('review', None). PURE function (no I/O) so the routing is unit-testable.

    CROP (default, invents no pixel) when the mark sits ENTIRELY inside one outer
    border band (<= WATERMARK_BORDER_BAND of the side) AND the resulting crop keeps
    BOTH sides >= min_side -- we cut the band up to the mark's INNER edge. LaMa when
    the mark is small (area <= WATERMARK_MAX_INPAINT_AREA) and does not straddle the
    image center. Otherwise (large, or on the central subject with no safe crop) ->
    manual review, never a risky auto-edit."""
    x1, y1, x2, y2 = bbox
    px1, py1, px2, py2 = x1 * W, y1 * H, x2 * W, y2 * H
    band = WATERMARK_BORDER_BAND
    # Border-band crops, tried top/bottom/left/right. The kept box is (left,top,right,bottom).
    if y2 <= band and (H - py2) >= min_side and W >= min_side:            # top band
        return 'crop', (0, int(round(py2)), W, H)
    if y1 >= 1 - band and py1 >= min_side and W >= min_side:              # bottom band
        return 'crop', (0, 0, W, int(round(py1)))
    if x2 <= band and (W - px2) >= min_side and H >= min_side:            # left band
        return 'crop', (int(round(px2)), 0, W, H)
    if x1 >= 1 - band and px1 >= min_side and H >= min_side:              # right band
        return 'crop', (0, 0, int(round(px1)), H)
    # Not a safe border crop (off-band, or the crop would fall below min_side).
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    overlaps_center = (x1 < 0.5 < x2) and (y1 < 0.5 < y2)
    if area <= WATERMARK_MAX_INPAINT_AREA and not overlaps_center:
        return 'lama', None
    return 'review', None


def _preserve_original(path) -> None:
    """Copy `path` to a sibling `<stem>.orig<suffix>` before a destructive edit, so the
    watermarked original stays recoverable. The app trash util (send_to_trash) MOVES a
    file -- unusable here since the cleaned image must keep serving from the SAME path
    (and LaMa overwrites it in place) -- so we keep a sibling copy instead. Only written
    ONCE (a re-clean must not clobber the true original with an already-modified one).
    These .orig files carry no DB row, so export/backup (which iterate rows) ignore them."""
    stem, ext = os.path.splitext(path)
    backup = f'{stem}.orig{ext or ".webp"}'
    if not os.path.exists(backup):
        try:
            shutil.copy2(path, backup)
        except OSError as e:
            logger.warning('watermark: could not preserve original %s: %s', path, e)


def _apply_watermark_crop(path, box) -> bool:
    """Crop `path` to `box` (left,top,right,bottom px) and re-save WEBP q92 WITHOUT
    resizing -- the whole point of the crop route is that it invents no pixel (the
    aspect-ratio change is absorbed by ai-toolkit's bucketing). Returns bool."""
    try:
        with Image.open(path) as opened, opened.convert('RGB') as im:
            box = (max(0, int(box[0])), max(0, int(box[1])),
                   min(im.width, int(box[2])), min(im.height, int(box[3])))
            if box[2] - box[0] < 1 or box[3] - box[1] < 1:
                return False
            out = io.BytesIO()
            with im.crop(box) as cropped:
                cropped.save(out, 'WEBP', quality=92)
    except (OSError, ValueError):
        return False
    with open(path, 'wb') as fh:
        fh.write(out.getvalue())
    return True


def detect_watermarks(user_id, dataset_id, *, include_dismissed=False):
    """Scan the KEPT images for an overlaid watermark via Qwen3-VL and persist
    watermark_state ('detected'|'none') + watermark_bbox (JSON normalized box).
    CALLER holds the GPU-exclusive vision window (same as classify/caption). Returns
    {'detected': n, 'none': n, 'checked': n}.

    Images the user already judged NOT a watermark ('dismissed', a false positive
    ruled out in the review lightbox) are SKIPPED so a re-run never re-flags them --
    that's the anti-frustration point. Pass include_dismissed=True to re-examine them
    (a deliberate "check everything again")."""
    try:
        from .vision_ollama import describe_image_ollama, unload_vision_model
    except ImportError:
        raise RuntimeError('vision (Ollama) service not configured/available yet')
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return {'detected': 0, 'none': 0, 'checked': 0}
    rows = (FaceDatasetImage.query.filter_by(dataset_id=dataset_id, status='keep')
            .filter(FaceDatasetImage.filename.isnot(None)).all())
    counts = {'detected': 0, 'none': 0, 'checked': 0}
    # Persistent progress indicator (survives a page reload); try/finally clears it
    # even if the vision pass raises → no phantom "Scanning…" spinner.
    token = dataset_activity.begin(dataset_id, 'watermark_detect', total=len(rows))
    try:
        for i, img in enumerate(rows):
            dataset_activity.progress(token, done=i + 1)
            # Dismissed = a confirmed false positive; don't waste a vision call re-asking
            # (and never silently re-flag it) unless the caller opts back in.
            if not include_dismissed and img.watermark_state == 'dismissed':
                continue
            path = _img_path(img)
            if not os.path.exists(path):
                continue
            with open(path, 'rb') as fh:
                raw = describe_image_ollama(fh.read(), WATERMARK_BBOX_PROMPT, num_predict=400,
                                            prefer_json=True, fmt='json',
                                            keep_alive=_VISION_BATCH_KEEPALIVE)
            if not (raw or '').strip():
                # Vision unreachable/empty != "no watermark" (same reasoning as
                # classify_images): leave the state UNTOUCHED (retry possible) instead
                # of falsely marking every image clean when Ollama is just down.
                continue
            img.watermark_regions = None
            bbox = _parse_watermark_bbox(raw)
            if bbox:
                img.watermark_state = 'detected'
                img.watermark_bbox = json.dumps([round(v, 4) for v in bbox])
                counts['detected'] += 1
            else:
                img.watermark_state = 'none'
                img.watermark_bbox = None
                counts['none'] += 1
            counts['checked'] += 1
            db.session.commit()
    finally:
        unload_vision_model()  # rend la VRAM a ComfyUI en fin de batch
        dataset_activity.end(token)
    return counts


def dismiss_watermarks(user_id, dataset_id, image_ids):
    """Mark 'detected' images as 'dismissed' -- the user ruled, in the review lightbox,
    that the flag is a FALSE positive. Dismissed images drop the 🚩 badge, leave the
    Clean batch, and are skipped by future detect passes (see detect_watermarks) so
    they're never re-flagged. Only 'detected' rows of THIS dataset transition (ids that
    don't belong / aren't detected are silently ignored, like batch_image_action).
    Returns the number of rows dismissed. The bbox is kept (harmless, and a later
    include_dismissed re-scan overwrites it)."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        return 0
    ids = [int(i) for i in (image_ids or [])
           if isinstance(i, (int, float, str)) and str(i).lstrip('-').isdigit()]
    if not ids:
        return 0
    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id, watermark_state='detected')
            .filter(FaceDatasetImage.id.in_(ids)).all())
    from . import curation_history
    batch_id = curation_history.new_batch_id()
    for img in rows:
        before = curation_history.snapshot(
            img, ('watermark_state', 'watermark_regions'))
        img.watermark_state = 'dismissed'
        img.watermark_regions = None
        curation_history.record(
            user_id, img, 'watermark_dismiss', before,
            curation_history.snapshot(
                img, ('watermark_state', 'watermark_regions')),
            batch_id=batch_id)
    if rows:
        db.session.commit()
    return len(rows)


def clean_watermarks(user_id, dataset_id, image_ids=None, device='cpu'):
    """Apply the crop/LaMa/review routing to every image marked 'detected'. Returns
    ({'cropped', 'inpainted', 'needs_review', 'failed', 'skipped'}, error|None) -- same
    tuple contract as score_dataset_faces: `error` is None unless a LaMa inpaint that
    was ATTEMPTED failed (never a silent swallow). Crop stays in PIL; LaMa uses the
    resolved CPU/GPU device. GPU mode is protected by the route's exclusive window.

    LaMa absent (probe False) is NOT an error: LaMa-routed images are counted as
    `skipped` (crop still runs) so the UI can nudge "install the ML extras".

    image_ids (optional): restrict the pass to this subset -- the review lightbox cleans
    ONE image at a time. The filter still requires watermark_state='detected' AND
    dataset ownership, so a stale/foreign id is a no-op (never touches another dataset,
    never re-edits an already-cleaned image). None = every detected image (bulk button)."""
    from . import watermark_lama
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    q = (FaceDatasetImage.query
         .filter_by(dataset_id=dataset_id, watermark_state='detected')
         .filter(FaceDatasetImage.filename.isnot(None)))
    if image_ids is not None:
        ids = [int(i) for i in (image_ids or [])
               if isinstance(i, (int, float, str)) and str(i).lstrip('-').isdigit()]
        q = q.filter(FaceDatasetImage.id.in_(ids or [-1]))   # empty subset -> match nothing
    rows = q.all()
    out = {'cropped': 0, 'inpainted': 0, 'needs_review': 0, 'failed': 0, 'skipped': 0}
    error = None
    lama_ok = watermark_lama.is_available()
    lama_pending = []  # (img, path, bboxes, manual_regions)
    # Persistent progress indicator (survives a page reload). The device is included
    # so the UI can honestly state whether ComfyUI is paused for the GPU pass.
    device_label = 'GPU' if device == 'cuda' else 'CPU'
    token = dataset_activity.begin(
        dataset_id, 'watermark_clean', total=len(rows),
        detail=f'Cleaning watermarks on {device_label}…')
    try:
        for i, img in enumerate(rows):
            dataset_activity.progress(token, done=i + 1)
            path = _img_path(img)
            if img.watermark_regions is not None:
                try:
                    regions = normalize_watermark_regions(
                        _safe_json(img.watermark_regions), allow_null=False,
                    )
                except ValueError as e:
                    out['failed'] += 1
                    error = {'kind': 'failed',
                             'detail': f'invalid watermark regions: {e}'}
                    db.session.commit()
                    continue
                if not regions:
                    out['needs_review'] += 1
                    db.session.commit()
                    continue
                if not os.path.exists(path):
                    out['failed'] += 1
                    db.session.commit()
                    continue
                if not lama_ok:
                    out['skipped'] += 1
                    db.session.commit()
                    continue
                _preserve_original(path)
                lama_pending.append((img, path, regions, True))
                continue
            bbox = _safe_json(img.watermark_bbox)
            if not os.path.exists(path) or not (isinstance(bbox, list) and len(bbox) == 4):
                img.watermark_state = 'failed'
                out['failed'] += 1
                db.session.commit()
                continue
            try:
                with Image.open(path) as im:
                    W, H = im.size
            except (OSError, ValueError):
                img.watermark_state = 'failed'
                out['failed'] += 1
                db.session.commit()
                continue
            route, box = _route_watermark(tuple(bbox), W, H)
            if route == 'crop':
                _preserve_original(path)
                if _apply_watermark_crop(path, box):
                    # NOTE dHash: the perceptual hash used for import-dedupe is recomputed
                    # ON THE FLY from the file (_existing_dhashes / _dhash), NOT stored in a
                    # column -- there is no stored dHash to leave untouched. So after a crop
                    # the dedupe compares against the CLEANED pixels; re-importing the same
                    # watermarked visual is NOT guaranteed to dedupe against it (a border
                    # crop shifts the whole hash). Preserving the original-dHash behaviour the
                    # spec asks for would need a new stored column -> deferred (out of V1 scope).
                    img.watermark_state = 'cleaned'
                    out['cropped'] += 1
                else:
                    img.watermark_state = 'failed'
                    out['failed'] += 1
            elif route == 'lama':
                if not lama_ok:
                    out['skipped'] += 1          # leave state='detected' (crop-only mode)
                else:
                    _preserve_original(path)
                    lama_pending.append((img, path, [bbox], False))
            else:  # 'review' -> stays 'detected' so the badge/count keep flagging it
                out['needs_review'] += 1
            db.session.commit()
        if lama_pending:
            if len(lama_pending) == 1:
                img, path, boxes, manual = lama_pending[0]
                if manual:
                    ok, err = watermark_lama.inpaint_watermarks(
                        path, boxes, **({'device': device} if device != 'cpu' else {}))
                else:
                    ok, err = watermark_lama.inpaint_watermark(
                        path, boxes[0], **({'device': device} if device != 'cpu' else {}))
                results = {path: (ok, err)}
            else:
                results = watermark_lama.inpaint_batch(
                    [{'image_path': path, 'bboxes': boxes}
                     for _img, path, boxes, _manual in lama_pending],
                    device=device,
                )
            for img, path, _boxes, manual in lama_pending:
                ok, err = results.get(path, (False, {'kind': 'failed', 'detail': 'missing inpaint result'}))
                if ok:
                    img.watermark_state = 'cleaned'
                    if manual:
                        img.watermark_regions = None
                    out['inpainted'] += 1
                elif err and err.get('kind') == 'unavailable':
                    out['skipped'] += 1
                else:
                    # Manual correction regions are user-authored retry metadata. Keep
                    # the image detected when LaMa fails so Clean can be retried.
                    if not manual:
                        img.watermark_state = 'failed'
                    out['failed'] += 1
                    if err:
                        error = err
                db.session.commit()
        return out, error
    finally:
        dataset_activity.end(token)


# --- Fan-out generation (Klein edit) ---------------------------------------
def _sync_generate_activity(dataset_id):
    """Reconcile the Klein 'generate' indicator with the dataset's live count of
    in-flight Klein jobs (pending rows that still carry a job_id and have no file
    yet). Klein completions arrive one-by-one on the job-queue monitor thread with
    only a job_id — no batch handle — so we track the honest pending COUNT rather
    than a per-batch job set (duplicated/cancelled completions would corrupt one).
    Called on enqueue, on each completion, and on cancel; the registry TTL is the
    last-resort net. API rows (job_id is NULL) are excluded — those batches own a
    separate begin()/end() 'generate' entry from _run_nanobanana_batch."""
    pending = (FaceDatasetImage.query
               .filter_by(dataset_id=dataset_id, status='pending')
               .filter(FaceDatasetImage.filename.is_(None))
               .filter(FaceDatasetImage.job_id.isnot(None)).count())
    dataset_activity.sync_pending(dataset_id, 'generate', pending, engine='klein')


def generate_variations(user_id, dataset_id, variations, multiplier, klein_model,
                        lora_strength=None):
    """For each (variation x multiplier), enqueue a Klein edit of the reference
    and create a pending FaceDatasetImage. Returns the created image ids.

    The row is committed BEFORE enqueuing (so an enqueue/commit failure can never
    leave an untracked orphan job); on enqueue failure the row is marked 'failed'
    and the error re-raised (already-enqueued variations keep their rows)."""
    try:
        from .klein_edit_helper import enqueue_klein_edit
    except ImportError:
        raise RuntimeError('ComfyUI is not configured')
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if not ds.ref_filename:
        raise ValueError('reference image required')
    # Preflight the Klein model files BEFORE creating any rows: a missing model
    # then surfaces as one actionable "downloading, retry" 409 (route handler) —
    # not a dataset full of failed tiles, each doomed by a ComfyUI validation
    # error on a file that isn't there.
    from .klein_edit_helper import klein_missing_assets, KLEIN_REQUIRED, KleinModelsMissing
    _missing = klein_missing_assets()
    if any(a in _missing for a in KLEIN_REQUIRED):
        raise KleinModelsMissing(_missing)
    mult = max(1, int(multiplier))
    total = len(variations) * mult
    if total > MAX_FANOUT:
        raise ValueError(f'fan-out too large ({total} > {MAX_FANOUT})')
    # Anti-DoS: the fan-out is free (never debited) → cap pending in-flight
    # generations per dataset so one user can't monopolize the single GPU.
    in_flight = (FaceDatasetImage.query
                 .filter_by(dataset_id=dataset_id, status='pending')
                 .filter(FaceDatasetImage.filename.is_(None)).count())
    if in_flight + total > MAX_FANOUT:
        raise ValueError(f'too many generations in flight ({in_flight}), wait or cancel')
    # Extra identity refs (multi-references) : chaînées en ReferenceLatent natifs
    # côté Klein — mêmes fichiers que le chemin Nano Banana multi-réfs.
    extra_paths = [os.path.join(_dataset_dir(ds.id), fn) for fn in extra_ref_filenames(ds)]
    ids = []
    # try/finally: advertise the live 'generate' indicator even if an enqueue
    # fails partway (the already-queued rows are still in flight). Each Klein job
    # completes asynchronously; _sync_generate_activity keeps the count honest and
    # link_completed_dataset_image clears it when the last one lands.
    try:
        for v in variations:
            for _ in range(mult):
                img = FaceDatasetImage(dataset_id=dataset_id, source='generated', status='pending',
                                       variation_label=v.get('label'), framing=v.get('framing'),
                                       variation_prompt=v['prompt'], klein_model=klein_model,
                                       generation_engine='klein',
                                       generation_anchor_ids='[]',
                                       generation_anchor_metadata=_explicit_reference_metadata_json(ds),
                                       generation_gap_ids=_variation_gap_ids_json(v))
                db.session.add(img)
                db.session.commit()
                # NSFW (flag explicite OU label du catalogue NSFW) : wrapper sans le
                # clamp SFW — chemin Klein local uniquement, les moteurs API sont
                # refusés en amont (route + generate_variations_nanobanana).
                nsfw = bool(v.get('nsfw')) or is_nsfw_label(v.get('label'))
                try:
                    job_id = enqueue_klein_edit(
                        user_id=str(user_id), source_filename=ds.ref_filename,
                        source_path=_ref_path(ds),
                        edit_prompt=wrap_variation_klein(v['prompt'], nsfw=nsfw,
                                                         framing=v.get('framing')),
                        klein_model=klein_model,
                        lora_strength=lora_strength, extra_ref_paths=extra_paths,
                        extra_metadata={'is_dataset': True, 'dataset_id': dataset_id,
                                        'variation_label': v.get('label')})
                except Exception:
                    img.status = 'failed'
                    db.session.commit()
                    raise
                img.job_id = job_id
                db.session.commit()
                ids.append(img.id)
    finally:
        _sync_generate_activity(dataset_id)
    return ids


def improve_existing_image(user_id, image_id):
    """Serialize one source's improve request, including the queue hand-off."""
    lock = _IMAGE_IMPROVE_LOCKS[hash((str(user_id), image_id))
                                % len(_IMAGE_IMPROVE_LOCKS)]
    with lock:
        return _improve_existing_image_locked(user_id, image_id)


def _image_improvement_source_path(img):
    if not img:
        return None
    original_path = (os.path.join(_dataset_dir(img.dataset_id), img.original_filename)
                     if img.original_filename else '')
    if original_path and os.path.isfile(original_path):
        return original_path
    return _img_path(img) if img.filename else None


def _improve_existing_image_locked(user_id, image_id):
    """Queue one identity-constrained reconstruction of an existing image.

    The exact uploaded original is used when available. The source and candidate
    then become an exclusive provenance pair resolved only through side-by-side
    review, so correlated pixels cannot be counted twice in training.

    Returns ``{'candidate_id', 'job_id'}``, ``None`` for an image not owned by
    ``user_id``, and returns the already-active candidate idempotently when the
    same source is clicked twice.
    """
    img = _owned_image(user_id, image_id)
    if not img:
        return None
    if img.derivation_kind in _SMALL_IMAGE_DERIVATIONS:
        raise ValueError(
            'resolve the small-image rescue pair before improving either image')
    if img.derivation_kind == KLEIN_IMAGE_IMPROVE:
        raise ValueError('a reconstruction candidate cannot be reconstructed again')
    if not img.filename:
        raise ValueError('image file required')
    ds = db.session.get(FaceDataset, img.dataset_id)
    source_path = _image_improvement_source_path(img)
    if not os.path.isfile(source_path):
        raise ValueError('image file missing')

    # A completed Klein job remains status=pending until the user curates it, so
    # both an in-flight candidate (no filename yet) and an unreviewed result are
    # active.  Repeated clicks return that same job instead of consuming the GPU
    # or producing visually indistinguishable duplicates.
    active = (FaceDatasetImage.query
              .filter_by(dataset_id=img.dataset_id, parent_image_id=img.id,
                         derivation_kind=KLEIN_IMAGE_IMPROVE)
              .order_by(FaceDatasetImage.id.desc()).first())
    if active:
        if active.status == 'pending' and active.job_id:
            return {'candidate_id': active.id, 'job_id': active.job_id}
        raise RuntimeError('this image already has a reconstruction comparison')

    from . import klein_edit_helper as keh
    missing = keh.klein_missing_assets()
    missing_nodes = keh.klein_missing_nodes()
    if missing_nodes:
        raise KleinNodesMissing(missing, missing_nodes)
    if any(asset in missing for asset in keh.KLEIN_REQUIRED):
        raise keh.KleinModelsMissing(missing)

    in_flight = (FaceDatasetImage.query
                 .filter_by(dataset_id=img.dataset_id, status='pending')
                 .filter(FaceDatasetImage.filename.is_(None)).count())
    if in_flight + 1 > MAX_FANOUT:
        raise ValueError(
            f'too many generations in flight ({in_flight}), wait or cancel')

    # The source carries composition; a small reviewed anchor pack constrains
    # identity from other real photos. The configured consistency LoRA remains
    # active (None means its configured strength), while style LoRAs stay off.
    anchors = select_generation_references(ds, max_images=5) if ds else []
    extra_paths = []
    for anchor in anchors:
        if anchor.get('image_id') == img.id:
            continue
        path = os.path.join(_dataset_dir(img.dataset_id), anchor['filename'])
        if os.path.isfile(path) and path != source_path:
            extra_paths.append(path)
    prompt = KLEIN_IMAGE_IMPROVE_PROMPT
    stored_prompt = prompt[:500]
    base_label = 'Klein reconstruction'
    source_label = (img.variation_label or '').strip()
    label = (f'{base_label} · {source_label}' if source_label else base_label)[:120]
    source_was_cropped = bool(img.original_filename and img.upscale_ratio is not None)
    candidate = FaceDatasetImage(
        dataset_id=img.dataset_id, source='generated', status='pending',
        parent_image_id=img.id, derivation_kind=KLEIN_IMAGE_IMPROVE,
        # A preserved full-frame original may differ from the cropped derivative
        # that supplied these fields. Do not attach known-stale framing/caption to
        # the reconstruction; it can be classified/captioned after admission.
        framing=None if source_was_cropped else img.framing,
        caption=None if source_was_cropped else img.caption,
        variation_label=label, variation_prompt=stored_prompt,
        generation_engine='klein',
        generation_anchor_ids=_generation_anchor_ids_json(anchors),
        generation_anchor_metadata=_generation_anchor_metadata_json(anchors),
        generation_gap_ids=json.dumps(['klein_image_improve']),
    )
    previous_source_status = img.status
    db.session.add(candidate)
    # Suspend the source's training admission while its correlated replacement
    # is unresolved. The dedicated resolver later admits exactly one version.
    img.status = 'pending'
    db.session.commit()

    try:
        job_id = keh.enqueue_klein_edit(
            user_id=str(user_id), source_filename=os.path.basename(source_path),
            source_path=source_path, edit_prompt=prompt,
            lora_strength=None, sampler_steps=4, base_lora_strength=0.0,
            extra_ref_paths=extra_paths,
            extra_metadata={
                'is_dataset': True,
                'dataset_id': img.dataset_id,
                'variation_label': label,
                'derivation_kind': KLEIN_IMAGE_IMPROVE,
                'parent_image_id': img.id,
                'source_image_id': img.id,
                'action': 'reconstruct_compare',
            },
        )
    except Exception:
        # No broken tile: restore the source's prior admission decision so a
        # queue failure cannot silently remove a previously accepted photo.
        db.session.delete(candidate)
        img.status = previous_source_status
        db.session.commit()
        raise

    candidate.job_id = job_id
    db.session.commit()
    _sync_generate_activity(img.dataset_id)
    return {'candidate_id': candidate.id, 'job_id': job_id}


_REPLACEMENT_STATE_FIELDS = (
    'filename', 'caption', 'status', 'klein_model', 'generation_anchor_ids',
    'generation_anchor_metadata', 'generation_engine', 'generation_gap_ids',
    'generation_provenance', 'analysis_json', 'training_usefulness',
    'coverage_value', 'coverage_json', 'coverage_provenance', 'source_rights',
    'source_sha256', 'perceptual_hash', 'duplicate_of_id', 'face_score',
    'face_state', 'upscale_ratio', 'watermark_state', 'watermark_bbox',
    'watermark_regions',
)


def _replacement_state(img) -> dict:
    return {field: getattr(img, field) for field in _REPLACEMENT_STATE_FIELDS}


def _replacement_provenance(img, provenance, previous_state=None) -> str:
    try:
        payload = json.loads(provenance or '{}')
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if img.filename:
        payload['_replacement_previous'] = previous_state or _replacement_state(img)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _replacement_previous(img):
    provenance = _safe_json(img.generation_provenance) or {}
    previous = provenance.get('_replacement_previous')
    return previous if isinstance(previous, dict) else None


def _final_generation_provenance(img, updates=None):
    provenance = _safe_json(img.generation_provenance) or {}
    provenance.pop('_replacement_previous', None)
    if updates:
        provenance.update(updates)
    return json.dumps(provenance, ensure_ascii=False, sort_keys=True)


def _restore_replacement_after_failure(img, reason):
    previous = _replacement_previous(img)
    if previous:
        for field in _REPLACEMENT_STATE_FIELDS:
            if field in previous:
                setattr(img, field, previous[field])
        img.job_id = None
        img.fail_reason = reason
    else:
        img.status = 'failed'
        img.fail_reason = reason


@trash.serialized_transaction
def _commit_generated_replacement(img, filename, data, *, provenance_updates=None):
    """Atomically swap a completed generation into a dataset image row."""
    dataset = db.session.get(FaceDataset, img.dataset_id)
    if dataset is None or dataset.trashed_at is not None:
        raise ValueError('cannot commit a generation to a deleted dataset')
    safe_name = Path(str(filename or '')).name
    if not safe_name or safe_name != filename:
        raise ValueError('invalid generated image filename')
    dataset_root = Path(_dataset_dir(img.dataset_id)).resolve()
    destination = (dataset_root / safe_name).resolve(strict=False)
    if not destination.is_relative_to(dataset_root) or destination.is_symlink():
        raise ValueError('generated image path escapes the dataset')
    previous = _replacement_previous(img)
    old_path = None
    if previous and previous.get('filename'):
        candidate = (dataset_root / Path(previous['filename']).name).resolve(strict=False)
        if candidate.is_relative_to(dataset_root) and candidate.is_file() \
                and not candidate.is_symlink():
            old_path = candidate
    if old_path == destination or destination.exists():
        stem, suffix = destination.stem, destination.suffix
        safe_name = f'{stem}_{uuid.uuid4().hex[:6]}{suffix}'
        destination = dataset_root / safe_name
    _atomic_write_bytes(destination, data)
    trashed = None
    try:
        if old_path is not None:
            trashed = trash.send_paths_to_trash(
                [old_path], context=f'dataset-{img.dataset_id}-regeneration', metadata={
                    'kind': 'regenerated_image',
                    'dataset_id': img.dataset_id,
                    'image_id': img.id,
                    'previous_state': previous,
                    'label': img.variation_label or old_path.name,
                })
        img.filename = safe_name
        img.caption = None
        img.status = 'pending'
        img.job_id = None
        img.fail_reason = None
        img.analysis_json = None
        img.training_usefulness = None
        img.coverage_value = None
        img.coverage_json = None
        img.coverage_provenance = None
        img.source_rights = json.dumps({'basis': 'generated'})
        img.source_sha256 = hashlib.sha256(data).hexdigest()
        img.perceptual_hash = None
        img.duplicate_of_id = None
        img.face_score = None
        img.face_state = None
        img.upscale_ratio = None
        _clear_watermark_metadata(img)
        img.generation_provenance = _final_generation_provenance(
            img, provenance_updates)
        db.session.commit()
    except Exception:
        db.session.rollback()
        destination.unlink(missing_ok=True)
        if trashed is not None:
            try:
                trash.restore_entry(trashed['id'])
            except Exception:
                logger.exception('could not roll back regenerated image swap %s', img.id)
        raise
    return safe_name


def regenerate_image(user_id, image_id, lora_strength=None, prompt=None, app=None,
                     engine=None, klein_model=None):
    """Re-enqueue a single generated variation IN PLACE (same row id): cancel any
    in-flight job, drop the old file, reset the row to pending with the new
    job_id. Returns the new job_id, or None if the image is not owned / not a
    generated variation. Raises ValueError if the dataset has no reference or
    the variation prompt can't be recovered.

    `prompt` (optional) is the user-EDITED core creative prompt from the tile's
    ✏️ bubble. When given it REPLACES and is PERSISTED into `variation_prompt`
    (so a later plain regenerate / reject-regenerate reuses the edit), then feeds
    the identity-guard wrapper like any catalog prompt — the face lock is still
    applied on top, the user only steers the creative half. Empty/None = the
    current behaviour (recover the prompt from the row or the label).

    `engine` (optional, 'nanobanana'/'chatgpt'/'klein') is the generator
    CURRENTLY selected in the workspace — it wins over the engine that
    originally produced the row, so a tile born on Klein doesn't pin every
    regenerate to Klein after the user switched to Nano Banana (and vice
    versa). None = legacy behaviour (reuse the row's origin). Exception:
    an NSFW-labelled tile always stays on the local Klein path (fail-closed —
    NSFW never goes to third-party APIs, mirroring the batch generate rule).
    `klein_model` (optional) is the workspace's Klein model pick, used when a
    row born on an API engine switches to Klein (its klein_model column holds
    an engine TAG, not a real model file)."""
    img = _owned_image(user_id, image_id)
    if not img or img.source != 'generated':
        return None
    if img.derivation_kind == KLEIN_SMALL_IMAGE:
        raise ValueError('small-image rescue candidates cannot be regenerated; re-import the source')
    if img.derivation_kind == KLEIN_IMAGE_IMPROVE:
        raise ValueError('reconstruction candidates cannot be regenerated from the dataset reference')
    ds = db.session.get(FaceDataset, img.dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    edited = (prompt or '').strip()
    if edited:
        img.variation_prompt = edited[:500]   # column is String(500); persist the edit
    prompt = img.variation_prompt or prompt_by_label(img.variation_label or '')
    if prompt is None:
        raise ValueError('variation prompt unknown')
    requested = (engine or '').strip() or None
    if requested is not None and requested != 'klein' and requested not in API_ENGINES:
        raise ValueError(f'unknown engine: {requested}')
    target = requested or (img.klein_model if img.klein_model in API_ENGINES else 'klein')
    if is_nsfw_label(img.variation_label):
        target = 'klein'              # fail-closed: NSFW never reaches an API engine
    else:
        # Engines disabled in Settings must not be used even when the row (or a
        # stale workspace selection) points at them: fall back to the default
        # engine, then to the first enabled one. An empty list means "all
        # enabled" (legacy configs); NSFW above already forced local Klein.
        enabled = [e for e in (cfg.get('engines.enabled') or [])
                   if e == 'klein' or e in API_ENGINES]
        if enabled and target not in enabled:
            default = cfg.get('engines.default')
            target = default if default in enabled else enabled[0]
    if target in API_ENGINES and not cfg.get('privacy.allow_remote_generation'):
        raise RemoteGenerationConsentRequired()
    if img.status == 'pending' and not img.filename and img.job_id:  # still generating
        try:
            from ..job_queue import queue_manager
            queue_manager.cancel_job(img.job_id, str(user_id), 'image')
        except Exception:
            pass
    # API target ('nanobanana'/'chatgpt' — requested, or the row's origin when
    # no engine was given): the row's klein_model column carries the engine tag.
    # With an `app` handle the call runs in a background thread (the row flips
    # to in-flight IMMEDIATELY so the tile shows "…" and the polling/banner UI
    # reacts at once); without it the call is synchronous (test path / legacy
    # callers).
    if target in API_ENGINES:
        engine = target
        previous_state = _replacement_state(img) if img.filename else None
        img.klein_model = engine      # the row's engine tag follows the switch
        api_generate = _api_generate_fn(engine)
        anchors = select_generation_references(
            ds, preferred_ids=_parse_generation_anchor_ids(img.generation_anchor_ids))
        ref_bytes = [anchor['bytes'] for anchor in anchors]
        if not ref_bytes:
            raise ValueError('reference image required — import a photo corpus or set a primary reference')
        img.generation_anchor_ids = _generation_anchor_ids_json(anchors)
        img.generation_anchor_metadata = _generation_anchor_metadata_json(anchors)
        img.generation_engine = engine
        img.status = 'pending'
        img.fail_reason = None   # fresh attempt: drop the previous failure message
        img.generation_provenance = _replacement_provenance(
            img, _remote_generation_provenance(engine, anchors), previous_state)
        db.session.commit()
        aspect = aspect_for_label(img.variation_label, img.framing)
        if app is not None:
            # Threaded path: _run_nanobanana_batch owns the 'generate' indicator
            # (begin/bump/end) so a single API regenerate takes the same lock as a
            # batch — every concurrent action stays disabled until it finishes.
            threading.Thread(target=_run_nanobanana_batch,
                             args=(app, [(img.id, prompt, aspect)], ref_bytes, engine,
                                   img.dataset_id),
                             daemon=True).start()
            return engine
        # Synchronous path (legacy / no-app callers): guard the same 'generate'
        # indicator directly so the payload advertises the regenerate too, and a
        # raise never leaks the entry (finally end()).
        token = dataset_activity.begin(img.dataset_id, 'generate', total=1, engine=engine)
        try:
            gen_kwargs = {'aspect_ratio': aspect}
            if engine == 'chatgpt':
                from .chatgpt_image import _use_subscription
                gen_kwargs['force_lane'] = 'subscription' if _use_subscription() else 'api'
            try:
                out = api_generate(ref_bytes, wrap_variation(prompt, ref_count=len(ref_bytes)),
                                   **gen_kwargs)
            except SubscriptionQuotaExceeded:
                out = None
                _restore_replacement_after_failure(img, _QUOTA_MSG)
                db.session.commit()
                return engine
            except SubscriptionUnavailable as e:
                out = None
                _restore_replacement_after_failure(img, f'chatgpt: {e}')
                db.session.commit()
                return engine
            if out:
                fn = f"{user_id}_{_ENGINE_FILE_TAG[engine]}_{uuid.uuid4().hex[:8]}.webp"
                normalized = normalize_to_webp(out)
                _commit_generated_replacement(
                    img, fn, normalized, provenance_updates={
                        'response_received_at': datetime.now(timezone.utc).isoformat(),
                        'response_sha256': hashlib.sha256(out).hexdigest(),
                        'stored_sha256': hashlib.sha256(normalized).hexdigest(),
                    })
            else:
                _restore_replacement_after_failure(
                    img, f'{engine}: empty response (often a content-policy refusal '
                         'or a transient API error - retry usually works)')
                db.session.commit()
            return engine
        except Exception as exc:
            db.session.rollback()
            img = db.session.get(FaceDatasetImage, image_id)
            if img is not None:
                _restore_replacement_after_failure(img, f'{engine}: {str(exc)[:400]}')
                db.session.commit()
            raise
        finally:
            dataset_activity.end(token)

    try:
        from .klein_edit_helper import enqueue_klein_edit
    except ImportError:
        raise RuntimeError('ComfyUI is not configured')
    if not ds.ref_filename:
        raise ValueError('a primary reference is required for local Klein generation')
    # Klein target: keep the row's real model file when it has one; a row born
    # on an API engine holds an engine TAG here, not a model — use the
    # workspace's Klein pick instead (None = enqueue's default model).
    model = (img.klein_model if img.klein_model not in API_ENGINES
             else ((klein_model or '').strip() or None))
    previous_state = _replacement_state(img) if img.filename else None
    extra_paths = [os.path.join(_dataset_dir(ds.id), fn) for fn in extra_ref_filenames(ds)]
    job_id = enqueue_klein_edit(
        user_id=str(user_id), source_filename=ds.ref_filename,
        source_path=_ref_path(ds),
        edit_prompt=wrap_variation_klein(prompt, nsfw=is_nsfw_label(img.variation_label),
                                         framing=img.framing),
        klein_model=model,
        lora_strength=lora_strength, extra_ref_paths=extra_paths,
        extra_metadata={'is_dataset': True, 'dataset_id': img.dataset_id,
                        'variation_label': img.variation_label})
    local_provenance = json.dumps({
        'schema_version': 1,
        'provider': 'local',
        'engine': 'klein',
        'model': model or 'configured-default',
        'client_request_id': str(uuid.uuid4()),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'remote_generation_consent': False,
        'data_sent': [],
        'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
    }, ensure_ascii=False, sort_keys=True)
    img.generation_provenance = _replacement_provenance(
        img, local_provenance, previous_state)
    img.klein_model = model           # the row's engine/model tag follows the switch
    img.generation_engine = 'klein'
    img.generation_anchor_ids = '[]'
    img.generation_anchor_metadata = _explicit_reference_metadata_json(ds)
    img.status = 'pending'
    img.job_id = job_id
    img.fail_reason = None   # fresh attempt: drop the previous failure message
    db.session.commit()
    # Advertise the in-flight Klein job so a single regenerate takes the same lock
    # as a batch; link_completed_dataset_image clears it on completion.
    _sync_generate_activity(img.dataset_id)
    return job_id


# --- Fan-out generation (API engines: Nano Banana / ChatGPT) ---------------
# Both engines share the exact generate_variation contract (refs + prompt +
# aspect -> bytes|None), so the whole fan-out below is engine-parametric. The
# filename tag keeps the provenance readable in the dataset folder.
API_ENGINES = ('nanobanana', 'chatgpt')
_ENGINE_FILE_TAG = {'nanobanana': 'NBFace', 'chatgpt': 'GPTFace'}


class RemoteGenerationConsentRequired(PermissionError):
    code = 'remote_generation_consent_required'

    def __init__(self):
        super().__init__(
            'Remote generation is off: reference images and prompts stay on '
            'this computer. Enable third-party generation in Settings ▸ Image engines.')

from .chatgpt_image import (  # noqa: E402 - keep optional image provider lazy at module tail
    SubscriptionQuotaExceeded, SubscriptionUnavailable)

_QUOTA_MSG = ('chatgpt: subscription image quota reached — remaining rows were '
              'stopped; rerun in API-key mode or wait for your plan quota to reset')
_LOST_MSG = ('chatgpt: subscription connection lost — remaining rows stopped; '
             'reconnect in Settings, then regenerate')


def _api_generate_fn(engine):
    if engine == 'chatgpt':
        from .chatgpt_image import generate_variation
    else:
        from .nanobanana import generate_variation
    return generate_variation


def _remote_generation_provenance(engine, anchors) -> str:
    if engine == 'chatgpt':
        from .chatgpt_image import CHATGPT_IMAGE_MODEL
        provider, model = 'openai', CHATGPT_IMAGE_MODEL
    else:
        from .nanobanana import NANOBANANA_MODEL
        provider, model = 'google', NANOBANANA_MODEL
    return json.dumps({
        'schema_version': 1,
        'provider': provider,
        'engine': engine,
        'model': model,
        'client_request_id': str(uuid.uuid4()),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'remote_generation_consent': bool(cfg.get('privacy.allow_remote_generation')),
        'data_sent': ['reference_images', 'variation_prompt'],
        'anchor_sha256': [anchor.get('sha256') or hashlib.sha256(anchor['bytes']).hexdigest()
                          for anchor in anchors],
    }, ensure_ascii=False, sort_keys=True)


def _run_nanobanana_batch(app, items, ref_bytes, engine='nanobanana', dataset_id=None):
    """Worker body: generate each (image_id, prompt) via the selected API engine
    and link the result. Runs in a background thread (factored out so tests can
    call it synchronously). Each row commits independently; an API failure marks
    that row 'failed' (visible + regenerable) without stopping the batch.

    ``dataset_id`` (when known) drives the 'generate' activity indicator: one
    begin() with total=len(items), a bump() per item handled (success OR fail),
    and end() in a finally — so the ⚡ Generate button (and every concurrent
    action) stays disabled for the WHOLE batch, and the indicator can never leak
    even if a row raises. Also used for single-image API regenerate (items=1),
    which therefore takes the same lock. ``None`` = no indicator (legacy callers)."""
    api_generate = _api_generate_fn(engine)
    from concurrent.futures import ThreadPoolExecutor
    # Guard d'identité adapté au nombre de références (multi = « use EVERY ref »).
    n_refs = len(ref_bytes) if isinstance(ref_bytes, (list, tuple)) else 1
    tag = _ENGINE_FILE_TAG.get(engine, 'NBFace')
    # Pin the ChatGPT auth lane ONCE for the whole batch. Without this, a
    # mid-batch token refresh failure (auth.openai.com non-200 -> logout())
    # would make every later row's OWN _use_subscription() call see
    # connected=False and silently reroute onto the paid API key — breaking
    # the feature's headline invariant. Pinning + stopping the batch instead
    # (via SubscriptionUnavailable below) closes that hole.
    force_lane = None
    if engine == 'chatgpt':
        from .chatgpt_image import _use_subscription
        force_lane = 'subscription' if _use_subscription() else 'api'
    # Set the moment ANY row hits the plan quota (or the pinned subscription
    # lane loses its token) — every later row would fail too, so the rest of
    # the batch fails fast instead of burning one call each.
    quota_exhausted = threading.Event()
    stop_msg = {'text': _QUOTA_MSG}   # set to the actual stop reason when it fires
    token = dataset_activity.begin(dataset_id, 'generate', total=len(items), engine=engine) \
        if dataset_id is not None else None

    def _run_one(item):
        # item = (image_id, prompt, aspect) ; aspect optionnel (rétro-compat → '1:1').
        image_id, prompt = item[0], item[1]
        aspect = item[2] if len(item) > 2 else '1:1'
        # Stop AVANT l'appel API : cancel_pending supprime les lignes en vol — si
        # celle-ci a disparu, ne pas payer une génération qui sera jetée (le bouton
        # Stop doit économiser le RESTE du batch, pas seulement masquer les tuiles).
        with app.app_context():
            row = db.session.get(FaceDatasetImage, image_id)
            if row is None or row.status != 'pending':
                logger.info(f"{engine} batch: row {image_id} cancelled - API call skipped")
                return
        if quota_exhausted.is_set():
            # A previous row hit the plan quota: skip the API for every row not
            # yet started (later calls would 429 too). Up to max_workers rows may
            # already be in flight past this check when the event trips — each is
            # still failed via the dedicated except below, so the batch wastes at
            # most ~max_workers calls, not all.
            with app.app_context():
                img = db.session.get(FaceDatasetImage, image_id)
                if img is not None:
                    _restore_replacement_after_failure(img, stop_msg['text'])
                    db.session.commit()
            return
        out = None
        fail_reason = None
        gen_kwargs = {'aspect_ratio': aspect}
        if engine == 'chatgpt':
            gen_kwargs['force_lane'] = force_lane
        try:
            wrapped_prompt = wrap_variation(prompt, ref_count=n_refs)
            with app.app_context():
                tracked = db.session.get(FaceDatasetImage, image_id)
                if tracked is not None:
                    provenance = _safe_json(tracked.generation_provenance) or {}
                    provenance.update({
                        'request_started_at': datetime.now(timezone.utc).isoformat(),
                        'actual_auth_lane': force_lane or 'api',
                        'aspect_ratio': aspect,
                        'wrapped_prompt_sha256': hashlib.sha256(
                            wrapped_prompt.encode('utf-8')).hexdigest(),
                    })
                    tracked.generation_provenance = json.dumps(
                        provenance, ensure_ascii=False, sort_keys=True)
                    db.session.commit()
            out = api_generate(ref_bytes, wrapped_prompt,
                               **gen_kwargs)
            if not out:
                # api_generate signale certains refus/vides par un retour falsy
                # sans lever — sans raison, la tuile "failed" resterait muette.
                fail_reason = f'{engine}: empty response (often a content-policy refusal or a transient API error - retry usually works)'
        except SubscriptionQuotaExceeded as e:
            quota_exhausted.set()
            stop_msg['text'] = _QUOTA_MSG
            logger.warning(f"{engine} batch: quota exhausted at row {image_id}: {e}")
            fail_reason = _QUOTA_MSG
        except SubscriptionUnavailable as e:
            quota_exhausted.set()
            stop_msg['text'] = _LOST_MSG
            logger.warning(f"{engine} batch: subscription lost at row {image_id}: {e}")
            fail_reason = _LOST_MSG
        except Exception as e:
            logger.warning(f"{engine} batch: generation error for row {image_id}: {e}")
            fail_reason = f'{engine}: {str(e)[:400]}'
        with app.app_context():
            img = db.session.get(FaceDatasetImage, image_id)
            if img is None:
                return
            if out:
                ds = db.session.get(FaceDataset, img.dataset_id)
                fn = f"{ds.user_id}_{tag}_{uuid.uuid4().hex[:8]}.webp"
                try:
                    # Conserve le ratio demandé (pas de letterbox carré sur les corps).
                    normalized = normalize_to_webp(out)
                    _commit_generated_replacement(
                        img, fn, normalized, provenance_updates={
                            'response_received_at': datetime.now(timezone.utc).isoformat(),
                            'response_sha256': hashlib.sha256(out).hexdigest(),
                            'stored_sha256': hashlib.sha256(normalized).hexdigest(),
                        })
                except Exception as e:
                    logger.warning(f"{engine} batch: save failed for row {image_id}: {e}")
                    db.session.rollback()
                    img = db.session.get(FaceDatasetImage, image_id)
                    if img is not None:
                        _restore_replacement_after_failure(
                            img, f'saving the image failed: {str(e)[:400]}')
                        db.session.commit()
            else:
                _restore_replacement_after_failure(img, fail_reason)
                db.session.commit()

    def _one(item):
        # Progress-tracking wrapper: bump the indicator once per item handled,
        # whatever the outcome (a raised _run_one still counts as one handled and
        # never strands the counter). No-op when token is None (bump(None)).
        try:
            return _run_one(item)
        finally:
            dataset_activity.bump(token)

    logger.info(f"{engine} batch: start ({len(items)} variation(s))")
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(_one, items))
    finally:
        dataset_activity.end(token)   # idempotent; end(None) is a no-op
    logger.info(f"{engine} batch: done ({len(items)} variation(s))")


def generate_variations_nanobanana(app, user_id, dataset_id, variations, multiplier,
                                   engine='nanobanana'):
    """API fan-out (Nano Banana or ChatGPT, per `engine`): pre-create pending
    rows (job_id stays None - that is the marker for API-generated rows), then
    fill them from a background thread. The existing polling/banner/cancel UI
    works unchanged (pending + no file = in flight). Returns the created ids."""
    if engine not in API_ENGINES:
        raise ValueError(f'unknown API engine: {engine}')
    # Fail-closed : les variations NSFW ne partent JAMAIS vers un moteur API
    # (comptes/API tiers) — elles n'existent que sur le chemin Klein local.
    if any(v.get('nsfw') or is_nsfw_label(v.get('label')) for v in variations):
        raise ValueError('NSFW variations run on the local Klein engine only')
    if not cfg.get('privacy.allow_remote_generation'):
        raise RemoteGenerationConsentRequired()
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    mult = max(1, int(multiplier))
    total = len(variations) * mult
    if total == 0:
        raise ValueError('no variations selected')
    if total > MAX_FANOUT:
        raise ValueError(f'fan-out too large ({total} > {MAX_FANOUT})')
    # The full imported corpus stays on the dataset; only a bounded, diverse
    # anchor set is sent to the provider for this request.
    anchors = select_generation_references(ds)
    ref_bytes = [anchor['bytes'] for anchor in anchors]
    if not ref_bytes:
        raise ValueError('reference image required — import a photo corpus or set a primary reference')
    anchor_ids = _generation_anchor_ids_json(anchors)

    ids, items = [], []
    for v in variations:
        for _ in range(mult):
            # klein_model=<engine> marks API-generated rows (the regenerate
            # path dispatches on it; never collides with real .safetensors names).
            img = FaceDatasetImage(dataset_id=dataset_id, source='generated', status='pending',
                                   variation_label=v.get('label'), framing=v.get('framing'),
                                   variation_prompt=v['prompt'], klein_model=engine, job_id=None,
                                   generation_anchor_ids=anchor_ids,
                                   generation_anchor_metadata=_generation_anchor_metadata_json(anchors),
                                   generation_engine=engine,
                                   generation_gap_ids=_variation_gap_ids_json(v),
                                   generation_provenance=_remote_generation_provenance(
                                       engine, anchors))
            db.session.add(img)
            db.session.commit()
            ids.append(img.id)
            items.append((img.id, v['prompt'], aspect_for_label(v.get('label'), v.get('framing'))))

    threading.Thread(target=_run_nanobanana_batch,
                     args=(app, items, ref_bytes, engine, dataset_id),
                     daemon=True).start()
    return ids


def recover_interrupted_api_generations() -> int:
    """Close API rows whose daemon disappeared during a process restart.

    Provider APIs do not offer a shared idempotency/result handle here. Blindly
    replaying a pending row could therefore charge twice after the remote call
    succeeded but before its bytes were committed. Marking the row failed makes
    the interruption explicit and keeps the existing Regenerate action as the
    safe, user-authorized retry path.
    """
    # A handful of very early databases can reach this startup hook while an
    # additive migration test is intentionally exercising only a partial legacy
    # table. Do not issue an ORM SELECT for columns that schema does not yet have.
    from sqlalchemy import inspect
    required = {'status', 'filename', 'job_id', 'generation_engine', 'fail_reason'}
    existing = {column['name'] for column in inspect(db.engine).get_columns(
        FaceDatasetImage.__tablename__)}
    if not required.issubset(existing):
        return 0
    rows = (FaceDatasetImage.query
            .filter_by(status='pending', filename=None, job_id=None)
            .filter(FaceDatasetImage.generation_engine.in_(tuple(API_ENGINES)))
            .all())
    for row in rows:
        row.status = 'failed'
        row.fail_reason = ('The app restarted before this provider generation was '
                           'saved. Check the provider history, then regenerate if needed.')
    if rows:
        db.session.commit()
    return len(rows)


# --- Completion linking (called from the job queue) -------------------------
def _technical_metric_score(analysis) -> float | None:
    metrics = (analysis or {}).get('metrics') or {}
    try:
        return (float(metrics['sharpness']) * 0.42
                + float(metrics['exposure']) * 0.23
                + float(metrics['resolution']) * 0.35)
    except (KeyError, TypeError, ValueError):
        return None


def _improvement_source_filename(source) -> str | None:
    """The dataset-relative file that supplied pixels to the reconstruction job."""
    if not source:
        return None
    if source.original_filename:
        original = os.path.join(_dataset_dir(source.dataset_id), source.original_filename)
        if os.path.isfile(original):
            return source.original_filename
    return source.filename


def _prepare_completed_improvement(img) -> bool:
    """Do the cheap reconstruction QA needed before the completion callback returns.

    Face scoring can load InsightFace and take minutes on a cold machine, so that pass
    is deliberately performed by ``_run_completed_improvement_qa`` instead of holding
    the single ComfyUI completion worker.  The provisional comparison also makes the
    UI explicit that no recommendation exists yet.
    """
    path = _img_path(img)
    try:
        with open(path, 'rb') as fh:
            candidate_analysis = analyse_image_bytes(fh.read(), source_name='reconstruction')
    except Exception as exc:
        logger.exception('reconstruction technical QA failed for image %s', img.id)
        candidate_analysis = parse_analysis(img.analysis_json)
        candidate_analysis['repair_comparison'] = {
            'phase': 'failed',
            'source_image_id': img.parent_image_id,
            'source_filename': None,
            'source_face': None,
            'source_identity_score': None,
            'technical_delta': None,
            'identity_delta': None,
            'recommendation': None,
            'qa_error': str(exc)[:400],
        }
        img.analysis_json = analysis_json(candidate_analysis)
        return False
    img.analysis_json = analysis_json(candidate_analysis)
    img.training_usefulness = candidate_analysis.get('training_usefulness')
    img.source_sha256 = candidate_analysis.get('source_sha256')
    img.coverage_value = img.coverage_value or 'unknown'
    source = db.session.get(FaceDatasetImage, img.parent_image_id)
    source_analysis = parse_analysis(source.analysis_json) if source else {}
    source_technical = _technical_metric_score(source_analysis)
    candidate_technical = _technical_metric_score(candidate_analysis)
    technical_delta = (round(candidate_technical - source_technical, 1)
                       if source_technical is not None and candidate_technical is not None
                       else None)
    candidate_analysis['repair_comparison'] = {
        'phase': 'analyzing',
        'source_image_id': source.id if source else img.parent_image_id,
        'source_filename': _improvement_source_filename(source),
        'source_face': None,
        'source_identity_score': None,
        'technical_delta': technical_delta,
        'identity_delta': None,
        'recommendation': None,
        'qa_error': None,
    }
    img.analysis_json = analysis_json(candidate_analysis)
    return True


def _analyze_completed_improvement(img):
    """Attach identity QA and a conservative recommendation to a reconstruction."""
    path = _img_path(img)
    source = db.session.get(FaceDatasetImage, img.parent_image_id)
    ds = db.session.get(FaceDataset, img.dataset_id)
    source_path = _image_improvement_source_path(source) if source else None
    candidate_analysis = parse_analysis(img.analysis_json)
    comparison = dict(candidate_analysis.get('repair_comparison') or {})
    if not comparison:
        if not _prepare_completed_improvement(img):
            return
        candidate_analysis = parse_analysis(img.analysis_json)
        comparison = dict(candidate_analysis.get('repair_comparison') or {})

    source_face = None
    source_identity = None
    qa_error = None
    if ds and ds.ref_filename and source_path and os.path.isfile(source_path):
        try:
            from .face_similarity import score_dataset_faces
            results, scoring_error = score_dataset_faces(
                _ref_path(ds), [path, source_path], ref_paths=_identity_reference_paths(ds))
            if results.get(path):
                _persist_face_result(img, results[path])
            if results.get(source_path):
                source_face = _face_result_payload(results[source_path])
                source_identity = source_face.get('sim')
            if scoring_error:
                qa_error = str(scoring_error)[:400]
        except Exception as exc:
            # Completion still succeeds when optional face tools are absent, but the
            # comparison must say that QA failed rather than silently recommending it.
            logger.exception('reconstruction QA face scoring failed for image %s', img.id)
            qa_error = str(exc)[:400]
    else:
        qa_error = 'The exact reconstruction source or primary identity reference is unavailable.'

    candidate_analysis = parse_analysis(img.analysis_json)
    face_quality = (candidate_analysis.get('face') or {}).get('quality')
    identity_delta = (round(img.face_score - source_identity, 4)
                      if img.face_score is not None and source_identity is not None
                      else None)
    technical_delta = comparison.get('technical_delta')
    try:
        identity_floor = float(cfg.get('face_scoring.orange') or 0.45)
    except (TypeError, ValueError):
        identity_floor = 0.45

    if img.face_state != 'scorable' or img.face_score is None or source_identity is None:
        recommendation = 'manual_identity_check'
    elif img.face_score < identity_floor or (identity_delta is not None and identity_delta < -0.03):
        recommendation = 'identity_risk'
    elif face_quality != 'green':
        recommendation = 'quality_risk'
    elif technical_delta is None:
        recommendation = 'manual_quality_check'
    elif technical_delta <= 0:
        recommendation = 'no_measured_gain'
    else:
        recommendation = 'candidate_improved'

    candidate_analysis['repair_comparison'] = {
        **comparison,
        'phase': 'ready',
        'source_image_id': source.id if source else img.parent_image_id,
        'source_filename': _improvement_source_filename(source),
        'source_face': source_face,
        'source_identity_score': source_identity,
        'candidate_identity_score': img.face_score,
        'identity_delta': identity_delta,
        'recommendation': recommendation,
        'qa_error': qa_error,
    }
    img.analysis_json = analysis_json(candidate_analysis)


def _run_completed_improvement_qa(app, image_id):
    """Run the optional, heavyweight face comparison outside the job queue worker."""
    with app.app_context():
        img = db.session.get(FaceDatasetImage, image_id)
        if not img or not img.filename or img.derivation_kind != KLEIN_IMAGE_IMPROVE:
            return
        try:
            _analyze_completed_improvement(img)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.exception('reconstruction QA failed for completed image %s', image_id)
            img = db.session.get(FaceDatasetImage, image_id)
            if img:
                candidate_analysis = parse_analysis(img.analysis_json)
                comparison = dict(candidate_analysis.get('repair_comparison') or {})
                candidate_analysis['repair_comparison'] = {
                    **comparison,
                    'phase': 'failed',
                    'recommendation': None,
                    'qa_error': str(exc)[:400],
                }
                img.analysis_json = analysis_json(candidate_analysis)
                db.session.commit()
        finally:
            db.session.remove()


def _start_completed_improvement_qa(app, image_id):
    threading.Thread(
        target=_run_completed_improvement_qa,
        args=(app, image_id),
        name=f'reconstruction-qa-{image_id}',
        daemon=True,
    ).start()


def link_completed_dataset_image(job_id, filename, failed=False, reason=None):
    """Attach a finished fan-out job to its FaceDatasetImage row.

    Called from the job-queue completion/failure/cancel paths, which may run in
    a long-lived monitor thread whose SQLAlchemy session holds a STALE read
    snapshot (rows committed by other threads are invisible). If the first
    lookup misses, end the transaction (rollback) and retry on a fresh snapshot
    before concluding the row really doesn't exist.
    `reason` (the job row's error_message, e.g. a ComfyUI execution error) shows
    on the failed tile so the user sees WHY, not a generic 'see the log'."""
    if filename and (not isinstance(filename, str)
                     or Path(filename).name != filename
                     or filename in ('.', '..')):
        failed = True
        reason = 'ComfyUI returned an unsafe output filename'
        filename = None
    qa_candidate_id = None
    img = FaceDatasetImage.query.filter_by(job_id=job_id).first()
    if img is None:
        db.session.rollback()  # drop the stale read snapshot, then re-read
        img = FaceDatasetImage.query.filter_by(job_id=job_id).first()
    if img is None:
        logger.warning(f"dataset link: no FaceDatasetImage row for job {job_id}")
        return
    if (img.derivation_kind in (KLEIN_SMALL_IMAGE, KLEIN_IMAGE_IMPROVE)
            and img.status in ('keep', 'reject')):
        # The user already resolved the pair while this job/callback was racing.
        # The terminal review decision wins: do not attach
        # a late file and do not turn reject into failed. Retain a local Comfy output
        # in app Trash so an expensive late generation is still recoverable.
        output_dir = _comfy_output_dir()
        late_output = os.path.join(output_dir, filename) if output_dir and filename else None
        if late_output and os.path.isfile(late_output):
            try:
                from . import trash
                trash.send_paths_to_trash(
                    [late_output], context='late-dataset-output', metadata={
                        'kind': 'orphaned_generation',
                        'dataset_id': img.dataset_id,
                        'label': f'Late dataset output: {os.path.basename(filename)}',
                    })
            except (OSError, ValueError):
                logger.exception('could not retain late dataset output %s', filename)
        try:
            _sync_generate_activity(img.dataset_id)
        except Exception:
            logger.exception(
                'dataset link: terminal review activity sync failed for job %s', job_id)
        return
    if failed:
        # A cancel racing with the worker dispatches a failure callback. Never let
        # that callback overwrite an already-resolved rescue choice (keep/reject).
        if not (img.derivation_kind in (KLEIN_SMALL_IMAGE, KLEIN_IMAGE_IMPROVE)
                and img.status in ('keep', 'reject')):
            _restore_replacement_after_failure(
                img, img.fail_reason or reason
                or 'Klein generation failed (see 🪵 Server log in Settings for the ComfyUI error)')
            db.session.commit()
    else:
        output_dir = _comfy_output_dir()
        src = os.path.join(output_dir, filename) if output_dir else None
        data = None
        if src and os.path.exists(src):
            with open(src, 'rb') as handle:
                data = handle.read()
        else:
            # The file isn't on disk where we look — ComfyUI was pointed at a
            # custom output path, or none is configured. Fetch it over the /view
            # API instead (path-independent, like other ComfyUI front-ends). #2
            from ..utils.comfyui import fetch_output_image_bytes
            data = fetch_output_image_bytes(filename)
        if data:
            _commit_generated_replacement(
                img, filename, data, provenance_updates={
                    'response_received_at': datetime.now(timezone.utc).isoformat(),
                    'response_sha256': hashlib.sha256(data).hexdigest(),
                })
            if src:
                try:
                    os.remove(src)
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.warning('could not remove imported ComfyUI output %s', src)
        else:
            _restore_replacement_after_failure(
                img, 'The finished image could not be retrieved from ComfyUI '
                     '(not on disk, and the /view API fetch failed).')
            db.session.commit()
            logger.warning(
                'dataset link: file not on disk and /view API fetch failed (job %s)',
                job_id)
        if (img.derivation_kind == KLEIN_IMAGE_IMPROVE
                and img.status == 'pending' and img.filename
                and os.path.isfile(_img_path(img))):
            if _prepare_completed_improvement(img):
                qa_candidate_id = img.id
    db.session.commit()
    # This job just left the in-flight set: reconcile the Klein 'generate'
    # indicator (clears it when this was the last job of the batch). Guarded — a
    # bookkeeping hiccup must never break completion linking; the TTL is the net.
    try:
        _sync_generate_activity(img.dataset_id)
    except Exception:
        logger.exception(f"dataset link: generate-activity sync failed for job {job_id}")
    if qa_candidate_id is not None:
        from flask import current_app
        _start_completed_improvement_qa(current_app._get_current_object(), qa_candidate_id)


# --- Migration helper (run once manually after deploy) ---------------------
def migrate_existing_images_to_per_dataset():
    """Migration helper - run once manually after deploy. Not called automatically."""
    counts = {'moved': 0, 'skipped': 0, 'missing': 0}
    output_dir = _comfy_output_dir()
    if output_dir is None:
        return counts
    datasets = FaceDataset.query.all()
    for ds in datasets:
        if ds.ref_filename:
            src = os.path.join(output_dir, ds.ref_filename)
            dst = os.path.join(_dataset_dir(ds.id), ds.ref_filename)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.move(src, dst)
                counts['moved'] += 1
            elif os.path.exists(dst):
                counts['skipped'] += 1
            else:
                counts['missing'] += 1
        for img in FaceDatasetImage.query.filter_by(dataset_id=ds.id).all():
            if not img.filename:  # pending/failed rows without a file
                continue
            src = os.path.join(output_dir, img.filename)
            dst = os.path.join(_dataset_dir(img.dataset_id), img.filename)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.move(src, dst)
                counts['moved'] += 1
            elif os.path.exists(dst):
                counts['skipped'] += 1
            else:
                counts['missing'] += 1
    return counts


# --- Export ----------------------------------------------------------------
_INFO = ("Trigger: {trigger}\nImages: {n}\nComposition: {comp}\n\n"
         "ai-toolkit Z-Image suggested: de-distill adapter ON, rank 12-16, ~2000 steps, "
         "batch 1-2, save checkpoint every 500, caption dropout 0.05.\n")


def _export_caption(ds, caption) -> str:
    """The exact text a trainer reads for one image: the dataset trigger prepended
    to the stored caption (captions are stored WITHOUT it — it's added at export).
    Single source of truth shared by the ZIP export and write_caption_files, so
    on-disk .txt sidecars always match what the ZIP would contain."""
    cap = (caption or '').strip()
    return f"{ds.trigger_word}, {cap}" if cap else ds.trigger_word


def build_export_zip(user_id, dataset_id, *, destination=None):
    """Training-ready ZIP in the PUBLIC-TOOL layout, not an app-internal format:
    one `10_<trigger>/` folder of `image.png` + same-stem `image.txt` caption
    pairs (captions carry the resolved trigger inline). That single shape feeds
    every mainstream trainer as-is: ai-toolkit (point the dataset at the folder;
    the folder name is ignored), kohya_ss / sd-scripts (drop under img/ — the
    `10_` prefix IS kohya's repeats convention), OneTrainer & friends (image+txt
    pairs). The info file is .md so no caption-scanner ever picks it up."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    kept = (FaceDatasetImage.query.filter_by(dataset_id=dataset_id, status='keep')
            .order_by(FaceDatasetImage.id.asc()).all())
    if not kept:
        raise ValueError('no kept images to export')
    available = [img for img in kept
                 if img.filename and os.path.exists(_img_path(img))]
    if not available:
        raise ValueError('kept image files are missing; run the integrity check')
    safe = ''.join(c for c in ds.name if c.isalnum() or c in ('-', '_')) or 'dataset'
    safe_trigger = ''.join(c for c in ds.trigger_word if c.isalnum() or c in ('-', '_')) or 'lora'
    folder = f"10_{safe_trigger}"
    comp = {'face': 0, 'bust': 0, 'body': 0, 'back': 0}
    exported_meta = []
    buf = destination if destination is not None else io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # The primary reference is an identity/generation anchor, not an admitted
        # training row. Every training/export surface consumes the same explicit
        # status='keep' projection; users can import the reference if they want it
        # represented in the training set.
        for n, img in enumerate(available, 1):
            path = _img_path(img)
            png = io.BytesIO()
            with Image.open(path) as opened, opened.convert('RGB') as converted:
                converted.save(png, 'PNG')
            png_bytes = png.getvalue()
            exported_caption = _export_caption(ds, img.caption)
            base = f"{folder}/{safe}_{n:03d}"
            zf.writestr(f"{base}.png", png_bytes)
            zf.writestr(f"{base}.txt", exported_caption)
            exported_meta.append({
                'file': f'{safe}_{n:03d}.png',
                'caption_file': f'{safe}_{n:03d}.txt',
                'source': img.source,
                'source_name': img.source_name or '',
                'source_sha256': img.source_sha256,
                'content_sha256': hashlib.sha256(png_bytes).hexdigest(),
                'caption_sha256': hashlib.sha256(
                    exported_caption.encode('utf-8')).hexdigest(),
                'framing': img.framing,
                'technical': img.training_usefulness,
                'coverage': parse_coverage(img.coverage_json),
                'coverage_provenance': _safe_json(img.coverage_provenance),
                'source_rights': (_safe_json(img.source_rights) or
                                  {'basis': 'generated' if img.source == 'generated'
                                   else 'unknown'}),
                'duplicate_of_id': img.duplicate_of_id,
                'generation_engine': img.generation_engine or (
                    img.klein_model if img.source == 'generated' else None),
                'generation_gap_ids': _parse_generation_gap_ids(img.generation_gap_ids),
                'generation_anchors': _parse_generation_anchor_metadata(
                    img.generation_anchor_metadata),
                'generation_provenance': _safe_json(img.generation_provenance),
            })
            if img.framing in comp:
                comp[img.framing] += 1
        zf.writestr(f"{folder}/_dataset_info.md",
                    _INFO.format(trigger=ds.trigger_word, n=len(exported_meta), comp=comp))
        zf.writestr(f"{folder}/_prep_my_avatar_manifest.json", json.dumps({
            'format': 'prep-my-avatar-training-export',
            'version': 2,
            'dataset': {'name': ds.name, 'trigger_word': ds.trigger_word,
                        'kind': ds.kind or 'character',
                        'fidelity': ds.fidelity or 'face',
                        'coverage_profile': ds.coverage_profile or 'balanced',
                        'coverage_targets': _safe_json(ds.coverage_targets)},
            'images': exported_meta,
            'source_mix': {
                'reference': sum(1 for item in exported_meta if item['source'] == 'reference'),
                'imported': sum(1 for item in exported_meta if item['source'] == 'import'),
                'generated': sum(1 for item in exported_meta if item['source'] == 'generated'),
            },
            'coverage_plan': build_coverage_plan(ds, available),
            'attribution': {
                'fork': 'Prep My Avatar',
                'upstream': 'perfectgf/lora-dataset-studio',
                'license': 'PolyForm Noncommercial 1.0.0',
            },
        }, ensure_ascii=False, indent=2))
    return buf if destination is not None else buf.getvalue()


def write_caption_files(user_id, dataset_id) -> dict:
    """Write a kohya/ai-toolkit-style `<image>.txt` sidecar NEXT TO each kept
    captioned image in the dataset folder (data/datasets/<id>/) — same caption
    text as the ZIP export (trigger prepended), for tools that read the folder
    directly instead of downloading the ZIP. Overwrites existing .txt files
    (it's a resync after re-captioning/edits); kept images without a caption are
    counted, not written — they'd only get the bare trigger, better captioned
    first. Returns {'ok', 'written', 'skipped_uncaptioned'}."""
    ds = get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    kept = (FaceDatasetImage.query.filter_by(dataset_id=dataset_id, status='keep')
            .order_by(FaceDatasetImage.id.asc()).all())
    written = skipped_uncaptioned = 0
    for img in kept:
        if not img.filename or not os.path.exists(_img_path(img)):
            continue                       # nothing on disk to sit next to
        if not (img.caption or '').strip():
            skipped_uncaptioned += 1
            continue
        stem = os.path.splitext(img.filename)[0]
        with open(os.path.join(_dataset_dir(dataset_id), f'{stem}.txt'), 'w',
                  encoding='utf-8') as fh:
            fh.write(_export_caption(ds, img.caption))
        written += 1
    return {'ok': True, 'written': written, 'skipped_uncaptioned': skipped_uncaptioned}
