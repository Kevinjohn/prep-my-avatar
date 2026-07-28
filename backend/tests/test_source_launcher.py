import importlib.util
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _launcher_module():
    path = Path(__file__).resolve().parents[1] / 'source_launcher.py'
    spec = importlib.util.spec_from_file_location('source_launcher_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_launcher_repairs_corrupt_run_before_execution(tmp_path):
    launcher = _launcher_module()
    root = tmp_path / 'checkout'
    backend = root / 'backend'
    data = tmp_path / 'private-data'
    backend.mkdir(parents=True)
    data.mkdir()
    marker = tmp_path / 'started.txt'
    run_py = backend / 'run.py'
    run_py.write_text(
        f'from pathlib import Path\nPath({str(marker)!r}).write_text("ok")\n',
        encoding='utf-8')
    subprocess.run(['git', 'init'], cwd=root, check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'tests@example.invalid'],
                   cwd=root, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Tests'], cwd=root, check=True)
    subprocess.run(['git', 'add', 'backend/run.py'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-m', 'working'], cwd=root, check=True,
                   capture_output=True)
    before = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
        capture_output=True, text=True).stdout.strip()
    run_py.write_text('this is corrupt !!!', encoding='utf-8')
    subprocess.run(['git', 'commit', '-am', 'broken update'], cwd=root, check=True,
                   capture_output=True)
    target = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
        capture_output=True, text=True).stdout.strip()
    source_recovery = Path(__file__).resolve().parents[1] / 'update_recovery.py'
    shutil.copy2(source_recovery, data / 'update-recovery.py')
    shutil.copy2(Path(__file__).resolve().parents[1] / 'source_launcher.py',
                 data / 'source-launcher.py')
    (data / 'boot-bundle.json').write_text(json.dumps({
        'version': 1,
        'files': {
            name: hashlib.sha256((data / name).read_bytes()).hexdigest()
            for name in ('update-recovery.py', 'source-launcher.py')},
    }), encoding='utf-8')
    (data / 'update-transaction.json').write_text(json.dumps({
        'version': 2, 'state': 'merged', 'root': str(root.resolve()),
        'before': before, 'target': target, 'changed_files': ['backend/run.py'],
    }), encoding='utf-8')

    assert launcher.launch(root, data, sys.executable) == 0
    assert marker.read_text(encoding='utf-8') == 'ok'
    assert subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
        capture_output=True, text=True).stdout.strip() == before


def test_installer_places_both_boot_files_outside_checkout(tmp_path):
    launcher = _launcher_module()
    root = tmp_path / 'checkout'
    backend = root / 'backend'
    data = tmp_path / 'private-data'
    backend.mkdir(parents=True)
    (backend / 'source_launcher.py').write_text('launcher', encoding='utf-8')
    (backend / 'update_recovery.py').write_text('recovery', encoding='utf-8')

    private = launcher.install(root, data)

    assert private == data / 'source-launcher.py'
    assert private.read_text(encoding='utf-8') == 'launcher'
    assert (data / 'update-recovery.py').read_text(encoding='utf-8') == 'recovery'
    assert json.loads((data / 'boot-bundle.json').read_text())['version'] == 1
