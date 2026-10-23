import json
import tempfile
import unittest
from pathlib import Path

from ptt_offline.materialize_channel_profile_backend_config import (
    load_config,
    materialize,
)


class ChannelProfileBackendConfigTests(unittest.TestCase):
    def base_config(self):
        return {
            "name": "holoviewer-public-api",
            "compatibility_date": "2026-10-14",
            "vars": {
                "ALLOWED_ORIGIN": "https://holodocchi.com",
                "PTT_PUBLISH_ENABLED": "false",
                "PTT_PUBLISH_MAX_ROWS": "5",
                "TODAY_SUPPORT_COLORS_JSON_0": "stale",
                "UNRELATED_VAR": "keep-me",
            },
            "d1_databases": [{
                "binding": "DB",
                "database_name": "holoviewer-public-v1",
                "database_id": "64e1a0ee-1455-4377-9640-3922e8f4d061",
            }],
            "kv_namespaces": [{"binding": "EXAMPLE_KV", "id": "abc"}],
            "services": [{"binding": "EXAMPLE_SERVICE", "service": "svc"}],
        }

    def support_colors(self):
        rows = [{"channel_id": "UC" + format(i, "022d"), "display_mode": "neutral"} for i in range(66)]
        for i in range(56):
            rows[i].update({
                "display_mode": "solid",
                "color_hex": "#112233",
                "verification_status": "verified",
            })
        rows[56].update({
            "display_mode": "dual_color",
            "color_hexes": ["#112233", "#445566"],
            "verification_status": "community",
            "color_semantics": "2025_6th_fes_penlight",
        })
        return {"schema_version": 1, "fallback": "neutral", "channels": rows}

    def test_materializer_preserves_runtime_contract_and_removes_plaintext_ptt_vars(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "source.json"
            colors = td / "colors.json"
            out = td / "materialized.json"
            src.write_text(json.dumps(self.base_config()), encoding="utf-8")
            colors.write_text(json.dumps(self.support_colors()), encoding="utf-8")

            receipt = materialize(str(src), str(colors), str(out))
            cfg = json.loads(out.read_text(encoding="utf-8"))

            self.assertEqual(cfg["name"], "holoviewer-public-api")
            self.assertEqual(cfg["compatibility_date"], "2026-10-14")
            self.assertEqual(cfg["vars"]["ALLOWED_ORIGIN"], "https://holodocchi.com")
            self.assertEqual(cfg["vars"]["UNRELATED_VAR"], "keep-me")
            self.assertNotIn("PTT_PUBLISH_ENABLED", cfg["vars"])
            self.assertNotIn("PTT_PUBLISH_MAX_ROWS", cfg["vars"])
            self.assertEqual(cfg["kv_namespaces"], [{"binding": "EXAMPLE_KV", "id": "abc"}])
            self.assertEqual(cfg["services"], [{"binding": "EXAMPLE_SERVICE", "service": "svc"}])

            keys = sorted(
                (k for k in cfg["vars"] if k.startswith("TODAY_SUPPORT_COLORS_JSON_")),
                key=lambda x: int(x.rsplit("_", 1)[1]),
            )
            payload = "".join(cfg["vars"][k] for k in keys)
            decoded = json.loads(payload)
            self.assertEqual(len(decoded["channels"]), 66)
            self.assertTrue(all(len(cfg["vars"][k].encode("utf-8")) <= 4000 for k in keys))
            self.assertEqual(receipt["support_color_receipt"], {"rows": 66, "colored": 57, "neutral": 9, "dual": 1})
            self.assertTrue(receipt["allowed_origin_preserved"])

    def test_frontend_assets_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "wrangler.json"
            cfg = self.base_config()
            cfg["assets"] = {"directory": "../site"}
            src.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_config(str(src))

    def test_wrong_d1_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "wrangler.json"
            cfg = self.base_config()
            cfg["d1_databases"][0]["database_name"] = "wrong"
            src.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_config(str(src))


if __name__ == "__main__":
    unittest.main()
