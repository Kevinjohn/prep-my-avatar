import hashlib
import io
import json
import zipfile

import pytest
from PIL import Image

from app.config import LOCAL_USER


def seed_bank(name='First subject'):
    from app.services import face_dataset_service as fds
    ds = fds.create_dataset(LOCAL_USER, name, 'person_token')
    root = __import__('pathlib').Path(fds._dataset_dir(ds.id)) / 'hosted_exports' / ('avatar_export_' + 'a' * 32)
    root.mkdir(parents=True)
    picture = io.BytesIO()
    Image.new('RGB', (40, 40), 'red').save(picture, 'PNG')
    data = picture.getvalue()
    entries = []
    files = {}
    for role in ('reference', 'evaluation'):
        path = f'{role}/one.png'
        (root / role).mkdir()
        (root / path).write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        entries.append({'image_path': path, 'image_sha256': sha, 'role': role, 'reference_role': 'identity'})
        files[path] = sha
    manifest = {'format': 'person-hosted-export', 'schema_version': 1, 'dataset_id': ds.id,
                'export_revision': root.name, 'entries': entries, 'files': files,
                'subject': {'name': name}, 'recipe': {}}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return ds, root, data


def attempt(snapshot, **extra):
    export = snapshot['exports'][0]
    ref = export['entries'][0]
    return {'version': snapshot['version'], 'export_revision': export['revision'],
            'manifest_sha256': export['manifest_sha256'], 'process': 'still',
            'recipe': {'id': 'manual', 'version': 1, 'provider': 'manual',
                       'endpoint': 'image-endpoint', 'model_id': 'image-model',
                       'base_family': 'image-base', 'parameters': {'steps': 20}},
            'references': [{'path': ref['image_path'], 'sha256': ref['image_sha256'], 'role': 'identity'}],
            'prompt': 'Portrait in a new scene', 'status': 'failed', 'notes': '', **extra}


def test_attempt_upload_review_bytes_and_complete_archive(app):
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, root, data = seed_bank()
        state = svc.get_bank(LOCAL_USER, ds.id)
        state = svc.create_attempt(LOCAL_USER, ds.id, attempt(state))
        assert state['attempts'][0]['status'] == 'failed'
        assert state['attempts'][0]['outputs'] == []
        aid = state['attempts'][0]['id']
        state = svc.import_file(LOCAL_USER, ds.id, aid, state['version'], io.BytesIO(data),
                                {'kind': 'image'})
        output = state['attempts'][0]['outputs'][0]
        stream, record = svc.open_file(LOCAL_USER, ds.id, aid, output['id'])
        with stream:
            assert stream.read() == data
        assert record['sha256'] == hashlib.sha256(data).hexdigest()
        state = svc.review_file(LOCAL_USER, ds.id, aid, output['id'],
                                {'version': state['version'], 'review': {'accepted': True,
                                 'subject_recognises_likeness': True, 'reason': 'Reviewed'}})
        assert state['attempts'][0]['outputs'][0]['review']['accepted']
        archive = io.BytesIO()
        svc.download(LOCAL_USER, ds.id, archive)
        with zipfile.ZipFile(archive) as z:
            assert any(n.endswith('manifest.json') for n in z.namelist())
            assert any(n.endswith('reference/one.png') for n in z.namelist())
            assert json.loads(z.read('bank.json'))['version'] == state['version']
        assert (root / 'manifest.json').exists()


def test_evaluation_tamper_stale_and_subject_isolation(app):
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, root, data = seed_bank()
        other, _, _ = seed_bank('Second subject')
        state = svc.get_bank(LOCAL_USER, ds.id)
        payload = attempt(state)
        payload['references'][0]['path'] = 'evaluation/one.png'
        with pytest.raises(svc.BankError, match='reference'):
            svc.create_attempt(LOCAL_USER, ds.id, payload)
        state = svc.create_attempt(LOCAL_USER, ds.id, attempt(state))
        with pytest.raises(svc.BankError, match='changed'):
            svc.create_attempt(LOCAL_USER, ds.id, attempt({**state, 'version': 0}))
        aid = state['attempts'][0]['id']
        with pytest.raises(svc.BankError, match='not found'):
            svc.import_file(LOCAL_USER, other.id, aid, 0, io.BytesIO(data), {'kind': 'image'})
        (root / 'reference/one.png').write_bytes(b'tampered')
        with pytest.raises(svc.BankError, match='changed'):
            svc.create_attempt(LOCAL_USER, ds.id, attempt(state))


