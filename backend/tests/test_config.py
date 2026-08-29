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


def test_dotenv_can_select_current_provider_and_models(tmp_path, monkeypatch):
    env_path = tmp_path / '.env'
    env_path.write_text(
        'LDS_DEFAULT_GENERATION_ENGINE=chatgpt\n'
        'LDS_ENABLED_GENERATION_ENGINES=klein,chatgpt\n'
        'LDS_CHATGPT_AUTH=api\n'
        'LDS_OPENAI_IMAGE_MODEL=gpt-image-2\n'
        'LDS_OPENAI_IMAGE_QUALITY=high\n'
        'LDS_GOOGLE_IMAGE_MODEL=gemini-2.5-flash-image\n'
        'LDS_NANOBANANA_PROVIDER=replicate\n'
        'LDS_REPLICATE_IMAGE_MODEL=google/nano-banana-pro\n'
        'LDS_LOCAL_VISION_BACKEND=lmstudio\n'
        'LDS_LMSTUDIO_URL=http://127.0.0.1:1234/v1\n'
        'LDS_LMSTUDIO_VISION_MODEL=qwen-vl\n'
        'LDS_LLAMACPP_URL=http://127.0.0.1:8080/v1\n'
        'LDS_LLAMACPP_VISION_MODEL=qwen-vl.gguf\n'
        'LDS_OLLAMA_URL=http://ollama.internal:11434\n'
        'LDS_OLLAMA_VISION_MODEL=qwen3-vl:8b\n',
        encoding='utf-8',
    )
    config = _fresh(monkeypatch, tmp_path)

    assert config.get('engines.default') == 'chatgpt'
    assert config.get('engines.enabled') == ['klein', 'chatgpt']
    assert config.get('engines.chatgpt_auth') == 'api'
    assert config.get('engines.openai_image_model') == 'gpt-image-2'
    assert config.get('engines.openai_image_quality') == 'high'
    assert config.get('engines.google_image_model') == 'gemini-2.5-flash-image'
    assert config.get('engines.nanobanana_provider') == 'replicate'
    assert config.get('engines.replicate_image_model') == 'google/nano-banana-pro'
    assert config.get('local_vision.backend') == 'lmstudio'
    assert config.get('lmstudio.url') == 'http://127.0.0.1:1234/v1'
    assert config.get('lmstudio.vision_model') == 'qwen-vl'
    assert config.get('llamacpp.url') == 'http://127.0.0.1:8080/v1'
    assert config.get('llamacpp.vision_model') == 'qwen-vl.gguf'
    assert config.get('ollama.url') == 'http://ollama.internal:11434'
    assert config.get('ollama.vision_model') == 'qwen3-vl:8b'


def test_config_json_overrides_environment_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('LDS_DEFAULT_GENERATION_ENGINE', 'chatgpt')
    monkeypatch.setenv('LDS_ENABLED_GENERATION_ENGINES', 'klein,chatgpt')
    (tmp_path / 'config.json').write_text(
        '{"engines":{"default":"klein","enabled":["klein"]}}',
        encoding='utf-8',
    )
    config = _fresh(monkeypatch, tmp_path)

    assert config.get('engines.default') == 'klein'
    assert config.get('engines.enabled') == ['klein']
    assert config.config_sources()['engines.default'] == 'settings'


