import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from flask.testing import FlaskClient


class TrackingFlaskClient(FlaskClient):
    """Keep responses alive and close every streamed body at fixture teardown."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tracked_responses = []

    def open(self, *args, **kwargs):
        response = super().open(*args, **kwargs)
        self._tracked_responses.append(response)
        return response

    def close_responses(self):
        for response in reversed(self._tracked_responses):
            response.close()
        self._tracked_responses.clear()

@pytest.fixture(autouse=True)
def _restore_secret_env():
    """set_secrets() writes os.environ directly; snapshot & restore the secret keys.

    Also CLEAR them at setup: config.py runs load_dotenv(ENV_PATH) at import, and at
    collection time (before LDS_ENV is pointed at a tmp file) ENV_PATH is the real
    repo .env — so a developer who saved a real Gemini/OpenAI key via the app would
    leak it into os.environ and make "unconfigured" probes see a key. Starting each
    test with the keys unset makes the suite independent of the local .env; tests
    that need a key set it themselves via monkeypatch.setenv."""
    import os
    from app.config import SECRET_KEYS as keys   # stays in sync as keys are added
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('LDS_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('LDS_CONFIG', str(tmp_path / 'config.json'))
    monkeypatch.setenv('LDS_ENV', str(tmp_path / '.env'))
    import app.config as _cfg
    monkeypatch.setattr(_cfg, 'ENV_PATH', tmp_path / '.env')   # never touch the real .env in tests
    # config.py caches load_config() in a module-level global keyed on nothing but
    # "has it been loaded before" -- it isn't tied to LDS_CONFIG. Without resetting it
    # here, a test that calls save_config() with a real comfyui.base_dir leaks that
    # value into every later test's "fresh" app (same process, stale cache), even
    # though each test gets its own tmp_path/env vars. Task 14 (Klein path) hit this:
    # a test asserting "ComfyUI unconfigured -> RuntimeError" silently inherited a
    # previous test's real base_dir and passed for the wrong reason.
    monkeypatch.setattr(_cfg, '_cache', None)
    from app import create_app
    application = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False,
                              'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    application.test_client_class = TrackingFlaskClient
    yield application

@pytest.fixture()
def client(app):
    test_client = app.test_client()
    yield test_client
    test_client.close_responses()
