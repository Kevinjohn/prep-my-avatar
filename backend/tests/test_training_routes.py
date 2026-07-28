"""Training blueprint: ai-toolkit gating + kwargs forwarding to the service.

Every test patches `app.capabilities.probe` so none of this ever touches a
real HTTP/subprocess probe, and patches the `lora_training`/`zimage_convert`
service functions it exercises so no test spawns a real subprocess.
"""
import pytest

def _create(client, name='Lola', trigger='lola'):
    return client.post('/api/dataset/create', json={'name': name, 'trigger_word': trigger}).get_json()['id']


def _valid(monkeypatch, ok=True):
    monkeypatch.setattr('app.capabilities.probe', lambda *a, **k: {'aitoolkit': {'valid': ok}})


# --- Gating -------------------------------------------------------------------

def test_train_unconfigured_returns_409_with_hint(client, monkeypatch):
    _valid(monkeypatch, False)
    resp = client.post('/api/dataset/1/train', json={})
    assert resp.status_code == 409
    body = resp.get_json()
    assert body['error'] == 'ai-toolkit is not configured'
    assert body['hint'] == 'Set its folder in Settings'


def test_status_available_false_when_unconfigured(client, monkeypatch):
    _valid(monkeypatch, False)
    resp = client.get('/api/dataset/train/status')
    assert resp.status_code == 200
    assert resp.get_json() == {'available': False}


def test_status_configured_is_read_only(client, monkeypatch):
    _valid(monkeypatch, True)
    monkeypatch.setattr(
        'app.services.lora_training.process_training_queue',
        lambda: (_ for _ in ()).throw(AssertionError('GET must not advance the queue')))
    monkeypatch.setattr('app.services.lora_training.training_status',
                        lambda user_id=None: {'in_progress': False, 'user': user_id})
    resp = client.get('/api/dataset/train/status')
    assert resp.status_code == 200
    assert resp.get_json() == {'in_progress': False, 'user': 'local'}


def test_stop_gated_when_unconfigured(client, monkeypatch):
    _valid(monkeypatch, False)
    resp = client.post('/api/dataset/train/stop')
    assert resp.status_code == 409


def test_train_unknown_dataset_404(client, monkeypatch):
    _valid(monkeypatch, True)
    resp = client.post('/api/dataset/999999/train', json={})
    assert resp.status_code == 404


def test_train_settings_unsupported_rank_is_typed_400(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)

    response = client.post(
        f'/api/dataset/{ds_id}/train/settings', json={'rank': 7})

    assert response.status_code == 400
    body = response.get_json()
    assert body['error'] == 'rank must be one of (8, 16, 24, 32, 48, 64) (or auto)'
    assert body['code'] == 'validation_error'


def test_map_error_safely_maps_legacy_builtins_and_reraises_unknowns(app):
    from app.routes._common import _map_error

    with app.app_context():
        validation, validation_status = _map_error(ValueError('internal parse'))
        conflict, conflict_status = _map_error(RuntimeError('broken invariant'))
        assert validation_status == 400
        assert validation.get_json()['error'] == 'invalid request'
        assert conflict_status == 409
        assert conflict.get_json()['error'] == 'operation conflicts with current state'
        with pytest.raises(KeyError, match='unknown'):
            _map_error(KeyError('unknown'))


# --- /train ---------------------------------------------------------------

def test_train_configured_forwards_kwargs(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    captured = {}

    def fake_launch(user_id, dataset_id, **kw):
        captured['user_id'] = user_id
        captured['dataset_id'] = dataset_id
        captured.update(kw)
        return {'started': True, 'pid': 123, 'config_path': 'x', 'steps': 1234,
                'dataset_folder': 'y', 'log_path': 'z'}

    monkeypatch.setattr('app.services.lora_training.launch_training', fake_launch)
    resp = client.post(f'/api/dataset/{ds_id}/train', json={
        'steps': 1234, 'masked': False, 'train_type': 'sdxl', 'allow_caption_mismatch': True})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True and body['pid'] == 123
    assert captured == {
        'user_id': 'local',
        'dataset_id': ds_id,
        'steps': 1234,
        'base_model': None,
        'variant': 'turbo',
        'train_type': 'sdxl',
        'allow_caption_mismatch': True,
        'allow_uncaptioned': False,   # absent du body → False (confirm non donné)
        'allow_unverified_weights': False,   # custom-weights confirm non donné
        'masked': False,
        'fresh': False,          # absent du body → False (resume historique)
    }
    # fresh=true (choix « Start fresh » du panneau) traverse jusqu'au service.
    client.post(f'/api/dataset/{ds_id}/train', json={'fresh': True})
    assert captured['fresh'] is True


def test_train_value_error_returns_400(client, monkeypatch):
    from app.domain_errors import DomainValidationError
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.services.lora_training.launch_training',
                        lambda *a, **k: (_ for _ in ()).throw(DomainValidationError('bad state')))
    resp = client.post(f'/api/dataset/{ds_id}/train', json={})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'bad state'


