"""Offline SQLite equivalence tests for Worker schema guards; never touches D1."""
from pathlib import Path
import sqlite3
import tempfile
import unittest


class WorkerSqliteSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(Path(self.tmp.name) / "worker-fixture.sqlite3")
        self.conn.executescript(Path(__file__).with_name("relay").joinpath("schema.sql").read_text())

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_returning_counts_only_push_rows_not_rate_trigger_writes(self):
        sql = (
            "INSERT OR IGNORE INTO ptt_pushes"
            "(push_id,aid,article_url,source_line,kind,author,content,occurred_at,producer_id,published_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING push_id"
        )
        args = ("g2-one", "G2_SYNTHETIC_TEST", "https://ptt.cc/", 1, "推", "g2_test",
                "synthetic", "2026-10-10T03:20:00Z", "g2-isolated-test", "2026-10-10T03:20:00Z")
        inserted = self.conn.execute(sql, args).fetchall()
        self.assertEqual(inserted, [("g2-one",)])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ptt_pushes").fetchone()[0], 1)
        self.assertEqual(
            dict(self.conn.execute("SELECT window_kind,inserted_pushes FROM ptt_write_rate")),
            {"minute": 1, "hour": 1},
        )
        self.assertEqual(self.conn.execute(sql, args).fetchall(), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ptt_pushes").fetchone()[0], 1)

    def test_trigger_blocks_minute_insert_overflow_and_rolls_back(self):
        for n in range(240):
            self.conn.execute(
                "INSERT INTO ptt_pushes(push_id,aid,article_url,source_line,kind,author,content,occurred_at,producer_id,published_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"id-{n}", "A", "https://ptt.cc/", n+1, "推", "x", "", "2026-10-09T00:00:00Z", "fixture", "2026-10-09T00:00:00Z")
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "minute insert budget exceeded"):
            self.conn.execute(
                "INSERT INTO ptt_pushes(push_id,aid,article_url,source_line,kind,author,content,occurred_at,producer_id,published_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("overflow", "A", "https://ptt.cc/", 241, "推", "x", "", "2026-10-09T00:00:00Z", "fixture", "2026-10-09T00:00:00Z")
            )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ptt_pushes").fetchone()[0], 240)
        self.assertEqual(
            dict(self.conn.execute("SELECT window_kind,inserted_pushes FROM ptt_write_rate")),
            {"hour": 240, "minute": 240},
        )

    def test_ignored_duplicates_do_not_consume_mutation_budget(self):
        self.conn.execute(
            "INSERT INTO ptt_pushes(push_id,aid,article_url,source_line,kind,author,content,occurred_at,producer_id,published_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("same", "A", "https://ptt.cc/", 1, "推", "x", "", "2026-10-09T00:00:00Z", "fixture", "2026-10-09T00:00:00Z")
        )
        for _ in range(5000):
            self.conn.execute("INSERT OR IGNORE INTO ptt_pushes(push_id,aid,source_line) VALUES ('same','A',1)")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ptt_pushes").fetchone()[0], 1)
        self.assertEqual(dict(self.conn.execute("SELECT window_kind,inserted_pushes FROM ptt_write_rate")), {"hour": 1, "minute": 1})
        self.conn.execute(
            "INSERT INTO ptt_pushes(push_id,aid,article_url,source_line,kind,author,content,occurred_at,producer_id,published_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("new", "A", "https://ptt.cc/", 2, "推", "x", "", "2026-10-09T00:00:00Z", "fixture", "2026-10-09T00:00:00Z")
        )
        self.assertGreater(self.conn.execute("SELECT cursor FROM ptt_pushes WHERE push_id='new'").fetchone()[0], 5000)

    def test_purged_source_floor_cap_and_conflict_preserve_high_water(self):
        self.conn.execute("INSERT INTO ptt_purged_source_floor(aid,source_line) VALUES ('A',100)")
        self.conn.execute(
            "INSERT INTO ptt_purged_source_floor(aid,source_line) VALUES ('A',80) ON CONFLICT(aid) DO UPDATE SET source_line=MAX(ptt_purged_source_floor.source_line,excluded.source_line)"
        )
        self.assertEqual(self.conn.execute("SELECT source_line FROM ptt_purged_source_floor WHERE aid='A'").fetchone()[0],100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
