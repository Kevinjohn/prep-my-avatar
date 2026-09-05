"""Boot recovery: orphan reconciliation + resuming the monitor of a run that
was active when the app was closed."""


def test_boot_recover_resumes_active_run(app, monkeypatch):
    monkeypatch.setenv('VAST_API_KEY', 'k-test')
    from app.services import cloud_training as ct
    from app.extensions import db
    from app.models import CloudTrainingRun
    resumed = []
    monkeypatch.setattr(ct, 'reconcile_orphans', lambda a: 0)
    monkeypatch.setattr(ct, '_start_monitor_for_app',
                        lambda app_, run_id: resumed.append(run_id))
    with app.app_context():
        run = CloudTrainingRun(dataset_id=1, status='training',
                               vast_instance_id='777', vast_label='lds-1',
                               job_name='j', staging_dir='/tmp/x')
        db.session.add(run)
        db.session.commit()
        ct.boot_recover(app)
        assert resumed == [run.id]


def test_boot_recover_resumes_multiple_active_runs(app, monkeypatch):
    """Two runs active at once (both with a pod) — boot_recover must resume
    BOTH monitors, not just the first."""
    monkeypatch.setenv('VAST_API_KEY', 'k-test')
    from app.services import cloud_training as ct
    from app.extensions import db
    from app.models import CloudTrainingRun
    resumed = []
    monkeypatch.setattr(ct, 'reconcile_orphans', lambda a: 0)
    monkeypatch.setattr(ct, '_start_monitor_for_app',
                        lambda app_, run_id: resumed.append(run_id))
    with app.app_context():
        run1 = CloudTrainingRun(dataset_id=1, status='training',
                                vast_instance_id='777', vast_label='lds-1',
                                job_name='j1', staging_dir='/tmp/x')
        run2 = CloudTrainingRun(dataset_id=2, status='uploading',
                                vast_instance_id='888', vast_label='lds-2',
                                job_name='j2', staging_dir='/tmp/y')
        db.session.add_all([run1, run2])
        db.session.commit()
        ct.boot_recover(app)
        assert sorted(resumed) == sorted([run1.id, run2.id])


def test_boot_recover_fails_instanceless_active_run(app, monkeypatch):
    monkeypatch.setenv('VAST_API_KEY', 'k-test')
    from app.services import cloud_training as ct
    from app.extensions import db
    from app.models import CloudTrainingRun
    monkeypatch.setattr(ct, 'reconcile_orphans', lambda a: 0)
    with app.app_context():
        run = CloudTrainingRun(dataset_id=1, status='preparing',
                               vast_label='lds-1', job_name='j')
        db.session.add(run)
        db.session.commit()
        ct.boot_recover(app)
        assert db.session.get(CloudTrainingRun, run.id).status == 'error'


def test_boot_recover_without_key_is_silent(app, monkeypatch):
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    from app.services import cloud_training as ct
    ct.boot_recover(app)          # must not raise


def test_recovery_retries_after_key_becomes_available(app, monkeypatch):
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    from app.services import cloud_training as ct
    from app.extensions import db
    from app.models import CloudTrainingRun
    resumed = []
    monkeypatch.setattr(ct, 'reconcile_orphans', lambda *a, **k: 0)
    monkeypatch.setattr(ct, '_start_monitor_for_app',
                        lambda app_, run_id: resumed.append(run_id))
    with app.app_context():
        run = CloudTrainingRun(dataset_id=1, status='training',
                               vast_instance_id='777', vast_label='lds-1',
                               job_name='j', staging_dir='/tmp/x')
        db.session.add(run)
        db.session.commit()
        ct.boot_recover(app)
        assert resumed == []
        monkeypatch.setenv('VAST_API_KEY', 'k-test')
        ct._recover_active_runs(app)
        assert resumed == [run.id]


def test_recovery_contains_per_run_failure(app, monkeypatch):
    monkeypatch.setenv('VAST_API_KEY', 'k-test')
    from app.services import cloud_training as ct
    from app.extensions import db
    from app.models import CloudTrainingRun
    resumed = []
    with app.app_context():
        runs = [CloudTrainingRun(dataset_id=i, status='training',
                                 vast_instance_id=str(i), vast_label=f'lds-{i}',
                                 job_name=f'j-{i}', staging_dir='/tmp/x')
                for i in (1, 2)]
        db.session.add_all(runs)
        db.session.commit()

        def start(_app, run_id):
            if run_id == runs[0].id:
                raise RuntimeError('thread failure')
            resumed.append(run_id)

        monkeypatch.setattr(ct, '_start_monitor_for_app', start)
        ct._recover_active_runs(app)
        assert resumed == [runs[1].id]


def test_recovery_checks_each_runs_provider(app, monkeypatch):
    from app.services import cloud_training as ct
    monkeypatch.delenv('VAST_API_KEY', raising=False)
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    resumed = []
    monkeypatch.setattr(ct, '_start_monitor_for_app', lambda app, iid: resumed.append(iid))
    with app.app_context():
        runs = [ct.CloudTrainingRun(dataset_id=i, provider=name, status='training',
                                    vast_instance_id=str(i))
                for i, name in enumerate(('vast', 'runpod'), 1)]
        ct.db.session.add_all(runs)
        ct.db.session.commit()
        ct._recover_active_runs(app)
        assert resumed == [runs[1].id]
