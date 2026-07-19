"""Human curation audit trail and conflict-safe transactional undo."""
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
