import importlib.util
import shutil
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_repository_contracts.py"
SPEC = importlib.util.spec_from_file_location("validate_repository_contracts", SCRIPT)
contracts = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(contracts)


def test_current_repository_governance_contracts():
    assert contracts.validate_governance() == []


def test_current_release_contract_is_consistent():
    assert contracts.validate_release(f"v{contracts.app_version()}") == []


def test_release_contract_rejects_mismatched_tag():
    errors = contracts.validate_release("v1900.01.01.1")
    assert any("does not match" in error for error in errors)


def test_docker_context_excludes_generated_runtime_and_distribution_trees():
    rules = {
        line.strip().rstrip('/')
        for line in (SCRIPT.parents[1] / '.dockerignore').read_text(
            encoding='utf-8'
        ).splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    }
    assert {'.python', 'packaging/build', 'packaging/dist', '.pytest_cache',
            'code-reviews'} <= rules


def _docs_fixture(tmp_path):
    root = SCRIPT.parents[1]
    for relative in (
        'README.md', 'CONTRIBUTING.md', 'CHANGELOG.md', 'docs/VERSIONING.md',
        'CODE_OF_CONDUCT.md', '.github/PULL_REQUEST_TEMPLATE.md',
        '.github/workflows/ci.yml', '.github/workflows/release.yml',
        '.github/ISSUE_TEMPLATE/config.yml',
        '.github/ISSUE_TEMPLATE/bug_report.yml',
        '.github/ISSUE_TEMPLATE/feature_request.yml',
        'packaging/build_portable.ps1',
        'backend/app/version.py',
        'backend/app/services/face_dataset_service.py',
        'backend/app/services/face_variations.py',
        'docs/guide/getting-started.md', 'docs/guide/getting-help.md',
        'docs/guide/troubleshooting.md',
        'docs/specs/import-first-multi-reference-design.md',
        'docs/screenshots/manifest.yml',
        'docs/screenshots/readme/05-training-readiness.jpg',
        'frontend/src/components/dataset/DatasetWorkflowNav.jsx',
        'frontend/src/components/dataset/PreflightModal.jsx',
        'frontend/src/utils/labels.js',
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    return tmp_path


def test_docs_contract_rejects_upstream_support_and_missing_named_target(tmp_path, monkeypatch):
    root = _docs_fixture(tmp_path)
    help_path = root / 'docs/guide/getting-help.md'
    help_path.write_text(
        help_path.read_text(encoding='utf-8').replace(
            'Kevinjohn/prep-my-avatar/issues',
            'perfectgf/lora-dataset-studio/issues',
        ),
        encoding='utf-8',
    )
    readme = root / 'README.md'
    readme.write_text(
        readme.read_text(encoding='utf-8').replace(
            '## Installation and launch', '## Launch'
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(contracts, 'ROOT', root)
    errors = contracts.validate_governance()
    assert any('upstream issue tracker' in error for error in errors)
    assert any('no Installation and launch section' in error for error in errors)


def test_docs_contract_requires_canonical_installation_target(tmp_path, monkeypatch):
    root = _docs_fixture(tmp_path)
    getting_started = root / 'docs/guide/getting-started.md'
    canonical_target = (
        f'https://github.com/{contracts.CANONICAL_REPOSITORY}#installation-and-launch'
    )
    source = getting_started.read_text(encoding='utf-8')
    assert canonical_target in source
    getting_started.write_text(
        source.replace(
            canonical_target,
            'https://github.com/perfectgf/lora-dataset-studio#installation-and-launch',
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(contracts, 'ROOT', root)

    errors = contracts.validate_governance()

    assert any(
        'does not target the canonical Installation and launch section' in error
        for error in errors
    )


def test_governance_contract_enforces_backend_frontend_catalog_label_parity(
        tmp_path, monkeypatch):
    root = _docs_fixture(tmp_path)
    labels = root / 'frontend/src/utils/labels.js'
    labels.write_text(
        labels.read_text(encoding='utf-8').replace(
            "  'Visage face, neutre': 'Face front, neutral',\n", ''
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(contracts, 'ROOT', root)
    errors = contracts.validate_governance()
    assert any('missing backend catalog keys' in error for error in errors)


def test_governance_contract_preserves_literal_hash_in_contact_description(
        tmp_path, monkeypatch):
    root = _docs_fixture(tmp_path)
    config = root / '.github/ISSUE_TEMPLATE/config.yml'
    parsed = contracts.yaml.safe_load(config.read_text(encoding='utf-8'))
    assert parsed['contact_links'][0]['about'] == contracts.ISSUE_CONTACT_ABOUT
    assert '#help' in parsed['contact_links'][0]['about']
    config.write_text(
        config.read_text(encoding='utf-8').replace(
            'about: "Ask in #help for inherited LoRA Dataset Studio behavior; '
            'fork bugs and feature ideas belong in this repository\'s issues."',
            'about: Ask in #help; fork bugs and feature ideas belong here.',
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(contracts, 'ROOT', root)
    parsed = contracts.yaml.safe_load(config.read_text(encoding='utf-8'))
    assert parsed['contact_links'][0]['about'] == 'Ask in'
    errors = contracts.validate_governance()
    assert any('complete support contact description' in error for error in errors)


def test_docs_contract_rejects_limit_drift_and_referenced_retired_screenshot(
        tmp_path, monkeypatch):
    root = _docs_fixture(tmp_path)
    spec = root / 'docs/specs/import-first-multi-reference-design.md'
    spec.write_text(
        spec.read_text(encoding='utf-8').replace(
            '12 for\nexperimental', '8 for\nexperimental'
        ),
        encoding='utf-8',
    )
    readme = root / 'README.md'
    readme.write_text(
        readme.read_text(encoding='utf-8')
        + '\n![stale](docs/screenshots/readme/05-training-readiness.jpg)\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(contracts, 'ROOT', root)
    errors = contracts.validate_governance()
    assert any('does not match coverage limits' in error for error in errors)
    assert any('Retired screenshot is still referenced' in error for error in errors)


def test_docs_contract_rejects_current_screenshot_after_relevant_source_changes(
        tmp_path, monkeypatch):
    root = _docs_fixture(tmp_path)
    manifest = root / 'docs/screenshots/manifest.yml'
    manifest.write_text(
        manifest.read_text(encoding='utf-8').replace(
            'status: retired', 'status: current'
        ),
        encoding='utf-8',
    )
    source = root / 'frontend/src/components/dataset/DatasetWorkflowNav.jsx'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('changed after the declared screenshot capture', encoding='utf-8')
    monkeypatch.setattr(contracts, 'ROOT', root)
    errors = contracts.validate_governance()
    assert any('Current screenshot predates relevant source' in error for error in errors)


def test_docs_contract_rejects_missing_owner_and_invalid_capture_revision(
        tmp_path, monkeypatch):
    root = _docs_fixture(tmp_path)
    manifest = root / 'docs/screenshots/manifest.yml'
    manifest.write_text(
        manifest.read_text(encoding='utf-8')
        .replace('owner: Kevinjohn/prep-my-avatar maintainers', 'owner: ""')
        .replace(
            'capture_revision: e77aa6c7397c682bf104f6c5712fd90b4fbe753d',
            'capture_revision: not-a-revision',
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(contracts, 'ROOT', root)
    errors = contracts.validate_governance()
    assert any('has no owner' in error for error in errors)
    assert any('invalid capture revision' in error for error in errors)


def test_docs_contract_rejects_unmanifested_screenshot_reference(tmp_path, monkeypatch):
    root = _docs_fixture(tmp_path)
    readme = root / 'README.md'
    readme.write_text(
        readme.read_text(encoding='utf-8')
        + '\n![unverified](docs/screenshots/readme/01-import-corpus.jpg)\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(contracts, 'ROOT', root)

    errors = contracts.validate_governance()

    assert any('no capture manifest' in error for error in errors)