def test_canonical_model_environment_name_wins_over_legacy_alias(
        tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('CHATGPT_IMAGE_MODEL', 'legacy-model')
    monkeypatch.setenv('LDS_OPENAI_IMAGE_MODEL', 'canonical-model')
    config = _fresh(monkeypatch, tmp_path)

    with caplog.at_level('WARNING', logger='app.config'):
        assert config.get('engines.openai_image_model') == 'canonical-model'
    assert config.config_sources()['engines.openai_image_model'] == 'environment'


@pytest.mark.parametrize('name,value,match', [
    ('LDS_ENABLED_GENERATION_ENGINES', 'klein,unknown', 'valid engines'),
    ('LDS_DEFAULT_GENERATION_ENGINE', 'unknown', 'valid engine'),
    ('LDS_OPENAI_IMAGE_QUALITY', 'ultra', 'one of'),
    ('LDS_NANOBANANA_PROVIDER', 'unknown', 'one of'),
    ('LDS_LOCAL_VISION_BACKEND', 'unknown', 'one of'),
    ('LDS_LMSTUDIO_URL', 'file:///tmp/server', 'http'),
    ('LDS_LLAMACPP_URL', 'http://user:pass@localhost:8080/v1', 'credentials'),
    ('LDS_OLLAMA_URL', 'not a url', 'http'),
])
def test_invalid_environment_defaults_fail_closed(
        tmp_path, monkeypatch, name, value, match):
    monkeypatch.setenv(name, value)
    config = _fresh(monkeypatch, tmp_path)

    with pytest.raises(config.ConfigError, match=match):
        config.load_config(force=True)


def test_contradictory_environment_engine_defaults_fail_closed(
        tmp_path, monkeypatch):
    monkeypatch.setenv('LDS_DEFAULT_GENERATION_ENGINE', 'chatgpt')
    monkeypatch.setenv('LDS_ENABLED_GENERATION_ENGINES', 'klein')
    config = _fresh(monkeypatch, tmp_path)

    with pytest.raises(config.ConfigError, match='default.*enabled'):
        config.load_config(force=True)


def test_config_sources_distinguish_dotenv_environment_settings_and_default(
        tmp_path, monkeypatch):
    (tmp_path / '.env').write_text(
        'LDS_OPENAI_IMAGE_QUALITY=high\n', encoding='utf-8')
    monkeypatch.setenv('LDS_CHATGPT_AUTH', 'api')
    (tmp_path / 'config.json').write_text(
        '{"ollama":{"vision_model":"custom-vlm"}}', encoding='utf-8')
    config = _fresh(monkeypatch, tmp_path)

    sources = config.config_sources()
    assert sources['engines.openai_image_quality'] == 'dotenv'
    assert sources['engines.chatgpt_auth'] == 'environment'
    assert sources['ollama.vision_model'] == 'settings'
    assert sources['engines.default'] == 'default'


def test_delete_config_override_reveals_environment_value(tmp_path, monkeypatch):
    monkeypatch.setenv('LDS_OLLAMA_VISION_MODEL', 'environment-vlm')
    config = _fresh(monkeypatch, tmp_path)
    config.save_config({'ollama': {'vision_model': 'settings-vlm', 'url': 'http://localhost:11434'}})

    assert config.delete_config_override('ollama.vision_model') == 'environment-vlm'
    stored = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
    assert 'vision_model' not in stored['ollama']
    assert stored['ollama']['url'] == 'http://localhost:11434'


def test_delete_absent_config_override_returns_without_locking(tmp_path, monkeypatch):
    config = _fresh(monkeypatch, tmp_path)
    assert config.delete_config_override('ollama.vision_model') \
        == config.DEFAULTS['ollama']['vision_model']


def test_delete_config_override_rejects_invalid_effective_engine_pair_without_writing(
        tmp_path, monkeypatch):
    monkeypatch.setenv('LDS_DEFAULT_GENERATION_ENGINE', 'chatgpt')
    monkeypatch.setenv('LDS_ENABLED_GENERATION_ENGINES', 'klein,chatgpt')
    config = _fresh(monkeypatch, tmp_path)
    config.save_config({'engines': {'default': 'klein', 'enabled': ['klein']}})
    before = (tmp_path / 'config.json').read_text(encoding='utf-8')

    with pytest.raises(config.ConfigError, match='default.*enabled'):
        config.delete_config_override('engines.default')

    assert (tmp_path / 'config.json').read_text(encoding='utf-8') == before

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


def test_secret_updates_preserve_dotenv_comments_and_quote_values(
        tmp_path, monkeypatch):
    (tmp_path / '.env').write_text(
        '# provider keys\nOPENAI_API_KEY=old\n\n# keep this note\n',
        encoding='utf-8',
    )
    config = _fresh(monkeypatch, tmp_path)

    config.set_secrets({'OPENAI_API_KEY': "key with spaces and 'quote'"})

    text = config.ENV_PATH.read_text(encoding='utf-8')
    assert '# provider keys' in text
    assert '# keep this note' in text
    assert config.secret('OPENAI_API_KEY') == "key with spaces and 'quote'"
    assert config.secret_source('OPENAI_API_KEY') == 'dotenv'


def test_ui_secret_write_does_not_override_external_process_secret(
        tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'operator-value')
    config = _fresh(monkeypatch, tmp_path)

    config.set_secrets({'OPENAI_API_KEY': 'file-value'})
    assert config.secret('OPENAI_API_KEY') == 'operator-value'
    assert config.secret_source('OPENAI_API_KEY') == 'environment'

    config.delete_secrets(['OPENAI_API_KEY'])
    assert config.secret('OPENAI_API_KEY') == 'operator-value'
    assert config.secret_source('OPENAI_API_KEY') == 'environment'


def test_blank_external_secret_does_not_mask_saved_dotenv_secret(
        tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', '')
    (tmp_path / '.env').write_text(
        'OPENAI_API_KEY=dotenv-value\n', encoding='utf-8')
    config = _fresh(monkeypatch, tmp_path)

    assert config.secret('OPENAI_API_KEY') == 'dotenv-value'
    assert config.secret_source('OPENAI_API_KEY') == 'dotenv'

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


@pytest.mark.parametrize('payload,match', [
    ({'engines': {'openai_image_model': ''}}, 'openai_image_model'),
    ({'engines': {'openai_image_quality': 'ultra'}}, 'openai_image_quality'),
    ({'ollama': {'url': 'file:///tmp/ollama'}}, 'ollama.url'),
    ({'comfyui': {'api_url': 'http://user:pass@localhost:8188'}}, 'credentials'),
])
def test_invalid_manual_provider_config_fails_startup(
        tmp_path, monkeypatch, payload, match):
    config = _fresh(monkeypatch, tmp_path)
    (tmp_path / 'config.json').write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(config.ConfigError, match=match):
        config.load_config(force=True)


def test_app_factory_rejects_invalid_environment_configuration_before_startup(
        tmp_path, monkeypatch):
    monkeypatch.setenv('LDS_OPENAI_IMAGE_QUALITY', 'ultra')
    config = _fresh(monkeypatch, tmp_path)
    from app import create_app

    with pytest.raises(config.ConfigError, match='LDS_OPENAI_IMAGE_QUALITY'):
        create_app({'TESTING': True})


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


def test_dotenv_example_covers_supported_defaults_without_secrets(
        tmp_path, monkeypatch):
    from dotenv import dotenv_values
    config = _fresh(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[2]
    values = dotenv_values(repo_root / '.env.example', interpolate=False)

    assert all((values.get(name) or '') == '' for name in config.SECRET_KEYS)
    for dotted, (canonical, _aliases, parser) in config._ENV_SETTINGS.items():
        assert canonical in values, f'{canonical} is missing from .env.example'
        if values[canonical] == '':
            node = config.DEFAULTS
            for part in dotted.split('.'):
                node = node[part]
            assert node == ''
            continue
        parsed = parser(canonical, values[canonical])
        node = config.DEFAULTS
        for part in dotted.split('.'):
            node = node[part]
        assert parsed == node


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
    assert "OPENAI_API_KEY='openai-value'" in text
    assert "HF_TOKEN='hf-value'" in text


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
