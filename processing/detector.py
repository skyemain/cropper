"""MediaPipe face engine: detection + landmarks with cached model instances.

Uses the modern MediaPipe Tasks API:
  * FaceDetector (BlazeFace short-range) for face counting and detection
    confidence scores,
  * FaceLandmarker (478 landmarks incl. iris, with facial transformation
    matrix) for eye geometry and pose.

Both models are bundled locally in ``models/`` - no network access is ever
performed. Model objects are created once and reused for the whole batch; a
lock makes the engine safe to share between the GUI and the worker thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

from processing.landmarks import (
    FaceData,
    eye_centers_px,
    landmarks_bbox,
    landmarks_to_px,
    pose_from_matrix,
)
from utilities.logging_utils import get_logger
from utilities.paths import resource_path

LANDMARKER_MODEL = "face_landmarker.task"
DETECTOR_MODEL = "blaze_face_short_range.tflite"

# Detection runs on a downscaled copy for speed; landmarks are normalized, so
# they are mapped back to full resolution with no precision loss in practice.
INFERENCE_MAX_DIM = 1600
MAX_FACES = 8


class EngineInitError(Exception):
    """MediaPipe could not be initialized (missing model, bad install...)."""


@dataclass
class EngineResult:
    """Everything the pipeline needs to know about one analyzed image."""

    faces: list[FaceData] = field(default_factory=list)
    detector_count: int = 0
    face_count: int = 0
    auto_rotation: int = 0  # degrees CW applied before detection succeeded
    image_bgr: np.ndarray | None = None  # rotated copy when auto_rotation != 0

    def primary_face_index(self) -> int:
        """Largest face by landmark bounding box area."""
        if not self.faces:
            raise ValueError("No faces available")
        areas = [f.bbox_area for f in self.faces]
        return int(np.argmax(areas))


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union > 0 else 0.0


class FaceEngine:
    """Cached MediaPipe FaceDetector + FaceLandmarker."""

    def __init__(self, models_dir: Path | None = None):
        models_dir = Path(models_dir) if models_dir else resource_path("models")
        landmarker_path = models_dir / LANDMARKER_MODEL
        detector_path = models_dir / DETECTOR_MODEL
        for p in (landmarker_path, detector_path):
            if not p.exists():
                raise EngineInitError(
                    f"Required model file is missing: {p}. "
                    "Reinstall the application to restore the bundled models."
                )
        try:
            self._landmarker = mp_vision.FaceLandmarker.create_from_options(
                mp_vision.FaceLandmarkerOptions(
                    base_options=mp_tasks.BaseOptions(model_asset_path=str(landmarker_path)),
                    running_mode=mp_vision.RunningMode.IMAGE,
                    num_faces=MAX_FACES,
                    min_face_detection_confidence=0.5,
                    min_face_presence_confidence=0.5,
                    output_facial_transformation_matrixes=True,
                )
            )
            self._detector = mp_vision.FaceDetector.create_from_options(
                mp_vision.FaceDetectorOptions(
                    base_options=mp_tasks.BaseOptions(model_asset_path=str(detector_path)),
                    min_detection_confidence=0.4,
                )
            )
        except Exception as exc:  # mediapipe raises various RuntimeErrors
            raise EngineInitError(f"MediaPipe initialization failed: {exc}") from exc
        self._lock = threading.Lock()
        get_logger().info("Face engine initialized (models: %s)", models_dir)

    def close(self) -> None:
        with self._lock:
            self._landmarker.close()
            self._detector.close()

    # ------------------------------------------------------------------

    def _landmark_via_crop(
        self,
        bgr: np.ndarray,
        det_box: tuple[float, float, float, float],
        score: float,
    ) -> FaceData | None:
        """Landmark one detector hit by re-running the landmarker on a padded
        crop around it. Rescues faces that are too small relative to the whole
        frame for the landmarker's internal detector."""
        full_h, full_w = bgr.shape[:2]
        x0, y0, x1, y1 = det_box
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        half = max(x1 - x0, y1 - y0) * 1.6
        cx0, cy0 = max(0, int(cx - half)), max(0, int(cy - half))
        cx1, cy1 = min(full_w, int(cx + half)), min(full_h, int(cy + half))
        if cx1 - cx0 < 24 or cy1 - cy0 < 24:
            return None
        crop = np.ascontiguousarray(bgr[cy0:cy1, cx0:cx1, ::-1])
        result = self._landmarker.detect(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)
        )
        if not result.face_landmarks:
            return None
        # Pick the landmarked face nearest to the crop center.
        ch, cw = crop.shape[:2]
        best_idx, best_dist = 0, float("inf")
        for idx, lms in enumerate(result.face_landmarks):
            pts = landmarks_to_px(lms, cw, ch)
            fx, fy = pts[:, 0].mean(), pts[:, 1].mean()
            dist = (fx - cw / 2) ** 2 + (fy - ch / 2) ** 2
            if dist < best_dist:
                best_idx, best_dist = idx, dist
        pts = landmarks_to_px(result.face_landmarks[best_idx], cw, ch)
        pts[:, 0] += cx0
        pts[:, 1] += cy0
        try:
            left_eye, right_eye = eye_centers_px(pts)
        except ValueError:
            return None
        face = FaceData(
            landmarks_px=pts, left_eye=left_eye, right_eye=right_eye,
            bbox=landmarks_bbox(pts), confidence=score,
        )
        matrices = list(getattr(result, "facial_transformation_matrixes", []) or [])
        if best_idx < len(matrices):
            try:
                face.yaw, face.pitch, face.roll = pose_from_matrix(
                    np.asarray(matrices[best_idx])
                )
                face.has_pose = True
            except (ValueError, IndexError):
                face.has_pose = False
        face.notes.append("small face landmarked via detector crop")
        return face

    def _run_models(self, bgr: np.ndarray) -> tuple[list[FaceData], int]:
        """Run detector + landmarker on one BGR image, return faces + count."""
        full_h, full_w = bgr.shape[:2]
        scale = min(1.0, INFERENCE_MAX_DIM / max(full_h, full_w))
        if scale < 1.0:
            small = cv2.resize(
                bgr,
                (max(1, round(full_w * scale)), max(1, round(full_h * scale))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            small = bgr
        rgb = np.ascontiguousarray(small[:, :, ::-1])
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        det_result = self._detector.detect(mp_image)
        lm_result = self._landmarker.detect(mp_image)

        # Detector boxes back to full resolution for matching.
        inv = 1.0 / scale if scale > 0 else 1.0
        det_boxes: list[tuple[tuple[float, float, float, float], float]] = []
        for det in det_result.detections:
            box = det.bounding_box
            score = det.categories[0].score if det.categories else 0.0
            det_boxes.append(
                (
                    (
                        box.origin_x * inv,
                        box.origin_y * inv,
                        (box.origin_x + box.width) * inv,
                        (box.origin_y + box.height) * inv,
                    ),
                    float(score),
                )
            )

        faces: list[FaceData] = []
        matrices = list(getattr(lm_result, "facial_transformation_matrixes", []) or [])
        for idx, norm_lms in enumerate(lm_result.face_landmarks):
            pts = landmarks_to_px(norm_lms, full_w, full_h)
            try:
                left_eye, right_eye = eye_centers_px(pts)
            except ValueError:
                continue
            bbox = landmarks_bbox(pts)
            face = FaceData(
                landmarks_px=pts, left_eye=left_eye, right_eye=right_eye, bbox=bbox
            )
            if idx < len(matrices):
                try:
                    face.yaw, face.pitch, face.roll = pose_from_matrix(
                        np.asarray(matrices[idx])
                    )
                    face.has_pose = True
                except (ValueError, IndexError):
                    face.has_pose = False
            best = 0.0
            for det_box, score in det_boxes:
                if _iou(bbox, det_box) > 0.25 and score > best:
                    best = score
            # The landmarker found this face even if the coarse detector did
            # not; treat that as medium confidence so QA can flag it.
            face.confidence = best if best > 0 else 0.5
            if best == 0.0:
                face.notes.append("face found by landmarker but not by detector")
            faces.append(face)

        # Rescue detector hits the full-frame landmarker missed (small faces).
        for det_box, score in det_boxes:
            if any(_iou(face.bbox, det_box) > 0.25 for face in faces):
                continue
            rescued = self._landmark_via_crop(bgr, det_box, score)
            if rescued is not None and not any(
                _iou(face.bbox, rescued.bbox) > 0.3 for face in faces
            ):
                faces.append(rescued)
        return faces, len(det_boxes)

    def _shift_faces(self, faces: list[FaceData], dx: float, dy: float) -> None:
        for face in faces:
            face.landmarks_px[:, 0] += dx
            face.landmarks_px[:, 1] += dy
            face.left_eye = (face.left_eye[0] + dx, face.left_eye[1] + dy)
            face.right_eye = (face.right_eye[0] + dx, face.right_eye[1] + dy)
            x0, y0, x1, y1 = face.bbox
            face.bbox = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)

    def _region_scan(self, bgr: np.ndarray) -> list[FaceData]:
        """Last-resort scan of overlapping regions for faces that are too
        small relative to the full frame (subject photographed from afar)."""
        h, w = bgr.shape[:2]
        if min(h, w) < 400:
            return []
        ov_x, ov_y = int(w * 0.12), int(h * 0.12)
        regions = [
            (0, 0, w // 2 + ov_x, h // 2 + ov_y),
            (w // 2 - ov_x, 0, w, h // 2 + ov_y),
            (0, h // 2 - ov_y, w // 2 + ov_x, h),
            (w // 2 - ov_x, h // 2 - ov_y, w, h),
            (w // 4, h // 4, 3 * w // 4, 3 * h // 4),
        ]
        found: list[FaceData] = []
        for x0, y0, x1, y1 in regions:
            tile = np.ascontiguousarray(bgr[y0:y1, x0:x1])
            tile_faces, _ = self._run_models(tile)
            self._shift_faces(tile_faces, x0, y0)
            for face in tile_faces:
                if any(_iou(face.bbox, other.bbox) > 0.3 for other in found):
                    continue
                face.notes.append("face found via region scan (small face)")
                found.append(face)
        return found

    def analyze(self, bgr: np.ndarray, try_rotations: bool = True) -> EngineResult:
        """Analyze an image; when no face is found, retry with a region scan
        (small faces) and at 90/270/180 degrees (portrait photos saved
        without EXIF orientation)."""
        with self._lock:
            faces, det_count = self._run_models(bgr)
            result = EngineResult(faces=faces, detector_count=det_count)
            if faces or not try_rotations:
                result.face_count = max(len(faces), det_count)
                return result

            scanned = self._region_scan(bgr)
            if scanned:
                return EngineResult(
                    faces=scanned,
                    detector_count=max(det_count, len(scanned)),
                    face_count=len(scanned),
                )

            for rotation, flag in (
                (90, cv2.ROTATE_90_CLOCKWISE),
                (270, cv2.ROTATE_90_COUNTERCLOCKWISE),
                (180, cv2.ROTATE_180),
            ):
                rotated = cv2.rotate(bgr, flag)
                faces, det_count = self._run_models(rotated)
                if faces:
                    get_logger().info(
                        "Face found after auto-rotating %d degrees", rotation
                    )
                    return EngineResult(
                        faces=faces,
                        detector_count=det_count,
                        face_count=max(len(faces), det_count),
                        auto_rotation=rotation,
                        image_bgr=rotated,
                    )
            result.face_count = max(len(result.faces), result.detector_count)
            return result


_engine: FaceEngine | None = None
_engine_lock = threading.Lock()


def get_face_engine() -> FaceEngine:
    """Process-wide cached engine so models load only once."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = FaceEngine()
        return _engine
