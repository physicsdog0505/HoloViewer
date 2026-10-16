import unittest
from datetime import datetime, timezone
from .youtube_readonly import live_provider_sample
C="UC"+"A"*22
V="abcdefghijk"
ROSTER={"version":"owner-v1","channels":[{"id":C,"group":"hololive","uploads_playlist":"UU"+C[2:]}]}
class RealProviderBoundaryTests(unittest.TestCase):
    def test_bounded_provider_transport_and_no_write(self):
        calls=[]
        def get(endpoint,params):
            calls.append(endpoint)
            if endpoint=="playlistItems":return {"items":[{"contentDetails":{"videoId":V}}]}
            return {"items":[{"id":V,"snippet":{"channelId":C,"title":"Live","channelTitle":"Test","liveBroadcastContent":"live"},
                "liveStreamingDetails":{"actualStartTime":"2026-10-15T11:00:00Z"}}]}
        result=live_provider_sample(ROSTER,"injected-test-key",request_json=get,
                  observed_at=datetime(2026,10,15,12,tzinfo=timezone.utc))
        self.assertEqual(calls,["playlistItems","videos"])
        self.assertEqual(result["d1_writes"],0)
        self.assertEqual(result["records"][0]["lifecycle_state"],"live")
    def test_optional_broadcast_discovery_uses_two_explicit_searches(self):
        calls=[]
        def get(endpoint,params):
            calls.append((endpoint,params.get("eventType")))
            if endpoint=="playlistItems":return {"items":[]}
            if endpoint=="search":return {"items":[{"id":{"videoId":V}}]}
            return {"items":[{"id":V,"snippet":{"channelId":C,"title":"Coming","channelTitle":"Test","liveBroadcastContent":"upcoming"},"liveStreamingDetails":{"scheduledStartTime":"2026-10-16T00:00:00Z"}}]}
        result=live_provider_sample(ROSTER,"injected-test-key",request_json=get,
             observed_at=datetime(2026,10,15,12,tzinfo=timezone.utc),discover_broadcasts=True)
        self.assertEqual(result["estimated_quota_units"],202)
        self.assertEqual(len(result["records"]),1)
        self.assertEqual(result["records"][0]["lifecycle_state"],"upcoming")
        self.assertEqual([item[1] for item in calls if item[0]=="search"],["live","upcoming"])
    def test_blocks_unapproved_or_unbounded_scope(self):
        with self.assertRaises(ValueError):live_provider_sample(ROSTER,"x",max_channels=4)
        with self.assertRaises(ValueError):live_provider_sample({**ROSTER,"channels":[{**ROSTER["channels"][0],"uploads_playlist":"UU"+"B"*22}]},"x")
if __name__=="__main__":unittest.main()
