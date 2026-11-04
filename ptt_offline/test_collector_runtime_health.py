from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ptt_offline.collector_runtime_health import read_collector_health


class CollectorRuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.fixed=self.root/"fixed"

    def write_status(self, **extra):
        body={
            "pid":22222,
            "run_id":"run-1",
            "managed":True,
            "phase":"collecting",
            "updated_at":1000.0,
            **extra,
        }
        (self.root/"collector_live_status.json").write_text(
            json.dumps(body)+"\n",encoding="utf-8"
        )

    def write_refresh(self, *, aid="#1live", line=178, when="1970-01-01T00:16:35+00:00"):
        (self.root/"collector_events.jsonl").write_text(json.dumps({
            "event":"refresh_complete",
            "aid":aid,
            "last_source_line":line,
            "inserted":0,
            "total":31,
            "time_utc":when,
        })+"\n",encoding="utf-8")

    def fixed_controller(self):
        path=self.fixed/"bin/collectorctl.py"
        path.parent.mkdir(parents=True)
        path.write_text("# fixture\n",encoding="utf-8")
        return path

    @patch("ptt_offline.collector_runtime_health.subprocess.run")
    def test_fixed_collectorctl_status_is_authoritative(self, run):
        controller=self.fixed_controller()
        run.return_value=Mock(
            returncode=0,
            stdout=json.dumps({
                "state":"RUNNING",
                "pid":44479,
                "run_id":"managed-run",
                "runtime_source_head":"44bcac99a464ae12c8fc077bb0094b6b21b0c60c",
                "approved_head":"44bcac99a464ae12c8fc077bb0094b6b21b0c60c",
                "state_path":str(self.fixed/"state"),
                "live_aid":"#1gwHM4TF",
                "phase":"collecting",
                "frontier_source_line":136,
                "remote_tail":136,
                "last_refresh_complete":995.0,
                "heartbeat_age_seconds":2.0,
                "refresh_interval_seconds":60,
                "startup_backfill_complete":True,
                "gap_status":"CLEAR",
                "process_count":1,
                "managed_identity":True,
                "kernel_lock_held":True,
                "healthy":True,
            }),
        )
        body=read_collector_health(
            self.root,
            now=1000.0,
            fixed_root=self.fixed,
        )
        self.assertTrue(body["process_alive"])
        self.assertTrue(body["heartbeat_fresh"])
        self.assertTrue(body["live_context_valid"])
        self.assertTrue(body["frontier_progressing"])
        self.assertEqual(body["live_aid"],"#1gwHM4TF")
        self.assertEqual(body["frontier"],136)
        self.assertEqual(body["evidence"]["authority"],"collectorctl-status-v1")
        run.assert_called_once_with(
            [
                __import__("sys").executable,
                str(controller.resolve()),
                "--root",
                str(self.fixed.resolve()),
                "status",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    @patch("ptt_offline.collector_runtime_health.subprocess.run")
    def test_fixed_collectorctl_unhealthy_never_passes_gate(self, run):
        self.fixed_controller()
        run.return_value=Mock(
            returncode=2,
            stdout=json.dumps({
                "state":"UNHEALTHY",
                "pid":44479,
                "run_id":"managed-run",
                "state_path":str(self.fixed/"state"),
                "live_aid":None,
                "phase":"collecting",
                "frontier_source_line":None,
                "heartbeat_age_seconds":2.0,
                "process_count":1,
                "managed_identity":True,
                "kernel_lock_held":True,
                "healthy":False,
            }),
        )
        body=read_collector_health(
            self.root,
            now=1000.0,
            fixed_root=self.fixed,
        )
        self.assertTrue(body["process_alive"])
        self.assertTrue(body["heartbeat_fresh"])
        self.assertFalse(body["live_context_valid"])
        self.assertFalse(body["frontier_progressing"])

    @patch("ptt_offline.collector_runtime_health.subprocess.run")
    @patch("os.kill")
    def test_fresh_repeated_frontier_is_healthy_activity(self, kill, run):
        self.write_status()
        self.write_refresh()
        run.return_value=Mock(stdout="S\n",returncode=0)
        body=read_collector_health(
            self.root,now=1000.0,fixed_root=self.fixed
        )
        self.assertTrue(body["process_alive"])
        self.assertTrue(body["heartbeat_fresh"])
        self.assertTrue(body["live_context_valid"])
        self.assertTrue(body["frontier_progressing"])
        self.assertEqual(body["live_aid"],"#1live")
        self.assertEqual(body["frontier"],178)
        self.assertEqual(body["evidence"]["authority"],"legacy-checkout-health-v1")

    @patch("ptt_offline.collector_runtime_health.subprocess.run")
    @patch("os.kill")
    def test_stale_refresh_marks_activity_stalled_without_requiring_line_growth(self, kill, run):
        self.write_status()
        self.write_refresh(when="1970-01-01T00:10:00+00:00")
        run.return_value=Mock(stdout="S\n",returncode=0)
        body=read_collector_health(
            self.root,now=1000.0,fixed_root=self.fixed
        )
        self.assertTrue(body["heartbeat_fresh"])
        self.assertFalse(body["frontier_progressing"])

    @patch("os.kill",side_effect=ProcessLookupError)
    def test_dead_process_fails_closed(self, kill):
        self.write_status()
        self.write_refresh()
        body=read_collector_health(
            self.root,now=1000.0,fixed_root=self.fixed
        )
        self.assertFalse(body["process_alive"])

    def test_missing_runtime_evidence_fails_closed(self):
        body=read_collector_health(
            self.root,now=1000.0,fixed_root=self.fixed
        )
        self.assertFalse(body["process_alive"])
        self.assertFalse(body["heartbeat_fresh"])
        self.assertFalse(body["live_context_valid"])
        self.assertFalse(body["frontier_progressing"])

    @patch("ptt_offline.collector_runtime_health.subprocess.run")
    @patch("os.kill")
    def test_zombie_pid_is_treated_as_dead(self, kill, run):
        self.write_status()
        self.write_refresh()
        run.return_value=Mock(stdout="Z    \n",returncode=0)
        body=read_collector_health(
            self.root,now=1000.0,fixed_root=self.fixed
        )
        self.assertFalse(body["process_alive"])
        self.assertEqual(body["process_state"],"Z")

    @patch("ptt_offline.collector_runtime_health.subprocess.run")
    @patch("os.kill")
    def test_empty_ps_state_fails_closed(self, kill, run):
        self.write_status()
        self.write_refresh()
        run.return_value=Mock(stdout="",returncode=1)
        body=read_collector_health(
            self.root,now=1000.0,fixed_root=self.fixed
        )
        self.assertFalse(body["process_alive"])
        self.assertIsNone(body["process_state"])


if __name__=="__main__":
    unittest.main()
