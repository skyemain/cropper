"""Source-safety proof: processing must never modify the source folder.

Hashes every source file before and after a full batch (including a resumed
run and contact sheets) and verifies names, sizes, contents, and directory
structure are bit-for-bit unchanged.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.settings import AppSettings
from processing.contact_sheet import generate_contact_sheets
from processing.processor import EXISTING_REPROCESS, BatchProcessor


def snapshot(folder: Path) -> dict[str, tuple[int, str]]:
    """Map of relative path -> (size, sha256) for every file under folder."""
    result: dict[str, tuple[int, str]] = {}
    for root, dirs, files in os.walk(folder):
        for name in files:
            path = Path(root) / name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[str(path.relative_to(folder))] = (path.stat().st_size, digest)
    return result


def test_source_folder_is_bit_for_bit_unchanged(sample_source: Path, engine):
    before = snapshot(sample_source)
    mtimes_before = {
        p.name: p.stat().st_mtime_ns for p in sample_source.iterdir() if p.is_file()
    }

    # Full run, a skip-mode resume, a reprocess run, and contact sheets.
    for mode in (None, "skip", EXISTING_REPROCESS):
        processor = BatchProcessor(
            source_dir=sample_source, settings=AppSettings(),
            existing_mode=mode or "skip",
        )
        processor.run()
        assert processor.error is None
    generate_contact_sheets(sample_source, processor.crop_root)

    after = snapshot(sample_source)
    assert before == after, "source files changed (names, sizes, or contents)"

    mtimes_after = {
        p.name: p.stat().st_mtime_ns for p in sample_source.iterdir() if p.is_file()
    }
    assert mtimes_before == mtimes_after, "source file timestamps changed"

    # No new entries appeared inside the source folder (e.g. no output leaked in).
    assert {p.name for p in sample_source.iterdir()} == set(mtimes_before)

    # The output folder is a sibling, never nested in the source.
    crop_root = processor.crop_root
    assert crop_root.parent == sample_source.parent
    assert not str(crop_root.resolve()).startswith(str(sample_source.resolve()) + os.sep)


def test_failed_copy_is_identical_copy_not_move(sample_source: Path, engine):
    corrupt = sample_source / "IMG_0005.JPG"
    original_bytes = corrupt.read_bytes()
    processor = BatchProcessor(source_dir=sample_source, settings=AppSettings())
    processor.run()
    # Original still present and identical.
    assert corrupt.exists()
    assert corrupt.read_bytes() == original_bytes
    # The FAILED copy matches the original bytes exactly.
    failed_copy = processor.crop_root / "FAILED" / "IMG_0005.JPG"
    assert failed_copy.exists()
    assert failed_copy.read_bytes() == original_bytes
