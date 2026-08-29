import pathlib
import pytest


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """GET /api/capabilities calls probe(), which hits every reachability
    probe. Stub the network/subprocess seams so this file never makes a
    real call, mirroring test_capabilities.py's isolation."""
    from app import capabilities
    capabilities._cache = None
    capabilities._cache_ts = 0.0
    capabilities._import_cache.clear()
    monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: False)
    monkeypatch.setattr(capabilities, '_import_ok', lambda *a, **k: False)
    yield
    capabilities._cache = None
    capabilities._cache_ts = 0.0
    capabilities._import_cache.clear()


def test_get_settings_masks_secrets(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-secret')
    data = client.get('/api/settings').get_json()
    assert data['secrets']['OPENAI_API_KEY'] is True
    assert 'sk-secret' not in str(data)


def test_get_settings_reports_config_and_secret_sources(client, monkeypatch):
    from app import config as cfg
    monkeypatch.setenv('OPENAI_API_KEY', 'external-secret')
    monkeypatch.setitem(cfg._PROCESS_ENV, 'OPENAI_API_KEY', 'external-secret')
    monkeypatch.setitem(cfg._PROCESS_ENV, 'LDS_CHATGPT_AUTH', 'api')
    monkeypatch.delitem(cfg._PROCESS_ENV, 'LDS_DEFAULT_GENERATION_ENGINE', raising=False)
    monkeypatch.delitem(cfg._DOTENV_VALUES, 'LDS_DEFAULT_GENERATION_ENGINE', raising=False)
    monkeypatch.setattr(cfg, '_cache', None)

    data = client.get('/api/settings').get_json()

    assert data['config_sources']['engines.chatgpt_auth'] == 'environment'
    assert data['config_sources']['engines.default'] == 'default'
    assert data['secret_sources']['OPENAI_API_KEY'] == 'environment'
    assert 'external-secret' not in str(data)


def test_delete_config_override_reveals_dotenv_default(client, monkeypatch):
    from app import config as cfg
    monkeypatch.setitem(cfg._DOTENV_VALUES, 'LDS_OLLAMA_VISION_MODEL', 'dotenv-vlm')
    monkeypatch.setattr(cfg, '_cache', None)
    saved = client.put('/api/settings', json={
        'config': {'ollama': {'vision_model': 'settings-vlm'}},
    })
    assert saved.status_code == 200
    assert saved.get_json()['config_sources']['ollama.vision_model'] == 'settings'

    response = client.delete('/api/settings/config/ollama.vision_model')

    assert response.status_code == 200
    data = response.get_json()
    assert data['config']['ollama']['vision_model'] == 'dotenv-vlm'
    assert data['config_sources']['ollama.vision_model'] == 'dotenv'


def test_delete_config_override_rejects_non_environment_setting(client):
    response = client.delete('/api/settings/config/server.port')
    assert response.status_code == 400
    assert 'cannot be reset' in response.get_json()['error']

def test_put_settings_persists_config_and_secret(client, tmp_path):
    r = client.put('/api/settings', json={
        'config': {'ollama': {'url': 'http://127.0.0.1:11500'}},
        'secrets': {'GEMINI_API_KEY': 'g-123'}})
    assert r.status_code == 200
    assert r.get_json()['config']['ollama']['url'] == 'http://127.0.0.1:11500'
    assert r.get_json()['secrets']['GEMINI_API_KEY'] is True


def test_put_settings_persists_provider_routing_without_exposing_replicate_token(client):
    response = client.put('/api/settings', json={
        'config': {
            'engines': {
                'nanobanana_provider': 'replicate',
                'replicate_image_model': 'google/nano-banana-pro',
            },
            'local_vision': {'backend': 'lmstudio'},
            'lmstudio': {
                'url': 'http://127.0.0.1:1234/v1',
                'vision_model': 'qwen-vl',
            },
        },
        'secrets': {'REPLICATE_API_TOKEN': 'r8-private-token'},
    })

    assert response.status_code == 200
    body = response.get_json()
    assert body['config']['engines']['nanobanana_provider'] == 'replicate'
    assert body['config']['engines']['replicate_image_model'] == 'google/nano-banana-pro'
    assert body['config']['local_vision']['backend'] == 'lmstudio'
    assert body['config']['lmstudio'] == {
        'url': 'http://127.0.0.1:1234/v1', 'vision_model': 'qwen-vl',
    }
    assert body['secrets']['REPLICATE_API_TOKEN'] is True
    assert 'r8-private-token' not in response.get_data(as_text=True)


def test_field_level_settings_writes_preserve_another_tabs_unrelated_change(client):
    """The SPA sends only its draft's changed leaves. The API's deep merge must
    preserve a write committed by another tab after this tab loaded."""
    first = client.put('/api/settings', json={
        'config': {'server': {'port': 6123}},
    })
    assert first.status_code == 200

    stale_other_tab = client.put('/api/settings', json={
        'config': {'captioning': {'backend': 'ollama'}},
    })
    assert stale_other_tab.status_code == 200
    config = stale_other_tab.get_json()['config']
    assert config['server']['port'] == 6123
    assert config['captioning']['backend'] == 'ollama'

def test_put_settings_saves_scrape_credentials(client):
    """REDDIT_CLIENT_ID / CIVITAI_API_KEY ride the same secrets store as the engine
    keys: presence-only in the payload, env stamped on save — the scrape sources
    read the env var first, so a key saved in the UI works without a restart."""
    import os
    r = client.put('/api/settings', json={'secrets': {'REDDIT_CLIENT_ID': 'my-cid',
                                                      'CIVITAI_API_KEY': 'civ-key'}})
    assert r.status_code == 200
    secrets = r.get_json()['secrets']
    assert secrets['REDDIT_CLIENT_ID'] is True and secrets['CIVITAI_API_KEY'] is True
    assert 'my-cid' not in str(r.get_json())               # presence only, never the value
    assert os.environ['REDDIT_CLIENT_ID'] == 'my-cid'      # effective immediately
    from app.scrape.sources import reddit
    from app.scrape.sources.civitai import civitai_api_key
    assert reddit._client_id() == 'my-cid'
    assert civitai_api_key() == 'civ-key'


def test_delete_scrape_credential_falls_back_to_shared_id(client, monkeypatch):
    """Removing the saved Reddit client id must drop it from the env too, so the
    source falls back to the shared gallery-dl id instead of a stale value."""
    import os
    from app.scrape.sources import reddit
    monkeypatch.setattr(reddit, 'resolve_cookies', lambda key: None)  # ignore any local admin file
    client.put('/api/settings', json={'secrets': {'REDDIT_CLIENT_ID': 'my-cid'}})
    r = client.delete('/api/settings/secret/REDDIT_CLIENT_ID')
    assert r.status_code == 200
    assert r.get_json()['secrets']['REDDIT_CLIENT_ID'] is False
    assert 'REDDIT_CLIENT_ID' not in os.environ
    assert reddit._client_id() == reddit._GDL_CLIENT_ID


def test_put_rejects_unknown_section(client):
    assert client.put('/api/settings', json={'config': {'nope': 1}}).status_code == 400

def test_put_rejects_non_object_section_value(client):
    """{"config": {"ollama": "x"}} would otherwise pass the top-level key-name
    check and let _deep_merge overwrite the whole 'ollama' section with a
    string, persistently corrupting config.json. Must be rejected AND leave
    the existing config untouched."""
    before = client.get('/api/settings').get_json()['config']['ollama']
    r = client.put('/api/settings', json={'config': {'ollama': 'x'}})
    assert r.status_code == 400
    after = client.get('/api/settings').get_json()['config']['ollama']
    assert after == before
    assert isinstance(after, dict) and 'url' in after

def test_put_rejects_non_object_config(client):
    assert client.put('/api/settings', json={'config': 'oops'}).status_code == 400

def test_put_rejects_non_object_secrets(client):
    assert client.put('/api/settings', json={'secrets': ['x']}).status_code == 400


@pytest.mark.parametrize('value', [123, True, ['secret'], {'value': 'secret'}])
def test_invalid_secret_value_is_rejected_before_any_settings_write(
        client, monkeypatch, value):
    import os
    from app import config as cfg

    config_path = cfg._config_path()
    before_config = config_path.read_bytes() if config_path.exists() else None
    before_env_file = cfg.ENV_PATH.read_bytes() if cfg.ENV_PATH.exists() else None
    before_runtime = os.environ.get('OPENAI_API_KEY')
    writes = []
    original_write = cfg._write_private_text

    def track_write(path, text):
        writes.append(path)
        return original_write(path, text)

    monkeypatch.setattr(cfg, '_write_private_text', track_write)
    response = client.put('/api/settings', json={
        'config': {'server': {'port': 6123}},
        'secrets': {'OPENAI_API_KEY': value},
    })

    assert response.status_code == 400
    assert response.get_json()['error'] == 'secret OPENAI_API_KEY must be a string'
    assert writes == []
    assert (config_path.read_bytes() if config_path.exists() else None) == before_config
    assert (cfg.ENV_PATH.read_bytes() if cfg.ENV_PATH.exists() else None) == before_env_file
    assert cfg.get('server.port') == 5050
    assert os.environ.get('OPENAI_API_KEY') == before_runtime


@pytest.mark.parametrize('body', [None, [], 'text', 1, True])
def test_put_rejects_non_object_request_body_without_writing(client, body):
    before = client.get('/api/settings').get_json()['config']
    response = client.put('/api/settings', json=body)
    assert response.status_code == 400
    assert response.get_json()['error'] == 'request body must be an object'
    assert client.get('/api/settings').get_json()['config'] == before


@pytest.mark.parametrize(('section', 'field', 'value'), [
    ('server', 'port', '5050'),
    ('server', 'port', 0),
    ('server', 'port', 65536),
    ('server', 'host', 'localhost'),
    ('server', 'require_token', 1),
    ('privacy', 'allow_remote_generation', 'false'),
    ('captioning', 'backend', 'invalid'),
    ('watermark', 'device', 'metal'),
    ('ollama', 'unknown', 'value'),
])
def test_put_rejects_invalid_nested_config_values(client, section, field, value):
    before = client.get('/api/settings').get_json()['config']
    response = client.put('/api/settings', json={
        'config': {section: {field: value}},
    })
    assert response.status_code == 400
    assert f'{section}.{field}' in response.get_json()['error']
    assert client.get('/api/settings').get_json()['config'] == before


def test_combined_settings_write_rolls_back_config_when_secret_write_fails(
        client, monkeypatch):
    from app import config as cfg
    config_path = cfg._config_path()
    before_config = config_path.read_bytes() if config_path.exists() else None
    original_write = cfg._write_private_text

    def fail_env_write(path, value):
        if path == cfg.ENV_PATH:
            raise OSError('disk full')
        original_write(path, value)

    monkeypatch.setattr(cfg, '_write_private_text', fail_env_write)
    response = client.put('/api/settings', json={
        'config': {'server': {'port': 6000}},
        'secrets': {'OPENAI_API_KEY': 'new-secret'},
    })
    assert response.status_code == 500
    if before_config is None:
        assert not config_path.exists()
    else:
        assert config_path.read_bytes() == before_config
    assert cfg.get('server.port') == 5050


@pytest.mark.parametrize(('field', 'value'), [
    ('max_concurrent_runs', 0), ('max_concurrent_runs', 11),
    ('max_price_per_hour', 0.09), ('max_price_per_hour', 5.01),
    ('monthly_budget_usd', -1),
    ('stall_timeout_minutes', 4), ('stall_timeout_minutes', 241),
])
def test_put_rejects_cloud_guardrails_outside_displayed_bounds(client, field, value):
    response = client.put('/api/settings', json={'config': {'cloud': {field: value}}})
    assert response.status_code == 400
    assert f'cloud.{field}' in response.get_json()['error']


def test_put_accepts_cloud_guardrail_boundaries(client):
    response = client.put('/api/settings', json={'config': {'cloud': {
        'max_concurrent_runs': 10,
        'max_price_per_hour': 5,
        'monthly_budget_usd': 0,
        'stall_timeout_minutes': 5,
    }}})
    assert response.status_code == 200


@pytest.mark.parametrize('face_scoring', [
    {'orange': -0.1, 'green': 0.5},
    {'orange': 0.4, 'green': 1.1},
    {'orange': 0.6, 'green': 0.5},
    {'orange': 0.5, 'green': 0.5},
])
def test_put_rejects_invalid_face_score_thresholds(client, face_scoring):
    response = client.put('/api/settings', json={
        'config': {'face_scoring': face_scoring},
    })
    assert response.status_code == 400
    assert 'orange < green' in response.get_json()['error']


@pytest.mark.parametrize('engines', [
    {'enabled': [], 'default': 'klein'},
    {'enabled': ['klein'], 'default': 'chatgpt'},
    {'enabled': ['unknown'], 'default': 'unknown'},
])
def test_put_rejects_contradictory_engine_settings(client, engines):
    response = client.put('/api/settings', json={'config': {'engines': engines}})
    assert response.status_code == 400
    assert 'engine' in response.get_json()['error']

def test_put_settings_autocorrects_portable_base_dir(client, tmp_path):
    """Saving a base_dir that points at the portable WRAPPER
    (...\\ComfyUI_windows_portable) must be rewritten to the nested ...\\ComfyUI
    that actually holds main.py + models/ -- otherwise every model lister scans an
    empty wrapper\\models and reports 'No checkpoint found' even though ComfyUI runs."""
    wrapper = tmp_path / 'ComfyUI_windows_portable'
    inner = wrapper / 'ComfyUI'
    inner.mkdir(parents=True)
    (inner / 'main.py').touch()
    (inner / 'models').mkdir()
    r = client.put('/api/settings', json={'config': {'comfyui': {'base_dir': str(wrapper)}}})
    assert r.status_code == 200
    saved = r.get_json()['config']['comfyui']['base_dir']
    assert pathlib.Path(saved) == inner   # auto-corrected down into the real install

def test_put_settings_keeps_valid_base_dir_unchanged(client, tmp_path):
    """A base_dir already pointing straight at a real ComfyUI install is left as-is."""
    base = tmp_path / 'Comfy'
    base.mkdir()
    (base / 'main.py').touch()
    (base / 'models').mkdir()
    r = client.put('/api/settings', json={'config': {'comfyui': {'base_dir': str(base)}}})
    assert pathlib.Path(r.get_json()['config']['comfyui']['base_dir']) == base

def test_capabilities_endpoint(client):
    caps = client.get('/api/capabilities').get_json()
    assert 'engines' in caps and 'studio_visible' in caps

def test_test_connection_unknown_target(client):
    assert client.post('/api/settings/test/nope').status_code == 404


def test_replicate_connection_target_uses_saved_token(client, monkeypatch):
    monkeypatch.setenv('REPLICATE_API_TOKEN', 'r8-test-token')
    response = client.post('/api/settings/test/replicate')
    assert response.status_code == 200
    assert response.get_json() == {'ok': True, 'detail': 'token set'}


def test_local_vision_connection_target_probes_selected_model(client, monkeypatch):
    from unittest.mock import MagicMock
    saved = client.put('/api/settings', json={'config': {
        'local_vision': {'backend': 'lmstudio'},
        'lmstudio': {
            'url': 'http://127.0.0.1:1234/v1', 'vision_model': 'qwen-vl',
        },
    }})
    assert saved.status_code == 200
    model_list = MagicMock(status_code=200)
    model_list.json.return_value = {'data': [{'id': 'qwen-vl'}]}
    monkeypatch.setattr('app.capabilities.requests.get', lambda *args, **kwargs: model_list)

    response = client.post('/api/settings/test/local_vision')

    assert response.status_code == 200
    assert response.get_json() == {
        'ok': True, 'detail': 'LM Studio and qwen-vl ready',
        'provider': 'lmstudio', 'label': 'LM Studio', 'reachable': True,
        'model_ready': True, 'url': 'http://127.0.0.1:1234/v1',
        'vision_model': 'qwen-vl',
    }


# --- CSRF cookie freshness (long-lived SPA session) ---------------------------
# Flask-WTF time-limits the CSRF token (WTF_CSRF_TIME_LIMIT). The cookie used to
# be planted ONLY on GET /, so a tab left open past that limit kept echoing a
# stale token and every Save/Test POST failed with a cryptic HTML 400 until a hard
# refresh. An after_request hook now re-plants a fresh token on / and every /api
# response — including the CSRF-rejection 400 itself, so the client's one-shot
# retry can recover without a reload.

def _csrf_cookies(resp):
    """The Set-Cookie header(s) that (re)plant csrf_token, if any."""
    return [c for c in resp.headers.getlist('Set-Cookie') if c.startswith('csrf_token=')]


def test_after_request_plants_fresh_csrf_cookie_on_api(client):
    """Any /api response re-plants the csrf_token cookie, JS-readable (not
    HttpOnly, since the SPA must echo it back in the X-CSRFToken header)."""
    r = client.get('/api/health')
    assert r.status_code == 200
    planted = _csrf_cookies(r)
    assert planted, 'csrf_token cookie must be (re)planted on /api responses'
    assert 'HttpOnly' not in planted[0]
    assert 'SameSite=Lax' in planted[0]


def test_static_assets_do_not_replant_csrf_cookie(client):
    """The hook stays quiet on static assets (pure noise) — only / and /api."""
    r = client.get('/assets/does-not-exist.js')
    assert not _csrf_cookies(r)


@pytest.fixture()
def csrf_client(tmp_path, monkeypatch):
    """A client on an app with CSRF actually enforced (the default fixture turns
    it off). Mirrors conftest's app fixture env/cache isolation."""
    monkeypatch.setenv('LDS_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('LDS_CONFIG', str(tmp_path / 'config.json'))
    monkeypatch.setenv('LDS_ENV', str(tmp_path / '.env'))
    import app.config as _cfg
    monkeypatch.setattr(_cfg, 'ENV_PATH', tmp_path / '.env')
    monkeypatch.setattr(_cfg, '_cache', None)
    from app import create_app
    application = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': True,
                              'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    return application.test_client()


def test_csrf_rejection_carries_fresh_cookie_and_allows_retry(csrf_client):
    """A mutating POST with no/stale token is still rejected (400) — but that very
    rejection response re-plants a fresh csrf_token cookie, so the client can read
    it and replay the request once and succeed, with no hard refresh."""
    r = csrf_client.put('/api/settings', json={'config': {'ollama': {'url': 'http://x'}}})
    assert r.status_code == 400                      # token missing -> Flask-WTF rejects
    assert r.headers['X-CSRF-Error'] == '1'
    assert r.get_json()['error_code'] == 'csrf_failed'
    planted = _csrf_cookies(r)
    assert planted, 'the CSRF-rejection response must still refresh the token cookie'
    token = planted[0].split('csrf_token=', 1)[1].split(';', 1)[0]
    # Replay WITH the fresh token in the header (the session cookie rode along on
    # the test client's jar) -> accepted, no longer a 400.
    r2 = csrf_client.put('/api/settings', json={'config': {'ollama': {'url': 'http://x'}}},
                         headers={'X-CSRFToken': token})
    assert r2.status_code == 200
    assert r2.get_json()['config']['ollama']['url'] == 'http://x'


@pytest.fixture()
def _reset_update_cache():
    from app.routes import settings as sroutes
    sroutes._update_cache.update(ts=0.0, data=None)
    sroutes._git_check_cache.update(ts=0.0, data=None)
    yield
    sroutes._update_cache.update(ts=0.0, data=None)
    sroutes._git_check_cache.update(ts=0.0, data=None)


class _FakeResp:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
    def json(self):
        return self._body


def test_failed_git_update_check_is_not_cached(client, monkeypatch,
                                                _reset_update_cache):
    from app.routes import settings as sroutes
    from app.services import updater
    calls = []
    monkeypatch.setattr(updater, 'is_git_checkout', lambda: True)
    monkeypatch.setattr(
        updater, 'git_update_status',
        lambda: calls.append(1) or {
            'ok': False, 'is_git': True, 'update_available': False,
            'reason': 'comparison failed',
        },
    )

    assert client.get('/api/update/check?auto=1').get_json()['ok'] is False
    assert client.get('/api/update/check?auto=1').get_json()['ok'] is False

    assert len(calls) == 2
    assert sroutes._git_check_cache['data'] is None


def test_update_check_detects_newer_release(client, monkeypatch, _reset_update_cache):
    import requests
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _FakeResp(200, {
        'tag_name': 'v9999.12.31', 'html_url': 'https://github.com/x/releases/tag/v9999.12.31'}))
    d = client.get('/api/update/check').get_json()
    assert d['update_available'] is True and d['latest'] == '9999.12.31'
    assert d['url'].endswith('v9999.12.31')


def test_update_check_same_version_and_cache(client, monkeypatch, _reset_update_cache):
    import requests
    from app.version import APP_VERSION
    calls = []
    monkeypatch.setattr(requests, 'get',
                        lambda *a, **k: calls.append(1) or _FakeResp(200, {'tag_name': f'v{APP_VERSION}'}))
    d = client.get('/api/update/check').get_json()
    assert d['update_available'] is False and d['latest'] == APP_VERSION
    client.get('/api/update/check')          # second call served from the 6h cache
    assert len(calls) == 1


def test_update_check_auto_fetches_git_then_serves_cache(client, monkeypatch, _reset_update_cache):
    """auto=1 (nav badge): the git-aware check RUNS (unlike the bare passive
    path) but is served from a TTL cache — SPA loads cost one fetch per 6 h."""
    from app.services import updater
    calls = []
    monkeypatch.setattr(updater, 'is_git_checkout', lambda root=None: True)
    monkeypatch.setattr(updater, 'git_update_status',
                        lambda root=None: calls.append(1) or {
                            'ok': True, 'is_git': True, 'update_available': True,
                            'behind': 2, 'current': '1.0'})
    d = client.get('/api/update/check?auto=1').get_json()
    assert d['update_available'] is True and d['behind'] == 2
    client.get('/api/update/check?auto=1')       # second auto call -> cache
    assert len(calls) == 1
    # a manual force check is always fresh AND refreshes the cache
    client.get('/api/update/check?force=1')
    assert len(calls) == 2


def test_update_check_bare_passive_never_fetches_git(client, monkeypatch, _reset_update_cache):
    """The bare passive path (no force, no auto) must not run the git check."""
    import requests
    from app.services import updater
    monkeypatch.setattr(updater, 'is_git_checkout', lambda root=None: True)
    monkeypatch.setattr(updater, 'git_update_status',
                        lambda root=None: (_ for _ in ()).throw(
                            AssertionError('git check must not run')))
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _FakeResp(404))
    d = client.get('/api/update/check').get_json()
    assert d['ok'] is True


