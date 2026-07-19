import os

import pytest
from PIL import Image

from app.config import LOCAL_USER


def _seed(app, tmp_path, count=12):
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as fds
    dataset = fds.create_dataset(LOCAL_USER, 'Snapshot', 'snapshot')
    root = fds._dataset_dir(dataset.id)
    for index in range(count):
        filename = f'{index}.png'
        Image.new('RGB', (8, 8), (index, 20, 30)).save(os.path.join(root, filename))
        fds.db.session.add(FaceDatasetImage(
            dataset_id=dataset.id, filename=filename, status='keep',
            caption=f'caption before {index}', source='import'))
    fds.db.session.commit()
    return dataset


def test_snapshot_keeps_exact_bytes_and_captions_after_live_edits(app, tmp_path):
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as fds
    from app.services import lora_training as training
    from app.services import training_snapshot
    with app.app_context():
        dataset = _seed(app, tmp_path)
        snapshot_dir = tmp_path / 'snapshot'
        manifest = training_snapshot.capture(LOCAL_USER, dataset.id, snapshot_dir)
        assert manifest['dataset_revision'] == dataset.revision
        assert manifest['training_config']['train_type'] == 'zimage'
        assert len(manifest['entries'][0]['caption_sha256']) == 64
        assert len(manifest['registry_manifest'][0][1]) == 64
        first = fds.db.session.get(FaceDatasetImage, manifest['entries'][0]['image_id'])
        first.caption = 'caption after launch'
        Image.new('RGB', (8, 8), (255, 255, 255)).save(fds._img_path(first))
        fds.db.session.commit()

        output = tmp_path / 'materialized'
        training.export_dataset_to_aitoolkit(
            LOCAL_USER, dataset.id, masked=False, dest_dir=output,
            snapshot_dir=snapshot_dir)
        assert (output / 'snapshot_000.txt').read_text() == 'snapshot, caption before 0'
        with Image.open(output / 'snapshot_000.png') as image:
            assert image.getpixel((0, 0)) == (0, 20, 30)


def test_snapshot_detects_tampering(app, tmp_path):
    from app.services import training_snapshot
    with app.app_context():
        dataset = _seed(app, tmp_path)
        snapshot_dir = tmp_path / 'snapshot'
        manifest = training_snapshot.capture(LOCAL_USER, dataset.id, snapshot_dir)
        target = training_snapshot.entry_path(snapshot_dir, manifest['entries'][0])
        target.write_bytes(b'changed')
        with pytest.raises(ValueError, match='content check failed'):
            training_snapshot.load(snapshot_dir)


def test_snapshot_detects_caption_and_registry_tampering(app, tmp_path):
    import json
    from app.services import training_snapshot
    with app.app_context():
        dataset = _seed(app, tmp_path)
        snapshot_dir = tmp_path / 'snapshot'
        training_snapshot.capture(LOCAL_USER, dataset.id, snapshot_dir)
        manifest_path = snapshot_dir / training_snapshot.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['entries'][0]['caption'] = 'tampered caption'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

        with pytest.raises(ValueError, match='metadata check failed'):
            training_snapshot.load(snapshot_dir)

        manifest['entries'][0]['caption_sha256'] = training_snapshot._caption_hash(
            'tampered caption')
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with pytest.raises(ValueError, match='registry manifest is inconsistent'):
            training_snapshot.load(snapshot_dir)


def test_snapshot_rejects_non_object_manifest(app, tmp_path):
    from app.services import training_snapshot
    snapshot_dir = tmp_path / 'snapshot'
    snapshot_dir.mkdir()
    (snapshot_dir / training_snapshot.MANIFEST_NAME).write_text('[]', encoding='utf-8')
    with app.app_context(), pytest.raises(ValueError, match='missing or invalid'):
        training_snapshot.load(snapshot_dir)


