import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image


def _png(color=(25, 50, 75)):
    buf = io.BytesIO()
    Image.new('RGB', (96, 64), color).save(buf, 'PNG')
    return buf.getvalue()


def _source(svc, image_cls, user_id, *, filename='source.png', derivation_kind=None):
    ds = svc.create_dataset(user_id, 'Improve', 'improve')
    os.makedirs(svc._dataset_dir(ds.id), exist_ok=True)
    raw = _png()
    if filename:
        with open(os.path.join(svc._dataset_dir(ds.id), filename), 'wb') as fh:
            fh.write(raw)
    image = image_cls(
        dataset_id=ds.id,
        filename=filename,
        source='import',
        status='keep',
        framing='body',
        caption='full body, outdoor light',
        variation_label='Imported low-resolution image',
        variation_prompt='original prompt',
        derivation_kind=derivation_kind,
    )
    svc.db.session.add(image)
    svc.db.session.commit()
    return ds, image, raw


@pytest.mark.parametrize('configured_prompt', [
    '',
    'Restore natural detail while preserving the person and composition.',
])
def test_improve_existing_image_is_non_destructive_and_uses_metadata_profile(
        app, monkeypatch, configured_prompt):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc
    from app.services import klein_edit_helper as keh

    queued = []
    syncs = []
    monkeypatch.setattr(keh, 'klein_missing_assets', lambda: [])
    monkeypatch.setattr(keh, 'klein_missing_nodes', lambda: [])
    monkeypatch.setattr(
        keh, 'enqueue_klein_edit',
        lambda **kwargs: (queued.append(kwargs) or 'improve-job-1'))
    monkeypatch.setattr(
        svc.cfg, 'get',
        lambda key, default=None: configured_prompt
        if key == 'klein.small_image_prompt' else default)
    monkeypatch.setattr(svc, '_sync_generate_activity', syncs.append)

    with app.app_context():
        ds, source, raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        original_raw = _png((90, 80, 70))
        source.original_filename = 'originals/source-original.png'
        os.makedirs(os.path.join(svc._dataset_dir(ds.id), 'originals'), exist_ok=True)
        with open(os.path.join(svc._dataset_dir(ds.id), source.original_filename), 'wb') as fh:
            fh.write(original_raw)
        svc.db.session.commit()
        source_id = source.id
        original_values = {
            field: getattr(source, field)
            for field in ('filename', 'source', 'framing', 'caption',
                          'variation_label', 'variation_prompt', 'derivation_kind',
                          'job_id', 'parent_image_id')
        }

        result = svc.improve_existing_image(LOCAL_USER, source_id)

        svc.db.session.expire_all()
        source = svc.db.session.get(FaceDatasetImage, source_id)
        candidate = svc.db.session.get(FaceDatasetImage, result['candidate_id'])
        assert {field: getattr(source, field) for field in original_values} == original_values
        assert source.status == 'pending'  # suspended until the exclusive review resolves
        with open(svc._img_path(source), 'rb') as fh:
            assert fh.read() == raw
        assert result == {'candidate_id': candidate.id, 'job_id': 'improve-job-1'}
        assert candidate.dataset_id == ds.id
        assert candidate.source == 'generated'
        assert candidate.status == 'pending'
        assert candidate.filename is None
        assert candidate.parent_image_id == source_id
        assert candidate.derivation_kind == svc.KLEIN_IMAGE_IMPROVE
        assert candidate.derivation_kind not in svc._SMALL_IMAGE_DERIVATIONS
        assert candidate.framing == source.framing
        assert candidate.caption == source.caption
        assert candidate.variation_prompt == svc.KLEIN_IMAGE_IMPROVE_PROMPT
        assert candidate.variation_label.startswith('Klein reconstruction')
        assert candidate.job_id == 'improve-job-1'
        assert queued[0]['source_filename'] == 'source-original.png'
        assert queued[0]['source_path'] == os.path.join(
            svc._dataset_dir(ds.id), source.original_filename)
        with open(queued[0]['source_path'], 'rb') as fh:
            assert fh.read() == original_raw
        assert queued[0]['edit_prompt'] == svc.KLEIN_IMAGE_IMPROVE_PROMPT
        assert queued[0]['lora_strength'] is None
        assert queued[0]['sampler_steps'] == 4
        assert queued[0]['base_lora_strength'] == 0.0
        assert queued[0]['extra_metadata']['source_image_id'] == source_id
        assert queued[0]['extra_metadata']['derivation_kind'] == svc.KLEIN_IMAGE_IMPROVE
        assert syncs == [ds.id]


