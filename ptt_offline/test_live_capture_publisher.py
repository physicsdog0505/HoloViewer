import sqlite3
import tempfile
import unittest
from pathlib import Path
from ptt_offline.live_capture_publisher import active_article_ids,inspect_latest_article,run_live_once,state_for_source
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.public_today_contract import ContractError

class LiveCapturePublisherTests(unittest.TestCase):
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

    def test_exact_ack_replay_and_unknown_remote_stop_latch(self):
        def approve(batch):
            self.assertEqual(len(batch["rows"]),2)
            self.assertTrue(all(len(x["time_proof"])==64 for x in batch["rows"]))
            return {"status":"ACK","batch_id":batch["batch_id"],"digest":batch["digest"],
              "logical_rows_acked":2,"d1_query_count":8,"d1_rows_written":5,
              "http_requests":1}
        result=run_live_once(self.db,state_path=self.state,secret="k"*40,
                             executor=approve,send=True)
        self.assertEqual(result["status"],"ACK")
        self.assertEqual(result["sent"],2)
        second=run_live_once(self.db,state_path=self.state,secret="k"*40,
                              executor=lambda _:self.fail("must not replay"),send=True)
        self.assertEqual(second["status"],"NO_NEW_ROWS")
        # Unknown remote state is deliberately not retried.
        alt=str(Path(self.tmp.name)/"uncertain.json")
        with self.assertRaisesRegex(RuntimeError,"connection lost"):
            run_live_once(self.db,state_path=alt,secret="k"*40,
                executor=lambda _: (_ for _ in ()).throw(RuntimeError("connection lost")),send=True)
        with self.assertRaisesRegex(ContractError,"remote ACK unresolved"):
            run_live_once(self.db,state_path=alt,secret="k"*40,
                executor=approve,send=True)
if __name__=="__main__":unittest.main()
