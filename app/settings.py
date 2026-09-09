"""Application settings: crop geometry, quality thresholds, persistence.

Crop settings are user-facing (editable in the GUI). Quality thresholds are
intentionally kept internal but easy to tune: they live in the same JSON
settings file and can be edited there without code changes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from utilities.logging_utils import get_config_dir, get_logger

SETTINGS_FILENAME = "settings.json"


@dataclass
class CropSettings:
    """Output geometry. Defaults produce a 600x800 (3:4) ID portrait."""

    output_width: int = 600
    output_height: int = 800
    eye_center_x_pct: float = 50.0  # eye midpoint X as % of output width
    eye_center_y_pct: float = 40.0  # eye midpoint Y as % of output height
    eye_distance_pct: float = 34.0  # eye-to-eye distance as % of output width
    jpeg_quality: int = 95

    def validated(self) -> "CropSettings":
        """Clamp values into safe ranges (no exceptions for GUI typos)."""
        return CropSettings(
            output_width=int(min(4000, max(100, self.output_width))),
            output_height=int(min(4000, max(100, self.output_height))),
            eye_center_x_pct=float(min(80.0, max(20.0, self.eye_center_x_pct))),
            eye_center_y_pct=float(min(75.0, max(15.0, self.eye_center_y_pct))),
            eye_distance_pct=float(min(80.0, max(10.0, self.eye_distance_pct))),
            jpeg_quality=int(min(100, max(60, self.jpeg_quality))),
        )


@dataclass
class QualityConfig:
    """QA thresholds that decide when an image is flagged for REVIEW."""

    blur_review_threshold: float = 28.0  # variance of Laplacian on the crop
    max_abs_yaw_deg: float = 20.0
    max_abs_pitch_deg: float = 20.0
    max_abs_roll_deg: float = 25.0
    min_detection_confidence: float = 0.60
    min_eye_distance_ratio: float = 0.04  # eye distance / source image width
    max_upscale_factor: float = 1.5  # source->output scale above this = low res
    headroom_min_pct: float = 1.0  # estimated head top must be below this line
    headroom_max_pct: float = 30.0
    chin_max_pct: float = 97.0
    face_border_margin_pct: float = 1.0  # face landmarks near source edge
    crop_overrun_pct: float = 1.5  # crop window may exceed the photo by this %
    copy_failed_originals: bool = True


@dataclass
class AppSettings:
    crop: CropSettings = field(default_factory=CropSettings)
    quality: QualityConfig = field(default_factory=QualityConfig)
    window_width: int = 1280
    window_height: int = 860

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _dataclass_from_dict(cls, data: dict):
    known = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in data.items() if k in known}
    return cls(**kwargs)


def settings_path() -> Path:
    return get_config_dir() / SETTINGS_FILENAME


def load_settings() -> AppSettings:
    path = settings_path()
    if not path.exists():
        return AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        settings = AppSettings(
            crop=_dataclass_from_dict(CropSettings, raw.get("crop", {})).validated(),
            quality=_dataclass_from_dict(QualityConfig, raw.get("quality", {})),
            window_width=int(raw.get("window_width", 1280)),
            window_height=int(raw.get("window_height", 860)),
        )
        return settings
    except (json.JSONDecodeError, TypeError, ValueError, OSError):
        get_logger().warning("Settings file was unreadable; using defaults.")
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    try:
        path = settings_path()
        path.write_text(settings.to_json(), encoding="utf-8")
    except OSError:
        get_logger().exception("Could not save settings")
