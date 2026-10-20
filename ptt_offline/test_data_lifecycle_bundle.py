from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.data_lifecycle_bundle import build_bundle, main


FIXTURE=Path(__file__).parent/"fixtures"/"data_lifecycle"/"ptt_complete_day.json"


class DataLifecycleBundleTests(unittest.TestCase):
    def test_fixture_builds_complete_read_only_bundle(self):
        raw=json.loads(FIXTURE.read_text(encoding="utf-8"))
        body=build_bundle(raw)
        self.assertEqual(body["schema_version"],"holoviewer-ptt-data-lifecycle-bundle-v1")
        self.assertTrue(body["sanitized"])
        self.assertEqual(body["expected_aids"]["status"],"COMPLETE")
        self.assertEqual(body["source_coverage"]["status"],"COMPLETE")
        self.assertEqual(
            body["system_health"]["components"]["Collector"]["semantic_check"]["status"],
            "healthy",
        )
        publisher=body["job_telemetry"]["components"]["Publisher"]
        self.assertEqual(publisher["published_count"],1)
        self.assertEqual(publisher["verified_count"],1)
        self.assertEqual(publisher["contract_gaps"],[
            "publisher-backoff-unavailable",
            "publisher-retry-after-unavailable",
        ])
        self.assertEqual(body["contract_gaps"],[
            "publisher-backoff-unavailable",
            "publisher-retry-after-unavailable",
        ])

    def test_partial_bundle_preserves_unknowns_and_contract_gaps(self):
        raw={
            "expected_aids":{"day":"2026-10-20","entries":[],"authority":{}},
            "coverage":{"day":"2026-10-20","aid":"1fixture","article_start_line":1,
                        "final_source_line":None,"lines":[]},
            "publisher":{"status":"NO_NEW_ROWS","observed_at":"2026-10-20T06:00:00Z",
                         "sent":0,"http_posts":0},
            "collector":{},
        }
        body=build_bundle(raw)
        self.assertEqual(body["expected_aids"]["status"],"UNKNOWN")
        self.assertEqual(body["source_coverage"]["status"],"REPAIR_NEEDED")
        self.assertEqual(
            body["system_health"]["components"]["Collector"]["semantic_check"]["status"],
            "unknown",
        )
        self.assertIn("expected-day-aid-missing",body["contract_gaps"])
        self.assertIn("final-source-line-unavailable",body["contract_gaps"])
        self.assertIn("publisher-independent-readback-unavailable",body["contract_gaps"])
        self.assertIn("collector-watermark-unavailable",body["contract_gaps"])

    def test_cli_writes_new_sanitized_file_only(self):
        raw=json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            inp=Path(d)/"input.json"
            out=Path(d)/"bundle.json"
            inp.write_text(json.dumps(raw),encoding="utf-8")
            main(["--input",str(inp),"--out",str(out)])
            body=json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(body["sanitized"])
            with self.assertRaises(FileExistsError):
                main(["--input",str(inp),"--out",str(out)])


if __name__=="__main__":
    unittest.main()
