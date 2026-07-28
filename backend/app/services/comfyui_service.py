"""Thin compatibility health wrappers for the canonical ComfyUI transport.

Prompt submission lives in :mod:`app.utils.comfyui`; this module retains only
the public readiness entry points used by that transport. Every call resolves
the current configured endpoint and uses the same bounded HTTP semantics.
"""
from __future__ import annotations

from urllib.parse import urljoin

import requests

from ..utils.comfyui import api_address

_HEALTH_TIMEOUT_SECONDS = 3


def _is_reachable() -> bool:
    try:
        response = requests.get(
            urljoin(api_address().rstrip('/') + '/', 'history'),
            timeout=_HEALTH_TIMEOUT_SECONDS,
        )
        return response.status_code in (200, 404)
    except requests.RequestException:
        return False


def ensure_comfyui_before_generation():
    if _is_reachable():
        return True, 'Running'
    return False, 'ComfyUI not running (Please start external supervisor)'


def check_comfyui_status():
    return {'running': _is_reachable(), 'pid': None}