def test_snapshot_rejects_symlinked_admitted_input(app, tmp_path):
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as fds
    from app.services import training_snapshot
    with app.app_context():
        dataset = _seed(app, tmp_path)
        row = FaceDatasetImage.query.filter_by(dataset_id=dataset.id).first()
        source = tmp_path / 'external.png'
        Image.new('RGB', (8, 8), (1, 2, 3)).save(source)
        image_path = fds._img_path(row)
        os.unlink(image_path)
        os.symlink(source, image_path)

        with pytest.raises(ValueError, match='unsafe path|missing on disk'):
            training_snapshot.capture(
                LOCAL_USER, dataset.id, tmp_path / 'symlink-snapshot')


def test_snapshot_destination_is_immutable(app, tmp_path):
    from app.services import training_snapshot
    with app.app_context():
        dataset = _seed(app, tmp_path)
        snapshot_dir = tmp_path / 'snapshot'
        training_snapshot.capture(LOCAL_USER, dataset.id, snapshot_dir)
        manifest_before = (snapshot_dir / training_snapshot.MANIFEST_NAME).read_bytes()
        with pytest.raises(FileExistsError, match='already exists'):
            training_snapshot.capture(LOCAL_USER, dataset.id, snapshot_dir)
        assert (snapshot_dir / training_snapshot.MANIFEST_NAME).read_bytes() == manifest_before


def test_snapshot_aborts_when_dataset_rows_change_during_capture(
        app, tmp_path, monkeypatch):
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as fds
    from app.services import training_snapshot
    with app.app_context():
        dataset = _seed(app, tmp_path)
        original_copy = training_snapshot.shutil.copy2
        changed = False

        def copy_and_edit(source, destination):
            nonlocal changed
            result = original_copy(source, destination)
            if not changed:
                changed = True
                row = (FaceDatasetImage.query.filter_by(dataset_id=dataset.id)
                       .order_by(FaceDatasetImage.id.desc()).first())
                row.caption = 'edited during snapshot'
                fds.db.session.commit()
            return result

        monkeypatch.setattr(training_snapshot.shutil, 'copy2', copy_and_edit)

        with pytest.raises(RuntimeError, match='dataset changed'):
            training_snapshot.capture(
                LOCAL_USER, dataset.id, tmp_path / 'racing-snapshot')
        assert not (tmp_path / 'racing-snapshot').exists()


def test_snapshot_aborts_when_an_earlier_source_changes_during_later_copies(
        app, tmp_path, monkeypatch):
    from app.services import face_dataset_service as fds
    from app.services import training_snapshot
    with app.app_context():
        dataset = _seed(app, tmp_path)
        first_source = os.path.join(fds._dataset_dir(dataset.id), '0.png')
        original_copy = training_snapshot.shutil.copy2
        copies = 0

        def copy_and_edit_earlier_source(source, destination):
            nonlocal copies
            result = original_copy(source, destination)
            copies += 1
            if copies == 2:
                Image.new('RGB', (8, 8), (255, 1, 2)).save(first_source)
            return result

        monkeypatch.setattr(training_snapshot.shutil, 'copy2', copy_and_edit_earlier_source)

        with pytest.raises(RuntimeError, match='dataset image changed'):
            training_snapshot.capture(
                LOCAL_USER, dataset.id, tmp_path / 'disk-racing-snapshot')
        assert not (tmp_path / 'disk-racing-snapshot').exists()


def test_local_launch_materialization_uses_immutable_snapshot(app, tmp_path):
    from app.services import lora_training as training
    with app.app_context():
        dataset = _seed(app, tmp_path)
        output, snapshot = training._materialize_local_training_dataset(
            LOCAL_USER, dataset.id, masked=False,
            destination=tmp_path / 'local-materialized')

        assert snapshot['dataset_revision'] == dataset.revision
        assert os.path.isfile(os.path.join(output, 'snapshot_000.png'))
        assert os.path.isfile(os.path.join(output, 'snapshot_000.txt'))
        assert not list(tmp_path.glob('.lds-local-launch-*'))
