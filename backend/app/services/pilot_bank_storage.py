"""Contained, private local bank storage with atomic optimistic revisions.

A revision is published by an exclusive hard link after fsync. Two writers
starting from the same version cannot overwrite one another. There is no lock
file to leave stale after a crash; unreferenced staging files are never served.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import tempfile
from pathlib import Path

from ..domain_errors import DomainValidationError
from . import face_dataset_service as fds

MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
FILE_LIMITS = {'image': 64 * 1024 * 1024, 'video': 256 * 1024 * 1024,
               'weights': MAX_FILE_BYTES, 'config': 16 * 1024 * 1024}
MAX_RECORD_BYTES = 4 * 1024 * 1024
ID = re.compile(r'^[a-f0-9]{32}$')
REVISION = re.compile(r'^avatar_export_[a-f0-9]{32}$')


class BankError(DomainValidationError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status
        self.status_code = status


def digest(data):
    return hashlib.sha256(data).hexdigest()


def contained(root, relative, *, file=False):
    root = Path(os.path.abspath(root))
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or ':' in relative or any(ord(c) < 32 for c in relative)):
        raise BankError('Unsafe bank path')
    parts = Path(relative).parts
    if Path(relative).is_absolute() or '..' in parts or '.' in parts:
        raise BankError('Unsafe bank path')
    # Check root as well, trusting only host aliases above the dataset root.
    current = root
    if current.is_symlink():
        raise BankError('Unsafe bank symlink')
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BankError('Unsafe bank symlink')
    if file and not current.is_file():
        raise BankError('Bank file not found', 404)
    return current


def dataset_root(user_id, dataset_id):
    dataset = fds.get_dataset(user_id, dataset_id)
    if dataset is None:
        raise BankError('Dataset not found', 404)
    if (dataset.kind or 'character') != 'character':
        raise BankError('Person bank requires a character dataset')
    root = Path(os.path.abspath(fds._dataset_dir(dataset_id)))
    if root.is_symlink():
        raise BankError('Unsafe dataset symlink')
    return root


def root_for(user_id, dataset_id):
    return contained(dataset_root(user_id, dataset_id), 'pilot_bank')


def mkdir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise BankError('Unsafe bank symlink')
    os.chmod(path, 0o700)


def read_bytes(root, relative, limit=MAX_FILE_BYTES):
    path = contained(root, relative, file=True)
    # Reject leaf symlinks atomically as well as all existing parents above.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise BankError('Bank file exceeds the local size limit')
    return data


def read_json(root, relative):
    try:
        data = json.loads(read_bytes(root, relative, MAX_RECORD_BYTES))
    except (UnicodeError, json.JSONDecodeError):
        raise BankError('Invalid bank record') from None
    if not isinstance(data, dict):
        raise BankError('Invalid bank record')
    return data


def state(root):
    revisions = contained(root, 'records')
    if not revisions.exists():
        return {'schema_version': 1, 'version': 0, 'attempts': []}
    names = [p.name for p in revisions.iterdir() if re.fullmatch(r'[0-9]{10}\.json', p.name)]
    if not names:
        return {'schema_version': 1, 'version': 0, 'attempts': []}
    latest = max(names)
    result = read_json(root, f'records/{latest}')
    if result.get('version') != int(latest[:10]):
        raise BankError('Invalid bank revision')
    return result


def version_check(record, version):
    if type(version) is not int or version != record['version']:
        raise BankError('Bank changed; reload before saving', 409)


def publish(root, record, version):
    version_check(state(root), version)
    mkdir(root)
    records = contained(root, 'records')
    mkdir(records)
    record['version'] = version + 1
    data = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    if len(data) > MAX_RECORD_BYTES:
        raise BankError('Bank record size limit reached')
    temporary = contained(root, f'records/.{uuid.uuid4().hex}.tmp')
    target = contained(root, f'records/{version + 1:010d}.json')
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            raise BankError('Bank changed; reload before saving', 409) from None
        if os.name != 'nt':
            directory_fd = os.open(records, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return record


def write_upload(root, stream, limit=MAX_FILE_BYTES):
    mkdir(root)
    folder = contained(root, 'files')
    mkdir(folder)
    file_id = uuid.uuid4().hex
    path = contained(root, f'files/{file_id}')
    size = 0
    hasher = hashlib.sha256()
    try:
        with path.open('xb') as dest:
            os.chmod(path, 0o600)
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise BankError('File exceeds the local size limit')
                dest.write(chunk)
                hasher.update(chunk)
            dest.flush()
            os.fsync(dest.fileno())
        if size == 0:
            raise BankError('Empty file cannot be imported')
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return file_id, path, hasher.hexdigest(), size


def checked_stream(root, output):
    if not ID.fullmatch(output.get('id', '')):
        raise BankError('Invalid bank file identifier')
    return verified_stream(root, f"files/{output['id']}", output['sha256'], output['size'])


def verified_stream(root, relative, expected_sha256, expected_size=None, limit=MAX_FILE_BYTES):
    path = contained(root, relative, file=True)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    stream = os.fdopen(fd, 'rb')
    snapshot = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
    hasher = hashlib.sha256()
    size = 0
    try:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise BankError('Bank file exceeds local size limit')
            hasher.update(chunk)
            snapshot.write(chunk)
        if hasher.hexdigest() != expected_sha256 or (expected_size is not None and size != expected_size):
            raise BankError('Bank file changed; integrity check failed', 409)
        snapshot.seek(0)
        stream.close()
        return snapshot
    except BaseException:
        stream.close()
        snapshot.close()
        raise


def hash_file(root, relative, limit=4 * MAX_FILE_BYTES):
    path = contained(root, relative, file=True)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        hasher = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise BankError('Export file exceeds local size limit')
            hasher.update(chunk)
    return hasher.hexdigest()


def archive_export_file(archive, root, relative, expected, name):
    path = contained(root, relative, file=True)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as source, archive.open(name, 'w', force_zip64=True) as target:
        hasher = hashlib.sha256()
        size = 0
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > 4 * MAX_FILE_BYTES:
                raise BankError('Export file exceeds local size limit')
            hasher.update(chunk)
            target.write(chunk)
        if hasher.hexdigest() != expected:
            raise BankError('Pinned export file changed during backup', 409)
