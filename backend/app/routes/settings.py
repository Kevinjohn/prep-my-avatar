"""Settings API: config/secrets CRUD + capability probes."""
import ipaddress
import math

from flask import Blueprint, current_app, jsonify, request

from .. import capabilities
from .. import config as cfg
# The path-redaction helper moved to a shared util so services (run_share) can
# reuse it without a route<-service back-import. Kept under its historical
# private name here for the diagnostic call site below.
from ..utils.redact import redact_user_paths as _redact_user_paths

bp = Blueprint('settings', __name__, url_prefix='/api')


_CLOUD_BOUNDS = {
    'max_concurrent_runs': (1, 10, int),
    'max_price_per_hour': (0.1, 5, float),
    'monthly_budget_usd': (0, None, float),
    'stall_timeout_minutes': (5, 240, int),
}


def _validate_cloud_settings(cloud: dict) -> str | None:
    """Return a field-specific error for paid-cloud operational guardrails."""
    for field, (minimum, maximum, kind) in _CLOUD_BOUNDS.items():
        if field not in cloud:
            continue
        value = cloud[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"cloud.{field} must be a number"
        if not math.isfinite(value):
            return f"cloud.{field} must be finite"
        if kind is int and int(value) != value:
            return f"cloud.{field} must be an integer"
        if value < minimum or (maximum is not None and value > maximum):
            upper = f' and at most {maximum}' if maximum is not None else ''
            return f"cloud.{field} must be at least {minimum}{upper}"
    return None


_ENUM_VALUES = {
    'server.host': {'127.0.0.1', '0.0.0.0'},
    'engines.chatgpt_auth': {'auto', 'api', 'subscription'},
    'engines.openai_image_quality': {'low', 'medium', 'high'},
    'engines.nanobanana_provider': {'google', 'replicate'},
    'local_vision.backend': {'ollama', 'lmstudio', 'llamacpp'},
    'captioning.backend': {'auto', 'joycaption', 'ollama', 'none'},
    'training.default_family': {'zimage', 'sdxl', 'krea', 'flux2klein'},
    'watermark.device': {'auto', 'cuda', 'cpu'},
}


def _validate_config_values(partial: dict, defaults: dict, prefix: str = '') -> str | None:
    """Validate nested keys and JSON value types against the config contract."""
    for key, value in partial.items():
        dotted = f'{prefix}.{key}' if prefix else key
        if key not in defaults:
            return f"unknown config field '{dotted}'"
        expected = defaults[key]
        if isinstance(expected, dict):
            if not isinstance(value, dict):
                return f'{dotted} must be an object'
            error = _validate_config_values(value, expected, dotted)
            if error:
                return error
        elif isinstance(expected, bool):
            if not isinstance(value, bool):
                return f'{dotted} must be a boolean'
        elif isinstance(expected, int):
            if isinstance(value, bool) or not isinstance(value, int):
                return f'{dotted} must be an integer'
        elif isinstance(expected, float):
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                return f'{dotted} must be a finite number'
        elif isinstance(expected, str):
            if not isinstance(value, str):
                return f'{dotted} must be a string'
        elif isinstance(expected, list):
            if not isinstance(value, list):
                return f'{dotted} must be an array'
            if expected and any(not isinstance(item, type(expected[0])) for item in value):
                return f'{dotted} contains an invalid value type'
        allowed = _ENUM_VALUES.get(dotted)
        if allowed is not None and value not in allowed:
            return f'{dotted} must be one of {sorted(allowed)}'
    return None


_TEST_TARGETS = {
    'gemini': capabilities.probe_gemini,
    'replicate': capabilities.probe_replicate,
    'openai': capabilities.probe_openai,
    'comfyui': capabilities.probe_comfyui,
    'ollama': capabilities.probe_ollama,
    'local_vision': capabilities.probe_local_vision,
    'aitoolkit': capabilities.probe_aitoolkit,
    'face_scoring': capabilities.probe_face_scoring,
    'masks': capabilities.probe_masks,
    'vast': capabilities.probe_vast,
}


def _secret_presence() -> dict:
    return {name: bool(cfg.secret(name)) for name in cfg.SECRET_KEYS}


def _probe_outbound_ip(target):
    """IPv4 of whichever interface the OS would use to reach `target`, or None.

    Le truc standard du connect() UDP : ouvrir un datagram socket vers une adresse
    ne fait sortir AUCUN paquet, mais force l'OS à choisir la route — getsockname()
    révèle alors l'IPv4 de cette interface. None sur OSError (pas de route, hors
    ligne).

    Le FILTRE reste chez l'appelant : ce qu'« une bonne réponse » veut dire diffère
    par sonde (hors loopback pour le LAN, dans 100.64/10 pour le tailnet), et c'est
    là qu'est la règle — ici il n'y a que la mécanique du socket."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _lan_ip():
    """This machine's primary LAN IPv4, or None. Probes toward a public address, so
    the OS picks the default-route interface. Returns None when offline or when only
    loopback is available, so callers can fall back to a placeholder."""
    ip = _probe_outbound_ip('8.8.8.8')
    return ip if ip and not ip.startswith('127.') else None


def _is_cgnat(ip) -> bool:
    """True for the 100.64.0.0/10 carrier-grade-NAT block that Tailscale draws
    every node's address from — the reliable signature of a tailnet IP."""
    try:
        address = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return False
    return address.version == 4 and address in ipaddress.ip_network('100.64.0.0/10')


def _query_flag(name: str) -> bool:
    return request.args.get(name, '').strip().lower() not in ('', '0', 'false', 'no')


def _tailscale_ip():
    """This host's Tailscale IPv4, or None when Tailscale isn't up. Same
    UDP-connect probe as _lan_ip but aimed at Tailscale's service IP
    (100.100.100.100): when the tunnel is up Tailscale owns the route for
    100.64.0.0/10, so the OS picks the tailscale interface and getsockname()
    reveals its address. With Tailscale down the probe falls through the default
    route to the LAN IP, which is outside 100.64/10 and gets rejected — so this
    is None exactly when there's no tailnet address to offer. A Tailscale URL is
    the phone's bulletproof path: it sidesteps Wi-Fi client-isolation, a shifting
    DHCP LAN IP, and works even off the home network."""
    ip = _probe_outbound_ip('100.100.100.100')   # selects the tailnet route
    return ip if _is_cgnat(ip) else None


def _settings_payload() -> dict:
    return {
        'config': cfg.load_config(), 'secrets': _secret_presence(),
        'config_sources': cfg.config_sources(),
        'secret_sources': {
            name: cfg.secret_source(name) for name in cfg.SECRET_KEYS
        },
        # What THIS running process is actually bound to — run.py stamps these
        # before app.run(); a dev/test boot that never went through run.py (or a
        # WSGI launch) leaves them unset, so the Server card just hides the
        # "running vs saved" diff instead of showing a misleading n/a:n/a.
        'runtime': {'host': current_app.config.get('LDS_BOUND_HOST'),
                    'port': current_app.config.get('LDS_BOUND_PORT'),
                    # LAN IPv4 so the Server card can show a real, copyable
                    # http://<ip>:port/ URL instead of a <this-computer> placeholder;
                    # None (offline / loopback-only) -> the UI keeps the placeholder.
                    'lan_ip': _lan_ip(),
                    # Tailscale IPv4 (100.64/10), or None when the tunnel is down.
                    # Offered alongside the LAN URL as the phone's bulletproof path
                    # (survives Wi-Fi client-isolation, a shifting DHCP IP, off-LAN).
                    'tailscale_ip': _tailscale_ip()},
    }


@bp.get('/settings')
def get_settings():
    return jsonify(_settings_payload())


@bp.put('/settings')
def put_settings():
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'request body must be an object'}), 400
    if 'config' in body and not isinstance(body['config'], dict):
        return jsonify({'error': "'config' must be an object"}), 400
    if 'secrets' in body and not isinstance(body['secrets'], dict):
        return jsonify({'error': "'secrets' must be an object"}), 400
    secrets_partial = body.get('secrets') or {}
    for name, value in secrets_partial.items():
        if name not in cfg.SECRET_KEYS:
            return jsonify({'error': f"unknown secret key '{name}'"}), 400
        if not isinstance(value, str):
            return jsonify({'error': f'secret {name} must be a string'}), 400
        if '\r' in value or '\n' in value or '\x00' in value:
            return jsonify({'error': f'secret {name} contains invalid characters'}), 400
    config_partial = body.get('config') or {}
    unknown = set(config_partial) - set(cfg.DEFAULTS)
    if unknown:
        return jsonify({'error': f"unknown config section '{sorted(unknown)[0]}'"}), 400
    # Each section must stay an object -- _deep_merge only recurses when both
    # sides are dicts, so a non-dict value here would REPLACE the whole section
    # (e.g. {"ollama": "x"} silently overwriting ollama.url + ollama.vision_model).
    for k, v in config_partial.items():
        if not isinstance(v, dict):
            return jsonify({'error': f"config section '{k}' must be an object"}), 400
    value_error = _validate_config_values(config_partial, cfg.DEFAULTS)
    if value_error:
        return jsonify({'error': value_error}), 400
    server = config_partial.get('server') or {}
    port = server.get('port')
    if port is not None and not 1 <= port <= 65535:
        return jsonify({'error': 'server.port must be between 1 and 65535'}), 400
    cloud_error = _validate_cloud_settings(config_partial.get('cloud') or {})
    if cloud_error:
        return jsonify({'error': cloud_error}), 400
    effective = cfg._deep_merge(cfg.load_config(), config_partial)
    face = effective.get('face_scoring') or {}
    green, orange = face.get('green'), face.get('orange')
    if (not isinstance(green, (int, float)) or isinstance(green, bool)
            or not isinstance(orange, (int, float)) or isinstance(orange, bool)
            or not 0 <= orange < green <= 1):
        return jsonify({
            'error': 'face_scoring thresholds must satisfy 0 <= orange < green <= 1',
        }), 400
    engines = effective.get('engines') or {}
    allowed_engines = {'klein', 'nanobanana', 'chatgpt'}
    enabled = engines.get('enabled')
    default_engine = engines.get('default')
    if (not isinstance(enabled, list) or not enabled
            or any(not isinstance(item, str) or item not in allowed_engines
                   for item in enabled)
            or len(set(enabled)) != len(enabled)):
        return jsonify({'error': 'engines.enabled must contain at least one valid engine'}), 400
    if default_engine not in enabled:
        return jsonify({'error': 'engines.default must be enabled'}), 400
    # Auto-correct the classic portable-bundle mistake: a base_dir pointing at
    # ...\ComfyUI_windows_portable gets rewritten to the nested ...\ComfyUI that
    # actually holds main.py + models/, so the base/model listers find checkpoints
    # instead of silently scanning an empty ...\<wrapper>\models.
    bd = (config_partial.get('comfyui') or {}).get('base_dir')
    if bd:
        r = capabilities.resolve_comfyui_base(bd)
        if r['valid'] and r['nested']:
            config_partial['comfyui']['base_dir'] = r['resolved']
    cfg.save_settings(config_partial, secrets_partial)
    # A changed ComfyUI location must take effect NOW: the base/model listers cache
    # their scans for 5 min, so without this the training-base dropdowns keep showing
    # the pre-save (often empty) list right after the user points the app at ComfyUI.
    # (The wizard's _scan_models view refreshes via the frontend's forced
    # /api/capabilities?force=1 call, so no probe(force) is needed here.)
    if 'comfyui' in config_partial:
        from ..utils import comfyui
        comfyui.clear_model_caches()
    return jsonify(_settings_payload())


