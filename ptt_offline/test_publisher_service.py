import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ptt_offline.publisher_service import build_runtime

class PublisherServiceTests(unittest.TestCase):
    def test_build_runtime_uses_existing_state_and_exact_phase_a_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"hololive_ptt.sqlite3").write_bytes(b"sqlite")
            state=root/".ptt-publisher-state"
            state.mkdir()
            (state/".publisher-secrets.json").write_text(json.dumps({
                "PTT_PUBLISH_HMAC_SECRET":"p"*40,
                "PTT_TIME_AUTHORITY_SECRET":"t"*40,
            }))
            env,argv=build_runtime(root)
            self.assertEqual(env["PTT_ALLOW_CAPTURE_TIME_POLICY"],"true")
            self.assertEqual(env["PTT_PUBLISH_HMAC_SECRET"],"p"*40)
            self.assertEqual(env["PTT_TIME_AUTHORITY_SECRET"],"t"*40)
            self.assertIn("--adaptive-live-cadence",argv)
            self.assertEqual(argv[argv.index("--max-batches")+1],"1")
            self.assertEqual(argv[argv.index("--burst-max-batches")+1],"1")
            self.assertEqual(argv[argv.index("--batch-cap")+1],"10")
            self.assertEqual(argv[argv.index("--iterations")+1],"0")
            self.assertEqual(argv[argv.index("--state-dir")+1],str(state/"state"))

    def test_missing_or_invalid_secret_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"hololive_ptt.sqlite3").write_bytes(b"sqlite")
            state=root/".ptt-publisher-state"; state.mkdir()
            (state/".publisher-secrets.json").write_text(json.dumps({
                "PTT_PUBLISH_HMAC_SECRET":"short",
                "PTT_TIME_AUTHORITY_SECRET":"t"*40,
            }))
            with self.assertRaises(Exception):
                build_runtime(root)

if __name__=="__main__":
    unittest.main()
