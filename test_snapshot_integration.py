import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_lifecycle.adapters import adapt_contract_snapshot
from data_lifecycle.common import content_hash
from data_lifecycle.inventory import build_inventory
from data_lifecycle.planner import build_sync_plan
from data_lifecycle.report import build_reconciliation_report
from data_lifecycle.cli import main

ROOT = Path(__file__).parent / "fixtures" / "data-lifecycle"


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class SnapshotIntegrationTests(unittest.TestCase):
    @staticmethod
    def verify_fixture_authority(value):
        return value.get("issuer") == "offline-test-only" and value.get("version") == "contract-fixture-authority-v1"

    def reconcile(self, day, filename):
        snapshot = adapt_contract_snapshot(day, load(filename), authority_verifier=self.verify_fixture_authority)
        inventory = build_inventory(day, snapshot)
        plans = [build_sync_plan(source, snapshot[source]["rows"], snapshot[source]["target_rows"],
                                 upstream_available=snapshot[source]["available"])
                 for source in ("youtube", "ptt")]
        return snapshot, inventory, plans, build_reconciliation_report(inventory, plans)

    def test_recent_youtube_contract_date_complete_source_target_missing(self):
        _, inventory, plans, report = self.reconcile("2026-10-15", "youtube-2026-10-15.sanitized.json")
        youtube = inventory["sources"][0]
        self.assertEqual(youtube["completeness_status"], "COMPLETE")
        self.assertEqual(youtube["actual_set"], ["8pF4qHcshDc"])
        self.assertEqual(plans[0]["actions"][0]["action"], "INSERT")
        self.assertEqual(report["recommended_actions"][0]["identity"], "8pF4qHcshDc")

    def test_recent_ptt_contract_date_complete_and_empty_content_valid(self):
        _, inventory, plans, _ = self.reconcile("2026-10-01", "ptt-2026-10-01.sanitized.json")
        ptt = inventory["sources"][1]
        self.assertEqual(ptt["completeness_status"], "COMPLETE")
        self.assertEqual(ptt["source_line_gaps"], {})
        self.assertEqual([a["action"] for a in plans[1]["actions"]], ["INSERT", "INSERT"])

    def test_incomplete_source_never_becomes_complete(self):
        raw = load("youtube-2026-10-15.sanitized.json")
        raw["youtube"]["expected_video_ids"].append("missingVid1")
        snapshot = adapt_contract_snapshot("2026-10-15", raw, authority_verifier=self.verify_fixture_authority)
        item = build_inventory("2026-10-15", snapshot)["sources"][0]
        self.assertEqual(item["completeness_status"], "REPAIR_NEEDED")
        self.assertEqual(item["missing_ids"], ["missingVid1"])

    def test_revision_conflict_against_sanitized_target(self):
        raw = load("youtube-2026-10-15.sanitized.json")
        raw["youtube"]["target"] = {"sanitized": True, "rows": [{
            "video_id": "8pF4qHcshDc", "revision": 1,
            "observed_at": "2026-10-17T00:00:00Z", "content_hash": content_hash("different")}]}
        snapshot = adapt_contract_snapshot("2026-10-15", raw, authority_verifier=self.verify_fixture_authority)
        action = build_sync_plan("youtube", snapshot["youtube"]["rows"],
                                 snapshot["youtube"]["target_rows"])["actions"][0]
        self.assertEqual((action["action"], action["reason"]), ("CONFLICT", "target-newer-than-source"))

    def test_snapshots_are_explicitly_sanitized_and_contain_no_credentials(self):
        for path in ROOT.glob("*.json"):
            raw = path.read_text(encoding="utf-8").lower()
            for forbidden in ("api_key", "authorization", "cookie", "password", "secret"):
                self.assertNotIn(forbidden, raw)

    def test_cli_cannot_promote_fixture_authority(self):
        source = ROOT / "youtube-2026-10-15.sanitized.json"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            md = Path(tmp) / "out.md"
            argv = ["cli", "--contract-export", "--date", "2026-10-15", "--snapshot", str(source),
                    "--json-out", str(out), "--markdown-out", str(md)]
            with patch("sys.argv", argv):
                self.assertEqual(main(), 0)
            result = json.loads(out.read_text())
            self.assertEqual(result["inventory"]["sources"][0]["completeness_status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
