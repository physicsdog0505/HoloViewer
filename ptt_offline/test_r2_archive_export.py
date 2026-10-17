import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.public_today_contract import ContractError
from ptt_offline.r2_archive_export import export_archive, vod_minute, write_archive_rows

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
            self.assertEqual([row["floor"] for row in payload["pushes"]],[1,2])
            self.assertEqual({row["floor_quality"] for row in payload["pushes"]},
                             {"per-thread-ordinal"})
            self.assertNotEqual(payload["pushes"][0]["floor"],
                                payload["pushes"][0]["source_line"])
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

    def test_gzip_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            first=export_archive(self.make_db(),from_day="2026-10-01",through_day="2026-10-01",out_dir=Path(left))
            second=export_archive(self.make_db(),from_day="2026-10-01",through_day="2026-10-01",out_dir=Path(right))
            key=first["objects"][0]["key"]
            self.assertEqual((Path(left)/key).read_bytes(),(Path(right)/key).read_bytes())
            self.assertEqual(first["objects"][0]["sha256"],second["objects"][0]["sha256"])

    def test_replaceable_chunk_uses_most_conservative_status(self):
        base={"occurred_at":"2026-10-01T04:01:00Z","aid":"A1","source_page":1,
              "kind":"push","author":"u","content":"x","source_url":"https://example.invalid",
              "source_path":"/tmp/source.sqlite3","time_quality":"source-minute"}
        rows=[dict(base,source_line=1,source_record_key="A1:1",coverage_day="2026-10-01"),
              dict(base,source_line=2,source_record_key="A1:2",coverage_day="2026-10-02")]
        days=[{"day":"2026-10-01","coverage_status":"COMPLETE","finalized":True,"reason":"verified"},
              {"day":"2026-10-02","coverage_status":"PARTIAL","finalized":False,"reason":"open"}]
        with tempfile.TemporaryDirectory() as td:
            receipt=write_archive_rows(rows,from_day="2026-10-01",through_day="2026-10-02",
                                       out_dir=Path(td),days=days,manifest_name="pilot.json")
            self.assertEqual(receipt["objects"][0]["coverage_status"],"PARTIAL")
            self.assertFalse(receipt["objects"][0]["finalized"])

    def test_vod_minute_uses_absolute_timezone_aware_timeline(self):
        self.assertEqual(
            vod_minute("2026-10-09T10:43:00Z","2026-10-09T18:00:00+08:00"),
            43,
        )

    def test_vod_minute_rejects_naive_timestamp(self):
        with self.assertRaisesRegex(ContractError,"timezone-aware timestamp required"):
            vod_minute("2026-10-09T10:43:00Z","2026-10-09T18:00:00")

    def test_floor_is_per_thread_and_survives_hour_and_source_line_gaps(self):
        db=self.make_db()
        db.execute("UPDATE pushes SET source_line=30,ptt_time='12:59' WHERE id=1")
        db.execute("UPDATE pushes SET source_line=80,ptt_time='13:00' WHERE id=2")
        posted=datetime(2026,10,1,12,30,tzinfo=TPE)
        url=f"https://www.ptt.cc/bbs/C_Chat/M.{int(posted.timestamp())}.A.002.html"
        board,aid=aid_from_article_url(url)
        db.execute("INSERT INTO articles VALUES(2,?,?,?,?,?,?)",
                   (board,aid,url,"second",posted.isoformat(),posted.isoformat()))
        db.execute("INSERT INTO pushes VALUES(3,2,500,1,'push','c','new thread','10/01','13:01',?)",
                   (posted.isoformat(),))
        db.commit()
        with tempfile.TemporaryDirectory() as td:
            receipt=export_archive(db,from_day="2026-10-01",through_day="2026-10-01",
                                   out_dir=Path(td))
            rows=[]
            for item in receipt["objects"]:
                with gzip.open(Path(td)/item["key"],"rt",encoding="utf-8") as handle:
                    rows.extend(json.load(handle)["pushes"])
        by_aid={}
        for row in rows:
            by_aid.setdefault(row["aid"],[]).append(row)
        first=next(value for value in by_aid.values() if len(value)==2)
        second=next(value for value in by_aid.values() if len(value)==1)
        self.assertEqual([row["source_line"] for row in first],[30,80])
        self.assertEqual([row["floor"] for row in first],[1,2])
        self.assertEqual(second[0]["source_line"],500)
        self.assertEqual(second[0]["floor"],1)

    def test_floor_is_unknown_without_thread_start_evidence(self):
        db=self.make_db()
        db.execute("UPDATE pushes SET source_page=5")
        db.commit()
        with tempfile.TemporaryDirectory() as td:
            receipt=export_archive(db,from_day="2026-10-01",through_day="2026-10-01",
                                   out_dir=Path(td))
            with gzip.open(Path(td)/receipt["objects"][0]["key"],"rt",encoding="utf-8") as handle:
                rows=json.load(handle)["pushes"]
        self.assertEqual([row["floor"] for row in rows],[None,None])
        self.assertEqual({row["floor_quality"] for row in rows},{"unknown"})


if __name__=="__main__":
    unittest.main()