@pytest.mark.parametrize('query', ['force=0', 'force=false', 'auto=no'])
def test_update_check_false_flags_do_not_run_git_check(
        client, monkeypatch, _reset_update_cache, query):
    import requests
    from app.services import updater
    monkeypatch.setattr(updater, 'is_git_checkout', lambda root=None: True)
    monkeypatch.setattr(updater, 'git_update_status',
                        lambda root=None: (_ for _ in ()).throw(
                            AssertionError('git check must not run')))
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _FakeResp(404))
    assert client.get(f'/api/update/check?{query}').status_code == 200


def test_update_check_degrades_when_feed_unreachable(client, monkeypatch, _reset_update_cache):
    import requests
    def boom(*a, **k):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr(requests, 'get', boom)
    d = client.get('/api/update/check').get_json()
    assert d['ok'] is True and d['update_available'] is False
    assert 'unreachable' in d['reason']


def test_update_check_private_repo_404(client, monkeypatch, _reset_update_cache):
    import requests
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _FakeResp(404))
    d = client.get('/api/update/check').get_json()
    assert d['update_available'] is False and '404' in d['reason']


def test_logs_tail_reads_app_log(client, tmp_path, monkeypatch):
    import os
    data_dir = os.environ['LDS_DATA_DIR']    # tmp dir set by the app fixture
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, 'app.log'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(f'line {i}' for i in range(500)) + '\n')
    d = client.get('/api/logs/tail?n=100').get_json()
    assert d['ok'] is True and d['file'] == 'app.log'
    assert len(d['lines']) == 100 and d['lines'][-1] == 'line 499'


