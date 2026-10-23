import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ptt_offline.publisher_supervisor import LABEL,render_plist,preflight
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
