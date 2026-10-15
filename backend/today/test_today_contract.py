"""#45 frozen T1–T8 Today cross-provider contract vectors. Offline-only."""
import unittest
from datetime import datetime,timezone,timedelta
from .engine import normalize_video,apply_observation,project,stamp
from .provider import LocalTodayProvider,CloudflareTodayProvider
from .schedule import Budget
C="UC"+"A"*22
V="abcdefghijk"
NOW=datetime(2026,10,15,12,tzinfo=timezone.utc)
def payload(state,*,ident=V,owner=C,ended=None,started=None):
    d={"scheduledStartTime":"2026-10-16T00:00:00Z"}
    if started:d["actualStartTime"]=started
    if ended:d["actualEndTime"]=ended
    return {"id":ident,"snippet":{"title":"Fixture","channelId":owner,"liveBroadcastContent":state},"liveStreamingDetails":d}
def norm(raw,at=NOW):
    return normalize_video(raw,observed_at=at,approved_channels={C},reference_now=NOW+timedelta(hours=1),roster_version="v1")
def readers(rows,*,gap=False,last=NOW,scanned=1,checkpoint="opaque"):
    cover={"last_success_at":last,"expected_channels":1,"scanned_channels":scanned,
           "gap":gap,"roster_version":"v1","checkpoint":checkpoint}
    a=LocalTodayProvider(tuple(rows),cover,NOW)
    b=CloudflareTodayProvider(lambda:tuple(rows),lambda:cover,NOW)
    x=a.read_today("2026-10-15",200)
    assert x==b.read_today("2026-10-15",200)
    return x
class TodayVectors(unittest.TestCase):
    def test_T1_upcoming(self):
        self.assertEqual(readers([norm(payload("upcoming"))])["streams"][0]["lifecycle_state"],"upcoming")
    def test_T2_live(self):
        self.assertEqual(readers([norm(payload("live",started="2026-10-15T11:00:00Z"))])["streams"][0]["lifecycle_state"],"live")
    def test_T3_ended(self):
        a=norm(payload("live",started="2026-10-15T11:00:00Z"),NOW-timedelta(minutes=5))
        b=norm(payload("none",started="2026-10-15T11:00:00Z",ended="2026-10-15T11:55:00Z"))
        self.assertEqual(readers([a,b])["streams"][0]["lifecycle_state"],"ended")
    def test_T4_older_live_replay(self):
        a=norm(payload("none",started="2026-10-15T11:00:00Z",ended="2026-10-15T11:55:00Z"))
        b=norm(payload("live",started="2026-10-15T11:00:00Z"),NOW-timedelta(minutes=1))
        self.assertEqual(readers([a,b])["streams"][0]["lifecycle_state"],"ended")
    def test_T5_provider_failure_last_good(self):
        a=norm(payload("live",started="2026-10-15T10:00:00Z"),NOW-timedelta(hours=2))
        x=readers([a],last=NOW-timedelta(hours=2))
        self.assertEqual(x["freshness"]["status"],"stale")
        self.assertEqual(x["streams"][0]["lifecycle_state"],"unknown")
    def test_T6_empty_gap(self):
        x=readers([],gap=True,scanned=0)
        self.assertEqual(x["streams"],[])
        self.assertTrue(x["completeness"]["gap"])
        self.assertNotEqual(x["completeness"]["status"],"complete")
    def test_T7_dedup_deterministic(self):
        a=norm(payload("live",started="2026-10-15T11:00:00Z"),NOW-timedelta(minutes=1))
        b=norm(payload("none",started="2026-10-15T11:00:00Z",ended="2026-10-15T11:55:00Z"))
        self.assertEqual(len(readers([a,b,a])["streams"]),1)
        self.assertEqual(readers([b,a])["streams"],readers([a,b])["streams"])
    def test_T8_unapproved(self):
        self.assertIsNone(norm(payload("live",owner="UC"+"B"*22)))
    def test_coverage_does_not_erase_item(self):
        a=norm(payload("live",started="2026-10-15T11:00:00Z"))
        self.assertEqual(readers([a],gap=True)["streams"][0]["lifecycle_state"],"live")
    def test_roster_evidence_mismatch(self):
        a=norm(payload("upcoming"))
        self.assertEqual(readers([a])["streams"][0]["video_id"],V)
        self.assertEqual(readers([{**a,"roster_version":"other"}])["streams"],[])
    def test_no_complete_from_successful_scan(self):
        self.assertEqual(readers([norm(payload("upcoming"))])["completeness"]["status"],"partial")
    def test_future_actual_rejected(self):
        with self.assertRaises(ValueError):
            norm(payload("none",ended="2026-10-15T14:00:00Z"))
    def test_ended_evidence_does_not_rejuvenate(self):
        a=norm(payload("none",ended="2026-10-15T11:30:00Z"))
        b=norm(payload("none"),NOW+timedelta(minutes=1))
        self.assertEqual(apply_observation(a,b)["observed_at"],a["observed_at"])
    def test_retry_terminal(self):
        b=Budget(max_retries=3)
        self.assertIsNone(b.retry_seconds(4))
        self.assertFalse(b.permits_retry(4))
    def test_non_divisor_ceiling(self):
        self.assertEqual(Budget(scan_minutes=31).requests_per_day_estimate(channel_count=1,video_batches=0),47)
if __name__=="__main__":
    unittest.main()
