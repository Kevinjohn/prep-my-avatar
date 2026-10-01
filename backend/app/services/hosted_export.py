"""Offline export boundary over the existing admitted person corpus.

list_sources/preview select and review exact target inputs; capture freezes their
roles, lineage, user decisions and emitted bytes into one atomic revision.
hosted_export_recipes owns versioned model/service compatibility and crop/layout
rules; its bounded formatters are the extension seam. Provider execution is a
separate future responsibility. Ordinary export and backup are unchanged.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import os
import shutil
import uuid
import zipfile
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from ..models import FaceDatasetImage
from ..utils.file_hashing import sha256_file
from . import face_dataset_service as fds
from . import hosted_export_recipes as recipes

ROLES = ('training', 'reference', 'evaluation')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _text(value, name, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name} must be non-empty text (at most {limit} characters)')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError(f'{name} contains control characters')
    return value.strip()


def _state(dataset, rows):
    # Include all corpus rows: an unselected parent or duplicate can bridge two
    # selected families, and rights/admission edits must be observed as well.
    def record(model):
        return {column.name: str(getattr(model, column.name))
                for column in model.__table__.columns}
    return {'dataset': record(dataset), 'images': [record(row) for row in rows]}


def _corpus(user_id, dataset_id):
    dataset = fds.get_dataset(user_id, dataset_id)
    if dataset is None:
        raise ValueError('dataset not found')
    if (dataset.kind or 'character') != 'character':
        raise ValueError('hosted person export requires a character dataset')
    rows = FaceDatasetImage.query.filter_by(dataset_id=dataset_id).order_by(
        FaceDatasetImage.id.asc()).all()
    return dataset, rows


def _safe_path(dataset_id, path):
    configured_root = Path(fds._dataset_dir(dataset_id)).absolute()
    path = Path(path).absolute()
    try:
        relative = path.relative_to(configured_root)
        if '..' in relative.parts:
            raise ValueError('source traversal')
        # Normalize only the trusted configured root. Reject child traversal
        # before normalization so a symlink/.. cannot bypass component checks.
        lexical_root = Path(os.path.abspath(configured_root))
        path = lexical_root / relative
        path.resolve(strict=True).relative_to(lexical_root.resolve())
    except (OSError, ValueError):
        raise ValueError('selected source is missing or has an unsafe path') from None
    # Host aliases above the configured root are trusted (e.g. macOS /var).
    # Symlinks strictly inside the dataset remain unsafe, even within-root ones.
    current = path
    while current != lexical_root:
        if current.is_symlink():
            raise ValueError('selected source has an unsafe symlink')
        current = current.parent
    if not path.is_file():
        raise ValueError('selected source is missing')
    return path


def _source(row):
    if not row.filename:
        raise ValueError('selected source is missing')
    # Validate filenames before training_source_path opens a possible original.
    _safe_path(row.dataset_id, Path(fds._dataset_dir(row.dataset_id)) / row.filename)
    if row.original_filename:
        original = Path(fds._dataset_dir(row.dataset_id)) / row.original_filename
        if original.exists():
            _safe_path(row.dataset_id, original)
    return _safe_path(row.dataset_id, fds.training_source_path(row))


def _rights(row):
    value = fds._safe_json(row.source_rights)
    return value if isinstance(value, dict) else {'basis': 'unknown'}


def _eligibility(row, role):
    if row.status != 'keep':
        return 'Only admitted (kept) images can be selected.'
    if not row.filename:
        return 'Image file is unavailable.'
    if role == 'reference' and row.anchor_decision == 'excluded':
        return 'This image is excluded from generation providers.'
    if role == 'evaluation' and row.source == 'generated':
        return 'Evaluation requires a real photograph.'
    rights = _rights(row)
    if rights.get('provider_excluded') is True or rights.get('consent_denied') is True:
        return 'Source rights exclude hosted use.'
    return ''


def _families(rows, source_checks=None):
    parents = {row.id: row.id for row in rows}

    def find(value):
        while parents[value] != value:
            parents[value] = parents[parents[value]]
            value = parents[value]
        return value

    def join(a, b):
        if b in parents:
            a, b = find(a), find(b)
            parents[max(a, b)] = min(a, b)

    seen = {}
    for row in rows:
        for related in (row.parent_image_id, row.duplicate_of_id):
            join(row.id, related)
        keys = [('source_hash', row.source_sha256),
                ('original_filename', row.original_filename)]
        # Hash originals as well: re-encodes can share an original even when the
        # current derivative and historical source_sha256 are different.
        if row.original_filename:
            original = Path(fds._dataset_dir(row.dataset_id)) / row.original_filename
            if original.exists():
                original = _safe_path(row.dataset_id, original)
                original_hash = sha256_file(original)
                keys.append(('original_hash', original_hash))
                if source_checks is not None:
                    source_checks[original] = original_hash
        for kind, value in keys:
            if value:
                key = (kind, value)
                if key in seen:
                    join(row.id, seen[key])
                seen[key] = row.id
    return {row.id: find(row.id) for row in rows}


def list_sources(user_id, dataset_id):
    dataset, rows = _corpus(user_id, dataset_id)
    families = _families(rows)
    images = []
    for row in rows:
        width = height = None
        reason = _eligibility(row, 'training')
        try:
            with Image.open(_source(row)) as image, ImageOps.exif_transpose(image) as oriented:
                width, height = oriented.size
        except (ValueError, OSError):
            reason = 'Image file is unavailable or invalid.'
        images.append({
            'id': row.id, 'status': row.status, 'caption': row.caption or '',
            'source': row.source, 'framing': row.framing,
            'original_lineage': families[row.id],
            'duplicate_group': families[row.id], 'rights': _rights(row),
            'anchor_decision': row.anchor_decision or 'auto',
            'eligible': not reason, 'exclusion_reason': reason,
            'role_exclusions': {role: _eligibility(row, role) for role in ROLES},
            'width': width, 'height': height,
            'source_preview_url': f'/api/dataset/{dataset_id}/hosted-export/source/{row.id}',
        })
    return {'dataset_revision': int(dataset.revision or 0),
            'subject': {'name': dataset.name, 'trigger_word': dataset.trigger_word},
            'recipes': [recipes.get_recipe(*key) for key in sorted(recipes.DEFINITIONS)],
            'images': images}


def source_preview(user_id, dataset_id, image_id):
    _, rows = _corpus(user_id, dataset_id)
    row = next((row for row in rows if row.id == image_id), None)
    if row is None:
        raise ValueError('image not found in dataset')
    with Image.open(_source(row)) as opened, ImageOps.exif_transpose(opened) as oriented:
        image = oriented.convert('RGB')
        try:
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            clean = Image.new('RGB', image.size)
            clean.paste(image)
            buffer = io.BytesIO()
            clean.save(buffer, 'PNG')
            clean.close()
            return buffer.getvalue()
        finally:
            image.close()


def _derivative(row, selection, definition, parameters, trigger):
    role = selection.get('role', 'training')
    if role not in definition['supported_roles']:
        raise ValueError('unsupported selection role for this recipe')
    reason = _eligibility(row, role)
    if reason:
        raise ValueError(reason)
    source = _source(row)
    raw = source.read_bytes()
    warnings = []
    with Image.open(io.BytesIO(raw)) as opened, ImageOps.exif_transpose(opened) as oriented:
        width, height = oriented.size
        crop = selection.get('crop')
        if crop is None:
            if role == 'training' and definition['crop_rule'] == 'square':
                side = min(width, height)
                left, top = (width-side)//2, (height-side)//2
                box = (left, top, left+side, top+side)
            else:
                box = (0, 0, width, height)
        else:
            if (not isinstance(crop, list) or len(crop) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v)
                           or v < 0 or v > 1 for v in crop)):
                raise ValueError('crop must be four normalized coordinates')
            box = tuple(round(v * size) for v, size in zip(crop, (width, height, width, height)))
        left, top, right, bottom = box
        if left >= right or top >= bottom:
            raise ValueError('crop has no image content')
        square = role == 'training' and definition['crop_rule'] == 'square'
        if square and right-left != bottom-top:
            raise ValueError('this recipe requires an exact square crop')
        if box != (0, 0, width, height):
            warnings.append('Crop removes source content. Check face, body and caption before approval.')
        if square and min(right-left, bottom-top) < parameters['resolution']:
            warnings.append('The source crop is smaller than the export resolution; detail will be upscaled.')
        with oriented.crop(box) as cropped, cropped.convert('RGB') as converted:
            if square:
                resized = converted.resize((parameters['resolution'], parameters['resolution']),
                                           Image.Resampling.LANCZOS)
            else:
                resized = converted.copy()
                resized.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            try:
                # New pixel-only image drops EXIF, ICC, text and all original metadata.
                with Image.new('RGB', resized.size) as clean:
                    clean.paste(resized)
                    buffer = io.BytesIO()
                    clean.save(buffer, 'PNG')
                    image_data = buffer.getvalue()
            finally:
                resized.close()
    override = selection.get('caption_override')
    if override is not None and (not isinstance(override, str) or len(override) > 10000):
        raise ValueError('caption override must be text (at most 10000 characters)')
    caption = (row.caption or '') if override is None else override
    caption = caption.strip()
    caption = f'{trigger}, {caption}' if caption else trigger
    transform = {'source_dimensions': [width, height], 'crop_pixels': list(box),
                 'crop_normalized': [left/width, top/height, right/width, bottom/height],
                 'output_format': 'PNG', 'metadata': 'stripped',
                 'resolution': parameters.get('resolution') if square else 'preserved-aspect-max-2048'}
    return image_data, caption, transform, warnings, source, _hash(raw)


def _pair_hash(image_hash, caption_hash, transform, source_hash):
    return _hash(json.dumps({'image_sha256': image_hash, 'caption_sha256': caption_hash,
                             'transform': transform, 'source_sha256': source_hash},
                            sort_keys=True, separators=(',', ':')).encode('utf-8'))


def preview(user_id, dataset_id, payload):
    if not isinstance(payload, dict):
        raise ValueError('preview must be an object')
    dataset, rows = _corpus(user_id, dataset_id)
    definition = recipes.get_recipe(payload.get('recipe_id'), payload.get('recipe_version'))
    parameters = recipes.parameters(definition, payload.get('parameters', {}))
    trigger = _text(payload.get('trigger_word', dataset.trigger_word), 'trigger word', 60)
    image_id = payload.get('image_id')
    if type(image_id) is not int:
        raise ValueError('image id must be an integer')
    row = next((row for row in rows if row.id == image_id), None)
    if row is None:
        raise ValueError('image not found in dataset')
    data, caption, crop, warnings, _, source_hash = _derivative(row, payload, definition, parameters, trigger)
    return {'image_data_url': 'data:image/png;base64,' + base64.b64encode(data).decode('ascii'),
            'image_sha256': _hash(data), 'caption': caption,
            'caption_sha256': _hash(caption.encode('utf-8')),
            'pair_sha256': _pair_hash(_hash(data), _hash(caption.encode('utf-8')), crop, source_hash),
            'crop': crop, 'warnings': warnings}


def _validate_selection(payload, dataset, rows, families, definition):
    subject = payload.get('subject')
    if not isinstance(subject, dict) or subject.get('consent') is not True:
        raise ValueError('subject consent must be explicitly confirmed')
    subject = {'name': _text(subject.get('name'), 'subject name', 100),
               'trigger_word': _text(subject.get('trigger_word'), 'trigger word', 60),
               'consent': True,
               'rights_basis': subject.get('rights_basis'),
               'publication_scope': _text(subject.get('publication_scope'), 'publication scope')}
    if subject['rights_basis'] not in ('owned', 'licensed', 'consented', 'public-domain'):
        raise ValueError('confirm a usable source rights basis')
    if type(payload.get('dataset_revision')) is not int or payload['dataset_revision'] != int(dataset.revision or 0):
        raise ValueError('dataset changed since review; refresh the source list')
    selections = payload.get('selections')
    if not isinstance(selections, list) or not selections or len(selections) > 10000:
        raise ValueError('select at least one image (at most 10000 selections)')
    by_id = {row.id: row for row in rows}
    seen = set()
    family_roles = {}
    group_families = {}
    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError('selection must be an object')
        image_id, role = selection.get('image_id'), selection.get('role')
        if type(image_id) is not int or image_id not in by_id or role not in definition['supported_roles']:
            raise ValueError('invalid selected image or role')
        if (image_id, role) in seen:
            raise ValueError('duplicate image role selection')
        seen.add((image_id, role))
        reason = _eligibility(by_id[image_id], role)
        if reason:
            raise ValueError(reason)
        family = families[image_id]
        family_roles.setdefault(family, set()).add(role)
        group = selection.get('burst_group')
        if group:
            group = _text(group, 'burst group', 100)
            group_families.setdefault(group, set()).add(family)
        if role == 'reference':
            _text(selection.get('reference_role'), 'reference purpose', 100)
    # Propagate burst associations across role-specific selections of each family.
    linked = {key: {key} for key in family_roles}
    for group in group_families.values():
        merged = set().union(*(linked[family] for family in group))
        for family in merged:
            linked[family] = merged
    for family, linked_families in linked.items():
        roles = set().union(*(family_roles[item] for item in linked_families))
        if 'evaluation' in roles and roles & {'training', 'reference'}:
            raise ValueError('held-out lineage or burst overlaps training/reference selections')
    for required_role, minimum in recipes.role_minima(definition).items():
        if sum(role == required_role for _, role in seen) < minimum:
            raise ValueError(f'select at least {minimum} {required_role} image(s)')
    excluded = payload.get('excluded_image_ids', [])
    if (not isinstance(excluded, list) or any(type(v) is not int or v not in by_id for v in excluded)
            or set(excluded) & {image_id for image_id, _ in seen}):
        raise ValueError('invalid or conflicting excluded image selections')
    return subject, selections, excluded, by_id


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def capture(user_id, dataset_id, payload, destination):
    """Selection/materialisation boundary; no credentials, trainer or network.

    Review decisions are immutable request data. Corpus and recipe states plus
    every selected source/original are checked again before atomic publication.
    """
    if not isinstance(payload, dict):
        raise ValueError('export configuration must be an object')
    payload = copy.deepcopy(payload)
    dataset, rows = _corpus(user_id, dataset_id)
    initial_state = _state(dataset, rows)
    definition = recipes.get_recipe(payload.get('recipe_id'), payload.get('recipe_version'))
    parameters = recipes.parameters(definition, payload.get('parameters', {}))
    source_checks = {}
    families = _families(rows, source_checks)
    subject, selections, excluded, by_id = _validate_selection(
        payload, dataset, rows, families, definition)
    # End the read transaction so the final check observes independent commits.
    fds.db.session.commit()
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('export revision already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.tmp-' + uuid.uuid4().hex)
    temporary.mkdir(mode=0o700)
    entries = []
    try:
        (temporary / 'references').mkdir(mode=0o700)
        (temporary / 'evaluation').mkdir(mode=0o700)
        archive_context = (zipfile.ZipFile(temporary / definition['archive_name'], 'w', zipfile.ZIP_DEFLATED)
                           if 'training' in definition['supported_roles'] else nullcontext())
        with archive_context as archive:
            for index, selection in enumerate(selections):
                row = by_id[selection['image_id']]
                data, caption, transform, warnings, source, source_hash = _derivative(
                    row, selection, definition, parameters, subject['trigger_word'])
                image_hash, caption_hash = _hash(data), _hash(caption.encode('utf-8'))
                if (selection.get('approved_image_sha256') != image_hash
                        or selection.get('approved_caption_sha256') != caption_hash
                        or selection.get('approved_pair_sha256') != _pair_hash(
                            image_hash, caption_hash, transform, source_hash)):
                    raise ValueError('exact derivative and caption approval required; preview and review again')
                if source in source_checks and source_checks[source] != source_hash:
                    raise RuntimeError('source changed while export was captured')
                source_checks[source] = source_hash
                stem = f'{index:05d}_{row.id}'
                role = selection['role']
                if role == 'training':
                    image_name, caption_name = recipes.pair_names(definition, stem)
                    archive.writestr(image_name, data)
                    archive.writestr(caption_name, caption.encode('utf-8'))
                else:
                    folder = 'references' if role == 'reference' else 'evaluation'
                    image_name, caption_name = f'{folder}/{stem}.png', f'{folder}/{stem}.txt'
                    (temporary / image_name).write_bytes(data)
                    (temporary / caption_name).write_text(caption, encoding='utf-8')
                entries.append({
                    'image_id': row.id, 'role': role,
                    'reference_role': selection.get('reference_role'),
                    'reference_order': sum(e['role'] == 'reference' for e in entries) if role == 'reference' else None,
                    'burst_group': selection.get('burst_group'),
                    'original_lineage': families[row.id],
                    'parent_image_id': row.parent_image_id, 'duplicate_of_id': row.duplicate_of_id,
                    'source_sha256': row.source_sha256, 'captured_source_sha256': source_hash,
                    'source': row.source, 'admission': row.status,
                    'anchor_decision': row.anchor_decision or 'auto', 'rights': _rights(row),
                    'master_caption': row.caption or '', 'caption_override': selection.get('caption_override'),
                    'caption': caption, 'image_path': image_name, 'caption_path': caption_name,
                    'image_sha256': image_hash, 'caption_sha256': caption_hash,
                    'transform': transform, 'review_warnings': warnings,
                    'approved_image_sha256': image_hash, 'approved_caption_sha256': caption_hash,
                    'approved_pair_sha256': selection['approved_pair_sha256'],
                })
        recipe_record = {'format': 'person-export-pinned-recipe', 'schema_version': 1,
                         'definition': definition, 'parameters': parameters,
                         'trigger_phrase': subject['trigger_word']}
        _write_json(temporary / 'recipe.json', recipe_record)
        training_instructions = (
            'Only the training ZIP contains provider inputs; never upload the outer package, '
            'manifest, references or evaluation directory as the training dataset.\n\n'
            if 'training' in definition['supported_roles'] else
            'This reference-only package contains no training archive. Select compatible references '
            'for the chosen endpoint; never submit held-out evaluation photos as generation inputs. '
            'Provider input compatibility remains unverified.\n\n')
        (temporary / 'README.md').write_text(
            '# Private person export\n\n'
            'Keep this complete revision private, with your master originals and a backup. '
            + training_instructions +
            'Before manual submission, recheck the endpoint documentation, consent, source rights, '
            'service retention and publication scope, current prices and an agreed spending ceiling. '
            'Review the pinned definition and parameters in recipe.json before use. '
            'For training, use reviewed sidecars and automatic captioning off. '
            'Provider acceptance and output likeness remain unverified.\n\n'
            'Use references in manifest order and map each purpose explicitly in prompts. '
            'Keep evaluation photographs held out from training and generation references. '
            'Compare generated identity, anatomy, composition and correction effort against these '
            'real views. Save accepted outputs, returned weights and configuration privately with '
            'hashes, recipe and compatibility evidence; provider URLs are temporary.\n', encoding='utf-8')
        hashes = {str(path.relative_to(temporary)).replace(os.sep, '/'): sha256_file(path)
                  for path in temporary.rglob('*') if path.is_file()}
        manifest = {'format': 'person-hosted-export', 'schema_version': 1,
                    'export_revision': destination.name,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'dataset_id': dataset_id, 'dataset_revision': int(dataset.revision or 0),
                    'subject': subject, 'recipe': recipe_record, 'entries': entries,
                    'excluded_image_ids': excluded,
                    'selection': {'dataset_revision': payload['dataset_revision'],
                                  'recipe_id': definition['id'], 'recipe_version': definition['version'],
                                  'parameters': parameters, 'subject': subject,
                                  'selections': [{key: item[key] for key in (
                                      'image_id', 'role', 'reference_role', 'burst_group', 'crop',
                                      'caption_override', 'approved_image_sha256',
                                      'approved_caption_sha256', 'approved_pair_sha256') if key in item}
                                      for item in selections],
                                  'excluded_image_ids': excluded}, 'files': hashes,
                    'lineage': [{'image_id': row.id, 'original_lineage': families[row.id],
                                 'parent_image_id': row.parent_image_id,
                                 'duplicate_of_id': row.duplicate_of_id,
                                 'source_sha256': row.source_sha256,
                                 'original_content_sha256': source_checks.get(
                                     Path(fds._dataset_dir(dataset_id)) / row.original_filename)
                                 if row.original_filename else None} for row in rows]}
        _write_json(temporary / 'manifest.json', manifest)
        for source, expected_hash in source_checks.items():
            if sha256_file(_safe_path(dataset_id, source)) != expected_hash:
                raise RuntimeError('source changed while export was captured')
        fds.db.session.expire_all()
        current_dataset, current_rows = _corpus(user_id, dataset_id)
        if _state(current_dataset, current_rows) != initial_state:
            raise RuntimeError('dataset changed while export was captured; refresh and retry')
        if recipes.get_recipe(definition['id'], definition['version']) != definition:
            raise RuntimeError('recipe changed while export was captured; review again')
        # A completed directory is the publication marker; all files are already
        # closed before rename. An interruption leaves only a .tmp directory.
        for path in temporary.rglob('*'):
            if path.is_file():
                path.chmod(0o600)
        if destination.exists():
            raise FileExistsError('export revision already exists')
        temporary.rename(destination)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def build_package_zip(user_id, dataset_id, payload, destination):
    """Persist a completed local revision, then stream its transport archive."""
    parent = Path(fds._dataset_dir(dataset_id)) / 'hosted_exports'
    revision = 'avatar_export_' + uuid.uuid4().hex
    root = parent / revision
    capture(user_id, dataset_id, payload, root)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                archive.write(path, f'{revision}/{path.relative_to(root).as_posix()}')
    return revision
