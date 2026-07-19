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
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..config import REPO_ROOT, get as _cfg_get

_GIT_TIMEOUT = 120
_UPDATE_LOCK = threading.Lock()
RESTART_EXIT_CODE = 75


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
    tmp = path.with_suffix('.json.tmp')
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def _clear_journal(root: Path) -> bool:
    try:
        _journal_path(root).unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _install_recovery_bootstrap(root: Path) -> tuple[bool, str]:
    """Persist recovery code outside the checkout before git mutates it."""
    source = root / 'backend' / 'update_recovery.py'
    target = _journal_path(root).parent / 'update-recovery.py'
    try:
        payload = source.read_bytes()
        compile(payload, str(source), 'exec')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.py.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
        return True, ''
    except (OSError, SyntaxError) as exc:
        return False, str(exc)


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
    packages = {
        _canonical_package_name(dist.metadata.get('Name') or ''): dist.version
        for dist in importlib.metadata.distributions()
        if dist.metadata.get('Name')
    }
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
    current = {
        _canonical_package_name(dist.metadata.get('Name') or ''):
            (dist.metadata.get('Name') or '')
        for dist in importlib.metadata.distributions()
        if dist.metadata.get('Name')
    }
    extras = sorted(current[name] for name in current if name not in original)
    if extras:
        ok, output = _run_checked(
            [sys.executable, '-m', 'pip', 'uninstall', '-y', *extras], cwd=root)
        if output:
            logs.append(output)
        if not ok:
            return False
    # Verify the final set and versions, not merely pip's return code.
    final = {
        _canonical_package_name(dist.metadata.get('Name') or ''): dist.version
        for dist in importlib.metadata.distributions()
        if dist.metadata.get('Name')
    }
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


