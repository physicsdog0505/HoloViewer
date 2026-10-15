import unittest
from datetime import datetime, timezone, timedelta
from .provider import LocalTodayProvider, CloudflareTodayProvider, today_contract
from .ingest import ApprovedRoster, ingest_batches
from .engine import normalize_video, apply_observation
from .schedule import Budget

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
C = "UC" + "A"*22
V = "abcdefghijk"

def video(ident=V, publisher=C, state="live", end=None):
    metadata = {"scheduledStartTime":"2026-10-16T00:00:00Z",
                "actualStartTime":"2026-10-15T11:00:00Z"}
    if end:
        metadata["actualEndTime"] = end
    return {"id":ident, "snippet":{"channelId":publisher, "title":"Fixture",
        "channelTitle":"Example", "liveBroadcastContent":state},
        "liveStreamingDetails":metadata}

class ProviderIngestionTests(unittest.TestCase):
    def setUp(self):
        self.roster = ApprovedRoster("fixture-v1", frozenset({C}))
        self.row = normalize_video(video(), observed_at=NOW,
            approved_channels={C}, reference_now=NOW)
    def ingest(self, pages, metadata, **kw):
        return ingest_batches(roster=self.roster, pages=pages, metadata=metadata,
            observed_at=NOW, reference_now=NOW, **kw)
    def test_swappable_readers(self):
        coverage = {"last_success_at":NOW, "expected_channels":1,
                    "scanned_channels":1, "gap":False}
        local = today_contract(LocalTodayProvider((self.row,),coverage),now=NOW)
        cloud = today_contract(CloudflareTodayProvider(lambda:(self.row,),lambda:coverage),now=NOW)
        self.assertEqual(local,cloud)
        self.assertEqual(local["streams"][0]["lifecycle_state"],"live")
    def test_global_gap_does_not_report_live(self):
        coverage = {"last_success_at":NOW, "expected_channels":1,
                    "scanned_channels":0, "gap":True}
        result = today_contract(LocalTodayProvider((self.row,),coverage),now=NOW)
        self.assertEqual(result["streams"][0]["lifecycle_state"],"live")
    def test_missing_coverage_is_gap(self):
        self.assertTrue(self.ingest({},lambda _:{}).gap)
    def test_dedup(self):
        result = self.ingest({C:[[V,V],[V]]},lambda ids:{V:video()})
        self.assertEqual(len(result.records),1)
        self.assertEqual(result.quota_units,1)
    def test_unapproved_publisher_quarantine(self):
        result=self.ingest({C:[[V]]},lambda ids:{V:video(publisher="UC"+"B"*22)})
        self.assertEqual(result.needs_review,(V,))
        self.assertFalse(result.records)
    def test_quota_fail_closed(self):
        result=self.ingest({C:[[V]]},lambda _:self.fail("must not call"),
            budget=Budget(daily_units=10,reserved_units=9),used_units=1)
        self.assertTrue(result.gap)
        self.assertEqual(result.quota_units,0)
    def test_provider_error_degrades(self):
        def fail(_):raise RuntimeError("synthetic failure")
        self.assertTrue(self.ingest({C:[[V]]},fail).gap)
    def test_missing_video_does_not_end(self):
        result=self.ingest({C:[[V]]},lambda _: {})
        self.assertTrue(result.gap)
        self.assertFalse(result.records)
    def test_live_ended_and_replay(self):
        ended=normalize_video(video(state="none",end="2026-10-15T11:59:00Z"),
            observed_at=NOW+timedelta(minutes=1),approved_channels={C},
            reference_now=NOW+timedelta(minutes=1))
        self.assertEqual(apply_observation(self.row,ended)["lifecycle_state"],"ended")
        self.assertEqual(apply_observation(ended,self.row)["lifecycle_state"],"ended")
    def test_invalid_roster(self):
        with self.assertRaises(ValueError):ApprovedRoster("",frozenset({C}))
    def test_limit_and_partial(self):
        ids=["id%09d"%i for i in range(201)]
        result=self.ingest({C:[ids]},lambda _: {})
        self.assertTrue(result.gap)
        self.assertEqual(result.attempted,200)
    def test_bad_metadata(self):
        result=self.ingest({C:[[V]]},lambda _:{V:{"id":"wrong"}})
        self.assertTrue(result.gap)
        self.assertFalse(result.records)
    def test_truncated_pages(self):
        self.assertTrue(self.ingest({C:[[V],[V],[V]]},lambda _:{V:video()}).gap)

if __name__=="__main__":
    unittest.main()
