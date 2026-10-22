from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from ptt_offline.daily_ptt_scheduler_gate import run_scheduler_gate


TPE=ZoneInfo("Asia/Taipei")


class DailyPttSchedulerGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.collector=self.root/"collector"
        self.collector.mkdir()
        (self.collector/"hololive_ptt.sqlite3").write_bytes(b"x")
        self.state=self.root/"state"
        self.config=self.root/"daily.json"
        self.config.write_text(json.dumps({
            "collector_source":str(self.collector/"hololive_ptt.sqlite3"),
            "state_root":str(self.state),
        }),encoding="utf-8")
        self.now=datetime(2026,10,22,7,30,tzinfo=TPE)

    def healthy(self, *, aid="#1live", frontier=200):
        return {
            "process_alive":True,
            "heartbeat_fresh":True,
            "live_context_valid":True,
            "frontier_progressing":True,
            "live_aid":aid,
            "frontier":frontier,
            "phase":"collecting",
        }

    def dead(self):
        return {
            "process_alive":False,
            "heartbeat_fresh":False,
            "live_context_valid":True,
            "frontier_progressing":False,
            "live_aid":"#1live",
            "frontier":199,
            "phase":"stopped",
        }

    def test_healthy_collector_never_restarts_and_downstream_stays_hold(self):
        called=[]
        body=run_scheduler_gate(
            daily_config_path=self.config,
            now=self.now,
            health_probe=lambda:self.healthy(),
            recovery_executor=lambda:called.append(True),
        )
        self.assertTrue(body["health_gate_passed"])
        self.assertFalse(body["restart_attempted"])
        self.assertEqual(called,[])
        self.assertFalse(body["downstream_authorized"])
        self.assertFalse(body["archive_ready"])
        self.assertEqual(body["failure_code"],"authoritative-tail-integration-pending")

    def test_dead_stopped_collector_gets_one_recovery_and_reprobe(self):
        probes=[self.dead(),self.healthy(frontier=210)]
        calls=[]
        def probe():
            return probes.pop(0)
        def recover():
            calls.append(True)
            return {"status":"RECOVERED"}
        body=run_scheduler_gate(
            daily_config_path=self.config,
            now=self.now,
            health_probe=probe,
            recovery_executor=recover,
        )
        self.assertEqual(calls,[True])
        self.assertTrue(body["restart_attempted"])
        self.assertEqual(body["restart_result"],"RECOVERED")
        self.assertTrue(body["health_gate_passed"])
        self.assertEqual(body["resolved_live_frontier"],210)
        self.assertFalse(body["downstream_authorized"])
        receipt=self.state/"collector-health"/"2026-10-21.json"
        self.assertTrue(receipt.is_file())

    def test_alive_unhealthy_fails_closed_without_recovery(self):
        called=[]
        unhealthy=self.healthy()
        unhealthy["heartbeat_fresh"]=False
        body=run_scheduler_gate(
            daily_config_path=self.config,
            now=self.now,
            health_probe=lambda:unhealthy,
            recovery_executor=lambda:called.append(True),
        )
        self.assertEqual(called,[])
        self.assertFalse(body["restart_attempted"])
        self.assertEqual(body["restart_result"],"ALIVE_UNHEALTHY_NO_RECOVERY_CHANNEL")
        self.assertFalse(body["health_gate_passed"])
        self.assertFalse(body["archive_ready"])
        self.assertEqual(body["failure_code"],"collector-health-not-restored")

    def test_failed_dead_recovery_fails_closed_before_downstream(self):
        probes=[self.dead(),self.dead()]
        body=run_scheduler_gate(
            daily_config_path=self.config,
            now=self.now,
            health_probe=lambda:probes.pop(0),
            recovery_executor=lambda:{"status":"FAILED"},
        )
        self.assertTrue(body["restart_attempted"])
        self.assertEqual(body["restart_result"],"FAILED")
        self.assertFalse(body["health_gate_passed"])
        self.assertFalse(body["downstream_authorized"])
        self.assertFalse(body["archive_ready"])
        self.assertEqual(body["safety"]["restart_attempts"],1)


if __name__=="__main__":
    unittest.main()
