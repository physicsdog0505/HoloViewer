from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.run_public_frontend_owner_release import (
    FOREIGN_PREFIXES,
    is_foreign_rel,
    ownership_gate,
)


class PublicFrontendReleaseGateTests(unittest.TestCase):
    def test_foreign_prefixes_reject_youtube_and_ptt(self):
        self.assertTrue(is_foreign_rel("youtube/v1/manifest.json"))
        self.assertTrue(is_foreign_rel("ptt/v1/manifests/x.json"))
        self.assertFalse(is_foreign_rel("data/watchalong/manifest.json"))
        self.assertFalse(is_foreign_rel("data/search/aliases/v1/latest.json"))

    def test_ownership_gate_accepts_frontend_owned_runtime_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "site/data/watchalong").mkdir(parents=True)
            (root / "site/data/watchalong/manifest.json").write_text("{}")
            result = ownership_gate(root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["forbidden_count"], 0)

    def test_ownership_gate_rejects_foreign_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "site/data/watchalong").mkdir(parents=True)
            (root / "site/data/watchalong/manifest.json").write_text("{}")
            target = root / "site/youtube/v1/manifest.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}")
            with self.assertRaisesRegex(Exception, "foreign-owner assets"):
                ownership_gate(root)

    def test_foreign_prefix_contract_is_explicit(self):
        self.assertEqual(FOREIGN_PREFIXES, ("youtube/v1/", "ptt/v1/"))


if __name__ == "__main__":
    unittest.main()
