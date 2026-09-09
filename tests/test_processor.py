"""Batch processing: classification, folder layout, report, resume, cancel."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PIL import Image

from app.settings import AppSettings
from processing.contact_sheet import generate_contact_sheets
from processing.processor import (
    EXISTING_REPROCESS,
    EXISTING_SKIP,
    BatchProcessor,
    ManualAdjust,
)
from utilities.report import REPORT_COLUMNS, load_report


def run_batch(source: Path, limit=None, existing=EXISTING_SKIP,
              on_progress=None) -> BatchProcessor:
    processor = BatchProcessor(
        source_dir=source, settings=AppSettings(), limit=limit,
        existing_mode=existing, on_progress=on_progress,
    )
    processor.run()  # synchronous for tests
    assert processor.error is None
    return processor


@pytest.fixture()
def finished_batch(sample_source: Path, engine) -> BatchProcessor:
    return run_batch(sample_source)


class TestClassificationAndLayout:
    def test_folder_structure(self, finished_batch: BatchProcessor):
        crop = finished_batch.crop_root
        assert crop.name == "Employee_IDs_crop"
        assert crop.parent == finished_batch.source_dir.parent
        assert (crop / "REVIEW").is_dir()
        assert (crop / "FAILED").is_dir()
        assert (crop / "processing_report.csv").exists()
        assert (crop / "processing.log").exists()

    def test_statuses(self, finished_batch: BatchProcessor):
        by_name = {o.filename: o for o in finished_batch.outcomes}
        assert by_name["IMG_0001.JPG"].status == "SUCCESS"
        assert by_name["IMG_0003.JPG"].status == "REVIEW"  # two faces
        assert any("multiple faces" in r for r in by_name["IMG_0003.JPG"].review_reasons)
        assert by_name["IMG_0003.JPG"].face_count == 2
        assert by_name["IMG_0004.JPG"].status == "FAILED"  # no face
        assert by_name["IMG_0005.JPG"].status == "FAILED"  # corrupt
        assert by_name["IMG_0006.JPG"].status == "SUCCESS"  # EXIF sideways
        assert by_name["DSC_1845.jpeg"].status == "SUCCESS"
        assert by_name["000123.png"].status == "SUCCESS"

    def test_output_files_in_correct_folders(self, finished_batch: BatchProcessor):
        crop = finished_batch.crop_root
        assert (crop / "IMG_0001.JPG").exists()
        assert (crop / "REVIEW" / "IMG_0003.JPG").exists()
        assert not (crop / "IMG_0003.JPG").exists()
        assert (crop / "FAILED" / "IMG_0004.JPG").exists()  # copy of original
        assert not (crop / "IMG_0004.JPG").exists()

    def test_filenames_and_extensions_preserved(self, finished_batch):
        crop = finished_batch.crop_root
        assert (crop / "DSC_1845.jpeg").exists()  # lowercase ext kept
        assert (crop / "000123.png").exists()  # leading zeros + png kept
        with Image.open(crop / "000123.png") as im:
            assert im.format == "PNG"
        with Image.open(crop / "IMG_0001.JPG") as im:
            assert im.format == "JPEG"

    def test_output_dimensions(self, finished_batch):
        with Image.open(finished_batch.crop_root / "IMG_0001.JPG") as im:
            assert im.size == (600, 800)
        with Image.open(finished_batch.crop_root / "REVIEW" / "IMG_0003.JPG") as im:
            assert im.size == (600, 800)

    def test_stats_add_up(self, finished_batch):
        stats = finished_batch.stats
        assert stats.total == 8  # notes.txt is not an image
        assert stats.processed == 8
        assert stats.failed == 2
        assert stats.review >= 1
        assert stats.success + stats.review == 6
        assert not stats.cancelled


class TestReport:
    def test_report_columns_and_rows(self, finished_batch):
        rows = load_report(finished_batch.crop_root / "processing_report.csv")
        assert len(rows) == 8
        assert list(rows[0].keys()) == REPORT_COLUMNS
        by_name = {r["filename"]: r for r in rows}
        assert by_name["IMG_0004.JPG"]["status"] == "FAILED"
        assert "no face" in by_name["IMG_0004.JPG"]["reason"]
        row = by_name["IMG_0001.JPG"]
        assert row["status"] == "SUCCESS"
        assert float(row["eye_distance_pixels"]) > 50
        assert 0 < float(row["eye_distance_ratio"]) < 1
        assert float(row["detection_confidence"]) > 0.5
        assert float(row["processing_time"]) > 0
        assert Path(row["output_path"]).exists()
        assert Path(row["source_path"]).exists()


class TestResumeModes:
    def test_skip_existing(self, sample_source, engine):
        first = run_batch(sample_source)
        assert first.stats.skipped == 0
        second = run_batch(sample_source, existing=EXISTING_SKIP)
        # 6 outputs exist (4 success + 2 review/success mix); failures rerun.
        assert second.stats.skipped == first.stats.success + first.stats.review
        assert second.stats.failed == first.stats.failed
        # Skipped rows keep their original measurements in the report.
        rows = load_report(second.crop_root / "processing_report.csv")
        assert {r["filename"] for r in rows} == {
            o.filename for o in first.outcomes}

    def test_reprocess_overwrites(self, sample_source, engine):
        first = run_batch(sample_source)
        target = first.crop_root / "IMG_0001.JPG"
        before = target.stat().st_mtime_ns
        second = run_batch(sample_source, existing=EXISTING_REPROCESS)
        assert second.stats.skipped == 0
        assert target.stat().st_mtime_ns != before

    def test_limit_processes_first_n(self, sample_source, engine):
        processor = run_batch(sample_source, limit=3)
        assert processor.stats.total == 3
        assert processor.stats.processed == 3


class TestCancellation:
    def test_cancel_stops_after_current_image(self, sample_source, engine):
        holder: dict = {}

        def on_progress(progress):
            if progress.stats.processed >= 2:
                holder["proc"].cancel()

        processor = BatchProcessor(
            source_dir=sample_source, settings=AppSettings(),
            on_progress=on_progress,
        )
        holder["proc"] = processor
        processor.run()
        assert processor.stats.cancelled
        assert 2 <= processor.stats.processed < processor.stats.total


class TestManualOverrideRender:
    def test_adjusted_render_used_for_review(self, sample_source, engine,
                                             default_settings):
        from processing.processor import load_and_analyze, render_from_analysis

        bgr, result = load_and_analyze(sample_source / "IMG_0003.JPG", engine)
        assert len(result.faces) == 2
        r_face0 = render_from_analysis(bgr, result, default_settings.crop,
                                       default_settings.quality, face_index=0)
        r_face1 = render_from_analysis(bgr, result, default_settings.crop,
                                       default_settings.quality, face_index=1)
        assert r_face0.face_index != r_face1.face_index
        assert (r_face0.output_bgr != r_face1.output_bgr).any()
        adjusted = render_from_analysis(
            bgr, result, default_settings.crop, default_settings.quality,
            face_index=0, adjust=ManualAdjust(dx=30, zoom=1.1),
        )
        assert (adjusted.output_bgr != r_face0.output_bgr).any()


class TestContactSheets:
    def test_sheets_created_with_captions_dir(self, finished_batch):
        sheets = generate_contact_sheets(
            finished_batch.source_dir, finished_batch.crop_root)
        assert len(sheets) == 1  # few images -> one page
        assert sheets[0].name == "contact_sheet_001.jpg"
        assert sheets[0].parent.name == "CONTACT_SHEETS"
        with Image.open(sheets[0]) as im:
            assert im.width > 1000

    def test_pagination_beyond_30_images(self, tmp_path, finished_batch):
        # Duplicate one processed image 35 times in a fake crop folder.
        crop = tmp_path / "many_crop"
        crop.mkdir()
        blob = (finished_batch.crop_root / "IMG_0001.JPG").read_bytes()
        for i in range(35):
            (crop / f"IMG_{i:04d}.JPG").write_bytes(blob)
        source = tmp_path / "many"
        source.mkdir()
        sheets = generate_contact_sheets(source, crop)
        assert [s.name for s in sheets] == ["contact_sheet_001.jpg",
                                            "contact_sheet_002.jpg"]
