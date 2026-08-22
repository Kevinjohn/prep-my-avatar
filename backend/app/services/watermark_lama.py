"""Watermark inpainting via the local Big-LaMa adapter, run in a dedicated ML
interpreter. Le protocole subprocess/JSON lui-meme vit dans
app/services/ml_worker.py — sauf pour `inpaint_batch`, qui lit en plus le flux de
progression ligne-a-ligne du worker et doit donc garder son propre appel (voir la
note sur place). Le device est configurable (Auto/GPU/CPU) ; le routeur reserve
la fenetre GPU uniquement quand CUDA est effectivement utilise.

LaMa est NON-generatif : seuls les pixels du rectangle masque changent, le reste de
l'image reste identique. Sert la V1 de la correction automatique des watermarks : les
bbox HORS bande de bord mais d'aire <= 10% sont repeintes ici (les bbox de bord sont
croppees en PIL pur, sans ce module)."""
from __future__ import annotations
import json
import logging
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from .. import config as cfg
from .ml_worker import run_json_worker, stderr_tail

logger = logging.getLogger(__name__)

# lama_infer.py vit dans backend/infer/ (pas app/services/).
_SCRIPT = str(cfg.BACKEND_DIR / 'infer' / 'lama_infer.py')
_cuda_probe = {'python': None, 'checked': 0.0, 'available': False}
# Shown to the user by both entry points; named so the two cannot drift into
# saying different things about the same missing install.
_UNAVAILABLE_DETAIL = 'watermark inpainting is not installed (ML extras)'


def lama_python() -> str:
    # Cle dediee, sinon on reutilise le python ML existant (rembg/insightface), sinon
    # l'interpreteur courant. LaMa dependencies live in requirements-ml.txt.
    # PUBLIC : le bouton « Install inpainting » (setup_installer) cible CE meme
    # resolveur, pour que l'install atterrisse la ou le wrapper importe ensuite.
    return cfg.get('watermark.python') or cfg.get('masks.python') or sys.executable


def is_available() -> bool:
    from ..capabilities import probe_watermark_inpaint
    return probe_watermark_inpaint()['ok']


