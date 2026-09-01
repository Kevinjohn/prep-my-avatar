"""Setup installer: run whitelisted, self-contained installs in a background
thread and expose their live state for polling. Actions:

  ml_extras          -> pip install -r backend/requirements-ml.txt (the app's own venv):
                        installs ALL the ML extras at once on Python 3.11–3.12
  face_scoring       -> pip install JUST the face-scoring packages (insightface + onnx-
                        runtime, versions read from requirements-ml.txt) into the inter-
                        preter probe_face_scoring resolves — install/repair ONE feature
  masks              -> pip install JUST the person-mask package (rembg) into the inter-
                        preter probe_masks resolves — install/repair ONE feature
  watermark_inpaint  -> pip install JUST the secure Torch/Pillow/OpenCV dependencies used
                        by the repository's LaMa adapter into the interpreter that adapter
                        resolves — the scoped install shown next to the Curate 🧽 tools
  (face_scoring/masks/watermark_inpaint all follow the same shape: ML interpreter resolved
   per capability, requirements-ml.txt pinned as a -c constraint, probe cache invalidated
   on success so the capability flips without a restart.)
  ollama_model       -> stream Ollama's /api/pull for the configured vision model
  klein_model        -> download the Klein fp8 diffusion model into <ComfyUI>/models/unet/klein/
                        (BFL repo is LICENSE-GATED: needs the agreement accepted on HF +
                        an HF_TOKEN secret; a 401 logs the exact recovery steps)
  klein_lora         -> download the consistency LoRA into <ComfyUI>/models/loras/klein/
  klein_text_encoder -> qwen_3_8b_fp8mixed into <ComfyUI>/models/text_encoders/
  klein_vae          -> flux2-vae into <ComfyUI>/models/vae/

No shell, no client-supplied arguments: each action's command/URL/destination is fixed.
"""
import logging
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import requests
from flask import current_app, has_app_context

from . import capabilities
from . import config as cfg

_Thread = threading.Thread

logger = logging.getLogger(__name__)

# Fixed catalog of the Klein downloads (checked 2026-07-10): the three Comfy-Org/
# dx8152 files are public; the BFL diffusion model is gated (401 without a token).
_KLEIN_DOWNLOADS = {
    'klein_model': {
        'url': 'https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8/resolve/main/flux-2-klein-9b-fp8.safetensors',
        'dest': ('unet', 'klein', 'flux-2-klein-9b-fp8.safetensors'),
        'min_free_gb': 15, 'gated': True,
        'license_url': 'https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8',
    },
    'klein_lora': {
        'url': 'https://huggingface.co/dx8152/Flux2-Klein-9B-Consistency/resolve/main/Flux2-Klein-9B-consistency-V2.safetensors',
        'dest': ('loras', 'klein', 'Flux2-Klein-9B-consistency-V2.safetensors'),
        'min_free_gb': 1, 'gated': False,
    },
    'klein_text_encoder': {
        'url': 'https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/resolve/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors',
        'dest': ('text_encoders', 'qwen_3_8b_fp8mixed.safetensors'),
        'min_free_gb': 12, 'gated': False,
    },
    'klein_vae': {
        'url': 'https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/resolve/main/split_files/vae/flux2-vae.safetensors',
        'dest': ('vae', 'flux2-vae.safetensors'),
        'min_free_gb': 2, 'gated': False,
    },
}

INSTALL_ACTIONS = ('ml_extras', 'scrape_extras', 'ollama_model',
                   'face_scoring', 'masks', 'watermark_inpaint') + tuple(_KLEIN_DOWNLOADS)

