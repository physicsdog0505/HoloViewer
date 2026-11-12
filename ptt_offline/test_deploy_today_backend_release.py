import json, tempfile, unittest
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from ptt_offline.deploy_today_backend_release import load_config, safe_deploy_config, ptt_operational_day, recent_clean_publisher_cycle

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

    def test_safe_config_never_reintroduces_plaintext_ptt_gate(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"wrangler.json"
            src.write_text(json.dumps(self.config()),encoding="utf-8")
            colors=Path(td)/"colors.json"
            channels=[]
            for i in range(66):
                row={"channel_id":"UC"+("A"*21)+str(i%10),"display_mode":"neutral"}
                channels.append(row)
            # replace generated ids with exact-length unique values
            channels=[{"channel_id":"UC"+format(i,"022d"),"display_mode":"neutral"} for i in range(66)]
            for i in range(56):
                channels[i].update({"display_mode":"solid","color_hex":"#112233","verification_status":"verified"})
            channels[56].update({"display_mode":"dual_color","color_hexes":["#112233","#445566"],"verification_status":"community","color_semantics":"2025_6th_fes_penlight"})
            colors.write_text(json.dumps({"schema_version":1,"fallback":"neutral","channels":channels}),encoding="utf-8")
            holder,out=safe_deploy_config(str(src),str(colors))
            try:
                cfg=json.loads(out.read_text())
                self.assertNotIn("PTT_PUBLISH_ENABLED",cfg["vars"])
                self.assertNotIn("PTT_PUBLISH_MAX_ROWS",cfg["vars"])
                self.assertEqual(cfg["vars"]["TODAY_CADENCE_ENABLED"],"true")
                self.assertEqual(cfg["vars"]["TODAY_DISCOVERY_ENABLED"],"false")
                self.assertEqual(cfg["vars"]["ALLOWED_ORIGIN"],"https://example.test")
                payload="".join(cfg["vars"][k] for k in sorted(
                    (k for k in cfg["vars"] if k.startswith("TODAY_SUPPORT_COLORS_JSON_")),
                    key=lambda x:int(x.rsplit("_",1)[1])))
                decoded=json.loads(payload)
                self.assertEqual(len(decoded["channels"]),66)
                self.assertTrue(all(
                    len(value.encode("utf-8")) <= 4000
                    for key, value in cfg["vars"].items()
                    if key.startswith("TODAY_SUPPORT_COLORS_JSON_")
                ))
            finally:
                holder.cleanup()


    def test_release_gate_accepts_fresh_owner_noop(self):
        now=datetime(2026,10,16,5,40,0,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            metrics=Path(td)/"minute-metrics.jsonl"
            metrics.write_text(json.dumps({
              "status":"NO_NEW_ROWS",
              "publisher_mode":"OWNER_APPROVED_SEND",
              "observed_at":"2026-10-16T05:39:30+00:00",
              "http_posts":0
            })+"\n",encoding="utf-8")
            row=recent_clean_publisher_cycle(metrics,now=now)
            self.assertEqual(row["status"],"NO_NEW_ROWS")

    def test_release_gate_rejects_stale_or_failed_latest_cycle(self):
        now=datetime(2026,10,16,5,40,0,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            metrics=Path(td)/"minute-metrics.jsonl"
            metrics.write_text(
              json.dumps({"status":"ACK","publisher_mode":"OWNER_APPROVED_SEND","observed_at":"2026-10-16T05:39:00+00:00"})+"\n"+
              json.dumps({"status":"STOP_RECONCILE","observed_at":"2026-10-16T05:39:30+00:00"})+"\n",
              encoding="utf-8")
            with self.assertRaises(SystemExit):
                recent_clean_publisher_cycle(metrics,now=now)
            metrics.write_text(json.dumps({
              "status":"NO_NEW_ROWS","publisher_mode":"OWNER_APPROVED_SEND",
              "observed_at":"2026-10-16T05:00:00+00:00"
            })+"\n",encoding="utf-8")
            with self.assertRaises(SystemExit):
                recent_clean_publisher_cycle(metrics,now=now)

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
