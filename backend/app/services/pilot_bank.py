"""Durable manual person pilots. No provider calls, asset loading, or corpus edits."""
from __future__ import annotations

import copy
import os
import shutil
from contextlib import contextmanager
import json
import math
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, quote

from . import pilot_bank_media as media
from . import pilot_bank_recipes as recipes
from . import pilot_bank_storage as store
from . import trash
from .pilot_bank_storage import BankError

STATUSES = ('not_started', 'submitted', 'succeeded', 'failed', 'unknown')
KINDS = ('image', 'video', 'weights', 'config')
PROCESSES = ('still', 'video', 'adaptation')
ASSET_KINDS = ('lora', 'checkpoint', 'refmod', 'embedding', 'other')


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, name, limit=4000, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise BankError(f'Invalid {name}')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise BankError(f'Invalid {name}')
    return value.strip()


def bounded_json(value, name, limit=16384):
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise BankError(f'Invalid {name}') from None
    if len(encoded) > limit:
        raise BankError(f'{name} exceeds record limit')
    return copy.deepcopy(value)


def object_payload(value):
    if not isinstance(value, dict):
        raise BankError('Expected a JSON object')
    bounded_json(value, 'request', 65536)
    return value


def number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise BankError(f'Invalid {name}')
    return value


def get_exports(user_id, dataset_id):
    dataset = store.dataset_root(user_id, dataset_id)
    parent = store.contained(dataset, 'hosted_exports')
    if not parent.exists():
        return []
    exports = []
    for child in sorted(parent.iterdir()):
        if not store.REVISION.fullmatch(child.name):
            continue
        # Validate parents from the dataset root, including hosted_exports.
        store.contained(dataset, f'hosted_exports/{child.name}/manifest.json', file=True)
        raw = store.read_bytes(child, 'manifest.json', store.MAX_RECORD_BYTES)
        try:
            manifest = json.loads(raw)
        except (ValueError, UnicodeError):
            raise BankError('Invalid export manifest') from None
        if (not isinstance(manifest, dict) or manifest.get('dataset_id') != dataset_id
                or manifest.get('export_revision') != child.name
                or manifest.get('format') != 'person-hosted-export'
                or not isinstance(manifest.get('entries'), list)
                or not isinstance(manifest.get('files'), dict)):
            raise BankError('Invalid export manifest')
        entries = copy.deepcopy(manifest['entries'])
        for entry in entries:
            if entry.get('role') in ('reference', 'evaluation') and isinstance(entry.get('image_path'), str):
                entry['preview_url'] = (f'/api/dataset/{dataset_id}/pilot-bank/exports/{child.name}/files/'
                                        f"{quote(entry['image_path'], safe='/')}?manifest_sha256={store.digest(raw)}")
        exports.append({'revision': child.name, 'manifest_sha256': store.digest(raw),
                        'subject': manifest.get('subject'), 'recipe': manifest.get('recipe'),
                        'entries': entries})
    return exports


def export_content(user_id, dataset_id, revision, manifest_sha256, *, verify_files=True):
    if not isinstance(revision, str) or not store.REVISION.fullmatch(revision):
        raise BankError('Invalid export revision')
    dataset = store.dataset_root(user_id, dataset_id)
    root = store.contained(dataset, f'hosted_exports/{revision}')
    raw = store.read_bytes(root, 'manifest.json', store.MAX_RECORD_BYTES)
    if store.digest(raw) != manifest_sha256:
        raise BankError('Pinned export manifest changed', 409)
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError):
        raise BankError('Invalid export manifest') from None
    if manifest.get('dataset_id') != dataset_id or manifest.get('export_revision') != revision:
        raise BankError('Export belongs to another dataset')
    if not isinstance(manifest.get('files'), dict) or not isinstance(manifest.get('entries'), list):
        raise BankError('Invalid export manifest')
    # Verify every declared export file before capture or backup, including ZIP.
    if verify_files:
        for relative, expected in manifest['files'].items():
            if store.hash_file(root, relative) != expected:
                raise BankError('Pinned export file changed', 409)
    return root, manifest, raw


