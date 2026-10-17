import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from ptt_offline.live_capture_publisher import active_article_ids,content_digest,inspect_latest_article,run_live_once,state_for_source
from ptt_offline.audit_live_line import audit
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.public_today_contract import ContractError

class LiveCapturePublisherTests(unittest.TestCase):
    def test_ack_preserves_reconciled_remote_commit_marker(self):
        from unittest.mock import patch
        import json, tempfile
        from pathlib import Path

        row={
            "push_id":"p1","aid":"#1abc","day":"2026-10-17","source_line":1,
            "kind":"push","author":"u","content":"x","occurred_at":"2026-10-17T07:00:00Z",
            "floor":1,"source_url":"https://www.ptt.cc/bbs/C_Chat/M.1.A.1.html",
            "source_record_key":"#1abc:1",
        }
        plan={
            "status":"READY","aid":"#1abc","source_identity":"a"*64,
            "candidate_rows":[row],"pending_source_lines":[],"scan_truncated":False,
        }
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"state.json"
            path.write_text(json.dumps({
                "status":"ACKED","source_identity":"a"*64,"accepted":{},
                "legacy_backlog_fence_v2":True,
                "reconciled_from_remote_commit":True,
            }),encoding="utf-8")
            ack={"batch_id":"dummy","accepted":1}
            with patch("ptt_offline.live_capture_publisher.inspect_latest_article",return_value=plan), \
                 patch("ptt_offline.live_capture_publisher.sign_time_proof",return_value="proof"), \
                 patch("ptt_offline.live_capture_publisher.execute_once",return_value=ack), \
                 patch("ptt_offline.live_capture_publisher.apply_ack",return_value=None):
                result=run_live_once(object(),state_path=path,secret="s"*32,executor=lambda *_: None,
                    send=True,batch_cap=1,now=datetime.fromisoformat("2026-10-17T07:01:00+00:00"))
            self.assertEqual(result["status"],"ACK")
            saved=json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(saved["reconciled_from_remote_commit"])


    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state=str(Path(self.tmp.name)/"live-state.json")
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        url="https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html"
        self.aid=aid_from_article_url(url)[1]
        self.db.executescript("""
          CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,title_hint TEXT,created_at TEXT,last_seen_at TEXT);
          CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
        """)
        self.db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'t','now','now')",(self.aid,url))
        self.db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",[
          (1,1,1,1,'推','a','old historical','10/14','09:00','2026-10-15T10:00:00Z'),
          (2,1,2,1,'推','b','new one','10/15','18:00','2026-10-15T10:01:05Z'),
          (3,1,3,1,'→','c','new two','10/15','18:01','2026-10-15T10:02:07Z')])
    def test_recent_articles_select_separate_active_aids(self):
        url="https://www.ptt.cc/bbs/C_Chat/M.1789081300.A.5FC.html"
        aid=aid_from_article_url(url)[1]
        self.db.execute("INSERT INTO articles VALUES(2,'C_Chat',?,?,'night','now','now')",(aid,url))
        self.db.execute("INSERT INTO pushes VALUES(4,2,1,1,'推','new','night line','10/15','18:03','2026-10-15T10:04:00Z')")
        self.assertEqual(active_article_ids(self.db,limit=2),[2,1])
        first=inspect_latest_article(self.db,article_id=1)
        second=inspect_latest_article(self.db,article_id=2)
        self.assertNotEqual(first["source_identity"],second["source_identity"])
        self.assertEqual(first["aid"],self.aid)
        self.assertEqual(second["aid"],aid)
    def test_per_thread_state_separates_day_night_receipts(self):
        directory=Path(self.tmp.name)
        self.assertNotEqual(state_for_source(directory,"a"*64),
                            state_for_source(directory,"b"*64))
        with self.assertRaisesRegex(ContractError,"invalid canonical source identity"):
            state_for_source(directory,"not-an-identity")

    def test_pending_old_does_not_block_new_source_lines(self):
        inspected=inspect_latest_article(self.db)
        self.assertEqual(len(inspected["candidate_rows"]),2)
        self.assertEqual(inspected["pending_source_lines"],[1])
        self.assertTrue(all(x["day"]=="2026-10-15" for x in inspected["candidate_rows"]))
    def test_verified_chronology_recovers_25_minute_delayed_collector_row(self):
        self.db.execute(
            "INSERT INTO pushes VALUES(4,1,4,1,'→','late','delayed live row','10/16','06:36','2026-10-15T23:01:23Z')"
        )
        plan=inspect_latest_article(self.db)
        row=next(x for x in plan["candidate_rows"] if x["source_line"]==4)
        self.assertEqual(row["occurred_at"],"2026-10-15T22:36:00Z")
        self.assertEqual(row["day"],"2026-10-16")
        self.assertNotIn(4,plan["pending_source_lines"])

    def test_verified_chronology_still_rejects_more_than_two_hour_collection_delay(self):
        self.db.execute(
            "INSERT INTO pushes VALUES(4,1,4,1,'→','late','too late','10/16','06:36','2026-10-16T01:01:23Z')"
        )
        plan=inspect_latest_article(self.db)
        self.assertIn(4,plan["pending_source_lines"])
        self.assertFalse(any(x["source_line"]==4 for x in plan["candidate_rows"]))

    def test_naive_collector_timestamp_cannot_recover_delayed_row(self):
        self.db.execute(
            "INSERT INTO pushes VALUES(4,1,4,1,'→','late','naive time','10/16','06:36','2026-10-15T23:01:23')"
        )
        plan=inspect_latest_article(self.db)
        self.assertIn(4,plan["pending_source_lines"])
        self.assertFalse(any(x["source_line"]==4 for x in plan["candidate_rows"]))

    def test_exact_source_line_audit_is_read_only_and_redacted(self):
        self.db.execute(
            "INSERT INTO pushes VALUES(4,1,4,1,'→','late','do not disclose','10/16','06:36','2026-10-15T23:01:23Z')"
        )
        filename=str(Path(self.tmp.name)/"collector.sqlite3")
        self.db.commit()
        on_disk=sqlite3.connect(filename)
        try:
            self.db.backup(on_disk)
        finally:
            on_disk.close()
        receipt=audit(filename,self.aid,4)
        self.assertEqual(receipt["status"],"ELIGIBLE")
        self.assertEqual(receipt["occurred_at"],"2026-10-15T22:36:00Z")
        self.assertEqual(receipt["day"],"2026-10-16")
        self.assertEqual(receipt["remote_writes"],0)
        self.assertNotIn("do not disclose",str(receipt))

    def test_exact_source_line_audit_accepts_hash_prefixed_collector_aid(self):
        self.db.execute("UPDATE articles SET aid=? WHERE id=1",("#"+self.aid,))
        self.db.execute(
            "INSERT INTO pushes VALUES(4,1,4,1,'→','late','redacted','10/16','06:36','2026-10-15T23:01:23Z')"
        )
        self.db.commit()
        filename=str(Path(self.tmp.name)/"collector-hash.sqlite3")
        target=sqlite3.connect(filename)
        try:
            self.db.backup(target)
        finally:
            target.close()
        receipt=audit(filename,"#"+self.aid,4)
        self.assertEqual(receipt["status"],"ELIGIBLE")
        self.assertEqual(receipt["occurred_at"],"2026-10-15T22:36:00Z")

    def test_bounded_scan_tracks_all_normal_100_plus_lines(self):
        self.db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",[
          (n,1,n,1,'推','a',f'bulk-{n}','10/15','18:01','2026-10-15T10:02:07Z')
          for n in range(4,102)])
        plan=inspect_latest_article(self.db)
        self.assertEqual(plan["checked_source_rows"],101)
        self.assertFalse(plan["scan_truncated"])
        limited=inspect_latest_article(self.db,max_rows=100)
        self.assertTrue(limited["scan_truncated"])
        self.assertEqual(limited["checked_source_rows"],101)

    def test_existing_rows_baseline_without_remote_write_then_new_push_acks_once(self):
        calls=[]
        baseline=run_live_once(self.db,state_path=self.state,secret="k"*40,
            executor=lambda batch: calls.append(batch),send=True)
        self.assertEqual(baseline["status"],"BASELINED")
        self.assertEqual(baseline["sent"],0)
        self.assertEqual(baseline["eligible"],0)
        self.assertEqual(calls,[])
        # A genuinely new near-live row after the baseline publishes normally.
        self.db.execute("INSERT INTO pushes VALUES(4,1,4,1,'推','d','after baseline','10/15','18:03','2026-10-15T10:03:30Z')")
        def approve(batch):
            calls.append(batch)
            self.assertEqual(len(batch["rows"]),1)
            self.assertEqual(batch["rows"][0]["source_line"],4)
            return {"status":"ACK","batch_id":batch["batch_id"],"digest":batch["digest"],
              "logical_rows_acked":1,"d1_query_count":7,"d1_rows_written":4,
              "http_requests":1}
        result=run_live_once(self.db,state_path=self.state,secret="k"*40,
                             executor=approve,send=True,
                             now=datetime.fromisoformat("2026-10-15T10:04:00+00:00"))
        self.assertEqual(result["status"],"ACK")
        self.assertEqual(result["sent"],1)
        second=run_live_once(self.db,state_path=self.state,secret="k"*40,
                              executor=lambda _:self.fail("must not replay"),send=True)
        self.assertEqual(second["status"],"NO_NEW_ROWS")

    def test_legacy_state_quarantines_only_rows_older_than_two_hours(self):
        plan=inspect_latest_article(self.db)
        accepted={plan["candidate_rows"][0]["source_record_key"]:"x"}
        # Use a syntactically valid legacy state with no fence marker and no
        # accepted rows, matching pre-upgrade production shape.
        Path(self.state).write_text(json.dumps({
            "status":"ACKED",
            "source_identity":plan["source_identity"],
            "accepted":{},
        }),encoding="utf-8")
        seen=[]
        def approve(batch):
            seen.extend(batch["rows"])
            return {"status":"ACK","batch_id":batch["batch_id"],"digest":batch["digest"],
              "logical_rows_acked":len(batch["rows"]),"d1_query_count":2+5*len(batch["rows"]),
              "d1_rows_written":2+2*len(batch["rows"]),"http_requests":1}
        result=run_live_once(
            self.db,state_path=self.state,secret="k"*40,executor=approve,send=True,
            now=datetime.fromisoformat("2026-10-15T10:02:30+00:00")
        )
        self.assertEqual(result["legacy_baselined"],0)
        self.assertEqual(result["sent"],2)
        body=json.loads(Path(self.state).read_text(encoding="utf-8"))
        self.assertTrue(body["legacy_backlog_fence_v2"])

        # A separate legacy state observed much later must baseline the same old
        # rows locally instead of sending them as historical catch-up.
        late=str(Path(self.tmp.name)/"legacy-late.json")
        Path(late).write_text(json.dumps({
            "status":"ACKED",
            "source_identity":plan["source_identity"],
            "accepted":{},
        }),encoding="utf-8")
        result=run_live_once(
            self.db,state_path=late,secret="k"*40,
            executor=lambda _:self.fail("old legacy backlog must not post"),send=True,
            now=datetime.fromisoformat("2026-10-15T13:00:00+00:00")
        )
        self.assertEqual(result["legacy_baselined"],2)
        self.assertEqual(result["sent"],0)
        self.assertEqual(result["status"],"NO_NEW_ROWS")
        body=json.loads(Path(late).read_text(encoding="utf-8"))
        self.assertTrue(body["legacy_backlog_fence_v2"])

    def test_new_baseline_keeps_delayed_recovery_path_enabled(self):
        baseline=run_live_once(self.db,state_path=self.state,secret="k"*40,
            executor=lambda _:self.fail("baseline must not post"),send=True)
        self.assertEqual(baseline["status"],"BASELINED")
        body=json.loads(Path(self.state).read_text(encoding="utf-8"))
        self.assertTrue(body["legacy_backlog_fence_v2"])

    def test_read_only_reports_legacy_fence_candidates_without_mutation(self):
        plan=inspect_latest_article(self.db)
        Path(self.state).write_text(json.dumps({
            "status":"ACKED",
            "source_identity":plan["source_identity"],
            "accepted":{},
        }),encoding="utf-8")
        before=Path(self.state).read_text(encoding="utf-8")
        result=run_live_once(
            self.db,state_path=self.state,send=False,
            now=datetime.fromisoformat("2026-10-15T13:00:00+00:00")
        )
        self.assertEqual(result["legacy_baseline_candidates"],2)
        self.assertEqual(result["retained_recovery_candidates"],0)
        self.assertEqual(result["sent"],0)
        self.assertEqual(Path(self.state).read_text(encoding="utf-8"),before)

    def test_unknown_remote_stop_latch_after_baseline(self):
        alt=str(Path(self.tmp.name)/"uncertain.json")
        baseline=run_live_once(self.db,state_path=alt,secret="k"*40,
            executor=lambda _:self.fail("baseline must not post"),send=True)
        self.assertEqual(baseline["status"],"BASELINED")
        self.db.execute("INSERT INTO pushes VALUES(4,1,4,1,'推','d','uncertain new','10/15','18:03','2026-10-15T10:03:30Z')")
        with self.assertRaisesRegex(RuntimeError,"connection lost"):
            run_live_once(self.db,state_path=alt,secret="k"*40,
                executor=lambda _: (_ for _ in ()).throw(RuntimeError("connection lost")),send=True,
                now=datetime.fromisoformat("2026-10-15T10:04:00+00:00"))
        with self.assertRaisesRegex(ContractError,"remote ACK unresolved"):
            run_live_once(self.db,state_path=alt,secret="k"*40,
                executor=lambda _:self.fail("must not replay"),send=True)

    def test_verified_delayed_row_after_baseline_still_publishes(self):
        baseline=run_live_once(self.db,state_path=self.state,secret="k"*40,
            executor=lambda _:self.fail("baseline must not post"),send=True)
        self.assertEqual(baseline["status"],"BASELINED")
        self.db.execute(
            "INSERT INTO pushes VALUES(4,1,4,1,'→','late','delayed after baseline','10/16','06:36','2026-10-15T23:01:23Z')"
        )
        seen=[]
        def approve(batch):
            seen.extend(batch["rows"])
            return {"status":"ACK","batch_id":batch["batch_id"],"digest":batch["digest"],
              "logical_rows_acked":1,"d1_query_count":7,"d1_rows_written":4,
              "http_requests":1}
        result=run_live_once(self.db,state_path=self.state,secret="k"*40,
                             executor=approve,send=True,
                             now=datetime.fromisoformat("2026-10-15T23:02:00+00:00"))
        self.assertEqual(result["status"],"ACK")
        self.assertEqual(result["sent"],1)
        self.assertEqual(seen[0]["source_line"],4)
        self.assertEqual(seen[0]["occurred_at"],"2026-10-15T22:36:00Z")

    def test_source_mutation_blocks_only_this_run_and_recovers_without_state_change(self):
        from unittest.mock import patch
        plan=inspect_latest_article(self.db)
        original=plan["candidate_rows"][0]
        Path(self.state).write_text(json.dumps({
            "status":"ACKED","source_identity":plan["source_identity"],
            "accepted":{original["source_record_key"]:content_digest(original)},
            "legacy_backlog_fence_v2":True,
        }),encoding="utf-8")
        before=Path(self.state).read_bytes()
        changed={**original,"content":"transient pagination shift"}
        changed_plan={**plan,"candidate_rows":[changed]}
        stable_plan={**plan,"candidate_rows":[original]}
        with patch("ptt_offline.live_capture_publisher.inspect_latest_article",
                   side_effect=[changed_plan,stable_plan]):
            blocked=run_live_once(self.db,state_path=self.state,send=True,
                secret="k"*40,executor=lambda _:self.fail("must not post"))
            self.assertEqual(blocked["status"],"LOCAL_SOURCE_MUTATION_BLOCKED")
            self.assertEqual(blocked["mutation_count"],1)
            self.assertEqual(blocked["mutations"][0]["aid"],plan["aid"])
            self.assertEqual(blocked["mutations"][0]["source_record_key"],original["source_record_key"])
            self.assertEqual(blocked["mutations"][0]["source_line"],original["source_line"])
            self.assertEqual(Path(self.state).read_bytes(),before)
            recovered=run_live_once(self.db,state_path=self.state,send=True,
                secret="k"*40,executor=lambda _:self.fail("must not replay"))
        self.assertEqual(recovered["status"],"NO_NEW_ROWS")
        self.assertEqual(Path(self.state).read_bytes(),before)

    def test_runtime_fence_with_migration_marker_drops_1800_stale_and_sends_20_recoverable(self):
        from unittest.mock import patch
        aid="1runtime"
        identity="f"*64
        url="https://www.ptt.cc/bbs/C_Chat/M.1792180800.A.001.html"
        def row(line,occurred_at):
            return {"push_id":f"p{line}","aid":aid,"day":"2026-10-17",
                "source_line":line,"kind":"推","author":"u","content":f"line-{line}",
                "occurred_at":occurred_at,"floor":line,"source_url":url,
                "source_record_key":f"{aid}:{line}"}
        rows=([row(line,"2026-10-17T06:00:00Z") for line in range(1,1801)]+
              [row(line,"2026-10-17T09:30:00Z") for line in range(1801,1821)])
        plan={"status":"READY","aid":aid,"source_identity":identity,
              "candidate_rows":rows,"pending_source_lines":[],"scan_truncated":False}
        Path(self.state).write_text(json.dumps({"status":"ACKED",
            "source_identity":identity,"accepted":{},
            "legacy_backlog_fence_v2":True}),encoding="utf-8")
        sent=[]
        def approve(batch):
            sent.extend(batch["rows"])
            return {"status":"ACK","batch_id":batch["batch_id"],"digest":batch["digest"],
                "logical_rows_acked":len(batch["rows"]),"d1_query_count":102,
                "d1_rows_written":42,"http_requests":1}
        with patch("ptt_offline.live_capture_publisher.inspect_latest_article",return_value=plan):
            result=run_live_once(self.db,state_path=self.state,send=True,
                secret="k"*40,executor=approve,batch_cap=25,
                now=datetime.fromisoformat("2026-10-17T10:00:00+00:00"))
            again=run_live_once(self.db,state_path=self.state,send=True,
                secret="k"*40,executor=lambda _:self.fail("must not replay"),batch_cap=25,
                now=datetime.fromisoformat("2026-10-17T10:00:00+00:00"))
        self.assertEqual(result["status"],"ACK")
        self.assertEqual(result["stale_fenced_rows"],1800)
        self.assertEqual(result["eligible"],20)
        self.assertEqual([x["source_line"] for x in sent],list(range(1801,1821)))
        self.assertEqual(again["status"],"NO_NEW_ROWS")
        self.assertEqual(again["stale_fenced_rows"],0)
        saved=json.loads(Path(self.state).read_text(encoding="utf-8"))
        self.assertEqual(len(saved["accepted"]),1820)
        self.assertTrue(saved["legacy_backlog_fence_v2"])
if __name__=="__main__":unittest.main()