@bp.delete('/settings/secret/<name>')
def delete_secret(name):
    """Clear a saved API key. Explicit deletion — set_secrets ignores blanks so a
    key can never be wiped by just emptying its (write-only) field."""
    if name not in cfg.SECRET_KEYS:
        return jsonify({'error': 'unknown secret'}), 400
    cfg.delete_secrets([name])
    return jsonify(_settings_payload())


@bp.delete('/settings/config/<path:dotted>')
def delete_config_override(dotted):
    """Remove one Settings override so dotenv/environment/default can win."""
    try:
        cfg.delete_config_override(dotted)
    except ValueError:
        return jsonify({'error': f"config field '{dotted}' cannot be reset"}), 400
    return jsonify(_settings_payload())


@bp.get('/capabilities')
def get_capabilities():
    force = _query_flag('force')
    return jsonify(capabilities.probe(force=force))


@bp.post('/settings/test/<target>')
def test_connection(target):
    probe_fn = _TEST_TARGETS.get(target)
    if probe_fn is None:
        return jsonify({'error': f"unknown test target '{target}'"}), 404
    return jsonify(probe_fn())


# Update check: compares the latest GitHub release tag to the local version.
# Cached 6 h so the SPA banner can call it freely. Degrades to
# update_available=False with a reason when the feed is unreachable (offline,
# repo private, no release yet) — never an error, never a blocker.
_UPDATE_TTL = 6 * 3600           # GitHub releases feed (packaged builds; rare)
_GIT_CHECK_TTL = 3600            # git commits-behind check — the project moves fast
_update_cache = {'ts': 0.0, 'data': None}
# Auto-detection (nav badge): the git fetch is allowed but CACHED — the SPA
# asks on every load, the network is hit at most once per TTL.
_git_check_cache = {'ts': 0.0, 'data': None}