_ML_REQUIREMENTS = cfg.BACKEND_DIR / 'requirements-ml.txt'
_SCRAPE_REQUIREMENTS = cfg.BACKEND_DIR / 'requirements-scrape.txt'
# pip -r installers share one worker; both target THIS interpreter (the scrape
# stack runs in-process, so any other environment would be invisible to the app).
_PIP_REQUIREMENTS = {'ml_extras': _ML_REQUIREMENTS, 'scrape_extras': _SCRAPE_REQUIREMENTS}
# --- ML extras, split per capability -------------------------------------------
# requirements-ml.txt is a FLAT pip file (not grouped by feature), so the
# package->capability grouping lives HERE. The VERSIONS are never duplicated: each
# package's exact requirement line is read from requirements-ml.txt via
# _requirement_spec(), and that same file rides along as a `-c` constraint. A dedicated
# test (test_no_orphan_ml_package) asserts EVERY line in requirements-ml.txt is
# owned by at least one capability below — a package added to the file but
# forgotten here would silently never be installed by any scoped action.
#
#   face_scoring  insightface (face embeddings), onnxruntime, NumPy and headless cv2.
#   masks         rembg (u2net background removal), ONNX, NumPy, Pillow and cv2.
#   watermark_inpaint  TorchScript runtime plus NumPy, Pillow and cv2 for the local
#                 hash-verifying LaMa adapter.
_CAPABILITY_PACKAGES = {
    'face_scoring': ('insightface', 'onnxruntime', 'numpy', 'opencv-python-headless'),
    'masks': ('rembg', 'onnxruntime', 'numpy', 'opencv-python-headless', 'pillow'),
    'watermark_inpaint': ('torch', 'numpy', 'opencv-python-headless', 'pillow'),
}
# The capabilities served by the GENERIC per-capability pip worker
# (_run_ml_capability). watermark_inpaint keeps its own worker, so it's excluded.
_CAPABILITY_ML_ACTIONS = ('face_scoring', 'masks')

# Actions whose success makes a NEW importable package appear -> the probe
# import-cache must be dropped so the capability flips without waiting out the
# 600 s TTL (ml_extras/scrape_extras via -r, the scoped per-capability installs).
_IMPORT_CACHE_ACTIONS = (frozenset(_PIP_REQUIREMENTS)
                         | set(_CAPABILITY_ML_ACTIONS) | {'watermark_inpaint'})
_LOG_MAX = 400  # ring-buffer the log so a chatty pip can't grow unbounded

_lock = threading.Lock()
_runs = {}  # action -> {'state', 'returncode', 'log'}
_persisted_progress = {}  # action -> (monotonic time, byte count)


class AlreadyRunning(Exception):
    pass


class Precondition(Exception):
    pass


class InstallerCancelled(Exception):
    """Internal control flow for cancellation before child publication."""


def _new_run():
    return {'state': 'running', 'returncode': None, 'log': [], 'progress': None,
            'job_id': None, 'process': None, 'cancel_requested': False,
            'environment_before': None}


def _environment_snapshot(interpreter: str) -> dict:
    """Record enough ownership/recovery evidence before pip mutates an env."""
    code = (
        "import importlib.metadata,json; "
        "print(json.dumps(sorted(f'{d.metadata[\"Name\"]}=={d.version}' "
        "for d in importlib.metadata.distributions() if d.metadata.get('Name'))))"
    )
    result = subprocess.run(
        [interpreter, '-c', code], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise Precondition(
            f'could not snapshot target interpreter before installation: '
            f'{(result.stderr or result.stdout).strip()[-1000:]}')
    try:
        packages = json.loads(result.stdout)
    except ValueError as exc:
        raise Precondition('target interpreter returned an invalid package snapshot') from exc
    if not isinstance(packages, list) or not all(isinstance(item, str) for item in packages):
        raise Precondition('target interpreter returned an invalid package snapshot')
    return {'interpreter': interpreter, 'packages': packages}


def _spawn_owned(action, command):
    with _lock:
        run = _runs[action]
        if run.get('cancel_requested'):
            raise InstallerCancelled('installer cancelled before process spawn')
        # Keep the cancellation check, spawn, and publication under one lock.
        # A concurrent cancel either wins before Popen or observes and terminates
        # the published child; it can never land in an unowned spawn gap.
        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1)
        run['process'] = proc
    child_identity = None
    try:
        import psutil
        child_identity = {
            'pid': proc.pid,
            'created_at': psutil.Process(proc.pid).create_time(),
        }
    except Exception:
        child_identity = {'pid': getattr(proc, 'pid', None), 'created_at': None}
    run['child_identity'] = child_identity
    _persist(action, result={
        'child_pid': getattr(proc, 'pid', None),
        'child_identity': child_identity,
        'environment_before': run.get('environment_before'),
    })
    return proc


def active_pip_mutations() -> list[str]:
    with _lock:
        return sorted(action for action, run in _runs.items()
                      if run.get('state') == 'running' and _pip_target(action) is not None)


