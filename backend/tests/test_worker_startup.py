import pytest


def test_worker_startup_rolls_back_and_can_retry(app, monkeypatch):
    import app as app_module
    from app.job_queue import queue_manager
    from app.services import checkpoint_registry, cloud_training, lora_training

    events = []
    monkeypatch.setattr(queue_manager, 'init_app', lambda current: events.append('queue:init'))
    monkeypatch.setattr(queue_manager, 'start', lambda: events.append('queue:start'))
    monkeypatch.setattr(queue_manager, 'stop', lambda: events.append('queue:stop'))
    monkeypatch.setattr(
        lora_training, 'start_training_scheduler',
        lambda current: events.append('scheduler:start'))
    monkeypatch.setattr(
        lora_training, 'stop_training_scheduler',
        lambda: events.append('scheduler:stop'))
    monkeypatch.setattr(
        checkpoint_registry, 'start_legacy_backfill',
        lambda current: events.append('backfill:start'))
    monkeypatch.setattr(
        checkpoint_registry, 'stop_legacy_backfill',
        lambda current: events.append('backfill:stop'))
    monkeypatch.setattr(
        cloud_training, 'stop_reconciler',
        lambda: events.append('reconciler:stop'))
    monkeypatch.setattr(cloud_training, 'boot_recover', lambda current: None)

    def fail_reconciler(current):
        events.append('reconciler:start')
        raise RuntimeError('injected startup failure')

    monkeypatch.setattr(cloud_training, 'start_reconciler', fail_reconciler)
    with pytest.raises(RuntimeError, match='injected startup failure'):
        app_module._start_workers(app)
    assert events[-3:] == ['backfill:stop', 'scheduler:stop', 'queue:stop']
    assert 'background_worker_owner' not in app.extensions

    monkeypatch.setattr(
        cloud_training, 'start_reconciler',
        lambda current: events.append('reconciler:start'))
    owner = app_module._start_workers(app)
    assert app_module._start_workers(app) is owner
    assert events.count('queue:start') == 2
    owner.stop()
    assert events[-4:] == [
        'reconciler:stop', 'backfill:stop', 'scheduler:stop', 'queue:stop']
