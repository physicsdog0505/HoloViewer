from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.daily_ptt_orchestrator import (
    DailyPttOrchestrationError,
    pending_archive_days,
    run_backlog_orchestration,
    run_orchestration,
)


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
            mode="production",
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
            mode="production",
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
            mode="production",
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
            mode="production",
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
            mode="acceptance",
            command_runner=runner,
        )
        self.assertEqual(body["status"],"SUCCEEDED")
        self.assertEqual(body["downstream_status"],"READY_TO_DEPLOY")


    def test_production_ready_to_deploy_fails_closed(self):
        def runner(command):
            if command==["gate"]:
                return 0,{"day":"2026-10-21","health_gate_passed":True}
            return 0,{"day":"2026-10-21","status":"READY_TO_DEPLOY"}

        body=run_orchestration(
            gate_command=["gate"],
            downstream_command=["archive"],
            mode="production",
            command_runner=runner,
        )
        self.assertEqual(body["status"],"FAILED")
        self.assertEqual(
            body["failure_code"],"ready-to-deploy-not-valid-in-production")

    def test_gate_and_downstream_day_mismatch_fails_closed(self):
        def runner(command):
            if command==["gate"]:
                return 0,{"day":"2026-10-21","health_gate_passed":True}
            return 0,{
                "day":"2026-10-22",
                "status":"VERIFIED_COMPLETE_PUBLISHED",
            }

        body=run_orchestration(
            gate_command=["gate"],
            downstream_command=["archive"],
            mode="production",
            command_runner=runner,
        )
        self.assertEqual(body["status"],"FAILED")
        self.assertEqual(body["day"],"2026-10-21")
        self.assertEqual(body["failure_code"],"gate-downstream-day-mismatch")

    def test_invalid_gate_day_fails_before_downstream(self):
        calls=[]
        def runner(command):
            calls.append(command)
            return 0,{"day":"2026-10-32","health_gate_passed":True}

        body=run_orchestration(
            gate_command=["gate"],
            downstream_command=["archive"],
            mode="production",
            command_runner=runner,
        )
        self.assertEqual(calls,[["gate"]])
        self.assertEqual(body["status"],"FAILED")
        self.assertFalse(body["downstream_invoked"])
        self.assertEqual(body["failure_code"],"gate-day-missing")

    def test_downstream_exception_keeps_stage_and_failure_detail(self):
        def runner(command):
            if command==["gate"]:
                return 0,{"day":"2026-11-07","health_gate_passed":True}
            raise DailyPttOrchestrationError(
                "command did not return one JSON object: DailyHistoryRuntimeError")

        body=run_orchestration(
            gate_command=["gate"],downstream_command=["archive"],
            mode="production",command_runner=runner)

        self.assertEqual(body["status"],"FAILED")
        self.assertEqual(body["day"],"2026-11-07")
        self.assertEqual(body["failure_code"],"command-output-invalid")
        self.assertEqual(body["failure_stage"],"downstream")
        self.assertIn("DailyHistoryRuntimeError",body["failure_detail"])

    def test_pending_days_are_oldest_unverified_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for day,verified in (("2026-11-06",True),("2026-11-08",False)):
                target=root/"archive"/day/"archive-job.json"
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps({"job_verified":verified}),encoding="utf-8")

            days,more=pending_archive_days(
                state_root=root,start_day="2026-11-06",
                through_day="2026-11-10",limit=3)

        self.assertEqual(days,["2026-11-07","2026-11-08","2026-11-09"])
        self.assertTrue(more)

    def test_backlog_expands_day_and_stops_on_first_failure(self):
        calls=[]
        def runner(command):
            calls.append(command)
            day=command[-1]
            if command[0]=="gate":
                return 0,{"day":day,"health_gate_passed":True}
            if day=="2026-11-08":
                return 2,{"day":day,"status":"NOT_ARCHIVE_READY",
                          "failure_code":"archive-build-failed"}
            return 0,{"day":day,"status":"VERIFIED_COMPLETE_PUBLISHED"}

        with tempfile.TemporaryDirectory() as tmp:
            body=run_backlog_orchestration(
                gate_command=["gate","--day","{day}"],
                downstream_command=["archive","--day","{day}"],
                mode="production",state_root=Path(tmp),
                start_day="2026-11-07",through_day="2026-11-10",
                max_days=4,command_runner=runner)

        self.assertEqual(body["status"],"FAILED")
        self.assertEqual(body["day"],"2026-11-08")
        self.assertEqual(body["processed_days"],["2026-11-07"])
        self.assertEqual(calls,[
            ["gate","--day","2026-11-07"],
            ["archive","--day","2026-11-07"],
            ["gate","--day","2026-11-08"],
            ["archive","--day","2026-11-08"],
        ])

    def test_backlog_runs_monthly_release_once_after_all_days(self):
        calls=[]
        def runner(command):
            calls.append(command)
            if command==["monthly","2026-11","2026-11-08"]:
                return 0,{"status":"MONTHLY_RELEASE_DEPLOYED"}
            day=command[-1]
            if command[0]=="gate":
                return 0,{"day":day,"health_gate_passed":True}
            return 0,{"day":day,"status":"VERIFIED_COMPLETE_PUBLISHED"}

        with tempfile.TemporaryDirectory() as tmp:
            body=run_backlog_orchestration(
                gate_command=["gate","{day}"],
                downstream_command=["archive","{day}"],
                post_command=["monthly","{month}","{day}"],
                mode="production",state_root=Path(tmp),
                start_day="2026-11-07",through_day="2026-11-08",
                max_days=3,command_runner=runner)

        self.assertEqual(body["status"],"SUCCEEDED")
        self.assertEqual(body["post_receipt"]["status"],"MONTHLY_RELEASE_DEPLOYED")
        self.assertEqual(calls[-1],["monthly","2026-11","2026-11-08"])

if __name__=="__main__":
    unittest.main()
