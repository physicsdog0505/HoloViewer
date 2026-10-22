from __future__ import annotations

import unittest

from ptt_offline.daily_ptt_orchestrator import run_orchestration


class DailyPttOrchestratorTests(unittest.TestCase):
    def test_healthy_gate_runs_downstream_once(self):
        calls=[]
        def runner(command):
            calls.append(command)
            if command==["gate"]:
                return 0,{
                    "day":"2026-10-21",
                    "health_gate_passed":True,
                    "failure_code":None,
                }
            return 0,{
                "day":"2026-10-21",
                "status":"VERIFIED_COMPLETE_PUBLISHED",
            }

        body=run_orchestration(
            gate_command=["gate"],
            downstream_command=["archive"],
            command_runner=runner,
        )

        self.assertEqual(calls,[["gate"],["archive"]])
        self.assertEqual(body["status"],"SUCCEEDED")
        self.assertTrue(body["health_gate_passed"])
        self.assertTrue(body["downstream_invoked"])
        self.assertEqual(
            body["downstream_status"],"VERIFIED_COMPLETE_PUBLISHED")

    def test_unhealthy_gate_fails_closed_without_downstream(self):
        calls=[]
        def runner(command):
            calls.append(command)
            return 3,{
                "day":"2026-10-21",
                "health_gate_passed":False,
                "failure_code":"collector-health-not-restored",
            }

        body=run_orchestration(
            gate_command=["gate"],
            downstream_command=["archive"],
            command_runner=runner,
        )

        self.assertEqual(calls,[["gate"]])
        self.assertEqual(body["status"],"BLOCKED")
        self.assertFalse(body["downstream_invoked"])
        self.assertEqual(body["downstream_status"],"NOT_RUN")
        self.assertEqual(
            body["failure_code"],"collector-health-not-restored")

    def test_gate_nonzero_blocks_even_if_payload_claims_healthy(self):
        calls=[]
        def runner(command):
            calls.append(command)
            return 2,{
                "day":"2026-10-21",
                "health_gate_passed":True,
                "failure_code":"gate-command-failed",
            }

        body=run_orchestration(
            gate_command=["gate"],
            downstream_command=["archive"],
            command_runner=runner,
        )

        self.assertEqual(calls,[["gate"]])
        self.assertEqual(body["status"],"BLOCKED")
        self.assertFalse(body["downstream_invoked"])

    def test_downstream_failure_is_not_claimed_success(self):
        calls=[]
        def runner(command):
            calls.append(command)
            if command==["gate"]:
                return 0,{
                    "day":"2026-10-21",
                    "health_gate_passed":True,
                }
            return 2,{
                "day":"2026-10-21",
                "status":"NOT_ARCHIVE_READY",
                "failure_code":"finalization-not-ready",
            }

        body=run_orchestration(
            gate_command=["gate"],
            downstream_command=["archive"],
            command_runner=runner,
        )

        self.assertEqual(calls,[["gate"],["archive"]])
        self.assertEqual(body["status"],"FAILED")
        self.assertTrue(body["downstream_invoked"])
        self.assertEqual(body["downstream_status"],"NOT_ARCHIVE_READY")
        self.assertEqual(body["failure_code"],"finalization-not-ready")

    def test_ready_to_deploy_is_valid_for_nonproduction_acceptance(self):
        def runner(command):
            if command==["gate"]:
                return 0,{"day":"2026-10-21","health_gate_passed":True}
            return 0,{"day":"2026-10-21","status":"READY_TO_DEPLOY"}

        body=run_orchestration(
            gate_command=["gate"],
            downstream_command=["archive"],
            command_runner=runner,
        )
        self.assertEqual(body["status"],"SUCCEEDED")
        self.assertEqual(body["downstream_status"],"READY_TO_DEPLOY")


if __name__=="__main__":
    unittest.main()
