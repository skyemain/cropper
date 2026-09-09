# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-FILE build for ID Photo Auto Cropper.

Portable: copy a single .exe to any Windows PC (no install step).
First launch is slower while the bundle unpacks to a temp folder.

Build (on Windows):
    pyinstaller --noconfirm packaging/pyinstaller-onefile.spec
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

APP_NAME = "IDPhotoAutoCropper"

project_root = Path(SPECPATH).resolve().parent

datas = [
    (str(project_root / "models"), "models"),
    (str(project_root / "assets"), "assets"),
]
binaries = []
hiddenimports = []

for package in ("mediapipe",):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

for package in ("flet_desktop", "flet_desktop_light"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "IPython", "pytest", "jax", "jaxlib", "scipy", "ml_dtypes"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project_root / "assets" / "icon.ico") if sys.platform == "win32" else None,
)
