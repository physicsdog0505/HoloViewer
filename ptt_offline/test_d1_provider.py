"""Regression for D1 provider's selected Taipei day + AID binding."""
import sqlite3
import unittest
from pathlib import Path
from ptt_offline.d1_publisher import publish_batch
from ptt_offline.d1_provider import D1PttProvider
from ptt_offline.public_today_contract import ContractError


class D1ProviderScopeTests(unittest.TestCase):
    def test_same_aid_cross_midnight_is_day_scoped(self):
        db = sqlite3.connect(":memory:")
        db.executescript((Path(__file__).with_name("d1_migrations") /
                          "0001_canonical_ptt.sql").read_text())
        def push(line, occurred):
            return dict(aid="A1", source_line=line, kind="推", author="tester",
                        content=f"row-{line}", occurred_at=occurred, origin="collector")
        publish_batch(db, "2026-10-15", {"A1"},
                      [push(1, "2026-10-15T23:59:59+08:00")])
        publish_batch(db, "2026-10-16", {"A1"},
                      [push(2, "2026-10-16T00:00:01+08:00")])
        provider = D1PttProvider(db, day="2026-10-15")
        visible = provider.initial_window("A1", limit=300)
        self.assertEqual(len(visible.pushes), 1)
        self.assertEqual(visible.pushes[0]["source_line"], 1)
        self.assertEqual(provider.aids_for_day("2026-10-15"), {"A1"})
        with self.assertRaises(ContractError):
            provider.snapshot_for_day("2026-10-16")
        db.close()


if __name__ == "__main__":
    unittest.main()
