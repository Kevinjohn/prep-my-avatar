import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / 'scripts' / 'publish_release.py'
SPEC = importlib.util.spec_from_file_location('publish_release', SCRIPT)
publish = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(publish)


class FakeGitHub:
    """A disk-backed release service for rerun/fault convergence tests."""

    def __init__(self, repository: Path, fail_after: str):
        self.state_path = repository / '.fake-github-releases.json'
        self.fail_after = fail_after
        self.failed = False

    def _load(self):
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else {}

    def _save(self, state):
        self.state_path.write_text(json.dumps(state, sort_keys=True))

    def __call__(self, command):
        operation = command[2]
        tag = command[3]
        state = self._load()
        release = state.get(tag)
        if operation == 'view':
            if release is None:
                return subprocess.CompletedProcess(command, 1, '', 'not found')
            return subprocess.CompletedProcess(command, 0, json.dumps(release), '')
        if operation == 'create':
            state.setdefault(tag, {'isDraft': True, 'assets': []})
        elif operation == 'upload':
            asset = Path(command[4])
            release['assets'] = [
                item for item in release['assets'] if item['name'] != asset.name]
            release['assets'].append({'name': asset.name, 'size': asset.stat().st_size})
        elif operation == 'edit':
            release['isDraft'] = False
        else:
            raise AssertionError(command)
        self._save(state)
        if operation == self.fail_after and not self.failed:
            self.failed = True
            return subprocess.CompletedProcess(command, 1, '', 'injected post-side-effect failure')
        return subprocess.CompletedProcess(command, 0, '', '')


@pytest.mark.parametrize('boundary', ['create', 'upload', 'edit'])
def test_release_publication_rerun_converges_after_each_boundary(tmp_path, boundary):
    repository = tmp_path / 'disposable-repository'
    repository.mkdir()
    subprocess.run(['git', 'init', '-q', str(repository)], check=True)
    asset = repository / 'LoRA-Dataset-Studio-win64.zip'
    asset.write_bytes(b'verified portable bytes')
    remote = FakeGitHub(repository, boundary)

    with pytest.raises(RuntimeError, match='injected post-side-effect failure'):
        publish.reconcile_release('v2026.07.27.1', asset, run=remote)
    publish.reconcile_release('v2026.07.27.1', asset, run=remote)

    state = json.loads(remote.state_path.read_text())
    assert list(state) == ['v2026.07.27.1']
    assert state['v2026.07.27.1'] == {
        'isDraft': False,
        'assets': [{'name': asset.name, 'size': asset.stat().st_size}],
    }
