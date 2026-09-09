# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ID Photo Auto Cropper.

One-FOLDER build by design: MediaPipe ships native libraries and model data
that are far more reliable unpacked next to the executable than repacked into
a self-extracting single file. Build with:

    pyinstaller --noconfirm packaging/pyinstaller.spec
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

APP_NAME = "ID Photo Auto Cropper"

project_root = Path(SPECPATH).resolve().parent  # spec lives in packaging/

datas = [
    (str(project_root / "models"), "models"),
    (str(project_root / "assets"), "assets"),
]
binaries = []
hiddenimports = []

# MediaPipe bundles .tflite/.binarypb graph assets inside the package; collect
# everything so the Tasks runtime finds them when frozen.
for package in ("mediapipe",):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# The Flet desktop client (Flutter runtime) lives in a per-platform package:
# flet_desktop on Windows/macOS, flet_desktop_light on Linux.
for package in ("flet_desktop", "flet_desktop_light"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # package for the other platform is simply not installed

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # NOTE: matplotlib cannot be excluded - mediapipe imports it at package
    # import time (mediapipe.python.solutions.drawing_utils).
    # jax/jaxlib/scipy are only used by mediapipe's model-maker/genai extras,
    # not by the vision tasks this app runs; excluding them cuts ~400 MB.
    # The packaged-app selftest exercises the full pipeline to prove this.
    excludes=["tkinter", "IPython", "pytest", "jax", "jaxlib", "scipy", "ml_dtypes"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI application - no console window
    disable_windowed_traceback=False,
    icon=str(project_root / "assets" / "icon.ico") if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