def test_routes_are_registered_and_reject_bad_json(client, app):
    with app.app_context():
        ds, _, _ = seed_bank()
    url = f'/api/dataset/{ds.id}/pilot-bank'
    assert client.get(url).status_code == 200
    response = client.post(url + '/attempts', json=[])
    assert response.status_code == 400
    assert client.get('/api/dataset/987654/pilot-bank').status_code == 404


def prepare_output(svc, ds, state, data, metadata=None):
    state = svc.create_attempt(LOCAL_USER, ds.id, attempt(state))
    aid = state['attempts'][-1]['id']
    state = svc.import_file(LOCAL_USER, ds.id, aid, state['version'], io.BytesIO(data), metadata or {'kind': 'image'})
    return state, aid, state['attempts'][-1]['outputs'][-1]


def test_import_tamper_snapshot_and_safe_name(client, app):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_storage as store
    with app.app_context():
        ds, _, data = seed_bank()
        state, aid, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), data)
        root = store.root_for(LOCAL_USER, ds.id)
        source, _ = svc.open_file(LOCAL_USER, ds.id, aid, output['id'])
        (root / 'files' / output['id']).write_bytes(b'mutation')
        with source:
            assert source.read() == data  # verified stream cannot change after checking
        with pytest.raises(svc.BankError, match='changed'):
            svc.open_file(LOCAL_USER, ds.id, aid, output['id'])
        with pytest.raises(svc.BankError, match='changed'):
            svc.review_file(LOCAL_USER, ds.id, aid, output['id'], {'version': state['version'], 'review': {}})
        assert output['download_name'].endswith('.png')
    response = client.get(output['url'])
    assert response.status_code == 409
    assert 'mutation' not in response.json['error']


@pytest.mark.parametrize('bad_path', ['../outside', '/tmp/outside', 'reference/../../outside', 'reference\\one.png'])
def test_export_traversal_rejected(app, bad_path):
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, root, _ = seed_bank()
        manifest = json.loads((root / 'manifest.json').read_text())
        manifest['files'][bad_path] = 'b' * 64
        (root / 'manifest.json').write_text(json.dumps(manifest))
        state = svc.get_bank(LOCAL_USER, ds.id)
        with pytest.raises(svc.BankError, match='Unsafe'):
            svc.create_attempt(LOCAL_USER, ds.id, attempt(state))


def test_symlink_in_export_bank_and_file_rejected(app, tmp_path):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_storage as store
    with app.app_context():
        ds, root, data = seed_bank()
        state, aid, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), data)
        bank_root = store.root_for(LOCAL_USER, ds.id)
        file = bank_root / 'files' / output['id']
        file.unlink()
        target = tmp_path / 'outside.png'
        target.write_bytes(data)
        file.symlink_to(target)
        with pytest.raises(svc.BankError, match='symlink'):
            svc.open_file(LOCAL_USER, ds.id, aid, output['id'])
        ref = root / 'reference/one.png'
        ref.unlink()
        ref.symlink_to(target)
        with pytest.raises(svc.BankError, match='symlink'):
            svc.create_attempt(LOCAL_USER, ds.id, attempt(state))
        file.unlink()
        ref.unlink()
        bank_root.rename(bank_root.with_name('saved_bank'))
        bank_root.symlink_to(bank_root.with_name('saved_bank'), target_is_directory=True)
        with pytest.raises(svc.BankError, match='symlink'):
            svc.get_bank(LOCAL_USER, ds.id)


def test_atomic_concurrent_publication_preserves_one_winner(app):
    import copy
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.services import pilot_bank_storage as store
    with app.app_context():
        ds, _, _ = seed_bank()
        root = store.root_for(LOCAL_USER, ds.id)
        initial = store.state(root)
        barrier = Barrier(2)

        def write(label):
            state = copy.deepcopy(initial)
            state['attempts'].append({'id': label})
            barrier.wait()
            try:
                store.publish(root, state, 0)
                return 'saved'
            except store.BankError as error:
                assert error.status == 409
                return 'conflict'

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ['one', 'two']))
        assert sorted(results) == ['conflict', 'saved']
        persisted = store.state(root)
        assert persisted['version'] == 1
        assert len(persisted['attempts']) == 1
        assert not list((root / 'records').glob('*.tmp'))