@bp.get('/update/check')
def update_check():
    import time
    import requests
    from ..version import APP_VERSION, is_newer_version
    from ..services import updater
    force = _query_flag('force')
    auto = _query_flag('auto')
    # A git checkout: the meaningful signal is commits-behind-origin (the user pushes
    # commits to a branch, not tagged releases — a release-only check reads "up to date"
    # while the tree is many commits behind). The fetch runs on an explicit check
    # (force, always fresh) or an auto check (nav badge — served from a TTL cache so
    # SPA loads don't hammer the network); never from the bare passive path.
    if (force or auto) and updater.is_git_checkout():
        now = time.time()
        if auto and not force and _git_check_cache['data'] is not None \
                and (now - _git_check_cache['ts']) < _GIT_CHECK_TTL:
            return jsonify(_git_check_cache['data'])
        gs = updater.git_update_status()
        if gs is not None:
            if gs.get('ok'):
                _git_check_cache.update(ts=now, data=gs)
            return jsonify(gs)
    now = time.time()
    if (_update_cache['data'] is not None and (now - _update_cache['ts']) < _UPDATE_TTL
            and not force):
        return jsonify(_update_cache['data'])
    repo = cfg.get('updates.repo') or cfg.DEFAULT_UPDATE_REPO
    out = {'ok': True, 'current': APP_VERSION, 'latest': None,
           'update_available': False, 'url': f'https://github.com/{repo}/releases'}
    sha = updater.current_sha()
    if sha:
        out['current_sha'] = sha
    try:
        r = requests.get(f'https://api.github.com/repos/{repo}/releases/latest',
                         timeout=6, headers={'Accept': 'application/vnd.github+json'})
        if r.status_code == 200:
            j = r.json()
            latest = (j.get('tag_name') or '').lstrip('vV').strip()
            out['latest'] = latest or None
            out['url'] = j.get('html_url') or out['url']
            out['update_available'] = bool(latest) and is_newer_version(
                latest, APP_VERSION)
        else:
            out['reason'] = (f'release feed answered {r.status_code} '
                             '(no public release yet?)')
    except requests.RequestException:
        out['reason'] = 'offline or GitHub unreachable'
    _update_cache.update(ts=now, data=out)
    return jsonify(out)


