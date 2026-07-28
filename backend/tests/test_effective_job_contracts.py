from types import SimpleNamespace

from app.services.studio_cells import EffectiveStudioCell
from app.services.studio_launch import LaunchOptions, LaunchSubject, launch_matrix
from app.services.training_jobs import EffectiveTrainingJob


def test_effective_training_job_round_trips_every_queue_field():
    job = EffectiveTrainingJob(
        job_id='job-1', user_id='local', dataset_id=7, steps=1800,
        extra_steps=600, check_captions=False, base_model='/base.safetensors',
        variant='raw', train_type='krea', allow_caption_mismatch=True,
        masked=False, fresh=True, allow_uncaptioned=True,
        vae_path='/vae.safetensors', te_path='/te.safetensors',
        allow_unverified_weights=True, not_before='2030-01-02T03:04:05')

    replay = EffectiveTrainingJob.from_queue_record(
        job.queue_record(), persisted=object())

    assert replay.queue_record() == job.queue_record()
    assert set(job.launch_kwargs()) == {
        'user_id', 'dataset_id', 'steps', 'check_captions', 'base_model',
        'variant', 'train_type', 'allow_caption_mismatch', 'masked', 'fresh',
        'allow_uncaptioned', 'vae_path', 'te_path', 'allow_unverified_weights',
    }
    assert set(job.continuation_kwargs()) == {
        'user_id', 'dataset_id', 'extra_steps', 'base_model', 'variant',
        'train_type', 'masked', 'fresh', 'allow_caption_mismatch',
        'allow_uncaptioned', 'vae_path', 'te_path', 'allow_unverified_weights',
    }


def test_effective_studio_cell_keeps_persistence_and_workflow_in_sync():
    cell = EffectiveStudioCell(
        checkpoint='z image/lora.safetensors', strength=0.8, seed=11,
        run_seed=10, z_model='z image/base.safetensors', aspect='portrait',
        prompt='portrait of trigger', cfg=1.2, steps=12, steps2=None,
        family='zimage', width=768, height=1024, dataset_id=4,
        trigger_word='trigger', extra_loras=({'filename': 'utility.safetensors',
                                             'strength': 0.5},),
        persisted_extra_loras=({'filename': 'utility.safetensors',
                                'strength': 0.5, 'batch': True},),
        negative='bad', sampler='euler', scheduler='simple',
        weight_dtype='default', enhancer_strength=0.2, detail_amount=0.3,
        resolution_tier='standard', init_image='input.png', denoise=0.4,
        run_id='run-1', training_run_record_id=9)

    row = cell.row_kwargs()
    workflow = cell.workflow_kwargs()
    assert row['extra_loras'].endswith('"batch": true}]')
    assert workflow['extra_loras'][0].get('batch') is None
    for field in ('cfg', 'steps', 'steps2', 'negative', 'sampler', 'scheduler',
                  'weight_dtype', 'enhancer_strength', 'detail_amount'):
        assert workflow[field] == row[field]

    restored = EffectiveStudioCell.from_row(
        SimpleNamespace(**row), family='zimage', width=768, height=1024,
        z_model=row['z_model'], prompt=row['prompt'], seed=row['seed'],
        trigger_word='trigger')
    assert restored.row_kwargs() == row


def test_studio_family_create_compare_preflight_resume_scoring_parity(app):
    """Every family and run mode crosses the same immutable field boundary."""
    from app.services.studio_scoring import _generation_config
    families = {
        'zimage': {'model': 'z/base.safetensors', 'steps2': None},
        'sdxl': {'model': 'sdxl/base.safetensors', 'steps2': 18},
        'krea': {'model': None, 'steps2': None},
    }
    for family, family_values in families.items():
        subject = LaunchSubject(
            dataset_id=7, trigger_word='person', prompt='portrait',
            checkpoint=f'{family}/person-100.safetensors',
            allowed=frozenset({f'{family}/person-100.safetensors'}),
            training_run_record_id=31,
        )
        knobs = {
            'extra_loras': [{'filename': f'{family}/style.safetensors', 'strength': 0.4}],
            'negative': 'bad', 'sampler': 'euler', 'scheduler': 'simple',
            'weight_dtype': 'default', 'enhancer_strength': 0.2,
            'detail_amount': 0.3, 'resolution_tier': 'standard',
            'init_image': 'input.png', 'denoise': 0.45,
        }
        options = LaunchOptions(
            family=family, run_seed=10, models=(family_values['model'],),
            seeds=(11,), batch_loras=({'filename': f'{family}/batch.safetensors',
                                       'strength': 0.6},),
            knobs=knobs, rebalance=4.0 if family == 'krea' else None,
        )
        matrix = [(subject.checkpoint, 0.8, '3:4', 1.2, 12,
                   family_values['steps2'])]

        captured = []
        def launch(cell, allowed):
            assert allowed == set(subject.allowed)
            captured.append(cell)
            return SimpleNamespace(id=len(captured))

        # Dataset create and comparison supply different subject/matrix adapters,
        # but the shared orchestrator must produce identical effective cells.
        launch_matrix(
            [subject], options, cells_for=lambda _subject: matrix,
            dimensions=lambda *_args: (768, 1024), launch=launch)
        launch_matrix(
            [subject], options, cells_for=lambda current: [
                (current.checkpoint, *matrix[0][1:])],
            dimensions=lambda *_args: (768, 1024), launch=launch)
        created, compared = captured
        assert created == compared

        # Preflight/workflow construction, persistence, resume, and scoring all
        # observe the same supported field values rather than rebuilding subsets.
        row = created.row_kwargs()
        resumed = EffectiveStudioCell.from_row(
            SimpleNamespace(**row), family=family, width=768, height=1024,
            z_model=row['z_model'], prompt=row['prompt'], seed=row['seed'],
            trigger_word='person')
        assert resumed.row_kwargs() == row
        assert resumed.workflow_kwargs() == created.workflow_kwargs()
        scoring_fields = _generation_config(SimpleNamespace(**row))
        assert scoring_fields == _generation_config(SimpleNamespace(**resumed.row_kwargs()))
