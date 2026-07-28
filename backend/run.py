import sys
import os


def _recover_interrupted_update():
    """Fallback for direct ``python backend/run.py`` launches.

    Supported launchers execute the private pre-update bootstrap before reaching
    this mutable checkout. This call keeps direct developer launches recoverable.
    """
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    data_dir = Path(os.environ.get('LDS_DATA_DIR', str(repo_root / 'data')))
    try:
        private_bootstrap = data_dir / 'update-recovery.py'
        if private_bootstrap.is_file():
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                '_lds_private_update_recovery', private_bootstrap)
            if spec is None or spec.loader is None:
                raise ImportError('private recovery bootstrap cannot be loaded')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            recover = module.recover
        else:
            from update_recovery import recover
        recover(
            repo_root, data_dir, python=sys.executable,
            restart_nonce=os.environ.get('LDS_RESTART_NONCE'))
    except Exception as exc:
        print(f'[LDS] interrupted update recovery failed: {exc}', file=sys.stderr, flush=True)
        raise SystemExit(70) from exc


def _reexec_into_venv():
    """Run on the project's pinned interpreter, not whatever Python launched us.

    If a project .venv exists and we are not already its interpreter, re-exec
    into it before anything else imports. This makes every launch method — the
    start.bat/start.sh flow, a bare `python backend/run.py`, a double-click, an
    IDE, a shell with a newer Python first on PATH — converge on the SAME
    interpreter. That is what lets the optional ML extras (InsightFace, rembg,
    ONNX Runtime and Torch, reviewed for CPython 3.11-3.12) install into
    a supported Python: the in-app installer and the capability probes both key
    off sys.executable, so if run.py runs on e.g. the machine's default 3.14 the
    extras can never install. Skipped for the frozen/portable build (it bundles
    its own Python) and once we are already the venv's python. Set
    LDS_NO_REEXEC=1 to opt out."""
    if getattr(sys, 'frozen', False) \
            or os.environ.get('LDS_REEXEC') == '1' \
            or os.environ.get('LDS_NO_REEXEC') == '1':
        return
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in (('.venv', 'Scripts', 'python.exe'), ('.venv', 'bin', 'python')):
        venv_py = os.path.join(repo_root, *rel)
        if os.path.exists(venv_py):
            break
    else:
        return                                   # no venv -> nothing to switch to
    try:
        if os.path.samefile(venv_py, sys.executable):
            return                               # already the venv interpreter
    except OSError:
        if os.path.normcase(os.path.realpath(venv_py)) \
                == os.path.normcase(os.path.realpath(sys.executable)):
            return
    os.environ['LDS_REEXEC'] = '1'               # loop guard for the re-exec'd child
    print(f"[LDS] re-launching under the project venv: {venv_py}", flush=True)
    os.execv(venv_py, [venv_py, os.path.abspath(__file__), *sys.argv[1:]])


_reexec_into_venv()
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from pathlib import Path  # noqa: E402 - re-exec must happen before project imports
from process_lock import (  # noqa: E402 - path is inserted after the re-exec
    AlreadyRunning, acquire as acquire_process_lock)

_repo_root = Path(__file__).resolve().parent.parent
_data_dir = Path(os.environ.get('LDS_DATA_DIR', str(_repo_root / 'data')))
try:
    # Keep the handle alive for the lifetime of this process. The OS releases
    # the lock automatically on exit or updater re-exec.
    _server_instance_lock = acquire_process_lock(_data_dir)
except AlreadyRunning as exc:
    print(f'[LDS] {exc}', file=sys.stderr, flush=True)
    raise SystemExit(73) from exc

_recover_interrupted_update()

from app import create_app  # noqa: E402 - recovery must precede app import

try:
    from app.config import get as cfg_get
except ImportError:
    def cfg_get(key, default=None):
        return {'server.host': '127.0.0.1', 'server.port': 5050}.get(
            key, default)

app = create_app({'PROCESS_LOCK_HANDLE': _server_instance_lock})


def _arm_update_readiness_deadline(timeout=90):
    """Fail the replacement process if its exact update handoff is never ready."""
    nonce = os.environ.get('LDS_RESTART_NONCE')
    if not nonce:
        return
    import json
    import threading
    import time

    def watchdog():
        time.sleep(timeout)
        journal = _data_dir / 'update-transaction.json'
        try:
            payload = json.loads(journal.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if (payload.get('state') == 'awaiting_restart'
                and payload.get('restart_nonce') == nonce):
            print('[LDS] updated process did not acknowledge readiness; rolling back',
                  file=sys.stderr, flush=True)
            os._exit(70)

    threading.Thread(
        target=watchdog, name='update-readiness-deadline', daemon=True).start()


_arm_update_readiness_deadline()

if __name__ == '__main__':
    host = os.environ.get('LDS_HOST') or cfg_get('server.host')
    port = int(os.environ.get('LDS_PORT') or cfg_get('server.port'))
    is_lan = host not in ('127.0.0.1', 'localhost', '::1')
    if is_lan and cfg_get('server.require_token') \
            and not os.environ.get('LDS_ACCESS_TOKEN') \
            and os.environ.get('LDS_ALLOW_UNAUTHENTICATED') != '1':
        # Token gate is ON (opt-in in Settings): make sure netguard has a token to
        # check. Persisted in config.json (not just this process's env) so it
        # survives a restart instead of rotating every boot -- the Settings
        # "Server" card reads it back from there to show/copy it.
        token = cfg_get('server.access_token') or ''
        if not token:
            import secrets
            token = secrets.token_urlsafe(24)
            try:
                from app.config import save_config
                save_config({'server': {'access_token': token}})
            except ImportError:
                pass   # config module unavailable (see cfg_get fallback above) -> ephemeral this run
        os.environ['LDS_ACCESS_TOKEN'] = token
        print(f"\n[LDS] server.host={host} reachable from the network -> access token REQUIRED.")
        print(f"[LDS] Open from another device:  http://<this-machine>:{port}/remote-login")
        print("[LDS] Copy the token from Settings -> Server on this computer. It is never put in a URL.")
        print("[LDS] (turn the token off in Settings -> Server only for an explicitly trusted network)\n")
    elif is_lan:
        print(f"\n[LDS] server.host={host} reachable from the network (no token — trusted-LAN mode).")
        print(f"[LDS] Open from another device:  http://<this-machine>:{port}/\n")
    # Snapshot of what's ACTUALLY bound, for the Settings "Server" card: config.json
    # may already hold newer values the user saved but hasn't restarted into yet, so
    # reading cfg_get again there would lie about what's currently serving requests.
    app.config['LDS_BOUND_HOST'] = host
    app.config['LDS_BOUND_PORT'] = port
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1',
            host=host,
            # LDS_PORT wins over config so the launcher can dodge a busy port
            # (macOS AirPlay, another Flask app, …) without touching config.json.
            port=port, threaded=True, use_reloader=False)