def test_oversize_corrupt_and_empty_imports_leave_no_output(app, monkeypatch):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_storage as store
    with app.app_context():
        ds, _, data = seed_bank()
        state = svc.create_attempt(LOCAL_USER, ds.id, attempt(svc.get_bank(LOCAL_USER, ds.id)))
        aid = state['attempts'][0]['id']
        for bad in (b'', b'not-an-image'):
            with pytest.raises(svc.BankError):
                svc.import_file(LOCAL_USER, ds.id, aid, state['version'], io.BytesIO(bad), {'kind': 'image'})
        monkeypatch.setitem(store.FILE_LIMITS, 'image', len(data) - 1)
        with pytest.raises(svc.BankError, match='limit'):
            svc.import_file(LOCAL_USER, ds.id, aid, state['version'], io.BytesIO(data), {'kind': 'image'})
        assert svc.get_bank(LOCAL_USER, ds.id)['attempts'][0]['outputs'] == []
        assert list((store.root_for(LOCAL_USER, ds.id) / 'files').iterdir()) == []


def video_bytes():
    return b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00synthetic-container'


def test_video_no_tool_or_failed_probe_is_retained_but_not_accepted(app, monkeypatch):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_media as media
    monkeypatch.setattr(media.shutil, 'which', lambda _: None)
    with app.app_context():
        ds, _, _ = seed_bank()
        state, aid, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), video_bytes(), {'kind': 'video'})
        assert output['probe']['status'] == 'unverified'
        with pytest.raises(svc.BankError, match='verified'):
            svc.review_file(LOCAL_USER, ds.id, aid, output['id'], {'version': state['version'], 'review': {
                'accepted': True, 'subject_recognises_likeness': True,
                'whole_clip_viewed': True, 'no_audio_stream_verified': True}})
        monkeypatch.setattr(media.shutil, 'which', lambda _: '/fake/ffprobe')
        monkeypatch.setattr(media, 'run_local', lambda *_, **__: b'invalid JSON')
        state = svc.review_file(LOCAL_USER, ds.id, aid, output['id'], {'version': state['version'], 'review': {'reason': 'Needs verification'}})
        assert state['attempts'][0]['outputs'][0]['probe']['status'] == 'unverified'
        assert state['attempts'][0]['outputs'][0]['review']['no_audio_stream_verified'] is False


def test_video_probe_exact_hash_and_whole_clip_acceptance(app, monkeypatch):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_media as media
    calls = []
    monkeypatch.setattr(media.shutil, 'which', lambda _: '/fake/ffprobe')

    def fake(args, **kwargs):
        calls.append(args)
        return json.dumps({'streams': [{'codec_type': 'video', 'codec_name': 'h264'}],
                           'format': {'duration': '1'}}).encode()

    monkeypatch.setattr(media, 'run_local', fake)
    with app.app_context():
        ds, _, _ = seed_bank()
        state, aid, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), video_bytes(), {'kind': 'video'})
        assert output['probe']['sha256'] == output['sha256']
        assert output['probe']['no_audio_stream_verified'] is True
        for whole in (False, True):
            payload = {'version': state['version'], 'review': {'accepted': True,
                       'subject_recognises_likeness': True, 'whole_clip_viewed': whole,
                       'timed_observations': [{'time_seconds': 0.5, 'note': 'Consistent face'}]}}
            if not whole:
                with pytest.raises(svc.BankError, match='whole-clip'):
                    svc.review_file(LOCAL_USER, ds.id, aid, output['id'], payload)
            else:
                state = svc.review_file(LOCAL_USER, ds.id, aid, output['id'], payload)
        assert state['attempts'][0]['outputs'][0]['review']['accepted']
        assert all('file,pipe' in call and '-format_whitelist' in call for call in calls)


def test_silent_derivative_keeps_exact_original_and_requires_re_review(app, monkeypatch):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_media as media
    monkeypatch.setattr(media.shutil, 'which', lambda _: None)
    with app.app_context():
        ds, _, _ = seed_bank()
        original = video_bytes()
        state, aid, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), original, {'kind': 'video'})
        monkeypatch.setattr(media, 'make_silent', lambda source, target: target.write_bytes(original + b'silent'))
        monkeypatch.setattr(media, 'probe', lambda path, sha: {'status': 'verified', 'sha256': sha, 'no_audio_stream_verified': True})
        state = svc.silent_file(LOCAL_USER, ds.id, aid, output['id'], {'version': state['version']})
        derivative = state['attempts'][0]['outputs'][-1]
        assert derivative['parent_sha256'] == output['sha256']
        assert derivative['sha256'] != output['sha256']
        assert derivative['review']['accepted'] is False
        source, _ = svc.open_file(LOCAL_USER, ds.id, aid, output['id'])
        with source:
            assert source.read() == original


