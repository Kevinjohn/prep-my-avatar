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


def _make_private(directory: Path) -> None:
    """Take the umask back off a directory that must stay owner-only.

    ``mkdir(mode=0o700)`` is MASKED by the process umask, so a directory holding
    a user's deleted files can end up group- or world-readable. Best-effort: a
    filesystem that cannot represent POSIX modes must not fail a delete."""
    if os.name == 'nt':
        return
    try:
        directory.chmod(0o700)
    except OSError:
        pass


def trash_root() -> Path:
    root = cfg._data_dir() / 'trash'
    root.mkdir(parents=True, exist_ok=True)
    _make_private(root)
    return root


def _new_entry(context='', metadata=None) -> tuple[Path, dict]:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    safe_ctx = ''.join(ch if ch.isascii() and (ch.isalnum() or ch in '-_') else '_'
                       for ch in str(context))[:60]
    base = f'{stamp}_{safe_ctx}' if safe_ctx else stamp
    # Both callers are @serialized_transaction, so this lock is redundant TODAY.
    # It is kept because the exclusivity it provides is what makes the loop below
    # a claim rather than a guess: mkdir is the atomic step, and a future caller
    # that reaches _new_entry undecorated must not silently lose that.
    with _ENTRY_CREATE_LOCK:
        dest_dir = trash_root() / base
        n = 1
        while dest_dir.exists():
            n += 1
            dest_dir = trash_root() / f'{base}_{n}'
        dest_dir.mkdir(parents=True, mode=0o700)
    _make_private(dest_dir)
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


def _undo_moves(moves, *, what) -> list[tuple[Path, Path]]:
    """Move each ``(source, destination)`` pair back, newest first, best effort.

    Returns the pairs actually reversed. A SHORTER list than `moves` is the
    signal that the transaction is only partly unwound — the caller must then
    publish a recovery marker rather than report a clean failure. Every failure
    is swallowed and logged on purpose: the payload's only surviving copy sits at
    one end or the other of each move, so one unmovable file must not abandon the
    rest of the compensation."""
    undone = []
    for source, destination in reversed(moves):
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(source))
        except OSError:
            logger.exception('could not roll back failed %s: %s', what, source)
            continue
        undone.append((source, destination))
    return undone


def _mark_unrestorable(entry: Path, kind: str, *, metadata=None, **extra) -> None:
    """Publish an entry as explicitly non-restorable once its payload has gone.

    `_inventory` calls an entry restorable on TWO conditions — a non-empty
    ``files`` list and ``restorable`` not being False — so both writers of that
    verdict go through here and cannot drift into stating only half of it.
    Best-effort: the destructive step this annotates has already happened, and a
    failed marker must not turn a completed purge into an error."""
    payload = metadata if metadata is not None else {'version': 1, 'files': []}
    payload.update({'kind': kind, 'restorable': False, **extra})
    try:
        _write_metadata(entry, payload)
    except OSError:
        logger.exception('could not mark trash entry %s as non-restorable', entry)


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
    planned = []
    try:
        used = {_META_NAME, f'{_META_NAME}.tmp'}
        for source in sources:
            name = source.name
            stem, suffix = source.stem, source.suffix
            n = 1
            while name in used or (entry / name).exists():
                n += 1
                name = f'{stem}_{n}{suffix}'
            used.add(name)
            destination = entry / name
            item = {
                'stored_name': name,
                'original_path': str(source.resolve(strict=False)),
                'is_dir': source.is_dir(),
                'state': 'pending',
            }
            meta['files'].append(item)
            planned.append((source, destination, item))
        meta['transaction_state'] = 'moving'
        _write_metadata(entry, meta)
        for source, destination, item in planned:
            shutil.move(str(source), str(destination))
            moved.append((source, destination))
            item['state'] = 'moved'
            _write_metadata(entry, meta)
        meta['transaction_state'] = 'complete'
        _write_metadata(entry, meta)
    except BaseException:
        undone = _undo_moves(moved, what='trash move')
        reversed_sources = {source for source, _destination in undone}
        for planned_source, _planned_destination, item in planned:
            if planned_source in reversed_sources:
                item['state'] = 'rolled_back'
        if len(undone) != len(moved):
            meta['recovery_required'] = True
            meta['transaction_state'] = 'recovery_required'
            meta['error'] = 'A failed trash operation could not be fully rolled back'
            try:
                _write_metadata(entry, meta)
            except OSError:
                logger.exception('could not publish recovery metadata for %s', entry)
        else:
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
        undone = _undo_moves(restored, what='trash restore')
        if len(undone) < len(restored):
            # DBR-0011 (review 2): a partial unwind splits the payload between
            # trash and original locations. Annotate the entry so inventory can
            # surface the split instead of leaving a retry to silently skip
            # targets that already exist.
            try:
                meta['partially_restored'] = True
                _write_metadata(entry, meta)
            except OSError:
                logger.exception(
                    'could not record partial restore state on %s', entry)
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
        _undo_moves(restored_back, what='re-trash')
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
                metadata = entry_metadata(entry_id)
            except (OSError, ValueError):
                metadata = None
            _mark_unrestorable(entry, 'restored_cleanup_pending', metadata=metadata,
                               files=[], label='Restored item (cleanup pending)')
        raise


def _iter_file_sizes(path: Path):
    """Yield ``(filename, bytes)`` for every regular file under `path`.

    Files the OS refuses to stat are skipped, not raised: a racing delete must
    never fail a size report. Shared by the two callers so the WALK is one rule
    — the two TOTALS deliberately are not (see `_inventory`)."""
    for dirpath, _dirs, files in os.walk(path):
        for filename in files:
            try:
                yield filename, os.path.getsize(os.path.join(dirpath, filename))
            except OSError:
                continue


def _inventory() -> tuple[int, list[dict]]:
    result = []
    total = 0
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
        # Two numbers from one walk, and they are NOT the same number: `total` is
        # the bytes Empty Trash will actually free, `size` is what the user is
        # shown per entry and excludes our own journal.
        for filename, file_size in _iter_file_sizes(entry):
            total += file_size
            if filename != _META_NAME:
                size += file_size
        result.append({
            'id': entry.name,
            'created_at': meta.get('created_at'),
            'context': meta.get('context') or entry.name,
            'kind': meta.get('kind') or 'files',
            'size_bytes': size,
            'restorable': bool(meta.get('files')) and meta.get('restorable') is not False,
        })
    return total, result


@serialized_transaction
def inventory() -> tuple[int, list[dict]]:
    """Return aggregate bytes and entry rows from one filesystem walk."""
    return _inventory()


@serialized_transaction
def list_entries() -> list[dict]:
    return _inventory()[1]


@serialized_transaction
def trash_size() -> int:
    return _inventory()[0]


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    # Counts the entry's journal too — this is what a purge really frees.
    return sum(file_size for _filename, file_size in _iter_file_sizes(path))


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
                _mark_unrestorable(entry, 'purged_bytes', metadata=metadata)
    return {'removed': removed, 'failed': failed, 'freed_bytes': freed}
