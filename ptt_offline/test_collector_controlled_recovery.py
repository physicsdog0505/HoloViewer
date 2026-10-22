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
        states=[
            {"process_alive":False,"heartbeat_fresh":False,"phase":"stopped"},
            {"process_alive":True,"heartbeat_fresh":True,
             "live_context_valid":True,"frontier_progressing":True,
             "live_aid":"#new","frontier":12,"phase":"collecting"},
        ]
        body=controlled_start_once(
            collector_root=self.root,config_path=self.cfg,
            receipt_path=self.receipt,run_key="2026-10-22",
            health_probe=lambda:states.pop(0),
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


if __name__=="__main__":
    unittest.main()