def get_bank(user_id, dataset_id):
    root = store.root_for(user_id, dataset_id)
    state = store.state(root)
    return {**state, 'exports': get_exports(user_id, dataset_id),
            'tools': media.tools(), 'recipes': recipes.list_recipes(),
            'limits': {'max_file_bytes': store.MAX_FILE_BYTES, 'file_bytes_by_kind': store.FILE_LIMITS},
            'backup_notice': 'Ordinary dataset backups exclude the bank. Download the complete private bank separately.'}


def load_mutation(user_id, dataset_id, payload):
    object_payload(payload)
    root = store.root_for(user_id, dataset_id)
    state = store.state(root)
    store.version_check(state, payload.get('version'))
    return root, state


def finish(user_id, dataset_id, root, state, version):
    store.publish(root, state, version)
    return get_bank(user_id, dataset_id)


def find_attempt(state, attempt_id):
    for item in state['attempts']:
        if item['id'] == attempt_id:
            return item
    raise BankError('Attempt not found', 404)


def find_output(state, attempt_id, file_id):
    attempt = find_attempt(state, attempt_id)
    for output in attempt['outputs']:
        if output['id'] == file_id:
            return output
    raise BankError('Bank file not found', 404)


def validate_recipe(value):
    object_payload(value)
    recipe = {}
    for name in ('id', 'provider', 'endpoint', 'model_id', 'base_family'):
        recipe[name] = text(value.get(name), f'recipe {name}', 500, required=True)
    endpoint = urlsplit(recipe['endpoint'])
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise BankError('Endpoint must contain no credentials, query, or fragment')
    if type(value.get('version')) is not int or value['version'] < 1:
        raise BankError('Invalid recipe version')
    recipe['version'] = value['version']
    params = value.get('parameters', {})
    if not isinstance(params, dict):
        raise BankError('Recipe parameters must be a JSON object')
    recipe['parameters'] = bounded_json(params, 'parameters')
    capabilities = value.get('capabilities', {})
    object_payload(capabilities)
    recipe['capabilities'] = {}
    if 'max_references' in capabilities:
        maximum = capabilities['max_references']
        if type(maximum) is not int or maximum < 0 or maximum > 32:
            raise BankError('Invalid recipe reference capability')
        recipe['capabilities']['max_references'] = maximum
    for key, choices in (('asset_kinds', ASSET_KINDS), ('asset_input_kinds', ('weights', 'config'))):
        values = capabilities.get(key, [])
        if not isinstance(values, list) or any(v not in choices for v in values):
            raise BankError('Invalid recipe asset capability')
        recipe['capabilities'][key] = values
    accepted_models = capabilities.get('accepted_asset_model_ids', [])
    if not isinstance(accepted_models, list) or len(accepted_models) > 32:
        raise BankError('Invalid accepted asset models')
    recipe['capabilities']['accepted_asset_model_ids'] = [text(v, 'asset model', 500, required=True) for v in accepted_models]
    if 'first_frame' in capabilities:
        if type(capabilities['first_frame']) is not bool:
            raise BankError('Invalid recipe first-frame capability')
        recipe['capabilities']['first_frame'] = capabilities['first_frame']
    for key in ('documentation_url', 'documentation_checked_at', 'provider_version_if_exposed'):
        recipe[key] = text(value.get(key), key, 1000)
    recipe['definition_sha256'] = store.digest(json.dumps(recipe, sort_keys=True).encode())
    return recipe


def same_subject(state, item, subject):
    object_payload(item)
    source_attempt = find_attempt(state, item.get('attempt_id'))
    source_subject = source_attempt.get('subject') or {}
    if any(source_subject.get(key) != subject.get(key) for key in ('name', 'trigger_word')):
        raise BankError('Selected asset belongs to a different pinned subject')


