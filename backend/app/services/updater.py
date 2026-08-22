"""In-app self-update for GIT checkouts: report how many commits behind origin the
working tree is, `git pull --ff-only`, reinstall deps only if requirements changed,
then relaunch the server.

Only meaningful for a git checkout. A packaged build (the portable bundle) has no
`.git`, so `is_git_checkout()` is False and the caller falls back to the releases
page — a running bundle can't safely overwrite its own locked exe/dlls anyway.
`git` must be on PATH; if it isn't we say so rather than fail cryptically (a clone
user has git by definition, so this only bites an unusual setup).
"""
from __future__ import annotations

import os
import hashlib
import importlib.metadata
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import DEFAULT_UPDATE_REPO, REPO_ROOT, get as _cfg_get

_GIT_TIMEOUT = 120
_UPDATE_LOCK = threading.Lock()
_RESTART_ACK_LOCK = threading.Lock()
RESTART_EXIT_CODE = 75
logger = logging.getLogger(__name__)


def _fsync_directory(path: Path) -> None:
    """Persist a directory metadata update where the platform supports it."""
    if os.name == 'nt':
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, data: bytes, *, sync_dir: bool = True) -> None:
    """Publish `path` in one step: write a private sibling temporary, fsync it,
    then rename over the target.

    This module's whole job is surviving a crash mid-update, so the sequence is
    stated ONCE and every durable write in the file goes through it. The
    temporary is the target's own name plus '.tmp', so an interrupted write
    leaves an obviously-partial file beside its target rather than a plausible
    one. `sync_dir=False` is for a caller publishing SEVERAL files into a single
    directory: it fsyncs that directory once at the end instead of per file.
    """
    temporary = path.with_name(path.name + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    if sync_dir:
        _fsync_directory(path.parent)


def _atomic_write_json(path: Path, payload, *, sync_dir: bool = True,
                       **dump_kwargs) -> None:
    """As `_atomic_write_bytes`, for one JSON document.

    Serialization kwargs stay at the CALL SITE deliberately: `boot-bundle.json`
    is read back and hashed by the launcher, so normalizing its encoding here
    would invalidate every manifest already on disk."""
    _atomic_write_bytes(path, json.dumps(payload, **dump_kwargs).encode('utf-8'),
                        sync_dir=sync_dir)


def _journal_path(root: Path) -> Path:
    data_dir = Path(os.environ.get('LDS_DATA_DIR', str(root / 'data')))
    return data_dir / 'update-transaction.json'


def _write_journal(root: Path, payload: dict) -> None:
    path = _journal_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
    _atomic_write_json(path, payload, indent=2)


def _clear_journal(root: Path) -> bool:
    try:
        path = _journal_path(root)
        path.unlink()
        _fsync_directory(path.parent)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def acknowledge_restart_readiness(nonce: str, root: Path = REPO_ROOT) -> bool:
    """Publish and re-observe the exact replacement's durable ready receipt."""
    with _RESTART_ACK_LOCK:
        path = _journal_path(root)
        try:
            journal = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            journal = None
        except (OSError, ValueError):
            return False
        if not nonce:
            return False
        # 'awaiting_restart' and 'committed' are checked IDENTICALLY — same nonce,
        # same HEAD. The only difference is that the first still has to promote the
        # journal; stating the shared checks once means the two answers cannot drift.
        if journal and journal.get('state') in ('awaiting_restart', 'committed'):
            if nonce != journal.get('restart_nonce'):
                return False
            try:
                current = (_git(root, 'rev-parse', 'HEAD').stdout or '').strip()
            except (OSError, subprocess.SubprocessError):
                return False
            if current != journal.get('target'):
                return False
            if journal['state'] == 'awaiting_restart':
                journal['state'] = 'committed'
                journal['ready_at'] = datetime.now(timezone.utc).isoformat()
                try:
                    _write_journal(root, journal)
                except OSError:
                    return False

        # Manual restarts have no update transaction. Keep their exact process
        # identity durable too, and do not consume either receipt on observation.
        receipt = path.with_name('restart-readiness.json')
        payload = {'restart_nonce': nonce,
                   'ready_at': datetime.now(timezone.utc).isoformat()}
        try:
            receipt.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(receipt, payload, sort_keys=True)
        except OSError:
            return False
        return True


def _install_recovery_bootstrap(root: Path) -> tuple[bool, str]:
    """Persist recovery and launch code outside the checkout before mutation."""
    sources = (
        (root / 'backend' / 'update_recovery.py', 'update-recovery.py'),
        (root / 'backend' / 'source_launcher.py', 'source-launcher.py'),
    )
    try:
        directory = _journal_path(root).parent
        directory.mkdir(parents=True, exist_ok=True)
        for source, name in sources:
            payload = source.read_bytes()
            compile(payload, str(source), 'exec')
            # The manifest below is written LAST and syncs the directory for the
            # whole bundle, so the code files skip their own directory fsync.
            _atomic_write_bytes(directory / name, payload, sync_dir=False)
        manifest = {
            'version': 1,
            'files': {
                name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                for _source, name in sources},
        }
        _atomic_write_json(directory / 'boot-bundle.json', manifest, sort_keys=True)
        return True, ''
    except (OSError, SyntaxError) as exc:
        return False, str(exc)


def record_migration_snapshot(database: Path, snapshot: Path,
                              root: Path = REPO_ROOT) -> bool:
    """Attach a verified pre-migration database image to an armed update."""
    path = _journal_path(root)
    try:
        journal = json.loads(path.read_text(encoding='utf-8'))
        if journal.get('state') != 'awaiting_restart':
            return False
        if Path(journal.get('root') or '').resolve() != root.resolve():
            raise OSError('update journal root does not match this checkout')
        current = (_git(root, 'rev-parse', 'HEAD').stdout or '').strip()
        if current != journal.get('target'):
            raise OSError('update journal target does not match this checkout')
        with sqlite3.connect(f'file:{snapshot}?mode=ro', uri=True) as connection:
            if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise OSError('migration snapshot failed SQLite integrity check')
        journal['migration_database_snapshot'] = {
            'database': str(database.resolve()),
            'snapshot': str(snapshot.resolve()),
            'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            'size': snapshot.stat().st_size,
        }
        _write_journal(root, journal)
        return True
    except FileNotFoundError:
        return False
    except (OSError, ValueError, sqlite3.Error):
        logger.exception('could not associate migration snapshot with update journal')
        raise


def _restore_migration_snapshot(journal: dict) -> bool:
    metadata = journal.get('migration_database_snapshot')
    if not metadata:
        return True
    try:
        database = Path(metadata['database'])
        snapshot = Path(metadata['snapshot'])
        expected_hash = str(metadata['sha256'])
        expected_size = int(metadata['size'])
        if snapshot.stat().st_size != expected_size \
                or hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_hash:
            return False
        with sqlite3.connect(f'file:{snapshot}?mode=ro', uri=True) as connection:
            if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                return False
        temporary = database.with_suffix(database.suffix + '.rollback.tmp')
        with snapshot.open('rb') as incoming, temporary.open('wb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        for suffix in ('-wal', '-shm'):
            Path(f'{database}{suffix}').unlink(missing_ok=True)
        temporary.replace(database)
        _fsync_directory(database.parent)
        return True
    except (KeyError, OSError, ValueError, sqlite3.Error):
        return False


def _cleanup_migration_snapshot(journal: dict) -> bool:
    metadata = journal.get('migration_database_snapshot')
    if not metadata:
        return True
    try:
        Path(metadata['snapshot']).unlink(missing_ok=True)
        return True
    except (KeyError, OSError, TypeError):
        return False


def _run_checked(command, *, cwd, timeout=900, env=None):
    """Run an updater verification/install step and retain bounded diagnostics."""
    try:
        result = subprocess.run(command, cwd=str(cwd), capture_output=True,
                                text=True, timeout=timeout, env=env)
        log = ((result.stdout or '') + (result.stderr or '')).strip()[-3000:]
        return result.returncode == 0, log
    except subprocess.TimeoutExpired as exc:
        return False, f'command timed out after {timeout}s: {exc}'
    except OSError as exc:
        return False, str(exc)


def _canonical_package_name(value: str) -> str:
    return re.sub(r'[-_.]+', '-', str(value).strip()).lower()


def _installed_distributions(value):
    """Map canonical package name -> ``value(dist)`` for every installed
    distribution that reports a name.

    Deliberately NOT cached, and deliberately re-called around every pip run:
    the whole point of the three call sites is comparing the environment BEFORE
    a resolver run with the environment AFTER it. What is shared here is the
    canonicalisation and the nameless-distribution skip, so the before/after
    sets are always keyed the same way and can be compared directly."""
    return {
        _canonical_package_name(dist.metadata.get('Name') or ''): value(dist)
        for dist in importlib.metadata.distributions()
        if dist.metadata.get('Name')
    }


def _python_dependency_change(changed_names) -> bool:
    """Whether an incoming change set touches the Python dependency inputs.

    The forward path decides whether to snapshot and reinstall from this; the
    rollback path decides whether to REVERSE that install from it. Stated twice,
    the two could disagree and leave the interpreter reinstalled but never
    restored — so they read the same predicate."""
    return any(name == 'pyproject.toml' or name.startswith('backend/requirements')
               for name in changed_names)


def _frontend_dependency_change(changed_names) -> bool:
    """Whether an incoming change set touches the front-end lockfile inputs.
    Paired with `_python_dependency_change`; same forward/rollback reasoning."""
    return any(name in ('frontend/package.json', 'frontend/pnpm-lock.yaml')
               for name in changed_names)


def _frontend_source_change(changed_names) -> bool:
    """Whether any front-end SOURCE changed — that is, anything under
    ``frontend/`` other than the built bundle.

    Kept separate from `_frontend_dependency_change` on purpose: forward
    verification rebuilds on any source change, while rollback only reinstalls
    when the lockfile itself moved. That asymmetry is intended, so the two
    questions stay two functions."""
    return any(name.startswith('frontend/') and not name.startswith('frontend/dist/')
               for name in changed_names)


def _pip_environment_snapshot() -> tuple[dict | None, str]:
    """Capture enough state to restore the interpreter exactly after a failed
    resolver run. Requirements files alone cannot remove newly-added transitive
    packages, so rollback keeps both a replayable freeze and the original set of
    installed distribution names."""
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'freeze', '--all'],
            capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout or 'pip freeze failed').strip()[-1500:]
    frozen = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    packages = _installed_distributions(lambda dist: dist.version)
    return {'freeze': frozen, 'packages': packages}, ''


