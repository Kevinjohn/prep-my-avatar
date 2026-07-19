"""Provenance registry: dataset fingerprint -> human version (v1/v2/...),
manifest diffs, and the version suffix on deployed checkpoint names."""
import json
import os
import threading

import pytest

from app.config import LOCAL_USER


@pytest.fixture()
def ds_with_images(app, client):
    """A dataset with 2 kept images (files on disk so the content proxy works)."""
    from app import config as cfg
    from app.extensions import db
    from app.models import FaceDatasetImage
    ds_id = client.post('/api/dataset/create',
                        json={'name': 'Prov', 'trigger_word': 'prov'}).get_json()['id']
    with app.app_context():
        img_dir = cfg.dataset_images_root() / str(ds_id)
        img_dir.mkdir(parents=True, exist_ok=True)
        ids = []
        for i in range(2):
            (img_dir / f'im{i}.png').write_bytes(b'PNG' + bytes([i]))
            row = FaceDatasetImage(dataset_id=ds_id, filename=f'im{i}.png',
                                   status='keep', caption=f'a photo {i}')
            db.session.add(row)
            db.session.commit()
            ids.append(row.id)
    return ds_id, ids


def test_register_allocates_versions_by_fingerprint(app, ds_with_images):
    from app.services import checkpoint_registry as reg
    ds_id, ids = ds_with_images
    with app.app_context():
        r1 = reg.register_launch(LOCAL_USER, ds_id, 'zimage', 'local', steps=1000)
        assert r1.version == 1
        # unchanged dataset -> same version on a re-launch
        r2 = reg.register_launch(LOCAL_USER, ds_id, 'zimage', 'local', steps=1200)
        assert r2.version == 1
        # edit a caption -> new fingerprint -> v2
        from app.models import FaceDatasetImage
        from app.extensions import db
        img = db.session.get(FaceDatasetImage, ids[0])
        img.caption = 'edited caption'
        db.session.commit()
        r3 = reg.register_launch(LOCAL_USER, ds_id, 'zimage', 'local', steps=1000)
        assert r3.version == 2
        # families version independently
        rk = reg.register_launch(LOCAL_USER, ds_id, 'krea', 'cloud', cloud_run_id=7)
        assert rk.version == 1 and rk.source == 'cloud' and rk.cloud_run_id == 7


def test_register_persists_admission_snapshot_and_explicit_overrides(app, ds_with_images):
    from app.services import checkpoint_registry as reg
    ds_id, _ = ds_with_images
    preflight = {'verdict': 'warning', 'kept': 12, 'blockers': [],
                 'warnings': ['limited pose coverage']}
    overrides = {'allow_caption_mismatch': True, 'masked': False}
    with app.app_context():
        row = reg.register_launch(
            LOCAL_USER, ds_id, 'zimage', 'local',
            preflight=preflight, overrides=overrides)
        assert json.loads(row.preflight) == preflight
        assert json.loads(row.overrides) == overrides


def test_required_registration_fails_closed(app, ds_with_images, monkeypatch):
    from app.services import checkpoint_registry as registry
    dataset_id, _ = ds_with_images
    with app.app_context():
        monkeypatch.setattr(registry, 'dataset_manifest', lambda *_args: object())
        with pytest.raises(RuntimeError, match='immutable training launch provenance'):
            registry.register_launch(
                LOCAL_USER, dataset_id, 'zimage', 'local', required=True)


def test_required_registration_fails_when_dataset_disappeared(app):
    from app.services import checkpoint_registry as registry
    with app.app_context():
        assert registry.register_launch(
            LOCAL_USER, 999999, 'zimage', 'local') is None
        with pytest.raises(RuntimeError, match='immutable training launch provenance'):
            registry.register_launch(
                LOCAL_USER, 999999, 'zimage', 'local', required=True)


