"""Read-only consistency audit for the SQLite graph and dataset filesystem."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from sqlalchemy import text

from .. import config as cfg
from ..extensions import db
from ..models import (BackgroundJob, CloudTrainingRun, CurationEvent,
                      FaceDataset, FaceDatasetImage, ImageGenerationQueue,
                      LoraTestImage, TrainingPreset, TrainingRunRecord)
from ..utils.time import utcnow

_HASH_RE = re.compile(r'^[0-9a-f]{64}$')
_IMAGE_STATUSES = {'pending', 'keep', 'reject', 'failed', 'trashed'}
_KINDS = {None, '', 'character', 'concept', 'style'}
_FIDELITIES = {None, '', 'face', 'body'}
_COVERAGE_PROFILES = {None, '', 'strict', 'balanced', 'experimental'}
_ANCHOR_DECISIONS = {None, '', 'auto', 'pinned', 'excluded'}
_QUEUE_TERMINAL = {'completed', 'failed', 'cancelled'}


def _json_list(value):
    try:
        parsed = json.loads(value or '[]')
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def _safe_filename(value) -> bool:
    if not value or not isinstance(value, str):
        return False
    p = Path(value)
    return (not p.is_absolute() and bool(p.parts)
            and all(part not in ('', '.', '..') for part in p.parts))


def _safe_dataset_path(folder: Path, value):
    if not _safe_filename(value):
        return None
    candidate = folder / value
    try:
        candidate.resolve(strict=False).relative_to(folder.resolve())
    except (OSError, ValueError):
        return None
    return candidate


def run(*, include_orphans=True) -> dict:
    findings = []

    def add(severity, code, message, **context):
        findings.append({'severity': severity, 'code': code, 'message': message,
                         **{key: value for key, value in context.items()
                            if value is not None}})

    def structured_json(value, expected_type, code, message, **context):
        """Parse one documented JSON column and report corrupt legacy rows."""
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = None
        if not isinstance(parsed, expected_type):
            add('warning', code, message, **context)
            return None
        return parsed

    def normalized_box(value):
        return (isinstance(value, list) and len(value) == 4
                and all(not isinstance(item, bool)
                        and isinstance(item, (int, float))
                        and math.isfinite(item) and 0 <= item <= 1
                        for item in value)
                and value[0] < value[2] and value[1] < value[3])

    # SQLite engine-level corruption and FK diagnostics come first; service-level
    # checks below remain useful even on schemas that predate enforced FKs.
    try:
        rows = db.session.execute(text('PRAGMA integrity_check')).all()
        for row in rows:
            if str(row[0]).lower() != 'ok':
                add('error', 'sqlite_integrity', str(row[0]))
    except Exception as exc:
        add('error', 'sqlite_integrity_unavailable', str(exc))
    try:
        for table, rowid, parent, fk_index in db.session.execute(
                text('PRAGMA foreign_key_check')).all():
            add('error', 'foreign_key_violation',
                f'{table} row {rowid} has no parent in {parent}',
                table=table, row_id=rowid, foreign_key_index=fk_index)
    except Exception as exc:
        add('warning', 'foreign_key_check_unavailable', str(exc))

    datasets = FaceDataset.query.all()
    dataset_ids = {row.id for row in datasets}
    images = FaceDatasetImage.query.all()
    image_by_id = {row.id: row for row in images}
    queue_by_job = {row.job_id: row for row in ImageGenerationQueue.query.all()}

    images_by_dataset = {}
    for image in images:
        images_by_dataset.setdefault(image.dataset_id, []).append(image)
        if image.dataset_id not in dataset_ids:
            add('error', 'dangling_image_dataset',
                'Image row points to a missing dataset.', image_id=image.id,
                dataset_id=image.dataset_id)
        if image.status not in _IMAGE_STATUSES:
            add('error', 'invalid_image_status', f'Unknown image status: {image.status}',
                image_id=image.id, dataset_id=image.dataset_id)
        if image.anchor_decision not in _ANCHOR_DECISIONS:
            add('warning', 'invalid_anchor_decision',
                f'Unknown anchor decision: {image.anchor_decision}', image_id=image.id)
        if image.source_sha256 and not _HASH_RE.fullmatch(image.source_sha256):
            add('warning', 'invalid_source_hash', 'Stored source SHA-256 is malformed.',
                image_id=image.id)
        if image.perceptual_hash and not re.fullmatch(
                r'[0-9a-f]{16}', image.perceptual_hash):
            add('warning', 'invalid_perceptual_hash',
                'Stored 64-bit perceptual hash is malformed.', image_id=image.id)
        for field in ('analysis_json', 'coverage_json', 'coverage_provenance',
                      'source_rights', 'generation_provenance'):
            if getattr(image, field):
                structured_json(
                    getattr(image, field), dict, f'invalid_{field}',
                    f'{field} is not a JSON object.', image_id=image.id,
                    dataset_id=image.dataset_id)
        for field, target_id in (('parent_image_id', image.parent_image_id),
                                 ('duplicate_of_id', image.duplicate_of_id)):
            if target_id is not None and target_id not in image_by_id:
                add('error', 'dangling_image_link', f'{field} points to a missing image.',
                    image_id=image.id, target_id=target_id, field=field)
            elif (target_id is not None
                  and image_by_id[target_id].dataset_id != image.dataset_id):
                add('error', 'cross_dataset_image_link',
                    f'{field} points into a different dataset.', image_id=image.id,
                    target_id=target_id, field=field)
        anchor_ids = _json_list(image.generation_anchor_ids)
        if image.generation_anchor_ids and anchor_ids is None:
            add('warning', 'invalid_anchor_json', 'Generation anchor ids are not a JSON list.',
                image_id=image.id)
        for target_id in anchor_ids or []:
            if (isinstance(target_id, bool) or not isinstance(target_id, int)
                    or target_id <= 0):
                add('warning', 'invalid_generation_anchor_id',
                    'Generation provenance contains a non-positive or non-integer image id.',
                    image_id=image.id, target_id=target_id)
            elif target_id not in image_by_id:
                add('warning', 'dangling_generation_anchor',
                    'Generation provenance points to a missing image.',
                    image_id=image.id, target_id=target_id)
            elif image_by_id[target_id].dataset_id != image.dataset_id:
                add('warning', 'cross_dataset_generation_anchor',
                    'Generation provenance points into a different dataset.',
                    image_id=image.id, target_id=target_id)
        if image.generation_anchor_metadata:
            structured_json(
                image.generation_anchor_metadata, list,
                'invalid_generation_anchor_metadata',
                'Generation anchor metadata are not a JSON list.',
                image_id=image.id, dataset_id=image.dataset_id)
        if image.generation_gap_ids:
            gap_ids = structured_json(
                image.generation_gap_ids, list, 'invalid_generation_gap_ids',
                'Generation coverage gap ids are not a JSON list.',
                image_id=image.id, dataset_id=image.dataset_id)
            if gap_ids is not None and any(
                    isinstance(item, bool) or not isinstance(item, (str, int))
                    for item in gap_ids):
                add('warning', 'invalid_generation_gap_id',
                    'Generation coverage gap ids contain an unsupported value.',
                    image_id=image.id, dataset_id=image.dataset_id)
        if image.watermark_bbox:
            box = structured_json(
                image.watermark_bbox, list, 'invalid_watermark_bbox_json',
                'Watermark bounding box is not a JSON list.', image_id=image.id)
            if box is not None and not normalized_box(box):
                add('warning', 'invalid_watermark_bbox',
                    'Watermark bounding box is not a valid normalized rectangle.',
                    image_id=image.id)
        if image.watermark_regions:
            boxes = structured_json(
                image.watermark_regions, list, 'invalid_watermark_regions_json',
                'Watermark regions are not a JSON list.', image_id=image.id)
            if boxes is not None and any(not normalized_box(box) for box in boxes):
                add('warning', 'invalid_watermark_region',
                    'Watermark regions contain an invalid normalized rectangle.',
                    image_id=image.id)
        if image.job_id:
            queue = queue_by_job.get(image.job_id)
            if queue is None:
                add('error', 'missing_generation_job',
                    'Image row points to a missing generation job.', image_id=image.id,
                    job_id=image.job_id)
            elif image.status == 'pending' and not image.filename and queue.status in _QUEUE_TERMINAL:
                add('error', 'unlinked_generation_result',
                    f'Pending image is linked to terminal queue state {queue.status}.',
                    image_id=image.id, job_id=image.job_id)

    for ds in datasets:
        if ds.kind not in _KINDS:
            add('warning', 'invalid_dataset_kind', f'Unknown dataset kind: {ds.kind}',
                dataset_id=ds.id)
        if ds.fidelity not in _FIDELITIES:
            add('warning', 'invalid_fidelity', f'Unknown fidelity target: {ds.fidelity}',
                dataset_id=ds.id)
        if ds.coverage_profile not in _COVERAGE_PROFILES:
            add('warning', 'invalid_coverage_profile',
                f'Unknown coverage profile: {ds.coverage_profile}', dataset_id=ds.id)
        for field, expected_type in (
                ('best_settings', dict), ('train_settings', dict),
                ('concept_terms', list)):
            if getattr(ds, field):
                structured_json(
                    getattr(ds, field), expected_type, f'invalid_{field}',
                    f'{field} has the wrong JSON shape.', dataset_id=ds.id)
        if ds.coverage_targets:
            try:
                parsed_targets = json.loads(ds.coverage_targets)
            except (TypeError, ValueError):
                parsed_targets = None
            if not isinstance(parsed_targets, dict):
                add('warning', 'invalid_coverage_targets',
                    'Coverage targets are not a JSON object.', dataset_id=ds.id)
        if ds.trashed_at and not ds.trash_entry_id:
            add('error', 'trashed_dataset_without_entry',
                'Dataset is marked trashed but has no restore entry.', dataset_id=ds.id)
        if ds.trashed_at:
            continue
        candidates = [('ref_filename', ds.ref_filename),
                      ('ref_original_filename', ds.ref_original_filename)]
        extras = _json_list(ds.ref_extra_filenames)
        if ds.ref_extra_filenames and extras is None:
            add('warning', 'invalid_extra_refs_json',
                'Additional references are not a JSON list.', dataset_id=ds.id)
        elif extras is not None and any(not isinstance(item, str) for item in extras):
            add('warning', 'invalid_extra_ref_value',
                'Additional references contain a non-string filename.',
                dataset_id=ds.id)
        candidates.extend(('ref_extra_filenames', item) for item in (extras or []))
        for image in images_by_dataset.get(ds.id, []):
            if image.status == 'trashed':
                continue
            candidates.extend((('image.filename', image.filename),
                               ('image.original_filename', image.original_filename)))
        folder = Path(cfg.dataset_images_root()) / str(ds.id)
        if not folder.is_dir():
            present_refs = [(field, filename) for field, filename in candidates if filename]
            # A newly-created empty dataset legitimately has no directory yet;
            # the service creates it with the first reference/import.
            if not present_refs:
                continue
            add('error', 'missing_dataset_directory', 'Dataset directory is missing.',
                dataset_id=ds.id, path=str(folder))
            for field, filename in present_refs:
                add('error', 'missing_referenced_file',
                    f'{field} points to a file that is missing.', dataset_id=ds.id,
                    filename=str(filename))
            continue

        referenced = set()
        for field, filename in candidates:
            if not filename:
                continue
            candidate = _safe_dataset_path(folder, filename)
            if candidate is None:
                add('error', 'unsafe_dataset_filename',
                    f'{field} is not a safe dataset-local filename.', dataset_id=ds.id,
                    filename=str(filename))
                continue
            referenced.add(str(filename).replace('\\', '/'))
            if not candidate.is_file():
                add('error', 'missing_referenced_file',
                    f'{field} points to a file that is missing.', dataset_id=ds.id,
                    filename=filename)

        if include_orphans:
            stems = {Path(name).stem for name in referenced}
            for child in folder.rglob('*'):
                if child.is_symlink():
                    add('error', 'dataset_symlink',
                        'Dataset storage contains a symbolic link.', dataset_id=ds.id,
                        filename=child.relative_to(folder).as_posix())
                    continue
                if not child.is_file():
                    continue
                relative = child.relative_to(folder).as_posix()
                if relative in referenced or child.name.startswith('.'):
                    continue
                # Same-stem caption files are intentionally materialized for local
                # trainers; they are derived and safe to regenerate.
                if child.suffix.lower() == '.txt' and child.stem in stems:
                    continue
                if child.stem.endswith('.orig') and child.stem[:-5] in stems:
                    continue
                add('warning', 'untracked_dataset_file',
                    'File is not referenced by the dataset database.', dataset_id=ds.id,
                    filename=child.name)

    for model, label in ((LoraTestImage, 'lora_test_image'),):
        for row in model.query.all():
            if row.dataset_id not in dataset_ids:
                add('error', 'dangling_dataset_reference',
                    f'{label} points to a missing dataset.', table=label,
                    row_id=row.id, dataset_id=row.dataset_id)
            if row.extra_loras:
                structured_json(
                    row.extra_loras, list, 'invalid_lora_test_extra_loras',
                    'Studio extra LoRAs are not a JSON list.', table=label,
                    row_id=row.id, dataset_id=row.dataset_id)

    for row in CurationEvent.query.all():
        for field in ('before_state', 'after_state'):
            structured_json(
                getattr(row, field), dict, f'invalid_curation_{field}',
                f'Curation {field} is not a JSON object.',
                table='curation_event', row_id=row.id, dataset_id=row.dataset_id)

    for row in ImageGenerationQueue.query.all():
        for field in ('workflow_data', 'job_metadata'):
            if getattr(row, field):
                structured_json(
                    getattr(row, field), dict, f'invalid_generation_{field}',
                    f'Generation {field} is not a JSON object.',
                    table='image_generation_queue', row_id=row.id, job_id=row.job_id)

    for row in BackgroundJob.query.all():
        for field, expected_type in (
                ('payload', dict), ('result', dict), ('log', list), ('progress', dict)):
            if getattr(row, field) is not None:
                structured_json(
                    getattr(row, field), expected_type,
                    f'invalid_background_job_{field}',
                    f'Background job {field} has the wrong JSON shape.',
                    table='background_job', row_id=row.id)

    # Launch records are historical provenance and intentionally survive a
    # future permanent dataset purge. Surface that relationship without making
    # an otherwise consistent database fail its integrity gate.
    for model, label in ((TrainingRunRecord, 'training_run_record'),
                         (CloudTrainingRun, 'cloud_training_run')):
        for row in model.query.all():
            if row.dataset_id not in dataset_ids:
                add('warning', 'historical_dataset_missing',
                    f'{label} refers to a dataset that has since been removed.',
                    table=label, row_id=row.id, dataset_id=row.dataset_id)

    for row in CloudTrainingRun.query.all():
        if row.train_params:
            structured_json(
                row.train_params, dict, 'invalid_cloud_train_params',
                'Cloud training parameters are not a JSON object.',
                table='cloud_training_run', row_id=row.id,
                dataset_id=row.dataset_id)

    for row in TrainingRunRecord.query.all():
        if row.manifest is not None:
            structured_json(
                row.manifest, list, 'invalid_training_manifest',
                'Training provenance manifest is not a JSON list.',
                table='training_run_record', row_id=row.id,
                dataset_id=row.dataset_id)
        for field in ('settings', 'preflight', 'overrides'):
            if getattr(row, field):
                structured_json(
                    getattr(row, field), dict, f'invalid_training_{field}',
                    f'Training provenance {field} is not a JSON object.',
                    table='training_run_record', row_id=row.id,
                    dataset_id=row.dataset_id)

    for row in TrainingPreset.query.all():
        structured_json(
            row.settings, dict, 'invalid_training_preset_settings',
            'Training preset settings are not a JSON object.',
            table='training_preset', row_id=row.id)

    training_run_datasets = {
        row.id: row.dataset_id for row in TrainingRunRecord.query.all()
    }
    for row in LoraTestImage.query.filter(
            LoraTestImage.training_run_record_id.isnot(None)).all():
        linked_dataset_id = training_run_datasets.get(row.training_run_record_id)
        if linked_dataset_id is None:
            add('warning', 'missing_studio_training_provenance',
                'Studio evidence points to a missing training launch.',
                row_id=row.id, training_run_record_id=row.training_run_record_id)
        elif linked_dataset_id != row.dataset_id:
            add('error', 'cross_dataset_studio_training_provenance',
                'Studio evidence points to a training launch for another dataset.',
                row_id=row.id, dataset_id=row.dataset_id,
                training_run_record_id=row.training_run_record_id,
                training_dataset_id=linked_dataset_id)

    counts = {
        'errors': sum(item['severity'] == 'error' for item in findings),
        'warnings': sum(item['severity'] == 'warning' for item in findings),
        'datasets': len(datasets),
        'images': len(images),
    }
    return {
        'ok': counts['errors'] == 0,
        'counts': counts,
        'findings': findings,
        'generated_at': utcnow().isoformat(),
    }
