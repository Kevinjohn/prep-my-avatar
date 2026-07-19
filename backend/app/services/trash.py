"""App-wide trash: NOTHING the app deletes is destroyed directly — files and
folders are MOVED into data/trash/<timestamp>_<context>/ so a wrong click on a
1 GB checkpoint is recoverable. Settings shows the trash size and an
'Empty trash' button (the only place bytes actually die).

Cross-drive moves (ComfyUI on another drive) degrade to copy+delete via
shutil.move — slower for GB files but deletes are rare."""
from __future__ import annotations

import logging
import os
import shutil
import json
import re
import threading
from functools import wraps
from datetime import datetime
from pathlib import Path

from .. import config as cfg

logger = logging.getLogger(__name__)

_META_NAME = '.trash.json'
_ENTRY_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_ENTRY_CREATE_LOCK = threading.Lock()
_TRASH_TRANSACTION_LOCK = threading.RLock()


def serialized_transaction(function):
    """Keep Empty Trash out of a multi-step file/database transaction.

    Application-specific deletes use this decorator around their filesystem
    move plus database commit/rollback. The trash primitives use it too, so a
    concurrent Empty request cannot consume an entry while it is being created,
    restored, or rolled back.
    """
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _TRASH_TRANSACTION_LOCK:
            return function(*args, **kwargs)
    return wrapped


def trash_root() -> Path:
    root = cfg._data_dir() / 'trash'
    root.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        try:
            root.chmod(0o700)
        except OSError:
            pass
    return root


def _new_entry(context='', metadata=None) -> tuple[Path, dict]:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    safe_ctx = ''.join(ch if ch.isalnum() or ch in '-_' else '_'
                       for ch in str(context))[:60]
    base = f'{stamp}_{safe_ctx}' if safe_ctx else stamp
    with _ENTRY_CREATE_LOCK:
        dest_dir = trash_root() / base
        n = 1
        while dest_dir.exists():
            n += 1
            dest_dir = trash_root() / f'{base}_{n}'
        dest_dir.mkdir(parents=True, mode=0o700)
    if os.name != 'nt':
        try:
            dest_dir.chmod(0o700)
        except OSError:
            pass
    meta = {
        'version': 1,
        'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'context': str(context or ''),
        'kind': 'files',
        'files': [],
    }
    if isinstance(metadata, dict):
        meta.update(metadata)
    return dest_dir, meta


def _write_metadata(entry: Path, metadata: dict) -> None:
    tmp = entry / f'{_META_NAME}.tmp'
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(entry / _META_NAME)


@serialized_transaction
def send_paths_to_trash(paths, context='', metadata=None) -> dict:
    """Move several files/folders into one recoverable trash entry.

    Every target is validated before the first move. If a later move fails, the
    already moved targets are rolled back to their original locations.
    """
    sources = [Path(path) for path in paths]
    if not sources or any(not source.exists() for source in sources):
        missing = next((source for source in sources if not source.exists()), None)
        raise FileNotFoundError(str(missing or 'no trash targets'))
    if any(source.is_symlink() for source in sources):
        raise ValueError('symbolic links cannot be moved into app trash')
    resolved = [source.resolve() for source in sources]
    if len(set(resolved)) != len(resolved):
        raise ValueError('duplicate trash target')
    for index, source in enumerate(resolved):
        if any(source.is_relative_to(other) or other.is_relative_to(source)
               for other in resolved[index + 1:]):
            raise ValueError('trash targets cannot contain one another')
    entry, meta = _new_entry(context, metadata)
    moved = []
    try:
        used = set()
        for source in sources:
            name = source.name
            stem, suffix = source.stem, source.suffix
            n = 1
            while name in used or (entry / name).exists():
                n += 1
                name = f'{stem}_{n}{suffix}'
            used.add(name)
            destination = entry / name
            shutil.move(str(source), str(destination))
            moved.append((source, destination))
            meta['files'].append({
                'stored_name': name,
                'original_path': str(source.resolve(strict=False)),
                'is_dir': destination.is_dir(),
            })
        _write_metadata(entry, meta)
    except Exception:
        for source, destination in reversed(moved):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            except OSError:
                logger.exception('could not roll back failed trash move %s', source)
        shutil.rmtree(entry, ignore_errors=True)
        raise
    logger.info('trashed %d path(s) -> %s', len(moved), entry)
    return {'id': entry.name, 'path': str(entry), 'files': meta['files']}