def test_first_frame_requires_accepted_still_and_same_pinned_subject(app):
    import copy
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, root, data = seed_bank()
        state, aid, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), data)
        selected = {'attempt_id': aid, 'file_id': output['id'], 'sha256': output['sha256']}
        with pytest.raises(svc.BankError, match='accepted'):
            svc.create_attempt(LOCAL_USER, ds.id, attempt(state, process='video', first_frame=selected))
        state = svc.review_file(LOCAL_USER, ds.id, aid, output['id'], {'version': state['version'], 'review': {
            'accepted': True, 'subject_recognises_likeness': True}})
        state = svc.create_attempt(LOCAL_USER, ds.id, attempt(state, process='video', first_frame=selected))
        assert state['attempts'][-1]['first_frame']['sha256'] == output['sha256']
        import shutil
        changed = root.with_name('avatar_export_' + 'b' * 32)
        shutil.copytree(root, changed)
        manifest = json.loads((changed / 'manifest.json').read_text())
        manifest['subject']['name'] = 'Different identity'
        manifest['export_revision'] = changed.name
        (changed / 'manifest.json').write_text(json.dumps(manifest))
        state = svc.get_bank(LOCAL_USER, ds.id)
        payload = attempt(state, process='video', first_frame=selected)
        target = next(e for e in state['exports'] if e['revision'] == changed.name)
        payload.update(export_revision=target['revision'], manifest_sha256=target['manifest_sha256'])
        with pytest.raises(svc.BankError, match='different pinned subject'):
            svc.create_attempt(LOCAL_USER, ds.id, copy.deepcopy(payload))


def test_adapter_compatibility_requires_kind_model_base_and_declared_target(app):
    import copy
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, _, _ = seed_bank()
        state = svc.get_bank(LOCAL_USER, ds.id)
        state, aid, output = prepare_output(svc, ds, state, b'opaque-weights', {
            'kind': 'weights', 'asset_kind': 'lora', 'model_id': 'trained-base', 'base_family': 'image-base',
            'original_name': '../../returned.safetensors',
            'compatibility': {'status': 'declared', 'provider': 'manual', 'endpoint': 'image-endpoint'}})
        assert output['download_name'].endswith('.safetensors')
        selected = {'attempt_id': aid, 'file_id': output['id'], 'sha256': output['sha256'], 'strength': 0.7}
        payload = attempt(state, asset_inputs=[selected])
        with pytest.raises(svc.BankError, match='asset kind'):
            svc.create_attempt(LOCAL_USER, ds.id, payload)
        payload['recipe']['capabilities'] = {'asset_kinds': ['lora'], 'asset_input_kinds': ['weights'],
                                            'accepted_asset_model_ids': ['trained-base']}
        bad = copy.deepcopy(payload)
        bad['recipe']['base_family'] = 'different-base'
        with pytest.raises(svc.BankError, match='base family'):
            svc.create_attempt(LOCAL_USER, ds.id, bad)
        state = svc.create_attempt(LOCAL_USER, ds.id, payload)
        assert state['attempts'][-1]['asset_inputs'][0]['application_verified'] is False
        assert state['attempts'][-1]['asset_inputs'][0]['strength'] == 0.7
        archive = io.BytesIO()
        svc.download(LOCAL_USER, ds.id, archive)
        with zipfile.ZipFile(archive) as z:
            assert z.read(output['archive_path']) == b'opaque-weights'


def test_attempt_reconciliation_and_immutable_capture(app):
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, _, _ = seed_bank()
        state = svc.create_attempt(LOCAL_USER, ds.id, attempt(svc.get_bank(LOCAL_USER, ds.id), status='unknown'))
        aid = state['attempts'][0]['id']
        state = svc.update_attempt(LOCAL_USER, ds.id, aid, {'version': state['version'], 'status': 'failed',
                                   'request_id': 'provider-123', 'error': 'Provider rejected request',
                                   'cost': {'currency': 'GBP', 'reported_actual': 0}})
        record = state['attempts'][0]
        assert record['outputs'] == []
        assert record['status'] == 'failed'
        assert record['request_id'] == 'provider-123'
        assert record['cost']['reported_actual'] == 0
        with pytest.raises(svc.BankError, match='immutable'):
            svc.update_attempt(LOCAL_USER, ds.id, aid, {'version': state['version'], 'prompt': 'Changed'})


