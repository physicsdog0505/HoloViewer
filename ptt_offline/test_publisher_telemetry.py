import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.publisher_telemetry import update_publisher_telemetry


class PublisherTelemetryTests(unittest.TestCase):
    def test_persists_sanitized_durable_success_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"publisher-telemetry.json"
            first=update_publisher_telemetry(path,{
                "status":"ACK","sent":3,"eligible":3,"http_posts":1,
                "articles_checked":4,"stale_fenced_rows":0,
                "observed_at":"2026-10-20T05:30:00+00:00",
            })
            second=update_publisher_telemetry(path,{
                "status":"NO_NEW_ROWS","sent":0,"eligible":0,"http_posts":0,
                "articles_checked":4,"stale_fenced_rows":0,
                "observed_at":"2026-10-20T05:31:00+00:00",
            })
            persisted=json.loads(path.read_text(encoding="utf-8"))

        item=second["components"]["Publisher"]
        self.assertEqual(first["components"]["Publisher"]["attempt_count"],1)
        self.assertEqual(item["attempt_count"],2)
        self.assertEqual(item["last_attempted_at"],"2026-10-20T05:31:00+00:00")
        self.assertEqual(item["last_successful_at"],"2026-10-20T05:31:00+00:00")
        self.assertEqual(item["published_count"],0)
        self.assertIsNone(item["retry_after"])
        self.assertIsNone(item["backoff_seconds"])
        self.assertFalse(item["error_sanitized"])
        self.assertEqual(persisted,second)

    def test_failure_exposes_only_error_class_not_message(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"publisher-telemetry.json"
            body=update_publisher_telemetry(path,{
                "status":"STOP_RECONCILE","error_class":"ContractError",
                "remote_outcome":"UNKNOWN_NO_RETRY",
                "observed_at":"2026-10-20T05:32:00+00:00",
            })
        item=body["components"]["Publisher"]
        self.assertEqual(item["status"],"failed")
        self.assertEqual(item["error_code"],"ContractError")
        self.assertIsNone(item["error_message"])
        self.assertFalse(item["error_sanitized"])


if __name__=="__main__":
    unittest.main()