@bp.post('/update/apply')
def update_apply():
    """Pull the latest commits (git checkout only) and, if anything changed, restart the
    server. Returns immediately with {ok, changed, from, to, restarting, log, ...}; the
    actual re-launch happens ~1 s after this response flushes, so the client can start
    polling /api/health. A packaged build (no git) gets {manual:true, url} instead."""
    from ..services import updater
    from .. import setup_installer
    active_installs = setup_installer.active_pip_mutations()
    if active_installs:
        return jsonify({
            'error': 'wait for or cancel the active package install before updating',
            'active_installs': active_installs,
        }), 409
    res = updater.apply_update()
    res['restarting'] = bool(res.get('ok') and res.get('changed'))
    if res['restarting']:
        # invalidate the cached checks so the banner/badge re-evaluate post-update
        _update_cache.update(ts=0.0, data=None)
        _git_check_cache.update(ts=0.0, data=None)
        updater.schedule_restart(restart_nonce=res.get('restart_nonce'))
    return jsonify(res)


@bp.post('/settings/restart')
def settings_restart():
    """Manual restart — used after saving server.host/server.port (a live bind
    change needs a fresh process; Flask can't rebind mid-request) and as a plain
    troubleshooting action. Same schedule_restart() as the updater, so it
    survives both a git checkout and the packaged build.

    Pins the restarted process to the SAVED host/port via env: the launcher
    (start.bat) exports LDS_PORT, which otherwise wins over config.json forever
    — so without this, changing the port in Settings + restart would keep coming
    back on the launcher's port and the field would look broken. schedule_restart
    passes os.environ down to the relaunch, so setting it here is what makes the
    saved port actually take effect."""
    import os
    import uuid
    from ..services import updater
    os.environ['LDS_HOST'] = str(cfg.get('server.host') or '127.0.0.1')
    os.environ['LDS_PORT'] = str(cfg.get('server.port') or 5050)
    from .. import setup_installer
    active_installs = setup_installer.active_pip_mutations()
    if active_installs:
        return jsonify({
            'error': 'wait for or cancel the active package install before restarting',
            'active_installs': active_installs,
        }), 409
    restart_nonce = uuid.uuid4().hex
    updater.schedule_restart(restart_nonce=restart_nonce)
    return jsonify({'ok': True, 'restarting': True,
                    'restart_nonce': restart_nonce})


