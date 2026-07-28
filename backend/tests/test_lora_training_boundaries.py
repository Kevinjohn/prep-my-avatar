"""Structural contracts for the local-training service boundaries."""


def test_queue_and_scheduler_api_is_owned_by_dedicated_module():
    from app.services import lora_training as training
    from app.services import lora_training_queue as queue

    public_queue_api = (
        'enqueue_training', 'dequeue_training', 'get_train_queue',
        'train_queue_view', 'process_training_queue',
        'start_training_scheduler', 'stop_training_scheduler',
    )
    for name in public_queue_api:
        assert getattr(training, name) is getattr(queue, name)
        assert getattr(queue, name).__module__ == queue.__name__


def test_queue_module_owns_process_recovery_and_handoff_implementation():
    from app.services import lora_training_queue as queue

    for name in (
        '_owned_training_process_alive', '_snapshot_final_checkpoint',
        '_advance_training_queue', '_launch_queued_item', '_due_index',
    ):
        assert getattr(queue, name).__module__ == queue.__name__


def test_training_responsibilities_have_real_module_owners():
    from app.services import lora_training as training
    from app.services import lora_training_checkpoints as checkpoints
    from app.services import lora_training_config_builder as config_builder
    from app.services import lora_training_export as export
    from app.services import lora_training_process as process
    from app.services import lora_training_settings as settings

    ownership = {
        settings: ('effective_train_settings', 'launch_settings_snapshot'),
        export: ('export_dataset_to_aitoolkit', 'export_registry_manifest'),
        config_builder: ('build_job_config', '_build_job_config_krea'),
        checkpoints: ('list_checkpoints', 'import_checkpoint'),
        process: ('launch_training', 'continue_training', 'stop_training'),
    }
    for owner, names in ownership.items():
        for name in names:
            assert getattr(training, name) is getattr(owner, name)
            assert getattr(owner, name).__module__ == owner.__name__
