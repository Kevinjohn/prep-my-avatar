"""Single source of truth and comparison helpers for the application CalVer.

Application releases use ``YYYY.MM.DD.N`` and Git tags use ``vYYYY.MM.DD.N``.
``N`` starts at 1 and increments for another release on the same calendar day.
The portable bundle picks this value up automatically because ``backend/`` is
copied verbatim into it.

The repository's prototype Python package has its own SemVer in ``pyproject.toml``;
that package version is intentionally independent from the application release.
"""
from __future__ import annotations

from datetime import date


APP_VERSION = '2026.07.17.1'


def calver_key(value: str) -> tuple[int, int, int, int]:
    """Parse ``[v]YYYY.MM.DD[.N]`` into a numerically comparable tuple.

    Three-part tags from older releases remain readable and sort as release zero
    for that date. Numeric comparison avoids the classic lexical mistake where
    release ``.10`` sorts below ``.9``.
    """
    raw = str(value or '').strip().lstrip('vV')
    parts = raw.split('.')
    if len(parts) not in (3, 4) or any(not part.isdigit() for part in parts):
        raise ValueError(f'invalid CalVer: {value!r}')
    if len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError(f'invalid CalVer: {value!r}')
    year, month, day = (int(part) for part in parts[:3])
    date(year, month, day)  # reject impossible calendar dates
    release = int(parts[3]) if len(parts) == 4 else 0
    if release < 0:
        raise ValueError(f'invalid CalVer: {value!r}')
    return year, month, day, release


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    """Return False for malformed release tags instead of breaking update checks."""
    try:
        return calver_key(candidate) > calver_key(current)
    except (TypeError, ValueError):
        return False