def test_improve_existing_image_returns_active_candidate_idempotently(app, monkeypatch):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc
    from app.services import klein_edit_helper as keh

    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        active = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='pending',
            parent_image_id=source.id, derivation_kind=svc.KLEIN_IMAGE_IMPROVE,
            variation_label='Klein reconstruction', job_id='already-running')
        svc.db.session.add(active)
        svc.db.session.commit()
        active_id = active.id

        monkeypatch.setattr(
            keh, 'klein_missing_assets',
            lambda: (_ for _ in ()).throw(AssertionError('idempotent path must not preflight')))
        monkeypatch.setattr(
            keh, 'klein_missing_nodes',
            lambda: (_ for _ in ()).throw(AssertionError('idempotent path must not preflight')))
        monkeypatch.setattr(
            keh, 'enqueue_klein_edit',
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError('must not enqueue twice')))

        first = svc.improve_existing_image(LOCAL_USER, source.id)
        second = svc.improve_existing_image(LOCAL_USER, source.id)
        assert first == second == {
            'candidate_id': active_id, 'job_id': 'already-running'}
        assert FaceDatasetImage.query.filter_by(
            parent_image_id=source.id,
            derivation_kind=svc.KLEIN_IMAGE_IMPROVE).count() == 1


def test_improve_existing_image_rejects_missing_and_review_sources(app, monkeypatch):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc
    from app.services import klein_edit_helper as keh

    monkeypatch.setattr(keh, 'klein_missing_assets', lambda: [])
    monkeypatch.setattr(keh, 'klein_missing_nodes', lambda: [])
    with app.app_context():
        assert svc.improve_existing_image(LOCAL_USER, 999999) is None

        _ds, missing_name, _ = _source(
            svc, FaceDatasetImage, LOCAL_USER, filename=None)
        with pytest.raises(ValueError, match='image file required'):
            svc.improve_existing_image(LOCAL_USER, missing_name.id)

        _ds, missing_file, _ = _source(svc, FaceDatasetImage, LOCAL_USER)
        os.remove(svc._img_path(missing_file))
        with pytest.raises(ValueError, match='image file missing'):
            svc.improve_existing_image(LOCAL_USER, missing_file.id)

        _ds, review_source, _ = _source(
            svc, FaceDatasetImage, LOCAL_USER,
            derivation_kind=svc.SMALL_IMAGE_SOURCE)
        with pytest.raises(ValueError, match='resolve the small-image rescue pair'):
            svc.improve_existing_image(LOCAL_USER, review_source.id)

        _ds, improve_candidate, _ = _source(
            svc, FaceDatasetImage, LOCAL_USER,
            derivation_kind=svc.KLEIN_IMAGE_IMPROVE)
        improve_candidate.source = 'generated'
        svc.db.session.commit()
        with pytest.raises(ValueError, match='cannot be reconstructed again'):
            svc.improve_existing_image(LOCAL_USER, improve_candidate.id)
        with pytest.raises(ValueError, match='cannot be regenerated'):
            svc.regenerate_image(LOCAL_USER, improve_candidate.id)