def _restore_python_environment(root: Path, snapshot: dict,
                                logs: list[str]) -> bool:
    """Replay exact versions and remove distributions introduced by the failed
    update. This reconciles both upgrades/downgrades and resolver-added extras."""
    frozen = snapshot.get('freeze') if isinstance(snapshot, dict) else None
    original = snapshot.get('packages') if isinstance(snapshot, dict) else None
    if not isinstance(frozen, list) or not isinstance(original, dict):
        logs.append('Python environment snapshot is missing or invalid.')
        return False
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', prefix='lds-pip-rollback-',
                suffix='.txt', delete=False) as handle:
            handle.write('\n'.join(str(line) for line in frozen))
            handle.write('\n')
            requirements = Path(handle.name)
        try:
            ok, output = _run_checked(
                [sys.executable, '-m', 'pip', 'install', '-q', '-r',
                 str(requirements)], cwd=root)
        finally:
            try:
                requirements.unlink()
            except OSError:
                pass
    except OSError as exc:
        logs.append(f'could not stage Python rollback requirements: {exc}')
        return False
    if output:
        logs.append(output)
    if not ok:
        return False
    current = _installed_distributions(lambda dist: dist.metadata.get('Name') or '')
    extras = sorted(current[name] for name in current if name not in original)
    if extras:
        ok, output = _run_checked(
            [sys.executable, '-m', 'pip', 'uninstall', '-y', *extras], cwd=root)
        if output:
            logs.append(output)
        if not ok:
            return False
    # Verify the final set and versions, not merely pip's return code.
    final = _installed_distributions(lambda dist: dist.version)
    expected = {_canonical_package_name(name): str(version)
                for name, version in original.items()}
    if final != expected:
        missing = sorted(set(expected) - set(final))
        unexpected = sorted(set(final) - set(expected))
        mismatched = sorted(name for name in set(final) & set(expected)
                            if final[name] != expected[name])
        logs.append('Python rollback verification failed: '
                    f'missing={missing[:12]}, unexpected={unexpected[:12]}, '
                    f'version_mismatch={mismatched[:12]}')
        return False
    return True


