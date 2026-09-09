"""Shared fixtures: deterministic sample photo sets built from a public-domain
portrait (NASA photo of Eileen Collins, distributed with scikit-image).

The engine fixture is session-scoped so MediaPipe models load only once.
Sample source folders are function-scoped copies so tests never interfere.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

DATA_DIR = Path(__file__).parent / "data"


def _grain(im: Image.Image, sigma: float, seed: int = 42) -> Image.Image:
    """Add camera-like sensor grain so upscaled fixtures read as 'sharp'."""
    arr = np.asarray(im).astype(np.float32)
    noise = np.random.default_rng(seed).normal(0.0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


def _jpeg_bytes(im: Image.Image, quality: int = 95) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def astronaut() -> Image.Image:
    return Image.open(DATA_DIR / "astronaut.jpg").convert("RGB")


@pytest.fixture(scope="session")
def clean_portrait(astronaut: Image.Image) -> Image.Image:
    """A portrait that should classify as SUCCESS under default settings."""
    crop = astronaut.crop((94, 0, 354, 347)).resize((1040, 1388), Image.LANCZOS)
    crop = crop.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=2))
    return _grain(crop, 3.0)


@pytest.fixture(scope="session")
def sample_files(astronaut: Image.Image, clean_portrait: Image.Image) -> dict[str, bytes]:
    """Filename -> raw bytes for a representative source folder."""
    files: dict[str, bytes] = {}
    files["IMG_0001.JPG"] = _jpeg_bytes(clean_portrait)

    rotated = clean_portrait.rotate(18, expand=True, fillcolor=(240, 240, 240))
    files["IMG_0002.JPG"] = _jpeg_bytes(rotated)

    head = astronaut.crop((150, 20, 320, 220))
    two = Image.new("RGB", (1800, 1200), (226, 230, 236))
    two.paste(head.resize((510, 600), Image.LANCZOS), (150, 300))
    two.paste(head.resize((425, 500), Image.LANCZOS), (1100, 350))
    files["IMG_0003.JPG"] = _jpeg_bytes(_grain(two, 2.0))

    grad = np.tile(np.linspace(40, 200, 800, dtype=np.uint8), (600, 1))
    noface = Image.fromarray(
        np.stack([grad, grad // 2 + 30, np.flipud(grad)], axis=2))
    files["IMG_0004.JPG"] = _jpeg_bytes(noface, quality=90)

    files["IMG_0005.JPG"] = _jpeg_bytes(clean_portrait)[:2048]  # truncated/corrupt

    # Sideways pixels + EXIF orientation 6 (must display upright after load).
    sideways = clean_portrait.rotate(90, expand=True)
    exif = Image.Exif()
    exif[274] = 6
    buf = io.BytesIO()
    sideways.save(buf, "JPEG", quality=95, exif=exif)
    files["IMG_0006.JPG"] = buf.getvalue()

    files["DSC_1845.jpeg"] = _jpeg_bytes(clean_portrait, quality=92)
    files["000123.png"] = _png_bytes(clean_portrait)
    files["notes.txt"] = b"not an image at all\n"
    return files


@pytest.fixture()
def sample_source(tmp_path: Path, sample_files: dict[str, bytes]) -> Path:
    """A fresh source folder named like a real one, e.g. .../Employee_IDs."""
    source = tmp_path / "Employee_IDs"
    source.mkdir()
    for name, blob in sample_files.items():
        (source / name).write_bytes(blob)
    return source


@pytest.fixture(scope="session")
def engine():
    from processing.detector import get_face_engine

    return get_face_engine()


@pytest.fixture()
def default_settings():
    from app.settings import AppSettings

    return AppSettings()
