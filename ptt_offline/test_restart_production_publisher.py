from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from ptt_offline.restart_production_publisher import (
    uncertain_states, read_running_pid, assert_expected_process, wait_stopped,
    assert_recent_completed_cycle,
)


class RestartProductionPublisherTests(unittest.TestCase):
    def test_uncertain_states_detects_only_remote_uncertain(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)
            (d/"a.json").write_text(json.dumps({"status":"ACKED"}),encoding="utf-8")
            (d/"b.json").write_text(json.dumps({"status":"REMOTE_UNCERTAIN"}),encoding="utf-8")
            (d/"bad.json").write_text("{",encoding="utf-8")
            self.assertEqual(uncertain_states(d),[str(d/"b.json")])

    def test_recent_completed_cycle_requires_fresh_ack_or_noop(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"metrics.jsonl"
            now=datetime(2026,10,15,23,40,0,tzinfo=timezone.utc)
            fresh=(now-timedelta(seconds=5)).isoformat()
            p.write_text(json.dumps({"status":"NO_NEW_ROWS","observed_at":fresh})+"\n",encoding="utf-8")
            self.assertEqual(assert_recent_completed_cycle(p,now=now)["status"],"NO_NEW_ROWS")
            p.write_text(json.dumps({"status":"BASELINED","observed_at":fresh})+"\n",encoding="utf-8")
            self.assertEqual(assert_recent_completed_cycle(p,now=now)["status"],"BASELINED")
            p.write_text(json.dumps({"status":"STOP_RECONCILE","observed_at":fresh})+"\n",encoding="utf-8")
            with self.assertRaises(SystemExit):
                assert_recent_completed_cycle(p,now=now)
            stale=(now-timedelta(seconds=30)).isoformat()
            p.write_text(json.dumps({"status":"ACK","observed_at":stale})+"\n",encoding="utf-8")
            with self.assertRaises(SystemExit):
                assert_recent_completed_cycle(p,now=now)

    def test_read_running_pid_rejects_missing_and_stale(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"publisher.pid"
            with self.assertRaises(SystemExit):
                read_running_pid(p)
            p.write_text("99999999\n",encoding="utf-8")
            with patch("os.kill",side_effect=ProcessLookupError):
                with self.assertRaises(SystemExit):
                    read_running_pid(p)

    def test_expected_process_requires_recurring_publisher(self):
        with patch("ptt_offline.restart_production_publisher.process_command",
                   return_value="python -B -m ptt_offline.recurring_publisher --send"):
            self.assertIn("recurring_publisher",assert_expected_process(123))
        with patch("ptt_offline.restart_production_publisher.process_command",
                   return_value="python unrelated.py"):
            with self.assertRaises(SystemExit):
                assert_expected_process(123)
        with patch("ptt_offline.restart_production_publisher.process_command",
                   return_value="python -B -m ptt_offline.publisher_service --root /tmp/runtime"):
            with self.assertRaises(SystemExit) as caught:
                assert_expected_process(123)
            self.assertIn("launchd-managed",str(caught.exception))

    def test_wait_stopped_never_escalates_to_sigkill(self):
        calls=[]
        def fake_kill(pid,sig):
            calls.append((pid,sig))
            raise ProcessLookupError
        with patch("os.kill",side_effect=fake_kill):
            wait_stopped(321,timeout=0.01)
        self.assertEqual(calls,[(321,0)])


if __name__=="__main__":
    unittest.main()