def _requirement_lines(path: Path) -> dict[str, str]:
    requirements = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return requirements
    for raw in lines:
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith(('-', 'http:', 'https:')):
            continue
        name = re.split(r'[<>=!~;\[\s@]', line, maxsplit=1)[0]
        if name:
            requirements[_canonical_package_name(name)] = line
    return requirements


def _ml_python_supported() -> bool:
    """Whether this app interpreter can safely receive the reviewed ML graph."""
    from ..capabilities import python_ml_status
    return bool(python_ml_status()['ml_supported'])


def _optional_python_install_commands(root: Path, changed_names: list[str],
                                      snapshot: dict) -> list[list[str]]:
    """Update optional features that were already installed without silently
    installing unrelated heavyweight capabilities."""
    installed = {_canonical_package_name(name)
                 for name in (snapshot.get('packages') or {})}
    commands = []
    scrape_path = root / 'backend' / 'requirements-scrape.txt'
    if 'backend/requirements-scrape.txt' in changed_names:
        scrape = _requirement_lines(scrape_path)
        if set(scrape) & installed:
            commands.append([sys.executable, '-m', 'pip', 'install', '-q',
                             '-r', str(scrape_path)])

    ml_path = root / 'backend' / 'requirements-ml.txt'
    if ('backend/requirements-ml.txt' in changed_names
            and _ml_python_supported()):
        ml = _requirement_lines(ml_path)
        # Mirrors setup_installer's scoped capability ownership. The sentinel
        # prevents an insightface-only user from unexpectedly pulling torch/LaMa.
        groups = {
            'insightface': ('insightface', 'onnxruntime', 'numpy',
                            'opencv-python-headless'),
            'rembg': ('rembg', 'onnxruntime', 'numpy',
                      'opencv-python-headless', 'pillow'),
            'torch': ('torch', 'numpy', 'opencv-python-headless', 'pillow'),
        }
        selected = []
        for sentinel, names in groups.items():
            if sentinel in installed:
                selected.extend(ml[name] for name in names if name in ml)
        selected = list(dict.fromkeys(selected))
        if selected:
            # The former LaMa convenience package pins Pillow below 10. Remove
            # that obsolete constraint before installing the in-repo adapter's
            # reviewed runtime. The updater's exact snapshot restores it if any
            # later install or verification step rolls back.
            if 'simple-lama-inpainting' in installed:
                commands.append([sys.executable, '-m', 'pip', 'uninstall', '-y',
                                 'simple-lama-inpainting'])
            commands.append([sys.executable, '-m', 'pip', 'install', '-q',
                             *selected, '-c', str(ml_path)])
    return commands


def _pnpm_command(root: Path):
    """Return the project-pinned pnpm launcher without silently changing tools."""
    package = root / 'frontend' / 'package.json'
    try:
        manager = json.loads(package.read_text(encoding='utf-8')).get('packageManager', '')
    except (OSError, ValueError):
        manager = ''
    version = manager.split('@', 1)[1] if manager.startswith('pnpm@') else ''
    corepack = shutil.which('corepack')
    if corepack and version:
        return [corepack, f'pnpm@{version}']
    pnpm = shutil.which('pnpm')
    return [pnpm] if pnpm else None