def selected_asset(root, state, item):
    object_payload(item)
    output = find_output(state, item.get('attempt_id'), item.get('file_id'))
    if item.get('sha256') != output['sha256']:
        raise BankError('Selected asset hash does not match')
    with store.checked_stream(root, output):
        pass
    return output


@trash.serialized_transaction
def create_attempt(user_id, dataset_id, payload):
    root, state = load_mutation(user_id, dataset_id, payload)
    process = payload.get('process')
    if process not in PROCESSES:
        raise BankError('Invalid pilot process')
    recipe = validate_recipe(payload.get('recipe'))
    _, manifest, _ = export_content(user_id, dataset_id, payload.get('export_revision'), payload.get('manifest_sha256'))
    reference_entries = {e['image_path']: e for e in manifest['entries'] if e.get('role') == 'reference'}
    refs = payload.get('references', [])
    if not isinstance(refs, list) or len(refs) > 32:
        raise BankError('Invalid ordered references')
    references = []
    for item in refs:
        object_payload(item)
        entry = reference_entries.get(item.get('path'))
        if entry is None or item.get('sha256') != entry.get('image_sha256'):
            raise BankError('Input must match a pinned export reference; evaluation is held out')
        if manifest['files'].get(item['path']) != item['sha256']:
            raise BankError('Reference is not a verified export file')
        references.append({'path': item['path'], 'sha256': item['sha256'],
                           'role': text(item.get('role'), 'reference role', 200, required=True)})
    definition = next((d for d in recipes.list_recipes()
                       if d['id'] == recipe['id'] and d['version'] == recipe['version']
                       and d['provider'] == recipe['provider'] and d['endpoint'] == recipe['endpoint']), None)
    capabilities = definition.get('capabilities', {}) if definition else recipe['capabilities']
    if len(references) > capabilities.get('max_references', 32):
        raise BankError('Reference count exceeds this recipe capability')
    subject = manifest.get('subject') or {}
    if not isinstance(subject, dict):
        raise BankError('Invalid pinned subject')
    if len({r['path'] for r in references}) != len(references):
        raise BankError('Duplicate reference selection')
    first_frame = payload.get('first_frame')
    if first_frame is not None:
        if capabilities.get('first_frame') is False:
            raise BankError('This recipe does not support first frames')
        if process != 'video':
            raise BankError('First frame requires a video attempt')
        same_subject(state, first_frame, subject)
        output = selected_asset(root, state, first_frame)
        if output['kind'] != 'image' or output.get('review', {}).get('accepted') is not True:
            raise BankError('First frame requires an accepted imported still')
        first_frame = {k: first_frame[k] for k in ('attempt_id', 'file_id', 'sha256')}
    assets = payload.get('asset_inputs', [])
    if not isinstance(assets, list) or len(assets) > 8:
        raise BankError('Invalid asset inputs')
    pinned_assets = []
    for item in assets:
        same_subject(state, item, subject)
        output = selected_asset(root, state, item)
        if output['kind'] not in ('weights', 'config'):
            raise BankError('Adapter input requires weights or configuration')
        if output.get('asset_kind') not in capabilities.get('asset_kinds', []):
            raise BankError('Target recipe must explicitly support this learned asset kind')
        if output['kind'] not in capabilities.get('asset_input_kinds', []):
            raise BankError('This recipe does not support the selected asset kind')
        compatibility = output.get('compatibility', {})
        if compatibility.get('status') != 'declared':
            raise BankError('Asset compatibility must be declared before selection')
        accepted_models = capabilities.get('accepted_asset_model_ids', [recipe['model_id']])
        if output.get('model_id') not in accepted_models or output.get('base_family') != recipe['base_family']:
            raise BankError('Asset model or base family does not match recipe')
        for key in ('provider', 'endpoint'):
            if compatibility.get(key) != recipe[key]:
                raise BankError('Asset provider or endpoint does not match recipe')
        pinned_assets.append({**{k: item[k] for k in ('attempt_id', 'file_id', 'sha256')},
                              'strength': number(item.get('strength'), 'asset strength'),
                              'asset_kind': output['asset_kind'], 'model_id': output['model_id'],
                              'base_family': output['base_family'],
                              'compatibility': copy.deepcopy(compatibility),
                              'compatibility_status': 'declared', 'application_verified': False})
    status = payload.get('status', 'not_started')
    if status not in STATUSES:
        raise BankError('Invalid attempt status')
    seed = payload.get('seed')
    if seed is not None and (type(seed) is not int or abs(seed) > 2**53 - 1):
        raise BankError('Seed must be an exact integer')
    record = {'id': uuid.uuid4().hex, 'created_at': now(), 'updated_at': now(),
              'process': process, 'subject': copy.deepcopy(subject), 'export_revision': payload['export_revision'],
              'manifest_sha256': payload['manifest_sha256'], 'recipe': recipe,
              'references': references, 'first_frame': first_frame, 'asset_inputs': pinned_assets,
              'prompt': text(payload.get('prompt', ''), 'prompt', 16000), 'seed': seed,
              'request_id': text(payload.get('request_id'), 'request ID', 500),
              'status': status, 'error': text(payload.get('error'), 'error'),
              'cost': validate_cost(payload.get('cost', {})), 'notes': text(payload.get('notes'), 'notes'),
              'outputs': [], 'controls': validate_controls(state, payload.get('controls', {})),
              'hosted_acceptance_verified': False, 'application_verified': False}
    if len(state['attempts']) >= 500:
        raise BankError('Bank attempt limit reached')
    state['attempts'].append(record)
    return finish(user_id, dataset_id, root, state, payload['version'])


