"""Affine alignment: rotation, scale, and translation in a single transform.

The face is normalized from eye geometry only (never by centering a bounding
box): the eye line is made horizontal, the eye-to-eye distance is scaled to a
fixed fraction of the output width, and the eye midpoint is placed at a fixed
output position. Manual review adjustments compose on top of the same matrix
so the interactive preview and the saved result are always identical.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.settings import CropSettings
from processing.landmarks import eye_geometry


@dataclass
class ManualAdjust:
    """User adjustments from the review screen, applied in output space."""

    dx: float = 0.0  # px, positive moves the crop window right (image left)
    dy: float = 0.0  # px, positive moves the crop window down (image up)
    zoom: float = 1.0
    rotate_deg: float = 0.0

    def is_identity(self) -> bool:
        return (
            abs(self.dx) < 1e-6
            and abs(self.dy) < 1e-6
            and abs(self.zoom - 1.0) < 1e-6
            and abs(self.rotate_deg) < 1e-6
        )


@dataclass
class AlignmentInfo:
    matrix: np.ndarray  # 2x3 affine, source px -> output px
    angle_deg: float  # measured eye-line tilt in the source image
    eye_distance_px: float  # measured eye distance in the source image
    scale: float  # overall source->output scale factor
    eye_midpoint_src: tuple[float, float]
    eye_target_out: tuple[float, float]


def compute_alignment(
    left_eye: tuple[float, float],
    right_eye: tuple[float, float],
    crop: CropSettings,
) -> AlignmentInfo:
    """Build the affine matrix that levels, scales, and positions the face."""
    midpoint, eye_dist, angle_deg = eye_geometry(left_eye, right_eye)
    if eye_dist < 2.0:
        raise ValueError("Eye landmarks are degenerate (distance < 2 px)")

    target_eye_dist = crop.eye_distance_pct / 100.0 * crop.output_width
    scale = target_eye_dist / eye_dist
    target = (
        crop.eye_center_x_pct / 100.0 * crop.output_width,
        crop.eye_center_y_pct / 100.0 * crop.output_height,
    )

    # Rotate by the measured eye-line angle around the eye midpoint (this
    # levels the eyes), scale about the same point, then translate the
    # midpoint onto the target output position.
    matrix = cv2.getRotationMatrix2D(midpoint, angle_deg, scale)
    matrix[0, 2] += target[0] - midpoint[0]
    matrix[1, 2] += target[1] - midpoint[1]

    return AlignmentInfo(
        matrix=matrix,
        angle_deg=angle_deg,
        eye_distance_px=eye_dist,
        scale=scale,
        eye_midpoint_src=midpoint,
        eye_target_out=target,
    )


def _as_3x3(m2x3: np.ndarray) -> np.ndarray:
    m = np.eye(3, dtype=np.float64)
    m[:2, :] = m2x3
    return m


def apply_manual_adjust(
    base: AlignmentInfo, crop: CropSettings, adjust: ManualAdjust
) -> np.ndarray:
    """Compose zoom/rotation (about the eye target) and panning on top of the
    automatic alignment matrix. Returns a new 2x3 matrix."""
    if adjust.is_identity():
        return base.matrix.copy()
    pivot = base.eye_target_out
    extra = cv2.getRotationMatrix2D(pivot, adjust.rotate_deg, adjust.zoom)
    extra[0, 2] += adjust.dx
    extra[1, 2] += adjust.dy
    combined = _as_3x3(extra) @ _as_3x3(base.matrix)
    return combined[:2, :].astype(np.float64)


def transform_points(m2x3: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Apply a 2x3 affine to an (N, 2) array of points."""
    pts = np.asarray(points, dtype=np.float64)
    ones = np.ones((pts.shape[0], 1), dtype=np.float64)
    return np.hstack([pts, ones]) @ np.asarray(m2x3, dtype=np.float64).T


def matrix_scale(m2x3: np.ndarray) -> float:
    """Uniform scale factor embedded in the affine matrix."""
    return float(np.hypot(m2x3[0, 0], m2x3[1, 0]))


def output_corners_in_source(m2x3: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Back-project the output rectangle corners into source coordinates."""
    inverse = cv2.invertAffineTransform(np.asarray(m2x3, dtype=np.float64))
    corners = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float64,
    )
    return transform_points(inverse, corners)
