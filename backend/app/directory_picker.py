"""Native directory selection for the local setup wizard.

A browser directory input cannot reveal an absolute host path. On macOS the
local server can safely ask Finder for one instead. Keep the supported purpose
list narrow so request data is never interpolated into AppleScript.
"""
from __future__ import annotations

import subprocess
import sys


class DirectoryPickerUnavailable(RuntimeError):
    """The host cannot provide the native directory dialog."""


_PROMPTS = {
    'aitoolkit': 'Choose the ai-toolkit folder',
}


def pick_directory(purpose: str) -> str | None:
    """Return the chosen absolute path, or ``None`` when the user cancels."""
    prompt = _PROMPTS.get(purpose)
    if prompt is None:
        raise ValueError(f'unknown directory purpose: {purpose}')
    if sys.platform != 'darwin':
        raise DirectoryPickerUnavailable(
            'The native folder chooser is currently available on macOS only.')

    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    try:
        result = subprocess.run(
            ['osascript', '-e', script], capture_output=True, text=True,
            timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DirectoryPickerUnavailable(
            'The macOS folder chooser could not be opened.') from exc

    if result.returncode == 0:
        return result.stdout.strip().rstrip('/')
    if 'User canceled' in result.stderr or '(-128)' in result.stderr:
        return None
    raise DirectoryPickerUnavailable(
        result.stderr.strip() or 'The macOS folder chooser failed.')
