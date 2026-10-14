"""Adversarial synthetic-only contract checks for Issue #48."""
import unittest
from datetime import datetime, timedelta, timezone
from ptt_offline.public_today_contract import (
    ContractError, TodayAdapter, canonical_id, history_completeness, taipei_day,
)


def push(i, aid="A1", origin="collector", when="2026-10-15T03:00:00+08:00"):
    return dict(aid=aid, source_line=i, floor=None, author="使用者",
                content="中文推文 " + str(i), occurred_at=when, origin=origin)


class PttOfflineContractTest(unittest.TestCase):
    def adapter(self):
        return TodayAdapter("2026-10-15", {"A1", "A2"})

    def test_canonical_identity_snapshot_relay_floor_independent(self):
        row = push(1)
        other = dict(row, floor=128, origin="web")
        self.assertEqual(canonical_id(row), canonical_id(other))
        self.assertEqual(canonical_id(row), canonical_id(dict(row, occurred_at="2026-10-14T19:00:00Z")))

    def test_multiple_aids_and_initial_300(self):
        a = self.adapter()
        a.merge_snapshot([push(i, aid="A1" if i % 2 else "A2") for i in range(1, 405)])
        self.assertEqual(len(a.read_initial()), 300)
        self.assertEqual(len(a.rows), 404)

    def test_snapshot_collector_wins_and_replay_is_deduped(self):
        a = self.adapter()
        web = push(1, origin="web")
        collector = dict(web, origin="collector", floor=1)
        a.merge_snapshot([web, collector, collector])
        self.assertEqual(len(a.rows), 1)
        self.assertEqual(next(iter(a.rows.values()))["origin"], "collector")

    def test_cross_thread_and_day_fail_closed(self):
        a = self.adapter()
        with self.assertRaises(ContractError):
            a.merge_snapshot([push(1, aid="other")])
        with self.assertRaises(ContractError):
            a.merge_snapshot([push(1, when="2026-10-16T00:00:00+08:00")])

    def test_missing_original_floor_remains_unknown(self):
        a = self.adapter()
        a.merge_snapshot([push(200)])
        self.assertIsNone(a.read_initial()[0]["floor"])

    def test_after_key_lost_is_gap(self):
        a = self.adapter()
        a.merge_snapshot([push(1)])
        self.assertEqual(a.read_after_key("expired"), [])
        self.assertTrue(a.history_gap)
        self.assertEqual(a.completeness, "partial")

    def test_multi_page_cursor_and_initial_tail_has_more(self):
        a = self.adapter()
        rows = [dict(push(i), cursor=i) for i in range(1, 351)]
        for start, end in ((0, 150), (150, 300), (300, 350)):
            a.ingest_relay_page(aid="A1", after_cursor=start, pushes=rows[start:end],
                                next_cursor=end, has_more=end < 350,
                                checked_at="2026-10-15T01:00:00Z")
        self.assertEqual(a.cursors["A1"], 350)
        self.assertEqual(len(a.rows), 350)

    def test_byte_truncation_requires_page_continuation(self):
        a = self.adapter()
        row = dict(push(1), cursor=1)
        a.ingest_relay_page(aid="A1", after_cursor=0, pushes=[row],
                            next_cursor=1, has_more=True, checked_at="2026-10-15T00:00:00Z")
        self.assertEqual(a.completeness, "partial")
        a.ingest_relay_page(aid="A1", after_cursor=1, pushes=[dict(push(2), cursor=2)],
                            next_cursor=2, has_more=False, checked_at="2026-10-15T00:00:02Z")
        self.assertEqual(len(a.rows), 2)

    def test_replay_out_of_order_expired_and_cross_aid(self):
        a = self.adapter()
        row = dict(push(1), cursor=2)
        with self.assertRaises(ContractError):
            a.ingest_relay_page(aid="A1", after_cursor=0, pushes=[row],
                                next_cursor=1, has_more=False, checked_at="2026-10-15T00:00:00Z")
        with self.assertRaises(ContractError):
            a.ingest_relay_page(aid="A1", after_cursor=3, pushes=[],
                                next_cursor=3, has_more=False, checked_at="2026-10-15T00:00:00Z")
        with self.assertRaises(ContractError):
            a.ingest_relay_page(aid="A1", after_cursor=0, pushes=[dict(push(2, aid="A2"), cursor=1)],
                                next_cursor=1, has_more=False, checked_at="2026-10-15T00:00:00Z")
        self.assertFalse(a.rows)

    def test_purged_floor_latches_partial_and_preserves_rows(self):
        a = self.adapter()
        a.merge_snapshot([push(1)])
        with self.assertRaises(ContractError):
            a.ingest_relay_page(aid="A1", after_cursor=0, pushes=[],
                                next_cursor=0, has_more=False, checked_at="2026-10-15T00:00:00Z",
                                purged_through_cursor=5)
        self.assertTrue(a.history_gap)
        self.assertEqual(len(a.rows), 1)
        a.merge_snapshot([push(2)])
        self.assertEqual(a.completeness, "partial")

    def test_oversize_cjk_and_page_bound(self):
        a = self.adapter()
        with self.assertRaises(ContractError):
            a.ingest_relay_page(aid="A1", after_cursor=0,
                                pushes=[dict(push(1), cursor=1, content="字" * 200000)],
                                next_cursor=1, has_more=False, checked_at="2026-10-15T00:00:00Z")
        self.assertEqual(a.cursors, {})

    def test_transient_failure_and_stale_checked_at(self):
        a = self.adapter()
        a.ingest_relay_page(aid="A1", after_cursor=0, pushes=[dict(push(1), cursor=1)],
                            next_cursor=1, has_more=False, checked_at="2026-10-15T00:00:00Z")
        self.assertEqual(a.freshness_at("2026-10-15T00:00:31Z"), "stale")
        a.mark_fetch_failure()
        self.assertEqual(len(a.rows), 1)
        self.assertEqual(a.cursors["A1"], 1)

    def test_taipei_midnight_ptt_only_state(self):
        a = self.adapter()
        next_ptt = a.roll_to("2026-10-15T16:00:00Z", {"NIGHT"})
        self.assertIsNot(a, next_ptt)
        self.assertEqual(next_ptt.day, "2026-10-16")
        self.assertEqual(next_ptt.aids, {"NIGHT"})

    def test_unknown_day_night_is_not_inferred(self):
        a = self.adapter()
        a.merge_snapshot([push(1)])
        self.assertNotIn("part", a.read_initial()[0])

    def test_history_requires_accepted_evidence(self):
        bad = [None, {}, {"status": "final-complete", "checksum": "ok"},
               {"authority": "synthetic-accepted-fixture", "status": "final-complete",
                "day": "2026-10-15", "aids": []}]
        for m in bad:
            self.assertEqual(history_completeness(m, True), "partial")
        accepted = {"authority": "synthetic-accepted-fixture", "status": "final-complete",
                    "day": "2026-10-15", "aids": ["A1", "A2"]}
        self.assertEqual(history_completeness(accepted, True), "complete")
        self.assertEqual(history_completeness(accepted, False), "partial")


if __name__ == "__main__":
    unittest.main()
