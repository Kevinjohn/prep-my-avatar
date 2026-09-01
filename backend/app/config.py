"""Config core: layered config.json over DEFAULTS, secrets in .env."""
import copy
import json
import logging
import os
import secrets as _secrets
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values, load_dotenv, set_key, unset_key

LOCAL_USER = 'local'

BACKEND_DIR = Path(__file__).resolve().parent.parent          # backend/
REPO_ROOT = BACKEND_DIR.parent

def _data_dir() -> Path:
    return Path(os.environ.get('LDS_DATA_DIR', str(REPO_ROOT / 'data')))

def _config_path() -> Path:
    return Path(os.environ.get('LDS_CONFIG', str(REPO_ROOT / 'config.json')))

# ``importlib.reload`` is used by the config tests and by a few integration
# tools. Remove only values that a previous import injected from its dotenv;
# real process variables are never touched.
for _name, _value in globals().get('_DOTENV_INJECTED', {}).items():
    if os.environ.get(_name) == _value:
        os.environ.pop(_name, None)

ENV_PATH = Path(os.environ.get('LDS_ENV', str(REPO_ROOT / '.env')))
_PROCESS_ENV = dict(os.environ)
_DOTENV_VALUES = {
    key: value for key, value in dotenv_values(ENV_PATH, interpolate=False).items()
    if value is not None
}
load_dotenv(ENV_PATH, override=False, interpolate=False)
_DOTENV_INJECTED = {
    key: value for key, value in _DOTENV_VALUES.items()
    if key not in _PROCESS_ENV and os.environ.get(key) == value
}

# REDDIT_CLIENT_ID / CIVITAI_API_KEY: scraping credentials (Settings > Scraping &
# sources). Both scrape sources read their env var first, and set_secrets() stamps
# os.environ on save — so a key saved in the UI takes effect without a restart.
SECRET_KEYS = ('GEMINI_API_KEY', 'OPENAI_API_KEY', 'REPLICATE_API_TOKEN',
               'HF_TOKEN', 'VAST_API_KEY',
               'REDDIT_CLIENT_ID', 'CIVITAI_API_KEY')

DEFAULT_UPDATE_REPO = 'Kevinjohn/prep-my-avatar'
_LEGACY_UPDATE_REPO = 'perfectgf/lora-dataset-studio'

