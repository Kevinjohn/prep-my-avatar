import copy
import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.config import LOCAL_USER


def seed(subject='First subject'):
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as fds
    ds = fds.create_dataset(LOCAL_USER, subject, 'person_token')
    root = fds._dataset_dir(ds.id)
    rows = []
    for index in range(3):
        name = f'photo_{index}.png'
        image = Image.new('RGB', (120, 80), (index * 70, 30, 40))
        image.save(f'{root}/{name}')
        row = FaceDatasetImage(dataset_id=ds.id, filename=name, source='import',
                               status='keep', caption=f'wearing shirt {index}')
        fds.db.session.add(row)
        rows.append(row)
    fds.db.session.commit()
    return ds, rows


def request_for(ds, rows, recipe_id='fal-krea-reviewed', recipe_version=1):
    from app.services import hosted_export as svc
    payload = {'dataset_revision': ds.revision, 'recipe_id': recipe_id,
               'recipe_version': recipe_version, 'parameters': {},
               'subject': {'name': ds.name, 'trigger_word': ds.trigger_word,
                           'consent': True, 'rights_basis': 'owned',
                           'publication_scope': 'private'},
               'excluded_image_ids': [], 'selections': []}
    for row, role in zip(rows, ['training', 'reference', 'evaluation']):
        selection = {'image_id': row.id, 'role': role,
                     'reference_role': 'identity' if role == 'reference' else ''}
        preview = svc.preview(LOCAL_USER, ds.id, {
            **payload, **selection, 'trigger_word': ds.trigger_word})
        selection['approved_pair_sha256'] = preview['pair_sha256']
        selection['approved_image_sha256'] = preview['image_sha256']
        selection['approved_caption_sha256'] = preview['caption_sha256']
        payload['selections'].append(selection)
    return payload


def test_offline_package_emits_only_exact_approved_pairs(app, tmp_path):
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        payload = request_for(ds, rows)
        root = tmp_path / 'completed'
        manifest = svc.capture(LOCAL_USER, ds.id, payload, root)
        with zipfile.ZipFile(root / 'krea_training.zip') as archive:
            assert len(archive.namelist()) == 2
            assert all('/' not in name for name in archive.namelist())
            entry = manifest['entries'][0]
            assert hashlib.sha256(archive.read(entry['image_path'])).hexdigest() == entry['image_sha256']
            assert hashlib.sha256(archive.read(entry['caption_path'])).hexdigest() == entry['caption_sha256']
            with Image.open(io.BytesIO(archive.read(entry['image_path']))) as image:
                assert image.size == (1024, 1024)
                assert not image.info
        assert (root / 'references' / '00001_2.png').exists()
        assert len(list((root / 'evaluation').glob('*.png'))) == 1
        assert manifest['subject']['name'] == 'First subject'
        assert manifest['recipe']['parameters']['auto_captioning'] == 'Off'
        assert rows[0].caption == 'wearing shirt 0'
        assert (root / 'README.md').exists()
        with pytest.raises(FileExistsError):
            svc.capture(LOCAL_USER, ds.id, payload, root)


def test_crop_or_caption_change_invalidates_approval(app, tmp_path):
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        payload = request_for(ds, rows)
        payload['selections'][0]['caption_override'] = 'changed caption'
        with pytest.raises(ValueError, match='approval'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'invalid')
        assert not (tmp_path / 'invalid').exists()


def test_evaluation_sibling_and_burst_leakage_rejected(app, tmp_path):
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        rows[2].parent_image_id = rows[0].id
        fds.db.session.commit()
        payload = request_for(ds, rows)
        with pytest.raises(ValueError, match='lineage'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'siblings')
        rows[2].parent_image_id = None
        fds.db.session.commit()
        payload = request_for(ds, rows)
        payload['selections'][1]['burst_group'] = 'capture-one'
        payload['selections'][2]['burst_group'] = 'capture-one'
        with pytest.raises(ValueError, match='lineage|burst'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'burst')


