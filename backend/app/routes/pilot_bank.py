"""Local private bank API. Uses the same local dataset owner and CSRF as corpus routes."""
import json
import tempfile
from functools import wraps

from flask import Blueprint, jsonify, request, send_file

from ..config import LOCAL_USER
from ..services import pilot_bank as svc
from ..services import pilot_bank_storage as store

bp = Blueprint('pilot_bank', __name__, url_prefix='/api/dataset/<int:dataset_id>/pilot-bank')


def boundary(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            response = function(*args, **kwargs)
        except svc.BankError as error:
            response = (jsonify({'error': str(error)}), error.status)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            response = (jsonify({'error': 'Private bank operation failed; verify the local records and files.'}), 400)
        if isinstance(response, tuple):
            result = response[0]
        else:
            result = response
        result.headers['Cache-Control'] = 'no-store'
        result.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    return wrapped


@bp.get('')
@boundary
def bank(dataset_id):
    return jsonify(svc.get_bank(LOCAL_USER, dataset_id))


@bp.post('/attempts')
@boundary
def create_attempt(dataset_id):
    return jsonify(svc.create_attempt(LOCAL_USER, dataset_id, request.get_json(silent=True)))


@bp.patch('/attempts/<attempt_id>')
@boundary
def update_attempt(dataset_id, attempt_id):
    return jsonify(svc.update_attempt(LOCAL_USER, dataset_id, attempt_id, request.get_json(silent=True)))


@bp.post('/attempts/<attempt_id>/files')
@boundary
def import_file(dataset_id, attempt_id):
    # The stream is bounded again by storage; declared Content-Length is advisory.
    if request.content_length is not None and request.content_length > store.MAX_FILE_BYTES + 65536:
        raise svc.BankError('File exceeds the local size limit', 413)
    value = request.form.get('metadata', '{}')
    if len(value) > 32768:
        raise svc.BankError('Metadata exceeds record limit')
    try:
        metadata = json.loads(value)
        version = int(request.form.get('version', ''))
    except (ValueError, TypeError):
        raise svc.BankError('Invalid upload metadata or version') from None
    uploaded = request.files.get('file')
    if uploaded is None:
        raise svc.BankError('Choose a local file to import')
    if isinstance(metadata, dict):
        metadata['original_name'] = uploaded.filename
    return jsonify(svc.import_file(LOCAL_USER, dataset_id, attempt_id, version, uploaded.stream, metadata))


@bp.post('/attempts/<attempt_id>/files/<file_id>/review')
@boundary
def review_file(dataset_id, attempt_id, file_id):
    return jsonify(svc.review_file(LOCAL_USER, dataset_id, attempt_id, file_id, request.get_json(silent=True)))


@bp.post('/attempts/<attempt_id>/files/<file_id>/silent')
@boundary
def silent_file(dataset_id, attempt_id, file_id):
    return jsonify(svc.silent_file(LOCAL_USER, dataset_id, attempt_id, file_id, request.get_json(silent=True)))


@bp.get('/attempts/<attempt_id>/files/<file_id>')
@boundary
def file_bytes(dataset_id, attempt_id, file_id):
    source, output = svc.open_file(LOCAL_USER, dataset_id, attempt_id, file_id)
    try:
        suffix = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp',
                  'video/mp4': 'mp4', 'video/webm': 'webm'}.get(output['mime_type'], 'bin')
        response = send_file(source, mimetype=output['mime_type'],
                             as_attachment=output['kind'] in ('weights', 'config'),
                             download_name=output.get('download_name', f"{output['id']}.{suffix}"),
                             conditional=False, etag=False)
        response.content_length = output['size']
        response.make_conditional(request.environ, accept_ranges=True, complete_length=output['size'])
    except BaseException:
        source.close()
        raise
    response.call_on_close(source.close)
    return response


@bp.get('/download')
@boundary
def download(dataset_id):
    stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
    try:
        svc.download(LOCAL_USER, dataset_id, stream)
        stream.seek(0)
        response = send_file(stream, mimetype='application/zip', as_attachment=True,
                             download_name=f'private_person_bank_{dataset_id}.zip', etag=False)
    except BaseException:
        stream.close()
        raise
    response.call_on_close(stream.close)
    return response


@bp.get('/exports/<revision>/files/<path:relative>')
@boundary
def export_image(dataset_id, revision, relative):
    source = svc.open_export_image(LOCAL_USER, dataset_id, revision, relative,
                                   request.args.get('manifest_sha256'))
    try:
        response = send_file(source, mimetype='image/png', conditional=False, etag=False)
    except BaseException:
        source.close()
        raise
    response.call_on_close(source.close)
    return response


@bp.patch('/attempts/<attempt_id>/files/<file_id>/metadata')
@boundary
def update_file_metadata(dataset_id, attempt_id, file_id):
    return jsonify(svc.update_file_metadata(LOCAL_USER, dataset_id, attempt_id, file_id,
                                            request.get_json(silent=True)))
