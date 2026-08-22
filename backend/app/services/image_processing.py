"""Image normalization, the vision bounding-box calls, and their pure parsers.

Only `normalize_to_webp`, `_bbox_from_vision_json`/`parse_watermark_bbox` and
`face_crop_to_square_webp(use_vision=False)` are pure. `detect_head_bbox` and
`detect_watermark_bbox` POST to a local Ollama and cost seconds each; the split
between them and the parsers is deliberate, so a batch can tell an EMPTY vision
answer apart from a clean "no watermark here".
"""

import io
import json

from PIL import Image, ImageOps

from .face_variations import HEAD_BBOX_PROMPT, WATERMARK_BBOX_PROMPT


WATERMARK_BBOX_MARGIN = 0.025


def normalize_to_webp(image_bytes: bytes, size: int = 1024) -> bytes:
    """Downscale to a bounded longest side while preserving aspect ratio."""
    with Image.open(io.BytesIO(image_bytes)) as opened, \
            ImageOps.exif_transpose(opened).convert('RGB') as image:
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, 'WEBP', quality=92)
    return output.getvalue()


def _bbox_from_vision_json(raw, *, honour_present=False):
    """Decode one bbox answer from a vision model into ``(x1, y1, x2, y2)`` in
    [0, 1], or ``None`` when there is no usable box.

    Both bbox prompts share this wire format and both had their own copy of it,
    with different exception tuples covering the same failures. The rules it
    states, in order: the answer is the FIRST ``{...}`` in a reply that may be
    wrapped in prose; the model emits a 0-1000 grid; Qwen3-VL routinely emits
    SWAPPED corners, so min/max rather than trust; and anything outside the grid
    (or degenerate) is rejected rather than clamped, because a box the model got
    that wrong is not evidence of where the subject is.

    ``honour_present`` is the watermark prompt's extra turn: it can answer
    "there is no watermark" explicitly, which is a different fact from an
    unparseable reply and must not be confused with one by the caller.
    """
    try:
        start = raw.index('{')
        parsed = json.loads(raw[start:raw.index('}', start) + 1])
        if honour_present and 'present' in parsed and not parsed.get('present'):
            return None
        y1, x1, y2, x2 = (float(parsed[key]) for key in ('y1', 'x1', 'y2', 'x2'))
    except (ValueError, KeyError, AttributeError, TypeError):
        return None
    x1, x2 = min(x1, x2), max(x1, x2)
    y1, y2 = min(y1, y2), max(y1, y2)
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        return None
    return x1 / 1000.0, y1 / 1000.0, x2 / 1000.0, y2 / 1000.0


def detect_head_bbox(image_bytes):
    """Return the primary head as normalized coordinates, or ``None``."""
    try:
        from .vision_ollama import describe_image_ollama
    except ImportError:
        return None
    raw = describe_image_ollama(
        image_bytes,
        HEAD_BBOX_PROMPT,
        num_predict=400,
        prefer_json=True,
        fmt='json',
    )
    return _bbox_from_vision_json(raw)


def parse_watermark_bbox(raw):
    """Parse and margin-expand a vision watermark response.

    The margin is this parser's own, not part of the shared decode: VLM
    watermark boxes run tight, and an unexpanded box leaves a rim of the mark
    behind after the crop or inpaint. A head box wants no such padding.
    """
    box = _bbox_from_vision_json(raw, honour_present=True)
    if box is None:
        return None
    x1, y1, x2, y2 = box
    margin = WATERMARK_BBOX_MARGIN
    return (
        max(0.0, x1 - margin),
        max(0.0, y1 - margin),
        min(1.0, x2 + margin),
        min(1.0, y2 + margin),
    )


def detect_watermark_bbox(image_bytes, *, keep_alive=0):
    """Return a normalized overlay-watermark box, or ``None``."""
    try:
        from .vision_ollama import describe_image_ollama
    except ImportError:
        return None
    raw = describe_image_ollama(
        image_bytes,
        WATERMARK_BBOX_PROMPT,
        num_predict=400,
        prefer_json=True,
        fmt='json',
        keep_alive=keep_alive,
    )
    return parse_watermark_bbox(raw)


def face_crop_to_square_webp(
    image_bytes: bytes,
    size: int = 1024,
    pad: float = 1.7,
    *,
    return_detected: bool = False,
    use_vision: bool = True,
    return_scale: bool = False,
    detector=detect_head_bbox,
):
    """Crop around a detected head, or fall back to the largest centered square."""
    with Image.open(io.BytesIO(image_bytes)) as opened, \
            ImageOps.exif_transpose(opened).convert('RGB') as image:
        width, height = image.size
        normalized = detector(image_bytes) if use_vision else None
        half = 0
        if normalized:
            x1, y1, x2, y2 = (
                normalized[0] * width,
                normalized[1] * height,
                normalized[2] * width,
                normalized[3] * height,
            )
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2 - (y2 - y1) * 0.10
            half = max(x2 - x1, y2 - y1) * pad / 2
            half = min(half, center_x, width - center_x, center_y, height - center_y)
        head_detected = half >= 8
        if head_detected:
            box = (
                int(center_x - half),
                int(center_y - half),
                int(center_x + half),
                int(center_y + half),
            )
        else:
            side = min(width, height)
            left, top = (width - side) // 2, (height - side) // 2
            box = left, top, left + side, top + side
        scale = size / max(1, box[2] - box[0])
        output = io.BytesIO()
        with image.crop(box) as cropped, cropped.resize(
            (size, size), Image.Resampling.LANCZOS,
        ) as resized:
            resized.save(output, 'WEBP', quality=92)
    webp = output.getvalue()
    if return_detected and return_scale:
        return webp, head_detected, scale
    if return_detected:
        return webp, head_detected
    if return_scale:
        return webp, scale
    return webp
