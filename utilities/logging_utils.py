"""Application and per-run logging.

Two log destinations are used:
  * ``app.log`` in the per-user config folder - application lifecycle,
    including everything that happens before an output folder exists.
  * ``processing.log`` inside each ``<source>_crop`` folder - a per-run log
    of the batch that produced that output.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

APP_LOGGER_NAME = "idphoto"

_FORMAT = "%(asctime)s  %(levelname)-8s %(name)s: %(message)s"


def get_config_dir() -> Path:
    """Per-user writable folder for settings and the application log."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        cfg = Path(base) / "IDPhotoAutoCropper"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        cfg = Path(base) / "id-photo-auto-cropper"
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg


def get_logger() -> logging.Logger:
    return logging.getLogger(APP_LOGGER_NAME)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure the application logger once; safe to call repeatedly."""
    logger = get_logger()
    if getattr(logger, "_idphoto_configured", False):
        return logger
    logger.setLevel(logging.DEBUG)

    stream = logging.StreamHandler()
    stream.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(stream)

    try:
        file_handler = logging.FileHandler(get_config_dir() / "app.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("Could not open app.log in the config folder; continuing without it.")

    logger._idphoto_configured = True  # type: ignore[attr-defined]
    return logger


def attach_run_log(crop_root: Path) -> logging.Handler | None:
    """Add a ``processing.log`` handler inside the output folder.

    Returns the handler so the caller can detach it when the run finishes.
    """
    logger = get_logger()
    try:
        handler = logging.FileHandler(Path(crop_root) / "processing.log", encoding="utf-8")
    except OSError:
        logger.exception("Could not create processing.log in %s", crop_root)
        return None
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    return handler


def detach_run_log(handler: logging.Handler | None) -> None:
    if handler is None:
        return
    logger = get_logger()
    logger.removeHandler(handler)
    handler.close()