def _restore_environment(snapshot: dict) -> tuple[bool, str]:
    interpreter = snapshot.get('interpreter') if isinstance(snapshot, dict) else None
    packages = snapshot.get('packages') if isinstance(snapshot, dict) else None
    if not interpreter or not isinstance(packages, list):
        return False, 'pre-install environment snapshot is incomplete'
    fd, raw_path = tempfile.mkstemp(prefix='pma-setup-recovery-', suffix='.txt')
    requirements = raw_path
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(packages) + '\n')
        result = subprocess.run(
            [interpreter, '-m', 'pip', 'install', '-r', requirements],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=1800)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout)[-2000:]
        current = _environment_snapshot(interpreter)['packages']
        expected_names = {_canon(item.split('==', 1)[0]) for item in packages}
        extras = [item.split('==', 1)[0] for item in current
                  if _canon(item.split('==', 1)[0]) not in expected_names]
        if extras:
            removed = subprocess.run(
                [interpreter, '-m', 'pip', 'uninstall', '-y', *extras],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=1800)
            if removed.returncode != 0:
                return False, (removed.stderr or removed.stdout)[-2000:]
        if _environment_snapshot(interpreter)['packages'] != packages:
            return False, 'package verification did not match the pre-install snapshot'
        return True, ''
    except (OSError, subprocess.SubprocessError, Precondition) as exc:
        return False, str(exc)
    finally:
        try:
            os.unlink(requirements)
        except OSError:
            pass


def recover_interrupted_installers() -> int:
    """Stop an owned pip child and restore its exact pre-install inventory."""
    from .models import BackgroundJob
    from .services import background_jobs

    rows = (BackgroundJob.query.filter_by(kind='setup')
            .filter(BackgroundJob.state.in_(background_jobs.ACTIVE_STATES)).all())
    recovered = 0
    for row in rows:
        saved = background_jobs.snapshot(row)
        snapshot = saved.get('environment_before')
        if not snapshot:
            continue
        identity = saved.get('child_identity') or {}
        pid = identity.get('pid')
        if pid:
            try:
                import psutil
                process = psutil.Process(int(pid))
                created = identity.get('created_at')
                if created is None or abs(process.create_time() - float(created)) < 0.01:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except psutil.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
            except Exception:
                # A missing child is the normal restart case. Any other failure
                # is logged, but environment restoration remains possible.
                try:
                    missing = isinstance(
                        sys.exc_info()[1], (psutil.NoSuchProcess, psutil.ZombieProcess))
                except (NameError, AttributeError):
                    missing = False
                if not missing:
                    logger.exception('could not stop interrupted installer child %s', pid)
        ok, detail = _restore_environment(snapshot)
        background_jobs.touch(
            row.id,
            state='interrupted' if ok else 'error',
            result={
                'returncode': None,
                'environment_before': snapshot,
                'environment_restored': ok,
            },
            error=('The app restarted during installation; the pre-install '
                   'environment was restored.' if ok else
                   f'Interrupted installer recovery failed: {detail}'),
            error_code='environment_restored' if ok else 'installer_recovery_failed')
        recovered += 1
    return recovered


def cancel(action) -> dict:
    with _lock:
        run = _runs.get(action)
        if not run or run.get('state') != 'running':
            raise Precondition('installer is not running')
        run['cancel_requested'] = True
        proc = run.get('process')
        result = {
            'cancel_requested': True,
            'child_pid': getattr(proc, 'pid', None),
            'child_identity': run.get('child_identity'),
            'environment_before': run.get('environment_before'),
        }
    _persist(action, result=result)
    if proc is not None and proc.poll() is None:
        proc.terminate()
    return status(action)


def _pip_target(action):
    """Canonical interpreter mutated by a setup action, or None for non-pip work."""
    if action in _PIP_REQUIREMENTS:
        return os.path.normcase(os.path.abspath(sys.executable))
    if action in _CAPABILITY_ML_ACTIONS:
        return os.path.normcase(os.path.abspath(_capability_python(action)))
    if action == 'watermark_inpaint':
        return os.path.normcase(os.path.abspath(_watermark_python()))
    return None


def _persist(action, **changes):
    run = _runs.get(action) or {}
    job_id = run.get('job_id')
    if not job_id or not has_app_context():
        return
    try:
        from .services import background_jobs
        background_jobs.touch(job_id, **changes)
    except Exception:
        logger.debug('could not persist setup job %s', action, exc_info=True)


def _append(action, line):
    log = _runs[action]['log']
    log.append(line.rstrip('\n'))
    if len(log) > _LOG_MAX:
        del log[:-_LOG_MAX]
    _persist(action, log=line.rstrip('\n'))


