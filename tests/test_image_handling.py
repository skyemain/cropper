"""Image IO: EXIF orientation, corrupt files, unusual modes, atomic writes."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from utilities.image_utils import (
    ImageLoadError,
    bgr_to_jpeg_base64,
    load_image_bgr,
    save_image,
)


class TestExifOrientation:
    def test_orientation_6_is_applied_in_memory(self, sample_source: Path):
        """IMG_0006.JPG stores sideways pixels + EXIF orientation 6; after
        loading it must have the same shape as the upright original."""
        upright = load_image_bgr(sample_source / "IMG_0001.JPG")
        exif_img = load_image_bgr(sample_source / "IMG_0006.JPG")
        assert exif_img.shape == upright.shape

    def test_source_file_untouched_by_loading(self, sample_source: Path):
        path = sample_source / "IMG_0006.JPG"
        before = path.read_bytes()
        load_image_bgr(path)
        assert path.read_bytes() == before


class TestRobustDecoding:
    def test_corrupt_file_raises_clean_error(self, sample_source: Path):
        with pytest.raises(ImageLoadError):
            load_image_bgr(sample_source / "IMG_0005.JPG")

    def test_missing_file_raises_clean_error(self, tmp_path: Path):
        with pytest.raises(ImageLoadError):
            load_image_bgr(tmp_path / "nope.jpg")

    def test_text_file_raises_clean_error(self, tmp_path: Path):
        bad = tmp_path / "fake.jpg"
        bad.write_text("this is not a jpeg")
        with pytest.raises(ImageLoadError):
            load_image_bgr(bad)

    def test_grayscale_and_rgba_convert_to_bgr(self, tmp_path: Path):
        gray = tmp_path / "gray.png"
        Image.new("L", (64, 48), 128).save(gray)
        arr = load_image_bgr(gray)
        assert arr.shape == (48, 64, 3)

        rgba = tmp_path / "rgba.png"
        Image.new("RGBA", (64, 48), (255, 0, 0, 0)).save(rgba)  # fully transparent
        arr = load_image_bgr(rgba)
        assert arr.shape == (48, 64, 3)
        # Transparent red over white background must come out white.
        assert arr[0, 0].tolist() == [255, 255, 255]

    def test_bgr_channel_order(self, tmp_path: Path):
        path = tmp_path / "red.png"
        Image.new("RGB", (8, 8), (255, 0, 0)).save(path)
        arr = load_image_bgr(path)
        assert arr[0, 0].tolist() == [0, 0, 255]  # red in BGR


class TestSaving:
    def test_atomic_write_leaves_no_partial_file(self, tmp_path: Path):
        img = np.full((10, 10, 3), 200, dtype=np.uint8)
        dest = tmp_path / "out.jpg"
        save_image(img, dest)
        assert dest.exists()
        assert not list(tmp_path.glob("*.part"))

    def test_extension_case_is_preserved_and_encodable(self, tmp_path: Path):
        img = np.full((10, 10, 3), 100, dtype=np.uint8)
        dest = tmp_path / "OUT.JPG"
        save_image(img, dest)
        assert (tmp_path / "OUT.JPG").exists()
        with Image.open(dest) as im:
            assert im.format == "JPEG"

    def test_unsupported_extension_rejected(self, tmp_path: Path):
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        with pytest.raises(ValueError):
            save_image(img, tmp_path / "out.bmp")

    def test_preview_base64_is_valid_jpeg(self):
        img = np.random.default_rng(1).integers(
            0, 255, (300, 200, 3), dtype=np.uint8)
        b64 = bgr_to_jpeg_base64(img, max_dim=128)
        import base64
        blob = base64.b64decode(b64)
        with Image.open(io.BytesIO(blob)) as im:
            assert im.format == "JPEG"
            assert max(im.size) <= 128
