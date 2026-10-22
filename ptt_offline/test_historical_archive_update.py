import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ptt_offline.historical_archive_update import (
    audit_static,
    build_archive,
    build_static,
)
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.r2_archive_export import write_archive_rows


TPE = ZoneInfo("Asia/Taipei")


class HistoricalArchiveUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.sqlite3"
        posted = datetime(2026, 10, 17, 9, 0, tzinfo=TPE)
        self.url = (
            f"https://www.ptt.cc/bbs/C_Chat/M.{int(posted.timestamp())}.A.001.html"
        )
        _, self.aid = aid_from_article_url(self.url)
        with sqlite3.connect(self.source) as db:
            db.executescript("""
                CREATE TABLE articles (
                  id INTEGER PRIMARY KEY, board TEXT, aid TEXT, url TEXT,
                  title_hint TEXT, created_at TEXT, last_seen_at TEXT,
                  last_page INTEGER, total_pages INTEGER, last_source_line INTEGER);
                CREATE TABLE pushes (
                  id INTEGER PRIMARY KEY, article_id INTEGER, source_line INTEGER,
                  source_page INTEGER, kind TEXT, author TEXT, content TEXT,
                  ptt_date TEXT, ptt_time TEXT, collected_at TEXT);
                CREATE TABLE article_screens (
                  id INTEGER PRIMARY KEY, article_id INTEGER, source_page INTEGER,
                  total_pages INTEGER, start_line INTEGER, end_line INTEGER,
                  captured_at TEXT);
            """)
            db.execute(
                "INSERT INTO articles VALUES(1,'C_Chat',?,?,?,?,?,1,1,3)",
                (self.aid, self.url, "Hololive 本日直播單 (1151017)",
                 posted.isoformat(), posted.isoformat()),
            )
            db.executemany(
                "INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",
                [
                    (1, 1, 2, 1, "推", "a", "first", "10/17", "10:01", posted.isoformat()),
                    (2, 1, 3, 1, "推", "b", "recovered", "10/17", "10:02", posted.isoformat()),
                ],
            )
            db.execute(
                "INSERT INTO article_screens VALUES(1,1,1,1,1,3,?)",
                (posted.isoformat(),),
            )

        self.baseline = self.root / "baseline"
        rows = [
            {
                "occurred_at": "2026-10-16T01:00:00Z", "aid": "OLD",
                "source_line": 1, "source_page": 1, "kind": "推", "author": "u",
                "content": "preserved", "source_url": "https://example.invalid/old",
                "source_path": "/accepted.sqlite3", "source_record_key": "OLD:1",
                "time_quality": "source-minute", "floor": 1,
                "floor_quality": "per-thread-ordinal", "coverage_day": "2026-10-16",
            },
            {
                "occurred_at": "2026-10-17T02:01:00Z", "aid": self.aid,
                "source_line": 2, "source_page": 1, "kind": "推", "author": "a",
                "content": "first", "source_url": self.url,
                "source_path": str(self.source),
                "source_record_key": f"{self.aid}:2", "time_quality": "source-minute",
                "ptt_date": "10/17", "ptt_time": "10:01",
                "floor": 1, "floor_quality": "per-thread-ordinal",
                "coverage_day": "2026-10-17",
            },
        ]
        days = [
            {"day": "2026-10-16", "coverage_status": "COMPLETE", "finalized": True,
             "reason": "accepted"},
            {"day": "2026-10-17", "coverage_status": "PARTIAL", "finalized": False,
             "reason": "gap"},
        ]
        write_archive_rows(
            rows, from_day="2026-10-16", through_day="2026-10-17",
            out_dir=self.baseline, days=days, manifest_name="baseline.json",
            generated_at="2026-10-18T00:00:00Z",
        )

    def test_repair_adds_only_missing_identity_and_preserves_prior_gzip(self):
        spec = self.root / "spec.json"
        spec.write_text(json.dumps({
            "generated_at": "2026-10-18T00:00:00Z",
            "archive_manifest_name": "repaired.json",
            "preserve_baseline_days": ["2026-10-16"],
            "sources": [{"path": str(self.source), "from_day": "2026-10-17",
                         "through_day": "2026-10-17"}],
            "days": [{"day": "2026-10-17", "required_aids": [self.aid]}],
        }), encoding="utf-8")
        archive = self.root / "archive"
        receipt = build_archive(
            baseline_root=self.baseline, baseline_manifest="baseline.json",
            spec_path=spec, archive_out=archive,
        )
        self.assertEqual(receipt["identities_added"], 1)
        self.assertEqual(receipt["baseline_identities_removed"], 0)
        self.assertEqual(receipt["total_pushes"], 3)
        self.assertTrue(receipt["preserved_baseline_gzip_objects_byte_identical"])
        old_key = "ptt/v1/chunks/2026/10/16/0100.json.gz"
        self.assertEqual((self.baseline / old_key).read_bytes(),
                         (archive / old_key).read_bytes())

        package = self.root / "package/public"
        static = build_static(
            archive_root=archive, archive_manifest="repaired.json",
            static_out=package, static_manifest_name="static-repaired.json",
        )
        self.assertEqual(static["status"], "PASS")
        self.assertFalse(list(package.rglob("*.gz")))
        self.assertNotIn("Content-Encoding", (package / "_headers").read_text())
        self.assertEqual(
            audit_static(archive_root=archive, archive_manifest="repaired.json",
                         static_out=package, static_manifest_name="static-repaired.json")
            ["total_pushes"],
            3,
        )


if __name__ == "__main__":
    unittest.main()