def test_metadata_upload_route_and_download_attachment(client, app):
    with app.app_context():
        from app.services import pilot_bank as svc
        ds, _, _ = seed_bank()
        state = svc.create_attempt(LOCAL_USER, ds.id, attempt(svc.get_bank(LOCAL_USER, ds.id)))
    aid = state['attempts'][0]['id']
    url = f'/api/dataset/{ds.id}/pilot-bank/attempts/{aid}/files'
    response = client.post(url, data={'version': str(state['version']),
        'metadata': json.dumps({'kind': 'config', 'asset_kind': 'lora'}),
        'file': (io.BytesIO(b'{"opaque":true}'), '../../provider_config.json')})
    assert response.status_code == 200
    output = response.json['attempts'][0]['outputs'][0]
    assert output['download_name'].endswith('.json')
    response = client.get(output['url'])
    assert response.data == b'{"opaque":true}'
    assert response.headers['Content-Disposition'].startswith('attachment;')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Cache-Control'] == 'no-store'


def test_review_and_silent_tools_consume_exact_private_snapshot(app, monkeypatch):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_media as media
    from app.services import pilot_bank_storage as store
    monkeypatch.setattr(media.shutil, 'which', lambda _: None)
    with app.app_context():
        ds, _, _ = seed_bank()
        original = video_bytes() + b'has-audio'
        state, aid, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), original, {'kind': 'video'})
        bank_path = store.root_for(LOCAL_USER, ds.id) / 'files' / output['id']
        seen = []

        def racing_probe(path, sha):
            bank_path.write_bytes(video_bytes() + b'silent')
            seen.append(path.read_bytes())
            bank_path.write_bytes(original)
            return {'status': 'verified', 'sha256': sha, 'no_audio_stream_verified': False}

        monkeypatch.setattr(media, 'probe', racing_probe)
        state = svc.review_file(LOCAL_USER, ds.id, aid, output['id'], {'version': state['version'], 'review': {}})
        assert seen == [original]
        assert state['attempts'][0]['outputs'][0]['review']['no_audio_stream_verified'] is False

        def racing_silent(source, destination):
            bank_path.write_bytes(video_bytes() + b'replacement')
            seen.append(source.read_bytes())
            bank_path.write_bytes(original)
            destination.write_bytes(video_bytes() + b'converted')

        monkeypatch.setattr(media, 'make_silent', racing_silent)
        state = svc.silent_file(LOCAL_USER, ds.id, aid, output['id'], {'version': state['version']})
        assert seen[:2] == [original, original]
        assert state['attempts'][0]['outputs'][-1]['parent_sha256'] == output['sha256']


def test_known_reference_limit_and_zip64_output_members(app, monkeypatch):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_recipes as recipes
    with app.app_context():
        ds, root, data = seed_bank()
        manifest = json.loads((root / 'manifest.json').read_text())
        for i in range(12):
            path = f'reference/{i}.png'
            (root / path).write_bytes(data)
            manifest['files'][path] = hashlib.sha256(data).hexdigest()
            manifest['entries'].insert(0, {'image_path': path, 'image_sha256': hashlib.sha256(data).hexdigest(), 'role': 'reference'})
        (root / 'manifest.json').write_text(json.dumps(manifest))
        state = svc.get_bank(LOCAL_USER, ds.id)
        recipe = next(r for r in recipes.list_recipes() if r['id'] == 'manual-video')
        payload = attempt(state, process='video', recipe=recipe)
        payload['references'] = [{'path': e['image_path'], 'sha256': e['image_sha256'], 'role': 'identity'}
                                 for e in manifest['entries'] if e['role'] == 'reference']
        with pytest.raises(svc.BankError, match='capability'):
            svc.create_attempt(LOCAL_USER, ds.id, payload)
        state, _, output = prepare_output(svc, ds, state, data)
        opened = []
        original_open = zipfile.ZipFile.open

        def tracking_open(self, name, mode='r', pwd=None, *, force_zip64=False):
            if mode == 'w' and isinstance(name, str) and name.startswith('files/'):
                opened.append(force_zip64)
            return original_open(self, name, mode, pwd, force_zip64=force_zip64)

        monkeypatch.setattr(zipfile.ZipFile, 'open', tracking_open)
        archive = io.BytesIO()
        svc.download(LOCAL_USER, ds.id, archive)
        assert opened == [True]
        with zipfile.ZipFile(archive) as z:
            assert z.read(output['archive_path']) == data


