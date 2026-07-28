"""Start the local Ollama server on demand — powers the Settings / Setup
"Start Ollama" button.

Whether Ollama is INSTALLED (binary on disk, server up or not) is detected
passively in capabilities (`_ollama_binary` / `probe_ollama_installed`). This
module owns the one thing that mutates the machine: LAUNCHING the server. It
spawns a DETACHED ``ollama serve`` that outlives this app (and an app restart),
then polls the configured URL until it answers (or a timeout), and reports
``{ok, reachable, ...}``.

GUARD-RAIL: nothing here may run from a passive probe. It is only ever reached
through an explicit user click on the Start button (POST /api/ollama/start), so
the app can never silently spawn a server behind the user's back.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from urllib.parse import urlparse

from .. import capabilities
from .. import config as cfg

logger = logging.getLogger(__name__)

_DEFAULT_URL = 'http://127.0.0.1:11434'
# How long to wait for a freshly-spawned server to answer before giving up. A
# cold ``ollama serve`` binds its port in well under this; the ceiling only bites
# a genuinely stuck launch (→ structured error + the stderr tail).
_READY_TIMEOUT = 15.0
_POLL_INTERVAL = 0.5
_start_lock = threading.Lock()


def _url() -> str:
    return (cfg.get('ollama.url') or _DEFAULT_URL).rstrip('/')


def _reachable(url) -> bool:
    """Does a server answer at `url`? Goes through capabilities._http_ok so the
    suite patches one seam and the real network is never hit in tests."""
    return capabilities._http_ok(f'{url}/api/tags')


def _spawn_detached(binary: str):
    """Spawn ``ollama serve`` fully detached with bounded output ownership."""
    environment = os.environ.copy()
    parsed = urlparse(_url())
    environment['OLLAMA_HOST'] = parsed.netloc
    # A detached lifetime log cannot be safely rotated by this process after it
    # exits. Use the bounded null sink instead of leaking anonymous temp files.
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True, env=environment)
    if os.name == 'nt':
        # DETACHED_PROCESS (0x8): no console, not tied to ours.
        # CREATE_NEW_PROCESS_GROUP (0x200): our termination / Ctrl-C can't cascade.
        # CREATE_NO_WINDOW (0x8000000): belt-and-braces, no console window flashes.
        kwargs['creationflags'] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kwargs['start_new_session'] = True     # POSIX: own session, survives us
    proc = subprocess.Popen([binary, 'serve'], **kwargs)
    return proc


def _stderr_tail(_proc) -> str:
    return ''


def start_ollama(*, wait_timeout: float = _READY_TIMEOUT,
                 poll_interval: float = _POLL_INTERVAL) -> dict:
    """Idempotently bring the local Ollama server up. Returns:
      already up           -> {ok:True,  reachable:True, already_running:True}
      started & answered   -> {ok:True,  reachable:True}
      not installed        -> {ok:False, reachable:False, error:...}
      launch failed        -> {ok:False, reachable:False, error:...}
      spawned, never ready -> {ok:False, reachable:False, error:..., stderr:...}
    Never raises."""
    # Serialize the reachability-check/spawn/readiness sequence. Concurrent
    # HTTP requests join the same startup attempt and re-check reachability
    # after the first caller publishes it.
    with _start_lock:
        return _start_ollama_locked(wait_timeout=wait_timeout, poll_interval=poll_interval)


def _start_ollama_locked(*, wait_timeout: float, poll_interval: float) -> dict:
    url = _url()
    # Idempotent no-op: a running server must never be double-spawned.
    if _reachable(url):
        return {'ok': True, 'reachable': True, 'already_running': True}
    if not _is_loopback_url(url):
        return {'ok': False, 'reachable': False,
                'error': f'Remote Ollama server cannot be started locally: {url}'}

    binary = capabilities._ollama_binary()
    if not binary:
        return {'ok': False, 'reachable': False,
                'error': 'Ollama is not installed (no binary on PATH or in the default '
                         'install location). Install it from https://ollama.com/download.'}
    try:
        proc = _spawn_detached(binary)
    except OSError as e:
        logger.warning('ollama start: launch failed: %s', e)
        return {'ok': False, 'reachable': False, 'error': f'could not launch Ollama: {e}'}

    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if _reachable(url):
            return {'ok': True, 'reachable': True}
        if proc.poll() is not None:
            # Exited before answering (port already bound by a broken instance,
            # missing runner, etc.) -> stop waiting and surface why.
            break
        time.sleep(poll_interval)

    # Final check closes the race between the last sleep and the deadline.
    if _reachable(url):
        return {'ok': True, 'reachable': True}
    out = {'ok': False, 'reachable': False,
           'error': f'Ollama did not become reachable within {int(wait_timeout)}s.'}
    tail = _stderr_tail(proc)
    if tail:
        out['stderr'] = tail
    return out


def _is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').lower()
    return host == 'localhost' or host == '::1' or host.startswith('127.')


def ensure_captioning_ready() -> dict:
    """Start a stopped local Ollama on demand and verify the configured model.

    A remote configured URL is never replaced by a local process. The caller is an
    explicit caption action, not a passive capability probe.
    """
    url = _url()
    if not _reachable(url):
        if not _is_loopback_url(url):
            return {'ok': False, 'reachable': False,
                    'error': f'Remote Ollama server is unreachable: {url}' }
        started = start_ollama()
        if not started.get('ok') or not started.get('reachable'):
            return {'ok': False, 'reachable': False,
                    'error': started.get('error') or 'Ollama could not start'}
    model = capabilities.probe_ollama_model(reachable=True)
    if not model.get('ok'):
        return {'ok': False, 'reachable': True,
                'error': model.get('detail') or 'Configured Ollama vision model is not available'}
    return {'ok': True, 'reachable': True, 'model_ready': True}