def _cuda_available() -> bool:
    """Probe CUDA in the same interpreter that runs LaMa (short cached subprocess)."""
    python = lama_python()
    now = time.monotonic()
    if _cuda_probe['python'] == python and now - _cuda_probe['checked'] < 60:
        return bool(_cuda_probe['available'])
    try:
        proc = subprocess.run(
            [python, '-c', 'import torch; print("1" if torch.cuda.is_available() else "0")'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        available = proc.returncode == 0 and (proc.stdout or '').strip().endswith('1')
    except (subprocess.TimeoutExpired, OSError):
        available = False
    _cuda_probe.update(python=python, checked=now, available=available)
    return available


def resolve_device(requested=None) -> str:
    requested = (requested or cfg.get('watermark.device') or 'auto').lower()
    if requested not in ('auto', 'cuda', 'cpu'):
        raise RuntimeError(f"Unknown watermark device '{requested}'")
    if requested == 'cpu':
        return 'cpu'
    available = _cuda_available()
    if requested == 'cuda' and not available:
        raise RuntimeError('CUDA was selected for watermark cleaning but is not available in the configured ML Python environment')
    return 'cuda' if available else 'cpu'


def _run_lama_payload(payload, timeout: int = 300) -> tuple[bool, dict | None]:
    """Execute le worker LaMa en preservant son protocole subprocess/JSON.

    Le seul appelant est `_inpaint_staged`, qui vient de creer `image_path` via
    mkstemp+copy2 : inutile de re-verifier son existence ici. Une source
    reellement absente est deja rapportee par le `copy2` en amont
    (« could not stage image: … »), avec le chemin fautif.
    """
    if not is_available():
        return False, {'kind': 'unavailable',
                       'detail': _UNAVAILABLE_DETAIL}
    data, error = run_json_worker(
        lama_python(), _SCRIPT, payload, timeout=timeout, logger=logger,
        label='watermark_lama', noun='inpainter')
    if error is not None:
        return False, error
    if not data.get('ok'):
        detail = data.get('error') or 'inpaint failed'
        logger.warning('watermark_lama: echec : %s', detail)
        return False, {'kind': 'failed', 'detail': detail}
    return True, None


def _staged_image_path(image_path: str, output_path: str) -> str:
    """Copy an image to a same-filesystem sibling for destructive ML work.

    `output_path` is required: the staged file must carry the DESTINATION's
    extension, because that is what tells the worker which encoder to use. Both
    callers already know it (an in-place edit passes the source back in).
    """
    source = Path(image_path)
    fd, staged = tempfile.mkstemp(
        prefix=f'.{source.name}.lama-',
        suffix=Path(output_path).suffix,
        dir=source.parent,
    )
    os.close(fd)
    try:
        shutil.copy2(source, staged)
    except Exception:
        Path(staged).unlink(missing_ok=True)
        raise
    return staged


def _publish_staged_image(staged: str, destination: str) -> None:
    """Durably publish completed pixels without exposing a partial overwrite."""
    # Windows rejects fsync on a read-only descriptor with EBADF.
    with open(staged, 'rb+') as handle:
        os.fsync(handle.fileno())
    os.replace(staged, destination)


def _inpaint_staged(payload: dict, timeout: int, output_path=None) -> tuple[bool, dict | None]:
    """Run the in-place helper on a copy and publish only a reported success."""
    source = str(payload['image_path'])
    destination = str(output_path or source)
    try:
        staged = _staged_image_path(source, destination)
    except OSError as exc:
        return False, {'kind': 'failed', 'detail': f'could not stage image: {exc}'}
    try:
        staged_payload = {**payload, 'image_path': staged}
        ok, error = _run_lama_payload(staged_payload, timeout=timeout)
        if not ok:
            return False, error
        try:
            _publish_staged_image(staged, destination)
        except OSError as exc:
            return False, {'kind': 'failed', 'detail': f'could not publish image: {exc}'}
        return True, None
    finally:
        Path(staged).unlink(missing_ok=True)


def inpaint_watermarks(image_path, bboxes, timeout: int = 300, device: str = 'cpu',
                       output_path=None) -> tuple[bool, dict | None]:
    """Repeint en une passe LaMa les rectangles normalises de ``bboxes``.

    L'image source est modifiee en place, SAUF si ``output_path`` est fourni —
    auquel cas la source n'est jamais touchee. Le retour ``(ok, error)`` conserve
    le contrat historique : ``error`` vaut ``None`` en cas de succes, sinon
    contient ``kind`` et ``detail``.
    """
    payload = {'image_path': str(image_path), 'bboxes': bboxes, 'device': device}
    return _inpaint_staged(payload, timeout=timeout, output_path=output_path)


def inpaint_watermark(image_path, bbox, timeout: int = 300, device: str = 'cpu',
                      output_path=None) -> tuple[bool, dict | None]:
    """Adaptateur compatible pour l'ancien appel a un seul rectangle."""
    try:
        bbox = [float(value) for value in bbox]
        if len(bbox) != 4:
            raise ValueError('bbox must have 4 values')
        if not all(math.isfinite(value) for value in bbox):
            raise ValueError('bbox values must be finite')
    except Exception as e:
        return False, {'kind': 'failed', 'detail': f'payload: {e}'}
    x1, y1, x2, y2 = bbox
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    normalized = [
        max(0.0, min(1.0, left)),
        max(0.0, min(1.0, top)),
        max(0.0, min(1.0, right)),
        max(0.0, min(1.0, bottom)),
    ]
    return inpaint_watermarks(
        image_path, [normalized], timeout=timeout, device=device,
        output_path=output_path)


def _item_outcome(item: dict) -> tuple[bool, dict | None]:
    """Read one per-image worker record into this module's ``(ok, error)`` pair.

    The worker reports the same record twice — streamed as it finishes each
    image, and again in the final summary — and both readers below used to
    decode it separately. One decode means the streamed and summary paths can
    never disagree about what the worker said.
    """
    if item.get('ok'):
        return True, None
    return False, {'kind': 'failed', 'detail': item.get('error') or 'inpaint failed'}


def inpaint_batch(jobs, *, device: str, timeout: int = 900) -> dict:
    """Run multiple image jobs in one worker so SimpleLama is loaded only once."""
    normalized = []
    for job in jobs or []:
        path = str(job.get('image_path') or '')
        if not path or not os.path.isfile(path):
            raise ValueError(f'image not found: {path}')
        normalized.append({
            'image_path': path,
            'output_path': str(job.get('output_path') or path),
            'bboxes': job.get('bboxes') or [],
        })
    if not normalized:
        return {}
    if not is_available():
        err = {'kind': 'unavailable', 'detail': _UNAVAILABLE_DETAIL}
        return {job['image_path']: (False, err) for job in normalized}
    staged_by_original = {}
    try:
        for job in normalized:
            staged_by_original[job['image_path']] = _staged_image_path(
                job['image_path'], job['output_path'])
    except OSError as exc:
        for staged in staged_by_original.values():
            Path(staged).unlink(missing_ok=True)
        err = {'kind': 'failed', 'detail': f'could not stage image: {exc}'}
        return {job['image_path']: (False, err) for job in normalized}
    original_by_staged = {staged: original for original, staged in staged_by_original.items()}
    staged_jobs = [
        {**job, 'image_path': staged_by_original[job['image_path']]}
        for job in normalized
    ]
    payload_json = json.dumps({'jobs': staged_jobs, 'device': device})
    proc = None
    interrupted_error = None
    # Deliberately NOT ml_worker.run_json_worker: this is the only caller that
    # needs the worker's partial stdout after a TimeoutExpired, so that images
    # finished before the kill are still published. The shared runner returns an
    # error and no output, which is right for everyone else and wrong here.
    try:
        proc = subprocess.run([lama_python(), _SCRIPT], input=payload_json,
                              capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired as exc:
        interrupted_error = {'kind': 'failed', 'detail': str(exc)}
        stdout = exc.stdout or ''
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8', errors='replace')
    except OSError as exc:
        interrupted_error = {'kind': 'failed', 'detail': str(exc)}
        stdout = ''
    else:
        stdout = proc.stdout or ''
    lines = stdout.splitlines()
    if interrupted_error is not None:
        # Only the interrupted path replays the per-image progress stream, to
        # keep whatever the worker managed to finish before it died. On the
        # normal path the summary object below already says the same thing, so
        # json-parsing every line again would be pure waste.
        streamed = {}
        for candidate in lines:
            try:
                item = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get('type') == 'result':
                streamed[str(item.get('image_path') or '')] = _item_outcome(item)
        staged_results = {job['image_path']: streamed.get(
            staged_by_original[job['image_path']], (False, interrupted_error))
                          for job in normalized}
        return _publish_batch_results(staged_results, staged_by_original, normalized)
    line = next((ln for ln in reversed(lines)
                 if ln.strip().startswith('{')), '')
    try:
        data = json.loads(line) if line else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict) or not data.get('ok'):
        detail = data.get('error') if isinstance(data, dict) else None
        err = {'kind': 'failed', 'detail': detail or stderr_tail(proc) or 'inpaint worker failed'}
        return _publish_batch_results(
            {job['image_path']: (False, err) for job in normalized},
            staged_by_original, normalized)
    results = data.get('results') or []
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        err = {'kind': 'failed', 'detail': 'invalid inpaint worker results schema'}
        return _publish_batch_results(
            {job['image_path']: (False, err) for job in normalized},
            staged_by_original, normalized)
    by_path = {}
    for item in results:
        path = original_by_staged.get(str(item.get('image_path') or ''), '')
        by_path[path] = _item_outcome(item)
    staged_results = {
        job['image_path']: by_path.get(
            job['image_path'],
            (False, {'kind': 'failed', 'detail': 'missing worker result'}),
        )
        for job in normalized
    }
    return _publish_batch_results(staged_results, staged_by_original, normalized)


def _publish_batch_results(results: dict, staged_by_original: dict[str, str],
                           jobs: list[dict]) -> dict:
    """Publish successful staged batch outputs and discard every other copy."""
    published = {}
    destinations = {job['image_path']: job['output_path'] for job in jobs}
    for original, staged in staged_by_original.items():
        ok, error = results.get(
            original, (False, {'kind': 'failed', 'detail': 'missing worker result'}))
        if ok:
            try:
                _publish_staged_image(staged, destinations[original])
            except OSError as exc:
                ok = False
                error = {'kind': 'failed', 'detail': f'could not publish image: {exc}'}
        Path(staged).unlink(missing_ok=True)
        published[original] = (ok, error)
    return published
