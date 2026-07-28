"""Tests for the lifted app.utils.comfyui module: the shared trained-LoRA
parser (label + group MUST share one parse — the drift-proof invariant),
config-driven listers (empty/None-safe when ComfyUI isn't configured), and
the LoRA-chain injectors (allowed-whitelist respected)."""
from app.utils.comfyui import (
    trained_lora_group, format_trained_lora_label, family_of_lora,
    inject_zimage_loras,
)


def test_label_and_group_share_parse():
    a = r'z image\lora_Lola_000002000.safetensors'
    b = r'z image\lora_Lola_000002500.safetensors'
    ga, _ = trained_lora_group(a, 'zimage')
    gb, _ = trained_lora_group(b, 'zimage')
    assert ga == gb                                  # siblings collapse
    assert '2000' in format_trained_lora_label(a, 'zimage')
    assert '2500' in format_trained_lora_label(b, 'zimage')


def test_base_tag_separates_groups():
    x = r'z image\lora_Lola_000002000_bigLove.safetensors'
    y = r'z image\lora_Lola_000002000.safetensors'
    assert trained_lora_group(x, 'zimage')[0] != trained_lora_group(y, 'zimage')[0]


def test_family_of_lora():
    assert family_of_lora(r'sdxl\lora_A_000001000.safetensors') == 'sdxl'
    assert family_of_lora(r'krea\x.safetensors') == 'krea'
    assert family_of_lora(r'z image\x.safetensors') == 'zimage'
    # flux vs flux2klein: the folder prefixes must never swallow each other.
    assert family_of_lora(r'flux\x.safetensors') == 'flux'
    assert family_of_lora(r'flux2klein\x.safetensors') == 'flux2klein'
    assert family_of_lora(r'unknown\x.safetensors') is None


def test_listers_empty_when_unconfigured(app):
    from app.utils.comfyui import (get_zimage_loras, get_sdxl_loras, get_krea_loras,
                                    get_zimage_models, get_krea_models, get_checkpoint_models)
    with app.app_context():
        assert get_zimage_loras() == []
        assert get_sdxl_loras() == []
        assert get_krea_loras() == []
        assert get_zimage_models() == []
        assert get_krea_models() == []
        assert get_checkpoint_models() == []


def test_resolve_checkpoint_ckpt_name_unconfigured_falls_back_to_name(app):
    from app.utils.comfyui import resolve_checkpoint_ckpt_name
    with app.app_context():
        assert resolve_checkpoint_ckpt_name('foo.safetensors') == 'foo.safetensors'
        assert resolve_checkpoint_ckpt_name('') == ''
        assert resolve_checkpoint_ckpt_name('sdxl/foo.safetensors') == 'sdxl/foo.safetensors'


def test_checkpoint_models_preserve_duplicate_relative_paths(app, tmp_path, monkeypatch):
    """A basename is not a checkpoint identity when nested folders are supported."""
    from app.utils import comfyui

    output_dir = tmp_path / 'comfyui' / 'output'
    checkpoints = tmp_path / 'comfyui' / 'models' / 'checkpoints'
    output_dir.mkdir(parents=True)
    (checkpoints / 'Biglove').mkdir(parents=True)
    (checkpoints / 'sdxl').mkdir()
    (checkpoints / 'Biglove' / 'duplicate.safetensors').write_bytes(b'a')
    (checkpoints / 'sdxl' / 'duplicate.safetensors').write_bytes(b'b')

    with app.app_context():
        monkeypatch.setattr(comfyui, '_out_dir', lambda: str(output_dir))
        comfyui.clear_model_caches()
        names = [item['name'] for item in comfyui.get_checkpoint_models()]

        assert names == [
            'Biglove/duplicate.safetensors',
            'sdxl/duplicate.safetensors',
        ]
        assert comfyui.resolve_checkpoint_ckpt_name(names[0]) == names[0]
        # A legacy ambiguous basename must not select whichever os.walk sees first.
        assert comfyui.resolve_checkpoint_ckpt_name('duplicate.safetensors') == 'duplicate.safetensors'


