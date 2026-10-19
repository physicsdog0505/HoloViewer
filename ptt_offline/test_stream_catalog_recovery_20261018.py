import sqlite3
import tempfile
import unittest
from pathlib import Path

from ptt_offline.stream_catalog_recovery_20261018 import source_inventory

C="UC"+"A"*22

class StreamCatalogRecoveryInventoryTests(unittest.TestCase):
    def make_db(self):
        td=tempfile.TemporaryDirectory()
        path=Path(td.name)/"hololive_stream_catalog.sqlite3"
        con=sqlite3.connect(path)
        con.executescript("""
        CREATE TABLE streams(
          video_id TEXT PRIMARY KEY,channel_id TEXT,title TEXT,
          scheduled_start TEXT,actual_start TEXT,actual_end TEXT,lifecycle_state TEXT,
          projection_observed_at TEXT,first_seen_at TEXT,last_seen_at TEXT,last_checked_at TEXT,
          is_livestream INTEGER,is_public INTEGER
        );
        CREATE TABLE channels(channel_id TEXT PRIMARY KEY,channel_name TEXT);
        """)
        con.execute("INSERT INTO channels VALUES(?,?)",(C,"Fixture Channel"))
        return td,path,con

    def test_taipei_day_and_actual_over_scheduled_priority(self):
        td,path,con=self.make_db(); self.addCleanup(td.cleanup)
        # scheduled is 10/18 Taipei, but authoritative actual_start moved to 10/19 Taipei.
        con.execute("INSERT INTO streams VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
          "priority001",C,"priority","2026-10-18T12:00:00Z","2026-10-18T16:30:00Z",None,"live",
          "2026-10-18T16:31:00Z","2026-10-18T11:00:00Z",None,None,1,1))
        # No actual_start: scheduled_start determines membership.
        con.execute("INSERT INTO streams VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
          "scheduled01",C,"scheduled","2026-10-18T15:00:00Z",None,None,"upcoming",
          "2026-10-18T14:00:00Z","2026-10-18T13:00:00Z",None,None,1,1))
        # No actual/scheduled: first_seen fallback determines membership.
        con.execute("INSERT INTO streams VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
          "firstseen01",C,"fallback",None,None,None,"unknown",
          "2026-10-18T10:00:00Z","2026-10-18T02:00:00Z",None,None,1,1))
        con.commit(); con.close()
        rows=source_inventory(path,"2026-10-18")
        by={r["video_id"]:r for r in rows}
        self.assertNotIn("priority001",by)
        self.assertEqual(by["scheduled01"]["selection_basis"],"scheduled_start")
        self.assertEqual(by["firstseen01"]["selection_basis"],"first_seen_at")

    def test_is_livestream_only(self):
        td,path,con=self.make_db(); self.addCleanup(td.cleanup)
        common=("2026-10-18T05:00:00Z","2026-10-18T05:01:00Z")
        con.execute("INSERT INTO streams VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
          "livevid0001",C,"live",common[0],common[1],None,"live","2026-10-18T05:02:00Z",
          "2026-10-18T04:00:00Z",None,None,1,1))
        con.execute("INSERT INTO streams VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
          "upload00001",C,"upload",common[0],common[1],None,"unknown","2026-10-18T05:02:00Z",
          "2026-10-18T04:00:00Z",None,None,0,1))
        con.commit(); con.close()
        ids={r["video_id"] for r in source_inventory(path,"2026-10-18")}
        self.assertEqual(ids,{"livevid0001"})

    def test_known_roboco_fixture_preserves_exact_actual_window(self):
        td,path,con=self.make_db(); self.addCleanup(td.cleanup)
        con.execute("INSERT INTO streams VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
          "TnijhHRqd5w","UCDqI2jOz0weumE8s7paEk6g","Roboco",
          "2026-10-18T15:00:00Z","2026-10-18T15:00:06Z","2026-10-18T16:04:31Z","ended",
          "2026-10-18T16:05:00Z","2026-10-18T14:00:00Z",None,None,1,1))
        con.commit(); con.close()
        rows=source_inventory(path,"2026-10-18")
        self.assertEqual(len(rows),1)
        r=rows[0]
        self.assertEqual(r["video_id"],"TnijhHRqd5w")
        self.assertEqual(r["actual_start"],"2026-10-18T15:00:06Z")
        self.assertEqual(r["actual_end"],"2026-10-18T16:04:31Z")
        self.assertEqual(r["lifecycle_state"],"ended")

if __name__=="__main__":
    unittest.main()