def _verify_frontend(root: Path, pnpm: list[str], logs: list[str]) -> tuple[bool, str]:
    """Run source gates and prove the checked-in bundle was built from them."""
    for script in ('lint', 'typecheck', 'test'):
        ok, output = _run_checked(
            [*pnpm, '--dir', 'frontend', 'run', script], cwd=root, timeout=900)
        if output:
            logs.append(output)
        if not ok:
            return False, f'Frontend {script} verification failed.'

    committed = root / 'frontend' / 'dist'
    if not (committed / 'index.html').is_file():
        return False, 'The update did not include a built frontend/dist/index.html.'
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
    """Initialize the updated Flask app against disposable private storage."""
    with tempfile.TemporaryDirectory(prefix='lds-update-smoke-') as temporary:
        temp = Path(temporary)
        env = dict(os.environ)
        env.update({
            'LDS_DATA_DIR': str(temp / 'data'),
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
        restore_ok = True
        # A resolver can fail after partially changing the environment.  Once
        # the old files are restored, re-apply their lock/requirements so code
        # and dependency state converge on the same revision again.
        if journal.get('state_before_rollback') in ('installing_dependencies', 'verifying'):
            changed = journal.get('changed_files') or []
            if any(name == 'pyproject.toml' or name.startswith('backend/requirements')
                   for name in changed):
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
            if any(name in ('frontend/package.json', 'frontend/pnpm-lock.yaml')
                   for name in changed):
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
        cleared = _clear_journal(root)
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
    try:
        branch = (_git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout or '').strip() or 'main'
        fetch = _git(root, 'fetch', '--quiet', 'origin', branch)
        if fetch.returncode != 0:
            base['reason'] = 'git fetch failed (offline, or no access to the remote).'
            return base
        behind = (_git(root, 'rev-list', '--count', f'HEAD..origin/{branch}').stdout or '0').strip()
        base['branch'] = branch
        base['current_sha'] = (_git(root, 'rev-parse', '--short', 'HEAD').stdout or '').strip()
        base['remote_sha'] = (_git(root, 'rev-parse', '--short', f'origin/{branch}').stdout or '').strip()
        try:
            n = int(behind)
        except ValueError:
            n = 0
        base['behind'] = n
        base['update_available'] = n > 0
        # Links so the user can read WHAT the pending update contains before
        # pulling: a compare view of exactly the incoming commits when behind,
        # else the branch history. Short SHAs work fine in GitHub URLs.
        repo = _cfg_get('updates.repo') or 'perfectgf/lora-dataset-studio'
        base['repo'] = repo
        base['commits_url'] = f'https://github.com/{repo}/commits/{branch}'
        if n > 0 and base['current_sha'] and base['remote_sha']:
            base['compare_url'] = (f'https://github.com/{repo}/compare/'
                                   f"{base['current_sha']}...{base['remote_sha']}")
    except FileNotFoundError:
        base['git_missing'] = True
        base['reason'] = 'git is not installed / not on PATH — install Git to enable in-app updates.'
    except subprocess.SubprocessError:
        base['reason'] = 'git command timed out.'
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
        from ..config import get as cfg_get
        repo = cfg_get('updates.repo') or 'perfectgf/lora-dataset-studio'
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

    python_deps = any(name == 'pyproject.toml'
                      or name.startswith('backend/requirements') for name in changed_names)
    frontend_deps = any(name in ('frontend/package.json', 'frontend/pnpm-lock.yaml')
                        for name in changed_names)
    frontend_sources = any(
        name.startswith('frontend/') and not name.startswith('frontend/dist/')
        for name in changed_names)
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
    if frontend_sources:
        frontend_ok, frontend_reason = _verify_frontend(root, pnpm, logs)
        if not frontend_ok:
            journal['state_before_rollback'] = 'verifying'
            return _rollback_update(root, before, journal,
                                    f'{frontend_reason} The update was rolled back.', logs)
    after = (_git(root, 'rev-parse', 'HEAD').stdout or '').strip()
    if after != target:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(root, before, journal,
                                'Post-update revision verification failed; the update was rolled back.', logs)
    journal['state'] = 'committed'
    journal['committed_at'] = datetime.now(timezone.utc).isoformat()
    try:
        _write_journal(root, journal)
    except OSError as exc:
        journal['state_before_rollback'] = 'verifying'
        return _rollback_update(root, before, journal,
                                f'Could not commit the recovery journal: {exc}', logs)
    journal_cleared = _clear_journal(root)
    return {'ok': True, 'changed': True, 'from': before[:8], 'to': after[:8],
            'deps_changed': bool(python_deps or frontend_deps),
            'python_deps_changed': python_deps,
            'frontend_deps_changed': frontend_deps,
            'frontend_sources_changed': frontend_sources,
            'verified': True, 'recovery_journal_cleared': journal_cleared,
            'log': '\n'.join(logs)[-4000:]}


def schedule_restart(delay: float = 1.2) -> None:
    """Restart without racing the old server or escaping a portable launcher.

    The portable launcher is the lifetime supervisor.  Its child exits with a
    reserved code and the launcher starts the replacement only after ``wait()``
    confirms that the old process (and its instance lock) are gone.  A source
    checkout has no supervisor, so a tiny detached helper waits for this exact
    PID to disappear before relaunching.  Port availability is deliberately not
    used as the hand-off signal: another process can claim a just-freed port.
    """
    py = sys.executable
    run_py = os.path.abspath(sys.argv[0])
    workdir = os.path.dirname(run_py) or None
    parent_pid = os.getpid()

    if os.environ.get('LDS_LAUNCHER_SUPERVISED') == '1':
        data_dir = Path(os.environ.get('LDS_DATA_DIR', str(REPO_ROOT / 'data')))
        request_path = data_dir / 'restart-request.json'
        request_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'host': os.environ.get('LDS_HOST') or _cfg_get('server.host') or '127.0.0.1',
            'port': int(os.environ.get('LDS_PORT') or _cfg_get('server.port') or 5050),
        }
        temporary = request_path.with_suffix('.json.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(request_path)

        def _exit_for_supervisor():
            import time
            time.sleep(delay)
            os._exit(RESTART_EXIT_CODE)

        threading.Thread(target=_exit_for_supervisor, daemon=True).start()
        return

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
        f'subprocess.Popen([{py!r},{run_py!r}], cwd={workdir!r}, creationflags=flags)\n'
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
        finally:
            os._exit(0)

    threading.Thread(target=_spawn_then_exit, daemon=True).start()
