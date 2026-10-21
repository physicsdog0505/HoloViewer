"""Host-fixed read-only readers for authoritative recovery projections.

Paths are supplied only by trusted host configuration. Browser requests cannot
select or override files.
"""
from __future__ import annotations

import json
from pathlib import Path

from .recovery_contracts import validate_daily_recovery, validate_data_library


class RecoveryProjectionReaders:
    def __init__(self, root: str | Path):
        path = Path(root).expanduser().resolve(strict=True)
        if not path.is_dir() or path.is_symlink():
            raise ValueError("trusted recovery projection directory required")
        self._root = path

    def _load(self, filename: str) -> dict:
        path = self._root / filename
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("recovery projection unavailable")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("recovery projection object required")
        return value

    def daily_recovery(self):
        return validate_daily_recovery(self._load("daily-recovery.json"))

    def data_library(self):
        return validate_data_library(self._load("data-library.json"))

    def injected(self):
        return {
            "daily_recovery": self.daily_recovery,
            "data_library": self.data_library,
        }


def merge_reader_sets(*sets: dict) -> dict:
    result = {}
    for values in sets:
        if not isinstance(values, dict):
            raise ValueError("reader set must be a dict")
        overlap = set(result) & set(values)
        if overlap:
            raise ValueError("duplicate dashboard readers: " + ",".join(sorted(overlap)))
        result.update(values)
    return result
