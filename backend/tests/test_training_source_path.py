"""Training uses untouched originals while retaining edited working images."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.config import LOCAL_USER
from app.services import face_dataset_service as fds


def _write_image(path, size, *, orientation=None):
    with Image.new('RGB', size, (30, 60, 90)) as image:
        exif = Image.Exif()
        if orientation is not None:
            exif[274] = orientation
        image.save(path, format='WEBP' if path.suffix == '.webp' else 'JPEG', exif=exif)


@pytest.fixture()
def imported(tmp_path, monkeypatch):
    monkeypatch.setattr(fds, '_dataset_dir', lambda dataset_id: str(tmp_path))
    (tmp_path / 'originals').mkdir()
    row = SimpleNamespace(dataset_id=1, filename='working.webp', source='import',
                          original_filename='originals/upload.jpg', upscale_ratio=None)
    _write_image(tmp_path / row.filename, (1024, 512))
    _write_image(tmp_path / row.original_filename, (3000, 1500))
    return row, tmp_path


def test_untouched_original_is_selected(imported):
    row, root = imported
    assert fds.training_source_path(row) == root / row.original_filename


@pytest.mark.parametrize('reason', [
    'upscale', 'edit_marker', 'aspect', 'generated', 'missing', 'empty',
    'corrupt', 'smaller', 'no_original', 'bad_derivative',
])
def test_unsafe_original_falls_back(imported, reason):
    row, root = imported
    original = root / row.original_filename
    if reason == 'upscale':
        row.upscale_ratio = 1.0
    elif reason == 'edit_marker':
        (root / 'working.orig.webp').touch()
    elif reason == 'aspect':
        _write_image(original, (3000, 2000))
    elif reason == 'generated':
        row.source = 'generated'
    elif reason == 'missing':
        original.unlink()
    elif reason == 'empty':
        original.write_bytes(b'')
    elif reason == 'corrupt':
        original.write_bytes(b'not an image')
    elif reason == 'smaller':
        _write_image(original, (800, 400))
    elif reason == 'no_original':
        row.original_filename = None
    elif reason == 'bad_derivative':
        (root / row.filename).write_bytes(b'not an image')
    assert fds.training_source_path(row) == root / row.filename


def test_exif_rotation_is_applied_before_comparing_aspect(imported):
    row, root = imported
    _write_image(root / row.original_filename, (1500, 3000), orientation=6)
    assert fds.training_source_path(row) == root / row.original_filename


def test_original_is_decoded_by_content(imported):
    row, root = imported
    renamed = (root / row.original_filename).with_suffix('.bin')
    (root / row.original_filename).rename(renamed)
    row.original_filename = str(renamed.relative_to(root))
    assert fds.training_source_path(row) == renamed


@pytest.mark.parametrize('snapshot', [False, True])
@pytest.mark.parametrize('long_side,edited,rotated', [
    (3000, False, False), (1600, False, False), (3000, True, False),
    (3000, False, True),
])
def test_export_uses_bounded_original_pixels(app, tmp_path, snapshot, long_side,
                                            edited, rotated):
    from app.models import FaceDatasetImage
    from app.services import lora_training_export as export
    from app.services import training_snapshot
    from app.utils.file_hashing import sha256_file

    with app.app_context():
        dataset = fds.create_dataset(LOCAL_USER, 'Originals', 'originals')
        root = Path(fds._dataset_dir(dataset.id))
        (root / 'originals').mkdir()
        row = FaceDatasetImage(
            dataset_id=dataset.id, filename='working.webp', status='keep',
            source='import', original_filename='originals/upload.jpg',
            upscale_ratio=1.0 if edited else None, caption='portrait')
        _write_image(root / row.filename, (1024, 512))
        size = (long_side // 2, long_side) if rotated else (long_side, long_side // 2)
        _write_image(root / row.original_filename, size, orientation=6 if rotated else None)
        fds.db.session.add(row)
        fds.db.session.commit()
        snapshot_dir = tmp_path / 'snapshot' if snapshot else None
        if snapshot:
            manifest = training_snapshot.capture(LOCAL_USER, dataset.id, snapshot_dir)
            entry = manifest['entries'][0]
            source = root / (row.filename if edited else row.original_filename)
            assert entry['source_kind'] == ('derivative' if edited else 'original')
            assert entry['source_filename'] == row.filename
            stored = training_snapshot.entry_path(snapshot_dir, entry)
            assert stored.suffix == source.suffix
            assert stored.read_bytes() == source.read_bytes()
        output = tmp_path / 'export'
        export.export_dataset_to_aitoolkit(
            LOCAL_USER, dataset.id, masked=False, dest_dir=output,
            snapshot_dir=snapshot_dir)
        png = output / 'originals_000.png'
        expected = 1024 if edited else min(long_side, 2048)
        with Image.open(png) as image:
            assert image.size == (expected, expected // 2)
            assert image.mode == 'RGB'
        assert export.export_registry_manifest(output)[0][2] == sha256_file(png)
