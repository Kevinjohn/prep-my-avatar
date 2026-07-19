"""Minimal, verified adapter for the public Big-LaMa TorchScript model.

The previous third-party convenience package was only a thin model/download
wrapper and now constrains Pillow to known-vulnerable releases. Keeping this
adapter local lets the ML environment use supported dependencies and makes the
205 MB executable model download fail closed on a SHA-256 mismatch.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen


MODEL_URL = (
    'https://github.com/enesmsahin/simple-lama-inpainting/releases/'
    'download/v0.1.0/big-lama.pt'
)
MODEL_SHA256 = '7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c'
MODEL_SIZE = 205_803_670
_DOWNLOAD_TIMEOUT = 60
_CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _verified(path: Path) -> bool:
    try:
        return path.stat().st_size == MODEL_SIZE and _sha256(path) == MODEL_SHA256
    except OSError:
        return False


def _model_cache_path() -> Path:
    override = os.environ.get('LAMA_MODEL')
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f'LaMa TorchScript model not found: {path}')
        return path

    import torch

    cache_dir = Path(torch.hub.get_dir()) / 'checkpoints'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / 'big-lama.pt'


def _download_verified(path: Path) -> None:
    request = Request(MODEL_URL, headers={'User-Agent': 'LoRA-Dataset-Studio/1'})
    part_path = None
    try:
        with urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
            declared = response.headers.get('Content-Length')
            if declared is not None and int(declared) != MODEL_SIZE:
                raise RuntimeError(
                    f'LaMa model size mismatch: expected {MODEL_SIZE}, got {declared}')
            with tempfile.NamedTemporaryFile(
                    mode='wb', prefix='big-lama-', suffix='.part',
                    dir=path.parent, delete=False) as target:
                part_path = Path(target.name)
                digest = hashlib.sha256()
                total = 0
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MODEL_SIZE:
                        raise RuntimeError('LaMa model download exceeded its expected size')
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
        if total != MODEL_SIZE or digest.hexdigest() != MODEL_SHA256:
            raise RuntimeError('LaMa model download failed SHA-256 verification')
        os.replace(part_path, path)
        part_path = None
    finally:
        if part_path is not None:
            try:
                part_path.unlink()
            except OSError:
                pass


def model_path() -> Path:
    path = _model_cache_path()
    if os.environ.get('LAMA_MODEL'):
        return path
    if not _verified(path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        _download_verified(path)
    return path


def _image_array(value):
    import numpy as np
    from PIL import Image

    if isinstance(value, Image.Image):
        array = np.asarray(value)
    elif isinstance(value, np.ndarray):
        array = value.copy()
    else:
        raise TypeError('image and mask must be PIL images or NumPy arrays')
    if array.ndim == 2:
        array = array[None, ...]
    elif array.ndim == 3:
        array = array.transpose(2, 0, 1)
    else:
        raise ValueError('image and mask arrays must have two or three dimensions')
    return array.astype(np.float32) / 255.0


def _pad_to_multiple(array, multiple=8):
    import numpy as np

    _channels, height, width = array.shape
    padded_height = ((height + multiple - 1) // multiple) * multiple
    padded_width = ((width + multiple - 1) // multiple) * multiple
    return np.pad(
        array,
        ((0, 0), (0, padded_height - height), (0, padded_width - width)),
        mode='symmetric',
    )


def _pil_image(value, mode):
    import numpy as np
    from PIL import Image

    if isinstance(value, Image.Image):
        return value.convert(mode)
    if isinstance(value, np.ndarray):
        return Image.fromarray(value).convert(mode)
    raise TypeError('image and mask must be PIL images or NumPy arrays')


def _composite_masked(generated, source, mask):
    """Guarantee that model predictions never change unmasked source pixels."""
    from PIL import Image

    return Image.composite(
        generated.convert('RGB'), source.convert('RGB'), mask.convert('L'))


class LamaModel:
    def __init__(self, device):
        import torch

        self.device = device
        self.model = torch.jit.load(str(model_path()), map_location=device)
        self.model.eval().to(device)

    def __call__(self, image, mask):
        import numpy as np
        from PIL import Image
        import torch

        source_image = _pil_image(image, 'RGB')
        source_mask = _pil_image(mask, 'L')
        original_size = source_image.size
        image_array = _pad_to_multiple(_image_array(source_image))
        mask_array = _pad_to_multiple(_image_array(source_mask))
        image_tensor = torch.from_numpy(image_array).unsqueeze(0).to(self.device)
        mask_tensor = torch.from_numpy(mask_array).unsqueeze(0).to(self.device)
        mask_tensor = (mask_tensor > 0).to(image_tensor.dtype)
        with torch.inference_mode():
            result = self.model(image_tensor, mask_tensor)
        pixels = result[0].permute(1, 2, 0).detach().cpu().numpy()
        output = Image.fromarray(np.clip(pixels * 255, 0, 255).astype(np.uint8))
        output = output.crop((0, 0, *original_size))
        return _composite_masked(output, source_image, source_mask)