def test_logs_tail_empty_when_no_log(client):
    d = client.get('/api/logs/tail').get_json()
    assert d == {'ok': True, 'file': None, 'lines': []}


def test_chatgpt_oauth_routes(client, monkeypatch):
    from unittest.mock import patch
    from app.services import chatgpt_oauth
    with patch.object(chatgpt_oauth, 'login_start',
                      return_value={'ok': True, 'verification_url': 'https://x/device',
                                    'user_code': 'AB-12'}):
        r = client.post('/api/settings/chatgpt-oauth/start')
        assert r.status_code == 200 and r.get_json()['user_code'] == 'AB-12'
    with patch.object(chatgpt_oauth, 'login_start',
                      return_value={'ok': False, 'detail': 'network error'}):
        assert client.post('/api/settings/chatgpt-oauth/start').status_code == 502
    with patch.object(chatgpt_oauth, 'login_poll', return_value={'status': 'pending',
                                                                 'detail': None}):
        r = client.get('/api/settings/chatgpt-oauth/poll')
        assert r.status_code == 200 and r.get_json()['status'] == 'pending'
    with patch.object(chatgpt_oauth, 'import_codex_cli',
                      return_value={'ok': False, 'detail': 'no session'}):
        assert client.post('/api/settings/chatgpt-oauth/import-codex').status_code == 404
    with patch.object(chatgpt_oauth, 'import_codex_cli',
                      return_value={'ok': True, 'detail': 'imported'}):
        assert client.post('/api/settings/chatgpt-oauth/import-codex').status_code == 200
    r = client.post('/api/settings/chatgpt-oauth/logout')
    assert r.status_code == 200 and r.get_json()['ok'] is True