@serialized_transaction
def send_to_trash(path, context='', metadata=None) -> str:
    """Move a file or folder into the trash; returns its new location.
    Raises on a missing source (callers whitelist first)."""
    result = send_paths_to_trash([path], context=context, metadata=metadata)
    return str(Path(result['path']) / result['files'][0]['stored_name'])


@serialized_transaction
def store_bytes(name, data: bytes, context='', metadata=None) -> dict:
    """Create a custom recoverable entry from bytes, such as a dataset backup."""
    safe_name = Path(str(name)).name
    if not safe_name or safe_name in {'.', '..'}:
        raise ValueError('invalid trash filename')
    entry, meta = _new_entry(context, metadata)
    destination = entry / safe_name
    try:
        descriptor = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        meta['files'].append({'stored_name': safe_name, 'original_path': None,
                              'is_dir': False})
        _write_metadata(entry, meta)
    except Exception:
        shutil.rmtree(entry, ignore_errors=True)
        raise
    return {'id': entry.name, 'path': str(entry), 'files': meta['files']}


def _entry_path(entry_id) -> Path:
    value = str(entry_id or '')
    if not _ENTRY_RE.fullmatch(value):
        raise ValueError('invalid trash entry')
    entry = trash_root() / value
    root = trash_root().resolve()
    if (entry.is_symlink() or not entry.is_dir()
            or entry.resolve().parent != root):
        raise FileNotFoundError(value)
    return entry


