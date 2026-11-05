"""Adversarial synthetic-only contract checks for Issue #48."""
import unittest

from ptt_offline.public_today_contract import (
    ContractError,
    INITIAL_WINDOW,
    InitialWindow,
    RelayPage,
    SyntheticPttProvider,
    TodayAdapter,
    canonical_id,
    history_completeness,
    normalize_public_aid,
)


def push(i, aid="A1", origin="collector", when="2026-10-15T03:00:00+08:00", *, cursor=None, content=None):
    row = dict(
        aid=aid,
        source_line=i,
        floor=None,
        author="使用者",
        content=content if content is not None else "中文推文 " + str(i),
        occurred_at=when,
        origin=origin,
    )
    if cursor is not None:
        row["cursor"] = cursor
    return row


class PttOfflineContractTest(unittest.TestCase):
    @staticmethod
    def fixture_authority(manifest):
        return manifest.get("authority") == "synthetic-accepted-fixture"

    def test_atomic_invalid_later_snapshot_row_keeps_all_state(self):
        a = self.adapter()
        a.merge_snapshot([push(1)])
        original = dict(a.rows)
        with self.assertRaises(ContractError):
            a.merge_snapshot([push(2), push(3, aid="FOREIGN")])
        self.assertEqual(a.rows, original)

    def test_atomic_invalid_later_relay_row_keeps_cursor_and_rows(self):
        a = TodayAdapter("2026-10-15", {"A1"})
        with self.assertRaises(ContractError):
            a.ingest_relay_page(RelayPage("A1", 0, 2, False, "2026-10-15T00:00:00Z", 0,
                [push(1, cursor=1), push(2, cursor=2, when="2026-10-16T00:00:00+08:00")]))
        self.assertEqual(a.rows, {})
        self.assertEqual(a.cursors["A1"], 0)

    def test_strict_date_day_key(self):
        for invalid in ("2026-10-15T00:00:00", "2026-1-5", "2026-02-30"):
            with self.assertRaises(ContractError):
                TodayAdapter(invalid, {"A1"})

    def test_freshness_regression_fails_closed(self):
        a = TodayAdapter("2026-10-15", {"A1"})
        a.ingest_relay_page(RelayPage("A1", 0, 1, False, "2026-10-15T00:00:30Z", 0, [push(1, cursor=1)]))
        with self.assertRaisesRegex(ContractError, "clock regression"):
            a.freshness_at("2026-10-15T00:00:29Z")
        self.assertEqual(a.freshness, "unknown")

    def test_consumer_checkpoint_is_opaque_and_day_bound(self):
        a = self.adapter()
        token = a.consumer_checkpoint()
        self.assertTrue(token.startswith("ptt:checkpoint:v1:"))
        self.assertNotIn("A1", token)
        a.check_consumer_checkpoint(token, "2026-10-15")
        with self.assertRaises(ContractError):
            a.check_consumer_checkpoint(token, "2026-10-16")
        a.cursors["A1"] = 5
        with self.assertRaises(ContractError):
            a.check_consumer_checkpoint(token, "2026-10-15")


    def adapter(self):
        return TodayAdapter("2026-10-15", {"A1", "A2"})

    def test_canonical_identity_matches_reviewed_311_vector_and_normalizes_hash_aid(self):
        vector = dict(
            aid="M.1791417600.A.001",
            source_line=101,
            author="viewer",
            occurred_at="2026-10-08T12:00:00Z",
            content="hello 世界",
        )
        expected = "ptt:v1:f2f14565abffc4941161bb4928925d381bd0d36465a81ce846b6fa859117c84f"
        self.assertEqual(canonical_id(vector), expected)
        self.assertEqual(canonical_id({**vector, "aid": "#M.1791417600.A.001"}), expected)
        self.assertEqual(normalize_public_aid("#1gntGd6b"), "1gntGd6b")
        self.assertRegex(expected, r"^ptt:v1:[0-9a-f]{64}$")

    def test_canonical_identity_floor_independent_and_timezone_stable(self):
        row = push(1)
        self.assertEqual(canonical_id(row), canonical_id(dict(row, floor=128, origin="web")))
        self.assertEqual(canonical_id(row), canonical_id(dict(row, occurred_at="2026-10-14T19:00:00Z")))

    def test_multiple_aids_and_initial_300(self):
        a = self.adapter()
        a.merge_snapshot([push(i, aid="A1" if i % 2 else "A2") for i in range(1, 405)])
        self.assertEqual(len(a.read_initial()), INITIAL_WINDOW)
        self.assertEqual(len(a.rows), 404)

    def test_snapshot_collector_wins_and_replay_is_deduped(self):
        a = self.adapter()
        web = push(1, origin="web")
        collector = dict(web, origin="collector", floor=1)
        a.merge_snapshot([web, collector, collector])
        self.assertEqual(len(a.rows), 1)
        self.assertEqual(next(iter(a.rows.values()))["origin"], "collector")

    def test_cross_thread_day_and_push_id_mismatch_fail_closed(self):
        a = self.adapter()
        with self.assertRaises(ContractError):
            a.merge_snapshot([push(1, aid="other")])
        with self.assertRaises(ContractError):
            a.merge_snapshot([push(1, when="2026-10-16T00:00:00+08:00")])
        with self.assertRaises(ContractError):
            a.merge_snapshot([{**push(1), "push_id": "ptt:v1:" + "0" * 64}])

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

    def test_multi_aid_cursor_vector_is_independent(self):
        a = self.adapter()
        a.ingest_relay_page(RelayPage("A1", 0, 10, False, "2026-10-15T00:00:00Z", 0, [push(1, aid="A1", cursor=10)]))
        a.ingest_relay_page(RelayPage("A2", 0, 3, False, "2026-10-15T00:00:01Z", 0, [push(2, aid="A2", cursor=3)]))
        self.assertEqual(a.cursors, {"A1": 10, "A2": 3})
        with self.assertRaises(ContractError):
            a.ingest_relay_page(RelayPage("A2", 10, 11, False, "2026-10-15T00:00:02Z", 0, [push(3, aid="A2", cursor=11)]))

    def test_initial_tail_has_more_is_rejected_as_forward_checkpoint(self):
        provider = SyntheticPttProvider(
            {"2026-10-15": {"A1"}},
            relay_rows={"A1": [push(i, aid="A1", cursor=i) for i in range(1, 351)]},
            tail_chunk_limit=1,
        )
        tail = provider.relay_tail("A1", limit=300)
        self.assertEqual(len(tail.pushes), 1)
        self.assertTrue(tail.has_more)
        with self.assertRaisesRegex(ContractError, "tail has_more"):
            TodayAdapter.reject_unsafe_tail_bootstrap(tail)

    def test_safe_initial_window_loads_recent_300_before_checkpoint(self):
        rows = [push(i, aid="A1", cursor=i) for i in range(1, 351)]
        provider = SyntheticPttProvider({"2026-10-15": {"A1"}}, relay_rows={"A1": rows})
        a = TodayAdapter("2026-10-15", {"A1"})
        a.initialize_from_provider(provider)
        initial = a.read_initial()
        self.assertEqual(len(initial), 300)
        self.assertEqual(initial[0]["source_line"], 51)
        self.assertEqual(initial[-1]["source_line"], 350)
        self.assertEqual(a.cursors["A1"], 350)

    def test_provider_cannot_claim_unsafe_initial_window(self):
        class UnsafeProvider(SyntheticPttProvider):
            def initial_window(self, aid, *, limit):
                return InitialWindow(aid, [push(9, aid=aid, cursor=9)], 9, self.checked_at, safe=False)
        a = TodayAdapter("2026-10-15", {"A1"})
        with self.assertRaisesRegex(ContractError, "not coverage-safe"):
            a.initialize_from_provider(UnsafeProvider({"2026-10-15": {"A1"}}))
        self.assertEqual(a.cursors["A1"], 0)
        self.assertFalse(a.rows)

    def test_byte_truncated_forward_poll_continues_in_bounded_pages(self):
        initial_rows = [push(i, aid="A1", cursor=i, content="seed" + str(i)) for i in range(1, 301)]
        provider = SyntheticPttProvider(
            {"2026-10-15": {"A1"}},
            relay_rows={"A1": list(initial_rows)},
            byte_limit=32 * 1024,
        )
        a = TodayAdapter("2026-10-15", {"A1"})
        a.initialize_from_provider(provider)
        for i in range(301, 330):
            provider.relay_rows["A1"].append(push(i, aid="A1", cursor=i, content="界" * 900 + str(i)))
        a.poll_provider(provider, page_limit=200, max_pages_per_aid=3)
        self.assertEqual(a.cursors["A1"], 329)
        self.assertEqual(len(a.read_initial()), 300)

    def test_replay_out_of_order_expired_and_cross_aid(self):
        a = self.adapter()
        with self.assertRaises(ContractError):
            a.ingest_relay_page(RelayPage("A1", 0, 1, False, "2026-10-15T00:00:00Z", 0, [push(1, cursor=2)]))
        with self.assertRaises(ContractError):
            a.ingest_relay_page(RelayPage("A1", 3, 3, False, "2026-10-15T00:00:00Z", 0, []))
        with self.assertRaises(ContractError):
            a.ingest_relay_page(RelayPage("A1", 0, 1, False, "2026-10-15T00:00:00Z", 0, [push(2, aid="A2", cursor=1)]))
        self.assertFalse(a.rows)

    def test_retention_gap_flag_is_exact_and_latches_partial(self):
        a = TodayAdapter("2026-10-15", {"A1"})
        a.merge_snapshot([push(1)])
        with self.assertRaisesRegex(ContractError, "retention gap"):
            a.ingest_relay_page(RelayPage("A1", 0, 0, False, "2026-10-15T00:00:00Z", 5, [], True))
        self.assertTrue(a.history_gap)
        self.assertEqual(a.completeness, "partial")
        a.merge_snapshot([push(2)])
        self.assertEqual(a.completeness, "partial")
        with self.assertRaisesRegex(ContractError, "flag mismatch"):
            a.ingest_relay_page(RelayPage("A1", 0, 0, False, "2026-10-15T00:00:00Z", 5, [], False))

    def test_oversize_cjk_page_rejected_without_state_mutation(self):
        a = TodayAdapter("2026-10-15", {"A1"})
        huge = push(1, cursor=1, content="字" * 200000)
        with self.assertRaises(ContractError):
            a.ingest_relay_page(RelayPage("A1", 0, 1, False, "2026-10-15T00:00:00Z", 0, [huge]))
        self.assertEqual(a.cursors["A1"], 0)
        self.assertFalse(a.rows)

    def test_transient_failure_keeps_last_good_rows_and_stale_uses_oldest_aid_check(self):
        a = self.adapter()
        a.ingest_relay_page(RelayPage("A1", 0, 1, False, "2026-10-15T00:00:00Z", 0, [push(1, aid="A1", cursor=1)]))
        a.ingest_relay_page(RelayPage("A2", 0, 1, False, "2026-10-15T00:00:20Z", 0, [push(2, aid="A2", cursor=1)]))
        self.assertEqual(a.freshness_at("2026-10-15T00:00:31Z"), "stale")
        a.mark_fetch_failure()
        self.assertEqual(len(a.rows), 2)
        self.assertEqual(a.cursors, {"A1": 1, "A2": 1})

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

    def test_provider_interface_keeps_ui_free_of_storage_schema(self):
        provider = SyntheticPttProvider(
            {"2026-10-15": {"A1"}},
            snapshots={"2026-10-15": [push(1, aid="A1")]},
        )
        a = TodayAdapter.from_provider(provider, "2026-10-15")
        self.assertEqual(len(a.rows), 1)
        self.assertEqual(a.source, "offline-contract")

    def test_history_requires_independent_accepted_evidence(self):
        bad = [
            None,
            {},
            {"status": "final-complete", "checksum": "ok"},
            {"authority": "synthetic-accepted-fixture", "status": "final-complete", "day": "2026-10-15", "aids": []},
            {"authority": "synthetic-accepted-fixture", "status": "final-complete", "day": "2026-10-15", "aids": ["A1"], "caller_complete": True},
        ]
        for manifest in bad:
            self.assertEqual(history_completeness(manifest, verify_authority=self.fixture_authority, expected_day="2026-10-15", expected_aids={"A1", "A2"}), "partial")
        accepted = {
            "authority": "synthetic-accepted-fixture",
            "status": "final-complete",
            "day": "2026-10-15",
            "aids": ["#A1", "A2"],
        }
        self.assertEqual(history_completeness(accepted, verify_authority=self.fixture_authority, expected_day="2026-10-15", expected_aids={"A1", "A2"}), "complete")
        self.assertEqual(history_completeness(accepted, expected_day="2026-10-15", expected_aids={"A1", "A2"}), "partial")
        self.assertEqual(history_completeness(accepted, verify_authority=self.fixture_authority, expected_day="2026-10-16", expected_aids={"A1", "A2"}), "partial")
        self.assertEqual(history_completeness(accepted, verify_authority=self.fixture_authority, expected_day="2026-10-15", expected_aids={"A1"}), "partial")


if __name__ == "__main__":
    unittest.main()
