"""Image reading, encoding, and safe atomic writing.

Reads happen exactly once per image (Pillow decode with EXIF orientation
applied in memory), all geometry is done on the decoded array, and the final
result is encoded exactly once. Sources are opened strictly read-only.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

JPEG_EXTENSIONS = {".jpg", ".jpeg"}


class ImageLoadError(Exception):
    """The file could not be decoded as an image."""


def load_image_bgr(path: Path) -> np.ndarray:
    """Decode an image file into a BGR uint8 array.

    EXIF orientation is applied in memory; the source file is not touched.
    Grayscale, palette, and alpha images are converted to 3-channel RGB
    (alpha composited over white, which suits ID photos).
    """
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                im = Image.alpha_composite(background, rgba).convert("RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")
            rgb = np.asarray(im, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ImageLoadError(f"Cannot decode image: {path.name} ({exc})") from exc
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0] < 8 or rgb.shape[1] < 8:
        raise ImageLoadError(f"Unsupported image geometry: {path.name}")
    return np.ascontiguousarray(rgb[:, :, ::-1])


def encode_image(bgr: np.ndarray, extension: str, jpeg_quality: int = 95) -> bytes:
    """Encode a BGR array once, honouring the requested file extension."""
    ext = extension.lower()
    if ext in JPEG_EXTENSIONS:
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    elif ext == ".png":
        ok, buf = cv2.imencode(".png", bgr, [int(cv2.IMWRITE_PNG_COMPRESSION), 6])
    else:
        raise ValueError(f"Unsupported output extension: {extension}")
    if not ok:
        raise ValueError(f"Failed to encode image as {extension}")
    return buf.tobytes()


def write_bytes_atomic(data: bytes, destination: Path) -> None:
    """Write bytes to *destination* via a temporary file + atomic replace.

    Prevents half-written images if the process is cancelled or crashes.
    Unicode-safe on Windows (no cv2.imwrite path limitations).
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".part")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, destination)


def save_image(bgr: np.ndarray, destination: Path, jpeg_quality: int = 95) -> None:
    """Encode once and write atomically. Caller must have validated the path."""
    data = encode_image(bgr, Path(destination).suffix, jpeg_quality)
    write_bytes_atomic(data, destination)


def bgr_to_jpeg_base64(bgr: np.ndarray, max_dim: int = 640, quality: int = 82) -> str:
    """Downscaled JPEG base64 string for GUI preview display."""
    h, w = bgr.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (max(1, round(w * scale)), max(1, round(h * scale))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("Failed to encode preview image")
    return base64.b64encode(buf.tobytes()).decode("ascii")