DEFAULTS = {
    # host: '127.0.0.1' = this machine only ; '0.0.0.0' = reachable from the LAN
    # (phone, tablet, another PC) — the Settings "Server" card's LAN toggle just
    # flips this. Port defaults to 5050 to match start.bat's default bind (so the
    # Settings port field shows what's actually running, not a phantom mismatch).
    # Non-loopback access is authenticated by default. The token is entered on a
    # dedicated login page (never placed in a URL) and becomes a signed session.
    # Loopback never needs it; an explicit Settings opt-out remains available.
    'server': {'host': '127.0.0.1', 'port': 5050, 'require_token': True, 'access_token': ''},
    'paths': {'dataset_images_root': ''},                      # '' -> DATA_DIR/datasets
    'comfyui': {'api_url': 'http://127.0.0.1:8188', 'base_dir': '',
                'output_dir': '', 'input_dir': '', 'models_dir': '', 'loras_dir': ''},
    'ollama': {'url': 'http://127.0.0.1:11434', 'vision_model': 'huihui_ai/qwen3-vl-abliterated:8b-instruct'},  # -instruct, NOT ':8b' (=thinking): see get_vision_model()
    'local_vision': {'backend': 'ollama'},  # ollama|lmstudio|llamacpp
    'lmstudio': {'url': 'http://127.0.0.1:1234/v1', 'vision_model': ''},
    'llamacpp': {'url': 'http://127.0.0.1:8080/v1', 'vision_model': ''},
    'aitoolkit': {'dir': '', 'datasets_dir': '', 'output_dir': '', 'hf_home': '',
                  # Explicit interpreter for installs without venv/.venv
                  # (conda, uv, system python). Empty = auto-detect.
                  'python': ''},
    'engines': {'default': 'klein', 'enabled': ['klein'],
                # chatgpt_auth: 'auto' = subscription when connected, else API key.
                'chatgpt_auth': 'auto',            # auto|api|subscription
                'chatgpt_subscription_model': 'gpt-5.4-mini',
                'openai_image_model': 'gpt-image-2',
                'openai_image_quality': 'high',
                'google_image_model': 'gemini-3-pro-image',
                'nanobanana_provider': 'google',       # google|replicate
                'replicate_image_model': 'google/nano-banana-pro'},
    # Reference pixels and prompts stay on-device until the user explicitly
    # enables third-party generation in Settings.
    'privacy': {'allow_remote_generation': False},
    'captioning': {'backend': 'auto'},                         # auto|joycaption|ollama|none
    'external_vision': {
        'openai_model': 'gpt-5.4-mini',
        'gemini_model': 'gemini-2.5-flash',
    },
    'training': {'default_family': 'zimage'},
    # Cloud GPU training (vast.ai). Everything has a sane default: the only
    # required user input is the VAST_API_KEY secret. Values here are knobs
    # for power users / for adjusting after the real-world smoke test.
    'cloud': {
        # Official vast.ai "Ostris AI Toolkit" template (smoke-validated
        # 2026-07-12): publishes the UI behind the pod's Caddy proxy on 18675
        # and generates the per-instance auth token. Clearing this falls back
        # to a raw-image launch using `image`/`onstart` below.
        'template_hash': '471ed5903d8cdb8e63b0d0e50f6cd519',
        'ui_port': 18675,              # container port the UI is reachable on (Caddy proxy)
        'image': 'vastai/ostris-ai-toolkit:4625406-2026-07-12-cuda-12.9',  # raw-image fallback only
        'max_price_per_hour': 0.80,    # background safety cap on offer price, $/h
        'offer_scan_limit': 100,       # offers fetched when listing GPU speed tiers
        'pod_overhead_minutes': 35,    # boot+model download+quantize (measured ~40 min live), in cost estimates
        'max_concurrent_runs': 1,      # simultaneous cloud pods; raise in Settings
        'min_inet_down_mbps': 400,     # skip hosts too slow to pull the 7 GB image
        'min_disk_bw_mbps': 500,       # skip hosts too slow to EXTRACT it (frozen 'loading')
        'min_reliability': 0.98,       # vast reliability floor (0.95 let a dead host through)
        'host_blacklist_days': 3,      # skip hosts whose pod never became ready
        'ready_timeout_minutes': 25,   # boot budget: image pull + services up
        'max_runtime_minutes': 480,    # safety net (stall watchdog is the first line): hard stop past this
        'stall_timeout_minutes': 30,   # no step progress past this -> rescue + kill
        'monthly_budget_usd': 0,       # 0 = unlimited; launches blocked past this
        'disk_gb': 60,                 # instance disk (base model + dataset + checkpoints)
        # min_vram_gb est PAR FAMILLE (pas par variante) : pour flux2klein on prend
        # 32 — le 9B (32-48 GB) est la voie cloud principale de cette famille, et un
        # pod 32 GB entraîne aussi le 4B sans problème (l'inverse serait faux).
        'min_vram_gb': {'zimage': 24, 'sdxl': 16, 'krea': 24, 'flux2klein': 32},
        'onstart': '',                 # raw-image fallback: optional startup command
    },
    'face_scoring': {'python': '', 'models_root': '', 'green': 0.50, 'orange': 0.45},
    'masks': {'python': ''},
    # Watermark inpainting (local Big-LaMa adapter, extra ML). Dedicated key so a
    # user can override it, but defaults empty -> reuse the same ML interpreter as
    # rembg/insightface (masks.python) then sys.executable. Never imported in-process.
    'watermark': {'python': '', 'device': 'auto'},  # auto|cuda|cpu
    # consistency_strength: the dx8152 LoRA anchors STRUCTURE (composition/
    # background), not the face — its own guide says start at 0.5 and that
    # 0.8-1.0 "can prevent edits from applying". 0.9 made every variation a
    # near-copy of the reference. 0 disables the LoRA entirely.
    'klein': {'consistency_lora': 'klein/Flux2-Klein-9B-consistency-V2.safetensors',
              'consistency_strength': 0.5,
              # Optional instruction for small scraped-image rescue only.
              # Manual "Upscale & improve" uses its own fixed quality profile.
              # Empty is intentional: never invent a restoration prompt for the user.
              'small_image_prompt': ''},
    'updates': {'repo': DEFAULT_UPDATE_REPO},      # GitHub repo for the release feed
}