def test_second_subject_recipe_layout_and_historical_defaults(app, tmp_path, monkeypatch):
    from app.services import hosted_export as svc
    from app.services import hosted_export_recipes as recipes
    with app.app_context():
        fixture = copy.deepcopy(recipes.get_recipe('fal-krea-reviewed', 1))
        fixture.update(id='fixture-landscape', name='Fixture landscape',
                       crop_rule='preserve', formatter='paired-folder', archive_name='fixture.zip',
                       service={'id': 'fixture-service', 'protocol': 'manual-offline',
                                'supported_base_families': ['fixture-base'],
                                'supported_asset_kinds': ['lora']}, base_family='fixture-base',
                       model_id='fixture-model', endpoint='fixture-service/person-training')
        monkeypatch.setitem(recipes.DEFINITIONS, ('fixture-landscape', 1), fixture)
        ds, rows = seed('Second subject')
        payload = request_for(ds, rows, 'fixture-landscape')
        root = tmp_path / 'fixture'
        manifest = svc.capture(LOCAL_USER, ds.id, payload, root)
        before = (root / 'recipe.json').read_bytes()
        with zipfile.ZipFile(root / 'fixture.zip') as archive:
            assert all(name.startswith('images/') for name in archive.namelist())
            with Image.open(io.BytesIO(archive.read(manifest['entries'][0]['image_path']))) as image:
                assert image.size == (120, 80)
        fixture['defaults']['steps'] = 200
        assert (root / 'recipe.json').read_bytes() == before
        assert recipes.get_recipe('fal-krea-reviewed', 1)['defaults']['steps'] == 1000


@pytest.mark.parametrize('change', ['crop', 'source'])
def test_pair_approval_binds_transform_and_source_even_with_identical_pixels(app, tmp_path, change):
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        payload = request_for(ds, rows)
        if change == 'crop':
            # Same uniform pixels and square output, different source region.
            payload['selections'][0]['crop'] = [0, 0, 2/3, 1]
        else:
            from PIL.PngImagePlugin import PngInfo
            info = PngInfo()
            info.add_text('private', 'metadata changed')
            Image.new('RGB', (120, 80), (0, 30, 40)).save(fds._img_path(rows[0]), pnginfo=info)
        with pytest.raises(ValueError, match='approval'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'changed')
        assert not (tmp_path / 'changed').exists()


