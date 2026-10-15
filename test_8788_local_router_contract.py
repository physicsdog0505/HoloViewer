"""Loopback-only #68 consumer canary; never calls real API or D1."""
import unittest
from unittest.mock import patch

from platform_adapter.public_api import PublicAPIUnavailable
from tools.check_8788_local_router_contract import checked_local_origin, consumer_receipt


class LoopbackCanaryTest(unittest.TestCase):
    def test_reject_nonlocal_redirectable_origins(self):
        for origin in (
            "https://holoviewer-public-api.singlebagel.workers.dev",
            "http://example.com:8787", "http://127.0.0.1:8787/extra",
            "http://127.0.0.1:8787@evil.test", "http://localhost",
            "http://127.0.0.1:8787/?secret=1"
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                checked_local_origin(origin)
        self.assertEqual(checked_local_origin("http://127.0.0.1:8787"),
                         "http://127.0.0.1:8787")

    def test_consumes_owner_canonical_today_without_backend_reimplementation(self):
        today = {
            "schema_version": "public-consumer-v1",
            "freshness": {"status": "fresh"},
            "completeness": {"status": "partial", "gap": True},
            "streams": [{
                "video_id": "dQw4w9WgXcQ",
                "title": "Contract fixture",
                "channel_name": "Fixture",
                "lifecycle_state": "waiting",
                "group": "hololive"
            }],
        }
        with patch("tools.check_8788_local_router_contract.read_json",
                   return_value=(200, today)) as read:
            receipt = consumer_receipt("http://127.0.0.1:8787")
        self.assertEqual(read.call_args.args[1], "/v1/catalog/today")
        self.assertEqual(receipt["canonical_today"]["visible_groups"], [0, 1, 0, 0])
        self.assertFalse(receipt["ptt_mount_checked"])
        self.assertEqual(receipt["d1_write_count"], 0)

    def test_missing_canonical_today_is_not_legacy_fallback(self):
        with patch("tools.check_8788_local_router_contract.read_json",
                   return_value=(404, {"error": "not mounted"})):
            with self.assertRaises(PublicAPIUnavailable):
                consumer_receipt("http://localhost:8787")


if __name__ == "__main__":
    unittest.main()
