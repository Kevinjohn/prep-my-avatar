"""Model-family access requirements must fail in webpage preflight, not after spawn."""

import pytest


@pytest.mark.parametrize(('family', 'label'), [
    ('krea', 'Krea 2'),
    ('flux', 'FLUX.1-dev'),
    ('flux2klein', 'FLUX.2 Klein'),
])
def test_gated_official_training_families_require_hugging_face_access(
        app, monkeypatch, family, label):
    from app.config import LOCAL_USER
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as datasets
    from app.services import lora_training

    monkeypatch.delenv('HF_TOKEN', raising=False)
    with app.app_context():
        dataset = datasets.create_dataset(
            LOCAL_USER, f'{family} gated', f'{family}_gated', train_type=family)
        datasets.db.session.add_all([
            FaceDatasetImage(
                dataset_id=dataset.id, status='keep', filename=f'{index}.webp',
                caption='a detailed portrait photograph with natural daylight')
            for index in range(20)
        ])
        datasets.db.session.commit()

        report = lora_training.training_preflight(
            LOCAL_USER, dataset.id, train_type=family)

        access = next(check for check in report['checks']
                      if check['id'] == 'hugging_face_access')
        assert report['verdict'] == 'blocked'
        assert access['status'] == 'fail'
        assert label in access['detail']
        assert 'display name is irrelevant' in access['detail']