def _set_progress(action, done, total):
    """Publish a live byte-progress snapshot for a streaming download, separate
    from the text log (so a smooth % bar never spams the log). `total` may be 0
    when the server sends no content-length -> pct is None (indeterminate)."""
    run = _runs.get(action)
    if run is None:
        return
    run['progress'] = {
        'done': done,
        'total': total,
        'pct': (done * 100 // total) if total else None,
    }
    # The UI gets every in-memory update, but a multi-GB download must not fsync
    # SQLite once per 8 MB network chunk. Persist at most every 2 seconds or
    # 64 MB, plus the first/final snapshot.
    now = time.monotonic()
    last_time, last_done = _persisted_progress.get(action, (0.0, -1))
    terminal = bool(total and done >= total)
    if (done == 0 or terminal or now - last_time >= 2.0
            or done - last_done >= 64 * 1024 * 1024):
        _persisted_progress[action] = (now, done)
        _persist(action, progress=run['progress'])


def _quote(p: str) -> str:
    # Quote paths with spaces so the manual command is copy-paste-safe: the
    # portable bundle can be extracted under e.g. C:\Users\...\LoRA Dataset Studio\.
    return f'"{p}"' if ' ' in p else p


def _canon(name: str) -> str:
    """PEP 503 canonical form: -_. all fold to a single dash, case-insensitive."""
    return re.sub(r'[-_.]+', '-', name).lower()


def _requirement_spec(name: str, requirements=_ML_REQUIREMENTS) -> str:
    """The full requirement line for `name` as written in a requirements file
    (e.g. 'torch==2.13.0') — the version pin lives in ONE place
    (requirements-ml.txt), never duplicated in this module. Package-name match is
    canonicalised (PEP 503: -_. all fold together, case-insensitive) and tolerant
    of version/marker/extras suffixes. Falls back to the bare name if the file or
    line is missing (an unpinned `pip install <name>` still works)."""
    canon = _canon(name)
    try:
        for raw in requirements.read_text(encoding='utf-8').splitlines():
            line = raw.split('#', 1)[0].strip()   # drop comments / blank lines
            if not line:
                continue
            token = re.split(r'[<>=!~;\[\s]', line, maxsplit=1)[0]   # name before any spec/marker
            if _canon(token) == canon:
                return line
    except OSError:
        pass
    return name


def _ml_requirement_names(requirements=_ML_REQUIREMENTS) -> set:
    """Canonical names of every package declared in a requirements file (comments
    and blank lines dropped). Used by the anti-orphan test to prove each ML package
    is mapped to a capability in _CAPABILITY_PACKAGES."""
    names = set()
    try:
        for raw in requirements.read_text(encoding='utf-8').splitlines():
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            token = re.split(r'[<>=!~;\[\s]', line, maxsplit=1)[0]
            names.add(_canon(token))
    except OSError:
        pass
    return names


def _watermark_python() -> str:
    """Interpreter the watermark LaMa wrapper resolves. Reuse the wrapper's OWN
    resolver (watermark.python > masks.python > sys.executable) so the install
    target and the later import can never drift apart."""
    from .services import watermark_lama
    return watermark_lama.lama_python()


def _capability_python(action) -> str:
    """Interpreter a scoped ML install targets — MUST match the resolution its
    matching probe uses, so the install target and the later import can't drift:
      face_scoring -> face_scoring.python  (see capabilities.probe_face_scoring)
      masks        -> masks.python         (see capabilities.probe_masks)
      watermark_inpaint -> the wrapper chain (watermark.python > masks.python)."""
    if action == 'watermark_inpaint':
        return _watermark_python()
    return cfg.get(f'{action}.python') or sys.executable


def manual_command(action) -> str:
    """The exact command that reproduces an install BY HAND, scoped to THIS app's
    own interpreter (sys.executable). A copy-paste then targets the SAME
    environment the app imports from -- the portable bundle's python\\python.exe or
    the dev venv -- instead of whatever bare `pip` happens to be first on PATH
    (which is the whole point of the user's question: a plain `pip install` would
    land in the wrong environment and the extras would never be importable)."""
    if action in _PIP_REQUIREMENTS:
        return f'{_quote(sys.executable)} -m pip install -r {_quote(str(_PIP_REQUIREMENTS[action]))}'
    if action in _CAPABILITY_ML_ACTIONS:
        # One scoped capability (face_scoring | masks): the exact version-pinned
        # lines from requirements-ml.txt, quoted (the '>=' / '<' are shell
        # redirection unquoted), plus that file as a -c constraint. Interpreter =
        # the same one the capability's probe resolves.
        specs = ' '.join(f'"{_requirement_spec(p)}"' for p in _CAPABILITY_PACKAGES[action])
        return (f'{_quote(_capability_python(action))} -m pip install {specs} '
                f'-c {_quote(str(_ML_REQUIREMENTS))}')
    if action == 'watermark_inpaint':
        specs = ' '.join(
            f'"{_requirement_spec(p)}"'
            for p in _CAPABILITY_PACKAGES['watermark_inpaint'])
        return (f'{_quote(_watermark_python())} -m pip install {specs} '
                f'-c {_quote(str(_ML_REQUIREMENTS))}')
    if action == 'ollama_model':
        model = (cfg.get('ollama.vision_model') or '').strip() or '<vision-model>'
        return f'ollama pull {model}'
    if action in _KLEIN_DOWNLOADS:
        spec = _KLEIN_DOWNLOADS[action]
        try:
            dest = _klein_dest_path(action)
        except Precondition:
            dest = os.path.join('<ComfyUI>', 'models', *spec['dest'])
        return f'curl -L -o "{dest}" "{spec["url"]}"'
    return ''


def status(action) -> dict:
    run = _runs.get(action)
    cmd = manual_command(action)
    if run is None:
        if has_app_context():
            try:
                from .services import background_jobs
                saved = background_jobs.snapshot(background_jobs.latest('setup', action))
                if saved.get('state') != 'idle':
                    state = saved['state']
                    if state == 'done':
                        state = 'success'
                    elif state == 'interrupted':
                        state = 'error'
                    return {
                        'state': state,
                        'returncode': saved.get('returncode'),
                        'log': saved.get('log') or [],
                        'progress': saved.get('progress'),
                        'error': saved.get('error'),
                        'error_code': saved.get('error_code'),
                        'job_id': saved.get('job_id'),
                        'child_pid': saved.get('child_pid'),
                        'environment_before': saved.get('environment_before'),
                        'manual_command': cmd,
                    }
            except Exception:
                logger.debug('could not load persisted setup job %s', action, exc_info=True)
        return {'state': 'idle', 'returncode': None, 'log': [], 'progress': None,
                'manual_command': cmd}
    return {'state': run['state'], 'returncode': run['returncode'],
            'log': list(run['log']), 'progress': run.get('progress'),
            'job_id': run.get('job_id'),
            'child_pid': getattr(run.get('process'), 'pid', None),
            'environment_before': run.get('environment_before'),
            'manual_command': cmd}


def start(action) -> dict:
    if action not in INSTALL_ACTIONS:
        raise ValueError(f'unknown action: {action}')
    with _lock:
        run = _runs.get(action)
        if run and run['state'] == 'running':
            raise AlreadyRunning(action)
        target = _pip_target(action)
        if target is not None:
            for other_action, other_run in _runs.items():
                if (other_action != action and other_run.get('state') == 'running'
                        and _pip_target(other_action) == target):
                    raise AlreadyRunning(
                        f'{other_action} is already modifying interpreter {target}')
        if action == 'ml_extras' and not capabilities.python_ml_status()['ml_supported']:
            ml_status = capabilities.python_ml_status()
            raise Precondition(
                f"ML extras require Python {ml_status['ml_range']}; this app uses "
                f"Python {ml_status['version']}")
        if action in (*_CAPABILITY_ML_ACTIONS, 'watermark_inpaint') \
                and _capability_python(action) == sys.executable \
                and not capabilities.python_ml_status()['ml_supported']:
            ml_status = capabilities.python_ml_status()
            raise Precondition(
                f"{action} requires Python {ml_status['ml_range']}; configure a supported "
                f"feature interpreter or run the app with one (current: {ml_status['version']})")
        if action == 'ollama_model':
            _check_ollama_precondition()
        if action in _KLEIN_DOWNLOADS:
            _check_klein_precondition(action)
        run = _new_run()
        if target is not None:
            run['environment_before'] = _environment_snapshot(target)
        app = current_app._get_current_object() if has_app_context() else None
        if app is not None:
            try:
                from .services import background_jobs
                job, created = background_jobs.create_or_get(
                    'setup', action, {'action': action})
                if not created:
                    raise AlreadyRunning(action)
                if job.state in background_jobs.ACTIVE_STATES and job.started_at:
                    run['job_id'] = job.id
            except AlreadyRunning:
                raise
            except Exception as exc:
                logger.exception('could not create durable setup job %s', action)
                raise Precondition(
                    'could not create a durable setup job; no installer was started') from exc
        _runs[action] = run
    _Thread(target=_execute_with_app, args=(app, action), daemon=True).start()
    return status(action)


def _execute_with_app(app, action):
    if app is None:
        _execute(action)
        return
    with app.app_context():
        _execute(action)


def _check_ollama_precondition():
    if not (cfg.get('ollama.url') or '').strip():
        raise Precondition('ollama.url not configured')
    if not (cfg.get('ollama.vision_model') or '').strip():
        raise Precondition('ollama.vision_model not configured')


def _klein_dest_path(action) -> str:
    """Absolute destination for a Klein download, under the VALIDATED ComfyUI
    models root. Raises Precondition when base_dir isn't a real install (we must
    never scatter multi-GB files under a wrong folder)."""
    r = capabilities.resolve_comfyui_base(cfg.get('comfyui.base_dir') or '')
    if not r['valid']:
        raise Precondition('point the app at a valid ComfyUI folder first (Setup, ComfyUI step)')
    spec = _KLEIN_DOWNLOADS[action]
    return os.path.join(r['resolved'], 'models', *spec['dest'])


def _check_klein_precondition(action):
    dest = _klein_dest_path(action)
    spec = _KLEIN_DOWNLOADS[action]
    try:
        free_gb = shutil.disk_usage(os.path.dirname(os.path.dirname(dest))).free / 1e9
        if free_gb < spec['min_free_gb']:
            raise Precondition(f'not enough disk space: {free_gb:.1f} GB free, '
                               f"~{spec['min_free_gb']} GB needed for this file")
    except OSError:
        pass   # unknown -> never block on a stat failure


def _execute(action):
    try:
        if _runs[action].get('cancel_requested'):
            raise InstallerCancelled('installer cancelled before worker start')
        rc = _WORKERS[action](action)
        cancelled = bool(_runs[action].get('cancel_requested'))
        if cancelled:
            snapshot = _runs[action].get('environment_before')
            restored, detail = ((True, '') if snapshot is None
                                else _restore_environment(snapshot))
            _runs[action]['returncode'] = rc
            _runs[action]['environment_restored'] = restored
            _runs[action]['state'] = 'cancelled' if restored else 'error'
            _persist(
                action,
                state='cancelled' if restored else 'error',
                result={
                    'returncode': rc,
                    'cancel_requested': True,
                    'child_pid': getattr(_runs[action].get('process'), 'pid', None),
                    'child_identity': _runs[action].get('child_identity'),
                    'environment_before': snapshot,
                    'environment_restored': restored,
                },
                error=('installer cancelled; the pre-install environment was restored'
                       if restored else f'installer cancellation recovery failed: {detail}'),
                error_code=('cancelled' if restored else 'installer_recovery_failed'))
            _persisted_progress.pop(action, None)
            return
        _runs[action]['returncode'] = rc
        _runs[action]['state'] = 'success' if rc == 0 else 'error'
        _persist(action, state='done' if rc == 0 else 'error',
                 result={
                     'returncode': rc,
                     'child_pid': getattr(_runs[action].get('process'), 'pid', None),
                     'child_identity': _runs[action].get('child_identity'),
                     'environment_before': _runs[action].get('environment_before'),
                 },
                 error=None if rc == 0 else f'installer exited with status {rc}',
                 error_code=None if rc == 0 else 'nonzero_exit')
        _persisted_progress.pop(action, None)
        if action in _IMPORT_CACHE_ACTIONS and rc == 0:
            try:
                capabilities.clear_import_cache()
            except Exception:
                # never downgrade a successful install; surface at debug only
                logger.debug('clear_import_cache failed after %s', action, exc_info=True)
        if action in _KLEIN_DOWNLOADS and rc == 0:
            # The training-base/model listers cache their scans 5 min — a freshly
            # downloaded model must show up on the next probe, not in 5 minutes.
            try:
                from .utils import comfyui
                comfyui.clear_model_caches()
            except Exception:
                logger.debug('clear_model_caches failed after %s', action, exc_info=True)
    except InstallerCancelled:
        snapshot = _runs[action].get('environment_before')
        restored, detail = ((True, '') if snapshot is None
                            else _restore_environment(snapshot))
        _runs[action]['returncode'] = None
        _runs[action]['environment_restored'] = restored
        _runs[action]['state'] = 'cancelled' if restored else 'error'
        _persist(
            action,
            state='cancelled' if restored else 'error',
            result={'returncode': None, 'cancel_requested': True,
                    'environment_before': snapshot,
                    'environment_restored': restored},
            error=('installer cancelled; the pre-install environment was restored'
                   if restored else f'installer cancellation recovery failed: {detail}'),
            error_code='cancelled' if restored else 'installer_recovery_failed')
        _persisted_progress.pop(action, None)
    except Exception as e:  # never let a worker thread die silently
        _append(action, f'error: {e}')
        _runs[action]['returncode'] = -1
        _runs[action]['state'] = 'error'
        _persist(action, state='error', result={'returncode': -1},
                 error=str(e), error_code='installer_exception')
        _persisted_progress.pop(action, None)


def _run_ml_extras(action) -> int:
    """Generic `pip install -r` worker (name kept for existing callers/tests):
    serves ml_extras AND scrape_extras via _PIP_REQUIREMENTS."""
    # The reviewed ML graph is supported on Python 3.11–3.12;
    # on a newer interpreter pip source-builds and fails with a cryptic numpy
    # conflict. Lead the log with a plain-English explanation + the fix so the
    # traceback that follows is already contextualized. (scrape_extras is pure
    # Python — no such ceiling — so it's exempt.)
    if action == 'ml_extras':
        ps = capabilities.python_ml_status()
        if not ps['ml_supported']:
            for line in (
                '=' * 64,
                f"NOTE: this app runs on Python {ps['version']}, but the ML extras",
                f"need Python {ps['ml_range']} (insightface / rembg / onnxruntime",
                "publish no wheels for newer versions → pip will try to BUILD them",
                "from source and the install will likely fail below.",
                "",
                "These extras are OPTIONAL — they only add face-resemblance scoring",
                "and background masking. You can:",
                "  1. Skip them (the app works without them), or",
                "  2. Install them into a separate Python 3.11/3.12 venv and set",
                "     face_scoring.python + masks.python to it in Settings.",
                '=' * 64,
            ):
                _append(action, line)
    proc = _spawn_owned(action,
        [sys.executable, '-m', 'pip', 'install', '-r',
         str(_PIP_REQUIREMENTS.get(action, _ML_REQUIREMENTS))])
    for line in proc.stdout:
        _append(action, line)
    proc.wait()
    return proc.returncode


def _run_watermark_inpaint(action) -> int:
    """Install the dependencies for the repository's LaMa adapter into the
    interpreter the LaMa wrapper resolves — NOT
    necessarily this app's venv (the ML extras can live in a separate 3.11–3.12
    env pointed to by watermark.python/masks.python). Versions are read from
    requirements-ml.txt and the same file is used as a constraint."""
    python = _watermark_python()
    specs = [_requirement_spec(p)
             for p in _CAPABILITY_PACKAGES['watermark_inpaint']]
    _append(action, f'target interpreter: {python}')
    _append(action, f"installing {', '.join(specs)}  (constraints: requirements-ml.txt)")
    proc = _spawn_owned(action,
        [python, '-m', 'pip', 'install', *specs, '-c', str(_ML_REQUIREMENTS)],
    )
    for line in proc.stdout:
        _append(action, line)
    proc.wait()
    return proc.returncode


def _run_ml_capability(action) -> int:
    """Install JUST the packages ONE ML capability needs (face_scoring | masks)
    into the interpreter that capability's probe resolves — so a user can install
    or REPAIR a single feature without the monolithic `-r requirements-ml.txt`.
    Versions come solely from requirements-ml.txt (via _requirement_spec) and that
    file rides along as a `-c` constraint so every scoped install uses the same
    reviewed dependency graph.
    Same shape as _run_watermark_inpaint (resolved ML python, -c constraint)."""
    python = _capability_python(action)
    specs = [_requirement_spec(p) for p in _CAPABILITY_PACKAGES[action]]
    # The reviewed ML graph is supported on Python 3.11–3.12.
    # When targeting THIS interpreter (no dedicated env) and it's out of range,
    # lead with the plain-English reason so the pip source-build failure below is
    # already contextualised — same courtesy the monolithic ml_extras worker gives.
    if action == 'face_scoring' and python == sys.executable:
        ps = capabilities.python_ml_status()
        if not ps['ml_supported']:
            _append(action, f"NOTE: Python {ps['version']} is outside the ML wheel "
                            f"range {ps['ml_range']} — insightface has no wheel here, "
                            "so pip will try to build it and likely fail. Install into a "
                            "separate 3.11/3.12 env and set face_scoring.python instead.")
    _append(action, f'target interpreter: {python}')
    _append(action, f"installing {', '.join(specs)}  (constraints: requirements-ml.txt)")
    proc = _spawn_owned(action,
        [python, '-m', 'pip', 'install', *specs, '-c', str(_ML_REQUIREMENTS)],
    )
    for line in proc.stdout:
        _append(action, line)
    proc.wait()
    return proc.returncode


def _run_klein_download(action) -> int:
    """Stream one Klein asset into the validated ComfyUI tree. Writes to a .part
    file then renames (a killed download never leaves a half file the model
    scanners would pick up). Progress lines land in the ring log (~every 512 MB).
    Gated repo without credentials -> actionable recovery steps, rc 1."""
    spec = _KLEIN_DOWNLOADS[action]
    dest = _klein_dest_path(action)
    if os.path.isfile(dest):
        if _valid_safetensors(dest):
            _append(action, f'already present: {dest}')
            return 0
        _append(action, f'removing invalid existing model: {dest}')
        os.remove(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    headers = {}
    token = cfg.secret('HF_TOKEN')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    _append(action, f"downloading {spec['url']}")
    _append(action, f'-> {dest}')
    part = dest + '.part'
    try:
        with requests.get(spec['url'], stream=True, timeout=(10, 120),
                          headers=headers, allow_redirects=True) as resp:
            if resp.status_code in (401, 403):
                if spec.get('gated'):
                    _append(action, f'HTTP {resp.status_code} - this repository is license-gated.')
                    _append(action, f"1. Open {spec['license_url']} and accept the agreement (free)")
                    _append(action, '2. Create a read token at https://huggingface.co/settings/tokens')
                    _append(action, '3. Paste it as HF_TOKEN in Settings -> API keys, then retry')
                    _append(action, '   (or download the file manually into the folder above)')
                else:
                    _append(action, f'HTTP {resp.status_code}')
                return 1
            if resp.status_code >= 400:
                _append(action, f'HTTP {resp.status_code}')
                return 1
            total = int(resp.headers.get('content-length') or 0)
            done = 0
            next_mark = 0
            _set_progress(action, 0, total)   # show the bar from the first byte
            with open(part, 'wb') as fh:
                for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    _set_progress(action, done, total)   # live % for the UI bar (every chunk)
                    if done >= next_mark:                 # coarse milestone in the text log
                        pct = f' ({done * 100 // total}%)' if total else ''
                        _append(action, f'{done / 1e9:.2f} / {total / 1e9:.2f} GB{pct}')
                        next_mark = done + 512 * 1024 * 1024
                fh.flush()
                os.fsync(fh.fileno())
        if total and done != total:
            _append(action, f'download length mismatch ({done}/{total} bytes) - retry')
            os.remove(part)
            return 1
        if not _valid_safetensors(part):
            _append(action, 'download is not a valid safetensors file - retry')
            os.remove(part)
            return 1
        os.replace(part, dest)
        try:
            directory = os.open(os.path.dirname(dest), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
        _append(action, f'done -> {dest}')
        return 0
    except requests.RequestException as e:
        _append(action, f'network error: {e}')
        try:
            os.remove(part)
        except OSError:
            pass
        return 1


def _valid_safetensors(path) -> bool:
    """Perform bounded structural validation before model bytes become visible."""
    try:
        size = os.path.getsize(path)
        if size < 10:
            return False
        with open(path, 'rb') as handle:
            header_size = int.from_bytes(handle.read(8), 'little')
            if header_size <= 1 or header_size > min(16 * 1024 * 1024, size - 8):
                return False
            header = json.loads(handle.read(header_size).decode('utf-8'))
        return isinstance(header, dict)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _run_ollama_model(action) -> int:
    url = (cfg.get('ollama.url') or '').rstrip('/')
    model = cfg.get('ollama.vision_model') or ''
    resp = requests.post(f'{url}/api/pull', json={'name': model, 'stream': True},
                         stream=True, timeout=(10, 120))
    if resp.status_code >= 400:
        _append(action, f'HTTP {resp.status_code}')
        return 1
    for line in resp.iter_lines():
        if line:
            _append(action, line.decode('utf-8', 'replace') if isinstance(line, bytes) else str(line))
    return 0


_WORKERS = {**{a: _run_ml_extras for a in _PIP_REQUIREMENTS},   # ml_extras + scrape_extras
            'ollama_model': _run_ollama_model,
            **{a: _run_ml_capability for a in _CAPABILITY_ML_ACTIONS},  # face_scoring + masks
            'watermark_inpaint': _run_watermark_inpaint,
            **{a: _run_klein_download for a in _KLEIN_DOWNLOADS}}
# Structural invariant: every whitelisted action MUST have a worker — a missing
# entry surfaces as a cryptic "error: '<action>'" KeyError at runtime (live
# repro: scrape_extras was added to INSTALL_ACTIONS but not here).
assert set(INSTALL_ACTIONS) == set(_WORKERS), \
    f'INSTALL_ACTIONS/_WORKERS mismatch: {set(INSTALL_ACTIONS) ^ set(_WORKERS)}'
