"""Issue #48 day-level consumer contract regressions, in-memory only."""
import unittest
from ptt_offline.public_today_contract import (
    ContractError, InitialWindow, PttConsumerReader,
    SyntheticPttProvider, TodayAdapter,
)


def row(n, aid="A1", cursor=None):
    result = {"aid": aid, "source_line": n, "author": "author",
              "content": f"post {n}", "floor": None,
              "occurred_at": "2026-10-15T03:00:00+08:00"}
    if cursor is not None:
        result["cursor"] = cursor
    return result


class DayBoundaryTests(unittest.TestCase):
    def test_init_failure_on_second_aid_keeps_day_state_unchanged(self):
        class Failing(SyntheticPttProvider):
            def initial_window(self, aid, *, limit):
                if aid == "A2":
                    return InitialWindow("A2", [], 0, self.checked_at, safe=False)
                return super().initial_window(aid, limit=limit)
        provider = Failing({"2026-10-15": {"A1", "A2"}},
                           relay_rows={"A1": [row(1, cursor=1)]})
        adapter = TodayAdapter("2026-10-15", {"A1", "A2"})
        with self.assertRaises(ContractError):
            adapter.initialize_from_provider(provider)
        self.assertFalse(adapter.rows)
        self.assertEqual(adapter.cursors, {"A1": 0, "A2": 0})
        self.assertFalse(adapter.last_checked_by_aid)

    def test_partial_poll_is_stale_and_retains_good_aid(self):
        class Failing(SyntheticPttProvider):
            def relay_after(self, aid, *, after_cursor, limit):
                if aid == "A2":
                    raise ConnectionError("offline synthetic failure")
                return super().relay_after(aid, after_cursor=after_cursor, limit=limit)
        provider = Failing({"2026-10-15": {"A1", "A2"}},
                           relay_rows={"A1": [row(1, cursor=1)]})
        adapter = TodayAdapter("2026-10-15", {"A1", "A2"})
        with self.assertRaises(ConnectionError):
            adapter.poll_provider(provider)
        self.assertEqual(adapter.freshness, "stale")
        self.assertEqual(adapter.completeness, "partial")
        self.assertEqual(adapter.cursors["A1"], 1)
        self.assertEqual(len(adapter.rows), 1)

    def test_read_today_model_hides_cursor_vector(self):
        provider = SyntheticPttProvider(
            {"2026-10-15": {"A1", "A2"}},
            relay_rows={"A1": [row(1, cursor=1)],
                        "A2": [row(2, aid="A2", cursor=2)]},
        )
        reader = PttConsumerReader(provider)
        model = reader.read_today("2026-10-15")
        self.assertEqual(model.schema_version, "public-consumer-v1")
        self.assertEqual(len(model.pushes), 2)
        self.assertNotIn("cursors", vars(model))
        self.assertNotIn("A1", model.checkpoint)
        resumed = reader.read_today("2026-10-15", checkpoint=model.checkpoint)
        self.assertEqual(resumed.day, model.day)

    def test_snapshot_change_revises_opaque_checkpoint(self):
        adapter = TodayAdapter("2026-10-15", {"A1"})
        adapter.merge_snapshot([{**row(1), "origin": "web"}])
        old = adapter.consumer_checkpoint()
        adapter.merge_snapshot([{**row(1), "origin": "collector", "floor": 5}])
        self.assertNotEqual(old, adapter.consumer_checkpoint())
        with self.assertRaises(ContractError):
            adapter.check_consumer_checkpoint(old, adapter.day)


if __name__ == "__main__":
    unittest.main()
