import json, tempfile, unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from ptt_offline.deploy_today_backend_release import load_config, safe_deploy_config, ptt_operational_day, load_support_color_chunks

class TodayBackendReleaseTests(unittest.TestCase):
    def config(self):
        return {
          "name":"holoviewer-public-api",
          "vars":{
            "PTT_PUBLISH_ENABLED":"false",
            "PTT_PUBLISH_MAX_ROWS":"5",
            "TODAY_CADENCE_ENABLED":"false",
            "ALLOWED_ORIGIN":"https://example.test"
          },
          "d1_databases":[{
            "binding":"DB",
            "database_name":"holoviewer-public-v1",
            "database_id":"64e1a0ee-1455-4377-9640-3922e8f4d061"
          }]
        }

    def support_colors(self):
        return {
          "schema_version":1,
          "fallback":"neutral",
          "channels":[
            {"channel_id":"UC"+f"{i:022d}","display_mode":"neutral","verification_status":"verified"}
            for i in range(66)
          ]
        }

    def test_safe_config_never_reintroduces_plaintext_ptt_gate_and_rehydrates_colors(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"wrangler.json"
            colors=Path(td)/"colors.json"
            src.write_text(json.dumps(self.config()),encoding="utf-8")
            colors.write_text(json.dumps(self.support_colors()),encoding="utf-8")
            holder,out=safe_deploy_config(str(src),support_colors_path=str(colors))
            try:
                cfg=json.loads(out.read_text())
                self.assertNotIn("PTT_PUBLISH_ENABLED",cfg["vars"])
                self.assertNotIn("PTT_PUBLISH_MAX_ROWS",cfg["vars"])
                self.assertEqual(cfg["vars"]["TODAY_CADENCE_ENABLED"],"true")
                self.assertEqual(cfg["vars"]["TODAY_DISCOVERY_ENABLED"],"false")
                self.assertEqual(cfg["vars"]["ALLOWED_ORIGIN"],"https://example.test")
                keys=sorted(k for k in cfg["vars"] if k.startswith("TODAY_SUPPORT_COLORS_JSON_"))
                self.assertTrue(keys)
                joined="".join(cfg["vars"][k] for k in keys)
                self.assertEqual(json.loads(joined),self.support_colors())
            finally:
                holder.cleanup()

    def test_support_color_payload_requires_exact_66_unique_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"colors.json"
            path.write_text(json.dumps(self.support_colors()),encoding="utf-8")
            self.assertTrue(load_support_color_chunks(path))
            broken=self.support_colors();broken["channels"]=broken["channels"][:-1]
            path.write_text(json.dumps(broken),encoding="utf-8")
            with self.assertRaises(SystemExit): load_support_color_chunks(path)

    def test_ptt_operational_day_rolls_at_0600_taipei(self):
        tz=ZoneInfo("Asia/Taipei")
        self.assertEqual(ptt_operational_day(datetime(2026,10,16,5,59,tzinfo=tz)),"2026-10-15")
        self.assertEqual(ptt_operational_day(datetime(2026,10,16,6,0,tzinfo=tz)),"2026-10-16")

    def test_release_gate_day_must_not_be_clock_only(self):
        # Regression marker: production gate resolves latest successful provider
        # day from D1 instead of trusting a wall-clock rollover boundary.
        source=Path(__file__).with_name("deploy_today_backend_release.py").read_text(encoding="utf-8")
        self.assertIn("PTT_LAST_DAY=",source)
        self.assertIn("ORDER BY last_success_at DESC LIMIT 1",source)


    def test_cleanup_marker_regex_matches_numeric_count(self):
        source=Path(__file__).with_name("deploy_today_backend_release.py").read_text(encoding="utf-8")
        self.assertIn('r"NONLIVE_DISCOVERY_ROWS=(\\d+)"', source)
        self.assertNotIn('r"NONLIVE_DISCOVERY_ROWS=(\\\\d+)"', source)

    def test_wrong_worker_fails_closed(self):
        cfg=self.config(); cfg["name"]="wrong-worker"
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"wrangler.json"; src.write_text(json.dumps(cfg),encoding="utf-8")
            with self.assertRaises(SystemExit): load_config(str(src))

if __name__=="__main__":
    unittest.main()