def test_config_binding_rejects_different_learned_kind_and_preserves_hash(app):
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, _, _ = seed_bank()
        state, aid, config = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), b'opaque-config',
                                           {'kind': 'config', 'asset_kind': 'lora', 'original_name': 'config.json'})
        with pytest.raises(svc.BankError, match='Configuration model'):
            svc.import_file(LOCAL_USER, ds.id, aid, state['version'], io.BytesIO(b'weights'),
                            {'kind': 'weights', 'asset_kind': 'checkpoint', 'configuration_file_id': config['id']})
        state = svc.import_file(LOCAL_USER, ds.id, aid, state['version'], io.BytesIO(b'weights'),
                                {'kind': 'weights', 'asset_kind': 'lora', 'configuration_file_id': config['id']})
        assert state['attempts'][0]['outputs'][-1]['configuration_sha256'] == config['sha256']


def test_import_serializes_with_dataset_deletion(threaded_app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_storage as store
    from app.services import face_dataset_service as fds
    entered, release, delete_entered = Event(), Event(), Event()
    with threaded_app.app_context():
        ds, _, data = seed_bank()
        dataset_id = ds.id
        state = svc.create_attempt(LOCAL_USER, ds.id, attempt(svc.get_bank(LOCAL_USER, ds.id)))
        aid = state['attempts'][0]['id']
        dataset_root = store.dataset_root(LOCAL_USER, ds.id)
    original_write = store.write_upload

    def blocked_write(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(store, 'write_upload', blocked_write)

    def upload():
        with threaded_app.app_context():
            return svc.import_file(LOCAL_USER, dataset_id, aid, state['version'], io.BytesIO(data), {'kind': 'image'})

    def delete():
        with threaded_app.app_context():
            delete_entered.set()
            return fds.delete_dataset(LOCAL_USER, dataset_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        upload_future = pool.submit(upload)
        assert entered.wait(5)
        delete_future = pool.submit(delete)
        assert delete_entered.wait(5)
        release.set()
        assert upload_future.result(timeout=10)['version'] == state['version'] + 1
        assert delete_future.result(timeout=10)
    assert not dataset_root.exists()
    with threaded_app.app_context(), pytest.raises(svc.BankError, match='Dataset not found'):
        svc.import_file(LOCAL_USER, dataset_id, aid, state['version'], io.BytesIO(data), {'kind': 'image'})
    assert not dataset_root.exists()


def test_verified_media_ranges_support_seek_and_reject_invalid_range(client, app):
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, _, data = seed_bank()
        state, _, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), data)
    response = client.get(output['url'], headers={'Range': 'bytes=0-15'})
    assert response.status_code == 206
    assert response.data == data[:16]
    assert response.headers['Content-Range'] == f'bytes 0-15/{len(data)}'
    response = client.get(output['url'], headers={'Range': f'bytes={len(data)+20}-'})
    assert response.status_code == 416


def test_export_review_gallery_is_exact_owned_and_held_out(client, app):
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, root, data = seed_bank()
        other, _, _ = seed_bank('Second subject')
        state = svc.get_bank(LOCAL_USER, ds.id)
        export = state['exports'][0]
        evaluation = next(e for e in export['entries'] if e['role'] == 'evaluation')
        url = evaluation['preview_url']
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == data
    assert response.headers['Content-Type'] == 'image/png'
    other_url = url.replace(f'dataset/{ds.id}/', f'dataset/{other.id}/')
    assert client.get(other_url).status_code != 200
    base = f'/api/dataset/{ds.id}/pilot-bank/exports/{export["revision"]}/files/'
    assert client.get(base + f'manifest.json?manifest_sha256={export["manifest_sha256"]}').status_code == 404
    assert client.get(base + f'../manifest.json?manifest_sha256={export["manifest_sha256"]}').status_code != 200
    (root / 'evaluation/one.png').write_bytes(b'tampered')
    assert client.get(url).status_code == 409


def test_requested_manifest_hash_and_file_hash_are_both_required(app):
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, root, _ = seed_bank()
        state = svc.get_bank(LOCAL_USER, ds.id)
        export = state['exports'][0]
        with pytest.raises(svc.BankError, match='manifest changed'):
            svc.open_export_image(LOCAL_USER, ds.id, export['revision'], 'evaluation/one.png', '0' * 64)
        manifest = json.loads((root / 'manifest.json').read_text())
        manifest['entries'][1]['image_sha256'] = 'f' * 64
        (root / 'manifest.json').write_text(json.dumps(manifest))
        export = svc.get_bank(LOCAL_USER, ds.id)['exports'][0]
        with pytest.raises(svc.BankError, match='verified export file'):
            svc.open_export_image(LOCAL_USER, ds.id, export['revision'], 'evaluation/one.png', export['manifest_sha256'])


@pytest.mark.parametrize('relative', ['C:secret', 'C:/secret', 'dir/file:stream', 'file\x00.png', 'dir/line\n.png'])
def test_portable_drive_and_control_paths_rejected(tmp_path, relative):
    from app.services import pilot_bank_storage as store
    with pytest.raises(store.BankError, match='Unsafe'):
        store.contained(tmp_path, relative)


def test_media_tool_output_cap_and_timeout_are_sanitized():
    import sys
    from app.services import pilot_bank_media as media
    from app.services.pilot_bank_storage import BankError
    assert media.run_local([sys.executable, '-c', 'print("bounded")']).strip() == b'bounded'
    with pytest.raises(BankError, match='validation failed'):
        media.run_local([sys.executable, '-c', 'import sys; sys.stderr.write("x"*200000)'])
    with pytest.raises(BankError, match='timed out'):
        media.run_local([sys.executable, '-c', 'import time; time.sleep(5)'], timeout=0.05)
    with pytest.raises(BankError, match='validation failed') as error:
        media.run_local([sys.executable, '-c', 'import sys; sys.stderr.write("secret-local-path"); sys.exit(2)'])
    assert 'secret-local-path' not in str(error.value)


def test_asset_evidence_transition_without_reupload_pins_prior_attempt(app):
    import copy
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_storage as store
    with app.app_context():
        ds, _, _ = seed_bank()
        state, aid, output = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), b'weights',
                                           {'kind': 'weights', 'asset_kind': 'lora', 'original_name': 'person.safetensors'})
        root = store.root_for(LOCAL_USER, ds.id)
        count = len(list((root / 'files').iterdir()))
        state = svc.update_file_metadata(LOCAL_USER, ds.id, aid, output['id'], {
            'version': state['version'], 'compatibility': {'status': 'declared', 'provider': 'manual', 'endpoint': 'image-endpoint'},
            'rights': {'licence': 'Reviewed'}, 'storage_evidence': {'visibility': 'Private'},
            'backup_evidence': {'notes': 'Retained privately'}})
        assert len(list((root / 'files').iterdir())) == count
        assert state['attempts'][0]['outputs'][0]['sha256'] == output['sha256']
        payload = attempt(state, asset_inputs=[{'attempt_id': aid, 'file_id': output['id'], 'sha256': output['sha256'], 'strength': 0.8}])
        payload['recipe']['capabilities'] = {'asset_kinds': ['lora'], 'asset_input_kinds': ['weights'],
                                            'accepted_asset_model_ids': ['image-model']}
        state = svc.create_attempt(LOCAL_USER, ds.id, payload)
        pinned = copy.deepcopy(state['attempts'][-1])
        state = svc.update_file_metadata(LOCAL_USER, ds.id, aid, output['id'], {
            'version': state['version'], 'compatibility': {'status': 'unproven'}})
        assert state['attempts'][-1] == pinned
        assert pinned['asset_inputs'][0]['compatibility']['status'] == 'declared'
        with pytest.raises(svc.BankError, match='immutable'):
            svc.update_file_metadata(LOCAL_USER, ds.id, aid, output['id'], {'version': state['version'], 'base_family': 'changed'})
        archive = io.BytesIO()
        svc.download(LOCAL_USER, ds.id, archive)
        with zipfile.ZipFile(archive) as z:
            history = [n for n in z.namelist() if n.startswith('records/')]
            assert len(history) == state['version']
            assert any(json.loads(z.read(n))['attempts'][0]['outputs'][0]['compatibility']['status'] == 'declared'
                       for n in history if json.loads(z.read(n))['attempts'][0]['outputs'])


