from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from admin_dashboard.dashboard import DashboardController
from admin_dashboard.fixture_readers import FixtureReaders
from admin_dashboard.recovery_contracts import (
    validate_daily_recovery, validate_data_library,
)
from admin_dashboard.recovery_readers import RecoveryProjectionReaders
from admin_dashboard.render import render_dashboard

ROOT = Path(__file__).parent / "fixtures" / "data-lifecycle"


class AdminRecoveryProjectionTests(unittest.TestCase):
    def test_fixture_sections_validate_and_render(self):
        readers = FixtureReaders(ROOT)
        daily = readers.daily_recovery()
        library = readers.data_library()
        self.assertEqual(daily["youtube"]["search_calls"], 0)
        self.assertEqual(daily["ptt"]["state"], "VERIFIED_COMPLETE")
        self.assertEqual(library["row_count"], 3)
        self.assertEqual(library["rows"][0]["transcript"]["status"], "READY")

        html = render_dashboard()
        for marker in (
            'data-tab="daily_recovery"',
            'data-tab="data_library"',
            'id="recovery-rows"',
            'id="library-rows"',
            'id="library-search"',
            'id="library-channel"',
            'id="library-lifecycle"',
            'id="library-transcript"',
            'id="library-translation"',
        ):
            self.assertIn(marker, html)
        for forbidden in (
            "Retry Recovery", "Retry Transcript", "Retry Translation",
            "Repair Video", "Delete Artifact", "Deploy Recovery",
        ):
            self.assertNotIn(forbidden, html)

    def test_refresh_all_contains_both_new_sections(self):
        fixture = json.loads((ROOT / "admin-ui-coverage.sanitized.json").read_text())
        readers = FixtureReaders(
            ROOT, days=fixture["days"],
            start_day=fixture["from_day"], end_day=fixture["through_day"])
        result = DashboardController(readers.injected(), cooldown_seconds=0).refresh()
        self.assertEqual(result["daily_recovery"]["availability"], "available")
        self.assertEqual(result["data_library"]["availability"], "available")
        self.assertEqual(result["daily_recovery"]["payload"]["schema_version"],
                         "holoviewer-admin-daily-recovery-v1")
        self.assertEqual(result["data_library"]["payload"]["schema_version"],
                         "holoviewer-authoritative-data-library-v1")

    def test_daily_recovery_rejects_unbounded_or_nonzero_search_shape(self):
        value = json.loads((ROOT / "daily-recovery.sanitized.json").read_text())
        value["youtube"]["unresolved_video_ids"] = ["not a video id"]
        with self.assertRaises(ValueError):
            validate_daily_recovery(value)

    def test_library_rejects_duplicate_video_identity(self):
        value = json.loads((ROOT / "data-library.sanitized.json").read_text())
        value["rows"].append(dict(value["rows"][0]))
        value["row_count"] += 1
        with self.assertRaises(ValueError):
            validate_data_library(value)

    def test_host_projection_reader_uses_fixed_files_only(self):
        daily = (ROOT / "daily-recovery.sanitized.json").read_text()
        library = (ROOT / "data-library.sanitized.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily-recovery.json").write_text(daily)
            (root / "data-library.json").write_text(library)
            readers = RecoveryProjectionReaders(root)
            self.assertEqual(readers.daily_recovery()["youtube"]["playlist_calls"], 66)
            self.assertEqual(readers.data_library()["row_count"], 3)
            self.assertEqual(set(readers.injected()), {"daily_recovery", "data_library"})

    def test_browser_contract_contains_no_author_or_content_fields(self):
        library = validate_data_library(
            json.loads((ROOT / "data-library.sanitized.json").read_text()))
        encoded = json.dumps(library).lower()
        self.assertNotIn('"author"', encoded)
        self.assertNotIn('"content"', encoded)
        self.assertNotIn("transcript text", encoded)
        self.assertNotIn("/users/", encoded)


if __name__ == "__main__":
    unittest.main()
