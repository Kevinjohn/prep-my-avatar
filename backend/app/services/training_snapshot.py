"""Immutable admitted-dataset snapshots used by deferred training workflows."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..models import FaceDatasetImage
from . import face_dataset_service as fds

FORMAT = 'prep-my-avatar-training-snapshot'
VERSION = 1
MANIFEST_NAME = 'training-snapshot.json'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _caption_hash(text) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def capture(user_id, dataset_id, destination) -> dict:
    """Copy every admitted input and caption into an immutable directory.

    The source is hashed again after copying. A concurrent in-place edit aborts
    the launch instead of producing a snapshot whose bytes and manifest disagree.
    """
    dataset = fds.get_dataset(user_id, dataset_id)
    if dataset is None:
        raise ValueError('dataset not found')
    rows = (FaceDatasetImage.query
            .filter_by(dataset_id=dataset_id, status='keep')
            .filter(FaceDatasetImage.filename.isnot(None))
            .order_by(FaceDatasetImage.id.asc()).all())
    if not rows:
        raise ValueError('no kept images to snapshot')
    initial_training_config = {
        'train_type': dataset.train_type,
        'train_base_model': dataset.train_base_model,
        'train_variant': dataset.train_variant,
        'train_vae_path': dataset.train_vae_path,
        'train_te_path': dataset.train_te_path,
        'train_settings': dataset.train_settings,
    }
    initial_dataset_state = (
        int(dataset.revision or 0), dataset.trigger_word,
        dataset.kind or 'character', dataset.fidelity or 'face',
        *initial_training_config.values(),
    )
    # End the read transaction after materialising the admitted rows. The final
    # check must open a new SQLite snapshot so it can observe edits committed by
    # another request while file copying was in progress.
    db_session = fds.db.session
    db_session.commit()

    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f'training snapshot already exists: {destination}')
    temporary = destination.with_name(f'{destination.name}.tmp-{uuid.uuid4().hex[:10]}')
    raw_dir = temporary / 'raw'
    raw_dir.mkdir(parents=True, mode=0o700)
    if os.name != 'nt':
        for private_dir in (temporary, raw_dir):
            try:
                private_dir.chmod(0o700)
            except OSError:
                pass
    entries = []
    source_checks = []
    dataset_root = Path(fds._dataset_dir(dataset_id)).resolve()
    try:
        for index, row in enumerate(rows):
            source = Path(fds._img_path(row))
            try:
                source.resolve(strict=True).relative_to(dataset_root)
            except (OSError, ValueError):
                raise ValueError(
                    f'admitted image has an unsafe path: {row.filename}')
            if source.is_symlink() or not source.is_file():
                raise ValueError(f'admitted image is missing on disk: {row.filename}')
            suffix = source.suffix.lower() if source.suffix else '.bin'
            stored_name = f'{index:05d}_{row.id}{suffix}'
            copied = raw_dir / stored_name
            before = source.stat()
            shutil.copy2(source, copied)
            if os.name != 'nt':
                try:
                    copied.chmod(0o600)
                except OSError:
                    pass
            copied_hash = _sha256(copied)
            after = source.stat()
            if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                    or _sha256(source) != copied_hash):
                raise RuntimeError(
                    f'dataset image changed while the training snapshot was captured: {row.filename}')
            source_checks.append((source, copied_hash, row.filename,
                                  (after.st_size, after.st_mtime_ns)))
            entries.append({
                'image_id': row.id,
                'stored_name': stored_name,
                'source_filename': row.filename,
                'content_sha256': copied_hash,
                'caption': row.caption or '',
                'caption_sha256': _caption_hash(row.caption),
                'source': row.source,
                'framing': row.framing,
            })
        # A file copied early can still be edited while later images are being
        # copied. Database revision checks cannot see edits made directly on
        # disk, so re-verify every admitted source at the end of the whole copy
        # window before publishing the immutable directory.
        for source, copied_hash, filename, expected_stat in source_checks:
            try:
                source.resolve(strict=True).relative_to(dataset_root)
                current = source.stat()
            except (OSError, ValueError):
                raise RuntimeError(
                    f'dataset image changed while the training snapshot was captured: {filename}')
            if (source.is_symlink() or not source.is_file()
                    or (current.st_size, current.st_mtime_ns) != expected_stat
                    or _sha256(source) != copied_hash):
                raise RuntimeError(
                    f'dataset image changed while the training snapshot was captured: {filename}')
        db_session.expire_all()
        current_dataset = fds.get_dataset(user_id, dataset_id)
        current_dataset_state = (
            int(current_dataset.revision or 0), current_dataset.trigger_word,
            current_dataset.kind or 'character', current_dataset.fidelity or 'face',
            current_dataset.train_type, current_dataset.train_base_model,
            current_dataset.train_variant, current_dataset.train_vae_path,
            current_dataset.train_te_path, current_dataset.train_settings,
        ) if current_dataset is not None else None
        if current_dataset_state != initial_dataset_state:
            raise RuntimeError(
                'dataset changed while the training snapshot was captured; retry launch')
        registry_manifest = [
            [entry['image_id'], entry['caption_sha256'], entry['content_sha256']]
            for entry in entries
        ]
        manifest = {
            'format': FORMAT,
            'version': VERSION,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'dataset_id': dataset_id,
            'dataset_revision': initial_dataset_state[0],
            'trigger_word': initial_dataset_state[1],
            'kind': initial_dataset_state[2],
            'fidelity': initial_dataset_state[3],
            'training_config': initial_training_config,
            'entries': entries,
            'registry_manifest': registry_manifest,
        }
        manifest_path = temporary / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        if os.name != 'nt':
            try:
                manifest_path.chmod(0o600)
            except OSError:
                pass
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(destination)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def load(snapshot_dir) -> dict:
    root = Path(snapshot_dir)
    try:
        manifest = json.loads((root / MANIFEST_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('training snapshot is missing or invalid')
    if not isinstance(manifest, dict):
        raise ValueError('training snapshot is missing or invalid')
    version = manifest.get('version')
    if (manifest.get('format') != FORMAT or isinstance(version, bool)
            or version != VERSION):
        raise ValueError('unsupported training snapshot')
    if (isinstance(manifest.get('dataset_id'), bool)
            or not isinstance(manifest.get('dataset_id'), int)):
        raise ValueError('training snapshot has an invalid dataset id')
    if not isinstance(manifest.get('trigger_word'), str):
        raise ValueError('training snapshot has an invalid trigger word')
    if manifest.get('kind') not in ('character', 'concept', 'style'):
        raise ValueError('training snapshot has an invalid dataset kind')
    entries = manifest.get('entries')
    if not isinstance(entries, list) or not entries:
        raise ValueError('training snapshot has no admitted images')
    raw_dir = root / 'raw'
    if raw_dir.is_symlink() or not raw_dir.is_dir():
        raise ValueError('training snapshot content directory is invalid')
    expected_registry = []
    seen_ids = set()
    for entry in entries:
        name = entry.get('stored_name') if isinstance(entry, dict) else None
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError('training snapshot contains an invalid filename')
        image_id = entry.get('image_id')
        if (isinstance(image_id, bool) or not isinstance(image_id, int)
                or image_id <= 0 or image_id in seen_ids):
            raise ValueError('training snapshot contains an invalid image id')
        seen_ids.add(image_id)
        caption = entry.get('caption')
        caption_hash = entry.get('caption_sha256')
        content_hash = entry.get('content_sha256')
        if (not isinstance(caption, str) or _caption_hash(caption) != caption_hash
                or not isinstance(content_hash, str) or len(content_hash) != 64):
            raise ValueError(f'training snapshot metadata check failed: {name}')
        path = raw_dir / name
        if (path.is_symlink() or not path.is_file() or _sha256(path) != content_hash):
            raise ValueError(f'training snapshot content check failed: {name}')
        expected_registry.append([image_id, caption_hash, content_hash])
    if manifest.get('registry_manifest') != expected_registry:
        raise ValueError('training snapshot registry manifest is inconsistent')
    return manifest


def entry_path(snapshot_dir, entry) -> Path:
    return Path(snapshot_dir) / 'raw' / entry['stored_name']
