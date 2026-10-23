import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ptt_offline.publisher_supervisor import (
    LABEL,render_plist,preflight,apply_cutover,validate_candidate_service,
)
from ptt_offline.public_today_contract import ContractError

class SupervisorTests(unittest.TestCase):
    def test_render_plist_is_exact_single_service_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            repo=root/"repo"; runtime=root/"runtime"
            repo.mkdir(); runtime.mkdir()
            plist=render_plist(repo_root=repo,runtime_root=runtime,
                               python_executable="/usr/bin/python3",
                               log_path=runtime/"publisher.log")
            self.assertEqual(plist["Label"],LABEL)
            self.assertEqual(plist["ProgramArguments"][:4],
                ["/usr/bin/python3","-B","-m","ptt_offline.publisher_service"])
            self.assertEqual(plist["ProgramArguments"][-2:],["--root",str(runtime.resolve())])
            self.assertTrue(plist["RunAtLoad"])
            self.assertEqual(plist["KeepAlive"],{"SuccessfulExit":False})
            self.assertEqual(plist["ThrottleInterval"],30)

    def test_preflight_allows_stopped_runtime_with_uncertain_state_for_startup_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            repo=root/"repo"; runtime=root/"runtime"
            repo.mkdir(); runtime.mkdir()
            state=runtime/".ptt-publisher-state"
            (state/"state").mkdir(parents=True)
            (runtime/"hololive_ptt.sqlite3").write_bytes(b"x")
            (state/".publisher-secrets.json").write_text("{}")
            (state/"state"/"x.json").write_text(json.dumps({
                "status":"REMOTE_UNCERTAIN","pending_batch_id":"ptt48:x"
            }))
            with patch("ptt_offline.publisher_supervisor._run") as run:
                run.return_value.stdout="abc\n"
                proof=preflight(repo_root=repo,runtime_root=runtime,expected_head="abc")
            self.assertEqual(proof["ambiguous_count"],1)
            self.assertIsNone(proof["manual_pid"])

    def test_preflight_rejects_live_manual_writer_with_uncertain_state(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            repo=root/"repo"; runtime=root/"runtime"
            repo.mkdir(); runtime.mkdir()
            state=runtime/".ptt-publisher-state"
            (state/"state").mkdir(parents=True)
            (runtime/"hololive_ptt.sqlite3").write_bytes(b"x")
            (state/".publisher-secrets.json").write_text("{}")
            (state/"publisher.pid").write_text("123\n")
            (state/"state"/"x.json").write_text(json.dumps({
                "status":"REMOTE_UNCERTAIN","pending_batch_id":"ptt48:x"
            }))
            with patch("ptt_offline.publisher_supervisor._run") as run, \
                 patch("ptt_offline.publisher_supervisor._pid_alive",return_value=True), \
                 patch("ptt_offline.publisher_supervisor._command",return_value="python -m ptt_offline.recurring_publisher"), \
                 patch("ptt_offline.publisher_supervisor._lock_holders",return_value=[123]):
                run.return_value.stdout="abc\n"
                with self.assertRaises(ContractError):
                    preflight(repo_root=repo,runtime_root=runtime,expected_head="abc")

    def test_preflight_recognizes_launchd_service_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            repo=root/"repo"; runtime=root/"runtime"
            repo.mkdir(); runtime.mkdir()
            state=runtime/".ptt-publisher-state"
            (state/"state").mkdir(parents=True)
            (runtime/"hololive_ptt.sqlite3").write_bytes(b"x")
            (state/".publisher-secrets.json").write_text("{}")
            (state/"publisher.pid").write_text("123\n")
            with patch("ptt_offline.publisher_supervisor._run") as run, \
                 patch("ptt_offline.publisher_supervisor._pid_alive",return_value=True), \
                 patch("ptt_offline.publisher_supervisor._command",return_value="python -m ptt_offline.publisher_service --root /tmp/runtime"), \
                 patch("ptt_offline.publisher_supervisor._lock_holders",return_value=[123]):
                run.return_value.stdout="abc\n"
                proof=preflight(repo_root=repo,runtime_root=runtime,expected_head="abc")
            self.assertEqual(proof["runtime_kind"],"launchd_service")
            self.assertEqual(proof["manual_pid"],123)

    def test_candidate_service_validation_runs_without_runtime_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)/"repo"; repo.mkdir()
            class Result:
                stdout="usage: publisher_service [-h] --root ROOT\n"
            with patch("ptt_offline.publisher_supervisor._run",return_value=Result()) as run:
                receipt=validate_candidate_service(
                    repo_root=repo,python_executable="/usr/bin/python3")
            self.assertEqual(receipt["service_import"],"PASS")
            self.assertEqual(receipt["repo_root"],str(repo.resolve()))
            args,kwargs=run.call_args
            self.assertIn("ptt_offline.publisher_service",args[0])
            self.assertEqual(kwargs["cwd"],str(repo.resolve()))

    def test_candidate_validation_failure_happens_before_live_writer_stop(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            repo=root/"repo"; runtime=root/"runtime"
            repo.mkdir(); runtime.mkdir()
            state=runtime/".ptt-publisher-state"
            (state/"state").mkdir(parents=True)
            (runtime/"hololive_ptt.sqlite3").write_bytes(b"x")
            (state/".publisher-secrets.json").write_text("{}")
            (state/"publisher.pid").write_text("123\n")
            with patch("ptt_offline.publisher_supervisor._run") as run, \
                 patch("ptt_offline.publisher_supervisor._pid_alive",return_value=True), \
                 patch("ptt_offline.publisher_supervisor._command",return_value="python -m ptt_offline.recurring_publisher"), \
                 patch("ptt_offline.publisher_supervisor._lock_holders",return_value=[123]), \
                 patch("ptt_offline.publisher_supervisor.validate_candidate_service",side_effect=ContractError("bad candidate")), \
                 patch("ptt_offline.publisher_supervisor.os.kill") as kill:
                run.return_value.stdout="abc\n"
                with self.assertRaises(ContractError):
                    apply_cutover(repo_root=repo,runtime_root=runtime,
                        expected_head="abc",python_executable="/usr/bin/python3",
                        plist_path=root/"publisher.plist")
            kill.assert_not_called()

    def test_apply_is_idempotent_when_launchd_service_already_owns_writer(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            repo=root/"repo"; runtime=root/"runtime"
            repo.mkdir(); runtime.mkdir()
            state=runtime/".ptt-publisher-state"
            (state/"state").mkdir(parents=True)
            (runtime/"hololive_ptt.sqlite3").write_bytes(b"x")
            (state/".publisher-secrets.json").write_text("{}")
            (state/"publisher.pid").write_text("123\n")
            plist=root/"publisher.plist"
            with patch("ptt_offline.publisher_supervisor._run") as run, \
                 patch("ptt_offline.publisher_supervisor._pid_alive",return_value=True), \
                 patch("ptt_offline.publisher_supervisor._command",return_value="python -m ptt_offline.publisher_service --root /tmp/runtime"), \
                 patch("ptt_offline.publisher_supervisor._lock_holders",return_value=[123]), \
                 patch("ptt_offline.publisher_supervisor.os.kill") as kill:
                run.return_value.stdout="abc\n"
                result=apply_cutover(repo_root=repo,runtime_root=runtime,
                    expected_head="abc",python_executable="/usr/bin/python3",
                    plist_path=plist)
            self.assertEqual(result["status"],"ALREADY_SUPERVISED")
            self.assertEqual(result["new_writer_pid"],123)
            kill.assert_not_called()
            self.assertFalse(plist.exists())

    def test_preflight_accepts_clean_stopped_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            repo=root/"repo"; runtime=root/"runtime"
            repo.mkdir(); runtime.mkdir()
            state=runtime/".ptt-publisher-state"
            (state/"state").mkdir(parents=True)
            (runtime/"hololive_ptt.sqlite3").write_bytes(b"x")
            (state/".publisher-secrets.json").write_text("{}")
            (state/"state"/"x.json").write_text(json.dumps({"status":"ACKED"}))
            with patch("ptt_offline.publisher_supervisor._run") as run:
                run.return_value.stdout="abc\n"
                proof=preflight(repo_root=repo,runtime_root=runtime,expected_head="abc")
            self.assertEqual(proof["head"],"abc")
            self.assertIsNone(proof["manual_pid"])
            self.assertEqual(proof["ambiguous_count"],0)

if __name__=="__main__":
    unittest.main()