def test_resolve_unique_legacy_checkpoint_basename(app, tmp_path, monkeypatch):
    from app.utils import comfyui

    output_dir = tmp_path / 'comfyui' / 'output'
    checkpoint = tmp_path / 'comfyui' / 'models' / 'checkpoints' / 'Biglove' / 'only.safetensors'
    output_dir.mkdir(parents=True)
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b'model')

    with app.app_context():
        monkeypatch.setattr(comfyui, '_out_dir', lambda: str(output_dir))
        assert comfyui.resolve_checkpoint_ckpt_name('only.safetensors') == 'Biglove/only.safetensors'


def test_checkpoint_cache_serves_both_wire_shapes_from_one_scan(app, tmp_path, monkeypatch):
    from app.utils import comfyui

    output_dir = tmp_path / 'comfyui' / 'output'
    checkpoint = tmp_path / 'comfyui' / 'models' / 'checkpoints' / 'model.safetensors'
    output_dir.mkdir(parents=True)
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b'model')
    real_walk = comfyui.os.walk
    scans = 0

    def counting_walk(path):
        nonlocal scans
        scans += 1
        return real_walk(path)

    with app.app_context():
        monkeypatch.setattr(comfyui, '_out_dir', lambda: str(output_dir))
        monkeypatch.setattr(comfyui.os, 'walk', counting_walk)
        comfyui.clear_model_caches()
        assert comfyui.get_checkpoint_models() == [
            {'name': 'model.safetensors', 'civitai_url': None},
        ]
        assert comfyui.get_checkpoint_models(include_hidden=True) == ['model.safetensors']

    assert scans == 1


def test_api_address_has_default_even_when_unconfigured(app):
    from app.utils.comfyui import api_address
    with app.app_context():
        assert api_address() == 'http://127.0.0.1:8188'


def test_api_address_reflects_config(app):
    from app.utils.comfyui import api_address
    from app import config as cfg
    with app.app_context():
        cfg.save_config({'comfyui': {'api_url': 'http://192.168.1.50:8188'}})
        assert api_address() == 'http://192.168.1.50:8188'


def test_listers_use_configured_dirs(app, tmp_path):
    """Once comfyui.base_dir is set, the trained-LoRA listers must find files
    under models/loras/<family>/ (not just report empty)."""
    from app.utils.comfyui import get_zimage_loras
    from app import config as cfg
    with app.app_context():
        base = tmp_path / 'comfyui'
        lora_dir = base / 'models' / 'loras' / 'z image'
        lora_dir.mkdir(parents=True)
        (lora_dir / 'lora_Lola_000002000.safetensors').write_bytes(b'')
        cfg.save_config({'comfyui': {'base_dir': str(base)}})
        result = get_zimage_loras()
        assert len(result) == 1
        assert result[0]['filename'] == 'z image\\lora_Lola_000002000.safetensors'
        assert result[0]['group'] is not None


def test_clear_model_caches_forces_rescan(app, tmp_path):
    """The gotcha: get_zimage_models caches even an EMPTY scan (unconfigured), so a
    base_dir set afterwards stays invisible for the 5-min TTL. clear_model_caches()
    must drop that stale empty result so the newly-configured models appear at once."""
    from app.utils import comfyui
    from app import config as cfg
    with app.app_context():
        comfyui.clear_model_caches()                      # clean slate (caches are process-global)
        assert comfyui.get_zimage_models() == []          # primes the cache with []
        base = tmp_path / 'comfyui'
        zdir = base / 'models' / 'unet' / 'z image'
        zdir.mkdir(parents=True)
        (zdir / 'merge_a.safetensors').write_bytes(b'')
        cfg.save_config({'comfyui': {'base_dir': str(base)}})
        assert comfyui.get_zimage_models() == []          # stale [] still served (TTL)
        comfyui.clear_model_caches()
        assert 'z image\\merge_a.safetensors' in comfyui.get_zimage_models()


def test_put_settings_comfyui_clears_model_caches(client):
    """Saving a comfyui section must invalidate the lister caches (so the training-base
    dropdown reflects a just-set base_dir), while a non-comfyui save leaves them alone."""
    from app.utils import comfyui
    comfyui._zimage_models_cache['data'] = ['stale']      # pretend a prior scan cached something
    comfyui._zimage_models_cache['timestamp'] = 9e18
    client.put('/api/settings', json={'config': {'ollama': {'url': 'http://127.0.0.1:11434'}}})
    assert comfyui._zimage_models_cache['data'] == ['stale']   # untouched (no comfyui section)
    client.put('/api/settings', json={'config': {'comfyui': {'base_dir': ''}}})
    assert comfyui._zimage_models_cache['data'] is None        # invalidated