def test_concurrent_distinct_launches_allocate_distinct_versions(app, ds_with_images):
    from app.services import checkpoint_registry as registry
    dataset_id, _ = ds_with_images
    barrier = threading.Barrier(3)
    versions = []
    errors = []

    def register(index):
        try:
            with app.app_context():
                barrier.wait(timeout=3)
                record = registry.register_launch(
                    LOCAL_USER, dataset_id, 'zimage', 'local',
                    manifest=[[index, f'caption-{index}', f'file-{index}']],
                    trigger='prov', kind='character', required=True)
                versions.append(record.version)
        except Exception as exc:  # surfaced below with the original exception
            errors.append(exc)

    threads = [threading.Thread(target=register, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=3)
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert sorted(versions) == [1, 2]


def test_manifest_diff_counts_changes():
    from app.services import checkpoint_registry as reg
    old = [[1, 'aaaa', 'f1'], [2, 'bbbb', 'f2'], [3, 'cccc', 'f3']]
    new = [[2, 'bbbb', 'f2X'], [3, 'CHANGED', 'f3'], [4, 'dddd', 'f4']]
    d = reg.manifest_diff(old, new)
    assert d == {'images_added': 1, 'images_removed': 1,
                 'captions_changed': 1, 'images_edited': 1}


def test_manifest_hashes_exact_bytes_not_size_or_mtime(app, ds_with_images):
    import os
    from pathlib import Path
    from app.services import checkpoint_registry as reg
    from app.services import face_dataset_service as fds
    from app.models import FaceDatasetImage
    ds_id, ids = ds_with_images
    with app.app_context():
        row = fds.db.session.get(FaceDatasetImage, ids[0])
        path = Path(fds._img_path(row))
        before_stat = os.stat(path)
        before = reg.dataset_manifest(ds_id)
        original = path.read_bytes()
        replacement = bytes([original[0] ^ 0xFF]) + original[1:]
        path.write_bytes(replacement)
        os.utime(path, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
        after = reg.dataset_manifest(ds_id)
        assert os.stat(path).st_size == before_stat.st_size
        assert before != after
        assert len(after[0][2]) == 64


def test_manifest_uses_sha256_for_captions_and_dataset_fingerprint(app, ds_with_images):
    from app.services import checkpoint_registry as registry
    from app.services import face_dataset_service as datasets
    with app.app_context():
        dataset_id, _images = ds_with_images
        dataset = datasets.get_dataset(LOCAL_USER, dataset_id)
        manifest = registry.dataset_manifest(dataset_id)
        assert len(manifest[0][1]) == 64
        assert len(manifest[0][2]) == 64
        assert len(registry.fingerprint_of(
            manifest, dataset.trigger_word, dataset.kind or '')) == 64


def test_full_fingerprint_keeps_legacy_prefix_version(app, ds_with_images):
    from app.extensions import db
    from app.models import TrainingRunRecord
    from app.services import checkpoint_registry as registry
    dataset_id, _images = ds_with_images
    with app.app_context():
        manifest = registry.dataset_manifest(dataset_id)
        legacy_full = registry.fingerprint_of(manifest, 'prov', '')
        full = registry.fingerprint_of(manifest, 'prov', 'character')
        db.session.add(TrainingRunRecord(
            dataset_id=dataset_id, family='zimage', source='legacy',
            fingerprint=legacy_full[:16], manifest=json.dumps(manifest), version=3,
        ))
        db.session.commit()

        state = registry.dataset_state(LOCAL_USER, dataset_id, 'zimage')
        record = registry.register_launch(
            LOCAL_USER, dataset_id, 'zimage', 'local', required=True)

        assert state['changed'] is False
        assert record.version == 3
        assert record.fingerprint == full


def test_dataset_state_flags_drift(app, ds_with_images):
    from app.services import checkpoint_registry as reg
    from app.extensions import db
    from app.models import FaceDatasetImage
    ds_id, ids = ds_with_images
    with app.app_context():
        assert reg.dataset_state(LOCAL_USER, ds_id, 'zimage')['registered'] is False
        reg.register_launch(LOCAL_USER, ds_id, 'zimage', 'local')
        st = reg.dataset_state(LOCAL_USER, ds_id, 'zimage')
        assert st['registered'] is True and st['version'] == 1
        assert st['changed'] is False and st['diff'] is None
        # remove an image -> drift with a readable diff
        db.session.get(FaceDatasetImage, ids[1]).status = 'reject'
        db.session.commit()
        st = reg.dataset_state(LOCAL_USER, ds_id, 'zimage')
        assert st['changed'] is True
        assert st['diff']['images_removed'] == 1


def test_import_suffixes_deployed_name_with_version(app, ds_with_images, tmp_path, monkeypatch):
    """A local import resolves the file's run via the registry and suffixes
    _v<N>; without any registry row the name stays EXACTLY as before."""
    from app import config as cfg
    from app.services import lora_training as lt
    from app.services import checkpoint_registry as reg
    ds_id, _ = ds_with_images
    with app.app_context():
        cfg.save_config({'comfyui': {'base_dir': str(tmp_path / 'comfy')},
                         'aitoolkit': {'dir': str(tmp_path / 'aitk')}})
        run_dir = tmp_path / 'run'
        run_dir.mkdir()
        ck = run_dir / 'lora_prov_000001000.safetensors'
        ck.write_bytes(b'W')
        monkeypatch.setattr(lt, '_run_dir', lambda *a, **k: str(run_dir))
        # no registry row yet -> unchanged historical name
        dest = lt.import_checkpoint(LOCAL_USER, ds_id, ck.name)
        assert os.path.basename(dest) == ck.name
        # registered BEFORE the file was written -> _v1 suffix
        reg.register_launch(LOCAL_USER, ds_id, 'zimage', 'local')
        os.utime(ck)                        # file newer than the record
        dest = lt.import_checkpoint(LOCAL_USER, ds_id, ck.name)
        assert os.path.basename(dest) == 'lora_prov_000001000_v1.safetensors'
        # both deployed files are listed (the _v suffix passes the boundary)
        names = [c['filename'] for c in lt.list_imported_checkpoints(LOCAL_USER, ds_id)]
        assert any(n.endswith('_v1.safetensors') for n in names)


def test_record_for_mtime_prefers_oldest_for_preregistry_files(app, ds_with_images):
    """A checkpoint file OLDER than every record predates the registry: its
    owner is the oldest record (legacy baseline), never the newest (live
    sighting: local checkpoints wore a ☁ chip because a cloud launch was the
    latest record)."""
    import time
    from app.services import checkpoint_registry as reg
    ds_id, _ = ds_with_images
    with app.app_context():
        legacy = reg.register_launch(LOCAL_USER, ds_id, 'krea', 'legacy')
        cloud = reg.register_launch(LOCAL_USER, ds_id, 'krea', 'cloud', cloud_run_id=10)
        assert legacy.id != cloud.id
        # file mtime far in the past -> oldest record wins
        rec = reg.record_for_mtime(ds_id, 'krea', time.time() - 86400)
        assert rec.id == legacy.id and rec.source == 'legacy'
        # file newer than everything -> newest record wins (loop path)
        rec = reg.record_for_mtime(ds_id, 'krea', time.time() + 60)
        assert rec.id == cloud.id


def test_ensure_baseline_retrofits_pretrained_datasets(app, ds_with_images):
    """Deployed-project rule: a dataset trained BEFORE the registry existed
    (evidence: checkpoints/cloud runs, zero records) gets a retroactive v1
    baseline — versioning must cover the past, not only future runs."""
    from app.services import checkpoint_registry as reg
    ds_id, _ = ds_with_images
    with app.app_context():
        # no training evidence -> nothing registered
        reg.ensure_baseline(LOCAL_USER, ds_id, 'zimage', had_training=False)
        assert reg.latest_record(ds_id, 'zimage') is None
        # evidence -> v1 baseline, source 'legacy'; idempotent
        reg.ensure_baseline(LOCAL_USER, ds_id, 'zimage', had_training=True)
        rec = reg.latest_record(ds_id, 'zimage')
        assert rec.version == 1 and rec.source == 'legacy'
        reg.ensure_baseline(LOCAL_USER, ds_id, 'zimage', had_training=True)
        assert reg.latest_record(ds_id, 'zimage').id == rec.id   # no duplicate


def test_legacy_backfill_runs_outside_checkpoint_get(app, ds_with_images, monkeypatch):
    """Startup migration preserves legacy provenance without a mutating GET."""
    from app.services import checkpoint_registry as reg
    ds_id, _ = ds_with_images
    monkeypatch.setattr(
        'app.services.lora_training.list_checkpoints',
        lambda _user, dataset_id, family=None, **_kwargs:
            [{'filename': 'legacy.safetensors'}]
            if dataset_id == ds_id and family == 'zimage' else [])
    with app.app_context():
        assert reg.backfill_legacy_baselines(LOCAL_USER) == 1
        rec = reg.latest_record(ds_id, 'zimage')
        assert rec is not None and rec.source == 'legacy'
        assert reg.backfill_legacy_baselines(LOCAL_USER) == 0


def test_cloud_checkpoints_lists_synced_saves_and_checks_files(app, ds_with_images, tmp_path):
    """The panel list must show cloud saves synced locally — including an
    ACTIVE run's latest (user-observed: step 1000, save synced, list empty) —
    and only files that still exist (hand-deletion must not yield 404s)."""
    import json as _json
    from app.extensions import db
    from app.models import CloudTrainingRun
    from app.services import cloud_training as ct
    ds_id, _ = ds_with_images
    with app.app_context():
        d10 = tmp_path / 'r10'
        d10.mkdir()
        d11 = tmp_path / 'r11'
        d11.mkdir()
        ck = d10 / 'lds10_x_000001000.safetensors'
        ck.write_bytes(b'W')
        gone = d11 / 'lds11_x_000000500.safetensors'   # never created
        active = CloudTrainingRun(
            dataset_id=ds_id, status='training', job_name='j', vast_label='lds-10',
            staging_dir=str(d10), checkpoint_local_path=str(ck),
            train_params=_json.dumps({'train_type': 'krea', 'version': 2, 'steps': 3100}))
        deleted = CloudTrainingRun(
            dataset_id=ds_id, status='done', job_name='j', vast_label='lds-11',
            staging_dir=str(d11), checkpoint_local_path=str(gone),
            train_params=_json.dumps({'train_type': 'krea'}))
        db.session.add_all([active, deleted])
        db.session.commit()
        out = ct.cloud_checkpoints(ds_id, 'krea')
        assert len(out) == 1                              # missing file filtered out
        assert out[0]['step'] == 1000 and out[0]['active'] is True
        assert out[0]['version'] == 2 and out[0]['cloud'] is True
        # checkpoint_ready reflects the FILE, not the stored path
        assert ct._run_payload(active)['checkpoint_ready'] is True
        assert ct._run_payload(deleted)['checkpoint_ready'] is False
        # family filter: zimage view doesn't show krea saves
        assert ct.cloud_checkpoints(ds_id, 'zimage') == []


def test_checkpoint_download_targets_run_id(app, client, monkeypatch, ds_with_images, tmp_path):
    """Two finished runs of a family: the older row's ⬇ must serve ITS file,
    not the newest run's (family resolution alone did)."""
    import json as _json
    from app.extensions import db
    from app.models import CloudTrainingRun
    ds_id, _ = ds_with_images
    monkeypatch.setenv('VAST_API_KEY', 'k-test')
    with app.app_context():
        runs = []
        for i, content in ((1, b'OLD'), (2, b'NEW')):
            ck = tmp_path / f'lds{i}_x_000001000.safetensors'
            ck.write_bytes(content)
            r = CloudTrainingRun(dataset_id=ds_id, status='done', job_name='j',
                                 vast_label=f'lds-{i}', staging_dir=str(tmp_path),
                                 checkpoint_local_path=str(ck),
                                 train_params=_json.dumps({'train_type': 'krea'}))
            db.session.add(r)
            db.session.commit()
            runs.append(r.id)
    old_id, new_id = runs
    # family resolution -> newest run's file (unchanged default)
    with client.get(f'/api/dataset/{ds_id}/train/cloud/checkpoint?train_type=krea') as response:
        assert response.data == b'NEW'
    # run_id targets the OLD row's own file
    with client.get(f'/api/dataset/{ds_id}/train/cloud/checkpoint?run_id={old_id}') as response:
        assert response.data == b'OLD'
    # a run_id of another dataset -> 404, no cross-dataset leak
    assert client.get(f'/api/dataset/{ds_id + 999}/train/cloud/checkpoint?run_id={old_id}').status_code == 404


def test_baseline_evidence_is_family_scoped(app, client, monkeypatch, ds_with_images, tmp_path):
    """A dataset with only a ZIMAGE cloud run must not get a krea/sdxl
    baseline just because the user clicks through family tabs (live sighting:
    tata got zimage+krea+sdxl v1 rows after tab browsing)."""
    import json as _json
    from app.extensions import db
    from app.models import CloudTrainingRun
    from app.services import checkpoint_registry as reg
    ds_id, _ = ds_with_images
    monkeypatch.setattr('app.capabilities.probe',
                        lambda force=False: {'aitoolkit': {'valid': True},
                                             'cloud_training': True})
    with app.app_context():
        from app import config as cfg
        cfg.save_config({'aitoolkit': {'dir': str(tmp_path)}})
        run = CloudTrainingRun(dataset_id=ds_id, status='done', job_name='j',
                               vast_label='lds-1',
                               train_params=_json.dumps({'train_type': 'zimage'}))
        db.session.add(run)
        db.session.commit()
    client.get(f'/api/dataset/{ds_id}/train/checkpoints?train_type=krea')
    client.get(f'/api/dataset/{ds_id}/train/checkpoints?train_type=zimage')
    with app.app_context():
        # Listing is read-only; startup maintenance performs the backfill.
        assert reg.latest_record(ds_id, 'krea') is None
        assert reg.latest_record(ds_id, 'zimage') is None
        assert reg.backfill_legacy_baselines(LOCAL_USER) == 1
        assert reg.latest_record(ds_id, 'krea') is None       # not trained -> no baseline
        z = reg.latest_record(ds_id, 'zimage')
        assert z is not None and z.version == 1               # trained -> baseline


def test_import_route_accepts_cloud_run_id(app, client, monkeypatch, ds_with_images, tmp_path):
    """POST /train/import {cloud_run_id}: imports from the run's staging with
    the run's dataset version in the deployed name."""
    import json as _json
    from app import config as cfg
    from app.extensions import db
    from app.models import CloudTrainingRun
    ds_id, _ = ds_with_images
    monkeypatch.setattr('app.capabilities.probe',
                        lambda force=False: {'aitoolkit': {'valid': True},
                                             'cloud_training': True})
    with app.app_context():
        cfg.save_config({'comfyui': {'base_dir': str(tmp_path / 'comfy')}})
        ck = tmp_path / 'lds10_x_000001000.safetensors'
        ck.write_bytes(b'W')
        run = CloudTrainingRun(
            dataset_id=ds_id, status='training', job_name='j', vast_label='lds-10',
            staging_dir=str(tmp_path), checkpoint_local_path=str(ck),
            train_params=_json.dumps({'train_type': 'zimage', 'version': 3}))
        db.session.add(run)
        db.session.commit()
        run_id = run.id
    r = client.post(f'/api/dataset/{ds_id}/train/import',
                    json={'filename': ck.name, 'train_type': 'zimage',
                          'cloud_run_id': run_id})
    assert r.status_code == 200
    assert r.get_json()['dest'] == 'lds10_x_000001000_v3.safetensors'
    # unknown run / wrong dataset -> 404
    r = client.post(f'/api/dataset/{ds_id}/train/import',
                    json={'filename': ck.name, 'cloud_run_id': 999999})
    assert r.status_code == 404


def test_cloud_launch_registers_and_stamps_version(app, client, monkeypatch, ds_with_images):
    from app.services import cloud_training as ct
    ds_id, _ = ds_with_images
    monkeypatch.setenv('VAST_API_KEY', 'k-test')
    monkeypatch.setattr(ct, '_start_monitor', lambda *a, **k: None)
    monkeypatch.setattr(ct, '_reconcile_before_launch', lambda a: None)
    monkeypatch.setattr(ct.lt, 'export_dataset_to_aitoolkit',
                        lambda uid, did, masked=True, dest_dir=None: dest_dir)
    monkeypatch.setattr(ct.lt, 'default_steps', lambda ds: 1000)
    monkeypatch.setattr(ct.lt, 'assert_trainable', lambda *a, **kw: None)
    with app.app_context():
        ct.launch_cloud_training(LOCAL_USER, ds_id)
        run = ct.get_active_run()
        assert json.loads(run.train_params)['version'] == 1
        assert ct._run_payload(run)['version'] == 1


def test_imported_list_shows_cloud_epoch_deployments(app, ds_with_images, tmp_path):
    """A cloud EPOCH deployed into loras/<family> must appear in the
    "in ComfyUI" list. Its deployed name is `<staging_stem>_<base_tag>_v<N>`
    while only the run's FINAL checkpoint_local_path basename is recorded —
    the exact-basename match missed every epoch (user-observed 2026-07-13:
    imports succeeded, header stuck at "0 in ComfyUI"). The pod-job prefix
    (`lds<run.id>_`) is what identifies the run's deployments."""
    from app import config as cfg
    from app.extensions import db
    from app.models import CloudTrainingRun
    from app.services import lora_training as lt
    ds_id, _ = ds_with_images
    with app.app_context():
        cfg.save_config({'comfyui': {'base_dir': str(tmp_path / 'comfy')}})
        run = CloudTrainingRun(dataset_id=ds_id, status='done')
        db.session.add(run)
        db.session.commit()
        dest = tmp_path / 'comfy' / 'models' / 'loras' / 'krea'
        dest.mkdir(parents=True)
        epoch = f'lds{run.id}_ulocal_prov_Krea-2-Raw_000002000_Krea-2-Raw_v1.safetensors'
        (dest / epoch).write_bytes(b'W')
        (dest / 'unrelated_other_lora.safetensors').write_bytes(b'W')
        names = [c['filename'] for c in
                 lt.list_imported_checkpoints(LOCAL_USER, ds_id, family='krea')]
        assert any(n.endswith(epoch) for n in names)          # the epoch is listed
        assert not any('unrelated' in n for n in names)       # others stay hidden


def test_register_launch_stores_settings_snapshot(app, ds_with_images):
    """The launch stamps the EFFECTIVE ai-toolkit settings on the record — the
    unified Runs page shows them per run. NULL-safe on pre-feature rows."""
    import json
    from app.services import checkpoint_registry as reg
    from app.config import LOCAL_USER
    ds_id, _imgs = ds_with_images
    with app.app_context():
        rec = reg.register_launch(LOCAL_USER, ds_id, 'krea', 'local',
                                  settings={'rank': 32, 'resolution': [768, 1024]})
        assert json.loads(rec.settings) == {'rank': 32, 'resolution': [768, 1024]}
        rec2 = reg.register_launch(LOCAL_USER, ds_id, 'krea', 'local')
        assert rec2.settings is None


def test_launch_settings_snapshot_reflects_effective_values(app, ds_with_images):
    """Effective values (defaults resolved), expert levers only when set."""
    from app.services import lora_training as lt
    from app.services import face_dataset_service as fds
    from app.config import LOCAL_USER
    ds_id, _imgs = ds_with_images
    with app.app_context():
        ds = fds.get_dataset(LOCAL_USER, ds_id)
        snap = lt.launch_settings_snapshot(ds, 'krea')
        assert snap['rank'] == 32 and snap['alpha'] == 32   # Krea researched defaults
        assert snap['trigger'] == 'prov'                    # recipe: trigger word
        assert snap['resolution'] == [768, 1024]
        assert snap['save_every'] == 250
        assert snap['timestep_type'] == 'linear'            # Krea family default
        assert 'dropout' not in snap                        # lever untouched -> absent
        lt.update_train_settings(LOCAL_USER, ds_id, {'rank': 64, 'dropout': 0.1})
        ds = fds.get_dataset(LOCAL_USER, ds_id)
        snap2 = lt.launch_settings_snapshot(ds, 'krea')
        assert snap2['rank'] == 64
        assert snap2['dropout'] == 0.1
