import pytest


def test_dataset_defaults_local_user(app):
    from app.extensions import db
    from app.models import FaceDataset
    with app.app_context():
        ds = FaceDataset(name='Lola', trigger_word='lola')
        db.session.add(ds)
        db.session.commit()
        assert ds.user_id == 'local'
        assert ds.id is not None

def test_image_fk_and_status_default(app):
    from app.extensions import db
    from app.models import FaceDataset, FaceDatasetImage
    with app.app_context():
        ds = FaceDataset(name='A', trigger_word='a')
        db.session.add(ds)
        db.session.commit()
        img = FaceDatasetImage(dataset_id=ds.id)
        db.session.add(img)
        db.session.commit()
        assert img.status == 'pending' and img.source == 'generated'


def test_studio_training_provenance_fk_and_deletion_semantics(app):
    import sqlalchemy as sa
    from app.extensions import db
    from app.models import FaceDataset, LoraTestImage, TrainingRunRecord

    with app.app_context():
        dataset = FaceDataset(name='Provenance', trigger_word='provenance')
        db.session.add(dataset)
        db.session.commit()
        run = TrainingRunRecord(
            dataset_id=dataset.id, family='zimage', source='local',
            fingerprint='fixture', version=1)
        db.session.add(run)
        db.session.commit()
        cell = LoraTestImage(
            dataset_id=dataset.id, checkpoint='zimage/run.safetensors',
            strength=1.0, training_run_record_id=run.id)
        db.session.add(cell)
        db.session.commit()

        db.session.add(LoraTestImage(
            dataset_id=dataset.id, checkpoint='zimage/missing.safetensors',
            strength=1.0, training_run_record_id=999999))
        with pytest.raises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.delete(run)
        db.session.commit()
        db.session.refresh(cell)
        assert cell.training_run_record_id is None

def test_queue_mixin_lifecycle(app):
    from app.extensions import db
    from app.models import ImageGenerationQueue
    with app.app_context():
        job = ImageGenerationQueue(job_id='j1', status='pending')
        db.session.add(job)
        db.session.commit()
        job.update_status('processing')
        assert job.started_at is not None and job.last_heartbeat is not None
        job.update_status('completed', result_filename='x.png')
        assert job.completed_at is not None and job.result_filename == 'x.png'


def test_queue_retry_clears_terminal_attempt_state(app):
    from app.models import ImageGenerationQueue
    from app.utils.time import utcnow
    with app.app_context():
        job = ImageGenerationQueue(
            job_id='retry', status='failed', error_message='boom',
            result_filename='old.png', comfyui_prompt_id='old-prompt',
            completed_at=utcnow())
        job.update_status('processing')
        assert job.error_message is None
        assert job.result_filename is None
        assert job.comfyui_prompt_id is None
        assert job.completed_at is None


def test_cloud_training_status_cannot_be_null(app):
    import sqlalchemy as sa
    from app.extensions import db
    from app.models import CloudTrainingRun
    with app.app_context():
        run = CloudTrainingRun(dataset_id=1)
        db.session.add(run)
        db.session.commit()
        run.status = None
        with pytest.raises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()

def test_system_state_upsert(app):
    from app.extensions import db
    from app.models import SystemState
    with app.app_context():
        db.session.merge(SystemState(key='k', value='"v"'))
        db.session.commit()
        assert db.session.get(SystemState, 'k').value == '"v"'

def test_image_generation_queue_to_dict_with_metadata(app):
    """Regression test: to_dict() and to_status_dict() require module-level json import."""
    from app.extensions import db
    from app.models import ImageGenerationQueue
    with app.app_context():
        job = ImageGenerationQueue(
            job_id='j2',
            status='pending',
            job_metadata='{"a": 1}'
        )
        db.session.add(job)
        db.session.commit()

        # Test to_dict() with metadata parsing
        d = job.to_dict()
        assert d['job_id'] == 'j2'
        assert d['status'] == 'pending'
        assert d['metadata'] == {'a': 1}

        # Test to_status_dict() with metadata parsing (would fail with NameError if json not imported)
        sd = job.to_status_dict()
        assert sd['job_id'] == 'j2'
        assert sd['status'] == 'pending'
        assert sd['metadata'] == {'a': 1}


@pytest.mark.parametrize('value', ['null', '1', '[]', '"text"', '{'])
def test_image_generation_queue_json_fields_require_objects(app, value):
    from app.models import ImageGenerationQueue
    with app.app_context():
        job = ImageGenerationQueue(job_id='scalar-json', status='pending',
                                   job_metadata=value, workflow_data=value)
        assert job.to_dict()['metadata'] == {}
        assert job.to_dict()['workflow_data'] == {}
        assert job.to_status_dict()['metadata'] == {}
