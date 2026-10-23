import sqlite3
import unittest
from pathlib import Path


SCHEMA = Path(__file__).with_name("worker_host").joinpath(
    "today", "0006_canonical_collab_projection.PROPOSED.sql"
)


class CollabProjectionQueryPlanTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))

    def tearDown(self):
        self.db.close()

    def plan(self, sql, args=()):
        return " | ".join(
            str(row[3])
            for row in self.db.execute("EXPLAIN QUERY PLAN " + sql, args)
        )

    def test_live_read_uses_live_index(self):
        plan = self.plan("""
            SELECT event_id,event_key,label,confidence,review_status,payload_json,
                   source_revision,published_at
            FROM public_collab_events
            WHERE is_current=1 AND live_scope=1 AND review_status!='rejected'
            ORDER BY start_at DESC,event_id DESC LIMIT 101
        """)
        self.assertIn("public_collab_events_live", plan)
        self.assertNotIn("SCAN public_collab_events", plan)

    def test_history_count_and_page_use_history_index(self):
        count_plan = self.plan("""
            SELECT COUNT(*) AS n
            FROM public_collab_events
            WHERE event_date=? AND is_current=1 AND review_status!='rejected'
        """, ("2026-10-22",))
        page_plan = self.plan("""
            SELECT event_id,event_key,label,confidence,review_status,payload_json,
                   source_revision,published_at
            FROM public_collab_events
            WHERE event_date=? AND is_current=1 AND review_status!='rejected'
            ORDER BY start_at DESC,event_id DESC LIMIT ? OFFSET ?
        """, ("2026-10-22", 50, 0))
        self.assertIn("public_collab_events_history", count_plan)
        self.assertIn("public_collab_events_history", page_plan)
        self.assertNotIn("SCAN public_collab_events", page_plan)

    def test_history_retirement_uses_partial_range_index(self):
        plan = self.plan("""
            UPDATE public_collab_events
            SET is_current=0
            WHERE is_current=1 AND live_scope=0 AND start_at>=? AND start_at<?
        """, ("2026-10-21T16:00:00+00:00", "2026-10-22T16:00:00+00:00"))
        self.assertIn("public_collab_events_retire_range", plan)
        self.assertNotIn("SCAN public_collab_events", plan)

    def test_live_replacement_uses_live_index(self):
        plan = self.plan("""
            UPDATE public_collab_events
            SET live_scope=0
            WHERE is_current=1 AND live_scope=1
        """)
        self.assertIn("public_collab_events_live", plan)
        self.assertNotIn("SCAN public_collab_events", plan)

    def test_detail_and_meta_are_primary_key_lookups(self):
        detail = self.plan("""
            SELECT event_id,event_key,label,confidence,review_status,payload_json,
                   source_revision,published_at
            FROM public_collab_events
            WHERE event_id=? AND is_current=1 AND review_status!='rejected'
        """, ("holoserver-hide-and-seek:5680e7ec7c29074a",))
        meta = self.plan("""
            SELECT projection_key,source_revision,published_at,range_start,range_end,
                   source_event_count,effective_event_count
            FROM public_collab_projection_meta
            WHERE projection_key=?
        """, ("live",))
        self.assertIn("sqlite_autoindex_public_collab_events_1", detail)
        self.assertIn("sqlite_autoindex_public_collab_projection_meta_1", meta)


if __name__ == "__main__":
    unittest.main()
