"""Flet desktop GUI: main screen, preview, batch progress, and dialogs.

All slow work (model loading, face analysis, batch processing, contact
sheets) runs on background threads; the UI thread only renders state.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import flet as ft

from app import APP_NAME, __version__
from app.review_ui import ReviewScreen
from app.settings import AppSettings, CropSettings, load_settings, save_settings
from processing.alignment import ManualAdjust  # noqa: F401 (re-export for review)
from processing.contact_sheet import generate_contact_sheets
from processing.detector import EngineInitError, get_face_engine
from processing.overlay import draw_debug_overlay
from processing.processor import (
    EXISTING_REPROCESS,
    EXISTING_SKIP,
    BatchProcessor,
    BatchProgress,
    load_and_analyze,
    render_from_analysis,
)
from utilities.image_utils import ImageLoadError, bgr_to_jpeg_base64
from utilities.logging_utils import get_logger
from utilities.paths import (
    REPORT_FILENAME,
    REVIEW_DIR_NAME,
    OutputSafetyError,
    derive_crop_root,
    enumerate_images,
    open_in_file_manager,
    resource_path,
)

_PREVIEW_DIM = 560


class CropperApp:
    """Main application controller."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.log = get_logger()
        self.settings: AppSettings = load_settings()
        self.source_dir: Optional[Path] = None
        self.crop_root: Optional[Path] = None
        self.image_count = 0

        self.samples: list[Path] = []
        self.sample_index = 0
        self._preview_cache: Optional[tuple] = None  # (path, bgr, EngineResult, rendered)
        self._preview_busy = False

        self.processor: Optional[BatchProcessor] = None
        self._sheet_cancel = threading.Event()

        self._configure_page()
        self._build_controls()
        self.show_main()

    # ------------------------------------------------------------------
    # page & layout
    # ------------------------------------------------------------------

    def _configure_page(self) -> None:
        page = self.page
        page.title = APP_NAME
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        page.theme_mode = ft.ThemeMode.LIGHT
        page.padding = 0
        if not page.web:
            try:
                page.window.width = self.settings.window_width
                page.window.height = self.settings.window_height
                page.window.min_width = 1080
                page.window.min_height = 700
                icon_path = resource_path("assets", "icon.ico")
                if icon_path.exists():
                    page.window.icon = str(icon_path)
            except Exception:  # window API varies per platform; never fatal
                self.log.debug("Window configuration not fully applied", exc_info=True)

    def _build_controls(self) -> None:
        # --- source ---------------------------------------------------
        self.source_field = ft.TextField(
            label="Source folder",
            hint_text=r"e.g. C:\Photos\Employee_IDs",
            expand=True,
            on_change=lambda e: self._on_source_changed(),
        )
        self.browse_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN, tooltip="Select Source Folder",
            on_click=self._browse_source,
        )
        self.output_field = ft.TextField(
            label="Output folder (created automatically)", read_only=True,
            value="", expand=True,
        )
        self.source_info = ft.Text("Select the folder that contains the portrait photos.",
                                   size=12, color=ft.Colors.GREY_700)

        self.dir_picker = ft.FilePicker(on_result=self._on_dir_picked)
        self.sample_picker = ft.FilePicker(on_result=self._on_samples_picked)
        self.page.overlay.extend([self.dir_picker, self.sample_picker])

        # --- settings ---------------------------------------------------
        def num_field(label: str, value: str, tooltip: str = "") -> ft.TextField:
            return ft.TextField(
                label=label, value=value, width=150, dense=True, tooltip=tooltip,
                on_change=lambda e: self._on_settings_changed(),
            )

        crop = self.settings.crop
        self.f_width = num_field("Output Width (px)", str(crop.output_width))
        self.f_height = num_field("Output Height (px)", str(crop.output_height))
        self.f_eye_x = num_field("Eye Center X (%)", f"{crop.eye_center_x_pct:g}",
                                 "Horizontal position of the eye midpoint")
        self.f_eye_y = num_field("Eye Center Y (%)", f"{crop.eye_center_y_pct:g}",
                                 "Vertical position of the eye midpoint")
        self.f_eye_dist = num_field("Target Eye Distance (%)", f"{crop.eye_distance_pct:g}",
                                    "Eye-to-eye distance as % of output width")
        self.f_quality = num_field("JPEG Quality", str(crop.jpeg_quality))

        # --- preview ----------------------------------------------------
        self.overlay_check = ft.Checkbox(
            label="Show Detection Overlay", value=False,
            on_change=lambda e: self._refresh_preview_images(),
        )
        self.preview_original = ft.Image(
            src_base64="", fit=ft.ImageFit.CONTAIN, visible=False,
            border_radius=6, height=430,
        )
        self.preview_cropped = ft.Image(
            src_base64="", fit=ft.ImageFit.CONTAIN, visible=False,
            border_radius=6, height=430,
        )
        self.preview_orig_placeholder = self._placeholder("Original photo")
        self.preview_crop_placeholder = self._placeholder("Processed preview")
        self.preview_status = ft.Text("No preview yet. Select a source folder, then press "
                                      "\"Auto Process Preview\".", size=13)
        self.preview_progress = ft.ProgressRing(width=18, height=18, stroke_width=2,
                                                visible=False)

        # --- batch ------------------------------------------------------
        self.start_button = ft.FilledButton(
            "Start Processing", icon=ft.Icons.PLAY_ARROW,
            on_click=lambda e: self._request_batch(None),
        )
        self.cancel_button = ft.OutlinedButton(
            "Cancel Processing", icon=ft.Icons.STOP, disabled=True,
            on_click=self._cancel_batch,
        )
        self.test10_button = ft.OutlinedButton(
            "Test First 10", on_click=lambda e: self._request_batch(10))
        self.test25_button = ft.OutlinedButton(
            "Test First 25", on_click=lambda e: self._request_batch(25))
        self.process_all_button = ft.OutlinedButton(
            "Process All", on_click=lambda e: self._request_batch(None))

        self.progress_bar = ft.ProgressBar(value=0.0)
        self.progress_current = ft.Text("", size=13, weight=ft.FontWeight.W_500)
        self.progress_counts = ft.Text("", size=13)
        self.batch_hint = ft.Text(
            "Originals are never modified. Processed copies are saved next to the "
            "source folder.", size=12, color=ft.Colors.GREY_700,
        )

    def _placeholder(self, label: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [ft.Icon(ft.Icons.IMAGE_OUTLINED, size=42, color=ft.Colors.GREY_400),
                 ft.Text(label, color=ft.Colors.GREY_500, size=12)],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=430, width=340, bgcolor=ft.Colors.GREY_100, border_radius=6,
            alignment=ft.alignment.center,
        )

    def _card(self, title: str, *controls: ft.Control) -> ft.Card:
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [ft.Text(title, weight=ft.FontWeight.BOLD, size=14), *controls],
                    spacing=10,
                ),
                padding=16,
            ),
        )

    def _main_view(self) -> ft.Control:
        left = ft.Column(
            [
                self._card(
                    "Source",
                    ft.Row([self.source_field, self.browse_button]),
                    self.output_field,
                    self.source_info,
                ),
                self._card(
                    "Output Settings",
                    ft.Row([self.f_width, self.f_height], wrap=True),
                    ft.Row([self.f_eye_x, self.f_eye_y], wrap=True),
                    ft.Row([self.f_eye_dist, self.f_quality], wrap=True),
                    ft.Row([
                        ft.TextButton("Restore defaults", icon=ft.Icons.RESTART_ALT,
                                      on_click=self._restore_defaults),
                    ]),
                ),
                self._card(
                    "Batch Processing",
                    ft.Row([self.start_button, self.cancel_button]),
                    ft.Row([self.test10_button, self.test25_button,
                            self.process_all_button], wrap=True),
                    self.progress_bar,
                    self.progress_current,
                    self.progress_counts,
                    self.batch_hint,
                ),
            ],
            width=430, spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        preview_buttons = ft.Row(
            [
                ft.OutlinedButton("Previous", icon=ft.Icons.CHEVRON_LEFT,
                                  on_click=lambda e: self._navigate_preview(-1)),
                ft.OutlinedButton("Next", icon=ft.Icons.CHEVRON_RIGHT,
                                  on_click=lambda e: self._navigate_preview(1)),
                ft.FilledTonalButton("Auto Process Preview", icon=ft.Icons.AUTO_FIX_HIGH,
                                     on_click=lambda e: self._process_preview()),
                ft.OutlinedButton("Reset", icon=ft.Icons.CLEAR,
                                  on_click=self._reset_preview),
                ft.TextButton("Choose sample photos...", icon=ft.Icons.PHOTO_LIBRARY,
                              on_click=self._choose_samples),
            ],
            wrap=True,
        )
        preview_row = ft.Row(
            [
                ft.Column([ft.Text("ORIGINAL", weight=ft.FontWeight.BOLD, size=12),
                           ft.Stack([self.preview_orig_placeholder, self.preview_original])],
                          expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Column([ft.Text("CROPPED", weight=ft.FontWeight.BOLD, size=12),
                           ft.Stack([self.preview_crop_placeholder, self.preview_cropped])],
                          expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ],
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        right = ft.Column(
            [
                self._card(
                    "Preview",
                    preview_buttons,
                    ft.Row([self.overlay_check, self.preview_progress]),
                    preview_row,
                    self.preview_status,
                ),
            ],
            expand=True, spacing=12, scroll=ft.ScrollMode.AUTO,
        )
        return ft.Container(
            content=ft.Row([left, right], expand=True,
                           vertical_alignment=ft.CrossAxisAlignment.START, spacing=14),
            padding=14, expand=True,
        )

    def show_main(self) -> None:
        self.page.appbar = ft.AppBar(
            leading=ft.Icon(ft.Icons.PORTRAIT),
            title=ft.Text(APP_NAME, weight=ft.FontWeight.BOLD),
            center_title=False,
            bgcolor=ft.Colors.INDIGO_50,
            actions=[
                ft.TextButton("Review Flagged Photos", icon=ft.Icons.FLAG,
                              on_click=lambda e: self.show_review()),
                ft.IconButton(ft.Icons.INFO_OUTLINE, tooltip="About",
                              on_click=self._show_about),
                ft.Container(width=8),
            ],
        )
        self.page.controls.clear()
        self.page.add(self._main_view())
        self.page.update()

    def show_review(self) -> None:
        if not self._require_source():
            return
        screen = ReviewScreen(
            page=self.page,
            settings=self.settings,
            source_dir=self.source_dir,
            crop_root=self.crop_root,
            on_back=self.show_main,
        )
        if not screen.items:
            self._info_dialog(
                "Manual Review",
                "There are no photos waiting for review in\n"
                f"{self.crop_root / REVIEW_DIR_NAME}",
            )
            return
        screen.show()

    # ------------------------------------------------------------------
    # source selection & settings
    # ------------------------------------------------------------------

    def _browse_source(self, e: ft.ControlEvent) -> None:
        if self.page.web:
            self._info_dialog(
                "Folder browser unavailable",
                "The native folder browser is available in the desktop app.\n"
                "Type or paste the source folder path into the text field instead.",
            )
            return
        self.dir_picker.get_directory_path(dialog_title="Select Source Folder")

    def _on_dir_picked(self, e: ft.FilePickerResultEvent) -> None:
        if e.path:
            self.source_field.value = e.path
            self._on_source_changed()

    def _on_source_changed(self) -> None:
        raw = (self.source_field.value or "").strip().strip('"')
        self.source_dir = None
        self.crop_root = None
        self.image_count = 0
        self.samples = []
        self.sample_index = 0
        self._preview_cache = None
        if raw:
            path = Path(raw)
            if path.is_dir():
                try:
                    crop_root = derive_crop_root(path)
                    images = enumerate_images(path)
                    self.source_dir = path.resolve()
                    self.crop_root = crop_root
                    self.image_count = len(images)
                    self.samples = images[:50]
                    self.output_field.value = str(crop_root)
                    self.source_info.value = (
                        f"{len(images)} supported image(s) found (JPG / JPEG / PNG). "
                        "Originals are never modified."
                    )
                    self.source_info.color = ft.Colors.GREEN_800
                except OutputSafetyError as exc:
                    self.output_field.value = ""
                    self.source_info.value = str(exc)
                    self.source_info.color = ft.Colors.RED_700
            else:
                self.output_field.value = ""
                self.source_info.value = "Folder not found. Check the path."
                self.source_info.color = ft.Colors.RED_700
        else:
            self.output_field.value = ""
            self.source_info.value = "Select the folder that contains the portrait photos."
            self.source_info.color = ft.Colors.GREY_700
        self.page.update()

    def _require_source(self) -> bool:
        if self.source_dir is None or self.crop_root is None:
            self._info_dialog("No source folder",
                              "Select a valid source folder first.")
            return False
        return True

    def _parse_settings(self) -> CropSettings:
        def as_float(field: ft.TextField, fallback: float) -> float:
            try:
                return float((field.value or "").replace(",", "."))
            except ValueError:
                return fallback

        defaults = CropSettings()
        crop = CropSettings(
            output_width=int(as_float(self.f_width, defaults.output_width)),
            output_height=int(as_float(self.f_height, defaults.output_height)),
            eye_center_x_pct=as_float(self.f_eye_x, defaults.eye_center_x_pct),
            eye_center_y_pct=as_float(self.f_eye_y, defaults.eye_center_y_pct),
            eye_distance_pct=as_float(self.f_eye_dist, defaults.eye_distance_pct),
            jpeg_quality=int(as_float(self.f_quality, defaults.jpeg_quality)),
        ).validated()
        self.settings.crop = crop
        return crop

    def _on_settings_changed(self) -> None:
        self._parse_settings()

    def _restore_defaults(self, e: ft.ControlEvent) -> None:
        crop = CropSettings()
        self.settings.crop = crop
        self.f_width.value = str(crop.output_width)
        self.f_height.value = str(crop.output_height)
        self.f_eye_x.value = f"{crop.eye_center_x_pct:g}"
        self.f_eye_y.value = f"{crop.eye_center_y_pct:g}"
        self.f_eye_dist.value = f"{crop.eye_distance_pct:g}"
        self.f_quality.value = str(crop.jpeg_quality)
        save_settings(self.settings)
        self.page.update()

    # ------------------------------------------------------------------
    # preview
    # ------------------------------------------------------------------

    def _choose_samples(self, e: ft.ControlEvent) -> None:
        if self.page.web:
            self._info_dialog(
                "File browser unavailable",
                "Choosing individual sample files requires the desktop app.\n"
                "Preview uses the images from the source folder instead.",
            )
            return
        self.sample_picker.pick_files(
            dialog_title="Choose sample photos",
            allow_multiple=True,
            allowed_extensions=["jpg", "jpeg", "png", "JPG", "JPEG", "PNG"],
        )

    def _on_samples_picked(self, e: ft.FilePickerResultEvent) -> None:
        if e.files:
            self.samples = [Path(f.path) for f in e.files if f.path]
            self.sample_index = 0
            self._process_preview()

    def _navigate_preview(self, step: int) -> None:
        if not self.samples:
            if not self._require_source():
                return
        if not self.samples:
            self._info_dialog("Preview", "No images found in the source folder.")
            return
        self.sample_index = (self.sample_index + step) % len(self.samples)
        self._process_preview()

    def _reset_preview(self, e: ft.ControlEvent) -> None:
        self._preview_cache = None
        self.sample_index = 0
        self.preview_original.visible = False
        self.preview_cropped.visible = False
        self.preview_orig_placeholder.visible = True
        self.preview_crop_placeholder.visible = True
        self.preview_status.value = ("Preview cleared. Press \"Auto Process Preview\" "
                                     "to process the current sample.")
        self.page.update()

    def _process_preview(self) -> None:
        if self._preview_busy:
            return
        if not self.samples:
            if not self._require_source():
                return
            self._info_dialog("Preview", "No images found in the source folder.")
            return
        path = self.samples[self.sample_index % len(self.samples)]
        self._preview_busy = True
        self.preview_progress.visible = True
        self.preview_status.value = f"Processing preview: {path.name} ..."
        self.page.update()
        self.page.run_thread(self._preview_worker, path)

    def _preview_worker(self, path: Path) -> None:
        crop = self._parse_settings()
        try:
            engine = get_face_engine()
            bgr, result = load_and_analyze(path, engine)
            rendered = None
            status_line: str
            if result.faces:
                rendered = render_from_analysis(bgr, result, crop, self.settings.quality)
                reasons = list(rendered.qa.review_reasons)
                would_be = "REVIEW" if reasons else "SUCCESS"
                detail = f" - {'; '.join(reasons)}" if reasons else ""
                status_line = f"{path.name}: would be {would_be}{detail}"
            else:
                status_line = (f"{path.name}: FAILED - no face detected"
                               if result.detector_count == 0
                               else f"{path.name}: FAILED - landmarks unavailable")
            self._preview_cache = (path, bgr, result, rendered)
            position = f"{(self.sample_index % len(self.samples)) + 1}/{len(self.samples)}"
            self.preview_status.value = f"[{position}] {status_line}"
        except (ImageLoadError, EngineInitError) as exc:
            self._preview_cache = None
            self.preview_status.value = f"{path.name}: {exc}"
            self.log.warning("Preview failed for %s: %s", path.name, exc)
        except Exception:
            self._preview_cache = None
            self.preview_status.value = (f"Could not process {path.name}. "
                                         "See processing.log for details.")
            self.log.exception("Preview failed for %s", path.name)
        finally:
            self._preview_busy = False
            self.preview_progress.visible = False
            self._refresh_preview_images()

    def _refresh_preview_images(self) -> None:
        cache = self._preview_cache
        if cache is None:
            self.page.update()
            return
        path, bgr, result, rendered = cache
        if self.overlay_check.value and result.faces:
            chosen = rendered.face_index if rendered else result.primary_face_index()
            display = draw_debug_overlay(bgr, result, chosen, max_dim=_PREVIEW_DIM * 2)
        else:
            display = bgr
        self.preview_original.src_base64 = bgr_to_jpeg_base64(display, _PREVIEW_DIM * 2)
        self.preview_original.visible = True
        self.preview_orig_placeholder.visible = False
        if rendered is not None:
            self.preview_cropped.src_base64 = bgr_to_jpeg_base64(
                rendered.output_bgr, _PREVIEW_DIM * 2)
            self.preview_cropped.visible = True
            self.preview_crop_placeholder.visible = False
        else:
            self.preview_cropped.visible = False
            self.preview_crop_placeholder.visible = True
        self.page.update()

    # ------------------------------------------------------------------
    # batch processing
    # ------------------------------------------------------------------

    def _request_batch(self, limit: Optional[int]) -> None:
        if self.processor is not None and self.processor.is_running():
            self._info_dialog("Processing", "A batch is already running.")
            return
        if not self._require_source():
            return
        if self.image_count == 0:
            self._info_dialog("Nothing to process",
                              "No supported images (JPG/JPEG/PNG) in the source folder.")
            return
        crop = self._parse_settings()
        save_settings(self.settings)

        existing_files = False
        if self.crop_root.exists():
            try:
                existing_files = any(self.crop_root.iterdir())
            except OSError:
                existing_files = False

        scope = f"first {limit} images" if limit else f"all {self.image_count} images"
        message = ft.Column(
            [
                ft.Text("Original images will remain unchanged.", weight=ft.FontWeight.BOLD),
                ft.Text("Processed copies will be saved to:"),
                ft.Text(str(self.crop_root), selectable=True,
                        color=ft.Colors.INDIGO_700, size=13),
                ft.Divider(),
                ft.Text(f"Scope: {scope}"),
                ft.Text(f"Output size: {crop.output_width} x {crop.output_height} px, "
                        f"JPEG quality {crop.jpeg_quality}"),
            ],
            tight=True, spacing=6,
        )
        mode_group = ft.RadioGroup(
            value=EXISTING_SKIP,
            content=ft.Column(
                [
                    ft.Radio(value=EXISTING_SKIP,
                             label="Continue / Skip Existing (keep files already processed)"),
                    ft.Radio(value=EXISTING_REPROCESS,
                             label="Reprocess Existing (overwrite previous output files)"),
                ],
                tight=True,
            ),
        )
        content_children: list[ft.Control] = [message]
        if existing_files:
            content_children += [
                ft.Divider(),
                ft.Text("The output folder already exists.", weight=ft.FontWeight.BOLD),
                mode_group,
            ]

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Start processing?"),
            content=ft.Container(ft.Column(content_children, tight=True, spacing=6,
                                           scroll=ft.ScrollMode.AUTO), width=520),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(dialog)),
                ft.FilledButton(
                    "Start",
                    on_click=lambda e: self._start_batch(dialog, limit, mode_group.value),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dialog)

    def _start_batch(self, dialog: ft.AlertDialog, limit: Optional[int],
                     existing_mode: str) -> None:
        self.page.close(dialog)
        self._set_batch_running(True)
        self.progress_bar.value = None  # indeterminate while models load
        self.progress_current.value = "Loading face detection models..."
        self.progress_counts.value = ""
        self.page.update()

        self.processor = BatchProcessor(
            source_dir=self.source_dir,
            settings=self.settings,
            limit=limit,
            existing_mode=existing_mode or EXISTING_SKIP,
            on_progress=self._on_batch_progress,
            on_finished=self._on_batch_finished,
        )
        self.processor.start()

    def _set_batch_running(self, running: bool) -> None:
        self.start_button.disabled = running
        self.test10_button.disabled = running
        self.test25_button.disabled = running
        self.process_all_button.disabled = running
        self.cancel_button.disabled = not running
        self.source_field.disabled = running
        self.browse_button.disabled = running

    def _cancel_batch(self, e: ft.ControlEvent) -> None:
        if self.processor is not None:
            self.processor.cancel()
            self.progress_current.value = "Cancelling after the current image..."
            self.page.update()

    def _on_batch_progress(self, progress: BatchProgress) -> None:
        stats = progress.stats
        if stats.total:
            self.progress_bar.value = stats.processed / stats.total
        if progress.current_name:
            self.progress_current.value = (
                f"Processing {progress.current_name}   "
                f"{progress.index} / {stats.total}"
            )
        pct = (stats.processed / stats.total * 100.0) if stats.total else 0.0
        self.progress_counts.value = (
            f"Processed {stats.processed}/{stats.total} ({pct:.0f}%)  |  "
            f"Successful: {stats.success}   Review: {stats.review}   "
            f"Failed: {stats.failed}   Skipped: {stats.skipped}"
        )
        try:
            self.page.update()
        except Exception:  # page may be closing
            pass

    def _on_batch_finished(self, processor: BatchProcessor) -> None:
        self._set_batch_running(False)
        stats = processor.stats
        self.progress_bar.value = (stats.processed / stats.total) if stats.total else 0.0
        if processor.error:
            self.progress_current.value = "Processing failed."
            self.page.update()
            self._info_dialog(
                "Processing failed",
                f"{processor.error}\n\nSee processing.log for technical details.",
            )
            return
        title = "Processing cancelled" if stats.cancelled else "Processing Complete"
        self.progress_current.value = title
        self.page.update()
        self._show_results_dialog(title, processor)

    def _show_results_dialog(self, title: str, processor: BatchProcessor) -> None:
        stats = processor.stats
        crop_root = processor.crop_root
        stats_rows = ft.Column(
            [
                ft.Text(f"Total: {stats.total}"),
                ft.Text(f"Success: {stats.success}", color=ft.Colors.GREEN_800),
                ft.Text(f"Review: {stats.review}", color=ft.Colors.ORANGE_800),
                ft.Text(f"Failed: {stats.failed}", color=ft.Colors.RED_700),
                ft.Text(f"Skipped: {stats.skipped}", color=ft.Colors.GREY_700),
            ],
            tight=True, spacing=4,
        )
        sheet_status = ft.Text("", size=12)

        def open_output(e):
            self._open_path(crop_root)

        def open_report(e):
            self._open_path(crop_root / REPORT_FILENAME)

        def open_review(e):
            self.page.close(dialog)
            self.show_review()

        def gen_sheets(e):
            sheet_status.value = "Generating contact sheets..."
            self.page.update()
            self.page.run_thread(self._contact_sheet_worker, crop_root, sheet_status)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Container(
                ft.Column([stats_rows, ft.Divider(),
                           ft.Text(f"Output folder:\n{crop_root}", selectable=True, size=12),
                           sheet_status],
                          tight=True, spacing=8),
                width=460,
            ),
            actions=[
                ft.TextButton("Open Output Folder", icon=ft.Icons.FOLDER_OPEN,
                              on_click=open_output),
                ft.TextButton("Review Flagged Photos", icon=ft.Icons.FLAG,
                              on_click=open_review),
                ft.TextButton("Generate Contact Sheet", icon=ft.Icons.GRID_VIEW,
                              on_click=gen_sheets),
                ft.TextButton("Open Processing Report", icon=ft.Icons.TABLE_VIEW,
                              on_click=open_report),
                ft.FilledButton("Close", on_click=lambda e: self.page.close(dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dialog)

    # ------------------------------------------------------------------
    # contact sheets / helpers
    # ------------------------------------------------------------------

    def _contact_sheet_worker(self, crop_root: Path, status_text: ft.Text) -> None:
        def tick(done: int, total: int) -> None:
            status_text.value = f"Contact sheets: {done}/{total} thumbnails..."
            if done % 10 == 0 or done == total:
                try:
                    self.page.update()
                except Exception:
                    pass

        try:
            self._sheet_cancel.clear()
            sheets = generate_contact_sheets(
                self.source_dir, crop_root, progress=tick,
                cancel_event=self._sheet_cancel,
            )
            status_text.value = f"Created {len(sheets)} contact sheet page(s)."
            self.page.update()
            if sheets:
                self._open_path(sheets[0].parent)
        except Exception:
            self.log.exception("Contact sheet generation failed")
            status_text.value = ("Contact sheet generation failed. "
                                 "See processing.log for details.")
            try:
                self.page.update()
            except Exception:
                pass

    def _open_path(self, path: Path) -> None:
        try:
            open_in_file_manager(path)
        except OSError:
            self.log.exception("Could not open %s", path)
            self._info_dialog("Open failed", f"Could not open:\n{path}")

    def _info_dialog(self, title: str, message: str) -> None:
        dialog = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Text(message, selectable=True),
            actions=[ft.TextButton("OK", on_click=lambda e: self.page.close(dialog))],
        )
        self.page.open(dialog)

    def _show_about(self, e: ft.ControlEvent) -> None:
        about = ft.AlertDialog(
            title=ft.Text(f"About {APP_NAME}"),
            content=ft.Container(
                ft.Column(
                    [
                        ft.Text(f"Application:  {APP_NAME}  v{__version__}"),
                        ft.Text("Purpose:  Automatically align and crop portrait "
                                "photographs for ID-card workflows."),
                        ft.Text("Processing:  Local / offline. No photos ever leave "
                                "this computer."),
                        ft.Text("Original files:  Never modified. All results are "
                                "written to a separate _crop folder."),
                        ft.Text("Privacy:  Facial landmarks are used only for "
                                "geometric alignment. No face recognition, no "
                                "identity matching, no biometric profiles."),
                    ],
                    tight=True, spacing=8,
                ),
                width=480,
            ),
            actions=[ft.TextButton("Close", on_click=lambda e: self.page.close(about))],
        )
        self.page.open(about)


def run_app(page: ft.Page) -> None:
    """Flet entry point."""
    CropperApp(page)
