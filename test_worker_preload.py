"""Deterministic no-network tests for Worker request-local API preloading."""
import unittest

from platform_adapter.public_api import (
    PublicAPI, PublicAPIUnavailable, preloaded_public_reads,
)


class RequestLocalProviderTest(unittest.TestCase):
    def test_preloaded_today_never_reaches_urllib(self):
        data = {"freshness": {"status": "fresh"}, "streams": []}
        with preloaded_public_reads({("/v1/catalog/today", ()): data}):
            self.assertEqual(PublicAPI().read_today(), data)

    def test_absent_preload_fails_closed_without_fallback(self):
        with preloaded_public_reads({}):
            with self.assertRaises(PublicAPIUnavailable):
                PublicAPI().read_today()

    def test_history_key_includes_day_limit_offset(self):
        from datetime import date
        params = (("day", "2026-10-15"), ("limit", "50"), ("offset", "0"))
        payload = {"items": [], "has_more": False}
        with preloaded_public_reads({("/v1/history", params): payload}):
            self.assertEqual(
                PublicAPI().read_day(date(2026, 10, 15))["items"], []
            )
            with self.assertRaises(PublicAPIUnavailable):
                PublicAPI().read_day(date(2026, 10, 14))

    def test_nested_preloads_do_not_leak_across_request_scope(self):
        parent = {"streams": [], "freshness": {"status": "unknown"}}
        child = {"streams": [], "freshness": {"status": "fresh"}}
        key = ("/v1/catalog/today", ())
        with preloaded_public_reads({key: parent}):
            with preloaded_public_reads({key: child}):
                self.assertIs(PublicAPI().read_today(), child)
            self.assertIs(PublicAPI().read_today(), parent)


if __name__ == "__main__":
    unittest.main()
