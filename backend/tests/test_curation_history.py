"""Human curation audit trail and conflict-safe transactional undo."""
from concurrent.futures import ThreadPoolExecutor
import threading

from app.extensions import db


def _dataset_with_images(client, app, count=2):
    dataset_id = client.post('/api/dataset/create', json={
        'name': 'History', 'trigger_word': 'history',
    }).get_json()['id']
    with app.app_context():
        from app.models import FaceDatasetImage
        rows = [FaceDatasetImage(dataset_id=dataset_id, status='pending')
                for _ in range(count)]
        db.session.add_all(rows)
        db.session.commit()
        ids = [row.id for row in rows]
    return dataset_id, ids


def test_single_status_and_caption_edits_are_audited_and_undoable(client, app):
    dataset_id, (image_id, _) = _dataset_with_images(client, app)
    assert client.post(f'/api/dataset/image/{image_id}/status',
                       json={'status': 'keep'}).status_code == 200
    assert client.post(f'/api/dataset/image/{image_id}/caption',
                       json={'caption': 'new caption'}).status_code == 200

    history = client.get(
        f'/api/dataset/{dataset_id}/curation/history').get_json()
    assert [row['action'] for row in history['events'][:2]] == [
        'caption', 'status:keep']
    assert history['can_undo'] is True

    assert client.post(f'/api/dataset/{dataset_id}/curation/undo', json={}).get_json()[
        'action'] == 'caption'
    with app.app_context():
        from app.models import FaceDatasetImage
        row = db.session.get(FaceDatasetImage, image_id)
        assert row.caption is None and row.status == 'keep'

    client.post(f'/api/dataset/{dataset_id}/curation/undo', json={})
    with app.app_context():
        from app.models import FaceDatasetImage
        assert db.session.get(FaceDatasetImage, image_id).status == 'pending'


def test_concurrent_status_edits_form_a_serial_undo_chain(app, client, monkeypatch):
    dataset_id, (image_id, _) = _dataset_with_images(client, app)
    from app.services import curation_history
    original_snapshot = curation_history.snapshot
    first_snapshot_started = threading.Event()
    release_first = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def paused_snapshot(image, fields):
        nonlocal calls
        with calls_lock:
            calls += 1
            call = calls
        if call == 1:
            first_snapshot_started.set()
            assert release_first.wait(timeout=2)
        return original_snapshot(image, fields)

    monkeypatch.setattr(curation_history, 'snapshot', paused_snapshot)

    def update(status):
        with app.app_context():
            from app.services import face_dataset_service as service
            return service.set_image_status('local', image_id, status)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(update, 'keep')
        assert first_snapshot_started.wait(timeout=2)
        second = pool.submit(update, 'reject')
        release_first.set()
        assert first.result(timeout=2) is True
        assert second.result(timeout=2) is True

    with app.app_context():
        from app.models import CurationEvent, FaceDatasetImage
        events = CurationEvent.query.filter_by(dataset_id=dataset_id).order_by(
            CurationEvent.id.asc()).all()
        assert [event.before_state for event in events] == [
            '{"status": "pending"}', '{"status": "keep"}']
        assert db.session.get(FaceDatasetImage, image_id).status == 'reject'
        result = curation_history.undo('local', dataset_id)
        assert result['undone'] == 1
        assert db.session.get(FaceDatasetImage, image_id).status == 'keep'


def test_batch_undo_restores_every_selected_image_atomically(client, app):
    dataset_id, image_ids = _dataset_with_images(client, app, count=3)
    response = client.post(f'/api/dataset/{dataset_id}/images/batch', json={
        'ids': image_ids, 'action': 'keep',
    })
    assert response.status_code == 200 and response.get_json()['affected'] == 3
    history = client.get(
        f'/api/dataset/{dataset_id}/curation/history').get_json()['events']
    assert len({row['batch_id'] for row in history}) == 1
    assert {row['batch_size'] for row in history} == {3}

    result = client.post(f'/api/dataset/{dataset_id}/curation/undo', json={
        'event_id': history[1]['id'],
    }).get_json()
    assert result['undone'] == 3
    with app.app_context():
        from app.models import FaceDatasetImage
        assert {db.session.get(FaceDatasetImage, image_id).status
                for image_id in image_ids} == {'pending'}


def test_undo_refuses_to_overwrite_a_newer_untracked_change(client, app):
    dataset_id, (image_id, _) = _dataset_with_images(client, app)
    client.post(f'/api/dataset/image/{image_id}/status', json={'status': 'keep'})
    with app.app_context():
        from app.models import FaceDatasetImage
        db.session.get(FaceDatasetImage, image_id).status = 'reject'
        db.session.commit()
    response = client.post(f'/api/dataset/{dataset_id}/curation/undo', json={})
    assert response.status_code == 409
    assert response.get_json()['code'] == 'curation_undo_conflict'
    with app.app_context():
        from app.models import FaceDatasetImage
        assert db.session.get(FaceDatasetImage, image_id).status == 'reject'


