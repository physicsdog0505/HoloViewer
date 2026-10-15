"""Contract-bound #68 consumer proof with injected #47/#48 router responses.

This tests the *consumer*, not an independently invented backend Worker.
The injected async callback stands in for the owner-owned canonical router
read endpoints. No D1 writes, second API implementation, or network traffic.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor" / "4174-a144bb3"))
from client_home import HomeStream  # noqa: E402

from platform_adapter.product_bindings import bind_home_reader, bind_history_reader
from platform_adapter.public_api import (
    PublicAPI, PublicAPIUnavailable, DEFAULT_API, preloaded_public_reads,
)
from platform_adapter.worker_preload import preload_for_accepted_request


TODAY = {
    "schema_version": "public-consumer-v1",
    "freshness": {"status": "fresh"},
    "completeness": {"status": "partial"},
    "gap": True,
    "streams": [
        {
            "video_id": "dQw4w9WgXcQ",
            "title": "Canonical live test fixture",
            "channel_name": "Contract Fixture",
            "channel_id": "UCexample",
            "lifecycle_state": "live",
            "group": "hololive",
            "scheduled_start": "2026-10-15T10:00:00Z",
        },
        {
            "video_id": "9bZkp7q19f0",
            "title": "Canonical waiting test fixture",
            "channel_name": "Contract Fixture",
            "lifecycle_state": "waiting",
            "group": "hololive",
        },
    ],
}
HISTORY = {
    "items": [
        {"video_id": "9bZkp7q19f0", "title": "Archive fixture",
         "lifecycle_state": "ended", "group": "hololive"}
    ],
    "has_more": False,
}


class CanonicalReadStub:
    """Injected read-only router response seam; not a backend implementation."""
    def __init__(self, today=None, history=None):
        self.today = TODAY if today is None else today
        self.history = HISTORY if history is None else history
        self.urls = []

    async def get_json(self, url):
        self.urls.append(url)
        if url == DEFAULT_API + "/v1/catalog/today":
            return self.today
        if url.startswith(DEFAULT_API + "/v1/history?"):
            return self.history
        raise AssertionError("Unexpected canonical consumer read: " + url)


class ConsumerIntegrationTest(unittest.TestCase):
    def test_worker_preload_to_original_home_stream_contract(self):
        router = CanonicalReadStub()
        preload = asyncio.run(preload_for_accepted_request("/", router.get_json))
        with preloaded_public_reads(preload):
            live, upcoming, ended, unknown = bind_home_reader(
                PublicAPI(), HomeStream
            )()
        self.assertEqual(len(router.urls), 1)
        self.assertEqual((len(live), len(upcoming), len(ended), len(unknown)),
                         (1, 1, 0, 0))
        self.assertIsInstance(live[0], HomeStream)
        self.assertEqual(live[0].state, "live")
        self.assertEqual(live[0].start_label, "18:00")  # 10:00 UTC -> Taipei
        self.assertEqual(upcoming[0].state, "waiting")
        self.assertEqual(router.urls[0], DEFAULT_API + "/v1/catalog/today")

    def test_partial_gap_does_not_create_false_completeness(self):
        self.assertEqual(TODAY["completeness"]["status"], "partial")
        self.assertTrue(TODAY["gap"])
        stale = {**TODAY, "freshness": {"status": "stale"}}
        router = CanonicalReadStub(today=stale)
        preload = asyncio.run(
            preload_for_accepted_request("/api/home", router.get_json)
        )
        with preloaded_public_reads(preload):
            live, upcoming, ended, unknown = bind_home_reader(
                PublicAPI(), HomeStream
            )()
        self.assertEqual(live, [])
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0].state, "unknown")
        self.assertEqual(len(upcoming), 1)

    def test_canonical_history_page_21_reaches_accepted_history_reader(self):
        from datetime import datetime
        from frontend_time import TAIPEI
        from client_history import history_day_bounds

        _, day = history_day_bounds(datetime.now(TAIPEI))
        router = CanonicalReadStub()
        preload = asyncio.run(preload_for_accepted_request(
            "/history?date=" + day.isoformat() + "&page=21",
            router.get_json,
        ))
        with preloaded_public_reads(preload):
            cards, has_more = bind_history_reader(PublicAPI(), HomeStream)(
                day, page=21
            )
        self.assertEqual(len(cards), 1)
        self.assertIsInstance(cards[0], HomeStream)
        self.assertFalse(has_more)
        self.assertEqual(parse_qs(urlsplit(router.urls[0]).query)["offset"], ["1000"])

    def test_no_unmounted_ptt_fallback(self):
        with preloaded_public_reads({}):
            with self.assertRaises(PublicAPIUnavailable):
                PublicAPI().read_today()

    def test_provider_origin_remains_canonical(self):
        router = CanonicalReadStub()
        preload = asyncio.run(
            preload_for_accepted_request("/api/home", router.get_json)
        )
        self.assertEqual(list(preload), [("/v1/catalog/today", ())])
        with self.assertRaises(ValueError):
            PublicAPI("https://unreviewed-router.example")


if __name__ == "__main__":
    unittest.main()
