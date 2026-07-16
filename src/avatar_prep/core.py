from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}

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
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


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
    return sum(a != b for a, b in zip(left, right))


def bounded_score(value: float) -> int:
    return max(0, min(100, round(value)))


def sharpness_score(image: Image.Image) -> int:
    thumbnail = ImageOps.grayscale(image.copy())
    thumbnail.thumbnail((768, 768))
    edges = thumbnail.filter(ImageFilter.FIND_EDGES)
    variance = ImageStat.Stat(edges).var[0]
    # This is a conservative heuristic, not a face-quality measurement.
    return bounded_score(math.sqrt(max(variance, 0)) * 3.2)


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
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


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
        if desired_width > width:
            desired_width = width
            desired_height = desired_width / aspect
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


def analyse_image(path: Path, original_path: str, annotations: dict[str, Any], token: str) -> ImageRecord:
    image = ImageOps.exif_transpose(Image.open(path))
    width, height = image.size
    digest = sha256(path)
    ahash = average_hash(image)
    metrics = {
        "sharpness": sharpness_score(image),
        "exposure": exposure_score(image),
        "resolution": resolution_score(width, height),
    }
    face_boxes = maybe_face_boxes(image)
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
    groups: list[tuple[str, str]] = []
    for record in records:
        group = None
        for existing_hash, existing_group in groups:
            if hamming_distance(record.average_hash, existing_hash) <= 5:
                group = existing_group
                break
        if group is None:
            group = f"dup-{len(groups) + 1:03d}"
            groups.append((record.average_hash, group))
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


def ingest(input_dir: Path, out_dir: Path, token: str, annotation_path: Path | None = None, vision: str = "auto") -> list[ImageRecord]:
    del vision  # Kept in the public contract for future provider selection.
    source_files = sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    if not source_files:
        raise ValueError(f"No supported images found in {input_dir}")
    annotations = import_annotations(annotation_path)
    originals_dir = out_dir / "originals"
    crop_dir = out_dir / "crops"
    records: list[ImageRecord] = []
    for source in source_files:
        relative = source.relative_to(input_dir)
        destination = originals_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        try:
            record = analyse_image(source, str(destination.relative_to(out_dir)), annotations.get(source.name, {}), token)
            image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
            face_boxes = maybe_face_boxes(image)
            for crop_name, aspect in {"square": 1.0, "portrait": 2 / 3, "landscape": 3 / 2}.items():
                crop_path = crop_dir / crop_name / f"{record.id}.jpg"
                save_crop(image, crop_box(record.width, record.height, aspect, face_boxes), crop_path)
                record.crops[crop_name] = str(crop_path.relative_to(out_dir))
            records.append(record)
        except Exception as exc:  # Preserve the source and surface the failure in the viewer.
            record = ImageRecord(
                id=sha256(source)[:12],
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
    _json_dump(out_dir / "manifest.json", {"version": 1, "token": token, "records": [record.to_dict() for record in records]})
    _json_dump(out_dir / "review.json", {})
    write_selection_csv(out_dir, records)
    write_reports(out_dir, records, token)
    return records


def load_records(out_dir: Path) -> tuple[dict[str, Any], list[ImageRecord]]:
    manifest = load_json(out_dir / "manifest.json", {})
    records = [ImageRecord(**item) for item in manifest.get("records", [])]
    review = load_json(out_dir / "review.json", {})
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


def export_packs(out_dir: Path, targets: list[str], include_amber: bool = False) -> list[Path]:
    manifest, records = load_records(out_dir)
    token = manifest.get("token", "pm_subject")
    allowed = {"green", "amber"} if include_amber else {"green"}
    created: list[Path] = []
    for target in targets:
        target_dir = out_dir / "exports" / target
        target_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for record in records:
            if record.status not in allowed or record.special == "holdout" or not record.crops.get(record.primary_crop):
                continue
            source = out_dir / record.crops[record.primary_crop]
            destination = target_dir / f"{count:04d}_{record.id}.jpg"
            shutil.copy2(source, destination)
            destination.with_suffix(".txt").write_text(record.caption + "\n", encoding="utf-8")
            count += 1
        metadata = {"target": target, "token": token, "images": count, "include_amber": include_amber}
        _json_dump(target_dir / "metadata.json", metadata)
        created.append(target_dir)
    # Keep CSV current after any browser decisions.
    write_selection_csv(out_dir, records)
    return created
