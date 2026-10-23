import tempfile
import unittest
from pathlib import Path

from ptt_offline.install_publisher_launchd import LABEL,build_plist

class LaunchdInstallerTests(unittest.TestCase):
    def test_plist_uses_keepalive_service_and_owner_paths(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)/"repo"; repo.mkdir()
            root=Path(td)/"owner"; root.mkdir()
            (root/".ptt-publisher-state").mkdir()
            body=build_plist(
                repo_root=repo,
                owner_root=root,
                python_executable="/opt/homebrew/bin/python3",
            )
            self.assertEqual(body["Label"],LABEL)
            self.assertTrue(body["RunAtLoad"])
            self.assertTrue(body["KeepAlive"])
            self.assertEqual(body["WorkingDirectory"],str(repo.resolve()))
            args=body["ProgramArguments"]
            self.assertEqual(args[0],"/opt/homebrew/bin/python3")
            self.assertIn("ptt_offline.publisher_service",args)
            self.assertEqual(args[args.index("--root")+1],str(root.resolve()))
            self.assertEqual(
                body["StandardOutPath"],
                str(root.resolve()/".ptt-publisher-state"/"publisher-service.log"),
            )
            self.assertEqual(body["StandardErrorPath"],body["StandardOutPath"])

if __name__=="__main__":
    unittest.main()
