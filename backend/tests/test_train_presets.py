"""Training presets: named snapshots of the advanced settings, import/export
friendly. The core promise is SCHEMA TOLERANCE — a preset from another app
version applies with unknown keys ignored and invalid values reported, never
a hard failure.
"""

import pytest


def _create_ds(client, name='Preset', trigger='pres', train_type='krea'):
    return client.post('/api/dataset/create',
                       json={'name': name, 'trigger_word': trigger,
                             'train_type': train_type}).get_json()['id']


def test_save_from_dataset_snapshot_and_list(client, app):
    ds_id = _create_ds(client)
    # give the dataset one explicit setting to snapshot
    with app.app_context():
        from app.services import lora_training as lt
        lt.update_train_settings('local', ds_id, {'rank': 32})
    r = client.post('/api/train/presets', json={'name': 'My Krea', 'dataset_id': ds_id})
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True and body['created'] is True
    assert body['train_type'] == 'krea'
    assert body['settings'] == {'rank': 32}
    listed = client.get('/api/train/presets').get_json()['presets']
    assert any(p['name'] == 'My Krea' and p['settings'] == {'rank': 32} for p in listed)


def test_save_overwrites_by_name(client):
    r1 = client.post('/api/train/presets',
                     json={'name': 'Dup', 'train_type': 'zimage', 'settings': {'rank': 16}})
    r2 = client.post('/api/train/presets',
                     json={'name': 'Dup', 'train_type': 'zimage', 'settings': {'rank': 64}})
    assert r1.get_json()['created'] is True
    assert r2.get_json()['created'] is False
    listed = client.get('/api/train/presets').get_json()['presets']
    assert [p['settings'] for p in listed if p['name'] == 'Dup'] == [{'rank': 64}]


def test_apply_is_schema_tolerant(client, app):
    """Unknown keys (future app versions) are ignored, invalid values rejected,
    valid keys land — all in one call, never fatal."""
    ds_id = _create_ds(client)
    r = client.post(f'/api/dataset/{ds_id}/train/presets/apply', json={'settings': {
        'rank': 32,                       # valid → applied
        'dropout': 0.1,                   # valid → applied
        'rank_v2_search_space': [1, 2],   # unknown → ignored
        'save_every': 123,                # invalid value → rejected
    }})
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True
    assert body['ignored'] == ['rank_v2_search_space']
    assert [x['key'] for x in body['rejected']] == ['save_every']
    with app.app_context():
        from app.services import lora_training as lt
        stored = lt.snapshot_train_settings('local', ds_id)
        assert stored == {'rank': 32, 'dropout': 0.1}


def test_apply_replaces_previous_settings(client, app):
    """A preset REPLACES the explicit settings — keys absent from the preset
    fall back to defaults instead of surviving from before."""
    ds_id = _create_ds(client)
    with app.app_context():
        from app.services import lora_training as lt
        lt.update_train_settings('local', ds_id, {'rank': 64, 'dropout': 0.3})
    client.post(f'/api/dataset/{ds_id}/train/presets/apply',
                json={'settings': {'rank': 16}})
    with app.app_context():
        from app.services import lora_training as lt
        assert lt.snapshot_train_settings('local', ds_id) == {'rank': 16}


def test_apply_rolls_back_complete_replacement_on_abrupt_interruption(
        client, app, monkeypatch):
    ds_id = _create_ds(client)
    with app.app_context():
        from app.services import lora_training as lt
        from app.services import face_dataset_service as fds
        lt.update_train_settings(
            'local', ds_id, {'rank': 64, 'dropout': 0.3})
        original = lt.update_train_settings
        calls = 0

        def interrupt_on_second_key(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SystemExit('simulated process interruption')
            return original(*args, **kwargs)

        monkeypatch.setattr(lt, 'update_train_settings', interrupt_on_second_key)
        with pytest.raises(SystemExit, match='simulated process interruption'):
            lt.apply_train_settings_dict(
                'local', ds_id, {'rank': 16, 'resolution': '768'})

        fds.db.session.expire_all()
        assert lt.snapshot_train_settings('local', ds_id) == {
            'rank': 64, 'dropout': 0.3}


def test_builtin_presets_listed_first_and_undeletable(client):
    listed = client.get('/api/train/presets').get_json()['presets']
    assert listed and listed[0]['id'] == 'builtin-krea-character'
    assert listed[0]['builtin'] is True
    # the delete route only matches integer ids — built-ins are unreachable
    assert client.delete('/api/train/presets/builtin-krea-character').status_code == 404


def test_every_builtin_applies_cleanly(client, app):
    """The shipped presets must ALWAYS apply with zero ignored keys and zero
    rejected values — this is the guard that catches a choice-list drifting
    away from what the built-ins promise."""
    from app.services.lora_training import BUILTIN_TRAIN_PRESETS
    ds_id = _create_ds(client)
    for preset in BUILTIN_TRAIN_PRESETS:
        r = client.post(f'/api/dataset/{ds_id}/train/presets/apply',
                        json={'settings': preset['settings']})
        body = r.get_json()
        assert body['ok'] is True, preset['id']
        assert body['ignored'] == [], preset['id']
        assert body['rejected'] == [], preset['id']


def test_apply_by_preset_id_and_delete(client):
    ds_id = _create_ds(client)
    pid = client.post('/api/train/presets',
                      json={'name': 'ById', 'train_type': 'krea',
                            'settings': {'rank': 32}}).get_json()['id']
    r = client.post(f'/api/dataset/{ds_id}/train/presets/apply', json={'preset_id': pid})
    assert r.get_json()['ok'] is True
    assert client.delete(f'/api/train/presets/{pid}').get_json()['ok'] is True
    assert client.delete(f'/api/train/presets/{pid}').status_code == 404