def _tree_manifest(directory: Path) -> dict[str, str]:
    """Return a deterministic content manifest and reject unsafe build links."""
    manifest = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise OSError(f'build output contains a symbolic link: {path}')
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _verify_frontend_bundle(root: Path) -> tuple[bool, str]:
    index = root / 'frontend' / 'dist' / 'index.html'
    if not index.is_file() or not index.read_bytes().strip():
        return False, 'The update did not include a usable frontend/dist/index.html.'
    return True, ''


def _verify_frontend(root: Path, pnpm: list[str], logs: list[str]) -> tuple[bool, str]:
    """Run source gates and prove the checked-in bundle was built from them."""
    for script in ('lint', 'typecheck', 'test'):
        ok, output = _run_checked(
            [*pnpm, '--dir', 'frontend', 'run', script], cwd=root, timeout=900)
        if output:
            logs.append(output)
        if not ok:
            return False, f'Frontend {script} verification failed.'

    bundle_ok, bundle_reason = _verify_frontend_bundle(root)
    if not bundle_ok:
        return False, bundle_reason
    committed = root / 'frontend' / 'dist'
    try:
        with tempfile.TemporaryDirectory(prefix='lds-update-frontend-') as temporary:
            built = Path(temporary)
            ok, output = _run_checked(
                [*pnpm, '--dir', 'frontend', 'exec', 'vite', 'build',
                 '--outDir', str(built), '--emptyOutDir'],
                cwd=root, timeout=900)
            if output:
                logs.append(output)
            if not ok:
                return False, 'Updated frontend sources failed to build.'
            if _tree_manifest(built) != _tree_manifest(committed):
                return False, ('Updated frontend sources do not match the committed '
                               'frontend/dist bundle.')
    except OSError as exc:
        return False, f'Could not verify the frontend build: {exc}'
    return True, ''


def _verify_app_startup(root: Path, logs: list[str]) -> tuple[bool, str]:
    """Initialize the updated app against a safe copy of current local state."""
    with tempfile.TemporaryDirectory(prefix='lds-update-smoke-') as temporary:
        temp = Path(temporary)
        smoke_data = temp / 'data'
        smoke_data.mkdir()
        live_data = Path(os.environ.get('LDS_DATA_DIR', str(root / 'data')))
        live_database = live_data / 'studio.db'
        if live_database.is_file():
            try:
                # SQLite's backup API produces a transactionally consistent
                # snapshot even while the live WAL-backed app is serving.
                with sqlite3.connect(f'file:{live_database}?mode=ro', uri=True) as source:
                    with sqlite3.connect(smoke_data / 'studio.db') as destination:
                        source.backup(destination)
            except sqlite3.Error as exc:
                return False, f'Could not safely copy the current database: {exc}'
        env = dict(os.environ)
        env.update({
            'LDS_DATA_DIR': str(smoke_data),
            'LDS_CONFIG': str(temp / 'config.json'),
            'LDS_ENV': str(temp / '.env'),
            'LDS_NO_REEXEC': '1',
        })
        code = (
            "import sys; sys.path.insert(0, 'backend'); "
            "from app import create_app; "
            "from app.update_selftest import run; "
            "app=create_app({'TESTING': True}); "
            "run(app)"
        )
        ok, output = _run_checked(
            [sys.executable, '-c', code], cwd=root, timeout=240, env=env)
        if output:
            logs.append(output)
        if not ok:
            return False, 'Updated application failed isolated startup/readiness verification.'
    return True, ''


