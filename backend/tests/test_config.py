import json
import importlib
import os
import stat
import threading
from pathlib import Path

import pytest

def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv('LDS_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('LDS_CONFIG', str(tmp_path / 'config.json'))
    monkeypatch.setenv('LDS_ENV', str(tmp_path / '.env'))
    import app.config as config
    importlib.reload(config)
    return config

def test_defaults_when_no_file(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    assert config.get('server.port') == 5050
    assert config.get('engines.default') == 'klein'
    assert config.get('engines.enabled') == ['klein']
    assert config.get('privacy.allow_remote_generation') is False
    assert config.is_configured() is False

def test_save_and_reload_deep_merge(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    config.save_config({'comfyui': {'api_url': 'http://10.0.0.2:8188'}})
    assert config.get('comfyui.api_url') == 'http://10.0.0.2:8188'
    assert config.get('server.port') == 5050          # untouched default survives
    assert config.is_configured() is True
    on_disk = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
    assert on_disk['comfyui']['api_url'] == 'http://10.0.0.2:8188'

def test_comfyui_dir_derivation(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    assert config.comfyui_dir('loras') is None        # unconfigured
    base = tmp_path / 'Comfy'
    (base / 'models' / 'loras').mkdir(parents=True)
    config.save_config({'comfyui': {'base_dir': str(base)}})
    assert config.comfyui_dir('loras') == base / 'models' / 'loras'
    assert config.comfyui_dir('output') == base / 'output'

def test_secrets_roundtrip(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert config.secret('OPENAI_API_KEY') is None
    config.set_secrets({'OPENAI_API_KEY': 'sk-test-123'})
    assert config.secret('OPENAI_API_KEY') == 'sk-test-123'
    env_text = (config.ENV_PATH).read_text(encoding='utf-8')
    assert 'sk-test-123' in env_text

def test_secret_strips_trailing_whitespace(tmp_path, monkeypatch):
    """A pasted key with a trailing newline/space must not corrupt the Bearer header."""
    config = _fresh(monkeypatch, tmp_path)
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test-123\n')
    assert config.secret('OPENAI_API_KEY') == 'sk-test-123'
    monkeypatch.setenv('OPENAI_API_KEY', '  sk-test-456  ')
    assert config.secret('OPENAI_API_KEY') == 'sk-test-456'

def test_local_user_constant(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    assert config.LOCAL_USER == 'local'

def test_load_config_returns_defensive_copy(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    cfg = config.load_config()
    cfg['server']['port'] = 9999          # caller mutation must not corrupt the cache
    assert config.get('server.port') == 5050


@pytest.mark.parametrize('contents', ['{broken', '[]', '[1]', 'null', '"text"'])
def test_invalid_config_is_preserved_and_rejected(tmp_path, monkeypatch, contents):
    config = _fresh(monkeypatch, tmp_path)
    path = tmp_path / 'config.json'
    path.write_text(contents, encoding='utf-8')
    with pytest.raises(config.ConfigError):
        config.load_config(force=True)
    with pytest.raises(config.ConfigError):
        config.save_config({'server': {'port': 6000}})
    assert path.read_text(encoding='utf-8') == contents
    assert config.is_configured() is False


def test_invalid_config_section_is_rejected(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    (tmp_path / 'config.json').write_text('{"server": 5}', encoding='utf-8')
    with pytest.raises(config.ConfigError, match="server"):
        config.load_config(force=True)


def test_legacy_upstream_update_default_migrates_in_memory(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    (tmp_path / 'config.json').write_text(
        '{"updates":{"repo":"perfectgf/lora-dataset-studio"}}', encoding='utf-8')
    assert config.get('updates.repo') == 'Kevinjohn/prep-my-avatar'


def test_legacy_empty_engine_list_migrates_to_explicit_local_default(
        tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    (tmp_path / 'config.json').write_text(
        '{"engines":{"enabled":[],"default":"chatgpt"}}', encoding='utf-8')
    assert config.get('engines.enabled') == ['klein']
    assert config.get('engines.default') == 'klein'


def test_example_config_matches_all_defaults(tmp_path, monkeypatch):
    """The shipped example is an executable contract, not stale documentation."""
    config = _fresh(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[2]
    example = json.loads((repo_root / 'config.example.json').read_text(encoding='utf-8'))
    assert example == config.DEFAULTS


def test_all_runtime_port_defaults_agree(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / 'docker-compose.yml').read_text(encoding='utf-8')
    dockerfile = (repo_root / 'Dockerfile').read_text(encoding='utf-8')
    vite = (repo_root / 'frontend' / 'vite.config.js').read_text(encoding='utf-8')
    port = config.DEFAULTS['server']['port']
    assert f'ports: ["{port}:{port}"]' in compose
    assert f'LDS_PORT={port}' in compose
    assert f'EXPOSE {port}' in dockerfile
    assert f"http://127.0.0.1:{port}" in vite


def test_secret_files_are_owner_only_on_posix(tmp_path, monkeypatch):
    if os.name == 'nt':
        return
    config = _fresh(monkeypatch, tmp_path)
    config.save_config({'server': {'require_token': True, 'access_token': 'private'}})
    config.set_secrets({'OPENAI_API_KEY': 'sk-private'})
    config.secret_key()
    for path in (tmp_path / 'config.json', config.ENV_PATH,
                 tmp_path / 'data' / 'secret_key'):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_concurrent_secret_updates_do_not_lose_keys(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    barrier = threading.Barrier(3)

    def save(name, value):
        barrier.wait()
        config.set_secrets({name: value})

    workers = [
        threading.Thread(target=save, args=('OPENAI_API_KEY', 'openai-value')),
        threading.Thread(target=save, args=('HF_TOKEN', 'hf-value')),
    ]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    text = config.ENV_PATH.read_text(encoding='utf-8')
    assert 'OPENAI_API_KEY=openai-value' in text
    assert 'HF_TOKEN=hf-value' in text


def test_concurrent_secret_key_creation_is_stable(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    barrier = threading.Barrier(5)
    values = []

    def read_key():
        barrier.wait()
        values.append(config.secret_key())

    workers = [threading.Thread(target=read_key) for _ in range(4)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert len(values) == 4
    assert len(set(values)) == 1


@pytest.mark.parametrize('contents', ['', '   \n', 'abcd'])
def test_invalid_secret_key_is_regenerated(tmp_path, monkeypatch, contents):
    config = _fresh(monkeypatch, tmp_path)
    key_path = tmp_path / 'data' / 'secret_key'
    key_path.parent.mkdir(parents=True)
    key_path.write_text(contents, encoding='utf-8')
    value = config.secret_key()
    assert len(value) == 64
    assert value != contents.strip()
    assert key_path.read_text(encoding='utf-8') == value


def test_failed_secret_write_keeps_runtime_and_disk_state(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    config.set_secrets({'OPENAI_API_KEY': 'old-value'})
    original = config.ENV_PATH.read_text(encoding='utf-8')

    def fail_write(path, value):
        raise OSError('disk full')

    monkeypatch.setattr(config, '_write_private_text', fail_write)
    with pytest.raises(OSError):
        config.set_secrets({'OPENAI_API_KEY': 'new-value'})
    assert os.environ['OPENAI_API_KEY'] == 'old-value'
    assert config.ENV_PATH.read_text(encoding='utf-8') == original

    with pytest.raises(OSError):
        config.delete_secrets(['OPENAI_API_KEY'])
    assert os.environ['OPENAI_API_KEY'] == 'old-value'
    assert config.ENV_PATH.read_text(encoding='utf-8') == original


def test_secret_key_rotation_of_invalid_file_logs_warning(tmp_path, monkeypatch, caplog):
    """Review-2 DBR-0005: regenerating a pre-existing invalid key must log a
    warning — silent rotation invalidates all signed sessions invisibly."""
    import logging
    from app import config as cfg
    monkeypatch.setattr(cfg, '_data_dir', lambda: tmp_path)
    keyfile = tmp_path / 'secret_key'
    keyfile.write_text('not-hex-at-all')
    with caplog.at_level(logging.WARNING, logger='app.config'):
        value = cfg.secret_key()
    assert len(value) == 64
    assert any('invalidated' in r.message for r in caplog.records)


def test_secret_key_valid_file_does_not_warn_or_rotate(tmp_path, monkeypatch, caplog):
    import logging
    from app import config as cfg
    monkeypatch.setattr(cfg, '_data_dir', lambda: tmp_path)
    good = 'a' * 64
    (tmp_path / 'secret_key').write_text(good)
    with caplog.at_level(logging.WARNING, logger='app.config'):
        assert cfg.secret_key() == good
    assert not [r for r in caplog.records if 'invalidated' in r.message]
