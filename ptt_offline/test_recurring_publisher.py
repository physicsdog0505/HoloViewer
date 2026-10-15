import unittest
from unittest.mock import patch
from contextlib import nullcontext
from ptt_offline.recurring_publisher import run_snapshot

class RecurringPublisherTests(unittest.TestCase):
    def test_empty_collector_never_posts(self):
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"NO_REAL_COLLECTOR_ROWS","candidate_rows":[]}), \
             patch("ptt_offline.recurring_publisher.run_live_once",side_effect=AssertionError("must not publish")):
            result=run_snapshot(source="unused",state_dir="/tmp/unused")
        self.assertEqual(result["http_posts"],0)
        self.assertEqual(result["status"],"NO_REAL_COLLECTOR_ROWS")
    def test_source_specific_state_and_no_repeat_when_dry_run(self):
        source="a"*64
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",return_value={"status":"READ_ONLY","eligible":4,"sent":0}) as runner:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test")
        self.assertEqual(result["http_posts"],0)
        self.assertIn(source,runner.call_args.kwargs["state_path"])
        self.assertFalse(runner.call_args.kwargs["send"])
if __name__=="__main__":unittest.main()