def test_put_settings_saves_chatgpt_auth_mode(client):
    r = client.put('/api/settings', json={'config': {'engines': {'chatgpt_auth': 'subscription'}}})
    assert r.status_code == 200
    assert r.get_json()['config']['engines']['chatgpt_auth'] == 'subscription'


# --- Server settings (host/port/LAN/access token) ----------------------------
def test_settings_payload_includes_server_defaults(client):
    cfg = client.get('/api/settings').get_json()['config']
    assert cfg['server'] == {'host': '127.0.0.1', 'port': 5050,
                             'require_token': True, 'access_token': ''}


def test_put_settings_saves_require_token(client):
    r = client.put('/api/settings', json={'config': {'server': {'require_token': True}}})
    assert r.status_code == 200
    assert r.get_json()['config']['server']['require_token'] is True


def test_settings_restart_pins_saved_host_port_to_env(client, monkeypatch):
    """The launcher exports LDS_PORT, which otherwise wins over config forever.
    The restart route must stamp the SAVED host/port into env so the relaunch
    actually binds where the user asked (else the port field looks broken)."""
    import os
    from app.services import updater
    monkeypatch.setattr(updater, 'schedule_restart', lambda *a, **k: None)
    monkeypatch.delenv('LDS_PORT', raising=False)
    monkeypatch.delenv('LDS_HOST', raising=False)
    client.put('/api/settings', json={'config': {'server': {'host': '0.0.0.0', 'port': 5123}}})
    client.post('/api/settings/restart')
    assert os.environ['LDS_HOST'] == '0.0.0.0'
    assert os.environ['LDS_PORT'] == '5123'


