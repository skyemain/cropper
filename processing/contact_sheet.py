"""Contact sheet generation.

Builds paginated grid sheets of the processed photos with the filename under
each thumbnail. Pages are rendered one at a time so a 2,000-image batch never
requires a huge bitmap or all images in memory at once.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from utilities.logging_utils import get_logger
from utilities.paths import (
    CONTACT_SHEET_DIR_NAME,
    SUPPORTED_EXTENSIONS,
    validate_output_path,
)

COLUMNS = 5
ROWS = 6
THUMB_W = 220
THUMB_H = 294  # 3:4, matches the default output aspect
CAPTION_H = 26
PADDING = 14
MARGIN = 20
BACKGROUND = (245, 246, 248)
CAPTION_COLOR = (40, 44, 52)


def _load_font(size: int = 15) -> ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # older Pillow without size kwarg
        return ImageFont.load_default()


def list_processed_images(crop_root: Path) -> list[Path]:
    """Final processed photos: the top level of the crop folder only."""
    crop_root = Path(crop_root)
    if not crop_root.is_dir():
        return []
    files = [
        p for p in crop_root.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def generate_contact_sheets(
    source_root: Path,
    crop_root: Path,
    progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> list[Path]:
    """Create ``CONTACT_SHEETS/contact_sheet_NNN.jpg`` pages; returns paths."""
    logger = get_logger()
    images = list_processed_images(crop_root)
    sheet_dir = Path(crop_root) / CONTACT_SHEET_DIR_NAME
    sheet_dir.mkdir(parents=True, exist_ok=True)

    per_page = COLUMNS * ROWS
    page_w = MARGIN * 2 + COLUMNS * THUMB_W + (COLUMNS - 1) * PADDING
    page_h = MARGIN * 2 + ROWS * (THUMB_H + CAPTION_H) + (ROWS - 1) * PADDING
    font = _load_font()
    created: list[Path] = []

    for page_idx in range(0, max(1, (len(images) + per_page - 1) // per_page)):
        if cancel_event is not None and cancel_event.is_set():
            break
        chunk = images[page_idx * per_page: (page_idx + 1) * per_page]
        if not chunk and page_idx > 0:
            break
        sheet = Image.new("RGB", (page_w, page_h), BACKGROUND)
        draw = ImageDraw.Draw(sheet)
        for cell, img_path in enumerate(chunk):
            row, col = divmod(cell, COLUMNS)
            x = MARGIN + col * (THUMB_W + PADDING)
            y = MARGIN + row * (THUMB_H + CAPTION_H + PADDING)
            try:
                with Image.open(img_path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
                    ox = x + (THUMB_W - im.width) // 2
                    oy = y + (THUMB_H - im.height) // 2
                    sheet.paste(im, (ox, oy))
            except (UnidentifiedImageError, OSError):
                draw.rectangle([x, y, x + THUMB_W, y + THUMB_H], outline=(200, 60, 60))
                draw.text((x + 8, y + 8), "unreadable", fill=(200, 60, 60), font=font)
            caption = img_path.stem
            if len(caption) > 26:
                caption = caption[:24] + "..."
            text_w = draw.textlength(caption, font=font)
            draw.text(
                (x + (THUMB_W - text_w) / 2, y + THUMB_H + 5),
                caption, fill=CAPTION_COLOR, font=font,
            )
            if progress:
                progress(page_idx * per_page + cell + 1, len(images))

        sheet_path = sheet_dir / f"contact_sheet_{page_idx + 1:03d}.jpg"
        validate_output_path(source_root, crop_root, sheet_path)
        sheet.save(sheet_path, "JPEG", quality=88)
        created.append(sheet_path)
        if not chunk:  # empty crop folder -> single empty page is enough
            break

    logger.info("Generated %d contact sheet page(s) in %s", len(created), sheet_dir)
    return created
