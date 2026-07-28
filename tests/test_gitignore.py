from pathlib import Path
import subprocess


def _ignored(root: Path, path: str) -> bool:
    result = subprocess.run(
        ['git', 'check-ignore', '--no-index', '--quiet', path], cwd=root,
        check=False)
    return result.returncode == 0


def test_runtime_ignores_are_scoped_to_repository_root():
    root = Path(__file__).resolve().parents[1]
    assert _ignored(root, 'output/generated.bin')
    assert _ignored(root, 'data/studio.db')
    assert _ignored(root, 'config.json')
    assert _ignored(root, 'code-reviews/local-review/run.json')

    assert not _ignored(root, 'frontend/src/output/example.js')
    assert not _ignored(root, 'tests/fixtures/data/sample.json')
    assert not _ignored(root, 'tests/fixtures/config.json')
