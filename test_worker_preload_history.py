"""Real accepted History validation boundary for async Worker prefetch."""
import asyncio
from datetime import datetime
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor" / "4174-a144bb3"))

from client_history import history_day_bounds  # noqa: E402
from frontend_time import TAIPEI  # noqa: E402
from platform_adapter.worker_preload import preload_for_accepted_request  # noqa: E402


class HistoryPreloadParityTest(unittest.TestCase):
    def test_accepted_page_range_is_not_narrowed_by_transport(self):
        _, latest = history_day_bounds(datetime.now(TAIPEI))
        day = latest.isoformat()
        calls = []

        async def fake_get(url):
            calls.append(url)
            return {"items": [], "has_more": False}

        for page, expected_offset in [(21, "1000"), (10000, "499950")]:
            calls.clear()
            mapping = asyncio.run(preload_for_accepted_request(
                f"/history?date={day}&page={page}", fake_get
            ))
            self.assertEqual(len(calls), 1)
            query = parse_qs(urlsplit(calls[0]).query)
            self.assertEqual(query["offset"], [expected_offset])
            self.assertEqual(query["day"], [day])
            self.assertEqual(len(mapping), 1)

        calls.clear()
        mapping = asyncio.run(preload_for_accepted_request(
            f"/history?date={day}&page=10001", fake_get
        ))
        self.assertEqual(mapping, {})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