@pytest.mark.parametrize('change', ['reference-caption', 'evaluation-status', 'bridge', 'file', 'original', 'definition', 'interrupt'])
def test_interrupted_or_concurrent_changes_never_publish(app, tmp_path, monkeypatch, change):
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    from app.services import hosted_export_recipes as recipes
    with app.app_context():
        ds, rows = seed()
        original_path = fds._img_path(rows[2]) + '.original.png'
        Image.new('RGB', (120, 80), (140, 30, 40)).save(original_path)
        rows[2].original_filename = original_path.split('/')[-1]
        bridge = FaceDatasetImage(dataset_id=ds.id, status='reject', source='import')
        fds.db.session.add(bridge)
        fds.db.session.commit()
        payload = request_for(ds, rows)
        original = svc._derivative
        calls = 0

        def materialize_and_change(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 3:
                if change == 'interrupt':
                    raise KeyboardInterrupt()
                if change == 'reference-caption':
                    rows[1].caption = 'concurrent change'
                    fds.db.session.commit()
                elif change == 'evaluation-status':
                    rows[2].status = 'reject'
                    fds.db.session.commit()
                elif change == 'bridge':
                    bridge.parent_image_id = rows[0].id
                    bridge.duplicate_of_id = rows[2].id
                    fds.db.session.commit()
                elif change == 'file':
                    Image.new('RGB', (120, 80), 'blue').save(fds._img_path(rows[0]))
                elif change == 'original':
                    Image.new('RGB', (120, 80), 'blue').save(original_path)
                elif change == 'definition':
                    changed = copy.deepcopy(recipes.DEFINITIONS[('fal-krea-reviewed', 1)])
                    changed['defaults']['steps'] = 200
                    monkeypatch.setitem(recipes.DEFINITIONS, ('fal-krea-reviewed', 1), changed)
            return result

        monkeypatch.setattr(svc, '_derivative', materialize_and_change)
        destination = tmp_path / 'revision'
        with pytest.raises((RuntimeError, KeyboardInterrupt), match=None if change == 'interrupt' else 'changed'):
            svc.capture(LOCAL_USER, ds.id, payload, destination)
        assert not destination.exists()
        assert not list(tmp_path.glob('revision.tmp-*'))


def test_unselected_lineage_bridge_rejects_evaluation_leakage(app, tmp_path):
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        fds.db.session.add(FaceDatasetImage(dataset_id=ds.id, status='reject', source='import',
                                           parent_image_id=rows[0].id, duplicate_of_id=rows[2].id))
        fds.db.session.commit()
        payload = request_for(ds, rows)
        with pytest.raises(ValueError, match='lineage'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'bridge')


@pytest.mark.parametrize('field,value,role', [('status', 'pending', 'training'),
                                              ('anchor_decision', 'excluded', 'reference'),
                                              ('source', 'generated', 'evaluation')])
def test_existing_admission_and_role_exclusions_preserved(app, field, value, role):
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        setattr(rows[0], field, value)
        fds.db.session.commit()
        with pytest.raises(ValueError):
            svc.preview(LOCAL_USER, ds.id, {'recipe_id': 'fal-krea-reviewed', 'recipe_version': 1,
                                          'image_id': rows[0].id, 'role': role})
        if field == 'anchor_decision':
            assert svc.preview(LOCAL_USER, ds.id, {'recipe_id': 'fal-krea-reviewed', 'recipe_version': 1,
                                                  'image_id': rows[0].id, 'role': 'training'})


def test_recipe_incompatibility_and_unknown_expired_offers_cannot_execute(app, tmp_path, monkeypatch):
    from app.services import hosted_export as svc
    from app.services import hosted_export_recipes as recipes
    with app.app_context():
        ds, rows = seed()
        definition = recipes.get_recipe('fal-krea-reviewed', 1)
        definition['service']['supported_base_families'] = ['other-family']
        monkeypatch.setitem(recipes.DEFINITIONS, ('bad-target', 1), {**definition, 'id': 'bad-target'})
        with pytest.raises(ValueError, match='incompatible'):
            recipes.get_recipe('bad-target', 1)
        definition = recipes.get_recipe('fal-krea-reviewed', 1)
        definition['asset_kind'] = 'refmod'
        monkeypatch.setitem(recipes.DEFINITIONS, ('bad-asset', 1), {**definition, 'id': 'bad-asset'})
        with pytest.raises(ValueError, match='incompatible'):
            recipes.get_recipe('bad-asset', 1)
        definition = recipes.get_recipe('fal-krea-reviewed', 1)
        definition['availability'] = {'status': 'unknown', 'offers': [
            {'expires_at': '2000-01-01', 'status': 'expired', 'credit': 100}]}
        monkeypatch.setitem(recipes.DEFINITIONS, ('fal-krea-reviewed', 1), definition)
        # Export records the unverified/expired evidence, never interprets it as
        # consent to execute or falls back to another service.
        import requests
        monkeypatch.setattr(requests.sessions.Session, 'request',
                            lambda *a, **k: pytest.fail('offline export made a network call'))
        manifest = svc.capture(LOCAL_USER, ds.id, request_for(ds, rows), tmp_path / 'offline')
        assert manifest['recipe']['definition']['availability'] == definition['availability']
        assert 'execution' not in manifest


def test_routes_source_preview_and_download_contract(client, app, tmp_path):
    with app.app_context():
        ds, rows = seed()
        dataset_id = ds.id
        payload = request_for(ds, rows)
    base = f'/api/dataset/{dataset_id}/hosted-export'
    listed = client.get(base)
    assert listed.status_code == 200
    assert listed.json['images'][0]['width'] == 120
    source = client.get(listed.json['images'][0]['source_preview_url'])
    assert source.status_code == 200
    with Image.open(io.BytesIO(source.data)) as image:
        assert image.size == (120, 80)
        assert not image.info
    preview = client.post(base + '/preview', json={**payload, 'image_id': rows[0].id,
                          'trigger_word': 'person_token'})
    assert preview.status_code == 200
    assert preview.json['pair_sha256'] == payload['selections'][0]['approved_pair_sha256']
    download = client.post(base, json=payload)
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        names = archive.namelist()
        assert any(name.endswith('/krea_training.zip') for name in names)
        assert any(name.endswith('/manifest.json') for name in names)
    assert client.post(base, json={**payload, 'subject': {'consent': False}}).status_code == 400
    assert client.get('/api/dataset/987654/hosted-export').status_code == 404


@pytest.mark.parametrize('crop', [[0, 0, 1, 1], [-1, 0, 1, 1], [0, 0, float('nan'), 1], 'square'])
def test_invalid_training_crops_are_rejected(app, crop):
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        with pytest.raises(ValueError, match='crop'):
            svc.preview(LOCAL_USER, ds.id, {'recipe_id': 'fal-krea-reviewed', 'recipe_version': 1,
                                           'image_id': rows[0].id, 'crop': crop})


def test_recipe_minimum_is_enforced_separately_from_guidance(app, tmp_path, monkeypatch):
    from app.services import hosted_export as svc
    from app.services import hosted_export_recipes as recipes
    with app.app_context():
        ds, rows = seed()
        definition = recipes.get_recipe('fal-krea-reviewed', 1)
        definition['input_requirements']['minimum_training_images'] = 2
        monkeypatch.setitem(recipes.DEFINITIONS, ('fal-krea-reviewed', 1), definition)
        payload = request_for(ds, rows)
        with pytest.raises(ValueError, match='at least 2'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'too-few')


def test_lineage_original_change_between_selection_and_copy_is_rejected(app, tmp_path, monkeypatch):
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        path = fds._img_path(rows[0]) + '.bridge.png'
        Image.new('RGB', (120, 80), 'red').save(path)
        fds.db.session.add(FaceDatasetImage(dataset_id=ds.id, status='reject', source='import',
                                           original_filename=path.split('/')[-1]))
        fds.db.session.commit()
        payload = request_for(ds, rows)
        original = svc._families

        def lineage_then_edit(*args, **kwargs):
            result = original(*args, **kwargs)
            Image.new('RGB', (120, 80), 'blue').save(path)
            return result

        monkeypatch.setattr(svc, '_families', lineage_then_edit)
        with pytest.raises(RuntimeError, match='changed'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'gap')
        assert not (tmp_path / 'gap').exists()


def test_metadata_is_removed_from_exact_preview_and_completed_derivative(app, tmp_path):
    from PIL.PngImagePlugin import PngInfo
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        metadata = PngInfo()
        metadata.add_text('Location', 'Private address')
        exif = Image.Exif()
        exif[0x010E] = 'Private photograph description'
        Image.new('RGB', (120, 80), (0, 30, 40)).save(
            fds._img_path(rows[0]), pnginfo=metadata, exif=exif, icc_profile=b'private profile')
        payload = request_for(ds, rows)
        root = tmp_path / 'clean'
        manifest = svc.capture(LOCAL_USER, ds.id, payload, root)
        with zipfile.ZipFile(root / 'krea_training.zip') as archive:
            with Image.open(io.BytesIO(archive.read(manifest['entries'][0]['image_path']))) as image:
                assert not image.info
                assert not image.getexif()
        with Image.open(fds._img_path(rows[0])) as original:
            assert original.info['Location'] == 'Private address'
            assert original.info['icc_profile'] == b'private profile'


def test_independent_request_edit_of_evaluation_aborts_atomic_publication(threaded_app, tmp_path, monkeypatch):
    import sqlite3
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with threaded_app.app_context():
        ds, rows = seed()
        payload = request_for(ds, rows)
        evaluation_id = rows[2].id
        database_path = fds.db.engine.url.database
        original = svc._derivative
        calls = 0

        def derivative_with_independent_edit(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 3:
                with sqlite3.connect(database_path) as connection:
                    connection.execute('UPDATE face_dataset_image SET caption = ? WHERE id = ?',
                                       ('Changed by separate request', evaluation_id))
            return result

        monkeypatch.setattr(svc, '_derivative', derivative_with_independent_edit)
        root = tmp_path / 'independent-edit'
        with pytest.raises(RuntimeError, match='dataset changed'):
            svc.capture(LOCAL_USER, ds.id, payload, root)
        assert not root.exists()
        assert not list(tmp_path.glob('independent-edit.tmp-*'))


@pytest.mark.parametrize('rights_flag', ['provider_excluded', 'consent_denied'])
def test_explicit_source_rights_exclusion_rejects_preview_and_export(app, tmp_path, rights_flag):
    import json
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        payload = request_for(ds, rows)
        rows[0].source_rights = json.dumps({'basis': 'owned', rights_flag: True})
        fds.db.session.commit()
        payload['dataset_revision'] = ds.revision
        with pytest.raises(ValueError, match='Source rights exclude hosted use'):
            svc.preview(LOCAL_USER, ds.id, {'recipe_id': 'fal-krea-reviewed', 'recipe_version': 1,
                                          'image_id': rows[0].id, 'role': 'training'})
        root = tmp_path / 'excluded-rights'
        with pytest.raises(ValueError, match='Source rights exclude hosted use'):
            svc.capture(LOCAL_USER, ds.id, payload, root)
        assert not root.exists()


def test_symlink_source_rejects_preview_and_export(app, tmp_path):
    from pathlib import Path
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        payload = request_for(ds, rows)
        source = Path(fds._img_path(rows[0]))
        replacement = tmp_path / 'external-source.png'
        Image.new('RGB', (120, 80), (0, 30, 40)).save(replacement)
        source.unlink()
        source.symlink_to(replacement)
        with pytest.raises(ValueError, match='unsafe'):
            svc.preview(LOCAL_USER, ds.id, {'recipe_id': 'fal-krea-reviewed', 'recipe_version': 1,
                                          'image_id': rows[0].id, 'role': 'training'})
        root = tmp_path / 'symlink-export'
        with pytest.raises(ValueError, match='unsafe'):
            svc.capture(LOCAL_USER, ds.id, payload, root)
        assert not root.exists()
        assert not list(tmp_path.glob('symlink-export.tmp-*'))


@pytest.mark.parametrize('supported_tasks', [[], ['reference-generation']])
def test_recipe_rejects_unsupported_process_capability(monkeypatch, supported_tasks):
    from app.services import hosted_export_recipes as recipes
    definition = recipes.get_recipe('fal-krea-reviewed', 1)
    definition['supported_tasks'] = supported_tasks
    monkeypatch.setitem(recipes.DEFINITIONS, ('fal-krea-reviewed', 1), definition)
    with pytest.raises(ValueError, match='task|purpose|capability'):
        recipes.get_recipe('fal-krea-reviewed', 1)


@pytest.mark.parametrize('model_id', ['', '   '])
def test_recipe_rejects_blank_model_identity(monkeypatch, model_id):
    from app.services import hosted_export_recipes as recipes
    definition = recipes.get_recipe('fal-krea-reviewed', 1)
    definition['model_id'] = model_id
    monkeypatch.setitem(recipes.DEFINITIONS, ('fal-krea-reviewed', 1), definition)
    with pytest.raises(ValueError, match='invalid versioned export recipe'):
        recipes.get_recipe('fal-krea-reviewed', 1)


def test_trusted_data_root_alias_allows_export_but_rejects_internal_symlinks_and_traversal(
        app, tmp_path, monkeypatch):
    from pathlib import Path
    from app.services import face_dataset_service as fds
    from app.services import hosted_export as svc
    actual_root = tmp_path / 'actual-data'
    actual_root.mkdir()
    alias = tmp_path / 'trusted-data-alias'
    alias.symlink_to(actual_root, target_is_directory=True)
    monkeypatch.setattr(fds.cfg, 'dataset_images_root', lambda: alias)
    with app.app_context():
        ds, rows = seed()
        payload = request_for(ds, rows)
        completed = tmp_path / 'alias-export'
        svc.capture(LOCAL_USER, ds.id, payload, completed)
        assert (completed / 'manifest.json').is_file()
        source = Path(fds._img_path(rows[0]))
        internal_target = source.with_name('internal-target.png')
        source.rename(internal_target)
        source.symlink_to(internal_target)
        with pytest.raises(ValueError, match='unsafe symlink'):
            svc.preview(LOCAL_USER, ds.id, {'recipe_id': 'fal-krea-reviewed', 'recipe_version': 1,
                                          'image_id': rows[0].id})
        source.unlink()
        internal_target.rename(source)
        outside = alias / 'outside-dataset.png'
        Image.new('RGB', (120, 80), (0, 30, 40)).save(outside)
        rows[0].filename = '../outside-dataset.png'
        fds.db.session.commit()
        with pytest.raises(ValueError, match='unsafe path'):
            svc.preview(LOCAL_USER, ds.id, {'recipe_id': 'fal-krea-reviewed', 'recipe_version': 1,
                                          'image_id': rows[0].id})


def reference_request(ds, rows, include_evaluation=True):
    from app.services import hosted_export as svc
    payload = {'dataset_revision': ds.revision, 'recipe_id': 'reviewed-reference',
               'recipe_version': 1, 'parameters': {},
               'subject': {'name': ds.name, 'trigger_word': ds.trigger_word,
                           'consent': True, 'rights_basis': 'owned',
                           'publication_scope': 'private'}, 'selections': []}
    selected = [(rows[0], 'reference')]
    if include_evaluation:
        selected.append((rows[2], 'evaluation'))
    for row, role in selected:
        selection = {'image_id': row.id, 'role': role, 'reference_role': 'identity'}
        preview = svc.preview(LOCAL_USER, ds.id, {**payload, **selection})
        selection.update({f'approved_{name}': preview[name] for name in
                          ('image_sha256', 'caption_sha256', 'pair_sha256')})
        payload['selections'].append(selection)
    return payload


@pytest.mark.parametrize('include_evaluation', [False, True])
def test_reference_only_pack_preserves_sources_and_aspect_without_training_zip(
        app, tmp_path, include_evaluation):
    from app.services import hosted_export as svc
    from app.services import face_dataset_service as fds
    with app.app_context():
        ds, rows = seed()
        before = {row.id: (Path(fds._img_path(row)).read_bytes(), row.caption) for row in rows}
        payload = reference_request(ds, rows, include_evaluation)
        root = tmp_path / 'reference-pack'
        manifest = svc.capture(LOCAL_USER, ds.id, payload, root)
        assert not list(root.glob('*.zip'))
        assert not any(entry['role'] == 'training' for entry in manifest['entries'])
        entry = manifest['entries'][0]
        with Image.open(root / entry['image_path']) as image:
            assert image.size == (120, 80)
        assert manifest['recipe']['definition']['supported_roles'] == ['reference', 'evaluation']
        assert manifest['recipe']['definition']['model_id'] is None
        assert len(list((root / 'evaluation').glob('*.png'))) == int(include_evaluation)
        assert 'no training archive' in (root / 'README.md').read_text().lower()
        for row in rows:
            assert (Path(fds._img_path(row)).read_bytes(), row.caption) == before[row.id]


def test_reference_recipe_rejects_training_and_requires_reference(app, tmp_path):
    from app.services import hosted_export as svc
    with app.app_context():
        ds, rows = seed()
        payload = reference_request(ds, rows)
        with pytest.raises(ValueError, match='role'):
            svc.preview(LOCAL_USER, ds.id, {**payload, 'image_id': rows[0].id, 'role': 'training'})
        changed = copy.deepcopy(payload)
        changed['selections'][0]['role'] = 'training'
        with pytest.raises(ValueError, match='role'):
            svc.capture(LOCAL_USER, ds.id, changed, tmp_path / 'training')
        payload['selections'] = payload['selections'][1:]
        with pytest.raises(ValueError, match='at least 1 reference'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'empty')


@pytest.mark.parametrize('overlap', ['lineage', 'burst'])
def test_reference_only_pack_rejects_held_out_overlap(app, tmp_path, overlap):
    from app.services import hosted_export as svc
    from app.services import face_dataset_service as fds
    with app.app_context():
        ds, rows = seed()
        payload = reference_request(ds, rows)
        if overlap == 'lineage':
            rows[2].parent_image_id = rows[0].id
            fds.db.session.commit()
            payload['dataset_revision'] = ds.revision
        else:
            for selection in payload['selections']:
                selection['burst_group'] = 'same-session'
        with pytest.raises(ValueError, match='lineage|burst'):
            svc.capture(LOCAL_USER, ds.id, payload, tmp_path / 'overlap')


def test_krea_still_requires_training_and_pinned_reference_recipe_is_historical(app, tmp_path, monkeypatch):
    from app.services import hosted_export as svc
    from app.services import hosted_export_recipes as recipes
    with app.app_context():
        ds, rows = seed()
        krea = request_for(ds, rows)
        krea['selections'] = krea['selections'][1:]
        with pytest.raises(ValueError, match='at least 1 training'):
            svc.capture(LOCAL_USER, ds.id, krea, tmp_path / 'krea')
        root = tmp_path / 'reference'
        svc.capture(LOCAL_USER, ds.id, reference_request(ds, rows), root)
        before = (root / 'recipe.json').read_bytes()
        changed = recipes.get_recipe('reviewed-reference', 1)
        changed['count_guidance']['reference'] = 99
        monkeypatch.setitem(recipes.DEFINITIONS, ('reviewed-reference', 1), changed)
        assert (root / 'recipe.json').read_bytes() == before


@pytest.mark.parametrize('change', ['caption', 'source'])
def test_reference_only_exact_approval_binds_caption_and_source(app, tmp_path, change):
    from PIL.PngImagePlugin import PngInfo
    from app.services import hosted_export as svc
    from app.services import face_dataset_service as fds
    with app.app_context():
        ds, rows = seed()
        payload = reference_request(ds, rows)
        if change == 'caption':
            payload['selections'][0]['caption_override'] = 'different caption'
        else:
            metadata = PngInfo()
            metadata.add_text('changed', 'same pixels, different source bytes')
            Image.new('RGB', (120, 80), (0, 30, 40)).save(fds._img_path(rows[0]), pnginfo=metadata)
        root = tmp_path / 'stale-reference'
        with pytest.raises(ValueError, match='approval'):
            svc.capture(LOCAL_USER, ds.id, payload, root)
        assert not root.exists()


def test_sources_list_exposes_both_maintained_recipes(app):
    from app.services import hosted_export as svc
    with app.app_context():
        ds, _ = seed()
        definitions = {item['id']: item for item in svc.list_sources(LOCAL_USER, ds.id)['recipes']}
        assert {'fal-krea-reviewed', 'reviewed-reference'} <= set(definitions)
        assert definitions['fal-krea-reviewed']['input_requirements']['minimum_training_images'] == 1
        assert definitions['reviewed-reference']['input_requirements']['minimum_images_by_role']['reference'] == 1
