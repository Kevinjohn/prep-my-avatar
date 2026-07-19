import os
import threading
import io
from pathlib import Path

import pytest
from PIL import Image


def test_trash_rejects_symlinks_and_overlapping_targets(app, tmp_path):
    from app.services import trash
    with app.app_context():
        folder = tmp_path / 'folder'
        folder.mkdir()
        child = folder / 'child.txt'
        child.write_text('data', encoding='utf-8')
        link = tmp_path / 'link'
        try:
            link.symlink_to(child)
        except (OSError, NotImplementedError):
            pytest.skip('symbolic links are unavailable')

        with pytest.raises(ValueError, match='symbolic links'):
            trash.send_paths_to_trash([link])
        with pytest.raises(ValueError, match='contain one another'):
            trash.send_paths_to_trash([folder, child])


def test_stored_bytes_and_metadata_are_private_and_restorable(app):
    from app.services import trash
    with app.app_context():
        entry = trash.store_bytes('record.json', b'{}', context='private')
        root = Path(entry['path'])
        assert trash.read_entry_file(entry['id'], 'record.json') == b'{}'
        if os.name != 'nt':
            assert root.stat().st_mode & 0o777 == 0o700
            assert (root / 'record.json').stat().st_mode & 0o777 == 0o600
            assert (root / '.trash.json').stat().st_mode & 0o777 == 0o600


def test_non_consuming_restore_can_be_rolled_back(app, tmp_path):
    from app.services import trash
    with app.app_context():
        original = tmp_path / 'recover.txt'
        original.write_text('recoverable', encoding='utf-8')
        entry = trash.send_paths_to_trash([original], context='transaction')

        restored = trash.restore_entry(entry['id'], consume=False)
        assert original.read_text(encoding='utf-8') == 'recoverable'
        trash.rollback_restored_entry(entry['id'], restored['metadata'])

        assert not original.exists()
        assert trash.read_entry_file(entry['id'], 'recover.txt') == b'recoverable'


def test_empty_trash_waits_for_application_transaction(app, tmp_path):
    from app.services import trash

    original = tmp_path / 'recover.txt'
    original.write_text('recoverable', encoding='utf-8')
    moved = threading.Event()
    release = threading.Event()
    empty_finished = threading.Event()

    @trash.serialized_transaction
    def move_then_roll_back():
        entry = trash.send_paths_to_trash([original], context='concurrent')
        moved.set()
        assert release.wait(2)
        trash.restore_entry(entry['id'])

    def empty():
        with app.app_context():
            trash.empty_trash()
        empty_finished.set()

    with app.app_context():
        mover = threading.Thread(target=move_then_roll_back)
        mover.start()
        assert moved.wait(2)
        emptier = threading.Thread(target=empty)
        emptier.start()
        assert not empty_finished.wait(0.1)
        release.set()
        mover.join(2)
        emptier.join(2)

    assert empty_finished.is_set()
    assert original.read_text(encoding='utf-8') == 'recoverable'


def test_empty_trash_hard_purges_image_tombstone_and_reports_actual_bytes(
        app, client):
    from app.config import LOCAL_USER
    from app.extensions import db
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as datasets

    with app.app_context():
        dataset = datasets.create_dataset(LOCAL_USER, 'Trash', 'trash')
        filename = 'discard.webp'
        path = Path(datasets._dataset_dir(dataset.id), filename)
        path.write_bytes(b'payload')
        image = FaceDatasetImage(
            dataset_id=dataset.id, filename=filename, source='import', status='keep')
        db.session.add(image)
        db.session.commit()
        image_id = image.id
        assert datasets.delete_image(LOCAL_USER, image_id)

    result = client.post('/api/trash/empty')
    assert result.status_code == 200
    payload = result.get_json()
    assert payload['freed_bytes'] >= len(b'payload')
    assert payload['failed'] == 0
    with app.app_context():
        assert db.session.get(FaceDatasetImage, image_id) is None


def test_trashed_image_cannot_be_recurated_before_restore(app):
    from app.config import LOCAL_USER
    from app.extensions import db
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as datasets
    from app.services import trash

    with app.app_context():
        dataset = datasets.create_dataset(LOCAL_USER, 'Restore status', 'restore_status')
        filename = 'recover.webp'
        path = Path(datasets._dataset_dir(dataset.id), filename)
        path.write_bytes(b'recoverable')
        image = FaceDatasetImage(
            dataset_id=dataset.id, filename=filename, source='import', status='keep')
        db.session.add(image)
        db.session.commit()
        image_id = image.id

        assert datasets.delete_image(LOCAL_USER, image_id)
        assert datasets.set_image_status(LOCAL_USER, image_id, 'keep') is False
        assert db.session.get(FaceDatasetImage, image_id).status == 'trashed'

        entry = next(item for item in trash.list_entries()
                     if item['kind'] == 'dataset_image'
                     and trash.entry_metadata(item['id']).get('image_id') == image_id)
        restored = datasets.restore_trashed_image(LOCAL_USER, entry['id'])
        assert restored.status == 'keep'
        assert path.read_bytes() == b'recoverable'


def test_empty_trash_hard_purges_dataset_graph_but_keeps_training_history(
        app, client):
    from app.config import LOCAL_USER
    from app.extensions import db
    from app.models import (CloudTrainingRun, FaceDataset, FaceDatasetImage,
                            LoraTestImage, TrainingRunRecord)
    from app.services import face_dataset_service as datasets

    output = io.BytesIO()
    Image.new('RGB', (16, 16), (20, 40, 60)).save(output, 'PNG')
    with app.app_context():
        dataset = datasets.create_dataset(LOCAL_USER, 'Whole dataset', 'whole')
        filename = 'kept.png'
        Path(datasets._dataset_dir(dataset.id), filename).write_bytes(output.getvalue())
        image = FaceDatasetImage(
            dataset_id=dataset.id, filename=filename, source='import', status='keep')
        studio = LoraTestImage(
            dataset_id=dataset.id, checkpoint='z image\\lora_whole.safetensors',
            strength=1.0, status='done')
        history = TrainingRunRecord(
            dataset_id=dataset.id, family='zimage', source='legacy',
            fingerprint='a' * 64, manifest='[]', version=1)
        cloud = CloudTrainingRun(dataset_id=dataset.id, status='done')
        db.session.add_all([image, studio, history, cloud])
        db.session.commit()
        dataset_id = dataset.id
        image_id, studio_id = image.id, studio.id
        history_id, cloud_id = history.id, cloud.id
        assert datasets.delete_dataset(LOCAL_USER, dataset_id)
        assert db.session.get(FaceDataset, dataset_id).trashed_at is not None

    response = client.post('/api/trash/empty')
    assert response.status_code == 200
    assert response.get_json()['failed'] == 0
    with app.app_context():
        assert db.session.get(FaceDataset, dataset_id) is None
        assert db.session.get(FaceDatasetImage, image_id) is None
        assert db.session.get(LoraTestImage, studio_id) is None
        assert db.session.get(TrainingRunRecord, history_id) is not None
        assert db.session.get(CloudTrainingRun, cloud_id) is not None
