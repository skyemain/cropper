#!/usr/bin/env bash
# Flet GUI in web mode for Cloud Agent preview (port 8619).
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"
exec .venv/bin/python main.py --web --host 127.0.0.1 --port 8619
