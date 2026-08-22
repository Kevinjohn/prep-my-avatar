"""Shared helpers for hashing files without loading them into memory."""
import hashlib
from pathlib import Path


_CHUNK_SIZE = 1024 * 1024


def sha256_file(path) -> str:
    """Return a file's SHA-256, streaming in fixed-size chunks.

    The fixed 1 MiB reads ensure a multi-gigabyte checkpoint never lands in
    memory.
    """
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()