_lock = threading.Lock()
_cache = None


class ConfigError(ValueError):
    """The persisted configuration cannot be safely loaded or updated."""


_ALLOWED_ENGINES = {'klein', 'nanobanana', 'chatgpt'}


def _parse_text(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f'{name} must be a string')
    result = value.strip()
    if not result or any(character in result for character in '\r\n\x00'):
        raise ConfigError(f'{name} must be a non-empty single-line value')
    return result


def _parse_choice(*choices):
    allowed = set(choices)

    def parse(name: str, value: str) -> str:
        result = _parse_text(name, value)
        if result not in allowed:
            raise ConfigError(f'{name} must be one of {sorted(allowed)}')
        return result

    return parse


def _parse_engines(name: str, value: str) -> list[str]:
    engines = [item.strip() for item in value.split(',') if item.strip()]
    if not engines or any(item not in _ALLOWED_ENGINES for item in engines) \
            or len(engines) != len(set(engines)):
        raise ConfigError(
            f'{name} must contain unique valid engines from {sorted(_ALLOWED_ENGINES)}')
    return engines


def _parse_engine(name: str, value: str) -> str:
    engine = _parse_text(name, value)
    if engine not in _ALLOWED_ENGINES:
        raise ConfigError(
            f'{name} must be a valid engine from {sorted(_ALLOWED_ENGINES)}')
    return engine


def _parse_http_url(name: str, value: str) -> str:
    result = _parse_text(name, value).rstrip('/')
    parsed = urlparse(result)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc \
            or parsed.username or parsed.password:
        raise ConfigError(f'{name} must be an http(s) URL without credentials')
    return result


def _parse_optional_http_url(name: str, value: str) -> str:
    if value == '':
        return ''
    return _parse_http_url(name, value)


# Canonical names are intentionally LDS-prefixed. The three historical model
# variables remain read-only aliases for compatibility; canonical names win.
_ENV_SETTINGS = {
    'engines.default': ('LDS_DEFAULT_GENERATION_ENGINE', (), _parse_engine),
    'engines.enabled': ('LDS_ENABLED_GENERATION_ENGINES', (), _parse_engines),
    'engines.chatgpt_auth': ('LDS_CHATGPT_AUTH', (),
                             _parse_choice('auto', 'api', 'subscription')),
    'engines.chatgpt_subscription_model': ('LDS_CHATGPT_SUBSCRIPTION_MODEL', (),
                                             _parse_text),
    'engines.openai_image_model': ('LDS_OPENAI_IMAGE_MODEL',
                                    ('CHATGPT_IMAGE_MODEL',), _parse_text),
    'engines.openai_image_quality': ('LDS_OPENAI_IMAGE_QUALITY',
                                      ('CHATGPT_IMAGE_QUALITY',),
                                      _parse_choice('low', 'medium', 'high')),
    'engines.google_image_model': ('LDS_GOOGLE_IMAGE_MODEL',
                                    ('NANOBANANA_MODEL',), _parse_text),
    'engines.nanobanana_provider': ('LDS_NANOBANANA_PROVIDER', (),
                                     _parse_choice('google', 'replicate')),
    'engines.replicate_image_model': ('LDS_REPLICATE_IMAGE_MODEL', (), _parse_text),
    'local_vision.backend': ('LDS_LOCAL_VISION_BACKEND', (),
                             _parse_choice('ollama', 'lmstudio', 'llamacpp')),
    'ollama.url': ('LDS_OLLAMA_URL', (), _parse_http_url),
    'ollama.vision_model': ('LDS_OLLAMA_VISION_MODEL',
                            ('VISION_OLLAMA_MODEL',), _parse_text),
    'lmstudio.url': ('LDS_LMSTUDIO_URL', (), _parse_http_url),
    'lmstudio.vision_model': ('LDS_LMSTUDIO_VISION_MODEL', (), _parse_text),
    'llamacpp.url': ('LDS_LLAMACPP_URL', (), _parse_http_url),
    'llamacpp.vision_model': ('LDS_LLAMACPP_VISION_MODEL', (), _parse_text),
    'comfyui.api_url': ('LDS_COMFYUI_API_URL', (), _parse_http_url),
    'comfyui.base_dir': ('LDS_COMFYUI_BASE_DIR', (), _parse_text),
}

