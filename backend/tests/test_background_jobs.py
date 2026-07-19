from app.extensions import db


def test_background_job_survives_memory_loss(app):
    from app.services import background_jobs
    with app.app_context():
        row = background_jobs.create('setup', 'masks', {'action': 'masks'})
        background_jobs.touch(row.id, log='downloading', progress={'pct': 25})
        saved_id = row.id
        db.session.remove()
        snap = background_jobs.snapshot(background_jobs.latest('setup', 'masks'))
        assert snap['job_id'] == saved_id
        assert snap['state'] == 'running'
        assert snap['log'] == ['downloading']
        assert snap['progress'] == {'pct': 25}


def test_create_or_get_deduplicates_active_jobs(app):
    from app.services import background_jobs
    with app.app_context():
        first, created = background_jobs.create_or_get(
            'setup', 'masks', {'action': 'masks'})
        second, duplicate_created = background_jobs.create_or_get(
            'setup', 'masks', {'action': 'different-payload'})
        assert created is True
        assert duplicate_created is False
        assert second.id == first.id
        assert background_jobs.latest('setup', 'masks').id == first.id


def test_background_result_cannot_spoof_authoritative_lifecycle_fields(app):
    from app.services import background_jobs
    with app.app_context():
        row = background_jobs.create('export', 'dataset-1')
        background_jobs.touch(row.id, state='done', result={
            'state': 'running', 'job_id': 'forged', 'artifact': 'ready',
        })
        snap = background_jobs.snapshot(background_jobs.get(row.id))
        assert snap['state'] == 'done'
        assert snap['job_id'] == row.id
        assert snap['artifact'] == 'ready'


def test_boot_recovery_closes_daemon_owned_jobs(app):
    from app.services import background_jobs
    with app.app_context():
        row = background_jobs.create('hf_publish', '7', {'repo_id': 'me/example'})
        assert background_jobs.recover_interrupted() == 1
        snap = background_jobs.snapshot(background_jobs.get(row.id))
        assert snap['state'] == 'interrupted'
        assert snap['error_code'] == 'process_restarted'
        assert 'remote state is unknown' in snap['error']


def test_terminal_background_job_cannot_be_resurrected(app):
    import pytest
    from app.services import background_jobs
    with app.app_context():
        row = background_jobs.create('setup', 'terminal')
        background_jobs.touch(row.id, state='done')
        with pytest.raises(RuntimeError, match='already terminal'):
            background_jobs.touch(row.id, state='running')
        assert background_jobs.get(row.id).state == 'done'


def test_terminal_background_job_result_and_log_are_immutable(app):
    import pytest
    from app.services import background_jobs
    with app.app_context():
        row = background_jobs.create('setup', 'terminal-payload')
        background_jobs.touch(
            row.id, state='done', result={'artifact': 'first'}, log='completed')
        with pytest.raises(RuntimeError, match='already terminal'):
            background_jobs.touch(
                row.id, state='done', result={'artifact': 'late'}, log='late worker')
        snap = background_jobs.snapshot(background_jobs.get(row.id))
        assert snap['artifact'] == 'first'
        assert snap['log'] == ['completed']


def test_setup_status_falls_back_to_durable_ledger(app):
    from app import setup_installer
    from app.services import background_jobs
    with app.app_context():
        row = background_jobs.create('setup', 'masks', {'action': 'masks'})
        background_jobs.touch(row.id, state='error', result={'returncode': -1},
                              error='interrupted', error_code='process_restarted')
        setup_installer._runs.pop('masks', None)
        status = setup_installer.status('masks')
        assert status['state'] == 'error'
        assert status['job_id'] == row.id
        assert status['error_code'] == 'process_restarted'


def test_api_generation_restart_recovery_is_explicit(app):
    from app.models import FaceDataset, FaceDatasetImage
    from app.services.face_dataset_service import recover_interrupted_api_generations
    with app.app_context():
        ds = FaceDataset(user_id='local', name='A', trigger_word='tok')
        db.session.add(ds)
        db.session.flush()
        interrupted = FaceDatasetImage(
            dataset_id=ds.id, source='generated', status='pending',
            generation_engine='nanobanana', klein_model='nanobanana')
        ordinary = FaceDatasetImage(
            dataset_id=ds.id, source='import', status='pending')
        db.session.add_all([interrupted, ordinary])
        db.session.commit()
        assert recover_interrupted_api_generations() == 1
        assert db.session.get(FaceDatasetImage, interrupted.id).status == 'failed'
        assert 'restarted' in db.session.get(FaceDatasetImage, interrupted.id).fail_reason
        assert db.session.get(FaceDatasetImage, ordinary.id).status == 'pending'
