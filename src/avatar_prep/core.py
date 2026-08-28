from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageFilter, ImageOps, ImageStat


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}

# The prototype is distributed as a standalone package and cannot import the
# Flask application's service module. Keep this deliberately duplicated focus
# contract in exact parity with backend/app/services/import_analysis.py; the
# cross-package synthetic tests fail on any algorithm or constant drift.
_SHARPNESS_THUMBNAIL_SIDE = 768
_LAPLACIAN = (0, 1, 0, 1, -4, 1, 0, 1, 0)
_LAPLACIAN_NEG = tuple(-coefficient for coefficient in _LAPLACIAN)
_LAPLACIAN_SCALE = 4
_SHARPNESS_TILE_GRID = 8
_SHARPNESS_TILE_MIN_SIDE = 32
_SHARPNESS_PERCENTILE = 0.90
_SHARPNESS_SCORE_SCALE = 13.5

DEFAULT_TARGETS = ("flux2", "krea2", "sdxl")

VIEW_TARGETS = {
    "frontal": 4,
    "three_quarter_left": 4,
    "three_quarter_right": 4,
    "profile_left": 2,
    "profile_right": 2,
}
FRAMING_TARGETS = {
    "close_up": 6,
    "head_shoulders": 10,
    "half_body": 10,
    "full_body": 8,
}
EXPRESSION_TARGETS = {"neutral": 10, "smile": 5, "open_mouth": 2}
LIGHTING_TARGETS = {"soft_daylight": 6, "indoor_diffuse": 6, "side_light": 3}


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        # Some platforms/filesystems do not support syncing directories.
        pass


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def average_hash(image: Image.Image, size: int = 16) -> str:
    grey = ImageOps.grayscale(image).resize((size, size))
    pixels = list(grey.get_flattened_data()) if hasattr(grey, "get_flattened_data") else list(grey.getdata())
    average = statistics.mean(pixels) if pixels else 0
    return "".join("1" if pixel >= average else "0" for pixel in pixels)


def hamming_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        raise ValueError("Hashes must have equal lengths")
    return sum(a != b for a, b in zip(left, right))


def bounded_score(value: float) -> int:
    return max(0, min(100, round(value)))


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


def sharpness_score(image: Image.Image) -> int:
    thumbnail = ImageOps.grayscale(image)
    thumbnail.thumbnail((_SHARPNESS_THUMBNAIL_SIDE, _SHARPNESS_THUMBNAIL_SIDE))
    width, height = thumbnail.size
    if width < 3 or height < 3:
        return 0
    interior = (1, 1, width - 1, height - 1)
    positive = thumbnail.filter(
        ImageFilter.Kernel((3, 3), _LAPLACIAN, scale=_LAPLACIAN_SCALE)
    )
    negative = thumbnail.filter(
        ImageFilter.Kernel((3, 3), _LAPLACIAN_NEG, scale=_LAPLACIAN_SCALE)
    )
    regional_variance = _nearest_rank_percentile(
        [
            _laplacian_variance(positive, negative, tile)
            for tile in _sharpness_tile_boxes(interior)
        ],
        _SHARPNESS_PERCENTILE,
    )
    return bounded_score(math.sqrt(regional_variance) * _SHARPNESS_SCORE_SCALE)


def exposure_score(image: Image.Image) -> int:
    grey = ImageOps.grayscale(image.copy())
    grey.thumbnail((512, 512))
    pixels = list(grey.get_flattened_data()) if hasattr(grey, "get_flattened_data") else list(grey.getdata())
    if not pixels:
        return 0
    mean = statistics.mean(pixels)
    clipped = sum(pixel <= 4 or pixel >= 251 for pixel in pixels) / len(pixels)
    distance = abs(mean - 128) / 128
    return bounded_score(100 - distance * 70 - clipped * 100)


def resolution_score(width: int, height: int) -> int:
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


