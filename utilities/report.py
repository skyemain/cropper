"""CSV processing report.

One row per image with the QA measurements requested for the workflow.
Only geometric/quality measurements are stored - no biometric templates.
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path

REPORT_COLUMNS = [
    "filename",
    "source_path",
    "output_path",
    "status",
    "face_count",
    "rotation_degrees",
    "eye_distance_pixels",
    "eye_distance_ratio",
    "blur_score",
    "detection_confidence",
    "processing_time",
    "reason",
]


class ReportBook:
    """In-memory report merged with any previous report, rewritten to disk.

    Keeping the whole table in memory is cheap (a few thousand small rows)
    and lets a "Continue / Skip Existing" run preserve the measurements from
    the run that actually produced each file.
    """

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path)
        self._rows: dict[str, dict[str, str]] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        if self.csv_path.exists():
            try:
                for row in load_report(self.csv_path):
                    self._insert(row)
            except (OSError, csv.Error):
                # A corrupt/locked old report should never block processing.
                self._rows.clear()
                self._order.clear()

    def _insert(self, row: dict[str, str]) -> None:
        name = row.get("filename", "")
        if not name:
            return
        if name not in self._rows:
            self._order.append(name)
        self._rows[name] = {col: str(row.get(col, "")) for col in REPORT_COLUMNS}

    def has_row(self, filename: str) -> bool:
        with self._lock:
            return filename in self._rows

    def set_row(self, row: dict[str, object]) -> None:
        with self._lock:
            self._insert({k: str(v) for k, v in row.items()})

    def update_row(self, filename: str, updates: dict[str, object]) -> None:
        with self._lock:
            existing = self._rows.get(filename)
            if existing is None:
                return
            for key, value in updates.items():
                if key in REPORT_COLUMNS:
                    existing[key] = str(value)

    def rows(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(self._rows[name]) for name in self._order]

    def save(self) -> None:
        with self._lock:
            tmp = self.csv_path.with_name(self.csv_path.name + ".part")
            with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS)
                writer.writeheader()
                for name in self._order:
                    writer.writerow(self._rows[name])
            tmp.replace(self.csv_path)


def load_report(csv_path: Path) -> list[dict[str, str]]:
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as fh:
        return [dict(row) for row in csv.DictReader(fh)]
