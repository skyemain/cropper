"""Quality assessment: blur metric and REVIEW-flag rules.

The blur score is the variance of the Laplacian computed on the central face
region of the FINAL standardized crop, which makes the number comparable
across source resolutions. Blur never fails an image outright - it only
flags it for human review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.settings import CropSettings, QualityConfig
from processing.alignment import output_corners_in_source, transform_points
from processing.landmarks import CHIN, FOREHEAD_TOP, FaceData

# Estimated hair allowance above the face-mesh forehead point, as a fraction
# of the forehead-to-chin distance.
HAIR_ALLOWANCE = 0.30


@dataclass
class QualityAssessment:
    review_reasons: list[str] = field(default_factory=list)
    blur_score: float = 0.0
    head_top_pct: float = 0.0  # estimated top of head, % of output height
    chin_pct: float = 0.0


def blur_score_of_crop(output_bgr: np.ndarray) -> float:
    """Variance of Laplacian over the central face area of the crop."""
    h, w = output_bgr.shape[:2]
    region = output_bgr[int(h * 0.15): int(h * 0.85), int(w * 0.20): int(w * 0.80)]
    if region.size == 0:
        region = output_bgr
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def assess(
    face: FaceData,
    matrix: np.ndarray,
    output_bgr: np.ndarray,
    source_shape: tuple[int, int],
    crop: CropSettings,
    cfg: QualityConfig,
    face_count: int,
    scale: float,
) -> QualityAssessment:
    """Run all QA rules for one processed image and collect review reasons."""
    qa = QualityAssessment()
    reasons = qa.review_reasons
    src_h, src_w = source_shape
    out_w, out_h = crop.output_width, crop.output_height

    if face_count > 1:
        reasons.append(f"multiple faces detected ({face_count})")

    if face.confidence < cfg.min_detection_confidence:
        reasons.append(f"low detection confidence ({face.confidence:.2f})")

    if face.has_pose:
        if abs(face.yaw) > cfg.max_abs_yaw_deg:
            reasons.append(f"head turned sideways (yaw {face.yaw:.0f} deg)")
        if abs(face.pitch) > cfg.max_abs_pitch_deg:
            reasons.append(f"head tilted up/down (pitch {face.pitch:.0f} deg)")
        if abs(face.roll) > cfg.max_abs_roll_deg:
            reasons.append(f"strong head tilt (roll {face.roll:.0f} deg)")

    eye_ratio = 0.0
    if src_w > 0:
        eye_dist = float(np.hypot(
            face.right_eye[0] - face.left_eye[0],
            face.right_eye[1] - face.left_eye[1],
        ))
        eye_ratio = eye_dist / src_w
        if eye_ratio < cfg.min_eye_distance_ratio:
            reasons.append(f"face is very small in the photo ({eye_ratio * 100:.1f}% of width)")

    if scale > cfg.max_upscale_factor:
        reasons.append(f"source resolution low for requested output (upscaled {scale:.2f}x)")

    # Head/chin framing in output space.
    pts = transform_points(matrix, face.landmarks_px[[FOREHEAD_TOP, CHIN]])
    forehead_y, chin_y = float(pts[0, 1]), float(pts[1, 1])
    face_height = max(1.0, chin_y - forehead_y)
    head_top_y = forehead_y - HAIR_ALLOWANCE * face_height
    qa.head_top_pct = head_top_y / out_h * 100.0
    qa.chin_pct = chin_y / out_h * 100.0
    if qa.head_top_pct < cfg.headroom_min_pct:
        reasons.append("top of head/hair may be cut off")
    elif qa.head_top_pct > cfg.headroom_max_pct:
        reasons.append("unusually large headroom (small face in crop)")
    if qa.chin_pct > cfg.chin_max_pct:
        reasons.append("chin very close to the bottom edge")

    # Face near the borders of the source photo.
    x0, y0, x1, y1 = face.bbox
    margin_x = cfg.face_border_margin_pct / 100.0 * src_w
    margin_y = cfg.face_border_margin_pct / 100.0 * src_h
    if x0 < margin_x or y0 < margin_y or x1 > src_w - margin_x or y1 > src_h - margin_y:
        reasons.append("face touches the edge of the photo")

    # Crop window escaping the source image (replicated border pixels).
    corners = output_corners_in_source(matrix, out_w, out_h)
    allowed = cfg.crop_overrun_pct / 100.0 * max(src_w, src_h)
    overrun = max(
        float(-corners[:, 0].min()),
        float(-corners[:, 1].min()),
        float(corners[:, 0].max() - (src_w - 1)),
        float(corners[:, 1].max() - (src_h - 1)),
        0.0,
    )
    if overrun > allowed:
        reasons.append("crop window extends past the photo edge")

    qa.blur_score = blur_score_of_crop(output_bgr)
    if qa.blur_score < cfg.blur_review_threshold:
        reasons.append(f"photo may be blurry (sharpness {qa.blur_score:.0f})")

    for note in face.notes:
        reasons.append(note)

    return qa
