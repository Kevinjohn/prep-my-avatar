"""Publish-to-HF (export-only). HfApi is ENTIRELY mocked — no real network,
no real upload ever happens here (the real smoke is the owner's to run)."""
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image


def _webp(color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new('RGB', (48, 48), color).save(buf, 'WEBP')
    return buf.getvalue()


def _make_dataset(app, name='Lola', trigger='lola', kind=None, train_type=None,
                  captions=('a candid smile', 'looking away'), with_ref=True):
    """A dataset with `len(captions)` kept webp images (+ optional ref photo) on
    disk. Returns the dataset id."""
    from app.services import face_dataset_service as svc
    from app.models import FaceDatasetImage
    from app.config import LOCAL_USER
    ds = svc.create_dataset(LOCAL_USER, name, trigger, kind=kind, train_type=train_type)
    d = svc._dataset_dir(ds.id)
    os.makedirs(d, exist_ok=True)
    if with_ref:
        Path(d, 'ref.webp').write_bytes(_webp((0, 0, 255)))
        ds.ref_filename = 'ref.webp'
    for i, cap in enumerate(captions, 1):
        fn = f'img{i}.webp'
        Path(d, fn).write_bytes(_webp((0, 255, 0)))
        svc.db.session.add(FaceDatasetImage(dataset_id=ds.id, filename=fn,
                                            status='keep', framing='face', caption=cap))
    svc.db.session.commit()
    return ds.id


class FakeHTTPError(Exception):
    """Mimics huggingface_hub.HfHubHTTPError: carries .response.status_code."""
    def __init__(self, status):
        super().__init__(f'HTTP {status}')
        self.response = type('R', (), {'status_code': status})()


class FakeApi:
    def __init__(self, role='write', fine=None, create_exc=None, upload_exc=None,
                 whoami_exc=None, delete_exc=None):
        self.role, self.fine = role, fine
        self.create_exc, self.upload_exc, self.whoami_exc = create_exc, upload_exc, whoami_exc
        self.delete_exc = delete_exc
        self.created = self.uploaded = None
        self.deleted = None
        self.uploaded_files = None

    def whoami(self, *a, **k):
        if self.whoami_exc:
            raise self.whoami_exc
        at = {'role': self.role}
        if self.fine is not None:
            at['fineGrained'] = self.fine
        return {'name': 'alice', 'auth': {'accessToken': at}}

    def create_repo(self, **kw):
        self.created = kw
        if self.create_exc:
            raise self.create_exc

    def upload_folder(self, folder_path=None, **kw):
        # Capture the folder contents AT upload time (the temp dir is deleted right
        # after publish_to_hf returns).
        self.uploaded_files = sorted(os.listdir(folder_path))
        self.uploaded = {'folder_path': folder_path, **kw}
        if self.upload_exc:
            raise self.upload_exc

    def delete_repo(self, **kw):
        self.deleted = kw
        if self.delete_exc:
            raise self.delete_exc


# --- folder build: metadata.jsonl, captions, README front-matter, redaction ---

def test_metadata_jsonl_captions_have_trigger(app, tmp_path):
    from app.services import hf_publish
    with app.app_context():
        ds_id = _make_dataset(app, trigger='lola', captions=('a smile', 'a wave'))
        info = hf_publish.build_publish_dir(
            'local', ds_id, str(tmp_path), include_ref=False,
            license='cc-by-4.0', nfaa=True)
    lines = (tmp_path / 'metadata.jsonl').read_text(encoding='utf-8').splitlines()
    rows = [json.loads(line) for line in lines]
    assert info['count'] == 2 and len(rows) == 2
    assert {r['file_name'] for r in rows} == {'Lola_001.webp', 'Lola_002.webp'}
    # Caption carries the trigger inline (export contract).
    assert rows[0]['text'] == 'lola, a smile'
    assert rows[1]['text'] == 'lola, a wave'
    # Same-stem .txt sidecar exists next to each image.
    assert (tmp_path / 'Lola_001.txt').read_text(encoding='utf-8') == 'lola, a smile'
    # webp kept as-is (no PNG re-encode).
    assert (tmp_path / 'Lola_001.webp').exists()
    assert not any(n.endswith('.png') for n in os.listdir(tmp_path))


def test_readme_front_matter_nfaa_and_license(app, tmp_path):
    from app.services import hf_publish
    with app.app_context():
        ds_id = _make_dataset(app)
        hf_publish.build_publish_dir('local', ds_id, str(tmp_path),
                                     include_ref=False, license='cc-by-nc-4.0', nfaa=True)
    readme = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert readme.startswith('---\n')
    assert 'license: cc-by-nc-4.0' in readme
    assert 'task_categories:\n- text-to-image' in readme
    assert '- lora-dataset-studio' in readme
    assert '- not-for-all-audiences' in readme          # nfaa ON
    assert 'LoRA Dataset Studio' in readme and 'github.com/perfectgf/lora-dataset-studio' in readme


def test_readme_no_nfaa_tag_when_off(app, tmp_path):
    from app.services import hf_publish
    from app.services import face_dataset_service as svc
    with app.app_context():
        ds_id = _make_dataset(app)
        readme = hf_publish.build_readme(svc.get_dataset('local', ds_id), 3,
                                         'cc0-1.0', nfaa=False)
    assert 'license: cc0-1.0' in readme
    assert 'not-for-all-audiences' not in readme


def test_readme_redacts_home_path(app, tmp_path):
    from app.services import hf_publish
    with app.app_context():
        # A home path smuggled into the dataset NAME must be redacted in the card.
        ds_id = _make_dataset(app, name=r'Lola C:\Users\Alice\stuff')
        hf_publish.build_publish_dir('local', ds_id, str(tmp_path),
                                     include_ref=False, license='openrail', nfaa=False)
    readme = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'Alice' not in readme and '~' in readme


def test_readme_escapes_markdown_control_characters(app):
    from app.services import hf_publish
    from app.services import face_dataset_service as svc
    with app.app_context():
        ds_id = _make_dataset(
            app, name='Name | <script>`x`', trigger='tick`|<img>')
        readme = hf_publish.build_readme(
            svc.get_dataset('local', ds_id), 2, 'cc0-1.0', nfaa=False)
    assert '# Name \\| &lt;script&gt;\\`x\\`' in readme
    assert '<script>' not in readme and '<img>' not in readme
    assert '``tick`&#124;&lt;img&gt;``' in readme


def test_caption_text_redacted(app, tmp_path):
    from app.services import hf_publish
    with app.app_context():
        ds_id = _make_dataset(app, trigger='lola',
                              captions=(r'a path C:\Users\Bob\x.png here',))
        hf_publish.build_publish_dir('local', ds_id, str(tmp_path),
                                     include_ref=False, license='cc0-1.0', nfaa=False)
    rows = [json.loads(line) for line in
            (tmp_path / 'metadata.jsonl').read_text('utf-8').splitlines()]
    assert 'Bob' not in rows[0]['text'] and '~' in rows[0]['text']


def test_metadata_excludes_private_source_rights_notes(app, tmp_path):
    from app.models import FaceDatasetImage
    from app.services import hf_publish
    from app.extensions import db
    with app.app_context():
        ds_id = _make_dataset(app, captions=('licensed portrait',))
        image = FaceDatasetImage.query.filter_by(dataset_id=ds_id).one()
        image.source_rights = json.dumps({
            'basis': 'licensed',
            'license': 'cc-by-4.0',
            'consent_confirmed': True,
            'notes': 'Private contract at C:\\Users\\Alice\\contracts\\source.pdf',
            'recorded_at': '2026-07-19T12:00:00Z',
        })
        db.session.commit()
        hf_publish.build_publish_dir(
            'local', ds_id, str(tmp_path), include_ref=False,
            license='cc-by-4.0', nfaa=False)

    row = json.loads((tmp_path / 'metadata.jsonl').read_text('utf-8').splitlines()[0])
    assert row['source_rights'] == {
        'basis': 'licensed', 'license': 'cc-by-4.0', 'consent_confirmed': True,
    }
    assert 'Alice' not in json.dumps(row)


# --- include_ref gating -------------------------------------------------------

def test_include_ref_off_excludes_anchor(app, tmp_path):
    from app.services import hf_publish
    with app.app_context():
        ds_id = _make_dataset(app, with_ref=True, captions=('a', 'b'))
        info = hf_publish.build_publish_dir('local', ds_id, str(tmp_path),
                                            include_ref=False, license='cc0-1.0', nfaa=False)
    names = os.listdir(tmp_path)
    assert not any('_000_ref' in n for n in names)
    assert info['count'] == 2


def test_include_ref_on_adds_anchor(app, tmp_path):
    from app.services import hf_publish
    with app.app_context():
        ds_id = _make_dataset(app, with_ref=True, captions=('a', 'b'))
        info = hf_publish.build_publish_dir('local', ds_id, str(tmp_path),
                                            include_ref=True, license='cc0-1.0', nfaa=False)
    rows = [json.loads(line) for line in
            (tmp_path / 'metadata.jsonl').read_text('utf-8').splitlines()]
    ref = [r for r in rows if '_000_ref' in r['file_name']]
    assert info['count'] == 3 and len(ref) == 1
    assert ref[0]['text'] == 'lola'                       # ref caption = bare trigger
    assert (tmp_path / 'Lola_000_ref.webp').exists()


# --- write-scope preflight ----------------------------------------------------

def test_read_only_token_refused_before_upload(app):
    from app.services import hf_publish
    api = FakeApi(role='read')
    with app.app_context():
        ds_id = _make_dataset(app)
        with pytest.raises(hf_publish.HfPublishError) as ei:
            hf_publish.publish_to_hf(ds_id, 'alice/lola', private=True, nfaa=True,
                                     license='cc0-1.0', include_ref=False,
                                     token='hf_x', _api=api)
    assert ei.value.code == 'read_only_token'
    assert 'read-only' in ei.value.message
    assert api.created is None and api.uploaded is None     # nothing was created/uploaded


def test_fine_grained_write_allowed(app):
    from app.services import hf_publish
    api = FakeApi(role='fineGrained',
                  fine={'scoped': [{'permissions': ['repo.content.read', 'repo.write']}]})
    with app.app_context():
        ds_id = _make_dataset(app)
        out = hf_publish.publish_to_hf(ds_id, 'alice/lola', private=True, nfaa=True,
                                       license='cc0-1.0', include_ref=False,
                                       token='hf_x', _api=api)
    assert out['ok'] and api.uploaded is not None


def test_fine_grained_read_only_refused(app):
    from app.services import hf_publish
    api = FakeApi(role='fineGrained',
                  fine={'global': [], 'scoped': [{'permissions': ['repo.content.read']}]})
    with app.app_context():
        ds_id = _make_dataset(app)
        with pytest.raises(hf_publish.HfPublishError) as ei:
            hf_publish.publish_to_hf(ds_id, 'alice/lola', private=True, nfaa=True,
                                     license='cc0-1.0', include_ref=False,
                                     token='hf_x', _api=api)
    assert ei.value.code == 'read_only_token'


# --- repo-exists / success ----------------------------------------------------

def test_repo_already_exists_clean_error(app):
    from app.services import hf_publish
    api = FakeApi(role='write', create_exc=FakeHTTPError(409))
    with app.app_context():
        ds_id = _make_dataset(app)
        with pytest.raises(hf_publish.HfPublishError) as ei:
            hf_publish.publish_to_hf(ds_id, 'alice/lola', private=True, nfaa=True,
                                     license='cc0-1.0', include_ref=False,
                                     token='hf_x', _api=api)
    assert ei.value.code == 'repo_exists'
    assert api.uploaded is None                            # never uploaded on a name clash


def test_publish_success_returns_url(app):
    from app.services import hf_publish
    api = FakeApi(role='write')
    with app.app_context():
        ds_id = _make_dataset(app, trigger='lola', captions=('a', 'b'))
        out = hf_publish.publish_to_hf(ds_id, 'alice/lola', private=True, nfaa=True,
                                       license='cc-by-4.0', include_ref=False,
                                       token='hf_x', _api=api)
    assert out['repo_url'] == 'https://huggingface.co/datasets/alice/lola'
    assert out['count'] == 2
    assert api.created['repo_type'] == 'dataset' and api.created['private'] is True
    assert api.created['exist_ok'] is False                # never silently overwrite
    # The uploaded folder carried the metadata + README + images.
    assert 'metadata.jsonl' in api.uploaded_files and 'README.md' in api.uploaded_files
    assert any(n.endswith('.webp') for n in api.uploaded_files)


def test_upload_failure_deletes_new_empty_repo(app):
    from app.services import hf_publish
    api = FakeApi(role='write', upload_exc=RuntimeError('upload failed'))
    with app.app_context():
        ds_id = _make_dataset(app)
        with pytest.raises(hf_publish.HfPublishError) as error:
            hf_publish.publish_to_hf(
                ds_id, 'alice/lola', private=True, nfaa=True,
                license='cc0-1.0', include_ref=False, token='hf_x', _api=api)
    assert error.value.code == 'network'
    assert api.deleted == {'repo_id': 'alice/lola', 'repo_type': 'dataset'}


def test_upload_failure_reports_partial_repo_when_cleanup_fails(app):
    from app.services import hf_publish
    api = FakeApi(
        role='write', upload_exc=RuntimeError('upload failed'),
        delete_exc=RuntimeError('delete failed'))
    with app.app_context():
        ds_id = _make_dataset(app)
        with pytest.raises(hf_publish.HfPublishError) as error:
            hf_publish.publish_to_hf(
                ds_id, 'alice/lola', private=True, nfaa=True,
                license='cc0-1.0', include_ref=False, token='hf_x', _api=api)
    assert error.value.code == 'upload_failed_repo_retained'
    assert 'delete "alice/lola"' in error.value.message


def test_invalid_license_rejected(app):
    from app.services import hf_publish
    with app.app_context():
        ds_id = _make_dataset(app)
        with pytest.raises(hf_publish.HfPublishError) as ei:
            hf_publish.publish_to_hf(ds_id, 'alice/lola', private=True, nfaa=True,
                                     license='gpl-3.0', include_ref=False,
                                     token='hf_x', _api=FakeApi())
    assert ei.value.code == 'invalid_license'


def test_invalid_repo_id_rejected(app):
    from app.services import hf_publish
    with app.app_context():
        ds_id = _make_dataset(app)
        with pytest.raises(hf_publish.HfPublishError) as ei:
            hf_publish.publish_to_hf(ds_id, 'no-namespace', private=True, nfaa=True,
                                     license='cc0-1.0', include_ref=False,
                                     token='hf_x', _api=FakeApi())
    assert ei.value.code == 'invalid_repo_id'


# --- route guards -------------------------------------------------------------

def test_route_consent_false_is_400(app, client, monkeypatch):
    monkeypatch.setenv('HF_TOKEN', 'hf_x')
    with app.app_context():
        ds_id = _make_dataset(app)
    r = client.post(f'/api/dataset/{ds_id}/publish-hf',
                    json={'repo_id': 'alice/lola', 'license': 'cc0-1.0', 'consent': False})
    assert r.status_code == 400
    assert 'consent' in r.get_json()['error']


def test_route_missing_token_is_400(app, client):
    with app.app_context():
        ds_id = _make_dataset(app)
    r = client.post(f'/api/dataset/{ds_id}/publish-hf',
                    json={'repo_id': 'alice/lola', 'license': 'cc0-1.0', 'consent': True})
    assert r.status_code == 400
    assert 'HF_TOKEN' in r.get_json()['error']


def test_route_launches_job_on_valid_consent(app, client, monkeypatch):
    monkeypatch.setenv('HF_TOKEN', 'hf_x')
    from app.services import hf_publish
    seen = {}
    monkeypatch.setattr(hf_publish, 'start_publish',
                        lambda *a, **k: seen.update(args=a, kwargs=k) or {'state': 'running'})
    with app.app_context():
        ds_id = _make_dataset(app)
    r = client.post(f'/api/dataset/{ds_id}/publish-hf',
                    json={'repo_id': 'alice/lola', 'license': 'cc0-1.0',
                          'consent': True, 'private': True, 'nfaa': True})
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] and body['state'] == 'running'
    assert seen['kwargs']['include_ref'] is False and seen['kwargs']['private'] is True


def test_start_publish_reuses_durable_job_without_duplicate_worker(app, monkeypatch):
    from app.services import background_jobs, hf_publish
    dataset_id = 991
    hf_publish._jobs.pop(dataset_id, None)
    with app.app_context():
        existing, _created = background_jobs.create_or_get(
            'hf_publish', str(dataset_id), {'repo_id': 'alice/lola'})
        existing_id = existing.id
    monkeypatch.setattr(
        hf_publish.threading, 'Thread',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('duplicate must not launch a worker')))

    result = hf_publish.start_publish(
        app, dataset_id, 'alice/lola', True, True, 'cc0-1.0', False, 'hf_x')

    assert result['already'] is True
    assert result['job_id'] == existing_id


def test_capability_reflects_hf_token(app, monkeypatch):
    from app import capabilities
    with app.app_context():
        capabilities.probe(force=True)
        assert capabilities.probe(force=True)['hf_publish'] is False
        monkeypatch.setenv('HF_TOKEN', 'hf_x')
        assert capabilities.probe(force=True)['hf_publish'] is True
