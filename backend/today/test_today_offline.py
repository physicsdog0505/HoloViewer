import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from .engine import normalize_video, apply_observation, project, stamp
from .storage import init_offline, write_offline
from .schedule import Budget

NOW = datetime(2026,10,15,12,0,tzinfo=timezone.utc)
CID = "UC" + "A"*22
VID = "abcdefghijk"

def raw(state, start=None, end=None, owner=CID):
    details = {}
    if start: details["actualStartTime"] = start
    if end: details["actualEndTime"] = end
    details["scheduledStartTime"] = "2026-10-16T00:00:00Z"
    return {"id":VID,"snippet":{"channelId":owner,"channelTitle":"Test","title":"Fixture",
          "liveBroadcastContent":state},"liveStreamingDetails":details}

class TodayOfflineTests(unittest.TestCase):
    def observe(self, data, at=NOW):
        return normalize_video(data, observed_at=at, approved_channels={CID}, reference_now=NOW+timedelta(hours=1))
    def test_verified_live(self):
        self.assertEqual(self.observe(raw("live","2026-10-15T11:00:00Z"))["lifecycle_state"],"live")
    def test_positive_ended(self):
        self.assertEqual(self.observe(raw("none","2026-10-15T11:00:00Z","2026-10-15T11:59:00Z"))["lifecycle_state"],"ended")
    def test_no_clock_guess(self):
        self.assertEqual(self.observe(raw("none","2026-10-15T11:00:00Z"))["lifecycle_state"],"unknown")
    def test_upcoming_provider_only(self):
        self.assertEqual(self.observe(raw("upcoming"))["lifecycle_state"],"upcoming")
    def test_foreign_owner_quarantine(self):
        self.assertIsNone(self.observe(raw("live",owner="UC"+"Z"*22)))
    def test_replay_and_ended(self):
        live=self.observe(raw("live","2026-10-15T11:00:00Z"), NOW-timedelta(minutes=1))
        end=self.observe(raw("none","2026-10-15T11:00:00Z","2026-10-15T11:59:00Z"))
        self.assertEqual(apply_observation(end,live)["lifecycle_state"],"ended")
        self.assertEqual(apply_observation(end,{**live,"observed_at":stamp(NOW+timedelta(minutes=1))})["lifecycle_state"],"ended")
    def test_idempotent_storage(self):
        conn=sqlite3.connect(":memory:")
        init_offline(conn)
        a=self.observe(raw("live","2026-10-15T11:00:00Z"))
        self.assertTrue(write_offline(conn,a))
        self.assertFalse(write_offline(conn,a))
        self.assertEqual(conn.execute("SELECT count(*) FROM today_observations").fetchone()[0],1)
    def test_missing_source_degraded(self):
        x=project([],now=NOW,expected_channels=66,scanned_channels=0,gap=True)
        self.assertEqual(x["freshness"]["status"],"degraded")
        self.assertEqual(x["streams"],[])
        self.assertTrue(x["completeness"]["gap"])
    def test_stale_no_false_live(self):
        a=self.observe(raw("live","2026-10-15T11:00:00Z"),NOW-timedelta(hours=2))
        x=project([a],now=NOW,last_success_at=NOW-timedelta(hours=2))
        self.assertEqual(x["streams"][0]["lifecycle_state"],"unknown")
    def test_budget_and_retry(self):
        b=Budget()
        self.assertFalse(b.permits(8500,1))
        self.assertTrue(b.permits(0,1))
        self.assertLessEqual(b.retry_seconds(50),3600)
        self.assertEqual(b.requests_per_day_estimate(),3240)
    def test_reject_invalid_identity(self):
        with self.assertRaises(ValueError):
            self.observe({"id":"bad","snippet":{"channelId":CID}})
    def test_reject_future_evidence(self):
        with self.assertRaises(ValueError):
            self.observe(raw("live"),datetime.now(timezone.utc)+timedelta(days=1))

if __name__=="__main__":
    unittest.main()