def validate_cost(value):
    object_payload(value)
    result = {}
    for key in ('currency', 'evidence'):
        result[key] = text(value.get(key), f'cost {key}', 2000)
    for key in ('estimated', 'reported_actual'):
        result[key] = number(value[key], f'cost {key}') if value.get(key) is not None else None
    return result


def validate_controls(state, value):
    object_payload(value)
    result = {'application_evidence': text(value.get('application_evidence'), 'application evidence')}
    for key in ('paired_without_adapter_attempt_id', 'paired_with_adapter_attempt_id'):
        aid = value.get(key)
        if aid is not None:
            find_attempt(state, aid)
        result[key] = aid
    result['application_verified'] = False
    return result


@trash.serialized_transaction
def update_attempt(user_id, dataset_id, attempt_id, payload):
    root, state = load_mutation(user_id, dataset_id, payload)
    record = find_attempt(state, attempt_id)
    if set(payload) - {'version', 'status', 'request_id', 'cost', 'notes', 'error', 'controls'}:
        raise BankError('Attempt inputs and recipe are immutable')
    if 'status' in payload:
        if payload['status'] not in STATUSES:
            raise BankError('Invalid attempt status')
        record['status'] = payload['status']
    for key in ('request_id', 'notes', 'error'):
        if key in payload:
            record[key] = text(payload[key], key, 500 if key == 'request_id' else 4000)
    if 'cost' in payload:
        record['cost'] = validate_cost(payload['cost'])
    if 'controls' in payload:
        record['controls'] = validate_controls(state, payload['controls'])
    record['updated_at'] = now()
    return finish(user_id, dataset_id, root, state, payload['version'])