def _rollback_update(root: Path, before: str, journal: dict, reason: str,
                     logs: list[str]) -> dict:
    journal.update(state='rolling_back', failure=reason)
    try:
        _write_journal(root, journal)
    except OSError as exc:
        logs.append(f'could not update recovery journal: {exc}')
    # The updater starts only from a clean checkout, but a user or editor can
    # still create a change while dependencies are installing.  Never let an
    # automatic ``reset --hard`` erase work created after the transaction began.
    try:
        status = _git(root, 'status', '--porcelain', '--untracked-files=normal')
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        status = None
        logs.append(f'could not verify rollback safety: {exc}')
    if status is None or status.returncode != 0 or (status.stdout or '').strip():
        journal['state'] = 'rollback_blocked'
        journal['rollback_log'] = (
            'Working tree changed during the update; automatic reset was refused.')
        try:
            _write_journal(root, journal)
        except OSError as exc:
            logs.append(f'could not update recovery journal: {exc}')
        return {'ok': False, 'changed': True, 'rolled_back': False,
                'recovery_required': True,
                'reason': (f'{reason} Automatic rollback was refused because the '
                           'working tree changed; preserve or remove those changes, then restart.'),
                'from': before[:8], 'to': journal.get('target', '')[:8],
                'log': '\n'.join(logs)[-4000:]}
    reset = _git(root, 'reset', '--hard', before)
    reset_log = ((reset.stdout or '') + (reset.stderr or '')).strip()
    if reset_log:
        logs.append(reset_log[-1500:])
    if reset.returncode == 0:
        restore_ok = _restore_migration_snapshot(journal)
        # A resolver can fail after partially changing the environment.  Once
        # the old files are restored, re-apply their lock/requirements so code
        # and dependency state converge on the same revision again.
        if journal.get('state_before_rollback') in ('installing_dependencies', 'verifying'):
            changed = journal.get('changed_files') or []
            if _python_dependency_change(changed):
                snapshot = journal.get('python_environment_before')
                if snapshot:
                    restore_ok = (_restore_python_environment(root, snapshot, logs)
                                  and restore_ok)
                else:
                    # Compatibility with journals written by older app versions.
                    req = root / 'backend' / 'requirements.txt'
                    if req.is_file():
                        command = [sys.executable, '-m', 'pip', 'install', '-q']
                        if 'pyproject.toml' in changed:
                            command.extend(['-e', str(root)])
                        command.extend(['-r', str(req)])
                        ok, restore_log = _run_checked(command, cwd=root)
                        restore_ok = restore_ok and ok
                        if restore_log:
                            logs.append(restore_log)
            if _frontend_dependency_change(changed):
                pnpm = _pnpm_command(root)
                if pnpm:
                    ok, restore_log = _run_checked(
                        [*pnpm, '--dir', 'frontend', 'install', '--frozen-lockfile'],
                        cwd=root)
                    restore_ok = restore_ok and ok
                    if restore_log:
                        logs.append(restore_log)
                else:
                    restore_ok = False
        if not restore_ok:
            # Keep the journal.  Startup recovery will retry dependency restore
            # before importing the old revision, rather than declaring success
            # with a checkout/environment mismatch.
            journal.update(
                state='rollback_failed',
                rollback_log='Code was restored, but dependency restoration failed.',
            )
            try:
                _write_journal(root, journal)
            except OSError as exc:
                logs.append(f'could not update recovery journal: {exc}')
            return {'ok': False, 'changed': False, 'rolled_back': True,
                    'environment_restored': False,
                    'recovery_journal_cleared': False,
                    'recovery_required': True,
                    'reason': (f'{reason} Code was restored, but dependencies still '
                               'need recovery; restart the app to retry.'),
                    'from': before[:8], 'to': before[:8],
                    'log': '\n'.join(logs)[-4000:]}
        snapshot_cleaned = _cleanup_migration_snapshot(journal)
        cleared = snapshot_cleaned and _clear_journal(root)
        return {'ok': False, 'changed': False, 'rolled_back': True,
                'environment_restored': restore_ok,
                'recovery_journal_cleared': cleared,
                'reason': reason, 'from': before[:8], 'to': before[:8],
                'log': '\n'.join(logs)[-4000:]}
    journal.update(state='rollback_failed', rollback_log=reset_log[-1500:])
    try:
        _write_journal(root, journal)
    except OSError as exc:
        return {'ok': False, 'changed': False,
                'reason': f'Could not create the private update recovery journal: {exc}'}
    return {'ok': False, 'changed': True, 'rolled_back': False,
            'recovery_required': True,
            'reason': f'{reason} Automatic rollback failed; restart the app to retry recovery.',
            'from': before[:8], 'to': journal.get('target', '')[:8],
            'log': '\n'.join(logs)[-4000:]}


def is_git_checkout(root=None) -> bool:
    return (root or REPO_ROOT).joinpath('.git').exists()


def _git(root, *args, timeout=_GIT_TIMEOUT):
    """Run a git subcommand in `root`. Returns the CompletedProcess (never raises on
    non-zero — callers inspect returncode)."""
    git = shutil.which('git')
    if not git:
        raise FileNotFoundError('git')
    return subprocess.run([git, '-C', str(root), *args],
                          capture_output=True, text=True, timeout=timeout)


