import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_roster", ROOT / "tools" / "verify_channel_roster.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class RosterTest(unittest.TestCase):
    def test_baseline_pinned(self):
        raw = json.loads((ROOT / "docs" / "roster" / "legacy-66.json").read_text())
        ids = mod.validate(raw)
        self.assertEqual(len(ids), 66)
        self.assertEqual([x["legacy_order"] for x in raw["channels"]], list(range(66)))
        self.assertTrue(all(x["verified_live"] is False for x in raw["channels"]))

    def test_duplicate_denied(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            mod.validate({"channels": [{"channel_id": "UC" + "a" * 22}] * 2})

    def test_invalid_denied(self):
        with self.assertRaisesRegex(ValueError, "format"):
            mod.validate({"channels": [{"channel_id": "not-a-youtube-id"}]})

if __name__ == "__main__":
    unittest.main()
