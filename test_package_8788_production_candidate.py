"""Offline regression for the real-name #68 deployment candidate package."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from tools.package_8788_production_candidate import package, TARGET, ASSETS

class ProductionPackageTests(unittest.TestCase):
    def test_direct_cli_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "cli-worker"
            repo_root = Path(__file__).resolve().parent
            run = subprocess.run([sys.executable, str(repo_root / "tools" / "package_8788_production_candidate.py"), "--output", str(output)], cwd=repo_root, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads((output / "wrangler.jsonc").read_text())["name"], TARGET)

    def test_existing_worker_identity_and_static_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "worker"
            receipt = package(dest)
            config = json.loads((dest / "wrangler.jsonc").read_text())
            self.assertEqual(config["name"], TARGET)
            self.assertEqual(config["main"], "entry.py")
            self.assertIn("python_workers", config["compatibility_flags"])
            self.assertEqual(config["assets"]["binding"], "ASSETS")
            self.assertEqual(config["services"], [{"binding": "PUBLIC_API", "service": "holoviewer-public-api"}])
            self.assertFalse(config["assets"]["run_worker_first"])
            self.assertNotIn("d1_databases", config)
            self.assertFalse(receipt["worker_deployed"])
            self.assertTrue(receipt["requires_explicit_owner_deploy_approval"])
            self.assertEqual(set(receipt["assets"]), set(ASSETS))
            self.assertFalse((dest / "entry_fixture.py").exists())
            shell = (dest / "client_ui_shell.py").read_text()
            self.assertIn("top:466px", shell)
            self.assertIn("max-height:calc(100vh - 478px)", shell)
            self.assertNotIn("top:270px;z-index:65;width:64px;max-height:calc(100vh - 282px)", shell)
            self.assertEqual(
                receipt["authorized_ui_overrides"]["live_channel_rail_clear_navigation"],
                "position:fixed;left:2px;top:466px;z-index:65;width:64px;max-height:calc(100vh - 478px);",
            )
            self.assertEqual(
                receipt["authorized_ui_overrides"]["default_hololive_keeps_unclassified_cards_visible"],
                "item.hidden=activeStreamFilter!=='all'&&group!==activeStreamFilter&&!(activeStreamFilter==='hololive'&&(group==='unknown'||group==='other'));",
            )
            self.assertEqual(
                receipt["authorized_ui_overrides"]["default_hololive_keeps_unclassified_live_rail_visible"],
                "item.hidden=filter!=='all'&&item.dataset.group!==filter&&!(filter==='hololive'&&(item.dataset.group==='unknown'||item.dataset.group==='other'));",
            )
            packaged_home = (dest / "client_home.py").read_text()
            packaged_shell = (dest / "client_ui_shell.py").read_text()
            self.assertIn("group==='unknown'||group==='other'", packaged_home)
            self.assertIn("item.dataset.group==='unknown'||item.dataset.group==='other'", packaged_shell)
            self.assertEqual(
                receipt["runtime_optimizations"]["client_home_lazy_runtime_imports"],
                "applied",
            )
            home = (dest / "client_home.py").read_text()
            self.assertNotIn("from youtube_metadata import YoutubeVideo", home)
            self.assertNotIn("from live_stream_discovery import LiveDiscoveryCache\nfrom today_stream_status", home)
            self.assertIn("from today_stream_status import stream_state", home)

if __name__ == "__main__":
    unittest.main()
