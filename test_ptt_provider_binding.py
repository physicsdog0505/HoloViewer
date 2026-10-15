"""#68 #48 Public reader contract matrix: no actual API Router is cloned."""
import asyncio
import unittest

from platform_adapter.ptt_provider import PttPublicReader
from platform_adapter.public_api import DEFAULT_API, PublicAPIUnavailable


def envelope(*, status="fresh", gap=False):
    return {
        "schema_version": "public-consumer-v1",
        "day": "2026-10-15",
        "as_of": "2026-10-15T10:00:00Z",
        "freshness": {"status": status, "last_success_at": None},
        "completeness": {"status": "partial", "gap": gap},
        "checkpoint": "opaque-snapshot",
        "pushes": [],
        "page": {"limit": 50, "has_more": False, "next_checkpoint": None},
    }


class PttProviderBindingTest(unittest.TestCase):
    def test_disabled_by_default_never_calls_transport(self):
        touched = []
        async def fetch(url):
            touched.append(url)
            raise AssertionError("Disabled reader must not fetch")
        reader = PttPublicReader()
        for method in (reader.read_today, reader.read_history):
            with self.assertRaises(PublicAPIUnavailable):
                asyncio.run(method("2026-10-15", fetch))
        self.assertEqual(touched, [])

    def test_fresh_stale_unknown_gap_matrix(self):
        for state in ("fresh", "stale", "unknown"):
            for gap in (True, False):
                with self.subTest(state=state, gap=gap):
                    called = []
                    data = envelope(status=state, gap=gap)
                    async def fetch(url):
                        called.append(url)
                        return data
                    actual = asyncio.run(PttPublicReader(enabled=True).read_today(
                        "2026-10-15", fetch,
                    ))
                    self.assertIs(actual, data)
                    self.assertEqual(actual["freshness"]["status"], state)
                    self.assertIs(actual["completeness"]["gap"], gap)
                    self.assertEqual(called, [
                        DEFAULT_API + "/v1/ptt/today?day=2026-10-15"
                    ])

    def test_history_checkpoint_preserved_opaque(self):
        calls = []
        async def fetch(url):
            calls.append(url)
            result = envelope()
            result["page"]["limit"] = 200
            result["page"]["next_checkpoint"] = "opaque-next"
            return result
        data = asyncio.run(PttPublicReader(enabled=True).read_history(
            "2026-10-15", fetch, checkpoint="opaque:/+?=token", limit=200,
        ))
        self.assertEqual(data["page"]["next_checkpoint"], "opaque-next")
        self.assertIn("checkpoint=opaque%3A%2F%2B%3F%3Dtoken", calls[0])
        self.assertIn("limit=200", calls[0])

    def test_invalid_envelopes_and_private_fields_fail_closed(self):
        invalid = [
            None, {}, {"pushes": []},
            {**envelope(), "freshness": {"state": "fresh"}},
            {**envelope(), "completeness": {"status": "partial"}},
            {**envelope(), "day": "2026-10-14"},
        ]
        for data in invalid:
            async def fetch(_url):
                return data
            with self.subTest(data=data), self.assertRaises(PublicAPIUnavailable):
                asyncio.run(PttPublicReader(enabled=True).read_today(
                    "2026-10-15", fetch
                ))

    def test_internal_push_fields_rejected(self):
        push = dict(
            push_id="ptt:v1:" + "a" * 64,
            aid="M.1234567890.A.ABC", source_line=1,
            kind="推", author="viewer", content="x",
            occurred_at="2026-10-15T10:00:00Z",
            floor=1, source_url=None,
        )
        for secret_key in ("cursor", "origin"):
            doc = envelope()
            doc["pushes"] = [{**push, secret_key: "private"}]
            async def fetch(_url):
                return doc
            with self.subTest(key=secret_key), self.assertRaises(PublicAPIUnavailable):
                asyncio.run(PttPublicReader(enabled=True).read_today(
                    "2026-10-15", fetch,
                ))

    def test_invalid_history_limit_or_checkpoint(self):
        async def fetch(_url):
            raise AssertionError("Invalid request must not fetch")
        for limit in (0, 201, -1, True, "50"):
            with self.assertRaises(ValueError):
                asyncio.run(PttPublicReader(enabled=True).read_history(
                    "2026-10-15", fetch, limit=limit
                ))
        with self.assertRaises(ValueError):
            asyncio.run(PttPublicReader(enabled=True).read_history(
                "2026-10-15", fetch, checkpoint=""
            ))


if __name__ == "__main__":
    unittest.main()