def test_put_settings_saves_server_lan_and_port(client):
    r = client.put('/api/settings', json={'config': {'server': {'host': '0.0.0.0', 'port': 5001}}})
    assert r.status_code == 200
    assert r.get_json()['config']['server']['host'] == '0.0.0.0'
    assert r.get_json()['config']['server']['port'] == 5001


def test_runtime_reflects_what_run_py_stamped_on_boot(client, app):
    """Before run.py's __main__ block runs (dev/test boots go through create_app()
    directly), nothing has been bound yet -- the card must show that as 'unknown',
    never fabricate a value that looks like a real running bind."""
    rt = client.get('/api/settings').get_json()['runtime']
    assert (rt['host'], rt['port']) == (None, None)   # lan_ip is orthogonal (see its own test)
    app.config['LDS_BOUND_HOST'] = '0.0.0.0'
    app.config['LDS_BOUND_PORT'] = 5000
    rt = client.get('/api/settings').get_json()['runtime']
    assert (rt['host'], rt['port']) == ('0.0.0.0', 5000)


def test_runtime_can_differ_from_saved_config_until_restart(client, app):
    """Saving a new port must NOT retroactively change what's reported as running --
    that would lie about a bind change that hasn't taken effect yet."""
    app.config['LDS_BOUND_HOST'] = '127.0.0.1'
    app.config['LDS_BOUND_PORT'] = 5000
    client.put('/api/settings', json={'config': {'server': {'host': '0.0.0.0', 'port': 5001}}})
    data = client.get('/api/settings').get_json()
    assert data['config']['server']['port'] == 5001
    assert (data['runtime']['host'], data['runtime']['port']) == ('127.0.0.1', 5000)