def test_improve_existing_image_preflights_models_and_fanout(app, monkeypatch):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc
    from app.services import klein_edit_helper as keh
    from app.services.klein_edit_helper import KleinModelsMissing

    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        monkeypatch.setattr(keh, 'klein_missing_assets', lambda: ['klein_model'])
        monkeypatch.setattr(keh, 'klein_missing_nodes', lambda: [])
        with pytest.raises(KleinModelsMissing):
            svc.improve_existing_image(LOCAL_USER, source.id)
        assert FaceDatasetImage.query.filter_by(
            derivation_kind=svc.KLEIN_IMAGE_IMPROVE).count() == 0

        monkeypatch.setattr(keh, 'klein_missing_assets', lambda: [])
        for _ in range(svc.MAX_FANOUT):
            svc.db.session.add(FaceDatasetImage(
                dataset_id=ds.id, source='generated', status='pending'))
        svc.db.session.commit()
        with pytest.raises(ValueError, match='too many generations in flight'):
            svc.improve_existing_image(LOCAL_USER, source.id)
        assert FaceDatasetImage.query.filter_by(
            derivation_kind=svc.KLEIN_IMAGE_IMPROVE).count() == 0


def test_improve_existing_image_removes_candidate_when_enqueue_fails(app, monkeypatch):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc
    from app.services import klein_edit_helper as keh

    monkeypatch.setattr(keh, 'klein_missing_assets', lambda: [])
    monkeypatch.setattr(keh, 'klein_missing_nodes', lambda: [])
    monkeypatch.setattr(
        keh, 'enqueue_klein_edit',
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('ComfyUI offline')))
    with app.app_context():
        _ds, source, raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        source_id = source.id
        with pytest.raises(RuntimeError, match='ComfyUI offline'):
            svc.improve_existing_image(LOCAL_USER, source_id)
        assert FaceDatasetImage.query.filter_by(
            derivation_kind=svc.KLEIN_IMAGE_IMPROVE).count() == 0
        source = svc.db.session.get(FaceDatasetImage, source_id)
        assert source.status == 'keep' and source.caption == 'full body, outdoor light'
        with open(svc._img_path(source), 'rb') as fh:
            assert fh.read() == raw


