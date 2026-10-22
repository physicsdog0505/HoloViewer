from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ptt_offline.collector_controlled_recovery import (
    controlled_start_once,
    load_recovery_config,
)
from ptt_offline.public_today_contract import ContractError


class CollectorControlledRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.cfg=self.root/"recovery.json"
        self.receipt=self.root/"receipt.json"
        self.cfg.write_text(json.dumps({
            "enabled":True,"username":"fixtureuser","test_account":False
        }),encoding="utf-8")
        (self.root/"collector_control.py").write_text(
            "def launch_collector(username, *, test_account=False):\n"
            "    return 'launched '+username\n",encoding="utf-8"
        )

    def test_healthy_never_launches(self):
        healthy={
            "process_alive":True,"heartbeat_fresh":True,
            "live_context_valid":True,"frontier_progressing":True,
            "live_aid":"#live","frontier":9,"phase":"collecting",
        }
        body=controlled_start_once(
            collector_root=self.root,config_path=self.cfg,
            receipt_path=self.receipt,run_key="2026-10-22",
            health_probe=lambda:healthy,
        )
        self.assertEqual(body["status"],"NOT_NEEDED")
        self.assertFalse(body["attempted"])
        self.assertFalse(self.receipt.exists())

    def test_dead_launches_once_and_confirms_health(self):
        calls=[]
        def probe(**kwargs):
            calls.append(kwargs)
            if len(calls)==1:
                return {
                    "process_alive":False,"heartbeat_fresh":False,
                    "phase":"stopped","pid":22222,"run_id":"old",
                }
            return {
                "process_alive":True,"heartbeat_fresh":True,
                "live_context_valid":True,"frontier_progressing":True,
                "live_aid":"#new","frontier":12,"phase":"collecting",
                "pid":33333,"run_id":"new",
                "heartbeat_timestamp":1001.0,
                "heartbeat_age_seconds":0.1,
            }
        body=controlled_start_once(
            collector_root=self.root,config_path=self.cfg,
            receipt_path=self.receipt,run_key="2026-10-22",
            health_probe=probe,
            sleep=lambda _x:None,
        )
        self.assertEqual(body["status"],"RECOVERED")
        self.assertTrue(body["attempted"])
        self.assertEqual(body["restart_attempts"],1)
        saved=json.loads(self.receipt.read_text())
        self.assertNotIn("username",saved)
        self.assertFalse(saved["checkpoint_reset"])

    def test_same_run_key_cannot_attempt_twice(self):
        self.receipt.write_text(json.dumps({
            "run_key":"2026-10-22","attempted":True,"status":"FAILED"
        }),encoding="utf-8")
        with self.assertRaises(ContractError):
            controlled_start_once(
                collector_root=self.root,config_path=self.cfg,
                receipt_path=self.receipt,run_key="2026-10-22",
                health_probe=lambda:{
                    "process_alive":False,"heartbeat_fresh":False,"phase":"stopped"
                },
            )

    def test_blocked_never_launches(self):
        with self.assertRaises(ContractError):
            controlled_start_once(
                collector_root=self.root,config_path=self.cfg,
                receipt_path=self.receipt,run_key="2026-10-22",
                health_probe=lambda:{
                    "process_alive":False,"heartbeat_fresh":False,"phase":"blocked"
                },
            )

    def test_config_requires_explicit_enable_and_ascii_username(self):
        self.cfg.write_text(json.dumps({"enabled":False,"username":"x"}))
        with self.assertRaises(ContractError):
            load_recovery_config(self.cfg)


    def test_alive_unhealthy_never_calls_launcher(self):
        (self.root/"collector_control.py").write_text(
            "def launch_collector(username, *, test_account=False):\n"
            "    raise AssertionError('launcher must not be called')\n",
            encoding="utf-8",
        )
        body=controlled_start_once(
            collector_root=self.root,config_path=self.cfg,
            receipt_path=self.receipt,run_key="2026-10-22",
            health_probe=lambda **_kwargs:{
                "process_alive":True,
                "heartbeat_fresh":False,
                "live_context_valid":False,
                "frontier_progressing":False,
                "phase":"collecting",
                "pid":22222,
                "run_id":"same",
            },
        )
        self.assertEqual(
            body["status"],"ALIVE_UNHEALTHY_NO_RECOVERY_CHANNEL"
        )
        self.assertFalse(body["attempted"])
        self.assertFalse(self.receipt.exists())

    def test_fresh_old_refresh_does_not_confirm_new_run(self):
        calls=[]
        def probe(**kwargs):
            calls.append(kwargs)
            if len(calls)==1:
                return {
                    "process_alive":False,"heartbeat_fresh":False,
                    "phase":"stopped","pid":22222,"run_id":"old",
                }
            return {
                "process_alive":True,
                "heartbeat_fresh":True,
                "live_context_valid":False,
                "frontier_progressing":False,
                "live_aid":None,
                "frontier":None,
                "phase":"collecting",
                "pid":33333,
                "run_id":"new",
                "heartbeat_timestamp":1001.0,
                "heartbeat_age_seconds":0.1,
            }
        body=controlled_start_once(
            collector_root=self.root,config_path=self.cfg,
            receipt_path=self.receipt,run_key="2026-10-22",
            health_probe=probe,
            sleep=lambda _x:None,
            confirm_timeout_seconds=1,
            confirm_interval_seconds=0,
        )
        self.assertEqual(body["status"],"STARTED_UNCONFIRMED")
        self.assertGreaterEqual(len(calls),2)
        self.assertIn("refresh_after_timestamp",calls[1])


    @patch("ptt_offline.collector_controlled_recovery.time.time",return_value=1000.0)
    def test_old_but_fresh_heartbeat_does_not_confirm_recovery(self, _now):
        calls=[]
        def probe(**kwargs):
            calls.append(kwargs)
            if len(calls)==1:
                return {
                    "process_alive":False,
                    "heartbeat_fresh":False,
                    "phase":"stopped",
                    "pid":22222,
                    "run_id":"old",
                }
            return {
                "process_alive":True,
                "heartbeat_fresh":True,
                "live_context_valid":True,
                "frontier_progressing":True,
                "live_aid":"#new",
                "frontier":12,
                "phase":"collecting",
                "pid":33333,
                "run_id":"new",
                "heartbeat_timestamp":999.5,
                "heartbeat_age_seconds":0.5,
            }
        body=controlled_start_once(
            collector_root=self.root,config_path=self.cfg,
            receipt_path=self.receipt,run_key="2026-10-22",
            health_probe=probe,
            sleep=lambda _x:None,
            confirm_timeout_seconds=1,
            confirm_interval_seconds=0,
        )
        self.assertEqual(body["status"],"STARTED_UNCONFIRMED")

    def test_unknown_dead_phase_is_not_restart_eligible(self):
        with self.assertRaises(ContractError):
            controlled_start_once(
                collector_root=self.root,config_path=self.cfg,
                receipt_path=self.receipt,run_key="2026-10-22",
                health_probe=lambda **_kwargs:{
                    "process_alive":False,
                    "heartbeat_fresh":False,
                    "phase":"unknown",
                    "pid":None,
                    "run_id":None,
                },
            )


if __name__=="__main__":
    unittest.main()