def test_history_is_owned_and_cursor_paginated(client, app):
    dataset_id, (image_id, _) = _dataset_with_images(client, app)
    client.post(f'/api/dataset/image/{image_id}/status', json={'status': 'keep'})
    client.post(f'/api/dataset/image/{image_id}/caption', json={'caption': 'one'})
    page = client.get(
        f'/api/dataset/{dataset_id}/curation/history?limit=1').get_json()
    assert len(page['events']) == 1 and page['next_cursor'] is not None
    older = client.get(
        f'/api/dataset/{dataset_id}/curation/history?limit=1&cursor={page["next_cursor"]}'
    ).get_json()
    assert len(older['events']) == 1
    assert client.get('/api/dataset/999999/curation/history').status_code == 404


def test_history_marks_invalid_snapshot_instead_of_rendering_empty_change(client, app):
    dataset_id, (image_id, _) = _dataset_with_images(client, app)
    with app.app_context():
        from app.models import CurationEvent
        db.session.add(CurationEvent(
            dataset_id=dataset_id, image_id=image_id, batch_id='invalid',
            actor_user_id='local', action='legacy',
            before_state='{"unsupported": 1}', after_state='{"unsupported": 2}'))
        db.session.commit()

    event = client.get(
        f'/api/dataset/{dataset_id}/curation/history').get_json()['events'][0]

    assert event['snapshot_valid'] is False
    assert event['before'] is None
    assert event['after'] is None


def test_can_undo_looks_beyond_a_page_of_reverted_events(client, app):
    dataset_id, (image_id, _) = _dataset_with_images(client, app)
    client.post(f'/api/dataset/image/{image_id}/status', json={'status': 'keep'})
    client.post(f'/api/dataset/image/{image_id}/caption', json={'caption': 'one'})
    latest = client.get(
        f'/api/dataset/{dataset_id}/curation/history?limit=1').get_json()['events'][0]
    client.post(f'/api/dataset/{dataset_id}/curation/undo', json={'event_id': latest['id']})
    page = client.get(
        f'/api/dataset/{dataset_id}/curation/history?limit=1').get_json()
    assert page['events'][0]['reverted'] is True
    assert page['can_undo'] is True


def test_undo_cannot_leap_over_newer_decisions_that_return_to_same_value(client, app):
    dataset_id, (image_id, _) = _dataset_with_images(client, app)
    client.post(f'/api/dataset/image/{image_id}/status', json={'status': 'keep'})
    oldest = client.get(
        f'/api/dataset/{dataset_id}/curation/history').get_json()['events'][0]
    client.post(f'/api/dataset/image/{image_id}/status', json={'status': 'reject'})
    client.post(f'/api/dataset/image/{image_id}/status', json={'status': 'keep'})

    response = client.post(f'/api/dataset/{dataset_id}/curation/undo', json={
        'event_id': oldest['id'],
    })

    assert response.status_code == 409
    assert response.get_json()['code'] == 'curation_undo_conflict'


def test_rights_and_coverage_provenance_are_audited_and_undoable(client, app):
    dataset_id, (image_id, _) = _dataset_with_images(client, app)
    with app.app_context():
        from app.models import FaceDatasetImage
        db.session.get(FaceDatasetImage, image_id).source = 'import'
        db.session.commit()

    response = client.post(f'/api/dataset/image/{image_id}/rights', json={
        'basis': 'licensed', 'license': 'CC BY 4.0', 'consent_confirmed': True,
    })
    assert response.status_code == 200
    history = client.get(
        f'/api/dataset/{dataset_id}/curation/history').get_json()['events']
    assert history[0]['action'] == 'rights:licensed'
    assert 'source_rights' in history[0]['after']
    assert client.post(
        f'/api/dataset/{dataset_id}/curation/undo', json={}).status_code == 200

    response = client.post(f'/api/dataset/image/{image_id}/coverage', json={
        'framing': 'face', 'angle': 'front', 'lighting': 'daylight',
    })
    assert response.status_code == 200
    history = client.get(
        f'/api/dataset/{dataset_id}/curation/history').get_json()['events']
    assert history[0]['action'] == 'coverage'
    assert 'coverage_provenance' in history[0]['after']
    assert client.post(
        f'/api/dataset/{dataset_id}/curation/undo', json={}).status_code == 200

    with app.app_context():
        from app.models import FaceDatasetImage
        row = db.session.get(FaceDatasetImage, image_id)
        assert row.source_rights is None
        assert row.coverage_json is None
        assert row.coverage_provenance is None
        assert row.coverage_value is None
        assert row.framing is None