def test_concurrent_improve_requests_enqueue_only_once(app, monkeypatch):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc
    from app.services import klein_edit_helper as keh

    entered = threading.Event()
    release = threading.Event()
    calls = []

    def enqueue(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(3), 'test did not release the fake enqueue'
        return 'one-concurrent-job'

    monkeypatch.setattr(keh, 'klein_missing_assets', lambda: [])
    monkeypatch.setattr(keh, 'klein_missing_nodes', lambda: [])
    monkeypatch.setattr(keh, 'enqueue_klein_edit', enqueue)
    monkeypatch.setattr(svc, '_sync_generate_activity', lambda _dataset_id: None)
    with app.app_context():
        _ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        source_id = source.id

    def run():
        with app.app_context():
            return svc.improve_existing_image(LOCAL_USER, source_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        assert entered.wait(3), 'first request never reached enqueue'
        second = pool.submit(run)
        time.sleep(0.1)
        assert not second.done(), 'second request bypassed the per-image lock'
        release.set()
        first_result = first.result(timeout=3)
        second_result = second.result(timeout=3)

    assert first_result == second_result
    assert first_result['job_id'] == 'one-concurrent-job'
    assert len(calls) == 1
    with app.app_context():
        assert FaceDatasetImage.query.filter_by(
            parent_image_id=source_id,
            derivation_kind=svc.KLEIN_IMAGE_IMPROVE).count() == 1


def test_improve_route_accepts_empty_json_and_returns_contract(client, monkeypatch):
    from app.services import face_dataset_service as svc

    monkeypatch.setattr(
        svc, 'improve_existing_image',
        lambda user_id, image_id: {'candidate_id': 41, 'job_id': 'route-job'})
    response = client.post('/api/dataset/image/7/improve', json={})
    assert response.status_code == 200
    assert response.get_json() == {
        'ok': True, 'candidate_id': 41, 'job_id': 'route-job'}


def test_improve_route_maps_not_found_and_klein_missing(client, monkeypatch):
    from app.services import face_dataset_service as svc
    from app.services import klein_edit_helper as keh
    from app.services.klein_edit_helper import KleinModelsMissing

    monkeypatch.setattr(
        keh, 'klein_missing_nodes',
        lambda: (_ for _ in ()).throw(AssertionError('route must not preflight before ownership')))
    monkeypatch.setattr(svc, 'improve_existing_image', lambda *_args: None)
    assert client.post('/api/dataset/image/404/improve').status_code == 404

    monkeypatch.setattr(
        svc, 'improve_existing_image',
        lambda *_args: (_ for _ in ()).throw(KleinModelsMissing(['klein_model'])))
    response = client.post('/api/dataset/image/8/improve', json={})
    assert response.status_code == 409
    assert response.get_json()['ok'] is False


def test_improve_route_preflights_missing_nodes(client, monkeypatch):
    from app.services import face_dataset_service as svc

    missing = [{'class_type': 'ExampleNode', 'pack': None, 'url': None}]
    monkeypatch.setattr(
        svc, 'improve_existing_image',
        lambda *_args: (_ for _ in ()).throw(svc.KleinNodesMissing([], missing)))
    response = client.post('/api/dataset/image/8/improve', json={})
    assert response.status_code == 409
    assert response.get_json()['klein_nodes_missing'] == missing


@pytest.mark.parametrize(('choice', 'expected'), [
    ('original', ('keep', 'reject')),
    ('improved', ('reject', 'keep')),
    ('reject', ('reject', 'reject')),
])
def test_resolve_image_improvement_admits_exactly_one_version(app, choice, expected):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc

    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        candidate_name = 'reconstructed.png'
        with open(os.path.join(svc._dataset_dir(ds.id), candidate_name), 'wb') as fh:
            fh.write(_png((80, 90, 100)))
        candidate = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='pending', filename=candidate_name,
            parent_image_id=source.id, derivation_kind=svc.KLEIN_IMAGE_IMPROVE)
        svc.db.session.add(candidate)
        svc.db.session.commit()

        result = svc.resolve_image_improvement(
            LOCAL_USER, ds.id, candidate.id, choice)
        svc.db.session.refresh(source)
        svc.db.session.refresh(candidate)
        assert (source.status, candidate.status) == expected
        assert result['choice'] == choice
        # Network retries are idempotent, but the pair cannot later be flipped by
        # either the dedicated resolver or generic curation controls.
        assert svc.resolve_image_improvement(
            LOCAL_USER, ds.id, candidate.id, choice)['choice'] == choice
        other = 'original' if choice != 'original' else 'reject'
        with pytest.raises(RuntimeError, match='already resolved'):
            svc.resolve_image_improvement(LOCAL_USER, ds.id, candidate.id, other)
        with pytest.raises(ValueError, match='dedicated comparison'):
            svc.set_image_status(LOCAL_USER, source.id, 'pending')
        with pytest.raises(ValueError, match='cannot be deleted independently'):
            svc.delete_image(LOCAL_USER, candidate.id)


def test_resolve_image_improvement_requires_ready_candidate(app):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc

    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        candidate = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='pending',
            parent_image_id=source.id, derivation_kind=svc.KLEIN_IMAGE_IMPROVE,
            job_id='not-ready')
        svc.db.session.add(candidate)
        svc.db.session.commit()
        with pytest.raises(ValueError, match='not ready'):
            svc.resolve_image_improvement(
                LOCAL_USER, ds.id, candidate.id, 'improved')


def test_image_improvement_resolve_route(client, monkeypatch):
    from app.services import face_dataset_service as svc

    monkeypatch.setattr(svc, 'resolve_image_improvement', lambda *_args: {
        'choice': 'improved',
        'source': {'id': 2, 'status': 'reject'},
        'candidate': {'id': 8, 'status': 'keep'},
    })
    response = client.post(
        '/api/dataset/3/image-improvement/8/resolve', json={'choice': 'improved'})
    assert response.status_code == 200
    assert response.get_json()['choice'] == 'improved'


