from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ptt_offline.month_static_publish import (
    MonthPublishError,
    MonthSource,
    build_month_package,
    publish_local_immutable,
    readback_http,
    run_owner_local,
)
from ptt_offline.month_static_release import RELEASE_SCHEMA, stage_release


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self,*_args):
        pass


class MonthStaticPublishTests(unittest.TestCase):
    def digest(self,path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def fixture(self,root: Path, *, status="PASS", complete="COMPLETE",
                orphan=False, duplicate_aid=False) -> MonthSource:
        db_path=root/"month.sqlite3"
        db=sqlite3.connect(db_path)
        db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,
          title_hint TEXT,created_at TEXT,last_seen_at TEXT,last_page INTEGER,
          total_pages INTEGER,last_source_line INTEGER);
        CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER REFERENCES articles(id),
          source_line INTEGER,source_page INTEGER,web_floor INTEGER,kind TEXT,author TEXT,
          content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
        CREATE TABLE article_provenance(article_id INTEGER PRIMARY KEY,roster_date TEXT,
          period TEXT,web_aid TEXT,ptt_aid TEXT,source_kind TEXT,source_path TEXT,
          source_sha256 TEXT,source_locator_semantics TEXT,declared_push_count INTEGER,
          parsed_push_count INTEGER,stored_push_count INTEGER,completeness_status TEXT,
          completeness_rule TEXT,logical_sha256 TEXT);
        """)
        db.executemany("INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?,?)",[
            (1,"C_Chat","#rawAid","https://www.ptt.cc/bbs/C_Chat/M.1780268403.A.FFB.html",
             "raw","2026-06-01T00:00:00Z","2026-06-01T00:00:00Z",1,1,20),
            (2,"C_Chat","#webAid","https://www.pttweb.cc/bbs/C_Chat/M.1780311280.A.5EF",
             "web","2026-06-01T00:00:00Z","2026-06-01T00:00:00Z",None,None,2),
        ])
        db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?,?)",[
            (1,1,10,1,None,"推","a","raw one","06/01","10:00","x"),
            (2,1,20,1,None,"推","b","raw two","06/01","10:01","x"),
            (3,2,1,0,1,"推","c","web one","06/01","20:00","x"),
            (4,2,2,0,2,"推","d","web two","06/01","20:01","x"),
        ])
        second_aid="#rawAid" if duplicate_aid else "#webAid"
        db.executemany("INSERT INTO article_provenance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",[
            (1,"2026-06-01","day","M.1780268403.A.FFB","#rawAid","Raw",
             "/Users/private/raw.sqlite3","1"*64,"collector_source_line",None,None,2,
             complete,"collector_raw_final_v1","2"*64),
            (2,"2026-06-01","night","M.1780311280.A.5EF",second_aid,"Web",
             "/Users/private/web.sqlite3","3"*64,"web_floor",2,2,2,
             complete,"web_declared_parsed_stored_contiguous_floor_v1","4"*64),
        ])
        db.commit()
        if orphan:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("INSERT INTO pushes VALUES(5,999,1,1,NULL,'推','x','orphan','06/01','21:00','x')")
        db.commit(); db.close()
        db_sha=self.digest(db_path)
        audit={"schema_version":1,"dataset":"issue403-month-202606-complete",
               "status":status,"output_sha256":db_sha,"quick_check":"ok",
               "foreign_key_errors":0,"duplicate_aids":0,"articles_complete":2,
               "web_failures":0,"table_counts":{"articles":2,
                   "article_provenance":2,"pushes":5 if orphan else 4},
               "source_kind_counts":{"Raw":1,"Web":1},
               "source_kind_push_counts":{"Raw":2,"Web":2},
               "articles":[
                   {"date":"2026-06-01","period":"day",
                    "web_aid":"M.1780268403.A.FFB","ptt_aid":"#rawAid",
                    "source_kind":"Raw","source_path":"/Users/private/raw.sqlite3",
                    "pushes":2,"completeness_rule":"collector_raw_final_v1",
                    "logical_sha256":"2"*64},
                   {"date":"2026-06-01","period":"night",
                    "web_aid":"M.1780311280.A.5EF","ptt_aid":second_aid,
                    "source_kind":"Web","source_path":"/Users/private/web.sqlite3",
                    "pushes":2,"completeness_rule":
                        "web_declared_parsed_stored_contiguous_floor_v1",
                    "logical_sha256":"4"*64},
               ]}
        audit_path=root/"audit.json"
        audit_path.write_text(json.dumps(audit,sort_keys=True),encoding="utf-8")
        return MonthSource(month="2026-06",sqlite_path=db_path,sqlite_sha256=db_sha,
                           audit_path=audit_path,audit_sha256=self.digest(audit_path),
                           article_count=2)

    def serve(self,root: Path):
        handler=lambda *a,**k:_Handler(*a,directory=str(root),**k)
        server=ThreadingHTTPServer(("127.0.0.1",0),handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        return server,thread

    def baseline(self,root: Path, *, key="ptt/v1/chunks/2026/05/01/0000.json",
                 body=b'{"old":true}') -> tuple[Path,dict]:
        public=root/"public"
        path=public/key
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(body)
        manifest={"schema_version":"ptt-r2-archive-v1","total_objects":1,
                  "total_pushes":1,"objects":[{"key":key,
                  "sha256":self.digest(path),"bytes_json":len(body)}]}
        manifest_key="ptt/v1/manifests/static-assets-full-2026-05.json"
        manifest_path=public/manifest_key
        manifest_path.parent.mkdir(parents=True,exist_ok=True)
        manifest_path.write_text(json.dumps(manifest,sort_keys=True),encoding="utf-8")
        return public,{"manifest_key":manifest_key,"sha256":self.digest(manifest_path)}

    def release_spec(self,root: Path,build: dict,baselines: list[dict]) -> Path:
        candidate={key:build[key] for key in (
            "month","source_sqlite_sha256","source_audit_sha256","manifest_key",
            "manifest_digest","registration_identity","article_set_sha256","articles",
            "pushes","objects")}
        spec={"schema_version":RELEASE_SCHEMA,"target":{"worker_name":"history-test",
              "base_url":"https://example.invalid"},"baselines":baselines,
              "candidate":candidate}
        path=root/"release-spec.json"
        path.write_text(json.dumps(spec),encoding="utf-8")
        return path

    def test_exact_sha_complete_source_builds_canonical_package(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); before=self.digest(spec.sqlite_path)
            result=build_month_package(spec,root/"package")
            self.assertEqual(result["status"],"PASS")
            self.assertEqual(result["source_completeness"],"COMPLETE")
            self.assertEqual(result["articles"],2)
            self.assertEqual(result["pushes"],4)
            self.assertEqual(self.digest(spec.sqlite_path),before)
            manifest=json.loads((root/"package/public"/result["manifest_key"]).read_text())
            self.assertEqual(manifest["schema_version"],"ptt-r2-archive-v1")
            self.assertEqual(manifest["delivery_target"],"workers-static-assets")
            self.assertTrue(all(item["key"].startswith(
                "ptt/v1/months/2026-06/chunks/") for item in manifest["objects"]))
            headers=(root/"package/public/_headers").read_text()
            for route in ("/ptt/v1/chunks/*","/ptt/v1/months/*",
                          "/ptt/v1/manifests/*","/ptt/v1/registrations/*",
                          "/ptt/v1/provenance/*"):
                self.assertIn(route,headers)

    def test_sqlite_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root)
            bad=MonthSource(**{**spec.__dict__,"sqlite_sha256":"0"*64})
            with self.assertRaisesRegex(MonthPublishError,"SQLite SHA"):
                build_month_package(bad,root/"package")

    def test_audit_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root)
            bad=MonthSource(**{**spec.__dict__,"audit_sha256":"0"*64})
            with self.assertRaisesRegex(MonthPublishError,"audit SHA"):
                build_month_package(bad,root/"package")

    def test_non_complete_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root,status="PARTIAL")
            with self.assertRaisesRegex(MonthPublishError,"not exact COMPLETE"):
                build_month_package(spec,root/"package")

    def test_sqlite_article_set_must_match_accepted_audit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root)
            audit=json.loads(spec.audit_path.read_text())
            audit["articles"][0]["logical_sha256"]="9"*64
            spec.audit_path.write_text(json.dumps(audit,sort_keys=True),encoding="utf-8")
            revised=MonthSource(**{**spec.__dict__,
                "audit_sha256":self.digest(spec.audit_path)})
            with self.assertRaisesRegex(MonthPublishError,"article set"):
                build_month_package(revised,root/"package")

    def test_duplicate_aid_fk_and_article_completeness_fail_closed(self):
        cases=[{"duplicate_aid":True},{"orphan":True},{"complete":"PARTIAL"}]
        for index,case in enumerate(cases):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                root=Path(td); spec=self.fixture(root,**case)
                with self.assertRaises(MonthPublishError):
                    build_month_package(spec,root/f"package-{index}")

    def test_identical_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"
            build_month_package(spec,package)
            first=publish_local_immutable(package_dir=package,target_root=root/"target")
            second=publish_local_immutable(package_dir=package,target_root=root/"target")
            self.assertEqual(first["status"],"succeeded")
            self.assertGreater(first["uploaded_count"],0)
            self.assertEqual(second["uploaded_count"],0)
            self.assertGreater(second["noop_count"],0)

    def test_two_independent_builds_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root)
            first=root/"package-a"; second=root/"package-b"
            a=build_month_package(spec,first); b=build_month_package(spec,second)
            self.assertEqual(a,b)
            first_files={str(path.relative_to(first)):self.digest(path)
                         for path in first.rglob("*") if path.is_file()}
            second_files={str(path.relative_to(second)):self.digest(path)
                          for path in second.rglob("*") if path.is_file()}
            self.assertEqual(first_files,second_files)

    def test_conflicting_month_registration_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"; target=root/"target"
            built=build_month_package(spec,package)
            publish_local_immutable(package_dir=package,target_root=target)
            path=target/built["registration_key"]
            body=json.loads(path.read_text()); body["registration_identity"]="f"*64
            path.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaisesRegex(MonthPublishError,"conflicting registration"):
                publish_local_immutable(package_dir=package,target_root=target)

    def test_tampered_package_fails_before_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"; target=root/"target"
            built=build_month_package(spec,package)
            manifest=json.loads((package/"public"/built["manifest_key"]).read_text())
            (package/"public"/manifest["objects"][0]["key"]).write_bytes(b"{}")
            with self.assertRaisesRegex(MonthPublishError,"object SHA"):
                publish_local_immutable(package_dir=package,target_root=target)
            self.assertFalse(target.exists())

    def test_release_stage_preserves_baseline_and_adds_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"
            build=build_month_package(spec,package)
            baseline,expected=self.baseline(root/"baseline")
            release=root/"release"
            result=stage_release(spec_path=self.release_spec(root,build,[expected]),
                                 month_package=package,baseline_public=[baseline],
                                 out_dir=release)
            self.assertEqual(result["status"],"PASS")
            self.assertFalse(result["production_execution"])
            self.assertGreater(result["deployable_bytes"],0)
            self.assertGreater(result["largest_asset_bytes"],0)
            self.assertEqual(self.digest(release/"public"/expected["manifest_key"]),
                             expected["sha256"])
            self.assertTrue((release/"public"/build["manifest_key"]).is_file())
            self.assertEqual(json.loads((release/"wrangler.jsonc").read_text())["name"],
                             "history-test")
            self.assertIn("OWNER_LOCAL=YES GITHUB_ACTIONS=NO CI_DEPLOY=NO",
                          result["owner_command"])

    def test_release_stage_rejects_tampered_baseline_and_key_collision(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"
            build=build_month_package(spec,package)
            baseline,expected=self.baseline(root/"baseline")
            (baseline/"ptt/v1/chunks/2026/05/01/0000.json").write_bytes(b"tampered")
            with self.assertRaisesRegex(MonthPublishError,"baseline object SHA"):
                stage_release(spec_path=self.release_spec(root,build,[expected]),
                              month_package=package,baseline_public=[baseline],
                              out_dir=root/"release-tampered")

        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"
            build=build_month_package(spec,package)
            manifest=json.loads((package/"public"/build["manifest_key"]).read_text())
            candidate_key=manifest["objects"][0]["key"]
            baseline,expected=self.baseline(root/"baseline",key=candidate_key,
                                            body=b'{"different":true}')
            with self.assertRaisesRegex(MonthPublishError,"release key collision"):
                stage_release(spec_path=self.release_spec(root,build,[expected]),
                              month_package=package,baseline_public=[baseline],
                              out_dir=root/"release-collision")

    def test_delivery_failure_keeps_source_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"
            build=build_month_package(spec,package)
            result=publish_local_immutable(package_dir=package,target_root=root/"target",
                                           simulate_failure=True)
            self.assertEqual(build["source_completeness"],"COMPLETE")
            self.assertEqual(result["source_completeness"],"COMPLETE")
            self.assertEqual(result["status"],"failed")

    def test_http_hash_mismatch_is_not_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"; target=root/"target"
            built=build_month_package(spec,package)
            publish_local_immutable(package_dir=package,target_root=target)
            manifest=json.loads((target/built["manifest_key"]).read_text())
            (target/manifest["objects"][0]["key"]).write_bytes(b"{}")
            server,thread=self.serve(target)
            try:
                receipt=readback_http(base_url=f"http://127.0.0.1:{server.server_port}",
                    registration_key=built["registration_key"],job_id="fixture-job",
                    observed_at="2026-10-21T00:00:00Z",target_identity="owner-local",
                    expected_registration_identity=built["registration_identity"])
            finally:
                server.shutdown(); thread.join(); server.server_close()
            self.assertFalse(receipt["job_verified"])
            self.assertEqual(receipt["error_code"],"object_hash_mismatch")

    def test_http_readback_rejects_registration_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"; target=root/"target"
            built=build_month_package(spec,package)
            publish_local_immutable(package_dir=package,target_root=target)
            registration=target/built["registration_key"]
            body=json.loads(registration.read_text())
            body["registration_identity"]="f"*64
            registration.write_bytes(json.dumps(body,sort_keys=True,
                separators=(",",":")).encode())
            server,thread=self.serve(target)
            try:
                receipt=readback_http(base_url=f"http://127.0.0.1:{server.server_port}",
                    registration_key=built["registration_key"],job_id="fixture-job",
                    observed_at="2026-10-21T00:00:00Z",target_identity="owner-local",
                    expected_registration_identity=built["registration_identity"])
            finally:
                server.shutdown(); thread.join(); server.server_close()
            self.assertFalse(receipt["job_verified"])
            self.assertFalse(receipt["coverage_scope_match"])

    def test_unrelated_month_bytes_are_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"; target=root/"target"
            unrelated=target/"ptt/v1/registrations/2026-05.json"
            unrelated.parent.mkdir(parents=True); unrelated.write_bytes(b"unchanged")
            before=self.digest(unrelated)
            build_month_package(spec,package)
            publish_local_immutable(package_dir=package,target_root=target)
            self.assertEqual(self.digest(unrelated),before)

    def test_raw_web_provenance_is_preserved_without_absolute_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root); package=root/"package"
            built=build_month_package(spec,package)
            manifest=json.loads((package/"public"/built["manifest_key"]).read_text())
            provenance=json.loads((package/"public"/manifest["provenance"]["key"]).read_text())
            self.assertEqual({x["source_kind"] for x in provenance["articles"]},{"Raw","Web"})
            self.assertEqual({x["source_path"] for x in provenance["articles"]},
                             {"raw.sqlite3","web.sqlite3"})
            for path in (package/"public").rglob("*.json"):
                self.assertNotIn(b"/Users/",path.read_bytes())

    def test_one_command_owner_local_pipeline_builds_delivers_and_reads_back(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); spec=self.fixture(root)
            result=run_owner_local(spec=spec,package_dir=root/"package",
                                   target_root=root/"target",
                                   observed_at="2026-10-21T00:00:00Z")
            self.assertEqual(result["delivery"]["status"],"succeeded")
            self.assertTrue(result["readback"]["job_verified"])
            self.assertTrue(result["evidence"]["job_verified"])
            self.assertFalse(result["production_execution"])
            self.assertFalse(result["r2_execution"])


if __name__=="__main__":
    unittest.main()
