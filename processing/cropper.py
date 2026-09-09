"""Rendering the aligned crop with quality-preserving resampling.

The whole geometric normalization is one affine warp. For large downscales
(24 MP camera images to a 600 px crop) the image is first reduced with
area-averaging interpolation to just above the target scale, then the exact
affine warp finishes with Lanczos resampling. This avoids the aliasing a
single warpAffine would produce while still decoding and encoding only once.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.settings import CropSettings
from processing.alignment import (
    AlignmentInfo,
    ManualAdjust,
    apply_manual_adjust,
    compute_alignment,
    matrix_scale,
)
from processing.landmarks import FaceData

# When the total scale is below this, pre-shrink with INTER_AREA first.
_AREA_THRESHOLD = 0.5


def warp_to_output(bgr: np.ndarray, m2x3: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Apply the affine transform, using two-stage resampling for big shrinks."""
    matrix = np.asarray(m2x3, dtype=np.float64).copy()
    scale = matrix_scale(matrix)
    src = bgr
    if 0 < scale < _AREA_THRESHOLD:
        h, w = bgr.shape[:2]
        pre = scale / _AREA_THRESHOLD  # leaves ~0.5x for the final warp
        new_w = max(2, round(w * pre))
        new_h = max(2, round(h * pre))
        src = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        # Compensate the matrix for the pre-scale (use the exact realized
        # factors, which differ slightly from `pre` due to rounding).
        fx, fy = new_w / w, new_h / h
        matrix[:, 0] /= fx
        matrix[:, 1] /= fy
    interp = cv2.INTER_LANCZOS4 if matrix_scale(matrix) <= 1.2 else cv2.INTER_CUBIC
    return cv2.warpAffine(
        src,
        matrix,
        (int(out_w), int(out_h)),
        flags=interp,
        borderMode=cv2.BORDER_REPLICATE,
    )


def render_crop(
    bgr: np.ndarray,
    face: FaceData,
    crop: CropSettings,
    adjust: ManualAdjust | None = None,
) -> tuple[np.ndarray, AlignmentInfo, np.ndarray]:
    """Produce the final output image for one face.

    Returns (output_bgr, alignment_info, effective_matrix). The effective
    matrix includes any manual adjustment and is what QA checks should use.
    """
    info = compute_alignment(face.left_eye, face.right_eye, crop)
    matrix = (
        apply_manual_adjust(info, crop, adjust)
        if adjust is not None
        else info.matrix.copy()
    )
    output = warp_to_output(bgr, matrix, crop.output_width, crop.output_height)
    return output, info, matrix