def current_sha(root=None):
    """Short SHA of the local checkout — local-only (no fetch), None outside a
    git checkout or when git is unavailable. Lets the passive update check show
    the current build without touching the network."""
    root = root or REPO_ROOT
    if not is_git_checkout(root):
        return None
    try:
        return (_git(root, 'rev-parse', '--short', 'HEAD').stdout or '').strip() or None
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def git_update_status(root=None) -> dict | None:
    """`git fetch` + how many commits behind the upstream branch we are. None when this
    isn't a git checkout (caller then uses the release-tag check). Network/git failures
    degrade to a reason string, never an exception."""
    root = root or REPO_ROOT
    from ..version import APP_VERSION
    if not is_git_checkout(root):
        return None
    base = {'ok': True, 'is_git': True, 'current': APP_VERSION, 'update_available': False}

    def fail(reason: str, **extra) -> dict:
        """Every failure exit is the same three statements; say them once so no
        future branch can set a reason and forget to clear ``ok``."""
        base.update({'ok': False, 'reason': reason, **extra})
        return base

    try:
        branch_result = _git(root, 'rev-parse', '--abbrev-ref', 'HEAD')
        branch = (branch_result.stdout or '').strip()
        if branch_result.returncode != 0 or not branch or branch == 'HEAD':
            return fail('Could not resolve the current git branch.')
        fetch = _git(root, 'fetch', '--quiet', 'origin', branch)
        if fetch.returncode != 0:
            return fail('git fetch failed (offline, or no access to the remote).')
        behind_result = _git(root, 'rev-list', '--count', f'HEAD..origin/{branch}')
        behind = (behind_result.stdout or '').strip()
        local_result = _git(root, 'rev-parse', '--short', 'HEAD')
        remote_result = _git(root, 'rev-parse', '--short', f'origin/{branch}')
        if (behind_result.returncode != 0 or local_result.returncode != 0
                or remote_result.returncode != 0):
            return fail('Could not compare the local and fetched revisions.')
        base['branch'] = branch
        base['current_sha'] = (local_result.stdout or '').strip()
        base['remote_sha'] = (remote_result.stdout or '').strip()
        try:
            n = int(behind)
        except ValueError:
            n = -1
        if n < 0 or not re.fullmatch(r'[0-9a-fA-F]{4,64}', base['current_sha']) \
                or not re.fullmatch(r'[0-9a-fA-F]{4,64}', base['remote_sha']):
            return fail('Git returned an invalid revision comparison.')
        base['behind'] = n
        base['update_available'] = n > 0
        # Links so the user can read WHAT the pending update contains before
        # pulling: a compare view of exactly the incoming commits when behind,
        # else the branch history. Short SHAs work fine in GitHub URLs.
        repo = _cfg_get('updates.repo') or DEFAULT_UPDATE_REPO
        base['repo'] = repo
        base['commits_url'] = f'https://github.com/{repo}/commits/{branch}'
        if n > 0 and base['current_sha'] and base['remote_sha']:
            base['compare_url'] = (f'https://github.com/{repo}/compare/'
                                   f"{base['current_sha']}...{base['remote_sha']}")
    except FileNotFoundError:
        fail('git is not installed / not on PATH — install Git to enable in-app updates.',
             git_missing=True)
    except subprocess.SubprocessError:
        fail('git command timed out.')
    return base


def apply_update(root=None) -> dict:
    if not _UPDATE_LOCK.acquire(blocking=False):
        return {'ok': False, 'reason': 'An update is already in progress.'}
    try:
        return _apply_update_locked(root)
    finally:
        _UPDATE_LOCK.release()


