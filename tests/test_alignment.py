"""Affine alignment math: eye leveling, scaling, positioning, adjustments."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.settings import CropSettings
from processing.alignment import (
    ManualAdjust,
    apply_manual_adjust,
    compute_alignment,
    matrix_scale,
    output_corners_in_source,
    transform_points,
)
from processing.landmarks import eye_geometry

CROP = CropSettings()  # 600x800, eyes at (50%, 40%), eye distance 34%
TARGET = (300.0, 320.0)
TARGET_DIST = 204.0  # 34% of 600


def _eyes_after(m, left, right):
    pts = transform_points(m, np.array([left, right], dtype=float))
    return pts[0], pts[1]


class TestEyeGeometry:
    def test_midpoint_distance_angle(self):
        mid, dist, angle = eye_geometry((100, 100), (200, 100))
        assert mid == (150, 100)
        assert dist == pytest.approx(100)
        assert angle == pytest.approx(0)

    def test_tilted_angle(self):
        d = 80.0
        right = (100 + d * math.cos(math.radians(30)),
                 100 + d * math.sin(math.radians(30)))
        _, dist, angle = eye_geometry((100, 100), right)
        assert dist == pytest.approx(d)
        assert angle == pytest.approx(30)


class TestComputeAlignment:
    def test_horizontal_eyes_map_to_targets(self):
        info = compute_alignment((100, 100), (200, 100), CROP)
        left, right = _eyes_after(info.matrix, (100, 100), (200, 100))
        assert left[1] == pytest.approx(TARGET[1], abs=1e-6)
        assert right[1] == pytest.approx(TARGET[1], abs=1e-6)
        assert right[0] - left[0] == pytest.approx(TARGET_DIST, abs=1e-6)
        mid = ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
        assert mid == pytest.approx(TARGET, abs=1e-6)
        assert info.scale == pytest.approx(TARGET_DIST / 100.0)

    @pytest.mark.parametrize("tilt_deg", [-35, -12, 8, 25])
    def test_tilted_eyes_become_level(self, tilt_deg):
        d = 150.0
        left = (400.0, 500.0)
        right = (left[0] + d * math.cos(math.radians(tilt_deg)),
                 left[1] + d * math.sin(math.radians(tilt_deg)))
        info = compute_alignment(left, right, CROP)
        assert info.angle_deg == pytest.approx(tilt_deg, abs=1e-6)
        new_left, new_right = _eyes_after(info.matrix, left, right)
        assert new_left[1] == pytest.approx(new_right[1], abs=1e-6)  # level
        assert new_right[0] > new_left[0]  # orientation preserved
        assert new_right[0] - new_left[0] == pytest.approx(TARGET_DIST, abs=1e-6)

    def test_degenerate_eyes_rejected(self):
        with pytest.raises(ValueError):
            compute_alignment((10, 10), (10.5, 10), CROP)

    def test_custom_settings_respected(self):
        crop = CropSettings(output_width=900, output_height=1200,
                            eye_center_x_pct=45, eye_center_y_pct=38,
                            eye_distance_pct=30)
        info = compute_alignment((0, 0), (100, 0), crop)
        left, right = _eyes_after(info.matrix, (0, 0), (100, 0))
        assert right[0] - left[0] == pytest.approx(270)  # 30% of 900
        mid = ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
        assert mid == pytest.approx((405, 456))  # 45% of 900, 38% of 1200


class TestManualAdjust:
    def test_identity_returns_same_mapping(self):
        info = compute_alignment((100, 100), (220, 130), CROP)
        m = apply_manual_adjust(info, CROP, ManualAdjust())
        assert np.allclose(m, info.matrix)

    def test_zoom_scales_about_eye_target(self):
        info = compute_alignment((100, 100), (200, 100), CROP)
        m = apply_manual_adjust(info, CROP, ManualAdjust(zoom=1.25))
        left, right = _eyes_after(m, (100, 100), (200, 100))
        assert right[0] - left[0] == pytest.approx(TARGET_DIST * 1.25)
        mid = ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
        assert mid == pytest.approx(TARGET)  # pivot unchanged

    def test_translation_moves_everything(self):
        info = compute_alignment((100, 100), (200, 100), CROP)
        m = apply_manual_adjust(info, CROP, ManualAdjust(dx=24, dy=-18))
        left, right = _eyes_after(m, (100, 100), (200, 100))
        mid = ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
        assert mid == pytest.approx((TARGET[0] + 24, TARGET[1] - 18))

    def test_rotation_pivots_on_eye_target(self):
        info = compute_alignment((100, 100), (200, 100), CROP)
        m = apply_manual_adjust(info, CROP, ManualAdjust(rotate_deg=10))
        pts = transform_points(m, np.array([[150.0, 100.0]]))  # eye midpoint
        assert pts[0] == pytest.approx(TARGET, abs=1e-6)


class TestMatrixHelpers:
    def test_matrix_scale(self):
        info = compute_alignment((0, 0), (100, 0), CROP)
        assert matrix_scale(info.matrix) == pytest.approx(2.04)

    def test_output_corners_roundtrip(self):
        info = compute_alignment((500, 400), (700, 460), CROP)
        corners_src = output_corners_in_source(info.matrix, 600, 800)
        back = transform_points(info.matrix, corners_src)
        expected = np.array([[0, 0], [599, 0], [599, 799], [0, 799]], dtype=float)
        assert np.allclose(back, expected, atol=1e-6)