def file_metadata(root, state, value, recipe, subject):
    object_payload(value)
    kind = value.get('kind')
    if kind not in KINDS:
        raise BankError('Invalid imported asset kind')
    asset_kind = value.get('asset_kind')
    if kind in ('weights', 'config') and asset_kind not in ASSET_KINDS:
        raise BankError('Weights/config require an explicit learned asset kind')
    result = {'kind': kind, 'asset_kind': asset_kind if kind in ('weights', 'config') else None}
    original = value.get('original_name')
    if original:
        original = re.split(r'[/\\]', text(original, 'original filename', 500))[-1]
    result['original_name'] = original
    suffix = Path(original).suffix.lower().lstrip('.') if original else value.get('file_format', 'bin')
    permitted = {'weights': ('safetensors', 'gguf', 'pt', 'ckpt', 'bin'),
                 'config': ('json', 'yaml', 'yml', 'toml', 'txt', 'bin')}
    result['file_format'] = suffix if suffix in permitted.get(kind, ()) else 'bin'
    for key in ('model_id', 'base_family', 'checkpoint', 'trigger', 'notes'):
        result[key] = text(value.get(key, recipe.get(key)), key)
    if kind in ('weights', 'config') and (not result['model_id'] or not result['base_family']):
        raise BankError('Weights/config require model and base family')
    compatibility = value.get('compatibility', {'status': 'unproven'})
    object_payload(compatibility)
    if compatibility.get('status') not in ('unproven', 'declared'):
        raise BankError('Compatibility is unproven or user-declared, never automatically verified')
    result['compatibility'] = {'status': compatibility['status'], 'application_verified': False}
    for key in ('provider', 'endpoint'):
        result['compatibility'][key] = text(compatibility.get(key), f'compatibility {key}', 500,
                                            required=compatibility['status'] == 'declared')
        if key == 'endpoint' and result['compatibility'][key]:
            endpoint = urlsplit(result['compatibility'][key])
            if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
                raise BankError('Compatibility endpoint must contain no credentials, query, or fragment')
    config_id = value.get('configuration_file_id')
    if config_id is not None:
        configs = [(a, o) for a in state['attempts'] for o in a['outputs'] if o['id'] == config_id]
        if not configs or configs[0][1]['kind'] != 'config':
            raise BankError('Configuration file not found')
        config_attempt, config = configs[0]
        if any((config_attempt.get('subject') or {}).get(key) != subject.get(key) for key in ('name', 'trigger_word')):
            raise BankError('Configuration belongs to a different pinned subject')
        with store.checked_stream(root, config):
            pass
        if (config['model_id'], config['base_family'], config.get('asset_kind')) != (result['model_id'], result['base_family'], result['asset_kind']):
            raise BankError('Configuration model or base family does not match')
        result['configuration_sha256'] = config['sha256']
    result['configuration_file_id'] = config_id
    for key in ('rights', 'storage_evidence', 'backup_evidence'):
        result[key] = bounded_json(value.get(key, {}), key, 8000)
    return result


def append_import(user_id, dataset_id, root, state, attempt_id, version, stream, metadata, parent_sha256=None):
    attempt = find_attempt(state, attempt_id)
    record = file_metadata(root, state, metadata, attempt['recipe'], attempt.get('subject') or {})
    if len(attempt['outputs']) >= 64:
        raise BankError('Attempt file limit reached')
    file_id, path, sha256, size = store.write_upload(root, stream, store.FILE_LIMITS[record['kind']])
    try:
        if record['kind'] in ('image', 'video'):
            with media_snapshot(root, {'id': file_id, 'sha256': sha256, 'size': size}) as verified_path:
                mime, probe = media.inspect(verified_path, record['kind'], sha256)
        else:
            if store.hash_file(root, f'files/{file_id}') != sha256:
                raise BankError('Imported asset changed', 409)
            mime, probe = 'application/octet-stream', None
        suffix = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp',
                  'video/mp4': 'mp4', 'video/webm': 'webm'}.get(mime, record['file_format'])
        record['file_format'] = suffix
        record['download_name'] = f'{file_id}.{suffix}'
        record['archive_path'] = f'files/{file_id}.{suffix}'
        record.update({'id': file_id, 'sha256': sha256, 'size': size, 'mime_type': mime,
                       'created_at': now(), 'probe': probe, 'parent_sha256': parent_sha256,
                       'review': {'accepted': False, 'whole_clip_viewed': False,
                                  'no_audio_stream_verified': bool(probe and probe['no_audio_stream_verified'])},
                       'url': f'/api/dataset/{dataset_id}/pilot-bank/attempts/{attempt_id}/files/{file_id}'})
        attempt['outputs'].append(record)
        attempt['updated_at'] = now()
        return finish(user_id, dataset_id, root, state, version)
    except BaseException:
        # Preserve a successfully published record even if later snapshot reading fails.
        published = store.state(root)
        if not any(o['id'] == file_id for a in published['attempts'] for o in a['outputs']):
            path.unlink(missing_ok=True)
        raise