def _apply_update_locked(root=None) -> dict:
    """Apply a verified fast-forward update as a recoverable transaction.

    The live checkout is never touched when it is dirty or diverged.  Once the
    target is resolved, a private journal records the prior revision; any merge,
    dependency, or compile failure resets the checkout to that revision.  The
    journal is marked committed only after every gate passes, so ``run.py`` can
    recover a process crash that occurs mid-update before importing new code.
    """
    root = Path(root or REPO_ROOT)
    if not is_git_checkout(root):
        repo = _cfg_get('updates.repo') or DEFAULT_UPDATE_REPO
        return {'ok': False, 'manual': True,
                'reason': 'This is a packaged build (no git checkout) — download the latest '
                          'release and replace the folder.',
                'url': f'https://github.com/{repo}/releases'}
    logs = []
    try:
        dirty = _git(root, 'status', '--porcelain', '--untracked-files=normal')
        if dirty.returncode != 0:
            return {'ok': False, 'reason': 'Could not inspect the working tree.',
                    'log': ((dirty.stderr or '') + (dirty.stdout or ''))[-1500:]}
        if (dirty.stdout or '').strip():
            return {'ok': False, 'dirty': True,
                    'reason': 'The checkout has local or untracked changes. Commit, stash, '
                              'or remove them before using the in-app updater.'}
        branch = (_git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout or '').strip()
        if not branch or branch == 'HEAD':
            return {'ok': False, 'reason': 'The checkout is detached; switch to a branch before updating.'}
        before = (_git(root, 'rev-parse', 'HEAD').stdout or '').strip()
        fetch = _git(root, 'fetch', '--quiet', 'origin', branch)
        fetch_log = ((fetch.stdout or '') + (fetch.stderr or '')).strip()
        if fetch_log:
            logs.append(fetch_log[-1500:])
        if fetch.returncode != 0:
            return {'ok': False, 'reason': 'git fetch failed; the live checkout was not changed.',
                    'log': '\n'.join(logs)[-1500:]}
        target_result = _git(root, 'rev-parse', f'origin/{branch}')
        target = (target_result.stdout or '').strip()
        if target_result.returncode != 0 or not target:
            return {'ok': False, 'reason': 'Could not resolve the fetched update target.',
                    'log': ((target_result.stderr or '') + (target_result.stdout or ''))[-1500:]}
        if before == target:
            return {'ok': True, 'changed': False, 'from': before[:8], 'to': target[:8],
                    'deps_changed': False, 'verified': True, 'log': '\n'.join(logs)[-1500:]}
        ancestor = _git(root, 'merge-base', '--is-ancestor', before, target)
        if ancestor.returncode != 0:
            return {'ok': False, 'reason': 'The local branch has diverged from origin; '
                                           'the updater only permits fast-forward updates.'}
        names_result = _git(root, 'diff', '--name-only', before, target)
        if names_result.returncode != 0:
            return {'ok': False, 'reason': 'Could not inspect the incoming update.'}
        changed_names = [name.strip() for name in (names_result.stdout or '').splitlines()
                         if name.strip()]
    except FileNotFoundError:
        return {'ok': False, 'reason': 'git is not installed / not on PATH.'}
    except subprocess.SubprocessError:
        return {'ok': False, 'reason': 'git command timed out; the live checkout was not changed.'}

    python_deps = _python_dependency_change(changed_names)
    frontend_deps = _frontend_dependency_change(changed_names)
    frontend_sources = _frontend_source_change(changed_names)
    frontend_bundle = any(name.startswith('frontend/dist/') for name in changed_names)
    python_snapshot = None
    if python_deps:
        python_snapshot, snapshot_error = _pip_environment_snapshot()
        if python_snapshot is None:
            return {'ok': False, 'changed': False,
                    'reason': ('Could not snapshot the current Python environment; '
                               'the live checkout was not changed.'),
                    'log': snapshot_error[-1500:]}
    recovery_ok, recovery_error = _install_recovery_bootstrap(root)
    if not recovery_ok:
        return {'ok': False, 'changed': False,
                'reason': ('Could not install the private update recovery bootstrap; '
                           'the live checkout was not changed.'),
                'log': recovery_error[-1500:]}
    journal = {'version': 2, 'state': 'prepared', 'root': str(root.resolve()),
               'before': before, 'target': target, 'branch': branch,
               'started_at': datetime.now(timezone.utc).isoformat(),
               'changed_files': changed_names,
               'python_environment_before': python_snapshot}
    try:
        _write_journal(root, journal)
    except OSError as exc:
        return {'ok': False, 'changed': False,
                'reason': f'Could not create the private update recovery journal: {exc}'}
    try:
        merge = _git(root, 'merge', '--ff-only', target)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return _rollback_update(root, before, journal,
                                f'Fast-forward update failed: {exc}', logs)
    merge_log = ((merge.stdout or '') + (merge.stderr or '')).strip()
    if merge_log:
        logs.append(merge_log[-1500:])
    if merge.returncode != 0:
        return _rollback_update(root, before, journal,
                                'Fast-forward update failed; the previous revision was restored.', logs)
    journal['state'] = 'installing_dependencies'
    try:
        _write_journal(root, journal)
    except OSError as exc:
        journal['state_before_rollback'] = 'installing_dependencies'
        return _rollback_update(root, before, journal,
                                f'Could not update the recovery journal: {exc}', logs)

    if python_deps:
        req = root / 'backend' / 'requirements.txt'
        core_changed = ('pyproject.toml' in changed_names
                        or 'backend/requirements.txt' in changed_names)
        if core_changed and not req.is_file():
            return _rollback_update(root, before, journal,
                                    'The update changed Python dependencies but removed requirements.txt.', logs)
        commands = []
        if core_changed:
            command = [sys.executable, '-m', 'pip', 'install', '-q']
            if 'pyproject.toml' in changed_names:
                command.extend(['-e', str(root)])
            command.extend(['-r', str(req)])
            commands.append(command)
        commands.extend(_optional_python_install_commands(
            root, changed_names, python_snapshot or {}))
        for command in commands:
            ok, dep_log = _run_checked(command, cwd=root)
            if dep_log:
                logs.append(dep_log)
            if not ok:
                journal['state_before_rollback'] = 'installing_dependencies'
                return _rollback_update(
                    root, before, journal,
                    'Python dependency installation failed; the update was rolled back.',
                    logs)
    if frontend_sources:
        pnpm = _pnpm_command(root)
        if not pnpm:
            journal['state_before_rollback'] = 'installing_dependencies'
            return _rollback_update(root, before, journal,
                                    'The update changed frontend sources but pnpm/Corepack is unavailable.', logs)
        # A source checkout may serve a committed bundle without having local
        # node_modules. Install the pinned graph before verifying any source
        # change; when the lock did not change this is idempotent and needs no
        # old-environment restoration during rollback.
        ok, dep_log = _run_checked(
            [*pnpm, '--dir', 'frontend', 'install', '--frozen-lockfile'], cwd=root)
        if dep_log:
            logs.append(dep_log)
        if not ok:
            journal['state_before_rollback'] = 'installing_dependencies'
            return _rollback_update(root, before, journal,
                                    'Frontend dependency installation failed; the update was rolled back.', logs)

    journal['state'] = 'verifying'
    try:
        _write_journal(root, journal)
    except OSError as exc:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(root, before, journal,
                                f'Could not update the recovery journal: {exc}', logs)
    ok, verify_log = _run_checked(
        [sys.executable, '-m', 'compileall', '-q', str(root / 'backend')],
        cwd=root, timeout=180)
    if verify_log:
        logs.append(verify_log)
    if not ok:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(root, before, journal,
                                'Updated Python sources failed to compile; the update was rolled back.', logs)
    startup_ok, startup_reason = _verify_app_startup(root, logs)
    if not startup_ok:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(root, before, journal,
                                f'{startup_reason} The update was rolled back.', logs)
    # Sources take priority: a rebuild verifies the shipped bundle as a side
    # effect, so there is nothing left for the bundle-only check to add.
    frontend_ok, frontend_reason = True, ''
    if frontend_sources:
        frontend_ok, frontend_reason = _verify_frontend(root, pnpm, logs)
    elif frontend_bundle:
        frontend_ok, frontend_reason = _verify_frontend_bundle(root)
    if not frontend_ok:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(root, before, journal,
                                f'{frontend_reason} The update was rolled back.', logs)
    after = (_git(root, 'rev-parse', 'HEAD').stdout or '').strip()
    if after != target:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(root, before, journal,
                                'Post-update revision verification failed; the update was rolled back.', logs)
    # The replacement process executes this private copy before importing the
    # updated checkout. Refresh it from the verified target so it understands
    # the nonce-bearing awaiting_restart state introduced by that target.
    recovery_ok, recovery_error = _install_recovery_bootstrap(root)
    if not recovery_ok:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(
            root, before, journal,
            'Could not publish the verified restart recovery bootstrap; '
            'the update was rolled back.', logs + [recovery_error])
    restart_nonce = uuid.uuid4().hex
    journal['state'] = 'awaiting_restart'
    journal['restart_nonce'] = restart_nonce
    journal['verified_at'] = datetime.now(timezone.utc).isoformat()
    try:
        _write_journal(root, journal)
    except OSError as exc:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(root, before, journal,
                                f'Could not commit the recovery journal: {exc}', logs)
    return {'ok': True, 'changed': True, 'from': before[:8], 'to': after[:8],
            'deps_changed': bool(python_deps or frontend_deps),
            'python_deps_changed': python_deps,
            'frontend_deps_changed': frontend_deps,
            'frontend_sources_changed': frontend_sources,
            'verified': True, 'restart_nonce': restart_nonce,
            'recovery_journal_cleared': False,
            'log': '\n'.join(logs)[-4000:]}