def make_caption(token: str, annotations: dict[str, Any]) -> str:
    subject = annotations.get("subject", "person")
    parts = [token, subject]
    for key in ("view", "expression", "framing"):
        value = annotations.get(key)
        if value and value != "unknown":
            parts.append(str(value).replace("_", " "))
    for key in ("clothing", "accessories"):
        values = annotations.get(key) or []
        if isinstance(values, str):
            values = [values]
        parts.extend(str(value).replace("_", " ") for value in values if value)
    for key in ("lighting", "background"):
        value = annotations.get(key)
        if value and value != "unknown":
            parts.append(str(value).replace("_", " "))
    return ", ".join(parts) + "."


def primary_crop_name(annotations: dict[str, Any], width: int, height: int) -> str:
    framing = annotations.get("framing")
    if framing in {"full_body", "half_body"} or height > width * 1.15:
        return "portrait"
    if width > height * 1.15:
        return "landscape"
    return "square"


@dataclass
class ImageRecord:
    id: str
    source_name: str
    source_path: str
    original_path: str
    width: int
    height: int
    file_size: int
    sha256: str
    average_hash: str
    metrics: dict[str, int]
    duplicate_group: str | None = None
    annotations: dict[str, Any] = field(default_factory=dict)
    caption: str = ""
    primary_crop: str = "square"
    status: str = "amber"
    training_usefulness: str = "amber"
    coverage_value: str = "amber"
    reasons: list[str] = field(default_factory=list)
    crops: dict[str, str] = field(default_factory=dict)
    manual: dict[str, Any] = field(default_factory=dict)
    special: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def import_annotations(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = load_json(path, {})
    if not isinstance(raw, dict):
        raise ValueError("Annotations must be a JSON object keyed by source filename")
    invalid = [str(key) for key, value in raw.items() if not isinstance(value, dict)]
    if invalid:
        raise ValueError(f"Annotations for {', '.join(invalid)} must be JSON objects")
    return {str(key): value for key, value in raw.items()}


def maybe_face_boxes(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Use optional local OpenCV Haar detection without making it mandatory."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return []

    rgb = image.convert("RGB")
    array = np.asarray(rgb)
    grey = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    found = cascade.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in found]


def crop_box(width: int, height: int, aspect: float, face_boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    if face_boxes:
        x, y, face_width, face_height = max(face_boxes, key=lambda box: box[2] * box[3])
        cx = x + face_width / 2
        cy = y + face_height * 1.8
        desired_height = max(face_height * 4.8, height * 0.38)
        desired_width = desired_height * aspect
        scale = min(1.0, width / desired_width, height / desired_height)
        desired_width *= scale
        desired_height *= scale
        left = cx - desired_width / 2
        top = cy - desired_height * 0.42
    else:
        desired_width = min(width, height * aspect)
        desired_height = desired_width / aspect
        left = (width - desired_width) / 2
        top = (height - desired_height) / 2

    left = max(0, min(left, width - desired_width))
    top = max(0, min(top, height - desired_height))
    return (round(left), round(top), round(left + desired_width), round(top + desired_height))


def save_crop(image: Image.Image, box: tuple[int, int, int, int], destination: Path, max_dimension: int = 1536) -> None:
    crop = image.crop(box)
    # Never upscale source material.
    crop.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    crop.save(destination, quality=95 if destination.suffix.lower() in {".jpg", ".jpeg"} else None)


def analyse_image(
    path: Path,
    original_path: str,
    annotations: dict[str, Any],
    token: str,
    *,
    image: Image.Image | None = None,
    face_boxes: list[tuple[int, int, int, int]] | None = None,
) -> ImageRecord:
    image = image if image is not None else ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    width, height = image.size
    digest = sha256(path)
    ahash = average_hash(image)
    metrics = {
        "sharpness": sharpness_score(image),
        "exposure": exposure_score(image),
        "resolution": resolution_score(width, height),
    }
    face_boxes = maybe_face_boxes(image) if face_boxes is None else face_boxes
    enriched = {
        "view": "unknown",
        "framing": "unknown",
        "expression": "unknown",
        "lighting": "unknown",
        "background": "unknown",
        "face_visibility": "unknown",
        "clothing": [],
        "accessories": [],
        **annotations,
    }
    reasons: list[str] = []
    if face_boxes and enriched.get("face_visibility") == "unknown":
        largest_face = max(face_boxes, key=lambda box: box[2] * box[3])
        face_ratio = (largest_face[2] * largest_face[3]) / max(width * height, 1)
        enriched["face_visibility"] = "high" if face_ratio >= 0.025 else "low"
        if face_ratio >= 0.15:
            enriched["framing"] = "close_up"
        elif face_ratio >= 0.07:
            enriched["framing"] = "head_shoulders"
        elif face_ratio >= 0.025:
            enriched["framing"] = "half_body"
        else:
            enriched["framing"] = "full_body"
    if len(face_boxes) > 1:
        reasons.append("multiple faces detected; review the subject selection")
    technical = metrics["sharpness"] * 0.42 + metrics["exposure"] * 0.23 + metrics["resolution"] * 0.35
    if metrics["sharpness"] < 35:
        reasons.append("low sharpness")
    elif metrics["sharpness"] < 55:
        reasons.append("borderline sharpness")
    if metrics["exposure"] < 40:
        reasons.append("difficult exposure")
    if metrics["resolution"] < 35:
        reasons.append("low source resolution")
    if not face_boxes and enriched.get("face_visibility") == "unknown":
        reasons.append("face/view not automatically verified")
    if enriched.get("face_visibility") in {"low", "occluded"}:
        reasons.append("face visibility is limited")

    if technical >= 70 and not any(reason in reasons for reason in ("low source resolution", "low sharpness")):
        training = "green" if face_boxes or enriched.get("face_visibility") == "high" else "amber"
    elif technical >= 45:
        training = "amber"
    else:
        training = "red"
    coverage = "green" if enriched.get("view") != "unknown" else "amber"
    if enriched.get("view") in {"profile_left", "profile_right", "three_quarter_left", "three_quarter_right"}:
        coverage = "green"
    status = training
    caption = make_caption(token, enriched)
    return ImageRecord(
        id=digest[:12],
        source_name=path.name,
        source_path=str(path),
        original_path=original_path,
        width=width,
        height=height,
        file_size=path.stat().st_size,
        sha256=digest,
        average_hash=ahash,
        metrics=metrics,
        annotations=enriched,
        caption=caption,
        primary_crop=primary_crop_name(enriched, width, height),
        status=status,
        training_usefulness=training,
        coverage_value=coverage,
        reasons=reasons,
    )


def mark_duplicates(records: list[ImageRecord]) -> None:
    representatives: list[tuple[ImageRecord, str]] = []
    exact_hashes: dict[str, int] = {}
    perceptual_buckets: dict[tuple[int, str, tuple[int, int, int]], list[int]] = {}
    threshold = 5
    chunk_count = threshold + 1
    for record in records:
        if not record.average_hash:
            record.duplicate_group = None
            continue
        group = None
        candidates: set[int] = set()
        if record.sha256 in exact_hashes:
            candidates.add(exact_hashes[record.sha256])
        record_colour = record.annotations.get("_average_rgb")
        colour_cell: tuple[int, int, int] | None = None
        if isinstance(record_colour, list) and len(record_colour) == 3:
            colour_cell = tuple(int(value) // 30 for value in record_colour)
            chunk_size = math.ceil(len(record.average_hash) / chunk_count)
            for chunk_index in range(chunk_count):
                start = chunk_index * chunk_size
                chunk = record.average_hash[start : start + chunk_size]
                for red_offset in (-1, 0, 1):
                    for green_offset in (-1, 0, 1):
                        for blue_offset in (-1, 0, 1):
                            nearby = (
                                colour_cell[0] + red_offset,
                                colour_cell[1] + green_offset,
                                colour_cell[2] + blue_offset,
                            )
                            candidates.update(perceptual_buckets.get((chunk_index, chunk, nearby), ()))
        for candidate in candidates:
            existing, existing_group = representatives[candidate]
            # Exact bytes are definitive. Perceptual hashes are only trusted when
            # the coarse colour signature also agrees, avoiding flat-colour false positives.
            same_bytes = record.sha256 == existing.sha256
            existing_colour = existing.annotations.get("_average_rgb")
            similar_colour = (
                isinstance(record_colour, list)
                and isinstance(existing_colour, list)
                and len(record_colour) == len(existing_colour) == 3
                and sum((left - right) ** 2 for left, right in zip(record_colour, existing_colour)) <= 30**2
            )
            if same_bytes or (similar_colour and hamming_distance(record.average_hash, existing.average_hash) <= 5):
                group = existing_group
                break
        if group is None:
            group = f"dup-{len(representatives) + 1:03d}"
            representative_index = len(representatives)
            representatives.append((record, group))
            exact_hashes.setdefault(record.sha256, representative_index)
            if colour_cell is not None:
                chunk_size = math.ceil(len(record.average_hash) / chunk_count)
                for chunk_index in range(chunk_count):
                    start = chunk_index * chunk_size
                    chunk = record.average_hash[start : start + chunk_size]
                    perceptual_buckets.setdefault((chunk_index, chunk, colour_cell), []).append(representative_index)
        record.duplicate_group = group
    by_group: dict[str, list[ImageRecord]] = {}
    for record in records:
        by_group.setdefault(record.duplicate_group or "", []).append(record)
    for group, members in by_group.items():
        if len(members) <= 1:
            members[0].duplicate_group = None
            continue
        keeper = max(members, key=lambda item: sum(item.metrics.values()))
        for member in members:
            if member is not keeper:
                member.training_usefulness = "red"
                member.status = "red"
                member.reasons.append(f"near-duplicate of {keeper.source_name}")


def _build_run(
    input_dir: Path,
    out_dir: Path,
    token: str,
    annotation_path: Path | None,
    vision: str,
    excluded_output: Path,
) -> list[ImageRecord]:
    del vision  # Kept in the public contract for future provider selection.
    input_root = input_dir.resolve()
    output_root = excluded_output.resolve()
    output_is_below_input = output_root.is_relative_to(input_root)
    source_files = sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and (not output_is_below_input or not path.resolve().is_relative_to(output_root))
    )
    if not source_files:
        raise ValueError(f"No supported images found in {input_dir}")
    annotations = import_annotations(annotation_path)
    basename_counts: dict[str, int] = {}
    for source in source_files:
        basename_counts[source.name] = basename_counts.get(source.name, 0) + 1
    originals_dir = out_dir / "originals"
    crop_dir = out_dir / "crops"
    records: list[ImageRecord] = []
    for source in source_files:
        relative = source.relative_to(input_dir)
        destination = originals_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        try:
            relative_key = relative.as_posix()
            annotation = annotations.get(relative_key)
            if annotation is None and basename_counts[source.name] == 1:
                annotation = annotations.get(source.name, {})
            image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
            face_boxes = maybe_face_boxes(image)
            annotation = dict(annotation or {})
            annotation["_average_rgb"] = [round(value) for value in ImageStat.Stat(image.resize((1, 1))).mean[:3]]
            record = analyse_image(
                source,
                str(destination.relative_to(out_dir)),
                annotation,
                token,
                image=image,
                face_boxes=face_boxes,
            )
            path_digest = hashlib.sha256(relative_key.encode("utf-8")).hexdigest()[:8]
            record.id = f"{record.sha256[:12]}-{path_digest}"
            try:
                for crop_name, aspect in {"square": 1.0, "portrait": 2 / 3, "landscape": 3 / 2}.items():
                    crop_path = crop_dir / crop_name / f"{record.id}.jpg"
                    save_crop(image, crop_box(record.width, record.height, aspect, face_boxes), crop_path)
                    record.crops[crop_name] = str(crop_path.relative_to(out_dir))
            except Exception as exc:
                record.crops.clear()
                record.status = "red"
                record.training_usefulness = "red"
                record.reasons.append(f"could not generate crops: {exc}")
            records.append(record)
        except Exception as exc:  # Preserve the source and surface the failure in the viewer.
            record = ImageRecord(
                id=f"{sha256(source)[:12]}-{hashlib.sha256(relative.as_posix().encode('utf-8')).hexdigest()[:8]}",
                source_name=source.name,
                source_path=str(source),
                original_path=str(destination.relative_to(out_dir)),
                width=0,
                height=0,
                file_size=source.stat().st_size,
                sha256=sha256(source),
                average_hash="",
                metrics={"sharpness": 0, "exposure": 0, "resolution": 0},
                primary_crop="square",
                status="red",
                training_usefulness="red",
                coverage_value="amber",
                reasons=[f"could not decode image: {exc}"],
            )
            records.append(record)
    mark_duplicates(records)
    previous_review = load_json(out_dir / "review.json", {})
    if not isinstance(previous_review, dict):
        previous_review = {}
    record_ids = {record.id for record in records}
    retained_review = {key: value for key, value in previous_review.items() if key in record_ids}
    _json_dump(out_dir / "manifest.json", {"version": 1, "token": token, "records": [record.to_dict() for record in records]})
    _json_dump(out_dir / "review.json", retained_review)
    write_selection_csv(out_dir, records)
    write_reports(out_dir, records, token)
    return records


def ingest(input_dir: Path, out_dir: Path, token: str, annotation_path: Path | None = None, vision: str = "auto") -> list[ImageRecord]:
    """Build a complete run beside the destination, then publish it atomically."""
    out_dir = out_dir.resolve()
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = out_dir.with_name(f".{out_dir.name}.staging-{uuid.uuid4().hex}")
    previous_dir = out_dir.with_name(f".{out_dir.name}.previous-{uuid.uuid4().hex}")
    staging_dir.mkdir()
    review_path = out_dir / "review.json"
    if review_path.exists():
        shutil.copy2(review_path, staging_dir / "review.json")
    try:
        records = _build_run(input_dir, staging_dir, token, annotation_path, vision, out_dir)
        if out_dir.exists():
            out_dir.replace(previous_dir)
        try:
            staging_dir.replace(out_dir)
        except Exception:
            if previous_dir.exists() and not out_dir.exists():
                previous_dir.replace(out_dir)
            raise
        if previous_dir.exists():
            shutil.rmtree(previous_dir)
        return records
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise


def load_records(out_dir: Path) -> tuple[dict[str, Any], list[ImageRecord]]:
    manifest_path = out_dir / "manifest.json"
    review_path = out_dir / "review.json"
    if not manifest_path.is_file() or not review_path.is_file():
        raise ValueError("Run is incomplete: manifest.json and review.json are required")
    try:
        manifest = load_json(manifest_path, {})
        review = load_json(review_path, {})
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Run state is unreadable: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("records"), list):
        raise ValueError("Run manifest is missing, malformed, or uses an unsupported version")
    try:
        records = [ImageRecord(**item) for item in manifest["records"] if isinstance(item, dict)]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Run manifest contains an invalid image record: {exc}") from exc
    if len(records) != len(manifest["records"]):
        raise ValueError("Run manifest contains an invalid image record")
    if not isinstance(review, dict):
        raise ValueError("Run review state must be a JSON object")
    for record in records:
        decision = review.get(record.id, {})
        for key in ("status", "caption", "manual", "special"):
            if key in decision:
                setattr(record, key, decision[key])
        if decision.get("training_usefulness"):
            record.training_usefulness = decision["training_usefulness"]
        if decision.get("coverage_value"):
            record.coverage_value = decision["coverage_value"]
    return manifest, records


def write_selection_csv(out_dir: Path, records: Iterable[ImageRecord]) -> None:
    path = out_dir / "analysis" / "selection.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "source_name", "status", "training_usefulness", "coverage_value", "sharpness", "exposure", "resolution", "view", "framing", "reasons"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "id": record.id,
                "source_name": record.source_name,
                "status": record.status,
                "training_usefulness": record.training_usefulness,
                "coverage_value": record.coverage_value,
                "sharpness": record.metrics.get("sharpness", 0),
                "exposure": record.metrics.get("exposure", 0),
                "resolution": record.metrics.get("resolution", 0),
                "view": record.annotations.get("view", "unknown"),
                "framing": record.annotations.get("framing", "unknown"),
                "reasons": "; ".join(record.reasons),
            })


