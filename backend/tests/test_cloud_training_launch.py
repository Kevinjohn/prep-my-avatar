"""Launch validation, LEAK-SAFE provisioning (the property that matters),
stop request, and boot reconciliation. vast_client and the monitor thread are
always mocked -- no network, no thread started for real."""
import json
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def ct(app, monkeypatch):
    return _configure_ct(monkeypatch)


@pytest.fixture()
def threaded_ct(threaded_app, monkeypatch):
    return _configure_ct(monkeypatch)


def _configure_ct(monkeypatch):
    monkeypatch.setenv('VAST_API_KEY', 'k-test')
    from app.services import cloud_training
    monkeypatch.setattr(cloud_training, 'utcnow', lambda: datetime(2026, 7, 15, 12))
    monkeypatch.setattr(cloud_training, '_now', lambda: 1784116800.0)
    # never start the real monitor thread in launch tests
    monkeypatch.setattr(cloud_training, '_start_monitor', lambda *a, **k: None)
    # launch_cloud_training now reconciles orphans on every call (so a user
    # coming back days later to a launch reaps an expired error_pod_kept pod
    # too, not just at boot) -- no-op that call site here so plain
    # launch/provision tests stay offline. Patching the seam (not
    # reconcile_orphans itself) leaves the reconcile-policy tests below,
    # which call reconcile_orphans() directly, exercising the real thing.
    monkeypatch.setattr(cloud_training, '_reconcile_before_launch', lambda a: None)
    monkeypatch.setattr(
        cloud_training, '_capture_training_snapshot',
        lambda uid, did, dest: {
            'registry_manifest': [], 'trigger_word': 'lola', 'kind': 'character',
        })
    return cloud_training


@pytest.fixture()
def seeded_dataset(app, client):
    ds_id = client.post('/api/dataset/create',
                        json={'name': 'Lola', 'trigger_word': 'lola'}).get_json()['id']
    return ds_id


def _fake_export(monkeypatch, ct):
    monkeypatch.setattr(ct.lt, 'export_dataset_to_aitoolkit',
                        lambda uid, did, masked=True, dest_dir=None, **kw: dest_dir)
    monkeypatch.setattr(ct.lt, 'default_steps', lambda ds: 1200)
    # The seeded_dataset fixture has 0 kept images -- the real assert_trainable
    # (lora_training.py, already a standalone helper: dataset_id, train_type=None,
    # allow_caption_mismatch=False) requires >= 10, which is orthogonal to what
    # these launch/provision/reconcile tests exercise. Stub it out here so launch
    # reaches the orchestration code; the caption-mismatch contract itself is
    # covered by lora_training's own tests.
    monkeypatch.setattr(ct.lt, 'assert_trainable', lambda *a, **kw: None)


def test_launch_rejects_custom_base(ct, app, seeded_dataset, monkeypatch):
    with app.app_context():
        with pytest.raises(ValueError, match='local'):
            ct.launch_cloud_training('local', seeded_dataset, base_model='myBase.safetensors')


def test_launch_rejects_persisted_local_base(ct, app, seeded_dataset):
    with app.app_context():
        from app.services import face_dataset_service as fds
        ds = fds.get_dataset('local', seeded_dataset)
        ds.train_base_model = 'converted-local-merge.safetensors'
        ct.db.session.commit()
        with pytest.raises(ValueError, match='local'):
            ct.launch_cloud_training('local', seeded_dataset)


def test_launch_rejects_sdxl(ct, app, seeded_dataset):
    with app.app_context():
        with pytest.raises(ValueError, match='SDXL'):
            ct.launch_cloud_training('local', seeded_dataset, train_type='sdxl')


def test_launch_rejects_flux_but_allows_flux2klein(ct, app, seeded_dataset, monkeypatch):
    """FLUX.1 stays local-only; FLUX.2 Klein is cloud-ENABLED (official HF bases
    the pod downloads itself — the 9B size is even the family's cloud-first
    lane). The launch persists the family and its '4b' default variant, exactly
    like the local path."""
    _fake_export(monkeypatch, ct)
    with app.app_context():
        with pytest.raises(ValueError, match='local-only'):
            ct.launch_cloud_training('local', seeded_dataset, train_type='flux')
        res = ct.launch_cloud_training('local', seeded_dataset, train_type='flux2klein')
        assert res['status'] == 'preparing'
        from app.services import face_dataset_service as fds
        ds = fds.get_dataset('local', seeded_dataset)
        assert ds.train_type == 'flux2klein'
        assert ds.train_variant == '4b'


def test_launch_flux2klein_accepts_9b_variant(ct, app, seeded_dataset, monkeypatch):
    """The per-family variant enum: '9b' is kept as-is; a foreign leftover like
    'turbo' falls back to the family default '4b' (never leaks into the run)."""
    import json as _json
    _fake_export(monkeypatch, ct)
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset,
                                 train_type='flux2klein', variant='9b')
        run = ct.get_active_run()
        assert _json.loads(run.train_params)['variant'] == '9b'
        from app.services import face_dataset_service as fds
        assert fds.get_dataset('local', seeded_dataset).train_variant == '9b'


def test_launch_flux2klein_coerces_foreign_variant_to_4b(ct, app, seeded_dataset, monkeypatch):
    import json as _json
    _fake_export(monkeypatch, ct)
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset,
                                 train_type='flux2klein', variant='turbo')
        run = ct.get_active_run()
        assert _json.loads(run.train_params)['variant'] == '4b'


def test_launch_without_key_raises(app, seeded_dataset, monkeypatch):
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    from app.services import cloud_training as ct
    with app.app_context():
        with pytest.raises(RuntimeError, match='key'):
            ct.launch_cloud_training('local', seeded_dataset)