def test_gallery_does_not_hash_unrelated_training_zip(app, monkeypatch):
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_storage as store
    with app.app_context():
        ds, root, data = seed_bank()
        (root / 'training.zip').write_bytes(b'not-needed-for-photo-review')
        manifest = json.loads((root / 'manifest.json').read_text())
        manifest['files']['training.zip'] = '0' * 64  # changed unrelated package does not hide held-out review photo
        (root / 'manifest.json').write_text(json.dumps(manifest))
        export = svc.get_bank(LOCAL_USER, ds.id)['exports'][0]
        monkeypatch.setattr(store, 'hash_file', lambda *args: pytest.fail('Gallery must not hash unrelated export files'))
        with svc.open_export_image(LOCAL_USER, ds.id, export['revision'], 'evaluation/one.png', export['manifest_sha256']) as stream:
            assert stream.read() == data
        (root / 'evaluation/one.png').write_bytes(b'changed')
        with pytest.raises(svc.BankError, match='integrity check'):
            svc.open_export_image(LOCAL_USER, ds.id, export['revision'], 'evaluation/one.png', export['manifest_sha256'])


def test_archive_history_stops_at_captured_bank_version(app, monkeypatch):
    import copy
    from pathlib import Path
    from app.services import pilot_bank as svc
    from app.services import pilot_bank_storage as store
    with app.app_context():
        ds, _, data = seed_bank()
        state, _, _ = prepare_output(svc, ds, svc.get_bank(LOCAL_USER, ds.id), data)
        root = store.root_for(LOCAL_USER, ds.id)
        records = root / 'records'
        original_iter = Path.iterdir
        seen = 0

        def concurrent_publication(path):
            nonlocal seen
            if path == records:
                seen += 1
                if seen == 2:  # after download captured bank.json, before it copies history
                    next_state = copy.deepcopy(state)
                    next_state['attempts'][0]['outputs'].append({'id': 'f' * 32, 'sha256': 'f' * 64})
                    store.publish(root, next_state, state['version'])
            return original_iter(path)

        monkeypatch.setattr(Path, 'iterdir', concurrent_publication)
        archive = io.BytesIO()
        svc.download(LOCAL_USER, ds.id, archive)
        with zipfile.ZipFile(archive) as z:
            history = [n for n in z.namelist() if n.startswith('records/')]
            assert len(history) == state['version']
            assert f'records/{state["version"] + 1:010d}.json' not in history
            assert json.loads(z.read('bank.json'))['version'] == state['version']


