from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
ALIAS_ORIGIN = "https://holoviewer-alias-static-assets.singlebagel.workers.dev"


class AliasStaticOriginTests(unittest.TestCase):
    def test_public_config_uses_dedicated_alias_origin(self):
        config = (ROOT / "site/assets/config.js").read_text(encoding="utf-8")
        self.assertIn(f'aliasStaticBase: "{ALIAS_ORIGIN}"', config)

    def test_csp_allows_dedicated_alias_origin(self):
        headers = (ROOT / "site/_headers").read_text(encoding="utf-8")
        self.assertIn(ALIAS_ORIGIN, headers)

    def test_frontend_tree_does_not_own_alias_dataset(self):
        alias_root = ROOT / "site/data/search/aliases/v1"
        files = [p for p in alias_root.rglob("*") if p.is_file()] if alias_root.exists() else []
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
