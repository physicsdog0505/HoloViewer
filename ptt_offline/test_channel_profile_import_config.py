import json
import unittest
from pathlib import Path


class ChannelProfileImportConfigTests(unittest.TestCase):
    def test_wrangler_main_resolves_from_config_directory(self):
        config_path = Path(__file__).with_name("channel-profile-import-local.wrangler.json")
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        main = config_path.parent / cfg["main"]
        self.assertTrue(main.is_file(), f"missing Wrangler entrypoint: {main}")


if __name__ == "__main__":
    unittest.main()
