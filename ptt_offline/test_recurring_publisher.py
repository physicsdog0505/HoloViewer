import unittest
from unittest.mock import patch
from contextlib import nullcontext
from ptt_offline.recurring_publisher import main,run_snapshot,snapshot_interval,seconds_until_next_snapshot
from datetime import datetime
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo
from ptt_offline.public_today_contract import ContractError

class RecurringPublisherTests(unittest.TestCase):
    def test_zero_iterations_is_continuous_until_external_stop(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            state=root/"state"
            state.mkdir()
            metrics=root/"metrics.jsonl"
            result={
                "status":"NO_NEW_ROWS","sent":0,"eligible":0,"http_posts":0,
                "observed_at":"2026-10-20T04:00:00+00:00",
                "publisher_mode":"DRY_RUN",
            }
            with patch("ptt_offline.recurring_publisher.exclusive_lock",
                       return_value=nullcontext()), \
                 patch("ptt_offline.recurring_publisher.run_snapshot",
                       return_value=result) as snapshot, \
                 patch("ptt_offline.recurring_publisher.time.sleep",
                       side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    main([
                        "--source","unused.sqlite3",
                        "--state-dir",str(state),
                        "--metrics",str(metrics),
                        "--iterations","0",
                        "--interval-seconds","60",
                    ])
        snapshot.assert_called_once()

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
                                send=True,batch_cap=25,max_batches=8,clock=lambda:0)
        self.assertEqual(result["articles_checked"],2)
        self.assertEqual(result["sent"],50)
        self.assertEqual(result["http_posts"],2)
        self.assertEqual(per_article,[1,1,2,2])
        self.assertFalse(result["backlog_may_remain"])

    def test_global_one_batch_budget_rotates_across_active_articles(self):
        def plan(_,article_id=None):
            return {"status":"READY","source_identity":str(article_id)*64}
        for clock_value,expected_article in [(0,1),(60,2)]:
            delivered=[]
            def publish(*args,**kwargs):
                delivered.append(kwargs["article_id"])
                return {"status":"ACK","sent":10}
            with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
                 patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1,2,3,4]), \
                 patch("ptt_offline.recurring_publisher.inspect_latest_article",side_effect=plan), \
                 patch("ptt_offline.recurring_publisher.run_live_once",side_effect=publish):
                result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                    send=True,batch_cap=10,max_batches=1,
                                    max_articles=4,clock=lambda v=clock_value:v)
            self.assertEqual(result["http_posts"],1)
            self.assertEqual(result["sent"],10)
            self.assertEqual(result["modeled_d1_writes_ceiling"],22)
            self.assertEqual(result["modeled_d1_queries_ceiling"],25)
            self.assertEqual(delivered,[expected_article])
            self.assertTrue(result["backlog_may_remain"])

    def test_query_model_matches_three_bounded_reads_per_batch(self):
        source="q"*64
        for sent,expected in [(1,7),(10,25),(25,55)]:
            with self.subTest(sent=sent), \
                 patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
                 patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
                 patch("ptt_offline.recurring_publisher.inspect_latest_article",
                       return_value={"status":"READY","source_identity":source}), \
                 patch("ptt_offline.recurring_publisher.run_live_once",
                       return_value={"status":"ACK","sent":sent}) as publisher:
                result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                    send=True,batch_cap=sent,max_batches=1,clock=lambda:0)
            self.assertEqual(result["modeled_d1_writes_ceiling"],2+2*sent)
            self.assertEqual(result["modeled_d1_queries_ceiling"],expected)
            self.assertEqual(publisher.call_count,1)

    def test_fresh_backlog_activates_three_batch_burst(self):
        source="e"*64
        responses=[
            {"status":"ACK","sent":10,"eligible":30,"fresh_eligible":30,"burst_safe_candidates":30},
            {"status":"ACK","sent":10,"eligible":20,"fresh_eligible":20,"burst_safe_candidates":20},
            {"status":"ACK","sent":10,"eligible":10,"fresh_eligible":10,"burst_safe_candidates":10},
        ]
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",side_effect=responses) as publisher:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=True,batch_cap=10,max_batches=1,burst_max_batches=3)
        self.assertEqual(result["sent"],30)
        self.assertEqual(result["http_posts"],3)
        self.assertTrue(result["burst_activated"])
        self.assertEqual(result["burst_batches"],2)
        self.assertEqual(result["modeled_d1_writes_ceiling"],66)
        self.assertEqual(result["modeled_d1_queries_ceiling"],75)
        self.assertTrue(publisher.call_args_list[1].kwargs["fresh_only"])
        self.assertTrue(publisher.call_args_list[2].kwargs["fresh_only"])

    def test_safe_two_hour_backlog_bursts_when_fresh_surge_exists(self):
        source="f"*64
        responses=[
            {"status":"ACK","sent":10,"eligible":908,"fresh_eligible":54,"burst_safe_candidates":908},
            {"status":"ACK","sent":10,"eligible":898,"fresh_eligible":54,"burst_safe_candidates":898},
            {"status":"ACK","sent":10,"eligible":888,"fresh_eligible":54,"burst_safe_candidates":888},
        ]
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",side_effect=responses) as publisher:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=True,batch_cap=10,max_batches=1,burst_max_batches=3)
        self.assertEqual(result["sent"],30)
        self.assertEqual(result["http_posts"],3)
        self.assertTrue(result["burst_activated"])
        self.assertEqual(result["burst_batches"],2)
        self.assertEqual(publisher.call_count,3)

    def test_burst_stays_off_when_recovery_window_is_not_fully_verified(self):
        source="7"*64
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",
                   return_value={"status":"ACK","sent":10,"eligible":30,"fresh_eligible":20,"burst_safe_candidates":29}) as publisher:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=True,batch_cap=10,max_batches=1,burst_max_batches=3)
        self.assertEqual(result["sent"],10)
        self.assertEqual(result["http_posts"],1)
        self.assertFalse(result["burst_activated"])
        self.assertEqual(publisher.call_count,1)

    def test_dry_run_aggregates_fence_preview_counts(self):
        source="9"*64
        responses=[
            {"status":"READ_ONLY","eligible":12,"fresh_eligible":3,
             "legacy_baseline_candidates":7,"baseline_skipped_candidates":4,
             "retained_recovery_candidates":5,"burst_safe_candidates":5,"sent":0},
            {"status":"READ_ONLY","eligible":8,"fresh_eligible":2,
             "legacy_baseline_candidates":6,"baseline_skipped_candidates":3,
             "retained_recovery_candidates":2,"burst_safe_candidates":2,"sent":0},
        ]
        def plan(_,article_id=None):
            return {"status":"READY","source_identity":str(article_id)*64}
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1,2]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",side_effect=plan), \
             patch("ptt_offline.recurring_publisher.run_live_once",side_effect=responses):
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=False,batch_cap=10,max_batches=1,
                                burst_max_batches=3,max_articles=4)
        self.assertEqual(result["eligible"],20)
        self.assertEqual(result["fresh_eligible"],5)
        self.assertEqual(result["legacy_baseline_candidates"],13)
        self.assertEqual(result["retained_recovery_candidates"],7)
        self.assertEqual(result["baseline_skipped_candidates"],7)
        self.assertEqual(result["burst_safe_candidates"],7)
        self.assertEqual(result["sent"],0)
        self.assertEqual(result["http_posts"],0)

    def test_fresh_state_baseline_is_zero_remote_posts(self):
        source="d"*64
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",return_value={"status":"BASELINED","sent":0,"eligible":0}) as publisher:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=True,batch_cap=10,max_batches=1,clock=lambda:0)
        self.assertEqual(result["status"],"BASELINED")
        self.assertEqual(result["sent"],0)
        self.assertEqual(result["http_posts"],0)
        self.assertEqual(result["modeled_d1_writes_ceiling"],0)
        self.assertEqual(result["modeled_d1_queries_ceiling"],0)
        self.assertEqual(publisher.call_count,1)

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

    def test_mutated_aid_does_not_consume_one_batch_budget_and_other_aid_acks(self):
        def plan(_,article_id=None):
            return {"status":"READY","source_identity":str(article_id)*64}
        responses=[
            {"status":"LOCAL_SOURCE_MUTATION_BLOCKED","aid":"#mutated",
             "mutation_count":1,"sent":0},
            {"status":"ACK","aid":"#healthy","sent":10},
        ]
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1,2]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",side_effect=plan), \
             patch("ptt_offline.recurring_publisher.run_live_once",side_effect=responses) as publisher:
            result=run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                                send=True,batch_cap=10,max_batches=1,clock=lambda:0)
        self.assertEqual([call.kwargs["article_id"] for call in publisher.call_args_list],[1,2])
        self.assertEqual(result["status"],"PARTIAL_SUCCESS")
        self.assertEqual(result["sent"],10)
        self.assertEqual(result["http_posts"],1)
        self.assertEqual(result["mutation_blocked_articles"],1)
        self.assertEqual(result["mutation_blocked_aids"],["#mutated"])
        self.assertEqual(result["mutation_blocked_count"],1)

    def test_remote_uncertain_remains_global_fail_closed(self):
        source="8"*64
        with patch("ptt_offline.recurring_publisher.open_source",return_value=nullcontext(object())), \
             patch("ptt_offline.recurring_publisher.active_article_ids",return_value=[1,2]), \
             patch("ptt_offline.recurring_publisher.inspect_latest_article",return_value={"status":"READY","source_identity":source}), \
             patch("ptt_offline.recurring_publisher.run_live_once",
                   side_effect=ContractError("remote ACK unresolved; inspect D1 before any replay")) as publisher:
            with self.assertRaisesRegex(ContractError,"remote ACK unresolved"):
                run_snapshot(source="unused",state_dir="/tmp/ptt48-test",
                             send=True,batch_cap=10,max_batches=1,clock=lambda:0)
        self.assertEqual(publisher.call_count,1)
if __name__=="__main__":unittest.main()
