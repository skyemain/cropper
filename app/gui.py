"""Flet desktop GUI: main screen, preview, batch progress, and dialogs.

Visual design: dark, modern surface system (deep-navy background, soft card
borders, indigo->violet accent gradient, Inter typeface bundled offline).
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
from app.theme import (
    ACCENT,
    ACCENT_2,
    AMBER,
    BG,
    BORDER,
    GREEN,
    GREY,
    MUTED,
    RED,
    SURFACE,
    SURFACE_2,
    TXT,
    body,
    button_style,
    card,
    header_bar,
    heading,
    stat_chip,
    style_field,
)
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

FRAMING_PRESETS = {"wide": 28.0, "standard": 34.0, "close": 40.0}


def _framing_word(value: float) -> str:
    if value <= 30.5:
        return "Wide"
    if value <= 37.0:
        return "Standard"
    return "Close-up"


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
        self._preview_seq = 0  # bumps the Image keys to force repaints

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
        page.fonts = {
            "Inter": "/fonts/Inter-Regular.ttf",
            "Inter-SemiBold": "/fonts/Inter-SemiBold.ttf",
            "Inter-Bold": "/fonts/Inter-Bold.ttf",
        }
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(color_scheme_seed=ACCENT, font_family="Inter",
                              use_material3=True)
        page.dark_theme = page.theme
        page.bgcolor = BG
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
        self.source_field = style_field(ft.TextField(
            label="Source folder",
            hint_text=r"e.g. C:\Photos\Employee_IDs",
            expand=True,
            on_change=lambda e: self._on_source_changed(),
        ))
        self.browse_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN_ROUNDED, tooltip="Select Source Folder",
            icon_color=ACCENT, on_click=self._browse_source,
        )
        self.output_field = style_field(ft.TextField(
            label="Output folder (created automatically)", read_only=True,
            value="", expand=True,
        ))
        self.source_info = body("Select the folder that contains the portrait photos.",
                                color=MUTED, size=12)

        self.dir_picker = ft.FilePicker(on_result=self._on_dir_picked)
        self.sample_picker = ft.FilePicker(on_result=self._on_samples_picked)
        self.page.overlay.extend([self.dir_picker, self.sample_picker])

        # --- settings ---------------------------------------------------
        def num_field(label: str, value: str, tooltip: str = "") -> ft.TextField:
            return style_field(ft.TextField(
                label=label, value=value, width=158, dense=True, tooltip=tooltip,
                on_change=lambda e: self._on_settings_changed(),
            ))

        crop = self.settings.crop
        self.f_width = num_field("Output Width (px)", str(crop.output_width))
        self.f_height = num_field("Output Height (px)", str(crop.output_height))
        self.f_eye_x = num_field("Eye Center X (%)", f"{crop.eye_center_x_pct:g}",
                                 "Horizontal position of the eye midpoint")
        self.f_eye_y = num_field("Eye Center Y (%)", f"{crop.eye_center_y_pct:g}",
                                 "Vertical position of the eye midpoint")
        self.f_eye_dist = num_field("Target Eye Distance (%)", f"{crop.eye_distance_pct:g}",
                                    "Eye-to-eye distance as % of output width - "
                                    "same control as the Framing slider")
        self.f_quality = num_field("JPEG Quality", str(crop.jpeg_quality))

        # --- framing (zoom) ------------------------------------------------
        self.framing_value_text = heading(
            f"{crop.eye_distance_pct:.0f}%  ·  {_framing_word(crop.eye_distance_pct)}",
            size=13, color=ACCENT)
        self.framing_slider = ft.Slider(
            min=24, max=46, divisions=22, value=crop.eye_distance_pct,
            active_color=ACCENT, inactive_color=SURFACE_2, expand=True,
            label="{value}%",
            on_change=lambda e: self._on_framing_slide(commit=False),
            on_change_end=lambda e: self._on_framing_slide(commit=True),
        )
        self.framing_presets = ft.SegmentedButton(
            on_change=self._on_framing_preset,
            selected={"standard"},
            allow_multiple_selection=False,
            allow_empty_selection=True,
            segments=[
                ft.Segment(value="wide", label=ft.Text("Wide")),
                ft.Segment(value="standard", label=ft.Text("Standard")),
                ft.Segment(value="close", label=ft.Text("Close-up")),
            ],
        )
        self._sync_framing_preset_selection()

        # --- preview ----------------------------------------------------
        self.overlay_check = ft.Checkbox(
            label="Show Detection Overlay", value=False,
            active_color=ACCENT, label_style=ft.TextStyle(color=TXT, size=13),
            on_change=lambda e: self._refresh_preview_images(),
        )
        self.preview_original = ft.Image(
            src_base64="", fit=ft.ImageFit.CONTAIN, visible=False,
            border_radius=12, height=414,
        )
        self.preview_cropped = ft.Image(
            src_base64="", fit=ft.ImageFit.CONTAIN, visible=False,
            border_radius=12, height=414,
        )
        self.preview_orig_placeholder = self._placeholder("Original photo")
        self.preview_crop_placeholder = self._placeholder("Processed preview")
        self.preview_status = body(
            "No preview yet. Select a source folder, then press \"Auto Process Preview\".",
            size=12.5, color=MUTED)
        self.preview_progress = ft.ProgressRing(width=16, height=16, stroke_width=2,
                                                color=ACCENT, visible=False)

        # --- batch ------------------------------------------------------
        self.start_button = ft.FilledButton(
            "Start Processing", icon=ft.Icons.PLAY_ARROW_ROUNDED,
            style=button_style(primary=True),
            on_click=lambda e: self._request_batch(None),
        )
        self.cancel_button = ft.OutlinedButton(
            "Cancel", icon=ft.Icons.STOP_ROUNDED, disabled=True,
            style=button_style(),
            on_click=self._cancel_batch,
        )
        self.test10_button = ft.OutlinedButton(
            "Test First 10", style=button_style(),
            on_click=lambda e: self._request_batch(10))
        self.test25_button = ft.OutlinedButton(
            "Test First 25", style=button_style(),
            on_click=lambda e: self._request_batch(25))
        self.process_all_button = ft.OutlinedButton(
            "Process All", style=button_style(),
            on_click=lambda e: self._request_batch(None))

        self.progress_bar = ft.ProgressBar(value=0.0, color=ACCENT, bgcolor=SURFACE_2,
                                           bar_height=7, border_radius=8)
        self.progress_current = body("", size=13, color=TXT)
        self.progress_pct = heading("", size=13, color=ACCENT)
        self.chip_success = stat_chip("Success", GREEN)
        self.chip_review = stat_chip("Review", AMBER)
        self.chip_failed = stat_chip("Failed", RED)
        self.chip_skipped = stat_chip("Skipped", GREY)
        self.stats_row = ft.Row(
            [self.chip_success.control, self.chip_review.control,
             self.chip_failed.control, self.chip_skipped.control],
            wrap=True, spacing=8, run_spacing=8, visible=False,
        )
        self.batch_hint = body(
            "Originals are never modified. Processed copies are saved next to the "
            "source folder.", size=11.5, color=MUTED)

    def _placeholder(self, label: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [ft.Icon(ft.Icons.IMAGE_OUTLINED, size=40, color=BORDER),
                 body(label, color=MUTED, size=12)],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=414, width=320, bgcolor=SURFACE_2, border_radius=12,
            border=ft.border.all(1, BORDER), alignment=ft.alignment.center,
        )

    def _framed(self, *controls: ft.Control) -> ft.Container:
        return ft.Container(
            content=ft.Stack(list(controls)),
            border_radius=12,
            shadow=ft.BoxShadow(blur_radius=22, spread_radius=-6,
                                color="#66000000", offset=ft.Offset(0, 10)),
        )

    def _main_view(self) -> ft.Control:
        left = ft.Column(
            [
                card(
                    "Source", ft.Icons.FOLDER_COPY_ROUNDED,
                    ft.Row([self.source_field, self.browse_button]),
                    self.output_field,
                    self.source_info,
                ),
                card(
                    "Output Settings", ft.Icons.TUNE_ROUNDED,
                    ft.Row([self.f_width, self.f_height], wrap=True),
                    ft.Row([self.f_eye_x, self.f_eye_y], wrap=True),
                    ft.Row([self.f_eye_dist, self.f_quality], wrap=True),
                    ft.Row([
                        ft.TextButton("Restore defaults", icon=ft.Icons.RESTART_ALT_ROUNDED,
                                      style=button_style(),
                                      on_click=self._restore_defaults),
                    ]),
                ),
                card(
                    "Batch Processing", ft.Icons.ROCKET_LAUNCH_ROUNDED,
                    ft.Row([self.start_button, self.cancel_button]),
                    ft.Row([self.test10_button, self.test25_button,
                            self.process_all_button], wrap=True),
                    self.progress_bar,
                    ft.Row([self.progress_current, self.progress_pct],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    self.stats_row,
                    self.batch_hint,
                ),
            ],
            width=436, spacing=14, scroll=ft.ScrollMode.AUTO,
        )

        preview_buttons = ft.Row(
            [
                ft.OutlinedButton("Previous", icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
                                  style=button_style(),
                                  on_click=lambda e: self._navigate_preview(-1)),
                ft.OutlinedButton("Next", icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
                                  style=button_style(),
                                  on_click=lambda e: self._navigate_preview(1)),
                ft.FilledTonalButton("Auto Process Preview",
                                     icon=ft.Icons.AUTO_FIX_HIGH_ROUNDED,
                                     style=button_style(),
                                     on_click=lambda e: self._process_preview()),
                ft.OutlinedButton("Reset", icon=ft.Icons.CLEAR_ROUNDED,
                                  style=button_style(),
                                  on_click=self._reset_preview),
                ft.TextButton("Choose sample photos...",
                              icon=ft.Icons.PHOTO_LIBRARY_ROUNDED,
                              style=button_style(),
                              on_click=self._choose_samples),
            ],
            wrap=True, spacing=8, run_spacing=8,
        )
        framing_block = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [ft.Row([ft.Icon(ft.Icons.CROP_FREE_ROUNDED, size=16,
                                         color=ACCENT),
                                 heading("Framing - face size in frame", size=13)],
                                spacing=8),
                         self.framing_value_text],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    self.framing_presets,
                    ft.Row(
                        [body("Wider view", size=11, color=MUTED),
                         self.framing_slider,
                         body("Closer face", size=11, color=MUTED)],
                        spacing=10,
                    ),
                    body("Applies to the preview and to every photo in the batch.",
                         size=11, color=MUTED),
                ],
                spacing=10,
            ),
            bgcolor=SURFACE_2, border=ft.border.all(1, BORDER),
            border_radius=12, padding=14,
        )
        self.original_label = heading("ORIGINAL", size=11.5, color=MUTED)
        preview_row = ft.Row(
            [
                ft.Column([self.original_label,
                           self._framed(self.preview_orig_placeholder,
                                        self.preview_original)],
                          expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                          spacing=8),
                ft.Column([heading("CROPPED", size=11.5, color=MUTED),
                           self._framed(self.preview_crop_placeholder,
                                        self.preview_cropped)],
                          expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                          spacing=8),
            ],
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        right = ft.Column(
            [
                card(
                    "Preview", ft.Icons.VISIBILITY_ROUNDED,
                    preview_buttons,
                    framing_block,
                    ft.Row([self.overlay_check, self.preview_progress]),
                    preview_row,
                    self.preview_status,
                ),
            ],
            expand=True, spacing=14, scroll=ft.ScrollMode.AUTO,
        )
        return ft.Container(
            content=ft.Row([left, right], expand=True,
                           vertical_alignment=ft.CrossAxisAlignment.START, spacing=16),
            padding=ft.padding.only(16, 14, 16, 16), expand=True,
        )

    def show_main(self) -> None:
        self.page.appbar = None
        header = header_bar(
            self.page,
            actions=[
                ft.FilledTonalButton(
                    "Review Flagged Photos", icon=ft.Icons.FLAG_ROUNDED,
                    style=button_style(),
                    on_click=lambda e: self.show_review()),
                ft.IconButton(ft.Icons.INFO_OUTLINE_ROUNDED, tooltip="About",
                              icon_color=MUTED, on_click=self._show_about),
            ],
        )
        self.page.controls.clear()
        self.page.add(ft.Column([header, self._main_view()], spacing=0, expand=True))
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
                    self.source_info.color = GREEN
                except OutputSafetyError as exc:
                    self.output_field.value = ""
                    self.source_info.value = str(exc)
                    self.source_info.color = RED
            else:
                self.output_field.value = ""
                self.source_info.value = "Folder not found. Check the path."
                self.source_info.color = RED
        else:
            self.output_field.value = ""
            self.source_info.value = "Select the folder that contains the portrait photos."
            self.source_info.color = MUTED
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
        crop = self._parse_settings()
        # Keep the framing slider in sync with the numeric field.
        slider_value = min(46.0, max(24.0, crop.eye_distance_pct))
        if abs(slider_value - float(self.framing_slider.value or 0)) > 0.01:
            self.framing_slider.value = slider_value
            self._update_framing_readout(crop.eye_distance_pct)
            self.page.update()

    def _restore_defaults(self, e: ft.ControlEvent) -> None:
        crop = CropSettings()
        self.settings.crop = crop
        self.f_width.value = str(crop.output_width)
        self.f_height.value = str(crop.output_height)
        self.f_eye_x.value = f"{crop.eye_center_x_pct:g}"
        self.f_eye_y.value = f"{crop.eye_center_y_pct:g}"
        self.f_eye_dist.value = f"{crop.eye_distance_pct:g}"
        self.f_quality.value = str(crop.jpeg_quality)
        self.framing_slider.value = crop.eye_distance_pct
        self._update_framing_readout(crop.eye_distance_pct)
        save_settings(self.settings)
        self.page.update()
        self._rerender_crop_only()

    # ------------------------------------------------------------------
    # framing (zoom) control
    # ------------------------------------------------------------------

    def _update_framing_readout(self, value: float) -> None:
        self.framing_value_text.value = f"{value:.0f}%  ·  {_framing_word(value)}"
        self._sync_framing_preset_selection()

    def _sync_framing_preset_selection(self) -> None:
        try:
            value = float(self.framing_slider.value or 0)
        except (TypeError, ValueError):
            value = 0.0
        selected = {
            name for name, preset in FRAMING_PRESETS.items()
            if abs(preset - value) < 0.51
        }
        self.framing_presets.selected = selected or set()

    def _on_framing_slide(self, commit: bool) -> None:
        value = float(self.framing_slider.value or CropSettings().eye_distance_pct)
        self._update_framing_readout(value)
        if not commit:
            self.page.update()
            return
        self.f_eye_dist.value = f"{value:g}"
        self._parse_settings()
        save_settings(self.settings)
        self.page.update()
        self._rerender_crop_only()

    def _on_framing_preset(self, e: ft.ControlEvent) -> None:
        selected = next(iter(self.framing_presets.selected or []), None)
        if selected not in FRAMING_PRESETS:
            self._sync_framing_preset_selection()
            self.page.update()
            return
        value = FRAMING_PRESETS[selected]
        self.framing_slider.value = value
        self.f_eye_dist.value = f"{value:g}"
        self._update_framing_readout(value)
        self._parse_settings()
        save_settings(self.settings)
        self.page.update()
        self._rerender_crop_only()

    def _rerender_crop_only(self) -> None:
        """Re-crop the current preview with the new settings - no re-detection."""
        if self._preview_cache is None or self._preview_busy:
            return
        self._preview_busy = True
        self.preview_progress.visible = True
        self.page.update()
        self.page.run_thread(self._rerender_worker)

    def _rerender_worker(self) -> None:
        try:
            path, bgr, result, _old = self._preview_cache
            crop = self.settings.crop
            rendered = None
            if result.faces:
                rendered = render_from_analysis(bgr, result, crop,
                                                self.settings.quality)
                reasons = list(rendered.qa.review_reasons)
                would_be = "REVIEW" if reasons else "SUCCESS"
                detail = f" - {'; '.join(reasons)}" if reasons else ""
                position = f"{(self.sample_index % max(1, len(self.samples))) + 1}/{max(1, len(self.samples))}"
                self.preview_status.value = f"[{position}] {path.name}: would be {would_be}{detail}"
            self._preview_cache = (path, bgr, result, rendered)
        except Exception:
            self.log.exception("Preview re-render failed")
        finally:
            self._preview_busy = False
            self.preview_progress.visible = False
            self._refresh_preview_images()

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
        overlay_on = bool(self.overlay_check.value and result.faces)
        if overlay_on:
            chosen = rendered.face_index if rendered else result.primary_face_index()
            display = draw_debug_overlay(bgr, result, chosen, max_dim=_PREVIEW_DIM * 2)
        else:
            display = bgr
        self.original_label.value = ("ORIGINAL  ·  DETECTION OVERLAY" if overlay_on
                                     else "ORIGINAL")
        self.original_label.color = ACCENT_2 if overlay_on else MUTED
        # Changing the key forces the Flutter Image widget to rebuild; without
        # it, some clients do not repaint when only src_base64 changes.
        self._preview_seq += 1
        self.preview_original.key = f"orig-{self._preview_seq}"
        self.preview_cropped.key = f"crop-{self._preview_seq}"
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
                heading("Original images will remain unchanged.", size=13.5,
                        color=GREEN),
                body("Processed copies will be saved to:", size=13),
                body(str(self.crop_root), color=ACCENT, size=12.5, selectable=True),
                ft.Divider(color=BORDER),
                body(f"Scope: {scope}", size=13),
                body(f"Output size: {crop.output_width} x {crop.output_height} px  ·  "
                     f"framing {crop.eye_distance_pct:.0f}% "
                     f"({_framing_word(crop.eye_distance_pct)})  ·  "
                     f"JPEG quality {crop.jpeg_quality}", size=13),
            ],
            tight=True, spacing=6,
        )
        mode_group = ft.RadioGroup(
            value=EXISTING_SKIP,
            content=ft.Column(
                [
                    ft.Radio(value=EXISTING_SKIP, active_color=ACCENT,
                             label="Continue / Skip Existing (keep files already processed)",
                             label_style=ft.TextStyle(color=TXT, size=13)),
                    ft.Radio(value=EXISTING_REPROCESS, active_color=ACCENT,
                             label="Reprocess Existing (overwrite previous output files)",
                             label_style=ft.TextStyle(color=TXT, size=13)),
                ],
                tight=True,
            ),
        )
        content_children: list[ft.Control] = [message]
        if existing_files:
            content_children += [
                ft.Divider(color=BORDER),
                heading("The output folder already exists.", size=13),
                mode_group,
            ]

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=SURFACE,
            shape=ft.RoundedRectangleBorder(radius=16),
            title=heading("Start processing?", size=16),
            content=ft.Container(ft.Column(content_children, tight=True, spacing=6,
                                           scroll=ft.ScrollMode.AUTO), width=540),
            actions=[
                ft.TextButton("Cancel", style=button_style(),
                              on_click=lambda e: self.page.close(dialog)),
                ft.FilledButton(
                    "Start", style=button_style(primary=True),
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
        self.progress_pct.value = ""
        self.stats_row.visible = True
        self._update_stat_chips(None)
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

    def _update_stat_chips(self, stats) -> None:
        self.chip_success.set(stats.success if stats else 0)
        self.chip_review.set(stats.review if stats else 0)
        self.chip_failed.set(stats.failed if stats else 0)
        self.chip_skipped.set(stats.skipped if stats else 0)

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
        self.progress_pct.value = f"{pct:.0f}%"
        self._update_stat_chips(stats)
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

        def stat_line(label: str, value: int, color: str) -> ft.Row:
            return ft.Row(
                [ft.Container(width=9, height=9, border_radius=5, bgcolor=color),
                 body(label, size=13.5, color=TXT),
                 ft.Container(expand=True),
                 heading(str(value), size=14, color=color)],
                spacing=10,
            )

        stats_rows = ft.Container(
            content=ft.Column(
                [
                    ft.Row([body("Total", size=13.5, color=MUTED),
                            ft.Container(expand=True),
                            heading(str(stats.total), size=14)], spacing=10),
                    stat_line("Success", stats.success, GREEN),
                    stat_line("Review", stats.review, AMBER),
                    stat_line("Failed", stats.failed, RED),
                    stat_line("Skipped", stats.skipped, GREY),
                ],
                spacing=8, tight=True,
            ),
            bgcolor=SURFACE_2, border=ft.border.all(1, BORDER),
            border_radius=12, padding=14,
        )
        sheet_status = body("", size=12, color=MUTED)

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
            bgcolor=SURFACE,
            shape=ft.RoundedRectangleBorder(radius=16),
            title=heading(title, size=16),
            content=ft.Container(
                ft.Column([stats_rows,
                           body(f"Output folder:\n{crop_root}", selectable=True,
                                size=12, color=MUTED),
                           sheet_status],
                          tight=True, spacing=10),
                width=470,
            ),
            actions=[
                ft.TextButton("Open Output Folder", icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                              style=button_style(), on_click=open_output),
                ft.TextButton("Review Flagged Photos", icon=ft.Icons.FLAG_ROUNDED,
                              style=button_style(), on_click=open_review),
                ft.TextButton("Generate Contact Sheet", icon=ft.Icons.GRID_VIEW_ROUNDED,
                              style=button_style(), on_click=gen_sheets),
                ft.TextButton("Open Processing Report", icon=ft.Icons.TABLE_VIEW_ROUNDED,
                              style=button_style(), on_click=open_report),
                ft.FilledButton("Close", style=button_style(primary=True),
                                on_click=lambda e: self.page.close(dialog)),
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
            bgcolor=SURFACE,
            shape=ft.RoundedRectangleBorder(radius=16),
            title=heading(title, size=15),
            content=body(message, selectable=True, size=13),
            actions=[ft.TextButton("OK", style=button_style(),
                                   on_click=lambda e: self.page.close(dialog))],
        )
        self.page.open(dialog)

    def _show_about(self, e: ft.ControlEvent) -> None:
        def fact(label: str, text: str) -> ft.Row:
            return ft.Row(
                [ft.Container(heading(label, size=12, color=ACCENT), width=110),
                 ft.Container(body(text, size=12.5), expand=True)],
                vertical_alignment=ft.CrossAxisAlignment.START,
            )

        about = ft.AlertDialog(
            bgcolor=SURFACE,
            shape=ft.RoundedRectangleBorder(radius=16),
            title=heading(f"About {APP_NAME}", size=15),
            content=ft.Container(
                ft.Column(
                    [
                        fact("Application", f"{APP_NAME}  v{__version__}"),
                        fact("Purpose", "Automatically align and crop portrait "
                                        "photographs for ID-card workflows."),
                        fact("Processing", "Local / offline. No photos ever leave "
                                           "this computer."),
                        fact("Original files", "Never modified. All results are "
                                               "written to a separate _crop folder."),
                        fact("Privacy", "Facial landmarks are used only for "
                                        "geometric alignment. No face recognition, "
                                        "no identity matching, no biometric "
                                        "profiles."),
                    ],
                    tight=True, spacing=10,
                ),
                width=500,
            ),
            actions=[ft.TextButton("Close", style=button_style(),
                                   on_click=lambda e: self.page.close(about))],
        )
        self.page.open(about)


def run_app(page: ft.Page) -> None:
    """Flet entry point."""
    CropperApp(page)
