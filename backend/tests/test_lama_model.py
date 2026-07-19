import hashlib

import pytest


class _Response:
    def __init__(self, payload, declared=None):
        self._payload = payload
        self._offset = 0
        self.headers = {}
        if declared is not None:
            self.headers['Content-Length'] = str(declared)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size):
        chunk = self._payload[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def _pin_payload(monkeypatch, module, payload):
    monkeypatch.setattr(module, 'MODEL_SIZE', len(payload))
    monkeypatch.setattr(module, 'MODEL_SHA256', hashlib.sha256(payload).hexdigest())


def test_download_verified_writes_only_verified_model(tmp_path, monkeypatch):
    from infer import lama_model

    payload = b'verified torchscript bytes'
    _pin_payload(monkeypatch, lama_model, payload)
    monkeypatch.setattr(
        lama_model, 'urlopen',
        lambda *_args, **_kwargs: _Response(payload, len(payload)))
    target = tmp_path / 'big-lama.pt'

    lama_model._download_verified(target)

    assert target.read_bytes() == payload
    assert not list(tmp_path.glob('*.part'))


def test_download_hash_mismatch_leaves_no_model_or_partial(tmp_path, monkeypatch):
    from infer import lama_model

    payload = b'tampered'
    monkeypatch.setattr(lama_model, 'MODEL_SIZE', len(payload))
    monkeypatch.setattr(lama_model, 'MODEL_SHA256', '0' * 64)
    monkeypatch.setattr(
        lama_model, 'urlopen',
        lambda *_args, **_kwargs: _Response(payload, len(payload)))
    target = tmp_path / 'big-lama.pt'

    with pytest.raises(RuntimeError, match='SHA-256'):
        lama_model._download_verified(target)

    assert not target.exists()
    assert not list(tmp_path.glob('*.part'))


def test_download_rejects_wrong_declared_size_before_writing(tmp_path, monkeypatch):
    from infer import lama_model

    payload = b'model'
    _pin_payload(monkeypatch, lama_model, payload)
    monkeypatch.setattr(
        lama_model, 'urlopen',
        lambda *_args, **_kwargs: _Response(payload, len(payload) + 1))

    with pytest.raises(RuntimeError, match='size mismatch'):
        lama_model._download_verified(tmp_path / 'big-lama.pt')

    assert list(tmp_path.iterdir()) == []


def test_image_preparation_pads_to_model_multiple_without_changing_channels():
    np = pytest.importorskip('numpy')
    from infer import lama_model

    source = np.zeros((9, 10, 3), dtype=np.uint8)
    prepared = lama_model._pad_to_multiple(lama_model._image_array(source))

    assert prepared.shape == (3, 16, 16)
    assert prepared.dtype == np.float32


def test_masked_composite_preserves_every_unmasked_pixel():
    from PIL import Image, ImageDraw
    from infer import lama_model

    source = Image.new('RGB', (8, 8), 'red')
    generated = Image.new('RGB', (8, 8), 'blue')
    mask = Image.new('L', (8, 8), 0)
    ImageDraw.Draw(mask).rectangle((2, 2, 5, 5), fill=255)

    result = lama_model._composite_masked(generated, source, mask)

    assert result.getpixel((0, 0)) == (255, 0, 0)
    assert result.getpixel((3, 3)) == (0, 0, 255)
