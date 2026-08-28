"""Asserted-caption admission and inference race protection."""

from pathlib import Path

import pytest


def _caption_dataset(service, image_cls, user_id, kind):
    dataset = service.create_dataset(
        user_id,
        f'{kind.title()} captions',
        f'{kind}_caption',
        kind=kind,
        concept_desc='a recurring action' if kind == 'concept' else None,
    )
    root = Path(service._dataset_dir(dataset.id))
    rows = []
    for index, (caption, origin) in enumerate((
            ('human words', 'asserted'),
            ('machine words', 'joycaption'),
            ('legacy words', None),
            (None, None))):
        filename = f'{index}.webp'
        root.joinpath(filename).write_bytes(b'image')
        rows.append(image_cls(
            dataset_id=dataset.id,
            filename=filename,
            source='import',
            status='keep',
            caption=caption,
            caption_origin=origin,
            caption_provenance='{"revision":"old"}' if origin == 'joycaption' else None,
        ))
    service.db.session.add_all(rows)
    service.db.session.commit()
    return dataset, rows


def _patch_ollama(monkeypatch, service):
    from app.services import vision_ollama

    calls = []

    def describe(*_args, **_kwargs):
        calls.append(True)
        return 'fresh model caption'

    monkeypatch.setattr(service.cfg, 'get', lambda key, default=None: (
        'ollama' if key == 'captioning.backend' else default))
    monkeypatch.setattr(vision_ollama, 'describe_image_ollama', describe)
    monkeypatch.setattr(vision_ollama, 'unload_vision_model', lambda: None)
    monkeypatch.setattr(service, '_get_concept_terms', lambda *_args, **_kwargs: [])
    return calls


@pytest.mark.parametrize('kind', ['character', 'concept', 'style'])
def test_forced_captioning_skips_asserted_in_every_lane(app, monkeypatch, kind):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import dataset_activity
    from app.services import face_dataset_service as service

    with app.app_context():
        totals = []
        original_begin = dataset_activity.begin
        original_progress = dataset_activity.progress

        def begin(*args, **kwargs):
            if kwargs.get('total') is not None:
                totals.append(kwargs['total'])
            return original_begin(*args, **kwargs)

        def progress(*args, **kwargs):
            if kwargs.get('total') is not None:
                totals.append(kwargs['total'])
            return original_progress(*args, **kwargs)

        monkeypatch.setattr(dataset_activity, 'begin', begin)
        monkeypatch.setattr(dataset_activity, 'progress', progress)
        calls = _patch_ollama(monkeypatch, service)
        dataset, rows = _caption_dataset(service, FaceDatasetImage, LOCAL_USER, kind)

        assert service.caption_images(LOCAL_USER, dataset.id, force=True) == 3

        service.db.session.expire_all()
        refreshed = [service.db.session.get(FaceDatasetImage, row.id) for row in rows]
        assert len(calls) == 3
        assert 3 in totals and 4 not in totals
        assert (refreshed[0].caption, refreshed[0].caption_origin) == (
            'human words', 'asserted')
        assert all(row.caption_origin == 'ollama' for row in refreshed[1:])
        assert all(row.caption_provenance is None for row in refreshed[1:])


def test_unforced_and_explicit_override_have_distinct_admission(app, monkeypatch):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as service

    with app.app_context():
        calls = _patch_ollama(monkeypatch, service)
        dataset, rows = _caption_dataset(
            service, FaceDatasetImage, LOCAL_USER, 'character')

        assert service.caption_images(LOCAL_USER, dataset.id) == 1
        assert len(calls) == 1
        assert service.caption_images(
            LOCAL_USER, dataset.id, force=True, include_asserted=True) == 4
        assert len(calls) == 5

        service.db.session.expire_all()
        assert all(
            service.db.session.get(FaceDatasetImage, row.id).caption_origin == 'ollama'
            for row in rows
        )


def test_midflight_edit_clear_and_delete_are_not_overwritten(app, monkeypatch):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as service
    from app.services import vision_ollama

    with app.app_context():
        _patch_ollama(monkeypatch, service)
        dataset, rows = _caption_dataset(
            service, FaceDatasetImage, LOCAL_USER, 'character')
        targets = rows[:3]
        targets[0].caption_origin = 'joycaption'
        targets[1].caption_origin = 'joycaption'
        targets[2].caption_origin = 'joycaption'
        service.db.session.commit()
        index = 0

        def mutate_during_inference(*_args, **_kwargs):
            nonlocal index
            if index >= len(targets):
                return 'ordinary model result'
            row = targets[index]
            if index == 0:
                assert service.set_image_caption(LOCAL_USER, row.id, 'edited by user')
            elif index == 1:
                assert service.batch_image_action(
                    LOCAL_USER, dataset.id, [row.id], 'clear_caption') == 1
            else:
                assert service.delete_image(LOCAL_USER, row.id)
            index += 1
            return 'late model result'

        monkeypatch.setattr(vision_ollama, 'describe_image_ollama', mutate_during_inference)

        assert service.caption_images(LOCAL_USER, dataset.id, force=True) == 1

        service.db.session.expire_all()
        edited, cleared, deleted = [
            service.db.session.get(FaceDatasetImage, row.id) for row in targets]
        assert (edited.caption, edited.caption_origin) == ('edited by user', 'asserted')
        assert (cleared.caption, cleared.caption_origin,
                cleared.caption_provenance) == (None, None, None)
        assert deleted.status == 'trashed'
        assert deleted.caption == 'legacy words'


def test_caption_route_forwards_explicit_asserted_override(client, monkeypatch):
    from app.services import face_dataset_service as service

    dataset_id = client.post('/api/dataset/create', json={
        'name': 'Override route', 'trigger_word': 'override_route',
    }).get_json()['id']
    seen = {}

    def caption_images(*_args, **kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(service, 'caption_images', caption_images)

    response = client.post(f'/api/dataset/{dataset_id}/caption', json={
        'force': True, 'include_asserted': True,
    })

    assert response.status_code == 200
    assert seen == {'force': True, 'mode': None, 'include_asserted': True}

    invalid = client.post(f'/api/dataset/{dataset_id}/caption', json={
        'force': True, 'include_asserted': 'true',
    })
    assert invalid.status_code == 400
    assert 'boolean' in invalid.get_json()['error']
