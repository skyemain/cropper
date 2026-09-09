"""Facial landmark geometry helpers (MediaPipe Face Landmarker topology).

Eye centers are computed from several landmarks (iris ring when available,
eyelid contour otherwise) instead of trusting a single point. "Left"/"right"
below always refer to IMAGE coordinates (left = smaller x), which is what the
cropping geometry needs; MediaPipe's subject-relative naming is resolved here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# MediaPipe FaceMesh/FaceLandmarker indices (478-landmark model with iris).
RIGHT_IRIS = [468, 469, 470, 471, 472]  # subject's right eye
LEFT_IRIS = [473, 474, 475, 476, 477]  # subject's left eye
RIGHT_EYE_CONTOUR = [33, 133, 159, 145, 158, 153, 160, 144]
LEFT_EYE_CONTOUR = [362, 263, 386, 374, 385, 380, 387, 373]
FOREHEAD_TOP = 10  # top of the face oval (hairline area)
CHIN = 152
NOSE_TIP = 1

FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379,
    378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127,
    162, 21, 54, 103, 67, 109,
]


@dataclass
class FaceData:
    """One detected face, fully measured in original-image pixel coordinates."""

    landmarks_px: np.ndarray  # (N, 2) float32
    left_eye: tuple[float, float]  # image-left eye center
    right_eye: tuple[float, float]  # image-right eye center
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 of landmarks
    confidence: float = 0.5
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    has_pose: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def bbox_area(self) -> float:
        x0, y0, x1, y1 = self.bbox
        return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def landmarks_to_px(normalized, width: int, height: int) -> np.ndarray:
    """Convert MediaPipe normalized landmarks to pixel coordinates."""
    pts = np.array([(lm.x * width, lm.y * height) for lm in normalized], dtype=np.float32)
    return pts


def _mean_of(pts: np.ndarray, indices: list[int]) -> tuple[float, float] | None:
    valid = [i for i in indices if i < len(pts)]
    if not valid:
        return None
    sub = pts[valid]
    return float(sub[:, 0].mean()), float(sub[:, 1].mean())


def eye_centers_px(pts: np.ndarray) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (image_left_eye, image_right_eye) centers.

    Each center is the mean of the 5 iris landmarks when the model provides
    them, otherwise the mean of 8 eyelid-contour landmarks.
    """
    subj_right = _mean_of(pts, RIGHT_IRIS) or _mean_of(pts, RIGHT_EYE_CONTOUR)
    subj_left = _mean_of(pts, LEFT_IRIS) or _mean_of(pts, LEFT_EYE_CONTOUR)
    if subj_right is None or subj_left is None:
        raise ValueError("Not enough landmarks to locate the eyes")
    if subj_right[0] <= subj_left[0]:
        return subj_right, subj_left
    return subj_left, subj_right


def landmarks_bbox(pts: np.ndarray) -> tuple[float, float, float, float]:
    return (
        float(pts[:, 0].min()),
        float(pts[:, 1].min()),
        float(pts[:, 0].max()),
        float(pts[:, 1].max()),
    )


def pose_from_matrix(matrix: np.ndarray) -> tuple[float, float, float]:
    """Extract (yaw, pitch, roll) in degrees from a MediaPipe 4x4
    facial transformation matrix. Used only for QA thresholds, so exact sign
    conventions are unimportant; magnitudes are what matter."""
    r = np.asarray(matrix, dtype=np.float64)[:3, :3]
    # Remove any scale component column-wise.
    norms = np.linalg.norm(r, axis=0)
    norms[norms == 0] = 1.0
    r = r / norms
    sy = math.hypot(r[0, 0], r[1, 0])
    if sy > 1e-6:
        pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
        yaw = math.degrees(math.atan2(-r[2, 0], sy))
        roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    else:  # gimbal lock
        pitch = math.degrees(math.atan2(-r[1, 2], r[1, 1]))
        yaw = math.degrees(math.atan2(-r[2, 0], sy))
        roll = 0.0
    return yaw, pitch, roll


def eye_geometry(
    left_eye: tuple[float, float], right_eye: tuple[float, float]
) -> tuple[tuple[float, float], float, float]:
    """Return (midpoint, distance_px, angle_degrees) of the eye line."""
    dx = right_eye[0] - left_eye[0]
    dy = right_eye[1] - left_eye[1]
    midpoint = ((left_eye[0] + right_eye[0]) / 2.0, (left_eye[1] + right_eye[1]) / 2.0)
    return midpoint, math.hypot(dx, dy), math.degrees(math.atan2(dy, dx))
