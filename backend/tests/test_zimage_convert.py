from pathlib import Path
from types import SimpleNamespace

import pytest


def _configure(monkeypatch, module, tmp_path):
    root = tmp_path / 'converted'
    merge = tmp_path / 'merge.safetensors'
    config = tmp_path / 'official.json'
    merge.write_bytes(b'merge')
    config.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(module, '_converted_root', lambda: root)
    monkeypatch.setattr(module, '_resolve_merge', lambda model: str(merge))
    monkeypatch.setattr(module, '_official_config', lambda: str(config))
    monkeypatch.setattr(module, '_venv_python', lambda: Path('/python'))
    return root


def test_failed_conversion_is_not_published(app, monkeypatch, tmp_path):
    from app.services import zimage_convert as convert

    _configure(monkeypatch, convert, tmp_path)

    def fail(command, **kwargs):
        output = Path(command[-1])
        (output / 'transformer').mkdir()
        (output / 'transformer' / 'config.json').write_text('{}')
        (output / 'transformer' / 'diffusion_pytorch_model.safetensors').write_bytes(b'partial')
        return SimpleNamespace(returncode=1, stdout='failed', stderr='broken')

    monkeypatch.setattr(convert.subprocess, 'run', fail)
    with pytest.raises(ValueError, match='conversion failed'):
        convert.convert('model.safetensors')
    assert not convert.is_converted('model.safetensors')
    assert not Path(convert.converted_dir('model.safetensors')).exists()


def test_successful_conversion_is_atomically_marked_complete(app, monkeypatch, tmp_path):
    from app.services import zimage_convert as convert

    _configure(monkeypatch, convert, tmp_path)

    def succeed(command, **kwargs):
        output = Path(command[-1])
        (output / 'transformer').mkdir()
        (output / 'transformer' / 'config.json').write_text('{}')
        (output / 'transformer' / 'diffusion_pytorch_model.safetensors').write_bytes(b'weights')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(convert.subprocess, 'run', succeed)
    result = convert.convert('model.safetensors')
    assert Path(result, '.conversion-complete').read_text() == 'ok\n'
    assert convert.is_converted('model.safetensors')


def test_convert_status_reconciles_orphaned_running_state(app, monkeypatch):
    from app.services import zimage_convert as convert
    convert._active_conversions.clear()
    monkeypatch.setattr(convert, 'is_converted', lambda model: False)
    monkeypatch.setattr(convert.queue_manager, '_get_system_state',
                        lambda key, default: {'z_model': 'model.safetensors',
                                              'status': 'running'})
    saved = []
    monkeypatch.setattr(convert.queue_manager, '_set_system_state',
                        lambda key, state, ttl_seconds: saved.append(state))

    state = convert.convert_status()

    assert state['status'] == 'error'
    assert 'interrupted' in state['error']
    assert saved == [state]


def test_start_convert_records_thread_start_failure(app, monkeypatch, tmp_path):
    from app.services import zimage_convert as convert
    convert._active_conversions.clear()
    monkeypatch.setattr(convert, '_resolve_merge', lambda model: str(tmp_path / model))
    monkeypatch.setattr(convert, '_converted_root', lambda: tmp_path / 'converted')
    monkeypatch.setattr(convert, 'assert_free_disk', lambda *args: None)
    monkeypatch.setattr(convert.queue_manager, '_get_system_state', lambda key, default: {})
    saved = []
    monkeypatch.setattr(convert.queue_manager, '_set_system_state',
                        lambda key, state, ttl_seconds: saved.append(state))

    class BrokenThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError('no threads')

    monkeypatch.setattr(convert.threading, 'Thread', BrokenThread)
    with pytest.raises(RuntimeError, match='no threads'):
        convert.start_convert_async(app, 'model.safetensors')
    assert saved[-1]['status'] == 'error'
    assert 'failed to start' in saved[-1]['error']
    assert 'model.safetensors' not in convert._active_conversions
