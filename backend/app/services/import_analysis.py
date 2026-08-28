"""Cheap, local-first analysis for imported photos.

This pass deliberately stays independent of Ollama, InsightFace, OpenCV, and
the GPU. It gives the import-first workflow an honest technical signal before
any optional vision pass runs. The result is stored as provenance metadata and
never replaces human review or identity scoring.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from typing import Any

from PIL import Image, ImageFilter, ImageOps


ANALYSIS_VERSION = 2

_SHARPNESS_THUMBNAIL_SIDE = 768
_LAPLACIAN = (0, 1, 0, 1, -4, 1, 0, 1, 0)
_LAPLACIAN_NEG = tuple(-coefficient for coefficient in _LAPLACIAN)
# Scaling each signed half by four keeps the complete 4-neighbour response in
# Pillow's 8-bit output without clipping. The original magnitude is restored
# when the histogram moments are combined below.
_LAPLACIAN_SCALE = 4
_SHARPNESS_TILE_GRID = 8
_SHARPNESS_TILE_MIN_SIDE = 32
_SHARPNESS_PERCENTILE = 0.90
# PROVISIONAL: separates the deterministic contract corpus while preserving the
# existing 35/55 public bands. Checkpoint QS cannot sign this off until the same
# mapping is recalibrated against rights-cleared real photographs as documented
# in tasks/reference-corpus/README.md.
_SHARPNESS_SCORE_SCALE = 13.5


def _bounded_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _grey_thumbnail(image: Image.Image, side: int) -> Image.Image:
    """A bounded greyscale copy of `image`, safe to mutate.

    ``ImageOps.grayscale`` already returns a NEW image, so the ``.copy()`` these
    two callers used to make first was a full second copy of the source RGB —
    tens of megabytes per photo, twice per import, thrown away immediately.
    Converting first and shrinking after is the whole trick; the caller's own
    ``thumbnail`` then mutates a picture nobody else holds."""
    grey = ImageOps.grayscale(image)
    grey.thumbnail((side, side))
    return grey


def _histogram_moments(histogram: list[int]) -> tuple[float, float]:
    total = sum(histogram)
    if not total:
        return 0.0, 0.0
    mean = sum(value * count for value, count in enumerate(histogram)) / total
    mean_square = (
        sum(value * value * count for value, count in enumerate(histogram)) / total
    )
    return mean, mean_square


def _laplacian_variance(
    positive: Image.Image, negative: Image.Image, box: tuple[int, int, int, int]
) -> float:
    """Recover signed Laplacian variance inside one already-filtered tile."""
    positive_mean, positive_square = _histogram_moments(
        positive.crop(box).histogram()
    )
    negative_mean, negative_square = _histogram_moments(
        negative.crop(box).histogram()
    )
    mean = _LAPLACIAN_SCALE * (positive_mean - negative_mean)
    mean_square = _LAPLACIAN_SCALE**2 * (
        positive_square + negative_square
    )
    return max(0.0, mean_square - mean * mean)


def _sharpness_tile_boxes(
    box: tuple[int, int, int, int],
) -> list[tuple[int, int, int, int]]:
    """Split an interior into at most 8x8 tiles without creating tiny tiles."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    columns = max(
        1, min(_SHARPNESS_TILE_GRID, width // _SHARPNESS_TILE_MIN_SIDE)
    )
    rows = max(1, min(_SHARPNESS_TILE_GRID, height // _SHARPNESS_TILE_MIN_SIDE))
    xs = [left + round(index * width / columns) for index in range(columns + 1)]
    ys = [top + round(index * height / rows) for index in range(rows + 1)]
    return [
        (xs[column], ys[row], xs[column + 1], ys[row + 1])
        for row in range(rows)
        for column in range(columns)
    ]


def _nearest_rank_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _sharpness_score(image: Image.Image) -> int:
    thumbnail = _grey_thumbnail(image, _SHARPNESS_THUMBNAIL_SIDE)
    width, height = thumbnail.size
    # Pillow leaves a one-pixel Kernel border unfiltered. Including that raw
    # border makes a flat image appear sharp, so images without an interior have
    # no usable focus signal.
    if width < 3 or height < 3:
        return 0
    interior = (1, 1, width - 1, height - 1)
    positive = thumbnail.filter(
        ImageFilter.Kernel(
            (3, 3), _LAPLACIAN, scale=_LAPLACIAN_SCALE
        )
    )
    negative = thumbnail.filter(
        ImageFilter.Kernel(
            (3, 3), _LAPLACIAN_NEG, scale=_LAPLACIAN_SCALE
        )
    )
    tile_variances = [
        _laplacian_variance(positive, negative, tile)
        for tile in _sharpness_tile_boxes(interior)
    ]
    regional_variance = _nearest_rank_percentile(
        tile_variances, _SHARPNESS_PERCENTILE
    )
    return _bounded_score(math.sqrt(regional_variance) * _SHARPNESS_SCORE_SCALE)


def _exposure_score(image: Image.Image) -> int:
    """Penalise both an off-centre average brightness and crushed/blown pixels.

    Read from the 256-bin histogram rather than a quarter-million-element Python
    list of the same pixels: the two questions asked here — the mean, and how
    many samples sit at the extremes — are exactly what a histogram answers, and
    it answers them in C. The arithmetic is integer-exact, so the score is
    identical to the per-pixel version this replaced.
    """
    counts = _grey_thumbnail(image, 512).histogram()
    total = sum(counts)
    if not total:
        return 0
    mean = sum(level * count for level, count in enumerate(counts)) / total
    clipped = (sum(counts[:5]) + sum(counts[251:])) / total
    distance = abs(mean - 128) / 128
    return _bounded_score(100 - distance * 70 - clipped * 100)


def _resolution_score(width: int, height: int) -> int:
    shortest = min(width, height)
    if shortest >= 2048:
        return 100
    if shortest >= 1536:
        return 90
    if shortest >= 1024:
        return 75
    if shortest >= 768:
        return 55
    if shortest >= 512:
        return 35
    return 10


def analyse_image_bytes(raw: bytes, source_name: str | None = None) -> dict[str, Any]:
    """Return stable technical/provenance metadata for one image.

    The returned ``training_usefulness`` is a conservative technical
    recommendation. It is intentionally separate from ``coverage_value`` and
    any later identity score.
    """
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ValueError("image bytes are required")

    digest = hashlib.sha256(raw).hexdigest()
    with Image.open(io.BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    width, height = image.size
    metrics = {
        "sharpness": _sharpness_score(image),
        "exposure": _exposure_score(image),
        "resolution": _resolution_score(width, height),
    }
    reasons: list[str] = []
    if metrics["sharpness"] < 35:
        reasons.append("low sharpness")
    elif metrics["sharpness"] < 55:
        reasons.append("borderline sharpness")
    if metrics["exposure"] < 40:
        reasons.append("difficult exposure")
    if metrics["resolution"] < 35:
        reasons.append("low source resolution")

    technical = (
        metrics["sharpness"] * 0.42
        + metrics["exposure"] * 0.23
        + metrics["resolution"] * 0.35
    )
    if technical >= 70 and not any(
        reason in reasons for reason in ("low source resolution", "low sharpness")
    ):
        usefulness = "green"
    elif technical >= 45:
        usefulness = "amber"
    else:
        usefulness = "red"

    return {
        "analysis_version": ANALYSIS_VERSION,
        "source_name": source_name or "",
        "source_sha256": digest,
        "width": width,
        "height": height,
        "metrics": metrics,
        "reasons": reasons,
        "training_usefulness": usefulness,
        "coverage_value": "unknown",
    }


def analysis_json(analysis: dict[str, Any]) -> str:
    return json.dumps(analysis, ensure_ascii=False, sort_keys=True)


def parse_analysis(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
