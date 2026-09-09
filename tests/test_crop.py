"""End-to-end crop geometry: output dimensions and eye placement, verified by
re-detecting the face on the produced crop."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.settings import CropSettings
from processing.processor import load_and_analyze, render_from_analysis
from utilities.image_utils import load_image_bgr, save_image


@pytest.fixture()
def clean_jpg(sample_source: Path) -> Path:
    return sample_source / "IMG_0001.JPG"


class TestRenderCrop:
    def test_output_has_exact_requested_dimensions(self, clean_jpg, engine,
                                                   default_settings):
        bgr, result = load_and_analyze(clean_jpg, engine)
        rendered = render_from_analysis(bgr, result, default_settings.crop,
                                        default_settings.quality)
        h, w = rendered.output_bgr.shape[:2]
        assert (w, h) == (600, 800)

    def test_eyes_land_on_configured_position(self, clean_jpg, engine,
                                              default_settings):
        """Re-detect the face on the produced crop: the eye midpoint must sit
        at (50%, 40%) and the eye distance at 34% of width."""
        bgr, result = load_and_analyze(clean_jpg, engine)
        rendered = render_from_analysis(bgr, result, default_settings.crop,
                                        default_settings.quality)
        recheck = engine.analyze(rendered.output_bgr, try_rotations=False)
        assert len(recheck.faces) == 1
        face = recheck.faces[0]
        mid_x = (face.left_eye[0] + face.right_eye[0]) / 2
        mid_y = (face.left_eye[1] + face.right_eye[1]) / 2
        dist = float(np.hypot(face.right_eye[0] - face.left_eye[0],
                              face.right_eye[1] - face.left_eye[1]))
        assert mid_x == pytest.approx(300, abs=600 * 0.03)
        assert mid_y == pytest.approx(320, abs=800 * 0.03)
        assert dist == pytest.approx(204, rel=0.06)
        # Eyes level after alignment.
        assert abs(face.right_eye[1] - face.left_eye[1]) < 600 * 0.015

    def test_rotated_source_comes_out_level(self, sample_source, engine,
                                            default_settings):
        bgr, result = load_and_analyze(sample_source / "IMG_0002.JPG", engine)
        assert result.faces, "rotated fixture must still be detectable"
        rendered = render_from_analysis(bgr, result, default_settings.crop,
                                        default_settings.quality)
        # The fixture was rotated by 18 deg; the astronaut has ~3 deg natural
        # roll, so the measured eye-line angle must be around -15 deg.
        assert rendered.alignment.angle_deg == pytest.approx(-15, abs=4)
        recheck = engine.analyze(rendered.output_bgr, try_rotations=False)
        assert recheck.faces
        face = recheck.faces[0]
        assert abs(face.right_eye[1] - face.left_eye[1]) < 600 * 0.02

    def test_custom_output_size(self, clean_jpg, engine):
        crop = CropSettings(output_width=413, output_height=531,  # 35x45 mm @300dpi
                            eye_distance_pct=32).validated()
        bgr, result = load_and_analyze(clean_jpg, engine)
        from app.settings import QualityConfig
        rendered = render_from_analysis(bgr, result, crop, QualityConfig())
        h, w = rendered.output_bgr.shape[:2]
        assert (w, h) == (413, 531)

    def test_large_source_downscale_path(self, clean_portrait, tmp_path, engine,
                                         default_settings):
        """A big (2.6x upscaled fixture -> 2704x3609) source exercises the
        INTER_AREA pre-shrink branch and must produce identical geometry."""
        big = clean_portrait.resize((2704, 3609))
        big_path = tmp_path / "BIG_0001.JPG"
        big.save(big_path, "JPEG", quality=92)
        bgr, result = load_and_analyze(big_path, engine)
        rendered = render_from_analysis(bgr, result, default_settings.crop,
                                        default_settings.quality)
        assert rendered.matrix is not None
        from processing.alignment import matrix_scale
        assert matrix_scale(rendered.matrix) < 0.5  # pre-shrink branch used
        recheck = engine.analyze(rendered.output_bgr, try_rotations=False)
        assert recheck.faces
        face = recheck.faces[0]
        mid_x = (face.left_eye[0] + face.right_eye[0]) / 2
        mid_y = (face.left_eye[1] + face.right_eye[1]) / 2
        assert mid_x == pytest.approx(300, abs=600 * 0.03)
        assert mid_y == pytest.approx(320, abs=800 * 0.03)


class TestSaveRoundtrip:
    def test_jpeg_quality_and_decodability(self, clean_jpg, tmp_path, engine,
                                           default_settings):
        bgr, result = load_and_analyze(clean_jpg, engine)
        rendered = render_from_analysis(bgr, result, default_settings.crop,
                                        default_settings.quality)
        out_hq = tmp_path / "hq.jpg"
        out_lq = tmp_path / "lq.jpg"
        save_image(rendered.output_bgr, out_hq, jpeg_quality=95)
        save_image(rendered.output_bgr, out_lq, jpeg_quality=60)
        assert out_hq.stat().st_size > out_lq.stat().st_size
        again = load_image_bgr(out_hq)
        assert again.shape == (800, 600, 3)

    def test_png_roundtrip(self, clean_jpg, tmp_path, engine, default_settings):
        bgr, result = load_and_analyze(clean_jpg, engine)
        rendered = render_from_analysis(bgr, result, default_settings.crop,
                                        default_settings.quality)
        out = tmp_path / "result.png"
        save_image(rendered.output_bgr, out)
        again = load_image_bgr(out)
        assert np.array_equal(again, rendered.output_bgr)  # PNG is lossless
