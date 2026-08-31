"""Setup API: auto-detect installed tools + run the whitelisted one-click installs."""
import ipaddress

from flask import Blueprint, jsonify, request

from .. import capabilities
from .. import setup_installer
from ..directory_picker import DirectoryPickerUnavailable, pick_directory

bp = Blueprint('setup', __name__, url_prefix='/api/setup')


@bp.get('/autodetect')
def setup_autodetect():
    """Discover already-installed tools (Ollama/ComfyUI/ai-toolkit) so the wizard
    can fill config itself. Reachable-port hits are safe to apply; disk paths are
    suggestions the UI confirms."""
    return jsonify(capabilities.autodetect())


@bp.post('/pick-directory/<purpose>')
def setup_pick_directory(purpose):
    """Open a native picker on the same Mac that runs this local server."""
    if purpose != 'aitoolkit':
        return jsonify({'error': f'unknown directory purpose: {purpose}'}), 404
    try:
        is_loopback = ipaddress.ip_address(request.remote_addr or '').is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        return jsonify({'error': 'The folder chooser is available locally only.'}), 403
    try:
        path = pick_directory(purpose)
    except DirectoryPickerUnavailable as exc:
        return jsonify({'error': str(exc)}), 503
    return jsonify({'path': path or '', 'cancelled': path is None})


@bp.post('/install/<action>')
def start_install(action):
    if action not in setup_installer.INSTALL_ACTIONS:
        return jsonify({'error': f'unknown action: {action}'}), 404
    try:
        state = setup_installer.start(action)
    except setup_installer.AlreadyRunning:
        return jsonify({'error': 'install already running'}), 409
    except setup_installer.Precondition as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(state)


@bp.get('/install/<action>/status')
def install_status(action):
    """Poll an install's structured phase progress.

    Clients should poll at a modest fixed cadence (the UI uses ~1s) and stop on
    any terminal state ('done' | 'failed' | 'cancelled'); the payload includes a
    monotonically increasing phase index so consumers can also back off when
    the index is unchanged. Polling is cheap (in-memory read), but there is no
    server-side push channel — unbounded tight loops are pointless, not harmful.
    """
    if action not in setup_installer.INSTALL_ACTIONS:
        return jsonify({'error': f'unknown action: {action}'}), 404
    return jsonify(setup_installer.status(action))


@bp.post('/install/<action>/cancel')
def cancel_install(action):
    if action not in setup_installer.INSTALL_ACTIONS:
        return jsonify({'error': f'unknown action: {action}'}), 404
    try:
        return jsonify(setup_installer.cancel(action))
    except setup_installer.Precondition as exc:
        return jsonify({'error': str(exc)}), 409