@bp.get('/trash')
def trash_info():
    """Trash size for the Settings card — everything the app 'deletes' lands
    there; only 'Empty trash' below actually destroys bytes."""
    from ..services import trash
    size_bytes, entries = trash.inventory()
    return jsonify({'size_bytes': size_bytes, 'entries': entries})


@bp.post('/trash/<entry_id>/restore')
def trash_restore(entry_id):
    from ..services import face_dataset_service as datasets
    from ..services import trash
    try:
        metadata = trash.entry_metadata(entry_id)
        kind = metadata.get('kind')
        if kind == 'dataset_image':
            image = datasets.restore_trashed_image(cfg.LOCAL_USER, entry_id)
            return jsonify({'ok': True, 'kind': kind, 'image_id': image.id,
                            'dataset_id': image.dataset_id})
        if kind == 'regenerated_image':
            image = datasets.restore_regenerated_image(cfg.LOCAL_USER, entry_id)
            return jsonify({'ok': True, 'kind': kind, 'image_id': image.id,
                            'dataset_id': image.dataset_id})
        if kind == 'dataset_backup':
            dataset = datasets.restore_trashed_dataset(cfg.LOCAL_USER, entry_id)
            return jsonify({'ok': True, 'kind': kind, 'dataset_id': dataset.id})
        if kind == 'dataset_extra_reference':
            dataset = datasets.restore_trashed_extra_reference(cfg.LOCAL_USER, entry_id)
            return jsonify({'ok': True, 'kind': kind, 'dataset_id': dataset.id})
        if kind == 'dataset_primary_reference':
            dataset = datasets.restore_trashed_primary_reference(cfg.LOCAL_USER, entry_id)
            return jsonify({'ok': True, 'kind': kind, 'dataset_id': dataset.id})
        result = trash.restore_entry(entry_id)
        return jsonify({'ok': True, 'kind': kind or 'files',
                        'restored': result['restored']})
    except FileExistsError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    except FileNotFoundError:
        return jsonify({'ok': False, 'error': 'trash entry not found'}), 404
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@bp.post('/trash/empty')
def trash_empty():
    from ..services import face_dataset_service as datasets
    from ..services import trash
    return jsonify({
        'ok': True,
        **trash.empty_trash(
            purge_record=lambda metadata, entry_id: datasets.purge_trashed_record(
                cfg.LOCAL_USER, metadata, entry_id)),
    })