def test_inject_zimage_loras_rewires_consumer_and_respects_allowed():
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z image\\base.safetensors"}},
        "7": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0], "steps": 20}},
    }
    injected = inject_zimage_loras(
        workflow,
        [{'filename': 'z image\\l.safetensors', 'strength': 1.0}],
        allowed={'z image\\l.safetensors'},
    )
    assert injected == 1
    lora_nodes = [n for n in workflow.values() if n.get("class_type") == "LoraLoaderModelOnly"]
    assert len(lora_nodes) == 1
    lora_node_id = [k for k, v in workflow.items() if v is lora_nodes[0]][0]
    # Consumer (node 7) must be rewired to point at the injected LoRA node, not node 1.
    assert workflow["7"]["inputs"]["model"] == [lora_node_id, 0]


def test_inject_zimage_loras_empty_allowed_injects_nothing():
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z image\\base.safetensors"}},
        "7": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0]}},
    }
    injected = inject_zimage_loras(
        workflow,
        [{'filename': 'z image\\l.safetensors', 'strength': 1.0}],
        allowed=set(),
    )
    assert injected == 0
    assert workflow["7"]["inputs"]["model"] == ["1", 0]  # untouched
    assert not any(n.get("class_type") == "LoraLoaderModelOnly" for n in workflow.values())


def test_lora_injectors_do_not_create_orphans_without_consumers():
    from app.utils.comfyui import inject_krea_loras

    z_workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "base.safetensors"}},
    }
    assert inject_zimage_loras(
        z_workflow,
        [{"filename": "z image/lora.safetensors", "strength": 1}],
        allowed={"z image/lora.safetensors"},
    ) == 0
    assert set(z_workflow) == {"1"}

    krea_workflow = {
        "20": {"class_type": "UNETLoader", "inputs": {"unet_name": "base.safetensors"}},
    }
    assert inject_krea_loras(
        krea_workflow,
        [{"filename": "krea/lora.safetensors", "strength": 1}],
        allowed={"krea/lora.safetensors"},
    ) == 0
    assert set(krea_workflow) == {"20"}


def test_sampler_params_path_points_to_backend_workflows():
    from app.utils import comfyui
    from app import config as cfg
    assert comfyui._SAMPLER_PARAMS_JSON_PATH == str(cfg.BACKEND_DIR / 'workflows' / 'sampler_params.json')


def test_apply_optimal_sampler_params_uses_code_defaults(app):
    """With the shipped backend/workflows/sampler_params.json (empty overrides),
    a known SDXL checkpoint must still get its code-default sampler/scheduler/cfg."""
    from app.utils.comfyui import apply_optimal_sampler_params
    with app.app_context():
        workflow = {
            "1": {"class_type": "KSampler",
                  "inputs": {"sampler_name": "euler", "scheduler": "normal", "cfg": 7.0, "steps": 20}},
        }
        apply_optimal_sampler_params(workflow, "bigLove_photo5.safetensors")
        inputs = workflow["1"]["inputs"]
        assert inputs["sampler_name"] == "lcm"
        assert inputs["scheduler"] == "ddim_uniform"
        assert inputs["cfg"] == 1.0
        assert inputs["steps"] == 20  # steps intentionally left untouched


def test_partial_sampler_override_preserves_missing_selector_fields(app, monkeypatch):
    from app.utils import comfyui

    workflow = {
        "select": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "schedule": {"class_type": "BasicScheduler", "inputs": {
            "scheduler": "normal", "steps": 20,
        }},
        "sample": {"class_type": "KSampler", "inputs": {
            "sampler_name": "euler", "scheduler": "normal", "cfg": 7.0,
        }},
    }
    monkeypatch.setattr(comfyui, '_resolve_optimal_params', lambda _name: {'cfg': 1.5})

    with app.app_context():
        comfyui.apply_optimal_sampler_params(workflow, 'custom.safetensors')

    assert workflow['select']['inputs']['sampler_name'] == 'euler'
    assert workflow['schedule']['inputs']['scheduler'] == 'normal'
    assert workflow['sample']['inputs']['cfg'] == 1.5
