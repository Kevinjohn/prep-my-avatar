import json
import subprocess


def test_joycaption_seed_revision_protocol_and_provenance(app, tmp_path, monkeypatch):
    from app.services import joycaption

    image = tmp_path / 'image.png'
    image.write_bytes(b'image')
    monkeypatch.setattr(joycaption, 'is_available', lambda: True)
    monkeypatch.setattr(
        joycaption.cfg, 'aitoolkit_path',
        lambda key: tmp_path / ('python' if key == 'venv_python' else 'hf'))
    seen = {}

    def run(command, **kwargs):
        seen.update(json.loads(kwargs['input']))
        provenance = {
            str(image): {
                'provider': 'joycaption', 'model': 'model',
                'revision': seen['revision'], 'seed': seen['seed'],
            },
        }
        return subprocess.CompletedProcess(
            command, 0, json.dumps({
                'captions': {str(image): ' deterministic caption '},
                'errors': {}, 'provenance': provenance,
            }), '')

    monkeypatch.setattr(joycaption.subprocess, 'run', run)
    result = joycaption.caption_images_joycaption(
        [str(image)], seed=73, revision='a' * 40)

    assert seen['seed'] == 73 and seen['revision'] == 'a' * 40
    assert result == {str(image): 'deterministic caption'}
    assert result.provenance[str(image)]['seed'] == 73


def test_forced_joycaption_persists_per_caption_provenance(app, tmp_path, monkeypatch):
    from app.config import LOCAL_USER, save_config
    from app.models import FaceDatasetImage
    from app.services import face_dataset_service as service
    from app.services import joycaption

    with app.app_context():
        save_config({'captioning': {'backend': 'joycaption'}})
        dataset = service.create_dataset(LOCAL_USER, 'Provenance', 'subject')
        path = tmp_path / 'caption.png'
        path.write_bytes(b'image')
        monkeypatch.setattr(service, '_img_path', lambda row: str(path))
        row = FaceDatasetImage(
            dataset_id=dataset.id, filename='caption.png', status='keep',
            source='import')
        service.db.session.add(row)
        service.db.session.commit()
        monkeypatch.setattr(joycaption, 'is_available', lambda: True)
        result = joycaption.CaptionResults(
            {str(path): 'a person standing outside'},
            {str(path): {'provider': 'joycaption', 'revision': 'b' * 40, 'seed': 91}},
        )
        monkeypatch.setattr(
            joycaption, 'caption_images_joycaption', lambda *args, **kwargs: result)

        assert service.caption_images(LOCAL_USER, dataset.id) == 1
        persisted = service.db.session.get(FaceDatasetImage, row.id)
        assert json.loads(persisted.caption_provenance) == {
            'provider': 'joycaption', 'revision': 'b' * 40, 'seed': 91,
        }
