"""The one statement of how this app talks to a script in `backend/infer/`.

Four features (face scoring, person masks, watermark inpainting, JoyCaption)
each run a heavy ML model in a DEDICATED interpreter, because insightface /
rembg / torch are deliberately absent from the Flask venv. They all speak the
same protocol, and each of the four used to restate it:

    stdin   one JSON object
    stdout  the answer as the LAST line beginning with '{'
            (anything else on stdout is progress chatter and is ignored)
    stderr  logs; its last non-empty line is the crash message
    exit    non-zero is *reported*, never raised

Stating it four times let it drift on every axis that mattered: the accented and
unaccented spellings of the same log line, the 400-character stderr cap, the
Windows no-console flag, and — the one that cost a user-visible bug — whether a
dead worker came back as a structured error or as a silent empty result. It is
stated once here.

What this module deliberately does NOT own: what a valid answer looks like. Each
caller validates its own response schema and decides whether a failure is fatal,
because those genuinely differ (a missing mask is survivable, a broken face
scorer must be shown). It hands back ``(data, error)`` and lets the caller
choose.
"""
from __future__ import annotations

import json
import logging
import subprocess


def stderr_tail(proc) -> str:
    """Last non-empty line of `proc`'s stderr.

    For a Python crash that is the ``SomeError: ...`` line of the traceback —
    exactly the line a human wants to read, and the one that named the real
    problem (a nested antelopev2 AssertionError) in the field.
    """
    return next((line.strip() for line in reversed((proc.stderr or '').splitlines())
                 if line.strip()), '')


def run_json_worker(python, script, payload, *, timeout, logger: logging.Logger,
                    label: str, noun: str = 'worker', env=None, cwd=None):
    """Run `script` under `python`, hand it `payload` as JSON, return (data, error).

    Exactly one of the two is ever set. `error` is this app's usual
    ``{'kind': 'failed', 'detail': ...}`` shape, with `detail` written for a
    human: the worker's own crash line when there is one, otherwise a sentence
    naming `noun` and the exit code. `label` prefixes the log lines (it is the
    calling module's name) and `noun` names the worker in user-facing detail
    text ('scorer', 'inpainter', ...).

    Never raises: a worker that times out, fails to start, prints nothing, or
    prints garbage all come back as an `error`, because every caller here is a
    feature the app must survive without.
    """
    try:
        proc = subprocess.run(
            [str(python), str(script)], input=json.dumps(payload),
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout, env=env, cwd=cwd,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning('%s: subprocess echec : %s', label, exc)
        return None, {'kind': 'failed', 'detail': str(exc)}
    line = next((ln for ln in reversed((proc.stdout or '').splitlines())
                 if ln.strip().startswith('{')), '')
    if not line:
        # The tail is the useful half; the 400-character stderr window in the
        # log is for the surrounding context the tail alone loses.
        logger.warning('%s: pas de JSON (rc=%s) stderr=%s', label,
                       proc.returncode, (proc.stderr or '')[-400:])
        return None, {'kind': 'failed',
                      'detail': (stderr_tail(proc)
                                 or f'{noun} produced no output (rc={proc.returncode})')}
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        logger.warning('%s: JSON illisible : %s', label, exc)
        return None, {'kind': 'failed', 'detail': f'unreadable {noun} output: {exc}'}
    if not isinstance(data, dict):
        logger.warning('%s: invalid response schema', label)
        return None, {'kind': 'failed', 'detail': f'invalid {noun} response schema'}
    return data, None
