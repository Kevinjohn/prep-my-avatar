"""Standalone recovery bootstrap for interrupted source-checkout updates.

Before an update mutates the checkout this file is copied into the private data
directory. Launchers execute that copy before importing any potentially partial
new application code, so recovery does not depend on the state of ``run.py``.
Only the Python standard library is used here intentionally.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def recover(repo_root: Path, data_dir: Path, *, python: str | None = None) -> bool:
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
        journal_path.unlink()
        return True
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
    if (status.stdout or "").strip():
        raise RecoveryError(
            "working tree changed during the interrupted update; automatic reset "
            "was refused to protect local work")
    reset = _run([git, "-C", str(root), "reset", "--hard", before],
                 cwd=root, timeout=120)
    if reset.returncode != 0:
        raise RecoveryError((reset.stderr or reset.stdout or "git reset failed").strip())
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
    journal_path.unlink()
    print(f"[LDS] recovered interrupted update; restored {before[:8]}", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args(argv)
    try:
        with _bootstrap_lock(Path(args.data_dir)):
            recover(Path(args.root), Path(args.data_dir))
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
