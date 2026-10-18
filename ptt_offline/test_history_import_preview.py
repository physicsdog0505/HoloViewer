import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ptt_offline.history_import_preview import (
    SOURCE_REVISION,
    build_preview,
    open_catalog_read_only,
)


class HistoryImportPreviewTest(unittest.TestCase):
    def make_catalog(self):
        td = tempfile.TemporaryDirectory()
        path = Path(td.name) / "hololive_stream_catalog.sqlite3"
        con = sqlite3.connect(path)
        con.executescript(
            """
            CREATE TABLE stream_catalog_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO stream_catalog_metadata VALUES('schema_version','1');
            CREATE TABLE channels(
              channel_id TEXT PRIMARY KEY,
              channel_name TEXT NOT NULL DEFAULT '',
              avatar_url TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE streams(
              video_id TEXT PRIMARY KEY,
              channel_id TEXT,
              title TEXT,
              scheduled_start TEXT,
              actual_start TEXT,
              actual_end TEXT,
              lifecycle_state TEXT,
              projection_observed_at TEXT,
              is_livestream INTEGER
            );
            """
        )
        con.execute("INSERT INTO channels VALUES(?,?,?)",("UC"+"A"*22,"A","https://example.test/a.jpg"))
        rows=[
          ("62AgiXDP3tU","UC"+"A"*22,"A","2026-10-05T12:00:00+00:00","2026-10-05T12:01:05+00:00","2026-10-05T12:54:31+00:00","ended","2026-10-14T14:41:31+00:00",1),
          ("FVpLKAiHYFA","UC"+"A"*22,"B","2026-10-09T10:00:00+00:00","2026-10-09T10:00:05+00:00","2026-10-09T11:29:38+00:00","ended","2026-10-14T14:41:31+00:00",1),
          ("pwJeqkeHtPM","UC"+"A"*22,"C","2026-10-04T15:30:00+00:00","2026-10-04T15:29:35+00:00","2026-10-05T00:35:17+00:00","ended","2026-10-14T08:39:37+00:00",1),
          ("8pF4qHcshDc","UC"+"A"*22,"D","2026-10-15T12:00:00+00:00","2026-10-15T12:00:16+00:00","2026-10-15T14:42:31+00:00","ended","2026-10-16T23:03:55+00:00",1),
          ("badwindow01","UC"+"A"*22,"bad",None,"2026-10-06T13:00:00+00:00","2026-10-06T12:00:00+00:00","ended","2026-10-06T14:00:00+00:00",1),
          ("scheduled01","UC"+"A"*22,"scheduled","2026-10-06T12:00:00+00:00",None,None,"upcoming","2026-10-06T11:00:00+00:00",1)
        ]
        con.executemany("INSERT INTO streams VALUES(?,?,?,?,?,?,?,?,?)",rows)
        con.commit(); con.close()
        return td,path

    def test_known_vods_project_exact_actual_windows(self):
        td,path=self.make_catalog()
        self.addCleanup(td.cleanup)
        con=open_catalog_read_only(path)
        try:
            preview=build_preview(con,from_day="2026-10-01",through_day="2026-10-17")
        finally:
            con.close()
        by_id={row["video_id"]:row for row in preview["rows"]}
        self.assertEqual(preview["row_count"],4)
        self.assertEqual(by_id["62AgiXDP3tU"]["actual_start"],"2026-10-05T12:01:05Z")
        self.assertEqual(by_id["62AgiXDP3tU"]["actual_end"],"2026-10-05T12:54:31Z")
        self.assertEqual(by_id["FVpLKAiHYFA"]["actual_start"],"2026-10-09T10:00:05Z")
        self.assertEqual(by_id["FVpLKAiHYFA"]["actual_end"],"2026-10-09T11:29:38Z")
        self.assertEqual(by_id["pwJeqkeHtPM"]["actual_start"],"2026-10-04T15:29:35Z")
        self.assertEqual(by_id["pwJeqkeHtPM"]["actual_end"],"2026-10-05T00:35:17Z")
        self.assertEqual(by_id["8pF4qHcshDc"]["actual_start"],"2026-10-15T12:00:16Z")
        self.assertEqual(by_id["8pF4qHcshDc"]["actual_end"],"2026-10-15T14:42:31Z")
        self.assertTrue(all(x["source_revision"]==SOURCE_REVISION for x in preview["rows"]))

    def test_taipei_day_uses_actual_start_not_scheduled(self):
        td,path=self.make_catalog()
        self.addCleanup(td.cleanup)
        con=open_catalog_read_only(path)
        try:
            preview=build_preview(con,from_day="2026-10-01",through_day="2026-10-17")
        finally:
            con.close()
        by_id={row["video_id"]:row for row in preview["rows"]}
        # 15:29 UTC is 23:29 Taipei on 10/04.
        self.assertEqual(by_id["pwJeqkeHtPM"]["taipei_day"],"2026-10-04")

    def test_invalid_or_nonended_rows_are_fail_closed(self):
        td,path=self.make_catalog()
        self.addCleanup(td.cleanup)
        con=open_catalog_read_only(path)
        try:
            preview=build_preview(con,from_day="2026-10-01",through_day="2026-10-17")
        finally:
            con.close()
        ids={row["video_id"] for row in preview["rows"]}
        self.assertNotIn("badwindow01",ids)
        self.assertNotIn("scheduled01",ids)

    def test_read_only_open_rejects_writes(self):
        td,path=self.make_catalog()
        self.addCleanup(td.cleanup)
        con=open_catalog_read_only(path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM streams")
        finally:
            con.close()

    def test_projection_is_deterministic_and_idempotent(self):
        td,path=self.make_catalog()
        self.addCleanup(td.cleanup)
        con=open_catalog_read_only(path)
        try:
            a=build_preview(con,from_day="2026-10-01",through_day="2026-10-17")
            b=build_preview(con,from_day="2026-10-01",through_day="2026-10-17")
        finally:
            con.close()
        self.assertEqual(json.dumps(a,sort_keys=True),json.dumps(b,sort_keys=True))


if __name__ == "__main__":
    unittest.main()
