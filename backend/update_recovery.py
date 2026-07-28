"""Standalone recovery bootstrap for interrupted source-checkout updates.

Before an update mutates the checkout this file is copied into the private data
directory. Launchers execute that copy before importing any potentially partial
new application code, so recovery does not depend on the state of ``run.py``.
Only the Python standard library is used here intentionally.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class RecoveryError(RuntimeError):
    pass


class AlreadyRunning(RecoveryError):
    pass


@contextmanager
def _bootstrap_lock(data_dir: Path):
    """Use the same one-byte lock as process_lock.py without importing checkout
    code. A second launcher must not roll back an update under a live server."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "server.lock"
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError) as exc:
        handle.close()
        raise AlreadyRunning("another server is already using this data directory") from exc
    try:
        yield
    finally:
        handle.close()


def _canonical(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value).strip()).lower()


def _run(command, *, cwd: Path, timeout: int = 900):
    return subprocess.run(command, cwd=str(cwd), capture_output=True, text=True,
                          timeout=timeout)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _clear_journal(path: Path) -> bool:
    try:
        path.unlink()
        _fsync_directory(path.parent)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _restore_migration_snapshot(journal: dict) -> None:
    """Atomically restore the database image captured before new migrations."""
    metadata = journal.get("migration_database_snapshot")
    if not metadata:
        return
    try:
        database = Path(metadata["database"])
        snapshot = Path(metadata["snapshot"])
        expected_hash = str(metadata["sha256"])
        expected_size = int(metadata["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("migration database snapshot metadata is invalid") from exc
    try:
        if snapshot.stat().st_size != expected_size \
                or hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_hash:
            raise RecoveryError("migration database snapshot verification failed")
        with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RecoveryError("migration database snapshot integrity check failed")
        temporary = database.with_suffix(database.suffix + ".rollback.tmp")
        with snapshot.open("rb") as incoming, temporary.open("wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        for suffix in ("-wal", "-shm"):
            Path(f"{database}{suffix}").unlink(missing_ok=True)
        temporary.replace(database)
        _fsync_directory(database.parent)
    except (OSError, sqlite3.Error) as exc:
        raise RecoveryError(f"migration database restore failed: {exc}") from exc


def _updater_owned_dirty_state(root: Path, journal: dict, status_text: str) -> bool:
    """Recognize checkout materialization containing only recorded git blobs.

    Arbitrary content remains protected. This permits recovery when git was
    interrupted after writing some old/new blobs but before updating HEAD.
    """
    changed = set(journal.get("changed_files") or [])
    revisions = [str(journal.get("before") or ""), str(journal.get("target") or "")]
    for line in status_text.splitlines():
        if len(line) < 4 or line.startswith("??"):
            return False
        raw_name = line[3:]
        if " -> " in raw_name:
            raw_name = raw_name.rsplit(" -> ", 1)[1]
        name = raw_name.strip().strip('"')
        if name not in changed:
            return False
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            return False
        allowed: set[str | None] = set()
        for revision in revisions:
            blob = _run(["git", "-C", str(root), "rev-parse", f"{revision}:{name}"],
                        cwd=root, timeout=120)
            allowed.add((blob.stdout or "").strip() if blob.returncode == 0 else None)
        worktree_hash = None
        if path.is_file():
            hashed = _run(["git", "-C", str(root), "hash-object", "--", name],
                          cwd=root, timeout=120)
            if hashed.returncode != 0:
                return False
            worktree_hash = (hashed.stdout or "").strip()
        if worktree_hash not in allowed:
            return False
        if line[0] != " ":
            indexed = _run(["git", "-C", str(root), "ls-files", "-s", "--", name],
                           cwd=root, timeout=120)
            if indexed.returncode != 0:
                return False
            fields = (indexed.stdout or "").split()
            index_hash = fields[1] if len(fields) >= 2 else None
            if index_hash not in allowed:
                return False
    return True


def _installed_packages(python: str, root: Path) -> dict[str, str]:
    code = (
        "import importlib.metadata,json,re; "
        "canon=lambda s:re.sub(r'[-_.]+','-',str(s).strip()).lower(); "
        "print(json.dumps({canon(d.metadata.get('Name')):d.version "
        "for d in importlib.metadata.distributions() if d.metadata.get('Name')}))"
    )
    result = _run([python, "-c", code], cwd=root, timeout=180)
    if result.returncode != 0:
        raise RecoveryError(
            (result.stderr or result.stdout or "could not inspect Python packages").strip())
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RecoveryError("Python package inventory is invalid")
    return {_canonical(name): str(version) for name, version in payload.items()}


def _restore_python(root: Path, python: str, snapshot: dict) -> None:
    frozen = snapshot.get("freeze") if isinstance(snapshot, dict) else None
    expected = snapshot.get("packages") if isinstance(snapshot, dict) else None
    if not isinstance(frozen, list) or not isinstance(expected, dict):
        raise RecoveryError("Python environment snapshot is invalid")
    descriptor, raw_path = tempfile.mkstemp(prefix="lds-pip-recovery-", suffix=".txt")
    requirements = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(str(line) for line in frozen))
            handle.write("\n")
        result = _run(
            [python, "-m", "pip", "install", "-q", "-r", str(requirements)],
            cwd=root,
        )
    finally:
        try:
            requirements.unlink()
        except OSError:
            pass
    if result.returncode != 0:
        raise RecoveryError(
            (result.stderr or result.stdout or "Python dependency restore failed").strip())
    current = _installed_packages(python, root)
    expected_names = {_canonical(name) for name in expected}
    extras = sorted(name for name in current if name not in expected_names)
    if extras:
        result = _run([python, "-m", "pip", "uninstall", "-y", *extras], cwd=root)
        if result.returncode != 0:
            raise RecoveryError(
                (result.stderr or result.stdout or "could not remove added packages").strip())
    final = _installed_packages(python, root)
    normalized_expected = {_canonical(name): str(version)
                           for name, version in expected.items()}
    if final != normalized_expected:
        raise RecoveryError("Python dependency rollback did not restore the exact snapshot")


def _legacy_restore_python(root: Path, python: str, changed_files: list[str]) -> None:
    requirements = root / "backend" / "requirements.txt"
    command = [python, "-m", "pip", "install", "-q"]
    if "pyproject.toml" in changed_files:
        command.extend(["-e", str(root)])
    command.extend(["-r", str(requirements)])
    result = _run(command, cwd=root)
    if result.returncode != 0:
        raise RecoveryError(
            (result.stderr or result.stdout or "Python dependency restore failed").strip())


def _restore_frontend(root: Path) -> None:
    package = root / "frontend" / "package.json"
    manager = json.loads(package.read_text(encoding="utf-8")).get("packageManager", "")
    version = manager.split("@", 1)[1] if manager.startswith("pnpm@") else ""
    corepack = shutil.which("corepack")
    pnpm = shutil.which("pnpm")
    if corepack and version:
        command = [corepack, f"pnpm@{version}"]
    elif pnpm:
        command = [pnpm]
    else:
        raise RecoveryError("pnpm/Corepack is unavailable for dependency restore")
    result = _run([*command, "--dir", "frontend", "install", "--frozen-lockfile"],
                  cwd=root)
    if result.returncode != 0:
        raise RecoveryError(
            (result.stderr or result.stdout or "frontend dependency restore failed").strip())


def recover(repo_root: Path, data_dir: Path, *, python: str | None = None,
            restart_nonce: str | None = None) -> bool:
    """Restore an unfinished transaction. Returns whether recovery was needed."""
    root = Path(repo_root).resolve()
    data = Path(data_dir).resolve()
    journal_path = data / "update-transaction.json"
    if not journal_path.is_file():
        return False
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    before = str(journal.get("before") or "")
    expected_root = Path(journal.get("root") or "").resolve()
    if journal.get("state") == "committed" and expected_root == root:
        # Retain the exact-nonce receipt for every readiness observer. A later
        # update replaces it when the next prepared transaction is published.
        return False
    if (journal.get('state') == 'awaiting_restart'
            and expected_root == root
            and restart_nonce
            and restart_nonce == journal.get('restart_nonce')):
        # This is the exact replacement process being tested. Leave the journal
        # armed until /api/health/ready acknowledges it; every other process
        # (missing/wrong/stale nonce) falls through to rollback below.
        return False
    if expected_root != root or not re.fullmatch(r"[0-9a-fA-F]{7,64}", before):
        raise RecoveryError("journal target is invalid")
    changed_files = journal.get("changed_files") or []
    if not isinstance(changed_files, list) or not all(
            isinstance(name, str) for name in changed_files):
        raise RecoveryError("journal changed-file list is invalid")
    git = shutil.which("git")
    if not git:
        raise RecoveryError("git is unavailable")
    status = _run([git, "-C", str(root), "status", "--porcelain",
                   "--untracked-files=normal"], cwd=root, timeout=120)
    if status.returncode != 0:
        raise RecoveryError(
            (status.stderr or status.stdout or "git status failed").strip())
    if (status.stdout or "").strip() and not _updater_owned_dirty_state(
            root, journal, status.stdout):
        raise RecoveryError(
            "working tree changed during the interrupted update; automatic reset "
            "was refused to protect local work")
    reset = _run([git, "-C", str(root), "reset", "--hard", before],
                 cwd=root, timeout=120)
    if reset.returncode != 0:
        raise RecoveryError((reset.stderr or reset.stdout or "git reset failed").strip())
    # Restore the old schema before dependency cleanup or journal completion.
    # On failure the journal and verified snapshot remain available for retry.
    _restore_migration_snapshot(journal)
    interrupted_state = str(journal.get("state") or "")
    if interrupted_state in {
            "installing_dependencies", "verifying", "rolling_back",
            "rollback_blocked", "rollback_failed"}:
        python_changed = any(
            name == "pyproject.toml" or name.startswith("backend/requirements")
            for name in changed_files)
        if python_changed:
            snapshot = journal.get("python_environment_before")
            if snapshot:
                _restore_python(root, python or sys.executable, snapshot)
            else:
                _legacy_restore_python(root, python or sys.executable, changed_files)
        if any(name in ("frontend/package.json", "frontend/pnpm-lock.yaml")
               for name in changed_files):
            _restore_frontend(root)
    metadata = journal.get("migration_database_snapshot")
    if metadata:
        try:
            Path(metadata["snapshot"]).unlink(missing_ok=True)
        except (KeyError, OSError, TypeError) as exc:
            raise RecoveryError("could not clean restored migration snapshot") from exc
    if not _clear_journal(journal_path):
        print("[LDS] recovery completed; journal cleanup will be retried", flush=True)
    print(f"[LDS] recovered interrupted update; restored {before[:8]}", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--restart-nonce")
    args = parser.parse_args(argv)
    try:
        with _bootstrap_lock(Path(args.data_dir)):
            recover(Path(args.root), Path(args.data_dir),
                    restart_nonce=args.restart_nonce)
        return 0
    except AlreadyRunning as exc:
        print(f"[LDS] {exc}", file=sys.stderr, flush=True)
        return 73
    except Exception as exc:
        print(f"[LDS] interrupted update recovery failed: {exc}",
              file=sys.stderr, flush=True)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