@bp.get('/integrity')
def integrity_check():
    """Read-only DB/filesystem consistency audit for the Maintenance page."""
    from ..services import integrity
    include_orphans = request.args.get('orphans', '1').lower() not in ('0', 'false', 'no')
    return jsonify(integrity.run(include_orphans=include_orphans))


def _log_tail_lines(n):
    """(file_name, last_n_lines) of the server log. Reads data/app.log (the
    app's own rotating log), falling back to data/server.log (the portable
    launcher's raw stdout capture). (None, []) when no log exists yet."""
    import os
    from pathlib import Path
    data_dir = Path(os.environ.get('LDS_DATA_DIR', str(cfg.REPO_ROOT / 'data')))
    for name in ('app.log', 'server.log'):
        p = data_dir / name
        if p.is_file():
            try:
                size = p.stat().st_size
                with open(p, encoding='utf-8', errors='replace') as fh:
                    if size > 512 * 1024:               # tail window, never the whole file
                        fh.seek(size - 512 * 1024)
                    return name, fh.read().splitlines()[-n:]
            except OSError:
                continue
    return None, []


@bp.get('/logs/tail')
def logs_tail():
    """Last N lines of the server log for the in-app viewer — so a novice can
    copy-paste an error instead of hunting for files."""
    try:
        n = max(10, min(1000, int(request.args.get('n', 300))))
    except ValueError:
        n = 300
    name, lines = _log_tail_lines(n)
    return jsonify({'ok': True, 'file': name, 'lines': lines})


