from unittest.mock import patch
import multiprocessing
import os
import pathlib
import threading
import time
import pytest


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch):
    """Import-probes (face_scoring/masks) shell out to python -c 'import ...'.
    Stub the seam so the suite never spawns a real subprocess; individual
    tests that care about the ok/False split re-patch it locally."""
    from app import capabilities
    capabilities._import_cache.clear()
    capabilities._cache = None
    capabilities._cache_ts = 0.0
    monkeypatch.setattr(capabilities, '_import_ok', lambda *a, **k: False)
    yield
    capabilities._import_cache.clear()
    capabilities._cache = None
    capabilities._cache_ts = 0.0


# --- brief tests, verbatim ---------------------------------------------

def test_probe_all_off_when_unconfigured(app):
    with app.app_context():
        from app import capabilities
        with patch('app.capabilities._http_ok', return_value=False):
            caps = capabilities.probe(force=True)
    assert caps['engines'] == {'nanobanana': False, 'chatgpt': False, 'klein': False}
    assert caps['training_visible'] is False and caps['studio_visible'] is False

def test_python_ml_status_reports_version_and_range(app):
    """The probe exposes the interpreter version + whether it's inside the ML-wheel
    range (3.11–3.12), so the setup can warn before a doomed pip install."""
    with app.app_context():
        from app import capabilities
        with patch('app.capabilities._http_ok', return_value=False):
            caps = capabilities.probe(force=True)
    py = caps['python']
    assert py['ml_range'] == '3.11–3.12'
    assert isinstance(py['ml_supported'], bool)
    # ml_supported must agree with the reported version's minor.
    major, minor = (int(x) for x in py['version'].split('.')[:2])
    assert py['ml_supported'] == (major == 3 and 11 <= minor <= 12)


@pytest.mark.parametrize('info,ok', [((3, 9, 1), False), ((3, 10, 0), False),
                                     ((3, 12, 9), True), ((3, 13, 0), False), ((3, 14, 0), False)])
def test_python_ml_status_boundaries(app, info, ok):
    import types
    with app.app_context():
        from app import capabilities
        vi = types.SimpleNamespace(major=info[0], minor=info[1], micro=info[2])
        with patch('app.capabilities.sys.version_info', vi):
            st = capabilities.python_ml_status()
    assert st['ml_supported'] is ok
    assert st['version'] == f'{info[0]}.{info[1]}.{info[2]}'