def test_backup_preserves_inflight_reconstruction_pair_as_reviewable_failure(app):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc

    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        source.status = 'pending'
        candidate = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='pending',
            parent_image_id=source.id, derivation_kind=svc.KLEIN_IMAGE_IMPROVE,
            job_id='machine-local-job')
        svc.db.session.add(candidate)
        svc.db.session.commit()
        restored = svc.import_backup_zip(
            LOCAL_USER, svc.build_backup_zip(LOCAL_USER, ds.id))
        rows = FaceDatasetImage.query.filter_by(dataset_id=restored.id).all()
        restored_candidate = next(
            row for row in rows if row.derivation_kind == svc.KLEIN_IMAGE_IMPROVE)
        restored_source = svc.db.session.get(
            FaceDatasetImage, restored_candidate.parent_image_id)
        assert restored_candidate.status == 'failed'
        assert restored_source and restored_source.status == 'pending'
        assert 'source is preserved' in restored_candidate.fail_reason
        result = svc.resolve_image_improvement(
            LOCAL_USER, restored.id, restored_candidate.id, 'original')
        assert result['source']['status'] == 'keep'


def test_legacy_siblings_normalize_then_resolve_as_one_group(app):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc

    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        source.status = 'reject'
        siblings = []
        for index in range(2):
            filename = f'legacy-{index}.png'
            with open(os.path.join(svc._dataset_dir(ds.id), filename), 'wb') as fh:
                fh.write(_png((40 + index, 50, 60)))
            sibling = FaceDatasetImage(
                dataset_id=ds.id, source='generated', status='keep', filename=filename,
                parent_image_id=source.id, derivation_kind=svc.KLEIN_IMAGE_IMPROVE)
            svc.db.session.add(sibling)
            siblings.append(sibling)
        svc.db.session.commit()

        assert svc.normalize_legacy_image_improvement_rows(ds.id) == 1
        svc.db.session.refresh(source)
        for sibling in siblings:
            svc.db.session.refresh(sibling)
        assert source.status == 'pending'
        assert [sibling.status for sibling in siblings] == ['reject', 'pending']

        svc.resolve_image_improvement(
            LOCAL_USER, ds.id, siblings[1].id, 'improved')
        svc.db.session.refresh(source)
        for sibling in siblings:
            svc.db.session.refresh(sibling)
        assert source.status == 'reject'
        assert [sibling.status for sibling in siblings] == ['reject', 'keep']


def test_orphaned_legacy_candidate_is_independently_cleanable(app):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc

    with app.app_context():
        ds = svc.create_dataset(LOCAL_USER, 'Orphan', 'orphan')
        filename = 'orphan.png'
        with open(os.path.join(svc._dataset_dir(ds.id), filename), 'wb') as fh:
            fh.write(_png())
        orphan = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='reject', filename=filename,
            parent_image_id=999999, derivation_kind=svc.KLEIN_IMAGE_IMPROVE)
        svc.db.session.add(orphan)
        svc.db.session.commit()
        orphan_id = orphan.id

        assert svc.set_image_status(LOCAL_USER, orphan_id, 'pending') is True
        assert svc.set_image_status(LOCAL_USER, orphan_id, 'reject') is True
        assert svc.purge_unused(LOCAL_USER, ds.id) == 1
        assert svc.db.session.get(FaceDatasetImage, orphan_id) is None