@trash.serialized_transaction
def import_file(user_id, dataset_id, attempt_id, version, stream, metadata):
    root, state = load_mutation(user_id, dataset_id, {'version': version})
    return append_import(user_id, dataset_id, root, state, attempt_id, version, stream, metadata)


def open_file(user_id, dataset_id, attempt_id, file_id):
    root = store.root_for(user_id, dataset_id)
    output = find_output(store.state(root), attempt_id, file_id)
    return store.checked_stream(root, output), output


@trash.serialized_transaction
def review_file(user_id, dataset_id, attempt_id, file_id, payload):
    root, state = load_mutation(user_id, dataset_id, payload)
    output = find_output(state, attempt_id, file_id)
    with store.checked_stream(root, output):
        pass
    value = object_payload(payload.get('review'))
    result = {'reviewed_at': now()}
    for key in ('accepted', 'whole_clip_viewed', 'subject_recognises_likeness'):
        flag = value.get(key, False)
        if type(flag) is not bool:
            raise BankError(f'Invalid review {key}')
        result[key] = flag
    for key in ('face_detail', 'hands_body', 'prompt_adherence', 'clothing_flexibility',
                'copied_surroundings', 'composition_and_final_crop', 'reason'):
        result[key] = text(value.get(key), key)
    result['correction_minutes'] = number(value['correction_minutes'], 'correction minutes') if value.get('correction_minutes') is not None else None
    observations = value.get('timed_observations', [])
    if not isinstance(observations, list) or len(observations) > 100:
        raise BankError('Invalid timed observations')
    result['timed_observations'] = [{'time_seconds': number(object_payload(o).get('time_seconds'), 'observation time'),
                                     'note': text(o.get('note'), 'observation note', required=True)} for o in observations]
    if output['kind'] == 'video':
        with media_snapshot(root, output) as verified_path:
            output['probe'] = media.probe(verified_path, output['sha256'])
        with store.checked_stream(root, output):
            pass
    probe = output.get('probe')
    result['no_audio_stream_verified'] = bool(probe and probe.get('status') == 'verified'
                                             and probe.get('sha256') == output['sha256']
                                             and probe.get('no_audio_stream_verified'))
    if result['accepted'] and output['kind'] in ('image', 'video') and not result['subject_recognises_likeness']:
        raise BankError('Acceptance requires subject likeness review')
    if result['accepted'] and output['kind'] == 'video' and (not result['whole_clip_viewed'] or not result['no_audio_stream_verified']):
        raise BankError('Video acceptance requires whole-clip review and exact-file verified absence of audio')
    output['review'] = result
    return finish(user_id, dataset_id, root, state, payload['version'])


@trash.serialized_transaction
def silent_file(user_id, dataset_id, attempt_id, file_id, payload):
    root, state = load_mutation(user_id, dataset_id, payload)
    output = find_output(state, attempt_id, file_id)
    if output['kind'] != 'video':
        raise BankError('Silent derivative requires a video')
    with store.checked_stream(root, output):
        pass
    # The destination is private, generated, and never provider fetched.
    with media_snapshot(root, output) as source, tempfile.TemporaryDirectory(prefix='private_video_') as folder:
        target = Path(folder) / 'silent.mp4'
        media.make_silent(source, target)
        with store.checked_stream(root, output):
            pass
        with target.open('rb') as stream:
            return append_import(user_id, dataset_id, root, state, attempt_id, payload['version'],
                                 stream, {**output, 'notes': 'Silent derivative; original preserved'}, output['sha256'])


@contextmanager
def media_snapshot(root, output):
    # Tools consume exact verified bytes from a private copy, never the mutable bank path.
    with store.checked_stream(root, output) as source, tempfile.TemporaryDirectory(prefix='private_media_') as folder:
        target = Path(folder) / 'input.bin'
        with target.open('xb') as destination:
            os.chmod(target, 0o600)
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        yield target


