import json
import importlib
import os
import stat
import threading
from pathlib import Path

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
