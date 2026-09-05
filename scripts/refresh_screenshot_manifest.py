"""Refresh docs/screenshots/manifest.yml after a screenshot capture.

Recomputes, in place and without disturbing the file's layout (YAML anchors,
ordering, comments), the three things `validate_repository_contracts.py`
checks per record:

* ``sha256`` of every listed screenshot file;
* ``sha256`` of every ``relevant_sources`` path (text, UTF-8, same digest the
  validator uses);
* ``capture_revision`` for records whose screenshot bytes changed (defaults
  to the current ``git rev-parse HEAD``; override with ``--revision``).

Usage, from the repository root, after ``pnpm --dir frontend run capture:guide``::

    python scripts/refresh_screenshot_manifest.py
    python scripts/validate_repository_contracts.py
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/screenshots/manifest.yml"

_RECORD = re.compile(r"^  - path: (?P<path>\S+)\s*$")
_SOURCE = re.compile(r"^      - path: (?P<path>\S+)\s*$")
_SHA = re.compile(r"^(?P<indent>\s+)sha256: (?P<sha>[0-9a-f]{64})\s*$")
_REVISION = re.compile(r"^(?P<indent>\s+)capture_revision: (?P<sha>[0-9a-f]{40})\s*$")


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _head_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def refresh(text: str, revision: str) -> tuple[str, list[str]]:
    lines = text.splitlines(keepends=True)
    changes: list[str] = []
    # Walk the manifest line by line. The next `sha256:` after a screenshot
    # record belongs to the screenshot; the next one after a source entry
    # belongs to that source. `capture_revision` precedes the screenshot's
    # digest in each record, so its line index is remembered and rewritten
    # once the digest turns out to have changed.
    pending: tuple[str, Path, str] | None = None
    revision_index: int | None = None
    for index, line in enumerate(lines):
        record = _RECORD.match(line)
        if record:
            pending = ("screenshot", ROOT / "docs/screenshots" / record["path"], record["path"])
            revision_index = None
            continue
        source = _SOURCE.match(line)
        if source:
            pending = ("source", ROOT / source["path"], source["path"])
            continue
        revision_line = _REVISION.match(line)
        if revision_line:
            revision_index = index
            continue
        sha_line = _SHA.match(line)
        if not sha_line or pending is None:
            continue
        kind, path, label = pending
        pending = None
        if not path.is_file():
            changes.append(f"missing {kind}: {label}")
            continue
        digest = _file_digest(path) if kind == "screenshot" else _source_digest(path)
        if digest == sha_line["sha"]:
            continue
        lines[index] = f"{sha_line['indent']}sha256: {digest}\n"
        changes.append(f"updated {kind}: {label}")
        if kind == "screenshot" and revision_index is not None:
            indent = _REVISION.match(lines[revision_index])["indent"]
            lines[revision_index] = f"{indent}capture_revision: {revision}\n"
    return "".join(lines), changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--revision", help="capture revision to stamp on changed screenshots")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the manifest would change; write nothing")
    args = parser.parse_args()
    revision = args.revision or _head_revision()
    original = MANIFEST.read_text(encoding="utf-8")
    updated, changes = refresh(original, revision)
    for change in changes:
        print(change)
    if updated == original:
        print("manifest already current")
        return 0
    if args.check:
        print("manifest is stale", file=sys.stderr)
        return 1
    MANIFEST.write_text(updated, encoding="utf-8")
    print(f"manifest refreshed ({len(changes)} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
