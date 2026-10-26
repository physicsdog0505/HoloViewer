from __future__ import annotations

import unittest

from ptt_offline.collector_health_contract import classify_collector_health


class CollectorHealthContractTests(unittest.TestCase):
    def test_healthy_contract_preserves_identity(self):
        body=classify_collector_health({
            "process_alive":True,
            "heartbeat_fresh":True,
            "live_context_valid":True,
            "frontier_progressing":True,
            "live_aid":"#1live",
            "frontier":368,
        })
        self.assertTrue(body["healthy"])
        self.assertEqual(body["status"],"HEALTHY")
        self.assertEqual(body["failure_codes"],[])
        self.assertEqual(body["live_aid"],"#1live")
        self.assertEqual(body["frontier"],368)

    def test_each_required_health_bit_fails_closed(self):
        base={
            "process_alive":True,
            "heartbeat_fresh":True,
            "live_context_valid":True,
            "frontier_progressing":True,
        }
        expected={
            "process_alive":"collector-process-dead",
            "heartbeat_fresh":"collector-heartbeat-stale",
            "live_context_valid":"collector-live-context-invalid",
            "frontier_progressing":"collector-frontier-stalled",
        }
        for key,code in expected.items():
            with self.subTest(key=key):
                sample=dict(base)
                sample[key]=False
                body=classify_collector_health(sample)
                self.assertFalse(body["healthy"])
                self.assertIn(code,body["failure_codes"])

    def test_missing_evidence_fails_closed(self):
        body=classify_collector_health(None)
        self.assertFalse(body["healthy"])
        self.assertEqual(
            body["failure_codes"],["collector-health-unavailable"])


if __name__=="__main__":
    unittest.main()