def test_settings_runtime_includes_lan_ip(client):
    """The Server card builds a real copyable http://<ip>:port/ URL from this;
    it's the machine's primary LAN IPv4, or None (UI falls back to a placeholder)
    when offline / loopback-only. It must never be a loopback address."""
    runtime = client.get('/api/settings').get_json()['runtime']
    assert 'lan_ip' in runtime
    ip = runtime['lan_ip']
    assert ip is None or (isinstance(ip, str) and not ip.startswith('127.'))


def test_settings_runtime_includes_tailscale_ip(client):
    """The Server card offers a Tailscale URL beside the LAN one as the phone's
    off-perimeter path. It's a tailnet address (100.64.0.0/10) or None when the
    tunnel is down — never a bare LAN IP masquerading as a tailnet address."""
    from app.routes import settings as sroutes
    runtime = client.get('/api/settings').get_json()['runtime']
    assert 'tailscale_ip' in runtime
    ip = runtime['tailscale_ip']
    assert ip is None or sroutes._is_cgnat(ip)


def test_is_cgnat_classifies_tailscale_range():
    """Only 100.64.0.0/10 (Tailscale's CGNAT block) counts — a real LAN IP or a
    100.x address outside the block must not be mistaken for a tailnet address."""
    from app.routes import settings as sroutes
    assert sroutes._is_cgnat('100.87.119.32') is True     # in-block (real tailnet IP)
    assert sroutes._is_cgnat('100.64.0.1') is True        # lower edge
    assert sroutes._is_cgnat('100.127.255.254') is True   # upper edge
    assert sroutes._is_cgnat('100.63.255.255') is False   # just below the block
    assert sroutes._is_cgnat('100.128.0.1') is False      # just above the block
    assert sroutes._is_cgnat('192.168.1.162') is False    # a real LAN IP
    assert sroutes._is_cgnat('') is False
    assert sroutes._is_cgnat(None) is False