def test_launch_creates_run_and_staging(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    with app.app_context():
        res = ct.launch_cloud_training('local', seeded_dataset)
        assert res['status'] == 'preparing'
        assert res['steps'] == 1200
        run = ct.get_active_run()
        assert run is not None and run.dataset_id == seeded_dataset
        assert run.vast_label == f"lds-{run.id}"
        assert run.job_name.startswith('lds')


def test_monitor_start_failure_discards_unstarted_provenance(
        ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    monkeypatch.setattr(
        ct, '_start_monitor',
        lambda run_id: (_ for _ in ()).throw(RuntimeError('thread unavailable')))
    with app.app_context():
        with pytest.raises(RuntimeError, match='thread unavailable'):
            ct.launch_cloud_training('local', seeded_dataset)
        run = ct.CloudTrainingRun.query.one()
        assert run.status == 'error'
        assert 'thread unavailable' in run.error
        assert ct.TrainingRunRecord.query.count() == 0
        params = json.loads(run.train_params or '{}')
        assert 'record_id' not in params and 'version' not in params


def test_monitor_thread_start_failure_removes_registry_entry(ct, app, monkeypatch):
    class BrokenThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError('thread unavailable')

    monkeypatch.setattr(ct.threading, 'Thread', BrokenThread)
    with pytest.raises(RuntimeError, match='thread unavailable'):
        ct._start_monitor_for_app(app, 42)
    assert 42 not in ct._monitor_threads


def test_staging_records_mask_generation_fallback(
        ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset, masked=True)
        run = ct.get_active_run()
        params = json.loads(run.train_params)
        assert params['masked'] is True
        assert params['record_id']

        ct._prepare_staging(run)

        from app.models import TrainingRunRecord
        record = ct.db.session.get(TrainingRunRecord, params['record_id'])
        params = json.loads(run.train_params)
        overrides = json.loads(record.overrides)
        assert params['masked'] is False
        assert record.masked is False
        assert overrides['masked'] is False
        assert overrides['masked_requested'] is True
        assert overrides['mask_fallback'] == 'generation_unavailable'


def test_cloud_run_config_is_frozen_at_launch(
        ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    with app.app_context():
        from app.services import face_dataset_service as fds
        ds = fds.get_dataset('local', seeded_dataset)
        ds.train_settings = json.dumps({'rank': 16, 'resolution': '768'})
        ct.db.session.commit()
        ct.launch_cloud_training(
            'local', seeded_dataset, train_type='krea', variant='base')
        run = ct.get_active_run()
        params = json.loads(run.train_params)

        ds.trigger_word = 'edited_later'
        ds.kind = 'style'
        ds.train_type = 'zimage'
        ds.train_variant = 'turbo'
        ds.train_settings = json.dumps({'rank': 64, 'resolution': '1024'})
        ct.db.session.commit()

        frozen = ct._run_config_dataset(ds, params)
        assert frozen.trigger_word == 'lola'
        assert frozen.kind == 'character'
        assert frozen.train_type == 'krea'
        assert frozen.train_variant == 'base'
        assert json.loads(frozen.train_settings)['rank'] == 16


def test_retry_reuses_frozen_snapshot_and_recipe_after_dataset_edits(
        ct, app, seeded_dataset, monkeypatch):
    """A modern retry is the same admitted run, not today's mutable dataset."""
    _fake_export(monkeypatch, ct)
    from app.services import training_snapshot
    monkeypatch.setattr(ct, '_capture_training_snapshot', training_snapshot.capture)
    with app.app_context():
        from app.models import FaceDatasetImage
        from app.services import face_dataset_service as fds
        ds = fds.get_dataset('local', seeded_dataset)
        ds.train_settings = json.dumps({'rank': 16, 'resolution': '768'})
        image_path = ct.cfg.dataset_images_root() / str(seeded_dataset) / 'kept.png'
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b'original admitted bytes')
        row = FaceDatasetImage(
            dataset_id=seeded_dataset, filename='kept.png', status='keep',
            caption='lola portrait', source='import')
        ct.db.session.add(row)
        ct.db.session.commit()

        first = ct.launch_cloud_training(
            'local', seeded_dataset, train_type='krea', variant='base')
        source = ct.db.session.get(ct.CloudTrainingRun, first['run_id'])
        source.status = 'error'
        source.finished_at = ct.utcnow()
        ds.trigger_word = 'edited_later'
        ds.train_settings = json.dumps({'rank': 64, 'resolution': '1024'})
        ds.train_base_model = 'local-only.safetensors'
        ds.train_vae_path = 'local-only-vae.safetensors'
        image_path.write_bytes(b'new mutable bytes')
        ct.db.session.commit()

        retried = ct.retry_cloud_run('local', source.id)
        new_run = ct.db.session.get(ct.CloudTrainingRun, retried['run_id'])
        params = json.loads(new_run.train_params)
        copied = training_snapshot.load(
            ct.Path(new_run.staging_dir) / 'snapshot')
        copied_path = training_snapshot.entry_path(
            ct.Path(new_run.staging_dir) / 'snapshot', copied['entries'][0])

        assert params['config_snapshot']['trigger_word'] == 'lola'
        assert json.loads(params['config_snapshot']['train_settings'])['rank'] == 16
        assert copied_path.read_bytes() == b'original admitted bytes'


def test_launch_refuses_second_active_run(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset)
        with pytest.raises(RuntimeError, match='already'):
            ct.launch_cloud_training('local', seeded_dataset)


def test_simultaneous_launches_reserve_only_one_active_slot(
        threaded_ct, threaded_app, monkeypatch):
    from types import SimpleNamespace

    import threading
    ct = threaded_ct
    app = threaded_app
    with app.test_client() as client:
        seeded_dataset = client.post(
            '/api/dataset/create',
            json={'name': 'Lola', 'trigger_word': 'lola'},
        ).get_json()['id']
    _fake_export(monkeypatch, ct)
    # Freeze the already-seeded row so only the admission critical section
    # performs database work concurrently.
    with app.app_context():
        ds = ct.fds.get_dataset('local', seeded_dataset)
        frozen_ds = SimpleNamespace(**{
            column.name: getattr(ds, column.name)
            for column in ds.__table__.columns
        })
    monkeypatch.setattr(ct.fds, 'get_dataset', lambda *_args, **_kwargs: frozen_ds)
    barrier = threading.Barrier(2)
    results = []
    results_lock = threading.Lock()

    def launch():
        barrier.wait()
        try:
            with app.app_context():
                value = ('ok', ct.launch_cloud_training('local', seeded_dataset))
        except Exception as exc:
            value = ('error', exc)
        with results_lock:
            results.append(value)

    threads = [threading.Thread(target=launch) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert [kind for kind, _value in results].count('ok') == 1
    errors = [value for kind, value in results if kind == 'error']
    assert len(errors) == 1 and 'already' in str(errors[0])


def test_launch_persists_family_and_variant(ct, app, seeded_dataset, monkeypatch):
    """The cloud dialog's family/variant must drive the ACTUAL training: the
    monitor builds the job config from the PERSISTED dataset values, so the
    launch has to persist them exactly like the local path does. Absent
    variant resolves to the family-aware default (Krea → Raw), never a
    hardcoded 'turbo'."""
    _fake_export(monkeypatch, ct)
    with app.app_context():
        from app.services import face_dataset_service as fds
        ct.launch_cloud_training('local', seeded_dataset, train_type='krea')
        ds = fds.get_dataset('local', seeded_dataset)
        assert ds.train_type == 'krea'
        assert ds.train_variant == 'base'


def test_launch_floors_explicit_steps(ct, app, seeded_dataset, monkeypatch):
    """Same floor as the local path — a sub-500 target would produce a run
    with zero usable snapshots."""
    _fake_export(monkeypatch, ct)
    with app.app_context():
        res = ct.launch_cloud_training('local', seeded_dataset, steps=100)
        assert res['steps'] == 500


def test_retry_relaunches_failed_run_with_same_params(ct, app, seeded_dataset, monkeypatch):
    """↻ Retry = a REAL launch with the failed run's persisted params — and the
    caption confirms don't re-block (the original launch already cleared them)."""
    import json as _json
    with app.app_context():
        from app.extensions import db
        from app.models import CloudTrainingRun
        run = CloudTrainingRun(dataset_id=seeded_dataset, status='error', run_name='x',
                               train_params=_json.dumps(
                                   {'steps': 2000, 'variant': 'base', 'train_type': 'krea',
                                    'masked': False, 'requested_gpu': 'RTX 5090'}))
        db.session.add(run)
        db.session.commit()
        captured = {}
        monkeypatch.setattr(ct, 'launch_cloud_training',
                            lambda user_id, dataset_id, **kw:
                            (captured.update(dataset_id=dataset_id, **kw), {'ok': True})[1])
        ct.retry_cloud_run('local', run.id)
    assert captured['dataset_id'] == seeded_dataset
    assert captured['steps'] == 2000 and captured['variant'] == 'base'
    assert captured['train_type'] == 'krea' and captured['masked'] is False
    assert captured['gpu_name'] == 'RTX 5090'
    assert captured['allow_caption_mismatch'] is True
    assert captured['allow_uncaptioned'] is True


def test_retry_refuses_modern_run_when_snapshot_is_missing(
        ct, app, seeded_dataset, tmp_path):
    with app.app_context():
        run = ct.CloudTrainingRun(
            dataset_id=seeded_dataset, status='error', run_name='x',
            staging_dir=str(tmp_path / 'cleaned'),
            train_params=json.dumps({'record_id': 123, 'train_type': 'zimage'}))
        ct.db.session.add(run)
        ct.db.session.commit()

        with pytest.raises(ValueError, match='verified training snapshot'):
            ct.retry_cloud_run('local', run.id)


def test_retry_refuses_non_error_or_unknown_run(ct, app, seeded_dataset):
    with app.app_context():
        from app.extensions import db
        from app.models import CloudTrainingRun
        run = CloudTrainingRun(dataset_id=seeded_dataset, status='done', run_name='y')
        db.session.add(run)
        db.session.commit()
        with pytest.raises(ValueError, match='failed run'):
            ct.retry_cloud_run('local', run.id)
        with pytest.raises(ValueError, match='unknown'):
            ct.retry_cloud_run('local', 999999)


def test_provision_registers_instance(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    monkeypatch.setattr(ct.vast_client, 'search_offers',
                        lambda **kw: [{'offer_id': 9, 'gpu_name': 'RTX 4090',
                                       'dph_total': 0.4, 'gpu_ram_gb': 24.0}])
    monkeypatch.setattr(ct.vast_client, 'create_instance', lambda *a, **kw: '777')
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset)
        run = ct.get_active_run()
        ct._provision(run)
        assert run.vast_instance_id == '777'
        assert run.price_per_hour == 0.4
        assert run.status == 'provisioning'
        # template mode: the auth token is vast's per-instance jupyter_token,
        # picked up during boot-wait -- empty right after provisioning
        assert run.auth_token == ''


def test_provision_no_offer_fails_cleanly(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    monkeypatch.setattr(ct.vast_client, 'search_offers', lambda **kw: [])
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset)
        run = ct.get_active_run()
        with pytest.raises(RuntimeError, match='offer'):
            ct._provision(run)


def test_provision_leak_safe_on_post_create_failure(ct, app, seeded_dataset, monkeypatch):
    """THE test: if anything fails after create_instance, the pod is destroyed."""
    _fake_export(monkeypatch, ct)
    destroyed = []
    monkeypatch.setattr(ct.vast_client, 'search_offers',
                        lambda **kw: [{'offer_id': 9, 'gpu_name': 'g', 'dph_total': 0.4,
                                       'gpu_ram_gb': 24.0}])
    monkeypatch.setattr(ct.vast_client, 'create_instance', lambda *a, **kw: '777')
    monkeypatch.setattr(ct.vast_client, 'destroy_instance',
                        lambda iid: destroyed.append(iid) or True)
    # make the post-create registration explode
    monkeypatch.setattr(ct, '_register_instance',
                        lambda run, iid, offer, token: (_ for _ in ()).throw(OSError('db gone')))
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset)
        run = ct.get_active_run()
        with pytest.raises(OSError):
            ct._provision(run)
        assert destroyed == ['777']


def test_reconcile_destroys_orphans_keeps_active(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    destroyed = []
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset)
        run = ct.get_active_run()
        run.vast_instance_id = '111'
        ct.db.session.commit()
        monkeypatch.setattr(ct.vast_client, 'list_instances', lambda: [
            {'instance_id': '111', 'label': f'lds-{run.id}'},   # active -> keep
            {'instance_id': '222', 'label': 'lds-99'},          # orphan -> destroy
            {'instance_id': '333', 'label': 'other-app'},       # not ours -> keep
        ])
        monkeypatch.setattr(ct.vast_client, 'destroy_instance',
                            lambda iid: destroyed.append(iid) or True)
        n = ct.reconcile_orphans(app)
        assert destroyed == ['222']
        assert n == 1


def test_reconcile_without_key_is_noop(app, monkeypatch):
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    from app.services import cloud_training as ct
    assert ct.reconcile_orphans(app) == 0


def test_reconcile_never_raises(ct, app, monkeypatch):
    """Boot must never be blocked: even an unexpected failure OUTSIDE the
    vast_client calls (db not ready, config error...) is swallowed and logged."""
    monkeypatch.setattr(ct.vast_client, 'list_instances', lambda: [])
    calls = []

    def broken_config(*args, **kwargs):
        calls.append(True)
        raise RuntimeError('config unreadable')

    monkeypatch.setattr(ct.cfg, 'get', broken_config)
    assert ct.reconcile_orphans(app) == 0      # swallowed, boot not blocked
    assert calls


def test_reconcile_spares_recent_error_pod_kept(ct, app, monkeypatch):
    """A run left in 'error_pod_kept' deliberately keeps its pod alive so the
    user can recover the checkpoint by hand. Within cloud.max_runtime_minutes
    of run.finished_at, reconciliation must NOT destroy that pod -- otherwise
    the manual-recovery window would never actually exist."""
    destroyed = []
    with app.app_context():
        run = ct.CloudTrainingRun(dataset_id=1, status='error_pod_kept',
                                  vast_instance_id='555', vast_label='lds-1',
                                  job_name='j', error='checkpoint download failed',
                                  finished_at=ct.utcnow() - timedelta(minutes=10))
        ct.db.session.add(run)
        ct.db.session.commit()
        monkeypatch.setattr(ct.vast_client, 'list_instances',
                            lambda: [{'instance_id': '555', 'label': f'lds-{run.id}'}])
        monkeypatch.setattr(ct.vast_client, 'destroy_instance',
                            lambda iid: destroyed.append(iid) or True)
        n = ct.reconcile_orphans(app)
        assert destroyed == []
        assert n == 0
        # reconcile_orphans() ran its own nested app_context/session; the
        # mock's list_instances lambda (referencing run.id) forced an
        # implicit refresh -- and therefore a pinned read snapshot -- on
        # THIS (outer) session mid-call. expire_all() drops that pinned
        # snapshot so the assertions below see what was actually committed,
        # not a transaction-start-time view.
        ct.db.session.expire_all()
        kept = ct.db.session.get(ct.CloudTrainingRun, run.id)
        assert kept.status == 'error_pod_kept'
        assert kept.error == 'checkpoint download failed'   # untouched


def test_reconcile_reaps_expired_error_pod_kept(ct, app, monkeypatch):
    """Past the recovery window, the kept pod IS destroyed like any other
    orphan, and the run is annotated -- but its terminal status must stay
    'error_pod_kept' (not flipped to something else)."""
    destroyed = []
    with app.app_context():
        run = ct.CloudTrainingRun(dataset_id=1, status='error_pod_kept',
                                  vast_instance_id='555', vast_label='lds-1',
                                  job_name='j', error='checkpoint download failed',
                                  finished_at=ct.utcnow() - timedelta(minutes=500))
        ct.db.session.add(run)
        ct.db.session.commit()
        monkeypatch.setattr(ct.vast_client, 'list_instances',
                            lambda: [{'instance_id': '555', 'label': f'lds-{run.id}'}])
        monkeypatch.setattr(ct.vast_client, 'destroy_instance',
                            lambda iid: destroyed.append(iid) or True)
        n = ct.reconcile_orphans(app)
        assert destroyed == ['555']
        assert n == 1
        # see the sibling test above for why expire_all() is needed here
        ct.db.session.expire_all()
        kept = ct.db.session.get(ct.CloudTrainingRun, run.id)
        assert kept.status == 'error_pod_kept'               # terminal stays terminal
        assert kept.error.startswith('checkpoint download failed')
        assert kept.error.endswith('pod reaped after the recovery window')
        assert kept.billing_ended_at is not None
        assert kept.auth_token is None


def test_reconcile_closes_billing_when_kept_pod_is_absent(ct, app, monkeypatch):
    """The kept pod may already be gone (destroyed by hand, or a previous
    reconcile pass).  It needs no destroy call, but the durable billing window
    must close so history does not claim it is charging forever."""
    with app.app_context():
        run = ct.CloudTrainingRun(dataset_id=1, status='error_pod_kept',
                                  vast_instance_id='555', vast_label='lds-1',
                                  job_name='j', error='checkpoint download failed',
                                  finished_at=ct.utcnow() - timedelta(minutes=500))
        ct.db.session.add(run)
        ct.db.session.commit()
        monkeypatch.setattr(ct.vast_client, 'list_instances', lambda: [])
        monkeypatch.setattr(ct.vast_client, 'destroy_instance',
                            lambda iid: (_ for _ in ()).throw(
                                AssertionError('nothing to destroy')))
        n = ct.reconcile_orphans(app)
        assert n == 0
        ct.db.session.expire_all()
        kept = ct.db.session.get(ct.CloudTrainingRun, run.id)
        assert kept.billing_ended_at is not None
        assert kept.error.endswith('provider instance is no longer active')


def test_failed_destroy_stays_active_and_billable_until_reconciled(
        ct, app, monkeypatch):
    with app.app_context():
        run = ct.CloudTrainingRun(
            dataset_id=1, status='training', vast_instance_id='555',
            vast_label='lds-1', job_name='j', price_per_hour=1.0,
            billing_started_at=ct.utcnow()
                               - timedelta(hours=1))
        ct.db.session.add(run)
        ct.db.session.commit()
        monkeypatch.setattr(ct.vast_client, 'destroy_instance', lambda _iid: False)

        assert ct._finish(run, 'done', detail='Training complete') is False
        assert run.status == 'terminating'
        assert run.finished_at is None
        assert run.billing_ended_at is None
        assert ct._run_payload(run)['cost_final'] is False

        monkeypatch.setattr(ct.vast_client, 'list_instances', lambda: [
            {'instance_id': '555', 'label': 'lds-1'},
        ])
        monkeypatch.setattr(ct.vast_client, 'destroy_instance', lambda _iid: True)
        assert ct.reconcile_orphans(app) == 1
        ct.db.session.expire_all()
        cleaned = ct.db.session.get(ct.CloudTrainingRun, run.id)
        assert cleaned.status == 'done'
        assert cleaned.billing_ended_at is not None
        assert cleaned.finished_at is not None


def test_request_stop_can_terminate_recovery_pod(ct, app, monkeypatch):
    with app.app_context():
        run = ct.CloudTrainingRun(
            dataset_id=1, status='error_pod_kept', vast_instance_id='555',
            vast_label='lds-1', job_name='j', error='download failed',
            billing_started_at=ct.utcnow(),
            finished_at=ct.utcnow())
        ct.db.session.add(run)
        ct.db.session.commit()
        monkeypatch.setattr(ct.vast_client, 'destroy_instance', lambda _iid: True)

        assert ct.request_stop(run.id) is True
        assert run.status == 'stopped'
        assert run.billing_ended_at is not None


def test_reconcile_keeps_active_and_spares_error_pod_kept_together(ct, app, monkeypatch):
    """One reconcile pass must apply both policies at once: keep the truly
    active run's pod, spare the still-recoverable error_pod_kept pod, and
    destroy the plain orphan."""
    destroyed = []
    with app.app_context():
        active = ct.CloudTrainingRun(dataset_id=1, status='training',
                                     vast_instance_id='111', vast_label='lds-1',
                                     job_name='j1')
        kept_run = ct.CloudTrainingRun(dataset_id=2, status='error_pod_kept',
                                       vast_instance_id='555', vast_label='lds-2',
                                       job_name='j2', error='checkpoint download failed',
                                       finished_at=ct.utcnow() - timedelta(minutes=10))
        ct.db.session.add_all([active, kept_run])
        ct.db.session.commit()
        active_id, kept_id = active.id, kept_run.id
        monkeypatch.setattr(ct.vast_client, 'list_instances', lambda: [
            {'instance_id': '111', 'label': f'lds-{active_id}'},   # active -> keep
            {'instance_id': '555', 'label': f'lds-{kept_id}'},     # recoverable -> spare
            {'instance_id': '222', 'label': 'lds-99'},             # orphan -> destroy
        ])
        monkeypatch.setattr(ct.vast_client, 'destroy_instance',
                            lambda iid: destroyed.append(iid) or True)
        n = ct.reconcile_orphans(app)
        assert destroyed == ['222']
        assert n == 1


def test_launch_respects_higher_concurrent_limit(ct, app, client, monkeypatch):
    """cloud.max_concurrent_runs=2 + 2 different datasets -> both launches
    succeed; a 3rd dataset trips the limit guard."""
    _fake_export(monkeypatch, ct)
    ct.cfg.save_config({'cloud': {'max_concurrent_runs': 2}})
    ds1 = client.post('/api/dataset/create',
                      json={'name': 'A', 'trigger_word': 'a'}).get_json()['id']
    ds2 = client.post('/api/dataset/create',
                      json={'name': 'B', 'trigger_word': 'b'}).get_json()['id']
    ds3 = client.post('/api/dataset/create',
                      json={'name': 'C', 'trigger_word': 'c'}).get_json()['id']
    with app.app_context():
        ct.launch_cloud_training('local', ds1)
        ct.launch_cloud_training('local', ds2)
        with pytest.raises(RuntimeError, match='limit reached'):
            ct.launch_cloud_training('local', ds3)


def test_launch_refuses_same_dataset_twice_even_with_higher_limit(ct, app, client, monkeypatch):
    """The per-(dataset, family) uniqueness guard is independent of the
    concurrency cap: even with room under the limit, the SAME dataset cannot
    get a 2nd run of the SAME family (both launches default to zimage here)."""
    _fake_export(monkeypatch, ct)
    ct.cfg.save_config({'cloud': {'max_concurrent_runs': 2}})
    ds1 = client.post('/api/dataset/create',
                      json={'name': 'A', 'trigger_word': 'a'}).get_json()['id']
    with app.app_context():
        ct.launch_cloud_training('local', ds1)
        with pytest.raises(RuntimeError, match='already has an active .*cloud run'):
            ct.launch_cloud_training('local', ds1)


def test_request_stop_targets_only_the_given_run(ct, app, client, monkeypatch):
    _fake_export(monkeypatch, ct)
    ct.cfg.save_config({'cloud': {'max_concurrent_runs': 2}})
    ds1 = client.post('/api/dataset/create',
                      json={'name': 'A', 'trigger_word': 'a'}).get_json()['id']
    ds2 = client.post('/api/dataset/create',
                      json={'name': 'B', 'trigger_word': 'b'}).get_json()['id']
    with app.app_context():
        r1 = ct.launch_cloud_training('local', ds1)
        r2 = ct.launch_cloud_training('local', ds2)
        assert ct.request_stop(r1['run_id']) is True
        assert ct._stop_event_for(r1['run_id']).is_set() is True
        assert ct._stop_event_for(r2['run_id']).is_set() is False


def test_reconcile_keeps_multiple_actives_destroys_orphan(ct, app, monkeypatch):
    """Multi-run keep-set: TWO genuinely active runs (different datasets, both
    with a pod) must both be spared; only the true orphan is destroyed."""
    destroyed = []
    with app.app_context():
        active1 = ct.CloudTrainingRun(dataset_id=1, status='training',
                                      vast_instance_id='111', vast_label='lds-1',
                                      job_name='j1')
        active2 = ct.CloudTrainingRun(dataset_id=2, status='uploading',
                                      vast_instance_id='222', vast_label='lds-2',
                                      job_name='j2')
        ct.db.session.add_all([active1, active2])
        ct.db.session.commit()
        a1_id, a2_id = active1.id, active2.id
        monkeypatch.setattr(ct.vast_client, 'list_instances', lambda: [
            {'instance_id': '111', 'label': f'lds-{a1_id}'},   # active -> keep
            {'instance_id': '222', 'label': f'lds-{a2_id}'},   # active -> keep
            {'instance_id': '333', 'label': 'lds-99'},         # orphan -> destroy
        ])
        monkeypatch.setattr(ct.vast_client, 'destroy_instance',
                            lambda iid: destroyed.append(iid) or True)
        n = ct.reconcile_orphans(app)
        assert destroyed == ['333']
        assert n == 1


def test_export_failure_in_monitor_frees_the_active_slot(ct, app, seeded_dataset, monkeypatch):
    """The dataset export now runs in the MONITOR thread (the launch click
    must return fast — rembg masks cost ~1-2 s/image). An export failure must
    not strand the 'preparing' row: the monitor flips it to 'error' so the
    active slot is freed for the next launch."""
    monkeypatch.setattr(ct.lt, 'assert_trainable', lambda *a, **kw: None)
    monkeypatch.setattr(ct.lt, 'default_steps', lambda ds: 100)
    monkeypatch.setattr(ct.lt, 'export_dataset_to_aitoolkit',
                        lambda *a, **kw: (_ for _ in ()).throw(OSError('disk full')))
    with app.app_context():
        res = ct.launch_cloud_training('local', seeded_dataset)   # returns fast
        assert res['status'] == 'preparing'
        ct._monitor(app, res['run_id'])                            # export blows here
        assert ct.get_active_run() is None        # slot freed
        run = ct.CloudTrainingRun.query.first()
        assert run.status == 'error' and 'disk full' in run.error


# --- Monthly budget guard: block LAUNCHES only, never kill a running pod ----

def _seed_finished_run(ct, price, start_h, end_h, dataset_id=999):
    """A terminal run UNAMBIGUOUSLY inside the current month: timestamps are
    anchored to the month start (created = month_start + start_h, finished =
    month_start + end_h), never to `now` — a now-relative seed run during the
    first UTC hours of the 1st would land in the PREVIOUS month and genuinely
    fail the spend assertions. cost = price x (end_h - start_h)."""
    now = ct.utcnow()
    month_start = datetime(now.year, now.month, 1)
    run = ct.CloudTrainingRun(
        dataset_id=dataset_id, status='done', job_name='j', vast_label='lds-9',
        price_per_hour=price,
        created_at=month_start + timedelta(hours=start_h),
        finished_at=month_start + timedelta(hours=end_h))
    ct.db.session.add(run)
    ct.db.session.commit()
    return run


def test_budget_zero_never_blocks_launch(ct, app, seeded_dataset, monkeypatch):
    """monthly_budget_usd=0 (the default) means unlimited: heavy spend this
    month must not block anything."""
    _fake_export(monkeypatch, ct)
    with app.app_context():
        _seed_finished_run(ct, price=2.0, start_h=0, end_h=19)   # 19 h x $2 = $38
        res = ct.launch_cloud_training('local', seeded_dataset)
        assert res['status'] == 'preparing'


def test_budget_reached_blocks_launch(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    ct.cfg.save_config({'cloud': {'monthly_budget_usd': 3}})
    with app.app_context():
        # 0.5 $/h x 8 h = $4 spent >= $3 budget
        _seed_finished_run(ct, price=0.5, start_h=0, end_h=8)
        with pytest.raises(RuntimeError, match='budget'):
            ct.launch_cloud_training('local', seeded_dataset)


def test_budget_ignores_previous_month_runs(ct, app, seeded_dataset, monkeypatch):
    """Only runs STARTED since the 1st of the current month (UTC) count."""
    _fake_export(monkeypatch, ct)
    ct.cfg.save_config({'cloud': {'monthly_budget_usd': 3}})
    with app.app_context():
        now = ct.utcnow()
        month_start = datetime(now.year, now.month, 1)
        run = ct.CloudTrainingRun(
            dataset_id=999, status='done', job_name='j', vast_label='lds-9',
            price_per_hour=10.0,                            # $240 — last month
            created_at=month_start - timedelta(days=5),
            finished_at=month_start - timedelta(days=4))
        ct.db.session.add(run)
        ct.db.session.commit()
        res = ct.launch_cloud_training('local', seeded_dataset)
        assert res['status'] == 'preparing'


def test_month_spend_prorates_a_run_crossing_the_month_boundary(ct, app, monkeypatch):
    with app.app_context():
        fixed_now = datetime(2026, 7, 10, 12, 0, 0)
        month_start = fixed_now.replace(day=1, hour=0, minute=0, second=0)
        monkeypatch.setattr(ct, 'utcnow', lambda: fixed_now)
        run = ct.CloudTrainingRun(
            dataset_id=999, status='done', job_name='boundary',
            price_per_hour=2.0,
            created_at=month_start - timedelta(hours=2),
            billing_started_at=month_start - timedelta(hours=2),
            billing_ended_at=month_start + timedelta(hours=3),
            finished_at=month_start + timedelta(hours=3))
        ct.db.session.add(run)
        ct.db.session.commit()

        assert ct.month_spend_usd() == 6.0


def test_old_finished_cleanup_pending_pod_counts_month_overlap_and_blocks_cap(
        ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    fixed_now = datetime(2026, 7, 1, 3, 0, 0)
    month_start = fixed_now.replace(hour=0, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(ct, 'utcnow', lambda: fixed_now)
    ct.cfg.save_config({'cloud': {'monthly_budget_usd': 2}})
    with app.app_context():
        run = ct.CloudTrainingRun(
            dataset_id=999, status='error_pod_kept', job_name='still-billing',
            vast_instance_id='123', price_per_hour=1.0,
            created_at=month_start - timedelta(days=2),
            billing_started_at=month_start - timedelta(hours=2),
            finished_at=month_start - timedelta(days=1),
            billing_ended_at=None)
        ct.db.session.add(run)
        ct.db.session.commit()

        assert ct.month_spend_usd() == 3.0
        with pytest.raises(RuntimeError, match='monthly cloud budget reached'):
            ct.launch_cloud_training('local', seeded_dataset)


def test_month_spend_query_excludes_old_terminal_history(ct, app, monkeypatch):
    with app.app_context():
        fixed_now = datetime(2026, 7, 10, 12, 0, 0)
        monkeypatch.setattr(ct, 'utcnow', lambda: fixed_now)
        old = ct.CloudTrainingRun(
            dataset_id=1, status='done', job_name='old', vast_label='lds-old',
            price_per_hour=1.0, created_at=datetime(2020, 1, 1),
            finished_at=datetime(2020, 1, 2))
        current = ct.CloudTrainingRun(
            dataset_id=2, status='done', job_name='current', vast_label='lds-current',
            price_per_hour=1.0, created_at=fixed_now - timedelta(hours=2),
            finished_at=fixed_now - timedelta(hours=1))
        ct.db.session.add_all([old, current])
        ct.db.session.commit()
        assert ct.month_spend_usd() == 1.0


def test_cloud_status_reports_month_spend_budget_and_cap(ct, app, monkeypatch):
    ct.cfg.save_config({'cloud': {'monthly_budget_usd': 20}})
    with app.app_context():
        # 0.5 $/h x 4 h = $2.00
        _seed_finished_run(ct, price=0.5, start_h=0, end_h=4)
        # a priced-less run (crashed before provisioning) must count for $0
        _seed_finished_run(ct, price=None, start_h=0, end_h=1, dataset_id=998)
        s = ct.cloud_status()
        assert s['monthly_budget'] == 20
        assert s['month_spend'] == 2.0
        assert s['max_runtime_minutes'] == 480


def test_run_payload_uses_exact_provider_billing_window(ct, app):
    """Provisioning delay before instance creation and post-destroy history
    must not inflate provider cost.  The payload exposes estimate-vs-final and
    separate billing/training durations for the UI and run comparison."""
    with app.app_context():
        base = datetime(2026, 7, 10, 12, 0, 0)
        run = ct.CloudTrainingRun(
            dataset_id=999, status='done', job_name='j', price_per_hour=0.6,
            created_at=base, billing_started_at=base + timedelta(minutes=10),
            training_started_at=base + timedelta(minutes=20),
            billing_ended_at=base + timedelta(minutes=50),
            finished_at=base + timedelta(minutes=50), estimated_minutes=25,
            estimated_cost_usd=0.3)
        ct.db.session.add(run)
        ct.db.session.commit()

        payload = ct._run_payload(run)

        assert payload['cost_usd'] == 0.4
        assert payload['cost_final'] is True
        assert payload['billing_seconds'] == 40 * 60
        assert payload['training_seconds'] == 30 * 60
        assert payload['estimated_minutes'] == 25
        assert payload['estimated_cost_usd'] == 0.3


def test_legacy_terminal_run_cost_stops_at_finished_time(ct, app):
    """Rows predating explicit billing timestamps retain a stable fallback
    cost instead of accumulating cost on every page refresh."""
    with app.app_context():
        base = datetime(2026, 7, 10, 12, 0, 0)
        run = ct.CloudTrainingRun(
            dataset_id=999, status='done', job_name='j', price_per_hour=0.5,
            created_at=base, finished_at=base + timedelta(hours=4))
        ct.db.session.add(run)
        ct.db.session.commit()

        payload = ct._run_payload(run)

        assert payload['cost_usd'] == 2.0
        assert payload['cost_final'] is True
        assert payload['billing_seconds'] == 4 * 60 * 60


# --- Per-(dataset, family) uniqueness: a zimage run and a krea run may share
# --- one dataset; two runs of the SAME family on one dataset may not. -------

def test_launch_allows_two_families_on_same_dataset(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    ct.cfg.save_config({'cloud': {'max_concurrent_runs': 2}})
    with app.app_context():
        r1 = ct.launch_cloud_training('local', seeded_dataset, train_type='zimage')
        r2 = ct.launch_cloud_training('local', seeded_dataset, train_type='krea')
        assert r1['run_id'] != r2['run_id']
        assert len(ct.get_active_runs()) == 2
        # The dataset row now reads krea — the SECOND launch was the last writer.
        from app.services import face_dataset_service as fds
        ds = fds.get_dataset('local', seeded_dataset)
        assert ds.train_type == 'krea'
        # Each run must still build ITS family's config from its stamped params,
        # not from the shared (now-krea) dataset row — the root of the 2026-07-14
        # parallel multi-family incident (the audit noted this test only checked
        # ids). Build through the real config path + the monitor's config view.
        run1 = ct.db.session.get(ct.CloudTrainingRun, r1['run_id'])
        run2 = ct.db.session.get(ct.CloudTrainingRun, r2['run_id'])
        cfg1 = ct.lt.build_job_config(
            ct._run_config_dataset(ds, json.loads(run1.train_params)),
            '/staging/ds', steps=500, training_folder='__POD__')
        cfg2 = ct.lt.build_job_config(
            ct._run_config_dataset(ds, json.loads(run2.train_params)),
            '/staging/ds', steps=500, training_folder='__POD__')
        assert cfg1['config']['process'][0]['model']['arch'] == 'zimage'
        assert cfg2['config']['process'][0]['model']['arch'] == 'krea2'


def test_launch_refuses_same_family_on_same_dataset(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    ct.cfg.save_config({'cloud': {'max_concurrent_runs': 2}})
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset, train_type='krea')
        with pytest.raises(RuntimeError, match='already has an active krea cloud run'):
            ct.launch_cloud_training('local', seeded_dataset, train_type='krea')


def test_run_family_non_dict_json_degrades_to_none(ct, app, seeded_dataset):
    """train_params containing valid-but-non-dict JSON must yield None, never
    raise — one corrupt row would 500 cloud_status platform-wide."""
    from app.models import CloudTrainingRun
    with app.app_context():
        for bad in ('"x"', '[1]', '3'):
            run = CloudTrainingRun(dataset_id=seeded_dataset, status='error',
                                   vast_label='lds-x', train_params=bad)
            assert ct._run_family(run) is None
            assert ct._run_payload(run)['train_type'] is None


def test_launch_family_unknown_active_run_blocks_every_family(ct, app, seeded_dataset, monkeypatch):
    """An active run with no train_params (pre-feature row, or the 'preparing'
    window before the params are stamped) has an unknown family — out of
    caution it must block launches of ANY family on that dataset."""
    _fake_export(monkeypatch, ct)
    ct.cfg.save_config({'cloud': {'max_concurrent_runs': 3}})
    with app.app_context():
        run = ct.CloudTrainingRun(dataset_id=seeded_dataset, status='training',
                                  vast_label='lds-1', job_name='j')   # train_params NULL
        ct.db.session.add(run)
        ct.db.session.commit()
        for fam in ('zimage', 'krea'):
            with pytest.raises(RuntimeError, match='already has an active'):
                ct.launch_cloud_training('local', seeded_dataset, train_type=fam)


def test_run_payload_carries_train_type(ct, app):
    with app.app_context():
        run = ct.CloudTrainingRun(
            dataset_id=1, status='training', job_name='j', vast_label='lds-1',
            train_params=json.dumps({'train_type': 'krea', 'steps': 100}))
        ct.db.session.add(run)
        # defensive: corrupted params -> None, never a crash
        bad = ct.CloudTrainingRun(dataset_id=2, status='training', job_name='j2',
                                  vast_label='lds-2', train_params='{not json')
        ct.db.session.add(bad)
        ct.db.session.commit()
        assert ct._run_payload(run)['train_type'] == 'krea'
        assert ct._run_payload(bad)['train_type'] is None


def test_run_payload_carries_dataset_name_and_run_name(ct, app, client):
    ds = client.post('/api/dataset/create',
                     json={'name': 'Lola', 'trigger_word': 'lola'}).get_json()['id']
    with app.app_context():
        run = ct.CloudTrainingRun(dataset_id=ds, status='training', job_name='j',
                                  vast_label='lds-1', run_name='lola_krea')
        ct.db.session.add(run)
        ct.db.session.commit()
        p = ct._run_payload(run)
        assert p['dataset_name'] == 'Lola' and p['run_name'] == 'lola_krea'
        # a since-deleted dataset degrades to None, never a crash
        orphan = ct.CloudTrainingRun(dataset_id=999999, status='training',
                                     job_name='j', vast_label='lds-2')
        ct.db.session.add(orphan)
        ct.db.session.commit()
        assert ct._run_payload(orphan)['dataset_name'] is None


def test_all_runs_splits_active_and_recent(ct, app):
    with app.app_context():
        active = ct.CloudTrainingRun(dataset_id=1, status='training',
                                     job_name='j', vast_label='lds-1',
                                     price_per_hour=0.4)
        done1 = ct.CloudTrainingRun(dataset_id=2, status='done', job_name='j',
                                    vast_label='lds-2')
        done2 = ct.CloudTrainingRun(dataset_id=3, status='error', job_name='j',
                                    vast_label='lds-3')
        ct.db.session.add_all([active, done1, done2])
        ct.db.session.commit()
        out = ct.all_runs()
        assert [r['status'] for r in out['actives']] == ['training']
        # terminal runs, newest first
        assert [r['run_id'] for r in out['recent']] == [done2.id, done1.id]
        assert out['total_price_per_hour'] == 0.4
        assert 'month_spend' in out and 'monthly_budget' in out


def test_all_runs_respects_limit(ct, app):
    with app.app_context():
        for i in range(5):
            ct.db.session.add(ct.CloudTrainingRun(
                dataset_id=i, status='done', job_name='j', vast_label=f'lds-{i}'))
        ct.db.session.commit()
        assert len(ct.all_runs(limit=3)['recent']) == 3


def test_all_runs_backfills_history_hidden_by_active_admissions(ct, app):
    with app.app_context():
        from app.models import TrainingRunRecord
        terminals = []
        for i in range(3):
            run = ct.CloudTrainingRun(
                dataset_id=100 + i, status='done', job_name=f'done-{i}',
                vast_label=f'lds-done-{i}')
            ct.db.session.add(run)
            ct.db.session.flush()
            terminals.append(run)
            ct.db.session.add(TrainingRunRecord(
                dataset_id=run.dataset_id, family='krea', source='cloud',
                cloud_run_id=run.id, fingerprint=f'f{i}', version=1))
        active = ct.CloudTrainingRun(
            dataset_id=200, status='training', job_name='active',
            vast_label='lds-active')
        ct.db.session.add(active)
        ct.db.session.flush()
        ct.db.session.add(TrainingRunRecord(
            dataset_id=active.dataset_id, family='krea', source='cloud',
            cloud_run_id=active.id, fingerprint='active', version=1))
        ct.db.session.commit()

        out = ct.all_runs(limit=3)
        assert [row['run_id'] for row in out['recent']] == [
            run.id for run in reversed(terminals)]


def test_all_runs_batch_loads_dataset_names(ct, app):
    from sqlalchemy import event
    from app.models import FaceDataset

    with app.app_context():
        datasets = [
            FaceDataset(user_id='local', name=f'Dataset {i}', trigger_word=f'ds{i}')
            for i in range(3)
        ]
        ct.db.session.add_all(datasets)
        ct.db.session.flush()
        ct.db.session.add_all([
            ct.CloudTrainingRun(dataset_id=dataset.id, status='done',
                                job_name=f'job-{i}', vast_label=f'lds-{i}')
            for i, dataset in enumerate(datasets)
        ])
        ct.db.session.commit()
        dataset_selects = []

        def count_dataset_selects(_conn, _cursor, statement, *_args):
            normalized = statement.lower()
            if normalized.lstrip().startswith('select') and 'face_dataset' in normalized:
                dataset_selects.append(statement)

        event.listen(ct.db.engine, 'before_cursor_execute', count_dataset_selects)
        try:
            out = ct.all_runs(limit=3)
        finally:
            event.remove(ct.db.engine, 'before_cursor_execute', count_dataset_selects)

        assert {row['dataset_name'] for row in out['recent']} == {
            'Dataset 0', 'Dataset 1', 'Dataset 2'}
        assert len(dataset_selects) == 1


def test_recovery_required_is_not_lost_to_history_pagination(ct, app):
    with app.app_context():
        kept = ct.CloudTrainingRun(dataset_id=1, status='error_pod_kept',
                                   job_name='kept', vast_label='lds-kept',
                                   vast_instance_id='instance-123')
        ct.db.session.add(kept)
        ct.db.session.flush()
        for i in range(20):
            ct.db.session.add(ct.CloudTrainingRun(
                dataset_id=i + 2, status='done', job_name=f'j-{i}',
                vast_label=f'lds-{i}'))
        ct.db.session.commit()
        assert kept.id not in {row['run_id'] for row in ct.all_runs(limit=3)['recent']}
        expected = [kept.id]
        assert [row['run_id'] for row in ct.all_runs(limit=3)['recovery_required']] == expected
        assert [row['run_id'] for row in ct.cloud_status()['recovery_required']] == expected


def test_legacy_terminal_billing_ends_at_finished_time_with_provider_id(ct, app):
    from datetime import timedelta
    with app.app_context():
        now = ct.utcnow()
        run = ct.CloudTrainingRun(
            dataset_id=1, status='done', job_name='legacy', vast_label='lds-old',
            vast_instance_id='historical-id', price_per_hour=1.0,
            created_at=now - timedelta(hours=5),
            finished_at=now - timedelta(hours=1))
        start, end, final = ct._billing_window(run)
        assert start == run.created_at
        assert end == run.finished_at
        assert final is True


# --- Offer quality layer: blacklist, price-bait exclusion, reliability pref ---

def test_filter_offers_drops_blacklisted_hosts(ct, app):
    with app.app_context():
        ct._blacklist_host(43503, 'never became ready',
                           run=ct.CloudTrainingRun(provider='vast'))
        offers = [
            {'offer_id': 1, 'gpu_name': 'RTX 3090', 'dph_total': 0.10, 'machine_id': 43503},
            {'offer_id': 2, 'gpu_name': 'RTX 3090', 'dph_total': 0.15, 'machine_id': 99},
        ]
        kept = ct._filter_offers(offers)
        assert [o['offer_id'] for o in kept] == [2]


def test_blacklist_expires_after_ttl(ct, app, monkeypatch):
    with app.app_context():
        ct._blacklist_host(43503, 'never became ready',
                           run=ct.CloudTrainingRun(provider='vast'))
        assert '43503' in ct._load_bad_hosts()
        # jump past the 3-day TTL
        real_now = ct._now()
        monkeypatch.setattr(ct, '_now', lambda: real_now + 4 * 86400)
        assert ct._load_bad_hosts() == {}


def test_filter_offers_drops_price_bait_in_large_class(ct, app):
    with app.app_context():
        offers = [   # median 0.30 -> floor 0.18; the 0.05 offer is bait
            {'offer_id': 1, 'gpu_name': 'RTX 5090', 'dph_total': 0.05, 'machine_id': 1},
            {'offer_id': 2, 'gpu_name': 'RTX 5090', 'dph_total': 0.30, 'machine_id': 2},
            {'offer_id': 3, 'gpu_name': 'RTX 5090', 'dph_total': 0.35, 'machine_id': 3},
        ]
        kept = ct._filter_offers(offers)
        assert [o['offer_id'] for o in kept] == [2, 3]


def test_filter_offers_keeps_small_class_and_falls_back(ct, app):
    with app.app_context():
        # 2 offers only -> no reliable median -> both kept, even the cheap one
        small = [
            {'offer_id': 1, 'gpu_name': 'H100', 'dph_total': 0.50, 'machine_id': 1},
            {'offer_id': 2, 'gpu_name': 'H100', 'dph_total': 2.00, 'machine_id': 2},
        ]
        assert len(ct._filter_offers(small)) == 2


def test_bad_host_file_ignores_malformed_timestamps(ct, app):
    with app.app_context():
        ct._bad_hosts_path().write_text(
            json.dumps({'broken': {'ts': 'not-a-number'},
                        'also-broken': 'wrong-shape'}), encoding='utf-8')
        assert ct._load_bad_hosts() == {}


def test_best_of_empty_group_has_actionable_error(ct, app):
    with app.app_context(), pytest.raises(RuntimeError, match='no eligible'):
        ct._best_of([])


def test_best_of_prefers_reliability_within_price_window(ct, app):
    with app.app_context():
        group = [
            {'offer_id': 1, 'dph_total': 0.100, 'reliability': 0.981},
            {'offer_id': 2, 'dph_total': 0.108, 'reliability': 0.999},  # +8% -> in window
            {'offer_id': 3, 'dph_total': 0.150, 'reliability': 1.0},    # +50% -> out
        ]
        assert ct._best_of(group)['offer_id'] == 2


def test_pick_offer_applies_best_of_to_requested_class(ct, app):
    with app.app_context():
        offers = [
            {'offer_id': 1, 'gpu_name': 'RTX 3090', 'dph_total': 0.10, 'reliability': 0.99},
            {'offer_id': 2, 'gpu_name': 'RTX 5090', 'dph_total': 0.60, 'reliability': 0.981},
            {'offer_id': 3, 'gpu_name': 'RTX 5090', 'dph_total': 0.64, 'reliability': 0.998},
        ]
        assert ct._pick_offer(offers, 'RTX 5090')['offer_id'] == 3


def test_provision_stamps_machine_id(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    monkeypatch.setattr(ct.vast_client, 'search_offers', lambda **kw: [
        {'offer_id': 9, 'gpu_name': 'RTX 4090', 'dph_total': 0.4,
         'gpu_ram_gb': 24.0, 'machine_id': 141481, 'reliability': 0.99}])
    monkeypatch.setattr(ct.vast_client, 'create_instance', lambda *a, **kw: '777')
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset)
        run = ct.get_active_run()
        ct._provision(run)
        assert json.loads(run.train_params)['machine_id'] == 141481


def test_provision_blocks_projected_budget_overrun_before_rental(
        ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    monkeypatch.setattr(ct.vast_client, 'search_offers', lambda **kw: [
        {'offer_id': 9, 'gpu_name': 'RTX 4090', 'dph_total': 1.0,
         'gpu_ram_gb': 24.0, 'machine_id': 141481, 'reliability': 0.99}])
    monkeypatch.setattr(ct.gpu_speed, 'estimate_minutes', lambda *args: 120)
    rentals = []
    monkeypatch.setattr(
        ct.vast_client, 'create_instance',
        lambda *args, **kwargs: rentals.append(args) or 'should-not-exist')
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset)
        run = ct.get_active_run()
        ct.cfg.save_config({'cloud': {'monthly_budget_usd': 1.0,
                                      'pod_overhead_minutes': 0}})

        with pytest.raises(RuntimeError, match='projected.*cap'):
            ct._provision(run)

        assert rentals == []
        assert run.vast_instance_id is None


def test_projected_budget_reservations_are_visible_to_concurrent_runs(
        ct, app, monkeypatch):
    monkeypatch.setattr(ct.gpu_speed, 'estimate_minutes', lambda *args: 120)
    with app.app_context():
        ct.cfg.save_config({'cloud': {'monthly_budget_usd': 3.0,
                                      'pod_overhead_minutes': 0}})
        first = ct.CloudTrainingRun(
            dataset_id=101, status='preparing', job_name='first', vast_label='first')
        second = ct.CloudTrainingRun(
            dataset_id=102, status='preparing', job_name='second', vast_label='second')
        ct.db.session.add_all((first, second))
        ct.db.session.commit()
        offer = {'gpu_name': 'RTX 4090', 'dph_total': 1.0}

        assert ct._assert_projected_budget(
            first, offer, 'zimage', {'steps': 3000}) == 2.0
        assert first.estimated_cost_usd == 2.0
        with pytest.raises(RuntimeError, match='projected.*cap'):
            ct._assert_projected_budget(
                second, offer, 'zimage', {'steps': 3000})

        assert second.estimated_cost_usd is None


# --- Launch-time GPU speed picker: requested_gpu is a preference, not a lock ---

def test_launch_stores_requested_gpu(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset, gpu_name='RTX 5090')
        run = ct.get_active_run()
        assert json.loads(run.train_params)['requested_gpu'] == 'RTX 5090'


def test_launch_without_gpu_name_omits_requested_gpu(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset)
        run = ct.get_active_run()
        assert 'requested_gpu' not in json.loads(run.train_params)


def test_pick_offer_prefers_requested_class_cheapest():
    from app.services import cloud_training as ct
    offers = [                                    # already cheapest-first
        {'offer_id': 1, 'gpu_name': 'RTX 3090', 'dph_total': 0.12},
        {'offer_id': 2, 'gpu_name': 'RTX 5090', 'dph_total': 0.60},
        {'offer_id': 3, 'gpu_name': 'RTX 5090', 'dph_total': 0.55},
    ]
    assert ct._pick_offer(offers, 'RTX 5090')['offer_id'] == 3   # cheapest 5090
    assert ct._pick_offer(offers, None)['offer_id'] == 1         # global cheapest


def test_pick_offer_falls_back_to_similar_tier_not_potato():
    """Requested class sold out -> an offer of a SIMILAR-OR-BETTER speed tier,
    never the global cheapest (a $0.13 RTX 3090 handed to a 12B Krea retry,
    user-reported: bottom-barrel hosts are the flaky ones, and ~3x slower)."""
    from app.services import cloud_training as ct
    offers = [
        {'offer_id': 1, 'gpu_name': 'RTX 3090', 'dph_total': 0.12},   # 1.0x — too slow
        {'offer_id': 2, 'gpu_name': 'RTX 5090', 'dph_total': 0.60},   # 2.8x ≈ 93% of 3.0
    ]
    # RTX PRO 6000 (3.0x) sold out -> the 5090 (similar tier), not the 3090
    assert ct._pick_offer(offers, 'RTX PRO 6000 S')['offer_id'] == 2
    # nothing similar on the market -> actionable error, never a downgrade
    only_potato = [{'offer_id': 1, 'gpu_name': 'RTX 3090', 'dph_total': 0.12}]
    with pytest.raises(RuntimeError, match='similar'):
        ct._pick_offer(only_potato, 'RTX PRO 6000 S')
    # no requested class at all -> global best (unchanged behaviour)
    assert ct._pick_offer(only_potato, None)['offer_id'] == 1


def test_provision_honors_requested_gpu(ct, app, seeded_dataset, monkeypatch):
    _fake_export(monkeypatch, ct)
    monkeypatch.setattr(ct.vast_client, 'search_offers', lambda **kw: [
        {'offer_id': 1, 'gpu_name': 'RTX 3090', 'dph_total': 0.12, 'gpu_ram_gb': 24.0},
        {'offer_id': 2, 'gpu_name': 'RTX 5090', 'dph_total': 0.60, 'gpu_ram_gb': 32.0},
    ])
    created = {}
    monkeypatch.setattr(ct.vast_client, 'create_instance',
                        lambda offer_id, **kw: created.setdefault('offer_id', offer_id) or '777')
    with app.app_context():
        ct.launch_cloud_training('local', seeded_dataset, gpu_name='RTX 5090')
        run = ct.get_active_run()
        ct._provision(run)
        assert created['offer_id'] == 2          # the 5090, not the cheaper 3090
        assert run.price_per_hour == 0.60


def _offers_multi():
    return [
        {'offer_id': 1, 'gpu_name': 'RTX 3090', 'dph_total': 0.13, 'gpu_ram_gb': 24.0},
        {'offer_id': 2, 'gpu_name': 'RTX 3090', 'dph_total': 0.18, 'gpu_ram_gb': 24.0},
        {'offer_id': 3, 'gpu_name': 'RTX 5090', 'dph_total': 0.69, 'gpu_ram_gb': 32.0},
        {'offer_id': 4, 'gpu_name': 'RTX 4090', 'dph_total': 0.35, 'gpu_ram_gb': 24.0},
    ]


def test_gpu_tiers_groups_ranks_and_estimates(ct, app, seeded_dataset, monkeypatch):
    monkeypatch.setattr(ct.lt, 'default_steps', lambda ds: 3000)
    monkeypatch.setattr(ct.vast_client, 'search_offers', lambda **kw: _offers_multi())
    with app.app_context():
        out = ct.gpu_tiers('local', seeded_dataset, train_type='krea')
        tiers = out['tiers']
        assert out['steps'] == 3000 and out['family'] == 'krea'
        # one tier per GPU class, cheapest offer of each class kept
        names = [t['gpu_name'] for t in tiers]
        assert names == ['RTX 3090', 'RTX 4090', 'RTX 5090']    # slowest -> fastest
        by_name = {t['gpu_name']: t for t in tiers}
        assert by_name['RTX 3090']['dph_total'] == 0.13         # cheapest 3090, not 0.18
        assert by_name['RTX 3090']['offer_id'] == 1
        # faster GPU -> fewer estimated minutes; every tier priced & timed
        assert by_name['RTX 5090']['est_minutes'] < by_name['RTX 3090']['est_minutes']
        assert all(t['est_cost'] is not None and t['est_minutes'] > 0 for t in tiers)


@pytest.mark.parametrize('requested', [-1, 0, 100, 499, 500])
def test_gpu_tiers_uses_launch_step_floor(
        ct, app, seeded_dataset, monkeypatch, requested):
    monkeypatch.setattr(ct.vast_client, 'search_offers', lambda **kw: _offers_multi())
    with app.app_context():
        out = ct.gpu_tiers('local', seeded_dataset, train_type='krea',
                           steps=requested)
    assert out['steps'] == 500


def test_gpu_tiers_uses_same_reliability_price_rule_as_provisioning(
        ct, app, seeded_dataset, monkeypatch):
    offers = [
        {'offer_id': 1, 'gpu_name': 'RTX 5090', 'dph_total': 0.60,
         'reliability': 0.98, 'gpu_ram_gb': 32.0},
        {'offer_id': 2, 'gpu_name': 'RTX 5090', 'dph_total': 0.64,
         'reliability': 0.999, 'gpu_ram_gb': 32.0},
    ]
    monkeypatch.setattr(ct.vast_client, 'search_offers', lambda **kw: offers)
    with app.app_context():
        tier = ct.gpu_tiers('local', seeded_dataset, train_type='krea')['tiers'][0]
    assert tier['offer_id'] == 2
    assert tier['dph_total'] == 0.64


def test_gpu_tiers_flags_tiers_slower_than_the_runtime_cap(ct, app, seeded_dataset, monkeypatch):
    """A 3090 doing 6000 krea steps (~15 h measured rate) blows the 8 h cap —
    the tier must say so BEFORE the user rents it; a 5090 fits."""
    monkeypatch.setattr(ct.lt, 'default_steps', lambda ds: 6000)
    monkeypatch.setattr(ct.vast_client, 'search_offers', lambda **kw: [
        {'offer_id': 1, 'gpu_name': 'RTX 3090', 'dph_total': 0.13, 'gpu_ram_gb': 24.0},
        {'offer_id': 3, 'gpu_name': 'RTX 5090', 'dph_total': 0.69, 'gpu_ram_gb': 32.0},
    ])
    with app.app_context():
        out = ct.gpu_tiers('local', seeded_dataset, train_type='krea')
        by_name = {t['gpu_name']: t for t in out['tiers']}
        assert by_name['RTX 3090']['exceeds_cap'] is True
        assert by_name['RTX 5090']['exceeds_cap'] is False
        assert out['max_runtime_minutes'] == 480


def test_gpu_tiers_requires_key(app, seeded_dataset, monkeypatch):
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    from app.services import cloud_training as ct
    with app.app_context():
        with pytest.raises(RuntimeError, match='key'):
            ct.gpu_tiers('local', seeded_dataset)


def test_gpu_tiers_rejects_sdxl(ct, app, seeded_dataset):
    with app.app_context():
        with pytest.raises(ValueError, match='SDXL'):
            ct.gpu_tiers('local', seeded_dataset, train_type='sdxl')


# --- Continue in cloud: resume a finished run from its last checkpoint --------

def _seed_done_run(ct, dataset_id, staging, steps=750, ckpt_name='lds1_x_000000750.safetensors',
                   **params):
    """A 'done' cloud run whose staging holds a harvested checkpoint."""
    p = {'steps': steps, 'variant': 'turbo', 'train_type': 'zimage', 'masked': True}
    p.update(params)
    run = ct.CloudTrainingRun(
        dataset_id=dataset_id, status='done', job_name='lds1_x',
        vast_label='lds-1', staging_dir=str(staging), train_params=json.dumps(p))
    ct.db.session.add(run)
    ct.db.session.commit()
    if ckpt_name:
        (staging / ckpt_name).write_bytes(b'weights')
    return run


def test_continue_from_done_calls_launch_with_resume_params(ct, app, seeded_dataset,
                                                            monkeypatch, tmp_path):
    """▶ Continue = a REAL launch with the source run's persisted params, steps =
    last_checkpoint_step + extra, and the checkpoint marked for deposit on the pod
    (resume_ckpt_path / resume_step in the new run's params)."""
    staging = tmp_path / 'run_src'
    staging.mkdir()
    with app.app_context():
        src = _seed_done_run(ct, seeded_dataset, staging, steps=750,
                             variant='base', train_type='krea', masked=False,
                             requested_gpu='RTX 5090')
        ckpt = staging / 'lds1_x_000000750.safetensors'
        captured = {}
        monkeypatch.setattr(ct, 'launch_cloud_training',
                            lambda user_id, dataset_id, **kw:
                            (captured.update(dataset_id=dataset_id, **kw), {'ok': True})[1])
        res = ct.continue_cloud_run('local', src.id, extra_steps=500)
    assert captured['dataset_id'] == seeded_dataset
    assert captured['steps'] == 1250                       # 750 + 500
    assert captured['resume_ckpt_path'] == str(ckpt)
    assert captured['resume_step'] == 750
    assert captured['variant'] == 'base' and captured['train_type'] == 'krea'
    assert captured['masked'] is False and captured['gpu_name'] == 'RTX 5090'
    assert captured['allow_caption_mismatch'] is True
    assert res['resumed_from'] == 750 and res['target_steps'] == 1250


def test_continue_refuses_non_done_run(ct, app, seeded_dataset, tmp_path):
    staging = tmp_path / 'run_src'
    staging.mkdir()
    with app.app_context():
        for status in ('training', 'error', 'stopped'):
            run = _seed_done_run(ct, seeded_dataset, staging)
            run.status = status
            ct.db.session.commit()
            with pytest.raises(ValueError, match='done'):
                ct.continue_cloud_run('local', run.id)
        with pytest.raises(ValueError, match='unknown'):
            ct.continue_cloud_run('local', 999999)


def test_continue_without_checkpoint_errors_actionably(ct, app, seeded_dataset, tmp_path):
    """A done run whose staging was cleaned (no .safetensors) — or has no staging
    at all — must fail with an actionable message, never launch a fresh run that
    silently trains from scratch."""
    empty = tmp_path / 'run_empty'
    empty.mkdir()
    with app.app_context():
        run = _seed_done_run(ct, seeded_dataset, empty, ckpt_name=None)
        with pytest.raises(ValueError, match='harvested checkpoint'):
            ct.continue_cloud_run('local', run.id)
        run.staging_dir = None
        ct.db.session.commit()
        with pytest.raises(ValueError, match='harvested checkpoint'):
            ct.continue_cloud_run('local', run.id)


def test_continue_picks_highest_step_checkpoint(ct, app, seeded_dataset, monkeypatch, tmp_path):
    """Multiple harvested epochs -> resume from the MOST-trained one."""
    staging = tmp_path / 'run_src'
    staging.mkdir()
    with app.app_context():
        run = _seed_done_run(ct, seeded_dataset, staging, ckpt_name='lds1_x_000000500.safetensors')
        (staging / 'lds1_x_000001500.safetensors').write_bytes(b'w')
        (staging / 'lds1_x_000001000.safetensors').write_bytes(b'w')
        captured = {}
        monkeypatch.setattr(ct, 'launch_cloud_training',
                            lambda user_id, dataset_id, **kw:
                            (captured.update(**kw), {'ok': True})[1])
        ct.continue_cloud_run('local', run.id, extra_steps=1000)
    assert captured['resume_step'] == 1500 and captured['steps'] == 2500


class _FakeRemote:
    """Records the pod-driver calls the monitor makes, so a test can assert the
    seed happened between create_job and start_job."""
    def __init__(self, settings):
        self._settings = settings
        self.calls = []
        self.seeded = None

    def is_ready(self):
        return True

    def ensure_settings(self, hf_token=None):
        return self._settings

    def upload_dataset(self, name, folder):
        self.calls.append(('upload_dataset', name))
        return 1

    def seed_checkpoint(self, datasets_folder, dest_dir, remote_name, local_path):
        self.calls.append(('seed', remote_name))
        self.seeded = {'datasets_folder': datasets_folder, 'dest_dir': dest_dir,
                       'remote_name': remote_name, 'local_path': local_path}

    def create_job(self, name, job_config, gpu_ids='0'):
        self.calls.append(('create_job', name))
        return 'jid'

    def start_job(self, job_id, gpu_ids='0'):
        self.calls.append(('start_job', job_id))

    def stop_job(self, job_id):
        pass

    def get_job(self, job_id):
        return {'status': 'completed', 'info': '', 'step': 100}

    def get_log(self, job_id):
        return ''

    def get_samples(self, job_id):
        return []

    def list_files(self, job_id):
        return []


def test_continue_seeds_checkpoint_in_monitor_flow(ct, app, seeded_dataset,
                                                   monkeypatch, tmp_path):
    """End-to-end through the monitor: the harvested checkpoint is deposited on
    the pod (renamed to the NEW job's prefix, into <TRAINING_FOLDER>/<job>) AFTER
    create_job and BEFORE start_job — the ai-toolkit auto-resume contract."""
    _fake_export(monkeypatch, ct)
    src_staging = tmp_path / 'run_src'
    src_staging.mkdir()
    ckpt = src_staging / 'lds1_x_000000750.safetensors'
    ckpt.write_bytes(b'weights')
    fake = _FakeRemote({'TRAINING_FOLDER': '/root/ai-toolkit/output',
                        'DATASETS_FOLDER': '/root/ai-toolkit/datasets'})
    # network + pod driver fully mocked
    monkeypatch.setattr(ct.vast_client, 'search_offers',
                        lambda **kw: [{'offer_id': 9, 'gpu_name': 'RTX 4090',
                                       'dph_total': 0.4, 'gpu_ram_gb': 24.0}])
    monkeypatch.setattr(ct.vast_client, 'create_instance', lambda *a, **kw: '777')
    monkeypatch.setattr(ct.vast_client, 'get_instance',
                        lambda iid: {'jupyter_token': 'tok', 'actual_status': 'running',
                                     'ports': {'18675/tcp': [{}]}})
    monkeypatch.setattr(ct.vast_client, 'derive_base_url', lambda inst, port: 'http://pod')
    monkeypatch.setattr(ct.vast_client, 'destroy_instance', lambda iid: True)
    monkeypatch.setattr(ct, '_make_remote', lambda run: fake)
    monkeypatch.setattr(ct.lt, 'build_job_config', lambda *a, **kw: {'config': {'process': [{}]}})
    monkeypatch.setattr(ct, '_cloudify_job_config', lambda *a, **kw: {})
    monkeypatch.setattr(ct, '_try_download_checkpoint', lambda run, remote, **kw: True)
    monkeypatch.setattr(ct, '_download_intermediates', lambda run, remote: None)
    monkeypatch.setattr(ct, '_import_result', lambda run: None)
    monkeypatch.setattr(ct, '_mirror_into_local_run', lambda run: None)
    with app.app_context():
        src = _seed_done_run(ct, seeded_dataset, src_staging, ckpt_name=None)
        res = ct.continue_cloud_run('local', src.id, extra_steps=500)
        new_id = res['run_id']
        new_run = ct.db.session.get(ct.CloudTrainingRun, new_id)
        job_name = new_run.job_name
        ct._monitor(app, new_id)
        copied_resume = ct.Path(new_run.staging_dir) / 'resume' / ckpt.name
    assert fake.seeded is not None
    assert ct.Path(fake.seeded['local_path']) == copied_resume
    assert copied_resume.read_bytes() == b'weights'
    assert fake.seeded['remote_name'] == f'{job_name}_000000750.safetensors'
    assert fake.seeded['dest_dir'] == f'/root/ai-toolkit/output/{job_name}'
    # ordering: create_job -> seed -> start_job
    names = [c[0] for c in fake.calls]
    assert names.index('create_job') < names.index('seed') < names.index('start_job')


def test_gpu_tiers_flux2klein_open_and_uses_32gb_vram_floor(ct, app, seeded_dataset, monkeypatch):
    """The GPU picker is open for flux2klein (flux stays refused) and the offer
    search uses the family's min_vram_gb default of 32 — the 9B (32-48 GB) is
    the family's cloud lane, and a 32 GB pod trains the 4B fine too."""
    monkeypatch.setattr(ct.lt, 'default_steps', lambda ds: 1000)
    seen = {}
    monkeypatch.setattr(ct.vast_client, 'search_offers',
                        lambda **kw: seen.update(kw) or _offers_multi())
    with app.app_context():
        with pytest.raises(ValueError, match='local-only'):
            ct.gpu_tiers('local', seeded_dataset, train_type='flux')
        out = ct.gpu_tiers('local', seeded_dataset, train_type='flux2klein')
        assert out['family'] == 'flux2klein'
        assert seen['min_vram_gb'] == 32


def test_cloud_progress_selects_run_by_family(ct, app, seeded_dataset, tmp_path):
    with app.app_context():
        def seed(fam, step, sub):
            staging = tmp_path / sub
            staging.mkdir()
            (staging / 'training.log').write_text(
                f'{step}%|##        | {step}/100 loss: 0.02', encoding='utf-8')
            run = ct.CloudTrainingRun(
                dataset_id=seeded_dataset, status='training', job_name=f'j-{fam}',
                vast_label='lds-x', staging_dir=str(staging),
                train_params=json.dumps({'train_type': fam, 'steps': 100}))
            ct.db.session.add(run)
            ct.db.session.commit()
        seed('zimage', 30, 'run_z')
        seed('krea', 60, 'run_k')                        # newest
        assert ct.cloud_progress('local', seeded_dataset, train_type='zimage')['step'] == 30
        assert ct.cloud_progress('local', seeded_dataset, train_type='krea')['step'] == 60
        # no filter -> newest run (behavior unchanged)
        assert ct.cloud_progress('local', seeded_dataset)['step'] == 60
        # An explicitly different family must never bleed into this panel.
        assert ct.cloud_progress('local', seeded_dataset, train_type='sdxl')['step'] is None


@pytest.mark.parametrize('template', ['', 'template-1'])
def test_runpod_launch_auth(ct, app, seeded_dataset, monkeypatch, template):
    from app.services import runpod_client
    _fake_export(monkeypatch, ct)
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    monkeypatch.setenv('HF_TOKEN', 'hf-test')
    ct.cfg.save_config({'cloud': {
        'provider': 'runpod', 'image': 'ignored-vast-image',
        'onstart': 'ignored-vast-command', 'disk_gb': 91,
        'runpod': {'template_id': template, 'image': 'custom-runpod-image'}}})
    monkeypatch.setattr(runpod_client, 'search_offers', lambda **kw: [
        {'offer_id': 'RTX 4090', 'gpu_name': 'RTX 4090', 'dph_total': .4, 'gpu_ram_gb': 24}])
    seen = {}

    def create(*a, **kw):
        seen.update(kw)
        return 'pod-1'

    monkeypatch.setattr(runpod_client, 'create_instance', create)
    with app.app_context():
        result = ct.launch_cloud_training('local', seeded_dataset)
        assert result['provider'] == 'runpod'
        assert result['provider_label'] == 'RunPod'
        assert result['console_url'] == 'https://console.runpod.io/pods'
        run = ct.db.session.get(ct.CloudTrainingRun, result['run_id'])
        assert run.provider == 'runpod'
        ct._provision(run)
        assert run.auth_token and seen['env']['AI_TOOLKIT_AUTH'] == run.auth_token
        assert seen['env']['HF_TOKEN'] == 'hf-test'
        assert seen['template_hash'] == (template or None)
        assert seen['image'] == 'custom-runpod-image'
        assert seen['onstart'] is None
        assert seen['disk_gb'] == 91
        payload = ct._run_payload(run)
        assert payload['provider_label'] == 'RunPod'
        assert payload['console_url'] == 'https://console.runpod.io/pods/pod-1'
        ct._blacklist_host('host', 'failed', run=run)
        assert 'host' not in ct._load_bad_hosts()
        # A retry still belongs to RunPod after the selected provider changes.
        ct.cfg.save_config({'cloud': {'provider': 'vast'}})
        monkeypatch.setattr(ct, '_reusable_run_snapshot', lambda *a, **k: (None, None))
        calls = {}
        monkeypatch.setattr(ct, 'launch_cloud_training', lambda *a, **k: calls.update(k))
        ct._relaunch('local', run, {}, 500)
        assert calls['provider'] == 'runpod'


def test_reconcile_provider_id_collision(ct, app, monkeypatch):
    from app.services import runpod_client
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    destroyed = []
    listed = []
    for name, provider_client in [('vast', ct.vast_client), ('runpod', runpod_client)]:
        def instances(name=name):
            listed.append(name)
            return [{'instance_id': 'same', 'label': 'lds-1'}]
        monkeypatch.setattr(provider_client, 'list_instances', instances)
        monkeypatch.setattr(provider_client, 'destroy_instance',
                            lambda iid, name=name: destroyed.append((name, iid)) or True)
    with app.app_context():
        # Vast owns the active id; RunPod's terminal row must not overwrite it.
        ct.db.session.add_all([
            ct.CloudTrainingRun(dataset_id=1, provider='vast', status='training', vast_instance_id='same'),
            ct.CloudTrainingRun(dataset_id=2, provider='runpod', status='error', vast_instance_id='same')])
        ct.db.session.commit()
        assert ct.reconcile_orphans(app) == 1
        # Registry ordering is pinned explicitly in test_cloud_provider.py.
        assert listed == ['vast', 'runpod']
        assert destroyed == [('runpod', 'same')]


def test_status_any_provider_key(ct, app, monkeypatch):
    ct.cfg.save_config({'cloud': {'provider': 'runpod'}})
    monkeypatch.delenv('RUNPOD_API_KEY', raising=False)
    with app.app_context():
        for payload in (ct.cloud_status(), ct.all_runs()):
            assert payload['configured'] is True
            assert payload['selected_provider'] == {'name': 'runpod', 'label': 'RunPod', 'launch_ready': False}


def test_explicit_provider_checks_original_key(ct, app, seeded_dataset, monkeypatch):
    monkeypatch.delenv('RUNPOD_API_KEY', raising=False)
    with app.app_context():
        with pytest.raises(RuntimeError, match='RunPod API key'):
            ct.launch_cloud_training('local', seeded_dataset, provider='runpod')


def test_launch_unknown_provider_is_actionable(ct, app, seeded_dataset):
    with app.app_context(), pytest.raises(RuntimeError, match='^unknown cloud provider: bogus$'):
        ct.launch_cloud_training('local', seeded_dataset, provider='bogus')


@pytest.mark.parametrize('offers,blacklisted,message', [
    ([], False, 'no RunPod offer matches'),
    ([{'offer_id': 'gpu', 'gpu_name': 'RTX 4090', 'dph_total': .4}],
     True, 'all matching RunPod hosts are temporarily blacklisted'),
])
def test_runpod_offer_errors_name_provider(ct, app, monkeypatch, offers, blacklisted, message):
    from app.services import runpod_client
    monkeypatch.setattr(runpod_client, 'search_offers', lambda **kw: offers)
    if blacklisted:
        monkeypatch.setattr(ct, '_filter_offers', lambda offers: [])
    with app.app_context(), pytest.raises(RuntimeError, match=message):
        ct._provision(ct.CloudTrainingRun(provider='runpod', dataset_id=1))


def test_runpod_out_of_stock_marks_run_error(ct, app, seeded_dataset, monkeypatch):
    from app.services import runpod_client
    _fake_export(monkeypatch, ct)
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    monkeypatch.setattr(runpod_client, 'search_offers', lambda **kw: [
        {'offer_id': 'gpu', 'gpu_name': 'RTX 4090', 'dph_total': .4}])

    def no_capacity(*args, **kwargs):
        raise runpod_client.RunpodError(
            'no RunPod capacity for gpu right now — open the GPU picker and choose another tier')

    monkeypatch.setattr(runpod_client, 'create_instance', no_capacity)
    with app.app_context():
        result = ct.launch_cloud_training('local', seeded_dataset, provider='runpod')
        ct._monitor(app, result['run_id'])
        run = ct.db.session.get(ct.CloudTrainingRun, result['run_id'])
        assert run.status == 'error'
        assert 'open the GPU picker' in run.error
        assert run.vast_instance_id is None


def test_register_runpod_without_quoted_price(ct, app):
    with app.app_context():
        run = ct.CloudTrainingRun(provider='runpod', dataset_id=1)
        ct.db.session.add(run)
        ct.db.session.commit()
        ct._register_instance(run, 'pod', {'gpu_name': 'RTX 4090', 'dph_total': None}, 'token')
        assert run.vast_instance_id == 'pod'
        assert run.price_per_hour is None
        assert run.estimated_cost_usd is None
        assert run.estimated_minutes > 0


@pytest.mark.parametrize('machine_id', [None, 'host-7'])
def test_blacklist_run_host_preserves_vast_policy(ct, app, machine_id):
    with app.app_context():
        run = ct.CloudTrainingRun(provider='vast', train_params=json.dumps({'machine_id': machine_id}))
        ct._blacklist_run_host(run, 'boot failed')
        hosts = ct._load_bad_hosts()
        assert set(hosts) == ({'host-7'} if machine_id else set())
        if machine_id:
            assert hosts[machine_id]['reason'] == 'boot failed'


def test_blacklist_requires_run(ct):
    with pytest.raises(TypeError, match='run'):
        ct._blacklist_host('host', 'boot failed')


def test_best_of_empty_uses_provider_neutral_error(ct):
    with pytest.raises(RuntimeError, match='^no eligible cloud GPU offers remain$'):
        ct._best_of([])


def test_reconcile_runpod_only_ignores_non_training_pods(ct, app, monkeypatch):
    from app.services import runpod_client
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    monkeypatch.setattr(ct.vast_client, 'list_instances', lambda: pytest.fail('vast key is absent'))
    monkeypatch.setattr(runpod_client, 'list_instances', lambda: [
        {'instance_id': 'personal', 'label': 'my-pod'},
        {'instance_id': 'orphan', 'label': 'lds-orphan'}])
    destroyed = []
    monkeypatch.setattr(runpod_client, 'destroy_instance', lambda iid: destroyed.append(iid) or True)
    assert ct.reconcile_orphans(app) == 1
    assert destroyed == ['orphan']


def test_reconcile_legacy_null_provider_belongs_only_to_vast(ct, app, monkeypatch):
    from app.services import runpod_client
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    destroyed = []
    for name, client in [('vast', ct.vast_client), ('runpod', runpod_client)]:
        monkeypatch.setattr(client, 'list_instances', lambda: [
            {'instance_id': 'same', 'label': 'lds-legacy'}])
        monkeypatch.setattr(client, 'destroy_instance',
                            lambda iid, name=name: destroyed.append((name, iid)) or True)
    with app.app_context():
        run = ct.CloudTrainingRun(dataset_id=1, status='training', vast_instance_id='same')
        ct.db.session.add(run)
        ct.db.session.commit()
        run.provider = None
        ct.db.session.commit()
        assert ct.reconcile_orphans(app) == 1
        assert run.provider is None
        assert run.billing_ended_at is None
    assert destroyed == [('runpod', 'same')]


@pytest.mark.parametrize('age,reaped', [(10, False), (481, True), (None, True)])
def test_reconcile_runpod_recovery_window(ct, app, monkeypatch, age, reaped):
    from app.services import runpod_client
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    monkeypatch.setattr(runpod_client, 'list_instances', lambda: [
        {'instance_id': 'kept', 'label': 'lds-kept'}])
    destroyed = []
    monkeypatch.setattr(runpod_client, 'destroy_instance', lambda iid: destroyed.append(iid) or True)
    with app.app_context():
        run = ct.CloudTrainingRun(
            dataset_id=1, provider='runpod', status='error_pod_kept', vast_instance_id='kept',
            auth_token='token', error='download failed',
            billing_started_at=ct.utcnow() - timedelta(hours=10),
            finished_at=ct.utcnow() - timedelta(minutes=age) if age is not None else None)
        ct.db.session.add(run)
        ct.db.session.commit()
        assert ct.reconcile_orphans(app) == int(reaped)
        ct.db.session.refresh(run)
        assert run.status == 'error_pod_kept'
        assert destroyed == (['kept'] if reaped else [])
        assert ('reaped after the recovery window' in run.error) is reaped
        assert (run.billing_ended_at == ct.utcnow()) is reaped
        assert run.auth_token == (None if reaped else 'token')


def test_reconcile_runpod_vanished_billing_is_provider_scoped(ct, app, monkeypatch):
    from app.services import runpod_client
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    monkeypatch.setattr(runpod_client, 'list_instances', lambda: [])
    with app.app_context():
        runs = [ct.CloudTrainingRun(
            dataset_id=1, provider=provider, status='error_pod_kept', vast_instance_id='missing',
            billing_started_at=ct.utcnow() - timedelta(hours=1), auth_token='token')
            for provider in ('vast', 'runpod')]
        ct.db.session.add_all(runs)
        ct.db.session.commit()
        assert ct.reconcile_orphans(app) == 0
        for run in runs:
            ct.db.session.refresh(run)
        assert runs[0].billing_ended_at is None
        assert runs[0].auth_token == 'token'
        assert runs[1].billing_ended_at == ct.utcnow()
        assert runs[1].auth_token is None
        assert runs[1].error.endswith('provider instance is no longer active')


def test_reconcile_continues_after_first_provider_list_failure(ct, app, monkeypatch):
    from app.services import runpod_client
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')

    def fail_list():
        raise ct.vast_client.VastError('offline')

    monkeypatch.setattr(ct.vast_client, 'list_instances', fail_list)
    monkeypatch.setattr(runpod_client, 'list_instances', lambda: [
        {'instance_id': 'orphan', 'label': 'lds-orphan'}])
    destroyed = []
    monkeypatch.setattr(runpod_client, 'destroy_instance', lambda iid: destroyed.append(iid) or True)
    assert ct.reconcile_orphans(app) == 1
    assert destroyed == ['orphan']


@pytest.mark.parametrize('with_key', [True, False])
def test_status_runpod_selected_readiness(ct, app, monkeypatch, with_key):
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    monkeypatch.delenv('RUNPOD_API_KEY', raising=False)
    if with_key:
        monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    ct.cfg.save_config({'cloud': {'provider': 'runpod'}})
    with app.app_context():
        for payload in (ct.cloud_status(), ct.all_runs()):
            assert payload['configured'] is with_key
            assert payload['selected_provider'] == {
                'name': 'runpod', 'label': 'RunPod', 'launch_ready': with_key}


@pytest.mark.parametrize('provider,instance_id,url', [
    ('runpod', None, 'https://console.runpod.io/pods'),
    ('vast', '123', 'https://cloud.vast.ai/instances/'),
])
def test_run_payload_console_url(ct, app, provider, instance_id, url):
    with app.app_context():
        run = ct.CloudTrainingRun(dataset_id=1, provider=provider, vast_instance_id=instance_id)
        assert ct._run_payload(run)['console_url'] == url


def test_runpod_gpu_tiers_preserve_catalogue_classes_and_unknown_prices(
        ct, app, seeded_dataset, monkeypatch):
    from app.services import runpod_client
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    ct.cfg.save_config({'cloud': {'provider': 'runpod', 'max_runtime_minutes': 480}})
    offers = [
        {'offer_id': 'unknown', 'gpu_name': 'unpriced', 'dph_total': None},
        {'offer_id': 'slow', 'gpu_name': 'slow', 'dph_total': .2},
        {'offer_id': 'fast', 'gpu_name': 'fast', 'dph_total': .7},
    ]
    for offer in offers:
        offer.update(machine_id=None, reliability=None, gpu_ram_gb=24)
    monkeypatch.setattr(runpod_client, 'search_offers', lambda **kw: offers)
    monkeypatch.setattr(ct.gpu_speed, 'speed_factor', lambda name: 1)
    monkeypatch.setattr(ct.gpu_speed, 'estimate_minutes',
                        lambda name, *args: 500 if name == 'slow' else 30)
    with app.app_context():
        tiers = ct.gpu_tiers('local', seeded_dataset)['tiers']
    assert [tier['offer_id'] for tier in tiers] == ['slow', 'fast', 'unknown']
    assert tiers[0]['exceeds_cap'] is True
    assert tiers[1]['exceeds_cap'] is False
    assert tiers[1]['est_cost'] > 0
    assert tiers[2]['dph_total'] is None
    assert tiers[2]['est_cost'] is None


def test_runpod_gpu_tiers_require_selected_key(ct, app, seeded_dataset, monkeypatch):
    monkeypatch.delenv('RUNPOD_API_KEY', raising=False)
    ct.cfg.save_config({'cloud': {'provider': 'runpod'}})
    with app.app_context(), pytest.raises(RuntimeError, match='RunPod API key is not configured'):
        ct.gpu_tiers('local', seeded_dataset)


def test_reconcile_kept_run_destroy_exception_keeps_billing_open(ct, app, monkeypatch, caplog):
    from app.services import runpod_client
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    monkeypatch.setattr(runpod_client, 'list_instances', lambda: [
        {'instance_id': 'kept', 'label': 'lds-kept'}])

    def fail_destroy(iid):
        raise runpod_client.RunpodError('temporarily unreachable')

    monkeypatch.setattr(runpod_client, 'destroy_instance', fail_destroy)
    with app.app_context():
        run = ct.CloudTrainingRun(
            dataset_id=1, provider='runpod', status='error_pod_kept',
            vast_instance_id='kept', auth_token='token', error='download failed',
            finished_at=ct.utcnow() - timedelta(minutes=500))
        ct.db.session.add(run)
        ct.db.session.commit()
        assert ct.reconcile_orphans(app) == 0
        ct.db.session.refresh(run)
        assert run.status == 'error_pod_kept'
        assert run.billing_ended_at is None
        assert run.auth_token == 'token'
        assert run.error == 'download failed'
        assert 'destroy kept failed: temporarily unreachable' in caplog.text


def test_reconcile_vanished_runpod_completes_pending_cleanup(ct, app, monkeypatch):
    from app.services import runpod_client
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    monkeypatch.setattr(runpod_client, 'list_instances', lambda: [])
    with app.app_context():
        run = ct.CloudTrainingRun(
            dataset_id=1, provider='runpod', status='training',
            vast_instance_id='gone', auth_token='token',
            billing_started_at=ct.utcnow() - timedelta(minutes=10))
        ct.db.session.add(run)
        ct.db.session.commit()
        ct._mark_cleanup_pending(run, 'stopped', 'user stopped', None)
        assert ct.reconcile_orphans(app) == 0
        ct.db.session.refresh(run)
        assert run.status == 'stopped'
        assert run.phase_detail == 'user stopped'
        assert run.billing_ended_at == ct.utcnow()
        assert run.finished_at == ct.utcnow()
        assert run.auth_token is None