# Configurable defaults are parsed from the immutable snapshots above. Do not
# leave dotenv copies in ``os.environ``: that would make provenance ambiguous
# and would let a module reload mistake a file value for an operator override.
for _canonical, _aliases, _parser in _ENV_SETTINGS.values():
    for _name in (_canonical, *_aliases):
        if _name not in _PROCESS_ENV and os.environ.get(_name) == _DOTENV_VALUES.get(_name):
            os.environ.pop(_name, None)
            _DOTENV_INJECTED.pop(_name, None)


def _set_dotted(target: dict, dotted: str, value) -> None:
    node = target
    parts = dotted.split('.')
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = copy.deepcopy(value)


def _has_dotted(target: dict, dotted: str) -> bool:
    node = target
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _environment_layer() -> tuple[dict, dict]:
    layer = {}
    sources = {}
    for dotted, (canonical, aliases, parser) in _ENV_SETTINGS.items():
        selected = None
        raw = None
        source = None
        for candidate in (canonical, *aliases):
            if _PROCESS_ENV.get(candidate) not in (None, ''):
                selected, raw, source = candidate, _PROCESS_ENV[candidate], 'environment'
                break
            if _DOTENV_VALUES.get(candidate) not in (None, ''):
                selected, raw, source = candidate, _DOTENV_VALUES[candidate], 'dotenv'
                break
        if raw is None:
            continue
        value = parser(selected, raw)
        _set_dotted(layer, dotted, value)
        sources[dotted] = source
        if selected != canonical:
            logging.getLogger(__name__).warning(
                '%s is deprecated; use %s instead', selected, canonical)
    return layer, sources