def test_unresolved_reconstruction_pixels_are_immutable(app):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc

    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        source.status = 'pending'
        candidate = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='pending',
            filename='candidate.png', parent_image_id=source.id,
            derivation_kind=svc.KLEIN_IMAGE_IMPROVE)
        with open(os.path.join(svc._dataset_dir(ds.id), candidate.filename), 'wb') as fh:
            fh.write(_png((100, 110, 120)))
        svc.db.session.add(candidate)
        svc.db.session.commit()

        with pytest.raises(ValueError, match='before cropping'):
            svc.crop_image(LOCAL_USER, source.id, 0, 0, 32, 32)
        with pytest.raises(ValueError, match='before cropping'):
            svc.crop_image(LOCAL_USER, candidate.id, 0, 0, 32, 32)


def test_reconstruction_qa_scores_exact_input_without_overwriting_source(app, monkeypatch):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc
    from app.services import face_similarity

    captured = {}
    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        ds.ref_filename = 'ref.png'
        with open(os.path.join(svc._dataset_dir(ds.id), ds.ref_filename), 'wb') as fh:
            fh.write(_png((200, 200, 200)))
        source.original_filename = 'originals/exact.png'
        os.makedirs(os.path.dirname(os.path.join(
            svc._dataset_dir(ds.id), source.original_filename)), exist_ok=True)
        with open(os.path.join(svc._dataset_dir(ds.id), source.original_filename), 'wb') as fh:
            fh.write(_png((5, 6, 7)))
        source.face_state = 'scorable'
        source.face_score = 0.88
        source.analysis_json = '{"metrics":{"sharpness":50,"exposure":50,"resolution":50}}'
        source.status = 'pending'
        candidate = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='pending',
            filename='candidate.png', parent_image_id=source.id,
            derivation_kind=svc.KLEIN_IMAGE_IMPROVE)
        with open(os.path.join(svc._dataset_dir(ds.id), candidate.filename), 'wb') as fh:
            fh.write(_png((180, 180, 180)))
        svc.db.session.add(candidate)
        svc.db.session.commit()

        def score(_ref, paths, **_kwargs):
            captured['paths'] = paths
            return ({
                paths[0]: {'state': 'scorable', 'sim': 0.20, 'face_count': 1,
                           'face_sharpness': 80, 'face_exposure': 80},
                paths[1]: {'state': 'scorable', 'sim': 0.70, 'face_count': 1,
                           'face_sharpness': 80, 'face_exposure': 80},
            }, None)

        monkeypatch.setattr(face_similarity, 'score_dataset_faces', score)
        assert svc._prepare_completed_improvement(candidate) is True
        svc._analyze_completed_improvement(candidate)
        comparison = svc.parse_analysis(candidate.analysis_json)['repair_comparison']

        assert captured['paths'][1] == os.path.join(
            svc._dataset_dir(ds.id), source.original_filename)
        assert comparison['source_filename'] == source.original_filename
        assert comparison['source_identity_score'] == 0.70
        assert comparison['recommendation'] == 'identity_risk'
        assert comparison['phase'] == 'ready'
        assert source.face_score == 0.88


def test_backup_recovers_orphaned_reconstruction_as_ordinary_row(app):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as svc

    with app.app_context():
        ds, source, _raw = _source(svc, FaceDatasetImage, LOCAL_USER)
        filename = 'surviving-reconstruction.png'
        with open(os.path.join(svc._dataset_dir(ds.id), filename), 'wb') as fh:
            fh.write(_png((33, 44, 55)))
        candidate = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='reject', filename=filename,
            parent_image_id=source.id, derivation_kind=svc.KLEIN_IMAGE_IMPROVE)
        svc.db.session.add(candidate)
        svc.db.session.commit()
        # Recreate the legacy database shape that the current API no longer permits.
        svc.db.session.delete(source)
        svc.db.session.commit()

        restored = svc.import_backup_zip(
            LOCAL_USER, svc.build_backup_zip(LOCAL_USER, ds.id))
        rows = FaceDatasetImage.query.filter_by(dataset_id=restored.id).all()
        assert len(rows) == 1
        assert rows[0].filename == filename
        assert rows[0].parent_image_id is None
        assert rows[0].derivation_kind is None
        assert 'orphaned reconstruction' in rows[0].fail_reason
