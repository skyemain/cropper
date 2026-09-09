"""ID Photo Auto Cropper - application entry point.

Usage:
    python main.py                     desktop GUI (default)
    python main.py --web --port 8619   serve the GUI to a web browser
    python main.py --process SRC       headless batch processing (no GUI)
    python main.py --selftest          verify models/pipeline, then exit

Runs both from a normal Python environment and from a PyInstaller frozen
executable; bundled resources are resolved via utilities.paths.resource_path.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys

# In a windowed (no-console) frozen build, sys.stdout/stderr are None; give
# libraries that print a harmless sink so they cannot crash the app.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from app import APP_NAME, __version__
from utilities.logging_utils import get_logger, setup_logging
from utilities.paths import resource_path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME, description=__doc__)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--web", action="store_true",
                        help="serve the GUI over HTTP instead of a desktop window")
    parser.add_argument("--host", default="127.0.0.1", help="host for --web mode")
    parser.add_argument("--port", type=int, default=8619, help="port for --web mode")
    parser.add_argument("--process", metavar="SOURCE_DIR",
                        help="process a folder headlessly and exit")
    parser.add_argument("--limit", type=int, default=None,
                        help="with --process: only handle the first N images")
    parser.add_argument("--existing", choices=["skip", "reprocess"], default="skip",
                        help="with --process: how to treat existing output files")
    parser.add_argument("--contact-sheets", action="store_true",
                        help="with --process: also generate contact sheets")
    parser.add_argument("--selftest", action="store_true",
                        help="initialize models, process the bundled sample, exit")
    parser.add_argument("--verbose", action="store_true", help="verbose console logging")
    return parser.parse_args(argv)


def _run_selftest() -> int:
    """Exercise the full pipeline once. Used to validate frozen builds."""
    import cv2
    import mediapipe  # noqa: F401  (import check)
    import numpy

    import flet
    from app.settings import AppSettings
    from processing.detector import get_face_engine
    from processing.processor import STATUS_FAILED, process_single

    log = get_logger()
    log.info("Selftest: python=%s frozen=%s", sys.version.split()[0],
             getattr(sys, "frozen", False))
    log.info("Selftest: numpy=%s opencv=%s flet=%s", numpy.__version__,
             cv2.__version__, getattr(flet, "version", None) or "n/a")

    sample = resource_path("assets", "selftest_portrait.jpg")
    if not sample.exists():
        print(f"SELFTEST FAILED: missing bundled sample {sample}")
        return 1
    try:
        engine = get_face_engine()
    except Exception as exc:  # noqa: BLE001
        print(f"SELFTEST FAILED: engine init: {exc}")
        return 1
    settings = AppSettings()
    outcome, rendered = process_single(
        sample, settings.crop, settings.quality, engine)
    if outcome.status == STATUS_FAILED or rendered is None:
        print(f"SELFTEST FAILED: {outcome.status} {outcome.reason_text}")
        return 1
    h, w = rendered.output_bgr.shape[:2]
    if (w, h) != (settings.crop.output_width, settings.crop.output_height):
        print(f"SELFTEST FAILED: unexpected output size {w}x{h}")
        return 1
    print(f"SELFTEST OK: status={outcome.status} output={w}x{h} "
          f"faces={outcome.face_count} eyes={outcome.eye_distance_pixels:.1f}px")
    return 0


def _run_headless_batch(args: argparse.Namespace) -> int:
    from pathlib import Path

    from app.settings import load_settings
    from processing.contact_sheet import generate_contact_sheets
    from processing.processor import BatchProcessor

    source = Path(args.process).expanduser()
    if not source.is_dir():
        print(f"ERROR: source folder not found: {source}")
        return 2
    settings = load_settings()

    def on_progress(progress) -> None:
        if progress.current_name:
            stats = progress.stats
            print(f"[{progress.index}/{stats.total}] {progress.current_name}  "
                  f"ok={stats.success} review={stats.review} "
                  f"failed={stats.failed} skipped={stats.skipped}",
                  flush=True)

    processor = BatchProcessor(
        source_dir=source, settings=settings, limit=args.limit,
        existing_mode=args.existing, on_progress=on_progress,
    )
    processor.run()  # synchronous in CLI mode
    stats = processor.stats
    print(f"\nProcessing {'cancelled' if stats.cancelled else 'complete'}.")
    print(f"  Total:   {stats.total}")
    print(f"  Success: {stats.success}")
    print(f"  Review:  {stats.review}")
    print(f"  Failed:  {stats.failed}")
    print(f"  Skipped: {stats.skipped}")
    print(f"  Output:  {processor.crop_root}")
    if processor.error:
        print(f"ERROR: {processor.error}")
        return 1
    if args.contact_sheets:
        sheets = generate_contact_sheets(source, processor.crop_root)
        print(f"  Contact sheets: {len(sheets)} page(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    setup_logging(verbose=args.verbose)
    log = get_logger()
    log.info("%s v%s starting (frozen=%s)", APP_NAME, __version__,
             getattr(sys, "frozen", False))

    if args.selftest:
        return _run_selftest()
    if args.process:
        return _run_headless_batch(args)

    import flet as ft

    from app.gui import run_app

    if args.web:
        log.info("Serving GUI at http://%s:%d", args.host, args.port)
        ft.app(run_app, view=None, host=args.host, port=args.port,
               assets_dir=str(resource_path("assets")))
    else:
        ft.app(run_app, assets_dir=str(resource_path("assets")))
    return 0


if __name__ == "__main__":
    # Required for PyInstaller on Windows: without this, libraries that spawn
    # helper processes would re-launch the GUI in an endless loop.
    multiprocessing.freeze_support()
    sys.exit(main())