def entry_metadata(entry_id) -> dict:
    entry = _entry_path(entry_id)
    try:
        metadata = json.loads((entry / _META_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('trash entry is not restorable')
    if not isinstance(metadata, dict) or not isinstance(metadata.get('files'), list):
        raise ValueError('trash entry metadata is invalid')
    return metadata


def read_entry_file(entry_id, stored_name) -> bytes:
    with open_entry_file(entry_id, stored_name) as handle:
        return handle.read()


def open_entry_file(entry_id, stored_name):
    """Open one validated, non-symlink entry file for bounded-memory consumers."""
    entry = _entry_path(entry_id)
    name = Path(str(stored_name)).name
    if name != stored_name:
        raise ValueError('invalid trash filename')
    path = entry / name
    if (path.is_symlink() or not path.is_file()
            or path.resolve().parent != entry.resolve()):
        raise FileNotFoundError(name)
    return path.open('rb')


@serialized_transaction
def restore_entry(entry_id, *, consume=True) -> dict:
    """Restore an ordinary file entry to its recorded original locations."""
    entry = _entry_path(entry_id)
    meta = entry_metadata(entry_id)
    files = meta['files']
    if not files or any(not item.get('original_path') for item in files):
        raise ValueError('trash entry needs an application-specific restore')
    pairs = []
    for item in files:
        stored_name = item.get('stored_name')
        if not isinstance(stored_name, str) or Path(stored_name).name != stored_name:
            raise ValueError('trash entry metadata is invalid')
        source = entry / stored_name
        destination = Path(item['original_path'])
        if (source.is_symlink() or not source.exists()
                or source.resolve().parent != entry.resolve()):
            raise FileNotFoundError(stored_name)
        if destination.exists():
            raise FileExistsError(f'restore target already exists: {destination}')
        pairs.append((source, destination))
    restored = []
    try:
        for source, destination in pairs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            restored.append((source, destination))
    except Exception:
        for source, destination in reversed(restored):
            try:
                shutil.move(str(destination), str(source))
            except OSError:
                logger.exception('could not roll back failed trash restore %s', destination)
        raise
    if consume:
        try:
            remove_entry(entry_id)
        except OSError:
            # The user-visible operation already succeeded.  Do not turn a
            # cleanup failure into a false restore failure; a later Empty
            # Trash pass can consume the now-empty entry.
            logger.exception('restored entry but could not remove %s', entry)
    return {'id': str(entry_id), 'restored': len(restored), 'metadata': meta}


@serialized_transaction
def rollback_restored_entry(entry_id, metadata) -> None:
    """Move a non-consumed restore back into its original trash entry."""
    entry = _entry_path(entry_id)
    restored_back = []
    try:
        for item in reversed(metadata.get('files') or []):
            stored_name = item.get('stored_name')
            original_path = item.get('original_path')
            if (not isinstance(stored_name, str)
                    or Path(stored_name).name != stored_name or not original_path):
                raise ValueError('trash entry metadata is invalid')
            source = Path(original_path)
            destination = entry / stored_name
            if destination.exists():
                continue
            if not source.exists():
                raise FileNotFoundError(str(source))
            shutil.move(str(source), str(destination))
            restored_back.append((source, destination))
    except Exception:
        # Re-establish the restored state if re-trashing only partly succeeded.
        for source, destination in reversed(restored_back):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            except OSError:
                logger.exception('could not roll back failed re-trash %s', source)
        raise


@serialized_transaction
def remove_entry(entry_id) -> None:
    """Consume an entry after a successful restore.

    If directory cleanup fails after the payload already moved out, make the
    surviving metadata explicitly non-restorable. It can then be retried by
    Empty Trash without presenting a broken Restore action.
    """
    entry = _entry_path(entry_id)
    try:
        shutil.rmtree(entry)
    except OSError:
        if entry.exists() and entry.is_dir():
            try:
                try:
                    metadata = entry_metadata(entry_id)
                except (OSError, ValueError):
                    metadata = {'version': 1, 'files': []}
                metadata.update({
                    'kind': 'restored_cleanup_pending',
                    'restorable': False,
                    'files': [],
                    'label': 'Restored item (cleanup pending)',
                })
                _write_metadata(entry, metadata)
            except OSError:
                logger.exception('could not mark consumed trash entry %s', entry_id)
        raise


@serialized_transaction
def list_entries() -> list[dict]:
    result = []
    for entry in sorted(trash_root().iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        if entry.is_symlink():
            continue
        try:
            meta = entry_metadata(entry.name)
        except (OSError, ValueError):
            meta = {'context': entry.name, 'kind': 'legacy', 'files': []}
        size = 0
        for dirpath, _dirs, files in os.walk(entry):
            for filename in files:
                if filename == _META_NAME:
                    continue
                try:
                    size += os.path.getsize(os.path.join(dirpath, filename))
                except OSError:
                    pass
        result.append({
            'id': entry.name,
            'created_at': meta.get('created_at'),
            'context': meta.get('context') or entry.name,
            'kind': meta.get('kind') or 'files',
            'size_bytes': size,
            'restorable': bool(meta.get('files')) and meta.get('restorable') is not False,
        })
    return result


@serialized_transaction
def trash_size() -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(trash_root()):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for filename in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, filename))
            except OSError:
                pass
    return total


@serialized_transaction
def empty_trash(*, purge_record=None) -> dict:
    """Permanently consume entries and report bytes actually removed.

    ``purge_record`` is the domain hook that removes database tombstones before
    their last recoverable bytes disappear.  If filesystem deletion then fails,
    the leftover entry is explicitly marked non-restorable rather than lying to
    the user about a record that no longer exists.
    """
    root = trash_root()
    freed = 0
    removed = 0
    failed = 0
    for entry in list(root.iterdir()):
        size = _path_size(entry)
        try:
            metadata = None
            if entry.is_dir():
                try:
                    metadata = entry_metadata(entry.name)
                except (OSError, ValueError):
                    metadata = None
            if purge_record is not None and metadata is not None:
                purge_record(metadata, entry.name)
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed += 1
            freed += size
        except Exception as e:
            failed += 1
            logger.warning('empty_trash: could not remove %s: %s', entry, e)
            if entry.is_dir() and entry.exists():
                try:
                    meta = metadata or {'version': 1, 'files': []}
                    meta.update({'kind': 'purged_bytes', 'restorable': False})
                    _write_metadata(entry, meta)
                except OSError:
                    pass
    return {'removed': removed, 'failed': failed, 'freed_bytes': freed}
