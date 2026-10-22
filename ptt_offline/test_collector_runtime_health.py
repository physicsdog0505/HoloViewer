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

    @patch("os.kill")
    def test_fresh_repeated_frontier_is_healthy_activity(self, kill):
        self.write_status()
        self.write_refresh()
        body=read_collector_health(self.root,now=1000.0)
        self.assertTrue(body["process_alive"])
        self.assertTrue(body["heartbeat_fresh"])
        self.assertTrue(body["live_context_valid"])
        self.assertTrue(body["frontier_progressing"])
        self.assertEqual(body["live_aid"],"#1live")
        self.assertEqual(body["frontier"],178)

    @patch("os.kill")
    def test_stale_refresh_marks_activity_stalled_without_requiring_line_growth(self, kill):
        self.write_status()
        self.write_refresh(when="1970-01-01T00:10:00+00:00")
        body=read_collector_health(self.root,now=1000.0)
        self.assertTrue(body["heartbeat_fresh"])
        self.assertFalse(body["frontier_progressing"])

    @patch("os.kill",side_effect=ProcessLookupError)
    def test_dead_process_fails_closed(self, kill):
        self.write_status()
        self.write_refresh()
        body=read_collector_health(self.root,now=1000.0)
        self.assertFalse(body["process_alive"])

    def test_missing_runtime_evidence_fails_closed(self):
        body=read_collector_health(self.root,now=1000.0)
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
        body=read_collector_health(self.root,now=1000.0)
        self.assertFalse(body["process_alive"])
        self.assertEqual(body["process_state"],"Z")


if __name__=="__main__":
    unittest.main()
