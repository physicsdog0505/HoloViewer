"""Offline packaging regression for pinned 4174 Python Worker feasibility."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.build_python_worker_bundle import build, PINNED


class WorkerBundleTest(unittest.TestCase):
    def test_pinned_product_files_and_entrypoint(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "bundle"
            receipt = build(output)
            self.assertEqual(receipt["pinned_source"], PINNED)
            self.assertGreaterEqual(receipt["verified_product_files"], 82)
            self.assertEqual((output / "entry.py").read_text(),
                             "from platform_adapter.cloudflare_entry import Default\n")
            config = json.loads((output / "wrangler.jsonc").read_text())
            self.assertIn("python_workers", config["compatibility_flags"])
            self.assertIn('tzdata>=2025.2', (output / "pyproject.toml").read_text())
            self.assertFalse(receipt["deployed"])
            self.assertFalse((output / "requirements.txt").exists())
            if "requirements.txt -> bundle-metadata/requirements.txt" in receipt["relocated_legacy_metadata"]:
                original = (Path(__file__).parent / "vendor" / "4174-a144bb3" / "requirements.txt").read_bytes()
                copied = (output / "bundle-metadata" / "requirements.txt").read_bytes()
                self.assertEqual(copied, original)
            with self.assertRaises(ValueError):
                build(output)


if __name__ == "__main__":
    unittest.main()