@pytest.mark.parametrize('value', [
    '100.64', '100.64.nope', '100.64.0.1.2', '100.64.256.1', '100.64.-1.1',
])
def test_is_cgnat_rejects_malformed_addresses(value):
    from app.routes import settings as sroutes
    assert sroutes._is_cgnat(value) is False


@pytest.mark.parametrize('query', ['0', 'false', 'no'])
def test_capabilities_false_force_flag_uses_cached_probe(client, monkeypatch, query):
    from app import capabilities
    calls = []
    monkeypatch.setattr(capabilities, 'probe',
                        lambda force=False: calls.append(force) or {'ok': True})
    assert client.get(f'/api/capabilities?force={query}').status_code == 200
    assert calls == [False]


def test_settings_restart_triggers_schedule_restart(client, monkeypatch):
    from app.services import updater
    called = []
    monkeypatch.setattr(updater, 'schedule_restart', lambda *a, **k: called.append(1))
    r = client.post('/api/settings/restart')
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True and body['restarting'] is True
    assert len(body['restart_nonce']) == 32
    assert called == [1]


def test_settings_restart_refuses_active_package_mutation(client, monkeypatch):
    from app import setup_installer
    from app.services import updater
    called = []
    monkeypatch.setattr(
        setup_installer, 'active_pip_mutations', lambda: ['ml_extras'])
    monkeypatch.setattr(updater, 'schedule_restart', lambda: called.append(True))

    response = client.post('/api/settings/restart')

    assert response.status_code == 409
    assert response.get_json()['active_installs'] == ['ml_extras']
    assert called == []