def _read_user_config(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ConfigError(f'Invalid configuration at {path}; repair or remove the file before continuing') from exc
    if not isinstance(value, dict):
        raise ConfigError(f'Configuration at {path} must contain a JSON object')
    for key, default in DEFAULTS.items():
        if key in value and isinstance(default, dict) and not isinstance(value[key], dict):
            raise ConfigError(f'Configuration section {key!r} must contain a JSON object')
    return value


def _restrict_private_file(path: Path) -> None:
    """Best-effort owner-only permissions for files containing local secrets.

    Windows applies its own ACL model, while POSIX systems otherwise inherit a
    potentially permissive umask. Permission hardening must never make saving a
    valid configuration fail on an unsupported filesystem.
    """
    if os.name == 'nt':
        return
    try:
        path.chmod(0o600)
    except OSError as exc:
        # Fail-open stays intentional for filesystems without POSIX perms, but
        # the condition must be visible (secmed DBR-0002) instead of silent.
        import logging
        logging.getLogger(__name__).warning(
            'could not restrict permissions on %s: %s', path, exc)


def _write_private_text(path: Path, value: str) -> None:
    """Atomically replace sensitive text without a permissive creation window."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        _restrict_private_file(temporary_path)
        temporary_path.replace(path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Windows and some filesystems do not expose syncable directories.
            pass
        _restrict_private_file(path)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def _edited_dotenv_text(original: str, updates=None, removals=None) -> str:
    """Use python-dotenv's writer so comments, export lines, and quoting survive."""
    descriptor, temporary = tempfile.mkstemp(prefix='.lds-env-edit-', suffix='.env')
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(original)
        for name in removals or ():
            unset_key(str(temporary_path), name, quote_mode='always')
        for name, value in (updates or {}).items():
            set_key(str(temporary_path), name, value, quote_mode='always')
        return temporary_path.read_text(encoding='utf-8')
    finally:
        temporary_path.unlink(missing_ok=True)


def _refresh_dotenv_state() -> None:
    global _DOTENV_VALUES, _DOTENV_INJECTED
    _DOTENV_VALUES = {
        key: value for key, value in dotenv_values(ENV_PATH, interpolate=False).items()
        if value is not None
    }
    for name in SECRET_KEYS:
        if (_PROCESS_ENV.get(name) or '').strip():
            os.environ[name] = _PROCESS_ENV[name]
        elif (_DOTENV_VALUES.get(name) or '').strip():
            os.environ[name] = _DOTENV_VALUES[name]
        else:
            os.environ.pop(name, None)
    _DOTENV_INJECTED = {
        key: value for key, value in _DOTENV_VALUES.items()
        if key not in _PROCESS_ENV and key not in {
            name for canonical, aliases, _parser in _ENV_SETTINGS.values()
            for name in (canonical, *aliases)
        } and os.environ.get(key) == value
    }

def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _resolve_config(user: dict) -> dict:
    environment, _ = _environment_layer()
    resolved = _deep_merge(_deep_merge(DEFAULTS, environment), user)
    if resolved.get('updates', {}).get('repo') == _LEGACY_UPDATE_REPO:
        resolved['updates']['repo'] = DEFAULT_UPDATE_REPO
    engines = resolved.get('engines', {})
    enabled = engines.get('enabled')
    if enabled == []:
        # Historical empty lists meant "use legacy defaults" in the backend
        # but "disable all" in the browser. Preserve that one migration.
        engines['enabled'] = ['klein']
        engines['default'] = 'klein'
        enabled = engines['enabled']
    if (not isinstance(enabled, list) or not enabled
            or any(not isinstance(item, str) or item not in _ALLOWED_ENGINES
                   for item in enabled)
            or len(enabled) != len(set(enabled))):
        raise ConfigError('engines.enabled must contain unique valid engines')
    if engines.get('default') not in enabled:
        raise ConfigError('engines.default must be included in engines.enabled')
    _parse_choice('auto', 'api', 'subscription')(
        'engines.chatgpt_auth', engines.get('chatgpt_auth'))
    _parse_choice('low', 'medium', 'high')(
        'engines.openai_image_quality', engines.get('openai_image_quality'))
    _parse_choice('google', 'replicate')(
        'engines.nanobanana_provider', engines.get('nanobanana_provider'))
    for key in ('chatgpt_subscription_model', 'openai_image_model',
                'google_image_model', 'replicate_image_model'):
        _parse_text(f'engines.{key}', engines.get(key))
    _parse_choice('ollama', 'lmstudio', 'llamacpp')(
        'local_vision.backend', resolved.get('local_vision', {}).get('backend'))
    _parse_optional_http_url('ollama.url', resolved.get('ollama', {}).get('url'))
    _parse_optional_http_url('lmstudio.url', resolved.get('lmstudio', {}).get('url'))
    _parse_optional_http_url('llamacpp.url', resolved.get('llamacpp', {}).get('url'))
    _parse_optional_http_url(
        'comfyui.api_url', resolved.get('comfyui', {}).get('api_url'))
    for provider in ('openai', 'gemini'):
        _parse_text(
            f'external_vision.{provider}_model',
            resolved.get('external_vision', {}).get(f'{provider}_model'),
        )
    return resolved

def load_config(force=False) -> dict:
    global _cache
    with _lock:
        if _cache is not None and not force:
            return copy.deepcopy(_cache)
        user = {}
        p = _config_path()
        if p.exists():
            user = _read_user_config(p)
        _cache = _resolve_config(user)
        return copy.deepcopy(_cache)


def config_sources() -> dict[str, str]:
    """Return the winning source for every dotenv-configurable setting."""
    user = {}
    path = _config_path()
    if path.exists():
        user = _read_user_config(path)
    _, environment_sources = _environment_layer()
    return {
        dotted: ('settings' if _has_dotted(user, dotted)
                 else environment_sources.get(dotted, 'default'))
        for dotted in _ENV_SETTINGS
    }

def save_config(partial: dict) -> dict:
    global _cache
    with _lock:
        p = _config_path()
        current = {}
        if p.exists():
            current = _read_user_config(p)
        merged = _deep_merge(current, partial or {})
        _resolve_config(merged)
        _write_private_text(p, json.dumps(merged, indent=2, ensure_ascii=False))
        _cache = None
    return load_config()


def delete_config_override(dotted: str):
    """Delete one supported config.json leaf and reveal its lower-priority value."""
    if dotted not in _ENV_SETTINGS:
        raise ValueError(f'unsupported configurable setting: {dotted}')
    global _cache
    with _lock:
        path = _config_path()
        current = _read_user_config(path) if path.exists() else {}
        node = current
        parts = dotted.split('.')
        found = True
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                found = False
                break
            node = child
        if found:
            node.pop(parts[-1], None)
            for index in range(len(parts) - 1, 0, -1):
                parent = current
                for part in parts[:index - 1]:
                    parent = parent[part]
                child_name = parts[index - 1]
                if parent.get(child_name) == {}:
                    parent.pop(child_name)
            _resolve_config(current)
            if current:
                _write_private_text(path, json.dumps(current, indent=2, ensure_ascii=False))
            elif path.exists():
                _write_private_text(path, '{}')
        _cache = None
    return get(dotted)


def save_settings(config_partial: dict, secrets_partial: dict) -> dict:
    """Persist one settings request as a recoverable two-file transaction.

    Both files use atomic replacement individually.  If the environment-file
    replacement fails after config.json was committed, restore the exact prior
    config bytes before returning the error.  Runtime secrets are updated only
    after both durable writes succeed.
    """
    validated_secrets = {}
    for name, value in (secrets_partial or {}).items():
        if name not in SECRET_KEYS:
            raise ValueError(f'unknown secret key: {name}')
        if not isinstance(value, str):
            raise ValueError(f'secret {name} must be a string')
        if '\r' in value or '\n' in value or '\x00' in value:
            raise ValueError(f'secret {name} contains invalid characters')
        if value:
            validated_secrets[name] = value
    global _cache
    with _lock:
        config_path = _config_path()
        previous_config = (
            config_path.read_text(encoding='utf-8') if config_path.exists() else None
        )
        current = _read_user_config(config_path) if config_path.exists() else {}
        merged = _deep_merge(current, config_partial or {})
        _resolve_config(merged)
        config_text = json.dumps(merged, indent=2, ensure_ascii=False)

        previous_env = ENV_PATH.read_text(encoding='utf-8') if ENV_PATH.exists() else None
        accepted_secrets = validated_secrets
        env_text = _edited_dotenv_text(previous_env or '', accepted_secrets)

        wrote_config = False
        try:
            if config_partial:
                _write_private_text(config_path, config_text)
                wrote_config = True
            if secrets_partial:
                _write_private_text(ENV_PATH, env_text)
        except Exception:
            if wrote_config:
                if previous_config is None:
                    config_path.unlink(missing_ok=True)
                else:
                    _write_private_text(config_path, previous_config)
            _cache = None
            raise

        _cache = None
        if secrets_partial:
            _refresh_dotenv_state()
    return load_config()

def get(dotted: str, default=None):
    node = load_config()
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node

def is_configured() -> bool:
    p = _config_path()
    if not p.exists():
        return False
    try:
        _read_user_config(p)
    except ConfigError:
        return False
    return True

def secret(name: str):
    runtime_value = (os.environ.get(name) or '').strip()
    if runtime_value:
        return runtime_value
    values = dotenv_values(ENV_PATH, interpolate=False) if ENV_PATH.exists() else {}
    val = (values.get(name) or '').strip()
    return val or None


def secret_source(name: str) -> str:
    runtime_value = (os.environ.get(name) or '').strip()
    values = dotenv_values(ENV_PATH, interpolate=False) if ENV_PATH.exists() else {}
    dotenv_value = (values.get(name) or '').strip()
    if runtime_value and (
            (_PROCESS_ENV.get(name) or '').strip()
            or runtime_value != dotenv_value):
        return 'environment'
    if dotenv_value:
        return 'dotenv'
    return 'absent'

def set_secrets(d: dict) -> None:
    # Settings requests run in parallel. Keep the read/modify/replace cycle
    # inside one critical section so two simultaneous key saves cannot silently
    # discard each other's update.
    with _lock:
        updates = {
            name: value for name, value in (d or {}).items()
            if name in SECRET_KEYS and value
        }
        original = ENV_PATH.read_text(encoding='utf-8') if ENV_PATH.exists() else ''
        _write_private_text(ENV_PATH, _edited_dotenv_text(original, updates))
        _refresh_dotenv_state()

def delete_secrets(names) -> None:
    """Remove saved secrets outright (clear a key). Separate from set_secrets,
    which SKIPS empty values on purpose so a blank field can't wipe a key by
    accident — deletion has to be an explicit action."""
    names = [n for n in (names or []) if n in SECRET_KEYS]
    if not names:
        return
    with _lock:
        original = ENV_PATH.read_text(encoding='utf-8') if ENV_PATH.exists() else ''
        _write_private_text(ENV_PATH, _edited_dotenv_text(original, removals=names))
        _refresh_dotenv_state()

_COMFY_DERIVED = {'output': ('output_dir', 'output'), 'input': ('input_dir', 'input'),
                  'models': ('models_dir', 'models'), 'loras': ('loras_dir', 'models/loras')}

def comfyui_dir(kind: str):
    key, sub = _COMFY_DERIVED[kind]
    explicit = get(f'comfyui.{key}') or ''
    if explicit:
        return Path(explicit)
    base = get('comfyui.base_dir') or ''
    return Path(base) / Path(sub) if base else None

def aitoolkit_path(kind: str):
    root = get('aitoolkit.dir') or ''
    if not root:
        return None
    root = Path(root)
    if kind == 'dir':
        return root
    if kind == 'datasets':
        return Path(get('aitoolkit.datasets_dir') or root / 'datasets')
    if kind == 'output':
        return Path(get('aitoolkit.output_dir') or root / 'output')
    if kind == 'hf_home':
        return Path(get('aitoolkit.hf_home') or root / 'hf-cache' / 'huggingface')
    if kind == 'venv_python':
        # An explicit interpreter wins — installs WITHOUT a venv folder exist
        # in the wild (conda, uv, system python; user-reported from Reddit).
        explicit = (get('aitoolkit.python') or '').strip()
        if explicit:
            return Path(explicit)
        # Both venv directory names and both interpreter layouts exist in
        # exported/restored configurations. Prefer the native layout, but accept
        # the other platform's layout when it is the file actually on disk.
        layouts = (('Scripts', 'python.exe'), ('bin', 'python')) if os.name == 'nt' else (
            ('bin', 'python'), ('Scripts', 'python.exe'))
        for env_dir in ('venv', '.venv'):
            for parts in layouts:
                p = root / env_dir / Path(*parts)
                if p.exists():
                    return p
        # Nothing found: return the historical default path so callers keep a
        # concrete path to name in their "invalid" details.
        win = root / 'venv' / 'Scripts' / 'python.exe'
        return win if os.name == 'nt' else root / 'venv' / 'bin' / 'python'
    if kind == 'jobs':
        return root / 'config' / 'generated'
    raise KeyError(kind)

def dataset_images_root() -> Path:
    p = get('paths.dataset_images_root') or ''
    root = Path(p) if p else _data_dir() / 'datasets'
    root.mkdir(parents=True, exist_ok=True)
    return root

def secret_key() -> str:
    # A concurrent first request must not rotate the Flask signing key between
    # two writers. The process lock prevents multiple servers, while this lock
    # also covers parallel create_app/test initialization inside one process.
    with _lock:
        d = _data_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / 'secret_key'
        value = ''
        existed = f.exists()
        if existed:
            try:
                value = f.read_text(encoding='utf-8').strip()
            except OSError:
                value = ''
        if len(value) != 64 or any(character not in '0123456789abcdef' for character in value):
            if existed:
                # DBR-0005 (review 2): rotating a pre-existing key silently
                # invalidates every signed session — make that visible.
                logging.getLogger(__name__).warning(
                    'secret_key file at %s was unreadable or invalid; '
                    'a new signing key was generated and existing sessions '
                    'were invalidated', f)
            _write_private_text(f, _secrets.token_hex(32))
        _restrict_private_file(f)
        return f.read_text(encoding='utf-8').strip()