def test_multipart_png_checksum_failure_is_sanitized_and_valid_image_still_imports(client, app):
    import base64
    from app.services import pilot_bank as svc
    with app.app_context():
        ds, _, valid_png = seed_bank()
        state = svc.create_attempt(LOCAL_USER, ds.id, attempt(svc.get_bank(LOCAL_USER, ds.id)))
    aid = state['attempts'][0]['id']
    url = f'/api/dataset/{ds.id}/pilot-bank/attempts/{aid}/files'
    metadata = {'kind': 'image', 'asset_kind': None, 'model_id': 'image-model',
                'base_family': 'image-base', 'compatibility': {'status': 'unproven',
                 'provider': 'manual', 'endpoint': 'image-endpoint'}, 'notes': '',
                'checkpoint': '', 'trigger': '', 'configuration_file_id': None,
                'rights': {}, 'storage_evidence': {}, 'backup_evidence': {}}
    # Recognized PNG with corrupt IDAT CRC: Pillow verify raises SyntaxError.
    corrupt_png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
    response = client.post(url, data={'version': str(state['version']), 'metadata': json.dumps(metadata),
                                     'file': (io.BytesIO(corrupt_png), 'synthetic_output.png')})
    assert response.status_code == 400
    assert response.json['error'] == 'Invalid or oversized image'
    assert response.json['error_detail']['message'] == 'Invalid or oversized image'
    assert 'IDAT' not in response.json['error']
    reloaded = client.get(f'/api/dataset/{ds.id}/pilot-bank').json
    assert reloaded['version'] == state['version']
    assert reloaded['attempts'][0]['outputs'] == []
    response = client.post(url, data={'version': str(state['version']), 'metadata': json.dumps(metadata),
                                     'file': (io.BytesIO(valid_png), 'synthetic_output.png')})
    assert response.status_code == 200
    output = response.json['attempts'][0]['outputs'][0]
    assert client.get(output['url']).data == valid_png
