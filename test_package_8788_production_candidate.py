"""Offline regression for the real-name #68 deployment candidate package."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from tools.package_8788_production_candidate import package, TARGET, ASSETS, SUPPORT_COLOR_EXPORT


def write_support_colors(path: Path):
    rows = []
    for i in range(66):
        channel_id = "UC" + f"{i:022d}"
        if i < 56:
            rows.append({"channel_id": channel_id, "display_mode": "solid", "color_hex": "#123456"})
        elif i == 56:
            rows.append({"channel_id": channel_id, "display_mode": "dual_color", "color_hexes": ["#123456", "#654321"]})
        else:
            rows.append({"channel_id": channel_id, "display_mode": "neutral"})
    path.write_text(json.dumps({"schema_version": 1, "fallback": "neutral", "channels": rows}), encoding="utf-8")
    return path

class ProductionPackageTests(unittest.TestCase):
    def test_direct_cli_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "cli-worker"
            repo_root = Path(__file__).resolve().parent
            colors = write_support_colors(Path(temp) / "colors.json")
            run = subprocess.run([sys.executable, str(repo_root / "tools" / "package_8788_production_candidate.py"), "--output", str(output), "--support-colors", str(colors)], cwd=repo_root, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads((output / "wrangler.jsonc").read_text())["name"], TARGET)

    def test_existing_worker_identity_and_static_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "worker"
            colors = write_support_colors(Path(temp) / "colors.json")
            receipt = package(dest, support_colors=colors)
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
            self.assertTrue((dest / SUPPORT_COLOR_EXPORT).is_file())
            self.assertEqual(receipt["support_colors"]["rows"], 66)
            self.assertEqual(receipt["support_colors"]["colored"], 57)
            self.assertEqual(receipt["support_colors"]["neutral"], 9)
            self.assertEqual(receipt["support_colors"]["dual"], 1)
            shell = (dest / "client_ui_shell.py").read_text()
            self.assertIn("top:466px", shell)
            self.assertIn("max-height:calc(100vh - 478px)", shell)
            self.assertNotIn("top:270px;z-index:65;width:64px;max-height:calc(100vh - 282px)", shell)
            self.assertEqual(
                receipt["authorized_ui_overrides"]["live_channel_rail_clear_navigation"],
                "position:fixed;left:2px;top:466px;z-index:65;width:64px;max-height:calc(100vh - 478px);",
            )

if __name__ == "__main__":
    unittest.main()