def test_train_runtime_error_returns_409(client, monkeypatch):
    from app.domain_errors import DomainConflictError
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.services.lora_training.launch_training',
                        lambda *a, **k: (_ for _ in ()).throw(DomainConflictError('not installed')))
    resp = client.post(f'/api/dataset/{ds_id}/train', json={})
    assert resp.status_code == 409


# --- /train/continue --------------------------------------------------------

def test_continue_forwards_kwargs(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    captured = {}

    def fake_continue(user_id, dataset_id, **kw):
        captured.update(kw)
        return {'started': True, 'resumed_from': 500, 'target_steps': 1500}

    monkeypatch.setattr('app.services.lora_training.continue_training', fake_continue)
    resp = client.post(f'/api/dataset/{ds_id}/train/continue',
                       json={'extra_steps': 1000, 'variant': 'base', 'train_type': 'krea'})
    assert resp.status_code == 200
    assert captured == {'extra_steps': 1000, 'variant': 'base', 'train_type': 'krea'}


# --- /train/enqueue ----------------------------------------------------------

def test_enqueue_forwards_kwargs(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    captured = {}

    def fake_enqueue(user_id, dataset_id, **kw):
        captured.update(kw)
        return {'queued': True, 'position': 1, 'not_before': None}

    monkeypatch.setattr('app.services.lora_training.enqueue_training', fake_enqueue)
    resp = client.post(f'/api/dataset/{ds_id}/train/enqueue',
                       json={'extra_steps': 500, 'steps': 3000, 'allow_caption_mismatch': True})
    assert resp.status_code == 200
    assert captured == {
        'extra_steps': 500,
        'masked': True,
        'steps': 3000,
        'allow_caption_mismatch': True
    }


def test_enqueue_requires_and_forwards_explicit_fresh_mode(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    assert client.post(f'/api/dataset/{ds_id}/train/enqueue', json={}).status_code == 400
    captured = {}
    monkeypatch.setattr('app.services.lora_training.enqueue_training',
                        lambda *a, **kw: captured.update(kw) or {'queued': True})
    resp = client.post(f'/api/dataset/{ds_id}/train/enqueue', json={'fresh': True})
    assert resp.status_code == 200
    assert captured['fresh'] is True


# --- /train/schedule ---------------------------------------------------------

def test_schedule_past_returns_400(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    resp = client.post(f'/api/dataset/{ds_id}/train/schedule',
                       json={'at': '2000-01-01T00:00', 'fresh': False})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'scheduled time is in the past'


def test_schedule_invalid_datetime_returns_400(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    resp = client.post(f'/api/dataset/{ds_id}/train/schedule',
                       json={'at': 'not-a-date', 'fresh': False})
    assert resp.status_code == 400


def test_schedule_future_enqueues_with_not_before(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    captured = {}

    def fake_enqueue(user_id, dataset_id, **kw):
        captured.update(kw)
        return {'queued': True, 'position': 1, 'not_before': kw.get('not_before')}

    monkeypatch.setattr('app.services.lora_training.enqueue_training', fake_enqueue)
    resp = client.post(f'/api/dataset/{ds_id}/train/schedule',
                       json={'at': '2999-01-01T00:00', 'fresh': False})
    assert resp.status_code == 200
    assert captured == {
        'extra_steps': None,
        'not_before': '2999-01-01T00:00',
        'masked': True,
        'fresh': False,
    }


def test_schedule_tzaware_future_normalizes_and_enqueues(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    captured = {}

    def fake_enqueue(user_id, dataset_id, **kw):
        captured.update(kw)
        return {'queued': True, 'position': 1, 'not_before': kw.get('not_before')}

    monkeypatch.setattr('app.services.lora_training.enqueue_training', fake_enqueue)
    # Use UTC-05:00 offset so converting to local (UTC-based or positive) keeps date in 2999
    resp = client.post(f'/api/dataset/{ds_id}/train/schedule',
                       json={'at': '2999-01-02T00:00:00-05:00', 'fresh': False})
    assert resp.status_code == 200
    # tz-aware input is normalized; not_before should be naive local ISO format with year 2999+
    assert 'not_before' in captured
    # After normalization to local time, should be in year 2999 or later
    assert int(captured['not_before'][:4]) >= 2999


def test_schedule_tzaware_past_returns_400(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    resp = client.post(f'/api/dataset/{ds_id}/train/schedule',
                       json={'at': '1999-01-01T00:00:00+02:00', 'fresh': False})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'scheduled time is in the past'


# --- /train/dequeue, /train/stop ---------------------------------------------

def test_dequeue_calls_service(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.services.lora_training.dequeue_training', lambda dataset_id: 1)
    resp = client.post(f'/api/dataset/{ds_id}/train/dequeue')
    assert resp.status_code == 200
    assert resp.get_json() == {'ok': True, 'removed': 1}


def test_stop_calls_stop_training(client, monkeypatch):
    _valid(monkeypatch, True)
    calls = []
    monkeypatch.setattr('app.services.lora_training.stop_training',
                        lambda **kw: calls.append(kw))
    resp = client.post('/api/dataset/train/stop', json={'clear_queue': False})
    assert resp.status_code == 200
    assert calls == [{'clear_queue': False}]
    assert resp.get_json()['queue_cleared'] is False


def test_stop_rejects_non_boolean_queue_policy(client, monkeypatch):
    _valid(monkeypatch, True)
    assert client.post('/api/dataset/train/stop',
                       json={'clear_queue': 'yes'}).status_code == 400


# --- /train/checkpoints -------------------------------------------------------

def test_checkpoints_returns_recommended_steps(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.services.lora_training.list_checkpoints',
                        lambda *a, **k: [{'step': 500, 'filename': 'x.safetensors'}])
    monkeypatch.setattr('app.services.lora_training.recommended_steps', lambda dataset_id: 2500)
    monkeypatch.setattr('app.services.lora_training.list_imported_checkpoints', lambda *a, **k: [])
    resp = client.get(f'/api/dataset/{ds_id}/train/checkpoints')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['recommended_steps'] == 2500
    assert body['checkpoints'][0]['step'] == 500
    assert body['imported'] == []


# --- /train/base-info ---------------------------------------------------------

def test_base_info_returns_bases_by_type(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    resp = client.get(f'/api/dataset/{ds_id}/train/base-info')
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body['bases_by_type']) == {'zimage', 'sdxl', 'krea', 'flux', 'flux2klein'}
    assert body['train_type'] == 'zimage'


def test_base_info_unknown_dataset_404(client, monkeypatch):
    _valid(monkeypatch, True)
    resp = client.get('/api/dataset/999999/train/base-info')
    assert resp.status_code == 404


def test_base_info_comfyui_unconfigured_flag(client, monkeypatch):
    """Fresh config: no comfyui.base_dir -> comfyui_configured False, so the UI can
    say 'point the app at ComfyUI' instead of a blind 'No checkpoint found'."""
    _valid(monkeypatch, True)
    ds_id = _create(client)
    body = client.get(f'/api/dataset/{ds_id}/train/base-info').get_json()
    assert body['comfyui_configured'] is False
    assert body['models_dir'] == ''


def test_base_info_comfyui_configured_flag(client, monkeypatch, tmp_path):
    from app import config as cfg
    _valid(monkeypatch, True)
    base = tmp_path / 'comfyui'
    (base / 'models').mkdir(parents=True)
    cfg.save_config({'comfyui': {'base_dir': str(base)}})
    ds_id = _create(client)
    body = client.get(f'/api/dataset/{ds_id}/train/base-info').get_json()
    assert body['comfyui_configured'] is True
    assert body['models_dir'].replace('/', '\\').endswith('models')


# --- /train/prepare-base -------------------------------------------------------

def test_prepare_base_rejects_unknown_base(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.routes.training.get_zimage_models', lambda: ['z image\\known.safetensors'])
    resp = client.post(f'/api/dataset/{ds_id}/train/prepare-base', json={'base_model': 'unknown.safetensors'})
    assert resp.status_code == 400


def test_prepare_base_already_converted_returns_done(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.routes.training.get_zimage_models', lambda: ['z image\\known.safetensors'])
    monkeypatch.setattr('app.services.zimage_convert.is_converted', lambda m: True)
    resp = client.post(f'/api/dataset/{ds_id}/train/prepare-base',
                       json={'base_model': 'z image\\known.safetensors'})
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'done'


def test_prepare_base_starts_conversion(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.routes.training.get_zimage_models', lambda: ['z image\\known.safetensors'])
    monkeypatch.setattr('app.services.zimage_convert.is_converted', lambda m: False)
    calls = []
    monkeypatch.setattr('app.services.zimage_convert.start_convert_async',
                        lambda app, m: calls.append(m))
    resp = client.post(f'/api/dataset/{ds_id}/train/prepare-base',
                       json={'base_model': 'z image\\known.safetensors'})
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'running'
    assert calls == ['z image\\known.safetensors']


def test_prepare_base_requires_base_model(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    resp = client.post(f'/api/dataset/{ds_id}/train/prepare-base', json={})
    assert resp.status_code == 400


# --- /train/checkpoint/delete, /train/import -----------------------------------

def test_checkpoint_delete_calls_service(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.services.lora_training.delete_imported_checkpoint',
                        lambda user_id, dataset_id, fn, family=None: fn)
    resp = client.post(f'/api/dataset/{ds_id}/train/checkpoint/delete', json={'filename': 'x.safetensors'})
    assert resp.status_code == 200
    assert resp.get_json() == {'ok': True, 'removed': 'x.safetensors'}


def test_checkpoint_delete_unknown_returns_400(client, monkeypatch):
    from app.domain_errors import DomainValidationError
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.services.lora_training.delete_imported_checkpoint',
                        lambda *a, **k: (_ for _ in ()).throw(DomainValidationError('checkpoint inconnu')))
    resp = client.post(f'/api/dataset/{ds_id}/train/checkpoint/delete', json={'filename': 'nope.safetensors'})
    assert resp.status_code == 400


def test_import_checkpoint_calls_service(client, monkeypatch):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr('app.services.lora_training.import_checkpoint',
                        lambda user_id, dataset_id, fn, **kw: f'/some/dir/{fn}')
    resp = client.post(f'/api/dataset/{ds_id}/train/import', json={'filename': 'x.safetensors'})
    assert resp.status_code == 200
    assert resp.get_json() == {'ok': True, 'dest': 'x.safetensors'}


@pytest.mark.parametrize('payload', ['[]', '"text"', '1', 'null'])
def test_training_json_posts_reject_non_object_bodies(client, monkeypatch, payload):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    for path in (f'/api/dataset/{ds_id}/train',
                 f'/api/dataset/{ds_id}/train/enqueue',
                 '/api/dataset/train/stop'):
        response = client.post(path, data=payload, content_type='application/json')
        assert response.status_code == 400
        assert response.get_json()['error'] == 'request body must be a JSON object'


def test_training_stop_maps_service_errors(client, monkeypatch):
    from app.domain_errors import DomainConflictError
    _valid(monkeypatch, True)
    monkeypatch.setattr('app.services.lora_training.stop_training',
                        lambda **kwargs: (_ for _ in ()).throw(DomainConflictError('cannot stop safely')))
    response = client.post('/api/dataset/train/stop', json={'clear_queue': False})
    assert response.status_code != 500
    assert response.get_json()['error'] == 'cannot stop safely'


@pytest.mark.parametrize(('error', 'status', 'message'), [
    (ValueError('bug detail'), 400, 'invalid request'),
    (RuntimeError('bug detail'), 409, 'operation conflicts with current state'),
])
def test_training_generic_builtins_keep_legacy_status_without_public_detail(
        client, monkeypatch, error, status, message):
    _valid(monkeypatch, True)
    ds_id = _create(client)
    monkeypatch.setattr(
        'app.services.lora_training.launch_training',
        lambda *args, **kwargs: (_ for _ in ()).throw(error))

    response = client.post(f'/api/dataset/{ds_id}/train', json={})

    assert response.status_code == status
    assert response.get_json()['error'] == message
    assert 'bug detail' not in response.get_data(as_text=True)
