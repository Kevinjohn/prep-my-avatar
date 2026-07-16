from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from avatar_prep.core import export_packs, ingest, load_records
from avatar_prep.viewer import write_viewer


class CoreTests(unittest.TestCase):
    def make_image(self, path: Path, colour: tuple[int, int, int], size: tuple[int, int] = (1200, 900)) -> None:
        image = Image.new("RGB", size, colour)
        draw = ImageDraw.Draw(image)
        draw.rectangle((size[0] // 4, size[1] // 5, size[0] * 3 // 4, size[1] * 4 // 5), outline=(255, 255, 255), width=10)
        image.save(path, quality=95)

    def test_ingest_creates_manifest_crops_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            self.make_image(source / "two.jpg", (120, 100, 80), (900, 1200))
            annotations = root / "annotations.json"
            annotations.write_text(json.dumps({
                "one.jpg": {"view": "frontal", "framing": "head_shoulders", "face_visibility": "high", "expression": "neutral"},
                "two.jpg": {"view": "profile_left", "framing": "half_body", "face_visibility": "high", "expression": "smile"},
            }))
            records = ingest(source, output, "pm_test", annotations)
            write_viewer(output)
            self.assertEqual(len(records), 2)
            self.assertTrue((output / "manifest.json").exists())
            self.assertTrue((output / "reports" / "coverage-report.md").exists())
            self.assertTrue((output / "reports" / "index.html").exists())
            self.assertTrue((output / records[0].crops["square"]).exists())
            self.assertEqual(records[1].primary_crop, "portrait")

    def test_export_writes_matching_captions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            annotations = root / "annotations.json"
            annotations.write_text(json.dumps({"one.jpg": {"face_visibility": "high", "view": "frontal"}}))
            ingest(source, output, "pm_test", annotations)
            write_viewer(output)
            export_packs(output, ["flux2"], include_amber=True)
            files = list((output / "exports" / "flux2").glob("*.jpg"))
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].with_suffix(".txt").exists())

    def test_review_decisions_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            records = ingest(source, output, "pm_test", None)
            write_viewer(output)
            (output / "review.json").write_text(json.dumps({records[0].id: {"status": "red", "caption": "edited"}}))
            _, reviewed = load_records(output)
            self.assertEqual(reviewed[0].status, "red")
            self.assertEqual(reviewed[0].caption, "edited")

    def test_holdout_is_excluded_from_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            records = ingest(source, output, "pm_test", None)
            write_viewer(output)
            (output / "review.json").write_text(json.dumps({records[0].id: {"status": "green", "special": "holdout"}}))
            export_packs(output, ["flux2"])
            files = list((output / "exports" / "flux2").glob("*.jpg"))
            self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
