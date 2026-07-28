"""Persistent source-checkout launcher installed in the private data directory.

This file uses only the standard library. Install it while the checkout is
healthy, then invoke the private copy so interrupted updates can repair even a
missing or syntactically invalid ``backend/run.py`` before it is executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BOOT_BUNDLE_VERSION = 1


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.tmp')
    with source.open('rb') as incoming, temporary.open('wb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    temporary.replace(target)


def install(root: Path, data_dir: Path) -> Path:
    """Install both immutable boot files before any checkout mutation."""
    source_dir = root / 'backend'
    launcher = data_dir / 'source-launcher.py'
    _atomic_copy(source_dir / 'update_recovery.py', data_dir / 'update-recovery.py')
    _atomic_copy(source_dir / 'source_launcher.py', launcher)
    manifest = {
        'version': BOOT_BUNDLE_VERSION,
        'files': {
            name: hashlib.sha256((data_dir / name).read_bytes()).hexdigest()
            for name in ('update-recovery.py', 'source-launcher.py')},
    }
    manifest_path = data_dir / 'boot-bundle.json'
    temporary = manifest_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
    temporary.replace(manifest_path)
    return launcher


def launch(root: Path, data_dir: Path, python: str) -> int:
    recovery = data_dir / 'update-recovery.py'
    manifest_path = data_dir / 'boot-bundle.json'
    if not recovery.is_file() or not manifest_path.is_file():
        raise RuntimeError(
            'private boot bundle is incomplete; reinstall the source launcher')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('version') != BOOT_BUNDLE_VERSION:
        raise RuntimeError('private boot bundle version is incompatible')
    files = manifest.get('files') or {}
    if set(files) != {'update-recovery.py', 'source-launcher.py'}:
        raise RuntimeError('private boot bundle manifest is incomplete')
    for name, expected in files.items():
        actual = hashlib.sha256((data_dir / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f'private boot bundle is corrupt: {name}')
    recovery_command = [
        python, str(recovery), '--root', str(root), '--data-dir', str(data_dir)]
    restart_nonce = os.environ.get('LDS_RESTART_NONCE')
    if restart_nonce:
        recovery_command.extend(['--restart-nonce', restart_nonce])
    recovered = subprocess.run(recovery_command, cwd=str(root), env=dict(os.environ))
    if recovered.returncode != 0:
        return recovered.returncode
    return subprocess.call([python, str(root / 'backend' / 'run.py')], cwd=str(root))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    data_dir = args.data_dir.resolve()
    if args.install:
        private = install(root, data_dir)
        print(private)
        return 0
    return launch(root, data_dir, sys.executable)


if __name__ == '__main__':
    raise SystemExit(main())
