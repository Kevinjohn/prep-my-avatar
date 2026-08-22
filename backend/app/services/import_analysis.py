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

from PIL import Image, ImageFilter, ImageOps, ImageStat


ANALYSIS_VERSION = 1


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


def _sharpness_score(image: Image.Image) -> int:
    thumbnail = _grey_thumbnail(image, 768)
    edges = thumbnail.filter(ImageFilter.FIND_EDGES)
    variance = ImageStat.Stat(edges).var[0]
    return _bounded_score(math.sqrt(max(variance, 0)) * 3.2)


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
