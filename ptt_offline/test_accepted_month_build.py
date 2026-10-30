from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from ptt_offline.accepted_month_build import (
    AcceptedMonthError,
    AcceptedMonthSpec,
    build_accepted_month,
)
from ptt_offline.month_static_publish import MonthSource, build_month_package, run_owner_local


class AcceptedMonthBuildTests(unittest.TestCase):
    def digest(self,path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def raw_fixture(self,path: Path, *, gap: bool=False) -> None:
        db=sqlite3.connect(path)
        db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,
          title_hint TEXT,created_at TEXT,last_seen_at TEXT,last_page INTEGER,
          total_pages INTEGER,last_source_line INTEGER);
        CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,
          source_page INTEGER,kind TEXT,author TEXT,content TEXT,ptt_date TEXT,
          ptt_time TEXT,collected_at TEXT);
        CREATE TABLE article_source_lines(id INTEGER PRIMARY KEY,article_id INTEGER,
          source_line INTEGER,source_page INTEGER,content TEXT,captured_at TEXT);
        CREATE TABLE article_screens(id INTEGER PRIMARY KEY,article_id INTEGER,
          source_page INTEGER,total_pages INTEGER,start_line INTEGER,end_line INTEGER,
          captured_at TEXT);
        INSERT INTO articles VALUES(1,'C_Chat','#raw','https://www.ptt.cc/raw','raw',
          '2026-07-01T00:00:00Z','2026-07-01T00:00:00Z',2,2,4);
        INSERT INTO pushes VALUES(1,1,2,1,'推','a','one','07/01','10:00','x');
        INSERT INTO pushes VALUES(2,1,4,2,'推','b','two','07/01','10:01','x');
        INSERT INTO article_source_lines VALUES(1,1,1,1,'l1','x');
        INSERT INTO article_source_lines VALUES(2,1,2,1,'l2','x');
        INSERT INTO article_source_lines VALUES(3,1,3,2,'l3','x');
        INSERT INTO article_source_lines VALUES(4,1,4,2,'l4','x');
        INSERT INTO article_screens VALUES(1,1,1,2,1,2,'x');
        INSERT INTO article_screens VALUES(2,1,2,2,2,4,'x');
        """)
        if gap:
            db.execute("DELETE FROM article_source_lines WHERE source_line=3")
        db.commit(); db.close()

    def web_fixture(self,path: Path, *, floor_gap: bool=False) -> None:
        db=sqlite3.connect(path)
        db.executescript("""
        CREATE TABLE web_articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,title TEXT,
          source_url TEXT,declared_push_count INTEGER,parsed_push_count INTEGER,fetched_at TEXT);
        CREATE TABLE web_pushes(id INTEGER PRIMARY KEY,web_article_id INTEGER,floor INTEGER,
          kind TEXT,author TEXT,content TEXT,ptt_date TEXT,ptt_time TEXT,fetched_at TEXT);
        CREATE TABLE web_article_bodies(web_article_id INTEGER PRIMARY KEY,body_text TEXT,
          fetched_at TEXT);
        INSERT INTO web_articles VALUES(1,'C_Chat','M.1782902570.A.001','web','https://pttweb/web',
          2,2,'2026-07-01T00:00:00Z');
        INSERT INTO web_pushes VALUES(1,1,1,'推','c','web one','07/01','20:00','x');
        INSERT INTO web_pushes VALUES(2,1,2,'推','d','web two','07/01','20:01','x');
        INSERT INTO web_article_bodies VALUES(1,'body','x');
        """)
        if floor_gap:
            db.execute("UPDATE web_pushes SET floor=3 WHERE floor=2")
        db.commit(); db.close()

    def accepted_fixture(self,root: Path, *, raw_gap=False, web_gap=False,
                         high_kind="Raw") -> tuple[AcceptedMonthSpec,Path]:
        raw=root/"raw.sqlite3"; web=root/"web.sqlite3"
        self.raw_fixture(raw,gap=raw_gap); self.web_fixture(web,floor_gap=web_gap)
        accepted={
          "schema_version":"holoviewer-ptt-accepted-month-v1","month":"2026-07",
          "policy":{"raw_required_at_or_above":3},
          "expected":{"articles":2,"high_risk_raw":1,"low_risk_web":1},
          "evidence":{"ledger_commit":"a"*40},
          "web_source":{"basename":web.name,"sha256":self.digest(web)},
          "raw_sources":[{"basename":raw.name,"sha256":self.digest(raw)}],
          "articles":[
            {"date":"2026-07-01","period":"day","web_aid":"M.1782860441.A.000",
             "ptt_aid":"#raw","gate_push_count":3,
             "expected_stored_push_count":2,"accepted_source_kind":high_kind,
             "source_basename":raw.name,"source_sha256":self.digest(raw)},
            {"date":"2026-07-01","period":"night","web_aid":"M.1782902570.A.001",
             "ptt_aid":"#web","gate_push_count":2,
             "expected_stored_push_count":2,"accepted_source_kind":"Web",
             "source_basename":web.name,"source_sha256":self.digest(web)},
          ]}
        accepted_path=root/"accepted.json"
        accepted_path.write_text(json.dumps(accepted,sort_keys=True),encoding="utf-8")
        spec=AcceptedMonthSpec(accepted_path,root,web,root/"month.sqlite3",root/"audit.json")
        return spec,accepted_path

    def test_per_aid_gates_build_authoritative_month(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec,_=self.accepted_fixture(root)
            result=build_accepted_month(spec)
            self.assertEqual(result["articles"],2)
            self.assertEqual(result["high_risk_raw"],1)
            self.assertEqual(result["low_risk_web"],1)
            self.assertEqual(result["missing_aids"],[])
            with sqlite3.connect(spec.output_sqlite_path) as db:
                self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0],"ok")
                self.assertEqual(db.execute("SELECT count(DISTINCT ptt_aid) FROM article_provenance").fetchone()[0],2)
                self.assertEqual(db.execute("SELECT count(*) FROM article_source_lines").fetchone()[0],4)
            audit=json.loads(spec.output_audit_path.read_text())
            self.assertEqual(audit["accepted_set"]["high_risk_raw"],1)
            self.assertEqual(audit["accepted_set"]["low_risk_web"],1)

    def test_output_feeds_existing_month_static_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec,_=self.accepted_fixture(root)
            built=build_accepted_month(spec)
            month=MonthSource("2026-07",spec.output_sqlite_path,built["sqlite_sha256"],
                              spec.output_audit_path,built["audit_sha256"],2)
            package=build_month_package(month,root/"package")
            self.assertEqual(package["articles"],2)
            self.assertEqual(package["source_kind_counts"],{"Raw":1,"Web":1})
            local=run_owner_local(spec=month,package_dir=root/"package-readback",
                                  target_root=root/"target",
                                  observed_at="2026-10-28T00:00:00Z")
            self.assertEqual(local["evidence"]["expected_aid_completeness"]["authority"],
                             "per-aid-accepted-set-v1")

    def test_raw_gap_and_web_floor_gap_fail_closed(self):
        for kwargs,message in (({"raw_gap":True},"source-line"),
                               ({"web_gap":True},"Web completeness")):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as td:
                spec,_=self.accepted_fixture(Path(td),**kwargs)
                with self.assertRaisesRegex(AcceptedMonthError,message):
                    build_accepted_month(spec)

    def test_high_risk_web_binding_is_rejected_before_source_read(self):
        with tempfile.TemporaryDirectory() as td:
            spec,_=self.accepted_fixture(Path(td),high_kind="Web")
            with self.assertRaisesRegex(AcceptedMonthError,"high-risk"):
                build_accepted_month(spec)

    def test_source_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec,accepted_path=self.accepted_fixture(root)
            accepted=json.loads(accepted_path.read_text())
            accepted["raw_sources"][0]["sha256"]="0"*64
            accepted_path.write_text(json.dumps(accepted),encoding="utf-8")
            with self.assertRaisesRegex(AcceptedMonthError,"Raw source SHA"):
                build_accepted_month(spec)

    def test_outputs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec,_=self.accepted_fixture(root)
            first=build_accepted_month(spec)
            first_sqlite=spec.output_sqlite_path.read_bytes()
            first_audit=spec.output_audit_path.read_bytes()
            spec.output_sqlite_path.unlink(); spec.output_audit_path.unlink()
            second=build_accepted_month(spec)
            self.assertEqual(first["sqlite_sha256"],second["sqlite_sha256"])
            self.assertEqual(first_sqlite,spec.output_sqlite_path.read_bytes())
            self.assertEqual(first_audit,spec.output_audit_path.read_bytes())


if __name__=="__main__":
    unittest.main()
