"""Cross-platform bootstrap lock for one server per data directory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class AlreadyRunning(RuntimeError):
    """Raised when another server owns the data directory."""


def acquire(data_dir: Path) -> BinaryIO:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / 'server.lock'
    handle = path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError) as exc:
        handle.close()
        raise AlreadyRunning(
            f'another Prep My Avatar server is already using {data_dir}; '
            'stop it before starting a second process',
        ) from exc

    handle.seek(0)
    handle.truncate()
    handle.write(f'pid={os.getpid()}\n'.encode('ascii'))
    handle.flush()
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return handle
