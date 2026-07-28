import io
import json
import os
import sys
import types

import pytest
from PIL import Image

from infer import face_score_infer, joycaption_infer, lama_infer, mask_infer


def _import_converter(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace())
    package = types.ModuleType("safetensors")
    module = types.ModuleType("safetensors.torch")
    module.load_file = lambda _path: {}
    module.save_file = lambda _state, _path: None
    package.torch = module
    monkeypatch.setitem(sys.modules, "safetensors", package)
    monkeypatch.setitem(sys.modules, "safetensors.torch", module)
    sys.modules.pop("infer.convert_comfy_zimage_to_diffusers", None)
    from infer import convert_comfy_zimage_to_diffusers
    return convert_comfy_zimage_to_diffusers


def test_converter_returns_failure_when_gate_fails(monkeypatch):
    converter = _import_converter(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["converter", "input.safetensors", "config.json"])
    monkeypatch.setattr(converter, "build_diffusers_state_dict", lambda _path: {})
    monkeypatch.setattr(converter, "gate", lambda _state, _config: False)

    assert converter.main() == 1


def test_converter_validates_cli_arguments(monkeypatch):
    converter = _import_converter(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["converter"])

    assert converter.main() == 2


def test_zimage_mapping_matches_pinned_comfyui_fixture(monkeypatch):
    converter = _import_converter(monkeypatch)
    fixture_path = (
        __import__('pathlib').Path(__file__).parent / 'fixtures'
        / 'zimage_mapping_comfyui_5151cff.json')
    fixture = json.loads(fixture_path.read_text(encoding='utf-8'))

    assert converter.COMFYUI_MAPPING_REVISION == fixture['upstream_revision']
    mapping = converter.z_image_to_diffusers(fixture['config'])
    for key, expected in fixture['representative'].items():
        actual = mapping[key]
        if isinstance(expected, list):
            assert actual == (expected[0], tuple(expected[1]))
        else:
            assert actual == expected


def test_lama_atomic_save_preserves_format_and_original_on_replace_failure(
        monkeypatch, tmp_path):
    path = tmp_path / "source.png"
    Image.new("RGB", (4, 4), "red").save(path)
    original = path.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("disk failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk failure"):
        lama_infer._save_atomic(Image.new("RGB", (4, 4), "blue"), str(path))

    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".lama-*"))


def test_lama_atomic_save_uses_lossless_storage_and_rejects_jpeg(tmp_path):
    for suffix, expected in ((".png", "PNG"), (".webp", "WEBP")):
        path = tmp_path / f"source{suffix}"
        Image.new("RGB", (4, 4), "blue").save(path)
        lama_infer._save_atomic(Image.new("RGB", (4, 4), "red"), str(path))
        with Image.open(path) as image:
            assert image.format == expected
    jpeg = tmp_path / "source.jpg"
    Image.new("RGB", (4, 4), "blue").save(jpeg)
    with pytest.raises(ValueError, match="migrated to PNG"):
        lama_infer._save_atomic(Image.new("RGB", (4, 4), "red"), str(jpeg))


def test_face_model_cache_repair_completes_a_partial_outer_cache(tmp_path):
    outer = tmp_path / "models" / "antelopev2"
    inner = outer / "antelopev2"
    inner.mkdir(parents=True)
    (inner / "one.onnx").write_bytes(b"one")
    (inner / "two.onnx").write_bytes(b"two")
    (outer / "one.onnx").write_bytes(b"one")

    face_score_infer._repair_nested_antelopev2(str(tmp_path))

    assert (outer / "two.onnx").read_bytes() == b"two"
    assert (inner / "two.onnx").exists()
    assert not list(outer.glob(".antelopev2-*"))


def _run_mask(monkeypatch, capsys, payload, remove):
    fake_rembg = types.SimpleNamespace(new_session=lambda _name: object(), remove=remove)
    monkeypatch.setitem(sys.modules, "rembg", fake_rembg)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = mask_infer.main()
    return code, json.loads(capsys.readouterr().out)


def test_mask_worker_rejects_colliding_output_names(monkeypatch, capsys, tmp_path):
    payload = {"images": ["one/a.jpg", "two/a.png"], "out_dir": str(tmp_path)}

    code, response = _run_mask(monkeypatch, capsys, payload, lambda *_a, **_k: None)

    assert code == 1
    assert response["ok"] is False
    assert "unique output stems" in response["error"]


def test_mask_worker_reports_partial_batch_as_failure(monkeypatch, capsys, tmp_path):
    good = tmp_path / "good.jpg"
    bad = tmp_path / "bad.jpg"
    Image.new("RGB", (4, 4), "white").save(good)
    Image.new("RGB", (4, 4), "white").save(bad)

    def remove(image, **_kwargs):
        if getattr(remove, "called", False):
            raise RuntimeError("failed")
        remove.called = True
        return image.convert("L")

    code, response = _run_mask(
        monkeypatch, capsys,
        {"images": [str(good), str(bad)], "out_dir": str(tmp_path / "masks")},
        remove,
    )

    assert code == 1
    assert response["ok"] is False
    assert response["written"] == 1


