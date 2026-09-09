"""Single-image pipeline and batch orchestration.

The exact same code path (:func:`render_from_analysis`) powers the GUI
preview, the manual-review screen, and batch processing, so what the user
previews is precisely what gets saved.

Source files are only ever opened for reading. Every write destination is
checked by :func:`utilities.paths.validate_output_path` first.
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from app import __version__
from app.settings import AppSettings, CropSettings, QualityConfig
from processing.alignment import AlignmentInfo, ManualAdjust
from processing.cropper import render_crop
from processing.detector import EngineResult, FaceEngine, get_face_engine
from processing.landmarks import FaceData
from processing.quality import QualityAssessment, assess
from utilities.image_utils import ImageLoadError, load_image_bgr, save_image
from utilities.logging_utils import attach_run_log, detach_run_log, get_logger
from utilities.paths import (
    FAILED_DIR_NAME,
    REPORT_FILENAME,
    REVIEW_DIR_NAME,
    derive_crop_root,
    enumerate_images,
    validate_output_path,
)
from utilities.report import ReportBook

STATUS_SUCCESS = "SUCCESS"
STATUS_REVIEW = "REVIEW"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"


@dataclass
class ProcessOutcome:
    """Everything recorded about one image (one CSV row)."""

    filename: str
    source_path: Path
    status: str = STATUS_FAILED
    output_path: Optional[Path] = None
    face_count: int = 0
    rotation_degrees: float = 0.0
    eye_distance_pixels: float = 0.0
    eye_distance_ratio: float = 0.0
    blur_score: float = 0.0
    detection_confidence: float = 0.0
    processing_time: float = 0.0
    review_reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def reason_text(self) -> str:
        return "; ".join([*self.review_reasons, *self.notes])

    def to_report_row(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "source_path": str(self.source_path),
            "output_path": str(self.output_path) if self.output_path else "",
            "status": self.status,
            "face_count": self.face_count,
            "rotation_degrees": f"{self.rotation_degrees:.2f}",
            "eye_distance_pixels": f"{self.eye_distance_pixels:.1f}",
            "eye_distance_ratio": f"{self.eye_distance_ratio:.4f}",
            "blur_score": f"{self.blur_score:.1f}",
            "detection_confidence": f"{self.detection_confidence:.3f}",
            "processing_time": f"{self.processing_time:.3f}",
            "reason": self.reason_text,
        }


@dataclass
class RenderedFace:
    output_bgr: np.ndarray
    face: FaceData
    face_index: int
    alignment: AlignmentInfo
    matrix: np.ndarray
    qa: QualityAssessment


def load_and_analyze(
    source_path: Path, engine: FaceEngine
) -> tuple[np.ndarray, EngineResult]:
    """Read one image (EXIF-corrected, in memory) and run face analysis.

    Returns the working BGR image (already rotated when the engine had to
    auto-rotate to find a face) and the engine result.
    """
    bgr = load_image_bgr(Path(source_path))
    result = engine.analyze(bgr)
    if result.auto_rotation and result.image_bgr is not None:
        bgr = result.image_bgr
    return bgr, result


def render_from_analysis(
    bgr: np.ndarray,
    result: EngineResult,
    crop: CropSettings,
    quality_cfg: QualityConfig,
    face_index: Optional[int] = None,
    adjust: Optional[ManualAdjust] = None,
) -> RenderedFace:
    """Render the standardized crop for one detected face and QA it."""
    if not result.faces:
        raise ValueError("No landmarked faces available to render")
    idx = result.primary_face_index() if face_index is None else int(face_index)
    idx = max(0, min(idx, len(result.faces) - 1))
    face = result.faces[idx]
    output, info, matrix = render_crop(bgr, face, crop, adjust)
    qa = assess(
        face=face,
        matrix=matrix,
        output_bgr=output,
        source_shape=bgr.shape[:2],
        crop=crop,
        cfg=quality_cfg,
        face_count=result.face_count,
        scale=float(np.hypot(matrix[0, 0], matrix[1, 0])),
    )
    return RenderedFace(
        output_bgr=output, face=face, face_index=idx,
        alignment=info, matrix=matrix, qa=qa,
    )


def process_single(
    source_path: Path,
    crop: CropSettings,
    quality_cfg: QualityConfig,
    engine: FaceEngine,
    face_index: Optional[int] = None,
    adjust: Optional[ManualAdjust] = None,
) -> tuple[ProcessOutcome, Optional[RenderedFace]]:
    """Run the full pipeline for one image, without writing anything."""
    source_path = Path(source_path)
    outcome = ProcessOutcome(filename=source_path.name, source_path=source_path)
    started = time.perf_counter()
    try:
        bgr, result = load_and_analyze(source_path, engine)
    except ImageLoadError as exc:
        outcome.status = STATUS_FAILED
        outcome.notes.append(f"cannot open image: {exc}")
        outcome.processing_time = time.perf_counter() - started
        return outcome, None

    outcome.face_count = result.face_count
    if not result.faces:
        outcome.status = STATUS_FAILED
        if result.detector_count > 0:
            outcome.notes.append("face detected but landmarks unavailable")
        else:
            outcome.notes.append("no face detected")
        outcome.processing_time = time.perf_counter() - started
        return outcome, None

    rendered = render_from_analysis(bgr, result, crop, quality_cfg, face_index, adjust)
    outcome.rotation_degrees = rendered.alignment.angle_deg
    outcome.eye_distance_pixels = rendered.alignment.eye_distance_px
    src_w = bgr.shape[1]
    outcome.eye_distance_ratio = (
        rendered.alignment.eye_distance_px / src_w if src_w else 0.0
    )
    outcome.blur_score = rendered.qa.blur_score
    outcome.detection_confidence = rendered.face.confidence
    outcome.review_reasons = list(rendered.qa.review_reasons)

    if result.auto_rotation in (90, 270):
        outcome.notes.append(
            f"auto-rotated {result.auto_rotation} deg (missing EXIF orientation)"
        )
    elif result.auto_rotation == 180:
        outcome.review_reasons.append("image appeared upside down (auto-rotated 180 deg)")

    outcome.status = STATUS_REVIEW if outcome.review_reasons else STATUS_SUCCESS
    outcome.processing_time = time.perf_counter() - started
    return outcome, rendered


# ----------------------------------------------------------------------------


@dataclass
class BatchStats:
    total: int = 0
    processed: int = 0
    success: int = 0
    review: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False

    def register(self, status: str) -> None:
        self.processed += 1
        if status == STATUS_SUCCESS:
            self.success += 1
        elif status == STATUS_REVIEW:
            self.review += 1
        elif status == STATUS_FAILED:
            self.failed += 1
        elif status == STATUS_SKIPPED:
            self.skipped += 1


@dataclass
class BatchProgress:
    stats: BatchStats
    current_name: str = ""
    index: int = 0  # 1-based position within the run
    done: bool = False


EXISTING_SKIP = "skip"
EXISTING_REPROCESS = "reprocess"


class BatchProcessor:
    """Processes a whole source folder on a worker thread."""

    def __init__(
        self,
        source_dir: Path,
        settings: AppSettings,
        limit: Optional[int] = None,
        existing_mode: str = EXISTING_SKIP,
        on_progress: Optional[Callable[[BatchProgress], None]] = None,
        on_finished: Optional[Callable[["BatchProcessor"], None]] = None,
    ):
        self.source_dir = Path(source_dir).resolve()
        self.crop_root = derive_crop_root(self.source_dir)
        self.settings = settings
        self.limit = limit
        self.existing_mode = existing_mode
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.stats = BatchStats()
        self.outcomes: list[ProcessOutcome] = []
        self.error: Optional[str] = None
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="batch-processor", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- helpers ------------------------------------------------------------

    def _emit(self, current: str = "", index: int = 0, done: bool = False) -> None:
        if self.on_progress:
            self.on_progress(BatchProgress(stats=self.stats, current_name=current,
                                           index=index, done=done))

    def _existing_output(self, name: str) -> Optional[Path]:
        for candidate in (self.crop_root / name, self.crop_root / REVIEW_DIR_NAME / name):
            if candidate.exists():
                return candidate
        return None

    def _save_output(self, rendered: RenderedFace, outcome: ProcessOutcome) -> None:
        sub = REVIEW_DIR_NAME if outcome.status == STATUS_REVIEW else ""
        dest_dir = self.crop_root / sub if sub else self.crop_root
        destination = dest_dir / outcome.filename
        validate_output_path(self.source_dir, self.crop_root, destination)
        save_image(rendered.output_bgr, destination, self.settings.crop.jpeg_quality)
        outcome.output_path = destination
        # When a previously reviewed/successful copy exists in the *other*
        # location from an earlier run, remove it so there is exactly one
        # current result per source image (originals are never touched).
        other = (
            self.crop_root / outcome.filename
            if sub
            else self.crop_root / REVIEW_DIR_NAME / outcome.filename
        )
        if other.exists() and other != destination:
            try:
                validate_output_path(self.source_dir, self.crop_root, other)
                other.unlink()
            except OSError:
                get_logger().warning("Could not remove stale output %s", other)

    def _copy_failed_original(self, source: Path) -> None:
        if not self.settings.quality.copy_failed_originals:
            return
        destination = self.crop_root / FAILED_DIR_NAME / source.name
        try:
            validate_output_path(self.source_dir, self.crop_root, destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)  # read-only on the source
        except OSError:
            get_logger().exception("Could not copy failed original %s", source.name)

    # -- main loop ----------------------------------------------------------

    def run(self) -> None:
        logger = get_logger()
        run_handler = None
        report: Optional[ReportBook] = None
        try:
            images = enumerate_images(self.source_dir)
            if self.limit is not None:
                images = images[: self.limit]
            self.stats.total = len(images)

            self.crop_root.mkdir(parents=True, exist_ok=True)
            (self.crop_root / REVIEW_DIR_NAME).mkdir(exist_ok=True)
            (self.crop_root / FAILED_DIR_NAME).mkdir(exist_ok=True)
            run_handler = attach_run_log(self.crop_root)
            logger.info("=" * 60)
            logger.info("ID Photo Auto Cropper v%s - batch started", __version__)
            logger.info("Source folder: %s", self.source_dir)
            logger.info("Output folder: %s", self.crop_root)
            logger.info(
                "Images: %d | limit: %s | existing outputs: %s",
                len(images), self.limit, self.existing_mode,
            )
            logger.info("Crop settings: %s", self.settings.crop)

            report = ReportBook(self.crop_root / REPORT_FILENAME)
            engine = get_face_engine()
            self._emit()

            for position, path in enumerate(images, start=1):
                if self._cancel.is_set():
                    self.stats.cancelled = True
                    logger.warning("Batch cancelled by user at %d/%d", position - 1, len(images))
                    break
                self._emit(current=path.name, index=position)

                existing = (
                    self._existing_output(path.name)
                    if self.existing_mode == EXISTING_SKIP
                    else None
                )
                if existing is not None:
                    outcome = ProcessOutcome(
                        filename=path.name, source_path=path, status=STATUS_SKIPPED,
                        output_path=existing,
                    )
                    outcome.notes.append("output already exists (kept previous result)")
                    self.stats.register(STATUS_SKIPPED)
                    self.outcomes.append(outcome)
                    if not report.has_row(path.name):
                        report.set_row(outcome.to_report_row())
                    self._emit(current=path.name, index=position)
                    continue

                try:
                    outcome, rendered = process_single(
                        path, self.settings.crop, self.settings.quality, engine
                    )
                    if rendered is not None:
                        self._save_output(rendered, outcome)
                    elif outcome.status == STATUS_FAILED:
                        self._copy_failed_original(path)
                except Exception as exc:  # noqa: BLE001 - single image must not kill the batch
                    logger.exception("Unexpected error while processing %s", path.name)
                    outcome = ProcessOutcome(
                        filename=path.name, source_path=path, status=STATUS_FAILED
                    )
                    outcome.notes.append(f"processing error: {exc}")

                self.stats.register(outcome.status)
                self.outcomes.append(outcome)
                report.set_row(outcome.to_report_row())
                if position % 25 == 0:
                    report.save()
                logger.info(
                    "[%d/%d] %s -> %s%s",
                    position, len(images), path.name, outcome.status,
                    f" ({outcome.reason_text})" if outcome.reason_text else "",
                )
                self._emit(current=path.name, index=position)

            logger.info(
                "Batch finished: %d processed | %d success | %d review | %d failed | %d skipped%s",
                self.stats.processed, self.stats.success, self.stats.review,
                self.stats.failed, self.stats.skipped,
                " | CANCELLED" if self.stats.cancelled else "",
            )
        except Exception as exc:  # noqa: BLE001 - fatal batch error
            self.error = str(exc)
            get_logger().exception("Batch aborted: %s", exc)
        finally:
            if report is not None:
                try:
                    report.save()
                except OSError:
                    get_logger().exception("Could not save processing report")
            detach_run_log(run_handler)
            self._emit(done=True)
            if self.on_finished:
                self.on_finished(self)
