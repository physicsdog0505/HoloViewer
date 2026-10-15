import unittest
from unittest.mock import patch
from contextlib import nullcontext
from ptt_offline.recurring_publisher import run_snapshot,snapshot_interval,seconds_until_next_snapshot
from datetime import datetime
from zoneinfo import ZoneInfo

class RecurringPublisherTests(unittest.TestCase):
    def test_taipei_overnight_snapshot_boundaries(self):
        tpe=ZoneInfo("Asia/Taipei")
        for hour,minute,seconds,expected in [
            (1,59,0,60),(2,0,0,600),(2,1,0,600),
            (6,59,0,600),(7,0,0,60),(23,59,0,60)]:
            with self.subTest(hour=hour,minute=minute):
                at=datetime(2026,10,16,hour,minute,seconds,tzinfo=tpe)
                self.assertEqual(snapshot_interval(at),expected)
        self.assertEqual(seconds_until_next_snapshot(datetime(2026,10,16,1,59,30,tzinfo=tpe)),30)
        self.assertEqual(seconds_until_next_snapshot(datetime(2026,10,16,2,1,0,tzinfo=tpe)),540)
        self.assertEqual(seconds_until_next_snapshot(datetime(2026,10,16,6,59,0,tzinfo=tpe)),60)
        self.assertEqual(seconds_until_next_snapshot(datetime(2026,10,16,7,0,30,tzinfo=tpe)),30)
    def test_one_hundred_pushes_drain_four_ack_batches(self):
        source="b"*64
        responses=[{"status":"ACK","sent":25} for _ in range(4)]+[{"status":"NO_NEW_ROWS","sent":0}]
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",side_effect=responses) as publisher:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=True,executor=lambda x:x,batch_cap=25,max_batches=8)
        self.assertEqual(result["sent"],100)
        self.assertEqual(result["http_posts"],4)
        self.assertEqual(publisher.call_count,5)
        self.assertFalse(result["backlog_may_remain"])

    def test_bounded_drain_marks_possible_backlog(self):
        source="c"*64
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",return_value={"status":"ACK","sent":25}) as publisher:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=True,batch_cap=25,max_batches=8)
        self.assertEqual(result["sent"],200)
        self.assertEqual(result["http_posts"],8)
        self.assertEqual(publisher.call_count,8)
        self.assertTrue(result["backlog_may_remain"])

    def test_two_active_articles_separate_delivery_budgets(self):
        def plan(_,article_id=None):
            return {"status":"READY","source_identity":str(article_id)*64}
        per_article=[]
        def publish(*args,**kwargs):
            per_article.append(kwargs["article_id"])
            return {"status":"ACK","sent":25} if per_article.count(kwargs["article_id"])==1 else {"status":"NO_NEW_ROWS","sent":0}
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1,2]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",side_effect=plan), \
             patch("ptt_offline.recurring_publisher.run_live_once",side_effect=publish):
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=True,batch_cap=25,max_batches=8)
        self.assertEqual(result["articles_checked"],2)
        self.assertEqual(result["sent"],50)
        self.assertEqual(result["http_posts"],2)
        self.assertEqual(per_article,[1,1,2,2])
        self.assertFalse(result["backlog_may_remain"])

    def test_empty_collector_never_posts(self):
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"NO_REAL_COLLECTOR_ROWS","candidate_rows":[]}), \
             patch("ptt_offline.recurring_publisher.run_live_once",side_effect=AssertionError("must not publish")):
            result=run_snapshot(source="unused",state_dir="/tmp/unused")
        self.assertEqual(result["http_posts"],0)
        self.assertEqual(result["status"],"NO_REAL_COLLECTOR_ROWS")
    def test_source_specific_state_and_no_repeat_when_dry_run(self):
        source="a"*64
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",return_value={"status":"READ_ONLY","eligible":4,"sent":0}) as runner:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test")
        self.assertEqual(result["http_posts"],0)
        self.assertIn(source,runner.call_args.kwargs["state_path"])
        self.assertFalse(runner.call_args.kwargs["send"])
if __name__=="__main__":unittest.main()