@pytest.mark.parametrize("images", ["abc", [""], []])
def test_workers_reject_invalid_image_collections(monkeypatch, capsys, tmp_path, images):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "images": images, "out_dir": str(tmp_path), "ref": "ref.jpg",
    })))
    assert mask_infer.main() == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_joycaption_initialization_failure_is_structured(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"images": ["a.png"]})))
    monkeypatch.setitem(sys.modules, "torch", None)

    assert joycaption_infer.main() == 1
    response = json.loads(capsys.readouterr().out)
    assert response["captions"] == {}
    assert "_init" in response["errors"]


@pytest.mark.parametrize("max_tokens", [0, -1, 2049, "many"])
def test_joycaption_validates_token_bounds(monkeypatch, capsys, max_tokens):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "images": ["a.png"], "max_tokens": max_tokens,
    })))

    assert joycaption_infer.main() == 1
    assert "_input" in json.loads(capsys.readouterr().out)["errors"]


def test_joycaption_seed_uses_supported_generate_kwargs_and_restores_rng():
    class ForkRng:
        def __init__(self, torch):
            self.torch = torch

        def __enter__(self):
            self.saved = self.torch.state

        def __exit__(self, *_args):
            self.torch.state = self.saved

    class FakeTorch:
        state = 777

        class cuda:
            @staticmethod
            def is_available():
                return False

        class random:
            @staticmethod
            def fork_rng(*, devices, enabled):
                assert devices == [] and enabled is True
                return ForkRng(torch)

        @staticmethod
        def manual_seed(seed):
            FakeTorch.state = seed

        @staticmethod
        def sample():
            FakeTorch.state = (FakeTorch.state * 1103515245 + 12345) % (2 ** 31)
            return FakeTorch.state

    torch = FakeTorch()

    class StrictGenerationMixin:
        allowed = {
            'input_ids', 'pixel_values', 'attention_mask', 'max_new_tokens',
            'do_sample', 'temperature', 'top_p', 'suppress_tokens', 'use_cache',
        }

        def generate(self, **kwargs):
            unknown = set(kwargs) - self.allowed
            if unknown:
                raise TypeError(f'unused model_kwargs: {sorted(unknown)}')
            return [torch.sample() for _ in range(4)]

    model = StrictGenerationMixin()
    before = torch.state
    first = joycaption_infer._generate_with_seed(
        torch, model, 91, input_ids=object(), pixel_values=object())
    after = torch.state
    second = joycaption_infer._generate_with_seed(
        torch, model, 91, input_ids=object(), pixel_values=object())
    different = joycaption_infer._generate_with_seed(
        torch, model, 92, input_ids=object(), pixel_values=object())

    assert before == after
    assert first == second
    assert first != different


def test_face_worker_rejects_invalid_protocol_without_loading_models(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({
        'ref': 'ref.png', 'images': 'not-a-list',
    })))
    assert face_score_infer.main() == 1
    response = json.loads(capsys.readouterr().out)
    assert response['ref_ok'] is False
    assert response['results'] == {}


def test_mask_worker_persists_a_valid_png(monkeypatch, capsys, tmp_path):
    source = tmp_path / 'source.jpg'
    output = tmp_path / 'masks'
    Image.new('RGB', (5, 4), 'white').save(source)
    code, response = _run_mask(
        monkeypatch, capsys, {'images': [str(source)], 'out_dir': str(output)},
        lambda image, **kwargs: Image.new('L', image.size, 255),
    )
    assert code == 0 and response['written'] == 1
    with Image.open(output / 'source.png') as persisted:
        assert persisted.format == 'PNG'
        assert persisted.mode == 'L'
        assert persisted.size == (5, 4)


def test_lama_batch_emits_ack_after_each_persisted_file(monkeypatch, capsys, tmp_path):
    first = tmp_path / 'first.png'
    second = tmp_path / 'second.png'
    Image.new('RGB', (6, 6), 'red').save(first)
    Image.new('RGB', (6, 6), 'blue').save(second)
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        device=lambda value: value,
    )

    class FakeLama:
        def __init__(self, device):
            assert device == 'cpu'

        def __call__(self, image, mask):
            return Image.new('RGB', image.size, 'green')

    monkeypatch.setitem(sys.modules, 'torch', fake_torch)
    monkeypatch.setitem(sys.modules, 'lama_model', types.SimpleNamespace(LamaModel=FakeLama))
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({
        'device': 'cpu',
        'jobs': [
            {'image_path': str(first), 'bboxes': [[0, 0, 0.5, 0.5]]},
            {'image_path': str(second), 'bboxes': [[0.5, 0.5, 1, 1]]},
        ],
    })))

    assert lama_infer.main() == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line['image_path'] for line in lines[:2]] == [str(first), str(second)]
    assert all(line['type'] == 'result' and line['ok'] for line in lines[:2])
    assert lines[-1]['ok'] is True and len(lines[-1]['results']) == 2
    for path in (first, second):
        assert Image.open(path).getpixel((0, 0)) == (0, 128, 0)
