"""Path handling and write-safety rules.

Every file written by this application must pass through
:func:`validate_output_path`, which guarantees that nothing is ever written
into (or over) the user's source folder.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CROP_SUFFIX = "_crop"
REVIEW_DIR_NAME = "REVIEW"
FAILED_DIR_NAME = "FAILED"
CONTACT_SHEET_DIR_NAME = "CONTACT_SHEETS"
REPORT_FILENAME = "processing_report.csv"
LOG_FILENAME = "processing.log"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class OutputSafetyError(Exception):
    """Raised when a write destination violates the output-safety rules."""


def is_inside(child: Path, parent: Path) -> bool:
    """True if *child* is *parent* or located anywhere below it (resolved)."""
    child_r = child.resolve()
    parent_r = parent.resolve()
    return child_r == parent_r or child_r.is_relative_to(parent_r)


def derive_crop_root(source_dir: Path) -> Path:
    """Return the sibling output folder ``<source>_crop``.

    The output folder is always created NEXT TO the source folder, never
    inside it, e.g. ``C:\\Photos\\Employee_IDs`` -> ``C:\\Photos\\Employee_IDs_crop``.
    """
    source_dir = Path(source_dir).resolve()
    if source_dir.parent == source_dir:
        # Filesystem root (e.g. "C:\\" or "/") has no name to suffix and no
        # sibling location; refuse rather than guess.
        raise OutputSafetyError(
            "The source folder cannot be a drive or filesystem root. "
            "Choose a normal folder that contains the photos."
        )
    return source_dir.parent / (source_dir.name + CROP_SUFFIX)


def validate_output_path(source_root: Path, crop_root: Path, destination: Path) -> Path:
    """Validate that *destination* is a safe place to write a file.

    Rules enforced (all on resolved absolute paths):
      * the crop root is not the source root and not inside it,
      * the destination is inside the crop root,
      * the destination is not inside the source root.

    Returns the resolved destination. Raises :class:`OutputSafetyError` when
    any rule is violated.
    """
    source_r = Path(source_root).resolve()
    crop_r = Path(crop_root).resolve()
    dest_r = Path(destination).resolve()

    if is_inside(crop_r, source_r):
        raise OutputSafetyError(
            f"Output folder {crop_r} resolves inside the source folder {source_r}."
        )
    if not is_inside(dest_r, crop_r):
        raise OutputSafetyError(
            f"Write destination {dest_r} is outside the output folder {crop_r}."
        )
    if is_inside(dest_r, source_r):
        raise OutputSafetyError(
            f"Write destination {dest_r} resolves inside the source folder {source_r}."
        )
    if dest_r.name in ("", ".", ".."):
        raise OutputSafetyError(f"Write destination {dest_r} has no valid filename.")
    return dest_r


def enumerate_images(source_dir: Path) -> list[Path]:
    """List supported images in the top level of *source_dir*, sorted by name.

    Only reads directory entries; never touches file contents. Hidden files
    and subdirectories are ignored.
    """
    source_dir = Path(source_dir)
    images: list[Path] = []
    for entry in source_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() in SUPPORTED_EXTENSIONS:
            images.append(entry)
    images.sort(key=lambda p: p.name.lower())
    return images


def project_root() -> Path:
    """Root folder for bundled resources, both in dev and frozen builds."""
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def resource_path(*relative: str) -> Path:
    """Absolute path of a bundled resource (assets, models, ...).

    Works in the development environment and inside a PyInstaller/Flet
    frozen executable; never relies on the current working directory.
    """
    return project_root().joinpath(*relative)


def open_in_file_manager(path: Path) -> None:
    """Open a folder or file with the platform's default handler."""
    path = Path(path)
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - intended behaviour
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
