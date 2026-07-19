from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db


def _create(client):
    return client.post('/api/dataset/create',
                       json={'name': 'Integrity', 'trigger_word': 'integrity'}).get_json()['id']


def test_integrity_route_reports_clean_dataset(client):
    _create(client)
    report = client.get('/api/integrity').get_json()
    assert report['ok'] is True, report
    assert report['counts']['errors'] == 0
    assert report['counts']['datasets'] == 1


def test_integrity_reports_missing_referenced_file(client, app):
    dataset_id = _create(client)
    with app.app_context():
        from app.models import FaceDatasetImage
        row = FaceDatasetImage(dataset_id=dataset_id, source='import', status='keep',
                               filename='missing.webp')
        db.session.add(row)
        db.session.commit()
    report = client.get('/api/integrity').get_json()
    finding = next(item for item in report['findings']
                   if item['code'] == 'missing_referenced_file')
    assert report['ok'] is False
    assert finding['dataset_id'] == dataset_id
    assert finding['filename'] == 'missing.webp'


def test_integrity_reports_untracked_file_as_warning(client, app):
    dataset_id = _create(client)
    with app.app_context():
        from app import config as cfg
        folder = Path(cfg.dataset_images_root()) / str(dataset_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'orphan.webp').write_bytes(b'orphan')
    report = client.get('/api/integrity').get_json()
    assert report['ok'] is True
    assert any(item['code'] == 'untracked_dataset_file'
               and item['filename'] == 'orphan.webp' for item in report['findings'])


def test_integrity_accepts_nested_originals_and_ignores_trashed_image_files(client, app):
    dataset_id = _create(client)
    with app.app_context():
        from app import config as cfg
        from app.models import FaceDatasetImage
        folder = Path(cfg.dataset_images_root()) / str(dataset_id)
        originals = folder / 'originals'
        originals.mkdir(parents=True)
        (originals / 'source.png').write_bytes(b'original')
        (folder / 'active.webp').write_bytes(b'active')
        active = FaceDatasetImage(
            dataset_id=dataset_id, source='import', status='keep',
            filename='active.webp', original_filename='originals/source.png',
        )
        trashed = FaceDatasetImage(
            dataset_id=dataset_id, source='import', status='trashed',
            filename='moved.webp',
        )
        db.session.add_all([active, trashed])
        db.session.commit()
    report = client.get('/api/integrity').get_json()
    assert report['ok'] is True, report
    assert not any(item['code'] in {'unsafe_dataset_filename', 'missing_referenced_file'}
                   for item in report['findings'])
    assert not any(item['code'] == 'untracked_dataset_file'
                   and item.get('filename') == 'originals/source.png'
                   for item in report['findings'])


def test_integrity_reports_dangling_generation_anchor(client, app):
    dataset_id = _create(client)
    with app.app_context():
        from app.models import FaceDatasetImage
        row = FaceDatasetImage(dataset_id=dataset_id, source='generated', status='failed',
                               generation_anchor_ids='[8888]')
        db.session.add(row)
        db.session.commit()
    report = client.get('/api/integrity').get_json()
    codes = {item['code'] for item in report['findings']}
    assert 'dangling_generation_anchor' in codes


def test_integrity_reports_invalid_generation_anchor_value(client, app):
    dataset_id = _create(client)
    with app.app_context():
        from app.models import FaceDatasetImage
        row = FaceDatasetImage(
            dataset_id=dataset_id, source='generated', status='failed',
            generation_anchor_ids='[true, "12", 0]',
        )
        db.session.add(row)
        db.session.commit()

    report = client.get('/api/integrity').get_json()

    assert sum(item['code'] == 'invalid_generation_anchor_id'
               for item in report['findings']) == 3


def test_database_guards_reject_invalid_status_and_cross_dataset_links(client, app):
    first = _create(client)
    second = client.post('/api/dataset/create',
                         json={'name': 'Other', 'trigger_word': 'other'}).get_json()['id']
    with app.app_context():
        from app.models import FaceDatasetImage
        parent = FaceDatasetImage(dataset_id=first, status='keep')
        db.session.add(parent)
        db.session.commit()

        db.session.add(FaceDatasetImage(dataset_id=first, status='invented'))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(FaceDatasetImage(
            dataset_id=second, status='pending', parent_image_id=parent.id))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_database_guards_reject_invalid_coverage_profile(client, app):
    dataset_id = _create(client)
    with app.app_context():
        from app.models import FaceDataset
        dataset = db.session.get(FaceDataset, dataset_id)
        dataset.coverage_profile = 'reckless'
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_integrity_reports_malformed_legacy_coverage_targets(client, app):
    dataset_id = _create(client)
    with app.app_context():
        from app.models import FaceDataset
        dataset = db.session.get(FaceDataset, dataset_id)
        dataset.coverage_targets = '[]'
        db.session.commit()

    report = client.get('/api/integrity').get_json()

    assert report['ok'] is True
    assert any(item['code'] == 'invalid_coverage_targets'
               and item['dataset_id'] == dataset_id
               for item in report['findings'])


def test_integrity_audits_other_structured_json_columns(client, app):
    dataset_id = _create(client)
    with app.app_context():
        from app.models import (BackgroundJob, CloudTrainingRun, FaceDataset,
                                FaceDatasetImage, TrainingPreset,
                                TrainingRunRecord)
        dataset = db.session.get(FaceDataset, dataset_id)
        dataset.train_settings = '[]'
        image = FaceDatasetImage(
            dataset_id=dataset_id, source='generated', status='failed',
            analysis_json='not-json', generation_anchor_metadata='{}',
            watermark_regions='[[0, 0, 2, 1]]', perceptual_hash='xyz')
        db.session.add_all([
            image,
            BackgroundJob(id='integrity-job', kind='test', dedupe_key='test',
                          payload='[]', log='{}'),
            CloudTrainingRun(dataset_id=dataset_id, status='done', train_params='[]'),
            TrainingRunRecord(
                dataset_id=dataset_id, family='zimage', source='legacy',
                fingerprint='a' * 64, manifest='{}', version=1),
            TrainingPreset(name='Broken JSON', train_type='zimage', settings='[]'),
        ])
        db.session.commit()

    codes = {item['code'] for item in client.get('/api/integrity').get_json()['findings']}
    assert {
        'invalid_train_settings', 'invalid_analysis_json',
        'invalid_generation_anchor_metadata', 'invalid_watermark_region',
        'invalid_perceptual_hash', 'invalid_background_job_payload',
        'invalid_background_job_log', 'invalid_cloud_train_params',
        'invalid_training_manifest', 'invalid_training_preset_settings',
    } <= codes
