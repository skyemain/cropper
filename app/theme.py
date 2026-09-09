"""Design system: palette, typography, and reusable styled components.

A single dark, modern theme (deep-navy surfaces, indigo->violet accent,
Inter typeface). Both the main screen and the review screen build from these
helpers so the whole app stays visually consistent.
"""

from __future__ import annotations

import flet as ft

from app import APP_NAME, __version__

# ----------------------------------------------------------------------------
# palette
# ----------------------------------------------------------------------------

BG = "#0B1020"          # page background
SURFACE = "#141B2E"     # cards
SURFACE_2 = "#1C2540"   # nested surfaces / inputs
BORDER = "#2A355A"
ACCENT = "#7C8CFF"      # indigo
ACCENT_2 = "#A78BFA"    # violet
TXT = "#E8EDF8"
MUTED = "#8B96B4"
GREEN = "#34D399"
AMBER = "#FBBF24"
RED = "#F87171"
GREY = "#7E8AA6"

FONT_BODY = "Inter"
FONT_SEMIBOLD = "Inter-SemiBold"
FONT_BOLD = "Inter-Bold"


# ----------------------------------------------------------------------------
# typography
# ----------------------------------------------------------------------------

def heading(text: str, size: float = 14, color: str = TXT, **kwargs) -> ft.Text:
    return ft.Text(text, size=size, color=color, font_family=FONT_SEMIBOLD, **kwargs)


def body(text: str, size: float = 13, color: str = TXT, **kwargs) -> ft.Text:
    return ft.Text(text, size=size, color=color, font_family=FONT_BODY, **kwargs)


# ----------------------------------------------------------------------------
# components
# ----------------------------------------------------------------------------

def button_style(primary: bool = False) -> ft.ButtonStyle:
    if primary:
        return ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.Padding(18, 12, 18, 12),
            bgcolor=ACCENT,
            color="#0B1020",
        )
    return ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=10),
        padding=ft.Padding(14, 10, 14, 10),
    )


def style_field(field: ft.TextField) -> ft.TextField:
    """Apply the shared input styling to a TextField."""
    field.border_radius = 10
    field.bgcolor = SURFACE_2
    field.border_color = BORDER
    field.focused_border_color = ACCENT
    field.cursor_color = ACCENT
    field.text_style = ft.TextStyle(color=TXT, size=13, font_family=FONT_BODY)
    field.label_style = ft.TextStyle(color=MUTED, size=12, font_family=FONT_BODY)
    field.hint_style = ft.TextStyle(color=MUTED, size=12.5, font_family=FONT_BODY)
    return field


def card(title: str, icon, *controls: ft.Control) -> ft.Container:
    """A titled surface card with an accent icon badge."""
    header = ft.Row(
        [
            ft.Container(
                content=ft.Icon(icon, size=15, color=ACCENT),
                width=28, height=28, border_radius=8,
                bgcolor="#2A2F55", alignment=ft.alignment.center,
            ),
            heading(title, size=13.5),
        ],
        spacing=10,
    )
    return ft.Container(
        content=ft.Column([header, *controls], spacing=12),
        bgcolor=SURFACE,
        border=ft.border.all(1, BORDER),
        border_radius=16,
        padding=18,
    )


class StatChip:
    """A pill showing a colored dot, a label, and a live count."""

    def __init__(self, label: str, color: str):
        self.count_text = heading("0", size=13, color=color)
        self.control = ft.Container(
            content=ft.Row(
                [ft.Container(width=8, height=8, border_radius=4, bgcolor=color),
                 body(label, size=12, color=MUTED),
                 self.count_text],
                spacing=7, tight=True,
            ),
            bgcolor=SURFACE_2,
            border=ft.border.all(1, BORDER),
            border_radius=999,
            padding=ft.Padding(12, 7, 12, 7),
        )

    def set(self, value: int) -> None:
        self.count_text.value = str(value)


def stat_chip(label: str, color: str) -> StatChip:
    return StatChip(label, color)


def header_bar(page: ft.Page, actions: list[ft.Control],
               leading: ft.Control | None = None,
               title: str = APP_NAME,
               subtitle: str = "Batch ID portrait alignment - local & private") -> ft.Container:
    """Gradient app header shared by all screens."""
    logo = ft.Container(
        content=ft.Image(src="/icon.png", width=34, height=34, border_radius=8),
        width=42, height=42, border_radius=12,
        gradient=ft.LinearGradient(
            begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
            colors=[ACCENT, ACCENT_2],
        ),
        alignment=ft.alignment.center,
    )
    title_block = ft.Column(
        [ft.Row([heading(title, size=16.5),
                 ft.Container(
                     content=body(f"v{__version__}", size=10.5, color=MUTED),
                     bgcolor=SURFACE_2, border_radius=999,
                     padding=ft.Padding(8, 2, 8, 2),
                     border=ft.border.all(1, BORDER)),
                 ], spacing=10),
         body(subtitle, size=11.5, color=MUTED)],
        spacing=2,
    )
    items: list[ft.Control] = []
    if leading is not None:
        items.append(leading)
    items += [logo, title_block, ft.Container(expand=True), *actions]
    return ft.Container(
        content=ft.Row(items, spacing=14,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(18, 14, 18, 14),
        gradient=ft.LinearGradient(
            begin=ft.alignment.center_left, end=ft.alignment.center_right,
            colors=["#121A33", "#1A1633"],
        ),
        border=ft.border.only(bottom=ft.BorderSide(1, BORDER)),
    )