def schedule_restart(delay: float = 1.2, restart_nonce: str | None = None) -> None:
    """Restart without racing the old server or escaping a portable launcher.

    The portable launcher is the lifetime supervisor.  Its child exits with a
    reserved code and the launcher starts the replacement only after ``wait()``
    confirms that the old process (and its instance lock) are gone.  A source
    checkout has no supervisor, so a tiny detached helper waits for this exact
    PID to disappear before relaunching.  Port availability is deliberately not
    used as the hand-off signal: another process can claim a just-freed port.
    """
    supervised = os.environ.get('LDS_LAUNCHER_SUPERVISED') == '1'
    journal_path = _journal_path(REPO_ROOT)
    try:
        previous = json.loads(journal_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = None
    if (previous and previous.get('state') == 'committed'
            and previous.get('restart_nonce') != restart_nonce
            and not _clear_journal(REPO_ROOT)):
        raise RuntimeError(
            'Could not retire the previous restart receipt; the server remains running')
    if not supervised:
        recovery_ok, recovery_error = _install_recovery_bootstrap(REPO_ROOT)
        if not recovery_ok:
            raise RuntimeError(
                'Could not install the private restart bootstrap; '
                f'the server remains running: {recovery_error}')

    if supervised:
        request_dir = Path(os.environ.get('LDS_DATA_DIR', str(REPO_ROOT / 'data')))
        request_path = request_dir / 'restart-request.json'
        request_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'host': os.environ.get('LDS_HOST') or _cfg_get('server.host') or '127.0.0.1',
            'port': int(os.environ.get('LDS_PORT') or _cfg_get('server.port') or 5050),
        }
        if restart_nonce:
            payload['restart_nonce'] = restart_nonce
        _atomic_write_json(request_path, payload)

        def _exit_for_supervisor():
            import time
            time.sleep(delay)
            os._exit(RESTART_EXIT_CODE)

        threading.Thread(target=_exit_for_supervisor, daemon=True).start()
        return

    # Only the unsupervised path spawns a helper, so its inputs are gathered here
    # rather than above the branch that never reaches them.
    py = sys.executable
    run_py = os.path.abspath(sys.argv[0])
    workdir = os.path.dirname(run_py) or None
    data_dir = str(_journal_path(REPO_ROOT).parent)
    private_launcher = os.path.join(data_dir, 'source-launcher.py')
    parent_pid = os.getpid()

    helper = (
        'import os,time,subprocess\n'
        f'parent={parent_pid!r}\n'
        'for _ in range(240):\n'
        '    try:\n'
        '        os.kill(parent,0)\n'
        '    except OSError:\n'
        '        break\n'
        '    time.sleep(0.25)\n'
        # New visible console for the relaunched server: the helper itself is
        # DETACHED, so a default spawn would leave the server console-less and
        # the old launcher window frozen on stale output.
        'flags=0x00000010 if os.name=="nt" else 0\n'
        'env=dict(os.environ)\n'
        f'env["LDS_RESTART_NONCE"]={restart_nonce!r} or ""\n'
        f'child=subprocess.Popen([{py!r},{private_launcher!r},"--root",'
        f'{str(REPO_ROOT)!r},"--data-dir",{data_dir!r}], cwd={workdir!r}, '
        'creationflags=flags, env=env)\n'
        'child.wait()\n'
    )

    def _spawn_then_exit():
        import time
        time.sleep(delay)
        flags = 0
        if os.name == 'nt':
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
        try:
            subprocess.Popen([py, '-c', helper], cwd=workdir, env=dict(os.environ),
                             creationflags=flags, close_fds=True)
        except OSError:
            logger.exception('could not create restart helper; server remains running')
        else:
            os._exit(0)

    threading.Thread(target=_spawn_then_exit, daemon=True).start()
