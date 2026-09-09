"""Output-folder derivation, filename preservation, and write-safety rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from utilities.paths import (
    OutputSafetyError,
    derive_crop_root,
    enumerate_images,
    is_inside,
    resource_path,
    validate_output_path,
)


class TestDeriveCropRoot:
    def test_sibling_with_crop_suffix(self, tmp_path: Path):
        source = tmp_path / "Employee_IDs"
        source.mkdir()
        crop = derive_crop_root(source)
        assert crop == tmp_path / "Employee_IDs_crop"
        assert crop.parent == source.parent

    def test_never_inside_source(self, tmp_path: Path):
        source = tmp_path / "Photos"
        source.mkdir()
        crop = derive_crop_root(source)
        assert not is_inside(crop, source)

    def test_trailing_slash_is_harmless(self, tmp_path: Path):
        source = tmp_path / "Batch01"
        source.mkdir()
        assert derive_crop_root(Path(str(source) + "/")) == tmp_path / "Batch01_crop"

    def test_filesystem_root_rejected(self):
        with pytest.raises(OutputSafetyError):
            derive_crop_root(Path("/"))


class TestValidateOutputPath:
    @pytest.fixture()
    def dirs(self, tmp_path: Path) -> tuple[Path, Path]:
        source = tmp_path / "src"
        source.mkdir()
        crop = derive_crop_root(source)
        crop.mkdir()
        return source, crop

    def test_accepts_file_in_crop_root(self, dirs):
        source, crop = dirs
        resolved = validate_output_path(source, crop, crop / "IMG_0001.JPG")
        assert resolved == (crop / "IMG_0001.JPG").resolve()

    def test_accepts_review_subfolder(self, dirs):
        source, crop = dirs
        validate_output_path(source, crop, crop / "REVIEW" / "IMG_0001.JPG")

    def test_rejects_write_into_source(self, dirs):
        source, crop = dirs
        with pytest.raises(OutputSafetyError):
            validate_output_path(source, crop, source / "IMG_0001.JPG")

    def test_rejects_path_traversal_back_to_source(self, dirs):
        source, crop = dirs
        sneaky = crop / ".." / "src" / "IMG_0001.JPG"
        with pytest.raises(OutputSafetyError):
            validate_output_path(source, crop, sneaky)

    def test_rejects_destination_outside_crop_root(self, dirs, tmp_path: Path):
        source, crop = dirs
        with pytest.raises(OutputSafetyError):
            validate_output_path(source, crop, tmp_path / "elsewhere.jpg")

    def test_rejects_crop_root_inside_source(self, tmp_path: Path):
        source = tmp_path / "src"
        bad_crop = source / "src_crop"
        bad_crop.mkdir(parents=True)
        with pytest.raises(OutputSafetyError):
            validate_output_path(source, bad_crop, bad_crop / "a.jpg")

    def test_rejects_symlink_escape_to_source(self, dirs):
        source, crop = dirs
        link = crop / "link"
        try:
            link.symlink_to(source, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not available on this platform")
        with pytest.raises(OutputSafetyError):
            validate_output_path(source, crop, link / "IMG_0001.JPG")


class TestEnumerateImages:
    def test_supported_extensions_any_case(self, sample_source: Path):
        names = [p.name for p in enumerate_images(sample_source)]
        assert "IMG_0001.JPG" in names
        assert "DSC_1845.jpeg" in names
        assert "000123.png" in names
        assert "notes.txt" not in names

    def test_sorted_and_files_only(self, sample_source: Path):
        (sample_source / "subfolder").mkdir()
        names = [p.name for p in enumerate_images(sample_source)]
        assert names == sorted(names, key=str.lower)
        assert "subfolder" not in names

    def test_hidden_files_ignored(self, sample_source: Path):
        (sample_source / ".hidden.jpg").write_bytes(b"x")
        names = [p.name for p in enumerate_images(sample_source)]
        assert ".hidden.jpg" not in names


class TestResourcePath:
    def test_models_and_assets_resolve(self):
        assert (resource_path("models") / "face_landmarker.task").exists()
        assert resource_path("assets", "icon.ico").exists()
        assert resource_path("assets", "selftest_portrait.jpg").exists()
