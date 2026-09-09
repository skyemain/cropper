"""Debug overlay drawing for the preview screen.

Overlays are rendered onto a downscaled COPY for display only; they are never
written into processed output files.
"""

from __future__ import annotations

import cv2
import numpy as np

from processing.detector import EngineResult
from processing.landmarks import FACE_OVAL, LEFT_EYE_CONTOUR, RIGHT_EYE_CONTOUR

_BOX = (80, 190, 255)  # orange (BGR)
_BOX_OTHER = (160, 160, 160)
_EYE = (0, 230, 90)
_MID = (60, 80, 255)
_LINE = (0, 210, 255)
_LM = (230, 190, 60)


def draw_debug_overlay(
    bgr: np.ndarray, result: EngineResult, chosen_index: int, max_dim: int = 900
) -> np.ndarray:
    """Return a downscaled copy with face box, eye centers/line, and landmarks."""
    h, w = bgr.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    canvas = cv2.resize(
        bgr, (max(1, round(w * scale)), max(1, round(h * scale))),
        interpolation=cv2.INTER_AREA,
    ).copy()
    thick = max(1, round(canvas.shape[1] / 450))

    for idx, face in enumerate(result.faces):
        color = _BOX if idx == chosen_index else _BOX_OTHER
        x0, y0, x1, y1 = (v * scale for v in face.bbox)
        cv2.rectangle(canvas, (round(x0), round(y0)), (round(x1), round(y1)), color, thick)
        if len(result.faces) > 1:
            cv2.putText(
                canvas, f"face {idx + 1}", (round(x0), max(14, round(y0) - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, thick, cv2.LINE_AA,
            )
        if idx != chosen_index:
            continue

        pts = face.landmarks_px * scale
        for lm_idx in (*FACE_OVAL, *LEFT_EYE_CONTOUR, *RIGHT_EYE_CONTOUR):
            if lm_idx < len(pts):
                cv2.circle(canvas, (round(pts[lm_idx, 0]), round(pts[lm_idx, 1])),
                           max(1, thick - 1), _LM, -1, cv2.LINE_AA)

        left = (face.left_eye[0] * scale, face.left_eye[1] * scale)
        right = (face.right_eye[0] * scale, face.right_eye[1] * scale)
        mid = ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
        cv2.line(canvas, (round(left[0]), round(left[1])),
                 (round(right[0]), round(right[1])), _LINE, thick, cv2.LINE_AA)
        for point in (left, right):
            cv2.circle(canvas, (round(point[0]), round(point[1])),
                       thick * 3, _EYE, thick, cv2.LINE_AA)
        cv2.circle(canvas, (round(mid[0]), round(mid[1])), thick * 2, _MID, -1, cv2.LINE_AA)
    return canvas
