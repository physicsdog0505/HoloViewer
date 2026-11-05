import unittest
from ptt_offline.realtime_capture_candidate import near_capture_candidate
class CaptureCandidateTests(unittest.TestCase):
    def test_recent_observation_matching_ptt_minute(self):
        row={"occurred_at":"2026-10-15T10:00:00Z",
             "collected_at":"2026-10-15T10:01:06Z",
             "ptt_date":"10/15","ptt_time":"18:00","source_line":20}
        self.assertTrue(near_capture_candidate(row))
        self.assertFalse(near_capture_candidate({**row,"collected_at":"2026-10-16T10:01:06Z"}))
        self.assertFalse(near_capture_candidate({**row,"ptt_time":"17:00"}))
        self.assertFalse(near_capture_candidate({**row,"collected_at":"2026-10-15T09:59:59Z"}))
        self.assertFalse(near_capture_candidate({**row,"collected_at":"2026-10-15T10:03:01Z"}))
        self.assertFalse(near_capture_candidate({**row,"collected_at":"broken"}))
    def test_no_automatic_archival_year_claim(self):
        row={"occurred_at":"2025-10-15T10:00:00Z",
             "collected_at":"2026-10-15T10:01:06Z",
             "ptt_date":"10/15","ptt_time":"18:00","source_line":20}
        self.assertFalse(near_capture_candidate(row))
if __name__=="__main__":unittest.main()