def test_chatgpt_on_with_key(app, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-x')
    with app.app_context():
        from app import capabilities
        with patch('app.capabilities._http_ok', return_value=False):
            caps = capabilities.probe(force=True)
    assert caps['engines']['chatgpt'] is True

def test_comfyui_reachable_lights_studio_and_klein(app, monkeypatch, tmp_path):
    monkeypatch.setenv('OPENAI_API_KEY', '')
    with app.app_context():
        from app import capabilities, config
        base = tmp_path / 'Comfy'
        (base / 'models' / 'unet' / 'klein').mkdir(parents=True)
        (base / 'models' / 'unet' / 'klein' / 'k.safetensors').touch()
        config.save_config({'comfyui': {'base_dir': str(base)}})
        with patch('app.capabilities._http_ok', return_value=True):
            caps = capabilities.probe(force=True)
    assert caps['comfyui']['reachable'] is True
    assert caps['studio_visible'] is True
    assert caps['engines']['klein'] is True


# --- extra coverage: individual probe_* ok/detail contract --------------

def test_probe_gemini_missing_key(app, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with app.app_context():
        from app import capabilities
        result = capabilities.probe_gemini()
    assert result == {'ok': False, 'detail': 'key missing'}

def test_probe_gemini_with_key(app, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'g-x')
    with app.app_context():
        from app import capabilities
        result = capabilities.probe_gemini()
    assert result == {'ok': True, 'detail': 'key set'}


def test_selected_replicate_provider_controls_nanobanana_readiness(app, monkeypatch):
    from app import capabilities, config
    config.save_config({'engines': {'nanobanana_provider': 'replicate'}})
    monkeypatch.setenv('GEMINI_API_KEY', 'google-key-is-not-selected')
    monkeypatch.delenv('REPLICATE_API_TOKEN', raising=False)

    with patch('app.capabilities._http_ok', return_value=False):
        unavailable = capabilities.probe(force=True)
    assert unavailable['engines']['nanobanana'] is False

    monkeypatch.setenv('REPLICATE_API_TOKEN', 'replicate-token')
    with patch('app.capabilities._http_ok', return_value=False):
        available = capabilities.probe(force=True)
    assert available['engines']['nanobanana'] is True

def test_probe_openai_missing_key(app, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with app.app_context():
        from app import capabilities
        result = capabilities.probe_openai()
    assert result == {'ok': False, 'detail': 'key missing'}


def test_probe_openai_api_reports_exhausted_credits(app, monkeypatch):
    from app import capabilities

    class Response:
        status_code = 429

        def json(self):
            return {'error': {'code': 'credit_balance_exhausted'}}

    monkeypatch.setattr(capabilities.cfg, 'secret', lambda name: 'secret')
    monkeypatch.setattr(capabilities.requests, 'post', lambda *args, **kwargs: Response())

    with app.app_context():
        result = capabilities.probe_openai_api()

    assert result == {
        'ok': False,
        'detail': 'API credit balance exhausted — add credits in OpenAI billing',
        'code': 'credit_balance_exhausted',
    }

def test_probe_aitoolkit_invalid_when_unconfigured(app):
    with app.app_context():
        from app import capabilities
        result = capabilities.probe_aitoolkit()
    assert result['ok'] is False

def test_probe_aitoolkit_invalid_when_dir_set_but_incomplete(app, tmp_path):
    with app.app_context():
        from app import capabilities, config
        root = tmp_path / 'aitoolkit'
        root.mkdir()  # exists, but no run.py, no venv
        config.save_config({'aitoolkit': {'dir': str(root)}})
        result = capabilities.probe_aitoolkit()
    assert result['ok'] is False

def test_probe_aitoolkit_valid(app, tmp_path):
    with app.app_context():
        from app import capabilities, config
        root = tmp_path / 'aitoolkit'
        (root / 'venv' / 'Scripts').mkdir(parents=True)
        (root / 'venv' / 'Scripts' / 'python.exe').touch()
        (root / 'run.py').touch()
        config.save_config({'aitoolkit': {'dir': str(root)}})
        result = capabilities.probe_aitoolkit()
    assert result['ok'] is True

def test_probe_comfyui_unreachable(app):
    with app.app_context():
        from app import capabilities
        with patch('app.capabilities._http_ok', return_value=False):
            result = capabilities.probe_comfyui()
    assert result['ok'] is False

def test_probe_ollama_reachable(app):
    with app.app_context():
        from app import capabilities
        with patch('app.capabilities._http_ok', return_value=True):
            result = capabilities.probe_ollama()
    assert result['ok'] is True

def test_probe_face_scoring_goes_through_import_seam(app, monkeypatch):
    with app.app_context():
        from app import capabilities
        monkeypatch.setattr(capabilities, '_import_ok', lambda *a, **k: True)
        capabilities._import_cache.clear()
        result = capabilities.probe_face_scoring()
    assert result == {'ok': True, 'detail': 'insightface + onnxruntime import OK'}

def test_probe_masks_goes_through_import_seam(app, monkeypatch):
    with app.app_context():
        from app import capabilities
        monkeypatch.setattr(capabilities, '_import_ok', lambda *a, **k: True)
        capabilities._import_cache.clear()
        result = capabilities.probe_masks()
    assert result == {'ok': True, 'detail': 'rembg import OK'}

def test_import_probe_result_is_cached(app, monkeypatch):
    """Second call within the 10 min TTL must not re-invoke the seam."""
    with app.app_context():
        from app import capabilities
        calls = []
        monkeypatch.setattr(capabilities, '_import_ok', lambda *a, **k: calls.append(1) or True)
        capabilities._import_cache.clear()
        capabilities.probe_face_scoring()
        capabilities.probe_face_scoring()
    assert len(calls) == 1


def test_import_probe_timeout_is_not_cached_as_failure(app, monkeypatch):
    """_import_ok → None (subprocess TIMEOUT, e.g. rembg's first cold import
    compiling numba caches) must report not-ready NOW but not poison the 10 min
    cache: the next probe re-tries (warm import ~1 s → ✓). A real import error
    (False) stays cached as before."""
    with app.app_context():
        from app import capabilities
        calls = []
        monkeypatch.setattr(capabilities, '_import_ok',
                            lambda *a, **k: calls.append(1) or None)   # timeout
        capabilities._import_cache.clear()
        assert capabilities.probe_masks()['ok'] is False
        assert capabilities.probe_masks()['ok'] is False
        assert len(calls) == 2                       # re-probed: nothing cached
        monkeypatch.setattr(capabilities, '_import_ok',
                            lambda *a, **k: calls.append(1) or False)  # real failure
        assert capabilities.probe_masks()['ok'] is False
        assert capabilities.probe_masks()['ok'] is False
        assert len(calls) == 3                       # cached after the real False


def test_import_probe_cache_key_includes_interpreter_path(app, monkeypatch):
    """Changing interpreter path should invalidate the import cache."""
    with app.app_context():
        from app import capabilities, config

        # First call: interpreter A returns True
        monkeypatch.setattr(capabilities, '_import_ok', lambda *a, **k: True)
        capabilities._import_cache.clear()
        result1 = capabilities.probe_face_scoring()
        assert result1['ok'] is True

        # Second call: same interpreter, should use cache and return True
        monkeypatch.setattr(capabilities, '_import_ok', lambda *a, **k: False)
        result2 = capabilities.probe_face_scoring()
        assert result2['ok'] is True  # cached result

        # Third call: different interpreter path, should bypass cache and return False
        config.save_config({'face_scoring': {'python': '/different/python/path'}})
        result3 = capabilities.probe_face_scoring()
        assert result3['ok'] is False  # new interpreter, not cached


# --- model listing scan rules --------------------------------------------

def test_scan_models_empty_when_comfyui_unset(app):
    with app.app_context():
        from app import capabilities
        models = capabilities._scan_models()
    assert models == {'zimage': [], 'sdxl': [], 'krea': [], 'klein': []}

def test_scan_models_matches_rules(app, tmp_path):
    with app.app_context():
        from app import capabilities, config
        base = tmp_path / 'Comfy'
        (base / 'models' / 'unet' / 'Z-Image').mkdir(parents=True)
        (base / 'models' / 'unet' / 'Z-Image' / 'a.safetensors').touch()
        (base / 'models' / 'unet' / 'Z-Image' / 'notes.txt').touch()   # filtered out
        (base / 'models' / 'unet' / 'krea-turbo').mkdir(parents=True)
        (base / 'models' / 'unet' / 'krea-turbo' / 'k.gguf').touch()
        (base / 'models' / 'unet' / 'klein').mkdir(parents=True)
        (base / 'models' / 'unet' / 'klein' / 'k.safetensors').touch()
        (base / 'models' / 'checkpoints').mkdir(parents=True)
        (base / 'models' / 'checkpoints' / 'sdxl_base.safetensors').touch()
        config.save_config({'comfyui': {'base_dir': str(base)}})
        models = capabilities._scan_models()
    assert models['zimage'] == ['a.safetensors']
    assert models['krea'] == ['k.gguf']
    assert models['klein'] == ['k.safetensors']
    assert models['sdxl'] == ['sdxl_base.safetensors']

def test_scan_models_never_raises_on_absent_dir(app, tmp_path):
    with app.app_context():
        from app import capabilities, config
        config.save_config({'comfyui': {'base_dir': str(tmp_path / 'does_not_exist')}})
        models = capabilities._scan_models()
    assert models == {'zimage': [], 'sdxl': [], 'krea': [], 'klein': []}


# --- resolve_comfyui_base: portable-wrapper nesting ----------------------

def _make_comfyui(root):
    """Minimal ComfyUI marker: main.py + models/ is what _is_comfyui_dir checks."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'main.py').touch()
    (root / 'models').mkdir()


def test_resolve_comfyui_base_direct(tmp_path):
    from app.capabilities import resolve_comfyui_base
    _make_comfyui(tmp_path)
    r = resolve_comfyui_base(str(tmp_path))
    assert r['valid'] is True and r['nested'] is False
    assert pathlib.Path(r['resolved']) == tmp_path

def test_resolve_comfyui_base_portable_nested(tmp_path):
    """User points at ...\\ComfyUI_windows_portable; the real install is one level
    down in .../ComfyUI. resolve descends and flags nested=True so the caller
    can auto-correct base_dir."""
    from app.capabilities import resolve_comfyui_base
    wrapper = tmp_path / 'ComfyUI_windows_portable'
    _make_comfyui(wrapper / 'ComfyUI')
    r = resolve_comfyui_base(str(wrapper))
    assert r['valid'] is True and r['nested'] is True
    assert pathlib.Path(r['resolved']) == wrapper / 'ComfyUI'

def test_resolve_comfyui_base_invalid(tmp_path):
    from app.capabilities import resolve_comfyui_base
    r = resolve_comfyui_base(str(tmp_path))   # empty dir, no main.py/models
    assert r['valid'] is False and r['nested'] is False
    assert pathlib.Path(r['resolved']) == tmp_path

def test_resolve_comfyui_base_empty():
    from app.capabilities import resolve_comfyui_base
    assert resolve_comfyui_base('') == {'valid': False, 'resolved': '', 'nested': False}

def test_comfyui_folder_launcher_uses_its_own_mac_venv(tmp_path):
    from app.capabilities import _comfyui_folder_launcher
    install = tmp_path / 'ComfyUI'
    (install / '.venv' / 'bin').mkdir(parents=True)
    (install / '.venv' / 'bin' / 'python').touch()
    (install / 'main.py').touch()

    assert _comfyui_folder_launcher(str(install)) == {
        'cwd': str(install),
        'command': './.venv/bin/python main.py --listen 127.0.0.1 --port 8188',
        'managed_by_desktop': False,
    }


def test_comfyui_folder_launcher_identifies_desktop_managed_install(tmp_path):
    from app.capabilities import _comfyui_folder_launcher
    install = tmp_path / 'ComfyUI'
    (install / '.venv' / 'bin').mkdir(parents=True)
    (install / '.venv' / 'bin' / 'python').touch()
    (install / 'main.py').touch()
    (install / '.comfy_environment').write_text('local-desktop2-standalone')

    launcher = _comfyui_folder_launcher(str(install))

    assert launcher['managed_by_desktop'] is True


def test_comfyui_install_type_does_not_depend_on_a_terminal_launcher(tmp_path):
    from app.capabilities import _comfyui_install_type
    desktop = tmp_path / 'desktop' / 'ComfyUI'
    desktop.mkdir(parents=True)
    (desktop / '.comfy_environment').write_text('local-desktop2-standalone')
    git_clone = tmp_path / 'git' / 'ComfyUI'
    git_clone.mkdir(parents=True)
    (git_clone / 'main.py').touch()

    assert _comfyui_install_type(str(desktop)) == 'desktop'
    assert _comfyui_install_type(str(git_clone)) == 'git'
    assert _comfyui_install_type(str(tmp_path / 'missing')) == ''

def test_probe_exposes_dir_valid(app, tmp_path):
    """probe() surfaces dir_configured/dir_valid/resolved_dir so the wizard can
    tell a wrong path from a right one without a second round-trip."""
    with app.app_context():
        from app import capabilities, config
        _make_comfyui(tmp_path / 'ComfyUI')
        python = tmp_path / 'ComfyUI' / '.venv' / 'bin' / 'python'
        python.parent.mkdir(parents=True)
        python.touch()
        config.save_config({'comfyui': {'base_dir': str(tmp_path)}})   # wrapper, nested install
        with patch('app.capabilities._http_ok', return_value=False):
            caps = capabilities.probe(force=True)
    c = caps['comfyui']
    assert c['dir_configured'] is True and c['dir_valid'] is True
    assert pathlib.Path(c['resolved_dir']) == tmp_path / 'ComfyUI'
    assert c['install_type'] == 'git'
    assert c['folder_launcher']['cwd'] == str(tmp_path / 'ComfyUI')


# --- probe() caching ------------------------------------------------------

def test_probe_caches_for_30s_without_force(app, monkeypatch):
    with app.app_context():
        from app import capabilities
        capabilities._cache = None
        capabilities._cache_ts = 0.0
        with patch('app.capabilities._http_ok', return_value=False):
            first = capabilities.probe(force=True)
            monkeypatch.setenv('OPENAI_API_KEY', 'sk-new')
            second = capabilities.probe()  # stale cache, ignores the new key
    assert second == first
    assert second['engines']['chatgpt'] is False

def test_probe_force_bypasses_cache(app, monkeypatch):
    with app.app_context():
        from app import capabilities
        monkeypatch.setattr(capabilities, '_clock', lambda: 1.0)
        with patch('app.capabilities._http_ok', return_value=False):
            capabilities.probe(force=True)
            monkeypatch.setenv('OPENAI_API_KEY', 'sk-new')
            refreshed = capabilities.probe(force=True)
    assert refreshed['engines']['chatgpt'] is True


def test_probe_uses_one_subscription_snapshot(app, monkeypatch):
    from app import capabilities
    from app.services import chatgpt_oauth

    statuses = iter((_sub(False), _sub(True, 'later@example.test')))
    monkeypatch.setattr(chatgpt_oauth, 'status', lambda: next(statuses))
    with app.app_context(), patch('app.capabilities._http_ok', return_value=False):
        result = capabilities.probe(force=True)

    assert result['engines']['chatgpt'] is False
    assert result['chatgpt_subscription']['connected'] is False
    # A second status read would have consumed the connected snapshot.
    assert next(statuses)['connected'] is True


def test_capability_ttls_use_monotonic_clock(app, monkeypatch):
    from app import capabilities

    current = [100.0]
    monkeypatch.setattr(capabilities, '_clock', lambda: current[0])
    with app.app_context(), patch('app.capabilities._http_ok', return_value=False):
        first = capabilities.probe(force=True)
        monkeypatch.setenv('OPENAI_API_KEY', 'sk-after-expiry')
        current[0] = 131.0
        second = capabilities.probe()

    assert first['engines']['chatgpt'] is False
    assert second['engines']['chatgpt'] is True


def test_import_cache_ttl_uses_monotonic_clock(monkeypatch):
    from app import capabilities

    current = [50.0]
    probes = []
    monkeypatch.setattr(capabilities, '_clock', lambda: current[0])
    monkeypatch.setattr(
        capabilities, '_import_ok', lambda *_args: probes.append(current[0]) or True)

    assert capabilities._cached_import('x', 'python', 'import x') is True
    current[0] = 649.0
    assert capabilities._cached_import('x', 'python', 'import x') is True
    current[0] = 651.0
    assert capabilities._cached_import('x', 'python', 'import x') is True
    assert probes == [50.0, 651.0]


def test_gpu_cache_ttl_uses_monotonic_clock(monkeypatch):
    from types import SimpleNamespace
    from app import capabilities

    current = [10.0]
    calls = []
    monkeypatch.setattr(capabilities, '_clock', lambda: current[0])
    monkeypatch.setattr(capabilities.subprocess, 'run', lambda *_args, **_kwargs:
                        calls.append(current[0]) or
                        SimpleNamespace(returncode=0, stdout='8192\n'))
    capabilities._gpu_cache.update(ts=0.0, gb=None)

    assert capabilities.gpu_vram_gb() == 8.0
    current[0] = 609.0
    assert capabilities.gpu_vram_gb() == 8.0
    current[0] = 611.0
    assert capabilities.gpu_vram_gb() == 8.0
    assert calls == [10.0, 611.0]


# --- ollama vision-model presence + import-cache clear --------------------

def test_ollama_vision_model_ready_true(app, monkeypatch):
    with app.app_context():
        from app import capabilities, config
        config.save_config({'ollama': {'url': 'http://o', 'vision_model': 'qwen3-vl:8b'}})
        monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: True)
        monkeypatch.setattr(capabilities, '_ollama_tags', lambda *a, **k: ['qwen3-vl:8b'])
        result = capabilities.probe_ollama_model()
    assert result['ok'] is True

def test_ollama_vision_model_ready_false_when_absent(app, monkeypatch):
    with app.app_context():
        from app import capabilities, config
        config.save_config({'ollama': {'url': 'http://o', 'vision_model': 'qwen3-vl:8b'}})
        monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: True)
        monkeypatch.setattr(capabilities, '_ollama_tags', lambda *a, **k: ['llama3:8b'])
        result = capabilities.probe_ollama_model()
    assert result['ok'] is False

def test_ollama_vision_model_base_tag_match(app, monkeypatch):
    with app.app_context():
        from app import capabilities, config
        config.save_config({'ollama': {'url': 'http://o', 'vision_model': 'qwen3-vl'}})
        monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: True)
        monkeypatch.setattr(capabilities, '_ollama_tags', lambda *a, **k: ['qwen3-vl:8b'])
        result = capabilities.probe_ollama_model()
    assert result['ok'] is True


def test_ollama_tagged_model_does_not_match_different_tag():
    from app.capabilities import _model_present

    assert _model_present('qwen3-vl:8b-instruct', ['qwen3-vl:8b-thinking']) is False


def _concurrent_forced_probe_harness(connection, temp_root):
    """Run the thread-level proof in a process the parent can terminate safely."""
    os.environ['LDS_DATA_DIR'] = str(pathlib.Path(temp_root) / 'data')
    os.environ['LDS_CONFIG'] = str(pathlib.Path(temp_root) / 'config.json')
    os.environ['LDS_ENV'] = str(pathlib.Path(temp_root) / '.env')

    from app import capabilities, config, create_app

    config.ENV_PATH = pathlib.Path(temp_root) / '.env'
    config._cache = None
    application = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })
    capabilities._import_cache.clear()
    capabilities._cache = None
    capabilities._cache_ts = 0.0

    import_calls = []
    calls_lock = threading.Lock()

    def counted_import(python, module_expr, timeout=60):
        with calls_lock:
            import_calls.append((python, module_expr, timeout))
        return False

    worker_count = 3
    deadline = time.monotonic() + 5

    class CoordinatedLock:
        def __init__(self):
            self._backing = threading.Lock()
            self._entrants = threading.Barrier(worker_count)

        def __enter__(self):
            # probe() captures _cache_generation immediately before entering
            # this lock. The barrier therefore proves every caller captured
            # the same generation before any caller can start the refresh.
            self._entrants.wait(timeout=max(0, deadline - time.monotonic()))
            self._backing.acquire()
            return self

        def __exit__(self, *exc_info):
            self._backing.release()

    generation_before = capabilities._cache_generation
    capabilities._probe_lock = CoordinatedLock()
    capabilities._http_ok = lambda *args, **kwargs: False

    def disabled_request(*args, **kwargs):
        raise capabilities.requests.ConnectionError('network disabled in test')

    capabilities.requests.get = disabled_request
    capabilities._import_ok = counted_import
    results = []
    worker_errors = []

    def run_probe():
        try:
            with application.app_context():
                results.append(capabilities.probe(force=True))
        except BaseException as exc:
            worker_errors.append(repr(exc))

    connection.send({'status': 'ready'})
    workers = [threading.Thread(target=run_probe, daemon=True)
               for _ in range(worker_count)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=max(0, deadline - time.monotonic()))

    connection.send({
        'status': 'result',
        'finished': all(not worker.is_alive() for worker in workers),
        'worker_errors': worker_errors,
        'result_count': len(results),
        'snapshots_equal': len(results) == worker_count and results[1:] == results[:-1],
        'generation_delta': capabilities._cache_generation - generation_before,
        'module_exprs': sorted(call[1] for call in import_calls),
        'timeouts': [call[2] for call in import_calls],
    })
    connection.close()


def test_concurrent_forced_probes_share_one_refresh(tmp_path):
    context = multiprocessing.get_context('spawn')
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_concurrent_forced_probe_harness,
        args=(child_connection, str(tmp_path)),
    )
    process.start()
    child_connection.close()

    try:
        assert parent_connection.poll(10), 'probe harness did not initialize'
        assert parent_connection.recv() == {'status': 'ready'}
        assert parent_connection.poll(5), 'concurrent probe harness exceeded 5 seconds'
        result = parent_connection.recv()
        process.join(timeout=1)
        exited_cleanly = not process.is_alive()
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent_connection.close()

    assert exited_cleanly
    assert process.exitcode == 0
    assert result['status'] == 'result'
    assert result['finished'] is True
    assert result['worker_errors'] == []
    assert result['result_count'] == 3
    assert result['snapshots_equal'] is True
    assert result['generation_delta'] == 1
    assert result['module_exprs'] == sorted((
        'import insightface, onnxruntime',
        'import rembg',
        'import cv2, numpy, torch; from PIL import Image',
    ))
    assert result['timeouts'] == [60, 60, 60]

def test_ollama_vision_model_false_when_unreachable(app, monkeypatch):
    with app.app_context():
        from app import capabilities, config
        config.save_config({'ollama': {'url': 'http://o', 'vision_model': 'qwen3-vl:8b'}})
        monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: False)
        # _ollama_tags must not even be consulted when unreachable:
        monkeypatch.setattr(capabilities, '_ollama_tags',
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError('called')))
        result = capabilities.probe_ollama_model()
    assert result['ok'] is False

def test_probe_exposes_vision_model_fields(app, monkeypatch):
    with app.app_context():
        from app import capabilities, config
        config.save_config({'ollama': {'url': 'http://o', 'vision_model': 'qwen3-vl:8b'}})
        monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: True)
        monkeypatch.setattr(capabilities, '_ollama_tags', lambda *a, **k: ['qwen3-vl:8b'])
        caps = capabilities.probe(force=True)
    assert caps['ollama']['vision_model'] == 'qwen3-vl:8b'
    assert caps['ollama']['vision_model_ready'] is True

def test_clear_import_cache_empties_caches(app, monkeypatch):
    with app.app_context():
        from app import capabilities
        monkeypatch.setattr(capabilities, '_import_ok', lambda *a, **k: True)
        capabilities.probe_face_scoring()          # populates _import_cache
        assert capabilities._import_cache
        capabilities._cache = {'x': 1}
        capabilities._cache_ts = 123.0
        capabilities.clear_import_cache()
    assert capabilities._import_cache == {}
    assert capabilities._cache is None

def test_probe_ollama_model_uses_passed_reachability(app, monkeypatch):
    """probe() supplies the already-computed reachability so probe_ollama_model
    does not re-hit _http_ok — avoids the redundant/doubled /api/tags call."""
    with app.app_context():
        from app import capabilities, config
        config.save_config({'ollama': {'url': 'http://o', 'vision_model': 'qwen3-vl:8b'}})
        http_calls = []
        monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: http_calls.append(1) or True)
        monkeypatch.setattr(capabilities, '_ollama_tags', lambda *a, **k: ['qwen3-vl:8b'])
        ready = capabilities.probe_ollama_model(reachable=True)
        monkeypatch.setattr(capabilities, '_ollama_tags',
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError('tags fetched')))
        down = capabilities.probe_ollama_model(reachable=False)
    assert ready['ok'] is True
    assert http_calls == []          # reachability supplied, not re-fetched
    assert down['ok'] is False       # short-circuited without fetching tags


# --- Task 5: probe_openai() matrix + chatgpt_subscription payload ---------

def _sub(connected, email=None):
    return {'connected': connected, 'email': email, 'plan': 'plus' if connected else None}


def test_probe_openai_matrix(app, monkeypatch):
    from unittest.mock import patch
    from app import capabilities
    from app.services import chatgpt_oauth
    # neither
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with patch.object(chatgpt_oauth, 'status', return_value=_sub(False)):
        r = capabilities.probe_openai()
        assert r['ok'] is False and r['detail'] == 'key missing'
    # key only
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-x')
    with patch.object(chatgpt_oauth, 'status', return_value=_sub(False)):
        r = capabilities.probe_openai()
        assert r['ok'] is True and r['detail'] == 'key set'
    # subscription only
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with patch.object(chatgpt_oauth, 'status', return_value=_sub(True, 'u@x.io')):
        r = capabilities.probe_openai()
        assert r['ok'] is True and r['detail'] == 'subscription connected'
    # both
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-x')
    with patch.object(chatgpt_oauth, 'status', return_value=_sub(True, 'u@x.io')):
        r = capabilities.probe_openai()
        assert r['ok'] is True and r['detail'] == 'key set + subscription connected'


def test_probe_exposes_chatgpt_subscription_block(app, monkeypatch):
    from unittest.mock import patch
    from app import capabilities
    from app.services import chatgpt_oauth
    with patch.object(chatgpt_oauth, 'status', return_value=_sub(True, 'u@x.io')):
        caps = capabilities.probe(force=True)
    sub = caps['chatgpt_subscription']
    assert sub['connected'] is True
    assert sub['email'] == 'u@x.io'
    assert isinstance(sub['codex_cli_detected'], bool)
    assert caps['engines']['chatgpt'] is True     # subscription alone enables the engine


def test_probe_aitoolkit_accepts_dot_venv_and_explicit_python(app, tmp_path, monkeypatch):
    """Installs without `venv/` exist in the wild (Reddit-reported): `.venv/`
    must be auto-detected, and an explicit aitoolkit.python must win over
    both. run.py present but no interpreter -> ACTIONABLE detail."""
    import os
    from app import capabilities, config as cfg
    root = tmp_path / 'aitk'
    (root / '.venv' / ('Scripts' if os.name == 'nt' else 'bin')).mkdir(parents=True)
    py = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    py.touch()
    (root / 'run.py').touch()
    with app.app_context():
        cfg.save_config({'aitoolkit': {'dir': str(root)}})
        assert capabilities.probe_aitoolkit()['ok'] is True
        # explicit interpreter wins (even over an existing .venv)
        other = tmp_path / 'conda-python.exe'
        other.touch()
        cfg.save_config({'aitoolkit': {'dir': str(root), 'python': str(other)}})
        assert cfg.aitoolkit_path('venv_python') == other
        assert capabilities.probe_aitoolkit()['ok'] is True
        # run.py present, no interpreter anywhere -> actionable message
        bare = tmp_path / 'bare'
        bare.mkdir()
        (bare / 'run.py').touch()
        cfg.save_config({'aitoolkit': {'dir': str(bare), 'python': ''}})
        probe = capabilities.probe_aitoolkit()
        assert probe['ok'] is False
        assert 'Python interpreter' in probe['detail']


# --- ollama install detection (execution-independent) ---------------------

def test_ollama_binary_found_on_path(app, monkeypatch):
    """shutil.which hit is the primary signal — works whether or not the server runs."""
    from app import capabilities
    monkeypatch.setattr(capabilities.shutil, 'which', lambda name: r'C:\bin\ollama.exe')
    assert capabilities._ollama_binary() == r'C:\bin\ollama.exe'


def test_ollama_binary_windows_localappdata_fallback(app, tmp_path, monkeypatch):
    """Not on PATH (stale shell) but present at the official per-user install
    location %LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe -> still detected."""
    from app import capabilities
    monkeypatch.setattr(capabilities.shutil, 'which', lambda name: None)
    monkeypatch.setattr(capabilities.os, 'name', 'nt')
    exe = tmp_path / 'Programs' / 'Ollama' / 'ollama.exe'
    exe.parent.mkdir(parents=True)
    exe.touch()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert capabilities._ollama_binary() == str(exe)


def test_ollama_binary_absent_returns_empty(app, monkeypatch):
    from app import capabilities
    monkeypatch.setattr(capabilities.shutil, 'which', lambda name: None)
    monkeypatch.setattr(capabilities.os, 'name', 'nt')
    monkeypatch.setenv('LOCALAPPDATA', r'C:\nope-nonexistent-xyz')
    assert capabilities._ollama_binary() == ''
    assert capabilities.probe_ollama_installed()['ok'] is False


def test_probe_exposes_ollama_installed_independent_of_reachable(app, monkeypatch):
    """installed can be True while reachable is False — the whole point: an
    installed-but-stopped Ollama must NOT read as absent."""
    with app.app_context():
        from app import capabilities, config
        config.save_config({'ollama': {'url': 'http://o', 'vision_model': 'qwen3-vl:8b'}})
        monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: False)   # server down
        monkeypatch.setattr(capabilities, '_ollama_binary', lambda: r'C:\bin\ollama.exe')
        caps = capabilities.probe(force=True)
    o = caps['ollama']
    assert o['installed'] is True
    assert o['reachable'] is False
    assert o['binary_path'] == r'C:\bin\ollama.exe'


def test_probe_ollama_installed_false_when_binary_missing(app, monkeypatch):
    with app.app_context():
        from app import capabilities
        monkeypatch.setattr(capabilities, '_http_ok', lambda *a, **k: False)
        monkeypatch.setattr(capabilities, '_ollama_binary', lambda: '')
        caps = capabilities.probe(force=True)
    assert caps['ollama']['installed'] is False
    assert caps['ollama']['binary_path'] == ''


def test_is_comfyui_dir_accepts_desktop_layout(tmp_path):
    """The ComfyUI Desktop app's basedir has models/ + custom_nodes/ but NO
    main.py (a user had to symlink one to pass the old check)."""
    from app.capabilities import _is_comfyui_dir
    desktop = tmp_path / 'desktop'
    (desktop / 'models').mkdir(parents=True)
    (desktop / 'custom_nodes').mkdir()
    assert _is_comfyui_dir(desktop) is True
    classic = tmp_path / 'classic'
    (classic / 'models').mkdir(parents=True)
    (classic / 'main.py').touch()
    assert _is_comfyui_dir(classic) is True
    not_comfy = tmp_path / 'other'
    (not_comfy / 'custom_nodes').mkdir(parents=True)   # no models/
    assert _is_comfyui_dir(not_comfy) is False
def test_capabilities_expose_authoritative_pricing_and_resolution_matrix(client):
    data = client.get('/api/capabilities?force=1').get_json()
    pricing = data['generation_pricing']
    assert pricing['version'] == 1
    assert pricing['as_of']
    assert pricing['per_image'] == {'nanobanana': 0.15, 'chatgpt_api': 0.17}

    metadata = data['resolution_metadata']
    assert metadata['version'] == 1
    assert [tier['value'] for tier in metadata['tiers']] == [
        'fast', 'standard', 'hq', 'max',
    ]
    for profile in ('default', 'sdxl'):
        for by_tier in metadata['dimensions'][profile].values():
            assert set(by_tier) == {'fast', 'standard', 'hq', 'max'}
            assert all(width % 16 == height % 16 == 0
                       for width, height in by_tier.values())