def coverage_lines(records: list[ImageRecord]) -> list[str]:
    lines = ["# Coverage report", "", "This report distinguishes missing coverage from weak or unknown analysis.", ""]
    if any(record.annotations.get("view") == "unknown" for record in records):
        lines.extend([
            "> Vision annotations are incomplete. Add `--annotations annotations.json` or a vision provider before treating unknown categories as truly missing.",
            "",
        ])
    for label, key, targets in (
        ("View angle", "view", VIEW_TARGETS),
        ("Framing", "framing", FRAMING_TARGETS),
        ("Expression", "expression", EXPRESSION_TARGETS),
        ("Lighting", "lighting", LIGHTING_TARGETS),
    ):
        counts: dict[str, int] = {}
        for record in records:
            if record.status == "red" or record.training_usefulness == "red":
                continue
            value = record.annotations.get(key, "unknown")
            counts[value] = counts.get(value, 0) + 1
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| Category | Have | Suggested minimum | State |")
        lines.append("|---|---:|---:|---|")
        for category, minimum in targets.items():
            count = counts.get(category, 0)
            state = "covered" if count >= minimum else ("weak" if count else "missing")
            lines.append(f"| {category.replace('_', ' ')} | {count} | {minimum} | {state} |")
        lines.append("")
    return lines


