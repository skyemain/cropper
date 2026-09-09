#!/usr/bin/env bash
# Idempotent Cloud Agent install for ID Photo Auto Cropper.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

echo "[install] Repository: $ROOT"

if [[ ! -d .venv ]]; then
  echo "[install] Creating virtual environment..."
  python3 -m venv .venv
fi

echo "[install] Installing Python dependencies..."
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/pip install -r requirements-dev.txt -q

echo "[install] Verifying bundled MediaPipe models..."
test -f models/face_landmarker.task
test -f models/blaze_face_short_range.tflite
test -f assets/icon.ico

echo "[install] Running pipeline selftest..."
.venv/bin/python main.py --selftest

echo "[install] Done."