def download(user_id, dataset_id, destination):
    root = store.root_for(user_id, dataset_id)
    state = store.state(root)
    exports = {}
    for attempt in state['attempts']:
        key = (attempt['export_revision'], attempt['manifest_sha256'])
        if key not in exports:
            exports[key] = export_content(user_id, dataset_id, *key)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('bank.json', json.dumps(state, ensure_ascii=False, indent=2))
        archive.writestr('README.txt', 'Private person bank. Includes original bytes, reviews and pinned exports.\n'
                         'Compatibility declarations and manual request records are not proof of provider application.\n'
                         'Ordinary dataset backups exclude this bank. Keep this complete ZIP private.\n')
        records = store.contained(root, 'records')
        if records.exists():
            for revision_file in sorted(records.iterdir()):
                if (re.fullmatch(r'[0-9]{10}\.json', revision_file.name)
                        and int(revision_file.name[:10]) <= state['version']):
                    raw = store.read_bytes(root, f'records/{revision_file.name}', store.MAX_RECORD_BYTES)
                    archive.writestr(f'records/{revision_file.name}', raw)
        for attempt in state['attempts']:
            for output in attempt['outputs']:
                with store.checked_stream(root, output) as source, archive.open(safe_archive_path(output), 'w', force_zip64=True) as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
        for (revision, _), (export_root, manifest, raw) in exports.items():
            archive.writestr(f'exports/{revision}/manifest.json', raw)
            for relative, expected in manifest['files'].items():
                store.archive_export_file(archive, export_root, relative, expected,
                                          f'exports/{revision}/{relative}')


def open_export_image(user_id, dataset_id, revision, relative, manifest_sha256):
    root, manifest, _ = export_content(user_id, dataset_id, revision, manifest_sha256, verify_files=False)
    entry = next((e for e in manifest['entries'] if e.get('image_path') == relative
                  and e.get('role') in ('reference', 'evaluation')), None)
    if entry is None:
        raise BankError('Review image not found', 404)
    if manifest['files'].get(relative) != entry.get('image_sha256'):
        raise BankError('Review image is not a verified export file')
    if Path(relative).suffix.lower() != '.png':
        raise BankError('Review images must be exported PNG files')
    return store.verified_stream(root, relative, entry['image_sha256'], limit=store.FILE_LIMITS['image'])


def safe_archive_path(output):
    if not store.ID.fullmatch(output.get('id', '')):
        raise BankError('Invalid bank file identifier')
    suffix = output.get('file_format', 'bin')
    if suffix not in ('png', 'jpg', 'webp', 'mp4', 'webm', 'safetensors', 'gguf', 'pt',
                      'ckpt', 'json', 'yaml', 'yml', 'toml', 'txt', 'bin'):
        raise BankError('Invalid bank file format')
    return f"files/{output['id']}.{suffix}"


@trash.serialized_transaction
def update_file_metadata(user_id, dataset_id, attempt_id, file_id, payload):
    root, state = load_mutation(user_id, dataset_id, payload)
    allowed = {'version', 'compatibility', 'rights', 'storage_evidence', 'backup_evidence'}
    if set(payload) - allowed:
        raise BankError('Asset bytes, kind, model, base and creation metadata are immutable')
    attempt = find_attempt(state, attempt_id)
    output = find_output(state, attempt_id, file_id)
    if output['kind'] not in ('weights', 'config'):
        raise BankError('Asset evidence requires weights or configuration')
    with store.checked_stream(root, output):
        pass
    edited = {**output, **{k: v for k, v in payload.items() if k != 'version'}}
    validated = file_metadata(root, state, edited, attempt['recipe'], attempt.get('subject') or {})
    for key in allowed - {'version'}:
        if key in payload:
            output[key] = validated[key]
    output['evidence_updated_at'] = now()
    return finish(user_id, dataset_id, root, state, payload['version'])