def write_reports(out_dir: Path, records: list[ImageRecord], token: str) -> None:
    report_dir = out_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    counts = {colour: sum(record.status == colour for record in records) for colour in ("green", "amber", "red")}
    lines = [
        "# Avatar dataset review",
        "",
        f"Token: `{token}`",
        "",
        f"Images: {len(records)} | Green: {counts['green']} | Amber: {counts['amber']} | Red: {counts['red']}",
        "",
        "## Next capture plan",
        "",
        "The viewer will become the primary review surface. The initial automated plan is conservative:",
        "",
        "- Reshoot any missing or weak view angles shown in the coverage tables.",
        "- Prefer sharp, independent images over repeated burst frames.",
        "- Capture difficult angles with neutral expression and clear face visibility.",
        "- Add framing and lighting variety only after identity coverage is adequate.",
        "",
    ]
    lines.extend(coverage_lines(records))
    (report_dir / "coverage-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_export_target(target: str) -> str:
    """Return a safe export directory name, rejecting paths and traversal."""
    candidate = Path(target)
    if (
        not target
        or target in {".", ".."}
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or "/" in target
        or "\\" in target
    ):
        raise ValueError(f"Invalid export target {target!r}: expected a simple directory name")
    return target


def export_packs(out_dir: Path, targets: list[str], include_amber: bool = False) -> list[Path]:
    out_dir = out_dir.resolve()
    exports_dir = out_dir / "exports"
    if exports_dir.is_symlink():
        raise ValueError("Export directory must not be a symbolic link")

    target_dirs: list[tuple[str, Path]] = []
    for target in targets:
        validate_export_target(target)
        target_dir = exports_dir / target
        if target_dir.resolve(strict=False).parent != exports_dir.resolve(strict=False):
            raise ValueError(f"Invalid export target {target!r}: target escapes the export directory")
        target_dirs.append((target, target_dir))

    manifest, records = load_records(out_dir)
    token = manifest.get("token", "pm_subject")
    allowed = {"green", "amber"} if include_amber else {"green"}
    created: list[Path] = []
    for target, target_dir in target_dirs:
        staging_dir = target_dir.with_name(f".{target_dir.name}.staging")
        previous_dir = target_dir.with_name(f".{target_dir.name}.previous")
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True)
        count = 0
        for record in records:
            if (
                record.status not in allowed
                or record.training_usefulness not in allowed
                or record.special == "holdout"
                or not record.crops.get(record.primary_crop)
            ):
                continue
            source = out_dir / record.crops[record.primary_crop]
            destination = staging_dir / f"{count:04d}_{record.id}.jpg"
            shutil.copy2(source, destination)
            destination.with_suffix(".txt").write_text(record.caption + "\n", encoding="utf-8")
            count += 1
        metadata = {"target": target, "token": token, "images": count, "include_amber": include_amber}
        _json_dump(staging_dir / "metadata.json", metadata)
        if previous_dir.exists():
            shutil.rmtree(previous_dir)
        if target_dir.exists():
            target_dir.replace(previous_dir)
        try:
            staging_dir.replace(target_dir)
        except Exception:
            if previous_dir.exists() and not target_dir.exists():
                previous_dir.replace(target_dir)
            raise
        if previous_dir.exists():
            shutil.rmtree(previous_dir)
        created.append(target_dir)
    # Keep CSV current after any browser decisions.
    write_selection_csv(out_dir, records)
    return created