@bp.get('/diagnostic')
def diagnostic():
    """Paste-safe bug-report payload: version, platform, capability booleans and
    the log tail. Secret VALUES never appear (presence booleans only) and paths
    are reduced to *_set booleans — the output is meant to be pasted into a
    public issue or Discord thread as-is. (Log lines may still cite file names;
    the UI tells the user to skim before posting.)"""
    import platform
    import sys
    import time
    from ..version import APP_VERSION
    from ..services import updater
    conf = cfg.load_config()
    caps = capabilities.probe()
    e = caps.get('engines') or {}
    comfy = caps.get('comfyui') or {}
    oll = caps.get('ollama') or {}
    local_vision = caps.get('local_vision') or {
        'provider': 'ollama',
        'reachable': oll.get('reachable'),
        'model_ready': oll.get('vision_model_ready'),
    }
    # Redact ONLY in this paste-safe payload — /api/logs/tail (the in-app log
    # viewer) keeps the raw lines, they're local-only and never meant to be
    # copy-pasted into a public thread.
    _, log_lines = _log_tail_lines(80)
    log_lines = [_redact_user_paths(line) for line in log_lines]
    # DBR-0009 (review 2): record detected external media tool versions so
    # "works on my machine" download failures are diagnosable from the report.
    try:
        import yt_dlp as _ytdlp
        ytdlp_version = str(getattr(_ytdlp.version, '__version__', '')) or None
    except Exception:
        ytdlp_version = None
    import shutil as _shutil
    ffmpeg_path = _shutil.which('ffmpeg')
    if ffmpeg_path:
        try:
            import subprocess as _subprocess
            ffmpeg_version = _subprocess.run(
                ['ffmpeg', '-version'], capture_output=True, text=True,
                timeout=5).stdout.split()[2]
        except Exception:
            ffmpeg_version = None
    else:
        ffmpeg_version = None
    return jsonify({
        'app_version': APP_VERSION,
        'git_sha': updater.current_sha(),
        'external_tools': {'yt_dlp': ytdlp_version, 'ffmpeg': ffmpeg_version},
        'os': f'{platform.system()} {platform.release()}',
        'python': sys.version.split()[0],
        'secrets_present': _secret_presence(),
        'capabilities': {
            'engines': {'nanobanana': bool(e.get('nanobanana')),
                        'chatgpt': bool(e.get('chatgpt')),
                        'klein': bool(e.get('klein'))},
            'comfyui_reachable': bool(comfy.get('reachable')),
            'klein_model': bool((comfy.get('models') or {}).get('klein')),
            'ollama_reachable': bool(oll.get('reachable')),
            'vision_model_ready': bool(oll.get('vision_model_ready')),
            'local_vision_backend': local_vision.get('provider', 'ollama'),
            'local_vision_reachable': bool(local_vision.get('reachable')),
            'local_vision_model_ready': bool(local_vision.get('model_ready')),
            'face_scoring': bool(caps.get('face_scoring')),
            'masks': bool(caps.get('masks')),
            'aitoolkit_valid': bool((caps.get('aitoolkit') or {}).get('valid')),
            'training_visible': bool(caps.get('training_visible')),
            'studio_visible': bool(caps.get('studio_visible')),
            'cloud_training': bool(caps.get('cloud_training')),
        },
        'config': {
            'captioning_backend': (conf.get('captioning') or {}).get('backend'),
            'default_engine': (conf.get('engines') or {}).get('default'),
            'enabled_engines': (conf.get('engines') or {}).get('enabled'),
            'training_default_family': (conf.get('training') or {}).get('default_family'),
            'comfyui_base_dir_set': bool((conf.get('comfyui') or {}).get('base_dir')),
            'aitoolkit_dir_set': bool((conf.get('aitoolkit') or {}).get('dir')),
            'lan_enabled': (conf.get('server') or {}).get('host') not in (None, '', '127.0.0.1', 'localhost', '::1'),
        },
        'log_tail': log_lines,
        'generated_at': int(time.time()),
    })


# --- ChatGPT subscription (Codex OAuth) --------------------------------------
# Device-code login for the ChatGPT engine's subscription lane. One upstream
# check per poll call — the SPA polls every few seconds, no server thread.

@bp.post('/settings/chatgpt-oauth/start')
def chatgpt_oauth_start():
    from ..services import chatgpt_oauth
    out = chatgpt_oauth.login_start()
    return jsonify(out), (200 if out.get('ok') else 502)


@bp.get('/settings/chatgpt-oauth/poll')
def chatgpt_oauth_poll():
    from ..services import chatgpt_oauth
    return jsonify(chatgpt_oauth.login_poll())


@bp.post('/settings/chatgpt-oauth/import-codex')
def chatgpt_oauth_import_codex():
    from ..services import chatgpt_oauth
    out = chatgpt_oauth.import_codex_cli()
    return jsonify(out), (200 if out.get('ok') else 404)


@bp.post('/settings/chatgpt-oauth/logout')
def chatgpt_oauth_logout():
    from ..services import chatgpt_oauth
    chatgpt_oauth.logout()
    return jsonify({'ok': True})
