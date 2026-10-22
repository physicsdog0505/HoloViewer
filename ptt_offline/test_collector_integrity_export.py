from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

from ptt_offline.collector_integrity_export import export_article_integrity


class CollectorIntegrityExportTests(unittest.TestCase):
    def make_db(self):
        tmp=tempfile.TemporaryDirectory()
        path=Path(tmp.name)/"collector.sqlite3"
        db=sqlite3.connect(path)
        db.execute("""CREATE TABLE articles(
            id INTEGER PRIMARY KEY, board TEXT, aid TEXT, url TEXT,
            title_hint TEXT, created_at TEXT, last_seen_at TEXT,
            last_page INTEGER, total_pages INTEGER, last_source_line INTEGER)""")
        db.execute("""CREATE TABLE pushes(
            id INTEGER PRIMARY KEY, article_id INTEGER, source_line INTEGER,
            source_page INTEGER, kind TEXT, author TEXT, content TEXT,
            ptt_date TEXT, ptt_time TEXT, collected_at TEXT,
            UNIQUE(article_id,source_line))""")
        db.execute("""CREATE TABLE article_screens(
            id INTEGER PRIMARY KEY, article_id INTEGER, source_page INTEGER,
            total_pages INTEGER, start_line INTEGER, end_line INTEGER,
            captured_at TEXT, UNIQUE(article_id,start_line,end_line))""")
        db.execute("""INSERT INTO articles VALUES(
            1,'C_Chat','1fixture',
            'https://www.ptt.cc/bbs/C_Chat/M.1.A.001.html',
            'Hololive 日間直播單 (1151020)',
            '2026-10-20T00:00:00+00:00','2026-10-20T06:20:00+00:00',
            1,1,6)""")
        return tmp,db

    def test_complete_screen_coverage_classifies_non_push_and_empty_push(self):
        tmp,db=self.make_db()
        try:
            db.execute("""INSERT INTO article_screens VALUES(
                1,1,1,1,1,6,'2026-10-20T06:20:00+00:00')""")
            db.executemany("""INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)""",[
                (1,1,3,1,'推','u','hello','10/20','14:00','2026-10-20T06:00:10+00:00'),
                (2,1,4,1,'→','u','','10/20','14:01','2026-10-20T06:01:10+00:00'),
                (3,1,6,1,'噓','u','bye','10/20','14:02','2026-10-20T06:02:10+00:00'),
            ])
            body=export_article_integrity(db,day='2026-10-20',aid='1fixture',authoritative_remote_tail=6)
        finally:
            db.close(); tmp.cleanup()
        self.assertEqual(body["source_coverage"]["status"],"COMPLETE")
        self.assertEqual(body["source_coverage"]["missing_source_lines"],[])
        self.assertEqual(body["line_classification"]["push_count"],3)
        self.assertEqual(body["line_classification"]["non_push_count"],3)
        self.assertEqual(body["line_classification"]["legal_empty_push_count"],1)
        self.assertEqual(body["source_coverage"]["legal_empty_push_source_lines"],[4])
        self.assertEqual(body["source_coverage"]["non_push_source_lines"],[1,2,5])
        self.assertEqual(body["collector_semantic"]["semantic_check"]["watermark_source_line"],6)
        self.assertEqual(body["contract_gaps"],[])
        self.assertNotIn("hello",str(body))
        self.assertNotIn('"u"',str(body))

    def test_screen_gap_fails_closed_instead_of_inventing_non_push_rows(self):
        tmp,db=self.make_db()
        try:
            db.executemany("""INSERT INTO article_screens VALUES(?,?,?,?,?,?,?)""",[
                (1,1,1,1,1,2,'2026-10-20T06:20:00+00:00'),
                (2,1,1,1,5,6,'2026-10-20T06:20:00+00:00'),
            ])
            db.execute("""INSERT INTO pushes VALUES(
                1,1,6,1,'推','u','visible','10/20','14:02',
                '2026-10-20T06:02:10+00:00')""")
            body=export_article_integrity(db,day='2026-10-20',aid='1fixture',authoritative_remote_tail=6)
        finally:
            db.close(); tmp.cleanup()
        self.assertEqual(body["source_coverage"]["status"],"REPAIR_NEEDED")
        self.assertEqual(body["source_coverage"]["missing_source_lines"],[3,4])
        self.assertIn("collector-source-line-gap",body["contract_gaps"])
        self.assertEqual(
            body["collector_semantic"]["semantic_check"]["source_line_gaps"],[[3,4]]
        )
        classified={x["source_line"] for x in body["line_classification"]["lines"]}
        self.assertNotIn(3,classified)
        self.assertNotIn(4,classified)

    def test_screen_coverage_behind_article_final_reports_gap(self):
        tmp,db=self.make_db()
        try:
            db.execute("""INSERT INTO article_screens VALUES(
                1,1,1,1,1,4,'2026-10-20T06:20:00+00:00')""")
            body=export_article_integrity(db,day='2026-10-20',aid='1fixture',authoritative_remote_tail=6)
        finally:
            db.close(); tmp.cleanup()
        self.assertEqual(body["source_coverage"]["status"],"REPAIR_NEEDED")
        self.assertEqual(body["source_coverage"]["missing_source_lines"],[5,6])
        self.assertIn(
            "collector-screen-coverage-behind-local-tail",
            body["contract_gaps"],
        )


    def test_remote_tail_ahead_forces_bounded_tail_repair(self):
        tmp,db=self.make_db()
        try:
            db.execute("""INSERT INTO article_screens VALUES(
                1,1,1,1,1,6,'2026-10-20T06:20:00+00:00')""")
            body=export_article_integrity(
                db,day='2026-10-20',aid='1fixture',
                authoritative_remote_tail=10,
            )
        finally:
            db.close(); tmp.cleanup()
        self.assertEqual(body["source_coverage"]["status"],"REPAIR_NEEDED")
        self.assertEqual(body["source_coverage"]["local_tail_source_line"],6)
        self.assertEqual(body["source_coverage"]["authoritative_remote_tail"],10)
        self.assertFalse(body["source_coverage"]["tail_parity_confirmed"])
        self.assertEqual(body["source_coverage"]["tail_repair_range"],[7,10])
        self.assertEqual(body["source_coverage"]["missing_source_lines"],[7,8,9,10])
        self.assertEqual(body["tail_completeness"]["repair_range"],[7,10])
        self.assertEqual(
            body["collector_semantic"]["semantic_check"]["watermark_source_line"],6
        )
        self.assertEqual(
            body["collector_semantic"]["semantic_check"]["final_source_line"],10
        )

    def test_missing_remote_tail_never_verifies_complete(self):
        tmp,db=self.make_db()
        try:
            db.execute("""INSERT INTO article_screens VALUES(
                1,1,1,1,1,6,'2026-10-20T06:20:00+00:00')""")
            body=export_article_integrity(db,day='2026-10-20',aid='1fixture')
        finally:
            db.close(); tmp.cleanup()
        self.assertEqual(body["source_coverage"]["status"],"REPAIR_NEEDED")
        self.assertFalse(body["source_coverage"]["tail_parity_confirmed"])
        self.assertIn("authoritative-remote-tail-unavailable",body["contract_gaps"])


if __name__=="__main__":
    unittest.main()
