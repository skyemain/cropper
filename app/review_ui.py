"""Manual review screen for photos flagged as REVIEW.

Lets the user pan / zoom / rotate the crop, pick a face when several were
detected, and save the corrected result. Corrections are rendered by the
exact batch pipeline and saved into the main ``_crop`` folder; the copy in
``_crop/REVIEW`` is removed after a successful override. Originals are never
touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import flet as ft

from app.settings import AppSettings
from app.theme import (
    ACCENT,
    AMBER,
    BORDER,
    GREEN,
    MUTED,
    SURFACE,
    SURFACE_2,
    TXT,
    body,
    button_style,
    header_bar,
    heading,
)
from processing.alignment import ManualAdjust
from processing.detector import EngineResult, get_face_engine
from processing.processor import (
    STATUS_SUCCESS,
    load_and_analyze,
    render_from_analysis,
)
from utilities.image_utils import bgr_to_jpeg_base64, save_image
from utilities.logging_utils import get_logger
from utilities.paths import (
    REPORT_FILENAME,
    REVIEW_DIR_NAME,
    validate_output_path,
)
from utilities.report import ReportBook


class ReviewItem:
    def __init__(self, filename: str, source_path: Path, reasons: str):
        self.filename = filename
        self.source_path = source_path
        self.reasons = reasons


class ReviewScreen:
    def __init__(
        self,
        page: ft.Page,
        settings: AppSettings,
        source_dir: Path,
        crop_root: Path,
        on_back: Callable[[], None],
    ):
        self.page = page
        self.settings = settings
        self.source_dir = Path(source_dir)
        self.crop_root = Path(crop_root)
        self.on_back = on_back
        self.log = get_logger()

        self.report = ReportBook(self.crop_root / REPORT_FILENAME)
        self.items = self._collect_items()
        self.index = 0
        self.adjust = ManualAdjust()
        self.face_index: Optional[int] = None
        self._cache: Optional[tuple[str, object, EngineResult]] = None  # name, bgr, result
        self._busy = False
        self._image_seq = 0

        self._build_controls()

    # ------------------------------------------------------------------

    def _collect_items(self) -> list[ReviewItem]:
        review_dir = self.crop_root / REVIEW_DIR_NAME
        items: list[ReviewItem] = []
        for row in self.report.rows():
            if row.get("status") != "REVIEW":
                continue
            name = row.get("filename", "")
            if not name or not (review_dir / name).exists():
                continue
            source = Path(row.get("source_path") or (self.source_dir / name))
            if not source.exists():
                source = self.source_dir / name
            if source.exists():
                items.append(ReviewItem(name, source, row.get("reason", "")))
        # Also include files sitting in REVIEW/ that are missing from the CSV.
        known = {item.filename for item in items}
        if review_dir.is_dir():
            for path in sorted(review_dir.iterdir(), key=lambda p: p.name.lower()):
                if path.is_file() and path.name not in known:
                    source = self.source_dir / path.name
                    if source.exists():
                        items.append(ReviewItem(path.name, source, "flagged for review"))
        return items

    # ------------------------------------------------------------------

    def _build_controls(self) -> None:
        self.counter_text = heading("", size=13)
        self.reason_text = body("", size=12.5, color=AMBER)
        self.status_text = body("", size=12, color=MUTED)
        self.busy_ring = ft.ProgressRing(width=16, height=16, stroke_width=2,
                                         color=ACCENT, visible=False)

        self.image_view = ft.Image(src_base64="", fit=ft.ImageFit.CONTAIN,
                                   height=500, visible=False, border_radius=12)
        self.image_placeholder = ft.Container(
            content=ft.ProgressRing(color=ACCENT),
            height=500, alignment=ft.alignment.center,
            bgcolor=SURFACE_2, border_radius=12, border=ft.border.all(1, BORDER),
        )

        self.item_list = ft.ListView(expand=True, spacing=6)

        self.face_dropdown = ft.Dropdown(
            label="Use face", width=190, visible=False,
            bgcolor=SURFACE_2, border_color=BORDER, focused_border_color=ACCENT,
            border_radius=10,
            label_style=ft.TextStyle(color=MUTED, size=12),
            text_style=ft.TextStyle(color=TXT, size=13),
            on_change=lambda e: self._on_face_selected(),
        )

        def slider(mn: float, mx: float, value: float, fmt: str) -> ft.Slider:
            return ft.Slider(
                min=mn, max=mx, value=value, label=fmt, expand=True,
                active_color=ACCENT, inactive_color=SURFACE_2,
                on_change_end=lambda e: self._on_adjust_changed(),
            )

        self.s_dx = slider(-200, 200, 0, "{value} px")
        self.s_dy = slider(-200, 200, 0, "{value} px")
        self.s_zoom = slider(0.6, 1.6, 1.0, "{value}x")
        self.s_rot = slider(-20, 20, 0, "{value} deg")

        self.save_button = ft.FilledButton(
            "Save Override", icon=ft.Icons.SAVE_ROUNDED,
            style=button_style(primary=True),
            on_click=lambda e: self._save_override())
        self.reset_button = ft.OutlinedButton(
            "Reset to automatic crop", icon=ft.Icons.RESTART_ALT_ROUNDED,
            style=button_style(),
            on_click=lambda e: self._reset_adjust())
        self.prev_button = ft.OutlinedButton(
            "Previous", icon=ft.Icons.CHEVRON_LEFT_ROUNDED, style=button_style(),
            on_click=lambda e: self._navigate(-1))
        self.next_button = ft.OutlinedButton(
            "Next", icon=ft.Icons.CHEVRON_RIGHT_ROUNDED, style=button_style(),
            on_click=lambda e: self._navigate(1))

    def _label_row(self, text: str, control: ft.Control) -> ft.Row:
        return ft.Row([ft.Container(body(text, size=12, color=MUTED), width=130),
                       control])

    def show(self) -> None:
        self.page.appbar = None
        header = header_bar(
            self.page,
            leading=ft.IconButton(ft.Icons.ARROW_BACK_ROUNDED, tooltip="Back",
                                  icon_color=TXT,
                                  on_click=lambda e: self.on_back()),
            title="Manual Review",
            subtitle="Adjust and approve flagged photos",
            actions=[],
        )
        self._rebuild_item_list()

        left = ft.Container(
            content=ft.Column(
                [ft.Row([ft.Icon(ft.Icons.FLAG_ROUNDED, size=15, color=AMBER),
                         heading("Flagged photos", size=13)], spacing=8),
                 self.item_list],
                spacing=10, expand=True,
            ),
            width=272, padding=14,
            bgcolor=SURFACE, border=ft.border.all(1, BORDER), border_radius=16,
        )
        controls_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row([self.counter_text, self.busy_ring]),
                    self.reason_text,
                    self.face_dropdown,
                    self._label_row("Move left / right", self.s_dx),
                    self._label_row("Move up / down", self.s_dy),
                    self._label_row("Zoom", self.s_zoom),
                    self._label_row("Rotate", self.s_rot),
                    ft.Row([self.prev_button, self.next_button, self.reset_button,
                            self.save_button], wrap=True, spacing=8, run_spacing=8),
                    self.status_text,
                ],
                spacing=10,
            ),
            bgcolor=SURFACE, border=ft.border.all(1, BORDER), border_radius=16,
            padding=16,
        )
        center = ft.Column(
            [ft.Container(
                content=ft.Stack([self.image_placeholder, self.image_view]),
                border_radius=12,
                shadow=ft.BoxShadow(blur_radius=22, spread_radius=-6,
                                    color="#66000000", offset=ft.Offset(0, 10)),
             ),
             controls_panel],
            expand=True, spacing=14, scroll=ft.ScrollMode.AUTO,
        )
        self.page.controls.clear()
        self.page.add(ft.Column(
            [header,
             ft.Container(
                 content=ft.Row([left, center], expand=True, spacing=16,
                                vertical_alignment=ft.CrossAxisAlignment.START),
                 padding=ft.padding.only(16, 14, 16, 16), expand=True,
             )],
            spacing=0, expand=True,
        ))
        self.page.update()
        if self.items:
            self._load_item(0)

    # ------------------------------------------------------------------

    def _rebuild_item_list(self) -> None:
        self.item_list.controls.clear()
        for idx, item in enumerate(self.items):
            def make_handler(i: int):
                return lambda e: self._load_item(i)

            selected = idx == self.index
            self.item_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [heading(item.filename, size=12,
                                 color=ACCENT if selected else TXT),
                         body(item.reasons[:90] or "flagged for review",
                              size=10.5, color=MUTED)],
                        spacing=3, tight=True,
                    ),
                    padding=ft.Padding(12, 9, 12, 9),
                    border_radius=10,
                    bgcolor=SURFACE_2 if selected else None,
                    border=ft.border.all(1, BORDER if selected else "#00000000"),
                    on_click=make_handler(idx),
                    ink=True,
                )
            )

    def _navigate(self, step: int) -> None:
        if not self.items:
            return
        self._load_item((self.index + step) % len(self.items))

    def _load_item(self, index: int) -> None:
        if self._busy or not self.items:
            return
        self.index = max(0, min(index, len(self.items) - 1))
        item = self.items[self.index]
        self.adjust = ManualAdjust()
        self.face_index = None
        self.s_dx.value = 0
        self.s_dy.value = 0
        self.s_zoom.value = 1.0
        self.s_rot.value = 0
        self.counter_text.value = f"{self.index + 1} / {len(self.items)}  -  {item.filename}"
        self.reason_text.value = item.reasons or "flagged for review"
        self.status_text.value = ""
        self.image_view.visible = False
        self.image_placeholder.visible = True
        self._rebuild_item_list()
        self._set_busy(True)
        self.page.update()
        self.page.run_thread(self._analyze_worker, item)

    def _analyze_worker(self, item: ReviewItem) -> None:
        try:
            engine = get_face_engine()
            bgr, result = load_and_analyze(item.source_path, engine)
            self._cache = (item.filename, bgr, result)
            options = [
                ft.dropdown.Option(key=str(i), text=f"Face {i + 1}")
                for i in range(len(result.faces))
            ]
            self.face_dropdown.options = options
            if result.faces:
                primary = result.primary_face_index()
                self.face_dropdown.value = str(primary)
                self.face_index = primary
            self.face_dropdown.visible = len(result.faces) > 1
            self._render_current()
        except Exception:
            self.log.exception("Review: could not analyze %s", item.filename)
            self._cache = None
            self.status_text.value = (f"Could not process {item.filename}. "
                                      "See processing.log for details.")
            self._set_busy(False)
            self.page.update()

    def _render_current(self) -> None:
        cache = self._cache
        if cache is None:
            self._set_busy(False)
            return
        name, bgr, result = cache
        try:
            if not result.faces:
                self.status_text.value = "No face landmarks available for this photo."
                self.image_view.visible = False
                self.image_placeholder.visible = True
                return
            rendered = render_from_analysis(
                bgr, result, self.settings.crop, self.settings.quality,
                face_index=self.face_index, adjust=self.adjust,
            )
            self._image_seq += 1
            self.image_view.key = f"review-{self._image_seq}"
            self.image_view.src_base64 = bgr_to_jpeg_base64(rendered.output_bgr, 1100)
            self.image_view.visible = True
            self.image_placeholder.visible = False
            if rendered.qa.review_reasons:
                self.status_text.value = ("Current checks: "
                                          + "; ".join(rendered.qa.review_reasons))
                self.status_text.color = AMBER
            else:
                self.status_text.value = "Current checks: no remaining warnings."
                self.status_text.color = GREEN
        except Exception:
            self.log.exception("Review: render failed for %s", name)
            self.status_text.value = (f"Could not render {name}. "
                                      "See processing.log for details.")
        finally:
            self._set_busy(False)
            self.page.update()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_ring.visible = busy
        self.save_button.disabled = busy
        self.prev_button.disabled = busy
        self.next_button.disabled = busy

    # ------------------------------------------------------------------

    def _on_adjust_changed(self) -> None:
        self.adjust = ManualAdjust(
            dx=float(self.s_dx.value or 0.0),
            dy=float(self.s_dy.value or 0.0),
            zoom=float(self.s_zoom.value or 1.0),
            rotate_deg=float(self.s_rot.value or 0.0),
        )
        if not self._busy:
            self._set_busy(True)
            self.page.update()
            self.page.run_thread(self._render_current)

    def _on_face_selected(self) -> None:
        try:
            self.face_index = int(self.face_dropdown.value)
        except (TypeError, ValueError):
            self.face_index = None
        if not self._busy:
            self._set_busy(True)
            self.page.update()
            self.page.run_thread(self._render_current)

    def _reset_adjust(self) -> None:
        self.adjust = ManualAdjust()
        self.s_dx.value = 0
        self.s_dy.value = 0
        self.s_zoom.value = 1.0
        self.s_rot.value = 0
        if self._cache is not None:
            cached_result: EngineResult = self._cache[2]
            if cached_result.faces:
                self.face_index = cached_result.primary_face_index()
                self.face_dropdown.value = str(self.face_index)
        self.page.update()
        if not self._busy:
            self._set_busy(True)
            self.page.run_thread(self._render_current)

    # ------------------------------------------------------------------

    def _save_override(self) -> None:
        if self._busy or self._cache is None or not self.items:
            return
        self._set_busy(True)
        self.status_text.value = "Saving corrected crop..."
        self.page.update()
        self.page.run_thread(self._save_worker)

    def _save_worker(self) -> None:
        item = self.items[self.index]
        try:
            name, bgr, result = self._cache
            rendered = render_from_analysis(
                bgr, result, self.settings.crop, self.settings.quality,
                face_index=self.face_index, adjust=self.adjust,
            )
            destination = self.crop_root / item.filename
            validate_output_path(self.source_dir, self.crop_root, destination)
            save_image(rendered.output_bgr, destination,
                       self.settings.crop.jpeg_quality)

            review_copy = self.crop_root / REVIEW_DIR_NAME / item.filename
            if review_copy.exists():
                validate_output_path(self.source_dir, self.crop_root, review_copy)
                review_copy.unlink()

            self.report.update_row(item.filename, {
                "status": STATUS_SUCCESS,
                "output_path": str(destination),
                "reason": "manual override saved from review screen",
            })
            self.report.save()
            self.log.info("Review override saved for %s -> %s", item.filename, destination)

            del self.items[self.index]
            if not self.items:
                self._set_busy(False)
                self.status_text.value = "All flagged photos reviewed."
                self.on_back()
                return
            self._set_busy(False)
            self._load_item(min(self.index, len(self.items) - 1))
        except Exception:
            self.log.exception("Review: save override failed for %s", item.filename)
            self.status_text.value = (f"Could not save {item.filename}. "
                                      "See processing.log for details.")
            self._set_busy(False)
            self.page.update()
