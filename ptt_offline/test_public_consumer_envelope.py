"""Isolated #48 public consumer boundary regressions."""
import unittest

from ptt_offline.public_today_contract import (
    ContractError, SourceUnavailable, PttConsumerReader,
    SyntheticPttProvider, PUBLIC_PUSH_FIELDS,
)


def post(n, **extra):
    return dict(aid="A1", source_line=n, floor=None, author="viewer",
                content=f"message {n}", occurred_at="2026-10-15T03:00:00+08:00",
                kind="推", **extra)


class PublicConsumerEnvelopeTests(unittest.TestCase):
    def provider(self, rows):
        return SyntheticPttProvider(
            {"2026-10-15": {"A1"}},
            snapshots={"2026-10-15": rows},
            relay_rows={"A1": []},
            checked_at="2026-10-14T19:00:00Z",
        )

    def test_strips_backend_fields_on_both_readers(self):
        provider = self.provider([post(1, cursor=2, origin="web", internal_secret="never")])
        reader = PttConsumerReader(provider, clock=lambda: "2026-10-14T19:00:02Z")
        today = reader.read_today("2026-10-15")
        history = reader.read_history("2026-10-15", {"limit": 5})
        for result in (today, history):
            self.assertEqual(result.schema_version, "public-consumer-v1")
            self.assertEqual(set(result.pushes[0]), set(PUBLIC_PUSH_FIELDS))
            self.assertNotIn("cursor", result.pushes[0])
            self.assertNotIn("origin", result.pushes[0])
            self.assertNotIn("internal_secret", result.pushes[0])
            self.assertIn("last_success_at", result.freshness)
            self.assertIn("gap", result.completeness)
            self.assertTrue(result.as_of)

    def test_ttl_and_repeated_no_checkpoint_read_ages(self):
        current = ["2026-10-14T19:00:02Z"]
        reader = PttConsumerReader(self.provider([post(1)]), clock=lambda: current[0])
        first = reader.read_today("2026-10-15")
        self.assertEqual(first.freshness["status"], "fresh")
        current[0] = "2026-10-14T19:01:00Z"
        second = reader.read_today("2026-10-15")
        self.assertEqual(second.freshness["status"], "stale")

    def test_future_check_fails_closed(self):
        reader = PttConsumerReader(self.provider([post(1)]),
                                   clock=lambda: "2026-10-14T18:59:00Z")
        self.assertEqual(reader.read_today("2026-10-15").freshness["status"], "unknown")

    def test_kind_and_safe_url(self):
        valid = "https://www.ptt.cc/bbs/C_Chat/M.1234567890.A.ABC.html"
        evil = "https://evil.test/bbs/C_Chat/M.1234567890.A.ABC.html"
        rows = [post(1, source_url=valid), post(2, source_url=evil)]
        reader = PttConsumerReader(self.provider(rows))
        output = reader.read_history("2026-10-15", {"limit": 20})
        self.assertEqual(output.pushes[0]["kind"], "推")
        self.assertEqual(output.pushes[0]["source_url"], valid)
        self.assertIsNone(output.pushes[1]["source_url"])

    def test_invalid_kind_rejected(self):
        reader = PttConsumerReader(self.provider([post(1, kind="malformed")]))
        with self.assertRaises(ContractError):
            reader.read_history("2026-10-15", {})

    def test_verified_empty_is_not_unavailable(self):
        reader = PttConsumerReader(self.provider([]))
        today = reader.read_today("2026-10-15")
        self.assertEqual(today.pushes, [])
        self.assertFalse(today.completeness["gap"])
        self.assertEqual(today.completeness["status"], "partial")

    def test_unresolved_day_is_typed_unavailable(self):
        reader = PttConsumerReader(SyntheticPttProvider({}))
        with self.assertRaises(SourceUnavailable):
            reader.read_today("2026-10-15")
        with self.assertRaises(SourceUnavailable):
            reader.read_history("2026-10-15", {})


if __name__ == "__main__":
    unittest.main()
