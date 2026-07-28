"""Converge one GitHub tag on one published release with one verified asset."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Callable


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _checked(result: subprocess.CompletedProcess[str], operation: str) -> str:
    if result.returncode:
        detail = (result.stderr or result.stdout or '').strip()
        raise RuntimeError(f'{operation} failed{f": {detail}" if detail else ""}')
    return result.stdout


def _view(tag: str, run: Runner) -> dict | None:
    result = run(['gh', 'release', 'view', tag, '--json', 'isDraft,assets'])
    if result.returncode:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('release view returned invalid JSON') from exc
    if not isinstance(payload, dict):
        raise RuntimeError('release view returned an invalid document')
    return payload


def reconcile_release(tag: str, asset: Path, *, run: Runner = _run) -> None:
    """Create/resume, replace, verify, and publish an idempotent release."""
    if not asset.is_file():
        raise FileNotFoundError(asset)
    release = _view(tag, run)
    if release is None:
        _checked(run([
            'gh', 'release', 'create', tag, '--draft',
            '--title', f'LoRA Dataset Studio {tag}', '--generate-notes',
        ]), f'create draft release {tag}')

    _checked(run(['gh', 'release', 'upload', tag, str(asset), '--clobber']),
             f'upload release asset for {tag}')
    release = _view(tag, run)
    if release is None:
        raise RuntimeError(f'release {tag} disappeared after upload')
    expected_size = asset.stat().st_size
    matching = [item for item in release.get('assets', [])
                if isinstance(item, dict) and item.get('name') == asset.name]
    if len(matching) != 1 or matching[0].get('size') != expected_size:
        raise RuntimeError('uploaded release asset is missing, duplicated, or has the wrong size')
    if release.get('isDraft'):
        _checked(run(['gh', 'release', 'edit', tag, '--draft=false']),
                 f'publish draft release {tag}')

    final = _view(tag, run)
    if final is None or final.get('isDraft'):
        raise RuntimeError(f'release {tag} did not converge to published state')
    final_assets = [item for item in final.get('assets', [])
                    if isinstance(item, dict) and item.get('name') == asset.name]
    if len(final_assets) != 1 or final_assets[0].get('size') != expected_size:
        raise RuntimeError('published release asset failed final verification')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--asset', required=True, type=Path)
    args = parser.parse_args()
    reconcile_release(args.tag, args.asset)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
