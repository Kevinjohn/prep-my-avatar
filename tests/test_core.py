from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import avatar_prep.core as prototype_core
import backend.app.services.import_analysis as backend_import_analysis
from avatar_prep.cli import build_parser
from avatar_prep.core import (
    ImageRecord,
    crop_box,
    export_packs,
    ingest,
    load_records,
    mark_duplicates,
    sharpness_score,
)
from backend.app.services.import_analysis import _sharpness_score as backend_sharpness_score
from backend.tests.test_import_analysis import (
    _artifact_speck_fixture,
    _bokeh_fixture,
    _ordinary_sharp_fixture,
    _small_fixture,
    _uniform_blur_fixture,
)
from avatar_prep.viewer import VIEWER_HTML, _validate_review_patch, write_viewer


class CoreTests(unittest.TestCase):
    def make_image(self, path: Path, colour: tuple[int, int, int], size: tuple[int, int] = (1200, 900)) -> None:
        image = Image.new("RGB", size, colour)
        draw = ImageDraw.Draw(image)
        draw.rectangle((size[0] // 4, size[1] // 5, size[0] * 3 // 4, size[1] * 4 // 5), outline=(255, 255, 255), width=10)
        image.save(path, quality=95)

    def test_sharpness_scoring_matches_backend_on_shared_contract(self) -> None:
        for constant in (
            "_SHARPNESS_THUMBNAIL_SIDE",
            "_LAPLACIAN",
            "_LAPLACIAN_NEG",
            "_LAPLACIAN_SCALE",
            "_SHARPNESS_TILE_GRID",
            "_SHARPNESS_TILE_MIN_SIDE",
            "_SHARPNESS_PERCENTILE",
            "_SHARPNESS_SCORE_SCALE",
        ):
            with self.subTest(constant=constant):
                self.assertEqual(
                    getattr(prototype_core, constant),
                    getattr(backend_import_analysis, constant),
                )
        fixtures = (
            _bokeh_fixture,
            _uniform_blur_fixture,
            _artifact_speck_fixture,
            _ordinary_sharp_fixture,
            _small_fixture,
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture.__name__):
                image = fixture()
                self.assertEqual(
                    sharpness_score(image),
                    backend_sharpness_score(image),
                )

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
            self.assertEqual(
                json.loads((output / "manifest.json").read_text())["version"],
                1,
            )
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

    def test_reingest_preserves_review_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            records = ingest(source, output, "pm_test")
            (output / "review.json").write_text(json.dumps({records[0].id: {"status": "red", "caption": "edited"}}))

            ingest(source, output, "pm_test")

            _, reviewed = load_records(output)
            self.assertEqual(reviewed[0].status, "red")
            self.assertEqual(reviewed[0].caption, "edited")

    def test_failed_reingest_preserves_previous_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            original = ingest(source, output, "pm_test")[0]
            annotations = root / "annotations.json"
            annotations.write_text('{"one.jpg": "invalid"}')

            with self.assertRaises(ValueError):
                ingest(source, output, "pm_test", annotations)

            _, records = load_records(output)
            self.assertEqual(records[0].id, original.id)
            self.assertFalse(list(root.glob(".run.staging-*")))

    def test_ingest_ignores_output_nested_below_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = source / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))

            ingest(source, output, "pm_test")
            records = ingest(source, output, "pm_test")

            self.assertEqual([record.source_name for record in records], ["one.jpg"])

    def test_ingest_reads_input_nested_below_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            source = output / "photos"
            source.mkdir(parents=True)
            self.make_image(source / "one.jpg", (80, 100, 120))

            records = ingest(source, output, "pm_test")

            self.assertEqual([record.source_name for record in records], ["one.jpg"])

    def test_export_replaces_stale_pack_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            records = ingest(source, output, "pm_test")
            (output / "review.json").write_text(json.dumps({records[0].id: {"status": "green"}}))
            export_packs(output, ["flux2"])
            (output / "review.json").write_text(json.dumps({records[0].id: {"status": "red"}}))

            export_packs(output, ["flux2"])

            self.assertEqual(list((output / "exports" / "flux2").glob("*.jpg")), [])
            self.assertEqual(list((output / "exports" / "flux2").glob("*.txt")), [])

    def test_red_images_do_not_satisfy_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            annotations = root / "annotations.json"
            for index in range(4):
                self.make_image(source / f"{index}.jpg", (20 + index * 30, 100, 120))
            annotations.write_text(json.dumps({f"{index}.jpg": {"view": "frontal"} for index in range(4)}))
            records = ingest(source, output, "pm_test", annotations)
            (output / "review.json").write_text(json.dumps({record.id: {"status": "red", "training_usefulness": "red"} for record in records}))
            _, reviewed = load_records(output)

            from avatar_prep.core import coverage_lines

            report = "\n".join(coverage_lines(reviewed))
            self.assertIn("| frontal | 0 | 4 | missing |", report)

    def test_identical_files_have_independent_path_based_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            (source / "a").mkdir(parents=True)
            (source / "b").mkdir()
            self.make_image(source / "a" / "same.jpg", (80, 100, 120))
            (source / "b" / "same.jpg").write_bytes((source / "a" / "same.jpg").read_bytes())

            records = ingest(source, output, "pm_test")

            self.assertEqual(len({record.id for record in records}), 2)
            self.assertEqual(len({record.sha256 for record in records}), 1)

    def test_nested_annotations_use_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            (source / "a").mkdir(parents=True)
            (source / "b").mkdir()
            self.make_image(source / "a" / "same.jpg", (80, 100, 120))
            self.make_image(source / "b" / "same.jpg", (120, 100, 80))
            annotations = root / "annotations.json"
            annotations.write_text(json.dumps({"a/same.jpg": {"view": "frontal"}, "b/same.jpg": {"view": "profile_left"}}))

            records = ingest(source, output, "pm_test", annotations)

            self.assertEqual([record.annotations["view"] for record in records], ["frontal", "profile_left"])

    def test_decode_failure_is_not_grouped_as_duplicate(self) -> None:
        failed = ImageRecord("failed", "bad.jpg", "bad.jpg", "bad.jpg", 0, 0, 1, "a", "", {"sharpness": 0})
        failed2 = ImageRecord("failed2", "bad2.jpg", "bad2.jpg", "bad2.jpg", 0, 0, 1, "b", "", {"sharpness": 0})
        mark_duplicates([failed, failed2])
        self.assertIsNone(failed.duplicate_group)
        self.assertIsNone(failed2.duplicate_group)

    def test_different_flat_colours_are_not_duplicates(self) -> None:
        fields = dict(width=100, height=100, file_size=1, average_hash="1" * 256, metrics={"sharpness": 50})
        red = ImageRecord("red", "red.jpg", "red.jpg", "red.jpg", sha256="a", annotations={"_average_rgb": [255, 0, 0]}, **fields)
        blue = ImageRecord("blue", "blue.jpg", "blue.jpg", "blue.jpg", sha256="b", annotations={"_average_rgb": [0, 0, 255]}, **fields)
        mark_duplicates([red, blue])
        self.assertIsNone(red.duplicate_group)
        self.assertIsNone(blue.duplicate_group)

    def test_near_duplicate_lookup_matches_hashes_across_chunk_boundaries(self) -> None:
        fields = dict(width=100, height=100, file_size=1, metrics={"sharpness": 50}, annotations={"_average_rgb": [50, 50, 50]})
        original_hash = "0" * 256
        changed = list(original_hash)
        for index in (0, 43, 86, 129, 172):
            changed[index] = "1"
        original = ImageRecord("a", "a.jpg", "a.jpg", "a.jpg", sha256="a", average_hash=original_hash, **fields)
        near = ImageRecord("b", "b.jpg", "b.jpg", "b.jpg", sha256="b", average_hash="".join(changed), **fields)
        mark_duplicates([original, near])
        self.assertEqual(original.duplicate_group, near.duplicate_group)
        self.assertEqual(near.status, "red")

    def test_ingest_detects_faces_once_per_image(self) -> None:
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            with patch("avatar_prep.core.maybe_face_boxes", return_value=[]) as detector:
                ingest(source, root / "run", "pm_test")
            self.assertEqual(detector.call_count, 1)

    def test_annotations_reject_non_object_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            annotations = root / "annotations.json"
            annotations.write_text('{"one.jpg": "frontal"}')
            with self.assertRaisesRegex(ValueError, "must be JSON objects"):
                ingest(source, root / "run", "pm_test", annotations)

    def test_crop_failure_preserves_image_analysis(self) -> None:
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            with patch("avatar_prep.core.save_crop", side_effect=OSError("disk full")):
                record = ingest(source, root / "run", "pm_test")[0]
            self.assertGreater(record.width, 0)
            self.assertEqual(record.crops, {})
            self.assertIn("could not generate crops: disk full", record.reasons)
            self.assertNotIn("could not decode image", " ".join(record.reasons))

    def test_cli_rejects_invalid_token_and_empty_targets(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["run", "photos", "--out", "run", "--token", "bad token"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["export", "run", "--targets", " , "])
        for target in ("../outside", "nested/name", r"nested\name", "/absolute"):
            with self.subTest(target=target), self.assertRaises(SystemExit):
                parser.parse_args(["export", "run", "--targets", target])

    def test_export_rejects_escaping_targets_before_filesystem_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            outside = root / "outside"
            source.mkdir()
            outside.mkdir()
            sentinel = outside / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            self.make_image(source / "one.jpg", (80, 100, 120))
            ingest(source, output, "pm_test")

            for target in ("../../outside", str(outside), "nested/name", r"nested\name"):
                with self.subTest(target=target), self.assertRaisesRegex(ValueError, "Invalid export target"):
                    export_packs(output, [target])

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse((output / "exports").exists())

    def test_export_rejects_target_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            outside = root / "outside"
            source.mkdir()
            outside.mkdir()
            sentinel = outside / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            self.make_image(source / "one.jpg", (80, 100, 120))
            ingest(source, output, "pm_test")
            (output / "exports").mkdir()
            (output / "exports" / "escaped").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "escapes the export directory"):
                export_packs(output, ["escaped"])

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_face_crop_boxes_remain_in_bounds(self) -> None:
        for width, height, aspect in ((100, 1000, 1.5), (1000, 100, 2 / 3), (127, 293, 1.0)):
            left, top, right, bottom = crop_box(width, height, aspect, [(0, 0, 90, 90)])
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(right, width)
            self.assertLessEqual(bottom, height)
            self.assertAlmostEqual((right - left) / (bottom - top), aspect, delta=0.03)

    def test_load_records_rejects_unsupported_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "manifest.json").write_text('{"version": 2, "records": []}')
            (output / "review.json").write_text('{}')
            with self.assertRaisesRegex(ValueError, "unsupported version"):
                load_records(output)

    def test_run_consumers_reject_missing_malformed_and_incomplete_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            absent = root / "absent"
            with self.assertRaisesRegex(ValueError, "incomplete"):
                load_records(absent)
            with self.assertRaisesRegex(ValueError, "incomplete"):
                export_packs(absent, ["flux2"])

            malformed = root / "malformed"
            malformed.mkdir()
            (malformed / "manifest.json").write_text('{')
            (malformed / "review.json").write_text('{}')
            with self.assertRaisesRegex(ValueError, "unreadable"):
                load_records(malformed)

            incomplete = root / "incomplete"
            incomplete.mkdir()
            (incomplete / "manifest.json").write_text(
                '{"version": 1, "records": [{}]}')
            (incomplete / "review.json").write_text('{}')
            with self.assertRaisesRegex(ValueError, "invalid image record"):
                load_records(incomplete)

    def test_export_requires_status_and_training_usefulness(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            records = ingest(source, output, "pm_test")
            (output / "review.json").write_text(json.dumps({records[0].id: {"status": "green", "training_usefulness": "red"}}))

            export_packs(output, ["flux2"])

            self.assertEqual(list((output / "exports" / "flux2").glob("*.jpg")), [])

    def test_review_patch_schema_rejects_unknown_ids_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "photos"
            output = root / "run"
            source.mkdir()
            self.make_image(source / "one.jpg", (80, 100, 120))
            record = ingest(source, output, "pm_test")[0]
            with self.assertRaisesRegex(ValueError, "identify a record"):
                _validate_review_patch(output, "missing", {"status": "green"})
            with self.assertRaisesRegex(ValueError, "green, amber, or red"):
                _validate_review_patch(output, record.id, {"status": "blue"})
            with self.assertRaisesRegex(ValueError, "Unknown review fields"):
                _validate_review_patch(output, record.id, {"surprise": True})

    def test_viewer_handles_scalar_annotations_and_missing_crops(self) -> None:
        self.assertIn("Array.isArray(value)", VIEWER_HTML)
        self.assertIn("Crop unavailable", VIEWER_HTML)
        self.assertIn("map(encodeURIComponent)", VIEWER_HTML)
        self.assertIn("const pageSize = 100", VIEWER_HTML)
        self.assertIn("setTimeout", VIEWER_HTML)

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
