"""Offline regression for the real-name #68 deployment candidate package."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.package_8788_production_candidate import package, TARGET, ASSETS

class ProductionPackageTests(unittest.TestCase):
    def test_existing_worker_identity_and_static_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "worker"
            receipt = package(dest)
            config = json.loads((dest / "wrangler.jsonc").read_text())
            self.assertEqual(config["name"], TARGET)
            self.assertEqual(config["main"], "entry.py")
            self.assertIn("python_workers", config["compatibility_flags"])
            self.assertEqual(config["assets"]["binding"], "ASSETS")
            self.assertFalse(config["assets"]["run_worker_first"])
            self.assertNotIn("d1_databases", config)
            self.assertFalse(receipt["worker_deployed"])
            self.assertTrue(receipt["requires_explicit_owner_deploy_approval"])
            self.assertEqual(set(receipt["assets"]), set(ASSETS))
            self.assertFalse((dest / "entry_fixture.py").exists())

if __name__ == "__main__":
    unittest.main()
