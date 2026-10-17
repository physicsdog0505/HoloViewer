import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.r2_archive_export import export_archive

TPE=ZoneInfo("Asia/Taipei")


class R2ArchiveExportTests(unittest.TestCase):
    def make_db(self):
        db=sqlite3.connect(":memory:")
        db.execute("""CREATE TABLE articles(
            id INTEGER PRIMARY KEY, board TEXT, aid TEXT, url TEXT,
            title_hint TEXT, created_at TEXT, last_seen_at TEXT
        )""")
        db.execute("""CREATE TABLE pushes(
            id INTEGER PRIMARY KEY, article_id INTEGER, source_line INTEGER,
            source_page INTEGER, kind TEXT, author TEXT, content TEXT,
            ptt_date TEXT, ptt_time TEXT, collected_at TEXT
        )""")
        posted=datetime(2026,10,1,12,0,tzinfo=TPE)
        epoch=int(posted.timestamp())
        url=f"https://www.ptt.cc/bbs/C_Chat/M.{epoch}.A.001.html"
        board,aid=aid_from_article_url(url)
        db.execute(
            "INSERT INTO articles VALUES(1,?,?,?,?,?,?)",
            (board,aid,url,"test",posted.isoformat(),posted.isoformat()),
        )
        rows=[
            (1,1,10,1,"push","alice","hello","10/01","12:01",posted.isoformat()),
            (2,1,11,1,"arrow","bob","world","10/01","12:02",posted.isoformat()),
        ]
        db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",rows)
        db.commit()
        return db

    def test_exports_absolute_minute_hour_chunk(self):
        db=self.make_db()
        with tempfile.TemporaryDirectory() as td:
            receipt=export_archive(
                db,from_day="2026-10-01",through_day="2026-10-01",
                out_dir=Path(td),
            )
            self.assertEqual(receipt["pushes"],2)
            self.assertEqual(len(receipt["objects"]),1)
            item=receipt["objects"][0]
            self.assertEqual(item["key"],"ptt/v1/chunks/2026/10/01/0400.json.gz")
            path=Path(td)/item["key"]
            with gzip.open(path,"rt",encoding="utf-8") as handle:
                payload=json.load(handle)
            self.assertEqual(payload["precision"],"minute")
            self.assertEqual(payload["pushes"][0]["occurred_at"],"2026-10-01T04:01:00Z")
            self.assertEqual(payload["pushes"][1]["occurred_at"],"2026-10-01T04:02:00Z")
            self.assertEqual(
                payload["pushes"][1]["minute_epoch"]-payload["pushes"][0]["minute_epoch"],1
            )

    def test_manifest_declares_vod_mapping_contract(self):
        db=self.make_db()
        with tempfile.TemporaryDirectory() as td:
            receipt=export_archive(
                db,from_day="2026-10-01",through_day="2026-10-01",
                out_dir=Path(td),
            )
            self.assertEqual(receipt["schema_version"],"ptt-r2-archive-v1")
            self.assertEqual(receipt["chunk_minutes"],60)
            self.assertIn("actual_start",receipt["vod_mapping"])


if __name__=="__main__":
    unittest.main()
