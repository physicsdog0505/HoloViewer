"""Offline D1-compatible schema and replay regression tests for Issue #48."""
import sqlite3
import unittest
from pathlib import Path

from ptt_offline.d1_publisher import publish_batch, publish_provider_state, close_verified_gap, read_day
from ptt_offline.public_today_contract import ContractError, canonical_id


def record(i, **changes):
    r = dict(aid="A1", source_line=i, kind="推", author="tester",
             content=f"hello-{i}", occurred_at="2026-10-15T03:00:00+08:00",
             floor=None, origin="web",
             source_record_key=f"raw:{i}")
    r.update(changes)
    return r


class D1PublisherTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        path = Path(__file__).with_name("d1_migrations") / "0001_canonical_ptt.sql"
        schema = path.read_text(encoding="utf-8")
        self.db.executescript(schema)
        self.db.executescript(schema)

    def tearDown(self):
        self.db.close()

    def test_replay_and_collector_precedence(self):
        initial = record(1)
        self.assertEqual(publish_batch(self.db, "2026-10-15", {"A1"}, [initial]), 1)
        publish_batch(self.db, "2026-10-15", {"A1"}, [initial])
        enriched = record(1, origin="collector", floor=45)
        publish_batch(self.db, "2026-10-15", {"A1"}, [enriched])
        publish_batch(self.db, "2026-10-15", {"A1"}, [initial])
        aids, rows = read_day(self.db, "2026-10-15")
        self.assertEqual(aids, {"A1"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["push_id"], canonical_id(initial))
        self.assertEqual(rows[0]["floor"], 45)

    def test_day_aid_source_order_and_forward_repair(self):
        publish_batch(self.db, "2026-10-15", {"A1", "A2"},
                      [record(2, aid="A2"), record(1, aid="A1")])
        aids, rows = read_day(self.db, "2026-10-15")
        self.assertEqual(aids, {"A1", "A2"})
        self.assertEqual([(r["aid"], r["source_line"]) for r in rows],
                         [("A1", 1), ("A2", 2)])
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM public_ptt_schema_migrations").fetchone()[0], 1)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM ptt_source_evidence").fetchone()[0], 2)

    def test_failed_batch_no_partial_write(self):
        with self.assertRaises(ContractError):
            publish_batch(self.db, "2026-10-15", {"A1"},
                          [record(1), record(2, aid="A2")])
        self.assertEqual(read_day(self.db, "2026-10-15"), (set(), []))

    def test_identity_correction_with_stable_source_key_fails_closed(self):
        original = record(1)
        publish_batch(self.db, "2026-10-15", {"A1"}, [original])
        with self.assertRaisesRegex(ContractError, "identity conflict"):
            publish_batch(self.db, "2026-10-15", {"A1"},
                          [record(1, content="corrected identity")])
        self.assertEqual(len(read_day(self.db, "2026-10-15")[1]), 1)
        self.assertEqual(read_day(self.db, "2026-10-15")[1][0]["push_id"], canonical_id(original))

    def test_equal_priority_null_floor_never_regresses(self):
        for priority in ("web", "collector"):
            with self.subTest(priority=priority):
                item = record(10 if priority == "web" else 11, origin=priority, floor=45)
                publish_batch(self.db, "2026-10-15", {"A1"}, [item])
                publish_batch(self.db, "2026-10-15", {"A1"},
                              [record(item["source_line"], origin=priority, floor=None)])
                rows = read_day(self.db, "2026-10-15")[1]
                self.assertEqual(next(r["floor"] for r in rows if r["source_line"] == item["source_line"]), 45)

    def test_provider_state_replay_and_gap_are_monotonic(self):
        publish_provider_state(self.db, day="2026-10-15", aid="A1",
            last_success_at="2026-10-15T00:00:20Z", has_gap=True,
            relay_cursor=10, purged_through_cursor=4)
        publish_provider_state(self.db, day="2026-10-15", aid="A1",
            last_success_at="2026-10-15T00:00:10Z", has_gap=False)
        row = self.db.execute(
            "SELECT relay_cursor,purged_through_cursor,last_success_at,has_gap FROM ptt_provider_state WHERE day=? AND aid=?",
            ("2026-10-15","A1")).fetchone()
        self.assertEqual(row, (10,4,"2026-10-15T00:00:20Z",1))
        publish_provider_state(self.db, day="2026-10-15", aid="A1",
            last_success_at="2026-10-15T00:00:30Z")
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM ptt_provider_state").fetchone()[0], 1)

    def test_verified_gap_closure_blocks_old_replay_and_allows_new_gap(self):
        publish_provider_state(self.db, day="2026-10-15", aid="A1",
            last_success_at="2026-10-15T00:00:20Z", has_gap=True,
            purged_through_cursor=5)
        evidence = dict(day="2026-10-15", aid="A1",
            verified_at="2026-10-15T00:00:30Z",
            covered_through_cursor=5, repair_id="repair-1",
            evidence_digest="0123456789abcdef")
        with self.assertRaises(ContractError):
            close_verified_gap(self.db, evidence, verify_coverage=lambda _: False)
        close_verified_gap(self.db, evidence, verify_coverage=lambda _: True)
        publish_provider_state(self.db, day="2026-10-15", aid="A1",
            last_success_at="2026-10-15T00:00:20Z", has_gap=True)
        self.assertEqual(self.db.execute(
            "SELECT has_gap FROM ptt_provider_state WHERE aid='A1'").fetchone()[0],0)
        publish_provider_state(self.db, day="2026-10-15", aid="A1",
            last_success_at="2026-10-15T00:00:40Z", has_gap=True)
        self.assertEqual(self.db.execute(
            "SELECT has_gap FROM ptt_provider_state WHERE aid='A1'").fetchone()[0],1)

    def test_nullable_floor_and_replay_survive(self):
        publish_batch(self.db, "2026-10-15", {"A1"}, [record(1)])
        self.assertIsNone(read_day(self.db, "2026-10-15")[1][0]["floor"])
        publish_batch(self.db, "2026-10-15", {"A1"}, [record(1, floor=7)])
        self.assertEqual(read_day(self.db, "2026-10-15")[1][0]["floor"], 7)


if __name__ == "__main__":
    unittest.main()
